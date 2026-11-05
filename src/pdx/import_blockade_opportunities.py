"""Observed market imports and owned-state blockade, without world scans.

Imports are market totals and may travel over land. They are not an observed
shipping lane, country import bill or convoy loss. The only writer is a
relative mission preference for an already existing secondary fleet.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from . import config
from .model import Block, Scalar
from .parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Mapping

PARAMETERS = config.REPO / "mod/decisions/import_blockade_opportunities.toml"
FROZEN = config.REPO / "research/vanilla-ai/1.14.5/import-blockade-opportunities.json"
TRADE = "events/trade_route_events.txt"
OPIUM = "common/journal_entries/00_opium.txt"
ALERTS = "common/alert_types/00_alert_types.txt"
PULSE = "common/on_actions/00_code_on_actions.txt"
GOODS = "common/goods/00_goods.txt"
SOURCES = frozenset({TRADE, OPIUM, ALERTS, PULSE, GOODS})
SOURCE = "common/ai_strategies/00_default_strategy.txt"
FIELD = "ai_strategy_default.fleet_compositions.secondary_fleet.mission_type_weights.protect_supply"
QUERY_PARAMETER = "import_blockade_query"
UNKNOWN_POLICY = (
    "missing_local_market_or_collection=unknown; complete_empty_collection=false; "
    "any_true=true; no_true_with_missing_member_observation=unknown; malformed_input=error"
)


def load() -> dict[str, Any]:
    data = tomllib.loads(PARAMETERS.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "sources", "tuning"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or set(data["sources"]) != SOURCES
        or any(
            not isinstance(v, str) or not re.fullmatch(r"[a-f0-9]{64}", v)
            for v in data["sources"].values()
        )
    ):
        raise ValueError("进口封锁机会schema或完整原版来源无效")
    tuning = data["tuning"]
    if (
        set(tuning) != {"arms_exposure", "owned_state_disruption"}
        or any(type(v) not in {int, float} or not math.isfinite(v) for v in tuning.values())
        or not 1 < tuning["arms_exposure"] <= tuning["owned_state_disruption"] <= 1.20
    ):
        raise ValueError("进口封锁偏好参数必须有限且在1到1.20之间")
    return data


def _child(block: Block, key: str) -> Block:
    rows = block.all(key)
    if len(rows) != 1 or rows[0].op not in {"=", "?="} or not isinstance(rows[0].value, Block):
        raise ValueError(f"进口封锁原版唯一块漂移：{key}")
    return rows[0].value


def _scalar(block: Block, key: str, op: str, value: str) -> int:
    rows = block.all(key)
    if (
        len(rows) != 1
        or rows[0].op != op
        or not isinstance(rows[0].value, Scalar)
        or rows[0].value.unquoted != value
    ):
        raise ValueError(f"进口封锁原版精确标量漂移：{key}")
    return rows[0].line


def _shape(block: Block) -> tuple:
    rows = []
    for row in block.assignments():
        if isinstance(row.value, Block):
            value: str | tuple = _shape(row.value)
        elif isinstance(row.value, Scalar):
            value = row.value.unquoted
        else:
            raise ValueError("进口封锁原版AST无值")
        rows.append((row.key, row.op, value))
    if len(rows) != len(block.items):
        raise ValueError("进口封锁原版证据块含非赋值项")
    return tuple(rows)


def _find_shape(block: Block, key: str, expected: tuple) -> int:
    found = []

    def walk(current: Block) -> None:
        for row in current.assignments():
            if isinstance(row.value, Block):
                if row.key == key and _shape(row.value) == expected:
                    found.append(row.line)
                walk(row.value)

    walk(block)
    if len(found) != 1:
        raise ValueError(f"进口封锁原版唯一完整消费者AST漂移：{key}")
    return found[0]


def _roots(inputs: Mapping[str, str]) -> dict[str, Block]:
    roots = {}
    for source, digest in load()["sources"].items():
        text = inputs.get(source)
        if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != digest:
            raise ValueError(f"进口封锁完整原版来源漂移：{source}")
        parsed = parse_text(text)
        if parsed.errors:
            raise ValueError(f"进口封锁完整原版解析失败：{source}")
        roots[source] = parsed.root
    return roots


def frozen_inputs() -> dict[str, str]:
    data = json.loads(FROZEN.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "evidence", "normalization", "source_hashes", "inputs"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or data["evidence"] != "static_complete_native_sources_not_engine_execution"
        or data["normalization"] != "utf8_without_bom_lf_preserve_whitespace"
        or data["source_hashes"] != load()["sources"]
        or not isinstance(data["inputs"], dict)
        or set(data["inputs"]) != SOURCES
    ):
        raise ValueError("进口封锁冻结完整原版合同无效")
    _roots(data["inputs"])
    return data["inputs"]


@dataclass(frozen=True, slots=True)
class ImportBlockadeQuery:
    observation: Literal["arms_import_volume", "arms_import_reliance", "owned_state_blockade"]


@dataclass(frozen=True, slots=True)
class CompiledImportBlockadeQuery:
    expression: str
    references: tuple[str, ...]
    source_hashes: tuple[tuple[str, str], ...]
    local_collections: tuple[str, ...]
    actor: str = "country"
    kind: str = "boolean"
    unknown_policy: str = UNKNOWN_POLICY
    world_scans: int = 0
    runtime_cost: str = "one local market lookup or existential owned-state traversal"


def query_from_reader(engine: str, parameters: Mapping[str, str]) -> ImportBlockadeQuery:
    modes = {
        "arms_import_volume": "market",
        "arms_import_reliance": "market",
        "owned_state_blockade": "any_scope_state",
    }
    if set(parameters) != {QUERY_PARAMETER} or modes.get(parameters[QUERY_PARAMETER]) != engine:
        raise ValueError("进口封锁查询必须保持精确本国market/owned-state与固定商品签名")
    mode = parameters[QUERY_PARAMETER]
    if mode == "arms_import_volume":
        return ImportBlockadeQuery("arms_import_volume")
    if mode == "arms_import_reliance":
        return ImportBlockadeQuery("arms_import_reliance")
    return ImportBlockadeQuery("owned_state_blockade")


def render_query(query: ImportBlockadeQuery) -> str:
    if type(query) is not ImportBlockadeQuery:
        raise ValueError("进口封锁查询类型无效")
    if query.observation == "arms_import_volume":
        return "market = { mg:small_arms = { market_goods_imports >= 5 } }"
    if query.observation == "arms_import_reliance":
        return "market = { market_imports_reliance = { goods = small_arms value > 0.25 } }"
    if query.observation == "owned_state_blockade":
        return "any_scope_state = { blockade_level > 0 }"
    raise ValueError("未登记的进口封锁查询；不接受任意getter/商品/阈值")


def required_query_sources(query: ImportBlockadeQuery) -> tuple[str, ...]:
    render_query(query)
    return tuple(sorted(SOURCES))


def verify_inputs(inputs: Mapping[str, str]) -> tuple[str, ...]:
    roots = _roots(inputs)
    references = []
    trade = roots[TRADE]
    for event_id in ("trade_route_events.1", "trade_route_events.2", "trade_route_events.3"):
        event = _child(trade, event_id)
        _scalar(event, "type", "=", "country_event")
        _scalar(event, "placement", "=", "ROOT")
    trigger = _child(_child(trade, "trade_route_events.1"), "trigger")
    markets = _child(trigger, "any_market")
    reliance = _child(_child(markets, "root.market"), "market_imports_reliance")
    if _shape(reliance) != (
        ("target", "=", "prev"),
        ("goods", "=", "small_arms"),
        ("value", ">", "0.25"),
    ):
        raise ValueError("进口依赖固定small_arms/target市场/比例AST漂移")
    references.append(f"{TRADE}:{markets.all('root.market')[0].line}")
    trigger = _child(_child(trade, "trade_route_events.2"), "trigger")
    amount = _child(_child(_child(trigger, "any_market"), "root.market"), "market_imports")
    if _shape(amount) != (
        ("target", "=", "prev"),
        ("goods", "=", "small_arms"),
        ("value", ">=", "5"),
    ):
        raise ValueError("进口数量固定small_arms/target市场/amount AST漂移")
    trigger = _child(_child(trade, "trade_route_events.3"), "trigger")
    # Optional target absent is independently demonstrated; preserve its exact shape.
    line = _find_shape(
        trigger, "market_imports_reliance", (("goods", "=", "wine"), ("value", ">=", "0.1"))
    )
    capital_market = _child(trigger, "capital.market")
    if not capital_market.all("market_imports_reliance"):
        raise ValueError("本国市场总依赖路径漂移")
    references.append(f"{TRADE}:{line}")
    imports = _child(
        _child(_child(_child(roots[OPIUM], "je_opium"), "complete"), "any_market"), "mg:opium"
    )
    line = _scalar(imports, "market_goods_imports", ">=", "200")
    references.append(f"{OPIUM}:{line}")
    # The fixed substituted commodity is a real goods identity, not free script text.
    _child(roots[GOODS], "small_arms")
    for alert_id in ("blockaded_hub_alert", "blockaded_state_alert"):
        alert = _child(roots[ALERTS], alert_id)
        _scalar(alert, "script_context", "=", "player_state")
        line = _scalar(_child(alert, "valid"), "blockade_level", ">", "0")
        references.append(f"{ALERTS}:{line}")
    pulse = _child(_child(roots[PULSE], "on_monthly_pulse_country"), "effect")
    # Full country -> enemy -> owned states occurrence proves state getter scope.
    expected = (
        ("is_blockaded_by", "=", "ROOT"),
        ("is_world_market_hub", "=", "yes"),
        ("num_world_market_hub_trade_center_levels", ">=", "100"),
        ("blockade_level", ">=", "1"),
    )
    line = _find_shape(pulse, "any_scope_state", expected)
    references.append(f"{PULSE}:{line}")
    # An own-state collection occurs under the country event, independently of enemies.
    own = _child(_child(_child(trade, "trade_route_events.1"), "trigger"), "NOT")
    if _shape(own) != (
        ("any_scope_state", "=", (("has_building", "=", "building_arms_industry"),)),
    ):
        raise ValueError("国家本国owned-state集合证据漂移")
    return tuple(references)


def compile_query(
    query: ImportBlockadeQuery, inputs: Mapping[str, str]
) -> CompiledImportBlockadeQuery:
    expression = render_query(query)
    references = verify_inputs(inputs)
    return CompiledImportBlockadeQuery(
        expression,
        references,
        tuple(sorted(load()["sources"].items())),
        ("owned_states",) if query.observation == "owned_state_blockade" else ("country_market",),
    )


def derive(adapters: Mapping[str, Any]) -> dict[str, Any]:
    data = load()
    verify_inputs(frozen_inputs())
    readers = {key: adapters["readers"][key] for key in ("war", "navy")}
    for mode in ("arms_import_volume", "arms_import_reliance", "owned_state_blockade"):
        readers["import_blockade_" + mode] = {
            "engine": "any_scope_state" if mode == "owned_state_blockade" else "market",
            "scope": "root",
            "kind": "boolean",
            "unit": "boolean",
            "parameters": {QUERY_PARAMETER: mode},
        }
    rules: list[dict[str, Any]] = []
    for suffix, observations in (
        ("arms_exposure", ("arms_import_volume", "arms_import_reliance")),
        ("owned_state_disruption", ("owned_state_blockade",)),
    ):
        rules.append(
            {
                "id": "import_blockade_actual_" + suffix,
                "source": SOURCE,
                "field": FIELD,
                "domain": "military",
                "priority": 79000 + len(rules),
                "operation": "multiply",
                "value": data["tuning"][suffix],
                "semantic_role": "benefit",
                # Existing steamers price/balance variants use the default group.
                # Actual import/blockade observations join that same envelope so
                # simultaneous proxies never add independent positive rewards.
                "conditions": [
                    {"fact": "war", "op": "=", "value": True},
                    {"fact": "navy", "op": ">", "value": 0},
                    *[
                        {"fact": "import_blockade_" + mode, "op": "=", "value": True}
                        for mode in observations
                    ],
                ],
                "why": "真实市场军需进口暴露或本国州封锁使既有次要舰队保护任务获得有限相对优先；同原因取强，不创建舰队或预算承诺",
                "counterexample": "军需进口是本国所属市场总量/依赖，可能陆运或涉及同市场其他国家，绝非已知海路进口、来源集中度或convoy损失。仅已存在海军且正在战争时表达有界风险偏好；进口与封锁同因取强，不重复steamers价格/余额代理。未知本地市场/州集合只退出新需要，不撤既有需要；无战争、无海军、玩家、关闭保持原版，主力舰队保护零保持零。",
            }
        )
    return {
        "sources": dict(data["sources"]),
        "readers": readers,
        "rules": rules,
        "covered": [{"id": "secondary_fleet_protect_supply", "source": SOURCE, "field": FIELD}],
    }
