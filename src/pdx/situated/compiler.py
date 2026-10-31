"""统一的处境行动编译器。

处境源只声明能力、压力、机会、承诺和目标；原版信息规则及消费者适配器
仍是业务谓词的唯一来源。本模块把两者登记到同一个有界合同，并在生成期
对已有 ``pdx.decision_rules.RuleSet`` 做一次确定性的优先级编译。运行期
没有 Python 服务、世界扫描或新增的无界状态。
"""

from __future__ import annotations

import hashlib
import math
import re
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from .. import decision_adapters, decision_rules  # noqa: TID252
from ..parser import parse_text  # noqa: TID252
from . import action_instances, commitment, families, ir, opportunity, relations, state
from . import actions as action_source
from . import evidence as evidence_source
from . import goals as goal_source
from .arbitration import Candidate, choose
from .contracts import contract
from .schema import ActionCard, ConsumerContract, EvidenceSpec, Relation

REPO = Path(__file__).resolve().parents[3]
DECISIONS = REPO / "mod" / "decisions"
FACTS = DECISIONS / "facts.toml"
ACTIONS = DECISIONS / "actions.toml"
BASELINE = REPO / "research" / "vanilla-ai" / "1.14.5" / "00_default_strategy.txt"
SUPPORTING_SOURCES = (
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
    "action_families.toml",
)


@dataclass(frozen=True, slots=True)
class ProductionConsumer:
    id: str
    field: tuple[str, ...]
    source: str
    scope: str
    operation: str
    rule_count: int
    max_delta: float
    vanilla_tail: str


@dataclass(frozen=True, slots=True)
class SituatedModel:
    facts: tuple[EvidenceSpec, ...]
    consumers: tuple[ConsumerContract, ...]
    actions: tuple[ActionCard, ...]
    relations: tuple[Relation, ...]
    source_sha256: dict[str, str]
    production_consumers: tuple[ProductionConsumer, ...] = ()
    production_rule_count: int = 0
    goals: tuple[tuple[str, int], ...] = ()
    support_sources: dict[str, dict[str, Any]] | None = None
    action_instances: tuple[action_instances.ActionInstance, ...] = ()
    action_ir: tuple[ir.ActionIR, ...] = ()
    goal_specs: tuple[goal_source.Goal, ...] = ()

    def contract(self) -> dict[str, object]:
        result = contract(self.facts, self.consumers, self.actions, self.relations)
        result["source_fingerprints"] = dict(self.source_sha256)
        result["production"] = {
            "rule_count": self.production_rule_count,
            "consumer_count": len(self.production_consumers),
            "fields": [
                {
                    "id": item.id,
                    "field": ".".join(item.field),
                    "source": item.source,
                    "scope": item.scope,
                    "operation": item.operation,
                    "rule_count": item.rule_count,
                    "max_delta": item.max_delta,
                    "vanilla_tail": item.vanilla_tail,
                    "owner": "situated_kernel",
                    "write_once": True,
                }
                for item in self.production_consumers
            ],
            "goal_ranking": dict(self.goals),
            "unknown": "preserve_unknown_and_fallback_vanilla",
            "player_boundary": "is_ai_only; no player writes",
            "world_scans": 0,
            "runtime_python": False,
            "relationship_depth": 2,
        }
        result["action_instances"] = action_instances.contract(self.action_instances)
        result["ir"] = ir.contract(self.action_ir)
        result["typed_state"] = state.contract()
        supporting = self.support_sources or {}
        result["goals"] = goal_source.contract(self.goal_specs)
        result["opportunities"] = opportunity.contract(
            supporting.get("opportunities.toml", {}).get("opportunities", {})
        )
        result["commitments"] = commitment.contract(
            supporting.get("commitments.toml", {}).get("commitments", {})
        )
        result["action_families"] = {
            "schema": 1,
            "ids": list(families.FAMILIES),
            "definitions": supporting.get("action_families.toml", {}).get("families", {}),
            "classifier": "source_and_field_deterministic",
        }
        return result


