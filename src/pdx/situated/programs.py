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
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from . import core_contracts as contracts
from .ir import ActionIR, from_rule

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pdx.decision_rules import Reader, RuleSet

    from .semantic_core import ActionAssessment


@dataclass(frozen=True, slots=True)
class RelativeComparison:
    """消费者内的偏序证据；不模拟原版随机、选中或执行。"""

    witness: contracts.SelectionWitness
    non_dominated: tuple[contracts.EntityKey, ...]
    dominated: tuple[contracts.EntityKey, ...]
    deferred: tuple[contracts.EntityKey, ...]
    rule: str = "pareto_on_identical_dimensions_preserve_native_ties"


def _comparison_vector(item: ActionAssessment) -> dict[tuple[str, ...], float] | None:
    vector: dict[tuple[str, ...], float] = {}
    complete = True
    seen: set[tuple[str, ...]] = set()
    for term in (*item.benefits, *item.costs):
        dimension = (term.id, term.kind, term.unit, term.scope, term.horizon, term.baseline)
        if dimension in seen:
            raise ValueError(f"{item.candidate_id}: 重复比较项 {term.id}")
        seen.add(dimension)
        # Source facts are part of the semantic identity of a dimension.  Two
        # equal numbers with different evidence must remain incomparable; sort
        # the IDs because declaration order does not change their meaning.
        key = (
            *dimension,
            "sources",
            *sorted(term.source_ids),
        )
        if term.status != "known":
            complete = False
            continue
        if type(term.value) not in (int, float) or not math.isfinite(
            cast("int | float", term.value)
        ):
            raise ValueError(f"{item.candidate_id}: 比较项必须为有限数值")
        # 各维度保留单位、期限及现状基准，只反转成本方向，不跨维相加。
        vector[key] = cast("float", term.value) * (1 if term.kind == "benefit" else -1)
    return vector if complete and vector else None


