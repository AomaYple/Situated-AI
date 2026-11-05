"""Recovery and marginal commitment tradeoffs for exact diplomatic goals."""

from __future__ import annotations

import hashlib
import math
import tomllib
from typing import TYPE_CHECKING, Any

from . import config
from .model import Block, Scalar
from .parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Mapping

PARAMETERS = config.REPO / "mod/decisions/cooperation_opportunities.toml"
SOURCE = "common/ai_strategies/00_default_strategy.txt"
FIELDS = {
    name: f"ai_strategy_default.secret_goal_scores.{name}.score"
    for name in ("reconcile", "protect")
}
TUNING = {
    "reconcile_default",
    "reconcile_liquidity",
    "reconcile_recovery",
    "protect_default",
    "protect_liquidity",
    "protect_influence",
    "protect_recovery",
}


def load() -> dict[str, Any]:
    data = tomllib.loads(PARAMETERS.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "sources", "tuning"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or set(data["sources"]) != {SOURCE}
        or set(data["tuning"]) != TUNING
    ):
        raise ValueError("外交合作机会 schema 或候选分母无效")
    for key, value in data["tuning"].items():
        if type(value) not in {int, float} or not math.isfinite(value):
            raise ValueError("外交合作评分须有限")
        if not (0 < value <= 10 if key.startswith("reconcile_") else -10 <= value < 0):
            raise ValueError("外交缓和收益与新增承诺成本方向或边界无效")
    return data


def _block(parent: Block, key: str) -> Block:
    rows = parent.all(key)
    if len(rows) != 1 or not isinstance(rows[0].value, Block):
        raise ValueError(f"外交合作原版结构不唯一：{key}")
    return rows[0].value


def verify_inputs(inputs: Mapping[str, str]) -> None:
    data = load()
    text = inputs.get(SOURCE)
    if (
        not isinstance(text, str)
        or hashlib.sha256(text.encode()).hexdigest() != data["sources"][SOURCE]
    ):
        raise ValueError("外交合作原版来源漂移")
    parsed = parse_text(text)
    if parsed.errors:
        raise ValueError("外交合作原版解析失败")
    goals = _block(_block(parsed.root, "ai_strategy_default"), "secret_goal_scores")
    for name, base in (("reconcile", "100"), ("protect", "200")):
        goal = _block(goals, name)
        _block(goal, "trigger")
        score = _block(goal, "score")
        values = score.all("value")
        if (
            len(values) != 1
            or not isinstance(values[0].value, Scalar)
            or values[0].value.unquoted != base
        ):
            raise ValueError("外交合作原版基础评分漂移")


def derive(adapters: Mapping[str, Any]) -> dict[str, Any]:
    data = load()

    def c(fact: str, op: str, value: object) -> dict[str, object]:
        return {"fact": fact, "op": op, "value": value}

    financing = {
        "default": [c("default", "=", True)],
        "liquidity": [
            c("loans", "=", True),
            c("debt_ratio", ">=", 0.4),
            c("bankruptcy_horizon", "<", 26),
        ],
    }
    candidates = (
        ("reconcile", "default", "financing", financing["default"]),
        ("reconcile", "liquidity", "financing", financing["liquidity"]),
        ("reconcile", "recovery", "recovery", [c("war_defeat", "=", True)]),
        ("protect", "default", "financing", financing["default"]),
        ("protect", "liquidity", "financing", financing["liquidity"]),
        ("protect", "influence", "influence", [c("influence", "<", 0)]),
        ("protect", "recovery", "recovery", [c("war_defeat", "=", True)]),
    )
    rules = []
    for index, (name, reason, cause, conditions) in enumerate(candidates):
        rules.append(
            {
                "id": f"cooperation_{name}_{reason}",
                "source": SOURCE,
                "field": FIELDS[name],
                "domain": "diplomacy",
                "priority": 78000 + index,
                "operation": "add",
                "value": data["tuning"][f"{name}_{reason}"],
                "semantic_role": "benefit" if name == "reconcile" else "cost",
                "contribution_group": f"cooperation_{cause}",
                "conditions": [c("prospective_subject_population", ">", 0), *conditions],
                "why": (
                    "当前融资或原版限时败战状态提高缓和关系的相对价值，不重复原版关系、意识形态、集团及游说评分"
                    if name == "reconcile"
                    else "当前融资、影响力或败战恢复分别提高新增保护承诺的机会成本，不假称已参战或预知对手"
                ),
                "counterexample": "只改精确候选score；外层trigger、原版资格、成本、特殊历史和尾部保留。正常低债借款不罚，恢复后撤回，未知只撤相关项；目标身份未知不调整。相同融资原因取强，独立恢复/影响力联合；不是强制结盟、和平或承诺执行。",
            }
        )
    used = {c["fact"] for rule in rules for c in rule["conditions"]}
    readers = {key: adapters["readers"][key] for key in sorted(used - {"influence"})}
    readers["influence"] = {
        "engine": "influence",
        "scope": "root",
        "kind": "number",
        "unit": "capacity_balance",
    }
    return {
        "sources": dict(data["sources"]),
        "readers": readers,
        "rules": rules,
    }
