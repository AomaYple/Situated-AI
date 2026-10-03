"""汇总 pytest JUnit XML，并给 skipped 测试分配工程类别。

用法：

    python tools/ci/test_summary.py test-results.xml
    python tools/ci/test_summary.py test-results.xml --output tools/out/ci/test-summary.json

未知或空的跳过原因返回退出码 2。这样 CI 不会把新加入的、没有说明原因的
跳过项悄悄算进绿灯。
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import cast

from pdx.engineering import require_skip_category


def summarize(path: Path) -> dict[str, object]:
    root = ET.fromstring(path.read_text(encoding="utf-8-sig"))
    cases = list(root.iter("testcase"))
    skipped: list[dict[str, str]] = []
    categories: Counter[str] = Counter()
    unknown: list[str] = []
    for case in cases:
        node = case.find("skipped")
        if node is None:
            continue
        reason = (node.get("message") or node.text or "").strip()
        node_id = "::".join(filter(None, (case.get("classname"), case.get("name"))))
        try:
            category = require_skip_category(reason)
        except ValueError:
            category = "unknown"
            unknown.append(f"{node_id}: {reason!r}")
        categories[category] += 1
        skipped.append({"test": node_id, "category": category, "reason": reason})
    failures = sum(1 for case in cases if case.find("failure") is not None)
    errors = sum(1 for case in cases if case.find("error") is not None)
    return {
        "tests": len(cases),
        "skipped": len(skipped),
        "failures": failures,
        "errors": errors,
        "skip_categories": dict(sorted(categories.items())),
        "unknown_skip_reasons": unknown,
        "skips": skipped,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("junit", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = summarize(args.junit)
    except (OSError, ET.ParseError, UnicodeError) as exc:
        print(f"[test-summary] 无法读取 JUnit XML：{exc}", file=sys.stderr)
        return 2
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    unknown = cast("list[str]", report["unknown_skip_reasons"])
    if unknown:
        print("[test-summary] 存在未分类的跳过原因：", file=sys.stderr)
        for reason in unknown:
            print(f"  {reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
