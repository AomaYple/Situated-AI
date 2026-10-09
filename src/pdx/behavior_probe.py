"""固定存档中的第三方外交机会仪器；创建机会与AI选择分别记录。"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, NotRequired, TypedDict

from . import decision_probe, decisions, game_auto

if TYPE_CHECKING:
    from pathlib import Path

ROW = re.compile(
    r"SITAI OPPORTUNITY;(?P<tag>[A-Z]{3}|CONTROL);(?P<kind>[A-Z_]+);(?P<value>.*);(?P<date>[^;]*)$"
)
BOOLEAN_KINDS = frozenset(
    {
        "UNDECIDED",
        "CAN_INIT",
        "CAN_TARGET",
        "BACKER",
        "INIT_BACKER",
        "TARGET_BACKER",
        "ACTIVE",
        "ENTRY",
        "HOLD",
        "TASK",
        "FLAG",
        "PRESENT",
    }
)
SAMPLE_VAR = "sitai_probe_opportunity_sample"


class CountryEvidence(TypedDict):
    independent_opportunities: int
    joined: int
    observations: int
    absence_is_neutrality: bool
    eligible_active_days: int


class Analysis(TypedDict):
    rows: list[dict[str, str]]
    countries: dict[str, CountryEvidence]
    forced_creation_is_autonomous: bool
    sampling: str
    behavior_causality: bool
    common_eligible_active_dates: list[str]
    usable_for_paired_behavior: bool
    time_basis: str
    natural_capture: NotRequired[dict[str, object]]


def build(
    *,
    initiator: str = "AUS",
    target: str = "SAR",
    tags: tuple[str, str] = ("RUS", "PRU"),
    market_readings: bool = False,
    natural: bool = False,
    play_types: tuple[str, ...] = (),
) -> dict[str, str]:
    if (
        any(not re.fullmatch(r"[A-Z]{3}", tag) for tag in (initiator, target))
        or initiator == target
        or {initiator, target} & set(tags)
        or len(tags) != 2
        or tags[0] == tags[1]
        or any(not re.fullmatch(r"[A-Z]{3}", tag) for tag in tags)
    ):
        raise ValueError("第三方机会必须由两个不同的三字母国家标签构成，且不能是观察国")
    if natural and (
        not play_types
        or len(set(play_types)) != len(play_types)
        or any(not re.fullmatch(r"dp_[a-z0-9_]+", key) for key in play_types)
        or market_readings
    ):
        raise ValueError("自然响应只读仪器需要规范全量类型，不能同时开启市场实验")
    if play_types and not natural:
        raise ValueError("博弈类型全集仅用于自然响应仪器")
    roles = []
    for tag in tags:
        for kind, method in (
            ("UNDECIDED", "IsUndecidedParticipant"),
            ("CAN_INIT", "CanSupportInitiator"),
            ("CAN_TARGET", "CanSupportTarget"),
            ("BACKER", "IsBacker"),
            ("INIT_BACKER", "IsInitiatorBacker"),
            ("TARGET_BACKER", "IsTargetBacker"),
        ):
            expression = f"SCOPE.sDiplomaticPlay('sitai_opportunity').{method}(SCOPE.sCountry('sitai_{tag.lower()}').Self)"
            roles.append(
                f'''debug_log = "SITAI OPPORTUNITY;{tag};{kind};[Select_CString({expression}, 'yes', 'no')];[TimeKeeper.GetCurrentDate.GetString]"'''
            )
        roles.append(
            f"""c:{tag} ?= {{ if = {{ limit = {{ {decisions.ACTIVE_TRIGGER} = yes }} debug_log = "SITAI OPPORTUNITY;{tag};ACTIVE;yes;[TimeKeeper.GetCurrentDate.GetString]" }} else = {{ debug_log = "SITAI OPPORTUNITY;{tag};ACTIVE;no;[TimeKeeper.GetCurrentDate.GetString]" }} }}"""
        )
        if natural:
            roles.append(
                f"""if = {{ limit = {{ exists = c:{tag} }} debug_log = "SITAI OPPORTUNITY;{tag};PRESENT;yes;[TimeKeeper.GetCurrentDate.GetString]" }} else = {{ debug_log = "SITAI OPPORTUNITY;{tag};PRESENT;no;[TimeKeeper.GetCurrentDate.GetString]" }}"""
            )
            for kind, condition in (
                ("ENTRY", "sitai_fiscal_entry = yes"),
                ("HOLD", "sitai_fiscal_hold = yes"),
                ("TASK", "is_involved_in_journal_entry = je_peru_bolivia"),
                ("FLAG", "has_variable = attack_bolivia"),
            ):
                roles.append(
                    f"""c:{tag} ?= {{ if = {{ limit = {{ {condition} }} debug_log = "SITAI OPPORTUNITY;{tag};{kind};yes;[TimeKeeper.GetCurrentDate.GetString]" }} else = {{ debug_log = "SITAI OPPORTUNITY;{tag};{kind};no;[TimeKeeper.GetCurrentDate.GetString]" }} }}"""
                )
        score_lines = []
        for kind, method in (
            ("INIT_SCORE", "GetInitiatorPreferenceScore"),
            ("TARGET_SCORE", "GetTargetPreferenceScore"),
        ):
            expression = f"SCOPE.sDiplomaticPlay('sitai_opportunity').{method}(SCOPE.sCountry('sitai_{tag.lower()}').Self)"
            score_lines.append(
                f'''debug_log = "SITAI OPPORTUNITY;{tag};{kind};[{expression}|{"3" if market_readings else "0"}];[TimeKeeper.GetCurrentDate.GetString]"'''
            )
        if market_readings:
            roles.append(f"""c:{tag} ?= {{
                set_variable = {{ name = sitai_probe_dependency_init value = "scope:sitai_{tag.lower()}.economic_dependence(scope:sitai_init)" days = 1 }}
                set_variable = {{ name = sitai_probe_dependency_target value = "scope:sitai_{tag.lower()}.economic_dependence(scope:sitai_target)" days = 1 }}
                if = {{ limit = {{ var:sitai_probe_dependency_init >= 0 var:sitai_probe_dependency_target >= 0 }}
                debug_log = "SITAI OPPORTUNITY;{tag};DEPENDENCY_INIT;[THIS.Var('sitai_probe_dependency_init').GetValue|3];[TimeKeeper.GetCurrentDate.GetString]"
                debug_log = "SITAI OPPORTUNITY;{tag};DEPENDENCY_TARGET;[THIS.Var('sitai_probe_dependency_target').GetValue|3];[TimeKeeper.GetCurrentDate.GetString]"
                }} else = {{
                    debug_log = "SITAI OPPORTUNITY;{tag};DEPENDENCY_INIT;INVALID;[TimeKeeper.GetCurrentDate.GetString]"
                    debug_log = "SITAI OPPORTUNITY;{tag};DEPENDENCY_TARGET;INVALID;[TimeKeeper.GetCurrentDate.GetString]"
                }}
            }}""")
        detail_lines = []
        for kind, method in (
            ("INIT", "GetInitiatorPreferenceScoreDesc"),
            ("TARGET", "GetTargetPreferenceScoreDesc"),
        ):
            expression = f"SCOPE.sDiplomaticPlay('sitai_opportunity').{method}(SCOPE.sCountry('sitai_{tag.lower()}').Self)"
            detail_lines.append(
                f'''debug_log = "SITAI SCORE DETAIL;{tag};{kind};[{expression}];SITAI DETAIL END"'''
            )
        roles.append(
            f"""c:{tag} ?= {{
                if = {{ limit = {{ is_diplomatic_play_undecided_participant = yes }}
                    {" ".join(score_lines)}
                    if = {{ limit = {{ NOT = {{ has_variable = sitai_probe_score_detail }} }}
                        set_variable = {{ name = sitai_probe_score_detail value = 1 days = 7 }}
                        {" ".join(detail_lines)}
                    }}
                }}
            }}"""
        )
    script = """# 隔离机会仪器：不强制加入，不设置AI策略。
