"""Named production employment slices: source -> IR -> real generated PDX."""

from dataclasses import replace

import pytest
import test_situated_local_foundations as foundations
from test_situated_local_foundations import (
    _facts,
    _overlay,
)
from test_situated_local_foundations import (
    _values as _foundation_values,
)

from pdx import decision_adapters, decision_rules
from pdx.situated import pdx_eval, programs

generated = foundations.generated

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def production():
    """Keep the exact employment/input/base variants; full consumers live elsewhere."""
    source = "common/buildings/01_industry.txt"
    adapters = decision_adapters.load()
    policy = dict(adapters.policies)[source]
    identities = {
        "active_building_food_industry_pm_bakery_input_grain",
        "active_building_food_industry_pm_bakery_output_groceries",
        "comparative_employment_active_building_food_industry_pm_bakery_output_groceries",
        "active_building_textile_mill_pm_handsewn_clothes_input_fabric",
        "active_building_textile_mill_pm_handsewn_clothes_output_clothes",
        "borrowing_foundation_building_textile_mill",
        "lj06_employment_textile_unemployment_support",
    }
    rules = tuple(rule for rule in policy.rules if rule.id in identities)
    assert {rule.id for rule in rules} == identities
    keys = {key for rule in rules for key in rule.input_keys()}
    selected = replace(
        policy, rules=rules, readers=tuple(r for r in policy.readers if r.key in keys)
    )
    return adapters, {source: programs.enable(selected, source=source)}


def _values(policy, target, pm):
    values = _foundation_values(policy, target, pm)
    if target == "food_industry":
        values.update(state_owner_loans=False, state_owner_reserves=1)
    return values


@pytest.mark.integration
@pytest.mark.parametrize(
    ("target", "pm"),
    [("food_industry", "pm_bakery"), ("textile_mill", "pm_handsewn_clothes")],
)
@pytest.mark.parametrize(
    ("case", "expected"),
    [("aux_unknown", 1.05), ("core_unknown", 1), ("aux_proven", 1.3)],
)
def test_named_production_employment_tiers(production, generated, target, pm, case, expected):
    if target == "food_industry" and case == "aux_unknown":
        expected = 1.2
    source = "common/buildings/01_industry.txt"
    policy = production[1][source]
    values = _values(policy, target, pm)
    values["state_unemployment"] = None if case == "aux_unknown" else 0.1
    if case == "core_unknown":
        values[f"pm_active_building_{target}_{pm}"] = None
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(
        f"building_{target}.ai_value"
    )
    observed = pdx_eval.select(
        _overlay(generated[1][source], f"building_{target}.ai_value"), _facts(policy, values)
    )
    assert (reference[1] if reference else 1) == pytest.approx(expected)
    assert (observed.delta if observed.operation == "multiply" else 1) == pytest.approx(expected)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("target", "pm", "cost", "output"),
    [
        ("food_industry", "pm_bakery", "grain", "groceries"),
        ("textile_mill", "pm_handsewn_clothes", "fabric", "clothes"),
    ],
)
@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("none", 1.05),
        ("nan", 1.05),
        ("inf", 1.05),
        ("invalid", 1.05),
        ("bool", 1.05),
        ("out_low", 1.05),
        ("out_high", 1.05),
        ("missing", 1.05),
        ("below", 1.05),
        ("edge", 1.3),
        ("above", 1.3),
        ("pm_unknown", 1),
        ("output_unknown", 1),
        ("default_unknown", 1),
        ("cost_unknown", 1),
        ("cost_balance_unknown", 1),
        ("loan_unknown", 1),
        ("input_shortage", 0.8),
        ("input_expensive", 1),
        ("player", 1),
        ("disabled", 1),
        ("missing_owner", 1),
        ("known_false_core_unknown", 1),
    ],
)
def test_handwritten_real_tier_boundaries(
    production, generated, target, pm, cost, output, case, expected
):
    if target == "food_industry" and case in {
        "none",
        "nan",
        "inf",
        "invalid",
        "bool",
        "out_low",
        "out_high",
        "missing",
        "below",
        "cost_balance_unknown",
    }:
        # Unknown unemployment skips this exact variant; the demand base remains.
        # Grain balance is intentionally absent from both canonical conditions.
        expected = 1.2
    source = "common/buildings/01_industry.txt"
    policy = production[1][source]
    values = _values(policy, target, pm)
    aux_values = {
        "none": None,
        "nan": float("nan"),
        "inf": float("inf"),
        "invalid": "invalid",
        "bool": True,
        "out_low": -0.1,
        "out_high": 1.1,
        "below": 0.099,
        "edge": 0.1,
        "above": 0.101,
    }
    values["state_unemployment"] = aux_values.get(case)
    if case == "missing":
        del values["state_unemployment"]
    for label, key in {
        "pm_unknown": f"pm_active_building_{target}_{pm}",
        "output_unknown": f"state_owner_{output}_balance",
        "default_unknown": "state_owner_default",
        "cost_unknown": f"state_owner_{cost}_price",
        "cost_balance_unknown": f"state_owner_{cost}_balance",
        "loan_unknown": "state_owner_loans",
    }.items():
        if case == label:
            values[key] = None
    if case == "input_shortage":
        values[f"state_owner_{cost}_price"] = 0.6
        values[f"state_owner_{cost}_balance"] = -1
        values["state_unemployment"] = 0.1
    if case == "input_expensive":
        values[f"state_owner_{cost}_price"] = 0.251
    if case == "known_false_core_unknown":
        values["state_unemployment"] = 0
        values[f"pm_active_building_{target}_{pm}"] = None
    enabled: frozenset[str] | None = frozenset() if case == "disabled" else None
    reference = decision_rules.evaluate(
        policy, values, is_ai=case not in {"player", "missing_owner"}, enabled_domains=enabled
    ).get(f"building_{target}.ai_value")
    facts = _facts(policy, values, ai=case != "player")
    if case == "missing_owner":
        del facts["ROOT"]["owner"]
    text = (
        _overlay(generated[1][source], f"building_{target}.ai_value") if case != "disabled" else ""
    )
    observed = pdx_eval.select(text, facts)
    assert (reference[1] if reference else 1) == pytest.approx(expected)
    assert (observed.delta if observed.operation == "multiply" else 1) == pytest.approx(expected)


