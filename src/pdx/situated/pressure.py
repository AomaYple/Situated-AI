"""压力严重度的纯函数。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


def severity(pressures: Mapping[str, float | None], name: str) -> float | None:
    value = pressures.get(name)
    if value is None:
        return None
    return max(0.0, min(1.0, float(value)))
