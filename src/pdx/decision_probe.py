"""隔离的财政接口与生命周期实机仪器；注入仅存在于探针产物。"""

from __future__ import annotations

import json
import re
from collections import Counter
from itertools import pairwise
from typing import TYPE_CHECKING, TypedDict

from . import decisions
from . import game_auto as ga
from .localization import parse_loc_entries

if TYPE_CHECKING:
    from pathlib import Path

ROW = re.compile(
    r"SITAI DECISION;(?P<tag>RUS|PRU);(?P<kind>[A-Z_]+);(?P<value>.*);(?P<date>[^;]*)$"
)
SAMPLE_VAR = "sitai_probe_fiscal_sample"
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
    }
)
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
        "purpose": "diagnostic vanilla localization baseline; not production gameplay",
        "language": "l_simp_chinese",
        "keys": {key: found["l_english"][key][1] for key in missing},
        "already_present": sorted(BASELINE_LOC_KEYS - set(missing)),
        "limits": "English fallback text for verified missing vanilla keys; no engine error exemptions",
    }
    metadata = {
        "name": "SITAI vanilla localization baseline instrument",
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
    entry_observed: bool
    exit_after_entry: bool
    active_observed: bool


class Analysis(TypedDict):
    rows: list[dict[str, str]]
    counts: dict[str, int]
    countries: dict[str, CountryEvidence]
    behavior_causality: bool
    time_basis: str


def log(tag: str, kind: str, value: str) -> str:
    return f"debug_log = \"SITAI DECISION;{tag};{kind};{value};sample-[THIS.Var('{SAMPLE_VAR}').GetValue|0]\""


def on_actions(*, controlled: bool = False, inject: bool = True) -> str:
    subjects: list[str] = []
    for tag in ("RUS", "PRU"):
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
            target = "KRA" if tag == "RUS" else "LIP"
            setup = f"""if = {{
    limit = {{ var:sitai_probe_month = 1 exists = c:{target} }}
    create_diplomatic_play = {{ name = sitai_probe_fiscal_play target_country = c:{target} type = dp_humiliation }}
    {log(tag, "CONTROL_PLAY", target)}
}}"""
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


def build(*, controlled: bool = False, inject: bool = True) -> dict[str, str]:
    metadata = {
        "name": "SITAI fiscal lifecycle instrument",
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
            controlled=controlled, inject=inject
        ),
        ".metadata/metadata.json": json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        "localization/english/zz_sitai_decision_l_english.yml": 'l_english:\n sitai_probe_fiscal_play: "Fiscal lifecycle experiment"\n',
        "localization/simp_chinese/zz_sitai_decision_l_simp_chinese.yml": 'l_simp_chinese:\n sitai_probe_fiscal_play: "财政生命周期实验"\n',
    }


def build_observer() -> dict[str, str]:
    """只读生产状态；私有采样序号不注入财政或续期生产变量。"""
    countries = []
    for tag in ("RUS", "PRU"):
        readings = "\n".join(
            f"if = {{ limit = {{ {trigger} }} {log(tag, kind, 'yes')} }} else = {{ {log(tag, kind, 'no')} }}"
            for kind, trigger in (
                ("RISK", f"has_variable = {decisions.RISK_VAR}"),
                ("DEFAULT", "in_default = yes"),
                ("LOANS", "taking_loans = yes"),
                ("WAR", "is_at_war = yes"),
            )
        )
        countries.append(
            f"if = {{ limit = {{ c:{tag} ?= this }} {sample_step(SAMPLE_VAR)} {readings} }}"
        )
    files = build()
    return {
        ".metadata/metadata.json": files[".metadata/metadata.json"].replace(
            "fiscal lifecycle instrument", "fiscal read-only observer"
        ),
        "common/on_actions/zz_sitai_fiscal_observer.txt": "on_monthly_pulse_country = { on_actions = { zz_sitai_fiscal_observer } }\nzz_sitai_fiscal_observer = { effect = {\n"
        + "\n".join(countries)
        + "\n} }\n",
        **{name: text for name, text in files.items() if name.startswith("localization/")},
    }


def analyze(directory: Path) -> Analysis:
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
                    row["value"] = (
                        re.sub(r"\x15[^;\x15]*;", "", row["value"]).replace("\x15!", "").strip()
                    )
                    if row["kind"] in BOOLEANS and row["value"] not in {"yes", "no"}:
                        raise ValueError("财政布尔读数未解析")
                    if row["date"].startswith("sample-") and not re.fullmatch(
                        r"sample-[1-9]\d*", row["date"]
                    ):
                        raise ValueError("财政采样序号无效")
                    rows.append(row)
    if not rows:
        raise ValueError("缺少本局财政观测，不能把空日志当无风险")
    counts = Counter(
        f"{r['tag']}:{r['kind']}:{r['value']}"
        for r in rows
        if r["kind"] in {"DEFAULT", "ENTRY", "RISK", "ACTIVE", "INJECT"}
    )
    countries: dict[str, CountryEvidence] = {}
    for tag in ("RUS", "PRU"):
        risk = [r["value"] for r in rows if r["tag"] == tag and r["kind"] == "RISK"]
        countries[tag] = {
            "risk_series": risk,
            "entry_observed": "yes" in risk,
            "exit_after_entry": any(a == "yes" and b == "no" for a, b in pairwise(risk)),
            "active_observed": any(
                r["value"] == "yes" for r in rows if r["tag"] == tag and r["kind"] == "ACTIVE"
            ),
        }
    return {
        "rows": rows,
        "counts": dict(counts),
        "countries": countries,
        "behavior_causality": False,
        "time_basis": "sample-N is a per-country monthly observation sequence, not a calendar date; historical date strings remain unchanged",
    }
