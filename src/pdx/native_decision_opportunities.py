"""Exact Olympic decision: bounded administrative exposure, native reward retained."""

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

PARAMETERS = config.REPO / "mod/decisions/native_decision_opportunities.toml"
FROZEN = config.REPO / "research/vanilla-ai/1.14.5/native-decision-opportunities.json"
SOURCE = "common/decisions/00_decisions.txt"
HELP = "common/decisions/000_decisions_help.txt"
MODIFIERS = "common/static_modifiers/04_decision_modifiers.txt"
VALUES = "common/script_values/event_values.txt"
OUTPUT_SOURCE = "common/decisions/canal_decisions.txt"
OUTPUT_VALUES = "common/script_values/negotiation_values.txt"
OUTPUT_EFFECTS = "common/scripted_effects/04_negotiation_scripted_effects.txt"
SOURCES = frozenset({SOURCE, HELP, MODIFIERS, VALUES, OUTPUT_SOURCE, OUTPUT_VALUES, OUTPUT_EFFECTS})
DEFINITION = "revive_olympic_games_decision"
FIELD = f"{DEFINITION}.ai_chance"
FIELDS = (FIELD,)
_READERS = {
    "bureaucracy": {
        "engine": "bureaucracy",
        "scope": "root",
        "unit": "capacity_balance",
        "kind": "number",
    },
    "olympic_bureaucracy_output": {
        "engine": "produced_bureaucracy",
        "scope": "root",
        "unit": "capacity_output",
        "kind": "number",
        "minimum": 0,
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
        or set(data["sources"]) != SOURCES
        or any(
            not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value)
            for value in data["sources"].values()
        )
        or set(data["tuning"]) != {"thin_buffer", "strong_exposure"}
        or any(
            type(value) not in {int, float} or not math.isfinite(value) or not 0.75 <= value < 1
            for value in data["tuning"].values()
        )
        or not data["tuning"]["strong_exposure"] < data["tuning"]["thin_buffer"]
    ):
        raise ValueError("国家决议schema/完整来源/正倍率强弱边界无效")
    return data


def _block(parent: Block, key: str) -> Block:
    rows = parent.all(key)
    if len(rows) != 1 or rows[0].op != "=" or not isinstance(rows[0].value, Block):
        raise ValueError(f"国家决议原版块缺失或不唯一：{key}")
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
        or set(data["raw_source_hashes"]) != SOURCES
        or set(data["inputs"]) != SOURCES
        or set(data["contracts"])
        != {DEFINITION, "reward_modifier", "cost_modifier", "duration_days", "output_arithmetic"}
    ):
        raise ValueError("国家决议冻结完整底本合同无效")
    return cast("dict[str, Any]", data)


def frozen_inputs() -> dict[str, str]:
    inputs = _frozen()["inputs"]
    verify_inputs(inputs)
    return cast("dict[str, str]", inputs)


def verify_inputs(inputs: Mapping[str, str]) -> None:
    """Protect all source siblings, exact country consumer, reward and cost references."""
    roots = {}
    for source, digest in load()["sources"].items():
        text = inputs.get(source)
        if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != digest:
            raise ValueError(f"国家决议完整原版来源漂移：{source}")
        parsed = parse_text(text, path=source)
        if parsed.errors:
            raise ValueError(f"国家决议完整原版解析失败：{source}")
        roots[source] = parsed.root
    for statement in (
        "A decision is evaluated in country scope.",
        "The scripted weight which determines how likely AI is to take it amongst all possible decisions (country scope).",
        "If it evaluates to 0, AI will not take the decision. Evaluates to 1 if unspecified",
    ):
        if statement not in inputs[HELP]:
            raise ValueError("国家决议country ROOT/相对权重/拒绝零规范缺失")
    contracts = _frozen()["contracts"]
    decision = _block(roots[SOURCE], DEFINITION)
    if _shape(decision) != contracts[DEFINITION]:
        raise ValueError("奥林匹克完整资格/执行/评分父结构漂移")
    expected = parse_text(
        "value = 0 if = { limit = { bureaucracy > 0 } add = 5 } "
        "if = { limit = { OR = { is_diplomatic_play_committed_participant = yes "
        "is_at_war = yes } } multiply = 0 }"
    ).root
    if _shape(_block(decision, "ai_chance")) != _shape(expected):
        raise ValueError("奥林匹克原版5分/战争博弈终结零漂移")
    for name, contract, field, value in (
        ("modifier_olympic_games", "reward_modifier", "country_prestige_add", "100"),
        (
            "modifier_olympic_games_bureaucracy",
            "cost_modifier",
            "country_bureaucracy_mult",
            "-0.1",
        ),
    ):
        modifier = _shape(_block(roots[MODIFIERS], name))
        if modifier != contracts[contract] or [field, "=", value] not in modifier:
            raise ValueError(f"奥林匹克实际收益/行政成本漂移：{name}")
    duration = roots[VALUES].all("short_modifier_time")
    if (
        len(duration) != 1
        or duration[0].op != "="
        or not isinstance(duration[0].value, Scalar)
        or duration[0].value.unquoted != "913"
        or contracts["duration_days"] != 913
    ):
        raise ValueError("奥林匹克实际913天承诺漂移")
    arithmetic = _shape(_block(roots[OUTPUT_VALUES], "slight_bureaucracy_amount"))
    if arithmetic != contracts["output_arithmetic"] or arithmetic != [
        ["add", "=", "bureaucracy_usage"],
        ["multiply", "=", "1.10"],
        ["subtract", "=", "produced_bureaucracy"],
    ]:
        raise ValueError("行政产出数值getter原版算术身份漂移")
    survey = _block(roots[OUTPUT_SOURCE], "suez_survey_decision")
    if ["produced_bureaucracy", ">", "1000"] not in _shape(_block(survey, "possible")):
        raise ValueError("行政产出getter失去原版country决议数值比较")


