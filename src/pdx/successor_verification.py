"""Verify frozen ZIP provenance and the first legacy-writer transition from Git objects."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from functools import cache
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from pdx import distribution, version_contracts, writer_transition
from pdx.successor_sources import (
    _RETAINED_VANILLA_PAYLOADS,
    check_reviewed_sources,
    object_from_json,
    sha256,
)

if TYPE_CHECKING:
    from pathlib import Path


LOCK = "generation-lock.json"
DIRECTORIES = ("common", "localization", ".metadata")
GENERATED_ROOTS = {name.casefold() for name in (*DIRECTORIES, distribution.THUMBNAIL_NAME, LOCK)}


def _owned(name: str) -> bool:
    parts = PurePosixPath(name).parts
    return name == distribution.THUMBNAIL_NAME or (len(parts) >= 2 and parts[0] in DIRECTORIES)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate lock key: {key}")
        result[key] = value
    return result


def _outputs(raw: bytes) -> dict[str, str]:
    lock = json.loads(raw, object_pairs_hook=_unique_object)
    if (
        not isinstance(lock, dict)
        or type(lock.get("schema")) is not int
        or lock["schema"] != 1
        or lock.get("evidence") != "frozen_generation_not_current_game_verification"
        or not isinstance(lock.get("files"), dict)
        or not lock["files"]
    ):
        raise ValueError("expected a nonempty schema 1 generation lock")
    files = lock["files"]
    distribution._validate_paths(list(files))
    reviewed: dict[str, str] = {}
    for name, digest in files.items():
        if (
            not _owned(name)
            or not isinstance(digest, str)
            or not re.fullmatch("[a-f0-9]{64}", digest)
        ):
            raise ValueError(f"invalid generated output or digest: {name}")
        reviewed[name] = digest
    return reviewed


def _git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "--no-lazy-fetch",
            "--no-replace-objects",
            "-C",
            str(repo),
            *args,
        ],
        env={key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")},
        capture_output=True,
        check=False,
    )
    if result.returncode:
        reason = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"git {args[0]}: {reason or 'comparison failed'}")
    return result.stdout


def _git_outputs(repo: Path, commit: str | None) -> dict[str, str]:
    if commit is None:
        raw = _git(repo, "ls-files", "--stage", "-z")
    else:
        raw = _git(repo, "ls-tree", "-rz", commit)
    result = {}
    for row in raw.split(b"\0"):
        if not row:
            continue
        metadata, path = row.split(b"\t", 1)
        parts = path.decode("utf-8", errors="surrogateescape").split("/")
        if parts[0].casefold() != "mod":
            continue
        if len(parts) == 1 or parts[0] != "mod":
            raise ValueError(f"conflicting Git output root: {path!r}")
        if parts[1].casefold() not in GENERATED_ROOTS:
            continue
        if commit is None:
            mode, oid, stage = metadata.split()
            if stage != b"0":
                raise ValueError(f"unmerged generated index entry: {path!r}")
        else:
            mode, _, oid = metadata.split()
        if mode != b"100644":
            raise ValueError(f"expected a regular generated blob: {path!r}")
        result["/".join(parts[1:])] = oid.decode()
    return result


def _reviewed_commit(repo: Path, commit: object) -> str:
    if not isinstance(commit, str) or not re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", commit):
        raise ValueError("Expected an immutable reviewed Git commit")
    if _git(repo, "cat-file", "-t", commit) != b"commit\n":
        raise ValueError("Reviewed Git identity must be a commit object")
    return commit


def _read_blob(repo: Path, commit: str, path: str) -> bytes:
    entries = _git(repo, "ls-tree", "-z", commit, "--", f":(literal){path}").split(b"\0")
    if (
        len(entries) != 2
        or not entries[0].startswith(b"100644 blob ")
        or entries[0].partition(b"\t")[2] != path.encode()
    ):
        raise ValueError(f"Expected a recoverable regular Git source: {path}")
    oid = entries[0].split(None, 3)[2].decode()
    return _git(repo, "cat-file", "blob", oid)


# Record the first successfully published transition source here once its release is verified.
# The later origin-only policy is available only to descendants of that trusted source.
COMPLETED_WRITER_TRANSITION_COMMIT: str | None = None


def verify_origin_lineage(repo: Path, source_commit: str) -> None:
    """Require a later source to descend from a completed transition."""
    completed = COMPLETED_WRITER_TRANSITION_COMMIT
    if completed is None or completed == source_commit:
        raise ValueError("尚未登记已完成的 3.4.0 写点迁移，须使用首次切换的审查")
    _git(repo, "merge-base", "--is-ancestor", completed, source_commit)


def verify_reviewed_package(
    repo: Path,
    source_commit: str,
    archive: bytes,
    review: bytes,
    review_sha256: str,
    *,
    successor_lock: bytes | None = None,
    baseline_archive: Path | None = None,
    expected_previous: tuple[object, object] | None = None,
    installation: Path | None = None,
) -> dict[str, object]:
    """Bind a selected commit, its generation lock and one ZIP to external review bytes."""
    if sha256(review) != review_sha256:
        raise ValueError("Package source review differs from independent approval")
    decision = object_from_json(review)
    if decision.get("schema") != 2:
        raise ValueError("Expected a schema 2 package source review")
    successor_commit = _reviewed_commit(repo, source_commit)
    if decision.get("source_commit") != successor_commit:
        raise ValueError("Successor review differs from the selected Git source")
    git_lock = _read_blob(repo, successor_commit, f"mod/{LOCK}")
    lock_sha = sha256(git_lock)
    if lock_sha != decision.get("generation_lock_sha256") or (
        successor_lock is not None and successor_lock != git_lock
    ):
        raise ValueError("Successor lock differs from the approved Git source")

    @cache
    def source(path: str) -> bytes:
        return _read_blob(repo, successor_commit, path)

    successor_files = _outputs(git_lock)
    if _git_outputs(repo, successor_commit).keys() != {*successor_files, LOCK}:
        raise ValueError("Successor Git generation differs from its lock")
    locked_sources = object_from_json(git_lock).get("sources")
    if not isinstance(locked_sources, dict) or not locked_sources:
        raise ValueError("Successor lock lacks generation source identities")
    payload = writer_transition.verify_package_sources(
        archive, review, trusted_review_sha256=review_sha256
    )
    for name, raw in payload.items():
        if previous_name := _RETAINED_VANILLA_PAYLOADS.get(sha256(raw)):
            raise ValueError(
                f"Candidate member {name} reproduces retained 3.4.0 bytes: {previous_name}"
            )
    check_reviewed_sources(payload, decision["members"], successor_files, locked_sources, source)
    receipt = {
        "source_commit": successor_commit,
        "generation_lock_sha256": lock_sha,
        "candidate_zip_sha256": decision["archive_sha256"],
        "package_source_review_sha256": review_sha256,
        "reviewed_payload_members": len(payload),
    }
    if baseline_archive is None:
        return receipt

    baseline = decision.get("baseline")
    if not isinstance(baseline, dict):
        raise ValueError("Successor review does not identify the frozen predecessor")
    previous_commit = _reviewed_commit(repo, baseline.get("commit"))
    release_commit = _reviewed_commit(repo, writer_transition.BASE_RELEASE_COMMIT)
    previous_lock = _read_blob(repo, previous_commit, f"mod/{LOCK}")
    release_lock = _read_blob(repo, release_commit, f"mod/{LOCK}")
    previous_files = _outputs(previous_lock)
    if previous_files != _outputs(release_lock):
        raise ValueError("Predecessor generation differs from the 3.4.0 release payload")
    expected_baseline = {
        "commit": previous_commit,
        "release_commit": release_commit,
        "generation_lock_sha256": sha256(previous_lock),
        "archive_sha256": writer_transition.BASE_ZIP_SHA256,
        "writer_inventory_sha256": writer_transition.LEDGER_SHA256,
    }
    if baseline != expected_baseline or (
        expected_previous is not None
        and expected_previous != (previous_commit, sha256(previous_lock))
    ):
        raise ValueError("Successor review does not identify the frozen predecessor")
    _git(repo, "merge-base", "--is-ancestor", release_commit, previous_commit)
    _git(repo, "merge-base", "--is-ancestor", previous_commit, successor_commit)
    with baseline_archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != expected_baseline["archive_sha256"]:
            raise ValueError("Predecessor ZIP differs from the 3.4.0 release")
    raw = version_contracts.research_path("situated", writer_transition.LEDGER).read_bytes()
    if sha256(raw) != writer_transition.LEDGER_SHA256:
        raise ValueError("Reviewed writer inventory changed")
    rows = writer_transition._inventory(raw)
    if len(rows) != writer_transition.BASE_WRITERS:
        raise ValueError("Unexpected 3.4.0 writer denominator")
    if _git_outputs(repo, previous_commit).keys() != {*previous_files, LOCK}:
        raise ValueError("Predecessor Git generation differs from its lock")
    old_payload = {
        name: _read_blob(repo, previous_commit, f"mod/{name}") for name in previous_files
    }
    for name, contents in old_payload.items():
        if sha256(contents) != previous_files[name]:
            raise ValueError(f"Predecessor Git payload differs from its generation lock: {name}")
    result = writer_transition.reconcile_successor_writers(
        old_payload, payload, rows, decision, source, installation=installation
    )
    return {**receipt, "baseline": expected_baseline, **result}
