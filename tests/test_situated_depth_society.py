"""D7 社会域静态合同：覆盖、未知保留、并行和作用域边界。"""

import hashlib
from dataclasses import replace
from typing import Any

import pytest

from pdx import country_state, decision_adapters, decision_rules
from pdx.model import Block, Scalar
from pdx.parser import parse_text
from pdx.situated import pdx_eval
from pdx.situated.compiler import baseline_path, load_model
from pdx.situated.domain_coverage import CHAINS, load
from pdx.situated.families import FAMILIES

pytestmark = pytest.mark.unit

SOCIETY_DOMAINS = frozenset({"political", "population", "social", "identity"})
WELFARE_FIELD = "institution_scores.institution_social_security"
WELFARE_PROGRAM = (
    "program_"
    + hashlib.sha256(f"mod/decisions/information.toml:{WELFARE_FIELD}".encode()).hexdigest()[:16]
)
WELFARE_SIZE_WITNESSES = [
    (1, False, (WELFARE_PROGRAM, 1.08)),
    (1_999_999, False, (WELFARE_PROGRAM, 1.08)),
    (2_000_000, False, (WELFARE_PROGRAM, 1.10)),
    (2_000_001, False, (WELFARE_PROGRAM, 1.10)),
    (1, True, (WELFARE_PROGRAM, 1.08)),
    (1_999_999, True, (WELFARE_PROGRAM, 1.08)),
    (2_000_000, True, (WELFARE_PROGRAM, 1.08)),
    (2_000_001, True, (WELFARE_PROGRAM, 1.08)),
]
WELFARE_BOUNDARY_WITNESSES = [
    ({"average_sol": 7.999}, (WELFARE_PROGRAM, 1.08)),
    ({"average_sol": 8}, None),
    ({"average_sol": 8.001}, None),
    ({"average_sol": None}, None),
    ({"average_sol": -1}, None),
    ({"average_sol": float("nan")}, None),
    ({"average_sol": float("inf")}, None),
    ({"average_sol": True}, None),
    ({"population": 0}, None),
    ({"population": -1}, None),
    ({"population": None}, None),
    # Zero spare administration is a cost tier; LJ04 keeps its low-cost local
    # welfare repair available instead of imposing a global hard gate.
    ({"bureaucracy": 0}, (WELFARE_PROGRAM, 1.08)),
    ({"bureaucracy": -1}, (WELFARE_PROGRAM, 0.98)),
    ({"bureaucracy": None}, (WELFARE_PROGRAM, 1.08)),
    ({"default": True}, (WELFARE_PROGRAM, 0.88)),
    ({"default": True, "war": True}, (WELFARE_PROGRAM, 0.93)),
    ({"default": None}, (WELFARE_PROGRAM, 1.08)),
    ({"war": None}, (WELFARE_PROGRAM, 1.08)),
    ({"population": 2_000_000, "war": None}, (WELFARE_PROGRAM, 1.08)),
    ({"coord_need_political": None}, (WELFARE_PROGRAM, 1.08)),
]


@pytest.fixture(scope="module")
def welfare_policy():
    policy = decision_rules.load()
    from pdx.situated import compiler

    selected = replace(
        policy,
        rules=tuple(rule for rule in policy.rules if ".".join(rule.field) == WELFARE_FIELD),
        enabled_domains=frozenset(
            rule.domain for rule in policy.rules if ".".join(rule.field) == WELFARE_FIELD
        ),
        semantic_ir=(),
    )
    return compiler.compile_policy(
        selected, "mod/decisions/information.toml", compiler.load_model()
    )[0]


def _welfare_values(**changes):
    # Neutral grain observations isolate these welfare scenarios from LJ07.
    # Explicit None values and absent observations remain unknown.
    return {
        "default": False,
        "war": False,
        "average_sol": 7,
        "population": 1_000_000,
        "bureaucracy": 1,
        "grain_price": 0.2,
        "grain_balance": 0,
        "net_surplus": 0,
        "insurrection": False,
        "coord_need_political": False,
        "coord_layer_stable": False,
        **changes,
    }


@pytest.mark.parametrize(
    ("population", "war", "expected"),
    WELFARE_SIZE_WITNESSES,
)
def test_welfare_foundation_does_not_require_large_population_or_peace(
    welfare_policy, population, war, expected
):
    result = decision_rules.evaluate(
        welfare_policy, _welfare_values(population=population, war=war), is_ai=True
    )
    assert result[WELFARE_FIELD][0] == expected[0]
    assert result[WELFARE_FIELD][1] == pytest.approx(expected[1])


@pytest.mark.parametrize(
    ("changes", "expected"),
    WELFARE_BOUNDARY_WITNESSES,
)
def test_welfare_foundation_preserves_need_cost_and_unknown_boundaries(
    welfare_policy, changes, expected
):
    result = decision_rules.evaluate(welfare_policy, _welfare_values(**changes), is_ai=True)
    actual = result.get(WELFARE_FIELD)
    if expected is None:
        assert actual is None
    else:
        assert actual is not None
        assert actual[0] == expected[0]
        assert actual[1] == pytest.approx(expected[1])


