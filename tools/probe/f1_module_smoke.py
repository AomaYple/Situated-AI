"""运行单个新增七模块的 F1 实机启动诊断。

该入口只用来回答“单模块候选是否能被当前引擎挂载并完成观察者/后台推进/恢复”
以及“模块是否产生引擎日志错误”。它不注入机会、不创建战争、不修改原版安装，
也不把策略权重或脚本加载成功写成 AI 行为质量通过。
"""

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
    distribution,
    explanation_probe,
    game_run,
    resource_baseline,
)

MODULE_VARIANTS = ("economy", "diplomacy", "subjects")
DEFAULT_MONTHS = 0.1
DEFAULT_OUTPUT = config.OUT / "f1-module-smoke"


def _context(module: str, *, resource: bool, localization: bool) -> dict[str, Any]:
    diagnostic = resource or localization
    return {
        "schema": "sitai-f1-module-smoke-v1",
        "candidate": module,
        "candidate_kind": "diagnostic_candidate" if diagnostic else "production_candidate",
        "diagnostic_baselines": {"resource": resource, "localization": localization},
        "behavior_quality": "not_evaluated",
        "production_package": not diagnostic,
        "limits": (
            "单模块烟测只回答真实挂载、日志、自动化和恢复；不证明真实消费者作用域、"
            "AI 行为质量、解释 GUI、翻译质量、玩家路径、保存重载或长期性能。"
        ),
    }


def _write_sources(
    root: Path,
    module: str,
    *,
    resource: bool,
    localization: bool,
) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    policy, extensions, files = distribution.package_inputs(module)
    files = explanation_probe.attach(files, policy, extensions)
    candidate = root / f"sitai_{module}_f1"
    decisions.write(candidate, files)
    sources: dict[str, Path] = {f"sitai_{module}_f1": candidate}
    if resource:
        baseline = root / "zz_sitai_resource_baseline"
        resource_baseline.write(baseline, config.GAME)
        sources["zz_sitai_resource_baseline"] = baseline
    if localization:
        baseline = root / "zz_sitai_vanilla_localization_baseline"
        decisions.write(baseline, decision_probe.build_localization_baseline(config.GAME))
        sources["zz_sitai_vanilla_localization_baseline"] = baseline
    return sources


def run(
    module: str,
    *,
    months: float = DEFAULT_MONTHS,
    output: Path = DEFAULT_OUTPUT,
    resource: bool = False,
    localization: bool = False,
    timeout: float = 3600,
) -> dict[str, Any]:
    if module not in MODULE_VARIANTS:
        raise ValueError(f"不支持的单模块：{module}；可选：{', '.join(MODULE_VARIANTS)}")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    context = _context(module, resource=resource, localization=localization)
    with tempfile.TemporaryDirectory(prefix=".sources-", dir=output) as directory:
        sources = _write_sources(
            Path(directory), module, resource=resource, localization=localization
        )
        report = game_run.run(sources, months=months, timeout=timeout, output=output)
    evidence = Path(str(report["evidence"]))
    game_run.write_json(evidence / "f1_context.json", context)
    report["f1_context"] = context
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("module", choices=MODULE_VARIANTS)
    parser.add_argument("--months", type=float, default=DEFAULT_MONTHS)
    parser.add_argument("--timeout", type=float, default=3600.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--resource-baseline", action="store_true")
    parser.add_argument("--localization-baseline", action="store_true")
    args = parser.parse_args(argv)
    report = run(
        args.module,
        months=args.months,
        timeout=args.timeout,
        output=args.output / args.module,
        resource=args.resource_baseline,
        localization=args.localization_baseline,
    )
    print(
        json.dumps(
            {
                "ok": report.get("ok"),
                "failure": report.get("failure"),
                "evidence": report.get("evidence"),
                "candidate": report.get("f1_context", {}).get("candidate"),
                "candidate_kind": report.get("f1_context", {}).get("candidate_kind"),
                "behavior_quality": "not_evaluated",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
