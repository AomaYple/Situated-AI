"""有限日期、单 host 的战争关系仪器；共同采样不等于独立关系真值。"""

from __future__ import annotations

import json
import re
from bisect import bisect_left, bisect_right
from datetime import date, timedelta
from itertools import pairwise
from typing import TYPE_CHECKING, Any

from . import decision_probe, decisions, game_auto
from .experiment_evidence import _tick, _wall_time

if TYPE_CHECKING:
    from pathlib import Path

HOST = "MEX"
PAIRS = (("MEX", "TEX"), ("BRZ", "TEX"), ("MEX", "MEX"))
SAMPLE_VAR = "sitai_probe_war_sample"
MARKER = "SITAI WAR;"
SOURCE = "zz_sitai_war_calibration"
ROW = re.compile(
    r"SITAI WAR;(?P<host>[A-Z]{3});(?P<kind>DATE|PRESENCE|RELATION);"
    r"(?P<object>[A-Z]{3}/[A-Z]{3}|-);(?P<value>[^;]+);sample-(?P<sample>[1-9]\d*)$"
)


def validate_dates(values: tuple[str, ...]) -> tuple[date, ...]:
    """事前声明的游戏日必须合法、连续、唯一且不超过 90 日。"""
    if not 1 <= len(values) <= 90:
        raise ValueError("战争校准必须显式声明 1 至 90 个连续游戏日")
    days = []
    for value in values:
        if not re.fullmatch(r"[1-9]\d{0,3}\.[1-9]\d?\.[1-9]\d?", value):
            raise ValueError("战争校准日期须为合法 yyyy.m.d，不允许表达式或小时")
        try:
            day = date(*game_auto.parse_tick_date(value))
            day + timedelta(days=1)
        except (ValueError, OverflowError) as exc:
            raise ValueError(f"战争校准日期无效：{value}") from exc
        days.append(day)
    if any(right - left != timedelta(days=1) for left, right in pairwise(days)):
        raise ValueError("战争校准日期必须按时间连续排列且唯一")
    return tuple(days)


def parse_dates(value: str) -> tuple[str, ...]:
    values = tuple(part.strip() for part in value.split(","))
    validate_dates(values)
    return values


def configuration(dates: tuple[str, ...]) -> dict[str, object]:
    validate_dates(dates)
    return {
        "schema": "sitai-war-calibration-v1",
        "purpose": "diagnostic-war-only",
        "host": HOST,
        "pairs": [list(pair) for pair in PAIRS],
        "dates": list(dates),
        "schedule": "on_monthly_pulse_country",
        "sampling_scope": "归档全部仪器日志，包含启动推进；不按 run simulation/activation 窗口截断，不用于正式资格",
        "sample_variable": SAMPLE_VAR,
        "relation_truth_source": None,
    }


