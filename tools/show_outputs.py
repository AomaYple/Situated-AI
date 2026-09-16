"""列出全量分析产出的内容结构与规模。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pdx import config  # noqa: E402

game = json.loads((config.OUT_GAME / "游戏本体.json").read_text(encoding="utf-8"))
mods = json.loads((config.OUT_MODS / "mod.json").read_text(encoding="utf-8"))
cross = json.loads((config.OUT_CROSS / "交叉.json").read_text(encoding="utf-8"))


def size(p: Path) -> str:
    n = p.stat().st_size
    return f"{n/1048576:.2f} MB" if n > 1048576 else f"{n/1024:.0f} KB"


print("=" * 70)
print("产出文件")
print("=" * 70)
for label, p in [
    ("游戏本体 JSON", config.OUT_GAME / "游戏本体.json"),
    ("mod JSON", config.OUT_MODS / "mod.json"),
    ("交叉 JSON", config.OUT_CROSS / "交叉.json"),
    ("游戏本体报告", config.REPORTS / "游戏本体分析.md"),
    ("mod 报告", config.REPORTS / "mod分析.md"),
]:
    print(f"  {label:<16} {size(p):>10}   {p.relative_to(config.REPO)}")

print()
print("=" * 70)
print("游戏本体 JSON —— 顶层字段")
print("=" * 70)
for k, v in game.items():
    if isinstance(v, dict):
        print(f"  {k:<16} 字典，{len(v):,} 个键")
    elif isinstance(v, list):
        print(f"  {k:<16} 列表，{len(v):,} 项")
    else:
        print(f"  {k:<16} {type(v).__name__}")

print()
print("  · common 每个目录记录的内容：")
sample = game["common"]["buildings"]
for k, v in sample.items():
    if isinstance(v, list):
        print(f"      {k:<14} 列表 {len(v):,} 项")
    elif isinstance(v, dict):
        print(f"      {k:<14} 字典 {len(v):,} 键")
    else:
        print(f"      {k:<14} {v}")

print()
print("  · 全部条目名覆盖：")
total_entries = sum(len(v["条目"]) for v in game["common"].values())
print(f"      common 条目名合计 {total_entries:,}")
print(f"      common 字段名合计 "
      f"{sum(len(v['字段']) for v in game['common'].values()):,}")

print()
print("=" * 70)
print("mod JSON —— 顶层字段")
print("=" * 70)
for k, v in mods.items():
    if isinstance(v, dict):
        print(f"  {k:<16} 字典，{len(v):,} 个键")
    elif isinstance(v, list):
        print(f"  {k:<16} 列表，{len(v):,} 项")
    else:
        print(f"  {k:<16} {type(v).__name__}")

print()
print("  · 每个 mod 记录的内容：")
s = mods["各mod"][1]
for k, v in s.items():
    if isinstance(v, list):
        print(f"      {k:<16} 列表 {len(v):,} 项")
    elif isinstance(v, dict):
        print(f"      {k:<16} 字典 {len(v):,} 键")
    else:
        print(f"      {k:<16} {v}")

print()
print("=" * 70)
print("交叉 JSON")
print("=" * 70)
for k, v in cross.items():
    if isinstance(v, dict):
        print(f"  {k:<16} 字典，{len(v):,} 个键")
    else:
        print(f"  {k:<16} {v}")
