"""多消费者补丁：合成离线反例、属性测试和原件逐字保留契约。"""

from __future__ import annotations

import hashlib
import math
import operator
import re
import tomllib
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from typing import TYPE_CHECKING

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from pdx import (
    config,
    country_state,
    decision_adapters,
    decision_intents,
    decision_rules,
    decisions,
    version_contracts,
)
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.textio import normalized_text

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.integration
@pytest.mark.skipif(
    not (config.GAME / "common/laws/readme.md").is_file(), reason="需要锁定版本的游戏原件"
)
def test_current_native_authority_recapture_reproduces_reviewed_bytes_twice(tmp_path, monkeypatch):
    """Exercise the explicit writer against live sources, keeping frozen evidence untouched."""
    reviewed = decision_adapters.NATIVE_AUTHORITY_115.read_bytes()
    assert hashlib.sha256(reviewed).hexdigest() == decision_adapters.NATIVE_AUTHORITY_115_SHA256
    destination = tmp_path / "authority" / "native-authority.json"
    monkeypatch.setattr(decision_adapters, "NATIVE_AUTHORITY_115", destination)
    with version_contracts.select_version("1.15.0"):
        assert decision_adapters.write_native_authority_115(config.GAME) == destination
        first = destination.read_bytes()
        assert first == reviewed
        assert decision_adapters.write_native_authority_115(config.GAME) == destination
        assert destination.read_bytes() == first
        assert decision_adapters.native_authority_115()["game_version"] == "1.15.0"


@pytest.mark.integration
@pytest.mark.skipif(
    not (config.GAME / "common/laws/readme.md").is_file(), reason="需要锁定版本的游戏原件"
)
def test_current_native_authority_recapture_rejects_existing_drift_without_overwriting(
    tmp_path, monkeypatch
):
    reviewed = decision_adapters.NATIVE_AUTHORITY_115.read_bytes()
    destination = tmp_path / "native-authority.json"
    damaged = reviewed + b"\n"
    destination.write_bytes(damaged)
    sentinel = tmp_path / "keep.txt"
    sentinel.write_bytes(b"existing evidence must survive")
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    monkeypatch.setattr(decision_adapters, "NATIVE_AUTHORITY_115", destination)
    with (
        version_contracts.select_version("1.15.0"),
        pytest.raises(ValueError, match="frozen declaration drift"),
    ):
        decision_adapters.write_native_authority_115(config.GAME)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


@pytest.mark.integration
@pytest.mark.skipif(
    not (config.GAME / "common/laws/readme.md").is_file(), reason="需要锁定版本的游戏原件"
)
def test_actual_input_pressure_and_output_use_opposite_joint_groups():
    """投入和产出都必须进入联合程序，不用优先级屏蔽另一方向。"""
    from pdx.situated import programs

    adapters = decision_adapters.load()
    checked = 0
    for source, policy in adapters.policies:
        by_field: dict[tuple[str, ...], dict[str, list[str]]] = {}
        for rule in policy.rules:
            if rule.id.startswith(("actual_cost_", "actual_output_")):
                by_field.setdefault(rule.field, {"cost": [], "output": []})[
                    "cost" if rule.id.startswith("actual_cost_") else "output"
                ].append(rule.id)
        compiled = programs.enable(policy, source=source)
        for field, groups in by_field.items():
            if groups["cost"] and groups["output"]:
                checked += 1
                program = next(p for p in compiled.consumer_programs if p.field == field)
                positive = {
                    v.action_id for g in program.groups if g.direction > 0 for v in g.variants
                }
                negative = {
                    v.action_id for g in program.groups if g.direction < 0 for v in g.variants
                }
                assert set(groups["cost"]) <= negative
                assert set(groups["output"]) <= positive
    # University now has a knowledge-demand consumer, rather than an ordinary
    # market-output recipe. Eleven remaining recipe consumers have both sides.
    assert checked == 11


def test_one_low_priority_input_rule_still_enters_joint_program(tmp_path, monkeypatch):
    from pdx.situated import programs

    text = decision_adapters.SOURCE.read_text(encoding="utf-8")
    changed, count = re.subn(
        r'(id = "actual_cost_building_iron_mine_[^\n]+\n(?:[^\n]*\n){3}priority = )\d+',
        r"\g<1>1",
        text,
        count=1,
    )
    assert count == 1
    source = tmp_path / "adapters.toml"
    source.write_text(changed, encoding="utf-8")
    monkeypatch.setattr(decision_adapters, "SOURCE", source)
    adapters = decision_adapters.load(source, strategy=decision_intents.load())
    policy = dict(adapters.policies)["common/buildings/03_mines.txt"]
    compiled = programs.enable(policy, source="common/buildings/03_mines.txt")
    program = next(
        p for p in compiled.consumer_programs if p.field == ("building_iron_mine", "ai_value")
    )
    selected = [v for g in program.groups if g.direction < 0 for v in g.variants if v.priority == 1]
    assert len(selected) == 1
    assert selected[0].action_id.startswith("actual_cost_building_iron_mine_")
    assert selected[0].value == 0.8


@pytest.mark.integration
def test_friendly_overlord_need_retains_relation_and_prices_candidate_war():
    from pdx.situated import programs

    policy = dict(decision_adapters.load().policies)["common/ai_strategies/00_default_strategy.txt"]
    policy = programs.enable(policy, source="common/ai_strategies/00_default_strategy.txt")
    rule = next(rule for rule in policy.rules if rule.id == "remaining_friendly_overlord_strong")
    values = {
        reader.key: False if reader.kind == "boolean" else max(0, reader.minimum or 0)
        for reader in policy.readers
    }
    values.update(
        default=True,
        war=False,
        candidate_overlord_war=False,
        prospective_overlord_population=100_000,
        overlord_relations=80,
    )
    field = "ai_strategy_default.become_subject_value"
    selected = decision_rules.evaluate(policy, values, is_ai=True)[field]
    assert selected[0].startswith("program_")
    assert selected[1] == rule.value == 3
    assert decision_rules.evaluate(policy, {**values, "war": True}, is_ai=True)[field] == selected
    assert (
        decision_rules.evaluate(policy, {**values, "candidate_overlord_war": True}, is_ai=True)[
            field
        ][1]
        == -2
    )
    assert (
        decision_rules.evaluate(policy, {**values, "overlord_relations": None}, is_ai=True).get(
            field
        )
        is None
    )


@pytest.mark.integration
def test_colonial_financing_and_relationship_costs_join_without_duplicate_friendship():
    from pdx.situated import programs

    policy = dict(decision_adapters.load().policies)["common/ai_strategies/00_default_strategy.txt"]
    policy = programs.enable(policy, source="common/ai_strategies/00_default_strategy.txt")
    values = {
        reader.key: False if reader.kind == "boolean" else max(0, reader.minimum or 0)
        for reader in policy.readers
    }
    field = "ai_strategy_default.wargoal_scores.colonization_rights"
    values.update(
        war=False,
        default=False,
        loans=True,
        debt_ratio=0.5,
        bankruptcy_horizon=10,
        prospective_subject_population=100_000,
        target_relations=75,
        target_truce=True,
        target_alliance=True,
    )
    result = decision_rules.evaluate(policy, values, is_ai=True)
    assert result[field][0].startswith("program_")
    assert result[field][1] == -8  # Short liquidity -4 plus strongest relationship -4.
    recovered = decision_rules.evaluate(policy, {**values, "default": True}, is_ai=True)
    assert recovered[field][1] == -7  # Default -3 replaces the same financing cause.


@pytest.mark.integration
def test_actual_subject_political_crisis_cost_remains_visible_during_war():
    from pdx.situated import programs

    policy = dict(decision_adapters.load().policies)["common/ai_strategies/00_default_strategy.txt"]
    policy = programs.enable(policy, source="common/ai_strategies/00_default_strategy.txt")
    values = {
        reader.key: False if reader.kind == "boolean" else max(0, reader.minimum or 0)
        for reader in policy.readers
    }
    values.update(
        war=False,
        legitimacy=20,
        insurrection=True,
        radical_share=0.3,
        prospective_subject_population=100_000,
        candidate_existing_subject=True,
    )
    field = "ai_strategy_default.wargoal_scores.reduce_autonomy"
    selected = decision_rules.evaluate(policy, values, is_ai=True)[field]
    assert selected[0].startswith("program_")
    assert selected[1] == -2
    wartime = decision_rules.evaluate(policy, {**values, "war": True}, is_ai=True)
    assert wartime[field] == selected
    unrelated = decision_rules.evaluate(
        policy, {**values, "candidate_existing_subject": False}, is_ai=True
    )
    assert unrelated.get(field) is None


@pytest.mark.integration
def test_critical_diplomatic_rules_match_generated_script():
    from test_remaining_joint_consumers import _overlay
    from test_situated_joint_witnesses import _facts

    from pdx.situated import compiler, pdx_eval

    source = "common/ai_strategies/00_default_strategy.txt"
    adapters = decision_adapters.load()
    model = compiler.load_model()
    policy, _ = compiler.compile_policy(dict(adapters.policies)[source], source, model)
    adapter_subset = replace(
        adapters,
        policies=((source, policy),),
        supply=None,
        initial_values=tuple(row for row in adapters.initial_values if row.source == source),
        scalar_values=tuple(row for row in adapters.scalar_values if row[0] == source),
    )
    files, _ = decision_adapters.build(
        adapter_subset, country_policy=country_state.load(), consumer_ir=model.consumer_ir
    )
    base = {
        reader.key: False if reader.kind == "boolean" else max(0, reader.minimum or 0)
        for reader in policy.readers
    }
    cases = [
        (
            "ai_strategy_default.become_subject_value",
            {
                **base,
                "default": True,
                "war": False,
                "candidate_overlord_war": False,
                "prospective_overlord_population": 100_000,
                "overlord_relations": 80,
            },
            "add",
            3,
        ),
        (
            "ai_strategy_default.wargoal_scores.colonization_rights",
            {
                **base,
                "default": True,
                "war": False,
                "prospective_subject_population": 100_000,
                "target_truce": True,
            },
            "add",
            -7,
        ),
    ]
    for field, values, operation, expected in cases:
        selected = decision_rules.evaluate(policy, values, is_ai=True).get(field)
        assert selected is not None
        assert selected[0].startswith("program_")
        assert selected[1] == expected
        actual = pdx_eval.select(_overlay(files[source], field), _facts(policy, values))
        assert (actual.operation, actual.delta) == (operation, expected)


@pytest.mark.integration
@pytest.mark.skipif(
    not (config.GAME / "common/laws/readme.md").is_file(), reason="需要锁定版本的游戏原件"
)
def test_urban_research_population_need_is_not_a_development_payment_gate():
    adapters = decision_adapters.load()
    policy = dict(adapters.policies)["common/technology/technologies/30_society.txt"]
    values = {
        "population": 3_000_000,
        "literacy": 0.4,
        "bureaucracy": 100,
        "net_surplus": 100,
        "default": False,
        "war": False,
    }
    result = decision_rules.evaluate(policy, values, is_ai=True)
    assert result["urbanization.ai_weight"] == ("situational_urbanization_research", 1.1)
    for key, value in (
        ("war", True),
        ("default", True),
        ("bureaucracy", -1),
        ("net_surplus", -1),
        ("literacy", None),
    ):
        assert decision_rules.evaluate(policy, {**values, key: value}, is_ai=True)[
            "urbanization.ai_weight"
        ] == ("situational_urbanization_research", 1.1)
    for population in (None, 1_999_999):
        assert "urbanization.ai_weight" not in decision_rules.evaluate(
            policy, {**values, "population": population}, is_ai=True
        )


_NAME = "common/laws/synthetic.txt"
_BASELINE = """# 合成输入，绝非冻结游戏证据
law_example = {
    can_enact = { bureaucracy >= 0 }
    ai_will_do = { is_at_war = no }
    ai_enact_weight_modifier = { value = 0 }
    modifier = { imaginary = 123 }
}
"""


def _synthetic() -> decision_adapters.AdapterSet:
    raw = {
        "schema": 1,
        "baseline_sha256": hashlib.sha256(_BASELINE.encode()).hexdigest(),
        "domains": {"political": True},
        "readers": {
            "capacity": {
                "engine": "bureaucracy",
                "scope": "root",
                "unit": "capacity_balance",
                "kind": "number",
            },
            "war": {"engine": "is_at_war", "scope": "root", "unit": "boolean", "kind": "boolean"},
        },
        "rules": [
            {
                "id": "funded_reform",
                "domain": "political",
                "field": "law_example.ai_enact_weight_modifier",
                "priority": 50,
                "operation": "add",
                "value": 15,
                "conditions": [
                    {"fact": "capacity", "op": ">=", "value": 0},
                    {"fact": "war", "op": "=", "value": False},
                ],
                "why": "合成能力条件",
                "counterexample": "不绕过原版资格",
            }
        ],
    }
    policy = decision_rules.from_data(raw, source_sha256="0" * 64)
    return decision_adapters.AdapterSet(
        ((_NAME, policy.baseline_sha256),), ((_NAME, policy),), "0" * 64
    )


@pytest.fixture(scope="module")
def synthetic_patch():
    adapters = _synthetic()
    files, contract = decision_adapters.build(adapters, texts={_NAME: _BASELINE})
    parsed = parse_text(files[_NAME])
    assert not parsed.errors
    law = parsed.top_assignments[0].value
    assert isinstance(law, Block)
    field = law.first("ai_enact_weight_modifier")
    assert field is not None
    assert isinstance(field.value, Block)
    return adapters, files, contract, field.value


