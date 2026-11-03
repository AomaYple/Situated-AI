"""Complete university and railway choices retain need without fictional recipes."""

import hashlib
import re
import tomllib

import pytest
from test_remaining_joint_consumers import _block, _overlay, _render
from test_situated_joint_witnesses import _facts

from pdx import country_state, decision_adapters, decision_rules
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval, programs

UNIVERSITY = "building_university.ai_value"
RAILWAY = "building_railway.ai_value"
GOV = "common/buildings/07_government.txt"
RAIL = "common/buildings/11_private_infrastructure.txt"
FIELDS = {GOV: UNIVERSITY, RAIL: RAILWAY}
UNI_PM = "pm_active_building_university_pm_scholastic_education"
RAIL_PM = "pm_active_building_railway_pm_early_trains"


def _raw_policies():
    raw_bytes = decision_adapters.SOURCE.read_bytes()
    data = tomllib.loads(raw_bytes.decode("utf-8"))
    selected = []
    for source, field in FIELDS.items():
        rules = [
            {key: value for key, value in r.items() if key != "source"}
            for r in data["rules"]
            if r["source"] == source and r["field"] == field
        ]
        names = {name for r in rules for name in r.get("contexts", [])}
        contexts = {name: data["contexts"][name] for name in names}
        conditions = [condition for r in rules for condition in r["conditions"]]
        conditions.extend(c for group in contexts.values() for c in group)
        used = {c["fact"] for c in conditions}
        policy = decision_rules.from_data(
            {
                "schema": 1,
                "baseline_sha256": data["sources"][source],
                "actor_path": ["owner"],
                "native_root": "state",
                "readers": {key: data["readers"][key] for key in used},
                "domains": {r["domain"]: True for r in rules},
                "rules": rules,
                "contexts": contexts,
            },
            source_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        )
        selected.append((source, policy))
    return data, raw_bytes, selected


@pytest.fixture(scope="module")
def production():
    data, raw_bytes, raw = _raw_policies()
    model = compiler.load_model()
    selected = [
        (source, compiler.compile_policy(policy, source, model)[0]) for source, policy in raw
    ]
    adapter = decision_adapters.AdapterSet(
        tuple(data["sources"].items()), tuple(selected), hashlib.sha256(raw_bytes).hexdigest()
    )
    inputs = decision_adapters.read_inputs(adapter)
    files, _ = decision_adapters.build(
        adapter, texts=inputs, country_policy=country_state.load(), consumer_ir=model.consumer_ir
    )
    disabled, _ = decision_adapters.build(
        adapter,
        texts=inputs,
        enabled_domains=frozenset(),
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
    )
    return dict(selected), files, inputs, disabled


def _values(policy, changes):
    values: dict[str, object] = {r.key: False if r.kind == "boolean" else 0 for r in policy.readers}
    values.update(state_owner_literacy=0.8, state_infrastructure=0)
    values.update(changes)
    return values


CASES = [
    (GOV, {"state_owner_literacy": 0.3, "state_owner_loans": True}, 1.10),
    (GOV, {"state_owner_literacy": 0.3, "state_owner_default": None, UNI_PM: None}, 1.10),
    (GOV, {"state_owner_literacy": 0.3, "state_owner_default": True}, 0.95),
    (GOV, {"state_owner_literacy": 0.3, "state_owner_academia_completed": True}, 1.15),
    (GOV, {"state_owner_literacy": 0.3, UNI_PM: True}, 1.20),
    (GOV, {"state_owner_literacy": 0.3, UNI_PM: True, "state_owner_paper_balance": None}, 1.10),
    (
        GOV,
        {
            "state_owner_literacy": 0.3,
            UNI_PM: True,
            "state_owner_paper_price": 0.6,
            "state_owner_paper_balance": -1,
        },
        0.90,
    ),
    (GOV, {"state_owner_literacy": 0.8, "coord_owner_layer_expansion": True, UNI_PM: True}, 1),
    (GOV, {"state_owner_literacy": 0.5}, 1),
    (GOV, {"state_owner_literacy": None, "coord_owner_layer_expansion": True}, 1),
    (RAIL, {"state_infrastructure": -1, RAIL_PM: None, "state_owner_loans": True}, 1.10),
    (
        RAIL,
        {"state_infrastructure": -1, "state_owner_default": None, "state_transport_price": None},
        1.10,
    ),
    (RAIL, {"state_infrastructure": -1, "state_owner_default": True}, 0.95),
    (RAIL, {"state_infrastructure": -1, RAIL_PM: True}, 1.20),
    (RAIL, {"state_infrastructure": -1, RAIL_PM: True, "state_owner_coal_balance": None}, 1.10),
    (
        RAIL,
        {
            "state_infrastructure": -1,
            RAIL_PM: True,
            "state_owner_coal_balance": -1,
            "state_owner_coal_price": 0.6,
        },
        0.90,
    ),
    (
        RAIL,
        {
            "state_infrastructure": -1,
            RAIL_PM: True,
            "state_owner_coal_balance": -1,
            "state_owner_coal_price": 0.6,
            "state_owner_engines_balance": -1,
            "state_owner_engines_price": 0.6,
        },
        0.70,
    ),
    (
        RAIL,
        {
            "state_infrastructure": 0,
            RAIL_PM: True,
            "state_transport_price": 0.6,
            "coord_owner_layer_expansion": True,
        },
        1,
    ),
    (RAIL, {"state_infrastructure": None, "coord_owner_layer_expansion": True}, 1),
]


