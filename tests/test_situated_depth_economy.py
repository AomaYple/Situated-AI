"""D6 经济域静态合同：覆盖、回退、并行和局部关系边界。"""

import re
import tomllib

import pytest

from pdx import config, country_state, decision_adapters, decision_rules
from pdx.situated import pdx_eval
from pdx.situated.compiler import load_model
from pdx.situated.domain_coverage import CHAINS, contract, load
from pdx.situated.families import FAMILIES

pytestmark = pytest.mark.unit

ECONOMY_DOMAINS = frozenset(
    {"fiscal", "administrative", "industry", "resources", "market", "research", "education"}
)


def _instances():
    return load_model().action_instances


def test_economy_domains_have_static_base_contract_and_all_chain_nodes():
    model = load_model()
    coverage = load()
    assert set(FAMILIES) >= ECONOMY_DOMAINS
    rows = [item for item in model.action_instances if item.family_id in ECONOMY_DOMAINS]
    assert {item.family_id for item in rows} == ECONOMY_DOMAINS
    assert all(coverage[name].production_instances > 0 for name in ECONOMY_DOMAINS)
    assert all(item.value != 0 for item in rows)
    assert all(item.vanilla_tail.startswith("retain_") for item in rows)
    chain_rows = [chain for chain in CHAINS if set(chain.domain_ids) & ECONOMY_DOMAINS]
    assert chain_rows
    assert all(
        any(item.family_id == domain for item in _instances())
        for chain in chain_rows
        for domain in chain.domain_ids
    )


def test_economy_unknown_policy_preserves_vanilla_and_does_not_become_false():
    model = load_model()
    coverage = load()
    assert all(coverage[name].unknown_policy == "vanilla" for name in ECONOMY_DOMAINS)
    assert all(fact.unknown == "vanilla" for fact in model.facts)
    assert model.contract()["unknown_fallback"] == "vanilla"
    assert model.contract()["behavior_quality"] != "verified"


def test_economy_domains_are_parallel_static_writers_with_no_cross_domain_output_dependency():
    rows = [item for item in _instances() if item.family_id in ECONOMY_DOMAINS]
    ids = {item.action_id for item in rows}
    assert len(ids) == len(rows)
    assert all(not set(item.condition_facts) & ids for item in rows)
    assert {item.kind for item in rows} <= {"rule_action", "action_card"}
    summary = contract(load(), _instances())
    assert all(
        summary["domains"][name]["declared_instances"]
        == summary["domains"][name]["actual_instances"]
        for name in ECONOMY_DOMAINS
    )


def test_economy_local_relation_boundary_keeps_target_state_fields_explicit():
    model = load_model()
    target_rows = [
        item
        for item in model.action_instances
        if item.family_id in ECONOMY_DOMAINS and item.target_scope != "none"
    ]
    assert {
        (item.rule_id, item.family_id, item.consumer_field, item.target_scope)
        for item in target_rows
    } == {("market_access_state_value", "market", "state_value", "target_state")}
    assert all(
        fact.scope in {"root", "target_country", "target_state", "interest_group", "overlord"}
        for fact in model.facts
    )


def _government_adapter_data():
    return tomllib.loads(decision_adapters.SOURCE.read_text(encoding="utf-8"))


def _government_policy():
    return dict(decision_adapters.load().policies)["common/buildings/07_government.txt"]


def _government_values(policy):
    return {reader.key: False if reader.kind == "boolean" else 0 for reader in policy.readers}


@pytest.fixture(scope="module")
def government_generated_text():
    files, _ = decision_adapters.build(
        decision_adapters.load(),
        enabled_domains=frozenset({"economy", "fiscal"}),
        country_policy=country_state.load(),
    )
    return files["common/buildings/07_government.txt"]


