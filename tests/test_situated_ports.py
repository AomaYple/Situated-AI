"""Typed ports lower actual reader predicates and preserve unknown/entity identity."""

from __future__ import annotations

import copy
import tomllib
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from pdx import decision_adapters, decision_rules
from pdx.parser import parse_text
from pdx.situated import decision_ir, pdx_eval

ROOT = Path(__file__).resolve().parents[1]
INFO = "mod/decisions/information.toml"
CARD = "mod/decisions/actions.toml"
SOURCE = ROOT / "mod/decisions/domain_ports.toml"


def _ports():
    from pdx.situated import ports

    return ports


def _context() -> decision_ir.EvaluationContext:
    actor = decision_ir.ContextBinding("root", "country", "actor", "fixture/native.txt", 1)
    return decision_ir.EvaluationContext(actor, evidence=("fixture/native.txt:1",))


def _fixture():
    reader = decision_rules.Reader(
        "literacy", "literacy_rate", "root", "ratio", "number", minimum=0, maximum=1
    )
    signature = asdict(reader)
    signature.pop("key")
    signature["path"] = []
    signature["parameters"] = []
    signature = {key: value for key, value in signature.items() if value is not None}
    data = {
        "schema": 1,
        "limits": {"nodes": 32, "depth": 8, "expanded_leaves": 32, "evaluation_cost": 128},
        "ports": {
            "low": {
                "domain": "education",
                "entity": "root",
                "entity_kind": "country",
                "unit": "flag",
                "direction": "need",
                "refresh": "consumer",
                "unknown": "vanilla",
                "cost": 1,
                "reader_source": INFO,
                "reader_key": "literacy",
                "reader": signature,
                "op": "<",
                "value": 0.5,
            },
        },
        "uses": [{"source": INFO, "definition": "school", "port": "low", "role": "need"}],
    }
    return data, {(INFO, "literacy"): reader}, {(INFO, "school"): _context()}


def _load(data=None, readers=None, writers=None):
    if data is None:
        data, readers, writers = _fixture()
    return _ports().from_data(data, readers=readers, writers=writers)


@pytest.mark.parametrize(
    ("raw", "expected"), [(0.4, True), (0.5, False), (None, None), (-1, None), (True, None)]
)
def test_port_threshold_matches_manual_and_generated_pdx(raw, expected) -> None:
    graph = _load()
    assert graph.evaluate("low", {(INFO, "literacy"): raw}) is expected
    guard = graph.guard(INFO, "school", "low")
    block = parse_text(guard.when_true).root
    # Out-of-domain numeric input is unknown to the reference; production
    # bounds disprove both known branches rather than detecting unknown.
    lowered_expected = False if raw == -1 and type(raw) is int else expected
    assert pdx_eval.condition(block, {"literacy_rate": raw}) is lowered_expected


def test_caller_cannot_forge_derived_alias_or_source_value() -> None:
    graph = _load()
    assert graph.evaluate("low", {"low": True, "literacy": 0.2}) is None


def test_aliases_keep_same_raw_origin_and_diamond_is_bounded() -> None:
    data, readers, writers = _fixture()
    data["ports"]["alias"] = copy.deepcopy(data["ports"]["low"])
    data["ports"]["both"] = {
        "domain": "education",
        "entity": "root",
        "entity_kind": "country",
        "unit": "flag",
        "direction": "need",
        "refresh": "consumer",
        "unknown": "vanilla",
        "cost": 1,
        "all": ["low", "alias"],
    }
    data["uses"][0]["port"] = "both"
    graph = _load(data, readers, writers)
    assert len(graph.origins("both")) == 1
    assert graph.evaluate("both", {(INFO, "literacy"): 0.3}) is True
    assert graph.expanded_leaves("both") == 2


@pytest.mark.parametrize("mutation", ["unit", "path", "parameters", "argument", "value_field"])
def test_reader_signature_drift_is_rejected(mutation: str) -> None:
    data, readers, writers = _fixture()
    changes = {
        "unit": "money",
        "path": ["owner"],
        "parameters": [["type", "law"]],
        "argument": "fake",
        "value_field": "value",
    }
    data["ports"]["low"]["reader"][mutation] = changes[mutation]
    with pytest.raises(ValueError, match="signature"):
        _load(data, readers, writers)


def test_wrong_entity_context_is_rejected() -> None:
    data, readers, writers = _fixture()
    data["ports"]["low"]["entity_kind"] = "state"
    with pytest.raises(ValueError, match="实体"):
        _load(data, readers, writers)


def test_dead_use_and_unused_port_are_rejected() -> None:
    data, readers, writers = _fixture()
    with pytest.raises(ValueError, match="writer"):
        _load(data, readers, {})
    data["ports"]["unused"] = copy.deepcopy(data["ports"]["low"])
    with pytest.raises(ValueError, match="未使用"):
        _load(data, readers, writers)


