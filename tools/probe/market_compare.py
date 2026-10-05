"""同检查点市场支持两臂：核依赖输入、有限评分方向与行为证据边界。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from dataclasses import replace
from pathlib import Path

from pdx import decisions, game_run

# 实机Getter即使请求|3仍返回整数。采用保守截断界，未假定引擎就近舍入。
SCORE_QUANTUM = 1.0
DEPENDENCY_QUANTUM = 0.001


def compare(control: dict, treatment: dict) -> dict:
    for report in (control, treatment):
        game_run.require_clean_report(report)
    digest = control.get("loaded_save", {}).get("sha256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or digest != treatment.get("loaded_save", {}).get(
        "sha256"
    ):
        raise ValueError("需要同一完整检查点指纹")
    if control.get("game_version") != treatment.get("game_version"):
        raise ValueError("游戏版本不一致")
    policy = replace(decisions.load(), neutrality=0, aggression=0)
    extensions = decisions.load_extensions()
    left, right = (r["source_hashes"] for r in (control, treatment))
    if left.keys() != right.keys():
        raise ValueError("启用集合不一致")
    for name in left:
        if name != "sitai_decision_candidate":
            if left[name] != right[name]:
                raise ValueError("市场以外的仪器发生变化")
            continue
        for actual, enabled in ((left[name], False), (right[name], True)):
            files = decisions.build(
                policy, extensions=replace(extensions, reform_enabled=False, market_enabled=enabled)
            )
            expected_hashes = {
                key: hashlib.sha256(text.encode("utf-8")).hexdigest() for key, text in files.items()
            }
            if actual != expected_hashes:
                raise ValueError("候选存在未声明的源差异")
    analyses = [r["analysis"]["opportunity"] for r in (control, treatment)]
    indexes = [
        {(row["tag"], row["date"], row["kind"]): row["value"] for row in a["rows"]}
        for a in analyses
    ]
    countries = {}
    for tag in analyses[0]["countries"]:
        observed: list[dict] = []
        unexplained: list[dict] = []
        unresolved: list[dict] = []
        matched = 0
        dates = {row["date"] for row in analyses[0]["rows"] if row["tag"] == tag}
        for date in sorted(dates):

            def value(index, kind, *, tag=tag, date=date):
                raw = indexes[index].get((tag, date, kind))
                if raw is None:
                    return None
                number = float(raw.replace("−", "-").replace(",", "."))
                if not math.isfinite(number):
                    raise ValueError("读数必须是有限数")
                return number

            eligible = all(
                m.get((tag, date, "UNDECIDED")) == "yes"
                and any(m.get((tag, date, key)) == "yes" for key in ("CAN_INIT", "CAN_TARGET"))
                for m in indexes
            )
            deps = [[value(i, k) for k in ("DEPENDENCY_INIT", "DEPENDENCY_TARGET")] for i in (0, 1)]
            if not eligible or any(v is None for pair in deps for v in pair):
                continue
            if any(abs(a - b) > 0.001 for a, b in zip(*deps, strict=True)):
                continue
            expected = decisions.market_delta(*deps[0], multiplier=extensions.market_multiplier)
            # 两臂整数差分误差<2；两项依赖各误差<.001，最大两倍margin传播。
            tolerance = (
                2 * SCORE_QUANTUM + 4 * abs(extensions.market_multiplier) * DEPENDENCY_QUANTUM
            )
            if abs(expected) <= tolerance:
                unresolved.append({"date": date, "default_support_delta": expected})
                continue
            scores = [[value(i, k) for k in ("INIT_SCORE", "TARGET_SCORE")] for i in (0, 1)]
            if any(v is None for pair in scores for v in pair):
                continue
            matched += 1
            deltas = [b - a for a, b in zip(*scores, strict=True)]
            valid = all(
                delta * change > 0
                and abs(delta) > 2 * SCORE_QUANTUM
                and min(change, 2 * change) - tolerance
                <= delta
                <= max(change, 2 * change) + tolerance
                for change, delta in zip((expected, -expected), deltas, strict=True)
            )
            (observed if valid else unexplained).append(
                {
                    "date": date,
                    "dependencies": deps[0],
                    "default_support_delta": expected,
                    "margin_deltas": deltas,
                }
            )
        countries[tag] = {
            "matching_eligible_dates": matched,
            "expected_direction": observed,
            "unexplained": unexplained,
            "below_measurement_resolution": unresolved,
            "control_behavior": analyses[0]["countries"][tag],
            "treatment_behavior": analyses[1]["countries"][tag],
        }
    return {
        "checkpoint_sha256": digest,
        "countries": countries,
        "two_country_score_effect_observed": len(countries) >= 2
        and all(c["expected_direction"] and not c["unexplained"] for c in countries.values()),
        "quality_improvement_proven": False,
        "measurement_model": {
            "score_quantum": SCORE_QUANTUM,
            "dependency_quantum": DEPENDENCY_QUANTUM,
            "rounding": "conservative truncation error bound; exact engine rounding is unverified",
            "minimum_visible_effect": "theoretical effect exceeds total error bound; both signed observed margins exceed 2 score units",
        },
        "limits": "Preference margin subtracts the larger of other-side support and neutrality; one support delta may yield between one and two times that margin delta. Integer Getter and dependence quantization are bounded conservatively. Matched rounded dependence inputs and directional agreement do not prove overall behavior quality.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--treatment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(
        *(game_run.read_reviewed_report(path) for path in (args.control, args.treatment))
    )
    game_run.write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
