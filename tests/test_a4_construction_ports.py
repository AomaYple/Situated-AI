"""Hand-derived A4 construction witnesses against production and native AST.

This is static numerical interpretation, never a game-engine execution claim.
"""

from __future__ import annotations

import json
import math
from dataclasses import replace

import pytest
from test_a3_rule_relation_projection import _patch
from test_a3_rule_relation_projection import production as production_fixture
from test_remaining_joint_consumers import _block, _native_number, _overlay, _render
from test_situated_joint_witnesses import _facts

from pdx import decision_adapters, decision_interfaces, decision_rules
from pdx.parser import parse_text
from pdx.situated import compiler, evidence, pdx_eval, ports, programs
from tools.ci import a4_classify

FIELD = "wanted_construction_output"
INFO = "mod/decisions/information.toml"


@pytest.fixture(scope="module")
def production():
    wrapped = getattr(production_fixture, "__wrapped__", None)
    assert callable(wrapped)
    return wrapped()


def values(**changes):
    result = {
        "population": 1000000,
        "cost_country_population": 1000000,
        "tools_balance": -1,
        "industrial_route": False,
        "default": False,
        "loans": False,
        "net_surplus": 0,
        "war_defeat": False,
        "current_public_schools": False,
        "schools_present": False,
        "literacy": 0.6,
    }
    result.update(changes)
    return result


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 1.10),
        ({"industrial_route": None, "net_surplus": None, "literacy": None}, 1.10),
        ({"tools_balance": 0}, 1),
        ({"tools_balance": None}, 1),
        ({"tools_balance": True}, 1),
        ({"tools_balance": -0.000001}, 1.10),
        ({"tools_balance": 0.000001}, 1),
        ({"tools_balance": 0, "war_defeat": True}, 1.12),
        ({"war_defeat": True}, 1.22),
        ({"war_defeat": True, "industrial_route": True, "net_surplus": 1}, 1.45),
        (
            {
                "war_defeat": True,
                "industrial_route": True,
                "net_surplus": 1,
                "current_public_schools": True,
                "schools_present": True,
            },
            1.475,
        ),
        (
            {
                "war_defeat": True,
                "default": True,
                "current_public_schools": True,
                "schools_present": True,
            },
            0.995,
        ),
        (
            {
                "war_defeat": True,
                "default": None,
                "current_public_schools": True,
                "schools_present": True,
            },
            0.995,
        ),
        (
            {
                "war_defeat": True,
                "industrial_route": True,
                "net_surplus": 1,
                "current_public_schools": True,
                "schools_present": True,
                "loans": True,
                "debt_ratio": 0.4,
                "bankruptcy_horizon": 1,
            },
            1.325,
        ),
        ({"loans": True, "debt_ratio": None, "bankruptcy_horizon": 1}, 0.95),
        ({"loans": False, "debt_ratio": None}, 1.10),
        ({"loans": True, "debt_ratio": 0.399999, "bankruptcy_horizon": 1}, 1.10),
        ({"loans": True, "debt_ratio": 0.4, "bankruptcy_horizon": 26}, 1.10),
        ({"loans": True, "debt_ratio": 0.4, "bankruptcy_horizon": 25.999}, 0.95),
        ({"loans": True, "debt_ratio": 0.4, "bankruptcy_horizon": None}, 0.95),
        ({"loans": True, "debt_ratio": None, "bankruptcy_horizon": 26}, 1.10),
        (
            {
                "loans": True,
                "debt_ratio": 0.4,
                "bankruptcy_horizon": 1,
                "population": None,
                "cost_country_population": None,
            },
            1.10,
        ),
    ],
)
def test_independent_supply_recovery_signed_cost_reference_and_pdx(production, changes, expected):
    _, policy, _, _, _ = production
    raw = values(**changes)
    reference = decision_rules.evaluate_ir(policy, raw, is_ai=True)
    assert reference.get(FIELD, ("", 1))[1] == pytest.approx(expected)
    parsed = pdx_eval.select(_overlay(_patch(production), FIELD), _facts(policy, raw))
    assert parsed.delta == pytest.approx(expected)


