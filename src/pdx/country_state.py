"""有限国家状态与路线协调器。TOML 是唯一规则来源，Python 与生成的 PDX 子集共享谓词、预算和生命周期。"""

from __future__ import annotations

import hashlib
import math
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import config

if TYPE_CHECKING:
    from pathlib import Path

SOURCE = config.REPO / "mod/decisions/country_state.toml"
DIMENSIONS = (
    "fiscal",
    "administrative",
    "political",
    "social",
    "industry",
    "market",
    "diplomacy",
    "military",
    "education",
    "overseas",
    "identity",
    "crisis",
)
ROUTES = ("fiscal_recovery", "stability", "defense", "industry", "education", "maritime")
FACTS = frozenset(
    {
        "war",
        "default",
        "loans",
        "debt_ratio",
        "net_surplus",
        "bureaucracy",
        "legitimacy",
        "literacy",
        "population",
        "navy",
        "industrial_route",
        "resource_route",
        "expansion_route",
        "insurrection",
        "war_defeat",
        "subject",
        "income",
        "artillery_tech",
    }
)
_BUDGETS = ("fiscal", "administrative", "security")
_OPS = {"=", "<", "<=", ">", ">="}
HOOKS = ("on_monthly_pulse_country", "on_country_default", "on_country_no_longer_default")


@dataclass(frozen=True, slots=True)
class CountryPolicy:
    data: dict[str, Any]
    source_sha256: str
    readers: dict[str, dict[str, Any]]
    enabled: bool

    @property
    def ttl_days(self):
        return int(self.data["variable_ttl_days"])

    @property
    def cooldown_days(self):
        return int(self.data["switch_cooldown_days"])


@dataclass(frozen=True, slots=True)
class RuntimeState:
    route: str | None = None
    expires_day: int | None = None
    cooldown_until: int = 0
    variables: dict[str, dict[str, int]] | None = None
    updated_day: int | None = None
    reserved_budget: dict[str, int] | None = None
    __hash__ = None  # type: ignore[assignment]

    def __getitem__(self, key):
        return self.as_dict()[key]

    def __eq__(self, other):
        return self.as_dict() == (other.as_dict() if isinstance(other, RuntimeState) else other)

    def as_dict(self):
        return {
            "route": self.route,
            "expires_day": self.expires_day,
            "cooldown_until": self.cooldown_until,
            "variables": dict(self.variables or {}),
            "updated_day": self.updated_day,
            "reserved_budget": dict(self.reserved_budget or {}),
        }


def _load(path):
    try:
        raw = path.read_bytes()
        data = tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError("country state TOML 无效或不可读") from exc
    return data, hashlib.sha256(raw).hexdigest()


