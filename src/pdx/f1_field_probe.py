"""F1 四个新增策略字段的隔离运行期观测器生成器。

该探针只用于诊断，不属于生产 Mod。它把每次运行限制为一个字段和一个臂，
在同一个国家作用域中记录策略持有状态、可观察的原版上下文和外交博弈钩子。
策略字段的数值本身没有通用脚本 getter，因此分析结果会明确保留
``runtime_field_value=unavailable``，不会把策略牌日志或根钩子误写成消费者行为通过。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from . import decisions

PROBE_ID = "sitai.probe.f1_field_observation"
PROBE_MOD = "zz_sitai_f1_field_observation"
SUBJECT = "RUS"
TARGET = "PRU"
SAMPLE_VAR = "sitai_f1_field_sample"
LATCH_VAR = "sitai_f1_field_play_latch"
FIELDS = (
    "economic_vs_government_spending_balance",
    "recklessness",
    "subject_value",
    "become_subject_value",
)
ARMS = ("control", "candidate")


@dataclass(frozen=True, slots=True)
class FieldSpec:
    field: str
    module: str
    slot: str
    control: float
    candidate: float
    expected_direction: str
    behavior_window: str


FIELD_SPECS: dict[str, FieldSpec] = {
    "economic_vs_government_spending_balance": FieldSpec(
        "economic_vs_government_spending_balance",
        "economy",
        "administrative",
        0.0,
        1.0,
        "candidate favors economic construction over government spending",
        "construction/debt context; no direct field getter",
    ),
    "recklessness": FieldSpec(
        "recklessness",
        "diplomacy",
        "diplomatic",
        -1.0,
        1.0,
        "candidate accepts more relative risk",
        "diplomatic play context",
    ),
    "subject_value": FieldSpec(
        "subject_value",
        "subjects",
        "diplomatic",
        0.0,
        50.0,
        "candidate values prospective subjects more",
        "subject target context; no forced relation",
    ),
    "become_subject_value": FieldSpec(
        "become_subject_value",
        "subjects",
        "diplomatic",
        0.0,
        50.0,
        "candidate values becoming a subject more",
        "overlord context; no forced relation",
    ),
}

ROW_RE = re.compile(r"SITAI F1 FIELD;(?P<kind>[A-Z_]+);(?P<value>.*?);sample-(?P<sample>[1-9]\d*)$")


def validate(field: str, arm: str) -> FieldSpec:
    if field not in FIELD_SPECS:
        raise ValueError(f"未知 F1 字段：{field}；可选：{', '.join(FIELDS)}")
    if arm not in ARMS:
        raise ValueError(f"未知 F1 臂：{arm}；可选：{', '.join(ARMS)}")
    return FIELD_SPECS[field]


def strategy_name(field: str, arm: str) -> str:
    validate(field, arm)
    return f"ai_strategy_sitai_f1_{field.replace('_', '')}_{arm}"


def strategy_text(field: str, arm: str) -> str:
    spec = validate(field, arm)
    value = getattr(spec, arm)
    name = strategy_name(field, arm)
    field_line = f"\t{field} = {{ value = {value:g} }}"
    return (
        "# 由 pdx.f1_field_probe 生成；仅用于 F1 隔离诊断。\n"
        f"{name} = {{\n"
        '\ticon = "gfx/interface/icons/ai_strategy_icons/maintain_power_balance.dds"\n'
        f"\ttype = {spec.slot}\n"
        "\tpossible = { always = yes }\n"
        "\tweight = { value = 0 }\n"
        f"{field_line}\n"
        "}\n"
    )


def _log(kind: str, value: str) -> str:
    return f"debug_log = \"SITAI F1 FIELD;{kind};{value};sample-[THIS.Var('{SAMPLE_VAR}').GetValue|0]\""


def on_actions_text(field: str, arm: str) -> str:
    """生成同一国家作用域的状态、上下文与有限外交行为观测。"""

    validate(field, arm)
    card = strategy_name(field, arm)
    # 这些 trigger 在锁定的原版财政/外交探针中已经使用过；它们是上下文，
    # 不是目标字段的直接读数。
    context = "\n".join(
        f"if = {{ limit = {{ {trigger} }} {_log(kind, 'yes')} }} else = {{ {_log(kind, 'no')} }}"
        for kind, trigger in (
            ("LOANS", "taking_loans = yes"),
            ("DEFAULT", "in_default = yes"),
            ("WAR", "is_at_war = yes"),
            ("SUBJECT", "is_subject = yes"),
        )
    )
    play = ""
    if field == "recklessness":
        play = f"""
if = {{
    limit = {{ var:{SAMPLE_VAR} >= 2 NOT = {{ has_variable = {LATCH_VAR} }} exists = c:{TARGET} }}
    set_variable = {{ name = {LATCH_VAR} value = 1 }}
    create_diplomatic_play = {{ name = sitai_f1_field_play target_country = c:{TARGET} type = dp_humiliation }}
    {_log("PLAY_CREATE", f"c:{TARGET}")}
}}
every_diplomatic_play = {{
    limit = {{ any_scope_play_involved = {{ this = root }} }}
    initiator = {{ {_log("PLAY_INIT", "yes")} }}
    target = {{ {_log("PLAY_TARGET", "yes")} }}
}}
"""
    subject_context = ""
    if field in {"subject_value", "become_subject_value"}:
        subject_context = f"""
if = {{ limit = {{ exists = c:{TARGET} }} c:{TARGET} ?= {{
    if = {{ limit = {{ is_subject_of = root }} {_log("RELATION_TARGET", "subject_of_root")} }}
    else = {{ {_log("RELATION_TARGET", "not_subject_of_root")} }}
}} }}
"""
    return f"""# 由 pdx.f1_field_probe 生成；仅用于 F1 隔离诊断。
