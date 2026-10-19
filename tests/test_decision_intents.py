"""生成期战略共享约束；合成反例不替代游戏证据。"""

from __future__ import annotations

import copy
import hashlib

import pytest

from pdx import decision_rules


def _strategy_data():
    return {
        "schema": 1,
        "signals": {
            "peace": [{"fact": "war", "op": "=", "value": False}],
            "solvent": [{"fact": "default", "op": "=", "value": False}],
        },
        "intents": {
            "capacity": {"signals": ["solvent", "peace"]},
            "development": {
                "requires": ["capacity"],
                "signals": ["peace"],
                "conditions": [{"fact": "income", "op": ">", "value": 0}],
            },
        },
    }


def _policy_data():
    return {
        "schema": 1,
        "baseline_sha256": "0" * 64,
        "domains": {"economy": True},
        "readers": {
            "war": {"engine": "is_at_war", "scope": "root", "unit": "boolean", "kind": "boolean"},
            "default": {
                "engine": "in_default",
                "scope": "root",
                "unit": "boolean",
                "kind": "boolean",
            },
            "income": {
                "engine": "fixed_income",
                "scope": "root",
                "unit": "currency_per_week",
                "kind": "number",
            },
        },
        "rules": [
            {
                "id": "development",
                "domain": "economy",
                "field": "wanted_construction_output",
                "priority": 50,
                "value": 1.05,
                "intent": "development",
                "conditions": [],
                "why": "合成发展意图",
                "counterexample": "财政不足与战时不鼓励新增发展",
            }
        ],
    }


def test_intent_dag_expands_once_and_is_emitted_into_actual_script():
    from pdx import decision_intents

    strategy = decision_intents.from_data(_strategy_data(), source_sha256="1" * 64)
    policy = decision_rules.from_data(_policy_data(), source_sha256="2" * 64, strategy=strategy)
    assert len(policy.rules[0].conditions) == 3
    assert decision_rules.evaluate(
        policy, {"war": False, "default": False, "income": 1}, is_ai=True
    )
    for change in ({"war": True}, {"default": True}, {"income": 0}, {"income": None}):
        assert not decision_rules.evaluate(
            policy, {"war": False, "default": False, "income": 1, **change}, is_ai=True
        )
    assert not decision_rules.evaluate(
        policy, {"war": False, "default": False, "income": 1}, is_ai=False
    )
    baseline = "ai_strategy_default = { wanted_construction_output = { value = 10 } }\n"
    policy = decision_rules.from_data(
        {**_policy_data(), "baseline_sha256": hashlib.sha256(baseline.encode()).hexdigest()},
        source_sha256="2" * 64,
        strategy=strategy,
    )
    script = decision_rules.patch(
        baseline,
        policy,
        baseline=baseline,
        reader_evidence="in_default = no is_at_war = no fixed_income > 0",
    )
    assert "in_default = no" in script
    assert "is_at_war = no" in script
    assert "fixed_income > 0" in script
    assert "multiply = 1.05" in script
    contract = decision_rules.contract(policy)
    entries = contract["rules"]
    assert isinstance(entries, list)
    assert entries[0]["intent"] == "development"
    metadata = contract["strategy"]
    assert isinstance(metadata, dict)
    assert metadata["source_sha256"] == "1" * 64
    assert len(metadata["generator_sha256"]) == 64


@pytest.mark.parametrize(
    "change",
    [
        {"development": {"requires": ["capacity", "capacity"]}},
        {"development": {"requires": ["missing"]}},
        {"capacity": {"requires": ["development"]}},
        {"development": {"signals": ["missing"]}},
        {"development": {"conditions": []}},
    ],
)
def test_invalid_intent_graph_is_rejected_before_rule_generation(change):
    from pdx import decision_intents

    raw = _strategy_data()
    raw["intents"].update(change)
    with pytest.raises(ValueError):
        decision_intents.from_data(raw, source_sha256="1" * 64)


def test_intent_expansion_keeps_existing_static_budget():
    from pdx import decision_intents

    raw = _strategy_data()
    raw["intents"]["development"]["conditions"] = [
        {"fact": "income", "op": ">", "value": value} for value in range(17)
    ]
    with pytest.raises(ValueError, match="预算"):
        decision_intents.from_data(raw, source_sha256="1" * 64)


def test_unknown_intent_does_not_silently_become_an_unconditional_rule():
    raw = copy.deepcopy(_policy_data())
    with pytest.raises(ValueError, match="意图"):
        decision_rules.from_data(raw, source_sha256="2" * 64)


@pytest.mark.parametrize("bad", [None, "", [], 0])
def test_malformed_intent_cannot_bypass_expansion(bad):
    from pdx import decision_intents

    raw = _policy_data()
    raw["rules"][0]["intent"] = bad
    raw["rules"][0]["conditions"] = [{"fact": "income", "op": ">", "value": 0}]
    strategy = decision_intents.from_data(_strategy_data(), source_sha256="1" * 64)
    with pytest.raises(ValueError, match="意图"):
        decision_rules.from_data(raw, source_sha256="2" * 64, strategy=strategy)


