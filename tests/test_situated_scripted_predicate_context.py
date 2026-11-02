"""The explicit boolean template keeps its exact native scripted-trigger identity."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any

import pytest

from pdx import decision_adapters, decision_interfaces, decision_rules
from pdx.situated import actions, compiler, decision_ir, evidence, relations, support_signals

pytestmark = pytest.mark.unit
_DEFINITION = "any_insurrection_ongoing = { any_political_movement = { is_insurrectionary = yes } }"


@pytest.fixture
def scripted_source(tmp_path, monkeypatch):
    data = json.loads(decision_interfaces.scripted_trigger_snapshot())
    source = data["reader"]["source"]
    game = tmp_path / "game"
    path = game / source
    path.parent.mkdir(parents=True)
    path.write_text(_DEFINITION, encoding="utf-8")
    data["sources"] = {source: hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest = tmp_path / "predicate.json"

    def freeze():
        raw = json.dumps(data).encode()
        manifest.write_bytes(raw)
        monkeypatch.setattr(decision_interfaces, "SCRIPTED_PREDICATE_SOURCE", manifest)
        monkeypatch.setattr(
            decision_interfaces, "SCRIPTED_PREDICATE_SHA256", hashlib.sha256(raw).hexdigest()
        )

    freeze()
    return game, path, data, freeze


def test_production_requires_current_script_source_not_snapshot_only(scripted_source):
    game, path, data, _ = scripted_source
    assert decision_interfaces.verify_scripted_trigger_game(game) == tuple(data["sources"].items())
    path.write_text(_DEFINITION + "\n# drift", encoding="utf-8")
    with pytest.raises(ValueError, match="来源SHA"):
        decision_interfaces.verify_scripted_trigger_game(game)
    path.unlink()
    with pytest.raises(ValueError, match="来源集合"):
        decision_interfaces.verify_scripted_trigger_game(game)


@pytest.mark.parametrize(
    "damage", ["leaf", "scope", "duplicate", "prefix", "argument", "quoted", "extra"]
)
def test_repin_cannot_replace_scripted_trigger_ast_or_unique_identity(scripted_source, damage):
    game, path, data, freeze = scripted_source
    content = {
        "leaf": _DEFINITION.replace("is_insurrectionary", "is_secessionist"),
        "scope": _DEFINITION.replace("any_political_movement", "any_country"),
        "duplicate": _DEFINITION + "\n" + _DEFINITION,
        "prefix": _DEFINITION.replace("is_insurrectionary =", "is_insurrectionary ?="),
        "argument": "any_insurrection_ongoing = yes",
        "quoted": _DEFINITION.replace("= yes", '= "yes"'),
        "extra": _DEFINITION.replace(
            "is_insurrectionary = yes", "is_insurrectionary = yes always = yes"
        ),
    }[damage]
    path.write_text(content, encoding="utf-8")
    data["sources"][data["reader"]["source"]] = hashlib.sha256(path.read_bytes()).hexdigest()
    freeze()
    with pytest.raises(ValueError, match="精确AST"):
        decision_interfaces.verify_scripted_trigger_game(game)


@pytest.mark.parametrize(
    "damage",
    [
        "scope",
        "kind",
        "unit",
        "path",
        "argument",
        "parameters",
        "value_field",
        "minimum",
        "maximum",
        "actor",
    ],
)
def test_scripted_reader_keeps_exact_country_boolean_signature(damage):
    reader = decision_rules.Reader(
        "ongoing", "any_insurrection_ongoing", "root", "boolean", "boolean"
    )
    assert decision_interfaces.reader_scope(reader, ()) == "country"
    changes: dict[str, dict[str, Any]] = {
        "scope": {"scope": "target_country"},
        "kind": {"kind": "number"},
        "unit": {"unit": "flag"},
        "path": {"path": ("owner",)},
        "argument": {"argument": "yes"},
        "parameters": {"parameters": (("who", "root"),)},
        "value_field": {"value_field": "value"},
        "minimum": {"minimum": 0},
        "maximum": {"maximum": 1},
        "actor": {},
    }
    with pytest.raises(ValueError, match="精确国家ROOT"):
        decision_interfaces.reader_scope(
            replace(reader, **changes[damage]), ("owner",) if damage == "actor" else ()
        )


def test_industrial_card_uses_real_scripted_trigger_template_not_ig_getter(monkeypatch):
    declared = evidence.load(compiler.FACTS)
    consumers, cards = actions.load(compiler.ACTIONS)
    sources = compiler._load_supporting_sources()
    signals = support_signals.load(
        sources,
        compiler._reader_facts(declared),
        cards,
        reader_shapes=compiler._reader_shapes(declared),
    )
    links = relations.relations(cards, sources["relations.toml"].get("relations", []))
    row = next(
        item
        for item in decision_ir.compile_decisions(cards, consumers, links)
        if item.action_id == "industrial_foundation"
    )
    readers = (
        *decision_rules.load().readers,
        *(reader for _, policy in decision_adapters.load().policies for reader in policy.readers),
    )
    seen = []
    original = decision_interfaces.reader_scope

    def capture(reader, actor_path):
        if reader.key == "no_insurrection":
            seen.append(reader)
        return original(reader, actor_path)

    monkeypatch.setattr(decision_interfaces, "reader_scope", capture)
    bindings = compiler._action_context_readers(
        row, compiler._frozen_strategy_contexts()[row.field], declared, signals, readers
    )
    assert ("no_insurrection", "root", "country", "actor") in bindings
    assert seen
    assert {reader.engine for reader in seen} == {"any_insurrection_ongoing"}
    assert all(
        reader.kind == "boolean" and not reader.path and reader.argument is None for reader in seen
    )
    damaged = tuple(
        replace(item, trigger="any_insurrection_ongoing = 0")
        if item.id == "no_insurrection"
        else item
        for item in declared
    )
    with pytest.raises(ValueError, match="读取器"):
        compiler._action_context_readers(
            row, compiler._frozen_strategy_contexts()[row.field], damaged, signals, readers
        )
