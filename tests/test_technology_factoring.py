"""Real technology factoring regressions against the independent catalog oracle.

No scratch renderer or production scoring function supplies expected answers.
Worlds come from raw catalog members; the oracle interprets their semantics.
"""

from __future__ import annotations

import copy
import json
from functools import cache
from itertools import product

import pytest
import technology_query_reference as reference

from pdx import decision_rules
from pdx import technology_opportunities as production
from pdx.parser import parse_text
from pdx.situated import pdx_eval, resources

RESTORED = (
    ("compression_ignition", "productive_ready", 18),
    ("compression_ignition", "labor_ready", 16),
    ("mechanized_workshops", "productive_ready", 7),
)
AFFECTED = (
    *(
        ("compression_ignition", purpose)
        for purpose in (
            "productive",
            "productive_ready",
            "labor",
            "labor_ready",
            "infrastructure",
            "local_supply",
        )
    ),
    ("mechanized_workshops", "productive"),
    ("mechanized_workshops", "productive_ready"),
)
PURPOSES = (
    "productive",
    "productive_ready",
    "labor",
    "labor_ready",
    "administration",
    "knowledge",
    "knowledge_ready",
    "infrastructure",
    "local_supply",
    "throughput",
    "trade",
    "construction",
    "resource",
    "infrastructure_direct",
    "scale",
)


@pytest.mark.parametrize(("technology", "purpose"), AFFECTED)
def test_factored_query_fits_actual_signed_envelope_depth(technology, purpose):
    # Exact block ancestry in generated 10_production.txt: technology,
    # ai_weight, if, multiply, add, if, limit, ROOT. These eight production
    # blocks count toward the global budget in addition to the query itself.
    expression = production.render_query(production.TechnologyUseQuery(technology, purpose))
    envelope = (
        technology + " = { ai_weight = { if = { multiply = { add = { "
        "if = { limit = { ROOT = { " + expression + " } } add = 0.25 } } } } } }"
    )
    metrics = resources.pdx_metrics(envelope)
    assert metrics["max_depth"] <= resources.load()["limits"]["max_depth"]


@pytest.mark.parametrize(
    "alternatives",
    [((0, 1), (1, 2), (0, 2)), ((0, 1), (0,)), ((0,), (1,), (2,))],
)
def test_flattened_factoring_preserves_complete_three_value_truth_table(alternatives):
    names = ("is_ai", "war", "has_debt")
    expression = production._factored_terms(
        [tuple(f"{names[index]} = yes" for index in row) for row in alternatives]
    )
    parsed = parse_text(expression)
    assert not parsed.errors
    # The independent truth ordering is False < unknown < True. Strong Kleene
    # conjunction/disjunction take min/max, including absorbing known values.
    truth = (False, None, True)
    for ranks in product(range(3), repeat=3):
        expected = truth[max(min(ranks[index] for index in row) for row in alternatives)]
        actual = pdx_eval.condition(
            parsed.root, dict(zip(names, (truth[r] for r in ranks), strict=True))
        )
        assert actual is expected


def _reader(technology, purpose):
    # This identity is independent of reader_spec() and query selection.
    return {
        "parameters": {
            "technology_query": "technology_use",
            "technology": technology,
            "purpose": purpose,
        }
    }


@cache
def _body(technology, purpose):
    parsed = parse_text(
        "ROOT = { "
        + production.render_query(production.TechnologyUseQuery(technology, purpose))
        + " }"
    )
    assert not parsed.errors
    return parsed.root


def _compare(technology, purpose, world):
    expected = reference.evaluate(_reader(technology, purpose), world)
    actual = pdx_eval.condition(_body(technology, purpose), {"ROOT": world})
    assert actual is expected
    return actual


MEMBERS = [
    pytest.param(
        technology,
        purpose,
        row,
        id=f"{technology}-{purpose}-{row['building']}-{row['prior']}-to-{row['method']}",
    )
    for technology, purpose, _ in RESTORED
    for row in reference._members(technology, purpose)
]


