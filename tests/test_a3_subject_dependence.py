"""Actual directed economic ties join one existing subject strategy program."""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from dataclasses import replace

import pytest
from test_remaining_joint_consumers import _native_number, _overlay

from pdx import (
    config,
    country_state,
    decision_adapters,
    decision_interfaces,
    decision_rules,
    observation_queries,
)
from pdx import subject_dependence_opportunities as dependence
from pdx.lexer import tokenize
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval, programs
from pdx.textio import normalized_text

pytestmark = pytest.mark.integration


def _query():
    return parse_text(dependence.render_query(dependence.ActualOverlordDependenceQuery())).root


def _country(*, index=2, subject=True, overlord="ACTUAL", observations=None):
    return {
        "is_ai": True,
        "is_subject": subject,
        "overlord": {"country_id": overlord} if overlord else None,
        "economic_dependence": {"ACTUAL": index} if observations is None else observations,
    }


def test_current_complete_native_sources_prove_direction_unit_identity_and_original_qualification():
    frozen = dependence.frozen_inputs()
    assert frozen == {
        source: normalized_text((config.GAME / source).read_text(encoding="utf-8-sig"))
        for source in dependence.SOURCES
    }
    refs = dependence.verify_inputs(frozen)
    assert f"{dependence.DEFINES}:1337" in refs
    assert f"{dependence.GRANT}:70" in refs
    assert f"{dependence.GRANT}:91" in refs
    query = observation_queries.from_reader(
        "AND", {dependence.QUERY_PARAMETER: "actual_overlord_above_neutral"}
    )
    assert isinstance(query, dependence.ActualOverlordDependenceQuery)
    compiled = observation_queries.compile_query(query, frozen)
    assert compiled.expression == dependence.render_query(query)
    assert compiled.actor == "country"
    assert compiled.kind == "boolean"
    assert compiled.local_collections == ()
    assert compiled.world_scans == 0
    assert "unknown" in compiled.unknown_policy
    assert set(dict(compiled.source_hashes)) == dependence.SOURCES
    assert set(observation_queries.required_sources(query)) == dependence.SOURCES


@pytest.mark.parametrize(
    ("engine", "parameters"),
    [
        ("OR", {dependence.QUERY_PARAMETER: "actual_overlord_above_neutral"}),
        ("AND", {dependence.QUERY_PARAMETER: "prospective_overlord"}),
        (
            "AND",
            {
                dependence.QUERY_PARAMETER: "actual_overlord_above_neutral",
                "target": "scope:overlord",
            },
        ),
        (
            "AND",
            {dependence.QUERY_PARAMETER: "actual_overlord_above_neutral", "threshold": "0"},
        ),
    ],
)
def test_no_free_threshold_country_target_or_prospective_alias(engine, parameters):
    with pytest.raises(ValueError, match="精确"):
        observation_queries.from_reader(engine, parameters)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, True),
        ({"index": 1.00001}, True),
        ({"index": 1}, False),
        ({"index": 0}, False),
        ({"index": 5}, True),
        ({"index": None}, None),
        ({"subject": False}, False),
        ({"subject": None}, None),
        ({"overlord": None}, False),
        ({"overlord": "WRONG"}, None),
        ({"observations": {"CANDIDATE": 5}}, None),
        ({"observations": {"ACTUAL": 0.5, "CANDIDATE": 5}}, False),
    ],
)
def test_exact_actual_direct_overlord_index_boundary_unknown_and_wrong_entity(changes, expected):
    actor = _country(**changes)
    actor["scope:overlord"] = {"country_id": "CANDIDATE", "economic_dependence": {"SELF": 5}}
    actor["top_overlord"] = {"country_id": "TOP", "economic_dependence": {"SELF": 5}}
    # Neither foreign values nor a fabricated already-aggregated getter can win.
    actor["ROOT.economic_dependence(overlord)"] = 5
    assert pdx_eval.condition(_query(), actor) is expected


@pytest.mark.parametrize("value", [-0.01, 5.01, float("inf"), True, "2"])
def test_malformed_index_is_error_not_healthy_or_unknown(value):
    with pytest.raises(pdx_eval.UnsupportedPdxError, match="0到5"):
        pdx_eval.condition(_query(), _country(index=value))


