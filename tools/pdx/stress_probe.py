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

自报：每一波落地时写一行（格式写死在这里与用例里）
--------------------------------------------------
格式 ``ZZPROBE STRESS;<KIND>;<wave>;<target>``（与 `ab_probe` 的 `ZZPROBE AB;…` 同型，
只是前缀不同 ⇒ 两族分析器互不误读：`ab.py:114` 要 `ZZPROBE AB;`、`h1.py:78` 要 `ZZPROBE (H1|H3);`）：

| 字段 | 取值 | 说明 |
|---|---|---|
| 前缀 | `ZZPROBE STRESS` | 固定；`STRESS` 这一族只有本模块写 |
| `<KIND>` | `WAR` / `BREAK` / `RADICAL` | 三条压力各一个分类 |
| `<wave>` | `1837.7.1` 这样的日期字面量 | 这一波**该在**哪一天释放（剧本常量，**不是**事发当时日期） |
| `<target>` | 目标国 tag | 大战写成 `发起国>目标国`（一场博弈有两端，只写一端分不出是哪一对） |

例：`ZZPROBE STRESS;WAR;1837.1.1;GBR>FRA`、`ZZPROBE STRESS;BREAK;1837.7.1;MEX`、
`ZZPROBE STRESS;RADICAL;1838.1.1;RUS`。**每一个 (KIND, wave, target) 只有一行** ——
发射点各自套在 ``if = { limit = { c:<tag> ?= this } … }`` 里（见 :func:`report_emitter`）。
为什么必须有守卫：`on_monthly_pulse_country` 是**逐国**跑这个效果的，不收敛到**一个** tag 上
就会写出 N 行，而 N（当时存在的国家数）在两臂之间会随世界演化分叉 ⇒ 比对会报**假**的不等。

**行数 = 施加次数**：自报与施加**写在同一个守卫块里**，而且自报排在施加**之后**
（:func:`report_emitter` 的 ``apply``）⇒ 一次施加写一行、只写一行。比对保留重复行
（`compare_report_sequences` 逐位比排序后的多重集），于是"同一波同一国多抽了一次"
一定判不等，且差异信息里带**次数**（`ReportDiff.describe` / `describe_count_differences`）。
⇒ 这就是 `阶段4-压力剧本-口径.md` §2.1③ 那句"两臂受的压一样"的可证形式。

谁读它：`tools/probe/perf_compare.py` 在两臂跑完后比对两份序列，**不等即出声失败**
（P13：不许静默降级）。"对照能不能称受控"就挂在这一条上 —— 口径页 §2.1③ 把它列为六条缺口里
最便宜、最承重的一条（在那之前，"两臂受的压一样"只能靠嘴说）。

下面两条是 `t50` 加观测时读出来的"不报错但会错"，`t63` 的处理状态各自写明：

* ① **破产波逐国重复施加**（`c:MEX ?= { add_treasury = … }` 缺"当前国就是这个 tag"的判据 ⇒
  每月每个目标国被**每一国**各抽一次，约 N 次）—— **已修**（`t63`）：施加改成与另外两条波同型的
  `if = { limit = { c:<tag> ?= this } … }`，**每国每月恰好一次**，且**次数进了自报与比对**
  （见上面那段）。改前/改后的机器可判读数在 `tools/tests/test_stress_probe.py` 里钉住。
* ② **革命潮那 8 条裸 `c:TAG ?= this`**（:func:`effects_text` 的 ③ 段）是**并列的触发器**（默认 AND），
  8 个互斥的 tag 不可能同时成立 ⇒ 这一波**可能一次都没释放过**。【仍开放】—— 归实机侦察卡；
  若真如此，两臂的自报里**一条 `RADICAL` 都不会有** ⇒ `perf_compare` 的"序列非空"判据会
  **硬报错**，而不是"两边都空所以算相等"（那正是这条判据存在的理由）。
  ⚠️ 因为那一族**没有**"行数 = 次数"的保证（它的施加是外层守卫下的 `every_scope_state`），
  本模块只对它做了"每 tag 一行"的收敛，**次数**问题留在这张侦察卡里一起判。
