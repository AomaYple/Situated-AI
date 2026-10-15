"""外交响应与战后回调的独立诊断；身份、覆盖和对象读数尚非实机契约。"""

from __future__ import annotations

import re
from typing import NotRequired, TypedDict

HOOKS = ("join_side", "abandon_side", "war_start")
_MARKER = "SITAI RESPONSE ROOT;"
_ROW = re.compile(
    r"SITAI RESPONSE ROOT;(?P<hook>[a-z_]+);(?P<saved_scope>missing|same|different);"
    r"(?P<actor_id>missing|[0-9]+);(?P<escalation>[0-9]+);(?P<date_text>[^;\[\]]+)$"
)
_ROW2 = re.compile(
    r"SITAI RESPONSE ROOT2;(?P<hook>[a-z_]+);(?P<saved_scope>missing|same|different);"
    r"(?P<persistent_scope>unbound|unavailable|same|different);"
    r"(?P<actor_tag>missing|unmatched|[A-Z]{3});(?P<escalation>[0-9]+);"
    r"(?P<date_text>[^;\[\]]+)$"
)
_OUTCOME_MARKER = "SITAI WAR OUTCOME;"
_OUTCOME_ROW = re.compile(
    r"SITAI WAR OUTCOME;(?P<hook>won|lost);(?P<tag>[A-Z]{3});"
    r"(?P<war_scope>present|missing);"
    r"(?P<play_reference>missing|unbound|unavailable|same|different);"
    r"(?P<benefitted_from_wargoal>yes|no);(?P<victim_of_wargoal>yes|no);"
    r"(?P<date_text>[^;\[\]]+)$"
)
REFERENCE = "sitai_response_reference"
REFERENCE_DAYS = 190


class RootEvent(TypedDict):
    hook: str
    saved_scope: str
    actor_id: str | None
    escalation: int
    date_text: str
    protocol_version: NotRequired[int]
    persistent_scope: NotRequired[str]
    actor_state: NotRequired[str]
    actor_tag: NotRequired[str | None]


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


class WarOutcome(TypedDict):
    hook: str
    tag: str
    war_scope: str
    play_reference: str
    benefitted_from_wargoal: bool
    victim_of_wargoal: bool
    date_text: str


class WarDiagnostics(TypedDict):
    status: str
    events: list[WarOutcome]
    count: int
    scope: str
    time_basis: str
    opportunity_identity_verified: bool
    country_coverage_verified: bool
    absence_proves_no_harm: bool
    quality_improvement_proven: bool


def configuration(
    tags: tuple[str, ...] = ("AUS", "SAR", "RUS", "PRU"),
    *,
    observers: tuple[str, str] = ("RUS", "PRU"),
) -> dict[str, object]:
    """让冻结来源记录观测范围，而不是只有一个启用布尔值。"""
    return {
        "version": 2,
        "identity": "persistent-reference-unvalidated",
        "reference_days": REFERENCE_DAYS,
        "actor": "declared-country-equality-unvalidated",
        "actor_tags": list(tags),
        "unbound_root": True,
        "war_outcomes": {
            "version": 1,
            "hooks": ["on_won_war", "on_lost_war"],
            "observer_tags": list(observers),
            "identity": "persistent-play-reference-unvalidated",
            "country_coverage_verified": False,
            "quantitative_cost_supported": False,
        },
    }


def binding() -> str:
    """只由唯一 BIND 写入；seen 比引用多活一天，缺引用不能猜成已过期。"""
    return (
        f"set_global_variable = {{ name = {REFERENCE} "
        f"value = scope:sitai_opportunity days = {REFERENCE_DAYS} }}\n"
        f"set_global_variable = {{ name = {REFERENCE}_seen value = 1 "
        f"days = {REFERENCE_DAYS + 1} }}\n"
    )


