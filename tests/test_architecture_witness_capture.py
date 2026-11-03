"""Explicit executed witnesses cannot be replaced by pytest/JUnit success alone."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pdx.situated import architecture_receipts as receipts
from pdx.situated.receipts import digest

pytestmark = pytest.mark.unit
REPO = Path(__file__).resolve().parents[1]


def _run(tmp_path, *, fault="", batch=False):
    source = tmp_path / "mod/decisions/actions.toml"
    source.parent.mkdir(parents=True)
    source.write_text("schema = 1\n", encoding="utf-8")
    generated = tmp_path / "mod/common/generated.txt"
    generated.parent.mkdir(parents=True)
    generated.write_text(
        "strategy = { weight = { value = 1 } other = { value = 2 } }\n", encoding="utf-8"
    )
    tests = tmp_path / "tests/test_business.py"
    tests.parent.mkdir()
    tests.write_text(
        """import pytest
from pathlib import Path

@pytest.fixture(autouse=True)
def lifecycle():
    if FAULT == "setup":
        raise RuntimeError("real setup failure")
    yield
    if FAULT == "teardown":
        raise RuntimeError("real teardown failure")

@pytest.mark.parametrize("responsibility", ["r8.executed", "knowledge.executed"] if BATCH else [None])
@pytest.mark.parametrize(("role", "expected"), [
    ("positive", 1), ("negative", 0), ("unknown", 0),
    ("disabled", 0), ("player", 0), ("native_tail", 0),
])
def test_actual(architecture_witness, request, role, expected, responsibility):
    if FAULT == "empty":
        return
    if FAULT == "xpass":
        request.node.add_marker(pytest.mark.xfail(strict=False))
    if FAULT == "partial" and responsibility == "knowledge.executed" and role != "positive":
        return
    responsibility_args = {"evidence_ids": [responsibility]} if BATCH else {}
    if FAULT == "undeclared":
        responsibility_args = {"evidence_ids": ["unregistered"]}
    if FAULT == "implicit":
        responsibility_args = {}
    consumers = [{"path":"mod/common/generated.txt", "definition":"strategy", "field":"missing" if FAULT == "consumer" else "weight"}]
    if FAULT == "consumer_bundle":
        consumers.append({"path":"mod/common/generated.txt", "definition":"strategy", "field":"other"})
    architecture_witness(
        **responsibility_args,
        case_id=role, role=role, input={"role": role},
        expected={"value": expected},
        reference={"value": -1 if FAULT == "mismatch" else int(role == "positive")},
        generated={"value": len([x for x in [1] if role == "positive"])},
        production=["mod/decisions/actions.toml"],
        consumers=consumers,
    )
    if FAULT == "consumer_constant" or (FAULT == "consumer_partial" and role == "positive"):
        architecture_witness(
            **responsibility_args,
            case_id="other."+role, role=role, input={"role":role,"field":"other"},
            expected={"value":2}, reference={"value":1+1}, generated={"value":sum([1,1])},
            production=["mod/decisions/actions.toml"],
            consumers=[{"path":"mod/common/generated.txt", "definition":"strategy", "field":"other"}],
        )
    if FAULT == "call":
        assert False, "real call failure"
    if FAULT == "skip":
        pytest.skip("real skip")
    if FAULT == "xfail":
        pytest.xfail("real xfail")
    if FAULT == "source":
        Path("mod/decisions/actions.toml").write_text("schema = 2\\n", encoding="utf-8")
    if FAULT == "generated_source":
        Path("mod/common/generated.txt").write_text("strategy = { weight = { value = 99 } }", encoding="utf-8")
    if FAULT == "plan":
        Path("tools/out/plan.json").write_text("{}", encoding="utf-8")
