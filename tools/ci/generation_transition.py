"""Read-only comparison of a reviewed successor lock with a Git-owned generated tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath

from pdx import distribution

LOCK = "generation-lock.json"
DIRECTORIES = ("common", "localization", ".metadata")
PATHS = [f"mod/{name}" for name in (*DIRECTORIES, distribution.THUMBNAIL_NAME, LOCK)]


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


def _git(repo: Path, *args: str, data: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "--no-lazy-fetch", "--no-replace-objects", "-C", str(repo), *args],
        input=data,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        reason = result.stderr.decode("utf-8", errors="replace").strip()
        if not reason:
            reason = (
                "generated index or committed output differs from predecessor"
                if args[0] == "diff"
                else "comparison failed"
            )
        raise ValueError(f"git {args[0]}: {reason}")
    return result.stdout


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
    head = _git(repo, "rev-parse", "HEAD").decode().strip()
    _git(repo, "merge-base", "--is-ancestor", previous_commit, head)
    _git(repo, "diff", "--quiet", previous_commit, head, "--", *PATHS)
    _git(repo, "diff", "--quiet", "--cached", previous_commit, "--", *PATHS)
    historical_lock = _git(repo, "show", f"{previous_commit}:mod/{LOCK}")
    previous = _outputs(historical_lock)
    # Consider both generations together: a case-only rename is ambiguous on Windows.
    all_names = sorted(previous.keys() | successor.keys())
    distribution._validate_paths(all_names)
    directories: dict[str, str] = {}
    folded = {name.casefold() for name in all_names}
    for name in all_names:
        for parent in PurePosixPath(name).parents:
            spelling = parent.as_posix()
            key = spelling.casefold()
            if key in folded or directories.setdefault(key, spelling) != spelling:
                raise ValueError(f"conflicting output directory: {spelling}")

    tracked: dict[str, str] = {}
    for row in _git(repo, "ls-tree", "-rz", previous_commit, "--", *PATHS).split(b"\0"):
        if row:
            metadata, raw_path = row.split(b"\t", 1)
            mode, kind, oid = metadata.split()
            if mode != b"100644" or kind != b"blob":
                raise ValueError(f"expected a regular generated blob: {raw_path!r}")
            tracked[raw_path.decode().removeprefix("mod/")] = oid.decode()
    object_ids = [oid.encode() for oid in tracked.values()]
    available = _git(
        repo,
        "cat-file",
        "--batch-check=%(objectname) %(objecttype)",
        data=b"\n".join(object_ids) + b"\n",
    ).splitlines()
    if available != [oid + b" blob" for oid in object_ids]:
        raise ValueError("local predecessor objects for recovery are incomplete")
    files = {
        name: path
        for name, path in distribution._profile_directory_files(repo / "mod").items()
        if _owned(name) or name == LOCK
    }
    original = {**previous, LOCK: hashlib.sha256(historical_lock).hexdigest()}
    for source, names in (("historical tree", tracked.keys()), ("working tree", files.keys())):
        if names != original.keys():
            raise ValueError(
                f"{source} differs from predecessor lock: {sorted(names ^ original.keys())}"
            )
    object_format = _git(repo, "rev-parse", "--show-object-format").decode().strip()
    for name, expected in original.items():
        path = files[name]
        content_hash = hashlib.sha256()
        git_hash = hashlib.new(object_format, f"blob {path.stat().st_size}\0".encode("ascii"))
        with path.open("rb") as stream:
            while chunk := stream.read(128 * 1024):
                content_hash.update(chunk)
                git_hash.update(chunk)
        if content_hash.hexdigest() != expected or git_hash.hexdigest() != tracked[name]:
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
