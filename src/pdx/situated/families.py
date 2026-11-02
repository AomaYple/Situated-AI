"""把生产规则映射到稳定的细分行动族。

规则的原始 ``domain`` 只有九个粗域；行动内核需要更细的审计维度，但不应在
第二份 TOML 里复制业务条件。本模块只根据已存在的来源路径和消费者字段进行
确定性分类，无法安全细分时保留粗域，且把分类方法写入合同。
"""

from __future__ import annotations

import re
import tomllib
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

FAMILIES: Final[tuple[str, ...]] = (
    "fiscal",
    "administrative",
    "industry",
    "resources",
    "market",
    "research",
    "education",
    "political",
    "population",
    "social",
    "identity",
    "diplomacy",
    "subjects",
    "army",
    "war",
    "navy",
    "overseas",
    "geography",
    "temporal",
)

_RESOURCE_WORDS = (
    "mine",
    "farm",
    "plantation",
    "logging",
    "fishing",
    "whaling",
    "gold",
    "oil",
    "rubber",
    "sulfur",
    "lead",
    "coal",
    "iron",
)


def classify(*, domain: str, field: str, source: str = "") -> str:
    """返回一个稳定的细分行动族，不读取国家名称或历史标签。"""

    lowered = f"{source}/{field}".casefold()
    # Lifecycle keys are identifiers, not arbitrary letter sequences inside
    # battle, bottle or resettlement. Keep their explicit source/key tokens.
    tokens = set(re.split(r"[^a-z0-9]+", lowered))
    if tokens & {"temporal", "cooldown", "ttl"}:
        return "temporal"
    if domain == "fiscal":
        return "fiscal"
    if domain == "subjects":
        return "subjects"
    if domain == "geography":
        return "geography"
    if domain == "identity":
        return "identity"
    if domain == "diplomacy":
        if any(word in lowered for word in ("colon", "overseas", "strategic_region")):
            return "overseas"
        return "diplomacy"
    if domain == "military":
        field_parts = field.casefold().split(".")
        field_tokens = set(re.split(r"[^a-z0-9]+", field.casefold()))
        if (
            any(word in lowered for word in ("navy", "ship", "admiralty", "sea_lane", "dockyard"))
            or field_tokens & {"fleet", "battlefleet", "naval", "marine", "marines", "submarine"}
            or "fleet_compositions" in field_parts
            or "protect_supply" in field_parts
        ):
            return "navy"
        if any(word in lowered for word in ("war", "wargoal", "battle", "combat", "mobil")):
            return "war"
        return "army"
    if domain == "political":
        if source.casefold() == "common/laws/01_colonial_affairs.txt":
            return "overseas"
        if any(
            word in lowered
            for word in ("school", "education", "academia", "literacy", "university")
        ):
            return "education"
        if any(word in lowered for word in ("population", "migration", "birth", "mortality")):
            return "population"
        if any(word in lowered for word in ("health", "welfare", "workplace", "rights", "social")):
            return "social"
        return "political"
    if domain == "market":
        return "market"
    if domain == "economy":
        if any(word in lowered for word in ("research", "technology", "tech", "innovation")):
            return "research"
        if any(word in lowered for word in _RESOURCE_WORDS):
            return "resources"
        if any(word in lowered for word in ("bureaucr", "government", "institution")):
            return "administrative"
        return "industry"
    return domain if domain in FAMILIES else "social"


def load_contract(path: Path) -> dict[str, dict[str, str]]:
    """读取行动族的唯一描述来源并做严格结构校验。"""

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or not isinstance(data.get("families"), dict):
        raise ValueError("行动族合同 schema 无效")
    values = data["families"]
    if set(values) != set(FAMILIES):
        raise ValueError("行动族合同必须覆盖全部 19 个族")
    result: dict[str, dict[str, str]] = {}
    for key, value in values.items():
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("domain"), str)
            or not isinstance(value.get("description"), str)
        ):
            raise ValueError(f"行动族合同字段无效：{key}")
        result[key] = {"domain": value["domain"], "description": value["description"]}
    return result


__all__ = ["FAMILIES", "classify", "load_contract"]
