"""隔离的财政接口与生命周期实机仪器；注入仅存在于探针产物。"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from itertools import pairwise
from typing import TYPE_CHECKING, NotRequired, TypedDict

from . import decisions
from . import game_auto as ga
from .localization import parse_loc_entries

if TYPE_CHECKING:
    from pathlib import Path

ROW = re.compile(
    r"SITAI DECISION;(?P<tag>[A-Z]{3});(?P<kind>[A-Z_]+);(?P<value>.*);(?P<date>[^;]*)$"
)
SAMPLE_VAR = "sitai_probe_fiscal_sample"
DEFAULT_TAGS = ("RUS", "PRU")
NATIVE_KINDS = ("NATIVE_CREDIT_POS", "NATIVE_ENTRY", "NATIVE_HOLD", "NATIVE_WEEKS")
BOOLEANS = frozenset(
    {
        "DEFAULT",
        "LOANS",
        "WAR",
        "EXPOSURE",
        "CREDIT_POS",
        "COMMITTED",
        "ENTRY",
        "HOLD",
        "RISK",
        "ACTIVE",
        "NATIVE_CREDIT_POS",
        "NATIVE_ENTRY",
        "NATIVE_HOLD",
    }
)
NATIVE_ALLOWED_KINDS = BOOLEANS | {"NATIVE_WEEKS"}
BASELINE_LOC_KEYS = frozenset(
    {
        "is_at_war_with_overlord_tt",
        "SHIP_TRANSFER_REQUIRES_RECIPROCAL_ARTICLE",
        "ANNEX_SUBJECT_START_EFFECTS_LINE",
    }
)


def build_localization_baseline(game: Path) -> dict[str, str]:
    """隔离实验的原版中文缺键补全；仅复制英语文本，不更改玩法或豁免错误。"""
    found: dict[str, dict[str, tuple[str, str]]] = {"l_english": {}, "l_simp_chinese": {}}
    for language in ("english", "simp_chinese"):
        for path in sorted((game / "localization" / language).rglob("*.yml")):
            # 先流式筛选目标行，再复用已有行式解析器；避免为3个键物化整份本地化。
            headers, selected = [], []
            with path.open(encoding="utf-8-sig") as stream:
                for line in stream:
                    if line.lstrip().startswith("l_"):
                        headers.append(line)
                    elif line.partition(":")[0].strip() in BASELINE_LOC_KEYS:
                        selected.append(line)
            lang, entries = parse_loc_entries("".join(headers + selected))
            if lang not in found:
                raise ValueError(f"本地化目录与语言声明不一致：{path}")
            for key, value in entries:
                if key not in BASELINE_LOC_KEYS:
                    continue
                if key in found[lang]:
                    raise ValueError(f"原版本地化目标键重复：{lang}/{key}")
                found[lang][key] = (value, path.relative_to(game).as_posix())
    missing_english = BASELINE_LOC_KEYS - found["l_english"].keys()
    if missing_english:
        raise ValueError(f"缺少原版英语底本：{sorted(missing_english)}")
    missing = sorted(BASELINE_LOC_KEYS - found["l_simp_chinese"].keys())
    lines = ["l_simp_chinese:"]
    # 原版反斜杠转义已由行式解析器保留；只补闭合引号，不用JSON/YAML重写值。
    lines.extend(f' {key}: "{found["l_english"][key][0]}"' for key in missing)
    manifest = {
        "purpose": "用于诊断的原版本地化基线，不属于生产玩法",
        "language": "l_simp_chinese",
        "keys": {key: found["l_english"][key][1] for key in missing},
        "already_present": sorted(BASELINE_LOC_KEYS - set(missing)),
        "limits": "只为已核实缺失的原版键提供英文回退文本；不豁免引擎错误",
    }
    metadata = {
        "name": "SITAI 原版本地化基线仪器",
        "id": "sitai.probe.localization_baseline",
        "version": "1.0",
        "supported_game_version": decisions.load().game_version,
        "short_description": "仅补原版中文缺键，不改游戏机制或错误门禁",
        "tags": [],
        "relationships": [],
        "game_custom_data": {"multiplayer_synchronized": False},
    }
    return {
        ".metadata/metadata.json": json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        "baseline.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        "localization/simp_chinese/zz_sitai_vanilla_baseline_l_simp_chinese.yml": "\n".join(lines)
        + "\n",
    }


def sample_step(variable: str) -> str:
    """原生脚本维护仪器私有序号；不用只能在Interface访问的全局GUI日期。"""
    if not re.fullmatch(r"sitai_probe_[a-z0-9_]+", variable):
        raise ValueError("采样变量必须在仪器命名空间内")
    return (
        f"if = {{ limit = {{ NOT = {{ has_variable = {variable} }} }} "
        f"set_variable = {{ name = {variable} value = 0 }} }}\n"
        f"change_variable = {{ name = {variable} add = 1 }}"
    )


class CountryEvidence(TypedDict):
    risk_series: list[str]
    risk_observation_available: bool
    entry_observed: bool | None
    exit_after_entry: bool | None
    active_observed: bool | None


class Analysis(TypedDict):
    rows: list[dict[str, str]]
    counts: dict[str, int]
    countries: dict[str, CountryEvidence]
    behavior_causality: bool
    time_basis: str
    native_fiscal_inputs: NotRequired[dict]


def log(tag: str, kind: str, value: str) -> str:
    return f"debug_log = \"SITAI DECISION;{tag};{kind};{value};sample-[THIS.Var('{SAMPLE_VAR}').GetValue|0]\""


def _validate_tags(tags: tuple[str, ...]) -> None:
    if (
        len(tags) != 2
        or len(set(tags)) != len(tags)
        or any(not re.fullmatch(r"[A-Z]{3}", tag) for tag in tags)
    ):
        raise ValueError("财政探针需要两个不重复的三字母国家标签")


def on_actions(
    *, controlled: bool = False, inject: bool = True, tags: tuple[str, ...] = DEFAULT_TAGS
) -> str:
    _validate_tags(tags)
    subjects: list[str] = []
    for tag in tags:
        readings = "\n".join(
            f"if = {{ limit = {{ {trigger} }} {log(tag, kind, 'yes')} }} else = {{ {log(tag, kind, 'no')} }}"
            for kind, trigger in (
                ("DEFAULT", "in_default = yes"),
                ("LOANS", "taking_loans = yes"),
                ("WAR", "is_at_war = yes"),
                ("EXPOSURE", "sitai_external_exposure = yes"),
                ("CREDIT_POS", "credit > 0"),
                ("COMMITTED", "is_diplomatic_play_committed_participant = yes"),
                ("ENTRY", "sitai_fiscal_entry = yes"),
                ("HOLD", "sitai_fiscal_hold = yes"),
                ("RISK", f"has_variable = {decisions.RISK_VAR}"),
                ("ACTIVE", f"{decisions.ACTIVE_TRIGGER} = yes"),
            )
        )
        scalars = "\n".join(
            log(tag, kind, f"[THIS.GetCountry.{method}|v]")
            for kind, method in [
                ("PRINCIPAL", "GetPrincipal"),
                ("CREDIT", "GetMaxCredit"),
                ("RESERVES", "GetGoldReserves"),
                ("WEEKS", "GetWeeksUntilBankruptcy"),
            ]
        )
        setup = ""
        if controlled:
            target = {"RUS": "KRA", "PRU": "LIP"}.get(tag)
            setup = (
                f"""if = {{
    limit = {{ var:sitai_probe_month = 1 exists = c:{target} }}
    create_diplomatic_play = {{ name = sitai_probe_fiscal_play target_country = c:{target} type = dp_humiliation }}
    {log(tag, "CONTROL_PLAY", target)}
}}"""
                if target is not None
                else ""
            )
        injection = (
            f"""if = {{ limit = {{ var:sitai_probe_month = 2 }} add_treasury = -1000000000 {log(tag, "INJECT", "withdraw")} }}
    if = {{ limit = {{ var:sitai_probe_month = 6 }} add_treasury = 2000000000 {log(tag, "INJECT", "recover")} }}"""
            if inject
            else ""
        )
        subjects.append(f"""if = {{
    limit = {{ c:{tag} ?= this }}
    {sample_step(SAMPLE_VAR)}
    if = {{ limit = {{ NOT = {{ has_variable = sitai_probe_month }} }} set_variable = {{ name = sitai_probe_month value = 0 }} }}
    change_variable = {{ name = sitai_probe_month add = 1 }}
    {setup}
    {injection}
    sitai_update_fiscal = yes
    {readings}
    {scalars}
}}""")
    return (
        """# 由 pdx.decision_probe 生成；不是正式玩法。
