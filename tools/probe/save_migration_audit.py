"""盘点可用于 Victoria 3 跨版本存档迁移实验的输入。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pdx.save_migration import dump_json, scan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="递归搜索 .v3 的证据或存档目录")
    parser.add_argument("--expected-version", help="覆盖当前安装版本，供离线报告复核")
    parser.add_argument("--output", type=Path, help="可选的 JSON 报告路径")
    args = parser.parse_args()
    inventory = scan(args.root, expected_version=args.expected_version)
    payload = inventory.to_dict()
    if args.output:
        dump_json(inventory, args.output)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if inventory.parse_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
