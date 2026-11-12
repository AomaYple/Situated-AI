"""Regenerable native consumer/dependency catalog, independent of Mod coverage.

The catalog records exact native declarations and documentary statements. Neither
discovery rules nor a resolved script symbol grant engine scope/write permission.
The previous version's frozen inventory and production generation lock are never
inputs. Every input byte is checked against the independent version inventory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_bytes
from pdx.situated.version_inventory import CONTENT_ROOTS, TEXT_EXTENSIONS, canonical_json
from pdx.version_contracts import active_version

if TYPE_CHECKING:
    from collections.abc import Iterator

SCHEMA = "situated-ai.native-consumer-catalog/1"
SYMBOL_CATEGORIES = {
    "script_values": "script_value",
    "scripted_values": "script_value",
    "scripted_triggers": "scripted_trigger",
    "scripted_effects": "scripted_effect",
}
# Map containers are structural, and never replace their individual native leaves.
# This is a syntax routing rule, not the former version's semantic/scope approval.
MAP_FIELDS = frozenset(
    {
        "building_group_weights",
        "goods_stances",
        "institution_scores",
        "secret_goal_scores",
        "secret_goal_weights",
        "wargoal_scores",
        "wargoal_weights",
        "strategic_region_scores",
        "strategic_region_stance_type_scores",
        "liberate_country_scores",
        "treaty_category_scores",
        "ai_ship_category_weights",
        "combat_unit_group_weights",
        "fleet_compositions",
        "strait_scores",
        "ai_construction_targets",
    }
)
EXPRESSION_FIELDS = frozenset(
    {
        "value",
        "base",
        "add",
        "subtract",
        "multiply",
        "divide",
        "min",
        "max",
        "if",
        "else_if",
        "else",
        "limit",
        "always",
        "exists",
        "NOT",
        "OR",
        "AND",
        "NOR",
        "NAND",
        "trigger",
        "score",
        "potential",
    }
)
NUMERIC_FIELDS = frozenset(
    {"value", "add", "subtract", "multiply", "divide", "min", "max", "base", "weight", "score"}
)
# Explicit AI fields in native content categories, irrespective of ai_ heuristic
# candidates in the earlier raw inventory. Unlisted categories remain unresolved
# unless their native documentation explicitly describes the exact field.
AI_FIELD_CATEGORIES = frozenset(
    {
        "buildings",
        "building_groups",
        "decrees",
        "laws",
        "law_groups",
        "institutions",
        "diplomatic_actions",
        "diplomatic_plays",
        "diplomatic_pacts",
        "subject_types",
        "company_types",
        "company_charter_types",
        "commander_orders",
        "combat_unit_types",
        "decisions",
        "journal_entries",
        "government_types",
        "interest_groups",
        "ideologies",
        "power_bloc_identities",
        "power_bloc_principles",
        "power_bloc_principle_groups",
        "production_methods",
        "production_method_groups",
        "technologies",
        "mobilization_options",
        "treaty_articles",
        "treaty_article_types",
        "treaty_categories",
        "war_goals",
        "wargoals",
        "country_formations",
        "country_creation",
        "grievance_types",
        "grievances",
        "character_interactions",
        "political_movements",
        "military_formations",
    }
)
_DOC_FIELD = re.compile(r"^\s*(?:#\s*)?([\w]+)\s*(?:=|\s{2,})")
_DOC_AI = re.compile(r"\bAI\b|\bai\b|score|weight|selection|prioriti[sz]", re.IGNORECASE)
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
_EXPLICIT_REF = re.compile(r"(?:script(?:ed)?_value|scripted_trigger|scripted_effect):([\w$]+)")
_PARAMETER = re.compile(r"\$[A-Za-z_0-9]+\$")


def _hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _category(path: str) -> str:
    parts = PurePosixPath(path).parts
    return parts[parts.index("common") + 1] if "common" in parts[:-1] else "outside_common"


def _walk(
    block: Block, address: tuple[int, ...] = (), parents: tuple[str, ...] = ()
) -> Iterator[tuple[Assignment | Scalar, tuple[int, ...], tuple[str, ...]]]:
    for index, item in enumerate(block.items):
        location = (*address, index)
        if isinstance(item, Assignment):
            yield item, location, parents
            if isinstance(item.value, Block):
                yield from _walk(item.value, location, (*parents, item.full_key))
        elif isinstance(item, Scalar):
            yield item, location, parents
        elif isinstance(item, Block):
            yield from _walk(item, location, parents)


def _source(
    path: str, sha: str, item: Assignment | Scalar, address: tuple[int, ...]
) -> dict[str, Any]:
    return {"path": path, "sha256": sha, "line": item.line, "address": list(address)}


def _checked_path(installation: Path, relative: str) -> Path:
    parts = PurePosixPath(relative).parts
    if (
        not parts
        or PurePosixPath(relative).is_absolute()
        or any(part in {"..", "."} or ":" in part or "\\" in part for part in parts)
    ):
        raise ValueError(f"invalid inventory path: {relative}")
    path = installation
    for part in parts:
        path /= part
        if path.is_symlink() or path.resolve() != path.absolute():
            raise ValueError(f"linked inventory path: {relative}")
    return path


def _current_content_paths(installation: Path) -> set[str]:
    """Return eligible native files currently present under declared content roots.

    This deliberately mirrors the inventory scanner's conservative suffix rule.  It
    catches a new text/PDX file added after inventory creation while leaving mods,
    binaries and media outside the static native scope.
    """
    paths: set[str] = set()

    def on_error(error: OSError) -> None:
        raise ValueError(f"native content enumeration failed: {error.filename}") from error

    for root_name in CONTENT_ROOTS:
        root = installation / root_name
        if not root.is_dir():
            continue
        if root.is_symlink() or root.resolve() != root.absolute():
            raise ValueError(f"linked native content root: {root_name}")
        for directory, directories, filenames in os.walk(root, followlinks=False, onerror=on_error):
            for name in [*directories, *filenames]:
                path = Path(directory) / name
                relative = path.relative_to(installation).as_posix()
                if path.is_symlink() or path.resolve() != path.absolute():
                    raise ValueError(f"linked native content: {relative}")
            for name in filenames:
                path = Path(directory) / name
                if path.suffix.lower() in TEXT_EXTENSIONS:
                    paths.add(path.relative_to(installation).as_posix())
    return paths


def _documents(
    records: dict[str, dict[str, Any]], inputs: dict[str, bytes]
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    result: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for path, raw in sorted(inputs.items()):
        if not path.endswith(".md") or _category(path) == "outside_common":
            continue
        try:
            lines = raw.decode("utf-8-sig").splitlines()
        except UnicodeDecodeError:
            continue  # Failure already retained from the input inventory.
        for index, line in enumerate(lines):
            match = _DOC_FIELD.match(line)
            if not match:
                continue
            field = match.group(1)
            # Preserve the paragraph preceding the declaration, including scope
            # statements; do not promote a nearby statement to engine permission.
            start = max(0, index - 6)
            snippet = "\n".join(lines[start : index + 2])
            result[_category(path), field].append(
                {
                    "kind": "native_documentation",
                    "path": path,
                    "sha256": records[path]["sha256"],
                    "line": index + 1,
                    "context_start_line": start + 1,
                    "text": snippet,
                    "claim": "native_documentary_statement_only",
                }
            )
    return result


def _evidence(
    path: str, sha: str, item: Assignment, lines: list[str], docs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    evidence = list(docs)
    index = item.line - 1
    # Contiguous preceding comments and the declaration's own inline comment.
    start = index
    while start > 0 and lines[start - 1].lstrip().startswith("#"):
        start -= 1
    selected = lines[start:index]
    if 0 <= index < len(lines) and "#" in lines[index]:
        selected = [*selected, lines[index]]
    if selected:
        evidence.append(
            {
                "kind": "native_inline_comment",
                "path": path,
                "sha256": sha,
                "line": start + 1,
                "text": "\n".join(selected),
                "claim": "native_comment_only",
            }
        )
    # File headers commonly document AI weights (decrees) without an assignment.
    for line_index, line in enumerate(lines[:40]):
        if line.lstrip().startswith("#") and re.match(
            rf"^\s*#\s*{re.escape(item.key)}(?:\s|=)", line
        ):
            evidence.append(
                {
                    "kind": "native_header_comment",
                    "path": path,
                    "sha256": sha,
                    "line": line_index + 1,
                    "text": line,
                    "claim": "native_comment_only",
                }
            )
    return evidence


def _frontier(
    item: Assignment, field: tuple[str, ...], address: tuple[int, ...], *, mapped: bool = False
) -> Iterator[tuple[Assignment, tuple[str, ...], tuple[int, ...], str]]:
    if isinstance(item.value, Block) and (mapped or item.key in MAP_FIELDS):
        children = [
            (index, child)
            for index, child in enumerate(item.value.items)
            if isinstance(child, Assignment) and not child.is_variable
        ]
        expression = any(
            child.key in EXPRESSION_FIELDS or child.key.startswith("scope:")
            for _, child in children
        )
        if children and not expression:
            yield item, field, address, "observational"
            for index, child in children:
                yield from _frontier(
                    child, (*field, child.full_key), (*address, index), mapped=True
                )
            return
        if mapped and any(child.key == "score" for _, child in children):
            yield item, field, address, "observational"
            for index, child in children:
                if child.key in {"score", "trigger", "potential"}:
                    yield (
                        child,
                        (*field, child.full_key),
                        (*address, index),
                        ("direct_candidate" if child.key == "score" else "observational"),
                    )
            return
    yield item, field, address, "direct_candidate"


def _consumer(
    path: str,
    record: dict[str, Any],
    definition: str,
    item: Assignment,
    field: tuple[str, ...],
    address: tuple[int, ...],
    classification: str,
    rule: str,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    source = _source(path, record["sha256"], item, address)
    value = item.value
    return {
        "consumer_id": _hash([path, list(address)]),
        "source": source,
        "definition": definition,
        "field": ".".join(field),
        "category": _category(path),
        "classification": classification,
        "discovery_rule": rule,
        "source_validity": record["parse_status"],
        "operator": item.op,
        "value_kind": "block" if isinstance(value, Block) else "scalar",
        "scalar": value.unquoted if isinstance(value, Scalar) else None,
        "legality": "unknown",
        "evidence": evidence,
        "semantics": {
            "actor_scope": "unknown",
            "target_scope": "unknown",
            "operation": "unknown",
            "zero_behavior": "unknown",
            "merge_behavior": "unknown",
            "tail_behavior": "unknown",
            "evaluation_timing": "unknown",
            "getter": "unknown",
            "engine_validation": "unknown",
        },
        "native_disposition": "native_retained",
        "preservation": "retain_original_source_bytes_until_consumer_contract_is_reproved",
        "dependencies": {"reference_ids": [], "status": "unknown"},
    }


def _discover_consumers(
    path: str,
    record: dict[str, Any],
    root: Block,
    lines: list[str],
    docs: dict[tuple[str, str], list[dict[str, Any]]],
    heuristics: dict[tuple[int, ...], dict[str, Any]],
) -> list[dict[str, Any]]:
    category = _category(path)
    rows: dict[tuple[int, ...], dict[str, Any]] = {}

    def add(item: Assignment, field: tuple[str, ...], address: tuple[int, ...], rule: str) -> None:
        for leaf, leaf_field, leaf_address, classification in _frontier(item, field, address):
            evidence = _evidence(
                path, record["sha256"], item, lines, docs.get((category, item.key), [])
            )
            rows[leaf_address] = _consumer(
                path,
                record,
                definition,
                leaf,
                leaf_field,
                leaf_address,
                classification,
                rule,
                evidence,
            )

    for definition_index, declaration in enumerate(root.items):
        if not isinstance(declaration, Assignment) or declaration.is_variable:
            continue
        definition = declaration.full_key
        if not isinstance(declaration.value, Block):
            continue
        for item, address, parents in _walk(declaration.value, (definition_index,), (definition,)):
            if not isinstance(item, Assignment) or item.is_variable:
                continue
            field = (*parents[1:], item.full_key)
            direct_child = len(parents) == 1 or parents[1:] == ("game_data",)
            if category.startswith("ai_") and direct_child and item.key not in {"icon", "type"}:
                add(item, field, address, "explicit_native_ai_category_field")
            elif item.key == "ai" and isinstance(item.value, Block):
                rows[address] = _consumer(
                    path,
                    record,
                    definition,
                    item,
                    field,
                    address,
                    "observational",
                    "explicit_native_ai_block_container",
                    [],
                )
                for index, child in enumerate(item.value.items):
                    if isinstance(child, Assignment) and not child.is_variable:
                        add(
                            child,
                            (*field, child.full_key),
                            (*address, index),
                            "explicit_native_ai_block_field",
                        )
            elif direct_child and category in AI_FIELD_CATEGORIES and item.key.startswith("ai_"):
                add(item, field, address, "explicit_native_content_category_ai_field")
            elif direct_child and any(
                _DOC_AI.search(doc["text"]) for doc in docs.get((category, item.key), [])
            ):
                add(item, field, address, "native_documentation_scored_field_candidate")
            if address in heuristics and address not in rows:
                parent_addresses = [address[:length] for length in range(1, len(address))]
                inside = any(
                    prefix in rows and rows[prefix]["classification"] == "direct_candidate"
                    for prefix in parent_addresses
                )
                rows[address] = _consumer(
                    path,
                    record,
                    definition,
                    item,
                    field,
                    address,
                    "observational" if inside or category in SYMBOL_CATEGORIES else "unresolved",
                    "raw_inventory_heuristic_without_consumer_contract",
                    [],
                )
    return list(rows.values())


def _symbol_references(
    item: Assignment | Scalar, names: set[str], parents: tuple[str, ...]
) -> list[tuple[str, str, str, str | None]]:
    """Return symbol, expression, syntax, requested kind; keep unknown explicit calls."""
    result: list[tuple[str, str, str, str | None]] = []
    if isinstance(item, Assignment):
        if item.key in names and parents:
            result.append((item.key, item.full_key, "assignment_key_call", None))
        elif parents and item.key.endswith(("_scripted_trigger", "_scripted_effect")):
            result.append((item.key, item.full_key, "unresolved_call_shaped_key", None))
        value = item.value
        if not isinstance(value, Scalar):
            return result
        expression = value.unquoted
        numeric = item.key in NUMERIC_FIELDS
        requested = SYMBOL_CATEGORIES.get(
            item.key, item.key if item.key.startswith("scripted_") else None
        )
    else:
        expression = item.unquoted
        numeric = bool(parents and parents[-1] in NUMERIC_FIELDS)
        requested = None
    quoted = (isinstance(item, Scalar) and item.quoted) or (
        isinstance(item, Assignment) and isinstance(item.value, Scalar) and item.value.quoted
    )
    if quoted:
        # A quoted token can be a localization/path/string mention. Preserve
        # identifier-shaped names as observations, but never resolve them as
        # executable calls, including explicit ``scripted_value:`` prefixes.
        field_name = item.key if isinstance(item, Assignment) else (parents[-1] if parents else "")
        symbolish_field = (
            field_name in NUMERIC_FIELDS
            or field_name in EXPRESSION_FIELDS
            or field_name.startswith("scripted_")
            or expression in names
        )
        if symbolish_field and (
            _IDENTIFIER.fullmatch(expression) or _EXPLICIT_REF.fullmatch(expression)
        ):
            return [(expression, expression, "quoted_symbol_observation", requested)]
        return result
    explicit = list(_EXPLICIT_REF.finditer(expression))
    if explicit:
        for match in explicit:
            prefix = match.group(0).split(":")[0]
            kind = "script_value" if "value" in prefix else prefix
            result.append((match.group(1), expression, "explicit_symbol_prefix", kind))
        return result
    if requested in {"scripted_value", "script_value", "scripted_trigger", "scripted_effect"}:
        result.append(
            (
                expression,
                expression,
                "explicit_reference_field",
                "script_value" if "value" in requested else requested,
            )
        )
        return result
    if _PARAMETER.search(expression):
        result.append((expression, expression, "parameterized_reference", requested))
        return result
    words = _IDENTIFIER.findall(expression)
    known = [word for word in words if word in names]
    for word in dict.fromkeys(known):
        syntax = (
            "quoted_symbol_observation"
            if (
                (isinstance(item, Scalar) and item.quoted)
                or (
                    isinstance(item, Assignment)
                    and isinstance(item.value, Scalar)
                    and item.value.quoted
                )
            )
            else "scalar_or_scope_chained_call"
        )
        result.append((word, expression, syntax, "script_value" if numeric else None))
    if (
        not known
        and numeric
        and re.fullmatch(r"[A-Za-z_][\w.:]*", expression)
        and expression not in {"yes", "no"}
    ):
        result.append(
            (
                expression,
                expression,
                "unresolved_numeric_identifier_or_engine_getter",
                "script_value",
            )
        )
    return result


def _cycles(
    definitions: list[dict[str, Any]], references: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Iterative SCC traversal avoids recursion limits on native call chains."""
    names = {row["symbol_id"]: row["name"] for row in definitions}
    graph: dict[str, set[str]] = {symbol: set() for symbol in names}
    reverse: dict[str, set[str]] = {symbol: set() for symbol in names}
    for reference in references:
        source = reference["caller_symbol_id"]
        if source not in graph or reference["status"] == "observational":
            continue
        for target in reference["resolved_to"]:
            graph[source].add(target)
            reverse[target].add(source)
    visited: set[str] = set()
    order: list[str] = []
    for origin in sorted(graph):
        if origin in visited:
            continue
        stack = [(origin, False)]
        while stack:
            node, leaving = stack.pop()
            if leaving:
                order.append(node)
            elif node not in visited:
                visited.add(node)
                stack.append((node, True))
                stack.extend(
                    (child, False)
                    for child in sorted(graph[node], reverse=True)
                    if child not in visited
                )
    visited.clear()
    result = []
    for origin in reversed(order):
        if origin in visited:
            continue
        members = []
        pending = [origin]
        while pending:
            node = pending.pop()
            if node in visited:
                continue
            visited.add(node)
            members.append(node)
            pending.extend(sorted(reverse[node] - visited))
        if len(members) > 1 or origin in graph[origin]:
            member_set = set(members)
            partial = any(
                reference["status"] == "partial_source"
                and reference["caller_symbol_id"] in member_set
                and any(target in member_set for target in reference["resolved_to"])
                for reference in references
            )
            result.append(
                {
                    "symbol_ids": sorted(members),
                    "symbols": sorted(names[node] for node in members),
                    "status": "cyclic_static_dependency_with_partial_source"
                    if partial
                    else "cyclic_static_dependency",
                    "evidence_completeness": "partial"
                    if partial
                    else "complete_within_declared_sources",
                }
            )
    return sorted(result, key=canonical_json)


