"""defines 提取 CLI。

取代原先的 dump_defines.ps1 / dump_precise.ps1 / extract_defines.ps1。

用法：
    .venv\\Scripts\\python.exe tools/run_defines.py              # 摘要
    .venv\\Scripts\\python.exe tools/run_defines.py --ai         # 只看 NAI
    .venv\\Scripts\\python.exe tools/run_defines.py --ns NAI     # 指定命名空间
    .venv\\Scripts\\python.exe tools/run_defines.py --json       # 落盘
    .venv\\Scripts\\python.exe tools/run_defines.py --overlay f  # 预览覆盖范围
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pdx import config, defines  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Victoria 3 defines 提取")
    ap.add_argument("--ns", help="只输出指定命名空间")
    ap.add_argument("--ai", action="store_true", help="等价于 --ns NAI")
    ap.add_argument("--json", action="store_true", help="落盘 JSON")
    ap.add_argument("--overlay", type=Path, help="预览一段 mod defines 的覆盖范围")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    reports = defines.extract_all_defines()
    game = reports["game"]
    jomini = reports["jomini"]

    print("defines 提取")
    print("─" * 64)
    for label, r in reports.items():
        s = r.summary()
        print(f"[{label}] 文件 {s['涉及文件']}  "
              f"命名空间块 {s['命名空间块数']}  "
              f"去重 {s['去重命名空间']}  "
              f"参数 {s['参数总数']:,}  "
              f"@变量 {s['@变量数']}")

    dup = game.summary()["跨文件重复的命名空间"]
    if dup:
        print("\n跨文件重复的命名空间（引擎按块名合并的直接证据）：")
        for k, v in dup.items():
            print(f"  {k}: {', '.join(v)}")

    if args.overlay:
        text = args.overlay.read_text(encoding="utf-8-sig")
        ov = defines.overlay(game, text)
        print(f"\n覆盖预览：{ov['命名空间数']} 个命名空间")
        for item in ov["明细"]:
            print(f"  [{item['状态']}] {item['命名空间']}")
            if item.get("覆盖参数"):
                print(f"      覆盖 {len(item['覆盖参数'])}: "
                      f"{', '.join(item['覆盖参数'][:8])}")
            if item.get("新增参数"):
                print(f"      新增 {len(item['新增参数'])}: "
                      f"{', '.join(item['新增参数'][:8])}")

    target = "NAI" if args.ai else args.ns
    if target:
        hits = game.get(target)
        if not hits:
            print(f"\n未找到命名空间 {target}")
            return 1
        for ns in hits:
            print(f"\n{ns.name}  ({ns.file}:{ns.line})  {ns.count} 个参数")
            print("─" * 64)
            for p in ns.params:
                if p.kind == defines.SCALAR:
                    print(f"  {p.name:<58} = {p.value}")
                else:
                    print(f"  {p.name:<58} [{p.kind} ×{p.elements}]")

    if args.json:
        config.ensure_dirs()
        out = config.OUT_GAME / "defines.json"
        out.write_text(
            json.dumps(
                {
                    label: {
                        "概览": r.summary(),
                        "命名空间": [n.to_dict() for n in r.namespaces],
                        "@变量": [
                            {"名称": n, "值": v, "行": ln}
                            for n, v, ln in r.variables
                        ],
                    }
                    for label, r in reports.items()
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n已写入 {out}  ({out.stat().st_size:,} 字节)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
