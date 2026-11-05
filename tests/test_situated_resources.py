"""Budget failures use actual AST sites and cannot be masked by a report."""

from __future__ import annotations

import hashlib
import json
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
    from pdx import (
        canal_opportunities,
        event_opportunities,
        famine_opportunities,
        native_decision_opportunities,
    )

    native = canal_opportunities.frozen_inputs()[canal_opportunities.SOURCE]
    assert resources.pdx_metrics(native)["persistent_write_sites"] == 6
    plague = resources.pdx_metrics(event_opportunities.frozen_inputs()[event_opportunities.PLAGUE])
    assert plague["persistent_write_sites"] == 23
    assert sum(plague["object_scan_keys"].get(key, 0) for key in resources.WORLD_SCANS) == 9
    assert data["limits"]["world_country_scan_sites"] == 1 + 9 + 1 + 3
    famine = resources.pdx_metrics(
        famine_opportunities.frozen_inputs()[famine_opportunities.SOURCE]
    )
    assert famine["persistent_write_sites"] == 3
    disaster = resources.pdx_metrics(
        event_opportunities.frozen_inputs()[event_opportunities.DISASTERS]
    )
    assert disaster["persistent_write_sites"] == 14
    assert disaster["persistent_write_keys"] == {
        "set_variable": 9,
        "change_global_variable": 3,
        "set_global_variable": 2,
    }
    assert sum(disaster["object_scan_keys"].get(key, 0) for key in resources.WORLD_SCANS) == 0
    native_decisions = resources.pdx_metrics(
        native_decision_opportunities.frozen_inputs()[native_decision_opportunities.SOURCE]
    )
    assert native_decisions["persistent_write_keys"] == {
        "set_variable": 2,
        "set_global_variable": 1,
    }
    assert (
        sum(native_decisions["object_scan_keys"].get(key, 0) for key in resources.WORLD_SCANS) == 0
    )
    assert data["limits"]["persistent_write_sites"] == 113
    assert data["limits"]["reader_path_length"] == 3


@pytest.mark.parametrize("source", sorted(resources.native_baseline()["inputs"]))
def test_all_current_native_operation_sources_reject_add_replace_and_move(source):
    native = resources.native_baseline()["inputs"][source]
    resources.verify_inherited_writes({source: native})
    for changed in (
        native + "\nany_country = { always = yes }\n",
        native + "\nset_variable = forged\n",
        "forged = { " + native + " }",
    ):
        with pytest.raises(ValueError, match="继承变量或世界扫描"):
            resources.verify_inherited_writes({source: changed})
    replaced, count = re.subn(
        r"\b(set_variable|change_variable|remove_variable|clamp_variable|set_global_variable|change_global_variable|remove_global_variable|any_country|every_country|random_country|ordered_country)(\s*=)",
        r"forged_operation\2",
        native,
        count=1,
    )
    assert count == 1
    with pytest.raises(ValueError, match="继承变量或世界扫描"):
        resources.verify_inherited_writes({source: replaced})


@pytest.mark.parametrize(
    "source", ["common/scripted_values/sitai_values.txt", "events/unknown.txt"]
)
@pytest.mark.parametrize("operation", ["set_variable = forged", "any_country = { always = yes }"])
def test_unknown_and_mod_owned_sources_cannot_borrow_native_allowances(source, operation):
    resources.verify_inherited_writes({source: "a = { value = 1 }"})
    with pytest.raises(ValueError, match="继承变量或世界扫描"):
        resources.verify_inherited_writes({source: "a = { " + operation + " }"})


def test_current_operation_source_corruption_cannot_be_authorized_by_outer_repin(
    tmp_path, monkeypatch
):
    data = resources.native_baseline()
    source = "common/laws/01_economic_system.txt"
    data["inputs"][source] = data["inputs"][source].replace("every_country", "any_country", 1)
    data["source_hashes"][source] = hashlib.sha256(data["inputs"][source].encode()).hexdigest()
    raw = json.dumps(data).encode()
    path = tmp_path / "repinned.json"
    path.write_bytes(raw)
    monkeypatch.setattr(resources, "_NATIVE_SOURCE", path)
    monkeypatch.setattr(resources, "_NATIVE_SHA256", hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match="来源或语义合同"):
        resources.native_baseline()


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


def test_disaster_inherited_state_counters_and_original_parents_are_exact():
    from pdx import event_opportunities as event

    native = event.frozen_inputs()[event.DISASTERS]
    generated = event.patch(event.frozen_inputs())[event.DISASTERS]
    resources.verify_inherited_writes({event.DISASTERS: generated})
    for changed in (
        native.replace("name = natural_disaster_cooldown", "name = wrong_cooldown", 1),
        native.replace("days = normal_modifier_time", "days = short_modifier_time", 1),
        native.replace("name = number_of_mega_floods", "name = wrong_counter", 1),
        native.replace("change_global_variable", "set_global_variable", 1),
        native + "\nset_variable = forged\n",
        native + "\nany_country = { always = yes }\n",
        "other = { " + native + " }",
    ):
        with pytest.raises(ValueError, match="继承变量或世界扫描"):
            resources.verify_inherited_writes({event.DISASTERS: changed})