@pytest.mark.parametrize(
    ("bureaucracy", "default", "loans", "expected"),
    [
        (-1, False, False, ("administrative_government_building_bureaucracy_repair", 1.25)),
        (-1, False, True, ("administrative_government_building_borrowed_repair", 1.10)),
        (-1, True, False, ("administrative_government_building_emergency_repair", 1.05)),
        (-1, True, True, ("administrative_government_building_emergency_repair", 1.05)),
        (0, False, False, None),
        (1, False, False, None),
        (0, False, True, ("fiscal_government_building_loans_downgrade", 0.75)),
        (0, True, False, ("fiscal_government_building_default_downgrade", 0.75)),
        (1, True, True, ("fiscal_government_building_default_downgrade", 0.75)),
        (-1, None, False, None),
        (-1, False, None, None),
        (None, False, False, None),
    ],
)
def test_government_local_repair_has_handwritten_cost_and_exit_witnesses(
    bureaucracy, default, loans, expected
):
    policy = _government_policy()
    values = _government_values(policy)
    values.update(
        state_owner_bureaucracy=bureaucracy,
        state_owner_default=default,
        state_owner_loans=loans,
    )
    actual = decision_rules.evaluate(policy, values, is_ai=True)
    assert actual.get("building_government_administration.ai_value") == expected
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}


@pytest.mark.integration
@pytest.mark.parametrize(
    ("bureaucracy", "default", "loans", "expected"),
    [
        (-0.001, False, False, ("administrative_government_building_bureaucracy_repair", 1.25)),
        (-1, False, True, ("administrative_government_building_borrowed_repair", 1.10)),
        (-1, True, False, ("administrative_government_building_emergency_repair", 1.05)),
        (-1, True, True, ("administrative_government_building_emergency_repair", 1.05)),
        (0, False, False, None),
        (0.001, False, False, None),
        (0, False, True, ("fiscal_government_building_loans_downgrade", 0.75)),
        (0, True, False, ("fiscal_government_building_default_downgrade", 0.75)),
        (-1, None, False, None),
        (-1, False, None, None),
        (None, False, False, None),
    ],
)
def test_government_actual_pdx_has_repair_cost_exit_and_unknown_witnesses(
    government_generated_text, bureaucracy, default, loans, expected
):
    overlay = _government_scoped_pdx_overlay(government_generated_text)
    facts = {
        "is_ai": True,
        "bureaucracy": bureaucracy,
        "in_default": default,
        "taking_loans": loans,
    }
    scoped = {"ROOT": {"owner": facts}}
    actual = pdx_eval.select(overlay, scoped)
    if expected is None:
        assert actual.fallback in {"vanilla", "unknown"}
        assert actual.operation is None
        assert actual.delta == 0
    else:
        assert (actual.action_id, actual.delta) == expected
        assert actual.operation == "multiply"
    assert (
        pdx_eval.select(overlay, {"ROOT": {"owner": {**facts, "is_ai": False}}}).fallback
        == "vanilla"
    )


def _government_scoped_pdx_overlay(text):
    start = text.index("# SITAI BEGIN information:building_government_administration.ai_value")
    end = text.index("# SITAI END information:building_government_administration.ai_value")
    result: list[str] = []
    for line in text[start:end].splitlines()[1:]:
        if "multiply = 1.0 }" in line:
            result.append(f"# government_unknown_guard_{len(result)} [generated];")
        result.append(line)
    return "\n".join(result) + "\n"


@pytest.mark.integration
def test_government_owner_boundary_is_evaluated_without_removing_production_scope(
    government_generated_text,
):
    overlay = _government_scoped_pdx_overlay(government_generated_text)
    actor = {"is_ai": True, "bureaucracy": -1, "in_default": True, "taking_loans": True}
    for missing in (None, {"owner": None}):
        assert pdx_eval.select(overlay, {"ROOT": missing, **actor}).fallback in {
            "vanilla",
            "unknown",
        }
    for bureaucracy in (-1, 0, -1):
        owner = {**actor, "bureaucracy": bureaucracy}
        result = pdx_eval.select(overlay, {"ROOT": {"owner": owner}, "bureaucracy": 100})
        assert result.delta == (1.05 if bureaucracy < 0 else 0.75)


