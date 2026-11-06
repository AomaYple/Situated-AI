"""Typed, bounded numeric contribution programs for concrete vanilla consumers.

The signed-envelope migration is an explicit aggregation policy: correlated
same-direction rules are alternative strength tiers, while opposite directions
jointly contribute. It does not infer that every historical predicate describes
an independent benefit or cost, or that script scores are globally comparable.
"""

from __future__ import annotations

import hashlib
import math
import operator
from dataclasses import asdict, dataclass, replace
from decimal import Decimal, localcontext
from typing import TYPE_CHECKING, Literal, cast

from .ir import ActionIR, from_rule
from .relations import RuleRelationProjection
from .relations import validate_execution as validate_relation

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pdx.decision_rules import Reader, RuleSet

    from .decision_ir import ConsumerDecisionIR
    from .schema import ConsumerContract, CostPredicate, Relation


@dataclass(frozen=True, slots=True)
class ScalarEffect:
    """A local conditional delta; its guard never selects another action."""

    guard: str
    amount: float | Decimal
    otherwise: float | Decimal = 0.0


@dataclass(frozen=True, slots=True)
class ScalarTerm:
    id: str
    action_id: str
    amount: float | Decimal
    effects: tuple[ScalarEffect, ...] = ()
    preceding: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScalarGroup:
    id: str
    terms: tuple[ScalarTerm, ...]
    selection: Literal["first", "minimum", "maximum"] = "first"


@dataclass(frozen=True, slots=True)
class ScalarProgram:
    """The common executable scalar algebra for rules and explicit cards."""

    action_id: str
    operation: str
    neutral: float
    lower: float | Decimal
    upper: float | Decimal
    groups: tuple[ScalarGroup, ...]


@dataclass(frozen=True, slots=True)
class CardCondition:
    """An adapter input, retaining card qualification separately from effects."""

    id: str
    row: ConsumerDecisionIR | None = None
    facts: tuple[str, ...] = ()
    cost: tuple[CostPredicate, ...] = ()
    enables: tuple[Relation, ...] = ()


@dataclass(frozen=True, slots=True)
class CardProgram:
    scalar: ScalarProgram
    conditions: tuple[CardCondition, ...]


def evaluate_scalar(program: ScalarProgram, guards: Mapping[str, bool]) -> float:
    """Select one member per cause, join all causes, then clamp exactly once."""
    total = program.neutral
    for group in program.groups:
        selected = 0.0
        for term in group.terms:
            if guards[term.id] and not any(guards[earlier] for earlier in term.preceding):
                amount = float(term.amount)
                for effect in term.effects:
                    amount += float(effect.amount if guards[effect.guard] else effect.otherwise)
                if group.selection == "first":
                    selected = amount
                    break
                selected = (
                    min(selected, amount) if group.selection == "minimum" else max(selected, amount)
                )
        total += selected
    return float(max(program.lower, min(program.upper, total)))


def _effect_text(effect: ScalarEffect, guards: Mapping[str, str], description: str = "") -> str:
    condition = guards[effect.guard]

    def amount(value):
        literal = numeric_literal(value)
        return f"{{ value = {literal} desc = {description} }}" if description else literal

    positive = f"add = {amount(effect.amount)}" if effect.amount else ""
    result = f"if = {{ limit = {{ {condition} }} {positive} }}"
    if effect.otherwise:
        result += f" else = {{ add = {amount(effect.otherwise)} }}"
    return result