def test_addition_uses_actual_consumer_and_preserves_every_other_byte(synthetic_patch):
    _, files, contract, field = synthetic_patch
    assert field.first("if") is not None
    restored = re.sub(
        r"\n\t\t# SITAI BEGIN information:[^\n]+\n.*?# SITAI END information:[^\n]+\n\t",
        "",
        files[_NAME],
        flags=re.DOTALL,
    )
    assert restored == _BASELINE
    assert contract["behavior_verified"] is False
    assert contract["runtime_state"] == "none"
    assert contract["sources"] == {_NAME: hashlib.sha256(_BASELINE.encode()).hexdigest()}


def _law_score(field: Block, *, capacity: int, war: bool, is_ai: bool) -> float:
    """仅解释合成产物的语法，不调用规则参考函数。"""

    def matches(block):
        for item in block.assignments():
            if item.key == "exists":
                assert item.value.unquoted == "ROOT"
            elif isinstance(item.value, Block):
                assert item.key == "ROOT"
                if not matches(item.value):
                    return False
            else:
                assert isinstance(item.value, Scalar)
                text = item.value.unquoted
                if item.key == "bureaucracy":
                    assert item.op == ">="
                    if capacity < float(text):
                        return False
                elif item.key == "is_at_war":
                    if war != (text == "yes"):
                        return False
                elif item.key == "is_ai":
                    if is_ai != (text == "yes"):
                        return False
                else:
                    pytest.fail(f"未登记的合成语法：{item.key}")
        return True

    result = 0.0
    for item in field.assignments():
        if item.key == "value":
            assert isinstance(item.value, Scalar)
            result = float(item.value.unquoted)
        elif item.key == "if":
            assert isinstance(item.value, Block)
            limit = item.value.first("limit")
            addition = item.value.first("add")
            assert limit is not None
            assert addition is not None
            assert isinstance(limit.value, Block)
            assert isinstance(addition.value, Scalar)
            if matches(limit.value):
                result += float(addition.value.unquoted)
        else:
            pytest.fail(f"意外修改：{item.key}")
    return result


@given(capacity=st.integers(-100000, 100000), war=st.booleans(), is_ai=st.booleans())
def test_law_generated_ast_equals_independent_condition_and_reference(
    synthetic_patch, capacity, war, is_ai
):
    adapters, _, _, field = synthetic_patch
    score = _law_score(field, capacity=capacity, war=war, is_ai=is_ai)
    assert score == (15 if is_ai and not war and capacity >= 0 else 0)
    reference = decision_rules.evaluate(
        adapters.policies[0][1], {"capacity": capacity, "war": war}, is_ai=is_ai
    )
    assert score == reference.get("law_example.ai_enact_weight_modifier", ("vanilla", 0))[1]


def test_missing_drift_and_unknown_switch_fail_before_any_generation(tmp_path):
    adapters = _synthetic()
    for texts in ({}, {_NAME: _BASELINE + "\n"}):
        with pytest.raises(ValueError, match=r"缺少|漂移"):
            decision_adapters.build(adapters, texts=texts)
    with pytest.raises(ValueError, match="缺少"):
        decision_adapters.build(adapters, game=tmp_path)
    with pytest.raises(ValueError, match="未知"):
        decision_adapters.build(
            adapters, texts={_NAME: _BASELINE}, enabled_domains=frozenset({"typo"})
        )
    files, contract = decision_adapters.build(
        adapters, texts={_NAME: _BASELINE}, enabled_domains=frozenset()
    )
    assert files == {}
    assert contract["consumers"] == []


def test_nested_market_path_requires_scopes_and_real_goods_evidence():
    adapters = _synthetic()
    policy = adapters.policies[0][1]
    policy = replace(
        policy,
        readers=(
            decision_rules.Reader(
                "price",
                "market_goods_pricier",
                "root",
                "price_above_base_ratio",
                "number",
                path=("market", "mg:grain"),
            ),
        ),
        rules=(
            replace(policy.rules[0], conditions=(decision_rules.Predicate("price", ">", 0.25),)),
        ),
    )
    adapters = replace(adapters, policies=((_NAME, policy),))
    # The vocabulary evidence is explicit synthetic script data, not a runtime claim.
    evidence = "market = { mg:grain = { market_goods_pricier > 0.25 } }"
    generated = decision_rules.patch(
        _BASELINE, policy, baseline=_BASELINE, default_strategy=False, reader_evidence=evidence
    )
    assert "exists = market market = { exists = mg:grain mg:grain = {" in generated
    with pytest.raises(ValueError, match="读取器"):
        decision_rules.patch(_BASELINE, policy, baseline=_BASELINE, default_strategy=False)


@pytest.fixture(scope="module")
def state_candidate():
    baseline = "building_example = { ai_value = { value = 100 } }\n"
    policy = decision_rules.from_data(
        {
            "schema": 1,
            "baseline_sha256": hashlib.sha256(baseline.encode()).hexdigest(),
            "actor_path": ["owner"],
            "domains": {"economy": True},
            "readers": {
                "infrastructure": {
                    "engine": "infrastructure_delta",
                    "scope": "root",
                    "unit": "infrastructure_points",
                    "kind": "number",
                },
                "default": {
                    "engine": "in_default",
                    "scope": "root",
                    "path": ["owner"],
                    "unit": "boolean",
                    "kind": "boolean",
                },
                "cost": {
                    "engine": "market_goods_pricier",
                    "scope": "root",
                    "path": ["owner", "market", "mg:coal"],
                    "unit": "price_above_base_ratio",
                    "kind": "number",
                },
            },
            "rules": [
                {
                    "id": "repair",
                    "domain": "economy",
                    "field": "building_example.ai_value",
                    "priority": 50,
                    "value": 1.2,
                    "conditions": [
                        {"fact": "infrastructure", "op": "<", "value": 0},
                        {"fact": "default", "op": "=", "value": False},
                        {"fact": "cost", "op": "<=", "value": 0.25},
                    ],
                    "why": "合成物流成本反例",
                    "counterexample": "玩家、缺失所有者或昂贵投入保留原版",
                }
            ],
        },
        source_sha256="0" * 64,
    )
    script = decision_rules.patch(
        baseline,
        policy,
        baseline=baseline,
        default_strategy=False,
        reader_evidence="owner infrastructure_delta in_default market mg:coal market_goods_pricier",
    )
    parsed = parse_text(script)
    assert not parsed.errors
    assert decision_rules.contract(policy)["actor"] == "root_state_owner"
    building = parsed.root.first("building_example")
    assert building is not None
    assert isinstance(building.value, Block)
    value = building.value.first("ai_value")
    assert value is not None
    assert isinstance(value.value, Block)
    return policy, value.value


def _state_candidate_score(block: Block, state: dict) -> float:
    """独立的州作用域小解释器，仅接受此合成契约的语法。"""

    def matches(node: Block, context: dict) -> bool:
        for assignment in node.assignments():
            if assignment.key == "exists":
                assert isinstance(assignment.value, Scalar)
                name = assignment.value.unquoted
                if name != "ROOT" and not isinstance(context.get(name), dict):
                    return False
            elif isinstance(assignment.value, Block):
                child = state if assignment.key == "ROOT" else context.get(assignment.key)
                if not isinstance(child, dict) or not matches(assignment.value, child):
                    return False
            else:
                assert isinstance(assignment.value, Scalar)
                value = context.get(assignment.key)
                if value is None:
                    return False
                text = assignment.value.unquoted
                if assignment.key in {"is_ai", "in_default"}:
                    if type(value) is not bool or value != (text == "yes"):
                        return False
                elif assignment.op == "<":
                    if value >= float(text):
                        return False
                elif assignment.op == "<=":
                    if value > float(text):
                        return False
                else:
                    pytest.fail(f"未声明语法 {assignment.key} {assignment.op}")
        return True

    result = 100.0
    for item in block.assignments():
        if item.key == "value":
            continue
        assert item.key == "if"
        assert isinstance(item.value, Block)
        limit = item.value.first("limit")
        factor = item.value.first("multiply")
        assert limit is not None
        assert factor is not None
        assert isinstance(limit.value, Block)
        assert isinstance(factor.value, Scalar)
        if matches(limit.value, state):
            result *= float(factor.value.unquoted)
    return result


@given(
    is_ai=st.booleans(),
    default=st.booleans(),
    infrastructure=st.integers(-100, 100),
    cost=st.integers(-75, 75),
)
def test_state_owner_cost_and_logistics_match_independent_policy(
    state_candidate, is_ai, default, infrastructure, cost
):
    policy, block = state_candidate
    state = {
        "infrastructure_delta": infrastructure,
        "owner": {
            "is_ai": is_ai,
            "in_default": default,
            "market": {"mg:coal": {"market_goods_pricier": cost / 100}},
        },
    }
    expected = 120 if is_ai and not default and infrastructure < 0 and cost <= 25 else 100
    assert _state_candidate_score(block, state) == expected
    reference = decision_rules.evaluate(
        policy,
        {"default": default, "infrastructure": infrastructure, "cost": cost / 100},
        is_ai=is_ai,
    )
    assert 100 * reference.get("building_example.ai_value", ("vanilla", 1))[1] == expected


def test_state_missing_owner_or_input_scopes_preserve_vanilla(state_candidate):
    _, block = state_candidate
    for state in (
        {},
        {"infrastructure_delta": -10},
        {"infrastructure_delta": -10, "owner": {"is_ai": True, "in_default": False}},
        {
            "infrastructure_delta": -10,
            "owner": {
                "is_ai": False,
                "in_default": False,
                "market": {"mg:coal": {"market_goods_pricier": 0}},
            },
        },
    ):
        assert _state_candidate_score(block, state) == 100


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("schema = 1", "schema = true"),
        ("common/ai_strategies/00_default_strategy.txt", "../outside.txt"),
        ('operation = "add"', 'operation = "force"'),
        ("value = 15", "value = 100000"),
        ('kind = "number"', 'kind = "unknown"'),
        ('scope = "root"', 'scope = "undefined"'),
        ('source = "common/', 'source = "missing/'),
        ('fact = "default"', 'fact = "invented"'),
        ('"common/buildings/03_mines.txt" = ["owner"]', '"common/buildings/03_mines.txt" = []'),
        (
            '"common/buildings/03_mines.txt" = ["owner"]',
            '"common/buildings/missing.txt" = ["owner"]',
        ),
    ],
)
def test_actual_adapter_configuration_rejects_unsafe_changes(tmp_path: Path, before, after):
    text = decision_adapters.SOURCE.read_text(encoding="utf-8")
    assert before in text
    source = tmp_path / "invalid.toml"
    source.write_text(text.replace(before, after, 1), encoding="utf-8", newline="\n")
    with pytest.raises(ValueError):
        decision_adapters.load(source)


def test_event_evidence_cannot_become_a_mutable_consumer(tmp_path):
    text = decision_adapters.SOURCE.read_text(encoding="utf-8")
    native = "common/ai_strategies/00_default_strategy.txt"
    assert native in text
    source = tmp_path / "event-consumer.toml"
    source.write_text(
        text.replace(native, "events/synthetic_evidence.txt"), encoding="utf-8", newline="\n"
    )
    with pytest.raises(ValueError, match="事件只能作为读取依据"):
        decision_adapters.load(source)


def _expanded_law_negative_contracts():
    """Independent finite G1-G3 contracts, pinned to native transition effects."""
    contracts = {}

    def add(law, suffix, value, group, *conditions):
        contracts[f"law_context_{law}_{suffix}"] = (value, group, set(conditions))

    def current(law):
        return (f"law_context_current_{law}", "=", True)

    # Native authority constants: current-only subjecthood has no score writer.
    authority_families = (
        {
            "law_subjecthood": 100,
            "law_ethnostate": 200,
            "law_national_supremacy": 150,
            "law_racial_segregation": 100,
            "law_cultural_exclusion": 50,
            "law_multicultural": 0,
        },
        {
            "law_state_religion": 200,
            "law_millet_system": 200,
            "law_people_of_the_book": 200,
            "law_freedom_of_conscience": 100,
            "law_total_separation": 0,
            "law_state_atheism": 200,
        },
    )
    labour = {
        "law_guild_system": (0, 0),
        "law_combination_acts": (0.25, -0.25),
        "law_anti_strike_laws": (0.10, -0.10),
        "law_right_to_associate": (-0.10, 0.10),
        "law_corporatized_unions": (0, 0),
        "law_factory_councils": (0, 0.25),
    }
    police = {
        "law_no_police": (0, 0, 0),
        "law_local_police": (-0.05, 0, 0),
        "law_dedicated_police": (0, -0.05, 0),
        "law_militarized_police": (0, -0.05, 0.004),
    }
    expanded_laws = (set().union(*authority_families) | labour.keys() | police.keys()) - {
        "law_subjecthood"
    }
    for law in expanded_laws:
        for tier, value in (("base", -6), ("strong", -10)):
            add(
                law,
                f"adopted_agenda_{tier}",
                value,
                "law_observed_agenda",
                (f"law_context_{law}_movement_{tier}", "=", True),
                current(law),
            )
    for family in authority_families:
        for law, candidate_authority in family.items():
            if law == "law_subjecthood":
                continue
            for origin, original_authority in family.items():
                loss = original_authority - candidate_authority
                if loss > 0:
                    add(
                        law,
                        f"{origin}_authority_transition",
                        -8,
                        "law_authority_transition",
                        current(origin),
                        ("authority", "<", loss),
                    )
    for law, effects in police.items():
        for origin, previous in police.items():
            if law == origin:
                continue
            if origin == "law_no_police":
                for fact, op, threshold, value in (
                    ("bureaucracy", "<", 0, -6),
                    ("default", "=", True, -8),
                ):
                    add(
                        law,
                        f"new_institution_{fact}",
                        value,
                        f"law_police_new_institution_{fact}",
                        current(origin),
                        (fact, op, threshold),
                    )
            for mechanism, candidate, old in zip(
                ("turmoil_protection", "movement_radicalization", "mortality"),
                effects,
                previous,
                strict=True,
            ):
                if candidate <= old:
                    continue
                for tier, investment in (("base", 1), ("invested", 3)):
                    exposure: tuple[tuple[str, str, bool | float], ...]
                    if mechanism == "movement_radicalization":
                        value, group = -6, "law_police_movement_loss"
                        exposure = (
                            (f"law_context_{law}_movement_base", "=", True),
                            ("radical_share", ">=", 0.25),
                        )
                    else:
                        value = {
                            ("turmoil_protection", "base"): -6,
                            ("turmoil_protection", "invested"): -9,
                            ("mortality", "base"): -8,
                            ("mortality", "invested"): -12,
                        }[mechanism, tier]
                        group = f"law_police_{mechanism}"
                        exposure = (("owned_state_turmoil", "=", True),)
                    add(
                        law,
                        f"{origin}_{mechanism}_{tier}",
                        value,
                        group,
                        current(origin),
                        ("police_investment", ">=", investment),
                        *exposure,
                    )
    for law, (radicalization, union_strength) in labour.items():
        for origin, (old_radicalization, old_union_strength) in labour.items():
            if radicalization > old_radicalization:
                add(
                    law,
                    f"{origin}_movement_radicalization",
                    -6,
                    "law_movement_radicalization_loss",
                    current(origin),
                    (f"law_context_{law}_movement_base", "=", True),
                    ("radical_share", ">=", 0.25),
                )
            if union_strength > old_union_strength:
                for tier, value in (("base", -6), ("government", -9)):
                    conditions: tuple[tuple[str, str, bool | float], ...] = (
                        current(origin),
                        ("union_approval", "<", 0),
                        ("union_clout", ">=", 0.2),
                    )
                    if tier == "government":
                        conditions += (("union_government", "=", True),)
                    add(
                        law,
                        f"{origin}_union_adjustment_{tier}",
                        value,
                        "law_union_transition_adjustment",
                        *conditions,
                    )
    return contracts