def _tier_data():
    import hashlib
    import tomllib
    from pathlib import Path

    raw = tomllib.loads(Path("mod/decisions/adapters.toml").read_text(encoding="utf-8"))
    baseline = "building_food_industry = { ai_value = { value = 2 min = 0 max = 10 } }"
    core = {"fact": "state_owner_default", "op": "=", "value": False}
    high = {
        "id": "auxiliary_test_high",
        "domain": "economy",
        "field": "building_food_industry.ai_value",
        "priority": 2,
        "value": 1.3,
        "why": "test benefit",
        "counterexample": "core unknown",
        "conditions": [
            core,
            {"fact": "state_unemployment", "op": ">=", "value": {"fact": "state_owner_literacy"}},
        ],
        "auxiliary_facts": ["state_unemployment", "state_owner_literacy"],
    }
    low = {
        **high,
        "id": "auxiliary_test_low",
        "priority": 1,
        "value": 1.05,
        "conditions": [core],
        "auxiliary_facts": [],
    }
    return {
        "schema": 1,
        "baseline_sha256": hashlib.sha256(baseline.encode()).hexdigest(),
        "actor_path": ["owner"],
        "domains": {"economy": True},
        "readers": {
            key: raw["readers"][key]
            for key in ("state_owner_default", "state_unemployment", "state_owner_literacy")
        },
        "rules": [high, low],
    }, baseline


def _synthetic():
    data, baseline = _tier_data()
    policy = decision_rules.from_data(data, source_sha256="0" * 64)
    text = decision_rules.patch(
        baseline,
        policy,
        baseline=baseline,
        default_strategy=False,
        reader_evidence="owner in_default state_unemployment_rate literacy_rate",
    )
    return policy, text


@pytest.mark.parametrize(
    ("unemployment", "literacy", "default", "expected"),
    [
        (0.2, 0.1, False, 1.3),
        (0.1, 0.2, False, 1.05),
        (None, 0.1, False, 1.05),
        (0.2, None, False, 1.05),
        (None, None, False, 1.05),
        (None, 0.1, None, 1),
        (0.2, 0.1, None, 1),
        (None, None, True, 1),
    ],
)
def test_multi_auxiliary_reference_dependencies(unemployment, literacy, default, expected):
    policy, text = _synthetic()
    values = {
        "state_owner_default": default,
        "state_unemployment": unemployment,
        "state_owner_literacy": literacy,
    }
    result = decision_rules.evaluate(policy, values, is_ai=True).get(
        "building_food_industry.ai_value"
    )
    observed = pdx_eval.select(
        _overlay(text, "building_food_industry.ai_value"), _facts(policy, values)
    )
    assert (result[1] if result else 1) == pytest.approx(expected)
    assert (observed.delta if observed.operation == "multiply" else 1) == pytest.approx(expected)


