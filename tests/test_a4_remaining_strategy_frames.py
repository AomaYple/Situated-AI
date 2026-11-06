"""Exact accepted country frames; definition keys never become live targets."""

from dataclasses import replace

import pytest

from pdx.decision_rules import Reader
from pdx.situated import compiler, decision_ir
from pdx.situated import strategy_candidate_frames as frames


def test_revolution_context_uses_existing_override_member_evidence():
    context = compiler._frozen_strategy_contexts()["revolution_aversion"]
    assert context.actor_scope is not None
    assert context.actor_scope.name == "root"
    assert context.actor_scope.kind == "country"
    assert not context.targets
    assert not context.auxiliary_scopes
    assert any("consumer=revolution_aversion:va=0x141828ecd" in row for row in context.evidence)


@pytest.mark.parametrize("definition", sorted(frames.WEIGHT_DEFINITIONS))
def test_exact_strategy_definition_weight_keeps_country_root(definition):
    source = (
        "common/ai_strategies/01_admin_strategies.txt"
        if definition.endswith("expansion")
        else "common/ai_strategies/02_subject_diplomatic_strategies.txt"
    )
    context = frames.strategy_weight_context(source, definition)
    reader = Reader("war", "is_at_war", "root", "boolean", "boolean")
    bound = compiler.validate_context_readers(
        "strategy.weight", context, {"war": reader}, (), input_keys=("war",), source=source
    )
    assert bound == (("war", "root", "country", "actor"),)
    assert not context.targets
    assert not context.auxiliary_scopes


@pytest.mark.parametrize("field", sorted(frames.SHIP_FIELDS))
@pytest.mark.parametrize("change", ["source", "field", "target", "actor", "owner"])
def test_ship_category_rejects_source_field_live_target_actor_and_owner(change, field):
    context = frames.ship_category_context(field)
    source = "common/ai_strategies/00_default_strategy.txt"
    field = field.removeprefix("ai_strategy_default.")
    actor_path: tuple[str, ...] = ()
    if change == "source":
        source = "common/ai_strategies/01_admin_strategies.txt"
    if change == "field":
        field = "ai_ship_category_weights.ai_ship_category_decoy"
    if change == "target":
        context = replace(
            context,
            targets=(
                decision_ir.ContextBinding("target_country", "country", "target", "fixture", 1),
            ),
            evidence=(*context.evidence, "fixture:1"),
        )
    if change == "actor":
        assert context.actor_scope is not None
        context = replace(context, actor_scope=replace(context.actor_scope, kind="state"))
    if change == "owner":
        actor_path = ("owner",)
    with pytest.raises(ValueError):
        compiler.validate_context_readers(
            field, context, {}, (), source=source, actor_path=actor_path
        )


@pytest.mark.parametrize("definition", ["ai_strategy_arbitrary", "ai_strategy_default"])
def test_weight_whitelist_cannot_authorize_arbitrary_definitions(definition):
    with pytest.raises(ValueError, match="白名单"):
        frames.strategy_weight_context("common/ai_strategies/01_admin_strategies.txt", definition)


def test_weight_exact_definition_cannot_move_to_other_strategy_type():
    with pytest.raises(ValueError, match="来源"):
        frames.strategy_weight_context(
            "common/ai_strategies/02_subject_diplomatic_strategies.txt",
            "ai_strategy_agricultural_expansion",
        )
