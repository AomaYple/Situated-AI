"""Observed school knowledge reaches one actual construction rule program.

Expectations are handwritten deltas; PDX comes from the real compiler/patch,
not a second reference formula or a synthetic reimplementation of the writer.
"""

from __future__ import annotations

import re
from dataclasses import replace

import pytest
from test_remaining_joint_consumers import _overlay
from test_situated_joint_witnesses import _facts

from pdx import country_state, decision_adapters, decision_interfaces, decision_rules
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval, programs

pytestmark = pytest.mark.integration
INFO = "mod/decisions/information.toml"
FIELD = "wanted_construction_output"
TARGET = "remaining_industrial_construction_need"
FUNDED = "remaining_industrial_construction_need_funded"


@pytest.fixture(scope="module")
def production():
    model = compiler.load_model()
    policy, contract = compiler.compile_policy(decision_rules.load(), INFO, model)
    adapters = decision_adapters.load()
    inputs = decision_adapters.read_inputs(adapters)
    words = (
        frozenset(decision_adapters.reader_evidence(inputs))
        | decision_interfaces.proven_reader_words()
    )
    native = compiler.BASELINE.read_text(encoding="utf-8")
    return model, policy, contract, words, native


def _patch(production, policy=None, enabled=None):
    model, original, _, words, native = production
    return decision_rules.patch(
        native,
        original if policy is None else policy,
        baseline=native,
        reader_words=words,
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
        consumer_source=INFO,
        enabled_domains=enabled,
    )


def _values(**changes):
    values: dict[str, object] = {
        "industrial_route": True,
        "tools_balance": -1,
        "current_public_schools": True,
        "schools_present": True,
        "literacy": 0.6,
        "default": False,
        "loans": False,
        "population": 100,
        "cost_country_population": 100,
        "net_surplus": 0,
        "war_defeat": False,
    }
    values.update(changes)
    return values


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 1.125),  # 1 + .10 industrial need + .025 observed knowledge.
        ({"net_surplus": 1}, 1.275),  # .25 funded tier replaces .10; relation once.
        ({"net_surplus": None}, 1.125),
        ({"current_public_schools": False}, 1.10),
        ({"current_public_schools": None}, 1.10),
        ({"schools_present": False}, 1.10),
        ({"schools_present": None}, 1.10),
        ({"literacy": 0.4999}, 1.10),
        ({"literacy": 0.5}, 1.125),
        ({"literacy": None}, 1.10),
        ({"literacy": -0.1}, 1.10),
        ({"industrial_route": False}, 1.125),
        ({"industrial_route": None}, 1.125),
        ({"tools_balance": 0}, 1),
        ({"tools_balance": None}, 1),
        ({"default": True}, 0.875),  # Need and relation survive independent -.25 cost.
        ({"default": None}, 0.875),
        ({"default": True, "current_public_schools": None}, 0.85),
        ({"loans": True, "debt_ratio": 0.4, "bankruptcy_horizon": 1}, 0.975),
        ({"loans": True, "debt_ratio": None, "bankruptcy_horizon": 1}, 0.975),
    ],
)
def test_real_rule_projection_manual_reference_and_actual_pdx(production, changes, expected):
    _, policy, _, _, _ = production
    values = _values(**changes)
    result = decision_rules.evaluate_ir(policy, values, is_ai=True)
    assert result.get(FIELD, ("", 1))[1] == pytest.approx(expected)
    actual = pdx_eval.select(_overlay(_patch(production), FIELD), _facts(policy, values))
    assert actual.delta == pytest.approx(expected)