@pytest.mark.parametrize("source", sorted(dependence.SOURCES))
def test_complete_native_source_drift_hard_fails(source):
    inputs = dependence.frozen_inputs()
    inputs[source] += "\n# drift\n"
    with pytest.raises(ValueError, match="完整原版来源漂移"):
        dependence.verify_inputs(inputs)


@pytest.mark.parametrize(
    ("source", "old", "new"),
    [
        (dependence.DEFINES, "ECONOMIC_DEPENDENCE_MAX = 5", "ECONOMIC_DEPENDENCE_MAX = 1"),
        (
            dependence.GRANT,
            '"scope:target_country.economic_dependence(root)" > 1',
            '"root.economic_dependence(scope:target_country)" > 1',
        ),
        (dependence.SOURCE, "liberty_desire <= 50", "liberty_desire <= 100"),
        (
            dependence.INDIA,
            '"ROOT.economic_dependence(top_overlord)" > 2.5',
            '"ROOT.economic_dependence(scope:overlord)" > 2.5',
        ),
    ],
)
def test_semantic_ast_rejects_repinned_direction_unit_qualification_drift(
    monkeypatch, source, old, new
):
    inputs = dependence.frozen_inputs()
    assert old in inputs[source]
    inputs[source] = inputs[source].replace(old, new)
    data = deepcopy(dependence.load())
    data["sources"][source] = hashlib.sha256(inputs[source].encode()).hexdigest()
    monkeypatch.setattr(dependence, "load", lambda: data)
    with pytest.raises(ValueError, match="漂移"):
        dependence.verify_inputs(inputs)


@pytest.fixture(scope="module")
def generated():
    adapters = decision_adapters.load()
    original = dict(adapters.policies)[dependence.SOURCE]
    rules = tuple(rule for rule in original.rules if ".".join(rule.field) == dependence.FIELD)
    assert dependence.RULE in {rule.id for rule in rules}
    used = {p.fact for rule in rules for p in rule.conditions}
    policy = replace(
        original,
        rules=rules,
        readers=tuple(reader for reader in original.readers if reader.key in used),
        semantic_ir=(),
        consumer_programs=(),
    )
    policy = programs.enable(policy, source=dependence.SOURCE)
    decision_interfaces.validate(policy)
    inputs = decision_adapters.read_inputs(adapters)
    native = inputs[dependence.SOURCE]
    text = decision_rules.patch(
        native,
        policy,
        baseline=native,
        default_strategy=False,
        country_policy=country_state.load(),
        reader_words=decision_interfaces.proven_reader_words()
        | frozenset(re.findall(r"[A-Za-z_][A-Za-z_0-9:]*", "\n".join(inputs.values()))),
    )
    return policy, inputs, text, _overlay(text, dependence.FIELD)


def _witness(generated, *, index=2, subject=True, liberty=40, relations=0, ai=True):
    policy, _, _, overlay = generated
    exposure = None if index is None or subject is None else bool(subject and index > 1)
    values = dict.fromkeys(reader.key for reader in policy.readers)
    values.update(
        actor_is_subject=subject,
        liberty=liberty,
        actual_overlord_relations=relations,
        **{dependence.READER: exposure},
    )
    actor = _country(index=index, subject=subject)
    actor.update(liberty_desire=liberty, is_ai=ai)
    actor["overlord"]["relations:root"] = relations
    facts = {"ROOT": actor}
    result = decision_rules.evaluate(policy, values, is_ai=ai).get(dependence.FIELD)
    return _native_number(1, overlay, facts), result[1] if result else 1, values, facts


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, 1.08),
        ({"index": 1}, 1),
        ({"index": 0}, 1),
        ({"index": None}, 1),
        ({"liberty": 25}, 1.18),
        ({"liberty": 25, "relations": 50}, 1.26),
        ({"liberty": 25, "relations": None}, 1.18),
        ({"liberty": None, "relations": 50}, 1.08),
        ({"liberty": 25, "relations": 50, "index": None}, 1.18),
        ({"subject": False, "liberty": 25, "relations": 50}, 1),
        ({"subject": None, "liberty": 25, "relations": 50}, 1),
        ({"ai": False, "liberty": 25, "relations": 50}, 1),
    ],
)
def test_hand_calculated_continuity_and_liberty_relation_causes_join_once(
    generated, kwargs, expected
):
    actual, reference, _, _ = _witness(generated, **kwargs)
    assert actual == pytest.approx(expected)
    assert reference == pytest.approx(expected)
    assert len(generated[0].consumer_programs) == 1


