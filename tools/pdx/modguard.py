"""五道闸门（阶段 3 并行轨的第二步）。

为什么闸门必须先于产物落地
--------------------------
冻结文档 §5 写着「每次生成后：闸门 ① 键/路径不相交、② 引用完整性、
⑤ 生成可复现 + `why` 非空 —— 不许提交」，「每个阶段结束：③ 稀释预算、
④ 往返净度」。这些检查如果晚于第一份产物出现，就永远补不上了：产物一旦进过
游戏，出问题的那个版本已经没人记得。

五道闸门（每道都能单独跑，失败即非零退出）
------------------------------------------
====  ============  ==========================================================
①     ``keys``      键/路径与原版不相交（含 F7 命名空间与平铺）
②     ``refs``      引用完整性（变量 / JE / 修正 / 图标 / 本地化键 / defines 参数）
③     ``dilution``  稀释预算（按阶段 2 的三槽价格表给递牌定价）
④     ``roundtrip`` 往返净度（生成 → 解析回来 → 与数据源逐条比对）
⑤     ``determin``  生成可复现 + `why` 非空 + 盘上产物确实由生成器产出
====  ============  ==========================================================

口径
----
* **每道闸门都要能回答"过/不过 + 关键数字"**：结论是一句话，明细是可数的条目，
  不是"看起来没问题"；
* **缺前置条件不等于通过**（P13）：原版目录不可用时 ①/② 报"前置条件缺失"
  （退出码 2），而不是静默跳过 —— 跳过会被当成绿灯；
* **③ 的价格表来自阶段 2 实测**（`exec/阶段2-结果.md`：政治 S≈33 / 外交 S≈107 /
  行政 S≈690），不在这里重新拟合：换版本要重跑探针，而不是在这里改数字。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pdx import config, defines, modgen
from pdx.cache import parse_cached
from pdx.model import Block

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

#: 三槽的等效竞争权重（阶段 2 实测，`01a` N 节）。
#:
#: 语义：同槽其它牌加起来等效多少权重。``p = W / (W + S)`` 是我们这张牌的份额。
SLOT_PRICE: dict[str, float] = {"political": 33.0, "diplomatic": 107.0, "administrative": 690.0}

#: 稀释预算：门开时，我们**全部**牌在同一个槽里最多占多少份额。
#:
#: 0.6 的理由：超过六成就等于我们替原版做决定，而目标是「原版 + 我们 > 原版」
#: ——原版自己的牌必须还有发言权（F2：不替换、不并行第二套 AI）。
#: 反过来，低于三成则喂进去的处境推不动落点（阶段 2：权重 10 在政治槽只占 23%，
#: 而 23% 已经能看出剂量反应，但不足以稳拿）。所以区间是 [0.3, 0.6]，
#: 这里只硬性卡上界；下界由行为质量定（阶段 4）。
MAX_CARD_SHARE = 0.60

#: **登记在案**的键覆盖：这些键名与原版相同是**故意的**，因为「按块 + 参数覆盖」
#: 正是我们改原版全局参数的唯一合法方式（KB 05 §1.7，阶段 2 storm 变体实测生效）。
#: 例外必须逐条写明理由 —— 否则闸门 ① 的"不相交"就成了一句空话。
OVERRIDE_BLOCKS: dict[str, str] = {
    "NAI": "阶段 2 实测：独立小文件按「块 + 参数」覆盖原版 defines（exec/阶段2-结果.md 发现 4）。"
    "只覆盖明列的键，不复制原版 00_ai.txt；键名是否存在由闸门 ② 逐条核对（原版改名后这里必须跟着改）。",
}

#: 闸门编号 → (键, 标题)。编号进 CLI 的 `--only`，键进代码与文档。
GATES: tuple[tuple[str, str, str], ...] = (
    ("1", "keys", "① 键 / 路径与原版不相交（含 F7 命名空间与平铺）"),
    ("2", "refs", "② 引用完整性（变量 / JE / 修正 / 图标 / 本地化键 / defines 参数）"),
    ("3", "dilution", "③ 稀释预算（按阶段 2 的三槽价格表定价）"),
    ("4", "roundtrip", "④ 往返净度（生成 → 解析回来 → 与数据源一致）"),
    ("5", "determinism", "⑤ 生成可复现 + why 非空 + 盘上产物确实由生成器产出"),
)

#: 我们的产物里，哪些"定义"要拿去和原版比键名。值是原版目录（相对 `game/`）。
DEFINITION_DIRS: dict[str, str] = {
    "effects": "common/scripted_effects",
    "modifier": "common/static_modifiers",
    "journal_entry": "common/journal_entries",
    "card": "common/ai_strategies",
    "defines": "common/defines",
}

#: 闸门 ② 的"原版词汇表"扫描目录：触发器 / 效果这类名字从形状上认不出来，
#: 只能看它在原版里有没有被用过。
VOCABULARY_DIRS: tuple[str, ...] = (
    "common/journal_entries",
    "common/scripted_effects",
    "common/scripted_triggers",
    "common/on_actions",
)

#: 闸门 ② 认得的引用类别 → 该类别去哪里找。
REFERENCE_KINDS: dict[str, str] = {
    "trigger": "原版触发器名（在 journal_entries / scripted_triggers / on_actions 里出现过）",
    "effect": "原版效果名（在 scripted_effects / journal_entries 里出现过）",
    "country_tag": "国家 tag（country_definitions 里的顶层键）",
}


@dataclass(frozen=True, slots=True)
class Finding:
    """一道闸门的结论。"""

    gate: str
    title: str
    ok: bool
    #: 一句话结论（含关键数字）—— 「过」也要说清过在哪。
    headline: str
    #: 明细（每行一条可数的事实；失败时是可执行的修法）。
    details: tuple[str, ...] = ()
    #: 前置条件缺失（没有游戏 / 没有产物）：CLI 按退出码 2 处理，不是"通过"。
    precondition: bool = False


@dataclass(frozen=True, slots=True)
class Context:
    """一次闸门运行的输入。"""

    archives: tuple[modgen.Archive, ...]
    built: modgen.Built
    root: Path
    game: Path
    data_dir: Path

    @property
    def has_game(self) -> bool:
        return (self.game / "common").is_dir()


@dataclass(frozen=True, slots=True)
class Report:
    """五道闸门的汇总。"""

    findings: tuple[Finding, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return all(f.ok for f in self.findings)

    @property
    def missing_precondition(self) -> bool:
        return any(f.precondition for f in self.findings)


def context(
    *,
    data_dir: Path | None = None,
    root: Path | None = None,
    game: Path | None = None,
) -> Context:
    """读数据源并编译一次，供各道闸门共用（避免每道闸门各读一遍）。"""
    base = data_dir or modgen.DATA_DIR
    archives = modgen.load_all(base)
    return Context(
        archives=archives,
        built=modgen.build_all(archives),
        root=root or modgen.PRODUCT_DIR,
        game=game or config.GAME,
        data_dir=base,
    )


# ── 原版侧的小工具 ──────────────────────────────────────────
def vanilla_keys(directory: Path) -> set[str]:
    """某个原版目录下全部 `.txt` 的**顶层键**（用仓库自己的解析器，带缓存）。"""
    if not directory.is_dir():
        return set()
    out: set[str] = set()
    for path in sorted(directory.rglob("*.txt")):
        out.update(parse_cached(path).top_keys)
    return out


def _vanilla_vocabulary(game: Path) -> set[str]:
    """原版脚本里出现过的**全部键名**（任意深度）—— 触发器/效果词汇表。

    刻意做浅（只收键名，不问语义）：这份表的用途是回答"这个名字在原版里存在吗"，
    而"语法是否合法"要进游戏才知道（doc 04 §13 的四条配方）。
    """
    out: set[str] = set()
    for rel in VOCABULARY_DIRS:
        base = game / rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.txt")):
            stack: list[Block] = [parse_cached(path).root]
            while stack:
                block = stack.pop()
                for item in block.assignments():
                    out.add(item.key)
                    if isinstance(item.value, Block):
                        stack.append(item.value)
    return out


def definition_names(files: Mapping[str, str]) -> dict[str, set[str]]:
    """从产物文本里抽出**我们定义了什么键**：``类别 → 名字集合``。

    口径：键名来自 :func:`modgen.readback` 的事实表（它按 PDX 语法解析产物），
    不是回放生成器拼的字符串。
    """
    out: dict[str, set[str]] = {kind: set() for kind in DEFINITION_DIRS}
    for path, _value in modgen.readback(files):
        head, _, rest = path.partition(".")
        if head in out and rest:
            out[head].add(rest.split(".", 1)[0])
    return out


def loc_keys(files: Mapping[str, str]) -> dict[str, set[str]]:
    """产物里各语言的本地化键。"""
    out: dict[str, set[str]] = {}
    for rel, text in files.items():
        parts = rel.split("/")
        if len(parts) == 3 and parts[0] == "localization":
            out[parts[1]] = set(modgen.parse_loc_text(text))
    return out


def _facts_map(files: Mapping[str, str]) -> dict[str, str]:
    return dict(modgen.readback(files))


def _ref_name(value: str) -> str:
    """判据事实值 → 被引用的名字。

    事实表里判据写成 ``op + 操作数``（``=sitai_x`` / ``<=50``），因为往返比对
    需要区分 ``=`` 与 ``?=``；这里取名字时把默认的 ``=`` 剥掉即可。
    """
    return value.removeprefix("=")


def _fail(gate: str, title: str, headline: str, details: Sequence[str]) -> Finding:
    return Finding(gate=gate, title=title, ok=False, headline=headline, details=tuple(details))


def _pass(gate: str, title: str, headline: str, details: Sequence[str] = ()) -> Finding:
    return Finding(gate=gate, title=title, ok=True, headline=headline, details=tuple(details))


# ── ① 键 / 路径与原版不相交 ─────────────────────────────────
def gate_keys(ctx: Context) -> Finding:
    """① 我们写下的每一个键与路径，原版里都不能有。

    三件事一起查（都是 F7 的同一句话）：
    * **路径不相交**：`game/<我们的相对路径>` 不能存在（存在就是覆盖了原版文件）；
    * **键不相交**：同名类别（effects / modifier / journal_entry / card / defines 块）
      与原版顶层键取交集，交集必须为空 —— 除非登记在 :data:`OVERRIDE_BLOCKS`；
    * **命名空间与平铺**：文件名 `sitai_*`、深度恰好是"原版目录 + 文件名"，
      不自建子目录（1.14.3 实测子目录不被引擎枚举）。
    """
    _, key, title = GATES[0]
    if not ctx.has_game:
        return Finding(
            gate=key,
            title=title,
            ok=False,
            headline=f"前置条件缺失：找不到原版目录 {ctx.game}（可用环境变量 V3_ROOT 指定）",
            precondition=True,
        )

    problems: list[str] = []
    notes: list[str] = []

    # ── 路径（含平铺与命名空间）──
    # 游戏侧文件（.txt / .yml）必须落在「原版目录 + 文件名」两层里；文档（.md）
    # 与元数据（.metadata/*.json）不进游戏目录树，只查命名空间 —— 它们放哪都
    # 不会被引擎读，硬套平铺规则只会制造假红。
    game_side = [rel for rel in ctx.built.paths if rel.endswith(modgen.GAME_SIDE_SUFFIXES)]
    loose = [rel for rel in ctx.built.paths if rel not in game_side and rel != modgen.METADATA_REL]
    for rel in [*game_side, *loose]:
        name = rel.rsplit("/", 1)[-1]
        if not name.startswith(modgen.FILE_PREFIX):
            problems.append(f"文件名不在 sitai_* 命名空间：{rel}（F7）")
    for rel in game_side:
        if len(rel.split("/")) != 3:
            problems.append(f"不是「原版目录 + 文件名」两层的平铺结构：{rel}（F7：不自建子目录）")
        if (ctx.game / rel).exists():
            problems.append(f"路径与原版相撞：game/{rel} 已存在")
    notes.append(
        f"产物 {len(ctx.built.paths)} 个：游戏侧 {len(game_side)} 个（两层平铺）、"
        f"文档与元数据 {len(loose) + 1} 个"
    )

    # ── 键 ──
    ours = definition_names(ctx.built.files)
    overrides: list[str] = []
    for kind, names in sorted(ours.items()):
        clash = names & vanilla_keys(ctx.game / DEFINITION_DIRS[kind])
        allowed = {n for n in clash if n in OVERRIDE_BLOCKS}
        problems.extend(
            f"{kind} 键与原版重名：{name}（原版 {DEFINITION_DIRS[kind]} 里已有）"
            for name in sorted(clash - allowed)
        )
        overrides.extend(f"{kind} {name}：{OVERRIDE_BLOCKS[name]}" for name in sorted(allowed))
        notes.append(
            f"{kind}：我们 {len(names)} 个键，与原版交集 {len(clash)} 个（登记覆盖 {len(allowed)} 个）"
        )

    details = [*notes, *[f"❌ {p}" for p in problems]]
    details.extend(f"ℹ️ 登记在案的覆盖：{o}" for o in overrides)
    if problems:
        return _fail(key, title, f"{len(problems)} 处与原版相交（不许进游戏）", details)
    return _pass(key, title, "路径、键、命名空间、平铺四项全过：与原版零交集", details)


# ── ② 引用完整性 ────────────────────────────────────────────
def gate_refs(ctx: Context) -> Finding:
    """② 我们引用的每个名字都必须存在（自家产物内 + 原版内）。

    分两类：
    * **带名字的引用**（变量 / 修正 / JE / 图标 / 本地化键 / defines 参数）——
      从产物里自动抽出来，逐个解析；
    * **形状上认不出来的引用**（`legitimacy`、`set_variable` 这类原版词汇）——
      由数据源的 `[[references]]` 逐条声明，这里拿原版语料核对。
    """
    _, key, title = GATES[1]
    if not ctx.has_game:
        return Finding(
            gate=key,
            title=title,
            ok=False,
            headline=f"前置条件缺失：找不到原版目录 {ctx.game}（可用环境变量 V3_ROOT 指定）",
            precondition=True,
        )

    problems: list[str] = []
    notes: list[str] = []
    facts = _facts_map(ctx.built.files)
    ours = definition_names(ctx.built.files)
    langs = loc_keys(ctx.built.files)

    # ① 我们定义了什么（自家产物内自洽）
    variables = {facts[path] for path in facts if path.endswith(".set_variable.name")}
    used_variables = {
        _ref_name(value) for path, value in facts.items() if path.endswith(".has_variable")
    }
    missing_var = sorted(used_variables - variables)
    problems.extend(f"引用了一个我们从未写下的变量：{name}" for name in missing_var)
    notes.append(f"变量：定义 {len(variables)} 个，被判据引用 {len(used_variables)} 个")

    # ② 修正 / JE / 组：自家 ∪ 原版
    modifier_refs = {facts[path] for path in facts if path.endswith(".add_modifier.name")}
    vanilla_modifiers = vanilla_keys(ctx.game / DEFINITION_DIRS["modifier"])
    problems.extend(
        f"引用了不存在的静态修正：{name}（自家产物与原版 static_modifiers 里都没有）"
        for name in sorted(modifier_refs - ours["modifier"] - vanilla_modifiers)
    )
    groups = {value for path, value in facts.items() if path.endswith(".group")}
    vanilla_groups = vanilla_keys(ctx.game / "common/journal_entry_groups")
    problems.extend(f"引用了不存在的 JE 分组：{name}" for name in sorted(groups - vanilla_groups))
    notes.append(
        f"修正：引用 {len(modifier_refs)} 个（原版池 {len(vanilla_modifiers)} 个）；"
        f"JE 分组：引用 {len(groups)} 个（原版 {len(vanilla_groups)} 个）"
    )

    # ③ 递牌引用的 JE 必须存在（本档案为空，但闸门要能回答"加了牌之后呢"）
    je_refs = {
        _ref_name(value) for path, value in facts.items() if path.endswith(".has_journal_entry")
    }
    ours_je = ours["journal_entry"] | vanilla_keys(ctx.game / DEFINITION_DIRS["journal_entry"])
    problems.extend(f"牌引用了一个不存在的 JE：{name}" for name in sorted(je_refs - ours_je))

    # ④ 图标：路径必须在自家产物或原版里真实存在
    icons = {facts[path] for path in facts if path.endswith(".icon")}
    problems.extend(
        f"引用了不存在的图标：{icon}"
        for icon in sorted(icons)
        if not ((ctx.root / icon).is_file() or (ctx.game / icon).is_file())
    )
    notes.append(f"图标：引用 {len(icons)} 个（全部落到真实文件）")

    # ⑤ defines 参数：键名必须在原版的同一个块里存在（阶段 2 的教训：改名即静默失效）
    report = defines.extract_defines(ctx.game / "common" / "defines")
    checked = 0
    for path in sorted(facts):
        parts = path.split(".")
        if len(parts) != 3 or parts[0] != "defines":
            continue
        block_name, param = parts[1], parts[2]
        names = {p.name for ns in report.get(block_name) for p in ns.params}
        checked += 1
        if param not in names:
            problems.append(
                f"defines 参数不存在：{block_name}.{param}（原版 {block_name} 块里没有这个名字，"
                "属于死配置 —— 阶段 2 的实测教训是「每版本核对键名」）"
            )
    notes.append(f"defines 参数：核对 {checked} 个（原版 {len(report.namespaces)} 个命名空间块）")

    # ⑥ 本地化：JE 与修正都必须有文案，且每种语言都要有
    needed = set(ours["journal_entry"]) | ours["modifier"]
    for lang, keys in sorted(langs.items()):
        problems.extend(f"{lang} 缺本地化键：{name}" for name in sorted(needed - keys))
    notes.append(
        "本地化：" + "、".join(f"{lang} {len(keys)} 键" for lang, keys in sorted(langs.items()))
    )

    # ⑦ 声明式引用：原版词汇表
    vocabulary = _vanilla_vocabulary(ctx.game)
    tags = vanilla_keys(ctx.game / "common" / "country_definitions")
    declared = 0
    for archive in ctx.archives:
        for ref in archive.references:
            declared += 1
            if ref.kind not in REFERENCE_KINDS:
                problems.append(
                    f"不认识的引用类别 {ref.kind!r}（{ref.name}）—— 可用：{sorted(REFERENCE_KINDS)}"
                )
                continue
            pool = tags if ref.kind == "country_tag" else vocabulary
            if ref.name not in pool:
                problems.append(
                    f"原版里找不到这个{REFERENCE_KINDS[ref.kind].split('（')[0]}：{ref.name}"
                    f"（数据源 references 里声明的）"
                )
    notes.append(
        f"声明式引用：核对 {declared} 条（原版词汇表 {len(vocabulary)} 个键、国家 tag {len(tags)} 个）"
    )

    details = [*notes, *[f"❌ {p}" for p in problems]]
    if problems:
        return _fail(key, title, f"{len(problems)} 处引用解析不到（缺引用即红）", details)
    return _pass(key, title, f"引用全部解析得到：{len(notes)} 类逐个核过，零缺失", details)


# ── ③ 稀释预算 ──────────────────────────────────────────────
def card_share(weight: float, slot: str) -> float:
    """我们一张牌在某个槽里的份额：``W / (W + S)``，S 取阶段 2 的价格表。"""
    price = SLOT_PRICE.get(slot)
    if price is None:
        raise KeyError(slot)
    return weight / (weight + price)


def gate_dilution(ctx: Context) -> Finding:
    """③ 递牌要吃多少份额 —— 用阶段 2 的价格表算，超预算即红。

    两条判据：
    * **份额上界**：门开时我们全部牌在同一槽里 ≤ :data:`MAX_CARD_SHARE`；
    * **必须带 `possible` 门**：没有门的牌在和平期也参与抽签，
      而出口判据是「和平期占槽率 ≈ 0」—— 无门就不可能满足。

    本档案 0 张牌（F5：A 级已表达）→ 占用 0%，两条判据都由构造成立。
    """
    _, key, title = GATES[2]
    problems: list[str] = []
    details: list[str] = []
    cards = [card for archive in ctx.archives for card in archive.cards]
    per_slot: dict[str, float] = {}
    for card in cards:
        if card.slot not in SLOT_PRICE:
            problems.append(
                f"{card.name} 的槽位 {card.slot!r} 不在价格表里（可用：{sorted(SLOT_PRICE)}）"
            )
            continue
        share = card_share(card.weight, card.slot)
        per_slot[card.slot] = per_slot.get(card.slot, 0.0) + share
        ceiling = MAX_CARD_SHARE * SLOT_PRICE[card.slot] / (1 - MAX_CARD_SHARE)
        details.append(
            f"{card.name}（{card.slot}）：权重 {modgen.num(card.weight)} / 价格 "
            f"{modgen.num(SLOT_PRICE[card.slot])} → 门开时占 {share:.1%}"
            f"（该槽的权重上限 ≈{ceiling:.0f}）"
        )
        if share > MAX_CARD_SHARE:
            problems.append(
                f"{card.name} 占 {card.slot} 槽 {share:.1%} > 预算 {MAX_CARD_SHARE:.0%}"
                f" —— 降到权重 {ceiling:.0f} 以下，或收窄 possible"
            )
        if not card.possible:
            problems.append(
                f"{card.name} 没有 possible 门 —— 和平期也会被抽中，"
                "与出口判据「和平期占槽率 ≈ 0」直接冲突（加门，或改走 A 级）"
            )
    for slot, total in sorted(per_slot.items()):
        details.append(f"{slot} 槽合计占用 {total:.1%}（预算 {MAX_CARD_SHARE:.0%}）")
        if total > MAX_CARD_SHARE:
            problems.append(f"{slot} 槽合计占用 {total:.1%} 超预算")
    if not cards:
        details.append(
            "本档案 0 张牌：A 级（变量 + 修正 + JE）已经表达完整条链路，"
            "递牌要等「整条路线要换」的处境（F5）—— 和平期占槽率 ≈0 由构造保证"
        )
    headline = (
        f"{len(cards)} 张牌，各槽占用 "
        + ("、".join(f"{slot} {total:.1%}" for slot, total in sorted(per_slot.items())) or "0.0%")
        + f"（预算 {MAX_CARD_SHARE:.0%}）"
    )
    if problems:
        return _fail(key, title, f"{headline} —— {len(problems)} 处超预算", [*details, *problems])
    return _pass(key, title, headline, details)


# ── ④ 往返净度 ──────────────────────────────────────────────
def gate_roundtrip(ctx: Context) -> Finding:
    """④ 生成 → 按 PDX 语法解析回来 → 与数据源逐条比对（无丢失字段）。"""
    _, key, title = GATES[3]
    try:
        back = modgen.readback(ctx.built.files)
    except modgen.DataError as exc:
        return _fail(key, title, "产物解析失败（生成物语法有错）", [str(exc)])

    details: list[str] = []
    problems: list[str] = []
    for archive in ctx.archives:
        want = modgen.facts(archive)
        missing = [item for item in want if item not in back]
        extra = [item for item in back if item not in want]
        details.append(
            f"{archive.id}：数据源 {len(want)} 条事实 / 产物反解 {len(back)} 条，"
            f"缺 {len(missing)}、多 {len(extra)}"
        )
        problems.extend(f"{archive.id} 产物里读不到：{path} = {value}" for path, value in missing)
        problems.extend(
            f"{archive.id} 产物里多出数据源没写的：{path} = {value}" for path, value in extra
        )

    if problems:
        return _fail(key, title, f"{len(problems)} 条事实在往返中丢失或多出", [*details, *problems])
    return _pass(key, title, "数据源与产物逐条一致：无丢失字段、无多余字段", details)


# ── ⑤ 生成可复现 + why 非空 ─────────────────────────────────
def gate_determinism(ctx: Context) -> Finding:
    """⑤ 两次生成逐字节一致；每个数字都有 `why`；盘上产物确实由生成器产出。"""
    _, key, title = GATES[4]
    problems: list[str] = []
    details: list[str] = []

    # ① 两次生成（重新读一遍数据源再编译 —— 只比同一个对象不算数）
    first = ctx.built
    second: modgen.Built | None
    try:
        second = modgen.build_all(modgen.load_all(ctx.data_dir))
    except modgen.DataError as exc:
        # 数据源在 context() 之后被改坏（编辑器保存、另一个进程重写）：
        # 这是闸门 ⑤ 必须抓到的情形之一，不能让它把整道闸门掀掉。
        second = None
        problems.append(f"重新编译失败：{exc}")
    same = second is not None and first.files == second.files
    details.append(
        f"两次生成：{len(first.files)} 个产物，"
        + ("逐字节一致" if same else "**不一致**（确定性被破坏）")
    )
    if second is not None and not same:
        problems.extend(
            f"两次生成不一致：{rel}"
            for rel in sorted(set(first.files) | set(second.files))
            if first.files.get(rel) != second.files.get(rel)
        )

    # ② why 非空（重新审计原始数据源：闸门不信任已经过一遍校验的对象）
    checked = 0
    for path in modgen.data_files(ctx.data_dir):
        try:
            numbers, whys = modgen.audit(modgen.read_source(path))
        except modgen.DataError as exc:
            problems.append(f"{path.name}：{exc}")
            continue
        checked += len(numbers)
        details.append(f"{path.name}：{len(numbers)} 个数字、{len(whys)} 张表，why 全部非空")
    details.append(f"带依据的数字合计 {checked} 个（`v3 modgen --why` 可逐条展开）")

    # ③ 盘上产物 = 生成结果（手改 / 陈旧 / 多余都会被点名）
    drift = modgen.check(first, ctx.root)
    details.append(
        f"盘上产物：{len(first.files)} 个，"
        + ("与生成结果一致" if not drift else f"{len(drift)} 处不一致")
    )
    problems.extend(drift)

    if problems:
        return _fail(
            key,
            title,
            f"{len(problems)} 处不满足（可复现 / why / 盘上一致）",
            [*details, *problems],
        )
    return _pass(key, title, "两次生成逐字节一致、why 全非空、盘上产物与生成结果一致", details)


#: 闸门键 → 函数（顺序即执行顺序）。
RUNNERS = {
    "keys": gate_keys,
    "refs": gate_refs,
    "dilution": gate_dilution,
    "roundtrip": gate_roundtrip,
    "determinism": gate_determinism,
}


def resolve(only: str) -> tuple[str, ...]:
    """把 `--only` 的值解析成闸门键（支持编号 `1`、键 `keys`、标题子串）。

    匹配分两级：**先**编号/键名精确匹配，**再**退到标题子串。分两级是必须的 ——
    标题里会出现别的闸门的编号（③ 的标题写着「按阶段 2 的价格表定价」），
    单级子串匹配会让 `--only 2` 同时命中 refs 与 dilution，跑出两道闸门却不报错。

    解析不到时返回空元组 —— 由调用方报错：**拼错一个字母就"全部通过"
    是这类门禁最容易骗过 CI 的失效方式**（`v3 verify --only` 也有同样的纪律）。
    """
    text = only.strip()
    if not text:
        return tuple(key for _number, key, _title in GATES)
    picked = [key for number, key, _title in GATES if text in (number, key)]
    if not picked:
        picked = [key for _number, key, title in GATES if text in title]
    return tuple(dict.fromkeys(picked))


def run(ctx: Context, only: str = "") -> Report:
    """跑（选中的）闸门。"""
    keys = resolve(only)
    if not keys:
        raise ValueError(
            f"没有匹配的闸门：{only!r}（可用：{[k for _n, k, _t in GATES]} 或编号 1–5）"
        )
    return Report(findings=tuple(RUNNERS[key](ctx) for key in keys))


def format_report(report: Report) -> str:
    """把结论排成人读的 markdown（rich 会渲染成表）。"""
    lines = ["| | 闸门 | 结论 |", "|---|---|---|"]
    lines.extend(
        f"| {'✅' if f.ok else ('⚠️' if f.precondition else '❌')} | {f.title} | {f.headline} |"
        for f in report.findings
    )
    for finding in report.findings:
        if finding.ok or not finding.details:
            continue
        lines += ["", f"**{finding.title} —— 明细**", ""]
        lines += [f"* {line}" for line in finding.details]
    lines += ["", "**总判定**：" + ("五道闸门全过 ✅" if report.ok else "未通过 ❌（不许进游戏）")]
    return "\n".join(lines)


__all__ = [
    "DEFINITION_DIRS",
    "GATES",
    "MAX_CARD_SHARE",
    "OVERRIDE_BLOCKS",
    "REFERENCE_KINDS",
    "RUNNERS",
    "SLOT_PRICE",
    "VOCABULARY_DIRS",
    "Context",
    "Finding",
    "Report",
    "card_share",
    "context",
    "definition_names",
    "format_report",
    "gate_determinism",
    "gate_dilution",
    "gate_keys",
    "gate_refs",
    "gate_roundtrip",
    "loc_keys",
    "resolve",
    "run",
    "vanilla_keys",
]