def test_declared_sources_have_consumers_and_real_bounded_conditions():
    adapters = decision_adapters.load()
    rules = [rule for _, policy in adapters.policies for rule in policy.rules]
    declared = tomllib.loads(decision_adapters.SOURCE.read_text(encoding="utf-8"))["rules"]
    actual = {rule.id: rule for rule in rules}
    expanded_negative = _expanded_law_negative_contracts()
    assert set(expanded_negative) <= actual.keys()
    for identity, contract in expanded_negative.items():
        rule = actual[identity]
        assert (
            rule.value,
            rule.contribution_group,
            {(c.fact, c.op, c.value) for c in rule.conditions},
        ) == contract
    # Native company/recipe/equipment/treaty/mobilization derivations add real consumers;
    # they are not hand-written TOML rows. Keep every authored identity exact,
    # and admit only the registered derived namespaces checked in their own
    # complete source/AST contract suites.
    for row in declared:
        rule = actual[row["id"]]
        assert (".".join(rule.field), rule.operation, rule.value) == (
            row["field"],
            row["operation"],
            row["value"],
        )
    authored = {row["id"] for row in declared}
    assert all(
        rule.id.startswith(
            (
                "company_",
                "building_",
                "equipment_",
                "treaty_",
                "mobilization_",
                "law_context_",
                "technology_",
            )
        )
        for rule in rules
        if rule.id not in authored
    )
    assert len({rule.id for rule in rules}) == len(rules)
    assert {rule.domain for rule in rules} == {
        "political",
        "fiscal",
        "economy",
        "market",
        "military",
        "subjects",
        "diplomacy",
    }
    assert all(rule.conditions and rule.why and rule.counterexample for rule in rules)
    for name, policy in adapters.policies:
        assert name in dict(adapters.sources)
        if "/buildings/" in name:
            assert policy.actor_path == ("owner",)
            assert all(rule.field[-1] == "ai_value" for rule in policy.rules)
        elif name == "common/mobilization_options/00_mobilization_option.txt":
            from pdx.mobilization_opportunities import CANDIDATE_IDS

            assert policy.native_root == "military_formation"
            assert policy.actor_path == ("owner",)
            assert {rule.field for rule in policy.rules} == {
                (identity, "ai_weight") for identity in CANDIDATE_IDS
            }
        else:
            assert policy.actor_path == ()
        if "/laws/" in name:
            for rule in policy.rules:
                assert rule.operation == "add"
                if rule.id.startswith("political_capacity_"):
                    assert rule.value == -10
                    assert {condition.fact for condition in rule.conditions} == {
                        "legitimacy",
                        "insurrection",
                        "radical_share",
                    }
                elif rule.id.startswith("bureaucracy_reform_") and rule.value < 0:
                    assert (rule.value, rule.contribution_group) == {
                        **{
                            f"bureaucracy_reform_appointed_elected_institution_cost_{key}": (
                                -8,
                                "bureaucracy_institution_cost",
                            )
                            for key in (
                                "police",
                                "home_affairs",
                                "colonial_affairs",
                                "health",
                                "schools",
                                "social_security",
                                "workplace_safety",
                            )
                        },
                        "bureaucracy_reform_elected_appointed_tax_loss": (
                            -10,
                            "bureaucracy_tax_capacity",
                        ),
                    }[rule.id]
                elif rule.id.startswith("health_reform_") and rule.value < 0:
                    health_costs = {
                        **{
                            f"health_reform_{candidate}_new_administrative_pressure": (
                                -8,
                                "health_administration",
                            )
                            for candidate in ("charity", "private", "public")
                        },
                        **{
                            f"health_reform_{candidate}_new_default_pressure": (
                                -6,
                                "health_financing",
                            )
                            for candidate in ("charity", "private", "public")
                        },
                        "health_reform_public_private_administrative_loss": (
                            -8,
                            "health_administration",
                        ),
                        "health_reform_public_private_default_pressure": (-6, "health_financing"),
                        "health_reform_public_charity_administrative_loss": (
                            -4,
                            "health_administration",
                        ),
                        "health_reform_public_charity_default_pressure": (-6, "health_financing"),
                        "health_reform_private_charity_food_loss": (
                            -4,
                            "health_food_security_loss",
                        ),
                        "health_reform_public_charity_food_loss": (-4, "health_food_security_loss"),
                        "health_reform_private_public_universal_access_loss": (
                            -8,
                            "health_universal_access_loss",
                        ),
                    }
                    assert (rule.value, rule.contribution_group) == health_costs[rule.id]
                elif rule.id.startswith("social_reform_") and rule.value < 0:
                    # 子女收入损失的最严重已设计档位为-18；其余社会法成本不低于-16。
                    minimum = (
                        -18
                        if rule.id
                        == "social_reform_compulsory_primary_school_from_child_labor_income_loss_8"
                        else -16
                    )
                    assert minimum <= rule.value < 0
                    assert rule.contribution_group.startswith(
                        ("social_reform_", "welfare_", "labor_", "school_", "child_")
                    )
                elif rule.id.startswith("law_context_") and rule.value < 0:
                    if rule.id in expanded_negative:
                        assert rule.value < 0
                    elif rule.id.endswith("_crisis_cost"):
                        assert (rule.value, rule.contribution_group) == (
                            -10,
                            "law_political_pressure",
                        )
                        assert {condition.fact for condition in rule.conditions} == {
                            "legitimacy",
                            "insurrection",
                            "radical_share",
                        }
                    elif rule.id.endswith("_administration_transition"):
                        assert (rule.value, rule.contribution_group) == (
                            -6,
                            "law_tax_administration_transition",
                        )
                    else:
                        assert (
                            rule.id
                            == "law_context_law_interventionism_population_administration_loss"
                        )
                        assert (rule.value, rule.contribution_group) == (
                            -6,
                            "law_population_administration",
                        )
                elif rule.value < 0:
                    assert (rule.id, rule.value) in {
                        ("public_school_administrative_pressure", -8),
                        ("public_school_default_pressure", -6),
                    }
                    assert rule.contribution_group
                else:
                    assert 0 < rule.value <= 30
        else:
            for rule in policy.rules:
                if rule.operation == "add":
                    assert rule.id.startswith(
                        (
                            "coordinated_",
                            "comparative_",
                            "structural_",
                            "lj08_",
                            "lj12_",
                            "remaining_",
                            "target_strategy_",
                        )
                    )
                    assert -10 <= rule.value <= 30
                    assert rule.field[0] == "ai_strategy_default"
                else:
                    assert rule.operation == "multiply"
                    if rule.id == "d6_steelworking_tools_shortage_pressure":
                        assert rule.value == 1.35
                    else:
                        assert 0.75 <= rule.value <= 1.3
    default_name = "common/ai_strategies/00_default_strategy.txt"
    default_policy = dict(adapters.policies)[default_name]
    changed = replace(
        default_policy,
        rules=(
            replace(
                default_policy.rules[0], field=("ai_strategy_default", "wanted_construction_output")
            ),
        ),
        enabled_domains=frozenset({default_policy.rules[0].domain}),
    )
    conflicting = replace(adapters, policies=((default_name, changed),))
    with pytest.raises(ValueError, match="重复写入"):
        decisions.build(information_rules=decision_rules.load(), consumer_adapters=conflicting)


@pytest.mark.integration
@pytest.mark.skipif(
    not (config.GAME / "common/laws/readme.md").is_file(), reason="需要锁定版本的游戏原件"
)
def test_all_real_adapter_files_retain_original_entries_and_non_ai_bytes():
    adapters = decision_adapters.load()
    files, contract = decision_adapters.build(adapters, country_policy=country_state.load())
    consumers = contract["consumers"]
    assert isinstance(consumers, list)
    policy_sources = {source for source, _policy in adapters.policies}
    assert {row["source"] for row in consumers} == policy_sources
    assert len(consumers) == len(policy_sources)
    scalar_consumers = contract["scalar_consumers"]
    assert isinstance(scalar_consumers, list)
    named_values = {
        row["source"]: row
        for row in scalar_consumers
        if row["operation"] == "retain_native_constant_in_named_value"
    }
    assert set(files) == policy_sources | {row["value_source"] for row in named_values.values()}
    for name, text in files.items():
        inline_text = text
        if name == "common/script_values/sitai_adapter_values.txt":
            assert not parse_text(text).errors
            continue
        baseline = normalized_text((config.GAME / name).read_text(encoding="utf-8-sig"))
        assert not parse_text(text).errors
        assert parse_text(text).top_keys == parse_text(baseline).top_keys
        if name in named_values:
            row = named_values[name]
            definition = files[row["value_source"]]
            opening, closing = definition.index("{"), definition.rindex("}") + 1
            inline_text = text.replace(row["value_name"], definition[opening:closing])
        restored = re.sub(
            r"\n\t\t# SITAI BEGIN information:[^\n]+\n.*?# SITAI END information:[^\n]+\n\t",
            "",
            inline_text,
            flags=re.DOTALL,
        )
        restored = re.sub(
            r"\n\t# SITAI BEGIN initialized:[^\n]+\n.*?# SITAI END initialized:[^\n]+\n",
            "",
            restored,
            flags=re.DOTALL,
        )
        restored = re.sub(
            r"\n\t\t# SITAI BEGIN supply:[^\n]+\n.*?# SITAI END supply:[^\n]+\n\t",
            "",
            restored,
            flags=re.DOTALL,
        )
        restored = re.sub(
            r"\{ value = ([0-9]+(?:\.[0-9]+)?) # SITAI wrapped-scalar:[^\n]+\n\}",
            r"\1",
            restored,
        )
        assert restored == baseline, name


@pytest.fixture(scope="module")
def implicit_building_adapter():
    """独立合成的缺省消费者，测试不依赖本体或生产配置的机械数字。"""
    name = "common/buildings/example.txt"
    defines = "common/defines/example.txt"
    text = "building_example = { possible = { owner = { in_default = no } } }\n"
    definition = "NAI = { PRODUCTION_BUILDING_BASE_VALUE = 1200 }\n"
    policy = decision_rules.from_data(
        {
            "schema": 1,
            "baseline_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "actor_path": ["owner"],
            "domains": {"economy": True},
            "readers": {
                "default": {
                    "engine": "in_default",
                    "scope": "root",
                    "path": ["owner"],
                    "unit": "boolean",
                    "kind": "boolean",
                },
            },
            "rules": [
                {
                    "id": "funded",
                    "domain": "economy",
                    "field": "building_example.ai_value",
                    "priority": 50,
                    "value": 1.1,
                    "conditions": [{"fact": "default", "op": "=", "value": False}],
                    "why": "合成缺省消费者",
                    "counterexample": "违约、玩家与关闭保留原版",
                }
            ],
        },
        source_sha256="0" * 64,
    )
    initial = decision_adapters.InitialValue(
        name, ("building_example", "ai_value"), defines, ("NAI", "PRODUCTION_BUILDING_BASE_VALUE")
    )
    adapters = decision_adapters.AdapterSet(
        (
            (name, policy.baseline_sha256),
            (defines, hashlib.sha256(definition.encode()).hexdigest()),
        ),
        ((name, policy),),
        "0" * 64,
        (initial,),
    )
    return adapters, {name: text, defines: definition}, name


