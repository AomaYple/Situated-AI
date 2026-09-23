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
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pdx import config, vanilla_index

if TYPE_CHECKING:
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

    issues: list[Issue] = []
    for rel, raw in sorted(files.items()):
        if not rel.endswith(".txt"):
            continue
        text = code_only(raw)

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
                ok = name in strategies
                issues.append(
                    Issue(
                        "AI 牌引用",
                        name,
                        ok,
                        f"原版有（{len(strategies)} 张）"
                        if ok
                        else "原版 ai_strategies 里没有这张牌",
                        "" if ok else "写错 ⇒ 牌那一格永远读不到（B87 就是这一族的另一面）",
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
    "Issue",
    "code_only",
    "failures",
    "lint",
]
