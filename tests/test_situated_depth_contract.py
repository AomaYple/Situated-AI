"""D0 独立原版分母：发现、作用域证据和拒错合同。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdx import ai_surface, version_contracts
from pdx.situated import inventory, vanilla_inventory

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def historical_discovery_contract():
    # These synthetic fixtures declare release/1.14.5 and its documentation;
    # installed 1.15 integrations keep their independently selected contract.
    with version_contracts.select_version("1.14.5"):
        yield


def _write(game: Path, relative: str, text: str) -> None:
    path = game / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _game(tmp_path: Path) -> Path:
    game = tmp_path / "game"
    _write(tmp_path, "caligula_branch.txt", "release/1.14.5\n")
    _write(tmp_path, "caligula_rev.txt", "fixture-revision\n")
    _write(tmp_path, "clausewitz_branch.txt", "fixture-engine-branch\n")
    _write(tmp_path, "clausewitz_rev.txt", "fixture-engine-revision\n")
    _write(
        game,
        "common/ai_strategies/00_default_strategy.txt",
        "ai_strategy_default = {\n"
        " # How much does the AI desire a state owned by another country\n"
        " # Using this value in other strategies will function additively\n"
        " # root = country\n"
        " # scope:target_state = state\n"
        " # scope:target_country = state owner\n"
        " state_value = { value = 1 }\n}\n",
    )
    _write(
        game,
        "common/ai_strategies/active/other.txt",
        "ai_strategy_active = { state_value = { value = 2 } }\n",
    )
    _write(
        game,
        "common/laws/untouched.txt",
        "law_new = { ai_enact_weight_modifier = { value = 3 } }\n",
    )
    _write(
        game,
        "common/laws/readme.md",
        "Root scope is AI country, scope:law contains the relevant law for that country\n"
        "This is a value that is added or subtracted from the AI's base weight to enact a law\n",
    )
    _write(
        game,
        "common/buildings/untouched.txt",
        "building_new = { ai_value = { value = 4 } }\n",
    )
    _write(
        game,
        "common/buildings/buildings.md",
        "# base AI value\n# scope is state the building is located in\nai_value = script value\n",
    )
    return game


def test_d0_new_legal_definition_in_untouched_file_expands_pending_denominator(tmp_path) -> None:
    game = _game(tmp_path)
    first = inventory.discover_vanilla(game=game)
    _write(
        game,
        "common/laws/nested/another.txt",
        "law_another = { ai_enact_weight_modifier = { value = 5 } }\n",
    )
    second = inventory.discover_vanilla(game=game)
    assert first.discovered_count == 4
    assert second.discovered_count == 5
    assert second.legal_count == 5
    added = next(item for item in second.surfaces if item.definition == "law_another")
    assert added.status == "pending"
    assert added.capability == "direct"
    assert added.responsibility_step == "D4.06"
    assert second.pending_count == 5
    assert first.scope_hash != second.scope_hash


def test_d0_active_and_default_strategy_same_field_have_distinct_identities(tmp_path) -> None:
    result = inventory.discover_vanilla(game=_game(tmp_path))
    rows = [item for item in result.surfaces if item.field == "state_value"]
    assert len(rows) == 2
    assert {item.definition for item in rows} == {"ai_strategy_default", "ai_strategy_active"}
    assert len({item.surface_id for item in rows}) == 2
    assert all(item.actor_scope == "country" for item in rows)
    assert all(
        item.target_scope == "scope:target_state=state;scope:target_country=country"
        for item in rows
    )
    assert all(item.operation == "additive_score" for item in rows)


def test_d0_strategy_documentation_proves_state_predicate_scope(tmp_path) -> None:
    game = _game(tmp_path)
    path = game / "common/ai_strategies/00_default_strategy.txt"
    original = path.read_text(encoding="utf-8").rstrip()
    path.write_text(
        original[:-1]
        + " # If this trigger evaluates to true, the AI will incorporate scope:target_state\n"
        " # root = country, scope:target_state = the state being considered\n"
        " will_incorporate_state = { always = yes }\n}\n",
        encoding="utf-8",
        newline="\n",
    )
    result = inventory.discover_vanilla(game=game)
    row = next(item for item in result.surfaces if item.field == "will_incorporate_state")
    assert (row.actor_scope, row.target_scope, row.operation, row.capability) == (
        "country",
        "scope:target_state=state",
        "predicate",
        "direct",
    )


def test_d0_strategy_documentation_proves_country_score_maps(tmp_path) -> None:
    game = _game(tmp_path)
    path = game / "common/ai_strategies/00_default_strategy.txt"
    original = path.read_text(encoding="utf-8").rstrip()
    path.write_text(
        original[:-1] + " # How much the AI wants to liberate a specific tag\n"
        " # Using this value in other strategies will function additively\n"
        " # root = liberator\n"
        " # scope:target = oppressor\n"
        " liberate_country_scores = { HOL = { value = 1 } }\n"
        " # Determines which strait settings the AI will use, highest score\n"
        " # Using this value in other strategies will function additively\n"
        " # root = country\n"
        " # scope:strait = the strait\n"
        " # scope:first_state = the first state controlling the strait\n"
        " # scope:second_state = the second state controlling the strait\n"
        " # scope:is_sole_controller = yes/no\n"
        " strait_scores = { status_scores = { open = { value = 1 } } }\n}\n",
        encoding="utf-8",
        newline="\n",
    )
    result = inventory.discover_vanilla(game=game)
    rows = [
        item
        for item in result.surfaces
        if item.field.startswith("liberate_country_scores.")
        or item.field.startswith("strait_scores.")
    ]
    assert rows
    assert all(item.capability == "direct" for item in rows)
    assert any(
        item.field.startswith("liberate_country_scores.")
        and item.actor_scope == "country"
        and item.target_scope == "scope:target=country"
        and item.operation == "additive_score"
        for item in rows
    )
    assert any(
        item.field.startswith("strait_scores.")
        and item.actor_scope == "country"
        and item.target_scope
        == "scope:strait=strait;scope:first_state=state;scope:second_state=state;"
        "scope:is_sole_controller=bool"
        and item.operation == "additive_score"
        for item in rows
    )


def test_d0_default_strategy_header_does_not_prove_all_fields_country_scores(tmp_path) -> None:
    game = _game(tmp_path)
    source = "common/ai_strategies/00_default_strategy.txt"
    path = game / source
    original = path.read_text(encoding="utf-8").rstrip()
    path.write_text(
        "# All AIs always load data from this strategy\n"
        + original[:-1]
        + " desired_tax_level = medium\n"
        " goods_stances = { grain = { stance = export } }\n"
        ' metadata = "country-scoped default"\n'
        ' icon = "default.dds"\n'
        " type = political\n"
        " possible = { always = yes }\n"
        " weight = { value = 1 }\n"
        " invented_score = { value = scope:target_country.foo }\n"
        " will_invent = { always = yes }\n}\n",
        encoding="utf-8",
        newline="\n",
    )
    scopes = vanilla_inventory._strategy_scopes({source: path.read_bytes()})
    assert set(scopes) == {"state_value"}
    result = inventory.discover_vanilla(game=game)
    rows = [
        item
        for item in result.surfaces
        if item.definition == "ai_strategy_default" and item.field != "state_value"
    ]
    assert {item.field for item in rows} == {
        "desired_tax_level",
        "goods_stances.grain.stance",
        "metadata",
        "possible",
        "weight",
        "invented_score",
        "will_invent",
    }
    for row in rows:
        assert (row.actor_scope, row.target_scope, row.operation, row.capability) == (
            "unknown",
            "unknown",
            "declared_field",
            "pending",
        )
        assert not row.scope_evidence
        assert row.getter is None
        assert row.status == "pending"
        assert row.surface_id in result.unknown_scopes


def test_d0_strategy_allocation_description_does_not_prove_evaluation_scope(tmp_path) -> None:
    game = _game(tmp_path)
    path = game / "common/ai_strategies/00_default_strategy.txt"
    original = path.read_text(encoding="utf-8")
    path.write_text(
        original.replace(
            " state_value = { value = 1 }\n",
            " state_value = { value = 1 }\n"
            " # Trigger for whether this strategy can be randomly allocated to a country\n"
            " possible = { always = yes }\n"
            " # Chance that this strategy will be randomly allocated to a country\n"
            " weight = { value = 2 }\n",
        ),
        encoding="utf-8",
        newline="\n",
    )
    result = inventory.discover_vanilla(game=game)
    rows = {
        item.field: item for item in result.surfaces if item.definition == "ai_strategy_default"
    }
    for field in ("possible", "weight"):
        assert rows[field].capability == "pending"
        assert rows[field].actor_scope == rows[field].target_scope == "unknown"


def test_d0_strategy_possible_without_allocation_documentation_stays_pending(tmp_path) -> None:
    game = _game(tmp_path)
    path = game / "common/ai_strategies/00_default_strategy.txt"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            " state_value = { value = 1 }\n",
            " state_value = { value = 1 }\n possible = { always = yes }\n weight = { value = 2 }\n",
        ),
        encoding="utf-8",
        newline="\n",
    )
    result = inventory.discover_vanilla(game=game)
    rows = {
        item.field: item for item in result.surfaces if item.definition == "ai_strategy_default"
    }
    for field in ("possible", "weight"):
        assert rows[field].capability == "pending"
        assert rows[field].actor_scope == rows[field].target_scope == "unknown"


def test_d0_fleet_composition_documentation_proves_nested_country_contract(tmp_path) -> None:
    game = _game(tmp_path)
    path = game / "common/ai_strategies/00_default_strategy.txt"
    original = path.read_text(encoding="utf-8").rstrip()
    path.write_text(
        original[:-1]
        + "\n"
        + " # All numeric fields accept script values, so weights can be tuned from country scope.\n"
        + " # ai_ship_category_weights:\n"
        + " # weights are summed per category\n"
        + " # mission_type_weights:\n"
        + " #   Multiplier applied when a fleet in this role picks which mission to pursue. 1.0 is neutral; 0.0 disables it for this role.\n"
        + " #   any mission type not listed is treated as 0. Omit the whole block to leave every mission neutral.\n"
        + " # min_ships_wanted:\n"
        + " #   Soft floor on fleet size used during role-fit scoring.\n"
        + " # num_fleets_wanted:\n"
        + " #   How many fleets should take this role. Omitted means one. Evaluated in country scope; a value of 0 drops the role for that country.\n"
        + " # potential:\n"
        + " #   Country-scoped trigger. If it fails the role is dropped entirely.\n"
        + " fleet_compositions = {\n"
        + "  escort = {\n"
        + "   ai_ship_category_weights = { screens = { value = 1 } }\n"
        + "   mission_type_weights = { protect_supply = { value = 2 } }\n"
        + "   min_ships_wanted = 3\n"
        + "   num_fleets_wanted = { value = 1 }\n"
        + "   potential = { always = yes }\n"
        + "  }\n"
        + " }\n}\n",
        encoding="utf-8",
        newline="\n",
    )
    scopes = vanilla_inventory._strategy_scopes(
        {"common/ai_strategies/00_default_strategy.txt": path.read_bytes()}
    )
    assert scopes["fleet_compositions.escort.ai_ship_category_weights.screens"].actor == "country"
    assert scopes["fleet_compositions.escort.ai_ship_category_weights.screens"].target == "none"
    assert (
        scopes["fleet_compositions.escort.ai_ship_category_weights.screens"].capability == "direct"
    )
    assert scopes["fleet_compositions.escort.ai_ship_category_weights.screens"].evidence
    assert scopes["fleet_compositions.escort.mission_type_weights.protect_supply"].operation == (
        "multiplicative_score"
    )
    assert scopes["fleet_compositions.escort.min_ships_wanted"].operation == "soft_floor"
    assert scopes["fleet_compositions.escort.num_fleets_wanted"].operation == "fleet_count"
    assert scopes["fleet_compositions.escort.potential"].operation == "predicate"


def test_d0_fleet_composition_missing_header_stays_pending(tmp_path) -> None:
    game = _game(tmp_path)
    path = game / "common/ai_strategies/00_default_strategy.txt"
    original = path.read_text(encoding="utf-8").rstrip()
    path.write_text(
        original[:-1]
        + " fleet_compositions = { escort = { mission_type_weights = { protect_supply = { value = 2 } } } }\n}\n",
        encoding="utf-8",
        newline="\n",
    )
    scopes = vanilla_inventory._strategy_scopes(
        {"common/ai_strategies/00_default_strategy.txt": path.read_bytes()}
    )
    assert not any(key.startswith("fleet_compositions.") for key in scopes)


def test_d0_strategy_negotiation_chance_uses_declared_law_and_interest_group_scopes(
    tmp_path,
) -> None:
    game = _game(tmp_path)
    path = game / "common/ai_strategies/00_default_strategy.txt"
    original = path.read_text(encoding="utf-8")
    path.write_text(
        original.replace(
            " state_value = { value = 1 }\n",
            " state_value = { value = 1 }\n"
            " # The chance that the AI will negotiate with an IG when trying to enact a specific law\n"
            " # Using this value in other strategies will function additively\n"
            " # root = country\n"
            " # scope:law = law type being enacted\n"
            " # scope:interest_group = IG to negotiate with\n"
            " negotiation_chance = { value = 2 }\n",
        ),
        encoding="utf-8",
        newline="\n",
    )
    result = inventory.discover_vanilla(game=game)
    row = next(
        item
        for item in result.surfaces
        if item.definition == "ai_strategy_default" and item.field == "negotiation_chance"
    )
    assert (row.actor_scope, row.target_scope, row.operation, row.capability) == (
        "country",
        "scope:law=law;scope:interest_group=interest_group",
        "additive_score",
        "direct",
    )


@pytest.mark.parametrize(
    "missing",
    [
        " # root = country\n",
        " # scope:target_state = state\n",
        " # scope:target_country = state owner\n",
        " # Using this value in other strategies will function additively\n",
    ],
)
def test_d0_default_header_cannot_replace_missing_field_evidence(tmp_path, missing) -> None:
    game = _game(tmp_path)
    source = "common/ai_strategies/00_default_strategy.txt"
    path = game / source
    original = path.read_text(encoding="utf-8").replace(missing, "")
    path.write_text(
        "# All AIs always load data from this strategy\n"
        + original.replace("}\n}", "}\n desired_tax_level = medium\n}"),
        encoding="utf-8",
        newline="\n",
    )
    result = inventory.discover_vanilla(game=game)
    rows = [item for item in result.surfaces if item.field == "state_value"]
    assert len(rows) == 2
    assert all(item.capability == "pending" for item in rows)
    assert all(not item.scope_evidence for item in rows)


@pytest.mark.parametrize(
    "missing",
    [
        "scope:first_state = the first state controlling the strait",
        "scope:second_state = the second state controlling the strait",
        "scope:is_sole_controller = yes/no",
    ],
)
def test_d0_strategy_map_requires_evidence_for_every_reported_target(tmp_path, missing) -> None:
    game = _game(tmp_path)
    source = "common/ai_strategies/00_default_strategy.txt"
    path = game / source
    original = path.read_text(encoding="utf-8").rstrip()
    comments = [
        "Using this value in other strategies will function additively",
        "root = country",
        "scope:strait = the strait",
        "scope:first_state = the first state controlling the strait",
        "scope:second_state = the second state controlling the strait",
        "scope:is_sole_controller = yes/no",
    ]
    path.write_text(
        original[:-1]
        + "".join(f" # {comment}\n" for comment in comments if comment != missing)
        + " strait_scores = { status_scores = { open = { value = 1 } } }\n}\n",
        encoding="utf-8",
        newline="\n",
    )
    result = inventory.discover_vanilla(game=game)
    row = next(item for item in result.surfaces if item.field.startswith("strait_scores."))
    assert row.capability == "pending"
    assert row.target_scope == "unknown"
    assert not row.scope_evidence


def test_d0_building_nationalization_documentation_proves_country_scope(tmp_path) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/buildings/buildings.txt",
        "building_new = { ai_nationalization_desire = { value = 1 } }\n",
    )
    _write(
        game,
        "common/buildings/buildings.md",
        "# how much the AI wants to nationalize/privatize the building\n"
        "# scope is country the building is located in\n"
        "ai_privatization_deisre = script value\n",
    )
    result = inventory.discover_vanilla(game=game)
    row = next(item for item in result.surfaces if item.field == "ai_nationalization_desire")
    assert (row.actor_scope, row.target_scope, row.operation, row.capability) == (
        "country",
        "none",
        "score",
        "direct",
    )


def test_d0_target_maps_preserve_full_field_path(tmp_path) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/ai_strategies/maps.txt",
        "ai_strategy_map = { institution_scores = { "
        "institution_education = { value = 1 } institution_health_system = { value = 2 } } }\n",
    )
    result = inventory.discover_vanilla(game=game)
    fields = {item.field for item in result.surfaces if item.definition == "ai_strategy_map"}
    assert fields == {
        "institution_scores",
        "institution_scores.institution_education",
        "institution_scores.institution_health_system",
    }
    parent = next(
        item
        for item in result.surfaces
        if item.definition == "ai_strategy_map" and item.field == "institution_scores"
    )
    # Retaining the map parent does not inherit the children's numeric scope.
    # This fixture has no independent container declaration evidence.
    assert parent.capability == "pending"
    assert parent.operation == "declared_field"
    assert not parent.legal


def test_d0_scope_comes_from_documentation_not_referenced_scope_strings(tmp_path) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/new_decision_kind/new.txt",
        "new_action = { ai_new_score = { value = scope:target_country.foo } }\n",
    )
    result = inventory.discover_vanilla(game=game)
    row = next(item for item in result.surfaces if item.definition == "new_action")
    assert row.actor_scope == "unknown"
    assert row.target_scope == "unknown"
    assert row.capability == "pending"
    assert row.getter is None
    assert row.responsibility_step == "D0.03"
    assert result.unexposed_count == 0


_DECISION_CHANCE_DOC = (
    "# A decision is evaluated in country scope.\n"
    "#######################################\n"
    "# `ai_chance` value\n"
    "#######################################\n"
    "#\n"
    "# The scripted weight which determines how likely AI is to take it amongst all "
    "possible decisions (country scope).\n"
    "# Similar to event options. If it evaluates to 0, AI will not take the decision. "
    "Evaluates to 1 if unspecified\n"
    "#\n"
    "#######################################\n"
    "# Localization\n"
    "#######################################\n"
    "# Example\n# ai_chance = { value = 20 }\n"
)


def test_d0_decision_chance_requires_its_own_documented_contract(tmp_path) -> None:
    game = _game(tmp_path)
    _write(game, "common/decisions/new.txt", "new_decision = { ai_chance = { value = 0 } }\n")
    _write(game, "common/decisions/000_decisions_help.txt", _DECISION_CHANCE_DOC)
    result = inventory.discover_vanilla(game=game)
    row = next(item for item in result.surfaces if item.definition == "new_decision")
    assert (row.actor_scope, row.target_scope, row.operation, row.capability) == (
        "country",
        "none",
        "chance",
        "direct",
    )
    assert row.legal
    assert row.getter is None
    assert row.status == "pending"
    assert row.responsibility_step == "D4.06"
    assert row.surface_id not in result.unknown_scopes
    assert row.scope_evidence == (
        "common/decisions/000_decisions_help.txt:3",
        "common/decisions/000_decisions_help.txt:6",
        "common/decisions/000_decisions_help.txt:7",
    )


@pytest.mark.parametrize(
    "missing",
    [
        None,
        "# `ai_chance` value\n",
        (
            "# The scripted weight which determines how likely AI is to take it amongst all "
            "possible decisions (country scope).\n"
        ),
        (
            "# Similar to event options. If it evaluates to 0, AI will not take the decision. "
            "Evaluates to 1 if unspecified\n"
        ),
    ],
)
def test_d0_decision_chance_missing_field_evidence_stays_pending(tmp_path, missing) -> None:
    game = _game(tmp_path)
    _write(game, "common/decisions/new.txt", "new_decision = { ai_chance = { value = 1 } }\n")
    if missing is not None:
        _write(
            game,
            "common/decisions/000_decisions_help.txt",
            _DECISION_CHANCE_DOC.replace(missing, ""),
        )
    result = inventory.discover_vanilla(game=game)
    row = next(item for item in result.surfaces if item.definition == "new_decision")
    assert (row.actor_scope, row.target_scope, row.operation, row.capability) == (
        "unknown",
        "unknown",
        "declared_field",
        "pending",
    )
    assert not row.scope_evidence
    assert not row.legal
    assert row.responsibility_step == "D0.03"
    assert row.surface_id in result.unknown_scopes


def test_d0_decision_chance_does_not_borrow_an_adjacent_fields_documentation(tmp_path) -> None:
    game = _game(tmp_path)
    _write(game, "common/decisions/new.txt", "new_decision = { ai_chance = { value = 1 } }\n")
    _write(
        game,
        "common/decisions/000_decisions_help.txt",
        _DECISION_CHANCE_DOC.replace(
            "# `ai_chance` value\n",
            "# `ai_chance` value\n#######################################\n"
            "#\n#######################################\n# `ai_neighbor` value\n",
        ),
    )
    result = inventory.discover_vanilla(game=game)
    row = next(item for item in result.surfaces if item.definition == "new_decision")
    assert row.capability == "pending"
    assert not row.scope_evidence
    assert row.surface_id in result.unknown_scopes


@pytest.mark.parametrize("field", ["ai_is_valid", "ai_frequency", "ai_chance_new"])
def test_d0_decision_chance_documentation_does_not_prove_neighboring_ai_fields(
    tmp_path, field
) -> None:
    game = _game(tmp_path)
    _write(game, "common/decisions/new.txt", f"new_decision = {{ {field} = 1 }}\n")
    _write(game, "common/decisions/000_decisions_help.txt", _DECISION_CHANCE_DOC)
    result = inventory.discover_vanilla(game=game)
    row = next(item for item in result.surfaces if item.definition == "new_decision")
    assert row.capability == "pending"
    assert not row.scope_evidence
    assert not row.legal
    assert row.surface_id in result.unknown_scopes


@pytest.mark.parametrize("field", [("ai_chance", "invented"), ("ai", "ai_chance")])
def test_d0_nested_decision_chance_cannot_inherit_the_top_level_field_contract(field) -> None:
    source = "common/decisions/new.txt"
    definition = vanilla_inventory.parse_bytes(b"new_decision = {}", path=source).top_assignments[0]
    scope = vanilla_inventory._scope(
        "decisions",
        field,
        {"common/decisions/000_decisions_help.txt": _DECISION_CHANCE_DOC.encode()},
        {},
        definition,
        source,
    )
    assert scope == vanilla_inventory._Scope()


def test_d0_building_ai_value_has_state_actor_and_unproven_current_score_getter(tmp_path) -> None:
    result = inventory.discover_vanilla(game=_game(tmp_path))
    row = next(item for item in result.surfaces if item.definition == "building_new")
    assert row.actor_scope == "state"
    assert row.target_scope == "none"
    assert row.getter is None
    assert "未证明" in row.getter_note
    assert any("buildings.md" in evidence for evidence in row.scope_evidence)


def test_d0_missing_scope_documentation_keeps_field_pending(tmp_path) -> None:
    game = _game(tmp_path)
    (game / "common/buildings/buildings.md").unlink()
    result = inventory.discover_vanilla(game=game)
    row = next(item for item in result.surfaces if item.definition == "building_new")
    assert row.capability == "pending"
    assert row.actor_scope == "unknown"
    assert result.legal_count == 3


def test_d0_conflicting_strategy_root_documentation_cannot_be_overridden_by_target_names(
    tmp_path,
) -> None:
    game = _game(tmp_path)
    path = game / "common/ai_strategies/00_default_strategy.txt"
    path.write_text(
        path.read_text(encoding="utf-8").replace("root = country", "root = state"),
        encoding="utf-8",
        newline="\n",
    )
    result = inventory.discover_vanilla(game=game)
    rows = [item for item in result.surfaces if item.field == "state_value"]
    assert all(item.capability == "pending" for item in rows)
    assert all(item.actor_scope == "unknown" for item in rows)


def test_d0_diplomatic_evaluation_and_selection_do_not_inherit_target_scope(tmp_path) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/diplomatic_actions/new.txt",
        "action_new = { ai = { evaluation_chance = { value = 1 } "
        "accept_score = { value = 2 } will_select_as_first_state = { always = yes } } }\n",
    )
    _write(
        game,
        "common/diplomatic_actions/diplomatic_action.md",
        "In the AI block, the AI country is always root and the other country always scope:target\n"
        "accept_score = {}\n"
        "evaluation_chance = {}\n"
        "will_select_as_first_state = {}\n"
        "evaluation_chance only looks at the proposing AI country and has no data about targets\n"
        "will_select_as_first_state and will_select_as_second_state only contain the state as root in the scope and no other data\n",
    )
    result = inventory.discover_vanilla(game=game)
    rows = {item.field: item for item in result.surfaces if item.definition == "action_new"}
    assert (rows["ai.accept_score"].actor_scope, rows["ai.accept_score"].target_scope) == (
        "country",
        "scope:target=country",
    )
    assert (
        rows["ai.evaluation_chance"].actor_scope,
        rows["ai.evaluation_chance"].target_scope,
    ) == ("country", "none")
    assert (
        rows["ai.will_select_as_first_state"].actor_scope,
        rows["ai.will_select_as_first_state"].target_scope,
    ) == ("state", "none")
    assert rows["ai.evaluation_chance"].operation == "chance"
    assert rows["ai.accept_score"].operation == "score"
    assert rows["ai.will_select_as_first_state"].operation == "predicate"


@pytest.mark.parametrize(
    "name",
    [
        "accept_score",
        "max_influence_spending_fraction",
        "use_obligation_chance",
        "owe_obligation_chance",
        "check_acceptance_for_will_propose",
        "check_acceptance_for_will_break",
    ],
)
def test_d0_diplomatic_container_cannot_prove_undocumented_field(tmp_path, name) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/diplomatic_actions/new.txt",
        f"action_new = {{ ai = {{ {name} = 1 }} }}\n",
    )
    _write(
        game,
        "common/diplomatic_actions/diplomatic_action.md",
        "In the AI block, the AI country is always root and the other country always scope:target\n",
    )
    result = inventory.discover_vanilla(game=game)
    row = next(item for item in result.surfaces if item.definition == "action_new")
    assert (row.actor_scope, row.target_scope, row.operation, row.capability) == (
        "unknown",
        "unknown",
        "declared_field",
        "pending",
    )
    assert not row.scope_evidence


def test_d0_diplomatic_nested_or_flat_field_cannot_inherit_ai_consumer_contract() -> None:
    source = "common/diplomatic_actions/new.txt"
    definition = vanilla_inventory.parse_bytes(b"action = {}", path=source).top_assignments[0]
    inputs = {
        "common/diplomatic_actions/diplomatic_action.md": (
            b"In the AI block, the AI country is always root and the other country always "
            b"scope:target\naccept_score = {}\n"
        )
    }
    for field in [("ai", "accept_score", "unknown"), ("ai.accept_score",), ("accept_score",)]:
        scope = vanilla_inventory._scope(
            "diplomatic_actions", field, inputs, {}, definition, source
        )
        assert scope == vanilla_inventory._Scope()


def test_d0_scripted_definition_stays_pending_without_call_scope_evidence(tmp_path) -> None:
    game = _game(tmp_path)
    _write(game, "common/scripted_triggers/new.txt", "ai_can_act = { always = yes }\n")
    result = inventory.discover_vanilla(game=game)
    row = next(item for item in result.surfaces if item.definition == "ai_can_act")
    assert row.capability == "pending"
    assert row.getter is None
    assert row.status == "pending"
    assert result.legal_count == 4


def test_d0_ai_references_are_reported_separately_from_controllable_surfaces(tmp_path) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/journal_entries/ai_reference.txt",
        "entry = { trigger = { is_ai = yes } effect = { set_variable = { name = ai_route } } }\n",
    )
    result = inventory.discover_vanilla(game=game)
    references = [
        item
        for item in result.references
        if item.source == "common/journal_entries/ai_reference.txt"
    ]
    assert len(references) == 2
    assert {item.kind for item in references} == {"predicate", "state_variable"}
    assert all(item.status == "reference_only" for item in references)
    assert not any(
        item.source.endswith("journal_entries/ai_reference.txt") for item in result.surfaces
    )
    first = inventory.discover_vanilla(game=game)
    assert result.scope_hash == first.scope_hash


def test_d0_reference_occurrences_are_unique_and_comments_are_not_calls(tmp_path) -> None:
    game = _game(tmp_path)
    source = "common/journal_entries/references.txt"
    _write(
        game,
        source,
        "# ROOT.ai_commented(scope:country) is_ai = yes\n"
        "ai_entry = { trigger = { is_ai = yes is_ai = no } "
        'description = "[ROOT.ai_treaty_value(scope:source_country)] '
        '[ROOT.ai_treaty_value(scope:source_country)]" }\n',
    )
    first = inventory.discover_vanilla(game=game)
    second = inventory.discover_vanilla(game=game)
    refs = [item for item in first.references if item.source == source]
    assert len(refs) == 5
    assert len({item.reference_id for item in refs}) == 5
    assert all(item.line == 2 for item in refs)
    predicates = [item for item in refs if item.kind == "predicate"]
    assert {item.occurrence for item in predicates} == {1, 2}
    assert len({item.column for item in predicates}) == 2
    calls = [item for item in refs if item.kind == "script_call"]
    assert [item.expression for item in calls] == ["ai_treaty_value", "ai_treaty_value"]
    assert {item.occurrence for item in calls} == {1, 2}
    assert sum(item.kind == "declaration_reference" for item in refs) == 1
    assert not any(item.source == source for item in first.surfaces)
    assert first.references == second.references
    assert first.scope_hash == second.scope_hash


@pytest.mark.parametrize("directory", ["script_values", "scripted_triggers"])
def test_d0_script_definitions_and_references_do_not_prove_getters(tmp_path, directory) -> None:
    game = _game(tmp_path)
    _write(game, f"common/{directory}/new.txt", "ai_read = { value = scope:target.foo }\n")
    _write(
        game,
        "common/journal_entries/new.txt",
        'entry = { text = "[ROOT.ai_read(scope:country)]" }\n',
    )
    result = inventory.discover_vanilla(game=game)
    row = next(item for item in result.surfaces if item.definition == "ai_read")
    assert (row.capability, row.actor_scope, row.target_scope) == ("pending", "unknown", "unknown")
    assert row.getter is None
    assert not row.scope_evidence
    assert not row.legal
    assert row.responsibility_step == "D0.03"
    assert any(item.kind == "script_call" for item in result.references)


def test_d0_new_diplomatic_key_needs_field_contract_despite_known_container_scope(tmp_path) -> None:
    game = _game(tmp_path)
    _write(
        game, "common/diplomatic_actions/new.txt", "action_new = { ai = { invented_score = 2 } }\n"
    )
    _write(
        game,
        "common/diplomatic_actions/diplomatic_action.md",
        "In the AI block, the AI country is always root and the other country always scope:target\n",
    )
    result = inventory.discover_vanilla(game=game)
    row = next(item for item in result.surfaces if item.definition == "action_new")
    assert row.capability == "pending"
    assert row.actor_scope == "unknown"


def test_d0_treaty_field_scope_requires_exact_section_and_article_kind(tmp_path) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/treaty_articles/new.txt",
        "article_one = { kind = directed ai = { evaluation_chance = 1 "
        "inherent_accept_score = 1 treaty_categories = { trade } "
        "combined_acceptance_cap_max = 3 } }\n"
        "article_unknown = { ai = { inherent_accept_score = 2 } }\n",
    )
    _write(
        game,
        "common/treaty_articles/treaty_articles.md",
        "### evaluation_chance\nOnly has root scope for the country we're looking at.\n"
        "### inherent_accept_score\n"
        "- `root`: The country we're looking to check the acceptance on.\n"
        "- `scope:article`: The article in question with whatever inputs it might have\n"
        "There is no `scope:treaty` here\nONLY for mutual articles:\n"
        "- `scope:first_country` is one of the parties\n"
        "- `scope:second_country` is the other party\nONLY for directed articles:\n"
        "- `scope:source_country` is the specific party\n"
        "- `scope:target_country` is the specific party\n",
    )
    result = inventory.discover_vanilla(game=game)
    rows = {(item.definition, item.field): item for item in result.surfaces}
    evaluation = rows[("article_one", "ai.evaluation_chance")]
    assert (evaluation.actor_scope, evaluation.target_scope, evaluation.capability) == (
        "country",
        "none",
        "direct",
    )
    acceptance = rows[("article_one", "ai.inherent_accept_score")]
    assert acceptance.legal
    assert "scope:target_country=country" in acceptance.target_scope
    assert "scope:first_country" not in acceptance.target_scope
    assert acceptance.getter is None
    assert any("new.txt:1" in evidence for evidence in acceptance.scope_evidence)
    for key in (
        ("article_one", "ai.treaty_categories"),
        ("article_one", "ai.combined_acceptance_cap_max"),
        ("article_unknown", "ai.inherent_accept_score"),
    ):
        assert rows[key].capability == "pending"
        assert not rows[key].legal
    doc = game / "common/treaty_articles/treaty_articles.md"
    doc.write_text(
        doc.read_text(encoding="utf-8").replace("### evaluation_chance", "### unrelated"),
        encoding="utf-8",
        newline="\n",
    )
    result = inventory.discover_vanilla(game=game)
    evaluation = next(item for item in result.surfaces if item.field == "ai.evaluation_chance")
    assert evaluation.capability == "pending"
    assert evaluation.responsibility_step == "D0.03"


def test_d0_treaty_metadata_and_acceptance_caps_are_observation_not_country_control(
    tmp_path,
) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/treaty_articles/new.txt",
        "article_one = { kind = directed ai = { treaty_categories = { trade } "
        "article_ai_usage = { economy } combined_acceptance_cap_max = 3 "
        "combined_acceptance_cap_min = 1 } }\n",
    )
    _write(
        game,
        "common/treaty_articles/treaty_articles.md",
        "treaty_categories = { # Categories exist for AI evaluations\n}\n"
        "article_ai_usage = { # AI filter metadata\n}\n"
        "combined_acceptance_cap_max = value\n"
        "combined_acceptance_cap_min = value\n",
    )
    result = inventory.discover_vanilla(game=game)
    rows = [item for item in result.surfaces if item.definition == "article_one"]
    assert {item.field for item in rows} == {
        "ai.treaty_categories",
        "ai.article_ai_usage",
        "ai.combined_acceptance_cap_max",
        "ai.combined_acceptance_cap_min",
    }
    for row in rows:
        assert (row.actor_scope, row.target_scope, row.capability, row.operation) == (
            "global",
            "none",
            "observation",
            "ai_metadata" if "cap" not in row.field else "acceptance_cap",
        )
        assert not row.legal


def test_d0_diplomatic_play_acceptance_cap_without_consumer_scope_is_observation(
    tmp_path,
) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/diplomatic_plays/new.txt",
        "play_new = { ai_acceptance_max = 75 }\n",
    )
    _write(
        game,
        "common/diplomatic_plays/diplomatic_plays.md",
        "ai_acceptance_max = num # upper bound for AI acceptance\n"
        "we use initiator as a root scope\n",
    )
    result = inventory.discover_vanilla(game=game)
    row = next(item for item in result.surfaces if item.definition == "play_new")
    assert (row.actor_scope, row.target_scope, row.capability, row.operation) == (
        "global",
        "none",
        "observation",
        "acceptance_cap",
    )
    assert not row.legal


def test_d0_ship_category_and_stance_capability_metadata_is_observation(tmp_path) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/ship_types/new.txt",
        "ship_new = { ai_ship_category = ai_ship_category_test }\n",
    )
    _write(
        game,
        "common/ship_types/ship_types.md",
        "# Which AI-only category the ship type belongs to\n"
        "ai_ship_category = <ai ship category key>\n"
        "# used by the AI\n",
    )
    _write(
        game,
        "common/ai_strategic_region_stance_types/new.txt",
        "stance_new = { can_send_fleets = yes }\n",
    )
    _write(
        game,
        "common/ai_strategic_region_stance_types/ai_strategic_region_stance_types.md",
        "strategic_region_stance_type = {\ncan_send_fleets = <yes/no>\n}\n",
    )
    result = inventory.discover_vanilla(game=game)
    ship = next(item for item in result.surfaces if item.definition == "ship_new")
    stance = next(item for item in result.surfaces if item.definition == "stance_new")
    assert (ship.actor_scope, ship.target_scope, ship.capability, ship.operation) == (
        "global",
        "none",
        "observation",
        "ai_metadata",
    )
    assert (stance.actor_scope, stance.target_scope, stance.capability, stance.operation) == (
        "global",
        "none",
        "observation",
        "stance_capability",
    )
    assert not ship.legal
    assert not stance.legal


def test_d0_parse_error_in_any_related_definition_hard_fails(tmp_path) -> None:
    game = _game(tmp_path)
    _write(game, "common/laws/broken.txt", "law_broken = { group = something\n")
    with pytest.raises(ValueError, match=r"broken\.txt"):
        inventory.discover_vanilla(game=game)


def test_d0_installed_dlc_in_game_common_definition_is_discovered_independently(tmp_path) -> None:
    game = _game(tmp_path)
    _write(game, "dlc/new/new.dlc", 'name = "New DLC" path = "dlc/new"\n')
    _write(
        game,
        "dlc/new/in_game/common/laws/new.txt",
        "law_dlc = { ai_enact_weight_modifier = 1 }\n",
    )
    result = inventory.discover_vanilla(game=game)
    assert result.discovered_count == 5
    row = next(item for item in result.surfaces if item.definition == "law_dlc")
    assert row.source == "dlc/new/in_game/common/laws/new.txt"
    assert row.status == "pending"
    assert "dlc/new/in_game/common" in result.content_roots
    assert "dlc/new/new.dlc" in result.source_hashes
    assert result.as_dict()["activation_policy"] == "all_installed_content_not_runtime_activation"


def test_d0_malformed_dlc_definition_hard_fails(tmp_path) -> None:
    game = _game(tmp_path)
    _write(game, "dlc/new/new.dlc", 'name = "New DLC" path = "dlc/new"\n')
    _write(game, "dlc/new/common/laws/broken.txt", "law_broken = {\n")
    with pytest.raises(ValueError, match=r"dlc/new/common/laws/broken\.txt"):
        inventory.discover_vanilla(game=game)


def test_d0_unread_archive_mount_is_explicit_failure(tmp_path) -> None:
    game = _game(tmp_path)
    _write(game, "dlc/new/new.dlc", 'name = "New DLC" archive = "dlc/new/content.zip"\n')
    with pytest.raises(ValueError, match="archive"):
        inventory.discover_vanilla(game=game)


def test_d0_descriptor_mounted_content_outside_dlc_folder_is_discovered(tmp_path) -> None:
    game = _game(tmp_path)
    _write(game, "dlc/new/new.dlc", 'name = "New DLC" path = "mounted/new"\n')
    _write(
        game, "mounted/new/common/laws/new.txt", "law_mounted = { ai_enact_weight_modifier = 1 }\n"
    )
    result = inventory.discover_vanilla(game=game)
    assert result.discovered_count == 5
    assert "mounted/new/common" in result.content_roots


def test_d0_missing_descriptor_mounted_directory_is_explicit_failure(tmp_path) -> None:
    game = _game(tmp_path)
    _write(game, "dlc/new/new.dlc", 'name = "New DLC" path = "missing/new"\n')
    with pytest.raises(ValueError, match="missing/new"):
        inventory.discover_vanilla(game=game)


@pytest.mark.parametrize(
    "mount",
    [
        "../outside",
        "mounted/../../outside",
        "/outside",
        "C:/outside",
        "C:outside",
        r"\\server\share",
        r"mounted\new",
    ],
)
def test_d0_dlc_mount_rejects_nonportable_or_escaping_paths(tmp_path, mount) -> None:
    game = _game(tmp_path)
    _write(game, "dlc/new/new.dlc", f'path = "{mount}"\n')
    with pytest.raises(ValueError, match="相对路径"):
        inventory.discover_vanilla(game=game)


def test_d0_dlc_only_scans_declared_mount_common_trees(tmp_path) -> None:
    game = _game(tmp_path)
    _write(game, "dlc/new/new.dlc", 'path = "mounted/new"\n')
    _write(
        game, "mounted/new/common/laws/new.txt", "law_mounted = { ai_enact_weight_modifier = 1 }\n"
    )
    _write(
        game,
        "mounted/new/in_game/common/laws/new.txt",
        "law_in_game = { ai_enact_weight_modifier = 2 }\n",
    )
    for relative in (
        "dlc/unmounted/common/laws/new.txt",
        "mounted/new/unmounted/common/laws/new.txt",
        "mounted/neighbor/common/laws/new.txt",
    ):
        _write(game, relative, "malformed_unmounted = {\n")
    result = inventory.discover_vanilla(game=game)
    assert result.discovered_count == 6
    assert set(result.content_roots) == {
        "common",
        "mounted/new/common",
        "mounted/new/in_game/common",
    }
    assert not any("unmounted" in source or "neighbor" in source for source in result.source_hashes)


def _symlink(link: Path, target: Path, *, directory: bool) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        pytest.skip(f"本机不支持创建符号链接：{exc}")


@pytest.mark.parametrize("escape", [False, True])
def test_d0_dlc_symlink_mount_cannot_alias_or_escape_locked_tree(tmp_path, escape) -> None:
    game = _game(tmp_path)
    target = tmp_path / "outside" if escape else game / "mounted"
    _write(target, "common/laws/new.txt", "law_linked = { ai_enact_weight_modifier = 1 }\n")
    link = game / "linked"
    _symlink(link, target, directory=True)
    _write(game, "dlc/new/new.dlc", 'path = "linked"\n')
    with pytest.raises(ValueError, match=r"锁定树|符号链接"):
        inventory.discover_vanilla(game=game)


def test_d0_input_alias_check_rejects_symlink_without_creating_one(tmp_path, monkeypatch) -> None:
    game = _game(tmp_path)
    mount = game / "mounted"
    mount.mkdir()
    from pdx.situated import vanilla_inventory

    monkeypatch.setattr(Path, "is_symlink", lambda self: self == mount)
    with pytest.raises(ValueError, match="符号链接"):
        vanilla_inventory._contained(game, mount)


@pytest.mark.parametrize("directory", [False, True])
def test_d0_mounted_common_rejects_symlink_inputs(tmp_path, directory) -> None:
    game = _game(tmp_path)
    _write(game, "dlc/new/new.dlc", 'path = "mounted/new"\n')
    common = game / "mounted/new/common"
    common.mkdir(parents=True)
    target = tmp_path / "external"
    _write(target, "new.txt", "law_external = { ai_enact_weight_modifier = 1 }\n")
    if directory:
        _symlink(common / "laws", target, directory=True)
    else:
        (common / "laws").mkdir()
        _symlink(common / "laws/new.txt", target / "new.txt", directory=False)
    with pytest.raises(ValueError, match=r"锁定树|符号链接"):
        inventory.discover_vanilla(game=game)


def test_d0_duplicate_declarations_keep_both_occurrences_and_explicit_unknown_merge(
    tmp_path,
) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/laws/duplicate.txt",
        "law_duplicate = { ai_enact_weight_modifier = 1 ai_enact_weight_modifier = 2 }\n",
    )
    result = inventory.discover_vanilla(game=game)
    rows = [item for item in result.surfaces if item.definition == "law_duplicate"]
    assert len(rows) == 2
    assert len({item.surface_id for item in rows}) == 2
    assert {item.declaration_occurrence for item in rows} == {1, 2}
    assert all(item.ambiguity == "duplicate_field_merge_semantics_unknown" for item in rows)
    assert all(item.capability == "pending" for item in rows)
    assert all(item.responsibility_step == "D0.03" for item in rows)


def test_d0_repeated_define_namespaces_keep_distinct_global_ai_parameters(tmp_path) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/defines/00_defines.txt",
        "NPops = { A = 1 } NPops = { B = 2 } "
        "NAI = { FIRST_PARAMETER = 3 } NAI = { SECOND_PARAMETER = 4 }\n",
    )
    result = inventory.discover_vanilla(game=game)
    rows = [item for item in result.surfaces if item.definition == "NAI"]
    assert {item.field for item in rows} == {"FIRST_PARAMETER", "SECOND_PARAMETER"}
    assert all(item.capability == "observation" for item in rows)
    assert all(item.actor_scope == "global" for item in rows)
    assert all(not item.legal for item in rows)
    assert all("不是国家脚本 getter" in item.getter_note for item in rows)


def test_d0_wrong_game_version_is_rejected(tmp_path) -> None:
    game = _game(tmp_path)
    _write(tmp_path, "caligula_branch.txt", "release/1.15.0\n")
    with pytest.raises(ValueError, match=r"1\.14\.5"):
        inventory.discover_vanilla(game=game)


def test_d0_missing_version_fingerprint_file_hard_fails(tmp_path) -> None:
    game = _game(tmp_path)
    (tmp_path / "caligula_rev.txt").unlink()
    with pytest.raises(ValueError, match="caligula_rev"):
        inventory.discover_vanilla(game=game)


def test_d0_discovery_is_deterministic_and_serializable_without_changing_legacy_scope(
    tmp_path,
) -> None:
    game = _game(tmp_path)
    first = inventory.discover_vanilla(game=game)
    second = inventory.discover_vanilla(game=game)
    assert first.scope_hash == second.scope_hash
    payload = json.loads(json.dumps(first.as_dict()))
    assert payload["discovered_count"] == 4
    assert payload["migration_denominator"] == 1401
    assert payload["status_counts"] == {"pending": 4}
    assert "common/laws/untouched.txt" in payload["source_hashes"]
    assert first.parse_failures == ()
    assert payload["parse_failures"] == list(first.parse_failures)
    assert payload["unknown_scopes"] == list(first.unknown_scopes)


def test_d0_unknown_scope_receipt_covers_each_missing_scope_component(tmp_path) -> None:
    game = _game(tmp_path)
    _write(
        game, "common/unknown_surface/new.txt", "new_action = { ai_new = { invented_score = 1 } }\n"
    )
    result = inventory.discover_vanilla(game=game)
    row = next(item for item in result.surfaces if item.definition == "new_action")
    assert row.actor_scope == "unknown"
    assert row.target_scope == "unknown"
    assert row.operation == "declared_field"
    assert not row.scope_evidence
    assert row.surface_id in result.unknown_scopes
    assert row.surface_id in result.as_dict()["unknown_scopes"]


def test_d0_strategy_reader_rejects_partial_parse_instead_of_returning_partial_cards(
    tmp_path,
) -> None:
    game = _game(tmp_path)
    _write(
        game, "common/ai_strategies/broken.txt", "ai_strategy_broken = { weight = { value = 1 }\n"
    )
    with pytest.raises(ValueError, match=r"broken\.txt"):
        ai_surface.read_cards(game)


def test_d0_strategy_reader_includes_nested_active_strategy_definitions(tmp_path) -> None:
    cards = ai_surface.read_cards(_game(tmp_path))
    assert {item.name for item in cards} == {"ai_strategy_default", "ai_strategy_active"}


def test_d0_strategy_reader_rejects_nested_partial_parse(tmp_path) -> None:
    game = _game(tmp_path)
    _write(game, "common/ai_strategies/nested/broken.txt", "ai_strategy_broken = {\n")
    with pytest.raises(ValueError, match=r"nested/broken\.txt"):
        ai_surface.read_cards(game)


@pytest.mark.parametrize(
    ("directory", "definition", "doc_name", "doc"),
    [
        (
            "company_types",
            (
                "company_new = { potential = { always = yes } attainable = { always = yes } "
                "possible = { always = yes } ai_will_do = { always = yes } ai_weight = 1 "
                "ai_construction_targets = { building_new = { level = 5 "
                "state_trigger = { state_region = s:STATE_NEW } } } }\n"
            ),
            "companies.md",
            (
                "# The following three triggers are evaluated in country scope.\n"
                "potential = {} attainable = {} possible = {}\n"
                "ai_will_do = { # If this trigger is true, the AI may form the company\n}\n"
                "# increased weight for certain building types in certain states\n"
                "ai_construction_targets = { building_new = { level = 5 state_trigger = {} } }\n"
                "ai_weight = {}\n"
            ),
        ),
        (
            "company_charter_types",
            "charter_new = { ai_possible = { always = yes } ai_weight = 1 }\n",
            "company_charter_types.md",
            (
                "possible = {} # A trigger evaluated in company scope\n"
                "ai_possible = {} # If this charter is possible to be picked up by AI\n"
                "ai_weight = {} # Check score for AI to pickup charter\n"
            ),
        ),
        (
            "production_method_groups",
            "pmg_new = { ai_selection = most_productive }\n",
            "production_method_groups.md",
            "ai_selection = most_productive # Affects how the AI chooses between PMs\n",
        ),
        (
            "naval_mission_types",
            (
                "mission_new = { ai_will_cancel_for_transportation = yes "
                "ai_distance_penalty_multiplier = 1 }\n"
            ),
            "naval_mission_types.md",
            "ai_will_do = {} # Trigger to enable/disable this for ai\nai_weight = {}\n",
        ),
        (
            "war_goal_types",
            "war_goal_new = { ai = { is_significant_demand = yes settles_grievance = no } }\n",
            "war_goal_types.md",
            (
                "ai = { is_significant_demand = yes settles_grievance = no }\n"
                "## Triggers and Effect\n### Scope\n"
                "For all of the following the same scopes are available:\n"
                "- root (holder country)\n- target_country\n- target_state\n"
                "### Possible trigger\nThis determines whether the war goal is listed.\n"
            ),
        ),
    ],
)
def test_d0_explicit_documentation_proves_documented_ai_scope(
    tmp_path, directory, definition, doc_name, doc
) -> None:
    game = _game(tmp_path)
    _write(game, f"common/{directory}/new.txt", definition)
    _write(game, f"common/{directory}/{doc_name}", doc)
    result = inventory.discover_vanilla(game=game)
    rows = [item for item in result.surfaces if item.source == f"common/{directory}/new.txt"]
    assert rows
    if directory == "company_types":
        by_field = {row.field: row for row in rows}
        assert by_field["ai_will_do"].capability == "pending"
        assert by_field["ai_will_do"].actor_scope == "unknown"
        assert by_field["ai_will_do"].target_scope == "unknown"
        assert not by_field["ai_will_do"].legal
        assert by_field["ai_weight"].capability == "pending"
        assert by_field["ai_weight"].surface_id in result.unknown_scopes
        construction = [row for row in rows if row.field.startswith("ai_construction_targets.")]
        assert construction
        assert all(row.actor_scope == "unknown" for row in construction)
        assert all(row.target_scope == "unknown" for row in construction)
        assert all(row.capability == "pending" and not row.legal for row in construction)
        return
    if directory == "company_charter_types":
        assert {row.field for row in rows} == {"ai_possible", "ai_weight"}
        assert all(row.capability == "pending" for row in rows)
        assert all(not row.legal for row in rows)
        assert all(row.actor_scope == "unknown" for row in rows)
        assert all(row.target_scope == "unknown" for row in rows)
        return
    if directory == "production_method_groups":
        row = rows[0]
        assert row.field == "ai_selection"
        assert row.capability == "pending"
        assert row.actor_scope == "unknown"
        assert row.target_scope == "unknown"
        assert row.surface_id in result.unknown_scopes
        return
    if directory == "war_goal_types":
        assert {row.field for row in rows} == {
            "ai.is_significant_demand",
            "ai.settles_grievance",
        }
        assert all(row.capability == "pending" for row in rows)
        assert all(row.actor_scope == "unknown" for row in rows)
        assert all(row.target_scope == "unknown" for row in rows)
        assert all(row.surface_id in result.unknown_scopes for row in rows)
        return
    for row in rows:
        assert row.capability == "pending"
        assert not row.legal
        assert row.actor_scope == "unknown"
        assert row.target_scope == "unknown"
        assert row.getter is None
        assert row.responsibility_step == "D0.03"
        assert row.surface_id in result.unknown_scopes


def test_d0_ship_modification_root_does_not_invent_a_target_scope(tmp_path) -> None:
    game = _game(tmp_path)
    _write(game, "common/ship_modifications/new.txt", "ship_mod_new = { ai_weight = 1 }\n")
    _write(
        game,
        "common/ship_modifications/ship_modifications.md",
        "# How important is this ship type to build for AI\n# root - country\n"
        "ai_weight = fixed_point\n",
    )
    result = inventory.discover_vanilla(game=game)
    row = next(item for item in result.surfaces if item.definition == "ship_mod_new")
    assert row.actor_scope == "country"
    assert row.target_scope == "unknown"
    assert row.operation == "score"
    assert row.capability == "pending"
    assert row.scope_evidence
    assert not row.legal
    assert row.responsibility_step == "D0.03"
    assert row.surface_id in result.unknown_scopes


def test_d0_country_rank_pool_multiplier_uses_its_explicit_template_contract(tmp_path) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/country_ranks/00_country_ranks.txt",
        "# ai_pool_character_multiplier = Multiplier on how many randomly generated pool characters "
        "an AI country of this rank will get.\n"
        "great_power = { ai_pool_character_multiplier = 1.0 }\n",
    )
    result = inventory.discover_vanilla(game=game)
    row = next(
        item
        for item in result.surfaces
        if item.source == "common/country_ranks/00_country_ranks.txt"
        and item.field == "ai_pool_character_multiplier"
    )
    assert (row.actor_scope, row.target_scope, row.operation, row.capability) == (
        "country",
        "none",
        "multiplier",
        "indirect",
    )
    assert row.scope_evidence
    assert row.legal
    assert row.responsibility_step == "D4.06"


def test_d0_country_rank_innovation_threshold_stays_pending_without_field_contract(
    tmp_path,
) -> None:
    game = _game(tmp_path)
    _write(
        game,
        "common/country_ranks/00_country_ranks.txt",
        "great_power = { ai_innovation_critical_threshold = 1.0 }\n",
    )
    result = inventory.discover_vanilla(game=game)
    row = next(
        item
        for item in result.surfaces
        if item.source == "common/country_ranks/00_country_ranks.txt"
        and item.field == "ai_innovation_critical_threshold"
    )
    assert (row.actor_scope, row.target_scope, row.operation, row.capability) == (
        "unknown",
        "unknown",
        "declared_field",
        "pending",
    )
    assert not row.legal


@pytest.mark.parametrize(
    ("field", "value"), [("invented_score", "1"), ("on_invented", "{}"), ("weight", "1")]
)
def test_d0_regional_objective_header_needs_the_exact_field_declaration(
    tmp_path, field, value
) -> None:
    game = _game(tmp_path)
    _write(
        game, "common/ai_regional_objectives/new.txt", f"objective_new = {{ {field} = {value} }}\n"
    )
    _write(
        game,
        "common/ai_regional_objectives/ai_regional_objectives.md",
        "### root = the AI country\n"
        "### scope:target_region = the strategic region the objective applies to\n"
        "### scope:target_stance = the regional stance being drawn for\n"
        "objective = { possible = { <trigger> } }\n",
    )
    result = inventory.discover_vanilla(game=game)
    row = next(item for item in result.surfaces if item.definition == "objective_new")
    assert row.capability == "pending"
    assert not row.legal
    assert row.surface_id in result.unknown_scopes


@pytest.mark.parametrize(
    ("field", "declaration", "operation", "capability"),
    [
        ("possible", "possible = { <trigger> }", "predicate", "direct"),
        ("complete", "complete = { <trigger> }", "predicate", "direct"),
        ("invalid", "invalid = { <trigger> }", "predicate", "direct"),
        ("weight", "weight = <script value>", "relative_weight", "direct"),
        ("on_create", "on_create = { <effect> }", "effect", "indirect"),
        ("on_complete", "on_complete = { <effect> }", "effect", "indirect"),
        ("on_invalid", "on_invalid = { <effect> }", "effect", "indirect"),
        ("stances", "stances = { stance_key ... }", "declared_field", "pending"),
    ],
)
def test_d0_regional_objective_operations_follow_the_field_contract(
    tmp_path, field, declaration, operation, capability
) -> None:
    game = _game(tmp_path)
    _write(game, "common/ai_regional_objectives/new.txt", f"objective_new = {{ {field} = {{}} }}\n")
    _write(
        game,
        "common/ai_regional_objectives/ai_regional_objectives.md",
        "### root = the AI country\n"
        "### scope:target_region = the strategic region the objective applies to\n"
        "### scope:target_stance = the regional stance being drawn for\n"
        f"objective = {{ {declaration} }}\n",
    )
    result = inventory.discover_vanilla(game=game)
    row = next(item for item in result.surfaces if item.definition == "objective_new")
    assert (row.operation, row.capability) == (operation, capability)
    assert row.legal is (capability != "pending")
