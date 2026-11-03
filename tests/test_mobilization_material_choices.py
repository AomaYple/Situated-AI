"""付费动员逐候选材料权衡；预期直接取原版投入和手算增量。"""

from __future__ import annotations

import pytest

from pdx import mobilization_opportunities as mobilization

pytestmark = pytest.mark.unit

# 基础补给没有效用；强行军是无物料的特质开关；航空侦察的效用路由未证。
NATIVE_ONLY = {
    "mobilization_option_basic_supplies",
    "mobilization_option_forced_march",
    "mobilization_option_aerial_recon",
}
MATERIALS = {
    "extra_supplies": {"groceries": "1.5"},
    "luxurious_supplies": {"meat": "1.5", "wine": "1.5"},
    "chocolate": {"sugar": "1"},
    "tobacco": {"tobacco": "0.5"},
    "liquor": {"liquor": "0.5"},
    "opium": {"opium": "0.5"},
    "truck_transport": {"automobiles": "0.5"},
    "rail_transport": {"engines": "0.5"},
    "machinegunners": {"small_arms": "1", "ammunition": "1"},
    "chemical_weapons": {"fertilizer": "2"},
    "flamethrowers": {"oil": "1"},
    "motorized_recon": {"automobiles": "1", "oil": "0.5"},
    "balloon_recon": {"fabric": "2", "oil": "0.5"},
    "first_aid": {"fabric": "1", "liquor": "2"},
    "field_hospitals": {"opium": "2", "tools": "1"},
}


def test_each_paid_choice_has_exact_direct_inputs_and_original_utility_evidence():
    frozen = mobilization.load_baseline()
    candidates = mobilization.candidate_catalog(frozen)
    assert set(candidates) == {f"mobilization_option_{name}" for name in MATERIALS}
    assert set(frozen["native_identities"]) - candidates.keys() == NATIVE_ONLY
    for short, goods in MATERIALS.items():
        row = candidates[f"mobilization_option_{short}"]
        assert row["goods"] == goods
        assert row["field"] == f"mobilization_option_{short}.ai_weight"
        assert row["goods_unit"] == "native_modifier_quantity_coefficient_not_purchase_or_currency"
        assert row["utility_evidence"]
    # 原证据仍只有已冻结的两个医疗候选，新增能力不改历史资料。
    assert len(frozen["candidates"]) == 2


def test_existing_medical_and_new_material_rules_share_one_joint_program_contract():
    result = mobilization.derive({"sources": {}, "readers": {}, "rules": []})
    assert {row["id"] for row in result["uncovered"]} == NATIVE_ONLY
    for short, goods in MATERIALS.items():
        field = f"mobilization_option_{short}.ai_weight"
        rules = [row for row in result["rules"] if row["field"] == field]
        assert len(rules) == 2 + 2 * len(goods)
        for rule in rules:
            assert rule["operation"] == "multiply"
            assert rule["contribution_group"]
            if short not in {"first_aid", "field_hospitals"}:
                assert rule["required_known_facts"] == ["mobilization_owner_ai"]
        # 缺少与某一编制无关的坦克/无线电组成数据，不创造材料全满足门。
        assert not any(
            condition["fact"] in {"mobilization_tanks_balance", "mobilization_radios_balance"}
            for rule in rules
            for condition in rule["conditions"]
        )
