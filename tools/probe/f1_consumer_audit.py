"""生成 F1 七模块静态字段消费者审计报告。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from pdx import consumer_audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=consumer_audit.OUTPUT)
    parser.add_argument("--baseline", type=Path, default=consumer_audit.BASELINE)
    args = parser.parse_args(argv)
    json_path, markdown_path = consumer_audit.write(args.output, baseline=args.baseline)
    print(
        json.dumps(
            {"json": str(json_path), "markdown": str(markdown_path)}, ensure_ascii=False, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
