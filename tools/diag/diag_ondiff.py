"""对比解析器提取的 on_action 键与 doc 04 记录的键，找出差异。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pdx import config  # noqa: E402
from pdx.cache import parse_cached  # noqa: E402
from pdx.scan import walk_files  # noqa: E402

# 解析器提取
dirpath = config.GAME / "common" / "on_actions"
mine: set[str] = set()
per_file: dict[str, list[str]] = {}
for f in sorted(walk_files(dirpath, ".txt"), key=lambda e: str(e.path)):
    keys = parse_cached(f.path).top_keys
    per_file[f.path.name] = keys
    mine |= set(keys)

# 文档记录的键：从 doc 04 的反引号代码片段里抽取
doc = (config.DOCS / "04-脚本系统.md").read_text(encoding="utf-8")
doc_keys = set(re.findall(r"`([a-z][a-z0-9_]{4,})`", doc))
# 只保留看起来像 on_action 的（文档里混杂了其他标识符，这里取与解析结果同域的）
candidate = {k for k in doc_keys if k.startswith("on_") or k.endswith("_events") or "_pulse" in k}

print(f"解析器键数: {len(mine)}")
print(f"文档中疑似 on_action 键: {len(candidate)}")
print()
only_mine = sorted(mine - candidate)
only_doc = sorted(candidate - mine)
print(f"仅在解析器结果中（{len(only_mine)}）:")
for k in only_mine[:40]:
    where = [fn for fn, ks in per_file.items() if k in ks]
    print(f"   {k:<48} {where}")
print()
print(f"仅在文档中（{len(only_doc)}）:")
for k in only_doc[:40]:
    print(f"   {k}")
