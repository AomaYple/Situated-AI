"""D1/D2 migration oracle for every current legacy writer.

This test intentionally does not inspect generated marker counts.  It compares
the pre-IR RuleSet, the ConsumerIR-lowered RuleSet and a small independent
three-valued evaluator over positive, negative, unknown, player and boundary
inputs for every production rule.  It is a static migration witness; it does
not prove engine runtime behaviour or package byte equivalence.
"""

from __future__ import annotations

import math
import operator
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

import pytest

from pdx import decision_adapters, decision_rules, policy_audit
from pdx.situated import compiler, decision_ir

pytestmark = pytest.mark.unit

_OPS = {
    "=": operator.eq,
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}


def _known(reader: decision_rules.Reader, value: object) -> bool:
    if reader.kind == "boolean":
        return type(value) is bool
    if type(value) not in {int, float}:
        return False
    numeric = cast("int | float", value)
    if not math.isfinite(numeric):
        return False
    return (reader.minimum is None or numeric >= reader.minimum) and (
        reader.maximum is None or numeric <= reader.maximum
    )


def _policies() -> tuple[tuple[str, decision_rules.RuleSet], ...]:
    return (
        ("mod/decisions/information.toml", decision_rules.load()),
        *decision_adapters.load().policies,
    )


def _oracle(
    policy: decision_rules.RuleSet,
    values: Mapping[str, object],
    *,
    is_ai: bool,
) -> dict[str, tuple[str, float]]:
    """Evaluate legacy rules independently with explicit unknown short-circuiting."""

    if not is_ai:
        return {}
    readers = {reader.key: reader for reader in policy.readers}
    result: dict[str, tuple[str, float]] = {}
    groups: dict[tuple[str, ...], list[decision_rules.Rule]] = {}
    for rule in policy.rules:
        if rule.domain in policy.enabled_domains:
            groups.setdefault(rule.field, []).append(rule)
    for field, candidates in groups.items():
        candidates.sort(key=lambda item: -item.priority)
        for rule in candidates:
            unknown = False
            failed = False
            for predicate in rule.conditions:
                left = values.get(predicate.fact)
                reader = readers[predicate.fact]
                right = (
                    values.get(predicate.value.key)
                    if isinstance(predicate.value, decision_rules.FactReference)
                    else predicate.value
                )
                valid = _known(reader, left) and (
                    not isinstance(predicate.value, decision_rules.FactReference)
                    or _known(readers[predicate.value.key], right)
                )
                if not valid:
                    unknown = True
                    continue
                if not _OPS[predicate.op](cast("Any", left), cast("Any", right)):
                    failed = True
                    break
            if failed:
                continue
            if unknown:
                break
            result[".".join(field)] = (rule.id, rule.value)
            break
    return result


def _cases(
    policy: decision_rules.RuleSet, rule: decision_rules.Rule
) -> Iterable[tuple[str, dict[str, object], bool]]:
    satisfying, candidates = policy_audit._fixture(policy, rule)
    yield "satisfying", satisfying, True

    violating: dict[str, object] | None = None
    for key, choices in candidates.items():
        for value in choices:
            trial = {**satisfying, key: value}
            if not all(policy_audit._satisfies(item, trial) for item in rule.conditions):
                violating = trial
                break
        if violating is not None:
            break
    if violating is None:
        raise AssertionError(f"无法为规则构造反例：{rule.id}")
    yield "violating", violating, True

    yield "player", satisfying, False

    for key in satisfying:
        for label, value in (("unknown", None), ("invalid", "invalid"), ("nan", float("nan"))):
            yield f"{label}:{key}", {**satisfying, key: value}, True

    # Exercise a typed reader boundary where one exists.  This is an input
    # boundary witness; output value bounds are covered by policy_audit.
    readers = {reader.key: reader for reader in policy.readers}
    for key in satisfying:
        reader = readers[key]
        for label, value in (("minimum", reader.minimum), ("maximum", reader.maximum)):
            if value is not None:
                yield f"{label}:{key}", {**satisfying, key: value}, True
        # Includes every literal threshold and its neighbouring representable
        # floats, plus both sides of relative comparisons from the fixture.
        for index, value in enumerate(candidates[key]):
            yield f"boundary:{key}:{index}", {**satisfying, key: value}, True


