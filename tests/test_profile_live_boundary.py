"""Online production requires installed originals; frozen checks stay offline.

The installation fixture copies reviewed native bytes into a temporary tree.
It tests filesystem/version contracts, never game execution or sampled values.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pdx import cli, config, distribution, version_contracts
from pdx.situated import production_profile as native
from pdx.situated import r2_reader_authority as authority


@pytest.fixture
def installation(tmp_path, monkeypatch):
    root = tmp_path / "installation"
    shutil.copytree(authority.FROZEN_ROOT, root)
    monkeypatch.setattr(config, "ROOT", root)
    monkeypatch.setattr(config, "OUT", tmp_path / "out")
    return root


def test_existing_complete_profile_can_regenerate_without_leaking_owned_backups(installation):
    profile = native.load_profile(native.BASELINE_ROOT)
    distribution.write_profile_outputs(profile)
    root = distribution.profile_output_root()
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    distribution.write_profile_outputs(profile)
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == before
    distribution.check_profile_outputs(profile)


@pytest.mark.parametrize("timing", ["existing", "during-transaction"])
def test_profile_rejects_unowned_same_prefix_file(installation, monkeypatch, timing):
    profile = native.load_profile(native.BASELINE_ROOT)
    distribution.write_profile_outputs(profile)
    root = distribution.profile_output_root()
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    unowned = root / "common/.sitai-generation-external"
    unowned.parent.mkdir(exist_ok=True)
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
        distribution.write_profile_outputs(profile)
    assert {path: path.read_bytes() for path in before} == before
    assert unowned.read_bytes() == b"unowned external bytes\n"
    assert {path for path in root.rglob("*") if path.is_file()} == set(before) | {unowned}


@pytest.mark.parametrize("selected", [None, "1.14.5", "1.15.0", "unknown"])
def test_cli_profile_defaults_follow_strict_version_but_explicit_profile_wins(
    monkeypatch, selected
):
    if selected is None:
        monkeypatch.delenv("V3_CONTRACT_PROFILE", raising=False)
    else:
        monkeypatch.setenv("V3_CONTRACT_PROFILE", selected)
    frozen = native.load_profile(native.BASELINE_ROOT)
    assert cli._production_profile("1.15.0", offline=True) == frozen
    if selected == "unknown":
        with pytest.raises(ValueError, match="合同版本"):
            cli._production_profile(None, offline=True)
    else:
        assert cli._production_profile(None, offline=True) == (
            frozen if selected == "1.15.0" else None
        )


def test_fresh_cli_import_preserves_explicit_profile_over_unknown_environment():
    environment = {**os.environ, "V3_CONTRACT_PROFILE": "unknown"}
    code = (
        "from pdx import cli\n"
        "assert cli._production_profile('1.15.0', offline=True) is not None\n"
        "try:\n"
        "    cli._production_profile(None, offline=True)\n"
        "except ValueError as error:\n"
        "    assert '合同版本' in str(error)\n"
        "else:\n"
        "    raise AssertionError('implicit unknown profile must fail')\n"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", "-c", code],
        cwd=config.REPO,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("relative", sorted(authority.SOURCE_SHA256))
@pytest.mark.parametrize("damage", ["missing", "drift"])
def test_online_profile_requires_every_installed_identity_and_reader_source(
    installation, relative, damage
):
    target = installation / relative
    if damage == "missing":
        target.unlink()
    else:
        target.write_bytes(target.read_bytes() + b"\n# unreviewed installed bytes\n")
    with pytest.raises(ValueError, match="R2 reader authority"):
        cli._production_profile("1.15.0")
    # Absence/drift in an installation cannot contaminate the independent
    # offline contract or force a live read in CI.
    assert cli._production_profile("1.15.0", offline=True) == native.load_profile(
        native.BASELINE_ROOT
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["modgen", "--write"],
        ["modgen", "--check"],
        ["package"],
        ["modguard"],
        ["decision-audit"],
    ],
)
@pytest.mark.parametrize("damage", ["missing-installation", "reader-drift", "version-drift"])
def test_every_online_entry_fails_before_writing_when_installed_inputs_are_invalid(
    installation, arguments, damage, tmp_path, monkeypatch
):
    if damage == "missing-installation":
        monkeypatch.setattr(config, "ROOT", tmp_path / "absent-installation")
    else:
        relative = (
            "launcher/launcher-settings.json"
            if damage == "version-drift"
            else "game/common/diplomatic_actions/01_expel_diplomats.txt"
        )
        target = installation / relative
        if damage == "version-drift":
            document = json.loads(target.read_bytes())
            document["rawVersion"] = "1.15.1"
            target.write_text(json.dumps(document), encoding="utf-8")
        else:
            target.write_bytes(target.read_bytes() + b"\n# installed drift\n")
    result = CliRunner().invoke(cli.app, [*arguments, "--profile", "1.15.0"])
    assert result.exit_code == 1, result.output
    assert "R2 reader authority" in result.output
    assert not config.OUT.exists()


def test_verified_installation_drives_online_chain_and_offline_checks_need_no_installation(
    installation, tmp_path, monkeypatch
):
    runner = CliRunner()
    assert cli._production_profile("1.15.0") == native.load_profile(installation)
    destination = tmp_path / "candidate.zip"
    for arguments in (
        ["modgen", "--write"],
        ["modgen", "--check"],
        ["modguard"],
        ["decision-audit", "--output", str(tmp_path / "online-audit.json")],
        ["package", "--output", str(destination)],
    ):
        result = runner.invoke(cli.app, [*arguments, "--profile", "1.15.0"])
        assert result.exit_code == 0, result.output
    assert destination.is_file()
    before = {
        path: path.read_bytes()
        for path in distribution.profile_output_root().rglob("*")
        if path.is_file()
    }
    monkeypatch.setattr(config, "ROOT", tmp_path / "absent-installation")
    for arguments in (
        ["modguard", "--offline"],
        ["decision-audit", "--offline", "--output", str(tmp_path / "offline-audit.json")],
    ):
        result = runner.invoke(cli.app, [*arguments, "--profile", "1.15.0"])
        assert result.exit_code == 0, result.output
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("operation", ["generate", "package"])
@pytest.mark.parametrize("damage", ["absent", "reader-drift", "profile-identity"])
def test_public_write_apis_cannot_bypass_installed_contract(
    installation, tmp_path, monkeypatch, operation, damage
):
    profile = native.load_profile(native.BASELINE_ROOT)
    target = tmp_path / "candidate.zip"
    target.write_bytes(b"previous complete package")
    if damage == "absent":
        monkeypatch.setattr(config, "ROOT", tmp_path / "missing")
    elif damage == "reader-drift":
        (installation / "game/common/diplomatic_actions/01_expel_diplomats.txt").write_bytes(
            b"unreviewed reader"
        )
    else:
        profile = replace(profile, build_id="unreviewed-build")
    if operation == "generate":
        with pytest.raises(ValueError, match=r"R2 reader authority|profile.*身份不一致"):
            distribution.write_profile_outputs(profile)
    else:
        with pytest.raises(ValueError, match=r"R2 reader authority|profile.*身份不一致"):
            distribution.profile_package(target, profile)
    assert not distribution.profile_output_root().exists()
    assert target.read_bytes() == b"previous complete package"


def test_installed_drift_during_generation_rolls_back_previous_candidate(installation, monkeypatch):
    profile = native.load_profile(native.BASELINE_ROOT)
    distribution.write_profile_outputs(profile)
    root = distribution.profile_output_root()
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    original_replace = distribution.GenerationTransaction.replace
    staged = False

    def drift_after_staging(transaction, files):
        nonlocal staged
        value = original_replace(transaction, files)
        staged = True
        (installation / "game/common/diplomatic_actions/01_expel_diplomats.txt").write_bytes(
            b"installed reader changed during generation"
        )
        return value

    monkeypatch.setattr(distribution.GenerationTransaction, "replace", drift_after_staging)
    with pytest.raises(ValueError, match="R2 reader authority: source drift"):
        distribution.write_profile_outputs(profile)
    assert staged
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("damage", ["reader", "source", "generated-output", "generation-lock"])
def test_drift_after_zip_validation_preserves_previous_package_and_removes_temporary_zip(
    installation, tmp_path, monkeypatch, damage
):
    profile = native.load_profile(native.BASELINE_ROOT)
    distribution.write_profile_outputs(profile)
    destination = tmp_path / "packages" / "candidate.zip"
    destination.parent.mkdir()
    destination.write_bytes(b"previous complete ZIP")
    validate_archive = distribution._validate_archive
    read_bytes = Path.read_bytes
    source = config.REPO / "src/pdx/situated/r2_reader_authority.py"
    source_copy = tmp_path / "source-view.py"
    source_copy.write_bytes(source.read_bytes())

    def read_source_view(path):
        # Model a changed source read using real temporary bytes, without
        # modifying shared repository sources during concurrent tests.
        return read_bytes(source_copy) if path == source else read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", read_source_view)

    def drift_after_validation(*args, **kwargs):
        validate_archive(*args, **kwargs)
        target = {
            "reader": installation / "game/common/diplomatic_actions/01_expel_diplomats.txt",
            "source": source_copy,
            "generated-output": distribution.profile_output_root() / distribution.METADATA_NAME,
            "generation-lock": distribution.profile_output_root() / "generation-lock.json",
        }[damage]
        target.write_bytes(target.read_bytes() + b"\nchanged while assembling ZIP\n")

    monkeypatch.setattr(distribution, "_validate_archive", drift_after_validation)
    with pytest.raises(ValueError, match=r"source drift|漂移"):
        distribution.profile_package(destination, profile)
    assert destination.read_bytes() == b"previous complete ZIP"
    assert list(destination.parent.iterdir()) == [destination]


@pytest.mark.parametrize("damage", ["source", "extra-output"])
def test_change_during_final_profile_live_verification_refuses_transaction(
    installation, tmp_path, monkeypatch, damage
):
    profile = native.load_profile(native.BASELINE_ROOT)
    distribution.write_profile_outputs(profile)
    root = distribution.profile_output_root()
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    source = config.REPO / "src/pdx/situated/network_profile.py"
    view = tmp_path / "changed-source.py"
    view.write_bytes(b"changed during final installation verification\n")
    extra = root / "common/unexpected.txt"
    opened = Path.open
    changed = False

    def open_view(path, *args, **kwargs):
        return opened(view if changed and path == source else path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_view)
    verify_installation = distribution.check_profile_installation
    calls = 0

    def drift_during_final_verification(selected):
        nonlocal calls, changed
        result = verify_installation(selected)
        calls += 1
        if calls == 2:
            if damage == "source":
                changed = True
            else:
                extra.write_bytes(b"unrelated concurrent output\n")
        return result

    monkeypatch.setattr(distribution, "check_profile_installation", drift_during_final_verification)
    with pytest.raises(ValueError, match="漂移"):
        distribution.write_profile_outputs(profile)
    assert calls == 2
    assert changed if damage == "source" else extra.is_file()
    changed = False
    assert {path: path.read_bytes() for path in before} == before
    # The transaction restores its owned files. Unknown concurrent files must
    # be reported and preserved, not silently deleted to manufacture a match.
    if damage == "extra-output":
        assert extra.read_bytes() == b"unrelated concurrent output\n"


def test_profile_generation_binds_source_before_compilation(installation, tmp_path, monkeypatch):
    profile = native.load_profile(native.BASELINE_ROOT)
    distribution.write_profile_outputs(profile)
    root = distribution.profile_output_root()
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    source = config.REPO / "src/pdx/situated/network_profile.py"
    view = tmp_path / "changed-source.py"
    view.write_bytes(b"changed immediately after compilation\n")
    opened = Path.open
    changed = False

    def open_view(path, *args, **kwargs):
        return opened(view if changed and path == source else path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_view)
    build = distribution.profile_outputs

    def drift_after_build(*args, **kwargs):
        nonlocal changed
        result = build(*args, **kwargs)
        changed = True
        return result

    monkeypatch.setattr(distribution, "profile_outputs", drift_after_build)
    with pytest.raises(ValueError, match="构建期间源码发生漂移"):
        distribution.write_profile_outputs(profile)
    assert changed
    changed = False
    assert {path: path.read_bytes() for path in before} == before


@pytest.fixture(autouse=True)
def _historical_1150_contract():
    """Keep the exact archived witness under its original version identity."""
    with version_contracts.select_version("1.15.0"):
        yield
