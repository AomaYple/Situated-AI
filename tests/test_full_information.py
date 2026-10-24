"""声明规则须进入真实标准包，并与独立生成脚本解释保持一致。"""

from __future__ import annotations

import codecs
import copy
import hashlib
import json
import math
import operator
import re
import tomllib
import zipfile
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pdx import (
    config,
    decision_adapters,
    decision_intents,
    decision_rules,
    decisions,
    distribution,
    information_catalog,
)
from pdx.consumer_matrix import ConsumerMatrix
from pdx.model import Block, Scalar
from pdx.parser import parse_text

if TYPE_CHECKING:
    from pathlib import Path


# 合成语义测试的附加token，仅允许独立解释生成条件，不作为真实本体依据。
# 真实依据另由integration用例对全部锁定原件核对SHA与接口签名。
_SYNTHETIC_READER_EVIDENCE = (
    "bureaucracy taking_loans scaled_debt net_total_income legitimacy "
    "has_insurrectionary_interest_groups has_variable recently_lost_war"
)


@pytest.mark.parametrize("excess", ["candidates", "field_predicates", "rule_predicates"])
def test_configuration_growth_cannot_bypass_static_runtime_budget(excess):
    data = tomllib.loads(decision_rules.SOURCE.read_text(encoding="utf-8"))
    first = data["rules"][0]
    count = 33 if excess == "candidates" else 28 if excess == "field_predicates" else 1
    predicates = 17 if excess == "rule_predicates" else 6 if excess == "field_predicates" else 1
    for index in range(count):
        data["rules"].append(
            {
                **first,
                "id": f"budget_{index}",
                "priority": 1000 + index,
                "conditions": [
                    {"fact": "income", "op": ">=", "value": value} for value in range(predicates)
                ],
            }
        )
    with pytest.raises(ValueError, match="复杂度预算"):
        decision_rules.from_data(data, source_sha256="a" * 64, strategy=decision_intents.load())


@pytest.fixture(scope="module")
def rules() -> decision_rules.RuleSet:
    return decision_rules.load()


@pytest.mark.integration
def test_shared_information_readers_have_sha_locked_native_evidence(rules):
    if not (config.GAME / "common/laws/readme.md").is_file():
        pytest.skip("需要锁定版本的游戏原件")
    inputs = decision_adapters.read_inputs(decision_adapters.load())
    evidence = decision_adapters.reader_evidence(inputs)
    assert all(reader.engine in evidence for reader in rules.readers)
    baseline = decisions.BASELINE.read_text(encoding="utf-8")
    script = decision_rules.patch(
        baseline, rules, baseline=baseline, reader_words=frozenset(evidence)
    )
    assert "bureaucracy >= 0" in script
    assert "has_insurrectionary_interest_groups = no" in script


def _values(**overrides: object) -> dict[str, object]:
    return {
        "default": False,
        "war": False,
        "war_defeat": False,
        "population": 3000000,
        "income": 5000,
        "net_surplus": 100,
        "debt_ratio": 0.1,
        "loans": False,
        "bureaucracy": 100,
        "legitimacy": 60,
        "insurrection": False,
        "navy": 50,
        "subject": False,
        "industrial_route": True,
        "resource_route": False,
        "expansion_route": False,
        "artillery_tech": True,
        "target_port": False,
        "fervor": 0,
        "target_homeland": False,
        "target_owned": False,
        "target_isolated": False,
        "target_cultural_share": 0,
        **overrides,
    }


def test_rules_have_real_readers_fields_priorities_and_no_invented_consumer(rules):
    source = tomllib.loads(decision_rules.SOURCE.read_text(encoding="utf-8"))
    assert {rule.id for rule in rules.rules} == {row["id"] for row in source["rules"]}
    assert {reader.key for reader in rules.readers} == set(source["readers"])
    assert {"state_value", "wanted_construction_output"} <= {
        ".".join(field) for field in rules.groups()
    }
    assert {rule.domain for rule in rules.rules} == {
        "political",
        "fiscal",
        "economy",
        "market",
        "diplomacy",
        "subjects",
        "military",
        "geography",
        "identity",
    }
    baseline = decisions.BASELINE.read_text(encoding="utf-8")
    script = decision_rules.patch(
        baseline, rules, baseline=baseline, reader_evidence=_SYNTHETIC_READER_EVIDENCE
    )
    assert not parse_text(script).errors
    assert not decisions.player_boundary_issues(script)
    for field in rules.groups():
        assert script.count(f"# SITAI BEGIN information:{'.'.join(field)}\n") == 1
    # 去除全部新增块后原版字节必须完全保留，包括注释、嵌套、空白。
    restored = re.sub(
        r"\n\t\t# SITAI BEGIN information:[^\n]+\n.*?# SITAI END information:[^\n]+\n\t",
        "",
        script,
        flags=re.DOTALL,
    )
    assert restored == baseline
    assert "ai_strategy_default" not in rules.groups()