@pytest.mark.integration
def test_government_administration_has_native_initial_value_and_production_reference():
    data = _government_adapter_data()
    initial = [
        item
        for item in data["initial_values"]
        if item["field"] == "building_government_administration.ai_value"
    ]
    assert initial == [
        {
            "source": "common/buildings/07_government.txt",
            "field": "building_government_administration.ai_value",
            "define_source": "common/defines/00_ai.txt",
            "define": "NAI.GOVERNMENT_BUILDING_BASE_VALUE",
        }
    ]
    source = (config.GAME / "common/buildings/07_government.txt").read_text(encoding="utf-8-sig")
    assert "building_government_administration = {" in source
    assert "production_method_groups = {" in source
    assert "required_construction = construction_cost_very_low" in source
    assert "unlocking_technologies = {" in source


def test_government_administration_rules_are_local_and_split_for_fiscal_crisis():
    data = _government_adapter_data()
    rules = [
        rule
        for rule in data["rules"]
        if rule["source"] == "common/buildings/07_government.txt"
        and rule["field"] == "building_government_administration.ai_value"
    ]
    by_id = {rule["id"]: rule for rule in rules}
    assert {
        "administrative_government_building_bureaucracy_repair",
        "fiscal_government_building_default_downgrade",
        "fiscal_government_building_loans_downgrade",
    } <= by_id.keys()
    assert by_id["administrative_government_building_bureaucracy_repair"]["domain"] == "economy"
    assert by_id["administrative_government_building_bureaucracy_repair"]["conditions"] == [
        {"fact": "state_owner_bureaucracy", "op": "<", "value": 0}
    ]
    assert by_id["administrative_government_building_bureaucracy_repair"]["operation"] == "multiply"
    assert by_id["administrative_government_building_bureaucracy_repair"]["value"] > 1
    for identifier, fact in (
        ("fiscal_government_building_default_downgrade", "state_owner_default"),
        ("fiscal_government_building_loans_downgrade", "state_owner_loans"),
    ):
        assert by_id[identifier]["domain"] == "fiscal"
        assert by_id[identifier]["conditions"] == [{"fact": fact, "op": "=", "value": True}]
        assert 0.5 <= by_id[identifier]["value"] < 1


@pytest.mark.parametrize(
    ("change", "selected"),
    [
        ({"state_owner_bureaucracy": -1}, "administrative_government_building_bureaucracy_repair"),
        ({"state_owner_default": True}, "fiscal_government_building_default_downgrade"),
        ({"state_owner_loans": True}, "fiscal_government_building_loans_downgrade"),
    ],
)
def test_government_administration_handwritten_positive_boundaries(change, selected):
    policy = _government_policy()
    values = _government_values(policy)
    values.update(change)
    result = decision_rules.evaluate(policy, values, is_ai=True)
    assert result["building_government_administration.ai_value"][0] == selected


@pytest.mark.parametrize(
    "change",
    [
        {"state_owner_bureaucracy": 0},
        {"state_owner_default": False, "state_owner_loans": False},
        {"state_owner_default": True, "state_owner_loans": True},
    ],
)
def test_government_administration_handwritten_negative_boundaries(change):
    policy = _government_policy()
    values = _government_values(policy)
    values.update(change)
    result = decision_rules.evaluate(policy, values, is_ai=True)
    if change == {"state_owner_default": True, "state_owner_loans": True}:
        assert result["building_government_administration.ai_value"][0] in {
            "fiscal_government_building_default_downgrade",
            "fiscal_government_building_loans_downgrade",
        }
    else:
        assert "building_government_administration.ai_value" not in result


def test_government_administration_unknown_and_player_paths_preserve_vanilla():
    policy = _government_policy()
    values = _government_values(policy)
    values["state_owner_bureaucracy"] = None
    values["state_owner_default"] = None
    values["state_owner_loans"] = None
    assert "building_government_administration.ai_value" not in decision_rules.evaluate(
        policy, values, is_ai=True
    )
    values.update(state_owner_bureaucracy=-1, state_owner_default=True, state_owner_loans=True)
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}


