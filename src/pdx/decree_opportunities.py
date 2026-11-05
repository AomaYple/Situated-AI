"""One state-root emergency-relief need, using the shared scalar rule algebra.

The native zero is an initial value, not a terminal rejection. The new component
is a gross disaster need of 40 with two embedded conservative cost allowances of
10 each: explicit non-default and nonnegative authority release those allowances.
Neither observation predicts money, rank-scaled authority cost or affordability.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tomllib
from typing import TYPE_CHECKING, Any

from . import config
from .model import Assignment, Block, Scalar
from .parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .situated.decision_ir import EvaluationContext

PARAMETERS = config.REPO / "mod/decisions/decree_opportunities.toml"
FROZEN = config.REPO / "research/vanilla-ai/1.14.5/decree-opportunities.json"
SOURCE = "common/decrees/00_decree.txt"
FINANCE = "events/brazil/amazonas.txt"
AUTHORITY = "common/tutorial_lessons/00_tutorial_lessons_promote_ig.txt"
SOURCES = frozenset({SOURCE, FINANCE, AUTHORITY})
DEFINITION = "decree_emergency_relief"
FIELD = f"{DEFINITION}.ai_weight"
DEVASTATION = "decree_relief_devastation"
DEFAULT = "decree_relief_owner_default"
CAPACITY = "decree_relief_owner_authority"
RULES = (
    "decree_relief_actual_disaster_need",
    "decree_relief_financing_cost_release",
    "decree_relief_authority_cost_release",
)


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
        raise ValueError("紧急救济schema或完整原版来源无效")
    tuning = data["tuning"]
    if (
        set(tuning) != {"disaster_residual", "financing_release", "authority_release"}
        or any(
            type(v) not in {int, float} or not math.isfinite(v) or v <= 0 for v in tuning.values()
        )
        or sum(tuning.values()) > 40
    ):
        raise ValueError("紧急救济需要及成本解除必须为正且总计不超过40")
    return data


def _block(parent: Block, key: str) -> Block:
    rows = parent.all(key)
    if len(rows) != 1 or rows[0].op not in {"=", "?="} or not isinstance(rows[0].value, Block):
        raise ValueError(f"紧急救济原版唯一块漂移：{key}")
    return rows[0].value


def _shape(block: Block) -> tuple:
    result: list[object] = []
    for row in block.items:
        if (
            isinstance(row, Assignment)
            and row.prefix is None
            and isinstance(row.value, (Block, Scalar))
        ):
            result.append(
                (
                    row.key,
                    row.op,
                    _shape(row.value) if isinstance(row.value, Block) else row.value.unquoted,
                )
            )
        elif isinstance(row, Scalar):
            result.append(row.unquoted)
        else:
            raise ValueError("紧急救济原版AST含未登记项")
    return tuple(result)


def verify_inputs(inputs: Mapping[str, str]) -> tuple[str, ...]:
    roots = {}
    for source, digest in load()["sources"].items():
        text = inputs.get(source)
        if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != digest:
            raise ValueError(f"紧急救济完整原版来源漂移：{source}")
        parsed = parse_text(text)
        if parsed.errors:
            raise ValueError(f"紧急救济完整原版解析失败：{source}")
        roots[source] = parsed.root
    decree = _block(roots[SOURCE], DEFINITION)
    expected = {
        "unlocking_technologies": ("centralization",),
        "modifier": (
            ("state_tax_collection_mult", "=", "-0.5"),
            ("state_infrastructure_mult", "=", "0.1"),
            ("state_market_access_price_impact", "=", "0.05"),
            ("state_food_security_add", "=", "0.05"),
        ),
        "state_trigger": (
            (
                "OR",
                "=",
                (
                    ("has_famine", "=", "yes"),
                    ("devastation", ">", "0.2"),
                    (
                        "ROOT.state_region",
                        "=",
                        (
                            (
                                "OR",
                                "=",
                                tuple(
                                    ("has_harvest_condition", "=", name)
                                    for name in (
                                        "flood",
                                        "wildfire",
                                        "drought",
                                        "disease_outbreak",
                                        "extreme_winds",
                                        "tsunami",
                                    )
                                ),
                            ),
                        ),
                    ),
                    (
                        "any_scope_pop",
                        "=",
                        (("percent", ">=", "0.2"), ("is_in_starvation", "=", "yes")),
                    ),
                ),
            ),
        ),
        "ai_weight": (
            ("value", "=", "0"),
            (
                "if",
                "=",
                (
                    ("limit", "=", (("average_sol", "<", "average_expected_sol"),)),
                    ("add", "=", "100"),
                ),
            ),
            (
                "if",
                "=",
                (
                    (
                        "limit",
                        "=",
                        (
                            (
                                "scope:country",
                                "=",
                                (
                                    (
                                        "OR",
                                        "=",
                                        (
                                            ("has_strategy", "=", "ai_strategy_nationalist_agenda"),
                                            ("has_strategy", "=", "ai_strategy_reactionary_agenda"),
                                        ),
                                    ),
                                ),
                            ),
                        ),
                    ),
                    ("multiply", "=", "0.5"),
                ),
            ),
        ),
    }
    for key, shape in expected.items():
        if _shape(_block(decree, key)) != shape:
            raise ValueError(f"紧急救济原版资格/效果/初始零/政治尾乘AST漂移：{key}")
    cost = decree.all("cost")
    if (
        len(cost) != 1
        or cost[0].op != "="
        or not isinstance(cost[0].value, Scalar)
        or cost[0].value.unquoted != "50"
    ):
        raise ValueError("紧急救济原版rank缩放成本参数漂移")
    lines = inputs[SOURCE].splitlines()
    for line, evidence in ((3, "scales with Power Rank"), (7, "state_trigger"), (8, "ai_weight")):
        if evidence not in lines[line - 1]:
            raise ValueError("紧急救济政令原版作用域/成本注释漂移")
    event = _block(roots[FINANCE], "amazonas.1")
    if ("type", "=", "country_event") not in _shape(event) or (
        "in_default",
        "=",
        "no",
    ) not in _shape(_block(event, "trigger")):
        raise ValueError("紧急救济财政读取country上下文漂移")
    lesson = _block(
        _block(roots[AUTHORITY], "lesson_promote_movement_how"), "lesson_promote_movement_how_4"
    )
    authority = _block(_block(_block(lesson, "trigger_transition"), "trigger"), "custom_tooltip")
    if ("authority", ">=", "define:NPolitics|IG_BOLSTER_COST") not in _shape(authority):
        raise ValueError("紧急救济authority容量余额读取漂移")
    return (
        f"{SOURCE}:3",
        f"{SOURCE}:7",
        f"{SOURCE}:8",
        f"{SOURCE}:144",
        f"{SOURCE}:179",
        f"{FINANCE}:24",
        f"{AUTHORITY}:131",
    )


def frozen_inputs() -> dict[str, str]:
    data = json.loads(FROZEN.read_text(encoding="utf-8"))
    if (
        set(data)
        != {"schema", "evidence", "normalization", "source_hashes", "raw_source_hashes", "inputs"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or data["evidence"] != "static_complete_native_sources_not_engine_execution"
        or data["normalization"] != "utf8_without_bom_lf_preserve_whitespace"
        or data["source_hashes"] != load()["sources"]
        or set(data["raw_source_hashes"]) != SOURCES
        or not isinstance(data["inputs"], dict)
        or set(data["inputs"]) != SOURCES
    ):
        raise ValueError("紧急救济冻结完整原版合同无效")
    verify_inputs(data["inputs"])
    return data["inputs"]


def consumer_catalog() -> dict[str, dict[str, Any]]:
    verify_inputs(frozen_inputs())
    return {
        DEFINITION: {
            "source": SOURCE,
            "field": FIELD,
            "native_root": "state",
            "actor": "owner",
            "actor_path": ["owner"],
            "native_unit": "weight",
            "operation": "add",
            "source_sha256": load()["sources"][SOURCE],
            "scope_evidence": SOURCE,
            "scope_evidence_line": 7,
            "score_evidence_line": 179,
            "target_binding": "candidate_state_is_root_not_foreign_target",
            "insertion": "before_native_political_multiply_tail",
        }
    }


def evaluation_context() -> EvaluationContext:
    from .situated.decision_ir import ContextBinding, EvaluationContext  # noqa: PLC0415

    verify_inputs(frozen_inputs())
    return EvaluationContext(
        actor_scope=ContextBinding("owner", "country", "actor", SOURCE, 179),
        auxiliary_scopes=(ContextBinding("root", "state", "auxiliary", SOURCE, 7),),
        evidence=(
            f"{SOURCE}:179",
            f"{SOURCE}:7",
            f"{SOURCE}:8",
            f"{SOURCE}:sha256={load()['sources'][SOURCE]}",
        ),
    )


def derive(adapters: Mapping[str, Any]) -> dict[str, Any]:
    """Feed one existing decree consumer into the common rule/program compiler."""
    del adapters
    data = load()
    verify_inputs(frozen_inputs())
    readers = {
        DEVASTATION: {
            "engine": "devastation",
            "scope": "root",
            "kind": "number",
            "unit": "ratio",
            "minimum": 0,
            "maximum": 1,
        },
        DEFAULT: {
            "engine": "in_default",
            "scope": "root",
            "path": ["owner"],
            "kind": "boolean",
            "unit": "boolean",
        },
        CAPACITY: {
            "engine": "authority",
            "scope": "root",
            "path": ["owner"],
            "kind": "number",
            "unit": "capacity_balance",
        },
    }
    conditions = [{"fact": DEVASTATION, "op": ">", "value": 0.2}]
    rules = []
    for index, (key, extra, group) in enumerate(
        (
            ("disaster_residual", [], "decree_relief_disaster"),
            (
                "financing_release",
                [{"fact": DEFAULT, "op": "=", "value": False}],
                "decree_relief_financing",
            ),
            (
                "authority_release",
                [{"fact": CAPACITY, "op": ">=", "value": 0}],
                "decree_relief_authority",
            ),
        )
    ):
        rules.append(
            {
                "id": RULES[index],
                "source": SOURCE,
                "field": FIELD,
                "domain": "political",
                "priority": 83000 + index,
                "operation": "add",
                "value": data["tuning"][key],
                "semantic_role": "benefit",
                "contribution_group": group,
                "conditions": [*conditions, *extra],
                "why": "同一实际受创州的有限救济需要40，内含融资与authority压力各10的保守留存；明确非default或非负authority仅解除对应留存",
                "counterexample": "只读候选州ROOT的devastation>0.2与真实owner；未知需要不写，未知压力不解除成本。authority>=0不是足够支付按rank缩放cost50。正常借款不等于default。新增分量0..40且受创州20..40，不扣减原SOL100；保留科技、完整state_trigger、效果、cost与政治0.5尾乘，玩家/关闭贡献0。",
            }
        )
    return {
        "sources": dict(data["sources"]),
        "actors": {SOURCE: ["owner"]},
        "readers": readers,
        "rules": rules,
        "covered": [
            {"id": "decree_emergency_relief_disaster_need", "source": SOURCE, "field": FIELD}
        ],
    }
