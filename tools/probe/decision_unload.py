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
    args = parser.parse_args()
    output = config.OUT / "decisions/unload"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".sources-", dir=output) as directory:
        observer = Path(directory)
        decisions.write(observer, decision_probe.build_observer())
        report = game_run.run(
            {"zz_sitai_fiscal_observer": observer},
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
