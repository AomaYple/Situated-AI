"""原版 AI 意图层的「可执行面」提取（阶段 1，纯读 + 生成）。

它回答三个问题，全部从原版文件里**枚举**出来（不手抄）：

1. **有哪些牌**：``common/ai_strategies/*.txt`` 里每张 ``ai_strategy_*`` 的槽位（``type``）、
   权重基准、条件条数、有无 ``possible`` 门、以及牌面上出现的字段；
2. **牌在读什么**：牌的 ``weight`` / ``possible`` 块里出现的**触发器**、
   **脚本值引用**与 **scope 引用** —— 这张清单就是「可喂输入清单」：
   凡是原版 AI 自己会读的量，我们移动它就能影响概率（手段阶梯的 B 级）；
3. **面有多大**：``common/defines/00_ai.txt`` 的 ``NAI`` 键与 ``AI_*`` 条目数。

产物：``docs/design/02-可执行面.md``（由 ``v3 ai-surface --write`` 生成，**勿手改**）。
人工判断（哪些因子进第一版、失败模式清单、H1 设计）写在
``docs/design/exec/阶段1-结果.md`` 里，与本模块无关。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pdx import config
from pdx.cache import parse_cached
from pdx.model import Assignment, Block, Node, Scalar

#: 策略文件所在目录（相对 ``game/``）。
STRATEGY_DIR = Path("common") / "ai_strategies"

#: 全局 AI 参数文件（相对 ``game/``）。
DEFINES_FILE = Path("common") / "defines" / "00_ai.txt"

#: 生成物路径（相对仓库根）。
DOC_PATH = Path("docs") / "design" / "02-可执行面.md"

#: 便于 CLI / 测试引用的路径字符串。
DOC_REL = DOC_PATH.as_posix()

#: 牌面上属于「元数据」而非行为参数的字段。
META_FIELDS = frozenset({"icon", "type", "weight", "possible"})

#: 逻辑包装键：本身不是输入，但要把里面的内容继续往下挖（比较时统一小写）。
LOGICAL_KEYS = frozenset(
    {
        "and",
        "or",
        "not",
        "nor",
        "nand",
        "if",
        "else",
        "else_if",
        "limit",
        "trigger_if",
        "trigger_else_if",
        "trigger_else",
        "hidden",
        "custom_tooltip",
        "trigger",
    }
)

#: 脚本值运算符：本身不是输入；它的**标量值**若是标识符，那才是被引用的脚本值/常量。
OPERATOR_KEYS = frozenset(
    {
        "value",
        "add",
        "subtract",
        "multiply",
        "divide",
        "modulo",
        "min",
        "max",
        "round",
        "ceiling",
        "floor",
        "power",
        "base",
        "desc",
    }
)

#: 数值/运算符形式：出现在脚本值表达式里但不是「引用」的 token。
_NUMERIC = re.compile(r"^[+-]?\d+(?:\.\d+)?$")

#: scope 引用（``c:AUS`` / ``ig:ig_landowners`` / ``var:x`` / ``scope:target`` …）。
_SCOPE_REF = re.compile(
    r"\b(?:c|cu|ig|var|scope|law_type|sr|s|g|p|hq|market|rel|tech):[A-Za-z0-9_]+"
)

#: 不是引用的字面量。
_LITERALS = frozenset({"yes", "no", "this", "root", "prev", "owner", "none"})


@dataclass(frozen=True, slots=True)
class Card:
    """一张 AI 策略牌。"""

    name: str
    slot: str
    file: str
    line: int
    weight_base: float | None
    weight_terms: int
    has_possible: bool
    fields: tuple[str, ...]
    weight_inputs: tuple[str, ...]
    possible_inputs: tuple[str, ...]
    field_inputs: tuple[str, ...]

    @property
    def inputs(self) -> tuple[str, ...]:
        return tuple(
            sorted(set(self.weight_inputs) | set(self.possible_inputs) | set(self.field_inputs))
        )


@dataclass(frozen=True, slots=True)
class InputUse:
    """一个被牌读到的输入及其用量。"""

    name: str
    kind: str  # trigger | script_value | scope
    cards: int
    where: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Factor:
    """候选账本因子（来自 `01a` A 节的输入清单）。"""

    name: str
    pattern: str
    note: str


#: 候选因子：名字 → 用于在原版输入里找对应物的正则。
FACTORS: tuple[Factor, ...] = (
    Factor(
        "利益集团力量/在朝",
        r"interest_group|^ig_|in_government|powerful|marginalized",
        "内部摩擦主体",
    ),
    Factor("法律状态", r"^law_|has_law|law_type|is_enacting|enact", "能否做 + 阻力"),
    Factor("合法性", r"legitimacy", "政权执行能力"),
    Factor("激进派/动乱", r"radical|turmoil|movement|unrest|protest", "社会压力"),
    Factor("财政/债务", r"treasury|debt|gold_reserves|credit|income|budget", "手段上限"),
    Factor("识字率/教育", r"literacy|education|university|academia", "长期能力"),
    Factor("军队规模/质量", r"army|battalion|military|mobiliz|conscript|navy|flotilla", "外部手段"),
    Factor("战争支持/疲惫", r"war_support|war_exhaustion|war_weariness|pro_war", "战争意愿"),
    Factor("恶名/威胁", r"infamy|threat|aggression|danger|menace", "外部结构"),
    Factor("邻国/边境", r"neighbor|border|adjacen|is_neighbor|contiguous", "地理位置"),
    Factor("态度/关系", r"attitude|relations|opinion|rivalry", "外交倾向"),
    Factor("条约/同盟/集团", r"treaty|pact|alliance|subject|overlord|power_bloc", "外交结构"),
    Factor("市场/贸易", r"market|trade|goods|tariff|embargo|export|import", "市场结构"),
    Factor("统治者/政府", r"ruler|government|has_ideology|monarchist|party", "身份项来源"),
    Factor("JE/使命", r"journal_entry|^je_", "官方已写下的执念"),
    Factor("科技/工业", r"technology|^tech_|industrial|^building_|manufacturing", "禀赋"),
)


def strategy_files(game: Path | None = None) -> list[Path]:
    """策略文件列表（排序稳定，便于可复现）。"""
    base = (game or config.GAME) / STRATEGY_DIR
    return sorted(p for p in base.glob("*.txt") if p.is_file())


def _scalar_text(node: Node | None) -> str | None:
    if isinstance(node, Scalar):
        return node.unquoted
    return None


def _walk(block: Block, triggers: list[str], values: list[str]) -> None:
    """递归收集块里的触发器名与脚本值/scope 引用。"""
    for item in block.items:
        if isinstance(item, Scalar):
            text = item.unquoted
            if _NUMERIC.match(text) or text in _LITERALS:
                continue
            (values if _SCOPE_REF.search(text) else triggers).append(text)
            continue
        if not isinstance(item, Assignment):
            continue
        key = item.key
        low = key.lower()
        value = item.value
        if low in LOGICAL_KEYS:
            if isinstance(value, Block):
                _walk(value, triggers, values)
            continue
        if low in OPERATOR_KEYS:
            # 脚本值表达式：标量若是标识符，就是被引用的脚本值/常量
            ref = _scalar_text(value)
            if ref is not None and not _NUMERIC.match(ref) and ref not in _LITERALS:
                values.append(ref)
            elif isinstance(value, Block):
                _walk(value, triggers, values)
            continue
        triggers.append(key)
        if isinstance(value, Block):
            _walk(value, triggers, values)


def _identifiers(block: Block) -> tuple[list[str], list[str]]:
    triggers: list[str] = []
    values: list[str] = []
    _walk(block, triggers, values)
    return triggers, values


def _weight_base(block: Block) -> float | None:
    for key in ("value", "base"):
        found = block.first(key)
        if found is not None:
            text = _scalar_text(found.value)
            if text is not None and _NUMERIC.match(text):
                return float(text)
    return None


def _term_count(block: Block) -> int:
    """权重块里的条件条数（``if`` / ``else_if`` / ``else`` 的个数）。"""
    return sum(1 for a in block.assignments() if a.key in {"if", "else_if", "else"})


def card_from(name: str, block: Block, *, file: str, line: int) -> Card:
    """把一张牌解析成 :class:`Card`。"""
    slot = "默认层" if name == "ai_strategy_default" else "未声明"
    type_field = block.first("type")
    if type_field is not None:
        slot = _scalar_text(type_field.value) or slot

    fields = tuple(a.key for a in block.assignments() if a.key not in META_FIELDS)

    base: float | None = None
    terms = 0
    weight_triggers: list[str] = []
    weight_values: list[str] = []
    weight = block.first("weight")
    if weight is not None and isinstance(weight.value, Block):
        base = _weight_base(weight.value)
        terms = _term_count(weight.value)
        weight_triggers, weight_values = _identifiers(weight.value)

    possible_triggers: list[str] = []
    possible_values: list[str] = []
    possible = block.first("possible")
    if possible is not None and isinstance(possible.value, Block):
        possible_triggers, possible_values = _identifiers(possible.value)

    # 牌面上的其他字段同样是决策逻辑（wargoal_weights / state_value / secret_goal_scores …），
    # 只扫 weight + possible 会漏掉一半输入 —— 实测踩过。
    field_triggers: list[str] = []
    field_values: list[str] = []
    for assignment in block.assignments():
        if assignment.key in META_FIELDS or not isinstance(assignment.value, Block):
            continue
        _walk(assignment.value, field_triggers, field_values)

    return Card(
        name=name,
        slot=slot,
        file=file,
        line=line,
        weight_base=base,
        weight_terms=terms,
        has_possible=possible is not None,
        fields=fields,
        weight_inputs=tuple(sorted(set(weight_triggers) | set(weight_values))),
        possible_inputs=tuple(sorted(set(possible_triggers) | set(possible_values))),
        field_inputs=tuple(sorted(set(field_triggers) | set(field_values))),
    )


def read_cards(game: Path | None = None) -> list[Card]:
    """读取全部策略牌。"""
    root = game or config.GAME
    cards: list[Card] = []
    for path in strategy_files(root):
        parsed = parse_cached(path)
        rel = path.relative_to(root).as_posix()
        for assignment in parsed.top_assignments:
            if not assignment.key.startswith("ai_strategy_"):
                continue
            if not isinstance(assignment.value, Block):
                continue
            cards.append(
                card_from(assignment.key, assignment.value, file=rel, line=assignment.line)
            )
    return cards


def _kind_of(name: str) -> str:
    if _SCOPE_REF.search(name):
        return "scope"
    if name.startswith("ai_"):
        return "script_value"
    return "trigger"


def collect_inputs(cards: list[Card]) -> list[InputUse]:
    """汇总全部被读到的输入（按被多少张牌读到降序，同名合并）。"""
    usage: dict[str, set[str]] = {}
    for card in cards:
        for name in card.inputs:
            usage.setdefault(name, set()).add(card.name)
    rows = [
        InputUse(name=name, kind=_kind_of(name), cards=len(names), where=tuple(sorted(names)[:4]))
        for name, names in usage.items()
    ]
    rows.sort(key=lambda r: (-r.cards, r.name))
    return rows


@dataclass(frozen=True, slots=True)
class FactorHit:
    """候选因子在原版输入里的命中情况。"""

    factor: Factor
    hits: tuple[InputUse, ...]

    @property
    def verdict(self) -> str:
        if not self.hits:
            return "❌ 策略侧未读（需单独验证，或改用 A 级改世界）"
        total = sum(h.cards for h in self.hits)
        return f"✅ 可喂输入（{len(self.hits)} 个读点 / {total} 处引用）"


def factor_report(inputs: list[InputUse], factors: tuple[Factor, ...] = FACTORS) -> list[FactorHit]:
    """把候选因子对到原版输入上。"""
    out: list[FactorHit] = []
    for factor in factors:
        rx = re.compile(factor.pattern, re.IGNORECASE)
        hits = tuple(i for i in inputs if rx.search(i.name))
        out.append(FactorHit(factor=factor, hits=hits))
    return out


@dataclass(frozen=True, slots=True)
class DefinesSurface:
    """``defines/00_ai.txt`` 的面（全部键都在 ``NAI = { … }`` 块里）。"""

    nai_keys: int
    enabled_switches: tuple[str, ...]
    ai_keys: tuple[str, ...]
    notable: tuple[str, ...]
    lines: int


#: 值得单独拎出来的全局旋钮（原版注释里明确影响 AI 行为的那几个）。
NOTABLE_DEFINES = (
    "STRATEGY_RANDOM_FACTOR",
    "DEFAULT_STRATEGY_STRING",
    "AI_AGGRESSION_MAX_ACCEPTABLE_INFAMY",
)


def read_defines(game: Path | None = None) -> DefinesSurface:
    """读全局 AI 参数面。"""
    path = (game or config.GAME) / DEFINES_FILE
    parsed = parse_cached(path)
    keys: list[str] = []
    for assignment in parsed.top_assignments:
        if assignment.key == "NAI" and isinstance(assignment.value, Block):
            keys = [a.key for a in assignment.value.assignments()]
    ai_keys = tuple(k for k in keys if k.startswith("AI_"))
    switches = tuple(k for k in keys if k.endswith("_ENABLED"))
    notable = tuple(k for k in NOTABLE_DEFINES if k in keys)
    lines = path.read_text(encoding="utf-8-sig", errors="replace").count("\n") + 1
    return DefinesSurface(
        nai_keys=len(keys),
        enabled_switches=switches,
        ai_keys=ai_keys,
        notable=notable,
        lines=lines,
    )


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return out


def render(
    cards: list[Card],
    inputs: list[InputUse],
    hits: list[FactorHit],
    defines: DefinesSurface,
    *,
    top: int = 60,
) -> str:
    """渲染 ``02-可执行面.md`` 的全文。"""
    slots: dict[str, int] = {}
    for card in cards:
        slots[card.slot] = slots.get(card.slot, 0) + 1
    slot_text = "、".join(f"{k} {v} 张" for k, v in sorted(slots.items()))

    lines = [
        "# 02 · 可执行面（阶段 1 产物）",
        "",
        (
            "> ⚠️ **本文件由 `v3 ai-surface --write` 生成，勿手改** —— 要改口径请改 "
            "`tools/pdx/ai_surface.py` 后重新生成。"
        ),
        "> 人工判断（哪些因子进第一版、失败模式清单、H1 设计）写在 `exec/阶段1-结果.md`。",
        "",
        "## 0. 复算",
        "",
        "```text",
        "v3 ai-surface --write   # 重新生成本文件",
        "v3 ai-surface --check   # 核对是否与生成结果一致（退出码 1 = 已被手改）",
        "```",
        "",
        (
            f"数据来源：`game/{STRATEGY_DIR.as_posix()}/*.txt`（**{len(cards)}** 张牌）、"
            f"`game/{DEFINES_FILE.as_posix()}`。"
        ),
        "",
        "## 1. 牌面总览",
        "",
        (
            f"槽位分布：{slot_text}。"
            f"「字段数」= 牌面上除 `{', '.join(sorted(META_FIELDS))}` 以外的一级字段个数；"
            "「条件数」= 权重块里 `if` / `else_if` / `else` 的个数。"
        ),
        "",
    ]
    lines += _table(
        ["牌", "槽位", "权重基准", "条件数", "possible", "字段数", "读到的输入数", "定义位置"],
        [
            [
                f"`{c.name}`",
                c.slot,
                f"{c.weight_base:g}" if c.weight_base is not None else "—",
                str(c.weight_terms),
                "有" if c.has_possible else "—",
                str(len(c.fields)),
                str(len(c.inputs)),
                f"`{c.file}:{c.line}`",
            ]
            for c in sorted(cards, key=lambda c: (c.slot, c.name))
        ],
    )

    lines += [
        "",
        "## 2. 原版 AI 读到的输入（可喂输入清单）",
        "",
        (
            f"合计 **{len(inputs)}** 个不同输入；下表按「被几张牌读到」降序，列前 {top} 个。"
            "`kind`：`trigger` 触发器 / `script_value` 脚本值或常量引用 / `scope` 带作用域的引用。"
        ),
        "",
        (
            "> ⚠️ 判读口径：本清单是**原版牌面里出现过的全部键**，因此也含牌面结构里的**子键**"
            "（如 `score`、`who`、`conquer`、`bg_army`）与常量名（如 `STATE_VALUE_*`）—— "
            "它们不代表「可以直接喂的输入」。判定一个量能不能喂，看它在第 3 节里是否"
            "「语义上等于」我们候选因子。"
        ),
        "",
    ]
    lines += _table(
        ["输入", "kind", "被几张牌读", "示例牌"],
        [[f"`{i.name}`", i.kind, str(i.cards), "、".join(i.where)] for i in inputs[:top]],
    )

    lines += [
        "",
        "## 3. 粒度可行性表（候选因子 → 原版读点）",
        "",
        (
            "判定口径：**原版 AI 自己在 AI 上下文里读它** ⇒ 数据可驱动（B 级「喂输入」可用）；"
            "读不到 ⇒ 需单独验证，或改用 A 级（真实改变世界状态）。"
        ),
        "",
    ]
    lines += _table(
        ["候选因子", "说明", "判定", "命中的读点（示例，括号为牌数）"],
        [
            [
                h.factor.name,
                h.factor.note,
                h.verdict,
                "、".join(f"`{i.name}`({i.cards})" for i in h.hits[:6]) or "—",
            ]
            for h in hits
        ],
    )

    lines += [
        "",
        "## 4. defines 面（全局 AI 参数）",
        "",
        (
            f"`{DEFINES_FILE.as_posix()}`：**{defines.lines}** 行，全部参数都在一个 "
            f"`NAI = {{{{ … }}}}` 块里，共 **{defines.nai_keys}** 个键"
            f"（其中 `AI_*` 前缀 **{len(defines.ai_keys)}** 个）。"
        ),
        "",
        (
            "**原版子系统开关**（`*_ENABLED`，设为 `no` 即关掉对应原版 AI —— "
            f"手段阶梯的 R4，本项目封存）：共 {len(defines.enabled_switches)} 个。"
        ),
        "",
        "```text",
        *defines.enabled_switches,
        "```",
        "",
        f"**与「随机性」直接相关的全局旋钮**：{'、'.join(f'`{k}`' for k in defines.notable) or '—'}。",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def build(game: Path | None = None, *, top: int = 60) -> str:
    """读原版数据并渲染全文。"""
    cards = read_cards(game)
    inputs = collect_inputs(cards)
    hits = factor_report(inputs)
    defines = read_defines(game)
    return render(cards, inputs, hits, defines, top=top)


def write_doc(*, game: Path | None = None, repo: Path | None = None, top: int = 60) -> Path:
    """生成并写盘，返回写入路径。"""
    base = repo or config.REPO
    text = build(game, top=top)
    target = base / DOC_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
    return target


def check_doc(*, game: Path | None = None, repo: Path | None = None, top: int = 60) -> str:
    """核对文档与生成结果；一致返回空串，否则返回差异说明。"""
    base = repo or config.REPO
    target = base / DOC_PATH
    if not target.is_file():
        return f"缺少 {DOC_REL} —— 先跑 `v3 ai-surface --write`"
    current = target.read_text(encoding="utf-8")
    expected = build(game, top=top)
    if current == expected:
        return ""
    cur_lines = current.splitlines()
    exp_lines = expected.splitlines()
    for idx, (a, b) in enumerate(zip(cur_lines, exp_lines, strict=False), start=1):
        if a != b:
            return f"{DOC_REL}:{idx} 与生成结果不一致\n  文档： {a[:110]}\n  生成： {b[:110]}"
    return f"{DOC_REL}: 行数不同（文档 {len(cur_lines)} 行，生成 {len(exp_lines)} 行）"


__all__ = [
    "DOC_PATH",
    "DOC_REL",
    "FACTORS",
    "STRATEGY_DIR",
    "Card",
    "DefinesSurface",
    "Factor",
    "FactorHit",
    "InputUse",
    "build",
    "card_from",
    "check_doc",
    "collect_inputs",
    "factor_report",
    "read_cards",
    "read_defines",
    "render",
    "strategy_files",
    "write_doc",
]
