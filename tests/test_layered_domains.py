"""从同一组真实国家事实贯通协调、路线和完整消费者优先级链。"""

from __future__ import annotations

import random
from dataclasses import replace
from functools import cache

import pytest
from test_country_coordination import facts
from test_country_state import Script

from pdx import country_coordination, country_state, decision_adapters, decision_rules, policy_audit


@pytest.fixture(scope="module")
def policies():
    return [("information", decision_rules.load()), *decision_adapters.load().policies]


@cache
def _country_policy():
    return country_state.load()


@cache
def _context(items):
    return country_coordination.evaluate(_country_policy(), dict(items))


def inputs(policy, country, **local):
    context = _context(tuple(sorted(country.items())))
    values = {}
    for reader in policy.readers:
        if reader.engine.startswith(country_coordination.PREFIX):
            values[reader.key] = context[reader.engine.removeprefix(country_coordination.PREFIX)]
        elif reader.key.startswith("route_"):
            values[reader.key] = False
        elif reader.key in country:
            values[reader.key] = country[reader.key]
        elif (
            reader.key.startswith("state_owner_")
            and reader.key.removeprefix("state_owner_") in country
        ):
            values[reader.key] = country[reader.key.removeprefix("state_owner_")]
        else:
            values[reader.key] = False if reader.kind == "boolean" else max(0, reader.minimum or 0)
    return {**values, **local}


def test_normal_low_debt_financing_does_not_select_recovery(policies):
    country = facts(loans=True, debt_ratio=0.1, net_surplus=5, industrial_route=False)
    policy = country_state.load()
    script = Script(policy)
    assert country_state.advance(policy, country, None, day=0).route != "fiscal_recovery"
    assert script.update(country, 0) != "fiscal_recovery"
    information = dict(policies)["information"]
    result = decision_rules.evaluate(information, inputs(information, country), is_ai=True)
    assert result["wanted_construction_output"][1] > 1


@pytest.mark.parametrize("missing", ["legitimacy", "bureaucracy"])
def test_proven_lower_layer_reaches_actual_subject_consumer(policies, missing):
    policy = dict(policies)["common/ai_strategies/02_subject_diplomatic_strategies.txt"]
    values = inputs(policy, facts(**{missing: None}), liberty=20)
    result = decision_rules.evaluate(policy, values, is_ai=True)
    field = "ai_strategy_subject_maintain_autonomy.weight"
    assert result[field][0].endswith("stable" if missing == "legitimacy" else "foundation")


def test_recent_defeat_outweighs_expansion_in_actual_wargoals(policies):
    policy = dict(policies)["common/ai_strategies/00_default_strategy.txt"]
    values = inputs(policy, facts(war_defeat=True))
    result = decision_rules.evaluate(policy, values, is_ai=True)
    for goal in (
        "annex_country",
        "conquer_state",
        "make_subject",
        "transfer_subject",
        "regime_change",
    ):
        assert result[f"ai_strategy_default.wargoal_scores.{goal}"][1] < 0


@pytest.mark.parametrize(
    "overrides", [{"default": True}, {"net_surplus": -1}, {"bureaucracy": None}]
)
def test_war_does_not_create_unfunded_military_capacity(policies, overrides):
    country = facts(war=True, **overrides)
    for _, policy in policies:
        values = inputs(policy, country, small_arms_balance=10)
        results = decision_rules.evaluate(policy, values, is_ai=True)
        for rule in policy.rules:
            if (
                rule.id.startswith("coordinated_layered_")
                and any(term.fact == "coord_need_security" for term in rule.conditions)
                and (
                    rule.field[-1]
                    in {
                        "wanted_army_size",
                        "wanted_num_supply_ships",
                        "combat_unit_group_artillery",
                        "conscript_battalion_ratio",
                    }
                )
            ):
                assert results.get(".".join(rule.field), (None,))[0] != rule.id


def test_each_layered_rule_has_a_joint_country_witness(policies):
    """禁止给派生布尔随意赋 True 来掩盖与原始事实矛盾的死规则。"""
    country_policy = country_state.load()
    rng = random.Random(5150)
    options: dict[str, list] = {
        "war": [False, True],
        "default": [False, True],
        "loans": [False, True],
        "debt_ratio": [0.1, 0.3, 0.5, 0.8],
        "net_surplus": [-5, 0, 100],
        "bureaucracy": [-1, 0, 150],
        "legitimacy": [20, 40, 60],
        "insurrection": [False, True],
        "literacy": [0.3, 0.8],
        "industrial_route": [False, True],
        "resource_route": [False, True],
        "expansion_route": [False, True],
        "war_defeat": [False, True],
    }
    samples = [
        facts(),
        facts(expansion_route=True),
        facts(bureaucracy=0),
        facts(bureaucracy=-1),
        facts(default=True),
        facts(war=True),
        facts(legitimacy=20),
        facts(war_defeat=True),
        facts(literacy=0.3),
    ]
    samples += [
        facts(**{key: rng.choice(vals) for key, vals in options.items()}) for _ in range(2500)
    ]
    failures = []
    for source, policy in policies:
        reader_map = {reader.key: reader for reader in policy.readers}
        for rule in policy.rules:
            if not rule.id.startswith("coordinated_layered_"):
                continue
            direct = tuple(c for c in rule.conditions if not c.fact.startswith("coord_"))
            direct_rule = replace(rule, conditions=direct)
            fixed = policy_audit._fixture(policy, direct_rule)[0] if direct else {}
            isolated = replace(policy, rules=(rule,), enabled_domains=frozenset({rule.domain}))
            matched = False
            for sample in samples:
                country = dict(sample)
                current_fixed = dict(fixed)
                for key, value in fixed.items():
                    reader = reader_map[key]
                    if reader.scope != "root" or reader.path not in {(), ("owner",)}:
                        continue
                    for name, native in country_policy.readers.items():
                        if (
                            native["engine"] == reader.engine
                            and native.get("argument") == reader.argument
                        ):
                            observed = country[name]
                            if not all(
                                policy_audit._satisfies(c, {key: observed})
                                for c in direct
                                if c.fact == key
                            ):
                                country[name] = value
                            current_fixed[key] = country[name]
                values = inputs(policy, country, **current_fixed)
                if decision_rules.evaluate(isolated, values, is_ai=True):
                    matched = True
                    break
            if not matched:
                failures.append((source, rule.id))
    assert not failures, "\n".join(str(row) for row in failures)