@pytest.mark.parametrize(
    "case", ["unused", "all", "partial_reference", "context", "negative", "hard_default"]
)
def test_auxiliary_declaration_rejects_ambiguous_or_hard_inputs(case):
    data, _ = _tier_data()
    high = data["rules"][0]
    if case == "unused":
        high["auxiliary_facts"] = ["absent"]
    elif case == "all":
        high["auxiliary_facts"].append("state_owner_default")
    elif case == "partial_reference":
        high["auxiliary_facts"] = ["state_unemployment"]
    elif case == "context":
        data["contexts"] = {"hard_requirement": [high["conditions"].pop()]}
        high["contexts"] = ["hard_requirement"]
    elif case == "negative":
        high["value"] = 0.8
    elif case == "hard_default":
        high["auxiliary_facts"] = ["state_owner_default"]
    with pytest.raises(ValueError, match="辅助"):
        decision_rules.from_data(data, source_sha256="0" * 64)


def test_explicit_auxiliary_opt_ins_and_ir_drift_are_checked_per_source():
    from dataclasses import replace

    from pdx import decision_adapters
    from pdx.situated import compiler, decision_ir, ir

    model = compiler.load_model()
    policies = (
        ("mod/decisions/information.toml", decision_rules.load()),
        *decision_adapters.load().policies,
    )
    opted = [
        (source, policy, rule)
        for source, policy in policies
        for rule in policy.rules
        if rule.auxiliary_facts
    ]
    assert {rule.id: rule.auxiliary_facts for _, _, rule in opted} == {
        "lj06_employment_textile_unemployment_support": ("state_unemployment",),
        "d6_steelworking_tools_shortage_pressure": ("tools_price",),
        "d6_rifling_small_arms_shortage_pressure": ("small_arms_price",),
        "d6_gantry_cranes_steamers_shortage_pressure": ("steamers_price",),
        "s2_corporatism_movement_pressure_upgrade": ("insurrection",),
        "s2_international_exchange_standards_borrowing_pressure": ("debt_ratio",),
        "s2_mutual_funds_borrowing_pressure": ("debt_ratio",),
        "s2_next_elevator_observed_absorption": (
            "industrial_workforce",
            "bureaucracy",
            "net_surplus",
        ),
        "s2_next_steel_frame_buildings_observed_absorption": (
            "industrial_workforce",
            "bureaucracy",
            "net_surplus",
        ),
        "s2_urban_planning_observed_absorption": (
            "industrial_workforce",
            "bureaucracy",
            "net_surplus",
        ),
        "s2_urbanization_observed_absorption": (
            "industrial_workforce",
            "bureaucracy",
            "net_surplus",
        ),
        "wartime_army_administrative_capacity": ("bureaucracy",),
        "wartime_army_capacity": ("net_surplus", "bureaucracy"),
        "wartime_army_fiscal_capacity": ("net_surplus",),
        "wartime_navy_administrative_capacity": ("bureaucracy",),
        "wartime_navy_capacity": ("net_surplus", "bureaucracy"),
        "wartime_navy_fiscal_capacity": ("net_surplus",),
    }
    assert model.consumer_ir is not None
    for source, policy, rule in opted:
        assert ir.from_rule(rule, source="test").to_rule() == rule
        writer = next(w for w in model.consumer_ir.writers if w.definition == rule.id)
        assert writer.legacy is not None
        assert writer.legacy.auxiliary_facts == rule.auxiliary_facts
        changed = replace(
            model.consumer_ir,
            writers=tuple(
                replace(w, legacy=replace(writer.legacy, auxiliary_facts=())) if w is writer else w
                for w in model.consumer_ir.writers
            ),
        )
        with pytest.raises(ValueError, match="不一致"):
            decision_ir.lower_legacy(policy, changed, source=source)


