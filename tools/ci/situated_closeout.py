"""A2 / S0--S6 的静态工程收口与证据门。

这个入口只汇总已有的生成锁、发行包输入、生产 metadata 和仓库卫生
检查；它不重生成生产树、不启动游戏，也不把静态通过写成行为验收。
``--require-engineering`` 核对 S0--S5 工程与功能出口，供 S6 交付前使用；
``--require-plan`` 另核对 S6 实际发布和部署收据。
报告默认输出到 stdout，``--output`` 只写被忽略的报告路径。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

# 该文件既可作为 ``python -m tools.ci.situated_closeout`` 运行，也应能被
# 贡献流程直接调用。直接执行脚本时，Python 默认只把 ``tools/ci`` 放入
# sys.path；先把仓库根加入路径，保证两种入口使用同一份源码，而不是
# 因调用方式不同产生导入失败。
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pdx import decisions, distribution  # noqa: E402
from pdx.situated import architecture_receipts, vanilla_inventory  # noqa: E402
from tools.ci import repo_hygiene  # noqa: E402

PRODUCTION = distribution.decisions.PRODUCT
TEXT_SUFFIXES = frozenset({".json", ".md", ".toml", ".txt", ".yml", ".yaml"})
PACKAGE_FORBIDDEN_PARTS = frozenset(
    {"probe", "probes", "cache", "caches", "logs", "log", "tools", "research", ".venv"}
)
PACKAGE_FORBIDDEN_SUFFIXES = frozenset({".py", ".pyc", ".pyo", ".log"})
PLAN_PATH = architecture_receipts.PLAN_PATH
STAGE_DEPENDENCIES = architecture_receipts.STAGE_DEPENDENCIES
ENGINEERING_STAGES = architecture_receipts.ENGINEERING_STAGES


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def production_encoding_violations(root: Path = PRODUCTION) -> list[dict[str, str]]:
    """检查生产树的仓库侧 UTF-8 无 BOM、LF 和 NUL 合同。

    ``thumbnail.png`` 等二进制资源不属于文本合同；其它受控文本若无法
    解码或含 CR/BOM，均返回可定位的违规项。
    """

    violations: list[dict[str, str]] = []
    if not root.is_dir():
        return [{"path": root.as_posix(), "reason": "生产目录不存在"}]
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        raw = path.read_bytes()
        relative = _relative(path, root)
        if raw.startswith(b"\xef\xbb\xbf"):
            violations.append({"path": relative, "reason": "UTF-8 BOM"})
        if b"\r" in raw:
            violations.append({"path": relative, "reason": "CR/CRLF"})
        if b"\x00" in raw:
            violations.append({"path": relative, "reason": "NUL"})
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            violations.append({"path": relative, "reason": "不是 UTF-8"})
    return violations


def package_exclusion_violations(names: list[str] | tuple[str, ...]) -> list[str]:
    """检查候选包路径是否携带探针、缓存、日志或 Python 运行态。"""

    violations: list[str] = []
    for name in sorted(names):
        path = Path(name.replace("\\", "/"))
        parts = {part.casefold() for part in path.parts}
        if parts & PACKAGE_FORBIDDEN_PARTS or path.suffix.casefold() in PACKAGE_FORBIDDEN_SUFFIXES:
            violations.append(name)
            continue
        if "probe" in name.casefold() or "cache" in name.casefold():
            violations.append(name)
    return violations


def consumer_ir_owner_report() -> dict[str, Any]:
    """从当前生产源重建 engineering metadata，核对 ConsumerIR 唯一 owner。"""

    files = decisions.build(extensions=decisions.load_extensions(profile="release"))
    raw = files.get(".metadata/metadata.json")
    if not isinstance(raw, str):
        return {"issues": ["生成 metadata 缺失"], "field_owners": {}, "writer_count": 0}
    metadata = json.loads(raw)
    situated = metadata.get("situated_actions")
    if not isinstance(situated, dict):
        return {"issues": ["metadata 缺少 situated_actions"], "field_owners": {}, "writer_count": 0}
    bundle = situated.get("consumer_ir")
    if not isinstance(bundle, dict):
        return {
            "issues": ["metadata 缺少 situated_actions.consumer_ir"],
            "field_owners": {},
            "writer_count": 0,
        }
    writers = bundle.get("writers")
    declared = bundle.get("field_owners")
    issues: list[str] = []
    if not isinstance(writers, list) or not writers:
        issues.append("ConsumerIR writers 为空")
        writers = []
    if bundle.get("writer_count") != len(writers):
        issues.append("ConsumerIR writer_count 与 writers 不一致")
    legacy_writers = [
        row for row in writers if isinstance(row, dict) and row.get("kind") == "rule_action"
    ]
    legacy_semantic = [row for row in legacy_writers if isinstance(row.get("legacy_action"), dict)]
    if bundle.get("legacy_writer_count") != len(legacy_writers):
        issues.append("ConsumerIR legacy_writer_count 与 writers 不一致")
    if bundle.get("legacy_semantic_count") != len(legacy_semantic):
        issues.append("ConsumerIR legacy_semantic_count 与 legacy writer 不一致")
    if not isinstance(declared, dict):
        issues.append("ConsumerIR field_owners 缺失")
        declared = {}
    field_owners: dict[str, set[str]] = {}
    writer_ids: set[str] = set()
    for row in writers:
        if not isinstance(row, dict):
            issues.append("ConsumerIR writer 不是对象")
            continue
        field, owner = row.get("field"), row.get("owner")
        writer_id = row.get("writer_id")
        if not isinstance(writer_id, str) or not writer_id:
            issues.append("ConsumerIR writer 缺少 writer_id")
        elif writer_id in writer_ids:
            issues.append(f"ConsumerIR writer ID 重复：{writer_id}")
        else:
            writer_ids.add(writer_id)
        if not isinstance(field, str) or not field:
            issues.append("ConsumerIR writer 缺少 field")
            continue
        if not isinstance(owner, str) or not owner:
            issues.append(f"ConsumerIR writer 缺少 owner：{field}")
            continue
        field_owners.setdefault(field, set()).add(owner)
    for field, owners in sorted(field_owners.items()):
        if len(owners) != 1:
            issues.append(f"消费者字段存在多个 owner：{field}")
        if declared.get(field) not in owners:
            issues.append(f"metadata field_owners 与 writer 不一致：{field}")
    if set(declared) != set(field_owners):
        issues.append("metadata field_owners 与 writer 字段集合不一致")
    return {
        "issues": issues,
        "field_owners": {
            field: min(owners) for field, owners in sorted(field_owners.items()) if len(owners) == 1
        },
        "writer_count": len(writers),
    }


def plan_gate(root: Path = ROOT) -> dict[str, Any]:
    """核对当前 A2/S 出口、来源及 fresh 原版范围；pending 不冒充不支持。"""
    try:
        inventory = vanilla_inventory.discover()
    except (OSError, ValueError) as exc:
        receipts = architecture_receipts.stage_report(root, None)
        return {
            "status": "blocked",
            "stage": "S0",
            "reason": str(exc),
            "discovered": None,
            "pending": None,
            "pending_scope": None,
            "unknown_scopes": None,
            "parse_failures": [],
            "scope_hash": None,
            "evidence": "static_check",
            "ready": False,
            "engineering_status": "blocked",
            "engineering_ready": False,
            "engineering_scope_matches": False,
            "scope_matches": False,
            "stage_receipts": receipts,
            "business_complete": False,
        }
    receipts = architecture_receipts.stage_report(root, inventory)
    inventory_ready = not inventory.parse_failures and bool(
        receipts.get("native_scope", {}).get("closed")
    )
    scope_matches = all(
        row.get("scope_hash") == inventory.scope_hash for row in receipts["stages"].values()
    )
    engineering_scope_matches = all(
        receipts["stages"][stage].get("scope_hash") == inventory.scope_hash
        for stage in ENGINEERING_STAGES
    )
    engineering_ready = (
        receipts["engineering_ready"] and inventory_ready and engineering_scope_matches
    )
    ready = receipts["ready"] and inventory_ready and scope_matches
    return {
        "status": "ready" if ready else "blocked",
        "stage": "S0"
        if inventory.parse_failures
        else "S4-S6"
        if inventory.unknown_scopes
        else "S0-S6",
        "ready": ready,
        "engineering_status": "ready" if engineering_ready else "blocked",
        "engineering_ready": engineering_ready,
        "engineering_scope_matches": engineering_scope_matches,
        "stage_receipts": receipts,
        "scope_matches": scope_matches,
        "reason": "A2 阶段、功能、范围或实际交付证据尚未闭合"
        if not ready
        else "A2/S0-S6 静态证据合同已核对",
        "discovered": inventory.discovered_count,
        "legal": inventory.legal_count,
        "observation": inventory.capability_counts.get("observation", 0),
        "unexposed": inventory.unexposed_count,
        "pending": inventory.pending_count,
        "pending_scope": len(inventory.unknown_scopes),
        "unknown_scopes": len(inventory.unknown_scopes),
        "parse_failures": list(inventory.parse_failures),
        "scope_hash": inventory.scope_hash,
        "evidence": "static_check",
        "business_complete": False,
    }


def report(*, root: Path = ROOT, production: Path = PRODUCTION) -> dict[str, Any]:
    """返回静态收口及独立的工程、最终交付状态；status 保持静态含义。"""

    lock_issues: list[str] = []
    try:
        distribution.check_generation_lock()
    except (FileNotFoundError, ValueError) as exc:
        lock_issues.append(str(exc))
    try:
        package_names = tuple(distribution.read_production_files())
    except OSError as exc:
        package_names = ()
        lock_issues.append(f"生产包输入不可读：{exc}")
    package_issues = package_exclusion_violations(package_names)
    encoding_issues = production_encoding_violations(production)
    owner_report = consumer_ir_owner_report()
    hygiene = repo_hygiene.report(root)
    scope_gate = plan_gate(root)
    checks = {
        "generation_lock": not lock_issues,
        "package_exclusions": not package_issues,
        "production_encoding": not encoding_issues,
        "consumer_ir_owner": not owner_report["issues"],
        "cleanliness": hygiene["violation_count"] == 0,
    }
    engineering_complete = all(checks.values()) and scope_gate["engineering_ready"]
    delivery_complete = all(checks.values()) and scope_gate["ready"]
    return {
        "schema": 1,
        "status": "complete" if all(checks.values()) else "incomplete",
        "checks": checks,
        "generation_lock_issues": lock_issues,
        "package_exclusions": package_issues,
        "production_encoding_violations": encoding_issues,
        "consumer_ir_owner": owner_report,
        "cleanliness": hygiene,
        "plan_gate": scope_gate,
        "engineering_complete": engineering_complete,
        "delivery_complete": delivery_complete,
        "delivery_ready": delivery_complete,
        "scope": "静态工程收口；不证明游戏内长期行为、平衡或玩家体验",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--production", type=Path, default=PRODUCTION)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--require-engineering",
        action="store_true",
        help="核对 A2/S0-S5 工程、依赖与功能出口；允许 S6 尚未交付",
    )
    parser.add_argument(
        "--require-plan",
        action="store_true",
        help="核对 A2/S0-S6 及实际发布部署字节；未闭合时返回失败",
    )
    args = parser.parse_args(argv)
    try:
        data = report(root=args.root, production=args.production)
        encoded = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded, encoding="utf-8", newline="\n")
        print(encoded, end="")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"[situated-closeout] 检查失败：{exc}", file=sys.stderr)
        return 2
    if data["status"] != "complete":
        return 1
    if args.require_engineering and not data["engineering_complete"]:
        return 1
    if args.require_plan and not data["delivery_ready"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
