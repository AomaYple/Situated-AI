"""Exact local-chain provenance passes through the production IR and PDX patcher."""

from dataclasses import replace

import pytest

from pdx import country_state, decision_adapters, decision_interfaces, decision_rules
from pdx.situated import compiler, joint_chain_contract

pytestmark = pytest.mark.unit


FOOD_EMPLOYMENT = "comparative_employment_active_building_food_industry_pm_bakery_output_groceries"


def test_food_employment_chain_targets_the_unique_canonical_production_rule():
    source = "common/buildings/01_industry.txt"
    policy = dict(decision_adapters.load().policies)[source]
    rules = [rule for rule in policy.rules if rule.id == FOOD_EMPLOYMENT]
    assert len(rules) == 1
    assert not any(rule.id == "lj06_employment_food_unemployment_support" for rule in policy.rules)
    expected = (
        ("state_owner_default", "=", False),
        ("state_owner_loans", "=", False),
        ("state_infrastructure", ">=", 0),
        ("pm_active_building_food_industry_pm_bakery", "=", True),
        ("state_owner_groceries_price", ">", 0.25),
        ("state_owner_groceries_balance", "<", 0),
        ("state_owner_grain_price", "<=", 0.25),
        ("state_unemployment", ">=", 0.1),
        ("state_owner_reserves", ">", 0),
    )
    assert tuple((p.fact, p.op, p.value) for p in rules[0].conditions) == expected
    assert rules[0].required_known_facts == ()
    assert rules[0].auxiliary_facts == ()
    target = next(
        row
        for row in joint_chain_contract._STRICT_TARGETS
        if row[1] == "LJ06.employment_food_unemployment_support"
    )
    assert target[2:] == (
        source,
        FOOD_EMPLOYMENT,
        "building_food_industry.ai_value",
        "owner",
        "none",
        "multiply",
    )
    assert joint_chain_contract._EXPECTED_CONDITIONS[FOOD_EMPLOYMENT] == expected


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    information = decision_rules.load()
    model = compiler.load_model()
    assert model.consumer_ir is not None
    policies = ((joint_chain_contract.INFO_SOURCE, information), *adapters.policies)
    return model, adapters, policies


def test_complete_model_binds_only_the_current_proven_local_writers(production):
    model, _adapters, policies = production
    bundle = model.consumer_ir
    assert bundle is not None
    joint_chain_contract.validate_bundle_refs(bundle)
    assert len(bundle.chain_bindings) == 31
    assert len({writer for writer, _chain, _link in bundle.chain_bindings}) == 31
    assert {chain for _writer, chain, _link in bundle.chain_bindings} == {
        "LJ01",
        "LJ02",
        "LJ03",
        "LJ04",
        "LJ05",
        "LJ06",
        "LJ07",
        "LJ08",
        "LJ09",
        "LJ10",
        "LJ11",
        "LJ12",
        "LJ13",
        "LJ14",
    }
    rebound = joint_chain_contract.bind_bundle(bundle, policies)
    assert rebound == bundle
    rows = bundle.as_dict()["writers"]
    assert sum(bool(row["chain_refs"]) for row in rows) == 31
    evidence = joint_chain_contract.build_strict(bundle, policies)
    assert len(evidence) == 31
    assert joint_chain_contract.strict_contract(evidence)["pending_chain_closure"] == [
        f"LJ{index:02d}" for index in range(1, 15)
    ]


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "legacy_id", "knowledge"])
def test_food_chain_rejects_missing_ambiguous_or_relabelled_rule(production, mutation):
    model, _adapters, policies = production
    source = "common/buildings/01_industry.txt"
    policy = dict(policies)[source]
    food = next(rule for rule in policy.rules if rule.id == FOOD_EMPLOYMENT)
    others = tuple(rule for rule in policy.rules if rule.id != FOOD_EMPLOYMENT)
    rules = {
        "missing": others,
        "duplicate": (*policy.rules, food),
        "legacy_id": (*others, replace(food, id="lj06_employment_food_unemployment_support")),
        "knowledge": (*others, replace(food, required_known_facts=("state_owner_loans",))),
    }[mutation]
    changed = tuple(
        (name, replace(item, rules=rules) if name == source else item) for name, item in policies
    )
    with pytest.raises(ValueError, match=r"规则必须唯一|核心知识声明漂移"):
        joint_chain_contract.bind_bundle(model.consumer_ir, changed)


