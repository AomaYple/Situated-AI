"""Capture or verify the independently pinned R2 native reader authorities."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pdx import version_contracts
from pdx.situated import r2_reader_authority as authority


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installation", type=Path, help="identity-verified Victoria 3 1.15 root")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--check", action="store_true", help="verify existing snapshot and live sources"
    )
    args = parser.parse_args()
    try:
        version_contracts.require_current()
        output = args.output or authority.frozen_root()
        if args.check:
            manifest = authority.verify_frozen(output)
            authority.verify_installation(args.installation)
        else:
            manifest = authority.capture(args.installation, output)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
