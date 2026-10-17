"""生成七模块的静态原版消费者台账。

这个模块只读取锁定版本的原版默认策略和精简 AI 面快照。它回答的是
“候选字段写入了哪个原版策略字段、默认策略块在哪里、哪些原版策略牌也声明了
同名字段”，不尝试读取游戏运行期数值，也不把脚本解析成功或评分变化解释为
Mod 行为质量通过。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path  # noqa: TC003 - runtime defaults and filesystem operations
from typing import TYPE_CHECKING

from . import ai_surface, config
from .model import Block
from .parser import parse_file

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


BASELINE = config.REPO / "research" / "vanilla-ai" / "1.14.5" / "00_default_strategy.txt"
OUTPUT = config.OUT / "f1-consumer-audit"


@dataclass(frozen=True, slots=True)
class ConsumerRow:
    """一个候选字段的静态消费者记录。"""

    module: str
    field: str
    consumer: str
    scope: str
    operation: str
    source: str
    source_line: int
    candidate_write: str
    strategy_cards: tuple[str, ...]
    status: str
    unknowns: tuple[str, ...]


FIELD_SPECS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "fiscal",
        "diplomatic_play_neutrality",
        "ai_strategy_default",
        "国家/外交博弈评估上下文",
        "默认策略字段追加；原版策略可继续叠加",
    ),
    (
        "security",
        "diplomatic_play_support",
        "ai_strategy_default",
        "root=评估国，country=被评估方，enemy_country=对手",
        "支持评分加法；候选安全理由在共享字段仲裁后只写一次",
    ),
    (
        "market",
        "diplomatic_play_support",
        "ai_strategy_default",
        "root=评估国，country/enemy_country=外交博弈双方",
        "方向性依赖差值的支持评分加法",
    ),
    (
        "reform",
        "change_law_chance",
        "ai_strategy_default",
        "国家策略上下文",
        "法律启动机会的加法；不等于法律候选排序",
    ),
    (
        "economy",
        "economic_vs_government_spending_balance",
        "ai_strategy_default",
        "国家策略上下文",
        "经济/政府支出平衡字段加法；不等于建筑选址",
    ),
    (
        "diplomacy",
        "recklessness",
        "ai_strategy_default",
        "国家策略上下文，并在目标评估中读取",
        "冒险程度加法；不创建外交机会或目标",
    ),
    (
        "subjects",
        "subject_value",
        "ai_strategy_default",
        "root=评估国，target_country=潜在/既有属国",
        "宗主评价值加法，位于原版可达性门内",
    ),
    (
        "subjects",
        "become_subject_value",
        "ai_strategy_default",
        "root=评估国，overlord=潜在宗主",
        "成为属国评价值加法",
    ),
)

UNKNOWN_BY_MODULE: dict[str, tuple[str, ...]] = {
    "fiscal": (
        "运行期财政变量的实际值和月度刷新时点",
        "中立值是否改变真实选边结果",
    ),
    "security": (
        "条约方向和支持评分到实际参战的因果链",
        "war goal 作用域在所有博弈类型中的运行期值",
    ),
    "market": (
        "economic_dependence 的运行期量纲、刷新时点和行为结果",
        "评分差是否改变实际选边",
    ),
    "reform": (
        "change_law_chance 的运行期概率和法律结果",
        "法律候选排序与通过率",
    ),
    "economy": (
        "字段对建设队列、商品取向和政府支出的实际影响",
        "bureaucracy 的运行期读取语义",
    ),
    "diplomacy": (
        "recklessness 的实际目标分母和宣战/和谈结果",
        "战争负担的运行期量纲",
    ),
    "subjects": (
        "宗属关系建立、解除、自治和独立的实际结果",
        "可达性与关系方向在全部场景中的运行期值",
    ),
}


def _default_block(path: Path) -> tuple[Block, str]:
    parsed = parse_file(path)
    if parsed.errors or parsed.top_keys != ["ai_strategy_default"]:
        raise ValueError(f"原版默认策略底本无效：{path}")
    assignment = parsed.top_assignments[0]
    if not isinstance(assignment.value, Block):
        raise ValueError("原版默认策略顶层必须是块")
    return assignment.value, path.relative_to(config.REPO).as_posix()


def _cards_for_field(cards: Iterable[ai_surface.Card], field: str) -> tuple[str, ...]:
    return tuple(sorted(card.name for card in cards if field in card.fields))


def audit(
    *,
    baseline: Path = BASELINE,
    cards: Iterable[ai_surface.Card] | None = None,
) -> tuple[ConsumerRow, ...]:
    """返回稳定排序的静态字段消费者台账。"""

    block, source = _default_block(baseline)
    if cards is None:
        cards, _defines = ai_surface.read_offline()
    card_list = tuple(cards)
    rows: list[ConsumerRow] = []
    for module, field, consumer, scope, operation in FIELD_SPECS:
        matches = block.all(field)
        if len(matches) != 1:
            raise ValueError(f"默认策略字段必须唯一：{field}（{len(matches)}）")
        row = matches[0]
        rows.append(
            ConsumerRow(
                module=module,
                field=field,
                consumer=f"{consumer}.{field}",
                scope=scope,
                operation=operation,
                source=source,
                source_line=row.line,
                candidate_write="src/pdx/decisions.py::patch_default",
                strategy_cards=_cards_for_field(card_list, field),
                status="static-mapping",
                unknowns=UNKNOWN_BY_MODULE[module],
            )
        )
    return tuple(rows)


def report(
    *, baseline: Path = BASELINE, cards: Iterable[ai_surface.Card] | None = None
) -> dict[str, object]:
    """返回 JSON 友好的审计报告，并明确其静态证据边界。"""

    rows = audit(baseline=baseline, cards=cards)
    return {
        "schema": "sitai-f1-consumer-audit-v1",
        "evidence_kind": "static-source-and-snapshot",
        "behavior_quality": "not_evaluated",
        "baseline": baseline.relative_to(config.REPO).as_posix(),
        "rows": [asdict(row) for row in rows],
        "limits": [
            "原版策略字段和作用域来自锁定底本/精简快照。",
            "不能由静态字段存在推出运行期消费者数值、AI 行动或行为质量。",
            "下一步实机必须使用同一候选、明确反事实和现有 pdx.game_run。",
        ],
    }


def render_markdown(data: Mapping[str, object]) -> str:
    """把报告渲染成可审阅的 Markdown，不写入仓库文档。"""

    rows = data.get("rows", [])
    if not isinstance(rows, list):
        raise ValueError("消费者报告 rows 无效")
    lines = [
        "# F1 静态字段消费者审计",
        "",
        "> 本页由 `pdx.consumer_audit` 生成。它是锁定原版底本与精简快照的静态映射，",
        "> 不代表游戏运行期消费者或 AI 行为质量通过。",
        "",
        "| 模块 | 候选字段 | 原版消费者 | 作用域 | 底本行 | 同名策略牌数 | 状态 |",
        "|---|---|---|---|---:|---:|---|",
    ]
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("消费者报告行无效")
        cards = row.get("strategy_cards", [])
        lines.append(
            "| {module} | `{field}` | `{consumer}` | {scope} | {line} | {count} | {status} |".format(
                module=row["module"],
                field=row["field"],
                consumer=row["consumer"],
                scope=row["scope"],
                line=row["source_line"],
                count=len(cards) if isinstance(cards, (list, tuple)) else 0,
                status=row["status"],
            )
        )
    lines.extend(
        [
            "",
            "## 证据边界",
            "",
            "- `evidence_kind=static-source-and-snapshot`；`behavior_quality=not_evaluated`。",
            "- 静态映射能证明字段存在、候选写入入口和已登记作用域，不能证明运行期数值、",
            "  实际行动、因果方向、玩家边界、语言显示或长期性能。",
            "- F1 下一步按模块登记同输入控制/候选反事实，使用 `pdx.game_run` 取运行期证据。",
            "",
        ]
    )
    return "\n".join(lines)


def write(output: Path = OUTPUT, *, baseline: Path = BASELINE) -> tuple[Path, Path]:
    """生成 JSON 与 Markdown 证据到忽略的输出目录。"""

    data = report(baseline=baseline)
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "report.json"
    markdown_path = output / "report.md"
    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    markdown_path.write_text(render_markdown(data), encoding="utf-8", newline="\n")
    return json_path, markdown_path


__all__ = ["FIELD_SPECS", "ConsumerRow", "audit", "render_markdown", "report", "write"]
