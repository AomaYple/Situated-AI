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

import re
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


def split_row(line: str) -> list[str]:
    """``| a | b |`` → ``['a', 'b']``（去首尾空单元格与两端空白）。

    >>> split_row("| 名字 | 数量 |")
    ['名字', '数量']
    >>> split_row("| `a` | 1 |")
    ['`a`', '1']
    """
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
            else merge_rows(
                spec,
                [split_row(ln) for ln in lines[start + 2 : end]],
                width=len(split_row(lines[start])),
                raw=[ln.rstrip("\n") for ln in lines[start + 2 : end]],
            )
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


def norm_key(text: str) -> str:
    """比对键时用的规范形式：去掉空白、Markdown 反引号**与加粗星号**。

    doc 19 的键列写的是 ``| `checksum_manifest.txt` |``，而生成器给的是
    ``checksum_manifest.txt`` —— 不做规范化就一行都匹配不上，
    整张表的散文列会被填成「待补」（实测撞过：37 行全部不匹配）。

    ``*`` 是后补的：doc 16 有大量**加粗的键**（``| **`usage_limit`** |``），
    不剥星号时那些行永远匹配不上 —— 于是它们的数字**永远不会被更新**
    （静默过期），而盘点还认为整张表「已看守」。

    **公开**（不再是 ``_norm_key``）：表的键在文档里常写成 ``| `player_subject` |``，
    而计数器给的键是不带反引号的值 —— 取值函数必须用同一个规范化函数去查计数器，
    否则**每行都查不到、全写 0**，而 ``append_new=False`` 的表连警告都不打
    （doc 17 实测：整列变 0，靠 `v3 tables` 的 diff 才发现）。

    >>> norm_key("`checksum_manifest.txt`")
    'checksum_manifest.txt'
    >>> norm_key("**`usage_limit`**")
    'usage_limit'
    """
    return text.strip().strip("`*").strip()


#: 合并行里各条目之间的分隔符。按**长到短**匹配（``" / "`` 先于 ``", "``），
#: 否则 ``"a / b"`` 会被 ``", "`` 抢走一半。
_GROUP_SEPS: tuple[str, ...] = (" / ", "、", ", ")


def key_parts(text: str) -> list[str]:
    """一行里的多个条目：``| `a` / `b` |`` → ``["a", "b"]``。

    单个条目时返回单元素列表（即 ``[norm_key(text)]``）。
    每个部分都各自过一遍 :func:`norm_key` —— 合并行的写法是
    ``| `fmodL.dll` / `fmodstudio.dll` |``，只对整个单元格剥一次反引号会剩下
    内层的那些（``'.shader`'`` 这种半截键），从而一行都匹配不上。

    生成器的合并行机制与测试的「每一行都有人认领」都用它，**判定必须同源**。
    """
    norm = norm_key(text)
    for sep in _GROUP_SEPS:
        if sep not in norm:
            continue
        parts = [norm_key(p) for p in norm.split(sep)]
        if len(parts) > 1 and all(parts):
            return parts
    return [norm]


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
        parts = key_parts(norm)
        if len(parts) < 2:
            continue
        subs = [generated.get(p) for p in parts]
        if any(s is None for s in subs):
            return None
        idxs = {frozenset(s) for s in subs if s is not None}
        if len(idxs) != 1:
            return None  # 各条目的生成列不一致 —— 拼起来会缺格
        return {i: sep.join(str(s[i]) for s in subs if s is not None) for i in idxs.pop()}
    return None


