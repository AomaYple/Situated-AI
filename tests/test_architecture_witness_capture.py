"""Explicit executed witnesses cannot be replaced by pytest/JUnit success alone."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

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
        Path("tools/out/fixture-plan.json").write_text("{}", encoding="utf-8")
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
        plan = tmp_path.joinpath("tools", "out", "fixture-plan.json")
        plan.parent.mkdir(parents=True, exist_ok=True)
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
        command.append("--architecture-witness-plan=tools/out/fixture-plan.json")
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
        rows[1]["output"] = "tools/out/fixture-plan.json"
    elif fault == "invalid_requirement":
        rows[0]["requirement_id"] = "archive_identity"
    elif fault == "extra_key":
        rows[0]["infer_all_consumers"] = "yes"
    elif fault == "empty":
        rows = []
    elif fault == "traversal":
        rows[0]["output"] = "tools/out/../outside.json"
    isolated_plan = tmp_path.joinpath("tools", "out", "fixture-plan.json")
    isolated_plan.parent.mkdir(parents=True, exist_ok=True)
    isolated_plan.write_text(json.dumps({"schema": 1, "rows": rows}), encoding="utf-8")
    with pytest.raises(pytest.UsageError):
        _plan(tmp_path, "tools/out/fixture-plan.json")


def _current_fixture(tmp_path, monkeypatch):
    """Exercise the real lock/tree orchestration with a tiny native fixture.

    Live installation verification and discovery have independent integration
    coverage; here only their narrow native input is substituted.
    """
    from pdx import config, decisions, distribution
    from tools.ci import architecture_witness_capture as capture

    source = tmp_path / "mod/decisions/actions.toml"
    source.parent.mkdir(parents=True)
    source.write_text("schema = 1\n", encoding="utf-8")
    test = tmp_path / "tests/test_business.py"
    test.parent.mkdir()
    test.write_text("def test_actual(role):\n    pass\n", encoding="utf-8")
    baseline = tmp_path / "research/vanilla-ai/1.15.0/default.txt"
    baseline.parent.mkdir(parents=True)
    baseline.write_text("native = {}\n", encoding="utf-8")
    product = tmp_path / capture._CURRENT_ROOT
    generated = product / "common/generated.txt"
    generated.parent.mkdir(parents=True)
    generated.write_text("strategy = { weight = { value = 1 } }\n", encoding="utf-8")
    native = tmp_path / "installation/game/common/native.txt"
    native.parent.mkdir(parents=True)
    native.write_bytes(b"native = {}\n")
    native_hash = hashlib.sha256(native.read_bytes()).hexdigest()
    native_sources = {"common/native.txt": native_hash}
    scope_hash = digest(native_sources)
    monkeypatch.setattr(config, "REPO", tmp_path)
    monkeypatch.setattr(config, "GAME", native.parents[1])
    monkeypatch.setattr(decisions, "PRODUCT", tmp_path / "mod")
    monkeypatch.setattr(decisions, "_HISTORICAL_PRODUCT", tmp_path / "mod")
    monkeypatch.setattr(decisions, "baseline_path", lambda: baseline)
    calls = []

    def verify_native():
        calls.append("verify_native")
        if hashlib.sha256(native.read_bytes()).hexdigest() != native_hash:
            raise ValueError("native fixture source drift")

    def discover_native():
        calls.append("discover_native")
        verify_native()
        return SimpleNamespace(
            baseline_id="victoria3-1.15.0:fixture",
            scope_hash=scope_hash,
            source_hashes=native_sources,
            discovered_count=1,
        )

    monkeypatch.setattr(distribution, "verify_compatibility_installation", verify_native)
    monkeypatch.setattr(capture.vanilla_inventory, "discover", discover_native)
    built = {"common/generated.txt": generated.read_bytes()}

    def package_inputs(*, include_engineering_metadata=False):
        assert include_engineering_metadata is True
        verify_native()
        return None, None, dict(built)

    monkeypatch.setattr(distribution, "package_inputs", package_inputs)
    monkeypatch.setattr(distribution, "_release_files", lambda files: files)
    lock = product / "generation-lock.json"
    lock.write_text(
        distribution.generation_lock({"common/generated.txt": generated.read_bytes()}),
        encoding="utf-8",
        newline="\n",
    )
    options = {
        "architecture_witness_output": "tools/out/current.json",
        "architecture_witness_stage": "S3",
        "architecture_witness_requirement": "observed_feedback_opportunity_cost",
        "architecture_witness_id": "current.executed",
        "architecture_witness_scope": scope_hash,
        "architecture_witness_profile": "1.15.0",
        "numprocesses": 0,
    }
    cfg = SimpleNamespace(
        rootpath=tmp_path, getoption=lambda name, default=None: options.get(name, default)
    )
    return (
        capture,
        cfg,
        options,
        {"source": source, "generated": generated, "native": native, "lock": lock},
        calls,
    )


def _record_current_roles(state, consumer=None):
    from tools.ci import architecture_witness_capture as capture

    for role in sorted(receipts.WITNESS_ROLES):
        nodeid = f"tests/test_business.py::test_actual[{role}]"
        value = int(role == "positive")
        state.record(
            nodeid,
            case_id=role,
            role=role,
            input={"role": role, "contract_version": "1.15.0"},
            expected={"value": value},
            reference={"value": value},
            generated={"value": value},
            production=["mod/decisions/actions.toml"],
            consumers=[
                {
                    "path": consumer or capture._CURRENT_ROOT + "/common/generated.txt",
                    "definition": "strategy",
                    "field": "weight",
                }
            ],
        )
        for phase in ("setup", "call", "teardown"):
            state.pytest_runtest_logreport(
                SimpleNamespace(nodeid=nodeid, when=phase, outcome="passed")
            )


def test_explicit_current_capture_binds_raw_lock_native_scope_and_true_output_tree(
    tmp_path, monkeypatch
):
    from pdx import version_contracts

    capture, cfg, _options, paths, calls = _current_fixture(tmp_path, monkeypatch)
    with version_contracts.select_version("1.15.0"):
        state = capture.Capture(cfg)
        _record_current_roles(state)
        result = state.pytest_sessionfinish(SimpleNamespace(testscollected=6, exitstatus=0), 0)
    assert result["status"] == "passed"
    assert result["schema"] == 2
    assert result["protocol"] == capture._CURRENT_PROTOCOL
    assert result["contract_version"] == "1.15.0"
    assert result["current_boundary"]["generated_root"] == capture._CURRENT_ROOT
    assert calls.count("discover_native") == 2
    assert (
        result["current_boundary"]["generation_lock"]["sha256"]
        == hashlib.sha256(paths["lock"].read_bytes()).hexdigest()
    )
    row_path = tmp_path / "tools/out/current.current-row.json"
    assert row_path.is_file()
    assert not (tmp_path / "tools/out/current.row.json").exists()
    row = json.loads(row_path.read_bytes())
    assert receipts._evidence(
        tmp_path, "S3", row, result["source_snapshot_sha256"], result["scope_hash"]
    )


@pytest.mark.parametrize(
    "consumer", ["mod/common/generated.txt", "tools/out/arbitrary/common/generated.txt"]
)
def test_current_capture_rejects_old_or_arbitrary_generated_roots(tmp_path, monkeypatch, consumer):
    from pdx import version_contracts

    capture, cfg, _options, _paths, _calls = _current_fixture(tmp_path, monkeypatch)
    with version_contracts.select_version("1.15.0"):
        state = capture.Capture(cfg)
        with pytest.raises(ValueError, match="exact compatibility output root"):
            _record_current_roles(state, consumer)


@pytest.mark.parametrize("fault", ["source", "generated", "lock", "native", "extra_output"])
def test_current_capture_rejects_changed_source_lock_output_or_native_bytes(
    tmp_path, monkeypatch, fault
):
    from pdx import version_contracts

    capture, cfg, _options, paths, _calls = _current_fixture(tmp_path, monkeypatch)
    with version_contracts.select_version("1.15.0"):
        state = capture.Capture(cfg)
        _record_current_roles(state)
        if fault == "extra_output":
            paths["generated"].with_name("unknown.txt").write_bytes(b"unknown={}")
        else:
            paths[fault].write_bytes(paths[fault].read_bytes() + b"\n# drift\n")
        session = SimpleNamespace(testscollected=6, exitstatus=0)
        result = state.pytest_sessionfinish(session, 0)
    assert result["status"] == "rejected"
    assert result["open_items"]
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert not (tmp_path / "tools/out/current.current-row.json").exists()


def test_current_capture_rejects_old_tree_even_with_a_coherently_refreshed_current_lock(
    tmp_path, monkeypatch
):
    from pdx import distribution, version_contracts

    capture, cfg, _options, paths, _calls = _current_fixture(tmp_path, monkeypatch)
    with version_contracts.select_version("1.15.0"):
        paths["generated"].write_bytes(b"strategy = { weight = { value = 99 } }\n")
        paths["lock"].write_text(
            distribution.generation_lock({"common/generated.txt": paths["generated"].read_bytes()}),
            encoding="utf-8",
            newline="\n",
        )
        with pytest.raises(pytest.UsageError, match="freshly built production bytes"):
            capture.Capture(cfg)


@pytest.mark.parametrize("fault", ["scope", "profile", "configured_root"])
def test_current_capture_requires_matching_discovered_scope_and_configured_profile(
    tmp_path, monkeypatch, fault
):
    from pdx import decisions, version_contracts

    capture, cfg, options, _paths, _calls = _current_fixture(tmp_path, monkeypatch)
    if fault == "scope":
        options["architecture_witness_scope"] = "0" * 64
    elif fault == "configured_root":
        monkeypatch.setattr(decisions, "PRODUCT", tmp_path / "other-output")
    with (
        version_contracts.select_version("1.14.5" if fault == "profile" else "1.15.0"),
        pytest.raises(pytest.UsageError, match="current architecture witness boundary"),
    ):
        capture.Capture(cfg)


def test_current_batch_responsibilities_share_one_complete_boundary_check(tmp_path, monkeypatch):
    from pdx import version_contracts

    capture, cfg, options, _paths, calls = _current_fixture(tmp_path, monkeypatch)
    with version_contracts.select_version("1.15.0"):
        boundary = capture._CurrentBoundary(tmp_path)
        first = capture.Capture(cfg, current_boundary=boundary)
        options["architecture_witness_output"] = "tools/out/second.json"
        options["architecture_witness_id"] = "second.executed"
        second = capture.Capture(cfg, current_boundary=boundary)
        for state in (first, second):
            _record_current_roles(state)
            result = state.pytest_sessionfinish(SimpleNamespace(testscollected=6, exitstatus=0), 0)
            assert result["status"] == "passed"
    assert calls.count("discover_native") == 2


@pytest.fixture(autouse=True)
def _historical_1150_contract():
    from pdx import version_contracts

    """Keep the exact archived witness under its original version identity."""
    with version_contracts.select_version("1.15.0"):
        yield