def test_unknown_player_and_empty_switches_preserve_vanilla(rules):
    assert decision_rules.evaluate(rules, {}, is_ai=True) == {}
    assert decision_rules.evaluate(rules, _values(), is_ai=False) == {}
    assert decision_rules.evaluate(rules, _values(), is_ai=True, enabled_domains=frozenset()) == {}
    assert (
        decision_rules.evaluate(rules, _values(default=None), is_ai=True).get(
            "wanted_construction_output"
        )
        is None
    )
    baseline = decisions.BASELINE.read_text(encoding="utf-8")
    assert (
        decision_rules.patch(
            baseline,
            rules,
            baseline=baseline,
            enabled_domains=frozenset(),
            reader_evidence=_SYNTHETIC_READER_EVIDENCE,
        )
        == baseline
    )
    disabled = replace(rules, enabled_domains=frozenset())
    assert (
        decision_rules.patch(
            baseline, disabled, baseline=baseline, reader_evidence=_SYNTHETIC_READER_EVIDENCE
        )
        == baseline
    )
    assert decision_rules.contract(disabled)["active_rule_count"] == 0
    with pytest.raises(ValueError, match="布尔"):
        decision_rules.evaluate(rules, _values(), is_ai=cast("Any", None))


@pytest.mark.parametrize(
    "invalid",
    [None, "yes", [], float("nan"), float("inf"), pytest.param(10**1000, id="overflow-integer")],
)
def test_invalid_input_cannot_become_safe_or_zero(rules, invalid):
    result = decision_rules.evaluate(rules, _values(income=invalid), is_ai=True)
    assert "wanted_construction_output" not in result


def test_scope_range_and_domain_typos_do_not_trigger_actions(rules):
    result = decision_rules.evaluate(rules, _values(navy=-1, population=-10), is_ai=True)
    assert "colonial_interest_ratio" not in result
    assert "institution_scores.institution_schools" not in result
    with pytest.raises(ValueError, match="领域开关"):
        decision_rules.evaluate(rules, _values(), is_ai=True, enabled_domains=frozenset({"typo"}))


def test_single_line_nested_script_keeps_exact_bytes_and_float_precision(rules):
    baseline = 'ai_strategy_default = { icon = "brace}#" wanted_construction_output = { value = 1 if = { limit = { in_default = yes is_at_war = no } add = 0 } } }\n'
    rule = next(rule for rule in rules.rules if rule.id == "fiscal_construction_guard")
    rule = replace(rule, value=0.8765432109876543)
    selected = {condition.fact for condition in rule.conditions}
    policy = replace(
        rules,
        rules=(rule,),
        enabled_domains=frozenset({rule.domain}),
        readers=tuple(reader for reader in rules.readers if reader.key in selected),
        baseline_sha256=hashlib.sha256(baseline.encode()).hexdigest(),
    )
    generated = decision_rules.patch(
        baseline, policy, baseline=baseline, reader_evidence=_SYNTHETIC_READER_EVIDENCE
    )
    assert "multiply = 0.8765432109876543" in generated
    restored = re.sub(
        r"\n\t\t# SITAI BEGIN information:.*?# SITAI END information:[^\n]+\n\t",
        "",
        generated,
        flags=re.DOTALL,
    )
    assert restored == baseline


