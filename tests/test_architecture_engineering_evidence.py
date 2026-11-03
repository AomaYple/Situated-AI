"""Capture actual S5 engineering and later S6 delivery observations after pytest.

SITAI_ENGINEERING_EVIDENCE_INPUT points to a root-produced JSON manifest below
tools/out. This module never runs a recursive suite, builds, publishes or deploys.
Missing input is an explicit artifact skip, never a successful receipt.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from pdx import config, covgate, distribution
from pdx.situated import architecture_receipts as receipts
from tools.ci import python_package, test_suite, test_summary

# mem_baseline includes historical probes outside the package type contract;
# use its existing runtime API exactly as the actual suite runner does.
mem_baseline = importlib.import_module("tools.ci.mem_baseline")

ROOT = config.REPO.resolve()
TEST_FILE = "tests/test_architecture_engineering_evidence.py"
S5 = ("full_regression_resources", "quality_hygiene_package")
S6 = ("merged_ci", "tag_release_zip_sha", "workshop_copy", "deployment_rollback_cleanup")
QUALITY = frozenset(
    {
        "encoding",
        "hygiene",
        "lint",
        "format",
        "types",
        "baseline",
        "deadcode",
        "python_package",
        "package",
    }
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _ref(path: Path) -> dict[str, str]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": _sha(path.read_bytes())}


class EngineeringCapture:
    """Publish a complete selected responsibility group only after final phases."""

    def __init__(self, manifest: Path, data: dict[str, Any], selected: set[str]):
        self.data = data
        self.snapshot = receipts.source_snapshot(ROOT)
        assert data["schema"] == 1
        assert data["source_snapshot"] == self.snapshot
        assert re.fullmatch(r"[a-f0-9]{64}", data["scope_hash"])
        self.output = receipts._path(ROOT, data["output_dir"])
        assert self.output.is_relative_to(ROOT / "tools/out")
        assert self.output != ROOT / "tools/out"
        self.output.mkdir(parents=True, exist_ok=True)
        self.phases: dict[str, dict[str, str]] = {}
        self.cases: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.artifacts: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
        self.manifest = manifest
        self.input_ref = _ref(manifest)
        self.delivery_checked = False
        # A later S6 capture must preserve the already validated S5 rows.
        active = {
            name
            for group, section in ((S5, "full_acceptance"), (S6, "delivery"))
            if section in data and selected.intersection(group)
            for name in group
        }
        for requirement in active:
            (self.output / f"{requirement}.row.json").unlink(missing_ok=True)

    def artifact(self, requirement: str, ref: dict[str, str]) -> Path:
        path = receipts._artifact(ROOT, ref)
        self.artifacts[requirement][ref["path"]] = dict(ref)
        return path

    def record(
        self,
        requirement: str,
        request: pytest.FixtureRequest,
        input_: dict[str, Any],
        expected: object,
        reference: object,
        observed: object,
    ) -> None:
        assert receipts.digest(expected) == receipts.digest(reference)
        assert receipts.digest(expected) == receipts.digest(observed)
        self.artifact(requirement, self.input_ref)
        self.cases[requirement].append(
            {
                "case_id": "actual." + requirement,
                "nodeid": request.node.nodeid,
                "expected_origin": "independent",
                "input": input_,
                "expected": expected,
                "reference": reference,
                "observed": observed,
            }
        )

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.nodeid.startswith(TEST_FILE + "::"):
            outcome = "xfail" if hasattr(report, "wasxfail") else report.outcome
            self.phases.setdefault(report.nodeid, {})[report.when] = outcome

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int):
        yield
        issues = []
        selected = set(self.cases)
        groups = [group for group in (S5, S6) if selected.intersection(group)]
        required = {name for group in groups for name in group}
        if not groups or selected != required:
            issues.append("complete_selected_responsibility_group_required")
        if exitstatus != 0 or session.exitstatus != 0:
            issues.append(f"pytest_exit_code:{int(session.exitstatus)}")
        if receipts.source_snapshot(ROOT) != self.snapshot:
            issues.append("source_changed_during_session")
        nodeids = {f"{TEST_FILE}::test_{'s5' if name in S5 else 's6'}_{name}" for name in required}
        issues.extend(
            "nonpassing_or_incomplete_phases:" + nodeid
            for nodeid in nodeids
            if self.phases.get(nodeid)
            != {"setup": "passed", "call": "passed", "teardown": "passed"}
        )
        for refs in self.artifacts.values():
            for ref in refs.values():
                try:
                    receipts._artifact(ROOT, ref)
                except (ValueError, OSError) as exc:
                    issues.append(str(exc))
        _write(
            self.output / "execution.json",
            {
                "exit_code": int(session.exitstatus),
                "phases": self.phases,
                "issues": issues,
                "source_snapshot": self.snapshot,
            },
        )
        for name in required:
            (self.output / f"{name}.row.json").unlink(missing_ok=True)
        if issues:
            if session.exitstatus == 0:
                session.exitstatus = pytest.ExitCode.TESTS_FAILED
            return
        rows = []
        for requirement in sorted(required):
            stage = "S5" if requirement in S5 else "S6"
            kind = receipts._evidence_kind(stage, requirement)
            artifacts = list(self.artifacts[requirement].values())
            cases = [
                {**case, "outcome": "passed", "phases": self.phases[case["nodeid"]]}
                for case in self.cases[requirement]
            ]
            result = {
                "schema": 1,
                "plan_version": "A2",
                "stage_id": stage,
                "requirement_id": requirement,
                "evidence_id": f"a2.{stage.lower()}.{requirement}",
                "source_snapshot_sha256": receipts.digest(self.snapshot),
                "scope_hash": self.data["scope_hash"],
                "evidence_category": "static_check",
                "evidence_kind": kind,
                "status": "passed",
                "artifacts": artifacts,
                "cases": cases,
                "open_items": [],
            }
            if requirement == "full_regression_resources":
                result["full_acceptance"] = self.data["full_acceptance"]["report"]
            result_path = self.output / f"{requirement}.json"
            _write(result_path, result)
            row = {
                "requirement_id": requirement,
                "evidence_id": result["evidence_id"],
                "direction": receipts.REQUIREMENT_DIRECTIONS[stage, requirement],
                "oracle": "independent",
                "evidence_kind": kind,
                "artifacts": artifacts,
                "tests": [
                    {"nodeid": case["nodeid"], "sha256": _sha((ROOT / TEST_FILE).read_bytes())}
                    for case in cases
                ],
                "result": _ref(result_path),
            }
            issues.extend(
                receipts._evidence(
                    ROOT, stage, row, receipts.digest(self.snapshot), self.data["scope_hash"]
                )
            )
            rows.append((requirement, row))
        if issues:
            _write(self.output / "rejection.json", {"issues": issues})
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
            return
        for requirement, row in rows:
            _write(self.output / f"{requirement}.row.json", row)


@pytest.fixture(scope="module")
def engineering_capture(request: pytest.FixtureRequest) -> EngineeringCapture:
    name = os.environ.get("SITAI_ENGINEERING_EVIDENCE_INPUT")
    if not name:
        pytest.skip("需要工程验收产物：设置 SITAI_ENGINEERING_EVIDENCE_INPUT")
    manifest = receipts._path(ROOT, name)
    assert manifest.is_relative_to(ROOT / "tools/out")
    if request.config.getoption("numprocesses", default=0) not in (0, None):
        raise pytest.UsageError("engineering/delivery evidence capture requires -n0")
    selected = {
        name
        for name in (*S5, *S6)
        if any(
            item.nodeid == f"{TEST_FILE}::test_{'s5' if name in S5 else 's6'}_{name}"
            for item in request.session.items
        )
    }
    capture = EngineeringCapture(manifest, receipts._json(manifest), selected)
    request.config.pluginmanager.register(capture, "architecture-engineering-local-capture")
    return capture


def _execution(capture: EngineeringCapture, requirement: str, command: dict[str, Any]) -> None:
    assert type(command["exit_code"]) is int
    assert command["exit_code"] == 0
    assert command["cwd"] == "."
    assert command["source_before"] == capture.snapshot
    assert command["source_after"] == capture.snapshot
    start, finish = (datetime.fromisoformat(command[key]) for key in ("started_at", "finished_at"))
    assert start.utcoffset() is not None
    assert finish.utcoffset() is not None
    assert finish > start
    argv = command["argv"]
    assert isinstance(argv, list)
    assert argv
    assert all(isinstance(arg, str) and arg for arg in argv)
    identity = command["id"]
    if identity in {"encoding", "hygiene", "lint", "format", "types", "baseline", "deadcode"}:
        assert "tools/ci/run_check.py" in [arg.replace("\\", "/") for arg in argv]
        assert identity in argv
        if identity == "format":
            assert "--check" in argv
    elif identity == "python_package":
        assert "tools/ci/python_package.py" in [arg.replace("\\", "/") for arg in argv]
    elif identity == "package":
        assert "package" in argv or "pdx.distribution" in argv
    elif identity == "full_acceptance":
        assert "full-acceptance" in argv or "tools.ci.test_suite" in argv
    for stream in ("stdout", "stderr"):
        capture.artifact(requirement, command[stream])


def _full_inputs(capture: EngineeringCapture):
    if "full_acceptance" not in capture.data:
        pytest.skip("需要工程验收产物：full_acceptance")
    requirement = "full_regression_resources"
    declaration = capture.data["full_acceptance"]
    _execution(capture, requirement, declaration["command"])
    assert declaration["command"]["id"] == "full_acceptance"
    path = capture.artifact(requirement, declaration["report"])
    full = receipts._json(path)
    out = Path(full["output"]).resolve()
    assert out == path.parent
    assert out.is_relative_to(ROOT / "tools/out")
    names = (
        "collection.json",
        "junit.xml",
        "coverage.json",
        "resource-summary.json",
        "invocation.json",
        "test-summary.json",
        "pytest.log",
        "samples.csv",
        "procs.csv",
    )
    for name in names:
        raw = out / name
        assert raw.is_file()
        assert raw.stat().st_size > 0
        capture.artifact(requirement, _ref(raw))
    samples = tuple(out.glob("inproc-full-*.json"))
    assert samples
    for sample in samples:
        capture.artifact(requirement, _ref(sample))
    return full, out


def test_s5_full_regression_resources(
    engineering_capture: EngineeringCapture, request: pytest.FixtureRequest
) -> None:
    capture = engineering_capture
    full, out = _full_inputs(capture)
    receipts._full_acceptance(full)
    assert full["ok"] is True
    assert full["exit_code"] == 0
    assert full["errors"] == []
    assert full["coverage"]["branch"] is True
    assert all(verdict["ok"] is True for verdict in full["verdict"])
    group = full["groups"][0]
    collection = receipts._json(out / "collection.json")
    assert full["collection"] == collection
    raw_summary = receipts._json(out / "resource-summary.json")
    # finalize adds actual worker classification to the in-memory group after
    # resource-summary.json was written. Every original measured field stays.
    assert all(group[key] == value for key, value in raw_summary.items() if key != "group")
    assert group["group"] == ("serial" if group["n_workers"] == 0 else "xdist")
    assert test_summary.summarize(out / "junit.xml") == full["tests"]
    assert receipts._json(out / "test-summary.json") == full["tests"]
    expected_nodes = Counter(collection["nodeids"])
    assert all(count == 1 for count in expected_nodes.values())
    assert collection["exitstatus"] == 0
    assert collection["counts"] == dict(expected_nodes)
    assert collection["started_counts"] == dict(expected_nodes)
    assert collection["finished_counts"] == dict(expected_nodes)
    assert collection["sha256"] == _sha(json.dumps(dict(expected_nodes), sort_keys=True).encode())
    reports = collection["reports"]
    assert not any(row["outcome"] == "failed" for row in reports)
    for phase in ("setup", "teardown"):
        assert Counter(row["nodeid"] for row in reports if row["when"] == phase) == expected_nodes
    calls = Counter(
        row["nodeid"] for row in reports if row["when"] == "call" and not row["subtest"]
    )
    skipped = Counter(
        row["nodeid"] for row in reports if row["when"] == "setup" and row["outcome"] == "skipped"
    )
    assert calls + skipped == expected_nodes
    effective = collection["effective"]
    assert effective["repeat"] == 1
    assert effective["dist"] != "each"
    assert len(collection["workers"]) == group["n_workers"] == effective["numprocesses"]
    assert group["worker_selection_effective"] == effective
    invocation = receipts._json(out / "invocation.json")
    for key in ("argv", "cwd", "config_sha256", "environment_sha256", "versions"):
        assert invocation[key] == group[key]
    assert Path(group["cwd"]).resolve() == ROOT
    for name, sha in group["config_sha256"].items():
        assert _sha(receipts._path(ROOT, name).read_bytes()) == sha
    resources = test_suite._resource_evidence(out, group)
    assert receipts.digest(resources) == receipts.digest(full["resources"])
    budget = {
        **group,
        "per_worker_peak_mb": max(group["per_worker_peak_mb"], resources["execution_peak_mb"]),
    }
    assert full["verdict"] == [mem_baseline.judge(budget)]
    coverage_path = out / "coverage.json"
    coverage = receipts._json(coverage_path)
    coverage_rows = covgate.load_coverage(coverage_path)
    assert coverage["meta"]["branch_coverage"] is True
    assert full["coverage"] == {
        "percent": float(coverage["totals"]["percent_covered"]),
        "floor": covgate.overall_floor(),
        "failed_modules": [row.module for row in covgate.check(coverage_rows)],
        "missing_modules": covgate.missing_floors(coverage_rows),
        "branch": True,
    }
    expected = {
        "complete_collection_execution": True,
        "zero_failures_errors": True,
        "branch_and_module_coverage": True,
        "dual_rss_and_budget": True,
        "current_config": True,
    }
    capture.record(
        "full_regression_resources",
        request,
        {
            "report": capture.data["full_acceptance"]["report"],
            "nodeids_sha256": collection["sha256"],
            "tests": full["tests"]["tests"],
            "workers": group["n_workers"],
        },
        expected,
        {
            "complete_collection_execution": Counter(collection["started"])
            == expected_nodes
            == Counter(collection["finished"]),
            "zero_failures_errors": full["ok"] and not full["errors"],
            "branch_and_module_coverage": full["coverage"]["percent"] >= full["coverage"]["floor"]
            and not covgate.check(coverage_rows),
            "dual_rss_and_budget": full["verdict"][0]["ok"],
            "current_config": invocation["config_sha256"] == group["config_sha256"],
        },
        {
            "complete_collection_execution": calls + skipped == expected_nodes,
            "zero_failures_errors": full["tests"]["errors"] == full["tests"]["failures"] == 0,
            "branch_and_module_coverage": coverage["meta"]["branch_coverage"]
            and not covgate.missing_floors(coverage_rows),
            "dual_rss_and_budget": mem_baseline.judge(budget)["ok"],
            "current_config": all(
                _sha((ROOT / name).read_bytes()) == sha
                for name, sha in group["config_sha256"].items()
            ),
        },
    )


def test_s5_quality_hygiene_package(
    engineering_capture: EngineeringCapture, request: pytest.FixtureRequest
) -> None:
    capture = engineering_capture
    if "quality" not in capture.data:
        pytest.skip("需要工程验收产物：quality")
    requirement = "quality_hygiene_package"
    quality = capture.data["quality"]
    commands = quality["commands"]
    ids = [command["id"] for command in commands]
    assert len(ids) == len(set(ids))
    assert set(ids) >= QUALITY
    for command in commands:
        _execution(capture, requirement, command)
    package = capture.artifact(requirement, quality["package"]["zip"])
    checksum = capture.artifact(requirement, quality["package"]["sha256_file"])
    assert checksum.read_text(encoding="utf-8").strip().split() == [
        _sha(package.read_bytes()),
        package.name,
    ]
    manifest = distribution.validate_package(package)
    assert manifest["schema"] == 2
    assert manifest["mod_id"] == "situated-ai"
    wheel = capture.artifact(requirement, quality["wheel"])
    assert wheel.suffix == ".whl"
    assert not python_package.missing_modules(wheel)
    modules = python_package.source_modules()
    with zipfile.ZipFile(wheel) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(set(archive.namelist()))
        for name in modules:
            assert archive.read(name) == (ROOT / "src" / name).read_bytes()
    hygiene_path = capture.artifact(requirement, quality["hygiene_report"])
    hygiene = receipts._json(hygiene_path)
    assert hygiene["schema"] == 1
    assert Path(hygiene["root"]).resolve() == ROOT
    assert hygiene["violation_count"] == 0
    assert hygiene["violations"] == []
    # The final hygiene command must follow the suite and every cache producer.
    hygiene_end = next(command["finished_at"] for command in commands if command["id"] == "hygiene")
    assert all(
        datetime.fromisoformat(command["finished_at"]) <= datetime.fromisoformat(hygiene_end)
        for command in commands
    )
    assert datetime.fromisoformat(
        capture.data["full_acceptance"]["command"]["finished_at"]
    ) <= datetime.fromisoformat(hygiene_end)
    expected = {
        "required_checks_successful": True,
        "source_stable": True,
        "current_standard_package": True,
        "wheel_exact_source_modules": True,
        "final_hygiene_clean": True,
    }
    capture.record(
        requirement,
        request,
        {
            "command_ids": ids,
            "package": quality["package"],
            "wheel": quality["wheel"],
            "hygiene_report": quality["hygiene_report"],
        },
        expected,
        {
            "required_checks_successful": set(ids) >= QUALITY
            and all(command["exit_code"] == 0 for command in commands),
            "source_stable": capture.snapshot == receipts.source_snapshot(ROOT),
            "current_standard_package": manifest["mod_id"] == distribution.MOD_ID,
            "wheel_exact_source_modules": not python_package.missing_modules(wheel),
            "final_hygiene_clean": hygiene["violation_count"] == 0,
        },
        {
            "required_checks_successful": all(
                command["stdout"]["sha256"]
                == _sha(receipts._artifact(ROOT, command["stdout"]).read_bytes())
                for command in commands
            ),
            "source_stable": all(
                command["source_before"] == command["source_after"] == capture.snapshot
                for command in commands
            ),
            "current_standard_package": checksum.read_text(encoding="utf-8").split()[0]
            == _sha(package.read_bytes()),
            "wheel_exact_source_modules": modules <= python_package.wheel_modules(wheel),
            "final_hygiene_clean": hygiene["violations"] == [],
        },
    )


def _delivery(capture: EngineeringCapture, requirement: str) -> dict[str, Any]:
    if "delivery" not in capture.data:
        pytest.skip("需要工程验收产物：实际发布部署后的 delivery")
    delivery = capture.data["delivery"]
    assert isinstance(delivery, dict)
    if not capture.delivery_checked:
        assert receipts._delivery(ROOT, delivery, receipts.digest(capture.snapshot)) == []
        capture.delivery_checked = True
    fields = {
        "merged_ci": ("publication_result",),
        "tag_release_zip_sha": ("publication_result", "zip", "checksum"),
        "workshop_copy": ("publication_result", "workshop_copy"),
        "deployment_rollback_cleanup": (
            "zip",
            "checksum",
            "rollback_instructions",
            "cleanup_result",
        ),
    }
    for field in fields[requirement]:
        capture.artifact(requirement, delivery[field])
    return delivery


def _raw(capture: EngineeringCapture, requirement: str, name: str):
    path = capture.artifact(requirement, capture.data["delivery_raw"][name])
    return json.loads(path.read_text(encoding="utf-8"))


def test_s6_merged_ci(
    engineering_capture: EngineeringCapture, request: pytest.FixtureRequest
) -> None:
    capture = engineering_capture
    requirement = "merged_ci"
    delivery = _delivery(capture, requirement)
    pr = _raw(capture, requirement, "pull_request")
    checks = _raw(capture, requirement, "checks")
    assert pr["url"] == delivery["pull_request_url"]
    assert pr["state"] == "MERGED"
    assert pr["mergedAt"]
    assert pr["mergeCommit"]["oid"] == delivery["merge_commit"]
    assert checks
    assert all(check["state"] == "SUCCESS" and check["name"] and check["link"] for check in checks)
    publication = receipts._json(receipts._artifact(ROOT, delivery["publication_result"]))
    expected = {"merged_at_exact_commit": True, "all_actual_ci_checks_passed": True}
    capture.record(
        requirement,
        request,
        {
            "pull_request": capture.data["delivery_raw"]["pull_request"],
            "checks": capture.data["delivery_raw"]["checks"],
        },
        expected,
        {
            "merged_at_exact_commit": publication["merge_commit"] == delivery["merge_commit"],
            "all_actual_ci_checks_passed": publication["ci_status"] == "passed",
        },
        {
            "merged_at_exact_commit": pr["state"] == "MERGED"
            and pr["mergeCommit"]["oid"] == delivery["merge_commit"],
            "all_actual_ci_checks_passed": all(check["state"] == "SUCCESS" for check in checks),
        },
    )


def test_s6_tag_release_zip_sha(
    engineering_capture: EngineeringCapture, request: pytest.FixtureRequest
) -> None:
    capture = engineering_capture
    requirement = "tag_release_zip_sha"
    delivery = _delivery(capture, requirement)
    release = _raw(capture, requirement, "release")
    tag = (
        capture.artifact(requirement, capture.data["delivery_raw"]["tag_commit"])
        .read_text(encoding="utf-8")
        .strip()
    )
    assert tag == delivery["merge_commit"] == delivery["tag_commit"]
    assert release["tagName"] == delivery["tag"]
    assert release["url"] == delivery["release_url"]
    assert release["isDraft"] is False
    asset_names = [asset["name"] for asset in release["assets"]]
    package = receipts._artifact(ROOT, delivery["zip"])
    checksum = receipts._artifact(ROOT, delivery["checksum"])
    assert asset_names.count(package.name) == asset_names.count(checksum.name) == 1
    for ref in (delivery["zip"], delivery["checksum"]):
        asset = next(item for item in release["assets"] if item["name"] == Path(ref["path"]).name)
        assert asset["size"] == receipts._artifact(ROOT, ref).stat().st_size
        if asset.get("digest"):
            assert asset["digest"] == "sha256:" + ref["sha256"]
    expected = {
        "tag_at_merge": True,
        "published_release_identity": True,
        "zip_and_checksum_assets": True,
    }
    publication = receipts._json(receipts._artifact(ROOT, delivery["publication_result"]))
    capture.record(
        requirement,
        request,
        {
            "release": capture.data["delivery_raw"]["release"],
            "tag": capture.data["delivery_raw"]["tag_commit"],
            "zip": delivery["zip"],
        },
        expected,
        {
            "tag_at_merge": publication["tag_commit"] == publication["merge_commit"],
            "published_release_identity": publication["release_url"] == delivery["release_url"],
            "zip_and_checksum_assets": checksum.read_text(encoding="utf-8").split()
            == [delivery["zip"]["sha256"], package.name],
        },
        {
            "tag_at_merge": tag == delivery["merge_commit"],
            "published_release_identity": release["tagName"] == delivery["tag"]
            and not release["isDraft"],
            "zip_and_checksum_assets": package.name in asset_names and checksum.name in asset_names,
        },
    )


def test_s6_workshop_copy(
    engineering_capture: EngineeringCapture, request: pytest.FixtureRequest
) -> None:
    capture = engineering_capture
    requirement = "workshop_copy"
    delivery = _delivery(capture, requirement)
    copy = capture.artifact(requirement, delivery["workshop_copy"]).read_text(encoding="utf-8")
    assert delivery["tag"] in copy
    assert delivery["workshop_url"] in copy
    assert delivery["release_url"] in copy
    assert len(copy.strip()) >= 100
    publication = receipts._json(receipts._artifact(ROOT, delivery["publication_result"]))
    expected = {"actual_workshop_identity": True, "versioned_release_copy": True}
    capture.record(
        requirement,
        request,
        {"workshop_copy": delivery["workshop_copy"], "workshop_url": delivery["workshop_url"]},
        expected,
        {
            "actual_workshop_identity": publication["workshop_url"] == delivery["workshop_url"],
            "versioned_release_copy": publication["tag"] == delivery["tag"]
            and publication["release_url"] == delivery["release_url"],
        },
        {
            "actual_workshop_identity": delivery["workshop_url"] in copy,
            "versioned_release_copy": delivery["tag"] in copy and delivery["release_url"] in copy,
        },
    )


def test_s6_deployment_rollback_cleanup(
    engineering_capture: EngineeringCapture, request: pytest.FixtureRequest
) -> None:
    capture = engineering_capture
    requirement = "deployment_rollback_cleanup"
    delivery = _delivery(capture, requirement)
    deployed = Path(delivery["deployment"]["root"])
    package = receipts._artifact(ROOT, delivery["zip"])
    with zipfile.ZipFile(package) as archive:
        expected_files = {name: _sha(archive.read(name)) for name in archive.namelist()}
    observed_files = {
        path.relative_to(deployed).as_posix(): _sha(path.read_bytes())
        for path in deployed.rglob("*")
        if path.is_file()
    }
    assert observed_files == expected_files
    launcher = delivery["deployment"]["launcher"]
    assert _sha(Path(launcher["path"]).read_bytes()) == launcher["sha256"]
    rollback = capture.artifact(requirement, delivery["rollback_instructions"]).read_text(
        encoding="utf-8"
    )
    assert len(rollback.strip()) >= 80
    assert deployed.name in rollback
    cleanup = receipts._json(capture.artifact(requirement, delivery["cleanup_result"]))
    assert cleanup["status"] == "complete"
    assert cleanup["remaining"] == []
    expected = {
        "deployed_file_sha256": expected_files,
        "launcher_points_at_deployment": True,
        "rollback_documented": True,
        "cleanup_complete": True,
    }
    capture.record(
        requirement,
        request,
        {
            "deployment": delivery["deployment"],
            "rollback_instructions": delivery["rollback_instructions"],
            "cleanup_result": delivery["cleanup_result"],
        },
        expected,
        {
            "deployed_file_sha256": expected_files,
            "launcher_points_at_deployment": receipts.launcher_points_at_deployment(
                Path(launcher["path"]), deployed
            ),
            "rollback_documented": len(rollback.strip()) >= 80,
            "cleanup_complete": cleanup["status"] == "complete",
        },
        {
            "deployed_file_sha256": observed_files,
            "launcher_points_at_deployment": _sha(Path(launcher["path"]).read_bytes())
            == launcher["sha256"],
            "rollback_documented": deployed.name in rollback,
            "cleanup_complete": cleanup["remaining"] == [],
        },
    )
