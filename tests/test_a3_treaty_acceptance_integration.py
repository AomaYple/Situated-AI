"""A directed acceptance program is an actual typed production consumer."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest
from test_a3_treaty_acceptance import _actual, _context, _values

from pdx import decision_adapters, decision_interfaces
from pdx import treaty_acceptance_opportunities as accept
from pdx.parser import parse_text
from pdx.situated import action_instances, compiler, domain_coverage, vanilla_inventory
from pdx.situated.decision_ir import ConsumerIRBundle, WriterDecisionIR

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def production():
    inputs = accept.frozen_inputs()
    program = accept.compile_program()
    adapters = decision_adapters.AdapterSet(
        sources=tuple(sorted(accept.load()["sources"].items())),
        policies=(),
        source_sha256="a" * 64,
        acceptance_programs=(program,),
    )
    bundle = ConsumerIRBundle(1, (), (program.writer_ir(),))
    return inputs, adapters, bundle


def test_real_compiler_freezes_the_current_accepting_country_article_and_goods(production):
    inputs, adapters, _ = production
    configured = decision_adapters.load()
    assert configured.acceptance_programs == adapters.acceptance_programs
    assert configured.treaty_acceptance_opportunities_sha256
    model = compiler.load_model()
    assert model.consumer_ir is not None
    programs = decision_adapters._acceptance_programs(configured, model.consumer_ir, enabled=True)
    assert len(programs) == 1
    program = programs[0]
    writer = next(row for row in model.consumer_ir.writers if row.kind == "acceptance_program")
    assert writer.acceptance_program is program
    assert writer.definition == "no_tariffs"
    assert writer.evaluation_context is not None
    assert writer.evaluation_context.targets == ()
    assert {row.kind for row in writer.evaluation_context.auxiliary_scopes} == {
        "country",
        "treaty_article_options",
        "market_goods",
    }
    assert (
        len(
            [
                row
                for row in model.observation_contracts
                if row[0] == accept.SOURCE and row[1].startswith("acceptance_")
            ]
        )
        == 8
    )
    contract = model.contract()["domain_coverage"]
    assert isinstance(contract, dict)
    assert any(
        row["definition"] == "no_tariffs" and row["consumer_id"] == accept.FIELD
        for row in contract["domains"]["diplomacy"]["targets"]
    )
    subset = ConsumerIRBundle(1, (), (writer,))
    generated, metadata = decision_adapters.build(
        adapters, texts=inputs, enabled_domains=frozenset({"diplomacy"}), consumer_ir=subset
    )
    assert set(generated) == {accept.SOURCE}
    assert metadata["acceptance_programs"] == [program.as_dict()]
    assert decision_interfaces.acceptance_consumer(program)["native_unit"] == "acceptance_score"
    assert metadata["field_owners"] == [
        {"source": accept.SOURCE, "field": accept.FIELD, "owner": "treaty_acceptance_opportunities"}
    ]
    instances = tuple(row for row in model.action_instances if row.kind == "acceptance_program")
    assert action_instances.missing_witnesses(instances, generated) == ()
    assert action_instances.missing_witnesses(instances, {}) == (program.writer_id,)
    for changes, expected in (
        ({"net_total_income": -1}, -8),
        ({"in_default": None}, -12),
        ({"root": "B"}, 6),
        ({"input_market_goods_exists": False}, 0),
    ):
        values = _values(**changes)
        assert program.evaluate(values, is_ai=True) == expected
        assert _actual(generated[accept.SOURCE], _context(values)) == expected


@pytest.mark.parametrize(
    "mutation",
    ["missing", "duplicate", "program", "roles", "reader", "field", "tail", "kind", "parent"],
)
def test_acceptance_cannot_silently_recompile_mutated_or_missing_supplied_ir(production, mutation):
    inputs, adapters, bundle = production
    writer = bundle.writers[0]
    assert writer.acceptance_program is not None
    rows: tuple[WriterDecisionIR, ...]
    if mutation == "missing":
        rows = ()
    elif mutation == "duplicate":
        rows = (writer, writer)
    elif mutation == "program":
        rows = (
            replace(
                writer,
                acceptance_program=replace(writer.acceptance_program, actor="source_country"),
            ),
        )
    elif mutation == "roles":
        rows = (replace(writer, evaluation_context=None),)
    elif mutation == "reader":
        rows = (replace(writer, reader_context_bindings=()),)
    elif mutation == "field":
        rows = (replace(writer, field="no_tariffs.ai.contextual_accept_score"),)
    elif mutation == "tail":
        rows = (replace(writer, vanilla_tail="replace"),)
    elif mutation == "kind":
        rows = (replace(writer, kind="rule_action"),)
    else:
        rows = (
            writer,
            WriterDecisionIR(
                "parent",
                "rule_action",
                accept.SOURCE,
                "parent",
                "parent",
                "no_tariffs.ai",
                "root",
                "none",
                "add",
                "preserve",
                "treaty_acceptance_opportunities",
            ),
        )
    changed = replace(bundle, writers=rows)
    with pytest.raises(ValueError):
        decision_adapters.build(
            adapters, texts=inputs, enabled_domains=frozenset({"diplomacy"}), consumer_ir=changed
        )
    if mutation != "missing":
        with pytest.raises(ValueError):
            decision_adapters.build(
                adapters, texts=inputs, enabled_domains=frozenset(), consumer_ir=changed
            )


def test_disabled_and_standalone_paths_share_the_same_immutable_acceptance_plan(production):
    inputs, adapters, bundle = production
    disabled, metadata = decision_adapters.build(
        adapters, texts=inputs, enabled_domains=frozenset(), consumer_ir=bundle
    )
    assert disabled == {}
    assert metadata["acceptance_programs"] == []
    assert metadata["field_owners"] == []
    standalone, _ = decision_adapters.build(
        adapters, texts=inputs, enabled_domains=frozenset({"diplomacy"})
    )
    assert standalone == accept.patch(inputs)
    # Other physical leaves may compose, while changing this score is rejected.
    overlay = inputs[accept.SOURCE].replace("value = 0.1", "value = 0.2")
    merged, _ = decision_adapters.build(
        adapters,
        texts=inputs,
        enabled_domains=frozenset({"diplomacy"}),
        consumer_ir=bundle,
        overlays={accept.SOURCE: overlay},
    )
    assert "value = 0.2" in merged[accept.SOURCE]
    invalid = inputs[accept.SOURCE].replace(
        "inherent_accept_score = {", "inherent_accept_score = { add = 1"
    )
    with pytest.raises(ValueError, match="双作者"):
        decision_adapters.build(
            adapters,
            texts=inputs,
            enabled_domains=frozenset({"diplomacy"}),
            consumer_ir=bundle,
            overlays={accept.SOURCE: invalid},
        )


def test_independent_native_inventory_joins_only_the_exact_inherent_consumer(production):
    inputs, _, bundle = production
    raw = {source: text.encode("utf-8") for source, text in inputs.items()}
    declaration = parse_text(inputs[accept.SOURCE]).root.first("no_tariffs")
    assert declaration is not None
    scope = vanilla_inventory._treaty_scope(
        ("ai", "inherent_accept_score"), raw, declaration, accept.SOURCE
    )
    surface = vanilla_inventory._surface(
        accept.SOURCE, "no_tariffs", "ai.inherent_accept_score", 159, scope
    )
    inventory = vanilla_inventory.VanillaInventory(
        "independent_directed_acceptance",
        {source: hashlib.sha256(value).hexdigest() for source, value in raw.items()},
        "a" * 64,
        (surface,),
        ("treaty_articles",),
        ("common",),
        1,
    )
    writer = bundle.writers[0]
    assert writer.acceptance_program is not None
    assert writer.evaluation_context is not None
    instance = action_instances.ActionInstance(
        action_id=writer.writer_id,
        kind="acceptance_program",
        source=writer.source,
        rule_id=writer.definition,
        domain="diplomacy",
        consumer_field=writer.field,
        operation="add",
        value=0,
        condition_facts=tuple(reader.key for reader in writer.acceptance_program.readers()),
        owner=writer.owner,
        vanilla_tail="preserve",
        evidence=writer.evaluation_context.evidence,
        family_id="diplomacy",
        evaluation_context=writer.evaluation_context,
    )
    report = domain_coverage.native_coverage(inventory, (instance,), native_sources=raw)
    assert report["counts"]["actual_covered"] == 1
    assert report["binding_issue_count"] == 0
    bad = domain_coverage.native_coverage(
        inventory, (replace(instance, evaluation_context=None),), native_sources=raw
    )
    assert bad["counts"]["actual_covered"] == 0
    assert bad["binding_issue_count"] == 1
