"""Exact power-bloc membership acceptance through normal adapters and WriterIR."""

import hashlib
import math
from dataclasses import replace

import pytest

from pdx import decision_adapters, decision_interfaces, decision_rules
from pdx import power_bloc_membership as membership
from pdx import treaty_acceptance_opportunities as acceptance
from pdx.parser import parse_text
from pdx.situated import decision_ir, pdx_eval


@pytest.fixture(scope="module")
def production():
    loaded = decision_adapters.load()
    (program,) = [p for p in loaded.acceptance_programs if membership.is_membership(p)]
    sources = acceptance.program_source_hashes()
    inputs = {**acceptance.frozen_inputs(), **membership.frozen_inputs()}
    # Normal loading is exercised above; narrow output generation to this one
    # actual consumer so tests do not build unrelated Mod output or compiler.
    narrowed = decision_adapters.AdapterSet(
        sources=tuple(sorted(sources.items())),
        policies=(),
        source_sha256=loaded.source_sha256,
        acceptance_programs=(program,),
        treaty_acceptance_opportunities_sha256=loaded.treaty_acceptance_opportunities_sha256,
    )
    bundle = decision_ir.ConsumerIRBundle(1, (), (program.writer_ir(),))
    files, contract = decision_adapters.build(
        narrowed, texts=inputs, enabled_domains=frozenset({"diplomacy"}), consumer_ir=bundle
    )
    return loaded, narrowed, program, bundle, inputs, files, contract


def values(**changes):
    return {
        "bloc_membership_income": -1,
        "bloc_membership_member": False,
        "bloc_membership_leader": True,
        "bloc_membership_tier3": True,
        **changes,
    }


def environment(v, *, is_ai=True):
    bloc = {"has_principle": {(("argument", membership.TOKEN),): v["bloc_membership_tier3"]}}
    return {
        "ROOT": {
            "is_ai": is_ai,
            "net_total_income": v["bloc_membership_income"],
            "is_in_power_bloc": v["bloc_membership_member"],
        },
        "scope:actor": {"is_power_bloc_leader": v["bloc_membership_leader"], "power_bloc": bloc},
    }


def suffix(text):
    return text.split("# SITAI BEGIN treaty_acceptance:invite_to_power_bloc\n", 1)[1].split(
        "# SITAI END treaty_acceptance:invite_to_power_bloc", 1
    )[0]


def hand(v, *, is_ai=True):
    income = v["bloc_membership_income"]
    return (
        -4
        if (
            is_ai
            and type(income) in {int, float}
            and math.isfinite(income)
            and income < 0
            and v["bloc_membership_member"] is False
            and v["bloc_membership_leader"] is True
            and v["bloc_membership_tier3"] is True
        )
        else 0
    )


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"bloc_membership_income": 0},
        {"bloc_membership_income": 1},
        {"bloc_membership_income": None},
        {"bloc_membership_income": float("nan")},
        {"bloc_membership_member": True},
        {"bloc_membership_member": None},
        {"bloc_membership_leader": False},
        {"bloc_membership_leader": None},
        {"bloc_membership_tier3": False},
        {"bloc_membership_tier3": None},
    ],
)
def test_normal_adapter_ir_pdx_hand_reference(production, changes):
    _, _, program, _, _, files, _ = production
    v = values(**changes)
    expected = hand(v)
    assert program.evaluate(v, is_ai=True) == expected
    assert pdx_eval.select(suffix(files[program.source]), environment(v)).delta == expected


def test_single_author_ports_actual_context_and_input_hashes(production):
    loaded, narrowed, program, bundle, inputs, files, contract = production
    assert (
        len(
            [
                p
                for p in loaded.acceptance_programs
                if p.field == program.field and p.source == program.source
            ]
        )
        == 1
    )
    assert decision_adapters.writes(narrowed, frozenset({"diplomacy"})) == (
        (program.source, program.field_path, "treaty_acceptance_opportunities"),
    )
    assert set(files) == {program.source}
    assert len(contract["acceptance_consumer_interfaces"]) == 1
    assert bundle.writers[0].validate_acceptance_program() == program
    assert bundle.writers[0].port_contributions
    assert {c.semantic_role for c in bundle.writers[0].port_contributions} == {"cost"}
    assert {
        o.entity
        for g in (program.predicate_ports().graph,)
        for use in g.uses
        for o in g.origins(use.port)
    } == {"root", "actor"}
    for name, digest in narrowed.sources:
        assert hashlib.sha256(inputs[name].encode()).hexdigest() == digest
    assert (
        contract["acceptance_consumer_interfaces"][0]["role"]
        == "vanilla_power_bloc_invitation_acceptance"
    )


def test_normal_disabled_player_and_native_bytes(production):
    _, narrowed, program, bundle, inputs, files, _ = production
    disabled, _ = decision_adapters.build(
        narrowed, texts=inputs, enabled_domains=frozenset(), consumer_ir=bundle
    )
    assert disabled == {}
    assert program.evaluate(values(), is_ai=False) == 0
    assert (
        pdx_eval.select(suffix(files[program.source]), environment(values(), is_ai=False)).delta
        == 0
    )
    generated = files[program.source]
    native = inputs[program.source]
    offset = decision_rules._offsets(native, {program.field_path})[program.field_path]
    end = generated.index("# SITAI END treaty_acceptance:invite_to_power_bloc") + len(
        "# SITAI END treaty_acceptance:invite_to_power_bloc\n\t\t"
    )
    assert generated[:offset] + generated[end:] == native
    assert not parse_text(generated).errors


