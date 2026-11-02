"""Consumer programs: manual net expectations and the real patch AST."""

import hashlib
from dataclasses import replace

import pytest

from pdx import decision_adapters, decision_rules
from pdx.parser import parse_text
from pdx.situated import pdx_eval, programs

pytestmark = pytest.mark.unit


def _policy(*, operation="multiply", field="wanted_construction_output"):
    baseline = (
        "ai_strategy_default = {\n"
        f"  {field} = {{ value = 100\n"
        "    # ORIGINAL NUMERIC TAIL\n"
        "  }\n}\n"
        "# Locked reader evidence: in_default is_at_war taking_loans ROOT\n"
    )
    readers = tuple(
        decision_rules.Reader(key, engine, "root", "boolean", "boolean")
        for key, engine in (
            ("need_high", "is_at_war"),
            ("need_low", "taking_loans"),
            ("cost", "in_default"),
        )
    )
    values = (1.2, 1.1, 0.75) if operation == "multiply" else (6.0, 4.0, -3.0)
    rules = tuple(
        decision_rules.Rule(
            name,
            "economy",
            (field,),
            priority,
            value,
            (decision_rules.Predicate(fact, "=", True),),
            "manual scenario",
            "missing or changed need",
            operation=operation,
        )
        for name, fact, priority, value in (
            ("high_demand", "need_high", 10, values[0]),
            ("low_demand", "need_low", 100, values[1]),
            ("commitment_cost", "cost", 1000, values[2]),
        )
    )
    policy = decision_rules.RuleSet(
        readers,
        rules,
        hashlib.sha256(baseline.encode()).hexdigest(),
        "0" * 64,
        frozenset({"economy"}),
    )
    return programs.enable(policy, source="fixture/vanilla.txt"), baseline


def _script(policy, baseline):
    patched = decision_rules.patch(
        baseline,
        policy,
        baseline=baseline,
        reader_evidence="in_default = no is_at_war = no taking_loans = no",
    )
    start = patched.index("# ACTION program_")
    end = patched.index("# SITAI END information:", start)
    fragment = patched[start:end]
    assert not parse_text(fragment).errors
    return patched, fragment


def _check(policy, baseline, values, expected, *, is_ai=True):
    reference = decision_rules.evaluate_ir(policy, values, is_ai=is_ai)
    field = ".".join(policy.rules[0].field)
    neutral = 1.0 if policy.rules[0].operation == "multiply" else 0.0
    assert reference.get(field, ("", neutral))[1] == pytest.approx(expected)
    patched, fragment = _script(policy, baseline)
    facts = {
        "is_ai": is_ai,
        **{reader.engine: values.get(reader.key) for reader in policy.readers},
    }
    generated = pdx_eval.select(fragment, facts)
    assert (generated.delta if generated.operation else neutral) == pytest.approx(expected)
    return patched


def test_decimal_precision_survives_actual_numeric_lowering():
    policy, baseline = _policy()
    rules = tuple(
        replace(rule, value=1.123456789) if rule.id == "high_demand" else rule
        for rule in policy.rules
    )
    policy = programs.enable(
        replace(policy, rules=rules, semantic_ir=()), source="fixture/vanilla.txt"
    )
    values = {"need_high": True, "need_low": False, "cost": False}
    reference = decision_rules.evaluate_ir(policy, values, is_ai=True)
    _patched, fragment = _script(policy, baseline)
    generated = pdx_eval.select(
        fragment,
        {"is_ai": True, "is_at_war": True, "taking_loans": False, "in_default": False},
    )
    assert reference["wanted_construction_output"][1] == pytest.approx(
        1.123456789, abs=1e-14, rel=0
    )
    assert generated.delta == pytest.approx(1.123456789, abs=1e-14, rel=0)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_numeric_literal_rejects_nonfinite_values(value):
    with pytest.raises(ValueError, match="有限"):
        programs.numeric_literal(value)


@pytest.mark.parametrize(
    ("high", "low", "cost", "expected"),
    [
        (True, True, True, 0.95),
        (True, True, False, 1.2),
        (False, True, True, 0.85),
        (None, True, True, 0.85),
        (True, True, None, 1.2),
        (False, False, True, 0.75),
        (False, False, False, 1.0),
    ],
)
def test_opposite_direction_is_joint_and_same_direction_uses_strongest_known_tier(
    high, low, cost, expected
):
    policy, baseline = _policy()
    _check(policy, baseline, {"need_high": high, "need_low": low, "cost": cost}, expected)


def test_additive_score_and_cost_share_one_bounded_program():
    policy, baseline = _policy(operation="add", field="change_law_chance")
    patched = _check(policy, baseline, {"need_high": True, "need_low": True, "cost": True}, 3.0)
    fragment = patched[
        patched.index("# ACTION program_") : patched.index("# SITAI END information:")
    ]
    assert fragment.count("min =") == 1
    assert fragment.count("max =") == 1
    assert "min = -3" in fragment
    assert "max = 6" in fragment


def test_source_order_and_priority_do_not_hide_opposite_direction():
    policy, baseline = _policy()
    policy = programs.enable(
        replace(policy, rules=tuple(reversed(policy.rules))), source="fixture/vanilla.txt"
    )
    _check(policy, baseline, {"need_high": True, "need_low": True, "cost": True}, 0.95)


