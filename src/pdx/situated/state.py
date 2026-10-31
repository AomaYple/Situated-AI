"""从已登记事实派生有限状态向量，不把不同单位压成万能分数。"""

from __future__ import annotations

import math
from collections.abc import Mapping  # noqa: TC003
from typing import Any

from .schema import EvidenceValue, StateVector
from .signals import (
    CapacitySignal,
    CommitmentSignal,
    NeedSignal,
    OpportunitySignal,
    TypedState,
)


def derive(values: Mapping[str, EvidenceValue]) -> StateVector:
    """只使用已知事实；未知值保持 ``None`` 并让消费者回退原版。"""

    def number(*names: str) -> tuple[tuple[str, float | None], ...]:
        result: list[tuple[str, float | None]] = []
        for name in names:
            item = values.get(name)
            value = item.value if item and item.known and type(item.value) in (int, float) else None
            numeric = (
                value
                if isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                else None
            )
            result.append((name, float(numeric) if numeric is not None else None))
        return tuple(result)

    pressure = number("default", "war", "insurrection", "literacy_low")
    capacity = number("stable_legitimacy", "strong_legitimacy", "bureaucracy_positive")
    opportunities = number("subject", "trade", "technology")
    commitments = number("diplomatic_commitment", "military_commitment", "political_capacity")
    return StateVector(
        capacities=capacity,
        pressures=pressure,
        opportunities=opportunities,
        commitments=commitments,
    )


def _fact(values: Mapping[str, EvidenceValue], name: str) -> tuple[Any, bool, bool]:
    item = values.get(name)
    if item is None or not item.known:
        return None, False, bool(item.stale) if item is not None else False
    return item.value, True, item.stale


def _compare(
    values: Mapping[str, EvidenceValue], name: str, op: str, expected: object
) -> bool | None:
    actual, known, _ = _fact(values, name)
    if not known:
        return None
    if type(actual) is bool:
        if op != "=" or type(expected) is not bool:
            return None
        return actual is expected
    if isinstance(actual, bool) or not isinstance(actual, (int, float)):
        return None
    if isinstance(expected, bool) or not isinstance(expected, (int, float)):
        return None
    return {
        "=": actual == expected,
        "<": actual < expected,
        "<=": actual <= expected,
        ">": actual > expected,
        ">=": actual >= expected,
    }[op]


def _all(values: tuple[bool | None, ...]) -> bool | None:
    if any(item is False for item in values):
        return False
    return None if any(item is None for item in values) else True


def _any(values: tuple[bool | None, ...]) -> bool | None:
    if any(item is True for item in values):
        return True
    return None if any(item is None for item in values) else False


def _signal(
    cls,
    *,
    signal_id: str,
    value: object | None,
    known: bool,
    stale: bool,
    unit: str,
    expression: str,
    source_facts: tuple[str, ...],
    scope: str = "country",
    bindings: tuple[str, ...] = (),
):
    return cls(
        id=signal_id,
        source="mod/decisions/country_state.toml",
        unit=unit,
        scope=scope,
        value=value if known else None,
        known=known,
        stale=stale,
        quality="derived",
        expression=expression,
        source_facts=source_facts,
        bindings=bindings,
    )


