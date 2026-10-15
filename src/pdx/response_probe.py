"""外交根钩子的独立诊断协议；局部身份与 actor 读数尚非实机契约。"""

from __future__ import annotations

import re
from typing import TypedDict

HOOKS = ("join_side", "abandon_side", "war_start")
_MARKER = "SITAI RESPONSE ROOT;"
_ROW = re.compile(
    r"SITAI RESPONSE ROOT;(?P<hook>[a-z_]+);(?P<saved_scope>missing|same|different);"
    r"(?P<actor_id>missing|[0-9]+);(?P<escalation>[0-9]+);(?P<date_text>[^;\[\]]+)$"
)


class RootEvent(TypedDict):
    hook: str
    saved_scope: str
    actor_id: str | None
    escalation: int
    date_text: str


class Diagnostics(TypedDict):
    status: str
    events: list[RootEvent]
    count: int
    scope: str
    time_basis: str
    opportunity_identity_verified: bool
    actor_scope_supported: bool
    absence_proves_no_response: bool
    quality_improvement_proven: bool


def configuration() -> dict[str, object]:
    """让冻结来源记录观测范围，而不是只有一个启用布尔值。"""
    return {
        "version": 1,
        "identity": "chain-local-diagnostic",
        "actor": "guarded-id-unvalidated",
        "unbound_root": True,
    }


def _diagnostic(hook: str, state: str) -> str:
    prefix = f"{_MARKER}{hook};{state};"
    suffix = ";[THIS.GetEscalation];__SITAI_RESPONSE_DATE__"
    return (
        "if = { limit = { exists = scope:actor } "
        f'''debug_log = "{prefix}[SCOPE.sCountry('actor').GetIDString]{suffix}" }} '''
        f'else = {{ debug_log = "{prefix}missing{suffix}" }}'
    )


def build_hooks() -> str:
    """每条根事件只命中一个存在性分支，输出诊断并保留原绑定记录。"""
    actions = []
    for hook in HOOKS:
        action = f"zz_sitai_response_{hook}"
        body = (
            f"{action} = {{ effect = {{ "
            "if = { limit = { exists = scope:sitai_opportunity } "
            "if = { limit = { this = scope:sitai_opportunity } "
            f"{_diagnostic(hook, 'same')} "
            f'debug_log = "SITAI RESPONSE;{hook};[THIS.GetEscalation];__SITAI_RESPONSE_DATE__" '
            f"}} else = {{ {_diagnostic(hook, 'different')} }} "
            f"}} else = {{ {_diagnostic(hook, 'missing')} }} "
            "} }"
        )
        actions.append(f"on_diplo_play_{hook} = {{ on_actions = {{ {action} }} }}\n{body}")
    return "\n".join(actions) + "\n"


def parse_line(line: str) -> RootEvent | None:
    """坏诊断即使与正常机会行混合也拒绝；不猜未展开读数。"""
    if _MARKER not in line:
        return None
    match = _ROW.search(line.rstrip())
    if match is None:
        raise ValueError("根钩子诊断行格式、身份或 getter 读数不完整")
    values = match.groupdict()
    if values["hook"] not in HOOKS or not 0 <= int(values["escalation"]) <= 100:
        raise ValueError("根钩子诊断包含未知钩子或越界升级值")
    if not values["date_text"].strip():
        raise ValueError("根钩子诊断缺少时间文本")
    return {
        "hook": values["hook"],
        "saved_scope": values["saved_scope"],
        "actor_id": None if values["actor_id"] == "missing" else values["actor_id"],
        "escalation": int(values["escalation"]),
        "date_text": values["date_text"],
    }


def summarize(events: list[RootEvent]) -> Diagnostics:
    """同一份流保留顺序和重复事件；不按日期猜测事件或机会身份。"""
    return {
        "status": "root_events_observed" if events else "no_root_events_observed",
        "events": events,
        "count": len(events),
        "scope": "all_diplomatic_plays",
        "time_basis": "未校准的引擎日期文本，不是共享日采样序号或响应时延",
        "opportunity_identity_verified": False,
        "actor_scope_supported": False,
        "absence_proves_no_response": False,
        "quality_improvement_proven": False,
    }
