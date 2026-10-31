"""生成元数据必须包含独立 PDX 语义见证，但不冒充实机验收。"""

import json

import pytest

from pdx import decisions

pytestmark = pytest.mark.unit


def test_metadata_contains_independent_pdx_semantic_witness() -> None:
    metadata = json.loads(
        decisions.build(extensions=decisions.load_extensions(profile="release"))[
            ".metadata/metadata.json"
        ]
    )
    witness = metadata["situated_actions"]["independent_pdx_semantics"]
    assert witness["consumer_count"] == 4
    assert set(witness["witnesses"]) == {
        "diplomatic_play_neutrality",
        "change_law_chance",
        "economic_vs_government_spending_balance",
        "recklessness",
    }
    assert witness["evidence"] == "static_semantic_witness"
    assert witness["behavior_quality"] == "not_evaluated"
