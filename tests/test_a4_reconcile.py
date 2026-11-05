"""Progress preservation, mapping existence and fail-closed preview primitives."""

from __future__ import annotations

import copy

import pytest

from tools.ci import a4_reconcile as reconcile
from tools.ci import a4_scope as gate
from tools.ci.a4_schema import pending_row


def row_for(sources, path, identity):
    discovery = {
        "id": identity,
        "origin": "fixture",
        "identity": identity,
        "source": sources.reference(path),
        "goal_ids": ["G01"],
    }
    return pending_row(discovery, "1.15.0")


def test_stale_closure_is_transitive_and_preserves_unrelated(tmp_path) -> None:
    for name in ("changed.txt", "unrelated.txt"):
        (tmp_path / name).write_text("before\n", encoding="utf8")
    sources = gate.Sources(tmp_path)
    first = row_for(sources, "changed.txt", "first")
    second = row_for(sources, "unrelated.txt", "second")
    second["dependency_ids"] = [first["id"]]
    unrelated = row_for(sources, "unrelated.txt", "unrelated")
    unrelated.update(
        disposition="retain_native", interface_status="native_handled", obligation_status="retained"
    )
    before = copy.deepcopy(unrelated)
    (tmp_path / "changed.txt").write_text("after\n", encoding="utf8")
    assert reconcile.stale_closure([first, second, unrelated], gate.Sources(tmp_path)) == {
        first["id"],
        second["id"],
    }
    assert unrelated == before


def test_a4_zero_requires_consumer_and_writer_mappings(tmp_path) -> None:
    (tmp_path / "source.txt").write_text("fixture", encoding="utf8")
    row = row_for(gate.Sources(tmp_path), "source.txt", "consumer")
    report = {"consumer_ids": ["consumer"], "writer_ids": ["consumer"]}
    gate.inventory_mappings({row["id"]: row}, [report], "A4-0")
    row["domain"] = "different"
    with pytest.raises(ValueError, match="mapping coverage missing"):
        gate.inventory_mappings({row["id"]: row}, [report], "A4-0")


def test_crosscheck_does_not_trust_receipt_declared_bindings(tmp_path) -> None:
    sources = gate.Sources(tmp_path)
    report = {"crosscheck_receipt_ids": ["run"], "source_inputs": []}
    data = {
        "receipts": [],
        "inventory": {"crosscheck_receipts": ["run"], "investigation_sources": [{}]},
    }
    with pytest.raises(ValueError, match="missing inventory crosscheck"):
        gate.validate_crosschecks(sources, data, [report], "A4-0")
    report["crosscheck_receipt_ids"] = []
    with pytest.raises(ValueError, match="mapping mismatch"):
        gate.validate_crosschecks(sources, data, [report], "A4-0")
    data["inventory"]["crosscheck_receipts"] = []
    with pytest.raises(ValueError, match="explicitly pending"):
        gate.validate_crosschecks(sources, data, [report], "A4-1")


def test_publish_preview_failure_does_not_change_roots(tmp_path, monkeypatch) -> None:
    for path in (gate.DISCOVERY_INDEX, gate.LEDGER):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"original\n")

    def reject(*args, **kwargs):
        raise ValueError("candidate rejected")

    monkeypatch.setattr(gate, "validate", reject)
    with pytest.raises(ValueError, match="candidate rejected"):
        reconcile.publish(tmp_path, {}, {})
    assert all(
        (tmp_path / path).read_bytes() == b"original\n"
        for path in (gate.DISCOVERY_INDEX, gate.LEDGER)
    )


