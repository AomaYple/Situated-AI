"""Validate A3 scope and evidence wiring; this does not certify game behavior."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LEDGER = Path("docs/design/A3实施台账.toml")
DIRECTIONS = {
    f"B{domain:02}.{direction}"
    for domain, count in enumerate((5, 5, 4, 4, 5, 5, 4, 4, 4, 4, 4, 4), start=1)
    for direction in range(1, count + 1)
}
RELATIONS = {f"R{number:02}" for number in range(1, 13)}
CONTRACTS = {f"C{number}" for number in range(1, 10)}
STATES = {"pending", "unknown", "in_progress", "implemented", "retained", "unsupported"}
TERMINAL = {"implemented", "retained", "unsupported"}
ROW_FIELDS = {
    "id",
    "parent",
    "title",
    "status",
    "question",
    "acceptance",
    "source_paths",
    "consumer_investigation",
    "existing_state",
    "gap",
    "evidence",
    "rationale",
}


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 为空或不是文本")
    return value


def _file(root: Path, value: Any) -> Path:
    raw = _text(value, "path")
    relative = PurePosixPath(raw)
    if "\\" in raw or ":" in raw or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"必须使用仓库内相对路径: {raw}")
    path = (root / raw).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"必须使用仓库内相对路径: {raw}")
    if not path.is_file():
        raise ValueError(f"引用文件不存在: {raw}")
    return path


def _reference(ref: Any, root: Path) -> tuple[str, Path]:
    if not isinstance(ref, dict) or set(ref) != {"role", "path", "kind", "identity", "sha256"}:
        raise ValueError("证据必须有 role/path/kind/identity/sha256，不允许文字通过")
    path = _file(root, ref["path"])
    identity = _text(ref["identity"], "identity")
    if ref["sha256"] != hashlib.sha256(path.read_bytes()).hexdigest():
        raise ValueError(f"证据源哈希过期: {path}")
    if ref["kind"] == "toml_key":
        if path.suffix != ".toml":
            raise ValueError("toml_key 必须引用 TOML 规则表")
        node: Any = tomllib.loads(path.read_text(encoding="utf-8"))
        for part in identity.split("."):
            if not isinstance(node, dict) or part not in node:
                raise ValueError(f"实际规则身份不存在: {path}#{identity}")
            node = node[part]
        if not isinstance(node, dict) or not node:
            raise ValueError(f"证据必须指向非空实际规则表: {path}#{identity}")
    elif ref["kind"] == "python_symbol":
        if path.suffix != ".py":
            raise ValueError("python_symbol 必须引用 Python 定义")
        tree: Any = ast.parse(path.read_text(encoding="utf-8"))
        for part in identity.split("."):
            tree = next(
                (
                    child
                    for child in tree.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    and child.name == part
                ),
                None,
            )
            if tree is None:
                raise ValueError(f"实际见证/规则身份不存在: {path}#{identity}")
    else:
        raise ValueError(f"不支持的证据身份类型: {ref['kind']}")
    role = _text(ref["role"], "role")
    if role not in {"source", "consumer", "witness", "boundary"}:
        raise ValueError(f"不支持的证据角色: {role}")
    if role in {"source", "consumer"} and not any(
        path.is_relative_to(root.resolve() / prefix)
        for prefix in ("mod/decisions", "src/pdx", "tools/ci")
    ):
        raise ValueError("source/consumer 必须引用实际生产源或工程校验器")
    if role == "witness" and (
        not path.is_relative_to(root.resolve() / "tests")
        or ref["kind"] != "python_symbol"
        or not identity.split(".")[-1].startswith("test_")
    ):
        raise ValueError("witness 必须引用独立 tests 下的实际测试身份")
    return role, path


def validate_scope(
    data: dict[str, Any], *, root: Path = ROOT, require_complete: bool = False
) -> dict[str, int]:
    """Reject omissions, stale/dead evidence and unsupported completion claims."""
    if set(data) != {"schema", "plan", "freeze", "obligations"}:
        raise ValueError("台账顶层字段不允许遗漏或额外声明")
    if data["schema"] != 1 or data["plan"] != "A3":
        raise ValueError("台账 schema/plan 不匹配")
    _text(data["freeze"], "freeze")
    rows = data["obligations"]
    if not isinstance(rows, list):
        raise ValueError("obligations 必须为工作项列表")
    ids: set[str] = set()
    parents: set[str] = set()
    pending = 0
    for row in rows:
        if not isinstance(row, dict) or set(row) - ROW_FIELDS:
            raise ValueError("工作项含不允许字段")
        item_id = _text(row.get("id"), "id")
        if item_id in ids:
            raise ValueError(f"工作项 ID 重复: {item_id}")
        ids.add(item_id)
        parent = _text(row.get("parent"), "parent")
        if parent not in DIRECTIONS | RELATIONS | CONTRACTS or not re.fullmatch(
            re.escape(parent) + r"\.[1-9]\d*", item_id
        ):
            raise ValueError(f"工作项 ID/parent 不匹配冻结范围: {item_id}")
        parents.add(parent)
        for name in (
            "title",
            "question",
            "acceptance",
            "consumer_investigation",
            "existing_state",
            "gap",
        ):
            _text(row.get(name), f"{item_id}.{name}")
        routes = row.get("source_paths")
        if not isinstance(routes, list) or not routes:
            raise ValueError(f"{item_id}.source_paths 为空")
        for route in routes:
            _file(root, route)
        status = row.get("status")
        if not isinstance(status, str) or status not in STATES:
            raise ValueError(f"不允许的状态: {item_id}={status}")
        refs = row.get("evidence")
        if not isinstance(refs, list):
            raise ValueError(f"{item_id}.evidence 必须显式列出（调查期可为空）")
        checked = [_reference(ref, root) for ref in refs]
        if status in TERMINAL:
            _text(row.get("rationale"), f"状态 {status} 的依据")
            required = (
                {"source", "consumer", "witness"}
                if status == "implemented"
                else {"source", "boundary", "witness"}
            )
            roles = {role for role, _ in checked}
            if required - roles:
                raise ValueError(f"状态 {status} 缺少证据角色: {sorted(required - roles)}")
            source_paths = {path for role, path in checked if role in {"source", "consumer"}}
            if any(path in source_paths for role, path in checked if role == "witness"):
                raise ValueError("witness 不得由生产文件自身签发")
        else:
            pending += 1
    missing = {f"{parent}.1" for parent in DIRECTIONS | RELATIONS | CONTRACTS} - ids
    if missing:
        raise ValueError(f"冻结方向/链/公共合同缺失: {sorted(missing)}")
    if require_complete and pending:
        raise ValueError(f"A3 尚有 {pending} 项未完成；引用通过不证明游戏行为验收")
    return {
        "directions": len(parents & DIRECTIONS),
        "relations": len(parents & RELATIONS),
        "contracts": len(parents & CONTRACTS),
        "pending": pending,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=ROOT / LEDGER)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = validate_scope(
            tomllib.loads(args.ledger.read_text(encoding="utf-8")),
            require_complete=args.require_complete,
        )
    except (OSError, ValueError) as exc:
        print(f"A3 scope: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False))
    print("仅证明范围及证据身份接线，不签发生产语义或游戏行为结论。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