def test_priority_and_normal_defense_counterexamples(rules):
    peaceful = decision_rules.evaluate(rules, _values(default=True), is_ai=True)
    wartime = decision_rules.evaluate(rules, _values(default=True, war=True), is_ai=True)
    for field in ("wanted_army_size", "wanted_navy_size", "wanted_construction_output"):
        assert peaceful[field][1] < 1
        assert field not in wartime
    result = decision_rules.evaluate(rules, _values(resource_route=True), is_ai=True)
    assert result["treaty_category_scores.economy"] == ("identity_resource_cooperation", 1.15)
    assert "wanted_army_size" not in result
    only = decision_rules.evaluate(
        rules, _values(default=True), is_ai=True, enabled_domains=frozenset({"military"})
    )
    assert set(only) == {
        "wanted_army_size",
        "wanted_navy_size",
        "max_ship_design_complexity",
        "combat_unit_group_weights.combat_unit_group_artillery",
    }


def test_vanilla_war_defeat_signal_is_bounded_and_unknown_safe(rules):
    recovering = decision_rules.evaluate(rules, _values(war_defeat=True), is_ai=True)
    assert recovering["wanted_construction_output"] == ("war_defeat_reconstruction", 1.05)
    assert "change_law_chance" not in recovering

    ordinary = decision_rules.evaluate(rules, _values(war_defeat=False), is_ai=True)
    assert ordinary["wanted_construction_output"] == ("economic_development", 1.05)
    assert "change_law_chance" not in ordinary

    # 缺少该原版变量时不能把未知当作“没有战败”，也不能抢跑低优先级建设规则。
    unknown_values = _values()
    unknown_values.pop("war_defeat")
    unknown = decision_rules.evaluate(rules, unknown_values, is_ai=True)
    assert "wanted_construction_output" not in unknown
    assert "change_law_chance" not in unknown

    # 战争中所有建设倾向都回退原版；战争失败变量不绕过当前战争门槛。
    wartime = decision_rules.evaluate(rules, _values(war_defeat=True, war=True), is_ai=True)
    assert "wanted_construction_output" not in wartime


def _evaluate_script(block: Block, engine_values: dict[str, object]) -> float:
    """独立解释生成的有限语法；不调用规则参考实现或重新生成预期字符串。"""
    operations = {
        "=": operator.eq,
        "<": operator.lt,
        "<=": operator.le,
        ">": operator.gt,
        ">=": operator.ge,
    }

    def condition(node: Block, mode: str = "AND") -> bool:
        results = []
        for assignment in node.assignments():
            if assignment.key == "exists":
                assert isinstance(assignment.value, Scalar)
                name = assignment.value.unquoted
                results.append(name == "ROOT" or engine_values.get(name) is True)
                continue
            if isinstance(assignment.value, Block):
                if assignment.key == "primary_cultures_percent_state":
                    target = assignment.value.first("target_country")
                    comparison = assignment.value.first("value")
                    assert target is not None
                    assert isinstance(target.value, Scalar)
                    assert target.value.unquoted == "root"
                    assert comparison is not None
                    assert isinstance(comparison.value, Scalar)
                    share = engine_values.get(assignment.key)
                    results.append(
                        isinstance(share, (int, float))
                        and operations[comparison.op](share, float(comparison.value.text))
                    )
                    continue
                results.append(condition(assignment.value, assignment.key))
                continue
            assert isinstance(assignment.value, Scalar)
            raw = assignment.value.unquoted
            actual: object
            if assignment.key == "is_ai":
                actual = True
            elif assignment.key in {
                "has_strategy",
                "has_variable",
                "has_technology_researched",
                "owner",
                "is_homeland_of_country_cultures",
            }:
                actual = engine_values.get(assignment.key + ":" + raw)
                raw = "yes"
            else:
                actual = engine_values.get(assignment.key)
            expected: bool | float = (
                {"yes": True, "no": False}[raw] if raw in {"yes", "no"} else float(raw)
            )
            if actual is None:
                results.append(False)
                continue
            assert isinstance(actual, (bool, int, float))
            results.append(operations[assignment.op](actual, expected))
        if mode == "OR":
            return any(results)
        if mode == "NOT":
            return not all(results)
        return all(results)

    for branch in block.assignments():
        assert isinstance(branch.value, Block)
        limit = branch.value.first("limit")
        assert limit is not None
        assert isinstance(limit.value, Block)
        if condition(limit.value):
            value = branch.value.first("multiply")
            assert value is not None
            if isinstance(value.value, Block):
                assert value.value.first("desc") is not None
                value = value.value.first("value")
                assert value is not None
            assert isinstance(value.value, Scalar)
            return float(value.value.text)
    return 1.0


