"""键名证据检索：把「未确认」压到四类可复算的证据上。

为什么要这个模块
--------------
doc 04 §13 有 28 项、全仓 92 处 **【未确认】**。它们此前只有两种命运：
猜一个（违背「不推测」）或永远躺着（等于没写）。其实其中相当一部分
**本地就有证据**，只是散在四个地方、口径各不相同：

======  ==========================================  ==========================
类      证据                                            复算方式
======  ==========================================  ==========================
①      原版用法：非注释的键位置、父键、取值形态          ``v3 evidence <键>``
②      官方 md：``game/**/*.md``（92 篇）里的行号       同上
③      MOD 用法：workshop + 本地 mod 的实践             ``v3 evidence --mods``
④      引擎字面量：``victoria3.exe`` 的标识符与邻居     同上
======  ==========================================  ==========================

口径（一次说清，免得又出现「无法复现的采集值」）
--------------------------------------------
* **只扫 ``.txt`` / ``.gui``**：两者都是 PDX 脚本语法，可以过同一个解析器。
  ``.yml`` 是显示文本，里面出现的词是**英语散文**（实测搜 ``orphan`` 会命中
  「orphaned and downtrodden」），算进脚本用法就是脏数据。
* **只用解析器的结果**：解析器天然丢掉 ``#`` 注释，所以
  ``#weight_multiplier = {`` 这类**被注释掉的写法不算用法**
  —— 这正是 doc 04 对 U3 的判断（「5 处全部被注释」）能机械复核的原因。
* **键名整串相等**：``a.key == 键``，不做子串匹配（``orphan`` 不会命中
  ``orphaned``）。
* ③ 是**本机快照**：取决于本机装了哪些 mod，任何文档都不得写成断言。

⚠️ ④ 是**线索不是结论**：见 :mod:`pdx.exe_strings` 的说明，邻居里混着
同节的无关字面量，且「引擎里有」≠「语法上合法」。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from . import config, exe_strings
from .cache import parse_cached
from .model import Block, ParsedFile
from .mods import discover_mods
from .parser import TOLERATED_ERRORS
from .scan import walk_files

if TYPE_CHECKING:
    from collections.abc import Collection, Iterator, Sequence

    from .model import Assignment, Node

#: 参与用法统计的扩展名（``.yml`` 故意不在内，理由见模块 docstring）。
SCRIPT_SUFFIXES: tuple[str, ...] = (".txt", ".gui")

#: 每个键最多留几条样例（CLI 展示用；统计不受它影响）。
SAMPLE_LIMIT = 3


@dataclass(frozen=True, slots=True)
class Sample:
    """一条用法样例。"""

    rel: str
    line: int
    parent: str
    form: str
    text: str

    @property
    def where(self) -> str:
        return f"{self.rel}:{self.line}"


@dataclass(slots=True)
class Usage:
    """某个键在原版（或某个根）里的用法画像。

    **键**与**值**分开统计，因为 doc 04 §13 里两类问题都有：
    ``orphan`` 是键（``orphan = yes``），而 ``character_event`` 是**值**
    （``type = character_event``）—— 只统计键就会得出「原版 0 处」这种
    看似反直觉的结论。
    """

    total: int = 0
    files: int = 0
    by_dir: Counter = field(default_factory=Counter)
    parents: Counter = field(default_factory=Counter)
    forms: Counter = field(default_factory=Counter)
    samples: list[Sample] = field(default_factory=list)
    #: 作为**标量值**出现的次数（``type = character_event``）
    values: int = 0
    value_parents: Counter = field(default_factory=Counter)
    value_samples: list[Sample] = field(default_factory=list)
    #: 该键自己的**标量取值分布**（``placement = X`` → X 的分布）
    scalar_values: Counter = field(default_factory=Counter)

    def add(
        self, *, rel: str, parent: str, form: str, line: int, text: str, scalar: str = ""
    ) -> None:
        self.total += 1
        self.by_dir[str(_dir_of(rel))] += 1
        self.parents[parent or "<顶层>"] += 1
        self.forms[form] += 1
        if scalar:
            self.scalar_values[scalar] += 1
        if len(self.samples) < SAMPLE_LIMIT:
            self.samples.append(Sample(rel, line, parent or "<顶层>", form, text))

    def add_value(self, *, rel: str, parent: str, key: str, line: int, text: str) -> None:
        """记录一次「本键出现在别人右边」。"""
        self.values += 1
        self.value_parents[parent or "<顶层>"] += 1
        if len(self.value_samples) < SAMPLE_LIMIT:
            self.value_samples.append(
                Sample(rel, line, parent or "<顶层>", f"{parent or '<顶层>'} = {key}", text)
            )


@dataclass(frozen=True, slots=True)
class DocHit:
    """官方 md 里的一处命中。

    ``kind`` 三态是刻意的：官方 md 是**英文散文**，``after`` / ``base`` / ``list``
    这类常用词会大量命中散文（实测 ``after`` 有 20 处，全是
    "after being established" 这种句子）。只有 ``码``（反引号里）与
    ``赋值``（``键 =``）才算「文档提到了这个键」。
    """

    rel: str
    line: int
    kind: str  # 码 / 赋值 / 散文
    text: str

    @property
    def where(self) -> str:
        return f"{self.rel}:{self.line}"

    @property
    def is_code(self) -> bool:
        return self.kind != "散文"


@dataclass(frozen=True, slots=True)
class Evidence:
    """一个键的四类证据合集。"""

    key: str
    vanilla: Usage
    docs: tuple[DocHit, ...] = ()
    prose: int = 0
    mods: tuple[tuple[str, int], ...] = ()
    exe_exact: bool = False
    exe_prev: tuple[str, ...] = ()
    exe_next: tuple[str, ...] = ()

    @property
    def documented(self) -> tuple[DocHit, ...]:
        """只保留「文档真的提到了这个键」的命中。"""
        return tuple(h for h in self.docs if h.is_code)

    @property
    def summary(self) -> str:
        """一行式小结（CLI 与文档引用同一句话，避免两边口径漂移）。"""
        v = self.vanilla
        parts = [f"原版键 {v.total} 处/{v.files} 文件"] if v.total else ["原版键 0 处"]
        if v.values:
            parts.append(f"作为值 {v.values} 处")
        documented = len(self.documented)
        parts.append(f"官方 md 提及 {documented} 处" if documented else "官方 md 0 处")
        if self.prose:
            parts.append(f"另有散文命中 {self.prose}")
        if self.mods:
            parts.append(f"mod {len(self.mods)} 个")
        parts.append("exe 有字面量" if self.exe_exact else "exe 无字面量")
        return "；".join(parts)


def _dir_of(rel: str) -> str:
    """``common/journal_entries/foo.txt`` → ``common/journal_entries``。"""
    head, _, _ = rel.rpartition("/")
    return head or rel


@lru_cache(maxsize=256)
def _lines(path: str) -> tuple[str, ...]:
    """按行读文件（只给样例取原文用，命中文件很少）。"""
    try:
        return tuple(Path(path).read_text(encoding="utf-8-sig", errors="replace").splitlines())
    except OSError:  # pragma: no cover - 权限/占用等极端情况
        return ()


def _form_of(value: Node | None) -> str:
    if value is None:
        return "无值"
    if isinstance(value, Block):
        return f"块({len(value.items)} 项)"
    text = getattr(value, "text", "")
    return f"= {text[:24]}" if text else "= <空>"


def _line_at(lines: tuple[str, ...], n: int) -> str:
    """取第 ``n`` 行原文（截断到 110 字符）；越界时给空串。"""
    return lines[n - 1].strip()[:110] if 0 < n <= len(lines) else ""


def _walk(node: Block | ParsedFile, parent: str = "") -> Iterator[tuple[Assignment, str]]:
    """递归产出 ``(赋值, 父键链)``。父键链是**包围它的块**的键，用 ``/`` 连接。"""
    items = node.top_assignments if isinstance(node, ParsedFile) else node.assignments()
    for a in items:
        yield a, parent
        if isinstance(a.value, Block):
            chain = f"{parent}/{a.key}" if parent else a.key
            yield from _walk(a.value, chain)


def _candidates(root: Path) -> Iterator[tuple[Path, str]]:
    """``root`` 下的脚本文件（``.txt`` / ``.gui``）。"""
    for entry in walk_files(root):
        if entry.path.suffix not in SCRIPT_SUFFIXES:
            continue
        try:
            rel = entry.path.relative_to(root).as_posix()
        except ValueError:  # pragma: no cover - walk_files 的产出必然在 root 下
            continue
        yield entry.path, rel


def scan_usage(keys: Collection[str], root: Path) -> dict[str, Usage]:
    """在 ``root`` 下统计这批键的用法。

    先按字节粗筛（键不是 ASCII 或文件里根本没这串就跳过），再过解析器 ——
    全树 8 千个文件里通常只有个位数文件命中，所以真实解析量很小。
    """
    wanted = {k for k in keys if k.isascii() and k}
    out: dict[str, Usage] = {k: Usage() for k in keys}
    if not wanted or not root.is_dir():
        return out

    needles = {k: k.encode() for k in wanted}
    for path, rel in _candidates(root):
        try:
            raw = path.read_bytes()
        except OSError:  # pragma: no cover - 权限/占用等极端情况
            continue
        present = {k for k, needle in needles.items() if needle in raw}
        if not present:
            continue
        try:
            pf = parse_cached(path)
        except TOLERATED_ERRORS:  # pragma: no cover - 解析器容忍范围内的坏文件
            continue
        lines = _lines(str(path))
        hit_files: set[str] = set()
        for a, parent in _walk(pf):
            value = a.value
            scalar = getattr(value, "text", "")
            if a.key in present:
                text = _line_at(lines, a.line)
                out[a.key].add(
                    rel=rel,
                    parent=parent,
                    form=_form_of(value),
                    line=a.line,
                    text=text,
                    scalar=scalar if isinstance(scalar, str) else "",
                )
                hit_files.add(a.key)
            # 反向：本批键出现在**右侧**（`type = character_event`）
            if isinstance(scalar, str) and scalar in present and scalar != a.key:
                text = _line_at(lines, a.line)
                out[scalar].add_value(rel=rel, parent=a.key, key=scalar, line=a.line, text=text)
                hit_files.add(scalar)
        for k in hit_files:
            out[k].files += 1
    return out


def _classify(line: str, key: str) -> str:
    """判断一行 md 是「提到这个键」还是「散文里恰好有这个单词」。"""
    quoted = re.search(rf"`{{1,2}}{re.escape(key)}`{{1,2}}", line)
    if quoted:
        return "码"
    if re.search(rf"(?<![\w-]){re.escape(key)}\s*=", line):
        return "赋值"
    return "散文"


def doc_hits(keys: Collection[str]) -> dict[str, list[DocHit]]:
    """官方 md（``game/**/*.md``）里出现这批键的篇名、行号与**命中性质**。

    一次扫描处理全部键。散文命中照样返回（``kind='散文'``），由调用方决定
    要不要看 —— 直接丢掉会让「20 处命中」这种数字无从解释。
    """
    out: dict[str, list[DocHit]] = {k: [] for k in keys}
    wanted = {k for k in keys if k.isascii() and k}
    if not wanted or not config.GAME.is_dir():
        return out
    for path in sorted(config.GAME.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:  # pragma: no cover - 权限/占用等极端情况
            continue
        rel = path.relative_to(config.GAME).as_posix()
        for i, line in enumerate(text.splitlines(), 1):
            for k in wanted:
                if k in line:
                    out[k].append(DocHit(rel, i, _classify(line, k), line.strip()[:110]))
    return out


def mod_hits(keys: Collection[str], roots: Sequence[Path]) -> dict[str, list[tuple[str, int]]]:
    """本机 mod 里出现这批键的次数（③ 类证据，本机快照）。"""
    out: dict[str, list[tuple[str, int]]] = {k: [] for k in keys}
    for root in roots:
        usage = scan_usage(keys, root)
        name = root.name
        for k, u in usage.items():
            if u.total:
                out[k].append((name, u.total))
    for hits in out.values():
        hits.sort(key=lambda item: (-item[1], item[0]))
    return out


def gather(
    keys: Sequence[str], *, mods: bool = False, span: int = 8, root: Path | None = None
) -> list[Evidence]:
    """一次取全这批键的四类证据（原版 / 官方 md / MOD / exe）。

    ``root`` 只影响 ① 类：给 ``GAME/common/scripted_lists`` 这类子树时，
    统计范围收窄到该目录（``base`` 这种常用词在整树里有 1448 处，收窄后才看得清）。
    ② ③ ④ 类不随 ``root`` 变。
    """
    keys = list(keys)
    vanilla = scan_usage(keys, root or config.GAME)
    docs = doc_hits(keys)
    mod_map: dict[str, list[tuple[str, int]]] = {k: [] for k in keys}
    if mods:
        mod_map = mod_hits(keys, discover_mods())
    neighbors = exe_strings.identifier_neighbors(keys, span=span)
    in_exe = exe_strings.exe_identifiers()
    return [
        Evidence(
            key=k,
            vanilla=vanilla[k],
            docs=tuple(docs[k]),
            prose=sum(1 for h in docs[k] if not h.is_code),
            mods=tuple(mod_map[k]),
            exe_exact=k in in_exe,
            exe_prev=neighbors[k][0] if neighbors[k] else (),
            exe_next=neighbors[k][1] if len(neighbors[k]) > 1 else (),
        )
        for k in keys
    ]


__all__ = [
    "SAMPLE_LIMIT",
    "SCRIPT_SUFFIXES",
    "DocHit",
    "Evidence",
    "Sample",
    "Usage",
    "doc_hits",
    "gather",
    "mod_hits",
    "scan_usage",
]