def _government_positive_pdx_overlay(text=None):
    """从生产生成物提取五条实际写分支供独立 PDX 求值器见证。

    生产 building 规则带有 owner/ROOT 作用域；这里仅去掉已由生成器验证的
    作用域壳，保留叶子条件、分支顺序和写值，避免把 Python 参考结果当作
    PDX 语义的替代。
    """
    if text is None:
        text = (config.REPO / "mod/common/buildings/07_government.txt").read_text(encoding="utf-8")
    lines = text.splitlines()
    ids = {
        "administrative_government_building_bureaucracy_repair",
        "administrative_government_building_borrowed_repair",
        "administrative_government_building_emergency_repair",
        "fiscal_government_building_default_downgrade",
        "fiscal_government_building_loans_downgrade",
    }
    result = []
    for index, line in enumerate(lines):
        marker = next((item for item in ids if f"# {item} [" in line), None)
        if marker is None:
            continue
        branch = lines[index + 1]
        branch = re.sub(
            r"exists = ROOT ROOT = \{ exists = owner owner = \{ (.*?) \} \} \} (?=multiply)",
            r"\1 } ",
            branch,
        )
        result.append(f"# {marker} [generated];\n{branch}")
    return "\n".join(result) + "\n"


@pytest.mark.parametrize(
    ("default", "loans", "selected", "multiplier"),
    [
        (False, False, "administrative_government_building_bureaucracy_repair", 1.25),
        (True, False, "administrative_government_building_emergency_repair", 1.05),
        (False, True, "administrative_government_building_borrowed_repair", 1.10),
        (True, True, "administrative_government_building_emergency_repair", 1.05),
    ],
)
@pytest.mark.parametrize("evaluator", ["reference", "generated_pdx"])
def test_government_administration_cost_scales_local_repair_in_reference_and_generated_pdx(
    default, loans, selected, multiplier, evaluator
):
    """违约优先于借贷且降低修复幅度；两者均不切断真实行政赤字修复。"""
    policy = _government_policy()
    values = _government_values(policy)
    values.update(state_owner_bureaucracy=-1, state_owner_default=default, state_owner_loans=loans)
    if evaluator == "reference":
        reference = decision_rules.evaluate(policy, values, is_ai=True)
        assert reference["building_government_administration.ai_value"] == (selected, multiplier)
    else:
        facts = {"is_ai": True, "bureaucracy": -1, "in_default": default, "taking_loans": loans}
        generated = pdx_eval.select(_government_positive_pdx_overlay(), facts)
        assert (generated.action_id, generated.operation, generated.delta, generated.fallback) == (
            selected,
            "multiply",
            multiplier,
            "selected",
        )


@pytest.mark.integration
def test_government_frozen_branches_match_locked_vanilla_regeneration():
    files, _ = decision_adapters.build(
        decision_adapters.load(),
        enabled_domains=frozenset({"economy", "fiscal"}),
        country_policy=country_state.load(),
    )
    assert _government_positive_pdx_overlay(files["common/buildings/07_government.txt"]) == (
        _government_positive_pdx_overlay()
    )


@pytest.mark.integration
def test_government_administration_generation_keeps_cost_and_vanilla_tail():
    adapters = decision_adapters.load()
    files, _ = decision_adapters.build(
        adapters,
        enabled_domains=frozenset({"economy", "fiscal"}),
        country_policy=country_state.load(),
    )
    generated = files["common/buildings/07_government.txt"]
    assert "ai_value = { value = 1000" in generated
    assert "# SITAI BEGIN information:building_government_administration.ai_value" in generated
    assert "is_ai = yes" in generated
    for fragment in (
        "unlocking_technologies = {",
        "should_auto_expand = {",
        "production_method_groups = {",
        "required_construction = construction_cost_very_low",
        'background = "gfx/interface/icons/building_icons/backgrounds/building_panel_bg_monuments.dds"',
    ):
        assert fragment in generated
