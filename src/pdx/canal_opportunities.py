"""Exact country canal survey and purchase choices with distinct marginal costs."""

from __future__ import annotations

import hashlib
import json
import math
import re
import tomllib
from typing import TYPE_CHECKING, Any, cast

from . import config
from .model import Block, Scalar
from .parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Mapping

PARAMETERS = config.REPO / "mod/decisions/canal_opportunities.toml"
FROZEN = config.REPO / "research/vanilla-ai/1.15.0/canal-opportunities.json"
SOURCE = "common/decisions/canal_decisions.txt"
HELP = "common/decisions/000_decisions_help.txt"
MODIFIERS = "common/static_modifiers/02_event_modifiers.txt"
PURCHASE_MODIFIERS = "common/static_modifiers/content_1_modifiers.txt"
NAMES = ("suez", "panama")
FIELDS = tuple(f"{name}_survey_decision.ai_chance" for name in NAMES)
PURCHASE_FIELDS = tuple(f"{name}_canal_purchase.ai_chance" for name in NAMES)
PURCHASE_WEEKLY_COST = 30000
PURCHASE_MONTHS = 120
_READERS = {
    "bureaucracy": {
        "engine": "bureaucracy",
        "scope": "root",
        "unit": "capacity_balance",
        "kind": "number",
    },
    "default": {"engine": "in_default", "scope": "root", "unit": "boolean", "kind": "boolean"},
    "net_surplus": {
        "engine": "net_total_income",
        "scope": "root",
        "unit": "currency_per_week",
        "kind": "number",
    },
    "cost_country_population": {
        "engine": "total_population",
        "scope": "root",
        "unit": "persons",
        "kind": "number",
        "minimum": 0,
    },
}


def load() -> dict[str, Any]:
    data = tomllib.loads(PARAMETERS.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "sources", "tuning"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or set(data["sources"]) != {SOURCE, HELP, MODIFIERS, PURCHASE_MODIFIERS}
        or any(
            not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value)
            for value in data["sources"].values()
        )
        or set(data["tuning"])
        != {"administration", "financing", "purchase_shortfall", "purchase_deficit"}
        or any(
            type(value) not in {int, float} or not math.isfinite(value) or not 0.75 <= value < 1
            for value in data["tuning"].values()
        )
    ):
        raise ValueError("运河机会schema/来源/正倍率边界无效")
    if not data["tuning"]["purchase_deficit"] < data["tuning"]["purchase_shortfall"]:
        raise ValueError("运河购买现金流成本必须保持亏损强档顺序")
    return data


def _block(parent: Block, key: str) -> Block:
    rows = parent.all(key)
    if len(rows) != 1 or rows[0].op != "=" or not isinstance(rows[0].value, Block):
        raise ValueError(f"运河原版块缺失或不唯一：{key}")
    return rows[0].value


def _shape(block: Block) -> list[Any]:
    return [
        [
            row.key,
            row.op,
            _shape(row.value)
            if isinstance(row.value, Block)
            else row.value.unquoted
            if isinstance(row.value, Scalar)
            else None,
        ]
        for row in block.assignments()
    ]


def _frozen() -> dict[str, Any]:
    data = json.loads(FROZEN.read_text(encoding="utf-8"))
    if (
        set(data)
        != {
            "schema",
            "evidence",
            "normalization",
            "source_hashes",
            "raw_source_hashes",
            "inputs",
            "contracts",
        }
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or data["evidence"] != "static_complete_native_sources_not_engine_execution"
        or data["normalization"] != "utf8_without_bom_lf_preserve_whitespace"
        or data["source_hashes"] != load()["sources"]
        or set(data["inputs"]) != {SOURCE, HELP, MODIFIERS, PURCHASE_MODIFIERS}
        or set(data["raw_source_hashes"]) != {SOURCE, HELP, MODIFIERS, PURCHASE_MODIFIERS}
        or set(data["contracts"])
        != {
            "suez_survey_decision",
            "panama_survey_decision",
            "modifiers",
            "suez_canal_purchase",
            "panama_canal_purchase",
            "purchase_modifiers",
        }
    ):
        raise ValueError("运河冻结完整底本合同无效")
    return cast("dict[str, Any]", data)


def frozen_inputs() -> dict[str, str]:
    inputs = _frozen()["inputs"]
    verify_inputs(inputs)
    return cast("dict[str, str]", inputs)


