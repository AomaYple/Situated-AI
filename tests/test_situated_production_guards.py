"""生产行动的唯一 IR 来源与单互补合同。"""

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
    [(False, False, 1.5), (True, False, 1.75), (True, True, 1.5)],
)
def test_only_one_proven_complement_contributes_to_production_delta(
    production_model, stronger, unknown, expected
):
    model = production_model
    if stronger:
        model = _rows(
            model,
            tuple(
                replace(
                    row,
                    relations=tuple(
                        replace(rel, strength=0.5) if rel.target == "political_reform" else rel
                        for rel in row.relations
                    ),
                )
                if row.action_id == "industrial_foundation"
                else row
                for row in model.decision_ir
            ),
        )
    values, facts = _economy_values()
    if unknown:
        values.update(no_insurrection=None, insurrection=None, ongoing_insurrection=None)
        facts["any_insurrection_ongoing"] = None
    actions = [row for row in model.decision_ir if row.consumer_id == "economic_balance"]
    chosen = compiler._select_action(
        actions, values, all_actions=list(model.decision_ir), model=model
    )
    assert chosen is not None
    assert chosen[0].action_id == "industrial_foundation"
    assert compiler._row_delta(chosen[0], values, complement=chosen[1], model=model) == expected
    generated = pdx_eval.select(
        compiler.strategy_overlay(model)["economic_vs_government_spending_balance"], facts
    )
    assert (generated.action_id, generated.delta) == ("industrial_foundation", expected)


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
        compiler._select_action(
            [row for row in model.decision_ir if row.consumer_id == "economic_balance"],
            values,
            all_actions=list(model.decision_ir),
            model=model,
        )


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
    with pytest.raises(pdx_eval.UnsupportedPdxError, match="未登记"):
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
        (False, False, "industrial_foundation", 1.5),
        (True, False, "industrial_foundation", 1.5),
        (False, True, "education_and_research", 1.15),
        (None, None, "industrial_foundation", 1.5),
    ],
)
def test_production_need_rank_changes_actual_consumer_selection(
    production_model, industry, education, expected_action, expected_delta
):
    values, facts = _economy_values()
    values.update(coord_evidence_need_industry=industry, coord_need_education=education)
    facts.update(
        sitai_context_evidence_need_industry=industry, sitai_context_need_education=education
    )
    actions = [row for row in production_model.decision_ir if row.consumer_id == "economic_balance"]
    chosen = compiler._select_action(
        actions, values, all_actions=list(production_model.decision_ir), model=production_model
    )
    assert chosen is not None
    assert chosen[0].action_id == expected_action
    assert compiler._row_delta(
        chosen[0], values, complement=chosen[1], model=production_model
    ) == pytest.approx(expected_delta)
    actual = pdx_eval.select(
        compiler.strategy_overlay(production_model)["economic_vs_government_spending_balance"],
        facts,
    )
    assert actual.action_id == expected_action
    assert actual.delta == pytest.approx(expected_delta)


def test_production_goal_priority_can_break_tied_need_tiers(production_model):
    values, facts = _economy_values()
    values.update(coord_evidence_need_industry=True, coord_need_education=True)
    facts.update(sitai_context_evidence_need_industry=True, sitai_context_need_education=True)
    # 净收益与需求档相同后，目标优先级只打破平局。
    actions = [row for row in production_model.decision_ir if row.consumer_id == "economic_balance"]
    tied_actions = [
        replace(row, base=row.base + 0.35) if row.action_id == "education_and_research" else row
        for row in actions
    ]
    tied_model = _rows(
        production_model,
        [
            row
            if row.consumer_id != "economic_balance"
            else next(
                (candidate for candidate in tied_actions if candidate.action_id == row.action_id),
                row,
            )
            for row in production_model.decision_ir
        ],
    )
    expected = [("structure", "industrial_foundation"), ("capacity", "education_and_research")]
    for goal_id, action_id in expected:
        model = replace(
            tied_model,
            goals=tuple((key, 100 if key == goal_id else 0) for key, _ in tied_model.goals),
        )
        actual = pdx_eval.select(
            compiler.strategy_overlay(model)["economic_vs_government_spending_balance"], facts
        )
        assert actual.action_id == action_id