def compare_candidates(
    consumer: contracts.ConsumerSpec,
    candidates: tuple[contracts.EntityKey, ...],
    assessments: Mapping[contracts.EntityKey, ActionAssessment],
) -> RelativeComparison:
    """为已观察候选建立 SelectionWitness，并比较同维度的完整已知评估。

    缺评估、资格未知或收益/成本未知保留为 deferred。无已证明成本上界时，
    conservative/lower_tier 也不能把未知成本填零；退回原版比较。已知低档
    应在现有程序中选择后再传入。返回的 frontier 不改变原版资格或随机尾部。
    """
    contracts.unique(candidates, "compare_candidates.candidates")
    if set(assessments) - set(candidates):
        raise ValueError("compare_candidates: 评估引入候选集合外的对象")
    actors = {item.actor for item in assessments.values()}
    if len(actors) > 1:
        raise ValueError("compare_candidates: 禁止跨国家比较")
    identities = {
        (identity[0], identity[2], identity[3])
        for item in assessments.values()
        if (identity := item.snapshot_identity) is not None
    }
    if len(identities) > 1 or any(item.snapshot_identity is None for item in assessments.values()):
        raise ValueError("compare_candidates: 评估快照身份不一致")
    objective_ids: set[str] = set()
    eligible: list[contracts.EntityKey] = []
    deferred: list[contracts.EntityKey] = []
    vectors: dict[contracts.EntityKey, dict[tuple[str, ...], float]] = {}
    for candidate in candidates:
        item = assessments.get(candidate)
        if item is None:
            deferred.append(candidate)
            continue
        if item.consumer_id != consumer.id:
            raise ValueError("compare_candidates: 禁止跨消费者比较")
        if (
            item.snapshot_identity is None
            or item.snapshot_identity[:3] != (item.actor, item.target, item.consumer_id)
            or item.actor.kind != "country"
        ):
            raise ValueError("compare_candidates: 评估快照对象串接")
        if (item.target is not None and item.target != candidate) or (
            item.target is None and item.candidate_id != candidate.id
        ):
            raise ValueError("compare_candidates: 候选与评估对象串接")
        objective_ids.update(item.objective_ids)
        if any(
            term.baseline and term.baseline not in item.objective_ids
            for term in (*item.benefits, *item.costs)
        ):
            raise ValueError("compare_candidates: 比较项未接入国家利益基准")
        if item.qualification != "known" or item.eligible is None:
            deferred.append(candidate)
            continue
        if item.eligible is not True:
            continue
        eligible.append(candidate)
        vector = _comparison_vector(item)
        if vector is None or item.unknowns:
            deferred.append(candidate)
        else:
            vectors[candidate] = vector
    dominated: set[contracts.EntityKey] = set()
    for candidate, vector in vectors.items():
        for other, other_vector in vectors.items():
            if candidate == other or vector.keys() != other_vector.keys():
                continue
            differences = tuple(other_vector[key] - value for key, value in vector.items())
            if all(value >= 0 for value in differences) and any(value > 0 for value in differences):
                dominated.add(candidate)
                break
    witness = contracts.SelectionWitness(
        consumer.id,
        candidates,
        tuple(eligible),
        consumer.comparator,
        tuple(sorted(objective_ids)),
        consumer.unknown_policy,
        consumer.neutral,
        consumer.tie_break,
        consumer.random,
        consumer.all_zero,
        consumer.baseline,
    )
    witness.validate(consumer)
    return RelativeComparison(
        witness,
        tuple(
            candidate
            for candidate in eligible
            if candidate not in dominated and candidate not in deferred
        ),
        tuple(candidate for candidate in candidates if candidate in dominated),
        tuple(deferred),
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


def _bounds(groups: tuple[ContributionGroup, ...], neutral: float) -> tuple[float, float]:
    # Group values use one physical consumer's unit; unrelated units never join.
    low = neutral + sum(min(0.0, *(i.value - neutral for i in g.variants)) for g in groups)
    high = neutral + sum(max(0.0, *(i.value - neutral for i in g.variants)) for g in groups)
    return (max(0.5, low), min(1.5, high)) if neutral == 1 else (max(-50.0, low), min(50.0, high))


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
        lower, upper = _bounds(groups, neutral)
        programs.append(
            ConsumerProgram(action_id, source, field, operation, neutral, lower, upper, groups)
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
            != _bounds(_groups(program.action_id, program.variants, neutral), neutral)
            or (program.operation == "multiply" and program.lower <= 0)
        ):
            raise ValueError("消费者贡献程序数值包络漂移")
        expected_groups = _groups(program.action_id, program.variants, neutral)
        if program.groups != expected_groups:
            raise ValueError("消费者贡献分组或最强档顺序漂移")
        if program.aggregation != "signed_envelope":
            raise ValueError("未支持的消费者贡献聚合合同")
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


def evaluate(
    policy: RuleSet, values: Mapping[str, object], selected: frozenset[str]
) -> dict[str, tuple[str, float]]:
    validate(policy)
    readers = {reader.key: reader for reader in policy.readers}
    result = {}
    for program in policy.consumer_programs:
        net = program.neutral
        for group in program.groups:
            for item in group.variants:
                if item.domain in selected and _applies(item, values, readers):
                    net += item.value - program.neutral
                    break
        net = max(program.lower, min(program.upper, net))
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
) -> str:
    """Lower the same typed groups at the caller's protected insertion point."""
    chunks = [
        f"\t\t# ACTION {program.action_id} [joint]; signed-envelope consumer action\n",
        f"\t\tif = {{ limit = {{ {ai_guard} }} {program.operation} = {{\n",
        f"\t\t\tvalue = {numeric_literal(program.neutral)}\n",
    ]
    for group in program.groups:
        candidates = [item for item in group.variants if item.action_id in guards]
        if not candidates:
            continue
        chunks.append(f"\t\t\t# GROUP {group.id}\n\t\t\tadd = {{ value = 0\n")
        for index, item in enumerate(candidates):
            chunks.append(producer_markers.get(item.action_id, ""))
            chunks.append(f"\t\t\t\t# {item.action_id} [{item.domain}]; {item.why}\n")
            amount = numeric_literal(Decimal(str(item.value)) - Decimal(str(program.neutral)))
            if item.action_id in descriptions:
                amount = f"{{ value = {amount} desc = {descriptions[item.action_id]} }}"
            branch = "if" if index == 0 else "else_if"
            chunks.append(
                f"\t\t\t\t{branch} = {{ limit = {{ {guards[item.action_id]} }} add = {amount} }}\n"
            )
        chunks.append("\t\t\t}\n")
    chunks.append(
        f"\t\t\tmin = {numeric_literal(program.lower)}\n"
        f"\t\t\tmax = {numeric_literal(program.upper)}\n\t\t}} }}\n"
    )
    return "".join(chunks)


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
