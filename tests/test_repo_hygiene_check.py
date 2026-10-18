"""仓库卫生检查器的正例、反例和排除范围。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tools.ci.repo_hygiene import find_violations, main, report

if TYPE_CHECKING:
    from pathlib import Path


def _paths(rows: list[dict[str, str]]) -> set[str]:
    return {row["path"] for row in rows}


def test_clean_tree_has_no_violations(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_text("value = 1\n", encoding="utf-8")

    assert find_violations(tmp_path) == []


def test_detects_root_caches_bytecode_and_nested_pycache(tmp_path: Path) -> None:
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".coverage.123").write_text("data", encoding="utf-8")
    (tmp_path / "src" / "__pycache__").mkdir(parents=True)
    (tmp_path / "src" / "__pycache__" / "module.cpython-313.pyc").write_bytes(b"bytecode")
    (tmp_path / "tools" / "cache.pyc").parent.mkdir(parents=True)
    (tmp_path / "tools" / "cache.pyc").write_bytes(b"bytecode")

    rows = find_violations(tmp_path)

    assert _paths(rows) == {
        ".coverage.123",
        ".pytest_cache",
        "src/__pycache__",
        "tools/cache.pyc",
    }


def test_excludes_environment_evidence_and_official_mirror(tmp_path: Path) -> None:
    for relative in (
        ".venv/__pycache__",
        "tools/out/__pycache__",
        "research/official-docs/__pycache__",
    ):
        path = tmp_path / relative
        path.mkdir(parents=True)
        (path / "ignored.pyc").write_bytes(b"bytecode")

    assert find_violations(tmp_path) == []


def test_report_and_cli_return_failure_for_dirty_tree(tmp_path: Path, capsys) -> None:
    (tmp_path / ".ruff-cache-test").mkdir()
    output = tmp_path / "report.json"

    data = report(tmp_path)
    result = main(["--root", str(tmp_path), "--output", str(output)])

    assert result == 1
    assert data["violation_count"] == 1
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["violations"] == data["violations"]
    assert "violation_count" in capsys.readouterr().out
