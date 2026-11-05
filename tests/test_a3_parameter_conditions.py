"""Exact current ScalarProgram Reader guards retain independent native proof."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest
from test_native_parameter_boundary_proofs import (
    _conditions,
    _dependencies,
    information_case,  # noqa: F401
)
from test_native_parameter_closure import _reader_case
from test_native_parameter_contract_reuse import _wire_contract

from pdx import (
    decision_adapters,
    decision_rules,
    famine_opportunities,
    subject_dependence_opportunities,
)
from pdx.model import Block
from pdx.parser import parse_bytes
from pdx.situated import programs
from pdx.situated.ir import from_rule
from pdx.situated.native_treatments import _resolve

pytestmark = pytest.mark.unit
METADATA = ".metadata/metadata.json"


@pytest.fixture(
    params=[
        "resource",
        "query",
        "production",
        "conservative",
        "cost_anchor",
        "native_fragment",
        "famine",
        "subject",
    ]
)
def emitted_case(request, tmp_path, monkeypatch):
    kind = request.param
    reader_kind = "resource" if kind in {"conservative", "cost_anchor"} else kind
    case = _reader_case(
        "query" if kind in {"native_fragment", "famine", "subject"} else reader_kind,
        tmp_path,
        monkeypatch,
    )
    source = case[0].surfaces[0].source
    adapters = decision_adapters.load()
    policy = dict(adapters.policies)[source]
    if kind == "native_fragment":
        case[1][source] = case[1][source].replace(
            b"value=10",
            b"value=10 if={limit={exists=ROOT ROOT={any_scope_state={market_access<0.8}}} add=1}",
        )
        policy = replace(policy, baseline_sha256=hashlib.sha256(case[1][source]).hexdigest())
        adapters = replace(
            adapters,
            sources=tuple(
                (name, hashlib.sha256(case[1][name]).hexdigest()) for name, _ in adapters.sources
            ),
        )
    reader = policy.readers[0]
    if kind == "famine":
        case[1].update(
            {name: text.encode() for name, text in famine_opportunities.frozen_inputs().items()}
        )
        case[1]["events/unrelated.txt"] = b"namespace = unrelated unrelated.1 = {}"
        reader = replace(reader, parameters=((famine_opportunities.QUERY_PARAMETER, "affected"),))
        adapters = replace(
            adapters,
            sources=tuple((name, hashlib.sha256(raw).hexdigest()) for name, raw in case[1].items()),
        )
    if kind == "subject":
        case[1].update(
            {
                name: text.encode()
                for name, text in subject_dependence_opportunities.frozen_inputs().items()
            }
        )
        case[1]["common/defines/unrelated.txt"] = b"NPops = { UNRELATED = 1 }"
        case[1].pop(source)
        source = subject_dependence_opportunities.SOURCE
        surface = replace(
            case[0].surfaces[0],
            source=source,
            definition="ai_strategy_subject_overlord_compliance",
            field="weight",
        )
        case = (
            replace(case[0], surfaces=(surface,)),
            case[1],
            case[2],
            case[3],
        )
        policy = replace(policy, baseline_sha256=hashlib.sha256(case[1][source]).hexdigest())
        reader = replace(
            reader,
            engine="AND",
            parameters=(
                (subject_dependence_opportunities.QUERY_PARAMETER, "actual_overlord_above_neutral"),
            ),
        )
        adapters = replace(
            adapters,
            sources=tuple((name, hashlib.sha256(raw).hexdigest()) for name, raw in case[1].items()),
        )
    if kind in {"resource", "conservative", "cost_anchor"}:
        reader = replace(reader, minimum=0, maximum=1)
    rule = policy.rules[0]
    if kind == "subject":
        rule = replace(
            rule,
            field=("ai_strategy_subject_overlord_compliance", "weight"),
            operation="multiply",
        )
    extra_readers: tuple[decision_rules.Reader, ...] = ()
    if kind == "cost_anchor":
        pressure = decision_rules.Reader(
            "pressure", "bureaucracy", "root", "capacity_balance", "number", path=("owner",)
        )
        extra_readers = (pressure,)
        rule = replace(
            rule,
            value=-2,
            conditions=(decision_rules.Predicate(pressure.key, "<", 0),),
            semantic_role="cost",
            conservative_unknown_facts=(pressure.key,),
            unknown_cost_basis="a known market number anchors otherwise unknown pressure",
            unknown_cost_required_known_facts=(reader.key,),
        )
    elif kind == "conservative":
        rule = replace(
            rule,
            value=-2,
            semantic_role="cost",
            conservative_unknown_facts=(reader.key,),
            unknown_cost_basis="unreadable market pressure retains the declared cost",
        )
    else:
        rule = replace(rule, required_known_facts=(reader.key,))
    policy = replace(policy, readers=(reader, *extra_readers), rules=(rule,))
    adapters = replace(adapters, policies=((source, policy),))
    monkeypatch.setattr(decision_adapters, "load", lambda: adapters)
    metadata = json.loads(case[2][METADATA])
    metadata["consumer_adapters"]["sources"] = dict(adapters.sources)
    metadata["consumer_adapters"]["consumers"] = [_wire_contract(source, policy, True)]
    case[2][METADATA] = json.dumps(metadata).encode()
    joint = programs.enable(
        replace(
            policy,
            semantic_ir=tuple(
                replace(from_rule(item, source=source), origin_priority=item.priority)
                for item in policy.rules
            ),
        ),
        source=source,
    )
    words = frozenset(
        {reader.engine, *reader.path, *policy.actor_path}
        | {value for _, value in reader.parameters}
        | {item.engine for item in extra_readers}
    )
    case[2][source] = decision_rules.patch(
        case[1][source].decode(),
        joint,
        baseline=case[1][source].decode(),
        default_strategy=False,
        reader_words=words,
    ).encode()
    return case, kind


def test_actual_shared_scalar_envelopes_prove_every_occurrence(emitted_case):
    case, kind = emitted_case
    rows, valid = _conditions(case)
    assert valid
    proof = next(iter(rows.values()))
    assert proof["actual_occurrences"]
    assert proof["native_sources"]
    assert proof["bindings"]
    if kind == "conservative":
        assert b"NOT = { market_goods_pricier <= 0.25 }" in case[2][case[0].surfaces[0].source]
        assert len(proof["actual_occurrences"]) >= 3


@pytest.mark.parametrize(
    "fault",
    ["argument", "scope", "remove_exists", "move_exists", "extra_occurrence", "bound"],
)
def test_emitted_envelope_rejects_changed_reader_context(emitted_case, fault):
    case, _kind = emitted_case
    surface = case[0].surfaces[0]
    raw = case[2][surface.source]
    if fault == "argument":
        if b"economic_dependence(overlord)" in raw:
            raw = raw.replace(b"economic_dependence(overlord)", b"economic_dependence(ROOT)", 1)
        elif b"has_famine = yes" in raw:
            raw = raw.replace(b"has_famine = yes", b"has_famine = no", 1)
        elif b"production_method = pm_tools" in raw:
            raw = raw.replace(b"production_method = pm_tools", b"production_method = invented", 1)
        elif b"mg:tools" in raw:
            raw = raw.replace(b"mg:tools", b"mg:invented", 1)
        else:
            raw = raw.replace(b"market_access < 1.0", b"market_access < 0.9", 1)
    elif fault == "scope":
        raw = raw.replace(b"ROOT = {", b"scope:target_country = {", 1)
    elif fault == "remove_exists":
        raw = raw.replace(b"exists = ROOT", b"always = yes", 1)
    elif fault == "move_exists":
        # The same token survives, but cannot guard a sibling/outer scope.
        raw = raw.replace(b"exists = ROOT ROOT = {", b"ROOT = { exists = ROOT", 1)
    elif fault == "bound":
        if b"market_goods_pricier >= 0" in raw:
            raw = raw.replace(b"market_goods_pricier >= 0", b"market_goods_pricier >= 0.1", 1)
        elif b"economic_dependence(overlord)" in raw:
            raw = raw.replace(
                b'economic_dependence(overlord)" > 1', b'economic_dependence(overlord)" > 2', 1
            )
        elif b"has_famine = yes" in raw:
            raw = raw.replace(b"has_famine = yes", b"has_famine = no", 1)
        elif b"market_access < 1.0" in raw:
            raw = raw.replace(b"market_access < 1.0", b"market_access < 0.9", 1)
        else:
            raw = raw.replace(
                b"NOT = { is_production_method_active", b"OR = { is_production_method_active", 1
            )
    else:
        deps = _dependencies(case)
        node, state = _resolve(
            deps.effective.roots[surface.source], surface.definition, surface.field
        )
        assert node is not None
        assert state == "found"
        assert isinstance(node.value, Block)
        branch = node.value.all("if")[-1 if _kind == "subject" else 0]
        # Duplicating a complete otherwise-valid signed program must not
        # multiply the permissions for its registered parameter occurrences.
        parsed = parse_bytes(raw, path="duplicate-emitted-program")
        definition, _ = _resolve(parsed.root, surface.definition, surface.field)
        assert definition is not None
        assert isinstance(definition.value, Block)
        definition.value.items.append(branch)
        before, _ = _resolve(deps.native.roots[surface.source], surface.definition, surface.field)
        assert before is not None
        assert not deps.parameter_conditions(
            before,
            definition,
            surface.source,
            surface.definition,
            surface.field,
            surface.actor_scope,
        )[1]
        return
    assert raw != case[2][surface.source]
    case[2][surface.source] = raw
    assert not _conditions(case)[1]


def test_oracle_never_replaces_the_independent_source_contract(emitted_case):
    case, _kind = emitted_case
    source = case[0].surfaces[0].source
    case[1][source] += b" # native drift"
    assert not _conditions(case)[1]


@pytest.mark.parametrize("emitted_case", ["native_fragment"], indirect=True)
def test_native_copy_is_not_licensed_by_the_program_oracle(emitted_case):
    case, kind = emitted_case
    assert kind == "native_fragment"
    source = case[0].surfaces[0].source
    original = b"if={limit={exists=ROOT ROOT={any_scope_state={market_access<0.8}}} add=1}"
    assert original in case[2][source]
    case[2][source] = case[2][source].replace(original, original + b" " + original)
    assert not _conditions(case)[1]


@pytest.mark.parametrize("emitted_case", ["subject"], indirect=True)
@pytest.mark.parametrize("fault", ["duplicate_queried_define", "changed_define_bytes"])
def test_subject_define_proof_rejects_real_leaf_override_or_drift(emitted_case, fault):
    case, _kind = emitted_case
    if fault == "duplicate_queried_define":
        case[2]["common/defines/unrelated.txt"] = (
            b"NPops = { UNRELATED = 1 } NDiplomacy = { ECONOMIC_DEPENDENCE_MIN = 0 }"
        )
    else:
        name = subject_dependence_opportunities.DEFINES
        case[2][name] = case[1][name] + b"\n# drift"
    assert not _conditions(case)[1]


@pytest.mark.parametrize("emitted_case", ["famine"], indirect=True)
def test_documentation_evidence_still_requires_its_locked_bytes(emitted_case):
    case, _kind = emitted_case
    name = famine_opportunities.HELP
    case[1][name] += b"\n# drift"
    assert not _conditions(case)[1]


@pytest.mark.parametrize("emitted_case", ["famine"], indirect=True)
def test_event_namespace_exception_keeps_complete_source_identity(emitted_case):
    case, _kind = emitted_case
    name = famine_opportunities.FINANCE
    case[2][name] = case[1][name].replace(b"namespace", b"invented_namespace", 1)
    assert case[2][name] != case[1][name]
    assert not _conditions(case)[1]


@pytest.mark.usefixtures("information_case")
def test_actual_information_program_has_its_own_emitted_occurrence_proof(request):
    case = request.getfixturevalue("information_case")
    source = case[0].surfaces[0].source
    policy = decision_rules.load()
    joint = programs.enable(
        replace(
            policy,
            semantic_ir=tuple(
                replace(
                    from_rule(item, source="mod/decisions/information.toml"),
                    origin_priority=item.priority,
                )
                for item in policy.rules
            ),
        ),
        source="mod/decisions/information.toml",
    )
    case[2][source] = decision_rules.patch(
        case[1][source].decode(),
        joint,
        baseline=case[1][source].decode(),
        reader_words=frozenset({"market_goods_pricier", "market", "mg:tools"}),
    ).encode()
    assert _conditions(case)[1]
