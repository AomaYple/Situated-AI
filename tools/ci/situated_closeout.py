"""D11--D13 的静态工程收口报告。

这个入口只汇总已有的生成锁、发行包输入、生产 metadata 和仓库卫生
检查；它不重生成生产树、不启动游戏，也不把静态通过写成行为验收。
``--require-engineering`` 核对 D0--D13 工程前置，供 D14 交付前使用；
``--require-plan`` 核对包含 D14 实际交付收据的最终门。
报告默认输出到 stdout，``--output`` 只写被忽略的报告路径。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]

# 该文件既可作为 ``python -m tools.ci.situated_closeout`` 运行，也应能被
# 贡献流程直接调用。直接执行脚本时，Python 默认只把 ``tools/ci`` 放入
# sys.path；先把仓库根加入路径，保证两种入口使用同一份源码，而不是
# 因调用方式不同产生导入失败。
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from pdx import decisions, distribution  # noqa: E402
from pdx.situated import vanilla_inventory  # noqa: E402
from pdx.situated.receipts import StageReceipt, validate_receipt  # noqa: E402
from tools.ci import repo_hygiene  # noqa: E402

PRODUCTION = distribution.decisions.PRODUCT
TEXT_SUFFIXES = frozenset({".json", ".md", ".toml", ".txt", ".yml", ".yaml"})
PACKAGE_FORBIDDEN_PARTS = frozenset(
    {"probe", "probes", "cache", "caches", "logs", "log", "tools", "research", ".venv"}
)
PACKAGE_FORBIDDEN_SUFFIXES = frozenset({".py", ".pyc", ".pyo", ".log"})
PLAN_PATH = Path("docs/design/exec/mod重设计-实施计划.md")
# 计划 0.4 的实际依赖图；D6--D8 是三个依赖 D5 的分支。
STAGE_DEPENDENCIES = {
    "D0": (),
    **{f"D{i}": (f"D{i - 1}",) for i in range(1, 7)},
    "D7": ("D5",),
    "D8": ("D5",),
    "D9": ("D6", "D7", "D8"),
    **{f"D{i}": (f"D{i - 1}",) for i in range(10, 15)},
}
ENGINEERING_STAGES = tuple(stage for stage in STAGE_DEPENDENCIES if stage != "D14")


def _receipt_issues(data: dict[str, Any], identity: str) -> list[str]:
    """复用生产 StageReceipt 合同；unknown/缺字段不转换为成功。"""

    issues: list[str] = []
    try:
        # 阶段摘要使用 ``stage_id``，而嵌套步骤使用 ``step_id``；两者
        # 共享 StageReceipt 的其余字段。历史收据有时只写 stage_id，
        # 这里将其规范化为校验器需要的 step_id，而不是把合法摘要误报为
        # 缺字段。身份仍由调用方严格核对。
        normalized = dict(data)
        normalized.setdefault("step_id", normalized.get("stage_id", identity))
        receipt = StageReceipt(
            **{key: normalized[key] for key in StageReceipt.__dataclass_fields__}
        )
        issues.extend(validate_receipt(receipt, strict=True))
        if receipt.step_id != identity:
            issues.append("step_id 与收据身份不一致")
        if receipt.status != "verified":
            issues.append(f"status={receipt.status}")
        if not isinstance(receipt.failures, list) or receipt.failures:
            issues.append("failures 必须显式为空列表")
        issues.extend(
            f"{field} 必须是列表"
            for field in ("output_paths", "evidence_ids", "dependencies")
            if not isinstance(data[field], list)
        )
        if not isinstance(receipt.input_hashes, dict):
            issues.append("input_hashes 必须是对象")
        # 无前置阶段的 D0 仍须显式声明 dependencies=[]。
        if identity.startswith("D0") and data["dependencies"] == []:
            issues = [issue for issue in issues if issue != "dependencies"]
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        issues.append(f"StageReceipt 无效：{exc}")
    return issues


def _feature_issues(value: Any, path: str = "receipt") -> list[str]:
    """公开机器收据内残留功能缺口；零计数不能覆盖非空逐项证据。"""

    issues: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            location = f"{path}.{key}"
            if key.removesuffix("_count") in {
                "pending",
                "blocked",
                "unknown",
                "unclassified",
                "parse_failures",
            } and child not in ([], {}, 0):
                issues.append(location)
            if key in {"status", "scope_status"} and (
                not isinstance(child, str)
                or child not in {"verified", "complete", "implemented", "engine_unexposed"}
            ):
                issues.append(f"{location}={child}")
            issues.extend(_feature_issues(child, location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            issues.extend(_feature_issues(child, f"{path}[{index}]"))
    return issues


def stage_receipt_report(root: Path = REPO) -> dict[str, Any]:
    """读取唯一阶段摘要及其 JSON 收据；散文、勾选和合并摘要不能关账。

    verified 候选须在 D<n>-结果.md 中包含一个带 stage_id 的 JSON 对象，
    沿用 StageReceipt 字段及 AuditResult 的 receipts、rows、scope_hash 和
    pending/blocked/unclassified。每个计划命名步骤均须有收据；输入哈希
    须包含前置摘要原始 SHA-256。这里只核对收据合同，不重新执行其见证。
    工程状态只聚合 D0--D13；D14 的问题仍完整报告并阻止最终交付。
    """

    plan_issues: list[str] = []
    try:
        plan = (root / PLAN_PATH).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        plan = ""
        plan_issues.append(f"计划不可读：{exc}")
    stages: dict[str, Any] = {}
    missing: list[str] = []
    payloads: dict[str, dict[str, Any]] = {}
    for stage, dependencies in STAGE_DEPENDENCIES.items():
        path = Path(f"docs/design/exec/{stage}-结果.md")
        row: dict[str, Any] = {
            "receipt_path": path.as_posix(),
            "status": "unknown",
            "ready": False,
            "dependencies": list(dependencies),
            "issues": [],
            "dependency_failures": [],
        }
        stages[stage] = row
        section = re.search(rf"^## {stage}[：:].*?(?=^## |\Z)", plan, re.MULTILINE | re.DOTALL)
        stage_plan = section[0] if section else ""
        plan_status = re.search(r"状态：\*\*\s*`([a-z_]+)`", stage_plan)
        row["plan_status"] = plan_status[1] if plan_status else "unknown"
        if row["plan_status"] != "verified":
            row["issues"].append("计划阶段尚未 verified")
        plan_dependencies = re.search(r"依赖：\*\*\s*([^；\n]+)", stage_plan)
        if (
            not plan_dependencies
            or tuple(re.findall(r"\bD\d+\b", plan_dependencies[1])) != dependencies
        ):
            row["issues"].append("计划依赖图缺失或已变化，需复核收口合同")
        required_steps = set(re.findall(rf"^\| ({stage}\.\d+) \|", plan, re.MULTILINE))
        if not required_steps:
            row["issues"].append("计划缺少本阶段命名步骤")
        try:
            raw = (root / path).read_bytes()
            text = raw.decode("utf-8")
            row["sha256"] = hashlib.sha256(raw).hexdigest()
        except FileNotFoundError:
            missing.append(stage)
            row["issues"].append("阶段收据缺失")
            continue
        except (OSError, UnicodeError) as exc:
            row["issues"].append(f"阶段收据不可读：{exc}")
            continue
        # 当前真实摘要的状态也保留在报告中；不能因缺机器报告而隐藏 incomplete。
        declared = re.search(r"(?:状态|status)\s*[：:]\s*`?([a-z_]+)", text)
        if declared:
            row["status"] = declared[1]
        candidates = []
        for block in re.findall(r"^```json\s*\n(.*?)^```", text, re.MULTILINE | re.DOTALL):
            try:
                item = json.loads(block)
            except ValueError:
                row["issues"].append("JSON 收据无法解析")
                continue
            if isinstance(item, dict) and "stage_id" in item:
                candidates.append(item)
        if len(candidates) != 1:
            row["issues"].append("必须有且只有一份带 stage_id 的 JSON 阶段收据")
            continue
        data = candidates[0]
        payloads[stage] = data
        if declared and declared[1] != data.get("status"):
            row["issues"].append("摘要状态与机器收据不一致")
        row["status"] = data.get("status", "unknown")
        if data["stage_id"] != stage:
            row["issues"].append("stage_id 与文件身份不一致")
        row["issues"].extend(_receipt_issues(data, stage))
        if data.get("dependencies") != list(dependencies):
            row["issues"].append("dependencies 与计划依赖不一致")
        # 采用现有 AuditResult 的逐项功能结果，不要求另一套布尔通过表。
        for field in ("pending", "blocked", "unclassified", "rows"):
            if not isinstance(data.get(field), list):
                row["issues"].append(f"缺少审计字段 {field}")
        if data.get("scope_status") != "verified":
            row["issues"].append("scope_status 尚未 verified")
        steps = data.get("receipts")
        if not isinstance(steps, list):
            steps = []
        ids = [
            item["step_id"]
            for item in steps
            if isinstance(item, dict) and isinstance(item.get("step_id"), str)
        ]
        if len(ids) != len(steps) or len(set(ids)) != len(ids) or set(ids) != required_steps:
            row["issues"].append("步骤收据存在缺失、重复或计划外身份")
        for item in steps:
            if isinstance(item, dict):
                row["issues"].extend(_receipt_issues(item, str(item.get("step_id", ""))))
        row["issues"].extend(_feature_issues(data))
    for stage, row in stages.items():
        data = payloads.get(stage, {})
        hashes = data.get("input_hashes")
        if not isinstance(hashes, dict):
            hashes = {}
        scope_hash = data.get("scope_hash")
        row["scope_hash"] = scope_hash
        if not isinstance(scope_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", scope_hash):
            row["issues"].append("缺少有效 scope_hash")
        for dependency in row["dependencies"]:
            prior = stages[dependency]
            if not prior["ready"]:
                row["dependency_failures"].append(f"{dependency} 未关闭")
            if not prior.get("sha256") or prior["sha256"] not in hashes.values():
                row["dependency_failures"].append(f"{dependency} 收据哈希缺失或失效")
            if scope_hash != prior.get("scope_hash"):
                row["dependency_failures"].append(f"{dependency} 范围哈希不一致")
        row["ready"] = not row["issues"] and not row["dependency_failures"]
    engineering_unfinished = [stage for stage in ENGINEERING_STAGES if not stages[stage]["ready"]]
    engineering_ready = not plan_issues and not engineering_unfinished
    ready = engineering_ready and stages["D14"]["ready"]
    return {
        "status": "ready" if ready else "blocked",
        "ready": ready,
        "engineering_status": "ready" if engineering_ready else "blocked",
        "engineering_ready": engineering_ready,
        "engineering_unfinished_stages": engineering_unfinished,
        "dependency_source": PLAN_PATH.as_posix() + "#0.4",
        "plan_issues": plan_issues,
        "stages": stages,
        "missing_receipts": missing,
        "unfinished_stages": [stage for stage, row in stages.items() if not row["ready"]],
    }


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


def plan_gate(root: Path = REPO) -> dict[str, Any]:
    """分别核对 D0--D13 工程前置与 D0--D14 交付，均保留 D0 独立范围门。"""

    receipts = stage_receipt_report(root)
    try:
        inventory = vanilla_inventory.discover()
    except (OSError, ValueError) as exc:
        return {
            "status": "blocked",
            "stage": "D0",
            "reason": str(exc),
            "discovered": None,
            "pending": None,
            "pending_scope": None,
            "parse_failures": [],
            "scope_hash": None,
            "evidence": "static_check",
            "ready": False,
            "engineering_status": "blocked",
            "engineering_ready": False,
            "engineering_scope_matches": False,
            "scope_matches": False,
            "stage_receipts": receipts,
        }
    # D0 只冻结发现分母和字段级作用域。实现 pending 是后续 D4--D13
    # 的逐面责任输入，不能在 D0 入口把它误当作范围发现失败；未知
    # actor/target/operation 或解析失败才阻止独立范围收口。
    inventory_ready = not (inventory.unknown_scopes or inventory.parse_failures)
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
    status = "ready" if ready else "blocked"
    return {
        "status": status,
        "stage": "D0-D14" if inventory_ready else "D0",
        "ready": ready,
        "engineering_status": "ready" if engineering_ready else "blocked",
        "engineering_ready": engineering_ready,
        "engineering_scope_matches": engineering_scope_matches,
        "stage_receipts": receipts,
        "scope_matches": scope_matches,
        "reason": (
            "阶段收据、依赖或功能门尚未全部关闭"
            if status == "blocked"
            else "D0-D14 收据、依赖与功能门均已核对"
        ),
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
    }


def report(*, root: Path = REPO, production: Path = PRODUCTION) -> dict[str, Any]:
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
    parser.add_argument("--root", type=Path, default=REPO)
    parser.add_argument("--production", type=Path, default=PRODUCTION)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--require-engineering",
        action="store_true",
        help="核对 D0-D13 工程前置、依赖与功能门；允许 D14 尚未交付",
    )
    parser.add_argument(
        "--require-plan",
        action="store_true",
        help="核对 D0-D14 收据、依赖与功能门；未闭合时返回失败",
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
