"""Production-generated legacy writer witnesses against an independent oracle.

This is a static check, not an engine execution test.  Every case is named by
source and rule identity.  Generated output is kept in memory; the frozen mod
tree is never read as the output oracle or modified.
"""

from __future__ import annotations

import math
import operator
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, cast

import pytest

from pdx import country_state, decision_adapters, decision_interfaces, decision_rules, policy_audit
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import action_instances, compiler, pdx_eval

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = pytest.mark.unit
INFO = "mod/decisions/information.toml"
_MARKER = re.compile(r"^\s*# ([a-z][a-z0-9_]*) \[[a-z][a-z0-9_]*\];")
_OPS = {"=": operator.eq, "<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}
_COLLECTIONS = frozenset(
    {"any_scope_state", "any_scope_building", "any_political_movement", "any_interest_group"}
)


@dataclass(frozen=True)
class _ReaderIndex:
    readers: Mapping[str, decision_rules.Reader]
    aliases: Mapping[str, tuple[str, ...]]

    @classmethod
    def build(cls, policy):
        observations: dict[tuple[object, ...], list[str]] = defaultdict(list)
        readers = {reader.key: reader for reader in policy.readers}
        for reader in policy.readers:
            identity = (
                reader.engine,
                reader.scope,
                reader.path,
                reader.argument,
                tuple(sorted(reader.parameters)),
                reader.value_field,
            )
            observations[identity].append(reader.key)
        aliases = {key: tuple(keys) for keys in observations.values() for key in keys}
        return cls(readers, aliases)

    def normalize(self, values: Mapping[str, object]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values.items():
            for alias in self.aliases[key]:
                assert alias not in result or result[alias] == value, (
                    f"contradictory aliases: {key}/{alias}"
                )
                result[alias] = value
        return result

    def change(self, values: Mapping[str, object], key: str, value: object) -> dict[str, object]:
        result = dict(values)
        for alias in self.aliases[key]:
            result[alias] = value
        assert all(result[alias] == value for alias in self.aliases[key])
        return result


@dataclass(frozen=True)
class _ParsedBranch:
    identity: str
    limit: Block
    operation: str
    delta: float
    proof_only: bool = False

    @classmethod
    def build(cls, identity: str, branch: Block):
        items = _ordinary_assignments(branch)
        assert len(items) == 2, identity
        assert items[0].key == "limit", identity
        if items[1].key == "if":
            assert isinstance(items[1].value, Block), identity
            nested = cls.build(identity, items[1].value)
            assert not nested.proof_only, identity
            inner_limit = items[1].value.first("limit")
            assert inner_limit is not None, identity
            assert isinstance(inner_limit.value, Block), identity
            assert len(inner_limit.value.items) == 1, identity
            always = inner_limit.value.first("always")
            assert always is not None, identity
            assert isinstance(always.value, Scalar), identity
            assert always.value.unquoted == "yes", identity
            assert isinstance(items[0].value, Block), identity
            _ordinary_condition(items[0].value)
            return cls(identity, items[0].value, nested.operation, nested.delta, True)
        assert items[1].key in {"add", "multiply"}, identity
        limit, effect = items
        assert isinstance(limit.value, Block), identity
        _ordinary_condition(limit.value)
        value = effect.value
        if isinstance(value, Block):
            terms = _ordinary_assignments(value)
            assert 1 <= len(terms) <= 2, identity
            assert terms[0].key == "value", identity
            if len(terms) == 2:
                assert terms[1].key == "desc", identity
                assert isinstance(terms[1].value, Scalar), identity
            value = terms[0].value
        assert isinstance(value, Scalar), identity
        assert not value.quoted, identity
        delta = float(value.text)
        assert math.isfinite(delta), identity
        return cls(identity, limit.value, effect.key, delta)


def _ordinary_assignments(block: Block) -> tuple[Assignment, ...]:
    result = []
    for item in block.items:
        assert isinstance(item, Assignment), "unsupported anonymous block or bare item"
        assert item.op == "=", "unsupported assignment operator"
        assert item.prefix is None, "unsupported assignment prefix"
        result.append(item)
    return tuple(result)


def _ordinary_condition(block: Block) -> None:
    # Numeric comparisons inside limit are part of the supported PDX predicate
    # language. Prefixes and anonymous/bare nodes are never ordinary predicates.
    for item in block.items:
        assert isinstance(item, Assignment), "unsupported condition item"
        assert item.prefix is None, "unsupported condition prefix"
        assert item.op in {"=", "<", "<=", ">", ">="}, "unsupported condition operator"
        if isinstance(item.value, Block):
            _ordinary_condition(item.value)
        else:
            assert isinstance(item.value, Scalar), "missing condition value"


@dataclass(frozen=True)
class _ParsedChain:
    """Immutable AST of the actual legacy chain; no production selector.

    Accept flat writes or one write-free proof around a static write; reject
    every other nesting/effect shape rather than silently approximate it.
    Conditions and effects use the independent PDX interpreter. Equivalence to
    its public text path is checked separately for every actual writer/field.
    """

    branches: tuple[_ParsedBranch, ...]

    @classmethod
    def build(cls, text: str):
        parsed = parse_text(text)
        assert not parsed.errors, parsed.errors
        markers: dict[int, str] = {}
        for line_number, line in enumerate(text.splitlines(), 1):
            if match := _MARKER.match(line):
                markers[line_number + 1] = match.group(1)
        result = []
        for index, assignment in enumerate(_ordinary_assignments(parsed.root)):
            assert assignment.key == ("if" if index == 0 else "else_if")
            assert isinstance(assignment.value, Block)
            assert assignment.line in markers, assignment.line
            result.append(_ParsedBranch.build(markers[assignment.line], assignment.value))
        assert result
        return cls(tuple(result))

    def select(self, facts: Mapping[str, object]):
        for branch in self.branches:
            outcome = pdx_eval.condition(branch.limit, facts)
            if outcome is None and not branch.proof_only:
                return pdx_eval.PdxDecision(branch.identity, None, 0.0, "unknown")
            if outcome is True:
                return pdx_eval.PdxDecision(
                    branch.identity, branch.operation, branch.delta, "selected"
                )
        return pdx_eval.PdxDecision(None, None, 0.0, "vanilla")


@pytest.mark.parametrize(
    ("rule_id", "key", "alias"),
    [
        ("institution_supply_supply_need", "navy", "own_navy"),
        ("health_public_low_living_need", "average_sol", "sol"),
        ("lj07_grain_health_social_capacity", "average_sol", "sol"),
    ],
)
def test_real_alias_counterfactuals_retain_missing_and_threshold_observations(rule_id, key, alias):
    policy = dict(decision_adapters.load().policies)["common/ai_strategies/00_default_strategy.txt"]
    rule = next(item for item in policy.rules if item.id == rule_id)
    cases = list(_cases(policy, rule))
    missing = next(values for name, values, _ in cases if name == f"unknown:{key}")
    assert missing[key] is None
    active_alias = alias in {reader.key for reader in policy.readers}
    if active_alias:
        assert missing[alias] is None
    assert _truth(rule, missing) is None
    for name, values, _ in cases:
        if name.startswith(f"negative:{key}"):
            if active_alias:
                assert values[key] == values[alias]
            assert _truth(rule, values) is False
        if name.startswith(f"threshold:{key}:"):
            boundary = float(name.rsplit(":", 1)[1])
            assert values[key] == boundary
            if active_alias:
                assert values[alias] == boundary


@pytest.mark.parametrize(
    "body",
    [
        "limit = { always = yes } multiply = { value = 1 if = { limit = { ROOT = { navy_size > 10 } } add = 0.2 } }",
        "limit = { always = yes } multiply = 1 limit = { always = no }",
        "limit = { always = yes } multiply = 1 multiply = 2",
        "limit = { always = yes } multiply = 1 add = 2",
        "limit = { always = yes } multiply = { value = 1 value = 2 }",
        "limit = { always = yes } multiply = { value = 1 desc = A desc = B }",
        "limit = { always = yes } multiply = { value = 1 add = 2 }",
        "limit = { always = yes } multiply = { value = 1 { hidden = yes } }",
        "limit = { always = yes } multiply = { value = 1 hidden }",
        "limit = { always = yes } multiply = { value = 1 desc = { hidden = yes } }",
        "limit = { always = yes } multiply = 1 { hidden = yes }",
        "limit = { always = yes } multiply = 1 hidden",
        "REPLACE:limit = { always = yes } multiply = 1",
        "limit = { always = yes } REPLACE:multiply = 1",
        "limit = { always = yes } multiply > 1",
        "limit > { always = yes } multiply = 1",
        "limit = { always = yes } multiply = { REPLACE:value = 1 }",
        "limit = { always = yes } multiply = { value > 1 }",
        "limit = { always = yes } multiply = { value = 1 REPLACE:desc = A }",
        "limit = { always = yes } multiply = nan",
        "limit = { always = yes } multiply = inf",
        "limit = { always = yes } multiply = yes",
        'limit = { always = yes } multiply = "1"',
        "limit = { always = yes } multiply = { desc = A }",
        "limit = { always = yes } multiply = { value = inf }",
    ],
)
def test_static_fast_branch_rejects_unsupported_shape(body):
    parsed = parse_text(f"if = {{ {body} }}")
    assert not parsed.errors
    assignment = parsed.root.first("if")
    assert assignment is not None
    assert isinstance(assignment.value, Block)
    with pytest.raises((AssertionError, pdx_eval.UnsupportedPdxError, ValueError)):
        _ParsedBranch.build("test_writer", assignment.value)


@pytest.mark.parametrize(
    "text",
    [
        "# test_writer [generated];\nif = { limit = { always = yes } multiply = 1 }\nhidden",
        "# test_writer [generated];\nif = { limit = { always = yes } multiply = 1 }\n{ hidden = yes }",
        "# test_writer [generated];\nREPLACE:if = { limit = { always = yes } multiply = 1 }",
        "# test_writer [generated];\nif > { limit = { always = yes } multiply = 1 }",
    ],
)
def test_static_fast_chain_rejects_unsupported_root(text):
    with pytest.raises((AssertionError, pdx_eval.UnsupportedPdxError, ValueError)):
        _ParsedChain.build(text)


@pytest.mark.parametrize("effect", ["1.25", "{ value = 1.25 }", "{ value = 1.25 desc = REASON }"])
def test_static_fast_chain_accepts_exact_static_effect(effect):
    text = f"# test_writer [generated];\nif = {{ limit = {{ ROOT = {{ is_ai = yes }} }} multiply = {effect} }}"
    chain = _ParsedChain.build(text)
    for facts in ({"ROOT": {"is_ai": True}}, {"ROOT": {"is_ai": False}}, {}):
        assert chain.select(facts) == pdx_eval.select(text, facts)


@pytest.mark.parametrize(
    ("war", "navy", "expected"),
    [
        (True, -1, None),
        (True, float("nan"), None),
        (True, float("inf"), None),
        (True, True, None),
        (True, None, None),
        (True, 0, False),
        (True, 1, True),
        (False, None, False),
        (False, -1, False),
    ],
)
def test_independent_oracle_retains_reader_validity_and_known_false_dominance(war, navy, expected):
    policy = dict(decision_adapters.load().policies)[
        "common/technology/technologies/20_military.txt"
    ]
    rule = next(item for item in policy.rules if item.id == "technology_admiralty_navy_war")
    index = _ReaderIndex.build(policy)
    values = {"war": war, "own_navy": navy}
    assert _truth(rule, values, index) is expected


@pytest.fixture(scope="module")
def generated():
    """Read locked originals once and run the actual lowering without writing files."""
    adapters = decision_adapters.load()
    info = decision_rules.load()
    model = compiler.load_model()
    assert model.consumer_ir is not None
    inputs = decision_adapters.read_inputs(adapters)
    policies = ((INFO, info), *adapters.policies)
    compiled, _report = compiler.compile_sources(info, adapters, config_model=model)
    by_source = dict(compiled)
    country = country_state.load()
    files, _ = decision_adapters.build(
        replace(adapters, policies=compiled[1:]),
        texts=inputs,
        country_policy=country,
        consumer_ir=model.consumer_ir,
    )
    baseline = compiler.baseline_path().read_text(encoding="utf-8")
    info_text = decision_rules.patch(
        baseline,
        by_source[INFO],
        baseline=baseline,
        reader_words=(
            frozenset(decision_adapters.reader_evidence(inputs))
            | decision_interfaces.proven_reader_words()
        ),
        country_policy=country,
        consumer_ir=model.consumer_ir,
        consumer_source=INFO,
    )
    return policies, model, files, info_text, inputs, baseline


def _blocks(text: str) -> dict[str, tuple[Block, _ParsedChain, str]]:
    """Parse each real marked branch, retaining duplicate identities as errors."""
    lines = text.splitlines()
    result: dict[str, tuple[Block, _ParsedChain, str]] = {}
    for index, line in enumerate(lines):
        match = _MARKER.match(line)
        if match is None:
            continue
        name = match.group(1)
        if name in result:
            raise AssertionError(f"duplicate generated writer: {name}")
        # The production lowerer emits a complete branch on the marker's next line.
        fragment = lines[index + 1].strip()
        parsed = parse_text(fragment)
        assert not parsed.errors, (name, parsed.errors)
        roots = _ordinary_assignments(parsed.root)
        assert len(roots) == 1, name
        branch = roots[0]
        assert branch.key in {"if", "else_if"}, name
        assert isinstance(branch.value, Block), name
        marked = f"# {name} [generated];\n{fragment}"
        if branch.key == "else_if":
            marked = "if = { limit = { always = no } }\n" + marked
        compiled_branch = _ParsedBranch.build(name, branch.value)
        compiled = _ParsedChain((compiled_branch,))
        effective = branch.value
        if compiled_branch.proof_only:
            inner = branch.value.first("if")
            assert inner is not None
            assert isinstance(inner.value, Block)
            outer_limit = branch.value.first("limit")
            assert outer_limit is not None
            effective = Block(
                [
                    outer_limit,
                    *(item for item in inner.value.items if getattr(item, "key", None) != "limit"),
                ]
            )
        result[name] = (effective, compiled, marked)
    return result


def _known(reader: decision_rules.Reader, value: object) -> bool:
    if reader.kind == "boolean":
        return type(value) is bool
    if type(value) not in (int, float) or not math.isfinite(cast("float", value)):
        return False
    number = cast("float", value)
    return (reader.minimum is None or number >= reader.minimum) and (
        reader.maximum is None or number <= reader.maximum
    )


def _truth(
    rule: decision_rules.Rule,
    values: Mapping[str, object],
    reader_index: _ReaderIndex | None = None,
) -> bool | None:
    """Independent conjunction over source predicates, without production selectors."""
    unknown = False
    for predicate in rule.conditions:
        left = values.get(predicate.fact)
        right = (
            values.get(predicate.value.key)
            if isinstance(predicate.value, decision_rules.FactReference)
            else predicate.value
        )
        valid = (
            left is not None and right is not None
            if reader_index is None
            else _known(reader_index.readers[predicate.fact], left)
            and (
                not isinstance(predicate.value, decision_rules.FactReference)
                or _known(reader_index.readers[predicate.value.key], right)
            )
        )
        if not valid:
            unknown = True
        elif not _OPS[predicate.op](cast("Any", left), cast("Any", right)):
            return False
    if reader_index is None:
        unknown |= any(type(values.get(key)) is not bool for key in rule.required_known_facts)
    else:
        unknown |= any(
            not _known(reader_index.readers[key], values.get(key))
            for key in rule.required_known_facts
        )
    return None if unknown else True


class _ObservedValues(dict[str, object]):
    """Scalar observations and query results derived from one owned world."""

    def __init__(self, values, collections, root_facts=None):
        super().__init__(values)
        self.collections = collections
        self.root_facts = {} if root_facts is None else root_facts


def _query_reference(reader, collections, root_facts=None):
    """Handwritten member semantics; never use a renderer or PDX for expectations."""

    def conjunction(*values):
        return False if False in values else None if None in values else True

    def exists(members, predicate):
        if members is None:
            return None
        outcomes = [predicate(member) for member in members]
        return True if True in outcomes else None if None in outcomes else False

    def compare(value, op, expected):
        return None if value is None or expected is None else op(value, expected)

    def identity(member, engine, argument):
        observed = member.get(engine)
        return None if observed is None else observed.get((("argument", argument),))

    def capacity(member, building):
        return conjunction(
            identity(member, "is_building_type", building),
            compare(member.get("level"), operator.ge, 1),
        )

    params = dict(reader.parameters)
    if "technology_query" in params:
        from technology_query_reference import evaluate

        return evaluate(reader, collections, root_facts)
    query = params.get("company_query")
    if reader.engine == "any_scope_building":

        def building(member):
            if query == "trade_business_pressure":
                return conjunction(
                    capacity(member, "building_trade_center"),
                    compare(member.get("weekly_profit"), operator.lt, 0),
                    compare(member.get("cash_reserves_ratio"), operator.lt, 0.25)
                    if params["tier"] == "strong"
                    else True,
                )
            if query == "existing_business":
                strong = params["tier"] == "strong"
                return conjunction(
                    capacity(member, params["building"]),
                    compare(member.get("weekly_profit"), operator.gt, 0),
                    compare(member.get("occupancy"), operator.ge, 0.9 if strong else 0.75),
                    compare(member.get("cash_reserves_ratio"), operator.gt, 0.5)
                    if strong
                    else True,
                )
            assert query in {None, "port_method"}
            return conjunction(
                capacity(member, params.get("building", "building_port")),
                identity(member, "has_active_production_method", params["method"]),
                compare(member.get("level"), operator.ge, int(params.get("min_level", "1"))),
            )

        return exists(collections[reader.engine], building)
    if reader.engine == "any_scope_state":

        def state(member):
            if params.get("state_query") == "turmoil_above":
                return compare(member.get("turmoil"), operator.gt, float(params["threshold"]))
            if "threshold" in params:
                return compare(member.get("market_access"), operator.lt, float(params["threshold"]))
            if params == {"state_query": "tax_capacity_shortfall"}:
                return conjunction(
                    member.get("is_incorporated"),
                    compare(
                        member.get("tax_capacity"), operator.lt, member.get("tax_capacity_usage")
                    ),
                )
            assert query in {"rail_infrastructure", "power_scarcity"}
            railway = query == "rail_infrastructure"
            good = "transportation" if railway else "electricity"
            return conjunction(
                exists(
                    member.get("any_scope_building"),
                    lambda candidate: capacity(
                        candidate, "building_railway" if railway else "building_power_plant"
                    ),
                ),
                compare(member.get("infrastructure_delta"), operator.lt, 0) if railway else True,
                compare(
                    member.get(f"sg:{good}", {}).get("state_goods_pricier"),
                    operator.gt,
                    float(params["minimum_price"]),
                )
                if "minimum_price" in params
                else True,
            )

        return exists(collections[reader.engine], state)
    assert reader.engine in {"any_political_movement", "any_interest_group"}

    def political(member):
        movement = reader.engine == "any_political_movement"
        engine = "law_enactment_stance" if movement else "law_stance"
        return conjunction(
            compare(member[engine].get((("law", "law_type:" + params["law"]),)), operator.gt, 0),
            compare(
                member.get("political_movement_support"),
                operator.ge,
                float(params["minimum_support"]),
            )
            if movement
            else True,
        )

    return exists(collections[reader.engine], political)


def _observed_values(index, requested):
    """Realize fixtures with real members, then recompute every query alias.

    The old source fixture requests one Boolean per query independently. Those
    requests are only witness construction hints: a strong business also makes
    its base query true, and state/country buildings describe the same objects.
    All expected rule results are recalculated from the resulting shared world.
    """
    query_readers = [reader for reader in index.readers.values() if reader.engine in _COLLECTIONS]
    collections: dict[str, Any] = {
        "any_scope_state": [],
        "any_scope_building": [],
        "any_political_movement": [],
        "any_interest_group": [],
    }
    from technology_query_reference import (
        BUILDING_IDENTITIES,
        METHOD_IDENTITIES,
        realize_query_world,
    )

    root_facts: dict[str, Any] = {}
    types = {
        *BUILDING_IDENTITIES,
        "building_art_academy",
        "building_port",
        "building_railway",
        "building_power_plant",
        "building_gold_mine",
        "building_trade_center",
    }
    methods = set(METHOD_IDENTITIES) | {
        dict(reader.parameters)["method"]
        for reader in query_readers
        if "method" in dict(reader.parameters)
    }

    def building(kind, method=None, *, strong=False):
        return {
            "is_building_type": {(("argument", item),): item == kind for item in types},
            "has_active_production_method": {
                (("argument", item),): item == method for item in methods
            },
            "level": 1,
            "weekly_profit": 1,
            "occupancy": 1 if strong else 0.75,
            "cash_reserves_ratio": 1 if strong else 0,
        }

    def state():
        return {
            "any_scope_building": [],
            "market_access": 1,
            "turmoil": 0,
            "is_incorporated": False,
            "tax_capacity": 10,
            "tax_capacity_usage": 0,
            "infrastructure_delta": 0,
            "sg:transportation": {"state_goods_pricier": 0},
            "sg:electricity": {"state_goods_pricier": 0},
        }

    observed = set()
    missing = set()
    for reader in query_readers:
        if reader.key not in requested:
            continue
        signature = (reader.engine, reader.parameters)
        if signature in observed:
            continue
        observed.add(signature)
        wanted = requested[reader.key]
        if wanted is None:
            missing.add(reader.engine)
            continue
        assert type(wanted) is bool
        if not wanted:
            continue
        params = dict(reader.parameters)
        query = params.get("company_query")
        if "technology_query" in params:
            world = realize_query_world(reader)
            collections["any_scope_state"].extend(world.get("any_scope_state", []))
            # All aggregate readers observe the same owned world; building
            # membership is rebuilt from these states below.
            for key, value in world.items():
                if key in _COLLECTIONS:
                    continue
                if isinstance(value, dict):
                    target = root_facts.setdefault(key, {})
                    for identity, observed_value in value.items():
                        if isinstance(observed_value, dict):
                            target.setdefault(identity, {}).update(observed_value)
                        else:
                            target[identity] = observed_value
                else:
                    root_facts[key] = value
            continue
        if reader.engine == "any_scope_building":
            member = building(
                params.get("building", "building_port"),
                params.get("method"),
                strong=params.get("tier") == "strong",
            )
            member["level"] = int(params.get("min_level", "1"))
            if query == "trade_business_pressure":
                member["is_building_type"] = {
                    (("argument", item),): item == "building_trade_center" for item in types
                }
                member["weekly_profit"] = -1
                member["cash_reserves_ratio"] = 0 if params["tier"] == "strong" else 0.5
            owned = state()
            owned["any_scope_building"].append(member)
            collections["any_scope_state"].append(owned)
        elif reader.engine == "any_scope_state":
            owned = state()
            if params.get("state_query") == "turmoil_above":
                owned["turmoil"] = (float(params["threshold"]) + 1) / 2
            elif "threshold" in params:
                owned["market_access"] = float(params["threshold"]) / 2
            elif params == {"state_query": "tax_capacity_shortfall"}:
                owned.update(is_incorporated=True, tax_capacity=0, tax_capacity_usage=1)
            else:
                assert query in {"rail_infrastructure", "power_scarcity"}
                railway = query == "rail_infrastructure"
                owned["any_scope_building"].append(
                    building("building_railway" if railway else "building_power_plant")
                )
                owned["infrastructure_delta"] = -1 if railway else 0
                good = "transportation" if railway else "electricity"
                owned[f"sg:{good}"]["state_goods_pricier"] = (
                    (float(params["minimum_price"]) + 0.75) / 2 if "minimum_price" in params else 0
                )
            collections["any_scope_state"].append(owned)
        else:
            movement = reader.engine == "any_political_movement"
            engine = "law_enactment_stance" if movement else "law_stance"
            laws = {
                dict(item.parameters)["law"]
                for item in query_readers
                if item.engine == reader.engine
            }
            collections[reader.engine].append(
                {
                    engine: {
                        (("law", "law_type:" + law),): int(law == params["law"]) for law in laws
                    },
                    "political_movement_support": float(params.get("minimum_support", "0")),
                }
            )
    if "any_scope_state" in missing or "any_scope_building" in missing:
        collections["any_scope_state"] = collections["any_scope_building"] = None
    else:
        collections["any_scope_building"] = [
            member
            for owned in collections["any_scope_state"]
            for member in owned["any_scope_building"]
        ]
    for engine in missing - {"any_scope_state", "any_scope_building"}:
        collections[engine] = None
    # Use exactly the physical scalar facts that _facts will present to PDX.
    # Explicit requested observations override helper-world setup hints.
    for key, value in requested.items():
        reader = index.readers[key]
        if reader.engine in _COLLECTIONS or reader.scope != "root":
            continue
        current = root_facts
        for part in reader.path:
            current = current.setdefault(part, {})
        if reader.engine == "is_production_method_active":
            params = dict(reader.parameters)
            current.setdefault(reader.engine, {}).setdefault(params["building_type"], {})[
                params["production_method"]
            ] = value
        elif reader.argument is not None or reader.parameters or reader.value_field:
            params = dict(reader.parameters)
            if reader.argument is not None:
                params["argument"] = reader.argument
            current.setdefault(reader.engine, {})[tuple(sorted(params.items()))] = value
        else:
            current[reader.engine] = value
    result = _ObservedValues(requested, collections, root_facts)
    for reader in query_readers:
        result[reader.key] = _query_reference(reader, collections, root_facts)
    return result


def _collection_test_policy():
    def query(key, engine, **parameters):
        return decision_rules.Reader(
            key, engine, "root", "boolean", "boolean", parameters=tuple(sorted(parameters.items()))
        )

    base = query(
        "base",
        "any_scope_building",
        company_query="existing_business",
        building="building_gold_mine",
        tier="base",
    )
    return decision_rules.RuleSet(
        readers=(
            base,
            replace(base, key="base_alias"),
            query(
                "strong",
                "any_scope_building",
                company_query="existing_business",
                building="building_gold_mine",
                tier="strong",
            ),
            query("rail", "any_scope_state", company_query="rail_infrastructure"),
            query(
                "rail_price",
                "any_scope_state",
                company_query="rail_infrastructure",
                minimum_price="0.25",
            ),
            query(
                "movement", "any_political_movement", law="law_free_trade", minimum_support="0.10"
            ),
            query("ig", "any_interest_group", law="law_anarchy"),
        ),
        rules=(),
        baseline_sha256="0" * 64,
        source_sha256="0" * 64,
        enabled_domains=frozenset(),
    )


def test_collection_witnesses_recompute_shared_business_tiers_and_complete_aliases():
    policy = _collection_test_policy()
    index = _ReaderIndex.build(policy)
    values = _observed_values(index, {"strong": True, "base": False})
    assert values["strong"] is values["base"] is values["base_alias"] is True
    members = values.collections["any_scope_building"]
    assert len(members) == 1
    assert members[0] is values.collections["any_scope_state"][0]["any_scope_building"][0]
    facts = _facts(policy, values, is_ai=True, reader_index=index)
    condition = parse_text(
        "ROOT = { any_scope_building = { is_building_type = building_gold_mine "
        "weekly_profit > 0 occupancy >= 0.75 level >= 1 } }"
    ).root
    assert pdx_eval.condition(condition, facts) is True


@pytest.mark.parametrize("observation", ["missing", "empty", "unknown_member", "known_member"])
def test_collection_reference_and_actual_pdx_keep_three_valued_member_semantics(observation):
    policy = _collection_test_policy()
    index = _ReaderIndex.build(policy)
    values = _observed_values(
        index, {"base": None if observation == "missing" else observation != "empty"}
    )
    if observation == "unknown_member":
        values.collections["any_scope_building"][0]["occupancy"] = None
    reader = index.readers["base"]
    expected = {"missing": None, "empty": False, "unknown_member": None, "known_member": True}[
        observation
    ]
    assert _query_reference(reader, values.collections) is expected
    condition = parse_text(
        "ROOT = { any_scope_building = { is_building_type = building_gold_mine "
        "weekly_profit > 0 occupancy >= 0.75 level >= 1 } }"
    ).root
    assert (
        pdx_eval.condition(condition, _facts(policy, values, is_ai=True, reader_index=index))
        is expected
    )


def test_state_queries_share_members_prices_and_keep_same_state_identity():
    policy = _collection_test_policy()
    index = _ReaderIndex.build(policy)
    values = _observed_values(index, {"rail_price": True, "rail": False})
    assert values["rail"] is values["rail_price"] is True
    condition = parse_text(
        "ROOT = { any_scope_state = { any_scope_building = { "
        "is_building_type = building_railway level >= 1 } infrastructure_delta < 0 } }"
    ).root
    owned = values.collections["any_scope_state"][0]
    owned["infrastructure_delta"] = 0
    values.collections["any_scope_state"].append(
        {**owned, "any_scope_building": [], "infrastructure_delta": -1}
    )
    assert _query_reference(index.readers["rail"], values.collections) is False
    assert (
        pdx_eval.condition(condition, _facts(policy, values, is_ai=True, reader_index=index))
        is False
    )


@pytest.mark.parametrize("key", ["movement", "ig"])
def test_political_query_witnesses_keep_parameter_identity_and_unknown_stance(key):
    policy = _collection_test_policy()
    index = _ReaderIndex.build(policy)
    values = _observed_values(index, {key: True})
    reader = index.readers[key]
    assert values[key] is True
    member = values.collections[reader.engine][0]
    engine = "law_enactment_stance" if key == "movement" else "law_stance"
    law = "law_free_trade" if key == "movement" else "law_anarchy"
    member[engine][(("law", "law_type:" + law),)] = None
    assert _query_reference(reader, values.collections) is None
    condition = parse_text(
        f"ROOT = {{ {reader.engine} = {{ {engine} = {{ law = law_type:{law} value > neutral }} "
        + ("political_movement_support >= 0.1 " if key == "movement" else "")
        + "} }"
    ).root
    assert (
        pdx_eval.condition(condition, _facts(policy, values, is_ai=True, reader_index=index))
        is None
    )


def test_required_known_ai_observation_and_player_guard_use_same_physical_actor():
    reader = decision_rules.Reader(
        "owner_ai", "is_ai", "root", "boolean", "boolean", path=("owner",)
    )
    policy = decision_rules.RuleSet(
        readers=(reader,),
        rules=(),
        baseline_sha256="0" * 64,
        source_sha256="0" * 64,
        enabled_domains=frozenset(),
        actor_path=("owner",),
        native_root="military_formation",
    )
    facts = _facts(policy, {"owner_ai": None}, is_ai=True)
    assert cast("Any", facts["ROOT"])["owner"]["is_ai"] is None
    assert (
        cast("Any", _facts(policy, {"owner_ai": True}, is_ai=False)["ROOT"])["owner"]["is_ai"]
        is False
    )


def _facts(
    policy: decision_rules.RuleSet,
    values: Mapping[str, object],
    *,
    is_ai: bool,
    reader_index: _ReaderIndex | None = None,
) -> dict[str, object]:
    root: dict[str, Any] = (
        {**values.root_facts, **values.collections} if isinstance(values, _ObservedValues) else {}
    )
    contexts: dict[str, dict[str, Any]] = {}
    readers = (reader_index or _ReaderIndex.build(policy)).readers
    for key, value in values.items():
        reader = readers[key]
        if reader.engine in _COLLECTIONS:
            assert isinstance(values, _ObservedValues), (
                "query observations require real owned members"
            )
            continue
        current = (
            root if reader.scope == "root" else contexts.setdefault(f"scope:{reader.scope}", {})
        )
        for part in reader.path:
            current = current.setdefault(part, {})
        if reader.engine == "is_production_method_active":
            parameters = dict(reader.parameters)
            current.setdefault(reader.engine, {}).setdefault(parameters["building_type"], {})[
                parameters["production_method"]
            ] = value
        elif reader.engine == "has_variable" and (reader.argument or "").startswith("sitai_route_"):
            current[f"{reader.argument}_active"] = value
        elif reader.argument is not None or reader.parameters or reader.value_field:
            identity = tuple(
                sorted(
                    {
                        **dict(reader.parameters),
                        **({"argument": reader.argument} if reader.argument is not None else {}),
                    }.items()
                )
            )
            current.setdefault(reader.engine, {})[identity] = value
        # Multiple source aliases may lower to the same PDX trigger (for
        # example own_navy and navy). Preserve uncertainty if a fixture
        # makes those aliases disagree instead of letting iteration order
        # silently choose one observation.
        elif reader.engine in current and current[reader.engine] != value:
            current[reader.engine] = None
        else:
            current[reader.engine] = value
        if reader.engine.startswith("sitai_context_"):
            current[reader.engine.replace("sitai_context_", "sitai_context_known_", 1)] = (
                value is not None
            )
    actor = root.setdefault("owner", {}) if policy.actor_path else root
    observed_ai = [
        values[reader.key]
        for reader in readers.values()
        if reader.engine == "is_ai"
        and reader.scope == "root"
        and reader.path == policy.actor_path
        and reader.key in values
    ]
    # A required-known is_ai reader and the player guard inspect the same
    # physical actor. Do not overwrite a missing observation with a known AI.
    actor["is_ai"] = observed_ai[0] if is_ai and observed_ai else is_ai
    return {"ROOT": root, **contexts}


def _cases(
    policy: decision_rules.RuleSet,
    rule: decision_rules.Rule,
    reader_index: _ReaderIndex | None = None,
):
    index = reader_index or _ReaderIndex.build(policy)
    positive, candidates = policy_audit._fixture(policy, rule)
    requested = index.normalize(positive)
    for reader in index.readers.values():
        if (
            reader.engine == "is_ai"
            and reader.scope == "root"
            and reader.path == policy.actor_path
            and reader.key in requested
        ):
            requested = index.change(requested, reader.key, True)
    positive = _observed_values(index, requested)
    assert _truth(rule, positive, index) is True, f"incoherent positive fixture: {rule.id}"
    yield "positive", positive, True
    yield "player", positive, False
    # Every declared input gets its own missing-observation witness. Checking
    # only the first key hid errors in later or parameterized readers.
    for key in requested:
        changed = _observed_values(index, index.change(requested, key, None))
        assert changed[key] is None
        assert _truth(rule, changed, index) is None
        yield f"unknown:{key}", changed, True
    negatives = [
        (key, value)
        for key, choices in candidates.items()
        for value in choices
        if _truth(rule, _observed_values(index, index.change(requested, key, value)), index)
        is False
    ]
    assert negatives, f"no independent negative fixture: {rule.id}"
    seen: set[str] = set()
    for key, value in negatives:
        if key not in seen:
            seen.add(key)
            yield (
                f"negative:{key}",
                _observed_values(index, index.change(requested, key, value)),
                True,
            )
    for predicate in rule.conditions:
        if type(predicate.value) in (int, float):
            numeric = float(cast("float", predicate.value))
            if not math.isfinite(numeric):
                continue
            for value in (
                numeric,
                math.nextafter(numeric, -math.inf),
                math.nextafter(numeric, math.inf),
            ):
                yield (
                    f"threshold:{predicate.fact}:{value}",
                    _observed_values(index, index.change(requested, predicate.fact, value)),
                    True,
                )


@pytest.mark.integration
def test_every_legacy_writer_has_generated_ast_semantics(generated):
    policies, model, files, info_text, _inputs, _baseline = generated
    assert model.consumer_ir is not None
    index = {source: _blocks(text) for source, text in files.items()}
    index[INFO] = _blocks(info_text)
    witnessed: set[tuple[str, str]] = set()
    counts: Counter[str] = Counter()
    for source, policy in policies:
        reader_index = _ReaderIndex.build(policy)
        for rule in policy.rules:
            identity = (source, rule.id)
            assert identity not in witnessed
            witnessed.add(identity)
            output = (
                INFO
                if source == INFO
                else action_instances._output_source(source, ".".join(rule.field))
            )
            branch, parsed_chain, marked = index[output][rule.id]
            limit = branch.first("limit")
            assert limit is not None, identity
            assert isinstance(limit.value, Block), identity
            write = branch.first("add")
            assert write is not None, identity
            if isinstance(write.value, Block):
                literal = write.value.first("value")
            else:
                literal = write
            assert literal is not None, identity
            assert not isinstance(literal.value, Block), identity
            assert literal.value is not None, identity
            neutral = 1.0 if rule.operation == "multiply" else 0.0
            assert float(literal.value.unquoted) == pytest.approx(rule.value - neutral), identity
            for case, values, is_ai in _cases(policy, rule, reader_index):
                counts[case.split(":", 1)[0]] += 1
                expected = _truth(rule, values, reader_index) if is_ai else False
                engine_facts = _facts(policy, values, is_ai=is_ai, reader_index=reader_index)
                try:
                    actual = pdx_eval.condition(limit.value, engine_facts)
                except pdx_eval.UnsupportedPdxError as exc:
                    raise AssertionError(
                        f"{source}:{rule.id}/{case}: unsupported PDX oracle primitive: {exc}"
                    ) from exc
                if expected is None:
                    assert actual is not True, f"{source}:{rule.id}/{case}: unknown selected"
                else:
                    assert actual is expected, (
                        f"{source}:{rule.id}/{case}: expected {expected}, got {actual}"
                    )
                selected = parsed_chain.select(engine_facts)
                if case in {"positive", "player"}:
                    assert selected == pdx_eval.select(
                        marked, engine_facts, path=f"{output}:{rule.id}"
                    )
                if expected is True:
                    assert (selected.action_id, selected.operation, selected.delta) == (
                        rule.id,
                        "add",
                        pytest.approx(rule.value - neutral),
                    ), f"{source}:{rule.id}/{case}: {selected}"
                elif expected is False:
                    neutral_noop = selected.operation == "multiply" and selected.delta == 1.0
                    assert (
                        selected.action_id != rule.id
                        or neutral_noop
                        or selected.fallback == "vanilla"
                    ), f"{source}:{rule.id}/{case}: false condition applied writer {selected}"
                else:
                    neutral_noop = selected.operation == "multiply" and selected.delta == 1.0
                    assert selected.fallback in {"unknown", "vanilla"} or neutral_noop, (
                        f"{source}:{rule.id}/{case}: unknown condition applied writer {selected}"
                    )
    assert len(witnessed) == sum(len(policy.rules) for _, policy in policies)
    assert counts["positive"] == counts["player"] == len(witnessed)
    assert counts["unknown"] >= len(witnessed)
    assert counts["negative"] >= len(witnessed)
    print("writer_oracle_isolated", dict(counts))


def _consumer_overlay(text: str, field: str) -> str:
    """Keep the entire production priority chain, including unknown guards."""
    begin = text.index(f"# SITAI BEGIN information:{field}")
    end = text.index(f"# SITAI END information:{field}", begin)
    return "\n".join(text[begin:end].splitlines()[1:])


@dataclass(frozen=True)
class _ParsedProgram:
    identity: str
    limit: Block
    effect: Assignment

    @classmethod
    def build(cls, text: str):
        parsed = parse_text(text)
        assert not parsed.errors, parsed.errors
        branches = _ordinary_assignments(parsed.root)
        assert len(branches) == 1
        branch = branches[0]
        assert branch.key == "if"
        assert isinstance(branch.value, Block)
        limit, effect = _ordinary_assignments(branch.value)
        assert limit.key == "limit"
        assert isinstance(limit.value, Block)
        assert effect.key in {"add", "multiply"}
        assert isinstance(effect.value, Block)
        marker = re.search(r"# ACTION (program_[0-9a-f]+) ", text)
        assert marker is not None
        return cls(marker.group(1), limit.value, effect)

    def select(self, facts):
        state = pdx_eval.condition(self.limit, facts)
        if state is None:
            return pdx_eval.PdxDecision(self.identity, None, 0.0, "unknown")
        if state is not True:
            return pdx_eval.PdxDecision(None, None, 0.0, "vanilla")
        # Actual numeric AST interpreter; no source rule, grouping or production
        # reference selector participates in this evaluation.
        value = pdx_eval._numeric_value(self.effect, facts)
        if value is None:
            return pdx_eval.PdxDecision(self.identity, None, 0.0, "unknown")
        return pdx_eval.PdxDecision(self.identity, self.effect.key, value, "selected")


def _independent_net(rules, values, reader_index, selected):
    """Source-level oracle: strongest known tier per declared cause/direction."""
    operation = rules[0].operation
    neutral = 1.0 if operation == "multiply" else 0.0
    envelopes = defaultdict(list)
    for rule in rules:
        envelopes[(rule.contribution_group, rule.value >= neutral)].append(rule)
    lower = neutral + sum(
        min(0.0, *(r.value - neutral for r in group)) for group in envelopes.values()
    )
    upper = neutral + sum(
        max(0.0, *(r.value - neutral for r in group)) for group in envelopes.values()
    )
    lower, upper = (
        (max(0.5, lower), min(1.5, upper)) if neutral else (max(-50, lower), min(50, upper))
    )
    net = neutral
    for (_cause, positive), group in sorted(envelopes.items()):
        matches = [
            rule.value - neutral
            for rule in group
            if rule.domain in selected and _truth(rule, values, reader_index) is True
        ]
        if matches:
            net += max(matches) if positive else min(matches)
    return operation, max(lower, min(upper, net))


@pytest.mark.integration
def test_complete_consumer_priority_matches_independent_oracle(generated):
    """Every writer's states exercise the complete bounded consumer program."""
    policies, _model, files, info_text, _inputs, _baseline = generated
    counts: Counter[str] = Counter()
    fields_checked = 0
    for source, policy in policies:
        reader_index = _ReaderIndex.build(policy)
        fields = defaultdict(list)
        for rule in policy.rules:
            if rule.domain in policy.enabled_domains:
                fields[rule.field].append(rule)
        for field, rules in fields.items():
            output = (
                INFO if source == INFO else action_instances._output_source(source, ".".join(field))
            )
            text = info_text if source == INFO else files[output]
            overlay = _consumer_overlay(text, ".".join(field))
            actual_program = _ParsedProgram.build(overlay)
            fields_checked += 1
            compared_text_states = set()
            for target in rules:
                target_cases: Counter[str] = Counter()
                for case, values, is_ai in _cases(policy, target, reader_index):
                    kind = case.split(":", 1)[0]
                    target_cases[kind] += 1
                    counts[kind] += 1
                    engine = _facts(policy, values, is_ai=is_ai, reader_index=reader_index)
                    actual = actual_program.select(engine)
                    state = (is_ai, actual.operation, actual.delta)
                    if state not in compared_text_states:
                        assert actual == pdx_eval.select(overlay, engine)
                        compared_text_states.add(state)
                    identity = (source, field, target.id, case)
                    if not is_ai:
                        assert actual == pdx_eval.PdxDecision(None, None, 0.0, "vanilla"), identity
                        continue
                    actor_ai = next(
                        (
                            values[reader.key]
                            for reader in reader_index.readers.values()
                            if reader.engine == "is_ai"
                            and reader.scope == "root"
                            and reader.path == policy.actor_path
                            and reader.key in values
                        ),
                        True,
                    )
                    if actor_ai is None:
                        assert actual == pdx_eval.PdxDecision(
                            actual_program.identity, None, 0.0, "unknown"
                        ), identity
                        counts["local_unknown"] += 1
                        continue
                    operation, expected = _independent_net(
                        rules, values, reader_index, policy.enabled_domains
                    )
                    assert actual.action_id == actual_program.identity, identity
                    assert actual.operation == operation, identity
                    assert actual.delta == pytest.approx(expected), (identity, expected, actual)
                    counts["local_unknown" if kind == "unknown" else "known_state"] += 1
                assert target_cases["positive"] == target_cases["player"] == 1
                assert target_cases["unknown"] >= len(target.input_keys())
                assert target_cases["negative"] >= 1
                numeric = sum(type(p.value) in (int, float) for p in target.conditions)
                assert target_cases["threshold"] == numeric * 3
    expected_count = sum(len(policy.rules) for _, policy in policies)
    assert counts["positive"] == counts["player"] == expected_count
    assert counts["local_unknown"] > 0
    assert counts["known_state"] > 0
    assert fields_checked > 0
    print("writer_oracle_complete", {"fields": fields_checked, **dict(counts)})