def merge_rows(
    spec: KeyedTableSpec,
    existing: list[list[str]],
    *,
    width: int = 0,
    raw: list[str] | None = None,
) -> list[str]:
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
    #: 规范化键 → 生成器给的**原始键文本**。追加新行时必须把键写回去 ——
    #: 少了它，新行会渲染成一整行「待补」，连名字都没有（实测：给 doc 08 §9.1
    #: 加一个 common 子目录，生成的是 `| —— **待补** | —— **待补** | 1 | 0 | … |`），
    #: 而且**下一轮认不出这行是自己刚写的**，于是每跑一次 `--write` 就再追加一条，
    #: 表格永远报红。
    key_text: dict[str, str] = {}
    for key, spec_cells in spec.cells():
        norm = norm_key(key)
        generated[norm] = spec_cells
        key_text[norm] = key

    out: list[str] = []
    seen: set[str] = set()
    dropped: list[str] = []
    unmatched: list[str] = []
    for row in existing:
        if len(row) <= spec.key_column:
            continue
        norm = norm_key(row[spec.key_column])
        cells: dict[int, str] | None = generated.get(norm)
        grouped = False
        if cells is None:
            cells = _group_cells(norm, generated)  # 合并行：拆开逐个查，再拼回去
            grouped = cells is not None
        if cells is None:
            # 生成结果里没有它。默认**原样保留**：静默删行会让整张表错位，
            # 而错位的散文比错的数字更难发现。确实该删的表用 allow_drop 显式声明。
            if not spec.allow_drop:
                # 原样输出**原文**：从单元格重拼会把 `| |` 写成 `|  |`
                out.append(raw[len(out)] if raw is not None else "| " + " | ".join(row) + " |")
                unmatched.append(norm)
            else:
                dropped.append(norm)
            continue
        seen.add(norm)
        # 已存在的行有三个「别动」的理由（都踩过）：
        #   1. **不填空单元格** —— 作者常故意留空末尾列（doc 16 有 89 行写成
        #      `| key | 18 | ✅ | |`），填成「—— **待补**」是替作者加话；
        #   2. **不补齐表头宽度** —— 同理会把 3 列的行改写成 4 列；
        #   3. **值没变就整行原样输出** —— 否则 `| |` 会被重拼成 `|  |`，
        #      89 行的纯空格差异把真正的改动淹掉（实测）。
        # 只有**追加的新行**才补宽度与空列（见下），因为新行没有原文可依。
        # 合并行**不套 _merge_cell**：那里的「 / 」是两个条目的分隔符，
        # 不是「N 分之 M」。套上去会把 `10 / 20` 变成 `10 / 2`（实测被测试抓到）。
        merged = (
            dict(cells)
            if grouped
            else {i: _merge_cell(row[i] if i < len(row) else "", text) for i, text in cells.items()}
        )
        if raw is not None and _same_cells(row, merged):
            out.append(raw[len(out)])  # 值没变 → 整行原样（含空格与加粗）
        else:
            out.append(_render(row, merged))
    if dropped:
        # 只有显式开了 allow_drop 才会走到这里；把删掉的东西打出来，
        # 免得「表短了几行」这种事只能靠肉眼发现。
        _warn(spec.name, "删除了", dropped)
    if unmatched and spec.append_new:
        # 只在**声称枚举全部条目**的表上出声（``append_new=True``）。
        #
        # 为什么必须出声：游戏升级删掉某个目录时，它的行会带着旧数字留在表里，
        # 而 `v3 tables` 照样报「全部一致」—— 那是最难发现的一类失效
        # （表格看着完整、数字却已经死了）。
        #
        # 为什么限定范围：``append_new=False`` 的表**本来就只覆盖子集**
        # （节选表、只更新几行的版本指纹表），未匹配是设计使然。
        # 实测给全部表都出声会稳定报三张表的十几行 —— 那种噪声会训练人
        # 忽略这条提示，比不出声更糟。
        #
        # 只提示、不报错：文档里作者自己加的说明行也会走到这里，
        # 报错会把正常的作者改动变成门禁红灯。
        _warn(
            spec.name,
            "未匹配、已原样保留",
            unmatched,
            hint="（游戏升级删了目录，还是文档里多了一行说明？）",
        )
    if spec.append_new:
        for norm, cells in generated.items():
            if norm not in seen:
                # 键列也要生成：文档里的键一律带反引号（``| `common` |``），
                # 照这个写法补上，新行才是「一行完整的数据」而不是一行问号。
                #
                # 还要按**表头宽度**补齐：生成器只知道它有值的列，不补的话
                # 新行会比表头短一截（实测 6 列的表追加出 5 列的行），
                # Markdown 渲染出来缺格，而作者也看不出该补哪一列。
                new_cells: dict[int, str] = {spec.key_column: f"`{key_text[norm]}`", **cells}
                out.append(_render([], new_cells, min_width=width, fill_missing=True))
    return out