@pytest.mark.parametrize(("technology", "purpose", "row"), MEMBERS)
def test_every_restored_real_member_and_its_readiness_exits(technology, purpose, row):
    world = reference.realize_query_world(_reader(technology, purpose))
    building = world["any_scope_building"][0]
    building["is_building_type"] = {
        (("argument", key),): key == row["building"] for key in reference.BUILDING_IDENTITIES
    }
    building["has_active_production_method"] = {
        (("argument", key),): key == row["prior"] for key in reference.METHOD_IDENTITIES
    }
    if purpose.startswith("productive"):
        for value in world["market"].values():
            value["market_goods_delta"] = 0
        output = next(good for good in row["outputs"] if reference.CATALOG["goods"][good]["market"])
        world["market"][f"mg:{output}"]["market_goods_delta"] = -1
    assert _compare(technology, purpose, world) is True

    for good, amount in (row["inputs"] | row["losses"]).items():
        if amount <= 0:
            continue
        assert reference.CATALOG["goods"][good]["market"]
        for balance in (-1, None):
            changed = copy.deepcopy(world)
            changed["market"][f"mg:{good}"]["market_goods_delta"] = balance
            _compare(technology, purpose, changed)

    for method in (None, row["method"]):
        changed = copy.deepcopy(world)
        changed["any_scope_building"][0]["has_active_production_method"] = {
            (("argument", key),): key == method for key in reference.METHOD_IDENTITIES
        }
        assert _compare(technology, purpose, changed) is False
    if purpose.startswith("productive"):
        changed = copy.deepcopy(world)
        for value in changed["market"].values():
            value["market_goods_delta"] = 0
        assert _compare(technology, purpose, changed) is False
    else:
        for field, value in (("state_unemployment_rate", 0.02), ("occupancy", 0.89)):
            changed = copy.deepcopy(world)
            target = (
                changed["any_scope_state"][0]
                if field == "state_unemployment_rate"
                else changed["any_scope_building"][0]
            )
            target[field] = value
            assert _compare(technology, purpose, changed) is False


BOUNDARIES = (
    "missing-states",
    "unknown-states",
    "empty-states",
    "missing-buildings",
    "unknown-buildings",
    "empty-buildings",
    "missing-market",
    "absent-market",
    "empty-market",
    "unknown-market-deltas",
    "unknown-state-buildings",
    "unknown-building-identities",
    "split-building",
    "split-state",
)


def _boundary(world, case):
    if case in {
        f"{prefix}-{collection}"
        for prefix in ("missing", "unknown", "empty", "absent")
        for collection in ("states", "buildings", "market")
    }:
        prefix, collection = case.split("-", 1)
        key = {"states": "any_scope_state", "buildings": "any_scope_building", "market": "market"}[
            collection
        ]
        if prefix == "missing":
            del world[key]
        elif prefix in {"unknown", "absent"}:
            world[key] = None
        else:
            world[key] = {} if collection == "market" else []
    elif case == "unknown-market-deltas":
        for value in world["market"].values():
            value["market_goods_delta"] = None
    elif case == "unknown-state-buildings":
        world["any_scope_state"][0]["any_scope_building"] = None
    elif case == "unknown-building-identities":
        building = world["any_scope_building"][0]
        for field in ("is_building_type", "has_active_production_method"):
            building[field] = dict.fromkeys(building[field])
    elif case == "split-building":
        first = world["any_scope_building"][0]
        second = copy.deepcopy(first)
        first["has_active_production_method"] = dict.fromkeys(
            first["has_active_production_method"], False
        )
        second["is_building_type"] = dict.fromkeys(second["is_building_type"], False)
        world["any_scope_building"] = [first, second]
        world["any_scope_state"][0]["any_scope_building"] = [first, second]
    else:
        assert case == "split-state"
        first = world["any_scope_state"][0]
        second = copy.deepcopy(first)
        first["any_scope_building"] = []
        second["state_unemployment_rate"] = 1
        second["infrastructure_delta"] = 1
        for key, value in second.items():
            if key.startswith("sg:"):
                value["state_goods_pricier"] = 0
        world["any_scope_state"] = [first, second]


