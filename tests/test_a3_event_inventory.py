"""Event denominator discovery does not infer optional-slot defaults or scopes."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from pdx import config
from pdx.parser import parse_bytes, parse_text
from pdx.situated import vanilla_inventory as inventory

pytestmark = pytest.mark.unit


def _write(root, path, text):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")


def test_all_mounted_events_including_files_without_ai_are_selected(tmp_path):
    _write(tmp_path, "common/laws/a.txt", "law = { ai_weight = 1 }")
    _write(
        tmp_path,
        "common/static_modifiers/context.txt",
        "heard = { interest_group_approval_add = 2 }",
    )
    _write(tmp_path, "events/deep/no_ai.txt", "x.1 = { option = { name = x.a } }")
    _write(tmp_path, "in_game/events/a.txt", "x.2 = { option = { name = x.b } }")
    _write(tmp_path, "dlc/a.dlc", 'path = "dlc/mounted"')
    _write(tmp_path, "dlc/mounted/events/a.txt", "x.3 = { option = { name = x.c } }")
    _write(tmp_path, "dlc/unmounted/events/a.txt", "unmounted = {}")
    inputs, directories, roots = inventory._inputs(tmp_path)
    assert "events/deep/no_ai.txt" in inputs
    assert "in_game/events/a.txt" in inputs
    assert "dlc/mounted/events/a.txt" in inputs
    assert "dlc/unmounted/events/a.txt" not in inputs
    assert "common/static_modifiers/context.txt" in inputs
    assert {"events", "in_game/events", "dlc/mounted/events"} <= set(roots)
    assert {"events", "in_game/events", "dlc/mounted/events"} <= set(directories)


def test_names_identity_and_default_flags_do_not_authorize_undeclared_weights():
    event = parse_text(
        "ai_event.1 = { type = country_event placement = ROOT "
        "option = { name = x.a default_option = yes ai_chance = { base = 50 } } "
        "option = { name = x.b } immediate = { ai_effect = yes } }"
    ).top_assignments[0]
    options, surfaces = inventory._event_candidates("events/x.txt", event)
    assert [row.field for row in options] == ["option[x.a].ai_chance", "option[x.b].ai_chance"]
    assert [row.operation for row in surfaces] == [
        "event_option_weight",
        "undeclared_event_option_weight",
    ]
    assert options[0].default_option == "yes"
    assert options[1].default_option is None
    assert all(not row.legal and row.actor_scope == "unknown" for row in surfaces)
    assert len(surfaces) == 2  # Neither ai_event.1 nor ai_effect is an option weight.


def test_dynamic_duplicate_names_and_duplicate_weights_stay_ambiguous():
    event = parse_text(
        "x = { option = { name = duplicate } option = { name = duplicate } "
        "option = { name = { first_valid = {} } } "
        "option = { name = x.d ai_chance = { base = 1 } ai_chance = { base = 2 } } }"
    ).top_assignments[0]
    options, rows = inventory._event_candidates("events/x.txt", event)
    assert [row.field for row in options[:3]] == [f"option[#{i}].ai_chance" for i in (1, 2, 3)]
    assert all(row.ambiguity for row in options)
    assert len(rows) == 5
    assert len(options[-1].weight_lines) == 2


def test_installed_event_denominator_matches_independent_full_ast_counts():
    if not config.GAME.is_dir():
        pytest.skip("requires locked installed native event files")
    records: list[inventory.VanillaEventOption] = []
    paths = sorted((config.GAME / "events").rglob("*.txt"))
    for path in paths:
        parsed = parse_bytes(path.read_bytes(), path=path.as_posix())
        assert not parsed.errors
        for event in parsed.top_assignments:
            options, _ = inventory._event_candidates(
                path.relative_to(config.GAME).as_posix(), event
            )
            records.extend(options)
    assert len(paths) == 328
    assert len(records) == 4840
    assert sum(len(row.weight_lines) for row in records) == 723
    assert sum(1 for row in records if not row.weight_lines) == 4117
    assert len({(r.source, r.definition, r.option_index) for r in records}) == 4840
    plague = [asdict(row) for row in records if row.definition == "plague.5"]
    assert len(plague) == 3
    assert all(not row["weight_lines"] for row in plague)
    assert [row["option_name"] for row in plague if row["default_option"] == "yes"] == [
        "plague.5.b"
    ]
