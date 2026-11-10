"""Complete compatibility writes retain independent live and frozen boundaries."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from pdx import config, decisions, distribution, version_contracts


@pytest.fixture(autouse=True)
def selected_version():
    with version_contracts.select_version("1.15.0"):
        yield


@pytest.fixture(scope="module")
def complete_inputs():
    with version_contracts.select_version("1.15.0"):
        return distribution.package_inputs(include_engineering_metadata=True)


@pytest.fixture
def compatibility_tree(tmp_path, monkeypatch, complete_inputs):
    target = tmp_path / "compatibility"
    monkeypatch.setattr(decisions, "product_path", lambda: target)
    # Reuse a complete, genuinely generated input bundle. The final live
    # verifier, source lock, exact tree check and archive validator stay real.
    monkeypatch.setattr(distribution, "package_inputs", lambda **_kwargs: complete_inputs)
    distribution.write_compatibility_outputs()
    return target


@pytest.mark.integration
@pytest.mark.parametrize("damage", ["exe", "native", "source", "output", "lock"])
def test_final_compatibility_zip_boundary_rejects_drift(
    compatibility_tree, tmp_path, monkeypatch, damage
):
    destination = tmp_path / "packages/candidate.zip"
    destination.parent.mkdir()
    destination.write_bytes(b"previous complete ZIP")
    view = tmp_path / "changed-view"
    view.write_bytes(b"changed after archive validation\n")
    target = {
        "exe": config.GAME.parent / "binaries/victoria3.exe",
        "native": config.GAME / "common/ai_strategies/00_default_strategy.txt",
        "source": config.REPO / "src/pdx/situated/compiler.py",
        "output": compatibility_tree / distribution.METADATA_NAME,
        "lock": compatibility_tree / "generation-lock.json",
    }[damage]
    opened = Path.open
    changed = False

    def open_view(path, *args, **kwargs):
        return opened(view if changed and path == target else path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_view)
    validate_archive = distribution._validate_archive

    def drift_after_validation(*args, **kwargs):
        nonlocal changed
        result = validate_archive(*args, **kwargs)
        changed = True
        return result

    monkeypatch.setattr(distribution, "_validate_archive", drift_after_validation)
    with pytest.raises(ValueError, match=r"漂移|不一致"):
        distribution.package(destination)
    assert destination.read_bytes() == b"previous complete ZIP"
    assert list(destination.parent.iterdir()) == [destination]


@pytest.mark.integration
@pytest.mark.parametrize("damage", ["exe", "native"])
def test_final_compatibility_generation_live_drift_rolls_back(
    compatibility_tree, tmp_path, monkeypatch, damage
):
    before = {path: path.read_bytes() for path in compatibility_tree.rglob("*") if path.is_file()}
    view = tmp_path / "changed-view"
    view.write_bytes(b"changed after generation lock validation\n")
    target = (
        config.GAME.parent / "binaries/victoria3.exe"
        if damage == "exe"
        else config.GAME / "common/ai_strategies/00_default_strategy.txt"
    )
    opened = Path.open
    changed = False

    def open_view(path, *args, **kwargs):
        return opened(view if changed and path == target else path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_view)
    check_lock = distribution.check_generation_lock

    def drift_after_lock():
        nonlocal changed
        check_lock()
        changed = True

    monkeypatch.setattr(distribution, "check_generation_lock", drift_after_lock)
    with pytest.raises(ValueError, match=r"漂移|不一致"):
        distribution.write_compatibility_outputs()
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.integration
@pytest.mark.parametrize("damage", ["source", "output", "lock"])
def test_change_during_final_live_verification_rolls_back(
    compatibility_tree, tmp_path, monkeypatch, damage
):
    before = {path: path.read_bytes() for path in compatibility_tree.rglob("*") if path.is_file()}
    target = {
        "source": config.REPO / "src/pdx/situated/compiler.py",
        "output": compatibility_tree / distribution.METADATA_NAME,
        "lock": compatibility_tree / "generation-lock.json",
    }[damage]
    view = tmp_path / "changed-view"
    view.write_bytes(b"changed during final live verification\n")
    opened = Path.open
    changed = False

    def open_view(path, *args, **kwargs):
        return opened(view if changed and path == target else path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_view)
    verify_live = distribution.verify_compatibility_installation

    def drift_during_live_verification():
        nonlocal changed
        verify_live()
        changed = True

    monkeypatch.setattr(
        distribution, "verify_compatibility_installation", drift_during_live_verification
    )
    with pytest.raises(ValueError, match="漂移"):
        distribution.write_compatibility_outputs()
    changed = False
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.skipif(os.name != "nt", reason="Windows junction contract")
@pytest.mark.parametrize("placement", ["root", "parent", "nested"])
@pytest.mark.parametrize(
    "entrypoint", ["scan", "compatibility-write", "profile-write", "profile-check"]
)
def test_isolated_output_apis_reject_real_junction(tmp_path, monkeypatch, placement, entrypoint):
    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "sentinel.txt"
    sentinel.write_bytes(b"external original\n")
    root = tmp_path / "candidate"
    link = root
    if placement == "parent":
        root = root / "nested"
    elif placement == "nested":
        root.mkdir()
        link = root / "nested"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(external)],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    try:
        # Isolate the output-boundary contract from compilation and installation
        # checks. The real shared scanner must reject before any transaction.
        files = {"common/current.txt": "current = yes\n"}
        monkeypatch.setattr(decisions, "product_path", lambda: root)
        monkeypatch.setattr(distribution, "package_inputs", lambda **_kwargs: (None, None, files))
        monkeypatch.setattr(distribution, "_release_files", dict)
        monkeypatch.setattr(distribution, "check_profile_installation", lambda profile: profile)
        monkeypatch.setattr(distribution, "profile_outputs", lambda *_args, **_kwargs: files)
        monkeypatch.setattr(distribution, "profile_generation_lock", lambda *_args: "{}\n")
        profile = distribution.production_profile.load_profile(
            distribution.production_profile.BASELINE_ROOT
        )
        operation = {
            "scan": lambda: distribution._profile_directory_files(root),
            "compatibility-write": distribution.write_compatibility_outputs,
            "profile-write": lambda: distribution.write_profile_outputs(profile, root=root),
            "profile-check": lambda: distribution.check_profile_outputs(profile, root=root),
        }[entrypoint]
        with pytest.raises(ValueError, match="重解析点"):
            operation()
        assert sentinel.read_bytes() == b"external original\n"
        assert list(external.iterdir()) == [sentinel]
    finally:
        # Remove the checked junction itself; never recurse into its target.
        link.rmdir()