def test_recovery_exit_removes_only_independent_recovery(production):
    _, policy, _, _, _ = production
    for raw, expected in (
        (values(war_defeat=True), 1.22),
        (values(war_defeat=False), 1.10),
        (values(war_defeat=True, tools_balance=0), 1.12),
    ):
        assert decision_rules.evaluate_ir(policy, raw, is_ai=True)[FIELD][1] == pytest.approx(
            expected
        )
        assert pdx_eval.select(
            _overlay(_patch(production), FIELD), _facts(policy, raw)
        ).delta == pytest.approx(expected)
    memory = decision_interfaces.war_memory_contract()
    assert memory["argument"] == "recently_lost_war"
    assert memory["days"] == 1825
    assert memory["mod_persistent_writes"] == 0


def test_financing_cost_scoped_or_cannot_waive_pressure_by_root_existence(production):
    _, policy, _, _, _ = production
    binding = next(
        binding
        for binding in policy.port_bindings
        if binding.definition == "liquidity_construction_guard"
    )
    readers = {reader.key: reader for reader in policy.readers}
    for changes, expected, cheap in (
        ({}, 0.95, False),
        ({"loans": False}, 1.1, True),
        ({"debt_ratio": None}, 0.95, None),
        ({"bankruptcy_horizon": 26}, 1.1, True),
    ):
        raw = values(loans=True, debt_ratio=0.4, bankruptcy_horizon=1)
        raw.update(changes)
        assert binding.cost_values(raw, readers) == (True, cheap is True)
        guard = binding.graph.guard(binding.source, binding.definition, binding.port)
        facts = _facts(policy, raw)
        assert pdx_eval.condition(parse_text(guard.when_false).root, facts) is cheap
        assert decision_rules.evaluate_ir(policy, raw, is_ai=True)[FIELD][1] == pytest.approx(
            expected
        )
        assert pdx_eval.select(_overlay(_patch(production), FIELD), facts).delta == pytest.approx(
            expected
        )
    for facts in ({}, {"ROOT": None}):
        assert pdx_eval.condition(parse_text(guard.when_false).root, facts) in (False, None)
        # Core existence remains unknown: the cost term itself exits locally,
        # and unknown is never evidence that the pressure is cheap.
        assert pdx_eval.select(_overlay(_patch(production), FIELD), facts).delta == 0


def test_independent_domains_and_native_player_disabled_boundaries(production):
    _, policy, _, _, native = production
    raw = values(war_defeat=True, literacy=0.2, bureaucracy=0)
    result = decision_rules.evaluate_ir(policy, raw, is_ai=True)
    assert result[FIELD][1] == pytest.approx(1.22)
    assert result["institution_scores.institution_schools"][1] == pytest.approx(1.10)
    assert _patch(production, enabled=frozenset()) == native
    assert decision_rules.evaluate_ir(policy, raw, is_ai=False) == {}
    assert (
        pdx_eval.select(_overlay(_patch(production), FIELD), _facts(policy, raw, is_ai=False)).delta
        == 0
    )


@pytest.mark.parametrize(("benefit", "cost", "expected"), [(1.2, -0.1, 1.5), (0.1, -1.2, 0.5)])
def test_common_scalar_terminal_saturation_with_explicit_program_inputs(benefit, cost, expected):
    # The actual slice peaks at 1.475. Inject explicit common-program terms to
    # test saturation without manufacturing impossible production facts.
    scalar = programs.ScalarProgram(
        "test_saturation",
        "multiply",
        1,
        0.5,
        1.5,
        (
            programs.ScalarGroup("benefit", (programs.ScalarTerm("b", "b", benefit),)),
            programs.ScalarGroup("cost", (programs.ScalarTerm("c", "c", cost),)),
        ),
    )
    assert programs.evaluate_scalar(scalar, {"b": True, "c": True}) == expected
    text = programs.render_scalar(
        scalar, {"b": "always = yes", "c": "always = yes"}, ai_guard="is_ai = yes", style="rules"
    )
    assert pdx_eval.select(text, {"is_ai": True}).delta == expected


