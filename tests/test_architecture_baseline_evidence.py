"""Execute real S0 observations; optionally capture them after successful pytest.

Set SITAI_S0_EVIDENCE_OUTPUT to a directory below tools/out and run this entire
module with -n0. Normal regression runs execute the assertions without publishing
rows. Capture binds the actual pytest phase reports, final exit status, frozen
source snapshot and installed-native scope; it never publishes a partial session.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import struct
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any

import pytest
import test_decision_adapters as adapter_tests

from pdx import config, decisions, version_contracts
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_bytes, parse_text
from pdx.situated import architecture_receipts as receipts
from pdx.situated import compiler, engine_scope, migration_baseline, pdx_eval, vanilla_inventory

if TYPE_CHECKING:
    from pathlib import Path

real_generated_branches = adapter_tests.real_generated_branches

ROOT = config.REPO.resolve()
TEST_FILE = "tests/test_architecture_baseline_evidence.py"
KINDS = {
    "archive_identity": "archive",
    "independent_scope": "scope",
    "known_failures_migration": "migration",
}
ARCHIVE_COMMIT = "c91569521ab4aad9cd38db0b242836cf8bda64ab"
# Handwritten frozen identities, independently reviewed against the old Git tree.
ARCHIVES = (
    (
        "docs/design/exec/mod重设计-实施计划.md",
        "6661104271c30e93779dfb774eda0da8e9e85d843db62516ded1330004623365",
        130854,
    ),
    (
        "docs/design/架构主计划.md",
        "7087f800dcf417dbb01c7125bed6f39cddaefd3760ce91601019b849183ab4a6",
        39543,
    ),
    (
        "docs/design/架构子计划.md",
        "50d26df22efca8c6602ff04e36afe5c5e1b6a4df02376439e557f719cf227c7a",
        22575,
    ),
    (
        "docs/design/03-处境决策设计.md",
        "07df1c15a53490a5b4f739a668981154cd8c3e6bc5851e19906503e1bea9c060",
        18573,
    ),
    (
        "docs/design/04-行动覆盖与验收.md",
        "038b68c6513c66294906e3172bd5a8fdaaa8a85ff38172ecab5f75cf3f79a31b",
        28759,
    ),
    (
        "docs/design/05-行动层深化设计.md",
        "054e7cb1c716f4bfd401d3bcf7dd6079a77d04526c3f6e34111a19af2fc6fb58",
        15487,
    ),
    (
        "docs/design/当前工作清单.md",
        "16a9f048c4bcca4601cf11f852e48c475e4803804b25fa6d696041a91b32b96f",
        11518,
    ),
)
FIELDS = ("source", "definition", "field", "actor", "target", "operation")
TAIL = "retain_original_qualification_cost_random_execution"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _ref(path: Path) -> dict[str, str]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": _sha(path.read_bytes())}


class BaselineCapture:
    """One module's actual observations, published only after the final reports."""

    def __init__(self, output: Path | None):
        self.output = output
        self.snapshot = receipts.source_snapshot(ROOT) if output else {}
        self.phases: dict[str, dict[str, str]] = {}
        self.cases: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.artifacts: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
        self.scope: vanilla_inventory.VanillaInventory | None = None
        if output:
            output.mkdir(parents=True, exist_ok=True)
            self._remove_rows()

    def _remove_rows(self) -> None:
        assert self.output is not None
        for requirement in KINDS:
            (self.output / f"{requirement}.row.json").unlink(missing_ok=True)

    def artifact(self, requirement: str, path: Path) -> None:
        if self.output:
            ref = _ref(path)
            self.artifacts[requirement][ref["path"]] = ref

    def observation(self, requirement: str, name: str, value: object) -> None:
        if self.output:
            path = self.output / name
            _write(path, value)
            self.artifact(requirement, path)

    def record(
        self,
        requirement: str,
        request: pytest.FixtureRequest,
        case_id: str,
        input_: dict[str, Any],
        expected: object,
        reference: object,
        observed: object,
    ) -> None:
        assert receipts.digest(expected) == receipts.digest(reference), case_id
        assert receipts.digest(expected) == receipts.digest(observed), case_id
        self.cases[requirement].append(
            {
                "case_id": case_id,
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
        if self.output is None:
            return
        issues = []
        if exitstatus != 0 or session.exitstatus != 0:
            issues.append(f"pytest_exit_code:{int(session.exitstatus)}")
        if receipts.source_snapshot(ROOT) != self.snapshot:
            issues.append("source_changed_during_session")
        expected_ids = {f"{TEST_FILE}::test_s0_{name}" for name in KINDS}
        if set(self.phases) != expected_ids:
            issues.append("complete_module_test_selection_required")
        issues.extend(
            f"nonpassing_or_incomplete_phases:{nodeid}"
            for nodeid in expected_ids
            if self.phases.get(nodeid)
            != {"setup": "passed", "call": "passed", "teardown": "passed"}
        )
        if self.scope is None:
            issues.append("actual_scope_not_discovered")
        # Re-read every bound native byte after execution, including EXE,
        # external manifests and version markers; do not trust a cached scan.
        elif self.scope.source_hashes != _actual_sources(self.scope):
            issues.append("native_inputs_changed_during_session")
        if set(self.cases) != set(KINDS):
            issues.append("requirement_observation_missing")
        _write(
            self.output / "execution.json",
            {
                "exit_code": int(session.exitstatus),
                "phases": self.phases,
                "issues": issues,
                "source_snapshot": self.snapshot,
            },
        )
        self._remove_rows()
        if issues:
            if session.exitstatus == 0:
                session.exitstatus = pytest.ExitCode.TESTS_FAILED
            return
        assert self.scope is not None
        rows = []
        for requirement, kind in KINDS.items():
            artifacts = list(self.artifacts[requirement].values())
            cases = [
                {**case, "outcome": "passed", "phases": self.phases[case["nodeid"]]}
                for case in self.cases[requirement]
            ]
            nodeids = sorted({case["nodeid"] for case in cases})
            result = {
                "schema": 1,
                "plan_version": "A2",
                "stage_id": "S0",
                "requirement_id": requirement,
                "evidence_id": f"a2.s0.{requirement}",
                "source_snapshot_sha256": receipts.digest(self.snapshot),
                "scope_hash": self.scope.scope_hash,
                "evidence_category": "static_check",
                "evidence_kind": kind,
                "status": "passed",
                "artifacts": artifacts,
                "cases": cases,
                "open_items": [],
            }
            if kind == "archive":
                result["archive_manifest"] = _ref(ROOT / "docs/design/archive/manifest.json")
            path = self.output / f"{requirement}.json"
            _write(path, result)
            row = {
                "requirement_id": requirement,
                "evidence_id": result["evidence_id"],
                "direction": "B0",
                "oracle": "independent",
                "evidence_kind": kind,
                "artifacts": artifacts,
                "tests": [
                    {"nodeid": nodeid, "sha256": _sha((ROOT / TEST_FILE).read_bytes())}
                    for nodeid in nodeids
                ],
                "result": _ref(path),
            }
            errors = receipts._evidence(
                ROOT, "S0", row, receipts.digest(self.snapshot), self.scope.scope_hash
            )
            if errors:
                issues.extend(errors)
            rows.append((requirement, row))
        if issues:
            _write(self.output / "rejection.json", {"issues": issues})
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
            return
        for requirement, row in rows:
            _write(self.output / f"{requirement}.row.json", row)


@pytest.fixture(scope="module")
def baseline_capture(request: pytest.FixtureRequest) -> BaselineCapture:
    name = os.environ.get("SITAI_S0_EVIDENCE_OUTPUT")
    output = None
    if name:
        if version_contracts.active_version() != "1.14.5":
            raise pytest.UsageError(
                "S0 A2 evidence capture is historical and requires the 1.14.5 contract; "
                "use the current independent inventory evidence entry for 1.15.0"
            )
        output = (ROOT / name).resolve()
        if (
            not output.is_relative_to((ROOT / "tools/out").resolve())
            or output == (ROOT / "tools/out").resolve()
        ):
            raise pytest.UsageError("S0 capture requires a dedicated directory below tools/out")
        if request.config.getoption("numprocesses", default=0) not in (0, None):
            raise pytest.UsageError("S0 evidence capture requires -n0")
    capture = BaselineCapture(output)
    if output:
        request.config.pluginmanager.register(capture, "architecture-s0-local-capture")
    return capture


@pytest.fixture(scope="module")
def actual_scope(baseline_capture: BaselineCapture) -> vanilla_inventory.VanillaInventory:
    inventory = vanilla_inventory.discover()
    baseline_capture.scope = inventory
    return inventory


def _source_path(name: str) -> Path:
    if name.startswith("@evidence/"):
        return ROOT / name.removeprefix("@evidence/")
    if name.startswith("@engine/"):
        return config.GAME.parent / name.removeprefix("@engine/")
    if name.startswith("@version/"):
        return config.GAME.parent / name.removeprefix("@version/")
    return config.GAME / name


def _actual_sources(inventory: vanilla_inventory.VanillaInventory) -> dict[str, str]:
    return {name: _sha(_source_path(name).read_bytes()) for name in inventory.source_hashes}


def _field_locations(block: Block, prefix: tuple[str, ...] = ()):
    for assignment in block.assignments():
        path = (*prefix, assignment.key)
        yield ".".join(path), assignment
        if isinstance(assignment.value, Block):
            yield from _field_locations(assignment.value, path)


def _ast_bytes(node: Assignment | Block | Scalar | None) -> object:
    if isinstance(node, Assignment):
        return ["assignment", node.key, node.op, node.prefix, _ast_bytes(node.value)]
    if isinstance(node, Block):
        return ["block", [_ast_bytes(child) for child in node.items]]
    if isinstance(node, Scalar):
        return ["scalar", node.text, node.quoted]
    return None


def _native_field_hash(path: Path, definition: str, field: str) -> str:
    parsed = parse_bytes(path.read_bytes(), path=path.name)
    assert not parsed.errors
    definitions = parsed.root.all(definition)
    assert len(definitions) == 1
    node = definitions[0]
    for key in field.split("."):
        assert isinstance(node.value, Block)
        children = node.value.all(key)
        assert len(children) == 1
        node = children[0]
    return _sha(
        json.dumps(_ast_bytes(node.value), ensure_ascii=False, separators=(",", ":")).encode()
    )


def test_s0_archive_identity(
    baseline_capture: BaselineCapture, request: pytest.FixtureRequest
) -> None:
    requirement = "archive_identity"
    manifest = ROOT / "docs/design/archive/manifest.json"
    data = json.loads(manifest.read_bytes())
    expected = [
        {"path": path, "sha256": sha, "bytes": size, "commit": ARCHIVE_COMMIT}
        for path, sha, size in ARCHIVES
    ]
    observed = []
    for path, expected_sha, _ in ARCHIVES:
        # Independent storage reader: no production loader, Git object or network.
        raw = gzip.decompress(
            (ROOT / f"docs/design/archive/objects/{ARCHIVE_COMMIT}/{expected_sha}.gz").read_bytes()
        )
        observed.append(
            {
                "path": path,
                "sha256": _sha(raw),
                "bytes": len(raw),
                "commit": ARCHIVE_COMMIT,
            }
        )
    assert data["schema"] == 1
    assert data["role"] == "historical_reference_only"
    baseline_capture.artifact(requirement, manifest)
    baseline_capture.observation(requirement, "archive-bytes-observation.json", observed)
    baseline_capture.record(
        requirement,
        request,
        "frozen-seven-originals",
        {"commit": ARCHIVE_COMMIT, "manifest": manifest.relative_to(ROOT).as_posix()},
        expected,
        data["files"],
        observed,
    )


@pytest.mark.integration
def test_s0_independent_scope(
    baseline_capture: BaselineCapture,
    actual_scope: vanilla_inventory.VanillaInventory,
    request: pytest.FixtureRequest,
) -> None:
    inventory = actual_scope
    requirement = "independent_scope"
    version = version_contracts.active_version()
    historical_expected = {
        "declarations": 8856,
        "legal": 5463,
        "capabilities": {
            "direct": 2730,
            "indirect": 2733,
            "observation": 2821,
            "pending": 572,
            "unexposed": 0,
        },
        "parsed_files": 1813,
        "content_roots": ["common"],
        "parse_failures": [],
    }
    expected = (
        {
            "declarations": 9766,
            "legal": 5740,
            "capabilities": {
                "direct": 2899,
                "indirect": 2841,
                "observation": 3403,
                "pending": 623,
                "unexposed": 0,
            },
            "parsed_files": 1878,
            "content_roots": ["common"],
            "parse_failures": [],
        }
        if version == "1.15.0"
        else historical_expected
    )
    observed = {
        "declarations": len(inventory.surfaces),
        "legal": sum(
            s.capability in {"direct", "indirect"}
            and s.actor_scope != "unknown"
            and s.target_scope != "unknown"
            and bool(s.scope_evidence)
            for s in inventory.surfaces
        ),
        "capabilities": dict(Counter(s.capability for s in inventory.surfaces)) | {"unexposed": 0},
        "parsed_files": sum(
            name.endswith(".txt")
            for name in inventory.source_hashes
            if not name.startswith("@")
            and any(name.startswith(directory + "/") for directory in inventory.scanned_directories)
        ),
        "content_roots": list(inventory.content_roots),
        "parse_failures": [],
    }
    reference = {
        "declarations": inventory.discovered_count,
        "legal": inventory.legal_count,
        "capabilities": inventory.capability_counts,
        "parsed_files": inventory.parsed_files,
        "content_roots": list(inventory.content_roots),
        "parse_failures": list(inventory.parse_failures),
    }
    baseline_capture.record(
        requirement,
        request,
        "installed-native-denominator",
        {
            "game_version": version,
            "activation": "all_installed_content_not_runtime_activation",
            "migration_denominator_not_discovery": 1401,
        },
        expected,
        reference,
        observed,
    )
    native_sources = _actual_sources(inventory)
    # Complete achievement and population sources prove reader scopes without
    # entering consumer discovery or changing its reviewed declaration count.
    assert len(native_sources) == (1960 if version == "1.15.0" else 1894)
    historical_pins = {
        "common/achievements/ep1_sphere_of_influence_achievements.txt": "aa504255aabcf3cfecf6fc6196cf66803a7e87b8b15c2458034c97a95dec82e0",
        "common/achievements/ip4_iberian_twilight_achievements.txt": "0fb91eda557761442864e4e18a4a5c7be3dace31ac9b423b2581bfab8b986268",
        "common/pop_types/laborers.txt": "90e109f061ca04c308d3d60cf6ba6d91cbe3769759ff28f0a9a0bd34e169a2d5",
        "common/pop_types/peasants.txt": "1d544a332f7c628b5f832f2a2033c25fafde6d9ed5e629b829432a57419f0c42",
        "common/pop_types/machinists.txt": "e0ddad8032fd6be5d0eb77533cf9f711a5baf5fe275d20819bc5ba8e3f6785ee",
        "common/journal_entries/00_urbanization.txt": "0be06294448f31679d2b14280b4e6c1991f0d2fa34f97ccc0452068c7cdc5ee6",
    }
    expected_pins = (
        {
            "common/achievements/ep1_sphere_of_influence_achievements.txt": "323263f0483c14145c79b2a054bc7dd04aee5783731e5204604861d602cd4969",
            "common/achievements/ip4_iberian_twilight_achievements.txt": "0fb91eda557761442864e4e18a4a5c7be3dace31ac9b423b2581bfab8b986268",
            "common/pop_types/laborers.txt": "3b136e31556cd483ea213c82eef47c93f9774490775870622331f6139160d9f2",
            "common/pop_types/peasants.txt": "1d544a332f7c628b5f832f2a2033c25fafde6d9ed5e629b829432a57419f0c42",
            "common/pop_types/machinists.txt": "5960f8b6cc15e67b1305bf5d0d74368d2004572099b87ce4c6c827818497c39f",
            "common/journal_entries/00_urbanization.txt": "dff544be003ef9c6283132b38696bf2b765f170aa0a06771a6ce4afc820fd622",
        }
        if version == "1.15.0"
        else historical_pins
    )
    assert {name: native_sources[name] for name in expected_pins} == expected_pins
    baseline_capture.record(
        requirement,
        request,
        "every-bound-source-byte",
        {"source_names": sorted(native_sources)},
        native_sources,
        inventory.source_hashes,
        _actual_sources(inventory),
    )
    # Independently walk actual syntax, resolving all discovered declarations by
    # definition, full field path, line and occurrence. No Mod rule supplies this
    # syntax index or the denominator. Retain parent/context bytes for inspection.
    surfaces_by_source: dict[str, list[Any]] = defaultdict(list)
    for surface in inventory.surfaces:
        surfaces_by_source[surface.source].append(surface)
    contexts = []
    for source, surfaces in surfaces_by_source.items():
        raw = _source_path(source).read_bytes()
        parsed = parse_bytes(raw, path=source)
        assert not parsed.errors, source
        locations: dict[tuple[str, str, int], list[Assignment]] = defaultdict(list)
        for definition in parsed.top_assignments:
            locations[(definition.key, "__body__", definition.line)].append(definition)
            if isinstance(definition.value, Block):
                for field, node in _field_locations(definition.value):
                    locations[(definition.key, field, node.line)].append(node)
        occurrences: dict[tuple[str, str], list[int]] = defaultdict(list)
        for surface in surfaces:
            assert locations[(surface.definition, surface.field, surface.source_line)], (
                source,
                surface.definition,
                surface.field,
                surface.source_line,
            )
            occurrences[(surface.definition, surface.field)].append(surface.declaration_occurrence)
            identity = (source, surface.definition, surface.field, surface.declaration_occurrence)
            assert surface.declaration_id == receipts.digest(identity)
            if surface.parent_field is not None:
                assert locations[
                    (surface.definition, surface.parent_field, surface.parent_source_line)
                ]
            lines = raw.decode("utf-8-sig").splitlines()
            contexts.append(
                {
                    "declaration_id": receipts.digest(identity),
                    "source": source,
                    "definition": surface.definition,
                    "field": surface.field,
                    "line": surface.source_line,
                    "occurrence": surface.declaration_occurrence,
                    "parent_field": surface.parent_field,
                    "parent_line": surface.parent_source_line,
                    "context_sha256": _sha(
                        "\n".join(
                            lines[max(0, surface.source_line - 3) : surface.source_line + 2]
                        ).encode()
                    ),
                }
            )
        for numbers in occurrences.values():
            assert sorted(numbers) == list(range(1, len(numbers) + 1))
    declarations = expected["declarations"]
    assert len({c["declaration_id"] for c in contexts}) == declarations
    baseline_capture.record(
        requirement,
        request,
        "syntax-identity-occurrence-parent-closure",
        {"declarations": declarations, "native_sources": len(surfaces_by_source)},
        {"closed": declarations, "unique": declarations},
        {
            "closed": inventory.discovered_count,
            "unique": len({s.declaration_id for s in inventory.surfaces}),
        },
        {"closed": len(contexts), "unique": len({c["declaration_id"] for c in contexts})},
    )
    baseline_capture.observation(requirement, "native-inventory.json", inventory.as_dict())
    baseline_capture.observation(requirement, "native-contexts.json", contexts)
    baseline_capture.observation(requirement, "source-byte-closure.json", native_sources)


def _known_failure_observations(
    capture: BaselineCapture, request: pytest.FixtureRequest, branches
) -> None:
    import test_decision_adapters as adapters
    from hypothesis.vendor.pretty import pretty

    requirement = "known_failures_migration"
    scripts = [
        "if = { limit = { always = yes } if = { limit = { always = yes } add = 2 } }",
        "if = { limit = { always = yes } if = { limit = { always = no } add = 2 } } else_if = { limit = { always = yes } add = 3 } else = { add = 4 }",
        "if = { limit = { always = no } add = 2 } else_if = { limit = { always = yes } if = { limit = { always = no } add = 3 } else = { multiply = 1.3 } } else = { add = 4 }",
        "if = { limit = { always = no } add = 2 } else_if = { limit = { always = no } add = 3 } else = { add = 4 }",
    ]
    for number, (script, expected) in enumerate(
        zip(scripts, [("add", 2.0), None, ("multiply", 1.3), ("add", 4.0)], strict=True)
    ):
        parsed = parse_text(script)
        assert not parsed.errors
        reference = adapters._interpret_adjustments(parsed.root, {})
        result = pdx_eval.evaluate("# ACTION nested_regression [oracle];\n" + script, {})
        selected = [item for item in result if item.fallback == "selected"]
        observed = (selected[0].operation, selected[0].delta) if selected else None
        capture.record(
            requirement,
            request,
            f"historical-nested-chain-{number}",
            {"script": script},
            expected,
            reference,
            observed,
        )
    # Replay the actual saved Hypothesis example against the unchanged, complete
    # generated adapter fixture and the original independent oracle assertions.
    adapters.test_every_actual_adapter_branch_matches_reference_with_typed_inputs.hypothesis.inner_test(
        branches, seed=284, is_ai=True, missing_target=False
    )
    capture.record(
        requirement,
        request,
        "original-typed-input-example",
        {
            "seed": 284,
            "is_ai": True,
            "missing_target": False,
            "test": "tests/test_decision_adapters.py::test_every_actual_adapter_branch_matches_reference_with_typed_inputs",
        },
        {"all_policy_assertions": True},
        {"all_policy_assertions": True},
        {"all_policy_assertions": True},
    )
    # Exercise diagnostics with the real full fixture, preserving its payload.
    assert len(branches.branches) > 20
    expected_diagnostics = {
        "repr": "_GeneratedBranches()",
        "pretty": f"_GeneratedBranches(policies={len(branches.branches)})",
        "payload_retained": True,
    }
    reference_diagnostics = {
        "repr": repr(branches),
        "pretty": pretty(branches),
        "payload_retained": bool(branches.scripts),
    }
    observed_diagnostics = {
        "repr": repr(branches),
        "pretty": pretty(branches),
        "payload_retained": all(id(policy) in branches.scripts for policy, _ in branches.branches),
    }
    capture.record(
        requirement,
        request,
        "bounded-real-fixture-diagnostics",
        {
            "policies": len(branches.branches),
            "rss_root_cause": "not_proven",
            "resource_acceptance_owner": "S5.full_regression_resources",
        },
        expected_diagnostics,
        reference_diagnostics,
        observed_diagnostics,
    )
    capture.artifact(requirement, ROOT / "tests/test_decision_adapters.py")
    current = version_contracts.active_version() == "1.15.0"
    law_manifest = (
        ROOT / "research/situated/victoria3-1.15.0-law-scope.json"
        if current
        else engine_scope.LAW_MANIFEST
    )
    expected_manifest_sha = (
        "5787364832b3a7c0ab9028d2733623ddbe999af0bd6a613eafcd0dea7ed28a7b"
        if current
        else "eb96a222582705af59147adc6da9e6f2b11533e05a73eb9583e55171f79b0ba9"
    )
    manifest_bytes = law_manifest.read_bytes()
    assert _sha(manifest_bytes) == expected_manifest_sha
    data = json.loads(manifest_bytes)
    assert data["baseline"] == f"victoria3-{version_contracts.active_version()}-windows-x64"
    inputs = {source: (config.GAME / source).read_bytes() for source in data["script_hashes"]}
    actual_hashes = {source: _sha(raw) for source, raw in inputs.items()}
    expected_sources = 25 if current else 21
    assert len(actual_hashes) == expected_sources
    assert actual_hashes == data["script_hashes"]
    proof = engine_scope.law_evidence(config.GAME, inputs)
    assert proof.verified
    if current:
        # Independently pinned current edges lie in the reviewed, byte-locked
        # observation windows. Do not inherit historical instruction addresses.
        control_flow_checks = [
            {
                "label": label,
                "instruction_va": address,
                "instruction_bytes": instruction,
                "target_va": target,
            }
            for label, address, instruction, target in (
                ("law parser thunk", "0x140840e3f", "e97cbefa00", "0x1417eccc0"),
                ("law exact token dispatch", "0x1417ecee7", "0f8447010000", "0x1417ed034"),
                ("law qualification wrapper", "0x141621f79", "e832da1c00", "0x1417ef9b0"),
                ("actual law AI candidate consumer", "0x1415e1449", "e842090400", "0x141621d90"),
                ("actual law AI candidate consumer", "0x1415e1455", "0f848d020000", "0x1415e16e8"),
            )
        ]
        windows = {point["label"]: point for point in data["observations"]}
        for check in control_flow_checks:
            point = windows[check["label"]]
            offset = int(check["instruction_va"], 16) - int(point["va"], 16)
            instruction = bytes.fromhex(check["instruction_bytes"])
            assert offset >= 0
            assert bytes.fromhex(point["bytes"])[offset : offset + len(instruction)] == instruction
    else:
        control_flow_checks = data["control_flow_checks"]
    executable = config.GAME.parent / "binaries/victoria3.exe"
    assert executable.stat().st_size == data["exe"]["bytes"]
    with executable.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == data["exe"]["sha256"]
        for point in data["observations"]:
            stream.seek(int(point["file_offset"], 16))
            assert stream.read(len(bytes.fromhex(point["bytes"]))) == bytes.fromhex(point["bytes"])
    for check in control_flow_checks:
        raw = bytes.fromhex(check["instruction_bytes"])
        assert int(check["instruction_va"], 16) + len(raw) + struct.unpack_from(
            "<i", raw, len(raw) - 4
        )[0] == int(check["target_va"], 16)
    expected_contract = {
        "family": "laws",
        "hook": "ai_will_do",
        "actor": "country",
        "target": "definition_only:law_type",
        "operation": "eligibility",
        "capability": "direct",
        "named_targets_proven": [],
    }
    capture.record(
        requirement,
        request,
        "law-interface-source-and-machine-byte-closure",
        {
            "native_sources": sorted(inputs),
            "machine_byte_points": len(data["observations"]),
            "control_flow_edges": len(control_flow_checks),
        },
        expected_contract,
        data["contract"],
        expected_contract if proof.verified and len(proof.sources) == expected_sources else {},
    )
    capture.artifact(requirement, law_manifest)
    capture.observation(
        requirement,
        "historical-failure-inputs.json",
        {
            "nested_scripts": scripts,
            "typed_input": {"seed": 284, "is_ai": True, "missing_target": False},
            "law_sources": actual_hashes,
            "law_control_flow": control_flow_checks,
            "memory": {
                "reproduced_problem": "unbounded diagnostic fixture expansion",
                "current_check": "actual complete fixture has bounded representations",
                "historical_rss_root_cause": "not_proven",
                "final_resource_gate": "S5.full_regression_resources",
            },
        },
    )


@pytest.mark.integration
def test_s0_known_failures_migration(
    baseline_capture: BaselineCapture,
    actual_scope: vanilla_inventory.VanillaInventory,
    real_generated_branches,
    request: pytest.FixtureRequest,
) -> None:
    requirement = "known_failures_migration"
    model = compiler.load_model()
    bundle = model.consumer_ir
    assert bundle is not None
    retired = migration_baseline.validated_retirements(bundle)
    historical = json.loads(migration_baseline.DEFAULT_SOURCE.read_bytes())
    retirement_data = json.loads(migration_baseline.RETIREMENTS_SOURCE.read_bytes())
    assert (
        _sha(migration_baseline.DEFAULT_SOURCE.read_bytes())
        == "fcce11e045e9933c13644a361da3a448330208c0b712ac3df615eed307aa55e6"
    )
    assert historical["commit"] == "74492fc05321c0767cb07202a91797a7663e7ee0"
    assert historical["tag"] == "v3.0.1"
    rules = {(w.source, w.definition): w for w in bundle.writers if w.kind == "rule_action"}
    all_ids = {(w.source, w.definition) for w in bundle.writers}
    cards = {w.definition: w for w in bundle.writers if w.kind == "action_card"}
    retirements = {
        (row["source"], row["definition"]): row for row in retirement_data["retirements"]
    }
    versioned = migration_baseline._versioned_contract()
    redirects = (
        {
            (entry["source"], entry["definition"], entry["historical_replacement"]): entry
            for entry in versioned["replacement_redirects"]
        }
        if versioned is not None
        else {}
    )
    if versioned is not None:
        assert len(redirects) == len(versioned["replacement_redirects"])
        assert set(redirects) == {
            (
                "common/technology/technologies/10_production.txt",
                "dough_rollers_ai_weight",
                "technology_dough_rollers_labor_ready",
            )
        }
        current_native = ROOT / versioned["source"]
        assert _sha(current_native.read_bytes()) == versioned["source_sha256"]
        for field, expected_hash in versioned["retentions"].items():
            assert (
                _native_field_hash(current_native, versioned["definition"], field) == expected_hash
            )
            assert (
                _native_field_hash(
                    config.GAME / "common/ai_strategies/00_default_strategy.txt",
                    versioned["definition"],
                    field,
                )
                == expected_hash
            )
    assert len(retirements) == len(retirement_data["retirements"])
    assert retired == set(retirements)
    expected_rows = []
    observed_rows = []
    for row in historical["rules"]:
        identity = (row["source"], row["definition"])
        expected = {field: row[field] for field in FIELDS}
        if identity in retirements:
            assert identity not in all_ids
            retirement = retirements[identity]
            assert {field: retirement[field] for field in FIELDS} == expected
            if "native_retention" in retirement:
                assert retirement["replacements"] == []
                assert retirement["native_retention"]["business_complete"] is False
                evidence = retirement["native_retention"]
                assert (
                    _native_field_hash(
                        ROOT / evidence["source"], evidence["definition"], evidence["field"]
                    )
                    == evidence["ast_sha256"]
                )
                assert (
                    _native_field_hash(
                        decisions.product_path() / "common/ai_strategies/00_default_strategy.txt",
                        evidence["definition"],
                        evidence["field"],
                    )
                    == evidence["ast_sha256"]
                )
                expected_rows.append({**expected, "disposition": "native_retention"})
                observed_rows.append(
                    {
                        **{field: retirement[field] for field in FIELDS},
                        "disposition": "native_retention",
                    }
                )
            else:
                for replacement in retirement["replacements"]:
                    redirect = redirects.get((row["source"], row["definition"], replacement))
                    current_replacement = replacement
                    if redirect is not None:
                        assert {
                            field: redirect[field] for field in FIELDS if field != "definition"
                        } == {field: row[field] for field in FIELDS if field != "definition"}
                        current_replacement = redirect["current_replacement"]
                        assert (row["source"], replacement) not in all_ids
                    writer = rules[(row["source"], current_replacement)]
                    assert {
                        field: getattr(writer, field) for field in FIELDS if field != "definition"
                    } == {field: row[field] for field in FIELDS if field != "definition"}
                    assert writer.owner.strip()
                    assert writer.vanilla_tail == TAIL
                expected_rows.append({**expected, "disposition": "replaced"})
                observed_rows.append(
                    {**{field: retirement[field] for field in FIELDS}, "disposition": "replaced"}
                )
        else:
            writer = rules[identity]
            expected_rows.append({**expected, "disposition": "retained_identity"})
            observed_rows.append(
                {
                    **{field: getattr(writer, field) for field in FIELDS},
                    "disposition": "retained_identity",
                }
            )
    assert len(expected_rows) == 1401
    baseline_capture.record(
        requirement,
        request,
        "all-1401-historical-rule-contracts",
        {
            "historical_tag": "v3.0.1",
            "historical_sha256": _sha(migration_baseline.DEFAULT_SOURCE.read_bytes()),
        },
        expected_rows,
        expected_rows,
        observed_rows,
    )
    expected_cards = [
        ("diplomatic_opening", "recklessness", "add"),
        ("diplomatic_restraint", "recklessness", "add"),
        ("education_and_research", "economic_vs_government_spending_balance", "add"),
        ("fiscal_recovery", "diplomatic_play_neutrality", "add"),
        ("industrial_foundation", "economic_vs_government_spending_balance", "add"),
        ("political_reform", "change_law_chance", "add"),
        ("wartime_defense", "diplomatic_play_neutrality", "add"),
    ]
    baseline_capture.record(
        requirement,
        request,
        "seven-published-action-card-contracts",
        {"tag": "v3.0.1"},
        expected_cards,
        [(r["definition"], r["field"], r["operation"]) for r in historical["cards"]],
        [(name, cards[name].field, cards[name].operation) for name, _, _ in expected_cards],
    )
    source = "common/ai_strategies/00_default_strategy.txt"
    expected_replacements = [
        "military_capacity_ship_need",
        "military_capacity_ship_funded",
        "military_capacity_ship_default_cost",
        "military_capacity_ship_liquidity_cost",
    ]
    row = retirements[(source, "ai_strategy_default_ship_construction_output_multiplier")]
    baseline_capture.record(
        requirement,
        request,
        "handwritten-ship-replacement-responsibility",
        {
            "source": source,
            "old_definition": row["definition"],
            "field": "ai_strategy_default.ship_construction_output_multiplier",
        },
        expected_replacements,
        row["replacements"],
        [rules[(source, name)].definition for name in expected_replacements],
    )
    native = retirements[("mod/decisions/information.toml", "colonial_projection_capacity")][
        "native_retention"
    ]
    baseline_capture.record(
        requirement,
        request,
        "retained-native-is-not-business-completion",
        {"historical_definition": "colonial_projection_capacity", "scope_responsibility": "S4"},
        {
            "business_complete": False,
            "ast_sha256": "4a4a4342151af33b74989498b00e2bd840da9e60862680b47ecbf17e7a4564ba",
        },
        {key: native[key] for key in ("business_complete", "ast_sha256")},
        {
            "business_complete": False,
            "ast_sha256": _native_field_hash(
                decisions.product_path() / "common/ai_strategies/00_default_strategy.txt",
                native["definition"],
                native["field"],
            ),
        },
    )
    baseline_capture.artifact(requirement, migration_baseline.DEFAULT_SOURCE)
    baseline_capture.artifact(requirement, migration_baseline.RETIREMENTS_SOURCE)
    if versioned is not None:
        baseline_capture.artifact(requirement, migration_baseline._VERSION_115_SOURCE)
    baseline_capture.observation(
        requirement,
        "migration-responsibilities.json",
        {
            "rules": observed_rows,
            "retirement_rows": retirement_data["retirements"],
            "cards": expected_cards,
        },
    )
    _known_failure_observations(baseline_capture, request, real_generated_branches)
