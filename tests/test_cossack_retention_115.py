"""Current native retention does not grant a new Mod consumer permission."""

from __future__ import annotations

import pytest

from pdx import decision_interfaces

pytestmark = pytest.mark.unit


def test_current_cossack_field_is_retained_without_mod_writer():
    (row,) = decision_interfaces.coverage(
        "ai_strategy_default = { cossack_host_scores = { establish_cossack_host = { value = 0 } } }",
        {},
    )
    assert row["status"] == "retained_vanilla_not_new_mod_implementation"
    assert row["writers"] == {}
    assert row["behavior_verified"] is False
    disposition = row["retained_disposition"]
    assert isinstance(disposition, dict)
    assert disposition["disposition"] == "native_cossack_host_policy"


def test_cossack_retention_is_exact():
    with pytest.raises(ValueError, match="缺少逐项处置"):
        decision_interfaces._retained_reason("cossack_host_score")
