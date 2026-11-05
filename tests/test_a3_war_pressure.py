"""Independent own-war support/count witnesses at one conquest consumer."""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from dataclasses import replace

import pytest
from test_remaining_joint_consumers import _block, _native_number, _overlay, _render

from pdx import (
    config,
    country_state,
    decision_adapters,
    decision_interfaces,
    decision_rules,
    observation_queries,
)
from pdx import war_pressure_opportunities as pressure
from pdx.lexer import tokenize
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval, programs
from pdx.textio import normalized_text

pytestmark = pytest.mark.integration

EXPRESSION = "any_scope_war = { count >= 2 has_war_support = { target = root value < 50 } }"


def _country(supports):
    return {
        "country_id": "SELF",
        "any_scope_war": [{"war_support": {"SELF": support, "ENEMY": 0}} for support in supports],
    }


@pytest.mark.parametrize(
    ("supports", "expected"),
    [
        ([], False),
        ([0], False),
        ([49.999, 49.999], True),
        ([-100, 49.999], True),
        ([49, 50], False),
        ([50, 50], False),
        ([49, 100, 49], True),
        ([49, None], None),
        ([None, None], None),
        ([100, None], False),
        ([49, None, 49], True),
        ([100, None, None], None),
    ],
)
def test_filtered_count_own_target_threshold_and_three_values(supports, expected):
    assert pdx_eval.condition(parse_text(EXPRESSION).root, _country(supports)) is expected


def test_missing_collection_and_explicit_root_never_read_foreign_or_flat_decoys():
    assert pdx_eval.condition(parse_text(EXPRESSION).root, {"country_id": "SELF"}) is None
    decoy = _country([0, 0])
    facts = {**decoy, "ROOT": {"country_id": "SELF"}, "scope:target_country": decoy}
    query = parse_text("ROOT = { " + EXPRESSION + " }").root
    assert pdx_eval.condition(query, facts) is None
    own = _country([100, 100])
    assert pdx_eval.condition(query, {**decoy, "ROOT": own}) is False


@pytest.mark.parametrize("collection", [True, 2, "wars", [None], [{}, True]])
def test_aggregate_bool_or_malformed_war_collection_is_error(collection):
    with pytest.raises(pdx_eval.UnsupportedPdxError):
        pdx_eval.condition(
            parse_text(EXPRESSION).root, {"country_id": "SELF", "any_scope_war": collection}
        )


@pytest.mark.parametrize("support", [True, "1", float("nan"), float("inf"), []])
def test_bad_own_support_is_error_not_zero_or_healthy(support):
    with pytest.raises(pdx_eval.UnsupportedPdxError, match="有限数值"):
        pdx_eval.condition(parse_text(EXPRESSION).root, _country([49, support]))


def test_wrong_country_support_absent_identity_and_each_unknown_count_bound():
    actor = _country([100, 100])
    # ENEMY is low in both wars, but that never makes own support low.
    assert pdx_eval.condition(parse_text(EXPRESSION).root, actor) is False
    for war in actor["any_scope_war"]:
        war["war_support"].pop("SELF")
    assert pdx_eval.condition(parse_text(EXPRESSION).root, actor) is None
    actor = _country([0, 0])
    actor.pop("country_id")
    assert pdx_eval.condition(parse_text(EXPRESSION).root, actor) is None
    actor = _country([0, 0])
    actor["country_id"] = "OTHER"
    assert pdx_eval.condition(parse_text(EXPRESSION).root, actor) is None
    actor = _country([0, 0])
    actor["country_id"] = ""
    with pytest.raises(pdx_eval.UnsupportedPdxError, match="身份"):
        pdx_eval.condition(parse_text(EXPRESSION).root, actor)


