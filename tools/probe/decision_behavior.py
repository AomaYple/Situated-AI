"""同一观察者检查点的零偏置/候选偏置外交行为对照。"""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import replace
from pathlib import Path

from pdx import behavior_probe, config, decision_probe, decisions, extension_probe, game_run
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
    output = config.OUT / "decisions/behavior" / args.arm
    if (args.initiator, args.target) != ("AUS", "SAR"):
        output /= f"{args.initiator}-{args.target}"
    if args.fiscal_injection != "stress":
        output /= f"input-{args.fiscal_injection}"
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
            initiator=args.initiator, target=args.target, tags=tags, market_readings=market_readings
        ),
    )

    def analyze(logdir):
        return {
            "fiscal": decision_probe.analyze(logdir, strict=True, tags=tags),
            "opportunity": behavior_probe.analyze(logdir, tags=tags),
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
        analyze=analyze,
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
