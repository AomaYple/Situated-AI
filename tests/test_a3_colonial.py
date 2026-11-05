"""真实殖民活动和投资优先级饱和的独立参考/PDX见证。"""

from __future__ import annotations

import re
import tomllib
from dataclasses import replace

import pytest
from test_remaining_joint_consumers import _block, _native_number, _overlay, _render
from test_situated_joint_witnesses import _facts

from pdx import colonial_opportunities as colonial
from pdx import config, country_state, decision_adapters, decision_rules
from pdx.parser import parse_text
from pdx.situated import compiler
from pdx.textio import normalized_text

pytestmark = pytest.mark.integration
SOURCE = colonial.SOURCE
FIELD = colonial.FIELD


@pytest.fixture(scope="module")
def native_inputs():
    return {
        source: normalized_text((config.GAME / source).read_text(encoding="utf-8-sig"))
        for source in colonial.load()["sources"]
    }


def test_native_activity_query_has_complete_owned_state_consumer_proof(native_inputs):
    query = colonial.query_from_reader("any_scope_state", {"colonial_query": "active_projects"})
    proof = colonial.compile_query(query, native_inputs)
    assert proof.expression == "any_scope_state = { is_under_colonization = yes }"
    assert proof.local_collections == ("owned_states",)
    assert proof.actor == "country"
    assert proof.world_scans == 0
    assert proof.references == (f"{colonial.QUERY_SOURCE}:1009",)
    assert "missing_member_observation=unknown" in proof.unknown_policy
    colonial.verify_inputs(native_inputs)
    with pytest.raises(ValueError, match="来源漂移"):
        colonial.verify_inputs(
            {**native_inputs, colonial.QUERY_SOURCE: native_inputs[colonial.QUERY_SOURCE] + "\n"}
        )
    for engine, parameters in (
        ("colonial_growth_per_colony", {"colonial_query": "active_projects"}),
        ("any_country", {"colonial_query": "active_projects"}),
        ("any_scope_state", {"colonial_query": "target_region"}),
        ("any_scope_state", {"colonial_query": "active_projects", "target_region": "africa"}),
    ):
        with pytest.raises(ValueError, match="精确"):
            colonial.query_from_reader(engine, parameters)


def test_frozen_derivation_does_not_read_installation_or_use_growth_as_activity(
    native_inputs, monkeypatch, tmp_path
):
    raw = tomllib.loads(decision_adapters.SOURCE.read_text(encoding="utf-8"))
    expected = colonial.derive(raw)
    assert colonial.frozen_inputs() == native_inputs
    monkeypatch.setattr(config, "GAME", tmp_path / "absent")
    assert colonial.derive(raw) == expected
    assert len(expected["rules"]) == 5
    assert len(expected["covered"]) == 1
    assert all(rule["semantic_role"] != "cost" for rule in expected["rules"])
    assert {reader["engine"] for reader in expected["readers"].values()} == {
        "has_institution",
        "institution_investment_level",
        "any_scope_state",
    }


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    model = compiler.load_model()
    policy, _ = compiler.compile_policy(dict(adapters.policies)[SOURCE], SOURCE, model)
    selected = replace(
        adapters,
        policies=((SOURCE, policy),),
        supply=None,
        initial_values=tuple(row for row in adapters.initial_values if row.source == SOURCE),
        scalar_values=tuple(row for row in adapters.scalar_values if row[0] == SOURCE),
    )
    native = decision_adapters.read_inputs(selected)
    files, _ = decision_adapters.build(
        selected, texts=native, country_policy=country_state.load(), consumer_ir=model.consumer_ir
    )
    return policy, files[SOURCE], native[SOURCE]


def _values(policy, changes):
    values = dict.fromkeys(reader.key for reader in policy.readers)
    values.update(
        has_colonial_affairs_institution=True,
        colonial_affairs_investment=0,
        colonial_active_projects=True,
        bureaucracy=0,
        default=False,
        war=False,
    )
    values.update(changes)
    return values


def _engine(policy, values, states):
    facts = _facts(policy, values)
    facts["ROOT"]["any_scope_state"] = states
    return facts


