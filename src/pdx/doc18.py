"""doc 18（history 初始状态）§3.2 的两个数字：217 个文件、各效果的**出现次数**。

为什么单独一个模块
-----------------
§3.2 那张表只到「子目录 / 文件数」一层，而真正解释「444 个国家文件怎么写」
的是紧随其后的一段散文：

    444 个国家文件里有 **217 个（49%）** 在预置效果之外还逐项写了
    `add_amendment`(26)、`set_institution_investment_level`(60)、
    `set_import_tariff_level`(66)、`set_export_tariff_level`(6)、
    `set_ruling_interest_groups`(2)、`create_diplomatic_pact`(1)。【实测】

这段话里有两种**容易互换**的口径，混起来不会有任何报错：

* **217** 是**文件数**（「有多少个国家文件逐项写了效果」）；
* 括号里的 (26)(60)(66)(6)(2)(1) 是**出现次数**（「这个效果一共被写了多少次」）。
  同一个效果在一个文件里出现两次算两次 —— `create_diplomatic_pact` 只有 1 次
  （`tur - ottoman empire.txt`），所以它的文件数也是 1，两者恰好相同；
  `add_amendment` 26 次的文件数却是另一回事。

两个口径都在这里，就不必靠人记。

口径上还有一处**刻意的不对称**：文件数只用 `add_`/`set_` 前缀，
出现次数还要加上 `create_` —— 否则文档点名要看的 `create_diplomatic_pact`
按前缀根本数不到，会安静地返回 0。理由写在 :data:`_OCCURRENCE_PREFIXES` 旁边。

⚠️ **必须任意深度**。这些效果写在 ``COUNTRIES = { c:TAG ?= { … } }`` **里面**，
而深度 1（`COUNTRIES` 直接子键）拿到的是 `c:ABS` 这类国家标签：
实测「深度 1 有 `add_*`/`set_*` 的文件数」= **0**，而任意深度 = **217**。
0 在文档里不像错、只像「这个目录没写效果」，所以这条口径必须写死在代码里。
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from . import config
from .cache import parse_cached
from .doc_tables import TableSpec
from .model import Block, ParsedFile
from .usage import _walk_all_blocks

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

#: §3.2 的目录（相对 ``game/``）。
_COUNTRIES_DIR = "common/history/countries"

#: **文件数**口径的前缀：`add_` + `set_`（doc 18 §3.2 的 217 个文件用的就是它）。
_FILE_PREFIXES = ("add_", "set_")

#: **出现次数**口径的前缀：在前两个之上再加 `create_`。
#:
#: 两套口径**刻意不同**，理由是一个实测踩到的事实：文档点名要看的
#: `create_diplomatic_pact`（1 次，`tur - ottoman empire.txt`）**不以**
#: `add_`/`set_` 开头 —— 只按文件数那套前缀数，它的次数是 **0**，
#: 而 0 在文档里不像错、只像「游戏里没有这个效果」。
#: 加上 `create_` 后，doc 18 §3.2 那张「可用效果」表的 10 个键**全部**能复算。
_OCCURRENCE_PREFIXES = ("add_", "set_", "create_")


def _country_files() -> list[Path]:
    """``common/history/countries/*.txt``（**不递归**：该目录是平铺的 444 个文件）。

    不递归是有意的：这里数的就是「逐国一个文件」的那 444 个。
    递归会在将来出现子目录时静默把别的文件也算进来。
    """
    base = config.GAME / _COUNTRIES_DIR
    if not base.is_dir():
        return []
    return sorted(p for p in base.glob("*.txt") if p.is_file())


def _effect_keys(pf: ParsedFile, prefixes: tuple[str, ...]) -> Iterator[str]:
    """``COUNTRIES`` 包装块内**任意深度**的、以 ``prefixes`` 之一开头的键。

    「任意深度」用 :func:`pdx.usage._walk_all_blocks` —— 它同时管**匿名块**
    （``{ … }`` 不带键）和普通嵌套块，这两样各写一遍迟早分岔。
    只取 ``COUNTRIES`` 块：实测该目录 444 个文件的顶层块**全部**叫 `COUNTRIES`
    （没有别名包装块），但写死名字才能保证将来多出别的包装块时不会混进来。
    """
    for top in pf.top_assignments:
        if top.is_variable or top.key != "COUNTRIES":
            continue
        value = top.value
        if not isinstance(value, Block):
            continue
        for block in (value, *_walk_all_blocks(value)):
            for a in block.assignments():
                if a.key.startswith(prefixes):
                    yield a.key


def country_effect_occurrences() -> Counter[str]:
    """效果名 → **出现次数**（跨 444 个文件累加，同文件内重复算多次）。

    前缀口径是 ``add_`` / ``set_`` / ``create_``（比文件数口径多一个 `create_`，
    见 :data:`_OCCURRENCE_PREFIXES`）。实测（1.14.3，只列文档点名的那 6 个）：

    * ``set_import_tariff_level`` —— 66
    * ``set_institution_investment_level`` —— 60
    * ``add_amendment`` —— 26
    * ``set_export_tariff_level`` —— 6
    * ``set_ruling_interest_groups`` —— 2
    * ``create_diplomatic_pact`` —— 1

    ⚠️ 这是**出现次数**，不是文件数：文档把那 6 个数写在句子括号里，
    紧挨着一句「有 217 个**文件**」。两种口径在同一句话里，最容易被后来者
    按同一个量去「核对」，然后发现怎么都对不上。
    """
    counter: Counter[str] = Counter()
    for path in _country_files():
        counter.update(_effect_keys(parse_cached(path), _OCCURRENCE_PREFIXES))
    return counter


def country_effect_file_count() -> int:
    """写了至少一个 `add_*` / `set_*` 效果的**文件数**（实测 217 / 444）。

    口径是「文件内任意深度至少有一个这样的键」——**有就记 1，不管几个**。
    与 :func:`country_effect_occurrences` 的合计（出现次数）不同：
    实测 217 个文件里 `add_*` / `set_*` 共出现 755 次、27 种。

    只数深度 1 会得 **0**（见模块 docstring），所以这里刻意用 `any(...)`
    遍历任意深度，而不是 ``top.value.assignments()`` 一层。
    """
    return sum(
        1 for path in _country_files() if any(_effect_keys(parse_cached(path), _FILE_PREFIXES))
    )


def effect_file_counts() -> Counter[str]:
    """效果名 → **出现在几个国家文件里**（同一文件里写两次只算 1）。

    与 :func:`country_effect_occurrences` 是同一批数据的两种口径：
    「有多少个国家文件用了它」与「它一共出现了几次」。
    doc 18 §3.2 原先那张「可用效果」表是**手挑的 10 个**，
    于是漏掉了用得最广的 `add_ruling_interest_group`（151 个文件）——
    改成由本函数生成之后，「漏了谁」这件事在结构上不可能再发生。
    """
    counter: Counter[str] = Counter()
    for path in _country_files():
        counter.update(set(_effect_keys(parse_cached(path), _OCCURRENCE_PREFIXES)))
    return counter


#: §3.2 那张完整效果表的表头（**由 v3 tables 生成**）。
EFFECT_TABLE_HEADER = "| 效果 | 出现的国家文件数 |"


def effect_rows() -> list[str]:
    """§3.2 完整效果表的全部数据行（按文件数降序，同数按名字）。"""
    counts = effect_file_counts()
    return [
        f"| `{name}` | {n} |" for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def doc_table_specs() -> list[TableSpec]:
    """doc 18 的生成表：§3.2 的完整效果清单。"""
    return [TableSpec(name="doc18 效果文件数", header=EFFECT_TABLE_HEADER, rows=effect_rows)]


__all__ = [
    "country_effect_file_count",
    "country_effect_occurrences",
]
