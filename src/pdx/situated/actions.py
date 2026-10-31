"""行动卡注册表和跨域引用检查。"""

from __future__ import annotations

import math
import re
import tomllib
from typing import TYPE_CHECKING

from .schema import ActionCard, ConsumerContract

if TYPE_CHECKING:
    from pathlib import Path

_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_UNKNOWN = {"vanilla", "conservative", "lower_tier"}


def _names(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not _ID.fullmatch(item) for item in value
    ):
        raise ValueError(f"{label} 必须是小写 ID 列表")
    return tuple(value)


def load(source: Path) -> tuple[tuple[ConsumerContract, ...], tuple[ActionCard, ...]]:
    data = tomllib.loads(source.read_text(encoding="utf-8"))
    if (
        data.get("schema") != 1
        or not isinstance(data.get("consumers"), dict)
        or not isinstance(data.get("actions"), dict)
    ):
        raise ValueError("行动卡 schema 必须为 1 且包含 consumers/actions")
    consumers: list[ConsumerContract] = []
    for key, raw in sorted(data["consumers"].items()):
        if not _ID.fullmatch(key) or not isinstance(raw, dict):
            raise ValueError(f"消费者 ID 或内容无效：{key}")
        required = {"field", "domain", "max_delta", "budget", "vanilla_tail"}
        if (
            set(raw) != required
            or not isinstance(raw["field"], str)
            or not isinstance(raw["domain"], str)
        ):
            raise ValueError(f"消费者 {key} 字段无效")
        if (
            isinstance(raw["max_delta"], bool)
            or not isinstance(raw["max_delta"], (int, float))
            or not math.isfinite(raw["max_delta"])
            or raw["max_delta"] <= 0
        ):
            raise ValueError(f"消费者 {key} max_delta 必须为正有限数")
        if type(raw["budget"]) is not int or raw["budget"] <= 0:
            raise ValueError(f"消费者 {key} budget 必须为正整数")
        consumers.append(ConsumerContract(id=key, **raw))
    actions: list[ActionCard] = []
    for key, raw in sorted(data["actions"].items()):
        if not _ID.fullmatch(key) or not isinstance(raw, dict):
            raise ValueError(f"行动 ID 或内容无效：{key}")
        required = {
            "domain",
            "consumer",
            "improves",
            "consumes",
            "requires_all",
            "requires_any",
            "blocked_by",
            "complements",
            "substitutes",
            "conflicts",
            "enables",
            "exit_when",
            "base",
            "stress",
            "opportunity",
            "commitment",
            "political_cost",
            "max_delta",
            "unknown_policy",
            "explanation",
        }
        if set(raw) != required:
            raise ValueError(f"行动 {key} 字段必须恰好为：{sorted(required)}")
        numbers = [
            raw[name]
            for name in (
                "base",
                "stress",
                "opportunity",
                "commitment",
                "political_cost",
                "max_delta",
            )
        ]
        if (
            any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in numbers
            )
            or raw["max_delta"] <= 0
        ):
            raise ValueError(f"行动 {key} 数值必须有限且 max_delta 为正")
        if (
            raw["unknown_policy"] not in _UNKNOWN
            or not isinstance(raw["explanation"], str)
            or not raw["explanation"].strip()
        ):
            raise ValueError(f"行动 {key} 未知策略或解释无效")
        actions.append(
            ActionCard(
                id=key,
                domain=raw["domain"],
                consumer=raw["consumer"],
                improves=_names(raw["improves"], f"{key}.improves"),
                consumes=_names(raw["consumes"], f"{key}.consumes"),
                requires_all=_names(raw["requires_all"], f"{key}.requires_all"),
                requires_any=_names(raw["requires_any"], f"{key}.requires_any"),
                blocked_by=_names(raw["blocked_by"], f"{key}.blocked_by"),
                complements=_names(raw["complements"], f"{key}.complements"),
                substitutes=_names(raw["substitutes"], f"{key}.substitutes"),
                conflicts=_names(raw["conflicts"], f"{key}.conflicts"),
                enables=_names(raw["enables"], f"{key}.enables"),
                exit_when=_names(raw["exit_when"], f"{key}.exit_when"),
                base=float(raw["base"]),
                stress=float(raw["stress"]),
                opportunity=float(raw["opportunity"]),
                commitment=float(raw["commitment"]),
                political_cost=float(raw["political_cost"]),
                max_delta=float(raw["max_delta"]),
                unknown_policy=raw["unknown_policy"],
                explanation=raw["explanation"],
            )
        )
    consumer_ids = {item.id for item in consumers}
    action_ids = {item.id for item in actions}
    if len(action_ids) != len(actions) or len(consumer_ids) != len(consumers):
        raise ValueError("行动或消费者 ID 重复")
    for action in actions:
        if action.consumer not in consumer_ids:
            raise ValueError(f"行动 {action.id} 引用了未知消费者：{action.consumer}")
        for relation in (
            *action.complements,
            *action.substitutes,
            *action.conflicts,
            *action.enables,
        ):
            if relation not in action_ids:
                raise ValueError(f"行动 {action.id} 引用了未知关系目标：{relation}")
        if action.max_delta > next(
            item.max_delta for item in consumers if item.id == action.consumer
        ):
            raise ValueError(f"行动 {action.id} 超出消费者影响预算")
    return tuple(consumers), tuple(actions)
