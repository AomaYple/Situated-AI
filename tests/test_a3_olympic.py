"""Olympic native reward, bounded administrative tiers and exact ROOT integration."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace

import pytest
from test_remaining_joint_consumers import _block, _native_number, _overlay, _render

from pdx import decision_adapters, decision_interfaces, decision_rules
from pdx import native_decision_opportunities as olympic
from pdx.parser import parse_text
from pdx.situated import compiler, domain_coverage, programs, vanilla_inventory

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def policy():
    derived = olympic.derive({"readers": {}})
    # The real public parser must accept the proven getter. No test-only
    # interface registration: this fixture needs the shared integration.
    parsed = decision_rules.from_data(
        {
            "schema": 1,
            "baseline_sha256": derived["sources"][olympic.SOURCE],
            "domains": {"political": True},
            "readers": derived["readers"],
            "rules": [
                {key: value for key, value in row.items() if key != "source"}
                for row in derived["rules"]
            ],
        },
        source_sha256="0" * 64,
    )
    return programs.enable(parsed, source=olympic.SOURCE)


@pytest.fixture(scope="module")
def production(policy):
    actual = decision_adapters.load()
    inputs = decision_adapters.read_inputs(actual)
    olympic.verify_inputs(inputs)
    assert olympic.SOURCE in dict(actual.policies)
    assert {rule.id for rule in dict(actual.policies)[olympic.SOURCE].rules} == {
        rule.id for rule in policy.rules
    }
    selected = replace(
        actual,
        policies=((olympic.SOURCE, policy),),
        supply=None,
        initial_values=(),
        scalar_values=(),
        event_programs=(),
        acceptance_programs=(),
    )
    files, _ = decision_adapters.build(selected, texts=inputs)
    return files[olympic.SOURCE], selected, inputs


def _values(balance, output, population):
    return {
        "bureaucracy": balance,
        "olympic_bureaucracy_output": output,
        "cost_country_population": population,
    }


def _native_facts(balance, output, population, **changes):
    return {
        "ROOT": {
            "is_ai": True,
            "bureaucracy": balance,
            "produced_bureaucracy": output,
            "total_population": population,
            "is_at_war": False,
            "is_diplomatic_play_committed_participant": False,
            **changes,
        }
    }


CASES = [
    (1000, None, None, 1),
    (250, 1000, None, 0.9),
    (250, 10000, None, 0.8),
    (50, 1000, None, 0.8),
    (50, 10000, 1000, 0.8),
    (250, None, 1000, 0.9),
    (250, -1, 1000, 0.9),
    (250, True, 1000, 0.9),
    (250, float("nan"), 1000, 0.9),
    (None, 1000, 1000, 0.8),
    (float("nan"), 1000, 1000, 0.8),
    (True, 1000, 1000, 0.8),
    (None, None, 0, 0.8),
    (None, 10000, None, 1),
    (None, 10000, -1, 1),
    (50, None, None, 0.8),
    (1000, 10000, 1000, 1),
    (99.99, 1000, 1000, 0.8),
    (100, 1000, 1000, 0.9),
    (499.99, 1000, 1000, 0.9),
    (500, 10000, 1000, 1),
    (250, 4999.99, 1000, 0.9),
    (250, 5000, 1000, 0.8),
]


@pytest.mark.parametrize(("balance", "output", "population", "factor"), CASES)
def test_hand_calculated_overlay_matches_reference_and_actual_pdx(
    policy, production, balance, output, population, factor
):
    text, _, _ = production
    values = _values(balance, output, population)
    assert decision_rules.evaluate_ir(policy, values, is_ai=True).get(olympic.FIELD, ("", 1))[
        1
    ] == pytest.approx(factor)
    # Fixed native 5 here deliberately isolates the overlay's local unknown
    # semantics. A missing overlay observation does not prove that the engine
    # can produce 5 from an unknown value of the very same native getter.
    facts = _native_facts(balance, output, population)
    assert _native_number(5, _overlay(text, olympic.FIELD), facts) == pytest.approx(5 * factor)
    assert decision_rules.evaluate_ir(policy, values, is_ai=False) == {}
    assert (
        decision_rules.evaluate_ir(replace(policy, enabled_domains=frozenset()), values, is_ai=True)
        == {}
    )


@pytest.mark.parametrize(
    ("balance", "output", "war", "play", "expected"),
    [
        (250, 1000, False, False, 4.5),
        (250, 10000, False, False, 4),
        (1000, 10000, False, False, 5),
        (0, 10000, False, False, 0),
        (-1, 10000, False, False, 0),
        (50, 10000, True, False, 0),
        (50, 10000, False, True, 0),
        (50, 10000, True, True, 0),
    ],
)
def test_complete_native_positive_and_terminal_zero_paths(
    production, balance, output, war, play, expected
):
    text, _, _ = production
    chance = _block(_block(parse_text(text).root, olympic.DEFINITION), "ai_chance")
    initial = chance.all("value")
    assert len(initial) == 1
    assert _render(initial[0]) == "value = 0"
    body = "\n".join(_render(row) for row in chance.items if row is not initial[0])
    facts = _native_facts(
        balance,
        output,
        1000,
        is_at_war=war,
        is_diplomatic_play_committed_participant=play,
    )
    assert _native_number(0, body, facts) == pytest.approx(expected)


def test_full_parent_siblings_execution_and_disabled_output_preserved(production):
    text, adapters, inputs = production
    assert text.count("# SITAI BEGIN") == 1
    begin = text.index(f"# SITAI BEGIN information:{olympic.FIELD}")
    end = text.index(f"# SITAI END information:{olympic.FIELD}", begin)
    end = text.index("\n", end) + 1
    stripped = text[:begin] + text[end:]
    assert _render(parse_text(stripped).root) == _render(parse_text(inputs[olympic.SOURCE]).root)
    files, _ = decision_adapters.build(adapters, texts=inputs, enabled_domains=frozenset())
    assert files == {}
    body = _overlay(text, olympic.FIELD)
    # The one overlay's AI guard leaves the complete native value/if/tail
    # untouched for the player; native effects are compared above as AST.
    assert _native_number(5, body, _native_facts(50, 10000, 1000, is_ai=False)) == 5


def test_known_cost_survives_unrelated_unknowns_and_wrong_entity_changes(policy, production):
    text, _, _ = production
    values = {
        **_values(250, 1000, None),
        "prestige": None,
        "default": None,
        "net_surplus": None,
    }
    assert decision_rules.evaluate_ir(policy, values, is_ai=True)[olympic.FIELD][1] == 0.9
    facts = _native_facts(250, 1000, None)
    facts["scope:target_country"] = {"bureaucracy": 1, "produced_bureaucracy": 1000000}
    facts["scope:target_state"] = {"bureaucracy": 1, "produced_bureaucracy": 1000000}
    assert _native_number(5, _overlay(text, olympic.FIELD), facts) == pytest.approx(4.5)


def test_three_same_cause_cost_tiers_no_secondary_rewards(policy):
    assert len(policy.rules) == 3
    assert {rule.contribution_group for rule in policy.rules} == {"olympic_administration_exposure"}
    assert all(rule.semantic_role == "cost" and 0 < rule.value < 1 for rule in policy.rules)
    assert all(rule.operation == "multiply" and rule.domain == "political" for rule in policy.rules)
    assert {reader.engine for reader in policy.readers} == {
        "bureaucracy",
        "produced_bureaucracy",
        "total_population",
    }
    unknown = [rule for rule in policy.rules if rule.conservative_unknown_facts]
    assert len(unknown) == 1
    assert unknown[0].id == "olympic_very_thin_buffer"
    assert unknown[0].unknown_cost_required_known_facts == ("cost_country_population",)


def test_complete_freeze_and_single_exact_catalog():
    inputs = olympic.frozen_inputs()
    assert set(inputs) == olympic.SOURCES
    frozen = json.loads(olympic.FROZEN.read_text(encoding="utf-8"))
    for source, text in inputs.items():
        assert not parse_text(text, path=source).errors
        assert hashlib.sha256(text.encode()).hexdigest() == frozen["source_hashes"][source]
    (row,) = olympic.consumer_catalog()
    assert (row["source"], row["field"], row["actor"], row["target"]) == (
        olympic.SOURCE,
        olympic.FIELD,
        "root",
        "none",
    )
    assert (row["reward_prestige"], row["positive_native_weight"]) == (100, 5)
    assert (row["cost_multiplier"], row["duration_days"]) == (-0.1, 913)
    assert "not_exact_ratio" in row["calibration"]


@pytest.mark.parametrize("source", sorted(olympic.SOURCES))
def test_every_full_source_rejects_missing_and_drifted_inputs(source):
    inputs = olympic.frozen_inputs()
    with pytest.raises(ValueError, match="漂移"):
        olympic.verify_inputs({key: value for key, value in inputs.items() if key != source})
    with pytest.raises(ValueError, match="漂移"):
        olympic.verify_inputs({**inputs, source: inputs[source] + "\n# drift"})


def test_shared_reader_and_consumer_permissions_are_exact(policy):
    reader = next(reader for reader in policy.readers if reader.engine == "produced_bureaucracy")
    assert decision_interfaces.reader_scope(reader, (), native_root="country") == "country"
    for changed in (
        replace(reader, scope="target_country"),
        replace(reader, path=("owner",)),
        replace(reader, unit="capacity_balance"),
        replace(reader, minimum=None),
        replace(reader, maximum=100000),
        replace(reader, argument="scope:target_country"),
    ):
        with pytest.raises(ValueError):
            decision_interfaces.reader_scope(changed, (), native_root="country")
    with pytest.raises(ValueError):
        decision_interfaces.reader_scope(reader, ("owner",), native_root="state")
    expected = decision_interfaces.consumer(
        tuple(olympic.FIELD.split(".")), (), source=olympic.SOURCE, native_root="country"
    )
    assert expected["native_unit"] == "relative_weight"
    for source, field, actor, root in (
        (olympic.OUTPUT_SOURCE, olympic.FIELD, (), "country"),
        (olympic.SOURCE, "lowlands_land_reclamation.ai_chance", (), "country"),
        (olympic.SOURCE, olympic.FIELD, ("owner",), "state"),
    ):
        with pytest.raises(ValueError):
            decision_interfaces.consumer(
                tuple(field.split(".")), actor, source=source, native_root=root
            )


@pytest.mark.parametrize(
    "key", ["bureaucracy", "olympic_bureaucracy_output", "cost_country_population"]
)
def test_reader_identity_conflicts_rejected(key):
    derived = olympic.derive({"readers": {}})
    wrong = copy.deepcopy(derived["readers"][key])
    wrong["scope"] = "target_country"
    with pytest.raises(ValueError, match="完整身份"):
        olympic.derive({"readers": {key: wrong}})


@pytest.mark.parametrize(
    ("original", "changed"),
    [
        ("thin_buffer = 0.90", "thin_buffer = 1.10"),
        ("strong_exposure = 0.80", "strong_exposure = 0.95"),
        ("strong_exposure = 0.80", "strong_exposure = 0"),
        ("strong_exposure = 0.80", "strong_exposure = nan"),
        ("strong_exposure = 0.80", "strong_exposure = true"),
        ("schema = 1", "schema = 2"),
    ],
)
def test_invalid_tuning_cannot_turn_cost_into_reward_or_zero(
    tmp_path, monkeypatch, original, changed
):
    path = tmp_path / "invalid-olympic.toml"
    text = olympic.PARAMETERS.read_text(encoding="utf-8")
    assert text.count(original) == 1
    path.write_text(text.replace(original, changed), encoding="utf-8")
    monkeypatch.setattr(olympic, "PARAMETERS", path)
    with pytest.raises(ValueError, match="边界"):
        olympic.load()


def test_real_compiler_context_and_aiweight_bindings(production):
    _, _, _ = production
    model = compiler.load_model()
    selected = [
        instance for instance in model.action_instances if instance.source == olympic.SOURCE
    ]
    assert len(selected) == 3
    assert {instance.consumer_field for instance in selected} == {olympic.FIELD}
    assert model.consumer_ir is not None
    for instance in selected:
        context = instance.evaluation_context
        assert context is not None
        assert context.actor_scope is not None
        assert (context.actor_scope.name, context.actor_scope.kind, context.actor_scope.role) == (
            "root",
            "country",
            "actor",
        )
        assert not context.targets
        assert not context.auxiliary_scopes
        assert instance.actor_scope == "root"
        assert instance.target_scope == "none"
        assert instance.vanilla_tail == "retain_original_qualification_cost_random_execution"
        writer = next(
            row
            for row in model.consumer_ir.writers
            if row.source == instance.source and row.writer_id == instance.action_id
        )
        assert writer.evaluation_context == context
        assert writer.reader_context_bindings
        assert all(
            binding[1:] == ("root", "country", "actor")
            for binding in writer.reader_context_bindings
        )


def test_independent_native_coverage_requires_exact_source_context_and_rules(production):
    _, _, inputs = production
    model = compiler.load_model()
    adapters = decision_adapters.load()
    instances = tuple(item for item in model.action_instances if item.source == olympic.SOURCE)
    native = {source: text.encode("utf-8") for source, text in inputs.items()}
    parsed = parse_text(inputs[olympic.SOURCE], path=olympic.SOURCE)
    decision = parsed.root.first(olympic.DEFINITION)
    assert decision is not None
    weight = _block(parsed.root, olympic.DEFINITION).first("ai_chance")
    assert weight is not None
    scope = vanilla_inventory._scope(
        "decisions", ("ai_chance",), native, {}, decision, olympic.SOURCE
    )
    surface = vanilla_inventory._surface(
        olympic.SOURCE, olympic.DEFINITION, "ai_chance", weight.line, scope
    )
    inventory = vanilla_inventory.VanillaInventory(
        baseline_id="independent_olympic_complete_source",
        source_hashes={name: hashlib.sha256(raw).hexdigest() for name, raw in native.items()},
        scope_hash="a" * 64,
        surfaces=(surface,),
        scanned_directories=("decisions",),
        content_roots=("frozen_complete_native_sources",),
        parsed_files=len(native),
    )
    policies = dict(adapters.policies)
    report = domain_coverage.native_coverage(
        inventory, instances, native_sources=native, production_policies=policies
    )
    assert report["binding_issue_count"] == 0
    assert report["denominator"] == report["counts"]["actual_covered"] == 1
    assert len(report["rows"][0]["covered_actions"]) == 3
    for changed in (
        replace(instances[0], evaluation_context=None),
        replace(instances[0], operation="add"),
        replace(instances[0], source=olympic.OUTPUT_SOURCE),
    ):
        damaged = domain_coverage.native_coverage(
            inventory,
            (changed,),
            native_sources=native,
            production_policies=policies,
        )
        assert damaged["counts"]["actual_covered"] == 0
        assert damaged["binding_issue_count"] > 0 or damaged["unmatched_production"]