def test_cycle_and_expansion_overflow_are_rejected() -> None:
    data, readers, writers = _fixture()
    data["ports"]["cycle"] = {
        key: value
        for key, value in data["ports"]["low"].items()
        if key
        in {"domain", "entity", "entity_kind", "unit", "direction", "refresh", "unknown", "cost"}
    }
    data["ports"]["cycle"]["not"] = "cycle"
    data["uses"][0]["port"] = "cycle"
    with pytest.raises(ValueError, match="环"):
        _load(data, readers, writers)


def test_cost_budget_and_numeric_unit_cannot_be_bypassed() -> None:
    data, readers, writers = _fixture()
    data["ports"]["low"]["cost"] = 129
    with pytest.raises(ValueError, match="预算"):
        _load(data, readers, writers)
    data, readers, writers = _fixture()
    data["ports"]["low"]["unit"] = "money"
    with pytest.raises(ValueError, match="单位"):
        _load(data, readers, writers)


def test_budget_declaration_itself_is_bounded_before_recursion() -> None:
    data, readers, writers = _fixture()
    data["limits"]["depth"] = 10000
    with pytest.raises(ValueError, match="预算"):
        _load(data, readers, writers)


def test_scoped_parameter_reader_uses_actual_reader_lowering() -> None:
    data, readers, writers = _fixture()
    reader = decision_rules.Reader(
        "literacy", "has_law", "root", "boolean", "boolean", argument="law_public_schools"
    )
    readers[(INFO, "literacy")] = reader
    data["ports"]["low"].update(reader=_ports().reader_signature(reader), op="=", value=True)
    graph = _load(data, readers, writers)
    assert graph.evaluate("low", {(INFO, "literacy"): True}) is True
    guard = graph.guard(INFO, "school", "low")
    assert "has_law = law_public_schools" in guard.when_true
    assert "literacy_rate" not in guard.when_true


def test_nonroot_target_and_boolean_not_keep_unknown_local() -> None:
    data, readers, writers = _fixture()
    target = replace(readers[(INFO, "literacy")], scope="target_country")
    readers[(INFO, "literacy")] = target
    data["ports"]["low"].update(entity="target_country", reader=_ports().reader_signature(target))
    data["ports"]["not_low"] = {
        key: value
        for key, value in data["ports"]["low"].items()
        if key
        in {"domain", "entity", "entity_kind", "unit", "direction", "refresh", "unknown", "cost"}
    }
    data["ports"]["not_low"]["not"] = "low"
    data["uses"][0]["port"] = "not_low"
    context = _context()
    binding = decision_ir.ContextBinding(
        "target_country", "country", "target", "fixture/native.txt", 2
    )
    writers[(INFO, "school")] = replace(
        context, targets=(binding,), evidence=(*context.evidence, "fixture/native.txt:2")
    )
    graph = _load(data, readers, writers)
    assert graph.evaluate("not_low", {(INFO, "literacy"): None}) is None
    expression = graph.guard(INFO, "school", "not_low").when_true
    assert (
        pdx_eval.condition(
            parse_text(expression).root,
            {"scope:target_country": {"literacy_rate": 0.8}, "literacy_rate": 0.2},
        )
        is True
    )
    assert (
        pdx_eval.condition(
            parse_text(expression).root,
            {"scope:target_country": {"literacy_rate": None}, "literacy_rate": 0.8},
        )
        is None
    )
    data, readers, writers = _fixture()
    data["limits"]["expanded_leaves"] = 0
    with pytest.raises(ValueError, match="预算"):
        _load(data, readers, writers)


def test_real_school_construction_and_card_uses_reference_actual_readers() -> None:
    assert SOURCE.is_file(), "缺少真实领域端口源"
    data = tomllib.loads(SOURCE.read_text(encoding="utf-8"))
    policy = decision_rules.load()
    readers = {(INFO, reader.key): reader for reader in policy.readers}
    readers.update(
        {
            (source, reader.key): reader
            for source, adapter in decision_adapters.load().policies
            for reader in adapter.readers
        }
    )
    rules = {rule.id for rule in policy.rules}
    cards = tomllib.loads((ROOT / CARD).read_text(encoding="utf-8"))["actions"]
    for use in data["uses"]:
        assert use["definition"] in (rules if use["source"] == INFO else cards)
    writers = {(use["source"], use["definition"]): _context() for use in data["uses"]}
    graph = _load(data, readers, writers)
    assert (
        graph.evaluate("school_need", {(INFO, "literacy"): 0.2, (INFO, "population"): 100}) is True
    )
    assert (
        graph.evaluate("financing_ready", {(INFO, "default"): False, (INFO, "net_surplus"): None})
        is None
    )
    assert (
        graph.evaluate(
            "financing_pressure",
            {(INFO, "debt_ratio"): 0.5, (INFO, "net_surplus"): -1, (INFO, "bureaucracy"): -2},
        )
        is True
    )