def test_current_raw_identity_and_joint_writer_contribution_are_mechanical(production):
    model, policy, _, _, _ = production
    assert model.consumer_ir is not None
    projected = a4_classify.current_evidence_ports(model, _patch(production))
    # Actual source/graph/IR projection must survive its persisted JSON boundary;
    # dataclass tuples must not invalidate an otherwise unchanged live candidate.
    assert json.loads(json.dumps(projected)) == projected
    budget = projected["static_budget"]
    # The graph is now a combined explicit + consumer-partition projection.
    # Keep whole-graph metrics truthful and check the historical construction
    # slice through its exact writer-use closure separately.
    assert (budget["ports"], budget["uses"]) == (4726, 6138)
    assert budget["max_expanded_leaves"] == 14
    assert budget["max_evaluation_cost"] == 15
    assert (budget["construction_ports"], budget["construction_uses"]) == (27, 13)
    assert budget["construction_max_expanded_leaves"] <= 4
    assert budget["construction_max_evaluation_cost"] <= 7
    assert budget["construction_nodes"] <= 320
    assert budget["construction_depth"] <= 26
    assert budget["construction_branches"] <= 12
    assert budget["construction_bytes"] <= 4200
    assert (
        budget["object_iterations"] == budget["world_scans"] == budget["mod_persistent_writes"] == 0
    )
    graph = model.port_graph
    assert graph is not None
    original_facts = {
        fact.id: fact
        for fact in compiler._reader_facts(
            evidence.load(compiler.FACTS),
            information=decision_rules.load(),
            adapters=decision_adapters.load(),
        )
    }
    fact_origins: dict[str, set[str]] = {}
    fact_ids = {fact.id for fact in model.facts}
    for port in graph.ports:
        origins = graph.origins(port.id)
        for reader_key, reader, aliases in (
            (port.reader_key, port.reader, port.reader_aliases),
            (port.reference_key, port.reference_reader, port.reference_aliases),
        ):
            if reader_key is None or reader is None:
                continue
            signature = json.dumps(
                ports.reader_signature(reader),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            ids = {
                origin.identity
                for origin in origins
                if origin.reader_source == reader_key[0] and origin.signature == signature
            }
            for _, alias in aliases or (reader_key,):
                fact_origins.setdefault(alias, set()).update(ids)
        if port.id in fact_ids and len(origins) == 1:
            fact_origins.setdefault(port.id, set()).add(origins[0].identity)
    # Concrete multi-observation counterexample: combining consumers must not
    # promote the logical tools fact to one arbitrary consumer observation.
    tools_fact = next(fact for fact in model.facts if fact.id == "tools_balance")
    assert len(fact_origins["tools_balance"]) > 1
    assert tools_fact.identity == "information:mod/decisions/information.toml:tools_balance"
    assert tools_fact.identity not in fact_origins["tools_balance"]
    for binding in policy.port_bindings:
        if binding.definition not in {
            "remaining_industrial_construction_need",
            "remaining_industrial_construction_need_funded",
            "remaining_reconstruction_need",
            "remaining_reconstruction_need_funded",
            "fiscal_construction_guard",
            "liquidity_construction_guard",
        }:
            continue
        writer = next(
            writer
            for writer in model.consumer_ir.writers
            if (writer.source, writer.definition) == (binding.source, binding.definition)
        )
        assert binding.contribution in writer.port_contributions
        assert binding.contribution.field == FIELD
        assert binding.contribution.actor == "root"
        assert binding.contribution.target == "none"
        assert binding.contribution.output_unit == "multiplier_delta"
        for origin in binding.graph.origins(binding.port):
            assert origin.identity == origin.observation.identity
            assert origin.observation.roles == ("actor",)
            assert origin.observation.source_sha256
            assert origin.observation.proof
            assert origin.observation.unknown == "preserve_unknown"
            fact = next(fact for fact in model.facts if fact.id == origin.reader_key)
            observation_ids = fact_origins[fact.id]
            # EvidenceSpec.identity is a logical fact ID unless compiler
            # proves one complete observation for that source/key/signature;
            # then it is promoted to that observation SHA. Origin identity is
            # always the complete Observation SHA.
            assert origin.identity in observation_ids
            if len(observation_ids) == 1:
                assert fact.identity == origin.identity
            else:
                assert fact.identity == original_facts[fact.id].identity
            assert origin.identity == origin.observation.identity


@pytest.mark.parametrize("fault", ["unit", "actor", "target", "cause"])
def test_contribution_cannot_borrow_another_unit_role_or_cause(production, fault):
    _, policy, _, _, _ = production
    binding = next(binding for binding in policy.port_bindings if binding.role == "recovery")
    changes = {
        "unit": {"output_unit": "currency"},
        "actor": {"actor": "owner"},
        "target": {"target": "target_country"},
        "cause": {"causal_id": "construction_supply_need"},
    }
    broken = replace(binding, contribution=replace(binding.contribution, **changes[fault]))
    rule = next(rule for rule in policy.rules if rule.id == binding.definition)
    with pytest.raises(ValueError, match="贡献"):
        broken.validate(rule, {reader.key: reader for reader in policy.readers})


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 13.75),
        ({"war_defeat": True}, 15.25),
        (
            {
                "war_defeat": True,
                "default": True,
                "current_public_schools": True,
                "schools_present": True,
            },
            12.4375,
        ),
        (
            {
                "war_defeat": True,
                "industrial_route": True,
                "net_surplus": 1,
                "current_public_schools": True,
                "schools_present": True,
            },
            23.046875,
        ),
    ],
)
def test_complete_native_construction_ast_keeps_cost_and_operations(production, changes, expected):
    _, policy, _, _, _ = production
    raw = values(**changes)
    facts = _facts(policy, raw)
    root = facts["ROOT"]
    root.update(
        gdp=2000000,
        investment_pool_income=8250,
        fixed_income=5000,
        diplomatic_pact_expense_ratio=0,
        country_rank=0,
        rank_values={
            "rank_value:great_power": 3,
            "rank_value:major_power": 2,
            "rank_value:unrecognized_major_power": 1,
        },
        has_game_rule={(("argument", "free_construction_unscaled"),): True},
    )
    for getter, names in {
        "has_strategy": (
            "ai_strategy_resource_expansion",
            "ai_strategy_maintain_mandate_of_heaven",
        ),
        "has_journal_entry": (
            "je_grunderzeit",
            "je_five_year_plan",
            "je_meiji_restoration",
            "je_meiji_main",
        ),
        "has_law_or_variant": ("law_type:law_traditionalism",),
    }.items():
        observed = root.setdefault(getter, {})
        for name in names:
            observed.setdefault((("argument", name),), False)
    actual = _block(_block(parse_text(_patch(production)).root, "ai_strategy_default"), FIELD)
    body = "\n".join(_render(item) for item in actual.items)
    assert _native_number(0, body, facts) == pytest.approx(expected)
    root["diplomatic_pact_expense_ratio"] = 0.2
    assert _native_number(0, body, facts) == pytest.approx(expected * 0.8)
    root["total_population"] = 250000
    assert _native_number(0, body, facts) == 0


