"""机会窗口的有限判定。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


def available(opportunities: Mapping[str, float | None], name: str) -> bool | None:
    value = opportunities.get(name)
    if value is None:
        return None
    return value > 0