def test_projection_is_owned_by_the_existing_exact_ir_writer_and_canonical_origins(production):
    model, policy, contract, _, native = production
    assert model.consumer_ir is not None
    (binding,) = policy.rule_relation_bindings
    item = binding.projection
    writer = next(
        row for row in model.consumer_ir.writers if row.source == INFO and row.definition == TARGET
    )
    assert binding.writer is writer
    assert item.writer_id == writer.writer_id
    assert item.field == (FIELD,)
    assert item.output_unit == "multiplier_delta"
    assert item.amount == 0.025
    relation = next(row for row in model.relations if row.cause_id == "school_knowledge_foundation")
    assert binding.relation is relation
    assert item.origins == relation.origins
    assert item.origins == binding.graph.guard(INFO, TARGET, item.port).origins
    assert {leaf.reader.engine for leaf in binding.graph.leaves(item.port)} == {
        "has_law_or_variant",
        "has_institution",
        "literacy_rate",
    }
    assert contract["rule_relations"][0]["writer_id"] == writer.writer_id
    assert "How much construction output should the AI aim for" in native
    assert "Acceptable debt threshold for economic construction" in native
    program = next(row for row in policy.consumer_programs if row.field == (FIELD,))
    scalar = programs.rule_scalar(program)
    assert scalar.groups[-1].selection == "maximum"
    assert scalar.groups[-1].terms[0].amount == 0.025
    text = _overlay(_patch(production), FIELD)
    assert text.count(f"# ACTION {program.action_id} ") == 1
    assert text.count(f"# GROUP {program.action_id}__relation_school_knowledge_foundation") == 1
    assert text.count("\n\t\t\tmin = ") == text.count("\n\t\t\tmax = ") == 1


def test_same_cause_projected_through_two_eligible_rule_paths_contributes_once(production):
    model, policy, _, _, _ = production
    assert model.consumer_ir is not None
    (original,) = policy.rule_relation_bindings
    old_use = next(use for use in original.graph.uses if use.relation_cause)
    graph = replace(
        original.graph, uses=(*original.graph.uses, replace(old_use, definition=FUNDED))
    )
    writer = next(
        row for row in model.consumer_ir.writers if row.source == INFO and row.definition == FUNDED
    )
    second = replace(
        original,
        graph=graph,
        writer=writer,
        projection=replace(original.projection, definition=FUNDED, writer_id=writer.writer_id),
    )
    doubled = programs.enable(
        replace(policy, rule_relation_bindings=(original, second)), source=INFO
    )
    values = _values(net_surplus=1)
    assert decision_rules.evaluate_ir(doubled, values, is_ai=True)[FIELD][1] == pytest.approx(1.275)
    text = _overlay(_patch(production, doubled), FIELD)
    assert pdx_eval.select(text, _facts(doubled, values)).delta == pytest.approx(1.275)
    # The funded path exits but the base path still contributes its one copy.
    values = _values(net_surplus=None)
    assert decision_rules.evaluate_ir(doubled, values, is_ai=True)[FIELD][1] == pytest.approx(1.125)
    assert pdx_eval.select(text, _facts(doubled, values)).delta == pytest.approx(1.125)


def test_relation_domain_disable_removes_only_auxiliary_not_base_or_independent_cost(production):
    _, policy, _, _, native = production
    selected = policy.enabled_domains - {"political"}
    for default, expected in ((False, 1.10), (True, 0.85)):
        values = _values(default=default)
        assert decision_rules.evaluate_ir(policy, values, is_ai=True, enabled_domains=selected)[
            FIELD
        ][1] == pytest.approx(expected)
        text = _overlay(_patch(production, enabled=selected), FIELD)
        assert pdx_eval.select(text, _facts(policy, values)).delta == pytest.approx(expected)
    assert _patch(production, enabled=frozenset()) == native
    assert (
        decision_rules.evaluate_ir(policy, _values(), is_ai=True, enabled_domains=frozenset()) == {}
    )
    assert decision_rules.evaluate_ir(policy, _values(), is_ai=False) == {}
    assert (
        pdx_eval.select(
            _overlay(_patch(production), FIELD), _facts(policy, _values(), is_ai=False)
        ).delta
        == 0
    )