@pytest.mark.parametrize(
    "fact",
    [
        "state_owner_loans",
        "state_owner_reserves",
        "state_unemployment",
        "pm_active_building_food_industry_pm_bakery",
        "state_owner_groceries_balance",
        "state_owner_groceries_price",
        "state_owner_grain_price",
        "state_owner_default",
        "state_infrastructure",
    ],
)
def test_food_chain_revalidates_every_canonical_condition(production, fact):
    model, _adapters, policies = production
    source = "common/buildings/01_industry.txt"
    policy = dict(policies)[source]
    rules = tuple(
        replace(rule, conditions=tuple(p for p in rule.conditions if p.fact != fact))
        if rule.id == FOOD_EMPLOYMENT
        else rule
        for rule in policy.rules
    )
    changed = tuple(
        (name, replace(item, rules=rules) if name == source else item) for name, item in policies
    )
    with pytest.raises(ValueError, match="谓词、运算符或阈值漂移"):
        joint_chain_contract.bind_bundle(model.consumer_ir, changed)


@pytest.mark.parametrize(
    "key",
    ["state_owner_reserves", "state_unemployment", "pm_active_building_food_industry_pm_bakery"],
)
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("engine", "changed"),
        ("kind", "changed"),
        ("scope", "owner"),
        ("path", ("market",)),
        ("argument", "changed"),
        ("parameters", (("production_method", "pm_changed"),)),
        ("value_field", "changed"),
        ("unit", "changed"),
        ("minimum", -2),
        ("maximum", 2),
    ],
)
def test_food_chain_revalidates_complete_reader_identity(production, key, field, value):
    model, _adapters, policies = production
    source = "common/buildings/01_industry.txt"
    policy = dict(policies)[source]
    readers = tuple(
        replace(reader, **{field: value}) if reader.key == key else reader
        for reader in policy.readers
    )
    changed = tuple(
        (name, replace(item, readers=readers) if name == source else item)
        for name, item in policies
    )
    with pytest.raises(ValueError, match="读取器字段级来源、作用域或类型漂移"):
        joint_chain_contract.bind_bundle(model.consumer_ir, changed)


@pytest.mark.parametrize("mutation", ["missing", "cross_chain", "duplicate"])
def test_writer_trace_tampering_is_rejected_before_lowering(production, mutation):
    model, _adapters, policies = production
    bundle = model.consumer_ir
    writer = next(writer for writer in bundle.writers if writer.chain_refs)
    refs = {
        "missing": (),
        "cross_chain": (("LJ14", writer.chain_refs[0][1]),),
        "duplicate": writer.chain_refs * 2,
    }[mutation]
    damaged = replace(
        bundle,
        writers=tuple(
            replace(row, chain_refs=refs) if row == writer else row for row in bundle.writers
        ),
    )
    with pytest.raises(ValueError, match="writer 引用缺失或漂移"):
        damaged.as_dict()
    with pytest.raises(ValueError, match="writer 引用缺失或漂移"):
        joint_chain_contract.bind_bundle(damaged, policies)
    policy = dict(policies)[writer.source]
    with pytest.raises(ValueError, match="writer 引用缺失或漂移"):
        compiler.compile_policy(policy, writer.source, replace(model, consumer_ir=damaged))


def test_registry_and_target_tampering_cannot_rebind_or_serialize(production):
    model, _adapters, policies = production
    bundle = model.consumer_ir
    truncated = replace(bundle, chain_bindings=bundle.chain_bindings[:-1])
    with pytest.raises(ValueError, match="绑定清单缺失或漂移"):
        joint_chain_contract.bind_bundle(truncated, policies)
    writer = next(writer for writer in bundle.writers if writer.chain_refs)
    changed_target = replace(
        bundle,
        writers=tuple(
            replace(row, target="target_state") if row == writer else row for row in bundle.writers
        ),
    )
    with pytest.raises(ValueError, match="身份或目标漂移"):
        changed_target.as_dict()
    with pytest.raises(ValueError, match="writer 字段或操作漂移"):
        joint_chain_contract.bind_bundle(changed_target, policies)


