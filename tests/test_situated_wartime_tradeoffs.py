"""S3 local army/navy targets: observed war need, capacity tiers and default cost."""

from dataclasses import replace

import pytest
from _frozen_reader_words import frozen_reader_words

from pdx import country_state, decision_rules
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval

pytestmark = pytest.mark.unit
INFO = "mod/decisions/information.toml"
FIELDS = ("wanted_army_size", "wanted_navy_size")


def _values(**changes):
    return {
        "war": True,
        "default": False,
        "net_surplus": 1,
        "bureaucracy": 1,
        "army": 100,
        "infamy": 0,
        "gdp": 1,
        "navy": 20,
        "gold_reserves": 0,
        "defensive_pact_articles": 0,
        "native_army_capacity": 101,
        "native_marine_capacity": 1,
        "coord_evidence_need_overseas": False,
        "coord_layer_stable": False,
        **changes,
    }


@pytest.fixture(scope="module")
def production():
    original = decision_rules.load()
    rules = tuple(rule for rule in original.rules if ".".join(rule.field) in FIELDS)
    keys = {key for rule in rules for key in rule.input_keys()}
    selected = replace(
        original,
        rules=rules,
        readers=tuple(reader for reader in original.readers if reader.key in keys),
        enabled_domains=frozenset(rule.domain for rule in rules),
        semantic_ir=(),
        consumer_programs=(),
    )
    model = compiler.load_model()
    compiled = compiler.compile_policy(selected, INFO, model)[0]
    native = compiler.BASELINE.read_text(encoding="utf-8")
    generated = decision_rules.patch(
        native,
        compiled,
        baseline=native,
        reader_words=frozen_reader_words(native),
        country_policy=country_state.load(),
        consumer_ir=model.consumer_ir,
        consumer_source=INFO,
    )
    return compiled, native, generated


def _facts(policy, values, *, is_ai=True):
    root = {"is_ai": is_ai}
    for reader in policy.readers:
        if reader.key not in values:
            continue
        assert reader.scope == "root"
        assert not reader.path
        observed = values[reader.key]
        if reader.engine == "has_variable":
            root[f"{reader.argument}_active"] = observed
        else:
            assert not reader.argument
            assert not reader.parameters
            assert not reader.value_field
            root[reader.engine] = observed
        if reader.engine.startswith("sitai_context_"):
            root[reader.engine.replace("sitai_context_", "sitai_context_known_", 1)] = (
                type(observed) is bool
            )
    return {"ROOT": root}


def _pdx_factors(policy, generated, values, *, is_ai=True):
    factors = []
    for program in policy.consumer_programs:
        actual = pdx_eval.select(
            pdx_eval.marked_block(generated, program.action_id),
            _facts(policy, values, is_ai=is_ai),
        )
        assert actual.operation in {None, "multiply"}
        factors.append(actual.delta if actual.operation == "multiply" else 1)
    return tuple(factors)


# These are alternatives within one observed military-demand envelope, not
# independent rewards to stack: army .08 base, .12 fiscal, .11 administrative,
# and .20 complete capacity; navy .06/.09/.09/.12. A lone capacity observation
# proves only its intermediate tier; the complete tier also proves no default.
CASES = [
    ("full_capacity", {}, (1.20, 1.12)),
    ("zero_flow", {"net_surplus": 0}, (1.11, 1.09)),
    ("negative_flow", {"net_surplus": -1}, (1.11, 1.09)),
    ("zero_administration", {"bureaucracy": 0}, (1.12, 1.09)),
    ("negative_administration", {"bureaucracy": -1}, (1.12, 1.09)),
    ("neither_capacity", {"net_surplus": -1, "bureaucracy": -1}, (1.08, 1.06)),
    # Known administration need +.11/+.09 and default cost -.15/-.20 jointly
    # yield .96/.89; default never removes the independently observed war need.
    ("default_with_administration", {"default": True}, (0.96, 0.89)),
    (
        "default_without_capacity",
        {"default": True, "net_surplus": -1, "bureaucracy": -1},
        (0.93, 0.86),
    ),
    ("unknown_flow", {"net_surplus": None}, (1.11, 1.09)),
    ("unknown_administration", {"bureaucracy": None}, (1.12, 1.09)),
    ("unknown_default", {"default": None}, (1.11, 1.09)),
    (
        "all_capacity_unknown",
        {"default": None, "net_surplus": None, "bureaucracy": None},
        (1.08, 1.06),
    ),
    ("unknown_war", {"war": None}, (1, 1)),
    ("unknown_war_known_default", {"war": None, "default": True}, (0.85, 0.8)),
    ("peace", {"war": False}, (1, 1)),
    ("peace_known_default", {"war": False, "default": True}, (0.85, 0.8)),
    # Actual threat/overseas tiers are correlated demand alternatives.
    ("threat_does_not_stack", {"army": 49, "infamy": 26}, (1.20, 1.12)),
    (
        "overseas_does_not_stack",
        {"coord_evidence_need_overseas": True, "coord_layer_stable": True},
        (1.20, 1.18),
    ),
]


