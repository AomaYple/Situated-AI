"""生成元数据必须包含独立 PDX 语义见证，但不冒充实机验收。"""

import json

import pytest
from _situated_sources import production_policy_sources

from pdx import config, decisions, distribution, version_contracts
from pdx.situated import action_instances, lowering
from pdx.situated.compiler import load_model

pytestmark = pytest.mark.unit


@pytest.fixture
def historical_assembly_contract():
    """Isolate offline metadata assembly using the frozen historical generation."""
    with version_contracts.select_version("1.14.5"):
        yield


def test_metadata_contains_independent_pdx_semantic_witness(historical_assembly_contract) -> None:
    metadata = json.loads(
        decisions.build(extensions=decisions.load_extensions(profile="release"))[
            ".metadata/metadata.json"
        ]
    )
    witness = metadata["situated_actions"]["independent_pdx_semantics"]
    assert witness["consumer_count"] >= 8
    assert {
        "diplomatic_play_neutrality",
        "change_law_chance",
        "economic_vs_government_spending_balance",
        "recklessness",
    } <= set(witness["witnesses"])
    assert witness["evidence"] == "static_semantic_witness"
    assert witness["behavior_quality"] == "not_evaluated"


def test_offline_metadata_serializes_legacy_behavior_witness_contract(
    monkeypatch, historical_assembly_contract
) -> None:
    """只隔离最终报告装配；实际 AST 见证由下方冻结树/重生成测试负责。"""
    sentinel = {"evidence": "metadata_assembly_test_only", "sentinel": ["final_texts"]}
    calls = []

    numeric_calls = []
    ast_calls = []
    collect_numeric = lowering.witnesses
    collect_ast = lowering.ast_witnesses

    def numeric(texts):
        assert "common/ai_strategies/00_default_strategy.txt" in texts
        assert all(name.endswith(".txt") for name in texts)
        result = collect_numeric(texts)
        numeric_calls.append(result)
        return result

    def ast(texts):
        result = collect_ast(texts)
        ast_calls.append(result)
        return result

    def witness(instances, generated):
        assert len([item for item in instances if item.kind == "rule_action"]) == len(
            production_policy_sources().rules
        )
        assert {
            (item.source, item.rule_id, item.consumer_field)
            for item in instances
            if item.kind == "rule_action"
        } == production_policy_sources().rules
        assert generated is numeric_calls[-1]
        assert isinstance(generated, tuple)
        assert all(item.source.endswith(".txt") for item in generated)
        calls.append(generated)
        return sentinel

    monkeypatch.setattr(lowering, "witnesses", numeric)
    monkeypatch.setattr(lowering, "ast_witnesses", ast)
    monkeypatch.setattr(action_instances, "_behavior_witness_contract", witness)
    for count in (1, 2):
        files = decisions.build(extensions=decisions.load_extensions(profile="release"))
        metadata = json.loads(files[".metadata/metadata.json"])
        assert len(calls) == len(numeric_calls) == len(ast_calls) == count
        assert metadata["situated_actions"]["legacy_behavior_witness_contract"] == sentinel
    assert numeric_calls[0] == numeric_calls[1]
    assert numeric_calls[0] is not numeric_calls[1]
    assert ast_calls[0] == ast_calls[1]
    assert ast_calls[0] is not ast_calls[1]


def _assert_legacy_contract(witness) -> None:
    assert witness["expected"] == len(production_policy_sources().rules)
    assert witness["count"] == len(production_policy_sources().rules)
    assert witness["missing"] == []
    assert witness["mismatches"] == []
    assert witness["duplicate_ids"] == []
    assert witness["behavior_quality"] == "not_evaluated"


def test_current_frozen_tree_contains_its_own_legacy_behavior_witness_contract() -> None:
    production = config.REPO / "mod"
    files = {
        path.relative_to(production).as_posix(): path.read_text(encoding="utf-8")
        for path in (production / "common").rglob("*.txt")
    }
    # mod/ is the current complete release tree; its metadata must use the same identity.
    with version_contracts.select_version("1.15.1"):
        _assert_legacy_contract(
            action_instances.behavior_witness_contract(load_model().action_instances, files)
        )


@pytest.mark.integration
def test_metadata_contains_legacy_behavior_witness_contract() -> None:
    _, _, files = distribution.package_inputs(include_engineering_metadata=True)
    metadata = json.loads(files[".metadata/metadata.json"])
    witness = metadata["situated_actions"]["legacy_behavior_witness_contract"]
    _assert_legacy_contract(witness)
    final_texts = {
        name: text
        for name, text in files.items()
        if name.startswith("common/") and name.endswith(".txt") and isinstance(text, str)
    }
    actual = action_instances.behavior_witness_contract(load_model().action_instances, final_texts)
    _assert_legacy_contract(actual)
    assert actual == witness