def _load_supporting_sources() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name in SUPPORTING_SOURCES:
        path = DECISIONS / name
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != 1:
            raise ValueError(f"辅助合同 {name} schema 必须为 1")
        result[name] = data
    return result


def _reader_facts(model_facts: tuple[EvidenceSpec, ...]) -> tuple[EvidenceSpec, ...]:
    """从 information/adapters 的 readers 补齐事实签名，不复制业务谓词。"""
    by_id = {item.id: item for item in model_facts}
    information = decision_rules.load()
    adapters = decision_adapters.load()
    readers: list[tuple[str, Any, str]] = [
        ("information", reader, "mod/decisions/information.toml") for reader in information.readers
    ]
    for source, policy in adapters.policies:
        readers.extend(("adapter", reader, source) for reader in policy.readers)
    for owner, reader, source in readers:
        if reader.key in by_id:
            item = by_id[reader.key]
            compatible_units = {item.unit, reader.unit} <= {"flag", "boolean"}
            if (item.unit != reader.unit and not compatible_units) or item.scope != reader.scope:
                raise ValueError(f"事实 {reader.key} 与原版 reader 的作用域/单位不一致")
            continue
        trigger = reader.engine
        if reader.argument is not None:
            trigger += f" = {reader.argument}"
        elif reader.kind == "boolean":
            trigger += " = yes"
        by_id[reader.key] = EvidenceSpec(
            id=reader.key,
            identity=f"{owner}:{source}:{reader.key}",
            domain="derived" if reader.engine.startswith("sitai_") else "vanilla",
            source=source,
            scope=reader.scope,
            kind="ratio" if reader.unit == "ratio" else reader.kind,
            unit=reader.unit,
            refresh="consumer",
            unknown="vanilla",
            trigger=trigger,
            minimum=reader.minimum,
            maximum=reader.maximum,
            quality="derived" if reader.engine.startswith("sitai_") else "observed",
        )
    return tuple(by_id[key] for key in sorted(by_id))


def _production_inventory() -> tuple[tuple[ProductionConsumer, ...], int, dict[str, str]]:
    consumers: list[ProductionConsumer] = []
    fingerprints: dict[str, str] = {}
    total = 0
    info = decision_rules.load()
    fingerprints["information"] = info.source_sha256
    for field, rules in info.groups().items():
        consumers.append(
            ProductionConsumer(
                id=f"information:{'.'.join(field)}",
                field=field,
                source="mod/decisions/information.toml",
                scope="root",
                operation=rules[0].operation,
                rule_count=len(rules),
                max_delta=0.5,
                vanilla_tail="retain_qualification_cost_random_execution",
            )
        )
        total += len(rules)
    adapters = decision_adapters.load()
    fingerprints["adapters"] = adapters.source_sha256
    for source, policy in adapters.policies:
        for field, rules in policy.groups().items():
            consumers.append(
                ProductionConsumer(
                    id=f"adapter:{source}:{'.'.join(field)}",
                    field=field,
                    source=source,
                    scope="owner" if policy.actor_path else "root",
                    operation=rules[0].operation,
                    rule_count=len(rules),
                    max_delta=0.5,
                    vanilla_tail="retain_original_qualification_cost_execution",
                )
            )
            total += len(rules)
    consumers.sort(key=lambda item: (item.source, item.field))
    return tuple(consumers), total, fingerprints