def test_implicit_building_value_comes_from_locked_define_and_is_fully_reversible(
    implicit_building_adapter,
):
    adapters, inputs, name = implicit_building_adapter
    files, contract = decision_adapters.build(adapters, texts=inputs)
    building = parse_text(files[name]).root.first("building_example")
    assert building is not None
    assert isinstance(building.value, Block)
    assignment = building.value.first("ai_value")
    assert assignment is not None
    value = assignment.value
    assert isinstance(value, Block)
    base = value.first("value")
    assert base is not None
    assert isinstance(base.value, Scalar)
    assert base.value.unquoted == "1200"
    assert "owner = { is_ai = yes" in files[name]
    initialized = contract["initialized_consumers"]
    assert isinstance(initialized, list)
    assert initialized[0]["define"] == "NAI.PRODUCTION_BUILDING_BASE_VALUE"
    restored = re.sub(
        r"\n\t# SITAI BEGIN initialized:[^\n]+\n.*?# SITAI END initialized:[^\n]+\n",
        "",
        files[name],
        flags=re.DOTALL,
    )
    assert restored == inputs[name]
    disabled, contract = decision_adapters.build(
        adapters, texts=inputs, enabled_domains=frozenset()
    )
    assert disabled == {}
    assert contract["initialized_consumers"] == []
    # 原件常量即使未被本次规则读取，也必须校验漂移，不能默认为 1000。
    with pytest.raises(ValueError, match="漂移"):
        decision_adapters.build(
            adapters, texts={key: value.replace("1200", "1000") for key, value in inputs.items()}
        )


@pytest.mark.parametrize("extra", [" ai_value = 900 ", " ai_value = { value = 900 } "])
def test_initializer_refuses_to_overwrite_an_existing_value(implicit_building_adapter, extra):
    adapters, inputs, name = implicit_building_adapter
    changed = inputs[name].replace("building_example = {", "building_example = {" + extra)
    digest = hashlib.sha256(changed.encode()).hexdigest()
    policy = replace(adapters.policies[0][1], baseline_sha256=digest)
    adapters = replace(
        adapters, sources=((name, digest), adapters.sources[1]), policies=((name, policy),)
    )
    with pytest.raises(ValueError, match="已经存在"):
        decision_adapters.build(adapters, texts={**inputs, name: changed})


@pytest.mark.parametrize("value", ["-1", "nan", "some_symbol", "{ value = 1200 }", "yes"])
def test_initializer_refuses_unknown_or_non_numeric_native_defaults(
    implicit_building_adapter, value
):
    adapters, inputs, _name = implicit_building_adapter
    defines = adapters.sources[1][0]
    changed = inputs[defines].replace("1200", value)
    adapters = replace(
        adapters,
        sources=(adapters.sources[0], (defines, hashlib.sha256(changed.encode()).hexdigest())),
    )
    with pytest.raises(ValueError, match=r"常量|数值"):
        decision_adapters.build(adapters, texts={**inputs, defines: changed})


@pytest.fixture(scope="module")
def scalar_building_adapter(implicit_building_adapter):
    adapters, inputs, name = implicit_building_adapter
    text = inputs[name].replace(
        "building_example = {", "building_example = { ai_value = 2000 # 原注释\n"
    )
    digest = hashlib.sha256(text.encode()).hexdigest()
    policy = replace(adapters.policies[0][1], baseline_sha256=digest)
    return (
        replace(
            adapters,
            sources=((name, digest),),
            policies=((name, policy),),
            initial_values=(),
            scalar_values=((name, ("building_example", "ai_value")),),
        ),
        {name: text},
        name,
    )


def test_scalar_consumer_retains_native_value_comments_and_disable(scalar_building_adapter):
    adapters, inputs, name = scalar_building_adapter
    files, contract = decision_adapters.build(adapters, texts=inputs)
    assert "value = 2000" in files[name]
    assert "# 原注释" in files[name]
    restored = re.sub(
        r"\n\t\t# SITAI BEGIN information:[^\n]+\n.*?# SITAI END information:[^\n]+\n\t",
        "",
        files[name],
        flags=re.DOTALL,
    )
    restored = re.sub(r"\{ value = (2000) # SITAI wrapped-scalar:[^\n]+\n\}", r"\1", restored)
    assert restored == inputs[name]
    scalars = contract["scalar_consumers"]
    assert isinstance(scalars, list)
    assert scalars[0]["field"] == "building_example.ai_value"
    disabled, metadata = decision_adapters.build(
        adapters, texts=inputs, enabled_domains=frozenset()
    )
    assert disabled == {}
    assert metadata["scalar_consumers"] == []
    assert metadata["reader_evidence"] == {}


@pytest.fixture
def fleet_scalar():
    name = "common/ai_strategies/00_default_strategy.txt"
    field = (
        "ai_strategy_default",
        "fleet_compositions",
        "secondary_fleet",
        "mission_type_weights",
        "protect_supply",
    )
    source = (
        "# 保留原件\nai_strategy_default = { possible = { bureaucracy >= 0 is_at_war = no }\n"
        "fleet_compositions = { secondary_fleet = {\n"
        "mission_type_weights = { protect_supply = 1.0 # 原注释\nraid_convoys = 0.5 }\n"
        "} } }\n"
    )
    base = _synthetic()
    policy = replace(
        base.policies[0][1],
        baseline_sha256=hashlib.sha256(source.encode()).hexdigest(),
        rules=(
            replace(base.policies[0][1].rules[0], field=field, operation="multiply", value=1.1),
        ),
    )
    adapters = replace(
        base,
        sources=((name, policy.baseline_sha256),),
        policies=((name, policy),),
        scalar_values=((name, field),),
    )
    return name, field, source, adapters


def test_fleet_scalar_uses_named_value_and_preserves_dynamic_body(fleet_scalar):
    """实机拒绝任务权重内联块；不能靠删除条件或改成常量消除错误。"""
    name, field, source, adapters = fleet_scalar
    files, contract = decision_adapters.build(adapters, texts={name: source})
    current: Block | Scalar | None = parse_text(files[name]).root
    for key in field:
        assert isinstance(current, Block)
        assignment = current.first(key)
        assert assignment is not None
        current = assignment.value
        if key != field[-1]:
            assert isinstance(current, Block)
    assert isinstance(current, Scalar), "任务权重必须引用具名值，不能输出已知解析错误的内联块"
    values_path = "common/script_values/sitai_adapter_values.txt"
    values = parse_text(files[values_path])
    assert not values.errors
    definition = values.root.first(current.text)
    assert definition is not None
    assert isinstance(definition.value, Block)
    base_value = definition.value.first("value")
    assert base_value is not None
    assert isinstance(base_value.value, Scalar)
    assert base_value.value.text == "1.0"
    assert "multiply = 1.1" in files[values_path]
    assert "bureaucracy >= 0" in files[values_path]
    assert "is_ai = yes" in files[values_path]
    assert "# 原注释" in files[name]
    assert "raid_convoys = 0.5" in files[name]
    scalars = contract["scalar_consumers"]
    assert scalars == [
        {
            "source": name,
            "field": ".".join(field),
            "operation": "retain_native_constant_in_named_value",
            "value_source": values_path,
            "value_name": current.text,
            "runtime_evaluation_verified": False,
        }
    ]
    assert files == decision_adapters.build(adapters, texts={name: source})[0]
    disabled, metadata = decision_adapters.build(
        adapters,
        texts={name: source},
        enabled_domains=frozenset(),
    )
    assert disabled == {}
    assert metadata["scalar_consumers"] == []


@pytest.mark.parametrize("collision", ["input_name", "output_path"])
def test_fleet_named_value_rejects_existing_definition(fleet_scalar, collision):
    name, _, source, adapters = fleet_scalar
    overlays = None
    if collision == "input_name":
        source += "sitai_adapter_fleet_supply_weight = { value = 4 }\n"
        digest = hashlib.sha256(source.encode()).hexdigest()
        adapters = replace(
            adapters,
            sources=((name, digest),),
            policies=((name, replace(adapters.policies[0][1], baseline_sha256=digest)),),
        )
    else:
        overlays = {"common/script_values/sitai_adapter_values.txt": "owned = 1\n"}
    with pytest.raises(ValueError, match=r"具名评分.*冲突"):
        decision_adapters.build(adapters, texts={name: source}, overlays=overlays)


@pytest.mark.parametrize(
    "value",
    [
        "-1",
        "nan",
        "yes",
        "1e20",
        "{ value = 2000 }",
        "2000 ai_value = 3000",
        "2000 ai_value = { value = 3000 }",
        "9" * 400,
    ],
)
def test_scalar_consumer_rejects_invalid_ambiguous_or_block_values(scalar_building_adapter, value):
    adapters, inputs, name = scalar_building_adapter
    changed = inputs[name].replace("ai_value = 2000", "ai_value = " + value)
    digest = hashlib.sha256(changed.encode()).hexdigest()
    adapters = replace(
        adapters,
        sources=((name, digest),),
        policies=((name, replace(adapters.policies[0][1], baseline_sha256=digest)),),
    )
    with pytest.raises(ValueError, match="常量评分"):
        decision_adapters.build(adapters, texts={name: changed})


@dataclass(frozen=True)
class _GeneratedBranches:
    # Hypothesis prints fixture arguments in a failing example. Keep the full
    # fixture for evaluation without serializing thousands of rules and ASTs
    # into every failure and exhausting the worker during error reporting.
    branches: tuple = dataclass_field(repr=False)
    scripts: dict[int, dict[str, str]] = dataclass_field(repr=False)
    prepared: dict = dataclass_field(default_factory=dict, repr=False)

    def __iter__(self):
        return iter(self.branches)

    def _repr_pretty_(self, printer, _cycle):
        # Hypothesis's dataclass printer ignores repr=False. Its custom hook
        # must also remain bounded when a real all-policy assertion fails.
        printer.text(f"_GeneratedBranches(policies={len(self.branches)})")


def test_generated_branches_have_bounded_hypothesis_failure_diagnostics():
    from hypothesis.vendor.pretty import pretty

    payload = "large generated rules and ASTs " * 100
    fixture = _GeneratedBranches(((payload,),), {1: {"field": payload}})
    assert pretty(fixture) == "_GeneratedBranches(policies=1)"
    assert repr(fixture) == "_GeneratedBranches()"


def _adapter_oracle_script(text):
    """Label native-neutral exits for the strict oracle without changing their AST.

    Legacy adapters emit unmarked multiply=1 fallback branches. pdx_eval needs
    an identity on every writing branch; only those exact neutral exits may
    receive a fixture label. Authored writer identities remain untouched.
    """
    lines = text.splitlines()
    marked_lines = set()
    for index, line in enumerate(lines):
        if not re.match(r"\s*# (?:ACTION )?[a-z][a-z0-9_]* \[[a-z][a-z0-9_]*\];", line):
            continue
        branch = index + 1
        while branch < len(lines) and not lines[branch].strip():
            branch += 1
        marked_lines.add(branch + 1)
    original = parse_text(text)
    assert not original.errors
    neutral_lines = set()

    def visit(block):
        for item in block.assignments():
            if not isinstance(item.value, Block):
                continue
            writes = [
                child for child in item.value.assignments() if child.key in {"add", "multiply"}
            ]
            if item.key in {"if", "else_if", "else"} and writes and item.line not in marked_lines:
                assert len(writes) == 1
                assert writes[0].key == "multiply"
                assert isinstance(writes[0].value, Scalar)
                assert float(writes[0].value.unquoted) == 1
                neutral_lines.add(item.line)
            visit(item.value)

    visit(original.root)
    return "\n".join(
        ("# ACTION adapter_neutral_fallback [oracle];\n" if index in neutral_lines else "") + line
        for index, line in enumerate(lines, 1)
    )


@pytest.fixture(scope="module")
def real_generated_branches():
    if not (config.GAME / "common/laws/readme.md").is_file():
        pytest.skip("需要锁定版本的游戏原件")
    adapters = decision_adapters.load()
    files, contract = decision_adapters.build(adapters, country_policy=country_state.load())
    scalar_consumers = contract["scalar_consumers"]
    assert isinstance(scalar_consumers, list)
    named_sources = {
        (row["source"], row["field"]): row["value_source"]
        for row in scalar_consumers
        if row["operation"] == "retain_native_constant_in_named_value"
    }
    result = []
    scripts: dict[int, dict[str, str]] = {}
    for source, policy in adapters.policies:
        blocks = {}
        scripts[id(policy)] = {}
        for field in policy.groups():
            name = ".".join(field)
            match = re.search(
                rf"# SITAI BEGIN information:{re.escape(name)}\n(.*?)# SITAI END information:",
                files[named_sources.get((source, name), source)],
                re.DOTALL,
            )
            assert match is not None
            parsed = parse_text(match.group(1))
            assert not parsed.errors
            blocks[name] = parsed.root
            scripts[id(policy)][name] = _adapter_oracle_script(match.group(1))
        result.append((policy, blocks))
    from pdx.situated import pdx_eval

    prepared = {
        identity: {field: pdx_eval.prepare(script, path=field) for field, script in rows.items()}
        for identity, rows in scripts.items()
    }
    return _GeneratedBranches(tuple(result), scripts, prepared)


@pytest.fixture(scope="module")
def social_reform_joint_branches():
    """Exercise current production IR, keeping the legacy adapter oracle separate."""
    from pdx.situated import compiler

    sources = {"common/laws/02_labor_rights.txt", "common/laws/02_welfare.txt"}
    adapters = decision_adapters.load()
    model = compiler.load_model()
    assert model.consumer_ir is not None
    selected = replace(
        adapters,
        policies=tuple(
            (source, compiler.compile_policy(policy, source, model)[0])
            for source, policy in adapters.policies
            if source in sources
        ),
        supply=None,
        initial_values=(),
        scalar_values=(),
    )
    files, _ = decision_adapters.build(
        selected, country_policy=country_state.load(), consumer_ir=model.consumer_ir
    )
    result = []
    scripts: dict[int, dict[str, str]] = {}
    for source, policy in selected.policies:
        blocks = {}
        scripts[id(policy)] = {}
        for field in policy.groups():
            name = ".".join(field)
            match = re.search(
                rf"# SITAI BEGIN information:{re.escape(name)}\n(.*?)# SITAI END information:",
                files[source],
                re.DOTALL,
            )
            assert match is not None
            parsed = parse_text(match.group(1))
            assert not parsed.errors
            blocks[name] = parsed.root
            scripts[id(policy)][name] = _adapter_oracle_script(match.group(1))
        result.append((policy, blocks))
    from pdx.situated import pdx_eval

    prepared = {
        identity: {field: pdx_eval.prepare(script, path=field) for field, script in rows.items()}
        for identity, rows in scripts.items()
    }
    return _GeneratedBranches(tuple(result), scripts, prepared)


