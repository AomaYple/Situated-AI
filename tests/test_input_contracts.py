"""四份工程输入合同的跨层反例；夹具不宣称真实原版或运行证据。"""

import json
import sys
from dataclasses import asdict, replace

import pytest

from pdx import input_contracts as contracts

pytestmark = pytest.mark.unit
H = "a" * 64
OTHER = "b" * 64
Bundle = tuple[
    contracts.InputIdentity,
    contracts.InputInventory,
    contracts.CapabilityRecord,
    contracts.ConsumerClosure,
]


def _bundle() -> Bundle:
    native = contracts.ArtifactRef("installation", "game/common/fixture.txt", H)
    evidence = contracts.ArtifactRef("evidence", "raw/fixture", H)
    source = contracts.ArtifactRef("repository", "src/pdx/fixture.py", H)
    record = contracts.InventoryRecord(
        native.path,
        12,
        H,
        "script",
        "game",
        "read",
        "complete",
        evidence,
        (),
        (),
        (),
        (),
        "complete",
    )
    digest = contracts.file_set_digest((record,))
    check = contracts.CaptureCheck("2026-11-12T00:00:00Z", H, digest, "stable")
    identity = contracts.InputIdentity(
        "fixture-installation",
        "fixture-version",
        "fixture-build",
        "public",
        (contracts.DlcState("optional", "yes", "unknown", "unknown", "unknown"),),
        (native,),
        1,
        digest,
        (source,),
        (source,),
        check,
        check,
        contracts.SnapshotProvenance("installation", "fixture", None, None),
        "complete",
    )
    inventory = contracts.InputInventory(identity.epoch_id, (record,), "complete", ())
    key = contracts.CapabilityKey(
        identity.version,
        identity.build_id,
        native,
        "observe",
        "fixture-reader",
        "fixture-consumer",
        contracts.RoleBinding("actor", "country"),
        (contracts.RoleBinding("target", "state"),),
        (),
        ("actor", "target"),
        "consumer_evaluation",
        (),
    )
    capability = contracts.CapabilityRecord(
        identity.epoch_id,
        key,
        "complete",
        "recognized",
        contracts.CapabilityStages(True, "proven", "proven", "proven", "proven", "unknown"),
        "points",
        "consumer_evaluation",
        "current_evaluation",
        "local_vanilla_fallback",
        contracts.CostRecord("unknown", "reader_calls", None, 1.0, "no engine measurement"),
        ("legal_read_candidate",),
        "static_check",
        (native,),
        (),
    )
    nodes = (
        contracts.ClosureNode("action", "action", source, None),
        contracts.ClosureNode("reader", "reader", source, capability.capability_id),
        contracts.ClosureNode("native", "native_source", native, None),
        contracts.ClosureNode(
            "generated", "generated", contracts.ArtifactRef("generated", "common/out.txt", H), None
        ),
        contracts.ClosureNode(
            "package", "package", contracts.ArtifactRef("package", "mod.zip", H), None
        ),
    )
    edges = (
        contracts.ClosureEdge("action", "reader", "binds"),
        contracts.ClosureEdge("reader", "native", "reads"),
        contracts.ClosureEdge("native", "generated", "generates"),
        contracts.ClosureEdge("generated", "package", "packages"),
    )
    closure = contracts.ConsumerClosure(
        identity.epoch_id, key.consumer, nodes, edges, (), "complete"
    )
    return identity, inventory, capability, closure


def _validate(bundle: Bundle, *, complete: bool = True) -> None:
    identity, inventory, capability, closure = bundle
    contracts.validate_handoff(
        identity, inventory, (capability,), closure, require_complete=complete
    )


def _rebind(bundle: Bundle, identity: contracts.InputIdentity) -> Bundle:
    _, inventory, capability, closure = bundle
    return (
        identity,
        replace(inventory, epoch_id=identity.epoch_id),
        replace(capability, epoch_id=identity.epoch_id),
        replace(closure, epoch_id=identity.epoch_id),
    )


def _add_inventory_record(bundle: Bundle, record: contracts.InventoryRecord) -> Bundle:
    identity, inventory, _, _ = bundle
    records = (*inventory.records, record)
    digest = contracts.file_set_digest(records)
    identity = replace(
        identity,
        file_count=len(records),
        file_set_sha256=digest,
        start=replace(identity.start, file_set_sha256=digest),
        end=replace(identity.end, file_set_sha256=digest),
    )
    identity, inventory, capability, closure = _rebind(bundle, identity)
    return identity, replace(inventory, records=records), capability, closure


