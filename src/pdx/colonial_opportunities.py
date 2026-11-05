"""Actual owned colonial projects and bounded investment-priority withdrawal.

Colonial growth capacity does not establish activity. Native institutional
effects remain linear; withdrawal tiers express finite preference saturation,
never an inferred current maximum or diminishing native growth multiplier.
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

PARAMETERS = config.REPO / "mod/decisions/colonial_opportunities.toml"
FROZEN = config.REPO / "research/vanilla-ai/1.14.5/colonial-opportunities.json"
QUERY_SOURCE = "common/power_bloc_principles/00_power_bloc_principles.txt"
INSTITUTION_SOURCE = "common/institutions/00_institutions.txt"
SOURCE = "common/ai_strategies/00_default_strategy.txt"
FIELD = "ai_strategy_default.institution_scores.institution_colonial_affairs"
_TUNING = frozenset(
    {
        "active_need",
        "invested_withdrawal",
        "deeply_invested_withdrawal",
        "inactive_withdrawal",
        "inactive_invested_withdrawal",
    }
)
UNKNOWN_POLICY = (
    "missing_collection=unknown; complete_empty_collection=false; any_true=true; "
    "no_true_with_missing_member_observation=unknown; malformed_input=error"
)


def load() -> dict[str, Any]:
    data = tomllib.loads(PARAMETERS.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "sources", "tuning"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
    ):
        raise ValueError("殖民机会schema无效")
    if set(data["sources"]) != {QUERY_SOURCE, INSTITUTION_SOURCE} or any(
        not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value)
        for value in data["sources"].values()
    ):
        raise ValueError("殖民机会必须锁定完整活动消费者和制度源")
    tuning = data["tuning"]
    if set(tuning) != _TUNING or any(
        type(value) not in {int, float} or not math.isfinite(value) for value in tuning.values()
    ):
        raise ValueError("殖民机会参数须为有限数值")
    if not (
        1 < tuning["active_need"] <= 1.25
        and 0.75 <= tuning["deeply_invested_withdrawal"] <= tuning["invested_withdrawal"] < 1
        and 0.75 <= tuning["inactive_invested_withdrawal"] <= tuning["inactive_withdrawal"] < 1
        and (tuning["active_need"] - 1) > (1 - tuning["deeply_invested_withdrawal"])
    ):
        raise ValueError("殖民需求与优先级退出档越界")
    return data


def _child(block: Block, key: str) -> Block:
    rows = block.all(key)
    if len(rows) != 1 or rows[0].op != "=" or not isinstance(rows[0].value, Block):
        raise ValueError(f"殖民原版缺少唯一完整块：{key}")
    return rows[0].value


def _shape(block: Block) -> tuple:
    rows = []
    for row in block.assignments():
        value: tuple | str
        if isinstance(row.value, Block):
            value = _shape(row.value)
        elif isinstance(row.value, Scalar):
            value = row.value.unquoted
        else:
            raise ValueError("殖民原版AST不能包含空值")
        rows.append((row.key, row.op, value))
    return tuple(rows)


def _roots(inputs: Mapping[str, str]) -> dict[str, Block]:
    result = {}
    for source, digest in load()["sources"].items():
        text = inputs.get(source)
        if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != digest:
            raise ValueError(f"殖民完整原版来源漂移：{source}")
        parsed = parse_text(text)
        if parsed.errors:
            raise ValueError(f"殖民完整原版解析失败：{source}")
        result[source] = parsed.root
    return result


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
        or set(data["inputs"]) != set(load()["sources"])
    ):
        raise ValueError("殖民冻结底本合同无效")
    _roots(data["inputs"])
    return data["inputs"]


@dataclass(frozen=True, slots=True)
class ColonialQuery:
    """Existence of an actual ongoing project in the country's owned states."""


@dataclass(frozen=True, slots=True)
class CompiledColonialQuery:
    expression: str
    references: tuple[str, ...]
    source_hashes: tuple[tuple[str, str], ...]
    local_collections: tuple[str, ...] = ("owned_states",)
    actor: str = "country"
    kind: str = "boolean"
    unknown_policy: str = UNKNOWN_POLICY
    world_scans: int = 0
    runtime_cost: str = "existential traversal of owned states"


def query_from_reader(engine: str, parameters: Mapping[str, str]) -> ColonialQuery:
    if engine != "any_scope_state" or parameters != {"colonial_query": "active_projects"}:
        raise ValueError("殖民活动查询必须保持精确本国州集合和活动getter")
    return ColonialQuery()


def render_query(query: ColonialQuery) -> str:
    if type(query) is not ColonialQuery:
        raise ValueError("殖民活动查询类型无效")
    return "any_scope_state = { is_under_colonization = yes }"


def required_query_sources(query: ColonialQuery) -> tuple[str, ...]:
    render_query(query)
    return (QUERY_SOURCE,)