def test_native_decision_writes_cannot_be_added_replaced_or_moved():
    from pdx import native_decision_opportunities as native

    original = native.frozen_inputs()[native.SOURCE]
    resources.verify_inherited_writes({native.SOURCE: original})
    for changed in (
        original.replace("name = revive_olympics_decision_taken", "name = forged_memory", 1),
        original.replace("value = yes", "value = no", 1),
        original.replace("set_global_variable", "change_global_variable", 1),
        original + "\nset_variable = forged\n",
        original + "\nany_country = { always = yes }\n",
        "other = { " + original + " }",
    ):
        assert changed != original
        with pytest.raises(ValueError, match="继承变量或世界扫描"):
            resources.verify_inherited_writes({native.SOURCE: changed})


def test_sol_inherited_state_and_local_scans_are_exact_native_operations():
    from pdx import event_opportunities as event

    inputs = event.frozen_inputs()
    native = inputs[event.SOL]
    generated = event.patch(inputs)[event.SOL]
    metrics = resources.pdx_metrics(native)
    assert metrics["persistent_write_keys"] == {"set_variable": 7}
    assert metrics["object_scan_sites"] == 21
    assert sum(metrics["object_scan_keys"].get(key, 0) for key in resources.WORLD_SCANS) == 0
    resources.verify_inherited_writes({event.SOL: generated})
    for changed in (
        generated.replace("set_variable", "change_variable", 1),
        generated + "\nset_variable = forged\n",
        "forged = { " + generated + " }",
        generated + "\nany_country = { always = yes }\n",
    ):
        with pytest.raises(ValueError, match="继承变量"):
            resources.verify_inherited_writes({event.SOL: changed})


def test_military_assistance_new_query_sites_stay_local_and_bounded():
    from pdx import treaty_acceptance_opportunities as acceptance

    inputs = acceptance.frozen_inputs()
    program = acceptance.compile_program("military_assistance")
    native = resources.pdx_metrics(inputs[program.source])
    generated = resources.pdx_metrics(
        acceptance.patch(inputs, consumer_program=program)[program.source]
    )
    assert native["object_scan_sites"] == 19
    assert generated["object_scan_sites"] == 23
    assert generated["persistent_write_sites"] == 0
    assert sum(generated["object_scan_keys"].get(key, 0) for key in resources.WORLD_SCANS) == 0
    assert (
        resources.load()["limits"]["object_scan_sites"] == 2300 + 21 + 19 + 4 + 26 + 23 + 5 + 1 + 6
    )


def test_native_button_inherited_writes_and_world_scans_keep_exact_parents():
    from pdx import native_button_opportunities as buttons

    inputs = buttons.frozen_inputs()
    totals = {"object_scan_sites": 0, "persistent_write_sites": 0, "world_country_scan_sites": 0}
    for source in {spec.source for spec in buttons.SPECS}:
        native = inputs[source]
        metrics = resources.pdx_metrics(native)
        for key in ("object_scan_sites", "persistent_write_sites"):
            totals[key] += metrics[key]
        totals["world_country_scan_sites"] += sum(
            metrics["object_scan_keys"].get(key, 0) for key in resources.WORLD_SCANS
        )
        resources.verify_inherited_writes({source: native})
        for changed in (
            native + "\nset_variable = forged\n",
            native + "\nany_country = { always = yes }\n",
            "forged = { " + native + " }",
        ):
            with pytest.raises(ValueError, match="继承变量或世界扫描"):
                resources.verify_inherited_writes({source: changed})
    assert totals == {
        "object_scan_sites": 26,
        "persistent_write_sites": 10,
        "world_country_scan_sites": 1,
    }


def test_hokkaido_native_operations_remain_exact_beside_five_local_queries():
    from pdx import event_opportunities as event

    inputs = event.frozen_inputs()
    native = inputs[event.HOKKAIDO]
    generated = event.patch(inputs)[event.HOKKAIDO]
    original = resources.pdx_metrics(native)
    actual = resources.pdx_metrics(generated)
    assert original["object_scan_sites"] == 23
    assert actual["object_scan_sites"] == 28
    assert (
        original["persistent_write_keys"]
        == actual["persistent_write_keys"]
        == {
            "change_variable": 3,
            "set_global_variable": 8,
            "set_variable": 5,
        }
    )
    assert sum(actual["object_scan_keys"].get(key, 0) for key in resources.WORLD_SCANS) == 0
    resources.verify_inherited_writes({event.HOKKAIDO: generated})
    for changed in (
        generated.replace("change_variable", "set_variable", 1),
        generated.replace("set_global_variable", "change_global_variable", 1),
        generated + "\nset_variable = forged\n",
        generated + "\nany_country = { always = yes }\n",
        "other = { " + generated + " }",
    ):
        assert changed != generated
        with pytest.raises(ValueError, match="继承变量或世界扫描"):
            resources.verify_inherited_writes({event.HOKKAIDO: changed})