def render_scalar(
    program: ScalarProgram,
    guards: Mapping[str, str],
    *,
    ai_guard: str,
    style: Literal["rules", "cards"],
    domain: str = "joint",
    intro: str = "",
    descriptions: Mapping[str, str] | None = None,
    producer_markers: Mapping[str, str] | None = None,
    comments: Mapping[str, str] | None = None,
) -> str:
    """Lower the same scalar groups, effects and final clamp at either adapter."""
    descriptions = descriptions or {}
    producer_markers = producer_markers or {}
    comments = comments or {}
    if style == "rules":
        chunks = [
            f"\t\t# ACTION {program.action_id} [joint]; signed-envelope consumer action\n",
            f"\t\tif = {{ limit = {{ {ai_guard} }} {program.operation} = {{\n",
            f"\t\t\tvalue = {numeric_literal(program.neutral)}\n",
        ]
    else:
        chunks = [
            f"# ACTION {program.action_id} [{domain}]; joint consumer contribution\n",
            f"if = {{ limit = {{ {ai_guard} }}\n\t{program.operation} = {{\n",
            f"\t\tvalue = {numeric_literal(program.neutral)}\n",
            intro,
        ]
    for group in program.groups:
        candidates = [term for term in group.terms if term.id in guards]
        if not candidates:
            continue
        wrapped_group = style == "rules" or group.selection != "first"
        if wrapped_group:
            chunks.append(f"\t\t\t# GROUP {group.id}\n\t\t\tadd = {{ value = 0\n")
        for index, term in enumerate(candidates):
            chunks.extend((producer_markers.get(term.id, ""), comments.get(term.id, "")))
            amount = numeric_literal(term.amount)
            if term.action_id in descriptions:
                amount = f"{{ value = {amount} desc = {descriptions[term.action_id]} }}"
            if style == "cards" or term.effects:
                effects = " ".join(
                    _effect_text(effect, guards, descriptions.get(term.action_id, ""))
                    for effect in term.effects
                )
                amount = f"{{ value = {numeric_literal(term.amount)}"
                amount += f" {effects}" if effects else ""
                amount += " }"
            indent = "\t\t\t\t" if style == "rules" else "\t\t"
            if term.preceding:
                branches = " ".join(
                    f"{'if' if index == 0 else 'else_if'} = {{ limit = {{ {guards[earlier]} }} }}"
                    for index, earlier in enumerate(term.preceding)
                )
                amount = (
                    "{ value = 0 "
                    + branches
                    + " else_if = { limit = { "
                    + guards[term.id]
                    + " } add = "
                    + amount
                    + " } }"
                )
                if group.selection == "first":
                    # Component groups containing variant selectors use an
                    # extremum below; first cannot safely ignore zero branches.
                    raise ValueError("variant子贡献必须使用有方向极值分组")
            if group.selection == "first":
                branch = "if" if index == 0 else "else_if"
                chunks.append(
                    f"{indent}{branch} = {{ limit = {{ {guards[term.id]} }} add = {amount} }}\n"
                )
            else:
                # PDX max limits the current value from above, hence it takes
                # the minimum candidate; min is the corresponding lower bound.
                operation = "max" if group.selection == "minimum" else "min"
                chunks.append(
                    f"{indent}{operation} = {{ value = 0 "
                    f"if = {{ limit = {{ {guards[term.id]} }} add = {amount} }} }}\n"
                )
        if wrapped_group:
            chunks.append("\t\t\t}\n")
    indent = "\t\t\t" if style == "rules" else "\t\t"
    chunks.append(
        f"{indent}min = {numeric_literal(program.lower)}\n"
        f"{indent}max = {numeric_literal(program.upper)}\n"
        + ("\t\t} }\n" if style == "rules" else "\t}\n}\n")
    )
    return "".join(chunks)


def _conservative(item: ActionIR) -> bool:
    return item.semantic_role == "cost" and bool(item.conservative_unknown_facts)


def _rule_term(item: ActionIR, neutral: float) -> ScalarTerm:
    values = (Decimal(str(item.value)), Decimal(str(neutral)))
    with localcontext() as context:
        context.prec = _source_precision(values)
        amount = values[0] - values[1]
    if _conservative(item):
        return ScalarTerm(
            item.action_id,
            item.action_id,
            0.0,
            (ScalarEffect(f"{item.action_id}__cheap", 0.0, amount),),
        )
    return ScalarTerm(item.action_id, item.action_id, amount)


def rule_scalar(program: ConsumerProgram) -> ScalarProgram:
    """Preserve signed-envelope grouping and decimal source precision."""
    lower, upper = _decimal_bounds(program.groups, program.neutral, program.relations)
    return ScalarProgram(
        program.action_id,
        program.operation,
        program.neutral,
        lower,
        upper,
        tuple(
            ScalarGroup(
                group.id,
                tuple(_rule_term(item, program.neutral) for item in group.variants),
                (
                    ("minimum" if group.direction < 0 else "maximum")
                    if any(_conservative(item) for item in group.variants)
                    else "first"
                ),
            )
            for group in program.groups
        )
        + _rule_relation_groups(program),
    )


