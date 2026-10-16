"""原版支持作用域内的有限防御候选；无持久状态或全世界扫描。

来源是锁定默认策略的 treaty、相邻和战争目标用例。静态同形用例不证明
当前组合在引擎中已生效；完整实验包集中实测，正式开关保持关闭。
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .decisions import Extensions


def triggers() -> str:
    """参数在调用点显式传入，不依赖跨事件 saved scope。"""
    return """# 由 pdx.decisions 生成；防御候选，无强制行动。
sitai_defense_commitment = {
    any_scope_treaty = {
        binds = $PARTNER$
        any_scope_article = {
            OR = { has_type = alliance has_type = defensive_pact }
        }
    }
}
sitai_neighbor_defense = {
    is_adjacent_to_country = $PARTNER$
    $OPPONENT$ = {
        OR = {
            play_participant_has_war_goal_of_type_against = {
                type = conquer_state
                target = $PARTNER$
            }
            play_participant_has_war_goal_of_type_against = {
                type = make_protectorate
                target = $PARTNER$
            }
        }
    }
}
"""


def support_addition(policy: Extensions) -> str:
    """支持防御方取最大理由，评价进攻方时反向；不叠加同一风险。"""
    amounts = (policy.security_commitment_bonus, policy.security_threat_bonus)
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 <= value <= 50
        or not math.isfinite(value)
        for value in amounts
    ):
        raise ValueError("外部防御权重必须是 0 到 50 的有限数值")
    if not policy.security_enabled or not any(amounts):
        return ""

    def side(partner: str, opponent: str, sign: int) -> str:
        reasons = [
            (amounts[0], f"sitai_defense_commitment = {{ PARTNER = {partner} }}", "COMMITMENT"),
            (
                amounts[1],
                f"sitai_neighbor_defense = {{ PARTNER = {partner} OPPONENT = {opponent} }}",
                "NEIGHBOR",
            ),
        ]
        result: list[str] = []
        for amount, condition, reason in sorted(reasons, key=lambda row: -row[0]):
            if amount == 0:
                continue
            branch = "if" if not result else "else_if"
            result.append(
                f"        {branch} = {{\n"
                f"            limit = {{ ROOT ?= {{ {condition} }} }}\n"
                f"            add = {{ value = {sign * amount:g} desc = SITAI_SECURITY_{reason}_REASON }}\n"
                "        }\n"
            )
        return "".join(result)

    return (
        "\t\t# SITAI SECURITY：防御方贡献为正，评价进攻方时反向。\n"
        "\t\tif = {\n"
        "            limit = { ROOT ?= { is_ai = yes } exists = scope:country\n"
        "                exists = scope:enemy_country exists = scope:diplomatic_play_type }\n"
        "            if = {\n"
        "                limit = { NOT = { exists = scope:is_initiator } }\n"
        + side("scope:country", "scope:enemy_country", 1)
        + "            }\n"
        "            else = {\n"
        + side("scope:enemy_country", "scope:country", -1)
        + "            }\n"
        "\t\t}\n"
    )
