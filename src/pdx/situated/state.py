"""从已登记事实派生有限状态向量，不把不同单位压成万能分数。"""

from __future__ import annotations

from collections.abc import Mapping  # noqa: TC003
from typing import cast

from .schema import EvidenceValue, StateVector


def derive(values: Mapping[str, EvidenceValue]) -> StateVector:
    """只使用已知事实；未知值保持 ``None`` 并让消费者回退原版。"""

    def number(*names: str) -> tuple[tuple[str, float | None], ...]:
        result: list[tuple[str, float | None]] = []
        for name in names:
            item = values.get(name)
            value = item.value if item and item.known and type(item.value) in (int, float) else None
            numeric = value if type(value) in (int, float) else None
            result.append(
                (name, float(cast("int | float", numeric)) if numeric is not None else None)
            )
        return tuple(result)

    pressure = number("default", "war", "insurrection", "literacy_low")
    capacity = number("stable_legitimacy", "strong_legitimacy", "bureaucracy_positive")
    return StateVector(capacities=capacity, pressures=pressure)
