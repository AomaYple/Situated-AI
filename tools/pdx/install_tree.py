"""游戏安装树的目录统计，供 doc 08 的生成表使用。

为什么单独一个模块
------------------
doc 08 是知识库里**数字最密集**的一份（690 行，逐目录的文件数 / 目录数 /
体积 / 扩展名分布），而它此前**完全没有看守**：63 条断言里只有 4 条落在它身上，
且都是 ``common`` 的口径。实测漂了 8 处：

* 两个版本修订哈希停在 1.14.3 之前的旧值。数字漂移扫描看不见哈希 ——
  ``_STANDALONE_NUM_RE`` 要求数字两侧不是字母数字，而哈希是**一整个**
  字母数字串，永远不匹配，于是成了检测盲区；
* ``binaries`` 体积 260.80 → 260.95 MB（1.14.3 更新替换了 ``victoria3.exe``，
  97,128,568 → 97,292,920 字节）；
* ``gfx`` 19,162 → 19,163 文件（更新新增了一个 ``.dds``；
  后来又查清其中还夹着一个 149,078 B 的**崩溃转储** ``fee87a16-….dmp``，
  已删除 —— 现在回到 **19,162**。见 doc 08 §18）；
* ``game`` 全树 17,055.80 → 17,055.90 MB（删掉那个转储后为 **17,055.76**）；
* ``map_data\\heightmap.png`` 52,487,053 → 52,487,093 字节；
* §8 标题写「14 个松散文件」而正文与表格都指向 13 个。

所以这里做两件事：把**能机械算的**表格交给生成器，把算不了的（散文）留给作者。

口径声明（重要，避免读者误判）
----------------------------
**统计的是磁盘上真实存在的文件**，不区分来源。本机游戏树里有 2 个**非 Paradox
文件**（一次崩溃留下的 ``.dmp`` 转储、看图工具 XnView 的 ``.XnViewSort`` 索引），
它们照常计入。理由：整个仓库的「文件数」只该有一个口径（分析产物、快照、
doc 01、doc 08 全部一致）；给它们开例外会让同一棵树有两套数字，
而「哪些算垃圾」本身就是个会吵起来的问题。doc 08 里有一节把这两个文件
逐一点名，读者可以自行扣减。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import config, scan
from .doc_tables import KeyedTableSpec, TableMalformedError, TableSpec

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping
    from pathlib import Path

    from .scan import DirStats

#: 「主要扩展名」列取前几名。doc 08 的表头写的是 Top5，各行的实际条数
#: 受目录里到底有几种后缀限制（``data_binding`` 只有 1 种）。
_TOP_N = 5


def _require(ok: bool, what: str) -> None:
    """前置条件不满足时抛 :class:`TableMalformedError`。

    抛这个而不是裸断言/裸异常：CLI 会把它转成「前置条件缺失 + 退出码 2」的
    干净提示，与「检查未通过（退出码 1）」区分开。没有游戏的机器（CI）上
    ``v3 tables`` 就是走这条路。
    """
    if not ok:
        raise TableMalformedError(f"{what} 不可用 —— 游戏目录不在这台机器上？")


@dataclass(slots=True, frozen=True)
class TreeRow:
    """一个目录的机械统计（doc 08 各表的行）。"""

    name: str
    files: int
    """递归文件数"""
    direct_files: int
    """直接文件数（不含子目录里的）"""
    dirs: int
    size: int
    top_suffixes: tuple[tuple[str, int], ...]
    """按出现次数降序的后缀计数，最多 :data:`_TOP_N` 项，已滤掉无扩展名"""


def _tree_row(stats: DirStats) -> TreeRow:
    """把 :class:`pdx.scan.DirStats` 转成表格行。

    ``by_suffix`` 可能有空键（无扩展名文件，如 ``fonts/SpoqaHanSansNeo/LICENSE``）。
    它在文档里从不出现，截断到 Top5 后也基本挤不进去 —— 但仍然显式滤掉，
    免得某天某目录里多出一堆无扩展名文件时，表格里冒出一行 ``:7``。
    """
    try:
        direct = sum(1 for p in stats.path.iterdir() if p.is_file())
    except OSError:
        direct = 0
    # 两件事的顺序要紧，实测踩过：
    #   1. **先滤掉无扩展名**（``""`` 桶，如 ``fonts/SpoqaHanSansNeo/LICENSE``），
    #      再截断到 Top5。反过来做，无扩展名会白占一个名额 ——
    #      ``game\fonts`` 因此少列了真实的 ``.pdf:1``，而口径说明还写着
    #      「无扩展名的文件不进这一列」。
    #   2. **同计数时按后缀名字典序**排。``most_common`` 的并列顺序取决于
    #      插入顺序，那会随文件系统遍历次序变化 —— 同一棵树能生成两份不同的
    #      Top5，连**截断位置**都跟着变（并列第 5 名选谁全看运气）。
    ranked = sorted(
        ((s, n) for s, n in stats.by_suffix.items() if s),
        key=lambda kv: (-kv[1], kv[0]),
    )
    return TreeRow(
        name=stats.name,
        files=stats.files,
        direct_files=direct,
        dirs=stats.dirs,
        size=stats.size,
        top_suffixes=tuple(ranked[:_TOP_N]),
    )


def rows_of(base: Path) -> list[TreeRow]:
    """``base`` 下**每个一级子目录**的行，按名称排序。"""
    if not base.is_dir():
        return []
    return [_tree_row(s) for s in scan.subdir_stats(base) if s.name]


def tree_row(base: Path) -> TreeRow:
    """``base`` **整棵树**的行（不是它的某个子目录）。"""
    _require(base.is_dir(), str(base))
    return _tree_row(scan.stats_for(base))


def root_loose_files() -> list[tuple[str, str]]:
    """安装根目录下的松散文件，返回 ``[(文件名, 内容), …]``。

    内容取自 :func:`pdx.config.game_version` —— 清单与 doc 01 用的是同一个来源，
    因此三处不可能给出不同的修订号。
    """
    _require(config.ROOT.is_dir(), "游戏安装根目录")
    version = config.game_version()
    out: list[tuple[str, str]] = []
    for path in sorted(p for p in config.ROOT.iterdir() if p.is_file()):
        value = version.get(path.stem, "")
        if value:
            out.append((path.name, value))
    return out


# ── 单元格格式化（照抄文档既有写法，避免无意义地改动全表）──
def fmt_count(n: int) -> str:
    """计数加千位分隔符：``3,101``。"""
    return f"{n:,}"


def fmt_mb(size: int) -> str:
    """体积的文档写法：``5,319.82`` / ``0.01`` / ``0``。

    **不足 0.005 MiB 的写成 ``0``**，而不是 ``0.00``：文档里那几个只有一个
    小文件的目录（``data_binding`` 2,649 B、``notifications`` 1,758 B）都写作
    ``0``，而 ``input_profile``（7,983 B）写作 ``0.01``。这条阈值就是照这个
    既有写法定的 —— 生成器的工作是让数字对，不是顺手改掉排版习惯。
    """
    mb = size / 1024 / 1024
    return "0" if mb < 0.005 else f"{mb:,.2f}"


def fmt_suffixes(pairs: Iterable[tuple[str, int]]) -> str:
    """`` `.dds:1566, .asset:514` `` —— 计数**不加**千位分隔符，整体加反引号。

    两条都是照抄文档既有写法（``.txt:3026``）、不是笔误：计数加逗号会让
    ``.dds:11293`` 变成 ``.dds:11,293``，全表被无意义地改写一遍；
    反引号则让这一列在渲染后是等宽字体。各表这一列的写法已逐张核对过。

    一项都没有时返回 ``—``：文档里空目录的这一列就是破折号，
    返回一对空反引号（`` `` ``）看起来像排版事故。
    """
    if not pairs:
        return "—"
    return "`" + ", ".join(f"{suffix}:{n}" for suffix, n in pairs) + "`"


# ── doc 08 的生成表 ────────────────────────────────────────
def _spec_global() -> TableSpec:
    """§1 全局总数 —— 四列全机械，用整表生成。

    这一张刻意用 :class:`TableSpec` 而不是按行合并：行标签是公式化的
    （``ROOT\\<目录名>``），且首行 ``ROOT\\game 全树`` 要**加粗**强调。
    按行合并的话，生成值要么带着 ``**``（与其余行不自洽）、要么把加粗抹掉；
    整表生成则由这里统一决定强调方式，不会再出现两种写法。
    """

    def rows() -> list[str]:
        tree = tree_row(config.GAME)
        body = [
            (
                f"| `ROOT\\game` 全树 | **{fmt_count(tree.files)}** | "
                f"**{fmt_count(tree.dirs)}** | **{fmt_mb(tree.size)} MB** |"
            )
        ]
        # `game` 已经由上面那行「全树」代表，这里不能再按子目录列一次 ——
        # 否则表里会出现两行 `game`，而且读者分不清哪行是递归口径。
        body.extend(
            f"| `ROOT\\{r.name}` | {fmt_count(r.files)} | "
            f"{fmt_count(r.dirs)} | {fmt_mb(r.size)} MB |"
            for r in rows_of(config.ROOT)
            if r.name != config.GAME.name
        )
        return body

    return TableSpec(
        name="doc08 全局总数",
        header="| 范围 | 文件数 | 目录数 | 体积 |",
        rows=rows,
    )


def _spec_root_dirs() -> KeyedTableSpec:
    """§2.1 ``ROOT`` 一级结构 —— 前四列机械，``用途说明`` 是作者写的。"""
    return KeyedTableSpec(
        name="doc08 ROOT 一级结构",
        header="| 目录 | 文件数 | 目录数 | 体积 | 用途说明 |",
        cells=lambda: [
            (r.name, {1: fmt_count(r.files), 2: fmt_count(r.dirs), 3: f"{fmt_mb(r.size)} MB"})
            for r in rows_of(config.ROOT)
        ],
    )


def _spec_root_loose() -> KeyedTableSpec:
    """§2.2 ``ROOT`` 根下的松散文件 —— 更新「内容」列。

    这一列此前是手抄的修订哈希，**停在 1.14.3 之前的旧值**，而本节还自称
    「判断当前装的是哪个版本的最权威依据」—— 权威依据写错了最要命。
    """
    # 只更新文档里已有的行：根下若多了别的东西，它不属于本节「4 个」的口径，
    # 追加进去会和正文的「4 个」自相矛盾。
    return KeyedTableSpec(
        name="doc08 ROOT 松散文件",
        header="| 文件 | 内容（实测读取） | 用途 |",
        cells=lambda: [(name, {1: f"`{value}`"}) for name, value in root_loose_files()],
        append_new=False,
    )


def _spec_game_dirs() -> KeyedTableSpec:
    """§8 ``game\\`` 一级目录 —— 5 列机械 + 1 列散文。"""
    return KeyedTableSpec(
        name="doc08 game 一级目录",
        header=(
            "| 目录 | 文件数（递归） | 直接文件数 | 子目录数 | 体积 MB | "
            "主要扩展名（Top5） | 用途说明 |"
        ),
        cells=lambda: [
            (
                r.name,
                {
                    1: fmt_count(r.files),
                    2: fmt_count(r.direct_files),
                    3: fmt_count(r.dirs),
                    4: fmt_mb(r.size),
                    5: fmt_suffixes(r.top_suffixes),
                },
            )
            for r in rows_of(config.GAME)
        ],
    )


def _spec_version_fingerprint() -> KeyedTableSpec:
    """§0 环境与版本指纹的四行版本号 —— 全部来自 :func:`config.game_version`。

    这张表是「怎么判断装的是哪一版」的入口，而它的两个修订哈希**曾经是错的**：
    停在 1.14.3 之前的 ``6c9b008f…`` / ``f57eec9a…``，而本体早已是
    ``bf52e8ef…`` / ``1ce8c96b…``。数字漂移扫描对此**完全无感** ——
    哈希是一整个字母数字串，``_STANDALONE_NUM_RE`` 要求数字两侧不是字母数字，
    所以永远匹配不到，于是它成了检测盲区（同一份文档的 §2.2 抄了同样的旧值）。
    交给生成器之后，这条路径上不可能再出现手抄的哈希。

    只更新这四行：其余行（ROOT / GAME / 用户数据 / Workshop 路径）是环境事实，
    换台机器本来就该不同，不属于这个口径。
    """
    version = config.game_version()
    keys = {
        "caligula 分支": "caligula_branch",
        "caligula 修订": "caligula_rev",
        "clausewitz 分支": "clausewitz_branch",
        "clausewitz 修订": "clausewitz_rev",
    }

    def cells() -> list[tuple[str, dict[int, str]]]:
        _require(config.ROOT.is_dir(), "游戏安装根目录")
        return [
            (label, {1: f"`{version[key]}`"}) for label, key in keys.items() if version.get(key)
        ]

    return KeyedTableSpec(
        name="doc08 版本指纹",
        header="| 项 | 值 | 来源 |",
        cells=cells,
        append_new=False,
    )


def _spec_excerpt(
    name: str,
    header: str,
    directory: Path,
    *,
    occurrence: int = 0,
) -> KeyedTableSpec:
    """**节选**表：只更新文档里已列出的那些文件的字节数。

    节选表（「体积最大的 10 个」「关键原生依赖」）不该由生成器决定入选名单 ——
    那是作者的取舍。但**列出来的字节数**必须是对的，否则读者会照着一个错的
    数字判断「改它有没有影响」。所以 ``append_new=False``：只更新，不扩充。
    """
    return KeyedTableSpec(
        name=name,
        header=header,
        cells=lambda: [
            (p.name, {1: f"{p.stat().st_size:,}"})
            for p in sorted(directory.rglob("*"))
            if p.is_file()
        ],
        occurrence=occurrence,
        append_new=False,
    )


def _spec_game_loose() -> KeyedTableSpec:
    """§8 的「``game\\`` 松散文件」表 —— 补上一直空着的字节数。

    这张表此前 13 行的「字节」列**全是 ``—``**，正文还专门声明
    「本轮仅确认存在与名称，**未逐个测量字节数**（属「未确认」项）」——
    而这是台机器上随时能算出来的东西。现在由生成器填上。

    注意键必须是**一行一个文件名**：这张表原先把 ``paths.settings`` /
    ``paths_checksummed.settings`` 合成一行、把 4 个 ``.tga`` 合成一行，
    于是「13 个文件」在表里显示成 9 行，标题还写着「14 个」。
    合并写法本身也没法验证（那一行的字节数该填谁？）。已改为一文件一行 ——
    与 doc 19 的 ``paths.settings`` 表同一个理由。
    """
    return KeyedTableSpec(
        name="doc08 game 松散文件",
        header="| 文件 | 字节 | 用途说明 |",
        cells=lambda: [
            (p.name, {1: f"{p.stat().st_size:,}"})
            for p in sorted(
                (p for p in config.GAME.iterdir() if p.is_file()),
                key=lambda p: p.name,
            )
        ],
        occurrence=3,
    )


def _spec_top_by_size(name: str, directory: Path, *, occurrence: int, top: int = 10) -> TableSpec:
    """「体积最大的 N 个」——**两列一对**的排版（``| 文件 | 字节 | 文件 | 字节 |``）。

    整表生成而不是按行合并：行是按体积降序**配对**出来的，键是复合的
    （一行的左半与右半是两个不相干的文件），任何一个文件进出榜单都会让
    后面所有行的配对整体错位 —— 按行合并只会得到一堆对不上的键。
    这张表也没有散文列，整表重生成不丢任何作者信息。
    """

    def rows() -> list[str]:
        direct = sorted(
            (p for p in directory.iterdir() if p.is_file()),
            key=lambda p: (-p.stat().st_size, p.name),
        )[:top]
        cells = [f"`{p.name}` | {p.stat().st_size:,}" for p in direct]
        # 奇数个时补一个空格子，免得渲染出半行
        if len(cells) % 2:
            cells.append(" ")
        return ["| " + " | ".join(cells[i : i + 2]) + " |" for i in range(0, len(cells), 2)]

    return TableSpec(
        name=name, header="| 文件 | 字节 | 文件 | 字节 |", rows=rows, occurrence=occurrence
    )


def _spec_dir_table(
    name: str,
    header: str,
    base: Path,
    columns: Mapping[int, Callable[[TreeRow], str]],
    *,
    occurrence: int = 0,
    key_column: int = 0,
) -> KeyedTableSpec:
    """「每个子目录一行」的表 —— doc 08 里这一族共 8 张，全部共用这里。

    ``columns`` 描述「第几列填什么」，例如 ``{1: 文件数, 2: 子目录数}``。
    列下标是**生成的**那一列在文档表格里的下标；其余列（含散文）原样保留。
    ``key_column`` 只在 §9.1 那种「第一列是行号 ``#``」的表里才需要挪。
    """
    return KeyedTableSpec(
        name=name,
        header=header,
        cells=lambda: [
            (r.name, {idx: fmt(r) for idx, fmt in columns.items()}) for r in rows_of(base)
        ],
        key_column=key_column,
        occurrence=occurrence,
    )


#: 各表的列填充规则。用模块级常量而不是内联 dict，是为了让「哪些表填哪几列」
#: 一眼可比 —— 同族表的差异只有列数。
_COL_FILES: dict[int, Callable[[TreeRow], str]] = {1: lambda r: fmt_count(r.files)}
_COL_FILES_DIRS: dict[int, Callable[[TreeRow], str]] = {
    1: lambda r: fmt_count(r.files),
    2: lambda r: fmt_count(r.dirs),
}
_COL_FILES_DIRS_SUFFIX: dict[int, Callable[[TreeRow], str]] = {
    1: lambda r: fmt_count(r.files),
    2: lambda r: fmt_count(r.dirs),
    3: lambda r: fmt_suffixes(r.top_suffixes),
}
#: §9.1 的列：``| # | 子目录 | 文件数 | 嵌套子目录 | 扩展名分布 | 用途说明 |``
_COL_COMMON_MAIN: dict[int, Callable[[TreeRow], str]] = {
    2: lambda r: fmt_count(r.files),
    3: lambda r: fmt_count(r.dirs),
    4: lambda r: fmt_suffixes(r.top_suffixes),
}


def doc_table_specs() -> list[TableSpec | KeyedTableSpec]:
    """doc 08 里那些**机械**表格的登记表。

    ⚠️ ``occurrence`` 是**按文档顺序**数的。doc 08 里同表头的表很多：

    * ``| 文件 | 字节 | 用途说明 |`` ×4（§3 两次、§7、§8 松散文件）
    * ``| 子目录 | 文件数 | 用途说明 |`` ×4（§9.2、§10、§11、§12）
    * ``| 子目录 | 文件数 | 子目录数 | 主要扩展名 | 用途说明 |`` ×2（§13、§15）
    * ``| 项 | 字节 | 用途说明 |`` ×2（§6、§14）
    * ``| 文件 | 字节 | 文件 | 字节 |`` ×2（§10、§12 的体积 Top10）

    漏改一个下标就会去改错表 —— 实测踩过：events 的规格指到了 §3 的第一张表，
    于是「生成了 0 行」。**加表时务必先数一遍文档里的出现次序。**

    做哪些、不做哪些（都写明白，免得下一个人以为漏了）：

    * **做**：§1、§2.1、§2.2、§3×2、§6、§7、§8×2、§9.1、§9.2、§10×2、
      §11×2、§12×2、§13、§14、§15 —— 共 21 张（全部落在**游戏安装目录**内）。
    * **不做 §16（用户数据目录）** —— 这是本轮唯一一处「能算但刻意不算」，
      理由值得写下来：那里装的是**运行期状态**而不是游戏内容。
      实测两次相隔不长的扫描：``logs\\`` 文件数都是 72，字节数却从
      8,466,280 涨到 11,713,752；``crashes\\`` 从 48 文件 / 334 MB 变成
      32 文件 / 223 MB（日志轮转与崩溃转储被清理）。把它纳入生成器，
      ``v3 tables`` 会**每次都不一致**，门禁随即失效 —— 一个永远报红的检查
      等于没有检查。要「每次核对用户目录」，那是一件独立的事（它需要的是
      采样策略，不是生成器）。
    * **不做**：§17 关键数字汇总 —— 它是上面这些表的**复述**，单元格里还混着
      「≈16.66 GB」这类换算与括注，逐格生成等于把格式化逻辑再抄一遍，
      信息量却没有增加。
    * **不做**：§4 ``ROOT\\clausewitz`` 的「路径 / 内容要点」表（单元格里是
      「1,110 B，引擎复合设置」这类叙述）、§5 jomini 的子目录表（文件数写的是
      「少量」）、§16.3 ``logs\\`` 的分组表（按用途分组，组内文件名列表是散文）、
      §0 与 §18 的两张说明表。这些表的「数字」要么不是统计量，要么单位与口径
      由作者判断，机械生成只会帮倒忙。
    """
    return [
        _spec_version_fingerprint(),
        _spec_global(),
        _spec_root_dirs(),
        _spec_root_loose(),
        _spec_game_dirs(),
        _spec_game_loose(),
        # `| 文件 | 字节 | 用途说明 |` 的第 0、1 次出现：§3 的两张节选表
        _spec_excerpt(
            "doc08 binaries 主程序", "| 文件 | 字节 | 用途说明 |", config.ROOT / "binaries"
        ),
        _spec_excerpt(
            "doc08 binaries 依赖",
            "| 文件 | 字节 | 用途说明 |",
            config.ROOT / "binaries",
            occurrence=1,
        ),
        # 第 2 次出现：§7 platform_specific_game_data
        _spec_excerpt(
            "doc08 platform_specific_game_data",
            "| 文件 | 字节 | 用途说明 |",
            config.ROOT / "platform_specific_game_data",
            occurrence=2,
        ),
        # `| 项 | 字节 | 用途说明 |` 出现两次：§6 launcher、§14 map_data。
        # §14 建表时把 `state_regions\`（子目录）也列成了一行 —— 那不是文件，
        # 生成器里没有它。默认行为就是**原样保留**未匹配的行，不用额外开关。
        _spec_excerpt("doc08 launcher 表", "| 项 | 字节 | 用途说明 |", config.ROOT / "launcher"),
        _spec_excerpt(
            "doc08 map_data 表",
            "| 项 | 字节 | 用途说明 |",
            config.GAME / "map_data",
            occurrence=1,
        ),
        # 各子目录的统计表
        _spec_dir_table(
            "doc08 common 主表（136 子目录）",
            "| # | 子目录 | 文件数 | 嵌套子目录 | 扩展名分布 | 用途说明 |",
            config.GAME / "common",
            _COL_COMMON_MAIN,
            key_column=1,
        ),
        _spec_dir_table(
            "doc08 history 子目录",
            "| 子目录 | 文件数 | 用途说明 |",
            config.GAME / "common" / "history",
            _COL_FILES,
            occurrence=0,
        ),
        _spec_dir_table(
            "doc08 events 子目录",
            "| 子目录 | 文件数 | 用途说明 |",
            config.GAME / "events",
            _COL_FILES,
            occurrence=1,
        ),
        _spec_dir_table(
            "doc08 localization 语言目录",
            "| 语言目录 | 文件数 | 子目录数 | 说明 |",
            config.GAME / "localization",
            _COL_FILES_DIRS,
        ),
        _spec_dir_table(
            "doc08 english 固定子目录",
            "| 子目录 | 文件数 | 用途说明 |",
            config.GAME / "localization" / "english",
            _COL_FILES,
            occurrence=2,
        ),
        _spec_dir_table(
            "doc08 gui 子目录",
            "| 子目录 | 文件数 | 用途说明 |",
            config.GAME / "gui",
            _COL_FILES,
            occurrence=3,
        ),
        _spec_dir_table(
            "doc08 gfx 子目录",
            "| 子目录 | 文件数 | 子目录数 | 主要扩展名 | 用途说明 |",
            config.GAME / "gfx",
            _COL_FILES_DIRS_SUFFIX,
            occurrence=0,
        ),
        _spec_dir_table(
            "doc08 dlc 子目录",
            "| 子目录 | 文件数 | 子目录数 | 主要扩展名 | 用途说明 |",
            config.GAME / "dlc",
            _COL_FILES_DIRS_SUFFIX,
            occurrence=1,
        ),
        # 体积 Top10（两列一对的排版）
        _spec_top_by_size("doc08 events 体积 Top10", config.GAME / "events", occurrence=0),
        _spec_top_by_size("doc08 gui 体积 Top10", config.GAME / "gui", occurrence=1),
    ]


__all__ = [
    "TreeRow",
    "doc_table_specs",
    "fmt_count",
    "fmt_mb",
    "fmt_suffixes",
    "root_loose_files",
    "rows_of",
    "tree_row",
]