def test_binding_revalidates_full_reader_identity_and_unique_source(production):
    model, _adapters, policies = production
    bundle = model.consumer_ir
    source = joint_chain_contract.INFO_SOURCE
    policy = dict(policies)[source]
    changed = replace(
        policy,
        readers=tuple(
            replace(reader, path=("market", "mg:tools")) if reader.key == "grain_price" else reader
            for reader in policy.readers
        ),
    )
    damaged = tuple((name, changed if name == source else item) for name, item in policies)
    with pytest.raises(ValueError, match="读取器字段级来源、作用域或类型漂移"):
        joint_chain_contract.bind_bundle(bundle, damaged)
    with pytest.raises(ValueError, match="策略来源重复"):
        joint_chain_contract.bind_bundle(bundle, (*policies, policies[0]))


@pytest.mark.integration
def test_real_pdx_contains_exact_chain_source_map_for_each_bound_writer(production):
    model, adapters, policies = production
    bundle = model.consumer_ir
    compiled = tuple(
        (source, compiler.compile_policy(policy, source, model)[0])
        for source, policy in adapters.policies
    )
    inputs = decision_adapters.read_inputs(adapters)
    files, _contract = decision_adapters.build(
        replace(adapters, policies=compiled),
        texts=inputs,
        country_policy=country_state.load(),
        consumer_ir=bundle,
    )
    info_source = joint_chain_contract.INFO_SOURCE
    information = compiler.compile_policy(dict(policies)[info_source], info_source, model)[0]
    baseline = compiler.baseline_path().read_text(encoding="utf-8")
    files[info_source] = decision_rules.patch(
        baseline,
        information,
        baseline=baseline,
        reader_words=(
            frozenset(decision_adapters.reader_evidence(inputs))
            | decision_interfaces.proven_reader_words()
        ),
        country_policy=country_state.load(),
        consumer_ir=bundle,
        consumer_source=info_source,
    )
    expected = set()
    for writer in bundle.writers:
        for chain_id, link_id in writer.chain_refs:
            marker = f"# SITAI CHAIN {chain_id}/{link_id} writer={writer.writer_id}"
            scalar_fields = {(source, ".".join(field)) for source, field in adapters.scalar_values}
            destination = (
                "common/script_values/sitai_adapter_values.txt"
                if (writer.source, writer.field) in scalar_fields
                else writer.source
            )
            assert files[destination].count(marker) == 1
            expected.add((destination, marker))
    actual = {
        (source, line.strip())
        for source, text in files.items()
        for line in text.splitlines()
        if line.strip().startswith("# SITAI CHAIN ")
    }
    assert actual == expected
    assert len(actual) == 31


def test_removing_all_trace_fields_from_bound_bundle_cannot_bypass_validation(production):
    model, _adapters, policies = production
    bundle = model.consumer_ir
    stripped = replace(
        bundle,
        writers=tuple(replace(writer, chain_refs=()) for writer in bundle.writers),
        chain_bindings=(),
    )
    assert stripped.chains_bound
    with pytest.raises(ValueError, match="绑定清单缺失或漂移"):
        stripped.as_dict()
    with pytest.raises(ValueError, match="绑定清单缺失或漂移"):
        joint_chain_contract.bind_bundle(stripped, policies)


def test_writer_predicates_cannot_be_relabelled_as_valid_chain_evidence(production):
    model, _adapters, policies = production
    bundle = model.consumer_ir
    writer = next(writer for writer in bundle.writers if writer.chain_refs)
    damaged = replace(
        bundle,
        writers=tuple(
            replace(row, predicates=()) if row == writer else row for row in bundle.writers
        ),
    )
    with pytest.raises(ValueError, match="writer 语义漂移"):
        joint_chain_contract.bind_bundle(damaged, policies)