def test_reconcile_keeps_decisions_maps_progress_and_archives_only_stale(
    tmp_path, monkeypatch
) -> None:
    from tools.ci import a4_history

    paths = {
        gate.MANIFEST,
        gate.SNAPSHOT,
        gate.SUMMARY,
        gate.DISCOVERY_INDEX,
        a4_history.HISTORY_PATH,
        *gate.GATE_INPUTS,
        *gate.PLANS,
        "original.gz",
        "first.txt",
        "dependent.txt",
        "unrelated.txt",
    }
    for path in paths:
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"before\n")
    sources = gate.Sources(tmp_path)
    rows = [
        row_for(sources, path, name)
        for path, name in (
            ("first.txt", "first"),
            ("dependent.txt", "dependent"),
            ("unrelated.txt", "unrelated"),
        )
    ]
    rows[0].update(
        disposition="retain_native", interface_status="native_handled", obligation_status="retained"
    )
    rows[1]["dependency_ids"] = [rows[0]["id"]]
    rows[2]["obligation_status"] = "in_progress"
    old_rows = copy.deepcopy(rows)
    discoveries = [
        {
            "id": row["discovery_ids"][0],
            "kind": "discovery",
            "origin": "fixture",
            "identity": row["domain"],
            "source": row["input_hashes"][0],
            "goal_ids": row["goal_ids"],
        }
        for row in rows
    ]
    original = sources.reference("original.gz")
    migrations = [
        {
            "old_id": "A3-original",
            "old_status": "pending",
            "old_row_sha256": "1" * 64,
            "original_sha256": "2" * 64,
            "decision": "retain",
            "row_ids": [rows[0]["id"]],
            "reason": "keep original mapping",
        }
    ]
    data = {
        "schema": 2,
        "plan": "A4",
        "freeze": {
            "target_version": "1.15.0",
            "plan_inputs": [],
            "inputs": [],
            "a3_original": original,
            "candidate_commit": gate.CANDIDATE,
            "production_base": gate.PRODUCTION_BASE,
            "installation": {
                "root": "/synthetic-no-game",
                "version": [{"key": "caligula_branch", "value": "release/1.15.0"}],
                "exe_sha256": "1" * 64,
                "steam_manifest_sha256": "2" * 64,
                "steam_buildid": "synthetic",
                "jomini_revision": "unknown",
                "trees": [],
            },
        },
        "inventory": {
            "stage": "A4-1",
            "status": "pending",
            "reason": "pending",
            "scanned_directories": [],
            "parse_failures": [],
            "unrecognized": [],
            "duplicates": [],
            "crosscheck_receipts": [],
            "dlc_ids": [],
            "investigation_sources": [],
        },
        "discoveries": discoveries,
        "rows": rows,
        "pending_rows": [],
        "stale_history": [],
        "migrations": migrations,
        "candidate_changes": [],
        "receipts": [],
        "facts": [],
        "ports": [],
        "causes": [],
    }
    (tmp_path / "first.txt").write_bytes(b"after\n")
    expected = copy.deepcopy(discoveries)
    expected[0]["source"] = gate.Sources(tmp_path).reference("first.txt")
    monkeypatch.setattr(gate, "original_a3", lambda _: (original, []))
    monkeypatch.setattr(gate, "changes", lambda _: [])
    monkeypatch.setattr(gate, "discover", lambda *_args: expected)
    monkeypatch.setattr(gate, "load_investigations", lambda *_args: ([], [], []))
    monkeypatch.setattr(gate, "production_paths", lambda _: [])
    result, summary = reconcile.reconcile(data, tmp_path)
    assert result["rows"][0]["disposition"] == "retain_native"
    assert result["rows"][0]["obligation_status"] == "pending"
    assert result["rows"][1]["obligation_status"] == "pending"
    assert result["rows"][2] == old_rows[2]
    assert result["migrations"] == migrations
    assert len(result["stale_history"]) == 2
    assert summary["stale_rows"] == sorted([row["id"] for row in rows[:2]])
    assert data["rows"] == old_rows


def test_crosscheck_expected_set_comes_from_report_inputs(tmp_path, monkeypatch) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_witness.py").write_text(
        "def test_actual():\n    pass\n", encoding="utf8"
    )
    (tmp_path / "report.json").write_bytes(b"{}")
    sources = gate.Sources(tmp_path)
    witness = sources.reference("tests/test_witness.py", "test_actual", "python")
    reference = sources.reference("report.json")
    report = {"crosscheck_receipt_ids": ["run"], "source_inputs": [witness]}
    data = {
        "receipts": [{"id": "run", "path": "fake-receipt.json", "sha256": "0" * 64}],
        "inventory": {"crosscheck_receipts": ["run"], "investigation_sources": [reference]},
    }
    observed = []
    monkeypatch.setattr(
        gate,
        "verify_receipt",
        lambda _source, _stub, needed, nodes: observed.append((needed, nodes)),
    )
    gate.validate_crosschecks(sources, data, [report], "A4-0")
    assert observed == [([reference, witness], ["tests/test_witness.py::test_actual"])]