def _finite(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    try:
        return math.isfinite(v)
    except OverflowError:
        return False


def _tree(value, readers):
    if not isinstance(value, list) or not value:
        raise ValueError("路线谓词必须是非空 OR-of-AND 列表")
    out = []
    for clause in value:
        if not isinstance(clause, list) or not clause:
            raise ValueError("路线谓词子句必须是非空列表")
        row = []
        for p in clause:
            if not isinstance(p, dict) or set(p) != {"fact", "op", "value"}:
                raise ValueError("路线谓词字段无效")
            fact, op, literal = p["fact"], p["op"], p["value"]
            if fact not in readers or op not in _OPS:
                raise ValueError("路线谓词引用未知事实或操作")
            reader = readers[fact]
            if reader["kind"] == "boolean":
                if op != "=" or type(literal) is not bool:
                    raise ValueError("布尔路线谓词必须等值")
                # A parameterized PDX boolean cannot safely distinguish a
                # false value from an unknown value through a bare NOT block.
                # Keep the route contract three-valued by requiring positive
                # evidence for argumented readers.
                if reader.get("argument") and literal is False:
                    raise ValueError("带参数布尔路线事实不允许否定谓词")
            elif not _finite(literal):
                raise ValueError("数值路线谓词必须有限")
            if ("min" in reader and literal < reader["min"]) or (
                "max" in reader and literal > reader["max"]
            ):
                raise ValueError("路线谓词超出 reader 范围")
            row.append({"fact": fact, "op": op, "value": literal})
        if len({(p["fact"], p["op"], repr(p["value"])) for p in row}) != len(row):
            raise ValueError("路线谓词重复")
        out.append(tuple(row))
    return tuple(out)


def from_data(data, *, source_sha256=""):
    required = {
        "schema",
        "variable_ttl_days",
        "switch_cooldown_days",
        "update_days",
        "enabled",
        "readers",
        "dimensions",
        "routes",
        "budgets",
    }
    if set(data) != required or data.get("schema") != 1 or type(data.get("enabled")) is not bool:
        raise ValueError("country state schema 无效")
    if (data["variable_ttl_days"], data["switch_cooldown_days"], data["update_days"]) != (
        100,
        62,
        30,
    ):
        raise ValueError("生命周期常量无效")
    readers = data["readers"]
    if not isinstance(readers, dict) or set(readers) != FACTS:
        raise ValueError("reader 合同无效")
    for name, r in readers.items():
        if not isinstance(r, dict) or set(r) - {"engine", "kind", "unit", "argument", "min", "max"}:
            raise ValueError(f"reader {name} 字段无效")
        if (
            not isinstance(r.get("engine"), str)
            or r.get("kind") not in {"boolean", "number"}
            or not isinstance(r.get("unit"), str)
        ):
            raise ValueError(f"reader {name} 类型无效")
        if r["kind"] == "boolean" and ("min" in r or "max" in r):
            raise ValueError(f"reader {name} 范围无效")
        if r["kind"] == "number" and any(not _finite(r[k]) for k in ("min", "max") if k in r):
            raise ValueError(f"reader {name} 范围无效")
        if "min" in r and "max" in r and r["min"] > r["max"]:
            raise ValueError(f"reader {name} 范围倒置")
        argumented = r["engine"] in {"has_strategy", "has_variable", "has_technology_researched"}
        if argumented != ("argument" in r) or (
            "argument" in r
            and (
                not isinstance(r["argument"], str)
                or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", r["argument"])
            )
        ):
            raise ValueError(f"reader {name} 参数无效")
        from .decision_interfaces import reader_scope  # noqa: PLC0415 - Reader 反向依赖状态层
        from .decision_rules import Reader  # noqa: PLC0415

        reader_scope(Reader(name, r["engine"], "root", r["unit"], r["kind"], r.get("argument")), ())
    dimensions = data["dimensions"]
    if not isinstance(dimensions, dict) or set(dimensions) != set(DIMENSIONS):
        raise ValueError("必须定义恰好 12 个维度")
    for item in dimensions.values():
        if (
            not isinstance(item, dict)
            or set(item) != {"facts"}
            or not isinstance(item["facts"], list)
            or not item["facts"]
            or len(item["facts"]) != len(set(item["facts"]))
            or any(f not in readers for f in item["facts"])
        ):
            raise ValueError("维度事实无效")
    routes = data["routes"]
    if not isinstance(routes, dict) or set(routes) != set(ROUTES):
        raise ValueError("必须定义恰好 6 条路线")
    priorities = []
    normalized = dict(data)
    if not isinstance(data["budgets"], dict) or set(data["budgets"]) != set(_BUDGETS):
        raise ValueError("影子预算必须定义财政、行政和安全档位")
    normalized["budgets"] = {}
    for name, levels in data["budgets"].items():
        if not isinstance(levels, dict) or set(levels) != {"1", "2"}:
            raise ValueError("影子预算必须定义 1、2 两档能力条件")
        normalized["budgets"][name] = {
            level: _tree(tree, readers) for level, tree in levels.items()
        }
    normalized["routes"] = {}
    for name, item in routes.items():
        if not isinstance(item, dict) or set(item) != {
            "priority",
            "emergency",
            "enter",
            "hold",
            "cost",
        }:
            raise ValueError(f"路线 {name} 配置字段无效")
        if type(item["priority"]) is not int or type(item["emergency"]) is not bool:
            raise ValueError(f"路线 {name} 优先级无效")
        priorities.append(item["priority"])
        if (
            not isinstance(item["cost"], dict)
            or set(item["cost"]) != set(_BUDGETS)
            or any(type(v) is not int or not 0 <= v <= 2 for v in item["cost"].values())
        ):
            raise ValueError("路线成本无效")
        n = dict(item)
        n["enter"] = _tree(item["enter"], readers)
        n["hold"] = _tree(item["hold"], readers)
        normalized["routes"][name] = n
    if len(priorities) != len(set(priorities)):
        raise ValueError("路线优先级必须互异")
    return CountryPolicy(
        normalized, source_sha256, {k: dict(v) for k, v in readers.items()}, data["enabled"]
    )


def load(path: Path = SOURCE):
    data, digest = _load(path)
    return from_data(data, source_sha256=digest)


def contract(policy):
    return {
        "schema": 1,
        "source_sha256": policy.source_sha256,
        "dimensions": list(DIMENSIONS),
        "route_names": list(ROUTES),
        "variable_ttl_days": policy.ttl_days,
        "switch_cooldown_days": policy.cooldown_days,
        "persistent_variables": [*(f"sitai_route_{r}" for r in ROUTES), "sitai_route_cooldown"],
    }


def owned_variables(_policy):
    return tuple(f"sitai_route_{r}" for r in ROUTES)


def owned_triggers(_policy):
    return tuple(f"sitai_route_{r}_active" for r in ROUTES)


def validate(policy, root=None, *, snapshot=None):
    from . import country_interfaces  # noqa: PLC0415 - 提取器复用本模块的合同

    if policy.enabled:
        country_interfaces.validate(policy, root=root, snapshot=snapshot)
    return {
        "enabled": policy.enabled,
        "readers": tuple(policy.readers),
        "variables": owned_variables(policy),
        "triggers": owned_triggers(policy),
        "hooks": HOOKS,
    }


def _fact(values, key, reader):
    value = values.get(key)
    if value is None:
        return None
    if reader["kind"] == "boolean":
        if type(value) is not bool:
            raise ValueError(f"{key} 必须为 boolean")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} 必须为 finite number")
    try:
        result = float(value)
        if not math.isfinite(result):
            raise ValueError
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{key} 必须为 finite number") from exc
    if ("min" in reader and result < reader["min"]) or ("max" in reader and result > reader["max"]):
        raise ValueError(f"{key} 超出 reader 范围")
    return result


