"""D5 support sources must drive typed reference and independently parsed PDX."""

from copy import deepcopy
from dataclasses import replace

import pytest

from pdx.situated import actions as action_source
from pdx.situated import compiler, evidence, pdx_eval, support_signals

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def model():
    return compiler.load_model()


def _load_with_sources(monkeypatch, model, change):
    sources = deepcopy(model.support_sources)
    change(sources)
    monkeypatch.setattr(compiler, "_load_supporting_sources", lambda: sources)
    return compiler.load_model()


def _reference(model, field, values):
    # The handwritten original consumer baseline is 10. Do not manufacture a
    # production binding to bypass exact source/IR validation in these unit tests.
    actions = compiler.evaluate_actions(model, values, is_ai=True)
    return 10.0 + actions.get(field, ("", 0.0))[1]


def test_every_active_signal_has_real_ir_users_and_reader_provenance(model):
    assert model.support_signals is not None
    rows = model.decision_ir
    for signal in model.support_signals.signals:
        assert signal.alias.startswith("support_")
        assert signal.source.trigger
        assert signal.source.source
        assert signal.source.identity
        assert signal.source.scope == "root"
        assert set(signal.actions) == {
            row.action_id for row in rows if signal.alias in support_signals.references(row)
        }
    assert model.support_signals.reserved
    assert model.contract()["supporting_signals"]["persistent_state"] is False
    assert model.contract()["goals"]["dynamic"] is True
    assert model.contract()["goals"]["activation"] == "per_action_live_rank_fact_sets_need_tier"
    assert model.contract()["goals"]["unknown"] == "rank_fact_unknown_uses_neutral_tier"
    assert model.contract()["goals"]["priority_role"] == (
        "legacy_metadata_not_utility; observed_rank_terms_contribute_amount"
    )


def test_pressure_source_counterfactual_changes_production_and_reference(monkeypatch, model):
    changed = _load_with_sources(
        monkeypatch,
        model,
        lambda sources: sources["pressures.toml"]["pressures"]["fiscal_default"].update(
            source_fact="war"
        ),
    )
    field = "diplomatic_play_neutrality"
    values = {"default": True, "war": False, "no_default": False, "peace": True}
    engine = {"ROOT": {"is_ai": True, "in_default": True, "is_at_war": False}}
    before = pdx_eval.select(compiler.strategy_overlay(model)[field], engine)
    after = pdx_eval.select(compiler.strategy_overlay(changed)[field], engine)
    assert (before.action_id, before.delta) == ("joint_fiscal_neutrality", 8.0)
    assert after.action_id == "joint_fiscal_neutrality"
    assert after.operation == "add"
    assert after.fallback == "selected"
    assert after.delta == 0.0
    assert _reference(model, field, values) == 18
    assert _reference(changed, field, values) == 10
    assert compiler.strategy_overlay(model)[field] != compiler.strategy_overlay(changed)[field]


def test_caller_cannot_forge_support_alias_or_fill_unknown_as_healthy(model):
    signal = next(s for s in model.support_signals.signals if s.id == "fiscal_default")
    values = {"war": False, "no_default": False, "peace": True, signal.alias: True}
    projected = model.support_signals.values(values)
    assert projected[signal.alias] is None
    field = "diplomatic_play_neutrality"
    assert _reference(model, field, values) == 10
    assert (
        model.support_signals.values({"default": False, signal.alias: True})[signal.alias] is False
    )


def test_numeric_cost_alias_is_real_ir_input_and_preserves_zero_false_and_unknown(model):
    support = model.support_signals
    debt = next(s for s in support.signals if s.id == "debt_service")
    assert any(p.fact == debt.alias for row in model.decision_ir for p in row.commitment_when)
    assert support.values({"debt_ratio": 0})[debt.alias] == 0
    assert support.values({"debt_ratio": False})[debt.alias] is None
    assert support.values({debt.alias: 0})[debt.alias] is None
    assert debt.source.minimum == 0
    assert debt.unit == "debt_to_credit_ratio"


