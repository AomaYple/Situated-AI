"""Strict R2 decoder/adapter boundaries and independent generated-PDX witnesses."""

from __future__ import annotations

import copy
import math
import tomllib
from dataclasses import replace
from typing import Any, cast

import pytest
from test_network_profile import _parsed, _score

from pdx.situated import action_network as net
from pdx.situated import core_contracts as core
from pdx.situated import expressions as ex
from pdx.situated import network_profile as adapter
from pdx.situated import production_profile as native


@pytest.fixture(scope="module")
def profile():
    return native.load_profile(native.BASELINE_ROOT)


@pytest.fixture(scope="module")
def declaration():
    with adapter.SOURCE.open("rb") as handle:
        return tomllib.load(handle)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema",), True),
        (("game_version",), ["1.15.0"]),
        (("action",), {}),
        (("action",), []),
        (("action", 0, "id"), []),
        (("action", 0, "id"), "bad id"),
        (("action", 0, "consumer"), []),
        (("action", 0, "bounds"), "[-4,4]"),
        (("action", 0, "bounds"), [False, 4]),
        (("action", 0, "bounds"), [float("inf"), 4]),
        (("action", 0, "required_facts"), "infrastructure"),
        (("action", 0, "required_facts"), []),
        (("action", 0, "required_facts"), ["infrastructure", "infrastructure"]),
        (("action", 0, "required_facts"), ["severe-shortage"]),
        (("action", 0, "required_facts"), ["literacy"]),
        (("action", 0, "predicate"), "wrong"),
        (("action", 0, "bridge"), {}),
        (("action", 0, "bridge"), []),
        (("action", 0, "bridge", 0, "id"), {}),
        (("action", 0, "bridge", 0, "path"), []),
        (("action", 0, "bridge", 0, "effect"), []),
        (("action", 0, "bridge", 0, "mechanism"), True),
        (("action", 0, "bridge", 0, "objective"), ""),
        (("action", 0, "bridge", 0, "kind"), []),
        (("action", 0, "bridge", 0, "value"), True),
        (("action", 0, "bridge", 0, "value"), "2.0"),
        (("action", 0, "bridge", 0, "rationale"), "  "),
        (("action", 0, "bridge", 0, "rank"), True),
        (("action", 0, "bridge", 0, "all"), []),
        (("action", 0, "bridge", 0, "all", 0, "fact"), []),
        (("action", 0, "bridge", 0, "all", 0, "op"), []),
        (("action", 0, "bridge", 0, "all", 0, "value"), "0.5"),
        (("action", 0, "bridge", 0, "all", 0, "value"), True),
        (("action", 0, "overlap"), "wrong"),
        (("action", 0, "overlap", 0, "rationale"), ""),
        (("action", 1, "residual"), {}),
        (("action", 1, "residual", 0, "bases"), "school-literacy"),
        (("action", 1, "residual", 0, "bases"), []),
        (("action", 1, "residual", 0, "complete"), True),
    ],
)
def test_decoder_rejects_malformed_shapes_ids_and_numeric_values(
    profile, declaration, monkeypatch, path, value
):
    changed = copy.deepcopy(declaration)
    current = changed
    for part in path[:-1]:
        current = current[part]
    current[path[-1]] = value
    original_load = tomllib.load

    def load(handle, **kwargs):
        return changed if handle.name == str(adapter.SOURCE) else original_load(handle, **kwargs)

    monkeypatch.setattr(adapter.tomllib, "load", load)
    with pytest.raises(ValueError):
        adapter.compile_profile(profile)


@pytest.mark.parametrize(
    "kind", ["action", "predicate", "bridge", "condition", "overlap", "residual"]
)
def test_decoder_rejects_duplicate_declarations(profile, declaration, monkeypatch, kind):
    changed = copy.deepcopy(declaration)
    row = changed["action"][0 if kind != "residual" else 1]
    if kind == "action":
        items = changed["action"]
    elif kind == "condition":
        items = row["bridge"][0]["all"]
    else:
        items = row[kind]
    items.append(copy.deepcopy(items[0]))
    original_load = tomllib.load

    def load(handle, **kwargs):
        return changed if handle.name == str(adapter.SOURCE) else original_load(handle, **kwargs)

    monkeypatch.setattr(adapter.tomllib, "load", load)
    with pytest.raises(ValueError):
        adapter.compile_profile(profile)