def _predicate(value, op, expected):
    if value is None:
        return False
    if op == "=":
        return value == expected
    if op == "<":
        return value < expected
    if op == "<=":
        return value <= expected
    if op == ">":
        return value > expected
    return value >= expected


def _tree_eval(clauses, facts):
    return any(
        all(_predicate(facts.get(p["fact"]), p["op"], p["value"]) for p in clause)
        for clause in clauses
    )


def _budgets(policy, facts):
    """返回已证实可承担的最高档位；未知高档不抹掉已证实的低档能力。"""
    result: dict[str, int | None] = {}
    for name, levels in policy.data["budgets"].items():
        used = {p["fact"] for tree in levels.values() for clause in tree for p in clause}
        if all(facts.get(key) is None for key in used):
            result[name] = None
        else:
            result[name] = next(
                (level for level in (2, 1) if _tree_eval(levels[str(level)], facts)), 0
            )
    return result


def derive(policy, values, is_ai=True):
    unknown = (
        set(values) - FACTS - {"has_strategy"} if isinstance(values, Mapping) else {"<non-mapping>"}
    )
    if type(is_ai) is not bool or not isinstance(values, Mapping) or unknown:
        raise ValueError("事实输入无效")
    facts = {k: _fact(values, k, policy.readers[k]) for k in policy.readers}
    strategy = values.get("has_strategy")
    if strategy is not None:
        if not isinstance(strategy, Mapping):
            raise ValueError("has_strategy 必须为 mapping")
        mapping = {
            "industrial_route": "ai_strategy_industrial_expansion",
            "resource_route": "ai_strategy_resource_expansion",
            "expansion_route": "ai_strategy_territorial_expansion",
        }
        for key, arg in mapping.items():
            value = strategy.get(arg)
            if value is not None and type(value) is not bool:
                raise ValueError(f"{key} 必须为 boolean")
            facts[key] = value
    dimensions = {}
    for name, item in policy.data["dimensions"].items():
        selected = {k: facts.get(k) for k in item["facts"]}
        status = (
            "unknown"
            if all(v is None for v in selected.values())
            else "known"
            if all(v is not None for v in selected.values())
            else "partial"
        )
        dimensions[name] = {
            "status": status,
            "facts": selected,
            "readers": {k: policy.readers[k] for k in item["facts"]},
        }
    budgets = _budgets(policy, facts)
    eligible = (
        {r: _route_enter(policy, r, facts, budgets) for r in ROUTES}
        if is_ai and policy.enabled
        else dict.fromkeys(ROUTES, False)
    )
    return {
        "dimensions": dimensions,
        "budgets": budgets,
        "eligible": eligible,
        "is_ai": is_ai,
        "facts": facts,
    }


