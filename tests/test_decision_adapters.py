"""多消费者补丁：合成离线反例、属性测试和原件逐字保留契约。"""

from __future__ import annotations

import hashlib
import math
import operator
import re
import tomllib
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pdx import config, decision_adapters, decision_rules, decisions
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.textio import normalized_text

if TYPE_CHECKING:
    from pathlib import Path


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


def test_declared_sources_have_consumers_and_real_bounded_conditions():
    adapters = decision_adapters.load()
    rules = [rule for _, policy in adapters.policies for rule in policy.rules]
    assert len(rules) == len(
        tomllib.loads(decision_adapters.SOURCE.read_text(encoding="utf-8"))["rules"]
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
        else:
            assert policy.actor_path == ()
        if "/laws/" in name:
            for rule in policy.rules:
                assert rule.operation == "add"
                if rule.id.startswith("political_capacity_"):
                    assert rule.value == -5
                    assert {condition.fact for condition in rule.conditions} == {
                        "legitimacy",
                        "insurrection",
                        "radical_share",
                    }
                else:
                    assert 0 < rule.value <= 20
        else:
            for rule in policy.rules:
                if rule.operation == "add":
                    assert rule.id.startswith(("coordinated_", "comparative_", "structural_"))
                    assert rule.value in {-5, 3, 1.05}
                    assert rule.field[0] == "ai_strategy_default"
                else:
                    assert rule.operation == "multiply"
                    assert 0.9 <= rule.value <= 1.2
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
    files, contract = decision_adapters.build(adapters)
    assert len(files) == 38
    consumers = contract["consumers"]
    assert isinstance(consumers, list)
    assert len(consumers) == len(files)
    for name, text in files.items():
        baseline = normalized_text((config.GAME / name).read_text(encoding="utf-8-sig"))
        assert not parse_text(text).errors
        assert parse_text(text).top_keys == parse_text(baseline).top_keys
        restored = re.sub(
            r"\n\t\t# SITAI BEGIN information:[^\n]+\n.*?# SITAI END information:[^\n]+\n\t",
            "",
            text,
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


@pytest.fixture(scope="module")
def real_generated_branches():
    if not (config.GAME / "common/laws/readme.md").is_file():
        pytest.skip("需要锁定版本的游戏原件")
    adapters = decision_adapters.load()
    files, _ = decision_adapters.build(adapters)
    result = []
    for source, policy in adapters.policies:
        blocks = {}
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
        result.append((policy, blocks))
    return result


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
        if key == "exists":
            assert isinstance(value, Scalar)
            return value.unquoted in (
                scopes
                if value.unquoted == "ROOT" or value.unquoted.startswith("scope:")
                else current
            )
        if isinstance(value, Block):
            values = list(value.assignments())
            if key in {"is_production_method_active", "has_diplomatic_pact"}:
                expected_keys = (
                    {"building_type", "production_method"}
                    if key == "is_production_method_active"
                    else {"who", "type"}
                )
                assert {item.key for item in values} == expected_keys
                pairs = []
                for item in values:
                    assert isinstance(item.value, Scalar)
                    pairs.append((item.key, item.value.unquoted))
                parameters = tuple(sorted(pairs))
                return current.get((key, parameters)) is True
            if key in {"pop_type_percent_country", "radical_fraction", "loyalist_fraction"} and any(
                item.key == "pop_type" for item in values
            ):
                parameter_items = [item for item in values if item.key == "pop_type"]
                assert len(parameter_items) == 1
                assert isinstance(parameter_items[0].value, Scalar)
                signature = (
                    key,
                    (("pop_type", parameter_items[0].value.unquoted),),
                )
                actual = current.get(signature)
                value_key = "percent" if key == "pop_type_percent_country" else "value"
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

    matched = False
    for branch in block.assignments():
        assert branch.key in {"if", "else_if"}
        assert isinstance(branch.value, Block)
        if branch.key == "if":
            matched = False
        if matched:
            continue
        limit = branch.value.first("limit")
        assert limit is not None
        assert isinstance(limit.value, Block)
        if all(condition(item, {}) for item in limit.value.assignments()):
            matched = True
            adjustments = [item for item in branch.value.assignments() if item.key != "limit"]
            assert len(adjustments) == 1
            adjustment = adjustments[0]
            assert isinstance(adjustment.value, Scalar)
            return adjustment.key, float(adjustment.value.unquoted)
    return None


@pytest.fixture(scope="module")
def population_candidate():
    source = "law_demo = { ai_enact_weight_modifier = { value = 0 } }\n"
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
                    "value_field": "percent",
                    "parameters": {"pop_type": "peasants"},
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
        reader_evidence="pop_type_percent_country = { pop_type = peasants percent > 0.6 }",
    )
    match = re.search(r"# SITAI BEGIN information:[^\n]+\n(.*?)# SITAI END", script, re.DOTALL)
    assert match is not None
    return policy, parse_text(match.group(1)).root


@given(share=st.floats(0, 1, allow_nan=False), is_ai=st.booleans())
def test_population_selector_matches_independent_generated_ast(population_candidate, share, is_ai):
    policy, block = population_candidate
    scopes = {
        "ROOT": {"is_ai": is_ai, ("pop_type_percent_country", (("pop_type", "peasants"),)): share}
    }
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


@pytest.mark.integration
@given(seed=st.integers(0, 1000000), is_ai=st.booleans(), missing_target=st.booleans())
def test_every_actual_adapter_branch_matches_reference_with_typed_inputs(
    real_generated_branches,
    seed,
    is_ai,
    missing_target,
):
    import random

    rng = random.Random(seed)
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
            scope = "ROOT" if reader.scope == "root" else "scope:" + reader.scope
            current = scopes[scope]
            for part in reader.path:
                current = current.setdefault(part, {})
            physical_key = (
                (reader.engine, reader.parameters)
                if reader.parameters
                else (reader.engine, reader.argument)
                if reader.argument is not None
                else reader.engine
            )
            current[physical_key] = value
            values[reader.key] = None if missing_target and reader.scope != "root" else value
        if missing_target:
            scopes.pop("scope:target_country")
            scopes.pop("scope:target_state")
            scopes.pop("scope:overlord")
            scopes.pop("scope:interest_group")
        reference = decision_rules.evaluate(policy, values, is_ai=is_ai)
        operations = {rule.id: rule.operation for rule in policy.rules}
        for field, block in blocks.items():
            actual = _interpret_adjustments(block, scopes)
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
        ("aggression", "fiscal"),
        ("diplomatic_play_support", "support"),
        ("recklessness", "diplomacy"),
        ("subject_value", "subjects"),
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
        subjects_enabled=owner == "subjects",
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
    scopes: dict = {"ROOT": {"is_ai": True}}
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
    return scopes


@pytest.mark.parametrize(
    ("source", "field", "before", "after"),
    [
        (
            "01_education_system.txt",
            "law_public_schools",
            {"peasant_share": 0.5},
            {"peasant_share": 0.6},
        ),
        (
            "01_education_system.txt",
            "law_public_schools",
            {"current_private_schools": False},
            {"current_private_schools": True},
        ),
        (
            "02_labor_rights.txt",
            "law_regulatory_bodies",
            {"radical_share": 0.1},
            {"radical_share": 0.3},
        ),
        ("02_welfare.txt", "law_wage_subsidies", {"radical_share": 0.1}, {"radical_share": 0.3}),
    ],
)
def test_stronger_social_need_does_not_accidentally_reduce_target_adjustment(
    real_generated_branches, source, field, before, after
):
    policy, blocks = next(
        (policy, blocks)
        for policy, blocks in real_generated_branches
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
        current_private_schools=True,
    )
    key = field + ".ai_enact_weight_modifier"
    low = _interpret_adjustments(blocks[key], _scopes_for_facts(policy, {**facts, **before}))
    high = _interpret_adjustments(blocks[key], _scopes_for_facts(policy, {**facts, **after}))
    assert low is not None, source
    assert high is not None, source
    assert low[0] == high[0] == "add"
    assert high[1] >= low[1] >= 15
    for guard in ({"war": True}, {"default": True}, {"legitimacy": 0}):
        blocked = _interpret_adjustments(
            blocks[key], _scopes_for_facts(policy, {**facts, **after, **guard})
        )
        assert blocked is None or blocked[1] <= 0


@pytest.mark.parametrize("war", [False, True])
def test_liquidity_pressure_is_cross_domain_and_preserves_wartime_defense(
    real_generated_branches, war
):
    policy, blocks = next(
        (p, b)
        for p, b in real_generated_branches
        if any(r.id.startswith("coordinated_liquidity_") for r in p.rules)
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
        target_army=50,
        own_navy=100,
        target_navy=10,
        navy=100,
        legitimacy=60,
        national_gdp=100000000,
        candidate_gdp=1000000,
    )
    for rule in policy.rules:
        if not rule.id.startswith("coordinated_liquidity_"):
            continue
        value = _interpret_adjustments(
            blocks[".".join(rule.field)], _scopes_for_facts(policy, facts)
        )
        if not war:
            assert value == (rule.operation, rule.value)
        else:
            assert value is None or value[1] >= (1 if value[0] == "multiply" else 0)
    for key in ("debt_ratio", "bankruptcy_horizon"):
        values = {**facts, "war": False, key: None}
        result = decision_rules.evaluate(policy, values, is_ai=True)
        assert all(
            not rule_id.startswith("coordinated_liquidity_") for rule_id, _ in result.values()
        )


@pytest.mark.parametrize("fact", ["target_truce", "target_alliance", "target_relations"])
def test_actual_diplomatic_commitment_is_a_bounded_cost_and_not_a_forced_action(
    real_generated_branches, fact
):
    policy, blocks = next(
        (p, b)
        for p, b in real_generated_branches
        if any(r.id.startswith("comparative_commitment_") for r in p.rules)
    )
    values = {
        r.key: False if r.kind == "boolean" else max(0.0, r.minimum or 0.0) for r in policy.readers
    }
    values.update(
        legitimacy=60,
        national_gdp=100000000,
        candidate_gdp=1000000,
        own_army=100,
        target_army=50,
        own_navy=50,
        target_navy=10,
        net_surplus=100,
        debt_ratio=0.1,
        prospective_subject_population=1000000,
    )
    values[fact] = 75 if fact == "target_relations" else True
    field = "ai_strategy_default.wargoal_scores.conquer_state"
    result = _interpret_adjustments(blocks[field], _scopes_for_facts(policy, values))
    assert result == ("add", -5)
    values["war"] = True
    wartime = decision_rules.evaluate(policy, values, is_ai=True)
    assert not wartime.get(field, ("", 0))[0].startswith(
        ("comparative_commitment_", "comparative_amicable_")
    )
    values["war"] = False
    values[fact] = None
    unknown = decision_rules.evaluate(policy, values, is_ai=True)
    assert field not in unknown


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
        "parameters": {"who": "root", "type": "alliance"},
        **change,
    }
    data["rules"][0]["conditions"] = [
        {"fact": "target", "op": "=", "value": True},
        {"fact": "own", "op": ">=", "value": 0},
    ]
    with pytest.raises(ValueError):
        decision_rules.from_data(data, source_sha256="a" * 64)


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
