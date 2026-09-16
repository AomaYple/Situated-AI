"""诊断：核实全量分析报告里几个存疑的数字。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pdx import config  # noqa: E402
from pdx.cache import parse_cached  # noqa: E402
from pdx.scan import walk_files  # noqa: E402

common = config.GAME / "common"

print("① common 子目录数")
dirs = sorted(p for p in common.iterdir() if p.is_dir())
print(f"   iterdir 得到的子目录: {len(dirs)}")
no_txt = []
for d in dirs:
    n = sum(1 for _ in walk_files(d, ".txt"))
    if n == 0:
        no_txt.append(d.name)
print(f"   其中没有任何 .txt 的: {len(no_txt)} 个 -> {no_txt}")
print()

print("② DLC 数量")
dlc_root = config.GAME / "dlc"
dlcs = sorted(p.name for p in dlc_root.iterdir() if p.is_dir())
print(f"   实际目录数: {len(dlcs)}")
for d in dlcs:
    print(f"     {d}")
print()

print("③ common 根下的散装 .txt")
loose = [f.path.name for f in walk_files(common, ".txt") if f.path.parent == common]
print(f"   {len(loose)} 个 -> {loose}")
print()

print("④ 解析报错的文件")
errs = 0
for f in walk_files(config.GAME, ".txt"):
    pf = parse_cached(f.path)
    if pf.errors:
        errs += 1
        rel = f.path.relative_to(config.GAME)
        print(f"   {rel}")
        for e in pf.errors[:2]:
            print(f"       {e}")
print(f"   合计 {errs} 个文件有报错")