def test_missing_and_foreign_decoy_objects(production):
    _, _, program, _, _, files, _ = production
    for missing in ("ROOT", "scope:actor", "power_bloc"):
        facts = environment(values())
        if missing == "power_bloc":
            facts["scope:actor"]["power_bloc"] = None
        else:
            facts[missing] = None
        facts.update(net_total_income=-1, is_ai=True, is_power_bloc_leader=True)
        facts["scope:target_country"] = environment(values())["scope:actor"]
        assert pdx_eval.select(suffix(files[program.source]), facts).delta == 0


def test_duplicate_field_program_bundle_and_overlay_rejected(production):
    _, narrowed, program, bundle, inputs, files, _ = production
    with pytest.raises(ValueError, match="重复"):
        decision_adapters.writes(
            replace(narrowed, acceptance_programs=(program, program)), frozenset({"diplomacy"})
        )
    with pytest.raises(ValueError, match="重复"):
        decision_ir.ConsumerIRBundle(1, (), (program.writer_ir(), program.writer_ir())).as_dict()
    with pytest.raises(ValueError, match="重复作者"):
        decision_adapters.build(
            narrowed,
            texts=inputs,
            enabled_domains=frozenset({"diplomacy"}),
            consumer_ir=bundle,
            overlays=files,
        )
    edited = inputs[program.source].replace("value = -100", "value = -101", 1)
    with pytest.raises(ValueError, match="双作者"):
        decision_adapters.build(
            narrowed,
            texts=inputs,
            enabled_domains=frozenset({"diplomacy"}),
            consumer_ir=bundle,
            overlays={program.source: edited},
        )


def test_interface_exact_role_not_global_scope_authority(production):
    _, _, program, _, _, _, _ = production
    for reader in program.readers():
        assert decision_interfaces.reader_scope(
            reader,
            (),
            source=program.source,
            field=program.field_path,
            context=program.evaluation_context(),
        ) in {"country", "power_bloc"}
        for kwargs in (
            {},
            {
                "source": program.source,
                "field": ("invite_to_power_bloc", "ai", "propose_score"),
                "context": program.evaluation_context(),
            },
        ):
            with pytest.raises(ValueError, match="exact receiving"):
                decision_interfaces.reader_scope(reader, (), **kwargs)
    with pytest.raises(ValueError, match="作用域"):
        replace(program.writer_ir(), evaluation_context=None).validate_acceptance_program()


def test_current_source_and_bundle_identity_drift_rejected(production):
    _, narrowed, program, bundle, inputs, _, _ = production
    wrong = dict(inputs)
    wrong[program.source] += "\n# drift\n"
    with pytest.raises(ValueError, match="原件漂移"):
        decision_adapters.build(
            narrowed, texts=wrong, enabled_domains=frozenset({"diplomacy"}), consumer_ir=bundle
        )
    with pytest.raises(ValueError, match="身份"):
        replace(
            program.writer_ir(), field="invite_to_power_bloc.ai.propose_score"
        ).validate_acceptance_program()


def test_existing_acceptance_writers_keep_exact_native_bytes():
    inputs = acceptance.frozen_inputs()
    for spec in acceptance.SPECS:
        program = acceptance.compile_program(spec.definition)
        program.writer_ir().validate_acceptance_program()
        rendered = acceptance.render(program)
        generated = acceptance.patch(inputs, consumer_program=program)[program.source]
        offset = decision_rules._offsets(inputs[program.source], {program.field_path})[
            program.field_path
        ]
        assert (
            generated
            == inputs[program.source][:offset] + rendered + inputs[program.source][offset:]
        )
        assert not parse_text(generated).errors


def test_missing_source_and_reader_signature_rejected(production):
    _, narrowed, program, bundle, inputs, _, _ = production
    missing = dict(inputs)
    del missing[membership.ROLE_DOC]
    with pytest.raises((KeyError, ValueError)):
        decision_adapters.build(
            narrowed, texts=missing, enabled_domains=frozenset({"diplomacy"}), consumer_ir=bundle
        )
    for reader in program.readers():
        for changed in (replace(reader, scope="target_country"), replace(reader, engine="is_ai")):
            with pytest.raises(ValueError, match="exact receiving"):
                decision_interfaces.reader_scope(
                    changed,
                    (),
                    source=program.source,
                    field=program.field_path,
                    context=program.evaluation_context(),
                )


def test_native_general_cost_preserved_and_only_independent_finance_added(production):
    _, _, program, _, inputs, files, _ = production
    # Full-parent verifier checks the complete native helper AST against -50.
    membership.verify(membership.snapshot())
    assert membership.frozen_inputs()[membership.VALUES] == inputs[membership.VALUES]
    assert membership.VALUES not in files
    actual = suffix(files[program.source])
    assert actual.count("min =") == 1
    assert actual.count("max =") == 1
    assert -50 + pdx_eval.select(actual, environment(values())).delta == -54
    assert (
        -50 + pdx_eval.select(actual, environment(values(bloc_membership_member=True))).delta == -50
    )


@pytest.mark.parametrize("cost", [0, 1, -6, float("inf"), float("nan"), True])
def test_tuning_rejects_invalid_or_unbounded_values(tmp_path, monkeypatch, cost):
    parameters = tmp_path / "parameters.toml"
    literal = str(cost).lower()
    parameters.write_text(f"schema = 1\ncost = {literal}\n", encoding="utf-8")
    monkeypatch.setattr(membership, "PARAMETERS", parameters)
    with pytest.raises(ValueError, match="finite exact"):
        membership.tuning()
