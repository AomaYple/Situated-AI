"""JUnit 跳过项报告器的测试。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from pdx import config
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


@pytest.mark.parametrize("encoding", ["cp1252", "gbk"])
@pytest.mark.parametrize(("mode", "expected_exit"), [("known", 0), ("unknown", 2), ("missing", 2)])
def test_non_utf8_console_preserves_json_and_exit_status(
    tmp_path: Path, encoding: str, mode: str, expected_exit: int
) -> None:
    reason = "游戏目录不可用 ✅" if mode == "known" else "说明尚待确认 ✅"
    source = _junit(tmp_path, reason)
    if mode == "missing":
        source = tmp_path / "缺失输入.xml"
    target = tmp_path / "summary.json"
    result = subprocess.run(
        [
            sys.executable,
            str(config.REPO / "tools/ci/test_summary.py"),
            str(source),
            "--output",
            str(target),
        ],
        env={**os.environ, "PYTHONIOENCODING": encoding, "PYTHONUTF8": "0"},
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == expected_exit, result.stderr
    stdout, stderr = result.stdout.decode("utf-8"), result.stderr.decode("utf-8")
    if mode == "missing":
        assert "无法读取" in stderr
        assert not target.exists()
    else:
        payload = target.read_bytes()
        assert not payload.startswith(b"\xef\xbb\xbf")
        assert b"\r" not in payload
        report = json.loads(stdout)
        assert report == json.loads(payload)
        assert report["skips"][0]["reason"] == reason
        if mode == "unknown":
            assert report["unknown_skip_reasons"]
            assert "未分类" in stderr
        else:
            assert report["skip_categories"] == {"game": 1}
            assert not report["unknown_skip_reasons"]
            assert not stderr