def _route_enter(policy, route, facts, budgets):
    item = policy.data["routes"][route]
    if not _tree_eval(item["enter"], facts):
        return False
    return item["emergency"] or all(
        cost == 0 or (budgets[k] is not None and budgets[k] >= cost)
        for k, cost in item["cost"].items()
    )


def _route_hold(policy, route, facts, budgets):
    item = policy.data["routes"][route]
    if not _tree_eval(item["hold"], facts):
        return False
    return item["emergency"] or all(
        cost == 0 or (budgets[k] is not None and budgets[k] >= cost)
        for k, cost in item["cost"].items()
    )


def _old(previous):
    if previous is None:
        return RuntimeState(variables={})
    if isinstance(previous, RuntimeState):
        old = previous
    elif isinstance(previous, Mapping):
        route = previous.get("route")
        if route not in (*ROUTES, None) or (route and previous.get("expires_day") is None):
            raise ValueError("旧状态路线无效")
        expires_day = previous.get("expires_day")
        cooldown_until = previous.get("cooldown_until", 0)
        updated_day = previous.get("updated_day")
        variables = previous.get("variables", {})
        reserved_budget = previous.get("reserved_budget", {})
        if expires_day is not None and (type(expires_day) is not int or expires_day < 0):
            raise ValueError("旧状态 expires_day 无效")
        if type(cooldown_until) is not int or cooldown_until < 0:
            raise ValueError("旧状态 cooldown_until 无效")
        if updated_day is not None and (type(updated_day) is not int or updated_day < 0):
            raise ValueError("旧状态 updated_day 无效")
        if not isinstance(variables, Mapping) or not isinstance(reserved_budget, Mapping):
            raise ValueError("旧状态变量结构无效")
        if any(
            not isinstance(key, str) or not isinstance(value, Mapping)
            for key, value in variables.items()
        ):
            raise ValueError("旧状态变量条目无效")
        if any(
            not isinstance(key, str) or type(value) is not int or not 0 <= value <= 2
            for key, value in reserved_budget.items()
        ):
            raise ValueError("旧状态预算无效")
        old = RuntimeState(
            route,
            expires_day,
            cooldown_until,
            dict(variables),
            updated_day,
            dict(reserved_budget),
        )
    else:
        raise ValueError("旧状态类型无效")
    if old.route not in (*ROUTES, None) or (old.route and old.expires_day is None):
        raise ValueError("旧状态路线无效")
    if old.expires_day is not None and (type(old.expires_day) is not int or old.expires_day < 0):
        raise ValueError("旧状态 expires_day 无效")
    if type(old.cooldown_until) is not int or old.cooldown_until < 0:
        raise ValueError("旧状态 cooldown_until 无效")
    if old.updated_day is not None and (type(old.updated_day) is not int or old.updated_day < 0):
        raise ValueError("旧状态 updated_day 无效")
    if (old.variables is not None and not isinstance(old.variables, Mapping)) or (
        old.reserved_budget is not None and not isinstance(old.reserved_budget, Mapping)
    ):
        raise ValueError("旧状态变量结构无效")
    if any(
        not isinstance(key, str) or not isinstance(value, Mapping)
        for key, value in (old.variables or {}).items()
    ):
        raise ValueError("旧状态变量条目无效")
    if any(
        not isinstance(key, str) or type(value) is not int or not 0 <= value <= 2
        for key, value in (old.reserved_budget or {}).items()
    ):
        raise ValueError("旧状态预算无效")
    if (
        old.expires_day is not None
        and old.updated_day is not None
        and old.expires_day < old.updated_day
    ):
        raise ValueError("旧状态 expires_day 早于 updated_day")
    return old


