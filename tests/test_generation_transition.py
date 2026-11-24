"""Synthetic Git histories for the generated-output transition preflight."""

import hashlib
import json
import subprocess
from typing import TYPE_CHECKING

import pytest

from tools.ci.generation_transition import LOCK, plan_transition

if TYPE_CHECKING:
    from pathlib import Path


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def lock(files: dict[str, bytes]) -> bytes:
    return json.dumps(
        {
            "schema": 1,
            "evidence": "frozen_generation_not_current_game_verification",
            "files": {path: digest(raw) for path, raw in files.items()},
            "sources": {},
        }
    ).encode()


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


@pytest.fixture
def history(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "core.autocrlf", "false")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "fixture@example.invalid")
    git(tmp_path, "config", "commit.gpgsign", "false")
    previous = {"common/keep.txt": b"k", "common/replace.txt": b"x", "common/retire.txt": b"y"}
    for name, raw in {**previous, LOCK: lock(previous)}.items():
        path = tmp_path / "mod" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    git(tmp_path, "add", "mod")
    git(tmp_path, "commit", "-qm", "previous")
    return tmp_path, git(tmp_path, "rev-parse", "HEAD"), previous


def test_plans_all_four_actions_and_preserves_files_and_index(history):
    repo, commit, old = history
    new = lock({"common/keep.txt": b"k", "common/replace.txt": b"z", "common/added.txt": b"a"})
    git(repo, "commit", "--allow-empty", "-qm", "later")
    (repo / "other").write_bytes(b"unrelated work")
    git(repo, "add", "other")
    before = git(repo, "status", "--porcelain")
    report = plan_transition(repo, commit, new, digest(new))
    assert report["head"] == git(repo, "rev-parse", "HEAD")
    assert report["previous_lock_sha256"] == digest(lock(old))
    assert {row["path"]: row["action"] for row in report["outputs"]} == {
        "common/added.txt": "add",
        "common/keep.txt": "keep",
        "common/replace.txt": "replace",
        "common/retire.txt": "retire",
    }
    retired = next(row for row in report["outputs"] if row["action"] == "retire")
    assert retired["previous_blob"] == git(repo, "rev-parse", f"{commit}:mod/common/retire.txt")
    assert retired["previous_sha256"] == digest(b"y")
    assert retired["successor_sha256"] is None
    assert git(repo, "status", "--porcelain") == before


@pytest.mark.parametrize(
    "change", ["edit", "missing", "untracked", "staged", "working-lock", "staged-revert"]
)
def test_requires_current_ownership(history, change):
    repo, commit, previous = history
    new = lock(previous)
    target = repo / "mod/common/retire.txt"
    if change == "missing":
        target.unlink()
    elif change == "working-lock":
        (repo / "mod" / LOCK).write_bytes(new + b" ")
    elif change == "untracked":
        (repo / "mod/common/local.txt").write_bytes(b"user")
    else:
        target.write_bytes(b"change")
        if change in {"staged", "staged-revert"}:
            git(repo, "add", "mod")
            if change == "staged-revert":
                git(repo, "commit", "-qm", "intervening output edit")
                target.write_bytes(b"y")
                git(repo, "add", "mod")
            else:
                target.write_bytes(b"y")
    before = git(repo, "status", "--porcelain")
    with pytest.raises(ValueError):
        plan_transition(repo, commit, new, digest(new))
    assert git(repo, "status", "--porcelain") == before


def test_binds_successor_and_requires_predecessor_ancestry(history):
    repo, commit, previous = history
    new = lock(previous)
    with pytest.raises(ValueError, match="reviewed digest"):
        plan_transition(repo, commit, new + b" ", digest(new))
    git(repo, "commit", "--allow-empty", "-qm", "future")
    future = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "--detach", commit)
    with pytest.raises(ValueError, match="merge-base"):
        plan_transition(repo, future, new, digest(new))


@pytest.mark.parametrize(
    "path",
    [
        "decisions/source.toml",
        "common/../foo",
        "common/RETIRE.txt",
        "common/keep.txt/child",
        "common/alias/file.txt",
        "common/con.txt",
    ],
)
def test_rejects_conflicting_or_out_of_scope_successor(history, path):
    repo, commit, _ = history
    new = lock({path: b"value", "common/Alias/witness.txt": b"synthetic"})
    with pytest.raises(ValueError):
        plan_transition(repo, commit, new, digest(new))


def test_rejects_duplicate_json_and_forged_historical_ownership(history):
    repo, _, previous = history
    commit = git(repo, "rev-parse", "HEAD")
    new = lock(previous)
    ambiguous = new.replace(b'"files":', b'"files": {}, "files":', 1)
    with pytest.raises(ValueError, match="duplicate"):
        plan_transition(repo, commit, ambiguous, digest(ambiguous))
    (repo / "mod" / LOCK).write_bytes(lock({**previous, "common/retire.txt": b"wrong digest"}))
    git(repo, "add", "mod")
    git(repo, "commit", "-qm", "inconsistent prior lock")
    with pytest.raises(ValueError, match="bytes"):
        plan_transition(repo, git(repo, "rev-parse", "HEAD"), new, digest(new))


def test_reserved_successor_path_is_an_existing_directory(history):
    repo, commit, previous = history
    directory = repo / "mod/common/added.txt"
    directory.mkdir()
    new = lock({**previous, "common/added.txt": b"addition"})
    with pytest.raises(ValueError, match="existing path"):
        plan_transition(repo, commit, new, digest(new))
    assert directory.is_dir()
