"""Observed own multiwar support pressure at one existing conquest score.

The Boolean observes at least two own wars with own support below 50. It is
not a peace writer, defeat forecast, manpower measure or global war gate.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import config
from .model import Block, Scalar
from .parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Mapping

PARAMETERS = config.REPO / "mod/decisions/war_pressure_opportunities.toml"
FROZEN = config.REPO / "research/vanilla-ai/1.14.5/war-pressure-opportunities.json"
SOURCE = "common/ai_strategies/00_default_strategy.txt"
FIELD = "ai_strategy_default.wargoal_scores.conquer_state"
IDEOLOGIES = "common/ideologies/01_character_ideologies.txt"
EFFECTS = "common/scripted_effects/00_victoria_scripted_effects.txt"
REGIONS = "common/ai_regional_objectives/00_ai_regional_objectives.txt"
TRIGGER_DOC = "common/trigger_localization/trigger_localization.md"
SOURCES = frozenset({SOURCE, IDEOLOGIES, EFFECTS, REGIONS, TRIGGER_DOC})
READER = "own_multiwar_low_support"
RULE = "war_pressure_conquer_state"
QUERY_PARAMETER = "war_pressure_query"
GROUP = "target_reconstruction_opportunity"


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
    ):
        raise ValueError("本国战争压力schema或完整原版来源无效")
    tuning = data["tuning"]
    if (
        set(tuning) != {"conquest_opportunity_cost"}
        or type(tuning["conquest_opportunity_cost"]) not in {int, float}
        or not math.isfinite(tuning["conquest_opportunity_cost"])
        or not -3 <= tuning["conquest_opportunity_cost"] < 0
    ):
        raise ValueError("本国战争压力成本必须有限且在-3到0之间")
    return data


def _child(block: Block, key: str) -> Block:
    rows = block.all(key)
    if len(rows) != 1 or rows[0].op != "=" or not isinstance(rows[0].value, Block):
        raise ValueError(f"本国战争压力原版唯一块漂移：{key}")
    return rows[0].value


def _shape(block: Block) -> tuple:
    rows = []
    for row in block.assignments():
        if isinstance(row.value, Block):
            value: str | tuple = _shape(row.value)
        elif isinstance(row.value, Scalar):
            value = row.value.unquoted
        else:
            raise ValueError("本国战争压力原版AST无值")
        rows.append((row.key, row.op, value))
    if len(rows) != len(block.items):
        raise ValueError("本国战争压力证据含非赋值项")
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
        raise ValueError(f"本国战争压力完整消费者AST漂移：{key}")
    return found[0]


def _roots(inputs: Mapping[str, str]) -> dict[str, Block]:
    roots = {}
    for source, digest in load()["sources"].items():
        text = inputs.get(source)
        if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != digest:
            raise ValueError(f"本国战争压力完整原版来源漂移：{source}")
        if source == TRIGGER_DOC:
            continue
        parsed = parse_text(text)
        if parsed.errors:
            raise ValueError(f"本国战争压力完整原版解析失败：{source}")
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
        raise ValueError("本国战争压力冻结完整原版合同无效")
    _roots(data["inputs"])
    return data["inputs"]


def verify_inputs(inputs: Mapping[str, str]) -> tuple[str, ...]:
    roots = _roots(inputs)
    references = []
    weight = _child(_child(roots[IDEOLOGIES], "ideology_pacifist"), "interest_group_leader_weight")
    expected = (
        ("attacker_warleader", "?=", (("this", "=", "ROOT.owner"),)),
        ("has_war_support", "=", (("target", "=", "root.owner"), ("value", "<", "50"))),
    )
    # Prove the full country-owner -> own wars -> explicit own support shape,
    # not a loose token match or the support of the opponent/war leader.
    line = _find_shape(
        weight, "owner", (("is_at_war", "=", "yes"), ("any_scope_war", "=", expected))
    )
    references.append(f"{IDEOLOGIES}:{line}")
    national = _child(roots[EFFECTS], "calculate_national_identity_progress")
    line = _find_shape(
        national,
        "every_scope_war",
        (
            (
                "limit",
                "=",
                (("has_war_support", "=", (("target", "=", "root"), ("value", ">", "80"))),),
            ),
            (
                "ROOT",
                "=",
                (
                    (
                        "change_variable",
                        "=",
                        (
                            ("name", "=", "national_identity_progress_from_wars"),
                            ("add", "=", "0.50"),
                        ),
                    ),
                ),
            ),
        ),
    )
    references.append(f"{EFFECTS}:{line}")
    complete = _child(_child(roots[REGIONS], "ai_regional_objective_acquire_states"), "complete")
    expected_count = (
        ("owner", "=", "root"),
        ("count", ">", "root.variable_map(aro_acquire_states_map|scope:target_region)"),
    )
    line = _find_shape(complete, "any_scope_state", expected_count)
    references.append(f"{REGIONS}:{line}")
    doc = inputs[TRIGGER_DOC].splitlines()
    statement = "# any_child = { count >= 5\t<triggers> }"
    lines = [index for index, value in enumerate(doc, 1) if value.strip() == statement]
    if len(lines) != 1 or '# Special "Any" Trigger: With "count" or "percent"' not in doc:
        raise ValueError("本国战争过滤后count比较文档漂移")
    references.append(f"{TRIGGER_DOC}:{lines[0]}")
    comments = (
        "# How much should the AI value a wargoal against another country/state",
        "# Using this value in other strategies will function additively",
        "# scope:target_country = wargoal target country",
        "# scope:target_state = wargoal target state (if any)",
    )
    source_lines = [line.strip() for line in inputs[SOURCE].splitlines()]
    if (
        sum(
            tuple(source_lines[index : index + 4]) == comments for index in range(len(source_lines))
        )
        != 1
    ):
        raise ValueError("征服目标精确候选作用域/加分合同漂移")
    goals = _child(_child(roots[SOURCE], "ai_strategy_default"), "wargoal_scores")
    conquest = _child(goals, "conquer_state")
    # Complete ordered native subtree includes original min/max, regional
    # ambition, and the final special-country terminal zero. Repinning a source
    # hash alone must not authorize changed eligibility or scoring semantics.
    digest = hashlib.sha256(json.dumps(_shape(conquest), ensure_ascii=False).encode()).hexdigest()
    if digest != CONQUEST_AST_SHA256:
        raise ValueError("征服目标完整原版AST漂移")
    references.append(f"{SOURCE}:{goals.all('conquer_state')[0].line}")
    return tuple(references)


CONQUEST_AST_SHA256 = "04162e5940bad62506685fc8665e4ccca66969cf15555b8d22e9c3f90d55eb57"


@dataclass(frozen=True, slots=True)
class OwnMultiwarLowSupportQuery:
    """At least two own wars each have own war support strictly below 50."""


@dataclass(frozen=True, slots=True)
class CompiledOwnMultiwarLowSupportQuery:
    expression: str
    references: tuple[str, ...]
    source_hashes: tuple[tuple[str, str], ...]
    local_collections: tuple[str, ...] = ("own_wars",)
    actor: str = "country"
    kind: str = "boolean"
    unknown_policy: str = "missing_own_collection=unknown; complete_empty=false; known_low>=2=true; possible_low<2=false; otherwise=unknown; malformed=error"
    world_scans: int = 0
    runtime_cost: str = "one own-war traversal with explicit ROOT-target support comparison; no persistent state or world scan"


def query_from_reader(engine: str, parameters: Mapping[str, str]) -> OwnMultiwarLowSupportQuery:
    if engine != "any_scope_war" or parameters != {QUERY_PARAMETER: "two_own_wars_below_50"}:
        raise ValueError("本国战争压力只接受精确own-list/count/ROOT支持度查询")
    return OwnMultiwarLowSupportQuery()


def render_query(query: OwnMultiwarLowSupportQuery) -> str:
    if type(query) is not OwnMultiwarLowSupportQuery:
        raise ValueError("本国战争压力只接受精确查询类型")
    return "any_scope_war = { count >= 2 has_war_support = { target = root value < 50 } }"


def required_query_sources(query: OwnMultiwarLowSupportQuery) -> tuple[str, ...]:
    render_query(query)
    return tuple(sorted(SOURCES))


def compile_query(
    query: OwnMultiwarLowSupportQuery, inputs: Mapping[str, str]
) -> CompiledOwnMultiwarLowSupportQuery:
    return CompiledOwnMultiwarLowSupportQuery(
        render_query(query), verify_inputs(inputs), tuple(sorted(load()["sources"].items()))
    )


def derive(adapters: Mapping[str, Any]) -> dict[str, Any]:
    data = load()
    verify_inputs(frozen_inputs())
    return {
        "sources": dict(data["sources"]),
        "readers": {
            "prospective_subject_population": adapters["readers"]["prospective_subject_population"],
            READER: {
                "engine": "any_scope_war",
                "scope": "root",
                "kind": "boolean",
                "unit": "boolean",
                "parameters": {QUERY_PARAMETER: "two_own_wars_below_50"},
            },
        },
        "rules": [
            {
                "id": RULE,
                "source": SOURCE,
                "field": FIELD,
                "domain": "diplomacy",
                "priority": 82000,
                "operation": "add",
                "value": data["tuning"]["conquest_opportunity_cost"],
                "semantic_role": "cost",
                "contribution_group": GROUP,
                "conditions": [
                    {"fact": "prospective_subject_population", "op": ">", "value": 0},
                    {"fact": READER, "op": "=", "value": True},
                ],
                "why": "本国至少两场现行战争各自对本国支持度低于50，对同一已知conquer_state新增领土敌对承诺形成有限机会成本；与近期败战恢复同组取强，不把当前战争和战败记忆重复扣分，融资按独立事实联合",
                "counterexample": "仅本国own-war列表且逐战争target=root，至少两场低支持而非两场战争中一场低支持；不借敌国支持、不预测败战、劳工或和平接受，不赋予全局禁止开战/防御门。未知集合或支持按三值计数，仅已知满足时扣本项；候选身份未知、玩家和关闭回原版，零/原版限幅/特殊主体终结零/资格和执行完整保留。正常低债借款不新增罚款，不推断集团固定军事义务。",
            }
        ],
        "covered": [
            {"id": "conquer_state_own_multiwar_pressure", "source": SOURCE, "field": FIELD}
        ],
    }
