"""Selected variant sub-contributions join direct, rank and relationship causes."""

from dataclasses import replace

import pytest

from pdx.situated import actions, compiler, decision_ir, pdx_eval, programs
from pdx.situated.schema import ConsumerContract, CostPredicate, EvidenceSpec, RankTerm, Relation

pytestmark = pytest.mark.unit


def test_toml_causal_sources_reach_canonical_compiled_base_and_rank(tmp_path):
    source = tmp_path / "actions.toml"
    source.write_text(
        """schema = 1
[consumers.c]
field = "field_c"
domain = "test"
max_delta = 2
budget = 2
vanilla_tail = "retain"
[actions.direct]
domain = "test"
consumer = "c"
improves = []
consumes = []
requires_all = ["literacy_low"]
requires_any = []
blocked_by = []
complements = []
substitutes = []
conflicts = []
enables = []
exit_when = []
base = 0.5
stress = 0
opportunity = 0
commitment = 0
political_cost = 0
max_delta = 2
unknown_policy = "vanilla"
explanation = "observed literacy need"
cause_group = "knowledge"
cause_origins = ["literacy_low"]
rank_terms = [{fact = "literacy_low", goal = "school_need", tier = 1, unit = "flag", amount = 0.3, evidence_group = "knowledge", origins = ["literacy_low"]}]
""",
        encoding="utf-8",
        newline="\n",
    )
    consumers, cards = actions.load(source)
    assert cards[0].cause_origins == cards[0].rank_terms[0].origins == ("literacy_low",)
    production = compiler.load_model()
    assert production.port_graph is not None
    canonical = tuple(origin.identity for origin in production.port_graph.origins("literacy_low"))
    bound = compiler._bind_action_origins(cards, production.port_graph, production.facts)
    row = decision_ir.compile_decisions(bound, consumers, ())[0]
    assert row.cause_origins == row.rank_terms[0].origins == canonical
    # Base .5 and rank .3 describe one declared cause, hence only .5 joins.
    _check((row,), {"literacy_low": True}, 0.5)


def _row(name, base, **changes):
    return decision_ir.ConsumerDecisionIR(
        name,
        "test",
        "c",
        "field_c",
        "add",
        (),
        (),
        (),
        (),
        10,
        10,
        "retain",
        "vanilla",
        (),
        base=base,
        requires_all=(name,),
        **changes,
    )


def _check(rows, values, expected, *, bound=10):
    consumer = ConsumerContract("c", "field_c", "test", bound, 32, "retain")
    names = {name for row in rows for name in row.requires_all}
    names.update(term.fact for row in rows for term in row.rank_terms)
    names.update(fact for row in rows for rel in row.relations for fact in rel.condition_facts)
    names.update(
        predicate.fact for row in rows for predicate in (*row.commitment_when, *row.political_when)
    )
    facts = tuple(
        EvidenceSpec(
            name,
            "test",
            "fixture",
            "root",
            "boolean",
            "flag",
            "consumer",
            "vanilla",
            f"{name} = yes",
        )
        for name in sorted(names)
    )
    links = {row.action_id: row.relations for row in rows}
    program = programs.card_program(consumer, rows, links)
    actual = programs.evaluate_scalar(
        program.scalar,
        compiler._card_condition_values(program.conditions, values, {f.id: f for f in facts}),
    )
    assert actual == pytest.approx(expected)
    text = programs.render_scalar(
        program.scalar,
        compiler._card_condition_texts(program.conditions, {f.id: f for f in facts}),
        ai_guard="is_ai = yes",
        style="cards",
    )
    assert pdx_eval.select(text, {**values, "is_ai": True}).delta == pytest.approx(expected)
    return text


@pytest.mark.parametrize(
    ("high", "demand", "expected"), [(True, True, 1.5), (True, False, 1.2), (None, True, 0.6)]
)
def test_selected_variant_components_share_external_relation_cause(high, demand, expected):
    relation = Relation(
        "external",
        "high",
        "complements",
        0.2,
        condition_facts=("demand",),
        cause_id="knowledge",
        origins=("reader:literacy",),
    )
    rows = (
        _row(
            "high",
            1,
            variant_group="choice",
            variant_priority=2,
            rank_terms=(
                RankTerm("demand", "goal", 1, "flag", 0.3, "knowledge", ("reader:literacy",)),
            ),
        ),
        _row(
            "low",
            0.2,
            variant_group="choice",
            variant_priority=1,
            rank_terms=(
                RankTerm("demand", "goal", 1, "flag", 0.1, "knowledge", ("reader:literacy",)),
            ),
        ),
        _row("external", 0.2, relations=(relation,)),
    )
    _check(rows, {"high": high, "low": True, "external": True, "demand": demand}, expected)


