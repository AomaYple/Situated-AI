"""独立版本盘点：字节身份、未完成状态、国家分母与原始位置。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from pdx.situated.version_inventory import (
    CONTENT_ROOTS,
    IDENTITY_PATHS,
    REQUIRED_ROOTS,
    canonical_json,
    inventory_installation,
)

if TYPE_CHECKING:
    from pathlib import Path


def _write(root: Path, relative: str, text: str | bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
    return path


@pytest.fixture
def installation(tmp_path: Path) -> Path:
    root = tmp_path / "game-installation"
    for relative in (*CONTENT_ROOTS, *REQUIRED_ROOTS):
        (root / relative).mkdir(parents=True, exist_ok=True)
    for relative in IDENTITY_PATHS:
        _write(root, relative, "fixture-build\n")
    _write(
        root,
        "launcher/launcher-settings.json",
        json.dumps({"gameId": "victoria3", "rawVersion": "1.15.0"}),
    )
    _write(
        root,
        "game/localization/english/native_l_english.yml",
        '\ufeffl_english:\n native:0 "Native"\n',
    )
    _write(
        root,
        "game/common/country_definitions/base.txt",
        "@variable = 1\nAAA = { country_type = recognized }\nBBB = { country_type = decentralized }\n",
    )
    _write(
        root,
        "game/common/strategies/base.txt",
        "strategy = {\n ai_weight = { value = 10 }\n weight = 1\n weight = 2\n}\n",
    )
    return root


def test_raw_bytes_and_repeatable_identity(installation: Path) -> None:
    first = inventory_installation(installation)
    assert first["status"] == "static_inventory_complete_semantics_unknown"
    assert canonical_json(first) == canonical_json(inventory_installation(installation))
    file = next(
        record for record in first["files"] if record["path"].endswith("native_l_english.yml")
    )
    assert file["sha256"] == hashlib.sha256((installation / file["path"]).read_bytes()).hexdigest()
    assert file["bytes"] == len((installation / file["path"]).read_bytes())
    _write(
        installation,
        "game/localization/english/native_l_english.yml",
        'l_english:\n native:0 "Native"\n',
    )
    second = inventory_installation(installation)
    assert first["inventory_sha256"] != second["inventory_sha256"]


def test_missing_root_and_missing_identity_are_visible(installation: Path) -> None:
    (installation / "game/events").rmdir()
    (installation / "caligula_rev.txt").unlink()
    result = inventory_installation(installation)
    assert result["status"] == "incomplete"
    assert {"kind": "missing_root", "path": "game/events"} in result["failures"]
    assert {"kind": "missing_identity_file", "path": "caligula_rev.txt"} in result["failures"]


def test_parser_failure_keeps_partial_sources(installation: Path) -> None:
    _write(installation, "game/events/broken.txt", "event = {\n ai_chance = 2\n")
    result = inventory_installation(installation)
    assert result["status"] == "incomplete"
    assert any(
        failure["kind"] == "parse" and failure["path"] == "game/events/broken.txt"
        for failure in result["failures"]
    )
    source = next(
        candidate for candidate in result["consumer_candidates"] if candidate["key"] == "ai_chance"
    )
    assert source["line"] == 2
    assert source["semantic_status"] == "unknown"


def test_duplicate_fields_retain_order_and_exact_ast_addresses(installation: Path) -> None:
    result = inventory_installation(installation)
    duplicate = next(group for group in result["duplicate_fields"] if group["key"] == "weight")
    assert [source["line"] for source in duplicate["occurrences"]] == [3, 4]
    assert [source["address"] for source in duplicate["occurrences"]] == [[0, 1], [0, 2]]
    candidates = [
        candidate for candidate in result["consumer_candidates"] if candidate["key"] == "weight"
    ]
    assert [candidate["scalar"] for candidate in candidates] == ["1", "2"]
    assert all(candidate["parents"] == ["strategy"] for candidate in candidates)
    raw = (installation / duplicate["path"]).read_bytes()
    assert all(source["sha256"] == hashlib.sha256(raw).hexdigest() for source in candidates)
    assert raw.decode().splitlines()[candidates[1]["line"] - 1].strip() == "weight = 2"


def test_country_universe_includes_decentralized_dlc_and_unimplemented(installation: Path) -> None:
    _write(
        installation,
        "game/dlc/test/common/country_definitions/extra.txt",
        "CCC = { country_type = unrecognized }\nAAA = { country_type = recognized }\n",
    )
    result = inventory_installation(installation)
    universe = result["actor_universe"]
    assert universe["actors"] == ["AAA", "BBB", "CCC"]
    assert len(universe["definitions"]) == 4
    assert all(definition["coverage_status"] == "unknown" for definition in universe["definitions"])
    assert universe["duplicate_actor_definitions"][0]["actor"] == "AAA"
    assert universe["excluded_definitions"] == [
        {
            "key": "@variable",
            "path": "game/common/country_definitions/base.txt",
            "line": 1,
            "reason": "script_variable_not_country_definition",
        }
    ]
    assert universe["runtime_actor_set"].startswith("unknown")


def test_scan_includes_non_ai_consumers_and_engine_sources(installation: Path) -> None:
    _write(installation, "game/gui/panel.gui", "panel = { chance = 0.5 }\n")
    _write(installation, "jomini/common/utility.txt", "utility = { score = 4 }\n")
    _write(
        installation,
        "game/map_data/custom.txt",
        "unclassified_reader = { arbitrary_field = yes }\n",
    )
    result = inventory_installation(installation)
    assert {candidate["path"] for candidate in result["consumer_candidates"]} >= {
        "game/gui/panel.gui",
        "jomini/common/utility.txt",
    }
    assert {field["key"] for field in result["field_index"]} >= {
        "unclassified_reader",
        "arbitrary_field",
    }
    assert result["scope"]["consumer_denominator_status"].startswith("unknown")


def test_exclusions_are_explicit_and_original_tree_is_read_only(installation: Path) -> None:
    asset = _write(installation, "game/gfx/picture.dds", b"\x00\x00asset")
    before = {
        path.relative_to(installation): path.read_bytes()
        for path in installation.rglob("*")
        if path.is_file()
    }
    result = inventory_installation(installation)
    assert {
        "path": "game/gfx/picture.dds",
        "reason": "unlisted_suffix",
        "suffix": ".dds",
    } in result["excluded_files"]
    assert asset.read_bytes() == b"\x00\x00asset"
    assert before == {
        path.relative_to(installation): path.read_bytes()
        for path in installation.rglob("*")
        if path.is_file()
    }


def test_no_fallback_to_old_version_or_language_list(installation: Path) -> None:
    _write(installation, "launcher/launcher-settings.json", '{"rawVersion": "1.14.5"}')
    _write(installation, "game/localization/english/native_l_english.yml", "# no language header\n")
    result = inventory_installation(installation)
    assert result["status"] == "incomplete"
    assert result["localization"]["languages"] == []
    assert any(failure["kind"] == "version_mismatch" for failure in result["failures"])
    assert any(failure["kind"] == "localization_no_languages" for failure in result["failures"])


@pytest.mark.parametrize("content", [b"a = \xff", b'{"broken":'])
def test_invalid_utf8_and_json_do_not_disappear(installation: Path, content: bytes) -> None:
    _write(installation, "game/dlc/test/descriptor.json", content)
    result = inventory_installation(installation)
    assert result["status"] == "incomplete"
    assert any(
        failure["kind"] == "decode_or_parse" and failure["path"] == "game/dlc/test/descriptor.json"
        for failure in result["failures"]
    )


def test_language_sources_and_conflicts(installation: Path) -> None:
    _write(installation, "game/localization/english/conflicting.yml", "l_new_language:\n")
    result = inventory_installation(installation)
    assert result["localization"]["languages"] == [
        {
            "directory": "english",
            "headers": ["l_english", "l_new_language"],
            "evidence_status": "static_discovery",
        }
    ]
    assert any(
        source["path"] == "game/localization/english/conflicting.yml" and source["line"] == 1
        for source in result["localization"]["header_sources"]
    )
    assert any(
        failure["kind"] == "localization_directory_conflict" for failure in result["failures"]
    )


def test_dlc_conditions_are_not_claimed_enabled(installation: Path) -> None:
    _write(installation, "game/dlc/test/test.dlc", 'name = "test"\n')
    _write(installation, "game/common/check.txt", "rule = { has_dlc_feature = feature_test }\n")
    result = inventory_installation(installation)
    assert result["dlc"]["ownership"] == result["dlc"]["enabled_state"] == "unknown"
    assert result["dlc"]["descriptors"][0]["path"] == "game/dlc/test/test.dlc"
    assert result["reference_candidates"][0]["value"] == "feature_test"
    assert result["reference_candidates"][0]["resolution_status"] == "unknown"


def test_language_registry_can_declare_multiple_headers(installation: Path) -> None:
    _write(
        installation,
        "game/localization/languages.yml",
        'l_english:\n l_english: "English"\nl_new:\n l_new: "New"\n',
    )
    result = inventory_installation(installation)
    assert not any(
        failure["kind"] == "localization_multiple_headers" for failure in result["failures"]
    )
    assert [source["header"] for source in result["localization"]["registry_sources"]] == [
        "l_english",
        "l_new",
    ]
    assert [language["directory"] for language in result["localization"]["languages"]] == [
        "english"
    ]


def test_duplicate_launcher_json_and_branch_drift_fail(installation: Path) -> None:
    _write(
        installation,
        "launcher/launcher-settings.json",
        '{"rawVersion":"1.14.5","rawVersion":"1.15.0"}',
    )
    _write(installation, "caligula_branch.txt", "release/1.14.5\n")
    result = inventory_installation(installation)
    assert result["status"] == "incomplete"
    assert {failure["kind"] for failure in result["failures"]} >= {
        "duplicate_json_field",
        "version_source_conflict",
    }


def test_same_installation_bytes_are_independent_of_location(
    installation: Path, tmp_path: Path
) -> None:
    relocated = tmp_path / "relocated"
    shutil.copytree(installation, relocated)
    assert canonical_json(inventory_installation(installation)) == canonical_json(
        inventory_installation(relocated)
    )


def test_cli_uses_same_json_and_refuses_installation_output(
    installation: Path, tmp_path: Path
) -> None:
    command = [
        sys.executable,
        "-B",
        "-X",
        "utf8",
        "-m",
        "pdx.situated.version_inventory",
        str(installation),
    ]
    output = tmp_path / "inventory.json"
    completed = subprocess.run(
        [*command, "--output", str(output)], capture_output=True, check=False
    )
    assert completed.returncode == 0, completed.stderr
    assert output.read_text(encoding="utf-8") == canonical_json(
        inventory_installation(installation)
    )
    refused = subprocess.run(
        [*command, "--output", str(installation / "wrong.json")], capture_output=True, check=False
    )
    assert refused.returncode == 2
    assert not (installation / "wrong.json").exists()


def test_localization_parent_name_does_not_change_content_classification(
    installation: Path, tmp_path: Path
) -> None:
    _write(installation, "game/extra.yml", "l_not_localization_content:\n")
    relocated = tmp_path / "localization" / "relocated"
    shutil.copytree(installation, relocated)
    original = inventory_installation(installation)
    moved = inventory_installation(relocated)
    assert canonical_json(original) == canonical_json(moved)
    assert not any(
        source["path"] == "game/extra.yml" for source in moved["localization"]["header_sources"]
    )


def test_identity_file_parent_link_cannot_escape_installation(
    installation: Path, tmp_path: Path
) -> None:
    launcher = installation / "launcher"
    (launcher / "launcher-settings.json").unlink()
    launcher.rmdir()
    outside = tmp_path / "outside-launcher"
    _write(outside, "launcher-settings.json", '{"rawVersion":"1.15.0"}')
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(launcher), str(outside)],
            capture_output=True,
            check=True,
        )
    else:
        launcher.symlink_to(outside, target_is_directory=True)
    try:
        result = inventory_installation(installation)
        assert result["version_identity"]["launcher"] is None
        assert not any(
            record["path"] == "launcher/launcher-settings.json" for record in result["files"]
        )
        assert any(
            failure["kind"] == "unfollowed_link"
            and failure["path"] == "launcher/launcher-settings.json"
            for failure in result["failures"]
        )
    finally:
        if os.name == "nt":
            launcher.rmdir()
        else:
            launcher.unlink()


def test_tolerant_parser_does_not_certify_extra_braces_or_missing_values(
    installation: Path,
) -> None:
    _write(installation, "game/common/malformed.txt", "}\nroot = { ai_weight = }\n")
    result = inventory_installation(installation)
    assert result["status"] == "incomplete"
    record = next(
        record for record in result["files"] if record["path"] == "game/common/malformed.txt"
    )
    assert record["parse_status"] == "partial"
    failure = next(
        failure
        for failure in result["failures"]
        if failure["kind"] == "strict_parse" and failure["path"] == "game/common/malformed.txt"
    )
    assert {error["kind"] for error in failure["errors"]} >= {
        "unexpected_closing_brace",
        "missing_assignment_value",
    }


def test_strict_structure_check_preserves_legal_bare_and_typed_blocks(installation: Path) -> None:
    _write(
        installation,
        "game/common/valid.txt",
        'root = { values = { a b 1 "two" { c d } } color = hsv { 0.1 0.2 0.3 } empty = {} scoped ?= { weight = 0 } }\n',
    )
    result = inventory_installation(installation)
    assert not any(failure["path"] == "game/common/valid.txt" for failure in result["failures"])
    record = next(record for record in result["files"] if record["path"] == "game/common/valid.txt")
    assert record["parse_status"] == "parsed"


def test_license_plaintext_is_hashed_without_pdx_syntax_claims(installation: Path) -> None:
    raw = b"================\nThird party copyright =\n"
    _write(installation, "game/licenses/software/example.txt", raw)
    result = inventory_installation(installation)
    record = next(
        record
        for record in result["files"]
        if record["path"] == "game/licenses/software/example.txt"
    )
    assert record["sha256"] == hashlib.sha256(raw).hexdigest()
    assert record["parse_status"] == "not_pdx"
    assert not any(
        failure["path"] == "game/licenses/software/example.txt" for failure in result["failures"]
    )
