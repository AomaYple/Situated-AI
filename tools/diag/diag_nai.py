"""核查 NAI 参数计数为何从 1013 变成 1017。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pdx import config  # noqa: E402
from pdx.cache import parse_cached  # noqa: E402
from pdx.model import Assignment, Block, Scalar  # noqa: E402

f = config.GAME / "common" / "defines" / "00_ai.txt"
pf = parse_cached(f)

print(f"文件顶层键: {pf.top_keys}")
print()

nai = None
for a in pf.top_assignments:
    if a.key == "NAI" and a.is_block:
        nai = a
        break

if nai is None:
    print("未找到 NAI 块")
    sys.exit(1)

assigns = list(nai.value.assignments())
print(f"NAI 块内 Assignment 数: {len(assigns)}")

# 按值类型分类
kinds = {"标量": 0, "块": 0, "空": 0}
for a in assigns:
    if isinstance(a.value, Block):
        kinds["块"] += 1
    elif isinstance(a.value, Scalar):
        kinds["标量"] += 1
    else:
        kinds["空"] += 1
print(f"  形态分布: {kinds}")

# 非标量的逐个列出
print()
print("非标量参数：")
for a in assigns:
    if not isinstance(a.value, Scalar):
        t = type(a.value).__name__
        n = len(a.value) if isinstance(a.value, Block) else 0
        print(f"   L{a.line:<6} {a.key:<50} {t}({n})")

# 唯一性
keys = [a.key for a in assigns]
print()
print(f"键总数 {len(keys)} / 去重 {len(set(keys))}")
dupes = [k for k in set(keys) if keys.count(k) > 1]
print(f"重复键: {dupes}")

# 原文件行级独立核对
lines = f.read_text(encoding="utf-8-sig").splitlines()
print()
print(f"文件总行数: {len(lines)}")
# 用最宽松口径独立数一遍块内参数
import re
in_nai = False
depth = 0
count = 0
for i, raw in enumerate(lines, 1):
    s = raw.split("#", 1)[0] if not raw.lstrip().startswith("#") else ""
    if not in_nai:
        if re.match(r"^NAI\s*=\s*\{", raw):
            in_nai = True
            depth = 1
        continue
    depth += s.count("{") - s.count("}")
    if depth <= 0:
        break
    if re.match(r"^\s+[A-Za-z@][^\s=]*\s*=", s):
        count += 1
print(f"独立行级计数（块内赋值行）: {count}")