def _validate_supporting_sources(sources, consumers, relation_list) -> None:
    raw_relations = sources["relations.toml"].get("relations", [])
    if not isinstance(raw_relations, list):
        raise ValueError("relations.toml 的 relations 必须是列表")
    listed: dict[tuple[str, str, str], tuple[float, str, tuple[str, ...], str]] = {}
    for item in raw_relations:
        if not isinstance(item, dict):
            raise ValueError("relations.toml 含无效关系项")
        raw_key = (item.get("source"), item.get("target"), item.get("kind"))
        strength = item.get("strength")
        scope = item.get("scope", "root")
        condition_facts = item.get("condition_facts", [])
        unknown_policy = item.get("unknown_policy", "vanilla")
        if (
            not all(isinstance(part, str) for part in raw_key)
            or raw_key in listed
            or isinstance(strength, bool)
            or not isinstance(strength, (int, float))
            or not math.isfinite(float(strength))
            or float(strength) <= 0
            or not isinstance(scope, str)
            or not isinstance(condition_facts, list)
            or any(not isinstance(fact, str) for fact in condition_facts)
            or not isinstance(unknown_policy, str)
        ):
            raise ValueError(f"relations.toml 含无效或重复关系：{raw_key}")
        key = cast("tuple[str, str, str]", raw_key)
        listed[key] = (float(strength), scope, tuple(condition_facts), unknown_policy)
    actual = {
        (item.source, item.target, item.kind): (
            item.strength,
            item.scope,
            item.condition_facts,
            item.unknown_policy,
        )
        for item in relation_list
    }
    if set(listed) != set(actual) or any(listed[key] != actual[key] for key in listed):
        raise ValueError("relations.toml 与行动卡关系不一致")
    consumer_fields = {item.field for item in consumers}
    declared = sources["consumers.toml"].get("consumers", {})
    if declared and {item["field"] for item in declared.values()} != consumer_fields:
        raise ValueError("consumers.toml 与行动卡消费者字段不一致")
    arbitration = sources["arbitration.toml"]
    if (
        arbitration.get("unknown_fallback") != "vanilla"
        or arbitration.get("max_candidates", 0) > 32
    ):
        raise ValueError("仲裁合同必须有原版未知回退和 32 个候选上限")
    temporal = sources["temporal.toml"]
    if temporal.get("max_persistent_routes") != 1 or temporal.get("max_reason_codes", 0) > 8:
        raise ValueError("时间合同必须限制持久路线和解释记录")
    localization = sources["localization.toml"]
    if localization.get("fallback") != "none" or len(localization.get("languages", [])) != 11:
        raise ValueError("本地化合同必须覆盖锁定本体的 11 种语言且不允许回退")
    families.load_contract(DECISIONS / "action_families.toml")


