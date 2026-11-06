"""Real production term substitution: same graph for reference and PDX."""

from __future__ import annotations

from dataclasses import replace

import pytest
from test_situated_joint_witnesses import _facts

from pdx import country_state, decision_adapters, decision_interfaces, decision_rules
from pdx.situated import compiler, pdx_eval
from pdx.situated.schema import RankTerm

INFO = "mod/decisions/information.toml"


@pytest.fixture(scope="module")
def production():
    model = compiler.load_model()
    policy, contract = compiler.compile_policy(decision_rules.load(), INFO, model)
    adapters = decision_adapters.load()
    inputs = decision_adapters.read_inputs(adapters)
    native = compiler.BASELINE.read_text(encoding="utf-8")
    patched = decision_rules.patch(
        native,
        policy,
        baseline=native,
        reader_words=(
            frozenset(decision_adapters.reader_evidence(inputs))
            | decision_interfaces.proven_reader_words()
        ),
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
        consumer_source=INFO,
    )
    return model, policy, contract, patched


@pytest.mark.parametrize(
    ("literacy", "population", "cash", "expected"),
    [
        (0.2, 100, 1, 1.2),
        (0.2, 100, None, 1.1),
        (0.8, 100, 1, 1.0),
        (None, 100, 1, 1.0),
        (0.2, None, 1, 1.0),
    ],
)
def test_production_school_port_manual_reference_and_pdx(
    production, literacy, population, cash, expected
):
    _, policy, contract, patched = production
    values = {
        "literacy": literacy,
        "population": population,
        "default": False,
        "net_surplus": cash,
        "bureaucracy": 0,
    }
    result = decision_rules.evaluate_ir(policy, values, is_ai=True)
    assert result.get("institution_scores.institution_schools", ("", 1))[1] == pytest.approx(
        expected
    )
    begin = patched.index("# SITAI BEGIN information:institution_scores.institution_schools")
    end = patched.index("# SITAI END information:institution_scores.institution_schools", begin)
    scalar = "\n".join(patched[begin:end].splitlines()[1:])
    assert pdx_eval.select(scalar, _facts(policy, values)).delta == pytest.approx(expected)
    assert len(contract["domain_ports"]) == 8
    assert decision_rules.evaluate_ir(policy, values, is_ai=False) == {}


def test_port_actual_predicate_drift_and_required_input_guard_are_rejected(production):
    _, policy, _, _ = production
    binding = policy.port_bindings[0]
    graph = binding.graph
    leaf = next(port for port in graph.ports if port.id == "literacy_low")
    broken = replace(
        graph,
        ports=tuple(
            replace(port, expected=0.9) if port.id == leaf.id else port for port in graph.ports
        ),
    )
    policy = replace(
        policy,
        port_bindings=tuple(
            replace(item, graph=broken) if item.port == binding.port else item
            for item in policy.port_bindings
        ),
    )
    with pytest.raises(ValueError, match="不等价"):
        decision_rules.evaluate_ir(policy, {"literacy": 0.2, "population": 100}, is_ai=True)


def test_card_numeric_fact_overrides_alias_and_conflict_fails(production):
    model, _, _, _ = production
    values = {"literacy": 0.8, "literacy_ready": False}
    with pytest.raises(ValueError, match="冲突"):
        compiler.evaluate_actions(model, values, is_ai=True)
    assert compiler.evaluate_actions(model, values, is_ai=False) == {}


def test_full_contract_tracks_port_source_and_canonical_relation_origins(production):
    model, _, _, _ = production
    assert "domain_ports" in model.source_sha256
    assert len(model.contract()["domain_ports"]["uses"]) == 13
    for relation in model.relations:
        expected = {
            origin.identity
            for fact in relation.condition_facts
            for origin in model.port_graph.origins(fact)
        }
        assert set(relation.origins) == expected


def test_binding_required_known_uses_reader_type_and_bounds(production):
    _, policy, _, _ = production
    binding = next(item for item in policy.port_bindings if item.port == "school_need")
    binding = replace(binding, required_known=("literacy",))
    readers = {reader.key: reader for reader in policy.readers}
    assert binding.evaluate({"literacy": 0.2, "population": 100}, readers)
    for literacy in (None, True, -1, "0.2"):
        assert not binding.evaluate({"literacy": literacy, "population": 100}, readers)


def test_action_origin_claims_require_actual_observed_source_closure(production):
    model, _, _, _ = production
    action = replace(
        model.actions[0],
        requires_all=("literacy_low",),
        requires_any=(),
        blocked_by=(),
        exit_when=(),
        cause_group="school_need",
        cause_origins=("literacy_low",),
        rank_terms=(
            RankTerm("literacy_low", "school_need", 1, "flag", 0.1, "need", ("literacy_low",)),
        ),
    )
    bound = compiler._bind_action_origins((action,), model.port_graph, model.facts)[0]
    expected = tuple(origin.identity for origin in model.port_graph.origins("literacy_low"))
    assert bound.cause_origins == expected
    assert bound.rank_terms[0].origins == expected
    with pytest.raises(ValueError, match="闭包不一致"):
        compiler._bind_action_origins(
            (replace(action, cause_origins=("population_present",)),), model.port_graph, model.facts
        )
    with pytest.raises(ValueError, match="观测端口"):
        compiler._bind_action_origins(
            (replace(action, rank_terms=(replace(action.rank_terms[0], fact="support_fiscal"),)),),
            model.port_graph,
            model.facts,
        )


def test_port_need_cannot_gate_unrelated_card_base_or_disabled_consumer(production):
    model, _, _, _ = production
    assert compiler.evaluate_actions(model, {}, is_ai=True) == compiler.evaluate_actions(
        model, {"school_need": False, "industrial_need": False}, is_ai=True
    )
    assert compiler.evaluate_actions(model, {}, is_ai=True, enabled_consumer_fields=set()) == {}


def test_card_port_reader_and_observed_predicate_drift_fail(production):
    model, _, _, _ = production
    graph = model.port_graph
    literacy = next(port for port in graph.ports if port.id == "literacy_low")
    broken = replace(
        graph,
        ports=tuple(
            replace(port, reader=replace(literacy.reader, maximum=0.9))
            if port.id == literacy.id
            else port
            for port in graph.ports
        ),
    )
    with pytest.raises(ValueError, match="完整身份"):
        compiler.evaluate_actions(replace(model, port_graph=broken), {}, is_ai=True)
    changed_facts = tuple(
        replace(fact, trigger="has_institution = institution_police")
        if fact.id == "schools_present"
        else fact
        for fact in model.facts
    )
    with pytest.raises(ValueError, match="实际原始事实"):
        compiler.evaluate_actions(replace(model, facts=changed_facts), {}, is_ai=True)