def _program(
    operation: net.Operation = "add", *, residual: bool = False, replacement: bool = False
) -> net.NetworkProgram:
    consumer = "a0-pol-schools"
    mapped: core.Unit = "consumer_score" if operation == "add" else "multiplier"
    action = net.ActionInstance(
        net.ActionDefinition(
            "witness",
            consumer,
            operation,
            mapped,
            "scalar",
            0 if operation == "add" else 1,
            -100 if operation == "add" else 0.01,
            100,
        ),
        core.EntityKey("country", "actor"),
        core.EntityKey("scalar", "institution_schools"),
        core.TimeIdentity("native-on-demand", 0),
    )
    values = (9.0, 16.0, 25.0) if operation == "add" else (1.3, 1.5 / 1.3, 1.5)
    if replacement:
        values = (3.0, 5.0, 5.0)
    base_condition = ex.Compare("literacy", "lt", 0.35)
    extra_condition = ex.Compare("school-agenda", "eq", True)
    if residual:
        extra_condition = cast("Any", ex.All((base_condition, extra_condition)))
    accounts = tuple(
        net.EffectAccount(
            name,
            name + ".mechanism",
            "benefit",
            consumer,
            mapped,
            "current",
            "native",
            ("test: mapped consumer witness",),
            "development",
        )
        for name in ("base", "extra")
    )
    bridges = tuple(
        net.ActionBridge(
            name + ".bridge",
            action,
            "direct" if name == "base" else "interaction",
            name,
            net.AssessmentTerm(
                name + ".term", name, "benefit", net.Constant(value), name + ".group"
            ),
            ("literacy",) if name == "base" else ("school-agenda",),
            condition,
            ("literacy",)
            if name == "base"
            else ("literacy", "school-agenda")
            if residual
            else ("school-agenda",),
        )
        for name, value, condition in (
            ("base", values[0], base_condition),
            ("extra", values[1], extra_condition),
        )
    )
    groups = tuple(
        net.AssessmentGroup(
            name + ".group",
            (name + ".term",),
            required_fact_ids=("literacy",),
            review_sources=("test: completeness",),
        )
        for name in ("base", "extra")
    )
    reviews = (
        net.OverlapReview(
            "base",
            "extra",
            "residual" if residual else "replacement" if replacement else "independent",
            (
                "test: mapped decomposition"
                if residual
                else "test: complete value replaces base under the same actual literacy baseline"
                if replacement
                else "test: distinct contributions share a current literacy objective source",
            ),
        ),
    )
    return net.compile_action_network(
        net.ActionNetwork(
            (action,),
            bridges,
            groups,
            net.EffectRegistry(accounts, overlaps=reviews),
            facts=tuple(adapter.READERS[name].fact(name) for name in ("literacy", "school-agenda")),
            objectives=(
                net.ObjectiveTemplate(
                    "development",
                    action,
                    ("literacy",),
                    "literacy",
                    action.time,
                    action.time,
                    ("test: current development objective bound to actual literacy observations",),
                ),
            ),
            residuals=(
                net.Residual(
                    "decomposition",
                    ("base",),
                    "extra",
                    net.Constant(values[2]),
                    ("test: mapped algebra",),
                ),
            )
            if residual
            else (),
            replacements=(net.Replacement("replacement", ("base",), "extra"),)
            if replacement
            else (),
        )
    )


@pytest.mark.parametrize(("operation", "expected"), [("add", 25.0), ("multiply", 1.5)])
def test_final_pdx_reconstructs_mapped_residual_in_the_consumer_algebra(operation, expected):
    program = _program(operation, residual=True)
    rendered = adapter.render_program(program)
    facts: dict[str, object | None] = {"literacy": 0.2, "school-agenda": True}
    neutral = 0 if operation == "add" else 1
    assert math.isclose(net.evaluate_network(program, facts).total, expected, rel_tol=1e-14)
    assert math.isclose(
        _score(_parsed(rendered), {**facts, "ai": True}, initial=neutral), expected, rel_tol=1e-14
    )
    assert _score(_parsed(rendered), {**facts, "ai": False}, initial=neutral) == neutral
    assert "divide" not in rendered


@pytest.mark.parametrize("available", [("literacy", "school-agenda"), ("literacy",)])
def test_final_pdx_unknown_replacement_restores_complete_basic_contribution(available):
    program = _program(replacement=True)
    facts: dict[str, object | None] = {
        "literacy": 0.2,
        **({"school-agenda": True} if "school-agenda" in available else {}),
    }
    expected = 5 if "school-agenda" in available else 3
    assert net.evaluate_network(program, facts).total == expected
    rendered = adapter.render_program(program, available=available)
    assert _score(_parsed(rendered), {**facts, "ai": True}) == expected