def load_model(
    *, facts_path: Path = FACTS, actions_path: Path = ACTIONS, baseline: str | None = None
) -> SituatedModel:
    facts = _reader_facts(evidence_source.load(facts_path))
    consumers, actions = action_source.load(actions_path)
    supporting = _load_supporting_sources()
    relation_list = relations.relations(
        actions,
        supporting["relations.toml"].get("relations", []),
    )
    relations.validate(actions, specs=supporting["relations.toml"].get("relations", []))
    _validate_supporting_sources(supporting, consumers, relation_list)
    fact_ids = {item.id for item in facts}
    relation_fact_ids = {fact for relation in relation_list for fact in relation.condition_facts}
    missing_relation_facts = sorted(relation_fact_ids - fact_ids)
    if missing_relation_facts:
        raise ValueError(f"行动关系引用了未知事实：{missing_relation_facts}")
    for action in actions:
        references = (
            *action.requires_all,
            *action.requires_any,
            *action.blocked_by,
            *action.exit_when,
        )
        missing = sorted(set(references) - fact_ids)
        if missing:
            raise ValueError(f"行动 {action.id} 引用了未知事实：{missing}")
    baseline_text = baseline if baseline is not None else BASELINE.read_text(encoding="utf-8")
    parsed = parse_text(baseline_text)
    if parsed.errors:
        raise ValueError("默认策略底本无法解析")
    available = set(re.findall(r"^\s*([a-z][a-z0-9_]*)\s*=\s*\{", baseline_text, re.MULTILINE))
    missing = [consumer.field for consumer in consumers if consumer.field not in available]
    if baseline is None and missing:
        raise ValueError(f"消费者字段不在默认策略底本：{missing[0]}")
    information = decision_rules.load()
    adapters = decision_adapters.load()
    production, count, production_hashes = _production_inventory()
    instances = action_instances.build(
        information,
        adapters,
        actions,
        consumer_fields={item.id: item.field for item in consumers},
    )
    action_ir = ir.from_rules(
        [("mod/decisions/information.toml", item) for item in information.rules]
        + [(source, item) for source, policy in adapters.policies for item in policy.rules]
    )
    goal_bindings = {
        "survival": ("fiscal_neutrality", "diplomatic_recklessness"),
        "recovery": ("economic_balance", "reform_chance"),
        "capacity": ("economic_balance", "reform_chance"),
        "structure": ("economic_balance", "reform_chance"),
    }

    def _goal_names(raw: object, label: str) -> tuple[str, ...]:
        if raw is None:
            return ()
        if not isinstance(raw, list) or any(not isinstance(item, str) or not item for item in raw):
            raise ValueError(f"goals.toml 的 {label} 必须是非空字符串列表")
        return tuple(raw)

    goal_specs = tuple(
        goal_source.Goal(
            id=key,
            priority=int(value.get("priority", 0)),
            horizon=str(value.get("horizon", "medium")),
            active=True,
            source_pressures=_goal_names(value.get("pressure"), "pressure"),
            source_needs=_goal_names(value.get("need"), "need"),
            consumer_bindings=_goal_names(
                value.get("consumers", list(goal_bindings.get(key, ()))), "consumers"
            ),
            ttl_days=(int(value["ttl_days"]) if type(value.get("ttl_days")) is int else None),
            unknown_policy=(
                value.get("unknown", "vanilla")
                if value.get("unknown", "vanilla") in {"vanilla", "conservative", "lower_tier"}
                else "vanilla"
            ),
        )
        for key, value in sorted(supporting["goals.toml"].get("goals", {}).items())
        if isinstance(value, dict) and type(value.get("priority")) is int
    )
    goals = tuple((item.id, item.priority) for item in goal_specs)
    hashes = {
        "facts": hashlib.sha256(facts_path.read_bytes()).hexdigest(),
        "actions": hashlib.sha256(actions_path.read_bytes()).hexdigest(),
        **production_hashes,
        **{
            name.removesuffix(".toml"): hashlib.sha256((DECISIONS / name).read_bytes()).hexdigest()
            for name in SUPPORTING_SOURCES
        },
    }
    return SituatedModel(
        facts,
        consumers,
        actions,
        relation_list,
        hashes,
        production,
        count,
        goals,
        supporting,
        instances,
        action_ir,
        goal_specs,
    )


def _condition(facts, ids):
    expressions = [facts[item].trigger for item in ids]
    if not expressions:
        return ""
    return expressions[0] if len(expressions) == 1 else "AND = { " + " ".join(expressions) + " }"


def _limit(action, facts, *, relation_guards: tuple[str, ...] = ()):
    all_expr = _condition(facts, action.requires_all)
    any_expr = (
        "OR = { " + " ".join(facts[item].trigger for item in action.requires_any) + " }"
        if action.requires_any
        else ""
    )
    blocked_expr = (
        "NOT = { OR = { " + " ".join(facts[item].trigger for item in action.blocked_by) + " } }"
        if action.blocked_by
        else ""
    )
    return (
        " AND = { "
        + " ".join(
            [
                "is_ai = yes",
                *(item for item in (all_expr, any_expr, blocked_expr) if item),
                *relation_guards,
            ]
        )
        + " }"
    )