@given(
    default=st.booleans(),
    war=st.booleans(),
    income=st.integers(-100000, 100000),
    population=st.integers(0, 50000000),
    navy=st.integers(0, 300),
    resource=st.booleans(),
    subject=st.booleans(),
)
def test_generated_conditions_equal_reference_on_legal_inputs(
    generated_rule_blocks, default, war, income, population, navy, resource, subject
):
    rules, blocks = generated_rule_blocks
    values = _values(
        default=default,
        war=war,
        income=income,
        population=population,
        navy=navy,
        resource_route=resource,
        subject=subject,
    )
    engine = {
        (
            reader.engine + ":" + reader.argument if reader.argument is not None else reader.engine
        ): values[reader.key]
        for reader in rules.readers
    }
    engine["scope:target_state"] = True
    reference = decision_rules.evaluate(rules, values, is_ai=True)
    for field_name, block in blocks.items():
        value = _evaluate_script(block, engine)
        assert value == reference.get(field_name, ("vanilla", 1.0))[1]
        assert math.isfinite(value)
        assert 0.5 <= value <= 1.5


@pytest.mark.parametrize("navy", [-1, -100])
def test_invalid_high_priority_fact_stops_generated_lower_priority(generated_rule_blocks, navy):
    rules, blocks = generated_rule_blocks
    # 低优先级违约规则本来会匹配；非法的高优先级海军读数必须使其回退。
    values = _values(default=True, navy=navy)
    engine = {reader.engine: values[reader.key] for reader in rules.readers}
    assert "colonial_interest_ratio" not in decision_rules.evaluate(rules, values, is_ai=True)
    assert _evaluate_script(blocks["colonial_interest_ratio"], engine) == 1


@pytest.mark.parametrize("high_uses_target", [True, False])
def test_missing_scope_obeys_priority_without_blocking_known_false(rules, high_uses_target):
    baseline = decisions.BASELINE.read_text(encoding="utf-8")
    original = next(rule for rule in rules.rules if rule.id == "geographic_port_continuity")
    top = replace(original, field=("state_value",), priority=100, value=1.1)
    lower = replace(original, id="lower", priority=50, value=0.9)
    root_only = (decision_rules.Predicate("default", "=", True),)
    target_only = (decision_rules.Predicate("target_port", "=", True),)
    top = replace(top, conditions=target_only if high_uses_target else root_only)
    lower = replace(lower, conditions=root_only if high_uses_target else lower.conditions)
    policy = replace(rules, rules=(top, lower), enabled_domains=frozenset({"geography"}))
    text = decision_rules.patch(
        baseline, policy, baseline=baseline, reader_evidence=_SYNTHETIC_READER_EVIDENCE
    )
    match = re.search(r"# SITAI BEGIN information:state_value\n(.*?)# SITAI END", text, re.DOTALL)
    assert match is not None
    block = parse_text(match.group(1)).root
    engine: dict[str, object] = {"in_default": True}
    values = _values(default=True, target_port=None)
    expected = 1.0 if high_uses_target else 1.1
    assert _evaluate_script(block, engine) == expected
    assert (
        decision_rules.evaluate(policy, values, is_ai=True).get("state_value", ("", 1.0))[1]
        == expected
    )
    if high_uses_target:
        # 财政条件已知为假，足以排除高候选，不应将缺失目标当成全字段阻塞。
        top = replace(top, conditions=(*top.conditions, decision_rules.Predicate("war", "=", True)))
        changed = replace(policy, rules=(top, lower))
        text = decision_rules.patch(
            baseline, changed, baseline=baseline, reader_evidence=_SYNTHETIC_READER_EVIDENCE
        )
        match = re.search(
            r"# SITAI BEGIN information:state_value\n(.*?)# SITAI END", text, re.DOTALL
        )
        assert match is not None
        assert (
            _evaluate_script(parse_text(match.group(1)).root, {**engine, "is_at_war": False}) == 0.9
        )
        assert decision_rules.evaluate(changed, values, is_ai=True)["state_value"][1] == 0.9


