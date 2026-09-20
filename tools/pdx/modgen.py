"""数据源 → mod 产物的生成器（阶段 3 并行轨的第一步）。

为什么要有它
------------
P3 说「引擎脚本由 Python 生成，人只改数据源」，F10 说「生成器优先、单一数据源」——
本模块就是这条纪律的落点：**`mod/` 下的脚本、本地化、档案文档全部由这里从
`mod/data/*.toml` 编译出来**，人只改 TOML。

它替掉的是"手写一版脚本 → 三个地方各写一遍数字 → 谁也不记得为什么是 20 不是 25"
这条路。手写的失效方式很安静：脚本里的 -20、本地化里的文案、文档里的说明
分别漂移，游戏照跑，只是行为与设计不一致。

口径（写清楚，免得以后各算各的）
--------------------------------
* **每张表都必须带非空 `why`** —— 不只是数字。空 `why` 当场报错（:class:`DataError`），
  这是 P10 从"纪律"变成"可执行检查"的那一步；
* **数字一律写成 `amount = N`**（同表内配 `why`）。缩写形式只有一种，于是
  :func:`why_report` 与闸门 ⑤ 能机械地枚举"每个数字 + 它的依据"；
* **产物路径 = 原版目录树的镜像**：`common/<原版目录>/sitai_*.txt` 与
  `localization/<语言>/sitai_*.yml`。F7 的「平铺不建子目录」指的是
  **每个原版目录下只放我们的文件、不再自建子目录**（自建子目录在 1.14.3 实测
  不被引擎枚举 —— 探针 `zz_probe_subdir_probe` 就是为这条留的证据）；
* **游戏侧文件一律写 UTF-8 BOM**（`encoding="utf-8-sig"`）：`common/` 下 3,026 个
  `.txt` 有 3,002 个带 BOM，`localization/` 的 `.yml` 同样带 —— 缺 BOM 的表现是
  "这份文件像没生效"，且只会写进 error.log（探针实测踩过）。`.md` 与 `.json`
  **不带** BOM：前者不是游戏侧文件，后者的读取方（启动器）按 JSON 解析。

产物清单（每份档案）
--------------------
===============================  ==========================================
``common/scripted_effects/``      冲击记账效果（变量 + 挂修正）
``common/static_modifiers/``      压力修正（真实的合法性/贵族/财政变化）
``common/static_modifiers/``      （可选）改革侧输入修正（`[reform_inputs]`，B2 处理段）
``common/journal_entries/``       改革窗口 JE（判据驱动）
``common/defines/``               节奏杠杆（按块 + 参数覆盖 ``NAI``）
``common/ai_strategies/``         递牌（本档案为空，F5）
``localization/<语言>/``          文案（中英）
``sitai_<id>.md``                 档案文档（每个数字与它的依据）
``.metadata/metadata.json``       启动器要的元数据（不带 BOM）
===============================  ==========================================

> **文档（`.md`）不在往返净度的范围内**：它是给人看的，由闸门 ⑤ 的可复现性守着。
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pdx import config
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

#: 数据源 schema 版本。不匹配就报错，不做兼容猜测（P13：不许静默降级）。
SCHEMA_VERSION = 1

#: 数据源目录（仓库根下）。
DATA_DIR = config.REPO / "mod" / "data"

#: 产物根（仓库根下）。**它就是 mod 根** —— 原版目录树的镜像。
PRODUCT_DIR = config.REPO / "mod"

#: 数据源扩展名。
DATA_SUFFIX = ".toml"

#: 我们自己的文件前缀（F7 命名空间）。
FILE_PREFIX = "sitai_"

#: 游戏侧文件（要写 BOM 的那些）。
GAME_SIDE_SUFFIXES = (".txt", ".yml")

#: 支持的语言：游戏目录名 → `.yml` 里的语言声明行。新增一种语言 = 这里加一行
#: + 数据源的每条本地化补一个同名字段（缺字段会报错，不会静默漏语言）。
LANGUAGES: dict[str, str] = {"english": "l_english", "simp_chinese": "l_simp_chinese"}

#: JE 的判据块顺序。**固定顺序**是确定性生成的一部分：数据源里换个书写次序
#: 不该让产物变样（否则"两次生成逐字节一致"会被无意义的编辑打破）。
GATE_ORDER = ("is_shown_when_inactive", "possible", "complete", "fail", "invalid")

#: 修正名的合法前缀（F7）：策略 `ai_strategy_sitai_*`、JE `je_sitai_*`、其余 `sitai_*`。
#:
#: 引擎认的是**它自己的**前缀（`je_` 让它找 journal_entries、`ai_strategy_` 让它
#: 找策略），所以 `sitai_` 只能排在后面 —— 于是判据写成"可选引擎前缀 + sitai_"，
#: 而不是"必须以 sitai_ 开头"。
NAMESPACE_PREFIX = "sitai_"

#: 命名空间的完整判据（见 :data:`NAMESPACE_PREFIX` 的注释）。
NAMESPACE_RE = re.compile(r"^(?:ai_strategy_|je_)?sitai_[a-z0-9_]+$")

#: 生成文件的注释头。**改产物没用**这件事必须写在文件里 —— 下一个人打开的是产物，
#: 不是生成器。（不带结尾换行：产物文本一律由 `"\n".join(...)` 拼，行内不再埋换行，
#: 否则每行注释都会多出一个空行。）
GEN_HEADER = (
    "# ⚠️ 本文件由 `v3 modgen` 生成（tools/pdx/modgen.py）—— 改这里没用，改数据源 mod/data/*.toml。"
)

#: 文档类产物的注释头（markdown 引用块）。
DOC_HEADER = "> ⚠️ 本文件由 `v3 modgen` 生成 —— 改这里没用，改数据源 `mod/data/*.toml`。"

#: mod 版本号。
#:
#: **为什么不是从数据源读**：它是发布节奏（mod 的第几个版本），不是设计数字 ——
#: 设计数字才受 P10 的 `why` 约束。游戏版本相反，它是"档案对哪个引擎有效"，
#: 所以写在数据源的 `archive.game_version` 里由作者显式钉住。
MOD_VERSION = "0.1.0"

#: 缩进（与生成物一致：Tab，原版脚本的写法）。
TAB = "\t"

#: 本地化文件的键版本号。`KEY:0 "值"` 的 `0` 是给译者看的新旧标记，
#: 新写的键一律 0（原版新键也是 0）。
LOC_VERSION = 0

#: mod 元数据的产物路径（不属于任何原版目录树，所以单列）。
METADATA_REL = ".metadata/metadata.json"


class DataError(ValueError):
    """数据源不合法（结构、类型、`why` 缺失、命名空间越界…）。

    刻意**不**继承 OSError / 不吞异常：数据源写错时必须当场停下，
    而不是生成一份"看起来正常"的产物。
    """


# ── 通用条目 ────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class Number:
    """数据源里的一个数字 + 它的依据。"""

    path: str
    value: float
    why: str


@dataclass(frozen=True, slots=True)
class Param:
    """``key = amount`` 形式的参数（变量参数、修正字段、牌面字段共用）。"""

    key: str
    amount: float
    why: str


@dataclass(frozen=True, slots=True)
class Clause:
    """一条判据：``key op arg``（数值形式写成 ``amount``）。"""

    key: str
    why: str
    op: str = "="
    arg: str | None = None
    amount: float | None = None

    def render(self) -> str:
        return f"{self.key} {self.op} {self.operand()}"

    def operand(self) -> str:
        return self.arg if self.arg is not None else num(self.amount or 0)

    def fact(self) -> str:
        """事实表里的值：``op + 操作数``（与 :func:`readback` 反解出来的一致）。"""
        return f"{self.op}{self.operand()}"


@dataclass(frozen=True, slots=True)
class Condition(Clause):
    """JE 的一条判据，额外带它属于哪个判据块（``gate``）。"""

    gate: str = "possible"


@dataclass(frozen=True, slots=True)
class Tempo:
    """节奏杠杆：覆盖某个 defines 块下的若干参数。"""

    block: str
    why: str
    keys: tuple[Param, ...]


@dataclass(frozen=True, slots=True)
class Memory:
    """战败记忆：变量 + 写它的效果。"""

    variable: str
    effect: str
    why: str
    params: tuple[Param, ...]


@dataclass(frozen=True, slots=True)
class Pressure:
    """压力：静态修正 + 挂它的参数。"""

    name: str
    icon: str
    why: str
    params: tuple[Param, ...]
    effects: tuple[Param, ...]


@dataclass(frozen=True, slots=True)
class Inputs:
    """改革侧输入：**第二个「效果 + 修正」对**（可选表 `[reform_inputs]`）。

    为什么档案需要第二个修正（而不是往 `[pressure]` 里再塞两条字段）：
    阶段 3 的 A/B 阶梯要在**一局之内**分开施加两处理 —— B 段只加冲击、B2 段再追加
    改革侧输入。挤进同一个修正就没有"只加冲击"的那一段，B 与 B2 的差分也就无从谈起
    （执行文档的失败长相要求两层分开报，前提是两处输入能分开施加）。
    """

    name: str
    effect: str
    icon: str
    why: str
    params: tuple[Param, ...]
    effects: tuple[Param, ...]


@dataclass(frozen=True, slots=True)
class JournalEntry:
    """改革窗口 JE。"""

    name: str
    group: str
    icon: str
    why: str
    fields: tuple[Param, ...]
    conditions: tuple[Condition, ...]


@dataclass(frozen=True, slots=True)
class Localization:
    """一条本地化：键 + 每种语言的值。"""

    key: str
    why: str
    values: dict[str, str]


@dataclass(frozen=True, slots=True)
class Card:
    """一张递牌（C 级）。本档案为空，闸门 ③ 按价格表给它定价。"""

    name: str
    slot: str
    weight: float
    why: str
    possible: tuple[Clause, ...]
    fields: tuple[Param, ...]


@dataclass(frozen=True, slots=True)
class Reference:
    """声明式引用：形状上认不出来、只能靠作者声明的那类原版词汇。"""

    kind: str
    name: str
    why: str


@dataclass(frozen=True, slots=True)
class Archive:
    """一份档案编译后的全部结构化事实。"""

    source: str
    id: str
    title: str
    country: str
    game_version: str
    why: str
    tempo: Tempo
    memory: Memory
    pressure: Pressure
    journal_entry: JournalEntry
    localization: tuple[Localization, ...]
    cards: tuple[Card, ...]
    cards_why: str
    references: tuple[Reference, ...]
    numbers: tuple[Number, ...]
    whys: tuple[tuple[str, str], ...]
    inputs: Inputs | None = None

    @property
    def effect_file(self) -> str:
        return f"common/scripted_effects/{FILE_PREFIX}{self.id}_effects.txt"

    @property
    def modifier_file(self) -> str:
        return f"common/static_modifiers/{FILE_PREFIX}{self.id}_pressure.txt"

    @property
    def inputs_file(self) -> str:
        return f"common/static_modifiers/{FILE_PREFIX}{self.id}_reform_inputs.txt"

    @property
    def journal_file(self) -> str:
        return f"common/journal_entries/{FILE_PREFIX}{self.id}_window.txt"

    @property
    def defines_file(self) -> str:
        return f"common/defines/{FILE_PREFIX}{self.id}_tempo.txt"

    @property
    def doc_file(self) -> str:
        return f"{FILE_PREFIX}{self.id}.md"

    def loc_file(self, lang: str) -> str:
        return f"localization/{lang}/{FILE_PREFIX}{self.id}_l_{lang}.yml"

    def card_file(self, card: Card) -> str:
        slug = card.name.removeprefix("ai_strategy_")
        return f"common/ai_strategies/{slug}.txt"


@dataclass(frozen=True, slots=True)
class Built:
    """一次 build 的产物：相对路径 → 文本（**不含 BOM**，写盘时才加）。"""

    archive_ids: tuple[str, ...]
    files: dict[str, str]
    numbers: tuple[Number, ...]

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(sorted(self.files))

    @property
    def game_side(self) -> tuple[str, ...]:
        return tuple(p for p in self.paths if p.endswith(GAME_SIDE_SUFFIXES))


# ── 数字与文本的小工具 ──────────────────────────────────────
def num(value: float) -> str:
    """数字 → PDX 字面量。

    整数不带小数点（原版写 ``-20`` 不写 ``-20.0``）；小数用 Python 的最短往返
    表示（``repr``），因此 ``0.2`` 写成 ``0.2`` 而不是 ``0.20000000000000001``。
    """
    if float(value).is_integer():
        return str(int(value))
    return repr(float(value))


def _require_table(raw: object, path: str) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise DataError(f"{path} 应当是表（table），实为 {type(raw).__name__}")
    return raw


def _require_text(raw: Mapping[str, object], key: str, path: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DataError(f"{path}.{key} 必须是非空字符串")
    return value.strip()


def _require_seq(raw: Mapping[str, object], key: str, path: str) -> list[object]:
    value = raw.get(key, [])
    if not isinstance(value, list):
        raise DataError(f"{path}.{key} 应当是数组")
    return value


def _entries(raw: Mapping[str, object], key: str, path: str) -> list[dict[str, object]]:
    return [
        _require_table(item, f"{path}.{key}[{i}]")
        for i, item in enumerate(_require_seq(raw, key, path))
    ]


def _amount(raw: Mapping[str, object], path: str) -> float:
    value = raw.get("amount")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DataError(f"{path}.amount 必须是数字")
    return float(value)


def _why(raw: Mapping[str, object], path: str) -> str:
    return _require_text(raw, "why", path)


# ── why 的机械校验（P10）────────────────────────────────────
def audit(raw: object, path: str = "") -> tuple[tuple[Number, ...], tuple[tuple[str, str], ...]]:
    """递归遍历数据源：收齐**每个数字**与**每张表的依据**，并检查空 `why`。

    一次收全再报错（而不是遇到第一个就抛）：数据源缺依据时，作者要的是一份
    "哪几处缺"的清单，不是一条一条试。
    """
    numbers: list[Number] = []
    whys: list[tuple[str, str]] = []
    missing: list[str] = []

    def walk(node: object, where: str) -> None:
        if isinstance(node, dict):
            why = node.get("why")
            if not where:
                pass  # 根表：整份数据源本身不需要 why（每张子表各带一条）
            elif not isinstance(why, str) or not why.strip():
                missing.append(where)
            else:
                whys.append((where, why.strip()))
            if "amount" in node:
                numbers.append(
                    Number(path=f"{where}.amount", value=_amount(node, where), why=str(why or ""))
                )
            for key, value in node.items():
                walk(value, f"{where}.{key}" if where else str(key))
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{where}[{index}]")

    walk(raw, path)
    if missing:
        raise DataError(
            "数据源里这些表没有 why（P10：每个数字都必须带依据，判据与文案同样如此）：\n  "
            + "\n  ".join(missing)
        )
    return tuple(numbers), tuple(whys)


# ── 数据源的解析 ────────────────────────────────────────────
def read_source(path: Path) -> dict[str, object]:
    """读一份 TOML 数据源。读不了 / 不是表都当场报错。"""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DataError(f"读不到数据源 {path}：{type(exc).__name__}: {exc}") from exc
    try:
        data = tomllib.loads(raw.decode("utf-8-sig"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise DataError(f"数据源不是合法 TOML：{path}（{type(exc).__name__}: {exc}）") from exc
    return _require_table(data, str(path))


def _params(raw: Mapping[str, object], key: str, path: str) -> tuple[Param, ...]:
    return tuple(
        Param(
            key=_require_text(item, "key", f"{path}.{key}[{i}]"),
            amount=_amount(item, f"{path}.{key}[{i}]"),
            why=_why(item, f"{path}.{key}[{i}]"),
        )
        for i, item in enumerate(_entries(raw, key, path))
    )


def _clause(item: dict[str, object], path: str, *, gate: str | None = None) -> Condition:
    """一条判据。

    ``gate`` 只有 JE 的判据需要（它决定挂在 ``possible`` 还是 ``complete`` 里）；
    递牌的 ``possible`` 里没有这一层，所以是**可选**字段 —— 硬性要求会让
    数据源多写一堆无意义的 `gate = "possible"`。
    """
    op = item.get("op", "=")
    if not isinstance(op, str):
        raise DataError(f"{path}.op 必须是字符串")
    arg = item.get("arg")
    if arg is not None and not isinstance(arg, str):
        raise DataError(f"{path}.arg 必须是字符串")
    has_amount = "amount" in item
    if arg is None and not has_amount:
        raise DataError(f"{path} 既没有 arg 也没有 amount —— 判据没有操作数")
    if gate is None and "gate" in item:
        gate = _require_text(item, "gate", path)
    return Condition(
        key=_require_text(item, "key", path),
        why=_why(item, path),
        op=op,
        arg=arg,
        amount=_amount(item, path) if has_amount else None,
        gate=gate or "",
    )


def parse_source(data: Mapping[str, object], source: str) -> Archive:
    """把一份已读入的数据源编译成 :class:`Archive`。"""
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise DataError(
            f"{source} 的 schema_version 是 {version!r}，本生成器只认 {SCHEMA_VERSION}"
            "（口径见 tools/pdx/modgen.py 的模块文档）"
        )

    numbers, whys = audit(data)

    archive = _require_table(data.get("archive"), f"{source}:archive")
    tempo_raw = _require_table(data.get("tempo"), f"{source}:tempo")
    memory_raw = _require_table(data.get("memory"), f"{source}:memory")
    pressure_raw = _require_table(data.get("pressure"), f"{source}:pressure")
    journal_raw = _require_table(data.get("journal_entry"), f"{source}:journal_entry")
    cards_raw = _require_table(data.get("cards"), f"{source}:cards")

    tempo = Tempo(
        block=_require_text(tempo_raw, "block", "tempo"),
        why=_why(tempo_raw, "tempo"),
        keys=_params(tempo_raw, "keys", "tempo"),
    )
    memory = Memory(
        variable=_require_text(memory_raw, "variable", "memory"),
        effect=_require_text(memory_raw, "effect", "memory"),
        why=_why(memory_raw, "memory"),
        params=_params(memory_raw, "params", "memory"),
    )
    pressure = Pressure(
        name=_require_text(pressure_raw, "name", "pressure"),
        icon=_require_text(pressure_raw, "icon", "pressure"),
        why=_why(pressure_raw, "pressure"),
        params=_params(pressure_raw, "params", "pressure"),
        effects=_params(pressure_raw, "effects", "pressure"),
    )
    conditions = tuple(
        _clause(item, f"journal_entry.conditions[{i}]")
        for i, item in enumerate(_entries(journal_raw, "conditions", "journal_entry"))
    )
    unknown = sorted({c.gate for c in conditions} - set(GATE_ORDER))
    if unknown:
        raise DataError(
            f"journal_entry.conditions 里有不认识的判据块 {unknown}；"
            f"可用：{list(GATE_ORDER)}（顺序固定，见 GATE_ORDER 的注释）"
        )
    journal = JournalEntry(
        name=_require_text(journal_raw, "name", "journal_entry"),
        group=_require_text(journal_raw, "group", "journal_entry"),
        icon=_require_text(journal_raw, "icon", "journal_entry"),
        why=_why(journal_raw, "journal_entry"),
        fields=_params(journal_raw, "fields", "journal_entry"),
        conditions=conditions,
    )

    # `[reform_inputs]` 是**可选**表：老档案（只有冲击一处处理）照样编译。
    # 缺省不是"静默降级"——产物清单与档案文档都会写明这一份档案有没有第二处理段。
    inputs: Inputs | None = None
    if "reform_inputs" in data:
        inputs_raw = _require_table(data["reform_inputs"], f"{source}:reform_inputs")
        inputs = Inputs(
            name=_require_text(inputs_raw, "name", "reform_inputs"),
            effect=_require_text(inputs_raw, "effect", "reform_inputs"),
            icon=_require_text(inputs_raw, "icon", "reform_inputs"),
            why=_why(inputs_raw, "reform_inputs"),
            params=_params(inputs_raw, "params", "reform_inputs"),
            effects=_params(inputs_raw, "effects", "reform_inputs"),
        )

    localization: list[Localization] = []
    for index, item in enumerate(_require_seq(data, "localization", "localization")):
        where = f"localization[{index}]"
        entry = _require_table(item, where)
        values: dict[str, str] = {}
        for lang in LANGUAGES:
            text = entry.get(lang)
            if not isinstance(text, str) or not text.strip():
                raise DataError(
                    f"{where}（键 {entry.get('key')!r}）缺 {lang} 文案 —— "
                    "支持的语言见 modgen.LANGUAGES，缺一种就是漏一种"
                )
            if '"' in text:
                raise DataError(
                    f"{where} 的 {lang} 文案里有裸双引号 —— `.yml` 的值用双引号包裹，"
                    "引擎对转义的支持没有实测证据，所以这里直接拒绝（P13）"
                )
            values[lang] = text
        localization.append(
            Localization(
                key=_require_text(entry, "key", where), why=_why(entry, where), values=values
            )
        )

    cards: list[Card] = []
    for index, item in enumerate(_entries(cards_raw, "items", "cards")):
        where = f"cards.items[{index}]"
        weight_raw = _require_table(item.get("weight"), f"{where}.weight")
        cards.append(
            Card(
                name=_require_text(item, "name", where),
                slot=_require_text(item, "slot", where),
                weight=_amount(weight_raw, f"{where}.weight"),
                why=_why(item, where),
                possible=tuple(
                    _clause(entry, f"{where}.possible[{i}]")
                    for i, entry in enumerate(_entries(item, "possible", where))
                ),
                fields=_params(item, "fields", where),
            )
        )

    references = tuple(
        Reference(
            kind=_require_text(entry, "kind", f"references[{i}]"),
            name=_require_text(entry, "name", f"references[{i}]"),
            why=_why(entry, f"references[{i}]"),
        )
        for i, entry in enumerate(
            _require_table(item, f"references[{i}]")
            for i, item in enumerate(_require_seq(data, "references", "references"))
        )
    )

    parsed = Archive(
        source=source,
        id=_require_text(archive, "id", "archive"),
        title=_require_text(archive, "title", "archive"),
        country=_require_text(archive, "country", "archive"),
        game_version=_require_text(archive, "game_version", "archive"),
        why=_why(archive, "archive"),
        tempo=tempo,
        memory=memory,
        pressure=pressure,
        journal_entry=journal,
        localization=tuple(localization),
        cards=tuple(cards),
        cards_why=_why(cards_raw, "cards"),
        references=references,
        numbers=numbers,
        whys=whys,
        inputs=inputs,
    )
    _check_namespace(parsed)
    return parsed


def _check_namespace(archive: Archive) -> None:
    """F7：命名空间 `sitai_*`、文件 `sitai_*.txt`。

    这条检查在**生成之前**做（闸门 ① 也会做一遍）—— 早早报错的代价远低于
    "产出一份污染了原版命名空间的文件"。
    """
    named = {
        "memory.variable": archive.memory.variable,
        "memory.effect": archive.memory.effect,
        "pressure.name": archive.pressure.name,
        "journal_entry.name": archive.journal_entry.name,
    }
    if archive.inputs is not None:
        named["reform_inputs.name"] = archive.inputs.name
        named["reform_inputs.effect"] = archive.inputs.effect
    for card in archive.cards:
        named[f"cards.{card.name}"] = card.name
    bad = [f"{k}={v!r}" for k, v in named.items() if not NAMESPACE_RE.match(v)]
    if bad:
        raise DataError(
            f"这些名字不在命名空间 `{(NAMESPACE_RE.pattern)}` 里（F7）：{', '.join(bad)}"
        )


def load_data(path: Path) -> Archive:
    """读一份数据源并编译成档案（含 `why` 校验与命名空间校验）。"""
    return parse_source(read_source(path), path.name)


def data_files(data_dir: Path | None = None) -> tuple[Path, ...]:
    """数据源目录下的全部档案（按文件名排序 —— 确定性的第一环）。"""
    base = data_dir or DATA_DIR
    if not base.is_dir():
        return ()
    return tuple(sorted(base.glob(f"*{DATA_SUFFIX}")))


def load_all(data_dir: Path | None = None) -> tuple[Archive, ...]:
    """读全部数据源。一份都没有时报错（空产物不是"成功"）。"""
    files = data_files(data_dir)
    if not files:
        raise DataError(f"{data_dir or DATA_DIR} 下没有 {DATA_SUFFIX} 数据源")
    return tuple(load_data(path) for path in files)


# ── 产物文本 ────────────────────────────────────────────────
#: 一个可渲染节点：一行文本（``key = value`` / 注释 / 空行），或 ``(块名, 子节点)``。
Node = str | tuple[str, "list[Node]"]


def _render(node: Node, indent: int = 0) -> list[str]:
    """把节点渲染成行。

    为什么要有它（而不是拼字符串）：脚本是**嵌套**的（效果里套 set_variable、
    JE 里套 possible），手拼缩进一旦错一层，产物在游戏里表现为"这段不生效"，
    而肉眼要盯着看很久。这里缩进由 ``indent`` 推出来，嵌套多深都不会错。
    空行不补缩进 —— 否则产物里会出现尾随空白，逐字节比对时成为噪声。
    """
    pad = TAB * indent
    if isinstance(node, str):
        return ["" if not node else f"{pad}{node}"]
    name, body = node
    out = [f"{pad}{name} = {{"]
    for child in body:
        out.extend(_render(child, indent + 1))
    out.append(f"{pad}}}")
    return out


def _comment(*lines: str) -> list[Node]:
    """注释段落（末尾补一个空行 —— 与脚本正文分开）。"""
    out: list[Node] = [f"# {line}" if line else "#" for line in lines]
    out.append("")
    return out


def effects_text(archive: Archive) -> str:
    """冲击记账效果：写记忆变量 + 挂压力修正（有第二处理段时再附一个效果）。"""
    memory = archive.memory
    set_variable: Node = (
        "set_variable",
        [f"name = {memory.variable}", *(f"{p.key} = {num(p.amount)}" for p in memory.params)],
    )
    add_modifier: Node = (
        "add_modifier",
        [
            f"name = {archive.pressure.name}",
            *(f"{p.key} = {num(p.amount)}" for p in archive.pressure.params),
        ],
    )
    lines: list[Node] = [
        GEN_HEADER,
        "",
        *_comment(
            "战败求存 · 冲击记账（A 级：真实世界状态 —— 变量 + 修正，不占任何槽位）。",
            "调用方：阶段 3 的 A/B 实验（B 组施加冲击）。本档案刻意**不绑 on_action**：",
            "原版 on_war_end 只给 scope:actor / scope:target，不带胜负（00_code_on_actions.txt:7043），",
            "挂错会把战胜方也记成战败 —— 「谁算战败」的判定留待实验给结论。",
            f"变量 {memory.variable}；压力修正 {archive.pressure.name}。",
        ),
        (memory.effect, [set_variable, add_modifier]),
    ]
    inputs = archive.inputs
    if inputs is not None:
        lines += [
            "",
            *_comment(
                f"改革侧输入（A 级：同样是真实世界状态）：{inputs.why}",
                "为什么单独一个效果：实验的 B 段只施加冲击、B2 段才追加这一处 ——",
                "两处合并在一个效果里就分不出是哪一处起了作用（执行文档：两层分开报）。",
                f"修正 {inputs.name}；效果名 {inputs.effect}（不绑 on_action，由实验显式调用）。",
            ),
            (
                inputs.effect,
                [
                    (
                        "add_modifier",
                        [
                            f"name = {inputs.name}",
                            *(f"{p.key} = {num(p.amount)}" for p in inputs.params),
                        ],
                    )
                ],
            ),
        ]
    return "\n".join(_flatten(lines))


def inputs_text(archive: Archive) -> str:
    """改革侧输入修正：把原版自己的读入抬起来（不递牌，仍走 A 级）。

    只有数据源里有 `[reform_inputs]` 时才生成 —— 调用方要先看
    :attr:`Archive.inputs` 是不是 ``None``（生成器不猜）。
    """
    inputs = archive.inputs
    if inputs is None:  # pragma: no cover - 调用方按 Archive.inputs 分支，这里只兜底
        raise DataError(f"档案 {archive.id} 没有 [reform_inputs]，不该走到这里")
    lines: list[Node] = [
        GEN_HEADER,
        "",
        *_comment(
            f"改革侧输入（A 级）：{inputs.why}",
            f"每条字段的依据见 {FILE_PREFIX}{archive.id}.md（由 why_report 生成）。",
            "⚠️ 这一份**不是**冲击本身：它是实验的第二处理段（B2）才挂的东西 ——",
            "写进 [pressure] 会让「只加冲击」的那一段消失。",
        ),
        (
            inputs.name,
            [f"icon = {inputs.icon}", *(f"{p.key} = {num(p.amount)}" for p in inputs.effects)],
        ),
    ]
    return "\n".join(_flatten(lines))


def modifier_text(archive: Archive) -> str:
    """压力修正：真实的合法性 / 贵族 / 财政变化。"""
    pressure = archive.pressure
    lines: list[Node] = [
        GEN_HEADER,
        "",
        *_comment(
            f"战败压力（A 级）：{archive.title}。三条字段都照原版同族用法取档位，",
            f"每条的依据见 {FILE_PREFIX}{archive.id}.md（由 why_report 生成）。",
        ),
        (
            pressure.name,
            [f"icon = {pressure.icon}", *(f"{p.key} = {num(p.amount)}" for p in pressure.effects)],
        ),
    ]
    return "\n".join(_flatten(lines))


def journal_text(archive: Archive) -> str:
    """改革窗口 JE：is_shown / possible / complete 判据 + weight。"""
    journal = archive.journal_entry
    body: list[Node] = [f'icon = "{journal.icon}"', f"group = {journal.group}"]
    for gate in GATE_ORDER:
        picked = [c for c in journal.conditions if c.gate == gate]
        if not picked:
            continue
        body.append("")
        body.append((gate, [c.render() for c in picked]))
    if journal.fields:
        body.append("")
        body.extend(f"{p.key} = {num(p.amount)}" for p in journal.fields)
    lines: list[Node] = [
        GEN_HEADER,
        "",
        *_comment(
            f"改革窗口 JE（{archive.title}）：判据驱动 —— 只有压力够大才开。",
            "为什么用 JE：原版有 18 张牌直接读 has_journal_entry（01a L 节），",
            "于是「开一个 JE」= 同时喂给原版自己的 18 张牌，不占任何槽位（F5）。",
        ),
        (journal.name, body),
    ]
    return "\n".join(_flatten(lines))


def defines_text(archive: Archive) -> str:
    """节奏杠杆：按「块 + 参数」覆盖，**不复制**原版 defines 文件。"""
    tempo = archive.tempo
    lines: list[Node] = [
        GEN_HEADER,
        "",
        *_comment(
            f"节奏杠杆（**全局作用域**：{archive.title} 只是它的来源档案）：只覆盖 {tempo.block} 块的 {len(tempo.keys)} 个键，",
            "不复制原版 00_ai.txt（KB 05 §1.7 的按「块 + 参数」覆盖；阶段 2 的 storm 变体实测生效）。",
            "⚠️ defines 没有单国写法：这两个键一改，**所有国家**的 AI 重抽节奏都变 —— 别把它当成单国效果。",
            "覆盖范围就是下面这几个键 —— 原版别的参数一个都不抄。",
        ),
        (tempo.block, [f"{p.key} = {num(p.amount)}" for p in tempo.keys]),
    ]
    return "\n".join(_flatten(lines))


def card_text(archive: Archive, card: Card) -> str:
    """一张递牌（本档案为空；骨架留着，因为它决定闸门 ③ 的输入形状）。

    ``archive`` 目前只用于注释头（档案 id）—— 保留这个形参是因为牌的
    traceability 迟早要引档案级信息，而调用点（:func:`build`）已按档案分发。
    """
    body: list[Node] = [f"type = {card.slot}"]
    if card.possible:
        body.extend(["", ("possible", [c.render() for c in card.possible])])
    body.extend(["", ("weight", [f"value = {num(card.weight)}"])])
    if card.fields:
        body.append("")
        body.extend(f"{p.key} = {num(p.amount)}" for p in card.fields)
    lines: list[Node] = [
        GEN_HEADER,
        "",
        *_comment(
            f"递牌（C 级）：{card.name} —— 占 {card.slot} 槽一个位置（档案 {archive.id}）。",
            "定价见闸门 ③（阶段 2 的等效竞争权重表）；档案里没有牌是 F5 的结果，不是漏写。",
        ),
        (card.name, body),
    ]
    return "\n".join(_flatten(lines))


def _flatten(nodes: Sequence[Node]) -> list[str]:
    """把一串节点渲染成行（顶层 indent = 0）。"""
    out: list[str] = []
    for node in nodes:
        out.extend(_render(node))
    return out


def loc_text(archive: Archive, lang: str) -> str:
    """一个语言的本地化文件。

    格式照原版：``l_<语言>:`` 行 + 每行一个 `` KEY:版本 "值"``。**注释头放在
    语言声明行之后**：抽查原版 `localization/english/` 前 60 个 `.yml`，首行是
    语言声明的是 60/60、首行是注释或空行的是 0 —— "首行必须是语言声明" 没有反例，
    而注释在语言行之后是原版常态（如 je_lobby_text_l_english.yml），所以不去试探它。
    """
    lines = [f"{LANGUAGES[lang]}:", GEN_HEADER]
    lines.extend(
        f' {entry.key}:{LOC_VERSION} "{entry.values[lang]}"' for entry in archive.localization
    )
    return "\n".join(lines) + "\n"


def metadata_text(archive: Archive) -> str:
    """`descriptor` 用的元数据（JSON，**不带 BOM** —— 读它的是启动器）。"""
    payload = {
        "name": f"SITAI 处境档案 · {archive.title}",
        "id": f"{NAMESPACE_PREFIX.rstrip('_')}.{archive.id}",
        "version": MOD_VERSION,
        "supported_game_version": archive.game_version,
        "short_description": archive.why,
        "tags": [],
        "relationships": [],
        "game_custom_data": {"multiplayer_synchronized": False},
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def doc_text(archive: Archive) -> str:
    """档案文档：人读的那一份 —— 每个数字、每条判据、每个引用与它的依据。"""
    lines = [
        f"# 档案 · {archive.title}",
        "",
        DOC_HEADER,
        "",
        (
            f"* **档案 id**：`{archive.id}`　**国家**：`{archive.country}`　"
            f"**游戏版本**：`{archive.game_version}`"
        ),
        f"* **本档案修什么毛病**：{archive.why}",
        f"* **递牌**：{len(archive.cards)} 张 —— {archive.cards_why}",
        "",
        "## 产物清单",
        "",
        "| 文件 | 作用 |",
        "|---|---|",
        f"| `{archive.effect_file}` | 冲击记账效果（写 `{archive.memory.variable}` + 挂 `{archive.pressure.name}`） |",
        f"| `{archive.modifier_file}` | 压力修正（真实的合法性 / 贵族 / 财政变化） |",
        f"| `{archive.journal_file}` | 改革窗口 JE（判据驱动） |",
        f"| `{archive.defines_file}` | 节奏杠杆（覆盖 `{archive.tempo.block}` 块） |",
        *(
            [
                (
                    f"| `{archive.inputs_file}` | 改革侧输入修正（第二处理段 B2 才挂；"
                    f"`{archive.inputs.effect}` 施加） |"
                )
            ]
            if archive.inputs is not None
            else [
                (
                    "| —— | 本档案没有第二处理段（数据源里没有 `[reform_inputs]`）："
                    "实验只有「加冲击 / 不加冲击」两段 |"
                )
            ]
        ),
        *(f"| `{archive.loc_file(lang)}` | {lang} 文案 |" for lang in sorted(LANGUAGES)),
        "| `.metadata/metadata.json` | mod 元数据（启动器读；不带 BOM） |",
        "",
        "## 每个数字与它的依据（P10）",
        "",
        why_report(archive),
        "",
        "## 判据（JE）",
        "",
        "| 判据块 | 判据 | 为什么 |",
        "|---|---|---|",
        *(f"| `{c.gate}` | `{c.render()}` | {c.why} |" for c in archive.journal_entry.conditions),
        "",
        "## 声明式引用（闸门 ② 逐条核对）",
        "",
        "| 类别 | 名字 | 为什么 |",
        "|---|---|---|",
        *(f"| `{r.kind}` | `{r.name}` | {r.why} |" for r in archive.references),
        "",
        "## 复算",
        "",
        "```text",
        "v3 modgen --write     # 数据源 → 产物（改完 TOML 必跑）",
        "v3 modguard           # 五道闸门（不通过不许进游戏）",
        "v3 modgen --why       # 只列每个数字与它的依据",
        "```",
        "",
    ]
    return "\n".join(lines)


# ── 编译 ────────────────────────────────────────────────────
def build(archive: Archive) -> Built:
    """把一份档案编译成 ``relpath → 文本``（相对产物根）。"""
    files: dict[str, str] = {
        archive.effect_file: effects_text(archive),
        archive.modifier_file: modifier_text(archive),
        archive.journal_file: journal_text(archive),
        archive.defines_file: defines_text(archive),
        archive.doc_file: doc_text(archive),
        METADATA_REL: metadata_text(archive),
    }
    if archive.inputs is not None:
        files[archive.inputs_file] = inputs_text(archive)
    for lang in sorted(LANGUAGES):
        files[archive.loc_file(lang)] = loc_text(archive, lang)
    for card in archive.cards:
        files[archive.card_file(card)] = card_text(archive, card)
    return Built(archive_ids=(archive.id,), files=files, numbers=archive.numbers)


def build_all(archives: Sequence[Archive]) -> Built:
    """把多份档案合成一次构建。

    产物路径冲突 = 两份档案写了同一个文件 —— 当场报错：静默覆盖会让
    "哪份档案在起作用"变成无解的问题。
    """
    files: dict[str, str] = {}
    numbers: list[Number] = []
    ids: list[str] = []
    for archive in archives:
        built = build(archive)
        clash = sorted(set(built.files) & set(files))
        if clash:
            raise DataError(
                f"档案 {archive.id} 与前面的档案写了同一个产物路径：{clash} —— "
                "产物路径由 `sitai_<档案 id>_*` 派生，改 id 而不是让它互相覆盖"
            )
        files.update(built.files)
        numbers.extend(built.numbers)
        ids.append(archive.id)
    return Built(archive_ids=tuple(ids), files=files, numbers=tuple(numbers))


def summary(built: Built) -> str:
    """给人看的构建摘要。"""
    lines = [
        f"档案：{'、'.join(built.archive_ids)}",
        f"产物 {len(built.files)} 个（游戏侧 {len(built.game_side)} 个）：",
    ]
    lines.extend(f"  {path}" for path in built.paths)
    numbers = len(built.numbers)
    lines.append(f"带依据的数字 {numbers} 个（`v3 modgen --why` 展开）")
    return "\n".join(lines)


# ── 写盘与核对 ──────────────────────────────────────────────
def _writes_bom(rel: str) -> bool:
    """这份产物要不要写 BOM。

    游戏侧（`.txt` / `.yml`）**要** —— 原版 3,026 个 `.txt` 里 3,002 个带 BOM，
    缺 BOM 的表现是"文件像没生效"。`.md`（给人看的）与 `.json`（启动器按 JSON 解析）
    **不要**。
    """
    return rel.endswith(GAME_SIDE_SUFFIXES)


def write(built: Built, root: Path | None = None) -> list[Path]:
    """把产物写进仓库里的产物根，并清掉**被取代的旧文件**。

    清理的判据：产物根下所有 `sitai_*` 文件里，不在本次构建结果中的那些。
    为什么必须清：数据源删掉一条（或改了档案 id）之后，旧文件会继续被游戏加载，
    表现是"改了数据源却没变化" —— 最容易被误信的一类失败。
    """
    base = root or PRODUCT_DIR
    written: list[Path] = []
    for rel, text in sorted(built.files.items()):
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        encoding = "utf-8-sig" if _writes_bom(rel) else "utf-8"
        path.write_text(text, encoding=encoding, newline="\n")
        written.append(path)
    for stale in stale_files(built, base):
        stale.unlink()
        _prune_empty(stale.parent, base)
    return written


def _prune_empty(path: Path, base: Path) -> None:
    """删掉因清理而空掉的目录（只删我们自己产物根下的空壳）。"""
    while path != base and base in path.parents:
        if any(path.iterdir()):
            return
        path.rmdir()
        path = path.parent


def stale_files(built: Built, root: Path | None = None) -> list[Path]:
    """产物根下**该清掉**的旧文件：我们的文件里不在本次构建结果中的那些。"""
    base = root or PRODUCT_DIR
    if not base.is_dir():
        return []
    wanted = {base / rel for rel in built.files}
    return [
        path
        for path in sorted(base.rglob(f"{FILE_PREFIX}*"))
        if path.is_file() and path not in wanted
    ]


def check(built: Built, root: Path | None = None) -> list[str]:
    """盘上产物与生成结果不一致的地方（手改 / 过期 / 多余 / 缺 BOM）。

    返回人读的问题清单，空列表 = 干净。``v3 modgen --check`` 与闸门 ⑤ 都用它 ——
    「产物是不是生成出来的」这件事必须能被机械地回答。
    """
    base = root or PRODUCT_DIR
    problems: list[str] = []
    for rel, text in sorted(built.files.items()):
        path = base / rel
        if not path.is_file():
            problems.append(f"缺产物：{rel}（跑 `v3 modgen --write`）")
            continue
        raw = path.read_bytes()
        if _writes_bom(rel):
            if not raw.startswith(b"\xef\xbb\xbf"):
                problems.append(f"缺 UTF-8 BOM：{rel}")
                continue
            raw = raw[3:]
        if raw.decode("utf-8", errors="replace") != text:
            problems.append(f"与数据源不一致（被手改或数据源改过没重生成）：{rel}")
    problems.extend(
        f"多余产物（被取代的旧文件）：{path.relative_to(base).as_posix()}"
        for path in stale_files(built, base)
    )
    return problems


# ── why 报告 ────────────────────────────────────────────────
def why_report(archive: Archive) -> str:
    """每个数字 + 它的依据（markdown 表）。也是档案文档正文章节。"""
    rows = [
        "| 位置 | 数值 | 依据 |",
        "|---|---:|---|",
        *(f"| `{n.path}` | {num(n.value)} | {n.why} |" for n in archive.numbers),
    ]
    return "\n".join(rows)


def why_tables(archive: Archive) -> str:
    """没有数字的那些表（判据块、引用、说明）的依据清单。"""
    rows = [
        "| 位置 | 依据 |",
        "|---|---|",
        *(f"| `{path}` | {why} |" for path, why in archive.whys),
    ]
    return "\n".join(rows)


# ── 事实表与反解（闸门 ④ 的两端）────────────────────────────
def facts(archive: Archive) -> list[tuple[str, str]]:
    """数据源 → 扁平事实表 ``(路径, 值)``。

    路径用点号串起结构（``modifier.<名>.<字段>``），值一律是字符串 —— 于是
    "数据源"与"从产物反解出来的东西"可以直接做集合比对（闸门 ④）。
    """
    out: list[tuple[str, str]] = [
        (f"effects.{archive.memory.effect}.set_variable.name", archive.memory.variable),
        (f"effects.{archive.memory.effect}.add_modifier.name", archive.pressure.name),
        (f"modifier.{archive.pressure.name}.icon", archive.pressure.icon),
        (f"journal_entry.{archive.journal_entry.name}.icon", archive.journal_entry.icon),
        (f"journal_entry.{archive.journal_entry.name}.group", archive.journal_entry.group),
        ("metadata.id", f"{NAMESPACE_PREFIX.rstrip('_')}.{archive.id}"),
        ("metadata.version", MOD_VERSION),
        ("metadata.supported_game_version", archive.game_version),
    ]
    out.extend(
        (f"effects.{archive.memory.effect}.set_variable.{p.key}", num(p.amount))
        for p in archive.memory.params
    )
    out.extend(
        (f"effects.{archive.memory.effect}.add_modifier.{p.key}", num(p.amount))
        for p in archive.pressure.params
    )
    out.extend(
        (f"modifier.{archive.pressure.name}.{p.key}", num(p.amount))
        for p in archive.pressure.effects
    )
    out.extend(
        (f"journal_entry.{archive.journal_entry.name}.{p.key}", num(p.amount))
        for p in archive.journal_entry.fields
    )
    out.extend(
        (f"journal_entry.{archive.journal_entry.name}.{c.gate}.{c.key}", c.fact())
        for c in archive.journal_entry.conditions
    )
    out.extend(
        (f"defines.{archive.tempo.block}.{p.key}", num(p.amount)) for p in archive.tempo.keys
    )
    if archive.inputs is not None:
        inputs = archive.inputs
        out.append((f"effects.{inputs.effect}.add_modifier.name", inputs.name))
        out.extend(
            (f"effects.{inputs.effect}.add_modifier.{p.key}", num(p.amount)) for p in inputs.params
        )
        out.append((f"modifier.{inputs.name}.icon", inputs.icon))
        out.extend((f"modifier.{inputs.name}.{p.key}", num(p.amount)) for p in inputs.effects)
    for card in archive.cards:
        out.append((f"card.{card.name}.slot", card.slot))
        out.append((f"card.{card.name}.weight", num(card.weight)))
        out.extend((f"card.{card.name}.possible.{c.key}", c.fact()) for c in card.possible)
        out.extend((f"card.{card.name}.{p.key}", num(p.amount)) for p in card.fields)
    for entry in archive.localization:
        out.extend((f"localization.{lang}.{entry.key}", entry.values[lang]) for lang in LANGUAGES)
    return sorted(out)


def _scalar(node: object) -> str:
    if isinstance(node, Scalar):
        return node.unquoted
    if isinstance(node, Block):
        return f"{{{len(node)}项}}"
    return ""


def _top(parsed_path: str, text: str) -> list[Assignment]:
    """解析一份生成物并返回顶层赋值；解析出错就报错（闸门 ④ 会把它当红）。"""
    parsed = parse_text(text, parsed_path)
    if parsed.errors:
        raise DataError(f"{parsed_path} 解析失败：{parsed.errors}")
    return parsed.top_assignments


def _block_of(node: Assignment | None) -> Block | None:
    return node.value if node is not None and isinstance(node.value, Block) else None


def _facts_effects(rel: str, text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for top in _top(rel, text):
        block = _block_of(top)
        if block is None:
            continue
        for label in ("set_variable", "add_modifier"):
            inner = _block_of(block.first(label))
            out.extend(
                (f"effects.{top.key}.{label}.{item.key}", _scalar(item.value))
                for item in (inner.assignments() if inner else [])
            )
    return out


def _facts_modifier(rel: str, text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for top in _top(rel, text):
        block = _block_of(top)
        out.extend(
            (f"modifier.{top.key}.{item.key}", _scalar(item.value))
            for item in (block.assignments() if block else [])
        )
    return out


def _facts_journal(rel: str, text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for top in _top(rel, text):
        block = _block_of(top)
        if block is None:
            continue
        for item in block.assignments():
            inner = _block_of(item)
            if item.key in GATE_ORDER:
                out.extend(
                    (
                        f"journal_entry.{top.key}.{item.key}.{clause.key}",
                        f"{clause.op}{_scalar(clause.value)}",
                    )
                    for clause in (inner.assignments() if inner else [])
                )
            else:
                out.append((f"journal_entry.{top.key}.{item.key}", _scalar(item.value)))
    return out


def _facts_defines(rel: str, text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for top in _top(rel, text):
        block = _block_of(top)
        out.extend(
            (f"defines.{top.key}.{item.key}", _scalar(item.value))
            for item in (block.assignments() if block else [])
        )
    return out


def _facts_card(rel: str, text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for top in _top(rel, text):
        block = _block_of(top)
        if block is None:
            continue
        weight = _block_of(block.first("weight"))
        value = weight.first("value") if weight is not None else None
        out.append((f"card.{top.key}.weight", _scalar(value.value) if value else ""))
        possible = _block_of(block.first("possible"))
        out.extend(
            (f"card.{top.key}.possible.{clause.key}", f"{clause.op}{_scalar(clause.value)}")
            for clause in (possible.assignments() if possible else [])
        )
        out.extend(
            (f"card.{top.key}.{item.key}", _scalar(item.value))
            for item in block.assignments()
            if item.key not in {"weight", "possible"}
        )
    return out


def _facts_loc(rel: str, text: str) -> list[tuple[str, str]]:
    lang = rel.split("/")[1]
    return [(f"localization.{lang}.{key}", value) for key, value in parse_loc_text(text).items()]


#: 产物目录 → 反解器。键是 ``(产物根下的第一层, 第二层)`` ——
#: 与 F7 的「平铺」同构：我们的文件只出现在这些位置。
_FACT_READERS: dict[tuple[str, str], Callable[[str, str], list[tuple[str, str]]]] = {
    ("common", "scripted_effects"): _facts_effects,
    ("common", "static_modifiers"): _facts_modifier,
    ("common", "journal_entries"): _facts_journal,
    ("common", "defines"): _facts_defines,
    ("common", "ai_strategies"): _facts_card,
    **{("localization", lang): _facts_loc for lang in LANGUAGES},
}


def readback(files: Mapping[str, str]) -> list[tuple[str, str]]:
    """产物 → 同一套扁平事实表（闸门 ④ 的另一端）。

    刻意**独立于生成器**：这里按 PDX 语法把文件解析回来，而不是回放生成时的字符串。
    两边共用同一套 render 函数就成了自说自话 —— 那样"往返净度"只能证明
    "我按我写的写了一遍"。
    """
    out: list[tuple[str, str]] = []
    for rel in sorted(files):
        text = files[rel]
        if rel == METADATA_REL:
            payload = json.loads(text)
            out.extend(
                (f"metadata.{key}", str(payload.get(key, "")))
                for key in ("id", "version", "supported_game_version")
            )
            continue
        parts = rel.split("/")
        reader = _FACT_READERS.get((parts[0], parts[1])) if len(parts) == 3 else None
        if reader is not None:
            out.extend(reader(rel, text))
    return sorted(out)


#: 本地化条目行：``KEY:版本 "值"``。**与 :mod:`pdx.localization` 的口径一致**
#: （键是第一个 ``:`` 之前的部分、版本号可缺省、值可能没有引号），
#: 这里自己写一遍是因为反解要比对**值**，而那边只返回键。
_LOC_ENTRY = re.compile(r"^\s*([^\s:#][^:]*?)\s*:\s*(\d+)?\s*(.*)$")


def parse_loc_text(text: str) -> dict[str, str]:
    """把一份 `.yml` 解析成 ``键 → 值``（本地化不是花括号语法，单独处理）。"""
    pattern = _LOC_ENTRY
    out: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = pattern.match(line)
        if not match:
            continue
        key, _version, value = match.group(1), match.group(2), match.group(3).strip()
        if key.startswith("l_"):
            continue  # 语言声明行，不是条目
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        out[key] = value
    return out


__all__ = [
    "DATA_DIR",
    "DATA_SUFFIX",
    "FILE_PREFIX",
    "GATE_ORDER",
    "GEN_HEADER",
    "LANGUAGES",
    "MOD_VERSION",
    "NAMESPACE_PREFIX",
    "PRODUCT_DIR",
    "SCHEMA_VERSION",
    "Archive",
    "Built",
    "Card",
    "Clause",
    "Condition",
    "DataError",
    "Inputs",
    "JournalEntry",
    "Localization",
    "Memory",
    "Number",
    "Param",
    "Pressure",
    "Reference",
    "Tempo",
    "audit",
    "build",
    "build_all",
    "card_text",
    "check",
    "data_files",
    "defines_text",
    "doc_text",
    "effects_text",
    "facts",
    "inputs_text",
    "journal_text",
    "load_all",
    "load_data",
    "loc_text",
    "metadata_text",
    "modifier_text",
    "num",
    "parse_loc_text",
    "parse_source",
    "read_source",
    "readback",
    "stale_files",
    "summary",
    "why_report",
    "why_tables",
    "write",
]
