"""审计当前 Python 源码中的未引用函数和类。

这个审计器只负责找候选，不会凭文本搜索结果自动删除代码。Typer、pytest、
插件 hook、``__all__`` 和直接执行脚本都可能通过动态机制发现符号，因此报告
会把这些情况单独标记出来；只有没有任何引用、也没有动态入口迹象的符号才会
在 ``--check`` 下阻断门禁。

用法：

    python -m tools.ci.deadcode_audit
    python -m tools.ci.deadcode_audit --json tools/out/ci/deadcode.json
    python -m tools.ci.deadcode_audit --check
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Iterable


ROOT = Path(__file__).resolve().parents[2]
SOURCE_PREFIXES = ("src/pdx/", "tools/ci/", "tools/benchmarks/", "tools/probe/")
EXCLUDED_PARTS = {"frozen", "__pycache__"}
WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
DECORATOR_HINTS = (
    "pytest.",
    "pytest.mark.",
    "app.command",
    "cli.command",
    "typer.",
    "click.",
    "hookimpl",
    "property",
    "staticmethod",
    "classmethod",
    "contextmanager",
    "dataclass",
    "register",
)
PYTEST_HOOK_NAMES = {
    "pytest_addoption",
    "pytest_configure",
    "pytest_collection_finish",
    "pytest_collection_modifyitems",
    "pytest_runtest_logstart",
    "pytest_runtest_logreport",
    "pytest_sessionstart",
    "pytest_sessionfinish",
    "pytest_xdist_auto_num_workers",
}
BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".bmp",
    ".dds",
    ".exe",
    ".dll",
    ".pyc",
    ".prof",
    ".bin",
    ".so",
    ".whl",
    ".zip",
    ".7z",
    ".sqlite",
}


@dataclass(frozen=True, slots=True)
class Definition:
    path: str
    line: int
    name: str
    kind: str
    same_uses: int
    local_loads: int
    other_uses: int
    dynamic_reasons: tuple[str, ...]
    doc: str

    @property
    def verdict(self) -> str:
        if self.dynamic_reasons:
            return "动态入口或 API"
        if self.other_uses:
            return "在用"
        if self.local_loads:
            return "仅定义文件内使用"
        return "零引用候选"

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "line": self.line,
            "name": self.name,
            "kind": self.kind,
            "same_uses": self.same_uses,
            "local_loads": self.local_loads,
            "other_uses": self.other_uses,
            "dynamic_reasons": list(self.dynamic_reasons),
            "doc": self.doc,
            "verdict": self.verdict,
        }


def _tracked_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    paths = result.stdout.decode("utf-8", "surrogateescape").split("\x00")
    return [
        path
        for path in sorted(set(paths))
        if path.endswith(".py")
        and path.startswith(SOURCE_PREFIXES)
        and not any(part in EXCLUDED_PARTS for part in Path(path).parts)
    ]


def _reference_paths() -> list[str]:
    """返回受控及尚未入库的新Python文本；忽略产物不能掩盖新代码漏审。"""

    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    paths = result.stdout.decode("utf-8", "surrogateescape").split("\x00")
    return [
        path
        for path in sorted(set(paths))
        if path.endswith(".py") and not any(part in EXCLUDED_PARTS for part in Path(path).parts)
    ]


def _read_surface(paths: Iterable[str]) -> dict[str, str]:
    surface: dict[str, str] = {}
    for path in paths:
        try:
            surface[path] = (ROOT / path).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
    return surface


def _word_index(surface: dict[str, str]) -> dict[str, list[tuple[str, int]]]:
    index: dict[str, list[tuple[str, int]]] = {}
    for path, text in surface.items():
        for line, content in enumerate(text.splitlines(), start=1):
            for name in set(WORD_RE.findall(content)):
                index.setdefault(name, []).append((path, line))
    return index


def _decorator_text(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> str:
    return " ".join(ast.unparse(decorator) for decorator in node.decorator_list)


def _has_main_guard(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        try:
            if ast.unparse(node.test) == "__name__ == '__main__'":
                return True
        except ValueError:
            continue
    return False


def _dynamic_reasons(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    tree: ast.Module,
    *,
    class_method: bool = False,
) -> tuple[str, ...]:
    reasons: list[str] = []
    decorator_text = _decorator_text(node)
    for hint in DECORATOR_HINTS:
        if hint in decorator_text:
            reasons.append(f"decorator:{hint}")
            break
    if node.name == "main" and _has_main_guard(tree):
        reasons.append("__main__ entrypoint")
    if node.name in PYTEST_HOOK_NAMES:
        reasons.append("pytest hook")
    if node.name in _exported_names(tree):
        reasons.append("__all__ export")
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and class_method:
        reasons.append("class method")
    return tuple(reasons)


def _exported_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            continue
        value = node.value
        if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            names.update(
                element.value
                for element in value.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            )
    return names


def _class_method_nodes(tree: ast.Module) -> set[int]:
    """一次遍历收集类体中的方法节点，避免逐定义反复遍历整棵 AST。"""

    methods: set[int] = set()
    for class_node in ast.walk(tree):
        if not isinstance(class_node, ast.ClassDef):
            continue
        methods.update(
            id(child)
            for child in class_node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
    return methods


def _local_loads(tree: ast.AST, name: str) -> int:
    """统计同一文件里真实的名字读取，排除文档和注释中的文字。"""

    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load)
    )


def scan_paths(
    paths: Iterable[str],
    surface: dict[str, str] | None = None,
    reference_paths: Iterable[str] | None = None,
) -> list[Definition]:
    """扫描给定 Python 文件，返回函数/类级别的引用分类。"""

    path_list = sorted(paths)
    texts = surface if surface is not None else _read_surface(reference_paths or path_list)
    index = _word_index(texts)
    rows: list[Definition] = []
    for path in path_list:
        text = texts.get(path)
        if text is None:
            continue
        try:
            tree = ast.parse(text, filename=path)
        except SyntaxError as exc:
            raise ValueError(f"无法解析 {path}:{exc.lineno}: {exc.msg}") from exc
        class_methods = _class_method_nodes(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            hits = index.get(node.name, [])
            same = sum(hit_path == path and hit_line != node.lineno for hit_path, hit_line in hits)
            other = sum(hit_path != path for hit_path, _ in hits)
            local_loads = _local_loads(tree, node.name)
            doc = ast.get_docstring(node) or ""
            rows.append(
                Definition(
                    path=path,
                    line=node.lineno,
                    name=node.name,
                    kind="class" if isinstance(node, ast.ClassDef) else "function",
                    same_uses=same,
                    local_loads=local_loads,
                    other_uses=other,
                    dynamic_reasons=_dynamic_reasons(
                        node, tree, class_method=id(node) in class_methods
                    ),
                    doc=(doc.strip().splitlines() or [""])[0][:160],
                )
            )
    return rows


def _report(rows: list[Definition], paths: list[str]) -> dict[str, object]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.verdict] = counts.get(row.verdict, 0) + 1
    candidates = [row.as_dict() for row in rows if row.verdict == "零引用候选"]
    local_only = [row.as_dict() for row in rows if row.verdict == "仅定义文件内使用"]
    return {
        "source_files": paths,
        "definition_count": len(rows),
        "verdicts": dict(sorted(counts.items())),
        "definite_candidates": candidates,
        "local_only_candidates": local_only,
        "definitions": [row.as_dict() for row in rows],
    }


def _write_json(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def _write_markdown(path: Path, report: dict[str, object]) -> None:
    counts = cast("dict[str, int]", report["verdicts"])
    candidates = cast("list[dict[str, object]]", report["definite_candidates"])
    local_only = cast("list[dict[str, object]]", report["local_only_candidates"])
    source_files = cast("list[str]", report["source_files"])
    lines = [
        "# 当前 Python 源码死代码审计",
        "",
        f"- 扫描文件：{len(source_files)}",
        f"- 定义点：{report['definition_count']}",
        "",
        "| 判定 | 数量 |",
        "|---|---:|",
    ]
    for verdict, count in counts.items():
        lines.append(f"| {verdict} | {count} |")
    lines.extend(["", "## 零引用候选", "", "| 文件:行 | 名称 | 类型 | 说明 |", "|---|---|---|---|"])
    lines.extend(
        f"| `{row['path']}:{row['line']}` | `{row['name']}` | {row['kind']} | {row['doc'] or '—'} |"
        for row in candidates
    )
    if not candidates:
        lines.append("| — | — | — | 未发现没有引用或动态入口标记的定义。 |")
    lines.extend(
        [
            "",
            "## 仅定义文件内使用（需要人工判断）",
            "",
            "这些定义没有跨文件文本引用，但可能是同文件组合、递归、注册或公开的脚本入口。",
            "| 文件:行 | 名称 | 类型 | 同文件引用 | 说明 |",
            "|---|---|---|---:|---|",
        ]
    )
    lines.extend(
        f"| `{row['path']}:{row['line']}` | `{row['name']}` | {row['kind']} | "
        f"{row['same_uses']} | {row['doc'] or '—'} |"
        for row in local_only
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="写出 JSON 报告")
    parser.add_argument("--markdown", type=Path, help="写出 Markdown 报告")
    parser.add_argument("--check", action="store_true", help="发现确定零引用候选时返回 1")
    args = parser.parse_args(argv)
    try:
        paths = _tracked_paths()
        report = _report(scan_paths(paths, reference_paths=_reference_paths()), paths)
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError) as exc:
        print(f"[deadcode] 审计失败：{exc}", file=sys.stderr)
        return 2
    if args.json:
        _write_json(args.json, report)
    if args.markdown:
        _write_markdown(args.markdown, report)
    print(
        json.dumps(
            {"definition_count": report["definition_count"], "verdicts": report["verdicts"]},
            ensure_ascii=False,
        )
    )
    return 1 if args.check and report["definite_candidates"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