@pytest.mark.parametrize(
    "getter",
    [
        "gdp",
        "investment_pool_income",
        "fixed_income",
        "total_population",
        "diplomatic_pact_expense_ratio",
    ],
)
@pytest.mark.parametrize("bad", [True, "1", math.inf, math.nan])
def test_complete_native_getters_reject_wrong_type_or_nonfinite(getter, bad):
    item = parse_text(f"value = {getter}").root.first("value")
    assert item is not None
    with pytest.raises(pdx_eval.UnsupportedPdxError, match="有限数"):
        pdx_eval._numeric_value(item, {"ROOT": {getter: bad}})
    assert pdx_eval._numeric_value(item, {"ROOT": {}}) is None


@pytest.mark.parametrize("bad", [True, "1", math.inf, math.nan])
def test_native_rank_symbol_requires_explicit_finite_observation(bad):
    limit = parse_text("country_rank >= rank_value:major_power").root
    facts = {"country_rank": 0, "rank_values": {"rank_value:major_power": bad}}
    with pytest.raises(pdx_eval.UnsupportedPdxError, match="有限数"):
        pdx_eval.condition(limit, facts)
    assert pdx_eval.condition(limit, {"country_rank": 0}) is None
    assert (
        pdx_eval.condition(limit, {"country_rank": 0, "rank_values": {"rank_value:major_power": 2}})
        is False
    )
    assert (
        pdx_eval.condition(limit, {"country_rank": 2, "rank_values": {"rank_value:major_power": 2}})
        is True
    )


def test_native_game_rule_observation_is_parameter_bound():
    limit = parse_text("has_game_rule = free_construction_unscaled").root
    assert (
        pdx_eval.condition(
            limit,
            {"has_game_rule": {(("argument", "free_construction_scaled_player_exemption"),): True}},
        )
        is None
    )
    assert (
        pdx_eval.condition(
            limit, {"has_game_rule": {(("argument", "free_construction_unscaled"),): False}}
        )
        is False
    )
    with pytest.raises(pdx_eval.UnsupportedPdxError, match="完整参数身份"):
        pdx_eval.condition(limit, {"has_game_rule": True})
