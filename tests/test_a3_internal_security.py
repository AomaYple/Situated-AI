"""A3 内部安全的原版完整效果、具体议程和真实制度转换见证。"""

from __future__ import annotations

import re
import tomllib
from dataclasses import replace

import pytest
from test_remaining_joint_consumers import _block, _native_number, _overlay, _render
from test_situated_joint_witnesses import _facts

from pdx import config, country_state, decision_adapters, decision_rules
from pdx import internal_security_opportunities as security
from pdx.parser import parse_text
from pdx.situated import compiler
from pdx.textio import normalized_text

pytestmark = pytest.mark.integration
SOURCE = security.LAW_SOURCE


@pytest.fixture(scope="module")
def native_inputs():
    return {
        source: normalized_text((config.GAME / source).read_text(encoding="utf-8-sig"))
        for source in security.load()["sources"]
    }


def test_complete_native_effect_inventory_preserves_mechanism_units_and_variant_boundary(
    native_inputs,
):
    result = security.inventory(native_inputs)
    laws = result["laws"]
    assert set(laws) == {
        "law_no_home_affairs",
        "law_national_guard",
        "law_secret_police",
        "law_shinsengumi",
        "law_third_section",
        "law_okhrana",
        "law_extraordinary_commission",
        "law_guaranteed_liberties",
    }
    assert laws["law_no_home_affairs"]["effects"] == []
    for law, expected in (
        ("law_national_guard", -0.03),
        ("law_secret_police", -0.05),
    ):
        effect = next(
            row
            for row in laws[law]["effects"]
            if row["field"] == "political_movement_radicalism_add"
        )
        assert (effect["value"], effect["unit"], effect["channel"]) == (
            expected,
            "per_invested_level",
            "movement_intensity",
        )
    variant = laws["law_shinsengumi"]
    assert variant["parent"] == "law_secret_police"
    effect = next(
        row for row in variant["effects"] if row["field"] == "political_movement_radicalism_add"
    )
    assert (effect["value"], effect["unit"], effect["channel"]) == (-0.05, "flat", None)
    assert all(row["responsibility"] for law in laws.values() for row in law["effects"])
    assert any(
        row["responsibility"] == "actual_coup_exposure_not_registered"
        for law in laws.values()
        for row in law["effects"]
    )
    security.verify_inputs(native_inputs)
    with pytest.raises(ValueError, match="来源漂移"):
        security.verify_inputs({**native_inputs, SOURCE: native_inputs[SOURCE] + "\n"})


def test_movement_query_requires_native_country_collection_and_exact_thresholds(native_inputs):
    for threshold in (0.25, 0.75):
        query = security.query_from_reader(
            "any_political_movement",
            {"security_query": "radicalism", "threshold": str(threshold)},
        )
        proof = security.compile_query(query, native_inputs)
        assert proof.expression == (
            f"any_political_movement = {{ political_movement_radicalism >= {threshold} }}"
        )
        assert proof.local_collections == ("owned_political_movements",)
        assert proof.world_scans == 0
        assert proof.references
    with pytest.raises(ValueError, match="阈值"):
        security.render_query(security.SecurityQuery(0.2))
    with pytest.raises(ValueError, match="参数"):
        security.query_from_reader(
            "any_scope_state", {"security_query": "radicalism", "threshold": "0.25"}
        )


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    model = compiler.load_model()
    policy, _ = compiler.compile_policy(dict(adapters.policies)[SOURCE], SOURCE, model)
    selected = replace(
        adapters,
        policies=((SOURCE, policy),),
        initial_values=(),
        scalar_values=(),
        supply=None,
    )
    native = decision_adapters.read_inputs(selected)
    files, _ = decision_adapters.build(
        selected,
        texts=native,
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
    )
    return policy, files[SOURCE], native[SOURCE]


def _values(policy, changes):
    values = dict.fromkeys(reader.key for reader in policy.readers)
    values.update(
        default=False,
        bureaucracy=0,
        legitimacy=60,
        insurrection=False,
        radical_share=0,
        home_affairs_investment=0,
        security_movement_radicalism_base=False,
    )
    for law in security.load()["candidates"]:
        values[f"security_current_{law}"] = False
        values[f"security_{law}_movement_base"] = False
        values[f"security_{law}_movement_strong"] = False
    values.update(changes)
    return values