@pytest.mark.parametrize("direction", [1, -1])
def test_direct_rank_relation_same_declared_cause_take_strongest_and_independent_causes_join(
    direction,
):
    relation = Relation(
        "rel",
        "direct",
        "complements",
        0.4,
        condition_facts=("demand",),
        cause_id="knowledge",
        origins=("reader:literacy",),
    )
    rows = (
        _row(
            "direct", direction * 0.5, cause_group="knowledge", cause_origins=("reader:literacy",)
        ),
        _row(
            "rank",
            direction * 0.1,
            rank_terms=(
                RankTerm("demand", "goal", 1, "flag", 0.3, "knowledge", ("reader:literacy",)),
            ),
        ),
        _row("rel", direction * 0.1, relations=(relation,)),
        _row(
            "other", direction * 0.2, cause_group="independent", cause_origins=("reader:literacy",)
        ),
    )
    values = {"direct": True, "rank": True, "rel": True, "other": True, "demand": True}
    _check(rows, values, direction * 0.9)
    changed = (replace(rows[0], cause_origins=("reader:other",)), *rows[1:])
    with pytest.raises(ValueError, match="因果身份"):
        _check(changed, {}, 0)
    opposite = (replace(rows[0], base=-rows[0].base), *rows[1:])
    with pytest.raises(ValueError, match="因果身份"):
        _check(opposite, values, 0)


def test_cross_category_cause_requires_nonempty_origins_even_with_equal_explicit_identity():
    rows = (
        _row("direct", 0.5, cause_group="knowledge"),
        _row(
            "rank",
            0.1,
            rank_terms=(RankTerm("demand", "goal", 1, "flag", 0.3, "knowledge"),),
        ),
    )
    with pytest.raises(ValueError, match="规范原始来源"):
        _check(rows, {"direct": True, "rank": True, "demand": True}, 0)


def test_zero_base_does_not_invent_opposite_direction_inside_negative_cause():
    rows = (
        _row("zero", 0, cause_group="same", cause_origins=("reader:need",)),
        _row("negative", -0.5, cause_group="same", cause_origins=("reader:need",)),
    )
    _check(rows, {"zero": True, "negative": True}, -0.5)


def test_higher_selected_variant_suppresses_lower_component_even_when_high_demand_false():
    rows = (
        _row(
            "high",
            1,
            variant_group="choice",
            variant_priority=2,
            rank_terms=(RankTerm("high_need", "goal", 1, "flag", 0.1, "same", ("reader:need",)),),
        ),
        _row(
            "low",
            0.2,
            variant_group="choice",
            variant_priority=1,
            rank_terms=(RankTerm("low_need", "goal", 1, "flag", 0.9, "same", ("reader:need",)),),
        ),
    )
    _check(rows, {"high": True, "low": True, "high_need": False, "low_need": True}, 1)


def test_variant_shared_path_budget_and_generated_cost_are_explicitly_bounded():
    def rows(size):
        return tuple(
            _row(
                f"a{i}",
                0.1,
                variant_group="choice",
                variant_priority=i,
                cause_group="same",
                cause_origins=("reader:need",),
            )
            for i in range(size)
        )

    small = _check(rows(8), {f"a{i}": True for i in range(8)}, 0.1)
    large = _check(rows(32), {f"a{i}": True for i in range(32)}, 0.1)
    # Guard prefixes are quadratic, bounded by the explicit 32-candidate cap.
    assert len(large) < len(small) * 17
    with pytest.raises(ValueError, match="32候选预算"):
        _check(rows(33), {}, 0)


def test_selected_variant_and_external_owner_share_cost_once_but_independent_costs_join():
    pressure = (CostPredicate("pressure", "=", True, "flag"),)
    rows = (
        _row(
            "high",
            1.0,
            variant_group="choice",
            variant_priority=2,
            commitment=0.4,
            commitment_when=pressure,
            commitment_cost_id="shared",
        ),
        _row(
            "low",
            0.2,
            variant_group="choice",
            variant_priority=1,
            commitment=0.4,
            commitment_when=pressure,
            commitment_cost_id="shared",
        ),
        _row(
            "external",
            1.0,
            commitment=0.4,
            commitment_when=pressure,
            commitment_cost_id="shared",
            political_cost=0.1,
            political_when=pressure,
        ),
    )
    values = {"high": True, "low": True, "external": True, "pressure": None}
    # Selected high 1 + external 1 - shared .4 - independent political .1.
    _check(rows, values, 1.5)
    _check(rows, {**values, "high": None}, 0.7)