def compile_query(query: ColonialQuery, inputs: Mapping[str, str]) -> CompiledColonialQuery:
    expression = render_query(query)
    text = inputs.get(QUERY_SOURCE)
    digest = load()["sources"][QUERY_SOURCE]
    if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != digest:
        raise ValueError("殖民活动查询原版来源漂移")
    parsed = parse_text(text)
    if parsed.errors:
        raise ValueError("殖民活动查询原版解析失败")
    principle = _child(parsed.root, "principle_colonial_offices_1")
    ai_weight = _child(principle, "ai_weight")
    expected = (
        (
            "limit",
            "=",
            (("NOT", "=", (("any_scope_state", "=", (("is_under_colonization", "=", "yes"),)),)),),
        ),
        ("multiply", "=", "0.0"),
    )
    matches = [
        row
        for row in ai_weight.all("if")
        if isinstance(row.value, Block) and _shape(row.value) == expected
    ]
    if len(matches) != 1:
        raise ValueError("殖民国家活动消费者完整AST证据漂移")
    return CompiledColonialQuery(
        expression, (f"{QUERY_SOURCE}:{matches[0].line}",), ((QUERY_SOURCE, digest),)
    )


def verify_inputs(inputs: Mapping[str, str]) -> None:
    roots = _roots(inputs)
    compile_query(ColonialQuery(), inputs)
    institution = _child(roots[INSTITUTION_SOURCE], "institution_colonial_affairs")
    modifier = _child(institution, "modifier")
    if _shape(modifier) != (("state_colony_growth_creation_factor", "=", "0.1"),):
        raise ValueError("殖民制度实际效果AST漂移")


def derive(adapters: Mapping[str, Any]) -> dict[str, Any]:
    data = load()
    verify_inputs(frozen_inputs())
    tuning = data["tuning"]
    readers = {
        key: adapters["readers"][key]
        for key in ("has_colonial_affairs_institution", "colonial_affairs_investment")
    }
    readers["colonial_active_projects"] = {
        "engine": "any_scope_state",
        "scope": "root",
        "kind": "boolean",
        "unit": "boolean",
        "parameters": {"colonial_query": "active_projects"},
    }
    rules: list[dict[str, Any]] = []

    def add(
        suffix: str, group: str, value: float, conditions: list[dict[str, object]], why: str
    ) -> None:
        rules.append(
            {
                "id": f"colonial_activity_{suffix}",
                "source": SOURCE,
                "field": FIELD,
                "domain": "economy",
                "priority": 75000 + len(rules),
                "operation": "multiply",
                "value": value,
                "semantic_role": "benefit" if suffix == "need" else "unspecified",
                "contribution_group": group,
                "conditions": [
                    {"fact": "has_colonial_affairs_institution", "op": "=", "value": True},
                    *conditions,
                ],
                "why": why,
                "counterexample": "倍率和投入3/5为有界偏好设计，不是原版收益递减、当前最高等级或强制降级。真实活动不是殖民能力；不假定target_region。已知需求独立于财政成本，未知活动不当无活动，未知投入仅退出饱和档；玩家、关闭和缺资格保留原版。",
            }
        )

    def condition(fact: str, op: str, value: object) -> dict[str, object]:
        return {"fact": fact, "op": op, "value": value}

    add(
        "need",
        "colonial_actual_activity_need",
        tuning["active_need"],
        [condition("colonial_active_projects", "=", True)],
        "本国拥有正在殖民中的真实州，产生制度投资需求；殖民能力和空闲殖民法不构成活动，不要求财政健康才承认需求",
    )
    for suffix, level in (("invested", 3), ("deeply_invested", 5)):
        add(
            suffix,
            "colonial_invested_priority_withdrawal",
            tuning[f"{suffix}_withdrawal"],
            [
                condition("colonial_active_projects", "=", True),
                condition("colonial_affairs_investment", ">=", level),
            ],
            "已有较多实际投入时撤回部分新增优先级，保留独立真实活动需求；原版每等级效果未被更改，也不推断需求已满足",
        )
    for suffix, level in (("inactive", 1), ("inactive_invested", 3)):
        add(
            suffix,
            "colonial_inactive_priority_withdrawal",
            tuning[f"{suffix}_withdrawal"],
            [
                condition("colonial_active_projects", "=", False),
                condition("colonial_affairs_investment", ">=", level),
            ],
            "完整本国州集合证实没有实际殖民项目，已投入制度降低新增优先级；不是强制撤销制度，不把未知集合或能力值当无活动",
        )
    return {
        "sources": dict(data["sources"]),
        "readers": readers,
        "rules": rules,
        "covered": [{"id": "institution_colonial_affairs", "source": SOURCE, "field": FIELD}],
    }
