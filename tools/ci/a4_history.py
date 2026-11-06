"""Explicit production presence and immutable historical objects for A4 discovery."""

from __future__ import annotations

import gzip
import re
import subprocess
from typing import TYPE_CHECKING, Any

from pdx.deployment import reject_links
from tools.ci.a4_schema import HASH, check_shape

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

from tools.ci.a4_discovery import (
    MAX_FILE_BYTES,
    encoded,
    pack,
    sha,
    strict_json,
    unpack,
    write_json,
)

ANCHOR = "f5e704fc2f021b066264c1168093155496e34d2f"
HISTORY_PATH = "research/vanilla-ai/1.15.0/discovery/production-history.json"
PRODUCTION = ("src/pdx", "mod/decisions", "mod/generation-lock.json")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
MAX_REVISIONS = 10000
MAX_TREE_BYTES = 16 * 1024 * 1024
MAX_TREE_ENTRIES = 100000
MAX_TAIL_ENTRIES = 2_000_000


def head_commit(git: Callable[..., bytes], root: Path) -> str:
    value = git(root, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    if not COMMIT.fullmatch(value):
        raise ValueError("invalid production history HEAD")
    return value


def check_head(git: Callable[..., bytes], root: Path, expected: str) -> None:
    if head_commit(git, root) != expected:
        raise ValueError("production history HEAD changed during verification")


def complete_history(git: Callable[..., bytes], root: Path, head: str) -> None:
    """A complete mainline cannot compensate for a shallow or missing side parent."""
    if git(root, "rev-parse", "--is-shallow-repository").strip() != b"false":
        raise ValueError("production history requires a complete non-shallow repository")
    # Traverse every parent, including those before the anchor. Missing commit
    # objects fail in Git instead of becoming an accepted truncated history.
    raw = git(root, "rev-list", "--parents", f"--max-count={MAX_REVISIONS + 1}", head)
    if len(raw) > MAX_TREE_BYTES or len(raw.splitlines()) > MAX_REVISIONS:
        raise ValueError("production history closure limit; explicit rebaseline required")


def disk_identity(root: Path, path: str) -> str:
    """Read current bounded regular-file bytes, independently of Sources caches."""
    source = root / path
    reject_links(source)
    if not source.resolve().is_relative_to(root.resolve()) or not source.is_file():
        raise ValueError(f"invalid current historical input: {path}")
    if source.stat().st_size >= MAX_FILE_BYTES:
        raise ValueError(f"oversized current historical input: {path}")
    with source.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES)
    if len(raw) >= MAX_FILE_BYTES:
        raise ValueError(f"oversized current historical input: {path}")
    return sha(raw)


def bind_input(sources: Any, path: str, identities: dict[str, str]) -> bytes:
    raw: bytes = sources.read(path)
    digest = sha(raw)
    if disk_identity(sources.root, path) != digest:
        raise ValueError(f"historical input changed during verification: {path}")
    identities[path] = digest
    return raw


def revision_range(
    git: Callable[..., bytes], root: Path, start: str, end: str, *, ancestry_path: bool = False
) -> list[str]:
    arguments = ("--ancestry-path",) if ancestry_path else ()
    raw = git(
        root,
        "rev-list",
        "--reverse",
        f"--max-count={MAX_REVISIONS + 1}",
        *arguments,
        f"{start}..{end}",
    )
    if len(raw) > (MAX_REVISIONS + 1) * 41:
        raise ValueError("production history edge limit; explicit refresh required")
    result = raw.decode().splitlines()
    if len(result) > MAX_REVISIONS:
        raise ValueError("production history edge limit; explicit refresh required")
    if any(not COMMIT.fullmatch(value) for value in result):
        raise ValueError("invalid production history revision")
    return result


def state(raw: bytes | None) -> dict[str, Any]:
    return {
        "presence": "absent" if raw is None else "present",
        "hashes": [] if raw is None else [sha(raw)],
    }


def revisions(
    git: Callable[..., bytes],
    root: Path,
    anchor: str,
    *,
    end: str = "HEAD",
    legacy_ancestry: bool = False,
) -> list[str]:
    """Retain every tree changing production against any explicit parent edge.

    ``-m`` compares merges against all parents. Their union selects the merge's
    complete actual tree, including resolution bytes absent from either parent.
    """
    git(root, "merge-base", "--is-ancestor", anchor, end)
    candidates = revision_range(git, root, anchor, end, ancestry_path=legacy_ancestry)
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
                *(("--root",) if not legacy_ancestry else ()),
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
    result = {}
    members = [(path, item[1]) for path, item in tree_entries(git, root, revision, extra).items()]
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


