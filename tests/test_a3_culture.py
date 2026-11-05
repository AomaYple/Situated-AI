"""Actual country religion exposure, exact legal effect and shared production."""

from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import replace

import pytest
from test_remaining_joint_consumers import _overlay
from test_situated_joint_witnesses import _facts

from pdx import (
    config,
    country_state,
    decision_adapters,
    decision_interfaces,
    decision_rules,
    observation_queries,
)
from pdx import culture_opportunities as culture
from pdx.lexer import tokenize
from pdx.model import Block
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval, programs, resources
from pdx.textio import normalized_text

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def frozen():
    return culture.frozen_inputs()


def test_complete_native_sources_exact_legal_effect_delta_and_finite_aggregate_query(frozen):
    assert frozen == {
        source: normalized_text((config.GAME / source).read_text(encoding="utf-8-sig"))
        for source in culture.SOURCES
    }
    refs = culture.verify_inputs(frozen)
    assert f"{culture.LOBBIES}:1140" in refs
    assert f"{culture.LOBBIES}:1144" in refs
    assert f"{culture.ALGERIA}:168" in refs
    assert f"{culture.VALUES}:166" in refs
    query = observation_queries.from_reader("OR", {"culture_query": "nonstate_religious_exposure"})
    compiled = observation_queries.compile_query(query, frozen)
    assert compiled.references == refs
    assert set(dict(compiled.source_hashes)) == culture.SOURCES
    assert set(observation_queries.required_sources(query)) == culture.SOURCES
    assert compiled.local_collections == ()
    assert compiled.world_scans == 0
    assert "51" in compiled.runtime_cost
    assert "unknown" in compiled.unknown_policy
    metrics = resources.pdx_metrics(compiled.expression)
    assert metrics["object_scan_sites"] == 0
    assert metrics["persistent_write_sites"] == 0
    root = parse_text(compiled.expression).root
    logical = root.first("OR")
    assert logical is not None
    assert isinstance(logical.value, Block)
    assert len(logical.value.all("AND")) == len(culture.RELIGIONS) == 17
    assert [
        b - a
        for a, b in zip(
            culture.EFFECTS[culture.ORIGIN], culture.EFFECTS[culture.CANDIDATE], strict=True
        )
    ] == [-5, 15, 15, 25]


@pytest.mark.parametrize(
    ("engine", "params"),
    [
        ("OR", {}),
        ("OR", {"culture_query": "anything"}),
        ("OR", {"culture_query": "nonstate_religious_exposure", "threshold": "0"}),
        ("OR", {"culture_query": "nonstate_religious_exposure", "target": "scope:target_country"}),
        ("any_scope_pop", {"culture_query": "nonstate_religious_exposure"}),
        ("OR", {"culture_query": "nonstate_religious_exposure", "script": "always = yes"}),
        ("AND", {"culture_query": "nonstate_religious_exposure"}),
    ],
)
def test_query_rejects_free_script_threshold_foreign_scope_or_unregistered_uppercase(
    engine, params
):
    with pytest.raises(ValueError):
        observation_queries.from_reader(engine, params)


def _minimal_data(engine="OR", params=None):
    derived = culture.derive({})
    readers = copy.deepcopy(derived["readers"])
    readers[culture.READER]["engine"] = engine
    readers[culture.READER]["parameters"] = (
        {"culture_query": "nonstate_religious_exposure"} if params is None else params
    )
    rule = {key: value for key, value in derived["rules"][0].items() if key != "source"}
    return {
        "schema": 1,
        "baseline_sha256": culture.load()["sources"][culture.SOURCE],
        "domains": {"political": True},
        "readers": readers,
        "rules": [rule],
    }


@pytest.mark.parametrize(("engine", "params"), [("OR", {}), ("AND", None), ("EXECUTE", None)])
def test_rule_reader_name_exception_cannot_authorize_bare_or_or_other_uppercase(engine, params):
    with pytest.raises(ValueError):
        decision_rules.from_data(_minimal_data(engine, params), source_sha256="1" * 64)