def test_actual_not_candidate_wrong_country_reverse_or_top_overlord(generated):
    _, _, _, facts = _witness(generated)
    overlay = generated[3]
    facts["ROOT"]["economic_dependence"] = {"ACTUAL": 0.5, "CANDIDATE": 5, "WRONG": 5, "TOP": 5}
    facts["scope:overlord"] = {"country_id": "CANDIDATE"}
    facts["scope:target_country"] = {"country_id": "WRONG"}
    facts["ROOT"]["top_overlord"] = {"country_id": "TOP"}
    facts["ROOT"]["overlord"]["economic_dependence"] = {"SELF": 5}
    assert _native_number(1, overlay, facts) == 1
    facts["ROOT"]["economic_dependence"].pop("ACTUAL")
    assert _native_number(1, overlay, facts) == 1
    facts["ROOT"]["economic_dependence"]["ACTUAL"] = 2
    assert _native_number(1, overlay, facts) == pytest.approx(1.08)
    # A genuinely changed current overlord rebinds the next read without memory.
    facts["ROOT"]["overlord"]["country_id"] = "NEW"
    assert _native_number(1, overlay, facts) == 1


def test_native_low_liberty_weight_and_zero_keep_their_values(generated):
    overlay = generated[3]
    for liberty, native, expected in ((25, 50, 59), (40, 20, 21.6), (50, 0, 0)):
        _, _, _, facts = _witness(generated, liberty=liberty)
        assert _native_number(native, overlay, facts) == pytest.approx(expected)


def test_normal_low_financing_player_disable_and_full_native_ast_preservation(generated):
    policy, inputs, text, overlay = generated
    actual, reference, values, facts = _witness(generated)
    facts["ROOT"].update(in_default=False, is_borrowing=True, debt_ratio=0.1, bankruptcy_horizon=52)
    assert actual == reference == pytest.approx(1.08)
    assert _native_number(1, overlay, facts) == pytest.approx(1.08)
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    assert (
        decision_rules.patch(
            inputs[dependence.SOURCE],
            policy,
            baseline=inputs[dependence.SOURCE],
            default_strategy=False,
            enabled_domains=frozenset(),
        )
        == inputs[dependence.SOURCE]
    )
    restored = re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        text,
        flags=re.DOTALL,
    )
    assert [(token.kind, token.value) for token in tokenize(restored)] == [
        (token.kind, token.value) for token in tokenize(inputs[dependence.SOURCE])
    ]
    assert _native_number(0, overlay, facts) == 0


def test_actual_compiler_ir_adapter_bridge_and_narrow_reader_authority(
    generated, monkeypatch, tmp_path
):
    policy, inputs, _, _ = generated
    model = compiler.load_model()
    assert model.consumer_ir is not None
    lowered, _ = compiler.compile_policy(policy, dependence.SOURCE, model)
    adapters = replace(
        decision_adapters.load(),
        policies=((dependence.SOURCE, lowered),),
        initial_values=(),
        scalar_values=(),
        supply=None,
        event_programs=(),
        acceptance_programs=(),
    )
    files, report = decision_adapters.build(adapters, texts=inputs, consumer_ir=model.consumer_ir)
    assert report["subject_dependence_opportunities_sha256"]
    assert dependence.RULE in _overlay(files[dependence.SOURCE], dependence.FIELD)
    before = dependence.derive({"readers": {"actor_is_subject": {"engine": "is_subject"}}})
    monkeypatch.setattr(config, "GAME", tmp_path / "absent")
    assert dependence.derive({"readers": {"actor_is_subject": {"engine": "is_subject"}}}) == before
    reader = next(reader for reader in policy.readers if reader.key == dependence.READER)
    for malformed in (
        replace(reader, scope="overlord"),
        replace(reader, path=("overlord",)),
        replace(reader, argument="root"),
    ):
        with pytest.raises(ValueError):
            decision_interfaces.reader_scope(malformed, actor_path=(), native_root="country")
    rule = next(rule for rule in policy.rules if rule.id == dependence.RULE)
    with pytest.raises(ValueError, match="实际宗主经济依赖"):
        decision_interfaces.validate(
            replace(
                policy,
                rules=(replace(rule, field=("ai_strategy_subject_strengthen_self", "weight")),),
            )
        )
