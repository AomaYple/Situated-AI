"""State tax shortfalls stay local, incorporated, source-proven and three-valued."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from pdx import config
from pdx import observation_queries as queries
from pdx.parser import parse_text
from pdx.situated import pdx_eval
from pdx.textio import normalized_text

pytestmark = pytest.mark.unit
GOVERNMENT = "common/buildings/07_government.txt"
PORTUGAL = "common/journal_entries/06_portugal_politics.txt"
PARAMETERS = {"state_query": "tax_capacity_shortfall"}
EXPECTED = "any_scope_state = { is_incorporated = yes tax_capacity < tax_capacity_usage }"


def _query():
    return queries.AnyIncorporatedStateTaxCapacityShortfall()


def _state(capacity=90, usage=100, *, incorporated=True):
    return {
        "is_incorporated": incorporated,
        "tax_capacity": capacity,
        "tax_capacity_usage": usage,
    }


def _evaluate(root, **decoys):
    parsed = parse_text("ROOT = { " + queries.render(_query()) + " }")
    assert not parsed.errors
    return pdx_eval.condition(parsed.root, {"ROOT": root, **decoys})


def test_fixed_reader_parameters_emit_actual_tax_comparison_without_world_or_building_scan():
    assert queries.from_reader("any_scope_state", PARAMETERS) == _query()
    expression = queries.render(_query())
    assert expression == EXPECTED
    assert not parse_text(expression).errors
    assert "bureaucracy" not in expression
    assert "any_scope_building" not in expression
    assert "any_country" not in expression
    assert queries.from_reader("any_scope_state", {"threshold": "0.9"}) == (
        queries.AnyStateMarketAccessBelow(0.9)
    )


@pytest.mark.parametrize(
    ("engine", "parameters"),
    [
        ("any_scope_state", {}),
        ("any_scope_state", {"state_query": "tax_capacity"}),
        ("any_scope_state", {"state_query": "tax_capacity_shortfall", "owner": "ROOT"}),
        ("any_scope_state", {"state_query": "tax_capacity_shortfall", "incorporated": "no"}),
        ("any_scope_state", {"state_query": "tax_capacity_shortfall", "threshold": "0.9"}),
        ("any_scope_state", {"state_query": "tax_capacity_shortfall", "comparison": "<="}),
        ("any_scope_state", {"state_query": True}),
        ("any_scope_state", {"state_query": "tax_capacity_shortfall } always=yes"}),
        ("any_country", PARAMETERS),
        ("any_scope_building", PARAMETERS),
    ],
)
def test_parameter_identity_rejects_other_scopes_comparisons_and_free_pdx(engine, parameters):
    with pytest.raises(ValueError):
        queries.from_reader(engine, parameters)


def test_rendering_is_pure_and_unparameterized(monkeypatch):
    def fail(*_args, **_kwargs):
        pytest.fail("tax query rendering attempted filesystem I/O")

    monkeypatch.setattr(Path, "read_text", fail)
    monkeypatch.setattr(Path, "read_bytes", fail)
    assert queries.render(queries.from_reader("any_scope_state", PARAMETERS)) == EXPECTED


@pytest.mark.parametrize(
    ("states", "expected"),
    [
        (None, None),
        ([], False),
        ([{}], None),
        ([_state()], True),
        ([_state(100, 100)], False),
        ([_state(101, 100)], False),
        ([_state(99.999, 100)], True),
        ([_state(0, 0)], False),
        ([_state(0, 1)], True),
        ([_state(incorporated=False)], False),
        ([_state(None, None, incorporated=False)], False),
        ([_state(None, 100)], None),
        ([_state(90, None)], None),
        ([_state(incorporated=None)], None),
        ([_state(100, 100), _state(None, 100)], None),
        ([_state(), _state(None, 100)], True),
        ([_state(100, 100), _state(incorporated=False)], False),
    ],
)
def test_emitted_pdx_true_false_unknown_and_unincorporated_states(states, expected):
    assert _evaluate({"any_scope_state": states}) is expected


def test_capacity_usage_and_incorporation_must_belong_to_the_same_owned_state():
    assert _evaluate({"any_scope_state": [_state(50, 40), _state(200, 100)]}) is False
    assert (
        _evaluate({"any_scope_state": [_state(0, 1, incorporated=False), _state(100, 100)]})
        is False
    )
    # No valid complete state proves a shortfall; missing observations stay unknown.
    assert _evaluate({"any_scope_state": [_state(0, None), _state(None, 100)]}) is None


def test_foreign_and_flat_collections_cannot_supply_a_deficit_to_country_root():
    assert (
        _evaluate(
            {"any_scope_state": [], "foreign_country": {"any_scope_state": [_state()]}},
            any_scope_state=[_state()],
            tax_capacity=0,
            tax_capacity_usage=1000,
        )
        is False
    )
    assert (
        _evaluate(
            {"any_scope_state": [_state(100, 100)]},
            any_scope_state=[_state()],
        )
        is False
    )
    assert _evaluate({}, any_scope_state=[_state()]) is None


@pytest.fixture
def source_texts(monkeypatch):
    # Independent tiny fixtures prove complete AST checks independently of hashes.
    texts = {
        GOVERNMENT: """building_government_administration = {
            should_auto_expand = { occupancy >= 0.8 OR = {
                state.tax_capacity < state.tax_capacity_usage
                owner = { bureaucracy < -10 }
            } }
        }""",
        PORTUGAL: """je_portugal_regeneration_public_works = { complete = {
            any_scope_state = { filter = { is_incorporated = yes }
                has_building = building_railway percent = 1 }
        } }""",
    }
    if queries.version_contracts.is_115():
        texts[PORTUGAL] = (
            texts[PORTUGAL].replace(
                "complete = {",
                "outcome = { header = je_standard_completion_header "
                "effect_header = je_standard_on_completion_header trigger = {",
            )
            + " }"
        )
    for source, text in texts.items():
        monkeypatch.setitem(
            queries.source_hashes(),
            source,
            hashlib.sha256(normalized_text(text).encode()).hexdigest(),
        )
    return texts


def test_compile_checks_actual_sources_and_preserves_collection_unknown_cost_contract(source_texts):
    query = _query()
    compiled = queries.compile_query(query, source_texts)
    assert compiled.expression == EXPECTED
    assert set(queries.required_sources(query)) == {GOVERNMENT, PORTUGAL}
    assert set(dict(compiled.source_hashes)) == {GOVERNMENT, PORTUGAL}
    assert compiled.local_collections == ("owned_states",)
    assert (compiled.actor, compiled.kind, compiled.world_scans) == ("country", "boolean", 0)
    assert compiled.unknown_policy == queries.UNKNOWN_POLICY
    assert "not constant time" in compiled.runtime_cost
    assert {reference.rsplit(":", 1)[0] for reference in compiled.references} == {
        GOVERNMENT,
        PORTUGAL,
    }


@pytest.mark.parametrize("source", [GOVERNMENT, PORTUGAL])
def test_missing_source_or_fingerprint_drift_is_fatal(source_texts, source):
    with pytest.raises(ValueError, match="缺少必需原版来源"):
        queries.compile_query(
            _query(), {key: value for key, value in source_texts.items() if key != source}
        )
    with pytest.raises(ValueError, match="原版来源漂移"):
        queries.compile_query(_query(), {**source_texts, source: source_texts[source] + "# drift"})


@pytest.mark.parametrize(
    ("source", "old", "new"),
    [
        (GOVERNMENT, "state.tax_capacity <", "state.tax_capacity <="),
        (GOVERNMENT, "state.tax_capacity_usage", "owner.bureaucracy"),
        (GOVERNMENT, "state.tax_capacity <", "owner.tax_capacity <"),
        (GOVERNMENT, "should_auto_expand =", "INJECT:should_auto_expand ="),
        (GOVERNMENT, "OR =", "AND ="),
        (GOVERNMENT, "owner = {", "owner ?= {"),
        (PORTUGAL, "any_scope_state =", "any_country ="),
        (PORTUGAL, "is_incorporated = yes", "is_incorporated = no"),
        (PORTUGAL, "filter =", "INJECT:filter ="),
        (
            PORTUGAL,
            "has_building = building_railway",
            "has_building = building_government_administration",
        ),
        (PORTUGAL, "percent = 1", "percent = 0.5"),
    ],
)
def test_repinned_wrong_complete_native_ast_never_grants_query(
    source_texts, monkeypatch, source, old, new
):
    changed = source_texts[source].replace(old, new)
    assert changed != source_texts[source]
    monkeypatch.setitem(
        queries.source_hashes(),
        source,
        hashlib.sha256(normalized_text(changed).encode()).hexdigest(),
    )
    with pytest.raises(ValueError):
        queries.compile_query(_query(), {**source_texts, source: changed})


@pytest.mark.integration
def test_installed_native_sources_authorize_exact_local_tax_query():
    texts = {
        source: (config.GAME / source).read_text(encoding="utf-8-sig")
        for source in (GOVERNMENT, PORTUGAL)
    }
    compiled = queries.compile_query(_query(), texts)
    assert compiled.expression == EXPECTED
    assert compiled.world_scans == 0
    assert set(dict(compiled.source_hashes)) == {GOVERNMENT, PORTUGAL}
    line = {"1.14.5": 530, "1.15.0": 580, "1.15.1": 580}[queries.version_contracts.active_version()]
    assert f"{PORTUGAL}:{line}" in compiled.references
    assert f"{GOVERNMENT}:12" in compiled.references
