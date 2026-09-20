"""文档里「还剩多少真问题」的**单一数字**与清单。

为什么还要一个工具
------------------
``v3 unverified`` 数的是带 ``【未确认】`` 标记的行 —— 那是**承诺**（凡是没证据的
都必须标出来）。但知识库里还有另一层：每篇末尾那节「未确认项 / 待办 / 下一步」，
**旧格式下它不带标记**，于是「到底还剩多少没解决」这个问题一直没有答案：
标记数说 51，章节里躺着两百多条，两个数字谁也不认谁。

这个模块把两层合起来数，并且**按状态列判定还开不开**：

* 章节里的**表格行**（``| # | 未确认内容 | 本地证据 | 状态 |``）—— 状态列含
  ``已答 / 已解决 / 已修正 / 已实测`` 之类即视为已关；
* 章节里的**列表项**（``- xxx`` / ``1. xxx``）——没有状态列，一律算开着
  （正文改造完这些会变成表格行）；
* ``已答（见 §x.y）`` 这种也算已关。

⚠️ 两个数字的关系：``v3 unverified`` ⊆ ``v3 backlog``（标记项大多也列在章节里），
所以**不要相加**。要「还剩多少真问题」看 backlog，要「有多少处承诺标着未确认」看
unverified。两个都能复算，口径写在这里。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from . import config
from .unknowns import MARKER

if TYPE_CHECKING:
    from pathlib import Path

#: 标题行：``(层级, 标题)``。**不能用 `pdx.unknowns._HEADING`** —— 那个只有
#: 一个捕获组（它只关心标题文字），层级是这里判定「节在哪结束」的关键。
_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")

#: 章节标题里出现这些词，就认为它是「未确认 / 待办」那一节。
SECTION_WORDS = ("待办", "未确认", "待实测", "下一步", "后续", "遗留", "待补", "已知缺口")

#: 状态列里出现这些词 → 视为已关。
CLOSED_WORDS = ("已答", "已解决", "已修正", "已确认", "已实测", "已复测", "已核对", "✅")

#: 列表项（``- xxx`` / ``1. xxx`` / ``- [ ] xxx``）。
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]\s+(?:\[[ xX]\]\s*)?|\d+[.)]\s+)(\S.*)$")

#: 表格分隔行（``| --- | --- |``）。
_SEPARATOR = re.compile(r"^\s*\|[\s:|-]+\|\s*$")

#: 表头里出现这些词，才认为这张表是**条目表**（而不是取证手册、配方表之类）。
#:
#: 这条判据是被 doc 04 §13.1 逼出来的：那一节是「四类证据 / 四条配方」的说明表，
#: 表格行竖着排下来会被逐行当成条目（实测多出 30 条假条目）。
#: 条目表的表头一律含「状态」或「未确认内容 / 问题 / 条目」这类列名。
_ITEM_HEADER = ("状态", "未确认内容", "问题", "条目", "待确认")


@dataclass(frozen=True, slots=True)
class Item:
    """一条待办 / 未确认条目。"""

    doc: str
    section: str
    line: int
    text: str
    status: str = ""

    @property
    def closed(self) -> bool:
        return any(w in self.status for w in CLOSED_WORDS)

    @property
    def marked(self) -> bool:
        """是否带 ``【未确认】`` 标记（与 :mod:`pdx.unknowns` 的集合对应）。"""
        return MARKER in self.text

    @property
    def where(self) -> str:
        return f"{self.doc}:{self.line}"


def _clean(text: str) -> str:
    text = text.strip().strip("|").strip()
    return re.sub(r"\s+", " ", text)


def _row_cells(line: str) -> list[str]:
    return [_clean(c) for c in line.strip().strip("|").split("|")]


def scan_doc(path: Path) -> list[Item]:
    """一篇文档里所有「未确认 / 待办」章节的条目。

    章节判定用**层级栈**：命中关键词的标题开启一节，直到出现同级或更高级的标题
    才结束 —— 子标题（``### 13.2 加载/覆盖语义``）继承父节的归属。
    第一版只看标题本身是否含关键词，于是 doc 04 §13 的六张子表**一条都没数到**
    （它们的标题是「13.2 加载/覆盖语义」这种），清单数字因此少了十几条。
    """
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:  # pragma: no cover - 权限/占用等极端情况
        return []

    out: list[Item] = []
    #: 命中关键词的标题：(层级, 标题)。空表示当前不在任何待办章节里。
    active: tuple[int, str] | None = None
    #: 当前表格是否为**条目表**（由表头判定，见 :data:`_ITEM_HEADER`）。
    item_table = False
    for i, raw in enumerate(lines, 1):
        head = _HEADING.match(raw)
        if head:
            level = len(head.group(1))
            title = head.group(2)
            if active and level <= active[0]:
                active = None
            if any(w in title for w in SECTION_WORDS):
                active = (level, title)
            item_table = False
            continue
        if active is None:
            continue
        section = active[1]
        if _SEPARATOR.match(raw):
            continue
        stripped = raw.lstrip()
        if stripped.startswith("|"):
            cells = _row_cells(raw)
            if any(w in " ".join(cells) for w in _ITEM_HEADER) and len(cells) >= 2:
                item_table = True  # 这一行是表头
                continue
            if not item_table or len(cells) < 2 or cells[0] in {"#", ""}:
                continue
            text = cells[1]
            status = cells[-1] if len(cells) >= 3 else ""
            if text and not text.startswith("#"):
                out.append(Item(path.name, section, i, text, status))
            continue
        item_table = False
        match = _LIST_ITEM.match(raw)
        if match:
            out.append(Item(path.name, section, i, _clean(match.group(1))))
    return out


@lru_cache(maxsize=1)
def all_items() -> tuple[Item, ...]:
    """全部条目（按篇名、行号排序）。"""
    items: list[Item] = []
    base = config.DOCS
    if not base.is_dir():  # pragma: no cover - 仓库里必然存在
        return ()
    for path in sorted(base.glob("*.md")):
        items.extend(scan_doc(path))
    return tuple(items)


def open_items(doc: str | None = None) -> list[Item]:
    """还开着的条目（``doc`` 给 ``"04"`` 这类前缀时只留那一篇）。"""
    return [
        it
        for it in all_items()
        if not it.closed and (not doc or it.doc.startswith(doc) or doc in it.doc)
    ]


def totals(doc: str | None = None) -> tuple[int, int]:
    """``(还开着, 已关)``。"""
    items = [it for it in all_items() if not doc or it.doc.startswith(doc) or doc in it.doc]
    closed = sum(1 for it in items if it.closed)
    return len(items) - closed, closed


def counts_by_doc() -> dict[str, int]:
    """每篇还开着多少条（升序篇名；没有的篇不出现）。"""
    out: dict[str, int] = {}
    for it in open_items():
        out[it.doc] = out.get(it.doc, 0) + 1
    return dict(sorted(out.items()))


def sections() -> dict[str, list[str]]:
    """篇名 → 它有哪些「未确认 / 待办」章节（去重、保持出现顺序）。"""
    out: dict[str, list[str]] = {}
    for it in all_items():
        names = out.setdefault(it.doc, [])
        if it.section not in names:
            names.append(it.section)
    return out


__all__ = [
    "CLOSED_WORDS",
    "SECTION_WORDS",
    "Item",
    "all_items",
    "counts_by_doc",
    "open_items",
    "scan_doc",
    "sections",
    "totals",
]
