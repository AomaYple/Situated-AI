"""同一观察者检查点的零偏置/候选偏置外交行为对照。"""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import replace
from pathlib import Path

from pdx import behavior_probe, config, decision_probe, decisions, extension_probe, game_run
from pdx.experiment_evidence import OBSERVATION_VERSION
from pdx.experiment_queue import RunRequest
from pdx.parser import parse_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", type=Path, required=True)
    parser.add_argument(
        "--arm",
        choices=("control", "candidate", "neutrality", "aggression", "market-control", "market"),
        required=True,
    )
    parser.add_argument("--months", type=float, default=6)
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument(
        "--language",
        choices=game_run.ga.SESSION_LANGUAGES,
        help="显式冻结本局语言；正式实验必须声明",
    )
    parser.add_argument(
        "--natural-opportunity",
        action="store_true",
        help="只绑定首场自然博弈；正式对照使用资格证据，侦察限无注入 control",
    )
    parser.add_argument("--experiment-plan", default="m3a-exploration-20261010")
    parser.add_argument("--experiment-scene")
    parser.add_argument(
        "--purpose",
        choices=("reconnaissance", "instrument", "M3-A", "M3-B"),
        default="reconnaissance",
        help="正式行为目的必须提供独立处理前资格报告",
    )
    parser.add_argument("--qualification-report", type=Path)
    parser.add_argument(
        "--qualification-registration",
        type=Path,
        help="仪器准备局开始前归档冻结的资格观察登记，不自动构成正式资格",
    )
    parser.add_argument("--pair-index", type=int, default=1)
    parser.add_argument(
        "--keep-save",
        action="store_true",
        help="归档窗口结束后的 autosave.v3；用于制作单独登记的风险检查点，不构成因果样本",
    )
    parser.add_argument("--initiator", default="AUS", help="机会发起国；不能是观察国")
    parser.add_argument("--target", default="SAR", help="机会目标国；不能是观察国")
    parser.add_argument("--observers", nargs=2, default=("RUS", "PRU"))
    parser.add_argument(
        "--fiscal-injection",
        choices=("stress", "no-stress", "none"),
        help="正式模式固定 none；探索模式未指定时沿用 stress",
    )
    parser.add_argument(
        "--localization-baseline", action="store_true", help="隔离实验补原版中文缺键；不豁免错误"
    )
    args = parser.parse_args()
    formal = args.purpose in {"M3-A", "M3-B"}
    if args.fiscal_injection is None:
        args.fiscal_injection = "none" if formal else "stress"
    if formal and (
        args.qualification_report is None
        or args.fiscal_injection != "none"
        or args.keep_save
        or not args.experiment_scene
        or args.language is None
    ):
        parser.error(
            "正式实验需要 --qualification-report、--experiment-scene、--language，且固定 --fiscal-injection none；不能同时制作存档"
        )
    if formal and args.arm not in (
        {"control", "neutrality"} if args.purpose == "M3-A" else {"control", "aggression"}
    ):
        parser.error("正式实验每次只允许与目的匹配的单字段控制/候选差异")
    if not formal and args.qualification_report is not None:
        parser.error("资格报告只能用于显式正式目的 M3-A/M3-B")
    if formal and args.qualification_registration is not None:
        parser.error("正式实验使用既有资格，不能在处理局临时补写资格预登记")
    if args.qualification_registration is not None and (
        args.purpose != "instrument"
        or args.arm != "control"
        or args.fiscal_injection != "none"
        or not args.natural_opportunity
        or not args.experiment_scene
        or args.language is None
        or args.keep_save
    ):
        parser.error("资格准备需要 instrument、无注入自然 control、场景及语言；不能制作存档")
    if args.natural_opportunity and (
        args.fiscal_injection != "none" or (not formal and args.arm != "control")
    ):
        parser.error("自然响应侦察仅允许 --arm control --fiscal-injection none，不派候选或制造机会")
    if formal and not args.natural_opportunity:
        parser.error("正式模式只接受已验证的自然只读机会观察包，需要 --natural-opportunity")
    output = config.OUT / "decisions/behavior" / args.arm
    if (args.initiator, args.target) != ("AUS", "SAR"):
        output /= f"{args.initiator}-{args.target}"
    if args.fiscal_injection != "stress":
        output /= f"input-{args.fiscal_injection}"
    if args.natural_opportunity:
        output /= "natural"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".sources-", dir=output) as directory:
        return execute(args, output, Path(directory))