def _engine(policy, values):
    facts = _facts(policy, values)
    # Real PDX queries execute the full collection rather than consuming a
    # precomputed true/false flag. Unknown candidate data stays in the collection.
    movements = []
    for law in security.load()["candidates"]:
        base = values[f"security_{law}_movement_base"]
        strong = values[f"security_{law}_movement_strong"]
        if base or strong:
            movements.append(
                {
                    "law_enactment_stance": {(("law", f"law_type:{law}"),): 1},
                    "political_movement_support": 0.25 if strong else 0.10,
                    "political_movement_radicalism": 0,
                }
            )
    intensity = values["security_movement_radicalism_base"]
    if intensity:
        movements.append(
            {
                "law_enactment_stance": {},
                "political_movement_support": 0,
                "political_movement_radicalism": 0.25,
            }
        )
    facts["ROOT"]["any_political_movement"] = None if intensity is None else movements
    return facts


CASES = [
    ("law_secret_police", {"security_law_secret_police_movement_base": True}, 6),
    ("law_shinsengumi", {"security_law_shinsengumi_movement_base": True}, 6),
    (
        "law_secret_police",
        {
            "security_law_secret_police_movement_base": True,
            "security_current_law_secret_police": None,
        },
        6,  # Independent known agenda survives an unknown current-law read.
    ),
    (
        "law_secret_police",
        {
            "security_law_secret_police_movement_base": True,
            "security_law_secret_police_movement_strong": True,
        },
        10,
    ),
    (
        "law_secret_police",
        {
            "security_law_secret_police_movement_base": True,
            "security_current_law_secret_police": True,
        },
        0,
    ),
    (
        "law_secret_police",
        {
            "security_current_law_no_home_affairs": True,
            "bureaucracy": -1,
            "default": True,
        },
        -14,
    ),
    (
        "law_secret_police",
        {
            "security_current_law_national_guard": True,
            "home_affairs_investment": 1,
            "security_movement_radicalism_base": True,
        },
        8,
    ),
    (
        "law_national_guard",
        {
            "security_current_law_secret_police": True,
            "home_affairs_investment": 3,
            "security_movement_radicalism_base": True,
        },
        -9,  # A weaker intensity effect loses protection, retaining native eligibility.
    ),
    (
        "law_no_home_affairs",
        {
            "security_current_law_guaranteed_liberties": True,
            "home_affairs_investment": 1,
            "security_movement_radicalism_base": True,
        },
        -6,  # Removing the two-sided movement-conversion mechanism costs once.
    ),
    (
        "law_guaranteed_liberties",
        {
            "security_current_law_national_guard": True,
            "home_affairs_investment": 1,
            "security_movement_radicalism_base": True,
            "bureaucracy": -1,
            "default": True,
        },
        2,  # Switching an existing institution adds no new-establishment charge.
    ),
    (
        "law_secret_police",
        {
            "security_current_law_national_guard": True,
            "home_affairs_investment": 3,
            "security_movement_radicalism_base": True,
            "security_law_secret_police_movement_strong": True,
            "security_law_secret_police_movement_base": True,
        },
        12,
    ),
    (
        "law_guaranteed_liberties",
        {
            "security_current_law_secret_police": True,
            "home_affairs_investment": 1,
            "security_movement_radicalism_base": True,
        },
        2,  # 8 conversion benefit - 6 movement-intensity loss.
    ),
    (
        "law_secret_police",
        {
            "security_current_law_guaranteed_liberties": True,
            "home_affairs_investment": 3,
            "security_movement_radicalism_base": True,
        },
        3,  # 12 movement benefit - 9 conversion loss.
    ),
    (
        "law_guaranteed_liberties",
        {
            "security_current_law_secret_police": True,
            "security_current_law_shinsengumi": True,
            "home_affairs_investment": 3,
            "security_movement_radicalism_base": True,
        },
        0,  # Parent truth cannot impersonate the exact secret-police origin.
    ),
    (
        "law_guaranteed_liberties",
        {
            "security_current_law_secret_police": True,
            "home_affairs_investment": None,
            "security_movement_radicalism_base": True,
            "security_law_guaranteed_liberties_movement_base": True,
        },
        6,
    ),
    (
        "law_guaranteed_liberties",
        {
            "security_current_law_secret_police": True,
            "home_affairs_investment": 3,
            "security_movement_radicalism_base": None,
        },
        0,
    ),
]


