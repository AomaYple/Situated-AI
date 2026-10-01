"""doc 14（经济与生产）里两条**跨文件/跨目录**的键名口径。

为什么单独一个模块
-----------------
doc 14 已有的机械表（§2~§15 每个目录一张字段次数表）登记在
:mod:`pdx.usage` 的 ``_DOC14_FIELD_TABLES`` 里 —— 那些表的单位是
「**某个目录内**某字段出现了几次」。本模块只放两种**不在字段层**的问法：

* **§4.2「PM 键名允许含连字符」** —— 问的是键名里有没有 ``-``。
  这不是字段统计，而是「用哪种正则提取键名」的判据，所以文档里写作一条
  **提取陷阱**；而且它的适用范围被写错过一次（见下），必须能**全 `common/` 普查**；
* **§7 `buy_packages`** —— 问的是「一个文件里 ``goods`` 块有几个成员」与
  「全目录的 ``goods`` 块用过多少种 `popneed_*` 类别」。前者在**深度 2**
  （``wealth_N = { goods = { … } }``），不是顶层字段，
  :func:`pdx.usage.field_occurrences` 数不到。

文档里被这两条口径改出来的两处
----------------------------
1. §4.2 的括注曾写「其余 13 个目录**无**含连字符的键」—— 那 13 个指的是 §0
   那 14 个目录里除 `production_methods` 之外的部分，**就这 14 个而言是对的**；
   但读起来像「全 `common/` 只有这一处」。实测全 `common/` 有 **4 个目录共 32 个**
   含连字符的顶层键（`character_templates` 27 / `production_methods` 3 /
   `power_bloc_names` 1 / `technology` 1），已把括注改成不歧义的写法。
2. §7 那三处数字（99 个包 / 每个包不必含全部 15 类 / `wealth_1` 只有 4 个）
   **本来就是对的** —— 本模块只是把它们变成可复算的，不改文档。
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from . import config
from .cache import parse_cached
from .model import Block
from .usage import field_occurrences

if TYPE_CHECKING:
    from pathlib import Path

#: 连字符普查的根：``common/`` 下的**全部**子目录（不只 doc 14 的 14 个）。
_COMMON = "common"

#: doc 14 §4.2 的目录。
_PRODUCTION_METHODS = "common/production_methods"

#: doc 14 §7 的文件（整个目录只有这一个文件、99 个包）。
_BUY_PACKAGES = "common/buy_packages"

#: ``wealth_1`` 那一包 —— 文档用它举例「每个包不必包含全部 15 个类别」。
_WEALTH_1 = "wealth_1"


def _top_keys(path: Path, *, hyphen_only: bool = False) -> list[str]:
    """文件里**顶层**赋值的键名（``@变量`` 不计）。

    ``hyphen_only=True`` 只留含 ``-`` 的键 —— 调用方是 :func:`pm_hyphen_key_count`
    与 :func:`hyphen_key_dir_counts`，两处都要「键名里有没有连字符」这一个判据，
    分头写迟早分岔（本仓库最贵的那类 bug）。
    """
    pf = parse_cached(path)
    return [
        a.key for a in pf.top_assignments if not a.is_variable and (not hyphen_only or "-" in a.key)
    ]


def pm_hyphen_key_count() -> int:
    """`common/production_methods` 里**含连字符**的顶层键数（实测 3）。

    三个键：`pm_ammonia-soda_process`（`01_industry.txt`）、
    `pm_coal-fired_plant` / `pm_oil-fired_plant`（`06_urban_center.txt`）。

    ⚠️ 这就是「用 `^[A-Za-z_][A-Za-z0-9_]*\\s*=` 提取会少 3 个」的那 3 个：
    436 个 PM 会被数成 433。口径是**键名含 `-`**，
    不是「值里有 `-`」（值里的连字符到处都是，那是另一个量）。
    """
    base = config.GAME / _PRODUCTION_METHODS
    if not base.is_dir():
        return 0
    return sum(len(_top_keys(path, hyphen_only=True)) for path in sorted(base.rglob("*.txt")))


def hyphen_key_dir_counts() -> Counter[str]:
    """全 ``common/`` 的连字符顶层键普查：``目录名 → 个数``（实测 4 个目录共 32 个）。

    `character_templates` 27 / `production_methods` 3 / `power_bloc_names` 1 /
    `technology` 1（只列出非零项：没有连字符键的目录不会出现在结果里）。

    **存在的理由**：doc 14 §4.2 的括注只扫了本文那 14 个目录就断言
    「无含连字符的键」，而 `character_templates`（27 个）与 `technology`
    根本不在那 14 个里 —— 想要否证那句话，就得有**一个跨目录**的口径。
    doc 17 的「早期缩进法误得 1983、漏 27 个」说的正是这 27 个。
    """
    counter: Counter[str] = Counter()
    root = config.GAME / _COMMON
    if not root.is_dir():
        return counter
    for child in sorted(p for p in root.iterdir() if p.is_dir()):
        for path in sorted(child.rglob("*.txt")):
            if not path.is_file():
                continue
            n = len(_top_keys(path, hyphen_only=True))
            if n:
                counter[child.name] += n
    return counter


def _goods_members(block: Block) -> list[str]:
    """``wealth_N = { goods = { … } }`` 里 ``goods`` 块的成员键（深度 2）。"""
    out: list[str] = []
    for a in block.assignments():
        if a.key != "goods":
            continue
        value = a.value
        if isinstance(value, Block):
            out.extend(x.key for x in value.assignments())
    return out


def _iter_goods_block_members() -> list[tuple[str, list[str]]]:
    """``buy_packages`` 目录下 ``(包名, goods 块成员)``，按文件与文件内顺序。"""
    base = config.GAME / _BUY_PACKAGES
    if not base.is_dir():
        return []
    out: list[tuple[str, list[str]]] = []
    for path in sorted(base.rglob("*.txt")):
        if not path.is_file():
            continue
        pf = parse_cached(path)
        for a in pf.top_assignments:
            if a.is_variable or not isinstance(a.value, Block):
                continue
            out.append((a.key, _goods_members(a.value)))
    return out


def wealth_1_goods_categories() -> int:
    """`wealth_1` 的 ``goods`` 块成员数（实测 4）。

    实测四个：`popneed_simple_clothing` / `popneed_basic_food` /
    `popneed_heating` / `popneed_intoxicants` —— 文档用它举例
    「**每个包不必包含全部 15 个类别**」，所以这个 4 是那句话的证据。

    ⚠️ 成员在**深度 2**（``wealth_1 = { goods = { … } }``）：
    按「顶层条目块的字段」数会得到 0 行/0 个，而 0 在文档里不像错，只像「没写」。
    """
    for name, members in _iter_goods_block_members():
        if name == _WEALTH_1:
            return len(members)
    return 0


def buy_package_goods_categories() -> int:
    """全部 ``goods`` 块里 `popneed_*` 类别的**去重**个数（实测 15）。

    口径是**去重**（跨 99 个包合并），不是「出现次数」：同一个类别会在几十个包
    里重复出现（`popneed_heating` 在 99 个包里都有）。这个 15 与
    `common/pop_needs` 的 15 个定义**同集** —— 两处若不等，说明有包引用了
    不存在的类别（或新类别没被任何包引用），那是真 bug 而不只是数字过期。
    """
    return len({member for _name, members in _iter_goods_block_members() for member in members})


def buy_package_entry_count() -> int:
    """`common/buy_packages` 的顶层**条目数**（实测 99，即 `wealth_1` … `wealth_99`）。

    只有 1 个文件 `00_buy_packages.txt`，**无官方 `.md`**。
    """
    return len(_iter_goods_block_members())


def buy_package_field_names() -> list[str]:
    """`buy_packages` 的**深度 1** 字段名（去重，实测 2：`goods` / `political_strength`）。

    与 :func:`buy_package_entry_count` 的 99 是两个量：99 个包、每个包 2 个字段。
    文档 §7 的表是「字段 | 深度 | 实测次数」三列 —— 深度 1 那两行就是这两个。
    """
    return sorted(field_occurrences(_BUY_PACKAGES))


__all__ = [
    "buy_package_entry_count",
    "buy_package_field_names",
    "buy_package_goods_categories",
    "hyphen_key_dir_counts",
    "pm_hyphen_key_count",
    "wealth_1_goods_categories",
]
