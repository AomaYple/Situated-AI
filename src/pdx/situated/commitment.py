"""既有承诺的边际成本与有界承受能力。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


def marginal_cost(commitments: Mapping[str, float | None], name: str) -> float | None:
    value = commitments.get(name)
    return None if value is None else max(0.0, float(value))


def overcommitted(commitments: Mapping[str, float | None], *, limit: float = 1.0) -> bool | None:
    values = [value for value in commitments.values() if value is not None]
    if not values:
        return None
    return sum(max(0.0, float(value)) for value in values) > limit
