"""Strict finite support bindings; aliases lower to existing evidence readers."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pdx.decision_rules import Reader

    from .goals import Goal
    from .schema import ActionCard, ConsumerContract, EvidenceSpec

_ID = re.compile(r"[a-z][a-z0-9_]*\Z")
_RAW = re.compile(r"[a-z][a-z0-9_:]*\Z")
_CATEGORIES = ("capacities", "pressures", "opportunities", "commitments")
_OPS = {"=", "<", "<=", ">", ">="}


@dataclass(frozen=True, slots=True)
class SupportSignal:
    id: str
    alias: str
    category: str
    source_fact: str
    unit: str
    actions: tuple[str, ...]
    source: EvidenceSpec
    mode: str
    op: str | None = None
    value: bool | float | None = None

    @property
    def boolean_source(self) -> bool:
        # Historical typed condition facts can carry a reader's numeric unit.
        # Their trigger is already a predicate; the caller supplies its truth.
        return self.source.kind == "boolean" or not _RAW.fullmatch(self.source.trigger)

    def evidence(self) -> EvidenceSpec:
        trigger = self.source.trigger
        if self.mode == "predicate":
            if self.boolean_source:
                trigger = trigger if self.value else f"NOT = {{ {trigger} }}"
            else:
                trigger = f"{trigger} {self.op} {self.value:g}"
        return replace(
            self.source,
            id=self.alias,
            identity=f"support:{self.category}:{self.id}",
            source=f"mod/decisions/{self.category}.toml:{self.id}",
            domain="derived",
            kind="boolean" if self.mode == "predicate" else self.source.kind,
            unit="flag" if self.mode == "predicate" else self.unit,
            trigger=trigger,
            minimum=None if self.mode == "predicate" else self.source.minimum,
            maximum=None if self.mode == "predicate" else self.source.maximum,
            quality="derived",
        )

    def evaluate(self, raw: object) -> object | None:
        if self.boolean_source:
            valid = type(raw) is bool
        else:
            valid = type(raw) in (int, float) and math.isfinite(cast("float", raw))
        if not valid:
            return None
        if not self.boolean_source:
            number = cast("float", raw)
            if (self.source.minimum is not None and number < self.source.minimum) or (
                self.source.maximum is not None and number > self.source.maximum
            ):
                # Preserve finite out-of-range numbers for the existing bounded
                # cost fallback guard rather than turning them into a cheap tier.
                return number if self.mode == "value" else None
        if self.mode == "value":
            return raw
        if self.op == "=":
            return raw == self.value
        left, right = cast("float", raw), cast("float", self.value)
        return {"<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}[
            cast("str", self.op)
        ]


@dataclass(frozen=True, slots=True)
class SupportSignals:
    signals: tuple[SupportSignal, ...]
    reserved: tuple[tuple[str, str], ...]

    def values(self, values: Mapping[str, object]) -> dict[str, object]:
        result = dict(values)
        for item in self.signals:
            # Always overwrite caller aliases from the original typed input.
            result[item.alias] = item.evaluate(values.get(item.source_fact))
        return result


def references(row: Any) -> tuple[str, ...]:
    names = (
        *row.requires_all,
        *row.requires_any,
        *row.blocked_by,
        *row.exit_when,
        *row.consumes,
        *(item.fact for item in (*row.commitment_when, *row.political_when)),
        *(item.fact for item in row.rank_terms),
    )
    return tuple(sorted({name for name in names if name.startswith("support_")}))


def _table(sources: Mapping[str, Any], category: str) -> Mapping[str, Any]:
    data = sources.get(f"{category}.toml")
    if (
        not isinstance(data, dict)
        or set(data) != {"schema", category}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or not isinstance(data[category], dict)
    ):
        raise ValueError(f"{category}.toml 必须严格包含 schema=1 与 {category} 表")
    return cast("Mapping[str, Any]", data[category])


def _names(raw: object, label: str) -> tuple[str, ...]:
    if (
        not isinstance(raw, list)
        or any(not isinstance(x, str) or not _ID.fullmatch(x) for x in raw)
        or len(raw) != len(set(raw))
    ):
        raise ValueError(f"{label} 必须是唯一 ID 列表")
    return tuple(raw)


def _reserved(raw: Mapping[str, object], label: str) -> str | None:
    if "reserved" not in raw:
        return None
    if (
        set(raw) != {"reserved", "reason"}
        or raw["reserved"] is not True
        or not isinstance(raw["reason"], str)
        or not raw["reason"].strip()
    ):
        raise ValueError(f"{label} reserved 必须为 true 且只提供非空 reason")
    return raw["reason"]


def load(
    sources: Mapping[str, Any],
    facts: tuple[EvidenceSpec, ...],
    actions: tuple[ActionCard, ...],
    *,
    reader_shapes: Mapping[str, tuple[Reader, ...]],
) -> SupportSignals:
    by_fact = {item.id: item for item in facts}
    by_action = {item.id: item for item in actions}
    signals: list[SupportSignal] = []
    reserved: list[tuple[str, str]] = []
    identities: set[str] = set()
    for category in _CATEGORIES:
        for name, raw in sorted(_table(sources, category).items()):
            label = f"{category}.{name}"
            if not isinstance(name, str) or not _ID.fullmatch(name) or not isinstance(raw, dict):
                raise ValueError(f"支持源 ID/内容无效：{label}")
            reason = _reserved(raw, label)
            if reason is not None:
                reserved.append((label, reason))
                continue
            required = {"domain", "mode", "source_fact", "unit", "scope", "unknown", "actions"}
            mode = raw.get("mode")
            if (
                not isinstance(mode, str)
                or mode not in {"predicate", "value"}
                or set(raw) != required | ({"op", "value"} if mode == "predicate" else set())
            ):
                raise ValueError(f"支持源 {label} 字段/模式无效；不支持 TTL 或额外操作")
            alias = f"support_{name}"
            if alias in identities or alias in by_fact:
                raise ValueError(f"支持源 alias 重复：{alias}")
            identities.add(alias)
            source = (
                by_fact.get(raw["source_fact"]) if isinstance(raw["source_fact"], str) else None
            )
            if source is None or source.id.startswith("support_"):
                raise ValueError(f"支持源 {label} 引用未知/递归 reader")
            readers = reader_shapes.get(source.id)
            if not readers:
                raise ValueError(f"支持源 {label} 缺少原始 reader 形状：{source.id}")
            for reader in readers:
                if (
                    reader.scope != "root"
                    or reader.path
                    or reader.parameters
                    or reader.value_field is not None
                ):
                    raise ValueError(
                        f"支持源 {label} reader 不是可降低的 root scalar："
                        "scope/path/parameters/value_field 不受支持"
                    )
                expected_unit = source.unit
                if reader.unit != expected_unit and {reader.unit, expected_unit} - {
                    "boolean",
                    "flag",
                }:
                    raise ValueError(f"支持源 {label} 原始 reader unit 不一致")
            if len(set(readers)) != 1:
                raise ValueError(f"支持源 {label} 原始 reader 同名定义不一致")
            if (
                raw["scope"] != "root"
                or source.scope != "root"
                or raw["unit"] != source.unit
                or raw["unknown"] != "vanilla"
            ):
                raise ValueError(f"支持源 {label} reader 单位/作用域/unknown 无效")
            if not isinstance(raw["domain"], str) or not _ID.fullmatch(raw["domain"]):
                raise ValueError(f"支持源 {label} domain 无效")
            bound = _names(raw["actions"], label)
            if not bound or set(bound) - set(by_action):
                raise ValueError(f"支持源 {label} 必须绑定实际 action")
            signal = SupportSignal(
                name,
                alias,
                category,
                source.id,
                source.unit,
                bound,
                source,
                mode,
                raw.get("op"),
                raw.get("value"),
            )
            if mode == "value":
                if not _RAW.fullmatch(source.trigger) and source.kind != "boolean":
                    raise ValueError(f"数值支持源 {label} 必须绑定原始 reader")
            elif (
                not isinstance(raw["op"], str)
                or raw["op"] not in _OPS
                or type(raw["value"]) not in (bool, int, float)
                or (type(raw["value"]) is not bool and not math.isfinite(raw["value"]))
            ):
                raise ValueError(f"支持源 {label} 比较谓词无效")
            elif signal.boolean_source != (type(raw["value"]) is bool) or (
                signal.boolean_source and raw["op"] != "="
            ):
                raise ValueError(f"支持源 {label} 谓词类型不匹配")
            if not source.trigger or not source.source or not source.identity:
                raise ValueError(f"支持源 {label} 缺少 reader 证据")
            # Bounded numeric predicate inputs need a dedicated unknown guard,
            # which this finite alias subset does not invent.  Values used by
            # costs already have the compiler's explicit out-of-range fallback.
            if (
                mode == "predicate"
                and not signal.boolean_source
                and (source.minimum is not None or source.maximum is not None)
            ):
                raise ValueError(f"支持源 {label} 有界数值只支持 value 成本模式")
            for action in actions:
                condition_names = (
                    *action.requires_all,
                    *action.requires_any,
                    *action.blocked_by,
                    *action.exit_when,
                    *(term.fact for term in action.rank_terms),
                )
                if alias in condition_names and signal.evidence().kind != "boolean":
                    raise ValueError(f"支持源 {label} 数值不可直接用作条件/rank")
            actual = {item.id for item in actions if alias in references(item)}
            if actual != set(bound):
                raise ValueError(
                    f"支持源 {label} action 使用者不一致：声明={sorted(bound)} 实际={sorted(actual)}"
                )
            signals.append(signal)
    referenced = {name for action in actions for name in references(action)}
    if referenced != {item.alias for item in signals}:
        raise ValueError(f"行动引用未声明或 reserved 支持源：{sorted(referenced - identities)}")
    return SupportSignals(tuple(signals), tuple(reserved))


def load_goals(
    sources: Mapping[str, Any],
    actions: tuple[ActionCard, ...],
    consumers: tuple[ConsumerContract, ...],
) -> tuple[Goal, ...]:
    from .goals import Goal  # noqa: PLC0415

    consumer_ids = {item.id for item in consumers}
    result = []
    active_ids = set()
    for name, raw in sorted(_table(sources, "goals").items()):
        if not isinstance(name, str) or not _ID.fullmatch(name) or not isinstance(raw, dict):
            raise ValueError("目标 ID/内容无效")
        if _reserved(raw, f"goals.{name}") is not None:
            continue
        if (
            set(raw) != {"priority", "horizon", "consumers", "source_needs", "unknown"}
            or type(raw["priority"]) is not int
            or not 0 <= raw["priority"] <= 100
            or not isinstance(raw["horizon"], str)
            or raw["horizon"] not in {"crisis", "short", "medium", "long"}
            or raw["unknown"] != "vanilla"
        ):
            raise ValueError(f"目标 {name} 字段无效；生产目标不支持 TTL/动态压力")
        bound = _names(raw["consumers"], f"goals.{name}")
        source_needs = _names(raw["source_needs"], f"goals.{name}.source_needs")
        actual = {
            item.consumer for item in actions if any(term.goal == name for term in item.rank_terms)
        }
        actual_needs = {
            term.fact for item in actions for term in item.rank_terms if term.goal == name
        }
        if (
            not bound
            or not source_needs
            or set(bound) - consumer_ids
            or set(bound) != actual
            or set(source_needs) != actual_needs
        ):
            raise ValueError(f"目标 {name} 没有一致的实际 rank 使用者")
        result.append(
            Goal(
                name,
                raw["priority"],
                raw["horizon"],
                True,
                source_needs=source_needs,
                consumer_bindings=bound,
            )
        )
        active_ids.add(name)
    if {term.goal for action in actions for term in action.rank_terms} != active_ids:
        raise ValueError("行动 rank 引用未声明或 reserved 目标")
    return tuple(result)


def contract(model: SupportSignals) -> dict[str, object]:
    return {
        "schema": 1,
        "persistent_state": False,
        "unknown": "preserve_and_fallback_vanilla",
        "signals": [
            {
                "id": item.id,
                "alias": item.alias,
                "category": item.category,
                "source_fact": item.source_fact,
                "unit": item.unit,
                "actions": list(item.actions),
                "scope": item.source.scope,
                "reader_identity": item.source.identity,
                "reader_source": item.source.source,
                "reader_trigger": item.source.trigger,
                "mode": item.mode,
                "op": item.op,
                "value": item.value,
            }
            for item in model.signals
        ],
        "reserved": [{"id": key, "reason": reason} for key, reason in model.reserved],
    }
