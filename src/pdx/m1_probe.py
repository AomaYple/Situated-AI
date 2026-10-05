"""M1：外交策略接口与实际外交行为的独立实机探针。

探针故意与正式 mod 分离。它只回答一个工程问题：运行时 ``set_strategy``
切换外交策略后，AI 是否继续把策略字段带入实际外交博弈，并能在日志中观察到
发起方、目标方、参与角色、博弈类型和战争目标。

仓库源文件无 BOM；安装到游戏目录时由 :func:`pdx.textio.deploy_tree` 添加 BOM。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 - constants are constructed at import time

from . import config

PROBE_MOD = "zz_probe_m1_diplomacy"
PROBE_DIR = config.OUT / "m1" / "generated"
SUBJECT = "RUS"
TARGET = "PRU"

CAUTIOUS = "ai_strategy_sitai_m1_cautious_diplomacy"
ASSERTIVE = "ai_strategy_sitai_m1_assertive_diplomacy"
MONTH_VAR = "sitai_m1_month"
PHASE_VAR = "sitai_m1_phase"
PLAY_LATCH = "sitai_m1_play_created"


@dataclass(frozen=True, slots=True)
class M1Row:
    """一行 M1 日志。"""

    kind: str
    value: str
    country: str


REPORT_RE = re.compile(r"ZZPROBE M1;(?P<kind>[A-Z_]+);(?P<value>.*?);(?P<country>[^;]*)\s*$")


def strategy_text() -> str:
    """生成两张外交策略牌，使用原版已确认的外交行为字段。"""
    return f"""# ⚠️ 由 src/pdx/m1_probe.py 生成；仅用于 M1 实机实验。
{CAUTIOUS} = {{
\ticon = "gfx/interface/icons/ai_strategy_icons/maintain_power_balance.dds"
\ttype = diplomatic

\tdiplomatic_play_neutrality = {{ value = 100 }}
\tdiplomatic_play_boldness = {{ value = -100 }}
\trecklessness = {{ value = -1 }}
\taggression = {{ value = -1 }}
\tdiplomatic_play_support = {{ value = -100 }}
\twargoal_maneuvers_fraction = {{ value = -0.25 }}
\twargoal_weights = {{
\t\tannex_country = -100
\t\tconquer_state = -100
\t\treturn_state = -50
\t\thumiliation = -25
\t}}
\tpossible = {{ always = yes }}
\tweight = {{ value = 0 }}
}}

{ASSERTIVE} = {{
\ticon = "gfx/interface/icons/ai_strategy_icons/territorial_expansion.dds"
\ttype = diplomatic

\tdiplomatic_play_neutrality = {{ value = -100 }}
\tdiplomatic_play_boldness = {{ value = 100 }}
\trecklessness = {{ value = 1 }}
\taggression = {{ value = 100 }}
\tdiplomatic_play_support = {{ value = 100 }}
\twargoal_maneuvers_fraction = {{ value = 0.25 }}
\twargoal_weights = {{
\t\tannex_country = 100
\t\tconquer_state = 100
\t\treturn_state = 50
\t\thumiliation = 25
\t}}
\tpossible = {{ always = yes }}
\tweight = {{ value = 0 }}
}}
"""


def _log(kind: str, value: str, country: str = "[THIS.GetCountry.GetNameNoFormatting]") -> str:
    return f'\t\tdebug_log = "ZZPROBE M1;{kind};{value};{country}"'


def on_actions_text() -> str:
    """生成月度切换、自报和受控外交博弈的脚本。"""
    goal_lines = "\n".join(
        f"\t\t\t\tif = {{ limit = {{ has_play_goal = {goal} }}\n"
        f'\t\t\t\t\tdebug_log = "ZZPROBE M1;PLAY_GOAL;{goal};play"\n\t\t\t\t}}'
        for goal in (
            "humiliation",
            "annex_country",
            "conquer_state",
            "return_state",
            "make_protectorate",
        )
    )
    type_lines = "\n".join(
        f"\t\t\t\tif = {{ limit = {{ is_diplomatic_play_type = {play_type} }}\n"
        f'\t\t\t\t\tdebug_log = "ZZPROBE M1;PLAY_TYPE;{play_type};play"\n\t\t\t\t}}'
        for play_type in ("dp_humiliation", "dp_annex_war", "dp_conquer_state", "dp_return_state")
    )
    return f"""# ⚠️ 由 src/pdx/m1_probe.py 生成；仅用于 M1 实机实验。
on_monthly_pulse_country = {{
\ton_actions = {{ zz_probe_m1_monthly }}
}}

on_diplomatic_play_started = {{
\ton_actions = {{ zz_probe_m1_play_started }}
}}

