"""Current standard writes retain independent live and frozen boundaries."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from pdx import config, decisions, distribution

if TYPE_CHECKING:
    from collections.abc import Callable

# Current R2 bureaucracy evidence, outside the legacy compatibility read set.
R2_READER_SOURCE = "common/scripted_buttons/scripted_buttons.md"
R2_DRIFT_MESSAGE = r"R2 reader authority: source drift .*scripted_buttons\.md"


@pytest.fixture(scope="module")
def complete_inputs():
    return distribution.package_inputs(include_engineering_metadata=True)


@pytest.fixture
def standard_tree(tmp_path, monkeypatch, complete_inputs):
    target = tmp_path / "standard"
    monkeypatch.setattr(decisions, "product_path", lambda: target)
    # Reuse a complete, genuinely generated input bundle. The final live
    # verifier, source lock, exact tree check and archive validator stay real.
    monkeypatch.setattr(distribution, "package_inputs", lambda **_kwargs: complete_inputs)
    distribution.write_standard_outputs()
    return target


@pytest.mark.integration
def test_existing_complete_standard_tree_regenerates_exactly(standard_tree):
    before = {path: path.read_bytes() for path in standard_tree.rglob("*") if path.is_file()}
    distribution.write_standard_outputs()
    assert {
        path: path.read_bytes() for path in standard_tree.rglob("*") if path.is_file()
    } == before
    distribution.check_generation_lock()


@pytest.mark.integration
@pytest.mark.parametrize("timing", ["existing", "during-transaction"])
def test_standard_rejects_unowned_same_prefix_file(standard_tree, monkeypatch, timing):
    before = {path: path.read_bytes() for path in standard_tree.rglob("*") if path.is_file()}
    unowned = standard_tree / "common/.sitai-generation-external"
    if timing == "existing":
        unowned.write_bytes(b"unowned external bytes\n")
    else:
        replace_files = distribution.GenerationTransaction.replace

        def inject(transaction, files):
            replace_files(transaction, files)
            assert transaction.temporary_paths
            unowned.write_bytes(b"unowned external bytes\n")

        monkeypatch.setattr(distribution.GenerationTransaction, "replace", inject)
    with pytest.raises(ValueError, match=r"额外文件|文件集合.*漂移"):
        distribution.write_standard_outputs()
    assert {path: path.read_bytes() for path in before} == before
    assert unowned.read_bytes() == b"unowned external bytes\n"
    assert {path for path in standard_tree.rglob("*") if path.is_file()} == set(before) | {unowned}


@pytest.mark.integration
@pytest.mark.parametrize("damage", ["exe", "native", "r2-reader", "source", "output", "lock"])
def test_final_standard_zip_boundary_rejects_drift(standard_tree, tmp_path, monkeypatch, damage):
    destination = tmp_path / "packages/candidate.zip"
    destination.parent.mkdir()
    destination.write_bytes(b"previous complete ZIP")
    view = tmp_path / "changed-view"
    view.write_bytes(b"changed after archive validation\n")
    target = {
        "exe": config.GAME.parent / "binaries/victoria3.exe",
        "native": config.GAME / "common/ai_strategies/00_default_strategy.txt",
        "r2-reader": config.GAME / R2_READER_SOURCE,
        "source": config.REPO / "src/pdx/situated/compiler.py",
        "output": standard_tree / distribution.METADATA_NAME,
        "lock": standard_tree / "generation-lock.json",
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
    expected_error = R2_DRIFT_MESSAGE if damage == "r2-reader" else r"漂移|不一致"
    with pytest.raises(ValueError, match=expected_error):
        distribution.package(destination)
    assert changed
    assert destination.read_bytes() == b"previous complete ZIP"
    assert list(destination.parent.iterdir()) == [destination]


@pytest.mark.integration
@pytest.mark.parametrize("damage", ["exe", "native", "r2-reader"])
def test_final_standard_generation_live_drift_rolls_back(
    standard_tree, tmp_path, monkeypatch, damage
):
    before = {path: path.read_bytes() for path in standard_tree.rglob("*") if path.is_file()}
    view = tmp_path / "changed-view"
    view.write_bytes(b"changed after generation lock validation\n")
    target = {
        "exe": config.GAME.parent / "binaries/victoria3.exe",
        "native": config.GAME / "common/ai_strategies/00_default_strategy.txt",
        "r2-reader": config.GAME / R2_READER_SOURCE,
    }[damage]
    opened = Path.open
    changed = False

    def open_view(path, *args, **kwargs):
        return opened(view if changed and path == target else path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_view)
    check_lock = distribution.check_generation_lock

    def drift_after_lock(*args, **kwargs):
        nonlocal changed
        check_lock(*args, **kwargs)
        changed = True

    monkeypatch.setattr(distribution, "check_generation_lock", drift_after_lock)
    expected_error = R2_DRIFT_MESSAGE if damage == "r2-reader" else r"漂移|不一致"
    with pytest.raises(ValueError, match=expected_error):
        distribution.write_standard_outputs()
    assert changed
    assert {
        path: path.read_bytes() for path in standard_tree.rglob("*") if path.is_file()
    } == before


@pytest.mark.integration
@pytest.mark.parametrize("damage", ["source", "output", "lock"])
def test_change_during_final_live_verification_rolls_back(
    standard_tree, tmp_path, monkeypatch, damage
):
    before = {path: path.read_bytes() for path in standard_tree.rglob("*") if path.is_file()}
    target = {
        "source": config.REPO / "src/pdx/situated/compiler.py",
        "output": standard_tree / distribution.METADATA_NAME,
        "lock": standard_tree / "generation-lock.json",
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
        distribution.write_standard_outputs()
    assert changed
    changed = False
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.skipif(os.name != "nt", reason="Windows junction contract")
@pytest.mark.parametrize("placement", ["root", "parent", "nested"])
@pytest.mark.parametrize(
    "entrypoint",
    ["scan", "standard-write"],
)
def test_isolated_output_apis_reject_real_junction(tmp_path, monkeypatch, placement, entrypoint):
    external = tmp_path / "external"
    external.mkdir()
    preserved_file = external / "sentinel.txt"
    preserved_file.write_bytes(b"external original\n")
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
        operations: dict[str, Callable[[], object]] = {
            "scan": lambda: distribution._profile_directory_files(root),
            "standard-write": distribution.write_standard_outputs,
        }
        with pytest.raises(ValueError, match="重解析点"):
            operations[entrypoint]()
        assert preserved_file.read_bytes() == b"external original\n"
        assert list(external.iterdir()) == [preserved_file]
    finally:
        # Remove the checked junction itself; never recurse into its target.
        link.rmdir()