def verify_inputs(inputs: Mapping[str, str]) -> None:
    """Verify full documents, country help contract and exact decision/effect AST."""
    parameters = load()
    roots = {}
    for source, digest in parameters["sources"].items():
        text = inputs.get(source)
        if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != digest:
            raise ValueError(f"运河完整原版来源漂移：{source}")
        parsed = parse_text(text)
        if parsed.errors:
            raise ValueError(f"运河完整原版解析失败：{source}")
        roots[source] = parsed.root
    help_text = inputs[HELP]
    for statement in (
        "A decision is evaluated in country scope.",
        "The scripted weight which determines how likely AI is to take it amongst all possible decisions (country scope).",
        "If it evaluates to 0, AI will not take the decision. Evaluates to 1 if unspecified",
    ):
        if statement not in help_text:
            raise ValueError("运河country scope/拒绝零值规范缺失")
    frozen = _frozen()["contracts"]
    for name in NAMES:
        definition = f"{name}_survey_decision"
        decision = _block(roots[SOURCE], definition)
        if _shape(decision) != frozen[definition]:
            raise ValueError(f"运河完整候选AST漂移：{definition}")
        chance = _shape(_block(decision, "ai_chance"))
        if chance != [
            ["value", "=", "0"],
            [
                "if",
                "=",
                [["limit", "=", [["produced_bureaucracy", ">", "5000"]]], ["add", "=", "10"]],
            ],
            [
                "if",
                "=",
                [
                    ["limit", "=", [["has_strategy", "=", "ai_strategy_armed_isolationism"]]],
                    ["multiply", "=", "0"],
                ],
            ],
            [
                "if",
                "=",
                [
                    [
                        "limit",
                        "=",
                        [
                            [
                                "OR",
                                "=",
                                [
                                    ["is_diplomatic_play_committed_participant", "=", "yes"],
                                    ["is_at_war", "=", "yes"],
                                ],
                            ]
                        ],
                    ],
                    ["multiply", "=", "0"],
                ],
            ],
        ]:
            raise ValueError("运河原版评分/终结零值结构漂移")
        effects = _shape(_block(decision, "when_taken"))
        if ["add_modifier", "=", [["name", "=", f"modifier_surveying_{name}"]]] not in effects:
            raise ValueError("运河调查实际成本modifier未接入")
        modifier = _block(roots[MODIFIERS], f"modifier_surveying_{name}")
        if _shape(modifier) != frozen["modifiers"][name] or [
            "country_bureaucracy_cost_add",
            "=",
            "1000",
        ] not in _shape(modifier):
            raise ValueError("运河调查实际1000官僚负担漂移")
        _verify_purchase(name, roots, frozen)


def _verify_purchase(name: str, roots: Mapping[str, Block], frozen: Mapping[str, Any]) -> None:
    definition = f"{name}_canal_purchase"
    purchase = _block(roots[SOURCE], definition)
    if _shape(purchase) != frozen[definition]:
        raise ValueError(f"运河完整购买候选AST漂移：{definition}")
    if _shape(_block(purchase, "ai_chance")) != [
        ["value", "=", "0"],
        ["if", "=", [["limit", "=", [["gold_reserves", ">", "15000000"]]], ["add", "=", "10"]]],
        [
            "if",
            "=",
            [
                ["limit", "=", [["net_fixed_income", ">", "100000"], ["gold_reserves", ">", "0"]]],
                ["add", "=", "10"],
            ],
        ],
        [
            "if",
            "=",
            [
                [
                    "limit",
                    "=",
                    [
                        [
                            "OR",
                            "=",
                            [
                                ["is_diplomatic_play_committed_participant", "=", "yes"],
                                ["is_at_war", "=", "yes"],
                            ],
                        ]
                    ],
                ],
                ["multiply", "=", "0"],
            ],
        ],
    ]:
        raise ValueError("运河购买储备/固定收入/终结零评分结构漂移")
    taken = _block(purchase, "when_taken")
    branch = _block(taken, "if")
    if _shape(_block(branch, "add_modifier")) != [
        ["name", "=", f"{name}_purchase"],
        ["months", "=", str(PURCHASE_MONTHS)],
    ]:
        raise ValueError("运河购买实际120月买方modifier挂接漂移")
    modifier = _shape(_block(roots[PURCHASE_MODIFIERS], f"{name}_purchase"))
    if (
        modifier != frozen["purchase_modifiers"][name]
        or ["country_expenses_add", "=", str(PURCHASE_WEEKLY_COST)] not in modifier
    ):
        raise ValueError("运河购买实际每周30000开支漂移")