def _dependencies(
    consumers: list[dict[str, Any]], references: list[dict[str, Any]], cycles: list[dict[str, Any]]
) -> None:
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_caller: dict[str, list[dict[str, Any]]] = defaultdict(list)
    cyclic = {symbol for cycle in cycles for symbol in cycle["symbol_ids"]}
    for reference in references:
        by_source[reference["source"]["path"]].append(reference)
        if reference["caller_symbol_id"]:
            by_caller[reference["caller_symbol_id"]].append(reference)
    for consumer in consumers:
        address = consumer["source"]["address"]
        direct = [
            ref
            for ref in by_source[consumer["source"]["path"]]
            if ref["source"]["address"][: len(address)] == address
        ]
        pending = list(direct)
        visited: set[str] = set()
        bad = False
        symbols: set[str] = set()
        while pending:
            reference = pending.pop()
            if reference["reference_id"] in visited:
                continue
            visited.add(reference["reference_id"])
            bad |= reference["status"] in {"unresolved", "ambiguous", "partial_source"}
            for symbol in reference["resolved_to"]:
                symbols.add(symbol)
                bad |= symbol in cyclic
                pending.extend(by_caller.get(symbol, []))
        consumer["dependencies"] = {
            "reference_ids": sorted(ref["reference_id"] for ref in direct),
            "transitive_reference_ids": sorted(visited),
            "symbol_ids": sorted(symbols),
            "status": "unresolved_or_cyclic" if bad else "statically_resolved_semantics_unknown",
        }


