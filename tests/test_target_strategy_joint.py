"""Complete target and strategy consumers join concrete causes, preserving native choice."""

from __future__ import annotations

import re
from dataclasses import replace

import pytest
from test_institution_supply_joint import _values
from test_remaining_joint_consumers import _block, _native_number, _overlay, _render
from test_situated_joint_witnesses import _facts

from pdx import country_state, decision_adapters, decision_interfaces, decision_rules
from pdx.parser import parse_text
from pdx.situated import compiler, migration_baseline, pdx_eval

pytestmark = pytest.mark.integration
DEFAULT = "common/ai_strategies/00_default_strategy.txt"
ADMIN = "common/ai_strategies/01_admin_strategies.txt"
SUBJECTS = "common/ai_strategies/02_subject_diplomatic_strategies.txt"
OFFENSIVE = (
    "annex_country",
    "conquer_state",
    "make_subject",
    "reduce_autonomy",
    "transfer_subject",
    "colonization_rights",
    "regime_change",
)
SECRETS = ("antagonize", "conquer", "dominate")
LIBERTY = ("increase_autonomy", "independence", "liberate_subject")
ADMIN_FIELDS = tuple(
    f"ai_strategy_{name}_expansion.weight" for name in ("agricultural", "industrial", "resource")
)
MAINTAIN = "ai_strategy_subject_maintain_autonomy.weight"
COOPERATE = "ai_strategy_subject_overlord_compliance.weight"
SELF = "ai_strategy_subject_strengthen_self.weight"
FIELDS = {
    DEFAULT: tuple(f"ai_strategy_default.wargoal_scores.{name}" for name in (*OFFENSIVE, *LIBERTY))
    + tuple(f"ai_strategy_default.secret_goal_scores.{name}.score" for name in SECRETS),
    ADMIN: ADMIN_FIELDS,
    SUBJECTS: (MAINTAIN, COOPERATE, SELF),
}


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    model = compiler.load_model()
    policies = {
        source: compiler.compile_policy(policy, source, model)[0]
        for source, policy in adapters.policies
        if source in FIELDS
    }
    selected = replace(
        adapters,
        policies=tuple(policies.items()),
        supply=None,
        initial_values=tuple(row for row in adapters.initial_values if row.source in FIELDS),
        scalar_values=tuple(row for row in adapters.scalar_values if row[0] in FIELDS),
    )
    inputs = decision_adapters.read_inputs(selected)
    files, _ = decision_adapters.build(
        selected, texts=inputs, country_policy=country_state.load(), consumer_ir=model.consumer_ir
    )
    return policies, files, inputs, model


def _base(policy, changes):
    return _values(
        policy,
        {
            "prospective_subject_population": 100,
            "candidate_existing_subject": True,
            "own_army": 10,
            "target_army": 0,
            "navy": 10,
            "target_navy": 0,
            **changes,
        },
    )


