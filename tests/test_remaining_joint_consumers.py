"""Complete remaining consumers join concrete need, capacity and independent risk.

Expectations are hand calculated from causes, never from compiled variants.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from functools import cache

import pytest
from test_situated_joint_witnesses import _facts

from pdx import (
    country_state,
    decision_adapters,
    decision_interfaces,
    decision_rules,
    version_contracts,
)
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, migration_baseline, pdx_eval

pytestmark = pytest.mark.integration
INFO = "mod/decisions/information.toml"
DEFAULT = "common/ai_strategies/00_default_strategy.txt"
CONSTRUCTION = "wanted_construction_output"
SCHOOL = "institution_scores.institution_schools"
TRADE = "treaty_category_scores.trade"
ECONOMY = "treaty_category_scores.economy"
STATE = "state_value"
SUBJECT = "ai_strategy_default.subject_value"
OVERLORD = "ai_strategy_default.become_subject_value"
PORT = "ai_strategy_default.treaty_port_value"
NEGOTIATION = "ai_strategy_default.negotiation_chance"
FIELDS = {
    INFO: (CONSTRUCTION, SCHOOL, TRADE, ECONOMY, STATE),
    DEFAULT: (SUBJECT, OVERLORD, PORT, NEGOTIATION),
}


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    model = compiler.load_model()
    assert model.consumer_ir is not None
    info, _ = compiler.compile_policy(decision_rules.load(), INFO, model)
    strategy, _ = compiler.compile_policy(dict(adapters.policies)[DEFAULT], DEFAULT, model)
    selected = replace(
        adapters,
        policies=((DEFAULT, strategy),),
        supply=None,
        initial_values=tuple(r for r in adapters.initial_values if r.source == DEFAULT),
        scalar_values=tuple(r for r in adapters.scalar_values if r[0] == DEFAULT),
    )
    inputs = decision_adapters.read_inputs(selected)
    generated, _ = decision_adapters.build(
        selected, texts=inputs, country_policy=country_state.load(), consumer_ir=model.consumer_ir
    )
    native_info = compiler.baseline_path().read_text(encoding="utf-8")
    words = (
        frozenset(decision_adapters.reader_evidence(inputs))
        | decision_interfaces.proven_reader_words()
    )
    patched = decision_rules.patch(
        native_info,
        info,
        baseline=native_info,
        reader_words=words,
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
        consumer_source=INFO,
    )
    return (
        {INFO: info, DEFAULT: strategy},
        {INFO: patched, DEFAULT: generated[DEFAULT]},
        {INFO: native_info, DEFAULT: inputs[DEFAULT]},
        model,
    )


def _values(policy, changes):
    values = {
        r.key: False if r.kind == "boolean" else max(r.minimum or 0, 0) for r in policy.readers
    }
    values.update(
        population=1_000_000,
        literacy=0.8,
        national_gdp=100,
        candidate_gdp=1,
        target_owned=False,
        bankruptcy_horizon=52,
        candidate_ig_approval=0,
        target_market_access=0,
        income=1,
        gdp=1,
    )
    values.update(changes)
    # Both aliases are one physical navy_size observation.
    if "navy" in changes:
        values["own_navy"] = changes["navy"]
    elif "own_navy" in changes:
        values["navy"] = changes["own_navy"]
    return values


def _overlay(text, field):
    begin = text.index(f"# SITAI BEGIN information:{field}")
    end = text.index(f"# SITAI END information:{field}", begin)
    return "\n".join(text[begin:end].splitlines()[1:])


CASES = [
    (CONSTRUCTION, {}, 1),
    (CONSTRUCTION, {"war_defeat": True}, 1.12),
    (CONSTRUCTION, {"war_defeat": True, "default": True}, 0.87),
    (CONSTRUCTION, {"war_defeat": True, "war": True, "default": True}, 0.87),
    (CONSTRUCTION, {"war_defeat": True, "net_surplus": None}, 1.12),
    (CONSTRUCTION, {"war_defeat": True, "net_surplus": 1}, 1.20),
    (CONSTRUCTION, {"industrial_route": True, "tools_balance": -1}, 1.10),
    (CONSTRUCTION, {"industrial_route": True, "tools_balance": -1, "net_surplus": 1}, 1.25),
    (CONSTRUCTION, {"industrial_route": True, "tools_balance": 0, "net_surplus": 1}, 1),
    (
        CONSTRUCTION,
        {
            "industrial_route": True,
            "tools_balance": -1,
            "loans": True,
            "debt_ratio": 0.4,
            "bankruptcy_horizon": 25.999,
        },
        0.95,
    ),
    (
        CONSTRUCTION,
        {
            "industrial_route": True,
            "tools_balance": -1,
            "loans": True,
            "debt_ratio": 0.4,
            "bankruptcy_horizon": 26,
        },
        1.10,
    ),
    (CONSTRUCTION, {"industrial_route": True, "tools_balance": -1, "default": None}, 1.10),
    (SCHOOL, {"literacy": 0.49}, 1.10),
    (SCHOOL, {"literacy": 0.5}, 1),
    (SCHOOL, {"literacy": 0.49, "default": True, "bureaucracy": -1}, 0.85),
    (SCHOOL, {"literacy": 0.49, "net_surplus": 1}, 1.20),
    (SCHOOL, {"literacy": 0.49, "bureaucracy": 1}, 1.18),
    (SCHOOL, {"literacy": 0.49, "net_surplus": 1, "bureaucracy": 1}, 1.25),
    (SCHOOL, {"literacy": 0.49, "net_surplus": 1, "bureaucracy": None}, 1.20),
    (SCHOOL, {"literacy": 0.49, "net_surplus": None, "bureaucracy": 1}, 1.18),
    (
        SCHOOL,
        {
            "literacy": 0.8,
            "population": 20_000_000,
            "net_surplus": 1,
            "bureaucracy": 1,
            "legitimacy": 100,
        },
        1,
    ),
    (TRADE, {"grain_balance": -1, "grain_price": 0.25}, 1.10),
    (TRADE, {"grain_balance": -1, "grain_price": 0.250001}, 1.20),
    (TRADE, {"grain_balance": -1, "grain_price": None, "war": True, "default": True}, 1.10),
    (
        TRADE,
        {
            "grain_balance": -1,
            "tools_balance": -1,
            "iron_balance": -1,
            "grain_price": 0.6,
            "tools_price": 0.6,
            "iron_price": 0.6,
        },
        1.20,
    ),
    (TRADE, {"net_surplus": 1, "bureaucracy": 1, "legitimacy": 100}, 1),
    (ECONOMY, {"industrial_route": True, "tools_balance": -1}, 1.10),
    (ECONOMY, {"resource_route": True, "iron_balance": -1, "iron_price": 0.26}, 1.20),
    (ECONOMY, {"resource_route": True, "iron_balance": 0, "iron_price": 0.6}, 1),
    (ECONOMY, {"resource_route": True, "iron_balance": None, "default": True}, 1),
    (STATE, {"target_homeland": True, "target_cultural_share": 0.25}, 1.05),
    (STATE, {"target_homeland": True, "target_cultural_share": 0.249999}, 1),
    (
        STATE,
        {
            "target_homeland": True,
            "target_cultural_share": 0.25,
            "fervor": 10,
            "expansion_route": True,
        },
        1.05,
    ),
    (
        STATE,
        {
            "target_homeland": True,
            "target_cultural_share": 0.25,
            "fervor": 10.01,
            "expansion_route": True,
        },
        1.20,
    ),
    (
        STATE,
        {
            "target_homeland": True,
            "target_cultural_share": 0.25,
            "fervor": 11,
            "expansion_route": True,
            "default": True,
            "bureaucracy": -1,
            "war_defeat": True,
        },
        0.84,
    ),
    (STATE, {"target_homeland": True, "target_isolated": True}, 0.90),
    (
        STATE,
        {
            "target_owned": True,
            "target_homeland": True,
            "target_cultural_share": 0.8,
            "default": True,
            "bureaucracy": -1,
            "war_defeat": True,
        },
        1,
    ),
    (SUBJECT, {"target_relations": 50}, 1),
    (SUBJECT, {"target_relations": 80}, 3),
    (SUBJECT, {"target_relations": 50, "own_army": 1, "target_army": 2}, -2),
    (SUBJECT, {"target_relations": 50, "candidate_gdp": 100}, 0),
    (SUBJECT, {"target_relations": None}, 0),
    (SUBJECT, {"candidate_existing_subject": True, "default": True, "war": True}, 1),
    (OVERLORD, {"overlord_relations": 50, "candidate_overlord_war": True, "war": True}, -2),
    (OVERLORD, {"overlord_relations": 80}, 3),
    (OVERLORD, {"overlord_relations": 80, "candidate_overlord_war": None}, 1),
    (OVERLORD, {"overlord_relations": 80, "current_overlord_relation": True, "liberty": 75}, 0),
    (OVERLORD, {"current_overlord_relation": True, "liberty": 74.999}, 0),
    (PORT, {"target_embargo": True, "navy": 1, "target_navy": 1}, 1),
    (PORT, {"target_embargo": True, "navy": 2, "target_navy": 1}, 3),
    (PORT, {"target_embargo": True, "navy": 1, "target_navy": 2}, -2),
    (PORT, {"target_embargo": True, "navy": 1, "target_navy": None}, 1),
    (PORT, {"target_embargo": True, "navy": 0}, 0),
    (
        NEGOTIATION,
        {"candidate_ig_clout": 0.1, "candidate_ig_approval": -1, "radical_share": 0.25},
        1.10,
    ),
    (
        NEGOTIATION,
        {
            "candidate_ig_clout": 0.1,
            "candidate_ig_approval": -1,
            "radical_share": 0.25,
            "legitimacy": 50,
        },
        1.25,
    ),
    (
        NEGOTIATION,
        {
            "candidate_ig_clout": 0.1,
            "candidate_ig_approval": -1,
            "radical_share": 0.25,
            "legitimacy": None,
            "insurrection": None,
            "default": True,
            "war": True,
        },
        1.10,
    ),
    (
        NEGOTIATION,
        {"candidate_ig_clout": 0.099999, "candidate_ig_approval": -1, "radical_share": 0.25},
        1,
    ),
    (
        NEGOTIATION,
        {"candidate_ig_clout": 0.1, "candidate_ig_approval": 0, "radical_share": 0.25},
        1,
    ),
]


@pytest.mark.parametrize(
    ("field", "changes", "expected"), [case for case in CASES if case[0] != SCHOOL]
)
def test_complete_need_cost_and_capacity_match_generated_pdx(production, field, changes, expected):
    policies, generated, _native, _model = production
    source = DEFAULT if field.startswith("ai_strategy_default.") else INFO
    policy = policies[source]
    values = _values(policy, changes)
    neutral = 0 if field in (SUBJECT, OVERLORD, PORT) else 1
    result = decision_rules.evaluate(policy, values, is_ai=True).get(field)
    assert (result[1] if result else neutral) == pytest.approx(expected)
    observed = pdx_eval.select(_overlay(generated[source], field), _facts(policy, values))
    assert (observed.delta if observed.operation else neutral) == pytest.approx(expected)


def test_every_consumer_retains_native_ast_and_player_and_missing_boundaries(production):
    policies, generated, native, _model = production
    for source, declared_fields in FIELDS.items():
        fields = declared_fields
        if version_contracts.active_version() == "1.15.1" and source == INFO:
            assert ("institution_scores", "institution_schools") not in policies[source].groups()
            fields = tuple(field for field in fields if field != SCHOOL)
        policy = policies[source]
        assert decision_rules.evaluate(policy, {}, is_ai=True) == {}
        assert decision_rules.evaluate(policy, _values(policy, {}), is_ai=False) == {}
        assert (
            decision_rules.evaluate(
                policy, _values(policy, {}), is_ai=True, enabled_domains=frozenset()
            )
            == {}
        )
        stripped = re.sub(
            r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
            "\n",
            generated[source],
            flags=re.DOTALL,
        )
        # Rendered formatting differs, so compare the complete ordered AST.
        before = parse_text(native[source])
        after = parse_text(stripped)
        assert not before.errors
        assert not after.errors
        from test_situated_social_governance_joint import _syntax

        if source == INFO:
            assert _syntax(before.root) == _syntax(after.root)
        else:
            left = _block(before.root, "ai_strategy_default")
            right = _block(after.root, "ai_strategy_default")
            for field in fields:
                assert _syntax(left.first(field.split(".")[-1])) == _syntax(
                    right.first(field.split(".")[-1])
                )
        for field in fields:
            overlay = _overlay(generated[source], field)
            missing = pdx_eval.select(
                overlay, {"ROOT": {"is_ai": True}, "other_country": {"in_default": True}}
            )
            assert missing.operation is None or missing.delta == (
                0 if field in (SUBJECT, OVERLORD, PORT) else 1
            )
            assert (
                pdx_eval.select(overlay, _facts(policy, _values(policy, {}), is_ai=False)).operation
                is None
            )


def test_exact_historical_retirements_have_live_same_consumer_successors(production):
    _policies, _generated, _native, model = production
    assert (
        hashlib.sha256(migration_baseline.DEFAULT_SOURCE.read_bytes()).hexdigest()
        == "fcce11e045e9933c13644a361da3a448330208c0b712ac3df615eed307aa55e6"
    )
    retired = migration_baseline.validated_retirements(model.consumer_ir)
    assert (INFO, "economic_development") in retired
    assert (DEFAULT, "comparative_friendly_subject") in retired


def _assignment(block: Block, key: str) -> Assignment:
    item = block.first(key)
    assert item is not None
    return item


def _block(block: Block, key: str) -> Block:
    node = _assignment(block, key).value
    assert isinstance(node, Block)
    return node


def _native_number(initial, body, facts):
    # The independent interpreter executes actual projected native operations
    # and the actual complete production overlay in source order.
    text = (
        "# ACTION original_tail [native]; projected numeric consumer\nif = { limit = { always = yes } multiply = { value = "
        + str(initial)
        + "\n"
        + body
        + "\n} }"
    )
    return pdx_eval.select(text, {**facts["ROOT"], **facts}).delta


def _render(node):

    if isinstance(node, Scalar):
        return node.text
    if isinstance(node, Assignment):
        return node.key + " " + node.op + " " + _render(node.value)
    assert isinstance(node, Block)
    return "{ " + " ".join(_render(item) for item in node.items) + " }"


def test_original_construction_zero_and_negotiation_and_overlord_clamps_still_execute(production):
    policies, generated, native, _model = production
    info = _block(parse_text(native[INFO]).root, "ai_strategy_default")
    construction = _block(info, CONSTRUCTION)
    terminal = construction.all("if")[-1]
    assert isinstance(terminal.value, Block)
    population_limit = _assignment(_block(terminal.value, "limit"), "total_population").value
    assert isinstance(population_limit, Scalar)
    assert population_limit.text == "250000"
    for population, construction_expected in ((250000, 0), (250001, 112)):
        values = _values(policies[INFO], {"war_defeat": True, "population": population})
        facts = _facts(policies[INFO], values)
        body = _render(terminal) + "\n" + _overlay(generated[INFO], CONSTRUCTION)
        assert _native_number(100, body, facts) == pytest.approx(construction_expected)
    native_strategy = _block(parse_text(native[DEFAULT]).root, "ai_strategy_default")
    for initial, expected in ((0, 0), (0.4, 0.5), (0.9, 1)):
        values = _values(
            policies[DEFAULT],
            {
                "candidate_ig_clout": 0.1,
                "candidate_ig_approval": -1,
                "radical_share": 0.25,
                "legitimacy": 50,
            },
        )
        clamp = _assignment(_block(native_strategy, "negotiation_chance"), "max")
        body = _overlay(generated[DEFAULT], NEGOTIATION) + "\n" + _render(clamp)
        assert _native_number(initial, body, _facts(policies[DEFAULT], values)) == pytest.approx(
            expected
        )
    body = _overlay(generated[DEFAULT], OVERLORD)
    block = _block(native_strategy, "become_subject_value")
    body += "\n" + _render(block.first("max")) + "\n" + _render(block.first("min"))
    for initial, expected in ((-1, 0), (-199, -196), (-250, -200)):
        values = _values(policies[DEFAULT], {"overlord_relations": 80})
        assert _native_number(initial, body, _facts(policies[DEFAULT], values)) == pytest.approx(
            expected
        )


def test_need_and_cost_switching_recomputes_without_selection_memory(production):
    policies, generated, _native, _model = production
    policy = policies[INFO]
    overlay = _overlay(generated[INFO], CONSTRUCTION)
    for changes, expected in (
        ({"war_defeat": True}, 1.12),
        ({"war_defeat": True, "default": True}, 0.87),
        ({"war_defeat": False, "default": True}, 0.75),
        ({"war_defeat": None, "default": True}, 0.75),
        ({"war_defeat": False, "default": False}, 1),
        ({"war_defeat": True, "default": False}, 1.12),
    ):
        values = _values(
            policy, {**changes, "candidate_selected": True, "construction_queued": True}
        )
        observed = pdx_eval.select(overlay, _facts(policy, values))
        assert observed.delta == pytest.approx(expected)


def test_same_need_does_not_stack_and_actual_cost_envelopes_remain_bounded(production):
    policies, generated, _native, _model = production
    policy = policies[INFO]
    cases = [
        (
            CONSTRUCTION,
            {"war_defeat": True, "industrial_route": True, "tools_balance": -1, "net_surplus": 1},
            1.25,
        ),
        (
            TRADE,
            {
                "grain_balance": -1,
                "tools_balance": -1,
                "iron_balance": -1,
                "grain_price": 0.6,
                "tools_price": 0.6,
                "iron_price": 0.6,
            },
            1.2,
        ),
        (
            STATE,
            {
                "target_homeland": True,
                "target_isolated": True,
                "default": True,
                "bureaucracy": -1,
                "war_defeat": True,
            },
            0.54,
        ),
    ]
    for field, changes, expected in cases:
        observed = pdx_eval.select(
            _overlay(generated[INFO], field), _facts(policy, _values(policy, changes))
        )
        assert observed.delta == pytest.approx(expected)
        assert 0.5 <= observed.delta <= 1.5


@pytest.mark.parametrize("version", ["1.14.5", "1.15.0"])
@pytest.mark.parametrize(
    ("field", "changes", "expected"), [case for case in CASES if case[0] == SCHOOL]
)
def test_historical_school_complete_need_cost_and_capacity_has_independent_pdx(
    version, field, changes, expected
):
    with version_contracts.select_version(version):
        policy, blocks = _historical_school_blocks(version)
        values = _values(policy, changes)
        result = decision_rules.evaluate(policy, values, is_ai=True).get(field)
        assert (result[1] if result else 1) == pytest.approx(expected)
        assert pdx_eval.select(blocks[field], _facts(policy, values)).delta == pytest.approx(
            expected
        )


@cache
def _historical_school_blocks(version):
    from test_full_information import _SYNTHETIC_READER_EVIDENCE

    with version_contracts.select_version(version):
        policy, _ = compiler.compile_policy(decision_rules.load(), INFO, compiler.load_model())
        baseline = compiler.baseline_path().read_text(encoding="utf-8")
        generated = decision_rules.patch(
            baseline,
            policy,
            baseline=baseline,
            reader_evidence=_SYNTHETIC_READER_EVIDENCE,
            country_policy=country_state.load(),
        )
        return policy, {SCHOOL: _overlay(generated, SCHOOL)}