def test_industry_without_positive_evidence_uses_proven_expansion_in_full_chain(policies):
    policy = dict(policies)["common/technology/technologies/10_production.txt"]
    country = facts(industrial_route=False, resource_route=False, war_defeat=False)
    result = decision_rules.evaluate(policy, inputs(policy, country), is_ai=True)

    assert result.get("mechanical_tools.ai_weight") == (
        "coordinated_layered_tech_mechanical_tools_expansion",
        1.1,
    )


def test_proven_industry_need_preempts_expansion_in_full_chain(policies):
    policy = dict(policies)["common/technology/technologies/10_production.txt"]
    country = facts(industrial_route=False, resource_route=True, war_defeat=False)
    result = decision_rules.evaluate(policy, inputs(policy, country), is_ai=True)

    assert result["mechanical_tools.ai_weight"] == (
        "coordinated_layered_tech_mechanical_tools_industry",
        1.25,
    )


def test_reconstruction_without_positive_evidence_uses_proven_expansion(policies):
    policy = dict(policies)["common/ai_strategies/00_default_strategy.txt"]
    country = facts(war_defeat=False)
    result = decision_rules.evaluate(policy, inputs(policy, country), is_ai=True)

    assert result.get("ai_strategy_default.wargoal_scores.conquer_state") == (
        "coordinated_layered_conquer_expansion",
        3.0,
    )


def test_no_overseas_evidence_does_not_block_funded_wartime_supply(policies):
    policy = dict(policies)["common/ai_strategies/00_default_strategy.txt"]
    country = facts(war=True, loans=True, expansion_route=False)
    result = decision_rules.evaluate(policy, inputs(policy, country), is_ai=True)

    assert result["ai_strategy_default.wanted_num_supply_ships"] == (
        "coordinated_layered_security_supply_war",
        1.15,
    )


@pytest.mark.parametrize("missing", ["default", "war", "debt_ratio", "income"])
def test_optional_evidence_does_not_reward_unknown_core_capacity(policies, missing):
    policy = dict(policies)["common/technology/technologies/10_production.txt"]
    country = facts(
        industrial_route=False, resource_route=False, war_defeat=False, **{missing: None}
    )
    result = decision_rules.evaluate(policy, inputs(policy, country), is_ai=True)

    assert "mechanical_tools.ai_weight" not in result


@pytest.mark.parametrize(
    ("source", "field", "overrides", "expected"),
    [
        (
            "common/technology/technologies/30_society.txt",
            "central_archives.ai_weight",
            {"bureaucracy": -1},
            ("central_archives_ai_weight", 1.25),
        ),
        (
            "common/technology/technologies/20_military.txt",
            "artillery.ai_weight",
            {"war": True},
            ("artillery_ai_weight", 1.2),
        ),
        (
            "common/ai_strategies/00_default_strategy.txt",
            "ai_strategy_default.institution_scores.institution_colonial_affairs",
            {"bureaucracy": -1},
            ("coordinated_institution_colonial_affairs_administrative_cost", 0.8),
        ),
        ("information", "wanted_army_size", {"war": True}, ("wartime_army_capacity", 1.15)),
    ],
)
def test_existing_bounded_results_survive_without_shadowed_duplicates(
    policies, source, field, overrides, expected
):
    policy = dict(policies)[source]
    result = decision_rules.evaluate(policy, inputs(policy, facts(**overrides)), is_ai=True)

    assert result[field] == expected


@pytest.mark.parametrize("expansion_route", [False, None, True])
def test_overseas_full_consumer_requires_positive_need_and_proven_capacity(
    policies, expansion_route
):
    policy = dict(policies)["common/ai_strategies/00_default_strategy.txt"]
    country = facts(expansion_route=expansion_route)
    result = decision_rules.evaluate(policy, inputs(policy, country), is_ai=True)
    field = "ai_strategy_default.target_marine_formation_size"

    if expansion_route is True:
        assert result[field] == (
            "coordinated_layered_naval_target_marine_formation_size_overseas",
            1.12,
        )
    else:
        assert field not in result
