"""Opt-in serial pytest capture of actual independent PDX witnesses.

Use ``-p tools.ci.architecture_witness_capture -n0`` and either the legacy
single-row options or ``--architecture-witness-plan=tools/out/plan.json``.
Plans declare explicit stage/requirement/evidence_id/scope/output rows. Every
batch fixture call must select its evidence_ids; nothing broadcasts implicitly.
Each row independently requires all functional roles and compares real outputs.
The plugin only writes result artifacts and draft rows, never stage completion.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest

from pdx.parser import parse_bytes
from pdx.situated import architecture_receipts as receipts
from pdx.situated.native_treatments import _digest, _resolve
from pdx.situated.receipts import digest

_STATE = "architecture-witness-capture-state"


def pytest_addoption(parser):
    group = parser.getgroup("architecture witness capture")
    for name in ("output", "stage", "requirement", "id", "scope", "plan"):
        group.addoption(f"--architecture-witness-{name}", default=None)


def _json_value(value):
    # Freeze caller-owned mappings now and reject NaN or non-JSON observations.
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _write(path: Path, value) -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


class Capture:
    def __init__(self, config, *, declaration=None, snapshot=None):
        self.root = Path(config.rootpath).resolve()
        declaration = declaration or {
            "output": config.getoption("architecture_witness_output"),
            "stage_id": config.getoption("architecture_witness_stage"),
            "requirement_id": config.getoption("architecture_witness_requirement"),
            "evidence_id": config.getoption("architecture_witness_id"),
            "scope_hash": config.getoption("architecture_witness_scope"),
        }
        output = declaration["output"]
        self.output = receipts._path(self.root, output)
        if not output.startswith("tools/out/") or not output.endswith(".json"):
            raise pytest.UsageError("architecture capture output must be tools/out/*.json")
        self.stage = declaration["stage_id"]
        self.requirement = declaration["requirement_id"]
        self.evidence_id = declaration["evidence_id"]
        self.scope = declaration["scope_hash"]
        if (
            self.requirement not in receipts.STAGE_REQUIREMENTS.get(self.stage, ())
            or receipts._evidence_kind(self.stage, self.requirement) != "pdx"
            or not isinstance(self.evidence_id, str)
            or not self.evidence_id
            or not isinstance(self.scope, str)
            or not re.fullmatch(r"[a-f0-9]{64}", self.scope)
        ):
            raise pytest.UsageError(
                "architecture capture requires valid PDX stage/requirement/id/scope"
            )
        if config.getoption("numprocesses", default=0) not in (0, None):
            raise pytest.UsageError("architecture witness capture requires -n0")
        self.snapshot = receipts.source_snapshot(self.root) if snapshot is None else snapshot
        self.external_issues: list[str] = []
        self.plan_ref: dict[str, str] | None = None
        self.artifact_cache: dict[str, dict[str, str]] = {}
        self.parsed_cache: dict[str, Any] = {}
        self.consumer_cache: dict[tuple[str, str, str], str] = {}
        self.cases: list[dict[str, Any]] = []
        self.phases: dict[str, dict[str, str]] = {}
        self.tests: dict[str, dict[str, str]] = {}
        self.production: dict[str, dict[str, str]] = {}
        self.generated: dict[str, dict[str, str]] = {}
        self.consumers: dict[tuple[str, str, str], dict[str, str]] = {}

    def artifact(self, name):
        if name not in self.artifact_cache:
            path = receipts._path(self.root, name)
            self.artifact_cache[name] = {
                "path": name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        return self.artifact_cache[name]

    def record(self, nodeid, **case):
        payload = _case(nodeid, **case)
        if any(item["case_id"] == payload["case_id"] for item in self.cases):
            raise ValueError("duplicate executed witness case_id")
        production = case["production"]
        consumers = case["consumers"]
        if not production or not consumers:
            raise ValueError("actual production and generated consumer identities required")
        test = {"nodeid": nodeid, "sha256": self.artifact(nodeid.split("::", 1)[0])["sha256"]}
        receipts._test_identity(self.root, test)
        self.tests[nodeid] = test
        for name in production:
            if not name.startswith(("src/pdx/", "mod/decisions/", "tools/ci/")):
                raise ValueError("production path outside source role")
            self.production[name] = self.artifact(name)
        for item in consumers:
            name, definition, field = (item[key] for key in ("path", "definition", "field"))
            if not name.startswith("mod/") or name.startswith("mod/decisions/"):
                raise ValueError("generated consumer path outside mod output role")
            identity = name, definition, field
            if identity not in self.consumer_cache:
                if name not in self.parsed_cache:
                    raw = receipts._path(self.root, name).read_bytes()
                    self.artifact_cache[name] = {
                        "path": name,
                        "sha256": hashlib.sha256(raw).hexdigest(),
                    }
                    self.parsed_cache[name] = parse_bytes(raw, path=name)
                parsed = self.parsed_cache[name]
                node, state = _resolve(parsed.root, definition, field)
                if parsed.errors or node is None or state != "found":
                    raise ValueError("actual generated consumer is missing or does not parse")
                self.consumer_cache[identity] = _digest(node)
            self.generated[name] = self.artifact(name)
            self.consumers[identity] = {**item, "ast_sha256": self.consumer_cache[identity]}
        self.cases.append(payload)

    def pytest_runtest_logreport(self, report):
        outcome = "xfail" if hasattr(report, "wasxfail") else report.outcome
        self.phases.setdefault(report.nodeid, {})[report.when] = outcome

    def pytest_sessionfinish(self, session, exitstatus):
        issues = list(self.external_issues)
        if exitstatus != 0:
            issues.append(f"pytest_exit_code:{int(exitstatus)}")
        if receipts.source_snapshot(self.root) != self.snapshot:
            issues.append("source_changed_during_execution")
        if not self.cases:
            issues.append("no_executed_witnesses")
        cases = []
        for case in self.cases:
            phases = self.phases.get(case["nodeid"], {})
            passed = phases == {"setup": "passed", "call": "passed", "teardown": "passed"}
            if not passed:
                issues.append(f"incomplete_or_nonpassing_phases:{case['case_id']}")
            cases.append({**case, "phases": phases, "outcome": "passed" if passed else "rejected"})
        if not {case["role"] for case in cases} >= receipts.WITNESS_ROLES:
            issues.append("missing_functional_witness_roles")
        if len({digest(case["expected"]) for case in cases}) < 2:
            issues.append("no_actual_output_distinction")
        # Row-wide roles cannot let consumer A's scenarios sign consumer B.
        # Each case retains its explicitly executed physical consumers.
        for identity in sorted(self.consumers):
            actual = [
                case
                for case in cases
                if identity
                in {(item["path"], item["definition"], item["field"]) for item in case["consumers"]}
            ]
            label = ":".join(identity)
            if not {case["role"] for case in actual} >= receipts.WITNESS_ROLES:
                issues.append(f"missing_consumer_witness_roles:{label}")
            if len({digest(case["expected"]) for case in actual}) < 2:
                issues.append(f"no_consumer_output_distinction:{label}")
        row = {
            "requirement_id": self.requirement,
            "evidence_id": self.evidence_id,
            "direction": receipts.REQUIREMENT_DIRECTIONS[self.stage, self.requirement],
            "oracle": "independent",
            "evidence_kind": "pdx",
            "production": [self.production[key] for key in sorted(self.production)],
            "generated": [self.generated[key] for key in sorted(self.generated)],
            "consumers": [self.consumers[key] for key in sorted(self.consumers)],
            "tests": [self.tests[key] for key in sorted(self.tests)],
        }
        result = {
            "schema": 1,
            "plan_version": receipts.PLAN_VERSION,
            "stage_id": self.stage,
            "source_snapshot_sha256": digest(self.snapshot),
            "scope_hash": self.scope,
            "evidence_category": "static_check",
            "status": "rejected" if issues else "passed",
            **{
                key: value
                for key, value in row.items()
                if key not in {"direction", "oracle", "tests"}
            },
            "cases": cases,
            "open_items": issues,
            "execution": {"exit_code": int(exitstatus), "collected": session.testscollected},
        }
        if self.plan_ref is not None:
            result["capture_plan"] = self.plan_ref
        ref = _write(self.output, result)
        ref["path"] = self.output.relative_to(self.root).as_posix()
        row["result"] = ref
        row_path = self.output.with_suffix(".row.json")
        if not issues:
            errors = receipts._evidence(
                self.root, self.stage, row, digest(self.snapshot), self.scope
            )
            if errors:
                result["status"] = "rejected"
                result["open_items"] = errors
                _write(self.output, result)
            else:
                _write(row_path, row)
        # An earlier successful run must never leave an apparently current row.
        if result["status"] != "passed":
            row_path.unlink(missing_ok=True)
            if exitstatus == 0:
                session.exitstatus = pytest.ExitCode.TESTS_FAILED
        return result


def _plan(root: Path, name: str) -> list[dict[str, str]]:
    """Read caller-owned row responsibility declarations, never infer coverage."""
    if not isinstance(name, str) or not name.startswith("tools/out/") or not name.endswith(".json"):
        raise pytest.UsageError("architecture witness plan must be tools/out/*.json")
    try:
        data = receipts._json(receipts._path(root, name))
        if (
            not isinstance(data, dict)
            or set(data) != {"schema", "rows"}
            or type(data["schema"]) is not int
            or data["schema"] != 1
        ):
            raise ValueError("plan schema must be 1 with explicit rows")
        rows = data["rows"]
        if not isinstance(rows, list) or not rows:
            raise ValueError("plan requires nonempty explicit rows")
        identities = set()
        paths = {receipts._path(root, name)}
        for row in rows:
            if (
                not isinstance(row, dict)
                or set(row) != {"stage_id", "requirement_id", "evidence_id", "scope_hash", "output"}
                or any(not isinstance(value, str) or not value for value in row.values())
            ):
                raise ValueError("plan row requires stage/requirement/evidence_id/scope/output")
            stage, requirement = row["stage_id"], row["requirement_id"]
            if (
                requirement not in receipts.STAGE_REQUIREMENTS.get(stage, ())
                or receipts._evidence_kind(stage, requirement) != "pdx"
                or not re.fullmatch(r"[a-f0-9]{64}", row["scope_hash"])
            ):
                raise ValueError("plan row must name a valid PDX responsibility and scope")
            if row["evidence_id"] in identities:
                raise ValueError("plan evidence_ids must be unique")
            identities.add(row["evidence_id"])
            output = row["output"]
            if not output.startswith("tools/out/") or not output.endswith(".json"):
                raise ValueError("plan result must be tools/out/*.json")
            path = receipts._path(root, output)
            row_path = path.with_suffix(".row.json")
            if path in paths or row_path in paths:
                raise ValueError("plan and result/row output paths must not overlap")
            paths.update((path, row_path))
        return rows
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise pytest.UsageError(f"invalid architecture witness plan: {exc}") from exc


class BatchCapture:
    def __init__(self, config):
        if any(
            config.getoption(f"architecture_witness_{name}") is not None
            for name in ("output", "stage", "requirement", "id", "scope")
        ):
            raise pytest.UsageError("architecture witness plan cannot mix with single-row options")
        root = Path(config.rootpath).resolve()
        declarations = _plan(root, config.getoption("architecture_witness_plan"))
        self.plan_path = receipts._path(root, config.getoption("architecture_witness_plan"))
        self.plan_sha256 = hashlib.sha256(self.plan_path.read_bytes()).hexdigest()
        snapshot = receipts.source_snapshot(root)
        self.captures = {
            row["evidence_id"]: Capture(config, declaration=row, snapshot=snapshot)
            for row in declarations
        }
        for capture in self.captures.values():
            capture.plan_ref = {
                "path": self.plan_path.relative_to(root).as_posix(),
                "sha256": self.plan_sha256,
            }
        # All rows bind the same initial bytes. Final source_snapshot drift
        # checks remain mandatory; caching grants no acceptance of mutations.
        first = next(iter(self.captures.values()))
        for capture in self.captures.values():
            capture.artifact_cache = first.artifact_cache
            capture.parsed_cache = first.parsed_cache
            capture.consumer_cache = first.consumer_cache

    def record(self, nodeid, *, evidence_ids, **case):
        if (
            not isinstance(evidence_ids, (list, tuple))
            or not evidence_ids
            or any(not isinstance(item, str) for item in evidence_ids)
            or len(set(evidence_ids)) != len(evidence_ids)
        ):
            raise ValueError("batch witness requires explicit nonempty unique evidence_ids")
        if any(item not in self.captures for item in evidence_ids):
            raise ValueError("batch witness names an undeclared evidence responsibility")
        # Validate outputs before recording any explicitly selected row.
        _case(nodeid, **case)
        for evidence_id in evidence_ids:
            self.captures[evidence_id].record(nodeid, **case)

    def pytest_runtest_logreport(self, report):
        for capture in self.captures.values():
            capture.pytest_runtest_logreport(report)

    def pytest_sessionfinish(self, session, exitstatus):
        try:
            unchanged = hashlib.sha256(self.plan_path.read_bytes()).hexdigest() == self.plan_sha256
        except OSError:
            unchanged = False
        for capture in self.captures.values():
            if not unchanged:
                capture.external_issues.append("capture_plan_changed_during_execution")
            capture.pytest_sessionfinish(session, exitstatus)


def _case(
    nodeid, *, case_id, role, expected, reference, generated, production, consumers, **observations
):
    if not isinstance(case_id, str) or not case_id or role not in receipts.WITNESS_ROLES:
        raise ValueError("witness requires case_id and an explicit supported role")
    if set(observations) != {"input"}:
        raise ValueError("witness requires explicit input observations")
    actual_input = observations["input"]
    if not isinstance(actual_input, dict) or not actual_input:
        raise ValueError("witness requires actual nonempty observations")
    if not production or not consumers:
        raise ValueError("actual production and generated consumer identities required")
    if not isinstance(consumers, list) or len(consumers) != 1:
        raise ValueError("each case must bind exactly one executed physical consumer")
    identities = []
    for consumer in consumers:
        if (
            not isinstance(consumer, dict)
            or set(consumer) != {"path", "definition", "field"}
            or any(not isinstance(value, str) or not value for value in consumer.values())
        ):
            raise ValueError("case consumer requires exact path/definition/field identity")
        identities.append((consumer["path"], consumer["definition"], consumer["field"]))
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate case consumer identity")
    payload = _json_value(
        {
            "case_id": case_id,
            "nodeid": nodeid,
            "role": role,
            "input": actual_input,
            "expected_origin": "independent",
            "expected": expected,
            "reference": reference,
            "generated": generated,
            "consumers": [
                {"path": path, "definition": definition, "field": field}
                for path, definition, field in sorted(identities)
            ],
        }
    )
    if digest(expected) != digest(reference) or digest(expected) != digest(generated):
        raise AssertionError("independent expected/reference/generated witness outputs differ")
    return payload


def pytest_configure(config):
    if config.getoption("architecture_witness_plan", default=None):
        config.pluginmanager.register(BatchCapture(config), _STATE)
    elif config.getoption("architecture_witness_output", default=None):
        config.pluginmanager.register(Capture(config), _STATE)


@pytest.fixture
def architecture_witness(request):
    """Record computed outputs; no output is written unless explicitly enabled."""
    state = request.config.pluginmanager.get_plugin(_STATE)

    def record(**case):
        evidence_ids = case.pop("evidence_ids", None)
        if state is None:
            _case(request.node.nodeid, **case)
        elif isinstance(state, BatchCapture):
            state.record(request.node.nodeid, evidence_ids=evidence_ids, **case)
        else:
            if evidence_ids is not None:
                raise ValueError("evidence_ids require an explicit batch plan")
            state.record(request.node.nodeid, **case)

    return record