def test_renderer_rejects_multiple_actions_and_wrong_candidate_context():
    program = _program()
    original = program.network.actions[0]
    second = replace(original, target=core.EntityKey("scalar", "other-institution"))
    multiple = net.compile_action_network(replace(program.network, actions=(original, second)))
    with pytest.raises(ValueError, match="exactly one"):
        adapter.render_program(multiple)
    wrong_context = net.compile_action_network(
        replace(
            program.network,
            actions=(second,),
            bridges=tuple(replace(bridge, action=second) for bridge in program.network.bridges),
            objectives=tuple(replace(goal, action=second) for goal in program.network.objectives),
        )
    )
    with pytest.raises(ValueError, match="candidate context"):
        adapter.render_program(wrong_context)


def test_renderer_rejects_forged_compiled_guards_and_reader_declarations():
    program = _program()
    forged = replace(
        program, contributions=(replace(program.contributions[0], guard=ex.BooleanLiteral(True)),)
    )
    with pytest.raises(ValueError, match="canonical compiled"):
        adapter.render_program(forged)
    fact = replace(program.network.facts[0], reader_id="invented-reader")
    altered = net.compile_action_network(
        replace(program.network, facts=(fact, program.network.facts[1]))
    )
    with pytest.raises(ValueError, match="audited reader"):
        adapter.render_program(altered)


def test_renderer_rejects_reader_authority_from_another_consumer():
    program = _program()
    first = program.network.facts[0]
    borrowed = replace(
        adapter.READERS["influence"].fact("influence"), consumer_ids=("a0-pol-schools",)
    )
    altered = net.compile_action_network(
        replace(program.network, facts=(*program.network.facts, borrowed))
    )
    assert first.id == "literacy"
    with pytest.raises(ValueError, match="audited reader"):
        adapter.render_program(altered)


def test_compile_profile_verifies_the_frozen_reader_evidence(profile, monkeypatch):
    def fail():
        raise ValueError("test frozen evidence drift")

    monkeypatch.setattr(adapter.authority, "verify_frozen", fail)
    with pytest.raises(ValueError, match="evidence drift"):
        adapter.compile_profile(profile)


def test_compile_profile_rejects_capability_source_coverage_drift(profile, monkeypatch):
    modified = dict(adapter.READERS)
    modified["literacy"] = replace(modified["literacy"], source="unreviewed.txt")
    monkeypatch.setattr(adapter, "READERS", modified)
    with pytest.raises(ValueError, match="authority coverage"):
        adapter.compile_profile(profile)


def test_audit_distinguishes_insertion_bounds_from_native_tail_delta(profile):
    programs = {
        item["consumer"]: item
        for item in cast("list[dict[str, Any]]", adapter.audit(profile)["programs"])
    }
    road = programs["a0-econ-road"]
    assert road["insertion_bounds"] == [-4, 4]
    tail = road["native_tail"]
    assert tail["conservative_delta_envelope"] == [-9, 9]
    assert tail["native_zero_factor"] == [0, 1]
    assert tail["capital_factor"] == tail["home_state_factor"] == [1, 1.5]
    assert "journal additions can restore" in tail["zero_behavior"]
    assert "need not be reachable" in tail["envelope_kind"]
    for consumer in ("a0-pol-schools", "a0-dip-relations"):
        program = programs[consumer]
        tail = program["native_tail"]
        assert tail["following_numeric_operations"] == []
        assert tail["delta_formula"] == "insertion_delta"
        assert tail["conservative_delta_envelope"] == program["insertion_bounds"]
    assert (
        "other strategies contribute additively"
        in programs["a0-pol-schools"]["native_tail"]["native_context"]
    )
    assert "multiply = 2 precedes" in programs["a0-dip-relations"]["native_tail"]["native_context"]
    for program in programs.values():
        assert program["native_tail"]["runtime"] == "unknown"
        assert program["native_tail"]["selection_and_execution_effect"] == "unknown"


def test_audit_native_tail_envelope_tracks_the_actual_compiled_bounds(
    profile, declaration, monkeypatch
):
    changed = copy.deepcopy(declaration)
    for action in changed["action"]:
        action["bounds"] = [-2, 5]
    original_load = tomllib.load

    def load(handle, **kwargs):
        return changed if handle.name == str(adapter.SOURCE) else original_load(handle, **kwargs)

    monkeypatch.setattr(adapter.tomllib, "load", load)
    for program in cast("list[dict[str, Any]]", adapter.audit(profile)["programs"]):
        assert program["insertion_bounds"] == [-2, 5]
        expected = [-4.5, 11.25] if program["consumer"] == "a0-econ-road" else [-2, 5]
        assert program["native_tail"]["conservative_delta_envelope"] == expected
