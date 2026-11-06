"""Explicit causal roles, fail-closed declarations, and exact original-value checks."""

from dataclasses import replace

import pytest

from pdx import regional_resource_opportunities as regional
from pdx import treaty_acceptance_opportunities as acceptance
from pdx.situated import program_ports

PROGRAMS = [*acceptance.compile_programs(), regional.compile_program()]
EXPECTED = {
    **{
        name: {
            "commitment_default": "cost",
            "commitment_deficit": "cost",
            "commitment_recovery": "cost",
        }
        for name in acceptance.COMMITMENTS
    },
    "military_assistance": {"military_source_default": "cost", "military_source_deficit": "cost"},
    "no_tariffs": {
        "source_tariff_commitment": "cost",
        "source_cheap": "cost",
        "source_deficit": "cost",
        "target_input_need": "benefit",
    },
    regional.ACTION: {regional.ACTION: "benefit"},
}


def arguments(program, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(program_ports, "bind", lambda **kwargs: kwargs)
        return program.predicate_ports()


@pytest.mark.parametrize("program", PROGRAMS, ids=lambda p: p.definition)
def test_all_actual_guards_have_exact_explicit_roles_and_ordinary_unknown(program):
    bound = program.predicate_ports()
    expected = EXPECTED[program.definition]
    assert dict(bound.guard_roles) == expected
    assert set(dict(bound.guards)) == set(expected)
    assert bound.as_dict()["guard_roles"] == expected
    assert all(use.role == "condition" for use in bound.graph.uses)
    assert all(
        bound.graph.guard(program.source, program.definition, pid).unknown_policy == "vanilla"
        for _, pid in bound.guards
    )
    writer = program.writer_ir()
    by_port = {pid: expected[key] for key, pid in bound.guards}
    assert tuple(row.semantic_role for row in writer.port_contributions) == tuple(
        by_port[use.port] for use in bound.graph.writer_uses(program.source, program.definition)
    )
    assert {row.causal_id for row in writer.port_contributions} == {
        group.id for group in program.scalar.groups
    }


@pytest.mark.parametrize("program", PROGRAMS, ids=lambda p: p.definition)
def test_term_effect_sign_and_neutral_cannot_change_declared_roles(program, monkeypatch):
    kwargs = arguments(program, monkeypatch)
    groups = tuple(
        replace(
            group,
            terms=tuple(
                replace(
                    term,
                    amount=(-999.0 if index % 2 else 777.0),
                    effects=tuple(
                        replace(effect, amount=(-33.0 if eidx % 2 else 88.0), otherwise=12.0)
                        for eidx, effect in enumerate(term.effects)
                    ),
                )
                for index, term in enumerate(group.terms)
            ),
        )
        for group in program.scalar.groups
    )
    scalar = replace(program.scalar, neutral=12345.0, groups=groups)
    assert (
        dict(program_ports.bind(**{**kwargs, "scalar": scalar}).guard_roles)
        == EXPECTED[program.definition]
    )


@pytest.mark.parametrize("bad", ["missing", "extra", "invalid", "unhashable"])
def test_incomplete_or_invalid_role_declaration_rejects(bad, monkeypatch):
    kwargs = arguments(acceptance.compile_program("no_tariffs"), monkeypatch)
    roles = dict(kwargs["guard_roles"])
    if bad == "missing":
        del roles["source_deficit"]
    elif bad == "extra":
        roles["extra"] = "cost"
    elif bad == "invalid":
        roles["source_cheap"] = "opportunity"
    else:
        roles["source_cheap"] = []
    with pytest.raises(ValueError, match="显式semantic role"):
        program_ports.bind(**{**kwargs, "guard_roles": roles})


def test_equal_predicate_port_with_conflicting_roles_rejects(monkeypatch):
    program = regional.compile_program()
    kwargs = arguments(program, monkeypatch)
    term = program.scalar.groups[0].terms[0]
    duplicate = replace(term, id="same_predicate_other_role", action_id="same_predicate_other_role")
    scalar = replace(
        program.scalar, groups=(replace(program.scalar.groups[0], terms=(term, duplicate)),)
    )
    with pytest.raises(ValueError, match="冲突semantic role"):
        program_ports.bind(
            **{
                **kwargs,
                "scalar": scalar,
                "predicates": {
                    **kwargs["predicates"],
                    duplicate.id: kwargs["predicates"][regional.ACTION],
                },
                "guard_roles": {regional.ACTION: "benefit", duplicate.id: "cost"},
            }
        )


def test_same_guard_reused_across_unequal_groups_rejects(monkeypatch):
    program = regional.compile_program()
    kwargs = arguments(program, monkeypatch)
    base = program.scalar.groups[0]
    scalar = replace(program.scalar, groups=(base, replace(base, id="different_cause")))
    with pytest.raises(ValueError, match="不等价因果组"):
        program_ports.bind(**{**kwargs, "scalar": scalar})


@pytest.mark.parametrize("amount", [-5.0, 0.0, 9.0])
def test_unspecified_remains_unspecified_for_every_sign(amount, monkeypatch):
    program = regional.compile_program()
    kwargs = arguments(program, monkeypatch)
    group = program.scalar.groups[0]
    scalar = replace(
        program.scalar, groups=(replace(group, terms=(replace(group.terms[0], amount=amount),)),)
    )
    bound = program_ports.bind(
        **{**kwargs, "scalar": scalar, "guard_roles": {regional.ACTION: "unspecified"}}
    )
    assert bound.guard_roles == ((regional.ACTION, "unspecified"),)
    assert {row.semantic_role for row in bound.contributions(program.writer_ir())} == {
        "unspecified"
    }
