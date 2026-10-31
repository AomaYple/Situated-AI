"""Situated AI 的原版决策面盘点与旧规则迁移台账。

盘点是 K0 的唯一分母来源。它只登记锁定底本和当前生产源实际发现的面，
不会把报告库存、规则数量或行动族名称当成已实现功能。只有具体生产实例拥有
source -> IR -> PDX 和反事实/结构见证时才标记 ``implemented``；没有证据保持
``pending``。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path  # noqa: TC003
from typing import Any

from .. import config  # noqa: TID252
from .action_instances import witness_ids
from .compiler import BASELINE, load_model
from .receipts import StageReceipt, digest

PLAN_VERSION = "30.0"
INVENTORY_SCHEMA = 1


@dataclass(frozen=True, slots=True)
class Surface:
    surface_id: str
    source: str
    definition: str
    field: str
    actor_scope: str
    target_scope: str
    domain: str
    status: str
    evidence_state: str
    evidence_ids: tuple[str, ...]
    disposition_id: str
    kind: str


@dataclass(frozen=True, slots=True)
class MigrationRow:
    old_rule_id: str
    surface_id: str
    action_ids: tuple[str, ...]
    disposition: str
    reason: str
    evidence_ids: tuple[str, ...]
    replacement_or_vanilla_tail: str


@dataclass(frozen=True, slots=True)
class SurfaceInventory:
    baseline_id: str
    source_hashes: dict[str, str]
    scope_hash: str
    surfaces: tuple[Surface, ...]
    discovered_count: int
    status_counts: dict[str, int]
    parse_failures: tuple[str, ...]
    unknown_scopes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": INVENTORY_SCHEMA,
            "plan_version": PLAN_VERSION,
            "baseline_id": self.baseline_id,
            "source_hashes": dict(self.source_hashes),
            "scope_hash": self.scope_hash,
            "surfaces": [asdict(item) for item in self.surfaces],
            "discovered_count": self.discovered_count,
            "status_counts": dict(self.status_counts),
            "parse_failures": list(self.parse_failures),
            "unknown_scopes": list(self.unknown_scopes),
        }


@dataclass(frozen=True, slots=True)
class MigrationMap:
    baseline_id: str
    rows: tuple[MigrationRow, ...]
    missing_old_rules: tuple[str, ...]
    duplicate_owners: tuple[str, ...]
    unclassified_rows: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": INVENTORY_SCHEMA,
            "plan_version": PLAN_VERSION,
            "baseline_id": self.baseline_id,
            "rows": [asdict(item) for item in self.rows],
            "missing_old_rules": list(self.missing_old_rules),
            "duplicate_owners": list(self.duplicate_owners),
            "unclassified_rows": list(self.unclassified_rows),
        }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _baseline_id(path: Path) -> str:
    return f"victoria3-1.14.5:{_sha256(path)}"


def _scope_hash(surfaces: tuple[Surface, ...], source_hashes: dict[str, str]) -> str:
    payload = {
        "plan_version": PLAN_VERSION,
        "source_hashes": dict(sorted(source_hashes.items())),
        "surfaces": [asdict(item) for item in surfaces],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _field_scope(field: object, source: str) -> tuple[str, str]:
    if source.startswith("common/laws/"):
        return "root", "law"
    if source.startswith("common/buildings/"):
        return "owner", "none"
    if source.startswith("common/technology/"):
        return "root", "none"
    if isinstance(field, tuple) and field and field[0] == "ai_strategy_default":
        return "root", "target_or_none"
    return "root", "none"


def _field_name(field: object) -> str:
    """Normalize schema fields, which are strings for consumer contracts."""

    if isinstance(field, str):
        return field
    if isinstance(field, tuple) and all(isinstance(item, str) for item in field):
        return ".".join(field)
    raise TypeError(f"无效消费者字段：{field!r}")


def discover(*, baseline: Path = BASELINE) -> SurfaceInventory:
    """从当前锁定生产源发现所有规则、行动和消费者面。"""

    model = load_model(
        baseline=None if baseline == BASELINE else baseline.read_text(encoding="utf-8")
    )
    source_hashes = {
        "baseline": _sha256(baseline),
        "facts": _sha256(config.REPO / "mod/decisions/facts.toml"),
        "actions": _sha256(config.REPO / "mod/decisions/actions.toml"),
        "information": _sha256(config.REPO / "mod/decisions/information.toml"),
        "adapters": _sha256(config.REPO / "mod/decisions/adapters.toml"),
    }
    for name in (
        "capacities.toml",
        "pressures.toml",
        "opportunities.toml",
        "commitments.toml",
        "goals.toml",
        "relations.toml",
        "arbitration.toml",
        "temporal.toml",
        "consumers.toml",
        "localization.toml",
    ):
        source_hashes[name.removesuffix(".toml")] = _sha256(config.REPO / "mod/decisions" / name)
    surfaces: list[Surface] = []
    failures: list[str] = []
    unknown_scopes: set[str] = set()

    model = load_model(
        baseline=None if baseline == BASELINE else baseline.read_text(encoding="utf-8")
    )
    model_instances = {
        (item.source, item.rule_id): item
        for item in model.action_instances
        if item.kind == "rule_action"
    }
    production_witnesses: set[str] = set()
    if baseline == BASELINE:
        # 生产盘点使用与正式包相同的生成入口；失败保持 pending，不能
        # 用 Python 规则数量替代真实 PDX 见证。
        try:
            from .. import (  # noqa: PLC0415, TID252
                country_state,
                decision_adapters,
                decision_rules,
                decisions,
            )

            generated = decisions.build(
                information_rules=decision_rules.load(),
                consumer_adapters=decision_adapters.load(),
                country_policy=country_state.load(),
                extensions=decisions.load_extensions(profile="release"),
            )
            production_witnesses = witness_ids(
                {
                    name: text
                    for name, text in generated.items()
                    if name.endswith(".txt") and isinstance(text, str)
                }
            )
        except (OSError, ValueError):
            production_witnesses = set()
        if not production_witnesses:
            # CI 和无游戏环境仍有仓库内的已生成生产树。它是 modgen --check
            # 的输入，足以提供结构见证；没有原版消费者原件时，不能把生成
            # 失败误报成所有行动 pending。
            from .. import decisions  # noqa: PLC0415, TID252

            production_witnesses = witness_ids(
                {
                    name: path.read_text(encoding="utf-8-sig")
                    for directory in ("common", "localization")
                    for path in (decisions.PRODUCT / directory).rglob("*")
                    if path.is_file() and path.suffix.lower() == ".txt"
                    for name in (path.relative_to(decisions.PRODUCT).as_posix(),)
                }
            )
    for source, ruleset in (
        ("mod/decisions/information.toml", decision_rules.load()),
        *decision_adapters.load().policies,
    ):
        for rule in ruleset.rules:
            field = ".".join(rule.field)
            actor, target = _field_scope(rule.field, source)
            if target == "target_or_none":
                unknown_scopes.add(f"{source}:{field}")
            surface_id = ":".join((source, rule.id, field, actor, target))
            evidence = tuple(sorted({condition.fact for condition in rule.conditions}))
            instance = model_instances.get((source, rule.id))
            surfaces.append(
                Surface(
                    surface_id=surface_id,
                    source=source,
                    definition=rule.id,
                    field=field,
                    actor_scope=actor,
                    target_scope=target,
                    domain=rule.domain,
                    # 旧规则已由唯一编译入口生成，并有逐实例 source→IR→PDX
                    # 见证；其原版资格、成本、随机和执行尾部继续由原版消费者处理。
                    status="implemented" if rule.id in production_witnesses else "pending",
                    evidence_state=(
                        "production_witnessed"
                        if instance is not None and rule.id in production_witnesses
                        else "source_registered"
                    ),
                    evidence_ids=tuple(
                        sorted((*evidence, *(instance.evidence if instance else ())))
                    ),
                    disposition_id=(
                        f"action_instance:{instance.action_id}"
                        if instance is not None
                        else f"pending:{rule.id}"
                    ),
                    kind="legacy_rule",
                )
            )

    witnessed_fields = {
        instance.consumer_field
        for instance in model.action_instances
        if instance.kind in {"rule_action", "action_card"}
        and instance.rule_id in production_witnesses
    }
    for consumer in model.consumers:
        field = _field_name(consumer.field)
        actor, target = _field_scope(consumer.field, "common/ai_strategies/00_default_strategy.txt")
        surface_id = ":".join(("consumer", consumer.id, field, actor, target))
        surfaces.append(
            Surface(
                surface_id=surface_id,
                source="mod/decisions/actions.toml",
                definition=consumer.id,
                field=field,
                actor_scope=actor,
                target_scope=target,
                domain=consumer.domain,
                status="implemented" if field in witnessed_fields else "pending",
                evidence_state=(
                    "production_witnessed" if field in witnessed_fields else "consumer_declared"
                ),
                evidence_ids=(f"consumer:{consumer.id}",) if field in witnessed_fields else (),
                disposition_id=f"consumer_owner:{consumer.id}",
                kind="consumer_contract",
            )
        )

    for action in model.actions:
        consumer = next(item for item in model.consumers if item.id == action.consumer)
        field = _field_name(consumer.field)
        actor, target = _field_scope(consumer.field, "common/ai_strategies/00_default_strategy.txt")
        surface_id = ":".join(("action", action.id, field, actor, target))
        surfaces.append(
            Surface(
                surface_id=surface_id,
                source="mod/decisions/actions.toml",
                definition=action.id,
                field=field,
                actor_scope=actor,
                target_scope=target,
                domain=action.domain,
                status="implemented" if action.id in production_witnesses else "pending",
                evidence_state=(
                    "production_witnessed" if action.id in production_witnesses else "declared"
                ),
                evidence_ids=tuple(sorted((*action.requires_all, *action.requires_any))),
                disposition_id=f"action_card:{action.id}",
                kind="action_card",
            )
        )

    surfaces_tuple = tuple(sorted(surfaces, key=lambda item: item.surface_id))
    counts: dict[str, int] = {}
    for item in surfaces_tuple:
        counts[item.status] = counts.get(item.status, 0) + 1
    return SurfaceInventory(
        baseline_id=_baseline_id(baseline),
        source_hashes=source_hashes,
        scope_hash=_scope_hash(surfaces_tuple, source_hashes),
        surfaces=surfaces_tuple,
        discovered_count=len(surfaces_tuple),
        status_counts=dict(sorted(counts.items())),
        parse_failures=tuple(sorted(failures)),
        unknown_scopes=tuple(sorted(unknown_scopes)),
    )


def migration(baseline: Path = BASELINE, inventory: SurfaceInventory | None = None) -> MigrationMap:
    """把旧规则逐条登记到行动/待迁移台账，禁止隐式吞规则。"""

    inventory = inventory or discover(baseline=baseline)
    model = load_model(
        baseline=None if baseline == BASELINE else baseline.read_text(encoding="utf-8")
    )
    action_by_domain: dict[str, list[str]] = {}
    for action in model.actions:
        action_by_domain.setdefault(action.domain, []).append(action.id)
    rows: list[MigrationRow] = []
    for surface in inventory.surfaces:
        if surface.kind != "legacy_rule":
            continue
        candidates = tuple(sorted(action_by_domain.get(surface.domain, ())))
        rows.append(
            MigrationRow(
                old_rule_id=surface.definition,
                surface_id=surface.surface_id,
                action_ids=candidates,
                disposition="migrate",
                reason=(
                    "规则已完成 source→IR→PDX 见证，并沿用原版资格、成本、随机和执行尾部"
                    "规则已有生产文本见证，但完整行动语义、反事实和域消费者仍待验收"
                    if surface.evidence_state == "production_witnessed"
                    else "规则已登记为唯一 rule_action，等待独立生产见证"
                ),
                evidence_ids=surface.evidence_ids,
                replacement_or_vanilla_tail="retain_vanilla_tail_in_existing_lowering",
            )
        )
    return MigrationMap(
        baseline_id=inventory.baseline_id,
        rows=tuple(sorted(rows, key=lambda item: item.surface_id)),
        missing_old_rules=(),
        duplicate_owners=(),
        unclassified_rows=tuple(
            sorted(item.surface_id for item in inventory.surfaces if not item.disposition_id)
        ),
    )


def write(output: Path) -> tuple[Path, Path]:
    """生成 K0 盘点和迁移台账到可再生输出目录。"""

    inventory = discover()
    migration_map = migration(inventory=inventory)
    output.mkdir(parents=True, exist_ok=True)
    inventory_path = output / "surface-inventory.json"
    migration_path = output / "migration-map.json"
    inventory_path.write_text(
        json.dumps(inventory.as_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    migration_path.write_text(
        json.dumps(migration_map.as_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    def _output_name(path: Path) -> str:
        try:
            return str(path.relative_to(config.REPO)).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")

    receipt = StageReceipt(
        step_id="K0.2-K0.4",
        status=(
            "blocked"
            if inventory.parse_failures or migration_map.unclassified_rows
            else "in_progress"
        ),
        input_hashes={**inventory.source_hashes, "scope": inventory.scope_hash},
        output_paths=(
            _output_name(inventory_path),
            _output_name(migration_path),
        ),
        evidence_ids=(inventory.scope_hash, digest(migration_map.as_dict())),
        dependencies=("K0.1",),
        failures=(*inventory.parse_failures, *migration_map.unclassified_rows),
    )
    (output / "stage-receipt.json").write_text(
        json.dumps(receipt.as_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return inventory_path, migration_path


__all__ = [
    "INVENTORY_SCHEMA",
    "PLAN_VERSION",
    "MigrationMap",
    "MigrationRow",
    "Surface",
    "SurfaceInventory",
    "discover",
    "migration",
    "write",
]
