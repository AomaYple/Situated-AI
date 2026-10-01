"""文档里的 **【未确认】** 项：可复算的待验证清单。

为什么要有它
----------
「不推测」这条规矩的代价是文档里会留下 **【未确认】**。但这些标记此前
只能靠人翻：到底有多少处、分布在哪几篇、哪些已经在别处答过了 —— 全靠记忆。
doc 04 §13 那份 U1–U28 清单就是一次人工整理，而人工整理会随正文修改而漂移。

这个模块只做一件事：**扫出全部标记并给出可定位的上下文**
（``v3 unverified``），让「还剩多少没验证」变成可数的事实。

口径
----
* 标记词就是 ``【未确认】``，逐行扫描 ``docs/victoria3-modding/*.md``；
* ``章节`` = 该行上方最近的 ``#`` 标题（用来定位到节，不用另建索引）；
* ``上下文`` = 该行去掉标记后的原文（截断到 120 字符）；
* 本模块**不判断**某一项是否已经答过 —— 那需要证据，而证据在
  :mod:`pdx.evidence`、结论在正文。清单只负责「有哪些、在哪」。

⚠️ 退出码无关：这是**清单**不是门禁。真正的门禁是 ``v3 verify``（数字/标记）
与 pytest（结构/一致性）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from . import config

if TYPE_CHECKING:
    from pathlib import Path

#: 标记词。用全角方括号是刻意的：正文里的半角 ``[未确认]`` 不会被误算。
MARKER = "【未确认】"

#: **元陈述**：这句话本身在*说明*标记约定（「无法确认的一律标注 **【未确认】**」），
#: 不是在*使用*标记。不排掉它们，清单里就会混进假条目 ——
#: 实测有 4 处：doc 04 的约定句与 §13 导语、doc 06 的约定句、索引页的说明。
#:
#: 判据：标记前后 24 个字符内出现「标注 / 标为 / 列出 / 一律 / 统一 / 全部 / 所有」
#: 这类**说明性动词**。真正的条目是「某字段的语义 **【未确认】**」这种句型，
#: 不含上述动词（`test_unknowns_covgate.py` 里正反两面的例子都钉住了）。
_META_NEAR = re.compile(
    r"(?:标注|标为|列出|一律|统一|全部|所有)[^。；\n]{0,24}【未确认】"
    r"|【未确认】[^。；\n]{0,10}(?:项|条目)"
)

#: 文档标题行（``## 12. xxx`` / ``### 12.1 xxx``）。
_HEADING = re.compile(r"^#{1,6}\s+(.*\S)\s*$")

#: 上下文截断长度。
CONTEXT_LIMIT = 120


def is_meta_statement(line: str) -> bool:
    """这一行是不是在**说明**标记约定，而不是在使用标记。"""
    return bool(_META_NEAR.search(line))


@dataclass(frozen=True, slots=True)
class Unverified:
    """一处 【未确认】。"""

    doc: str
    line: int
    section: str
    text: str

    @property
    def where(self) -> str:
        return f"{self.doc}:{self.line}"

    @property
    def context(self) -> str:
        return self.text[:CONTEXT_LIMIT]


def docs_dir() -> Path:
    """知识库目录（``docs/victoria3-modding``）。"""
    return config.DOCS


def doc_files(doc: str | None = None) -> list[Path]:
    """全部文档；``doc`` 给 ``"04"`` 这类前缀时只留那一篇。"""
    base = docs_dir()
    if not base.is_dir():  # pragma: no cover - 仓库里必然存在
        return []
    files = sorted(base.glob("*.md"))
    if doc:
        files = [p for p in files if p.name.startswith(doc) or doc in p.name]
    return files


def scan_doc(path: Path) -> list[Unverified]:
    """一篇文档里的全部 【未确认】。"""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:  # pragma: no cover - 权限/占用等极端情况
        return []

    out: list[Unverified] = []
    section = ""
    for i, raw in enumerate(lines, 1):
        head = _HEADING.match(raw)
        if head:
            section = head.group(1)
        if MARKER not in raw or is_meta_statement(raw):
            continue
        out.append(
            Unverified(
                doc=path.name,
                line=i,
                section=section,
                text=raw.strip(),
            )
        )
    return out


@lru_cache(maxsize=1)
def all_items() -> tuple[Unverified, ...]:
    """全库的所有 【未确认】项（按篇名、行号排序）。"""
    items: list[Unverified] = []
    for path in doc_files():
        items.extend(scan_doc(path))
    return tuple(items)


def unverified_items(doc: str | None = None) -> list[Unverified]:
    """按篇过滤后的清单；过滤不走缓存（``doc`` 的参数空间是开放的）。"""
    if not doc:
        return list(all_items())
    out: list[Unverified] = []
    for path in doc_files(doc):
        out.extend(scan_doc(path))
    return out


def counts_by_doc() -> dict[str, int]:
    """每篇的处数（升序篇名）—— 汇总表与测试共用同一口径。"""
    out: dict[str, int] = {}
    for item in all_items():
        out[item.doc] = out.get(item.doc, 0) + 1
    return out


__all__ = [
    "CONTEXT_LIMIT",
    "MARKER",
    "Unverified",
    "all_items",
    "counts_by_doc",
    "doc_files",
    "docs_dir",
    "is_meta_statement",
    "scan_doc",
    "unverified_items",
]
