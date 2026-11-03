"""从无状态协调节点唯一源生成参数注册和固定输入敏感性，不模拟引擎。"""

from __future__ import annotations

import copy
import tomllib
from typing import Any

from . import country_coordination, country_state


def scenarios() -> dict[str, dict[str, Any]]:
    base = {
        key: False if reader["kind"] == "boolean" else max(reader.get("min", 0), 1)
        for key, reader in country_state.load().readers.items()
    }
    base.update(
        debt_ratio=0.1,
        net_surplus=100,
        bureaucracy=100,
        legitimacy=60,
        literacy=0.7,
        population=3_000_000,
        navy=30,
        income=2000,
        industrial_route=True,
        artillery_tech=True,
    )
    # 名称只标记固定输入，不进入生产分支，也不声称是真实国家存档。
    changes: dict[str, dict[str, Any]] = {
        "education_need": {"literacy": 0.3},
        "war_and_education": {"war": True, "literacy": 0.3},
        "overseas_need": {"industrial_route": False, "expansion_route": True},
        "industrial_capacity": {},
        "political_crisis": {"insurrection": True},
        "fiscal_pressure": {"debt_ratio": 0.65},
        "small_admin_shortage": {"bureaucracy": -1},
        "landlocked": {"navy": 0, "industrial_route": False, "expansion_route": True},
        "colonial_subject": {
            "subject": True,
            "industrial_route": False,
            "expansion_route": True,
        },
        "default_and_war": {"default": True, "war": True},
    }
    return {name: {**base, **change} for name, change in changes.items()}


def _parameters(data):
    for section, nodes in data["coordination"].items():
        for name, node in nodes.items():
            for i, clause in enumerate(node["when"]):
                for j, predicate in enumerate(clause):
                    value = predicate["value"]
                    if isinstance(value, bool):
                        continue
                    reader = data["readers"][predicate["fact"]]
                    step = max(abs(value) * 0.1, 0.01 if reader.get("max") == 1 else 1)
                    points = [
                        max(reader.get("min", value - step), value - step),
                        value,
                        min(reader.get("max", value + step), value + step),
                    ]
                    yield (
                        ("coordination", section, name, "when", i, j, "value"),
                        value,
                        points,
                        reader["unit"],
                        node["why"],
                        "未知输入不形成正面能力；独立需求不占全国互斥槽位；不同单位不可相加",
                    )


def audit() -> dict[str, Any]:
    data = tomllib.loads(country_state.SOURCE.read_text(encoding="utf-8"))
    policy = country_state.load()
    profiles = scenarios()
    parameters = []
    for path, value, points, unit, why, counterexample in _parameters(data):
        sensitivity = []
        for point in sorted(set(points)):
            candidate = copy.deepcopy(data)
            target = candidate
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = point
            altered = country_state.from_data(candidate)
            outcomes = {}
            for name, inputs in profiles.items():
                outcomes[name] = country_coordination.evaluate(altered, inputs)
                if any(country_coordination.evaluate(altered, inputs, is_ai=False).values()):
                    raise ValueError(f"国家参数破坏玩家回退：{path}")
            sensitivity.append({"value": point, "coordination": outcomes})
        parameters.append(
            {
                "path": list(path),
                "value": value,
                "unit": unit,
                "range": {"lower": min(points), "upper": max(points)},
                "range_meaning": "audited_local_sensitivity_not_game_balance_guarantee",
                "why": why,
                "counterexample": counterexample,
                "sensitivity": sensitivity,
            }
        )
    return {
        "source_sha256": policy.source_sha256,
        "parameter_count": len(parameters),
        "parameters": parameters,
        "scenarios": {
            name: {
                "inputs": inputs,
                "coordination": country_coordination.evaluate(policy, inputs),
            }
            for name, inputs in profiles.items()
        },
        "dimensions": country_state.DIMENSIONS,
        "readers": policy.readers,
        "evaluation": "vanilla_consumer_demand",
        "evidence": "fixed_input_python_reference_not_engine_execution",
    }
