"""行动内核的 strategy → domain → tool 三层声明与关系图校验。

该模块只处理身份、依赖和合同。它不会把战略关联变成全局资格门，也不执行
国家行为；生产写入仍须经过消费者合同和 lowering。
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .schema import ActionCard, Relation

from .families import FAMILIES

_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_SCHEMA = 1
DEFAULT_SOURCE = Path(__file__).resolve().parents[3] / "mod" / "decisions" / "action_layers.toml"


@dataclass(frozen=True, slots=True)
class StrategyLayer:
    id: str
    description: str


@dataclass(frozen=True, slots=True)
class DomainLayer:
    id: str
    description: str
    parent: str | None = None


@dataclass(frozen=True, slots=True)
class ToolLayer:
    id: str
    domain_id: str
    strategy_id: str | None
    neutral_local: bool
    enables: tuple[str, ...]
    relations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LayerModel:
    strategies: tuple[StrategyLayer, ...]
    domains: tuple[DomainLayer, ...]
    tools: tuple[ToolLayer, ...]
    enables: tuple[tuple[str, str], ...]
    enables_depth: dict[str, int]
    source: str


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"action_layers.toml 缺少 {key} 映射")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise ValueError(f"{label} 必须是非空单行文本")
    return value


def _ids(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not _ID.fullmatch(item) for item in value
    ):
        raise ValueError(f"{label} 必须是小写 ID 列表")
    if len(set(value)) != len(value):
        raise ValueError(f"{label} 不能重复")
    return tuple(value)


def load(path: Path = DEFAULT_SOURCE, *, data: dict[str, Any] | None = None) -> LayerModel:
    raw = data if data is not None else tomllib.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema") != _SCHEMA or set(raw) != {"schema", "strategies", "domains", "tools"}:
        raise ValueError("action_layers.toml schema 必须为1且只包含三层声明")
    strategies: list[StrategyLayer] = []
    for key, value in sorted(_section(raw, "strategies").items()):
        if not _ID.fullmatch(key) or not isinstance(value, dict) or set(value) != {"description"}:
            raise ValueError(f"strategy 层声明无效：{key}")
        strategies.append(
            StrategyLayer(key, _text(value["description"], f"strategy {key}.description"))
        )
    domains: list[DomainLayer] = []
    for key, value in sorted(_section(raw, "domains").items()):
        if (
            not _ID.fullmatch(key)
            or not isinstance(value, dict)
            or set(value) not in ({"description"}, {"description", "parent"})
        ):
            raise ValueError(f"domain 层声明无效：{key}")
        parent = value.get("parent")
        if parent is not None and (not isinstance(parent, str) or not _ID.fullmatch(parent)):
            raise ValueError(f"domain {key}.parent 无效")
        domains.append(
            DomainLayer(key, _text(value["description"], f"domain {key}.description"), parent)
        )
    tools: list[ToolLayer] = []
    for key, value in sorted(_section(raw, "tools").items()):
        if (
            not _ID.fullmatch(key)
            or not isinstance(value, dict)
            or set(value) != {"domain", "strategy", "neutral_local", "enables", "relations"}
        ):
            raise ValueError(f"tool 层声明无效：{key}")
        domain = value["domain"]
        strategy = value["strategy"]
        if not isinstance(domain, str) or not _ID.fullmatch(domain):
            raise ValueError(f"tool {key}.domain 无效")
        if strategy is not None and (not isinstance(strategy, str) or not _ID.fullmatch(strategy)):
            raise ValueError(f"tool {key}.strategy 无效")
        if type(value["neutral_local"]) is not bool:
            raise ValueError(f"tool {key}.neutral_local 必须是布尔值")
        tools.append(
            ToolLayer(
                key,
                domain,
                strategy,
                value["neutral_local"],
                _ids(value["enables"], f"tool {key}.enables"),
                _ids(value["relations"], f"tool {key}.relations"),
            )
        )
    model = LayerModel(tuple(strategies), tuple(domains), tuple(tools), (), {}, str(path))
    validate(model)
    return model


def _depth(edges: tuple[tuple[str, str], ...]) -> dict[str, int]:
    graph: dict[str, tuple[str, ...]] = {}
    for source, target in edges:
        graph[source] = (*graph.get(source, ()), target)
    result: dict[str, int] = {}

    def visit(node: str, stack: tuple[str, ...] = ()) -> int:
        if node in stack:
            raise ValueError(f"enables 关系存在循环：{' -> '.join((*stack, node))}")
        if node in result:
            return result[node]
        children = graph.get(node, ())
        value = 0 if not children else 1 + max(visit(child, (*stack, node)) for child in children)
        if value > 2:
            raise ValueError(f"enables 关系深度超过2：{node}")
        result[node] = value
        return value

    for node in graph:
        visit(node)
    return result


def validate(model: LayerModel) -> None:
    strategy_ids = {item.id for item in model.strategies}
    domain_ids = {item.id for item in model.domains}
    tool_ids = {item.id for item in model.tools}
    if (
        len(strategy_ids) != len(model.strategies)
        or len(domain_ids) != len(model.domains)
        or len(tool_ids) != len(model.tools)
    ):
        raise ValueError("strategy/domain/tool ID 必须唯一")
    if set(FAMILIES) - domain_ids:
        raise ValueError(f"domain 层缺少 19 个行动族：{sorted(set(FAMILIES) - domain_ids)}")
    for domain in model.domains:
        if domain.parent is not None and domain.parent not in domain_ids:
            raise ValueError(f"domain {domain.id}.parent 未知：{domain.parent}")

    # domain 父树必须无环。
    def check_parent(node: str, stack: tuple[str, ...] = ()) -> None:
        parent = next(item.parent for item in model.domains if item.id == node)
        if parent is None:
            return
        if node in stack:
            raise ValueError(f"domain 父树存在循环：{' -> '.join((*stack, node))}")
        check_parent(parent, (*stack, node))

    for domain in model.domains:
        check_parent(domain.id)
    for tool in model.tools:
        if tool.domain_id not in domain_ids:
            raise ValueError(f"tool {tool.id}.domain_id 未知：{tool.domain_id}")
        if tool.strategy_id is not None and tool.strategy_id not in strategy_ids:
            raise ValueError(f"tool {tool.id}.strategy_id 未知：{tool.strategy_id}")
        if not tool.neutral_local and tool.strategy_id is None:
            raise ValueError(f"tool {tool.id} 必须声明 strategy 或 neutral_local")
        if any(target not in tool_ids for target in tool.enables):
            raise ValueError(f"tool {tool.id}.enables 含未知工具")
        if any(target not in tool_ids for target in tool.relations):
            raise ValueError(f"tool {tool.id}.relations 含未知工具")
    edges = tuple((tool.id, target) for tool in model.tools for target in tool.enables)
    depths = _depth(edges)
    object.__setattr__(model, "enables", edges)
    object.__setattr__(model, "enables_depth", depths)


def validate_links(
    model: LayerModel, actions: tuple[ActionCard, ...], relations: tuple[Relation, ...]
) -> None:
    """核对层级索引与行动源，避免独立登记出不一致的关系。"""

    by_action = {action.id: action for action in actions}
    for tool in model.tools:
        action = by_action.get(tool.id)
        if action is None:
            raise ValueError(f"工具缺少行动：{tool.id}")
        expected_relations = {
            relation.target for relation in relations if relation.source == tool.id
        }
        if set(tool.relations) != expected_relations:
            raise ValueError(f"工具关系与行动源不一致：{tool.id}")
        if set(tool.enables) != set(action.enables):
            raise ValueError(f"工具使能与行动源不一致：{tool.id}")


__all__ = [
    "DEFAULT_SOURCE",
    "DomainLayer",
    "LayerModel",
    "StrategyLayer",
    "ToolLayer",
    "load",
    "validate",
    "validate_links",
]
