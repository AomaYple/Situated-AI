"""Real Git mutations are confined to a disposable, test-owned repository."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

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


@pytest.fixture
def frozen_history(tmp_path, monkeypatch):
    """All Git mutations and generated objects belong to this disposable repository."""

    def run(*args, expected=0):
        process = subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, check=False)
        assert process.returncode == expected, process.stderr.decode("utf8", "replace")
        return process.stdout

    def commit(message):
        run("add", "-A")
        run("commit", "-qm", message)
        return run("rev-parse", "HEAD").decode().strip()

    run("init", "-q")
    run("config", "user.name", "history freeze fixture")
    run("config", "user.email", "fixture@example.invalid")
    run("config", "commit.gpgsign", "false")
    run("config", "core.autocrlf", "false")
    source = tmp_path / "src/pdx/input.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"base\n")
    base = commit("base")
    main = run("symbolic-ref", "--short", "HEAD").decode().strip()
    (source.parent / "candidate.py").write_bytes(b"candidate\n")
    anchor = commit("candidate anchor")
    monkeypatch.setattr(history, "ANCHOR", anchor)
    run("checkout", "-qb", "topic")
    source.write_bytes(b"frozen production\n")
    head = commit("final production H")
    history.write_history(gate.git, tmp_path, anchor, base)
    manifest = (tmp_path / history.HISTORY_PATH).read_bytes()
    evidence = commit("history evidence E")

    def verify():
        return history.verify_history(gate.Sources(tmp_path), gate.git, anchor, base)

    return SimpleNamespace(
        root=tmp_path,
        run=run,
        commit=commit,
        source=source,
        base=base,
        anchor=anchor,
        head=head,
        evidence=evidence,
        main=main,
        manifest=manifest,
        verify=verify,
    )


def test_frozen_history_survives_real_production_merge_without_self_reference(frozen_history):
    f = frozen_history
    assert f.verify()["freeze_head"] == f.head
    f.run("checkout", "-q", f.main)
    f.run("merge", "--no-ff", "--no-edit", "topic")
    merge = f.run("rev-parse", "HEAD").decode().strip()
    assert len(f.run("rev-list", "--parents", "-n", "1", merge).split()) == 3
    # The merge changes production versus main's parent but introduces no new tree.
    assert f.run("diff-tree", "-m", "-r", "--name-only", merge, "--", *history.PRODUCTION)
    assert f.verify()["freeze_head"] == f.head
    assert (f.root / history.HISTORY_PATH).read_bytes() == f.manifest


@pytest.mark.parametrize("fault", ["content", "add_delete", "delete_restore", "mode"])
def test_frozen_tail_rejects_intermediate_change_even_when_head_tree_restored(
    frozen_history, fault
):
    f = frozen_history
    if fault == "content":
        f.source.write_bytes(b"transient bytes absent from HEAD\n")
        f.commit("transient bytes")
    elif fault == "add_delete":
        (f.source.parent / "transient.py").write_bytes(b"transient member\n")
        f.commit("transient member")
    elif fault == "delete_restore":
        f.source.unlink()
        f.commit("transient absence")
    else:
        f.run("update-index", "--chmod=+x", "src/pdx/input.py")
        f.run("commit", "-qm", "transient executable mode")
    f.run("read-tree", "--reset", "-u", f.evidence)
    f.run("commit", "-qm", "restore complete frozen tree")
    assert history.tree_entries(gate.git, f.root, "HEAD") == history.tree_entries(
        gate.git, f.root, f.head
    )
    with pytest.raises(ValueError, match="tail changed"):
        f.verify()


def test_new_reachable_side_branch_before_anchor_is_not_hidden(frozen_history):
    f = frozen_history
    f.run("checkout", "-qb", "old-side", f.base)
    f.source.write_bytes(b"side bytes outside anchor ancestry\n")
    side = f.commit("old side production")
    f.run("checkout", "-q", "topic")
    f.run("merge", "--no-ff", "-s", "ours", "--no-edit", "old-side")
    with pytest.raises(ValueError, match="tail changed"):
        f.verify()
    history.write_history(gate.git, f.root, f.anchor, f.base)
    refreshed = f.verify()
    assert refreshed["paths"]["src/pdx/input.py"][side]["hashes"] == [
        gate.sha(b"side bytes outside anchor ancestry\n")
    ]
    assert f.run("show", f.evidence + ":" + history.HISTORY_PATH) == f.manifest


def test_new_unrelated_root_bytes_are_retained_after_explicit_refresh(frozen_history):
    f = frozen_history
    f.run("checkout", "--orphan", "unrelated-root")
    f.run("rm", "-rf", ".")
    f.source.parent.mkdir(parents=True, exist_ok=True)
    f.source.write_bytes(b"unrelated root production bytes\n")
    side = f.commit("new unrelated root")
    f.run("checkout", "-q", "topic")
    f.run(
        "merge",
        "--allow-unrelated-histories",
        "--no-ff",
        "-s",
        "ours",
        "--no-edit",
        "unrelated-root",
    )
    with pytest.raises(ValueError, match="tail changed"):
        f.verify()
    history.write_history(gate.git, f.root, f.anchor, f.base)
    assert f.verify()["paths"]["src/pdx/input.py"][side]["hashes"] == [
        gate.sha(b"unrelated root production bytes\n")
    ]


def test_frozen_tail_rejects_merge_only_resolution_then_restoration(frozen_history):
    f = frozen_history
    f.run("checkout", "-qb", "same-production-side", f.evidence)
    (f.root / "side-receipt.md").write_bytes(b"evidence only\n")
    f.commit("side evidence")
    f.run("checkout", "-q", "topic")
    (f.root / "topic-receipt.md").write_bytes(b"evidence only\n")
    f.commit("topic evidence")
    f.run("merge", "--no-ff", "--no-commit", "same-production-side")
    f.source.write_bytes(b"bytes exist only in merge resolution\n")
    merge = f.commit("merge-only production resolution")
    f.run("read-tree", "--reset", "-u", f.evidence)
    f.run("commit", "-qm", "restore frozen tree")
    with pytest.raises(ValueError, match="tail changed"):
        f.verify()
    history.write_history(gate.git, f.root, f.anchor, f.base)
    assert f.verify()["paths"]["src/pdx/input.py"][merge]["hashes"] == [
        gate.sha(b"bytes exist only in merge resolution\n")
    ]


@pytest.mark.parametrize("kind", ["symlink", "gitlink"])
def test_frozen_tail_rejects_unsupported_git_tree_members(frozen_history, kind):
    f = frozen_history
    if kind == "symlink":
        blob = f.run("rev-parse", f.head + ":src/pdx/input.py").decode().strip()
        f.run("update-index", "--add", "--cacheinfo", "120000", blob, "src/pdx/linked.py")
    else:
        f.run("update-index", "--add", "--cacheinfo", "160000", f.head, "src/pdx/submodule")
    f.run("commit", "-qm", "unsupported production member")
    with pytest.raises(ValueError, match="non-file object"):
        f.verify()


@pytest.mark.parametrize(
    "fault", ["invalid", "missing", "nonancestor", "before_anchor", "rollback"]
)
def test_freeze_head_must_be_a_real_bounded_ancestor(frozen_history, fault):
    f = frozen_history
    manifest = gate.Sources(f.root).json(history.HISTORY_PATH)
    if fault == "invalid":
        manifest["freeze_head"] = "HEAD"
    elif fault == "missing":
        manifest["freeze_head"] = "0" * 40
    elif fault == "before_anchor":
        manifest["freeze_head"] = f.base
    elif fault == "rollback":
        manifest["freeze_head"] = f.anchor
    else:
        f.run("checkout", "-qb", "unmerged-side", f.base)
        (f.root / "side.md").write_bytes(b"unmerged evidence\n")
        manifest["freeze_head"] = f.commit("not an ancestor")
        f.run("checkout", "-q", "topic")
    history.write_json(f.root / history.HISTORY_PATH, manifest)
    with pytest.raises(ValueError):
        f.verify()


def test_frozen_history_does_not_archive_dirty_worktree(frozen_history):
    f = frozen_history
    f.source.write_bytes(b"uncommitted current production\n")
    assert f.verify()["freeze_head"] == f.head
    delta = {row["id"]: row for row in history.changes(gate.git, f.root, f.anchor, f.base)}
    assert delta["production_delta:src/pdx/input.py"]["current"]["hashes"] == [
        gate.sha(b"uncommitted current production\n")
    ]
    history.write_history(gate.git, f.root, f.anchor, f.base)
    refreshed = f.verify()
    original = json.loads(f.manifest)
    assert refreshed["freeze_head"] == f.evidence
    assert refreshed["paths"] == original["paths"]
    assert refreshed["objects"] == original["objects"]
    assert gate.sha(b"uncommitted current production\n") not in refreshed["objects"]
    (f.source.parent / "untracked.py").write_bytes(b"not registered\n")
    with pytest.raises(ValueError, match="untracked production candidate"):
        history.changes(gate.git, f.root, f.anchor, f.base)


@pytest.mark.parametrize("fault", ["missing_revision", "object_corruption", "unknown_schema"])
def test_frozen_history_still_checks_complete_manifest_and_original_objects(frozen_history, fault):
    f = frozen_history
    manifest = gate.Sources(f.root).json(history.HISTORY_PATH)
    if fault == "missing_revision":
        for states in manifest["paths"].values():
            states.pop(f.head)
    elif fault == "unknown_schema":
        manifest["schema"] = 3
    else:
        item = next(iter(manifest["objects"].values()))
        (f.root / item["path"]).write_bytes(b"corrupt frozen original\n")
    history.write_json(f.root / history.HISTORY_PATH, manifest)
    with pytest.raises(ValueError):
        f.verify()


def test_schema_one_keeps_strict_legacy_contract_and_original_bytes(frozen_history):
    f = frozen_history
    manifest, objects = history.history(gate.git, f.root, f.anchor, f.base, anchor=f.anchor)
    manifest["objects"] = {}
    for digest, raw in objects.items():
        path = f"research/vanilla-ai/1.15.0/discovery/history-objects/{digest}.gz"
        packed = history.pack(raw)
        (f.root / path).write_bytes(packed)
        manifest["objects"][digest] = {"path": path, "sha256": gate.sha(packed), "bytes": len(raw)}
    history.write_json(f.root / history.HISTORY_PATH, manifest)
    legacy = (f.root / history.HISTORY_PATH).read_bytes()
    assert f.verify()["schema"] == 1
    assert (f.root / history.HISTORY_PATH).read_bytes() == legacy
    f.source.write_bytes(b"new committed production\n")
    f.commit("new production after legacy receipt")
    with pytest.raises(ValueError, match="membership/edge"):
        f.verify()
    assert (f.root / history.HISTORY_PATH).read_bytes() == legacy


@pytest.mark.parametrize("limit", ["revisions", "tree_bytes", "tree_entries", "tail_cost"])
def test_frozen_tail_has_explicit_resource_limits(frozen_history, monkeypatch, limit):
    f = frozen_history
    if limit == "revisions":
        monkeypatch.setattr(history, "MAX_REVISIONS", 0)
    elif limit == "tree_bytes":
        monkeypatch.setattr(history, "MAX_TREE_BYTES", 1)
    elif limit == "tree_entries":
        monkeypatch.setattr(history, "MAX_TREE_ENTRIES", 0)
    else:
        monkeypatch.setattr(history, "MAX_TAIL_ENTRIES", 1)
    with pytest.raises(ValueError, match="limit"):
        f.verify()


def test_frozen_history_rejects_head_moving_during_verification(frozen_history):
    f = frozen_history
    calls = 0

    def moving_git(root, *arguments):
        nonlocal calls
        if arguments == ("rev-parse", "--verify", "HEAD^{commit}"):
            calls += 1
            if calls == 2:
                return (f.head + "\n").encode()
        return gate.git(root, *arguments)

    with pytest.raises(ValueError, match="HEAD changed"):
        history.verify_history(gate.Sources(f.root), moving_git, f.anchor, f.base)


@pytest.mark.parametrize("location", ["tail", "before_freeze"])
def test_complete_mainline_cannot_hide_shallow_side_parent(frozen_history, location):
    f = frozen_history
    f.run("checkout", "-qb", "hidden-side", f.anchor)
    f.source.write_bytes(b"hidden intermediate side production B\n")
    hidden = f.commit("side X with different production")
    f.source.write_bytes(b"frozen production\n")
    boundary = f.commit("side Y restores production A")
    f.run("checkout", "-q", "topic")
    f.run("merge", "--no-ff", "-s", "ours", "--no-edit", "hidden-side")
    if location == "before_freeze":
        history.write_history(gate.git, f.root, f.anchor, f.base)
        f.commit("complete history records side X before freeze")
    # This test-owned boundary hides X even while both mainline ancestry checks
    # remain true and the physical X commit object is still present.
    (f.root / ".git/shallow").write_text(boundary + "\n", encoding="ascii")
    f.run("merge-base", "--is-ancestor", f.anchor, f.head)
    f.run("merge-base", "--is-ancestor", f.head, "HEAD")
    assert hidden.encode() not in f.run("rev-list", f.head + "..HEAD").splitlines()
    assert f.run("cat-file", "-t", hidden).strip() == b"commit"
    original = (f.root / history.HISTORY_PATH).read_bytes()
    with pytest.raises(ValueError, match="complete non-shallow"):
        f.verify()
    with pytest.raises(ValueError, match="complete non-shallow"):
        history.write_history(gate.git, f.root, f.anchor, f.base)
    assert (f.root / history.HISTORY_PATH).read_bytes() == original


def test_nonshallow_repository_with_missing_side_parent_is_rejected(frozen_history):
    f = frozen_history
    f.run("checkout", "-qb", "missing-side", f.anchor)
    f.source.write_bytes(b"intermediate side bytes\n")
    missing = f.commit("side parent to remove")
    f.source.write_bytes(b"frozen production\n")
    f.commit("same-tree side tip")
    f.run("checkout", "-q", "topic")
    f.run("merge", "--no-ff", "-s", "ours", "--no-edit", "missing-side")
    missing_object = f.root / ".git/objects" / missing[:2] / missing[2:]
    # Git loose objects are read-only on Windows; only this disposable object is changed.
    missing_object.chmod(0o600)
    missing_object.unlink()
    assert f.run("rev-parse", "--is-shallow-repository").strip() == b"false"
    with pytest.raises(ValueError, match="git input failed"):
        f.verify()
    with pytest.raises(ValueError, match="git input failed"):
        history.write_history(gate.git, f.root, f.anchor, f.base)


@pytest.mark.parametrize("schema", [1, 2])
@pytest.mark.parametrize("target", ["manifest", "object"])
def test_history_rechecks_real_disk_after_final_head_readback(frozen_history, schema, target):
    f = frozen_history
    if schema == 1:
        manifest, objects = history.history(gate.git, f.root, f.anchor, f.base, anchor=f.anchor)
        manifest["objects"] = {}
        for digest, raw in objects.items():
            path = f"research/vanilla-ai/1.15.0/discovery/history-objects/{digest}.gz"
            packed = history.pack(raw)
            manifest["objects"][digest] = {
                "path": path,
                "sha256": gate.sha(packed),
                "bytes": len(raw),
            }
        history.write_json(f.root / history.HISTORY_PATH, manifest)
    sources = gate.Sources(f.root)
    manifest = sources.json(history.HISTORY_PATH)
    path = history.HISTORY_PATH
    if target == "object":
        path = next(iter(manifest["objects"].values()))["path"]
    original = sources.read(path)
    calls = 0

    def change_disk_on_readback(root, *arguments):
        nonlocal calls
        result = gate.git(root, *arguments)
        if arguments == ("rev-parse", "--verify", "HEAD^{commit}"):
            calls += 1
            if calls == 2:
                (f.root / path).write_bytes(original + b"persistent disk drift\n")
        return result

    with pytest.raises(ValueError, match="historical input changed"):
        history.verify_history(sources, change_disk_on_readback, f.anchor, f.base)
    assert calls == 2
    assert sources.read(path) == original
    assert (f.root / path).read_bytes() != original


@pytest.mark.parametrize("target", ["manifest", "object"])
def test_history_rejects_stale_sources_override_before_accepting_current_disk(
    frozen_history, target
):
    f = frozen_history
    cached = gate.Sources(f.root)
    manifest = cached.json(history.HISTORY_PATH)
    path = history.HISTORY_PATH
    if target == "object":
        path = next(iter(manifest["objects"].values()))["path"]
    raw = cached.read(path)
    sources = gate.Sources(f.root, {path: raw})
    (f.root / path).write_bytes(raw + b"changed after preloaded input\n")
    with pytest.raises(ValueError, match="historical input changed"):
        history.verify_history(sources, gate.git, f.anchor, f.base)
