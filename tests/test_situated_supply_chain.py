"""Canonical native supply stages and a two-opportunity replay with shared financing."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

import pytest

from pdx import config
from pdx import mobilization_opportunities as supply
from pdx.model import Block
from pdx.parser import parse_text
from pdx.situated import reference_strategy as ref
from pdx.situated.core_contracts import EntityKey, TimeIdentity

pytestmark = pytest.mark.unit
COUNTRY = EntityKey("country", "A")
FORMATION = EntityKey("military_formation", "a-1")
EXTRA: supply.SupplyOption = "extra_supplies"
LUXURY: supply.SupplyOption = "luxurious_supplies"
SOURCE = supply.SOURCE
BASELINE = "native-hold"
TIMELINE = "game-1"
CONTROL = "control-1"
EVALUATION = "evaluation-1"
RESOURCE = ref.Resource(COUNTRY, "weekly-supply-capacity", "money", "capacity")


def _offer(option: supply.SupplyOption = LUXURY) -> supply.SupplyOpportunity:
    return supply.SupplyOpportunity(
        COUNTRY, FORMATION, option, TimeIdentity(TIMELINE, 2), "ai", CONTROL, True
    )


def _observation() -> supply.SupplyObservation:
    return supply.SupplyObservation(
        COUNTRY,
        FORMATION,
        1,
        TimeIdentity(TIMELINE, 2),
        CONTROL,
        2,
        True,
        True,
        frozenset({"army_reserves", "military_statistics"}),
        frozenset({"groceries", "meat", "wine"}),
    )


def test_enablement_and_active_upkeep_are_distinct() -> None:
    state = replace(_observation(), extra_in_effect=False)
    assert supply.supply_eligibility(_offer(), state) == supply.SupplyEligibility(True, False)
    state = replace(state, extra_enabled=False)
    assert supply.supply_eligibility(_offer(), state) == supply.SupplyEligibility(False, False)
    assert supply.supply_eligibility(_offer(EXTRA), state) == supply.SupplyEligibility(True, False)


def test_later_stage_ignores_stale_late_and_other_formation_observations() -> None:
    offer = _offer()
    observation = _observation()
    neutral = supply.SupplyEligibility(None, None)
    assert supply.supply_eligibility(offer, None) == neutral
    assert (
        supply.supply_eligibility(
            offer, replace(observation, learned=TimeIdentity(TIMELINE, 3), valid_until=4)
        )
        == neutral
    )
    assert (
        supply.supply_eligibility(
            offer, replace(observation, learned=TimeIdentity(TIMELINE, 1), valid_until=1)
        )
        == neutral
    )
    assert (
        supply.supply_eligibility(
            offer, replace(observation, formation=EntityKey("military_formation", "a-2"))
        )
        == neutral
    )
    assert (
        supply.supply_eligibility(offer, replace(observation, actor=EntityKey("country", "B")))
        == neutral
    )
    assert supply.supply_eligibility(replace(offer, provided=False), observation) == neutral
    assert supply.supply_eligibility(replace(offer, control="player"), observation) == neutral


def test_later_stage_rejects_prior_timeline_observation_after_loading() -> None:
    observation = _observation()
    assert supply.supply_eligibility(_offer(), observation).eligible is True
    loaded_at_same_time = replace(_offer(), time=TimeIdentity("loaded-game", 2))
    assert supply.supply_eligibility(loaded_at_same_time, observation) == supply.SupplyEligibility(
        None, None
    )
    fresh = replace(observation, occurred_at=2, learned=loaded_at_same_time.time)
    assert supply.supply_eligibility(loaded_at_same_time, fresh).eligible is True


def test_ai_can_resume_only_with_observation_from_current_control_epoch() -> None:
    observation = replace(_observation(), valid_until=10)
    initial = _offer()
    assert supply.supply_eligibility(initial, observation).eligible is True
    player = replace(
        initial, control="player", control_epoch="control-2", time=TimeIdentity(TIMELINE, 3)
    )
    resumed = replace(
        player, control="ai", control_epoch="control-3", time=TimeIdentity(TIMELINE, 4)
    )
    assert supply.supply_eligibility(player, observation) == supply.SupplyEligibility(None, None)
    assert supply.supply_eligibility(resumed, observation) == supply.SupplyEligibility(None, None)
    fresh = replace(
        observation, occurred_at=4, learned=resumed.time, control_epoch=resumed.control_epoch
    )
    assert supply.supply_eligibility(resumed, fresh).eligible is True


def test_current_supply_and_technology_must_be_known() -> None:
    observation = _observation()
    assert supply.supply_eligibility(
        _offer(), replace(observation, potential_supply=frozenset({"meat"}))
    ) == supply.SupplyEligibility(False, True)
    assert supply.supply_eligibility(
        _offer(), replace(observation, technologies=frozenset({"army_reserves"}))
    ) == supply.SupplyEligibility(False, True)
    assert supply.supply_eligibility(
        _offer(), replace(observation, potential_supply=None)
    ) == supply.SupplyEligibility(None, True)


def test_formal_derivation_reports_both_stages_and_no_uncalibrated_contribution() -> None:
    derived = supply.derive({"sources": {}, "readers": {}, "rules": []})
    contract = derived["supply_chain"]
    assert contract == supply.supply_chain_contract()
    assert set(contract["stages"]) == {EXTRA, LUXURY}
    assert contract["projection"] == "native_rules_only_pending_calibration"
    assert len(derived["rules"]) == 72
    assert all("supply_chain" not in row["id"] for row in derived["rules"])


@pytest.mark.integration
def test_native_gate_and_withdrawal_are_preserved_as_separate_sections() -> None:
    contract = supply.supply_chain_contract(supply.verify_game(config.GAME))
    root = parse_text((config.GAME / SOURCE).read_text(encoding="utf-8-sig")).root
    luxury = supply._node(root, "mobilization_option_luxurious_supplies")
    assert contract["eligibility_operator"]["scope"] == "scope:military_formation"
    manual_gate = parse_text("""
        possible = {
            scope:military_formation = {
                has_mobilization_option = mobilization_option:mobilization_option_extra_supplies
            }
            market ?= {
                mg:meat ?= { has_potential_supply = yes }
                mg:wine ?= { has_potential_supply = yes }
            }
        }
    """).root
    assert isinstance(luxury.value, Block)
    assert supply._ast(supply._node(luxury.value, "possible")) == supply._ast(
        supply._node(manual_gate, "possible")
    )
    for slot in (EXTRA, LUXURY):
        assert contract["stages"][slot]["proof"]["on_deactivate_while_mobilized"]["line"] in (
            46,
            123,
        )
    assert supply.supply_withdrawal_morale_change(Fraction(4, 5), mobilized=True) == Fraction(-2, 5)
    assert supply.supply_withdrawal_morale_change(Fraction(4, 5), mobilized=False) == 0


def _endpoint(outcome: str, value: int, time: int) -> ref.Endpoint:
    return ref.Endpoint(
        ref.Attribution(
            COUNTRY, FORMATION, "own", outcome, "net-value", time, time + 1, BASELINE, outcome
        ),
        value,
        SOURCE,
    )


def _supply_problem(
    capacity: int, later_present: bool, *, later_learned: int = 2, tech_retained: bool = True
) -> ref.Problem:
    # Fixture values, in a common test unit. E consumes 3 and L another 2.
    # E alone is -2. L, when it is actually offered and affordable, adds 5.
    finish = ref.End(4)
    after_extra: ref.Node = finish
    technologies = frozenset({"military_statistics"}) if tech_retained else frozenset()
    later_state = replace(
        _observation(),
        learned=TimeIdentity(TIMELINE, later_learned),
        valid_until=3,
        technologies=technologies,
    )
    luxury_offer = replace(_offer(), provided=later_present)
    baseline_state = replace(later_state, extra_enabled=False, extra_in_effect=False)
    assert supply.supply_eligibility(luxury_offer, baseline_state).eligible is not True
    if supply.supply_eligibility(luxury_offer, later_state).eligible is True:
        luxury = ref.Transition(
            2,
            "luxury-paid",
            finish,
            ((RESOURCE, -2),),
            (_endpoint("luxury", 5, 2),),
            blocked=finish,
            blocked_event="luxury-budget-refused",
        )
        after_extra = ref.Choice(
            2,
            "luxury-review",
            (("keep-extra", finish), ("luxury", luxury)),
            actor=COUNTRY,
            control="ai",
        )
    extra = ref.Transition(
        0,
        "extra-paid",
        after_extra,
        ((RESOURCE, -3),),
        (_endpoint("extra", -2, 0),),
        blocked=finish,
        blocked_event="extra-budget-refused",
    )
    expected = ref.Choice(
        0,
        "extra-review",
        (("hold", finish), ("extra", extra)),
        actor=COUNTRY,
        control="ai",
    )
    world = ref.World("test-world", Fraction(1), expected, (ref.Balance(RESOURCE, capacity),))
    return ref.Problem(
        COUNTRY,
        "supply-replay",
        BASELINE,
        "net-value",
        (ref.Model("supply-model", (world,), SOURCE),),
        ref.Budget(),
    )


@pytest.mark.parametrize(
    ("capacity", "later_present", "direction"),
    [
        (5, True, "increase"),
        (4, True, "decrease"),
        (5, False, "decrease"),
    ],
)
def test_reference_reverses_extra_if_later_luxury_is_unavailable(
    capacity: int, later_present: bool, direction: str
) -> None:
    result = ref.compare(_supply_problem(capacity, later_present), "extra", "hold")
    assert result.direction == direction


@pytest.mark.parametrize(
    ("later_learned", "tech_retained", "expected"),
    [(2, True, 3), (3, True, -2), (2, False, -2)],
)
def test_reference_only_uses_known_current_eligibility(
    later_learned: int, tech_retained: bool, expected: int
) -> None:
    problem = _supply_problem(5, True, later_learned=later_learned, tech_retained=tech_retained)
    assert ref.compare(problem, "extra", "hold").bounds == ref.Interval(expected, expected)


@pytest.mark.integration
def test_native_compare_records_installed_define_identity() -> None:
    proof = supply.verify_supply_comparison(config.GAME)
    contract = supply.supply_chain_contract()["native_activation_comparison"]
    expected = {
        "MOBILIZATION_OPTION_RANDOM_FACTOR": "1/2",
        "MOBILIZATION_OPTION_MONEY_COST_FACTOR": "20",
        "MOBILIZATION_OPTION_NUM_ACTIVE_OPTIONS_DIVISOR": "1/4",
        "MOBILIZATION_OPTION_GOODS_SHORTAGE_MULT": "0",
        "MOBILIZATION_OPTIONS_MIN_EXTRA_EXPENSE_RATIO": "1/10",
        "MOBILIZATION_OPTIONS_MAX_EXTRA_EXPENSE_RATIO": "1",
        "MOBILIZATION_OPTIONS_EXPENSE_HYSTERESIS": "1/10",
    }
    assert contract["defines"] == expected
    assert set(proof) == set(expected)
    assert {item["line"] for item in proof.values()} == set(range(116, 123))
    assert contract["observation_identity"] == "recorded_evaluation_id_unique_within_timeline"
    assert set(contract["unverified"]) == {"native_order", "rank", "acceptance", "execution"}


def _compare(
    opportunity: supply.SupplyOpportunity, observed: supply.SupplyComparisonObservation
) -> supply.SupplyComparison | None:
    return supply.compare_supply_activation(opportunity, observed, evaluation_id=EVALUATION)


@pytest.mark.parametrize(
    ("count", "factor"), [(0, Fraction(1)), (1, Fraction(4, 5)), (4, Fraction(1, 2))]
)
def test_non_activated_comparison_applies_divisor_once(count: int, factor: Fraction) -> None:
    opportunity = _offer()
    observed = supply.SupplyComparisonObservation(
        opportunity, EVALUATION, False, count, False, Fraction(100), Fraction(5)
    )
    result = _compare(opportunity, observed)
    assert result == supply.SupplyComparison(
        (factor, factor), (100 * factor, 100 * factor), Fraction(100)
    )


def test_known_zero_shortage_and_unknown_do_not_collapse() -> None:
    opportunity = _offer()
    observed = supply.SupplyComparisonObservation(opportunity, EVALUATION, False, None, None)
    result = _compare(opportunity, observed)
    assert result == supply.SupplyComparison((Fraction(0), Fraction(1)), None, None)
    known_zero = replace(observed, weighted_utility=Fraction(0))
    assert _compare(opportunity, known_zero) == replace(
        result, adjusted_utility=(Fraction(0), Fraction(0))
    )
    known_shortage = replace(observed, input_shortage=True)
    assert _compare(opportunity, known_shortage) == replace(
        result, adjusted_utility=(Fraction(0), Fraction(0))
    )
    negative = replace(observed, weighted_utility=Fraction(-100), active_options=1)
    assert _compare(opportunity, negative) == supply.SupplyComparison(
        (Fraction(4, 5), Fraction(4, 5)), (Fraction(-80), Fraction(0)), None
    )


def test_activation_comparison_requires_inactive_same_call() -> None:
    opportunity = _offer()
    observed = supply.SupplyComparisonObservation(opportunity, EVALUATION, False, 0, False)
    assert _compare(opportunity, replace(observed, candidate_active=True)) is None
    assert _compare(opportunity, replace(observed, candidate_active=None)) is None
    assert _compare(_offer(EXTRA), observed) is None
    assert _compare(replace(opportunity, time=TimeIdentity(TIMELINE, 3)), observed) is None
    assert (
        _compare(replace(opportunity, formation=EntityKey("military_formation", "a-2")), observed)
        is None
    )
    player = replace(opportunity, control="player")
    assert _compare(player, replace(observed, opportunity=player)) is None


def test_distinct_same_time_evaluations_keep_separate_observations() -> None:
    opportunity = _offer()
    observation = supply.SupplyComparisonObservation(
        opportunity, EVALUATION, False, 1, False, Fraction(-100), Fraction(5)
    )
    same_time = replace(opportunity)
    assert (
        supply.compare_supply_activation(same_time, observation, evaluation_id="evaluation-2")
        is None
    )
    second_observation = replace(observation, evaluation_id="evaluation-2", active_options=0)
    assert _compare(same_time, second_observation) is None
    assert _compare(same_time, replace(observation, opportunity=same_time)) == (
        supply.SupplyComparison(
            (Fraction(4, 5), Fraction(4, 5)),
            (Fraction(-80), Fraction(-80)),
            Fraction(100),
        )
    )
