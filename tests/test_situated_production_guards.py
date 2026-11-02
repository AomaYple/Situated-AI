"""生产行动的唯一 IR 来源与线性联合贡献合同。"""

from dataclasses import replace

import pytest

from pdx import decision_rules
from pdx.situated import compiler, pdx_eval

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def production_model():
    return compiler.load_model()


def _rows(model, rows):
    """构造语义一致的 IR 变体；损坏变体由各负例直接构造。"""
    by_id = {row.action_id: row for row in rows}
    bundle = model.consumer_ir
    assert bundle is not None
    writers = tuple(
        replace(writer, action=by_id[writer.definition]) if writer.kind == "action_card" else writer
        for writer in bundle.writers
        if writer.kind != "action_card" or writer.definition in by_id
    )
    return replace(
        model,
        decision_ir=tuple(rows),
        consumer_ir=replace(bundle, actions=tuple(rows), writers=writers),
    )


def _damaged_model(model, damage):
    bundle = model.consumer_ir
    assert bundle is not None
    writer = next(item for item in bundle.writers if item.kind == "action_card")
    row = writer.action
    assert row is not None
    if damage == "missing_writer":
        return replace(
            model,
            consumer_ir=replace(bundle, writers=tuple(w for w in bundle.writers if w != writer)),
        )
    if damage == "duplicate_writer":
        return replace(model, consumer_ir=replace(bundle, writers=(*bundle.writers, writer)))
    if damage == "missing_bundle_action":
        return replace(
            model,
            consumer_ir=replace(bundle, actions=tuple(a for a in bundle.actions if a != row)),
        )
    if damage == "duplicate_bundle_action":
        return replace(model, consumer_ir=replace(bundle, actions=(*bundle.actions, row)))
    if damage == "different_decision_row":
        return replace(
            model,
            decision_ir=tuple(
                replace(a, base=a.base + 1) if a == row else a for a in model.decision_ir
            ),
        )
    changes: dict[str, dict[str, object]] = {
        "writer_source": {"source": "wrong/source.toml"},
        "writer_definition": {"definition": "wrong_action"},
        "writer_id": {"writer_id": "wrong_writer"},
        "writer_consumer": {"consumer_id": "wrong_consumer"},
        "writer_field": {"field": "wrong_field"},
        "writer_operation": {"operation": "multiply"},
        "writer_actor": {"actor": "owner"},
        "writer_target": {"target": "target_state"},
        "writer_tail": {"vanilla_tail": "wrong_tail"},
        "writer_owner": {"owner": "other_owner"},
        "writer_action_missing": {"action": None},
        "writer_action_drift": {"action": replace(row, base=row.base + 1)},
    }
    changed = replace(writer, **changes[damage])
    return replace(
        model,
        consumer_ir=replace(
            bundle, writers=tuple(changed if w == writer else w for w in bundle.writers)
        ),
    )


@pytest.mark.parametrize("entry", ["overlay", "reference", "legacy_compile"])
@pytest.mark.parametrize(
    "damage",
    [
        "missing_writer",
        "duplicate_writer",
        "missing_bundle_action",
        "duplicate_bundle_action",
        "different_decision_row",
        "writer_source",
        "writer_definition",
        "writer_id",
        "writer_consumer",
        "writer_field",
        "writer_operation",
        "writer_actor",
        "writer_target",
        "writer_tail",
        "writer_owner",
        "writer_action_missing",
        "writer_action_drift",
    ],
)
def test_all_production_entries_reject_inconsistent_explicit_writer(
    production_model, entry, damage
):
    """删除或漂移 source map 不得留下仍可生成的匿名卡。"""
    model = _damaged_model(production_model, damage)
    entrypoint = {
        "overlay": lambda: compiler.strategy_overlay(model),
        "reference": lambda: compiler.evaluate_policy(
            decision_rules.load(), {}, is_ai=True, config_model=model
        ),
        "legacy_compile": lambda: compiler.compile_policy(
            decision_rules.load(), "mod/decisions/information.toml", config_model=model
        ),
    }[entry]
    with pytest.raises(ValueError, match=r"IR|writer|行动"):
        entrypoint()


