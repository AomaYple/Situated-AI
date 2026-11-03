"""原版支持作用域内的有限防御候选；无持久状态或全世界扫描。

来源是锁定默认策略的 treaty、相邻和战争目标用例。静态同形用例不证明
当前组合在引擎中已生效；完整实验包集中实测，正式开关保持关闭。
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from .situated.support_program import SupportProgram

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
    """兼容入口：只启用共享连续程序中的防御原因组。"""
    return SupportProgram.from_extensions(replace(policy, market_enabled=False)).render()
