"""Independent physical-world PDX interpreter for the exact native stance.

No regional adapter/query or ScalarProgram helpers are imported. The grammar is
finite and rejects everything outside the reviewed native and emitted subset.
"""

from __future__ import annotations

import math

from pdx.model import Block, Scalar
from pdx.parser import parse_text


def all3(values):
    return False if False in values else None if None in values else True


def any3(values):
    return True if True in values else None if None in values else False


def not3(value):
    return None if value is None else not value


def child(block, key):
    rows = block.all(key)
    assert len(rows) == 1, key
    assert isinstance(rows[0].value, Block), key
    return rows[0].value


def stance(text):
    parsed = parse_text(text)
    assert not parsed.errors
    return child(
        child(child(parsed.root, "ai_strategy_default"), "strategic_region_stance_type_scores"),
        "stance_colonize_region",
    )


def literal(value):
    assert isinstance(value, Scalar)
    if value.unquoted in {"yes", "no"}:
        return value.unquoted == "yes"
    try:
        return float(value.unquoted)
    except ValueError:
        return value.unquoted


def resolve(name, env, current):
    if name in {"root", "ROOT"}:
        return env["ROOT"]
    if name == "scope:target_region":
        return env["scope:target_region"]
    if name == "owner":
        return None if current is None else current.get("owner")
    if name == "capital.region":
        return env["ROOT"].get("capital_region")
    if name == "this":
        return current
    if name.startswith("sr:"):
        return env.get(name)
    raise AssertionError("unknown independent scope " + name)


def compare(actual, op, expected):
    if actual is None or expected is None:
        return None
    if isinstance(actual, dict) or isinstance(expected, dict):
        assert op in {"=", "!=", "?="}
        return actual is not expected if op == "!=" else actual is expected
    if op == "=":
        return actual == expected
    if op == "!=":
        return actual != expected
    assert type(actual) in {int, float}
    assert math.isfinite(actual)
    assert type(expected) in {int, float}
    assert math.isfinite(expected)
    return {
        ">": actual > expected,
        ">=": actual >= expected,
        "<": actual < expected,
        "<=": actual <= expected,
    }[op]


def condition(block, env, current):
    results = []
    for row in block.assignments():
        key, value = row.key, row.value
        if key in {"AND", "OR", "NOR", "NOT"}:
            assert isinstance(value, Block)
            children = [condition(Block([r]), env, current) for r in value.items]
            result = any3(children) if key in {"OR", "NOR"} else all3(children)
            results.append(not3(result) if key in {"NOT", "NOR"} else result)
        elif key == "exists":
            results.append(resolve(literal(value), env, current) is not None)
        elif key in {"any_scope_state", "any_neighbouring_state"}:
            assert isinstance(value, Block)
            candidates = (
                None
                if current is None
                else current.get("states" if key == "any_scope_state" else "neighbours")
            )
            results.append(
                None if candidates is None else any3([condition(value, env, c) for c in candidates])
            )
        elif key in {"ROOT", "root", "scope:target_region", "owner"} and isinstance(value, Block):
            scoped = resolve(key, env, current)
            results.append(None if scoped is None else condition(value, env, scoped))
        elif key in {
            "has_technology_researched",
            "has_law_or_variant",
            "has_strategy",
            "has_journal_entry",
        }:
            mapping = {
                "has_technology_researched": "technologies",
                "has_law_or_variant": "laws",
                "has_strategy": "strategies",
                "has_journal_entry": "journal",
            }[key]
            entries = None if current is None else current.get(mapping)
            results.append(None if entries is None else entries.get(literal(value)))
        elif key == "is_country_type":
            results.append(
                compare(
                    None if current is None else current.get("country_type"), row.op, literal(value)
                )
            )
        elif key.startswith("num_potential_resources("):
            assert key.endswith(")")
            resource = key[len("num_potential_resources(bt:") : -1]
            entries = None if current is None else current.get("potential_resources")
            results.append(
                compare(None if entries is None else entries.get(resource), row.op, literal(value))
            )
        elif key in {"scope:target_region", "this", "region"}:
            expected = resolve(literal(value), env, current)
            actual = (
                current.get("region")
                if key == "region" and current is not None
                else resolve(key, env, current)
            )
            results.append(compare(actual, row.op, expected))
        elif key in {"is_ai", "navy_size", "country_rank", "country_is_colonial_or_company"}:
            expected = literal(value)
            if expected == "rank_value:minor_power":
                expected = 4
            results.append(compare(None if current is None else current.get(key), row.op, expected))
        else:
            raise AssertionError("unproved independent condition " + key)
    return all3(results)


def number(block, env, current, initial=0):
    result, chain = initial, False
    for row in block.assignments():
        if row.key in {"limit", "desc"}:
            continue
        if row.key in {"if", "else_if", "else"}:
            assert isinstance(row.value, Block)
            if row.key == "if":
                chain = False
            guard = row.value.first("limit")
            if row.key == "else":
                hit = not chain
            else:
                assert guard is not None
                hit = not chain and condition(guard.value, env, current) is True
            if hit:
                result = number(row.value, env, current, result)
                chain = True
            continue
        if row.key == "scope:target_region":
            result = number(row.value, env, env["scope:target_region"], result)
            continue
        if row.key == "every_scope_state":
            candidates = None if current is None else current.get("states")
            assert candidates is not None, (
                "numeric native traversal needs complete state identities"
            )
            limit = row.value.first("limit")
            for state in candidates:
                if limit is None or condition(limit.value, env, state) is True:
                    result = number(row.value, env, state, result)
            continue
        assert row.key in {"value", "add", "multiply", "min", "max"}, row.key
        operand = (
            number(row.value, env, current) if isinstance(row.value, Block) else literal(row.value)
        )
        assert type(operand) in {int, float}
        if row.key == "value":
            result = operand
        elif row.key == "add":
            result += operand
        elif row.key == "multiply":
            result *= operand
        elif row.key == "min":
            result = max(result, operand)
        else:
            result = min(result, operand)
    return result


def evaluate(text, actor, region):
    env = {"ROOT": actor, "scope:target_region": region}
    if region is not None:
        env["sr:" + region.get("id", "")] = region
    return number(stance(text), env, actor)