def consumer_catalog() -> tuple[dict[str, Any], ...]:
    """One exact relative-weight consumer; no claim of exact post-action balance."""
    verify_inputs(_frozen()["inputs"])
    return (
        {
            "source": SOURCE,
            "field": FIELD,
            "definition": DEFINITION,
            "actor": "root",
            "target": "none",
            "native_root": "country",
            "operation": "multiply",
            "vanilla_tail": "retain",
            "native_base": 0,
            "positive_native_weight": 5,
            "reward_prestige": 100,
            "cost_modifier": "modifier_olympic_games_bureaucracy",
            "cost_source": MODIFIERS,
            "cost_multiplier": -0.1,
            "duration_days": 913,
            "scope_source": HELP,
            "unknown_policy": "balance_unknown_bounded_cost_requires_actual_country_anchor; output_unknown_only_exits_scale_tier",
            "calibration": "bounded_design_assumption_not_exact_ratio_or_marginal_loss",
        },
    )


def derive(adapters: Mapping[str, Any]) -> dict[str, Any]:
    """Three same-cause tiers; output alone never penalizes a country."""
    data = load()
    consumer_catalog()
    for key, expected in _READERS.items():
        if key in adapters["readers"] and adapters["readers"][key] != expected:
            raise ValueError(f"国家决议Reader完整身份冲突：{key}")
    rules = []
    for offset, (name, factor, conditions) in enumerate(
        (
            ("thin_buffer", "thin_buffer", [("bureaucracy", "<", 500)]),
            ("very_thin_buffer", "strong_exposure", [("bureaucracy", "<", 100)]),
            (
                "output_exposure",
                "strong_exposure",
                [("bureaucracy", "<", 500), ("olympic_bureaucracy_output", ">=", 5000)],
            ),
        )
    ):
        rule: dict[str, Any] = {
            "id": f"olympic_{name}",
            "source": SOURCE,
            "field": FIELD,
            "domain": "political",
            "priority": 79300 + offset,
            "operation": "multiply",
            "value": data["tuning"][factor],
            "semantic_role": "cost",
            "contribution_group": "olympic_administration_exposure",
            "conditions": [
                {"fact": fact, "op": op, "value": threshold} for fact, op, threshold in conditions
            ],
            "why": "原版赛事持续913天降低行政产出乘数0.1；薄净余额与薄余额且大产出暴露属于同一行政风险分档取强。阈值是有界设计假设，不是精确比例或执行后损失；大产出单独不降权。",
            "counterexample": "保留原版正行政余额才加5、战争/博弈终结0、GRE/科技/一次资格、全部同源决议与真实收益/成本执行。产出未知仅退出规模强档，已知余额成本不消失；玩家和关闭原样。",
        }
        if name == "very_thin_buffer":
            rule.update(
                conservative_unknown_facts=["bureaucracy"],
                unknown_cost_required_known_facts=["cost_country_population"],
                unknown_cost_basis="精确赛事确定具有-0.1行政产出乘数、913天承诺；本国实体已证而余额未知时保留有限保守成本，不推定行政亏空；本国实体也未知时仅退出该未知分支，已知成本照常。",
            )
        rules.append(rule)
    return {
        "sources": dict(data["sources"]),
        "readers": {key: dict(cast("dict[str, Any]", value)) for key, value in _READERS.items()},
        "rules": rules,
    }
