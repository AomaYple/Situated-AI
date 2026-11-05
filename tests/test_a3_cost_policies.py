"""Semantic policy families isolate identity from bounded unknown pressure."""

import copy
import hashlib
import tomllib
from pathlib import Path
from typing import Any, cast

import pytest

from pdx import decision_rules
from pdx.situated import cost_policies, pdx_eval, programs

pytestmark = pytest.mark.unit


def _data(group="target_financing", *, source="common/ai_strategies/00_default_strategy.txt"):
    return {
        "readers": {
            "default": {
                "engine": "in_default",
                "scope": "root",
                "unit": "boolean",
                "kind": "boolean",
            },
            "prospective_subject_population": {
                "engine": "total_population",
                "scope": "target_country",
                "unit": "persons",
                "kind": "number",
                "minimum": 0,
            },
        },
        "rules": [
            {
                "id": "fixture",
                "source": source,
                "contribution_group": group,
                "value": -3,
                "operation": "add",
                "conditions": [
                    {"fact": "prospective_subject_population", "op": ">", "value": 0},
                    {"fact": "default", "op": "=", "value": True},
                ],
            }
        ],
    }


def test_declared_cost_keeps_existing_candidate_identity_and_does_not_mutate_source():
    raw = _data()
    frozen = copy.deepcopy(raw)
    result = cost_policies.apply(raw, source="adapters")
    rule = result["rules"][0]
    assert raw == frozen
    assert rule["semantic_role"] == "cost"
    assert rule["conservative_unknown_facts"] == ["default"]
    assert "required_known_facts" not in rule
    assert result["readers"] == raw["readers"]
    assert rule["conditions"] == raw["rules"][0]["conditions"]
    assert rule["value"] == -3
    assert cost_policies.apply(result, source="adapters") == result


@pytest.mark.parametrize(
    ("population", "candidate", "default", "expected"),
    [
        (100, 200, None, -3),
        (100, 200, True, -3),
        (100, 200, False, 0),
        (None, 200, None, -3),
        (None, 200, True, -3),
        (100, None, None, 0),
        (100, 0, None, 0),
    ],
)
def test_policy_produces_handwritten_reference_and_actual_pdx(
    population, candidate, default, expected
):
    raw = cost_policies.apply(_data(), source="adapters")
    rule = raw["rules"][0]
    readers = tuple(
        decision_rules.Reader(key=key, **value) for key, value in raw["readers"].items()
    )
    typed = decision_rules.Rule(
        "fixture",
        "test",
        ("field",),
        1,
        rule["value"],
        tuple(decision_rules.Predicate(**item) for item in rule["conditions"]),
        "fixture",
        "fixture",
        operation="add",
        contribution_group=rule["contribution_group"],
        required_known_facts=tuple(rule.get("required_known_facts", [])),
        semantic_role=rule["semantic_role"],
        conservative_unknown_facts=tuple(rule["conservative_unknown_facts"]),
        unknown_cost_basis=rule["unknown_cost_basis"],
    )
    policy = programs.enable(
        decision_rules.RuleSet(
            readers, (typed,), hashlib.sha256(b"").hexdigest(), "0" * 64, frozenset({"test"})
        ),
        source="fixture",
    )
    values = {
        "population": population,
        "prospective_subject_population": candidate,
        "default": default,
    }
    assert (
        decision_rules.evaluate_ir(policy, values, is_ai=True).get("field", ("", 0))[1] == expected
    )
    text = programs.render(
        policy.consumer_programs[0],
        guards={"fixture": "always = yes"},
        ai_guard="is_ai = yes",
        descriptions={},
        producer_markers={},
        cost_guards={"fixture": ("prospective_subject_population > 0", "default = no")},
    )
    assert pdx_eval.select(text, {**values, "is_ai": True}).delta == expected