def advance(policy, values, previous, *, day, is_ai=True, enabled=True):
    """在一次合法 country 刷新时仲裁；本函数调用不代表引擎会在任意日触发 hook。"""
    if (
        type(day) is not int
        or isinstance(day, bool)
        or day < 0
        or type(is_ai) is not bool
        or type(enabled) is not bool
    ):
        raise ValueError("day/is_ai/enabled 参数无效")
    old = _old(previous)
    if not is_ai or not enabled or not policy.enabled:
        # 引擎即使不执行 Mod hook 也会分别到期路线和冷却变量。
        # 只裁剪到期状态，绝不在关闭或玩家路径刷新 TTL。
        route_live = old.route is not None and old.expires_day is not None and day < old.expires_day
        cooldown = old.cooldown_until if old.cooldown_until > day else 0
        variables = dict(old.variables or {})
        if not route_live:
            for route in ROUTES:
                variables.pop(f"sitai_route_{route}", None)
        if not cooldown:
            variables.pop("sitai_route_cooldown", None)
        if not route_live and not cooldown:
            return RuntimeState(variables={})
        return RuntimeState(
            old.route if route_live else None,
            old.expires_day if route_live else None,
            cooldown,
            variables,
            old.updated_day,
            dict(old.reserved_budget or {}) if route_live else {},
        )
    if not isinstance(values, Mapping):
        raise ValueError("事实输入无效")
    info = derive(policy, values)
    facts, budgets = info["facts"], info["budgets"]
    current = (
        old.route if old.route and old.expires_day is not None and day < old.expires_day else None
    )
    prior_cooldown = old.cooldown_until if old.cooldown_until > day else 0
    emergency = next(
        (
            r
            for r in sorted(ROUTES, key=lambda r: -policy.data["routes"][r]["priority"])
            if policy.data["routes"][r]["emergency"] and _route_enter(policy, r, facts, budgets)
        ),
        None,
    )
    hold = current is not None and _route_hold(policy, current, facts, budgets)
    selected: str | None = None
    if emergency is not None:
        selected = emergency
    elif hold and current is not None:
        if prior_cooldown > day:
            selected = current
        else:
            higher = next(
                (
                    route
                    for route in sorted(
                        ROUTES,
                        key=lambda r: -policy.data["routes"][r]["priority"],
                    )
                    if policy.data["routes"][route]["priority"]
                    > policy.data["routes"][current]["priority"]
                    and _route_enter(policy, route, facts, budgets)
                ),
                None,
            )
            selected = higher or current
    elif prior_cooldown > day:
        selected = None
    else:
        selected = next(
            (
                r
                for r in sorted(ROUTES, key=lambda r: -policy.data["routes"][r]["priority"])
                if _route_enter(policy, r, facts, budgets)
            ),
            None,
        )
    switching = selected != current
    variables = {}
    if selected is not None:
        variables[f"sitai_route_{selected}"] = {"value": 1, "set_day": day}
        expires = day + policy.ttl_days
    else:
        expires = None
    if selected is None:
        cooldown = prior_cooldown
    elif switching:
        cooldown = day + policy.cooldown_days
    else:
        cooldown = prior_cooldown
    if cooldown > day:
        variables["sitai_route_cooldown"] = {
            "value": 1,
            "set_day": cooldown - policy.cooldown_days,
            "expires_day": cooldown,
        }
    cost = policy.data["routes"][selected]["cost"] if selected else dict.fromkeys(_BUDGETS, 0)
    return RuntimeState(selected, expires, cooldown, variables, day, dict(cost))


def _literal(value):
    return "yes" if value is True else "no" if value is False else f"{value:g}"


def _predicate_text(policy, p):
    reader = policy.readers[p["fact"]]
    engine = reader["engine"]
    value = p["value"]
    if reader["kind"] == "boolean":
        if reader.get("argument"):
            token = f"{engine} = {reader['argument']}"
            return token if value is True else f"NOT = {{ {token} }}"
        return f"{engine} = {_literal(value)}"
    return f"{engine} {p['op']} {_literal(value)}"


def _trigger_expr(policy, clauses):
    rows = [
        f"AND = {{ {' '.join(_predicate_text(policy, p) for p in clause)} }}" for clause in clauses
    ]
    return rows[0] if len(rows) == 1 else "OR = { " + " ".join(rows) + " }"


def _route_limit(policy, route, hold):
    item = policy.data["routes"][route]
    expr = _trigger_expr(policy, item["hold" if hold else "enter"])
    if not item["emergency"]:
        extra = [
            _trigger_expr(
                policy,
                tuple(
                    clause
                    for level in range(cost, 3)
                    for clause in policy.data["budgets"][name][str(level)]
                ),
            )
            for name, cost in item["cost"].items()
            if cost
        ]
        if extra:
            expr = f"AND = {{ {expr} {' '.join(extra)} }}"
    return expr


