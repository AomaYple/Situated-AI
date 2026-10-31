"""D0 独立原版分母：发现、作用域证据和拒错合同。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdx import ai_surface
from pdx.situated import inventory

pytestmark = pytest.mark.unit


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
        "institution_scores.institution_education",
        "institution_scores.institution_health_system",
    }


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
