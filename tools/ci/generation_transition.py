"""Read-only comparison of a reviewed successor lock with a Git-owned generated tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import ntpath
import os
import re
import stat
import subprocess
import zipfile
from functools import cache
from pathlib import Path, PurePosixPath

from pdx import distribution, version_contracts, writer_transition
from pdx.model import ParseError
from pdx.publishing.local import checked_path
from pdx.publishing.runner import _RETAINED_VANILLA_PAYLOADS
from pdx.successor_sources import check_reviewed_sources, object_from_json, sha256

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


def _check_worktree(repo: Path) -> None:
    top, gitdir, index = (
        _git(
            repo,
            "rev-parse",
            "--path-format=absolute",
            "--show-toplevel",
            "--absolute-git-dir",
            "--git-path",
            "index",
        )
        .decode()
        .splitlines()
    )
    if not repo.samefile(top) or checked_path(Path(index)) != Path(gitdir) / "index":
        raise ValueError("expected the physical root and index of the selected Git worktree")


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


def _working_files(root: Path, outputs: list[str]) -> dict[str, Path]:
    """Compare actual files and empty directories with the entire proposed Windows namespace."""
    topology: dict[str, tuple[str, bool]] = {}

    def register(name: str, directory: bool) -> None:
        identity = name.casefold()
        if topology.setdefault(identity, (name, directory)) != (name, directory):
            raise ValueError(f"conflicting directory, casing or existing path: {name}")
        if any(ntpath.isreserved(part) for part in PurePosixPath(name).parts):
            raise ValueError(f"reserved Windows output path: {name}")

    for name in DIRECTORIES:
        register(name, True)
    for name in [*outputs, LOCK, distribution.THUMBNAIL_NAME]:
        register(name, False)
        for parent in PurePosixPath(name).parents:
            if parent.parts:
                register(parent.as_posix(), True)

    unseen_parents = {name for name, directory in topology.values() if directory}
    files = {}
    pending = [checked_path(root)]
    while pending:
        for path in pending.pop().iterdir():
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or (
                getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise ValueError(f"generated tree contains a redirect: {path}")
            name = path.relative_to(root).as_posix()
            directory = stat.S_ISDIR(info.st_mode)
            register(name, directory)
            if directory:
                unseen_parents.discard(name)
                pending.append(path)
            elif not stat.S_ISREG(info.st_mode):
                raise ValueError(f"generated tree contains a special file: {name}")
            elif _owned(name) or name == LOCK:
                files[name] = path
    # NTFS short names may resolve even though iteration yielded only the long name.
    for name in sorted(unseen_parents):
        try:
            (root / name).lstat()
        except FileNotFoundError:
            continue
        raise ValueError(f"successor directory conflicts with an existing path: {name}")
    return files


def plan_transition(
    repo: Path, previous_commit: str, successor_lock: bytes, successor_sha256: str
) -> dict[str, object]:
    """Verify the predecessor and return only paths, identities and repository-byte digests.

    The caller obtains the successor digest from independent review. Its contents describe the
    proposed output set; ownership, provenance and product approval of that successor are separate.
    """
    if not re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", previous_commit):
        raise ValueError("expected a full immutable predecessor commit")
    if hashlib.sha256(successor_lock).hexdigest() != successor_sha256:
        raise ValueError("successor lock differs from the reviewed digest")
    successor = _outputs(successor_lock)
    repo = repo.resolve(strict=True)
    _check_worktree(repo)
    if _git(repo, "cat-file", "-t", previous_commit) != b"commit\n":
        raise ValueError("predecessor must identify the commit object itself")
    head = _git(repo, "rev-parse", "HEAD").decode().strip()
    _git(repo, "merge-base", "--is-ancestor", previous_commit, head)
    tracked = _git_outputs(repo, previous_commit)
    if (head != previous_commit and tracked != _git_outputs(repo, head)) or tracked != _git_outputs(
        repo, None
    ):
        raise ValueError("generated HEAD or index differs from the predecessor")
    # The stage listing gives an intent-to-add entry the same identity as an empty blob.
    # Hiding those entries from the cached diff exposes deletions after the identity check.
    hidden_deletions = _git(
        repo,
        "diff-index",
        "--cached",
        "--ita-invisible-in-index",
        "--no-ext-diff",
        "--no-renames",
        "--diff-filter=D",
        "--name-only",
        "-z",
        head,
        "--",
        *(f"mod/{name}" for name in (*DIRECTORIES, LOCK, distribution.THUMBNAIL_NAME)),
    )
    if hidden_deletions:
        path = hidden_deletions.split(b"\0", 1)[0]
        raise ValueError(f"generated index has an intent-to-add entry: {path!r}")
    historical_lock = _git(repo, "show", f"{previous_commit}:mod/{LOCK}")
    previous = _outputs(historical_lock)
    # Consider both generations together: a case-only rename is ambiguous on Windows.
    all_names = sorted(previous.keys() | successor.keys())
    distribution._validate_paths(all_names)
    files = _working_files(repo / "mod", all_names)

    original = {**previous, LOCK: hashlib.sha256(historical_lock).hexdigest()}
    for source, names in (("historical tree", tracked.keys()), ("working tree", files.keys())):
        if names != original.keys():
            raise ValueError(
                f"{source} differs from predecessor lock: {sorted(names ^ original.keys())}"
            )
    object_format = _git(repo, "rev-parse", "--show-object-format").decode().strip()
    for name, expected in original.items():
        # Decode the recoverable object, including packed/delta objects. Only hashes leave RAM.
        raw = _git(repo, "cat-file", "blob", tracked[name])
        git_hash = hashlib.new(object_format, f"blob {len(raw)}\0".encode("ascii"))
        git_hash.update(raw)
        if git_hash.hexdigest() != tracked[name] or hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f"predecessor object bytes differ from lock or Git identity: {name}")
        with files[name].open("rb") as stream:
            working_digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if working_digest != expected:
            raise ValueError(f"working bytes, predecessor blob or lock differ: {name}")

    outputs = []
    for name in all_names:
        if name not in previous:
            if (repo / "mod" / name).exists():
                raise ValueError(f"successor addition would replace an existing path: {name}")
            action = "add"
        elif name not in successor:
            action = "retire"
        elif previous[name] == successor[name]:
            action = "keep"
        else:
            action = "replace"
        outputs.append(
            {
                "path": name,
                "previous_blob": tracked.get(name),
                "previous_sha256": previous.get(name),
                "successor_sha256": successor.get(name),
                "action": action,
            }
        )
    return {
        "check_scope": "file_ownership_only",
        "retirement_authorized": False,
        "head": head,
        "previous_commit": previous_commit,
        "previous_lock_sha256": original[LOCK],
        "successor_lock_sha256": successor_sha256,
        "outputs": outputs,
    }


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


def verify_successor(
    repo: Path,
    plan: dict[str, object],
    successor_lock: bytes,
    baseline_archive: Path,
    candidate_archive: Path,
    review: bytes,
    review_sha256: str,
    *,
    installation: Path | None = None,
) -> dict[str, object]:
    """Check the paired Git, lock, ZIP, source and writer identities without a renderer."""
    if sha256(review) != review_sha256:
        raise ValueError("Package source review differs from independent approval")
    decision = object_from_json(review)
    previous_commit = _reviewed_commit(repo, plan["previous_commit"])
    release_commit = _reviewed_commit(repo, writer_transition.BASE_RELEASE_COMMIT)
    previous_lock = _read_blob(repo, previous_commit, f"mod/{LOCK}")
    release_lock = _read_blob(repo, release_commit, f"mod/{LOCK}")
    previous_files = _outputs(previous_lock)
    if (
        previous_files != _outputs(release_lock)
        or sha256(previous_lock) != plan["previous_lock_sha256"]
    ):
        raise ValueError("Predecessor generation differs from the 3.4.0 release payload")
    expected_baseline = {
        "commit": previous_commit,
        "release_commit": release_commit,
        "generation_lock_sha256": sha256(previous_lock),
        "archive_sha256": writer_transition.BASE_ZIP_SHA256,
        "writer_inventory_sha256": writer_transition.LEDGER_SHA256,
    }
    if decision.get("schema") != 2 or decision.get("baseline") != expected_baseline:
        raise ValueError("Successor review does not identify the frozen predecessor")
    with baseline_archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != expected_baseline["archive_sha256"]:
            raise ValueError("Predecessor ZIP differs from the 3.4.0 release")
    successor_commit = _reviewed_commit(repo, decision.get("source_commit"))
    lock_sha = sha256(successor_lock)
    if (
        lock_sha != plan["successor_lock_sha256"]
        or lock_sha != decision.get("generation_lock_sha256")
        or successor_lock != _read_blob(repo, successor_commit, f"mod/{LOCK}")
    ):
        raise ValueError("Successor lock differs from the approved Git source")

    @cache
    def source(path: str) -> bytes:
        return _read_blob(repo, successor_commit, path)

    successor_files = _outputs(successor_lock)
    if _git_outputs(repo, successor_commit).keys() != {*successor_files, LOCK}:
        raise ValueError("Successor Git generation differs from its lock")
    locked_sources = object_from_json(successor_lock).get("sources")
    if not isinstance(locked_sources, dict) or not locked_sources:
        raise ValueError("Successor lock lacks generation source identities")
    payload = writer_transition.verify_package_sources(
        candidate_archive.read_bytes(), review, trusted_review_sha256=review_sha256
    )
    for name, raw in payload.items():
        if previous_name := _RETAINED_VANILLA_PAYLOADS.get(sha256(raw)):
            raise ValueError(
                f"Candidate member {name} reproduces retained 3.4.0 bytes: {previous_name}"
            )
    check_reviewed_sources(payload, decision["members"], successor_files, locked_sources, source)
    raw = version_contracts.research_path("situated", writer_transition.LEDGER).read_bytes()
    if sha256(raw) != writer_transition.LEDGER_SHA256:
        raise ValueError("Reviewed writer inventory changed")
    rows = writer_transition._inventory(raw)
    if len(rows) != writer_transition.BASE_WRITERS:
        raise ValueError("Unexpected 3.4.0 writer denominator")
    old_payload = {
        name: _read_blob(repo, previous_commit, f"mod/{name}")
        for name in previous_files
        if name != distribution.THUMBNAIL_NAME
    }
    result = writer_transition.reconcile_successor_writers(
        old_payload, payload, rows, decision, source, installation=installation
    )
    return {
        "baseline": expected_baseline,
        "source_commit": successor_commit,
        "generation_lock_sha256": lock_sha,
        "candidate_zip_sha256": decision["archive_sha256"],
        "package_source_review_sha256": review_sha256,
        "reviewed_payload_members": len(payload),
        **result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--previous-commit", required=True)
    parser.add_argument("--successor-lock", type=Path, required=True)
    parser.add_argument("--successor-sha256", required=True)
    parser.add_argument(
        "--writer-candidate",
        type=Path,
        help="Require the original company's frozen ZIP and per-writer retirement evidence",
    )
    parser.add_argument("--successor-archive", type=Path, help="Frozen successor ZIP")
    parser.add_argument("--baseline-archive", type=Path, help="Published 3.4.0 ZIP")
    parser.add_argument("--successor-review", type=Path, help="Independent package/writer review")
    parser.add_argument("--successor-review-sha256", help="Digest from independent review")
    parser.add_argument(
        "--installation",
        type=Path,
        help="Read-only locked Victoria 3 installation for original values (default: V3_ROOT or Steam)",
    )
    args = parser.parse_args()
    review_args = (
        args.successor_archive,
        args.baseline_archive,
        args.successor_review,
        args.successor_review_sha256,
    )
    use_review = any(value is not None for value in review_args)
    if use_review and (not all(review_args) or args.writer_candidate is not None):
        parser.error(
            "Use the four successor review arguments together, separately from --writer-candidate"
        )
    exit_code = 0
    try:
        successor_lock = args.successor_lock.read_bytes()
        report = plan_transition(
            args.repo.resolve(strict=True),
            args.previous_commit,
            successor_lock,
            args.successor_sha256,
        )
        if args.writer_candidate is not None:
            previous = _git(args.repo, "show", f"{args.previous_commit}:mod/{LOCK}")
            report["writer_transition"] = writer_transition.check_candidate(
                args.writer_candidate,
                successor_files=_outputs(successor_lock),
                previous_files=_outputs(previous),
            )
        if use_review:
            successor_result = verify_successor(
                args.repo,
                report,
                successor_lock,
                args.baseline_archive,
                args.successor_archive,
                args.successor_review.read_bytes(),
                args.successor_review_sha256,
                installation=args.installation,
            )
            report["writer_transition"] = successor_result
            if not successor_result["writer_disposition_complete"]:
                exit_code = 1
    except (OSError, ValueError, ParseError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