@pytest.mark.parametrize(
    ("source", "old", "new"),
    [
        (
            culture.SOURCE,
            "country_acceptance_shared_religious_trait_add = 15",
            "country_acceptance_shared_religious_trait_add = 14",
        ),
        (culture.SOURCE, "parent = law_state_religion", "parent = law_total_separation"),
        (culture.LOBBIES, "type = country_event", "type = state_event"),
        (culture.LOBBIES, "target = ROOT.religion", "target = scope:relevant_religion"),
        (culture.HIERARCHY, "target = rel:hindu", "target = rel:sunni"),
        (
            culture.ALGERIA,
            "target = rel:sunni value >= religious_acceptance_medium",
            "target = rel:sunni value >= religious_acceptance_low",
        ),
        (culture.VALUES, "religious_acceptance_very_low = 0", "religious_acceptance_very_low = 1"),
        (culture.RELIGION_SOURCE, "atheist = {", "new_religion = {"),
    ],
)
def test_resigned_source_hash_does_not_hide_scope_dictionary_or_actual_effect_drift(
    frozen, monkeypatch, source, old, new
):
    changed = dict(frozen)
    assert old in changed[source]
    changed[source] = changed[source].replace(old, new)
    with pytest.raises(ValueError, match="漂移"):
        culture.verify_inputs(changed)
    data = culture.load()
    data["sources"][source] = hashlib.sha256(changed[source].encode()).hexdigest()
    monkeypatch.setattr(culture, "load", lambda: data)
    with pytest.raises(ValueError, match="漂移"):
        culture.verify_inputs(changed)


def _religious_facts(*, shares=None, acceptance=None, state="catholic"):
    shares = {"sunni": 0.1} if shares is None else shares
    acceptance = {"sunni": -1} if acceptance is None else acceptance
    return {
        "country_has_state_religion": {
            (("argument", f"rel:{religion}"),): religion == state for religion in culture.RELIGIONS
        },
        "religion_percent_country": {
            (("target", f"rel:{religion}"),): shares.get(religion, 0)
            for religion in culture.RELIGIONS
        },
        "country_average_religious_acceptance": {
            (("target", f"rel:{religion}"),): acceptance.get(religion, 0)
            for religion in culture.RELIGIONS
        },
    }


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, True),
        ({"shares": {"sunni": 0.09999}}, False),
        ({"acceptance": {"sunni": 0}}, False),
        ({"acceptance": {"sunni": None}}, None),
        ({"shares": {"sunni": None}}, None),
        ({"shares": {"sunni": 0.2}, "acceptance": {"hindu": -25}}, False),
        ({"shares": {"catholic": 0.5}, "acceptance": {"catholic": -25}}, False),
        ({"shares": {"hindu": 0.2}, "acceptance": {"hindu": -10}}, True),
        ({"shares": {"atheist": 0.2}, "acceptance": {"atheist": -10}}, True),
        (
            {"shares": {"sunni": None, "hindu": 0.2}, "acceptance": {"sunni": None, "hindu": -10}},
            True,
        ),
        ({"shares": {}}, False),
    ],
)
def test_actual_country_aggregate_pdx_same_religion_identity_and_unknown(kwargs, expected):
    query = parse_text(culture.render_query(culture.ReligiousExposureQuery())).root
    assert pdx_eval.condition(query, _religious_facts(**kwargs)) is expected


@pytest.fixture(scope="module")
def generated():
    adapters = decision_adapters.load()
    original = dict(adapters.policies)[culture.SOURCE]
    rules = tuple(rule for rule in original.rules if ".".join(rule.field) == culture.FIELD)
    assert culture.RULE in {rule.id for rule in rules}
    used = {p.fact for rule in rules for p in rule.conditions}
    policy = replace(
        original,
        rules=rules,
        readers=tuple(r for r in original.readers if r.key in used),
        semantic_ir=(),
        consumer_programs=(),
    )
    policy = programs.enable(policy, source=culture.SOURCE)
    decision_interfaces.validate(policy)
    inputs = decision_adapters.read_inputs(adapters)
    text = decision_rules.patch(
        inputs[culture.SOURCE],
        policy,
        baseline=inputs[culture.SOURCE],
        default_strategy=False,
        country_policy=country_state.load(),
        reader_words=decision_interfaces.proven_reader_words()
        | frozenset(re.findall(r"[A-Za-z_][A-Za-z_0-9:]*", "\n".join(inputs.values()))),
    )
    return policy, inputs, text, _overlay(text, culture.FIELD)


