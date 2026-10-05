"""9 国目标函数表（`mod/data/*.toml` 的 `[objectives]`）的判据与渲染。

**判据的唯一定义不在本模块，而在** `docs/design/exec/阶段5-目标函数表-口径.md`（v3）：
住址（§1）、形状 schema（§2.1）、四档刻度（§2.2）、渲染表的列（§2.3）、
来源与「不许编的清单」（§3）、五条闸门 P1–P5（§4.1）与 `derive()`（§4.1.1）、
退出码三档与报告形态（§4.1.2）。本模块**只实现它**，不重新裁决。

为什么要有这张表（而不是继续把「目标函数」写在散文里）：`01-大方向.md` §0 的派生义务
要求「每份档案的目标函数显式、可审、可测」，而**原版没有可抄的效用表** ——
编一个 0–100 的「在乎程度」就是发明数字（违反 P10）。本表把「在乎」拆成两件可查的事：
**档位**（这项对这份国家有没有账：0 留空 / 1 叙述 / 2 具名事实 / 3 判据或字段）
+ **幅度**（只在原版同族阶梯或本仓实测处写）。

实现纪律（四条，都来自实测教训）：

1. **逐份 `try/except`**：`modgen.load_all` 在任一档案缺必填段时 `raise DataError`，
   整批退出会拿不到另外 8 份的红绿 ⇒ 本模块**自己逐文件读**，坏的那份标红后继续；
2. **不许静默 0**：`[objectives]` 命中 0 条时退出码必须是 **2**（判不了），不是 0（全绿）——
   这两件事在退出码上必须分得开，否则「表还没落地」会看起来像「表全过」；
3. **两态 `evidence`**：形态①（`带子路径的文件:行`）复用 :mod:`pdx.citations`；
   形态②（`别名:行`）由本模块展开 —— `CITATION_RE` 要求文件名带后缀，
   `01a:269` 这类简称在它那里**恒定 0 命中**，所以别名分支不是"另一套解析"，是唯一能判它的路；
4. **`kind` 由规则算出**（§4.1.1 的 `derive()`）：`pushed` / `declared` / `opening_card` /
   `measured_true` / `underivable` 五个值都是算出来的，落盘的值与算出来的不一致就是红。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pdx import citations, config, doc_tables
from pdx.cache import parse_cached
from pdx.model import Block

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

# ── 值域（口径页 §2.1）────────────────────────────────────────

#: 五个利益项：一条不许少（口径页 §2.1 硬约束 1）。
ITEM_KEYS: tuple[str, ...] = ("survival", "finance", "legitimacy", "military", "market")

#: 身份项取值域（§2.1）。
IDENTITY_KEYS: tuple[str, ...] = ("mission", "ideology", "prestige")

#: 约束集取值域（§2.1）。
CONSTRAINT_KEYS: tuple[str, ...] = ("endowment", "position", "friction", "external", "player")

#: `verdict.kind` 的取值域（§4.1 P4 / §4.1.1）—— **由 `derive()` 算出**，不是人挑的。
KINDS: tuple[str, ...] = ("pushed", "declared", "opening_card", "measured_true", "underivable")

#: `measured_true` / `underivable` 必须给 `verdict.evidence`（读数行 / §K 待校准行）。
KINDS_NEED_EVIDENCE: frozenset[str] = frozenset({"measured_true", "underivable"})

#: 中文显示名（渲染用；键仍是英文，判据只认键）。
DISPLAY: dict[str, str] = {
    "survival": "存续",
    "finance": "财政",
    "legitimacy": "合法性",
    "military": "军力",
    "market": "市场依赖",
    "mission": "使命",
    "ideology": "意识形态",
    "prestige": "威望",
    "endowment": "禀赋",
    "position": "位置",
    "friction": "摩擦",
    "external": "外部结构",
    "player": "玩家",
}

#: 文档别名表（写死；口径页 §2.1）。别名必须全 ASCII，且必须是这张表里的键。
ALIASES: dict[str, str] = {
    "01": "docs/design/01-大方向.md",
    "01a": "docs/design/01a-依据与参考.md",
    "backlog": "docs/design/backlog.md",
    "v1": "docs/design/exec/阶段5-9国目标函数表.md",
    "t9": "docs/design/exec/阶段5-目标牌口径.md",
    "t16": "docs/design/exec/档案目标牌-实机读数.md",
    "批1": "docs/design/exec/阶段5-批次1-结果.md",
    "批2": "docs/design/exec/阶段5-批次2-结果.md",
    "批3": "docs/design/exec/阶段5-批次3-结果.md",
    "复核41": "docs/reports/目标函数表口径-独立复核.md",
}

#: 档 3 的合法面之一：原版策略文件（口径页 §2.2）。
STRATEGY_PREFIX = "common/ai_strategies/"

#: 档 1 的别名必须映射到设计文档（`docs/**`）。
DOCS_PREFIX = "docs/"

#: 政治槽的等效竞争权重 `S`（口径页 §3.4；实测值在 `src/pdx/modguard.py:51`）。
POLITICAL_SLOT_S = 33.0

#: 渲染表（口径页 §2.3）的表头前缀 —— 那一行以它开头（`doc_tables` 按前缀定位）。
TABLE_HEADER = "| 档案 | 国 | 存续 | 财政 | 合法性 |"

#: 渲染表的宿主页（§2.3 那张表就在这一页上）。
TABLE_DOC = config.REPO / "docs" / "design" / "exec" / "阶段5-目标函数表-口径.md"

#: 数据源目录（只认**根下** `*.toml`：口径页 §2.1 反例①把递归扫描判成更坏的静默失败路径）。
DATA_DIR = config.REPO / "mod" / "data"

#: `mod/sitai_<id>.md` 产物目录。
PRODUCT_DIR = config.REPO / "mod" / "legacy"

#: `derive()` 的输入之一：原版开局牌所在文件（§4.1.1）。
STRATEGY_HISTORY = ("common", "history", "ai", "00_strategy.txt")


# ── 数据模型（口径页 §2.1 的四个子段）────────────────────────


@dataclass(frozen=True, slots=True)
class Row:
    """一格：`key` / `tier` / `evidence` / `why`（口径页 §2.1 的四个字段）。

    ``ordinal`` 是它在**同一子段里的第几条**（1 起数）—— 用来把红点定位到
    `mod/data/<id>.toml` 的第几个 `[[objectives.<子段>]]` 块上：TOML 解析器不给行号，
    而"第几个块"是稳定锚（行号会随别处编辑漂，块序不会）。
    """

    section: str
    ordinal: int
    key: str
    tier: int
    evidence: str
    why: str

    @property
    def label(self) -> str:
        return f"{self.section}[{self.ordinal}] {self.key or '（缺 key）'}"


@dataclass(frozen=True, slots=True)
class Verdict:
    """`[objectives.verdict]`（§2.1）。"""

    kind: str
    card: str
    evidence: str
    why: str


@dataclass(frozen=True, slots=True)
class Objectives:
    """一份档案的 `[objectives]` 节。"""

    why: str
    items: tuple[Row, ...]
    identity: tuple[Row, ...]
    constraints: tuple[Row, ...]
    verdict: Verdict | None

    @property
    def rows(self) -> tuple[Row, ...]:
        return (*self.items, *self.identity, *self.constraints)


@dataclass(frozen=True, slots=True)
class Entry:
    """一份数据源 + 它的 `[objectives]`（缺节时 ``objectives is None``）。"""

    path: Path
    id: str
    country: str
    reform_card: str
    pushed: str
    political_weight: float
    objectives: Objectives | None
    text: str

    @property
    def rel(self) -> str:
        return f"mod/data/{self.path.name}"

    @property
    def product(self) -> Path:
        return PRODUCT_DIR / f"sitai_{self.id}.md"


# ── 读盘（逐文件，不借 `load_all`）──────────────────────────


def data_files(data_dir: Path | None = None) -> tuple[Path, ...]:
    """`mod/data` **根下**的 `*.toml`，按文件名排序（= `load_all` 的文件序）。"""
    root = data_dir or DATA_DIR
    return tuple(sorted(root.glob("*.toml")))


#: `mod/data/` 下允许存在、但**不是**数据源的文件（今天为空）。
#:
#: ⚠️ 往这里加东西要写理由：口径页 §1 的裁决是「扫到就报」，不是「按白名单放行」——
#: 那三种静默写法之所以危险，正因为它们**看着像数据源、而谁都读不到**。
STRAY_ALLOWED: frozenset[str] = frozenset()


def _stray_kind(path: Path, root: Path) -> str:
    """这条「多出来的文件」属于口径页 §1 的哪一种静默写法（用来在报错里指名）。"""
    name = path.name.lower()
    if name.endswith(".toml"):
        if len(path.relative_to(root).parts) > 1:
            return "子目录里的 `.toml`（`glob` 非递归；引擎也不枚举子目录）"
        return "文件名大小写不同的 `.toml`（Windows 的 `glob` 认它、Linux 不认）"
    if ".toml." in name:
        return "以 `.toml` 开头但不是 `.toml` 结尾（`.bak` / `.notes` 那一族）"
    return "扩展名不是 `.toml`（换扩展名那一族）"


def stray_files(data_dir: Path | None = None) -> tuple[Path, ...]:
    """`mod/data/` 下**不会被读到**的文件 —— 口径页 §1 的三种静默写法一起判。

    三条判据（口径页 §1:65-69 的原文要求，缺一条就有一种写法能溜过去）：

    * **递归**：走 `mod/data/**/*` —— 子目录里的 `*.toml` **既**不会被 :func:`data_files`
      （非递归 `glob`）读到，**也**不会被引擎读到（引擎不枚举子目录）；
    * **后缀规范化**：比对前把名字折成小写，`.TOML` 与 `.toml` 算同一个后缀
      （Windows 的 `glob` 大小写不敏感、Linux 敏感 ⇒ 同一棵树在两种平台上档案数不同）；
    * **绕过列举**：不去和 `data_files()` 求差集了事，而是把**整棵树**列出来逐个核 ——
      `x.toml.bak` / `x.toml.notes` / `other.yaml` 这些名字压根不在 `*.toml` 这个模式里，
      靠「多出来的倍数」永远看不见它们（这正是「比第 10 份档案更坏」的那一类）。

    **只读**：扫到只报，不搬、不改、不删（改文件不是闸门的事）。
    """
    root = data_dir or DATA_DIR
    if not root.is_dir():
        return ()
    known = {path.resolve() for path in data_files(root)}
    return tuple(
        path
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.resolve() not in known
        and path.relative_to(root).as_posix() not in STRAY_ALLOWED
    )


def _table(raw: object) -> Mapping[str, object]:
    return raw if isinstance(raw, dict) else {}


def _seq(raw: object) -> list[object]:
    return list(raw) if isinstance(raw, list) else []


def _text(item: Mapping[str, object], key: str) -> str:
    value = item.get(key)
    if isinstance(value, str):
        return value.strip()
    return "" if value is None else str(value).strip()


def _rows(section: str, raw: object) -> tuple[Row, ...]:
    out: list[Row] = []
    for ordinal, item in enumerate(_seq(raw), start=1):
        table = _table(item)
        tier_raw = table.get("tier")
        tier = tier_raw if isinstance(tier_raw, int) and not isinstance(tier_raw, bool) else -1
        out.append(
            Row(
                section=section,
                ordinal=ordinal,
                key=_text(table, "key"),
                tier=tier,
                evidence=_text(table, "evidence"),
                why=_text(table, "why"),
            )
        )
    return tuple(out)


def _objectives(raw: Mapping[str, object]) -> Objectives | None:
    section = raw.get("objectives")
    if not isinstance(section, dict):
        return None
    verdict_raw = section.get("verdict")
    verdict = None
    if isinstance(verdict_raw, dict):
        verdict = Verdict(
            kind=_text(verdict_raw, "kind"),
            card=_text(verdict_raw, "card"),
            evidence=_text(verdict_raw, "evidence"),
            why=_text(verdict_raw, "why"),
        )
    return Objectives(
        why=_text(section, "why"),
        items=_rows("items", section.get("items")),
        identity=_rows("identity", section.get("identity")),
        constraints=_rows("constraints", section.get("constraints")),
        verdict=verdict,
    )


def _first_arg(raw: object) -> str:
    """`[[journal_entry.signals.set_strategy]]` 的第一条 `arg`（§4.1.1 的 `pushed`）。"""
    for item in _seq(raw):
        arg = _text(_table(item), "arg")
        if arg:
            return arg
    return ""


def _political_weight(raw: Mapping[str, object]) -> float:
    """本档案 `[cards]` 里政治槽的权重和（渲染表的**代价列**；§2.3、§3.4）。"""
    total = 0.0
    for item in _seq(_table(raw.get("cards")).get("items")):
        table = _table(item)
        if _text(table, "slot") != "political":
            continue
        amount = _table(table.get("weight")).get("amount")
        if isinstance(amount, (int, float)) and not isinstance(amount, bool):
            total += float(amount)
    return total


def cost_percent(weight: float) -> str:
    """代价列 = `W/(W+S)`（**现算**，表里不存这个数：§3.4）。"""
    return f"{100.0 * weight / (weight + POLITICAL_SLOT_S):.1f}%"


def load(path: Path) -> Entry:
    """读一份数据源（**只读**；坏文件由调用方 `try/except`）。"""
    text = path.read_text(encoding="utf-8")
    raw = tomllib.loads(text)
    archive = _table(raw.get("archive"))
    signals = _table(_table(raw.get("journal_entry")).get("signals"))
    return Entry(
        path=path,
        id=_text(archive, "id") or path.stem,
        country=_text(archive, "country"),
        reform_card=_text(_table(raw.get("probe")), "reform_card"),
        pushed=_first_arg(signals.get("set_strategy")),
        political_weight=_political_weight(raw),
        objectives=_objectives(raw),
        text=text,
    )


#: `entry_for` 的进程内缓存（`modgen.doc_text` 每份档案都会来取一次）。
_ENTRY_CACHE: dict[str, Entry] = {}


def entry_for(archive_id: str, data_dir: Path | None = None) -> Entry | None:
    """按档案 id 取那一份（渲染产物小节用；找不到返回 ``None``，**不抛**）。"""
    cached = _ENTRY_CACHE.get(archive_id)
    if cached is not None:
        return cached
    for path in data_files(data_dir):
        try:
            entry = load(path)
        except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
            continue
        if entry.id == archive_id:
            _ENTRY_CACHE[archive_id] = entry
            return entry
    return None


def load_all(data_dir: Path | None = None) -> tuple[list[Entry], list[tuple[str, str]]]:
    """逐份读；返回 ``(读成功的, [(文件名, 异常说明), …])`` —— **绝不整批崩**。"""
    entries: list[Entry] = []
    broken: list[tuple[str, str]] = []
    for path in data_files(data_dir):
        try:
            entries.append(load(path))
        except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
            broken.append((path.name, f"{type(exc).__name__}: {exc}"))
    return entries, broken


# ── `evidence` 两态（§2.1）──────────────────────────────────


@dataclass(frozen=True, slots=True)
class Form:
    """`evidence` 解析结果。``kind``：``file``（形态①）/ ``alias``（形态②）/ ``none``。"""

    kind: str
    name: str = ""
    start: int = 0
    end: int = 0
    detail: str = ""


def _alias_rel(name: str) -> str | None:
    return ALIASES.get(name)


def _alias_path(name: str) -> Path | None:
    rel = _alias_rel(name)
    return None if rel is None else config.REPO / rel


def classify(evidence: str) -> Form:
    """判 `evidence` 属于哪一态（**恰好一条引用**是硬约束 2：不是布尔）。

    形态①先走 :mod:`pdx.citations` 的正则（它会给出"命中几条"）；命中 0 条时再试别名分支 ——
    `01a:269` 这类简称在 `CITATION_RE` 里恒 0 命中（正则的字符类不含中文），这是**设计**。
    """
    value = evidence.strip()
    if not value:
        return Form("none", detail="空")
    found = citations.scan_text(value, where="[objectives].evidence", root=config.GAME)
    if len(found) == 1:
        item = found[0]
        return Form("file", name=item.file, start=item.start, end=item.end, detail=item.status)
    if len(found) > 1:
        return Form("file", detail=f"一个字段里有 {len(found)} 条引用（要求恰好 1 条）")
    name, sep, span = value.rpartition(":")
    if not sep or not name:
        return Form("none", detail="既不是 `文件:行` 也不是 `别名:行`")
    start_s, _, end_s = span.partition("-")
    if not start_s.isdigit() or (end_s and not end_s.isdigit()):
        return Form("none", detail=f"行号不是数字：{span!r}")
    if _alias_path(name) is None:
        return Form("none", detail=f"别名 {name!r} 不在别名表里（也不是带后缀的文件引用）")
    return Form("alias", name=name, start=int(start_s), end=int(end_s) if end_s else int(start_s))


def _lines_of(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def line_text(form: Form) -> str:
    """引用指向的那一行原文（`derive()` 的 `reading_text`；§4.1.2 ①′）。"""
    if form.kind == "alias":
        path = _alias_path(form.name)
    elif form.kind == "file":
        path, status, _detail = citations._resolve(form.name, root=config.GAME)
        if path is None or status != "ok":
            return ""
    else:
        return ""
    if path is None or not path.is_file():
        return ""
    lines = _lines_of(path)
    return lines[form.start - 1] if 0 < form.start <= len(lines) else ""


# ── P4 的 `derive()`（§4.1.1；**规则算出，不由人挑**）────────


@dataclass(frozen=True, slots=True)
class Inputs:
    """`derive()` 的四个输入（口径页 §4.1.1 逐字）。"""

    rc: str
    pushed: str
    opening: str
    reading_text: str


_CARD_TYPES: dict[str, str] = {}


def _scalar(node: object) -> str:
    return "" if isinstance(node, Block) else str(getattr(node, "text", "")).strip()


def card_type(name: str, *, game: Path | None = None) -> str:
    """`common/ai_strategies/*.txt` 里那张牌的 `type`（找不到返回空串；进程内记忆）。

    ⚠️ 牌块的**键就是全名**（`ai_strategy_tanzimat_reforms = { … }`）—— 先按全名找，
    找不到再退到去掉前缀的短名（某些版本两种写法都出现过，不退这一档会静默读空）。
    """
    if name in _CARD_TYPES:
        return _CARD_TYPES[name]
    root = (game or config.GAME) / "common" / "ai_strategies"
    found = ""
    if root.is_dir():
        for path in sorted(root.rglob("*.txt")):
            block = _find_block(path, name) or _find_block(path, name.removeprefix("ai_strategy_"))
            if block is None:
                continue
            for inner in block.assignments():
                if inner.key == "type":
                    found = _scalar(inner.value)
                    break
            if found:
                break
    _CARD_TYPES[name] = found
    return found


def _find_block(path: Path, key: str) -> Block | None:
    """在脚本文件里按名字找 `key = { … }` 的块 —— **任意深度**（找不到返回 ``None``）。

    为什么不能只看顶层：`common/history/ai/00_strategy.txt` 整份文件包在一个
    `AI = { … }` 块里（实测：它唯一的顶层键就是 `AI`），`c:TUR` 那一族在它**里面**。
    这一类"外面还套一层"的写法在原版很常见（`common/ai_strategies/**` 则多为平铺）。
    """
    try:
        root = parse_cached(path).root
    except (OSError, ValueError):  # pragma: no cover - 文件读不了按"找不到"处理
        return None
    stack = [root]
    while stack:
        block = stack.pop()
        for item in block.assignments():
            if not isinstance(item.value, Block):
                continue
            if item.key == key:
                return item.value
            stack.append(item.value)
    return None


def opening_card(entry: Entry, *, game: Path | None = None) -> str:
    """原版 `00_strategy.txt` 里该国 **政治** 开局牌（没有该块就是空；§4.1.1）。

    为什么不能只取第一个 `set_strategy`：同一个 `c:<TAG>` 块会同时设行政 / 政治 / 外交
    三张牌（`c:BRZ` 块就是三张），而 §4.1.1 要的是**政治**那一张 ——
    所以拿牌名回 `common/ai_strategies/*.txt` 查它的 `type = political`。
    """
    if not entry.country:
        return ""
    base = game or config.GAME
    block = _find_block(base.joinpath(*STRATEGY_HISTORY), f"c:{entry.country}")
    if block is None:
        return ""
    names = [_scalar(inner.value) for inner in block.assignments() if inner.key == "set_strategy"]
    names = [name for name in names if name]
    for name in names:
        if card_type(name, game=game) == "political":
            return name
    return names[0] if names else ""


def raw_inputs(entry: Entry, *, game: Path | None = None) -> Inputs:
    """从盘上取 `derive()` 的四个输入（`reading_text` = `verdict.evidence` 指的那一行）。"""
    verdict = entry.objectives.verdict if entry.objectives is not None else None
    reading = ""
    if verdict is not None and verdict.evidence:
        reading = line_text(classify(verdict.evidence))
    return Inputs(
        rc=entry.reform_card,
        pushed=entry.pushed,
        opening=opening_card(entry, game=game),
        reading_text=reading,
    )


def derive(entry: Entry, *, inputs: Inputs | None = None) -> str:
    """按 §4.1.1 的三条规则算 `kind`；**全不成立返回空串**（= 红）。"""
    data = inputs or raw_inputs(entry)
    if data.rc:
        return "pushed" if data.pushed == data.rc else "declared"
    verdict = entry.objectives.verdict if entry.objectives is not None else None
    card = verdict.card if verdict is not None else ""
    short = card.removeprefix("ai_strategy_")
    if card and data.opening == card:
        return "opening_card"
    if card and not data.opening and (card in data.reading_text or short in data.reading_text):
        return "measured_true"
    if not card and not data.opening and "待校准" in data.reading_text:
        return "underivable"
    return ""


# ── 五条闸门（§4.1）────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Problem:
    """一条红。``where`` 是"第几个块 / 哪个字段"，不是行号（行号会漂，块序不会）。"""

    predicate: str
    where: str
    detail: str


@dataclass(frozen=True, slots=True)
class EntryReport:
    """一份档案的红绿。"""

    id: str
    rel: str
    problems: tuple[Problem, ...]
    kind: str = ""

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass(frozen=True, slots=True)
class Report:
    """整批结论（退出码三档见 §4.1.2 ①）。"""

    entries: tuple[EntryReport, ...]
    broken: tuple[tuple[str, str], ...]
    prerequisites: tuple[str, ...]

    @property
    def counts(self) -> dict[str, int]:
        out = {f"P{n}": 0 for n in range(1, 6)}
        for entry in self.entries:
            for problem in entry.problems:
                out[problem.predicate] = out.get(problem.predicate, 0) + 1
        return out

    @property
    def reds(self) -> int:
        return sum(len(entry.problems) for entry in self.entries) + len(self.broken)

    def exit_code(self) -> int:
        """0 = 全过；1 = 判据红；2 = 前置缺失 ⇒ **判不了**（§4.1.2 ①）。"""
        if self.prerequisites or self.broken:
            return 2
        return 1 if self.reds else 0

    def summary(self) -> str:
        counts = self.counts
        head = " · ".join(f"{name} 红 {counts[name]}" for name in sorted(counts))
        return f"{head} · 总红 {self.reds} · 退出码 {self.exit_code()}"


def _expect_keys(
    rows: Sequence[Row],
    allowed: Sequence[str],
    section: str,
    out: list[Problem],
    *,
    exact: bool = False,
) -> None:
    """键的合法性。``exact=True`` 只给 `items` 用：五个利益项**一条不许少**（§2.1）。

    ⚠️ `identity` / `constraints` **不查重复**：口径页 §2.1 只规定「≥1 / ≥3」与取值域，
    而 §3.3 的「摩擦」一类本来就可以有多条来源（本国历史文件 + 本档案的 IG 字段）。
    比口径更严会把合法填法判红 —— 「判据比引擎严比漏判更坏」是本仓的既有纪律。
    """
    seen: list[str] = []
    for row in rows:
        if not row.key:
            out.append(Problem("P1", row.label, f"{section} 缺 `key`"))
            continue
        if row.key not in allowed:
            out.append(Problem("P1", row.label, f"`{row.key}` 不在值域 {{{' | '.join(allowed)}}}"))
        if exact and row.key in seen:
            out.append(Problem("P1", row.label, f"`{row.key}` 重复"))
        seen.append(row.key)
    if exact:
        missing = [key for key in allowed if key not in seen]
        if missing:
            out.append(Problem("P1", section, f"少 {' / '.join(missing)} —— 五个利益项一条不许少"))


def _tier_kind_ok(row: Row, form: Form, entry: Entry) -> str:
    """档位与依据**种类**是否一致（§2.2 的边界判据）；不一致时返回一句说明。

    ⚠️ 档位由「依据的种类」决定，**不由路径前缀决定**（§2.2 档 3 子规则 (a)）——
    但对机器判据来说，种类就是由路径类别与形态表达出来的，所以这里按路径类别判。
    """
    if row.tier == 1:
        if form.kind != "alias":
            return "档 1（叙述）的依据必须是形态②（别名 → `docs/**`）"
        return ""
    if row.tier == 2:
        if form.kind != "file":
            return "档 2（具名事实）的依据必须是形态①（原版文件:行）"
        if form.name.startswith(STRATEGY_PREFIX):
            return "档 2 不能拿 `common/ai_strategies/**` 当依据（那是判据 ⇒ 档 3）"
        return "" if form.name.startswith("common/") else "档 2 的依据应落在原版 `common/**`"
    if row.tier == 3:
        if form.kind == "alias":
            return ""
        if form.name.startswith(STRATEGY_PREFIX):
            return ""
        if form.name == entry.rel:
            return ""
        return "档 3（判据或字段）的依据只能是 `common/ai_strategies/**` 或本档案自身"
    return ""


def _source_owner(entry: Entry) -> str:
    """引用方（`--check` 报红时要说清是谁写的这一条）。"""
    return f"{entry.rel} 的 `[objectives]`"


def check_entry(entry: Entry, *, problems: list[Problem], prereq: list[str]) -> None:
    """一份档案的 P1–P4（P5 是产物与宿主页对表，另行判）。"""
    obj = entry.objectives
    if obj is None:
        problems.append(Problem("P1", "`[objectives]`", "缺这一节"))
        prereq.append(f"{entry.id}：缺 `[objectives]` 节（先补数据源再判）")
        return

    # P1 存在性与形状
    if len(obj.items) != 5:
        problems.append(Problem("P1", "items", f"必须恰好 5 条，实际 {len(obj.items)} 条"))
    _expect_keys(obj.items, ITEM_KEYS, "items", problems, exact=True)
    if not obj.identity:
        problems.append(Problem("P1", "identity", "至少 1 条，实际 0 条"))
    _expect_keys(obj.identity, IDENTITY_KEYS, "identity", problems)
    if len(obj.constraints) < 3:
        problems.append(Problem("P1", "constraints", f"至少 3 条，实际 {len(obj.constraints)} 条"))
    _expect_keys(obj.constraints, CONSTRAINT_KEYS, "constraints", problems)
    if obj.verdict is None:
        problems.append(Problem("P1", "verdict", "缺这一子段"))
    elif obj.verdict.kind not in KINDS:
        problems.append(
            Problem("P1", "verdict.kind", f"`{obj.verdict.kind}` 不在值域 {{{' | '.join(KINDS)}}}")
        )

    # P2 档位合法（含「档 0 必须写明缺什么」这条唯一权威定义）
    if not obj.why:
        problems.append(Problem("P2", "`[objectives].why`", "空（P10：每个决定都要有依据）"))
    for row in obj.rows:
        if not row.why:
            problems.append(Problem("P2", row.label, "空 `why`（P10）"))
        if row.tier not in (0, 1, 2, 3):
            problems.append(Problem("P2", row.label, f"`tier = {row.tier}` 不在值域 {{0,1,2,3}}"))
            continue
        if row.tier == 0:
            if row.evidence:
                problems.append(
                    Problem("P2", row.label, f"档 0（留空）不许有依据，却有 `{row.evidence}`")
                )
            if "缺" not in row.why:
                problems.append(
                    Problem("P2", row.label, "档 0 的 `why` 里必须写明缺什么（含「缺」）")
                )
            continue
        if not row.evidence:
            problems.append(Problem("P2", row.label, f"档 {row.tier} 必须有 `evidence`"))
            continue
        form = classify(row.evidence)
        if form.kind == "none":
            problems.append(Problem("P2", row.label, f"`evidence` 形态非法：{form.detail}"))
            continue
        bad = _tier_kind_ok(row, form, entry)
        if bad:
            problems.append(Problem("P2", row.label, bad))

    # P3 引用可解
    support = _support()
    for row in (*obj.rows, *_verdict_rows(obj)):
        if not row.evidence:
            continue
        form = classify(row.evidence)
        if form.kind == "none":
            problems.append(Problem("P3", row.label, f"`{row.evidence}` 解析不了：{form.detail}"))
            continue
        if form.kind == "alias":
            path = _alias_path(form.name)
            if path is None or not path.is_file():
                problems.append(
                    Problem(
                        "P3",
                        row.label,
                        f"别名 `{form.name}` 指向的文件不存在：{_alias_rel(form.name)}",
                    )
                )
                continue
            total = len(_lines_of(path))
            if form.start > total or form.end > total:
                problems.append(
                    Problem(
                        "P3",
                        row.label,
                        f"别名 `{form.name}` 引到第 {form.start} 行，文件只有 {total} 行",
                    )
                )
            continue
        found = citations.scan_text(row.evidence, where=_source_owner(entry), root=config.GAME)
        if len(found) != 1:
            problems.append(
                Problem("P3", row.label, f"`evidence` 里必须恰好 1 条引用，实际 {len(found)} 条")
            )
            continue
        if not found[0].ok:
            # `missing` / `ambiguous` / `out_of_range` = **引用写错**（P3 红，退出码 1）。
            # ⚠️ 它**不是**"支撑域过期"：两者在 §4.1.2 ①′ 里退出码都可能非零，
            # 必须读结论才分得开 —— 这里按结论分流，不把写错的引用算成 rc 2。
            problems.append(
                Problem("P3", row.label, f"`{row.evidence}` {found[0].status}：{found[0].detail}")
            )
            continue
        stale = citations.unsupported(found, support, live=True)
        for item, reason in stale:
            # 解析得开、但与**入库支撑域**对不上 ⇒ 前置缺失（rc 2，§4.1.2 ①）：
            # 先跑 `v3 snapshot create --compact` 再判，别把它当"表填错了"。
            problems.append(
                Problem("P3", row.label, f"{entry.id}：`{item.file}:{item.start}` {reason}")
            )
            prereq.append(
                f"{entry.id}：支撑域过期 ⇒ 先跑 `v3 snapshot create --compact`（{reason}）"
            )

    # P4 裁定自洽
    if obj.verdict is not None:
        expected = derive(entry)
        if expected != obj.verdict.kind:
            problems.append(
                Problem(
                    "P4",
                    "verdict.kind",
                    f"落盘 `{obj.verdict.kind or '（空）'}` ≠ `derive()` 算出的 `{expected or '（无规则成立）'}`",
                )
            )
        card = obj.verdict.card
        kind = obj.verdict.kind
        if not obj.verdict.why:
            problems.append(Problem("P4", "verdict.why", "空 `why`（P10）"))
        if kind == "underivable" and card:
            problems.append(Problem("P4", "verdict.card", "`underivable` 必须留空 `card`"))
        if kind and kind != "underivable" and not card:
            problems.append(Problem("P4", "verdict.card", f"`{kind}` 必须给 `card`"))
        if (
            kind in {"pushed", "declared"}
            and card
            and entry.reform_card
            and card != entry.reform_card
        ):
            problems.append(
                Problem("P4", "verdict.card", f"`{kind}` 的 `card` 必须等于 `[probe].reform_card`")
            )
        if kind in KINDS_NEED_EVIDENCE and not obj.verdict.evidence:
            problems.append(Problem("P4", "verdict.evidence", f"`{kind}` 必须给读数行"))
        if kind == "opening_card" and entry.reform_card:
            problems.append(
                Problem("P4", "verdict.kind", "`[probe].reform_card` 非空 ⇒ 应是 pushed/declared")
            )


def _verdict_rows(obj: Objectives) -> tuple[Row, ...]:
    """把 `verdict.evidence` 也过一遍 P3（它一样有引用要解得开）。"""
    if obj.verdict is None or not obj.verdict.evidence:
        return ()
    return (
        Row(
            section="verdict",
            ordinal=1,
            key=obj.verdict.kind,
            tier=1,
            evidence=obj.verdict.evidence,
            why=obj.verdict.why,
        ),
    )


def _support() -> dict[str, list[str]]:
    """入库支撑域（判 `unsupported` 用；没有快照就是空域 ⇒ 新加的引用会报出来）。"""
    from pdx import verify  # noqa: PLC0415 - 只有这条检查要拉快照那套

    snap = verify.latest_compact_snapshot()
    return dict((snap.sections.get(citations.SECTION) or {}) if snap is not None else {})


def check_p5(entries: Sequence[Entry], *, page: Path | None = None) -> list[Problem]:
    """P5 渲染一致：`mod/sitai_<id>.md` 的目标函数小节 + 宿主页 §2.3 的那张表。"""
    out: list[Problem] = []
    for entry in entries:
        if entry.objectives is None:
            continue
        expected = "\n".join(section_lines(entry))
        try:
            body = entry.product.read_text(encoding="utf-8")
        except OSError:
            out.append(
                Problem("P5", entry.id, f"产物缺 {entry.product.name}（跑 `v3 modgen --write`）")
            )
            continue
        if expected not in body:
            out.append(
                Problem("P5", entry.id, f"{entry.product.name} 的「目标函数」小节与数据源不一致")
            )
    doc = page or TABLE_DOC
    spec = doc_table_specs()[0]
    try:
        current = doc_tables.current_rows(doc, spec)
    except (doc_tables.TableNotFoundError, doc_tables.TableMalformedError, OSError) as exc:
        out.append(Problem("P5", doc.name, f"找不到由工具生成的表：{exc}"))
        return out
    expected_rows = spec.rows()
    if [doc_tables.split_row(row) for row in current] != [
        doc_tables.split_row(row) for row in expected_rows
    ]:
        out.append(
            Problem(
                "P5",
                doc.name,
                f"§2.3 的表与生成结果不一致（文档 {len(current)} 行 / 生成 {len(expected_rows)} 行）"
                " —— 跑 `v3 tables --write`",
            )
        )
    return out


def check(data_dir: Path | None = None, *, page: Path | None = None) -> Report:
    """跑完 P1–P5，返回整批结论（退出码见 :meth:`Report.exit_code`）。"""
    entries, broken = load_all(data_dir)
    problems: list[Problem] = []
    prereq: list[str] = []
    reports: list[EntryReport] = []
    if len(entries) + len(broken) != 9:
        prereq.append(
            f"档案数 = {len(entries) + len(broken)}（应 9）—— `mod/data/` 根下的 `*.toml` 少了或多了"
        )
    for name, detail in broken:
        problems.append(Problem("P1", name, f"读不了：{detail}"))
    for entry in entries:
        mine: list[Problem] = []
        check_entry(entry, problems=mine, prereq=prereq)
        reports.append(
            EntryReport(
                id=entry.id,
                rel=entry.rel,
                problems=tuple(mine),
                kind=(
                    entry.objectives.verdict.kind
                    if entry.objectives and entry.objectives.verdict
                    else ""
                ),
            )
        )
    # 文件面（口径页 §1 的三种静默写法）：**逐份判完再扫整棵树**。
    #
    # 为什么单列一次扫描、而不并进上面那个 `!= 9` 的计数守卫：那一条只能看见
    # 「根下多了一个 `*.toml`」（`load_all` 会自己报错），而这里三类**一个都不会**让它变数 ——
    # 子目录、`.bak`/`.notes`、换扩展名都落在 `glob("*.toml")` 的模式之外，
    # 于是"数据看着在、其实没人读"，引擎与生成器两侧都不出声。
    for stray in stray_files(data_dir):
        root = data_dir or DATA_DIR
        relative = stray.relative_to(root).as_posix()
        reports.append(
            EntryReport(
                id=relative,
                rel=f"mod/data/{relative}",
                problems=(
                    Problem(
                        "P1",
                        "mod/data 的文件面（口径页 §1 的三种静默写法）",
                        f"`{relative}` 既不会被 `data_files()` 读到、也不会被引擎读到 —— "
                        f"{_stray_kind(stray, root)}。"
                        "它不会让「档案数」变成 10（那个由档案数守卫报），"
                        "属于「数据看着在、其实没人读」的那一类，必须当场指名。",
                    ),
                ),
            )
        )
    p5 = check_p5(entries, page=page)
    if p5:
        extra: dict[str, list[Problem]] = {}
        for problem in p5:
            extra.setdefault(problem.where, []).append(problem)
        reports = [
            EntryReport(
                id=report.id,
                rel=report.rel,
                problems=(*report.problems, *extra.pop(report.id, [])),
                kind=report.kind,
            )
            for report in reports
        ]
        reports.extend(
            EntryReport(id=key, rel=key, problems=tuple(items)) for key, items in extra.items()
        )
    return Report(entries=tuple(reports), broken=tuple(broken), prerequisites=tuple(prereq))


# ── 渲染（产物小节 + §2.3 的表）──────────────────────────────


def _cell(row: Row) -> str:
    if row.tier == 0:
        return "0 · 缺"
    return f"{row.tier} · `{row.evidence}`"


def section_lines(entry: Entry) -> list[str]:
    """`mod/sitai_<id>.md` 里的「目标函数」小节（人读的那一页）。"""
    obj = entry.objectives
    if obj is None:
        return ["## 目标函数（9 国目标函数表 · I7）", "", "> ⚠️ 数据源缺 `[objectives]` 节。", ""]
    out = [
        "## 目标函数（9 国目标函数表 · I7）",
        "",
        "| 项 | 档 | 依据 | 为什么 |",
        "|---|---|---|---|",
    ]
    out.extend(
        f"| {DISPLAY.get(row.key, row.key)} | {_cell(row)} | {row.why} |" for row in obj.items
    )
    out.extend(f"| 身份项 · `{row.key}` | {_cell(row)} | {row.why} |" for row in obj.identity)
    out.extend(f"| 约束集 · `{row.key}` | {_cell(row)} | {row.why} |" for row in obj.constraints)
    out.append("")
    verdict = obj.verdict
    if verdict is not None:
        label = f"`{verdict.kind}`"
        if verdict.card:
            label += f" · `{verdict.card}`"
        out.append(f"**裁定**：{label} —— {verdict.why}")
    out.append(
        f"**代价**：政治槽 `{int(entry.political_weight) if entry.political_weight else 0}/"
        f"({int(entry.political_weight) if entry.political_weight else 0} + {int(POLITICAL_SLOT_S)})`"
        f" = **{cost_percent(entry.political_weight)}**（现算；预算 `[0.3, 0.6]` 见闸门 ③）"
    )
    out.append("")
    return out


def table_rows() -> list[str]:
    """口径页 §2.3 那张表的 9 个数据行（11 个内容列；顺序 = `load_all` 文件序）。"""
    entries, _broken = load_all()
    rows: list[str] = []
    for entry in entries:
        obj = entry.objectives
        cells = [f"`{entry.id}`", f"`{entry.country}`"]
        if obj is None:
            cells.extend(["——"] * 5)
            identity = constraints = "——"
            verdict = "——"
        else:
            cells.extend(_cell(row) for row in obj.items)
            identity = " / ".join(f"`{row.key}` {row.tier}" for row in obj.identity)
            constraints = " / ".join(f"`{row.key}` {row.tier}" for row in obj.constraints)
            cell = "——" if obj.verdict is None else f"**`{obj.verdict.kind}`**"
            if obj.verdict is not None and obj.verdict.card:
                cell += f" · `{obj.verdict.card}`"
            verdict = cell
        cells.extend([identity, constraints, verdict, cost_percent(entry.political_weight)])
        rows.append("| " + " | ".join(cells) + " |")
    return rows


def doc_table_specs() -> tuple[doc_tables.TableSpec, ...]:
    """登记进 `docgen.targets()` 的那张表（口径页 §2.3）。"""
    return (doc_tables.TableSpec(name="阶段5 9国目标函数表", header=TABLE_HEADER, rows=table_rows),)