def _interpret_adjustments(block: Block, scopes: dict) -> tuple[str, float] | None:
    """独立解释实际生成的条件树，不读取 Rule.conditions 或参考求值器。"""
    operators = {
        "=": operator.eq,
        "<": operator.lt,
        "<=": operator.le,
        ">": operator.gt,
        ">=": operator.ge,
    }

    def condition(assignment, current):
        key, value = assignment.key, assignment.value
        if key == "always":
            assert isinstance(value, Scalar)
            assert value.unquoted in {"yes", "no"}
            return value.unquoted == "yes"
        if key == "exists":
            assert isinstance(value, Scalar)
            return value.unquoted in (
                scopes
                if value.unquoted == "ROOT" or value.unquoted.startswith("scope:")
                else current
            )
        if isinstance(value, Block):
            values = list(value.assignments())
            if key in {
                "is_production_method_active",
                "has_diplomatic_pact",
                "has_treaty_alliance_with",
            }:
                expected_keys = {
                    "is_production_method_active": {"building_type", "production_method"},
                    "has_diplomatic_pact": {"who", "type"},
                    "has_treaty_alliance_with": {"TARGET"},
                }[key]
                assert {item.key for item in values} == expected_keys
                pairs = []
                for item in values:
                    assert isinstance(item.value, Scalar)
                    pairs.append((item.key, item.value.unquoted))
                parameters = tuple(sorted(pairs))
                return current.get((key, parameters)) is True
            if key == "pop_type_percent_country" or (
                key in {"radical_fraction", "loyalist_fraction"}
                and any(item.key == "pop_type" for item in values)
            ):
                current_population = (
                    key == "pop_type_percent_country"
                    and version_contracts.active_version() == "1.15.0"
                )
                parameter_key = "target" if current_population else "pop_type"
                parameter_items = [item for item in values if item.key == parameter_key]
                assert len(parameter_items) == 1
                assert isinstance(parameter_items[0].value, Scalar)
                signature = (
                    key,
                    ((parameter_key, parameter_items[0].value.unquoted),),
                )
                actual = current.get(signature)
                value_key = (
                    "percent"
                    if key == "pop_type_percent_country" and not current_population
                    else "value"
                )
                assert {item.key for item in values} == {parameter_key, value_key}
                return all(
                    condition(item, {value_key: actual}) for item in values if item.key == value_key
                )
            if key in {"AND", "OR", "NOT"}:
                results = [condition(item, current) for item in values]
                return (
                    any(results)
                    if key == "OR"
                    else not all(results)
                    if key == "NOT"
                    else all(results)
                )
            child = (
                scopes.get(key) if key == "ROOT" or key.startswith("scope:") else current.get(key)
            )
            if key == "radical_fraction":
                assert all(item.key == "value" for item in values)
                return all(condition(item, {"value": child}) for item in values)
            return isinstance(child, dict) and all(condition(item, child) for item in values)
        assert isinstance(value, Scalar)
        literal = value.unquoted
        if (key, literal) in current:
            return current.get((key, literal)) is True
        actual = current.get(key)
        if literal in {"yes", "no"}:
            return type(actual) is bool and actual == (literal == "yes")
        assert isinstance(actual, (int, float))
        assert math.isfinite(actual)
        if literal.startswith(("ROOT.", "scope:")):
            parts = literal.split(".")
            other = scopes.get(parts[0])
            for part in parts[1:]:
                other = other.get(part) if isinstance(other, dict) else None
            return isinstance(other, (int, float)) and operators[assignment.op](actual, other)
        return operators[assignment.op](actual, float(literal))

    def execute(statements: Block) -> tuple[str, float] | None:
        matched = False
        result = None
        for statement in statements.assignments():
            if statement.key == "limit":
                continue
            if statement.key in {"if", "else_if", "else"}:
                assert isinstance(statement.value, Block)
                if statement.key == "if":
                    matched = False
                if matched:
                    continue
                limit = statement.value.first("limit")
                if statement.key != "else":
                    assert limit is not None
                    assert isinstance(limit.value, Block)
                    if not all(condition(item, {}) for item in limit.value.assignments()):
                        continue
                else:
                    assert limit is None
                matched = True
                adjustment = execute(statement.value)
                if adjustment is not None:
                    assert result is None
                    result = adjustment
            else:
                assert statement.key in {"add", "multiply"}
                assert isinstance(statement.value, Scalar)
                assert result is None
                result = statement.key, float(statement.value.unquoted)
        return result

    return execute(block)


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        (
            "if = { limit = { always = yes } if = { limit = { always = yes } add = 2 } }",
            ("add", 2.0),
        ),
        (
            (
                "if = { limit = { always = yes } "
                "if = { limit = { always = no } add = 2 } } "
                "else_if = { limit = { always = yes } add = 3 } "
                "else = { add = 4 }"
            ),
            None,
        ),
        (
            (
                "if = { limit = { always = no } add = 2 } "
                "else_if = { limit = { always = yes } "
                "if = { limit = { always = no } add = 3 } "
                "else = { multiply = 1.3 } } "
                "else = { add = 4 }"
            ),
            ("multiply", 1.3),
        ),
        (
            (
                "if = { limit = { always = no } add = 2 } "
                "else_if = { limit = { always = no } add = 3 } "
                "else = { add = 4 }"
            ),
            ("add", 4.0),
        ),
    ],
)
def test_adjustment_interpreter_executes_nested_conditional_chains(script, expected):
    parsed = parse_text(script)
    assert not parsed.errors
    assert _interpret_adjustments(parsed.root, {}) == expected


@pytest.mark.integration
@pytest.mark.parametrize(
    "rule_id",
    [
        "remaining_friendly_subject_strong",
        "remaining_friendly_overlord_strong",
        "remaining_embargo_access_naval_capacity",
    ],
)
def test_shared_intent_reaches_production_consumers_and_preserves_counterexamples(
    real_generated_branches, rule_id
):
    policy, blocks = next(
        (policy, blocks)
        for policy, blocks in real_generated_branches
        if any(rule.id == rule_id for rule in policy.rules)
    )
    rule = next(rule for rule in policy.rules if rule.id == rule_id)
    assert rule.intent is None
    facts = {
        r.key: False if r.kind == "boolean" else max(0.0, r.minimum or 0.0) for r in policy.readers
    }
    facts.update(
        legitimacy=60,
        bureaucracy=100,
        net_surplus=100,
        debt_ratio=0.1,
        industrial=True,
        union_clout=0.2,
        union_approval=-1,
        radical_share=0.3,
        target_relations=80,
        overlord_relations=80,
        target_embargo=True,
        navy=50,
        own_navy=50,
        national_gdp=100000000,
        candidate_gdp=1000000,
    )
    field = ".".join(rule.field)
    actual = _interpret_adjustments(blocks[field], _scopes_for_facts(policy, facts))
    assert actual == (rule.operation, rule.value)
    for change in (
        {"loans": True},
        {"debt_ratio": 0.6},
        {"net_surplus": -1},
        {"bureaucracy": -1},
        {"legitimacy": 20},
        {"insurrection": True},
        {"war": True},
        {"default": True},
    ):
        changed = {**facts, **change}
        reference = decision_rules.evaluate(policy, changed, is_ai=True)
        assert reference[field] == (rule_id, rule.value)
        actual = _interpret_adjustments(blocks[field], _scopes_for_facts(policy, changed))
        assert actual == (rule.operation, rule.value)
    core_fact = {
        "remaining_friendly_subject_strong": "target_relations",
        "remaining_friendly_overlord_strong": "overlord_relations",
        "remaining_embargo_access_naval_capacity": "target_embargo",
    }[rule_id]
    for value in (None, False if core_fact == "target_embargo" else 49):
        unknown = decision_rules.evaluate(policy, {**facts, core_fact: value}, is_ai=True)
        assert field not in unknown
    assert not decision_rules.evaluate(policy, facts, is_ai=False)
    assert not decision_rules.evaluate(policy, facts, is_ai=True, enabled_domains=frozenset())


@pytest.mark.integration
def test_wartime_defense_intent_survives_insolvency_in_generated_script(real_generated_branches):
    policy, blocks = next(
        (p, b)
        for p, b in real_generated_branches
        if any(r.id == "structural_wartime_supply_escort" for r in p.rules)
    )
    rule = next(r for r in policy.rules if r.id == "structural_wartime_supply_escort")
    assert rule.intent == "wartime_defense"
    facts = {
        r.key: False if r.kind == "boolean" else max(0.0, r.minimum or 0.0) for r in policy.readers
    }
    facts.update(
        war=True,
        default=True,
        loans=True,
        net_surplus=-100,
        debt_ratio=0.9,
        legitimacy=10,
        insurrection=True,
        navy=20,
        own_navy=20,
        steamers_price=0.5,
        steamers_balance=-10,
    )
    field = ".".join(rule.field)
    assert _interpret_adjustments(blocks[field], _scopes_for_facts(policy, facts)) == (
        "multiply",
        1.25,
    )
    assert (
        _interpret_adjustments(blocks[field], _scopes_for_facts(policy, {**facts, "war": False}))
        is None
    )


@pytest.fixture(scope="module")
def population_candidate():
    source = "law_demo = { ai_enact_weight_modifier = { value = 0 } }\n"
    current = version_contracts.active_version() == "1.15.0"
    policy = decision_rules.from_data(
        {
            "schema": 1,
            "baseline_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "domains": {"political": True},
            "readers": {
                "peasants": {
                    "engine": "pop_type_percent_country",
                    "scope": "root",
                    "kind": "number",
                    "unit": "ratio",
                    "minimum": 0,
                    "maximum": 1,
                    "value_field": "value" if current else "percent",
                    "parameters": {"target": "pop_type:peasants"}
                    if current
                    else {"pop_type": "peasants"},
                }
            },
            "rules": [
                {
                    "id": "population_need",
                    "domain": "political",
                    "field": "law_demo.ai_enact_weight_modifier",
                    "priority": 1,
                    "operation": "add",
                    "value": 5,
                    "conditions": [{"fact": "peasants", "op": ">=", "value": 0.6}],
                    "why": "合成人口占比接口条件",
                    "counterexample": "合成样例不构成游戏运行时证明",
                }
            ],
        },
        source_sha256="0" * 64,
    )
    script = decision_rules.patch(
        source,
        policy,
        baseline=source,
        default_strategy=False,
        reader_evidence=(
            "pop_type_percent_country = { target = pop_type:peasants value > 0.6 }"
            if current
            else "pop_type_percent_country = { pop_type = peasants percent > 0.6 }"
        ),
    )
    match = re.search(r"# SITAI BEGIN information:[^\n]+\n(.*?)# SITAI END", script, re.DOTALL)
    assert match is not None
    return policy, parse_text(match.group(1)).root


@given(share=st.floats(0, 1, allow_nan=False), is_ai=st.booleans())
def test_population_selector_matches_independent_generated_ast(population_candidate, share, is_ai):
    policy, block = population_candidate
    population_identity = (
        (("target", "pop_type:peasants"),)
        if version_contracts.active_version() == "1.15.0"
        else (("pop_type", "peasants"),)
    )
    scopes = {"ROOT": {"is_ai": is_ai, ("pop_type_percent_country", population_identity): share}}
    actual = _interpret_adjustments(block, scopes)
    expected = ("add", 5.0) if is_ai and share >= 0.6 else None
    assert actual == expected
    assert bool(decision_rules.evaluate(policy, {"peasants": share}, is_ai=is_ai)) == (
        expected is not None
    )


@pytest.mark.parametrize("bad", [None, -0.1, 1.1, True, "0.8", float("nan"), float("inf")])
def test_population_selector_invalid_facts_preserve_vanilla(population_candidate, bad):
    policy, _ = population_candidate
    assert decision_rules.evaluate(policy, {"peasants": bad}, is_ai=True) == {}


