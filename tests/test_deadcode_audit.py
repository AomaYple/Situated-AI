"""死代码审计器的行为测试。

这些测试故意用很小的内存文本构造 AST，锁住审计口径本身；最后再解析当前受控源码，
确保审计器不会因为仓库新增语法而静默漏扫。
"""

from __future__ import annotations

import json

from tools.ci import deadcode_audit as audit


def _scan(*files: tuple[str, str]) -> list[audit.Definition]:
    surface = dict(files)
    return audit.scan_paths(surface, surface=surface, reference_paths=surface)


def _one(rows: list[audit.Definition], name: str) -> audit.Definition:
    return next(row for row in rows if row.name == name)


def test_未引用函数被列为确定候选() -> None:
    row = _one(_scan(("sample.py", "def unused():\n    return 1\n")), "unused")
    assert row.verdict == "零引用候选"
    assert row.other_uses == 0
    assert row.local_loads == 0


def test_同文件真实调用不会被误判为零引用() -> None:
    rows = _scan(
        (
            "sample.py",
            "def helper():\n    return 1\n\ndef caller():\n    return helper()\n",
        )
    )
    row = _one(rows, "helper")
    assert row.local_loads == 1
    assert row.verdict == "仅定义文件内使用"


def test_测试文件中的跨文件调用计入引用面() -> None:
    rows = _scan(
        ("module.py", "def helper():\n    return 1\n"),
        ("test_module.py", "def test_helper():\n    return helper()\n"),
    )
    row = _one(rows, "helper")
    assert row.other_uses == 1
    assert row.verdict == "在用"


def test_动态入口和导出符号不会被列为确定候选() -> None:
    rows = _scan(
        (
            "entry.py",
            "__all__ = ['exported']\n\ndef exported():\n    return 1\n\ndef main():\n    return 0\n\nif __name__ == '__main__':\n    main()\n",
        ),
        (
            "conftest.py",
            "def pytest_configure(config):\n    return None\n",
        ),
    )
    assert "__all__ export" in _one(rows, "exported").dynamic_reasons
    assert "__main__ entrypoint" in _one(rows, "main").dynamic_reasons
    assert "pytest hook" in _one(rows, "pytest_configure").dynamic_reasons
    assert not [row for row in rows if row.verdict == "零引用候选"]


def test_类方法按动态入口处理() -> None:
    rows = _scan(
        (
            "sample.py",
            "class Adapter:\n    def run(self):\n        return 1\n",
        )
    )
    row = _one(rows, "run")
    assert "class method" in row.dynamic_reasons
    assert row.verdict == "动态入口或 API"


def test_当前受控源码全部可以解析() -> None:
    paths = audit._tracked_paths()
    surface = audit._read_surface(audit._reference_paths())
    rows = audit.scan_paths(paths, surface=surface)
    assert len(paths) >= 1
    assert len(rows) >= len(paths)


def test_报告写出为无BOM的LF文本(tmp_path) -> None:
    paths = ["sample.py"]
    rows = _scan((paths[0], "def unused():\n    return 1\n"))
    report = audit._report(rows, paths)
    json_path = tmp_path / "deadcode.json"
    markdown_path = tmp_path / "deadcode.md"
    audit._write_json(json_path, report)
    audit._write_markdown(markdown_path, report)

    for path in (json_path, markdown_path):
        raw = path.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf")
        assert b"\r" not in raw
    assert json.loads(json_path.read_text(encoding="utf-8"))["definition_count"] == 1
