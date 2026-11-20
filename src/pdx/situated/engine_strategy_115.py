"""Exact current strategy permissions from independently reviewed 1.15 PE evidence.

The historical validator stays separate. This module never projects old VAs or
infers arbitrary readers from a country-tagged container.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping


def validate(data: Mapping[str, Any]) -> None:
    """Reject permission, exact member, target identity and merge-contract drift."""
    from . import engine_scope_115  # noqa: PLC0415
    from .engine_strategy_1152 import CONTRACTS  # noqa: PLC0415

    for name, expected in CONTRACTS.items():
        if data.get(name) != expected:
            raise ValueError(f"1.15 策略独立字段合同不一致：{name}")
    if data.get("evidence_kind") != "binary_static" or data.get("runtime") != "unknown":
        raise ValueError("1.15 策略证据类别不一致")
    digest, exe_bytes = engine_scope_115.executable_identity()
    if data["exe"]["sha256"] != digest or data["exe"]["bytes"] != exe_bytes:
        raise ValueError("1.15 策略证据可执行文件身份不一致")
    # Exact current observations must cover every field's own parser branch and
    # own consumer, not merely a shared country container or another field.
    intervals = tuple(
        (
            int(point["va"], 16),
            int(point["va"], 16) + point["size"],
        )
        for point in data["observations"]
    )
    for field, contract in data["consumers"].items():
        for key in ("parser_va", "consumer_va"):
            address = int(contract[key], 16)
            if not any(start <= address < end for start, end in intervals):
                raise ValueError(f"1.15 策略精确字段缺少真实观察：{field}.{key}")
