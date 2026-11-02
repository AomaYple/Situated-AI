"""Exact local-chain provenance passes through the production IR and PDX patcher."""

from dataclasses import replace

import pytest

from pdx import country_state, decision_adapters, decision_interfaces, decision_rules
from pdx.situated import compiler, joint_chain_contract

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def production():
    adapters = decision_adapters.load()
    information = decision_rules.load()
    model = compiler.load_model()
    assert model.consumer_ir is not None
    policies = ((joint_chain_contract.INFO_SOURCE, information), *adapters.policies)
    return model, adapters, policies


def test_complete_model_binds_only_the_thirty_four_proven_local_writers(production):
    model, _adapters, policies = production
    bundle = model.consumer_ir
    assert bundle is not None
    joint_chain_contract.validate_bundle_refs(bundle)
    assert len(bundle.chain_bindings) == 34
    assert len({writer for writer, _chain, _link in bundle.chain_bindings}) == 34
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
    assert sum(bool(row["chain_refs"]) for row in rows) == 34
    evidence = joint_chain_contract.build_strict(bundle, policies)
    assert len(evidence) == 34
    assert joint_chain_contract.strict_contract(evidence)["pending_chain_closure"] == [
        f"LJ{index:02d}" for index in range(1, 15)
    ]


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
    baseline = compiler.BASELINE.read_text(encoding="utf-8")
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
    assert len(actual) == 34


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