CASES = [
    (
        DEFAULT,
        "ai_strategy_default.wargoal_scores.annex_country",
        {
            "default": True,
            "current_infamy": 50,
            "bureaucracy": -1,
            "target_truce": True,
            "target_alliance": True,
            "target_relations": 80,
            "target_army": 20,
            "war_defeat": True,
            "legitimacy": 20,
            "insurrection": True,
            "radical_share": 0.25,
        },
        -20,
    ),
    (
        DEFAULT,
        "ai_strategy_default.wargoal_scores.conquer_state",
        {"default": True, "bureaucracy": -1, "candidate_gdp": 1000000},
        -5,
    ),
    (
        DEFAULT,
        "ai_strategy_default.wargoal_scores.annex_country",
        {"loans": True, "debt_ratio": 0.4, "bankruptcy_horizon": 25.99},
        -4,
    ),
    (
        DEFAULT,
        "ai_strategy_default.wargoal_scores.annex_country",
        {"loans": True, "debt_ratio": 0.4, "bankruptcy_horizon": 26},
        0,
    ),
    (
        DEFAULT,
        "ai_strategy_default.wargoal_scores.annex_country",
        {"default": True, "loans": True, "debt_ratio": 0.8, "bankruptcy_horizon": 1},
        -3,
    ),
    (
        DEFAULT,
        "ai_strategy_default.wargoal_scores.annex_country",
        {"target_truce": True, "target_alliance": True, "target_relations": 80},
        -4,
    ),
    (
        DEFAULT,
        "ai_strategy_default.wargoal_scores.annex_country",
        {"target_truce": None, "target_alliance": True, "target_relations": 80},
        -4,
    ),
    (DEFAULT, "ai_strategy_default.wargoal_scores.annex_country", {"target_relations": 50}, -2),
    (
        DEFAULT,
        "ai_strategy_default.wargoal_scores.annex_country",
        {"default": True, "war": True, "target_army": 20},
        -6,
    ),
    (
        DEFAULT,
        "ai_strategy_default.wargoal_scores.annex_country",
        {"default": True, "bureaucracy": None, "target_army": None, "national_gdp": None},
        -3,
    ),
    (
        DEFAULT,
        "ai_strategy_default.wargoal_scores.annex_country",
        {"coord_layer_expansion": True, "route_maritime": True},
        0,
    ),
    (
        DEFAULT,
        "ai_strategy_default.wargoal_scores.reduce_autonomy",
        {"candidate_existing_subject": False, "bureaucracy": -1, "default": True},
        0,
    ),
    (
        DEFAULT,
        "ai_strategy_default.wargoal_scores.reduce_autonomy",
        {"candidate_existing_subject": True, "bureaucracy": -1, "default": True},
        -5,
    ),
    (
        DEFAULT,
        "ai_strategy_default.wargoal_scores.colonization_rights",
        {"target_navy": 20, "default": True, "target_truce": True},
        -10,
    ),
    (
        DEFAULT,
        "ai_strategy_default.wargoal_scores.regime_change",
        {"legitimacy": 24.99, "insurrection": True, "radical_share": 0.25},
        -2,
    ),
    (
        DEFAULT,
        "ai_strategy_default.wargoal_scores.regime_change",
        {"legitimacy": 25, "insurrection": True, "radical_share": 0.25},
        0,
    ),
    (
        DEFAULT,
        "ai_strategy_default.wargoal_scores.independence",
        {"actor_is_target_subject": True, "liberty": 75, "default": True, "war": True},
        1.10,
    ),
    (
        DEFAULT,
        "ai_strategy_default.wargoal_scores.independence",
        {"actor_is_target_subject": False, "liberty": 100},
        1,
    ),
    (
        DEFAULT,
        "ai_strategy_default.wargoal_scores.increase_autonomy",
        {"actor_is_target_subject": True, "liberty": 74.999},
        1,
    ),
    (
        DEFAULT,
        "ai_strategy_default.wargoal_scores.increase_autonomy",
        {"actor_is_target_subject": True, "liberty": 90},
        1.18,
    ),
    (
        DEFAULT,
        "ai_strategy_default.wargoal_scores.liberate_subject",
        {"target_is_subject": True, "target_liberty": 75, "liberty": 0},
        1.10,
    ),
    (
        DEFAULT,
        "ai_strategy_default.wargoal_scores.liberate_subject",
        {"target_is_subject": True, "target_liberty": 75, "target_relations": 50},
        1.18,
    ),
    (
        DEFAULT,
        "ai_strategy_default.wargoal_scores.liberate_subject",
        {"target_is_subject": True, "target_liberty": 0, "liberty": 100, "target_relations": 80},
        1,
    ),
    (
        DEFAULT,
        "ai_strategy_default.wargoal_scores.liberate_subject",
        {"target_is_subject": True, "target_liberty": 75, "target_relations": None},
        1.10,
    ),
    (ADMIN, ADMIN_FIELDS[0], {"grain_balance": -1, "default": True, "war": True}, 1.10),
    (ADMIN, ADMIN_FIELDS[0], {"grain_balance": -1, "grain_price": 0.25001}, 1.18),
    (ADMIN, ADMIN_FIELDS[1], {"tools_balance": -1, "tools_price": 0.25}, 1.10),
    (
        ADMIN,
        ADMIN_FIELDS[1],
        {"tools_balance": 0, "tools_price": 1, "industrial_workforce": 0.5},
        1,
    ),
    (ADMIN, ADMIN_FIELDS[2], {"iron_balance": -1, "iron_price": None}, 1.10),
    (ADMIN, ADMIN_FIELDS[2], {"iron_balance": None, "iron_price": 1, "war_defeat": True}, 1),
    (
        SUBJECTS,
        MAINTAIN,
        {"actor_is_subject": True, "liberty": 25, "default": True, "war": True},
        1.10,
    ),
    (SUBJECTS, MAINTAIN, {"actor_is_subject": True, "liberty": 49.999}, 1.10),
    (SUBJECTS, MAINTAIN, {"actor_is_subject": True, "liberty": 50}, 1),
    (SUBJECTS, MAINTAIN, {"actor_is_subject": False, "liberty": 30}, 1),
    (SUBJECTS, COOPERATE, {"actor_is_subject": True, "liberty": 25, "default": True}, 1.10),
    (
        SUBJECTS,
        COOPERATE,
        {"actor_is_subject": True, "liberty": 25, "actual_overlord_relations": 50},
        1.18,
    ),
    (
        SUBJECTS,
        COOPERATE,
        {"actor_is_subject": True, "liberty": 25, "actual_overlord_relations": None},
        1.10,
    ),
    (SUBJECTS, COOPERATE, {"actor_is_subject": True, "liberty": 25.0001, "default": True}, 1),
    (
        SUBJECTS,
        SELF,
        {"actor_is_subject": True, "liberty": 50, "bureaucracy": -1, "default": True},
        1.18,
    ),
    (SUBJECTS, SELF, {"actor_is_subject": True, "liberty": 75, "bureaucracy": -1}, 1.26),
    (SUBJECTS, SELF, {"actor_is_subject": True, "liberty": None, "bureaucracy": -1}, 1.08),
    (SUBJECTS, SELF, {"actor_is_subject": False, "liberty": 100, "bureaucracy": -1}, 1),
]
CASES.extend(
    (
        DEFAULT,
        f"ai_strategy_default.secret_goal_scores.{secret}.score",
        {
            "default": True,
            "target_truce": True,
            "target_alliance": True,
            "target_relations": 80,
            "war": True,
        },
        -7,
    )
    for secret in SECRETS
)


