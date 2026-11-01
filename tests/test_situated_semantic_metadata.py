"""生成元数据必须包含独立 PDX 语义见证，但不冒充实机验收。"""

import json

import pytest

from pdx import decisions, distribution

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


def test_metadata_contains_legacy_behavior_witness_contract() -> None:
    _, _, files = distribution.package_inputs(include_engineering_metadata=True)
    metadata = json.loads(files[".metadata/metadata.json"])
    witness = metadata["situated_actions"]["legacy_behavior_witness_contract"]
    assert witness["expected"] == 1414
    assert witness["count"] == 1414
    assert witness["missing"] == []
    assert witness["mismatches"] == []
    assert witness["duplicate_ids"] == []
    assert witness["behavior_quality"] == "not_evaluated"