def test_capacity_source_counterfactual_changes_actual_cost(monkeypatch, model):
    changed = _load_with_sources(
        monkeypatch,
        model,
        lambda sources: sources["capacities.toml"]["capacities"]["fiscal"].update(
            source_fact="income"
        ),
    )
    field = "economic_vs_government_spending_balance"
    values = {
        "peace": True,
        "war": False,
        "no_default": True,
        "default": False,
        "literacy_low": False,
        "literacy_ready": True,
        "debt_ratio": 0,
        "net_surplus": 1,
        "income": -1,
        "bureaucracy": 0,
        "legitimacy": 75,
        "coord_evidence_need_industry": False,
        "coord_need_education": False,
        "no_insurrection": False,
        "insurrection": True,
        "ongoing_insurrection": True,
        "stable_legitimacy": False,
        "strong_legitimacy": False,
    }
    engine = {
        "ROOT": {
            "is_ai": True,
            "is_at_war": False,
            "in_default": False,
            "literacy_rate": 0.8,
            "scaled_debt": 0,
            "net_total_income": 1,
            "fixed_income": -1,
            "bureaucracy": 0,
            "legitimacy": 75,
            "any_insurrection_ongoing": True,
            "sitai_context_evidence_need_industry": False,
            "sitai_context_need_education": False,
        }
    }
    for candidate, expected in ((model, 0.175), (changed, 0.075)):
        selected = pdx_eval.select(compiler.strategy_overlay(candidate)[field], engine)
        assert selected.action_id == "joint_economic_balance"
        assert selected.delta == pytest.approx(expected)
        assert _reference(candidate, field, values) == pytest.approx(10 + expected)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda x: x.update(unknown_key=True),
        lambda x: x.update(ttl_days=30),
        lambda x: x.update(source_fact="missing"),
        lambda x: x.update(scope="owner"),
        lambda x: x.update(unit="normalized"),
        lambda x: x.update(actions=["missing"]),
        lambda x: x.update(actions=[]),
        lambda x: x.update(actions=["fiscal_recovery", "fiscal_recovery"]),
        lambda x: x.update(value=float("nan")),
        lambda x: x.update(op="!="),
        lambda x: x.update(op=[]),
        lambda x: x.update(mode=[]),
        lambda x: x.update(alias="default"),
    ],
)
def test_malformed_support_config_fails_closed(monkeypatch, model, mutation):
    with pytest.raises(ValueError):
        _load_with_sources(
            monkeypatch,
            model,
            lambda sources: mutation(sources["pressures.toml"]["pressures"]["fiscal_default"]),
        )


def test_duplicate_alias_and_unused_or_reserved_consumers_are_rejected(monkeypatch, model):
    original = deepcopy(model.support_sources)
    raw = original["pressures.toml"]["pressures"]
    raw["copy"] = deepcopy(raw["fiscal_default"])
    monkeypatch.setattr(compiler, "_load_supporting_sources", lambda: original)
    with pytest.raises(ValueError):
        compiler.load_model()
    raw.pop("copy")
    raw["fiscal_default"]["actions"] = ["political_reform"]
    with pytest.raises(ValueError):
        compiler.load_model()


def test_goals_reject_unknown_fields_ttl_and_unused_goal(monkeypatch, model):
    for change in (
        {"ttl_days": 10},
        {"priority": True},
        {"unknown": "healthy"},
        {"consumers": ["fiscal_neutrality"]},
        {"source_needs": ["support_fiscal_default"]},
        {"pressure": ["fiscal_default"]},
    ):
        with pytest.raises(ValueError):
            _load_with_sources(
                monkeypatch,
                model,
                lambda sources, change=change: sources["goals.toml"]["goals"]["capacity"].update(
                    change
                ),
            )


def _rank_inputs():
    values = {
        "peace": True,
        "war": False,
        "default": False,
        "no_default": True,
        "literacy_low": True,
        "literacy_ready": False,
        "debt_ratio": 0,
        "net_surplus": 1,
        "bureaucracy": 0,
        "legitimacy": 75,
        "coord_evidence_need_industry": True,
        "coord_need_education": True,
        "no_insurrection": False,
        "insurrection": True,
        "ongoing_insurrection": True,
        "stable_legitimacy": False,
        "strong_legitimacy": False,
    }
    engine = {
        "ROOT": {
            "is_ai": True,
            "is_at_war": False,
            "in_default": False,
            "literacy_rate": 0.2,
            "scaled_debt": 0,
            "net_total_income": 1,
            "bureaucracy": 0,
            "legitimacy": 75,
            "any_insurrection_ongoing": True,
            "sitai_context_evidence_need_industry": True,
            "sitai_context_need_education": True,
        }
    }
    return values, engine


