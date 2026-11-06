"""Finite successor witnesses: source closure, native tails and unchanged old gates."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from pdx.situated import audit
from pdx.situated.native_treatments import native_treatments
from pdx.situated.vanilla_inventory import VanillaInventory, VanillaSurface
from tools.ci import a4_classify as classify
from tools.ci import a4_discovery as discovery
from tools.ci import a4_successor as successor
from tools.ci.a4_scope import Sources

NODE = "tests/test_domain.py::test_domain_witness"
PATH = "common/ai_strategies/fixture.txt"
NATIVE = b"candidate={unknown={value=10} sibling={value=2}}\n"


def _native(raw=NATIVE):
    surface = VanillaSurface(
        surface_id="protected",
        source=PATH,
        definition="candidate",
        field="unknown",
        actor_scope="unknown",
        target_scope="unknown",
        operation="declared_field",
        capability="pending",
        status="pending",
        getter=None,
        getter_note="no authority inferred",
        scope_evidence=(f"{PATH}:1",),
        responsibility_step="D0",
        source_line=1,
    )
    inventory = VanillaInventory(
        baseline_id="fixture",
        source_hashes={PATH: discovery.sha(NATIVE)},
        scope_hash="c" * 64,
        surfaces=(surface,),
        scanned_directories=("ai_strategies",),
        content_roots=("game",),
        parsed_files=1,
    )
    proof = native_treatments(inventory, {PATH: NATIVE}, {PATH: raw}, production_complete=True)
    return {"native_treatments": proof}


def _case(tmp_path):
    writer = {
        "source": "src/pdx/producer.py",
        "definition": "domain_need",
        "consumer_id": "candidate.unknown",
        "chain_refs": [],
        "native_source": PATH,
        "native_field": "candidate.unknown",
        "actor": "root",
        "target": "none",
        "semantic_ir_sha256": "a" * 64,
        "evaluation_context": "country",
        "semantic_role": "benefit",
        "unit": "ratio",
        "reader_context_bindings": [["capacity", "country"]],
        "fact_key_bindings": {"capacity": "fact:capacity"},
        "native_parent_ids": ["parent:candidate"],
        "native_physical_ids": ["physical:unknown"],
        "semantics": {"predicates": [{"fact": "capacity", "op": "<", "value": 1}]},
    }
    before = {
        "observations": {"raw": {"original": True}},
        "migration_writers": {"writer:domain": writer},
        "migration_files": {PATH: {"generated_sha256": discovery.sha(NATIVE)}},
        "targets": {"G01": {"current_writer_ids": ["writer:domain"]}},
        "predecessors": {"old:domain": {"current_writer_ids": ["writer:domain"]}},
        "facts": {"fact:capacity": {"unit": "ratio", "getter": "exact_country_getter"}},
        "current_native_boundaries": {"initializers": ["known"]},
    }
    after = deepcopy(before)
    after["migration_writers"]["writer:domain"].update(
        semantic_ir_sha256="b" * 64,
        semantic_role="opportunity_cost",
        semantics={"predicates": [{"fact": "capacity", "op": ">", "value": 0}]},
    )
    raw = {
        "tests/test_domain.py": b"def test_domain_witness():\n    assert 1 + 1 == 2\n",
        "src/pdx/producer.py": b"def produce():\n    return 'typed producer authority'\n",
        "native-proof.json": discovery.encoded(_native()),
        f"mod/{PATH}": NATIVE,
        "current.zip": b"independent package fixture",
        discovery.ROOT_PATH: discovery.encoded({"source_hashes": {PATH: discovery.sha(NATIVE)}}),
    }
    sources = Sources(tmp_path, raw)
    raw["mod/generation-lock.json"] = discovery.encoded(
        {
            "sources": {"src/pdx/producer.py": sources.hash("src/pdx/producer.py")},
            "files": {},
        }
    )
    sources = Sources(tmp_path, raw)
    transition = {
        "schema": 1,
        "base_commit": "a" * 40,
        "base_root": {
            "path": classify.CURRENT_ROOT,
            "sha256": "c" * 64,
            "identity": "whole_file",
            "kind": "file",
        },
        "before_sha256": discovery.digest(successor.payload(before)),
        "after_sha256": discovery.digest(successor.payload(after)),
        "native_proof": sources.reference("native-proof.json"),
        "witnesses": [
            {
                "node": NODE,
                "source": sources.reference(
                    "tests/test_domain.py", "test_domain_witness", "python"
                ),
            }
        ],
        "changes": [],
        "tombstones": [],
    }
    intake = {
        "schema": 2,
        "historical_commit": "d" * 40,
        "package": sources.reference("current.zip"),
        "status": "pending",
        "receipt_path": "pending",
        "witness_nodes": [NODE],
        "crosscheck_nodes": [NODE],
        "changes": [],
    }
    return sources, before, after, transition, intake


def _bind(sources, before, after, transition, intake):
    transition["before_sha256"] = discovery.digest(successor.payload(before))
    transition["after_sha256"] = discovery.digest(successor.payload(after))
    raw = {
        **sources.bytes,
        "before-authority.json": discovery.encoded(before),
        "after-authority.json": discovery.encoded(after),
    }
    sources = Sources(sources.root, raw)

    def authorities(item):
        side = "after" if item["after"]["present"] else "before"
        values = after if side == "after" else before
        artifact, identity = item["artifact"], item["identity"]
        row = values[artifact][identity]

        def proof(role, family, name, ref):
            return {
                "role": role,
                "side": side,
                "artifact": family,
                "identity": name,
                "reference": ref,
            }

        def row_ref(family, name):
            pointer = name.replace("~", "~0").replace("/", "~1")
            return sources.reference(f"{side}-authority.json", f"{family}/{pointer}", "json")

        result = [
            proof("endpoint", artifact, identity, row_ref(artifact, identity)),
            proof(
                "production",
                "generation_lock",
                "production_source_closure",
                sources.reference("mod/generation-lock.json"),
            ),
        ]
        if artifact == "migration_writers":
            result.extend(
                proof(role, artifact, identity, row_ref(artifact, identity))
                for role in ("producer", "context")
            )
            result.extend(
                proof("getter", "facts", fact, row_ref("facts", fact))
                for fact in set(row["fact_key_bindings"].values())
            )
            result.append(
                proof(
                    "native",
                    "native_report",
                    f"{row['native_source']}#{row['native_field']}",
                    transition["native_proof"],
                )
            )
        return result

    transition["changes"] = [
        {
            **item,
            "reason": "Independent typed domain candidate",
            "witness_nodes": [NODE],
            "authority": authorities(item),
        }
        for item in successor.differences(before, after)
    ]
    intake["changes"] = [
        {
            "writer_id": item["identity"],
            "before": item["before"]["semantic_ir_sha256"],
            "after": item["after"]["semantic_ir_sha256"],
            "reason": item["reason"],
            "witness_nodes": item["witness_nodes"],
        }
        for item in transition["changes"]
        if item["artifact"] == "migration_writers"
        and item["before"]["present"]
        and item["after"]["present"]
        and item["before"]["semantic_ir_sha256"] != item["after"]["semantic_ir_sha256"]
    ]
    raw = {**sources.bytes, "transition.json": discovery.encoded(transition)}
    bound = Sources(sources.root, raw)
    intake["successor"] = bound.reference("transition.json")
    return Sources(sources.root, {**raw, classify.CURRENT_INTAKE: discovery.encoded(intake)})


def test_successor_admits_complete_domain_payload_and_real_source_witness(tmp_path):
    sources, before, after, transition, intake = _case(tmp_path)
    sources = _bind(sources, before, after, transition, intake)
    assert classify.current_intake(sources)["schema"] == 2
    assert successor.contract(sources, intake) == transition
    assert successor.admit(sources, before, after, transition, frozen=sources) == (
        ["writer:domain"],
        {},
    )
    assert transition["changes"][0]["before"]["semantic_ir_sha256"] == "a" * 64
    assert transition["changes"][0]["after"]["payload_sha256"] == discovery.digest(
        after["migration_writers"]["writer:domain"]
    )


@pytest.mark.parametrize(
    "field",
    [
        "actor",
        "target",
        "evaluation_context",
        "semantic_role",
        "unit",
        "reader_context_bindings",
        "fact_key_bindings",
        "native_parent_ids",
        "native_physical_ids",
    ],
)
def test_successor_rejects_undeclared_context_getter_role_unit_and_native_authority(
    tmp_path, field
):
    sources, before, after, transition, intake = _case(tmp_path)
    sources = _bind(sources, before, after, transition, intake)
    changed = deepcopy(after)
    changed["migration_writers"]["writer:domain"][field] = "forged"
    with pytest.raises(ValueError, match="complete payload/authority"):
        successor.admit(sources, before, changed, transition, frozen=sources)


@pytest.mark.parametrize(
    "fault",
    ["missing", "duplicate", "wrong_before", "wrong_after", "presence", "semantic", "undeclared"],
)
def test_successor_rejects_forged_changed_sets_even_with_resigned_complete_hashes(tmp_path, fault):
    sources, before, after, transition, intake = _case(tmp_path)
    sources = _bind(sources, before, after, transition, intake)
    if fault == "missing":
        transition["changes"] = []
    elif fault == "duplicate":
        transition["changes"] *= 2
    elif fault == "wrong_before":
        transition["changes"][0]["before"]["payload_sha256"] = "f" * 64
    elif fault == "wrong_after":
        transition["changes"][0]["after"]["payload_sha256"] = "f" * 64
    elif fault == "presence":
        transition["changes"][0]["before"]["present"] = False
    elif fault == "semantic":
        transition["changes"][0]["after"]["semantic_ir_sha256"] = "f" * 64
    else:
        after["facts"]["fact:capacity"]["getter"] = "other_getter"
        transition["after_sha256"] = discovery.digest(successor.payload(after))
    with pytest.raises(ValueError, match="changed set"):
        successor.admit(sources, before, after, transition, frozen=sources)


@pytest.mark.parametrize("fault", ["empty", "wrong_function", "stale", "authority", "intake"])
def test_successor_rejects_empty_forged_or_stale_independent_witness_proof(tmp_path, fault):
    sources, before, after, transition, intake = _case(tmp_path)
    sources = _bind(sources, before, after, transition, intake)
    if fault == "empty":
        transition["changes"][0]["witness_nodes"] = []
    elif fault == "wrong_function":
        transition["witnesses"][0]["source"]["identity"] = "produce"
    elif fault == "stale":
        transition["native_proof"]["sha256"] = "0" * 64
    elif fault == "authority":
        transition["changes"][0]["authority"] = []
    else:
        intake["changes"] = []
    raw = {**sources.bytes, "transition.json": discovery.encoded(transition)}
    sources = Sources(tmp_path, raw)
    intake["successor"] = sources.reference("transition.json")
    with pytest.raises(ValueError, match=r"successor|stale hash|missing python"):
        successor.contract(sources, intake)


def test_successor_preserves_new_writer_and_removed_writer_lineage_without_product_authority(
    tmp_path,
):
    sources, before, after, transition, intake = _case(tmp_path)
    after["migration_writers"]["writer:new"] = after["migration_writers"].pop("writer:domain")
    sources = _bind(sources, before, after, transition, intake)
    with pytest.raises(ValueError, match="lineage/tombstone"):
        successor.admit(sources, before, after, transition, frozen=sources)
    transition["tombstones"] = [
        {
            "writer_id": "writer:domain",
            "before_sha256": discovery.digest(before["migration_writers"]["writer:domain"]),
            "successor_ids": ["writer:new"],
            "reason": "Exact successor source",
            "witness_nodes": [NODE],
        }
    ]
    changed, registry = successor.admit(sources, before, after, transition, frozen=sources)
    assert changed == ["writer:domain", "writer:new"]
    assert registry["writer:domain"]["previous"] == before["migration_writers"]["writer:domain"]
    assert registry["writer:domain"]["product_authority"] is False
    transition["tombstones"][0]["successor_ids"] = ["writer:absent"]
    with pytest.raises(ValueError, match="dangling"):
        successor.admit(sources, before, after, transition, frozen=sources)


def test_successor_refuses_raw_scope_or_discovery_loss_even_when_declared(tmp_path):
    sources, before, after, transition, intake = _case(tmp_path)
    after["observations"]["raw"]["original"] = False
    with pytest.raises(ValueError, match="immutable discovery/scope"):
        _bind(sources, before, after, transition, intake)
    after = deepcopy(before)
    after["predecessors"] = {}
    sources = _bind(sources, before, after, transition, intake)
    with pytest.raises(ValueError, match="stable discovery/predecessor"):
        successor.admit(sources, before, after, transition, frozen=sources)


@pytest.mark.parametrize("replacement", [b"sibling={value=3}", b"other={value=2}"])
def test_successor_uses_actual_native_projections_to_reject_sibling_and_parent_drift(
    tmp_path, replacement
):
    sources, before, after, _transition, _intake = _case(tmp_path)
    raw = NATIVE.replace(b"sibling={value=2}", replacement)
    after["migration_files"][PATH]["generated_sha256"] = discovery.sha(raw)
    sources = Sources(tmp_path, {**sources.bytes, f"mod/{PATH}": raw})
    with pytest.raises(ValueError, match="tail/parent/sibling"):
        successor.validate_native(
            sources, Sources(tmp_path, {f"mod/{PATH}": NATIVE}), before, after, _native(raw)
        )


def test_successor_native_report_must_be_rebuilt_not_signed_by_intake(tmp_path, monkeypatch):
    sources, before, after, transition, intake = _case(tmp_path)
    sources = _bind(sources, before, after, transition, intake)
    monkeypatch.setattr(audit, "native_report", _native)
    successor.native_protection(sources, sources, before, after, transition)
    forged = _native()
    forged["native_treatments"]["production_manifest_complete_asserted"] = False
    monkeypatch.setattr(audit, "native_report", lambda: forged)
    with pytest.raises(ValueError, match="independent normal production reconstruction"):
        successor.native_protection(sources, sources, before, after, transition)


def test_successor_initializer_permission_cannot_be_asserted_by_intake(tmp_path, monkeypatch):
    sources, before, after, transition, intake = _case(tmp_path)
    after["current_native_boundaries"]["initializers"].append("unproved_initializer")
    sources = _bind(sources, before, after, transition, intake)
    # Independent production reconstruction contains only the actual known set.
    actual = deepcopy(after)
    actual["current_native_boundaries"] = deepcopy(before["current_native_boundaries"])
    monkeypatch.setattr(audit, "native_report", _native)
    with pytest.raises(ValueError, match="complete payload/authority"):
        successor.admit(sources, before, actual, transition, frozen=sources)


def test_successor_existing_normal_proof_preserves_complete_unknown_native_source(tmp_path):
    sources, before, after, _transition, _intake = _case(tmp_path)
    frozen = Sources(tmp_path, {f"mod/{PATH}": NATIVE})
    successor.validate_native(sources, frozen, before, after, _native())


def test_successor_unproven_new_operand_cannot_replace_numeric_native_tail():
    # Exercise the existing independent native treatment, not a fabricated
    # context_closed boolean. The fixture's native opaque operand must survive.
    raw = b"candidate={unknown={value=10 multiply=native_opaque} sibling={value=2}}\n"
    source = "common/scripted_buttons/fixture.txt"
    surface = VanillaSurface(
        surface_id="numeric",
        source=source,
        definition="candidate",
        field="unknown",
        actor_scope="country",
        target_scope="none",
        operation="chance",
        capability="direct",
        status="pending",
        getter=None,
        getter_note="fixture",
        scope_evidence=(f"{source}:1",),
        responsibility_step="D0",
        source_line=1,
    )
    inventory = VanillaInventory(
        baseline_id="fixture",
        source_hashes={source: discovery.sha(raw)},
        scope_hash="c" * 64,
        surfaces=(surface,),
        scanned_directories=("scripted_buttons",),
        content_roots=("game",),
        parsed_files=1,
    )
    # Unknown opaque values cannot become an intake-authorized numeric change.
    changed = raw.replace(b"multiply=native_opaque", b"multiply=other_opaque")
    proof = native_treatments(inventory, {source: raw}, {source: changed}, production_complete=True)
    assert proof["rows"][0]["active_unknown_usage"]
    assert not proof["rows"][0]["interface"]["control_authorized"]


def test_successor_actual_typed_projection_keeps_complete_parent_sibling_and_tail(tmp_path):
    from dataclasses import asdict  # noqa: PLC0415

    source = "common/ai_regional_objectives/fixture.txt"
    raw = b"candidate={unknown=1 weight={value=unregistered_native_operand} sibling={value=2}}"
    surface = VanillaSurface(
        surface_id="unknown",
        source=source,
        definition="candidate",
        field="unknown",
        actor_scope="unknown",
        target_scope="unknown",
        operation="declared_field",
        capability="pending",
        status="pending",
        getter=None,
        getter_note="fixture",
        scope_evidence=(f"{source}:1",),
        responsibility_step="D0",
        source_line=1,
    )
    child = replace(
        surface,
        surface_id="weight",
        field="weight",
        actor_scope="country",
        target_scope="none",
        operation="score",
        capability="direct",
    )
    inventory = VanillaInventory(
        baseline_id="fixture",
        source_hashes={source: discovery.sha(raw)},
        scope_hash="c" * 64,
        surfaces=(surface, child),
        scanned_directories=("ai_regional_objectives",),
        content_roots=("game",),
        parsed_files=1,
    )
    coverage = {
        "baseline_id": inventory.baseline_id,
        "scope_hash": inventory.scope_hash,
        "source_hashes": inventory.source_hashes,
        "denominator": 2,
        "rows": [
            {
                **asdict(item),
                "declaration_id": item.declaration_id,
                "coverage_status": "actual_covered",
                "covered_actions": ["typed_writer"],
                "matched_actions": ["typed_writer"],
                "legal": item.legal,
                "unknown_scope": False,
                "binding_issues": {},
            }
            for item in inventory.surfaces
        ],
    }
    changed = raw.replace(
        b"unregistered_native_operand", b"unregistered_native_operand multiply=1.1"
    )
    proof = native_treatments(
        inventory, {source: raw}, {source: changed}, coverage=coverage, production_complete=True
    )
    assert proof["rows"][1]["interface"]["control_authorized"]
    before = {"migration_files": {source: {"generated_sha256": discovery.sha(raw)}}}
    after = {"migration_files": {source: {"generated_sha256": discovery.sha(changed)}}}
    sources = Sources(
        tmp_path,
        {
            f"mod/{source}": changed,
            discovery.ROOT_PATH: discovery.encoded({"source_hashes": inventory.source_hashes}),
        },
    )
    frozen = Sources(tmp_path, {f"mod/{source}": raw})
    successor.validate_native(sources, frozen, before, after, {"native_treatments": proof})
    broken = changed.replace(b"unregistered_native_operand", b"unregistered_other_operand")
    bad_proof = native_treatments(
        inventory, {source: raw}, {source: broken}, coverage=coverage, production_complete=True
    )
    assert bad_proof["rows"][1]["active_unknown_usage"]
    after["migration_files"][source]["generated_sha256"] = discovery.sha(broken)
    sources = Sources(tmp_path, {**sources.bytes, f"mod/{source}": broken})
    with pytest.raises(ValueError, match="tail/parent/sibling"):
        successor.validate_native(sources, frozen, before, after, {"native_treatments": bad_proof})


@pytest.mark.parametrize("forged", [False, True])
def test_successor_current_lifecycle_uses_independent_production_result(
    tmp_path, monkeypatch, forged
):
    sources, before, after, transition, intake = _case(tmp_path)
    actual = deepcopy(after)
    if forged:
        after["migration_writers"]["writer:domain"]["evaluation_context"] = "forged_owner"
    sources = _bind(sources, before, after, transition, intake)
    paths = {name: f"frozen/{name}.json" for name in before}
    frozen = Sources(
        tmp_path,
        {
            classify.CURRENT_ROOT: discovery.encoded(
                {"artifacts": {name: {"path": path} for name, path in paths.items()}}
            ),
            f"mod/{PATH}": NATIVE,
        },
    )
    monkeypatch.setattr(classify, "historical_checkpoint", lambda *_args: (frozen, before))
    monkeypatch.setattr(successor, "base", lambda *_args: (frozen, before))
    calls = []

    def artifacts(_sources, *, current_package, successor):
        calls.append((current_package, successor))
        return deepcopy(actual)

    monkeypatch.setattr(classify, "artifacts", artifacts)
    monkeypatch.setattr(audit, "native_report", _native)
    monkeypatch.setattr(classify, "migration_acceptance", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(classify, "stage_assignments", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        classify,
        "index_checkpoint",
        lambda *_args, **kwargs: {"product_completion": False, "successor": kwargs["successor"]},
    )
    if forged:
        with pytest.raises(ValueError, match="complete payload/authority"):
            classify.current_artifacts(sources, replay=False)
    else:
        values, checkpoint, actual_paths = classify.current_artifacts(sources, replay=False)
        assert values["migration_writers"] == actual["migration_writers"]
        assert values["migration_acceptance"] == {}
        assert checkpoint["product_completion"] is False
        assert checkpoint["current_migration_status"] == "pending"
        assert checkpoint["changed_writer_ids"] == ["writer:domain"]
        assert actual_paths["observations"] == paths["observations"]
    assert calls == [("current.zip", True)]


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "stale_junit",
        "source_drift",
        "nonancestor",
        "self_selected",
        "baseline_hash",
        "pending_base",
        "committed_candidate",
        "omitted_source",
        "omitted_function",
        "bad_command",
        "missing_production",
        "wrong_args_resigned",
        "stale_args",
        "wrong_junit_path",
    ],
)
def test_successor_base_reads_only_immediate_accepted_current_root_and_original_witness_bytes(
    tmp_path, monkeypatch, fault
):
    from tools.ci import (  # noqa: PLC0415
        a4_history,
        a4_scope,
    )
    from tools.ci.run_check import interpreter  # noqa: PLC0415

    historical_commit = "d" * 40
    raw = {
        classify.CURRENT_INTAKE: discovery.encoded(
            {
                "status": "verified",
                "receipt_path": "receipt.json",
                "witness_nodes": [NODE],
                "package": {"path": "current.zip"},
            }
        ),
        "before.json": discovery.encoded({"writer:old": {"semantic_ir_sha256": "a" * 64}}),
        "results.xml": b'<testsuites><testsuite><testcase classname="tests.test_domain" name="test_domain_witness"/></testsuite></testsuites>',
        "tests/test_domain.py": b"def test_domain_witness():\n    assert True\n",
    }
    paths = {
        classify.MIGRATION_PATH,
        "current.zip",
        classify.TASK6_PACKAGE,
        classify.TASK6_LOCK,
        *classify.INPUTS,
        *a4_scope.GATE_INPUTS,
    }
    raw.update(dict.fromkeys(paths, b"frozen complete production input\n"))
    raw["tools/ci/a4_scope.py"] = b"GATE_INPUTS = ()\n"
    raw[classify.MIGRATION_PATH] = discovery.encoded(
        {"objectives": {"fixture": {"witness_nodes": [NODE]}}}
    )
    raw["mod/generation-lock.json"] = discovery.encoded({"sources": {}, "files": {}})
    frozen = Sources(tmp_path, raw)
    receipt = {
        "schema": 1,
        "id": "accepted-current",
        "command": [
            str(interpreter(tmp_path)),
            "-B",
            "-X",
            "utf8",
            "-m",
            "pytest",
            "-o",
            "addopts=",
            "-q",
            "-p",
            "no:cacheprovider",
            NODE,
            f"--junitxml={tmp_path / 'results.xml'}",
        ],
        "selection": [NODE],
        "exit_code": 0,
        "junit": frozen.reference("results.xml"),
        "bindings": [
            frozen.reference("tests/test_domain.py", "test_domain_witness", "python"),
            *(
                frozen.reference(path)
                for path in [*paths, "mod/generation-lock.json", "tests/test_domain.py"]
            ),
        ],
        "passed": [NODE],
        "failed": [],
    }
    raw["receipt.json"] = discovery.encoded(receipt)
    frozen = Sources(tmp_path, raw)
    root = {
        "classification_status": "current_witnessed",
        "historical_commit": historical_commit,
        "inputs": [
            frozen.reference(classify.CURRENT_INTAKE),
            frozen.reference("receipt.json"),
            frozen.reference("results.xml"),
        ],
        "artifacts": {"migration_writers": frozen.reference("before.json")},
    }
    raw[classify.CURRENT_ROOT] = discovery.encoded(root)
    frozen = Sources(tmp_path, raw)
    transition = {"base_commit": "a" * 40, "base_root": frozen.reference(classify.CURRENT_ROOT)}
    sources = Sources(tmp_path, {classify.CURRENT_INTAKE: discovery.encoded({"schema": 2})})
    if fault == "stale_junit":
        raw["results.xml"] = raw["results.xml"].replace(b"test_domain_witness", b"other_witness")
    elif fault == "source_drift":
        raw["tests/test_domain.py"] += b"# changed test implementation\n"
    elif fault == "baseline_hash":
        transition["base_root"]["sha256"] = "0" * 64
    elif fault == "pending_base":
        root["classification_status"] = "current_migration_pending"
        raw[classify.CURRENT_ROOT] = discovery.encoded(root)
        transition["base_root"]["sha256"] = discovery.sha(raw[classify.CURRENT_ROOT])
    if fault in {
        "omitted_source",
        "omitted_function",
        "bad_command",
        "missing_production",
        "wrong_args_resigned",
        "stale_args",
        "wrong_junit_path",
    }:
        if fault == "omitted_source":
            receipt["bindings"] = [
                ref for ref in receipt["bindings"] if ref["path"] != "tests/test_domain.py"
            ]
            del raw["tests/test_domain.py"]
        elif fault == "omitted_function":
            receipt["bindings"] = [ref for ref in receipt["bindings"] if ref["kind"] != "python"]
        elif fault == "bad_command":
            receipt["command"] = ["never-ran-pytest"]
        elif fault == "missing_production":
            receipt["bindings"] = [
                ref for ref in receipt["bindings"] if ref["path"] != classify.TASK6_LOCK
            ]
        elif fault == "wrong_junit_path":
            receipt["command"][-1] = f"--junitxml={tmp_path / 'unrelated.xml'}"
        else:
            raw["selection.args"] = (NODE + "\n").encode()
            receipt["command"] = [
                *receipt["command"][:11],
                f"@{tmp_path / 'selection.args'}",
                receipt["command"][-1],
            ]
            receipt["bindings"].append(Sources(tmp_path, raw).reference("selection.args"))
            raw["selection.args"] = b"tests/test_other.py::test_other\n"
            if fault == "wrong_args_resigned":
                receipt["bindings"][-1] = Sources(tmp_path, raw).reference("selection.args")
        raw["receipt.json"] = discovery.encoded(receipt)
        fresh = Sources(tmp_path, raw)
        root["inputs"] = [
            fresh.reference(ref["path"], ref["identity"], ref["kind"]) for ref in root["inputs"]
        ]
        raw[classify.CURRENT_ROOT] = discovery.encoded(root)
        transition["base_root"] = Sources(tmp_path, raw).reference(classify.CURRENT_ROOT)

    def git(_root, *args):
        if args[0] == "merge-base":
            if fault == "nonancestor":
                raise ValueError("git input failed: nonancestor base")
            return b""
        if args[0] == "log":
            return f"{'b' * 40}\n{'a' * 40}\n".encode()
        if (
            args == ("show", f"{'b' * 40}:{classify.CURRENT_ROOT}")
            and fault == "committed_candidate"
        ):
            return discovery.encoded(
                {
                    **root,
                    "inputs": [
                        {
                            "path": classify.CURRENT_INTAKE,
                            "sha256": sources.hash(classify.CURRENT_INTAKE),
                        },
                        {"path": "tools/ci/a4_successor.py", "sha256": "e" * 64},
                    ],
                }
            )
        if args == ("show", f"{'b' * 40}:{classify.CURRENT_ROOT}") and fault == "self_selected":
            return discovery.encoded({**root, "newer_accepted_root": True})
        assert args[0] == "show"
        return raw[classify.CURRENT_ROOT]

    monkeypatch.setattr(a4_scope, "git", git)
    monkeypatch.setattr(
        a4_history, "tree", lambda _git, _root, _commit, paths: {path: raw[path] for path in paths}
    )
    if fault in {"none", "committed_candidate"}:
        _base, values = successor.base(
            sources, {"historical_commit": historical_commit}, transition
        )
        assert values["migration_writers"] == frozen.json("before.json")
    else:
        with pytest.raises(
            ValueError,
            match=r"stale hash|nonancestor|self-selected|verified current|historical|receipt",
        ):
            successor.base(sources, {"historical_commit": historical_commit}, transition)


def test_successor_changed_production_source_without_repin_fails_complete_closure(tmp_path):
    sources, before, after, transition, intake = _case(tmp_path)
    sources = _bind(sources, before, after, transition, intake)
    sources = Sources(
        tmp_path,
        {
            **sources.bytes,
            "src/pdx/producer.py": b"def produce():\n    return 'forged authority'\n",
        },
    )
    successor.contract(sources, intake)
    with pytest.raises(ValueError, match="production source closure drift"):
        successor.admit(sources, before, after, transition, frozen=sources)


def test_successor_new_writer_cannot_be_omitted_from_resigned_changed_set(tmp_path):
    sources, before, after, transition, intake = _case(tmp_path)
    sources = _bind(sources, before, after, transition, intake)
    after["migration_writers"]["writer:new"] = deepcopy(after["migration_writers"]["writer:domain"])
    transition["after_sha256"] = discovery.digest(successor.payload(after))
    with pytest.raises(ValueError, match="changed set"):
        successor.admit(sources, before, after, transition, frozen=sources)


def test_successor_native_source_cannot_be_excluded_by_intake(tmp_path):
    sources, before, after, transition, intake = _case(tmp_path)
    transition["excluded_native_sources"] = [PATH]
    sources = _bind(sources, before, after, transition, intake)
    with pytest.raises(ValueError, match="schema fields"):
        successor.contract(sources, intake)
    raw = NATIVE.replace(b"value=2", b"value=3")
    after["migration_files"][PATH]["generated_sha256"] = discovery.sha(raw)
    sources = Sources(tmp_path, {**sources.bytes, f"mod/{PATH}": raw})
    proof = _native(raw)
    proof["native_treatments"]["rows"] = []
    with pytest.raises(ValueError, match="complete native source proof missing"):
        successor.validate_native(
            sources, Sources(tmp_path, {f"mod/{PATH}": NATIVE}), before, after, proof
        )
