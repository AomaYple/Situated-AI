"""「用了多少次」类统计表 —— 跨多份文档，所以集中在这里。

为什么单独一个模块
------------------
全仓盘点（``tools/tests/test_inventory.py``）数出 **125 张表含真统计量列而无人看守**，
其中一大类是同一个形状：

    | 字段 | 实测次数 | 说明 |      ← 某目录内各字段出现了多少次
    | 键   | 文件数   | 说明 |      ← 某目录内有多少个文件用到某个键

这些表散在 doc 04 / 14 / 15 / 16 / 17 里，而这几份文档**还没有自己的领域模块**
（不像 doc 05 有 ``defines.py``、doc 08 有 ``install_tree.py``）。为一张表各建一个
模块是过度设计，所以把「同一个形状的分析 + 它的表规格」集中在这里；
等某份文档的表多到值得拆分时再拆。

口径（两个都容易被悄悄改掉，所以写死在这里）
------------------------------------------
* **次数** = 该键作为字段**出现**的总次数（跨文件累加，同一个文件里出现两次算两次）；
* **文件数** = 用到该键的**文件个数**（同一个文件里出现两次只算一个）。
  两者不可互换 —— 实测同一张表里两种口径差得很远。

另有一组**文件级**口径（:func:`file_key_name_count` /
:func:`file_key_name_count_by_line` / :func:`file_line_count`）——
doc 03 §4 那一节的四个数字靠它们复算，见 :func:`ai_script_values_key_stats`。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

from . import config
from .cache import parse_cached
from .doc_tables import KeyedTableSpec
from .extract import entry_fields
from .model import Assignment, Block, ParsedFile, Scalar

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterator
    from pathlib import Path


def _iter_keyed_blocks(node: Block | ParsedFile) -> Iterator[tuple[str, Block]]:
    """递归产出 ``(键, 块)``。

    块自己**不带键** —— 键只存在于指向它的赋值上，所以必须从赋值往下走。
    另外 ``ParsedFile`` 与 ``Block`` 的入口不同（前者是 ``top_assignments``
    属性、后者是 ``assignments()`` 方法），实测第一版就在这里写错了。
    """
    items = node.top_assignments if isinstance(node, ParsedFile) else node.assignments()
    for a in items:
        v = a.value
        if isinstance(v, Block):
            yield a.key, v
            yield from _iter_keyed_blocks(v)


def _as_entry_block(a: Assignment) -> Block | None:
    """赋值指向块、且不是 ``@变量`` —— 则它是条目块。

    单独一个函数是为了让 mypy 收窄得动：``a.value`` 是**属性**，
    在推导式的条件里写 ``isinstance(a.value, Block)`` 收窄不了表达式
    （实测报 ``Argument 1 has incompatible type``）。
    """
    if a.is_variable or not isinstance(a.value, Block):
        return None
    return a.value


def _entry_blocks(pf: ParsedFile) -> list[Block]:
    """文件里的**顶层条目块**（``@变量`` 不算）。"""
    return [b for b in map(_as_entry_block, pf.top_assignments) if b is not None]


def _iter_all_blocks(node: Block | ParsedFile) -> Iterator[Block]:
    """**任意深度**的块，**含顶层**，``@变量`` 不算。

    与 :func:`_iter_keyed_blocks` 的区别：那个要配对的键，这个只要块。
    与 :func:`_entry_blocks` 的区别：那个只到顶层。

    ``含顶层`` 这一条是踩出来的：doc 17 的取值分布表要「全部 ``type =`` 赋值」，
    第一版写成 ``_entry_blocks(pf) + list(所有嵌套块)`` —— 顶层块被**数了两遍**，
    于是 `country` 189 变成 378、`character` 105 变成 210，
    而错得这么整齐（全是两倍）在 diff 里反倒像「口径变了」而不是 bug。
    """
    items = node.top_assignments if isinstance(node, ParsedFile) else node.assignments()
    for a in items:
        if a.is_variable:
            continue
        v = a.value
        if isinstance(v, Block):
            yield v
            yield from _iter_all_blocks(v)


def _collect(dir_rel: str, *, within: str | tuple[str, ...] | None, per_file: bool) -> Counter[str]:
    """``dir_rel`` 下要统计的块的字段。

    * ``within=None`` —— 只数**顶层条目块**的字段（如 ``common/buildings/``
      里 115 个建筑各自的字段）。嵌套块不是条目，不参与；
    * ``within="modifier"`` —— 数**任意深度**上名为 ``modifier`` 的块的字段
      （doc 16 的战争目标是 ``war_goal = { modifier = { … } }`` 这种形状）；
    * ``within=("a", "b")`` —— 数这几个块名**合起来**的字段。
    """
    base = config.GAME / dir_rel
    if not base.is_dir():
        return Counter()
    total: Counter[str] = Counter()
    for path in sorted(p for p in base.rglob("*.txt") if p.is_file()):
        pf = parse_cached(path)
        if within is None:
            blocks = _entry_blocks(pf)
        elif isinstance(within, str):
            blocks = [b for key, b in _iter_keyed_blocks(pf) if key == within]
        else:
            wanted = set(within)
            blocks = [b for key, b in _iter_keyed_blocks(pf) if key in wanted]
        seen: set[str] = set()
        for b in blocks:
            for key in entry_fields(b):
                if per_file:
                    seen.add(key)
                else:
                    total[key] += 1
        if per_file:
            total.update(seen)
    return total


def field_occurrences(dir_rel: str, *, within: str | tuple[str, ...] | None = None) -> Counter[str]:
    """字段名 → **出现次数**（跨文件累加）。

    ``within`` 给**块名**（或一组块名）：只数这些块内部的字段，不数别的。
    传一组是后补的：doc 14 的「档位」表数的是
    ``building_modifiers`` + ``state_modifiers`` + ``country_modifiers``
    **三种块合起来**的次数（实测 302 + 149 + 61 = 512，正是文档写的 512）——
    只认一种块名会让那张表少算一半，而**少算的数字照样写进文档**。
    """
    return _collect(dir_rel, within=within, per_file=False)


def field_file_counts(dir_rel: str, *, within: str | tuple[str, ...] | None = None) -> Counter[str]:
    """字段名 → **用到它的文件数**（同文件内重复只算一次）。"""
    return _collect(dir_rel, within=within, per_file=True)


def nested_field_occurrences(dir_rel: str, parent: str) -> Counter[str]:
    """``parent`` 块的**子字段**，键写成 ``parent.子字段``。

    存在的理由：doc 17 的 `modifier_types` 字段表把两种层级写在同一张表里 ——
    ``game_data`` 是顶层字段，而 ``game_data.ai_value`` / ``game_data.tags``
    是它**内部**的子字段。前者用 :func:`field_occurrences` 数得到，
    后者数不到（它们不是条目的字段）。点号键让两者共存于一张表。
    """
    counter: Counter[str] = Counter()
    base = config.GAME / dir_rel
    if not base.is_dir():
        return counter
    for path in sorted(p for p in base.rglob("*.txt") if p.is_file()):
        pf = parse_cached(path)
        for key, block in _iter_keyed_blocks(pf):
            if key != parent:
                continue
            for a in block.assignments():
                counter[f"{parent}.{a.key}"] += 1
    return counter


def file_definition_counts(dir_rel: str, *, blocks_only: bool = False) -> dict[str, int]:
    """文件名 → **顶层定义数**（``@变量`` 不计）。

    口径写死在这里：``@变量`` 是文件级宏、不是定义，算进去会让
    `messages\\00_messages.txt` 一类的数字多出几行。游戏自身的文档
    也把「定义数」与「文件行数」分得很开。

    ``blocks_only=True`` 只数 ``键 = { … }`` 形式的**块**，跳过标量赋值
    （``键 = 5``）。这一条是被 doc 04 逼出来的：`common/script_values/` 里
    块 270 个、赋值 479 个 —— 差的那 209 个是标量，而文档那句「共 264 个顶层键」
    用的是**块**口径。口径不同不是错，不写清楚才是。
    """
    out: dict[str, int] = {}
    base = config.GAME / dir_rel
    if not base.is_dir():
        return out
    for path in sorted(p for p in base.rglob("*.txt") if p.is_file()):
        pf = parse_cached(path)
        out[path.name] = sum(
            1
            for a in pf.top_assignments
            if not a.is_variable and (isinstance(a.value, Block) or not blocks_only)
        )
    return out


def definition_rows(
    dir_rel: str, col: int, *, blocks_only: bool = False
) -> Callable[[], list[tuple[str, dict[int, str]]]]:
    """``文件名 → 顶层定义数`` 的行工厂（文档里那族「逐文件定义数」表共用）。"""

    def rows() -> list[tuple[str, dict[int, str]]]:
        counts = file_definition_counts(dir_rel, blocks_only=blocks_only)
        return [(name, {col: f"{n:,}"}) for name, n in sorted(counts.items())]

    return rows


def field_value_counts(dir_rel: str, field: str, *, deep: bool = False) -> Counter[str]:
    """某字段的**取值分布**（值 → 出现次数）。

    ``deep=False`` 只数**顶层条目块**的字段（消息、警报、特质都是这种形状）；
    ``deep=True`` 数**任意深度**的赋值 —— 自定义 loc 有 8 处 ``type`` 写在嵌套块里，
    只数顶层会得到 376 而不是 384，而文档那张表用的正是 384 那个口径。
    """
    counter: Counter[str] = Counter()
    base = config.GAME / dir_rel
    if not base.is_dir():
        return counter
    for path in sorted(p for p in base.rglob("*.txt") if p.is_file()):
        pf = parse_cached(path)
        # ``deep`` 用**全部块**（已含顶层）；浅口径只数顶层条目块。
        blocks = list(_iter_all_blocks(pf)) if deep else list(_entry_blocks(pf))
        for block in blocks:
            for a in block.assignments():
                if a.key != field:
                    continue
                v = a.value
                if isinstance(v, Block):
                    counter["<块>"] += 1
                elif isinstance(v, Scalar):
                    counter[v.unquoted.strip()] += 1
    return counter


def field_missing(dir_rel: str, field: str) -> int:
    """目录里**没写**某个字段的顶层条目数（doc 05 的「31 个键没写 ``decimals``」）。

    与 :func:`field_value_counts` 是一对：那个数「写了什么值」，这个数「谁没写」。
    不能拿「条目数 − 取值出现次数」相减 —— 后者数的是**出现次数**，
    同一个键里写两次会重复计入（本目录没有这种键，但口径不牢）。
    """
    missing = 0
    base = config.GAME / dir_rel
    if not base.is_dir():
        return 0
    for path in sorted(p for p in base.rglob("*.txt") if p.is_file()):
        pf = parse_cached(path)
        for a in pf.top_assignments:
            if a.is_variable or not isinstance(a.value, Block):
                continue
            if not any(f == field for f in entry_fields(a.value)):
                missing += 1
    return missing


def count_key_assignments(path: Path, key: str) -> int:
    """一个文件里某个键**在任意深度**被赋值的次数。

    用途：doc 06 的「``fonts.font`` 里共 53 个 ``languages`` 块」—— 那些块不是
    顶层键（在 ``fontfiles`` 里面），而缩进在 PDX 里没有语义，所以只能按 AST 递归数。

    ⚠️ 不能改用行正则：``fonts.font`` 第 1 行的注释里就有一个 ``languages``，
    纯文本计数会得到 **54**。
    """
    total = 0
    pf = parse_cached(path)
    total += sum(1 for a in pf.top_assignments if a.key == key)
    for block in _walk_all_blocks(pf):
        total += sum(1 for a in block.assignments() if a.key == key)
    return total


def value_census(dir_rel: str, values: Collection[str]) -> Counter[str]:
    """**键无关**的取值普查：给定取值集合，数它们作为赋值出现了多少次。

    与 :func:`field_value_counts` 的区别是它**不看键名** —— doc 15 的
    「五档态度」就是这种形状：``lawgroup_xxx = approve`` 里的键有 26 种，
    但取值只有 5 种，作者关心的是这 5 种各占多少。

    只数 ``=`` 赋值，不数 ``>=`` / ``<`` 这类比较：``law_stance = { value >= approve }``
    里的 ``approve`` 是**比较对象**，不是一次态度声明。
    """
    wanted = set(values)
    counter: Counter[str] = Counter()
    base = config.GAME / dir_rel
    if not base.is_dir():
        return counter
    for path in sorted(p for p in base.rglob("*.txt") if p.is_file()):
        pf = parse_cached(path)
        for block in _iter_all_blocks(pf):
            for a in block.assignments():
                if a.op != "=":
                    continue
                v = a.value
                if isinstance(v, Scalar):
                    text = v.unquoted.strip()
                    if text in wanted:
                        counter[text] += 1
    return counter


def all_field_occurrences(dir_rel: str) -> Counter[str]:
    """字段名 → 出现次数，**含顶层、任意深度、含匿名块**。

    与 :func:`field_occurrences` 的区别：那个只数**顶层条目块**的字段，
    这个把顶层赋值与 ``{ { … } { … } }`` 这种**匿名块**里的字段一起数。

    存在的理由：doc 16 的 `travel_network\\naval_network.txt` 是程序导出的文件 ——
    结构是 ``nodes = { { province = 1 x = … } … }``，
    ``nodes`` / ``connections`` 在**顶层**，而 ``province`` / ``from`` 在**匿名块**里。
    只数顶层会得到 2 个键，只数「有名字的块」会得到 6 个 —— 都不是那张表。

    ⚠️ 匿名块藏在**别的块里面**（``nodes`` 块里才是那一堆 ``{ … }``），
    所以递归必须在**每一层**都检查 ``items`` 里的裸块 —— 只在文件顶层找一次
    会得到和「只数顶层」一样的结果（实测就是这么错了第一版）。
    """
    counter: Counter[str] = Counter()
    base = config.GAME / dir_rel
    if not base.is_dir():
        return counter
    for path in sorted(p for p in base.rglob("*.txt") if p.is_file()):
        pf = parse_cached(path)
        for a in pf.top_assignments:
            if not a.is_variable:
                counter[a.key] += 1
        for block in _walk_all_blocks(pf):
            for a in block.assignments():
                counter[a.key] += 1
    return counter


def _walk_all_blocks(node: Block | ParsedFile) -> Iterator[Block]:
    """任意深度的所有块：赋值的值 + ``items`` 里裸着的匿名块。"""
    items = node.top_assignments if isinstance(node, ParsedFile) else node.items
    for it in items:
        if isinstance(it, ParsedFile):  # pragma: no cover - 只为类型收窄
            continue
        if isinstance(it, Assignment):
            if it.is_variable or not isinstance(it.value, Block):
                continue
            yield it.value
            yield from _walk_all_blocks(it.value)
        elif isinstance(it, Block):
            yield it
            yield from _walk_all_blocks(it)


# ── 文件级口径（doc 03 §4 的四个数字）────────────────────────
#: 行正则口径：``^`` **必须**锚定行首 —— 不锚定（或写成 ``\s*键\s*=`` 的 search）
#: 会把 ``limit = { has_law_or_variant = … }`` 这类**行中间**的键也算进来。
#: 键名字符类只含字母/数字/下划线：``c:KRA`` / ``scope:target_country`` 这类
#: 带 ``:`` 的键，行正则**永远**匹配不到（AST 能）。
_LINE_KEY_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")


def file_key_name_count(path: Path, *, any_depth: bool) -> int:
    """一个文件里**赋值的去重键名**个数（``@变量`` 不计）。

    ``any_depth=False`` 只数**顶层**赋值（花括号深度 0）；
    ``any_depth=True`` 递归到**每一个块**里（:meth:`pdx.model.Block.assignments`）。

    为什么递归要用 AST 而不是行正则（doc 03 §4 实测 75 vs 64，差的 11 个）：

    * **行中间的键**（6 个）：``limit = { has_law_or_variant = … }`` ——
      键名不在行首，锚定的行正则看不见；
    * **用比较符赋值的键**（4 个）：``gdp < 100000`` / ``liberty_desire > 25`` ——
      行正则只认 ``=``，AST 的 ``Assignment.op`` 是 ``<`` / ``>``；
    * **键名带 ``:`` 的键**（1 个）：``scope:target_country`` —— 行正则字符类不含 ``:``。

    ``@变量`` 与行正则口径保持一致地排除：那个正则的字符类不含 ``@``，
    本来也匹配不到 ``@foo = 5``。两个口径要能对着看，就不能一个含 ``@``、一个不含。

    ⚠️ 别为此新写解析器 —— 走 :func:`pdx.cache.parse_cached`（同一路径只解析一次）。
    """
    pf = parse_cached(path)
    keys = {a.key for a in pf.top_assignments if not a.is_variable}
    if any_depth:
        for block in _walk_all_blocks(pf):
            keys.update(a.key for a in block.assignments() if not a.is_variable)
    return len(keys)


def file_key_name_count_by_line(path: Path) -> int:
    """按**行正则**数一个文件里的去重键名个数（``any_depth=True`` 的对照口径）。

    正则写死为 ``^\\s*[A-Za-z_][A-Za-z0-9_]*\\s*=``：**锚定行首**（见
    :data:`_LINE_KEY_RE`），不做引号/注释处理 —— 这正是它比 AST 少数个键的原因。
    两者一起用才有意义：差得多说明文件里有内联写法或比较符赋值。
    """
    if not path.is_file():
        return 0
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    return len({m.group(1) for line in text.splitlines() if (m := _LINE_KEY_RE.match(line))})


def file_line_count(path: Path) -> int:
    """文件行数（``splitlines`` 口径，与 ``Get-Content | Measure-Object -Line`` 同解）。

    **不**用 ``read_text().count("\\n")``：末尾没有换行的文件会少算一行，
    而「682 行 vs 703 行」这种数字差一行在文档里看不出来。
    """
    if not path.is_file():
        return 0
    return len(path.read_text(encoding="utf-8-sig", errors="replace").splitlines())


#: doc 03 §4 的文件（AI 专用脚本值）。
AI_SCRIPT_VALUES_FILE = "common/script_values/ai_script_values.txt"


def ai_script_values_key_stats() -> dict[str, int]:
    """doc 03 §4 那四个数字**一次算全**（1.14.3 实测 703 / 33 / 75 / 64）。

    * ``lines`` —— 行数（703）；
    * ``top_keys`` —— 顶层去重键名（33，1.14.2 时文档写 18）；
    * ``ast_keys`` —— AST 任意深度去重键名（75）；
    * ``line_regex_keys`` —— 行正则同口径去重键名（64）。

    四个都留着而不是只留一个：文档里那句话同时用到「行数 + 顶层键数」与
    「任意深度键数」，两处口径不同（33 vs 75），只给一个数没法复算另一处。
    游戏目录不在时全 0（与 :func:`pdx.game_root.checksum_targets` 同一个约定）。
    """
    path = config.GAME / AI_SCRIPT_VALUES_FILE
    if not path.is_file():
        return dict.fromkeys(("lines", "top_keys", "ast_keys", "line_regex_keys"), 0)
    return {
        "lines": file_line_count(path),
        "top_keys": file_key_name_count(path, any_depth=False),
        "ast_keys": file_key_name_count(path, any_depth=True),
        "line_regex_keys": file_key_name_count_by_line(path),
    }


def ai_script_values_referenced() -> int:
    """`ai_script_values.txt` 的顶层键里，有多少个被 `00_default_strategy.txt` 引用。

    实测 **19 / 33**（doc 09 §4 那张表最后一行：「33 个脚本值（其中 19 个被
    ``00_default_strategy.txt`` 引用）」）。口径是**文本引用**：
    `ai_strategies\\` 目录里那个默认策略文件出现了这个键名就算 ——
    不要求它出现在某个特定字段下（策略文件里同一批键会被多处引用）。
    """
    keys = {
        a.key
        for a in parse_cached(
            config.GAME / "common/script_values/ai_script_values.txt"
        ).top_assignments
        if not a.is_variable
    }
    strategy = config.GAME / "common/ai_strategies/00_default_strategy.txt"
    if not keys or not strategy.is_file():
        return 0
    text = strategy.read_text(encoding="utf-8-sig", errors="replace")
    return sum(1 for key in keys if key in text)


def word_file_counts(dir_rel: str, words: Collection[str]) -> Counter[str]:
    """给定一批词 → **文本里出现过它的文件数**（不看结构）。

    用途：doc 16 的 `flags` / `settings` / `ai.*` 那几张表统计的是
    「有多少个文件用了这个值」，而不是「它作为某个字段的取值出现了几次」——
    两者在**一个文件里出现两次**时才会分岔（实测 `can_be_renegotiated` 就是：
    出现 27 次、只在 26 个文件里）。
    """
    counter: Counter[str] = Counter()
    texts = _dir_texts(dir_rel)
    for word in words:
        counter[word] = sum(1 for text in texts if word in text)
    return counter


def word_stats(dir_rel: str, word: str) -> tuple[int, int]:
    """``(出现次数, 出现文件数)`` —— 纯文本计数，不看结构。"""
    texts = _dir_texts(dir_rel)
    return sum(text.count(word) for text in texts), sum(1 for text in texts if word in text)


def _dir_texts(dir_rel: str) -> list[str]:
    base = config.GAME / dir_rel
    if not base.is_dir():
        return []
    return [
        p.read_text(encoding="utf-8-sig", errors="replace")
        for p in sorted(base.rglob("*.txt"))
        if p.is_file()
    ]


def _rows(counter: Counter[str], col: int) -> list[tuple[str, dict[int, str]]]:
    """``(键, {列下标: 文本})``。

    ``col`` 是**次数那一列在表里的下标** —— 必须逐表指定，不能假定它在第 1 列：
    doc 04 那张是 ``| 字段 | 官方 md 行 | 原版使用次数 | md 说明 |``，
    次数在第 **2** 列。写成 1 会把次数写进「官方 md 行」列，而
    :func:`pdx.doc_tables._render` 只替换指定列、**原值留在原处** ——
    于是生成出「``| `x` | 18 | 18 |``」这种双重计数，肉眼看还以为是排版问题。

    排序：计数降序、同值按名称升序（确定性）。只在**追加新行**时用到 ——
    已存在的行由 :func:`pdx.doc_tables.merge_rows` 保持文档原序。
    """
    return [
        (key, {col: f"{n:,}"}) for key, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


#: doc 14 的「字段 / 令牌 实测次数」表 —— §2~§15 每个目录各一张。
#:
#: ``(表头, occurrence, 次数列, 目录, 块名)``。occurrence 是**精确表头**在文档里的出现次序，
#: 必须数准：:func:`pdx.doc_tables._find_header` 按次序取表，数错就会把 A 目录的次数
#: 写进 B 目录的表 —— 而那种错**不报错**，只是写错地方。
#: 这 21 条映射逐条核对过：每条算出来的行号都落在该目录自己的章节里（实测 0 处不符）。
#:
#: ``块名`` 那两处是**后补的**（doc 14 的这两张表原先一直在静默过期）：
#: `pop_needs` 的 `goods` / `weight` 在 ``entry = { … }`` 里，
#: `production_methods` 的四个「档位」在 ``building_modifiers`` / ``state_modifiers`` /
#: ``country_modifiers`` 里 —— 都不在顶层条目层，按「条目字段」数会得到 0 行。
#: 那张表照样摆在文档里、数字照样不动，**只有「每一行都有人认领」会发现**。
_DOC14_FIELD_TABLES: tuple[tuple[str, int, int, str, str | tuple[str, ...] | None], ...] = (
    ("| 字段 | 实测次数 | 说明 |", 0, 1, "buildings", None),
    ("| 字段 | 实测次数 | 说明 |", 1, 1, "production_methods", None),
    ("| 字段 | 实测次数 | 说明 |", 2, 1, "goods", None),
    ("| 字段 | 实测次数 | 说明 |", 3, 1, "company_types", None),
    ("| 字段 | 实测次数 | 说明 |", 4, 1, "pop_needs", "entry"),
    ("| 字段 | 实测次数 | 说明 |", 5, 1, "decrees", None),
    ("| 字段 | 实测次数 | 说明 |", 6, 1, "harvest_condition_types", None),
    ("| 字段 | 实测次数 | 首现位置 | 语义（据用法推断） |", 0, 1, "buildings", None),
    ("| 字段 | 实测次数 | 首现位置 | 语义（据用法推断） |", 1, 1, "building_groups", None),
    ("| 字段 | 实测次数 | 首现位置 | 语义 |", 0, 1, "production_methods", None),
    ("| 字段 | 实测次数 | 首现位置 | 语义 |", 1, 1, "company_types", None),
    ("| 字段 | 实测次数 | 含义（逐字来自文件头注释） |", 0, 1, "building_groups", None),
    ("| 字段 | 实测次数 | `.md` | 说明 |", 0, 1, "production_method_groups", None),
    ("| 字段 | 实测次数 | `prestige_goods.md` | 说明 |", 0, 1, "prestige_goods", None),
    ("| 字段 | 实测次数 | 来源 | 说明 |", 0, 1, "pop_needs", None),
    ("| 字段 | `.md` | 实测次数 | 说明 |", 0, 2, "company_charter_types", None),
    ("| 字段 | 深度 | 实测次数 | 说明 |", 0, 2, "buy_packages", None),
    ("| 字段 | 深度 | 实测次数 | 说明 |", 1, 2, "dynamic_company_names", None),
    # travel_network（§15）的两张「令牌 | 形式 | 实测次数」表在 `doc_table_specs()` 里
    # 单独登记（口径是「任意深度 + 匿名块」，不是「条目字段」）。
    (
        "| 档位 | 实测次数 | 缩放基准 |",
        0,
        1,
        "production_methods",
        ("building_modifiers", "state_modifiers", "country_modifiers"),
    ),
)


def _field_rows_factory(
    dir_rel: str,
    col: int,
    within: str | tuple[str, ...] | None = None,
) -> Callable[[], list[tuple[str, dict[int, str]]]]:
    """把「哪个目录、哪个块、第几列」烘进一个无参函数。

    不用 ``lambda dd=d, cc=col: …`` 那种默认参数式捕获 —— 实测 mypy 推不出
    它的类型（``Cannot infer type of lambda``）。:mod:`pdx.game_root` 里的
    ``_path_rows`` 早就因为同一个原因改成了闭包工厂，这里是同一个坑。
    """

    def rows() -> list[tuple[str, dict[int, str]]]:
        return _rows(field_occurrences(dir_rel, within=within), col)

    return rows


def _doc14_specs() -> list[KeyedTableSpec]:
    """doc 14 各目录的字段表 —— 同一形状，逐表指定目录与列号。"""
    out: list[KeyedTableSpec] = []
    for n, (header, occ, col, d, within) in enumerate(_DOC14_FIELD_TABLES, start=1):
        out.append(
            KeyedTableSpec(
                # 名字必须**唯一**：`patch_doc` 的返回值以表名为键，重名会互相覆盖 ——
                # 那样「19 张表都跑了吗」就看不出来了。实测撞过两次：
                # 先是 production_methods 有三张表，再是「（目录, occurrence, 列号）」
                # 相同而**表头不同**的两张（`首现位置|语义` 与 `档位|缩放基准`）。
                # 所以直接用序号编名字。
                name=f"doc14 表{n} {d}",
                header=header,
                cells=_field_rows_factory(f"common/{d}", col, within),
                occurrence=occ,
                # 节选表：只列官方 `.md` 声明过的字段
                append_new=False,
            )
        )
    return out


#: doc 16 那族「键 → 计数」表 —— 每个 `common\` 目录一张。
#:
#: ``(表头, occurrence, 目录, 块名, 口径)``。三个值得写下来的发现：
#:
#: * **口径不是统一的**：285/329/351 三张确实是「有多少个文件用到它」，
#:   其余二十张的数值**只可能是出现次数** —— 例如 `ship_groups` 整个目录
#:   只有 2 个文件，而表里写着 4。实测拿两种口径各比一遍文档，
#:   出现次数那一栏逐行相符、文件数那一栏几乎全错。
#: * 那些表的**列名原本是错的**（写着「文件数/使用文件数」），已改为「出现次数」。
#:   列名一改，`_find_header` 的候选集就变了，所以 occurrence 是改完之后重解的。
#: * `occurrence` 用**模拟 `_find_header`** 反解出来的：先枚举 ``startswith`` 的候选，
#:   再取序号，最后断言它落在目标行 —— 不靠人眼数（数错会把 A 目录的次数写进 B 目录）。
_DOC16_KEY_TABLES: tuple[tuple[str, int, str, str, str], ...] = (
    ("| 键 | 文件数 | 类型 | 说明 / 与官方文档的关系 |", 0, "diplomatic_actions", "", "files"),
    ("| 键 | 文件数 | 官方文档 | 说明 |", 0, "diplomatic_actions", "ai", "files"),
    ("| 键 | 文件数 | 文档 | 说明 |", 0, "diplomatic_actions", "pact", "files"),
    ("| 键 | 出现次数 | 实测取值 |", 0, "proposal_types", "", "occur"),
    ("| 键 | 出现次数 | 文档 | 说明 |", 0, "acceptance_statuses", "", "occur"),
    ("| 键 | 出现次数 | 类型 | 说明 |", 0, "war_goal_types", "", "occur"),
    ("| 键 | 出现次数 | 类型 | 说明 |", 1, "combat_unit_types", "", "occur"),
    ("| 键 | 出现次数 | 说明 |", 0, "combat_unit_groups", "", "occur"),
    ("| 键 | 出现次数 | 说明 |", 1, "combat_unit_experience_levels", "", "occur"),
    ("| 键 | 出现次数 | 文档 | 说明 |", 1, "ship_types", "", "occur"),
    ("| 键 | 出现次数 | 文档 |", 2, "ship_groups", "", "occur"),
    ("| 键 | 出现次数 | 文档 |", 3, "ship_modification_slots", "", "occur"),
    ("| 键 | 出现次数 | 文档 |", 4, "ship_veterancy_levels", "", "occur"),
    ("| 键 | 出现次数 | 类型 | 子键（实测） |", 0, "commander_ranks", "", "occur"),
    ("| 键 | 出现次数 | 文档 | 说明 |", 2, "mobilization_options", "", "occur"),
    ("| 键 | 出现次数 | 文档 | 说明 |", 3, "battle_conditions", "", "occur"),
    ("| 键 | 出现次数 | 文档 | 类型 | 说明 |", 0, "naval_battle_conditions", "", "occur"),
    ("| 键 | 出现次数 | 文档 | 说明 |", 4, "naval_mission_types", "", "occur"),
    ("| 键 | 出现次数 | 文档 | 说明 |", 5, "strategic_regions", "", "occur"),
    ("| 键 | 出现次数 | 类型 | 说明 |", 2, "state_traits", "", "occur"),
    ("| 键 | 出现次数 | 在顶部模板里 | 说明 |", 0, "terrain", "", "occur"),
    ("| 键 | 出现次数 | 说明 |", 2, "terrain_manipulators", "", "occur"),
    ("| 键 | 出现次数 | 文档 | 说明 |", 6, "geographic_regions", "", "occur"),
)


def _key_rows_factory(
    dir_rel: str, block_name: str, caliber: str
) -> Callable[[], list[tuple[str, dict[int, str]]]]:
    """把「哪个目录、哪个块、哪种口径」烘进一个无参函数。"""

    def rows() -> list[tuple[str, dict[int, str]]]:
        counter = (
            field_file_counts(dir_rel, within=block_name or None)
            if caliber == "files"
            else field_occurrences(dir_rel, within=block_name or None)
        )
        return _rows(counter, 1)

    return rows


def _doc16_specs() -> list[KeyedTableSpec]:
    """doc 16 各目录的「键 → 计数」表。"""
    out: list[KeyedTableSpec] = []
    for n, (header, occ, d, b, caliber) in enumerate(_DOC16_KEY_TABLES, start=1):
        out.append(
            KeyedTableSpec(
                name=f"doc16 表{n} {d}",
                header=header,
                cells=_key_rows_factory(f"common/{d}", b, caliber),
                occurrence=occ,
                # 节选表：只列文档里出现过的键
                append_new=False,
            )
        )
    return out


def travel_network_token_rows() -> list[tuple[str, dict[int, str]]]:
    """doc 14 §15.3：`naval_network.txt` 的**令牌**计数（``province=x93C3BC`` 形式）。

    这一张与 doc 16 §4.6 那张是同一个文件的两种问法：doc 16 问「有哪些键」
    （8 个，含顶层的 `nodes`/`connections`），doc 14 问的是 `nodes`/`connections`
    两个块**内部**的令牌（`province`/`x`/`y`/`type` 与 `from`/`to`）。

    口径：`all_field_occurrences`（任意深度 + 匿名块），
    再按文档的行顺序取出这四个令牌 —— `x` / `y` 那一行在文档里是**合并行**、
    值写作「—」（作者没数），这里照 6,641 填上（两个数字实测相等）。
    """
    counter = all_field_occurrences("common/travel_network")
    return [
        ("`province`", {2: f"{counter['province']:,}"}),
        ("`x` / `y`", {2: f"{counter['x']:,}"}),
        ("`type`", {2: f"{counter['type']:,}"}),
    ]


def travel_network_connection_rows() -> list[tuple[str, dict[int, str]]]:
    """doc 14 §15.3 的 `connections` 块令牌表（`from` / `to`）。"""
    counter = all_field_occurrences("common/travel_network")
    return [("`from`", {2: f"{counter['from']:,}"}), ("`to`", {2: f"{counter['to']:,}"})]


def doc_table_specs() -> list[KeyedTableSpec]:
    """这一族表的登记表。

    每张都注明**数据目录**、**口径**（次数 / 文件数）与**次数所在列** ——
    文档里那几列常常紧挨着出现、只差一个字，指错列不会报错、只会写错地方。
    """
    return [
        # doc 14 §15.3 `travel_network\naval_network.txt` 的两张令牌表。
        # 它们的口径是「任意深度 + 匿名块」（`nodes = { { province = … } }`），
        # 不是 `field_occurrences` 那种「顶层条目块的字段」—— 见
        # `all_field_occurrences` 的说明。表头是**前缀关系**：
        # `| 令牌 | 形式 | 实测次数 |` 同时匹配 4 列那张，所以那张用 occurrence=0、
        # 这张 3 列的用 occurrence=1（`_find_header` 按 `startswith` 数候选）。
        KeyedTableSpec(
            name="doc14 travel_network 节点令牌",
            header="| 令牌 | 形式 | 实测次数 | 说明 |",
            cells=travel_network_token_rows,
            key_column=0,
            occurrence=0,
            append_new=False,
        ),
        KeyedTableSpec(
            name="doc14 travel_network 连接令牌",
            header="| 令牌 | 形式 | 实测次数 |",
            cells=travel_network_connection_rows,
            key_column=0,
            occurrence=1,
            append_new=False,
        ),
        # doc 04 §journal_entries：172 个 JE 文件里各字段出现了多少次。
        # 表是 | 字段 | 官方 md 行 | 原版使用次数 | md 说明 | → 次数在**第 2 列**。
        KeyedTableSpec(
            name="doc04 journal_entries 字段使用次数",
            header="| 字段 | 官方 md 行 | 原版使用次数 | md 说明（逐字引用/摘要） |",
            cells=lambda: _rows(field_occurrences("common/journal_entries"), 2),
            # 节选表：只列 `journal_entries.md` **声明过**的字段。
            # 生成器给的是该目录下**全部**字段 —— 不关掉就会追加一堆
            # 官方文档没提过的行，而它们的说明列只能填「待补」。
            append_new=False,
        ),
        # doc 16 §4 · `state_traits`：州特性里的 `modifier` 块用到的 32 种修正。
        # **不是** `war_goal_types` —— 那里根本没有 `modifier` 块，写错会生成 0 行
        # （`test_生成结果非空` 当场失败，实测抓过两次）。
        KeyedTableSpec(
            name="doc16 state_traits modifier 修正次数",
            header="| 修正 | 次数 | 作用方向 |",
            cells=lambda: _rows(field_occurrences("common/state_traits", within="modifier"), 1),
            append_new=False,
        ),
        # doc 14 的整族（§2~§15）：见下面的 _doc14_specs()
        *_doc14_specs(),
        # doc 16 的整族：见下面的 _doc16_specs()
        *_doc16_specs(),
    ]


__all__ = [
    "AI_SCRIPT_VALUES_FILE",
    "ai_script_values_key_stats",
    "all_field_occurrences",
    "definition_rows",
    "doc_table_specs",
    "field_file_counts",
    "field_occurrences",
    "field_value_counts",
    "file_definition_counts",
    "file_key_name_count",
    "file_key_name_count_by_line",
    "file_line_count",
    "nested_field_occurrences",
    "value_census",
    "word_file_counts",
    "word_stats",
]
