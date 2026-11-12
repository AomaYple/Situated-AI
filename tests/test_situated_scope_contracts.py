"""D0 字段级 operation 证据：部分合同可记录，作用域缺失仍保持 pending。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pdx import version_contracts
from pdx.situated import inventory

if TYPE_CHECKING:
    from pathlib import Path


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _game(tmp_path: Path) -> Path:
    game = tmp_path / "game"
    _write(tmp_path, "caligula_branch.txt", f"release/{version_contracts.active_version()}\n")
    _write(tmp_path, "caligula_rev.txt", "fixture\n")
    _write(tmp_path, "clausewitz_branch.txt", "fixture\n")
    _write(tmp_path, "clausewitz_rev.txt", "fixture\n")
    _write(
        game,
        "common/ai_strategies/00_default_strategy.txt",
        "ai_strategy_default = {\n"
        " # Using this value in other strategies will function additively\n"
        " diplomatic_play_neutrality = { value = 1 }\n"
        " # Using this value in other strategies will function multiplicatively\n"
        " ideological_opinion_effect_mult = { value = 1 }\n"
        " # Using a different value in a strategy will override this value\n"
        " desired_tax_level = medium\n"
        ' icon = "default.dds"\n'
        "}\n",
    )
    _write(
        game,
        "common/technology/technologies/10_production.txt",
        "technology_test = { ai_weight = { value = 1 } }\n",
    )
    _write(game, "common/technology/eras/eras.md", "technology_cost = number\n")
    return game


def test_strategy_merge_documentation_records_operation_without_scope(tmp_path: Path) -> None:
    result = inventory.discover_vanilla(game=_game(tmp_path))
    rows = {
        item.field: item for item in result.surfaces if item.definition == "ai_strategy_default"
    }
    assert (
        rows["diplomatic_play_neutrality"].actor_scope,
        rows["diplomatic_play_neutrality"].target_scope,
    ) == (
        "unknown",
        "unknown",
    )
    assert rows["diplomatic_play_neutrality"].operation == "additive_score"
    assert rows["diplomatic_play_neutrality"].capability == "pending"
    assert rows["ideological_opinion_effect_mult"].operation == "multiplicative_score"
    assert rows["desired_tax_level"].operation == "override_value"
    assert all(
        item.surface_id in result.unknown_scopes for item in rows.values() if item.field != "icon"
    )


def test_strategy_operation_evidence_is_removed_when_comment_is_missing(tmp_path: Path) -> None:
    game = _game(tmp_path)
    path = game / "common/ai_strategies/00_default_strategy.txt"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            " # Using this value in other strategies will function additively\n", ""
        ),
        encoding="utf-8",
        newline="\n",
    )
    result = inventory.discover_vanilla(game=game)
    row = next(
        item
        for item in result.surfaces
        if item.definition == "ai_strategy_default" and item.field == "diplomatic_play_neutrality"
    )
    assert (row.operation, row.capability, row.scope_evidence) == (
        "declared_field",
        "pending",
        (),
    )


def test_technology_ai_weight_stays_pending_without_outer_consumer_contract(tmp_path: Path) -> None:
    result = inventory.discover_vanilla(game=_game(tmp_path))
    row = next(item for item in result.surfaces if item.field == "ai_weight")
    assert row.source.endswith("common/technology/technologies/10_production.txt")
    assert (row.actor_scope, row.target_scope, row.operation, row.capability) == (
        "unknown",
        "unknown",
        "declared_field",
        "pending",
    )


def test_law_impose_chance_does_not_inherit_enact_weight_scope_documentation(
    tmp_path: Path,
) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/laws/readme.md",
        "Root scope is AI country, scope:law contains the relevant law for that country\n",
    )

    _write(
        game,
        "common/laws/policy.txt",
        "law_known = {\n"
        " ai_impose_chance = { value = 25 }\n"
        " ai_will_do = { always = yes }\n"
        " ai_enact_weight_modifier = { value = 10 }\n"
        "}\n",
    )
    result = inventory.discover_vanilla(game=game)
    rows = {item.field: item for item in result.surfaces if item.definition == "law_known"}
    for field in ("ai_impose_chance", "ai_will_do"):
        row = rows[field]
        assert (row.actor_scope, row.target_scope, row.operation, row.capability) == (
            "unknown",
            "unknown",
            "declared_field",
            "pending",
        )
        assert not row.scope_evidence
        assert row.surface_id in result.unknown_scopes
    enact = rows["ai_enact_weight_modifier"]
    assert (enact.actor_scope, enact.target_scope, enact.operation) == (
        "country",
        "scope:law=law",
        "additive_score",
    )
    assert enact.legal


def test_company_charter_ai_operations_are_recorded_without_inheriting_company_scope(
    tmp_path: Path,
) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/company_charter_types/company_charter_types.md",
        "company_charter_type = {\n"
        " possible = {} # A trigger evaluated in company scope to determine if this charter type should be available to the company\n"
        " ai_possible = {} # If this charter is possible to be picked up by AI\n"
        " ai_weight = {} # Check score for AI to pickup charter, will be scaled by company relative size to other companies\n"
        "}\n",
    )
    _write(
        game,
        "common/company_charter_types/known.txt",
        "charter_known = { ai_possible = { always = yes } ai_weight = { value = 2 } }\n",
    )
    result = inventory.discover_vanilla(game=game)
    rows = {item.field: item for item in result.surfaces if item.definition == "charter_known"}
    assert (rows["ai_possible"].actor_scope, rows["ai_possible"].target_scope) == (
        "unknown",
        "unknown",
    )
    assert rows["ai_possible"].operation == "predicate"
    assert rows["ai_weight"].operation == "relative_weight"
    for row in rows.values():
        assert row.capability == "pending"
        assert row.scope_evidence
        assert not row.legal
        assert row.surface_id in result.unknown_scopes


def test_company_charter_ai_operation_requires_its_own_template_description(tmp_path: Path) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/company_charter_types/company_charter_types.md",
        "possible = {} # A trigger evaluated in company scope to determine if this charter type should be available to the company\n"
        "ai_possible = {}\n"
        "ai_weight = {}\n",
    )
    _write(
        game,
        "common/company_charter_types/known.txt",
        "charter_known = { ai_possible = { always = yes } ai_weight = { value = 2 } }\n",
    )
    result = inventory.discover_vanilla(game=game)
    rows = {item.field: item for item in result.surfaces if item.definition == "charter_known"}
    assert all(row.operation == "declared_field" for row in rows.values())
    assert all(row.capability == "pending" and not row.scope_evidence for row in rows.values())


def test_naval_mission_ai_operations_do_not_invent_runtime_scope(tmp_path: Path) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/naval_mission_types/naval_mission_types.md",
        "ai_will_do = {} # Trigger to enable/disable this for ai\n"
        "# Used after AI has decided what type of mission behavior it wants what mission to pick\n"
        "# This means it is weighted between missions with same mission behavior profile and not against\n"
        "# all mission types that has been scripted\n"
        "ai_weight = {}\n",
    )
    _write(
        game,
        "common/naval_mission_types/known.txt",
        "mission_known = { ai_will_do = { always = yes } ai_weight = { value = 1 } }\n",
    )
    result = inventory.discover_vanilla(game=game)
    rows = {item.field: item for item in result.surfaces if item.definition == "mission_known"}
    assert rows["ai_will_do"].operation == "predicate"
    assert rows["ai_weight"].operation == "relative_weight"
    for row in rows.values():
        assert (row.actor_scope, row.target_scope) == ("unknown", "unknown")
        assert row.capability == "pending"
        assert row.scope_evidence
        assert not row.legal
        assert row.surface_id in result.unknown_scopes


def test_naval_mission_ai_weight_requires_its_specific_selection_semantics(tmp_path: Path) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/naval_mission_types/naval_mission_types.md",
        "ai_will_do = {} # Trigger to enable/disable this for ai\nai_weight = {}\n",
    )
    _write(
        game,
        "common/naval_mission_types/known.txt",
        "mission_known = { ai_will_do = { always = yes } ai_weight = { value = 1 } }\n",
    )
    result = inventory.discover_vanilla(game=game)
    rows = {item.field: item for item in result.surfaces if item.definition == "mission_known"}
    assert rows["ai_will_do"].operation == "predicate"
    assert rows["ai_weight"].operation == "declared_field"
    assert rows["ai_weight"].capability == "pending"
    assert rows["ai_weight"].scope_evidence == ()


def test_cohesion_ai_support_score_is_static_engine_configuration(tmp_path: Path) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/cohesion_levels/levels.txt",
        "cohesion_level_high = {\n"
        " # AI implications for Power Blocs: high cohesion changes unification support\n"
        " ai_unification_support_score = 10\n"
        "}\n",
    )
    result = inventory.discover_vanilla(game=game)
    row = next(item for item in result.surfaces if item.field == "ai_unification_support_score")
    assert (row.actor_scope, row.target_scope, row.operation, row.capability) == (
        "global",
        "none",
        "unification_support_score",
        "indirect",
    )
    assert row.legal
    assert row.getter is None
    assert row.scope_evidence == ("common/cohesion_levels/levels.txt:2",)
    assert row.surface_id not in result.unknown_scopes


def test_cohesion_field_without_its_ai_comment_stays_pending(tmp_path: Path) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/cohesion_levels/levels.txt",
        "cohesion_level_high = { ai_unification_support_score = 10 }\n",
    )
    result = inventory.discover_vanilla(game=game)
    row = next(item for item in result.surfaces if item.field == "ai_unification_support_score")
    assert row.capability == "pending"
    assert (row.actor_scope, row.target_scope) == ("unknown", "unknown")
    assert row.operation == "declared_field"
    assert not row.scope_evidence
    assert not row.legal


def _ship_modification_game(
    tmp_path: Path,
    *,
    multiplier: str = "ship_mod_market_multiplier",
    formula: str = "ship_modification_market_demand_ratio(scope:ship_modification_type)",
) -> Path:
    game = _game(tmp_path)
    _write(
        game,
        "common/ship_modifications/ship_modifications.md",
        "# Ship modification\n"
        "# [Default = 1] How important is this ship type to build for AI\n"
        "# root - country\n"
        "ai_weight = fixed_point\n",
    )
    _write(
        game,
        "common/ship_modifications/ships.txt",
        "ship_mod_test = {\n"
        " type = ship_mod_slot_armor\n"
        " ai_weight = { value = 1 multiply = "
        f"{multiplier}"
        " }\n"
        "}\n",
    )
    _write(
        game,
        "common/script_values/script_values.md",
        "# Formulas\nThese allow you to use everything available in\n"
        "the scope you're currently in.\n",
    )
    _write(
        game,
        "common/script_values/ai_script_values.txt",
        f'ship_mod_market_multiplier = {{\n value = "{formula}"\n}}\n',
    )
    return game


def test_ship_modification_scope_requires_documented_actor_and_scoped_score_chain(
    tmp_path: Path,
) -> None:
    result = inventory.discover_vanilla(game=_ship_modification_game(tmp_path))
    row = next(item for item in result.surfaces if item.definition == "ship_mod_test")
    assert (
        row.actor_scope,
        row.target_scope,
        row.operation,
        row.capability,
    ) == ("country", "scope:ship_modification_type=ship_modification", "score", "direct")
    assert row.legal
    assert row.scope_evidence == (
        "common/ship_modifications/ship_modifications.md:2",
        "common/script_values/ai_script_values.txt:2",
        "common/script_values/script_values.md:1",
        "common/ship_modifications/ships.txt:3",
    )
    assert row.surface_id not in result.unknown_scopes


@pytest.mark.parametrize(
    ("multiplier", "formula"),
    [
        (
            "unrelated_multiplier",
            "ship_modification_market_demand_ratio(scope:ship_modification_type)",
        ),
        ("ship_mod_market_multiplier", "ship_modification_market_demand_ratio"),
    ],
)
def test_ship_modification_scope_stays_pending_without_the_scoped_formula_link(
    tmp_path: Path, multiplier: str, formula: str
) -> None:
    result = inventory.discover_vanilla(
        game=_ship_modification_game(tmp_path, multiplier=multiplier, formula=formula)
    )
    row = next(item for item in result.surfaces if item.definition == "ship_mod_test")
    assert (row.actor_scope, row.target_scope, row.operation, row.capability) == (
        "country",
        "unknown",
        "score",
        "pending",
    )
    assert row.surface_id in result.unknown_scopes


_SUBJECT_VALUE_DOC = (
    " # Multiplies both subject_value and become_subject_value in AI strategies\n"
    " # Higher value means AI is more interested in having this type of subject but less "
    "interested in *being* this type of subject\n"
    " # Cannot return a value lower than MIN_SUBJECT_TYPE_VALUE\n"
)


def _subject_value_game(
    tmp_path: Path, body: str, *, documentation: str = _SUBJECT_VALUE_DOC
) -> Path:
    game = _game(tmp_path)
    _write(
        game,
        "common/subject_types/subjects.txt",
        "subject_type_test = {\n"
        + documentation
        + body
        + "\n}\nsubject_type_inventory_sentinel = { ai_value = { value = 1 } }\n",
    )
    _write(
        game,
        "common/defines/00_ai.txt",
        "NAI = {\n MIN_SUBJECT_TYPE_VALUE = 1 # ai_value for a subject type is never below this\n}\n",
    )
    return game


@pytest.mark.parametrize("constant", ["1", "1.1", "1.25", "1.5"])
def test_subject_type_ai_value_is_only_static_configuration(tmp_path: Path, constant: str) -> None:
    result = inventory.discover_vanilla(
        game=_subject_value_game(tmp_path, f" ai_value = {{ value = {constant} }}")
    )
    row = next(item for item in result.surfaces if item.definition == "subject_type_test")
    assert (row.actor_scope, row.target_scope, row.operation, row.capability) == (
        "global",
        "none",
        "static_subject_type_value_multiplier",
        "indirect",
    )
    assert row.legal
    assert row.getter is None
    assert row.getter_note == "静态定义配置；不是国家脚本 getter，也没有生产写入"
    assert row.scope_evidence == (
        "common/subject_types/subjects.txt:2",
        "common/defines/00_ai.txt:2",
    )
    assert row.surface_id not in result.unknown_scopes


@pytest.mark.parametrize(
    "body",
    [
        " ai_value = { }",
        " ai_value = { value = 1 if = { limit = { is_ai = yes } add = 1 } }",
        " ai_value = { value = subject_multiplier }",
        " ai_value = { value = 1 multiply = 2 }",
        " ai_value = { value = 1 value = 2 }",
        " ai_value = { value = 1 bare_token }",
        ' ai_value = { value = "1" }',
        " ai_value = { value = nan }",
        " ai_value = { value = inf }",
        " ai_value = { value = 1e999 }",
        " ai_value = { value > 1 }",
        " ai_value = { INJECT:value = 1 }",
        " ai_value = 1",
        " ai_value > { value = 1 }",
        " INJECT:ai_value = { value = 1 }",
        " ai_value = { value = 1 }\n ai_value = { value = 1 }",
    ],
)
def test_subject_type_dynamic_or_ambiguous_ai_value_stays_pending(
    tmp_path: Path, body: str
) -> None:
    result = inventory.discover_vanilla(game=_subject_value_game(tmp_path, body))
    rows = [item for item in result.surfaces if item.definition == "subject_type_test"]
    assert rows
    for row in rows:
        assert (row.actor_scope, row.target_scope, row.operation, row.capability) == (
            "unknown",
            "unknown",
            "declared_field",
            "pending",
        )
        assert not row.legal
        assert row.getter is None
        assert row.scope_evidence == ()
        assert row.surface_id in result.unknown_scopes


@pytest.mark.parametrize(
    "documentation",
    [
        "",
        _SUBJECT_VALUE_DOC.replace("Multiplies both", "Adds to both"),
        _SUBJECT_VALUE_DOC.replace("but less interested", "but more interested"),
        _SUBJECT_VALUE_DOC.replace(
            "# Cannot return a value lower than MIN_SUBJECT_TYPE_VALUE\n", ""
        ),
        _SUBJECT_VALUE_DOC + " other_field = yes\n",
        _SUBJECT_VALUE_DOC + " # unrelated field documentation\n",
    ],
)
def test_subject_type_ai_value_requires_its_exact_adjacent_documentation(
    tmp_path: Path, documentation: str
) -> None:
    result = inventory.discover_vanilla(
        game=_subject_value_game(tmp_path, " ai_value = { value = 1 }", documentation=documentation)
    )
    row = next(item for item in result.surfaces if item.definition == "subject_type_test")
    assert (row.actor_scope, row.target_scope, row.operation, row.capability) == (
        "unknown",
        "unknown",
        "declared_field",
        "pending",
    )
    assert row.scope_evidence == ()
    assert not row.legal


@pytest.mark.parametrize("same_file", [False, True])
def test_subject_type_duplicate_definition_cannot_grant_static_scope(
    tmp_path: Path, same_file: bool
) -> None:
    body = " ai_value = { value = 1 }"
    game = _subject_value_game(tmp_path, body)
    path = game / "common/subject_types/subjects.txt"
    duplicate = "subject_type_test = {\n" + _SUBJECT_VALUE_DOC + body + "\n}\n"
    if same_file:
        path.write_text(
            path.read_text(encoding="utf-8") + duplicate, encoding="utf-8", newline="\n"
        )
    else:
        _write(game, "common/subject_types/duplicate.txt", duplicate)
    result = inventory.discover_vanilla(game=game)
    rows = [item for item in result.surfaces if item.definition == "subject_type_test"]
    assert len(rows) == 2
    for row in rows:
        assert row.capability == "pending"
        assert (row.actor_scope, row.target_scope) == ("unknown", "unknown")
        assert row.scope_evidence == ()
        assert not row.legal


@pytest.mark.parametrize(
    "prefix",
    ["INJECT", "REPLACE", "TRY_INJECT", "TRY_REPLACE", "INJECT_OR_CREATE", "REPLACE_OR_CREATE"],
)
def test_ai_directory_with_only_prefixed_assignment_is_discovered(
    tmp_path: Path, prefix: str
) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/subject_types/prefixed.txt",
        "subject_type_prefixed = {\n"
        + _SUBJECT_VALUE_DOC
        + f" {prefix}:ai_value = {{ value = 1 }}\n}}\n",
    )
    result = inventory.discover_vanilla(game=game)
    row = next(item for item in result.surfaces if item.definition == "subject_type_prefixed")
    assert row.field == "ai_value"
    assert row.capability == "pending"
    assert (row.actor_scope, row.target_scope) == ("unknown", "unknown")
    assert row.scope_evidence == ()


@pytest.mark.parametrize(
    "body",
    [
        "# INJECT:ai_value = { value = 1 }\n",
        'documentation = "INJECT:ai_value = { value = 1 }"\n',
        "# ai_value = { value = 1 }\n",
        'documentation = "ai_value = { value = 1 }"\n',
    ],
)
def test_comment_and_string_assignments_do_not_create_ai_surfaces(
    tmp_path: Path, body: str
) -> None:
    from pdx.situated.vanilla_inventory import _has_ai_assignment

    game = _game(tmp_path)
    _write(game, "common/subject_types/false.txt", "subject_type_false = {\n" + body + "}\n")
    assert not _has_ai_assignment(body.encode("utf-8"))
    result = inventory.discover_vanilla(game=game)
    assert not any(item.definition == "subject_type_false" for item in result.surfaces)


@pytest.mark.parametrize(
    ("constant", "defines"),
    [
        (
            "0",
            "NAI = { MIN_SUBJECT_TYPE_VALUE = 1 # ai_value for a subject type is never below this\n}",
        ),
        (
            "-1",
            "NAI = { MIN_SUBJECT_TYPE_VALUE = 1 # ai_value for a subject type is never below this\n}",
        ),
        (
            ".5",
            "NAI = { MIN_SUBJECT_TYPE_VALUE = 1 # ai_value for a subject type is never below this\n}",
        ),
        (
            "1",
            "NAI = { MIN_SUBJECT_TYPE_VALUE = 2 # ai_value for a subject type is never below this\n}",
        ),
        ("1", None),
        ("1", "NAI = { OTHER_VALUE = 1 }"),
        (
            "1",
            "NAI = { MIN_SUBJECT_TYPE_VALUE = 0 # ai_value for a subject type is never below this\n}",
        ),
        (
            "1",
            "NAI = { MIN_SUBJECT_TYPE_VALUE = -1 # ai_value for a subject type is never below this\n}",
        ),
        (
            "1",
            'NAI = { MIN_SUBJECT_TYPE_VALUE = "1" # ai_value for a subject type is never below this\n}',
        ),
        (
            "1",
            "NAI = { MIN_SUBJECT_TYPE_VALUE = nan # ai_value for a subject type is never below this\n}",
        ),
        (
            "1",
            "NAI = { MIN_SUBJECT_TYPE_VALUE = inf # ai_value for a subject type is never below this\n}",
        ),
        (
            "1",
            "NAI = { MIN_SUBJECT_TYPE_VALUE = 1e999 # ai_value for a subject type is never below this\n}",
        ),
        (
            "1",
            "NAI = { MIN_SUBJECT_TYPE_VALUE = yes # ai_value for a subject type is never below this\n}",
        ),
        (
            "1",
            "NAI = { MIN_SUBJECT_TYPE_VALUE = { value = 1 } # ai_value for a subject type is never below this\n}",
        ),
        (
            "1",
            "NAI = { MIN_SUBJECT_TYPE_VALUE > 1 # ai_value for a subject type is never below this\n}",
        ),
        (
            "1",
            "NAI = { INJECT:MIN_SUBJECT_TYPE_VALUE = 1 # ai_value for a subject type is never below this\n}",
        ),
        (
            "1",
            "INJECT:NAI = { MIN_SUBJECT_TYPE_VALUE = 1 # ai_value for a subject type is never below this\n}",
        ),
        (
            "1",
            "NAI > { MIN_SUBJECT_TYPE_VALUE = 1 # ai_value for a subject type is never below this\n}",
        ),
        (
            "1",
            "NAI = { MIN_SUBJECT_TYPE_VALUE = 1 # ai_value for a subject type is never below this\n MIN_SUBJECT_TYPE_VALUE = 1 }",
        ),
        (
            "1",
            "NAI = { MIN_SUBJECT_TYPE_VALUE = 1 # ai_value for a subject type is never below this\n}\nNAI = { OTHER_VALUE = 1 }",
        ),
        (
            "1",
            "NAI = { MIN_SUBJECT_TYPE_VALUE = 1 # ai_value for a subject type is never above this\n}",
        ),
        (
            "1",
            "NAI = { # ai_value for a subject type is never below this\n MIN_SUBJECT_TYPE_VALUE = 1 }",
        ),
        (
            "1",
            "NAI = { MIN_SUBJECT_TYPE_VALUE = 1\n OTHER_VALUE = 1 # ai_value for a subject type is never below this\n}",
        ),
    ],
)
def test_subject_type_minimum_requires_unique_positive_documented_define(
    tmp_path: Path, constant: str, defines: str | None
) -> None:
    game = _subject_value_game(tmp_path, f" ai_value = {{ value = {constant} }}")
    if defines is None:
        (game / "common/defines/00_ai.txt").unlink()
    else:
        _write(game, "common/defines/00_ai.txt", defines)
    result = inventory.discover_vanilla(game=game)
    row = next(item for item in result.surfaces if item.definition == "subject_type_test")
    assert row.capability == "pending"
    assert (row.actor_scope, row.target_scope) == ("unknown", "unknown")
    assert row.getter is None
    assert row.scope_evidence == ()
    assert row.surface_id in result.unknown_scopes


def test_subject_minimum_duplicate_mounted_namespace_does_not_borrow_base_evidence(tmp_path: Path):
    game = _subject_value_game(tmp_path, " ai_value = { value = 1 }")
    _write(game, "common/defines/extra.txt", "NAI = { OTHER_VALUE = 2 }")
    result = inventory.discover_vanilla(game=game)
    row = next(item for item in result.surfaces if item.definition == "subject_type_test")
    assert row.capability == "pending"
    assert row.scope_evidence == ()


@pytest.mark.parametrize(("constant", "minimum"), [("2", "2"), ("2.5", "2"), (".5", ".5")])
def test_subject_static_value_at_or_above_a_positive_changed_minimum(
    tmp_path: Path, constant: str, minimum: str
):
    game = _subject_value_game(tmp_path, f" ai_value = {{ value = {constant} }}")
    _write(
        game,
        "common/defines/00_ai.txt",
        "# shifted source evidence\nNAI = {\n MIN_SUBJECT_TYPE_VALUE = "
        + minimum
        + " # ai_value for a subject type is never below this\n}\n",
    )
    result = inventory.discover_vanilla(game=game)
    row = next(item for item in result.surfaces if item.definition == "subject_type_test")
    assert row.capability == "indirect"
    assert row.getter is None
    assert (row.actor_scope, row.target_scope) == ("global", "none")
    assert row.scope_evidence == (
        "common/subject_types/subjects.txt:2",
        "common/defines/00_ai.txt:3",
    )