def _economy_values():
    values = {
        "peace": True,
        "war": False,
        "default": False,
        "no_default": True,
        "no_insurrection": True,
        "insurrection": False,
        "ongoing_insurrection": False,
        "stable_legitimacy": True,
        "strong_legitimacy": False,
        "literacy_low": True,
        "bureaucracy_positive": True,
        "legitimacy": 60,
        "bureaucracy": 1,
        "debt_ratio": 0.4,
        "net_surplus": 1,
    }
    facts = {
        "is_ai": True,
        "is_at_war": False,
        "in_default": False,
        "any_insurrection_ongoing": False,
        "legitimacy": 60,
        "bureaucracy": 1,
        "literacy_rate": 0.3,
        "scaled_debt": 0.4,
        "net_total_income": 1,
    }
    return values, facts


@pytest.mark.parametrize(
    ("stronger", "unknown", "expected"),
    [(False, False, 0.2), (True, False, 0.225), (True, True, 0.175)],
)
def test_only_one_proven_complement_contributes_to_production_delta(
    production_model, stronger, unknown, expected
):
    """Historical identity: both independent observed complements now contribute."""
    model = production_model
    if stronger:
        model = _rows(
            model,
            tuple(
                replace(
                    row,
                    relations=tuple(
                        replace(rel, strength=0.05) if rel.target == "political_reform" else rel
                        for rel in row.relations
                    ),
                )
                if row.action_id == "industrial_foundation"
                else row
                for row in model.decision_ir
            ),
        )
    values, facts = _economy_values()
    # Real completion evidence is strong legitimacy and ready literacy; the
    # education intention itself is ineligible here, yet its completed fact counts.
    values.update(legitimacy=80, strong_legitimacy=True, literacy_ready=True, literacy_low=False)
    facts.update(legitimacy=80, literacy_rate=0.8)
    if unknown:
        values.update(no_insurrection=None, insurrection=None, ongoing_insurrection=None)
        facts["any_insurrection_ongoing"] = None
    field = "economic_vs_government_spending_balance"
    actual = compiler.evaluate_actions(model, values, is_ai=True)
    assert actual[field][1] == pytest.approx(expected)
    generated = pdx_eval.select(compiler.strategy_overlay(model)[field], facts)
    assert generated.action_id == "joint_economic_balance"
    assert generated.delta == pytest.approx(expected)


def test_complement_order_is_deterministic_under_source_permutation(production_model):
    rows = tuple(
        replace(row, relations=tuple(reversed(row.relations)))
        for row in production_model.decision_ir
    )
    reordered = _rows(production_model, rows)
    assert compiler.strategy_overlay(reordered) == compiler.strategy_overlay(production_model)


@pytest.mark.parametrize("strength", [float("nan"), float("inf"), -1.0])
def test_complement_strength_must_be_finite_and_positive_before_ordering(
    production_model, strength
):
    model = _rows(
        production_model,
        tuple(
            replace(row, relations=tuple(replace(rel, strength=strength) for rel in row.relations))
            if row.action_id == "industrial_foundation"
            else row
            for row in production_model.decision_ir
        ),
    )
    with pytest.raises(ValueError, match=r"关系|互补"):
        compiler.strategy_overlay(model)
    values, _ = _economy_values()
    with pytest.raises(ValueError, match=r"关系|互补"):
        compiler.evaluate_actions(model, values, is_ai=True)


def test_auxiliary_if_chain_selects_only_first_proven_branch():
    text = """# ACTION source [test];
if = { limit = { is_ai = yes } add = { value = 1
if = { limit = { stronger = yes } add = 0.5 }
else_if = { limit = { weaker = yes } add = 0.25 }
min = -5 max = 5 } }
"""
    for stronger, expected in ((True, 1.5), (False, 1.25), (None, 1.25)):
        result = pdx_eval.select(text, {"is_ai": True, "stronger": stronger, "weaker": True})
        assert result.delta == expected


def test_auxiliary_else_if_without_if_is_rejected():
    text = """# ACTION source [test];
if = { limit = { is_ai = yes } add = { value = 1
else_if = { limit = { weaker = yes } add = 0.25 } } }
"""
    with pytest.raises(pdx_eval.UnsupportedPdxError, match=r"else_if|分支"):
        pdx_eval.select(text, {"is_ai": True, "weaker": True})


