"""Lossless, bounded, offline projection of a saved unverified capture; no scanner."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from tools.ci.a4_schema import INVESTIGATION, check_shape

CAPTURE_SHA256 = "51343911008b9b1dd62c53d31c1d118175d049b6346f18022acf515143e8537e"
DIRECTORY = "research/vanilla-ai/1.15.0/discovery"
ROOT_PATH = f"{DIRECTORY}/capture.json"
CATALOG_PATH = f"{DIRECTORY}/catalog.json"
REPORT_PATH = f"{DIRECTORY}/investigation.json"
PROJECTOR_INPUTS = (
    "tools/ci/a4_discovery.py",
    "tools/ci/a4_history.py",
    "tools/ci/a4_reconcile.py",
    "tools/ci/a4_schema.py",
    "tools/ci/a4_scope.py",
    "tests/test_a4_discovery.py",
    "tests/test_a4_history.py",
    "tests/test_a4_reconcile.py",
)
CROSSCHECK_NODES = (
    "tests/test_a4_discovery.py::test_projection_preserves_physical_and_bare_members",
    "tests/test_a4_history.py::test_real_git_add_delete_rename_and_untracked",
    "tests/test_a4_reconcile.py::test_stale_closure_is_transitive_and_preserves_unrelated",
)
CHUNK_BYTES = 8 * 1024 * 1024
MAX_CAPTURE_BYTES = 512 * 1024 * 1024
MAX_NODES = 2_000_000
MAX_DEPTH = 256
MAX_FILE_BYTES = 64 * 1024 * 1024
GOALS = ["G01", "G02", "G07", "C1", "C9", "C10"]


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encoded(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(value: Any) -> str:
    """The existing inventory's canonical JSON identity encoding, without importing a scanner."""
    return sha(encoded(value))