@pytest.mark.parametrize(("source", "field", "changes", "expected"), CASES)
def test_complete_actual_source_and_generated_pdx_follow_handwritten_causes(
    production, source, field, changes, expected
):
    policies, files, _native, _model = production
    policy = policies[source]
    values = _base(policy, changes)
    neutral = 1 if field.endswith(".weight") or field.split(".")[-1] in LIBERTY else 0
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(field)
    assert (neutral if reference is None else reference[1]) == pytest.approx(expected)
    decision = pdx_eval.select(_overlay(files[source], field), _facts(policy, values))
    assert (neutral if decision.operation is None else decision.delta) == pytest.approx(expected)


def test_every_target_field_has_only_explicit_causes_and_preserves_full_native_ast(production):
    policies, files, native, model = production
    for source, fields in FIELDS.items():
        stripped = re.sub(
            r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
            "\n",
            files[source],
            flags=re.DOTALL,
        )
        before, after = parse_text(native[source]).root, parse_text(stripped).root
        for field in fields:
            original, retained = before, after
            for part in field.split("."):
                original, retained = _block(original, part), _block(retained, part)
            assert _render(original) == _render(retained)
            writers = [rule for rule in policies[source].rules if ".".join(rule.field) == field]
            assert writers
            assert all(rule.id.startswith("target_strategy_") for rule in writers)
            assert all(
                rule.contribution_group and rule.intent is None and not rule.contexts
                for rule in writers
            )
    retired = migration_baseline.validated_retirements(model.consumer_ir)
    assert (DEFAULT, "coordinated_liquidity_wargoal_scores_annex_country") in retired
    assert (ADMIN, "ai_strategy_agricultural_expansion_weight") in retired
    assert (SUBJECTS, "ai_strategy_subject_maintain_autonomy_weight") in retired


def test_players_disabled_missing_and_wrong_candidates_never_supply_opportunity(production):
    policies, files, _native, _model = production
    for source, fields in FIELDS.items():
        policy = policies[source]
        values = _base(
            policy,
            {
                "actor_is_subject": True,
                "actor_is_target_subject": True,
                "target_is_subject": True,
                "target_liberty": 100,
                "liberty": 100,
            },
        )
        assert decision_rules.evaluate(policy, values, is_ai=False) == {}
        assert (
            decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
        )
        for field in fields:
            overlay = _overlay(files[source], field)
            assert pdx_eval.select(overlay, {}).operation is None
            assert pdx_eval.select(overlay, _facts(policy, values, is_ai=False)).operation is None
    policy = policies[DEFAULT]
    values = _base(policy, {"target_is_subject": False, "target_liberty": 0, "liberty": 100})
    facts = _facts(policy, values)
    facts["other_country"] = {"is_subject": True, "liberty_desire": 100}
    decision = pdx_eval.select(
        _overlay(files[DEFAULT], "ai_strategy_default.wargoal_scores.liberate_subject"), facts
    )
    assert decision.delta == 1


