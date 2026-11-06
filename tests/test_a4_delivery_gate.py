"""Only gate wiring is simulated here; live transport semantics have separate tests."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from pdx import config, publishing_contract
from tools.ci import a4_delivery, a4_scope


@pytest.fixture
def gate(tmp_path, monkeypatch):
    calls = []
    root = tmp_path
    monkeypatch.setattr(config, "REPO", root)
    for path in a4_scope.GATE_INPUTS:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"controlled source\n")
    (root / "tools/out").mkdir(parents=True)
    request_path = "tools/out/delivery.json"
    production_files = {
        "docs/publishing/workshop.toml": b"current workshop configuration\n",
        "mod/common/ai_strategies/00_default_strategy.txt": b"current generated Mod file\n",
    }
    for path, raw in production_files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    request = {
        "mode": "live",
        "run_dir": "tools/out/publish-run",
        "production_snapshot": {path: a4_scope.sha(raw) for path, raw in production_files.items()},
    }
    (root / "tools/out/readback").mkdir()
    (root / request_path).write_text(json.dumps(request), encoding="utf8")
    # Shape/semantic validation belongs to the real verifier's 113 tests. This
    # boundary isolates routing and does not claim this tiny input is a sidecar.
    monkeypatch.setattr(a4_delivery, "validate_request", lambda value: value)
    git_reader = object()
    github_reader = object()
    workshop_reader = object()

    def git_factory(path):
        calls.append(("git", path))
        return git_reader

    def github_factory(path):
        calls.append(("github", path))
        return github_reader

    def workshop_factory(item, output):
        calls.append(("workshop", item, output))
        assert output.is_dir()
        assert output.is_relative_to(root / "tools/out")
        return workshop_reader

    monkeypatch.setattr(a4_delivery, "GitReader", git_factory)
    monkeypatch.setattr(a4_delivery, "GitHubReader", SimpleNamespace(from_git=github_factory))
    monkeypatch.setattr(a4_delivery, "WorkshopReader", workshop_factory)
    monkeypatch.setattr(
        publishing_contract, "publication_config", lambda _path: {"published_file_id": 1234}
    )
    result = {
        "mode": "live",
        "status": "verified",
        "evidence": "live",
        "delivery_complete": True,
    }

    def verify(path, value, **kwargs):
        calls.append(("verify", path, value, kwargs))
        assert kwargs["git"] is git_reader
        assert kwargs["github"] is github_reader
        assert kwargs["workshop"] is workshop_reader
        return result

    monkeypatch.setattr(a4_delivery, "verify_delivery", verify)
    return SimpleNamespace(
        root=root, path=request_path, request=request, calls=calls, result=result, verify=verify
    )


@pytest.mark.parametrize("stage", ["A4-8", "all"])
def test_delivery_gate_requires_explicit_request_before_external_calls(gate, stage):
    with pytest.raises(ValueError, match="explicit --delivery-request"):
        a4_scope.delivery_gate(stage, gate.root)
    assert gate.calls == []


@pytest.mark.parametrize("number", range(8))
def test_delivery_before_stage_eight_never_reads_request_or_creates_readers(gate, number):
    result = a4_scope.delivery_gate(
        f"A4-{number}", gate.root, request_path="../missing-unsafe.json"
    )
    assert result == {"status": "pending", "evidence": "not_requested", "delivery_complete": False}
    assert gate.calls == []


def test_delivery_offline_request_never_constructs_live_readers(gate):
    (gate.root / gate.path).write_text('{"mode":"offline_fixture"}', encoding="utf8")
    with pytest.raises(ValueError, match="requires live"):
        a4_scope.delivery_gate(
            "all", gate.root, request_path=gate.path, output_path="tools/out/readback"
        )
    assert gate.calls == []


@pytest.mark.parametrize(
    "path", ["../outside.json", "/outside.json", "tools\\out\\x.json", "tools/out/./x.json"]
)
def test_delivery_request_paths_are_canonical_and_confined(gate, path):
    with pytest.raises(ValueError, match=r"safe relative path|request must be below"):
        a4_scope.delivery_gate("A4-8", gate.root, request_path=path)
    assert gate.calls == []


@pytest.mark.parametrize("raw", [b'{"mode":"live","mode":"live"}', b'{"mode":NaN}'])
def test_delivery_request_uses_strict_json(gate, raw):
    (gate.root / gate.path).write_bytes(raw)
    with pytest.raises(ValueError, match=r"JSON|sidecar|duplicate"):
        a4_scope.delivery_gate(
            "A4-8", gate.root, request_path=gate.path, output_path="tools/out/readback"
        )
    assert gate.calls == []


def test_delivery_request_size_is_bounded_before_external_calls(gate, monkeypatch):
    monkeypatch.setattr(a4_delivery, "MAX_JSON_BYTES", 3)
    with pytest.raises(ValueError, match="oversized delivery input"):
        a4_scope.delivery_gate(
            "A4-8", gate.root, request_path=gate.path, output_path="tools/out/readback"
        )
    assert gate.calls == []


@pytest.mark.parametrize(
    "output", [None, "tools/out/missing", "docs/output", "tools/out/publish-run"]
)
def test_delivery_output_requires_explicit_empty_separate_precreated_directory(gate, output):
    (gate.root / "tools/out/publish-run").mkdir()
    with pytest.raises(ValueError, match=r"delivery-output|precreated empty|separate"):
        a4_scope.delivery_gate("all", gate.root, request_path=gate.path, output_path=output)
    assert gate.calls == []


def test_delivery_output_refuses_existing_diagnostics(gate):
    (gate.root / "tools/out/readback/old-response.json").write_text("{}", encoding="utf8")
    with pytest.raises(ValueError, match="precreated empty"):
        a4_scope.delivery_gate(
            "all", gate.root, request_path=gate.path, output_path="tools/out/readback"
        )
    assert gate.calls == []


def test_delivery_gate_passes_independent_userdir_without_sidecar_authorization(gate):
    alternate = gate.root / "controller-authorized-userdir"
    result = a4_scope.delivery_gate(
        "all",
        gate.root,
        request_path=gate.path,
        output_path="tools/out/readback",
        authorized_userdir=alternate,
    )
    verify_call = next(row for row in gate.calls if row[0] == "verify")
    assert verify_call[3]["authorized_userdir"] == alternate
    assert gate.calls[:2] == [("git", gate.root), ("github", gate.root)]
    assert next(row for row in gate.calls if row[0] == "workshop")[1] == 1234
    assert result["request"]["sha256"] == a4_scope.sha((gate.root / gate.path).read_bytes())
    assert result["checked_input_count"] == len(a4_scope.GATE_INPUTS) + 3


def test_delivery_gate_uses_config_default_without_copying_sidecar_userdir(gate):
    gate.request["userdir"] = str(gate.root / "untrusted-sidecar-target")
    (gate.root / gate.path).write_text(json.dumps(gate.request), encoding="utf8")
    a4_scope.delivery_gate(
        "A4-8", gate.root, request_path=gate.path, output_path="tools/out/readback"
    )
    assert next(row for row in gate.calls if row[0] == "verify")[3]["authorized_userdir"] is None


@pytest.mark.parametrize(
    "patch",
    [
        {"mode": "offline_fixture"},
        {"status": "pending"},
        {"evidence": "offline_fixture"},
        {"delivery_complete": False},
        {"delivery_complete": 1},
    ],
)
def test_delivery_result_must_confirm_every_live_completion_field(gate, patch):
    gate.result.update(patch)
    with pytest.raises(ValueError, match="verified actual live"):
        a4_scope.delivery_gate(
            "all", gate.root, request_path=gate.path, output_path="tools/out/readback"
        )


@pytest.mark.parametrize("target", ["request", "source"])
def test_delivery_gate_rejects_input_drift_during_external_verification(gate, monkeypatch, target):
    path = gate.path if target == "request" else a4_scope.GATE_INPUTS[0]

    def drift(root, request, **kwargs):
        result = gate.verify(root, request, **kwargs)
        (gate.root / path).write_bytes(b"changed after verification started\n")
        return result

    monkeypatch.setattr(a4_delivery, "verify_delivery", drift)
    with pytest.raises(ValueError, match="input changed during verification"):
        a4_scope.delivery_gate(
            "all", gate.root, request_path=gate.path, output_path="tools/out/readback"
        )


def test_delivery_gate_rechecks_product_sources_before_creating_readers(gate):
    sources = a4_scope.Sources(gate.root)
    sources.read(a4_scope.GATE_INPUTS[0])
    (gate.root / a4_scope.GATE_INPUTS[0]).write_bytes(b"drifted since product validation\n")
    with pytest.raises(ValueError, match="input identity conflict"):
        a4_scope.delivery_gate(
            "all",
            gate.root,
            request_path=gate.path,
            output_path="tools/out/readback",
            sources=sources,
        )
    assert gate.calls == []


@pytest.mark.parametrize(
    "path",
    ["docs/publishing/workshop.toml", "mod/common/ai_strategies/00_default_strategy.txt"],
)
def test_delivery_snapshot_files_are_rechecked_after_verifier_readback(gate, monkeypatch, path):
    # These are real production path classes outside Sources/GATE_INPUTS. Drift
    # persists after the verifier has checked Git bytes and performed readback.
    def drift(root, request, **kwargs):
        result = gate.verify(root, request, **kwargs)
        (root / path).write_bytes(b"changed during Steam readback and left changed\n")
        return result

    monkeypatch.setattr(a4_delivery, "verify_delivery", drift)
    with pytest.raises(ValueError, match=f"input changed during verification: {path}"):
        a4_scope.delivery_gate(
            "all", gate.root, request_path=gate.path, output_path="tools/out/readback"
        )
    assert any(row[0] == "verify" for row in gate.calls)


def test_delivery_snapshot_mismatch_fails_before_constructing_readers(gate):
    (gate.root / "docs/publishing/workshop.toml").write_bytes(b"changed before delivery\n")
    with pytest.raises(ValueError, match="input changed during verification"):
        a4_scope.delivery_gate(
            "all", gate.root, request_path=gate.path, output_path="tools/out/readback"
        )
    assert gate.calls == []


def test_delivery_request_cannot_replace_previously_checked_source_identity(gate):
    sources = a4_scope.Sources(gate.root)
    sources.read(gate.path)
    gate.request["run_dir"] = "tools/out/another-fixed-publish-run"
    (gate.root / gate.path).write_text(json.dumps(gate.request), encoding="utf8")
    with pytest.raises(ValueError, match=f"input identity conflict: {gate.path}"):
        a4_scope.delivery_gate(
            "all",
            gate.root,
            request_path=gate.path,
            output_path="tools/out/readback",
            sources=sources,
        )
    assert gate.calls == []


@pytest.mark.parametrize("overlap", ["source", "gate", "request"])
def test_delivery_snapshot_conflicting_overlap_is_never_overwritten(gate, overlap):
    sources = a4_scope.Sources(gate.root)
    if overlap == "source":
        path = "docs/publishing/workshop.toml"
        sources.read(path)
    elif overlap == "gate":
        path = a4_scope.GATE_INPUTS[0]
    else:
        path = gate.path
    gate.request["production_snapshot"][path] = "0" * 64
    (gate.root / gate.path).write_text(json.dumps(gate.request), encoding="utf8")
    with pytest.raises(ValueError, match=f"input identity conflict: {path}"):
        a4_scope.delivery_gate(
            "all",
            gate.root,
            request_path=gate.path,
            output_path="tools/out/readback",
            sources=sources,
        )
    assert gate.calls == []


def test_delivery_equal_overlap_keeps_one_identity_and_still_passes(gate):
    sources = a4_scope.Sources(gate.root)
    gate_path = a4_scope.GATE_INPUTS[0]
    gate.request["production_snapshot"][gate_path] = a4_scope.sha(
        (gate.root / gate_path).read_bytes()
    )
    (gate.root / gate.path).write_text(json.dumps(gate.request), encoding="utf8")
    for path in [gate.path, gate_path, *gate.request["production_snapshot"]]:
        sources.read(path)
    result = a4_scope.delivery_gate(
        "all", gate.root, request_path=gate.path, output_path="tools/out/readback", sources=sources
    )
    assert result["status"] == "verified"
    assert result["checked_input_count"] == len(a4_scope.GATE_INPUTS) + 3


def test_delivery_request_schema_is_not_bypassed_by_gate(gate, monkeypatch):
    def reject(_request):
        raise ValueError("strict sidecar schema rejected")

    monkeypatch.setattr(a4_delivery, "validate_request", reject)
    with pytest.raises(ValueError, match="strict sidecar schema rejected"):
        a4_scope.delivery_gate(
            "all", gate.root, request_path=gate.path, output_path="tools/out/readback"
        )
    assert gate.calls == []


def test_delivery_cli_forwards_explicit_path_without_userdir_override(gate, monkeypatch, capsys):
    ledger = gate.root / "ledger.json"
    ledger.write_text("{}", encoding="utf8")
    monkeypatch.setattr(a4_scope, "ROOT", gate.root)
    received = []

    def validate(data, root, **kwargs):
        received.append((data, root, kwargs))
        return {"delivery": "pending"}

    monkeypatch.setattr(a4_scope, "validate", validate)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "a4_scope",
            "validate",
            "--ledger",
            "ledger.json",
            "--stage",
            "all",
            "--delivery-request",
            gate.path,
            "--delivery-output",
            "tools/out/readback",
        ],
    )
    assert a4_scope.main() == 0
    assert received == [
        (
            {},
            gate.root,
            {
                "stage": "all",
                "check_installation": True,
                "delivery_request": gate.path,
                "delivery_output": "tools/out/readback",
            },
        )
    ]
    assert json.loads(capsys.readouterr().out)["delivery"] == "pending"


def test_delivery_gate_inputs_include_verifier_and_its_both_test_layers():
    assert {
        "tools/ci/a4_delivery.py",
        "tests/test_a4_delivery.py",
        "tests/test_a4_delivery_gate.py",
    } <= set(a4_scope.GATE_INPUTS)


def test_delivery_cli_refuses_ledger_drift_after_validation(gate, monkeypatch):
    ledger = gate.root / "ledger.json"
    ledger.write_text("{}", encoding="utf8")
    monkeypatch.setattr(a4_scope, "ROOT", gate.root)

    def validate(_data, _root, **_kwargs):
        ledger.write_text('{"changed":true}', encoding="utf8")
        return {"delivery": "verified"}

    monkeypatch.setattr(a4_scope, "validate", validate)
    monkeypatch.setattr(sys, "argv", ["a4_scope", "validate", "--ledger", "ledger.json"])
    assert a4_scope.main() == 1