def test_welfare_foundation_preserves_player_and_disabled_paths(welfare_policy):
    values = _welfare_values()
    assert decision_rules.evaluate(welfare_policy, values, is_ai=False) == {}
    assert (
        decision_rules.evaluate(
            welfare_policy, values, is_ai=True, enabled_domains=frozenset({"economy"})
        )
        == {}
    )


@pytest.fixture(scope="module")
def welfare_generated(welfare_policy):
    baseline = baseline_path().read_text(encoding="utf-8")
    inputs = decision_adapters.read_inputs(decision_adapters.load())
    kwargs = {
        "baseline": baseline,
        "reader_words": frozenset(decision_adapters.reader_evidence(inputs)),
        "country_policy": country_state.load(),
    }
    generated = decision_rules.patch(baseline, welfare_policy, **kwargs)
    begin = f"# SITAI BEGIN information:{WELFARE_FIELD}"
    end = f"# SITAI END information:{WELFARE_FIELD}"
    overlay = generated.split(begin, 1)[1].split(end, 1)[0]
    # The independent evaluator receives the actual branches, including neutral
    # unknown guards. Only annotate those guards; all scopes, conditions, branch
    # order and writes remain intact.
    used_keys = {key for rule in welfare_policy.rules for key in rule.input_keys()}
    expected_paths = {("ROOT",)}
    for reader in welfare_policy.readers:
        if reader.key not in used_keys:
            continue
        assert reader.scope == "root"
        for length in range(1, len(reader.path) + 1):
            expected_paths.add(("ROOT", *reader.path[:length]))
    assert _existence_paths(parse_text(overlay).root) == expected_paths
    lines: list[str] = []
    for line in overlay.splitlines():
        if line.lstrip().startswith(("if =", "else_if =")) and (
            not lines or not lines[-1].lstrip().startswith("# ")
        ):
            lines.append("# welfare_unknown_guard [political]; retain native value")
        lines.append(line)
    return baseline, generated, "\n".join(lines), kwargs


def _existence_paths(block: Block, path: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    paths: set[tuple[str, ...]] = set()
    for item in block.assignments():
        if item.key == "exists":
            assert isinstance(item.value, Scalar)
            paths.add((*path, item.value.unquoted))
        elif isinstance(item.value, Block):
            child_path = (
                path
                if item.key
                in {
                    "if",
                    "else_if",
                    "limit",
                    "AND",
                    "OR",
                    "NOT",
                    "add",
                    "multiply",
                    "min",
                    "max",
                    "divide",
                }
                else (*path, item.key)
            )
            paths.update(_existence_paths(item.value, child_path))
    return paths


def _welfare_pdx_facts(policy, values, *, is_ai=True, root_exists=True):
    country: dict[str, Any] = {"is_ai": is_ai}
    used_keys = {key for rule in policy.rules for key in rule.input_keys()}
    for reader in policy.readers:
        if reader.key not in used_keys:
            continue
        assert reader.scope == "root"
        assert reader.argument is None
        assert not reader.parameters
        current = country
        for part in reader.path:
            current = current.setdefault(part, {})
        current[reader.engine] = values.get(reader.key)
        if reader.engine.startswith("sitai_context_"):
            current[reader.engine.replace("sitai_context_", "sitai_context_known_", 1)] = (
                values.get(reader.key) is not None
            )
    return {"ROOT": country if root_exists else None}


@pytest.mark.integration
@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        *[
            ({"population": population, "war": war}, expected)
            for population, war, expected in WELFARE_SIZE_WITNESSES
        ],
        *WELFARE_BOUNDARY_WITNESSES,
    ],
)
def test_welfare_actual_pdx_preserves_need_cost_unknown_and_size_tiers(
    welfare_policy, welfare_generated, changes, expected
):
    _, _, overlay, _ = welfare_generated
    actual = pdx_eval.select(
        overlay, _welfare_pdx_facts(welfare_policy, _welfare_values(**changes))
    )
    if expected is None:
        assert actual.fallback in {"vanilla", "unknown"} or (
            actual.operation == "multiply" and actual.delta == 1.0
        )
    else:
        assert actual.action_id == expected[0]
        assert actual.delta == pytest.approx(expected[1])
        assert actual.operation == "multiply"
    # Native score is ten, so a neutral/unknown path retains ten rather than
    # granting institutions, cash, eligibility or an unconditional score.
    factor = actual.delta if actual.operation == "multiply" else 1.0
    assert 10 * factor == pytest.approx(10 * (expected[1] if expected else 1.0))


