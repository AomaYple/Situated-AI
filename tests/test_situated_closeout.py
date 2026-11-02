"""A2 静态工程收口与阶段门合同。"""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from dataclasses import asdict, replace
from types import SimpleNamespace
from typing import Any

import pytest

from pdx.model import Block
from pdx.parser import parse_bytes
from pdx.situated import architecture_receipts as receipts
from pdx.situated.native_treatments import _digest
from pdx.situated.receipts import digest
from pdx.situated.vanilla_inventory import VanillaInventory, VanillaSurface
from tools.ci import situated_closeout

pytestmark = pytest.mark.unit


def test_生产文件编码合同拒绝BOM_CR和非法UTF8(tmp_path) -> None:
    root = tmp_path / "mod"
    (root / "common").mkdir(parents=True)
    (root / "common" / "good.txt").write_bytes(b"good = {}\n")
    (root / "common" / "bom.txt").write_bytes(b"\xef\xbb\xbfbad\n")
    (root / "common" / "crlf.txt").write_bytes(b"bad\r\n")
    (root / "common" / "invalid.txt").write_bytes(b"\xff\n")

    violations = situated_closeout.production_encoding_violations(root)

    assert {(item["path"], item["reason"]) for item in violations} == {
        ("common/bom.txt", "UTF-8 BOM"),
        ("common/crlf.txt", "CR/CRLF"),
        ("common/invalid.txt", "不是 UTF-8"),
    }


def test_候选包拒绝探针缓存日志和Python运行态() -> None:
    names = (
        ".metadata/metadata.json",
        "common/ai_strategies/00_default_strategy.txt",
        "common/probes/temporary.txt",
        "common/scripted_effects/cache_values.txt",
        "debug.log",
        "tools/out/report.json",
        "scripts/build.py",
    )

    assert situated_closeout.package_exclusion_violations(names) == [
        "common/probes/temporary.txt",
        "common/scripted_effects/cache_values.txt",
        "debug.log",
        "scripts/build.py",
        "tools/out/report.json",
    ]


def test_当前生产metadata登记ConsumerIR唯一owner() -> None:
    result = situated_closeout.consumer_ir_owner_report()

    assert result["issues"] == []
    assert result["writer_count"] > 0
    owners = result["field_owners"]
    assert owners["diplomatic_play_neutrality"] == "situated_kernel"
    assert owners["change_law_chance"] == "situated_kernel"
    assert owners["recklessness"] == "situated_kernel"
    assert "consumer_adapters" in set(owners.values())


