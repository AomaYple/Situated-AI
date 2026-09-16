"""性能剖析：找出全量分析的时间去向。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pdx import config  # noqa: E402
from pdx.extract import extract_dir  # noqa: E402
from pdx.mods import analyse_all, vanilla_prefix_count  # noqa: E402
from pdx.parser import parse_file  # noqa: E402
from pdx.scan import stats_for, walk_files  # noqa: E402


def t(label, fn):
    t0 = time.perf_counter()
    r = fn()
    dt = time.perf_counter() - t0
    print(f"  {label:<44} {dt:7.2f}s")
    return r, dt


print("阶段耗时剖析")
print("─" * 62)

common = config.GAME / "common"

# 1. 纯文件枚举
files, _ = t("枚举 game/common 下全部文件", lambda: list(walk_files(common)))

# 2. 单个目录解析
_, _ = t("解析 static_modifiers（68 文件）",
         lambda: extract_dir(common / "static_modifiers"))

# 3. 全部 .txt 解析
txt_files = list(walk_files(common, ".txt"))
print(f"  （common 下 .txt 共 {len(txt_files)} 个）")


def parse_all():
    n = 0
    for f in txt_files:
        parse_file(f.path)
        n += 1
    return n


_, dt_parse = t(f"解析全部 {len(txt_files)} 个 .txt", parse_all)

# 4. 各种统计
_, _ = t("统计三个内容根（stats_for）", lambda: [
    stats_for(r) for r in (config.GAME, config.JOMINI, config.CLAUSEWITZ)
    if r.is_dir()
])

# 5. 原版前缀扫描（会再解析一遍全部 .txt）
_, dt_prefix = t("vanilla_prefix_count（重复解析全库）", vanilla_prefix_count)

# 6. mod 分析
_, dt_mods = t("analyse_all（23 个 mod）", analyse_all)

print("─" * 62)
print(f"  合计约 {dt_parse + dt_prefix + dt_mods:.1f}s")
print()
print("观察：")
print("  * vanilla_prefix_count 会**重复解析**一遍全库 .txt —— 纯浪费")
print("  * mod 覆盖比对会**逐个重新解析**原版文件 —— 同一文件可能被解析多次")
