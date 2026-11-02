"""Independent collection semantics and exact Reader contracts."""

import pytest

from pdx import decision_interfaces, decision_rules
from pdx.parser import parse_text
from pdx.situated import pdx_eval


def evaluate(expression, root, **decoys):
    parsed = parse_text(expression)
    assert not parsed.errors
    return pdx_eval.condition(parsed.root, {"ROOT": root, **decoys})


@pytest.mark.parametrize(
    ("candidates", "expected"),
    [
        (None, None),
        ([], False),
        ([{"market_access": 1}], False),
        ([{"market_access": 0.9}], False),
        ([{"market_access": 0.89}], True),
        ([{}], None),
        ([{"market_access": 1}, {}], None),
        ([{}, {"market_access": 0.5}], True),
    ],
)
def test_native_owned_state_existential_three_valued_logic(candidates, expected):
    body = "ROOT = { any_scope_state = { market_access < 0.9 } }"
    root = {"any_scope_state": candidates}
    assert evaluate(body, root, any_scope_state=[{"market_access": 0}]) is expected
    inverse = "ROOT = { NOT = { any_scope_state = { market_access < 0.9 } } }"
    assert evaluate(inverse, root) is (None if expected is None else not expected)


@pytest.mark.parametrize("bad", [True, False, {}, 1, "yes", [True], [None]])
def test_collection_rejects_precomputed_bool_or_wrong_objects(bad):
    with pytest.raises(pdx_eval.UnsupportedPdxError, match="完整对象列表"):
        evaluate("ROOT = { any_scope_state = { market_access < 1 } }", {"any_scope_state": bad})


def test_building_conditions_must_match_one_owned_object():
    def building(kind, method, level):
        return {
            "is_building_type": {(("argument", kind),): True},
            "has_active_production_method": {(("argument", method),): True},
            "level": level,
        }

    expression = """ROOT = { any_scope_building = {
        is_building_type = building_art_academy
        has_active_production_method = pm_traditional_art level >= 2
    } }"""
    correct = building("building_art_academy", "pm_traditional_art", 2)
    assert evaluate(expression, {"any_scope_building": [correct]}) is True
    assert evaluate(expression, {"any_scope_building": []}, any_scope_building=[correct]) is False
    # Split evidence cannot be pooled into an imaginary matching building.
    wrong = [
        building("building_art_academy", "pm_film_art", 2),
        building("building_paper_mills", "pm_traditional_art", 2),
    ]
    assert evaluate(expression, {"any_scope_building": wrong}) is None
    for candidate in wrong:
        candidate["is_building_type"].setdefault((("argument", "building_art_academy"),), False)
        candidate["has_active_production_method"].setdefault(
            (("argument", "pm_traditional_art"),), False
        )
    assert evaluate(expression, {"any_scope_building": wrong}) is False


@pytest.mark.parametrize(
    ("stance", "support", "expected"),
    [(1, 0.1, True), (0, 0.2, False), (-1, 0.9, False), (1, 0.09, False), (None, 0.2, None)],
)
def test_law_stance_and_support_belong_to_same_real_movement(stance, support, expected):
    expression = """ROOT = { any_political_movement = {
       law_enactment_stance = { law = law_type:law_free_trade value > neutral }
       political_movement_support >= 0.10
    } }"""
    movement = {
        "law_enactment_stance": {(("law", "law_type:law_free_trade"),): stance},
        "political_movement_support": support,
    }
    assert evaluate(expression, {"any_political_movement": [movement]}) is expected


@pytest.mark.parametrize(
    ("engine", "parameters"),
    [
        ("any_scope_state", {"threshold": ".9"}),
        ("any_scope_state", {"threshold": "NaN"}),
        ("any_scope_state", {"threshold": "0.9", "country": "root"}),
        ("any_political_movement", {"law": "law_free_trade"}),
        (
            "any_scope_building",
            {"building": "building_art_academy", "method": "pm_nonexistent", "min_level": "1"},
        ),
    ],
)
def test_query_parameters_are_not_arbitrary_native_script(engine, parameters):
    reader = decision_rules.Reader(
        "query", engine, "root", "boolean", "boolean", parameters=tuple(parameters.items())
    )
    with pytest.raises(ValueError):
        decision_interfaces.reader_scope(reader, ())


@pytest.mark.parametrize(
    "change",
    [
        {"scope": "target_country"},
        {"path": ("owner",)},
        {"unit": "ratio"},
        {"kind": "number"},
        {"minimum": 0},
        {"argument": "root"},
        {"value_field": "value"},
    ],
)
def test_query_cannot_borrow_another_country_or_numeric_signature(change):
    reader = decision_rules.Reader(
        **{
            "key": "query",
            "engine": "any_scope_state",
            "scope": "root",
            "unit": "boolean",
            "kind": "boolean",
            "parameters": (("threshold", "0.9"),),
            **change,
        }
    )
    with pytest.raises(ValueError):
        decision_interfaces.reader_scope(reader, ())


@pytest.mark.parametrize(("stance", "expected"), [(1, True), (0, False), (-1, False), (None, None)])
def test_interest_group_actual_law_stance_is_not_movement_or_current_law_preference(
    stance, expected
):
    expression = """ROOT = { any_interest_group = {
        law_stance = { law = law_type:law_anarchy value > neutral }
    } }"""
    identity = (("law", "law_type:law_anarchy"),)
    group = {"law_stance": {identity: stance}, "law_enactment_stance": {identity: 1}}
    assert evaluate(expression, {"any_interest_group": [group]}) is expected
    assert evaluate(expression, {"any_interest_group": []}, any_interest_group=[group]) is False
    assert evaluate(expression, {"any_interest_group": None}, any_interest_group=[group]) is None
