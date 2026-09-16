"""诊断 scoping 改动引入的两个问题。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pdx import config  # noqa: E402
from pdx.extract import extract_dir  # noqa: E402
from pdx.scan import walk_files  # noqa: E402

common = config.GAME / "common"

print("① common 下的『散装文件』（不属于任何子目录）")
for f in walk_files(common):
    if f.path.parent == common:
        print(f"   {f.path.name}  ({f.suffix})")

print()
print("② on_actions 条目对比")
res = extract_dir(common / "on_actions")
print(f"   extract_dir 得到: {res.unique_entries}")
files = sorted((common / "on_actions").rglob("*"))
for f in files:
    if f.is_file():
        print(f"     {f.name}")

print()
print("③ 与 walk_files 的 .txt 口径对比")
n_txt = sum(1 for _ in walk_files(common / "on_actions", ".txt"))
print(f"   on_actions 下 .txt 文件数: {n_txt}")
print(f"   extract_dir 统计的文件数: {res.files}")

print()
print("④ 逐个文件看键数")
from pdx.cache import parse_cached  # noqa: E402
total = set()
for f in sorted(walk_files(common / "on_actions", ".txt"), key=lambda e: str(e.path)):
    keys = parse_cached(f.path).top_keys
    total.update(keys)
    print(f"   {f.path.name:<34} {len(keys):>4} 键")
print(f"   去重合计 {len(total)}")