@pytest.mark.parametrize("category", ["opportunities", "goals"])
def test_opportunity_and_goal_counterfactuals_change_actual_rank_or_qualification(
    monkeypatch, model, category
):
    def mutate(sources):
        if category == "goals":
            sources["goals.toml"]["goals"]["structure"]["priority"] = 100
        else:
            sources["opportunities.toml"]["opportunities"]["education"]["value"] = False

    changed = _load_with_sources(monkeypatch, model, mutate)
    values, engine = _rank_inputs()
    if category == "opportunities":
        values["coord_evidence_need_industry"] = False
        engine["ROOT"]["sitai_context_evidence_need_industry"] = False
    field = "economic_vs_government_spending_balance"
    # Removing the education opportunity cancels its -.10 base and -.025 need;
    # changing rank metadata cannot select away either signed contribution.
    expected_before = 0.025 if category == "opportunities" else 0.05
    expected_after = 0.15 if category == "opportunities" else 0.05
    for candidate, expected in ((model, expected_before), (changed, expected_after)):
        selected = pdx_eval.select(compiler.strategy_overlay(candidate)[field], engine)
        assert selected.action_id == "joint_economic_balance"
        assert selected.delta == pytest.approx(expected)
        assert _reference(candidate, field, values) == pytest.approx(10 + expected)
    assert (
        compiler.strategy_overlay(model)[field] == compiler.strategy_overlay(changed)[field]
    ) is (category == "goals")


@pytest.mark.parametrize(
    ("debt", "expected_delta"),
    [(0.0, 0.05), (0.5, 0.03)],
    ids=["affordable-industry", "debt-cost-switches-to-education"],
)
def test_actual_economy_cost_changes_selection_between_live_goals(model, debt, expected_delta):
    values, engine = _rank_inputs()
    values["debt_ratio"] = debt
    engine["ROOT"]["scaled_debt"] = debt
    field = "economic_vs_government_spending_balance"
    selected = pdx_eval.select(compiler.strategy_overlay(model)[field], engine)
    assert selected.action_id == "joint_economic_balance"
    assert selected.delta == pytest.approx(expected_delta)
    assert _reference(model, field, values) == pytest.approx(10 + selected.delta)


def test_commitment_source_counterfactual_uses_numeric_reader_not_caller_alias(monkeypatch, model):
    changed = _load_with_sources(
        monkeypatch,
        model,
        lambda sources: sources["commitments.toml"]["commitments"]["diplomatic"].update(
            source_fact="war"
        ),
    )
    values = {"subject": True, "war": False, "support_diplomatic": True}
    assert model.support_signals.values(values)["support_diplomatic"] is True
    assert changed.support_signals.values(values)["support_diplomatic"] is False
    field = "recklessness"
    typed = {
        **values,
        "peace": True,
        "no_default": True,
        "default": False,
        "stable_legitimacy": False,
        "infamy": 0,
    }
    engine = {
        "ROOT": {
            "is_ai": True,
            "is_subject": True,
            "is_at_war": False,
            "in_default": False,
            "legitimacy": 0,
            "infamy": 0,
        }
    }
    before = pdx_eval.select(compiler.strategy_overlay(model)[field], engine)
    after = pdx_eval.select(compiler.strategy_overlay(changed)[field], engine)
    assert before.action_id == after.action_id == "joint_diplomatic_recklessness"
    assert before.delta == 1.0
    assert after.delta == 2.0
    assert before.delta != after.delta
    for candidate, selection in ((model, before), (changed, after)):
        assert _reference(candidate, field, typed) == pytest.approx(10 + selection.delta)


