"""Optional state consumers require exact relative and population reader proof."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any

import pytest
from test_native_boundary_closure import _implicit_fixture
from test_native_parameter_boundary_proofs import _dependencies
from test_native_parameter_closure import _reader_case
from test_native_parameter_contract_reuse import _wire_contract

from pdx import decision_adapters, decision_rules, observation_queries, version_contracts
from pdx.situated import vanilla_inventory
from pdx.situated.native_treatments import _implicit_conditions_known, _resolve, native_treatments

pytestmark = pytest.mark.unit
TAX = "common/buildings/07_government.txt"
PORTUGAL = "common/journal_entries/06_portugal_politics.txt"
MOVEMENT = "common/political_movements/05_slave_revolt_movements.txt"
POP = "common/pop_types/peasants.txt"
METADATA = ".metadata/metadata.json"


@pytest.fixture(params=["tax", "population"])
def local_case(request, tmp_path, monkeypatch):
    template = _reader_case("resource", tmp_path, monkeypatch)
    inventory, native, generated, coverage, source = _implicit_fixture()
    if request.param == "tax":
        native[TAX] = (
            b"building_government_administration={should_auto_expand={occupancy>=0.8 "
            b"OR={state.tax_capacity<state.tax_capacity_usage owner={bureaucracy<-10}}}}"
        )
        trigger = (
            "any_scope_state={filter={is_incorporated=yes} has_building=building_railway percent=1}"
        )
        completion = (
            "outcome={header=je_standard_completion_header "
            "effect_header=je_standard_on_completion_header trigger={" + trigger + "}}"
            if version_contracts.is_115()
            else "complete={" + trigger + "}"
        )
        native[PORTUGAL] = ("je_portugal_regeneration_public_works={" + completion + "}").encode()
        for name in (TAX, PORTUGAL):
            monkeypatch.setitem(
                observation_queries.source_hashes(), name, hashlib.sha256(native[name]).hexdigest()
            )
        readers = tuple(
            decision_rules.Reader(key, engine, "root", "tax_capacity_points", "number")
            for key, engine in (("capacity", "tax_capacity"), ("usage", "tax_capacity_usage"))
        )
        predicate = decision_rules.Predicate(
            "capacity", "<", decision_rules.FactReference("usage", "ROOT.tax_capacity_usage")
        )
    else:
        expected_hashes = dict(vanilla_inventory._parameter_evidence_contract())
        monkeypatch.setattr(
            vanilla_inventory, "_parameter_evidence_contract", lambda: expected_hashes
        )
        native[MOVEMENT] = (
            b"movement_slave_revolt={creation_trigger={OR={any_scope_state={"
            b"pop_type_percent_state={target=pop_type:slaves value>=0.55}}}}}"
        )
        native[POP] = b"peasants={wage_weight=1}"
        for name in (MOVEMENT, POP):
            monkeypatch.setitem(
                expected_hashes,
                name,
                hashlib.sha256(native[name]).hexdigest(),
            )
        readers = (
            decision_rules.Reader(
                "peasants",
                "pop_type_percent_state",
                "root",
                "ratio",
                "number",
                minimum=0,
                maximum=1,
                value_field="value",
                parameters=(("target", "pop_type:peasants"),),
            ),
        )
        predicate = decision_rules.Predicate("peasants", "<", 0.02)
    adapters = decision_adapters.load()
    policy = replace(
        adapters.policies[0][1],
        readers=readers,
        rules=(replace(adapters.policies[0][1].rules[0], conditions=(predicate,)),),
        baseline_sha256=hashlib.sha256(native[source]).hexdigest(),
    )
    adapters = replace(
        adapters,
        sources=tuple((name, hashlib.sha256(raw).hexdigest()) for name, raw in native.items()),
        policies=((source, policy),),
    )
    monkeypatch.setattr(decision_adapters, "load", lambda: adapters)
    metadata = json.loads(template[2][METADATA])
    metadata["consumer_adapters"].update(
        sources=dict(adapters.sources), consumers=[_wire_contract(source, policy, False)]
    )
    generated[METADATA] = json.dumps(metadata).encode()
    statement = decision_rules._scoped_conditions(
        {
            ("root", ()): [
                readers[0].expression(predicate.op, predicate.value),
                *decision_rules._reader_bounds(readers[0]),
            ]
        }
    )
    generated[source] = (
        "candidate={unknown=1 possible={always=yes} ai_value={value=100 "
        f"if={{limit={{{statement}}} add=2}}}}}}"
    ).encode()
    inventory = replace(
        inventory,
        source_hashes={name: hashlib.sha256(raw).hexdigest() for name, raw in native.items()},
    )
    coverage["source_hashes"] = inventory.source_hashes
    return inventory, native, generated, coverage, source, request.param, policy


def _proof(case):
    deps = _dependencies((*case[:3], None))
    proof = deps.parameter_readers(case[4], "candidate", "ai_value", "state")
    node, _ = _resolve(deps.effective.roots[case[4]], "candidate", "ai_value")
    assert node is not None
    return deps, node, proof


def test_exact_local_readers_close_optional_source_boundary(local_case):
    deps, node, proof = _proof(local_case)
    assert proof["status"] == "proven_parameter_reader"
    assert _implicit_conditions_known(node, {"actor_scope": "state"}, deps.native, proof)
    assert not _implicit_conditions_known(node, {"actor_scope": "state"}, deps.native, {})
    result = native_treatments(*local_case[:3], coverage=local_case[3], production_complete=True)
    row = result["rows"][0]
    assert row["source_protection"]["context_closed"]
    assert row["source_protection"]["proven"]
    assert len(row["source_protection"]["implicit_numeric_projections"]) == 1
    assert not row["active_unknown_usage"]
    assert not row["interface"]["control_authorized"]


@pytest.mark.parametrize("fault", ["scope", "getter", "operation", "argument", "extra"])
def test_generated_comparison_must_match_the_used_local_clause(local_case, fault):
    generated, source, kind = local_case[2], local_case[4], local_case[5]
    replacements = (
        {
            "scope": (b"ROOT.tax_capacity_usage", b"owner.tax_capacity_usage"),
            "getter": (b"ROOT.tax_capacity_usage", b"ROOT.bureaucracy"),
            "operation": (b"tax_capacity <", b"tax_capacity >"),
            "argument": (b'"ROOT.tax_capacity_usage"', b'"ROOT.tax_capacity_usage + 1"'),
            "extra": (b"tax_capacity <", b"invented = yes tax_capacity <"),
        }
        if kind == "tax"
        else {
            "scope": (b"ROOT = {", b"owner = {"),
            "getter": (b"pop_type_percent_state", b"pop_type_percent_country"),
            "operation": (b"value < 0.02", b"value > 0.02"),
            "argument": (b"pop_type:peasants", b"pop_type:slaves"),
            "extra": (b"target = pop_type:peasants", b"target = pop_type:peasants extra = yes"),
        }
    )
    before, after = replacements[fault]
    assert before in generated[source]
    generated[source] = generated[source].replace(before, after)
    deps, node, proof = _proof(local_case)
    assert not _implicit_conditions_known(node, {"actor_scope": "state"}, deps.native, proof)
    report = native_treatments(*local_case[:3], coverage=local_case[3], production_complete=True)
    assert not report["rows"][0]["source_protection"]["context_closed"]


@pytest.mark.parametrize("fault", ["bytes", "ast_rehashed", "effective", "duplicate"])
def test_native_local_proof_requires_pinned_ast_and_unique_identity(local_case, monkeypatch, fault):
    _, native, generated, _, _source, kind, _ = local_case
    evidence = TAX if kind == "tax" else MOVEMENT
    if fault == "bytes":
        native[evidence] += b"# drift"
    elif fault == "ast_rehashed":
        native[evidence] = native[evidence].replace(
            b"state.tax_capacity_usage" if kind == "tax" else b"pop_type:slaves", b"invented"
        )
        registry = (
            observation_queries.source_hashes()
            if kind == "tax"
            else vanilla_inventory._parameter_evidence_contract()
        )
        monkeypatch.setitem(registry, evidence, hashlib.sha256(native[evidence]).hexdigest())
        # Even coherently refreshed source claims cannot replace the native AST.
        adapters = decision_adapters.load()
        adapters = replace(
            adapters,
            sources=tuple((name, hashlib.sha256(raw).hexdigest()) for name, raw in native.items()),
        )
        monkeypatch.setattr(decision_adapters, "load", lambda: adapters)
        metadata = json.loads(generated[METADATA])
        metadata["consumer_adapters"]["sources"] = dict(adapters.sources)
        generated[METADATA] = json.dumps(metadata).encode()
    elif fault == "effective":
        generated[evidence] = b"invented={}"
    else:
        family = "buildings" if kind == "tax" else "pop_types"
        definition = "building_government_administration" if kind == "tax" else "peasants"
        generated[f"common/{family}/duplicate.txt"] = f"{definition}={{}}".encode()
    deps, node, proof = _proof(local_case)
    assert not proof
    assert not _implicit_conditions_known(node, {"actor_scope": "state"}, deps.native, proof)


@pytest.mark.parametrize("fault", ["unit", "rhs_scope", "rhs_getter", "self", "reference"])
@pytest.mark.parametrize("local_case", ["tax"], indirect=True)
def test_relative_contract_cannot_license_an_invalid_reader_pair(local_case, monkeypatch, fault):
    policy = local_case[6]
    left, right = policy.readers
    predicate = policy.rules[0].conditions[0]
    if fault == "unit":
        right = replace(right, unit="ratio")
    elif fault == "rhs_scope":
        right = replace(right, scope="target_state")
    elif fault == "rhs_getter":
        right = replace(right, engine="bureaucracy")
    elif fault == "self":
        right = replace(right, engine=left.engine)
    else:
        predicate = replace(predicate, value=decision_rules.FactReference("usage", "ROOT.infamy"))
    policy = replace(
        policy, readers=(left, right), rules=(replace(policy.rules[0], conditions=(predicate,)),)
    )
    adapters = replace(decision_adapters.load(), policies=((local_case[4], policy),))
    monkeypatch.setattr(decision_adapters, "load", lambda: adapters)
    metadata = json.loads(local_case[2][METADATA])
    if fault not in {"unit", "rhs_scope", "rhs_getter"}:
        metadata["consumer_adapters"]["consumers"] = [_wire_contract(local_case[4], policy, False)]
    local_case[2][METADATA] = json.dumps(metadata).encode()
    assert not _proof(local_case)[2]


@pytest.mark.parametrize("local_case", ["population"], indirect=True)
@pytest.mark.parametrize(
    "fault",
    [
        "pop_bytes",
        "pop_identity",
        "duplicate_native",
        "value_field",
        "country_scope",
        "bounds",
        "extra_parameter",
    ],
)
def test_state_population_contract_cannot_expand_past_exact_native_identity(
    local_case, monkeypatch, fault
):
    native = local_case[1]
    policy = local_case[6]
    reader = policy.readers[0]
    if fault == "pop_bytes":
        native[POP] += b"# drift"
    elif fault == "pop_identity":
        native[POP] = b"invented={wage_weight=1}"
        monkeypatch.setitem(
            vanilla_inventory._parameter_evidence_contract(),
            POP,
            hashlib.sha256(native[POP]).hexdigest(),
        )
    elif fault == "duplicate_native":
        native["common/pop_types/duplicate.txt"] = b"peasants={}"
    else:
        changes: dict[str, dict[str, Any]] = {
            "value_field": {"value_field": "percent"},
            "country_scope": {"path": ("owner",)},
            "bounds": {"maximum": 100},
            "extra_parameter": {"parameters": (*reader.parameters, ("extra", "yes"))},
        }
        policy = replace(policy, readers=(replace(reader, **changes[fault]),))
        adapters = replace(decision_adapters.load(), policies=((local_case[4], policy),))
        monkeypatch.setattr(decision_adapters, "load", lambda: adapters)
    assert not _proof(local_case)[2]


@pytest.mark.parametrize("local_case", ["tax"], indirect=True)
def test_real_relative_occurrence_is_rejected_after_moving_to_another_state(local_case):
    deps, after, _ = _proof(local_case)
    source = local_case[4]
    before, _ = _resolve(deps.native.roots[source], "candidate", "unknown")
    assert before is not None
    assert deps.parameter_conditions(before, after, source, "candidate", "ai_value", "state")[1]
    local_case[2][source] = local_case[2][source].replace(b"ROOT = {", b"scope:target_state = {")
    deps, after, _ = _proof(local_case)
    assert not deps.parameter_conditions(before, after, source, "candidate", "ai_value", "state")[1]


def test_existing_country_relative_comparison_keeps_its_independent_reader_proof(
    tmp_path, monkeypatch
):
    case = _reader_case("resource", tmp_path, monkeypatch)
    adapters = decision_adapters.load()
    source, policy = adapters.policies[0]
    extra = (
        decision_rules.Reader("navy", "navy_size", "root", "ships", "number", path=("owner",)),
        decision_rules.Reader("other_navy", "navy_size", "target_country", "ships", "number"),
    )
    relative = decision_rules.Predicate(
        "navy", ">=", decision_rules.FactReference("other_navy", "scope:target_country.navy_size")
    )
    rule = replace(policy.rules[0], conditions=(*policy.rules[0].conditions, relative))
    policy = replace(policy, readers=(*policy.readers, *extra), rules=(rule,))
    monkeypatch.setattr(
        decision_adapters, "load", lambda: replace(adapters, policies=((source, policy),))
    )
    document = json.loads(case[2][METADATA])
    document["consumer_adapters"]["consumers"] = [_wire_contract(source, policy, False)]
    case[2][METADATA] = json.dumps(document).encode()
    proof = _dependencies(case).parameter_readers(source, "candidate", "ai_value", "state")
    assert proof["status"] == "proven_parameter_reader"
    assert {binding["reader"] for binding in proof["bindings"]} == {"price"}