def test_round_trip_preserves_unknown_dlc_runtime_and_cost() -> None:
    bundle = _bundle()
    _validate(bundle)
    for item in bundle:
        serialized = contracts.dumps_contract(item)
        restored = contracts.loads_contract(serialized)
        assert restored == item
        assert contracts.dumps_contract(restored) == serialized
    identity, _, capability, _ = bundle
    assert identity.dlcs[0].owned == "unknown"
    assert capability.stages.runtime == "unknown"
    assert capability.cost.amount is None


@pytest.mark.parametrize("value", [True, 1.0, "1", None])
def test_schema_is_an_exact_integer(value: object) -> None:
    data = asdict(_bundle()[0])
    data["schema"] = value
    with pytest.raises(contracts.InputContractError, match="invalid_enum"):
        contracts.loads_contract(json.dumps(data))


@pytest.mark.parametrize(
    "change",
    ["unknown_field", "missing_field", "nested_field", "bool_count", "wrong_tuple", "bad_kind"],
)
def test_strict_loader_rejects_silent_coercion_and_unknown_fields(change: str) -> None:
    data = json.loads(contracts.dumps_contract(_bundle()[0]))
    if change == "unknown_field":
        data["future_field"] = "ignored?"
    elif change == "missing_field":
        del data["branch"]
    elif change == "nested_field":
        data["dlcs"][0]["entitled"] = True
    elif change == "bool_count":
        data["file_count"] = True
    elif change == "wrong_tuple":
        data["dlcs"] = {"optional": "yes"}
    else:
        data["kind"] = []
    with pytest.raises(contracts.InputContractError):
        contracts.loads_contract(json.dumps(data))


def test_duplicate_json_keys_are_not_last_writer_wins() -> None:
    with pytest.raises(contracts.InputContractError, match="duplicate_json_key"):
        contracts.loads_contract('{"kind":"input_inventory","kind":"input_identity"}')


@pytest.mark.parametrize(
    "path", ["/absolute", "../escape", "a/../b", "a\\b", "C:/drive", "a//b", "a/./b"]
)
def test_artifact_paths_cannot_escape_or_change_platform_meaning(path: str) -> None:
    with pytest.raises(contracts.InputContractError, match="invalid_path"):
        contracts.ArtifactRef("installation", path, H)


def test_digest_requires_hex_not_only_length() -> None:
    with pytest.raises(contracts.InputContractError, match="invalid_digest"):
        contracts.ArtifactRef("evidence", "source", "z" * 64)


def test_changed_epoch_and_mixed_build_are_rejected() -> None:
    bundle = _bundle()
    identity, inventory, capability, closure = bundle
    changed = replace(identity, build_id="new-build")
    assert changed.epoch_id != identity.epoch_id
    with pytest.raises(contracts.InputContractError, match="epoch_mismatch"):
        _validate((changed, inventory, capability, closure))
    with pytest.raises(contracts.InputContractError, match="identity_mismatch"):
        _validate(_rebind(bundle, changed))


def test_read_drift_is_not_complete_even_if_final_count_matches() -> None:
    bundle = _bundle()
    identity = replace(bundle[0], end=replace(bundle[0].end, installation_sha256=OTHER))
    with pytest.raises(contracts.InputContractError, match="input_drift"):
        _validate(_rebind(bundle, identity))


def test_file_denominator_is_independent_of_order_and_rejects_duplicates() -> None:
    record = _bundle()[1].records[0]
    second = replace(record, path="game/another.txt")
    assert contracts.file_set_digest((record, second)) == contracts.file_set_digest(
        (second, record)
    )
    for duplicate in (record, replace(record, path=record.path.upper())):
        with pytest.raises(contracts.InputContractError, match="duplicate_path"):
            contracts.file_set_digest((record, duplicate))
    identity, inventory, capability, closure = _bundle()
    with pytest.raises(contracts.InputContractError, match="denominator_mismatch"):
        _validate((identity, replace(inventory, records=()), capability, closure))


def test_source_bytes_must_belong_to_current_inventory() -> None:
    identity, inventory, capability, closure = _bundle()
    bad = replace(capability, evidence=(replace(capability.key.source, sha256=OTHER),))
    with pytest.raises(contracts.InputContractError, match="source_mismatch"):
        _validate((identity, inventory, bad, closure))


