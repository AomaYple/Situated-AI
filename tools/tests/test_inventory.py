"""全仓「机械数字」的盘点看守 —— 防止又长出一张无人看守的表。

为什么需要它
-----------
这一轮反复踩到同一个形态：**文档里有一堆机械可核对的数字，而没有任何东西在看守**。
实测盘点（doc 13 整体生成、不计入）：

* 表格 578 张 —— 33 张由 `v3 tables` 生成、21 张有测试看守，
  其余里 **126 张含「真统计量列」而零看守**；
* 散文数字 133 个 —— 只有 19 个等于本文件某条断言的期望值。

数字本身会随游戏升级而漂，但**「又新增了一张无人看守的表」这件事不会有人发现** ——
除非把盘点本身变成检查。这就是本文件。

判定规则（宁可宽，别漏）
---------------------
一张表算「含真统计量列」要同时满足：

1. 有**非行号、非判读**的列（排除 `#` / `行` / `状态` / `类型` … —— 那些不是统计量）；
2. 该列名像统计量（次数 / 数量 / 文件数 / 条目 / 字节 / 定义数 / count / entries …）；
3. 该列 70% 以上的单元格是纯数字。

口径的局限（写清楚，免得被当成「全覆盖」）
--------------------------------------
* 它**只认表**，不认散文里的数字；散文那面的现状另记在下面的基线里；
* 它判不出「数字对不对」—— 那是 `v3 tables` / `v3 verify` / 各看守测试的事。
  这条只管**有没有人管**。

两个余额的终点（以及剩下的 61 个散文数字为什么不算欠债）
----------------------------------------------------
**表**那一面已经归零（`UNGUARDED_TABLE_BUDGET = 0`）：107 张原先无人看守的表
全部接进了 `v3 tables`，另 8 张写进 :data:`NOT_GENERATED` 并各有理由 ——
口径复现不出（doc 06 函数频次）、作者的分组判断（doc 17 基因分组）、
统计对象是**本机订阅的 mod**（doc 02 ×2 / doc 12 / doc 14 §1.4 / doc 16 ×2）。

**散文**那一面还剩 61 个，分六类，每一类都给了判断依据：

1. **本机 mod 侧数字**（doc 02 的 42 / 23、doc 06 的 18、doc 12 的 4、
   doc 14 的 0、README 的 4,750 / 4,777 / 13）—— 换台机器、退订一个 mod 就变。
   与 `NOT_GENERATED` 里那几张表同一个理由：**这不是「数字过期」，是另一台机器**。
2. **历史勘误值**（如 doc 05 的 6125 / 6121、doc 17 的修正记录表）——
   记录的是「以前写错过什么」。它们**天生不可能有期望值**，
   除非把「曾经错过的数」也做成断言（那是自欺）。
3. **算术示例**（doc 04 的 15、doc 07 的 15、doc 05 的 3 / 7）——
   算的是「`add=5 → multiply=4 → max=10` 得多少」，不是从游戏里数出来的量。
4. **官方 `.md` 里读到的常量与清单**（doc 07 的 512 通道数、41 / 20 个标题）——
   **原文如此**。它们是引用，改了就不再是引用；要核对只能核 sha256（另有测试）。
5. **跟排版走的行号与局部计数**（doc 03 的 49、doc 15 的 9 / 5 / 2 之类）——
   与 doc 05 那几张表的「起始行」列同性质：改一行就全废，机械重算只会制造噪声。
6. **有意并列的两个口径**（doc 17 的 954 / 955、179 / 178，doc 15 的 9 / 26 / 35）——
   作者在同一句里同时给出两个口径的数，本身就是在说明口径差异。
   把其中一个做成断言，反而会诱导下一个人「统一」掉那个差异。

换句话说：余额的终点不是「散文里一个数字都没有」，而是**剩下的每个数字都答得出
「为什么它不该由工具算」**。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pdx import config, docgen

if TYPE_CHECKING:
    from pathlib import Path

#: doc 13 由 `v3 index` **整体重新生成**，其中的数字不可能过期，故不参与盘点。
FULLY_GENERATED_DOCS = frozenset({"13-common全量键名索引.md"})

#: 这些列名**不是统计量**：行号、序号、以及作者的判读标签。
NON_STAT = (
    "#",
    "行",
    "序号",
    "状态",
    "类型",
    "值类型",
    "领域",
    "作用方向",
    "首例",
    "首现位置",
    "官方 md 行",
    "建议",
    "备注",
    "说明",
)

#: 列名里出现这些词才可能是统计量。
STAT_HINT = (
    "次数",
    "数量",
    "文件数",
    "条目",
    "字节",
    "定义数",
    "键数",
    "合计",
    "总计",
    "count",
    "entries",
    "params",
    "blocks",
)

#: **未看守的机械表数量上限**。这是「欠债余额」：只许减少，不许增加。
#:
#: 进度 125 → 82 → 58 → 44 → 29 → 19 → 7 → **0**：doc 05 的两张「假脚本化」表、
#: doc 04/16 的「用了多少次」各一张、doc 14 整族 21 张、doc 16 整族 33 张、doc 17 整族 24 张、
#: doc 06 的 5 张 + doc 15 的 7 张、doc 04 的 15 张（另加 4 张原先没被判成统计表的汇总表）、
#: doc 03/10/11/18/20 的 6 张 + doc 14 的 2 张令牌表、**doc 05 剩下的 7 张**。
#: 生成表总数 31 → 77 → 107 → 119 → 139 → 149 → 157 → **164**。
#:
#: **0 就是终点**：剩下的都在 :data:`NOT_GENERATED` 里，每一条都写明了
#: 「为什么不能机械生成」。这个数再涨回来就意味着**新长出了一张没人管的表** ——
#: 那正是这条预算要拦住的事。
UNGUARDED_TABLE_BUDGET = 0

#: **无人看守的散文数字数量上限**（表格之外）。见模块 docstring 的口径。
#:
#: 进度 133（基线）→ 115 → 61 → 57 → 49 → 34：前两轮把「口径唯一、可机械复算」的散文数字
#: **登记成了 `v3 verify` 断言**（断言表 81 → 135 → 141 → 151 条），于是它们从「无人看守」
#: 变成「每次核验」。**doc 05/06/08** 那一批又移出 15 个（jomini 未接管文件 15、
#: 无 ``decimals`` 的键 31、``_factor`` 5、其它尾段 9、数字开头 3、带缩进 7、
#: ``fonts.font`` 的 53 个 ``languages``、texticon 432、``.yml`` 去重名 1,855 …）。
#:
#: **0 就是终点**，但它的含义要说清：终点不是「散文里一个数字都没有」，而是
#: **剩下每个没被断言看守的数字都在 :data:`PROSE_NOT_COMPUTED` 里写明了理由** ——
#: 这个预算只数「既没有断言、也没有理由」的那些，而且**必须正好等于**实际个数
#: （见 :func:`test_剩下的散文数字都写明了理由`：它是承诺，不是上限）。
UNGUARDED_PROSE_BUDGET = 34


def _tables(path: Path) -> list[tuple[int, str, list[list[str]]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[tuple[int, str, list[list[str]]]] = []
    i = 0
    while i < len(lines):
        if (
            lines[i].startswith("|")
            and i + 1 < len(lines)
            and lines[i + 1].startswith("|")
            and set(lines[i + 1].strip()) <= set("|-: ")
        ):
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].startswith("|"):
                rows.append([c.strip() for c in lines[j].strip().strip("|").split("|")])
                j += 1
            out.append((i + 1, lines[i], rows))
            i = j
        else:
            i += 1
    return out


def _is_number(cell: str) -> bool:
    return bool(re.fullmatch(r"\**[\d][\d,]*\**", cell.strip()))


def _stat_columns(header: str, rows: list[list[str]]) -> list[str]:
    """表里「看起来是统计量」的列名，判据见模块 docstring。"""
    labels = [c.strip() for c in header.strip().strip("|").split("|")]
    out: list[str] = []
    for ci, label in enumerate(labels):
        low = label.lower()
        if any(x in label for x in NON_STAT):
            continue
        vals = [r[ci] for r in rows if ci < len(r)]
        if not vals or sum(_is_number(v) for v in vals) < max(2, int(len(vals) * 0.7)):
            continue
        if any(h in label or h in low for h in STAT_HINT):
            out.append(label)
    return out


def _generated_headers() -> dict[str, list[tuple[str, int]]]:
    """``文档名 → [(表头, occurrence), …]``。

    **必须带上 occurrence**：一条 spec 只覆盖**同表头的第 N 张**表。
    doc 14 里有好几张表头都是 ``| 字段 | 实测次数 | 说明 |``，而生成器只管其中一张 ——
    只按表头文本判「已看守」会把其余几张也算成有人管，于是盘点**少报**，
    给出虚假的「快做完了」。实测第一版就是这么错的（125 一下掉到 116，
    而实际只接了 3 张）。
    """
    out: dict[str, list[tuple[str, int]]] = {}
    for t in docgen.targets():
        for s in t.specs:
            out.setdefault(t.name, []).append((s.header, getattr(s, "occurrence", 0)))
    return out


def _is_guarded_by_spec(
    headers: list[str], index: int, generated: dict[str, list[tuple[str, int]]], doc: str
) -> bool:
    """第 ``index`` 张表是否落在某条 spec 的射程内。

    判定必须与 :func:`pdx.doc_tables._find_header` **同源**：那个函数用
    ``ln.startswith(spec.header)`` 找候选、再按 ``occurrence`` 取第 N 个。
    所以这里也用**完整表头**逐条 spec 数匹配位置，而不是按「精确表头」数 ——
    两者在**表头互为前缀**时会得出不同的序号。实测踩过：
    ``| 令牌 | 形式 | 实测次数 |`` 是 ``| 令牌 | 形式 | 实测次数 | 说明 |``
    的前缀，文档里两张表，按精确表头数只有 1 个候选（序号 0），
    按 ``startswith`` 数有 2 个（序号 0、1）—— 于是生成器认第 2 张、
    而盘点认第 1 张，同一张表一边说已看守、一边说没看守。

    **早先这里写的是 ``spec_header[:24]``（只看前 24 个字符），这是错的** ——
    截短只会**多**匹配：doc 17 的 ``| 字段 | 官方 `.md` | `.txt` 实测次数 | 说明 |``
    与前面两张 ``… | `.txt` 实测 | 说明（…） |`` 共享前 24 个字符，
    于是 ``hits[0]`` 落到第 483 行的表上，真正被看守的第 1460 行那张被判成「无人看守」
    （``v3 tables`` 明明在管它）。方向上是**少报**（不会漏掉真问题），
    但余额因此对不上，而且「已看守」的定义会随文档里多一张同前缀的表而改变。
    截短能匹配上的表，完整表头未必匹配得上 —— 而 :func:`_find_header` 只认完整表头，
    所以截短匹配到的那些表**生成器根本写不进去**，不该算看守。
    """
    for spec_header, occurrence in generated.get(doc, []):
        hits = [i for i, h in enumerate(headers) if h.startswith(spec_header)]
        if occurrence < len(hits) and hits[occurrence] == index:
            return True
    return False


def _is_guarded(path: Path, header: str) -> bool:
    # 字节列由 test_docs_consistency 逐行核对
    if "字节" in header or "| B |" in header:
        return True
    # doc 16/17 的 §0 总览表由 test_doc_overview 核对
    return bool(
        path.name in {"16-外交军事与地图.md", "17-角色科技与呈现.md"}
        and header.startswith("| # | 目录 |")
    )


#: **刻意不生成**的表：``(文档名, 表头前缀) → 理由``。
#:
#: 这是欠债余额的**终点形态** —— 余额降到只剩这些条目就算做完了，
#: 所以每一条都必须能回答「为什么不能机械生成」。加进来之前先问自己：
#: 是**口径说不清**，还是**数字根本不该由工具拥有**？
#: 「懒得做」不是理由，也不该出现在这里。
NOT_GENERATED: dict[tuple[str, str], str] = {
    (
        "06-本地化与界面资源.md",
        "| 函数 | 次数 | 函数 | 次数 |",
    ): "§1.5.5 数据函数频次：原口径复现不出（四种合理口径都对不上，见 pdx.localization"
    ".data_function_counts 的实测对比），需要先重新定义口径",
    (
        "17-角色科技与呈现.md",
        "| 组 | 键 | 数量 |",
    ): "§8.3 基因分组：`数量` 列是作者分组的结果，`gene_*` 那一行还是近似值 `~95`，"
    "机械生成会把「分成哪几组」这个判断也顶掉",
    (
        "16-外交军事与地图.md",
        "| 前缀 | 出现次数 | 语义（由 mod 用法推断） |",
    ): "§1.1 六种前缀：统计对象是 `workshop\\content\\529340\\**\\*.txt`（**本机订阅的 mod**）——"
    "换台机器、退订一个 mod 数字就变；这不是「数字过期」，而是「这份快照描述的是另一台机器」",
    (
        "16-外交军事与地图.md",
        "| SteamId | mod 名 | 本范围内文件数 |",
    ): "§5 改造面总表：同上，统计的是本机 23 个 mod 的覆盖/新增清单",
    (
        "02-Mod结构与加载.md",
        "| 前缀 | 次数 | 语义（由行为推断） |",
    ): "§5.1 六个数据功能前缀的出现次数：统计对象是本机 23 个 Workshop mod 的 `.txt`"
    "（机器相关，同 doc 16 §1.1）",
    (
        "02-Mod结构与加载.md",
        "| 使用次数 | 目录 |",
    ): "§5.1.1「前缀出现在哪些 `common\\` 子目录」：同上，来自本机 mod",
    (
        "12-真实mod解剖与改造面地图.md",
        "| 前缀 | 次数 |",
    ): "§2 六个前缀的独立复核（1,115 / 737 / …）：同上，来自本机 23 个 mod ——"
    "注意它与 doc 02 那张的数值略差（作者当时用了不同的复核范围），两张都只能算时点快照",
    (
        "14-经济与生产系统.md",
        "| 关键字 | 出现次数 |",
    ): "§1.4「本机 23 个 mod 的实测使用量」：同上，来自本机 workshop 内容",
}


def _is_not_generated(doc: str, header: str) -> bool:
    return any(doc == d and header.startswith(h) for d, h in NOT_GENERATED)


#: **刻意不生成、也不登记断言**的散文数字：``(文档名, 数字) → 理由``。
#:
#: 这是散文那面欠债余额的**终点形态** —— 余额降到只剩这些条目就算做完了。
#: 与 :data:`NOT_GENERATED` 同一套标准：每一条都得能回答「为什么这个数字不该由工具算」，
#: 「懒得做」不是理由。
#:
#: **键是数字本身，不是行号。** 行号会随文档增删漂移，而盘点本身也是按
#: 「同一文档里还有哪些数字没人管」来数数的 —— 同一个数字在一份文档里出现几次
#: 只算一笔账，所以登记一次就够。
#:
#: 三类理由（与模块 docstring 的六类对应，这里只挑真正的**不该算**）：
#:
#: * **另一台机器**：统计对象是本机订阅的 Workshop mod（doc 02 / 06 / 12 / 14 / README），
#:   换台机器、退订一个 mod 就变 —— 与 :data:`NOT_GENERATED` 里那几张表同一个理由；
#: * **原文如此**：引用官方 `.md` 里写的常量或清单（doc 04 的 4 条、doc 07 的 512 / 41 / 20），
#:   是引用而不是测量；要核对只能核官方文件的 sha256（另有测试）；
#: * **算例与勘误**：算术推演的结果、以及「本节曾写错成什么」（doc 04 / 05 / 07 / 17），
#:   它们存在的意义就是记录推导过程与历史错误，**天生没有期望值**。
PROSE_NOT_COMPUTED: dict[tuple[str, int], str] = {
    ("02-Mod结构与加载.md", 42): "§5.1.1「共 42 个 `common\\` 子目录出现该机制」—— 与本篇那张"
    "已列入 NOT_GENERATED 的表**同一份数据**（本机 23 个 Workshop mod 的 `INJECT:` 分布）",
    ("02-Mod结构与加载.md", 23): "§6.1 启动器 `enabledMods` 的项数 —— 这是**本机订阅状态**，"
    "不是仓库事实；换机器就变",
    ("02-Mod结构与加载.md", 1): "§2.2「23 个 mod 里有 1 个连 `game_custom_data` 都没写」—— "
    "本机 mod 侧计数（与上面那两条同一份数据）",
    ("04-脚本系统.md", 15): "§script value 的**算例**：`add=5 → multiply=4 → max=10 → add=5` "
    "推演出 15（不是 25）—— 算的是书写顺序，不是从游戏数据里数出来的量",
    (
        "04-脚本系统.md",
        4,
    ): '§decisions 的**勘误**：官方 `.md` 自称 "3 fundamental things" 却列了 4 条。'
    "该数字数的是**官方文档的条目**（doc 07 那一类：原文如此），且它正是用来指出原文自相矛盾的地方 —— "
    "生成它反而抹掉了这处勘误",
    (
        "05-defines与修饰符.md",
        6125,
    ): "§static_modifiers 的**勘误记录**：「本节先后写过 6125 与 6121，"
    "两个都是错的」—— 这两个数的意义就是记录**曾经错过的值**，天生不可能有期望值"
    "（正确值 6128 已有断言看守）",
    ("05-defines与修饰符.md", 6121): "同上一条，同一次勘误里的第二个错误值",
    (
        "06-本地化与界面资源.md",
        18,
    ): "§A「mod 中与原版同名的文件共 18 个」—— 统计对象是本机 mod 目录",
    ("07-官方文档索引.md", 15): "与 doc 04 的 15 同一个算例（`max=10` 在最后一次 `add` 之前生效）",
    ("07-官方文档索引.md", 20): "§OOB 引用官方 `1836_oob.md` 里的国家清单 —— **原文如此**："
    "该文档是史实编制清单，国家数由 Paradox 写定，不是游戏数据里的量",
    ("07-官方文档索引.md", 41): "同上，官方文档里 `## ` 驻地/舰队标题的个数 —— 引用而非测量",
    ("07-官方文档索引.md", 512): "§4.9.2 引用官方 `audio_settings.md`：`max_audio_channels` "
    "未指定时默认 **512** —— **FMOD 的默认值，原文如此**，不在游戏数据里",
    (
        "12-真实mod解剖与改造面地图.md",
        4,
    ): "§5「本机最小的完整 mod，只有 4 个文件」—— 本机 workshop 内容",
    (
        "14-经济与生产系统.md",
        0,
    ): "§5.5「本机 23 个 mod 中 `common\\production_method_groups\\` 下有 0 个文件」"
    "—— 本机 mod 侧统计（数字碰巧是 0 也一样会变）",
    ("README.md", 4750): "索引页 §3「对 23 个 mod 共 4,750 个相对路径」—— 本机 mod 侧统计",
}


def _unguarded_prose() -> dict[str, set[int]]:
    """``文档名 → 既没有断言看守的散文数字``（含已在 :data:`PROSE_NOT_COMPUTED` 登记理由的）。

    为什么要返回**明细**而不只是个数：余额的终点形态不是「个数为 0」，
    而是「剩下的每一个都答得出为什么」—— 所以既要能数个数，也要能核对
    登记清单有没有指向不存在的数字（登记表烂掉必须报出来，见
    :func:`test_剩下的散文数字都写明了理由`）。
    """
    from pdx import verify

    bold = re.compile(r"\*\*([\d][\d,]*)\*\*")
    cnt = re.compile(r"(共|合计|总计|有)\s*\*{0,2}([\d][\d,]*)\s*个")
    claim_values: dict[str, set[int]] = {}
    for c in verify.CLAIMS:
        if isinstance(c.expected, int):
            claim_values.setdefault(c.doc, set()).add(c.expected)

    out: dict[str, set[int]] = {}
    for md in sorted(config.DOCS.glob("*.md")):
        if md.name in FULLY_GENERATED_DOCS:
            # 整体由 `v3 index` 生成的文档（doc 13）连正文都是产物 ——
            # 它里面的数字与表格那面的处理一致，不计入余额。
            continue
        prose = "\n".join(
            ln
            for ln in md.read_text(encoding="utf-8").splitlines()
            if not ln.lstrip().startswith("|")
        )
        nums = {int(x.replace(",", "")) for x in bold.findall(prose)}
        nums |= {int(x.replace(",", "")) for _k, x in cnt.findall(prose)}
        left = nums - claim_values.get(md.name, set())
        if left:
            out[md.name] = left
    return out


def _count_unguarded_prose() -> int:
    """**还没写明理由**的散文数字个数（在 :data:`PROSE_NOT_COMPUTED` 登记过的不算欠债）。"""
    return sum(
        1
        for doc, nums in _unguarded_prose().items()
        for n in nums
        if (doc, n) not in PROSE_NOT_COMPUTED
    )


def _count_unguarded_tables() -> tuple[int, list[str]]:
    """``(未看守的表数, 前若干条示例)``。

    「刻意不生成」的表（:data:`NOT_GENERATED`）**不算欠债** —— 它们的理由已经写下来了，
    余额的目标就是「只剩这些」。
    """
    generated = _generated_headers()
    unguarded: list[str] = []
    for path in sorted(config.DOCS.glob("*.md")):
        if path.name in FULLY_GENERATED_DOCS:
            continue
        tables = _tables(path)
        headers = [h for _ln, h, _rows in tables]
        for index, (lineno, header, rows) in enumerate(tables):
            if not rows or _is_guarded(path, header):
                continue
            if _is_guarded_by_spec(headers, index, generated, path.name):
                continue
            if _is_not_generated(path.name, header):
                continue
            if _stat_columns(header, rows):
                unguarded.append(f"{path.name}:{lineno} {header[:70]}")
    return len(unguarded), unguarded


def test_未看守的机械表不超过预算() -> None:
    """**欠债余额只许减少。**

    这条不是「有多少表」，而是「还有多少表没人管」。做完一批就把
    :data:`UNGUARDED_TABLE_BUDGET` 往下调；**上调必须说明理由** ——
    否则「又长出一张无人看守的表」永远不会有人发现。
    """
    n, examples = _count_unguarded_tables()
    assert n <= UNGUARDED_TABLE_BUDGET, (
        f"含统计量列、无人看守的表从 {UNGUARDED_TABLE_BUDGET} 涨到了 {n}。\n"
        f"要么接进 `v3 tables`／加看守测试，要么在提交信息里说明为什么允许它涨。\n"
        f"前 10 张：\n  " + "\n  ".join(examples[:10])
    )


def test_未看守的散文数字不超过预算() -> None:
    """散文数字那面的同一个余额：只数**既没断言、也没理由**的那些。"""
    n = _count_unguarded_prose()
    detail = "\n  ".join(
        f"{doc}: {sorted(nums)}"
        for doc, nums in sorted(_unguarded_prose().items())
        if any((doc, x) not in PROSE_NOT_COMPUTED for x in nums)
    )
    assert n <= UNGUARDED_PROSE_BUDGET, (
        f"散文里无人看守的不同数字从 {UNGUARDED_PROSE_BUDGET} 涨到了 {n} —— "
        f"新增数字时请补断言，或在 PROSE_NOT_COMPUTED 里写明为什么它不该由工具算。\n"
        f"明细：\n  {detail}"
    )


def test_剩下的散文数字都写明了理由() -> None:
    """**终点判据**：剩下每个无人看守的散文数字都在登记表里。

    两个方向都在查，但它们**不是同一时刻生效**的：

    * **不能有数字没登记** —— 预算 > 0 时（一轮做到一半）要求「未登记个数
      正好等于 :data:`UNGUARDED_PROSE_BUDGET`」：预算是**承诺**而不是上限，
      写着 34 就该是 34。等它降到 0，这条自动变成「一个都不能少」。
    * **登记表不能指向空处**（任何时刻都查）—— 登记了却已经不在文档里的数字，
      说明表在腐烂（数字改对了、段落删了）。留着它，这份清单就从「理由清单」
      退化成「免责清单」。
    """
    left = _unguarded_prose()
    registered = {(doc, n) for doc, nums in left.items() for n in nums}
    missing = sorted(registered - set(PROSE_NOT_COMPUTED))
    detail = "\n  ".join(f"{d} 的 {n}" for d, n in missing)
    assert len(missing) == UNGUARDED_PROSE_BUDGET, (
        f"未写明理由的散文数字有 {len(missing)} 个，而预算是 {UNGUARDED_PROSE_BUDGET} —— "
        f"做完一批就把它调下来（它同时是进度记录）。\n明细：\n  {detail}"
    )
    if UNGUARDED_PROSE_BUDGET == 0:
        assert not missing, (
            f"还有散文数字既没有断言、也没有理由（预算已降到 0，本该一个不剩）：\n  {detail}"
            "\n要么补断言（能复算就复算），要么在 PROSE_NOT_COMPUTED 里写明理由。"
        )
    stale = sorted(set(PROSE_NOT_COMPUTED) - registered)
    assert not stale, (
        "PROSE_NOT_COMPUTED 里登记了文档中已不存在的数字（多半是数字改对了、段落删了）：\n  "
        + "\n  ".join(f"{d} 的 {n} —— {PROSE_NOT_COMPUTED[(d, n)][:40]}…" for d, n in stale)
        + "\n请删掉这些条目：登记表一旦可以指向空处，它就只是免责声明。"
    )


def _scan_counts() -> tuple[int, int, int]:
    """``(扫到的表总数, 由生成器看守的, 命中的「刻意不生成」条目)``。

    这三个数用来证明**盘点本身在工作** —— 它们与「欠债余额」是两回事：
    余额可以是 0（那是终点），但「扫到了多少张表」永远不该是 0。
    """
    generated = _generated_headers()
    total = guarded = excluded = 0
    for path in sorted(config.DOCS.glob("*.md")):
        if path.name in FULLY_GENERATED_DOCS:
            continue
        tables = _tables(path)
        headers = [h for _ln, h, _rows in tables]
        for index, (_lineno, header, rows) in enumerate(tables):
            if not rows:
                continue
            total += 1
            if _is_guarded_by_spec(headers, index, generated, path.name):
                guarded += 1
            elif _is_not_generated(path.name, header):
                excluded += 1
    return total, guarded, excluded


def test_盘点自身能跑出非零结果() -> None:
    """**元测试**：确保盘点真的在数东西，而不是恒为 0。

    一条「扫全仓、永远返回 0」的检查会让人以为已经清零了 ——
    比没有检查更糟（本仓库在哈希那件事上刚踩过同类的坑）。

    注意这里**不**断言「未看守的表 > 0」：余额的终点就是 0
    （剩下的都在 :data:`NOT_GENERATED` 里、各有理由）。要证明的是
    **扫描本身没退化** —— 所以看的是「扫到多少张表」「其中多少张有人管」。
    """
    total, guarded, excluded = _scan_counts()
    assert total > 100, f"只扫到 {total} 张表 —— 解析多半退化了"
    assert guarded > 0, "没有任何表被生成器看守 —— 规格登记多半断了"
    assert excluded == len(NOT_GENERATED), (
        f"排除清单有 {len(NOT_GENERATED)} 条，但只命中 {excluded} 张表 —— "
        f"表头改过？清单指向了不存在的表？"
    )
    prose_left = sum(len(v) for v in _unguarded_prose().values())
    assert prose_left >= len(PROSE_NOT_COMPUTED), (
        f"扫到的无人看守散文数字只有 {prose_left} 个，却登记了 {len(PROSE_NOT_COMPUTED)} 条理由 —— "
        f"散文解析多半退化了（登记表那面由 test_剩下的散文数字都写明了理由 核对）"
    )
    assert prose_left > 0, "散文数字盘点返回 0 —— 同上"
    assert _stat_columns("| 目录 | 文件数 | 说明 |", [["a", "3", "x"], ["b", "4", "y"]]), (
        "列判定退化了"
    )
    assert not _stat_columns("| # | 项 | 状态 |", [["1", "a", "b"], ["2", "c", "d"]]), (
        "行号/状态列不该被当成统计量"
    )
