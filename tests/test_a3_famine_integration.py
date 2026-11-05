"""Actual famine button generation and owned-state collection witnesses."""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace

import pytest
from test_remaining_joint_consumers import _native_number, _overlay, _render

from pdx import decision_adapters, decision_interfaces, decision_rules, observation_queries
from pdx import famine_opportunities as famine
from pdx.lexer import tokenize
from pdx.model import Block
from pdx.parser import parse_bytes, parse_text
from pdx.situated import compiler, domain_coverage, pdx_eval, resources, vanilla_inventory

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    model = compiler.load_model()
    assert model.consumer_ir is not None
    policy, _ = compiler.compile_policy(
        dict(adapters.policies)[famine.SOURCE], famine.SOURCE, model
    )
    selected = replace(
        adapters,
        policies=((famine.SOURCE, policy),),
        supply=None,
        initial_values=(),
        scalar_values=(),
        event_programs=(),
        acceptance_programs=(),
    )
    inputs = decision_adapters.read_inputs(selected)
    generated, report = decision_adapters.build(
        selected, texts=inputs, consumer_ir=model.consumer_ir
    )
    return policy, inputs, generated[famine.SOURCE], model, report


def _state(famine_present=True, railway=False):
    return {
        "has_famine": famine_present,
        "has_building": {(("argument", "building_railway"),): railway},
    }


def _facts(states, *, default=False, ai=True):
    country = {"is_ai": ai, "any_scope_state": states, "in_default": default}
    return {"ROOT": country}


def _observe(states, mode):
    """Independent Kleene existential over physical states, not the renderer."""
    if states is None:
        return None
    unknown = False
    for state in states:
        affected = state.get("has_famine")
        railway = state.get("has_building", {}).get((("argument", "building_railway"),))
        relevant = True if mode == "affected" else railway
        if mode == "nonrailway" and relevant is not None:
            relevant = not relevant
        if affected is True and relevant is True:
            return True
        unknown |= affected is not False and relevant is not False
    return None if unknown else False


@pytest.mark.parametrize(
    ("states", "default", "expected"),
    [
        ([], False, (1, 1, 1)),
        ([_state(False, True)], True, (1, 1, 1)),
        ([_state()], False, (1.12, 0.89, 1.22)),
        ([_state(True, True)], False, (1.22, 1.07, 1.34)),
        ([_state(), _state(True, True)], False, (1.22, 0.97, 1.34)),
        ([_state(True, None)], None, (1.04, 0.86, 1.16)),
        (None, True, (1, 1, 1)),
        ([_state(None)], True, (1, 1, 1)),
        ([_state(None), _state()], False, (1.12, 0.89, 1.22)),
    ],
)
def test_full_collection_bridge_hand_calculation_reference_and_actual_pdx(
    production, states, default, expected
):
    policy, _, text, _, _ = production
    facts = _facts(states, default=default)
    values = {
        famine.READER: _observe(states, "affected"),
        famine.RAILWAY: _observe(states, "railway"),
        famine.NONRAILWAY: _observe(states, "nonrailway"),
        "default": default,
    }
    result = decision_rules.evaluate(policy, values, is_ai=True)
    for row, factor in zip(famine.consumer_catalog(), expected, strict=True):
        field = row["field"]
        assert result.get(field, (None, 1))[1] == pytest.approx(factor)
        body = _overlay(text, field)
        assert _native_number(10, body, facts) == pytest.approx(10 * factor)
        # Every native terminal zero remains a zero under the positive multiplier.
        assert _native_number(0, body, facts) == 0


def test_real_query_dispatch_exact_parameter_state_and_foreign_decoys(production):
    policy = production[0]
    states = [_state()]
    country = _facts(states)["ROOT"]
    country["foreign_states"] = [_state(True, True)]
    for reader in policy.readers:
        if not reader.parameters:
            continue
        query = observation_queries.from_reader(reader.engine, dict(reader.parameters))
        assert isinstance(query, famine.FamineStateQuery)
        compiled = observation_queries.compile_query(query, famine.frozen_inputs())
        assert compiled.world_scans == 0
        assert compiled.local_collections == ("owned_states",)
        limit = parse_text(compiled.expression).root
        assert pdx_eval.condition(limit, country) is _observe(states, query.observation)
    with pytest.raises(pdx_eval.UnsupportedPdxError):
        pdx_eval.condition(
            parse_text("has_building = building_railway").root, {"has_building": True}
        )