def strategy_overlay(model: SituatedModel) -> dict[str, str]:
    facts = {item.id: item for item in model.facts}
    consumers = {item.id: item for item in model.consumers}
    grouped: dict[str, list[ActionCard]] = {item.field: [] for item in model.consumers}
    for action in model.actions:
        grouped[consumers[action.consumer].field].append(action)
    output = {}
    by_id = {item.id: item for item in model.actions}
    relations_by_source: dict[str, list[Relation]] = {}
    for relation in model.relations:
        relations_by_source.setdefault(relation.source, []).append(relation)
    for consumer in model.consumers:
        chosen = sorted(
            grouped[consumer.field], key=lambda item: (-item.stress, -item.opportunity, item.id)
        )[: consumer.budget]
        blocks = []
        for index, action in enumerate(chosen):
            delta = action.base + action.opportunity - action.commitment
            limit = min(action.max_delta, consumer.max_delta)
            delta = max(-limit, min(limit, delta))
            relation_guards: list[str] = []
            complement_effects: list[str] = []
            for relation in relations_by_source.get(action.id, ()):
                target = by_id[relation.target]
                target_guard = _limit(target, facts)
                if relation.condition_facts:
                    relation_guard = _condition(facts, relation.condition_facts)
                    target_guard = f" AND = {{ {relation_guard} {target_guard} }}"
                if relation.kind == "enables":
                    relation_guards.append(target_guard)
                elif relation.kind in {"substitutes", "conflicts"}:
                    relation_guards.append(f"NOT = {{ {target_guard} }}")
                elif relation.kind == "complements":
                    complement_effects.append(
                        f"\n\t\t\tif = {{ limit = {{ ROOT ?= {{ {target_guard} }} }} add = {relation.strength:g} }}"
                    )
            blocks.append(
                f"\t\t# ACTION {action.id} [{action.domain}]; {action.explanation}\n"
                f"\t\t{'if' if index == 0 else 'else_if'} = {{\n\t\t\tlimit = {{ ROOT ?= {{ {_limit(action, facts, relation_guards=tuple(relation_guards))} }} }}\n\t\t\tadd = {delta:g}"
                f"{''.join(complement_effects)}\n\t\t}}\n"
            )
        output[consumer.field] = "".join(blocks)
    return output