def test_marked_fragment_retains_outer_proof_and_generic_unknown_remains_strict():
    policy, text = _synthetic()
    fragment = pdx_eval.marked_block(text, "auxiliary_test_high")
    values = {"state_owner_default": False, "state_unemployment": None, "state_owner_literacy": 0.1}
    assert pdx_eval.select(fragment, _facts(policy, values)).operation is None
    values["state_unemployment"] = 0.2
    assert pdx_eval.select(fragment, _facts(policy, values)).delta == 1.3
    assert "in_default" in fragment
    assert "state_unemployment_rate" in fragment
    generic = "# ACTION strict [test];\nif = { limit = { x >= 1 } multiply = 1.3 }\n# ACTION low [test];\nelse_if = { limit = { always = yes } multiply = 1.05 }"
    assert pdx_eval.select(generic, {"x": None}).fallback == "unknown"
    with pytest.raises(pdx_eval.UnsupportedPdxError, match="身份标记"):
        pdx_eval.select(
            "if = { limit = { always = yes } if = { limit = { always = yes } multiply = 1.3 } }", {}
        )


def test_known_false_auxiliary_excludes_high_candidate_before_unrelated_core_unknown():
    """A disproven high candidate cannot block a separately proven low tier."""
    import tomllib
    from pathlib import Path

    data, baseline = _tier_data()
    raw = tomllib.loads(Path("mod/decisions/adapters.toml").read_text(encoding="utf-8"))
    pm = "pm_active_building_food_industry_pm_bakery"
    data["readers"][pm] = raw["readers"][pm]
    data["rules"][0]["conditions"].append({"fact": pm, "op": "=", "value": True})
    policy = decision_rules.from_data(data, source_sha256="0" * 64)
    text = decision_rules.patch(
        baseline,
        policy,
        baseline=baseline,
        default_strategy=False,
        reader_evidence="owner in_default state_unemployment_rate literacy_rate is_production_method_active building_food_industry pm_bakery",
    )
    values = {
        "state_owner_default": False,
        "state_unemployment": 0.1,
        "state_owner_literacy": 0.2,
        pm: None,
    }
    result = decision_rules.evaluate(policy, values, is_ai=True)
    assert result["building_food_industry.ai_value"] == ("auxiliary_test_low", 1.05)
    observed = pdx_eval.select(
        _overlay(text, "building_food_industry.ai_value"), _facts(policy, values)
    )
    assert observed.action_id == "auxiliary_test_low"
    assert observed.delta == 1.05


def test_default_without_opt_in_still_blocks_on_auxiliary_shaped_unknown():
    data, baseline = _tier_data()
    data["rules"][0].pop("auxiliary_facts")
    policy = decision_rules.from_data(data, source_sha256="0" * 64)
    text = decision_rules.patch(
        baseline,
        policy,
        baseline=baseline,
        default_strategy=False,
        reader_evidence="owner in_default state_unemployment_rate literacy_rate",
    )
    values = {"state_owner_default": False, "state_unemployment": None, "state_owner_literacy": 0.1}
    assert decision_rules.evaluate(policy, values, is_ai=True) == {}
    observed = pdx_eval.select(
        _overlay(text, "building_food_industry.ai_value"), _facts(policy, values)
    )
    assert observed.fallback == "unknown"
    assert observed.operation is None


