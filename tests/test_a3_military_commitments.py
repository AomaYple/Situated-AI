"""Independent hand expectations and parsed production military acceptance PDX."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import asdict, replace
from typing import Any

import pytest

from pdx import config, observation_queries
from pdx import treaty_acceptance_opportunities as production
from pdx.model import Block, Scalar
from pdx.parser import parse_text
from pdx.situated.expressions import truth_all, truth_any, truth_not

pytestmark = pytest.mark.unit
UNKNOWN = object()


@pytest.fixture(scope="module")
def accept():
    return production


@pytest.fixture(scope="module")
def inputs(accept):
    return accept.frozen_inputs()


@pytest.fixture(scope="module")
def patched(accept, inputs):
    return {
        definition: accept.patch(inputs, consumer_program=accept.compile_program(definition))[
            meta[0]
        ]
        for definition, meta in accept.COMMITMENTS.items()
    }


def values(definition, **changes):
    roles = (
        {"first": "A", "second": "B"}
        if definition in {"alliance", "defensive_pact"}
        else {"source": "A", "target": "B"}
    )
    return {
        "root": "A",
        **roles,
        "article_exists": True,
        "is_treaty_active_exists": False,
        "is_renegotiation_exists": False,
        "existing_treaties": [],
        "in_default": False,
        "net_total_income": 0,
        "war_defeat": False,
        **changes,
    }


def env(v, *, ai=True):
    countries: dict[str, dict[str, Any]] = {key: {"id": key} for key in ("A", "B", "C", "D")}
    root = countries.get(v.get("root"))
    if root is not None:
        root.update(
            {
                "is_ai": ai,
                "in_default": v.get("in_default"),
                "net_total_income": v.get("net_total_income"),
                "has_variable": v.get("war_defeat"),
            }
        )
        treaties = v.get("existing_treaties")
        root["treaties"] = (
            None
            if treaties is None
            else [
                {
                    "binds": treaty.get("binds"),
                    "articles": None
                    if treaty.get("articles") is None
                    else [
                        {
                            "has_type": article.get("type"),
                            "source_country": countries.get(article.get("source")),
                        }
                        for article in treaty["articles"]
                    ],
                }
                for treaty in treaties
            ]
        )
    result = {
        "ROOT": root,
        "scope:article": {} if v.get("article_exists") else None,
        "scope:is_treaty_active": UNKNOWN
        if v.get("is_treaty_active_exists") is None
        else object()
        if v.get("is_treaty_active_exists")
        else None,
        "scope:is_renegotiation": UNKNOWN
        if v.get("is_renegotiation_exists") is None
        else object()
        if v.get("is_renegotiation_exists")
        else None,
    }
    for key in ("first", "second", "source", "target"):
        result[f"scope:{key}_country"] = countries.get(v.get(key))
    return result


def literal(value):
    assert isinstance(value, Scalar)
    if value.unquoted in {"yes", "no"}:
        return value.unquoted == "yes"
    try:
        return float(value.unquoted)
    except ValueError:
        return value.unquoted


def resolve(name, world, current):
    if name == "this":
        return current
    if name == "ROOT" or name.startswith("scope:"):
        return world.get(name)
    assert name == "source_country"
    return current.get(name) if current is not None else None


def condition(block, world, current):
    results = []
    for row in block.assignments():
        key, value = row.key, row.value
        if key in {"AND", "OR", "NOT"}:
            children = tuple(condition(Block([child]), world, current) for child in value.items)
            result = truth_any(children) if key == "OR" else truth_all(children)
            results.append(truth_not(result) if key == "NOT" else result)
        elif key == "exists":
            observed = resolve(literal(value), world, current)
            results.append(None if observed is UNKNOWN else observed is not None)
        elif key in {"any_scope_treaty", "any_scope_article"}:
            collection = current.get("treaties" if key == "any_scope_treaty" else "articles")
            results.append(
                None
                if collection is None
                else truth_any(
                    tuple(condition(value, world, candidate) for candidate in collection)
                )
            )
        elif isinstance(value, Block):
            scoped = resolve(key, world, current)
            results.append(None if scoped is None else condition(value, world, scoped))
        elif key == "binds":
            target = resolve(literal(value), world, current)
            collection = current.get("binds")
            results.append(
                None if collection is None or target is None else target["id"] in collection
            )
        elif key == "source_country" or key.startswith("scope:"):
            a, b = resolve(key, world, current), resolve(literal(value), world, current)
            results.append(None if a is None or b is None else a is b)
        elif key == "has_variable":
            assert literal(value) == "recently_lost_war"
            results.append(current.get("has_variable"))
        else:
            assert key in {"is_ai", "in_default", "net_total_income", "has_type"}
            a, b = current.get(key), literal(value)
            if a is None:
                results.append(None)
            elif row.op in {"=", "?="}:
                results.append(type(a) is type(b) and a == b)
            else:
                results.append(
                    None if type(a) not in {int, float} or not math.isfinite(a) else a < b
                )
    return truth_all(tuple(results))


def number(block, world, current, initial=0):
    total, chain = initial, False
    for row in block.assignments():
        if row.key in {"limit", "desc"}:
            continue
        if row.key in {"if", "else_if", "else"}:
            if row.key == "if":
                chain = False
            limit = row.value.first("limit")
            hit = not chain and (
                row.key == "else"
                or (limit is not None and condition(limit.value, world, current) is True)
            )
            if hit:
                total = number(row.value, world, current, total)
                chain = True
            continue
        assert row.key in {"value", "add", "min", "max"}
        operand = (
            number(row.value, world, current)
            if isinstance(row.value, Block)
            else literal(row.value)
        )
        total = (
            operand
            if row.key == "value"
            else total + operand
            if row.key == "add"
            else max(total, operand)
            if row.key == "min"
            else min(total, operand)
        )
    return total


def actual(text, definition, v, *, ai=True, base=0):
    suffix = text.split(f"# SITAI BEGIN treaty_acceptance:{definition}\n")[1].split(
        f"# SITAI END treaty_acceptance:{definition}"
    )[0]
    parsed = parse_text(suffix)
    assert not parsed.errors
    world = env(v, ai=ai)
    return number(parsed.root, world, world["ROOT"], base)


CASES = [
    ({}, 0),
    ({"in_default": True}, -6),
    ({"net_total_income": -1}, -3),
    ({"in_default": True, "net_total_income": -1}, -6),
    ({"war_defeat": True}, -2),
    ({"in_default": True, "war_defeat": True}, -8),
    ({"net_total_income": -1, "war_defeat": True}, -5),
    ({"in_default": None, "net_total_income": -1, "war_defeat": None}, -3),
    ({"in_default": True, "net_total_income": None, "war_defeat": None}, -6),
    ({"in_default": None, "net_total_income": None, "war_defeat": True}, -2),
    ({"in_default": None, "net_total_income": None, "war_defeat": None}, 0),
    ({"net_total_income": float("nan")}, 0),
    ({"in_default": True, "military_expenses": None, "is_at_war": None}, -6),
    ({"in_default": True, "is_treaty_active_exists": True}, 0),
    ({"in_default": True, "is_renegotiation_exists": True}, 0),
    ({"in_default": True, "is_treaty_active_exists": None}, 0),
    ({"in_default": True, "is_renegotiation_exists": None}, 0),
    ({"in_default": True, "article_exists": False}, 0),
    ({"in_default": True, "root": "C"}, 0),
    ({"in_default": True, "root": None}, 0),
    ({"in_default": True, "existing_treaties": None}, 0),
    ({"in_default": True, "existing_treaties": [{"binds": None, "articles": []}]}, -6),
    ({"in_default": True, "existing_treaties": [{"binds": ["A", "B"], "articles": None}]}, 0),
    ({"in_default": True, "existing_treaties": [{"binds": ["A", "C"], "articles": None}]}, -6),
]


@pytest.mark.parametrize(
    "definition", ["support_independence", "guarantee_independence", "alliance", "defensive_pact"]
)
@pytest.mark.parametrize(("changes", "expected"), CASES)
def test_hand_expected_ir_and_actual_suffix(accept, patched, definition, changes, expected):
    v = values(definition, **changes)
    assert accept.compile_program(definition).evaluate(v, is_ai=True) == expected
    assert actual(patched[definition], definition, v) == expected
    assert actual(patched[definition], definition, v, base=-1000) == -1000 + expected


@pytest.mark.parametrize(
    "definition", ["support_independence", "guarantee_independence", "alliance", "defensive_pact"]
)
def test_exact_target_newness_and_frozen_existing_obligations(accept, patched, definition):
    for binds, source, expected in (
        (["A", "B"], "A", 0),
        (["A", "C"], "A", -6),
        (["A", "B"], None, 0),
    ):
        v = values(
            definition,
            in_default=True,
            existing_treaties=[
                {
                    "binds": binds,
                    "frozen": True,
                    "articles": [{"type": definition, "source": source, "active": False}],
                }
            ],
        )
        assert accept.compile_program(definition).evaluate(v, is_ai=True) == expected
        assert actual(patched[definition], definition, v) == expected
    if definition in {"support_independence", "guarantee_independence"}:
        v = values(
            definition,
            in_default=True,
            existing_treaties=[
                {"binds": ["A", "B"], "articles": [{"type": definition, "source": "B"}]}
            ],
        )
        assert accept.compile_program(definition).evaluate(v, is_ai=True) == -6
        assert actual(patched[definition], definition, v) == -6


@pytest.mark.parametrize("definition", ["alliance", "defensive_pact"])
def test_both_mutual_roles_and_swapped_identity(accept, patched, definition):
    for changes, expected in (
        ({"root": "B"}, -6),
        ({"first": "B", "second": "A"}, -6),
        ({"first": "A", "second": "A"}, 0),
        ({"first": None}, 0),
    ):
        v = values(definition, in_default=True, **changes)
        assert accept.compile_program(definition).evaluate(v, is_ai=True) == expected
        assert actual(patched[definition], definition, v) == expected


@pytest.mark.parametrize("definition", ["support_independence", "guarantee_independence"])
def test_directed_target_never_pays_source_commitment(accept, patched, definition):
    for changes, expected in (
        ({"root": "B"}, 0),
        ({"source": "B", "target": "A"}, 0),
        ({"root": "B", "source": "B", "target": "A"}, -6),
        ({"target": None}, 0),
        ({"target": "A"}, 0),
    ):
        v = values(definition, in_default=True, **changes)
        assert accept.compile_program(definition).evaluate(v, is_ai=True) == expected
        assert actual(patched[definition], definition, v) == expected


def test_old_consumers_unchanged_complete_ast_switches_and_writer_identity(accept, inputs, patched):
    # Captured from the production module before military commitments were added.
    legacy = {
        "no_tariffs": {
            "scalar_sha256": "fb8943201e54fab4b7531bd39ec5d00a9295af9449be8acf47ac63aa5b002e25",
        },
        "military_assistance": {
            "scalar_sha256": "dda855d35b6a3a559a3554315f7a9539b23df1f1406524ebaf43a7c9ba91e826",
        },
    }
    for definition, expected in legacy.items():
        program = accept.compile_program(definition)
        scalar = json.dumps(asdict(program.scalar), sort_keys=True, separators=(",", ":")).encode()
        assert hashlib.sha256(scalar).hexdigest() == expected["scalar_sha256"]
        # Typed ports change guard representation; immutable scalar hashes and
        # complete native AST restoration below retain the original contract.
        # The independent actual-PDX matrices in this module and the directed
        # tariff/aid modules prove numeric, role and unknown equivalence.
        graph = program.predicate_ports()
        assert program.writer_ir().port_contributions
        assert all(guard in accept.render(program) for guard in program.port_guards().values())
        assert {use.relation_cause for use in graph.graph.uses} == {
            group.id for group in program.scalar.groups
        }
    for definition, text in patched.items():
        program = accept.compile_program(definition)
        stripped = re.sub(
            r"\s*# SITAI BEGIN treaty_acceptance:.*?# SITAI END treaty_acceptance:[^\n]+\n\s*",
            "\n",
            text,
            flags=re.DOTALL,
        )
        assert accept._shape(parse_text(stripped).root) == accept._shape(
            parse_text(inputs[program.source]).root
        )
        assert not parse_text(text).errors
        assert len(program.scalar.groups) == 2
        assert program.writer_ir().validate_acceptance_program() is program
        v = values(definition, in_default=True, war_defeat=True)
        assert actual(text, definition, v, ai=False) == 0
        assert program.evaluate(v, is_ai=False) == 0
        assert program.evaluate(v, is_ai=True, enabled=False) == 0
        assert accept.patch(inputs, consumer_program=program, enabled_domains=frozenset()) == {}
        with pytest.raises(ValueError, match="重复作者"):
            accept.patch(inputs, overlays={program.source: text}, consumer_program=program)
        with pytest.raises(ValueError, match="身份"):
            accept.render(replace(program, field=f"{definition}.ai.contextual_accept_score"))
        rendered = accept.render(program)
        for forbidden in (
            "military_expenses",
            "country_military_goods_cost_mult",
            "scope:treaty",
            "scope:article.treaty",
            "set_variable",
            "every_",
            "any_country",
        ):
            assert forbidden not in rendered


@pytest.mark.integration
def test_full_live_sources_match_frozen_sources(inputs):
    for source, text in inputs.items():
        assert (config.GAME / source).read_text(encoding="utf-8-sig") == text


def test_resigned_parent_drift_is_rejected(accept, inputs, monkeypatch):
    definition = "support_independence"
    source = accept.COMMITMENTS[definition][0]
    changed = {**inputs, source: inputs[source].replace("dp_hungarian_revolution", "dp_imagined")}
    tuning = copy.deepcopy(accept.load())
    tuning["sources"][source] = hashlib.sha256(changed[source].encode()).hexdigest()
    monkeypatch.setattr(accept, "load", lambda: tuning)
    with pytest.raises(ValueError, match="父结构漂移"):
        accept.verify_inputs(changed)


@pytest.mark.parametrize(
    "definition", ["support_independence", "guarantee_independence", "alliance", "defensive_pact"]
)
def test_incomplete_legacy_and_new_target_do_not_become_global_firstness(
    accept, patched, definition
):
    for article, binds, expected in (
        ({"type": None}, ["A", "B"], 0),
        ({"type": "other_article"}, ["A", "B"], -6),
        ({"type": definition, "source": "A"}, None, 0),
        ({"type": definition, "source": "A"}, ["A", "C"], -6),
    ):
        v = values(
            definition, in_default=True, existing_treaties=[{"binds": binds, "articles": [article]}]
        )
        assert accept.compile_program(definition).evaluate(v, is_ai=True) == expected
        assert actual(patched[definition], definition, v) == expected


def test_malformed_mix_and_foreign_observations_fail_or_cannot_supply_known_cost(accept, patched):
    for definition in accept.COMMITMENTS:
        v = values(definition, in_default=None, net_total_income=None, war_defeat=None)
        v["other_country"] = {"in_default": True, "net_total_income": -999, "war_defeat": True}
        v["owner"] = v["other_country"]
        assert accept.compile_program(definition).evaluate(v, is_ai=True) == 0
        assert actual(patched[definition], definition, v) == 0
        malformed: list[dict[str, object]] = [
            {"in_default": "yes"},
            {"war_defeat": 1},
            {"existing_treaties": {}},
            {"existing_treaties": [{"binds": ["A", "B"], "articles": 1}]},
        ]
        for changed in malformed:
            with pytest.raises(ValueError, match="军事"):
                accept.compile_program(definition).evaluate(
                    values(definition, **changed), is_ai=True
                )
        conflicting = (
            {"source": "A"} if definition in {"alliance", "defensive_pact"} else {"first": "A"}
        )
        with pytest.raises(ValueError, match="角色"):
            accept.compile_program(definition).evaluate(
                values(definition, **conflicting), is_ai=True
            )


def test_exact_query_public_routing_readers_and_no_world_scan(accept, inputs):
    for definition in accept.COMMITMENTS:
        program = accept.compile_program(definition)
        reader = next(row for row in program.readers() if row.engine == "any_scope_treaty")
        query = accept.query_from_reader(reader.engine, dict(reader.parameters))
        public_query = observation_queries.from_reader(reader.engine, dict(reader.parameters))
        assert public_query == query
        assert set(observation_queries.required_sources(public_query)) == accept.SOURCES
        public_compiled = observation_queries.compile_query(public_query, inputs)
        assert public_compiled == accept.compile_query(query, inputs)
        assert observation_queries.render(public_query) == accept.render_query(query)
        compiled = accept.compile_query(query, inputs)
        assert compiled.expression == accept.render_query(query)
        assert compiled.world_scans == 0
        assert compiled.local_collections == (
            "country.any_scope_treaty",
            "treaty.any_scope_article",
        )
        assert f"has_type = {definition}" in compiled.expression
        assert "binds = scope:" in compiled.expression
        assert "is_active" not in compiled.expression
        assert "military_expenses" not in compiled.expression
        assert "scope:article.treaty" not in compiled.expression
        if accept.COMMITMENTS[definition][1] == "directed":
            assert "source_country = ROOT" in compiled.expression
            assert "scope:first_country" not in compiled.expression
        else:
            assert "scope:second_country" in compiled.expression
            assert "scope:first_country" in compiled.expression
            assert "source_country" not in compiled.expression
    with pytest.raises(ValueError, match="定义"):
        accept.query_from_reader("any_scope_treaty", {accept.COMMITMENT_PARAMETERS: "imagined"})