def consumer_catalog() -> tuple[dict[str, Any], ...]:
    """Four exact country consumers; survey and purchase costs remain distinct."""
    verify_inputs(_frozen()["inputs"])
    surveys = tuple(
        {
            "source": SOURCE,
            "field": field,
            "definition": f"{name}_survey_decision",
            "actor": "root",
            "target": "none",
            "native_root": "country",
            "operation": "multiply",
            "vanilla_tail": "retain",
            "native_base": 0,
            "cost": 1000,
            "cost_unit": "capacity_balance",
            "cost_source": MODIFIERS,
            "cost_modifier": f"modifier_surveying_{name}",
            "scope_source": HELP,
        }
        for name, field in zip(NAMES, FIELDS, strict=True)
    )
    purchases = tuple(
        {
            "source": SOURCE,
            "field": field,
            "definition": f"{name}_canal_purchase",
            "actor": "root",
            "target": "none",
            "native_root": "country",
            "operation": "multiply",
            "vanilla_tail": "retain",
            "native_base": 0,
            "cost": PURCHASE_WEEKLY_COST,
            "cost_unit": "currency_per_week",
            "cost_source": PURCHASE_MODIFIERS,
            "cost_modifier": f"{name}_purchase",
            "duration_months": PURCHASE_MONTHS,
            "scope_source": HELP,
            "unknown_policy": "cashflow_unknown_bounded_cost_requires_actual_country_anchor; core_unknown_native",
        }
        for name, field in zip(NAMES, PURCHASE_FIELDS, strict=True)
    )
    return surveys + purchases


def derive(adapters: Mapping[str, Any]) -> dict[str, Any]:
    """Separate survey capacity from purchase cashflow; unknown retains native gates."""
    data = load()
    consumer_catalog()
    for key, expected in _READERS.items():
        if key in adapters["readers"] and adapters["readers"][key] != expected:
            raise ValueError(f"运河Reader完整身份冲突：{key}")
    rules = []
    for index, (name, field) in enumerate(zip(NAMES, FIELDS, strict=True)):
        for offset, (reason, fact, op, threshold) in enumerate(
            (
                ("administration", "bureaucracy", "<", 1000),
                ("financing", "default", "=", True),
            )
        ):
            rules.append(
                {
                    "id": f"canal_{name}_{reason}",
                    "source": SOURCE,
                    "field": field,
                    "domain": "geography",
                    "priority": 79000 + index * 2 + offset,
                    "operation": "multiply",
                    "value": data["tuning"][reason],
                    "semantic_role": "cost",
                    "contribution_group": f"canal_{reason}",
                    "conditions": [{"fact": fact, "op": op, "value": threshold}],
                    "why": "调查实际新增1000官僚负担：净余额不足的行政成本与已观察违约融资成本独立联合，不把总产出当可用余量。",
                    "counterexample": "正倍率保留原版0拒绝、全部资格/地理/科技、isolationism/war/play终结零分及原调查modifier/JE/变量执行；未知只回本项，不强制调查或假定运河建成。",
                }
            )
    for index, (name, field) in enumerate(zip(NAMES, PURCHASE_FIELDS, strict=True)):
        for offset, (reason, threshold) in enumerate(
            (("shortfall", PURCHASE_WEEKLY_COST), ("deficit", 0))
        ):
            rules.append(
                {
                    "id": f"canal_{name}_purchase_{reason}",
                    "source": SOURCE,
                    "field": field,
                    "domain": "geography",
                    "priority": 79004 + index * 2 + offset,
                    "operation": "multiply",
                    "value": data["tuning"][f"purchase_{reason}"],
                    "semantic_role": "cost",
                    "conservative_unknown_facts": ["net_surplus"],
                    "unknown_cost_required_known_facts": ["cost_country_population"],
                    "unknown_cost_basis": "精确购买具有原版每周30000、120月承诺；本国实体已证而净现金流未知时保留有限强档压力，不声称实际亏损；实体锚也未知时回原版。",
                    "contribution_group": "canal_purchase_cashflow",
                    "conditions": [{"fact": "net_surplus", "op": "<", "value": threshold}],
                    "why": "购买非玩家卖方土地时原版新增每周30000、120月开支；当前净总收支不足和既有亏损分档取强，独立于储备/净固定收入加分，不复制调查行政或通用违约成本。",
                    "counterexample": "当前现金流只是观察到的承受压力，不预测120月收入、付款后利润或完成转地；压力未知且本国实体已证时取有限保守成本而不推定亏损，实体核心未知回原版。正倍率保留原0、15m/100k评分、战争零、全部资格/变量/效果顺序及玩家卖方事件路径；玩家和关闭不干预。",
                }
            )
    return {
        "sources": dict(data["sources"]),
        "readers": {key: dict(cast("dict[str, Any]", value)) for key, value in _READERS.items()},
        "rules": rules,
    }
