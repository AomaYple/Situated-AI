"""仓库卫生检查器的正例、反例和排除范围。"""

from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.ci.repo_hygiene import clean, find_violations, main, report


def _paths(rows: list[dict[str, str]]) -> set[str]:
    return {row["path"] for row in rows}


def test_clean_tree_has_no_violations(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_text("value = 1\n", encoding="utf-8")

    assert find_violations(tmp_path) == []


def test_src_egg_info_cleanup_is_limited_to_direct_children(tmp_path: Path) -> None:
    artifact = tmp_path / "src" / "project.egg-info"
    protected = (
        tmp_path / "src" / "package" / "nested.egg-info",
        tmp_path / "src" / "build",
        tmp_path / ".venv" / "Lib" / "dependency.egg-info",
    )
    for directory in (artifact, *protected):
        directory.mkdir(parents=True)
        (directory / "PKG-INFO").write_bytes(b"metadata")
    assert _paths(find_violations(tmp_path)) == {"src/project.egg-info"}
    assert clean(tmp_path)["removed"] == []
    assert artifact.is_dir()
    result = clean(tmp_path, apply=True)
    assert result["removed"] == ["src/project.egg-info"]
    assert result["failures"] == []
    assert all((directory / "PKG-INFO").read_bytes() == b"metadata" for directory in protected)


def test_nonexistent_root_is_an_error_not_a_clean_tree(tmp_path: Path, capsys) -> None:
    root = tmp_path / "missing"
    with pytest.raises(NotADirectoryError):
        find_violations(root)
    assert main(["--root", str(root)]) == 2
    assert "检查失败" in capsys.readouterr().err


def test_reparse_directory_is_not_traversed(tmp_path: Path, monkeypatch) -> None:
    linked = tmp_path / "junction"
    (linked / "__pycache__").mkdir(parents=True)
    path_type = type(linked)
    original = path_type.lstat

    def lstat(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == linked:
            return SimpleNamespace(
                st_mode=info.st_mode, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT
            )
        return info

    monkeypatch.setattr(path_type, "lstat", lstat)
    assert find_violations(tmp_path) == []


def test_detects_abandoned_pip_directories_only_at_root(tmp_path: Path) -> None:
    names = ("pip-install-abandoned", "pip-ephem-wheel-cache-abandoned")
    for name in names:
        (tmp_path / name).mkdir()
    (tmp_path / "src" / "pip-install-legitimate").mkdir(parents=True)

    assert _paths(find_violations(tmp_path)) == set(names)


def test_reports_default_mutmut_output_without_adding_cleanup_permission(tmp_path: Path) -> None:
    output = tmp_path / "mutants"
    output.mkdir()
    stats = output / "mutmut-stats.json"
    stats.write_bytes(b"{}")
    (tmp_path / "src" / "mutants").mkdir(parents=True)

    rows = find_violations(tmp_path)
    assert _paths(rows) == {"mutants"}
    result = clean(tmp_path, apply=True)
    assert result["skipped"] == rows
    assert result["removed"] == []
    assert stats.read_bytes() == b"{}"


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


def test_git_index_checks_registered_outputs_and_force_added_ignored_paths(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    rules = Path(__file__).resolve().parents[1] / ".gitignore"
    (tmp_path / ".gitignore").write_bytes(rules.read_bytes())
    tracked = ("tools/out/snapshots/release-1.15.2.compact.json",)
    ignored = (
        "tools/out/snapshots/本机结果.compact.json",
        "tools/out/evidence/v0.1-g1-20261013/g1-reopen-scan-20261013.json",
        "tools/out/raw/游戏资料.json",
        ".venv/pyvenv.cfg",
        "research/official-docs/官方文档.txt",
    )
    for relative in (*tracked, *ignored):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"example\n")

    subprocess.run(["git", "add", "--", *tracked], cwd=tmp_path, check=True)
    assert find_violations(tmp_path) == []

    subprocess.run(["git", "add", "-f", "--", *ignored], cwd=tmp_path, check=True)
    violations = find_violations(tmp_path)
    assert _paths(violations) == set(ignored)
    assert {row["kind"] for row in violations} == {"tracked_ignored"}


def test_cleanup_preserves_indexed_cache_files_and_ancestors(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    cache_dir = tmp_path / ".pytest_cache"
    cache_dir.mkdir()
    indexed = cache_dir / "important.txt"
    indexed.write_bytes(b"tracked\n")
    transient = tmp_path / ".coverage"
    transient.write_bytes(b"transient\n")
    subprocess.run(["git", "add", "--", ".pytest_cache/important.txt"], cwd=tmp_path, check=True)

    result = clean(tmp_path, apply=True)

    assert result["removed"] == [".coverage"]
    skipped = result["skipped"]
    assert isinstance(skipped, list)
    assert {row["path"] for row in skipped} == {".pytest_cache"}
    assert indexed.read_bytes() == b"tracked\n"
    assert not transient.exists()


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
