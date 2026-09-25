"""探针产物的**引用体检**：它引用的每个外部名字是否真的存在。

为什么值得单独一个模块：探针是**一次性实机实验**的载体 —— 起游戏到选国家界面实测约 137 秒，
跑满 66 个游戏月是分钟级，而**一个拼错的引用不会让探针崩**：

* 拼错效果名 ⇒ 引擎记一条 `Unknown effect`，那一格读数**静默为空**（看起来像"没发生"）；
* 拼错 `law_type:` ⇒ 那条 `LAW` 行永远不出现，"法没换"与"没记"分不清；
* 拼错 data function ⇒ `debug_log` 把那串 `[...]` **原样**打出来（`0.248` 那种假读数就是这么来的）。

这三类都是**开局前可查**的 —— 名字在不在原版/本仓库里，读文件就知道，不需要引擎。
闸门 ①② 对**我们自己的 mod** 已经做了这件事（`pdx.modguard`），但**探针不是 modgen 的产物**
（它由 `pdx.ab_probe` / `pdx.h1_probe` 生成、单独部署），所以它一直没被这套判据覆盖。
本模块把那份"引用完整性"的判据补到探针上。

两条纪律（都是被真实误报逼出来的）：

* **只看代码，不看注释** —— 探针的注释里**故意**举原版例子，其中包含**反例**
  （`h1_probe` 的注释里就有「`[This.GetTag]` 不是合法命令」这句）；
  拿注释去校验，第一天就会红一片，然后人就会把它关掉。
* **只查形状能认出来的那些类别** —— 触发器/效果的词汇表太宽（生成物里几百个裸键），
  查它只会制造噪声。这里只查"我们自己的前缀 + 四种有明确落点的名字"。

除了"引用得到吗"，本模块还管**形状**（2026-09-25 加：一次白烧的实机窗口换来的）。
两类语法错误引擎**只记一行日志**、脚本侧毫无感觉，而它们在开局前读文件就能判：

* **on_action 块里直接写脚本效果调用** ⇒ 整份文件被拒
  （`Unexpected token: zz_stress_tick, near line: 6`），症状是**钩子一次都没挂上**
  （那一局 0 行自报）；
* **`if = {` 之后少了 `limit = {`** ⇒ 引擎把里面那几行当**效果**读
  （实测 8 行 `Unknown effect c:GBR`），读数静默为空；
* **`limit = { … }` 里平铺了几条作用域比较**（`c:GBR ?= this` + `c:RUS ?= this` …）⇒
  `limit` 是**与**（AND）、两个不同国家不可能同时是当前国 ⇒ 整段恒假、一次都不执行，
  **而引擎一行日志都不报**（2026-09-25 03:33 实测：四波 32 行自报与
  `add_radicals_in_state` 全没发生，`error.log` 里提到我们文件的行数是 0）。
  这是三条里唯一**完全安静**的一条。

判据一律**机械推导**，不手抄白名单：

* 规则①的合法键 = 现扫 `game/common/on_actions/*.txt` 得到的**深度 1 键** ∪ 官方
  `_on_actions.md` 的结构成员（原版恰好没用到的官方成员**必须判过** —— 判据比引擎严，
  误报的代价是这套体检被关掉，比漏判更坏）；
* 规则②的不变式在**原版**上成立：`on_actions` 393 个 + `scripted_effects` 1540 个
  `if = {`，违规 0（`scripted_triggers` 0 个）。取证口径见
  `tools/tests/test_probe_lint.py::TestShapeRules`。
* 规则③的两种**合法**形状（`OR = { … }` 包着、或每个 tag 一个独立 `if`）与两种非法形状
  （平铺进一个 `limit`；`c:TAG ?= this` 直接跟在 `if = {` 后面）都有用例；
  阴性对照用的是**归档的真产物**（`config.USERDIR/v3probe-logs-archive/t73-改前产物-F2语义-0334/`，
  9,148 B / 带 BOM / sha256[:16] `eae08b05ae437c46`），不现造样本。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pdx import config, vanilla_index
from pdx.cache import parse_cached
from pdx.model import Assignment, Block
from pdx.parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

#: 我们自己会定义的名字前缀（探针与真 mod）。
OUR_PREFIXES = ("zz_probe_", "sitai_")

#: 引擎侧的名字池：这些类别都要在**原版**里有定义/用法。
LAW_DIR = ("common", "laws")
STRATEGY_DIR = ("common", "ai_strategies")
IG_DIR = ("common", "interest_groups")

#: 注释行（``#`` 开头）整行丢掉 —— 见模块开头第二条纪律。
_COMMENT_LINE = re.compile(r"^\s*#")

#: 我们自己前缀的**效果调用**：``name = yes`` 或 ``name = {``。
_OUR_CALL = re.compile(
    rf"^\s*((?:{'|'.join(OUR_PREFIXES)})[A-Za-z0-9_]*)\s*=\s*(?:yes|\{{)", re.MULTILINE
)
_JE_USE = re.compile(r"has_journal_entry\s*=\s*([A-Za-z0-9_]+)")
_LAW_USE = re.compile(r"law_type:([A-Za-z0-9_]+)")
_STRATEGY_USE = re.compile(r"has_strategy\s*=\s*([A-Za-z0-9_]+)")
_IG_USE = re.compile(r"\big:([A-Za-z0-9_]+)")
#: ``debug_log`` 行里的 data function 链：``[THIS.GetCountry.GetNameNoFormatting]``。
_DATA_FN = re.compile(r"debug_log\s*=\s*\"([^\"]*)\"")
_DATA_FN_CALL = re.compile(r"\[([A-Za-z][A-Za-z0-9_.']*?)(?:\|[^\]]*)?\]")
#: 定义（我们自己产出的）：``name = {`` 出现在文件行首层级。
_DEFINITION = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\{", re.MULTILINE)

#: `on_action` 产物的目录（规则①只对这个目录下的生成物生效）。
ON_ACTION_DIR = ("common", "on_actions")
_ON_ACTION_PREFIX = "/".join(ON_ACTION_DIR) + "/"

#: 官方 `_on_actions.md` 的结构成员，**逐字**抄自本仓的官方文档镜像
#: （`docs/victoria3-modding/07-官方文档索引.md:289`；`04-脚本系统.md` §3.3 是同一份清单）。
#:
#: 为什么规则①取「原版用到的键 ∪ 这 10 个」而不是只取原版用到的 5 个：官方支持的写法里有
#: 几个**原版恰好一次都没用**（`weight_multiplier` / `first_valid` / `random_on_actions` /
#: `first_valid_on_action` / `fallback`）。判据比引擎严的后果是把**官方支持的写法判红**，
#: 而误报的代价是这套体检被关掉（见模块开头第二条纪律）—— 比漏判更坏。
ON_ACTION_OFFICIAL_MEMBERS: frozenset[str] = frozenset(
    {
        "trigger",
        "weight_multiplier",
        "events",
        "random_events",
        "first_valid",
        "on_actions",
        "random_on_actions",
        "first_valid_on_action",
        "effect",
        "fallback",
    }
)

#: 生成物里 `if = {` 的开口。⚠️ `(?<![A-Za-z0-9_])` 让 `else_if` **不算**（`_` 不是词边界）：
#: 本卡的判据只覆盖官方文档逐字讲的那一条（`if`），`else_if` 的口径未取数，不在这里顺手判。
_IF_OPEN = re.compile(r"(?<![A-Za-z0-9_])if\s*=\s*\{")
#: `if = {` 之后（可以过空白）允许出现的第一条语句。
_LIMIT_OPEN = re.compile(r"\s*limit\s*=\s*\{")

#: **作用域比较**的两种写法都认：`c:GBR ?= this`（设计器在左）与 `this ?= s:STATE_X`（在右）。
_SCOPE_COMPARISON = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):([A-Za-z0-9_.]+)$")
#: 变量前缀**不算**作用域比较：`var:a ?= 1` 与 `var:b ?= 2` 可以同时为真，
#: 平铺在一个 `limit` 里是**合法的与**，判它红就是误报（误报的代价是这套体检被关掉）。
#: 原版实测（`common/{scripted_effects,scripted_triggers,on_actions,journal_entries}` 的 `?=`
#: 左侧前缀计数）：`c` 1611 / `scope` 518 / `s` 287 / `cu` 188 / `ig` 150 / `je` 132 /
#: `law_type` 88 / `var` 56 / `active_law` 19 / `mg` 11 / `global_var` 3 / `region_state` 3 /
#: `p` 2 —— 只把 `var` / `global_var` 这类**变量**前缀排除在外。
_VARIABLE_PREFIXES: frozenset[str] = frozenset({"var", "local_var", "global_var"})


@dataclass(frozen=True, slots=True)
class Issue:
    """一条引用体检结论。``ok=False`` 时 ``hint`` 说清怎么修。"""

    kind: str
    name: str
    ok: bool
    detail: str = ""
    hint: str = ""

    def describe(self) -> str:
        mark = "✅" if self.ok else "❌"
        tail = f"   → {self.hint}" if (self.hint and not self.ok) else ""
        return f"{mark} {self.kind} {self.name}：{self.detail}{tail}"


def code_only(text: str) -> str:
    """去掉整行注释与行尾注释（引号内的 ``#`` 不算注释起点）。

    ⚠️ 探针的注释里**故意**写了反例（例如「`[This.GetTag]` 不是合法命令」），
    所以"注释也一起查"必然误报 —— 而误报的代价是这套体检被关掉。
    """
    out: list[str] = []
    for line in text.splitlines():
        if _COMMENT_LINE.match(line):
            continue
        cut = len(line)
        quote = ""
        for index, char in enumerate(line):
            if quote:
                if char == quote:
                    quote = ""
                continue
            if char in "\"'":
                quote = char
            elif char == "#":
                cut = index
                break
        out.append(line[:cut])
    return "\n".join(out)


def _vanilla_keys(directory: Path) -> set[str]:
    """某个原版目录下全部 ``.txt`` 的顶层键（走仓库自己的解析器，带缓存）。"""
    return vanilla_index.vanilla_keys(directory)


def on_action_members(directory: Path) -> set[str]:
    """原版 `common/on_actions/*.txt` 里**每个顶层块**的深度 1 键（机械扫描，不手抄白名单）。

    「深度 1」= on_action 名字块（`on_monthly_pulse_country = { … }`）**直接**写的那几个键。
    ⚠️ 深度 2 的条目**不在**这条判据的作用范围：转调列表
    `on_actions = { delay = { days = 4 } … }` 里的 `delay`（原版 `00_code_on_actions.txt:1558`）
    是列表条目、引擎认它 —— 判据比引擎严比漏判更坏（理由见 :data:`ON_ACTION_OFFICIAL_MEMBERS`）。
    """
    if not directory.is_dir():
        return set()
    out: set[str] = set()
    for path in sorted(directory.rglob("*.txt")):
        root = parse_cached(path).root
        for item in root.assignments():
            block = item.value
            if isinstance(block, Block):
                out.update(inner.key for inner in block.assignments())
    return out


def on_action_allowed_keys(game: Path | None = None) -> set[str]:
    """规则①的合法键集合 = **现扫原版**得到的 ∪ 官方结构成员（两处都不是手抄的）。

    ⚠️ 实测：原版用到的 5 个（`effect` / `events` / `on_actions` / `random_events` / `trigger`）
    **恰好是官方 10 个的子集**，所以今天这个并集等于官方那 10 个 —— 并集仍然照取：原版那边
    一旦冒出官方清单里没有的键（版本更新），判据要跟着放宽，而不是把原版真用到的写法判红。
    """
    root = game or config.GAME
    return on_action_members(root.joinpath(*ON_ACTION_DIR)) | set(ON_ACTION_OFFICIAL_MEMBERS)


def on_action_block_keys(text: str) -> dict[str, list[str]]:
    """一段 on_action 文本的「块名 → 深度 1 键」对照（走仓库自己的解析器，不另写扫描器）。"""
    out: dict[str, list[str]] = {}
    for item in parse_text(text).root.assignments():
        block = item.value
        if isinstance(block, Block):
            out.setdefault(item.key, []).extend(inner.key for inner in block.assignments())
    return out


def count_if_blocks(text: str) -> int:
    """文本里 `if = {` 的个数（规则②的**覆盖面**读数；`else_if` 不算，见 :data:`_IF_OPEN`）。"""
    return len(_IF_OPEN.findall(text))


def count_limit_blocks(text: str) -> int:
    """文本里 `limit = {` 的个数（规则③的**覆盖面**读数）。"""
    return sum(
        1
        for block in _walk_blocks(parse_text(text).root)
        for item in block.assignments()
        if item.key == "limit" and isinstance(item.value, Block)
    )


def if_blocks_without_limit(text: str) -> list[str]:
    """`if = {` 之后第一条语句**不是** `limit = {` 的每一处，返回**内容片段**（不给行号）。

    为什么按内容定位：引擎对 `scripted_effects` 报的行号**偏移不恒定**（本仓已有三个不自洽的
    数据点，backlog B84）⇒ 拿行号当锚会把"修好了"与"锚漂了"混起来。片段里那一行就是引擎会
    当成**效果**读的那一行本身，改完即消失。
    """
    out: list[str] = []
    for match in _IF_OPEN.finditer(text):
        rest = text[match.end() :]
        if _LIMIT_OPEN.match(rest):
            continue
        out.append(" ".join(rest.strip().splitlines()[:1]).strip()[:80])
    return out


def _scalar_text(value: object) -> str:
    """标量节点的原文（块与 ``None`` 一律空串）。"""
    return "" if isinstance(value, Block) else str(getattr(value, "text", ""))


def _scope_comparison_pair(item: Assignment) -> str | None:
    """这条 `?=` 是不是**作用域比较**？是的话返回它的**整句**（`c:GBR ?= this` 这种）。

    两种方向都认（原版两种都在用）：设计器在左（`c:GBR ?= this`，1611 处）或在右
    （`this ?= s:STATE_HOKKAIDO`，23 处）。变量前缀（`var:` / `global_var:`）不算。
    """
    if item.op != "?=":
        return None
    right = _scalar_text(item.value)
    for text in (item.key, right):
        match = _SCOPE_COMPARISON.match(text)
        if match and match.group(1) not in _VARIABLE_PREFIXES:
            return " ".join(part for part in (item.key, item.op, right) if part)
    return None


def _walk_blocks(root: Block) -> Iterator[Block]:
    """深度优先遍历所有块（含 ``root`` 自己）。"""
    stack = [root]
    while stack:
        block = stack.pop()
        yield block
        below = [item.value for item in block.assignments() if isinstance(item.value, Block)]
        stack.extend(below)


def limit_scope_flattenings(text: str) -> list[str]:
    """`limit = { … }` 里**平铺 ≥2 条作用域比较**的每一处，返回内容片段（不给行号）。

    为什么这是**静默**失效（比语法错误更坏，因为它一行日志都不留）：`limit` 是**与**（AND）
    ⇒ `c:GBR ?= this` 与 `c:RUS ?= this` 同时为真**不可能** ⇒ 整个 `limit` 恒假 ⇒ 里面那
    一整段一次都不执行，而 `error.log` 里提到我们文件的行数是 **0**。实测（2026-09-25 03:33，
    第一臂 15 月档）：`ZZPROBE STRESS;` 只有 WAR ×5，四波 32 行自报与 `add_radicals_in_state`
    **全没发生** —— 从 9 行 `Unknown effect` 降到 0 行**不等于修好了**。

    ⚠️ 两种**合法**形状不许判红（阳性对照）：`limit = { OR = { c:GBR ?= this … } }`（有显式
    `OR = {` 包着 ⇒ 那些比较的父块不是 `limit`）与 8 个各自独立的
    `if = { limit = { c:TAG ?= this } … }`（每个 `limit` 里只有 1 条）。
    ⚠️ 作用范围**只到 `limit`**（本卡口径）：显式 `AND = { … }` 或其它触发器容器不在判据内。
    """
    out: list[str] = []
    for block in _walk_blocks(parse_text(text).root):
        for item in block.assignments():
            if item.key != "limit" or not isinstance(item.value, Block):
                continue
            found = [
                pair
                for pair in (_scope_comparison_pair(child) for child in item.value.assignments())
                if pair
            ]
            if len(found) >= 2:
                out.append(f"{len(found)} 条：{' / '.join(found[:2])} …")
    return out


@dataclass(frozen=True, slots=True)
class ShapeScan:
    """形状体检的**覆盖面**读数：结论行用它证明这两条规则真的跑过，而不是"没查到"。"""

    on_action_blocks: int = 0
    on_action_keys: int = 0
    on_action_bad: int = 0
    if_blocks: int = 0
    if_bad: int = 0
    limits: int = 0
    limit_bad: int = 0
    #: 原版扫到的深度 1 键个数（0 = 这台机器没有游戏 ⇒ 规则①只按官方 10 个成员判）。
    vanilla_keys: int = 0


def scan_shapes(files: dict[str, str], *, game: Path | None = None) -> ShapeScan:
    """只数**形状**（不判引用）：给开局前的结论行提供覆盖面读数。"""
    root = game or config.GAME
    vanilla = on_action_members(root.joinpath(*ON_ACTION_DIR))
    allowed = vanilla | set(ON_ACTION_OFFICIAL_MEMBERS)
    blocks = keys = bad_keys = if_blocks = bad_ifs = bad_limits = 0
    limits = 0
    for rel, raw in sorted(files.items()):
        if not rel.endswith(".txt"):
            continue
        text = code_only(raw)
        if_blocks += count_if_blocks(text)
        bad_ifs += len(if_blocks_without_limit(text))
        limits += count_limit_blocks(text)
        bad_limits += len(limit_scope_flattenings(text))
        if not rel.startswith(_ON_ACTION_PREFIX):
            continue
        for group in on_action_block_keys(text).values():
            blocks += 1
            keys += len(group)
            bad_keys += sum(1 for key in group if key not in allowed)
    return ShapeScan(blocks, keys, bad_keys, if_blocks, bad_ifs, limits, bad_limits, len(vanilla))


def _defined_in_probe(files: dict[str, str]) -> set[str]:
    """探针自己的文件里定义的名字（``name = {``）。"""
    names: set[str] = set()
    for text in files.values():
        names |= set(_DEFINITION.findall(code_only(text)))
    return names


def _defined_in_mod(root: Path | None = None) -> set[str]:
    """真 mod 的产物里定义的名字（脚本效果 / JE / 修正 / 本地化键之外的定义名）。"""
    base = root or (config.REPO / "mod")
    names: set[str] = set()
    for path in base.rglob("*.txt"):
        try:
            names |= set(
                _DEFINITION.findall(code_only(path.read_text(encoding="utf-8", errors="replace")))
            )
        except OSError:  # pragma: no cover - 读不动就跳过
            continue
    return names


def lint(
    files: dict[str, str],
    *,
    game: Path | None = None,
    mod_root: Path | None = None,
    exe_identifiers: frozenset[str] | None = None,
) -> list[Issue]:
    """体检探针产物的引用（只读、不碰游戏、不需要引擎）。

    ``files`` 是**生成结果**（``ab_probe.build().files``）：查的是"生成出来的东西引用得到吗"，
    而不是"盘上那份"—— 盘上的可能还没重新生成。
    """
    game_root = game or config.GAME
    probe_names = _defined_in_probe(files)
    mod_names = _defined_in_mod(mod_root)
    laws = _vanilla_keys(game_root.joinpath(*LAW_DIR))
    strategies = _vanilla_keys(game_root.joinpath(*STRATEGY_DIR))
    igs = _vanilla_keys(game_root.joinpath(*IG_DIR))
    on_action_allowed = on_action_allowed_keys(game_root)
    vanilla_members = len(on_action_members(game_root.joinpath(*ON_ACTION_DIR)))

    issues: list[Issue] = []
    for rel, raw in sorted(files.items()):
        if not rel.endswith(".txt"):
            continue
        text = code_only(raw)

        # ── 形状①：on_action 块里的深度 1 键只能是官方结构成员 ──────────────
        # t64 侦察局实测：块里直接写脚本效果调用 ⇒ 引擎拒掉**整份文件**
        # （`Unexpected token: zz_stress_tick, near line: 6`）⇒ 钩子一次都没挂上、那一局 0 行自报。
        if rel.startswith(_ON_ACTION_PREFIX):
            seen_keys: dict[str, str] = {}
            for block_name, group in on_action_block_keys(text).items():
                for key in group:
                    seen_keys.setdefault(key, block_name)
            for key, block_name in sorted(seen_keys.items()):
                ok = key in on_action_allowed
                issues.append(
                    Issue(
                        "on_action 顶层键",
                        key,
                        ok,
                        f"{rel} 的 `{block_name}` 块："
                        + (
                            "是结构成员"
                            if ok
                            else f"它不在合法键集合里（原版扫到 {vanilla_members} 个 + 官方 10 个）"
                        ),
                        ""
                        if ok
                        else (
                            "on_action 块里只能写官方结构成员（`effect` / `events` / `on_actions` / "
                            "`random_events` / `trigger` / …）；要调脚本效果就得先**转调**一个自己的 "
                            "on_action（官方配方：`docs/victoria3-modding/04-脚本系统.md` §3.4）"
                            " —— 写错时引擎拒**整份文件**，症状是钩子一次都没挂上"
                        ),
                    )
                )

        # ── 形状②：`if = {` 的第一条语句必须是 `limit = {` ────────────────
        # t64 侦察局实测：少了它 ⇒ 里面那几行被当**效果**读（8 行 `Unknown effect c:TAG`）。
        issues.extend(
            Issue(
                "if 缺 limit",
                snippet,
                False,
                f"{rel} 里这一处 `if = {{` 之后的第一条语句不是 `limit = {{`：{snippet}",
                "`if` 的第一条必须是 `limit = { … }`；少它引擎会把里面这几行当**效果**读"
                "（t64 实测 8 行 `Unknown effect c:GBR`），那一格读数静默为空"
                " —— 改生成器，不要手改部署产物",
            )
            for snippet in if_blocks_without_limit(text)
        )

        # ── 形状③：`limit` 里平铺 ≥2 条作用域比较 ⇒ **静默恒假** ─────────────
        # 这条比前两条更坏：`limit` 是与（AND），而 `c:GBR ?= this` 与 `c:RUS ?= this`
        # 不可能同时为真 ⇒ 整段不执行，**而引擎一行日志都不报**（t73 2026-09-25 03:33 实测）。
        issues.extend(
            Issue(
                "limit 平铺作用域比较",
                snippet,
                False,
                f"{rel} 的 `limit` 块里平铺了 {snippet}"
                "（`limit` 是**与** ⇒ 恒假 ⇒ 整段一次都不执行）",
                "要「任一命中」就用 `OR = { c:A ?= this c:B ?= this }`，或拆成每个 tag 一个独立的 "
                "`if = { limit = { c:TAG ?= this } … }`；这条**引擎一行日志都不报**"
                "（t73 实测：四波 32 行自报全没发生、`error.log` 里提到我们文件的行数是 0）",
            )
            for snippet in limit_scope_flattenings(text)
        )

        for name in sorted(set(_OUR_CALL.findall(text))):
            if name in probe_names:
                issues.append(Issue("我们自己定义的效果", name, True, f"{rel} 调用，探针里有定义"))
            elif name in mod_names:
                issues.append(Issue("真 mod 定义的效果", name, True, f"{rel} 调用，mod 里有定义"))
            else:
                issues.append(
                    Issue(
                        "未知效果",
                        name,
                        False,
                        f"{rel} 调用了它，但探针与 mod 里都没有定义",
                        "引擎只会记一条 Unknown effect，那一格读数会静默为空 —— 改对名字或补上定义",
                    )
                )

        for name in sorted(set(_JE_USE.findall(text))):
            ok = name in mod_names
            issues.append(
                Issue(
                    "日志条目引用",
                    name,
                    ok,
                    "mod 里有定义" if ok else f"{rel} 引用了它，但 mod 里没有定义",
                    "" if ok else "JE 名写错 ⇒ 那一行永远 inactive（看起来像「窗口没开」）",
                )
            )

        if laws:
            for name in sorted(set(_LAW_USE.findall(text))):
                ok = name in laws
                issues.append(
                    Issue(
                        "法类型引用",
                        name,
                        ok,
                        f"原版有（{len(laws)} 个）" if ok else "原版 common/laws 里没有这个名字",
                        "" if ok else "写错 ⇒ 那条 LAW/ENACT 行永远不出现（法没换与没记分不清）",
                    )
                )

        if strategies:
            for name in sorted(set(_STRATEGY_USE.findall(text))):
                ok = name in strategies or name in probe_names or name in mod_names
                issues.append(
                    Issue(
                        "AI 牌引用",
                        name,
                        ok,
                        (
                            f"原版有（{len(strategies)} 张）"
                            if name in strategies
                            else "探针自己的文件里有定义"
                            if name in probe_names
                            else "真 mod 的产物里有定义"
                            if name in mod_names
                            else "原版 ai_strategies 里没有，探针与真 mod 的产物里也没有"
                        ),
                        ""
                        if ok
                        else (
                            "写错 ⇒ 牌那一格永远读不到（B87 就是这一族的另一面）。"
                            "⚠️ 只放行**有定义**的名字：拼错的牌名必须仍然判红"
                        ),
                    )
                )

        if igs:
            for name in sorted(set(_IG_USE.findall(text))):
                ok = name in igs
                issues.append(
                    Issue(
                        "利益集团引用",
                        name,
                        ok,
                        f"原版有（{len(igs)} 个）" if ok else "原版 interest_groups 里没有它",
                        "" if ok else "写错 ⇒ 那一行 CLOUT/GOV 自报不会出现",
                    )
                )

        identifiers = exe_identifiers
        if identifiers:
            for call in _DATA_FN.findall(text):
                for chain in _DATA_FN_CALL.findall(call):
                    for part in chain.split("."):
                        if part in {"THIS", "ROOT", "PREV", "FROM", "SCOPE"}:
                            continue
                        ok = part in identifiers
                        issues.append(
                            Issue(
                                "data function 片段",
                                part,
                                ok,
                                "exe 里有这个标识符" if ok else "exe 里没有这个标识符",
                                ""
                                if ok
                                else "写错 ⇒ debug_log 把 `[...]` 原样打出来（假读数，B90 的两种写法就是为它留的）",
                            )
                        )
    return issues


def failures(issues: list[Issue]) -> list[Issue]:
    """只留不通过的（调用方据此判退出码）。"""
    return [issue for issue in issues if not issue.ok]


__all__ = [
    "ON_ACTION_DIR",
    "ON_ACTION_OFFICIAL_MEMBERS",
    "Issue",
    "ShapeScan",
    "code_only",
    "count_if_blocks",
    "count_limit_blocks",
    "failures",
    "if_blocks_without_limit",
    "limit_scope_flattenings",
    "lint",
    "on_action_allowed_keys",
    "on_action_block_keys",
    "on_action_members",
    "scan_shapes",
]
