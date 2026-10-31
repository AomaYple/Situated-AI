"""既有承诺的边际成本与有界承受能力。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .signals import CommitmentSignal

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .schema import EvidenceValue


def marginal_cost(commitments: Mapping[str, float | None], name: str) -> float | None:
    value = commitments.get(name)
    return None if value is None else max(0.0, float(value))


def overcommitted(commitments: Mapping[str, float | None], *, limit: float = 1.0) -> bool | None:
    values = [value for value in commitments.values() if value is not None]
    if not values:
        return None
    return sum(max(0.0, float(value)) for value in values) > limit


def _bindings(spec: Mapping[str, object]) -> tuple[str, ...]:
    actions = spec.get("actions")
    if not isinstance(actions, list):
        return ()
    return tuple(item for item in actions if isinstance(item, str))


def derive(
    values: Mapping[str, EvidenceValue],
    specifications: Mapping[str, Mapping[str, object]],
) -> tuple[CommitmentSignal, ...]:
    """把承诺成本降低为带单位/未知传播的类型化信号。"""

    result: list[CommitmentSignal] = []
    for name, spec in sorted(specifications.items()):
        source = spec.get("source_fact", name)
        if not isinstance(source, str) or not source:
            raise ValueError(f"承诺 {name} 的 source_fact 无效")
        item = values.get(source)
        known = item is not None and item.known
        raw = item.value if item is not None and known else None
        if known and not isinstance(raw, bool) and not isinstance(raw, (int, float)):
            # 布尔承诺保留布尔单位；数值承诺保留原始数值，绝不静默归一化。
            known = False
            raw = None
        unit = str(spec.get("unit", "normalized"))
        binding_values = _bindings(spec)
        result.append(
            CommitmentSignal(
                id=f"commitment_{name}",
                source=f"mod/decisions/commitments.toml:{name}",
                unit=unit,
                scope="country",
                value=raw if known else None,
                known=known,
                stale=bool(item.stale) if item is not None else False,
                quality="derived",
                expression=source,
                source_facts=(source,),
                bindings=binding_values,
            )
        )
    return tuple(result)


def contract(specifications: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
    return {
        "schema": 1,
        "signals": [
            {
                "id": f"commitment_{name}",
                "source": str(spec.get("source_fact", name)),
                "unit": str(spec.get("unit", "normalized")),
                "scope": "country",
                "bindings": list(_bindings(spec)),
                "unknown": str(spec.get("unknown", "vanilla")),
            }
            for name, spec in sorted(specifications.items())
        ],
        "unknown": "preserve_and_fallback_vanilla",
    }
