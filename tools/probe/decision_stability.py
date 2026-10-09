"""自然观察者局或固定存档的长期/后期稳定性与政治扩展实验。"""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import replace
from pathlib import Path

from pdx import config, decision_probe, decisions, extension_probe, game_run, natural_probe
from pdx.parser import parse_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--arm",
        choices=(
            "vanilla",
            "fiscal",
            "reform",
            "combined",
            "reform-positive-control",
            "reform-global-positive-control",
        ),
        required=True,
    )
    parser.add_argument("--months", type=float, default=120)
    parser.add_argument("--save", type=Path)
    parser.add_argument("--keep-save", action="store_true")
    parser.add_argument("--timeout", type=float, default=21600)
    parser.add_argument("--allow-save-upgrade", action="store_true")
    parser.add_argument("--profile", action="store_true", help="采集后台窗口的引擎逐帧任务计时")
    parser.add_argument(
        "--localization-baseline", action="store_true", help="隔离实验补原版中文缺键；不豁免错误"
    )
    parser.add_argument(
        "--natural-diplomacy", action="store_true", help="只读记录自然发起事实；不创建博弈"
    )
    parser.add_argument(
        "--natural-tags",
        default=",".join(natural_probe.DEFAULT_TAGS),
        help="自然外交观察国标签，逗号分隔，至少两个（默认 RUS,PRU）",
    )
    parser.add_argument(
        "--natural-targets",
        default="",
        help="实验性只读 dp_humiliation 命令合法性目标，逗号分隔；需要 --natural-diplomacy",
    )
    parser.add_argument(
        "--legality-laws",
        default="",
        help="实验性只读显式国家×法律阻挡要求，法律键逗号分隔",
    )
    parser.add_argument(
        "--legality-tags",
        default="RUS,FRA",
        help="法律阻挡要求观察国标签，逗号分隔（默认 RUS,FRA）",
    )
    parser.add_argument(
        "--enactment-details",
        action="store_true",
        help="只读记录自然进行中法律键及当前 checkpoint 成功/推进概率",
    )
    args = parser.parse_args()
    if args.natural_targets and not args.natural_diplomacy:
        parser.error("--natural-targets 需要 --natural-diplomacy")
    if args.legality_laws and not args.legality_tags:
        parser.error("--legality-laws 需要 --legality-tags")
    laws: list[str] = []
    for path in sorted((config.GAME / "common/laws").glob("*.txt")):
        tree = parse_file(path)
        if tree.errors:
            raise ValueError(f"原版法律无法解析：{path}")
        laws.extend(key for key in tree.top_keys if key.startswith("law_"))
    output = config.OUT / "decisions/stability" / args.arm
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".sources-", dir=output) as directory:
        return execute(args, laws, output, Path(directory))


