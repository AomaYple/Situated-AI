"""串行运行规则审计并输出可复核资源测量。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pdx import policy_audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="policy_audit 串行资源基准")
    parser.add_argument("--out", type=Path, default=Path("tools/out/t-plan/parameter-report.json"))
    args = parser.parse_args(argv)
    report = policy_audit.build(measure=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(report["resource_measurement"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