def build_native_catalog(installation: Path, inventory: dict[str, Any]) -> dict[str, Any]:
    """Read native inputs named by a sealed raw inventory; retain unknowns/failures."""
    installation = Path(installation)
    if installation.is_symlink() or installation.resolve() != installation.absolute():
        raise ValueError(f"linked installation root: {installation}")
    installation = installation.absolute()
    if not isinstance(inventory.get("expected_version"), str):
        raise ValueError("unsupported inventory version; missing exact identity")
    expected_version = active_version(inventory["expected_version"])
    if expected_version == "1.14.5":
        raise ValueError("unsupported inventory version; expected a reviewed 1.15 identity")
    version_identity = inventory.get("version_identity")
    if not isinstance(version_identity, dict) or version_identity.get("version_match") is not True:
        raise ValueError("version identity is not a verified expected-version match")
    claimed = inventory.get("inventory_sha256")
    actual = _hash({key: value for key, value in inventory.items() if key != "inventory_sha256"})
    if claimed != actual or inventory.get("schema") != "situated-ai.native-inventory/1":
        raise ValueError("raw inventory identity mismatch")
    records: dict[str, dict[str, Any]] = {}
    inputs: dict[str, bytes] = {}
    for record in inventory["files"]:
        path = record["path"]
        if path in records:
            raise ValueError(f"duplicate inventory path: {path}")
        native = _checked_path(installation, path)
        try:
            raw = native.read_bytes()
        except OSError as error:
            raise ValueError(f"native content drift: {path}: {type(error).__name__}") from error
        if hashlib.sha256(raw).hexdigest() != record["sha256"] or len(raw) != record["bytes"]:
            raise ValueError(f"native content drift: {path}")
        records[path] = record
        # Keep only scripts and documentation after checking all raw bytes.
        if record["parse_status"] in {"parsed", "partial"} or path.endswith(".md"):
            inputs[path] = raw
    listed_content = {path for path in records if path.split("/", 1)[0] in CONTENT_ROOTS}
    current_content = _current_content_paths(installation)
    added = sorted(current_content - listed_content)
    if added:
        raise ValueError(f"unlisted native content: {added[0]}")
    docs = _documents(records, inputs)
    definitions = []
    symbol_lookup: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path, raw in sorted(inputs.items()):
        category = _category(path)
        if category not in SYMBOL_CATEGORIES or not path.endswith(".txt"):
            continue
        for index, item in enumerate(parse_bytes(raw, path=path).root.items):
            if not isinstance(item, Assignment) or item.is_variable:
                continue
            symbol = {
                "symbol_id": _hash([path, [index]]),
                "name": item.key,
                "kind": SYMBOL_CATEGORIES[category],
                "source": _source(path, records[path]["sha256"], item, (index,)),
                "source_validity": records[path]["parse_status"],
                "definition_status": "observed_native_definition_semantics_unknown",
                "native_disposition": "native_retained",
            }
            definitions.append(symbol)
            symbol_lookup[item.key].append(symbol)
    names = set(symbol_lookup)
    symbol_source = {
        (row["source"]["path"], row["source"]["address"][0]): row["symbol_id"]
        for row in definitions
    }
    heuristics: dict[str, dict[tuple[int, ...], dict[str, Any]]] = defaultdict(dict)
    for candidate in inventory.get("consumer_candidates", []):
        heuristics[candidate["path"]][tuple(candidate["address"])] = candidate
    consumers = []
    references: list[dict[str, Any]] = []
    failures = list(inventory.get("failures", []))
    for path, raw in sorted(inputs.items()):
        record = records[path]
        if record["parse_status"] not in {"parsed", "partial"}:
            continue
        parsed = parse_bytes(raw, path=path)
        consumers.extend(
            _discover_consumers(
                path,
                record,
                parsed.root,
                raw.decode("utf-8-sig").splitlines(),
                docs,
                heuristics.get(path, {}),
            )
        )
        if parsed.errors and record["parse_status"] != "partial":
            failures.append({"kind": "catalog_parse_failure", "path": path, "scope": "whole_file"})
        for item, address, parents in _walk(parsed.root):
            for occurrence, (name, expression, syntax, kind) in enumerate(
                _symbol_references(item, names, parents)
            ):
                targets = [
                    symbol
                    for symbol in symbol_lookup.get(name, [])
                    if kind is None or symbol["kind"] == kind
                ]
                status = (
                    "resolved" if len(targets) == 1 else "ambiguous" if targets else "unresolved"
                )
                if syntax == "quoted_symbol_observation":
                    status = "observational"
                elif record["parse_status"] == "partial" or any(
                    symbol["source_validity"] == "partial" for symbol in targets
                ):
                    status = "partial_source"
                references.append(
                    {
                        "reference_id": _hash([path, list(address), syntax, name, occurrence]),
                        "source": _source(path, record["sha256"], item, address),
                        "definition": parents[0]
                        if parents
                        else (item.key if isinstance(item, Assignment) else "unknown"),
                        "field": ".".join((*parents[1:], item.key))
                        if isinstance(item, Assignment)
                        else ".".join(parents[1:]),
                        "symbol": name,
                        "expression": expression,
                        "syntax": syntax,
                        "requested_kind": kind or "unknown",
                        "status": status,
                        "resolved_to": sorted(symbol["symbol_id"] for symbol in targets),
                        "caller_symbol_id": symbol_source.get((path, address[0])),
                        "scope_permission": "unknown",
                        "native_disposition": "native_retained",
                    }
                )
    cycles = _cycles(definitions, references)
    _dependencies(consumers, references, cycles)
    consumers.sort(key=lambda row: (row["source"]["path"], row["source"]["address"]))
    references.sort(
        key=lambda row: (row["source"]["path"], row["source"]["address"], row["reference_id"])
    )
    definitions.sort(key=lambda row: (row["source"]["path"], row["source"]["address"]))
    failure_scopes = [
        {
            "path": path,
            "scope": "whole_file",
            "parse_status": record["parse_status"],
            "consumer_completeness": "unknown",
            "dependency_completeness": "unknown",
        }
        for path, record in sorted(records.items())
        if record["parse_status"] in {"partial", "failed"}
    ]
    by_category: dict[str, Counter[str]] = defaultdict(Counter)
    for row in consumers:
        by_category[row["category"]][row["classification"]] += 1
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "evidence_kind": "static_check",
        "inventory_sha256": claimed,
        "expected_version": inventory["expected_version"],
        "status": "incomplete"
        if failures
        else "static_candidate_index_complete_within_declared_rules_semantics_unknown",
        "scanner": {
            "module": "pdx.situated.native_catalog",
            "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
        "scope": {
            "input": "all_hashed_native_files_from_raw_inventory",
            "mod_inputs": [],
            "strategy_fields": "all_non_variable_definition_fields_except_icon_and_type",
            "map_fields": sorted(MAP_FIELDS),
            "explicit_ai_field_categories": sorted(AI_FIELD_CATEGORIES),
            "other_fields": "documented_scored_candidates_and_unresolved_raw_heuristics",
            "reference_scan": "all_inventory_parsed_native_ASTs_with_symbol_names_explicit_prefixes_and_numeric_unknowns",
            "limitations": [
                "Static symbol resolution does not establish engine invocation or scope legality.",
                "Unrecognized engine getters and numeric identifiers remain unresolved.",
                "String mentions are observational; dynamic names and parameters remain unresolved.",
                "DLC activation, load precedence, overrides and runtime actors are unknown.",
                "Unclassified fields and failed file scopes prevent a proven engine consumer denominator.",
            ],
        },
        "denominator": {
            "implementation_independent": True,
            "index_kind": "implementation-independent static candidate index",
            "legal_consumers": "unknown",
            "basis": "static candidate occurrences from declared native rules; unresolved, unclassified, and failed scopes prevent a complete engine field denominator",
            "direct_candidate_occurrences": sum(
                row["classification"] == "direct_candidate" for row in consumers
            ),
            "unresolved_occurrences": sum(
                row["classification"] == "unresolved" for row in consumers
            ),
            "engine_completeness": "incomplete_unresolved_unclassified_or_failed_scopes",
        },
        "consumers": consumers,
        "symbol_definitions": definitions,
        "references": references,
        "dependency_cycles": cycles,
        "parse_failure_scopes": failure_scopes,
        "failures": sorted(failures, key=canonical_json),
        "summary": {
            "checked_input_files": len(records),
            "consumers": len(consumers),
            "classifications": dict(
                sorted(Counter(row["classification"] for row in consumers).items())
            ),
            "categories": {
                key: dict(sorted(value.items())) for key, value in sorted(by_category.items())
            },
            "symbol_definitions": len(definitions),
            "references": len(references),
            "reference_statuses": dict(
                sorted(Counter(row["status"] for row in references).items())
            ),
            "dependency_cycles": len(cycles),
            "failures": len(failures),
        },
    }
    result["catalog_sha256"] = _hash(result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installation", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    result = build_native_catalog(
        args.installation, json.loads(args.inventory.read_text(encoding="utf-8"))
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(canonical_json(result), encoding="utf-8", newline="\n")
    print(canonical_json(result["summary"]), end="")
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
