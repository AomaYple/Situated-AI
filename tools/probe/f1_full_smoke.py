"""运行 F1 七模块 ``full`` 候选的短实机烟测。

默认生成并挂载标准 ``full`` Mod，结果用于确认候选能否启动、进入观察者、用快捷键
``5`` 设置速度、用空格开始推进、切回后台并安全恢复。``--with-explanation-probe``
只在本次生成的标准 Mod 目录中临时附加解释探针；它不改变生产源，也不进入普通候选。
``--resource-baseline`` 和 ``--localization-baseline`` 只允许诊断环境使用：它们补齐
已确认的原版安装问题，不能进入生产包，也不能把无错误启动提升为 AI 行为质量通过。

脚本只负责生成本局临时源并调用现有 :mod:`pdx.game_run`；部署、互斥、日志、
进程、恢复和证据归档均由现有运行器负责。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

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

VARIANT = "full"
DEFAULT_MONTHS = 0.1
DEFAULT_OUTPUT = config.OUT / "f1-full-smoke"


def _context(
    *,
    resource: bool,
    localization: bool,
    with_explanation_probe: bool,
    language: str | None,
    load_save: Path | None,
) -> dict[str, Any]:
    diagnostic = resource or localization
    instrumented = with_explanation_probe and not diagnostic
    return {
        "schema": "sitai-f1-full-smoke-v1",
        "delivery_contract": distribution.generation_contract(
            variant=VARIANT, with_explanation_probe=with_explanation_probe
        ),
        "candidate": "full",
        "language": language,
        "loaded_observer": load_save is not None,
        "candidate_kind": (
            "diagnostic_candidate"
            if diagnostic
            else "instrumented_candidate"
            if instrumented
            else "production_candidate"
        ),
        "diagnostic_baselines": {
            "resource": resource,
            "localization": localization,
        },
        "standard_mod": True,
        "temporary_probe": "explanation" if with_explanation_probe else None,
        "behavior_quality": "not_evaluated",
        "production_package": not diagnostic and not with_explanation_probe,
        "limits": (
            "标准 Mod 运行只回答挂载、日志、自动化和恢复问题；临时探针只回答其声明的仪器问题；"
            "诊断基线运行只回答已知原版环境问题。"
            "两者都不能证明真实 AI 行为、消费者作用域、解释 GUI、语言质量、玩家路径、保存重载或长期性能。"
        ),
    }


def _write_sources(
    root: Path,
    *,
    resource: bool,
    localization: bool,
    with_explanation_probe: bool,
) -> dict[str, Path]:
    """在隔离临时目录内生成标准 Mod 和可选临时诊断源。"""

    root.mkdir(parents=True, exist_ok=True)
    policy, extensions, files = distribution.package_inputs(VARIANT)
    if with_explanation_probe:
        files = explanation_probe.attach(files, policy, extensions)
    candidate = root / distribution.INSTALL_DIRECTORY_NAME
    decisions.write(candidate, files)
    sources: dict[str, Path] = {distribution.INSTALL_DIRECTORY_NAME: candidate}

    if resource:
        resource_root = root / "zz_sitai_resource_baseline"
        resource_baseline.write(resource_root, config.GAME)
        sources["zz_sitai_resource_baseline"] = resource_root

    if localization:
        localization_root = root / "zz_sitai_vanilla_localization_baseline"
        decisions.write(
            localization_root,
            decision_probe.build_localization_baseline(config.GAME),
        )
        sources["zz_sitai_vanilla_localization_baseline"] = localization_root

    return sources


def run(
    *,
    months: float = DEFAULT_MONTHS,
    output: Path = DEFAULT_OUTPUT,
    resource: bool = False,
    localization: bool = False,
    with_explanation_probe: bool = False,
    language: str | None = None,
    load_save: Path | None = None,
    timeout: float = 3600,
) -> dict[str, Any]:
    """运行一次 F1 烟测并返回现有运行器报告。"""

    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    context = _context(
        resource=resource,
        localization=localization,
        with_explanation_probe=with_explanation_probe,
        language=language,
        load_save=load_save,
    )
    with tempfile.TemporaryDirectory(prefix=".sources-", dir=output) as directory:
        sources = _write_sources(
            Path(directory),
            resource=resource,
            localization=localization,
            with_explanation_probe=with_explanation_probe,
        )
        report = game_run.run(
            sources,
            months=months,
            timeout=timeout,
            output=output,
            language=language,
            load_save=load_save,
        )
    evidence = Path(str(report["evidence"]))
    game_run.write_json(evidence / "f1_context.json", context)
    report["f1_context"] = context
    return cast("dict[str, Any]", report)


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    session = report.get("session")
    findings = report.get("log_findings")
    return {
        "ok": report.get("ok"),
        "failure": report.get("failure"),
        "evidence": report.get("evidence"),
        "candidate_kind": report.get("f1_context", {}).get("candidate_kind"),
        "diagnostic_baselines": report.get("f1_context", {}).get("diagnostic_baselines"),
        "mod_errors": findings.get("mod_errors", []) if isinstance(findings, dict) else [],
        "engine_errors": findings.get("errors", {}) if isinstance(findings, dict) else {},
        "unclassified_errors": (
            findings.get("unclassified_errors", []) if isinstance(findings, dict) else []
        ),
        "automation_phase": session.get("automation_phase") if isinstance(session, dict) else None,
        "speed_source": session.get("speed_source") if isinstance(session, dict) else None,
        "speed_ok": session.get("speed_ok") if isinstance(session, dict) else None,
        "cleanup_errors": report.get("cleanup_errors", []),
        "behavior_quality": "not_evaluated",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", type=float, default=DEFAULT_MONTHS)
    parser.add_argument("--timeout", type=float, default=3600.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--load-save",
        type=Path,
        help="从已验证的观察者检查点启动；英语会话必须使用此选项",
    )
    parser.add_argument(
        "--language",
        choices=game_run.ga.SESSION_LANGUAGES,
        help="显式冻结本局界面语言；只覆盖支持的自动化语言模板",
    )
    parser.add_argument(
        "--with-explanation-probe",
        action="store_true",
        help="在本次标准 Mod 中临时附加未验收的只读解释探针；验证结束后随临时部署清理",
    )
    parser.add_argument(
        "--resource-baseline",
        action="store_true",
        help="挂载已确认的原版维修图标诊断源；不能进入生产包",
    )
    parser.add_argument(
        "--localization-baseline",
        action="store_true",
        help="挂载已确认的原版中文缺键诊断源；不能进入生产包",
    )
    args = parser.parse_args(argv)
    report = run(
        months=args.months,
        timeout=args.timeout,
        output=args.output,
        language=args.language,
        load_save=args.load_save,
        with_explanation_probe=args.with_explanation_probe,
        resource=args.resource_baseline,
        localization=args.localization_baseline,
    )
    print(json.dumps(_summary(report), ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
