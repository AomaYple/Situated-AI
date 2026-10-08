"""原版政治 AI 策略的结构化只读索引。

这个模块只读取 ``common/ai_strategies`` 中 ``type = political`` 的策略牌，
把法律启动相关的脚本字段、条件加法和偏好对象整理成可追踪的数据。它不运行
触发器，也不尝试求出引擎内部的候选排序、随机抽签或最终启动概率。

原版脚本把 ``change_law_chance`` 写成脚本值块，例如：

.. code-block:: text

    change_law_chance = {
        value = 2.5
        if = { limit = { ... } add = 7.5 }
    }

因此这里保留基值、每个条件项的操作和值，以及条件中的顶层触发器。动态表达式
不会被猜成数字，而是以 ``expression`` 留在索引中，避免把静态审计冒充运行时读数。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import config
from .cache import parse_cached
from .model import Assignment, Block, Node, Scalar

if TYPE_CHECKING:
    from collections.abc import Iterable


STRATEGY_DIR = Path("common") / "ai_strategies"
DEFAULT_PATH = STRATEGY_DIR / "00_default_strategy.txt"
DOC_PATH = Path("docs") / "design" / "02-政治候选面.md"
DOC_REL = DOC_PATH.as_posix()

_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
_NUMERIC_LITERAL = re.compile(
    r"^[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|nan|inf(?:inity)?)$",
    re.IGNORECASE,
)
_CONDITION_WRAPPERS = frozenset(
    {
        "and",
        "or",
        "not",
        "nor",
        "nand",
        "if",
        "else_if",
        "else",
        "limit",
        "trigger_if",
        "trigger_else_if",
        "trigger_else",
        "hidden",
        "custom_tooltip",
    }
)
_VALUE_OPERATORS = frozenset(
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


@dataclass(frozen=True, slots=True)
class ConditionalContribution:
    """一个脚本值条件分支的可审计摘要。"""

    line: int
    operator: str
    amount: float | None
    expression: str | None
    condition_keys: tuple[str, ...]
    path: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScriptValueSummary:
    """脚本值的静态摘要；不会把动态表达式折算成数值。"""

    base: float | None
    dynamic_base: str | None
    contributions: tuple[ConditionalContribution, ...]
    canonical_ast: str = ""
    canonical_sha256: str = ""
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PoliticalStrategy:
    """一张原版政治策略牌。"""

    name: str
    file: str
    line: int
    source_sha256: str
    revolution_aversion: ScriptValueSummary | None
    min_law_chance_to_pass: ScriptValueSummary | None
    max_progressiveness: ScriptValueSummary | None
    max_regressiveness: ScriptValueSummary | None
    change_law_chance: ScriptValueSummary | None
    pro_interest_groups: tuple[str, ...]
    anti_interest_groups: tuple[str, ...]
    pro_movements: tuple[str, ...]
    anti_movements: tuple[str, ...]
    possible_keys: tuple[str, ...]


def _text(node: Node | None) -> str | None:
    return node.unquoted if isinstance(node, Scalar) else None


def _number(node: Node | None) -> float | None:
    value = _text(node)
    if value is None or not _NUMBER.fullmatch(value):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _canonical_node(node: Node | None) -> object:
    """将 AST 变为稳定 JSON 形状，保留重复项、运算符、作用域字面量和行号。"""

    if node is None:
        return None
    if isinstance(node, Scalar):
        return {"kind": "scalar", "text": node.text, "quoted": node.quoted, "line": node.line}
    if isinstance(node, Assignment):
        return {
            "kind": "assignment",
            "key": node.key,
            "op": node.op,
            "prefix": node.prefix,
            "line": node.line,
            "value": _canonical_node(node.value),
        }
    return {
        "kind": "block",
        "line": node.line,
        "items": [_canonical_node(item) for item in node.items],
    }


def _canonical_json(node: Node | None) -> str:
    return json.dumps(
        _canonical_node(node), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _condition_keys(block: Block) -> tuple[str, ...]:
    """提取条件中出现的触发器键，过滤逻辑包装和脚本值运算符。"""

    found: set[str] = set()

    def walk(current: Block) -> None:
        for assignment in current.assignments():
            key = assignment.key
            value = assignment.value
            lowered = key.lower()
            if lowered in _CONDITION_WRAPPERS or lowered in _VALUE_OPERATORS:
                if isinstance(value, Block):
                    walk(value)
                continue
            found.add(key)
            if isinstance(value, Block):
                walk(value)

    walk(block)
    return tuple(sorted(found))


def _contributions(
    block: Block, *, path: tuple[str, ...] = (), conditions: tuple[str, ...] = ()
) -> list[ConditionalContribution]:
    """递归记录所有脚本值运算；不因同一分支有多个运算而丢项。"""

    out: list[ConditionalContribution] = []
    for item in block.assignments():
        key = item.key.lower()
        value = item.value
        next_conditions = conditions
        if key in {"if", "else_if", "else"} and isinstance(value, Block):
            limit = value.first("limit")
            if limit is not None and isinstance(limit.value, Block):
                next_conditions = conditions + _condition_keys(limit.value)
        if key in _VALUE_OPERATORS and not (not path and key == "value"):
            amount = _number(value)
            expression = None if amount is not None else _text(value)
            if expression is None and isinstance(value, Block):
                expression = _canonical_json(value)
            out.append(
                ConditionalContribution(
                    line=item.line,
                    operator=item.key,
                    amount=amount,
                    expression=expression,
                    condition_keys=next_conditions,
                    path=(*path, item.key),
                )
            )
        if isinstance(value, Block):
            out.extend(_contributions(value, path=(*path, item.key), conditions=next_conditions))
    return out


def _numeric_diagnostics(block: Block) -> tuple[str, ...]:
    found: list[str] = []

    def walk(current: Block, path: tuple[str, ...] = ()) -> None:
        for item in current.assignments():
            value = _text(item.value)
            if (
                item.key.lower() in _VALUE_OPERATORS
                and value is not None
                and _NUMERIC_LITERAL.fullmatch(value)
                and _number(item.value) is None
            ):
                found.append(f"{'.'.join((*path, item.key))}={value!r} (non-finite or invalid)")
            if isinstance(item.value, Block):
                walk(item.value, (*path, item.key))

    walk(block)
    return tuple(found)


def script_value_summary(assignment: Assignment | None) -> ScriptValueSummary | None:
    """读取一个脚本值块，动态部分保持原样。"""

    if assignment is None or not isinstance(assignment.value, Block):
        return None
    block = assignment.value
    base_assignment = block.first("value")
    base = _number(base_assignment.value) if base_assignment is not None else None
    dynamic_base = (
        None if base is not None else _text(base_assignment.value) if base_assignment else None
    )
    contributions = tuple(_contributions(block))
    canonical_ast = _canonical_json(block)
    return ScriptValueSummary(
        base,
        dynamic_base,
        contributions,
        canonical_ast,
        hashlib.sha256(canonical_ast.encode("utf-8")).hexdigest(),
        _numeric_diagnostics(block),
    )


def _list_values(assignment: Assignment | None) -> tuple[str, ...]:
    if assignment is None or not isinstance(assignment.value, Block):
        return ()
    return tuple(value.unquoted for value in assignment.value.scalars())


def _condition_names(block: Block | None) -> tuple[str, ...]:
    return _condition_keys(block) if block is not None else ()


def strategy_files(game: Path | None = None) -> list[Path]:
    """返回稳定排序的原版策略文件。"""

    root = game or config.GAME
    return sorted((root / STRATEGY_DIR).glob("*.txt"))


def _strategy_from_assignment(
    assignment: Assignment, *, relative: str, source_sha256: str
) -> PoliticalStrategy | None:
    if not assignment.key.startswith("ai_strategy_") or not isinstance(assignment.value, Block):
        return None
    block = assignment.value
    possible_assignment = block.first("possible")
    possible_block = (
        possible_assignment.value
        if possible_assignment is not None and isinstance(possible_assignment.value, Block)
        else None
    )
    return PoliticalStrategy(
        name=assignment.key,
        file=relative,
        line=assignment.line,
        source_sha256=source_sha256,
        revolution_aversion=script_value_summary(block.first("revolution_aversion")),
        min_law_chance_to_pass=script_value_summary(block.first("min_law_chance_to_pass")),
        max_progressiveness=script_value_summary(block.first("max_progressiveness")),
        max_regressiveness=script_value_summary(block.first("max_regressiveness")),
        change_law_chance=script_value_summary(block.first("change_law_chance")),
        pro_interest_groups=_list_values(block.first("pro_interest_groups")),
        anti_interest_groups=_list_values(block.first("anti_interest_groups")),
        pro_movements=_list_values(block.first("pro_movements")),
        anti_movements=_list_values(block.first("anti_movements")),
        possible_keys=_condition_names(possible_block),
    )


def _read_file_strategies(path: Path, root: Path) -> list[PoliticalStrategy]:
    parsed = parse_cached(path)
    if parsed.errors:
        raise ValueError(f"原版政治策略无法解析：{path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    relative = path.relative_to(root).as_posix()
    strategies: list[PoliticalStrategy] = []
    for assignment in parsed.top_assignments:
        strategy = _strategy_from_assignment(assignment, relative=relative, source_sha256=digest)
        if strategy is not None:
            strategies.append(strategy)
    return strategies


def read_strategies(game: Path | None = None) -> list[PoliticalStrategy]:
    """读取全部 ``type = political`` 策略牌并保留源文件指纹。"""

    root = game or config.GAME
    strategies: list[PoliticalStrategy] = []
    for path in strategy_files(root):
        parsed = parse_cached(path)
        if parsed.errors:
            raise ValueError(f"原版政治策略无法解析：{path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        relative = path.relative_to(root).as_posix()
        for assignment in parsed.top_assignments:
            strategy = _strategy_from_assignment(
                assignment, relative=relative, source_sha256=digest
            )
            if strategy is None or not isinstance(assignment.value, Block):
                continue
            type_node = assignment.value.first("type")
            if type_node is not None and _text(type_node.value) == "political":
                strategies.append(strategy)
    if not strategies:
        raise ValueError(f"未找到原版政治策略：{root / STRATEGY_DIR}")
    names = [strategy.name for strategy in strategies]
    if len(names) != len(set(names)):
        raise ValueError("原版政治策略键重复")
    return sorted(strategies, key=lambda strategy: strategy.name)


def read_default_strategy(game: Path | None = None) -> PoliticalStrategy:
    """读取原版默认层；它不是政治牌，但其贡献参与最终聚合。"""

    root = game or config.GAME
    path = root / DEFAULT_PATH
    if not path.is_file():
        raise ValueError(f"原版默认策略不存在：{path}")
    strategies = _read_file_strategies(path, root)
    default = next((item for item in strategies if item.name == "ai_strategy_default"), None)
    if default is None:
        raise ValueError(f"默认策略缺失 ai_strategy_default：{path}")
    return default


def _format_number(value: float | None) -> str:
    return "—" if value is None else f"{value:g}"


def _format_summary(summary: ScriptValueSummary | None) -> str:
    if summary is None:
        return "—"
    base = _format_number(summary.base)
    if summary.dynamic_base is not None:
        base = f"`{summary.dynamic_base}`"
    if not summary.contributions:
        return base
    terms = ", ".join(
        f"{term.operator} {_format_number(term.amount) if term.amount is not None else '`' + (term.expression or '?') + '`'}"
        f"〔{','.join(term.condition_keys) or '无条件'}〕"
        for term in summary.contributions
    )
    diagnostics = f"；诊断 {len(summary.diagnostics)}" if summary.diagnostics else ""
    return f"{base}；{terms}；AST `{summary.canonical_sha256[:12]}`{diagnostics}"


def _table(headers: list[str], rows: Iterable[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines


def render(
    strategies: list[PoliticalStrategy], default_strategy: PoliticalStrategy | None = None
) -> str:
    """渲染可审计的政治策略文档。"""

    lines = [
        "# 02 · 政治候选面（原版只读索引）",
        "",
        "> 本文件由 `v3 political-surface --write` 生成，勿手改。",
        "> 它是原版脚本的静态结构索引，不是引擎运行时的最终候选排名或启动概率。",
        "",
        "## 复算",
        "",
        "```text",
        "v3 political-surface --write",
        "v3 political-surface --check",
        "```",
        "",
        f"共枚举 **{len(strategies)}** 张 `type = political` 策略牌。",
        "`change_law_chance` 等字段的数值来自脚本值块；条件项只列出原文操作和值与触发器键。",
        "动态脚本值保留为表达式，避免把静态基值误报为最终概率。",
        "",
        "## 策略字段与来源",
        "",
    ]
    lines.extend(
        _table(
            [
                "策略",
                "change_law_chance（基值；条件项）",
                "min_law_chance_to_pass",
                "进度上限",
                "倒退上限",
                "革命厌恶",
                "亲/反 IG",
                "来源",
                "源 SHA-256（前12位）",
            ],
            [
                [
                    f"`{strategy.name}`",
                    _format_summary(strategy.change_law_chance),
                    _format_summary(strategy.min_law_chance_to_pass),
                    _format_summary(strategy.max_progressiveness),
                    _format_summary(strategy.max_regressiveness),
                    _format_summary(strategy.revolution_aversion),
                    f"{len(strategy.pro_interest_groups)}/{len(strategy.anti_interest_groups)}",
                    f"`{strategy.file}:{strategy.line}`",
                    f"`{strategy.source_sha256[:12]}`",
                ]
                for strategy in strategies
            ],
        )
    )
    if default_strategy is not None:
        lines.extend(
            [
                "",
                "### 默认层（所有 AI 国家共同参与聚合）",
                "",
                (
                    f"`{default_strategy.name}` 的 `change_law_chance`："
                    f"{_format_summary(default_strategy.change_law_chance)}；"
                    f"来源 `{default_strategy.file}:{default_strategy.line}`；"
                    f"源 SHA-256 前12位 `{default_strategy.source_sha256[:12]}`。"
                ),
                "默认层不是一张 `type = political` 牌，但它的贡献必须与活动政治策略相加审计。",
            ]
        )
    lines.extend(
        [
            "",
            "## 偏好对象与候选门",
            "",
        ]
    )
    lines.extend(
        _table(
            ["策略", "亲 IG", "反 IG", "亲运动", "反运动", "possible 中的条件键"],
            [
                [
                    f"`{strategy.name}`",
                    ", ".join(strategy.pro_interest_groups) or "—",
                    ", ".join(strategy.anti_interest_groups) or "—",
                    ", ".join(strategy.pro_movements) or "—",
                    ", ".join(strategy.anti_movements) or "—",
                    ", ".join(strategy.possible_keys) or "—",
                ]
                for strategy in strategies
            ],
        )
    )
    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            "* `change_law_chance` 是原版策略贡献字段；脚本基值和条件加法不等于最终启动概率。",
            "* 候选法律仍需以正确的 `scope:law`、可用性、方向限制、政府/运动支持和革命风险逐法判断。",
            "* 本索引没有引擎 Getter 可直接提供的最终排序、随机因子、24 个月记忆或抽签次数；",
            "  这些缺口继续由 M5 结果页记录，不能用静态表补齐。",
            "* 每行带原版相对路径、定义行和短指纹；结构化 JSON 保存完整 SHA-256。游戏升级后必须重新生成并审查差异。",
            "",
        ]
    )
    return "\n".join(lines)


def build(game: Path | None = None) -> str:
    return render(read_strategies(game), read_default_strategy(game))


def write_doc(repo: Path | None = None, *, game: Path | None = None) -> Path:
    root = repo or config.REPO
    path = root / DOC_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build(game), encoding="utf-8", newline="\n")
    return path


def check_doc(repo: Path | None = None, *, game: Path | None = None) -> str:
    root = repo or config.REPO
    path = root / DOC_PATH
    if not path.is_file():
        return f"缺少 {DOC_REL}；请运行 `v3 political-surface --write`"
    expected = build(game)
    actual = path.read_text(encoding="utf-8")
    return "" if actual == expected else f"{DOC_REL} 与原版政治策略索引不一致"


def as_json(
    strategies: list[PoliticalStrategy], default_strategy: PoliticalStrategy | None = None
) -> dict[str, object]:
    """给脚本和报告使用的稳定 JSON 形状。"""

    def summary(value: ScriptValueSummary | None) -> dict[str, object] | None:
        if value is None:
            return None
        return {
            "base": value.base,
            "dynamic_base": value.dynamic_base,
            "contributions": [
                {
                    "line": term.line,
                    "operator": term.operator,
                    "amount": term.amount,
                    "expression": term.expression,
                    "condition_keys": list(term.condition_keys),
                    "path": list(term.path),
                }
                for term in value.contributions
            ],
            "canonical_ast": value.canonical_ast,
            "canonical_sha256": value.canonical_sha256,
            "diagnostics": list(value.diagnostics),
        }

    payload: dict[str, object] = {
        "strategy_count": len(strategies),
        "strategies": [
            {
                "name": strategy.name,
                "file": strategy.file,
                "line": strategy.line,
                "source_sha256": strategy.source_sha256,
                "revolution_aversion": summary(strategy.revolution_aversion),
                "min_law_chance_to_pass": summary(strategy.min_law_chance_to_pass),
                "max_progressiveness": summary(strategy.max_progressiveness),
                "max_regressiveness": summary(strategy.max_regressiveness),
                "change_law_chance": summary(strategy.change_law_chance),
                "pro_interest_groups": list(strategy.pro_interest_groups),
                "anti_interest_groups": list(strategy.anti_interest_groups),
                "pro_movements": list(strategy.pro_movements),
                "anti_movements": list(strategy.anti_movements),
                "possible_keys": list(strategy.possible_keys),
            }
            for strategy in strategies
        ],
        "limits": {
            "final_engine_chance": False,
            "candidate_ranking": False,
            "random_memory": False,
        },
    }
    if default_strategy is not None:
        payload["default_strategy"] = {
            "name": default_strategy.name,
            "file": default_strategy.file,
            "line": default_strategy.line,
            "source_sha256": default_strategy.source_sha256,
            "change_law_chance": summary(default_strategy.change_law_chance),
        }
    return payload


def write_json(path: Path, *, game: Path | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            as_json(read_strategies(game), read_default_strategy(game)),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path
