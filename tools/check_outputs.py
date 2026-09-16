"""核验分析产物：确认关键数字与已核实结论一致。"""
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

g, m = game["概览"], mods["概览"]
ok = True


def chk(label, actual, expect):
    global ok
    good = actual == expect
    ok &= good
    print(f"  {'✅' if good else '❌'} {label:<36} {actual}  (期望 {expect})")


print("游戏本体")
chk("common 目录数", g["common 目录数"], 136)
chk("DLC 数", g["DLC"], 17)
chk("官方 md 数", g["官方md"], 92)
chk("原版前缀使用", g["原版前缀使用"], 0)
chk("本地化语言数", g["本地化语言数"], 11)

print("\n条目数抽样")
common = game["common"]
for name, want in [
    ("static_modifiers", 6128), ("modifier_type_definitions", 2364),
    ("character_templates", 2011), ("production_methods", 436),
    ("buildings", 115), ("laws", 138), ("on_actions", 263),
]:
    chk(name, common[name]["顶层条目数"], want)

print("\n空目录是否被收录")
chk("scripted_modifiers 在 common 中", "scripted_modifiers" in common, True)

print("\nmod")
chk("mod 数", m["mod 数"], 23)
prefixes = mods["全部功能前缀"]
chk("前缀总数", sum(prefixes.values()), 2737)
chk("REPLACE_OR_CREATE", prefixes.get("REPLACE_OR_CREATE"), 1116)
chk("INJECT", prefixes.get("INJECT"), 740)

print("\n交叉")
chk("被改动原版条目数 > 0", cross["概览"]["被改动的原版条目数"] > 0, True)

print()
print("全部一致 ✅" if ok else "存在不一致 ❌")
sys.exit(0 if ok else 1)