@pytest.mark.parametrize("change", ["missing_path", "changed_hash"])
def test_installation_identity_source_must_match_inventory(change: str) -> None:
    bundle = _bundle()
    source = bundle[0].identity_sources[0]
    source = (
        replace(source, path="game/absent-identity.txt")
        if change == "missing_path"
        else replace(source, sha256=OTHER)
    )
    identity = replace(bundle[0], identity_sources=(source,))
    with pytest.raises(contracts.InputContractError, match="source_mismatch"):
        _validate(_rebind(bundle, identity))


def test_matching_installation_identity_source_is_preserved() -> None:
    bundle = _bundle()
    _validate(bundle)
    identity, inventory, _, _ = bundle
    record = inventory.records[0]
    assert record.sha256 is not None
    assert identity.identity_sources == (
        contracts.ArtifactRef("installation", record.path, record.sha256),
    )
    assert contracts.loads_contract(contracts.dumps_contract(identity)) == identity


def test_raw_complete_handoff_preserves_failed_parsing_and_diagnostics() -> None:
    identity, inventory, capability, closure = _bundle()
    diagnostic = contracts.Diagnostic("parse_failed", "parser cannot read this syntax", None)
    record = replace(
        inventory.records[0],
        parse_status="failed",
        completeness="failed",
        diagnostics=(diagnostic,),
    )
    inventory = replace(inventory, records=(record,))
    _validate((identity, inventory, capability, closure))
    assert contracts.loads_contract(contracts.dumps_contract(inventory)) == inventory


@pytest.mark.parametrize("change", ["path_and_hash", "namespace"])
def test_complete_reader_cannot_borrow_proof_for_another_source(change: str) -> None:
    bundle = _bundle()
    extra = replace(
        bundle[1].records[0],
        path="game/common/unrelated.txt",
        sha256=OTHER,
        raw=contracts.ArtifactRef("evidence", "raw/unrelated", OTHER),
    )
    identity, inventory, capability, closure = _add_inventory_record(bundle, extra)
    source = (
        contracts.ArtifactRef("installation", extra.path, OTHER)
        if change == "path_and_hash"
        else replace(capability.key.source, namespace="repository")
    )
    closure = replace(
        closure,
        nodes=tuple(
            replace(node, artifact=source) if node.role == "native_source" else node
            for node in closure.nodes
        ),
    )
    with pytest.raises(contracts.InputContractError, match="source_mismatch"):
        _validate((identity, inventory, capability, closure))


def test_complete_reader_can_include_additional_sources_and_dependencies() -> None:
    bundle = _bundle()
    extra = replace(bundle[1].records[0], path="game/common/additional.txt")
    identity, inventory, capability, closure = _add_inventory_record(bundle, extra)
    source = contracts.ArtifactRef("installation", extra.path, H)
    closure = replace(
        closure,
        nodes=(
            *closure.nodes,
            contracts.ClosureNode("additional", "native_source", source, None),
            contracts.ClosureNode("dependency", "dependency", capability.key.source, None),
        ),
        edges=(
            *closure.edges,
            contracts.ClosureEdge("reader", "additional", "reads"),
            contracts.ClosureEdge("additional", "dependency", "depends_on"),
            contracts.ClosureEdge("dependency", "generated", "generates"),
        ),
    )
    _validate((identity, inventory, capability, closure))


def test_partial_parsing_does_not_imply_unsupported_engine_capability() -> None:
    identity, inventory, capability, closure = _bundle()
    partial = replace(
        capability,
        parse_status="partial",
        semantic_status="unknown",
        stages=contracts.CapabilityStages(
            True, "unknown", "not_implemented", "unknown", "unknown", "unknown"
        ),
    )
    _validate((identity, inventory, partial, closure), complete=False)
    restored = contracts.loads_contract(contracts.dumps_contract(partial))
    assert isinstance(restored, contracts.CapabilityRecord)
    assert restored.parse_status == "partial"
    assert restored.stages.legality == "unknown"
    with pytest.raises(contracts.InputContractError, match="incomplete_capability"):
        _validate((identity, inventory, partial, closure))


def test_capability_context_does_not_borrow_another_scope_or_consumer() -> None:
    identity, inventory, capability, closure = _bundle()
    other = replace(capability, key=replace(capability.key, consumer="other-consumer"))
    assert other.capability_id != capability.capability_id
    changed_closure = replace(
        closure,
        nodes=tuple(
            replace(node, capability_id=other.capability_id) if node.role == "reader" else node
            for node in closure.nodes
        ),
    )
    with pytest.raises(contracts.InputContractError, match="consumer_mismatch"):
        _validate((identity, inventory, other, changed_closure))
    with pytest.raises(contracts.InputContractError, match="duplicate_capability"):
        contracts.validate_handoff(identity, inventory, (capability, capability), closure)