@pytest.mark.parametrize(
    "text",
    [
        EXPRESSION.replace("count >= 2", "count >= 1"),
        EXPRESSION.replace("count >= 2", "count = 2"),
        EXPRESSION.replace("target = root", "target = scope:target_country"),
        EXPRESSION.replace("value < 50", "value <= 50"),
        EXPRESSION.replace("value < 50", "value < 51"),
        EXPRESSION.replace("target = root", "target = root target = root"),
        EXPRESSION.replace("count >= 2", "count >= 2 count >= 2"),
        "scope:target_country = { " + EXPRESSION + " }",
    ],
)
def test_evaluator_never_opens_arbitrary_count_threshold_or_foreign_scope(text):
    with pytest.raises(pdx_eval.UnsupportedPdxError):
        pdx_eval.condition(
            parse_text(text).root,
            {"ROOT": _country([0, 0]), "scope:target_country": _country([0, 0])},
        )


def test_complete_native_freeze_query_contract_and_no_installation_dependency(
    monkeypatch, tmp_path
):
    frozen = pressure.frozen_inputs()
    assert frozen == {
        source: normalized_text((config.GAME / source).read_text(encoding="utf-8-sig"))
        for source in pressure.SOURCES
    }
    query = observation_queries.from_reader(
        "any_scope_war", {pressure.QUERY_PARAMETER: "two_own_wars_below_50"}
    )
    assert type(query) is pressure.OwnMultiwarLowSupportQuery
    compiled = observation_queries.compile_query(query, frozen)
    assert compiled.expression == EXPRESSION
    assert compiled.actor == "country"
    assert compiled.kind == "boolean"
    assert compiled.local_collections == ("own_wars",)
    assert compiled.world_scans == 0
    assert "possible_low<2=false" in compiled.unknown_policy
    assert set(dict(compiled.source_hashes)) == pressure.SOURCES
    assert set(observation_queries.required_sources(query)) == pressure.SOURCES
    assert compiled.references == (
        f"{pressure.IDEOLOGIES}:2764",
        f"{pressure.EFFECTS}:2762",
        f"{pressure.REGIONS}:35",
        f"{pressure.TRIGGER_DOC}:110",
        f"{pressure.SOURCE}:9558",
    )
    monkeypatch.setattr(config, "GAME", tmp_path / "absent")
    assert observation_queries.compile_query(query, frozen) == compiled


@pytest.mark.parametrize(
    ("engine", "parameters"),
    [
        ("AND", {pressure.QUERY_PARAMETER: "two_own_wars_below_50"}),
        ("any_scope_war", {pressure.QUERY_PARAMETER: "one_war"}),
        ("any_scope_war", {pressure.QUERY_PARAMETER: "two_own_wars_below_50", "threshold": "50"}),
        ("any_scope_war", {pressure.QUERY_PARAMETER: "two_own_wars_below_50", "target": "enemy"}),
    ],
)
def test_only_fixed_typed_own_query_can_be_requested(engine, parameters):
    with pytest.raises(ValueError, match="精确"):
        observation_queries.from_reader(engine, parameters)


@pytest.mark.parametrize("source", sorted(pressure.SOURCES))
def test_complete_native_source_drift_hard_fails(source):
    inputs = pressure.frozen_inputs()
    inputs[source] += "\n# drift\n"
    with pytest.raises(ValueError, match="完整原版来源漂移"):
        pressure.verify_inputs(inputs)


