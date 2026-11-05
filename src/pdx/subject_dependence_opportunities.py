"""Actual subject -> current direct overlord economic relationship benefit.

The native dependence index is 0..5, not a GDP share, transfer or forecast.
Only the existing compliance strategy receives a bounded continuity benefit;
liberty desire, financing, security and the native strategy qualifications stay
independent. No prospective-country binding or persistent state is introduced.
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

PARAMETERS = config.REPO / "mod/decisions/subject_dependence_opportunities.toml"
FROZEN = config.REPO / "research/vanilla-ai/1.14.5/subject-dependence-opportunities.json"
SOURCE = "common/ai_strategies/02_subject_diplomatic_strategies.txt"
FIELD = "ai_strategy_subject_overlord_compliance.weight"
GRANT = "common/diplomatic_actions/36_subjects_grant_own_market.txt"
DEFINES = "common/defines/00_defines.txt"
INDIA = "common/journal_entries/04_india_non_cooperation.txt"
SOURCES = frozenset({SOURCE, GRANT, DEFINES, INDIA})
READER = "subject_actual_overlord_dependence"
RULE = "subject_actual_economic_relationship_continuity"
QUERY_PARAMETER = "subject_dependence_query"


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
        raise ValueError("实际宗主依赖schema或完整原版来源无效")
    tuning = data["tuning"]
    if (
        set(tuning) != {"economic_relationship_continuity"}
        or type(tuning["economic_relationship_continuity"]) not in {int, float}
        or not math.isfinite(tuning["economic_relationship_continuity"])
        or not 1 < tuning["economic_relationship_continuity"] <= 1.10
    ):
        raise ValueError("实际宗主经济连续性收益必须在1到1.10之间")
    return data


def _child(block: Block, key: str) -> Block:
    rows = block.all(key)
    if len(rows) != 1 or rows[0].op not in {"=", "?="} or not isinstance(rows[0].value, Block):
        raise ValueError(f"实际宗主依赖原版唯一块漂移：{key}")
    return rows[0].value


def _scalar(block: Block, key: str, op: str, value: str) -> int:
    rows = block.all(key)
    if (
        len(rows) != 1
        or rows[0].op != op
        or not isinstance(rows[0].value, Scalar)
        or rows[0].value.unquoted != value
    ):
        raise ValueError(f"实际宗主依赖原版标量漂移：{key}")
    return rows[0].line


def _shape(block: Block) -> tuple:
    rows = []
    for row in block.assignments():
        if isinstance(row.value, Block):
            value: str | tuple = _shape(row.value)
        elif isinstance(row.value, Scalar):
            value = row.value.unquoted
        else:
            raise ValueError("实际宗主依赖原版AST无值")
        rows.append((row.key, row.op, value))
    if len(rows) != len(block.items):
        raise ValueError("实际宗主依赖证据含非赋值项")
    return tuple(rows)


def _roots(inputs: Mapping[str, str]) -> dict[str, Block]:
    roots = {}
    for source, digest in load()["sources"].items():
        text = inputs.get(source)
        if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != digest:
            raise ValueError(f"实际宗主依赖完整原版来源漂移：{source}")
        parsed = parse_text(text)
        if parsed.errors:
            raise ValueError(f"实际宗主依赖完整原版解析失败：{source}")
        roots[source] = parsed.root
    return roots


def frozen_inputs() -> dict[str, str]:
    data = json.loads(FROZEN.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "evidence", "normalization", "source_hashes", "inputs"}
        or data["schema"] != 1
        or type(data["schema"]) is not int
        or data["evidence"] != "static_complete_native_sources_not_engine_execution"
        or data["normalization"] != "utf8_without_bom_lf_preserve_whitespace"
        or data["source_hashes"] != load()["sources"]
        or not isinstance(data["inputs"], dict)
        or set(data["inputs"]) != SOURCES
    ):
        raise ValueError("实际宗主依赖冻结完整原版合同无效")
    _roots(data["inputs"])
    return data["inputs"]


def verify_inputs(inputs: Mapping[str, str]) -> tuple[str, ...]:
    roots = _roots(inputs)
    refs = []
    diplomacy = _child(roots[DEFINES], "NDiplomacy")
    for key, value in (("ECONOMIC_DEPENDENCE_MIN", "0"), ("ECONOMIC_DEPENDENCE_MAX", "5")):
        refs.append(f"{DEFINES}:{_scalar(diplomacy, key, '=', value)}")
    grant = _child(roots[GRANT], "grant_own_market")
    direct = _child(_child(_child(grant, "possible"), "OR"), "scope:target_country")
    refs.append(f"{GRANT}:{_scalar(direct, 'is_direct_subject_of', '=', 'root')}")
    effects = _child(grant, "accept_effect")
    for branch, comparison in (("if", ">"), ("else_if", "<")):
        limit = _child(_child(effects, branch), "limit")
        refs.append(
            f"{GRANT}:{_scalar(limit, 'scope:target_country.economic_dependence(root)', comparison, '1')}"
        )
        _scalar(_child(limit, "scope:target_country"), "is_subject_of", "=", "root")
    strategy = _child(roots[SOURCE], "ai_strategy_subject_overlord_compliance")
    possible = _child(strategy, "possible")
    if _shape(possible) != (
        ("is_subject", "=", "yes"),
        ("liberty_desire", "<=", "50"),
        ("NOT", "=", (("is_diplomatic_play_enemy_of", "=", "overlord"),)),
    ):
        raise ValueError("宗属合作原版实际宗主/自由愿望/非敌人资格AST漂移")
    refs.append(f"{SOURCE}:{possible.all('is_subject')[0].line}")
    weight = _child(strategy, "weight")
    if _shape(weight) != (
        ("value", "=", "50"),
        ("subtract", "=", "liberty_desire"),
        ("multiply", "=", "2"),
        ("if", "=", (("limit", "=", (("is_princely_state", "=", "yes"),)), ("add", "=", "10"))),
    ):
        raise ValueError("宗属合作原版完整weight AST漂移")
    # A real country trigger proves the quoted ROOT getter and guarded dynamic
    # country-scope argument. Direct overlord is separately proved above; it is
    # deliberately not top_overlord and never the prospective scope:overlord.
    india = _child(_child(roots[INDIA], "je_india_non_cooperation_movement"), "possible")
    _scalar(india, "is_subject", "=", "yes")
    _scalar(_child(india, "hidden_trigger"), "exists", "=", "top_overlord")
    refs.append(f"{INDIA}:{_scalar(india, 'ROOT.economic_dependence(top_overlord)', '>', '2.5')}")
    return tuple(refs)


@dataclass(frozen=True, slots=True)
class ActualOverlordDependenceQuery:
    """Root's dependence on its current direct overlord, strictly above 1."""


