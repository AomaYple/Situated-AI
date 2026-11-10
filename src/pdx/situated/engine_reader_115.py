"""Current defensive-pact count and original barracks-target value evidence."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from . import engine_scope_115

if TYPE_CHECKING:
    from pathlib import Path

NATIVE_VALUES = frozenset({"wanted_army_size_script_value", "wanted_marines_size_script_value"})


def snapshot() -> bytes:
    """Load only this executable's reviewed getter and positive-base guard."""
    path, _, digest = engine_scope_115.manifest("defensive-pact-reader")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("1.15 LJ10 reader: frozen engine evidence drift")
    data = json.loads(raw)
    strategy, identity, strategy_digest = engine_scope_115.manifest("strategy")
    if (
        hashlib.sha256(strategy.read_bytes()).hexdigest() != strategy_digest
        or data["parent_scope_manifest"]["path"] != identity
        or data["parent_scope_manifest"]["sha256"] != strategy_digest
        or data["exe"]["sha256"] != engine_scope_115.EXE_SHA256
        or data["exe"]["bytes"] != engine_scope_115.EXE_BYTES
        or data["runtime"] != "unknown"
        or data["reader"]
        != {
            "engine": "num_defensive_pacts",
            "actor": "country",
            "scope": "root",
            "unit": "treaty_article_count",
            "kind": "number",
            "minimum": 0,
            "parameters": [],
            "argument": None,
            "consumer": "ai_strategy_default.wanted_army_size",
        }
        or data["positive_native_guard"]["readers"]
        != [
            {"engine": name, "scope": "root", "kind": "number", "unit": "barracks_levels"}
            for name in ("wanted_army_size_script_value", "wanted_marines_size_script_value")
        ]
        or data["flag_map"]["is_defensive_pact_index"] != 1
        or data["flag_map"]["complete_object_flags_offset"] != "0xd0"
    ):
        raise ValueError("1.15 LJ10 reader: exact reader or native-value contract drift")
    return raw


def proven_words() -> frozenset[str]:
    """Token discovery only; typed own-Country signatures remain independently strict."""
    snapshot()
    return frozenset({"num_defensive_pacts", *NATIVE_VALUES})


def project_information_readers(readers: dict) -> None:
    """Correct two units in the current view while preserving the historical TOML.

    These named original script values are consumed as barracks targets. There
    is no battalion conversion, and unrelated battalion-valued readers retain
    their existing unit.
    """
    snapshot()
    expected = {
        "native_army_capacity": "wanted_army_size_script_value",
        "native_marine_capacity": "wanted_marines_size_script_value",
    }
    for key, engine in expected.items():
        row = readers[key]
        if row != {"engine": engine, "scope": "root", "unit": "battalions", "kind": "number"}:
            raise ValueError("1.15 LJ10 reader: historical declaration identity drift")
        readers[key] = {**row, "unit": "barracks_levels"}


def verify_game(game: Path) -> tuple[tuple[str, str], ...]:
    """Revalidate this broad compatibility reader closure against installed bytes."""
    from pdx import version_contracts  # noqa: PLC0415

    from . import engine_scope  # noqa: PLC0415

    data = json.loads(snapshot())
    try:
        inputs = {source: (game / source).read_bytes() for source in data["script_hashes"]}
    except OSError as exc:
        raise ValueError("1.15 LJ10 reader: missing installed original") from exc
    _, hashes, verified = engine_scope._verified_manifest(
        game,
        inputs,
        *engine_scope_115.manifest("defensive-pact-reader"),
        "1.15 LJ10 reader",
    )
    if not verified:
        raise ValueError("1.15 LJ10 reader: installed source or executable drift")
    with version_contracts.select_version("1.15.0"):
        parent = engine_scope.verify_strategy_game(game)
    return tuple(
        sorted({**dict(parent.source_hashes), **dict(hashes), **data["script_hashes"]}.items())
    )
