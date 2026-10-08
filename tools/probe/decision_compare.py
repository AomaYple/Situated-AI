"""核对固定存档两臂的真实外交评分差分；评分效果与行为质量分开。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from pdx import decision_probe, decisions, game_run


@lru_cache(maxsize=4)
def _strategy_hashes(policy: decisions.Policy, baseline: str) -> dict[str, tuple[float, float]]:
    result = {}
    for neutrality, aggression in (
        (0, 0),
        (policy.neutrality, 0),
        (0, policy.aggression),
        (policy.neutrality, policy.aggression),
    ):
        text = decisions.patch_default(
            baseline,
            replace(policy, neutrality=neutrality, aggression=aggression),
        )
        result[hashlib.sha256(text.encode("utf-8")).hexdigest()] = neutrality, aggression
    return result


def strategy_amounts(digest: str) -> tuple[float, float]:
    """只接受锁定底本上生成的四个实验臂，拒绝其他默认策略改动。"""
    amounts = _strategy_hashes(
        decisions.load(), decisions.BASELINE.read_text(encoding="utf-8")
    ).get(digest)
    if amounts is not None:
        return amounts
    raise ValueError("默认策略并非已声明实验臂；拒绝混入额外改动")


def paired_sources(control: dict, treatment: dict) -> list[dict]:
    """两类配对共享版本、完整检查点与挂载来源契约。"""
    for report in (control, treatment):
        game_run.require_clean_report(report)
    mount_lists = [report.get("mount_allowlist") for report in (control, treatment)]
    if any(value is not None for value in mount_lists):
        if not all(
            isinstance(value, list) and all(isinstance(item, str) for item in value)
            for value in mount_lists
        ):
            raise ValueError("两臂必须记录完整挂载允许清单")
        normalized = [
            tuple(sorted(item.casefold() for item in value))
            for value in mount_lists
            if isinstance(value, list)
        ]
        if normalized[0] != normalized[1]:
            raise ValueError("两臂基础内容与探针的挂载允许清单必须一致")
    left, right = control.get("loaded_save", {}), treatment.get("loaded_save", {})
    if (
        not isinstance(left.get("sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", left["sha256"])
        or left.get("sha256") != right.get("sha256")
    ):
        raise ValueError("两臂必须记录相同检查点的完整 SHA-256")
    if control.get("game_version") != treatment.get("game_version"):
        raise ValueError("两臂游戏版本不一致")
    sources = [r["source_hashes"] for r in (control, treatment)]
    if any("sitai_decision_candidate" not in source for source in sources):
        raise ValueError("两臂必须包含已声明的候选决策产物")
    if sources[0].keys() != sources[1].keys():
        raise ValueError("两臂启用的 mod 不一致")
    return sources


def compare(control: dict, treatment: dict, *, neutrality_delta: float = 25) -> dict:
    if not math.isfinite(neutrality_delta) or not 0 < neutrality_delta <= 100:
        raise ValueError("neutrality 差分必须是0到100之间的有限正数")
    sources = paired_sources(control, treatment)
    for name in sources[0]:
        if name == "sitai_decision_candidate":
            a, b = dict(sources[0][name]), dict(sources[1][name])
            amounts = [
                strategy_amounts(m.pop("common/ai_strategies/00_default_strategy.txt", ""))
                for m in (a, b)
            ]
            if amounts[1][0] - amounts[0][0] != neutrality_delta or amounts[0][1] != amounts[1][1]:
                raise ValueError("本配对只接受 neutrality 单字段差分，aggression 必须一致")
        else:
            a, b = sources[0][name], sources[1][name]
        if a != b:
            raise ValueError(f"两臂存在非策略字段差异：{name}")
    analyses = [r["analysis"]["opportunity"] for r in (control, treatment)]
    tags = sorted(analyses[0]["countries"])
    if (
        len(tags) != 2
        or any(not re.fullmatch(r"[A-Z]{3}", tag) for tag in tags)
        or set(tags) != set(analyses[1]["countries"])
    ):
        raise ValueError("两臂必须观察相同的两个规范国家标签")
    indexes = []
    for analysis in analyses:
        index: dict[tuple[str, str, str], str] = {}
        for row in analysis["rows"]:
            key = row["tag"], row["date"], row["kind"]
            if key in index and index[key] != row["value"]:
                raise ValueError(f"同一评分采样键存在冲突：{key}")
            index[key] = row["value"]
        indexes.append(index)
    countries = {}
    for tag in tags:
        active_deltas: Counter[str] = Counter()
        inactive_deltas: Counter[str] = Counter()
        post_exit_deltas: Counter[str] = Counter()
        active_seen = False
        dates = set()
        for key, raw in indexes[0].items():
            if (
                key[0] != tag
                or key[2] not in {"INIT_SCORE", "TARGET_SCORE"}
                or key not in indexes[1]
            ):
                continue
            date = key[1]
            states = [m.get((tag, date, "ACTIVE")) for m in indexes]
            if states == ["yes", "yes"]:
                active_seen = True
            side = "CAN_INIT" if key[2] == "INIT_SCORE" else "CAN_TARGET"
            eligible = all(
                m.get((tag, date, "UNDECIDED")) == "yes" and m.get((tag, date, side)) == "yes"
                for m in indexes
            )
            delta = float(indexes[1][key].replace("−", "-").replace(",", ".")) - float(
                raw.replace("−", "-").replace(",", ".")
            )
            if states == ["yes", "yes"] and eligible:
                active_deltas[str(delta)] += 1
                dates.add(date)
            elif states == ["no", "no"]:
                inactive_deltas[str(delta)] += 1
                if active_seen:
                    post_exit_deltas[str(delta)] += 1
        countries[tag] = {
            "eligible_active_dates": sorted(dates),
            "active_score_deltas": dict(active_deltas),
            "inactive_score_deltas": dict(inactive_deltas),
            "post_exit_score_deltas": dict(post_exit_deltas),
            "exit_effect_status": (
                "not_observed"
                if not post_exit_deltas
                else "zero_difference"
                if set(post_exit_deltas) == {"0.0"}
                else "residual_difference"
            ),
            "inactive_effect_status": (
                "not_observed"
                if not inactive_deltas
                else "zero_difference"
                if set(inactive_deltas) == {"0.0"}
                else "residual_difference"
            ),
            "expected_score_effect_observed": (
                active_deltas[str(-float(neutrality_delta))] > 0
                and set(active_deltas) <= {"0.0", str(-float(neutrality_delta))}
            ),
            "control_behavior": analyses[0]["countries"][tag],
            "treatment_behavior": analyses[1]["countries"][tag],
        }
    return {
        "control_evidence": control["evidence"],
        "treatment_evidence": treatment["evidence"],
        "checkpoint_sha256": control["loaded_save"]["sha256"],
        "neutrality_delta": neutrality_delta,
        "countries": countries,
        "two_country_score_effect_observed": all(
            c["expected_score_effect_observed"] for c in countries.values()
        ),
        "two_country_exit_effect_observed": all(
            c["exit_effect_status"] == "zero_difference" for c in countries.values()
        ),
        "quality_improvement_proven": False,
        "limits": "One controlled opportunity per run. Dates and score rows are repeated observations, not independent behavior samples. Only the declared neutrality field changes; native simulation randomness remains uncontrolled.",
    }


def compare_inputs(control: dict, treatment: dict) -> dict:
    """财政单输入实验：注入改变真实世界，状态差分不等于策略行为收益。"""
    sources = paired_sources(control, treatment)
    instrument = "zz_probe_decision_lifecycle"
    if any(instrument not in source for source in sources):
        raise ValueError("财政输入对照必须包含同一生命周期仪器")
    for source, stress in zip(sources, (False, True), strict=True):
        expected = {
            name: hashlib.sha256(text.encode("utf-8")).hexdigest()
            for name, text in decision_probe.build(inject=stress).items()
        }
        if source[instrument] != expected:
            raise ValueError("财政输入必须是声明的无注入/压力注入两臂，拒绝其他脚本改动")
    for name in sources[0]:
        if name != instrument and sources[0][name] != sources[1][name]:
            raise ValueError(f"财政输入实验存在其他来源差异：{name}")
    analyses = [report["analysis"]["fiscal"]["countries"] for report in (control, treatment)]
    if any(set(analysis) != {"RUS", "PRU"} for analysis in analyses):
        raise ValueError("财政输入实验必须完整观察RUS和PRU")
    for report in (control, treatment):
        rows = report["analysis"]["fiscal"].get("rows", [])
        if any(
            not any(row["tag"] == tag and row["kind"] == "RISK" for row in rows)
            for tag in ("RUS", "PRU")
        ):
            raise ValueError("两臂各国都必须有真实风险观测，不能把缺失当无风险")
    countries = {
        tag: {
            "control": analyses[0][tag],
            "stress": analyses[1][tag],
            "risk_input_effect_observed": (
                not analyses[0][tag]["entry_observed"] and analyses[1][tag]["entry_observed"]
            ),
        }
        for tag in ("RUS", "PRU")
    }
    return {
        "control_evidence": control["evidence"],
        "treatment_evidence": treatment["evidence"],
        "checkpoint_sha256": control["loaded_save"]["sha256"],
        "policy_unchanged": True,
        "countries": countries,
        "two_country_fiscal_input_effect_observed": all(
            country["risk_input_effect_observed"] for country in countries.values()
        ),
        "quality_improvement_proven": False,
        "limits": "Only the declared treasury withdrawal/recovery instrument differs. This changes real finances and can change native world behavior; risk activation is not an isolated policy score or behavior-quality effect. Native randomness remains uncontrolled.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--treatment", type=Path, required=True)
    parser.add_argument("--neutrality-delta", type=float, default=25)
    parser.add_argument("--mode", choices=("neutrality", "fiscal-input"), default="neutrality")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reports = [game_run.read_reviewed_report(p) for p in (args.control, args.treatment)]
    result = (
        compare_inputs(*reports)
        if args.mode == "fiscal-input"
        else compare(*reports, neutrality_delta=args.neutrality_delta)
    )
    game_run.write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