"""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pdx import config

if TYPE_CHECKING:
    from collections.abc import Sequence

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


# ── 自报（格式见模块 docstring「自报」一节）────────────────────────────────
#
#: 自报行的**固定前缀**。**与 `AB` / `H1` 两族不同前缀是有意的**：`ab.py:114` 的
#: 行正则要求 `ZZPROBE AB;`、`h1.py:78` 要求 `ZZPROBE (H1|H3);` ⇒ 三个家族互不误读。
REPORT_PREFIX = "ZZPROBE STRESS"

#: 三条压力的分类位。**只能是大写字母**（`[A-Z]+`，与 `ab.py:114` 的 kind 同口径）：
#: 下划线会把分类位截断，分析器就再也认不出这一行。
KIND_WAR = "WAR"
KIND_BREAK = "BREAK"
KIND_RADICAL = "RADICAL"

#: 分类位全集：解析器按它判"形状对不对"——不认识的分类**记进 malformed**，不静默丢（P13）。
REPORT_KINDS: tuple[str, ...] = (KIND_WAR, KIND_BREAK, KIND_RADICAL)

#: 自报行的行正则：`ZZPROBE STRESS;<KIND>;<wave>;<target>`。
#: `wave` 是 `YYYY.M.D` 日期字面量；`target` 是 tag（大战写成 `发起国>目标国`）。
#: 用 `search` 而不是 `fullmatch`：日志行前面还有 `[时间][来源]: <文件>:<行>:` 那一串前缀。
REPORT_LINE_RE = re.compile(
    rf"{re.escape(REPORT_PREFIX)};"
    r"(?P<kind>[A-Z]+);"
    r"(?P<wave>\d{4}\.\d{1,2}\.\d{1,2});"
    r"(?P<target>[A-Z0-9>]+)"
)


def report_line(kind: str, wave: str, target: str) -> str:
    """一条自报行的文本 —— **格式的唯一来源**（生成器与用例都调它，不手抄）。"""
    return f"{REPORT_PREFIX};{kind};{wave};{target}"


def report_emitter(
    kind: str, wave: str, target: str, *, tag: str, tabs: int = 2, apply: str = ""
) -> str:
    """一条自报的**发射块**：``if = { limit = { c:<tag> ?= this } <施加> debug_log = "…" }``。

    ``tag`` = "谁来说这句话"（也是"谁来做这件事"）：守卫保证**只有那个国家**写这一行。
    它不是装饰 —— 效果是**逐国**跑的（模块 docstring「自报」一节），没有守卫就会写出 N 行，
    而 N 在两臂之间可以不同 ⇒ 比对会报假不等。

    ⚠️ **给了 ``apply`` 时，行数 = 施加次数**：施加语句与自报**在同一个守卫里**
    （而且自报排在施加**之后** —— 走到它说明这一条已经执行过），一次施加写一行、只写一行。
    这就是"两臂序列相等 ⇒ 施加次数相同"的机器形式：多重集比对**保留重复**，而重复即次数。
    """
    body = "".join(f"{TAB * (tabs + 1)}{line}\n" for line in apply.splitlines() if line.strip())
    return (
        f"{TAB * tabs}if = {{\n"
        f"{TAB * (tabs + 1)}limit = {{ c:{tag} ?= this }}\n"
        f"{body}"
        f'{TAB * (tabs + 1)}debug_log = "{report_line(kind, wave, target)}"\n'
        f"{TAB * tabs}}}\n"
    )


@dataclass(frozen=True, slots=True)
class ReportScan:
    """从一段文本里扫出来的自报行：**合法的** + **形状不对的**（后者不许被吞掉，P13）。"""

    lines: tuple[str, ...] = ()
    malformed: tuple[str, ...] = ()


def scan_report_lines(text: str) -> ReportScan:
    """扫出文本里（通常是日志）的全部压力自报行。

    ⚠️ 三条"不许静默"的规矩：① 含前缀但**形状不对**的行进 ``malformed``；
    ② 分类位不认识（比如格式漂成 `STRESS;BOGUS;…`）也进 ``malformed``；
    ③ 合法行**原样保留重复** —— 重复本身就是"这一波释放了两次"的证据，别去重。

    注释行（`#` 开头）直接跳过：自报一定是引擎写进日志的行，**注释不可能是自报**；
    跳过它之后这个扫描器也能直接喂**生成物**（`effects_text()` 的头部注释里就印着格式），
    于是"生成物里的自报行是否条条合法"也是一条可判的用例。
    """
    lines: list[str] = []
    malformed: list[str] = []
    for raw in text.splitlines():
        if raw.lstrip().startswith("#"):
            continue
        if REPORT_PREFIX not in raw:
            continue
        match = REPORT_LINE_RE.search(raw)
        if match is None or match.group("kind") not in REPORT_KINDS:
            malformed.append(raw.strip())
            continue
        lines.append(match.group(0))
    return ReportScan(tuple(lines), tuple(malformed))


def report_wave(line: str) -> str:
    """从一行自报里取**波次（日期）**那位；取不到给 ``"?"``（会被写进差异信息里，不冒充日期）。"""
    match = REPORT_LINE_RE.search(line)
    return match.group("wave") if match is not None else "?"


@dataclass(frozen=True, slots=True)
class ReportDiff:
    """两份自报序列的**第一处不同**（比对口径见 :func:`compare_report_sequences`）。

    ``left_count`` / ``right_count`` = **这一行在各自序列里出现几次**。因为
    "行数 = 施加次数"（见 :func:`report_emitter`），这两个数就是**施加次数**
    —— 差异信息里必须出现它们，否则读的人看不出"是次数问题"（t63 的要求）。
    """

    index: int
    left: str | None
    right: str | None
    wave: str
    left_count: int = 0
    right_count: int = 0

    def describe(self, *, left_label: str = "vanilla", right_label: str = "ours") -> str:
        """可读的差异：**第几处 + 哪一波 + 两臂各自那一行 + 各自的施加次数**。"""
        where = f"第 {self.index + 1} 处不同（波次 {self.wave}）"
        if self.left is None:
            return (
                f"{where}：{right_label} **多出**一行 {self.right!r}（共 {self.right_count} 次），"
                f"{left_label} 没有"
            )
        if self.right is None:
            return (
                f"{where}：{right_label} **少**一行 —— {left_label} 有 {self.left!r}"
                f"（共 {self.left_count} 次），{right_label} 没有"
            )
        return (
            f"{where}：{left_label}={self.left!r}（{self.left_count} 次） ／ "
            f"{right_label}={self.right!r}（{self.right_count} 次）"
        )


def count_report_lines(lines: Sequence[str]) -> dict[str, int]:
    """每一条自报行出现了几次 —— **它就是"这一波这一国施加了几次"**（行数 = 次数）。"""
    counts: dict[str, int] = {}
    for line in lines:
        counts[line] = counts.get(line, 0) + 1
    return counts


def describe_count_differences(
    left: Sequence[str],
    right: Sequence[str],
    *,
    left_label: str = "vanilla",
    right_label: str = "ours",
) -> list[str]:
    """**次数层面**的差异（多重集差）：只在一侧出现的行，以及两侧次数不同的行。

    为什么要单独一层：:func:`compare_report_sequences` 只报**第一处**不同，而"次数不同"最常见的
    长相是"同一国多施加了一次" —— 第一处不同会落在**它后面**那些行上（排序后位置变了），
    只读那一条信息看不出根因。本函数按行把两侧次数并排列出来，交给跑者印进失败信息。
    """
    counts_left = count_report_lines(left)
    counts_right = count_report_lines(right)
    out: list[str] = []
    for line in sorted(set(counts_left) | set(counts_right)):
        one, other = counts_left.get(line, 0), counts_right.get(line, 0)
        if one != other:
            out.append(f"{line!r}：{left_label} {one} 次 / {right_label} {other} 次")
    return out


def compare_report_sequences(left: Sequence[str], right: Sequence[str]) -> ReportDiff | None:
    """两份序列哪里不一样；**一样就返回 ``None``**（这是"受控"的机器判据）。

    ⚠️ 比对前两侧都**排序**（"规范序"）。为什么：同一月里各 tag 的自报谁先谁后，取决于
    引擎遍历国家的顺序 —— 那不是"受的压"，算进判据会报**假**不等（世界一分叉，国家集合
    与遍历顺序就可能不同）。排序**不会**把"某一波没落地"藏起来：那时某一行**根本不存在**，
    长度就不同。波次也写在行里（剧本常量）⇒ 排序不丢"是哪一波"。

    ⚠️ **重复行保留、且计入比较**：行数 = 施加次数（:func:`report_emitter`）⇒
    "同一波同一国多抽了一次"表现为多出一行，逐位比就一定不等，差异信息里带次数。
    """
    ordered_left = sorted(left)
    ordered_right = sorted(right)
    counts_left = count_report_lines(ordered_left)
    counts_right = count_report_lines(ordered_right)
    for index in range(max(len(ordered_left), len(ordered_right))):
        one = ordered_left[index] if index < len(ordered_left) else None
        other = ordered_right[index] if index < len(ordered_right) else None
        if one != other:
            return ReportDiff(
                index=index,
                left=one,
                right=other,
                wave=report_wave(one or other or ""),
                left_count=counts_left.get(one, 0) if one is not None else 0,
                right_count=counts_right.get(other, 0) if other is not None else 0,
            )
    return None


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
    """每月脉冲调用的那一个效果（三条压力都在这里，**按国家各自判**）。

    ⚠️ **施加与自报在同一个守卫里**（`:func:`report_emitter` 的 ``apply``）⇒ **行数 = 施加次数**。
    大战与破产两族**每国每月恰好一次**（这就是修掉"逐国各抽一次"的那处缺陷）；革命潮那一族的
    施加是外层守卫下的 `every_scope_state`，它的"次数"问题归另一张卡（模块 docstring 的②）。

    **时点语义（`t73` 按部署产物逐行核过）**：六条守卫**全是严格大于**（WAR `> 1837.1.1`、
    BREAK `> 1837.7.1`、四波 RADICAL `> 1837.1.1 / 1837.7.1 / 1838.1.1 / 1838.7.1`）⇒ 每一波在
    **其后第一个月度脉冲**落地（不是当天）。所以自报行数是**跑多久**的函数：`12` 月停在 1837.1.1、
    **恰好在首波之前 ⇒ 0 行是预期、不是失败**；`15` 月见首波 **13** 行（WAR ×5 + RADICAL[1] ×8）；
    `21` 月累计 **29**（再加 BREAK ×8 + RADICAL[2] ×8）；跑满 `33` 月才是设计总量 **45**。
    判「钩子挂上了没有」用 15 月就够 —— 这条口径由 `t73` 的实机自证用。
    """
    wars = "".join(
        report_emitter(
            KIND_WAR,
            WAR_DATE,
            f"{initiator}>{target}",
            tag=initiator,
            apply=(
                "create_diplomatic_play = {\n"
                f"{TAB}type = {kind}\n"
                f"{TAB}escalation = 80\n"
                f"{TAB}target_country = c:{target}\n"
                "}"
            ),
        )
        for initiator, target, kind in WAR_PAIRS
    )
    breakers = "".join(
        report_emitter(
            KIND_BREAK,
            BREAK_DATE,
            tag,
            tag=tag,
            apply=f"add_treasury = {TREASURY_DRAIN}",
        )
        for tag in BREAK_TAGS
    )
    radical_blocks = "".join(
        f"{TAB}if = {{\n"
        + _fire_guard(f"zz_stress_radicals_{index}", date)
        + f"{TAB * 2}# 这一波落到哪些国家：**每个 tag 各自一行**（自报的守卫就是「当前国是不是它」）。\n"
        + "".join(report_emitter(KIND_RADICAL, date, tag, tag=tag) for tag in RADICAL_TAGS)
        + f"{TAB * 2}every_scope_state = {{\n"
        f"{TAB * 3}add_radicals_in_state = {{ value = {{ add = {RADICALS_PER_WAVE} }} }}\n"
        f"{TAB * 2}}}\n"
        f"{TAB}}}\n"
        for index, date in enumerate(RADICAL_DATES, start=1)
    )
    # ⚠️ 这 8 个 tag 有两个坑，两个都撞过（`t73`，判据必须落在**语义**上）：
    #    ① 直接跟在 `if = {` 后面 ⇒ 引擎把它们当**效果**读 ⇒ 8 行 `Unknown effect c:GBR`
    #       （响亮失败；引擎对 `scripted_effects` 报的行号偏移还不恒定，本文件实测 Δ=5 ⇒ 按内容锚）。
    #    ② 平铺进 `limit = {` ⇒ `limit` 是**与** ⇒「当前国同时是这 8 个 tag」**恒假** ⇒
    #       自报 0 行、`add_radicals_in_state` 一次都不执行，而引擎**不再报错**（首波实测：
    #       WAR×5 到齐、RADICAL = 0 vs 预期 8）—— 安静失败比响亮失败更坏。
    #    ⇒ 正确写法 = 收进 **`OR`**：每月脉冲对「自己是不是这 8 国之一」判一次，
    #      8 国各命中一次 ⇒ 每波正好 8 行、每国各自的 `fired` 变量各设各的。
    radicals_guard = (
        f"{TAB * 2}limit = {{\n"
        f"{TAB * 3}OR = {{\n"
        + "".join(f"{TAB * 4}c:{tag} ?= this\n" for tag in RADICAL_TAGS)
        + f"{TAB * 3}}}\n"
        + f"{TAB * 2}}}\n"
    )
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
        f"#\n"
        f"# ⚠️ **施加语句一律套在 `if = {{ limit = {{ c:<tag> ?= this }} … }}` 里**：这个效果由\n"
        f"#    `on_monthly_pulse_country` **逐国**调用 ⇒ 少了守卫，每个目标国会**被每一国各抽一次**\n"
        f"#    （每月约 N 次，N = 世界上的国家数），而「次数」正是两臂要比的东西之一。\n"
        f"#\n"
        f"# **自报**（`{REPORT_PREFIX};<KIND>;<wave>;<target>`，格式见 pdx.stress_probe 的模块 docstring）：\n"
        f"# 每一波落地时由**一个写死的国家**写一行，且**写在同一个守卫里** ⇒ **行数 = 施加次数**。\n"
        f"# 两臂的这两串行必须逐行相等（含重复行），`tools/probe/perf_compare.py` 跑完就比，不等即出声失败（P13）。\n"
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
        f"{TAB * 2}# 外面那个 `limit = {{ OR = {{ … }} }}` 收的就是上面 8 个 tag（**是 `OR` 不是 `AND`**：\n"
        f"{TAB * 2}# 平铺进 `limit` 会恒假 ⇒ 自报 0 行且压力一次不执行，而引擎不报错）；\n"
        f"{TAB * 2}# 每一波各自一个 fired 变量：四波之间互不影响（少一波也看得出是哪一波）。\n"
        f"{radical_blocks}"
        f"{TAB}}}\n"
        f"}}\n"
    )


#: 转调用 on_action 的名字（**我们的命名空间**，与原版任何 on_action 键都不同名）。
#:
#: 为什么需要它：`on_action` 块里**不许**直接写脚本效果调用 —— 顶层键只有官方那五种
#: （`effect` / `events` / `on_actions` / `random_events` / `trigger`）。旧写法（块里直接写
#: `zz_stress_tick = yes`）会被引擎拒掉整份文件：`Unexpected token: zz_stress_tick, near line: 6`
#: （`t64` 侦察局实测）⇒ 症状是**钩子一次都没挂上**（那一局 0 行 `ZZPROBE STRESS;`）。
#: 官方追加配方是**转调**：`on_monthly_pulse_country = { on_actions = { <我们的 on_action> } }`
#: （原版 `common/on_actions/_on_actions.md:113-128`；本仓
#: `docs/victoria3-modding/04-脚本系统.md` §3.4 逐字引用）。
#:
#: **原版自己就在同一个脉冲上这么转调**（`t73` 只读核过）：`GAME/common/on_actions/00_code_on_actions.txt`
#: 的 `on_monthly_pulse_country` 块内（`:1556-1563`）写着 `on_actions = { coup_monthly_events … }`；
#: 被转调的名字定义在 `common/on_actions/00_on_actions_monthly.txt:12` 的**顶层命名块**里。
#: 原版把两半分在**两份** on_actions 文件，我们把 `TICK_ON_ACTION` 定义在**同一份**（少一个文件、只多一行）。
TICK_ON_ACTION = "zz_stress_monthly_tick"

#: 转调目标里调的那个**脚本效果**名（它定义在 `zz_stress_effects.txt`；名字不许改 ——
#: 三条压力的语义与自报都挂在它上面）。
TICK_EFFECT = "zz_stress_tick"


def on_actions_text() -> str:
    """每月脉冲挂上那个效果（**不碰任何原版钩子**：只加自己的 on_action 条目）。

    ⚠️ **两条形状约束**（都被实机撞过；`tools/tests/test_stress_probe.py` 逐条钉住）：

    1. `on_monthly_pulse_country` 块里**只能**出现官方那五种顶层键。直接写脚本效果调用
       （`zz_stress_tick = yes`）会被整份拒绝：`Unexpected token: zz_stress_tick, near line: 6`
       —— `t64` 侦察局实测，症状是**钩子一次都没挂上**（那一局 0 行 `ZZPROBE STRESS;`）。
    2. 转调目标要定义成一个**顶层命名块**（`<名字> = { effect = { … } }`）：放在**同一份**文件里
       （我们这样）或**另一份 `common/on_actions/*.txt`**（原版那样）都合法。**不许**的是：
       (a) 塞进 `common/scripted_effects/*.txt`（阶段 2 踩过：`No on_action scripted with tag … cannot link`）；
       (b) 在第二个文件里**再声明一次原版那个键**（`on_monthly_pulse_country = { effect = … }`）—— 那会触发
       "There is more than one 'effect' defined using most recent"（原话记在
       `docs/victoria3-modding/02-Mod结构与加载.md:262`）⇒ 盖掉原版 effect（R3 类风险，F2 禁用）。
    """
    return (
        f"{GEN_HEADER}\n"
        f"# 只做一件事：每月脉冲**转调**我们自己的 on_action `{TICK_ON_ACTION}`。\n"
        f"# ⚠️ on_action 块内**不许**直接写脚本效果调用（引擎原话 `Unexpected token: zz_stress_tick, near line: 6`）：\n"
        f"#    官方只认这五种顶层键 —— `effect` / `events` / `on_actions` / `random_events` / `trigger`。\n"
        f"# 原版自己在同一个脉冲上就是**转调**：`00_code_on_actions.txt:1556-1563` 的 `on_monthly_pulse_country`\n"
        f"# 块内写着 `on_actions = {{ coup_monthly_events … }}`；名字定义在 `00_on_actions_monthly.txt:12`。\n"
        f"# ⚠️ 本文件只有 `on_monthly_pulse_country` 一个**原版键**的块 —— 探针 mod 与真 mod 各自管各自的，\n"
        f"#    不在这里覆盖原版的 on_action 文件（那是 R3 的整文件替换，F2 明令禁用）。\n"
        f"on_monthly_pulse_country = {{\n"
        f"{TAB}on_actions = {{ {TICK_ON_ACTION} }}\n"
        f"}}\n"
        f"\n"
        f"# 转调目标：按官方配方**定义在同一份文件里**；它的 `effect` 块里才调脚本效果。\n"
        f"{TICK_ON_ACTION} = {{\n"
        f"{TAB}effect = {{\n"
        f"{TAB * 2}{TICK_EFFECT} = yes\n"
        f"{TAB}}}\n"
        f"}}\n"
    )


def mod_game_version(mod_root: Path | None = None) -> str:
    """仓库产物 `.metadata/metadata.json` 里的 ``supported_game_version``（**现读，不手抄**）。

    为什么要它：探针 mod 的元数据里那一格原来**写死 `1.14.3`**，而本仓产物当天是 `1.14.4`
    （t50 读出来的事实，t63 修）。版本对不上时**启动器可能干脆不挂这份探针**，症状是
    "0 行自报" —— 虽然会被 `perf_compare` 的受控性判据兜住，但那一局实机窗口就白烧了。
    所以与 `perf_compare` 的壳 mod **同源**（同一个函数，单一来源；P9）。

    读不到就**报错**（P13）：猜一个版本号写进 metadata，症状是"启动器里那个 mod 灰掉/不匹配"，
    而这条链上没人会去看。
    """
    meta = (mod_root or (config.REPO / "mod")) / ".metadata" / "metadata.json"
    if not meta.is_file():
        raise RuntimeError(f"找不到仓库产物的元数据：{meta} —— 先跑 `v3 modgen`")
    payload = json.loads(meta.read_text(encoding="utf-8"))
    version = payload.get("supported_game_version") if isinstance(payload, dict) else None
    if not isinstance(version, str) or not version:
        raise RuntimeError(f"{meta} 里没有 supported_game_version —— 先跑 `v3 modgen` 重生成")
    return version


def metadata_text(mod_root: Path | None = None) -> str:
    """mod 元数据（启动器要的那一份）。

    ``supported_game_version`` **现读仓库产物**（:func:`mod_game_version`）—— 与
    `perf_compare` 的壳 mod 同一个来源；以前这里写死 `1.14.3` 而产物是 `1.14.4`（t63 修）。
    """
    return (
        "{\n"
        '  "name": "SITAI 压力剧本探针（阶段 4 ④：大战 + 连锁破产 + 革命潮）",\n'
        f'  "id": "sitai.stress.{MOD_NAME}",\n'
        '  "version": "0.1.0",\n'
        f'  "supported_game_version": "{mod_game_version(mod_root)}",\n'
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
    "KIND_BREAK",
    "KIND_RADICAL",
    "KIND_WAR",
    "MOD_NAME",
    "RADICALS_PER_WAVE",
    "RADICAL_DATES",
    "RADICAL_TAGS",
    "REPORT_KINDS",
    "REPORT_LINE_RE",
    "REPORT_PREFIX",
    "TICK_EFFECT",
    "TICK_ON_ACTION",
    "TREASURY_DRAIN",
    "WAR_DATE",
    "WAR_PAIRS",
    "ReportDiff",
    "ReportScan",
    "compare_report_sequences",
    "count_report_lines",
    "describe_count_differences",
    "dest",
    "effects_text",
    "files",
    "metadata_text",
    "mod_game_version",
    "on_actions_text",
    "report_emitter",
    "report_line",
    "report_wave",
    "scan_report_lines",
    "write",
]