def test_all_legacy_rules_match_independent_migration_oracle() -> None:
    model = compiler.load_model()
    assert model.consumer_ir is not None
    legacy_count = 0
    for source, policy in _policies():
        lowered = decision_ir.lower_legacy(policy, model.consumer_ir, source=source)
        for rule in policy.rules:
            legacy_count += 1
            isolated = replace(
                policy, rules=(rule,), enabled_domains=frozenset({rule.domain}), semantic_ir=()
            )
            lowered_isolated = replace(
                lowered,
                rules=(rule,),
                enabled_domains=frozenset({rule.domain}),
                semantic_ir=tuple(
                    item for item in lowered.semantic_ir if item.action_id == rule.id
                ),
            )
            for case, values, is_ai in _cases(policy, rule):
                expected = _oracle(isolated, values, is_ai=is_ai)
                if case == "satisfying":
                    assert expected == {".".join(rule.field): (rule.id, rule.value)}
                if case in {"violating", "player"} or case.startswith(
                    ("unknown:", "invalid:", "nan:")
                ):
                    assert expected == {}, (
                        f"oracle fixture did not exercise fallback: {rule.id}/{case}"
                    )
                before = decision_rules.evaluate(isolated, values, is_ai=is_ai)
                after = decision_rules.evaluate(lowered_isolated, values, is_ai=is_ai)
                assert before == expected, f"legacy oracle drift: {source}:{rule.id}/{case}"
                assert after == expected, f"IR migration drift: {source}:{rule.id}/{case}"

            # The whole consumer context also has to preserve first-match
            # order, including known-false clauses beside unknown inputs.
            values, _ = policy_audit._fixture(policy, rule)
            expected = _oracle(policy, values, is_ai=True)
            assert decision_rules.evaluate(policy, values, is_ai=True) == expected
            assert decision_rules.evaluate(lowered, values, is_ai=True) == expected
    assert legacy_count >= 1401
    assert legacy_count == 1414


def test_migration_oracle_detects_writer_semantic_drift() -> None:
    model = compiler.load_model()
    assert model.consumer_ir is not None
    source, policy = _policies()[0]
    target = policy.rules[0]
    writers = []
    for writer in model.consumer_ir.writers:
        if writer.source == source and writer.definition == target.id:
            assert writer.legacy is not None
            writers.append(
                replace(writer, legacy=replace(writer.legacy, value=writer.legacy.value + 0.25))
            )
        else:
            writers.append(writer)
    drifted = replace(model.consumer_ir, writers=tuple(writers))
    with pytest.raises(ValueError, match="不一致"):
        decision_ir.lower_legacy(policy, drifted, source=source)


@pytest.mark.parametrize("false_first", [False, True])
def test_oracle_known_false_dominates_unknown_without_using_semantic_ir(false_first: bool) -> None:
    policy = decision_rules.load()
    base = policy.rules[0]
    conditions: tuple[decision_rules.Predicate, ...] = (
        decision_rules.Predicate("war", "=", True),
        decision_rules.Predicate("default", "=", False),
    )
    if false_first:
        conditions = tuple(reversed(conditions))
    higher = replace(base, id="higher", priority=20, conditions=conditions)
    lower = replace(
        base,
        id="lower",
        priority=10,
        conditions=(decision_rules.Predicate("default", "=", True),),
    )
    policy = replace(policy, rules=(lower, higher), semantic_ir=())
    assert _oracle(policy, {"war": None, "default": True}, is_ai=True) == {
        ".".join(base.field): ("lower", lower.value)
    }
    assert _oracle(policy, {"war": None, "default": False}, is_ai=True) == {}
