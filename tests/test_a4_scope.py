"""A4 scope gates reject omissions and stale or self-signed acceptance."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def synthetic_installation() -> dict:
    """Explicit offline identity; no installed game files are read or certified."""
    import json

    from tools.ci import a4_scope

    version = json.loads((ROOT / a4_scope.SNAPSHOT).read_bytes())["版本"]
    return {
        "root": "/synthetic-a4-installation-not-a-live-game",
        "version": [{"key": key, "value": value} for key, value in sorted(version.items())],
        "exe_sha256": "0" * 64,
        "steam_manifest_sha256": "0" * 64,
        "steam_buildid": "synthetic-offline-fixture",
        "jomini_revision": "unknown: synthetic fixture",
        "trees": [{"path": "synthetic/scripts", "count": 0, "sha256": "0" * 64}],
    }


@pytest.fixture(scope="module")
def initial():
    from tools.ci import a4_scope

    return a4_scope.bootstrap(ROOT, frozen_installation=synthetic_installation())


def test_frozen_bootstrap_does_not_read_live_installation(monkeypatch) -> None:
    from tools.ci import a4_scope

    def refuse_live(_root):
        raise AssertionError("offline bootstrap must not inspect a live game")

    monkeypatch.setattr(a4_scope, "installation_identity", refuse_live)
    data = a4_scope.bootstrap(ROOT, frozen_installation=synthetic_installation())
    assert data["freeze"]["installation"]["steam_buildid"] == "synthetic-offline-fixture"
    assert a4_scope.validate(data, ROOT, stage="A4-0")["inventory"] == "pending"


@pytest.mark.integration
def test_live_installation_identity_is_separate_integration() -> None:
    from tools.ci import a4_scope

    data = a4_scope.bootstrap(ROOT)
    assert (
        a4_scope.validate(data, ROOT, stage="A4-0", check_installation=True)["inventory"]
        == "pending"
    )


def test_stage_zero_accepts_future_pending_but_plan_gate_rejects(initial) -> None:
    from tools.ci import a4_scope

    assert a4_scope.validate(initial, ROOT, stage="A4-0")["future_pending"] > 0
    with pytest.raises(ValueError, match="nonterminal"):
        a4_scope.validate(initial, ROOT, stage="all")


@pytest.mark.parametrize("field", ["discoveries", "rows", "migrations", "candidate_changes"])
def test_independent_sources_reject_deleted_denominator(initial, field: str) -> None:
    from tools.ci import a4_scope

    data = copy.deepcopy(initial)
    data[field].pop()
    with pytest.raises(ValueError, match=r"coverage|mapping"):
        a4_scope.validate(data, ROOT, stage="A4-0")


def test_duplicate_rows_are_rejected(initial) -> None:
    from tools.ci import a4_scope

    data = copy.deepcopy(initial)
    data["rows"].append(copy.deepcopy(data["rows"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        a4_scope.validate(data, ROOT, stage="A4-0")


@pytest.mark.parametrize("dependency", ["missing-id", "self"])
def test_dangling_and_cyclic_dependencies_are_rejected(initial, dependency: str) -> None:
    from tools.ci import a4_scope

    data = copy.deepcopy(initial)
    row = data["rows"][0]
    row["dependency_ids"] = [row["id"] if dependency == "self" else dependency]
    with pytest.raises(ValueError, match=r"dangling|cycle"):
        a4_scope.validate(data, ROOT, stage="A4-0")


@pytest.mark.parametrize("disposition", ["retain_native", "unsupported", "implement"])
def test_text_only_terminal_claims_are_rejected(initial, disposition: str) -> None:
    from tools.ci import a4_scope

    data = copy.deepcopy(initial)
    row = data["rows"][0]
    row.update(
        disposition=disposition, obligation_status="retained", interface_status="unsupported"
    )
    if disposition == "implement":
        row.update(obligation_status="verified", interface_status="verified")
    elif disposition == "retain_native":
        row["interface_status"] = "native_handled"
    with pytest.raises(ValueError, match=r"evidence|writer|witness"):
        a4_scope.validate(data, ROOT, stage="A4-0")


def test_stale_input_is_rejected_even_in_future_phase(initial) -> None:
    from tools.ci import a4_scope

    data = copy.deepcopy(initial)
    data["freeze"]["inputs"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match=r"hash|identity"):
        a4_scope.validate(data, ROOT, stage="A4-0")


@pytest.mark.parametrize("path", ["../secret", "C:/secret", "/secret", "a\\b"])
def test_paths_cannot_escape_repository(path: str) -> None:
    from tools.ci import a4_scope

    with pytest.raises(ValueError, match="path"):
        a4_scope.safe_path(ROOT, path)


def test_legacy_states_are_not_inherited(initial) -> None:
    assert len(initial["migrations"]) == 96
    assert {row["obligation_status"] for row in initial["rows"]} == {"pending"}
    assert all(item["reason"] and item["old_id"] for item in initial["migrations"])


@pytest.fixture
def terminal(initial):
    from tools.ci import a4_schema, a4_scope

    row = copy.deepcopy(initial["rows"][0])
    row.update(
        disposition="retain_native", interface_status="native_handled", obligation_status="retained"
    )
    for key, schema in a4_schema.ROW.items():
        if schema == a4_schema.VALUE:
            row[key] = {
                "status": "applicable",
                "reason": "fixture boundary",
                "value": "specific_consumer",
            }
    for coverage in row["applicability"].values():
        coverage.update(status="applicable", reason="fixture case", case_ids=["case-1"])
    row["case_ids"] = ["case-1"]
    row["configurations"] = [
        {"id": "base", "dlc_ids": [], "enabled": True, "case_ids": ["case-1"]},
        {"id": "disabled", "dlc_ids": [], "enabled": False, "case_ids": ["case-1"]},
        {"id": "dlc", "dlc_ids": ["dlc-a"], "enabled": True, "case_ids": ["case-1"]},
    ]
    source = a4_scope.Sources(ROOT)
    row["evidence_hashes"] = [source.reference("tools/ci/a4_scope.py", "validate", "python")]
    row["boundary_evidence"] = [source.reference("tools/ci/a4_scope.py", "validate", "python")]
    native = source.reference(
        a4_scope.SNAPSHOT, "域/ai_surface/cards~1ai_strategy_agricultural_expansion", "json"
    )
    row["boundary_proofs"] = [
        {"role": role, "reference": native}
        for role in ("native_source", "parent_structure", "reference_closure", "disabled_path")
    ]
    row["witness_paths"] = ["tests/test_a4_scope.py"]
    row["witnesses"] = [
        {
            "node_id": "tests/test_a4_scope.py::test_paths_cannot_escape_repository[../secret]",
            "case_ids": ["case-1"],
            "receipt_id": "run-1",
        }
    ]
    return row


@pytest.mark.parametrize(
    "dimension", ["dlc", "disabled", "unknown", "object", "role", "threshold", "lifecycle", "U07"]
)
def test_terminal_missing_applicable_dimension_is_rejected(terminal, dimension: str) -> None:
    from tools.ci import a4_scope

    terminal["applicability"][dimension]["status"] = "pending"
    with pytest.raises(ValueError, match="applicability"):
        a4_scope.terminal_evidence(terminal, a4_scope.Sources(ROOT), {}, ["dlc-a"])


@pytest.mark.parametrize("configuration", ["disabled", "dlc"])
def test_terminal_missing_concrete_configuration_is_rejected(terminal, configuration: str) -> None:
    from tools.ci import a4_scope

    terminal["configurations"] = [
        item for item in terminal["configurations"] if item["id"] != configuration
    ]
    with pytest.raises(ValueError, match="configuration"):
        a4_scope.terminal_evidence(terminal, a4_scope.Sources(ROOT), {}, ["dlc-a"])


def test_unwired_implement_is_rejected(terminal) -> None:
    from tools.ci import a4_scope

    terminal.update(
        disposition="implement", interface_status="verified", obligation_status="verified"
    )
    with pytest.raises(ValueError, match="unwired writer"):
        a4_scope.terminal_evidence(terminal, a4_scope.Sources(ROOT), {}, ["dlc-a"])


def test_receipt_rejects_failed_and_forged_passed(tmp_path) -> None:
    import json

    from tools.ci import a4_scope

    root = tmp_path
    (root / "tests").mkdir()
    (root / "tests/test_witness.py").write_text(
        "def test_actual():\n    assert False\n", encoding="utf8"
    )
    sources = a4_scope.Sources(root)
    reference = sources.reference("tests/test_witness.py", "test_actual", "python")
    junit = root / "junit.xml"
    junit.write_text(
        '<testsuites><testsuite><testcase classname="tests.test_witness" name="test_actual"><failure/></testcase></testsuite></testsuites>',
        encoding="utf8",
    )
    receipt = {
        "schema": 1,
        "id": "run-1",
        "command": [str(a4_scope.interpreter(root))],
        "selection": ["tests/test_witness.py::test_actual"],
        "exit_code": 0,
        "junit": sources.reference("junit.xml"),
        "bindings": [reference],
        "passed": ["tests/test_witness.py::test_actual"],
        "failed": [],
    }
    (root / "receipt.json").write_text(json.dumps(receipt), encoding="utf8")
    stub = {
        "id": "run-1",
        "path": "receipt.json",
        "sha256": a4_scope.sha((root / "receipt.json").read_bytes()),
    }
    with pytest.raises(ValueError, match="failed JUnit"):
        a4_scope.verify_receipt(sources, stub, [reference], ["tests/test_witness.py::test_actual"])


def test_real_witness_run_is_bound_and_replayed() -> None:
    import json
    import tempfile

    from tools.ci import a4_scope

    sources = a4_scope.Sources(ROOT)
    node = "tests/test_a4_scope.py::test_paths_cannot_escape_repository[../secret]"
    refs = [a4_scope.witness_reference(sources, node), sources.reference("tools/ci/a4_scope.py")]
    output_root = ROOT / "tools/out/a4-scope-tests"
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output_root) as directory:
        output = Path(directory)
        receipt = a4_scope.run_tests(ROOT, [node], refs, output)
        assert receipt["exit_code"] == 0
        assert receipt["passed"] == [node]
        path = output / "receipt.json"
        path.write_text(json.dumps(receipt), encoding="utf8")
        stub = {
            "id": receipt["id"],
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": a4_scope.sha(path.read_bytes()),
        }
        a4_scope.verify_receipt(a4_scope.Sources(ROOT), stub, refs, [node])


def test_pending_dependency_blocks_signed_row(initial) -> None:
    from tools.ci import a4_scope

    data = copy.deepcopy(initial)
    data["rows"][0]["dependency_ids"] = [data["rows"][1]["id"]]
    with pytest.raises(ValueError, match="nonterminal"):
        a4_scope.validate(data, ROOT, stage="A4-1")


def test_raw_a3_row_identity_preserves_original_bytes() -> None:
    import gzip
    import re

    from tools.ci import a4_scope

    sources = a4_scope.Sources(ROOT)
    original, _ = a4_scope.original_a3(sources)
    raw = gzip.decompress(sources.read(original["path"]))
    first = re.split(rb"(?m)(?=^\[\[obligations\]\])", raw)[1]
    assert a4_scope.original_row_hashes(sources, original)["B05.5.7"] == a4_scope.sha(first)


def test_independent_investigation_rejects_deleted_discovery(initial) -> None:
    import json
    import tempfile

    from tools.ci import a4_scope

    data = copy.deepcopy(initial)
    output_root = ROOT / "tools/out/a4-scope-tests"
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output_root) as directory:
        path = Path(directory) / "independent.json"
        extra = copy.deepcopy(data["discoveries"][0])
        extra.update(
            id="D:investigation:additional-consumer",
            origin="investigation",
            identity="additional-consumer",
        )
        report = {
            "schema": 1,
            "source_version": "1.15.0",
            "source_inputs": [extra["source"]],
            "scanned_directories": ["game/common"],
            "parse_failures": [],
            "unrecognized": [],
            "duplicates": [],
            "discoveries": [extra],
            "dlc_ids": [],
            "writer_ids": [],
            "consumer_ids": ["additional-consumer"],
            "crosscheck_receipt_ids": [],
        }
        path.write_text(json.dumps(report), encoding="utf8")
        data["inventory"]["investigation_sources"] = [
            a4_scope.Sources(ROOT).reference(path.relative_to(ROOT).as_posix())
        ]
        with pytest.raises(ValueError, match="independent discovery source coverage"):
            a4_scope.validate(data, ROOT, stage="A4-0")


def test_independent_index_cannot_be_removed_from_ledger(tmp_path) -> None:
    import json

    from tools.ci import a4_scope

    index = tmp_path / a4_scope.DISCOVERY_INDEX
    index.parent.mkdir(parents=True)
    report = tmp_path / "report.json"
    report.write_text("{}\n", encoding="utf8")
    source = a4_scope.Sources(tmp_path)
    ref = source.reference("report.json")
    index.write_text(
        json.dumps({"schema": 1, "plan": "A4", "investigations": [ref]}), encoding="utf8"
    )
    with pytest.raises(ValueError, match="independent discovery source coverage"):
        a4_scope.investigation_references(source, [])


def test_terminal_retain_requires_precise_boundary_not_file_only(terminal) -> None:
    from tools.ci import a4_scope

    terminal["boundary_evidence"] = terminal["input_hashes"]
    with pytest.raises(ValueError, match="exact boundary"):
        a4_scope.terminal_evidence(terminal, a4_scope.Sources(ROOT), {}, ["dlc-a"])


def test_terminal_validates_real_run_not_just_passed_claim(terminal, initial) -> None:
    import json
    import tempfile

    from tools.ci import a4_scope

    sources = a4_scope.Sources(ROOT)
    node = terminal["witnesses"][0]["node_id"]
    refs = [
        *terminal["input_hashes"],
        *terminal["evidence_hashes"],
        *terminal["boundary_evidence"],
        *(proof["reference"] for proof in terminal["boundary_proofs"]),
        a4_scope.witness_reference(sources, node),
    ]
    refs = list({json.dumps(ref, sort_keys=True): ref for ref in refs}.values())
    output_root = ROOT / "tools/out/a4-scope-tests"
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output_root) as directory:
        output = Path(directory)
        receipt = a4_scope.run_tests(ROOT, [node], refs, output)
        terminal["witnesses"][0]["receipt_id"] = receipt["id"]
        path = output / "receipt.json"
        path.write_text(json.dumps(receipt), encoding="utf8")
        stub = {
            "id": receipt["id"],
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": a4_scope.sha(path.read_bytes()),
        }
        a4_scope.terminal_evidence(
            terminal, a4_scope.Sources(ROOT), {receipt["id"]: stub}, ["dlc-a"]
        )
        data = copy.deepcopy(initial)
        data["rows"][0] = terminal
        terminal["dependency_ids"] = [data["rows"][1]["id"]]
        data["receipts"] = [stub]
        with pytest.raises(ValueError, match="unclosed dependency"):
            a4_scope.validate(data, ROOT, stage="A4-0")


def test_receipt_live_replay_rejects_forged_green(tmp_path) -> None:
    import json
    import tempfile

    from tools.ci import a4_scope

    # A controlled failing test is an input to the real runner, never a product witness.
    output_root = ROOT / "tools/out/a4-scope-tests"
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output_root) as directory:
        output = Path(directory)
        root = tmp_path
        (root / "tests").mkdir()
        (root / "tests/test_fail.py").write_text(
            "def test_fails():\n    assert False\n", encoding="utf8"
        )
        # Missing repository .venv uses the active test interpreter, including CI setup-python.
        temporary_output = root / "tools/out/witness"
        fallback = a4_scope.run_tests(
            root, ["tests/test_fail.py::test_fails"], [], temporary_output
        )
        assert fallback["exit_code"] == 1
        assert fallback["failed"] == ["tests/test_fail.py::test_fails"]
        # Real failure in the project interpreter, preserved in the receipt.
        fixture = ROOT / "tests/test_a4_failure_fixture.py"
        assert not fixture.exists()
        try:
            fixture.write_text(
                "def test_fails():\n    assert False\n", encoding="utf8", newline="\n"
            )
            node = "tests/test_a4_failure_fixture.py::test_fails"
            refs = [a4_scope.witness_reference(a4_scope.Sources(ROOT), node)]
            receipt = a4_scope.run_tests(ROOT, [node], refs, output)
            assert receipt["exit_code"] == 1
            assert receipt["failed"] == [node]
            receipt.update(exit_code=0, passed=[node], failed=[])
            junit = output / "junit.xml"
            junit.write_text(
                '<testsuites><testsuite><testcase classname="tests.test_a4_failure_fixture" name="test_fails"/></testsuite></testsuites>',
                encoding="utf8",
            )
            receipt["junit"]["sha256"] = a4_scope.sha(junit.read_bytes())
            path = output / "receipt.json"
            path.write_text(json.dumps(receipt), encoding="utf8")
            stub = {
                "id": receipt["id"],
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": a4_scope.sha(path.read_bytes()),
            }
            with pytest.raises(ValueError, match="failed live witness replay"):
                a4_scope.verify_receipt(a4_scope.Sources(ROOT), stub, refs, [node])
        finally:
            fixture.unlink(missing_ok=True)


def test_schema_rejects_unknown_fields_and_legacy_complete(initial) -> None:
    from tools.ci import a4_scope

    data = copy.deepcopy(initial)
    data["rows"][0]["complete"] = True
    with pytest.raises(ValueError, match="schema fields"):
        a4_scope.validate(data, ROOT, stage="A4-0")


def test_fact_and_port_ids_require_actual_source_registry(initial) -> None:
    from tools.ci import a4_scope

    data = copy.deepcopy(initial)
    data["rows"][0]["fact_ids"] = ["invented-fact"]
    with pytest.raises(ValueError, match="dangling facts"):
        a4_scope.validate(data, ROOT, stage="A4-0")


def test_shared_run_replays_once_per_gate() -> None:
    import json
    import tempfile

    from tools.ci import a4_scope

    sources = a4_scope.Sources(ROOT)
    nodes = [
        "tests/test_a4_scope.py::test_paths_cannot_escape_repository[../secret]",
        "tests/test_a4_scope.py::test_paths_cannot_escape_repository[C:/secret]",
    ]
    refs = [a4_scope.witness_reference(sources, node) for node in nodes]
    output_root = ROOT / "tools/out/a4-scope-tests"
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output_root) as directory:
        output = Path(directory)
        receipt = a4_scope.run_tests(ROOT, nodes, refs, output)
        path = output / "receipt.json"
        path.write_text(json.dumps(receipt), encoding="utf8")
        stub = {
            "id": receipt["id"],
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": a4_scope.sha(path.read_bytes()),
        }
        a4_scope.verify_receipt(sources, stub, [refs[0]], [nodes[0]])
        assert len(sources.replayed) == 1
        a4_scope.verify_receipt(sources, stub, [refs[1]], [nodes[1]])
        assert len(sources.replayed) == 1


def test_inventory_maps_future_expansion_without_signing_it(initial) -> None:
    from tools.ci import a4_scope

    future = copy.deepcopy(initial["rows"][0])
    future.update(stage="A4-3", domain="new-future-consumer")
    report = {"consumer_ids": ["new-future-consumer"], "writer_ids": ["new-future-consumer"]}
    a4_scope.inventory_mappings({future["id"]: future}, [report], "A4-1")
    with pytest.raises(ValueError, match="nonterminal consumer"):
        a4_scope.inventory_mappings({future["id"]: future}, [report], "A4-7")
    future["stage"] = "A4-8"
    with pytest.raises(ValueError, match="nonterminal consumer"):
        a4_scope.inventory_mappings({future["id"]: future}, [report], "A4-7")
    future["stage"] = "A4-1"
    with pytest.raises(ValueError, match="nonterminal consumer"):
        a4_scope.inventory_mappings({future["id"]: future}, [report], "A4-1")


@pytest.mark.parametrize("stage", ["A4-8", "all"])
def test_external_delivery_cannot_pass_without_implemented_verifier(stage: str) -> None:
    from tools.ci import a4_scope

    with pytest.raises(ValueError, match="external delivery verification is not implemented"):
        a4_scope.delivery_gate(stage)
    a4_scope.delivery_gate("A4-7")


def test_product_obligation_cannot_move_to_delivery_stage(initial) -> None:
    from tools.ci import a4_scope

    data = copy.deepcopy(initial)
    data["rows"][0]["stage"] = "A4-8"
    with pytest.raises(ValueError, match=r"schema enum.*stage"):
        a4_scope.validate(data, ROOT, stage="A4-7")


def test_missing_venv_uses_actual_interpreter_and_verifies_command(tmp_path) -> None:
    import json
    import sys

    from tools.ci import a4_scope

    root = tmp_path
    (root / "tests").mkdir()
    (root / "tests/test_controlled.py").write_text(
        "def test_real():\n    assert 3 * 7 == 21\n", encoding="utf8"
    )
    sources = a4_scope.Sources(root)
    node = "tests/test_controlled.py::test_real"
    refs = [a4_scope.witness_reference(sources, node)]
    output = root / "tools/out/witness"
    receipt = a4_scope.run_tests(root, [node], refs, output)
    assert not (root / ".venv").exists()
    assert Path(receipt["command"][0]).resolve() == Path(sys.executable).resolve()
    path = output / "receipt.json"
    path.write_text(json.dumps(receipt), encoding="utf8")
    stub = {
        "id": receipt["id"],
        "path": path.relative_to(root).as_posix(),
        "sha256": a4_scope.sha(path.read_bytes()),
    }
    a4_scope.verify_receipt(a4_scope.Sources(root), stub, refs, [node])
    receipt["command"][0] = "untrusted-python"
    path.write_text(json.dumps(receipt), encoding="utf8")
    stub["sha256"] = a4_scope.sha(path.read_bytes())
    with pytest.raises(ValueError, match="receipt interpreter"):
        a4_scope.verify_receipt(a4_scope.Sources(root), stub, refs, [node])