@pytest.mark.parametrize("disposition", ["implement", "retain_native", "unsupported"])
def test_mixed_unresolved_group_cannot_be_signed(tmp_path, disposition) -> None:
    (tmp_path / "source.txt").write_bytes(b"fixture")
    row = row_for(gate.Sources(tmp_path), "source.txt", "raw-member")
    row["disposition"] = disposition
    row["interface_status"] = (
        "verified"
        if disposition == "implement"
        else "native_handled"
        if disposition == "retain_native"
        else "unsupported"
    )
    row["obligation_status"] = "verified" if disposition == "implement" else "retained"
    catalog = {"unresolved_groups": ["mixed"], "groups": {"mixed": ["raw-member", "other-unknown"]}}
    with pytest.raises(ValueError, match="unresolved aggregate"):
        gate.validate_unresolved({row["id"]: row}, [catalog])


def test_independent_index_must_include_native_report(tmp_path) -> None:
    from tools.ci.a4_discovery import write_json

    write_json(tmp_path / gate.DISCOVERY_INDEX, {"schema": 1, "plan": "A4", "investigations": []})
    with pytest.raises(ValueError, match="native projection report coverage"):
        gate.load_investigations(gate.Sources(tmp_path), "1.15.0")


def test_source_hash_cache_is_session_local_and_does_not_cache_identity(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / "catalog.json").write_bytes(b'{"first":1,"second":2}')
    original_sha = gate.sha
    calls = []
    monkeypatch.setattr(gate, "sha", lambda raw: (calls.append(len(raw)), original_sha(raw))[1])
    source = gate.Sources(tmp_path)
    first = source.reference("catalog.json", "first", "json")
    for _ in range(100):
        source.verify(first)
    source.verify({**first, "identity": "second"})
    assert len(calls) == 1
    with pytest.raises(ValueError, match="missing json identity"):
        source.verify({**first, "identity": "missing"})
    (tmp_path / "catalog.json").write_bytes(b'{"first":3}')
    with pytest.raises(ValueError, match="stale hash"):
        gate.Sources(tmp_path).verify(first)


@pytest.mark.parametrize("mutation", ["changed", "deleted", "invalid_receipt_schema"])
def test_receipt_owned_junit_invalidates_direct_and_transitive_only(tmp_path, mutation) -> None:
    from tools.ci.a4_discovery import write_json
    from tools.ci.a4_schema import RECEIPT, check_shape

    (tmp_path / "source.txt").write_bytes(b"same input")
    (tmp_path / "run.xml").write_bytes(b"<testsuites/>")
    sources = gate.Sources(tmp_path)
    rows = [row_for(sources, "source.txt", name) for name in ("direct", "dependent", "unrelated")]
    rows[0].update(
        disposition="retain_native", interface_status="native_handled", obligation_status="retained"
    )
    rows[0]["witnesses"] = [
        {"node_id": "tests/test_witness.py::test_actual", "case_ids": ["case"], "receipt_id": "run"}
    ]
    rows[1]["dependency_ids"] = [rows[0]["id"]]
    rows[2]["obligation_status"] = "in_progress"
    receipt = {
        "schema": 1,
        "id": "run",
        "command": ["controlled-interpreter"],
        "selection": ["tests/test_witness.py::test_actual"],
        "exit_code": 0,
        "junit": sources.reference("run.xml"),
        "bindings": [sources.reference("source.txt")],
        "passed": ["tests/test_witness.py::test_actual"],
        "failed": [],
    }
    check_shape(receipt, RECEIPT)
    write_json(tmp_path / "receipt.json", receipt)
    stub = {
        "id": "run",
        "path": "receipt.json",
        "sha256": gate.sha((tmp_path / "receipt.json").read_bytes()),
    }
    before = copy.deepcopy(rows)
    assert reconcile.stale_closure(rows, gate.Sources(tmp_path), [stub]) == set()
    if mutation == "changed":
        (tmp_path / "run.xml").write_bytes(b"changed JUnit")
    elif mutation == "deleted":
        (tmp_path / "run.xml").unlink()
    else:
        receipt["unexpected"] = "not the actual receipt contract"
        write_json(tmp_path / "receipt.json", receipt)
        stub["sha256"] = gate.sha((tmp_path / "receipt.json").read_bytes())
    assert reconcile.stale_closure(rows, gate.Sources(tmp_path), [stub]) == {
        rows[0]["id"],
        rows[1]["id"],
    }
    assert rows == before
