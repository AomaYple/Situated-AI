"""本州真实大迁移目标与既有岗位吸纳同因升档。"""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from dataclasses import replace

import pytest
from test_remaining_joint_consumers import _block, _native_number, _overlay, _render
from test_situated_joint_witnesses import _facts

from pdx import config, country_state, decision_adapters, decision_interfaces, decision_rules
from pdx import migration_opportunities as migration
from pdx.model import Block
from pdx.parser import parse_text
from pdx.situated import compiler
from pdx.textio import normalized_text

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def budget_source():
    from unittest.mock import patch

    original = decision_rules.from_data
    captured = []

    def capture(data, *, source_sha256, strategy=None):
        if any(
            row["id"] == "migration_target_textile_employment_absorption" for row in data["rules"]
        ):
            captured.append((deepcopy(data), source_sha256, strategy))
        return original(data, source_sha256=source_sha256, strategy=strategy)

    with patch.object(decision_rules, "from_data", side_effect=capture):
        decision_adapters.load()
    assert len(captured) == 1
    return captured[0]


def test_textile_budget_extension_is_exactly_one_candidate_and_151_predicates(budget_source):
    data, digest, strategy = budget_source
    policy = decision_rules.from_data(deepcopy(data), source_sha256=digest, strategy=strategy)
    rules = [rule for rule in policy.rules if ".".join(rule.field) == migration.FIELD]
    assert len(rules) == 33
    assert sum(len(rule.conditions) + len(rule.required_known_facts) for rule in rules) == 151
    assert decision_rules.STATIC_BUDGET["candidates_per_field"] == 32
    assert decision_rules.STATIC_BUDGET["predicates_per_field"] == 160


@pytest.mark.parametrize("mutation", ["extra_rule", "different_baseline", "different_field"])
def test_local_budget_cannot_be_borrowed_by_extra_or_unrelated_consumers(budget_source, mutation):
    source, digest, strategy = budget_source
    data = deepcopy(source)
    if mutation == "extra_rule":
        extra = deepcopy(
            next(
                row
                for row in data["rules"]
                if row["id"] == "migration_target_textile_employment_absorption"
            )
        )
        extra["id"] += "_extra"
        extra["priority"] += 100000
        data["rules"].append(extra)
    elif mutation == "different_baseline":
        data["baseline_sha256"] = "0" * 64
    else:
        for rule in data["rules"]:
            if rule["field"] == migration.FIELD:
                rule["field"] = "building_migration_budget_probe.ai_value"
    with pytest.raises(ValueError, match="静态复杂度预算"):
        decision_rules.from_data(data, source_sha256=digest, strategy=strategy)


def test_real_state_root_event_and_exact_trigger_prove_migration_target():
    text = normalized_text(
        (config.GAME / migration.EVIDENCE_SOURCE).read_text(encoding="utf-8-sig")
    )
    assert migration.verify_inputs({migration.EVIDENCE_SOURCE: text}) == (
        f"{migration.EVIDENCE_SOURCE}:26",
    )
    with pytest.raises(ValueError, match="来源漂移"):
        migration.verify_inputs({migration.EVIDENCE_SOURCE: text + "\n"})


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        ("type = state_event", "type = country_event"),
        ("placement = root", "placement = scope:target_state"),
        ("is_mass_migration_target = yes", "is_mass_migration_target = no"),
    ],
)
def test_hash_rebaseline_alone_cannot_change_state_activity_scope(
    original, replacement, monkeypatch
):
    text = normalized_text(
        (config.GAME / migration.EVIDENCE_SOURCE).read_text(encoding="utf-8-sig")
    )
    changed = text.replace(original, replacement, 1)
    assert changed != text
    data = migration.load()
    data["sources"][migration.EVIDENCE_SOURCE] = hashlib.sha256(changed.encode()).hexdigest()
    monkeypatch.setattr(migration, "load", lambda: data)
    with pytest.raises(ValueError, match=r"州ROOT|getter"):
        migration.verify_inputs({migration.EVIDENCE_SOURCE: changed})


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    model = compiler.load_model()
    policy, _ = compiler.compile_policy(
        dict(adapters.policies)[migration.SOURCE], migration.SOURCE, model
    )
    selected = replace(
        adapters,
        policies=((migration.SOURCE, policy),),
        initial_values=tuple(
            row for row in adapters.initial_values if row.source == migration.SOURCE
        ),
        scalar_values=tuple(row for row in adapters.scalar_values if row[0] == migration.SOURCE),
        supply=None,
    )
    native = decision_adapters.read_inputs(selected)
    files, _ = decision_adapters.build(
        selected, texts=native, country_policy=country_state.load(), consumer_ir=model.consumer_ir
    )
    return policy, files[migration.SOURCE], native[migration.SOURCE]