@pytest.mark.parametrize(("case", "changes", "expected"), CASES, ids=[row[0] for row in CASES])
def test_war_capacity_and_cost_have_handwritten_joint_reference(
    production, case, changes, expected
):
    policy, _, generated = production
    values = _values(**changes)
    selected = decision_rules.evaluate(policy, values, is_ai=True)
    factors = tuple(selected[field][1] if field in selected else 1 for field in FIELDS)
    assert factors == pytest.approx(expected), case
    assert _pdx_factors(policy, generated, values) == pytest.approx(expected), case


@pytest.mark.parametrize("unknown", [None, float("nan"), float("inf"), "invalid"])
@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("net_surplus", (1.11, 1.09)),
        ("bureaucracy", (1.12, 1.09)),
        ("default", (1.11, 1.09)),
        ("war", (1, 1)),
    ],
)
def test_unknown_observation_only_removes_its_own_proven_tiers(production, key, unknown, expected):
    policy, _, generated = production
    values = _values(**{key: unknown})
    selected = decision_rules.evaluate(policy, values, is_ai=True)
    assert tuple(
        selected[field][1] if field in selected else 1 for field in FIELDS
    ) == pytest.approx(expected)
    assert _pdx_factors(policy, generated, values) == pytest.approx(expected)


def _entry(text, field):
    strategy = parse_text(text).root.first("ai_strategy_default")
    assert strategy is not None
    assert isinstance(strategy.value, Block)
    entry = strategy.value.first(field)
    assert entry is not None
    assert isinstance(entry.value, Block)
    return entry


def _tree(node):
    if isinstance(node, Scalar):
        return node.text
    if isinstance(node, Assignment):
        return node.key, node.op, _tree(node.value)
    assert isinstance(node, Block)
    return tuple(_tree(item) for item in node.items)


def _bind_native_values(node, observations):
    """Only replace the vanilla getter leaves; interpret the actual numeric AST."""
    if isinstance(node, Scalar):
        return (
            replace(node, text=str(observations[node.text])) if node.text in observations else node
        )
    if isinstance(node, Assignment):
        return replace(node, value=_bind_native_values(node.value, observations))
    assert isinstance(node, Block)
    return replace(node, items=[_bind_native_values(item, observations) for item in node.items])


@pytest.mark.parametrize(
    ("changes", "army", "marines", "navy", "expected"),
    [
        # Complete observed war capacity: (100 - 20) * 1.20, 10 * 1.12.
        ({}, 100, 20, 10, (96, 11.2)),
        # 80 * (1 + .11 - .15), 10 * (1 + .09 - .20).
        ({"default": True}, 100, 20, 10, (76.8, 8.9)),
        ({"war": False}, 100, 20, 10, (80, 10)),
        # Multiplying before the native marine subtraction would invent a
        # positive non-marine army target from these equal native getters.
        ({}, 1, 1, 0, (0, 0)),
        ({"default": True}, 0, 0, 0, (0, 0)),
    ],
)
def test_complete_native_numeric_consumers_preserve_subtraction_and_zero(
    production, changes, army, marines, navy, expected
):
    policy, _, generated = production
    facts = _facts(policy, _values(**changes))
    observations = {
        "wanted_army_size_script_value": army,
        "wanted_marines_size_script_value": marines,
        "wanted_navy_size_script_value": navy,
    }
    actual = tuple(
        pdx_eval._numeric_value(_bind_native_values(_entry(generated, field), observations), facts)
        for field in FIELDS
    )
    assert actual == pytest.approx(expected)


def test_both_numeric_consumers_keep_native_getters_and_one_bounded_write(production):
    policy, native, generated = production
    for field in FIELDS:
        before, after = _entry(native, field), _entry(generated, field)
        assert _tree(before.value) == tuple(
            _tree(item) for item in after.value.items[: len(before.value.items)]
        )
        assert len(after.value.items) == len(before.value.items) + 1
    army = _entry(native, FIELDS[0]).value
    navy = _entry(native, FIELDS[1]).value
    assert [(item.key, item.value.text) for item in army.assignments()] == [
        ("value", "wanted_army_size_script_value"),
        ("subtract", "wanted_marines_size_script_value"),
    ]
    assert [(item.key, item.value.text) for item in navy.assignments()] == [
        ("value", "wanted_navy_size_script_value")
    ]
    assert all(
        program.operation == "multiply" and program.lower > 0
        for program in policy.consumer_programs
    )


def test_player_off_and_other_country_observations_keep_local_boundary(production):
    policy, native, generated = production
    values = _values(default=True)
    assert decision_rules.evaluate(policy, values, is_ai=False) == {}
    assert _pdx_factors(policy, generated, values, is_ai=False) == (1, 1)
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    assert (
        decision_rules.patch(native, policy, baseline=native, enabled_domains=frozenset()) == native
    )
    local = _values(war=False, default=False, net_surplus=-1, bureaucracy=-1)
    facts = _facts(policy, local)
    decoy = {
        "is_ai": True,
        "is_at_war": True,
        "in_default": True,
        "net_total_income": 10,
        "bureaucracy": 10,
    }
    facts["ROOT"]["other_country"] = decoy
    facts["ROOT"]["owner"] = decoy
    facts["scope:target_country"] = decoy
    facts.update(decoy)
    for program in policy.consumer_programs:
        actual = pdx_eval.select(pdx_eval.marked_block(generated, program.action_id), facts)
        assert actual.operation == "multiply"
        assert actual.delta == 1