def tree_entries(
    git: Callable[..., bytes], root: Path, revision: str, extra: tuple[str, ...] = ()
) -> dict[str, tuple[str, str]]:
    """Preserve complete path/mode/blob identities without reading file contents."""
    raw = git(root, "ls-tree", "-r", "-z", revision, "--", *PRODUCTION, *extra)
    if len(raw) > MAX_TREE_BYTES:
        raise ValueError("production history tree size limit; explicit refresh required")
    result = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, kind, object_id = metadata.split()
        if kind != b"blob" or mode not in {b"100644", b"100755"}:
            raise ValueError("production tree contains non-file object")
        path, identity = raw_path.decode("utf8"), object_id.decode("ascii")
        if path in result or not COMMIT.fullmatch(identity):
            raise ValueError("invalid production tree identity")
        result[path] = (mode.decode("ascii"), identity)
        if len(result) > MAX_TREE_ENTRIES:
            raise ValueError("production history tree entry limit; explicit refresh required")
    return result


def verify_tail(git: Callable[..., bytes], root: Path, freeze_head: str, head: str) -> None:
    """Every new reachable commit must have exactly the frozen production tree."""
    if not isinstance(freeze_head, str) or not COMMIT.fullmatch(freeze_head):
        raise ValueError("invalid production history freeze_head")
    resolved = git(root, "rev-parse", "--verify", f"{freeze_head}^{{commit}}").decode().strip()
    if resolved != freeze_head:
        raise ValueError("production history freeze_head must name a commit")
    git(root, "merge-base", "--is-ancestor", ANCHOR, freeze_head)
    git(root, "merge-base", "--is-ancestor", freeze_head, head)
    frozen = tree_entries(git, root, freeze_head)
    cost = len(frozen)
    if cost > MAX_TAIL_ENTRIES:
        raise ValueError("production history tail cost limit; explicit refresh required")
    for revision in revision_range(git, root, freeze_head, head):
        current = tree_entries(git, root, revision)
        cost += len(current)
        if cost > MAX_TAIL_ENTRIES:
            raise ValueError("production history tail cost limit; explicit refresh required")
        if current != frozen:
            raise ValueError("production history tail changed; write_history refresh required")


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
    git: Callable[..., bytes],
    root: Path,
    candidate: str,
    base: str,
    *,
    anchor: str = ANCHOR,
    freeze_head: str | None = None,
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
        revision: tree(git, root, revision)
        for revision in revisions(
            git, root, anchor, end=freeze_head or "HEAD", legacy_ancestry=freeze_head is None
        )[1:]
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
        "schema": 1 if freeze_head is None else 2,
        **({"freeze_head": freeze_head} if freeze_head is not None else {}),
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
    head = head_commit(git, root)
    complete_history(git, root, head)
    manifest, objects = history(git, root, candidate, base, anchor=ANCHOR, freeze_head=head)
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
    check_head(git, root, head)
    complete_history(git, root, head)
    write_json(root / HISTORY_PATH, manifest)


def verify_history(
    sources: Any, git: Callable[..., bytes], candidate: str, base: str
) -> dict[str, Any]:
    head = head_commit(git, sources.root)
    complete_history(git, sources.root, head)
    identities: dict[str, str] = {}
    actual: dict[str, Any] = strict_json(bind_input(sources, HISTORY_PATH, identities))
    if (
        not isinstance(actual, dict)
        or type(actual.get("schema")) is not int
        or actual["schema"] not in {1, 2}
    ):
        raise ValueError("unsupported production history schema")
    freeze_head = None
    if actual["schema"] == 2:
        freeze_head = actual.get("freeze_head")
        if not isinstance(freeze_head, str):
            raise ValueError("invalid production history freeze_head")
        verify_tail(git, sources.root, freeze_head, head)
    expected, objects = history(
        git, sources.root, candidate, base, anchor=ANCHOR, freeze_head=freeze_head
    )
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
        packed = bind_input(sources, path, identities)
        # Empty historical files are present objects, never absence.
        if sha(packed) != item["sha256"] or gzip_bytes(packed, len(raw)) != raw:
            raise ValueError("historical object identity mismatch")
    check_head(git, sources.root, head)
    complete_history(git, sources.root, head)
    for path, digest in identities.items():
        if disk_identity(sources.root, path) != digest:
            raise ValueError(f"historical input changed during verification: {path}")
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
