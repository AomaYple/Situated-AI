"""由工具生成的 Markdown 表格：统一的替换与登记机制。

为什么需要这个模块
------------------
知识库里有一批表格是**机械统计**出来的：doc 05 的 5 张 defines 表、
doc 19 的 game 根目录文件表与 ``paths.settings`` 映射表。它们的共同点是
会随游戏版本静默漂移 —— 而 doc 05 那 5 张表**整整落后了一个游戏版本**
（总数 3434 应当变 3488），因为那批已退休的 PowerShell 脚本再没人重跑过。

上一轮给 doc 05 写了一份专门的替换逻辑。本模块把它抽成通用的东西，
让「再加一张生成的表」变成登记一行，而不是再抄一遍替换算法。

设计约定（每一条都对应实际踩过的坑）
------------------------------------
* **只替换数据行**：表头、``|---|`` 分隔线、以及表格前后的散文一律不碰 ——
  那些是文档作者写的解释，生成器不该覆盖它们。
* **允许行数变化**：这是相对第一版最重要的改动。游戏升级后新增一个
  ``paths.settings`` 映射、或多出一个根级文件，表格就该跟着变长；
  把「生成行数 == 文档现有行数」当成功条件，恰恰会让生成器在**最需要它的时候**
  拒绝工作。第一版就是这么写的。
* **表头找不到就报错，不静默跳过**：静默跳过是这类生成器腐烂的最快方式。
* **在副本上先试再写**：``write=True`` 时也是先算出完整文本再一次性落盘，
  中途失败不会留下半张表。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path


class TableNotFoundError(LookupError):
    """文档里找不到指定的表头 —— 说明表结构被改过，生成器应当停下来。"""


class TableMalformedError(ValueError):
    """表结构不合法（表头下面没有分隔线，或生成器给出了空表）。"""


@dataclass(slots=True)
class TableSpec:
    """一张「整表由工具生成」的表。

    ``header`` 是表头首行的**前缀**（够唯一即可，不必抄全）；
    ``rows`` 是取值函数，返回全部数据行（不含表头与分隔线）；
    ``occurrence`` 用于**同一文档里表头相同**的多张表（doc 19 的
    ``| 逻辑名 | 实际路径 |`` 出现三次），0 是第一张。
    """

    name: str
    header: str
    rows: Callable[[], list[str]]
    occurrence: int = 0


#: 新增行里，工具不拥有的列填什么 —— 让读者一眼看出「这里需要人补」
NEW_CELL = "—— **待补**"


@dataclass(slots=True)
class KeyedTableSpec:
    """一张「只有部分列由工具生成」的表 —— 其余列是散文，必须保留。

    doc 19 的根目录文件表就是这种：``文件 | 字节 | 作用``，前两列是机械的，
    第三列是作者写的说明。整表重生成会把说明抹掉，只按键更新数字列才对。

    * ``cells()`` 返回 ``[(键, {列下标: 文本}), …]``，**顺序即行的顺序**；
    * 未列出的列从文档现值里按键保留；
    * 文档里没有的新键会追加，工具不拥有的列填 :data:`NEW_CELL`；
    * 文档里有、生成结果里没有的行会被**删掉**（说明那个文件真的没了）。

    ``key_column`` 是键所在的列下标（默认 0）。

    三个开关用来覆盖上面最后两条默认行为 —— 都是被 doc 08 逼出来的：

    * ``allow_drop``：允许「文档里有、生成结果里没有」的行被删掉。默认
      **不允许，未匹配的行原样保留** —— 静默删行是最危险的一种失败，实测踩过：
      doc 08 的 §3 把几个 DLL 合并成一行（``| `fmodL.dll` / `fmodstudio.dll` | … |``），
      「一文件一行」的生成器认不出这个键，于是把它们全删了，表格短了 5 行，
      后面每一行的散文都跟着错位。**错的散文比错的数字更难发现。**
      键集合确实权威（文件没了就该删行）的表再显式开它。
    * ``append_new``：生成结果里多出来的键**不追加**。用于**节选**表：
      doc 08 的 §3 只列「体积最大的几个原生依赖」，若把 binaries 下 40 个文件
      全追加进去，节选就不再是节选。

    合并行（一行里塞多个条目）**不需要额外开关**：键里的 `` / `` / ``、`` /
    ``, `` 会被拆开逐个匹配，全部匹配上就按同样的分隔符把生成值拼回去 ——
    作者的分组意图得以保留，而数字仍然是算出来的。
    """

    name: str
    header: str
    cells: Callable[[], list[tuple[str, dict[int, str]]]]
    key_column: int = 0
    occurrence: int = 0
    append_new: bool = True
    allow_drop: bool = False


def _split_row(line: str) -> list[str]:
    """``| a | b |`` → ``['a', 'b']``（去首尾空单元格与两端空白）。"""
    stripped = line.strip()
    stripped = stripped.removeprefix("|")
    stripped = stripped.removesuffix("|")
    return [c.strip() for c in stripped.split("|")]


def patch_doc(
    doc: Path, specs: Sequence[TableSpec | KeyedTableSpec], *, write: bool = False
) -> dict[str, int]:
    """按 ``specs`` 重算 ``doc`` 里的表格，返回 ``{表名: 替换的行数}``。

    ``write=False``（默认）只做核对：算出结果、与文档现值比对，
    但**不落盘**。调用方据此报告「有几张表需要更新」。
    """
    lines = doc.read_text(encoding="utf-8").splitlines(keepends=True)
    replaced: dict[str, int] = {}

    for spec in specs:
        start = _find_header(lines, doc, spec)
        if start + 1 >= len(lines) or not _is_separator(lines[start + 1]):
            raise TableMalformedError(f"{doc.name} 的表 {spec.name!r} 下面没有 |---| 分隔线")

        # 表格现有数据行的**文本**（保留散文列要用）
        end = start + 2
        while end < len(lines) and lines[end].lstrip().startswith("|"):
            end += 1

        want = (
            spec.rows()
            if isinstance(spec, TableSpec)
            else _merge_rows(spec, [_split_row(ln) for ln in lines[start + 2 : end]])
        )
        if not want:
            raise TableMalformedError(f"表 {spec.name!r} 生成了 0 行 —— 多半是游戏目录不可用")

        lines[start + 2 : end] = [row + "\n" for row in want]
        replaced[spec.name] = len(want)

    if write:
        doc.write_text("".join(lines), encoding="utf-8", newline="\n")
    return replaced


def _find_header(lines: list[str], doc: Path, spec: TableSpec | KeyedTableSpec) -> int:
    """定位表头行；``occurrence`` 指定「同表头的第几张」。

    同一文档里表头相同是常见情形（doc 19 的三张 ``| 逻辑名 | 实际路径 |``
    是按语义分组的）。不区分出现次序就永远只能改到第一张 ——
    而后面几张照样漂。
    """
    hits = [n for n, ln in enumerate(lines) if ln.startswith(spec.header)]
    if not hits:
        raise TableNotFoundError(f"{doc.name} 里找不到表头：{spec.header}")
    if spec.occurrence >= len(hits):
        raise TableNotFoundError(
            f"{doc.name} 里表头 {spec.header!r} 只出现 {len(hits)} 次，"
            f"取不到第 {spec.occurrence + 1} 张（表 {spec.name!r}）"
        )
    return hits[spec.occurrence]


def _norm_key(text: str) -> str:
    """比对键时用的规范形式：去掉空白与 Markdown 反引号。

    doc 19 的键列写的是 ``| `checksum_manifest.txt` |``，而生成器给的是
    ``checksum_manifest.txt`` —— 不做规范化就一行都匹配不上，
    整张表的散文列会被填成「待补」（实测撞过：37 行全部不匹配）。
    """
    return text.strip().strip("`").strip()


#: 合并行里各条目之间的分隔符。按**长到短**匹配（``" / "`` 先于 ``", "``），
#: 否则 ``"a / b"`` 会被 ``", "`` 抢走一半。
_GROUP_SEPS: tuple[str, ...] = (" / ", "、", ", ")


def _group_cells(norm: str, generated: dict[str, dict[int, str]]) -> dict[int, str] | None:
    """把「一行多个条目」的键拆开逐个查表，再按原分隔符拼回来。

    doc 08 的 §3 就是这么写的：``| `fmodL.dll` / `fmodstudioL.dll` | 2,301,952 / … |``。
    生成器按单个文件名给键，直接查表永远查不到 —— 旧行为是**把这行删掉**，
    于是表格短了几行、后面所有行的散文都错位。

    要求每个拆分出来的键都查得到，且它们给出的列下标集合一致；
    否则返回 ``None``（调用方保留原行，绝不猜）。
    """
    for sep in _GROUP_SEPS:
        if sep not in norm:
            continue
        parts = [_norm_key(p) for p in norm.split(sep)]
        if len(parts) < 2 or not all(parts):
            continue
        subs = [generated.get(p) for p in parts]
        if any(s is None for s in subs):
            return None
        idxs = {frozenset(s) for s in subs if s is not None}
        if len(idxs) != 1:
            return None  # 各条目的生成列不一致 —— 拼起来会缺格
        return {i: sep.join(str(s[i]) for s in subs if s is not None) for i in idxs.pop()}
    return None


def _merge_rows(spec: KeyedTableSpec, existing: list[list[str]]) -> list[str]:
    """按键把生成的单元格并进文档现有的行。

    两条默认规则，都是为了**不夺走文档作者的信息**：

    * **未生成的列保留原文** —— 那些是散文，工具不该覆盖；
    * **行的顺序沿用文档** —— doc 19 的根目录文件表按语义排（先配置文件、
      后素材），生成器按文件名排会把它打乱。只有文档里没有的**新键**
      才追加到末尾（工具不拥有的列填「待补」，提示人来写说明）。

    ``allow_drop`` / ``append_new`` 两个开关分别控制「删掉未匹配的行」与
    「追加新键」，供**键集合权威**与**节选**两类表使用 —— 见
    :class:`KeyedTableSpec` 的说明。
    """
    generated: dict[str, dict[int, str]] = {}
    for key, spec_cells in spec.cells():
        generated[_norm_key(key)] = spec_cells

    out: list[str] = []
    seen: set[str] = set()
    dropped: list[str] = []
    for row in existing:
        if len(row) <= spec.key_column:
            continue
        norm = _norm_key(row[spec.key_column])
        cells: dict[int, str] | None = generated.get(norm)
        if cells is None:
            cells = _group_cells(norm, generated)  # 合并行：拆开逐个查，再拼回去
        if cells is None:
            # 生成结果里没有它。默认**原样保留**：静默删行会让整张表错位，
            # 而错位的散文比错的数字更难发现。确实该删的表用 allow_drop 显式声明。
            if not spec.allow_drop:
                out.append("| " + " | ".join(row) + " |")
            else:
                dropped.append(norm)
            continue
        seen.add(norm)
        out.append(_render(row, cells))
    if dropped:
        # 只有显式开了 allow_drop 才会走到这里；把删掉的东西打出来，
        # 免得「表短了几行」这种事只能靠肉眼发现。
        print(
            f"[doc_tables] {spec.name}: 删除了 {len(dropped)} 行 —— "
            f"{dropped[:5]}{' …' if len(dropped) > 5 else ''}",
            file=sys.stderr,
        )
    if spec.append_new:
        for norm, cells in generated.items():
            if norm not in seen:
                out.append(_render([], cells))
    return out


def _render(row: list[str], generated: dict[int, str]) -> str:
    """把生成的单元格并进一行，未提供的列保留 ``row`` 的原文。"""
    width = max([len(row), *(i + 1 for i in generated)], default=1)
    cells = [row[i] if i < len(row) else "" for i in range(width)]
    for idx, text in generated.items():
        cells[idx] = text
    for i in range(width):
        if i not in generated and not cells[i]:
            cells[i] = NEW_CELL
    return "| " + " | ".join(cells) + " |"


def _is_separator(line: str) -> bool:
    """``|---|:--:|`` 这类分隔线。"""
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return False
    body = stripped.strip("|")
    return bool(body) and all(set(cell.strip()) <= set("-: ") for cell in body.split("|"))


def check_doc(
    doc: Path, specs: Sequence[TableSpec | KeyedTableSpec]
) -> list[tuple[str, int, str, str]]:
    """核对而不修改，返回 ``[(表名, 行号, 文档现值, 生成值), …]``。

    这是**给别人看的线索**：`v3 tables` 默认走这条，告诉用户哪几行不一致。
    """
    lines = doc.read_text(encoding="utf-8").splitlines()
    out: list[tuple[str, int, str, str]] = []
    for spec in specs:
        start = _find_header(lines, doc, spec)
        end = start + 2
        while end < len(lines) and lines[end].startswith("|"):
            end += 1
        want = (
            spec.rows()
            if isinstance(spec, TableSpec)
            else _merge_rows(spec, [_split_row(ln) for ln in lines[start + 2 : end]])
        )
        n = start + 2
        for expected in want:
            actual = lines[n] if n < len(lines) else "<表格结束>"
            if actual != expected:
                out.append((spec.name, n + 1, actual, expected))
            n += 1
        # 文档里剩下的行若还是表格行，说明文档比生成结果长 —— 也算不一致
        while n < len(lines) and lines[n].startswith("|"):
            out.append((spec.name, n + 1, lines[n], "<生成结果里没有这一行>"))
            n += 1
    return out
