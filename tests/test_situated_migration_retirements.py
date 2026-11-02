"""Explicit retirements preserve the immutable published identity oracle."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from pdx.situated import decision_ir, migration_baseline

pytestmark = pytest.mark.unit

_TAIL = "retain_original_qualification_cost_random_execution"
_PROOF = "tests/test_situated_migration_retirements.py::test_exact_retirement_requires_live_same_consumer_replacement"


@pytest.fixture(scope="module")
def published_bundle():
    historical = json.loads(migration_baseline.DEFAULT_SOURCE.read_bytes())
    writers = []
    for index, row in enumerate(historical["rules"]):
        writers.append(
            decision_ir.WriterDecisionIR(
                writer_id=f"published_{index}",
                kind="rule_action",
                consumer_id="fixture",
                vanilla_tail=_TAIL,
                owner="consumer_adapters",
                **row,
            )
        )
    for index, row in enumerate(historical["cards"]):
        writers.append(
            decision_ir.WriterDecisionIR(
                writer_id=f"card_{index}",
                kind="action_card",
                source="mod/decisions/actions.toml",
                actor="root",
                target="none",
                consumer_id="fixture",
                vanilla_tail=_TAIL,
                owner="situated_kernel",
                **row,
            )
        )
    return decision_ir.ConsumerIRBundle(schema=1, actions=(), writers=tuple(writers))


@pytest.fixture
def retirement_case(tmp_path, published_bundle):
    old = next(
        w
        for w in published_bundle.writers
        if w.definition == "coordinated_layered_building_building_arms_industry_expansion"
    )
    replacement = replace(old, definition="replacement_same_consumer", writer_id="replacement")
    bundle = replace(
        published_bundle,
        writers=tuple(replacement if w is old else w for w in published_bundle.writers),
    )
    row = {
        key: getattr(old, key)
        for key in ("source", "definition", "field", "actor", "target", "operation")
    }
    row.update(
        reason="Replace aggregate capacity with the actual local opportunity at the same consumer.",
        replacements=[replacement.definition],
        validation=[_PROOF],
    )
    payload = {"schema": 1, "baseline_tag": "v3.0.1", "retirements": [row]}
    return bundle, old, replacement, payload, tmp_path / "retirements.json"


def validate_case(case):
    bundle, _, _, payload, path = case
    path.write_text(json.dumps(payload), encoding="utf-8")
    migration_baseline.validate_bundle(bundle, retirements_path=path)


def test_exact_retirement_requires_live_same_consumer_replacement(retirement_case):
    validate_case(retirement_case)


def test_validated_retirements_returns_immutable_ids_only_after_full_validation(retirement_case):
    bundle, old, _, payload, path = retirement_case
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = migration_baseline.validated_retirements(bundle, retirements_path=path)
    assert type(result) is frozenset
    assert result == frozenset({(old.source, old.definition)})
    broken = replace(bundle, writers=tuple(w for w in bundle.writers if w.kind != "action_card"))
    with pytest.raises(ValueError, match="历史显式卡身份缺失"):
        migration_baseline.validated_retirements(broken, retirements_path=path)


def test_empty_retirement_list_preserves_every_published_identity(tmp_path, published_bundle):
    path = tmp_path / "empty.json"
    path.write_text('{"schema":1,"baseline_tag":"v3.0.1","retirements":[]}', encoding="utf-8")
    migration_baseline.validate_bundle(published_bundle, retirements_path=path)


def test_undeclared_same_count_replacement_still_loses_historical_identity(retirement_case):
    retirement_case[3]["retirements"] = []
    with pytest.raises(ValueError, match="历史迁移身份缺失"):
        validate_case(retirement_case)


def test_declaring_one_retirement_cannot_hide_another_same_count_loss(retirement_case):
    bundle, old, _, payload, path = retirement_case
    other = next(w for w in bundle.writers if w.kind == "rule_action" and w.field != old.field)
    changed = replace(
        bundle,
        writers=tuple(
            replace(w, definition="unlisted_replacement") if w is other else w
            for w in bundle.writers
        ),
    )
    with pytest.raises(ValueError, match="历史迁移身份缺失"):
        validate_case((changed, old, None, payload, path))


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("field", "building_other.ai_value"),
        ("actor", "root"),
        ("target", "target_state"),
        ("operation", "add"),
    ],
)
def test_retirement_must_match_original_historical_contract(retirement_case, key, value):
    retirement_case[3]["retirements"][0][key] = value
    with pytest.raises(ValueError, match="退役"):
        validate_case(retirement_case)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("field", "building_other.ai_value"),
        ("actor", "root"),
        ("target", "target_state"),
        ("operation", "add"),
        ("source", "common/buildings/other.txt"),
        ("kind", "action_card"),
        ("vanilla_tail", "discard_cost_qualification"),
        ("owner", ""),
    ],
)
def test_replacement_cannot_borrow_another_consumer_or_remove_native_tail(
    retirement_case, key, value
):
    bundle, old, replacement, payload, path = retirement_case
    changed = replace(
        bundle,
        writers=tuple(
            replace(w, **{key: value}) if w is replacement else w for w in bundle.writers
        ),
    )
    with pytest.raises(ValueError, match="退役"):
        validate_case((changed, old, replacement, payload, path))


@pytest.mark.parametrize(
    "damage",
    [
        "not_historical",
        "still_present",
        "still_present_as_card",
        "missing_replacement",
        "duplicate_current",
        "duplicate_retirement",
    ],
)
def test_retirement_cannot_be_forged_or_repeated(retirement_case, damage):
    bundle, old, replacement, payload, path = retirement_case
    if damage == "not_historical":
        payload["retirements"][0]["definition"] = "not_a_published_rule"
    elif damage == "still_present":
        bundle = replace(bundle, writers=(*bundle.writers, old))
    elif damage == "still_present_as_card":
        bundle = replace(bundle, writers=(*bundle.writers, replace(old, kind="action_card")))
    elif damage == "missing_replacement":
        payload["retirements"][0]["replacements"] = ["nonexistent_replacement"]
    elif damage == "duplicate_current":
        bundle = replace(
            bundle, writers=(*bundle.writers, replace(replacement, writer_id="duplicate"))
        )
    else:
        payload["retirements"].append(dict(payload["retirements"][0]))
    with pytest.raises(ValueError, match=r"退役|重复"):
        validate_case((bundle, old, replacement, payload, path))


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("reason", ""),
        ("reason", "  "),
        ("reason", None),
        ("replacements", []),
        ("replacements", ["replacement_same_consumer", "replacement_same_consumer"]),
        ("replacements", [None]),
        ("validation", []),
        ("validation", ["tests/test_missing_retirement_evidence.py"]),
        ("validation", ["../tests/test_situated_migration_retirements.py"]),
        ("validation", ["tests/test_situated_migration_retirements.py::test_does_not_exist"]),
        ("validation", ["src/pdx/situated/migration_baseline.py"]),
        ("validation", [_PROOF, _PROOF]),
        ("unrecognized", True),
    ],
)
def test_retirement_requires_unambiguous_reason_replacements_and_real_test_identity(
    retirement_case, key, value
):
    retirement_case[3]["retirements"][0][key] = value
    with pytest.raises(ValueError, match="退役"):
        validate_case(retirement_case)


@pytest.mark.parametrize(
    "key",
    [
        "source",
        "definition",
        "field",
        "actor",
        "target",
        "operation",
        "reason",
        "replacements",
        "validation",
    ],
)
def test_retirement_requires_every_contract_field(retirement_case, key):
    retirement_case[3]["retirements"][0].pop(key)
    with pytest.raises(ValueError, match="退役"):
        validate_case(retirement_case)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"schema": True, "baseline_tag": "v3.0.1", "retirements": []},
        {"schema": 1, "baseline_tag": "other", "retirements": []},
        {"schema": 1, "baseline_tag": "v3.0.1", "retirements": None},
        {"schema": 1, "baseline_tag": "v3.0.1", "retirements": [None]},
        {"schema": 1, "baseline_tag": "v3.0.1", "retirements": [], "ignore_missing": True},
    ],
)
def test_retirement_manifest_schema_is_strict(retirement_case, payload):
    bundle, old, replacement, _, path = retirement_case
    with pytest.raises(ValueError, match="退役"):
        validate_case((bundle, old, replacement, payload, path))


def test_missing_retirement_manifest_is_a_hard_failure(retirement_case):
    bundle, _, _, _, path = retirement_case
    with pytest.raises(ValueError, match=r"退役.*缺失"):
        migration_baseline.validate_bundle(bundle, retirements_path=path)


def test_duplicate_json_keys_cannot_override_retirement_schema(retirement_case):
    bundle, _, _, _, path = retirement_case
    path.write_text(
        '{"schema":2,"schema":1,"baseline_tag":"v3.0.1","retirements":[]}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match=r"退役.*重复"):
        migration_baseline.validate_bundle(bundle, retirements_path=path)


def test_retirement_does_not_relax_original_manifest_byte_lock(retirement_case):
    bundle, _, _, payload, path = retirement_case
    path.write_text(json.dumps(payload), encoding="utf-8")
    historical = path.with_name("historical.json")
    historical.write_bytes(migration_baseline.DEFAULT_SOURCE.read_bytes() + b" ")
    with pytest.raises(ValueError, match="历史迁移 manifest 原始字节漂移"):
        migration_baseline.validate_bundle(bundle, path=historical, retirements_path=path)


def test_default_retirement_bytes_are_pinned(retirement_case, monkeypatch):
    bundle = retirement_case[0]
    monkeypatch.setattr(migration_baseline, "_RETIREMENTS_SHA256", "0" * 64, raising=False)
    with pytest.raises(ValueError, match=r"退役.*原始字节漂移"):
        migration_baseline.validate_bundle(bundle)
