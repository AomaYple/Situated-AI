"""Read-only comparison of a reviewed successor lock with a Git-owned generated tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import ntpath
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath

from pdx import distribution, writer_transition
from pdx.model import ParseError
from pdx.publishing.local import checked_path
from pdx.successor_sources import object_from_json, sha256
from pdx.successor_verification import (
    DIRECTORIES,
    LOCK,
    _git,
    _git_outputs,
    _outputs,
    _owned,
    _reviewed_commit,
    verify_reviewed_package,
)


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
    """Bind a predecessor ownership plan to the same package provenance check as publishing."""
    decision = object_from_json(review)
    if sha256(review) != review_sha256:
        raise ValueError("Package source review differs from independent approval")
    if sha256(successor_lock) != plan["successor_lock_sha256"]:
        raise ValueError("Successor lock differs from the reviewed draft")
    return verify_reviewed_package(
        repo,
        _reviewed_commit(repo, decision.get("source_commit")),
        candidate_archive.read_bytes(),
        review,
        review_sha256,
        successor_lock=successor_lock,
        baseline_archive=baseline_archive,
        expected_previous=(plan["previous_commit"], plan["previous_lock_sha256"]),
        installation=installation,
    )


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
