"""从固定观察者存档卸载生产机制，读出原变量自然过期。"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from pdx import config, decision_probe, decisions, game_run


def analyze_unload(logdir: Path):
    return decision_probe.analyze(logdir, strict=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", type=Path, required=True)
    parser.add_argument("--months", type=float, default=4)
    parser.add_argument(
        "--localization-baseline", action="store_true", help="隔离实验补原版中文缺键；不豁免错误"
    )
    args = parser.parse_args()
    output = config.OUT / "decisions/unload"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".sources-", dir=output) as directory:
        root = Path(directory)
        observer = root / "fiscal-observer"
        lifecycle = root / "fiscal-lifecycle-observer"
        decisions.write(observer, decision_probe.build_observer())
        # 固定检查点可能保留旧生命周期探针的元数据。卸载实验不需要它的
        # 生产逻辑，但必须用同名只读兼容源满足存档挂载契约，否则引擎会把
        # “缺少 Mod”计入本局错误，掩盖真正的卸载观测结果。
        decisions.write(lifecycle, decision_probe.build_observer(lifecycle=True))
        sources = {
            "zz_sitai_fiscal_observer": observer,
            "zz_probe_decision_lifecycle": lifecycle,
        }
        if getattr(args, "localization_baseline", False):
            baseline = root / "localization-baseline"
            decisions.write(baseline, decision_probe.build_localization_baseline(config.GAME))
            sources["zz_sitai_vanilla_localization_baseline"] = baseline
        report = game_run.run(
            sources,
            months=args.months,
            output=output,
            load_save=args.save,
            analyze=analyze_unload,
        )
    print(
        json.dumps(
            {
                key: report.get(key)
                for key in ("ok", "failure", "evidence", "progress", "cleanup_errors", "analysis")
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