def _adapter_collection_observations(seed):
    """Sample owned objects, never a precomputed existential-query result.

    Keep this RNG separate from scalar Reader sampling so existing seeds still
    identify the same scalar/parameterized observations in every policy.
    """
    import random

    rng = random.Random(f"adapter-owned-observations:{seed}")
    from technology_query_reference import BUILDING_METHODS

    methods = {
        **BUILDING_METHODS,
        "building_art_academy": (
            "pm_traditional_art",
            "pm_realist_art",
            "pm_photographic_art",
        ),
        "building_port": ("pm_basic_port", "pm_industrial_port", "pm_modern_port"),
        "building_railway": ("pm_early_trains", "pm_steam_trains", "pm_electric_trains"),
        "building_power_plant": ("pm_early_power_plant", "pm_coal-fired_plant"),
        "building_gold_mine": ("pm_gold_mining",),
        "building_trade_center": ("pm_trade_center",),
    }
    all_methods = tuple(method for group in methods.values() for method in group)

    def building(kind):
        method = rng.choice(methods[kind])
        return {
            "is_building_type": {
                (("argument", candidate),): candidate == kind for candidate in methods
            },
            "has_active_production_method": {
                (("argument", candidate),): candidate == method for candidate in all_methods
            },
            "level": rng.choice([None, 0, 1, 2, 5]),
            "weekly_profit": rng.choice([None, -1, 0, 1, 100]),
            "occupancy": rng.choice([None, 0, 0.74, 0.75, 0.89, 0.9, 1]),
            "cash_reserves_ratio": rng.choice([None, 0, 0.24, 0.25, 0.26, 0.5, 0.6, 1]),
        }

    def buildings():
        # Missing and complete empty lists have different three-valued meaning.
        state = rng.randrange(5)
        if state == 0:
            return None
        if state == 1:
            return []
        return [building(kind) for kind in methods if rng.choice([True, False])]

    def states():
        state = rng.randrange(5)
        if state == 0:
            return None
        return [
            {
                "any_scope_building": buildings(),
                "market_access": rng.choice([None, 0, 0.89, 0.9, 0.99, 1]),
                "turmoil": rng.choice([None, 0, 0.09999, 0.1, 0.10001, 0.5]),
                "is_incorporated": rng.choice([None, False, True]),
                "tax_capacity": rng.choice([None, 0, 5, 10, 20]),
                "tax_capacity_usage": rng.choice([None, 0, 5, 10, 20]),
                "infrastructure_delta": rng.choice([None, -20, -1, 0, 10]),
                "sg:transportation": {
                    "state_goods_pricier": rng.choice([None, 0, 0.25, 0.26, 0.5, 0.51])
                },
                "sg:electricity": {
                    "state_goods_pricier": rng.choice([None, 0, 0.25, 0.26, 0.5, 0.51])
                },
            }
            for _ in range(state - 1)
        ]

    def political_members(engine, laws):
        state = rng.randrange(5)
        if state == 0:
            return None
        return [
            {
                engine: {
                    (("law", f"law_type:{law}"),): rng.choice([None, -1, 0, 1]) for law in laws
                },
                "political_movement_support": rng.choice([None, 0, 0.09, 0.1, 0.11, 0.5]),
            }
            for _ in range(state - 1)
        ]

    owned_states = states()
    # Country and state iterators describe the same owned world; incomplete
    # state observations cannot become a complete country building list.
    owned_buildings = (
        None
        if owned_states is None
        or any(state["any_scope_building"] is None for state in owned_states)
        else [member for state in owned_states for member in state["any_scope_building"]]
    )
    return {
        "any_scope_building": owned_buildings,
        "any_scope_state": owned_states,
        "any_political_movement": political_members(
            "law_enactment_stance", ("law_free_trade", "law_mercantilism")
        ),
        "any_interest_group": political_members("law_stance", ("law_anarchy",)),
    }


def _adapter_query_reference(reader, observations, root_facts=None):
    """Handwritten query semantics over members, independent of render/compiler/PDX."""

    def conjunction(*values):
        return False if False in values else None if None in values else True

    def existential(members, predicate):
        if members is None:
            return None
        values = [predicate(member) for member in members]
        return True if True in values else None if None in values else False

    def compare(actual, op, expected):
        return None if actual is None else op(actual, expected)

    def identity(member, engine, argument):
        observed = member.get(engine)
        return None if observed is None else observed.get((("argument", argument),))

    def capacity(member, kind):
        return conjunction(
            identity(member, "is_building_type", kind),
            compare(member.get("level"), operator.ge, 1),
        )

    parameters = dict(reader.parameters)
    if "technology_query" in parameters:
        from technology_query_reference import evaluate

        return evaluate(reader, observations, root_facts)
    query = parameters.get("company_query")
    if reader.engine == "any_scope_building":

        def building(member):
            if query == "trade_business_pressure":
                return conjunction(
                    capacity(member, "building_trade_center"),
                    compare(member.get("weekly_profit"), operator.lt, 0),
                    compare(member.get("cash_reserves_ratio"), operator.lt, 0.25)
                    if parameters["tier"] == "strong"
                    else True,
                )
            if query == "existing_business":
                strong = parameters["tier"] == "strong"
                return conjunction(
                    capacity(member, parameters["building"]),
                    compare(member["weekly_profit"], operator.gt, 0),
                    compare(member["occupancy"], operator.ge, 0.9 if strong else 0.75),
                    compare(member["cash_reserves_ratio"], operator.gt, 0.5) if strong else True,
                )
            assert query in {None, "port_method"}
            return conjunction(
                capacity(member, parameters.get("building", "building_port")),
                identity(member, "has_active_production_method", parameters["method"]),
                compare(member["level"], operator.ge, int(parameters.get("min_level", "1"))),
            )

        return existential(observations[reader.engine], building)
    if reader.engine == "any_scope_state":

        def state(member):
            if parameters.get("state_query") == "turmoil_above":
                return compare(member["turmoil"], operator.gt, float(parameters["threshold"]))
            if "threshold" in parameters:
                return compare(member["market_access"], operator.lt, float(parameters["threshold"]))
            if parameters == {"state_query": "tax_capacity_shortfall"}:
                return conjunction(
                    member["is_incorporated"],
                    compare(member["tax_capacity"], operator.lt, member["tax_capacity_usage"])
                    if member["tax_capacity_usage"] is not None
                    else None,
                )
            assert query in {"rail_infrastructure", "power_scarcity"}
            railway = query == "rail_infrastructure"
            good = "transportation" if railway else "electricity"
            return conjunction(
                existential(
                    member["any_scope_building"],
                    lambda candidate: capacity(
                        candidate, "building_railway" if railway else "building_power_plant"
                    ),
                ),
                compare(member["infrastructure_delta"], operator.lt, 0) if railway else True,
                compare(
                    member[f"sg:{good}"]["state_goods_pricier"],
                    operator.gt,
                    float(parameters["minimum_price"]),
                )
                if "minimum_price" in parameters
                else True,
            )

        return existential(observations[reader.engine], state)
    assert reader.engine in {"any_political_movement", "any_interest_group"}

    def political(member):
        movement = reader.engine == "any_political_movement"
        engine = "law_enactment_stance" if movement else "law_stance"
        return conjunction(
            compare(
                member[engine].get((("law", "law_type:" + parameters["law"]),)), operator.gt, 0
            ),
            compare(
                member["political_movement_support"],
                operator.ge,
                float(parameters["minimum_support"]),
            )
            if movement
            else True,
        )

    return existential(observations[reader.engine], political)


@pytest.mark.integration
# This is an all-corpus correctness check with independent PDX parsing, not a
# 200ms microbenchmark. Keep all 100 examples and the pytest 300-second limit.
@settings(deadline=None)
@example(seed=284, is_ai=True, missing_target=False)
@given(seed=st.integers(0, 1000000), is_ai=st.booleans(), missing_target=st.booleans())
def test_every_actual_adapter_branch_matches_reference_with_typed_inputs(
    real_generated_branches,
    seed,
    is_ai,
    missing_target,
):
    import random

    from pdx import observation_queries

    rng = random.Random(seed)
    collections = _adapter_collection_observations(seed)
    for policy, blocks in real_generated_branches:
        scopes: dict = {
            "ROOT": {},
            "scope:target_country": {},
            "scope:target_state": {},
            "scope:overlord": {},
            "scope:interest_group": {},
        }
        actor = scopes["ROOT"]
        for part in policy.actor_path:
            actor = actor.setdefault(part, {})
        actor["is_ai"] = is_ai
        values = {}
        sampled = {}
        for reader in policy.readers:
            signature = (
                reader.scope,
                reader.path,
                reader.engine,
                reader.argument,
                reader.parameters,
            )
            if signature not in sampled:
                sampled[signature] = (
                    rng.choice([True, False])
                    if reader.kind == "boolean"
                    else rng.choice(
                        [-1.0, 0.0, 0.1, 0.25, 0.5, 1.0, 12.0, 25.0, 50.0, 75.0, 100.0, 10000000.0]
                    )
                )
            value = sampled[signature]
            # This reader names the same physical actor already chosen above;
            # it cannot be an independent random observation of another AI.
            # Keep the draw so every other historical scalar input is unchanged.
            if (
                reader.engine == "is_ai"
                and reader.scope == "root"
                and reader.path == policy.actor_path
            ):
                value = is_ai
            scope = "ROOT" if reader.scope == "root" else "scope:" + reader.scope
            current = scopes[scope]
            for part in reader.path:
                current = current.setdefault(part, {})
            if reader.engine in observation_queries.QUERY_ENGINES:
                assert reader.scope == "root"
                assert not reader.path
                current[reader.engine] = collections[reader.engine]
                # Resolve aggregate readers after every scalar ROOT observation
                # exists; research queries refer to laws, goods and prior tech.
                continue
            if reader.engine == "is_production_method_active":
                parameters = dict(reader.parameters)
                current.setdefault(reader.engine, {}).setdefault(parameters["building_type"], {})[
                    parameters["production_method"]
                ] = value
            elif reader.parameters or reader.argument is not None or reader.value_field is not None:
                parameters = dict(reader.parameters)
                if reader.argument is not None:
                    parameters["argument"] = reader.argument
                current.setdefault(reader.engine, {})[tuple(sorted(parameters.items()))] = value
            else:
                current[reader.engine] = value
            if reader.engine.startswith("sitai_context_"):
                current["sitai_context_known_" + reader.engine.removeprefix("sitai_context_")] = (
                    True
                )
            # The country-state interpreter separately proves active/TTL semantics.
            # This layer tests the typed active interface against adapter branches.
            if reader.engine == "has_variable" and (reader.argument or "").startswith(
                "sitai_route_"
            ):
                current[f"{reader.argument}_active"] = value
            values[reader.key] = None if missing_target and reader.scope != "root" else value
        for reader in policy.readers:
            if reader.engine in observation_queries.QUERY_ENGINES:
                values[reader.key] = _adapter_query_reference(reader, collections, scopes["ROOT"])
        if missing_target:
            scopes.pop("scope:target_country")
            scopes.pop("scope:target_state")
            scopes.pop("scope:overlord")
            scopes.pop("scope:interest_group")
        reference = decision_rules.evaluate(policy, values, is_ai=is_ai)
        operations = {rule.id: rule.operation for rule in policy.rules}
        for field in blocks:
            observed = real_generated_branches.prepared[id(policy)][field].select(scopes)
            actual = (
                (observed.operation, observed.delta) if observed.operation is not None else None
            )
            expected = reference.get(field)
            if expected is None:
                assert actual in (None, ("multiply", 1.0)), field
            else:
                assert actual == (operations[expected[0]], expected[1]), field


@pytest.fixture(scope="module")
def supply_candidate():
    name = "common/ai_strategies/00_default_strategy.txt"
    goods_name = "common/goods/00_goods.txt"
    evidence_name = "common/scripted_triggers/evidence.txt"
    text = """# 合成默认策略，绝非游戏原件
ai_strategy_default = {
    weight = { value = 0 }
    possible = { in_default = no }
    goods_stances = { grain = { stance = wants_high_supply } }
}
"""
    inputs = {
        name: text,
        goods_name: "tools = {} glass = {} grain = {}\n",
        evidence_name: "example = { market = { mg:grain = { market_goods_pricier > 0.25 market_goods_delta < 0 } } }\n",
    }
    policy = decision_rules.from_data(
        {
            "schema": 1,
            "baseline_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "domains": {"market": True},
            "readers": {
                "default": {
                    "engine": "in_default",
                    "scope": "root",
                    "unit": "boolean",
                    "kind": "boolean",
                }
            },
            "rules": [
                {
                    "id": "synthetic",
                    "domain": "market",
                    "field": "ai_strategy_default.weight",
                    "priority": 50,
                    "value": 1.1,
                    "conditions": [{"fact": "default", "op": "=", "value": False}],
                    "why": "合成输入",
                    "counterexample": "不改变原版零值",
                }
            ],
        },
        source_sha256="0" * 64,
    )
    adapters = decision_adapters.AdapterSet(
        tuple((key, hashlib.sha256(value.encode()).hexdigest()) for key, value in inputs.items()),
        ((name, policy),),
        "0" * 64,
        supply=decision_adapters.SupplyPlan(name, ("glass", "tools"), 0.25),
    )
    files, contract = decision_adapters.build(adapters, texts=inputs)
    document = parse_text(files[name])
    assert not document.errors
    trigger = document.top_assignments[0].value
    assert isinstance(trigger, Block)
    for key in ("goods_stances", "tools", "trigger"):
        child = trigger.first(key)
        assert child is not None
        assert isinstance(child.value, Block)
        trigger = child.value
    # 解释真实产物的 trigger；只把其 AST 放入现有独立解释器支持的数值包装。
    branch = Block(
        [
            Assignment(
                "if",
                "=",
                Block(
                    [
                        Assignment("limit", "=", Block([Assignment("ROOT", "=", trigger)])),
                        Assignment("multiply", "=", Scalar("1.1")),
                    ]
                ),
            )
        ]
    )
    return adapters, inputs, files, contract, branch


@given(
    is_ai=st.booleans(),
    price=st.floats(-0.75, 0.75),
    balance=st.integers(-100000, 100000),
    missing=st.booleans(),
)
def test_supply_stance_matches_actual_scarcity_and_never_forces_trade(
    supply_candidate, is_ai, price, balance, missing
):
    _, _, _, _, branch = supply_candidate
    country = {"is_ai": is_ai}
    if not missing:
        country["market"] = {
            "mg:tools": {"market_goods_pricier": price, "market_goods_delta": balance}
        }
    actual = _interpret_adjustments(branch, {"ROOT": country})
    expected = ("multiply", 1.1) if is_ai and not missing and price > 0.25 and balance < 0 else None
    assert actual == expected


def test_supply_disable_and_declared_switch_preserve_vanilla(supply_candidate):
    adapters, inputs, files, contract, _ = supply_candidate
    assert contract["supply_plan"]["behavior_verified"] is False
    assert contract["supply_plan"]["goods"] == ["glass", "tools"]
    assert "grain = { stance = wants_high_supply }" in next(iter(files.values()))
    assert decision_adapters.build(adapters, texts=inputs, enabled_domains=frozenset())[0] == {}
    policies = tuple(
        (name, replace(policy, enabled_domains=frozenset())) for name, policy in adapters.policies
    )
    disabled = replace(adapters, policies=policies)
    outputs, metadata = decision_adapters.build(disabled, texts=inputs)
    assert outputs == {}
    assert metadata["supply_plan"] is None


