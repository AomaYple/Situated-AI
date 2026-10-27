"""从国家状态唯一源生成参数注册和固定输入敏感性，不模拟引擎。"""

from __future__ import annotations

import copy
import tomllib
from typing import Any

from . import country_state


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
        "Russia_education": {"literacy": 0.3},
        "Russia_war": {"war": True, "literacy": 0.3},
        "Netherlands_maritime": {"industrial_route": False, "expansion_route": True},
        "Prussia_industry": {},
        "Austria_stability": {"insurrection": True},
        "France_fiscal": {"debt_ratio": 0.65},
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
    for key in ("variable_ttl_days", "switch_cooldown_days", "update_days"):
        value = data[key]
        yield (
            (key,),
            value,
            [value],
            "days",
            "锁定的刷新、路线有效期和切换冷却合同",
            "不可任意改变钩子频率或存档生命周期",
        )
    for name, route in data["routes"].items():
        priority = route["priority"]
        yield (
            ("routes", name, "priority"),
            priority,
            [priority - 1, priority, priority + 1],
            "ordinal",
            "危机抢占、普通路线互斥仲裁",
            "较低优先级不得抢占已成立的紧急路线",
        )
        for budget, cost in route["cost"].items():
            yield (
                ("routes", name, "cost", budget),
                cost,
                [0, cost, 2],
                "shadow_tier",
                "普通路线占用有限影子预算；紧急路线为生存需要绕过预算",
                "影子档位不代表原版货币、资源或实际支出",
            )
    for section, name, stage, tree in [
        *(
            ("routes", name, stage, row[stage])
            for name, row in data["routes"].items()
            for stage in ("enter", "hold")
        ),
        *(
            ("budgets", name, tier, tree)
            for name, levels in data["budgets"].items()
            for tier, tree in levels.items()
        ),
    ]:
        for i, clause in enumerate(tree):
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
                    (section, name, stage, i, j, "value"),
                    value,
                    points,
                    reader["unit"],
                    "能力进入/保持阈值；迟滞减少普通波动引起的切换",
                    "未知输入不能形成正面能力；不同单位不得直接相加",
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
                state = country_state.advance(altered, inputs, None, day=0)
                outcomes[name] = state.route
                # 生命周期/未知/玩家/禁用的同一参考求值，不把敏感性变成引擎证据。
                if any(
                    state.route is not None
                    for state in (
                        country_state.advance(altered, inputs, None, day=0, is_ai=False),
                        country_state.advance(altered, inputs, None, day=0, enabled=False),
                        country_state.advance(altered, {}, None, day=0),
                    )
                ):
                    raise ValueError(f"国家参数破坏玩家、禁用或未知回退：{path}")
            sensitivity.append({"value": point, "routes": outcomes})
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
                "route": country_state.advance(policy, inputs, None, day=0).route,
            }
            for name, inputs in profiles.items()
        },
        "dimensions": country_state.DIMENSIONS,
        "readers": policy.readers,
        "budget_semantics": "single_exclusive_route_reservation; emergencies_bypass_capacity",
        "evidence": "fixed_input_python_reference_not_engine_execution",
    }
