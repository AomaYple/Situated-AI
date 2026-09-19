"""本地化（``.yml``）提取。

为什么单独一个模块
------------------
本地化**不是** PDX 花括号语法，而是行式的::

    l_english:
     KEY:0 "Value"
     ANOTHER_KEY:1 "Value with $PLACEHOLDER$"

实测把 ``localization/languages.yml`` 交给 :mod:`pdx.parser` 会得到
**0 个顶层键、0 个错误** —— 也就是静默地什么都没解析出来，还不报错。
这正是覆盖面审计里最隐蔽的一个窟窿：``.yml`` 一直挂在
``config.SCRIPTABLE_SUFFIXES`` 里，但 ``localization/`` 不在
``SCRIPTABLE_DIRS`` 中，所以那 2,176 个文件从来没有被真正读过内容，
只被数了个数。

**也不是 YAML**，所以不能用 PyYAML 之类的成熟解析器（实测过）::

    >>> yaml.safe_load('l_english:\\n COLON:0 ":"\\n')
    yaml.scanner.ScannerError: while scanning a simple key
      could not find expected ':'

YAML 要求映射写成 ``键: 值``（冒号后必须有空格），而这里大量存在
``COLON:0 ":"`` 这种**冒号紧跟版本号**的写法 —— 对 YAML 来说那是一整个
标量，不是键值对。Paradox 的 ``.yml`` 是自家格式，只能自己按行读。

这里的口径
----------
* **语言**由文件里的 ``l_xx:`` 行决定，不由目录名 —— ``localization/modifiers/``
  这种目录名并不是语言码
* **键**是 ``KEY:`` 前面的部分；``:`` 后面紧跟的**版本号**（``:0`` / ``:1``）
  是给译者看的新旧标记，不属于键名
* 一行里第一个 ``:`` 之前是键，之后到引号之间是版本号，引号内是值
* 空行与 ``#`` 开头的行跳过

输出规模
--------
实测全库 **2,176 个文件 / 11 种语言 / 146,226 个去重键 / 1,171,938 次出现**。
键名本身是 mod 作者最需要的信息之一（"这个键存不存在"、"汉化要覆盖哪些键"），
因此**完整记录**，但放进独立产物文件，避免把主产物 JSON 撑大。
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import config
from .doc_tables import KeyedTableSpec
from .parser import TOLERATED_ERRORS
from .scan import walk_files

if TYPE_CHECKING:
    from pathlib import Path

#: 语言声明行：``l_english:``（行尾可带空白）
_LANG_RE = re.compile(r"^\s*(l_[A-Za-z0-9_]+)\s*:\s*$")

#: 条目行：``KEY:版本 "值"``。
#: 键名允许字母数字下划线点号（``SOME.KEY`` 确实存在），
#: 版本号可缺省，值可以没有引号（实测存在）。
_ENTRY_RE = re.compile(r"^\s*([^\s:#][^:]*?)\s*:\s*(\d+)?\s*(.*)$")


#: 这些"键"是文件头的语言声明而不是数据条目
def _is_lang_line(key: str) -> bool:
    return key.startswith("l_")


#: 本地化文件的扩展名
SUFFIXES = (".yml", ".yaml")


@dataclass(slots=True)
class LocEntry:
    """一个去重后的本地化键。"""

    key: str
    #: 出现的语言（排序）
    langs: tuple[str, ...]
    #: 出现的文件数
    files: int


@dataclass(slots=True)
class LocalizationReport:
    """本地化全量提取结果。"""

    #: 语言 -> 统计
    by_lang: dict[str, dict[str, int]] = field(default_factory=dict)
    #: 去重键 -> 记录
    entries: dict[str, LocEntry] = field(default_factory=dict)
    #: 分类目录（localization 下的一级子目录）-> 键数
    by_category: Counter = field(default_factory=Counter)
    files: int = 0
    total_size: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def unique_keys(self) -> int:
        return len(self.entries)

    @property
    def total_occurrences(self) -> int:
        return sum(v["键出现次数"] for v in self.by_lang.values())

    def summary(self) -> dict[str, object]:
        return {
            "文件": self.files,
            "语言数": len(self.by_lang),
            "去重键": self.unique_keys,
            "键出现次数": self.total_occurrences,
            "分类目录数": len(self.by_category),
            "体积MB": round(self.total_size / 1048576, 2),
            "解析错误": len(self.errors),
        }

    def to_dict(self) -> dict[str, object]:
        """完整产物。**含全部 14 万个键名**，因此单独落一个文件。

        格式取舍：``键`` 只给**排序后的字符串列表**，不给每个键都挂一份
        "出现在哪些语言" —— 后者会让产物从约 5 MB 涨到 41 MB（实测），
        而绝大多数查询要的是「这个键存不存在」。
        真正需要语言维度的只是**没有被全部语言覆盖**的那一小撮，
        单独放在 ``仅部分语言有的键`` 里。
        """
        total_langs = len(self.by_lang)
        partial = {
            e.key: list(e.langs)
            for e in sorted(self.entries.values(), key=lambda e: e.key)
            if len(e.langs) < total_langs
        }
        return {
            "概览": self.summary(),
            "各语言": dict(sorted(self.by_lang.items())),
            "分类目录": dict(self.by_category.most_common()),
            "键": sorted(self.entries),
            "仅部分语言有的键": partial,
            "解析错误": [{"文件": p, "消息": m} for p, m in self.errors],
        }


def parse_loc_text(text: str) -> tuple[str, list[str]]:
    """解析一份本地化文本，返回 ``(语言, 键列表)``。

    语言取**最后一个** ``l_xx:`` 声明 —— 一个文件里理论上可以有多段，
    实测都只有一段，取最后与旧实现口径一致。
    """
    lang = "?"
    keys: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _LANG_RE.match(line)
        if m:
            lang = m.group(1)
            continue
        if _is_lang_line(stripped):
            # ``l_english:1 "English"`` 这种带值的语言行，不算数据条目
            continue
        m = _ENTRY_RE.match(line)
        if m:
            key = m.group(1).strip()
            if key:
                keys.append(key)
    return lang, keys


def extract_localization(root: Path | None = None) -> LocalizationReport:
    """提取一个内容根下 ``localization/`` 的全部键名。

    ``root`` 默认为 ``config.GAME``；传 ``config.JOMINI`` 可提取 Jomini 层。
    mod 目录同样适用 —— 结构一致。

    目录结构
    --------
    实测是 ``localization/<语言>/<分类>_l_<语言>.yml``（例如
    ``localization/english/buildings_l_english.yml``）—— **语言在目录上、
    分类在文件名上**，与直觉相反。因此分类取文件名词干并去掉
    ``_l_<语言>`` 后缀，而不是取目录名。
    """
    root = root or config.GAME
    loc = root / "localization"
    report = LocalizationReport()
    if not loc.is_dir():
        return report

    lang_files: Counter = Counter()
    lang_keys: Counter = Counter()
    lang_seen: dict[str, set[str]] = defaultdict(set)
    per_file: Counter = Counter()
    langs_of: dict[str, set[str]] = defaultdict(set)
    category_keys: Counter = Counter()

    for f in sorted(walk_files(loc), key=lambda e: str(e.path)):
        if f.suffix not in SUFFIXES:
            continue
        try:
            text = f.path.read_text(encoding="utf-8-sig", errors="replace")
        except TOLERATED_ERRORS as exc:
            report.errors.append((str(f.path), f"{type(exc).__name__}: {exc}"))
            continue

        lang, keys = parse_loc_text(text)
        category = _category_of(f.path.stem)

        report.files += 1
        report.total_size += f.size
        lang_files[lang] += 1
        lang_keys[lang] += len(keys)
        for k in keys:
            lang_seen[lang].add(k)
            per_file[k] += 1
            langs_of[k].add(lang)
            category_keys[category] += 1

    report.by_lang = {
        lang: {
            "文件": lang_files[lang],
            "键出现次数": lang_keys[lang],
            "去重键": len(lang_seen[lang]),
        }
        for lang in lang_files
    }

    report.entries = {
        k: LocEntry(key=k, langs=tuple(sorted(langs_of[k])), files=per_file[k]) for k in per_file
    }
    report.by_category = category_keys
    return report


def _category_of(stem: str) -> str:
    """从文件名得到分类名：``buildings_l_english`` -> ``buildings``。

    去掉结尾的 ``_l_<语言>``。没有该后缀时原样返回 —— 少数文件确实不带
    （例如 ``localization/languages.yml``）。
    """
    m = re.search(r"_l_[A-Za-z0-9_]+$", stem)
    return stem[: m.start()] if m else stem


# ──────────────────────────────────────────────────────────────
# doc 06 的两张机械表（本地化侧）
# ──────────────────────────────────────────────────────────────


def language_header_counts(root: Path | None = None) -> Counter[str]:
    """``localization/`` 全树 ``.yml`` 的**首行语言声明** → 文件数。

    口径是**首行**而不是「文件里出现过哪些 ``l_xx:``」：一个文件理论上可以有
    多段语言声明（实测都只有一段），按后者数会重复计入。实测 1,877 个文件
    各归入 11 种语言之一，合计正好等于文件总数 —— 这条恒等式由
    ``tools/tests/test_doc06.py`` 看守。
    """
    base = (root or config.GAME) / "localization"
    counter: Counter[str] = Counter()
    if not base.is_dir():
        return counter
    for path in sorted(base.rglob("*.yml")):
        try:
            first = path.read_text(encoding="utf-8-sig", errors="replace").split("\n", 1)[0]
        except OSError:  # pragma: no cover - 权限/占用等极端情况
            continue
        counter[first.strip()] += 1
    return counter


#: ``[...]`` 绑定（数据函数链）—— 供将来若要重新定义「函数频次」口径时使用。
#: **本模块当前不用它生成表格**：doc 06 §1.5.5 那张表的口径复现不出来，
#: 见 :data:`NOT_GENERATED` 的理由。
_BRACKET_RE = re.compile(r"\[([^\[\]]*)\]")

#: 引号串（``'concept_x'`` / ``"gfx/..."``）—— 先剥掉，否则里面的词会被当成函数名。
_QUOTED_RE = re.compile(r"'[^']*'|\"[^\"]*\"")

#: 链上的一个标识符：后面跟 ``(`` / ``.`` / ``|``，或位于这一段末尾。
_CHAIN_TOKEN_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?=[\(\.\|]|$)")

#: 全大写 = 作用域常量（``SCOPE`` / ``ROOT`` / ``COUNTRY`` …），不是函数。
_SCOPE_CONST_RE = re.compile(r"^[A-Z][A-Z_0-9]*$")


def data_function_counts(root: Path | None = None) -> Counter[str]:
    """``[...]`` 里出现的数据函数 / 作用域链接 → 次数（英文库全量）。

    **这张表刻意不进生成器**（见 :data:`NOT_GENERATED`）：文档现值采集于 1.14.2，
    而四种合理口径 —— 段内任意标识符、仅链首、`grep -c` 式行计数、
    括号调用 —— 没有一种能复现它（``GetName`` 实测 17,888 / 14,106 / 9，
    文档写 8,491；``Self`` 在前三种口径下分别是 0 / 769 / 9，文档写 1,082）。
    口径说不清的表不该假装能重算，故保留为**人工维护**并在此留下可复算的实现，
    供下一个人重新定义口径时直接用。
    """
    base = (root or config.GAME) / "localization" / "english"
    counter: Counter[str] = Counter()
    if not base.is_dir():
        return counter
    for path in sorted(base.rglob("*.yml")):
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        for raw in _BRACKET_RE.findall(text):
            span = _QUOTED_RE.sub(" ", raw)
            for m in _CHAIN_TOKEN_RE.finditer(span):
                token = m.group(1)
                if len(token) < 2 or _SCOPE_CONST_RE.match(token):
                    continue
                counter[token] += 1
    return counter


#: 本篇**刻意不生成**的表 —— 每条都要写明理由（`tools/tests/test_inventory.py`
#: 的欠债余额最终只应该剩下这一类）。
NOT_GENERATED: dict[str, str] = {
    "| 函数 | 次数 | 函数 | 次数 |": (
        "§1.5.5 数据函数频次：原口径不可复现（四种合理口径都对不上，见 "
        "`data_function_counts` 的说明），需要先重新定义口径才能生成"
    ),
}


def doc_table_specs() -> list[KeyedTableSpec]:
    """doc 06 本地化侧的生成表（登记进 :func:`pdx.docgen.targets`）。"""
    return [
        KeyedTableSpec(
            name="doc06 语言首行头文件数",
            header="| 首行头（=语言代码） | 文件数 | 中文名 | 备注 |",
            cells=lambda: [
                (header, {1: f"{n:,}"}) for header, n in sorted(language_header_counts().items())
            ],
            append_new=False,
        ),
    ]
