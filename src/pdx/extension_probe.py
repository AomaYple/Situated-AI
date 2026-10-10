"""只读政治观测：全量法律目标、四个生命周期事件与月度处境。

脚本值自报只表示default新增贡献的重算，不冒充最终AI概率。
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import TYPE_CHECKING

from . import decision_probe, decisions, game_auto, political_approval
from .model import Block
from .parser import parse_file

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

ROW = re.compile(
    r"SITAI REFORM;(?P<tag>[A-Z]{3});(?P<kind>[A-Z_0-9]+);(?P<value>[^;]*);(?P<date>[^;]*)$"
)
LEGALITY_ROW = re.compile(
    r"SITAI REFORM;(?P<tag>[A-Z]{3});(?P<kind>LEGAL_BLOCKED|LEGAL_ENACTED);"
    r"(?P<law>law_[a-z0-9_]+)=(?P<value>yes|no|0|1);(?P<date>[^;]*)$"
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
ENACTMENT_DETAIL_NUMERIC = {"CHECKPOINT_SUCCESS", "CHECKPOINT_ADVANCE"}
ENACTMENT_DETAILS_UNAVAILABLE = (
    "进行中法律阶段概率观测已停用：1.14.5 实机触发 Interface 访问断言，"
    "注册 getter 不能据此用于只读脚本日志；重新验收前拒绝生成或运行。"
)


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
    legality_laws: Iterable[str] = (),
    enactment_details: bool = False,
    approval_igs: Iterable[str] = (),
    approval_laws: Iterable[str] = (),
) -> dict[str, str]:
    if enactment_details:
        raise ValueError(ENACTMENT_DETAILS_UNAVAILABLE)
    laws = sorted(set(laws))
    if not laws or any(not re.fullmatch(r"law_[a-z0-9_]+", law) for law in laws):
        raise ValueError("只读仪器必须提供规范的全量法律键")
    if (
        not tags
        or len(tags) != len(set(tags))
        or any(not re.fullmatch(r"[A-Z]{3}", tag) for tag in tags)
    ):
        raise ValueError("观察国标签无效或重复")
    legality_laws = sorted(set(legality_laws))
    approval_igs, approval_laws = political_approval.validate(approval_igs, approval_laws)
    if any(not re.fullmatch(r"law_[a-z0-9_]+", law) for law in legality_laws):
        raise ValueError("法律阻挡要求观察键无效")
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
        legality_readings = "\n".join(
            "\n".join(
                (
                    log(
                        "LEGAL_BLOCKED",
                        f"{law}=[Not(StringIsEmpty(GetLawType('{law}').GetBlockingRequirements(THIS.GetCountry.Self)))]",
                    ),
                    f"if = {{ limit = {{ has_law = law_type:{law} }} {log('LEGAL_ENACTED', f'{law}=yes')} }} else = {{ {log('LEGAL_ENACTED', f'{law}=no')} }}",
                )
            )
            for law in legality_laws
        )
        if approval_igs:
            legality_readings += "\n" + political_approval.readings(
                tag, approval_igs, approval_laws, SAMPLE_VAR
            )
        # 保留原可选读数所在的空行，使已验收的默认观测源指纹保持一致。
        readings.append(f"""if = {{ limit = {{ c:{tag} ?= this }}
            {decision_probe.sample_step(SAMPLE_VAR)}
            {log("COUNTRY_NAME", "[THIS.GetCountry.GetNameNoFormatting]")}
            {booleans}
            {""}
            {strategy_readings}
            {log("LEGITIMACY", "[THIS.GetCountry.GetGovernmentLegitimacy|3]")}
            {log("COMPUTED_DEFAULT_DELTA", "[THIS.GetCountry.MakeScope.ScriptValue('sitai_probe_reform_default_delta')|3]")}
            {legality_readings}
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
                "name": "SITAI 政治只读观察器",
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


def analyze(
    directory: Path,
    *,
    expected_tags: tuple[str, ...] = (),
    expected_laws: tuple[str, ...] = (),
    expected_approval_igs: tuple[str, ...] = (),
    expected_approval_laws: tuple[str, ...] = (),
) -> dict:
    rows = []
    approval_rows = []
    for path in game_auto.rotated_logs(directory, "debug"):
        with path.open(encoding="utf-8-sig", errors="replace") as stream:
            for line in stream:
                if political_approval.PREFIX in line:
                    approval_rows.append(political_approval.parse_row(line))
                    continue
                if "SITAI REFORM;" not in line:
                    continue
                legal_match = LEGALITY_ROW.search(line.rstrip())
                match = None if legal_match else ROW.search(line.rstrip())
                if legal_match is not None:
                    row = legal_match.groupdict()
                    row["value"] = {"1": "yes", "0": "no"}.get(row["value"], row["value"])
                    if row["date"].startswith("sample-") and not re.fullmatch(
                        r"sample-[1-9]\d*", row["date"]
                    ):
                        raise ValueError("政治采样序号无效")
                    rows.append(row)
                    continue
                if ";LEGAL_BLOCKED;" in line or ";LEGAL_ENACTED;" in line:
                    raise ValueError("法律资格读数未完整解析")
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
                    if row["kind"] == "ENACTING_LAW" and not re.fullmatch(
                        r"law_[a-z0-9_]+", row["value"]
                    ):
                        raise ValueError(f"进行中法律键未解析：{row}")
                    if row["kind"] in ENACTMENT_DETAIL_NUMERIC:
                        try:
                            number = float(row["value"].replace("−", "-").replace(",", "."))
                        except ValueError as exc:
                            raise ValueError(f"立法概率未解析：{row}") from exc
                        if not math.isfinite(number):
                            raise ValueError(f"立法概率非有限：{row}")
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
            "enacting_law_keys": [r["value"] for r in seen if r["kind"] == "ENACTING_LAW"],
            "checkpoint_success_values": [
                r["value"] for r in seen if r["kind"] == "CHECKPOINT_SUCCESS"
            ],
            "checkpoint_advance_values": [
                r["value"] for r in seen if r["kind"] == "CHECKPOINT_ADVANCE"
            ],
            "computed_delta_distribution": dict(
                Counter(r["value"] for r in seen if r["kind"] == "COMPUTED_DEFAULT_DELTA")
            ),
            "country_names": sorted({r["value"] for r in seen if r["kind"] == "COUNTRY_NAME"}),
            "legality": {
                law: {
                    "blocked_yes": sum(
                        r["kind"] == "LEGAL_BLOCKED" and r.get("law") == law and r["value"] == "yes"
                        for r in seen
                    ),
                    "blocked_no": sum(
                        r["kind"] == "LEGAL_BLOCKED" and r.get("law") == law and r["value"] == "no"
                        for r in seen
                    ),
                    "enacted_yes": sum(
                        r["kind"] == "LEGAL_ENACTED" and r.get("law") == law and r["value"] == "yes"
                        for r in seen
                    ),
                    "enacted_no": sum(
                        r["kind"] == "LEGAL_ENACTED" and r.get("law") == law and r["value"] == "no"
                        for r in seen
                    ),
                }
                for law in sorted({r["law"] for r in seen if r["kind"] == "LEGAL_BLOCKED"})
            },
        }
    legal_rows = [r for r in rows if r["kind"] == "LEGAL_BLOCKED"]
    legal_values = {r["value"] for r in legal_rows}
    # 预注册矩阵不能从已收到的行反推，否则整国/整法律漏采仍会伪装完整。
    issues: list[str] = []
    if not expected_tags or not expected_laws:
        issues.append("expected_matrix.missing")
    if (
        len(set(expected_tags)) != len(expected_tags)
        or any(not re.fullmatch(r"[A-Z]{3}", tag) for tag in expected_tags)
        or len(set(expected_laws)) != len(expected_laws)
        or any(not re.fullmatch(r"law_[a-z0-9_]+", law) for law in expected_laws)
    ):
        raise ValueError("法律资格预注册矩阵无效")
    blocked = Counter((r["tag"], r["date"], r["law"]) for r in legal_rows)
    enacted = Counter((r["tag"], r["date"], r["law"]) for r in rows if r["kind"] == "LEGAL_ENACTED")
    samples = {
        (r["tag"], r["date"])
        for r in rows
        if r["kind"]
        in BOOLEANS
        | {
            "COUNTRY_NAME",
            "LEGITIMACY",
            "LEGAL_BLOCKED",
            "LEGAL_ENACTED",
            "POLITICAL_STRATEGY",
            "COMPUTED_DEFAULT_DELTA",
        }
    }
    expected = {
        (tag, sample, law)
        for tag, sample in samples
        if tag in expected_tags
        for law in expected_laws
    }
    if set(expected_tags) != {tag for tag, _sample in samples}:
        issues.append("matrix.country_missing_or_unexpected")
    if not expected or set(blocked) != expected or set(enacted) != expected:
        issues.append("matrix.missing_or_unexpected_cells")
    if any(count != 1 for count in (*blocked.values(), *enacted.values())):
        issues.append("matrix.duplicate_cells")
    names = Counter(
        (r["tag"], r["date"])
        for r in rows
        if r["kind"] == "COUNTRY_NAME"
        and r["value"]
        and "[" not in r["value"]
        and "]" not in r["value"]
    )
    if any(names[tag, sample] != 1 for tag, sample, _law in expected):
        issues.append("matrix.country_name_missing_or_duplicate")
    if legal_values != {"yes", "no"}:
        issues.append("controls.yes_no_missing")
    result = {
        "rows": rows,
        "countries": countries,
        "legality_interface_validated": bool(legal_rows and not issues),
        "legality_validation": {
            "expected_tags": list(expected_tags),
            "expected_laws": list(expected_laws),
            "expected_cells": len(expected),
            "blocked_cells": len(blocked),
            "enacted_cells": len(enacted),
            "issues": issues,
            "country_identity_verified": False,
            "identity_basis": "名称从显式国家标签作用域读取；没有独立的标签与名称身份真值可供核对。",
        },
        "legality_scope": (
            "显式国家标签 × 请求的法律类型；阻断要求来自原版 GUI getter，已颁布状态由另一原版接口单独读取"
            if legal_rows
            else None
        ),
        "quality_improvement_proven": False,
        "time_basis": "sample-N 是各国独立的观察/事件序号，不是日历日期；历史日期字符串原样保留",
        "limits": "每月空闲观察不能证明存在可行法律。法律阻断只覆盖显式请求的国家 × 法律组合，且必须具备同局 yes/no 对照；它不代表最终 AI 可行性、成功概率或法律选择排名。政府偏好的可用法律和估算的推进阈值分桶只是部分条件。当前政治策略单独观察；条件最小值、方向与内战否决仍分别记录。计算的默认层贡献不代表引擎最终概率。通过、失败、结束分别记录；单局不能证明因果。",
    }
    if approval_rows or expected_approval_igs or expected_approval_laws:
        result["approval"] = political_approval.analyze(
            approval_rows,
            expected_tags=expected_tags,
            expected_igs=expected_approval_igs,
            expected_laws=expected_approval_laws,
            country_samples=[
                (r["tag"], r["date"], r["value"]) for r in rows if r["kind"] == "COUNTRY_NAME"
            ],
        )
    return result