def test_core_else_if_without_if_is_rejected():
    text = """# ACTION source [test];
else_if = { limit = { is_ai = yes } add = 1 }
"""
    with pytest.raises(pdx_eval.UnsupportedPdxError, match=r"else_if|分支"):
        pdx_eval.select(text, {"is_ai": True})


def test_marked_else_if_fragment_uses_explicit_false_predecessor():
    text = """# ACTION source [generated];
else_if = { limit = { is_ai = yes } add = 1 }
"""
    fragment = pdx_eval.marked_block(text, "source")
    assert "if = { limit = { always = no } }" in fragment
    assert pdx_eval.select(fragment, {"is_ai": True}).action_id == "source"


def test_auxiliary_branch_rejects_unregistered_operations():
    text = """# ACTION source [test];
if = { limit = { is_ai = yes } add = { value = 1
if = { limit = { weaker = yes } add = 0.25 mystery = 1 } } }
"""
    with pytest.raises(pdx_eval.UnsupportedPdxError, match=r"未登记|不支持"):
        pdx_eval.select(text, {"is_ai": True, "weaker": True})


@pytest.mark.parametrize("disposition", ["merge", "remove", "retain_vanilla"])
@pytest.mark.parametrize("entry", ["overlay", "reference", "legacy_compile"])
def test_in_memory_disposition_cannot_bypass_production_validation(
    production_model, disposition, entry
):
    row = production_model.binding_rows[0]
    model = replace(
        production_model,
        binding_rows=(replace(row, disposition=disposition), *production_model.binding_rows[1:]),
    )
    entrypoint = {
        "overlay": lambda: compiler.strategy_overlay(model),
        "reference": lambda: compiler.evaluate_policy(
            decision_rules.load(), {}, is_ai=True, config_model=model
        ),
        "legacy_compile": lambda: compiler.compile_policy(
            decision_rules.load(), config_model=model
        ),
    }[entry]
    with pytest.raises(ValueError, match="处置"):
        entrypoint()


@pytest.mark.parametrize(
    ("industry", "education", "expected_action", "expected_delta"),
    [
        (False, False, "joint_economic_balance", 0.045),
        (True, False, "joint_economic_balance", 0.070),
        (False, True, "joint_economic_balance", 0.020),
        (None, None, "joint_economic_balance", 0.045),
    ],
)
def test_production_need_rank_changes_actual_consumer_selection(
    production_model, industry, education, expected_action, expected_delta
):
    """Observed demand amounts change the joint delta, without selecting one card."""
    values, facts = _economy_values()
    values.update(coord_evidence_need_industry=industry, coord_need_education=education)
    facts.update(
        sitai_context_evidence_need_industry=industry, sitai_context_need_education=education
    )
    field = "economic_vs_government_spending_balance"
    reference = compiler.evaluate_actions(production_model, values, is_ai=True)
    assert reference[field][0] == expected_action
    assert reference[field][1] == pytest.approx(expected_delta)
    actual = pdx_eval.select(compiler.strategy_overlay(production_model)[field], facts)
    assert actual.action_id == expected_action
    assert actual.delta == pytest.approx(expected_delta)


def test_production_goal_priority_can_break_tied_need_tiers(production_model):
    """Historical priority identity: static priority cannot alter actual utility."""
    values, facts = _economy_values()
    values.update(coord_evidence_need_industry=True, coord_need_education=True)
    facts.update(sitai_context_evidence_need_industry=True, sitai_context_need_education=True)
    field = "economic_vs_government_spending_balance"
    for goal_id in ("structure", "capacity"):
        model = replace(
            production_model,
            goals=tuple((key, 100 if key == goal_id else 0) for key, _ in production_model.goals),
            goal_specs=tuple(
                replace(goal, priority=100 if goal.id == goal_id else 0)
                for goal in production_model.goal_specs
            ),
        )
        assert compiler.evaluate_actions(model, values, is_ai=True)[field][1] == pytest.approx(
            0.045
        )
        actual = pdx_eval.select(compiler.strategy_overlay(model)[field], facts)
        assert actual.action_id == "joint_economic_balance"
        assert actual.delta == pytest.approx(0.045)