def test_dlc_installed_is_not_owned_or_script_available() -> None:
    identity, inventory, capability, closure = _bundle()
    key = replace(
        capability.key,
        dlc_conditions=(contracts.DlcCondition("optional", "script_available", "yes"),),
    )
    changed = replace(capability, key=key)
    closure = replace(
        closure,
        nodes=tuple(
            replace(node, capability_id=changed.capability_id) if node.role == "reader" else node
            for node in closure.nodes
        ),
    )
    with pytest.raises(contracts.InputContractError, match="unavailable_dlc"):
        _validate((identity, inventory, changed, closure))


@pytest.mark.parametrize("amount", [0.0, 1.0])
def test_unknown_cost_cannot_disappear_as_zero(amount: float) -> None:
    with pytest.raises(contracts.InputContractError, match="unknown_cost"):
        contracts.CostRecord("unknown", "reader_calls", amount, None, "not measured")


@pytest.mark.parametrize("amount", [float("nan"), float("inf"), -1.0, True])
def test_nonfinite_negative_and_boolean_costs_are_rejected(amount: float) -> None:
    data = json.loads(contracts.dumps_contract(_bundle()[2]))
    data["cost"].update(status="known", amount=amount)
    with pytest.raises(contracts.InputContractError):
        contracts.loads_contract(json.dumps(data))


@pytest.mark.parametrize(
    ("amount", "budget"),
    [(1, 2), (0, 1.0), (1.0, 2), (10**308, 10**308), (sys.float_info.max, sys.float_info.min)],
)
def test_accepted_cost_numbers_have_stable_canonical_round_trip(
    amount: float, budget: float
) -> None:
    capability = _bundle()[2]
    capability = replace(
        capability, cost=replace(capability.cost, status="known", amount=amount, budget=budget)
    )
    serialized = contracts.dumps_contract(capability)
    restored = contracts.loads_contract(serialized)
    assert contracts.dumps_contract(restored) == serialized
    cost = json.loads(serialized)["cost"]
    assert type(cost["amount"]) is float
    assert type(cost["budget"]) is float
    assert cost["amount"] == float(amount)
    assert cost["budget"] == float(budget)


@pytest.mark.parametrize("field", ["amount", "budget"])
@pytest.mark.parametrize("boundary", ["load", "dump", "handoff"])
def test_overflowing_cost_integer_is_a_stable_contract_error(field: str, boundary: str) -> None:
    identity, inventory, capability, closure = _bundle()
    capability = replace(
        capability,
        cost=replace(
            capability.cost,
            status="known",
            amount=10**1000 if field == "amount" else 1.0,
            budget=10**1000 if field == "budget" else 1.0,
        ),
    )
    if boundary == "load":
        with pytest.raises(contracts.InputContractError) as error:
            contracts.loads_contract(json.dumps(asdict(capability)))
    elif boundary == "dump":
        with pytest.raises(contracts.InputContractError) as error:
            contracts.dumps_contract(capability)
    else:
        with pytest.raises(contracts.InputContractError) as error:
            _validate((identity, inventory, capability, closure))
    assert error.value.code == "invalid_number"


def test_capability_requires_at_least_one_disposition() -> None:
    capability = _bundle()[2]
    with pytest.raises(contracts.InputContractError, match="missing_disposition"):
        replace(capability, dispositions=())
    data = json.loads(contracts.dumps_contract(capability))
    data["dispositions"] = []
    with pytest.raises(contracts.InputContractError, match="missing_disposition"):
        contracts.loads_contract(json.dumps(data))


def test_unresolved_disposition_preserves_unknown_research_capability() -> None:
    identity, inventory, capability, closure = _bundle()
    capability = replace(
        capability,
        parse_status="not_attempted",
        semantic_status="unknown",
        stages=contracts.CapabilityStages(
            True, "unknown", "unknown", "unknown", "unknown", "unknown"
        ),
        dispositions=("unresolved",),
    )
    _validate((identity, inventory, capability, closure), complete=False)
    assert contracts.loads_contract(contracts.dumps_contract(capability)) == capability