def _warn(table: str, what: str, keys: list[str], *, hint: str = "") -> None:
    """把生成器「没能覆盖的行」打到 stderr。

    为什么不抛异常：这两种情况都可能是**正常**的（作者在表里加了一行说明、
    或者确实该删的表开了 ``allow_drop``）。它们需要的是被人看见，
    而不是把门禁卡死 —— 一个动不动就红的检查会很快被忽略。
    """
    shown = ", ".join(keys[:5])
    more = f" …（共 {len(keys)} 行）" if len(keys) > 5 else ""
    print(f"[doc_tables] {table}: {what} {len(keys)} 行 —— {shown}{more}{hint}", file=sys.stderr)


#: 单元格里的数字段（可能带千位分隔符）
#: 单元格里的数字段（可能带千位分隔符 —— 逗号**或空格**）。
#:
#: 空格是后补的：doc 06 的几张表把千位分隔符写成空格（``1 013`` / ``10 252``），
#: 而生成器写逗号。不认空格时 ``**11 294**`` 会被当成**两个**数字段，
#: 落进「不是恰好一个数字」的分支 → 整格替换 → **加粗被抹掉**
#: （实测：doc 06 的 `.dds` 那一行）。
_NUM_PAT = r"\d[\d,]*(?: \d{3})*"
_NUM_IN_CELL = re.compile(_NUM_PAT)


def _merge_cell(old: str, new: str) -> str:
    """把新数字写进旧单元格，**保留数字之外的文字**。

    ``**77**（可重复）`` + 新值 ``80`` → ``**80**（可重复）``：
    强调与括注都是作者的，生成器只拥有那个数字。
    旧格里只有数字（或没有数字）时才整格替换。

    千位分隔符的风格由**生成器**决定（一律逗号），作者写在数字两边的
    文字与强调一律保留 —— ``**11 294**`` + ``11,294`` → ``**11,294**``。
    """
    old_s = old.strip()
    if not old_s:
        return new
    m_new = _NUM_IN_CELL.search(new)
    if m_new is None:
        return new  # 新值里没数字 —— 没什么可保留的
    new_num: str = str(m_new.group(0))

    # 形式一：「N / M」—— 分子归生成器，**分母是作者的**（如「239 个条目里 239 个」）
    slash = re.fullmatch(rf"(.*?)({_NUM_PAT})(\s*/\s*{_NUM_PAT}.*)", old_s)
    if slash:
        return slash.group(1) + new_num + slash.group(3) if slash.group(2) != new_num else old_s

    # 形式二：整格恰好一个数字段、两边的文字都归作者（``**77**（可重复）``）
    olds = _NUM_IN_CELL.findall(old_s)
    if len(olds) != 1 or len(_NUM_IN_CELL.findall(new)) != 1:
        # 形式三：生成的是**纯数字**、且旧格**以数字开头** → 只换那一个数字。
        #
        # 这一条是被 doc 15 逼出来的：``8（在 `03_` 里）`` 有两个数字段（8 与 03），
        # 走「整格替换」会把作者的括注抹掉 —— 而且**值没变时也抹**
        # （每次 `--write` 都掉一次，属于「夺走作者信息」）。
        # 加了这个判据后 ``8（在 `03_` 里）`` → ``9（在 `03_` 里）``。
        #
        # 为什么要求「生成值必须是纯数字」：doc 08 的体积列形如
        # ``17,055.76 MB``，生成器给的是**整格文本** ``17,056 MB`` ——
        # 那种情况必须整格替换，否则会拼出 ``17,056.76 MB``（实测撞过，418 行）。
        if re.fullmatch(r"[\d,]+", new.strip()):
            head = _NUM_IN_CELL.match(old_s)
            if head is not None:
                return old_s[: head.start()] + new.strip() + old_s[head.end() :]
        return new
    if str(olds[0]) == new_num:
        return old_s  # 数字没变 → 连排版一起保留
    m = _NUM_IN_CELL.search(old_s)
    assert m is not None
    return old_s[: m.start()] + new_num + old_s[m.end() :]