@pytest.mark.parametrize(
    ("debt", "expected_action", "expected_delta"),
    [
        (-0.01, None, 0.0),
        (0.0, "industrial_foundation", 1.5),
        (0.4, "industrial_foundation", 1.5),
        (0.41, "education_and_research", 0.9),
    ],
)
def test_cost_boundaries_preserve_zero_and_reject_negative_debt(
    production_model, debt, expected_action, expected_delta
):
    values, facts = _economy_values()
    values["debt_ratio"] = debt
    facts["scaled_debt"] = debt
    actions = [row for row in production_model.decision_ir if row.consumer_id == "economic_balance"]
    chosen = compiler._select_action(
        actions, values, all_actions=list(production_model.decision_ir), model=production_model
    )
    if expected_action is None:
        assert chosen is None
    else:
        assert chosen is not None
        assert chosen[0].action_id == expected_action
        assert compiler._row_delta(
            chosen[0], values, complement=chosen[1], model=production_model
        ) == pytest.approx(expected_delta)
    actual = pdx_eval.select(
        compiler.strategy_overlay(production_model)["economic_vs_government_spending_balance"],
        facts,
    )
    assert actual.action_id == expected_action
    assert actual.delta == pytest.approx(expected_delta)


@pytest.mark.parametrize(
    ("name", "value"), [("legitimacy", -0.01), ("legitimacy", 100.01), ("debt_ratio", -1)]
)
def test_out_of_range_cost_is_local_unknown_and_preserves_vanilla(production_model, name, value):
    values, facts = _economy_values()
    values[name] = value
    facts[{"debt_ratio": "scaled_debt", "legitimacy": "legitimacy"}[name]] = value
    actions = [row for row in production_model.decision_ir if row.consumer_id == "economic_balance"]
    assert (
        compiler._select_action(
            actions, values, all_actions=list(production_model.decision_ir), model=production_model
        )
        is None
    )
    actual = pdx_eval.select(
        compiler.strategy_overlay(production_model)["economic_vs_government_spending_balance"],
        facts,
    )
    assert actual.action_id is None
    assert actual.delta == 0
    # 同一个非法债务数值不关闭只读取战争事实的外交克制工具。
    unaffected = pdx_eval.select(
        compiler.strategy_overlay(production_model)["recklessness"], {**facts, "is_at_war": True}
    )
    assert unaffected.action_id == "diplomatic_restraint"


@pytest.mark.parametrize(
    ("debt", "expected"), [(0.4, "education_and_research"), (0.41, "education_and_research")]
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
    assert actual.delta == pytest.approx(1.15 if debt == 0.4 else 0.9)


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
    model = production_model
    for consumer in model.consumers:
        rows = [row for row in model.decision_ir if row.consumer_id == consumer.id]
        costs = {
            predicates
            for row in rows
            for predicates, amount in (
                (row.commitment_when, row.commitment),
                (row.political_when, row.political_cost),
            )
            if predicates and amount > 0
        }
        needs = {term.fact for row in rows for term in row.rank_terms}
        assert 2 ** (len(costs) + len(needs)) <= 16


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
    support = {**production_model.support_sources, "arbitration.toml": {"rank": order}}
    with pytest.raises(ValueError, match="rank"):
        compiler.strategy_overlay(replace(production_model, support_sources=support))


def test_rank_partition_overflow_rejects_without_pruning_candidates(production_model):
    from pdx.situated.schema import RankTerm

    names = tuple(
        f.id for f in production_model.facts if f.kind == "boolean" and f.scope == "root"
    )[:10]
    assert len(names) == 10
    rows = tuple(
        replace(row, rank_terms=tuple(RankTerm(name, "capacity", 1, "flag") for name in names))
        if row.action_id == "industrial_foundation"
        else row
        for row in production_model.decision_ir
    )
    model = _rows(production_model, rows)
    with pytest.raises(ValueError, match="512"):
        compiler.strategy_overlay(model)


def test_arbitration_order_is_consumed_by_actual_pdx_rank(production_model):
    _values, facts = _economy_values()
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
    assert (
        pdx_eval.select(compiler.strategy_overlay(production_model)[field], facts).action_id
        == "education_and_research"
    )
    changed = replace(production_model, support_sources=support)
    assert (
        pdx_eval.select(compiler.strategy_overlay(changed)[field], facts).action_id
        == "industrial_foundation"
    )


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