def _actor(hook: str, state: str, reference: str, tags: tuple[str, ...]) -> str:
    prefix = f"SITAI RESPONSE ROOT2;{hook};{state};{reference};"
    suffix = ";[THIS.GetEscalation];__SITAI_RESPONSE_DATE__"
    cases = []
    for index, tag in enumerate(tags):
        keyword = "if" if index == 0 else "else_if"
        cases.append(
            f"{keyword} = {{ limit = {{ exists = c:{tag} "
            f"c:{tag} ?= {{ this = scope:actor }} }} "
            f'debug_log = "{prefix}{tag}{suffix}" }}'
        )
    return (
        "if = { limit = { exists = scope:actor } "
        + " ".join(cases)
        + f' else = {{ debug_log = "{prefix}unmatched{suffix}" }} }} '
        f'else = {{ debug_log = "{prefix}missing{suffix}" }}'
    )


def _diagnostic(hook: str, state: str, tags: tuple[str, ...]) -> str:
    return (
        f"if = {{ limit = {{ exists = global_var:{REFERENCE} }} "
        f"if = {{ limit = {{ this = global_var:{REFERENCE} }} "
        f"{_actor(hook, state, 'same', tags)} }} "
        f"else = {{ {_actor(hook, state, 'different', tags)} }} }} "
        f"else = {{ if = {{ limit = {{ has_global_variable = {REFERENCE}_seen }} "
        f"{_actor(hook, state, 'unavailable', tags)} }} "
        f"else = {{ {_actor(hook, state, 'unbound', tags)} }} }}"
    )


def _outcome_flags(prefix: str) -> str:
    cases = []
    for benefit in ("yes", "no"):
        keyword = "if" if benefit == "yes" else "else"
        limit = "limit = { exists = scope:benefitted_from_wargoal } " if benefit == "yes" else ""
        cases.append(
            f"{keyword} = {{ {limit}"
            "if = { limit = { exists = scope:victim_of_wargoal } "
            f'debug_log = "{prefix};{benefit};yes;__SITAI_RESPONSE_DATE__" }} '
            f'else = {{ debug_log = "{prefix};{benefit};no;__SITAI_RESPONSE_DATE__" }} }}'
        )
    return " ".join(cases)


def _outcome_reference(prefix: str) -> str:
    return (
        "if = { limit = { exists = scope:diplomatic_play } "
        f"if = {{ limit = {{ exists = global_var:{REFERENCE} }} "
        f"if = {{ limit = {{ scope:diplomatic_play ?= {{ this = global_var:{REFERENCE} }} }} "
        f"{_outcome_flags(prefix + ';same')} }} "
        f"else = {{ {_outcome_flags(prefix + ';different')} }} }} "
        f"else = {{ if = {{ limit = {{ has_global_variable = {REFERENCE}_seen }} "
        f"{_outcome_flags(prefix + ';unavailable')} }} "
        f"else = {{ {_outcome_flags(prefix + ';unbound')} }} }} }} "
        f"else = {{ {_outcome_flags(prefix + ';missing')} }}"
    )


def _outcome_hooks(observers: tuple[str, str]) -> str:
    """只读两个声明国家的 Country 根回调；不推断第三方覆盖或对象存续。"""
    actions = []
    for hook in ("won", "lost"):
        action = f"zz_sitai_outcome_{hook}"
        countries = []
        for tag in observers:
            prefix = f"{_OUTCOME_MARKER}{hook};{tag}"
            countries.append(
                f"if = {{ limit = {{ exists = c:{tag} this = c:{tag} }} "
                "if = { limit = { exists = scope:war } "
                f"{_outcome_reference(prefix + ';present')} }} "
                f"else = {{ {_outcome_reference(prefix + ';missing')} }} }}"
            )
        actions.append(
            f"on_{hook}_war = {{ on_actions = {{ {action} }} }}\n"
            f"{action} = {{ effect = {{ {' '.join(countries)} }} }}"
        )
    return "\n".join(actions) + "\n"


