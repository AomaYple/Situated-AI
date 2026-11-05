"""Independent source-cost truth table and parsed actual treaty suffix."""

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


@pytest.fixture(scope="module")
def program():
    return accept.compile_program("military_assistance")


@pytest.fixture(scope="module")
def inputs():
    return accept.frozen_inputs()


@pytest.fixture(scope="module")
def patched(inputs, program):
    return accept.patch(inputs, consumer_program=program)[accept.MILITARY_SOURCE]


def _values(**changes):
    return {
        "root": "A",
        "source": "A",
        "target": "B",
        "article_exists": True,
        "is_treaty_active_exists": False,
        "is_renegotiation_exists": False,
        "existing_treaties": [],
        "military_expenses": 1,
        "net_total_income": 0,
        "in_default": False,
        **changes,
    }


def _environment(values, *, is_ai=True):
    countries: dict[str, dict[str, Any]] = {name: {"id": name} for name in ("A", "B", "C", "D")}
    for name in ("root", "source", "target"):
        identity = values.get(name)
        if isinstance(identity, str):
            countries.setdefault(identity, {"id": identity})
    root = countries.get(values.get("root"))
    if root is not None:
        root.update(
            {
                key: values.get(key)
                for key in ("in_default", "net_total_income", "military_expenses")
            }
        )
        root["is_ai"] = is_ai
        treaties = values.get("existing_treaties")
        root["treaties"] = (
            None
            if treaties is None
            else [
                {
                    "articles": None
                    if treaty.get("articles") is None
                    else [
                        {
                            "has_type": article.get("type"),
                            "source_country": countries.get(article.get("source")),
                            "target_country": countries.get(article.get("target")),
                        }
                        for article in treaty["articles"]
                    ]
                }
                for treaty in treaties
            ]
        )
    return {
        "ROOT": root,
        "scope:source_country": countries.get(values.get("source")),
        "scope:target_country": countries.get(values.get("target")),
        "scope:article": {} if values.get("article_exists") is True else None,
        "scope:is_treaty_active": object()
        if values.get("is_treaty_active_exists") is True
        else None,
        "scope:is_renegotiation": object()
        if values.get("is_renegotiation_exists") is True
        else None,
    }


def _literal(value):
    assert isinstance(value, Scalar)
    if value.unquoted in {"yes", "no"}:
        return value.unquoted == "yes"
    try:
        return float(value.unquoted)
    except ValueError:
        return value.unquoted


def _resolve(name, env, current):
    if name == "this":
        return current
    if name == "ROOT" or name.startswith("scope:"):
        return env.get(name)
    if name in {"source_country", "target_country"}:
        return current.get(name) if current is not None else None
    raise AssertionError(f"Unproved military assistance scope: {name}")


def _compare(actual, op, expected):
    if actual is None or expected is None:
        return None
    if isinstance(actual, dict) or isinstance(expected, dict):
        assert op in {"=", "?="}
        return actual is expected
    if op in {"=", "?="}:
        return type(actual) is type(expected) and actual == expected
    if type(actual) not in {int, float} or not math.isfinite(actual):
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
        if key in {"AND", "OR", "NOT"}:
            assert isinstance(value, Block)
            children = tuple(_condition(Block([child]), env, current) for child in value.items)
            result = truth_any(children) if key == "OR" else truth_all(children)
            results.append(truth_not(result) if key == "NOT" else result)
        elif key == "exists":
            results.append(_resolve(_literal(value), env, current) is not None)
        elif key in {"any_scope_treaty", "any_scope_article"}:
            assert isinstance(value, Block)
            candidates = current.get("treaties" if key == "any_scope_treaty" else "articles")
            results.append(
                None
                if candidates is None
                else truth_any(tuple(_condition(value, env, candidate) for candidate in candidates))
            )
        elif isinstance(value, Block):
            scoped = _resolve(key, env, current)
            results.append(None if scoped is None else _condition(value, env, scoped))
        elif key.startswith("scope:") or key == "source_country":
            results.append(
                _compare(
                    _resolve(key, env, current), row.op, _resolve(_literal(value), env, current)
                )
            )
        else:
            assert key in {
                "is_ai",
                "military_expenses",
                "in_default",
                "net_total_income",
                "has_type",
            }
            results.append(
                _compare(current.get(key) if current is not None else None, row.op, _literal(value))
            )
    return truth_all(tuple(results))