def strict_json(raw: bytes | str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise ValueError(f"duplicate JSON key: {key}")
            value[key] = item
        return value

    try:
        return json.loads(raw, object_pairs_hook=pairs)
    except (RecursionError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid bounded JSON") from error


def write_json(path: Path, value: Any) -> None:
    raw = encoded(value) + b"\n"
    if len(raw) >= MAX_FILE_BYTES:
        raise ValueError(f"oversized controlled JSON: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def pack(raw: bytes) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0, compresslevel=6) as stream:
        stream.write(raw)
    return output.getvalue()


def unpack(raw: bytes, size: int) -> bytes:
    if type(size) is not int or not 0 < size <= CHUNK_BYTES or len(raw) > CHUNK_BYTES + 65536:
        raise ValueError("oversized decompression declaration")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            result = stream.read(size + 1)
            if len(result) != size or stream.read(1):
                raise ValueError("oversized or truncated decompression")
    except (OSError, EOFError) as error:
        raise ValueError("corrupt gzip shard") from error
    return result


def unique(items: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        identity = item[key]
        if identity in result:
            raise ValueError(f"duplicate raw ID: {identity}")
        result[identity] = item
    return result


def project(raw: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct raw identity/ownership and the complete finite mapping from captured data."""
    version = raw["target_version"]
    if (
        raw["discovery_mode"] != "unverified"
        or raw["authorization"] != "none"
        or raw["actual_version"]["caligula_branch"] != f"release/{version}"
        or raw["baseline_id"] != f"victoria3-{version}:{digest(raw['source_hashes'])}"
    ):
        raise ValueError("mixed baseline/version or native authority")
    namespace = f"native:{version}"
    entries: dict[str, Any] = {}
    groups: dict[str, list[str]] = defaultdict(list)

    def add(kind: str, identity: str, source: str, group: str) -> None:
        key = f"D:{namespace}:{kind}:{identity}"
        if key in entries or source not in raw["source_hashes"]:
            raise ValueError("duplicate discovery or dangling source")
        entries[key] = {"kind": kind, "raw_id": identity, "source": source, "group": group}
        groups[group].append(key)

    for source in sorted(raw["source_hashes"]):
        add("source", source, source, f"{namespace}:structure:{source}")
    definitions = unique(raw["definitions"], "declaration_id")
    surfaces = unique(raw["surfaces"], "declaration_id")
    references = unique(raw["references"], "reference_id")
    slots = unique(raw["event_slots"], "slot_id")
    unique(raw["surfaces"], "surface_id")
    owned: Counter[str] = Counter()
    for identity, item in definitions.items():
        source = item["source"]
        if identity != digest((source, item["definition"], item["declaration_occurrence"])):
            raise ValueError("definition identity drift")
        add("definition", identity, source, f"{namespace}:structure:{source}")
        for member in item["surface_declaration_ids"]:
            surface = surfaces.get(member)
            if surface is None or (surface["source"], surface["definition"]) != (
                source,
                item["definition"],
            ):
                raise ValueError("dangling definition ownership")
            owned[member] += 1
    if owned != Counter(dict.fromkeys(surfaces, 1)):
        raise ValueError("surface ownership coverage mismatch")
    slot_owners: dict[str, str] = {}
    options: dict[tuple[str, str, int, int], dict[str, Any]] = {}
    # Event options are ordered physical observations; repeated names are never dictionary keys.
    option_queues: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for option in raw["event_options"]:
        option_queues[(option["source"], option["definition"])].append(option)
    for identity, item in slots.items():
        owner = definitions.get(item["owner_declaration_id"])
        if (
            owner is None
            or any(
                item[key] != owner[other]
                for key, other in (
                    ("source", "source"),
                    ("definition", "definition"),
                    ("owner_definition_index", "definition_index"),
                    ("owner_declaration_occurrence", "declaration_occurrence"),
                )
            )
            or identity != digest((item["owner_declaration_id"], item["option_index"]))
        ):
            raise ValueError("dangling slot owner or identity")
        matching = [
            option
            for option in option_queues[(item["source"], item["definition"])]
            if option["option_index"] == item["option_index"]
            and option["source_line"] == item["source_line"]
        ]
        if len(matching) != 1:
            raise ValueError("physical event option ownership ambiguous")
        option = matching[0]
        option_key = (
            item["source"],
            item["owner_declaration_id"],
            item["option_index"],
            item["source_line"],
        )
        options[option_key] = option
        members = item["surface_declaration_ids"]
        if len(members) != max(1, len(option["weight_lines"])):
            raise ValueError("physical slot weight coverage mismatch")
        if item["surface_ids"] != [surfaces[member]["surface_id"] for member in members]:
            raise ValueError("slot surface identity mismatch")
        for member in members:
            if member in slot_owners or member not in owner["surface_declaration_ids"]:
                raise ValueError("duplicate slot member or wrong owner")
            slot_owners[member] = identity
        add("slot", identity, item["source"], f"{namespace}:slot:{identity}")
    if len(options) != len(raw["event_options"]):
        raise ValueError("missing event option slot")
    if set(slot_owners) != {
        key for key, item in surfaces.items() if item["source"].startswith("events/")
    }:
        raise ValueError("event surface ownership mismatch")
    for identity, item in surfaces.items():
        if identity != digest(
            (item["source"], item["definition"], item["field"], item["declaration_occurrence"])
        ):
            raise ValueError("surface declaration identity drift")
        if (
            item["legal"]
            or item["capability"] != "pending"
            or item["status"] != "pending"
            or item["getter"] is not None
            or item["scope_evidence"]
        ):
            raise ValueError("unverified native candidate grants authority")
        group = (
            f"{namespace}:slot:{slot_owners[identity]}"
            if identity in slot_owners
            else f"{namespace}:surface:{identity}"
        )
        add("surface", identity, item["source"], group)
    for identity, item in references.items():
        add("reference", identity, item["source"], f"{namespace}:references:{item['source']}")
    definitions_by_source: dict[str, dict[int, Any]] = defaultdict(dict)
    for item in definitions.values():
        definitions_by_source[item["source"]][item["definition_index"]] = item
    nodes = 0
    syntax_sources: dict[str, Any] = {}
    for source, item in sorted(raw["source_syntax"].items()):
        text = item["syntax_json"]
        if (
            item["source_sha256"] != raw["source_hashes"].get(source)
            or sha(text.encode()) != item["syntax_sha256"]
        ):
            raise ValueError("syntax/source hash drift")
        tree = strict_json(text)
        count = 0
        stack: list[tuple[dict[str, Any], tuple[int, ...]]] = [(tree, ())]
        member_hash = hashlib.sha256()
        top_definitions = dict(definitions_by_source[source])
        definition_index = 0
        while stack:
            node, position = stack.pop()
            if (
                len(position) > MAX_DEPTH
                or node["node_position"] != list(position)
                or node["node_id"] != digest((source, position))
            ):
                raise ValueError("syntax node ownership/identity drift or depth limit")
            count += 1
            nodes += 1
            if nodes > MAX_NODES:
                raise ValueError("syntax node limit")
            member_hash.update((node["node_id"] + "\n").encode())
            kind = node["kind"]
            if kind == "assignment":
                if (
                    len(position) == 1
                    and source.endswith(".txt")
                    and not node["key"].startswith("@")
                ):
                    owner = top_definitions.get(definition_index)
                    if owner is None or (
                        owner["definition"],
                        owner["source_line"],
                        owner["operator"],
                        owner["prefix"],
                        owner["is_block"],
                    ) != (
                        node["key"],
                        node["line"],
                        node["operator"],
                        node["prefix"],
                        node["value"]["kind"] == "block",
                    ):
                        raise ValueError("syntax declaration ownership mismatch")
                    del top_definitions[definition_index]
                if len(position) == 1:
                    definition_index += 1
                stack.append((node["value"], (*position, -1)))
            elif kind == "block":
                stack.extend(
                    (child, (*position, index))
                    for index, child in reversed(list(enumerate(node["items"])))
                )
            elif kind not in {"scalar", "missing_value"}:
                raise ValueError("unknown captured syntax kind")
        if count != item["node_count"] or top_definitions:
            raise ValueError("syntax node/empty definition coverage mismatch")
        syntax_sources[source] = {
            "node_count": count,
            "membership_sha256": member_hash.hexdigest(),
            "syntax_sha256": item["syntax_sha256"],
        }
        add("syntax", source, source, f"{namespace}:structure:{source}")
    for index, item in enumerate(raw["unsupported_structures"]):
        # Preserve the complete observation in the captured shards; its physical occurrence stays distinct.
        add(
            "unclassified",
            digest((index, item)),
            item["source"],
            f"{namespace}:structure:{item['source']}",
        )
    duplicates = [
        f"surface:{key}:{item['ambiguity']}" for key, item in surfaces.items() if item["ambiguity"]
    ]
    duplicate_groups = Counter(
        (item["directory"], item["definition"]) for item in definitions.values()
    )
    duplicates += [
        f"definition:{directory}:{name}:{count}"
        for (directory, name), count in sorted(duplicate_groups.items())
        if count > 1
    ]
    return {
        "schema": 1,
        "source_version": version,
        "baseline_id": raw["baseline_id"],
        "capture_scope_hash": raw["scope_hash"],
        "entries": entries,
        "groups": {key: sorted(members) for key, members in sorted(groups.items())},
        "syntax_sources": syntax_sources,
        "raw_duplicates": sorted(duplicates),
        "unresolved_groups": sorted(groups),
        "node_count": nodes,
        "dlc_ids": sorted(
            source
            for source in raw["source_hashes"]
            if source.startswith("dlc_metadata/")
            or (source.startswith("dlc/") and source.endswith(".dlc"))
        ),
    }


def report_for(
    sources: Any, root_manifest: dict[str, Any], catalog: dict[str, Any]
) -> dict[str, Any]:
    catalog_ref = sources.reference(CATALOG_PATH)
    discoveries = [
        {
            "id": identity,
            "kind": "discovery",
            "origin": "native_projection",
            "identity": identity.removeprefix("D:"),
            "source": {
                **catalog_ref,
                "kind": "json",
                "identity": "entries/" + identity.replace("~", "~0").replace("/", "~1"),
            },
            "goal_ids": GOALS,
        }
        for identity in sorted(catalog["entries"])
    ]
    report = {
        "schema": 1,
        "source_version": catalog["source_version"],
        "source_inputs": [
            sources.reference(path)
            for path in sorted(
                {
                    ROOT_PATH,
                    CATALOG_PATH,
                    *PROJECTOR_INPUTS,
                    *(item["path"] for item in root_manifest["shards"]),
                }
            )
        ]
        + [sources.reference(*node.split("::"), kind="python") for node in CROSSCHECK_NODES],
        "scanned_directories": root_manifest["scanned_directories"],
        "parse_failures": root_manifest["parse_failures"],
        "unrecognized": catalog["unresolved_groups"],
        "duplicates": catalog["raw_duplicates"],
        "discoveries": discoveries,
        "dlc_ids": catalog["dlc_ids"],
        "writer_ids": [],
        "consumer_ids": sorted(
            key for key in catalog["groups"] if ":surface:" in key or ":slot:" in key
        ),
        "crosscheck_receipt_ids": [],
    }
    check_shape(report, INVESTIGATION)
    return report


def import_capture(
    root: Path, capture: Path, *, expected_sha256: str = CAPTURE_SHA256
) -> dict[str, Any]:
    """Write deterministic controlled inputs from one already captured file; never reads a game."""
    size = capture.stat().st_size
    if not 0 < size <= MAX_CAPTURE_BYTES:
        raise ValueError("capture size limit")
    raw = capture.read_bytes()
    if sha(raw) != expected_sha256:
        raise ValueError("fixed capture identity mismatch")
    payload = strict_json(raw)
    catalog = project(payload)
    shards = []
    for offset in range(0, len(raw), CHUNK_BYTES):
        chunk = raw[offset : offset + CHUNK_BYTES]
        packed = pack(chunk)
        path = f"{DIRECTORY}/objects/{sha(packed)}.json.gz"
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.read_bytes() != packed:
            raise ValueError("immutable shard collision")
        destination.write_bytes(packed)
        shards.append(
            {"path": path, "sha256": sha(packed), "bytes": len(chunk), "raw_sha256": sha(chunk)}
        )
    manifest = {
        "schema": 1,
        "format": "a4-lossless-capture-chunks-v1",
        "raw_sha256": expected_sha256,
        "raw_bytes": size,
        "source_version": payload["target_version"],
        "actual_version": payload["actual_version"],
        "baseline_id": payload["baseline_id"],
        "source_hashes": payload["source_hashes"],
        "scanned_directories": payload["scanned_directories"],
        "parse_failures": payload["parse_failures"],
        "shards": shards,
    }
    write_json(root / ROOT_PATH, manifest)
    write_json(root / CATALOG_PATH, catalog)
    from tools.ci.a4_scope import Sources  # noqa: PLC0415

    report = report_for(Sources(root), manifest, catalog)
    write_json(root / REPORT_PATH, report)
    return {
        "raw_bytes": size,
        "shards": len(shards),
        "nodes": catalog["node_count"],
        "discoveries": len(catalog["entries"]),
        "groups": len(catalog["groups"]),
    }


def validate_projection(sources: Any, report: dict[str, Any]) -> dict[str, Any]:
    manifest = sources.json(ROOT_PATH)
    required = {
        "schema",
        "format",
        "raw_sha256",
        "raw_bytes",
        "source_version",
        "actual_version",
        "baseline_id",
        "source_hashes",
        "scanned_directories",
        "parse_failures",
        "shards",
    }
    if (
        set(manifest) != required
        or manifest["schema"] != 1
        or manifest["format"] != "a4-lossless-capture-chunks-v1"
    ):
        raise ValueError("capture root schema")
    if not 0 < manifest["raw_bytes"] <= MAX_CAPTURE_BYTES:
        raise ValueError("capture total size limit")
    if manifest["raw_sha256"] != CAPTURE_SHA256:
        raise ValueError("fixed original capture identity mismatch")
    if len(manifest["shards"]) != (manifest["raw_bytes"] + CHUNK_BYTES - 1) // CHUNK_BYTES:
        raise ValueError("capture shard count mismatch")
    chunks = []
    seen = set()
    total = 0
    for number, item in enumerate(manifest["shards"]):
        if set(item) != {"path", "sha256", "bytes", "raw_sha256"} or item["path"] in seen:
            raise ValueError("duplicate or invalid shard member")
        seen.add(item["path"])
        if item["bytes"] != min(CHUNK_BYTES, manifest["raw_bytes"] - number * CHUNK_BYTES):
            raise ValueError("capture shard boundary mismatch")
        if item["path"] != f"{DIRECTORY}/objects/{item['sha256']}.json.gz":
            raise ValueError("unsafe shard identity or hash cycle")
        packed = sources.read(item["path"])
        if sha(packed) != item["sha256"]:
            raise ValueError("corrupt shard hash")
        chunk = unpack(packed, item["bytes"])
        if sha(chunk) != item["raw_sha256"]:
            raise ValueError("shard raw identity")
        total += len(chunk)
        if total > MAX_CAPTURE_BYTES:
            raise ValueError("oversized capture decompression")
        chunks.append(chunk)
    raw = b"".join(chunks)
    del chunks
    if len(raw) != manifest["raw_bytes"] or sha(raw) != manifest["raw_sha256"]:
        raise ValueError("missing/reordered/truncated capture shard")
    payload = strict_json(raw)
    del raw
    for key in (
        "actual_version",
        "source_hashes",
        "scanned_directories",
        "parse_failures",
        "baseline_id",
    ):
        if payload[key] != manifest[key]:
            raise ValueError("capture root relation drift")
    if payload["target_version"] != manifest["source_version"]:
        raise ValueError("mixed capture version")
    catalog = project(payload)
    del payload
    if catalog != sources.json(CATALOG_PATH):
        raise ValueError("raw projection/catalog membership or ownership mismatch")
    expected = report_for(sources, manifest, catalog)
    expected["crosscheck_receipt_ids"] = report["crosscheck_receipt_ids"]
    if report != expected:
        raise ValueError("projection report/source_inputs closure or code identity mismatch")
    return catalog
