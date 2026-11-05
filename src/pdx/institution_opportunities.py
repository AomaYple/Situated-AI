"""Bounded withdrawal of investment priority under observed specific needs.

These tiers are preference design, not a claim that native institution effects
stop increasing, that demand is satisfied, or that level five is attainable.
"""

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

PARAMETERS = config.REPO / "mod/decisions/institution_opportunities.toml"
SOURCE = "common/ai_strategies/00_default_strategy.txt"
INSTITUTION_SOURCE = "common/institutions/00_institutions.txt"
EDUCATION_SOURCE = "common/laws/01_education_system.txt"
HEALTH_SOURCE = "common/laws/01_health_system.txt"
INSTITUTIONS = (
    "social_security",
    "workplace_safety",
    "schools",
    "police",
    "health_system",
    "home_affairs",
)


def load() -> dict[str, Any]:
    data = tomllib.loads(PARAMETERS.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "sources", "tuning"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or set(data["sources"]) != {INSTITUTION_SOURCE, EDUCATION_SOURCE, HEALTH_SOURCE}
        or set(data["tuning"])
        != {f"{name}_{tier}" for name in INSTITUTIONS for tier in ("invested", "deeply_invested")}
    ):
        raise ValueError("制度投入优先级schema或候选分母无效")
    tuning = data["tuning"]
    if any(
        type(value) not in {int, float} or not math.isfinite(value) for value in tuning.values()
    ):
        raise ValueError("制度投入优先级须为有限数值")
    if any(
        not 0.94 <= tuning[f"{name}_deeply_invested"] <= tuning[f"{name}_invested"] < 1
        for name in INSTITUTIONS
    ):
        raise ValueError("制度投入优先级必须保留基础需求余量")
    return data


def inventory(inputs: Mapping[str, str]) -> dict[str, Any]:
    """List complete actual institutional effects without inventing saturation."""
    result: dict[str, Any] = {}
    for source, digest in load()["sources"].items():
        text = inputs.get(source)
        if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != digest:
            raise ValueError(f"制度完整原版来源漂移：{source}")
        parsed = parse_text(text)
        if parsed.errors:
            raise ValueError(f"制度完整原版解析失败：{source}")
        definitions = {}
        for definition in parsed.root.assignments():
            if not isinstance(definition.value, Block):
                raise ValueError("制度原版定义必须为块")
            effects = {}
            for container in ("modifier", "institution_modifier"):
                blocks = definition.value.all(container)
                if len(blocks) > 1:
                    raise ValueError("制度原版效果块重复")
                if not blocks:
                    continue
                block = blocks[0].value
                if not isinstance(block, Block):
                    raise ValueError("制度原版效果必须为块")
                rows = {}
                for row in block.assignments():
                    if not isinstance(row.value, Scalar):
                        raise ValueError("制度原版效果须为有限常数")
                    value = float(row.value.unquoted)
                    if not math.isfinite(value):
                        raise ValueError("制度原版效果须为有限常数")
                    rows[row.key] = value
                effects[container] = rows
            definitions[definition.key] = effects
        result[source] = definitions
    if set(result[INSTITUTION_SOURCE]) != {
        f"institution_{name}" for name in (*INSTITUTIONS, "colonial_affairs")
    }:
        raise ValueError("原版完整七制度分母漂移")
    return result


def verify_inputs(inputs: Mapping[str, str]) -> None:
    inventory(inputs)


def derive(adapters: Mapping[str, Any]) -> dict[str, Any]:
    return _derive(adapters, information=False)


def derive_information(information_data: Mapping[str, Any]) -> dict[str, Any]:
    return _derive(information_data, information=True)


