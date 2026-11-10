"""Known financing pressure survives war, independently of native design tails."""

import copy
from dataclasses import replace

import pytest

from pdx import config, decision_rules, decisions
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import pdx_eval, programs

pytestmark = pytest.mark.unit
FIELD = "max_ship_design_complexity"


@pytest.fixture(scope="module")
def design():
    original = decision_rules.load()
    rules = tuple(rule for rule in original.rules if rule.field == (FIELD,))
    assert len(rules) == 1
    assert rules[0].id == "naval_design_affordability"
    keys = {key for rule in rules for key in rule.input_keys()}
    policy = programs.enable(
        replace(
            original,
            enabled_domains=frozenset({"military"}),
            rules=rules,
            readers=tuple(r for r in original.readers if r.key in keys),
            semantic_ir=(),
            consumer_programs=(),
        ),
        source="mod/decisions/information.toml",
    )
    baseline = decisions.baseline_path().read_text(encoding="utf-8")
    text = decision_rules.patch(
        baseline, policy, baseline=baseline, reader_words=frozenset({"is_at_war", "in_default"})
    )
    overlay = pdx_eval.marked_block(text, policy.consumer_programs[0].action_id)
    return policy, text, overlay


@pytest.mark.parametrize("war", [False, True, None])
@pytest.mark.parametrize(("default", "expected"), [(True, 0.85), (False, 1), (None, 1)])
def test_default_is_one_cause_and_does_not_require_known_peace(design, war, default, expected):
    policy, _, overlay = design
    values = {"default": default, "war": war, "loans": True}
    assert decision_rules.evaluate_ir(policy, values, is_ai=True).get(FIELD, ("", 1))[
        1
    ] == pytest.approx(expected)
    facts = {"ROOT": {"is_ai": True, "in_default": default, "is_at_war": war, "taking_loans": True}}
    result = pdx_eval.select(overlay, facts)
    assert (result.delta if result.operation else 1) == pytest.approx(expected)
    assert decision_rules.evaluate_ir(policy, values, is_ai=False) == {}
    assert decision_rules.evaluate_ir(policy, values, is_ai=True, enabled_domains=frozenset()) == {}
    facts["ROOT"]["is_ai"] = False
    assert pdx_eval.select(overlay, facts).operation is None


@pytest.mark.parametrize(
    ("rank", "law", "native"),
    [(1, "merchant", 5), (4, "jeune", 9), (7, "professional", 14), (4, "none", 10)],
)
def test_native_rank_and_law_execute_before_positive_financing_multiplier(
    design, rank, law, native
):
    _, text, _ = design
    definition = parse_text(text).root.first("ai_strategy_default")
    assert definition is not None
    assert isinstance(definition.value, Block)
    weight = definition.value.first(FIELD)
    assert weight is not None
    assert isinstance(weight.value, Block)
    cloned = copy.deepcopy(weight.value)
    addition = cloned.items[1]
    assert isinstance(addition, Assignment)
    assert isinstance(addition.value, Block)
    rank_value = addition.value.first("value")
    assert rank_value is not None
    assert isinstance(rank_value.value, Scalar)
    assert rank_value.value.unquoted == "country_rank"
    rank_value.value = Scalar(str(rank))
    for branch, name in zip(cloned.items[2:5], ("merchant", "jeune", "professional"), strict=True):
        assert isinstance(branch, Assignment)
        assert isinstance(branch.value, Block)
        limit = branch.value.first("limit")
        assert limit is not None
        assert isinstance(limit.value, Block)
        assert limit.value.first("has_law_or_variant") is not None
        limit.value = parse_text("always = yes" if name == law else "always = no").root
    facts = {"ROOT": {"is_ai": True, "in_default": True, "is_at_war": True}}
    assert pdx_eval._numeric_value(Assignment("multiply", "=", cloned), facts) == pytest.approx(
        native * 0.85
    )
    # A zero native result is not awakened by the sole positive multiplier.
    overlay = cloned.items[-1]
    zero = Block([Assignment("value", "=", Scalar("0")), overlay])
    assert pdx_eval._numeric_value(Assignment("multiply", "=", zero), facts) == 0


def test_locked_native_strategy_is_not_inferred_from_development_fixture():
    import hashlib

    from pdx.textio import normalized_text

    source = config.GAME / "common/ai_strategies/00_default_strategy.txt"
    if not source.is_file():
        pytest.skip("锁定原版不可用")
    assert (
        hashlib.sha256(normalized_text(source.read_text(encoding="utf-8-sig")).encode()).hexdigest()
        == decision_rules.load().baseline_sha256
    )
