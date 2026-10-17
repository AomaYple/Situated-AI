"""经济与行政能力模块的纯函数和原版策略补丁。

本模块只使用原版默认策略已经消费的字段：
``economic_vs_government_spending_balance``。它把可观察的借款和行政能力
作为有限的倾向修正，不创建免费的资源、建筑或外部规划器。运行期未知值由
游戏脚本的条件自然保持为不干预；Python 参考函数同样把未知输入返回为零。
"""

from __future__ import annotations

import hashlib
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path

SOURCE = Path(__file__).parents[2] / "mod" / "decisions" / "economy.toml"


@dataclass(frozen=True, slots=True)
class EconomyPolicy:
    enabled: bool = False
    bureaucracy_floor: float = 0.0
    debt_penalty: float = -0.25
    capacity_bonus: float = 0.10
    source_sha256: str = ""


def load(source: Path = SOURCE) -> EconomyPolicy:
    raw = source.read_bytes()
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"经济模块数据源无效：{source}") from exc
    if set(data) != {"schema_version", "economy"} or data.get("schema_version") != 1:
        raise ValueError("经济模块 schema 无效")
    values = data["economy"]
    expected = {"enabled", "bureaucracy_floor", "debt_penalty", "capacity_bonus", "why"}
    if not isinstance(values, dict) or set(values) != expected:
        raise ValueError("经济模块含缺失或未知字段")
    if (
        type(values["enabled"]) is not bool
        or not isinstance(values["why"], str)
        or not values["why"].strip()
    ):
        raise ValueError("经济模块开关和依据无效")
    numbers = (
        values["bureaucracy_floor"],
        values["debt_penalty"],
        values["capacity_bonus"],
    )
    if any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
        for v in numbers
    ):
        raise ValueError("经济模块参数必须是有限数值")
    if (
        not -100 <= values["bureaucracy_floor"] <= 100
        or not -1 <= values["debt_penalty"] <= 0
        or not 0 <= values["capacity_bonus"] <= 1
    ):
        raise ValueError("经济模块参数超出保守范围")
    return EconomyPolicy(
        values["enabled"],
        float(values["bureaucracy_floor"]),
        float(values["debt_penalty"]),
        float(values["capacity_bonus"]),
        hashlib.sha256(raw).hexdigest(),
    )


def strategy_delta(
    *,
    taking_loans: bool | None,
    bureaucracy: float | None,
    policy: EconomyPolicy,
) -> float:
    """返回经济支出平衡的有限参考增量；缺失输入保守地不干预。"""

    if not policy.enabled or taking_loans is None or bureaucracy is None:
        return 0.0
    if not isinstance(taking_loans, bool) or not math.isfinite(bureaucracy):
        raise ValueError("经济输入必须是布尔值和有限数值")
    if taking_loans or bureaucracy < policy.bureaucracy_floor:
        return policy.debt_penalty
    return policy.capacity_bonus


def triggers(policy: EconomyPolicy | None = None) -> str:
    policy = policy or load()
    if not policy.enabled:
        return ""
    return f"""# 由 pdx.decision_economy 生成；只读取原版财政和行政事实。
sitai_economy_constraint = {{
    is_ai = yes
    OR = {{ taking_loans = yes bureaucracy < {policy.bureaucracy_floor:g} }}
}}
sitai_economy_capacity = {{
    is_ai = yes
    taking_loans = no
    bureaucracy >= {policy.bureaucracy_floor:g}
}}
"""


def strategy_addition(policy: EconomyPolicy | None = None) -> str:
    policy = policy or load()
    if not policy.enabled:
        return ""
    return f"""\t\t# SITAI ECONOMY BEGIN
\t\tif = {{ limit = {{ ROOT ?= {{ is_ai = yes }} sitai_economy_constraint = yes }} add = {policy.debt_penalty:g} }}
\t\tif = {{ limit = {{ ROOT ?= {{ is_ai = yes }} sitai_economy_capacity = yes }} add = {policy.capacity_bonus:g} }}
\t\t# SITAI ECONOMY END
"""
