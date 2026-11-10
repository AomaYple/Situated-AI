"""Current native retention does not grant a new Mod consumer permission."""

from __future__ import annotations

import pytest

from pdx import decision_interfaces, version_contracts

pytestmark = pytest.mark.unit


def test_current_cossack_field_is_retained_without_mod_writer():
    with version_contracts.select_version("1.15.0"):
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


@pytest.mark.parametrize(
    ("version", "field"), [("1.14.5", "cossack_host_scores"), ("1.15.0", "cossack_host_score")]
)
def test_cossack_retention_is_exact_and_current_only(version, field):
    with version_contracts.select_version(version), pytest.raises(ValueError, match="缺少逐项处置"):
        decision_interfaces._retained_reason(field)
