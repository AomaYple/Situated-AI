"""统一的处境行动编译器。

显式行动通过同一 ConsumerDecisionIR 编译为消费者联合数值程序；独立
贡献共同参与，只在消费者边界限幅。旧 RuleSet 的精确迁移合同仍单独
保留，不能据此声称所有旧规则已经转换为联合行动语义。运行期没有
Python 服务、世界扫描或新增的无界状态。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from .. import config, decision_adapters, decision_interfaces, decision_rules  # noqa: TID252
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
    programs,
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
_LAW_DOC = REPO / "research/official-docs/game/common/laws/readme.md"
_LAW_DOC_MANIFEST = REPO / "research/official-docs.manifest.json"
_LAW_DOC_SHA256 = "034ed06d19b2bd6fb8070bfbb95f6e768aaff36a162172147d80f9023f208076"
_LAW_NATIVE_SHA256 = "2e172974c75e5a544777f0a21099019043ca0164d499927786e10572b8956a0c"
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
        "treaty_port_value": (
            common,
            ("target_state", "state", "target", "scope:target_state = state"),
            ("target_country", "country", "auxiliary", "scope:target_country = state owner"),
        ),
        "combat_unit_group_weights": (
            common,
            (
                "military_formation",
                "military_formation",
                "auxiliary",
                "scope:military_formation = military formation",
            ),
        ),
        "conscript_battalion_ratio": (
            common,
            (
                "military_formation",
                "military_formation",
                "auxiliary",
                "scope:military_formation = military formation",
            ),
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
            re.search(
                r"\broot\s*(?:=|is\b)|\bscope\s*:\s*[a-z][a-z0-9_]*\s*(?:=|is\b)",
                marker,
                re.IGNORECASE,
            )
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
    # Only this documented map projects its parent's country/formation context
    # to ordinary, unique numeric child blocks. Other maps remain independent.
    parent = definitions[0].value.all("combat_unit_group_weights")
    if len(parent) == 1 and isinstance(parent[0].value, Block):
        context = result["combat_unit_group_weights"]
        for child in parent[0].value.assignments():
            field = f"combat_unit_group_weights.{child.key}"
            siblings = parent[0].value.all(child.key)
            result[field] = (
                decision_ir.EvaluationContext(status="ambiguous")
                if len(siblings) != 1
                else context
                if child.op == "=" and child.prefix is None and isinstance(child.value, Block)
                else decision_ir.EvaluationContext(status="unknown")
            )
    return result


def law_evaluation_context(text: str) -> decision_ir.EvaluationContext:
    """The enact-weight README proves country/law, never ai_will_do or a getter."""
    lines = text.splitlines()
    heading = "# Documentation for ai_enact_weight_modifier"
    statement = "Root scope is AI country, scope:law contains the relevant law for that country"
    headings = [i for i, line in enumerate(lines) if line.strip() == heading]
    statements = [i for i, line in enumerate(lines) if line.strip() == statement]
    example = [i for i, line in enumerate(lines) if line.strip() == "# Example"]
    if len(headings) != 1 or len(statements) != 1 or len(example) != 1:
        return decision_ir.EvaluationContext(status="unknown")
    start, location, end = headings[0], statements[0], example[0]
    if not start < location < end or any(
        re.search(r"Root\s+scope|scope\s*:\s*law", line) and line.strip() != statement
        for line in lines[start + 1 : end]
    ):
        return decision_ir.EvaluationContext(status="unknown")
    source = "common/laws/readme.md"
    line = location + 1
    return decision_ir.EvaluationContext(
        actor_scope=decision_ir.ContextBinding("root", "country", "actor", source, line),
        auxiliary_scopes=(decision_ir.ContextBinding("law", "law", "auxiliary", source, line),),
        evidence=(f"{source}:{line}",),
    )


def _frozen_law_context() -> decision_ir.EvaluationContext:
    raw = _LAW_DOC.read_bytes()
    manifest = json.loads(_LAW_DOC_MANIFEST.read_text(encoding="utf-8"))
    entry = manifest["文档"]["game/common/laws/readme.md"]
    if (
        hashlib.sha256(raw).hexdigest() != _LAW_DOC_SHA256
        or entry["镜像sha256"] != _LAW_DOC_SHA256
        or entry["sha256"] != _LAW_NATIVE_SHA256
    ):
        raise ValueError("法律 enact weight 冻结文档证据漂移")
    native = config.GAME / "common/laws/readme.md"
    if native.is_file() and hashlib.sha256(native.read_bytes()).hexdigest() != _LAW_NATIVE_SHA256:
        raise ValueError("法律 enact weight 原版文档证据漂移")
    context = law_evaluation_context(raw.decode("utf-8"))
    if context.status != "observed":
        raise ValueError("法律 enact weight 文档没有精确上下文")
    return context


def validate_context_readers(
    field: str,
    context: decision_ir.EvaluationContext,
    readers: dict[str, decision_rules.Reader],
    predicates: tuple[decision_rules.Predicate, ...],
    *,
    actor_path: tuple[str, ...] = (),
    input_keys: tuple[str, ...] = (),
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
    shapes["treaty_port_value"] = shapes["state_value"]
    shapes["ai_enact_weight_modifier"] = {"root": ("country", "actor"), "law": ("law", "auxiliary")}
    formation_shape = {
        "root": ("country", "actor"),
        "military_formation": ("military_formation", "auxiliary"),
    }
    shapes["conscript_battalion_ratio"] = formation_shape
    if field.startswith("combat_unit_group_weights.") and field.count(".") == 1:
        shapes[field] = formation_shape
    if field not in shapes or context.status != "observed":
        return ()
    # These contracts document a country ROOT. Reaching a country again via
    # owner cannot preserve that actor's identity after a caller-side offset.
    if actor_path:
        raise ValueError(f"消费者 {field} 读取器 actor 路径偏离已证明的国家 ROOT")
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

    for key in input_keys:
        check(key)
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
    observation_contracts: tuple[tuple[str, str, tuple[object, ...]], ...] = ()

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
        result["observation_contracts"] = [
            {"source": source, "fact": key, "signature": signature}
            for source, key, signature in self.observation_contracts
        ]
        result["ir"] = ir.contract(self.action_ir)
        result["typed_state"] = state.contract()
        supporting = self.support_sources or {}
        result["goals"] = {
            **goal_source.contract(self.goal_specs),
            "activation": "per_action_live_rank_fact_sets_need_tier",
            "deactivation": "rank_fact_false_or_unknown_restores_neutral_tier",
            "unknown": "rank_fact_unknown_uses_neutral_tier",
            "persistent_state": False,
            "priority_role": "legacy_metadata_not_utility; observed_rank_terms_contribute_amount",
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
                    "stress_semantics": "compatibility_metadata_not_utility",
                    "opportunity": item.opportunity,
                    "commitment": item.commitment,
                    "political_cost": item.political_cost,
                    "variant_group": item.variant_group,
                    "variant_priority": item.variant_priority,
                    "cause_group": item.cause_group,
                    "commitment_cost_id": item.commitment_cost_id,
                    "political_cost_id": item.political_cost_id,
                    "rank_terms": [
                        {
                            "fact": term.fact,
                            "goal": term.goal,
                            "tier": term.tier,
                            "unit": term.unit,
                            "amount": term.amount,
                            "evidence_group": term.evidence_group,
                        }
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
    # flattened adapter evidence. Admit only one scalar's bounded predicate, and never
    # overwrite a raw Reader (whose full scope/path must still be checked).
    for fact in declared_facts:
        engine = evidence_source.scalar_predicate_engine(fact.trigger)
        if fact.id not in result and fact.scope == "root" and engine:
            result[fact.id] = [
                decision_rules.Reader(
                    key=fact.id,
                    engine=engine,
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
    law_context = _frozen_law_context()
    context_readers = {}
    instance_contexts = {}
    for source, policy in (("mod/decisions/information.toml", information), *adapters.policies):
        readers = {reader.key: reader for reader in policy.readers}
        for rule in policy.rules:
            field = ".".join(rule.field).removeprefix("ai_strategy_default.")
            context = (
                observed_contexts.get(field)
                if source
                in {
                    "mod/decisions/information.toml",
                    "common/ai_strategies/00_default_strategy.txt",
                }
                else law_context
                if source.startswith("common/laws/")
                and len(rule.field) == 2
                and rule.field[-1] == "ai_enact_weight_modifier"
                else None
            )
            if context is not None:
                instance_contexts[(source, rule.id)] = context
                reader_field = (
                    "ai_enact_weight_modifier" if source.startswith("common/laws/") else field
                )
                context_readers[(source, rule.id)] = validate_context_readers(
                    reader_field,
                    context,
                    readers,
                    rule.conditions,
                    actor_path=policy.actor_path,
                    input_keys=tuple(rule.input_keys()),
                )
    instances = tuple(
        replace(
            instance, evaluation_context=instance_contexts.get((instance.source, instance.rule_id))
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
        "law_enact_context_document": _LAW_DOC_SHA256,
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
        tuple(
            (source, reader.key, _reader_signature(reader))
            for source, policy in (
                ("mod/decisions/information.toml", information),
                *adapters.policies,
            )
            for reader in policy.readers
        ),
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


def _rank_order(arbitration):
    raw = arbitration.get("rank", _RANK_ORDER)
    if not isinstance(raw, (list, tuple)) or any(not isinstance(key, str) for key in raw):
        raise ValueError("rank 必须是词典序维度列表")
    order = tuple(raw)
    if len(order) != len(_RANK_ORDER) or set(order) != set(_RANK_ORDER) or order[-1] != "action_id":
        raise ValueError("rank 必须完整且唯一，稳定 action_id 必须最后比较")
    return order


def _row_delta(
    row: decision_ir.ConsumerDecisionIR,
    values: Mapping[str, object],
    *,
    complement: float = 0.0,
    model: SituatedModel | None = None,
) -> float:
    """Unclamped signed contribution; only the consumer clamps the sum."""
    direction = -1.0 if row.base + row.opportunity < 0 else 1.0
    demand = sum(term.amount for term in row.rank_terms if values.get(term.fact) is True)
    return (
        row.base
        + row.opportunity
        + direction * (demand + complement - _row_cost(row, values, model=model))
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
            terms.append(f"{trigger} {predicate.op} {programs.numeric_literal(predicate.value)}")
    return " OR = { " + " ".join(terms) + " }"


def _cheap_cost_trigger(predicates, facts):
    bounds = []
    for predicate in predicates:
        fact = facts[predicate.fact]
        if type(predicate.value) is bool:
            continue
        if fact.minimum is not None:
            bounds.append(f"{fact.trigger} >= {programs.numeric_literal(fact.minimum)}")
        if fact.maximum is not None:
            bounds.append(f"{fact.trigger} <= {programs.numeric_literal(fact.maximum)}")
    return "AND = { " + " ".join(bounds) + " NOT = { " + _cost_trigger(predicates, facts) + " } }"


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
    facts = {fact.id: fact for fact in model.facts}
    for action_id, row in canonical.items():
        if row.operation != "add":
            raise ValueError("显式联合消费者仅支持已核实的 add 投影；倍率必须使用独立原版适配")
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
    _validate_action_groups(bundle.actions, facts)
    return bundle.actions


def _direction(row: decision_ir.ConsumerDecisionIR) -> float:
    return -1.0 if row.base + row.opportunity < 0 else 1.0


def _validate_action_groups(rows, facts) -> None:
    """Only declared identities deduplicate; equal predicates never imply identity.

    Variant branches are local numeric chains. Sharing their costs or evidence
    outside the chain requires a selected-variant runtime value, which this
    stateless adapter cannot legally provide. Reject that combination explicitly.
    """
    groups: dict[tuple[str, str, str], object] = {}
    priorities: dict[tuple[str, str], set[int]] = {}
    for row in rows:
        for label in ("variant_group", "cause_group", "commitment_cost_id", "political_cost_id"):
            value = getattr(row, label)
            if not isinstance(value, str) or (
                value and not re.fullmatch(r"[a-z][a-z0-9_]*", value)
            ):
                raise ValueError(f"行动 {row.action_id} 的 {label} ID 无效")
        if type(row.variant_priority) is not int or (
            row.variant_priority and not row.variant_group
        ):
            raise ValueError("variant_priority 必须是显式 variant_group 的整数优先级")
        if row.variant_group:
            if (
                row.cause_group
                or row.commitment_cost_id
                or row.political_cost_id
                or any(term.evidence_group for term in row.rank_terms)
            ):
                raise ValueError("variant 与跨卡 cause/evidence/shared cost 聚合尚无合法无状态投影")
            priority_key = (row.consumer_id, row.variant_group)
            used = priorities.setdefault(priority_key, set())
            if row.variant_priority in used:
                raise ValueError("同组 variant_priority 必须唯一")
            used.add(row.variant_priority)
        for category, name, signature in (
            ("variant", row.variant_group, _direction(row)),
            ("cause", row.cause_group, _direction(row)),
            *(
                ("evidence", term.evidence_group, (term.goal, term.unit, _direction(row)))
                for term in row.rank_terms
            ),
        ):
            if name:
                key = (row.consumer_id, category, name)
                if key in groups and groups[key] != signature:
                    raise ValueError(f"行动 {category} 去重组方向/目标/单位不一致：{name}")
                groups[key] = signature
        for identity, amount, predicates in (
            (row.commitment_cost_id, row.commitment, row.commitment_when),
            (row.political_cost_id, row.political_cost, row.political_when),
        ):
            if not identity:
                continue
            if amount <= 0 or not predicates:
                raise ValueError("显式 shared cost 必须包含正成本与谓词")
            specs = []
            for predicate in predicates:
                fact = facts.get(predicate.fact)
                if fact is None or fact.scope != "root" or fact.unit != predicate.unit:
                    raise ValueError("shared cost 事实作用域或单位无效")
                specs.append((predicate, fact))
            signature = (amount, _direction(row), frozenset(specs))
            key = (row.consumer_id, "cost", identity)
            if key in groups and groups[key] != signature:
                raise ValueError(f"shared cost 身份的金额/方向/谓词/作用域/单位不一致：{identity}")
            groups[key] = signature


@dataclass(frozen=True, slots=True)
class _ExplicitTerm:
    row: decision_ir.ConsumerDecisionIR
    amount: float
    facts: tuple[str, ...] = ()
    cost: tuple[CostPredicate, ...] = ()
    full_variant: bool = False


def _explicit_groups(rows, by_id, enabled):
    """Linear numeric chains: one known applicable member per declared group."""
    groups: dict[tuple[str, ...], list[_ExplicitTerm]] = {}
    for row in rows:
        if row.variant_group:
            groups.setdefault(("variant", row.variant_group), []).append(
                _ExplicitTerm(row, 0.0, full_variant=True)
            )
            continue
        cause_key = (
            ("cause", row.cause_group) if row.cause_group else ("local_cause", row.action_id)
        )
        groups.setdefault(cause_key, []).append(_ExplicitTerm(row, row.base + row.opportunity))
        for index, term in enumerate(row.rank_terms):
            if term.amount:
                key = (
                    ("demand", term.evidence_group)
                    if term.evidence_group
                    else ("local_demand", row.action_id, str(index))
                )
                groups.setdefault(key, []).append(
                    _ExplicitTerm(row, _direction(row) * term.amount, (term.fact,))
                )
        for label, identity, predicates, amount in (
            ("commitment", row.commitment_cost_id, row.commitment_when, row.commitment),
            ("political", row.political_cost_id, row.political_when, row.political_cost),
        ):
            if predicates and amount:
                key = (
                    ("shared_cost", identity) if identity else ("local_cost", row.action_id, label)
                )
                groups.setdefault(key, []).append(
                    _ExplicitTerm(row, -_direction(row) * amount, cost=predicates)
                )
        for index, relation in enumerate(_effective_relations(row, by_id, enabled)):
            if relation.kind != "enables":
                amount = (
                    _direction(row)
                    * relation.strength
                    * (-1 if relation.kind in {"substitutes", "conflicts"} else 1)
                )
                groups[("relation", row.action_id, str(index))] = [
                    _ExplicitTerm(row, amount, relation.condition_facts)
                ]
    return tuple(
        tuple(
            sorted(
                members,
                key=lambda term: (
                    -term.row.variant_priority if term.full_variant else -abs(term.amount),
                    term.row.action_id,
                ),
            )
        )
        for _, members in sorted(groups.items())
    )


def _term_links(term, by_id, enabled):
    links = _effective_relations(term.row, by_id, enabled)
    if any(relation.kind == "enables" and relation not in links for relation in term.row.relations):
        return None
    return links


def _variant_effects(row, links, facts):
    effects = [f"value = {programs.numeric_literal(row.base + row.opportunity)}"]
    for predicates, amount in (
        (row.commitment_when, row.commitment),
        (row.political_when, row.political_cost),
    ):
        if predicates and amount:
            effects.append(
                "if = { limit = { ROOT ?= { "
                + _cheap_cost_trigger(predicates, facts)
                + " } } } else = { add = "
                + programs.numeric_literal(-_direction(row) * amount)
                + " }"
            )
    effects.extend(
        "if = { limit = { ROOT ?= { "
        + facts[term.fact].trigger
        + " } } add = "
        + programs.numeric_literal(_direction(row) * term.amount)
        + " }"
        for term in row.rank_terms
    )
    for relation in links:
        if relation.kind != "enables":
            amount = (
                _direction(row)
                * relation.strength
                * (-1 if relation.kind in {"substitutes", "conflicts"} else 1)
            )
            effects.append(
                "if = { limit = { ROOT ?= { "
                + _condition(facts, relation.condition_facts)
                + " } } add = "
                + programs.numeric_literal(amount)
                + " }"
            )
    return " ".join(effects)


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


def _effective_relations(row, by_id, enabled_fields):
    """Only explicit world-fact conditions carry causal relation semantics.

    An eligible target card is an intention, never evidence of completion.
    Unconditional historical links remain trace metadata until migrated.
    """
    return tuple(
        relation
        for relation in _ordered_relations(row)
        if relation.condition_facts
        and relation.target in by_id
        and by_id[relation.target].field in enabled_fields
    )


def strategy_overlay(
    model: SituatedModel,
    *,
    enabled_consumer_fields: set[str] | frozenset[str] | None = None,
) -> dict[str, str]:
    """Emit one additive program per consumer without truth-table expansion.

    Independent action terms share the final clamp. Unknown qualification skips
    only its term; unknown cost takes its conservative expensive branch.
    """
    rows = _production_action_rows(model)
    facts = {fact.id: fact for fact in model.facts}
    by_id = {row.action_id: row for row in rows}
    enabled = (
        frozenset(consumer.field for consumer in model.consumers)
        if enabled_consumer_fields is None
        else frozenset(enabled_consumer_fields)
    )
    output = {}
    for consumer in model.consumers:
        if consumer.field not in enabled:
            continue
        declared = sorted(
            (row for row in rows if row.consumer_id == consumer.id),
            key=lambda row: row.action_id,
        )
        if len(declared) > consumer.budget:
            raise ValueError(f"消费者 {consumer.id} 的行动数超过预算；不能静默丢弃候选")
        parts = [
            f"\t\t# ACTION {row.action_id} [{row.domain}]; {row.explanation}\n" for row in declared
        ]
        for group in _explicit_groups(declared, by_id, enabled):
            branches: list[str] = []
            for term in group:
                links = _term_links(term, by_id, enabled)
                if links is None:
                    continue
                guards = tuple(
                    _condition(facts, relation.condition_facts)
                    for relation in links
                    if relation.kind == "enables"
                ) + ((_condition(facts, term.facts),) if term.facts else ())
                if term.full_variant:
                    effects = _variant_effects(term.row, links, facts)
                elif term.cost:
                    effects = (
                        "value = 0 if = { limit = { ROOT ?= { "
                        + _cheap_cost_trigger(term.cost, facts)
                        + " } } } else = { add = "
                        + programs.numeric_literal(term.amount)
                        + " }"
                    )
                else:
                    effects = f"value = {programs.numeric_literal(term.amount)}"
                keyword = "if" if not branches else "else_if"
                branches.append(
                    "\t\t"
                    + keyword
                    + " = { limit = { ROOT ?= { "
                    + _limit(term.row, facts, relation_guards=guards)
                    + " } } add = { "
                    + effects
                    + " } }\n"
                )
            parts.extend(branches)
        output[consumer.field] = (
            f"# ACTION joint_{consumer.id} [{consumer.domain}]; joint consumer contribution\n"
            "if = { limit = { ROOT ?= { is_ai = yes } }\n"
            "\tadd = {\n\t\tvalue = 0\n"
            + "".join(parts)
            + f"\t\tmin = {programs.numeric_literal(-consumer.max_delta)}\n"
            + f"\t\tmax = {programs.numeric_literal(consumer.max_delta)}\n"
            "\t}\n}\n"
        )
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
            actor_path = {"root": (), "owner": ("owner",)}.get(writer.actor)
            if actor_path is None or policy.actor_path != actor_path:
                raise ValueError(f"生产 actor 路径与冻结 IR 不一致：{writer.source}:{rule.id}")
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
    program_sources = {item.source for item in compiled_ir}
    exact_source = source_key or (
        next(iter(program_sources)) if len(program_sources) == 1 else None
    )
    if exact_source is None and compiled_ir:
        raise ValueError("联合消费者编译需要精确来源，不能跨来源混合字段")
    observations = {
        (source, key): signature for source, key, signature in model.observation_contracts
    }
    required_readers = {key for rule in compiled.rules for key in rule.input_keys()}
    readers = {reader.key: reader for reader in compiled.readers}
    if len(readers) != len(compiled.readers) or required_readers - readers.keys():
        raise ValueError("生产 reader 身份重复或缺失")
    for key in sorted(required_readers):
        if exact_source is None or observations.get((exact_source, key)) != _reader_signature(
            readers[key]
        ):
            raise ValueError(f"生产 reader 完整身份与冻结 IR 不一致：{exact_source}:{key}")
    compiled = programs.enable(compiled, source=exact_source or "empty")
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
        "adjustment_application": "signed_envelope_concrete_consumer_program; explicit_joint_net",
        "consumer_programs": programs.contract(compiled),
        "ir_to_pdx": "consumer_ir_to_bounded_consumer_program",
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


def evaluate_actions(
    model: SituatedModel,
    values: Mapping[str, object],
    *,
    is_ai: bool,
    enabled_consumer_fields: set[str] | frozenset[str] | None = None,
) -> dict[str, tuple[str, float]]:
    """Reference signed action terms, then clamp once per physical consumer."""
    if type(is_ai) is not bool:
        raise ValueError("is_ai 必须为明确布尔值")
    rows = _production_action_rows(model)
    if not is_ai:
        return {}
    if model.support_signals is not None:
        values = model.support_signals.values(values)
    by_id = {row.action_id: row for row in rows}
    enabled = (
        frozenset(consumer.field for consumer in model.consumers)
        if enabled_consumer_fields is None
        else frozenset(enabled_consumer_fields)
    )
    result = {}
    for consumer in model.consumers:
        if consumer.field not in enabled:
            continue
        candidates = sorted(
            (row for row in rows if row.consumer_id == consumer.id),
            key=lambda row: row.action_id,
        )
        if len(candidates) > consumer.budget:
            raise ValueError(f"消费者 {consumer.id} 的行动数超过预算；不能静默丢弃候选")
        total = 0.0
        for group in _explicit_groups(candidates, by_id, enabled):
            for term in group:
                row = term.row
                if _action_status(row, values) is not True:
                    continue
                links = _term_links(term, by_id, enabled)
                if (
                    links is None
                    or any(
                        _relation_conditions(relation, values) is not True
                        for relation in links
                        if relation.kind == "enables"
                    )
                    or any(values.get(fact) is not True for fact in term.facts)
                ):
                    continue
                if term.full_variant:
                    relation_delta = sum(
                        relation.strength
                        * (-1 if relation.kind in {"substitutes", "conflicts"} else 1)
                        for relation in links
                        if relation.kind != "enables"
                        and _relation_conditions(relation, values) is True
                    )
                    total += _row_delta(row, values, complement=relation_delta, model=model)
                elif term.cost:
                    if (
                        _cost_state(term.cost, values, {fact.id: fact for fact in model.facts})
                        is not False
                    ):
                        total += term.amount
                else:
                    total += term.amount
                break
        delta = max(-consumer.max_delta, min(consumer.max_delta, total))
        if delta != 0:
            result[consumer.field] = (f"joint_{consumer.id}", delta)
    return result


def evaluate_policy(
    policy: decision_rules.RuleSet,
    values: Mapping[str, object],
    *,
    is_ai: bool,
    config_model: SituatedModel | None = None,
) -> dict[str, tuple[str, float]]:
    """Reference the default strategy's disjoint physical consumer owners.

    Explicit consumers replace old field writers even when their current net
    contribution is neutral. They are not percentage adjustments to old scores.
    """
    if type(is_ai) is not bool:
        raise ValueError("is_ai 必须为明确布尔值")
    model = config_model or load_model()
    _production_action_rows(model)
    if model.support_signals is not None:
        values = model.support_signals.values(values)
    policy, _contract = compile_policy(policy, config_model=model)
    baseline = decision_rules.evaluate_ir(policy, values, is_ai=is_ai)
    if not is_ai:
        return baseline
    owned_fields = {consumer.field for consumer in model.consumers}
    result = {field: value for field, value in baseline.items() if field not in owned_fields}
    result.update(evaluate_actions(model, values, is_ai=True))
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
