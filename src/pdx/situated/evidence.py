"""事实注册表：来源、作用域、单位、未知语义和确定性 PDX 条件。"""

from __future__ import annotations

import re
import tomllib
from typing import TYPE_CHECKING

from .schema import EvidenceSpec

if TYPE_CHECKING:
    from pathlib import Path

_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_TRIGGER = re.compile(
    r"^[a-z][a-z0-9_]*(?:\s*(?:=|>=|<=|>|<)\s*(?:yes|no|-?[0-9]+(?:\.[0-9]+)?))?$"
)
_REFRESH = {"consumer", "monthly", "shock"}
_UNKNOWN = {"vanilla", "conservative", "lower_tier"}


def load(source: Path) -> tuple[EvidenceSpec, ...]:
    """严格加载 ``facts.toml``，拒绝隐式零值和未知触发器。"""

    data = tomllib.loads(source.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or not isinstance(data.get("facts"), dict):
        raise ValueError("事实注册表 schema 必须为 1 且包含 facts")
    result: list[EvidenceSpec] = []
    for key, raw in sorted(data["facts"].items()):
        if not _ID.fullmatch(key) or not isinstance(raw, dict):
            raise ValueError(f"事实 ID 或内容无效：{key}")
        required = {"domain", "source", "scope", "kind", "unit", "refresh", "unknown", "trigger"}
        optional = {"minimum", "maximum", "quality", "identity"}
        if not required <= set(raw) or set(raw) - required - optional:
            raise ValueError(f"事实 {key} 字段必须恰好为：{sorted(required)}")
        if (
            not all(isinstance(raw[name], str) and raw[name].strip() for name in required)
            or raw["refresh"] not in _REFRESH
            or raw["unknown"] not in _UNKNOWN
            or raw["kind"] not in {"boolean", "number", "ratio", "enum"}
            or raw["scope"] not in {"root", "target_country", "target_state"}
            or not _TRIGGER.fullmatch(raw["trigger"])
            or raw.get("quality", "observed") not in {"observed", "derived", "declared", "unknown"}
        ):
            raise ValueError(f"事实 {key} 的类型、作用域、刷新、未知或 trigger 无效")
        for bound in ("minimum", "maximum"):
            value = raw.get(bound)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float))
            ):
                raise ValueError(f"事实 {key} 的 {bound} 必须为有限数")
        result.append(EvidenceSpec(id=key, **raw))
    if len({item.id for item in result}) != len(result):
        raise ValueError("事实 ID 重复")
    return tuple(result)
