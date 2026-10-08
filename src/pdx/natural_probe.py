"""自然运行的外交发起事实；不制造机会，也不把started计数当机会分母。"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import TYPE_CHECKING

from . import decision_probe, decisions, game_auto

if TYPE_CHECKING:
    from pathlib import Path

START_VAR = "sitai_probe_natural_start_sample"
MONTH_VAR = "sitai_probe_natural_month_sample"
DEFAULT_TAGS = ("RUS", "PRU")
ROW = re.compile(
    r"SITAI NATURAL;(?P<tag>[A-Z]{3}|ROOT);(?P<kind>START|TYPE|PULSE|HOOK|INITIATOR|TARGET);(?P<value>.*);(?P<sample>sample-\d+)$"
)


def parse_tags(value: str) -> tuple[str, ...]:
    """解析 CLI 的观察国列表，避免把拼写错误静默写进探针。"""

    tags = tuple(part.strip() for part in value.split(",") if part.strip())
    if (
        len(tags) < 2
        or len(set(tags)) != len(tags)
        or any(not re.fullmatch(r"[A-Z]{3}", tag) for tag in tags)
    ):
        raise ValueError("自然外交至少需要两个不重复的三字母国家标签")
    return tags


def build(play_types: list[str], *, tags: tuple[str, ...] = DEFAULT_TAGS) -> dict[str, str]:
    """从全量原版类型键生成纯观察钩子；变量只属于本仪器。"""
    if (
        not play_types
        or len(set(play_types)) != len(play_types)
        or any(not re.fullmatch(r"dp_[a-z0-9_]+", key) for key in play_types)
        or not tags
        or len(set(tags)) != len(tags)
        or any(not re.fullmatch(r"[A-Z]{3}", tag) for tag in tags)
    ):
        raise ValueError("自然观测需要唯一的国家标签与完整合法的博弈类型键")
    starts, pulses = [], []
    for tag in tags:
        sample = f"sample-[SCOPE.sCountry('initiator').MakeScope.Var('{START_VAR}').GetValue|0]"
        types = "\n".join(
            f'if = {{ limit = {{ is_diplomatic_play_type = {key} }} debug_log = "SITAI NATURAL;{tag};TYPE;{key};{sample}" }}'
            for key in sorted(play_types)
        )
        starts.append(f"""debug_log = "SITAI NATURAL;ROOT;HOOK;start;sample-0"
        scope:initiator ?= {{
            debug_log = "SITAI NATURAL;ROOT;INITIATOR;[SCOPE.sCountry('initiator').GetNameNoFormatting];sample-0"
            scope:target ?= {{
                debug_log = "SITAI NATURAL;ROOT;TARGET;[SCOPE.sCountry('target').GetNameNoFormatting];sample-0"
            }}
            if = {{ limit = {{ c:{tag} ?= this is_ai = yes }}
                {decision_probe.sample_step(START_VAR)}
                debug_log = "SITAI NATURAL;{tag};START;[SCOPE.sCountry('target').GetNameNoFormatting];sample-[THIS.Var('{START_VAR}').GetValue|0]"
                root = {{ {types} }}
            }}
        }}""")
        pulses.append(f"""if = {{ limit = {{ c:{tag} ?= this is_ai = yes }}
            {decision_probe.sample_step(MONTH_VAR)}
            debug_log = "SITAI NATURAL;{tag};PULSE;ready;sample-[THIS.Var('{MONTH_VAR}').GetValue|0]"
        }}""")
    script = (
        "# 自然运行started事实；无创建博弈、强制策略、财政注入或立法。\n"
        "on_diplomatic_play_started = { on_actions = { zz_sitai_natural_start } }\n"
        "on_monthly_pulse_country = { on_actions = { zz_sitai_natural_pulse } }\n"
        "zz_sitai_natural_start = { effect = {\n"
        + "\n".join(starts)
        + "\n} }\nzz_sitai_natural_pulse = { effect = {\n"
        + "\n".join(pulses)
        + "\n} }\n"
    )
    metadata = {
        "name": "SITAI natural diplomatic start observer",
        "id": "sitai.probe.natural_diplomacy",
        "version": "1.0",
        "supported_game_version": decisions.load().game_version,
        "short_description": "只记录自然运行发起事实，不构造机会或修改AI",
        "tags": [],
        "relationships": [],
        "game_custom_data": {"multiplayer_synchronized": False},
    }
    return {
        "common/on_actions/zz_sitai_natural.txt": script,
        ".metadata/metadata.json": json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
    }


def analyze(directory: Path, *, tags: tuple[str, ...] = DEFAULT_TAGS) -> dict:
    """按国家和started私有序号去重；冲突、缺类型或缺观察自报均失败。"""
    starts: dict[tuple[str, str], dict[str, str]] = {}
    pulses: dict[str, set[str]] = {tag: set() for tag in tags}
    root_observations: dict[str, set[str]] = {
        kind: set() for kind in ("HOOK", "INITIATOR", "TARGET")
    }
    for path in game_auto.rotated_logs(directory, "debug"):
        with path.open(encoding="utf-8-sig", errors="replace") as stream:
            for line in stream:
                if "SITAI NATURAL;" not in line:
                    continue
                match = ROW.search(line.rstrip())
                if match is None:
                    raise ValueError("自然外交仪器行未完整解析")
                row = match.groupdict()
                tag, sample, kind, value = (row[key] for key in ("tag", "sample", "kind", "value"))
                if tag == "ROOT":
                    if kind not in root_observations or not value:
                        raise ValueError("自然外交根作用域哨兵无效")
                    root_observations[kind].add(value)
                    continue
                if tag not in pulses:
                    raise ValueError(f"自然外交出现未声明观察国：{tag}")
                if kind == "PULSE":
                    if value != "ready":
                        raise ValueError("自然外交月度自报无效")
                    pulses[tag].add(sample)
                    continue
                if not value or "ERROR:" in value or "[SCOPE." in value:
                    raise ValueError("自然外交目标或类型未解析")
                event = starts.setdefault((tag, sample), {})
                if kind in event and event[kind] != value:
                    raise ValueError("同一自然发起序号存在冲突记录")
                event[kind] = value
    if any(not seen for seen in pulses.values()):
        raise ValueError("缺少各观察国月度自报，不能把日志缺失当零发起")
    if any(set(event) != {"START", "TYPE"} for event in starts.values()):
        raise ValueError("自然发起缺目标或类型，观测不完整")
    countries = {}
    for tag in tags:
        events = [
            {"sample": sample, "target": e["START"], "play_type": e["TYPE"]}
            for (t, sample), e in starts.items()
            if t == tag
        ]
        countries[tag] = {
            "monthly_observations": len(pulses[tag]),
            "started": len(events),
            "types": dict(Counter(e["play_type"] for e in events)),
            "targets": dict(Counter(e["target"] for e in events)),
            "events": events,
        }
    return {
        "countries": countries,
        "hook_observations": len(root_observations["HOOK"]),
        "root_initiators": sorted(root_observations["INITIATOR"]),
        "root_targets": sorted(root_observations["TARGET"]),
        "time_basis": "separate per-country monthly and started sequences; actual calendar window from runner ticks",
        "opportunity_denominator": None,
        "quality_improvement_proven": False,
        "limits": "Root hook observations distinguish a hook with no matching observer country from a wholly silent window. Started facts can include vanilla-scripted plays. Accepted demands without a play are absent. Counts do not identify all available AI opportunities, engine autonomy, end outcomes, or policy quality.",
    }