def _rule_relation_groups(program: ConsumerProgram) -> tuple[ScalarGroup, ...]:
    groups = []
    for cause in sorted({item.cause_id for item in program.relations}):
        members = tuple(item for item in program.relations if item.cause_id == cause)
        identities = {
            (
                item.origins,
                item.output_unit,
                item.dependency_domain,
                item.relation_source,
                item.relation_target,
            )
            for item in members
        }
        if len(identities) != 1 or any(
            variant.contribution_group == cause for variant in program.variants
        ):
            raise ValueError("规则关系同因来源漂移或与未绑定原始来源的直接贡献重复")
        groups.append(
            ScalarGroup(
                f"{program.action_id}__relation_{cause}",
                tuple(ScalarTerm(item.guard_id, item.definition, item.amount) for item in members),
                "maximum",
            )
        )
    return tuple(groups)


@dataclass(frozen=True, slots=True)
class _CardTerm:
    row: ConsumerDecisionIR
    amount: float
    facts: tuple[str, ...] = ()
    cost: tuple[CostPredicate, ...] = ()
    category: str = "local"
    origins: tuple[str, ...] = ()
    full_variant: bool = False


def _direction(row: ConsumerDecisionIR) -> float:
    return -1.0 if row.base + row.opportunity < 0 else 1.0


def _card_groups(rows, links):
    """Build consumer-level sub-contributions after local variant selection."""
    groups: dict[tuple[str, ...], list[_CardTerm]] = {}
    for row in rows:
        for relation in row.relations:
            validate_relation(relation)
        shared_variant = row.variant_group and any(
            other.cause_group
            or other.commitment_cost_id
            or other.political_cost_id
            or any(term.evidence_group for term in other.rank_terms)
            or any(relation.cause_id for relation in other.relations)
            for other in rows
            if other.variant_group == row.variant_group
        )
        if row.variant_group and not shared_variant:
            groups.setdefault(("variant", row.variant_group), []).append(
                _CardTerm(row, 0.0, full_variant=True)
            )
            continue
        cause_key = (
            ("causal", row.cause_group) if row.cause_group else ("local_cause", row.action_id)
        )
        groups.setdefault(cause_key, []).append(
            _CardTerm(row, row.base + row.opportunity, category="base", origins=row.cause_origins)
        )
        for index, term in enumerate(row.rank_terms):
            if term.amount:
                key = (
                    ("causal", term.evidence_group)
                    if term.evidence_group
                    else ("local_demand", row.action_id, str(index))
                )
                groups.setdefault(key, []).append(
                    _CardTerm(
                        row,
                        _direction(row) * term.amount,
                        (term.fact,),
                        category="rank",
                        origins=term.origins,
                    )
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
                    _CardTerm(row, -_direction(row) * amount, cost=predicates, category="cost")
                )
        for index, relation in enumerate(links[row.action_id]):
            if relation.kind != "enables":
                amount = (
                    _direction(row)
                    * relation.strength
                    * (-1 if relation.kind in {"substitutes", "conflicts"} else 1)
                )
                key = (
                    ("causal", relation.cause_id)
                    if relation.cause_id
                    else ("relation", row.action_id, str(index))
                )
                groups.setdefault(key, []).append(
                    _CardTerm(
                        row,
                        amount,
                        relation.condition_facts,
                        category="relation",
                        origins=relation.origins,
                    )
                )
    for group_key, members in groups.items():
        if group_key[0] == "causal":
            categories = {member.category for member in members}
            origins = {frozenset(member.origins) for member in members}
            directions = {1 if member.amount > 0 else -1 for member in members if member.amount}
            if len(directions) > 1 or len(origins) > 1:
                raise ValueError("同一因果身份的方向/来源/作用域/语义不一致")
            if len(categories) > 1 and (not origins or not next(iter(origins))):
                raise ValueError("跨类别因果去重必须具有相同的规范原始来源")
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


