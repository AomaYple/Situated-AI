"""Three native famine buttons, expressed by the shared bounded rule algebra.

Owned-state famine is necessary evidence. Railway observations strengthen only
the effects the native button improves. Work camps retain a separate mortality
penalty. Fiscal terms describe observed commitment pressure, never affordability.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from . import config
from .model import Assignment, Block, Scalar
from .parser import parse_text

PARAMETERS = config.REPO / "mod/decisions/famine_opportunities.toml"
FROZEN = config.REPO / "research/vanilla-ai/1.14.5/famine-opportunities.json"
SOURCE = "common/scripted_buttons/04_indian_famines_buttons.txt"
JOURNAL = "common/journal_entries/04_indian_famines.txt"
HELP = "common/scripted_buttons/scripted_buttons.md"
MODIFIERS = "common/static_modifiers/00_ip2_02_modifiers.txt"
VALUES = "common/script_values/event_values.txt"
FINANCE = "events/brazil/amazonas.txt"
SOURCES = frozenset({SOURCE, JOURNAL, HELP, MODIFIERS, VALUES, FINANCE})
NAMES = ("relief_kitchens", "work_camps", "epidemic_control")
QUERY_PARAMETER = "famine_query"
READER = "famine_affected"
RAILWAY = "famine_railway"
NONRAILWAY = "famine_nonrailway"
_DEFAULT = {"engine": "in_default", "scope": "root", "unit": "boolean", "kind": "boolean"}
_COST_SCALE = {
    "relief_kitchens": "money_amount_multiplier_medium",
    "work_camps": "money_amount_multiplier_very_small",
    "epidemic_control": "money_amount_multiplier_small",
}
_EFFECTS = {
    "relief_kitchens": {
        "state_radicals_from_political_movements_mult": "-0.05",
        "state_mortality_mult": "-0.01",
    },
    "improved_relief_kitchens": {
        "state_radicals_from_political_movements_mult": "-0.1",
        "state_mortality_mult": "-0.02",
    },
    "work_camps": {
        "state_welfare_payments_add": "0.15",
        "state_mortality_mult": "0.02",
        "state_construction_mult": "0.05",
    },
    "improved_work_camps": {
        "state_welfare_payments_add": "0.3",
        "state_mortality_mult": "0.01",
        "state_construction_mult": "0.1",
    },
    "epidemic_control": {"state_mortality_mult": "-0.02", "state_birth_rate_mult": "0.02"},
    "improved_epidemic_control": {"state_mortality_mult": "-0.04", "state_birth_rate_mult": "0.04"},
}


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
        or set(data["tuning"]) != set(NAMES)
    ):
        raise ValueError("饥荒schema或完整原版来源无效")
    for name, tuning in data["tuning"].items():
        keys = {"benefit", "railway_benefit", "commitment", "financing"}
        if name == "work_camps":
            keys |= {"mortality", "nonrailway_mortality"}
        if set(tuning) != keys or any(
            type(v) not in {int, float} or not math.isfinite(v) for v in tuning.values()
        ):
            raise ValueError("饥荒独立收益/费用/死亡参数无效")
        if not 1 < tuning["benefit"] < tuning["railway_benefit"] <= 1.5 or any(
            not 0.75 <= tuning[k] < 1 for k in keys - {"benefit", "railway_benefit"}
        ):
            raise ValueError("饥荒倍率必须为有限正值，铁路只能提升实际收益")
    return data


def _block(parent: Block, key: str) -> Block:
    rows = parent.all(key)
    if len(rows) != 1 or rows[0].op != "=" or not isinstance(rows[0].value, Block):
        raise ValueError(f"饥荒原版唯一块漂移：{key}")
    return rows[0].value


def _shape(block: Block) -> list[Any]:
    result: list[Any] = []
    for row in block.items:
        if isinstance(row, Scalar):
            result.append(row.unquoted)
        elif (
            isinstance(row, Assignment)
            and row.prefix is None
            and isinstance(row.value, (Block, Scalar))
        ):
            result.append(
                [
                    row.key,
                    row.op,
                    _shape(row.value) if isinstance(row.value, Block) else row.value.unquoted,
                ]
            )
        else:
            raise ValueError("饥荒原版AST包含未登记结构")
    return result


def _snapshot() -> dict[str, Any]:
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
        or set(data["inputs"]) != SOURCES
        or set(data["raw_source_hashes"]) != SOURCES
        or set(data["contracts"]) != {SOURCE, JOURNAL, MODIFIERS, VALUES, FINANCE}
    ):
        raise ValueError("饥荒冻结完整原版合同无效")
    return cast("dict[str, Any]", data)


def verify_inputs(inputs: Mapping[str, str]) -> tuple[str, ...]:
    """Check full-source identities and complete qualification/effect/lifecycle ASTs."""
    roots = {}
    snapshot = _snapshot()
    for source, digest in load()["sources"].items():
        text = inputs.get(source)
        if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != digest:
            raise ValueError(f"饥荒完整原版来源漂移：{source}")
        if source == HELP:
            if "#Country scope\n          ai_chance" not in text:
                raise ValueError("饥荒按钮country ROOT帮助证据漂移")
            continue
        parsed = parse_text(text)
        if parsed.errors:
            raise ValueError(f"饥荒完整原版解析失败：{source}")
        roots[source] = parsed.root
        if _shape(parsed.root) != snapshot["contracts"][source]:
            raise ValueError(f"饥荒完整父结构AST漂移：{source}")
    journal = _block(roots[JOURNAL], "je_indian_famines")
    attached = [
        r.value.unquoted for r in journal.all("scripted_button") if isinstance(r.value, Scalar)
    ]
    if attached != [f"je_indian_famines_button_{name}" for name in NAMES]:
        raise ValueError("饥荒实际JE按钮接线漂移")
    for name in NAMES:
        button = _block(roots[SOURCE], f"je_indian_famines_button_{name}")
        if _shape(_block(button, "ai_chance")) != [["value", "=", "10"]] or _shape(
            _block(button, "cooldown")
        ) != [["days", "=", "365"]]:
            raise ValueError("饥荒原版基数/冷却漂移")
        effect = _block(button, "effect")
        if _shape(_block(effect, "set_variable")) != [
            ["name", "=", f"{name}_button_var"],
            ["months", "=", "12"],
        ]:
            raise ValueError("饥荒原版selected生命周期漂移")
        if _shape(_block(effect, "add_modifier")) != [
            ["name", "=", f"{name}_costs_modifier"],
            ["months", "=", "12"],
            ["multiplier", "=", _COST_SCALE[name]],
        ]:
            raise ValueError("饥荒原版真实费用倍率漂移")
        states = _block(_block(effect, "hidden_effect"), "every_scope_state")
        if _shape(_block(states, "limit")) != [["has_famine", "=", "yes"]] or _shape(
            _block(_block(states, "if"), "limit")
        ) != [["has_building", "=", "building_railway"]]:
            raise ValueError("饥荒真实owned州暴露/铁路效果分支漂移")
        for mode in (name, f"improved_{name}"):
            modifier = _block(roots[MODIFIERS], f"{mode}_effect_modifier")
            actual = {
                r.key: r.value.unquoted
                for r in modifier.assignments()
                if isinstance(r.value, Scalar) and r.key != "icon"
            }
            if actual != _EFFECTS[mode]:
                raise ValueError("饥荒真实收益/劳役营正死亡代价漂移")
        costs = _block(roots[MODIFIERS], f"{name}_costs_modifier")
        if ["country_expenses_add", "=", "1"] not in _shape(costs):
            raise ValueError("饥荒真实经常费用方向漂移")
    if ["in_default", "=", "no"] not in _shape(
        _block(_block(roots[FINANCE], "amazonas.1"), "trigger")
    ):
        raise ValueError("饥荒财政country ROOT reader证据漂移")
    return (
        f"{HELP}:19",
        f"{JOURNAL}:6",
        f"{SOURCE}:15",
        f"{SOURCE}:83",
        f"{SOURCE}:151",
        f"{MODIFIERS}:39",
        f"{VALUES}:49",
        f"{FINANCE}:24",
    )


def frozen_inputs() -> dict[str, str]:
    inputs = _snapshot()["inputs"]
    verify_inputs(inputs)
    return cast("dict[str, str]", inputs)


@dataclass(frozen=True, slots=True)
class FamineStateQuery:
    observation: Literal["affected", "railway", "nonrailway"]


@dataclass(frozen=True, slots=True)
class CompiledFamineStateQuery:
    expression: str
    references: tuple[str, ...]
    source_hashes: tuple[tuple[str, str], ...]
    local_collections: tuple[str, ...] = ("owned_states",)
    actor: Literal["country"] = "country"
    kind: Literal["boolean"] = "boolean"
    unknown_policy: str = "any_true=true; complete_empty=false; no_true_with_unknown_member=unknown"
    world_scans: int = 0
    runtime_cost: str = (
        "bounded existential owned-state traversal; no world scan or persistent state"
    )


def query_from_reader(engine: str, parameters: Mapping[str, str]) -> FamineStateQuery:
    if not isinstance(parameters, Mapping):
        raise ValueError("饥荒查询参数必须为字符串映射")
    if (
        engine != "any_scope_state"
        or set(parameters) != {QUERY_PARAMETER}
        or not isinstance(parameters[QUERY_PARAMETER], str)
        or parameters[QUERY_PARAMETER] not in {"affected", "railway", "nonrailway"}
    ):
        raise ValueError("饥荒查询仅允许固定owned州暴露签名")
    return FamineStateQuery(
        cast("Literal['affected', 'railway', 'nonrailway']", parameters[QUERY_PARAMETER])
    )


def render_query(query: FamineStateQuery) -> str:
    if (
        type(query) is not FamineStateQuery
        or not isinstance(query.observation, str)
        or query.observation not in {"affected", "railway", "nonrailway"}
    ):
        raise ValueError("饥荒查询类型或暴露模式无效")
    extra = {
        "affected": "",
        "railway": " has_building = building_railway",
        "nonrailway": " NOT = { has_building = building_railway }",
    }[query.observation]
    return f"any_scope_state = {{ has_famine = yes{extra} }}"


def required_query_sources(query: FamineStateQuery) -> tuple[str, ...]:
    render_query(query)
    return tuple(sorted(SOURCES))


def compile_query(query: FamineStateQuery, inputs: Mapping[str, str]) -> CompiledFamineStateQuery:
    expression = render_query(query)
    references = verify_inputs(inputs)
    return CompiledFamineStateQuery(
        expression, references, tuple(sorted(load()["sources"].items()))
    )


def consumer_catalog() -> tuple[dict[str, Any], ...]:
    inputs = frozen_inputs()
    root = parse_text(inputs[SOURCE]).root
    return tuple(
        {
            "source": SOURCE,
            "definition": f"je_indian_famines_button_{name}",
            "field": f"je_indian_famines_button_{name}.ai_chance",
            "native_root": "country",
            "actor": "root",
            "actor_path": [],
            "target": "none",
            "role": "native_famine_button_relative_weight",
            "interface_kind": "scripted_value",
            "operation": "multiply",
            "native_base": 10,
            "vanilla_tail": "retain",
            "scope_source": HELP,
            "scope_evidence_line": 19,
            "source_sha256": load()["sources"][SOURCE],
            "score_evidence_line": _block(root, f"je_indian_famines_button_{name}")
            .all("ai_chance")[0]
            .line,
            "insertion": "append_positive_multiplier_to_unique_ai_chance",
            "cost_source": MODIFIERS,
            "cost_modifier": f"{name}_costs_modifier",
            "cost_scale_source": VALUES,
            "cost_scale": _COST_SCALE[name],
            "cost_duration_months": 12,
            "effect_source": MODIFIERS,
            "effects": {k: v for k, v in _EFFECTS.items() if k in {name, f"improved_{name}"}},
            "effect_scope": "owned_states_with_has_famine; railway_changes_only_native_effect_tier",
        }
        for name in NAMES
    )


def derive(adapters: Mapping[str, Any]) -> dict[str, Any]:
    data = load()
    consumer_catalog()
    if "default" in adapters.get("readers", {}) and adapters["readers"]["default"] != _DEFAULT:
        raise ValueError("饥荒default Reader完整身份冲突")
    readers = {
        key: {
            "engine": "any_scope_state",
            "scope": "root",
            "kind": "boolean",
            "unit": "boolean",
            "parameters": {QUERY_PARAMETER: mode},
        }
        for key, mode in ((READER, "affected"), (RAILWAY, "railway"), (NONRAILWAY, "nonrailway"))
    }
    readers["default"] = dict(_DEFAULT)
    rules = []
    for index, name in enumerate(NAMES):
        field = f"je_indian_famines_button_{name}.ai_chance"
        tuning = data["tuning"][name]
        definitions: list[tuple[str, str, str, list[dict[str, Any]], list[str]]] = [
            ("benefit", "actual_famine_effect", "benefit", [], []),
            (
                "railway_benefit",
                "actual_famine_effect",
                "benefit",
                [{"fact": RAILWAY, "op": "=", "value": True}],
                [],
            ),
            ("commitment", "twelve_month_expense", "cost", [], []),
            (
                "financing",
                "observed_fiscal_pressure",
                "cost",
                [{"fact": "default", "op": "=", "value": True}],
                ["default"],
            ),
        ]
        if name == "work_camps":
            definitions.extend(
                (
                    ("mortality", "unavoidable_mortality", "cost", [], []),
                    (
                        "nonrailway_mortality",
                        "nonrailway_extra_mortality",
                        "cost",
                        [{"fact": NONRAILWAY, "op": "=", "value": True}],
                        [NONRAILWAY],
                    ),
                )
            )
        for offset, (key, group, role, conditions, unknown) in enumerate(definitions):
            rule: dict[str, Any] = {
                "id": f"famine_{name}_{key}",
                "source": SOURCE,
                "field": field,
                "domain": "political",
                "priority": 87000 + index * 10 + offset,
                "operation": "multiply",
                "value": tuning[key],
                "semantic_role": role,
                "contribution_group": f"famine_{name}_{group}",
                "conditions": [{"fact": READER, "op": "=", "value": True}, *conditions],
                "why": "实际本国饥荒州的具体效果与12月经常成本联合；劳役营正死亡独立成本，铁路只影响原版效果档位",
                "counterexample": "必要饥荒未知无增量；default未知不解除融资成本，非铁路暴露未知不解除额外死亡成本；非default不预测支付能力；不改资格/效果/变量/365日冷却，正倍率保留原版拒绝，玩家/关闭回退原10",
            }
            if key == "railway_benefit":
                rule["auxiliary_facts"] = [RAILWAY]
            if unknown:
                rule["conservative_unknown_facts"] = unknown
                rule["unknown_cost_basis"] = (
                    "原版真实12月承诺或劳役营死亡成本，辅助观察缺失保留有限成本；必要饥荒必须明确为真"
                )
            rules.append(rule)
    return {
        "sources": dict(data["sources"]),
        "readers": readers,
        "rules": rules,
        "covered": [
            {
                "id": f"famine_{name}",
                "source": SOURCE,
                "field": f"je_indian_famines_button_{name}.ai_chance",
            }
            for name in NAMES
        ],
    }