""".replace("FAULT", repr(fault)).replace("BATCH", repr(batch)),
        encoding="utf-8",
        newline="\n",
    )
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    command = [
        sys.executable,
        "-X",
        "utf8",
        "-m",
        "pytest",
        "-o",
        "addopts=",
        "-q",
        "-n0",
        "-p",
        "tools.ci.architecture_witness_capture",
        "--architecture-witness-output=tools/out/capture.json",
        "--architecture-witness-stage=S3",
        "--architecture-witness-requirement=observed_feedback_opportunity_cost",
        "--architecture-witness-id=r8.executed",
        "--architecture-witness-scope=" + "c" * 64,
    ]
    if batch:
        plan = tmp_path / "tools/out/plan.json"
        plan.parent.mkdir(parents=True)
        plan.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "rows": [
                        {
                            "stage_id": "S3",
                            "requirement_id": "observed_feedback_opportunity_cost",
                            "evidence_id": "r8.executed",
                            "scope_hash": "c" * 64,
                            "output": "tools/out/capture.json",
                        },
                        {
                            "stage_id": "S2",
                            "requirement_id": "society_education_knowledge",
                            "evidence_id": "knowledge.executed",
                            "scope_hash": "d" * 64,
                            "output": "tools/out/knowledge.json",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        command = [item for item in command if not item.startswith("--architecture-witness-")]
        command.append("--architecture-witness-plan=tools/out/plan.json")
    result = subprocess.run(
        command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=45, check=False
    )
    path = tmp_path / "tools/out/capture.json"
    assert path.is_file(), result.stdout + result.stderr
    return result, json.loads(path.read_text(encoding="utf-8"))


def test_real_three_phase_results_bind_source_test_and_consumer_ast(tmp_path):
    run, result = _run(tmp_path)
    assert run.returncode == 0, run.stdout + run.stderr
    assert result["status"] == "passed"
    assert len(result["cases"]) == 6
    assert result["source_snapshot_sha256"] == digest(receipts.source_snapshot(tmp_path))
    row = json.loads((tmp_path / "tools/out/capture.row.json").read_text(encoding="utf-8"))
    assert receipts._evidence(tmp_path, "S3", row, result["source_snapshot_sha256"], "c" * 64) == []
    assert not (tmp_path / receipts.RECEIPT_PATH).exists()
    assert all(
        set(case["phases"]) == {"setup", "call", "teardown"}
        and set(case["phases"].values()) == {"passed"}
        for case in result["cases"]
    )


@pytest.mark.parametrize(
    "fault",
    [
        "setup",
        "call",
        "teardown",
        "skip",
        "xfail",
        "xpass",
        "source",
        "generated_source",
        "empty",
        "mismatch",
        "consumer",
        "consumer_bundle",
    ],
)
def test_failed_skipped_xfailed_changed_or_missing_execution_is_never_signed(tmp_path, fault):
    _run_result, result = _run(tmp_path, fault=fault)
    assert result["status"] == "rejected"
    assert result["open_items"]
    assert not (tmp_path / "tools/out/capture.row.json").exists()


def test_one_frozen_execution_has_two_explicit_independent_requirement_rows(tmp_path):
    run, first = _run(tmp_path, batch=True)
    assert run.returncode == 0, run.stdout + run.stderr
    second = json.loads((tmp_path / "tools/out/knowledge.json").read_text(encoding="utf-8"))
    assert first["status"] == second["status"] == "passed"
    assert first["source_snapshot_sha256"] == second["source_snapshot_sha256"]
    assert first["requirement_id"] != second["requirement_id"]
    for name, result in (("capture", first), ("knowledge", second)):
        row = json.loads((tmp_path / f"tools/out/{name}.row.json").read_text(encoding="utf-8"))
        assert len(result["cases"]) == len(row["tests"]) == 6
        assert all(case["nodeid"].endswith(result["evidence_id"] + "]") for case in result["cases"])
        assert (
            receipts._evidence(
                tmp_path,
                result["stage_id"],
                row,
                result["source_snapshot_sha256"],
                result["scope_hash"],
            )
            == []
        )
    assert not (tmp_path / receipts.RECEIPT_PATH).exists()


def test_six_roles_in_one_requirement_never_sign_another_requirements_positive_only(tmp_path):
    run, first = _run(tmp_path, batch=True, fault="partial")
    second = json.loads((tmp_path / "tools/out/knowledge.json").read_text(encoding="utf-8"))
    assert run.returncode != 0
    assert first["status"] == "passed"
    assert second["status"] == "rejected"
    assert len(second["cases"]) == 1
    assert "missing_functional_witness_roles" in second["open_items"]
    assert not (tmp_path / "tools/out/knowledge.row.json").exists()


def test_case_consumers_are_exact_and_six_roles_for_A_never_sign_B(tmp_path):
    run, result = _run(tmp_path, fault="consumer_partial")
    assert run.returncode != 0
    assert result["status"] == "rejected"
    assert len(result["consumers"]) == 2
    assert all("consumers" in case for case in result["cases"])
    assert any(
        item.endswith(":strategy:other") and item.startswith("missing_consumer_witness_roles:")
        for item in result["open_items"]
    )
    assert not (tmp_path / "tools/out/capture.row.json").exists()


def test_other_consumer_output_change_cannot_sign_constant_consumer(tmp_path):
    run, result = _run(tmp_path, fault="consumer_constant")
    assert run.returncode != 0
    assert result["status"] == "rejected"
    assert any(
        item.endswith(":strategy:other") and item.startswith("no_consumer_output_distinction:")
        for item in result["open_items"]
    )
    assert not any(
        item.startswith("missing_consumer_witness_roles:") for item in result["open_items"]
    )
    assert all(len(case["consumers"]) == 1 for case in result["cases"])


@pytest.mark.parametrize("fault", ["implicit", "undeclared", "source", "call", "plan"])
def test_batch_missing_explicit_responsibility_or_failed_run_rejects_all_rows(tmp_path, fault):
    run, first = _run(tmp_path, batch=True, fault=fault)
    second = json.loads((tmp_path / "tools/out/knowledge.json").read_text(encoding="utf-8"))
    assert run.returncode != 0
    assert first["status"] == second["status"] == "rejected"
    assert not (tmp_path / "tools/out/capture.row.json").exists()
    assert not (tmp_path / "tools/out/knowledge.row.json").exists()


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate_id",
        "same_output",
        "row_output_overlap",
        "plan_output_overlap",
        "invalid_requirement",
        "extra_key",
        "empty",
        "traversal",
    ],
)
def test_batch_plan_rejects_ambiguous_or_noncanonical_responsibility(tmp_path, fault):
    from tools.ci.architecture_witness_capture import _plan

    declaration = {
        "stage_id": "S2",
        "requirement_id": "society_education_knowledge",
        "evidence_id": "society.executed",
        "scope_hash": "c" * 64,
        "output": "tools/out/society.json",
    }
    rows = [
        declaration,
        {**declaration, "evidence_id": "second.executed", "output": "tools/out/second.json"},
    ]
    if fault == "duplicate_id":
        rows[1]["evidence_id"] = rows[0]["evidence_id"]
    elif fault == "same_output":
        rows[1]["output"] = rows[0]["output"]
    elif fault == "row_output_overlap":
        rows[1]["output"] = "tools/out/society.row.json"
    elif fault == "plan_output_overlap":
        rows[1]["output"] = "tools/out/plan.json"
    elif fault == "invalid_requirement":
        rows[0]["requirement_id"] = "archive_identity"
    elif fault == "extra_key":
        rows[0]["infer_all_consumers"] = "yes"
    elif fault == "empty":
        rows = []
    elif fault == "traversal":
        rows[0]["output"] = "tools/out/../outside.json"
    path = tmp_path / "tools/out/plan.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema": 1, "rows": rows}), encoding="utf-8")
    with pytest.raises(pytest.UsageError):
        _plan(tmp_path, "tools/out/plan.json")