@pytest.mark.integration
def test_welfare_actual_pdx_preserves_native_tail_player_root_and_disabled_paths(
    welfare_policy, welfare_generated
):
    baseline, generated, overlay, kwargs = welfare_generated
    begin = generated.index(f"\n\t\t# SITAI BEGIN information:{WELFARE_FIELD}")
    end = generated.index(f"# SITAI END information:{WELFARE_FIELD}", begin)
    end = generated.index("\n\t", end) + len("\n\t")
    assert generated[:begin] + generated[end:] == baseline
    parsed = parse_text(generated)
    strategy = parsed.root.first("ai_strategy_default")
    assert strategy is not None
    assert isinstance(strategy.value, Block)
    institution_scores = strategy.value.first("institution_scores")
    assert institution_scores is not None
    assert isinstance(institution_scores.value, Block)
    social_entry = institution_scores.value.first("institution_social_security")
    assert social_entry is not None
    assert isinstance(social_entry.value, Block)
    social = social_entry.value
    value_entry = social.first("value")
    assert value_entry is not None
    assert isinstance(value_entry.value, Scalar)
    assert value_entry.value.unquoted == "10"
    assert set(social.keys()) <= {"value", "if", "else_if"}
    assert (
        decision_rules.patch(baseline, welfare_policy, enabled_domains=frozenset(), **kwargs)
        == baseline
    )
    for context in ({"is_ai": False}, {"root_exists": False}):
        actual = pdx_eval.select(
            overlay, _welfare_pdx_facts(welfare_policy, _welfare_values(), **context)
        )
        assert actual.fallback == "vanilla"


@pytest.mark.integration
@pytest.mark.parametrize("key", ["grain_price", "grain_balance"])
@pytest.mark.parametrize("missing", [False, True], ids=["explicit_unknown", "missing"])
def test_welfare_missing_grain_observation_keeps_native_score(
    welfare_policy, welfare_generated, key, missing
):
    _, _, overlay, _ = welfare_generated
    values = _welfare_values(grain_price=0.6, grain_balance=-1, net_surplus=1)
    expected = 1.12
    assert decision_rules.evaluate(welfare_policy, values, is_ai=True)[WELFARE_FIELD][
        1
    ] == pytest.approx(expected)
    ready = pdx_eval.select(overlay, _welfare_pdx_facts(welfare_policy, values))
    assert ready.action_id == WELFARE_PROGRAM
    assert ready.delta == pytest.approx(expected)
    if missing:
        del values[key]
    else:
        values[key] = None
    # Losing a grain observation exits that optional tier, while independently
    # observed low living standards retain the 1.08 local need.
    reference = decision_rules.evaluate(welfare_policy, values, is_ai=True)[WELFARE_FIELD]
    assert reference[1] == pytest.approx(1.08)
    actual = pdx_eval.select(overlay, _welfare_pdx_facts(welfare_policy, values))
    assert actual.action_id == WELFARE_PROGRAM
    assert actual.operation == "multiply"
    assert actual.delta == pytest.approx(1.08)
    assert 10 * actual.delta == pytest.approx(10.8)


def test_society_domains_and_chain_nodes_are_completely_declared():
    model = load_model()
    coverage = load()
    assert set(FAMILIES) >= SOCIETY_DOMAINS
    rows = [item for item in model.action_instances if item.family_id in SOCIETY_DOMAINS]
    assert {item.family_id for item in rows} == SOCIETY_DOMAINS
    assert all(
        coverage[name].production_instances
        == sum(
            item.family_id == name and item.kind == "rule_action" for item in model.action_instances
        )
        for name in SOCIETY_DOMAINS
    )
    chains = [chain for chain in CHAINS if set(chain.domain_ids) & SOCIETY_DOMAINS]
    assert chains
    assert all(
        any(item.family_id == domain for item in model.action_instances)
        for chain in chains
        for domain in chain.domain_ids
    )


def test_society_unknown_inputs_keep_vanilla_fallback_contract():
    model = load_model()
    assert all(load()[name].unknown_policy == "vanilla" for name in SOCIETY_DOMAINS)
    assert all(fact.unknown == "vanilla" for fact in model.facts)
    assert all(action.unknown_policy == "vanilla" for action in model.actions)
    assert model.contract()["behavior_quality"] != "verified"


def test_society_rules_can_be_reviewed_in_parallel_without_using_other_rule_ids_as_inputs():
    model = load_model()
    rows = [item for item in model.action_instances if item.family_id in SOCIETY_DOMAINS]
    ids = {item.action_id for item in rows}
    assert len(ids) == len(rows)
    assert all(not ids.intersection(item.condition_facts) for item in rows)
    assert all(item.vanilla_tail.startswith("retain_") for item in rows)


def test_society_local_relations_use_declared_scope_only():
    model = load_model()
    rows = [item for item in model.action_instances if item.family_id in SOCIETY_DOMAINS]
    assert all(item.actor_scope in {"root", "owner"} for item in rows)
    assert all(item.target_scope in {"none", "target_state"} for item in rows)
    assert all(
        item.target_scope
        == ("target_state" if item.consumer_field.endswith("state_value") else "none")
        for item in rows
    )
    assert all(relation.scope == "root" for relation in model.relations)
