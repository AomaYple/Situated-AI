"""Real Git mutations are confined to a disposable, test-owned repository."""

from __future__ import annotations

import subprocess

import pytest

from tools.ci import a4_history as history
from tools.ci import a4_scope as gate


def test_real_git_add_delete_rename_and_untracked(tmp_path, monkeypatch) -> None:
    root = tmp_path

    def run(*args):
        result = subprocess.run(["git", *args], cwd=root, capture_output=True, check=True)
        return result.stdout

    run("init", "-q")
    run("config", "user.name", "A4 isolated fixture")
    run("config", "user.email", "fixture@example.invalid")
    source = root / "src/pdx"
    source.mkdir(parents=True)
    (source / "old.py").write_bytes(b"old\n")
    (source / "rename.py").write_bytes(b"rename\n")
    run("add", ".")
    run("commit", "-qm", "base")
    base = run("rev-parse", "HEAD").decode().strip()
    (source / "old.py").write_bytes(b"candidate\n")
    run("commit", "-qam", "candidate")
    candidate = run("rev-parse", "HEAD").decode().strip()
    (source / "added.py").write_bytes(b"tracked after candidate\n")
    run("add", ".")
    run("commit", "-qm", "anchor")
    anchor = run("rev-parse", "HEAD").decode().strip()
    monkeypatch.setattr(history, "ANCHOR", anchor)
    # Reuse the real read-only gate adapter on this independent repository.
    (source / "old.py").unlink()
    (source / "rename.py").rename(source / "renamed.py")
    run("add", "-A")
    delta = {item["id"]: item for item in history.changes(gate.git, root, candidate, base)}
    assert delta["production_delta:src/pdx/added.py"]["checkpoint"] == {
        "presence": "absent",
        "hashes": [],
    }
    assert delta["production_delta:src/pdx/old.py"]["current"] == {
        "presence": "absent",
        "hashes": [],
    }
    assert delta["production_delta:src/pdx/rename.py"]["current"]["presence"] == "absent"
    assert delta["production_delta:src/pdx/renamed.py"]["checkpoint"]["presence"] == "absent"
    assert history.state(b"") == {"presence": "present", "hashes": [gate.sha(b"")]}
    manifest, objects = history.history(gate.git, root, candidate, base, anchor=anchor)
    assert "src/pdx/old.py" in manifest["paths"]
    assert gate.sha(b"old\n") in objects
    history.write_history(gate.git, root, candidate, base)
    assert history.verify_history(gate.Sources(root), gate.git, candidate, base)["registered_paths"]
    (source / "transient.py").write_bytes(b"historical production\n")
    run("add", "-A")
    run("commit", "-qm", "later addition and rename")
    (source / "transient.py").unlink()
    run("add", "-A")
    run("commit", "-qm", "later retirement")
    historical = {item["id"]: item for item in history.changes(gate.git, root, candidate, base)}
    assert historical["production_delta:src/pdx/transient.py"]["checkpoint"]["presence"] == "absent"
    assert historical["production_delta:src/pdx/transient.py"]["current"]["presence"] == "absent"
    history.write_history(gate.git, root, candidate, base)
    assert (
        "src/pdx/transient.py"
        in history.verify_history(gate.Sources(root), gate.git, candidate, base)["registered_paths"]
    )
    (source / "untracked.py").write_bytes(b"new production\n")
    with pytest.raises(ValueError, match="untracked production candidate"):
        history.changes(gate.git, root, candidate, base)


@pytest.mark.parametrize(
    "value", [{"presence": "absent", "hashes": ["0" * 64]}, {"presence": "present", "hashes": []}]
)
def test_absence_never_uses_placeholder_hash(value) -> None:
    with pytest.raises(ValueError, match="presence/hash"):
        history.validate_state(value)


def test_real_merge_resolution_and_merge_only_retirement_survive(tmp_path, monkeypatch) -> None:
    def run(*args, expected=0):
        process = subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, check=False)
        assert process.returncode == expected, process.stderr.decode("utf8", "replace")
        return process.stdout

    run("init", "-q")
    run("config", "user.name", "isolated merge fixture")
    run("config", "user.email", "fixture@example.invalid")
    source = tmp_path / "src/pdx"
    source.mkdir(parents=True)
    conflict = source / "conflict.py"
    conflict.write_bytes(b"base\n")
    run("add", ".")
    run("commit", "-qm", "base")
    base = run("rev-parse", "HEAD").decode().strip()
    main = run("symbolic-ref", "--short", "HEAD").decode().strip()
    (source / "candidate.py").write_bytes(b"candidate\n")
    run("add", ".")
    run("commit", "-qm", "candidate anchor")
    anchor = run("rev-parse", "HEAD").decode().strip()
    monkeypatch.setattr(history, "ANCHOR", anchor)
    run("checkout", "-qb", "side")
    conflict.write_bytes(b"side\n")
    run("commit", "-qam", "side change")
    run("checkout", "-q", main)
    conflict.write_bytes(b"main\n")
    run("commit", "-qam", "main change")
    run("merge", "--no-commit", "side", expected=1)
    conflict.write_bytes(b"merge resolution exists in neither parent\n")
    merged_path = source / "merge_only.py"
    merged_path.write_bytes(b"created only by merge resolution\n")
    run("add", "-A")
    run("commit", "-qm", "actual resolved merge")
    merge = run("rev-parse", "HEAD").decode().strip()
    assert len(run("rev-list", "--parents", "-n", "1", merge).split()) == 3
    merged_path.unlink()
    conflict.write_bytes(b"later content\n")
    run("add", "-A")
    run("commit", "-qm", "retire merge-only content")
    assert merge in history.revisions(gate.git, tmp_path, anchor)
    manifest, objects = history.history(gate.git, tmp_path, anchor, base, anchor=anchor)
    assert "src/pdx/merge_only.py" in manifest["registered_paths"]
    assert (
        objects[gate.sha(b"created only by merge resolution\n")]
        == b"created only by merge resolution\n"
    )
    assert (
        objects[gate.sha(b"merge resolution exists in neither parent\n")]
        == b"merge resolution exists in neither parent\n"
    )
    delta = {item["id"]: item for item in history.changes(gate.git, tmp_path, anchor, base)}
    assert delta["production_delta:src/pdx/merge_only.py"]["current"]["presence"] == "absent"
    history.write_history(gate.git, tmp_path, anchor, base)
    assert (
        history.verify_history(gate.Sources(tmp_path), gate.git, anchor, base)["paths"][
            "src/pdx/merge_only.py"
        ][merge]["presence"]
        == "present"
    )