@pytest.mark.parametrize("good", ["grain", "invented"])
def test_supply_cannot_replace_existing_stance_or_reference_unknown_good(supply_candidate, good):
    adapters, inputs, _, _, _ = supply_candidate
    with pytest.raises(ValueError, match="不能覆写"):
        decision_adapters.build(
            replace(adapters, supply=replace(adapters.supply, goods=(good,))), texts=inputs
        )


def _relative_data():
    baseline = "ai_strategy_default = { subject_value = { value = 50 if = { limit = { OR = { scope:target_country = { is_subject_of = root } can_reach_target_country = { TARGET_COUNTRY = scope:target_country } } } add = 0 } gdp = 0 } }\n"
    if version_contracts.active_version() == "1.15.0":
        baseline = baseline.replace(
            "can_reach_target_country =", "can_reach_target_country_to_subjugate ="
        )
    return baseline, {
        "schema": 1,
        "baseline_sha256": hashlib.sha256(baseline.encode()).hexdigest(),
        "domains": {"subjects": True},
        "readers": {
            key: {
                "engine": "gdp",
                "scope": scope,
                "unit": "annual_gdp_currency",
                "kind": "number",
                "minimum": 0,
            }
            for key, scope in (("own", "root"), ("target", "target_country"))
        },
        "rules": [
            {
                "id": "relative_administration_cost",
                "domain": "subjects",
                "field": "subject_value",
                "priority": 100,
                "operation": "add",
                "value": -5,
                "conditions": [{"fact": "target", "op": ">", "value": {"fact": "own"}}],
                "why": "相对规模的合成反例",
                "counterexample": "无读数不猜测，GDP不预测胜率",
            }
        ],
    }


@given(
    own=st.integers(0, 10**12),
    target=st.integers(0, 10**12),
    is_ai=st.booleans(),
    missing=st.booleans(),
)
def test_relative_comparison_actual_script_and_reference_agree(own, target, is_ai, missing):
    baseline, data = _relative_data()
    rules = decision_rules.from_data(data, source_sha256="a" * 64)
    text = decision_rules.patch(baseline, rules, baseline=baseline)
    match = re.search(r"# SITAI BEGIN information:subject_value\n(.*?)# SITAI END", text, re.DOTALL)
    assert match is not None
    scopes = {"ROOT": {"is_ai": is_ai, "gdp": own}}
    if not missing:
        scopes["scope:target_country"] = {"gdp": target}
    actual = _interpret_adjustments(parse_text(match.group(1)).root, scopes)
    values = {"own": own, "target": None if missing else target}
    expected = is_ai and not missing and target > own
    assert actual == (("add", -5) if expected else None)
    assert bool(decision_rules.evaluate(rules, values, is_ai=is_ai)) == expected
    contract = decision_rules.contract(rules)
    entries = contract["rules"]
    assert isinstance(entries, list)
    entry = entries[0]
    assert entry["inputs"] == ["own", "target"]
    assert entry["conditions"][0]["value"] == {"fact": "own"}


@pytest.mark.parametrize("missing", ["own", "target"])
@pytest.mark.parametrize("bad", [None, -1, float("nan"), float("inf"), True, "100"])
def test_relative_comparison_unknown_or_invalid_inputs_never_grant_lower_priority(missing, bad):
    baseline, data = _relative_data()
    data["rules"].append(
        {
            **data["rules"][0],
            "id": "lower",
            "priority": 50,
            "value": 3,
            "conditions": [{"fact": "own", "op": ">=", "value": 0}],
        }
    )
    rules = decision_rules.from_data(data, source_sha256="a" * 64)
    assert not decision_rules.evaluate(rules, {"own": 100, "target": 200, missing: bad}, is_ai=True)
    # 数值边界可表达的非法数值和缺失作用域也核对真实生成分支。
    if bad in (None, -1) and type(bad) is not bool:
        text = decision_rules.patch(baseline, rules, baseline=baseline)
        match = re.search(
            r"# SITAI BEGIN information:subject_value\n(.*?)# SITAI END", text, re.DOTALL
        )
        assert match is not None
        scopes = {"ROOT": {"is_ai": True, "gdp": 100}, "scope:target_country": {"gdp": 200}}
        name = "ROOT" if missing == "own" else "scope:target_country"
        if bad is None:
            scopes.pop(name)
        else:
            scopes[name]["gdp"] = bad
        assert _interpret_adjustments(parse_text(match.group(1)).root, scopes) in (
            None,
            ("multiply", 1.0),
        )


@pytest.mark.parametrize(
    "reference",
    [
        None,
        {},
        {"fact": "target"},
        {"fact": "bad"},
        {"fact": "own", "extra": 1},
        {"fact": "own } add = 999"},
    ],
)
def test_relative_comparison_rejects_unknown_self_or_injected_references(reference):
    _, data = _relative_data()
    data["rules"][0]["conditions"][0]["value"] = reference
    with pytest.raises(ValueError):
        decision_rules.from_data(data, source_sha256="a" * 64)


@pytest.mark.parametrize(
    "change", [{"unit": "persons"}, {"kind": "boolean", "minimum": None}, {"value_field": "value"}]
)
def test_relative_comparison_cannot_mix_units_or_use_unproven_getters(change):
    _, data = _relative_data()
    data["readers"]["own"].update(change)
    if change.get("kind") == "boolean":
        data["readers"]["own"].pop("minimum")
    with pytest.raises(ValueError):
        decision_rules.from_data(data, source_sha256="a" * 64)


@pytest.mark.parametrize(
    ("field", "owner"),
    [
        ("aggression", "diplomacy"),
        ("diplomatic_play_support", "support"),
        ("recklessness", "diplomacy"),
    ],
)
def test_legacy_and_information_field_owners_cannot_silently_stack(field, owner):
    baseline, data = _relative_data()
    data["readers"]["target"]["scope"] = "root"
    data["rules"][0]["field"] = field
    rules = decision_rules.from_data(data, source_sha256="a" * 64)
    extensions = replace(
        decisions.load_extensions(),
        market_enabled=owner == "support",
        diplomacy_enabled=owner == "diplomacy",
    )
    policy = replace(decisions.load(), enabled=owner == "fiscal")
    with pytest.raises(ValueError, match="重复写入"):
        decisions.build(policy, baseline, extensions=extensions, information_rules=rules)


@pytest.mark.parametrize(
    "field", ["goods_stances", "goods_stances.tools", "goods_stances.tools.weight"]
)
def test_supply_append_uses_the_same_parent_child_writer_guard(supply_candidate, field):
    adapters, inputs, *_ = supply_candidate
    source, policy = adapters.policies[0]
    policy = replace(
        policy, rules=(replace(policy.rules[0], field=("ai_strategy_default", *field.split("."))),)
    )
    adapters = replace(adapters, policies=((source, policy),))
    with pytest.raises(ValueError, match=r"重复写入|父子字段"):
        decision_adapters.build(adapters, texts=inputs)


def _scopes_for_facts(policy, facts):
    scopes: dict = {"ROOT": {}}
    actor = scopes["ROOT"]
    for part in policy.actor_path:
        actor = actor.setdefault(part, {})
    actor["is_ai"] = True
    for reader in policy.readers:
        current = scopes.setdefault(
            "ROOT" if reader.scope == "root" else "scope:" + reader.scope, {}
        )
        for part in reader.path:
            current = current.setdefault(part, {})
        key = (
            (reader.engine, reader.parameters)
            if reader.parameters
            else (reader.engine, reader.argument)
            if reader.argument
            else reader.engine
        )
        current[key] = facts[reader.key]
        if reader.engine == "has_variable" and (reader.argument or "").startswith("sitai_route_"):
            current[f"{reader.argument}_active"] = facts[reader.key]
    return scopes


@pytest.mark.integration
def test_political_crisis_joins_known_safety_need_without_erasing_it(social_reform_joint_branches):
    from test_situated_joint_witnesses import _facts

    from pdx.situated import pdx_eval

    field = "law_regulatory_bodies.ai_enact_weight_modifier"
    policy, _ = next((p, b) for p, b in social_reform_joint_branches if field in b)
    facts = {
        r.key: False if r.kind == "boolean" else max(0.0, r.minimum or 0.0) for r in policy.readers
    }
    facts.update(
        legitimacy=60,
        radical_share=0.3,
        current_no_workers_rights=True,
        workplace_safety_present=False,
        industrial_workforce=0.2,
        bureaucracy=1,
    )
    crisis = {**facts, "legitimacy": 24, "insurrection": True}
    # 工业劳力对应的安全收益+12；政治危机-10独立加入。未知只退出该原因。
    cases = [
        (facts, 12),
        (crisis, 2),
        ({**crisis, "radical_share": None}, 12),
        ({**crisis, "industrial_workforce": None}, -10),
        ({**crisis, "bureaucracy": -1}, -6),
    ]
    for values, expected in cases:
        reference = decision_rules.evaluate(policy, values, is_ai=True).get(field)
        assert reference is not None
        assert reference[1] == pytest.approx(expected)
        actual = pdx_eval.select(
            social_reform_joint_branches.scripts[id(policy)][field], _facts(policy, values)
        )
        assert actual.operation == "add"
        assert actual.delta == pytest.approx(expected)


@pytest.mark.integration
def test_same_government_benefit_is_gated_by_interest_group_resistance_in_generated_ast(
    real_generated_branches,
):
    """Political resistance downgrades continuity before hard boundaries remove it."""

    field = "ai_strategy_default.interest_group_government_weight"
    policy, blocks = next(
        (policy, blocks)
        for policy, blocks in real_generated_branches
        if any(rule.id == "structural_stable_government_member" for rule in policy.rules)
    )
    facts = {
        reader.key: False if reader.kind == "boolean" else max(0.0, reader.minimum or 0.0)
        for reader in policy.readers
    }
    facts.update(
        legitimacy=60,
        insurrection=False,
        candidate_ig_clout=0.2,
        candidate_ig_approval=1,
        candidate_ig_government=True,
    )
    paired = {
        "supported": (facts, ("add", 1.05)),
        "weak_clout": ({**facts, "candidate_ig_clout": 0.19}, ("add", 0.5)),
        "below_foundation_clout": ({**facts, "candidate_ig_clout": 0.09999}, None),
        "disapproving": ({**facts, "candidate_ig_approval": -1}, None),
        "outside_government": ({**facts, "candidate_ig_government": False}, None),
        "low_legitimacy": ({**facts, "legitimacy": 49}, ("add", 0.5)),
        "below_foundation_legitimacy": ({**facts, "legitimacy": 34.99999}, None),
    }
    rule_by_id = {rule.id: rule for rule in policy.rules}
    for name, (values, expected) in paired.items():
        actual = _interpret_adjustments(blocks[field], _scopes_for_facts(policy, values))
        reference = decision_rules.evaluate(policy, values, is_ai=True).get(field)
        reference = (
            None if reference is None else (rule_by_id[reference[0]].operation, reference[1])
        )
        assert reference == expected, name
        assert actual == expected, name


@pytest.mark.integration
def test_same_political_resistance_uses_observed_political_space_in_generated_ast(
    real_generated_branches,
):
    """Political unknowns remove only the capacity tier; finance does not erase need."""
    from test_situated_joint_witnesses import _facts

    from pdx.situated import pdx_eval

    field = "ai_strategy_default.negotiation_chance"
    policy, _blocks = next(
        (policy, blocks)
        for policy, blocks in real_generated_branches
        if any(rule.id == "remaining_organized_negotiation_need" for rule in policy.rules)
    )
    facts = {
        reader.key: False if reader.kind == "boolean" else max(0.0, reader.minimum or 0.0)
        for reader in policy.readers
    }
    facts.update(
        war=False,
        default=False,
        loans=False,
        debt_ratio=0.1,
        net_surplus=100,
        bureaucracy=100,
        legitimacy=60,
        insurrection=False,
        candidate_ig_clout=0.2,
        candidate_ig_approval=-1,
        candidate_ig_government=False,
        radical_share=0.3,
    )
    paired = {
        "funded": (facts, ("multiply", 1.25)),
        "no_surplus": ({**facts, "net_surplus": -1}, ("multiply", 1.25)),
        "high_debt": ({**facts, "debt_ratio": 0.41}, ("multiply", 1.25)),
        "loan_dependent": ({**facts, "loans": True}, ("multiply", 1.25)),
        "political_space_unknown": ({**facts, "legitimacy": None}, ("multiply", 1.1)),
        "candidate_unknown": ({**facts, "candidate_ig_clout": None}, None),
    }
    rule_by_id = {rule.id: rule for rule in policy.rules}
    for name, (values, expected) in paired.items():
        observed = pdx_eval.select(
            real_generated_branches.scripts[id(policy)][field], _facts(policy, values, is_ai=True)
        )
        actual = None if observed.operation is None else (observed.operation, observed.delta)
        reference = decision_rules.evaluate(policy, values, is_ai=True).get(field)
        reference = (
            None if reference is None else (rule_by_id[reference[0]].operation, reference[1])
        )
        assert reference == expected, name
        assert actual == expected, name