def test_duplicate_predicates_cannot_hide_boolean_type_errors():
    from pdx import decision_intents

    raw = _strategy_data()
    raw["intents"]["development"]["conditions"] += [
        {"fact": "war", "op": "=", "value": 0},
    ]
    strategy = decision_intents.from_data(raw, source_sha256="1" * 64)
    with pytest.raises(ValueError, match="类型"):
        decision_rules.from_data(_policy_data(), source_sha256="2" * 64, strategy=strategy)


def test_depth_budget_covers_cached_dependencies():
    from pdx import decision_intents

    raw = _strategy_data()
    for index in range(10):
        raw["intents"][f"chain_{index}"] = {
            "requires": [f"chain_{index - 1}" if index else "development"]
        }
    with pytest.raises(ValueError, match="深度预算"):
        decision_intents.from_data(raw, source_sha256="1" * 64)


@pytest.mark.parametrize(
    "change",
    [
        {"schema": True},
        {"signals": []},
        {"intents": {}},
        {"unexpected": {}},
        {"signals": {"bad/name": [{"fact": "war", "op": "=", "value": False}]}},
        {"signals": {"peace": []}},
        {"signals": {"peace": "war"}},
        {"signals": {"peace": [{"fact": "war", "op": "!=", "value": False}]}},
        {"signals": {"peace": [{"fact": "war", "op": "=", "value": "no"}]}},
        {"signals": {"peace": [{"fact": "war", "op": "=", "value": float("nan")}]}},
        {"signals": {"peace": [{"fact": "war", "op": "=", "value": 10**1000}]}},
        {"signals": {"peace": [{"fact": "war", "op": "=", "value": {"fact": "bad/name"}}]}},
        {"intents": {"capacity": {"unexpected": []}}},
        {"intents": {"capacity": {"requires": "development"}}},
        {"intents": {"capacity": {"signals": ["peace", "peace"]}}},
    ],
)
def test_malformed_strategy_inputs_fail_closed(change):
    from pdx import decision_intents

    with pytest.raises(ValueError):
        decision_intents.from_data({**_strategy_data(), **change}, source_sha256="1" * 64)


def test_unconsumed_signal_and_unknown_intent_cannot_survive():
    from pdx import decision_intents

    raw = _strategy_data()
    raw["signals"]["orphan"] = [{"fact": "income", "op": ">", "value": 0}]
    with pytest.raises(ValueError, match="消费者"):
        decision_intents.from_data(raw, source_sha256="1" * 64)
    strategy = decision_intents.from_data(_strategy_data(), source_sha256="1" * 64)
    with pytest.raises(ValueError, match="未知战略意图"):
        strategy.expand("missing")


def test_graph_count_budgets_are_independent_of_predicate_deduplication():
    from pdx import decision_intents

    raw = _strategy_data()
    raw["intents"].update({f"extra_{index}": {"signals": ["peace"]} for index in range(33)})
    with pytest.raises(ValueError, match="数量预算"):
        decision_intents.from_data(raw, source_sha256="1" * 64)


def test_unknown_higher_intent_blocks_lower_candidate_unless_known_false():
    from pdx import decision_intents

    raw = _policy_data()
    raw["rules"].append(
        {
            **raw["rules"][0],
            "id": "lower",
            "priority": 1,
            "conditions": [{"fact": "income", "op": ">", "value": 0}],
        }
    )
    del raw["rules"][1]["intent"]
    strategy = decision_intents.from_data(_strategy_data(), source_sha256="1" * 64)
    policy = decision_rules.from_data(raw, source_sha256="2" * 64, strategy=strategy)
    assert not decision_rules.evaluate(
        policy, {"war": None, "default": False, "income": 1}, is_ai=True
    )
    result = decision_rules.evaluate(
        policy, {"war": True, "default": None, "income": 1}, is_ai=True
    )
    assert result["wanted_construction_output"][0] == "lower"


def test_production_intents_coordinate_fiscal_recovery_development_and_cooperation():
    policy = decision_rules.load()
    values = {
        reader.key: False if reader.kind == "boolean" else max(0.0, reader.minimum or 0.0)
        for reader in policy.readers
    }
    values.update(
        income=100,
        net_surplus=10,
        debt_ratio=0.1,
        legitimacy=60,
        industrial_route=True,
        population=3_000_000,
    )
    fields = (
        "wanted_construction_output",
        "institution_scores.institution_schools",
        "treaty_category_scores.trade",
        "treaty_category_scores.economy",
    )
    result = decision_rules.evaluate(policy, values, is_ai=True)
    assert all(result[field][1] > 1 for field in fields)
    for change in (
        {"loans": True},
        {"net_surplus": -1},
        {"debt_ratio": 0.6},
        {"legitimacy": 20},
        {"insurrection": True},
        {"net_surplus": None},
    ):
        result = decision_rules.evaluate(policy, {**values, **change}, is_ai=True)
        assert all(field not in result for field in fields)
    recovering = decision_rules.evaluate(policy, {**values, "default": True}, is_ai=True)
    assert recovering["wanted_construction_output"][1] < 1
    assert recovering["wanted_army_size"][1] < 1
    assert recovering["institution_scores.institution_social_security"][1] < 1
    wartime = decision_rules.evaluate(policy, {**values, "default": True, "war": True}, is_ai=True)
    assert "wanted_army_size" not in wartime
    assert "max_active_stances" not in wartime
