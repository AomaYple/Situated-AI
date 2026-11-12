"""Resolved configuration explains declared withdrawals, never unknown fields."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

import pytest

from pdx import (
    decision_adapters,
    decision_interfaces,
    decision_rules,
    decisions,
    distribution,
    version_contracts,
)
from pdx.model import Block
from pdx.parser import parse_text
from pdx.situated.profile_configuration import DOMAINS, ProfileConfiguration

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def current_version():
    with version_contracts.select_version("1.15.1"):
        yield


@pytest.mark.parametrize(
    "configuration", [ProfileConfiguration(core=False), ProfileConfiguration(mode="neutral")]
)
def test_all_disabled_coverage_retains_complete_native_denominator(configuration):
    baseline = decisions.baseline_path().read_text(encoding="utf-8-sig")
    rows = decision_interfaces.coverage(baseline, {}, configuration=configuration)
    root = parse_text(baseline).top_assignments[0].value
    assert isinstance(root, Block)
    assert [row["field"] for row in rows] == root.keys()
    assert all(row["status"] == "retained_vanilla_not_new_mod_implementation" for row in rows)
    assert all(not row["writers"] and row["behavior_verified"] is False for row in rows)
    infamy = next(row for row in rows if row["field"] == "undesirable_infamy_level")
    retained = infamy["retained_disposition"]
    assert isinstance(retained, dict)
    assert retained["disposition"] == "configuration_disabled_writer"
    assert retained["configuration"] == configuration.identity()
    assert retained["disabled_writers"]
    assert all(
        item["domain"] not in configuration.legacy_domains for item in retained["disabled_writers"]
    )
    icon = next(row for row in rows if row["field"] == "icon")
    assert cast("dict[str, Any]", icon["retained_disposition"])["disposition"] == "presentation"
    institution = next(row for row in rows if row["field"] == "institution_scores")
    disabled = cast("list[dict[str, str]]", institution["configuration_disabled_writers"])
    assert any(item["writer_id"] == "a0-pol-schools" for item in disabled)
    assert not any(item["writer_id"].startswith("remaining_school_") for item in disabled)


@pytest.mark.parametrize(
    "configuration",
    [
        ProfileConfiguration(core=False),
        ProfileConfiguration(mode="neutral"),
        ProfileConfiguration(),
    ],
)
def test_unknown_native_field_still_fails_under_any_configuration(configuration):
    with pytest.raises(ValueError, match="缺少逐项处置"):
        decision_interfaces.coverage(
            "ai_strategy_default={invented_unknown={value=1}}", {}, configuration=configuration
        )


def test_active_writer_cannot_be_explained_as_configuration_disabled():
    with pytest.raises(ValueError, match=r"缺少启用声明writer.*undesirable_infamy_level"):
        decision_interfaces.coverage(
            "ai_strategy_default={undesirable_infamy_level={value=1}}",
            {},
            configuration=ProfileConfiguration(),
        )


def test_partial_domain_coverage_records_disabled_contributions_and_active_sibling():
    selected = ProfileConfiguration(domains=frozenset(DOMAINS) - {"economy"})
    baseline = "ai_strategy_default={diplomatic_play_support={value=0} goods_stances={}}"
    rows = decision_interfaces.coverage(
        baseline, {("diplomatic_play_support",): "situated_kernel"}, configuration=selected
    )
    support = rows[0]
    assert support["status"] == "generated_intervention"
    assert support["retained_disposition"] is None
    assert support["configuration_disabled_writers"]
    assert {
        item["domain"]
        for item in cast("list[dict[str, str]]", support["configuration_disabled_writers"])
    } == {"market"}
    goods = rows[1]
    retained = cast("dict[str, Any]", goods["retained_disposition"])
    assert retained["disposition"] == "configuration_disabled_writer"
    supply = retained["disabled_writers"]
    assert len(supply) == 33
    plan = decision_adapters.load().supply
    assert plan is not None
    assert {item["writer_id"] for item in supply} == {f"supply_{good}" for good in plan.goods}


def test_disabled_market_cannot_hide_missing_active_security_writer():
    selected = ProfileConfiguration(domains=frozenset(DOMAINS) - {"economy"})
    _, extensions = distribution.production_configuration(configuration=selected)
    assert extensions.market_enabled is False
    assert extensions.security_enabled is True
    with pytest.raises(ValueError, match=r"缺少启用声明writer.*diplomatic_play_support"):
        decision_interfaces.coverage(
            "ai_strategy_default={diplomatic_play_support={value=0}}", {}, configuration=selected
        )


def test_duplicate_declared_rule_identity_cannot_create_disabled_authority(monkeypatch):
    rules = decision_rules.load()
    monkeypatch.setattr(
        decision_rules, "load", lambda: replace(rules, rules=(*rules.rules, rules.rules[0]))
    )
    with pytest.raises(ValueError, match="重复"):
        decision_interfaces.coverage(
            "ai_strategy_default={icon=x}", {}, configuration=ProfileConfiguration(core=False)
        )


def test_configuration_input_rejects_unresolved_mapping():
    with pytest.raises(ValueError, match="配置"):
        decision_interfaces.coverage(
            "ai_strategy_default={icon=x}", {}, configuration=cast("Any", {"core": False})
        )


def test_no_configuration_preserves_historical_coverage_shape():
    with version_contracts.select_version("1.15.0"):
        (row,) = decision_interfaces.coverage("ai_strategy_default={icon=x}", {})
    assert "configuration_disabled_writers" not in row
    assert cast("dict[str, Any]", row["retained_disposition"])["disposition"] == "presentation"
