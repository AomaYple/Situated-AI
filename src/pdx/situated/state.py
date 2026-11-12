"""从已登记事实派生有限状态向量，不把不同单位压成万能分数。"""

from __future__ import annotations

import math
from collections.abc import Mapping  # noqa: TC003
from typing import TYPE_CHECKING, Any, cast

from .schema import EvidenceValue, StateVector
from .signals import (
    CapacitySignal,
    CommitmentSignal,
    NeedSignal,
    OpportunitySignal,
    TypedState,
)

if TYPE_CHECKING:
    from pdx.country_state import CountryPolicy


def derive(values: Mapping[str, EvidenceValue]) -> StateVector:
    """只使用已知事实；未知值保持 ``None`` 并让消费者回退原版。"""

    def number(*names: str) -> tuple[tuple[str, float | None], ...]:
        result: list[tuple[str, float | None]] = []
        for name in names:
            value, known, _stale = _fact(values, name)
            value = value if known and type(value) in (int, float) else None
            numeric = (
                value
                if isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                else None
            )
            result.append((name, float(numeric) if numeric is not None else None))
        return tuple(result)

    def flags(*names: str) -> tuple[tuple[str, float | None], ...]:
        # StateVector keeps dimensionless truth as 0/1; this is not the
        # original reader's raw points/ratio or a combined utility score.
        result: list[tuple[str, float | None]] = []
        for name in names:
            value, known, _stale = _fact(values, name)
            result.append((name, float(value) if known and type(value) is bool else None))
        return tuple(result)

    pressure = flags("default", "war", "insurrection", "literacy_low")
    capacity = flags("stable_legitimacy", "strong_legitimacy", "bureaucracy_positive")
    opportunities = (*flags("subject"), *number("trade", "technology"))
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
    # 过期值仍保留 stale provenance，但不能继续作为已知事实驱动新决策。
    # 否则旧存档/旧快照会被误当成当前健康状态，破坏 unknown 回退合同。
    if item.stale:
        return None, False, True
    if type(item.value) in (int, float) and not math.isfinite(cast("int | float", item.value)):
        return None, False, False
    return item.value, True, False


def derive_typed(
    values: Mapping[str, EvidenceValue], *, policy: CountryPolicy | None = None
) -> TypedState:
    """Derive the typed view from the one normalized country policy.

    Capacities and selected layers use the coordinator's exact three-valued
    priority and recovery rules. Compatibility aliases reference policy nodes;
    the retired security capacity has no such node and remains explicitly
    unsupported rather than retaining a second threshold table.
    """
    from pdx import country_coordination, country_state  # noqa: PLC0415

    selected_policy = country_state.load() if policy is None else policy
    supplied = {name: _fact(values, name)[0] for name in selected_policy.readers}
    raw = {
        name: country_state._fact(supplied, name, reader)
        for name, reader in selected_policy.readers.items()
    }
    outcomes = country_coordination.evaluate(selected_policy, raw)
    if not selected_policy.enabled:
        outcomes = dict.fromkeys(outcomes)
    nodes = selected_policy.data["coordination"]

    def node(section: str, name: str) -> tuple[tuple[str, ...], str]:
        tree = nodes[section][name]["when"]
        names = tuple(dict.fromkeys(item["fact"] for clause in tree for item in clause))
        expression = " OR ".join(
            "("
            + " AND ".join(f"{item['fact']} {item['op']} {item['value']!r}" for item in clause)
            + ")"
            for clause in tree
        )
        return names, expression

    def combined(*names: str) -> tuple[tuple[str, ...], str]:
        references = tuple(node("capacities", name) for name in names)
        facts = tuple(dict.fromkeys(fact for source, _ in references for fact in source))
        return facts, "; ".join(
            f"{name}: {text}" for name, (_, text) in zip(names, references, strict=True)
        )

    def signal(
        cls,
        signal_id: str,
        outcome,
        description: tuple[tuple[str, ...], str],
        *,
        unit="boolean",
        quality="derived",
    ):
        names, expression = description
        return cls(
            id=signal_id,
            source="mod/decisions/country_state.toml",
            unit=unit,
            scope="country",
            value=outcome,
            known=outcome is not None,
            stale=any(_fact(values, name)[2] for name in names),
            quality=quality,
            expression=expression,
            source_facts=names,
        )

    capacities = [
        signal(CapacitySignal, name, outcomes[name], combined(name, "recovery"))
        for name in country_coordination.CAPACITIES
    ]
    layer_nodes = {
        "recovery": ("recovery",),
        "expansion": ("expansion_capacity", "recovery"),
        "stable": ("stable_capacity", "expansion_capacity", "recovery"),
        "foundation": ("development", "stable_capacity", "expansion_capacity", "recovery"),
    }
    for name in country_coordination.LAYERS:
        names, expression = combined(*layer_nodes[name])
        capacities.append(
            signal(
                CapacitySignal,
                f"layer_{name}",
                outcomes[f"layer_{name}"],
                (names, f"coordinator selected layer {name}; {expression}"),
            )
        )
    needs = tuple(
        signal(NeedSignal, f"need_{name}", outcomes[f"need_{name}"], node("needs", name))
        for name in country_coordination.NEEDS
    )
    by_need = {item.id: item for item in needs}

    def complement(name: str):
        value = outcomes[f"need_{name}"]
        return None if value is None else not value

    for alias, need in (
        ("administrative_capacity", "administrative"),
        ("political_capacity", "political"),
    ):
        names, expression = node("needs", need)
        capacities.append(
            signal(CapacitySignal, alias, complement(need), (names, f"NOT ({expression})"))
        )
    capacities.append(
        signal(
            CapacitySignal,
            "security_capacity",
            None,
            (("navy",), "unsupported: country policy declares no security capacity node"),
            quality="unknown",
        )
    )
    education = by_need["need_education"]
    administrative = next(item for item in capacities if item.id == "administrative_capacity")
    opportunities = (
        signal(
            OpportunitySignal,
            "opportunity_education",
            education.value,
            (education.source_facts, f"policy alias need_education: {education.expression}"),
        ),
        signal(
            OpportunitySignal,
            "opportunity_administrative_foundation",
            administrative.value,
            (
                administrative.source_facts,
                f"policy alias administrative_capacity: {administrative.expression}",
            ),
        ),
    )
    commitments = []
    for signal_id, fact in (
        ("debt_service", "debt_ratio"),
        ("military", "war"),
        ("diplomatic", "subject"),
    ):
        value = raw[fact]
        known = value is not None
        commitments.append(
            signal(
                CommitmentSignal,
                f"commitment_{signal_id}",
                value if known and selected_policy.enabled else None,
                ((fact,), f"policy reader {fact}"),
                unit=selected_policy.readers[fact]["unit"],
            )
        )
    return TypedState(tuple(capacities), needs, opportunities, tuple(commitments))


def contract() -> dict[str, object]:
    """Export the typed registry from the current normalized policy."""
    return derive_typed({}).as_dict()