def test_no_inputs_do_not_create_cost_and_negative_number_does_not_declare_cost():
    raw = _data(group="unclassified_negative")
    assert cost_policies.apply(raw, source="adapters") == raw
    row = cost_policies.audit(raw, source="adapters")[0]
    assert row.family == "unclassified"
    assert row.mode == "unchanged"


def test_same_cause_group_observed_saving_is_explicit_benefit_exception():
    raw = _data(group="bureaucracy_institution_cost")
    raw["rules"][0]["id"] = "bureaucracy_reform_elected_institution_saving_police_deficit"
    row = cost_policies.audit(raw, source="adapters")[0]
    assert row.mode == "benefit"
    assert cost_policies.apply(raw, source="adapters") == raw


def test_active_recipe_is_core_but_unanchored_building_uses_actual_owner_unknown_anchor():
    raw = _data(group="building_active_input_steel", source="common/buildings/01_industry.txt")
    raw["rules"][0]["conditions"] = [
        {"fact": "pm_active_fixture", "op": "=", "value": True},
        {"fact": "state_owner_steel_price", "op": ">", "value": 0.5},
    ]
    row = cost_policies.audit(raw, source="adapters")[0]
    assert row.mode == "conservative"
    assert row.core == ("pm_active_fixture",)
    assert row.pressure == ("state_owner_steel_price",)
    raw["rules"][0]["contribution_group"] = "building_financing_pressure"
    raw["rules"][0]["conditions"] = [{"fact": "state_owner_default", "op": "=", "value": True}]
    row = cost_policies.audit(raw, source="adapters")[0]
    assert row.mode == "conservative_anchor"
    assert row.unknown_anchor == ("cost_owner_population",)


def test_shock_relationship_and_withdrawal_are_not_unknown_costs():
    for group, expected in (
        ("target_reconstruction_opportunity", "known_only"),
        ("target_relationship_commitment", "known_only"),
        ("institution_schools_invested_priority_withdrawal", "withdrawal"),
    ):
        raw = _data(group)
        assert cost_policies.audit(raw, source="adapters")[0].mode == expected
        assert cost_policies.apply(raw, source="adapters") == raw


def test_war_context_alone_is_not_entity_identity_and_shared_hard_pressure_is_not_relaxed():
    raw = _data()
    raw["rules"][0]["conditions"][0] = {"fact": "war", "op": "=", "value": False}
    row = cost_policies.audit(raw, source="adapters")[0]
    assert row.mode == "conservative_anchor"
    assert row.unknown_anchor == ("cost_country_population",)
    raw = _data()
    raw["rules"][0]["contexts"] = ["hard_default"]
    raw["contexts"] = {"hard_default": [{"fact": "default", "op": "=", "value": True}]}
    assert cost_policies.audit(raw, source="adapters")[0].mode == "known_only"


def test_conflicting_prior_policy_is_rejected():
    raw = _data()
    raw["rules"][0].update(
        semantic_role="cost", conservative_unknown_facts=["prospective_subject_population"]
    )
    with pytest.raises(ValueError, match="已有声明冲突"):
        cost_policies.apply(raw, source="adapters")


def test_production_information_known_conditions_and_reader_catalog_are_preserved():
    source = Path(__file__).resolve().parents[1] / "mod/decisions/information.toml"
    raw = tomllib.loads(source.read_text(encoding="utf-8"))
    changed = cost_policies.apply(raw, source="information")
    assert {key: changed["readers"][key] for key in raw["readers"]} == raw["readers"]
    declarations = {
        "semantic_role",
        "conservative_unknown_facts",
        "unknown_cost_basis",
        "unknown_cost_required_known_facts",
    }
    for before, after in zip(raw["rules"], changed["rules"], strict=True):
        assert {k: v for k, v in before.items() if k not in declarations} == {
            k: v for k, v in after.items() if k not in declarations
        }
    policy = decision_rules.from_data(
        changed, source_sha256="0" * 64, strategy=decision_rules.decision_intents.load()
    )
    assert sum(bool(rule.conservative_unknown_facts) for rule in policy.rules) >= 4