def build_hooks(tags: tuple[str, ...], *, observers: tuple[str, str] = ("RUS", "PRU")) -> str:
    """每条根事件只命中一个存在性分支，输出诊断并保留原绑定记录。"""
    actions = []
    for hook in HOOKS:
        action = f"zz_sitai_response_{hook}"
        body = (
            f"{action} = {{ effect = {{ "
            "if = { limit = { exists = scope:sitai_opportunity } "
            "if = { limit = { this = scope:sitai_opportunity } "
            f"{_diagnostic(hook, 'same', tags)} "
            f'debug_log = "SITAI RESPONSE;{hook};[THIS.GetEscalation];__SITAI_RESPONSE_DATE__" '
            f"}} else = {{ {_diagnostic(hook, 'different', tags)} }} "
            f"}} else = {{ {_diagnostic(hook, 'missing', tags)} }} "
            "} }"
        )
        actions.append(f"on_diplo_play_{hook} = {{ on_actions = {{ {action} }} }}\n{body}")
    return "\n".join(actions) + "\n" + _outcome_hooks(observers)


def parse_outcome(line: str, *, observers: tuple[str, str]) -> WarOutcome | None:
    """结果协议只接受声明的观察国；日期保留文本，不关联到机会或日采样。"""
    if _OUTCOME_MARKER not in line:
        return None
    match = _OUTCOME_ROW.search(line.rstrip())
    if match is None or not match["date_text"].strip():
        raise ValueError("战后结果诊断行格式或存在性状态不完整")
    if match["tag"] not in observers:
        raise ValueError("战后结果诊断返回未声明的观察国")
    return {
        "hook": match["hook"],
        "tag": match["tag"],
        "war_scope": match["war_scope"],
        "play_reference": match["play_reference"],
        "benefitted_from_wargoal": match["benefitted_from_wargoal"] == "yes",
        "victim_of_wargoal": match["victim_of_wargoal"] == "yes",
        "date_text": match["date_text"],
    }


def summarize_outcomes(events: list[WarOutcome]) -> WarDiagnostics:
    """保留回调顺序和重复；输赢与战目标标志都不是逐国净成本或质量指标。"""
    return {
        "status": "country_callbacks_observed" if events else "no_country_callbacks_observed",
        "events": events,
        "count": len(events),
        "scope": "declared_observer_countries_all_wars",
        "time_basis": "未校准的引擎日期文本，不是共享日采样序号或响应时延",
        "opportunity_identity_verified": False,
        "country_coverage_verified": False,
        "absence_proves_no_harm": False,
        "quality_improvement_proven": False,
    }


def parse_line(line: str) -> RootEvent | None:
    """坏诊断即使与正常机会行混合也拒绝；不猜未展开读数。"""
    version2 = "SITAI RESPONSE ROOT2;" in line
    if _MARKER not in line and not version2:
        return None
    match = (_ROW2 if version2 else _ROW).search(line.rstrip())
    if match is None:
        raise ValueError("根钩子诊断行格式、身份或 getter 读数不完整")
    values = match.groupdict()
    if values["hook"] not in HOOKS or not 0 <= int(values["escalation"]) <= 100:
        raise ValueError("根钩子诊断包含未知钩子或越界升级值")
    result: RootEvent = {
        "hook": values["hook"],
        "saved_scope": values["saved_scope"],
        "actor_id": None if version2 or values["actor_id"] == "missing" else values["actor_id"],
        "escalation": int(values["escalation"]),
        "date_text": values["date_text"],
    }
    if version2:
        actor = values["actor_tag"]
        result["protocol_version"] = 2
        result["persistent_scope"] = values["persistent_scope"]
        result["actor_state"] = actor if actor in {"missing", "unmatched"} else "matched"
        result["actor_tag"] = None if actor in {"missing", "unmatched"} else actor
    return result


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
