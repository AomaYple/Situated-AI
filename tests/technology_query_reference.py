"""Independent collection oracle for the frozen research mechanism data.

This reads the artifact as data. It imports no production query selector,
renderer, compiler, generator or evaluator. Numeric expectations stay in tests.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_RAW = tomllib.loads(
    (Path(__file__).resolve().parents[1] / "mod/decisions/technology_opportunities.toml").read_text(
        encoding="utf-8"
    )
)
CATALOG = json.loads(_RAW["catalog_json"])
BUILDING_METHODS = {
    building: tuple(
        sorted(
            {method for group in row["groups"] for method in CATALOG["groups"][group]["methods"]}
        )
    )
    for building, row in CATALOG["buildings"].items()
}
BUILDING_IDENTITIES = tuple(sorted(BUILDING_METHODS))
METHOD_IDENTITIES = tuple(sorted(CATALOG["methods"]))


def _all(values):
    values = tuple(values)
    return False if False in values else None if None in values else True


def _any(values):
    values = tuple(values)
    return True if True in values else None if None in values else False


def _not(value):
    return None if value is None else not value


def _number(value, op, expected):
    if type(value) not in (int, float):
        return None
    return {
        "<": lambda: value < expected,
        ">": lambda: value > expected,
        ">=": lambda: value >= expected,
        "<=": lambda: value <= expected,
    }[op]()


def _parameter(facts, engine, argument=None, **parameters):
    observed = facts.get(engine)
    if observed is None:
        return None
    if not isinstance(observed, Mapping):
        raise ValueError("Technology query parameter observations require an identity map")
    identity = {"argument": argument} if argument is not None else parameters
    return observed.get(tuple(sorted(identity.items())))


def _collection(facts, key):
    collection = facts.get(key)
    if collection is None:
        return None
    if not isinstance(collection, (list, tuple)) or any(
        not isinstance(x, Mapping) for x in collection
    ):
        raise ValueError("Technology query collections require complete object lists")
    return collection


def _building(facts, building, method="", *, occupied=False, minimum_level=1):
    terms = [
        _parameter(facts, "is_building_type", building),
        _number(facts.get("level"), ">=", minimum_level),
    ]
    if method:
        terms.append(_parameter(facts, "has_active_production_method", method))
    if occupied:
        terms.append(_number(facts.get("occupancy"), ">=", 0.9))
    return _all(terms)


def _market(root, good, op, amount):
    if "market" not in root:
        return None
    market = root["market"]
    if market is None:
        return False
    if not isinstance(market, Mapping):
        raise ValueError("Technology market scope must be an object")
    if f"mg:{good}" not in market:
        return None
    goods = market[f"mg:{good}"]
    if goods is None:
        return False
    if not isinstance(goods, Mapping):
        raise ValueError("Technology market goods scope must be an object")
    return _number(goods.get("market_goods_delta"), op, amount)


def _gates(row, root):
    terms = [
        _parameter(root, "has_technology_researched", technology)
        for technology in row["requirements"]
    ]
    method = CATALOG["methods"].get(row["method"], {})
    laws = method.get("law_gates", {})
    if laws.get("unlocking_laws"):
        terms.append(
            _any(
                _parameter(root, "has_law_or_variant", f"law_type:{law}")
                for law in laws["unlocking_laws"]
            )
        )
    terms.extend(
        _not(_parameter(root, "has_law_or_variant", f"law_type:{law}"))
        for law in laws.get("disallowing_laws", [])
    )
    return _all(terms)


def _members(technology, purpose):
    profile = CATALOG["technologies"][technology]
    selected = []
    for row in profile["opportunities"]:
        if "unlocking_principles" in row["special_gates"]:
            continue
        services = row.get("services", {})
        ordinary = any(CATALOG["goods"][good]["market"] for good in row["outputs"])
        if purpose in {"productive", "productive_ready"}:
            keep = row["kind"] == "method" and ordinary
        elif purpose in {"labor", "labor_ready"}:
            keep = row["labor_saved"] > 0 and bool(row["prior"])
        elif purpose == "administration":
            keep = row["kind"] == "method" and services.get("country_bureaucracy_add", 0) > 0
        elif purpose == "knowledge":
            keep = row["kind"] == "method" and services.get("country_weekly_innovation_add", 0) > 0
        elif purpose == "infrastructure":
            keep = services.get("state_infrastructure_add", 0) > 0
        elif purpose == "local_supply":
            keep = any(CATALOG["goods"][good]["local"] for good in row["outputs"])
        elif purpose == "trade":
            keep = row["kind"] == "method" and services.get("state_trade_quantity_mult", 0) > 0
        elif purpose == "resource":
            keep = row["kind"] == "building" and services.get("country_minting_add", 0) > 0
        else:
            keep = False
        if keep:
            selected.append(row)
    if purpose == "throughput":
        for modifier, amount in profile["modifier"].items():
            building = modifier.removesuffix("_throughput_add")
            if (
                amount <= 0
                or not modifier.endswith("_throughput_add")
                or building not in BUILDING_METHODS
            ):
                continue
            outputs = {
                good: 1
                for method in BUILDING_METHODS[building]
                for good, value in CATALOG["methods"][method]["outputs"].items()
                if value > 0 and CATALOG["goods"][good]["market"]
            }
            if outputs:
                selected.append(
                    {
                        "kind": "throughput",
                        "building": building,
                        "prior": "",
                        "method": "",
                        "outputs": outputs,
                        "requirements": [],
                        "inputs": {},
                    }
                )
    return selected


def realize_query_world(reader):
    """Build a positive fixture from raw catalog data, never an expected value.

    Return one complete country object. The caller must bind this same object
    as ROOT when evaluating nested owned states/buildings. This deliberately
    calls no production query selector, renderer, evaluator or compiler.
    """
    parameters = dict(reader.parameters) if hasattr(reader, "parameters") else reader["parameters"]
    tag = parameters["technology_query"]
    purpose = parameters.get("purpose", "")
    technologies = set(CATALOG["technologies"])
    laws = set()
    for technology in CATALOG["technologies"].values():
        technologies.update(technology["prerequisites"])
        for row in technology["opportunities"]:
            technologies.update(row["requirements"])
    for method in CATALOG["methods"].values():
        technologies.update(method["technologies"])
        laws.update(method["law_gates"]["unlocking_laws"])
        laws.update(method["law_gates"]["disallowing_laws"])
    country: dict[str, Any] = {
        "any_scope_building": [],
        "any_scope_state": [],
        "has_technology_researched": {(("argument", key),): True for key in technologies},
        "has_law_or_variant": {(("argument", f"law_type:{key}"),): False for key in laws},
        "market": {f"mg:{key}": {"market_goods_delta": 0} for key in CATALOG["goods"]},
    }
    state: dict[str, Any] = {
        "state_unemployment_rate": 0.01,
        "infrastructure_delta": -1,
        "pop_type_percent_state": {(("target", "pop_type:peasants"),): 0.01},
        "has_potential_resource": {(("argument", key),): False for key in BUILDING_IDENTITIES},
        "any_scope_building": [],
        **{
            f"sg:{key}": {"state_goods_pricier": 0}
            for key, row in CATALOG["goods"].items()
            if row["local"]
        },
    }
    country["any_scope_state"] = [state]
    row = None
    if tag in {"existing_building", "existing_method", "labor_saving"}:
        building, method = parameters["building"], parameters.get("method", "")
    elif tag != "technology_use":
        raise ValueError("Unregistered finite technology query fixture")
    elif purpose == "infrastructure_direct":
        return country
    elif purpose == "construction":
        building, method = "building_construction_sector", ""
    elif purpose == "scale":
        building = next(
            key
            for key, definition in CATALOG["buildings"].items()
            if definition["scale"]
            and any(CATALOG["goods"][g]["market"] for g in definition["common_outputs"])
        )
        good = next(
            g
            for g in CATALOG["buildings"][building]["common_outputs"]
            if CATALOG["goods"][g]["market"]
        )
        country["market"][f"mg:{good}"]["market_goods_delta"] = -1
        method = ""
    else:
        candidates = _members(parameters["technology"], purpose)
        row = next(
            candidate
            for candidate in candidates
            if not purpose.endswith("_ready")
            or all(CATALOG["goods"][good]["market"] for good in candidate["inputs"])
        )
        building, method = row["building"], row["prior"]
        if row["method"]:
            gates = CATALOG["methods"][row["method"]]["law_gates"]
            if gates["unlocking_laws"]:
                law = gates["unlocking_laws"][0]
                country["has_law_or_variant"][(("argument", f"law_type:{law}"),)] = True
        if purpose.startswith("productive") or purpose == "throughput":
            good = next(g for g in row["outputs"] if CATALOG["goods"][g]["market"])
            country["market"][f"mg:{good}"]["market_goods_delta"] = -1
        elif purpose == "local_supply":
            good = next(g for g in row["outputs"] if CATALOG["goods"][g]["local"])
            state[f"sg:{good}"]["state_goods_pricier"] = 0.5
        elif purpose == "resource":
            state["has_potential_resource"][(("argument", building),)] = True
            return country
    observed_building = {
        "is_building_type": {(("argument", key),): key == building for key in BUILDING_IDENTITIES},
        "has_active_production_method": {
            (("argument", key),): key == method for key in METHOD_IDENTITIES
        },
        "level": 20 if purpose == "scale" else 1,
        "occupancy": 1,
        "weekly_profit": 1,
    }
    country["any_scope_building"] = [observed_building]
    state["any_scope_building"] = [observed_building]
    return country


def evaluate(reader, collections, root_facts=None):
    """Evaluate by full reader parameters and real country/state/building objects."""
    parameters = dict(reader.parameters) if hasattr(reader, "parameters") else reader["parameters"]
    root = collections if root_facts is None else root_facts
    tag = parameters["technology_query"]
    if tag in {"existing_building", "existing_method", "labor_saving"}:
        if tag == "labor_saving":
            states = _collection(collections, "any_scope_state")
            if states is None:
                return None

            def labor(state):
                buildings = _collection(state, "any_scope_building")
                return _all(
                    (
                        _number(state.get("state_unemployment_rate"), "<", 0.02),
                        _number(
                            _parameter(state, "pop_type_percent_state", target="pop_type:peasants"),
                            "<",
                            0.02,
                        ),
                        None
                        if buildings is None
                        else _any(
                            _building(
                                b, parameters["building"], parameters["method"], occupied=True
                            )
                            for b in buildings
                        ),
                    )
                )

            return _any(labor(state) for state in states)
        buildings = _collection(collections, "any_scope_building")
        return (
            None
            if buildings is None
            else _any(
                _building(b, parameters["building"], parameters.get("method", ""))
                for b in buildings
            )
        )
    if tag != "technology_use":
        raise ValueError("Unregistered finite technology query")
    technology, purpose = parameters["technology"], parameters["purpose"]
    states = purpose in {
        "labor",
        "labor_ready",
        "infrastructure",
        "local_supply",
        "resource",
        "infrastructure_direct",
    }
    collection = _collection(collections, "any_scope_state" if states else "any_scope_building")
    if collection is None:
        return None
    if purpose == "infrastructure_direct":
        return _any(_number(state.get("infrastructure_delta"), "<", 0) for state in collection)
    if purpose == "construction":
        return _any(
            _all(
                (
                    _building(b, "building_construction_sector"),
                    _number(b.get("occupancy"), ">=", 0.75),
                )
            )
            for b in collection
        )
    if purpose == "scale":
        selected = [
            (identity, row["common_outputs"])
            for identity, row in CATALOG["buildings"].items()
            if row.get("scale")
            and any(CATALOG["goods"][g]["market"] for g in row["common_outputs"])
        ]
        return _any(
            _all(
                (
                    _number(b.get("level"), ">=", 20),
                    _number(b.get("occupancy"), ">=", 0.75),
                    _any(
                        _all(
                            (
                                _parameter(b, "is_building_type", identity),
                                _any(
                                    _market(root, g, "<", 0)
                                    for g in goods
                                    if CATALOG["goods"][g]["market"]
                                ),
                            )
                        )
                        for identity, goods in selected
                    ),
                )
            )
            for b in collection
        )
    members = _members(technology, purpose)
    answers = []
    for row in members:
        if purpose.endswith("_ready") and any(
            amount > 0 and not CATALOG["goods"][good]["market"]
            for good, amount in (row["inputs"] | row.get("losses", {})).items()
        ):
            continue
        ready = (
            _all(
                _market(root, good, ">=", 0)
                for good, amount in (row["inputs"] | row.get("losses", {})).items()
                if amount > 0
            )
            if purpose.endswith("_ready")
            else True
        )
        common = [_gates(row, root), ready]
        if purpose.startswith("productive") or purpose == "throughput":
            common.append(
                _any(
                    _market(root, g, "<", 0)
                    for g in row["outputs"]
                    if CATALOG["goods"][g]["market"]
                )
            )
        if not states:
            candidates = []
            for building in collection:
                terms = [*common, _building(building, row["building"], row["prior"])]
                if purpose == "trade":
                    terms.extend(
                        (
                            _number(building.get("occupancy"), ">=", 0.75),
                            _number(building.get("weekly_profit"), ">", 0),
                        )
                    )
                candidates.append(_all(terms))
            answers.append(_any(candidates))
            continue
        candidates = []
        for state in collection:
            terms = list(common)
            if purpose.startswith("labor"):
                terms.extend(
                    (
                        _number(state.get("state_unemployment_rate"), "<", 0.02),
                        _number(
                            _parameter(state, "pop_type_percent_state", target="pop_type:peasants"),
                            "<",
                            0.02,
                        ),
                    )
                )
            elif purpose == "infrastructure":
                terms.append(_number(state.get("infrastructure_delta"), "<", 0))
            elif purpose == "local_supply":
                terms.append(
                    _any(
                        _number(
                            (state.get(f"sg:{good}") or {}).get("state_goods_pricier"), ">", 0.25
                        )
                        for good in row["outputs"]
                        if CATALOG["goods"][good]["local"]
                    )
                )
            elif purpose == "resource":
                terms.append(_parameter(state, "has_potential_resource", row["building"]))
            if purpose.startswith("labor") or (purpose != "resource" and row["kind"] == "method"):
                buildings = _collection(state, "any_scope_building")
                terms.append(
                    None
                    if buildings is None
                    else _any(
                        _building(
                            b, row["building"], row["prior"], occupied=purpose.startswith("labor")
                        )
                        for b in buildings
                    )
                )
            candidates.append(_all(terms))
        answers.append(_any(candidates))
    return _any(answers)
