"""找出 00_code_on_actions.txt 里多出的那个键。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pdx import config  # noqa: E402
from pdx.cache import parse_cached  # noqa: E402
from pdx.lexer import tokenize  # noqa: E402

f = config.GAME / "common" / "on_actions" / "00_code_on_actions.txt"
pf = parse_cached(f)

print(f"解析器得到 {len(pf.top_keys)} 个顶层键")
print(f"其中 @变量 {sum(1 for k in pf.top_keys if k.startswith('@'))} 个")
print()

# 找出可疑键：含非常规字符、或以数字开头等
keys = pf.top_keys
suspects = [
    k for k in keys
    if not k.replace("_", "").isalnum() or k[:1].isdigit()
]
print(f"可疑键（含非常规字符或数字开头）: {suspects}")
print()

# 定位每个可疑键的行号
for s in suspects:
    for a in pf.top_assignments:
        if a.key == s:
            print(f"  {s}  在第 {a.line} 行  前缀={a.prefix}  是块={a.is_block}")
            break
print()

# 打印可疑键所在行的原文
lines = f.read_text(encoding="utf-8-sig").splitlines()
for s in suspects:
    for a in pf.top_assignments:
        if a.key == s and 0 < a.line <= len(lines):
            print(f"  第 {a.line} 行原文: {lines[a.line-1][:90]!r}")
            break

print()
print("最后 5 个键:", keys[-5:])
print()
# 统计块 vs 标量
blocks = sum(1 for a in pf.top_assignments if a.is_block)
scalars = sum(1 for a in pf.top_assignments if not a.is_block)
print(f"块 {blocks} 个 / 非块 {scalars} 个")
nonscalar = [(a.key, a.line) for a in pf.top_assignments if not a.is_block]
print("非块的键:", nonscalar[:10])
