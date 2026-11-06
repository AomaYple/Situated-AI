"""Locked university numeric tails, independently observed native branch values."""

from copy import deepcopy

import pytest
from test_a4_economy_consumers import GOV
from test_a4_economy_consumers import generated as generated  # noqa: PLC0414
from test_situated_joint_witnesses import _facts

from pdx.model import Block
from pdx.parser import parse_text
from pdx.situated import pdx_eval


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (False, False, True),
        (False, True, False),
        (True, False, False),
        (True, True, False),
        (None, False, None),
        (False, None, None),
        (None, True, False),
        (True, None, False),
        (None, None, None),
    ],
)
def test_native_nor_three_value_table(left, right, expected):
    block = parse_text("NOR = { left = yes right = yes }").root
    assert pdx_eval.condition(block, {"left": left, "right": right}) is expected


@pytest.mark.parametrize(
    "text", ["NOR > { always = yes }", "NOR = yes", "NOR = { hidden = { x = yes } }"]
)
def test_native_nor_rejects_invalid_or_unsupported_descendants(text):
    with pytest.raises(pdx_eval.UnsupportedPdxError):
        pdx_eval.condition(parse_text(text).root, {})


def query(name):
    return (("argument", name),)


def native_world():
    return {
        "owner": {
            "has_journal_entry": {
                query(name): False
                for name in (
                    "je_british_dictate_universities",
                    "je_taming_the_north",
                    "je_tp_pool_educational_reform",
                    "je_congress_poland",
                )
            },
            "has_variable": {
                query(name): False
                for name in (
                    "ai_ukraine_renaissance_accelerate",
                    "ai_belarus_renaissance_accelerate",
                    "ai_poland_white",
                    "poland_university_requirement_met_var",
                )
            },
            "country_innovation": 80,
            "max_innovation": 100,
        },
        "state_region": {
            "identity": "s:STATE_WEST_BENGAL",
            "is_homeland": {query("cu:ukrainian"): False, query("cu:byelorussian"): False},
        },
        "has_building": {query("building_university"): False},
        "any_scope_building": [],
    }


@pytest.mark.parametrize(
    ("case", "base"),
    [
        ("ordinary", 2000),
        ("british", 4000),
        ("british_existing", 2000),
        ("british_level", 2000),
        ("british_unknown", 2000),
        ("hokkaido", 12000),
        ("education", 4000),
        ("education_cap", 2000),
        ("education_unknown", 2000),
        ("ukrainian", 3000),
        ("byelorussian", 3000),
        ("poland", 3000),
        ("poland_complete", 2000),
        ("combined", 14000),
    ],
)
def test_complete_university_native_tail_and_owned_multiplier(generated, case, base):
    _model, policies, texts, inputs = generated
    policy = policies[GOV]
    world = native_world()
    owner = world["owner"]
    if case.startswith("british"):
        owner["has_journal_entry"][query("je_british_dictate_universities")] = True
        if case == "british_existing":
            world["has_building"][query("building_university")] = True
        elif case == "british_level":
            world["any_scope_building"] = [
                {"is_building_type": {query("building_university"): True}, "level": 4}
            ]
        elif case == "british_unknown":
            world["has_building"][query("building_university")] = None
    if case in {"hokkaido", "combined"}:
        owner["has_journal_entry"][query("je_taming_the_north")] = True
        world["state_region"]["identity"] = "s:STATE_HOKKAIDO"
    if case.startswith("education") or case == "combined":
        owner["has_journal_entry"][query("je_tp_pool_educational_reform")] = True
        if case == "education_cap":
            owner["max_innovation"] = 80
        elif case == "education_unknown":
            owner["max_innovation"] = None
    if case in {"ukrainian", "byelorussian"}:
        variable = (
            "ai_ukraine_renaissance_accelerate"
            if case == "ukrainian"
            else "ai_belarus_renaissance_accelerate"
        )
        owner["has_variable"][query(variable)] = True
        world["state_region"]["is_homeland"][query(f"cu:{case}")] = True
    if case.startswith("poland"):
        world["has_building"][query("building_university")] = True
        owner["has_variable"][query("ai_poland_white")] = True
        owner["has_journal_entry"][query("je_congress_poland")] = True
        owner["has_variable"][query("poland_university_requirement_met_var")] = (
            case == "poland_complete"
        )

    values: dict[str, object] = {
        "state_owner_innovation": 80,
        "state_owner_innovation_cap": 100,
        "state_owner_literacy": 0.8,
        "state_owner_default": False,
        "state_owner_academia_completed": False,
        "state_owner_paper_balance": 0,
        "state_owner_paper_price": 0,
        "pm_active_building_university_pm_scholastic_education": False,
        "pm_active_building_university_pm_philosophy_department": False,
        "pm_active_building_university_pm_analytical_philosophy_department": False,
    }
    for ai in (True, False):
        root = deepcopy(world)
        observed = _facts(policy, values, is_ai=ai)["ROOT"]
        for key, value in observed["owner"].items():
            if isinstance(value, dict) and isinstance(root["owner"].get(key), dict):
                root["owner"][key].update(value)
            else:
                root["owner"][key] = value
        facts = {**root, "ROOT": root}
        for text, expected in ((inputs[GOV], base), (texts[GOV], base * (1.1 if ai else 1))):
            parent = parse_text(text).root.first("building_university")
            assert parent is not None
            assert isinstance(parent.value, Block)
            field = parent.value.first("ai_value")
            assert field is not None
            assert pdx_eval._numeric_value(field, facts) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("region", "expected"),
    [
        ({"identity": "s:STATE_HOKKAIDO"}, True),
        ({"identity": "s:STATE_BOMBAY"}, False),
        ({}, None),
        ({"identity": None}, None),
    ],
)
def test_state_region_identity_is_local_and_never_replaced_by_root_decoy(region, expected):
    block = parse_text("state_region = s:STATE_HOKKAIDO").root
    facts = {"state_region": region, "ROOT": {"state_region": {"identity": "s:STATE_HOKKAIDO"}}}
    assert pdx_eval.condition(block, facts) is expected


@pytest.mark.parametrize("identity", [True, 1, {}, "country:JAP"])
def test_state_region_wrong_identity_type_is_not_an_unknown(identity):
    with pytest.raises(pdx_eval.UnsupportedPdxError, match="identity"):
        pdx_eval.condition(
            parse_text("state_region = s:STATE_HOKKAIDO").root,
            {"state_region": {"identity": identity}},
        )


def test_state_region_homeland_and_exact_innovation_rhs_keep_current_object():
    block = parse_text("state_region = { is_homeland = cu:ukrainian }").root
    query = (("argument", "cu:ukrainian"),)
    facts = {
        "state_region": {"is_homeland": {query: False}},
        "ROOT": {"state_region": {"is_homeland": {query: True}}},
    }
    assert pdx_eval.condition(block, facts) is False
    block = parse_text("owner = { country_innovation < max_innovation }").root
    assert (
        pdx_eval.condition(
            block, {"owner": {"country_innovation": 80, "max_innovation": 100}, "max_innovation": 0}
        )
        is True
    )
    assert (
        pdx_eval.condition(block, {"owner": {"country_innovation": 80}, "max_innovation": 100})
        is None
    )