@pytest.mark.parametrize(
    ("debt", "expected_action", "expected_delta"),
    [
        (-0.01, "joint_economic_balance", 0.025),
        (0.0, "joint_economic_balance", 0.045),
        (0.4, "joint_economic_balance", 0.045),
        (0.41, "joint_economic_balance", 0.025),
    ],
)
def test_cost_boundaries_preserve_zero_and_reject_negative_debt(
    production_model, debt, expected_action, expected_delta
):
    values, facts = _economy_values()
    values["debt_ratio"] = debt
    facts["scaled_debt"] = debt
    field = "economic_vs_government_spending_balance"
    actual = compiler.evaluate_actions(production_model, values, is_ai=True)
    assert actual[field][0] == expected_action
    assert actual[field][1] == pytest.approx(expected_delta)
    generated = pdx_eval.select(compiler.strategy_overlay(production_model)[field], facts)
    assert generated.action_id == expected_action
    assert generated.delta == pytest.approx(expected_delta)


@pytest.mark.parametrize(
    ("name", "value"), [("legitimacy", -0.01), ("legitimacy", 100.01), ("debt_ratio", -1)]
)
def test_out_of_range_cost_is_local_unknown_and_preserves_vanilla(production_model, name, value):
    values, facts = _economy_values()
    values[name] = value
    if name == "legitimacy":
        values.update(stable_legitimacy=False, strong_legitimacy=False)
    facts[{"debt_ratio": "scaled_debt", "legitimacy": "legitimacy"}[name]] = value
    field = "economic_vs_government_spending_balance"
    # Invalid pressure charges only the relevant conservative cost; it does not
    # veto both known action qualifications or unrelated consumers.
    expected = 0.025 if name == "debt_ratio" else 0.045
    reference = compiler.evaluate_actions(production_model, values, is_ai=True)
    assert reference[field][1] == pytest.approx(expected)
    actual = pdx_eval.select(compiler.strategy_overlay(production_model)[field], facts)
    assert actual.action_id == "joint_economic_balance"
    assert actual.delta == pytest.approx(expected)
    unaffected = pdx_eval.select(
        compiler.strategy_overlay(production_model)["recklessness"], {**facts, "is_at_war": True}
    )
    assert unaffected.action_id == "joint_diplomatic_recklessness"
    assert unaffected.delta == -4.0


@pytest.mark.parametrize(
    ("debt", "expected"), [(0.4, "joint_economic_balance"), (0.41, "joint_economic_balance")]
)
def test_demand_rank_still_reduces_expensive_commitment(production_model, debt, expected):
    _values, facts = _economy_values()
    facts.update(
        scaled_debt=debt,
        sitai_context_need_education=True,
        sitai_context_evidence_need_industry=False,
    )
    actual = pdx_eval.select(
        compiler.strategy_overlay(production_model)["economic_vs_government_spending_balance"],
        facts,
    )
    assert actual.action_id == expected
    assert actual.delta == pytest.approx(0.020 if debt == 0.4 else 0.0)


def test_rank_declarations_reject_missing_or_duplicate_fact_and_goal(production_model):
    from pdx.situated.schema import RankTerm

    source = next(
        row for row in production_model.decision_ir if row.action_id == "industrial_foundation"
    )
    for terms in (
        (RankTerm("unknown_fact", "capacity", 1, "flag"),),
        (RankTerm("coord_need_education", "missing_goal", 1, "flag"),),
        (*source.rank_terms, *source.rank_terms),
    ):
        changed = _rows(
            production_model,
            tuple(
                replace(row, rank_terms=terms) if row == source else row
                for row in production_model.decision_ir
            ),
        )
        with pytest.raises(ValueError, match="rank"):
            compiler.strategy_overlay(changed)


def test_rank_partition_budget_is_frozen_for_real_consumers(production_model):
    """Bound actual emitted branches, not the retired Cartesian state count."""
    for consumer in production_model.consumers:
        rows = [row for row in production_model.decision_ir if row.consumer_id == consumer.id]
        terms = sum(
            1
            + len(row.rank_terms)
            + bool(row.commitment_when)
            + bool(row.political_when)
            + len(row.relations)
            for row in rows
        )
        text = compiler.strategy_overlay(production_model)[consumer.field]
        # One qualification per contribution and one extra cheap-cost test.
        assert text.count("limit =") <= 1 + terms + 2 * len(rows)
        assert text.count("min =") == text.count("max =") == 1


