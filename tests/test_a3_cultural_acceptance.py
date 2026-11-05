"""Actual cultural identity, exact legal dominance and the production writer."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import replace

import pytest
from test_remaining_joint_consumers import _overlay
from test_situated_joint_witnesses import _facts

from pdx import (
    country_state,
    decision_adapters,
    decision_interfaces,
    decision_rules,
    observation_queries,
)
from pdx import culture_opportunities as culture
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval, programs

pytestmark = pytest.mark.integration


def _actor(*, primary=("russian",), cultures=("polish",), acceptance=None):
    return {
        "primary_cultures": primary,
        "any_scope_state": [
            {
                "any_scope_culture": cultures,
                "culture_pop_acceptance": {"polish": 79} if acceptance is None else acceptance,
            }
        ],
    }


@pytest.mark.parametrize(
    ("actor", "expected"),
    [
        (_actor(), True),
        (_actor(acceptance={"polish": 80}), False),
        (_actor(acceptance={"polish": 79.999}), True),
        (_actor(primary=("polish",)), False),
        (_actor(cultures=("russian",)), False),
        (_actor(acceptance={"polish": None}), None),
        (_actor(primary=None), None),
        (_actor(cultures=()), False),
        ({"any_scope_state": []}, False),
        ({}, None),
        (
            {
                "primary_cultures": ["russian"],
                "any_scope_state": [
                    {"any_scope_culture": ["polish"], "culture_pop_acceptance": {"finnish": 20}},
                    {"any_scope_culture": ["finnish"], "culture_pop_acceptance": {"polish": 20}},
                ],
            },
            None,
        ),
    ],
)
def test_same_owned_state_same_nonprimary_culture_three_valued_observation(actor, expected):
    query = culture.CulturalExposureQuery()
    compiled = observation_queries.compile_query(query, culture.frozen_inputs())
    assert compiled.local_collections == ("owned_states", "state_cultures")
    assert compiled.world_scans == 0
    facts = {**actor, "scope:target_country": _actor(), "owner": _actor()}
    assert pdx_eval.condition(parse_text(compiled.expression).root, facts) is expected


@pytest.mark.parametrize(
    ("source", "old", "new"),
    [
        (
            culture.CITIZENSHIP,
            "country_acceptance_shared_heritage_trait_add = 60",
            "country_acceptance_shared_heritage_trait_add = 10",
        ),
        (culture.HOMELAND, "culture = prev", "culture = ROOT"),
        (culture.HOMELAND, "is_primary_culture_of = ROOT", "is_primary_culture_of = PREV"),
        (culture.VALUES, "acceptance_status_5 = 80", "acceptance_status_5 = 79"),
    ],
)
def test_resigning_native_hash_cannot_hide_identity_or_legal_effect_drift(
    monkeypatch, source, old, new
):
    inputs = culture.frozen_inputs()
    assert old in inputs[source]
    inputs[source] = inputs[source].replace(old, new)
    data = culture.load()
    data["sources"][source] = hashlib.sha256(inputs[source].encode()).hexdigest()
    monkeypatch.setattr(culture, "load", lambda: data)
    with pytest.raises(ValueError, match="漂移"):
        culture.verify_inputs(inputs)


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    original = dict(adapters.policies)[culture.CITIZENSHIP]
    rules = tuple(r for r in original.rules if r.field == tuple(culture.CULTURAL_FIELD.split(".")))
    used = {c.fact for r in rules for c in r.conditions}
    policy = replace(
        original,
        rules=rules,
        enabled_domains=frozenset(r.domain for r in rules),
        readers=tuple(r for r in original.readers if r.key in used),
        semantic_ir=(),
        consumer_programs=(),
    )
    policy = programs.enable(policy, source=culture.CITIZENSHIP)
    decision_interfaces.validate(policy)
    inputs = decision_adapters.read_inputs(adapters)
    model = compiler.load_model()
    lowered, _ = compiler.compile_policy(policy, culture.CITIZENSHIP, model)
    focused = replace(
        adapters,
        policies=((culture.CITIZENSHIP, lowered),),
        initial_values=(),
        scalar_values=(),
        supply=None,
        event_programs=(),
        acceptance_programs=(),
    )
    files, _ = decision_adapters.build(focused, texts=inputs, consumer_ir=model.consumer_ir)
    return lowered, files, inputs, _overlay(files[culture.CITIZENSHIP], culture.CULTURAL_FIELD)


@pytest.mark.parametrize(
    ("exposure", "current", "authority", "ai", "expected"),
    [
        (True, culture.CULTURAL_ORIGIN, 200, True, 6),
        (True, culture.CULTURAL_ORIGIN, 199, True, -2),
        (None, culture.CULTURAL_ORIGIN, 199, True, -8),
        (False, culture.CULTURAL_ORIGIN, 199, True, -8),
        (False, culture.CULTURAL_ORIGIN, 200, True, 0),
        (None, culture.CULTURAL_ORIGIN, 200, True, 0),
        (True, culture.CULTURAL_CANDIDATE, 200, True, 0),
        (True, "law_cultural_exclusion", 200, True, 0),
        (True, culture.CULTURAL_ORIGIN, 200, False, 0),
    ],
)
def test_actual_model_ir_adapter_writer_matches_independent_hand_result(
    production, exposure, current, authority, ai, expected
):
    policy, _, _, overlay = production
    values = {
        r.key: False if r.kind == "boolean" else max(r.minimum or 0, 0) for r in policy.readers
    }
    for key in values:
        if key.startswith(("culture_current_", "law_context_current_")):
            values[key] = key.endswith(current)
    values.update(
        {
            culture.CULTURAL_READER: exposure,
            "authority": authority,
            "legitimacy": 60,
            "radical_share": 0,
            "insurrection": False,
        }
    )
    facts = _facts(policy, values, is_ai=ai)
    facts["ROOT"].update(
        _actor(acceptance={"polish": None if exposure is None else 79 if exposure else 80})
    )
    facts["ROOT"]["any_political_movement"] = []
    actual = pdx_eval.select(overlay, facts).delta
    result = decision_rules.evaluate(policy, values, is_ai=ai).get(culture.CULTURAL_FIELD)
    assert actual == (result[1] if result else 0) == expected
    assert len(policy.consumer_programs) == 1


def test_disable_restores_native_and_parent_protection(production):
    policy, files, inputs, _ = production
    assert (
        decision_rules.patch(
            inputs[culture.CITIZENSHIP],
            policy,
            baseline=inputs[culture.CITIZENSHIP],
            default_strategy=False,
            enabled_domains=frozenset(),
            country_policy=country_state.load(),
        )
        == inputs[culture.CITIZENSHIP]
    )
    before = parse_text(inputs[culture.CITIZENSHIP]).root
    after = parse_text(files[culture.CITIZENSHIP]).root

    def protected(root):
        root = copy.deepcopy(root)
        candidate = root.first(culture.CULTURAL_CANDIDATE).value
        candidate.items = [
            item
            for item in candidate.items
            if getattr(item, "key", "") != "ai_enact_weight_modifier"
        ]
        return culture._shape(root)

    assert protected(before) == protected(after)
