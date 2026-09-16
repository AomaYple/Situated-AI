"""运行知识库断言核对。

用法：
    .venv\\Scripts\\python.exe tools/run_verify.py            # 全部
    .venv\\Scripts\\python.exe tools/run_verify.py --fast      # 跳过全库扫描
    .venv\\Scripts\\python.exe tools/run_verify.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pdx import verify  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="核对知识库文档中的数量断言")
    ap.add_argument("--fast", action="store_true", help="跳过需要全库扫描的检查")
    ap.add_argument("--json", type=Path, help="把结果写入 JSON")
    ap.add_argument("--only", help="只跑 id 含该子串的断言")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    claims = verify.CLAIMS
    if args.only:
        claims = [c for c in claims if args.only in c.id]

    results = verify.run_claims(claims, include_slow=not args.fast)

    total = len(results)
    failed = [r for r in results if not r.ok]

    print(f"核对 {total} 条断言\n" + "─" * 72)
    for r in results:
        print(r.line())
    print("─" * 72)

    s = verify.summarize(results)
    print(f"通过 {s['通过']} / {total}    失败 {s['失败']}")
    if failed:
        print("\n失败明细：")
        for r in failed:
            c = r.claim
            print(f"  [{c.id}] {c.doc}")
            print(f"      {c.text}")
            print(f"      期望 {c.expected}  实得 {r.actual}  {r.error}")
            if c.note:
                print(f"      备注：{c.note}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(
                {
                    "summary": s,
                    "results": [
                        {
                            "id": r.claim.id,
                            "doc": r.claim.doc,
                            "text": r.claim.text,
                            "kind": r.claim.kind,
                            "target": r.claim.target,
                            "expected": r.claim.expected,
                            "actual": r.actual,
                            "ok": r.ok,
                            "error": r.error,
                        }
                        for r in results
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nJSON 已写入 {args.json}")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