def _same_cells(row: list[str], generated: dict[int, str]) -> bool:
    """生成值与文档现值是否**逐格相同**（忽略空白与加粗记号）。

    用途是「值没变就别动这一行」：Markdown 里 ``| |`` 与 ``|  |`` 渲染相同，
    但 diff 里是两行差异。忽略加粗是因为生成器不写强调，而强调是装饰、
    不是内容 —— 真要保留强调，就该连值一起不变。
    """

    def norm(s: str) -> str:
        return s.replace("*", "").strip()

    return all(norm(text) == norm(row[i] if i < len(row) else "") for i, text in generated.items())


def _render(
    row: list[str],
    generated: dict[int, str],
    *,
    min_width: int = 0,
    fill_missing: bool = False,
) -> str:
    """把生成的单元格并进一行，未提供的列保留 ``row`` 的原文。

    ``min_width`` 是**表头的列数**；``fill_missing`` 决定空单元格要不要填
    :data:`NEW_CELL`。两者都**只给追加的新行用**：

    * 新行没有原文可依，不补齐到表头宽度就会缺格，而作者也看不出该补哪一列；
    * 已存在的行**不能填**：作者有意留空的单元格很常见
      （doc 16 有 69 行写成 ``| `key` | 18 | ✅ | |``，第四列本来就是空的），
      填上「待补」等于**替作者加话** —— 实测就是这么误伤 69 行的。
    """
    width = max([len(row), min_width, *(i + 1 for i in generated)], default=1)
    cells = [row[i] if i < len(row) else "" for i in range(width)]
    for idx, text in generated.items():
        cells[idx] = text
    if fill_missing:
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
            else merge_rows(
                spec,
                [split_row(ln) for ln in lines[start + 2 : end]],
                width=len(split_row(lines[start])),
                raw=[ln.rstrip("\n") for ln in lines[start + 2 : end]],
            )
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


def current_rows(doc: Path, spec: TableSpec | KeyedTableSpec) -> list[str]:
    """文档里**现在**写着的表格数据行（不含表头与分隔线）。"""
    lines = doc.read_text(encoding="utf-8").splitlines()
    start = _find_header(lines, doc, spec)
    end = start + 2
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    return lines[start + 2 : end]


def write_rows(doc: Path, spec: TableSpec | KeyedTableSpec, rows: Sequence[str]) -> int:
    """把 ``rows`` 写进文档里该表的位置（行数可增可减），返回写入行数。

    `v3 tables --offline --write` 用它：**离线**（不读游戏）按快照里记录的
    行把文档恢复成「当时算出来的样子」。表头、分隔线与表格前后的散文一律不动 ——
    与 :func:`patch_doc` 同一套约定。
    """
    lines = doc.read_text(encoding="utf-8").splitlines(keepends=True)
    start = _find_header(lines, doc, spec)
    end = start + 2
    while end < len(lines) and lines[end].lstrip().startswith("|"):
        end += 1
    lines[start + 2 : end] = [row.rstrip("\n") + "\n" for row in rows]
    doc.write_text("".join(lines), encoding="utf-8", newline="\n")
    return len(rows)


def spec_key(doc_name: str, spec: TableSpec | KeyedTableSpec) -> str:
    """快照里用的表标识：``文档名::表名``（``occurrence`` 已含在表名里时也不冲突）。

    必须**稳定**：它是「文档里的表」与「快照里的行」之间唯一的对接口，
    改一次格式就等于把旧快照里的记录全部作废。
    """
    suffix = f"#{spec.occurrence}" if spec.occurrence else ""
    return f"{doc_name}::{spec.name}{suffix}"