def test_static_evidence_cannot_claim_runtime_or_unproven_lowering() -> None:
    capability = _bundle()[2]
    with pytest.raises(contracts.InputContractError, match="invalid_stage"):
        replace(capability, stages=replace(capability.stages, runtime="proven"))
    with pytest.raises(contracts.InputContractError, match="invalid_stage"):
        replace(capability, stages=replace(capability.stages, legality="unknown"))


def test_legal_write_and_native_retention_do_not_fabricate_a_reader() -> None:
    identity, inventory, capability, closure = _bundle()
    for disposition in ("legal_write_candidate", "native_retained"):
        operation = replace(
            capability,
            key=replace(capability.key, reader=None, operation="retain_or_write"),
            dispositions=(disposition,),
        )
        assert contracts.loads_contract(contracts.dumps_contract(operation)) == operation
        changed = replace(
            closure,
            nodes=tuple(
                replace(node, capability_id=operation.capability_id)
                if node.role == "reader"
                else node
                for node in closure.nodes
            ),
        )
        with pytest.raises(contracts.InputContractError, match="invalid_operation"):
            _validate((identity, inventory, operation, changed))
    with pytest.raises(contracts.InputContractError, match="invalid_operation"):
        replace(capability, key=replace(capability.key, reader=None))


def test_direct_construction_is_checked_at_serialization_and_handoff_boundary() -> None:
    identity, inventory, capability, closure = _bundle()
    malformed = replace(identity, file_count=True)
    with pytest.raises(contracts.InputContractError, match="invalid_type"):
        contracts.dumps_contract(malformed)
    with pytest.raises(contracts.InputContractError, match="invalid_type"):
        _validate((malformed, inventory, capability, closure))


def test_closure_relations_cannot_shortcut_typed_production_chain() -> None:
    identity, inventory, capability, closure = _bundle()
    closure = replace(
        closure, edges=(contracts.ClosureEdge("action", "reader", "packages"), *closure.edges[1:])
    )
    with pytest.raises(contracts.InputContractError, match="invalid_edge"):
        _validate((identity, inventory, capability, closure))


def test_native_dependency_cycle_and_dead_end_are_rejected() -> None:
    identity, inventory, capability, closure = _bundle()
    dependency = contracts.ClosureNode("dependency", "dependency", capability.key.source, None)
    nodes = (*closure.nodes, dependency)
    branch = contracts.ClosureEdge("native", "dependency", "depends_on")
    closure = replace(closure, nodes=nodes, edges=(*closure.edges, branch))
    with pytest.raises(contracts.InputContractError, match="incomplete_closure"):
        _validate((identity, inventory, capability, closure))
    cycle = replace(
        closure, edges=(*closure.edges, contracts.ClosureEdge("dependency", "native", "depends_on"))
    )
    with pytest.raises(contracts.InputContractError, match="cyclic_closure"):
        _validate((identity, inventory, capability, cycle))
    complete = replace(
        closure,
        edges=(*closure.edges, contracts.ClosureEdge("dependency", "generated", "generates")),
    )
    _validate((identity, inventory, capability, complete))


def test_unknown_frontier_survives_round_trip_and_blocks_completion() -> None:
    identity, inventory, capability, closure = _bundle()
    closure = replace(
        closure,
        completeness="partial",
        nodes=tuple(
            replace(node, artifact=None) if node.id == "package" else node for node in closure.nodes
        ),
        unknown_frontier=(
            contracts.UnknownFrontier("package", "package not generated", ("ENG-12",)),
        ),
    )
    _validate((identity, inventory, capability, closure), complete=False)
    assert contracts.loads_contract(contracts.dumps_contract(closure)) == closure
    with pytest.raises(contracts.InputContractError, match="incomplete_handoff"):
        _validate((identity, inventory, capability, closure))


@pytest.mark.parametrize("failure", ["edge", "node", "frontier", "disconnected"])
def test_closure_rejects_dangling_and_disconnected_evidence(failure: str) -> None:
    identity, inventory, capability, closure = _bundle()
    if failure == "edge":
        closure = replace(
            closure, edges=(*closure.edges, contracts.ClosureEdge("missing", "package", "packages"))
        )
    elif failure == "node":
        closure = replace(closure, nodes=(*closure.nodes, closure.nodes[0]))
    elif failure == "frontier":
        closure = replace(
            closure,
            unknown_frontier=(contracts.UnknownFrontier("missing", "unknown", ("ENG-04",)),),
        )
    else:
        closure = replace(closure, edges=closure.edges[:-1])
    with pytest.raises(contracts.InputContractError):
        _validate((identity, inventory, capability, closure))