def build(*, dates: tuple[str, ...], host: str = HOST) -> dict[str, str]:
    """只写仪器私有计数器；所有日志留在 MEX effect 作用域。"""
    days = validate_dates(dates)
    if host != HOST:
        raise ValueError("战争校准只允许事前声明的独立 host=MEX")
    sample = f"sample-[THIS.Var('{SAMPLE_VAR}').GetValue|0]"

    def log(kind: str, object_key: str, value: str) -> str:
        return f'debug_log = "{MARKER}{host};{kind};{object_key};{value};{sample}"'

    branches = []
    for raw, day in zip(dates, days, strict=True):
        following = day + timedelta(days=1)
        next_date = f"{following.year}.{following.month}.{following.day}"
        readings = []
        for actor, target in PAIRS:
            key = f"{actor}/{target}"
            readings.append(f"""if = {{ limit = {{ exists = c:{actor} exists = c:{target} }}
                {log("PRESENCE", key, "yes")}
                if = {{ limit = {{ c:{actor} ?= {{ has_war_with = c:{target} }} }}
                    {log("RELATION", key, "yes")}
                }} else = {{ {log("RELATION", key, "no")} }}
            }} else = {{
                {log("PRESENCE", key, "no")}
                {log("RELATION", key, "no")}
            }}""")
        branches.append(f"""if = {{ limit = {{ game_date >= {raw} game_date < {next_date} }}
            {decision_probe.sample_step(SAMPLE_VAR)}
            {log("DATE", "-", raw)}
            {chr(10).join(readings)}
        }}""")
    script = (
        "# 独立有限日期战争仪器；只读 country trigger，不改变模拟或外交。\n"
        f"on_monthly_pulse_country = {{ on_actions = {{ {SOURCE} }} }}\n"
        f"{SOURCE} = {{ effect = {{\n"
        f"if = {{ limit = {{ c:{host} ?= this }}\n" + "\n".join(branches) + "\n} } }\n"
    )
    metadata = decisions.metadata_payload()
    metadata.update(
        name="SITAI 有限战争关系校准仪器",
        id="sitai.probe.war_calibration",
        short_description="共同日期与关系采样；没有同 tick 独立战争真值，不证明关系语义或质量",
        game_custom_data={
            "multiplayer_synchronized": False,
            "war_calibration": configuration(dates),
        },
    )
    return {
        f"common/on_actions/{SOURCE}.txt": script,
        ".metadata/metadata.json": json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
    }


def _clock(directory: Path) -> dict[int, tuple[tuple[int, ...], tuple[int, ...]]]:
    clock: dict[int, tuple[tuple[int, ...], tuple[int, ...]]] = {}
    previous_time = -1
    previous_tick: tuple[int, ...] = ()
    for path in game_auto.rotated_logs(directory, "dedicated_server"):
        with path.open(encoding="utf-8-sig", errors="strict") as stream:
            for line in stream:
                match = game_auto.TICK_RE.search(line)
                if match is None:
                    continue
                stamp, tick = _wall_time(line), _tick(match[1])
                if stamp < previous_time or tick < previous_tick:
                    raise ValueError("战争校准逐 tick 日志倒退或跨午夜，不能绑定时间")
                lower, upper = clock.get(stamp, (tick, tick))
                clock[stamp] = min(lower, tick), max(upper, tick)
                previous_time, previous_tick = stamp, tick
    return clock


