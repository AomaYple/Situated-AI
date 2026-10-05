"""只读政治观测：全量法律目标、四个生命周期事件与月度处境。

脚本值自报只表示default新增贡献的重算，不冒充最终AI概率。
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import TYPE_CHECKING

from . import decision_probe, decisions, game_auto
from .model import Block
from .parser import parse_file

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

ROW = re.compile(
    r"SITAI REFORM;(?P<tag>[A-Z]{3});(?P<kind>[A-Z_0-9]+);(?P<value>[^;]*);(?P<date>[^;]*)$"
)
THRESHOLDS = (10, 15, 20, 50)
BOOLEANS = {
    "ENACTING",
    "FRAGILE",
    "OPPORTUNITY",
    "WAR",
    "INSURRECTION",
    "GOV_PREFERRED_AVAILABLE",
    "GOV_PREFERRED_ADVANCE_POSITIVE",
} | {f"GOV_PREFERRED_ADVANCE_GE_{value}" for value in THRESHOLDS}
SAMPLE_VAR = "sitai_probe_reform_sample"


def political_keys(game: Path) -> list[str]:
    """仅从已解析的原版political槽收集键；不猜字段或硬编码国家路线。"""
    keys: list[str] = []
    for path in sorted((game / "common/ai_strategies").glob("*.txt")):
        tree = parse_file(path)
        if tree.errors:
            raise ValueError(f"原版策略无法解析：{path}")
        for assignment in tree.root.assignments():
            if isinstance(assignment.value, Block):
                kind = assignment.value.first("type")
                if kind is not None and str(kind.value) == "political":
                    keys.append(assignment.key)
    if not keys or len(keys) != len(set(keys)):
        raise ValueError("原版政治策略缺失或重复")
    return sorted(keys)


def build(
    laws: Iterable[str],
    *,
    tags: tuple[str, ...] = ("RUS", "FRA"),
    strategies: Iterable[str] = (),
) -> dict[str, str]:
    laws = sorted(set(laws))
    if not laws or any(not re.fullmatch(r"law_[a-z0-9_]+", law) for law in laws):
        raise ValueError("只读仪器必须提供规范的全量法律键")
    if (
        not tags
        or len(tags) != len(set(tags))
        or any(not re.fullmatch(r"[A-Z]{3}", tag) for tag in tags)
    ):
        raise ValueError("观察国标签无效或重复")
    strategies = list(strategies)
    if len(strategies) != len(set(strategies)) or any(
        not re.fullmatch(r"ai_strategy_[a-z0-9_]+", key) for key in strategies
    ):
        raise ValueError("政治策略键无效或重复")
    extensions = decisions.load_extensions()
    # 原版 ip4_negotiation_triggers / scripted_effects 使用这两个法律接口。
    # 可用且为政府IG所偏好仍只是部分条件，不能当最终AI候选资格。
    available_law = "law_is_available = yes NOT = { ROOT = { has_law = prev.type } }"
    government_available = (
        "any_interest_group = { is_in_government = yes any_preferred_law = { "
        + available_law
        + " } }"
    )
    government_advance_positive = (
        "any_interest_group = { is_in_government = yes any_preferred_law = { "
        + available_law
        + " this.type = { law_estimated_enactment_chance > 0 } } }"
    )
    thresholds = tuple(
        (
            f"GOV_PREFERRED_ADVANCE_GE_{value}",
            "any_interest_group = { is_in_government = yes any_preferred_law = { "
            + available_law
            + f" this.type = {{ law_estimated_enactment_chance >= {value} }} }} }}",
        )
        for value in THRESHOLDS
    )
    readings = []
    hooks = []
    for tag in tags:

        def log(kind: str, value: str, *, tag: str = tag) -> str:
            return f"debug_log = \"SITAI REFORM;{tag};{kind};{value};sample-[THIS.Var('{SAMPLE_VAR}').GetValue|0]\""

        booleans = "\n".join(
            f"if = {{ limit = {{ {condition} }} {log(kind, 'yes')} }} else = {{ {log(kind, 'no')} }}"
            for kind, condition in (
                ("ENACTING", "enacting_any_law = yes"),
                ("FRAGILE", "sitai_probe_reform_fragile = yes"),
                ("OPPORTUNITY", "sitai_probe_reform_opportunity = yes"),
                ("WAR", "is_at_war = yes"),
                ("INSURRECTION", "any_insurrection_ongoing = yes"),
                ("GOV_PREFERRED_AVAILABLE", government_available),
                ("GOV_PREFERRED_ADVANCE_POSITIVE", government_advance_positive),
                *thresholds,
            )
        )
        strategy_readings = "\n".join(
            f"if = {{ limit = {{ has_strategy = {key} }} {log('POLITICAL_STRATEGY', key)} }}"
            for key in sorted(strategies)
        )
        readings.append(f"""if = {{ limit = {{ c:{tag} ?= this }}
            {decision_probe.sample_step(SAMPLE_VAR)}
            {booleans}
            {strategy_readings}
            {log("LEGITIMACY", "[THIS.GetCountry.GetGovernmentLegitimacy|3]")}
            {log("COMPUTED_DEFAULT_DELTA", "[THIS.GetCountry.MakeScope.ScriptValue('sitai_probe_reform_default_delta')|3]")}
        }}""")
        for kind in ("START", "PASS", "FAIL", "END"):
            target = "\n".join(
                f"if = {{ limit = {{ is_enacting_law = law_type:{law} }} {log(kind + '_LAW', law)} }}"
                for law in laws
            )
            hooks.append(
                f"sitai_probe_reform_{kind.lower()}_{tag} = {{ effect = {{ if = {{ limit = {{ c:{tag} ?= this }} {decision_probe.sample_step(SAMPLE_VAR)} {log(kind, 'event')} {target} }} }} }}"
            )
    on_actions = [
        "on_monthly_pulse_country = { on_actions = { sitai_probe_reform_read } }",
        "sitai_probe_reform_read = { effect = {\n" + "\n".join(readings) + "\n} }",
    ]
    for kind, name in (("START", "started"), ("PASS", "pass"), ("FAIL", "fail"), ("END", "ended")):
        on_actions.append(
            f"on_law_enactment_{name} = {{ on_actions = {{ {' '.join(f'sitai_probe_reform_{kind.lower()}_{tag}' for tag in tags)} }} }}"
        )
    on_actions.extend(hooks)
    return {
        "common/on_actions/zz_sitai_reform_observer.txt": "\n".join(on_actions) + "\n",
        "common/scripted_triggers/zz_sitai_reform_observer.txt": decisions.extension_triggers(
            extensions
        ).replace("sitai_reform_", "sitai_probe_reform_"),
        "common/script_values/zz_sitai_reform_observer.txt": decisions.extension_values(
            extensions
        ).replace("sitai_reform_", "sitai_probe_reform_"),
        ".metadata/metadata.json": json.dumps(
            {
                "name": "SITAI read-only political observer",
                "id": "sitai.probe.reform",
                "version": "1.0",
                "supported_game_version": decisions.load().game_version,
                "short_description": "只读处境、立法开始/通过/失败/结束；不写法律或IG",
                "tags": [],
                "relationships": [],
                "game_custom_data": {"multiplayer_synchronized": False},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    }


def analyze(directory: Path) -> dict:
    rows = []
    for path in game_auto.rotated_logs(directory, "debug"):
        with path.open(encoding="utf-8-sig", errors="replace") as stream:
            for line in stream:
                if "SITAI REFORM;" not in line:
                    continue
                match = ROW.search(line.rstrip())
                if match is None:
                    raise ValueError("政治仪器行未完整解析")
                if match:
                    row = match.groupdict()
                    if row["date"].startswith("sample-") and not re.fullmatch(
                        r"sample-[1-9]\d*", row["date"]
                    ):
                        raise ValueError("政治采样序号无效")
                    row["value"] = (
                        re.sub(r"\x15[^;\x15]*;", "", row["value"]).replace("\x15!", "").strip()
                    )
                    if row["kind"] in BOOLEANS and row["value"] not in {"yes", "no"}:
                        raise ValueError(f"政治布尔读数未解析：{row}")
                    if row["kind"] == "POLITICAL_STRATEGY" and not re.fullmatch(
                        r"ai_strategy_[a-z0-9_]+", row["value"]
                    ):
                        raise ValueError(f"政治策略读数未解析：{row}")
                    if row["kind"] in {"LEGITIMACY", "COMPUTED_DEFAULT_DELTA"}:
                        try:
                            number = float(row["value"].replace("−", "-").replace(",", "."))
                        except ValueError as exc:
                            raise ValueError(f"政治数值未解析：{row}") from exc
                        if not math.isfinite(number):
                            raise ValueError(f"政治数值非有限：{row}")
                    rows.append(row)
    if not rows:
        raise ValueError("缺少本局政治读数")
    countries = {}
    for tag in sorted({r["tag"] for r in rows}):
        seen = [r for r in rows if r["tag"] == tag]
        counts = Counter(r["kind"] for r in seen)
        countries[tag] = {
            "monthly_observations": counts["LEGITIMACY"],
            "enactment_idle_observations": sum(
                r["kind"] == "ENACTING" and r["value"] == "no" for r in seen
            ),
            "government_preferred_available_observations": sum(
                r["kind"] == "GOV_PREFERRED_AVAILABLE" and r["value"] == "yes" for r in seen
            ),
            "government_preferred_advance_positive_observations": sum(
                r["kind"] == "GOV_PREFERRED_ADVANCE_POSITIVE" and r["value"] == "yes" for r in seen
            ),
            "government_preferred_threshold_observations": {
                str(value): sum(
                    r["kind"] == f"GOV_PREFERRED_ADVANCE_GE_{value}" and r["value"] == "yes"
                    for r in seen
                )
                for value in THRESHOLDS
            },
            "political_strategy_distribution": dict(
                Counter(r["value"] for r in seen if r["kind"] == "POLITICAL_STRATEGY")
            ),
            "events": {kind: counts[kind] for kind in ("START", "PASS", "FAIL", "END")},
            "starts": [r for r in seen if r["kind"] == "START_LAW"],
            "computed_delta_distribution": dict(
                Counter(r["value"] for r in seen if r["kind"] == "COMPUTED_DEFAULT_DELTA")
            ),
        }
    return {
        "rows": rows,
        "countries": countries,
        "quality_improvement_proven": False,
        "time_basis": "sample-N is a per-country observation/event sequence, not a calendar date; historical date strings remain unchanged",
        "limits": "Monthly idle observations do not prove a viable law existed. Government-preferred available laws and estimated advance threshold buckets are partial conditions, not final AI feasibility, success chance, or law-selection scores. Active political strategy is observed separately; conditional minimums, direction and civil-war vetoes remain distinct. Computed default contribution is not final engine chance. Pass/fail/end are separate outcomes; one run is not causal proof.",
    }
