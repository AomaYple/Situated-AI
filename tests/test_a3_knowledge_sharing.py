"""Exact knowledge donor ROOT cost, actual PDX and independent native-tail proof."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import tomllib
from dataclasses import replace
from typing import Any

import pytest

from pdx import config, decision_adapters, decision_interfaces, decision_rules
from pdx import native_action_opportunities as actions
from pdx.model import Assignment, Block
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval, programs

SOURCE = "common/diplomatic_actions/40_subjects_knowledge_sharing.txt"
FIELD = ("da_knowledge_sharing", "ai", "propose_score")
SPREAD = "knowledge_donor_spread"
POPULATION = "knowledge_donor_population"
ENGINE = "modifier:country_tech_spread_mult"


@pytest.fixture(scope="module")
def production():
    if not (config.GAME / SOURCE).is_file():
        pytest.skip("需要锁定原版完整外交行动源")
    adapters = decision_adapters.load()
    original = dict(adapters.policies)[SOURCE]
    assert original.native_root == "country"
    assert original.actor_path == ()
    rules = tuple(rule for rule in original.rules if rule.field == FIELD)
    assert len(rules) == 2
    assert all(rule.semantic_role == "cost" for rule in rules)
    keys = {key for rule in rules for key in rule.input_keys()}
    policy = programs.enable(
        replace(
            original,
            rules=rules,
            readers=tuple(reader for reader in original.readers if reader.key in keys),
            semantic_ir=(),
            consumer_programs=(),
            enabled_domains=frozenset({"diplomacy"}),
        ),
        source=SOURCE,
    )
    selected = replace(
        adapters,
        policies=((SOURCE, policy),),
        supply=None,
        event_programs=(),
        acceptance_programs=(),
    )
    inputs = decision_adapters.read_inputs(adapters)
    generated, _ = decision_adapters.build(selected, texts=inputs)
    return policy, generated[SOURCE], selected, inputs


@pytest.mark.parametrize(
    ("spread", "population", "expected", "hand_score"),
    [
        (0.20, 100, 1.0, 5),
        (0.10, 100, 1.0, 5),
        (0.099999, 100, 0.95, 4.75),
        (0, 100, 0.95, 4.75),
        (-0.000001, 100, 0.85, 4.25),
        (-0.20, 100, 0.85, 4.25),
        (-0.25, 100, 0.85, 4.25),
        (None, 100, 0.85, 4.25),
        (None, None, 1.0, 5),
        (-0.20, None, 0.85, 4.25),
        (0.20, None, 1.0, 5),
    ],
)
def test_independent_hand_multipliers_match_real_pdx_and_shared_ir(
    production, spread, population, expected, hand_score
):
    policy, generated, _, _ = production
    values = {SPREAD: spread, POPULATION: population}
    result = decision_rules.evaluate_ir(policy, values, is_ai=True)
    assert result.get(".".join(FIELD), ("native", 1))[1] == pytest.approx(expected)
    branch = pdx_eval.marked_block(generated, policy.consumer_programs[0].action_id)
    facts = {
        "ROOT": {
            "is_ai": True,
            ENGINE: spread,
            "total_population": population,
            "influence": -100,
            "in_default": True,
        }
    }
    actual = pdx_eval.select(branch, facts)
    assert actual.delta == pytest.approx(expected)
    # Native rank contribution4 gives1+4=5; rank contribution1 gives1+1=2.
    # These bases are independent inputs, not recomputed by the new policy.
    assert 5 * actual.delta == pytest.approx(hand_score)
    assert 2 * actual.delta == pytest.approx(2 * expected)
    assert 0 * actual.delta == 0


def test_exact_native_eligibility_is_independent_of_spread_margin(production):
    policy, generated, _, _ = production
    branch = pdx_eval.marked_block(generated, policy.consumer_programs[0].action_id)
    assert "influence" not in branch
    assert "will_propose" not in branch
    assert "scope:target" not in branch
    assert "owner" not in branch
    assert {reader.key for reader in policy.readers} == {SPREAD, POPULATION}
    # Both worlds remain eligible under the unchanged native >-0.25 condition;
    # only independently observed donor margin differs, no influence penalty.
    for spread, expected in ((0.20, 1), (-0.20, 0.85)):
        assert spread > -0.25
        for influence in (-100, 0, 100):
            facts = {
                "ROOT": {
                    "is_ai": True,
                    ENGINE: spread,
                    "total_population": 100,
                    "influence": influence,
                }
            }
            assert pdx_eval.select(branch, facts).delta == pytest.approx(expected)


def _shape(node):
    if isinstance(node, Assignment):
        return node.key, node.op, node.prefix, _shape(node.value)
    if isinstance(node, Block):
        return tuple(_shape(child) for child in node.items)
    return str(node)


def test_full_ordered_native_ast_pact_eligibility_target_rank_and_request_preserved(production):
    _, generated, _, inputs = production
    native = inputs[SOURCE]
    restored = re.sub(
        r"\t\t# SITAI BEGIN information:da_knowledge_sharing\.ai\.propose_score\n.*?"
        r"\t\t# SITAI END information:da_knowledge_sharing\.ai\.propose_score\n",
        "",
        generated,
        flags=re.DOTALL,
    )
    assert _shape(parse_text(restored).root) == _shape(parse_text(native).root)
    assert generated.count("# SITAI BEGIN") == 1
    action = actions._block(parse_text(native).root, FIELD[0])
    pact = actions._block(action, "pact")
    for key, value in (
        ("cost", "50"),
        ("maintenance_paid_by", "first_country"),
        ("forced_duration", "12"),
    ):
        actions._scalar(pact, key, value)
    actions._scalar(actions._block(pact, "first_modifier"), "country_tech_spread_mult", "-0.10")
    actions._scalar(actions._block(pact, "second_modifier"), "country_tech_spread_mult", "0.25")
    ai = actions._block(action, "ai")
    actions._scalar(actions._block(ai, "will_propose"), ENGINE, "-0.25", ">")
    score = actions._block(ai, "propose_score")
    actions._scalar(score, "value", "1")
    actions._scalar(actions._block(score, "add"), "value", "scope:target_country.country_rank")
    assert "reverse_pact = da_knowledge_sharing" in restored


def test_player_disabled_unknown_identity_and_foreign_owner_decoys(production):
    policy, generated, adapters, inputs = production
    values = {SPREAD: -0.20, POPULATION: 100}
    assert decision_rules.evaluate_ir(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate_ir(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    branch = pdx_eval.marked_block(generated, policy.consumer_programs[0].action_id)
    assert (
        pdx_eval.select(
            branch, {"ROOT": {"is_ai": False, ENGINE: -0.20, "total_population": 100}}
        ).operation
        is None
    )
    decoy = {ENGINE: -0.20, "total_population": 100, "is_ai": True}
    facts = {
        "ROOT": {"is_ai": True, ENGINE: 0.20, "owner": decoy},
        "scope:target_country": decoy,
        "scope:target": decoy,
    }
    assert pdx_eval.select(branch, facts).delta == 1
    facts["ROOT"] = {"is_ai": True, "owner": decoy}
    assert pdx_eval.select(branch, facts).delta == 1
    output, _ = decision_adapters.build(adapters, texts=inputs, enabled_domains=frozenset())
    assert output == {}
    with pytest.raises(ValueError, match="漂移"):
        decision_adapters.build(adapters, texts={**inputs, SOURCE: inputs[SOURCE] + "\n"})


@pytest.mark.parametrize(
    "damage", ["path", "scope", "unit", "minimum", "maximum", "argument", "engine"]
)
def test_exact_reader_rejects_foreign_or_invented_modifier_signatures(production, damage):
    policy, _, _, _ = production
    reader = next(reader for reader in policy.readers if reader.key == SPREAD)
    changes: dict[str, dict[str, Any]] = {
        "path": {"path": ("owner",)},
        "scope": {"scope": "target_country"},
        "unit": {"unit": "ratio"},
        "minimum": {"minimum": -1},
        "maximum": {"maximum": 1},
        "argument": {"argument": "country_tech_spread_mult"},
        "engine": {"engine": "modifier:country_tech_research_speed_mult"},
    }
    with pytest.raises(ValueError):
        decision_interfaces.reader_scope(
            replace(reader, **changes[damage]), (), native_root="country"
        )
    with pytest.raises(ValueError):
        decision_interfaces.reader_scope(reader, ("owner",), native_root="state")


def test_new_consumer_catalog_context_and_old_objects_are_isolated():
    raw = tomllib.loads(decision_adapters.SOURCE.read_text(encoding="utf-8"))
    derived = actions.derive(raw)
    catalog = actions.consumer_catalog()
    assert FIELD[0] in catalog
    row = catalog[FIELD[0]]
    assert row["field"] == ".".join(FIELD)
    assert row["native_root"] == "country"
    assert row["actor_path"] == []
    context = compiler._frozen_native_action_contexts()[(SOURCE, ".".join(FIELD))]
    assert context.actor_scope is not None
    assert context.actor_scope.name == "root"
    assert not context.targets
    broken = copy.deepcopy(raw)
    broken["readers"][SPREAD] = {**actions.KNOWLEDGE_READERS[SPREAD], "path": ["owner"]}
    with pytest.raises(ValueError, match="身份漂移"):
        actions.derive(broken)
    assert not any(
        rule["field"] != ".".join(FIELD) and SPREAD in {c["fact"] for c in rule["conditions"]}
        for rule in derived["rules"]
    )


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf")])
def test_invalid_spread_never_becomes_a_healthy_waiver(production, bad):
    policy, _, _, _ = production
    reader = next(reader for reader in policy.readers if reader.key == SPREAD)
    assert not reader.accepts(bad)
    result = decision_rules.evaluate_ir(policy, {SPREAD: bad, POPULATION: 100}, is_ai=True)
    assert result[".".join(FIELD)][1] == pytest.approx(0.85)


@pytest.mark.parametrize(
    "field",
    [
        ("da_knowledge_sharing", "ai", "accept_score"),
        ("da_request_knowledge_sharing", "ai", "propose_score"),
        ("join_power_bloc", "ai", "propose_score"),
    ],
)
def test_exact_getter_does_not_authorize_other_consumers(production, field):
    policy, _, _, _ = production
    altered = replace(policy, rules=tuple(replace(rule, field=field) for rule in policy.rules))
    with pytest.raises(ValueError, match="只授权精确"):
        decision_interfaces.validate(altered)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("maintenance_paid_by = first_country", "maintenance_paid_by = second_country"),
        ("country_tech_spread_mult = -0.10", "country_tech_spread_mult = 0.10"),
        ("country_tech_spread_mult = 0.25", "country_tech_spread_mult = 0.10"),
        ("modifier:country_tech_spread_mult > -0.25", "modifier:country_tech_spread_mult > -0.50"),
        ("forced_duration = 12", "forced_duration = 1"),
        ("value = scope:target_country.country_rank", "value = country_rank"),
    ],
)
def test_resigning_a_source_cannot_hide_role_cost_or_native_score_drift(
    tmp_path, monkeypatch, old, new
):
    baseline = copy.deepcopy(actions.load_baseline())
    inputs = baseline["texts"]
    actions.verify_inputs(inputs)
    assert old in inputs[SOURCE]
    inputs[SOURCE] = inputs[SOURCE].replace(old, new, 1)
    parameters = copy.deepcopy(actions.load())
    parameters["sources"][SOURCE] = hashlib.sha256(inputs[SOURCE].encode()).hexdigest()
    # Re-sign a coherent complete-source fixture, including its parent AST. This
    # gets past the snapshot/schema guards and tests the named semantic atom.
    baseline["sources"] = copy.deepcopy(parameters["sources"])
    baseline["raw_sources"][SOURCE] = parameters["sources"][SOURCE]
    parsed = parse_text(inputs[SOURCE])
    assert not parsed.errors
    baseline["contracts"][f"{SOURCE}#da_knowledge_sharing"] = actions._shape(
        actions._block(parsed.root, "da_knowledge_sharing")
    )
    frozen = tmp_path / "resigned-complete-source.json"
    frozen.write_text(json.dumps(baseline), encoding="utf-8", newline="\n")
    monkeypatch.setattr(actions, "load", lambda: parameters)
    monkeypatch.setattr(actions, "FROZEN", frozen)
    monkeypatch.setattr(actions, "FROZEN_SHA256", hashlib.sha256(frozen.read_bytes()).hexdigest())
    assert actions._snapshot() == baseline
    with pytest.raises(ValueError, match=re.escape(f"效果或资格漂移：{old.split()[0]}")):
        actions.verify_inputs(inputs)