def files(policy):
    names = (
        "common/scripted_triggers/sitai_country_triggers.txt",
        "common/scripted_effects/sitai_country_effects.txt",
        "common/on_actions/sitai_country_on_actions.txt",
    )
    if not policy.enabled:
        return dict.fromkeys(names, "")
    order = sorted(ROUTES, key=lambda r: -policy.data["routes"][r]["priority"])
    lines: list[str] = []
    for route in ROUTES:
        lines.append(
            f"sitai_route_{route}_hold = {{ is_ai = yes {_route_limit(policy, route, True)} }}"
        )
        lines.append(
            f"sitai_route_{route}_candidate = {{ is_ai = yes {_route_limit(policy, route, False)} }}"
        )
    # Do not emit an unreferenced trigger; emergency precedence is inlined in
    # the active-route guards below and an extra global symbol only expands the
    # generated surface without changing behavior.
    for route in ROUTES:
        higher = [
            r
            for r in order
            if policy.data["routes"][r]["emergency"]
            and policy.data["routes"][r]["priority"] > policy.data["routes"][route]["priority"]
        ]
        guard = (
            ""
            if not higher
            else " NOT = { OR = { "
            + " ".join(f"sitai_route_{r}_candidate = yes" for r in higher)
            + " } }"
        )
        lines.append(
            f"sitai_route_{route}_active = {{ is_ai = yes has_variable = sitai_route_{route} sitai_route_{route}_hold = yes{guard} }}"
        )
    triggers = "\n".join(lines) + "\n"
    remove = " ".join(f"remove_variable = sitai_route_{r}" for r in ROUTES)
    branches = []
    first = True
    # Emergency routes preempt immediately, but a matching current emergency is
    # only renewed; it must not refresh the switch cooldown every month.
    for route in order:
        if not policy.data["routes"][route]["emergency"]:
            continue
        candidate = f"sitai_route_{route}_candidate = yes"
        prefix = "if" if first else "else_if"
        first = False
        branches.append(
            f"{prefix} = {{ limit = {{ {candidate} has_variable = sitai_route_{route} }} set_variable = {{ name = sitai_route_{route} value = 1 days = {policy.ttl_days} }} }}"
        )
        branches.append(
            f"else_if = {{ limit = {{ {candidate} }} {remove} set_variable = {{ name = sitai_route_{route} value = 1 days = {policy.ttl_days} }} set_variable = {{ name = sitai_route_cooldown value = 1 days = {policy.cooldown_days} }} }}"
        )
    # Preserve a feasible current route before considering ordinary candidates.
    for route in order:
        higher = [
            candidate
            for candidate in order
            if policy.data["routes"][candidate]["priority"]
            > policy.data["routes"][route]["priority"]
            and not policy.data["routes"][candidate]["emergency"]
        ]
        higher_guard = (
            ""
            if not higher
            else " OR = { has_variable = sitai_route_cooldown NOT = { OR = { "
            + " ".join(f"sitai_route_{candidate}_candidate = yes" for candidate in higher)
            + " } } }"
        )
        branches.append(
            f"else_if = {{ limit = {{ has_variable = sitai_route_{route} sitai_route_{route}_hold = yes{higher_guard} }} set_variable = {{ name = sitai_route_{route} value = 1 days = {policy.ttl_days} }} }}"
        )
    for route in order:
        if policy.data["routes"][route]["emergency"]:
            continue
        candidate = f"sitai_route_{route}_candidate = yes"
        branches.append(
            f"else_if = {{ limit = {{ {candidate} NOT = {{ has_variable = sitai_route_cooldown }} }} {remove} set_variable = {{ name = sitai_route_{route} value = 1 days = {policy.ttl_days} }} set_variable = {{ name = sitai_route_cooldown value = 1 days = {policy.cooldown_days} }} }}"
        )
    effects = (
        "sitai_refresh_country_routes = {\n    if = { limit = { is_ai = yes }\n        "
        + "\n        ".join(branches)
        + f"\n        else = {{ {remove} }}\n    }}\n}}\n"
    )
    hooks = "".join(f"{hook} = {{ on_actions = {{ sitai_refresh_country }} }}\n" for hook in HOOKS)
    hooks += "sitai_refresh_country = { effect = { sitai_refresh_country_routes = yes } }\n"
    return {names[0]: triggers, names[1]: effects, names[2]: hooks}