def test_rank_terms_survive_source_ir_and_instance_dependency_maps(production_model):
    rows = {row.action_id: row for row in production_model.decision_ir}
    instances = {
        item.rule_id: item
        for item in production_model.action_instances
        if item.kind == "action_card"
    }
    for action in production_model.actions:
        assert rows[action.id].rank_terms == action.rank_terms
        assert {term.fact for term in action.rank_terms} <= set(
            instances[action.id].condition_facts
        )
    exported = production_model.contract()["decision_ir"]["items"]
    assert any(row.get("rank_terms") for row in exported)


@pytest.mark.parametrize("order", [None, 1, ["need_tier"] * 6, ["unknown"]])
def test_invalid_rank_order_is_rejected_explicitly(production_model, order):
    # The legacy schema is checked at the source boundary. An already-built
    # model's retired rank metadata is never a second production utility source.
    support = {
        **production_model.support_sources,
        "arbitration.toml": {**production_model.support_sources["arbitration.toml"], "rank": order},
    }
    with pytest.raises(ValueError, match="rank"):
        compiler._validate_supporting_sources(
            support, production_model.consumers, production_model.relations
        )


def test_rank_partition_overflow_rejects_without_pruning_candidates(production_model):
    from pdx.situated.schema import RankTerm

    names = tuple(
        f.id
        for f in production_model.facts
        if f.kind == "boolean" and f.scope == "root" and f.unit == "flag"
    )[:10]
    assert len(names) == 10
    # Ten independent demand inputs used to imply 1024 truth-table partitions.
    # All now survive as ten linear contributions; no pruning or overflow escape.
    source = next(
        row for row in production_model.decision_ir if row.action_id == "industrial_foundation"
    )

    def expanded(count):
        rows = tuple(
            replace(
                row,
                rank_terms=tuple(
                    RankTerm(name, "structure", 1, "flag", 0.001) for name in names[:count]
                ),
            )
            if row == source
            else row
            for row in production_model.decision_ir
        )
        model = _rows(production_model, rows)
        text = compiler.strategy_overlay(model)["economic_vs_government_spending_balance"]
        return model, text

    _, small = expanded(2)
    model, large = expanded(10)
    assert len(large) < 5 * len(small)
    assert large.count("limit =") - small.count("limit =") == 8
    assert (
        len(next(row for row in model.decision_ir if row.action_id == source.action_id).rank_terms)
        == 10
    )


def test_arbitration_order_is_consumed_by_actual_pdx_rank(production_model):
    """Retired rank order cannot resurrect the old single-card winner path."""
    values, facts = _economy_values()
    values.update(coord_evidence_need_industry=False, coord_need_education=True)
    facts.update(sitai_context_need_education=True, sitai_context_evidence_need_industry=False)
    support = {
        **production_model.support_sources,
        "arbitration.toml": {
            **production_model.support_sources["arbitration.toml"],
            "rank": [
                "net_benefit",
                "need_tier",
                "goal_priority",
                "stress",
                "opportunity",
                "action_id",
            ],
        },
    }
    field = "economic_vs_government_spending_balance"
    changed = replace(production_model, support_sources=support)
    assert (
        compiler.strategy_overlay(changed)[field]
        == compiler.strategy_overlay(production_model)[field]
    )
    for model in (production_model, changed):
        assert compiler.evaluate_actions(model, values, is_ai=True)[field][1] == pytest.approx(
            0.020
        )
        assert pdx_eval.select(
            compiler.strategy_overlay(model)[field], facts
        ).delta == pytest.approx(0.020)


@pytest.mark.parametrize(
    "change",
    [
        {"tier": True},
        {"tier": 0},
        {"tier": 3},
        {"tier": 1.0},
        {"unit": "currency"},
        {"fact": ""},
        {"goal": ""},
    ],
)
def test_rank_term_rejects_nonordinal_or_untyped_inputs(change):
    from pdx.situated.schema import RankTerm

    values = {"fact": "demand", "goal": "capacity", "tier": 1, "unit": "flag", **change}
    with pytest.raises(ValueError, match="RankTerm"):
        RankTerm(**values)


