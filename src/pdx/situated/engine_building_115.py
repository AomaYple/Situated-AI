"""Exact missing building scores proven against the current executable.

The template/self selection remains intact. Only the selected score is ever
evaluated; this evidence grants no claim about an unselected definition.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, cast

from . import engine_scope_115

if TYPE_CHECKING:
    from pathlib import Path


def snapshot() -> bytes:
    """Load reviewed static permission and its separate exact native AST identity."""
    from pdx import decision_adapters  # noqa: PLC0415

    path, _, digest = engine_scope_115.manifest("building-default")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("1.15 building default: frozen engine evidence drift")
    data = json.loads(raw)
    exe_sha256, exe_bytes = engine_scope_115.executable_identity()
    native = decision_adapters.native_authority_115()
    expected_fields = [
        {"source": row["source"], "field": row["field"], "parent": row["parents"][0]}
        for row in native["fields"]
        if row["kind"] == "missing_declared_default"
    ]
    contract = data["contracts"][0]
    if (
        data["exe"]["sha256"] != exe_sha256
        or data["exe"]["bytes"] != exe_bytes
        or data["runtime"] != "unknown"
        or data["native_authority"]
        != {
            "path": decision_adapters.native_authority_path()
            .relative_to(engine_scope_115.ROOT)
            .as_posix(),
            "sha256": decision_adapters.native_authority_sha256(),
        }
        or data["implicit_buildings"] != expected_fields
        or len(expected_fields) != 11
        or len(data["contracts"]) != 1
        or contract["field"] != "ai_value"
        or contract["actor"] != "state"
        or contract["capability"] != "exact_default_initializer"
        or contract["selection"] != "valid_template_else_self"
        or contract["default_value"] != 1000
        or {row["define"]: row["value"] for row in contract["default_branches"]}
        != {
            "NAI.PRODUCTION_BUILDING_BASE_VALUE": 1000,
            "NAI.GOVERNMENT_BUILDING_BASE_VALUE": 1000,
        }
    ):
        raise ValueError("1.15 building default: exact initializer contract drift")
    return raw


def authorized_fields() -> frozenset[tuple[str, str]]:
    """Permission applies to these eleven absent fields, not other numeric shapes."""
    data = json.loads(snapshot())
    return frozenset((row["source"], row["field"]) for row in data["implicit_buildings"])


def verify_game(game: Path) -> tuple[tuple[str, str], ...]:
    """Require current raw sources, executable identity, and every observed byte."""
    from . import engine_scope  # noqa: PLC0415

    data = cast("dict[str, Any]", json.loads(snapshot()))
    try:
        inputs = {source: (game / source).read_bytes() for source in data["script_hashes"]}
    except OSError as exc:
        raise ValueError("1.15 building default: missing installed original") from exc
    _, hashes, verified = engine_scope._verified_manifest(
        game,
        inputs,
        *engine_scope_115.manifest("building-default"),
        "1.15 building default",
    )
    if not verified:
        raise ValueError("1.15 building default: installed source or executable drift")
    return tuple(sorted({**dict(hashes), **data["script_hashes"]}.items()))
