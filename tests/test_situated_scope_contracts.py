"""D0 字段级 operation 证据：部分合同可记录，作用域缺失仍保持 pending。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pdx.situated import inventory

if TYPE_CHECKING:
    from pathlib import Path


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _game(tmp_path: Path) -> Path:
    game = tmp_path / "game"
    _write(tmp_path, "caligula_branch.txt", "release/1.14.5\n")
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
