"""在隔离观察者局核对两国真实财政接口与风险状态退出。"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from pdx import config, decision_probe, decisions, game_run


def analyze_lifecycle(logdir: Path):
    """M2 证据必须使用严格连续样本口径。"""

    return decision_probe.analyze(logdir, strict=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", type=float, default=9)
    parser.add_argument(
        "--controlled", action="store_true", help="仪器创建两场外交承诺窗口；不算AI自主行为"
    )
    parser.add_argument(
        "--keep-save", action="store_true", help="游戏停止后归档自动存档作为固定检查点"
    )
    parser.add_argument("--load-save", type=Path, help="重载归档的观察者检查点")
    args = parser.parse_args()
    output = config.OUT / "decisions" / ("activation" if args.controlled else "lifecycle")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".sources-", dir=output) as directory:
        candidate, probe = Path(directory) / "candidate", Path(directory) / "instrument"
        decisions.write(candidate)
        decisions.write(probe, decision_probe.build(controlled=args.controlled))
        report = game_run.run(
            {"sitai_decision_candidate": candidate, "zz_probe_decision_lifecycle": probe},
            months=args.months,
            output=output,
            analyze=analyze_lifecycle,
            load_save=args.load_save,
            keep_save=args.keep_save,
        )
    print(
        json.dumps(
            {
                key: report.get(key)
                for key in ("ok", "failure", "cleanup_errors", "evidence", "progress")
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
