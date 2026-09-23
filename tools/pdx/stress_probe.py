"""标准压力剧本（阶段 4 ④）：**大战 + 连锁破产 + 革命潮**，一份可重放的探针 mod。

为什么需要它
------------
`阶段4-结果.md` §六·补 把 G-EXIT-3 的对照表跑出来了（6 局、`--repeat 3`），但那是
**非受控**对照：两臂各跑一局新开的观察者局，vanilla 自己三局的极差就有 **2.1 ms**，
而两配置的差只有 0.51 ms ⇒ **噪声比信号大 4 倍**，0.5 ms 的预算落在噪声里分辨不出来。

要把 0.5 ms 分辨出来，需要的是 `阶段4-框架化.md` §④ 说的那样：**固定指令序列**下的对照 ——
也就是这一份剧本。它挂在**同一套自动化**上（起游戏 → 观察者局 → 跑到固定日期），
在两臂里**都装**，于是两臂面对的是同一个世界演化，唯一差别只有我们的 mod。

三条压力都用**原版自己的效果**造，不伪造状态
--------------------------------------------
伪造的状态（比如直接挂一个"破产"修正）不会让引擎干活，也就压不出负载。三条各自的原版先例：

===========  ==========================================  ============================================================
压力          用什么                                       原版先例
===========  ==========================================  ============================================================
**大战**      ``create_diplomatic_play = { … }``          ``common/scripted_effects/00_sepoy_mutiny_scripted_effects.txt:474``
**革命潮**    ``add_radicals_in_state = { value = {…} }``  ``common/scripted_effects/00_chris_scripted_effects.txt:43``
**连锁破产**  ``add_treasury = -N`` ⇒ 国库见底           ``common/scripted_effects/paris_commune_events.txt:243``（−100000）、
                                                         ``common/scripted_effects/0000_debug_effects.txt:5``（−50000）
===========  ==========================================  ============================================================

⚠️ **破产不是我们写上去的**：原版没有"让某国破产"的效果 —— 破产是引擎自己的判定
（`DECLARE_BANKRUPTCY_MIN_DAYS_IN_DEFAULT = 30`，`common/defines/00_ai.txt:52`：
违约满 30 天，AI 自己宣布破产）。我们只把它**推**到那一步，引擎走完剩下的一步，
**负载才是真的**。这也是为什么这里用 `add_treasury` 而不是伪造一个破产修正。

时点用 `game_date` 卡，不用"第几个月"计数器
--------------------------------------------
每个月脉冲判一次 ``game_date > "YYYY.M.D"`` + 一个 **fired 标记**（变量）：到点就做、只做一次。
比数月份简单，而且**与两臂的世界日期天然对齐**（两边都是 1836.1 开局）。

口径与边界
----------
* 目标国**写死**（不按国力排序 —— 排序需要一个不稳定谓词），所以两臂受的压力逐字节相同；
* 本模块只**生成**探针 mod，不跑游戏；跑由 `tools/probe/perf_compare.py --stress` 负责
  （它两臂都装这一份，见那边的注释）。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from pdx import config

TAB = "\t"

#: 探针 mod 在用户 mod 目录里的名字（`zz_` 前缀 ⇒ `pdx.mods.discover_mods()` 会排除它，
#: 与既有的探针同一条口径：它不算"本机装了哪些 mod"）。
MOD_NAME = "zz_stress_scenario"

#: 生成文件头上的那句话（与 `modgen` 的产物同一口径：改这里没用）。
GEN_HEADER = (
    "# ⚠️ 本文件由 `pdx.stress_probe` 生成（tools/pdx/stress_probe.py）—— 改这里没用，改生成器。"
)

#: **大战**：写死的五对。每一对都是 `initiator` 主动开一场博弈（`escalation` 拉高 ⇒ 更容易打成仗）。
#: 为什么写死而不是按国力挑：挑需要一个稳定谓词，而"谁强"每个月都在变 —— 写死才能保证两臂同压。
WAR_PAIRS: tuple[tuple[str, str, str], ...] = (
    # (initiator, target, dp 类型)
    ("GBR", "FRA", "dp_open_market"),
    ("RUS", "TUR", "dp_regime_change"),
    ("AUS", "PRU", "dp_open_market"),
    ("USA", "MEX", "dp_conquer_state"),
    ("CHI", "GBR", "dp_open_market"),
)

#: **连锁破产**：这些国家的国库被抽干 ⇒ 违约 ⇒ 引擎在 30 天后自己宣布破产（见模块头）。
#: 选的是中等国家：抽同样一笔钱，大国扛得住、小国当场见底 —— 中等国家最接近"连锁"。
BREAK_TAGS: tuple[str, ...] = ("MEX", "BRZ", "SPA", "TUR", "PER", "EGY", "CHI", "JAP")

#: **革命潮**：这些国家每隔半年吃一波激进派（走 `add_radicals_in_state`，真进运动系统）。
#: 选大国是因为它们的状态多、POP 多 —— 激进派一多，运动与革命的算量才上得去。
RADICAL_TAGS: tuple[str, ...] = ("GBR", "FRA", "RUS", "AUS", "PRU", "CHI", "TUR", "USA")

#: 三件事各自的**触发日期**（`game_date > …`）。
WAR_DATE = "1837.1.1"  # 开局后约 12 个月
BREAK_DATE = "1837.7.1"  # 约 18 个月
RADICAL_DATES: tuple[str, ...] = ("1837.1.1", "1837.7.1", "1838.1.1", "1838.7.1")

#: 抽干国库的额度（负数 = 抽走）。取 −200000：比原版 `paris_commune_events.txt:243`
#: 那一处的 −100000 再重一档 —— 中等国家的国库量级撑不住它，于是**一定**进违约。
TREASURY_DRAIN = -200000

#: 每波激进派的比例（`add_radicals_in_state` 的 `value` 是**占该州人口的比例**，
#: 原版 `00_chris_scripted_effects.txt:43` 用的是 0.015 量级；压力剧本要的是"革命潮"，
#: 所以取 0.10 —— 一个州多出十分之一人口的激进派，运动与革命的算量立刻上台阶）。
RADICALS_PER_WAVE = 0.10


def _fire_guard(tag_var: str, date: str) -> str:
    """到点做一次、只做一次的判据（`game_date` + fired 变量）。"""
    return (
        f"{TAB}limit = {{\n"
        f"{TAB * 2}NOT = {{ has_variable = {tag_var} }}\n"
        f'{TAB * 2}game_date > "{date}"\n'
        f"{TAB}}}\n"
        f"{TAB}set_variable = {{ name = {tag_var} value = 1 }}\n"
    )


def effects_text() -> str:
    """每月脉冲调用的那一个效果（三条压力都在这里，**按国家各自判**）。"""
    wars = "".join(
        f"{TAB * 2}if = {{\n"
        f"{TAB * 3}limit = {{ c:{initiator} ?= this }}\n"
        f"{TAB * 3}create_diplomatic_play = {{\n"
        f"{TAB * 4}type = {kind}\n"
        f"{TAB * 4}escalation = 80\n"
        f"{TAB * 4}target_country = c:{target}\n"
        f"{TAB * 3}}}\n"
        f"{TAB * 2}}}\n"
        for initiator, target, kind in WAR_PAIRS
    )
    breakers = "".join(
        f"{TAB * 2}c:{tag} ?= {{ add_treasury = {TREASURY_DRAIN} }}\n" for tag in BREAK_TAGS
    )
    radical_blocks = "".join(
        f"{TAB}if = {{\n"
        + _fire_guard(f"zz_stress_radicals_{index}", date)
        + f"{TAB * 2}every_scope_state = {{\n"
        f"{TAB * 3}add_radicals_in_state = {{ value = {{ add = {RADICALS_PER_WAVE} }} }}\n"
        f"{TAB * 2}}}\n"
        f"{TAB}}}\n"
        for index, date in enumerate(RADICAL_DATES, start=1)
    )
    radicals_guard = "".join(f"{TAB * 2}c:{tag} ?= this\n" for tag in RADICAL_TAGS)
    return (
        f"{GEN_HEADER}\n"
        f"# 标准压力剧本的效果本体：**大战 + 连锁破产 + 革命潮**（阶段 4 ④）。\n"
        f"#\n"
        f"# 三条都用原版自己的效果造，不伪造状态（伪造的状态不让引擎干活，压不出负载）：\n"
        f"#   * 大战     —— `create_diplomatic_play`（原版先例 00_sepoy_mutiny_scripted_effects.txt:474）\n"
        f"#   * 连锁破产 —— `add_treasury = {TREASURY_DRAIN}` ⇒ 国库见底 ⇒ **引擎自己**在违约 30 天后\n"
        f"#                 宣布破产（DECLARE_BANKRUPTCY_MIN_DAYS_IN_DEFAULT = 30，common/defines/00_ai.txt:52）\n"
        f"#   * 革命潮   —— `add_radicals_in_state`（原版先例 00_chris_scripted_effects.txt:43）\n"
        f"#\n"
        f"# 时点用 `game_date` + fired 变量卡：到点做一次、只做一次；两臂的日期天然对齐。\n"
        f"# 目标国**写死**（不按国力排序）：排序需要一个不稳定谓词，写死才能保证两臂同压。\n"
        f"zz_stress_tick = {{\n"
        f"{TAB}# ① 大战：一场博弈由**发起国自己**开（每月脉冲每国都跑，所以判据必须收到一个 tag 上）。\n"
        f"{TAB}if = {{\n" + _fire_guard("zz_stress_war_fired", WAR_DATE) + f"{wars}{TAB}}}\n"
        f"\n"
        f"{TAB}# ② 连锁破产：抽干这些国家的国库（引擎自己走完「违约 → 破产」那一步）。\n"
        f"{TAB}if = {{\n"
        + _fire_guard("zz_stress_break_fired", BREAK_DATE)
        + f"{breakers}{TAB}}}\n"
        f"\n"
        f"{TAB}# ③ 革命潮：这些国家每半年吃一波激进派（真进运动系统）。\n"
        f"{TAB}if = {{\n"
        f"{radicals_guard}"
        f"{TAB * 2}# 每一波各自一个 fired 变量：四波之间互不影响（少一波也看得出是哪一波）。\n"
        f"{radical_blocks}"
        f"{TAB}}}\n"
        f"}}\n"
    )


def on_actions_text() -> str:
    """每月脉冲挂上那个效果（**不碰任何原版钩子**：只加自己的 on_action 条目）。"""
    return (
        f"{GEN_HEADER}\n"
        f"# 只挂一条：每月脉冲调 `zz_stress_tick`。\n"
        f"# ⚠️ 本文件只有 `on_monthly_pulse_country` 一个块 —— 探针 mod 与真 mod 各自管各自的，\n"
        f"#    不在这里覆盖原版的 on_action 文件（那是 R3 的整文件替换，F2 明令禁用）。\n"
        f"on_monthly_pulse_country = {{\n"
        f"{TAB}zz_stress_tick = yes\n"
        f"}}\n"
    )


def metadata_text() -> str:
    """mod 元数据（启动器要的那一份；`supported_game_version` 与真 mod 同口径）。"""
    return (
        "{\n"
        '  "name": "SITAI 压力剧本探针（阶段 4 ④：大战 + 连锁破产 + 革命潮）",\n'
        f'  "id": "sitai.stress.{MOD_NAME}",\n'
        '  "version": "0.1.0",\n'
        '  "supported_game_version": "1.14.3",\n'
        '  "short_description": "阶段 4 ④ 的标准压力剧本。**不是产品 mod**：'
        "它只把世界推到高压状态（博弈/破产/革命潮），让 G-EXIT-3 的对照能在同一个世界里做。"
        '由 tools/pdx/stress_probe.py 生成，改这里没用。",\n'
        '  "tags": [],\n'
        '  "relationships": [],\n'
        '  "game_custom_data": { "multiplayer_synchronized": false }\n'
        "}\n"
    )


def files() -> dict[str, str]:
    """``相对路径 -> 文本``（游戏侧 ``.txt`` 带 BOM，与既有两个探针同口径）。"""
    return {
        ".metadata/metadata.json": metadata_text(),
        "common/scripted_effects/zz_stress_effects.txt": effects_text(),
        "common/on_actions/zz_stress_on_actions.txt": on_actions_text(),
    }


def write(root: Path | None = None) -> list[Path]:
    """把剧本写到 ``root``（默认：仓库外的临时目录），返回写出的文件。

    ⚠️ 与 `modgen` 同一条纪律：**产物一律由这里生成**，改产物没用。
    游戏侧文本带 UTF-8 BOM（原版 `common/` 下的文件实测都带），JSON 不带。
    """
    base = root or (Path(tempfile.gettempdir()) / MOD_NAME)
    written: list[Path] = []
    for rel, text in sorted(files().items()):
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        encoding = "utf-8-sig" if rel.endswith(".txt") else "utf-8"
        path.write_text(text, encoding=encoding, newline="\n")
        written.append(path)
    return written


def dest() -> Path:
    """剧本在**用户 mod 目录**里的落点（`perf_compare.py --stress` 装的就是它）。"""
    return config.LOCAL_MODS / MOD_NAME


__all__ = [
    "BREAK_DATE",
    "BREAK_TAGS",
    "MOD_NAME",
    "RADICALS_PER_WAVE",
    "RADICAL_DATES",
    "RADICAL_TAGS",
    "TREASURY_DRAIN",
    "WAR_DATE",
    "WAR_PAIRS",
    "dest",
    "effects_text",
    "files",
    "metadata_text",
    "on_actions_text",
    "write",
]
