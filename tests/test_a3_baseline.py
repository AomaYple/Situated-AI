"""A3 成本基线使用真实 AST 和完整 reader 身份，不把文本巧合当成本。"""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools/ci/a3_baseline.py"


def _api():
    assert SCRIPT.is_file(), "缺少 A3 基线采集入口"
    return runpy.run_path(str(SCRIPT))


def test_expression_metrics_ignore_comments_and_count_actual_ast() -> None:
    metrics = _api()["pdx_metrics"](
        "# any_country = { set_variable = fake }\n"
        "a = { b = 2 if = { limit = { is_ai = yes } add = 1 } }"
    )
    assert metrics["assignment_nodes"] == 6
    assert metrics["block_nodes"] == 4
    assert metrics["scalar_nodes"] == 3
    assert metrics["max_depth"] == 3
    assert metrics["object_scan_sites"] == 0
    assert metrics["persistent_write_sites"] == 0


def test_expression_metrics_count_scans_and_persistent_writer_sites() -> None:
    metrics = _api()["pdx_metrics"](
        "any_owned_state = { set_variable = { name = sitai_a value = 2 } }\n"
        "remove_variable = sitai_a"
    )
    assert metrics["object_scan_sites"] == 1
    assert metrics["persistent_write_sites"] == 2


def test_expression_metrics_fail_on_parse_error() -> None:
    with pytest.raises(ValueError, match="解析"):
        _api()["pdx_metrics"]("a = {")


def test_reader_duplicate_metrics_preserve_target_and_path_identity() -> None:
    root = ("gdp", "root", "money", "number", None, 0, None, (), None, ())
    target = ("gdp", "target", "money", "number", None, 0, None, (), None, ())
    nested = ("gdp", "root", "money", "number", None, 0, None, ("owner",), None, ())
    report = _api()["reader_metrics"](
        [("a", "one", root), ("b", "alias", root), ("a", "target", target), ("a", "nested", nested)]
    )
    assert report["declarations"] == 4
    assert report["unique_observation_signatures"] == 3
    assert report["duplicate_declarations"] == 1
    assert report["with_object_path"] == 1


def test_identity_guard_rejects_source_changes(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text("a = 1\n", encoding="utf-8")
    api = _api()
    before = api["file_identity"]([source], root=tmp_path)
    source.write_text("a = 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="漂移"):
        api["require_identity"](before, api["file_identity"]([source], root=tmp_path))