def test_cooperation_requires_actual_overlord_path_and_subject_identity(production):
    policies, files, _native, _model = production
    policy = policies[SUBJECTS]
    reader = next(r for r in policy.readers if r.key == "actual_overlord_relations")
    assert (
        reader.scope,
        reader.path,
        reader.engine,
        reader.unit,
        reader.minimum,
        reader.maximum,
    ) == (
        "root",
        ("overlord",),
        "relations:root",
        "relations_minus100_100",
        -100,
        100,
    )
    values = _base(
        policy, {"actor_is_subject": True, "liberty": 25, "actual_overlord_relations": 50}
    )
    facts = _facts(policy, values)
    overlay = _overlay(files[SUBJECTS], COOPERATE)
    assert pdx_eval.select(overlay, facts).delta == pytest.approx(1.18)
    # A named candidate, a flat actor relation, and a different foreign country
    # cannot impersonate ROOT.overlord, even when every decoy relation is high.
    facts["ROOT"]["overlord"] = {"relations:root": None}
    facts["ROOT"]["relations:root"] = 100
    facts["scope:overlord"] = {"relations:root": 100}
    facts["scope:target_country"] = {"relations:root": 100}
    assert pdx_eval.select(overlay, facts).delta == pytest.approx(1.10)
    facts["ROOT"]["overlord"] = {"relations:root": 100}
    facts["ROOT"]["is_subject"] = False
    assert pdx_eval.select(overlay, facts).delta == 1
    facts["ROOT"]["is_subject"] = True
    facts["ROOT"]["is_ai"] = False
    assert pdx_eval.select(overlay, facts).operation is None


def test_cooperation_reader_cannot_borrow_named_candidate_or_other_consumer():
    policy = dict(decision_adapters.load().policies)[SUBJECTS]
    reader = next(r for r in policy.readers if r.key == "actual_overlord_relations")
    rule = next(r for r in policy.rules if r.id == "target_strategy_subject_cooperation_relation")
    used = rule.input_keys()
    isolated = replace(
        policy, rules=(rule,), readers=tuple(r for r in policy.readers if r.key in used)
    )
    decision_interfaces.validate(isolated)
    wrong_scope = replace(reader, scope="overlord", path=())
    with pytest.raises(ValueError, match="具名作用域"):
        decision_interfaces.validate(
            replace(
                isolated,
                readers=tuple(wrong_scope if r.key == reader.key else r for r in isolated.readers),
            )
        )
    with pytest.raises(ValueError, match="实际宗主关系仅授权"):
        decision_interfaces.validate(
            replace(isolated, rules=(replace(rule, field=tuple(SELF.split("."))),))
        )


@pytest.mark.parametrize(("initial", "expected"), [(0, 0), (50, 45), (200, 100)])
def test_original_make_subject_clamps_still_execute_after_joint_costs(
    production, initial, expected
):
    policies, files, native, _model = production
    field = "ai_strategy_default.wargoal_scores.make_subject"
    country = _block(parse_text(native[DEFAULT]).root, "ai_strategy_default")
    original = _block(_block(country, "wargoal_scores"), "make_subject")
    clamps = [item for item in original.assignments() if item.key in {"min", "max"}]
    assert [_render(item) for item in clamps] == ["min = 0", "max = 100"]
    facts = _facts(
        policies[DEFAULT], _base(policies[DEFAULT], {"default": True, "bureaucracy": -1})
    )
    body = _overlay(files[DEFAULT], field) + " " + " ".join(_render(item) for item in clamps)
    assert _native_number(initial, body, facts) == expected


def test_independence_native_special_zero_cannot_be_revived_by_soft_multiplier(production):
    policies, files, native, _model = production
    field = "ai_strategy_default.wargoal_scores.independence"
    country = _block(parse_text(native[DEFAULT]).root, "ai_strategy_default")
    original = _block(_block(country, "wargoal_scores"), "independence")
    special = original.all("if")[:2]
    assert len(special) == 2
    assert all("multiply = 0.0" in _render(branch) for branch in special)
    facts = _facts(
        policies[DEFAULT],
        _base(policies[DEFAULT], {"actor_is_target_subject": True, "liberty": 100}),
    )
    # The exact country predicates remain in the full AST preservation test.
    # Once native evaluation has yielded zero, the actual 1.18 overlay preserves it.
    assert pdx_eval.select(_overlay(files[DEFAULT], field), facts).delta == pytest.approx(1.18)
    assert _native_number(0, _overlay(files[DEFAULT], field), facts) == 0


@pytest.mark.parametrize("learning", [True, False])
def test_original_secret_outer_trigger_is_retained_and_excludes_tutorial_target(
    production, learning
):
    policies, files, native, _model = production
    country = _block(parse_text(native[DEFAULT]).root, "ai_strategy_default")
    original = _block(_block(country, "secret_goal_scores"), "antagonize")
    trigger = _block(original, "trigger")
    generated_country = _block(parse_text(files[DEFAULT]).root, "ai_strategy_default")
    generated_goal = _block(_block(generated_country, "secret_goal_scores"), "antagonize")
    assert _render(_block(generated_goal, "trigger")) == _render(trigger)
    facts = _facts(
        policies[DEFAULT], _base(policies[DEFAULT], {"default": True, "target_truce": True})
    )
    facts["scope:target_country"]["is_subject_of"] = {(("argument", "root"),): False}
    facts["scope:target_country"]["is_still_learning"] = learning
    assert pdx_eval.condition(trigger, facts) is (not learning)
