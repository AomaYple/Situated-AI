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
from typing import TYPE_CHECKING, Any, cast

from .. import decision_adapters, decision_interfaces, decision_rules  # noqa: TID252
from ..model import Block  # noqa: TID252
from ..parser import parse_text  # noqa: TID252
from . import (
    action_instances,
    bindings,
    commitment,
    decision_ir,
    domain_coverage,
    families,
    ir,
    joint_chain_contract,
    layers,
    migration_baseline,
    opportunity,
    relations,
    state,
    support_signals,
)
from . import actions as action_source
from . import evidence as evidence_source
from . import goals as goal_source
from .contracts import contract
from .expressions import Truth, truth_all, truth_any, truth_not
from .schema import ActionCard, ConsumerContract, CostPredicate, EvidenceSpec, Relation

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .decision_ir import ConsumerIRBundle

REPO = Path(__file__).resolve().parents[3]
DECISIONS = REPO / "mod" / "decisions"
FACTS = DECISIONS / "facts.toml"
ACTIONS = DECISIONS / "actions.toml"
LAYERS = DECISIONS / "action_layers.toml"
BINDINGS = DECISIONS / "action_bindings.toml"
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
    "action_layers.toml",
    "action_bindings.toml",
    "domain_actions.toml",
)
_RANK_ORDER = ("need_tier", "net_benefit", "stress", "opportunity", "goal_priority", "action_id")


def evaluation_contexts(text: str) -> dict[str, decision_ir.EvaluationContext]:
    """Observe exact field-local vanilla comments without changing writer IDs."""
    source = "common/ai_strategies/00_default_strategy.txt"
    # name, engine type, semantic role, exact documentary statement
    common = ("root", "country", "actor", "root = country")
    specs = {
        "subject_value": (
            (
                "root",
                "country",
                "actor",
                "root is the AI doing the evaluation, scope:target_country is prospective subject",
            ),
            (
                "target_country",
                "country",
                "target",
                "root is the AI doing the evaluation, scope:target_country is prospective subject",
            ),
        ),
        "become_subject_value": (
            (
                "root",
                "country",
                "actor",
                "root is the AI doing the evaluation, scope:overlord is prospective overlord",
            ),
            (
                "overlord",
                "country",
                "target",
                "root is the AI doing the evaluation, scope:overlord is prospective overlord",
            ),
        ),
        "interest_group_government_weight": (
            common,
            ("interest_group", "interest_group", "candidate", "scope:interest_group = IG"),
        ),
        "negotiation_chance": (
            common,
            (
                "interest_group",
                "interest_group",
                "candidate",
                "scope:interest_group = IG to negotiate with",
            ),
            ("law", "law", "auxiliary", "scope:law = law type being enacted"),
            (
                "amenability",
                "scalar",
                "auxiliary",
                "scope:amenability = IG amenability to negotiation divided by MAX_AMENABILITY (ie, if MAX_AMENABILITY is 100 and IG amenability is 50, this value will be 0.5)",
            ),
            (
                "advance_chance",
                "scalar",
                "auxiliary",
                "scope:advance_chance = Chance to advance law enactment",
            ),
            (
                "stall_chance",
                "scalar",
                "auxiliary",
                "scope:stall_chance = Chance for law enactment to stall",
            ),
        ),
        "state_value": (
            common,
            ("target_state", "state", "target", "scope:target_state = state"),
            ("target_country", "country", "auxiliary", "scope:target_country = state owner"),
        ),
    }
    parsed = parse_text(text)
    if parsed.errors:
        raise ValueError("求值上下文默认策略底本无法解析")
    definitions = [item for item in parsed.root.assignments() if item.key == "ai_strategy_default"]
    if len(definitions) != 1:
        return {
            field: decision_ir.EvaluationContext(status="ambiguous" if definitions else "unknown")
            for field in specs
        }
    if (
        not isinstance(definitions[0].value, Block)
        or definitions[0].op != "="
        or definitions[0].prefix is not None
    ):
        return {field: decision_ir.EvaluationContext(status="unknown") for field in specs}
    result = {}
    lines = text.splitlines()
    for field, expected in specs.items():
        fields = [item for item in definitions[0].value.assignments() if item.key == field]
        if len(fields) != 1:
            result[field] = decision_ir.EvaluationContext(
                status="ambiguous" if fields else "unknown"
            )
            continue
        if fields[0].op != "=" or fields[0].prefix is not None:
            result[field] = decision_ir.EvaluationContext(status="unknown")
            continue
        field_line = lines[fields[0].line - 1].strip()
        if re.match(rf"{re.escape(field)}\s*=", field_line) is None:
            # A same-line preceding assignment has no reliable field-local
            # comment boundary; never borrow the previous field's evidence.
            result[field] = decision_ir.EvaluationContext(status="unknown")
            continue
        comments: dict[str, list[int]] = {}
        for index in range(fields[0].line - 2, definitions[0].line - 1, -1):
            line = lines[index].strip()
            if line and not line.startswith("#"):
                break
            if line.startswith("#"):
                comments.setdefault(line[1:].strip(), []).append(index + 1)
        expected_markers = {marker for *_, marker in expected}
        contradictory = any(
            re.search(r"\broot\s*(?:=|is\b)|\bscope\s*:\s*[a-z][a-z0-9_]*\s*(?:=|is\b)", marker)
            and marker not in expected_markers
            for marker in comments
        )
        if contradictory:
            result[field] = decision_ir.EvaluationContext(status="unknown")
            continue
        if any(len(comments.get(marker, ())) != 1 for *_, marker in expected):
            result[field] = decision_ir.EvaluationContext(status="unknown")
            continue
        bindings = tuple(
            decision_ir.ContextBinding(name, kind, role, source, comments[marker][0])
            for name, kind, role, marker in expected
        )
        result[field] = decision_ir.EvaluationContext(
            actor_scope=bindings[0],
            targets=tuple(b for b in bindings[1:] if b.role in {"target", "candidate"}),
            auxiliary_scopes=tuple(b for b in bindings[1:] if b.role == "auxiliary"),
            evidence=tuple(sorted({f"{b.source}:{b.line}" for b in bindings})),
        )
    return result