@pytest.fixture(scope="module")
def generated_rule_blocks(rules):
    baseline = decisions.BASELINE.read_text(encoding="utf-8")
    generated = decision_rules.patch(
        baseline, rules, baseline=baseline, reader_evidence=_SYNTHETIC_READER_EVIDENCE
    )
    blocks = {}
    for field in rules.groups():
        field_name = ".".join(field)
        match = re.search(
            rf"# SITAI BEGIN information:{re.escape(field_name)}\n(.*?)# SITAI END information:",
            generated,
            flags=re.DOTALL,
        )
        assert match is not None
        blocks[field_name] = parse_text(match.group(1)).root
    return rules, blocks


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({}, 1.05),
        ({"target_owned": True}, 1.0),
        ({"target_homeland": False}, 1.0),
        ({"target_cultural_share": 0.24}, 1.0),
        ({"target_cultural_share": 1.1}, 1.0),
        ({"target_cultural_share": None}, 1.0),
        ({"target_isolated": True}, 1.0),
        ({"fervor": 10}, 1.0),
        ({"default": True}, 1.0),
        ({"war": True}, 1.0),
        ({"income": 0}, 1.0),
        ({"expansion_route": False}, 1.0),
    ],
)
def test_identity_reward_requires_cultural_and_material_feasibility(
    generated_rule_blocks, change, expected
):
    rules, blocks = generated_rule_blocks
    values = _values(
        **dict(
            {
                "target_homeland": True,
                "target_cultural_share": 0.5,
                "fervor": 15,
                "expansion_route": True,
            },
            **change,
        )
    )
    engine = {
        reader.engine + (":" + reader.argument if reader.argument else ""): values[reader.key]
        for reader in rules.readers
    }
    engine["scope:target_state"] = True
    assert _evaluate_script(blocks["state_value"], engine) == expected
    assert (
        decision_rules.evaluate(rules, values, is_ai=True).get("state_value", ("", 1.0))[1]
        == expected
    )
    assert decision_rules.evaluate(rules, values, is_ai=False) == {}


def test_geographic_cost_precedes_reward_and_missing_state_preserves_vanilla(
    generated_rule_blocks,
):
    rules, blocks = generated_rule_blocks
    values = _values(default=True, target_isolated=True, navy=0, target_port=True)
    engine = {
        reader.engine + (":" + reader.argument if reader.argument else ""): values[reader.key]
        for reader in rules.readers
    }
    engine["scope:target_state"] = True
    assert _evaluate_script(blocks["state_value"], engine) == 0.95
    assert decision_rules.evaluate(rules, values, is_ai=True)["state_value"] == (
        "geographic_isolation_financial_cost",
        0.95,
    )
    engine.pop("scope:target_state")
    assert _evaluate_script(blocks["state_value"], engine) == 1.0


def test_drift_bad_path_and_unproven_reader_refuse_generation(rules):
    baseline = decisions.BASELINE.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="漂移"):
        decision_rules.patch(baseline, rules, baseline=baseline + "\n")
    broken = replace(
        rules,
        rules=(replace(rules.rules[0], field=("missing",)),),
        enabled_domains=frozenset({rules.rules[0].domain}),
    )
    with pytest.raises(ValueError, match="消费者"):
        decision_rules.patch(
            baseline, broken, baseline=baseline, reader_evidence=_SYNTHETIC_READER_EVIDENCE
        )
    broken = replace(
        rules, readers=(replace(rules.readers[0], engine="invented_reader"), *rules.readers[1:])
    )
    with pytest.raises(ValueError, match="读取器"):
        decision_rules.patch(
            baseline, broken, baseline=baseline, reader_evidence=_SYNTHETIC_READER_EVIDENCE
        )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("schema = 1", "schema = true"),
        ('kind = "boolean"', 'kind = "integer"'),
        ('scope = "root"', 'scope = "world"'),
        ("political = true", "political = 1"),
        ('op = "="', 'op = "<"'),
        ("value = 0.85", "value = nan"),
        ("priority = 100", "priority = true"),
        ('field = "wanted_construction_output"', 'field = "bad/path"'),
        ('fact = "default"', 'fact = "missing"'),
        ('engine = "in_default"', 'engine = "in_default }"'),
    ],
)
def test_invalid_configuration_fails_closed(tmp_path, before, after):
    text = decision_rules.SOURCE.read_text(encoding="utf-8")
    assert before in text
    path = tmp_path / "invalid.toml"
    path.write_text(text.replace(before, after, 1), encoding="utf-8", newline="\n")
    with pytest.raises(ValueError):
        decision_rules.load(path, strategy=decision_intents.load())