def _derive(adapters: Mapping[str, Any], *, information: bool) -> dict[str, Any]:
    data = load()
    readers: dict[str, Any] = {}
    rules: list[dict[str, Any]] = []

    def c(fact: str, op: str, value: object) -> dict[str, object]:
        return {"fact": fact, "op": op, "value": value}

    # Reuse the existing independent need observations. No financing-health
    # prerequisite is added to recognising the need or its withdrawal tier.
    needs = {
        "social_security": (
            "social_security_present",
            "social_security_investment",
            [[c("average_sol", "<", 8), c("population", ">", 0)]],
        ),
        "workplace_safety": (
            "has_workplace_safety_institution",
            "workplace_safety_investment",
            [[c("industrial_workforce", ">=", 0.1)]],
        ),
        "schools": (
            "schools_present",
            "schools_investment",
            [[c("literacy", "<", 0.5), c("population", ">", 0)]],
        ),
        "police": (
            "has_police_institution",
            "police_investment",
            [[c("owned_state_turmoil", "=", True)]],
        ),
        "health_system": (
            "has_health_system_institution",
            "health_investment",
            [
                [c("current_public_health", "=", True), c("average_sol", "<", 10)],
                [
                    c("current_charitable_health", "=", True),
                    c("grain_price", ">", 0.5),
                    c("grain_balance", "<", 0),
                ],
            ],
        ),
        "home_affairs": (
            "has_home_affairs_institution",
            "home_affairs_investment",
            [[c("insurrection", "=", True)]],
        ),
    }
    selected = (
        ("schools", "social_security")
        if information
        else ("workplace_safety", "police", "health_system", "home_affairs")
    )
    if information:
        for name, present, investment in (
            ("schools", "schools_present", "schools_investment"),
            ("social_security", "social_security_present", "social_security_investment"),
        ):
            readers[present] = {
                "engine": "has_institution",
                "scope": "root",
                "kind": "boolean",
                "unit": "boolean",
                "argument": f"institution_{name}",
            }
            readers[investment] = {
                "engine": "institution_investment_level",
                "scope": "root",
                "kind": "number",
                "unit": "institution_level",
                "minimum": 0,
                "value_field": "value",
                "parameters": {"institution": f"institution_{name}"},
            }
    else:
        readers["has_health_system_institution"] = {
            "engine": "has_institution",
            "scope": "root",
            "kind": "boolean",
            "unit": "boolean",
            "argument": "institution_health_system",
        }
    for name, (present, investment, alternatives) in needs.items():
        if name not in selected:
            continue
        for cause, observed_need in enumerate(alternatives):
            for tier, level in (("invested", 3), ("deeply_invested", 5)):
                rules.append(
                    {
                        "id": f"institution_priority_{name}_{cause}_{tier}",
                        **({} if information else {"source": SOURCE}),
                        "field": f"{'institution_scores' if information else 'ai_strategy_default.institution_scores'}.institution_{name}",
                        "domain": "economy",
                        "priority": 76000 + len(rules),
                        "operation": "multiply",
                        "value": data["tuning"][f"{name}_{tier}"],
                        "semantic_role": "unspecified",
                        "contribution_group": f"institution_{name}_invested_priority_withdrawal",
                        "conditions": [
                            c(present, "=", True),
                            c(investment, ">=", level),
                            *observed_need,
                        ],
                        "why": "本制度对应的真实既有需求仍存在且已有实际投入时，有限撤回新增优先级；保留需求余量、独立融资和行政成本，不把达到设计档位当作需求满足",
                        "counterexample": "3/5投入档及倍率是有界偏好设计，不是原版效果边际递减或当前最高等级。未知投入只退出本分量，未知需求不推出已经满足；不把未观察死亡、失业、政变、灾害和未接通收益当零。玩家、领域关闭和原版资格成本执行保留。",
                    }
                )
    used = {condition["fact"] for rule in rules for condition in rule["conditions"]}
    for key in sorted(used - readers.keys()):
        if key not in adapters["readers"]:
            raise ValueError(f"制度优先级缺少既有精确读取器：{key}")
        readers[key] = adapters["readers"][key]
    return {
        "sources": dict(data["sources"]),
        "readers": readers,
        "rules": rules,
        "covered": [
            {
                "id": name,
                "source": "mod/decisions/information.toml" if information else SOURCE,
                "field": f"{'institution_scores' if information else 'ai_strategy_default.institution_scores'}.institution_{name}",
            }
            for name in selected
        ],
    }
