"""国家事实画像和按消费者求值的无持久状态协调器。"""

from __future__ import annotations

import hashlib
import math
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import config, country_coordination

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
_OPS = {"=", "<", "<=", ">", ">="}


@dataclass(frozen=True, slots=True)
class CountryPolicy:
    data: dict[str, Any]
    source_sha256: str
    readers: dict[str, dict[str, Any]]
    enabled: bool


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
        raise ValueError("协调谓词必须是非空 OR-of-AND 列表")
    out = []
    for clause in value:
        if not isinstance(clause, list) or not clause:
            raise ValueError("协调谓词子句必须是非空列表")
        row = []
        for p in clause:
            if not isinstance(p, dict) or set(p) != {"fact", "op", "value"}:
                raise ValueError("协调谓词字段无效")
            fact, op, literal = p["fact"], p["op"], p["value"]
            if fact not in readers or op not in _OPS:
                raise ValueError("协调谓词引用未知事实或操作")
            reader = readers[fact]
            if reader["kind"] == "boolean":
                if op != "=" or type(literal) is not bool:
                    raise ValueError("布尔协调谓词必须等值")
                # A parameterized PDX boolean cannot safely distinguish a
                # false value from an unknown value through a bare NOT block.
                # Keep the route contract three-valued by requiring positive
                # evidence for argumented readers.
                if reader.get("argument") and literal is False:
                    raise ValueError("带参数布尔协调事实不允许否定谓词")
            elif not _finite(literal):
                raise ValueError("数值协调谓词必须有限")
            if ("min" in reader and literal < reader["min"]) or (
                "max" in reader and literal > reader["max"]
            ):
                raise ValueError("协调谓词超出 reader 范围")
            row.append({"fact": fact, "op": op, "value": literal})
        if len({(p["fact"], p["op"], repr(p["value"])) for p in row}) != len(row):
            raise ValueError("协调谓词重复")
        out.append(tuple(row))
    return tuple(out)


def from_data(data, *, source_sha256=""):
    required = {"schema", "enabled", "readers", "dimensions", "coordination"}
    if set(data) != required or data.get("schema") != 2 or type(data.get("enabled")) is not bool:
        raise ValueError("country coordination schema 无效")
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
    normalized = dict(data)
    normalized["coordination"] = country_coordination.normalize(data["coordination"], readers)
    return CountryPolicy(
        normalized, source_sha256, {k: dict(v) for k, v in readers.items()}, data["enabled"]
    )


def load(path: Path = SOURCE):
    data, digest = _load(path)
    return from_data(data, source_sha256=digest)


def contract(policy):
    return {
        "schema": 2,
        "source_sha256": policy.source_sha256,
        "dimensions": list(DIMENSIONS),
        "evaluation": "vanilla_consumer_demand",
        "persistent_variables": [],
        "coordination": country_coordination.contract(policy),
    }


def owned_triggers(_policy):
    return (*(f"{country_coordination.PREFIX}{name}" for name in country_coordination.NAMES),)


def validate(policy, root=None, *, snapshot=None):
    from . import country_interfaces  # noqa: PLC0415 - 提取器复用本模块的合同

    if policy.enabled:
        country_interfaces.validate(policy, root=root, snapshot=snapshot)
    return {
        "enabled": policy.enabled,
        "readers": tuple(policy.readers),
        "triggers": owned_triggers(policy),
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
    return {
        "dimensions": dimensions,
        "is_ai": is_ai,
        "facts": facts,
        "coordination": country_coordination.evaluate(policy, facts, is_ai=is_ai),
        "typed_state": country_coordination.evaluate_typed(policy, facts, is_ai=is_ai).as_dict(),
    }


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


def files(policy):
    if not policy.enabled:
        return {}
    return {
        "common/scripted_triggers/sitai_country_triggers.txt": country_coordination.triggers(policy)
    }