zz_probe_m1_play_started = {{
\teffect = {{
\t\t# root = diplomatic_play；两条国家日志分别记录真实发起方和目标方。
\t\tinitiator = {{ debug_log = "ZZPROBE M1;PLAY_START_INIT;yes;[THIS.GetCountry.GetNameNoFormatting]" }}
\t\ttarget = {{ debug_log = "ZZPROBE M1;PLAY_START_TARGET;yes;[THIS.GetCountry.GetNameNoFormatting]" }}
{type_lines}
{goal_lines}
\t}}
}}

zz_probe_m1_monthly = {{
\teffect = {{
\t\tif = {{
\t\t\tlimit = {{ c:{SUBJECT} ?= this }}
\t\t\tif = {{
\t\t\t\tlimit = {{ NOT = {{ has_variable = {MONTH_VAR} }} }}
\t\t\t\tset_variable = {{ name = {MONTH_VAR} value = 0 }}
\t\t\t}}
\t\t\tif = {{
\t\t\t\tlimit = {{ NOT = {{ has_variable = {PHASE_VAR} }} }}
\t\t\t\tset_variable = {{ name = {PHASE_VAR} value = 0 }}
\t\t\t}}
\t\t\tchange_variable = {{ name = {MONTH_VAR} add = 1 }}

\t\t\t# 阶段 1：月份 1–6，保守；阶段 2：7–12，进取；阶段 3：13 起，切回保守。
\t\t\tif = {{
\t\t\t\tlimit = {{ var:{PHASE_VAR} < 1 }}
\t\t\t\tset_variable = {{ name = {PHASE_VAR} value = 1 }}
\t\t\t\tset_strategy = {CAUTIOUS}
\t\t\t\t{_log("PHASE", "cautious")}
\t\t\t}}
\t\t\tif = {{
\t\t\t\tlimit = {{ var:{PHASE_VAR} = 1 var:{MONTH_VAR} >= 7 }}
\t\t\t\tset_variable = {{ name = {PHASE_VAR} value = 2 }}
\t\t\t\tset_strategy = {ASSERTIVE}
\t\t\t\t{_log("PHASE", "assertive")}
\t\t\t}}
\t\t\tif = {{
\t\t\t\tlimit = {{ var:{PHASE_VAR} = 2 var:{MONTH_VAR} >= 13 }}
\t\t\t\tset_variable = {{ name = {PHASE_VAR} value = 3 }}
\t\t\t\tset_strategy = {CAUTIOUS}
\t\t\t\t{_log("PHASE", "cautious_reentry")}
\t\t\t}}

\t\t\t# 第 4 月创建一个可重复的受控外交博弈；若自然博弈已经占用目标则不重复创建。
\t\t\tif = {{
\t\t\t\tlimit = {{
\t\t\t\t\tvar:{MONTH_VAR} >= 4
\t\t\t\t\tNOT = {{ has_variable = {PLAY_LATCH} }}
\t\t\t\t\texists = c:{TARGET}
\t\t\t\t\tNOT = {{ any_diplomatic_play = {{ initiator_is = c:{SUBJECT} target_is = c:{TARGET} }} }}
\t\t\t\t}}
\t\t\t\tset_variable = {{ name = {PLAY_LATCH} value = 1 }}
\t\t\t\tcreate_diplomatic_play = {{
\t\t\t\t\tname = sitai_m1_controlled_play
\t\t\t\t\ttarget_country = c:{TARGET}
\t\t\t\t\ttype = dp_humiliation
\t\t\t\t}}
\t\t\t\t{_log("CONTROL_PLAY", f"c:{TARGET}")}
\t\t\t}}

\t\t\t# 当前持有策略：这是策略层证据；下面的 PLAY_* 是行为层证据。
\t\t\tif = {{ limit = {{ has_strategy = {CAUTIOUS} }}\n{_log("STRATEGY", "cautious")}\t\t\t}}
\t\t\telse_if = {{ limit = {{ has_strategy = {ASSERTIVE} }}\n{_log("STRATEGY", "assertive")}\t\t\t}}
\t\t\telse = {{\n{_log("STRATEGY", "other")}\t\t\t}}

\t\t\tif = {{ limit = {{ is_diplomatic_play_initiator = yes }}\n{_log("PLAY_ROLE", "initiator")}\t\t\t}}
\t\t\tif = {{ limit = {{ is_diplomatic_play_target = yes }}\n{_log("PLAY_ROLE", "target")}\t\t\t}}
\t\t\tif = {{ limit = {{ is_diplomatic_play_committed_participant = yes }}\n{_log("PLAY_ROLE", "committed")}\t\t\t}}
\t\t\tif = {{ limit = {{ is_diplomatic_play_undecided_participant = yes }}\n{_log("PLAY_ROLE", "undecided")}\t\t\t}}

\t\t\tevery_diplomatic_play = {{
\t\t\t\tlimit = {{ any_scope_play_involved = {{ this = root }} }}
\t\t\t\tinitiator = {{ debug_log = "ZZPROBE M1;PLAY_ACTIVE_INIT;yes;[THIS.GetCountry.GetNameNoFormatting]" }}
\t\t\t\ttarget = {{ debug_log = "ZZPROBE M1;PLAY_ACTIVE_TARGET;yes;[THIS.GetCountry.GetNameNoFormatting]" }}
\t\t\t\t{type_lines}
\t\t\t\t{goal_lines}
\t\t\t}}
\t\t}}
\t}}
}}
"""


def metadata_text() -> str:
    return '{\n  "name": "SITAI M1 diplomacy probe",\n  "id": "",\n  "version": "1.0",\n  "supported_game_version": "1.14.5",\n  "short_description": "M1 实机验证：外交策略切换是否进入 AI 外交博弈行为",\n  "tags": [],\n  "relationships": [],\n  "game_custom_data": {\n    "multiplayer_synchronized": false\n  }\n}\n'


def localization_text() -> str:
    return 'l_simp_chinese:\n sitai_m1_controlled_play: "SITAI M1 受控外交博弈"\n'


def build() -> dict[str, str]:
    return {
        "common/ai_strategies/zz_probe_m1_diplomatic.txt": strategy_text(),
        "common/on_actions/zz_probe_m1_on_actions.txt": on_actions_text(),
        ".metadata/metadata.json": metadata_text(),
        "localization/simp_chinese/zz_probe_m1_l_simp_chinese.yml": localization_text(),
    }


def write(root: Path | None = None) -> list[Path]:
    base = root or PROBE_DIR
    written: list[Path] = []
    for rel, text in build().items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)
    return written


def parse_rows(text: str) -> tuple[M1Row, ...]:
    rows: list[M1Row] = []
    for line in text.splitlines():
        match = REPORT_RE.search(line)
        if match:
            rows.append(M1Row(match["kind"], match["value"], match["country"]))
    return tuple(rows)


def summarize(rows: tuple[M1Row, ...]) -> dict[str, object]:
    """输出可审计摘要；缺少行为行时明确报告未观测到。"""
    by_kind: dict[str, list[str]] = {}
    for row in rows:
        by_kind.setdefault(row.kind, []).append(row.value)
    strategies = list(dict.fromkeys(by_kind.get("STRATEGY", [])))
    roles = list(dict.fromkeys(by_kind.get("PLAY_ROLE", [])))
    controlled_targets = list(dict.fromkeys(by_kind.get("CONTROL_PLAY", [])))
    return {
        "rows": len(rows),
        "strategies": strategies,
        "strategy_counts": dict(
            sorted(
                {value: by_kind.get("STRATEGY", []).count(value) for value in strategies}.items()
            )
        ),
        "phases": list(dict.fromkeys(by_kind.get("PHASE", []))),
        "phase_counts": dict(
            sorted(
                {
                    value: by_kind.get("PHASE", []).count(value)
                    for value in set(by_kind.get("PHASE", []))
                }.items()
            )
        ),
        "play_roles": roles,
        "play_role_counts": dict(
            sorted({value: by_kind.get("PLAY_ROLE", []).count(value) for value in roles}.items())
        ),
        "control_play_observed": bool(controlled_targets),
        "control_play_targets": controlled_targets,
        "play_start_observed": bool(by_kind.get("PLAY_START_INIT")),
        "play_active_observed": bool(by_kind.get("PLAY_ACTIVE_INIT")),
        "play_types": list(dict.fromkeys(by_kind.get("PLAY_TYPE", []))),
        "play_type_counts": dict(
            sorted(
                {
                    value: by_kind.get("PLAY_TYPE", []).count(value)
                    for value in set(by_kind.get("PLAY_TYPE", []))
                }.items()
            )
        ),
        "play_goals": list(dict.fromkeys(by_kind.get("PLAY_GOAL", []))),
        "play_goal_counts": dict(
            sorted(
                {
                    value: by_kind.get("PLAY_GOAL", []).count(value)
                    for value in set(by_kind.get("PLAY_GOAL", []))
                }.items()
            )
        ),
        "behavior_evidence": bool(by_kind.get("PLAY_START_INIT") or by_kind.get("PLAY_ROLE")),
    }


__all__ = [
    "ASSERTIVE",
    "CAUTIOUS",
    "PROBE_DIR",
    "PROBE_MOD",
    "REPORT_RE",
    "M1Row",
    "build",
    "metadata_text",
    "on_actions_text",
    "parse_rows",
    "strategy_text",
    "summarize",
    "write",
]