def _action_ranks(model):
    goals = dict(model.goals)
    structure_goal = goals.get("structure") or 0
    domain_goal: dict[str, int] = {
        "fiscal": goals.get("survival", 0),
        "military": goals.get("survival", 0),
        "political": goals.get("recovery", 0),
        "economy": goals.get("capacity", 0),
        "education": goals.get("capacity", 0),
    }
    ranks = {
        action.id: max(0, min(2, domain_goal.get(action.domain, structure_goal) // 50))
        for action in model.actions
    }
    for relation in model.relations:
        if relation.kind == "complements":
            ranks[relation.target] = min(2, ranks.get(relation.target, 0) + 1)
        elif relation.kind in {"substitutes", "conflicts"}:
            ranks[relation.target] = max(0, ranks.get(relation.target, 0) - 1)
    return ranks


def compile_policy(
    policy: decision_rules.RuleSet,
    source: object | None = None,
    config_model: SituatedModel | None = None,
):
    """返回 ``(RuleSet, contract)``；谓词沿用原版 RuleSet，字段一次有界写入。"""
    model = config_model or load_model()
    action_ranks = _action_ranks(model)
    action_fields = {
        next(
            (item.field for item in model.consumers if item.id == action.consumer), ""
        ): action_ranks.get(action.id, 0)
        for action in model.actions
    }
    compiled_rules = []
    field_contract = []
    for field, rules in policy.groups().items():
        for rule in rules:
            bump = max(0, min(2, action_fields.get(".".join(rule.field), 0)))
            compiled_rules.append(replace(rule, priority=rule.priority * 3 + bump))
        field_contract.append(
            {
                "field": ".".join(field),
                "source": str(source or "rule_set"),
                "rule_count": len(rules),
                "write_once": True,
                "unknown_fallback": "vanilla",
                "player_fallback": "vanilla",
                "vanilla_tail": "retain_qualification_cost_random_execution",
                "max_rank_adjustment": 2,
            }
        )
    compiled = replace(policy, rules=tuple(sorted(compiled_rules, key=lambda item: item.id)))
    compiled_contract = {
        "schema": 2,
        "rule_set": "pdx.decision_rules.RuleSet",
        "source": str(source or "rule_set"),
        "source_sha256": policy.source_sha256,
        "baseline_sha256": policy.baseline_sha256,
        "active_rule_count": len(compiled.rules),
        "field_count": len(field_contract),
        "production_rule_count": model.production_rule_count,
        "production_consumer_count": len(model.production_consumers),
        "fields": field_contract,
        "goals": dict(model.goals),
        "relations": [
            {
                "source": item.source,
                "target": item.target,
                "kind": item.kind,
                "strength": item.strength,
            }
            for item in model.relations
        ],
        "relationship_depth": 2,
        "unknown": "preserve_unknown_and_fallback_vanilla",
        "player": "is_ai_only",
        "runtime_python": False,
        "world_scans": 0,
        "adjustment_application": "one_matching_rule_per_field; bounded_priority_tiebreak",
    }
    return compiled, compiled_contract


def compile_sources(
    information: decision_rules.RuleSet,
    adapters: decision_adapters.AdapterSet,
    *,
    config_model: SituatedModel | None = None,
) -> tuple[tuple[tuple[str, decision_rules.RuleSet], ...], dict[str, object]]:
    """统一编译 information + adapters 的全部 RuleSet，并返回合同。"""
    model = config_model or load_model()
    compiled: list[tuple[str, decision_rules.RuleSet]] = []
    reports: list[dict[str, object]] = []
    item, report = compile_policy(information, "mod/decisions/information.toml", model)
    compiled.append(("mod/decisions/information.toml", item))
    reports.append(report)
    for source, policy in adapters.policies:
        item, report = compile_policy(policy, source, model)
        compiled.append((source, item))
        reports.append(report)
    return tuple(compiled), {
        "schema": 2,
        "rule_count": sum(len(item.rules) for _, item in compiled),
        "consumer_count": len(model.production_consumers),
        "reports": reports,
        "unknown": "vanilla",
        "player": "vanilla",
        "write_once": True,
        "relationship_depth": 2,
    }


def _action_conditions(action: ActionCard, values: dict[str, object]) -> bool | None:
    """三值求值；未知不伪造负面证据。"""

    def test(name: str) -> bool | None:
        if name not in values:
            return None
        value = values[name]
        return value is True

    required = [test(name) for name in action.requires_all]
    blocked = [test(name) for name in action.blocked_by]
    if any(item is False for item in required) or any(item is True for item in blocked):
        return False
    if any(item is None for item in required + blocked):
        return None
    options = [test(name) for name in action.requires_any]
    if options and all(item is False for item in options):
        return False
    if options and any(item is None for item in options):
        return None
    return True


def _relation_conditions(relation: Relation, values: dict[str, object]) -> bool | None:
    """关系自己的条件采用三值逻辑；未知默认不额外改变原版。"""

    if not relation.condition_facts:
        return True
    states = tuple(
        None if name not in values or type(values[name]) is not bool else values[name]
        for name in relation.condition_facts
    )
    if any(item is False for item in states):
        return False
    if any(item is None for item in states):
        return None
    return True


def evaluate_policy(
    policy: decision_rules.RuleSet,
    values: dict[str, object],
    *,
    is_ai: bool,
    config_model: SituatedModel | None = None,
) -> dict[str, tuple[str, float]]:
    """参考求值：原版字段先选一条规则，再应用一次有界处境增量。

    该函数只用于生成期等价性/反例测试和解释；PDX 产物仍由同一字段的
    ``if/else_if`` 降低。玩家、未知输入、资格失败均返回原版结果。
    """
    if type(is_ai) is not bool:
        raise ValueError("is_ai 必须为明确布尔值")
    baseline = decision_rules.evaluate(policy, values, is_ai=is_ai)
    if not is_ai:
        return baseline
    model = config_model or load_model()
    by_field = {(item.field,): item for item in model.consumers}
    action_by_field: dict[tuple[str, ...], list[ActionCard]] = {}
    for action in model.actions:
        consumer = next((item for item in model.consumers if item.id == action.consumer), None)
        if consumer is not None:
            action_by_field.setdefault((consumer.field,), []).append(action)
    result = dict(baseline)
    for field, (rule_id, raw) in baseline.items():
        actions = action_by_field.get((field,))
        if not actions:
            continue
        candidates: list[tuple[ActionCard, float, Candidate]] = []
        for action in actions:
            status = _action_conditions(action, values)
            if status is not True:
                continue
            pressure = 1.0 if any(values.get(name) is True for name in action.consumes) else 0.0
            relation_bonus = 0.0
            relation_blocked = False
            for relation in model.relations:
                if relation.source != action.id:
                    continue
                relation_state = _relation_conditions(relation, values)
                if relation_state is False or (
                    relation_state is None
                    and (
                        relation.unknown_policy in {"vanilla", "lower_tier"}
                        or relation.kind in {"complements", "enables"}
                    )
                ):
                    continue
                target = next(item for item in model.actions if item.id == relation.target)
                target_status = _action_conditions(target, values)
                if relation.kind in {"substitutes", "conflicts"} and target_status is True:
                    relation_blocked = True
                elif relation.kind == "complements" and target_status is True:
                    relation_bonus += relation.strength
            if relation_blocked:
                continue
            candidate = Candidate(
                action_id=action.id,
                crisis_protection=max(0.0, action.stress * pressure),
                bottleneck_relief=max(0.0, action.base),
                capability_gain=max(0.0, action.opportunity) + relation_bonus,
                feasibility=1.0,
                substitute_availability=1.0 if relation_bonus else 0.0,
                opportunity_value=action.opportunity,
                commitment_cost=action.commitment * pressure,
                inertia=0.0,
                # ``choose`` supplies the shared score components; this term
                # preserves negative base deltas without counting positive base
                # relief twice.
                base_delta=action.base - max(0.0, action.base),
            )
            candidates.append((action, 0.0, candidate))
        if not candidates:
            continue
        # All candidates are ranked together.  This keeps the reference path
        # identical to the finite arbitration contract instead of selecting
        # independently and then applying an accidental reverse tie-break.
        arbitration = choose(
            tuple(item[2] for item in candidates),
            max_delta=max(item[0].max_delta for item in candidates),
        )
        if arbitration.action_id is None:
            continue
        selected = next(item for item in candidates if item[0].id == arbitration.action_id)
        action = selected[0]
        delta = max(-action.max_delta, min(action.max_delta, arbitration.delta))
        contract_item = by_field.get((field,))
        if contract_item is not None:
            delta = max(-contract_item.max_delta, min(contract_item.max_delta, delta))
        if action.base == 0 and delta == 0:
            continue
        result[field] = (
            rule_id,
            raw + delta if action.base < 0 or raw < 0 else raw * (1.0 + delta / 100.0),
        )
    return result


def audit(model: SituatedModel) -> list[str]:
    problems = [
        f"消费者 {consumer.id} 超过行动预算"
        for consumer in model.consumers
        if sum(1 for action in model.actions if action.consumer == consumer.id) > consumer.budget
    ]
    if len(model.actions) > 32:
        problems.append("行动候选超过 32 个静态上限")
    if model.production_rule_count and model.production_rule_count < 1401:
        problems.append("生产事实源未覆盖 information + adapters 全部规则")
    return problems
