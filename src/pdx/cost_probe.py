"""隔离的国家预算 getter 校准；总支出不是外交行动净代价。"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING, Any

from . import game_auto

if TYPE_CHECKING:
    from pathlib import Path

MARKER = "SITAI COST;"
ROW = re.compile(
    r"SITAI COST;(?P<tag>[A-Z]{3});(?P<kind>[A-Z_]+);(?P<value>[^;]+);sample-(?P<sample>[1-9]\d*)$"
)
# 只保留已在独立财政仪器中无断言的原版国家 getter。军用品与舰船维护
# getter 虽然在部分版本的符号表中存在，但在外交机会事件作用域下会触发
# GameStateAccess 断言；它们不能进入默认校准路径，避免把探针本身变成
# 游戏错误来源。这里的读数仍只是国家财政快照，不能推导单次外交行动净代价。
GETTERS = {
    "PRINCIPAL": "GetPrincipal",
    "MAX_CREDIT": "GetMaxCredit",
    "RESERVES": "GetGoldReserves",
    "WEEKS_UNTIL_BANKRUPTCY": "GetWeeksUntilBankruptcy",
}
FIELD_METADATA: dict[str, dict[str, object]] = {
    "PRINCIPAL": {
        "getter": "GetPrincipal",
        "scope": "country",
        "unit": "currency_stock",
        "sampling": "shared_sample_N",
        "unknown": "null_or_parse_error",
        "sentinel": None,
        "attribution": "country_total_not_single_action",
    },
    "MAX_CREDIT": {
        "getter": "GetMaxCredit",
        "scope": "country",
        "unit": "currency_capacity",
        "sampling": "shared_sample_N",
        "unknown": "null_or_parse_error",
        "sentinel": None,
        "attribution": "country_total_not_single_action",
    },
    "RESERVES": {
        "getter": "GetGoldReserves",
        "scope": "country",
        "unit": "currency_stock",
        "sampling": "shared_sample_N",
        "unknown": "null_or_parse_error",
        "sentinel": None,
        "attribution": "country_total_not_single_action",
    },
    "WEEKS_UNTIL_BANKRUPTCY": {
        "getter": "GetWeeksUntilBankruptcy",
        "scope": "country",
        "unit": "engine_display_weeks",
        "sampling": "shared_sample_N",
        "unknown": "null_or_parse_error",
        "sentinel": "engine_large_value_must_remain_raw",
        "attribution": "country_total_not_single_action",
    },
}
REQUIRED = frozenset(GETTERS) | {"PRESENT", "COUNTRY_ID", "COMMITTED"}


def validate_mode(*, purpose: str, arm: str, injection: str, natural: bool) -> None:
    if purpose != "instrument" or arm != "control" or injection != "none" or natural:
        raise ValueError(
            "预算校准仅允许 instrument、control、无财政注入的受控机会；不能进入正式或自然包"
        )


def configuration() -> dict[str, object]:
    return {
        "schema": "sitai-country-cost-v2",
        "getters": dict(GETTERS),
        "fields": {key: dict(value) for key, value in FIELD_METADATA.items()},
        "identity_getter": "GetIDString",
        "commitment_trigger": "is_diplomatic_play_committed_participant",
        "units": "本金/储备为货币存量；信用为可用额度；破产周数为引擎显示值；日志保留三位小数",
        "limits": "国家总量及所有博弈的承诺状态；不能归因单次行动，不能推断放弃收益或不利结果",
        "action_cost": None,
        "adverse_outcome": None,
        "quality_improvement_proven": False,
    }


def readings(tag: str) -> str:
    """由机会仪器放进延迟事件，复用其共享采样序号。"""
    if not re.fullmatch(r"[A-Z]{3}", tag):
        raise ValueError("预算校准国家标签必须为三个大写字母")

    def log(kind: str, value: str) -> str:
        return f'debug_log = "{MARKER}{tag};{kind};{value};[TimeKeeper.GetCurrentDate.GetString]"'

    values = [
        log("PRESENT", "yes"),
        log("COUNTRY_ID", "[THIS.GetCountry.GetIDString]"),
        "if = { limit = { is_diplomatic_play_committed_participant = yes } "
        + log("COMMITTED", "yes")
        + " } else = { "
        + log("COMMITTED", "no")
        + " }",
        *(log(kind, f"[THIS.GetCountry.{method}|3]") for kind, method in GETTERS.items()),
    ]
    return (
        f"if = {{ limit = {{ exists = c:{tag} }} c:{tag} = {{\n"
        + "\n".join(values)
        + "\n} } else = { "
        + log("PRESENT", "no")
        + " }"
    )


def analyze(directory: Path, *, tags: tuple[str, str] = ("RUS", "PRU")) -> dict[str, Any]:
    """流式读取完整两国矩阵；未校准数值真值前只报告解析事实。"""
    if len(set(tags)) != 2 or any(not re.fullmatch(r"[A-Z]{3}", tag) for tag in tags):
        raise ValueError("预算校准需要两个不同的规范国家标签")
    samples: dict[int, dict[str, dict[str, str | float]]] = {}
    identities: dict[str, str] = {}
    previous = 0
    for path in game_auto.rotated_logs(directory, "debug"):
        with path.open(encoding="utf-8-sig", errors="strict") as stream:
            for line in stream:
                if MARKER not in line:
                    continue
                match = ROW.search(line.rstrip())
                if match is None or match["tag"] not in tags or match["kind"] not in REQUIRED:
                    raise ValueError("预算校准行格式、国家、字段或序号无效")
                number, tag, kind = int(match["sample"]), match["tag"], match["kind"]
                if number < previous:
                    raise ValueError("预算校准采样倒序")
                previous = number
                state = samples.setdefault(number, {}).setdefault(tag, {})
                if kind in state:
                    raise ValueError("预算校准同国同采样字段重复")
                raw = re.sub(r"\x15[^;\x15]*;", "", match["value"]).replace("\x15!", "").strip()
                value: str | float = raw
                if kind in {"PRESENT", "COMMITTED"}:
                    if raw not in {"yes", "no"} or (kind == "PRESENT" and raw != "yes"):
                        raise ValueError("预算校准布尔无效或国家不存在")
                elif kind == "COUNTRY_ID":
                    if not re.fullmatch(r"0|[1-9]\d*", raw):
                        raise ValueError("预算校准国家身份未展开")
                    if tag in identities and identities[tag] != raw:
                        raise ValueError("预算校准国家身份跨样本变化")
                    identities[tag] = raw
                else:
                    if not re.fullmatch(r"[+−-]?\d+(?:[.,]\d+)?", raw):
                        raise ValueError("预算校准费用未返回数值")
                    value = float(raw.replace("−", "-").replace(",", "."))
                    if not math.isfinite(value):
                        raise ValueError("预算校准费用非有限")
                state[kind] = value
    numbers = sorted(samples)
    if not numbers or any(number != expected for expected, number in enumerate(numbers, 1)):
        raise ValueError("预算校准无样本或序号缺失")
    if set(identities) != set(tags) or len(set(identities.values())) != len(tags):
        raise ValueError("预算校准国家身份缺失或两国对象相同")
    for matrix in samples.values():
        if set(matrix) != set(tags) or any(set(state) != REQUIRED for state in matrix.values()):
            raise ValueError("预算校准两国字段矩阵不完整")
    return {
        "configuration": configuration(),
        "status": "parsed",
        "sample_count": len(samples),
        "country_ids": identities,
        "samples": [{"sample": number, "countries": samples[number]} for number in numbers],
        "sampling": "同一机会的共享 sample-N；启动推进与运行窗口分别由运行器记录；不是精确日历",
        "engine_interface_validated": False,
        "independent_numeric_truth": None,
        "action_cost": None,
        "adverse_outcome": None,
        "quality_improvement_proven": False,
    }
