"""存档迁移输入盘点的纯 Python 测试。"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import pytest

from pdx import save_migration

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _save(path: Path, *, version: str, observer: bool = True, invalid: bool = False) -> None:
    rule = 'settings={ "" }' if invalid else "settings={}"
    player = (
        "player_manager={database={}}" if observer else "player_manager={database={1={country=42}}}"
    )
    path.write_bytes(f'SAV0100\nversion="{version}" game_date=1836.4.1 {rule}\n{player}'.encode())


def test_scan_groups_versions_and_keeps_relative_sha(tmp_path: Path):
    _save(tmp_path / "current.v3", version="1.14.5")
    nested = tmp_path / "nested"
    nested.mkdir()
    _save(nested / "old.v3", version="1.14.4")

    inventory = save_migration.scan(tmp_path, expected_version="1.14.5")

    assert inventory.versions == {"1.14.4": 1, "1.14.5": 1}
    assert len(inventory.observer_entries) == 2
    assert len(inventory.invalid_rule_entries) == 0
    assert [entry.path for entry in inventory.entries] == ["current.v3", "nested/old.v3"]
    old = inventory.entries[1]
    assert old in inventory.cross_version_entries
    assert old in inventory.eligible_upgrade_entries
    assert old.sha256 == hashlib.sha256((nested / "old.v3").read_bytes()).hexdigest()


def test_invalid_rules_are_not_upgrade_candidates(tmp_path: Path):
    _save(tmp_path / "bad.v3", version="1.14.4", invalid=True)
    _save(tmp_path / "player.v3", version="1.14.4", observer=False)

    inventory = save_migration.scan(tmp_path, expected_version="1.14.5")

    assert len(inventory.cross_version_entries) == 2
    assert len(inventory.invalid_rule_entries) == 1
    assert inventory.eligible_upgrade_entries == ()


def test_legacy_mod_state_is_not_upgrade_candidate(tmp_path: Path):
    path = tmp_path / "legacy.v3"
    path.write_bytes(
        b'SAV0100\nversion="1.14.4" game_date=1841.1.2 settings={}\n'
        b"player_manager={database={}} je_sitai_ru_defeat_window={}"
    )

    inventory = save_migration.scan(tmp_path, expected_version="1.14.5")

    assert len(inventory.legacy_state_entries) == 1
    assert inventory.eligible_upgrade_entries == ()


def test_parse_errors_are_retained_and_reported(tmp_path: Path):
    broken = tmp_path / "broken.v3"
    broken.write_bytes(b"not a save")

    inventory = save_migration.scan(tmp_path, expected_version="1.14.5")
    payload = inventory.to_dict()

    assert payload["total"] == 1
    assert payload["parse_errors"] == 1
    assert payload["entries"][0]["path"] == "broken.v3"
    assert payload["entries"][0]["sha256"] == hashlib.sha256(b"not a save").hexdigest()
    assert "parse_error" in payload["entries"][0]


def test_dump_json_is_utf8_lf_and_round_trips(tmp_path: Path):
    _save(tmp_path / "save.v3", version="1.14.5")
    inventory = save_migration.scan(tmp_path, expected_version="1.14.5")
    output = tmp_path / "report.json"
    save_migration.dump_json(inventory, output)

    raw = output.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in raw
    assert json.loads(raw.decode("utf-8"))["total"] == 1