def test_收口报告保持静态范围且可写出稳定JSON(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(situated_closeout, "PRODUCTION", tmp_path / "mod")
    monkeypatch.setattr(situated_closeout.distribution, "check_generation_lock", lambda: None)
    monkeypatch.setattr(
        situated_closeout.distribution,
        "read_production_files",
        lambda: {"common/a.txt": "a = {}\n"},
    )
    monkeypatch.setattr(
        situated_closeout,
        "consumer_ir_owner_report",
        lambda: {"issues": [], "field_owners": {"field": "owner"}, "writer_count": 1},
    )
    monkeypatch.setattr(
        situated_closeout.repo_hygiene,
        "report",
        lambda root: {
            "schema": 1,
            "root": str(root),
            "excluded_roots": [],
            "violation_count": 0,
            "violations": [],
        },
    )
    monkeypatch.setattr(
        situated_closeout,
        "plan_gate",
        lambda _root: {
            "status": "blocked",
            "ready": False,
            "engineering_ready": False,
            "stage": "S0",
            "reason": "测试中的未闭合范围",
            "discovered": 1,
            "pending": 1,
            "parse_failures": [],
            "scope_hash": "a" * 64,
            "evidence": "static_check",
        },
    )
    (tmp_path / "mod" / "common").mkdir(parents=True)
    (tmp_path / "mod" / "common" / "a.txt").write_bytes(b"a = {}\n")

    result = situated_closeout.report(root=tmp_path, production=tmp_path / "mod")

    assert result["status"] == "complete"
    assert result["delivery_ready"] is False
    assert all(result["checks"].values())
    assert result["scope"].startswith("静态工程收口")
    assert json.dumps(result, ensure_ascii=False, sort_keys=True)


def test_A2门使用当前计划与精确S阶段依赖() -> None:
    assert situated_closeout.PLAN_PATH.as_posix() == "docs/design/架构主计划.md"
    assert situated_closeout.STAGE_DEPENDENCIES == {
        "S0": (),
        "S1": ("S0",),
        "S2": ("S1",),
        "S3": ("S1",),
        "S4": ("S2", "S3"),
        "S5": ("S4",),
        "S6": ("S5",),
    }


def _ref(root, path):
    return {"path": path, "sha256": hashlib.sha256((root / path).read_bytes()).hexdigest()}


def _write(root, path, value):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return _ref(root, path)


def _save(candidate):
    return _write(candidate.root, receipts.RECEIPT_PATH.as_posix(), candidate.data)


@pytest.fixture
def architecture_candidate(tmp_path, monkeypatch):
    """Synthetic complete evidence graph; no real A2 completion is asserted."""
    root = tmp_path
    for path in (receipts.PLAN_PATH, receipts.SUBPLAN_PATH):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(situated_closeout.REPO / path, target)
    for name, text in {
        "src/pdx/fixture.py": "def evaluate(value):\n    return value\n",
        "mod/common/fixture.txt": "candidate={weight={value=1}}\n",
        "tests/test_witness.py": "\n".join(
            f"def test_{role}():\n    assert 1 == 1\n" for role in sorted(receipts.WITNESS_ROLES)
        ),
    }.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    surfaces = tuple(
        VanillaSurface(
            surface_id=f"surface-{capability}",
            source="common/fixture.txt",
            definition="candidate",
            field=f"weight_{capability}",
            actor_scope="country",
            target_scope="none",
            operation="score",
            capability=capability,
            status="pending",
            getter=None,
            getter_note="fixture",
            scope_evidence=("native:1",),
            responsibility_step="legacy-not-a-stage",
            source_line=1,
        )
        for capability in ("direct", "observation", "unexposed")
    )
    inventory = VanillaInventory(
        baseline_id="independent-native",
        source_hashes={"common/fixture.txt": "d" * 64},
        scope_hash="b" * 64,
        surfaces=surfaces,
        scanned_directories=("fixture",),
        content_roots=("game",),
        parsed_files=1,
    )
    snapshot = receipts.source_snapshot(root)
    data = {
        "schema": 1,
        "plan_version": "A2",
        "plan": _ref(root, receipts.PLAN_PATH.as_posix()),
        "subplan": _ref(root, receipts.SUBPLAN_PATH.as_posix()),
        "source_snapshot": snapshot,
        "closed_stages": list(receipts.STAGE_DEPENDENCIES),
        "stages": [],
        "native_scope": {
            "baseline_id": inventory.baseline_id,
            "scope_hash": inventory.scope_hash,
            "denominator": inventory.discovered_count,
            "source_hashes": inventory.source_hashes,
            "assignments": [],
        },
    }
    test_path = "tests/test_witness.py"
    tests = [
        {"nodeid": f"{test_path}::test_{role}", "sha256": _ref(root, test_path)["sha256"]}
        for role in sorted(receipts.WITNESS_ROLES)
    ]
    production = [_ref(root, "src/pdx/fixture.py")]
    generated = [_ref(root, "mod/common/fixture.txt")]
    node = parse_bytes(
        (root / "mod/common/fixture.txt").read_bytes(), path="mod/common/fixture.txt"
    ).root.first("candidate")
    assert node is not None
    assert isinstance(node.value, Block)
    field = node.value.first("weight")
    assert field is not None
    consumers = [
        {
            "path": "mod/common/fixture.txt",
            "definition": "candidate",
            "field": "weight",
            "ast_sha256": _digest(field),
        }
    ]
    stage_map: dict[str, Any] = {}
    for stage, dependencies in receipts.STAGE_DEPENDENCIES.items():
        evidence = []
        requirements = []
        for requirement in receipts.STAGE_REQUIREMENTS[stage]:
            evidence_id = f"{stage}.{requirement}"
            cases = [
                {
                    "case_id": role,
                    "role": role,
                    "nodeid": test["nodeid"],
                    "outcome": "passed",
                    "expected_origin": "independent",
                    "input": {"role": role},
                    "expected": index,
                    "reference": index,
                    "generated": index,
                }
                for index, (role, test) in enumerate(
                    zip(sorted(receipts.WITNESS_ROLES), tests, strict=True)
                )
            ]
            result = {
                "schema": 1,
                "plan_version": "A2",
                "stage_id": stage,
                "requirement_id": requirement,
                "evidence_id": evidence_id,
                "source_snapshot_sha256": digest(snapshot),
                "scope_hash": inventory.scope_hash,
                "evidence_category": "static_check",
                "status": "passed",
                "production": production,
                "generated": generated,
                "consumers": consumers,
                "cases": cases,
                "open_items": [],
            }
            if requirement == "full_regression_resources":
                result["full_acceptance"] = _write(
                    root,
                    "tools/out/full-acceptance.json",
                    {
                        "ok": True,
                        "exit_code": 0,
                        "errors": [],
                        "collection": {
                            field: [test["nodeid"] for test in tests]
                            for field in ("nodeids", "started", "finished")
                        },
                        "groups": [
                            {
                                "tag": "full",
                                "exit_code": 0,
                                "wall_s": 1,
                                "peak_total_mb": 10,
                                "per_worker_peak_mb": 10,
                                "samples": 1,
                                "n_workers": 0,
                            }
                        ],
                        "tests": {
                            "tests": len(tests),
                            "errors": 0,
                            "failures": 0,
                            "unknown_skip_reasons": [],
                        },
                        "resources": {
                            "execution_peak_mb": 10,
                            "inproc": [{"worker": "master"}],
                            "peak_pairs": [{"worker": "master"}],
                        },
                        "verdict": [{"ok": True}],
                        "coverage": {
                            "branch": True,
                            "percent": 100,
                            "floor": 90,
                            "failed_modules": [],
                            "missing_modules": [],
                        },
                    },
                )
            evidence.append(
                {
                    "evidence_id": evidence_id,
                    "requirement_id": requirement,
                    "direction": receipts.REQUIREMENT_DIRECTIONS[stage, requirement],
                    "oracle": "independent",
                    "production": production,
                    "generated": generated,
                    "consumers": consumers,
                    "tests": tests,
                    "result": _write(root, f"tools/out/{evidence_id}.json", result),
                }
            )
            requirements.append(
                {"requirement_id": requirement, "status": "verified", "evidence_ids": [evidence_id]}
            )
        payload = {
            "stage_id": stage,
            "status": "verified",
            "directions": list(receipts.STAGE_DIRECTIONS[stage]),
            "dependencies": list(dependencies),
            "dependency_hashes": {dep: digest(stage_map[dep]) for dep in dependencies},
            "scope_hash": inventory.scope_hash,
            "pending": [],
            "blocked": [],
            "unclassified": [],
            "failures": [],
            "input_hashes": {item["path"]: item["sha256"] for item in production + generated},
            "output_paths": [item["result"]["path"] for item in evidence],
            "evidence_ids": [item["evidence_id"] for item in evidence],
            "requirements": requirements,
            "evidence": evidence,
        }
        stage_map[stage] = payload
        data["stages"].append(payload)
    for surface in surfaces:
        data["native_scope"]["assignments"].append(
            {
                "declaration_id": surface.declaration_id,
                "context": json.loads(json.dumps(asdict(surface))),
                "stage": "S4",
                "status": {
                    "direct": "implemented",
                    "observation": "observation",
                    "unexposed": "engine_unexposed",
                }[surface.capability],
                "evidence_ids": ["S4.legal_scope_disposition"],
            }
        )
    package = root / "tools/out/package.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("common/fixture.txt", b"candidate={weight=1}\n")
    deployed = root / "deployment"
    with zipfile.ZipFile(package) as archive:
        archive.extractall(deployed)
    launcher = root / "launcher.mod"
    launcher.write_text(f'path="{deployed.as_posix()}"\n', encoding="utf-8")
    publication = {
        "plan_version": "A2",
        "source_snapshot_sha256": digest(snapshot),
        "status": "published",
        "ci_status": "passed",
        "merge_commit": "a" * 40,
        "tag_commit": "a" * 40,
        "tag": "v-test",
        "pull_request_url": "https://example.org/pr/1",
        "release_url": "https://example.org/release/v-test",
        "workshop_url": "https://example.org/workshop/1",
    }
    checksum = root / "tools/out/package.zip.sha256"
    checksum.write_text(
        f"{_ref(root, 'tools/out/package.zip')['sha256']}  package.zip\n", encoding="utf-8"
    )
    data["delivery"] = {
        **{
            key: publication[key]
            for key in (
                "merge_commit",
                "tag_commit",
                "tag",
                "pull_request_url",
                "release_url",
                "workshop_url",
            )
        },
        "status": "verified",
        "zip": _ref(root, "tools/out/package.zip"),
        "checksum": _ref(root, "tools/out/package.zip.sha256"),
        "publication_result": _write(root, "tools/out/publication.json", publication),
        "deployment": {
            "root": str(deployed),
            "launcher": {
                "path": str(launcher),
                "sha256": hashlib.sha256(launcher.read_bytes()).hexdigest(),
            },
        },
        "cleanup_result": _write(
            root, "tools/out/cleanup.json", {"status": "complete", "remaining": []}
        ),
        "workshop_copy": _write(root, "tools/out/workshop.json", {"text": "fixture"}),
        "rollback_instructions": _write(root, "tools/out/rollback.json", {"text": "fixture"}),
    }
    candidate = SimpleNamespace(root=root, data=data, stages=stage_map, inventory=inventory)
    _save(candidate)
    # Standard package schema is tested by distribution; this fixture isolates
    # the new delivery byte/identity checks, not a real distributable package.
    monkeypatch.setattr(receipts, "_package_contract", lambda _path: None)
    monkeypatch.setattr(
        situated_closeout.vanilla_inventory, "discover", lambda: candidate.inventory
    )
    monkeypatch.setattr(situated_closeout.distribution, "check_generation_lock", lambda: None)
    monkeypatch.setattr(
        situated_closeout.distribution, "read_production_files", lambda: {"common/fixture.txt": "x"}
    )
    monkeypatch.setattr(
        situated_closeout,
        "consumer_ir_owner_report",
        lambda: {"issues": [], "writer_count": 1, "field_owners": {"fixture": "owner"}},
    )
    monkeypatch.setattr(
        situated_closeout.repo_hygiene, "report", lambda _root: {"violation_count": 0}
    )
    return candidate


def test_S阶段完整证据图可区分工程和最终交付(architecture_candidate, capsys):
    candidate = architecture_candidate
    gate = situated_closeout.plan_gate(candidate.root)
    assert gate["ready"]
    assert gate["engineering_ready"]
    assert gate["pending"] == 3  # physical discovery pending is not implementation truth
    candidate.stages["S6"]["status"] = "in_progress"
    candidate.data["closed_stages"].remove("S6")
    candidate.data["delivery"] = {"status": "pending"}
    _save(candidate)
    arguments = ["--root", str(candidate.root), "--production", str(candidate.root / "mod")]
    assert situated_closeout.main([*arguments, "--require-engineering"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["engineering_complete"]
    assert not result["delivery_ready"]
    assert situated_closeout.main([*arguments, "--require-plan"]) == 1
    assert not json.loads(capsys.readouterr().out)["delivery_complete"]


def test_早期阶段可登记未知责任但S4以后不能闭合(architecture_candidate):
    c = architecture_candidate
    surface = replace(c.inventory.surfaces[0], actor_scope="unknown")
    c.inventory = replace(c.inventory, surfaces=(surface, *c.inventory.surfaces[1:]))
    assignment = c.data["native_scope"]["assignments"][0]
    assignment["context"] = json.loads(json.dumps(asdict(surface)))
    assignment["status"] = "pending"
    assignment["stage"] = "S4"
    assignment["evidence_ids"] = []
    _save(c)
    gate = situated_closeout.plan_gate(c.root)
    stages = gate["stage_receipts"]["stages"]
    assert stages["S0"]["ready"]
    assert stages["S1"]["ready"]
    assert gate["stage_receipts"]["native_scope"]["ready"]
    assert not gate["stage_receipts"]["native_scope"]["closed"]
    assert not stages["S4"]["ready"]
    assert gate["unknown_scopes"] == 1
    assert gate["stage"] == "S4-S6"
    assert not gate["engineering_ready"]
    assert not gate["ready"]


@pytest.mark.parametrize(
    "fault",
    [
        "missing_stage",
        "duplicate_stage",
        "extra_stage",
        "closed_set",
        "dependency",
        "dependency_hash",
        "old_plan",
        "plan_hash",
        "subplan_hash",
        "source_drift",
        "scope_hash",
        "denominator",
        "native_source_hash",
        "missing_assignment",
        "duplicate_assignment",
        "unsupported_legal",
        "pending_implementation",
        "unknown_scope",
        "parse_failure",
        "requirement_missing",
        "requirement_duplicate",
        "direction",
        "input_hash",
        "result_missing",
        "test_missing",
        "generated_field",
        "generic_pass",
        "unclosed_result",
        "zero_hides_pending",
        "unequal_output",
        "old_result",
        "missing_full_acceptance",
    ],
)
def test_A2严格门拒绝不完整或失效证据(architecture_candidate, fault):
    c = architecture_candidate
    evidence = c.stages["S2"]["evidence"][0]
    if fault == "missing_stage":
        c.data["stages"].remove(c.stages["S3"])
    elif fault == "duplicate_stage":
        c.data["stages"].append(c.stages["S3"])
    elif fault == "extra_stage":
        c.data["stages"].append({"stage_id": "D0", "status": "verified"})
    elif fault == "closed_set":
        c.data["closed_stages"].remove("S2")
    elif fault == "dependency":
        c.stages["S4"]["dependencies"] = ["S1"]
    elif fault == "dependency_hash":
        c.stages["S4"]["dependency_hashes"]["S2"] = "0" * 64
    elif fault == "old_plan":
        c.data["plan_version"] = "31.4"
    elif fault in {"plan_hash", "subplan_hash"}:
        c.data[fault.removesuffix("_hash")]["sha256"] = "0" * 64
    elif fault == "source_drift":
        (c.root / "src/pdx/fixture.py").write_text("changed=True\n", encoding="utf-8")
    elif fault == "scope_hash":
        c.stages["S2"]["scope_hash"] = "c" * 64
    elif fault == "denominator":
        c.data["native_scope"]["denominator"] = True
    elif fault == "native_source_hash":
        c.data["native_scope"]["source_hashes"] = {}
    elif fault == "missing_assignment":
        c.data["native_scope"]["assignments"].pop()
    elif fault == "duplicate_assignment":
        c.data["native_scope"]["assignments"].append(c.data["native_scope"]["assignments"][0])
    elif fault == "unsupported_legal":
        c.data["native_scope"]["assignments"][0]["status"] = "engine_unexposed"
    elif fault == "pending_implementation":
        c.data["native_scope"]["assignments"][0]["status"] = "pending"
    elif fault == "unknown_scope":
        c.inventory = replace(
            c.inventory,
            surfaces=(
                replace(c.inventory.surfaces[0], actor_scope="unknown"),
                *c.inventory.surfaces[1:],
            ),
        )
    elif fault == "parse_failure":
        c.inventory = replace(c.inventory, parse_failures=("bad.txt",))
    elif fault == "requirement_missing":
        c.stages["S2"]["requirements"].pop()
    elif fault == "requirement_duplicate":
        c.stages["S2"]["requirements"].append(c.stages["S2"]["requirements"][0])
    elif fault == "direction":
        evidence["direction"] = "B6"
    elif fault == "input_hash":
        c.stages["S2"]["input_hashes"]["src/pdx/fixture.py"] = "0" * 64
    elif fault == "result_missing":
        (c.root / evidence["result"]["path"]).unlink()
    elif fault == "test_missing":
        evidence["tests"][0]["nodeid"] = "tests/test_witness.py::test_nonexistent"
    elif fault == "generated_field":
        evidence["consumers"][0]["field"] = "nonexistent"
    else:
        if fault == "missing_full_acceptance":
            evidence = next(
                item
                for item in c.stages["S5"]["evidence"]
                if item["requirement_id"] == "full_regression_resources"
            )
        result = json.loads((c.root / evidence["result"]["path"]).read_text(encoding="utf-8"))
        if fault == "generic_pass":
            result["cases"] = []
        elif fault == "unclosed_result":
            result["open_items"] = ["actual functionality missing"]
        elif fault == "zero_hides_pending":
            result["pending_count"] = 0
            result["rows"] = [{"status": "pending"}]
        elif fault == "unequal_output":
            result["cases"][0]["generated"] = 99
        elif fault == "old_result":
            result["plan_version"] = "31.4"
        else:
            del result["full_acceptance"]
        evidence["result"] = _write(c.root, evidence["result"]["path"], result)
    _save(c)
    gate = situated_closeout.plan_gate(c.root)
    assert not gate["engineering_ready"]
    assert not gate["ready"]
    assert not gate["business_complete"]


@pytest.mark.parametrize(
    "fault",
    [
        "missing_zip",
        "bad_zip_hash",
        "bad_checksum",
        "tag_commit",
        "ci",
        "old_publication",
        "deployment",
        "residual",
        "launcher",
        "cleanup",
    ],
)
def test_S6必须有实际交付字节与发布身份(architecture_candidate, fault):
    c = architecture_candidate
    delivery = c.data["delivery"]
    if fault == "missing_zip":
        (c.root / delivery["zip"]["path"]).unlink()
    elif fault == "bad_zip_hash":
        delivery["zip"]["sha256"] = "0" * 64
    elif fault == "bad_checksum":
        path = delivery["checksum"]["path"]
        (c.root / path).write_text("0" * 64 + "  package.zip\n", encoding="utf-8")
        delivery["checksum"] = _ref(c.root, path)
    elif fault == "tag_commit":
        delivery["tag_commit"] = "b" * 40
    elif fault in {"ci", "old_publication"}:
        result = json.loads(
            (c.root / delivery["publication_result"]["path"]).read_text(encoding="utf-8")
        )
        result["ci_status" if fault == "ci" else "plan_version"] = (
            "failed" if fault == "ci" else "31.4"
        )
        delivery["publication_result"] = _write(
            c.root, delivery["publication_result"]["path"], result
        )
    elif fault == "deployment":
        (c.root / "deployment/common/fixture.txt").write_bytes(b"wrong bytes")
    elif fault == "residual":
        (c.root / "deployment/old.txt").write_bytes(b"old")
    elif fault == "launcher":
        (c.root / "launcher.mod").write_text('path="wrong"\n', encoding="utf-8")
        delivery["deployment"]["launcher"]["sha256"] = hashlib.sha256(
            (c.root / "launcher.mod").read_bytes()
        ).hexdigest()
    else:
        delivery["cleanup_result"] = _write(
            c.root,
            delivery["cleanup_result"]["path"],
            {"status": "complete", "remaining": ["old.txt"]},
        )
    _save(c)
    gate = situated_closeout.plan_gate(c.root)
    assert gate["engineering_ready"]
    assert not gate["ready"]
    assert gate["stage_receipts"]["stages"]["S6"]["issues"]


def test_旧D收据或散文verified不能关闭A2(architecture_candidate):
    c = architecture_candidate
    (c.root / receipts.RECEIPT_PATH).unlink()
    for index in range(15):
        (c.root / f"docs/design/exec/D{index}-结果.md").write_text(
            'status: verified\n{"status":"verified"}\n', encoding="utf-8"
        )
    gate = situated_closeout.plan_gate(c.root)
    assert not gate["engineering_ready"]
    assert gate["stage_receipts"]["missing_receipts"] == list(receipts.STAGE_DEPENDENCIES)


def test_原版缺失时严格门失败并公开环境原因(architecture_candidate, monkeypatch):
    def unavailable():
        raise FileNotFoundError("locked native unavailable")

    monkeypatch.setattr(situated_closeout.vanilla_inventory, "discover", unavailable)
    gate = situated_closeout.plan_gate(architecture_candidate.root)
    assert not gate["engineering_ready"]
    assert gate["discovered"] is None
    assert "locked native unavailable" in gate["reason"]
