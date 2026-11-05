"""Budget failures use actual AST sites and cannot be masked by a report."""

from __future__ import annotations

import re
from dataclasses import replace

import pytest

from pdx.situated import resources

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("key", sorted(resources.METRICS))
def test_each_frozen_budget_hard_fails_above_boundary(key):
    limits = dict.fromkeys(resources.METRICS, 10)
    metrics = dict(limits)
    resources.validate_metrics(metrics, limits)
    metrics[key] += 1
    with pytest.raises(ValueError, match="预算"):
        resources.validate_metrics(metrics, limits)


def test_source_budget_is_complete_and_prevents_new_world_scans_or_state():
    data = resources.load()
    from pdx import canal_opportunities, event_opportunities, famine_opportunities

    native = canal_opportunities.frozen_inputs()[canal_opportunities.SOURCE]
    assert resources.pdx_metrics(native)["persistent_write_sites"] == 6
    plague = resources.pdx_metrics(event_opportunities.frozen_inputs()[event_opportunities.PLAGUE])
    assert plague["persistent_write_sites"] == 23
    assert sum(plague["object_scan_keys"].get(key, 0) for key in resources.WORLD_SCANS) == 9
    assert data["limits"]["world_country_scan_sites"] == 1 + 9
    famine = resources.pdx_metrics(
        famine_opportunities.frozen_inputs()[famine_opportunities.SOURCE]
    )
    assert famine["persistent_write_sites"] == 3
    assert data["limits"]["persistent_write_sites"] == 31 + 6 + 23 + 3
    assert data["limits"]["reader_path_length"] == 3


def test_missing_counts_or_invalid_numbers_cannot_pass():
    metrics = dict.fromkeys(resources.METRICS, 0)
    limits = dict.fromkeys(resources.METRICS, 10)
    for invalid in ({}, {**metrics, "max_depth": -1}, {**metrics, "max_depth": True}):
        with pytest.raises(ValueError):
            resources.validate_metrics(invalid, limits)


def test_inherited_write_allowance_cannot_add_replace_or_move_native_state():
    from pdx import canal_opportunities

    source = canal_opportunities.SOURCE
    native = canal_opportunities.frozen_inputs()[source]
    resources.verify_inherited_writes({source: native})
    for changed in (
        native + "\nset_variable = forged\n",
        native.replace("set_variable", "change_variable", 1),
        "forged = { " + native + " }",
    ):
        with pytest.raises(ValueError, match="继承变量"):
            resources.verify_inherited_writes({source: changed})


def test_measure_separates_exact_scan_ast_from_quoted_or_comment_text():
    from pdx.situated.compiler import SituatedModel

    model = SituatedModel((), (), (), (), {})
    text = '# any_country = { set_variable = fake }\na = "any_country"\n'
    result = resources.measure({"common/scripted_values/a.txt": text}, model)
    assert result["world_country_scan_sites"] == 0
    assert result["persistent_write_sites"] == 0
    actual = resources.measure(
        {"common/scripted_values/a.txt": "any_country = { always = yes }"},
        replace(model, observation_contracts=()),
    )
    assert actual["world_country_scan_sites"] == 1


def test_plague_inherited_state_and_world_scans_cannot_be_repurposed():
    from pdx import event_opportunities

    source = event_opportunities.PLAGUE
    native = event_opportunities.frozen_inputs()[source]
    resources.verify_inherited_writes({source: native})
    for changed in (
        native + "\nset_variable = forged\n",
        native + "\nany_country = { always = yes }\n",
        native.replace("set_variable", "change_variable", 1),
        native.replace("random_country", "every_country", 1),
        "forged = { " + native + " }",
    ):
        with pytest.raises(ValueError, match="继承变量或世界扫描"):
            resources.verify_inherited_writes({source: changed})


def test_famine_inherited_button_state_cannot_change_name_duration_or_parent():
    from pdx import famine_opportunities as famine

    native = famine.frozen_inputs()[famine.SOURCE]
    resources.verify_inherited_writes({famine.SOURCE: native})
    for changed in (
        re.sub(r"(set_variable\s*=\s*\{[^}]*months\s*=\s*)12", r"\g<1>24", native, count=1),
        re.sub(
            r"(set_variable\s*=\s*\{\s*name\s*=\s*)relief_kitchens_button_var",
            r"\g<1>forged_button_var",
            native,
            count=1,
        ),
        native + "\nset_variable = forged\n",
        "other = { " + native + " }",
    ):
        with pytest.raises(ValueError, match="继承变量"):
            resources.verify_inherited_writes({famine.SOURCE: changed})
