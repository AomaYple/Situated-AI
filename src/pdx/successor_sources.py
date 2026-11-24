"""Bind an independently reviewed successor archive to recoverable authored Git inputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from pdx import distribution

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def object_from_json(raw: bytes) -> dict[str, Any]:
    record = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(record, dict):
        raise ValueError("Expected a JSON object")
    return record


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def check_reviewed_sources(
    members: Mapping[str, bytes],
    listed: Mapping[str, Any],
    locked_files: Mapping[str, str],
    locked_sources: Mapping[str, str],
    read_blob: Callable[[str], bytes],
) -> None:
    """Recover authored inputs and check the canonical delivery bytes against the ZIP."""
    generated = members.keys() - {"README.md"}
    if generated != locked_files.keys():
        raise ValueError("Successor lock does not describe the verified candidate payload")
    required = {"README.md", distribution.METADATA_NAME}
    if not required <= members.keys():
        raise ValueError("Successor payload requires launcher metadata and README")
    if distribution.THUMBNAIL_NAME in members:
        distribution._validate_thumbnail(members[distribution.THUMBNAIL_NAME])
    repository: dict[str, str | bytes] = {}
    for name, raw in members.items():
        parts = PurePosixPath(name).parts
        is_script = len(parts) >= 3 and parts[0] == "common" and name.endswith(".txt")
        is_language = len(parts) >= 3 and parts[0] == "localization" and name.endswith(".yml")
        if (
            name not in required | {distribution.THUMBNAIL_NAME} and not (is_script or is_language)
        ) or "probe" in name.casefold():
            raise ValueError(f"Invalid generated member: {name}")
        record = listed[name]
        if record.get("origin") != "original":
            raise ValueError(f"Member lacks reviewed original provenance: {name}")
        sources = record.get("source_files")
        if not isinstance(sources, dict) or not sources:
            raise ValueError(f"Member lacks recoverable original source: {name}")
        distribution._validate_paths(list(sources))
        generated_path = f"mod/{name}"
        material = generated_path if name in generated else record.get("repository_path")
        if not isinstance(material, str):
            raise ValueError(f"Member lacks a repository path: {name}")
        distribution._validate_paths([material])
        if name == "README.md" and material not in sources:
            raise ValueError("README lacks a reviewed authored Git blob")
        source = read_blob(material)
        if name in locked_files and sha256(source) != locked_files[name]:
            raise ValueError(f"Member Git bytes differ from successor lock: {name}")
        for path, digest in sources.items():
            if path == material:
                if name in generated and name != distribution.THUMBNAIL_NAME:
                    raise ValueError(f"Generated member requires its authored inputs: {name}")
            elif locked_sources.get(path) != digest:
                raise ValueError(f"Member source is absent from the successor lock: {path}")
            if sha256(read_blob(path)) != digest:
                raise ValueError(f"Member source Git bytes differ from review: {path}")
        if name == distribution.THUMBNAIL_NAME:
            repository[name] = source
            continue
        decoded = source.decode("utf-8")
        if "\ufeff" in decoded or "\r" in decoded:
            raise ValueError(f"Invalid repository BOM/LF: {material}")
        repository[name] = decoded
        if not raw:
            raise ValueError(f"Empty package member: {name}")
    expected = distribution.payloads(distribution._release_files(repository))
    for name, raw in members.items():
        if raw != expected[name]:
            raise ValueError(f"Member delivery bytes differ from Git/lock projection: {name}")