@dataclass(frozen=True, slots=True)
class CompiledActualOverlordDependenceQuery:
    expression: str
    references: tuple[str, ...]
    source_hashes: tuple[tuple[str, str], ...]
    local_collections: tuple[str, ...] = ()
    actor: str = "country"
    kind: str = "boolean"
    unknown_policy: str = "not_subject_or_absent_overlord=false; unknown_identity_or_dependence=unknown; malformed=error"
    world_scans: int = 0
    runtime_cost: str = "one actual direct-overlord lookup and one 0..5 dependence getter; no collection traversal or persistent state"


def query_from_reader(engine: str, parameters: Mapping[str, str]) -> ActualOverlordDependenceQuery:
    if engine != "AND" or parameters != {QUERY_PARAMETER: "actual_overlord_above_neutral"}:
        raise ValueError("宗主依赖只接受精确实际本国宗主AND查询")
    return ActualOverlordDependenceQuery()


def render_query(query: ActualOverlordDependenceQuery) -> str:
    if type(query) is not ActualOverlordDependenceQuery:
        raise ValueError("宗主依赖只接受精确实际宗主类型")
    return 'AND = { is_subject = yes exists = overlord "ROOT.economic_dependence(overlord)" > 1 }'


def required_query_sources(query: ActualOverlordDependenceQuery) -> tuple[str, ...]:
    render_query(query)
    return tuple(sorted(SOURCES))


def compile_query(
    query: ActualOverlordDependenceQuery, inputs: Mapping[str, str]
) -> CompiledActualOverlordDependenceQuery:
    return CompiledActualOverlordDependenceQuery(
        render_query(query), verify_inputs(inputs), tuple(sorted(load()["sources"].items()))
    )


def derive(adapters: Mapping[str, Any]) -> dict[str, Any]:
    data = load()
    verify_inputs(frozen_inputs())
    return {
        "sources": dict(data["sources"]),
        "readers": {
            "actor_is_subject": adapters["readers"]["actor_is_subject"],
            READER: {
                "engine": "AND",
                "scope": "root",
                "kind": "boolean",
                "unit": "boolean",
                "parameters": {QUERY_PARAMETER: "actual_overlord_above_neutral"},
            },
        },
        "rules": [
            {
                "id": RULE,
                "source": SOURCE,
                "field": FIELD,
                "domain": "subjects",
                "priority": 81000,
                "operation": "multiply",
                "value": data["tuning"]["economic_relationship_continuity"],
                "semantic_role": "benefit",
                "contribution_group": "subject_economic_relationship_continuity",
                "conditions": [
                    {"fact": "actor_is_subject", "op": "=", "value": True},
                    {"fact": READER, "op": "=", "value": True},
                ],
                "auxiliary_facts": [READER],
                "why": "本国实际属国对当前直接宗主的经济依赖指数高于1，当前经济联系形成有限合作连续性收益；与自由愿望/关系需要独立联合，不把依赖一概判坏",
                "counterexample": "0..5是无量纲经济依赖指数，不是GDP份额、转移收入或未来利润。仅绑定本国实际直接宗主，不借候选scope:overlord、外国/顶层宗主或反向依赖；不保证共同市场，不创造援助或永久忠诚。低/中性依赖、非属国、缺宗主和未知只退出本分量，不抹已有自由需要或成本。正常低债融资不变；保留原版possible自由愿望<=50/非宗主敌人、完整weight、玩家/关闭与执行。",
            }
        ],
        "covered": [{"id": "subject_actual_overlord_compliance", "source": SOURCE, "field": FIELD}],
    }