on_monthly_pulse_country = {{ on_actions = {{ zz_sitai_f1_field_monthly }} }}
zz_sitai_f1_field_monthly = {{ effect = {{
    if = {{ limit = {{ c:{SUBJECT} ?= this }}
        if = {{ limit = {{ NOT = {{ has_variable = {SAMPLE_VAR} }} }}
            set_variable = {{ name = {SAMPLE_VAR} value = 0 }}
        }}
        change_variable = {{ name = {SAMPLE_VAR} add = 1 }}
        set_strategy = {card}
        {_log("STRATEGY", card)}
        {context}
        {play}
        {subject_context}
        {_log("FIELD", field)}
        {_log("ARM", arm)}
    }}
}} }}
"""


def metadata_text(field: str, arm: str) -> str:
    spec = validate(field, arm)
    payload = {
        "name": "SITAI F1 字段运行期观测器",
        "id": PROBE_ID,
        "version": "1.0",
        "supported_game_version": decisions.load().game_version,
        "short_description": f"F1 隔离观测：{field} / {arm}",
        "tags": [],
        "relationships": [],
        "game_custom_data": {"multiplayer_synchronized": False},
        "f1_observation": {
            "field": field,
            "module": spec.module,
            "arm": arm,
            "control_value": spec.control,
            "candidate_value": spec.candidate,
            "expected_direction": spec.expected_direction,
            "runtime_field_value": "unavailable",
            "behavior_quality": "not_evaluated",
            "limits": spec.behavior_window,
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def build(field: str, arm: str) -> dict[str, str]:
    validate(field, arm)
    return {
        f"common/ai_strategies/zz_sitai_f1_{field}_{arm}.txt": strategy_text(field, arm),
        "common/on_actions/zz_sitai_f1_field.txt": on_actions_text(field, arm),
        ".metadata/metadata.json": metadata_text(field, arm),
        "localization/english/zz_sitai_f1_field_l_english.yml": 'l_english:\n sitai_f1_field_play: "SITAI F1 field observation"\n',
        "localization/simp_chinese/zz_sitai_f1_field_l_simp_chinese.yml": 'l_simp_chinese:\n sitai_f1_field_play: "SITAI F1 字段观测"\n',
    }


def parse_rows(text: str) -> tuple[dict[str, str], ...]:
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        match = ROW_RE.search(line.rstrip())
        if match:
            rows.append(match.groupdict())
    return tuple(rows)


def summarize(rows: tuple[dict[str, str], ...], *, field: str, arm: str) -> dict[str, Any]:
    spec = validate(field, arm)
    by_kind: dict[str, list[str]] = {}
    for row in rows:
        by_kind.setdefault(row["kind"], []).append(row["value"])
    return {
        "schema": "sitai-f1-field-observation-v1",
        "field": field,
        "module": spec.module,
        "arm": arm,
        "rows": len(rows),
        "samples": len({row["sample"] for row in rows}),
        "strategy_observed": strategy_name(field, arm) in by_kind.get("STRATEGY", []),
        "strategy_values": list(dict.fromkeys(by_kind.get("STRATEGY", []))),
        "context": {
            kind: list(dict.fromkeys(values))
            for kind, values in sorted(by_kind.items())
            if kind not in {"FIELD", "ARM", "STRATEGY"}
        },
        "runtime_field_value": "unavailable",
        "expected_direction": spec.expected_direction,
        "behavior_quality": "not_evaluated",
        "evidence_kind": "runtime-hook-and-context",
        "limits": [
            "策略字段没有通用脚本 getter；策略持有日志不证明真实消费者读取。",
            "一次新局诊断不证明方向、量纲、AI质量、玩家路径或长期性能。",
            spec.behavior_window,
        ],
    }


def compare_summaries(control: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """比较同一字段的控制/候选摘要，保留行为质量的未评估边界。"""

    if control.get("field") != candidate.get("field"):
        raise ValueError("控制与候选摘要必须来自同一字段")
    if control.get("module") != candidate.get("module"):
        raise ValueError("控制与候选摘要必须来自同一模块")
    control_context = control.get("context", {})
    candidate_context = candidate.get("context", {})
    return {
        "schema": "sitai-f1-field-pair-v1",
        "field": control["field"],
        "module": control["module"],
        "control": {
            "rows": control.get("rows", 0),
            "samples": control.get("samples", 0),
            "strategy_observed": control.get("strategy_observed", False),
            "strategy_values": control.get("strategy_values", []),
        },
        "candidate": {
            "rows": candidate.get("rows", 0),
            "samples": candidate.get("samples", 0),
            "strategy_observed": candidate.get("strategy_observed", False),
            "strategy_values": candidate.get("strategy_values", []),
        },
        "context_equal": control_context == candidate_context,
        "context_control": control_context,
        "context_candidate": candidate_context,
        "runtime_field_value": "unavailable",
        "behavior_quality": "not_evaluated",
        "evidence_kind": "paired-runtime-hook-and-context",
        "limits": [
            "策略牌持有与根钩子上下文不能证明引擎真实读取字段数值。",
            "没有通用脚本 getter，不能从本配对推出量纲、方向或 AI 行为质量。",
            "每臂一次新局只覆盖短窗口，不证明玩家路径、长期稳定性或跨语言显示。",
        ],
    }


__all__ = [
    "ARMS",
    "FIELDS",
    "FIELD_SPECS",
    "PROBE_MOD",
    "FieldSpec",
    "build",
    "compare_summaries",
    "metadata_text",
    "on_actions_text",
    "parse_rows",
    "strategy_name",
    "strategy_text",
    "summarize",
    "validate",
]