@pytest.mark.parametrize(("source", "changes", "expected"), CASES)
def test_raw_complete_field_has_independent_need_and_cost(source, changes, expected):
    _, _, policies = _raw_policies()
    policy = programs.enable(dict(policies)[source], source=source)
    result = decision_rules.evaluate(policy, _values(policy, changes), is_ai=True).get(
        FIELDS[source]
    )
    assert (result[1] if result else 1) == pytest.approx(expected)


@pytest.mark.parametrize(("source", "changes", "expected"), CASES)
def test_complete_choice_matches_hand_value_reference_and_production_pdx(
    production, source, changes, expected
):
    policies, files, _, _ = production
    policy = policies[source]
    values = _values(policy, changes)
    selected = decision_rules.evaluate(policy, values, is_ai=True).get(FIELDS[source])
    assert (selected[1] if selected else 1) == pytest.approx(expected)
    assert pdx_eval.select(
        _overlay(files[source], FIELDS[source]), _facts(policy, values)
    ).delta == pytest.approx(expected)


def test_full_native_definition_ast_and_player_unknown_disabled_are_preserved(production):
    policies, files, inputs, disabled = production
    for source, field in FIELDS.items():
        name = field.split(".")[0]
        stripped = re.sub(
            r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
            "\n",
            files[source],
            flags=re.DOTALL,
        )
        assert _render(_block(parse_text(inputs[source]).root, name)) == _render(
            _block(parse_text(stripped).root, name)
        )
        assert source not in disabled
        policy = policies[source]
        values = _values(policy, {"state_owner_literacy": 0.3, "state_infrastructure": -1})
        overlay = _overlay(files[source], field)
        assert pdx_eval.select(overlay, _facts(policy, values, is_ai=False)).operation is None
        assert pdx_eval.select(overlay, {}).operation is None
        assert not decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset())


def test_no_common_gate_or_unknown_recipe_or_healthy_expansion_reward(production):
    policies, _, _, _ = production
    for source, policy in policies.items():
        for rule in policy.rules:
            if rule.value > 1:
                keys = rule.input_keys()
                assert not any(
                    key.startswith("coord_") or key in {"state_owner_default", "state_owner_loans"}
                    for key in keys
                )
                assert ("state_owner_literacy" if source == GOV else "state_infrastructure") in keys
        assert all("university_observed" not in r.key for r in policy.readers)


@pytest.mark.parametrize(
    ("source", "method", "goods"),
    [
        (GOV, "pm_scholastic_education", ("paper",)),
        (GOV, "pm_philosophy_department", ("paper",)),
        (GOV, "pm_analytical_philosophy_department", ("paper",)),
        (RAIL, "pm_early_trains", ("coal", "engines")),
        (RAIL, "pm_steam_trains", ("coal", "engines")),
        (RAIL, "pm_steam_trains_principle_transport_3", ("coal", "engines")),
        (RAIL, "pm_electric_trains", ("electricity", "engines")),
        (RAIL, "pm_electric_trains_principle_transport_3", ("electricity", "engines")),
        (RAIL, "pm_diesel_trains", ("engines", "oil")),
        (RAIL, "pm_diesel_trains_principle_transport_3", ("engines", "oil")),
    ],
)
def test_every_actual_recipe_preparation_and_each_input_cost_remain_separate(
    production, source, method, goods
):
    policies, files, _, _ = production
    policy = policies[source]
    building = FIELDS[source].split(".")[0]
    need = {"state_owner_literacy": 0.3} if source == GOV else {"state_infrastructure": -1}
    changes = {**need, f"pm_active_{building}_{method}": True}
    overlay = _overlay(files[source], FIELDS[source])
    for cost_good in (None, *goods):
        values = _values(policy, changes)
        if cost_good:
            values[f"state_owner_{cost_good}_price"] = 0.6
            values[f"state_owner_{cost_good}_balance"] = -1
        expected = 0.90 if cost_good else 1.20
        selected = decision_rules.evaluate(policy, values, is_ai=True).get(FIELDS[source])
        assert (selected[1] if selected else 1) == pytest.approx(expected)
        assert pdx_eval.select(overlay, _facts(policy, values)).delta == pytest.approx(expected)


def test_unknown_recipe_never_assumes_coal_power_oil_or_paper_cost(production):
    policies, files, _, _ = production
    for source, policy in policies.items():
        changes = {"state_owner_literacy": 0.3} if source == GOV else {"state_infrastructure": -1}
        values = _values(policy, changes)
        for reader in policy.readers:
            if reader.key.startswith("pm_active_"):
                values[reader.key] = None
            elif reader.key.endswith("_price"):
                values[reader.key] = 0.6
            elif reader.key.endswith("_balance"):
                values[reader.key] = -1
        selected = decision_rules.evaluate(policy, values, is_ai=True).get(FIELDS[source])
        assert (selected[1] if selected else 1) == pytest.approx(1.10)
        assert pdx_eval.select(
            _overlay(files[source], FIELDS[source]), _facts(policy, values)
        ).delta == pytest.approx(1.10)


def test_electric_railway_does_not_pay_coal_recipe_cost(production):
    policies, files, _, _ = production
    policy = policies[RAIL]
    values = _values(
        policy,
        {
            "state_infrastructure": -1,
            "pm_active_building_railway_pm_electric_trains": True,
            "state_owner_coal_balance": -1,
            "state_owner_coal_price": 0.6,
        },
    )
    selected = decision_rules.evaluate(policy, values, is_ai=True).get(RAILWAY)
    assert selected is not None
    assert selected[1] == pytest.approx(1.20)
    assert pdx_eval.select(
        _overlay(files[RAIL], RAILWAY), _facts(policy, values)
    ).delta == pytest.approx(1.20)
