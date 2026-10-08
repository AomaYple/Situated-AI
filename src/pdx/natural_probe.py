"""自然运行的外交发起事实；不制造机会，也不把started计数当机会分母。"""

from __future__ import annotations

import json
import re
from collections import Counter
from itertools import pairwise
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
COMMAND_ROW = re.compile(
    r"SITAI COMMAND;(?P<actor>[A-Z]{3});(?P<target>[A-Z]{3});dp_humiliation;VALID;(?P<value>yes|no);sample-(?P<sample>[1-9]\d*)$"
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


def build(
    play_types: list[str],
    *,
    tags: tuple[str, ...] = DEFAULT_TAGS,
    command_targets: tuple[str, ...] = (),
) -> dict[str, str]:
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
    if command_targets and "dp_humiliation" not in play_types:
        raise ValueError("有限命令观测需要原版 dp_humiliation 类型")
    if len(set(command_targets)) != len(command_targets) or any(
        not re.fullmatch(r"[A-Z]{3}", tag) for tag in command_targets
    ):
        raise ValueError("有限命令目标必须是唯一的规范国家标签")
    starts: list[str] = []
    pulses: list[str] = []
    commands: list[str] = []
    for tag in tags:
        sample = f"sample-[SCOPE.sCountry('initiator').MakeScope.Var('{START_VAR}').GetValue|0]"
        types = "\n".join(
            f'if = {{ limit = {{ is_diplomatic_play_type = {key} }} debug_log = "SITAI NATURAL;{tag};TYPE;{key};{sample}" }}'
            for key in sorted(play_types)
        )
        starts.append(f"""scope:initiator ?= {{
            if = {{ limit = {{ c:{tag} ?= this is_ai = yes }}
                {decision_probe.sample_step(START_VAR)}
                debug_log = "SITAI NATURAL;{tag};START;[SCOPE.sCountry('target').GetNameNoFormatting];sample-[THIS.Var('{START_VAR}').GetValue|0]"
                root = {{ {types} }}
            }}
        }}""")
        schedules = []
        actor_scope = f"sitai_command_actor_{tag.lower()}"
        for target in command_targets:
            event_id = f"zz_sitai_natural_commands.{len(commands) + 1}"
            target_scope = f"sitai_command_target_{tag.lower()}_{target.lower()}"
            schedules.append(f"""if = {{ limit = {{ exists = c:{target} }}
                c:{target} ?= {{ save_scope_as = {target_scope} }}
                trigger_event = {{ id = {event_id} days = 1 }}
            }}""")
            expression = (
                "IsValid(GetDiplomaticPlayType('dp_humiliation').GetStartCommandCountry("
                f"SCOPE.sCountry('{actor_scope}').Self,"
                f"SCOPE.sCountry('{target_scope}').Self))"
            )
            commands.append(f"""{event_id} = {{
    type = country_event
    hidden = yes
    immediate = {{
        debug_log = "SITAI COMMAND;{tag};{target};dp_humiliation;VALID;[Select_CString({expression}, 'yes', 'no')];sample-[THIS.Var('{MONTH_VAR}').GetValue|0]"
    }}
}}""")
        bindings = f"save_scope_as = {actor_scope}\n" + "\n".join(schedules) if schedules else ""
        pulses.append(f"""if = {{ limit = {{ c:{tag} ?= this is_ai = yes }}
            {decision_probe.sample_step(MONTH_VAR)}
            debug_log = "SITAI NATURAL;{tag};PULSE;ready;sample-[THIS.Var('{MONTH_VAR}').GetValue|0]"
            {bindings}
        }}""")
    script = (
        "# 自然运行started事实；无创建博弈、强制策略、财政注入或立法。\n"
        "on_diplomatic_play_started = { on_actions = { zz_sitai_natural_start } }\n"
        "on_monthly_pulse_country = { on_actions = { zz_sitai_natural_pulse } }\n"
        "zz_sitai_natural_start = { effect = {\n"
        'debug_log = "SITAI NATURAL;ROOT;HOOK;start;sample-0"\n'
        "scope:initiator ?= { debug_log = \"SITAI NATURAL;ROOT;INITIATOR;[SCOPE.sCountry('initiator').GetNameNoFormatting];sample-0\" }\n"
        "scope:target ?= { debug_log = \"SITAI NATURAL;ROOT;TARGET;[SCOPE.sCountry('target').GetNameNoFormatting];sample-0\" }\n"
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
    files = {
        "common/on_actions/zz_sitai_natural.txt": script,
        ".metadata/metadata.json": json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
    }
    if commands:
        files["events/zz_sitai_natural_commands.txt"] = (
            "# 只读查询原版启动命令的合法性；不执行命令。\n"
            "namespace = zz_sitai_natural_commands\n" + "\n".join(commands) + "\n"
        )
    return files


def analyze_commands(directory: Path, *, tags: tuple[str, ...], targets: tuple[str, ...]) -> dict:
    """核对有限目标集的月度合法性快照，不把玩家命令资格冒充AI机会全集。"""
    if (
        not tags
        or not targets
        or any(
            len(set(values)) != len(values)
            or any(not re.fullmatch(r"[A-Z]{3}", value) for value in values)
            for values in (tags, targets)
        )
    ):
        raise ValueError("命令观测必须声明规范的观察国与有限目标集")
    expected = {(actor, target) for actor in tags for target in targets}
    observations: dict[tuple[str, str], dict[int, bool]] = {pair: {} for pair in expected}
    for path in game_auto.rotated_logs(directory, "debug"):
        with path.open(encoding="utf-8-sig", errors="replace") as stream:
            for line in stream:
                if "SITAI COMMAND;" not in line:
                    continue
                match = COMMAND_ROW.search(line.rstrip())
                if match is None:
                    raise ValueError("命令合法性观测未解析为规范布尔值与采样序号")
                actor, target, raw, sample = match.group("actor", "target", "value", "sample")
                pair = actor, target
                if pair not in expected:
                    raise ValueError(f"未声明命令观测对象：{pair}")
                values = observations[pair]
                number, valid = int(sample), raw == "yes"
                if number in values and values[number] != valid:
                    raise ValueError(f"同一命令合法性样本冲突：{pair}/sample-{number}")
                values[number] = valid
    pairs: list[dict] = []
    negative_controls: list[dict] = []
    for (actor, target), values in sorted(observations.items()):
        samples = sorted(values)
        if not samples or samples != list(range(samples[0], samples[-1] + 1)):
            raise ValueError(f"命令观测缺失或不连续：{actor}/{target}")
        first = bool(values[samples[0]])
        entries = sum(not values[a] and values[b] for a, b in pairwise(samples))
        if actor == target:
            if any(values.values()):
                raise ValueError("自我目标命令被判合法，不能确认该接口的合法性语义")
            negative_controls.append({"actor": actor, "snapshots": len(samples), "passed": True})
            continue
        pairs.append(
            {
                "actor": actor,
                "target": target,
                "play_type": "dp_humiliation",
                "first_sample": samples[0],
                "last_sample": samples[-1],
                "candidate_snapshots": len(samples),
                "valid_snapshots": sum(values.values()),
                "observed_valid_episodes": int(first) + entries,
                "valid_entry_transitions": entries,
                "first_episode_left_censored": first,
                "observations": [{"sample": n, "valid": values[n]} for n in samples],
            }
        )
    for actor in tags:
        coverages = [tuple(sorted(observations[(actor, target)])) for target in targets]
        if any(coverage != coverages[0] for coverage in coverages):
            raise ValueError(f"同一观察国的目标集合采样覆盖不一致：{actor}")
    interface_validated = bool(
        negative_controls and any(pair["valid_snapshots"] > 0 for pair in pairs)
    )
    return {
        "pairs": pairs,
        "negative_controls": negative_controls,
        "candidate_snapshots": sum(pair["candidate_snapshots"] for pair in pairs),
        "valid_snapshots": sum(pair["valid_snapshots"] for pair in pairs),
        "observed_valid_episodes": sum(pair["observed_valid_episodes"] for pair in pairs),
        "valid_entry_transitions": sum(pair["valid_entry_transitions"] for pair in pairs),
        "negative_control_snapshots": sum(control["snapshots"] for control in negative_controls),
        "complete_opportunity_denominator": None,
        "engine_interface_validated": interface_validated,
        "interface_validation_scope": (
            "same-run finite dp_humiliation target positive plus self-target negative control"
            if interface_validated
            else None
        ),
        "quality_improvement_proven": False,
        "scope": "explicit actor/target subset; country-target dp_humiliation command validity",
        "sampling": "monthly pulse, delayed one day with distinct actor/target scopes; sample-N is the country counter read on the following day, not calendar time",
        "limits": "Interface validation requires same-run positive and self-target negative controls and a separately clean runner report. Validity is command legality, not native AI feasibility, utility or start rate. Monthly snapshots can miss short episodes; an initially valid episode is left censored. State-target plays and accepted demands without plays are absent.",
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
                    if (
                        kind not in root_observations
                        or sample != "sample-0"
                        or not value
                        or "ERROR:" in value
                        or "[SCOPE." in value
                        or (kind == "HOOK" and value != "start")
                    ):
                        raise ValueError("自然外交根作用域哨兵无效")
                    root_observations[kind].add(value)
                    continue
                if tag not in pulses:
                    raise ValueError(f"自然外交出现未声明观察国：{tag}")
                if not re.fullmatch(r"sample-[1-9]\d*", sample):
                    raise ValueError("自然外交国家序号必须为正整数")
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
    for tag, seen in pulses.items():
        samples = sorted(int(sample.removeprefix("sample-")) for sample in seen)
        if samples != list(range(samples[0], samples[-1] + 1)):
            raise ValueError(f"自然外交月度自报不连续：{tag}")
    if any(set(event) != {"START", "TYPE"} for event in starts.values()):
        raise ValueError("自然发起缺目标或类型，观测不完整")
    countries = {}
    for tag in tags:
        events = [
            {"sample": sample, "target": e["START"], "play_type": e["TYPE"]}
            for (t, sample), e in sorted(
                starts.items(),
                key=lambda item: (item[0][0], int(item[0][1].removeprefix("sample-"))),
            )
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
        "hook_seen": bool(root_observations["HOOK"]),
        "hook_count": None,
        "root_initiators": sorted(root_observations["INITIATOR"]),
        "root_targets": sorted(root_observations["TARGET"]),
        "time_basis": "separate per-country monthly and started sequences; actual calendar window from runner ticks",
        "opportunity_denominator": None,
        "quality_improvement_proven": False,
        "limits": "Root hook_seen records presence, never event count; historical hook_observations was also only deduplicated presence. Started facts can include vanilla-scripted plays. Accepted demands without a play are absent. Counts do not identify all available AI opportunities, engine autonomy, end outcomes, or policy quality.",
    }
