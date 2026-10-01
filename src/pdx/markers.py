"""正文数字的**归属标记**：把「这个数字属于哪条断言」写进文档里。

为什么需要它
-----------
``v3 verify`` 的断言只管**数值对不对**，而正文里的那个数字仍要人改 —— 因为
文本来回扫描只能靠「锚点词 + 量级接近」去猜，同一行里有两个同量级数字时它分不清，
于是有了 :data:`pdx.verify.KNOWN_METRIC_MIXUPS` 那类「已知口径错配」的豁免。

标记把「猜」换成「绑定」：数字后面紧跟一个 HTML 注释（GitHub 渲染时不可见）

    GAME 下这 33 个目录共 205<!--claim:dip.group_files--> 个文件

* ``v3 verify`` 检查标记处的数字与断言期望是否一致；
* ``v3 verify --fix`` 只改**带标记的那一个数字** —— 不再猜、不会误伤同行其它数字；
* 标记指向的断言不存在 → 报错；有标记的断言**不再参与**锚点漂移扫描（绑定比扫描精确）。

口径（三条，都是踩出来的）
------------------------
* **标记贴在数字右边、中间最多一个空格**，允许 ``**205**`` / `` `205` `` 这种包裹 ——
  修的时候只换数字本身，包裹与空格原样保留（``--fix`` 幂等的前提）。
* **表格行不打标记**：表格归 ``v3 tables`` 所有，``--write`` 会整表重写，标记会被抹掉。
* **千位分隔符跟着现值走**：现值写 ``11,705`` 就继续按千分位格式化，写 ``11705`` 就写纯数字 ——
  文档的排版风格不该被工具改掉。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import config

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

#: 一条标记：``数字 [**或反引号] [一个空格] <!--claim:id-->``，**可以链式挂多条**。
#:
#: ``num`` 只捕获数字本身（含千分位），包裹字符不捕获 —— ``--fix`` 只替换 ``num``
#: 的跨度，于是 ``**205**`` 改完还是 ``**210**``。
#:
#: ``chain`` 让**同一个数字绑多条断言**（实测真需要：doc 02 那句
#: 「``.mod`` 与 ``descriptor.mod`` 文件数量为 **0**」同时是 6 条 ``pfx.vanilla_*``
#: 断言的证据）。没有它就只能绑第一条，其余几条永远显示「没有标记」。
MARKER_RE = re.compile(
    r"(?P<num>\d[\d,]*)(?P<wrap>\*{0,2}|`{0,2})(?P<gap> ?)"
    r"(?P<chain>(?:<!--claim:[A-Za-z0-9_.]+-->)+)"
)

#: 从 ``chain`` 里逐条取出断言 id。
_CHAIN_ID_RE = re.compile(r"<!--claim:([A-Za-z0-9_.]+)-->")


def parse_chain(chain: str) -> list[str]:
    """``<!--claim:a--><!--claim:b-->`` → ``["a", "b"]``（供迁移脚本复用）。

    >>> parse_chain("<!--claim:dip.group_files-->")
    ['dip.group_files']
    >>> parse_chain("<!--claim:a--><!--claim:b-->")
    ['a', 'b']
    >>> parse_chain("没有标记")
    []
    """
    return _CHAIN_ID_RE.findall(chain)


@dataclass(slots=True)
class Marker:
    """文档里的一处标记。"""

    doc: str
    line: int  # 1 基
    id: str
    value: int
    raw: str  # 文档里原本写的数字（保留千分位写法）
    start: int  # ``raw`` 在该行里的字符偏移
    end: int

    def describe(self) -> str:
        return f"{self.doc}:{self.line} {self.id} = {self.raw}"


def iter_markers(text: str, doc: str) -> Iterator[Marker]:
    """按行产出 ``text`` 里的全部标记（链式标记逐个展开）。"""
    for lineno, line in enumerate(text.splitlines(), start=1):
        for m in MARKER_RE.finditer(line):
            raw = m.group("num")
            for claim_id in _CHAIN_ID_RE.findall(m.group("chain")):
                yield Marker(
                    doc=doc,
                    line=lineno,
                    id=claim_id,
                    value=int(raw.replace(",", "")),
                    raw=raw,
                    start=m.start("num"),
                    end=m.end("num"),
                )


def markers_in(path: Path) -> list[Marker]:
    return list(iter_markers(path.read_text(encoding="utf-8"), path.name))


def all_markers(docs_dir: Path | None = None) -> list[Marker]:
    """全库标记（按文档名、行号排序）。"""
    base = docs_dir or config.DOCS
    out: list[Marker] = []
    for path in sorted(base.glob("*.md")):
        out.extend(markers_in(path))
    return out


def marker_ids_by_doc(docs_dir: Path | None = None) -> dict[str, set[str]]:
    """``文档名 → 该文档里出现过的断言 id``（跳过漂移扫描用）。"""
    out: dict[str, set[str]] = {}
    for m in all_markers(docs_dir):
        out.setdefault(m.doc, set()).add(m.id)
    return out


def format_value(value: int, raw: str) -> str:
    """按现值风格格式化新值：本来有千分位就继续用千分位。

    >>> format_value(205, "205")
    '205'
    >>> format_value(12345, "12,345")
    '12,345'
    >>> format_value(12345, "205")
    '12345'
    """
    return f"{value:,}" if "," in raw else str(value)


@dataclass(slots=True)
class MarkerFix:
    """一处待修的数字。"""

    doc: str
    line: int
    id: str
    old: str
    new: str

    def describe(self) -> str:
        return f"{self.doc}:{self.line} {self.id} {self.old} → {self.new}"


def apply_fixes(
    docs_dir: Path, expected: dict[str, int], *, write: bool = False
) -> tuple[list[MarkerFix], int]:
    """把标记处的数字改成断言期望值。

    返回 ``(改动清单, 检查过的标记数)``。``write=False`` 时只算不写 ——
    调用方据此既能报告、也能在 ``--fix`` 下真正落盘。

    **只替换数字的跨度**：包裹（``**`` / 反引号）、空格、标记本身都原样保留，
    所以对已经一致的文件再跑一次是**零改动**（幂等）。
    """
    fixes: list[MarkerFix] = []
    checked = 0
    for path in sorted(docs_dir.glob("*.md")):
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        changed = False
        for lineno, line in enumerate(lines, start=1):
            # 逐标记拼装新行：只换 ``num`` 的跨度，其余字符（包裹、空格、标记本身）
            # 原样搬过去。最初用闭包 + ``re.sub`` 写过一版，ruff 直接抓出
            # 「循环变量未绑定」与「nonlocal 漏声明」两个真 bug —— 正向拼装更直白。
            pieces: list[str] = []
            last = 0
            for m in MARKER_RE.finditer(line):
                raw = m.group("num")
                value = int(raw.replace(",", ""))
                ids = _CHAIN_ID_RE.findall(m.group("chain"))
                # 链式标记共用同一个数字：只要有一条对不上就改，改完所有条都满足
                # （同一个数字不可能同时等于两个不同的期望值 —— 真出现就是数据错，
                # 那时 --fix 会以最后一条为准，`v3 verify` 随即报红）。
                want = next(
                    (expected[i] for i in ids if i in expected and expected[i] != value), None
                )
                checked += len(ids)
                pieces.append(line[last : m.start("num")])
                if want is None:
                    pieces.append(raw)
                else:
                    new = format_value(want, raw)
                    fixes.extend(
                        MarkerFix(path.name, lineno, claim_id, raw, new)
                        for claim_id in ids
                        if expected.get(claim_id) == want
                    )
                    pieces.append(new)
                    changed = True
                last = m.end("num")
            if not pieces:
                continue
            pieces.append(line[last:])
            newline = "".join(pieces)
            if newline != line:
                lines[lineno - 1] = newline
        if changed and write:
            path.write_text("".join(lines), encoding="utf-8", newline="\n")
    return fixes, checked


def claims_without_markers(claim_docs: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """``[(claim_id, doc)]``：在文档里**一个标记都没有**的断言。

    这不是失败 —— 只写在表格里的断言由 ``v3 tables`` 拥有，不需要标记。
    它是给迁移与人工检查看的清单。
    """
    bound = {(m.doc, m.id) for m in all_markers()}
    return sorted((cid, doc) for cid, doc in claim_docs if (doc, cid) not in bound)


__all__ = [
    "MARKER_RE",
    "Marker",
    "MarkerFix",
    "all_markers",
    "apply_fixes",
    "claims_without_markers",
    "format_value",
    "iter_markers",
    "marker_ids_by_doc",
    "markers_in",
    "parse_chain",
]
