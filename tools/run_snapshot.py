"""快照与版本比对 CLI。

用途：捕获某个游戏版本下全部 mod 相关信息，日后 Paradox 增删字段时
一次 diff 就能全部发现。

用法：
    .venv\\Scripts\\python.exe tools/run_snapshot.py create            # 存当前版本快照
    .venv\\Scripts\\python.exe tools/run_snapshot.py create --label x  # 指定名字
    .venv\\Scripts\\python.exe tools/run_snapshot.py list              # 列出已有快照
    .venv\\Scripts\\python.exe tools/run_snapshot.py diff A B          # 比对两份
    .venv\\Scripts\\python.exe tools/run_snapshot.py verify            # 自我一致性检查
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pdx import config, snapshot  # noqa: E402


def cmd_create(args) -> int:
    snap = snapshot.build(verbose=True)
    label = args.label or snap.version_label.replace("/", "-")
    path = snapshot.snapshot_path(label)
    snap.write(path)

    counts = snap.counts()
    print(f"\n已写入 {path}")
    print(f"  域 {len(snap.sections)} 个，条目总计 {sum(counts.values()):,}")
    for sec, body in snap.sections.items():
        n = sum(len(v) for v in body.values())
        print(f"    {sec:<18} {len(body):>5} 项 / {n:>7,} 条")
    return 0


def cmd_list(args) -> int:
    paths = snapshot.list_snapshots()
    if not paths:
        print("尚无快照。先运行 create。")
        return 0
    print(f"共 {len(paths)} 份快照：")
    for p in paths:
        try:
            s = snapshot.Snapshot.load(p)
            n = sum(len(v) for v in s.sections.values() for v in [v])
            total = sum(len(names) for body in s.sections.values() for names in body.values())
            print(f"  {p.name:<24} {s.version_label:<20} {total:>8,} 条  ({p.stat().st_size:,} 字节)")
        except Exception as exc:
            print(f"  {p.name:<24} 读取失败: {exc}")
    return 0


def cmd_diff(args) -> int:
    a_path = snapshot.snapshot_path(args.a)
    b_path = snapshot.snapshot_path(args.b)
    for p in (a_path, b_path):
        if not p.is_file():
            print(f"找不到快照 {p}")
            return 1
    a = snapshot.Snapshot.load(a_path)
    b = snapshot.Snapshot.load(b_path)

    print(f"对比 {a.version_label}  →  {b.version_label}")
    print("─" * 68)
    print(f"  A rev: {a.version.get('caligula_rev', '?')}")
    print(f"  B rev: {b.version.get('caligula_rev', '?')}")
    print()

    changes = snapshot.compare(a, b)
    if not changes:
        print("两份快照完全一致 —— 没有检测到任何字段增删。")
        return 0

    s = snapshot.diff_summary(changes)
    for c in changes:
        print(c.line())

    print("─" * 68)
    print(f"变更项 {s['变更项数']} 处，新增条目 {s['新增条目']}，删除条目 {s['删除条目']}")

    if args.detail:
        print("\n明细：")
        for c in changes:
            print(f"\n[{c.section}] {c.name}")
            for x in c.added:
                print(f"  + {x}")
            for x in c.removed:
                print(f"  - {x}")

    if args.json:
        out = config.OUT_CROSS / "diff.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "from": {"版本": a.version, "文件": a_path.name},
                    "to": {"版本": b.version, "文件": b_path.name},
                    "概览": s,
                    "变更": [
                        {"域": c.section, "名称": c.name,
                         "新增": c.added, "删除": c.removed}
                        for c in changes
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nJSON 已写入 {out}")

    return 0


def cmd_verify(args) -> int:
    """自我一致性检查：同一环境重复生成的快照必须逐字节相同。"""
    print("构建快照两次并比较 …")
    a = snapshot.build()
    b = snapshot.build()
    da = json.dumps(a.to_dict(), ensure_ascii=False, indent=1, sort_keys=True)
    db = json.dumps(b.to_dict(), ensure_ascii=False, indent=1, sort_keys=True)
    if da == db:
        print("✅ 两次构建结果完全一致 —— 快照是确定性的")
        total = sum(len(n) for body in a.sections.values() for n in body.values())
        print(f"   域 {len(a.sections)} 个，条目总计 {total:,}")
        return 0
    print("❌ 两次构建结果不同 —— 快照不稳定，diff 会充满噪声")
    changes = snapshot.compare(a, b)
    for c in changes[:20]:
        print(c.line())
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Victoria 3 mod 信息快照与版本比对")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("create", help="生成当前版本快照")
    p.add_argument("--label", help="快照名（默认为版本号）")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("list", help="列出已有快照")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("diff", help="比对两份快照")
    p.add_argument("a", help="旧快照名")
    p.add_argument("b", help="新快照名")
    p.add_argument("--detail", action="store_true", help="列出增删明细")
    p.add_argument("--json", action="store_true", help="落盘 JSON")
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("verify", help="自我一致性检查")
    p.set_defaults(func=cmd_verify)

    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