@pytest.mark.parametrize("path", [["in_default"], ["market", "owner"], ["owner"]])
def test_known_words_cannot_be_recombined_into_invented_scopes(path):
    data = tomllib.loads(decision_rules.SOURCE.read_text(encoding="utf-8"))
    data["readers"]["default"]["path"] = path
    with pytest.raises(ValueError, match="作用域"):
        decision_rules.from_data(data, source_sha256="0" * 64, strategy=decision_intents.load())


def test_parent_and_child_fields_cannot_have_separate_authors():
    data = tomllib.loads(decision_rules.SOURCE.read_text(encoding="utf-8"))
    data["rules"][0]["field"] = "institution_scores"
    with pytest.raises(ValueError, match="父子字段"):
        decision_rules.from_data(data, source_sha256="0" * 64, strategy=decision_intents.load())


@pytest.mark.parametrize(
    "overrides",
    [
        {"value_field": "threshold"},
        {"value_field": ["value"]},
        {"value_field": "value", "kind": "boolean"},
        {"value_field": "value", "argument": "some_argument"},
    ],
)
def test_compound_number_reader_rejects_ambiguous_shapes(overrides):
    data = tomllib.loads(decision_rules.SOURCE.read_text(encoding="utf-8"))
    data = copy.deepcopy(data)
    data["readers"]["income"].update(overrides)
    with pytest.raises(ValueError, match="复合数值"):
        decision_rules.from_data(data, source_sha256="0" * 64, strategy=decision_intents.load())


@pytest.mark.parametrize(
    "parameters",
    [
        None,
        [],
        "value",
        {"production_method": "pm_test"},
        {"building_type": "building_test", "production_method": "pm_test }"},
    ],
)
def test_compound_boolean_reader_rejects_unsafe_parameters(parameters):
    data = tomllib.loads(decision_rules.SOURCE.read_text(encoding="utf-8"))
    data["readers"]["default"]["engine"] = "is_production_method_active"
    data["readers"]["default"]["parameters"] = parameters
    with pytest.raises(ValueError, match="复合布尔"):
        decision_rules.from_data(data, source_sha256="0" * 64, strategy=decision_intents.load())


@pytest.mark.parametrize(
    "contexts", [[], {"unused": []}, {"unused": [{"fact": "default", "op": "=", "value": True}]}]
)
def test_unconsumed_or_invalid_shared_constraint_fails_closed(contexts):
    data = tomllib.loads(decision_rules.SOURCE.read_text(encoding="utf-8"))
    data["contexts"] = contexts
    with pytest.raises(ValueError, match="共享约束"):
        decision_rules.from_data(data, source_sha256="0" * 64, strategy=decision_intents.load())


def test_shared_constraints_expand_into_real_fields_once(rules):
    data = tomllib.loads(decision_rules.SOURCE.read_text(encoding="utf-8"))
    selected = next(row for row in data["rules"] if row["id"] == "fiscal_construction_guard")
    conditions = copy.deepcopy(selected["conditions"])
    data["contexts"] = {"shared_fiscal_risk": conditions}
    selected["contexts"] = ["shared_fiscal_risk"]
    selected["conditions"] = conditions[:1]
    policy = decision_rules.from_data(
        data, source_sha256="0" * 64, strategy=decision_intents.load()
    )
    rule = next(row for row in policy.rules if row.id == selected["id"])
    assert len(rule.conditions) == len(conditions)
    assert rule.contexts == ("shared_fiscal_risk",)
    for default in (False, True):
        for war in (False, True):
            values = _values(default=default, war=war)
            assert decision_rules.evaluate(policy, values, is_ai=True) == decision_rules.evaluate(
                rules, values, is_ai=True
            )
    baseline = decisions.BASELINE.read_text(encoding="utf-8")
    assert decision_rules.patch(
        baseline, policy, baseline=baseline, reader_evidence=_SYNTHETIC_READER_EVIDENCE
    ) == decision_rules.patch(
        baseline, rules, baseline=baseline, reader_evidence=_SYNTHETIC_READER_EVIDENCE
    )