def _variant_components(row, links, prefix, conditions):
    effects = []
    for label, predicates, amount in (
        ("commitment", row.commitment_when, row.commitment),
        ("political", row.political_when, row.political_cost),
    ):
        if predicates and amount:
            key = f"{prefix}:{label}"
            conditions.append(CardCondition(key, cost=predicates))
            effects.append(ScalarEffect(key, 0.0, -_direction(row) * amount))
    for index, term in enumerate(row.rank_terms):
        key = f"{prefix}:rank:{index}"
        conditions.append(CardCondition(key, facts=(term.fact,)))
        effects.append(ScalarEffect(key, _direction(row) * term.amount))
    for index, relation in enumerate(links):
        if relation.kind != "enables":
            key = f"{prefix}:relation:{index}"
            conditions.append(CardCondition(key, facts=relation.condition_facts))
            amount = (
                _direction(row)
                * relation.strength
                * (-1 if relation.kind in {"substitutes", "conflicts"} else 1)
            )
            effects.append(ScalarEffect(key, amount))
    return tuple(effects)


def card_program(
    consumer: ConsumerContract,
    rows: tuple[ConsumerDecisionIR, ...] | list[ConsumerDecisionIR],
    links: Mapping[str, tuple[Relation, ...]],
) -> CardProgram:
    """Compile card variants and local terms to the same algebra as rules."""
    if consumer.scope != "root" or consumer.operation != "add":
        raise ValueError("行动子贡献只支持已验证root/add消费者")
    conditions: list[CardCondition] = []
    eligible = [
        row
        for row in rows
        if not any(
            rel.kind == "enables" and rel not in links[row.action_id] for rel in row.relations
        )
    ]
    selectors = {}
    for row in eligible:
        if (
            row.variant_group
            and sum(other.variant_group == row.variant_group for other in eligible) > 32
        ):
            raise ValueError("variant子贡献选择超过已验证32候选预算")
        key = f"selected:{row.action_id}"
        selectors[row.action_id] = key
        conditions.append(
            CardCondition(
                key,
                row=row,
                enables=tuple(rel for rel in links[row.action_id] if rel.kind == "enables"),
            )
        )
    predecessors = {}
    for row in eligible:
        predecessors[row.action_id] = tuple(
            selectors[other.action_id]
            for other in sorted(eligible, key=lambda item: (-item.variant_priority, item.action_id))
            if row.variant_group
            and other.variant_group == row.variant_group
            and other.variant_priority > row.variant_priority
        )
    groups = []
    for group_index, members in enumerate(_card_groups(rows, links)):
        terms = []
        for term_index, member in enumerate(members):
            row = member.row
            if row.action_id not in selectors:
                continue
            key = f"card:{group_index}:{term_index}"
            conditions.append(
                CardCondition(
                    key,
                    row=row,
                    facts=member.facts,
                    enables=tuple(rel for rel in links[row.action_id] if rel.kind == "enables"),
                )
            )
            amount = member.amount
            effects: tuple[ScalarEffect, ...] = ()
            if member.full_variant:
                amount = row.base + row.opportunity
                effects = _variant_components(row, links[row.action_id], key, conditions)
            elif member.cost:
                cost_key = f"{key}:cost"
                conditions.append(CardCondition(cost_key, cost=member.cost))
                effects = (ScalarEffect(cost_key, 0.0, amount),)
                amount = 0.0
            terms.append(
                ScalarTerm(
                    key,
                    row.action_id,
                    amount,
                    effects,
                    () if member.full_variant else predecessors[row.action_id],
                )
            )
        selection: Literal["first", "minimum", "maximum"] = "first"
        if any(term.row.variant_group and not term.full_variant for term in members):
            sign = next((term.amount for term in members if term.amount), 0.0)
            selection = "minimum" if sign < 0 else "maximum"
        groups.append(ScalarGroup(f"card:{group_index}", tuple(terms), selection))
    return CardProgram(
        ScalarProgram(
            f"joint_{consumer.id}",
            consumer.operation,
            0.0,
            -consumer.max_delta,
            consumer.max_delta,
            tuple(groups),
        ),
        tuple(conditions),
    )


