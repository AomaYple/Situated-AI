"""外交目标与战争负担模块。"""

from __future__ import annotations

import hashlib
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path

SOURCE = Path(__file__).parents[2] / "mod" / "decisions" / "diplomatic_goals.toml"


@dataclass(frozen=True, slots=True)
class DiplomacyPolicy:
    enabled: bool = False
    war_burden_penalty: float = -0.5
    peaceful_opportunity_bonus: float = 0.15
    source_sha256: str = ""


def load(source: Path = SOURCE) -> DiplomacyPolicy:
    raw = source.read_bytes()
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"外交模块数据源无效：{source}") from exc
    if set(data) != {"schema_version", "diplomacy"} or data.get("schema_version") != 1:
        raise ValueError("外交模块 schema 无效")
    values = data["diplomacy"]
    expected = {"enabled", "war_burden_penalty", "peaceful_opportunity_bonus", "why"}
    if not isinstance(values, dict) or set(values) != expected:
        raise ValueError("外交模块含缺失或未知字段")
    if (
        type(values["enabled"]) is not bool
        or not isinstance(values["why"], str)
        or not values["why"].strip()
    ):
        raise ValueError("外交模块开关和依据无效")
    numbers = (values["war_burden_penalty"], values["peaceful_opportunity_bonus"])
    if any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
        for v in numbers
    ):
        raise ValueError("外交模块参数必须是有限数值")
    if (
        not -1 <= values["war_burden_penalty"] <= 0
        or not 0 <= values["peaceful_opportunity_bonus"] <= 1
    ):
        raise ValueError("外交模块参数超出保守范围")
    return DiplomacyPolicy(
        values["enabled"],
        float(values["war_burden_penalty"]),
        float(values["peaceful_opportunity_bonus"]),
        hashlib.sha256(raw).hexdigest(),
    )


def recklessness_delta(
    *, in_war: bool | None, taking_loans: bool | None, policy: DiplomacyPolicy
) -> float:
    """战争或借款时降低冒险程度；未知输入不猜测。"""

    if not policy.enabled or in_war is None or taking_loans is None:
        return 0.0
    if not isinstance(in_war, bool) or not isinstance(taking_loans, bool):
        raise ValueError("外交输入必须是布尔值")
    return (
        policy.war_burden_penalty if in_war or taking_loans else policy.peaceful_opportunity_bonus
    )


def triggers(policy: DiplomacyPolicy | None = None) -> str:
    policy = policy or load()
    if not policy.enabled:
        return ""
    return """# 由 pdx.decision_diplomacy 生成；不创建外交机会、不强制宣战。
sitai_diplomatic_war_burden = {
    is_ai = yes
    OR = { is_at_war = yes taking_loans = yes in_default = yes }
}
sitai_diplomatic_capacity = {
    is_ai = yes
    is_at_war = no
    in_default = no
    taking_loans = no
}
"""


def strategy_addition(policy: DiplomacyPolicy | None = None) -> str:
    policy = policy or load()
    if not policy.enabled:
        return ""
    return f"""\t\t# SITAI DIPLOMACY BEGIN
\t\tif = {{ limit = {{ sitai_diplomatic_war_burden = yes }} add = {policy.war_burden_penalty:g} }}
\t\tif = {{ limit = {{ sitai_diplomatic_capacity = yes }} add = {policy.peaceful_opportunity_bonus:g} }}
\t\t# SITAI DIPLOMACY END
"""
