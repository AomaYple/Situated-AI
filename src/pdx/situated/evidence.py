"""事实注册表：来源、作用域、单位、未知语义和确定性 PDX 条件。"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from ..model import Assignment, Block, Scalar  # noqa: TID252
from ..parser import parse_text  # noqa: TID252
from .schema import EvidenceSpec

if TYPE_CHECKING:
    from pathlib import Path

_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_TRIGGER = re.compile(
    r"^[a-z][a-z0-9_]*(?:\s*(?:=|>=|<=|>|<)\s*(?:yes|no|-?[0-9]+(?:\.[0-9]+)?))?$"
)
_REFRESH = {"consumer", "monthly", "shock"}
_UNKNOWN = {"vanilla", "conservative", "lower_tier"}


@dataclass(frozen=True, slots=True)
class Observation:
    """One original getter, bound to current source and documented legal roles.

    Predicate thresholds and consumer fallback do not change the raw observation.
    Its value remains unknown until the original reader accepts a supplied value.
    """

    source: str
    source_sha256: str
    getter: str
    entity: str
    entity_kind: str
    roles: tuple[str, ...]
    proof: tuple[str, ...]
    original_unit: str
    timing: str
    unknown: str
    evaluation_cost: int

    def __post_init__(self) -> None:
        if (
            not self.source
            or not re.fullmatch(r"[0-9a-f]{64}", self.source_sha256)
            or not self.getter
            or not self.entity
            or not self.entity_kind
            or len(self.roles) != 1
            or not set(self.roles) <= {"actor", "target", "candidate", "auxiliary"}
            or not self.proof
            or not all(self.proof)
            or not self.original_unit
            or self.timing != "consumer"
            or self.unknown != "preserve_unknown"
            or type(self.evaluation_cost) is not int
            or not 1 <= self.evaluation_cost <= 16384
        ):
            raise ValueError("原始观测缺少当前来源、getter、合法对象/角色、单位、时机或有限成本")

    @property
    def identity(self) -> str:
        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


def scalar_predicate_engine(trigger: str) -> str | None:
    """Accept an atom or a bounded conjunction on one scalar, without scopes.

    Range checks belong to the same observation as its threshold. Arbitrary
    nested expressions, mixed readers, prefixes and quoted values are rejected.
    """
    if _TRIGGER.fullmatch(trigger):
        match = re.match(r"[a-z][a-z0-9_]*", trigger)
        assert match is not None
        return match[0]
    if len(trigger) > 2048:
        return None
    parsed = parse_text(trigger)
    if parsed.errors or len(parsed.root.items) != 1:
        return None
    outer = parsed.root.items[0]
    if (
        not isinstance(outer, Assignment)
        or outer.key != "AND"
        or outer.op != "="
        or outer.prefix is not None
        or not isinstance(outer.value, Block)
        or not 2 <= len(outer.value.items) <= 8
    ):
        return None
    engine = None
    for atom in outer.value.items:
        if (
            not isinstance(atom, Assignment)
            or atom.prefix is not None
            or not isinstance(atom.value, Scalar)
            or atom.value.quoted
            or not _TRIGGER.fullmatch(f"{atom.key} {atom.op} {atom.value.text}")
            or (engine is not None and atom.key != engine)
        ):
            return None
        engine = atom.key
    return engine


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
            or scalar_predicate_engine(raw["trigger"]) is None
            or (not _TRIGGER.fullmatch(raw["trigger"]) and raw["kind"] != "boolean")
            or raw.get("quality", "observed") not in {"observed", "derived", "declared", "unknown"}
        ):
            raise ValueError(f"事实 {key} 的类型、作用域、刷新、未知或 trigger 无效")
        if raw["kind"] == "boolean" and any(
            raw.get(bound) is not None for bound in ("minimum", "maximum")
        ):
            raise ValueError(f"布尔事实 {key} 不能声明数值边界")
        if raw["kind"] == "ratio" and raw["unit"] not in {"ratio", "proportion", "percent"}:
            raise ValueError(f"比例事实 {key} 的单位必须是 ratio/proportion/percent")
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