def analyze(directory: Path, *, dates: tuple[str, ...]) -> dict[str, Any]:
    """流式核对完整矩阵，再用独立逐 tick 日志包围采样的壁钟秒。"""
    config = configuration(dates)
    required = {
        ("DATE", "-"),
        *[(kind, "/".join(pair)) for pair in PAIRS for kind in ("PRESENCE", "RELATION")],
    }
    samples: dict[int, dict[tuple[str, str], str]] = {}
    stamps: dict[int, set[int]] = {}
    previous_sample, previous_stamp = 0, -1
    for path in game_auto.rotated_logs(directory, "debug"):
        with path.open(encoding="utf-8-sig", errors="strict") as stream:
            for line in stream:
                if MARKER not in line:
                    continue
                match = ROW.search(line.rstrip())
                if match is None or match["host"] != HOST:
                    raise ValueError("战争校准日志 host、对象、值或 sample 非规范/未展开")
                number, stamp = int(match["sample"]), _wall_time(line)
                if number < previous_sample or stamp < previous_stamp:
                    raise ValueError("战争校准 sample 或壁钟日志顺序倒退")
                key, value = (match["kind"], match["object"]), match["value"]
                if key not in required:
                    raise ValueError("战争校准存在未声明对象")
                if key[0] == "DATE":
                    if value not in dates:
                        raise ValueError("战争校准存在未声明日期")
                elif value not in {"yes", "no"}:
                    raise ValueError("战争校准关系与 presence 必须为 yes/no")
                readings = samples.setdefault(number, {})
                if key in readings:
                    raise ValueError("战争校准 pair/sample 或 DATE 重复")
                readings[key] = value
                stamps.setdefault(number, set()).add(stamp)
                previous_sample, previous_stamp = number, stamp
    numbers = sorted(samples)
    if (
        not numbers
        or numbers[0] != 1
        or any(right != left + 1 for left, right in pairwise(numbers))
    ):
        raise ValueError("战争校准无完整样本或 sample 不连续")
    clock = _clock(directory)
    times = sorted(clock)
    output: list[dict[str, Any]] = []
    previous_date: date | None = None
    for number in numbers:
        readings = samples[number]
        if set(readings) != required:
            raise ValueError("战争校准样本缺 DATE、presence 或关系")
        if any(readings[("PRESENCE", "/".join(pair))] != "yes" for pair in PAIRS):
            raise ValueError("战争校准国家不存在，不能作为阴性")
        if readings[("RELATION", "MEX/MEX")] != "no":
            raise ValueError("战争校准自我结构性阴性失败")
        raw_date = readings[("DATE", "-")]
        declared_day = date(*game_auto.parse_tick_date(raw_date))
        if previous_date is not None and declared_day <= previous_date:
            raise ValueError("战争校准样本日期重复或倒退")
        previous_date = declared_day
        bounds = []
        bounded = True
        for stamp in sorted(stamps[number]):
            before, after = bisect_left(times, stamp) - 1, bisect_right(times, stamp)
            if before < 0 or after >= len(times):
                bounded = False
                continue
            bounds.append((clock[times[before]][0], clock[times[after]][1]))
        shared_lower = max((bound[0] for bound in bounds), default=())
        shared_upper = min((bound[1] for bound in bounds), default=())
        if bounds and shared_lower > shared_upper:
            raise ValueError("战争校准共享 sample 的独立时间区间不相交")
        # 交集只证明共同时间仍可行；验收覆盖每行全部可能 tick，不能靠交集缩窄歧义。
        lower = min((bound[0] for bound in bounds), default=())
        upper = max((bound[1] for bound in bounds), default=())
        binding = "unknown"
        declared_parts = tuple(game_auto.parse_tick_date(raw_date))
        # 某行缺包围只阻止升级 verified，不能掩盖其他行已经证明的日期冲突。
        if any(not start[:3] <= declared_parts <= end[:3] for start, end in bounds):
            raise ValueError("战争校准 DATE 与独立逐 tick 包围区间冲突")
        if bounded and bounds and lower[:3] == upper[:3]:
            binding = "verified"
        output.append(
            {
                "host": HOST,
                "sample": number,
                "date": raw_date,
                "date_binding": binding,
                "tick_binding": "verified" if bounded and lower and lower == upper else "unknown",
                "tick_bounds": [list(lower), list(upper)] if bounds else None,
                "shared_time_feasible_bounds": [list(shared_lower), list(shared_upper)]
                if bounds
                else None,
                "wall_seconds": sorted(stamps[number]),
                "pairs": [
                    {
                        "actor": actor,
                        "target": target,
                        "present": True,
                        "has_war_with": readings[("RELATION", f"{actor}/{target}")] == "yes",
                    }
                    for actor, target in PAIRS
                ],
            }
        )
    return {
        "configuration": config,
        "samples": output,
        "date_binding": "verified"
        if all(row["date_binding"] == "verified" for row in output)
        else "unknown",
        "unobserved_dates": [
            value for value in dates if value not in {row["date"] for row in output}
        ],
        "structural_negative_control_passed": True,
        "instrument_safe": None,
        "engine_interface_validated": False,
        "relation_truth_validated": False,
        "quality_improvement_proven": False,
        "limits": "安全由 run 严格日志/挂载/恢复门禁决定；DATE guard 不能自证日期。仪器采样包含启动推进，与 run simulation/activation 窗口分别记录，不作正式资格。缺同状态 tick 独立战争/side 真值，自我阴性不能替代普通关系正反校准。",
    }