@pytest.mark.integration
@pytest.mark.parametrize(
    ("target", "pm", "cost"),
    [("food_industry", "pm_bakery", "grain"), ("textile_mill", "pm_handsewn_clothes", "fabric")],
)
@pytest.mark.parametrize("unknown", ["price", "balance", "loans"])
def test_review_p1_auxiliary_proven_cannot_bypass_unknown_cost_or_financing(
    production, generated, target, pm, cost, unknown
):
    """Six concrete reviewer counterexamples; aux is explicitly proven, not None."""
    source = "common/buildings/01_industry.txt"
    policy = production[1][source]
    values = _values(policy, target, pm)
    values["state_unemployment"] = 0.1
    key = "state_owner_loans" if unknown == "loans" else f"state_owner_{cost}_{unknown}"
    values[key] = None
    field = f"building_{target}.ai_value"
    result = decision_rules.evaluate(policy, values, is_ai=True).get(field)
    observed = pdx_eval.select(_overlay(generated[1][source], field), _facts(policy, values))
    # Both channels are evaluated before asserting so the first red records both.
    actual = (result[1] if result else 1, observed.delta if observed.operation == "multiply" else 1)
    expected = 1.3 if target == "food_industry" and unknown == "balance" else 1
    assert actual == pytest.approx((expected, expected)), (target, key, result, observed)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("target", "pm", "cost", "output"),
    [
        ("food_industry", "pm_bakery", "grain", "groceries"),
        ("textile_mill", "pm_handsewn_clothes", "fabric", "clothes"),
    ],
)
@pytest.mark.parametrize("auxiliary", [None, 0.1])
@pytest.mark.parametrize(
    "key_kind",
    [
        "input_price",
        "input_balance",
        "loans",
        "output_price",
        "infra",
        "pm",
        "default",
        "output_balance",
    ],
)
@pytest.mark.parametrize("invalid", [None, "invalid", float("nan")])
def test_review_p1_crosses_auxiliary_with_each_invalid_core(
    production, generated, target, pm, cost, output, auxiliary, key_kind, invalid
):
    source = "common/buildings/01_industry.txt"
    policy = production[1][source]
    values = _values(policy, target, pm)
    values["state_unemployment"] = auxiliary
    key = {
        "input_price": f"state_owner_{cost}_price",
        "input_balance": f"state_owner_{cost}_balance",
        "loans": "state_owner_loans",
        "output_price": f"state_owner_{output}_price",
        "infra": "state_infrastructure",
        "pm": f"pm_active_building_{target}_{pm}",
        "default": "state_owner_default",
        "output_balance": f"state_owner_{output}_balance",
    }[key_kind]
    values[key] = invalid
    field = f"building_{target}.ai_value"
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(field)
    expected = (
        (1.3 if auxiliary == 0.1 else 1.2)
        if target == "food_industry" and key_kind == "input_balance"
        else 1
    )
    assert (reference[1] if reference else 1) == expected
    if key_kind == "pm" and invalid is not None:
        # Parameterized observations retain the interpreter's existing strict
        # type contract; malformed observation data is rejected, not coerced.
        with pytest.raises(pdx_eval.UnsupportedPdxError, match="结果必须是布尔或未知"):
            pdx_eval.select(_overlay(generated[1][source], field), _facts(policy, values))
        return
    actual = pdx_eval.select(_overlay(generated[1][source], field), _facts(policy, values))
    assert (actual.delta if actual.operation == "multiply" else 1) == expected


@pytest.mark.integration
@pytest.mark.parametrize(
    ("target", "pm"),
    [("food_industry", "pm_bakery"), ("textile_mill", "pm_handsewn_clothes")],
)
@pytest.mark.parametrize(
    ("loans", "auxiliary", "expected"),
    [(True, 0.1, 1.3), (False, 0.1, 1.3), (True, None, 1.05), (False, None, 1.2)],
)
def test_known_financing_respects_each_production_employment_contract(
    production, generated, target, pm, loans, auxiliary, expected
):
    if target == "food_industry":
        expected = 1 if loans else (1.3 if auxiliary == 0.1 else 1.2)
    source = "common/buildings/01_industry.txt"
    policy = production[1][source]
    values = _values(policy, target, pm)
    values.update(state_owner_loans=loans, state_unemployment=auxiliary)
    field = f"building_{target}.ai_value"
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(field)
    actual = pdx_eval.select(_overlay(generated[1][source], field), _facts(policy, values))
    assert (reference[1] if reference else 1) == pytest.approx(expected)
    assert actual.delta == pytest.approx(expected)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("state_owner_reserves", 1, 1.3),
        ("state_owner_reserves", 0, 1.2),
        ("state_owner_reserves", -1, 1.2),
        ("state_owner_reserves", None, 1.2),
        ("state_owner_reserves", "invalid", 1.2),
        ("state_owner_reserves", float("nan"), 1.2),
        ("state_owner_loans", True, 1),
        ("state_owner_loans", None, 1),
        ("state_unemployment", 0.099, 1.2),
        ("state_unemployment", 0.1, 1.3),
        ("state_unemployment", None, 1.2),
        ("state_owner_grain_balance", -1, 1.3),
        ("state_owner_grain_balance", None, 1.3),
        ("state_owner_grain_price", 0.25, 1.3),
        ("state_owner_grain_price", 0.251, 1),
        ("state_owner_groceries_price", 0.25, 1),
    ],
)
def test_canonical_food_employment_gates_reach_generated_pdx(
    production, generated, key, value, expected
):
    source = "common/buildings/01_industry.txt"
    policy = production[1][source]
    values = _values(policy, "food_industry", "pm_bakery")
    values["state_unemployment"] = 0.1
    values[key] = value
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(
        "building_food_industry.ai_value"
    )
    actual = pdx_eval.select(
        _overlay(generated[1][source], "building_food_industry.ai_value"), _facts(policy, values)
    )
    assert (reference[1] if reference else 1) == pytest.approx(expected)
    assert (actual.delta if actual.operation == "multiply" else 1) == pytest.approx(expected)