def _values(policy, changes):
    values = dict.fromkeys(reader.key for reader in policy.readers)
    values.update(
        state_mass_migration_target=True,
        state_unemployment=0.1,
        state_owner_clothes_balance=-1,
        state_owner_default=False,
        state_infrastructure=0,
        state_market_access=1,
        state_owner_clothes_price=0,
        state_peasants_share=0.1,
    )
    values.update(changes)
    return values


CASES: list[tuple[dict[str, object], float]] = [
    ({}, 1.18),  # 1+.08 basic clothes need + max(.06 base jobs,.10 migration jobs).
    ({"state_mass_migration_target": False}, 1.14),
    ({"state_mass_migration_target": None}, 1.14),
    ({"state_mass_migration_target": False, "state_unemployment": 0.09999}, 1.08),
    ({"state_unemployment": 0.09999}, 1.08),
    ({"state_unemployment": None}, 1.08),
    ({"state_owner_clothes_balance": 0}, 1),
    ({"state_owner_clothes_balance": None}, 1),
    ({"state_owner_default": True}, 1.03),
]


@pytest.mark.parametrize(("changes", "expected"), CASES)
def test_real_production_joint_consumer_uses_same_cause_upgrade(production, changes, expected):
    policy, generated, _ = production
    values = _values(policy, changes)
    reference = decision_rules.evaluate(policy, values, is_ai=True)
    assert reference.get(migration.FIELD, ("native", 1))[1] == pytest.approx(expected)
    assert _native_number(
        1, _overlay(generated, migration.FIELD), _facts(policy, values)
    ) == pytest.approx(expected)


def test_exact_state_scope_and_reverse_country_decoys_cannot_supply_migration(production):
    policy, generated, _ = production
    reader = next(row for row in policy.readers if row.key == migration.READER)
    assert decision_interfaces.reader_scope(reader, ("owner",), native_root="state") == "state"
    for changed, actor, native in (
        (replace(reader, scope="target_state"), ("owner",), "state"),
        (replace(reader, path=("owner",)), ("owner",), "state"),
        (reader, (), "country"),
        (replace(reader, argument="root"), ("owner",), "state"),
    ):
        with pytest.raises(ValueError, match="真实候选州ROOT"):
            decision_interfaces.reader_scope(changed, actor, native_root=native)
    values = _values(policy, {"state_mass_migration_target": None})
    facts = _facts(policy, values)
    facts["ROOT"]["owner"]["is_mass_migration_target"] = True
    facts["other_state"] = {"is_mass_migration_target": True}
    facts["is_mass_migration_target"] = True
    assert _native_number(1, _overlay(generated, migration.FIELD), facts) == pytest.approx(1.14)
    facts["ROOT"]["owner"]["is_ai"] = False
    assert _native_number(1, _overlay(generated, migration.FIELD), facts) == 1
    assert decision_rules.evaluate(policy, values, is_ai=True, enabled_domains=frozenset()) == {}


def test_same_employment_group_and_complete_original_textile_consumer_are_retained(production):
    policy, generated, native = production
    employment = [
        rule
        for rule in policy.rules
        if ".".join(rule.field) == migration.FIELD
        and rule.contribution_group == "employment_absorption"
    ]
    assert {rule.id for rule in employment} == {
        "migration_target_textile_employment_absorption",
        "comparative_employment_active_building_textile_mill_pm_handsewn_clothes_output_clothes",
        "comparative_employment_active_building_textile_mill_pm_dye_workshops_output_clothes",
        "comparative_employment_active_building_textile_mill_pm_electric_sewing_machines_output_clothes",
        "comparative_employment_active_building_textile_mill_pm_sewing_machines_output_clothes",
        "lj06_employment_textile_unemployment_support",
    }
    stripped = re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        generated,
        flags=re.DOTALL,
    )
    original, retained = parse_text(native), parse_text(stripped)
    assert not original.errors
    assert not retained.errors
    before = _block(original.root, "building_textile_mill")
    after = _block(retained.root, "building_textile_mill")
    # The existing scalar-initialization adapter creates this native-missing
    # consumer at 1000. It is distinct from the bounded migration suffix.
    assert before.all("ai_value") == []
    assert _render(_block(after, "ai_value")) == "{ value = 1000 }"
    assert _render(before) == _render(
        Block([row for row in after.items if getattr(row, "key", None) != "ai_value"])
    )