# Handwritten actual project and known investment tiers; no native maximum claim.
CASES: list[tuple[dict[str, object], list[dict[str, object]] | None, float]] = [
    ({}, [{"is_under_colonization": True}], 1.18),
    ({"colonial_affairs_investment": 2.999}, [{"is_under_colonization": True}], 1.18),
    ({"colonial_affairs_investment": 3}, [{"is_under_colonization": True}], 1.08),
    ({"colonial_affairs_investment": 5}, [{"is_under_colonization": True}], 1.04),
    ({"colonial_affairs_investment": 50}, [{"is_under_colonization": True}], 1.04),
    ({"colonial_affairs_investment": None}, [{"is_under_colonization": True}], 1.18),
    ({"colonial_active_projects": False}, [], 1),
    ({"colonial_active_projects": False, "colonial_affairs_investment": 1}, [], 0.92),
    ({"colonial_active_projects": False, "colonial_affairs_investment": 3}, [], 0.85),
    ({"colonial_active_projects": False, "colonial_affairs_investment": None}, [], 1),
    ({"colonial_active_projects": None, "colonial_affairs_investment": 5}, None, 1),
    ({"colonial_active_projects": None, "colonial_affairs_investment": 5}, [{}], 1),
    (
        {"colonial_active_projects": None, "colonial_affairs_investment": 5},
        [{"is_under_colonization": False}, {}],
        1,
    ),
    ({"colonial_affairs_investment": 3}, [{}, {"is_under_colonization": True}], 1.08),
    (
        {"colonial_active_projects": False, "colonial_affairs_investment": 3},
        [{"is_under_colonization": False}],
        0.85,
    ),
    ({"bureaucracy": -1}, [{"is_under_colonization": True}], 0.98),
    ({"default": True}, [{"is_under_colonization": True}], 0.93),
    (
        {"default": True, "bureaucracy": -1, "colonial_affairs_investment": 3},
        [{"is_under_colonization": True}],
        0.63,
    ),
    ({"bureaucracy": None}, [{"is_under_colonization": True}], 1.18),
    ({"has_colonial_affairs_institution": False}, [{"is_under_colonization": True}], 1),
    ({"has_colonial_affairs_institution": None}, [{"is_under_colonization": True}], 1),
]


@pytest.mark.parametrize(("changes", "states", "expected"), CASES)
def test_reference_and_real_pdx_follow_independent_activity_and_saturation(
    production, changes, states, expected
):
    policy, generated, _ = production
    values = _values(policy, changes)
    result = decision_rules.evaluate(policy, values, is_ai=True)
    assert result.get(FIELD, ("native", 1))[1] == pytest.approx(expected)
    assert _native_number(
        1, _overlay(generated, FIELD), _engine(policy, values, states)
    ) == pytest.approx(expected)


def test_foreign_activity_and_growth_capacity_cannot_supply_owned_activity(production):
    policy, generated, _ = production
    values = _values(policy, {"colonial_active_projects": False, "colonial_affairs_investment": 3})
    facts = _engine(policy, values, [])
    facts["scope:target_country"] = {"any_scope_state": [{"is_under_colonization": True}]}
    facts["scope:target_region"] = {"any_scope_state": [{"is_under_colonization": True}]}
    facts["ROOT"]["colonial_growth_per_colony"] = 500
    facts["ROOT"]["has_colonial_growth"] = True
    assert _native_number(1, _overlay(generated, FIELD), facts) == pytest.approx(0.85)
    facts["ROOT"]["is_ai"] = False
    assert _native_number(1, _overlay(generated, FIELD), facts) == 1
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}


def test_complete_native_strategy_ast_remains_with_all_original_decisions(production):
    _, generated, native = production
    stripped = re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        generated,
        flags=re.DOTALL,
    )
    original, retained = parse_text(native), parse_text(stripped)
    assert not original.errors
    assert not retained.errors
    original_scores = _block(_block(original.root, "ai_strategy_default"), "institution_scores")
    retained_scores = _block(_block(retained.root, "ai_strategy_default"), "institution_scores")
    assert _render(original_scores) == _render(retained_scores)
