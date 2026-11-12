"""Corroborate R2 writers against exact native inputs and actual output ASTs.

Metadata describes the candidate; it grants no interface permission. Each
binding below also proves its complete generated expression, insertion position,
unchanged native numeric body and pinned reader evidence. No game state is read.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pdx import version_contracts
from pdx.model import Assignment, Block
from pdx.parser import parse_text

from . import network_profile, production_profile, r2_reader_authority
from .profile_configuration import ProfileConfiguration

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .action_network import NetworkProgram
    from .native_treatments import _AuditMetadata
    from .vanilla_inventory import VanillaSurface


@dataclass(frozen=True, slots=True)
class NetworkProgramBinding:
    consumer: str
    source: str
    definition: str
    field: str
    source_line: int
    program: NetworkProgram
    production_sha256: str
    overlay_sha256: str
    metadata_sha256: str
    native_sha256: str
    native_ast_sha256: str
    effective_ast_sha256: str
    reader_evidence: tuple[tuple[str, str], ...]


def _node(text: str, keys: tuple[str, ...]) -> Assignment:
    parsed = parse_text(text)
    if parsed.errors:
        raise ValueError("R2 production source cannot be parsed")
    body = parsed.root
    selected = None
    for key in keys:
        nodes = body.all(key)
        value = nodes[0].value if len(nodes) == 1 else None
        if (
            len(nodes) != 1
            or nodes[0].op != "="
            or nodes[0].prefix is not None
            or not isinstance(value, Block)
        ):
            raise ValueError("R2 physical consumer is missing, duplicated or not ordinary")
        selected = nodes[0]
        body = value
    assert selected is not None
    return selected


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def production_bindings(
    generated: Mapping[str, str | bytes],
    native_sources: Mapping[str, bytes],
    *,
    metadata: _AuditMetadata | None = None,
) -> tuple[NetworkProgramBinding, ...]:
    """Bind only the finite R2 programs present in this exact candidate.

    Frozen source bytes establish reader authority even for evidence files that
    are outside the AI inventory. Any independently supplied copy must agree.
    The full-package caller separately verifies the installed reader authority.
    Missing R2 metadata cannot hide a marked output; unmarked modifications
    receive no proof and remain subject to the ordinary native audit.
    """
    from .native_treatments import _AuditMetadata, _digest  # noqa: PLC0415

    def text(value: str | bytes) -> str:
        return value.decode("utf-8") if isinstance(value, bytes) else value

    raw = generated.get(".metadata/metadata.json", "{}")
    owner = metadata or _AuditMetadata(raw)
    document = owner.document(raw, utf8_text=True)
    declared = document.get("action_network")
    marked = {
        name: text(value)
        for name, value in generated.items()
        if name.endswith(".txt") and "# SITAI POLICY" in text(value)
    }
    if declared is None:
        if marked:
            raise ValueError("R2 output exists without its candidate declaration")
        return ()
    if version_contracts.active_version() != "1.15.1":
        raise ValueError("complete R2 native audit requires the current release contract")
    selected = document.get("configuration")
    if not isinstance(selected, dict):
        raise ValueError("R2 candidate lacks its resolved configuration")
    domains = selected.get("domains")
    if not isinstance(domains, list) or len(set(domains)) != len(domains):
        raise ValueError("R2 candidate domain configuration is invalid")
    configuration = ProfileConfiguration(selected["core"], frozenset(domains), selected["mode"])
    if _canonical(configuration.identity()) != _canonical(selected):
        raise ValueError("R2 resolved configuration differs from the strict contract")
    baseline = production_profile.baseline_root()
    profile = production_profile.load_profile(baseline)
    r2_reader_authority.verify_frozen()
    evidence_root = r2_reader_authority.frozen_root()
    evidence = {}
    for evidence_path, expected_sha256 in r2_reader_authority.source_hashes().items():
        if not evidence_path.startswith("game/"):
            continue
        source = evidence_path.removeprefix("game/")
        frozen = (evidence_root / evidence_path).read_bytes()
        if source in native_sources and native_sources[source] != frozen:
            raise ValueError(f"R2 supplied native reader evidence differs: {source}")
        evidence[source] = expected_sha256
    programs = {
        program.network.actions[0].definition.consumer_id: program
        for program in network_profile.compile_profile(profile, configuration=configuration)
    }
    writers = [
        {
            "id": row.id,
            "source": row.source.removeprefix("game/"),
            "definition": row.definition,
            "field": list(row.field),
            "writer": "R2/action-network-v2",
            "enabled": row.id in programs,
        }
        for row in profile.declarations
    ]
    expected = {
        "architecture": "R2/action-network-v2",
        "source": network_profile.source_path().relative_to(production_profile.ROOT).as_posix(),
        "source_sha256": hashlib.sha256(network_profile.source_path().read_bytes()).hexdigest(),
        "evidence": "static_symbolic_lowering",
        "runtime": "unknown",
        "integration": "complete-production-single-writer",
        "writers": writers,
        "legacy_school_migration": network_profile.SCHOOL_MIGRATION,
        "school_numeric_policy": network_profile.SCHOOL_NUMERIC_POLICY,
        "future_domain_depth": "not_claimed",
    }
    if _canonical(declared) != _canonical(expected):
        raise ValueError("R2 candidate declaration differs from current typed semantics")
    result = []
    for row in profile.declarations:
        source = row.source.removeprefix("game/")
        original_bytes = (baseline / row.source).read_bytes()
        if native_sources.get(source) != original_bytes:
            raise ValueError(f"R2 native write-point bytes are missing or changed: {source}")
        original = original_bytes.decode("utf-8-sig")
        content = text(generated[source])
        path = (row.definition, *row.field)
        native = _node(original, path)
        effective = _node(content, path)
        occurrences = [name for name, value in marked.items() if f"BEGIN {row.id}" in value]
        if row.id not in programs:
            if occurrences or _digest(native) != _digest(effective):
                raise ValueError(f"R2 disabled writer still changes its native field: {row.id}")
            continue
        program = programs[row.id]
        overlay = network_profile.render_program(program)
        marker = re.compile(
            rf"\n\t# SITAI POLICY 1\.15\.1 BEGIN {re.escape(row.id)}\n"
            rf"(?P<body>[\s\S]*?)\t# SITAI POLICY 1\.15\.1 END {re.escape(row.id)}\n"
        )
        matches = list(marker.finditer(content))
        if (
            occurrences != [source]
            or len(matches) != 1
            or content.count(f"BEGIN {row.id}") != 1
            or content.count(f"END {row.id}") != 1
            or matches[0].group("body") != overlay
        ):
            raise ValueError(f"R2 actual expression or unique physical source differs: {row.id}")
        restored = marker.sub("", content)
        if _digest(_node(restored, path)) != _digest(native):
            raise ValueError(f"R2 changed the complete native numeric body: {row.id}")
        if production_profile._insert_policy(restored, row, overlay) != content:
            raise ValueError(f"R2 expression moved across an ordered native statement: {row.id}")
        result.append(
            NetworkProgramBinding(
                row.id,
                source,
                row.definition,
                ".".join(row.field),
                native.line,
                program,
                hashlib.sha256(content.encode()).hexdigest(),
                hashlib.sha256(overlay.encode()).hexdigest(),
                owner.sha256(raw),
                hashlib.sha256(original_bytes).hexdigest(),
                _digest(native),
                _digest(effective),
                tuple(sorted(evidence.items())),
            )
        )
    return tuple(result)


def native_issue(binding: NetworkProgramBinding, surface: VanillaSurface) -> str | None:
    """Require the independent native inventory to corroborate the interface."""
    identity = surface.source, surface.definition, surface.field
    if identity != (binding.source, binding.definition, binding.field):
        return "network_native_identity_mismatch"
    if surface.source_line != binding.source_line or surface.ambiguity or not surface.legal:
        return "network_native_declaration_unproven"
    expected = {
        "a0-econ-road": ("state", "scope:country=country", "relative_weight"),
        "a0-pol-schools": ("country", "definition_only:institution_type", "additive_score"),
        "a0-dip-relations": ("country", "scope:target=country", "score"),
    }
    if (surface.actor_scope, surface.target_scope, surface.operation) != expected.get(
        binding.consumer
    ):
        return "network_native_context_unproven"
    if surface.capability != "direct":
        return "network_native_capability_unproven"
    return None


def dependency_proof(binding: NetworkProgramBinding) -> dict[str, Any]:
    return {
        "family": "network_program",
        "definition": binding.consumer,
        "status": "proven_generated",
        "native_source": binding.source,
        "effective_source": binding.source,
        "native_source_sha256": binding.native_sha256,
        "effective_source_sha256": binding.production_sha256,
        "native_ast_sha256": binding.native_ast_sha256,
        "effective_ast_sha256": binding.effective_ast_sha256,
        "overlay_sha256": binding.overlay_sha256,
        "metadata_sha256": binding.metadata_sha256,
        "reader_sources_verified": dict(binding.reader_evidence),
        "interface_authorized": True,
        "business_complete": False,
    }