@pytest.mark.parametrize(
    ("source", "field", "before", "after", "expected", "financing_cost"),
    [
        (
            "02_labor_rights.txt",
            "law_regulatory_bodies",
            {"industrial_workforce": 0.2},
            {"industrial_workforce": 0.25},
            (12, 16),
            0,
        ),
        ("02_welfare.txt", "law_wage_subsidies", {"sol": 12}, {"sol": 10}, (-3, 13), 6),
    ],
)
@pytest.mark.integration
def test_stronger_social_need_does_not_accidentally_reduce_target_adjustment(
    social_reform_joint_branches, source, field, before, after, expected, financing_cost
):
    from test_situated_joint_witnesses import _facts

    from pdx.situated import pdx_eval

    policy, _ = next(
        (policy, blocks)
        for policy, blocks in social_reform_joint_branches
        if any(rule.field[0] == field for rule in policy.rules)
    )
    facts = {
        reader.key: False if reader.kind == "boolean" else max(0.0, reader.minimum or 0.0)
        for reader in policy.readers
    }
    facts.update(
        legitimacy=60,
        literacy=0.3,
        sol=10,
        population=2000000,
        industrial_workforce=0.2,
        skilled_workforce=0.1,
        current_no_workers_rights=True,
        workplace_safety_present=False,
        social_security_present=False,
        bureaucracy=1,
    )
    key = field + ".ai_enact_weight_modifier"
    assert expected[1] > expected[0]
    cases = [
        ({**facts, **before}, expected[0]),
        ({**facts, **after}, expected[1]),
        ({**facts, **after, "war": True}, expected[1]),
        ({**facts, **after, "default": True}, expected[1] - financing_cost),
        ({**facts, **after, "legitimacy": 0}, expected[1]),
        ({**facts, **after, "bureaucracy": -1}, expected[1] - 8),
        (
            {**facts, **after, "legitimacy": 0, "insurrection": True, "radical_share": 0.3},
            expected[1] - 10,
        ),
    ]
    for values, score in cases:
        reference = decision_rules.evaluate(policy, values, is_ai=True).get(key)
        assert reference is not None, source
        assert reference[1] == pytest.approx(score), source
        actual = pdx_eval.select(
            social_reform_joint_branches.scripts[id(policy)][key], _facts(policy, values)
        )
        assert actual.operation == "add", source
        assert actual.delta == pytest.approx(score), source


@pytest.fixture(scope="module")
def public_school_joint_generated():
    from pdx.situated import programs

    source = "common/laws/01_education_system.txt"
    adapters = decision_adapters.load()
    policy = programs.enable(dict(adapters.policies)[source], source=source)
    selected = replace(
        adapters, policies=((source, policy),), initial_values=(), scalar_values=(), supply=None
    )
    files, _ = decision_adapters.build(selected, country_policy=country_state.load())
    return policy, files[source]


@pytest.mark.integration
@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ({"peasant_share": 0.5}, {"peasant_share": 0.6}, (10, 12)),
        ({"current_private_schools": False}, {"current_private_schools": True}, (0, 10)),
    ],
)
def test_stronger_public_school_need_joins_exact_administrative_financial_and_political_costs(
    public_school_joint_generated, before, after, expected
):
    from test_situated_joint_witnesses import _facts

    from pdx.situated import pdx_eval

    policy, generated = public_school_joint_generated
    field = "law_public_schools.ai_enact_weight_modifier"
    match = re.search(
        rf"# SITAI BEGIN information:{re.escape(field)}\n(.*?)# SITAI END information:",
        generated,
        re.DOTALL,
    )
    assert match is not None
    values: dict[str, object] = {
        reader.key: False if reader.kind == "boolean" else 0 for reader in policy.readers
    }
    values.update(
        current_private_schools=True,
        literacy=0.3,
        peasant_share=0.5,
        bureaucracy=1,
        default=False,
        legitimacy=60,
        insurrection=False,
        radical_share=0.1,
    )

    def adjustment(changes):
        facts = {**values, **changes}
        observed = pdx_eval.select(match.group(1), _facts(policy, facts))
        reference = decision_rules.evaluate(policy, facts, is_ai=True).get(field)
        actual = observed.delta if observed.operation == "add" else 0
        assert actual == pytest.approx(reference[1] if reference else 0)
        return actual

    assert (adjustment(before), adjustment(after)) == expected
    for costs, delta in (
        ({"bureaucracy": -1}, -8),
        ({"default": True}, -6),
        ({"bureaucracy": -1, "default": True}, -14),
        ({"legitimacy": 20, "insurrection": True, "radical_share": 0.3}, -10),
        (
            {
                "legitimacy": 20,
                "insurrection": True,
                "radical_share": 0.3,
                "bureaucracy": -1,
                "default": True,
            },
            -24,
        ),
        ({"war": True}, 0),
        ({"loans": True}, 0),
        ({"legitimacy": 0}, 0),
    ):
        assert adjustment({**after, **costs}) == expected[1] + delta


@pytest.mark.parametrize("war", [False, True])
@pytest.mark.integration
def test_liquidity_pressure_is_cross_domain_and_preserves_wartime_defense(
    real_generated_branches, war
):
    from test_situated_writer_pdx_oracle import _facts

    from pdx.situated import pdx_eval

    policy, blocks = next(
        (p, b)
        for p, b in real_generated_branches
        if any(r.id == "target_strategy_goal_annex_country_liquidity" for r in p.rules)
    )
    facts = {
        r.key: False if r.kind == "boolean" else max(0.0, r.minimum or 0.0) for r in policy.readers
    }
    facts.update(
        war=war,
        default=False,
        loans=True,
        debt_ratio=0.6,
        bankruptcy_horizon=10,
        prospective_subject_population=1000000,
        own_army=100,
        target_army=0,
        own_navy=100,
        target_navy=0,
        navy=100,
        legitimacy=60,
        national_gdp=100000000,
        candidate_gdp=1000000,
    )
    field = "ai_strategy_default.wargoal_scores.annex_country"
    # Financing is a local cost of this concrete new commitment in peace and
    # war; it no longer uses a global liquidity intent to silence other needs.
    value = _interpret_adjustments(blocks[field], _scopes_for_facts(policy, facts))
    assert value == ("add", -4)
    used = {
        key for rule in policy.rules if ".".join(rule.field) == field for key in rule.input_keys()
    }
    for key in ("debt_ratio", "bankruptcy_horizon"):
        values = {**facts, key: None}
        result = decision_rules.evaluate(policy, values, is_ai=True)
        assert result.get(field, ("", 0))[1] == 0
        # The complete independent PDX oracle preserves numeric unknown values;
        # the old adjustment-only helper intentionally accepts known scalars.
        actual = pdx_eval.select(
            real_generated_branches.scripts[id(policy)][field],
            _facts(policy, {key: values[key] for key in used}, is_ai=True),
        )
        assert actual.operation is None
        assert actual.fallback == "unknown"
        assert actual.delta == 0


@pytest.mark.parametrize("fact", ["target_truce", "target_alliance", "target_relations"])
@pytest.mark.integration
def test_actual_diplomatic_commitment_is_a_bounded_cost_and_not_a_forced_action(
    real_generated_branches, fact
):
    policy, blocks = next(
        (p, b)
        for p, b in real_generated_branches
        if any(r.id == "target_strategy_goal_conquer_state_truce" for r in p.rules)
    )
    values = {
        r.key: False if r.kind == "boolean" else max(0.0, r.minimum or 0.0) for r in policy.readers
    }
    values.update(
        legitimacy=60,
        national_gdp=100000000,
        candidate_gdp=1000000,
        own_army=100,
        target_army=0,
        own_navy=50,
        target_navy=0,
        net_surplus=100,
        debt_ratio=0.1,
        prospective_subject_population=1000000,
    )
    values[fact] = 75 if fact == "target_relations" else True
    field = "ai_strategy_default.wargoal_scores.conquer_state"
    result = _interpret_adjustments(blocks[field], _scopes_for_facts(policy, values))
    assert result == ("add", -2 if fact == "target_relations" else -4)
    assert result is not None
    values["war"] = True
    wartime = decision_rules.evaluate(policy, values, is_ai=True)
    assert wartime[field][1] == result[1]
    values["war"] = False
    values[fact] = None
    unknown = decision_rules.evaluate(policy, values, is_ai=True)
    assert unknown.get(field, ("", 0))[1] == 0


@pytest.mark.parametrize(
    "change",
    [
        {"scope": "root"},
        {"parameters": {"who": "target_country", "type": "alliance"}},
        {"parameters": {"who": "root", "type": "invented"}},
        {"parameters": {"who": "root", "type": "alliance } add = 100"}},
    ],
)
def test_pairwise_treaty_reader_rejects_unprovided_context_or_injected_contract(change):
    _baseline, data = _relative_data()
    data["readers"]["target"] = {
        "engine": "has_diplomatic_pact",
        "scope": "target_country",
        "kind": "boolean",
        "unit": "boolean",
        "parameters": {"who": "root", "type": "embargo"},
        **change,
    }
    data["rules"][0]["conditions"] = [
        {"fact": "target", "op": "=", "value": True},
        {"fact": "own", "op": ">=", "value": 0},
    ]
    with pytest.raises(ValueError):
        decision_rules.from_data(data, source_sha256="a" * 64)


@pytest.mark.parametrize("article", ["alliance", "defensive_pact"])
def test_treaty_article_cannot_be_used_as_diplomatic_action_type(article):
    _baseline, data = _relative_data()
    data["readers"]["target"] = {
        "engine": "has_diplomatic_pact",
        "scope": "target_country",
        "kind": "boolean",
        "unit": "boolean",
        "parameters": {"who": "root", "type": article},
    }
    data["rules"][0]["conditions"] = [
        {"fact": "target", "op": "=", "value": True},
        {"fact": "own", "op": ">=", "value": 0},
    ]
    with pytest.raises(ValueError, match="外交"):
        decision_rules.from_data(data, source_sha256="a" * 64)


def test_alliance_reader_uses_current_native_treaty_interface():
    adapters = decision_adapters.load()
    reader = next(
        reader
        for _source, policy in adapters.policies
        for reader in policy.readers
        if reader.key == "target_alliance"
    )
    assert reader.engine == "has_treaty_alliance_with"
    assert dict(reader.parameters) == {"TARGET": "root"}


@pytest.mark.parametrize(
    "change",
    [
        {"scope": "root"},
        {"parameters": {}},
        {"parameters": {"target": "root"}},
        {"parameters": {"TARGET": "target_country"}},
        {"parameters": {"TARGET": "root } add = 100"}},
        {"parameters": {"TARGET": "root", "type": "alliance"}},
    ],
)
def test_native_alliance_reader_rejects_missing_wrong_or_injected_context(change):
    _baseline, data = _relative_data()
    data["readers"]["target"] = {
        "engine": "has_treaty_alliance_with",
        "scope": "target_country",
        "kind": "boolean",
        "unit": "boolean",
        "parameters": {"TARGET": "root"},
        **change,
    }
    data["rules"][0]["conditions"] = [
        {"fact": "target", "op": "=", "value": True},
        {"fact": "own", "op": ">=", "value": 0},
    ]
    with pytest.raises(ValueError):
        decision_rules.from_data(data, source_sha256="a" * 64)


@pytest.mark.integration
def test_native_alliance_definition_and_call_are_in_locked_sources():
    inputs = decision_adapters.read_inputs(decision_adapters.load())
    definition = inputs["common/scripted_triggers/00_diplomacy_triggers.txt"]
    # 核对真实签名和条约/条款遍历，不能仅因某处出现同名词就认为调用有效。
    match = re.search(
        r"has_treaty_alliance_with\s*=\s*\{(?P<body>.*?)\n\}\n\nhas_treaty_defensive_pact_with",
        definition,
        re.DOTALL,
    )
    assert match is not None
    body = match.group("body")
    assert re.search(r"binds\s*=\s*\$TARGET\$", body)
    assert re.search(r"any_scope_article\s*=\s*\{\s*has_type\s*=\s*alliance", body)
    consumer = inputs["common/ai_regional_objectives/00_ai_regional_objectives.txt"]
    assert re.search(r"has_treaty_alliance_with\s*=\s*\{\s*TARGET\s*=\s*root\s*\}", consumer)


@given(
    price=st.floats(-0.75, 0.75),
    balance=st.integers(-100, 100),
    missing=st.sampled_from([None, "ROOT", "owner", "market", "mg:tools", "scope:target_country"]),
)
def test_shared_scope_prefixes_match_frozen_unshared_contract(price, balance, missing):
    conditions = {
        ("root", ()): ["is_ai = yes"],
        ("root", ("owner",)): ["in_default = no"],
        ("root", ("owner", "market", "mg:tools")): [
            "market_goods_pricier > 0.25",
            "market_goods_delta < 0",
        ],
        ("target_country", ()): ["army_size > 0"],
    }
    # 优化前的冻结组合方式；不调用新生成器构造对照。
    previous = []
    for (scope, path), expressions in sorted(conditions.items()):
        name = "ROOT" if scope == "root" else "scope:" + scope
        body = " ".join(dict.fromkeys(expressions))
        for part in reversed(path):
            body = f"exists = {part} {part} = {{ {body} }}"
        previous.append(f"exists = {name} {name} = {{ {body} }}")
    old = " ".join(previous)
    new = decision_rules._scoped_conditions(conditions)
    scopes: dict = {
        "ROOT": {
            "is_ai": True,
            "owner": {
                "in_default": False,
                "market": {
                    "mg:tools": {"market_goods_pricier": price, "market_goods_delta": balance}
                },
            },
        },
        "scope:target_country": {"army_size": 10},
    }
    if missing in {"ROOT", "scope:target_country"}:
        scopes.pop(missing)
    elif missing:
        parent = scopes["ROOT"]
        for part in ("owner", "market", "mg:tools"):
            if part == missing:
                parent.pop(part)
                break
            parent = parent[part]

    def outcome(fragment):
        return _interpret_adjustments(
            parse_text("if = { limit = { " + fragment + " } multiply = 1.1 }").root, scopes
        )

    assert outcome(new) == outcome(old)
    assert new.count("exists = ROOT") == 1
    assert new.count("exists = owner") == 1
    assert new.count("exists = ") < old.count("exists = ")