def test_final_derived_adapter_policy_is_accepted_by_real_parser(monkeypatch):
    from pdx import decision_adapters

    merge = decision_adapters._merge_derivation
    collected: list[cost_policies.CostAudit] = []

    def applying(data, derived, label):
        merge(data, derived, label)
        if label == "同州真实迁移目标与就业吸纳":
            collected.extend(cost_policies.audit(data, source="adapters"))
            changed = cost_policies.apply(data, source="adapters")
            for before, after in zip(data["rules"], changed["rules"], strict=True):
                assert before["conditions"] == after["conditions"]
                assert before.get("required_known_facts", []) == after.get(
                    "required_known_facts", []
                )
            data.clear()
            data.update(changed)

    monkeypatch.setattr(decision_adapters, "_merge_derivation", applying)
    policies = decision_adapters.load().policies
    conservative = [
        rule for _, policy in policies for rule in policy.rules if rule.conservative_unknown_facts
    ]
    assert collected
    assert len(conservative) > 400
    for row in collected:
        if row.mode == "conservative":
            assert row.core
            assert row.pressure
            assert not set(row.core) & set(row.pressure)
    for source, policy in policies:
        common = programs.enable(policy, source=source)
        assert decision_rules.evaluate_ir(common, {}, is_ai=True) == {}


@pytest.mark.parametrize(
    ("pressure", "population", "expected"),
    [
        (True, None, 0.8),
        (True, 100, 0.8),
        (False, None, 1),
        (None, 100, 0.8),
        (None, None, 1),
        (None, "wrong", 1),
    ],
)
@pytest.mark.parametrize("actor_path", [(), ("owner",)])
def test_unknown_only_actor_anchor_preserves_known_cost_and_actual_patched_pdx(
    pressure, population, expected, actor_path
):
    from test_remaining_joint_consumers import _native_number

    from pdx import decision_interfaces
    from pdx.situated import ir

    raw = _data(
        group="equipment_financing_pressure",
        source="common/ship_modifications/00_ship_modifications.txt",
    )
    raw["rules"][0].update(
        id="fixture_cost",
        domain="test",
        field="candidate.ai_weight",
        priority=1,
        operation="multiply",
        value=0.8,
        why="fixture cost",
        counterexample="fixture",
        conditions=[{"fact": "default", "op": "=", "value": True}],
    )
    raw["readers"].pop("prospective_subject_population")
    if actor_path:
        raw["rules"][0]["source"] = "common/buildings/01_industry.txt"
        raw["readers"]["default"]["path"] = ["owner"]
    original = copy.deepcopy(raw["rules"][0])
    changed = cost_policies.apply(raw, source="adapters")
    rule = changed["rules"][0]
    assert rule["conditions"] == original["conditions"]
    assert not rule.get("required_known_facts")
    native = "candidate = { ai_weight = { value = 10 } }"
    policy = decision_rules.from_data(
        {
            "schema": 1,
            "baseline_sha256": hashlib.sha256(native.encode()).hexdigest(),
            "domains": {"test": True},
            "readers": changed["readers"],
            "rules": [{k: v for k, v in rule.items() if k != "source"}],
            "actor_path": list(actor_path),
            "native_root": "state" if actor_path else "country",
        },
        source_sha256="0" * 64,
    )
    policy = programs.enable(policy, source="fixture")
    anchor = "cost_owner_population" if actor_path else "cost_country_population"
    values = {"default": pressure, anchor: population}
    assert decision_rules.evaluate_ir(policy, values, is_ai=True).get(
        "candidate.ai_weight", ("", 1)
    )[1] == pytest.approx(expected)
    generated = decision_rules.patch(
        native,
        policy,
        baseline=native,
        default_strategy=False,
        reader_words=decision_interfaces.proven_reader_words()
        | {"in_default", "total_population", "owner"},
    )
    begin = generated.index("# SITAI BEGIN")
    end = generated.index("# SITAI END")
    overlay = "\n".join(generated[begin:end].splitlines()[1:])
    country = {"is_ai": True, "in_default": pressure, "total_population": population}
    facts = {"ROOT": {"owner": country} if actor_path else country}
    assert _native_number(10, overlay, facts) == pytest.approx(10 * expected)
    action = ir.from_rule(policy.rules[0], source="fixture")
    assert action.to_rule() == policy.rules[0]
    assert action.unknown_cost_required_known_facts == (anchor,)
    contract = cast("dict[str, Any]", decision_rules.contract(policy, source="fixture"))
    row = contract["rules"][0]
    assert row["unknown_cost_required_known_facts"] == [anchor]
    assert anchor in row["inputs"]
    assert contract["cost_by_field"]["candidate.ai_weight"]["predicates"] == 2