def test_required_known_is_a_real_core_input_and_rejects_ir_drift():
    from dataclasses import replace

    from pdx import decision_adapters
    from pdx.situated import compiler, decision_ir, joint_chain_contract

    model = compiler.load_model()
    assert model.consumer_ir is not None
    source = "common/buildings/01_industry.txt"
    policy = dict(decision_adapters.load().policies)[source]
    for rule in policy.rules:
        if not rule.required_known_facts:
            continue
        assert rule.required_known_facts == ("state_owner_loans",)
        assert "state_owner_loans" in rule.input_keys()
        instance = next(item for item in model.action_instances if item.rule_id == rule.id)
        assert "state_owner_loans" in instance.condition_facts
        writer = next(item for item in model.consumer_ir.writers if item.definition == rule.id)
        assert writer.legacy is not None
        changed_writer = replace(writer, legacy=replace(writer.legacy, required_known_facts=()))
        changed = replace(
            model.consumer_ir,
            writers=tuple(
                changed_writer if item is writer else item for item in model.consumer_ir.writers
            ),
        )
        with pytest.raises(ValueError, match="不一致"):
            decision_ir.lower_legacy(policy, changed, source=source)
        with pytest.raises(ValueError, match="语义漂移"):
            joint_chain_contract.bind_bundle(
                changed,
                (
                    ("mod/decisions/information.toml", decision_rules.load()),
                    *decision_adapters.load().policies,
                ),
            )


@pytest.mark.parametrize(
    "declaration",
    [
        [],
        ["missing"],
        ["state_owner_default", "state_owner_default"],
        [1],
        "state_owner_default",
    ],
)
def test_required_known_declaration_rejects_invalid_reader_or_shape(declaration):
    data, _ = _tier_data()
    data["rules"][0]["required_known_facts"] = declaration
    with pytest.raises(ValueError, match="核心知识"):
        decision_rules.from_data(data, source_sha256="0" * 64)


@pytest.mark.parametrize("joint", [False, True])
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, 1.3),
        (0.5, 1.3),
        (1, 1.3),
        (None, 1),
        (-0.1, 1),
        (1.1, 1),
        (True, 1),
        ("0.5", 1),
        (float("nan"), 1),
        (float("inf"), 1),
    ],
)
def test_numeric_core_knowledge_checks_type_range_and_unknown_without_a_health_gate(
    joint, value, expected
):
    data, baseline = _tier_data()
    high = data["rules"][0]
    high["conditions"] = [{"fact": "state_owner_default", "op": "=", "value": False}]
    high["auxiliary_facts"] = []
    high["required_known_facts"] = ["state_unemployment"]
    data["rules"] = [high]
    del data["readers"]["state_owner_literacy"]
    policy = decision_rules.from_data(data, source_sha256="0" * 64)
    if joint:
        policy = programs.enable(policy, source="common/buildings/01_industry.txt")
    text = decision_rules.patch(
        baseline,
        policy,
        baseline=baseline,
        default_strategy=False,
        reader_evidence="owner in_default state_unemployment_rate",
    )
    values = {"state_owner_default": False, "state_unemployment": value}
    actual = decision_rules.evaluate(policy, values, is_ai=True).get(
        "building_food_industry.ai_value"
    )
    observed = pdx_eval.select(
        _overlay(text, "building_food_industry.ai_value"), _facts(policy, values)
    )
    assert (actual[1] if actual else 1) == pytest.approx(expected)
    assert (observed.delta if observed.operation == "multiply" else 1) == pytest.approx(expected)
