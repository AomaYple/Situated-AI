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
from pathlib import Path, PurePosixPath

from pdx import distribution
from pdx.publishing.local import checked_path

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
        ["git", "--no-lazy-fetch", "--no-replace-objects", "-C", str(repo), *args],
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
                pending.append(path)
            elif not stat.S_ISREG(info.st_mode):
                raise ValueError(f"generated tree contains a special file: {name}")
            elif _owned(name) or name == LOCK:
                files[name] = path
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
        "head": head,
        "previous_commit": previous_commit,
        "previous_lock_sha256": original[LOCK],
        "successor_lock_sha256": successor_sha256,
        "outputs": outputs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--previous-commit", required=True)
    parser.add_argument("--successor-lock", type=Path, required=True)
    parser.add_argument("--successor-sha256", required=True)
    args = parser.parse_args()
    try:
        report = plan_transition(
            args.repo.resolve(strict=True),
            args.previous_commit,
            args.successor_lock.read_bytes(),
            args.successor_sha256,
        )
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