def test_foreign_country_owner_and_derived_alias_cannot_forge_the_observed_relation(production):
    _, policy, _, _, _ = production
    values = _values(current_public_schools=None, schools_present=None, literacy=None)
    values["education_production_feedback"] = True
    facts = _facts(policy, values)
    facts["scope:target_country"] = _facts(policy, _values())["ROOT"]
    facts["ROOT"]["owner"] = _facts(policy, _values())["ROOT"]
    assert decision_rules.evaluate_ir(policy, values, is_ai=True)[FIELD][1] == pytest.approx(1.10)
    assert pdx_eval.select(_overlay(_patch(production), FIELD), facts).delta == pytest.approx(1.10)


def _tree(value):
    if isinstance(value, Scalar):
        return value.unquoted
    if isinstance(value, Assignment):
        return value.key, value.op, _tree(value.value)
    assert isinstance(value, Block)
    return tuple(_tree(item) for item in value.items)


def test_complete_native_strategy_is_retained_after_removing_owned_insertions(production):
    native = production[-1]
    generated = _patch(production)
    stripped = re.sub(
        r"(?ms)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        generated,
    )
    assert _tree(parse_text(stripped).root) == _tree(parse_text(native).root)


@pytest.mark.parametrize("mutation", ["amount", "origins", "writer", "reader", "unit", "cause"])
def test_relation_contract_drift_fails_before_reference_and_generation(production, mutation):
    _, policy, _, _, _ = production
    (binding,) = policy.rule_relation_bindings
    item = binding.projection
    if mutation == "reader":
        changed = replace(
            policy,
            readers=tuple(
                replace(reader, scope="target_country")
                if reader.key == "current_public_schools"
                else reader
                for reader in policy.readers
            ),
        )
    else:
        modifications: dict[str, dict[str, object]] = {
            "amount": {"amount": 0.05},
            "origins": {"origins": ("forged",)},
            "writer": {"writer_id": "another_writer"},
            "unit": {"output_unit": "persons"},
            "cause": {"cause_id": "another_school_cause"},
        }
        changed = replace(
            policy,
            rule_relation_bindings=(
                replace(binding, projection=replace(item, **modifications[mutation])),
            ),
        )
    with pytest.raises(ValueError):
        decision_rules.evaluate_ir(changed, _values(), is_ai=True)
    with pytest.raises(ValueError):
        _patch(production, changed)


def test_projection_cannot_double_an_existing_direct_cause_without_source_contract(production):
    _, policy, _, _, _ = production
    (binding,) = policy.rule_relation_bindings
    # Explicit causal identity alone is insufficient to merge or add a direct
    # rule with an unproven raw-origin closure.
    source = next(rule for rule in policy.rules if rule.id == TARGET)
    mutated = replace(source, contribution_group=binding.projection.cause_id)
    rules = tuple(mutated if rule.id == TARGET else rule for rule in policy.rules)
    from pdx.situated.ir import from_rule

    changed = replace(
        policy, rules=rules, semantic_ir=tuple(from_rule(rule, source=INFO) for rule in rules)
    )
    with pytest.raises(ValueError, match="重复"):
        decision_rules.evaluate_ir(programs.enable(changed, source=INFO), _values(), is_ai=True)


def test_missing_or_wrong_real_relation_cannot_be_substituted_at_compile_time(production):
    model, _, _, _, _ = production
    with pytest.raises(ValueError, match="唯一"):
        compiler.compile_policy(decision_rules.load(), INFO, replace(model, relations=()))
    relation = next(
        item for item in model.relations if item.cause_id == "school_knowledge_foundation"
    )
    altered = replace(relation, condition_facts=("current_public_schools",))
    with pytest.raises(ValueError, match="不匹配"):
        compiler.compile_policy(
            decision_rules.load(),
            INFO,
            replace(
                model,
                relations=tuple(altered if item is relation else item for item in model.relations),
            ),
        )
