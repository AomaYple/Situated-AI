"""从现有 v3 入口盘点合成安装根。"""

import json
import os
import shutil
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from typer.testing import CliRunner

from pdx import cli, config, input_inventory, version_contracts

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


def _install_identity(
    root: Path, monkeypatch: pytest.MonkeyPatch, *, valid: bool = True
) -> set[str]:
    hashes = {}
    for relative in version_contracts.INSTALLATION_IDENTITY_SHA256:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"synthetic-{relative}".encode())
        hashes[relative] = sha256(path.read_bytes()).hexdigest()
    launcher = root / "launcher/launcher-settings.json"
    launcher.write_text(
        json.dumps(
            {
                "gameId": "victoria3",
                "rawVersion": version_contracts.CURRENT_VERSION if valid else "1.15.0",
                "version": version_contracts.CURRENT_VERSION,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(version_contracts, "INSTALLATION_IDENTITY_SHA256", hashes)
    return set(hashes)


@pytest.mark.parametrize(
    ("matching", "denied", "unrepresentable"),
    [(True, False, False), (False, False, False), (True, True, False), (True, False, True)],
)
def test_input_inventory_reports_only_metadata_and_checks_version_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    matching: bool,
    denied: bool,
    unrepresentable: bool,
) -> None:
    anchor_path = "game/common/ai_strategies/00_default_strategy.txt"
    anchor = tmp_path / anchor_path
    anchor.parent.mkdir(parents=True)
    anchor.write_bytes(b"fixture_strategy = {}")
    extra = tmp_path / "some-new-format"
    extra.write_bytes(b"unique-original-bytes")
    identities = _install_identity(tmp_path, monkeypatch)
    (tmp_path / "empty").mkdir()

    expected_version = version_contracts.CURRENT_VERSION
    contract = version_contracts.VERSION_SPECS[expected_version]
    expected_anchor = sha256(anchor.read_bytes() if matching else b"changed").hexdigest()
    monkeypatch.setitem(
        version_contracts.VERSION_SPECS,
        expected_version,
        replace(contract, default_strategy_sha256=expected_anchor),
    )
    monkeypatch.delenv(version_contracts.ENVIRONMENT_VARIABLE, raising=False)
    monkeypatch.setattr(config, "ROOT", tmp_path / "empty" / "..")
    if denied:
        open_verified = input_inventory._open_verified

        def fail_extra_file(path: Path) -> int:
            if path == extra:
                raise PermissionError("fixture")
            return open_verified(path)

        monkeypatch.setattr(input_inventory, "_open_verified", fail_extra_file)
    malformed_name = "unrepresentable-\udcff"
    if unrepresentable:
        scandir = os.scandir
        entry = cast("os.DirEntry[str]", SimpleNamespace(name=malformed_name, path=extra))

        @contextmanager
        def scandir_with_surrogate(path: Path) -> Iterator[Iterator[os.DirEntry[str]]]:
            with scandir(path) as entries:
                yield iter([*entries, entry]) if path == tmp_path else entries

        monkeypatch.setattr(os, "scandir", scandir_with_surrogate)

    result = CliRunner().invoke(cli.app, ["input-inventory"])

    assert result.exit_code == (
        0 if matching and not denied and not unrepresentable else cli.EXIT_FAILED
    ), result.output
    payload = json.loads(result.stdout)
    assert payload["scan_status"] == ("partial" if denied or unrepresentable else "complete")
    assert payload["expected_version"] == expected_version
    assert payload["version_anchor"] == {"path": anchor_path, "matched": matching}
    if unrepresentable:
        assert payload["file_set_sha256"] is None
        assert payload["unrecorded_paths"] == [r"unrepresentable-\udcff"]
        assert payload["diagnostic_codes"] == ["invalid_path"]
        assert b"\\\\udcff" in result.stdout.encode("utf-8")
    else:
        assert payload["file_set_sha256"]
        assert payload["unrecorded_paths"] == []
    records = {row["path"]: row for row in payload["records"]}
    assert set(records) == identities | {anchor_path, "some-new-format"}
    assert records["some-new-format"] == {
        "path": "some-new-format",
        "sha256": None if denied else sha256(b"unique-original-bytes").hexdigest(),
        "size": 21,
        "category": "unknown",
        "read_status": "failed" if denied else "read",
        "diagnostic_codes": ["read_failed"] if denied else [],
    }
    assert "unique-original-bytes" not in result.stdout
    assert str(tmp_path) not in result.stdout
    assert extra.read_bytes() == b"unique-original-bytes"


@pytest.mark.parametrize("historical_contract", [True, False])
def test_input_inventory_rejects_noncurrent_contract_or_installation_before_scanning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, historical_contract: bool
) -> None:
    _install_identity(tmp_path, monkeypatch, valid=historical_contract)
    (tmp_path / "game").mkdir()
    monkeypatch.setattr(config, "ROOT", tmp_path)
    if historical_contract:
        monkeypatch.setenv(version_contracts.ENVIRONMENT_VARIABLE, "1.15.0")
    else:
        monkeypatch.delenv(version_contracts.ENVIRONMENT_VARIABLE, raising=False)

    result = CliRunner().invoke(cli.app, ["input-inventory"])

    assert result.exit_code == cli.EXIT_USAGE, result.output
    assert result.stdout == ""
    assert version_contracts.CURRENT_VERSION in result.stderr


@pytest.mark.parametrize(
    ("change", "diagnostic"),
    [
        ("launcher", "installation_identity_source_changed"),
        ("revision", "installation_identity_source_changed"),
        ("root", "installation_root_changed"),
    ],
)
def test_input_inventory_binds_preflight_identity_to_the_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str, diagnostic: str
) -> None:
    root = tmp_path / "installation"
    anchor = root / "game/common/ai_strategies/00_default_strategy.txt"
    anchor.parent.mkdir(parents=True)
    anchor.write_bytes(b"fixture_strategy = {}")
    _install_identity(root, monkeypatch)
    baseline = version_contracts.contract(version_contracts.CURRENT_VERSION)
    monkeypatch.setitem(
        version_contracts.VERSION_SPECS,
        baseline.version,
        replace(baseline, default_strategy_sha256=sha256(anchor.read_bytes()).hexdigest()),
    )
    monkeypatch.delenv(version_contracts.ENVIRONMENT_VARIABLE, raising=False)
    monkeypatch.setattr(config, "ROOT", root)
    verify = version_contracts.verify_installation_identity

    def replace_after_verification(path: Path) -> version_contracts.VerifiedInstallation:
        verified = verify(path)
        if change == "root":
            archived = root.with_name("previous-root")
            root.rename(archived)
            shutil.copytree(archived, root)
        elif change == "launcher":
            launcher = root / "launcher/launcher-settings.json"
            launcher.write_bytes(
                launcher.read_bytes().replace(
                    f'"rawVersion": "{version_contracts.CURRENT_VERSION}"'.encode(),
                    b'"rawVersion": "0.0.0"',
                )
            )
        else:
            (root / "caligula_rev.txt").write_bytes(b"replaced revision")
        return verified

    monkeypatch.setattr(
        version_contracts, "verify_installation_identity", replace_after_verification
    )
    result = CliRunner().invoke(cli.app, ["input-inventory"])

    assert result.exit_code == cli.EXIT_FAILED, result.output
    payload = json.loads(result.stdout)
    assert payload["scan_status"] in {"partial", "failed"}
    assert payload["file_set_sha256"] is None
    assert diagnostic in payload["diagnostic_codes"]
    if change == "root":
        assert payload["records"] == []
        assert payload["blocked_directories"] == ["."]
    else:
        assert payload["version_anchor"]["matched"]
        affected = "launcher/launcher-settings.json" if change == "launcher" else "caligula_rev.txt"
        records = {record["path"]: record for record in payload["records"]}
        assert diagnostic in records[affected]["diagnostic_codes"]
