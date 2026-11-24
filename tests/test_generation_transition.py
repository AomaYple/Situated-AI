"""Synthetic Git histories for the generated-output transition preflight."""

import hashlib
import json
import shutil
import stat
import subprocess
import zlib
from pathlib import Path
lazy import os

import pytest

from tools.ci.generation_transition import LOCK, plan_transition


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
    (repo / "intent-only").touch()
    git(repo, "add", "--intent-to-add", "intent-only")
    before = git(repo, "status", "--porcelain")
    report = plan_transition(repo, commit, new, digest(new))
    assert report["head"] == git(repo, "rev-parse", "HEAD")
    assert report["previous_lock_sha256"] == digest(lock(old))
    rows = report["outputs"]
    assert isinstance(rows, list)
    assert {row["path"]: row["action"] for row in rows} == {
        "common/added.txt": "add",
        "common/keep.txt": "keep",
        "common/replace.txt": "replace",
        "common/retire.txt": "retire",
    }
    retired = next(row for row in rows if row["action"] == "retire")
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
        "common/CONIN$.txt",
        "common/CON .txt",
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


@pytest.mark.parametrize("damage", ["truncated", "checksum", "wrong-object"])
def test_reads_historical_blob_body(history, damage):
    repo, commit, previous = history
    target = "common/retire.txt"
    oid = git(repo, "rev-parse", f"{commit}:mod/{target}")
    obj = repo / ".git/objects" / oid[:2] / oid[2:]
    compressed = obj.read_bytes()
    if damage == "truncated":
        corrupted = compressed[:-2]
    elif damage == "checksum":
        corrupted = compressed[:-1] + bytes([compressed[-1] ^ 1])
    else:
        corrupted = zlib.compress(b"blob 1\0z")
    obj.chmod(stat.S_IREAD | stat.S_IWRITE)
    obj.write_bytes(corrupted)
    new = lock({name: raw for name, raw in previous.items() if name != target})
    with pytest.raises(ValueError):
        plan_transition(repo, commit, new, digest(new))


def test_requires_physical_repository_root_and_its_own_index(history, monkeypatch):
    repo, commit, previous = history
    new = lock(previous)
    nested = repo / "child"
    shutil.copytree(repo / "mod", nested / "mod")
    monkeypatch.setenv("GIT_DIR", str(repo / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(nested))
    with pytest.raises(ValueError, match="physical root"):
        plan_transition(nested, commit, new, digest(new))
    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_WORK_TREE")
    clean_index = repo / "clean-index"
    shutil.copyfile(repo / ".git/index", clean_index)
    target = repo / "mod/common/retire.txt"
    target.write_bytes(b"staged")
    git(repo, "add", "mod")
    target.write_bytes(previous["common/retire.txt"])
    monkeypatch.setenv("GIT_INDEX_FILE", str(clean_index))
    with pytest.raises(ValueError, match="index"):
        plan_transition(repo, commit, new, digest(new))


@pytest.mark.parametrize("existing", ["Localization/notes.txt", "common/Notes"])
def test_rejects_occupied_directory_aliases(history, existing):
    repo, commit, previous = history
    occupied = repo / "mod" / existing
    if occupied.suffix:
        occupied.parent.mkdir()
        occupied.write_bytes(b"user")
    else:
        occupied.mkdir()
    new = lock({**previous, "common/notes/added.txt": b"new"})
    with pytest.raises(ValueError, match="casing"):
        plan_transition(repo, commit, new, digest(new))


def test_rejects_tag_objects_and_staged_gitlinks_despite_diff_configuration(history):
    repo, commit, previous = history
    new = lock(previous)
    git(repo, "tag", "-a", "example", "-m", "example")
    tag = git(repo, "rev-parse", "example")
    with pytest.raises(ValueError, match="commit object"):
        plan_transition(repo, tag, new, digest(new))
    git(repo, "config", "diff.ignoreSubmodules", "all")
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{commit},mod/common/extra")
    with pytest.raises(ValueError, match="regular generated blob"):
        plan_transition(repo, commit, new, digest(new))


def test_unmerged_generated_index_entry_is_rejected(history):
    repo, commit, previous = history
    new = lock(previous)
    path = "mod/common/retire.txt"
    oid = git(repo, "rev-parse", f"{commit}:{path}")
    git(repo, "update-index", "--force-remove", "--", path)
    subprocess.run(
        ["git", "-C", str(repo), "update-index", "--index-info"],
        input=f"100644 {oid} 2\t{path}\n".encode(),
        check=True,
    )
    with pytest.raises(ValueError, match="unmerged"):
        plan_transition(repo, commit, new, digest(new))


def test_rejects_an_intent_to_add_entry_for_an_empty_historical_blob(history):
    repo, _, previous = history
    path = "common/empty.txt"
    previous[path] = b""
    (repo / "mod" / path).touch()
    new = lock(previous)
    (repo / "mod" / LOCK).write_bytes(new)
    git(repo, "add", "mod")
    git(repo, "commit", "-qm", "empty generated blob")
    commit = git(repo, "rev-parse", "HEAD")
    index_entries = git(repo, "ls-files", "--stage", "-z", "mod")
    plan_transition(repo, commit, new, digest(new))

    git(repo, "update-index", "--force-remove", "--", f"mod/{path}")
    git(repo, "add", "--intent-to-add", "--", f"mod/{path}")
    assert git(repo, "ls-files", "--stage", "-z", "mod") == index_entries
    before = (repo / ".git/index").read_bytes()
    with pytest.raises(ValueError, match="intent-to-add"):
        plan_transition(repo, commit, new, digest(new))
    assert (repo / ".git/index").read_bytes() == before


def test_rejects_a_short_alias_of_an_existing_output_parent(history, monkeypatch):
    repo, commit, previous = history
    common = repo.resolve() / "mod/common"
    directory = common / "Long Output Subdirectory"
    directory.mkdir()
    alias = common / "LONGOU~1"
    current_lstat = Path.lstat

    def lstat_through_alias(path: Path) -> os.stat_result:
        # Directory enumeration yields the long name, while lookup accepts the short alias.
        return current_lstat(directory if path == alias else path)

    monkeypatch.setattr(Path, "lstat", lstat_through_alias)
    new = lock({**previous, "common/LONGOU~1/missing/added.txt": b"new"})
    with pytest.raises(ValueError, match="existing path"):
        plan_transition(repo, commit, new, digest(new))
