"""精确区分防约原版计数与读取器可用范围。"""

from dataclasses import replace

import pytest

from pdx import decision_interfaces, decision_rules

pytestmark = pytest.mark.unit

READERS = (
    decision_rules.Reader(
        "defensive_pact_articles",
        "num_defensive_pacts",
        "root",
        "treaty_article_count",
        "number",
        minimum=0,
    ),
    decision_rules.Reader(
        "native_army_capacity",
        "wanted_army_size_script_value",
        "root",
        "barracks_levels",
        "number",
    ),
    decision_rules.Reader(
        "native_marine_capacity",
        "wanted_marines_size_script_value",
        "root",
        "barracks_levels",
        "number",
    ),
)


@pytest.mark.parametrize("reader", READERS, ids=[reader.key for reader in READERS])
def test_original_getters_keep_exact_local_signatures(reader):
    assert decision_interfaces.reader_scope(reader, ()) == "country"


def test_count_and_native_comparison_have_no_production_readers():
    policy = decision_rules.load()
    assert all(rule.id != "lj10_defensive_pact_flow_pressure" for rule in policy.rules)
    assert {reader.engine for reader in READERS}.isdisjoint(row.engine for row in policy.readers)


@pytest.mark.parametrize("reader", READERS, ids=[reader.key for reader in READERS])
@pytest.mark.parametrize(
    "change",
    [
        {"scope": "target_country"},
        {"path": ("owner",)},
        {"argument": "c:RUS"},
        {"parameters": (("country", "c:RUS"),)},
        {"value_field": "value"},
        {"maximum": 100},
        {"kind": "boolean"},
        {"unit": "currency"},
    ],
)
def test_reader_rejects_unproven_signature_changes(reader, change):
    with pytest.raises(ValueError):
        decision_interfaces.reader_scope(replace(reader, **change), ())


@pytest.mark.parametrize("reader", READERS, ids=[reader.key for reader in READERS])
def test_reader_rejects_state_actor_and_changed_minimum(reader):
    with pytest.raises(ValueError):
        decision_interfaces.reader_scope(reader, ("owner",))
    with pytest.raises(ValueError):
        decision_interfaces.reader_scope(replace(reader, minimum=1), ())


def test_pinned_reader_manifest_is_checked_before_returning_words(monkeypatch, tmp_path):
    from pdx.situated import engine_scope_115

    original, _, digest = engine_scope_115.manifest("defensive-pact-reader")
    path = tmp_path / "evidence.json"
    path.write_bytes(original.read_bytes() + b" ")
    monkeypatch.setitem(engine_scope_115.MANIFESTS, "defensive-pact-reader", (str(path), digest))
    with pytest.raises(ValueError, match="drift"):
        decision_interfaces.proven_reader_words()