def test_full_native_source_restored_and_no_extra_state_or_world_scan(production):
    _, inputs, text, _, _ = production
    restored = re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        text,
        flags=re.DOTALL,
    )
    assert [(t.kind, t.value) for t in tokenize(restored)] == [
        (t.kind, t.value) for t in tokenize(inputs[famine.SOURCE])
    ]
    assert _render(parse_text(restored).root) == _render(parse_text(inputs[famine.SOURCE]).root)
    resources.verify_inherited_writes({famine.SOURCE: text})


def test_actual_ir_context_exact_consumers_and_independent_inventory(production):
    policy, _, text, model, report = production
    assert len(policy.consumer_programs) == 3
    assert report["famine_opportunities_sha256"]
    instances = tuple(i for i in model.action_instances if i.source == famine.SOURCE)
    assert len(instances) == 14
    inputs = {name: value.encode() for name, value in famine.frozen_inputs().items()}
    root = parse_bytes(inputs[famine.SOURCE], path=famine.SOURCE).root
    surfaces = []
    for row in famine.consumer_catalog():
        declaration = root.first(row["definition"])
        assert declaration is not None
        assert isinstance(declaration.value, Block)
        weight = declaration.value.first("ai_chance")
        assert weight is not None
        scope = vanilla_inventory._scope(
            "scripted_buttons", ("ai_chance",), inputs, {}, declaration, famine.SOURCE
        )
        surfaces.append(
            vanilla_inventory._surface(
                famine.SOURCE, row["definition"], "ai_chance", weight.line, scope
            )
        )
        assert text.count(f"# SITAI BEGIN information:{row['field']}\n") == 1
        interface = decision_interfaces.consumer(
            tuple(row["field"].split(".")), (), source=famine.SOURCE, native_root="country"
        )
        assert interface["native_unit"] == "relative_weight"
    inventory = vanilla_inventory.VanillaInventory(
        baseline_id="exact_complete_famine_sources",
        source_hashes={name: hashlib.sha256(raw).hexdigest() for name, raw in inputs.items()},
        scope_hash="a" * 64,
        surfaces=tuple(surfaces),
        scanned_directories=("scripted_buttons",),
        content_roots=("frozen_complete_sources",),
        parsed_files=len(inputs),
    )
    proof = domain_coverage.native_coverage(
        inventory, instances, native_sources=inputs, production_policies={famine.SOURCE: policy}
    )
    assert proof["binding_issue_count"] == 0
    assert proof["counts"]["actual_covered"] == 3
    for instance in instances:
        context = instance.evaluation_context
        assert context is not None
        assert context.actor_scope is not None
        assert (context.actor_scope.name, context.actor_scope.kind) == ("root", "country")
        assert not context.targets
        assert not context.auxiliary_scopes


def test_player_and_domain_off_are_native(production):
    policy, inputs, text, _, _ = production
    for row in famine.consumer_catalog():
        assert _native_number(10, _overlay(text, row["field"]), _facts([_state()], ai=False)) == 10
    disabled = replace(policy, enabled_domains=frozenset())
    result = decision_rules.patch(
        inputs[famine.SOURCE], disabled, baseline=inputs[famine.SOURCE], default_strategy=False
    )
    assert result == inputs[famine.SOURCE]


def test_exact_context_rejects_changed_query_identity(production):
    policy = production[0]
    field = famine.consumer_catalog()[0]["field"]
    context = compiler._frozen_famine_contexts()[(famine.SOURCE, field)]
    readers = {r.key: r for r in policy.readers}
    malformed = replace(
        readers[famine.READER], parameters=(("state_query", "tax_capacity_shortfall"),)
    )
    with pytest.raises(ValueError, match="精确事实身份"):
        compiler.validate_context_readers(
            field,
            context,
            {**readers, famine.READER: malformed},
            (),
            source=famine.SOURCE,
            native_root="country",
            input_keys=(famine.READER,),
        )


def test_exact_authorization_rejects_other_button_source_and_scope():
    row = famine.consumer_catalog()[0]
    for source, field, actor in (
        (famine.SOURCE, "other.ai_chance", ()),
        ("common/scripted_buttons/other.txt", row["field"], ()),
        (famine.SOURCE, row["field"], ("owner",)),
    ):
        with pytest.raises(ValueError):
            decision_interfaces.consumer(
                tuple(field.split(".")), actor, source=source, native_root="country"
            )