def test_numeric_predicate_compiles_finite_comparison_with_same_zero_boundary(monkeypatch, model):
    changed = _load_with_sources(
        monkeypatch,
        model,
        lambda sources: sources["pressures.toml"]["pressures"]["fiscal_default"].update(
            source_fact="bureaucracy",
            unit="capacity_balance",
            op="<",
            value=0,
        ),
    )
    field = "diplomatic_play_neutrality"
    for value, expected in ((-1, 8.0), (0, 0.0), (1, 0.0), (None, 0.0)):
        typed = {"bureaucracy": value, "war": False, "peace": True, "no_default": False}
        engine = {
            "ROOT": {"is_ai": True, "bureaucracy": value, "is_at_war": False, "in_default": True}
        }
        selected = pdx_eval.select(compiler.strategy_overlay(changed)[field], engine)
        assert selected.delta == expected
        assert _reference(changed, field, typed) == 10 + expected
    assert "bureaucracy < 0" in compiler.strategy_overlay(changed)[field]


def test_numeric_cost_missing_or_nonfinite_stays_unknown_and_expensive(model):
    row = next(row for row in model.decision_ir if row.action_id == "industrial_foundation")
    for debt in (None, False, float("nan"), float("inf")):
        typed = {"debt_ratio": debt, "net_surplus": 1, "bureaucracy": 0, "legitimacy": 75}
        assert model.support_signals.values(typed)["support_debt_service"] is None
        assert compiler._row_delta(row, typed, model=model) == pytest.approx(0.05)


def test_bounded_numeric_predicate_is_explicitly_unsupported(monkeypatch, model):
    with pytest.raises(ValueError, match="有界数值"):
        _load_with_sources(
            monkeypatch,
            model,
            lambda sources: sources["pressures.toml"]["pressures"]["fiscal_default"].update(
                source_fact="debt_ratio",
                unit="debt_to_credit_ratio",
                op=">",
                value=0.4,
            ),
        )


def _support_inputs():
    _, actions = action_source.load(compiler.ACTIONS)
    declared = evidence.load(compiler.FACTS)
    facts = compiler._reader_facts(declared)
    return compiler._load_supporting_sources(), facts, actions, compiler._reader_shapes(declared)


def test_support_shape_guard_keeps_default_typed_predicate_inputs():
    sources, facts, actions, readers = _support_inputs()
    support = support_signals.load(sources, facts, actions, reader_shapes=readers)
    assert len(support.signals) == 11
    assert support.values({"literacy_low": True})["support_education"] is True
    assert support.values({"literacy_low": False})["support_education"] is False


def test_support_rejects_real_owner_reader_before_flattening():
    sources, facts, actions, readers = _support_inputs()
    sources["capacities.toml"]["capacities"]["administrative"]["source_fact"] = (
        "state_owner_bureaucracy"
    )
    with pytest.raises(ValueError, match=r"reader.*(path|路径|scope)"):
        support_signals.load(sources, facts, actions, reader_shapes=readers)


@pytest.mark.parametrize(
    "reader_changes",
    [
        {"path": ("owner",)},
        {"path": ("market",)},
        {"parameters": (("target_country", "root"),)},
        {"value_field": "value"},
        {"parameters": (("pop_type", "academics"),), "value_field": "percent"},
        {"scope": "target_state"},
    ],
    ids=["owner", "market", "parameters", "value-field", "parameterized-scalar", "scope"],
)
def test_support_checks_original_reader_shape_not_flat_evidence(reader_changes):
    sources, facts, actions, readers = _support_inputs()
    # EvidenceSpec remains exactly the original flat root scalar.  Change a
    # non-first raw reader to prove all same-key origins are inspected.
    original = readers["bureaucracy"]
    readers["bureaucracy"] = (*original[:-1], replace(original[-1], **reader_changes))
    with pytest.raises(ValueError, match=r"reader.*(path|parameters|value_field|scope|路径)"):
        support_signals.load(sources, facts, actions, reader_shapes=readers)


def test_support_reader_provenance_is_required_and_ambiguous_reader_rejected():
    sources, facts, actions, readers = _support_inputs()
    missing = {key: value for key, value in readers.items() if key != "bureaucracy"}
    with pytest.raises(ValueError, match="原始 reader 形状"):
        support_signals.load(sources, facts, actions, reader_shapes=missing)
    readers["bureaucracy"] = (
        *readers["bureaucracy"],
        replace(readers["bureaucracy"][0], engine="other_engine"),
    )
    with pytest.raises(ValueError, match="同名定义不一致"):
        support_signals.load(sources, facts, actions, reader_shapes=readers)