def test_generated_rank_paths_stay_within_128_predicate_budget(production_model):
    from pdx.model import Assignment, Block
    from pdx.parser import parse_text

    def atoms(block):
        return sum(
            atoms(item.value) if isinstance(item.value, Block) else 1
            for item in block.assignments()
        )

    def worst(block):
        total = 0
        chain: list[Assignment] = []

        def chain_cost():
            suffix = 0
            for item in reversed(chain):
                assert isinstance(item.value, Block)
                limit = item.value.first("limit")
                assert limit is None or isinstance(limit.value, Block)
                condition_cost = atoms(limit.value) if limit is not None else 0
                body = Block(
                    [part for part in item.value.items if getattr(part, "key", "") != "limit"]
                )
                suffix = condition_cost + max(worst(body), suffix)
            return suffix

        for item in block.assignments():
            if item.key in {"if", "else_if", "else"}:
                if item.key == "if":
                    total += chain_cost()
                    chain = []
                chain.append(item)
            else:
                total += chain_cost()
                chain = []
                if isinstance(item.value, Block):
                    total += worst(item.value)
        return total + chain_cost()

    for field, text in compiler.strategy_overlay(production_model).items():
        count = worst(parse_text(text).root)
        assert count <= 128, (field, count)


@pytest.mark.parametrize(
    ("name", "raw_key", "raw", "expected"),
    [
        ("stable_legitimacy", "legitimacy", -0.01, False),
        ("stable_legitimacy", "legitimacy", 0, False),
        ("stable_legitimacy", "legitimacy", 50, True),
        ("stable_legitimacy", "legitimacy", 100, True),
        ("stable_legitimacy", "legitimacy", 100.01, False),
        ("strong_legitimacy", "legitimacy", -0.01, False),
        ("strong_legitimacy", "legitimacy", 74.99, False),
        ("strong_legitimacy", "legitimacy", 75, True),
        ("strong_legitimacy", "legitimacy", 100, True),
        ("strong_legitimacy", "legitimacy", 100.01, False),
        ("literacy_low", "literacy_rate", -0.01, False),
        ("literacy_low", "literacy_rate", 0, True),
        ("literacy_low", "literacy_rate", 0.499, True),
        ("literacy_low", "literacy_rate", 0.5, False),
        ("literacy_low", "literacy_rate", 1.01, False),
        ("literacy_ready", "literacy_rate", -0.01, False),
        ("literacy_ready", "literacy_rate", 0.499, False),
        ("literacy_ready", "literacy_rate", 0.5, True),
        ("literacy_ready", "literacy_rate", 1, True),
        ("literacy_ready", "literacy_rate", 1.01, False),
        ("stable_legitimacy", "legitimacy", None, None),
        ("strong_legitimacy", "legitimacy", None, None),
        ("literacy_low", "literacy_rate", None, None),
        ("literacy_ready", "literacy_rate", None, None),
    ],
)
def test_derived_flags_observe_raw_reader_bounds(production_model, name, raw_key, raw, expected):
    from pdx.parser import parse_text

    fact = next(fact for fact in production_model.facts if fact.id == name)
    trigger = parse_text(fact.trigger).root
    assert pdx_eval.condition(trigger, {raw_key: raw}) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (-0.01, 0.15),
        (1.01, 0.15),
        (None, 0.15),
        (0, 0.045),
        (0.499, 0.045),
        (0.5, 0.175),
        (1, 0.175),
    ],
)
def test_invalid_literacy_neither_opens_education_nor_rewards_ready_complement(
    production_model, raw, expected
):
    values, facts = _economy_values()
    valid = raw is not None and 0 <= raw <= 1
    values.update(
        literacy_low=raw < 0.5 if valid else None if raw is None else False,
        literacy_ready=raw >= 0.5 if valid else None if raw is None else False,
    )
    facts["literacy_rate"] = raw
    field = "economic_vs_government_spending_balance"
    assert compiler.evaluate_actions(production_model, values, is_ai=True)[field][
        1
    ] == pytest.approx(expected)
    generated = pdx_eval.select(compiler.strategy_overlay(production_model)[field], facts)
    assert generated.delta == pytest.approx(expected)