def execute(args: argparse.Namespace, output: Path, source_root: Path) -> int:
    purpose = getattr(args, "purpose", "reconnaissance")
    formal = purpose in {"M3-A", "M3-B"}
    if formal and (
        getattr(args, "qualification_report", None) is None
        or args.fiscal_injection != "none"
        or getattr(args, "keep_save", False)
        or not getattr(args, "experiment_scene", None)
        or not getattr(args, "natural_opportunity", False)
        or getattr(args, "language", None) is None
        or getattr(args, "qualification_registration", None) is not None
        or args.arm
        not in ({"control", "neutrality"} if purpose == "M3-A" else {"control", "aggression"})
    ):
        raise ValueError("正式实验缺少资格、身份或无注入自然观察约束")
    if getattr(args, "qualification_registration", None) is not None and (
        purpose != "instrument"
        or args.arm != "control"
        or args.fiscal_injection != "none"
        or not getattr(args, "natural_opportunity", False)
        or not getattr(args, "experiment_scene", None)
        or getattr(args, "language", None) is None
        or getattr(args, "keep_save", False)
    ):
        raise ValueError("资格准备缺少无注入自然 control、场景、语言或包含存档制作")
    candidate, fiscal, opportunity = (
        source_root / "candidate",
        source_root / "fiscal",
        source_root / "opportunity",
    )
    tags = tuple(args.observers)
    natural = getattr(args, "natural_opportunity", False)
    play_types: list[str] = []
    if natural:
        for path in sorted((config.GAME / "common/diplomatic_plays").glob("*.txt")):
            tree = parse_file(path)
            if tree.errors:
                raise ValueError(f"原版博弈类型无法解析：{path}")
            play_types.extend(key for key in tree.top_keys if key.startswith("dp_"))
    policy = decisions.load()
    if args.arm in {"control", "market", "market-control"}:
        policy = replace(policy, neutrality=0, aggression=0)
    elif args.arm == "neutrality":
        policy = replace(policy, aggression=0)
    elif args.arm == "aggression":
        policy = replace(policy, neutrality=0)
    market_readings = args.arm in {"market", "market-control"}
    extensions = replace(
        decisions.load_extensions(), market_enabled=args.arm == "market", reform_enabled=False
    )
    decisions.write(candidate, decisions.build(policy, extensions=extensions))
    decisions.write(
        fiscal,
        decision_probe.build(inject=args.fiscal_injection == "stress", tags=tags)
        if args.fiscal_injection in {"stress", "no-stress"}
        else decision_probe.build_observer(lifecycle=True, tags=tags),
    )
    decisions.write(
        opportunity,
        behavior_probe.build(
            initiator=args.initiator,
            target=args.target,
            tags=tags,
            market_readings=market_readings,
            natural=natural,
            play_types=tuple(play_types),
        ),
    )

    def analyze(logdir):
        return {
            "fiscal": decision_probe.analyze(logdir, strict=True, tags=tags),
            "opportunity": behavior_probe.analyze(
                logdir, tags=tags, natural_pair=(args.initiator, args.target) if natural else None
            ),
        }

    # 固定检查点的每个实验臂都记录两种财政探针身份。
    sources = {
        "sitai_decision_candidate": candidate,
        "zz_probe_decision_lifecycle": fiscal,
        "zz_probe_decision_opportunity": opportunity,
    }
    # ``none`` 禁用注入，但仍挂载只读观察器。
    readonly = source_root / "fiscal-readonly"
    decisions.write(readonly, decision_probe.build_observer(tags=tags))
    sources["zz_sitai_fiscal_observer"] = readonly
    # 各臂都保留自然检查点原只读仪器身份；不让观测源随输入实验改变。
    laws: list[str] = []
    for path in sorted((config.GAME / "common/laws").glob("*.txt")):
        tree = parse_file(path)
        if tree.errors:
            raise ValueError(f"原版法律无法解析：{path}")
        laws.extend(key for key in tree.top_keys if key.startswith("law_"))
    observer = source_root / "politics"
    decisions.write(
        observer,
        extension_probe.build(laws, strategies=extension_probe.political_keys(config.GAME)),
    )
    sources["zz_sitai_reform_observer"] = observer

    if getattr(args, "localization_baseline", False):
        baseline = source_root / "localization-baseline"
        decisions.write(baseline, decision_probe.build_localization_baseline(config.GAME))
        sources["zz_sitai_vanilla_localization_baseline"] = baseline

    report = game_run.run(
        sources,
        months=args.months,
        output=output,
        load_save=args.save,
        keep_save=getattr(args, "keep_save", False),
        timeout=getattr(args, "timeout", 3600),
        language=getattr(args, "language", None),
        analyze=analyze,
        experiment=RunRequest(
            plan_id=getattr(args, "experiment_plan", "m3a-exploration-20261010"),
            scene_id=getattr(args, "experiment_scene", None)
            or f"{'natural:' if natural else ''}{args.initiator}-{args.target}:{args.fiscal_injection}",
            arm=args.arm,
            pair=getattr(args, "pair_index", 1),
            purpose=purpose,
        ),
        qualification_report=getattr(args, "qualification_report", None),
        qualification_registration=getattr(args, "qualification_registration", None),
        qualification_context={
            "observers": list(tags),
            "initiator": args.initiator,
            "target": args.target,
            "fiscal_injection": args.fiscal_injection,
            "observation": {
                "package": "natural-response",
                "version": OBSERVATION_VERSION,
                "observers": list(tags),
                "initiator": args.initiator,
                "target": args.target,
                "extra_fiscal": True,
                "reform": True,
                "localization_baseline": getattr(args, "localization_baseline", False),
            },
        },
    )
    print(
        json.dumps(
            {
                key: report.get(key)
                for key in ("ok", "failure", "evidence", "progress", "cleanup_errors")
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
