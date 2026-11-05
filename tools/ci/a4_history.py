"""Explicit production presence and immutable historical objects for A4 discovery."""

from __future__ import annotations

import gzip
import subprocess
from typing import TYPE_CHECKING, Any

from tools.ci.a4_schema import HASH, check_shape

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

from tools.ci.a4_discovery import encoded, pack, sha, unpack, write_json

ANCHOR = "f5e704fc2f021b066264c1168093155496e34d2f"
HISTORY_PATH = "research/vanilla-ai/1.15.0/discovery/production-history.json"
PRODUCTION = ("src/pdx", "mod/decisions", "mod/generation-lock.json")


def state(raw: bytes | None) -> dict[str, Any]:
    return {
        "presence": "absent" if raw is None else "present",
        "hashes": [] if raw is None else [sha(raw)],
    }


def revisions(git: Callable[..., bytes], root: Path, anchor: str) -> list[str]:
    """Retain every tree changing production against any explicit parent edge.

    ``-m`` compares merges against all parents. Their union selects the merge's
    complete actual tree, including resolution bytes absent from either parent.
    """
    git(root, "merge-base", "--is-ancestor", anchor, "HEAD")
    candidates = (
        git(root, "rev-list", "--reverse", "--ancestry-path", f"{anchor}..HEAD")
        .decode()
        .splitlines()
    )
    if len(candidates) > 10000:
        raise ValueError("production history edge limit; explicit rebaseline required")
    return [
        anchor,
        *(
            revision
            for revision in candidates
            if git(
                root,
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-m",
                "-r",
                revision,
                "--",
                *PRODUCTION,
            ).strip()
        ),
    ]


def validate_state(value: dict[str, Any]) -> None:
    check_shape(value, {"presence": {"present", "absent"}, "hashes": [HASH]})
    if len(value["hashes"]) != (1 if value["presence"] == "present" else 0):
        raise ValueError("presence/hash cardinality mismatch")


def tree(
    git: Callable[..., bytes], root: Path, revision: str, extra: tuple[str, ...] = ()
) -> dict[str, bytes]:
    records = git(root, "ls-tree", "-r", "-z", revision, "--", *PRODUCTION, *extra).split(b"\0")
    result = {}
    members = []
    for record in records:
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, kind, object_id = metadata.split()
        if kind != b"blob" or mode not in {b"100644", b"100755"}:
            raise ValueError("production tree contains non-file object")
        members.append((raw_path.decode("utf8"), object_id.decode()))
    process = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=root,
        input="".join(identity + "\n" for _, identity in members).encode(),
        capture_output=True,
        check=False,
    )
    if process.returncode:
        raise ValueError("production historical batch read failed")
    offset = 0
    for path, identity in members:
        end = process.stdout.index(b"\n", offset)
        header = process.stdout[offset:end].split()
        if len(header) != 3 or header[1] != b"blob" or header[0].decode() != identity:
            raise ValueError("historical Git blob missing")
        size = int(header[2])
        result[path] = process.stdout[end + 1 : end + 1 + size]
        offset = end + size + 2
    if offset != len(process.stdout):
        raise ValueError("historical Git batch framing mismatch")
    return result


def current(git: Callable[..., bytes], root: Path, extra: tuple[str, ...] = ()) -> dict[str, bytes]:
    tracked = git(root, "ls-files", "-z", "--", *PRODUCTION, *extra).split(b"\0")
    untracked = git(root, "ls-files", "--others", "--exclude-standard", "-z", "--", *PRODUCTION)
    if untracked.strip(b"\0"):
        raise ValueError(
            "unregistered untracked production candidate: "
            + untracked.replace(b"\0", b", ").decode("utf8")
        )
    result = {}
    for value in tracked:
        if not value:
            continue
        name = value.decode("utf8")
        path = root / name
        if path.is_symlink():
            raise ValueError("production symlink is unsupported")
        if path.is_file():
            result[name] = path.read_bytes()
    return result


def edge(before: dict[str, bytes], after: dict[str, bytes], origin: str) -> list[dict[str, Any]]:
    differences = {
        path: [state(before.get(path)), state(after.get(path))]
        for path in sorted(set(before) | set(after))
        if before.get(path) != after.get(path)
    }
    diff = sha(encoded(differences))
    return [
        {
            "id": f"{origin}:{path}",
            "path": path,
            "checkpoint": sides[0],
            "current": sides[1],
            "diff_sha256": diff,
        }
        for path, sides in differences.items()
    ]


