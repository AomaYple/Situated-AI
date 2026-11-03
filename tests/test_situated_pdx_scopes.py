"""独立 AST 求值必须保留实际 actor/target 与存在性，不能扁平化。"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

import pytest

from pdx.situated.pdx_eval import UnsupportedPdxError, select

pytestmark = pytest.mark.unit

OVERLAY = """# ACTION scoped_repair [test];
if = { limit = {
    exists = ROOT ROOT = { exists = owner owner = { is_ai = yes bureaucracy < 0 } }
} multiply = 1.05 }
"""


def test_actual_owner_uses_its_values_instead_of_root_or_current_target():
    facts = {
        "is_ai": False,
        "bureaucracy": 20,
        "owner": {"is_ai": False, "bureaucracy": 15},
        "ROOT": {"owner": {"is_ai": True, "bureaucracy": -1}},
    }
    selected = select(OVERLAY, facts)
    assert (selected.action_id, selected.operation, selected.delta) == (
        "scoped_repair",
        "multiply",
        1.05,
    )


@pytest.mark.parametrize("root", [None, {"owner": None}])
def test_explicit_missing_owner_cannot_reuse_flat_healthy_data(root):
    assert select(OVERLAY, {"ROOT": root, "is_ai": True, "bureaucracy": -1}).fallback == "vanilla"


def test_missing_scope_is_unknown_and_does_not_silently_become_current_scope():
    assert select(OVERLAY, {"is_ai": True, "bureaucracy": -1}).fallback == "unknown"


@pytest.mark.parametrize("owner", [None, 0, True, "country"])
@pytest.mark.parametrize("body", ["always = yes", "", "ROOT = { is_ai = yes }"])
def test_absent_or_invalid_scope_cannot_select_scope_independent_body(owner, body):
    text = f"# ACTION a [test];\nif = {{ limit = {{ owner = {{ {body} }} }} add = 1 }}"
    facts = {"ROOT": {"is_ai": True}, "owner": owner}
    if owner is None:
        assert select(text, facts).fallback == "vanilla"
    else:
        with pytest.raises(UnsupportedPdxError, match="作用域"):
            select(text, facts)


@pytest.mark.parametrize("body", ["always = yes", "", "ROOT = { is_ai = yes }"])
def test_unobserved_scope_never_selects_even_with_constant_body(body):
    text = f"# ACTION a [test];\nif = {{ limit = {{ owner = {{ {body} }} }} add = 1 }}"
    assert select(text, {"ROOT": {"is_ai": True}}).fallback == "unknown"


def test_root_exists_and_root_lookup_are_invariant_under_logical_grouping():
    prefix = "# ACTION a [test];\nif = { limit = { "
    suffix = " } add = 1 }"
    plain = prefix + "OR = { exists = ROOT ROOT = { is_ai = yes } }" + suffix
    grouped = prefix + "OR = { exists = ROOT AND = { ROOT = { is_ai = yes } } }" + suffix
    cases: tuple[tuple[Mapping[str, object | None], str], ...] = (
        ({"is_ai": True}, "selected"),
        ({"ROOT": {"is_ai": True}}, "selected"),
        ({"ROOT": None, "is_ai": True}, "vanilla"),
    )
    for facts, expected in cases:
        assert select(plain, facts).fallback == expected
        assert select(grouped, facts).fallback == expected


def test_explicit_empty_root_does_not_prove_owner_absence():
    assert select(OVERLAY, {"ROOT": {}}).fallback == "unknown"


def test_missing_optional_scope_does_not_assert_unproven_engine_null_semantics():
    text = "# ACTION a [test];\nif = { limit = { owner ?= { always = yes } } add = 1 }"
    assert select(text, {"owner": None}).fallback == "unknown"


def test_scoped_owner_core_unknown_remains_unknown():
    assert select(OVERLAY, {"ROOT": {"owner": {"is_ai": True}}}).fallback == "unknown"


def test_optional_root_scope_supports_production_overlay_without_flattening_explicit_actor():
    optional = OVERLAY.replace("ROOT = {", "ROOT ?= {")
    assert select(optional, {"ROOT": {"owner": {"is_ai": True, "bureaucracy": -1}}}).delta == 1.05
    assert select(optional, {"ROOT": None, "is_ai": True, "bureaucracy": -1}).fallback == "vanilla"


def test_switching_root_owner_has_no_cross_target_state():
    for value, expected in [(-1, "selected"), (0, "vanilla"), (-1, "selected")]:
        facts = {"ROOT": {"owner": {"is_ai": True, "bureaucracy": value}}}
        assert select(OVERLAY, facts).fallback == expected


def test_unregistered_scope_block_still_fails_loudly():
    with pytest.raises(UnsupportedPdxError, match="未登记"):
        select("# ACTION a [test];\nif = { limit = { hidden_scope = { a = yes } } add = 1 }", {})


def test_game_constant_always_is_literal_not_an_input_fact():
    text = "# ACTION a [test];\nif = { limit = { always = no } add = 1 }"
    assert select(text, {"always": True}).fallback == "vanilla"


def test_exists_unregistered_scalar_is_not_assumed_true():
    text = "# ACTION a [test];\nif = { limit = { exists = mystery } add = 1 }"
    with pytest.raises(UnsupportedPdxError, match="未登记"):
        select(text, {"mystery": {}})


def _query_overlay(expression):
    return f"# ACTION query [test];\nif = {{ limit = {{ {expression} }} add = 1 }}"


@pytest.mark.parametrize(
    ("value", "expected"), [(True, "selected"), (False, "vanilla"), (None, "unknown")]
)
def test_technology_parameter_preserves_target_truth_and_unknown(value, expected):
    facts = {
        "has_technology_researched": {
            (("argument", "academia"),): value,
            (("argument", "mechanical_tools"),): True,
        }
    }
    assert (
        select(_query_overlay("has_technology_researched = academia"), facts).fallback == expected
    )


def test_technology_query_does_not_use_another_target_or_country():
    expression = "ROOT = { owner = { has_technology_researched = academia } }"
    data = {
        "has_technology_researched": {(("argument", "academia"),): True},
        "ROOT": {
            "owner": {"has_technology_researched": {(("argument", "mechanical_tools"),): True}}
        },
    }
    assert select(_query_overlay(expression), data).fallback == "unknown"


@pytest.mark.parametrize(
    ("expression", "identity"),
    [
        ("has_treaty_alliance_with = { TARGET = root }", (("TARGET", "root"),)),
        (
            "has_diplomatic_pact = { type = embargo who = root }",
            (("type", "embargo"), ("who", "root")),
        ),
    ],
)
@pytest.mark.parametrize(
    ("value", "expected"), [(True, "selected"), (False, "vanilla"), (None, "unknown")]
)
def test_boolean_parameter_blocks_preserve_identity(expression, identity, value, expected):
    name = expression.split(" = ", 1)[0]
    facts = {name: {identity: value, (("TARGET", "other"),): True}}
    assert select(_query_overlay(expression), facts).fallback == expected
    assert select(_query_overlay(expression), {name: {}}).fallback == "unknown"


@pytest.mark.parametrize(
    ("value", "expected"), [(True, "selected"), (False, "vanilla"), (None, "unknown")]
)
def test_actual_production_method_is_keyed_by_both_building_and_method(value, expected):
    expression = "is_production_method_active = { building_type = building_tooling_workshop production_method = pm_pig_iron }"
    data = {"is_production_method_active": {"building_tooling_workshop": {"pm_pig_iron": value}}}
    assert select(_query_overlay(expression), data).fallback == expected


def test_missing_parameter_queries_and_wrong_target_remain_unknown():
    expression = "is_production_method_active = { production_method = pm_pig_iron building_type = building_tooling_workshop }"
    cases: tuple[dict[str, object], ...] = (
        {},
        {"is_production_method_active": {"other_building": {"pm_pig_iron": True}}},
        {"is_production_method_active": {"building_tooling_workshop": {}}},
        {"is_production_method_active": {"building_tooling_workshop": None}},
    )
    for data in cases:
        assert select(_query_overlay(expression), data).fallback == "unknown"


@pytest.mark.parametrize(
    "expression",
    [
        "has_technology_researched > academia",
        "has_technology_researched = { technology = academia }",
        "has_technology_researched = yes",
        "has_treaty_alliance_with = { target = root }",
        "has_treaty_alliance_with = { TARGET = root extra = yes }",
        "has_treaty_alliance_with = { TARGET = root TARGET = other }",
        "has_diplomatic_pact = { who = root }",
        "has_diplomatic_pact = { who = root type = embargo extra = yes }",
        "is_production_method_active = pm_pig_iron",
        "is_production_method_active = { building_type = building_tooling_workshop }",
        "is_production_method_active = { building_type = building_tooling_workshop production_method = pm_pig_iron extra = yes }",
        "is_production_method_active = { building_type = building_tooling_workshop building_type = other production_method = pm_pig_iron }",
        "is_production_method_active = { building_type > building_tooling_workshop production_method = pm_pig_iron }",
        "is_production_method_active = { building_type = { value = building_tooling_workshop } production_method = pm_pig_iron }",
        "is_production_method_active = { building_type = building_tooling_workshop production_method = pm_pig_iron stray }",
        "is_production_method_active = { building_type = building_tooling_workshop production_method = pm_pig_iron value = 1 }",
        "pop_type_percent_country = laborers",
        "pop_type_percent_country = { pop_type = laborers value >= 0.2 }",
        "pop_type_percent_country = { pop_type = laborers percent >= 0.2 extra = yes }",
        "pop_type_percent_country = { pop_type = laborers }",
        "pop_type_percent_country = { pop_type = laborers percent >= invalid }",
    ],
)
def test_parameter_query_rejects_unsupported_syntax(expression):
    with pytest.raises(UnsupportedPdxError, match=r"参数|查询|未登记|数值"):
        select(_query_overlay(expression), {})


@pytest.mark.parametrize("value", [True, 0, "yes", [], {"building_tooling_workshop": True}])
def test_production_method_query_rejects_untyped_fixture(value):
    expression = "is_production_method_active = { building_type = building_tooling_workshop production_method = pm_pig_iron }"
    with pytest.raises(UnsupportedPdxError, match=r"参数|查询|未登记|观测|映射"):
        select(_query_overlay(expression), {"is_production_method_active": value})