on_monthly_pulse_country = { on_actions = { zz_sitai_decision_read } }
zz_sitai_decision_read = { effect = {
"""
        + "\n".join(subjects)
        + "\n} }\n"
    )


def build(
    *, controlled: bool = False, inject: bool = True, tags: tuple[str, ...] = DEFAULT_TAGS
) -> dict[str, str]:
    _validate_tags(tags)
    metadata = {
        "name": "SITAI 财政生命周期仪器",
        "id": "sitai.probe.decisions",
        "version": "1.0",
        "supported_game_version": decisions.load().game_version,
        "short_description": "隔离仪器：两国真实财政进入、恢复与生命周期",
        "tags": [],
        "relationships": [],
        "game_custom_data": {"multiplayer_synchronized": False},
    }
    return {
        "common/on_actions/zz_sitai_decision_probe.txt": on_actions(
            controlled=controlled, inject=inject, tags=tags
        ),
        ".metadata/metadata.json": json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        "localization/english/zz_sitai_decision_l_english.yml": 'l_english:\n sitai_probe_fiscal_play: "Fiscal lifecycle experiment"\n',
        "localization/simp_chinese/zz_sitai_decision_l_simp_chinese.yml": 'l_simp_chinese:\n sitai_probe_fiscal_play: "财政生命周期实验"\n',
    }


def build_observer(
    *,
    lifecycle: bool = False,
    tags: tuple[str, ...] = DEFAULT_TAGS,
    policy_state: bool = True,
    native_fiscal_inputs: bool = False,
) -> dict[str, str]:
    """只读状态；原版基线只读原生输入，不引用未挂载的生产变量。"""
    _validate_tags(tags)
    countries = []
    conditions = ((("RISK", f"has_variable = {decisions.RISK_VAR}"),) if policy_state else ()) + (
        ("DEFAULT", "in_default = yes"),
        ("LOANS", "taking_loans = yes"),
        ("WAR", "is_at_war = yes"),
    )
    if native_fiscal_inputs:
        policy = decisions.load()
        conditions += (
            ("NATIVE_CREDIT_POS", "credit > 0"),
            ("NATIVE_ENTRY", decisions.fiscal_condition(policy.entry_weeks)),
            ("NATIVE_HOLD", decisions.fiscal_condition(policy.exit_weeks)),
        )
    for tag in tags:
        readings = "\n".join(
            f"if = {{ limit = {{ {trigger} }} {log(tag, kind, 'yes')} }} else = {{ {log(tag, kind, 'no')} }}"
            for kind, trigger in conditions
        )
        if native_fiscal_inputs:
            readings += "\n" + log(
                tag, "NATIVE_WEEKS", "[THIS.GetCountry.GetWeeksUntilBankruptcy|3]"
            )
        countries.append(
            f"if = {{ limit = {{ c:{tag} ?= this }} {sample_step(SAMPLE_VAR)} {readings} }}"
        )
    files = build()
    metadata = json.loads(files[".metadata/metadata.json"])
    if lifecycle:
        metadata["short_description"] = "兼容固定存档的只读观察器"
    else:
        metadata["name"] = "SITAI 财政只读观察器"
    return {
        ".metadata/metadata.json": json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        "common/on_actions/zz_sitai_fiscal_observer.txt": "on_monthly_pulse_country = { on_actions = { zz_sitai_fiscal_observer } }\nzz_sitai_fiscal_observer = { effect = {\n"
        + "\n".join(countries)
        + "\n} }\n",
        **{name: text for name, text in files.items() if name.startswith("localization/")},
    }


def _validate_lifecycle(
    rows: list[dict[str, str]],
    *,
    countries: tuple[str, ...],
    policy_state: bool = True,
    native_fiscal_inputs: bool = False,
) -> None:
    """严格模式下拒绝缺国、缺月、重复月和跨缺失月份的退出判定。"""

    for tag in countries:
        country_rows = [row for row in rows if row["tag"] == tag]
        if not country_rows:
            raise ValueError(f"财政生命周期缺少国家观测：{tag}")
        samples: list[int] = []
        kind_samples: set[tuple[str, int]] = set()
        for row in country_rows:
            date = row["date"]
            if not date.startswith("sample-"):
                raise ValueError(f"财政生命周期缺少 sample-N 时间基准：{tag}")
            sample = int(date.removeprefix("sample-"))
            samples.append(sample)
            key = (row["kind"], sample)
            if key in kind_samples:
                raise ValueError(f"财政生命周期同类样本重复：{tag}/{row['kind']}/sample-{sample}")
            kind_samples.add(key)
        unique = sorted(set(samples))
        # 加载的检查点可能已有观察记录，因此计数器不必从一开始。
        # 从本局首次观察的序号起检查连续性，同时保留重复与缺口检测。
        expected = list(range(unique[0], unique[-1] + 1))
        if unique != expected:
            raise ValueError(f"财政生命周期样本不连续：{tag}，实际 {unique}")
        required: tuple[str, ...] = ("RISK",) if policy_state else ("DEFAULT", "LOANS", "WAR")
        if native_fiscal_inputs:
            required += NATIVE_KINDS
        for kind in required:
            kind_values = {
                int(row["date"].removeprefix("sample-"))
                for row in country_rows
                if row["kind"] == kind
            }
            if not kind_values:
                raise ValueError(f"财政生命周期缺少 {kind} 观测：{tag}")
            if kind_values != set(unique):
                missing = sorted(set(unique) - kind_values)
                raise ValueError(f"财政生命周期 {kind} 样本不连续：{tag}，缺少 {missing}")


def analyze(
    directory: Path,
    *,
    strict: bool = False,
    tags: tuple[str, ...] = DEFAULT_TAGS,
    policy_state: bool = True,
    native_fiscal_inputs: bool = False,
) -> Analysis:
    _validate_tags(tags)
    rows: list[dict[str, str]] = []
    for path in ga.rotated_logs(directory, "debug"):
        with path.open(encoding="utf-8-sig", errors="replace") as stream:
            for line in stream:
                if "SITAI DECISION;" not in line:
                    continue
                match = ROW.search(line.strip())
                if match is None:
                    raise ValueError("财政仪器行未完整解析")
                if match:
                    row = match.groupdict()
                    if native_fiscal_inputs and (
                        row["tag"] not in tags or row["kind"] not in NATIVE_ALLOWED_KINDS
                    ):
                        raise ValueError("原生财政输入出现未声明国家或字段")
                    row["value"] = (
                        re.sub(r"\x15[^;\x15]*;", "", row["value"]).replace("\x15!", "").strip()
                    )
                    if row["kind"] in BOOLEANS and row["value"] not in {"yes", "no"}:
                        raise ValueError("财政布尔读数未解析")
                    if row["kind"] in NATIVE_KINDS and not native_fiscal_inputs:
                        raise ValueError("未声明原生财政输入观测")
                    if row["kind"] == "NATIVE_WEEKS":
                        try:
                            number = float(row["value"].replace("−", "-").replace(",", "."))
                        except ValueError as exc:
                            raise ValueError("原生财政周数未解析") from exc
                        if not math.isfinite(number):
                            raise ValueError("原生财政周数非有限")
                    if row["date"].startswith("sample-") and not re.fullmatch(
                        r"sample-[1-9]\d*", row["date"]
                    ):
                        raise ValueError("财政采样序号无效")
                    rows.append(row)
    if not rows:
        raise ValueError("缺少本局财政观测，不能把空日志当无风险")
    if strict or native_fiscal_inputs:
        _validate_lifecycle(
            rows,
            countries=tags,
            policy_state=policy_state,
            native_fiscal_inputs=native_fiscal_inputs,
        )
    if not policy_state and any(row["kind"] in {"RISK", "ACTIVE"} for row in rows):
        raise ValueError("原版输入观察模式不能混入生产状态读数")
    counts = Counter(
        f"{r['tag']}:{r['kind']}:{r['value']}"
        for r in rows
        if r["kind"] in {"DEFAULT", "ENTRY", "RISK", "ACTIVE", "INJECT"}
    )
    countries: dict[str, CountryEvidence] = {}
    for tag in tags:
        risk_rows = [r for r in rows if r["tag"] == tag and r["kind"] == "RISK"]
        if strict:
            risk_rows.sort(key=lambda row: int(row["date"].removeprefix("sample-")))
        risk = [r["value"] for r in risk_rows]
        transitions = list(pairwise(risk))
        if strict:
            transitions = [
                (a["value"], b["value"])
                for a, b in pairwise(risk_rows)
                if int(b["date"].removeprefix("sample-"))
                == int(a["date"].removeprefix("sample-")) + 1
            ]
        countries[tag] = {
            "risk_series": risk,
            "risk_observation_available": bool(risk),
            "entry_observed": "yes" in risk if risk else None,
            "exit_after_entry": any(a == "yes" and b == "no" for a, b in transitions)
            if risk
            else None,
            "active_observed": any(
                r["value"] == "yes" for r in rows if r["tag"] == tag and r["kind"] == "ACTIVE"
            )
            if any(r["tag"] == tag and r["kind"] == "ACTIVE" for r in rows)
            else None,
        }
    result: Analysis = {
        "rows": rows,
        "counts": dict(counts),
        "countries": countries,
        "behavior_causality": False,
        "time_basis": "sample-N 是各国独立的每月观察序号，不是日历日期；历史日期字符串原样保留",
    }
    if native_fiscal_inputs:
        result["native_fiscal_inputs"] = {
            "rows": [row for row in rows if row["kind"] in NATIVE_KINDS],
            "scope": "只读取原版周数、信用及声明的进入/保持阈值条件；阈值定义在归档的观察器源中，不代表引擎 AI 风险政策。舍入后的周数不能独立证明精确阈值边界。",
            "production_risk_state_inferred": False,
            "active_inferred": False,
        }
    return result
