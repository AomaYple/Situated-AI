"""从现有 v3 入口盘点合成安装根。"""

import json
from dataclasses import replace
from hashlib import sha256
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from pdx import cli, config, input_inventory, version_contracts

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(("matching", "denied"), [(True, False), (False, False), (True, True)])
def test_input_inventory_reports_only_metadata_and_checks_version_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, matching: bool, denied: bool
) -> None:
    anchor_path = "game/common/ai_strategies/00_default_strategy.txt"
    anchor = tmp_path / anchor_path
    anchor.parent.mkdir(parents=True)
    anchor.write_bytes(b"fixture_strategy = {}")
    extra = tmp_path / "some-new-format"
    extra.write_bytes(b"unique-original-bytes")

    expected_version = version_contracts.CURRENT_VERSION
    contract = version_contracts.VERSION_SPECS[expected_version]
    expected_anchor = sha256(anchor.read_bytes() if matching else b"changed").hexdigest()
    monkeypatch.setitem(
        version_contracts.VERSION_SPECS,
        expected_version,
        replace(contract, default_strategy_sha256=expected_anchor),
    )
    monkeypatch.delenv(version_contracts.ENVIRONMENT_VARIABLE, raising=False)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    if denied:
        open_verified = input_inventory._open_verified

        def fail_extra_file(path: Path) -> int:
            if path == extra:
                raise PermissionError("fixture")
            return open_verified(path)

        monkeypatch.setattr(input_inventory, "_open_verified", fail_extra_file)

    result = CliRunner().invoke(cli.app, ["input-inventory"])

    assert result.exit_code == (0 if matching and not denied else cli.EXIT_FAILED), result.output
    payload = json.loads(result.stdout)
    assert payload["scan_status"] == ("partial" if denied else "complete")
    assert payload["expected_version"] == expected_version
    assert payload["version_anchor"] == {"path": anchor_path, "matched": matching}
    assert payload["file_set_sha256"]
    records = {row["path"]: row for row in payload["records"]}
    assert set(records) == {anchor_path, "some-new-format"}
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