def test_unknown_only_anchor_cannot_read_another_entity_or_claim_pressure_as_identity():
    raw = _data(group="equipment_financing_pressure")
    raw["rules"][0]["conditions"] = [{"fact": "default", "op": "=", "value": True}]
    changed = cost_policies.apply(raw, source="adapters")
    changed["readers"].pop("prospective_subject_population")
    changed["readers"]["cost_country_population"]["scope"] = "target_country"
    rule = changed["rules"][0]
    data = {
        "schema": 1,
        "baseline_sha256": "0" * 64,
        "domains": {"test": True},
        "readers": changed["readers"],
        "rules": [
            {
                **{k: v for k, v in rule.items() if k != "source"},
                "domain": "test",
                "field": "candidate.ai_weight",
                "priority": 1,
                "why": "fixture",
                "counterexample": "fixture",
            }
        ],
    }
    with pytest.raises(ValueError, match="实际actor"):
        decision_rules.from_data(data, source_sha256="0" * 64)


@pytest.mark.parametrize(
    ("family", "values", "expected"),
    [
        ("payments", {"default": True, "net_surplus": -10}, 0.85),
        ("payments", {"default": None, "net_surplus": None, "cost_country_population": 10}, 0.85),
        ("payments", {"default": None, "net_surplus": None}, 1),
        ("payments", {"default": False, "net_surplus": 0}, 1),
        ("canal", {"bureaucracy": 999, "default": True}, 0.65),
        ("canal", {"bureaucracy": 1000, "default": False}, 1),
        ("canal", {"bureaucracy": None, "default": None, "cost_country_population": 10}, 0.65),
        ("canal", {"bureaucracy": None, "default": None}, 1),
        ("canal", {"bureaucracy": 1000, "default": None, "cost_country_population": 10}, 0.85),
    ],
)
def test_native_commitment_cost_family_actual_pdx_known_unknown_and_zero(family, values, expected):
    from test_remaining_joint_consumers import _native_number, _overlay
    from test_situated_joint_witnesses import _facts

    from pdx import canal_opportunities, decision_adapters, decision_interfaces
    from pdx import native_action_opportunities as native

    source = (
        canal_opportunities.SOURCE if family == "canal" else native.CANDIDATES["decrease_payments"]
    )
    policy = programs.enable(dict(decision_adapters.load().policies)[source], source=source)
    baseline = (
        canal_opportunities.frozen_inputs()[source]
        if family == "canal"
        else native.load_baseline()["texts"][source]
    )
    generated = decision_rules.patch(
        baseline,
        policy,
        baseline=baseline,
        default_strategy=False,
        reader_words=decision_interfaces.proven_reader_words()
        | {"in_default", "bureaucracy", "net_total_income", "total_population"},
    )
    assert all(rule.conservative_unknown_facts for rule in policy.rules)
    assert all(
        rule.unknown_cost_required_known_facts == ("cost_country_population",)
        for rule in policy.rules
    )
    facts = _facts(policy, values)
    for field in policy.groups():
        overlay = _overlay(generated, ".".join(field))
        assert _native_number(10, overlay, facts) == pytest.approx(10 * expected)
        assert _native_number(0, overlay, facts) == 0