@pytest.mark.parametrize(("technology", "purpose"), AFFECTED)
@pytest.mark.parametrize("case", BOUNDARIES)
def test_factoring_preserves_unknown_empty_and_correlated_witnesses(technology, purpose, case):
    world = reference.realize_query_world(_reader(technology, purpose))
    assert _compare(technology, purpose, world) is True
    _boundary(world, case)
    actual = _compare(technology, purpose, world)
    if case == "split-building" or (
        case == "split-state"
        and purpose in {"labor", "labor_ready", "infrastructure", "local_supply"}
    ):
        assert actual is False


def _member_identity(row):
    return tuple(row.get(key, "") for key in ("kind", "building", "group", "prior", "method"))


def _canonical(row):
    return json.dumps(row, sort_keys=True)


def _independent_denominator():
    """Extend the reference's ordinary selector with raw direct modifier cases."""
    expected = {}
    for technology, profile in reference.CATALOG["technologies"].items():
        for purpose in PURPOSES:
            rows = reference._members(technology, purpose)
            if rows:
                expected[technology, purpose] = [_member_identity(row) for row in rows]
        modifier = profile["modifier"]
        if any(
            modifier.get(key, 0) > 0
            for key in (
                "building_construction_sector_throughput_add",
                "country_max_weekly_construction_progress_add",
            )
        ):
            expected[technology, "construction"] = [
                ("construction", "building_construction_sector", "", "", "")
            ]
        if modifier.get("building_economy_of_scale_level_cap_add", 0) > 0:
            expected[technology, "scale"] = [
                ("scale", building, "", "", "")
                for building, definition in reference.CATALOG["buildings"].items()
                if definition.get("scale")
                and any(
                    reference.CATALOG["goods"][good]["market"]
                    for good in definition["common_outputs"]
                )
            ]
        if any(
            modifier.get(key, 0) > 0
            for key in (
                "state_infrastructure_add",
                "state_infrastructure_from_population_add",
                "state_infrastructure_from_population_max_add",
            )
        ):
            expected[technology, "infrastructure_direct"] = [
                ("infrastructure_direct", "", "", "", "")
            ]
    return expected


def test_all_independent_queries_and_members_are_emitted_within_unchanged_budget():
    expected = _independent_denominator()
    assert len(expected) == 173
    assert sum(map(len, expected.values())) == 902
    assert decision_rules.STATIC_BUDGET["predicates_per_field"] == 160
    derived = production.derive({"rules": [], "sources": {}, "readers": {}})
    readers = {
        (spec["parameters"]["technology"], spec["parameters"]["purpose"]): (fact, spec)
        for fact, spec in derived["readers"].items()
        if spec.get("parameters", {}).get("technology_query") == "technology_use"
    }
    assert readers.keys() == expected.keys()
    used = {condition["fact"] for rule in derived["rules"] for condition in rule["conditions"]}
    for (technology, purpose), identities in expected.items():
        fact, spec = readers[technology, purpose]
        assert fact in used
        query = production.query_from_reader(spec["engine"], spec["parameters"])
        assert isinstance(query, production.TechnologyUseQuery)
        assert sorted(map(_member_identity, production.query_members(query))) == sorted(identities)
    for technology, purpose, count in RESTORED:
        assert len(reference._members(technology, purpose)) == count
        query = production.TechnologyUseQuery(technology, purpose)
        assert sorted(map(_canonical, production.query_members(query))) == sorted(
            map(_canonical, reference._members(technology, purpose))
        )
        matching = [
            rule for rule in derived["rules"] if rule["id"] == f"technology_{technology}_{purpose}"
        ]
        assert len(matching) == 1
        assert matching[0]["conditions"] == [
            {"fact": readers[technology, purpose][0], "op": "=", "value": True}
        ]