def test_explicit_independent_causes_add_while_correlated_tiers_do_not():
    policy, baseline = _policy()
    rules = tuple(
        replace(rule, contribution_group="population" if rule.id == "low_demand" else "industry")
        for rule in policy.rules
    )
    migrated = programs.enable(
        replace(policy, rules=rules, semantic_ir=(), consumer_programs=()),
        source="fixture/vanilla.txt",
    )
    _check(migrated, baseline, {"need_high": True, "need_low": True, "cost": False}, 1.3)
    _check(migrated, baseline, {"need_high": True, "need_low": True, "cost": True}, 1.05)
    _check(migrated, baseline, {"need_high": None, "need_low": True, "cost": True}, 0.85)


def test_causal_groups_preserve_roundtrip_and_reject_semantic_drift():
    policy, baseline = _policy()
    rules = tuple(replace(rule, contribution_group="production") for rule in policy.rules)
    policy = programs.enable(
        replace(policy, rules=rules, semantic_ir=(), consumer_programs=()),
        source="fixture/vanilla.txt",
    )
    assert all(item.to_rule().contribution_group == "production" for item in policy.semantic_ir)
    _check(policy, baseline, {"need_high": True, "need_low": True, "cost": True}, 0.95)
    with pytest.raises(ValueError, match="不一致"):
        programs.validate(
            replace(policy, rules=(replace(rules[0], contribution_group="other"), *rules[1:]))
        )


def test_player_and_disabled_domain_remain_original():
    policy, baseline = _policy()
    _check(policy, baseline, {"need_high": True, "need_low": True, "cost": True}, 1.0, is_ai=False)
    assert decision_rules.evaluate_ir(policy, {}, is_ai=True, enabled_domains=frozenset()) == {}
    assert (
        decision_rules.patch(baseline, policy, baseline=baseline, enabled_domains=frozenset())
        == baseline
    )


def test_rule_producer_markers_survive_and_original_tail_is_retained():
    policy, baseline = _policy()
    patched, fragment = _script(policy, baseline)
    for rule in policy.rules:
        assert f"# {rule.id} [{rule.domain}];" in fragment
    assert patched.index("# ORIGINAL NUMERIC TAIL") < patched.index("# ACTION program_")
    assert "# ORIGINAL NUMERIC TAIL" in patched
    assert "value = 100" in patched


def test_mixed_operation_requires_an_explicit_conversion_contract():
    policy, _baseline = _policy()
    changed = replace(policy.rules[0], operation="add")
    original = replace(
        policy, rules=(changed, *policy.rules[1:]), semantic_ir=(), consumer_programs=()
    )
    with pytest.raises(ValueError, match="混合操作"):
        programs.enable(original, source="fixture/vanilla.txt")


@pytest.mark.parametrize(
    ("operation", "value"), [("add", 5.0), ("multiply", 0.0), ("multiply", -1.0)]
)
def test_construction_goal_cannot_become_additive_or_nonpositive(operation, value):
    policy, _baseline = _policy()
    rule = replace(policy.rules[0], operation=operation, value=value)
    original = replace(policy, rules=(rule,), semantic_ir=(), consumer_programs=())
    with pytest.raises(ValueError, match=r"建设目标|倍率"):
        programs.enable(original, source="fixture/vanilla.txt")


def test_stale_program_or_envelope_fails_instead_of_falling_back():
    policy, _baseline = _policy()
    mutated = replace(policy.consumer_programs[0], upper=99.0)
    with pytest.raises(ValueError, match="包络"):
        decision_rules.evaluate_ir(replace(policy, consumer_programs=(mutated,)), {}, is_ai=True)
    with pytest.raises(ValueError, match="不一致"):
        decision_rules.evaluate_ir(
            replace(policy, semantic_ir=policy.semantic_ir[:-1]), {}, is_ai=True
        )


def test_all_current_rules_have_real_complete_consumer_programs():
    policies = (
        ("mod/decisions/information.toml", decision_rules.load()),
        *decision_adapters.load().policies,
    )
    variants = program_count = 0
    for source, policy in policies:
        migrated = programs.enable(policy, source=source)
        programs.validate(migrated)
        assert len(migrated.consumer_programs) == len(policy.groups())
        assert {
            item.action_id for program in migrated.consumer_programs for item in program.variants
        } == {rule.id for rule in policy.rules}
        variants += len(policy.rules)
        program_count += len(migrated.consumer_programs)
    assert variants == 1455
    assert program_count == 379


def test_native_construction_terminal_zero_is_not_revived():
    policy, baseline = _policy()
    baseline = baseline.replace("# ORIGINAL NUMERIC TAIL", "multiply = 0 # ORIGINAL NUMERIC TAIL")
    policy = replace(policy, baseline_sha256=hashlib.sha256(baseline.encode()).hexdigest())
    patched, _fragment = _script(policy, baseline)
    start = patched.index("wanted_construction_output = {") + len("wanted_construction_output = {")
    depth = 1
    end = start
    while depth:
        if patched[end] == "{":
            depth += 1
        elif patched[end] == "}":
            depth -= 1
        end += 1
    body = patched[start : end - 1]
    complete_numeric_ast = (
        "# ACTION final_value [test];\nif = { limit = { always = yes } add = {" + body + "} }"
    )
    result = pdx_eval.select(
        complete_numeric_ast,
        {"is_ai": True, "is_at_war": True, "taking_loans": True, "in_default": False},
    )
    assert result.delta == 0.0