def validate_context_readers(
    field: str,
    context: decision_ir.EvaluationContext,
    readers: dict[str, decision_rules.Reader],
    predicates: tuple[decision_rules.Predicate, ...],
    *,
    actor_path: tuple[str, ...] = (),
) -> tuple[tuple[str, str, str, str], ...]:
    """Bind existing observations to evidenced objects, never authorize getters."""
    shapes = {
        "subject_value": {"root": ("country", "actor"), "target_country": ("country", "target")},
        "become_subject_value": {"root": ("country", "actor"), "overlord": ("country", "target")},
        "interest_group_government_weight": {
            "root": ("country", "actor"),
            "interest_group": ("interest_group", "candidate"),
        },
        "negotiation_chance": {
            "root": ("country", "actor"),
            "interest_group": ("interest_group", "candidate"),
            "law": ("law", "auxiliary"),
        },
        "state_value": {
            "root": ("country", "actor"),
            "target_state": ("state", "target"),
            "target_country": ("country", "auxiliary"),
        },
    }
    if field not in shapes or context.status != "observed":
        return ()
    bindings = {
        binding.name: binding
        for binding in (context.actor_scope, *context.targets, *context.auxiliary_scopes)
        if binding is not None
    }
    result: set[tuple[str, str, str, str]] = set()

    def bind(key: str, scope: str, *, argument_kind: str | None = None) -> None:
        binding = bindings.get(scope)
        expected = shapes[field].get(scope)
        if binding is None or expected is None or (binding.kind, binding.role) != expected:
            raise ValueError(f"消费者 {field} 读取器 {key} 作用域/类型/角色缺少上下文证据：{scope}")
        if argument_kind is not None and binding.kind != argument_kind:
            raise ValueError(
                f"消费者 {field} 读取器 {key} 参数 {scope} 必须为 {argument_kind}，实际为 {binding.kind}"
            )
        result.add((key, binding.name, binding.kind, binding.role))

    def bind_argument(reader: decision_rules.Reader, literal: str, parameter: str = "") -> None:
        # These are object-argument signatures of existing readers, not a
        # getter registry. Interpret root only after choosing the signature:
        # has_variable = root names a variable, not the actor country.
        country_arguments = {
            ("is_subject_of", ""),
            ("has_truce_with", ""),
            ("is_homeland_of_country_cultures", ""),
            ("owner", ""),
            ("has_diplomatic_pact", "who"),
            ("has_treaty_alliance_with", "TARGET"),
            ("primary_cultures_percent_state", "target_country"),
        }
        if (reader.engine, parameter) not in country_arguments:
            if literal.startswith("scope:"):
                raise ValueError(
                    f"消费者 {field} 读取器 {reader.key} 参数不支持对象作用域：{literal}"
                )
            return
        scope = "root" if literal.lower() == "root" else literal.removeprefix("scope:")
        if scope == literal and scope != "root":
            return
        bind(reader.key, scope, argument_kind="country")

    def check(key: str) -> decision_rules.Reader:
        reader = readers.get(key)
        if reader is None:
            raise ValueError(f"消费者 {field} 缺少真实读取器：{key}")
        bind(key, reader.scope)
        if reader.scope not in {
            "root",
            "target_country",
            "overlord",
            "interest_group",
            "target_state",
        }:
            raise ValueError(
                f"消费者 {field} 读取器没有已审计的作用域 getter：{key}/{reader.scope}"
            )
        # Existing interface signatures keep output kind, unit and every path
        # conversion authoritative; an observed law is not a new law getter.
        decision_interfaces.reader_scope(reader, actor_path)
        if reader.argument is not None:
            bind_argument(reader, reader.argument)
        for parameter, literal in reader.parameters:
            bind_argument(reader, literal, parameter)
        for literal in reader.path:
            if literal.lower() == "root":
                bind(key, "root")
            elif literal.startswith("scope:"):
                bind(key, literal.removeprefix("scope:"))
        if reader.engine == "relations:root":
            bind(key, "root", argument_kind="country")
        return reader

    for predicate in predicates:
        check(predicate.fact)
        if isinstance(predicate.value, decision_rules.FactReference):
            other = check(predicate.value.key)
            if predicate.value.expression != other.reference():
                raise ValueError(f"消费者 {field} FactReference 右侧与读取器不一致：{other.key}")
    return tuple(sorted(result))


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
    layer_model: layers.LayerModel | None = None
    binding_rows: tuple[bindings.Binding, ...] = ()
    decision_ir: tuple[decision_ir.ConsumerDecisionIR, ...] = ()
    consumer_ir: ConsumerIRBundle | None = None
    support_signals: support_signals.SupportSignals | None = None

    def contract(self) -> dict[str, object]:
        result = contract(self.facts, self.consumers, self.actions, self.relations)
        result["source_fingerprints"] = dict(self.source_sha256)
        owners_by_source_field: dict[tuple[str, str], set[str]] = {}
        for instance in self.action_instances:
            if instance.kind != "rule_action":
                continue
            key = (instance.source, instance.consumer_field)
            owners_by_source_field.setdefault(key, set()).add(instance.owner)
        production_fields = []
        for item in self.production_consumers:
            owners = owners_by_source_field.get((item.source, ".".join(item.field)))
            if not owners:
                raise ValueError(
                    f"生产消费者缺少实际 producer owner：{item.source}:{'.'.join(item.field)}"
                )
            if len(owners) != 1:
                raise ValueError(
                    f"生产消费者存在多个 producer owner：{item.source}:{'.'.join(item.field)}"
                )
            production_fields.append(
                {
                    "id": item.id,
                    "field": ".".join(item.field),
                    "source": item.source,
                    "scope": item.scope,
                    "operation": item.operation,
                    "rule_count": item.rule_count,
                    "max_delta": item.max_delta,
                    "vanilla_tail": item.vanilla_tail,
                    "owner": next(iter(owners)),
                    "write_once": True,
                }
            )
        result["production"] = {
            "rule_count": self.production_rule_count,
            "consumer_count": len(self.production_consumers),
            "fields": production_fields,
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
        result["goals"] = {
            **goal_source.contract(self.goal_specs),
            "activation": "per_action_live_rank_fact_sets_need_tier",
            "deactivation": "rank_fact_false_or_unknown_restores_neutral_tier",
            "unknown": "rank_fact_unknown_uses_neutral_tier",
            "persistent_state": False,
            "priority_role": "tie_break_after_need_and_net_benefit",
            "reserved": {
                key: value["reason"]
                for key, value in supporting.get("goals.toml", {}).get("goals", {}).items()
                if value.get("reserved") is True
            },
        }
        if self.support_signals is not None:
            result["supporting_signals"] = support_signals.contract(self.support_signals)
        result["opportunities"] = opportunity.contract(
            {
                key: value
                for key, value in supporting.get("opportunities.toml", {})
                .get("opportunities", {})
                .items()
                if value.get("reserved") is not True
            }
        )
        result["commitments"] = commitment.contract(
            {
                key: value
                for key, value in supporting.get("commitments.toml", {})
                .get("commitments", {})
                .items()
                if value.get("reserved") is not True
            }
        )
        result["action_families"] = {
            "schema": 1,
            "ids": list(families.FAMILIES),
            "definitions": supporting.get("action_families.toml", {}).get("families", {}),
            "classifier": "source_and_field_deterministic",
        }
        coverage = domain_coverage.load(DECISIONS / "domain_actions.toml")
        result["domain_coverage"] = domain_coverage.contract(coverage, self.action_instances)
        layer_model = self.layer_model
        if layer_model is not None:
            result["layers"] = {
                "schema": 1,
                "strategies": [item.id for item in layer_model.strategies],
                "domains": [item.id for item in layer_model.domains],
                "tools": [
                    {
                        "id": item.id,
                        "domain": item.domain_id,
                        "strategy": item.strategy_id,
                        "neutral_local": item.neutral_local,
                        "enables": list(item.enables),
                        "relations": list(item.relations),
                    }
                    for item in layer_model.tools
                ],
                "enables_depth": dict(sorted(layer_model.enables_depth.items())),
            }
        result["bindings"] = bindings.contract(self.binding_rows)
        result["decision_ir"] = {
            "schema": 1,
            "count": len(self.decision_ir),
            "items": [
                {
                    "action_id": item.action_id,
                    "domain": item.domain,
                    "consumer_id": item.consumer_id,
                    "field": item.field,
                    "operation": item.operation,
                    "core_evidence": list(item.core_evidence),
                    "auxiliary_evidence": list(item.auxiliary_evidence),
                    "hard_negative": list(item.hard_negative),
                    "costs": list(item.costs),
                    "max_delta": item.max_delta,
                    "consumer_max_delta": item.consumer_max_delta,
                    "vanilla_tail": item.vanilla_tail,
                    "unknown_policy": item.unknown_policy,
                    "relation_ids": list(item.relation_ids),
                    "single_clamp": item.single_clamp,
                    "improves": list(item.improves),
                    "consumes": list(item.consumes),
                    "requires_all": list(item.requires_all),
                    "requires_any": list(item.requires_any),
                    "blocked_by": list(item.blocked_by),
                    "exit_when": list(item.exit_when),
                    "base": item.base,
                    "stress": item.stress,
                    "opportunity": item.opportunity,
                    "commitment": item.commitment,
                    "political_cost": item.political_cost,
                    "rank_terms": [
                        {"fact": term.fact, "goal": term.goal, "tier": term.tier, "unit": term.unit}
                        for term in item.rank_terms
                    ],
                    "relations": [
                        {
                            "target": relation.target,
                            "kind": relation.kind,
                            "strength": relation.strength,
                            "scope": relation.scope,
                            "condition_facts": list(relation.condition_facts),
                            "unknown_policy": relation.unknown_policy,
                        }
                        for relation in item.relations
                    ],
                }
                for item in self.decision_ir
            ],
        }
        if self.consumer_ir is not None:
            result["consumer_ir"] = self.consumer_ir.as_dict()
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


def _reader_signature(reader: decision_rules.Reader) -> tuple[object, ...]:
    """Identify the observation, independently of the file reusing it.

    Boolean unit spellings and parameter order have the same engine meaning;
    every other field participates in identity, including numeric validity.
    """
    return (
        reader.engine,
        reader.scope,
        "boolean" if reader.unit in {"flag", "boolean"} else reader.unit,
        reader.kind,
        reader.argument,
        reader.minimum,
        reader.maximum,
        reader.path,
        reader.value_field,
        tuple(sorted(reader.parameters)),
    )


def _declared_reader_matches(fact: EvidenceSpec, reader: decision_rules.Reader) -> bool:
    """A direct declaration may reuse a reader, but cannot flatten its meaning."""
    fact_kind = "number" if fact.kind == "ratio" else fact.kind
    units_match = fact.unit == reader.unit or {fact.unit, reader.unit} <= {"flag", "boolean"}
    if (
        not units_match
        or fact.scope != reader.scope
        or fact_kind != reader.kind
        or fact.minimum != reader.minimum
        or fact.maximum != reader.maximum
        or reader.path
        or reader.parameters
        or reader.value_field is not None
    ):
        return False
    expected = reader.expression("=", True) if reader.kind == "boolean" else reader.engine
    return "".join(fact.trigger.split()) == "".join(expected.split())


def _reader_facts(model_facts: tuple[EvidenceSpec, ...]) -> tuple[EvidenceSpec, ...]:
    """从 information/adapters 的 readers 补齐事实签名，不复制业务谓词。"""
    for item in model_facts:
        if any(op in item.trigger for op in ("=", "<", ">")) and (
            item.kind != "boolean" or item.unit not in {"flag", "boolean"}
        ):
            raise ValueError(f"事实 {item.id} 与 reader 谓词类型不一致：比较结果必须是布尔值")
    by_id = {item.id: item for item in model_facts}
    declared_by_id = dict(by_id)
    observations: dict[str, tuple[decision_rules.Reader, str]] = {}
    information = decision_rules.load()
    adapters = decision_adapters.load()
    readers: list[tuple[str, Any, str]] = [
        ("information", reader, "mod/decisions/information.toml") for reader in information.readers
    ]
    for source, policy in adapters.policies:
        readers.extend(("adapter", reader, source) for reader in policy.readers)
    for owner, reader, source in readers:
        prior = observations.get(reader.key)
        if prior is not None and _reader_signature(prior[0]) != _reader_signature(reader):
            raise ValueError(f"事实 {reader.key} 的 reader 完整语义不一致：{prior[1]} / {source}")
        observations[reader.key] = (reader, source)
        declared = declared_by_id.get(reader.key)
        if declared is not None and not _declared_reader_matches(declared, reader):
            raise ValueError(f"事实 {reader.key} 与原版 reader 的完整语义不一致：{source}")
        if reader.key in by_id:
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


def _reader_shapes(
    declared_facts: tuple[EvidenceSpec, ...] = (),
) -> dict[str, tuple[decision_rules.Reader, ...]]:
    """Expose original reader shape for support-source lowering guards."""
    information = decision_rules.load()
    adapters = decision_adapters.load()
    result: dict[str, list[decision_rules.Reader]] = {}
    for reader in information.readers:
        result.setdefault(reader.key, []).append(reader)
    for _source, policy in adapters.policies:
        for reader in policy.readers:
            result.setdefault(reader.key, []).append(reader)
    # Direct facts.toml predicates are a separate explicit source, not the
    # flattened adapter evidence.  Admit only their flat scalar form, and never
    # overwrite a raw Reader (whose full scope/path must still be checked).
    for fact in declared_facts:
        match = re.fullmatch(
            r"([a-z][a-z0-9_]*)\s*(?:=|<|<=|>|>=)\s*(?:yes|no|-?\d+(?:\.\d+)?)",
            fact.trigger,
        )
        if fact.id not in result and fact.scope == "root" and match:
            result[fact.id] = [
                decision_rules.Reader(
                    key=fact.id,
                    engine=match.group(1),
                    scope="root",
                    unit=fact.unit,
                    kind="boolean",
                )
            ]
    return {key: tuple(value) for key, value in result.items()}


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
    _rank_order(arbitration)
    temporal = sources["temporal.toml"]
    if temporal.get("max_persistent_routes") != 1 or temporal.get("max_reason_codes", 0) > 8:
        raise ValueError("时间合同必须限制持久路线和解释记录")
    localization = sources["localization.toml"]
    if localization.get("fallback") != "none" or len(localization.get("languages", [])) != 11:
        raise ValueError("本地化合同必须覆盖锁定本体的 11 种语言且不允许回退")
    families.load_contract(DECISIONS / "action_families.toml")
    layers.load(DECISIONS / "action_layers.toml")
    bindings.load(DECISIONS / "action_bindings.toml")
    domain_coverage.load(DECISIONS / "domain_actions.toml")


def load_model(
    *, facts_path: Path = FACTS, actions_path: Path = ACTIONS, baseline: str | None = None
) -> SituatedModel:
    declared_facts = evidence_source.load(facts_path)
    facts = _reader_facts(declared_facts)
    layer_model = layers.load(LAYERS)
    binding_rows = bindings.load(BINDINGS)
    consumers, actions = action_source.load(actions_path)
    tool_ids = {item.id for item in layer_model.tools}
    action_ids = {item.id for item in actions}
    if tool_ids != action_ids:
        raise ValueError(
            "action_layers.toml 必须为每张显式行动卡提供且只提供一个 tool："
            f"缺失={sorted(action_ids - tool_ids)} 多余={sorted(tool_ids - action_ids)}"
        )
    supporting = _load_supporting_sources()
    support_model = support_signals.load(
        supporting, facts, actions, reader_shapes=_reader_shapes(declared_facts)
    )
    facts = (*facts, *(item.evidence() for item in support_model.signals))
    goal_specs = support_signals.load_goals(supporting, actions, consumers)
    relation_list = relations.relations(
        actions,
        supporting["relations.toml"].get("relations", []),
    )
    relations.validate(actions, specs=supporting["relations.toml"].get("relations", []))
    layers.validate_links(layer_model, actions, relation_list)
    decision_rows = decision_ir.compile_decisions(actions, consumers, relation_list)
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
        _validate_action_costs(action, {item.id: item for item in facts})
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
        consumer_contracts={item.id: item for item in consumers},
    )
    observed_contexts = evaluation_contexts(baseline_text)
    context_readers = {}
    for source, policy in (("mod/decisions/information.toml", information), *adapters.policies):
        if source not in {
            "mod/decisions/information.toml",
            "common/ai_strategies/00_default_strategy.txt",
        }:
            continue
        readers = {reader.key: reader for reader in policy.readers}
        for rule in policy.rules:
            field = ".".join(rule.field).removeprefix("ai_strategy_default.")
            context = observed_contexts.get(field)
            if context is not None:
                context_readers[(source, rule.id)] = validate_context_readers(
                    field,
                    context,
                    readers,
                    rule.conditions,
                    actor_path=policy.actor_path,
                )
    instances = tuple(
        replace(
            instance,
            evaluation_context=observed_contexts.get(
                instance.consumer_field.removeprefix("ai_strategy_default.")
            )
            if instance.source
            in {"mod/decisions/information.toml", "common/ai_strategies/00_default_strategy.txt"}
            else None,
        )
        for instance in instances
    )
    action_ir = ir.from_rules(
        [("mod/decisions/information.toml", item) for item in information.rules]
        + [(source, item) for source, policy in adapters.policies for item in policy.rules]
    )
    consumer_bundle = decision_ir.compile_consumer_ir(
        actions,
        consumers,
        relation_list,
        action_ir,
        binding_rows,
        instances,
        source_hashes=production_hashes,
    )
    consumer_bundle = replace(
        consumer_bundle,
        writers=tuple(
            replace(
                writer,
                reader_context_bindings=context_readers.get((writer.source, writer.definition), ()),
            )
            for writer in consumer_bundle.writers
        ),
    )
    migration_baseline.validate_bundle(consumer_bundle)
    consumer_bundle = joint_chain_contract.bind_bundle(
        consumer_bundle,
        ((joint_chain_contract.INFO_SOURCE, information), *adapters.policies),
    )
    goals = tuple((item.id, item.priority) for item in goal_specs)
    hashes = {
        "migration_baseline": hashlib.sha256(
            migration_baseline.DEFAULT_SOURCE.read_bytes()
        ).hexdigest(),
        "facts": hashlib.sha256(facts_path.read_bytes()).hexdigest(),
        "actions": hashlib.sha256(actions_path.read_bytes()).hexdigest(),
        "action_layers": hashlib.sha256(LAYERS.read_bytes()).hexdigest(),
        "action_bindings": hashlib.sha256(BINDINGS.read_bytes()).hexdigest(),
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
        layer_model,
        binding_rows,
        decision_rows,
        consumer_bundle,
        support_model,
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
    exit_expr = (
        "NOT = { OR = { " + " ".join(facts[item].trigger for item in action.exit_when) + " } }"
        if action.exit_when
        else ""
    )
    return (
        " AND = { "
        + " ".join(
            [
                "is_ai = yes",
                *(item for item in (all_expr, any_expr, blocked_expr, exit_expr) if item),
                *relation_guards,
            ]
        )
        + " }"
    )


def _validate_action_costs(action: ActionCard, facts: dict[str, EvidenceSpec]) -> None:
    for name in action.consumes:
        if name not in facts:
            raise ValueError(f"行动 {action.id} 成本事实不存在：{name}")
    for amount, predicates in (
        (action.commitment, action.commitment_when),
        (action.political_cost, action.political_when),
    ):
        if amount < 0 or (amount > 0 and not predicates):
            raise ValueError(f"行动 {action.id} 成本必须非负且有明确成本谓词")
        for predicate in predicates:
            fact = facts.get(predicate.fact)
            if fact is None or fact.scope != "root" or fact.unit != predicate.unit:
                raise ValueError(
                    f"行动 {action.id} 成本谓词的事实、单位或作用域无效：{predicate.fact}"
                )
            if (fact.kind == "boolean") != (type(predicate.value) is bool):
                raise ValueError(f"行动 {action.id} 成本谓词类型不匹配：{predicate.fact}")
            if type(predicate.value) is bool and predicate.op != "=":
                raise ValueError(f"行动 {action.id} 布尔成本只支持相等判断")
    if action.commitment == 0 and action.political_cost == 0 and not action.zero_cost_reason:
        raise ValueError(f"行动 {action.id} 零成本必须逐卡说明原因")


def _cost_state(
    predicates: tuple[CostPredicate, ...],
    values: Mapping[str, object],
    facts: Mapping[str, EvidenceSpec] | None = None,
) -> Truth:
    states: list[Truth] = []
    for predicate in predicates:
        value = values.get(predicate.fact)
        if type(value) is bool or type(predicate.value) is bool:
            valid = type(value) is bool and type(predicate.value) is bool
        else:
            valid = type(value) in (int, float) and math.isfinite(cast("float", value))
        spec = facts.get(predicate.fact) if facts is not None else None
        if valid and spec is not None and type(value) is not bool:
            number = cast("float", value)
            valid = (spec.minimum is None or number >= spec.minimum) and (
                spec.maximum is None or number <= spec.maximum
            )
        if not valid:
            states.append(None)
            continue
        if predicate.op == "=":
            states.append(value == predicate.value)
        else:
            left = cast("float", value)
            right = float(predicate.value)
            states.append(
                {"<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}[
                    predicate.op
                ]
            )
    return truth_any(tuple(states)) if states else False


def _row_cost(
    row: decision_ir.ConsumerDecisionIR,
    values: Mapping[str, object],
    states: dict[tuple[CostPredicate, ...], bool] | None = None,
    model: SituatedModel | None = None,
) -> float:
    if model is not None and model.support_signals is not None:
        values = model.support_signals.values(values)

    def active(predicates: tuple[CostPredicate, ...]) -> bool:
        if not predicates:
            return False
        return (
            states[predicates]
            if states is not None
            # Only a proven absence of pressure permits the cheaper tier.
            else _cost_state(predicates, values, {f.id: f for f in model.facts} if model else None)
            in (True, None)
        )

    return (row.commitment if active(row.commitment_when) else 0.0) + (
        row.political_cost if active(row.political_when) else 0.0
    )


def _row_magnitude(
    row: decision_ir.ConsumerDecisionIR,
    values: Mapping[str, object],
    states: dict[tuple[CostPredicate, ...], bool] | None = None,
    model: SituatedModel | None = None,
) -> float:
    magnitude = abs(row.base + row.opportunity)
    cost = _row_cost(row, values, states, model)
    return max(0.0, magnitude - cost)


def _rank_order(arbitration):
    raw = arbitration.get("rank", _RANK_ORDER)
    if not isinstance(raw, (list, tuple)) or any(not isinstance(key, str) for key in raw):
        raise ValueError("rank 必须是词典序维度列表")
    order = tuple(raw)
    if len(order) != len(_RANK_ORDER) or set(order) != set(_RANK_ORDER) or order[-1] != "action_id":
        raise ValueError("rank 必须完整且唯一，稳定 action_id 必须最后比较")
    return order


def _row_order(row, values, states=None, rank_states=None, model=None):
    if model is not None and model.support_signals is not None:
        values = model.support_signals.values(values)
    goals = dict(model.goals) if model else {}
    active = [
        term
        for term in row.rank_terms
        if (
            rank_states.get(term.fact, False)
            if rank_states is not None
            else values.get(term.fact) is True
        )
    ]
    tier, priority = max(((term.tier, goals.get(term.goal, 0)) for term in active), default=(0, 0))
    metrics = {
        "need_tier": tier,
        "goal_priority": priority,
        "net_benefit": _row_magnitude(row, values, states, model),
        "stress": row.stress,
        "opportunity": row.opportunity,
    }
    order = (
        _rank_order((model.support_sources or {}).get("arbitration.toml", {}))
        if model
        else _RANK_ORDER
    )
    return (*(-metrics[key] for key in order[:-1]), row.action_id)


def _row_delta(
    row: decision_ir.ConsumerDecisionIR,
    values: Mapping[str, object],
    *,
    complement: float = 0.0,
    model: SituatedModel | None = None,
) -> float:
    direction = -1.0 if row.base + row.opportunity < 0 else 1.0
    magnitude = _row_magnitude(row, values, model=model)
    delta = direction * magnitude + (complement if direction > 0 else min(complement, magnitude))
    if direction < 0:
        delta = min(0.0, delta)
    return max(-row.max_delta, min(row.max_delta, delta))


def _row_delta_expression(
    row: decision_ir.ConsumerDecisionIR,
    *,
    max_delta: float | None = None,
    complement_effects: tuple[str, ...] = (),
    cost_states: dict[tuple[CostPredicate, ...], bool] | None = None,
) -> str:
    """生成与 ``_row_delta`` 同构的有限 PDX value block。"""

    limit = row.max_delta if max_delta is None else min(row.max_delta, max_delta)
    direction = -1.0 if row.base + row.opportunity < 0 else 1.0
    base = direction * _row_magnitude(row, {}, cost_states)
    effects = list(complement_effects)
    if not effects:
        delta = max(-limit, min(limit, base))
        return f"add = {delta:g}"
    return (
        f"add = {{\n\t\t\t\tvalue = {base:g}"
        f"{''.join(effects)}"
        f"\n\t\t\t\tmin = {-limit:g}\n\t\t\t\tmax = {(0 if direction < 0 else limit):g}\n\t\t\t}}"
    )


def _cost_trigger(predicates: tuple[CostPredicate, ...], facts: dict[str, EvidenceSpec]) -> str:
    terms = []
    for predicate in predicates:
        trigger = facts[predicate.fact].trigger
        if type(predicate.value) is bool:
            terms.append(trigger if predicate.value else f"NOT = {{ {trigger} }}")
        else:
            if any(operator in trigger for operator in ("=", "<", ">")):
                raise ValueError(f"数值成本必须引用原始 reader：{predicate.fact}")
            terms.append(f"{trigger} {predicate.op} {predicate.value:g}")
    return " OR = { " + " ".join(terms) + " }"


def _cheap_cost_trigger(predicates, facts):
    bounds = []
    for predicate in predicates:
        fact = facts[predicate.fact]
        if type(predicate.value) is bool:
            continue
        if fact.minimum is not None:
            bounds.append(f"{fact.trigger} >= {fact.minimum:g}")
        if fact.maximum is not None:
            bounds.append(f"{fact.trigger} <= {fact.maximum:g}")
    return "AND = { " + " ".join(bounds) + " NOT = { " + _cost_trigger(predicates, facts) + " } }"


def _bounded_cost_specs(actions, visible, facts):
    """Only this consumer and its direct relation targets affect its fallback."""
    by_id = {row.action_id: row for row in visible}
    relevant = [
        *actions,
        *(by_id[rel.target] for row in actions for rel in row.relations if rel.target in by_id),
    ]
    names = {p.fact for row in relevant for p in (*row.commitment_when, *row.political_when)}
    return tuple(
        facts[name]
        for name in sorted(names)
        if name in facts and (facts[name].minimum is not None or facts[name].maximum is not None)
    )


def _cost_feasibility_trigger(row, facts: dict[str, EvidenceSpec]) -> str:
    """Return a finite guard for a relation target's affordable status.

    Cost predicates are OR within each cost tier and the tiers are additive.
    Enumerating the finite tier combinations keeps the target relation guard
    equivalent to the reference affordability check without introducing a
    second dynamic selector.
    """

    groups = tuple(
        (predicates, amount)
        for predicates, amount in (
            (row.commitment_when, row.commitment),
            (row.political_when, row.political_cost),
        )
        if predicates and amount > 0
    )
    magnitude = abs(row.base + row.opportunity)
    impossible = "NOT = { is_ai = yes }"
    if not groups:
        return ""
    if magnitude <= 0:
        return impossible
    feasible_terms: list[str] = []
    for mask in range(1 << len(groups)):
        total = sum(amount for index, (_, amount) in enumerate(groups) if mask & (1 << index))
        if magnitude <= total:
            continue
        terms = []
        for index, (predicates, _) in enumerate(groups):
            trigger = _cost_trigger(predicates, facts)
            terms.append(trigger if mask & (1 << index) else f"NOT = {{ {trigger} }}")
        feasible_terms.append(terms[0] if len(terms) == 1 else "AND = { " + " ".join(terms) + " }")
    if not feasible_terms:
        return impossible
    return (
        feasible_terms[0]
        if len(feasible_terms) == 1
        else "OR = { " + " ".join(feasible_terms) + " }"
    )


def _production_action_rows(model: SituatedModel) -> tuple[decision_ir.ConsumerDecisionIR, ...]:
    """Reject divergent explicit-card identities before any production lowering.

    The compatibility decision rows, canonical bundle rows and writer source map
    must describe the same actions.  A missing writer cannot leave an anonymous
    card in the generated output or the reference evaluator.
    """
    for binding in model.binding_rows:
        bindings.validate_disposition(binding)
    bundle = model.consumer_ir
    if bundle is None:
        raise ValueError("显式行动缺少 ConsumerIR bundle")
    rows = {row.action_id: row for row in model.decision_ir}
    canonical = {row.action_id: row for row in bundle.actions}
    if (
        len(rows) != len(model.decision_ir)
        or len(canonical) != len(bundle.actions)
        or rows != canonical
    ):
        raise ValueError("显式行动 DecisionIR 与 ConsumerIR 行重复或不一致")
    if len(set(bundle.writer_ids())) != len(bundle.writers):
        raise ValueError("ConsumerIR 生产 writer ID 重复")
    writers = [writer for writer in bundle.writers if writer.kind == "action_card"]
    by_action = {writer.definition: writer for writer in writers}
    if len(by_action) != len(writers) or set(by_action) != set(canonical):
        raise ValueError("显式行动缺少唯一 ConsumerIR writer")
    consumers = {consumer.id: consumer for consumer in model.consumers}
    if len(consumers) != len(model.consumers):
        raise ValueError("显式行动消费者身份重复")
    for action_id, row in canonical.items():
        writer = by_action[action_id]
        consumer = consumers.get(row.consumer_id)
        if consumer is None or (
            writer.writer_id != f"card_{action_id}"
            or writer.source != "mod/decisions/actions.toml"
            or writer.consumer_id != row.consumer_id
            or writer.field != row.field
            or writer.operation != row.operation
            or writer.vanilla_tail != row.vanilla_tail
            or writer.actor != consumer.scope
            or writer.target != "none"
            or writer.owner != consumer.owner
            or writer.action != row
            or writer.legacy is not None
            or writer.predicates
            or row.field != consumer.field
            or row.operation != consumer.operation
            or row.vanilla_tail != consumer.vanilla_tail
        ):
            raise ValueError(f"显式行动 ConsumerIR writer 与消费者/行动不一致：{action_id}")
        facts = {fact.id: fact for fact in model.facts}
        goals = {goal.id: goal for goal in model.goal_specs}
        seen = set()
        for term in row.rank_terms:
            fact = facts.get(term.fact)
            goal = goals.get(term.goal)
            if (
                fact is None
                or fact.kind != "boolean"
                or fact.scope != "root"
                or {fact.unit, term.unit} - {"flag", "boolean"}
                or goal is None
                or row.consumer_id not in goal.consumer_bindings
                or term.fact in seen
            ):
                raise ValueError(
                    f"行动 rank 事实/目标/单位/消费者无效或重复：{action_id}:{term.fact}"
                )
            seen.add(term.fact)
    return bundle.actions


def _ordered_relations(row: decision_ir.ConsumerDecisionIR) -> tuple[Relation, ...]:
    """Choose strongest complements first, with stable identities breaking ties."""
    for relation in row.relations:
        if (
            type(relation.strength) not in (int, float)
            or not math.isfinite(relation.strength)
            or relation.strength <= 0
        ):
            raise ValueError(f"行动关系强度必须为正有限数：{row.action_id}->{relation.target}")
    return tuple(
        sorted(
            row.relations,
            key=lambda relation: (
                relation.kind,
                -relation.strength,
                relation.target,
                relation.scope,
                relation.condition_facts,
                relation.unknown_policy,
            ),
        )
    )


def strategy_overlay(
    model: SituatedModel,
    *,
    enabled_consumer_fields: set[str] | frozenset[str] | None = None,
) -> dict[str, str]:
    """Lower the overlay while isolating disabled consumer modules.

    Action relations may cross consumer fields.  When a module is disabled,
    its target action must not leave a complement, alternative, conflict, or
    enable guard in an enabled consumer's generated branch.  Filtering at the
    lowering boundary keeps the production output consistent with the module
    switch instead of filtering only the top-level fields afterwards.
    """
    action_rows = _production_action_rows(model)
    facts = {item.id: item for item in model.facts}
    # DecisionIR 是 lowering 的唯一行动输入。ActionCard 只在 load_model
    # 阶段校验和编译成 IR，避免生成器再次从源 TOML 拼出另一套语义。
    rows_by_consumer: dict[str, list[decision_ir.ConsumerDecisionIR]] = {
        item.id: [] for item in model.consumers
    }
    for row in action_rows:
        rows_by_consumer[row.consumer_id].append(row)
    output = {}
    by_id = {item.action_id: item for item in action_rows}
    consumer_field_by_action = {
        item.action_id: next(
            consumer.field for consumer in model.consumers if consumer.id == item.consumer_id
        )
        for item in action_rows
    }
    enabled_fields = (
        frozenset(consumer.field for consumer in model.consumers)
        if enabled_consumer_fields is None
        else frozenset(enabled_consumer_fields)
    )
    for consumer in model.consumers:
        declared = rows_by_consumer[consumer.id]
        if len(declared) > consumer.budget:
            raise ValueError(
                f"消费者 {consumer.id} 的行动数 {len(declared)} 超过预算 {consumer.budget}；"
                "不能静默丢弃候选"
            )
        groups = tuple(
            dict.fromkeys(
                predicates
                for row in declared
                for predicates, amount in (
                    (row.commitment_when, row.commitment),
                    (row.political_when, row.political_cost),
                )
                if predicates and amount > 0
            )
        )
        rank_facts = tuple(sorted({term.fact for row in declared for term in row.rank_terms}))
        # Explicit finite cost tiers only: never enumerate factual qualification
        # combinations or silently prune candidates to meet the runtime budget.
        if len(groups) + len(rank_facts) > 9:
            raise ValueError(f"消费者 {consumer.id} rank/成本分区超过 512 叶预算")
        if len(groups) > 3:
            raise ValueError(f"消费者 {consumer.id} 成本分区超过 8 叶预算")

        def leaf(states, rank_states, declared=declared):
            chosen = sorted(
                declared, key=lambda item: _row_order(item, {}, states, rank_states, model)
            )
            chosen_position = {item.action_id: index for index, item in enumerate(chosen)}
            blocks: list[str] = []
            for row in chosen:
                if _row_magnitude(row, {}, states) == 0:
                    continue
                blocks.append(branch(row, chosen_position, states, len(blocks)))
            return "".join(blocks)

        def branch(row, chosen_position, states, index, consumer=consumer):
            relation_guards: list[str] = []
            complement_effects: list[str] = []
            for relation in _ordered_relations(row):
                target_enabled = consumer_field_by_action[relation.target] in enabled_fields
                if not target_enabled and relation.kind != "enables":
                    continue
                target = by_id[relation.target]
                target_guard = _limit(target, facts)
                if not target_enabled:
                    # A disabled target cannot satisfy an enablement relation;
                    # keep the source action conservative instead of turning
                    # the missing module into an implicit pass-through.
                    relation_guards.append("NOT = { is_ai = yes }")
                    continue
                feasibility = _cost_feasibility_trigger(target, facts)
                if feasibility:
                    target_guard = f" AND = {{ {feasibility} {target_guard} }}"
                if relation.condition_facts:
                    relation_guard = _condition(facts, relation.condition_facts)
                    target_guard = f" AND = {{ {relation_guard} {target_guard} }}"
                if relation.kind == "enables":
                    relation_guards.append(target_guard)
                elif relation.kind in {"substitutes", "conflicts"}:
                    # Symmetric alternatives are ordered once.  Only the
                    # lower-ranked branch receives the guard; otherwise two
                    # active alternatives would mutually disable each other.
                    if (
                        relation.target not in chosen_position
                        or chosen_position[row.action_id] > chosen_position[relation.target]
                    ):
                        relation_guards.append(f"NOT = {{ {target_guard} }}")
                elif relation.kind == "complements":
                    # An auxiliary unknown does not prevent the next proven
                    # complement; the if/else_if chain contributes at most one.
                    branch_key = "else_if" if complement_effects else "if"
                    complement_effects.append(
                        f"\n\t\t\t\t{branch_key} = {{ limit = {{ ROOT ?= {{ {target_guard} }} }} add = {relation.strength:g} }}"
                    )
            # Clamp the adjustment inside its own script value, so vanilla's
            # accumulated score is not clamped along with the Mod delta.  The
            # expression is the lowering of _row_delta, with the same known
            # commitment facts and optional complement additions.
            effect = _row_delta_expression(
                row,
                max_delta=consumer.max_delta,
                complement_effects=tuple(complement_effects),
                cost_states=states,
            )
            return (
                f"\t\t# ACTION {row.action_id} [{row.domain}]; {row.explanation}\n"
                f"\t\t{'if' if index == 0 else 'else_if'} = {{\n\t\t\tlimit = {{ ROOT ?= {{ {_limit(row, facts, relation_guards=tuple(relation_guards))} }} }}\n\t\t\t{effect}\n\t\t}}\n"
            )

        def rank_partition(index, states, rank_states, rank_facts=rank_facts):
            if index == len(rank_facts):
                return leaf(states, rank_states)
            name = rank_facts[index]
            high = rank_partition(index + 1, states, {**rank_states, name: True})
            low = rank_partition(index + 1, states, {**rank_states, name: False})
            return (
                f"if = {{ limit = {{ ROOT ?= {{ {facts[name].trigger} }} }}\n{high}}}\n"
                f"else = {{\n{low}}}\n"
            )

        def partition(index, states, groups=groups):
            if index == len(groups):
                return rank_partition(0, states, {})
            group = groups[index]
            low = partition(index + 1, {**states, group: False})
            high = partition(index + 1, {**states, group: True})
            guard = _cheap_cost_trigger(group, facts)
            return f"if = {{ limit = {{ ROOT ?= {{ {guard} }} }}\n{low}}}\nelse = {{\n{high}}}\n"

        generated = partition(0, {})
        invalid_terms = []
        enabled_rows = [
            row for row in action_rows if consumer_field_by_action[row.action_id] in enabled_fields
        ]
        for fact in _bounded_cost_specs(declared, enabled_rows, facts):
            if fact.minimum is not None:
                invalid_terms.append(f"{fact.trigger} < {fact.minimum:g}")
            if fact.maximum is not None:
                invalid_terms.append(f"{fact.trigger} > {fact.maximum:g}")
        if invalid_terms:
            invalid = "OR = { " + " ".join(invalid_terms) + " }"
            # An out-of-contract input is locally unknown, never a healthy
            # cheap tier or a proof that a relation target is affordable.
            generated = (
                f"if = {{ limit = {{ ROOT ?= {{ {invalid} }} }} }}\nelse = {{\n{generated}}}\n"
            )
        output[consumer.field] = generated
    return output


def compile_policy(
    policy: decision_rules.RuleSet,
    source: object | None = None,
    config_model: SituatedModel | None = None,
):
    """返回 ``(RuleSet, contract)``；谓词沿用原版 RuleSet，字段一次有界写入。"""
    model = config_model or load_model()
    _production_action_rows(model)
    policy = decision_ir.lower_legacy(
        policy, model.consumer_ir, source=str(source) if source is not None else None
    )
    source_key = str(source) if source is not None else None
    # Rule IDs are only unique inside their source file.  Resolving by the
    # pair is part of the production contract; a same-named adapter rule must
    # never silently borrow the information rule's IR row.
    ir_by_key = {(item.source, item.action_id): item for item in model.action_ir}
    binding_by_id = {(item.source, item.definition): item for item in model.binding_rows}
    writer_by_key = {
        (item.source, item.definition): item
        for item in (model.consumer_ir.writers if model.consumer_ir is not None else ())
        if item.kind == "rule_action"
    }
    owner_by_key = {(item.source, item.rule_id): item.owner for item in model.action_instances}
    compiled_rules = []
    field_contract = []
    for field, rules in policy.groups().items():
        for rule in rules:
            ir_item = (
                ir_by_key.get((source_key, rule.id))
                if source_key is not None
                else next(
                    (item for item in ir_by_key.values() if item.action_id == rule.id),
                    None,
                )
            )
            binding = (
                binding_by_id.get((str(source), rule.id))
                if source is not None
                else next((item for item in model.binding_rows if item.definition == rule.id), None)
            )
            writer = (
                writer_by_key.get((source_key, rule.id))
                if source_key is not None
                else next(
                    (item for item in writer_by_key.values() if item.definition == rule.id),
                    None,
                )
            )
            if ir_item is None or binding is None or writer is None:
                raise ValueError(f"生产规则缺少 IR/绑定：{rule.id}")
            legacy = writer.legacy
            expected_predicates = tuple(
                (predicate.fact, predicate.op, predicate.value) for predicate in rule.conditions
            )
            if legacy is None or (
                legacy.source != writer.source
                or legacy.definition != rule.id
                or legacy.domain != rule.domain
                or legacy.consumer_id != binding.consumer
                or legacy.field != ".".join(rule.field)
                or legacy.actor != binding.actor
                or legacy.target != binding.target
                or legacy.operation != rule.operation
                or legacy.value != rule.value
                or legacy.predicates != expected_predicates
                or legacy.vanilla_tail != ir_item.vanilla_tail
            ):
                raise ValueError(f"重复写入或 ConsumerIR legacy 语义与生产规则不一致：{rule.id}")
            if (
                writer.consumer_id != binding.consumer
                or writer.field != ".".join(rule.field)
                or writer.operation != rule.operation
                or writer.vanilla_tail != ir_item.vanilla_tail
                or writer.owner != owner_by_key.get((writer.source, writer.definition))
            ):
                raise ValueError(f"重复写入或 ConsumerIR writer 与规则/绑定不一致：{rule.id}")
            if ir_item.field != ".".join(rule.field) or ir_item.operation != rule.operation:
                # 规则在进入统一 IR 后不允许被另一套适配语义悄悄改写。
                # 对外沿用“重复写入”这一合同词，便于调用方把字段漂移与
                # owner 冲突统一归入同一类硬失败，而不是把内部不一致当作
                # 可接受的降级。
                raise ValueError(f"IR 与生产规则不一致（重复写入或字段漂移）：{rule.id}")
            if source is not None and binding.source != str(source):
                raise ValueError(f"绑定来源与生产规则不一致：{rule.id}")
            # Legacy defaults preserve their actual ordering.  Explicit cards
            # have their own finite fact/goal rank, not a field-wide constant.
            compiled_rules.append(
                replace(
                    legacy.to_action_ir(),
                    priority=legacy.priority,
                    origin_priority=legacy.priority,
                )
            )
        field_contract.append(
            {
                "field": ".".join(field),
                "source": str(source or "rule_set"),
                "rule_count": len(rules),
                "write_once": True,
                "unknown_fallback": "vanilla",
                "player_fallback": "vanilla",
                "vanilla_tail": "retain_qualification_cost_random_execution",
                "max_rank_adjustment": 0,
            }
        )
    compiled_ir = tuple(sorted(compiled_rules, key=lambda item: item.action_id))
    compiled = replace(
        policy, rules=tuple(item.to_rule() for item in compiled_ir), semantic_ir=compiled_ir
    )
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
        "adjustment_application": "legacy_order_preserved; explicit_finite_fact_goal_rank",
        "ir_to_pdx": "consumer_ir_writer_to_exact_rule_lowering",
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


def _action_conditions(
    action: ActionCard | decision_ir.ConsumerDecisionIR, values: Mapping[str, object]
) -> bool | None:
    """三值求值；未知不伪造负面证据。"""

    def test(name: str) -> bool | None:
        value = values.get(name)
        return value if type(value) is bool else None

    required = [test(name) for name in action.requires_all]
    blocked = [test(name) for name in action.blocked_by]
    if any(item is False for item in required) or any(item is True for item in blocked):
        return False
    options = [test(name) for name in action.requires_any]
    if options and all(item is False for item in options):
        return False
    if (
        any(item is None for item in required)
        or any(item is None for item in blocked)
        or (options and not any(item is True for item in options))
    ):
        return None
    return True


def _relation_conditions(relation: Relation, values: Mapping[str, object]) -> bool | None:
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


def _action_status(action: decision_ir.ConsumerDecisionIR, values: Mapping[str, object]) -> Truth:
    """Return the same complete qualification state used by lowering."""

    exit_values: tuple[Truth, ...] = tuple(
        None if name not in values or type(values[name]) is not bool else cast("bool", values[name])
        for name in action.exit_when
    )
    exit_state = truth_not(truth_any(exit_values)) if exit_values else True
    return truth_all((_action_conditions(action, values), exit_state))


def _action_feasibility(
    action: decision_ir.ConsumerDecisionIR,
    values: Mapping[str, object],
    model: SituatedModel | None = None,
) -> Truth:
    """Return whether an action can contribute a non-zero adjustment.

    A malformed or unknown cost fact is conservatively treated as costly for
    magnitude selection, but relation consumers must preserve the uncertainty
    instead of claiming that the target is definitely affordable/unaffordable.
    """

    groups = tuple(
        (predicates, amount)
        for predicates, amount in (
            (action.commitment_when, action.commitment),
            (action.political_when, action.political_cost),
        )
        if predicates and amount > 0
    )
    if not groups:
        return True
    facts = {fact.id: fact for fact in model.facts} if model else None
    states = tuple(_cost_state(predicates, values, facts) for predicates, _ in groups)
    feasible: list[Truth] = []
    for mask in range(1 << len(groups)):
        cost = sum(amount for index, (_, amount) in enumerate(groups) if mask & (1 << index))
        if abs(action.base + action.opportunity) <= cost:
            continue
        feasible.append(
            truth_all(
                tuple(
                    state if mask & (1 << index) else truth_not(state)
                    for index, state in enumerate(states)
                )
            )
        )
    return truth_any(tuple(feasible)) if feasible else False


def _select_action(
    actions: list[decision_ir.ConsumerDecisionIR],
    values: Mapping[str, object],
    *,
    all_actions: list[decision_ir.ConsumerDecisionIR] | None = None,
    model: SituatedModel | None = None,
) -> tuple[decision_ir.ConsumerDecisionIR, float] | None:
    """按生成的候选顺序选择行动；核心条件未知时阻断更低优先级候选。

    与独立 PDX 三值求值器保持相同的短路规则；未知核心条件不能被当成
    “不匹配”后继续选择低优先级行动。all_actions 提供其他消费者的关系
    目标资格，不要求目标在其消费者中已被选中或已经执行。
    """

    if model is not None and model.support_signals is not None:
        values = model.support_signals.values(values)
    visible = actions if all_actions is None else all_actions
    if model is not None:
        specs = _bounded_cost_specs(actions, visible, {fact.id: fact for fact in model.facts})
        for fact in specs:
            value = values.get(fact.id)
            if (
                type(value) in (int, float)
                and math.isfinite(cast("float", value))
                and (
                    (fact.minimum is not None and value < fact.minimum)
                    or (fact.maximum is not None and value > fact.maximum)
                )
            ):
                return None
    statuses = {row.action_id: _action_status(row, values) for row in visible}
    feasible = {row.action_id: _action_feasibility(row, values, model) for row in visible}
    ordered = sorted(actions, key=lambda item: _row_order(item, values, model=model))
    position = {row.action_id: index for index, row in enumerate(ordered)}
    for action in ordered:
        if _row_magnitude(action, values, model=model) == 0:
            continue
        status = statuses[action.action_id]
        if status is False:
            continue
        if status is None:
            return None
        blocked = False
        complement = 0.0
        for relation in _ordered_relations(action):
            target_status = truth_all(
                (statuses.get(relation.target), feasible.get(relation.target))
            )
            relation_state = _relation_conditions(relation, values)
            if relation.kind == "complements":
                if complement == 0.0 and relation_state is True and target_status is True:
                    complement = relation.strength
                continue
            relation_guard = truth_all((relation_state, target_status))
            if relation.kind == "enables" and relation_guard is not True:
                if relation_guard is None:
                    return None
                blocked = True
            elif relation.kind in {"substitutes", "conflicts"}:
                if (
                    relation.target in position
                    and position[action.action_id] < position[relation.target]
                ):
                    continue
                relation_guard = truth_not(relation_guard)
                if relation_guard is None:
                    return None
                if relation_guard is False:
                    blocked = True
        if not blocked:
            return action, complement
    return None


def evaluate_actions(
    model: SituatedModel,
    values: Mapping[str, object],
    *,
    is_ai: bool,
    enabled_consumer_fields: set[str] | frozenset[str] | None = None,
) -> dict[str, tuple[str, float]]:
    """Evaluate the real explicit overlay, independent of legacy rule matches.

    The returned values are Mod deltas, never final vanilla scores or executed
    actions. Disabled optional relation targets are isolated exactly as in
    ``strategy_overlay``; a disabled enables target cannot become fulfilled.
    """

    if type(is_ai) is not bool:
        raise ValueError("is_ai 必须为明确布尔值")
    rows = _production_action_rows(model)
    if not is_ai:
        return {}
    if model.support_signals is not None:
        values = model.support_signals.values(values)
    consumers = {consumer.id: consumer for consumer in model.consumers}
    enabled = (
        frozenset(consumer.field for consumer in model.consumers)
        if enabled_consumer_fields is None
        else frozenset(enabled_consumer_fields)
    )
    field_by_action = {row.action_id: row.field for row in rows}
    visible = [
        replace(
            row,
            relations=tuple(
                relation
                for relation in row.relations
                if field_by_action[relation.target] in enabled or relation.kind == "enables"
            ),
        )
        for row in rows
        if row.field in enabled
    ]
    result: dict[str, tuple[str, float]] = {}
    for consumer in model.consumers:
        candidates = [row for row in visible if row.consumer_id == consumer.id]
        if not candidates:
            continue
        if len(candidates) > consumer.budget:
            raise ValueError(f"消费者 {consumer.id} 的行动数超过预算；不能静默丢弃候选")
        selected = _select_action(candidates, values, all_actions=visible, model=model)
        if selected is None:
            continue
        action, complement = selected
        delta = _row_delta(action, values, complement=complement, model=model)
        bound = consumers[action.consumer_id].max_delta
        delta = max(-bound, min(bound, delta))
        if delta != 0:
            result[consumer.field] = (action.action_id, delta)
    return result


def evaluate_policy(
    policy: decision_rules.RuleSet,
    values: Mapping[str, object],
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
    model = config_model or load_model()
    _production_action_rows(model)
    if model.support_signals is not None:
        values = model.support_signals.values(values)
    policy = decision_ir.lower_legacy(policy, model.consumer_ir)
    baseline = decision_rules.evaluate_ir(policy, values, is_ai=is_ai)
    if not is_ai:
        return baseline
    adjustments = evaluate_actions(model, values, is_ai=True)
    result = dict(baseline)
    for field, (rule_id, raw) in baseline.items():
        adjustment = adjustments.get(field)
        if adjustment is None:
            continue
        _, delta = adjustment
        selected_rule = next((rule for rule in policy.rules if rule.id == rule_id), None)
        if selected_rule is None:
            continue
        adjusted = raw + delta if selected_rule.operation == "add" else raw * (1.0 + delta / 100.0)
        result[field] = (rule_id, adjusted)
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