def execute(args: argparse.Namespace, laws: list[str], output: Path, source_root: Path) -> int:
    positive_control = args.arm in {"reform-positive-control", "reform-global-positive-control"}
    global_control = args.arm == "reform-global-positive-control"
    observer, fiscal = source_root / "politics", source_root / "fiscal-observer"
    # 固定检查点可能来自旧版生命周期实验，并在存档元数据中保留
    # ``zz_probe_decision_lifecycle``。自然外交观测不需要注入财政，但必须
    # 提供同源的只读兼容仪器，否则引擎会把缺少旧 mod 记录为本局错误。
    lifecycle = source_root / "fiscal-lifecycle-observer"
    decisions.write(
        observer,
        extension_probe.build(
            laws,
            strategies=extension_probe.political_keys(config.GAME),
            tags=tuple(value.strip() for value in args.legality_tags.split(",") if value.strip()),
            legality_laws=tuple(
                value.strip() for value in args.legality_laws.split(",") if value.strip()
            ),
            enactment_details=args.enactment_details,
        ),
    )
    policy_state = args.arm != "vanilla"
    decisions.write(fiscal, decision_probe.build_observer(policy_state=policy_state))
    decisions.write(
        lifecycle, decision_probe.build_observer(lifecycle=True, policy_state=policy_state)
    )
    sources = {
        "zz_sitai_reform_observer": observer,
        "zz_sitai_fiscal_observer": fiscal,
        "zz_probe_decision_lifecycle": lifecycle,
    }
    if getattr(args, "localization_baseline", False):
        baseline = source_root / "localization-baseline"
        decisions.write(baseline, decision_probe.build_localization_baseline(config.GAME))
        sources["zz_sitai_vanilla_localization_baseline"] = baseline
    natural = getattr(args, "natural_diplomacy", False)
    natural_tags = (
        natural_probe.parse_tags(args.natural_tags) if natural else natural_probe.DEFAULT_TAGS
    )
    command_targets = tuple(
        value.strip() for value in getattr(args, "natural_targets", "").split(",") if value.strip()
    )
    if natural:
        play_types: list[str] = []
        for path in sorted((config.GAME / "common/diplomatic_plays").glob("*.txt")):
            tree = parse_file(path)
            if tree.errors:
                raise ValueError(f"原版博弈类型无法解析：{path}")
            play_types.extend(key for key in tree.top_keys if key.startswith("dp_"))
        diplomacy = source_root / "natural-diplomacy"
        decisions.write(
            diplomacy,
            natural_probe.build(play_types, tags=natural_tags, command_targets=command_targets),
        )
        sources["zz_sitai_natural_diplomacy"] = diplomacy
    if args.arm != "vanilla":
        candidate = source_root / "candidate"
        extensions = replace(
            decisions.load_extensions(),
            reform_enabled=args.arm in {"reform", "combined"} or positive_control,
            market_enabled=args.arm == "combined",
        )
        policy = decisions.load()
        if args.arm == "reform" or positive_control:
            policy = replace(policy, neutrality=0, aggression=0)
        files = decisions.build(policy, extensions=extensions)
        if positive_control:
            # 仪器专属放大参数，只验证引擎通道；不回写生产配置、不直接启动立法。
            files["common/script_values/sitai_reform_values.txt"] = (
                "sitai_reform_default_delta = { value = 99 }\n"
                if global_control
                else "sitai_reform_default_delta = { value = 0 if = { limit = { OR = { c:RUS ?= this c:FRA ?= this } } add = 99 } }\n"
            )
            if global_control:
                # 独立排除ROOT过滤和国家筛选；仅全局放大默认启动意愿，不执行立法。
                guard = "\t\tif = { limit = { ROOT ?= { is_ai = yes } } add = sitai_reform_default_delta }\n"
                key = "common/ai_strategies/00_default_strategy.txt"
                if files[key].count(guard) != 1:
                    raise ValueError("全局正控未找到唯一声明的改革条件块")
                files[key] = files[key].replace(guard, "\t\tadd = sitai_reform_default_delta\n", 1)
            metadata = json.loads(files[".metadata/metadata.json"])
            metadata["name"] = (
                "SITAI global law-start positive control instrument"
                if global_control
                else "SITAI law-start positive control instrument"
            )
            metadata["short_description"] = "仅验证立法启动通道；放大参数不是生产玩法或质量证明"
            metadata["game_custom_data"]["multiplayer_synchronized"] = False
            files[".metadata/metadata.json"] = (
                json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
            )
        decisions.write(candidate, files)
        sources["sitai_decision_candidate"] = candidate

    def analyze(logdir):
        result: dict[str, object] = {
            "fiscal": decision_probe.analyze(logdir, strict=True, policy_state=policy_state),
            "reform": extension_probe.analyze(
                logdir,
                expected_tags=tuple(
                    value.strip() for value in args.legality_tags.split(",") if value.strip()
                ),
                expected_laws=tuple(
                    value.strip() for value in args.legality_laws.split(",") if value.strip()
                ),
            ),
            "experiment": {
                "arm": args.arm,
                "positive_control_default_contribution": (99 if positive_control else None),
                "positive_control_scope": (
                    "all AI countries, unconditional default contribution"
                    if global_control
                    else "RUS and FRA, guarded default contribution"
                    if positive_control
                    else None
                ),
                "computed_delta_scope": (
                    "Observer recomputes the conservative rule, not the positive-control "
                    "99 contribution or final engine chance. Source snapshots identify the "
                    "actual candidate contribution."
                ),
                "legality_laws": tuple(
                    value.strip() for value in args.legality_laws.split(",") if value.strip()
                ),
                "legality_tags": tuple(
                    value.strip() for value in args.legality_tags.split(",") if value.strip()
                ),
                "enactment_details": args.enactment_details,
            },
        }
        if natural:
            result["natural_diplomacy"] = natural_probe.analyze(logdir, tags=natural_tags)
            result["natural_tags"] = natural_tags
            if command_targets:
                result["command_legality"] = natural_probe.analyze_commands(
                    logdir, tags=natural_tags, targets=command_targets
                )
        return result

    report = game_run.run(
        sources,
        months=args.months,
        output=output,
        load_save=args.save,
        keep_save=args.keep_save,
        timeout=args.timeout,
        analyze=analyze,
        allow_save_upgrade=args.allow_save_upgrade,
        profile=args.profile,
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