def _number(block, env, current, initial=0):
    total, chain = initial, False
    for row in block.assignments():
        if row.key in {"limit", "desc"}:
            continue
        if row.key in {"if", "else_if", "else"}:
            assert isinstance(row.value, Block)
            if row.key == "if":
                chain = False
            limit = row.value.first("limit")
            hit = not chain and (
                row.key == "else"
                or (limit is not None and _condition(limit.value, env, current) is True)
            )
            if hit:
                total = _number(row.value, env, current, total)
                chain = True
            continue
        assert row.key in {"value", "add", "min", "max"}
        operand = (
            _number(row.value, env, current)
            if isinstance(row.value, Block)
            else _literal(row.value)
        )
        if row.key == "value":
            total = operand
        elif row.key == "add":
            total += operand
        elif row.key == "min":
            total = max(total, operand)
        elif row.key == "max":
            total = min(total, operand)
    return total


def _actual(patched, values, *, is_ai=True, native_inherent=0):
    suffix = patched.split("# SITAI BEGIN treaty_acceptance:military_assistance\n")[1].split(
        "# SITAI END treaty_acceptance:military_assistance"
    )[0]
    parsed = parse_text(suffix)
    assert not parsed.errors
    env = _environment(values, is_ai=is_ai)
    return _number(parsed.root, env, env["ROOT"], native_inherent)


# Hand expectations are independent of ScalarProgram construction and rendering.
CASES = [
    ({}, 0),
    ({"net_total_income": -1}, -6),
    ({"in_default": True}, -10),
    ({"in_default": True, "net_total_income": -1}, -10),
    ({"in_default": True, "net_total_income": None}, -10),
    ({"in_default": None, "net_total_income": -1}, -6),
    ({"in_default": None, "net_total_income": None}, 0),
    ({"in_default": None, "net_total_income": 1}, 0),
    ({"in_default": True, "military_expenses": 1e-100}, -10),
    *[
        ({"in_default": True, "net_total_income": -1, "military_expenses": value}, 0)
        for value in (None, 0, -1, float("nan"), float("inf"), True)
    ],
    *[({"net_total_income": value}, 0) for value in (None, 0, 1, float("nan"), float("inf"), True)],
    ({"root": "B", "in_default": True, "net_total_income": -1}, 0),
    ({"root": "C", "in_default": True}, 0),
    ({"root": "B", "source": "B", "target": "A", "in_default": True}, -10),
    ({"target": "D", "net_total_income": -1}, -6),
    ({"source": "B", "target": "A", "in_default": True}, 0),
    *[({key: None, "in_default": True}, 0) for key in ("root", "source", "target")],
    ({"source": "A", "target": "A", "in_default": True}, 0),
    ({"article_exists": False, "in_default": True}, 0),
    *[
        ({key: True, "in_default": True}, 0)
        for key in ("is_treaty_active_exists", "is_renegotiation_exists")
    ],
    ({"is_treaty_active_exists": True, "is_renegotiation_exists": True, "in_default": True}, 0),
    ({"existing_treaties": None, "in_default": True}, 0),
    ({"existing_treaties": [{"articles": None}], "in_default": True}, 0),
    *[
        (
            {
                "existing_treaties": [
                    {
                        "status": status,
                        "articles": [
                            {"type": "military_assistance", "source": "A", "target": partner}
                        ],
                    }
                ],
                "in_default": True,
            },
            0,
        )
        for status in ("active", "frozen", None)
        for partner in ("B", "C")
    ],
    (
        {
            "existing_treaties": [{"articles": [{"type": "military_assistance", "source": None}]}],
            "in_default": True,
        },
        0,
    ),
    ({"existing_treaties": [{"articles": [{"type": None, "source": "A"}]}], "in_default": True}, 0),
    (
        {
            "existing_treaties": [
                {"articles": [{"type": "military_assistance", "source": "B", "target": "A"}]}
            ],
            "in_default": True,
        },
        -10,
    ),
    (
        {
            "existing_treaties": [
                {"articles": [{"type": "no_tariffs", "source": "A", "target": "B"}]}
            ],
            "net_total_income": -1,
        },
        -6,
    ),
]


