"""JUnit 跳过项报告器的测试。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tools.ci.test_summary import main, summarize

if TYPE_CHECKING:
    from pathlib import Path


def _junit(tmp_path: Path, skipped: str = "") -> Path:
    path = tmp_path / "results.xml"
    path.write_text(
        "<testsuite tests='3'>"
        "<testcase classname='unit' name='ok'/>"
        f"<testcase classname='env' name='skip'><skipped message='{skipped}'/></testcase>"
        "<testcase classname='unit' name='fail'><failure/></testcase>"
        "</testsuite>",
        encoding="utf-8",
        newline="\n",
    )
    return path


def test_summary_counts_and_classifies(tmp_path: Path) -> None:
    report = summarize(_junit(tmp_path, "游戏目录不可用"))
    assert report["tests"] == 3
    assert report["skipped"] == 1
    assert report["failures"] == 1
    assert report["skip_categories"] == {"game": 1}
    assert report["unknown_skip_reasons"] == []


def test_unknown_skip_reason_fails_and_can_write_report(tmp_path: Path, capsys) -> None:
    source = _junit(tmp_path, "unexplained condition")
    output = tmp_path / "out" / "summary.json"
    assert main([str(source), "--output", str(output)]) == 2
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["skip_categories"] == {"unknown": 1}
    assert "未分类" in capsys.readouterr().err


def test_empty_skip_reason_is_rejected(tmp_path: Path) -> None:
    report = summarize(_junit(tmp_path, ""))
    assert report["unknown_skip_reasons"]