def card_value(row: ConsumerDecisionIR, *, complement: float = 0.0) -> CardProgram:
    """Compatibility row value, evaluated by the common unbounded scalar algebra."""
    key = "card:value"
    conditions = [CardCondition(key)]
    effects = _variant_components(row, (), key, conditions)
    term = ScalarTerm(
        key, row.action_id, row.base + row.opportunity + _direction(row) * complement, effects
    )
    return CardProgram(
        ScalarProgram(row.action_id, "add", 0.0, -math.inf, math.inf, (ScalarGroup(key, (term,)),)),
        tuple(conditions),
    )


@dataclass(frozen=True, slots=True)
class ContributionGroup:
    """Mutually exclusive numeric strength variants within one causal envelope."""

    id: str
    direction: int
    variants: tuple[ActionIR, ...]


@dataclass(frozen=True, slots=True)
class ConsumerProgram:
    action_id: str
    source: str
    field: tuple[str, ...]
    operation: str
    neutral: float
    lower: float
    upper: float
    groups: tuple[ContributionGroup, ...]
    aggregation: str = "signed_envelope"
    relations: tuple[RuleRelationProjection, ...] = ()

    @property
    def variants(self) -> tuple[ActionIR, ...]:
        return tuple(variant for group in self.groups for variant in group.variants)


def numeric_literal(value: float | Decimal) -> str:
    """Preserve finite source decimal precision without exponent notation."""
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("PDX 数值字面量必须有限")
    literal = format(number, "f")
    return literal.rstrip("0").rstrip(".") if "." in literal else literal


def _groups(action_id: str, variants: tuple[ActionIR, ...] | list[ActionIR], neutral: float):
    """Only explicitly independent causes add; undeclared variants share a tier."""
    groups = []
    for cause in sorted({item.contribution_group for item in variants}):
        for direction in (1, -1):
            candidates = tuple(
                sorted(
                    (
                        item
                        for item in variants
                        if item.contribution_group == cause
                        and (item.value >= neutral) == (direction == 1)
                    ),
                    key=lambda item: (
                        -direction * (item.value - neutral),
                        -item.priority,
                        item.action_id,
                    ),
                )
            )
            if candidates:
                suffix = f"_{cause}" if cause else ""
                groups.append(
                    ContributionGroup(
                        f"{action_id}{suffix}_{'positive' if direction > 0 else 'negative'}",
                        direction,
                        candidates,
                    )
                )
    return tuple(groups)


def _bounds(
    groups: tuple[ContributionGroup, ...],
    neutral: float,
    relations: tuple[RuleRelationProjection, ...] = (),
) -> tuple[float, float]:
    # Persist the established JSON-number contract, while lowering below keeps
    # the exact source-decimal limits instead of converting them back to float.
    lower, upper = _decimal_bounds(groups, neutral, relations)
    return float(lower), float(upper)


def _source_precision(values: tuple[Decimal, ...]) -> int:
    """Enough decimal places for every finite source and all possible carries."""
    if any(not value.is_finite() for value in values):
        raise ValueError("消费者贡献数值必须有限")
    integers = max(0, *(value.adjusted() + 1 for value in values))
    fractions = max(0, *(-cast("int", value.as_tuple().exponent) for value in values))
    return integers + fractions + len(str(len(values))) + 2


def _decimal_bounds(
    groups: tuple[ContributionGroup, ...],
    neutral: float,
    relations: tuple[RuleRelationProjection, ...] = (),
) -> tuple[Decimal, Decimal]:
    # Group values use one physical consumer's unit; unrelated units never join.
    base, zero = Decimal(str(neutral)), Decimal(0)
    values = (
        base,
        *(Decimal(str(item.value)) for group in groups for item in group.variants),
        *(Decimal(str(item.amount)) for item in relations),
    )
    with localcontext() as context:
        context.prec = _source_precision(values)
        deltas = tuple(
            tuple(Decimal(str(item.value)) - base for item in group.variants) for group in groups
        )
        low = base + sum((min(zero, *items) for items in deltas), zero)
        high = base + sum((max(zero, *items) for items in deltas), zero)
        high += sum(
            (
                max(Decimal(str(item.amount)) for item in relations if item.cause_id == cause)
                for cause in {item.cause_id for item in relations}
            ),
            zero,
        )
        return (
            (max(Decimal("0.5"), low), min(Decimal("1.5"), high))
            if neutral == 1
            else (max(Decimal(-50), low), min(Decimal(50), high))
        )