def derive_typed(values: Mapping[str, EvidenceValue]) -> TypedState:
    """从已登记事实派生 K2 的四类类型化信号。

    每个表达式采用三值逻辑：缺失或未知事实不会被当成 ``False``，而是
    传播为未知；消费者可据此回退原版。表达式与源事实随信号导出，便于
    K5 将参考语义与 PDX 生成逐项见证。
    """

    def expr(signal_id: str, clauses: tuple[tuple[str, str, object], ...], *, unit="boolean"):
        outcome = _all(tuple(_compare(values, *clause) for clause in clauses))
        stale = any(_fact(values, name)[2] for name, _, _ in clauses)
        expression = " AND ".join(f"{name} {op} {literal!r}" for name, op, literal in clauses)
        return _signal(
            CapacitySignal,
            signal_id=signal_id,
            value=outcome,
            known=outcome is not None,
            stale=stale,
            unit=unit,
            expression=expression,
            source_facts=tuple(name for name, _, _ in clauses),
        )

    capacities = (
        expr("layer_recovery", (("default", "=", True),)),
        expr(
            "layer_expansion",
            (
                ("default", "=", False),
                ("war", "=", False),
                ("debt_ratio", "<", 0.2),
                ("net_surplus", ">", 0),
                ("bureaucracy", ">=", 100),
                ("legitimacy", ">=", 60),
                ("insurrection", "=", False),
            ),
        ),
        expr(
            "layer_stable",
            (
                ("default", "=", False),
                ("war", "=", False),
                ("debt_ratio", "<=", 0.5),
                ("net_surplus", ">=", 0),
                ("bureaucracy", ">=", 0),
            ),
        ),
        expr(
            "layer_foundation",
            (
                ("default", "=", False),
                ("war", "=", False),
                ("debt_ratio", "<", 0.75),
                ("income", ">", 0),
            ),
        ),
        expr("administrative_capacity", (("bureaucracy", ">=", 0),)),
        expr("political_capacity", (("legitimacy", ">=", 35), ("insurrection", "=", False))),
        expr("security_capacity", (("navy", ">", 0),)),
    )

    need_specs = {
        "fiscal": (("default", "=", True),),
        "administrative": (("bureaucracy", "<", 0),),
        "political": (("legitimacy", "<", 35),),
        "education": (("literacy", "<", 0.5), ("population", ">", 0)),
        "industry": (("industrial_route", "=", True),),
        "security": (("war", "=", True),),
        "reconstruction": (("war_defeat", "=", True), ("war", "=", False)),
        "overseas": (("expansion_route", "=", True), ("navy", ">=", 25), ("subject", "=", False)),
    }
    needs: list[NeedSignal] = []
    for name, clauses in need_specs.items():
        # Alternative evidence is intentionally represented as a tuple of OR
        # clauses for pressure/need domains where one of several facts suffices.
        alternatives = {
            "fiscal": (
                (("default", "=", True),),
                (("debt_ratio", ">=", 0.5),),
                (("loans", "=", True), ("net_surplus", "<", 0)),
            ),
            "political": ((("legitimacy", "<", 35),), (("insurrection", "=", True),)),
            "industry": (
                (("industrial_route", "=", True),),
                (("resource_route", "=", True),),
                (("war_defeat", "=", True),),
            ),
        }.get(name, (clauses,))
        results = tuple(
            _all(tuple(_compare(values, *clause) for clause in alternative))
            for alternative in alternatives
        )
        outcome = _any(results)
        names = tuple(sorted({fact for alternative in alternatives for fact, _, _ in alternative}))
        stale = any(_fact(values, fact)[2] for fact in names)
        expression = " OR ".join(
            " AND ".join(f"{fact} {op} {literal!r}" for fact, op, literal in alternative)
            for alternative in alternatives
        )
        needs.append(
            _signal(
                NeedSignal,
                signal_id=f"need_{name}",
                value=outcome,
                known=outcome is not None,
                stale=stale,
                unit="boolean",
                expression=expression,
                source_facts=names,
            )
        )

    opportunities: list[OpportunitySignal] = []
    for signal_id, fact, expression in (
        ("education", "literacy", "literacy < 0.5 AND population > 0"),
        ("administrative_foundation", "bureaucracy", "bureaucracy >= 0"),
    ):
        _, _, stale = _fact(values, fact)
        if signal_id == "education":
            result = _all(
                (_compare(values, "literacy", "<", 0.5), _compare(values, "population", ">", 0))
            )
        else:
            result = _compare(values, "bureaucracy", ">=", 0)
        opportunities.append(
            _signal(
                OpportunitySignal,
                signal_id=f"opportunity_{signal_id}",
                value=result,
                known=result is not None,
                stale=stale,
                unit="boolean",
                expression=expression,
                source_facts=(fact, "population") if signal_id == "education" else (fact,),
            )
        )

    commitments: list[CommitmentSignal] = []
    for signal_id, fact, unit, expression in (
        ("debt_service", "debt_ratio", "debt_to_credit_ratio", "debt_ratio"),
        ("military", "war", "boolean", "war"),
        ("diplomatic", "subject", "boolean", "subject"),
    ):
        source_value, known, stale = _fact(values, fact)
        commitments.append(
            _signal(
                CommitmentSignal,
                signal_id=f"commitment_{signal_id}",
                value=source_value,
                known=known,
                stale=stale,
                unit=unit,
                expression=expression,
                source_facts=(fact,),
            )
        )

    return TypedState(
        capacities=capacities,
        needs=tuple(needs),
        opportunities=tuple(opportunities),
        commitments=tuple(commitments),
    )


def contract() -> dict[str, object]:
    """导出不依赖具体事实值的状态表达式注册表。"""

    return derive_typed({}).as_dict()
