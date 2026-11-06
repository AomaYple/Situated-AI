"""Real custom-program lowering, complete original AST and exact typed frames."""

from dataclasses import replace

import pytest

from pdx import regional_resource_opportunities as regional
from pdx import treaty_acceptance_opportunities as acceptance
from pdx.situated import compiler, fleet_mission_frame, ports


@pytest.mark.parametrize("program", [*acceptance.compile_programs(), regional.compile_program()])
def test_program_guards_have_actual_graph_uses_and_exact_causal_groups(program):
    bound = program.predicate_ports()
    contract = bound.as_dict()
    assert contract["guards"]
    assert all(
        use.source == program.source and use.definition == program.definition
        for use in bound.graph.uses
    )
    expected = {group.id for group in program.scalar.groups}
    assert {use.relation_cause for use in bound.graph.uses} == expected
    writer = program.writer_ir()
    assert writer.port_contributions == bound.contributions(replace(writer, port_contributions=()))
    assert {row.causal_id for row in writer.port_contributions} == expected
    assert all(row.origins for row in writer.port_contributions)
    assert all(
        origin.observation.roles for _, origins in bound.graph.origin_rows for origin in origins
    )
    validator = (
        writer.validate_acceptance_program
        if writer.kind == "acceptance_program"
        else writer.validate_regional_resource_program
    )
    assert validator() is program
    changed = replace(writer, port_contributions=())
    with pytest.raises(ValueError, match=r"身份|完整语义"):
        (
            changed.validate_acceptance_program
            if writer.kind == "acceptance_program"
            else changed.validate_regional_resource_program
        )()
    for _, pid in bound.guards:
        bound.graph.validate_origins(pid)
        assert bound.graph.guard(program.source, program.definition, pid).when_true


def test_exact_wanted_army_and_definition_only_strategy_frames():
    frames = compiler._frozen_strategy_contexts()
    for field in ("wanted_army_size", "weight"):
        context = frames[field]
        assert context.actor_scope is not None
        assert (context.actor_scope.name, context.actor_scope.kind, context.actor_scope.role) == (
            "root",
            "country",
            "actor",
        )
        assert context.targets == context.auxiliary_scopes == ()
    assert any("definition_only:ai_strategy" in row for row in frames["weight"].evidence)
    fleet = fleet_mission_frame.frozen_context()
    assert fleet.actor_scope is not None
    assert fleet.actor_scope.name == "root"
    assert not fleet.targets
    assert not fleet.auxiliary_scopes


def test_article_input_alias_is_exact_and_never_a_guessed_named_scope():
    program = acceptance.compile_program("no_tariffs")
    guards = program.port_guards()
    assert '"scope:article.input_market_goods(root)"' in guards["target_input_need"]
    assert "scope:article_input_market_goods" not in guards["target_input_need"]
    reader = next(row for row in program.readers() if row.key == "acceptance_delta")
    with pytest.raises(ValueError, match="精确现有delta"):
        ports._scoped(replace(reader, engine="net_total_income"), "net_total_income < 0")


def test_normal_compiler_assigns_all_three_previously_missing_exact_contexts():
    model = compiler.load_model()
    expected = {
        ("mod/decisions/information.toml", "wanted_army_size"),
        (
            "common/ai_strategies/00_default_strategy.txt",
            "ai_strategy_default.fleet_compositions.secondary_fleet.mission_type_weights.protect_supply",
        ),
        (
            "common/ai_strategies/02_subject_diplomatic_strategies.txt",
            "ai_strategy_subject_overlord_compliance.weight",
        ),
    }
    actual = set()
    assert model.consumer_ir is not None
    for writer in model.consumer_ir.writers:
        if (writer.source, writer.field) not in expected:
            continue
        actual.add((writer.source, writer.field))
        context = writer.evaluation_context
        assert context is not None
        assert context.actor_scope is not None
        assert context.status == "observed"
        assert context.actor_scope.name == "root"
        assert not context.targets
        assert not context.auxiliary_scopes
        assert writer.reader_context_bindings
    assert actual == expected


@pytest.mark.parametrize("definition", tuple(acceptance.COMMITMENTS))
def test_existing_or_unknown_query_and_independent_recovery_are_local(definition):
    program = acceptance.compile_program(definition)
    bound = program.predicate_ports()
    values = {
        "commitment_active_exists": False,
        "commitment_renegotiation_exists": False,
        "commitment_existing": False,
        "commitment_default": True,
        "commitment_income": None,
        "commitment_defeat": True,
    }
    assert bound.evaluate(values) == {
        "commitment_default": True,
        "commitment_deficit": False,
        "commitment_recovery": True,
    }
    for key in (
        "commitment_existing",
        "commitment_active_exists",
        "commitment_renegotiation_exists",
    ):
        assert not any(bound.evaluate({**values, key: None}).values())
        assert not any(bound.evaluate({**values, key: True}).values())
    for key in ("commitment_default", "commitment_defeat"):
        result = bound.evaluate({**values, key: None})
        assert result[
            "commitment_recovery" if key == "commitment_default" else "commitment_default"
        ]