def enable(policy: RuleSet, *, source: str) -> RuleSet:
    """Explicitly migrate every input rule to the bounded signed-envelope policy.

    Mixed operations are deliberately rejected: an additive score and a relative
    multiplier need a field-specific conversion contract, never an implicit sum.
    """
    if not source:
        raise ValueError("消费者贡献程序缺少精确来源")
    semantic = policy.semantic_ir or tuple(from_rule(rule, source=source) for rule in policy.rules)
    original = {rule.id: rule for rule in policy.rules}
    if len(original) != len(policy.rules) or len(semantic) != len(original):
        raise ValueError("贡献程序规则身份重复或不完整")
    for item in semantic:
        if item.source != source or item.to_rule() != original.get(item.action_id):
            raise ValueError(f"贡献程序 IR 来源或语义不一致：{item.action_id}")
    fields: dict[tuple[str, ...], list[ActionIR]] = {}
    for item in semantic:
        fields.setdefault(tuple(item.field.split(".")), []).append(item)
    programs = []
    for field, variants in sorted(fields.items()):
        if any(not math.isfinite(item.value) for item in variants):
            raise ValueError("消费者贡献数值必须有限")
        operations = {item.operation for item in variants}
        if len(operations) != 1 or not operations <= {"add", "multiply"}:
            raise ValueError(f"消费者贡献程序需要显式混合操作合同：{source}:{'.'.join(field)}")
        operation = next(iter(operations))
        neutral = 1.0 if operation == "multiply" else 0.0
        if operation == "multiply" and any(item.value <= 0 for item in variants):
            raise ValueError("消费者贡献倍率必须保持正值")
        if field[-1] == "wanted_construction_output" and operation != "multiply":
            raise ValueError("建设目标只允许正倍率贡献程序")
        identity = hashlib.sha256(f"{source}:{'.'.join(field)}".encode()).hexdigest()[:16]
        action_id = f"program_{identity}"
        groups = _groups(action_id, variants, neutral)
        relations = tuple(
            binding.projection
            for binding in policy.rule_relation_bindings
            if binding.projection.source == source and binding.projection.field == field
        )
        lower, upper = _bounds(groups, neutral, relations)
        programs.append(
            ConsumerProgram(
                action_id,
                source,
                field,
                operation,
                neutral,
                lower,
                upper,
                groups,
                relations=relations,
            )
        )
    return replace(policy, semantic_ir=semantic, consumer_programs=tuple(programs))