@pytest.mark.parametrize(
    ("source", "old", "new"),
    [
        (pressure.IDEOLOGIES, "target = root.owner", "target = attacker_warleader"),
        (pressure.EFFECTS, "target = root value > 80", "target = prev value > 80"),
        (
            pressure.REGIONS,
            "aro_is_acquire_states_target = yes",
            "aro_is_acquire_states_target = no",
        ),
        (pressure.TRIGGER_DOC, "count >= 5", "count = 5"),
        (pressure.SOURCE, "max = 100", "max = 200"),
    ],
)
def test_repinned_sources_still_require_exact_native_scope_count_and_full_candidate_ast(
    monkeypatch, source, old, new
):
    inputs = pressure.frozen_inputs()
    assert old in inputs[source]
    inputs[source] = inputs[source].replace(old, new)
    data = deepcopy(pressure.load())
    data["sources"][source] = hashlib.sha256(inputs[source].encode()).hexdigest()
    monkeypatch.setattr(pressure, "load", lambda: data)
    with pytest.raises(ValueError, match="漂移"):
        pressure.verify_inputs(inputs)


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    original = dict(adapters.policies)[pressure.SOURCE]
    ids = {
        pressure.RULE,
        "target_strategy_goal_conquer_state_reconstruction",
        "target_strategy_goal_conquer_state_default",
    }
    rules = tuple(rule for rule in original.rules if rule.id in ids)
    assert {rule.id for rule in rules} == ids
    used = {condition.fact for rule in rules for condition in rule.conditions}
    used.update(fact for rule in rules for fact in rule.conservative_unknown_facts)
    policy = replace(
        original,
        rules=rules,
        readers=tuple(reader for reader in original.readers if reader.key in used),
        enabled_domains=frozenset({"diplomacy"}),
        semantic_ir=(),
        consumer_programs=(),
    )
    policy = programs.enable(policy, source=pressure.SOURCE)
    decision_interfaces.validate(policy)
    inputs = decision_adapters.read_inputs(adapters)
    native = inputs[pressure.SOURCE]
    text = decision_rules.patch(
        native,
        policy,
        baseline=native,
        default_strategy=False,
        country_policy=country_state.load(),
        reader_words=decision_interfaces.proven_reader_words()
        | frozenset(re.findall(r"[A-Za-z_][A-Za-z_0-9:]*", "\n".join(inputs.values()))),
    )
    return adapters, policy, inputs, text, _overlay(text, pressure.FIELD)


def _witness(production, supports, *, defeat=False, default=False, population=1, ai=True):
    _, policy, _, _, overlay = production
    low = sum(value is not None and value < 50 for value in supports)
    unknown = sum(value is None for value in supports)
    exposure = True if low >= 2 else False if low + unknown < 2 else None
    values = {
        "prospective_subject_population": population,
        pressure.READER: exposure,
        "war_defeat": defeat,
        "default": default,
    }
    actor = _country(supports)
    actor.update(
        is_ai=ai,
        has_variable={(("argument", "recently_lost_war"),): defeat},
        in_default=default,
    )
    facts = {"ROOT": actor, "scope:target_country": {"total_population": population}}
    reference = decision_rules.evaluate(policy, values, is_ai=ai).get(pressure.FIELD)
    return _native_number(20, overlay, facts), reference[1] if reference else 0, facts


@pytest.mark.parametrize(
    ("supports", "kwargs", "expected"),
    [
        ([49, 49], {}, 17),
        ([49, 50], {}, 20),
        ([49, 100, 49], {}, 17),
        ([49, None], {}, 20),
        ([100, None], {}, 20),
        ([49, None, 49], {}, 17),
        ([49, 49], {"defeat": True}, 17),
        ([49, 50], {"defeat": True}, 18),
        ([49, None], {"defeat": True}, 18),
        ([49, 49], {"default": True}, 14),
        ([49, 49], {"default": True, "defeat": True}, 14),
        ([49, 49], {"population": None}, 20),
        ([49, 49], {"population": 0}, 20),
        ([49, 49], {"ai": False}, 20),
    ],
)
def test_hand_calculated_cost_same_war_cause_strongest_and_independent_financing(
    production, supports, kwargs, expected
):
    actual, delta, _ = _witness(production, supports, **kwargs)
    assert actual == expected
    assert 20 + delta == expected
    assert len(production[1].consumer_programs) == 1


