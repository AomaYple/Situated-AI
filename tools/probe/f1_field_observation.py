"""运行 F1 四个新增策略字段的隔离 Windows 实机诊断。"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from pdx import (
    config,
    decision_probe,
    decisions,
    f1_field_probe,
    game_run,
    resource_baseline,
)

DEFAULT_OUTPUT = config.OUT / "f1-field-observation"


def _context(field: str, arm: str, *, resource: bool, localization: bool) -> dict[str, Any]:
    spec = f1_field_probe.validate(field, arm)
    return {
        "schema": "sitai-f1-field-observation-v1",
        "field": field,
        "module": spec.module,
        "arm": arm,
        "control_value": spec.control,
        "candidate_value": spec.candidate,
        "expected_direction": spec.expected_direction,
        "diagnostic_baselines": {"resource": resource, "localization": localization},
        "runtime_field_value": "unavailable",
        "behavior_quality": "not_evaluated",
        "limits": [
            "字段没有通用脚本 getter；策略持有状态不能证明真实消费者读取。",
            spec.behavior_window,
        ],
    }


def _write_sources(
    root: Path,
    field: str,
    arm: str,
    *,
    resource: bool,
    localization: bool,
) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    probe = root / f"{f1_field_probe.PROBE_MOD}_{field}_{arm}"
    decisions.write(probe, f1_field_probe.build(field, arm))
    sources: dict[str, Path] = {probe.name: probe}
    if resource:
        baseline = root / "zz_sitai_resource_baseline"
        resource_baseline.write(baseline, config.GAME)
        sources[baseline.name] = baseline
    if localization:
        baseline = root / "zz_sitai_vanilla_localization_baseline"
        decisions.write(baseline, decision_probe.build_localization_baseline(config.GAME))
        sources[baseline.name] = baseline
    return sources


def _analyze(field: str, arm: str, directory: Path) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    for path in game_run.ga.rotated_logs(directory, "debug"):
        rows.extend(
            f1_field_probe.parse_rows(path.read_text(encoding="utf-8-sig", errors="replace"))
        )
    return f1_field_probe.summarize(tuple(rows), field=field, arm=arm)


def compare_reports(control_report: Path, candidate_report: Path) -> dict[str, Any]:
    """从两份已收口报告生成保守的控制/候选配对摘要。"""

    control = json.loads(control_report.read_text(encoding="utf-8"))
    candidate = json.loads(candidate_report.read_text(encoding="utf-8"))
    return f1_field_probe.compare_summaries(control["analysis"], candidate["analysis"])


def run(
    field: str,
    arm: str,
    *,
    months: float = 0.1,
    output: Path = DEFAULT_OUTPUT,
    resource: bool = False,
    localization: bool = False,
    timeout: float = 3600,
) -> dict[str, Any]:
    f1_field_probe.validate(field, arm)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    context = _context(field, arm, resource=resource, localization=localization)
    with tempfile.TemporaryDirectory(prefix=".sources-", dir=output) as directory:
        sources = _write_sources(
            Path(directory), field, arm, resource=resource, localization=localization
        )
        report = game_run.run(
            sources,
            months=months,
            timeout=timeout,
            output=output,
            analyze=lambda logdir: _analyze(field, arm, logdir),
        )
    evidence = Path(str(report["evidence"]))
    game_run.write_json(evidence / "f1_context.json", context)
    report["f1_context"] = context
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("field", choices=f1_field_probe.FIELDS, nargs="?")
    parser.add_argument("arm", choices=f1_field_probe.ARMS, nargs="?")
    parser.add_argument("--months", type=float, default=0.1)
    parser.add_argument("--timeout", type=float, default=3600.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--resource-baseline", action="store_true")
    parser.add_argument("--localization-baseline", action="store_true")
    parser.add_argument("--compare-control-report", type=Path)
    parser.add_argument("--compare-candidate-report", type=Path)
    args = parser.parse_args(argv)
    if bool(args.compare_control_report) != bool(args.compare_candidate_report):
        parser.error("控制/候选报告必须同时提供")
    if args.compare_control_report:
        print(
            json.dumps(
                compare_reports(args.compare_control_report, args.compare_candidate_report),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.field is None or args.arm is None:
        parser.error("运行字段观测时必须提供 field 和 arm")
    report = run(
        args.field,
        args.arm,
        months=args.months,
        timeout=args.timeout,
        output=args.output / args.field / args.arm,
        resource=args.resource_baseline,
        localization=args.localization_baseline,
    )
    print(
        json.dumps(
            {
                "ok": report.get("ok"),
                "failure": report.get("failure"),
                "evidence": report.get("evidence"),
                "field": args.field,
                "arm": args.arm,
                "analysis": report.get("analysis"),
                "behavior_quality": "not_evaluated",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
