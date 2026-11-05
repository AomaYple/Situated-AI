"""Directed acceptance roles and actual article input, independently executed."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import replace
from typing import Any

import pytest

from pdx import config
from pdx import treaty_acceptance_opportunities as accept
from pdx.model import Block, Scalar
from pdx.parser import parse_text
from pdx.situated.expressions import truth_all, truth_any, truth_not
from pdx.textio import normalized_text

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def inputs():
    return accept.frozen_inputs()


@pytest.fixture(scope="module")
def patched(inputs):
    return accept.patch(inputs)[accept.SOURCE]


def test_full_native_documentation_roles_optional_goods_and_actual_effects(inputs):
    assert inputs == {
        source: normalized_text((config.GAME / source).read_text(encoding="utf-8-sig"))
        for source in accept.SOURCES
    }
    accept.verify_inputs(inputs)
    row = accept.consumer_catalog()["no_tariffs"]
    assert row["native_root"] == "country"
    assert row["actor"] == "root"
    assert row["kind"] == "directed"
    assert row["native_unit"] == "acceptance_score"
    assert row["field"] == "no_tariffs.ai.inherent_accept_score"
    assert row["treaty_scope"] == "unavailable_not_consumed"
    assert "unknown_finance=worst_cost" in row["unknown_policy"]
    assert f"{accept.DOC}:585" in row["scope_evidence"]
    assert f"{accept.SOURCE}:159" in row["scope_evidence"]


# This interpreter does not call the module's reference evaluator, evaluate_scalar,
# render guards or precompute query booleans. It parses the actual inserted PDX
# and resolves country identity and the current article's input market goods.
def _literal(value):
    assert isinstance(value, Scalar)
    text = value.unquoted
    if text in {"yes", "no"}:
        return text == "yes"
    try:
        return float(text)
    except ValueError:
        return text


def _resolve(name, env, current):
    if name == "this":
        return current
    if name == "ROOT":
        return env.get("ROOT")
    if name in {"scope:source_country", "scope:target_country", "scope:article"}:
        return env.get(name)
    article = env.get("scope:article")
    if name == "scope:article.input_goods":
        return article.get("input_goods") if article else None
    if name == "scope:article.input_market_goods(root)":
        root = env.get("ROOT")
        good = article.get("input_goods") if article else None
        if not root or good is None:
            return None
        return root.get("market", {}).get(good)
    raise AssertionError(f"Unproved treaty scope: {name}")


def _compare(actual, op, expected):
    if actual is None or expected is None:
        return None
    if isinstance(actual, dict) or isinstance(expected, dict):
        assert op in {"=", "?="}
        assert isinstance(actual, dict)
        assert isinstance(expected, dict)
        return actual is expected
    if op in {"=", "?="}:
        return type(actual) is type(expected) and actual == expected
    if type(actual) not in {float, int} or not math.isfinite(actual):
        return None
    return {
        "<": actual < expected,
        ">": actual > expected,
        ">=": actual >= expected,
        "<=": actual <= expected,
    }[op]


def _condition(block, env, current):
    results = []
    for row in block.assignments():
        key, value = row.key, row.value
        if key in {"NOT", "AND", "OR"}:
            assert isinstance(value, Block)
            children = [_condition(Block([child]), env, current) for child in value.items]
            result = truth_any(tuple(children)) if key == "OR" else truth_all(tuple(children))
            results.append(truth_not(result) if key == "NOT" else result)
        elif key == "exists":
            results.append(_resolve(_literal(value), env, current) is not None)
        elif isinstance(value, Block):
            assert row.op == "="
            scoped = _resolve(key, env, current)
            results.append(_condition(value, env, scoped) if scoped is not None else None)
        elif key.startswith("scope:"):
            results.append(
                _compare(
                    _resolve(key, env, current), row.op, _resolve(_literal(value), env, current)
                )
            )
        elif key == "has_any_tariffs_on":
            good = _resolve(_literal(value), env, current)
            results.append(current.get("tariffs", {}).get(good) if current and good else None)
        else:
            assert key in {"is_ai", "in_default", "net_total_income", "market_goods_delta"}
            results.append(_compare(current.get(key) if current else None, row.op, _literal(value)))
    return truth_all(tuple(results))


def _number(block, env, current, initial=0):
    total = initial
    for row in block.assignments():
        if row.key in {"limit", "desc"}:
            continue
        if row.key == "if":
            assert isinstance(row.value, Block)
            limit = row.value.first("limit")
            assert limit is not None
            assert isinstance(limit.value, Block)
            if _condition(limit.value, env, current) is True:
                total = _number(row.value, env, current, total)
            continue
        assert row.key in {"value", "add", "min", "max"}
        operand = (
            _number(row.value, env, current)
            if isinstance(row.value, Block)
            else _literal(row.value)
        )
        assert type(operand) in {int, float}
        if row.key == "value":
            total = operand
        elif row.key == "add":
            total += operand
        elif row.key == "min":
            total = max(total, operand)
        elif row.key == "max":
            total = min(total, operand)
    return total


def _context(values, *, is_ai=True):
    source: dict[str, Any] | None = {
        "country_id": values.get("source"),
        "is_ai": is_ai,
        "in_default": values.get("in_default"),
        "net_total_income": values.get("net_total_income"),
        "tariffs": {"g:grain": values.get("tariffs_on_input")},
        "market": {"g:grain": {"market_goods_delta": values.get("input_goods_delta")}},
    }
    assert source is not None
    target: dict[str, Any] | None = {**source, "country_id": values.get("target")}
    root: dict[str, Any] | None = (
        source
        if values.get("root") == values.get("source")
        else target
        if values.get("root") == values.get("target")
        else {**source, "country_id": values.get("root")}
    )
    if values.get("root") is None:
        root = None
    if values.get("source") is None:
        source = None
    if values.get("target") is None:
        target = None
    if values.get("root") == values.get("source") == values.get("target"):
        target = source
    if root is not None and values.get("input_market_goods_exists") is not True:
        root["market"] = {}
    return {
        "ROOT": root,
        "scope:source_country": source,
        "scope:target_country": target,
        "scope:article": {"input_goods": "g:grain"}
        if values.get("article_exists") is True
        else None,
    }


def _actual(patched, env):
    suffix = patched.split("# SITAI BEGIN treaty_acceptance:no_tariffs\n")[1].split(
        "# SITAI END treaty_acceptance:no_tariffs"
    )[0]
    parsed = parse_text(suffix)
    assert not parsed.errors
    return _number(parsed.root, env, env.get("ROOT"))


def _values(**changes):
    return {
        "root": "A",
        "source": "A",
        "target": "B",
        "article_exists": True,
        "input_market_goods_exists": True,
        "tariffs_on_input": True,
        "in_default": False,
        "net_total_income": 0,
        "input_goods_delta": -1,
        **changes,
    }


CASES = [
    ({}, 0),
    ({"net_total_income": -0.01}, -8),
    ({"in_default": True}, -12),
    ({"in_default": True, "net_total_income": -10}, -12),
    ({"in_default": None}, -12),
    ({"net_total_income": None}, -12),
    ({"in_default": None, "net_total_income": None}, -12),
    ({"net_total_income": float("nan")}, -12),
    ({"tariffs_on_input": False, "in_default": True}, 0),
    ({"tariffs_on_input": None, "in_default": True}, 0),
    ({"input_market_goods_exists": False, "in_default": True}, 0),
    ({"root": "B"}, 6),
    ({"root": "B", "input_goods_delta": 0}, 0),
    ({"root": "B", "input_goods_delta": None}, 0),
    ({"root": "B", "input_goods_delta": True}, 0),
    ({"root": "B", "in_default": True, "net_total_income": -10}, 6),
    ({"root": "B", "tariffs_on_input": False}, 6),
    ({"root": "C", "in_default": True}, 0),
    ({"root": None}, 0),
    ({"source": None}, 0),
    ({"target": None}, 0),
    ({"article_exists": False}, 0),
    ({"input_market_goods_exists": False, "root": "B"}, 0),
    ({"source": "A", "target": "A", "in_default": True}, 0),
]


@pytest.mark.parametrize(("changes", "expected"), CASES)
def test_independent_hand_calculations_reference_and_actual_pdx(patched, changes, expected):
    values = _values(**changes)
    assert accept.evaluate(values, is_ai=True) == expected
    assert _actual(patched, _context(values)) == expected


def test_foreign_country_goods_and_article_decoys_never_supply_roles_or_input(patched):
    values = _values(root="B", input_goods_delta=1)
    env = _context(values)
    env["scope:other_country"] = {"in_default": True, "net_total_income": -1000}
    env["ROOT"]["market"]["g:oil"] = {"market_goods_delta": -1000}
    env["scope:article"]["input_goods"] = "g:oil"
    assert _actual(patched, env) == 6
    env["scope:article"]["input_goods"] = "g:grain"
    assert _actual(patched, env) == 0
    env["scope:article"]["input_goods"] = "g:nonexistent"
    assert _actual(patched, env) == 0
    env["scope:article"]["input_goods"] = "g:grain"
    env["ROOT"]["market"] = {}
    env["scope:source_country"]["market"] = {"g:grain": {"market_goods_delta": -1000}}
    assert _actual(patched, env) == 0


def _tree(block):
    return [
        (r.key, r.op, r.prefix, _tree(r.value) if isinstance(r.value, Block) else r.value.unquoted)
        for r in block.assignments()
    ]


def test_complete_ordered_native_ast_and_native_caps_execution_eligibility_preserved(
    inputs, patched
):
    stripped = re.sub(
        r"\s*# SITAI BEGIN treaty_acceptance:no_tariffs\n.*?# SITAI END treaty_acceptance:no_tariffs\n\s*",
        "\n",
        patched,
        flags=re.DOTALL,
    )
    assert _tree(parse_text(stripped).root) == _tree(parse_text(inputs[accept.SOURCE]).root)
    assert "scope:treaty" not in accept.render(accept.compile_program())
    assert "scope:first_country" not in accept.render(accept.compile_program())
    assert "scope:second_country" not in accept.render(accept.compile_program())
    assert "set_variable" not in accept.render(accept.compile_program())
    assert accept.patch(inputs, enabled_domains=frozenset()) == {}
    assert accept.evaluate(_values(in_default=True), is_ai=False) == 0
    assert accept.evaluate(_values(in_default=True), is_ai=True, enabled_domains=frozenset()) == 0
    assert _actual(patched, _context(_values(in_default=True), is_ai=False)) == 0
    with pytest.raises(ValueError, match="重复作者"):
        accept.patch(inputs, overlays={accept.SOURCE: patched})
    conflict = inputs[accept.SOURCE].replace("value = -25", "value = -24", 1)
    with pytest.raises(ValueError, match="双作者"):
        accept.patch(inputs, overlays={accept.SOURCE: conflict})


@pytest.mark.parametrize(
    ("source", "old", "new"),
    [
        (accept.SOURCE, "kind = directed", "kind = mutual"),
        (accept.SOURCE, "scope:source_country ?= this", "scope:target_country ?= this"),
        (accept.SOURCE, "set_import_tariff_level", "set_import_tariff_level_bad"),
        (accept.SOURCE, "no_tariffs_or_subventions", "protect_domestic_supply"),
        (accept.DOC, "There is no `scope:treaty` here", "There is a `scope:treaty` here"),
        (
            accept.DOC,
            "The country we're looking to check the acceptance on.",
            "The article proposer.",
        ),
        (
            accept.GOODS_TRANSFER,
            'exists = "scope:article.input_market_goods(root)"',
            "exists = scope:other_country",
        ),
        (accept.INCOME, "net_total_income > 0", "net_total_income_bad > 0"),
    ],
)
def test_complete_source_and_resigned_role_effect_docs_getter_drift_rejected(
    inputs, monkeypatch, source, old, new
):
    changed = dict(inputs)
    assert old in changed[source]
    changed[source] = changed[source].replace(old, new)
    with pytest.raises(ValueError, match="来源漂移"):
        accept.verify_inputs(changed)
    data = accept.load()
    data["sources"][source] = hashlib.sha256(changed[source].encode()).hexdigest()
    monkeypatch.setattr(accept, "load", lambda: data)
    with pytest.raises(ValueError, match="漂移"):
        accept.verify_inputs(changed)


def test_frozen_offline_program_uses_shared_scalar_and_rejects_mutation(
    inputs, monkeypatch, tmp_path
):
    expected = accept.patch(inputs)
    monkeypatch.setattr(config, "GAME", tmp_path / "absent")
    assert accept.patch(accept.frozen_inputs()) == expected
    program = accept.compile_program()
    assert len(program.scalar.groups) == 2
    assert program.scalar.lower == -12
    assert program.scalar.upper == 6
    with pytest.raises(ValueError, match="漂移"):
        accept.render(replace(program, kind="mutual"))
    with pytest.raises(ValueError, match="漂移"):
        accept.render(replace(program, scalar=replace(program.scalar, upper=100)))