@pytest.mark.parametrize(("changes", "expected"), CASES)
def test_independent_truth_table_and_actual_pdx(program, patched, changes, expected):
    values = _values(**changes)
    assert program.evaluate(values, is_ai=True) == expected
    assert _actual(patched, values) == expected


def test_recovery_unknown_auxiliary_and_no_fallback(program, patched):
    for changes, expected in (
        ({}, 0),
        ({"net_total_income": -1}, -6),
        ({"in_default": True, "net_total_income": -1}, -10),
        ({"in_default": None, "net_total_income": -1}, -6),
        (
            {"in_default": True, "military_expenses": None, "army_size": 100000, "is_at_war": True},
            0,
        ),
        ({}, 0),
    ):
        assert program.evaluate(_values(**changes), is_ai=True) == expected
        assert _actual(patched, _values(**changes)) == expected


def test_native_whole_source_tail_qualification_and_effects_preserved(inputs, patched, program):
    stripped = re.sub(
        r"\s*# SITAI BEGIN treaty_acceptance:military_assistance\n.*?"
        r"# SITAI END treaty_acceptance:military_assistance\n\s*",
        "\n",
        patched,
        flags=re.DOTALL,
    )
    assert accept._shape(parse_text(stripped).root) == accept._shape(
        parse_text(inputs[program.source]).root
    )
    rendered = accept.render(program)
    assert "scope:treaty" not in rendered
    assert "scope:article.treaty" not in rendered
    assert "scope:first_country" not in rendered
    assert "scope:second_country" not in rendered
    assert "set_variable" not in rendered
    assert "is_at_war" not in rendered
    assert "army_size" not in rendered
    assert len(program.scalar.groups) == 1
    assert (program.scalar.lower, program.scalar.upper) == (-10, 0)
    for base, changes, expected in (
        (20, {"net_total_income": -1}, 14),
        (20, {"in_default": True}, 10),
        (-1000, {"in_default": True}, -1010),
        (0, {}, 0),
    ):
        assert _actual(patched, _values(**changes), native_inherent=base) == expected
    assert program.writer_ir().acceptance_program is program


def test_source_role_and_financing_readers_have_exact_identity(program, inputs):
    assert program.source == "common/treaty_articles/12_military_assistance.txt"
    assert program.field == "military_assistance.ai.inherent_accept_score"
    assert program.writer_id == "treaty_acceptance_military_assistance"
    assert program.evaluation_context().targets == ()
    reader = next(row for row in program.readers() if row.engine == "any_scope_treaty")
    assert reader.argument is None
    query = accept.query_from_reader(reader.engine, dict(reader.parameters))
    compiled = accept.compile_query(query, inputs)
    assert compiled.world_scans == 0
    assert compiled.local_collections == ("country.any_scope_treaty", "treaty.any_scope_article")
    assert compiled.expression == accept.render_query(query)
    assert "source_country = ROOT" in compiled.expression
    assert "NOT = { exists = source_country }" in compiled.expression
    assert "is_active" not in compiled.expression
    with pytest.raises(ValueError):
        accept.query_from_reader("any_scope_treaty", {accept.QUERY_PARAMETER: "recipient"})


def test_immutable_identity_duplicates_disabled_and_player(inputs, program, patched):
    for changed in (
        replace(program, source=accept.SOURCE),
        replace(program, actor="source_country"),
        replace(program, field="military_assistance.ai.contextual_accept_score"),
        replace(program, scalar=replace(program.scalar, lower=-100)),
    ):
        with pytest.raises(ValueError):
            accept.render(changed)
    with pytest.raises(ValueError, match="重复作者"):
        accept.patch(inputs, overlays={program.source: patched}, consumer_program=program)
    conflict = inputs[program.source].replace("value = -10\n", "value = -11\n", 1)
    with pytest.raises(ValueError, match="双作者"):
        accept.patch(inputs, overlays={program.source: conflict}, consumer_program=program)
    values = _values(in_default=True)
    assert program.evaluate(values, is_ai=False) == 0
    assert _actual(patched, values, is_ai=False) == 0
    assert program.evaluate(values, is_ai=True, enabled=False) == 0
    assert accept.patch(inputs, consumer_program=program, enabled_domains=frozenset()) == {}


