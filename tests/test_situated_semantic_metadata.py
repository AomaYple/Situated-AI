"""生成元数据必须包含独立 PDX 语义见证，但不冒充实机验收。"""

import json

import pytest

from pdx import config, decisions, distribution
from pdx.situated import action_instances
from pdx.situated.compiler import load_model

pytestmark = pytest.mark.unit


def test_metadata_contains_independent_pdx_semantic_witness() -> None:
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


def test_offline_metadata_serializes_legacy_behavior_witness_contract(monkeypatch) -> None:
    """只隔离最终报告装配；实际 AST 见证由下方冻结树/重生成测试负责。"""
    sentinel = {"evidence": "metadata_assembly_test_only", "sentinel": ["final_texts"]}
    calls = []

    def witness(instances, texts):
        assert len([item for item in instances if item.kind == "rule_action"]) == 1455
        assert "common/ai_strategies/00_default_strategy.txt" in texts
        assert all(name.endswith(".txt") for name in texts)
        calls.append(texts)
        return sentinel

    monkeypatch.setattr(action_instances, "behavior_witness_contract", witness)
    files = decisions.build(extensions=decisions.load_extensions(profile="release"))
    metadata = json.loads(files[".metadata/metadata.json"])
    assert len(calls) == 1
    assert metadata["situated_actions"]["legacy_behavior_witness_contract"] == sentinel


def _assert_legacy_contract(witness) -> None:
    assert witness["expected"] == 1455
    assert witness["count"] == 1455
    assert witness["missing"] == []
    assert witness["mismatches"] == []
    assert witness["duplicate_ids"] == []
    assert witness["behavior_quality"] == "not_evaluated"


def test_frozen_production_contains_legacy_behavior_witness_contract() -> None:
    production = config.REPO / "mod"
    files = {
        path.relative_to(production).as_posix(): path.read_text(encoding="utf-8")
        for path in (production / "common").rglob("*.txt")
    }
    _assert_legacy_contract(
        action_instances.behavior_witness_contract(load_model().action_instances, files)
    )


@pytest.mark.integration
def test_metadata_contains_legacy_behavior_witness_contract() -> None:
    _, _, files = distribution.package_inputs(include_engineering_metadata=True)
    metadata = json.loads(files[".metadata/metadata.json"])
    _assert_legacy_contract(metadata["situated_actions"]["legacy_behavior_witness_contract"])
