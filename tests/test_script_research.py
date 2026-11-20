"""脚本研究索引保留类型、位置和不确定性。"""

from __future__ import annotations

from dataclasses import fields

import pytest

from pdx.parser import parse_bytes, parse_text
from pdx.script_research import ScriptReference, definition_kind, iter_definitions, iter_references

_DIGEST = "a" * 64


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        ("game/common/scripted_triggers/sample.txt", "scripted_trigger"),
        ("jomini/common/scripted_values/nested/sample.txt", "script_value"),
        ("clausewitz/common/script_values/sample.txt", "script_value"),
        ("game/common/scripted_effects/sample.txt", "scripted_effect"),
        ("game/common/scripted_modifiers/sample.txt", "scripted_modifier"),
        ("game/common/static_modifiers/sample.txt", "static_modifier"),
        ("game/common/modifier_type_definitions/sample.txt", "modifier_type"),
        ("game/common/opinion_modifiers/sample.txt", "opinion_modifier"),
        ("game/common/scripted_triggers/README.md", None),
        ("game/gfx/common/scripted_triggers/sample.txt", None),
        ("other/common/scripted_triggers/sample.txt", None),
    ],
)
def test_definition_directory_and_file_kind(source: str, kind: str | None) -> None:
    assert definition_kind(source) == kind


def test_definitions_keep_repeated_names_addresses_and_parser_status() -> None:
    path = "game/common/script_values/sample.txt"
    parsed = parse_text("@private = 3\n{ ignored = 4 }\nknown = 5\nREPLACE:known = { value = 2 }\n")
    actual = list(iter_definitions(path, _DIGEST, parsed))
    assert [(row.name, row.address, row.path, row.line) for row in actual] == [
        ("known", (2,), ("known",), 3),
        ("known", (3,), ("REPLACE:known",), 4),
    ]
    assert {(row.source, row.source_sha256, row.parse_status, row.kind) for row in actual} == {
        (path, _DIGEST, "complete", "script_value")
    }
    modifiers = list(
        iter_definitions(
            "game/common/static_modifiers/test.txt",
            _DIGEST,
            parse_text("1836_buff = {}\nnot_a_block = yes"),
        )
    )
    assert [row.name for row in modifiers] == ["1836_buff"]
    malformed = parse_text("known = { value = 2")
    assert [row.parse_status for row in iter_definitions(path, _DIGEST, malformed)] == ["partial"]
    untrusted = parse_bytes(b"known = 3\n# \xff", path, encoding="utf-8-sig")
    assert untrusted.parse_status == "failed"
    assert list(iter_definitions(path, _DIGEST, untrusted)) == []


def test_key_calls_use_role_not_name_collisions_and_preserve_ast_addresses() -> None:
    path = "game/common/decisions/test.txt"
    parsed = parse_text(
        "decision = {\n"
        " is_shown = { check = yes { root.check = yes } }\n"
        " possible = { unregistered_scripted_trigger = yes }\n"
        " when_taken = { check = { check = yes } limit = { check = yes } $CALL$ = yes }\n"
        " unrelated = { check = yes }\n"
        " label = check\n"
        "}\n"
    )
    names = {"check": {"scripted_trigger": 2, "scripted_effect": 1, "script_value": 3}}
    rows = list(iter_references(path, _DIGEST, parsed, names))
    assert [(row.name, row.requested_kind, row.status, row.address) for row in rows] == [
        ("check", "scripted_trigger", "ambiguous", (0, 0, 0)),
        ("check", "scripted_trigger", "ambiguous", (0, 0, 1, 0)),
        ("unregistered_scripted_trigger", "scripted_trigger", "unknown", (0, 1, 0)),
        ("check", "scripted_effect", "candidate", (0, 2, 0)),
        ("check", "scripted_trigger", "ambiguous", (0, 2, 1, 0)),
        (None, "scripted_effect", "dynamic", (0, 2, 2)),
    ]
    assert rows[1].path == ("decision", "is_shown", "[]", "root.check")
    assert rows[1].line == 2
    assert {(row.source, row.source_sha256, row.parse_status) for row in rows} == {
        (path, _DIGEST, "complete")
    }