def _witness(
    generated,
    *,
    exposure=True,
    current=culture.ORIGIN,
    authority=100,
    political=False,
    ai=True,
    religion_kwargs=None,
):
    policy, _, _, overlay = generated
    values = {
        r.key: False if r.kind == "boolean" else max(r.minimum or 0, 0) for r in policy.readers
    }
    for law in (culture.ORIGIN, *culture.VARIANTS, culture.CANDIDATE):
        # has_law_or_variant(parent) is also true for the two excluded variants.
        active = law == current or (law == culture.ORIGIN and current in culture.VARIANTS)
        values[f"culture_current_{law}"] = active
        values[f"law_context_current_{law}"] = active
    values.update(
        {
            culture.READER: exposure,
            "authority": authority,
            "legitimacy": 20 if political else 60,
            "radical_share": 0.3 if political else 0,
            "insurrection": political,
        }
    )
    facts = _facts(policy, values, is_ai=ai)
    facts["ROOT"].update(_religious_facts(**(religion_kwargs or {})))
    facts["ROOT"]["any_political_movement"] = []
    actual = pdx_eval.select(overlay, facts).delta
    result = decision_rules.evaluate(policy, values, is_ai=ai).get(culture.FIELD)
    return actual, result[1] if result else 0, values, facts


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, 6),
        ({"authority": 99}, -2),
        ({"authority": 99, "political": True}, -12),
        ({"exposure": False, "religion_kwargs": {"shares": {}}}, 0),
        ({"exposure": None, "religion_kwargs": {"acceptance": {"sunni": None}}}, 0),
        ({"authority": 99, "exposure": None, "religion_kwargs": {"shares": {"sunni": None}}}, -8),
        ({"current": culture.CANDIDATE}, 0),
        ({"current": "law_millet_system"}, 0),
        ({"current": "law_people_of_the_book"}, 0),
        ({"current": None}, 0),
        ({"ai": False}, 0),
    ],
)
def test_new_observed_need_joins_existing_authority_and_political_cost_in_same_shared_program(
    generated, kwargs, expected
):
    actual, reference, _, _ = _witness(generated, **kwargs)
    assert actual == reference == expected
    assert len(generated[0].consumer_programs) == 1


def test_foreign_decoys_missing_member_data_disable_and_complete_native_preservation(generated):
    policy, inputs, text, overlay = generated
    _, _, values, facts = _witness(generated, exposure=False, religion_kwargs={"shares": {}})
    facts["scope:target_country"] = _religious_facts()
    facts["ROOT"]["owner"] = _religious_facts()
    facts["ROOT"]["OR"] = {(("culture_query", "nonstate_religious_exposure"),): True}
    assert pdx_eval.select(overlay, facts).delta == 0
    facts["ROOT"] = {"is_ai": True, **_religious_facts(shares={})}
    facts["ROOT"]["religion_percent_country"].pop((("target", "rel:sunni"),))
    query = parse_text(culture.render_query(culture.ReligiousExposureQuery())).root
    assert pdx_eval.condition(query, facts["ROOT"]) is None
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    assert (
        decision_rules.patch(
            inputs[culture.SOURCE],
            policy,
            baseline=inputs[culture.SOURCE],
            default_strategy=False,
            enabled_domains=frozenset(),
        )
        == inputs[culture.SOURCE]
    )
    restored = re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        text,
        flags=re.DOTALL,
    )
    assert [(t.kind, t.value) for t in tokenize(restored)] == [
        (t.kind, t.value) for t in tokenize(inputs[culture.SOURCE])
    ]


def test_frozen_offline_derivation_single_real_writer_and_exact_reader_boundaries(
    monkeypatch, tmp_path
):
    before = culture.derive({})
    monkeypatch.setattr(config, "GAME", tmp_path / "no-installation")
    assert culture.derive({}) == before
    loaded = decision_adapters.load()
    assert loaded.culture_opportunities_sha256
    policy = dict(loaded.policies)[culture.SOURCE]
    assert sum(r.id == culture.RULE for r in policy.rules) == 1
    reader = next(r for r in policy.readers if r.key == culture.READER)
    for malformed in (
        replace(reader, scope="target_country"),
        replace(reader, path=("owner",)),
        replace(reader, argument="root"),
    ):
        with pytest.raises(ValueError):
            decision_interfaces.reader_scope(malformed, actor_path=(), native_root="country")


def test_actual_compiler_consumer_ir_and_adapter_keep_exposure_and_independent_costs(generated):
    policy, inputs, _, _ = generated
    model = compiler.load_model()
    assert model.consumer_ir is not None
    lowered, _ = compiler.compile_policy(policy, culture.SOURCE, model)
    adapters = replace(
        decision_adapters.load(),
        policies=((culture.SOURCE, lowered),),
        initial_values=(),
        scalar_values=(),
        supply=None,
        event_programs=(),
        acceptance_programs=(),
    )
    files, report = decision_adapters.build(adapters, texts=inputs, consumer_ir=model.consumer_ir)
    assert report["culture_opportunities_sha256"]
    overlay = _overlay(files[culture.SOURCE], culture.FIELD)
    for kwargs, expected in (
        ({}, 6),
        ({"authority": 99}, -2),
        ({"authority": 99, "political": True}, -12),
    ):
        _, _, values, facts = _witness(generated, **kwargs)
        assert pdx_eval.select(overlay, facts).delta == expected
        assert decision_rules.evaluate(lowered, values, is_ai=True)[culture.FIELD][1] == expected
    assert len(lowered.consumer_programs) == 1