@pytest.mark.parametrize(
    "changes",
    [
        {"first": "A", "second": "B"},
        {"existing_treaties": {}},
        {"existing_treaties": [1]},
        {"existing_treaties": [{"articles": 1}]},
        {"existing_treaties": [{"articles": [1]}]},
        {"existing_treaties": [{"articles": [{"type": 1}]}]},
        {"existing_treaties": [{"articles": [{"type": "military_assistance", "source": 1}]}]},
        {"is_treaty_active_exists": "no"},
        {"in_default": "yes"},
    ],
)
def test_malformed_context_hard_fails(program, changes):
    with pytest.raises(ValueError):
        program.evaluate(_values(**changes), is_ai=True)


def test_complete_frozen_sources_live_match_and_whole_source_drift(inputs, program):
    for source in accept.SOURCES:
        assert inputs[source] == normalized_text(
            (config.GAME / source).read_text(encoding="utf-8-sig")
        )
        changed = {**inputs, source: inputs[source] + "\n# drift\n"}
        with pytest.raises(ValueError, match="来源漂移"):
            accept.verify_inputs(changed)
    declaration = parse_text(inputs[program.source]).root.first("military_assistance")
    assert declaration is not None
    assert isinstance(declaration.value, Block)
    modifier = declaration.value.first("source_modifier")
    assert modifier is not None
    assert isinstance(modifier.value, Block)
    cost = modifier.value.first("country_military_goods_cost_mult")
    assert cost is not None
    assert isinstance(cost.value, Scalar)
    assert cost.value.unquoted == "0.10"
    assert (
        hashlib.sha256(inputs[program.source].encode()).hexdigest()
        == accept.load()["sources"][program.source]
    )


@pytest.mark.parametrize(
    ("source", "old", "new"),
    [
        (accept.MILITARY_SOURCE, "kind = directed", "kind = mutual"),
        (accept.MILITARY_SOURCE, "cost = 25", "cost = 26"),
        (
            accept.MILITARY_SOURCE,
            "maintenance_paid_by = source_country",
            "maintenance_paid_by = target_country",
        ),
        (
            accept.MILITARY_SOURCE,
            "country_military_goods_cost_mult = 0.10",
            "country_military_goods_cost_mult = -0.10",
        ),
        (
            accept.MILITARY_SOURCE,
            "country_military_goods_cost_mult = -0.1",
            "country_military_goods_cost_mult = 0.1",
        ),
        (
            accept.MILITARY_SOURCE,
            "source_country = scope:source_country",
            "target_country = scope:source_country",
        ),
        (accept.MILITARY_SOURCE, "scope:source_country ?= this", "scope:target_country ?= this"),
        (accept.POWER_VALUES, "military_expenses < 2000", "unproved_expenses < 2000"),
        (accept.JOIN_BLOC, "add = ai_accept_join_request_score_treaties", "add = unproved_helper"),
        (
            accept.HOST_EMBASSY,
            "add = ai_accept_join_request_score_treaties",
            "add = unproved_helper",
        ),
        (
            accept.DOC,
            "`scope:is_renegotiation`: only set when the treaty is being renegotiated",
            "unproved marker",
        ),
    ],
)
def test_resigned_role_effect_lifecycle_and_same_stage_reader_drift_rejected(
    inputs, monkeypatch, source, old, new
):
    assert old in inputs[source]
    changed = {**inputs, source: inputs[source].replace(old, new)}
    data = accept.load()
    data["sources"][source] = hashlib.sha256(changed[source].encode()).hexdigest()
    monkeypatch.setattr(accept, "load", lambda: data)
    with pytest.raises(ValueError, match="漂移"):
        accept.verify_inputs(changed)


def test_no_tariffs_program_and_suffix_are_unchanged(inputs):
    old = accept.compile_program()
    assert old.definition == "no_tariffs"
    assert (old.scalar.lower, old.scalar.upper) == (-12, 6)
    assert len(old.scalar.groups) == 2
    values = {
        "root": "A",
        "source": "A",
        "target": "B",
        "article_exists": True,
        "input_market_goods_exists": True,
        "tariffs_on_input": True,
        "net_total_income": -1,
        "in_default": False,
    }
    assert old.evaluate(values, is_ai=True) == -8
    assert old.evaluate({**values, "in_default": None}, is_ai=True) == -12
    assert old.evaluate({**values, "root": "B", "input_goods_delta": -1}, is_ai=True) == 6
    assert accept.patch(inputs) == accept.patch(inputs, consumer_program=old)
    assert len(accept.compile_programs()) == 2
