"""同一观察者检查点的零偏置/候选偏置外交行为对照。"""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import replace
from pathlib import Path

from pdx import behavior_probe, config, decision_probe, decisions, extension_probe, game_run
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
        "--natural-opportunity",
        action="store_true",
        help="只绑定首场自然博弈；仅限无注入 control 仪器",
    )
    parser.add_argument("--experiment-plan", default="m3a-exploration-20261010")
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
        "--fiscal-injection", choices=("stress", "no-stress", "none"), default="stress"
    )
    parser.add_argument(
        "--localization-baseline", action="store_true", help="隔离实验补原版中文缺键；不豁免错误"
    )
    args = parser.parse_args()
    if args.natural_opportunity and (args.arm != "control" or args.fiscal_injection != "none"):
        parser.error("自然响应侦察仅允许 --arm control --fiscal-injection none，不派候选或制造机会")
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

    # Fixed checkpoints record both fiscal probe identities for every arm.
    sources = {
        "sitai_decision_candidate": candidate,
        "zz_probe_decision_lifecycle": fiscal,
        "zz_probe_decision_opportunity": opportunity,
    }
    # ``none`` disables injection but still mounts the read-only observer.
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
        analyze=analyze,
        experiment=RunRequest(
            plan_id=getattr(args, "experiment_plan", "m3a-exploration-20261010"),
            scene_id=f"{'natural:' if natural else ''}{args.initiator}-{args.target}:{args.fiscal_injection}",
            arm=args.arm,
            pair=getattr(args, "pair_index", 1),
        ),
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
