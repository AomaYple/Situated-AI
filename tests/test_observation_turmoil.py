"""Police demand observes turmoil in finite owned states, with local unknowns."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from pdx import config, decision_adapters
from pdx import observation_queries as queries
from pdx.parser import parse_text
from pdx.situated import pdx_eval
from pdx.textio import normalized_text

ACW = "common/journal_entries/00_acw_entries.txt"
PORTUGAL = "common/journal_entries/06_portugal_politics.txt"
PARAMETERS = {"state_query": "turmoil_above", "threshold": "0.1"}
EXPRESSION = "any_scope_state = { turmoil > 0.1 }"


def _query():
    return queries.from_reader("any_scope_state", PARAMETERS)


def _condition(root, **decoys):
    parsed = parse_text("ROOT = { " + queries.render(_query()) + " }")
    assert not parsed.errors
    return pdx_eval.condition(parsed.root, {"ROOT": root, **decoys})


def test_exact_template_preserves_market_and_tax_query_parameter_identities():
    assert queries.render(_query()) == EXPRESSION
    assert queries.from_reader("any_scope_state", {"threshold": "0.9"}) == (
        queries.AnyStateMarketAccessBelow(0.9)
    )
    assert queries.from_reader("any_scope_state", {"state_query": "tax_capacity_shortfall"}) == (
        queries.AnyIncorporatedStateTaxCapacityShortfall()
    )


@pytest.mark.parametrize(
    ("states", "expected"),
    [
        (None, None),
        ([], False),
        ([{}], None),
        ([{"turmoil": 0.1}], False),
        ([{"turmoil": 0.100001}], True),
        ([{"turmoil": 0}], False),
        ([{"turmoil": 0.9}, {}], True),
        ([{"turmoil": 0.05}, {}], None),
        ([{"turmoil": None}, {"turmoil": 0.1}], None),
    ],
)
def test_finite_own_state_collection_threshold_and_partial_unknowns(states, expected):
    assert _condition({"any_scope_state": states}) is expected


def test_flat_or_foreign_country_turmoil_cannot_supply_owned_state_need():
    assert (
        _condition(
            {"any_scope_state": [], "foreign": {"any_scope_state": [{"turmoil": 0.8}]}},
            any_scope_state=[{"turmoil": 0.8}],
            turmoil=0.8,
        )
        is False
    )
    assert _condition({}, any_scope_state=[{"turmoil": 0.8}]) is None
    with pytest.raises(pdx_eval.UnsupportedPdxError, match="完整对象列表"):
        _condition({"any_scope_state": True})


@pytest.mark.parametrize(
    "parameters",
    [
        {"state_query": "turmoil_above"},
        {"state_query": "turmoil_above", "threshold": ".1"},
        {"state_query": "turmoil_above", "threshold": "1.1"},
        {"state_query": "turmoil_above", "threshold": "nan"},
        {"state_query": "turmoil_above", "threshold": "0.1", "owner": "other"},
        {"state_query": "turmoil > .1 } always = yes", "threshold": "0.1"},
    ],
)
def test_reader_rejects_free_expressions_invalid_numbers_and_unbound_scopes(parameters):
    with pytest.raises(ValueError):
        queries.from_reader("any_scope_state", parameters)


def test_rendering_does_not_read_installation(monkeypatch):
    def fail(*_args, **_kwargs):
        pytest.fail("rendering performed I/O")

    monkeypatch.setattr(Path, "read_text", fail)
    monkeypatch.setattr(Path, "read_bytes", fail)
    assert queries.render(_query()) == EXPRESSION


@pytest.fixture
def native_texts():
    return {
        name: normalized_text((config.GAME / name).read_text(encoding="utf-8-sig"))
        for name in (ACW, PORTUGAL)
    }


@pytest.mark.integration
def test_locked_native_complete_country_collection_consumers_and_cost_contract(native_texts):
    compiled = queries.compile_query(_query(), native_texts)
    assert compiled.expression == EXPRESSION
    assert set(queries.required_sources(_query())) == {ACW, PORTUGAL}
    assert compiled.local_collections == ("owned_states",)
    assert compiled.world_scans == 0
    assert compiled.unknown_policy == queries.UNKNOWN_POLICY
    assert "not constant time" in compiled.runtime_cost
    assert {reference.rsplit(":", 1)[0] for reference in compiled.references} == {ACW, PORTUGAL}


@pytest.mark.integration
def test_native_fingerprint_and_complete_parent_ast_are_independent_requirements(
    native_texts, monkeypatch
):
    changed = native_texts[ACW].replace("turmoil > 0.1", "turmoil > 0.2")
    with pytest.raises(ValueError, match="来源漂移"):
        queries.compile_query(_query(), {**native_texts, ACW: changed})
    monkeypatch.setitem(queries.source_hashes(), ACW, hashlib.sha256(changed.encode()).hexdigest())
    with pytest.raises(ValueError, match="完整查询AST"):
        queries.compile_query(_query(), {**native_texts, ACW: changed})


@pytest.mark.parametrize("wanted", [True, False, None])
def test_all_policy_test_oracles_use_turmoil_objects_instead_of_market_access(wanted):
    from test_decision_adapters import _adapter_query_reference
    from test_situated_writer_pdx_oracle import _observed_values, _query_reference, _ReaderIndex

    policy = dict(decision_adapters.load().policies)["common/ai_strategies/00_default_strategy.txt"]
    reader = next(item for item in policy.readers if item.key == "owned_state_turmoil")
    values = _observed_values(_ReaderIndex.build(policy), {reader.key: wanted})
    assert _adapter_query_reference(reader, values.collections) is wanted
    assert _query_reference(reader, values.collections) is wanted
    assert _condition(values.collections) is wanted