@pytest.mark.parametrize(("law", "changes", "expected"), CASES)
def test_actual_pdx_and_reference_follow_handwritten_transition_tradeoffs(
    production, law, changes, expected
):
    policy, generated, _native = production
    values = _values(policy, changes)
    field = f"{law}.ai_enact_weight_modifier"
    reference = decision_rules.evaluate(policy, values, is_ai=True)
    assert reference.get(field, ("native", 0))[1] == pytest.approx(expected)
    assert _native_number(0, _overlay(generated, field), _engine(policy, values)) == pytest.approx(
        expected
    )


def test_native_eligibility_petitions_and_all_effects_remain_complete(production):
    _policy, generated, native = production
    stripped = re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        generated,
        flags=re.DOTALL,
    )
    original, retained = parse_text(native), parse_text(stripped)
    assert not original.errors
    assert not retained.errors
    assert _render(original.root) == _render(retained.root)
    no_home = _block(original.root, "law_no_home_affairs")
    assert _render(_block(no_home, "ai_will_do")) == "{ always = no }"
    guard = _block(original.root, "law_national_guard")
    assert "law_secret_police" in _render(_block(guard, "ai_will_do"))
    assert "law_guaranteed_liberties" in _render(_block(guard, "ai_will_do"))


def test_player_disabled_missing_and_wrong_country_do_not_supply_political_exposure(production):
    policy, generated, _native = production
    values = _values(
        policy,
        {
            "security_current_law_national_guard": True,
            "home_affairs_investment": 3,
            "security_movement_radicalism_base": True,
        },
    )
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    field = "law_secret_police.ai_enact_weight_modifier"
    overlay = _overlay(generated, field)
    facts = _engine(policy, values)
    facts["ROOT"]["is_ai"] = False
    assert _native_number(0, overlay, facts) == 0
    facts["ROOT"]["is_ai"] = True
    facts["scope:target_country"] = {
        "any_political_movement": [{"political_movement_radicalism": 1}]
    }
    facts["ROOT"]["any_political_movement"] = []
    assert _native_number(0, overlay, facts) == 0
    facts["ROOT"]["any_political_movement"] = None
    assert _native_number(0, overlay, facts) == 0


def test_source_derivation_has_only_existing_finite_consumers(native_inputs):
    adapters = tomllib.loads(decision_adapters.SOURCE.read_text(encoding="utf-8"))
    derived = security.derive(adapters, native_inputs)
    assert len(derived["covered"]) == 8
    assert all(rule["contribution_group"] for rule in derived["rules"])
    assert all(rule["operation"] == "add" for rule in derived["rules"])
    assert all(rule["source"] == SOURCE for rule in derived["rules"])
    assert all(
        "radical_share" not in {condition["fact"] for condition in rule["conditions"]}
        for rule in derived["rules"]
    )
    assert all(
        rule["semantic_role"] == "unspecified"
        for rule in derived["rules"]
        if "_adopted_agenda_" in rule["id"]
    )


def test_frozen_derivation_does_not_read_installation(native_inputs, monkeypatch, tmp_path):
    adapters = tomllib.loads(decision_adapters.SOURCE.read_text(encoding="utf-8"))
    expected = security.derive(adapters, native_inputs)
    monkeypatch.setattr(config, "GAME", tmp_path / "absent-installation")
    assert security.derive(adapters) == expected
    assert security.frozen_inputs() == native_inputs
    drifted = tmp_path / "internal-security-opportunities.json"
    drifted.write_text(
        security.FROZEN.read_text(encoding="utf-8").replace(
            "static_complete_native_sources_not_engine_execution", "engine_execution"
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(security, "FROZEN", drifted)
    with pytest.raises(ValueError, match="冻结底本"):
        security.derive(adapters)
