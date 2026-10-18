"""生产链契约：实际隶属、规模和负产出不能由词袋或假配方替代。"""

from __future__ import annotations

import pytest

from pdx import production_inputs


@pytest.fixture
def inputs():
    return {
        "common/buildings/example.txt": "building_example = { production_method_groups = { group_a group_b } }",
        "common/production_method_groups/example.txt": "group_a = { production_methods = { pm_a } } group_b = { production_methods = { pm_b } }",
        "common/production_methods/example.txt": "pm_a = { building_modifiers = { workforce_scaled = { goods_input_tools_add = 5 goods_output_coal_add = 20 } } } pm_b = { building_modifiers = { level_scaled = { goods_output_coal_add = -3 } } }",
    }


def test_actual_membership_recipe_scaling_and_signed_output_are_retained(inputs):
    result = production_inputs.recipes(
        inputs,
        [("building_example", "pm_b"), ("building_example", "pm_a"), ("building_example", "pm_a")],
    )
    assert [(row["method"], row["group"]) for row in result] == [
        ("pm_a", "group_a"),
        ("pm_b", "group_b"),
    ]
    assert [
        (item["kind"], item["good"], item["quantity"], item["scaling"])
        for item in result[0]["goods"]
    ] == [("input", "tools", 5, "workforce_scaled"), ("output", "coal", 20, "workforce_scaled")]
    assert result[1]["goods"][0]["quantity"] == -3
    assert result[1]["goods"][0]["scaling"] == "level_scaled"
    assert production_inputs.recipes({}, []) == []


@pytest.mark.parametrize(
    ("source", "before", "after"),
    [
        ("buildings", "group_a group_b", "group_a missing_group"),
        ("production_method_groups", "{ pm_a }", "{ pm_b }"),
        ("production_method_groups", "{ pm_b }", "{ pm_a pm_b }"),
        ("production_method_groups", "{ pm_a }", "{ fake = pm_a }"),
        ("production_method_groups", "{ pm_a }", "{ pm_a pm_a }"),
        ("buildings", "group_a group_b", "group_a group_a"),
        ("production_methods", "goods_input_tools_add = 5", "goods_input_tools_add = @unknown"),
        (
            "production_methods",
            "goods_input_tools_add = 5",
            "goods_input_tools_add = { value = 5 }",
        ),
        ("production_methods", "goods_input_tools_add = 5", "goods_input_tools_add = inf"),
        ("production_methods", "pm_b = {", "pm_a = {"),
    ],
)
def test_invalid_or_unrelated_recipe_is_rejected(inputs, source, before, after):
    name = f"common/{source}/example.txt"
    inputs[name] = inputs[name].replace(before, after)
    with pytest.raises(ValueError, match="生产"):
        production_inputs.recipes(inputs, [("building_example", "pm_a")])


@pytest.mark.parametrize("pair", [("missing", "pm_a"), ("building_example", "missing")])
def test_missing_locked_definitions_do_not_create_fake_consumers(inputs, pair):
    with pytest.raises(ValueError, match="锁定定义"):
        production_inputs.recipes(inputs, [pair])


def test_non_common_path_cannot_supply_production_definitions(inputs):
    text = inputs.pop("common/buildings/example.txt")
    inputs["events/buildings/example.txt"] = text
    with pytest.raises(ValueError, match="锁定定义"):
        production_inputs.recipes(inputs, [("building_example", "pm_a")])
