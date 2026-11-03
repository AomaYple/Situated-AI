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


@pytest.mark.parametrize(
    "expression",
    [
        "INJECT:flag = yes",
        "REPLACE:always = yes",
        "INJECT:exists = ROOT",
        "INJECT:ROOT = { always = yes }",
        "INJECT:law_stance = { law = law_type:law_anarchy value > neutral }",
        "law_stance = { law = law_type:law_anarchy INJECT:value > neutral }",
        "law_stance = { INJECT:law = law_type:law_anarchy value > neutral }",
        "law_stance = { law = law_type:law_anarchy law = law_type:law_anarchy value > neutral }",
        "law_stance = { law = law_type:law_anarchy value > neutral value > neutral }",
        "law_stance = { law = law_type:law_anarchy value > { neutral } }",
        "law_stance = { law = law_type:law_anarchy unexpected value > neutral }",
        "institution_investment_level = { institution = institution_police value > nan }",
        "flag != yes",
        "flag ?= yes",
        "any_scope_state = { INJECT:market_access < 1 }",
        "ROOT = { INJECT:flag = yes }",
        *[
            f"{prefix}{key} {operator} {{ always = yes }}"
            for key in ("AND", "OR", "NOT")
            for prefix, operator in (("INJECT:", "="), ("", "!="), ("", "?="))
        ],
    ],
)
@pytest.mark.parametrize("known", [False, True])
def test_unsupported_condition_ast_is_rejected_even_when_observations_are_missing(
    expression, known
):
    facts = (
        {
            "flag": True,
            "ROOT": {"flag": True},
            "any_scope_state": [],
            "law_stance": {(("law", "law_type:law_anarchy"),): 1},
        }
        if known
        else {}
    )
    parsed = parse_text(expression)
    assert not parsed.errors
    with pytest.raises(pdx_eval.UnsupportedPdxError):
        pdx_eval.condition(parsed.root, facts)


@pytest.mark.parametrize(
    "body",
    [
        "INJECT:add = 1",
        "add != 1",
        "add = { value = 1 value = 2 }",
        "add = { INJECT:value = 1 }",
        "add = { value != 1 }",
        "add = { value = 1 unexpected }",
        "add = { value = 1 {} }",
        "add = { value = 1 INJECT:multiply = 2 }",
        "add = { value = 1 multiply != 2 }",
        "add = { value = 1 if != { limit = { always = yes } add = 2 } }",
        "add = { value = 1 if = { INJECT:limit = { always = yes } add = 2 } }",
        "add = { value = 1 if = { limit = { always = yes } limit = { always = no } add = 2 } }",
        "add = { value = 1 if = { limit = { always = no } INJECT:add = 2 } }",
        "add = { value = 1 if = { limit = { always = no } add = 2 } else = { limit = { always = no } add = 3 } }",
        "add = 1 limit = { always = no }",
        "add = 1 unexpected = 4",
    ],
)
def test_numeric_ast_and_duplicate_control_fields_fail_closed(body):
    text = "# ACTION strict [test];\nif = { limit = { always = yes } " + body + " }"
    with pytest.raises(pdx_eval.UnsupportedPdxError):
        pdx_eval.select(text, {})


@pytest.mark.parametrize(
    "text",
    [
        "INJECT:if = { limit = { always = yes } add = 1 }",
        "if != { limit = { always = yes } add = 1 }",
        "if = { INJECT:limit = { always = yes } add = 1 }",
        "if = { limit = { always = yes } add = 1 } unexpected",
        "if = { limit = { always = no } add = 1 } else = { limit = { always = no } add = 2 }",
        "if = { limit = { always = yes } add = 1 } else = { INJECT:multiply = 2 }",
    ],
)
def test_action_control_ast_cannot_discard_unsupported_syntax(text):
    with pytest.raises(pdx_eval.UnsupportedPdxError):
        pdx_eval.select("# ACTION strict [test];\n" + text, {})


def test_valid_optional_scope_unknown_and_repeated_numeric_operations_are_preserved():
    assert evaluate("ROOT ?= { flag = yes }", None) is None
    assert evaluate("ROOT = { flag = yes }", None) is False
    assert evaluate("ROOT ?= { flag = yes }", {}) is None
    assert evaluate("ROOT = { flag >= 1 flag <= 2 }", {"flag": 1}) is True
    text = """# ACTION strict [test];
if = { limit = { always = yes }
    add = { value = 1 add = 2 add = 3
        if = { limit = { missing = yes } add = 100 }
        if = { limit = { always = no } add = 100 }
        else_if = { limit = { always = yes } multiply = 2 }
        else = { add = 100 }
    }
}"""
    assert pdx_eval.select(text, {}).delta == 12


@pytest.mark.parametrize(("condition", "expected"), [("no", 1), ("yes", 7)])
def test_conditional_numeric_value_reset_obeys_source_order(condition, expected):
    text = (
        "# ACTION strict [test];\nif = { limit = { always = yes } "
        "add = { value = 1 if = { limit = { always = " + condition + " } value = 7 } } }"
    )
    result = pdx_eval.select(text, {})
    assert result.operation == "add"
    assert result.delta == expected