@pytest.mark.integration
@pytest.mark.skipif(
    not (config.GAME / "common/laws/readme.md").is_file(), reason="需要锁定版本的游戏原件"
)
def test_release_is_a_real_standard_package(tmp_path):
    path = distribution.package(tmp_path / "situated-ai-1.0.2.zip")
    _, _, engineering_files = distribution.package_inputs(include_engineering_metadata=True)
    assert all(
        not line.endswith((" ", "\t"))
        for name, text in engineering_files.items()
        if name.endswith((".txt", ".yml"))
        for line in text.splitlines()
    )
    engineering_metadata = json.loads(engineering_files[".metadata/metadata.json"])
    first = path.read_bytes()
    distribution.package(path)
    assert path.read_bytes() == first
    manifest = distribution.validate_package(path)
    contract = manifest["contract"]
    assert isinstance(contract, dict)
    generation = manifest["generation"]
    assert isinstance(generation, dict)
    assert generation["behavior_quality"] == "not_evaluated"
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        assert not any("probe" in name or name.startswith("gui/") for name in names)
        metadata = json.loads(archive.read(".metadata/metadata.json"))
        assert metadata["name"] == "Situated AI"
        assert metadata["id"] == distribution.MOD_ID == "situated-ai"
        assert set(metadata) == set(distribution.LAUNCHER_METADATA_KEYS)
        assert len(archive.read(".metadata/metadata.json")) < 2_000
        assert metadata["version"] == "1.0.2"
        assert contract["status"] == "candidate"
        assert contract["behavior_quality"] == "not_evaluated"
        assert engineering_metadata["decision_rules"]["behavior_verified"] is False
        assert engineering_metadata["consumer_adapters"]["behavior_verified"] is False
        assert engineering_metadata["default_field_owners"]["subject_value"] == "consumer_adapters"
        assert (
            engineering_metadata["default_field_owners"]["become_subject_value"]
            == "consumer_adapters"
        )
        assert "subjects" not in contract["enabled_modules"]
        assert b"# SITAI SUBJECTS BEGIN" not in archive.read(
            "common/ai_strategies/00_default_strategy.txt"
        )
        assert contract["consumer_count"] == 38
        assert "information_rules" in contract["enabled_modules"]
        strategy = archive.read("common/ai_strategies/00_default_strategy.txt")
        assert strategy.startswith(codecs.BOM_UTF8)
        assert b"\r" not in strategy
        fleet_value = archive.read("common/script_values/sitai_adapter_values.txt")
        assert fleet_value.startswith(codecs.BOM_UTF8)
        assert b"\r" not in fleet_value
        assert b"protect_supply = sitai_adapter_fleet_supply_weight" in strategy
        assert b"sitai_adapter_fleet_supply_weight = {" in fleet_value
        declared_fields = set(engineering_metadata["decision_rules"]["field_owners"])
        default_contract = next(
            row
            for row in engineering_metadata["consumer_adapters"]["consumers"]
            if row["source"] == "common/ai_strategies/00_default_strategy.txt"
        )
        declared_fields.update(default_contract["field_owners"])
        actual_fields = {
            name.decode().removeprefix("ai_strategy_default.")
            for name in re.findall(
                rb"# SITAI BEGIN information:([^\n]+)", strategy + b"\n" + fleet_value
            )
        }
        assert actual_fields == {
            name.removeprefix("ai_strategy_default.") for name in declared_fields
        }
        assert len([name for name in names if name.startswith("localization/")]) == 11
        explanation_keys = {
            row["description_key"]
            for row in engineering_metadata["decision_rules"]["rules"]
            if row["description_key"] is not None
        }
        assert explanation_keys
        for name in names:
            if name.startswith("localization/"):
                localization = archive.read(name).decode("utf-8-sig")
                for key in explanation_keys:
                    assert f" {key}:" in localization, (name, key)


def test_static_matrix_never_claims_execution_contract(tmp_path: Path):
    item = information_catalog.InformationItem(
        id="one",
        domain="test",
        name="one",
        source="fixture",
        source_sha256="a" * 64,
        source_line=1,
        consumers=("ai_strategy:x:field",),
    )
    catalog = information_catalog.InformationCatalog(version={}, roots={}, items=(item,))
    matrix = ConsumerMatrix.from_catalog(catalog)
    assert matrix.mappings[0].merge == "unresolved_static_association"
    assert matrix.mappings[0].behavior_verified is False
    path = tmp_path / "matrix.json"
    matrix.write(path)
    assert not path.read_bytes().startswith(codecs.BOM_UTF8)
    assert b"\r" not in path.read_bytes()
    assert (
        json.loads(path.read_text(encoding="utf-8"))["evidence"] == "static_name_associations_only"
    )