def validate(policy: RuleSet) -> None:
    """Reject stale or partial programs rather than silently evaluating old rules."""
    if not policy.consumer_programs:
        if policy.rules:
            raise ValueError("贡献程序为空，不能声明规则迁移完成")
        return
    variants = [variant for program in policy.consumer_programs for variant in program.variants]
    expected = policy.semantic_ir
    if len(variants) != len(expected) or {item.action_id: item for item in variants} != {
        item.action_id: item for item in expected
    }:
        raise ValueError("消费者贡献程序与 semantic IR 不一致")
    if {item.action_id: item.to_rule() for item in expected} != {
        rule.id: rule for rule in policy.rules
    }:
        raise ValueError("贡献程序源规则与 semantic IR 不一致")
    if len({program.field for program in policy.consumer_programs}) != len(
        policy.consumer_programs
    ):
        raise ValueError("具体消费者存在多个贡献程序")
    readers = {reader.key: reader for reader in policy.readers}
    projected = [item for program in policy.consumer_programs for item in program.relations]
    if len(projected) != len(policy.rule_relation_bindings) or {
        item.guard_id for item in projected
    } != {binding.projection.guard_id for binding in policy.rule_relation_bindings}:
        raise ValueError("规则关系投影没有唯一实际消费者程序")
    if len({binding.projection.guard_id for binding in policy.rule_relation_bindings}) != len(
        policy.rule_relation_bindings
    ):
        raise ValueError("规则关系投影writer/cause身份重复")
    for binding in policy.rule_relation_bindings:
        binding.validate(readers)
    for program in policy.consumer_programs:
        identity = hashlib.sha256(
            f"{program.source}:{'.'.join(program.field)}".encode()
        ).hexdigest()[:16]
        if not program.variants or program.action_id != f"program_{identity}":
            raise ValueError("消费者贡献程序身份缺失或漂移")
        neutral = 1.0 if program.operation == "multiply" else 0.0
        if (
            program.operation not in {"add", "multiply"}
            or program.neutral != neutral
            or (program.lower, program.upper)
            != _bounds(
                _groups(program.action_id, program.variants, neutral), neutral, program.relations
            )
            or (program.operation == "multiply" and program.lower <= 0)
        ):
            raise ValueError("消费者贡献程序数值包络漂移")
        expected_groups = _groups(program.action_id, program.variants, neutral)
        if program.groups != expected_groups:
            raise ValueError("消费者贡献分组或最强档顺序漂移")
        if program.aggregation != "signed_envelope":
            raise ValueError("未支持的消费者贡献聚合合同")
        expected_relations = tuple(
            binding.projection
            for binding in policy.rule_relation_bindings
            if binding.projection.source == program.source
            and binding.projection.field == program.field
        )
        if program.relations != expected_relations:
            raise ValueError("消费者规则关系与已验证端口绑定不一致")
        for relation in program.relations:
            relation.validate()
            if (
                relation.definition not in {item.action_id for item in program.variants}
                or relation.operation != program.operation
                or relation.dependency_domain not in {item.domain for item in expected}
            ):
                raise ValueError("规则关系缺少同一消费者行动或已登记依赖领域")
        _rule_relation_groups(program)
        if any(
            item.source != program.source
            or tuple(item.field.split(".")) != program.field
            or item.operation != program.operation
            for item in program.variants
        ):
            raise ValueError("消费者贡献程序字段、来源或操作漂移")


def _applies(item: ActionIR, values: Mapping[str, object], readers: Mapping[str, Reader]) -> bool:
    from pdx.decision_rules import FactReference  # noqa: PLC0415

    operations = {
        "=": operator.eq,
        "<": operator.lt,
        "<=": operator.le,
        ">": operator.gt,
        ">=": operator.ge,
    }
    if any(not readers[key].accepts(values.get(key)) for key in item.required_known_facts):
        return False
    for predicate in item.predicates:
        left = values.get(predicate.fact)
        right = predicate.value
        if isinstance(right, FactReference):
            if not readers[right.key].accepts(values.get(right.key)):
                return False
            right = values[right.key]
        if not readers[predicate.fact].accepts(left):
            return False
        if not operations[predicate.operator](
            cast("bool | float", left), cast("bool | float", right)
        ):
            return False
    return True


def _cost_guard_values(
    item: ActionIR, values: Mapping[str, object], readers: Mapping[str, Reader]
) -> tuple[bool, bool]:
    """Core identity stays proven; only declared pressure inputs may be unknown."""
    from pdx.decision_rules import FactReference  # noqa: PLC0415

    core = all(readers[key].accepts(values.get(key)) for key in item.required_known_facts)
    cheap = False
    operations = {
        "=": operator.eq,
        "<": operator.lt,
        "<=": operator.le,
        ">": operator.gt,
        ">=": operator.ge,
    }
    pressure = set(item.conservative_unknown_facts)
    pressure_known = True
    for predicate in item.predicates:
        left = values.get(predicate.fact)
        right = predicate.value
        valid = readers[predicate.fact].accepts(left)
        if isinstance(right, FactReference):
            valid = valid and readers[right.key].accepts(values.get(right.key))
            right = values.get(right.key)
        state = (
            operations[predicate.operator](cast("bool | float", left), cast("bool | float", right))
            if valid
            else None
        )
        if predicate.fact in pressure:
            pressure_known = pressure_known and valid
            cheap = cheap or state is False
        else:
            core = core and state is True
    if not pressure_known and item.unknown_cost_required_known_facts:
        core = core and all(
            readers[key].accepts(values.get(key)) for key in item.unknown_cost_required_known_facts
        )
    return core, cheap