on_monthly_pulse_country = { on_actions = { zz_sitai_opportunity } }
zz_sitai_opportunity = { effect = {
    if = { limit = { c:AUS ?= this }
        if = { limit = { NOT = { has_variable = sitai_opportunity_created } exists = c:SAR }
            set_variable = { name = sitai_opportunity_created value = 1 }
            set_variable = { name = sitai_opportunity_watch value = 1 days = 370 }
            set_variable = { name = sitai_probe_opportunity_sample value = 0 }
            create_diplomatic_play = { name = sitai_opportunity_name target_country = c:SAR type = dp_humiliation }
            debug_log = "SITAI OPPORTUNITY;CONTROL;CREATE;AUS_SAR;[TimeKeeper.GetCurrentDate.GetString]"
            c:AUS ?= { save_scope_as = sitai_init }
            c:SAR ?= { save_scope_as = sitai_target }
            __SITAI_COUNTRY_SCOPES__
            every_diplomatic_play = {
                limit = { initiator_is = c:AUS target_is = c:SAR }
                save_scope_as = sitai_opportunity
            }
            # 已保存的scope随延迟事件传递；不能在读取GUI的同一事件内首次绑定。
            trigger_event = { id = zz_sitai_opportunity.1 days = 1 }
        }
    }
} }
"""
    watch = (
        """namespace = zz_sitai_opportunity