def test_full_native_ordered_ast_zero_disable_and_own_collection_preservation(production):
    _, policy, inputs, text, overlay = production
    restored = re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        text,
        flags=re.DOTALL,
    )
    assert [(token.kind, token.value) for token in tokenize(restored)] == [
        (token.kind, token.value) for token in tokenize(inputs[pressure.SOURCE])
    ]
    _, _, facts = _witness(production, [49, 49])
    native = _block(
        _block(
            _block(parse_text(inputs[pressure.SOURCE]).root, "ai_strategy_default"),
            "wargoal_scores",
        ),
        "conquer_state",
    )
    zeroes = native.all("if")[1:3]
    assert len(zeroes) == 2
    clamps = "\n".join(_render(native.first(key)) for key in ("min", "max"))
    # Execute actual native zero/clamp statements after the overlay in their
    # original order. The additive overlay by itself is not a complete score.
    body = overlay + "\n" + "\n".join(_render(zero) for zero in zeroes) + "\n" + clamps
    facts["ROOT"]["ai_russia_gendarme_spares_china"] = False
    facts["ROOT"]["has_variable"][(("argument", "attack_bolivia"),)] = False
    assert _native_number(0, body, facts) == 0
    assert _native_number(1, body, facts) == 0
    assert _native_number(100, body, facts) == 97
    facts["ROOT"]["has_variable"][(("argument", "attack_bolivia"),)] = True
    facts["scope:target_country"].update(
        is_involved_in_journal_entry={(("argument", "je_peru_bolivia"),): True},
        has_variable={(("argument", "pbc_member"),): True},
    )
    assert _native_number(100, body, facts) == 0
    facts["ROOT"]["has_variable"][(("argument", "attack_bolivia"),)] = False
    facts["ROOT"]["ai_russia_gendarme_spares_china"] = True
    assert _native_number(100, body, facts) == 0
    candidate = text[text.index("\t\tconquer_state = {") : text.index("\t\treturn_state = {")]
    assert candidate.index("# SITAI END information:") < candidate.rindex(
        "has_variable = attack_bolivia"
    )
    assert candidate.index("# SITAI END information:") < candidate.index(
        "ai_russia_gendarme_spares_china = yes"
    )
    assert decision_rules.evaluate(policy, {}, is_ai=True, enabled_domains=frozenset()) == {}
    assert (
        decision_rules.patch(
            inputs[pressure.SOURCE],
            policy,
            baseline=inputs[pressure.SOURCE],
            default_strategy=False,
            enabled_domains=frozenset(),
        )
        == inputs[pressure.SOURCE]
    )
    facts["ROOT"].pop("any_scope_war")
    facts["scope:target_country"].update(_country([0, 0]))
    assert _native_number(20, overlay, facts) == 20


def test_actual_shared_compiler_consumer_ir_adapter_and_reader_boundary(production):
    adapters, policy, inputs, _, _ = production
    model = compiler.load_model()
    assert model.consumer_ir is not None
    lowered, _ = compiler.compile_policy(policy, pressure.SOURCE, model)
    selected = replace(
        adapters,
        policies=((pressure.SOURCE, lowered),),
        initial_values=(),
        scalar_values=(),
        supply=None,
        event_programs=(),
        acceptance_programs=(),
    )
    files, metadata = decision_adapters.build(
        selected,
        texts=inputs,
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
    )
    assert metadata["war_pressure_opportunities_sha256"]
    assert pressure.RULE in _overlay(files[pressure.SOURCE], pressure.FIELD)
    reader = next(reader for reader in policy.readers if reader.key == pressure.READER)
    for malformed in (
        replace(reader, scope="target_country"),
        replace(reader, path=("owner",)),
        replace(reader, argument="root"),
    ):
        with pytest.raises(ValueError):
            decision_interfaces.reader_scope(malformed, actor_path=(), native_root="country")
    rule = next(rule for rule in policy.rules if rule.id == pressure.RULE)
    for malformed in (
        replace(rule, field=("ai_strategy_default", "wargoal_scores", "make_subject")),
        replace(rule, operation="multiply"),
        replace(rule, value=-4),
        replace(rule, value=1),
        replace(rule, semantic_role="benefit"),
    ):
        with pytest.raises(ValueError, match="多线低支持"):
            decision_interfaces.validate(replace(policy, rules=(malformed,)))