def evaluate(
    policy: RuleSet,
    values: Mapping[str, object],
    selected: frozenset[str],
    *,
    guard_overrides: Mapping[str, bool] | None = None,
    cost_overrides: Mapping[str, tuple[bool, bool]] | None = None,
) -> dict[str, tuple[str, float]]:
    validate(policy)
    semantic = {item.action_id: item for item in policy.semantic_ir}
    for identity, value in (guard_overrides or {}).items():
        item = semantic.get(identity)
        if item is None or type(value) is not bool or _conservative(item):
            raise ValueError("端口守卫替换必须绑定普通已知规则和明确布尔值")
    readers = {reader.key: reader for reader in policy.readers}
    for identity, states in (cost_overrides or {}).items():
        if (
            identity not in semantic
            or not _conservative(semantic[identity])
            or not isinstance(states, tuple)
            or len(states) != 2
            or any(type(state) is not bool for state in states)
            or not any(
                binding.definition == identity and binding.role == "cost"
                for binding in policy.port_bindings
            )
        ):
            raise ValueError("成本守卫替换必须绑定实际core/cheap端口与明确布尔状态")
    result = {}
    for program in policy.consumer_programs:
        guards = {
            item.action_id: item.domain in selected
            and (
                guard_overrides[item.action_id]
                if guard_overrides is not None and item.action_id in guard_overrides
                else _applies(item, values, readers)
            )
            for item in program.variants
        }
        for item in program.variants:
            if _conservative(item):
                core, cheap = (cost_overrides or {}).get(
                    item.action_id, _cost_guard_values(item, values, readers)
                )
                guards[item.action_id] = item.domain in selected and core
                guards[f"{item.action_id}__cheap"] = cheap
        for binding in policy.rule_relation_bindings:
            relation = binding.projection
            if relation in program.relations:
                guards[relation.guard_id] = (
                    guards[relation.definition]
                    and relation.dependency_domain in selected
                    and binding.evaluate(values, readers)
                )
        net = evaluate_scalar(rule_scalar(program), guards)
        if net != program.neutral:
            result[".".join(program.field)] = (program.action_id, net)
    return result


def render(
    program: ConsumerProgram,
    *,
    guards: Mapping[str, str],
    ai_guard: str,
    descriptions: Mapping[str, str],
    producer_markers: Mapping[str, str],
    cost_guards: Mapping[str, tuple[str, str]] | None = None,
    relation_guards: Mapping[str, str] | None = None,
) -> str:
    """Lower the same typed groups at the caller's protected insertion point."""
    if program.relations and relation_guards is None:
        raise ValueError("规则关系生成缺少显式端口守卫合同")
    selected_guards = dict(guards)
    for relation in program.relations:
        if relation_guards is not None and relation.guard_id in relation_guards:
            if relation.definition not in selected_guards:
                continue
            selected_guards[relation.guard_id] = (
                "AND = { "
                + selected_guards[relation.definition]
                + " "
                + relation_guards[relation.guard_id]
                + " }"
            )
    for item in program.variants:
        if _conservative(item) and item.action_id in guards:
            if cost_guards is None or item.action_id not in cost_guards:
                raise ValueError(f"保守未知成本缺少 core/cheap 生成守卫：{item.action_id}")
            core, cheap = cost_guards[item.action_id]
            selected_guards[item.action_id] = core
            selected_guards[f"{item.action_id}__cheap"] = cheap
    return render_scalar(
        rule_scalar(program),
        selected_guards,
        ai_guard=ai_guard,
        style="rules",
        descriptions=descriptions,
        producer_markers=producer_markers,
        comments={
            item.action_id: f"\t\t\t\t# {item.action_id} [{item.domain}]; {item.why}\n"
            for item in program.variants
        },
    )


def contract(policy: RuleSet) -> dict[str, object]:
    validate(policy)
    return {
        "aggregation": "signed_envelope",
        "semantics": "strongest_known_variant_per_explicit_cause_and_direction_then_joint_net_once_bounded",
        "inference_boundary": "numeric_direction_is_not_semantic_benefit_or_cost",
        "program_count": len(policy.consumer_programs),
        "variant_count": sum(len(program.variants) for program in policy.consumer_programs),
        "programs": [asdict(program) for program in policy.consumer_programs],
    }