def test_numeric_and_explicit_uses_keep_only_identifiers_and_source_position() -> None:
    path = "game/common/script_values/test.txt"
    parsed = parse_text(
        "example = {\n value =\n scope:owner.reference\n add = root.engine_getter\n"
        " base = scripted_value:missing\n subtract = @local_constant\n"
        ' multiply = scope:owner.var:token\n min = "script_value:reference"\n'
        " max = /asset/path/reference\n score = 2.1E-3\n trigger = { scripted_trigger = $CHECK$ }\n"
        ' round_to = reference\n hidden = "/private/script_value:do_not_store"\n'
        " add = access_$(private_expr)\n { scripted_effect:absent }\n}\n"
    )
    rows = list(iter_references(path, _DIGEST, parsed, {"reference": {"script_value": 1}}))
    assert [(row.name, row.requested_kind, row.status, row.line) for row in rows] == [
        ("reference", "script_value", "candidate", 3),
        ("engine_getter", "script_value", "unknown", 4),
        ("missing", "script_value", "missing", 5),
        (None, "script_value", "dynamic", 6),
        (None, "script_value", "dynamic", 7),
        ("reference", "script_value", "observational", 8),
        (None, "scripted_trigger", "dynamic", 11),
        ("reference", "script_value", "candidate", 12),
        ("absent", "scripted_effect", "missing", 15),
    ]
    assert rows[-1].path == ("example", "[]")
    assert rows[-1].address[:1] == (0,)
    assert not {"expression", "scalar", "raw"} & {field.name for field in fields(ScriptReference)}


def test_modifier_accessors_entries_and_effect_arguments_use_distinct_types() -> None:
    names = {
        "shared": {"static_modifier": 1, "modifier_type": 2},
        "named_months": {"script_value": 1},
    }
    event = "game/events/test.txt"
    parsed = parse_text(
        "event = {\n trigger = { has_modifier = shared }\n"
        " option = { add_modifier = { name = shared days = named_months }\n"
        " remove_modifier = absent add_modifier = $MODIFIER$ }\n"
        " score = owner.modifier:shared\n name = shared\n}\n"
    )
    rows = list(iter_references(event, _DIGEST, parsed, names))
    assert [(row.name, row.requested_kind, row.status) for row in rows] == [
        ("shared", "static_modifier", "candidate"),
        ("shared", "static_modifier", "candidate"),
        ("named_months", "script_value", "candidate"),
        ("absent", "static_modifier", "missing"),
        (None, "static_modifier", "dynamic"),
        ("shared", "modifier_type", "ambiguous"),
    ]
    for source, text, syntax in [
        (
            "game/common/static_modifiers/test.txt",
            "existing = { shared = 2 icon = gfx/texture.dds }",
            "static_modifier_entry",
        ),
        (
            "game/common/modifier_type_definitions/test.txt",
            'existing = { game_data = { translate = "shared" } }',
            "modifier_type_translation",
        ),
    ]:
        (reference,) = iter_references(source, _DIGEST, parse_text(text), names)
        assert (reference.name, reference.requested_kind, reference.syntax, reference.status) == (
            "shared",
            "modifier_type",
            syntax,
            "ambiguous",
        )


def test_parser_failures_and_unrelated_pdx_are_not_positive_evidence() -> None:
    names = {"known": {"script_value": 1}}
    source = "game/common/script_values/test.txt"
    partial = parse_text("possible = { value = known")
    (row,) = iter_references(source, _DIGEST, partial, names)
    assert (row.status, row.parse_status) == ("unknown", "partial")
    failed = parse_bytes(b"foo = { value = known } #\xff", source, encoding="utf-8-sig")
    assert list(iter_references(source, _DIGEST, failed, names)) == []
    valid = parse_text("foo = { value = known }")
    assert list(iter_references("game/gfx/test.txt", _DIGEST, valid, names)) == []