zz_sitai_opportunity.1 = {
    type = country_event
    hidden = yes
    immediate = {
        __SITAI_SAMPLE_STEP__
        if = { limit = { any_diplomatic_play = { initiator_is = c:AUS target_is = c:SAR } }
        scope:sitai_opportunity ?= {
            debug_log = "SITAI OPPORTUNITY;CONTROL;ESCALATION;[SCOPE.sDiplomaticPlay('sitai_opportunity').GetEscalation];[TimeKeeper.GetCurrentDate.GetString]"
"""
        "__SITAI_ROLE_READINGS__"
        """
        }
        if = { limit = { has_variable = sitai_opportunity_watch } trigger_event = { id = zz_sitai_opportunity.1 days = 1 } }
        }
        else = { debug_log = "SITAI OPPORTUNITY;CONTROL;END;AUS_SAR;[TimeKeeper.GetCurrentDate.GetString]" }
    }
}
"""
    )
    if natural:
        # ROOT 就是引擎创建的那场博弈；只捕获首场，延迟事件持有同一 scope，
        # 不通过国家对重新搜索另一场博弈，也不调用创建/加入/注入效果。
        script = """# 只绑定引擎自然创建的首场声明机会。
on_diplomatic_play_started = { on_actions = { zz_sitai_opportunity_bind } }
on_monthly_pulse_country = { on_actions = { zz_sitai_opportunity_ready } }
zz_sitai_opportunity_ready = { effect = {
    if = { limit = { c:AUS ?= this }
        debug_log = "SITAI OPPORTUNITY;CONTROL;READY;AUS_SAR;sample-0"
    }
} }
zz_sitai_opportunity_bind = { effect = {
    debug_log = "SITAI OPPORTUNITY;CONTROL;HOOK;natural;sample-0"
    if = { limit = { initiator_is = c:AUS target_is = c:SAR
            c:AUS = { NOT = { has_variable = sitai_opportunity_created } }
        }
        save_scope_as = sitai_opportunity
        c:AUS ?= { save_scope_as = sitai_init }
        c:SAR ?= { save_scope_as = sitai_target }
        __SITAI_COUNTRY_SCOPES__
        c:AUS ?= {
            set_variable = { name = sitai_opportunity_created value = 1 }
            set_variable = { name = sitai_opportunity_watch value = 1 days = 190 }
            set_variable = { name = sitai_probe_opportunity_sample value = 0 }
            debug_log = "SITAI OPPORTUNITY;CONTROL;BIND;AUS_SAR;sample-0"
            trigger_event = { id = zz_sitai_opportunity.1 days = 1 }
        }
    }
} }
"""
        script = script.replace(
            "initiator_is = c:AUS target_is = c:SAR",
            "initiator_is = c:AUS target_is = c:SAR __SITAI_OBSERVER_GUARDS__",
            1,
        )
        watch = watch.replace(
            "any_diplomatic_play = { initiator_is = c:AUS target_is = c:SAR }",
            "exists = scope:sitai_opportunity",
            1,
        )
        type_readings = "\n".join(
            f"""if = {{ limit = {{ is_diplomatic_play_type = {key} }} debug_log = "SITAI OPPORTUNITY;CONTROL;TYPE;{key};[TimeKeeper.GetCurrentDate.GetString]" }}"""
            for key in sorted(play_types)
        )
        watch = watch.replace(
            "__SITAI_ROLE_READINGS__", type_readings + "\n__SITAI_ROLE_READINGS__"
        )
    mapping = {"AUS": initiator, "SAR": target}
    script = re.sub(r"c:(AUS|SAR)\b", lambda m: f"c:{mapping[m[1]]}", script).replace(
        "AUS_SAR", f"{initiator}_{target}"
    )
    watch = re.sub(r"c:(AUS|SAR)\b", lambda m: f"c:{mapping[m[1]]}", watch).replace(
        "AUS_SAR", f"{initiator}_{target}"
    )
    watch = watch.replace("__SITAI_ROLE_READINGS__", "\n".join(roles))
    watch = watch.replace("__SITAI_SAMPLE_STEP__", decision_probe.sample_step(SAMPLE_VAR))
    watch = watch.replace(
        "[TimeKeeper.GetCurrentDate.GetString]",
        f"sample-[SCOPE.sCountry('sitai_init').MakeScope.Var('{SAMPLE_VAR}').GetValue|0]",
    )
    script = script.replace("[TimeKeeper.GetCurrentDate.GetString]", "sample-0")
    script = script.replace(
        "__SITAI_OBSERVER_GUARDS__", " ".join(f"exists = c:{tag}" for tag in tags)
    )
    script = script.replace(
        "__SITAI_COUNTRY_SCOPES__",
        "\n".join(f"c:{tag} ?= {{ save_scope_as = sitai_{tag.lower()} }}" for tag in tags),
    )
    if natural:
        for old, new in (
            (SAMPLE_VAR, "sitai_probe_natural_response_sample"),
            ("sitai_opportunity_created", "sitai_probe_natural_bound"),
            ("sitai_opportunity_watch", "sitai_probe_natural_watch"),
        ):
            script, watch = script.replace(old, new), watch.replace(old, new)
    files = {
        "common/on_actions/zz_sitai_opportunity.txt": script,
        "events/zz_sitai_opportunity.txt": watch,
        ".metadata/metadata.json": json.dumps(
            {
                "name": "SITAI natural third-party response observer"
                if natural
                else "SITAI third-party opportunity instrument",
                "id": "sitai.probe.opportunity",
                "version": "1.0",
                "supported_game_version": decisions.load().game_version,
                "short_description": "只绑定自然博弈并读取第三方响应，不创造机会"
                if natural
                else "受控机会与自主选边分开计数",
                "tags": [],
                "relationships": [],
                "game_custom_data": {"multiplayer_synchronized": False},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        "localization/english/zz_sitai_opportunity_l_english.yml": 'l_english:\n sitai_opportunity_name: "Third-party diplomacy experiment"\n',
        "localization/simp_chinese/zz_sitai_opportunity_l_simp_chinese.yml": 'l_simp_chinese:\n sitai_opportunity_name: "第三方外交机会实验"\n',
    }
    if natural:
        for name in tuple(files):
            if name.startswith("localization/"):
                del files[name]
    return files


def analyze(
    directory: Path,
    *,
    tags: tuple[str, str] = ("RUS", "PRU"),
    natural_pair: tuple[str, str] | None = None,
) -> Analysis:
    rows: list[dict[str, str]] = []
    for path in game_auto.rotated_logs(directory, "debug"):
        with path.open(encoding="utf-8-sig", errors="replace") as stream:
            for line in stream:
                match = ROW.search(line.rstrip())
                if natural_pair is not None and "SITAI OPPORTUNITY;" in line and match is None:
                    raise ValueError("自然响应仪器行格式不完整")
                if match:
                    row = match.groupdict()
                    if row["date"].startswith("sample-") and not re.fullmatch(
                        r"sample-\d+", row["date"]
                    ):
                        raise ValueError(f"外交采样序号未返回非负整数：{row}")
                    row["value"] = (
                        re.sub(r"\x15[^;\x15]*;", "", row["value"]).replace("\x15!", "").strip()
                    )
                    if row["kind"] in BOOLEAN_KINDS and row["value"] not in {"yes", "no"}:
                        raise ValueError(f"外交数据函数未返回可判布尔值：{row}")
                    if row["kind"] == "ESCALATION" and (
                        row["tag"] != "CONTROL"
                        or not re.fullmatch(r"\d+", row["value"])
                        or not 0 <= int(row["value"]) <= 100
                    ):
                        raise ValueError(f"外交阶段未返回0到100之间的整数：{row}")
                    if row["kind"] in {
                        "INIT_SCORE",
                        "TARGET_SCORE",
                        "DEPENDENCY_INIT",
                        "DEPENDENCY_TARGET",
                    } and not re.fullmatch(r"[+−-]?\d+(?:[.,]\d+)?", row["value"]):
                        raise ValueError(f"外交偏好分数未返回有限数值：{row}")
                    rows.append(row)
    if not rows:
        raise ValueError("缺少本局机会自报，不能把无记录当保持中立")
    countries: dict[str, CountryEvidence] = {}
    eligible_active: dict[str, set[str]] = {}
    for tag in tags:
        seen = [r for r in rows if r["tag"] == tag]
        eligible = any(
            r["kind"] in {"CAN_INIT", "CAN_TARGET"} and r["value"] == "yes" for r in seen
        )
        backed = any(r["kind"] == "BACKER" and r["value"] == "yes" for r in seen)
        daily: dict[str, set[str]] = {}
        for row in seen:
            if row["value"] == "yes":
                daily.setdefault(row["date"], set()).add(row["kind"])
        eligible_active[tag] = {
            date
            for date, kinds in daily.items()
            if {"UNDECIDED", "ACTIVE"} <= kinds and kinds & {"CAN_INIT", "CAN_TARGET"}
        }
        countries[tag] = {
            "independent_opportunities": int(eligible),
            "joined": int(backed),
            "observations": len(seen),
            "absence_is_neutrality": False,
            "eligible_active_days": len(eligible_active[tag]),
        }
    result: Analysis = {
        "rows": rows,
        "countries": countries,
        "forced_creation_is_autonomous": False,
        "sampling": "daily; changes within one day may be missed; one controlled country pair per run",
        "time_basis": "sample-N is a shared daily opportunity observation sequence, not a calendar date; actual window dates are runner ticks; historical date strings remain unchanged",
        "behavior_causality": False,
        "common_eligible_active_dates": sorted(eligible_active[tags[0]] & eligible_active[tags[1]]),
        "usable_for_paired_behavior": bool(eligible_active[tags[0]] & eligible_active[tags[1]]),
    }
    if natural_pair is not None:
        result["natural_capture"] = _natural_capture(rows, tags, natural_pair)
        result["sampling"] = (
            "daily after first natural START; exact saved play scope; at most one captured play per run"
        )
        # 绑定或资格侦察不能自行成为配对因果样本。
        result["usable_for_paired_behavior"] = False
    return result


def _natural_capture(
    rows: list[dict[str, str]], tags: tuple[str, str], pair: tuple[str, str]
) -> dict[str, object]:
    expected_pair = "_".join(pair)
    grouped: dict[tuple[str, str], dict[str, str]] = {}
    bindings = 0
    last_sample = 0
    end_sample: int | None = None
    samples: set[int] = set()
    required = BOOLEAN_KINDS | {"INIT_SCORE", "TARGET_SCORE"}
    for row in rows:
        tag, kind, value, date = (row[key] for key in ("tag", "kind", "value", "date"))
        if tag not in {"CONTROL", *tags} or not re.fullmatch(r"sample-\d+", date):
            raise ValueError("自然响应含未声明国家或错误序号")
        number = int(date.removeprefix("sample-"))
        if kind in {"BIND", "READY", "HOOK"}:
            if (
                tag != "CONTROL"
                or number != 0
                or value != ("natural" if kind == "HOOK" else expected_pair)
            ):
                raise ValueError("自然响应入口身份或采样不符")
            bindings += int(kind == "BIND")
            continue
        if kind == "END":
            if (
                tag != "CONTROL"
                or value != expected_pair
                or bindings != 1
                or end_sample is not None
                or number != last_sample + 1
            ):
                raise ValueError("自然响应结束身份或时序不符")
            end_sample = number
            continue
        if (
            number < 1
            or (tag == "CONTROL" and kind not in {"TYPE", "ESCALATION"})
            or (tag != "CONTROL" and kind not in required)
        ):
            raise ValueError("自然响应包含未知读数或零序号")
        if bindings != 1:
            raise ValueError("自然响应读数出现在唯一绑定之前")
        if end_sample is not None or number < last_sample:
            raise ValueError("自然响应结束后读数或日样本倒序")
        last_sample = number
        state = grouped.setdefault((tag, date), {})
        if kind in state:
            raise ValueError("自然响应同一样本重复读数")
        state[kind] = value
        samples.add(number)
    if bindings > 1 or (samples and bindings != 1):
        raise ValueError("自然响应绑定缺失或重复")
    if samples and sorted(samples) != list(range(1, max(samples) + 1)):
        raise ValueError("自然响应样本缺号")
    for number in samples:
        date = f"sample-{number}"
        control = grouped.get(("CONTROL", date), {})
        if set(control) != {"TYPE", "ESCALATION"} or not re.fullmatch(
            r"dp_[a-z0-9_]+", control["TYPE"]
        ):
            raise ValueError("自然响应类型或阶段缺失")
        for tag in tags:
            state = grouped.get((tag, date), {})
            if not state.keys() >= BOOLEAN_KINDS or (
                state["UNDECIDED"] == "yes" and not required <= state.keys()
            ):
                raise ValueError("自然响应角色／资格／任务读数不完整")
            if state["PRESENT"] != "yes":
                raise ValueError("自然响应观察国不存在，不能接受空对象读数")
            backing_sides = sum(state[kind] == "yes" for kind in ("INIT_BACKER", "TARGET_BACKER"))
            if (
                backing_sides > 1
                or (state["BACKER"] == "yes") != bool(backing_sides)
                or (state["UNDECIDED"] == state["BACKER"] == "yes")
            ):
                raise ValueError("自然响应角色互相矛盾")
    return {
        "captured": bindings == 1,
        "binding_matrix_complete": bool(bindings == 1 and samples),
        "samples": len(samples),
        "ended": end_sample is not None,
        "end_sample": end_sample,
        "pair": list(pair),
        "engine_safety_requires_clean_report": True,
        "complete_opportunity_denominator": None,
        "quality_improvement_proven": False,
    }