def history(
    git: Callable[..., bytes], root: Path, candidate: str, base: str, *, anchor: str = ANCHOR
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Expected historical membership comes from actual fixed Git trees, never ledger IDs."""
    extra = tuple(
        git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", candidate)
        .decode("utf8")
        .splitlines()
    )
    checkpoint = tree(git, root, candidate, extra)
    parent = tree(git, root, candidate + "^", extra)
    baseline = tree(git, root, base, extra)
    registered = tree(git, root, anchor, extra)
    evolution = {
        revision: tree(git, root, revision) for revision in revisions(git, root, anchor)[1:]
    }
    paths = sorted(
        set(checkpoint)
        | set(parent)
        | set(baseline)
        | set(registered)
        | {path for files in evolution.values() for path in files}
    )
    objects: dict[str, bytes] = {}
    members = {}
    for path in paths:
        states = {}
        for name, files in [
            ("candidate_parent", parent),
            ("candidate", checkpoint),
            ("production_base", baseline),
            ("registered", registered),
            *evolution.items(),
        ]:
            raw = files.get(path)
            states[name] = state(raw)
            if raw is not None:
                objects[sha(raw)] = raw
        members[path] = states
    return {
        "schema": 1,
        "anchor": anchor,
        "candidate": candidate,
        "production_base": base,
        "paths": members,
        "registered_paths": sorted(
            path
            for path in set(registered) | {path for files in evolution.values() for path in files}
            if path.startswith(("src/pdx/", "mod/decisions/")) or path == "mod/generation-lock.json"
        ),
    }, objects


def write_history(git: Callable[..., bytes], root: Path, candidate: str, base: str) -> None:
    manifest, objects = history(git, root, candidate, base, anchor=ANCHOR)
    manifest["objects"] = {}
    for identity, raw in objects.items():
        packed = pack(raw)
        path = f"research/vanilla-ai/1.15.0/discovery/history-objects/{identity}.gz"
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("historical production object size limit")
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.read_bytes() != packed:
            raise ValueError("immutable historical object collision")
        destination.write_bytes(packed)
        manifest["objects"][identity] = {"path": path, "sha256": sha(packed), "bytes": len(raw)}
    write_json(root / HISTORY_PATH, manifest)


def verify_history(
    sources: Any, git: Callable[..., bytes], candidate: str, base: str
) -> dict[str, Any]:
    expected, objects = history(git, sources.root, candidate, base, anchor=ANCHOR)
    actual: dict[str, Any] = sources.json(HISTORY_PATH)
    if (
        set(actual) != {*expected, "objects"}
        or {key: actual[key] for key in expected} != expected
        or set(actual["objects"]) != set(objects)
    ):
        raise ValueError("production historical membership/edge mismatch")
    for identity, raw in objects.items():
        item = actual["objects"][identity]
        path = f"research/vanilla-ai/1.15.0/discovery/history-objects/{identity}.gz"
        if (
            set(item) != {"path", "sha256", "bytes"}
            or item["path"] != path
            or item["bytes"] != len(raw)
        ):
            raise ValueError("historical object schema/size mismatch")
        packed = sources.read(path)
        # Empty historical files are present objects, never absence.
        if sha(packed) != item["sha256"] or gzip_bytes(packed, len(raw)) != raw:
            raise ValueError("historical object identity mismatch")
    return actual


def gzip_bytes(packed: bytes, size: int) -> bytes:
    if size == 0:
        if packed != pack(b""):
            raise ValueError("noncanonical empty historical object")
        return gzip.decompress(packed)
    return unpack(packed, size)


def changes(
    git: Callable[..., bytes], root: Path, candidate: str, base: str
) -> list[dict[str, Any]]:
    extra = tuple(
        git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", candidate)
        .decode("utf8")
        .splitlines()
    )
    checkpoint = tree(git, root, candidate, extra)
    parent = tree(git, root, candidate + "^", extra)
    baseline = tree(git, root, base)
    registered = tree(git, root, ANCHOR)
    evolution = [tree(git, root, revision) for revision in revisions(git, root, ANCHOR)[1:]]
    now_production = current(git, root)
    now = current(git, root, extra)
    # Registered paths remain visible even if later returned to the base or deleted.
    historical = {item["path"] for item in edge(baseline, registered, "production_delta")}
    historical.update(
        item["path"] for files in evolution for item in edge(baseline, files, "production_delta")
    )
    delta = {item["path"]: item for item in edge(baseline, now_production, "production_delta")}
    for path in historical - set(delta):
        delta[path] = {
            "id": f"production_delta:{path}",
            "path": path,
            "checkpoint": state(baseline.get(path)),
            "current": state(now_production.get(path)),
            "diff_sha256": sha(
                encoded([state(baseline.get(path)), state(now_production.get(path))])
            ),
        }
    # Keep candidate checkpoint path identities; current side is the actual current path state.
    candidates = []
    for item in edge(parent, checkpoint, "checkpoint"):
        item["checkpoint"] = state(checkpoint.get(item["path"]))
        item["current"] = state(now.get(item["path"]))
        candidates.append(item)
    return [*candidates, *(delta[path] for path in sorted(delta))]


def production_paths(git: Callable[..., bytes], root: Path) -> list[str]:
    return sorted(current(git, root))
