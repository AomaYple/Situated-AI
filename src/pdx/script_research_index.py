"""Store the declared script research index alongside the occurrence locators."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable, Iterable, Set
    from typing import Any

    from .script_research import ScriptDefinition, ScriptReference


def create_tables(connection: sqlite3.Connection) -> None:
    # Source hash, path and stable ordinal address remain in the shared occurrence row.
    connection.executescript("""
        CREATE TABLE script_sources(
            source TEXT PRIMARY KEY REFERENCES sources(path), definition_kind TEXT
        );
        CREATE INDEX script_source_definition_kind ON script_sources(definition_kind,source);
        CREATE TABLE script_definitions(
            occurrence_id TEXT PRIMARY KEY REFERENCES occurrences(id),
            kind TEXT NOT NULL, name TEXT NOT NULL
        );
        CREATE INDEX script_definition_lookup ON script_definitions(name,occurrence_id);
        CREATE TABLE script_references(
            occurrence_id TEXT REFERENCES occurrences(id) NOT NULL,
            ordinal INTEGER NOT NULL, line INTEGER NOT NULL, name TEXT,
            requested_kind TEXT, syntax TEXT NOT NULL, status TEXT NOT NULL,
            target_definition_sources_incomplete INTEGER NOT NULL,
            PRIMARY KEY(occurrence_id,ordinal)
        );
        CREATE INDEX script_reference_lookup ON script_references(name,occurrence_id,ordinal);
    """)


def add_source(connection: sqlite3.Connection, source: str, definition_kind: str | None) -> None:
    connection.execute("INSERT INTO script_sources VALUES(?,?)", (source, definition_kind))


def add_source_rows(
    connection: sqlite3.Connection,
    definitions: Iterable[ScriptDefinition],
    references: Iterable[ScriptReference],
    incomplete_definition_kinds: Set[str],
    occurrence_id: Callable[[str, tuple[int, ...]], str],
) -> None:
    connection.executemany(
        "INSERT INTO script_definitions VALUES(?,?,?)",
        ((occurrence_id(row.source, row.address), row.kind, row.name) for row in definitions),
    )

    def reference_row(
        ordinal: int, row: ScriptReference
    ) -> tuple[str, int, int, str | None, str | None, str, str, bool]:
        incomplete = row.requested_kind in incomplete_definition_kinds
        status = "unknown" if incomplete and row.status in {"candidate", "missing"} else row.status
        return (
            occurrence_id(row.source, row.address),
            ordinal,
            row.line,
            row.name,
            row.requested_kind,
            row.syntax,
            status,
            incomplete,
        )

    connection.executemany(
        "INSERT INTO script_references VALUES(?,?,?,?,?,?,?,?)",
        (reference_row(ordinal, row) for ordinal, row in enumerate(references)),
    )


def reference_cursor(value: str) -> tuple[str, int]:
    occurrence_id, _, ordinal = value.partition(":")
    if (
        not re.fullmatch(r"[0-9a-f]{64}", occurrence_id)
        or not ordinal.isascii()
        or not ordinal.isdigit()
    ):
        raise ValueError("引用续页位置须使用 occurrence_id:ordinal")
    result = int(ordinal)
    if result > 2**63 - 1:
        raise ValueError("引用续页位置的 ordinal 超出 SQLite 整数范围")
    return occurrence_id, result


def query_symbol(
    connection: sqlite3.Connection,
    name: str,
    *,
    limit: int,
    after: tuple[str, int] = ("", -1),
) -> dict[str, object]:
    """Page by stable source locator and the syntax row ordinal."""
    definition_rows = connection.execute(
        """SELECT d.occurrence_id,d.kind,d.name,o.source,o.source_sha256,
                  o.address,o.path,o.line,o.parse_status
           FROM script_definitions d JOIN occurrences o ON o.id=d.occurrence_id
           WHERE d.name=?
           ORDER BY d.occurrence_id LIMIT ?""",
        (name, limit),
    )
    reference_rows = connection.execute(
        """SELECT r.*,o.source,o.source_sha256,o.address,o.path,o.parse_status
           FROM script_references r JOIN occurrences o ON o.id=r.occurrence_id
           WHERE r.name=? AND (r.occurrence_id,r.ordinal)>(?,?)
           ORDER BY r.occurrence_id,r.ordinal LIMIT ?""",
        (name, *after, limit),
    )
    return {
        "name": name,
        "status": "static_candidates",
        "definitions": [_location(row) for row in definition_rows],
        "definition_count": connection.execute(
            "SELECT count(*) FROM script_definitions WHERE name=?", (name,)
        ).fetchone()[0],
        "references": [_location(row) for row in reference_rows],
    }


def query_source(
    connection: sqlite3.Connection,
    source: str,
    *,
    limit: int,
    after: tuple[str, int] = ("", -1),
) -> dict[str, object]:
    state = connection.execute(
        """SELECT s.parse_status,ss.source AS scanned
           FROM sources s LEFT JOIN script_sources ss ON s.path=ss.source WHERE s.path=?""",
        (source,),
    ).fetchone()
    if state is None:
        status = "unknown_source"
    elif state["scanned"] is None:
        status = "not_attempted"
    else:
        status = state["parse_status"]
    rows = connection.execute(
        """SELECT r.*,o.source,o.source_sha256,o.address,o.path,o.parse_status
           FROM occurrences o JOIN script_references r ON o.id=r.occurrence_id
           WHERE o.source=? AND (r.occurrence_id,r.ordinal)>(?,?)
           ORDER BY r.occurrence_id,r.ordinal LIMIT ?""",
        (source, *after, limit),
    )
    return {"source": source, "status": status, "references": [_location(row) for row in rows]}


def incomplete_definition_sources(connection: sqlite3.Connection) -> list[dict[str, object]]:
    return [
        dict(row)
        for row in connection.execute(
            """SELECT ss.definition_kind,s.path AS source,s.sha256,s.parse_status
               FROM script_sources ss JOIN sources s ON s.path=ss.source
               WHERE ss.definition_kind IS NOT NULL AND s.parse_status<>'complete'
               ORDER BY ss.definition_kind,s.path"""
        )
    ]


def _location(row: sqlite3.Row) -> dict[str, Any]:
    location = dict(row)
    location["address"] = json.loads(location["address"])
    location["path"] = json.loads(location["path"])
    if "target_definition_sources_incomplete" in location:
        location["target_definition_sources_incomplete"] = bool(
            location["target_definition_sources_incomplete"]
        )
    return location
