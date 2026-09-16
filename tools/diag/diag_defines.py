"""诊断：defines 目录的顶层块到底有多少个，以及口径差异从何而来。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pdx import config  # noqa: E402
from pdx.parser import parse_file  # noqa: E402

blocks: list[tuple[str, str]] = []   # (键名, 文件)
for f in (config.GAME / "common" / "defines").rglob("*.txt"):
    for a in parse_file(f).top_assignments:
        blocks.append((a.key, f.name))

upper = [b for b in blocks if b[0][:1].isupper()]
lower = [b for b in blocks if not b[0][:1].isupper()]

print(f"全部顶层块      : {len(blocks)}")
print(f"大写字母开头    : {len(upper)}   唯一 {len({b[0] for b in upper})}")
print(f"非大写字母开头  : {len(lower)}   唯一 {len({b[0] for b in lower})}")
print()
print("非大写开头的块（这些是 doc 05 的 75 口径排除掉的）：")
for name, fname in sorted(lower):
    print(f"  {name:<44} {fname}")
print()
print("大写块中重复出现的（跨文件同名）：")
seen: dict[str, list[str]] = {}
for name, fname in upper:
    seen.setdefault(name, []).append(fname)
for name, files in sorted(seen.items()):
    if len(files) > 1:
        print(f"  {name:<28} x{len(files)}  {', '.join(files)}")
