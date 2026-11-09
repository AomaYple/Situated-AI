"""Reproduce A0 migration, per-country observation and offline cost evidence.

This inventory reads the frozen old compiler without promoting any old contract
to 1.15. It never generates Mod files, changes the generation lock, or runs the
game. Native field discovery and runtime legality remain separate evidence.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import tomllib
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

import psutil

from pdx.model import Block, Scalar
from pdx.parser import parse_bytes

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = "docs/design/exec/1.15-A0-纵切合同.md"
SLICES: tuple[dict[str, Any], ...] = (
    {
        "id": "A0-ECON-ROAD",
        "objective_id": "A0-OBJ-LOCAL-INFRASTRUCTURE",
        "source": "game/common/decrees/00_decree.txt",
        "field": ["decree_road_maintenance", "ai_weight"],
        "actor": "scope:country; native same-consumer explicit country journal and variable reads",
        "target": "root state; native same-consumer is_capital and country home-state comparison",
        "facts": ["A0-FACT-RELATIVE-INFRASTRUCTURE", "A0-FACT-ROAD-DECREE-PRESENT"],
        "interest_source": "actual local infrastructure shortfall; native country journal and state interests",
    },
    {
        "id": "A0-POL-SCHOOLS",
        "objective_id": "A0-OBJ-EDUCATION-CAPACITY",
        "source": "game/common/ai_strategies/00_default_strategy.txt",
        "field": ["ai_strategy_default", "institution_scores", "institution_schools"],
        "actor": "country root; native same-school-score country journal read",
        "target": "institution_schools type of same actor",
        "facts": [
            "A0-FACT-SCHOOL-AGENDA",
            "A0-FACT-LITERACY",
            "A0-FACT-SCHOOL-LEVEL",
            "A0-FACT-FISCAL-PRESSURE",
            "A0-FACT-BUREAUCRACY",
        ],
        "interest_source": "actor literacy and institutional capacity; native active political agendas",
    },
    {
        "id": "A0-DIP-RELATIONS",
        "objective_id": "A0-OBJ-BILATERAL-SPACE",
        "source": "game/common/diplomatic_actions/00_relations_actions.txt",
        "field": ["increase_relations", "ai", "propose_score"],
        "actor": "root AI country",
        "target": "exact scope:target_country; explicit native same-consumer usage; docs call it scope:target",
        "facts": [
            "A0-FACT-DIPLOMATIC-ATTITUDE",
            "A0-FACT-BILATERAL-RELATIONS",
            "A0-FACT-FISCAL-PRESSURE",
        ],
        "interest_source": "native bilateral relations, attitude and regional objectives; actor costs",
    },
)
FACTS = (
    (
        "A0-FACT-SCHOOL-AGENDA",
        "school_agenda",
        "has_journal_entry",
        "root country",
        "game/common/ai_strategies/03_political_strategies.txt",
        "same institution_schools score reads country journal; static country scope usage, not engine runtime proof",
    ),
    (
        "A0-FACT-DIPLOMATIC-ATTITUDE",
        "diplomatic_attitude",
        "has_attitude",
        "root country; who=scope:target_country",
        "game/common/diplomatic_actions/00_relations_actions.txt",
        "same propose_score reads exact bilateral country attitude; static usage, not engine runtime proof",
    ),
    (
        "A0-FACT-RELATIVE-INFRASTRUCTURE",
        "relative_infrastructure",
        "relative_infrastructure",
        "root state",
        "game/common/decrees/00_decree.txt",
        "native same-consumer state read; runtime refresh and numeric semantics unknown",
    ),
    (
        "A0-FACT-ROAD-DECREE-PRESENT",
        "road_decree_present",
        "has_decree",
        "root state; decree_road_maintenance parameter",
        "game/common/decrees/00_decree.txt",
        "native same-consumer state read; no inference about actor authority balance",
    ),
    (
        "A0-FACT-LITERACY",
        "literacy",
        "literacy_rate",
        "root country",
        "game/common/ai_strategies/01_admin_strategies.txt",
        "strategy use, not institution consumer legality proof",
    ),
    (
        "A0-FACT-SCHOOL-LEVEL",
        "schools_investment",
        "institution_investment_level",
        "root country; institution_schools parameter pending_reproof",
        "game/common/scripted_triggers/00_strike_triggers.txt",
        "native workplace/social security examples; schools parameter unproven here",
    ),
    (
        "A0-FACT-FISCAL-PRESSURE",
        "default",
        "in_default",
        "root country",
        "game/common/alert_types/00_alert_types.txt",
        "default is observed pressure; no implied reservation or spending capability",
    ),
    (
        "A0-FACT-BUREAUCRACY",
        "bureaucracy",
        "bureaucracy",
        "root country",
        "game/common/scripted_triggers/05_tsarpoints_scripted_triggers.txt",
        "independent administrative pressure, not common development gate",
    ),
    (
        "A0-FACT-BILATERAL-RELATIONS",
        "target_relations",
        "scope:target_country.relations:root",
        "exact actor-target pair",
        "game/common/diplomatic_actions/00_relations_actions.txt",
        "native pact requirement; propose_score legality still pending_reproof",
    ),
)
DECLARATION_KINDS = {
    "readers": "declared_reader",
    "actions": "declared_action",
    "relations": "declared_relation",
    "rules": "declared_rule",
    "strategies": "declared_strategy",
    "intents": "declared_intent",
    "initial_values": "declared_initial_writer",
    "scalar_values": "declared_scalar_writer",
    "bindings": "declared_binding",
    "consumers": "declared_consumer",
}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def read_inventory(raw: bytes) -> dict[str, Any]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    result = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    if not isinstance(result, dict):
        raise ValueError("inventory must be an object")
    return result


def validate_output(game: Path, output: Path) -> None:
    if output.resolve().is_relative_to(game.resolve()):
        raise ValueError("output must not be inside the game installation")
    for folder in ("mod", "src", "docs", "tests", "research"):
        if output.resolve().is_relative_to((ROOT / folder).resolve()):
            raise ValueError(f"output must not be inside controlled sources: {folder}")


def validate_inventory(data: dict, game: Path) -> None:
    """Bind scan content, version and all consumed native files to current bytes."""
    content = {key: value for key, value in data.items() if key != "inventory_sha256"}
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if digest(canonical.encode("utf-8")) != data.get("inventory_sha256"):
        raise ValueError("inventory content fingerprint mismatch")
    if (
        data.get("schema") != "situated-ai.native-inventory/1"
        or data.get("expected_version") != "1.15.0"
    ):
        raise ValueError("inventory schema/version must identify 1.15.0")
    identity = data.get("version_identity", {})
    if identity.get("version_match") is not True:
        raise ValueError("inventory version identity mismatch")
    for item in data.get("roots", []):
        if item.get("present") is not True or not (game / item["path"]).is_dir():
            raise ValueError(f"inventory root missing: {item.get('path')}")
    scanner = data.get("scanner", {})
    if scanner.get("module") != "pdx.situated.version_inventory" or not scanner.get("sources"):
        raise ValueError("inventory scanner source identity missing")
    for item in scanner["sources"]:
        source_path = (ROOT / item["path"]).resolve()
        if (
            not source_path.is_relative_to((ROOT / "src/pdx").resolve())
            or not source_path.is_file()
            or digest(source_path.read_bytes()) != item["sha256"]
        ):
            raise ValueError(f"scanner source drift: {item['path']}")
    universe = data["actor_universe"]
    actors = universe["actors"]
    defined_actors = [item["actor"] for item in universe["definitions"]]
    if len(actors) != len(set(actors)) or set(actors) != set(defined_actors):
        raise ValueError("actor universe inconsistent with source definitions")
    files = {}
    for item in data["files"]:
        path = item["path"]
        if path in files:
            raise ValueError(f"duplicate inventory file: {path}")
        files[path] = item
    required = {spec["source"] for spec in SLICES}
    required.update(item[4] for item in FACTS)
    required.update(item["source"]["path"] for item in data["actor_universe"]["definitions"])
    identities = [*identity["files"], identity["launcher"]]
    required.update(item["path"] for item in identities)
    failed = {item.get("path") for item in data.get("failures", [])}
    for relative in sorted(required):
        path = (game / relative).resolve()
        if not path.is_relative_to(game.resolve()):
            raise ValueError(f"native source outside installation: {relative}")
        entry = files.get(relative)
        if entry is None or relative in failed or entry.get("parse_status") == "partial":
            raise ValueError(f"missing/incomplete consumed native source: {relative}")
        if not path.is_file() or digest(path.read_bytes()) != entry["sha256"]:
            raise ValueError(f"native source drift: {relative}")
    for item in identities:
        if files[item["path"]]["sha256"] != item["sha256"]:
            raise ValueError(f"version identity hash mismatch: {item['path']}")


def pending(kind: str, identity: str, source: str, pointer: str, **extra: Any) -> dict[str, Any]:
    return {
        "kind": kind,
        "id": identity,
        "original_source": source,
        "original_pointer": pointer,
        "disposition": "pending_reproof",
        "automatic_inheritance": False,
        **extra,
    }


def declaration_rows(data: dict, source: str) -> list[dict[str, Any]]:
    """Retain table namespaces and array positions, including repeated IDs."""
    rows: list[dict[str, Any]] = []
    for table, kind in DECLARATION_KINDS.items():
        values = data.get(table, {})
        entries = values.items() if isinstance(values, dict) else enumerate(values)
        for key, item in entries:
            if not isinstance(item, dict):
                continue
            identity = str(item.get("id", item.get("binding_id", key)))
            if table == "relations":
                identity = str(
                    item.get(
                        "id", f"{item.get('source')}:{item.get('kind')}:{item.get('target')}:{key}"
                    )
                )
            rows.append(pending(kind, identity, source, f"{table}/{key}", original=item))
    return rows


def migration_inventory(root: Path = ROOT) -> dict[str, Any]:
    """Include raw declarations and actual expanded frozen compiler identities."""
    from pdx.situated.compiler import load_model  # noqa: PLC0415

    rows: list[dict[str, Any]] = []
    sources = []
    for path in sorted((root / "mod/decisions").glob("*.toml")):
        raw = path.read_bytes()
        relative = path.relative_to(root).as_posix()
        sources.append({"path": relative, "sha256": digest(raw), "bytes": len(raw)})
        rows.extend(declaration_rows(tomllib.loads(raw.decode("utf-8")), relative))
    model = load_model()
    for index, (source, reader_id, signature) in enumerate(model.observation_contracts):
        rows.append(
            pending(
                "compiled_reader_binding",
                reader_id,
                source,
                f"observation_contracts/{index}",
                frozen_signature=signature,
                declaration_sources="mod/decisions/*.toml; hashes above",
            )
        )
    rows.extend(
        pending(
            "compiled_action",
            item.action_id,
            item.source,
            item.rule_id,
            consumer_field=item.consumer_field,
            actor=item.actor_scope,
            target=item.target_scope,
            old_kind=item.kind,
            condition_facts=item.condition_facts,
        )
        for item in model.action_instances
    )
    if model.consumer_ir is None:
        raise ValueError("frozen compiler returned no consumer IR")
    rows.extend(
        pending(
            "compiled_writer",
            item.writer_id,
            item.source,
            item.definition,
            consumer_field=item.field,
            actor=item.actor,
            target=item.target,
            old_kind=item.kind,
            operation=item.operation,
            old_vanilla_tail=item.vanilla_tail,
        )
        for item in model.consumer_ir.writers
    )
    for index, item in enumerate(model.production_consumers):
        rows.append(
            pending(
                "physical_consumer",
                str(index),
                item.source,
                ".".join(item.field),
                original=asdict(item),
            )
        )
    for index, relation in enumerate(model.relations):
        rows.append(
            pending(
                "compiled_relation",
                f"{relation.source}:{relation.kind}:{relation.target}",
                "mod/decisions/relations.toml",
                f"relations/{index}",
                original=asdict(relation),
            )
        )
    # Preserve native strategy IDs in the frozen production output separately
    # from symbolic strategy layers/intents; they are different namespaces.
    for path in sorted((root / "mod/common/ai_strategies").glob("*.txt")):
        raw = path.read_bytes()
        parsed = parse_bytes(raw, path.as_posix())
        if parsed.errors:
            raise ValueError(f"frozen strategy parse failure: {path}: {parsed.errors}")
        for index, strategy_assignment in enumerate(parsed.root.assignments()):
            if isinstance(strategy_assignment.value, Block) and not strategy_assignment.is_variable:
                rows.append(
                    pending(
                        "frozen_native_strategy",
                        strategy_assignment.key,
                        path.relative_to(root).as_posix(),
                        f"root/{index}",
                        line=strategy_assignment.line,
                        source_sha256=digest(raw),
                    )
                )
    rows.sort(
        key=lambda item: (
            item["kind"],
            item["original_source"],
            item["original_pointer"],
            item["id"],
        )
    )
    generator_sources = [
        {"path": path.relative_to(root).as_posix(), "sha256": digest(path.read_bytes())}
        for path in sorted((root / "src/pdx").rglob("*.py"))
    ]
    return {
        "schema": "situated-ai.a0-migration/1",
        "evidence_kind": "static_check",
        "baseline": "frozen 1.14.5 production declarations and offline compiler; not local 1.15 proof",
        "contract": CONTRACT,
        "sources": sources,
        "generator_sources": generator_sources,
        "counts": dict(sorted(Counter(item["kind"] for item in rows).items())),
        "dispositions": {"pending_reproof": len(rows)},
        "rows": rows,
    }


def select_block(root: Block, field: list[str]) -> Block:
    """Require a unique exact path; never silently choose among duplicate fields."""
    current = root
    for key in field:
        matches = current.all(key)
        if len(matches) != 1 or not isinstance(matches[0].value, Block):
            raise ValueError(f"expected one block at {'.'.join(field)}; {key}: {len(matches)}")
        current = matches[0].value
    return current


def block_metrics(root: Block) -> dict[str, Any]:
    assignments = 0
    max_depth = 0
    max_siblings = 0
    query_forms: Counter[str] = Counter()
    duplicates: Counter[str] = Counter()
    stack = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        max_depth = max(max_depth, depth)
        nodes = list(current.assignments())
        max_siblings = max(max_siblings, len(nodes))
        duplicates.update(
            {key: count - 1 for key, count in Counter(a.key for a in nodes).items() if count > 1}
        )
        for item in nodes:
            assignments += 1
            if item.key.startswith(("any_", "every_", "random_", "ordered_")):
                query_forms[item.key] += 1
            if isinstance(item.value, Block):
                stack.append((item.value, depth + 1))
        stack.extend((item, depth + 1) for item in current.items if isinstance(item, Block))
    return {
        "assignments": assignments,
        "block_depth": max_depth,
        "max_assignments_in_block": max_siblings,
        "query_forms": dict(sorted(query_forms.items())),
        "duplicate_assignments": dict(sorted(duplicates.items())),
    }


def static_samples(game: Path, root: Path = ROOT) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for spec in SLICES:
        for baseline in ("native_1.15", "frozen_mod_1.14.5"):
            relative = (
                spec["source"]
                if baseline == "native_1.15"
                else spec["source"].replace("game/", "mod/", 1)
            )
            path = game / relative if baseline == "native_1.15" else root / relative
            row: dict[str, Any] = {"slice_id": spec["id"], "baseline": baseline, "path": relative}
            if not path.exists():
                row["status"] = "absent_no_old_writer; not_a_zero_cost_sample"
            else:
                raw = path.read_bytes()
                raw.decode("utf-8-sig")  # A measured sample cannot silently replace invalid bytes.
                parsed = parse_bytes(raw, relative)
                if parsed.errors:
                    raise ValueError(
                        f"selected consumer parse failure: {relative}: {parsed.errors}"
                    )
                block = select_block(parsed.root, spec["field"])
                row.update(
                    status="parsed",
                    sha256=digest(raw),
                    bytes=len(raw),
                    file_metrics=block_metrics(parsed.root),
                    consumer_metrics=block_metrics(block),
                )
            rows.append(row)
    maxima = [row["consumer_metrics"] for row in rows if row.get("status") == "parsed"]
    return {
        "schema": "situated-ai.a0-static-baseline/1",
        "evidence_kind": "static_check",
        "samples": rows,
        "query_budget": {
            "id": "A0-BUDGET-LOCAL-ONLY",
            "contract": CONTRACT,
            "additional_global_scans": 0,
            "additional_candidate_expansion_per_evaluation": 0,
            "selected_candidates_per_evaluation": 1,
            "cross_candidate_cartesian_products": 0,
            "additional_scope_path_hops": 1,
            "additional_iterator_nesting": 0,
            "additional_block_depth": 3,
            "justification": "one local AI guard, one fact condition, one bounded term; explicit native scope:country; no iterator introduced",
            "observed_max_consumer_block_depth": max(item["block_depth"] for item in maxima),
            "observed_max_consumer_assignments": max(item["assignments"] for item in maxima),
            "observed_size_is_engine_limit": False,
            "runtime_cost": "unknown; static shape budget is not an engine benchmark",
        },
    }


def source_occurrences(raw: bytes, source: str, key: str) -> list[dict[str, Any]]:
    """Find exact parsed assignment keys, never comments or scalar substrings."""
    raw.decode("utf-8-sig")
    parsed = parse_bytes(raw, source)
    if parsed.errors:
        raise ValueError(f"fact source parse failure: {source}: {parsed.errors}")
    rows = []
    stack: list[tuple[Block, list[str], list[int]]] = [(parsed.root, [], [])]
    while stack:
        block, parents, address = stack.pop()
        for index, item in enumerate(block.assignments()):
            position = [*address, index]
            if item.key == key:
                rows.append(
                    {
                        "path": source,
                        "parents": parents,
                        "address": position,
                        "key": item.key,
                        "operator": item.op,
                        "line": item.line,
                        "value": item.value.text if isinstance(item.value, Scalar) else None,
                    }
                )
            if isinstance(item.value, Block):
                stack.append((item.value, [*parents, item.key], position))
    return sorted(rows, key=lambda row: row["line"])


def fact_sources(game: Path) -> list[dict[str, Any]]:
    old = {}
    for name in ("adapters", "information", "country_state"):
        path = ROOT / f"mod/decisions/{name}.toml"
        old[name] = tomllib.loads(path.read_text(encoding="utf-8")).get("readers", {})
    result = []
    for identity, old_key, engine, scope, relative, limitation in FACTS:
        raw = (game / relative).read_bytes()
        occurrences = source_occurrences(raw, relative, engine)
        result.append(
            {
                "id": identity,
                "old_reader_id": old_key,
                "engine": engine,
                "scope": scope,
                "unit": {
                    "A0-FACT-ROAD-DECREE-PRESENT": "boolean",
                    "A0-FACT-SCHOOL-AGENDA": "boolean",
                    "A0-FACT-DIPLOMATIC-ATTITUDE": "boolean",
                    "A0-FACT-FISCAL-PRESSURE": "boolean",
                    "A0-FACT-RELATIVE-INFRASTRUCTURE": "unknown; native relative ratio shape, numeric definition not documented",
                    "A0-FACT-LITERACY": "ratio; old reader contract pending current semantic reproof",
                    "A0-FACT-SCHOOL-LEVEL": "institution_level; old reader contract pending current semantic reproof",
                    "A0-FACT-BUREAUCRACY": "bureaucracy_points; old reader contract pending current semantic reproof",
                    "A0-FACT-BILATERAL-RELATIONS": "relations_points; old [-100,100] range pending current semantic reproof",
                }[identity],
                "native_source": {
                    "path": relative,
                    "sha256": digest(raw),
                    "assignments": occurrences,
                },
                "native_discovery": "static_assignment"
                if occurrences
                else "not_found_in_selected_source",
                "limitation": limitation,
                "old_sources": [
                    {
                        "path": f"mod/decisions/{name}.toml",
                        "pointer": f"readers/{old_key}",
                        "shape": readers[old_key],
                    }
                    for name, readers in old.items()
                    if old_key in readers
                ],
                "contextual_legal_read": (
                    "native_same_consumer_static_usage"
                    if identity
                    in {
                        "A0-FACT-RELATIVE-INFRASTRUCTURE",
                        "A0-FACT-ROAD-DECREE-PRESENT",
                        "A0-FACT-SCHOOL-AGENDA",
                        "A0-FACT-DIPLOMATIC-ATTITUDE",
                    }
                    else "pending_reproof"
                ),
                "runtime_value": "unknown",
                "ttl": "this_consumer_evaluation",
                "refresh": "runtime-unknown",
                "unknown_policy": "withdraw_only_dependent_new_term; preserve_native",
            }
        )
    return result


def classify_failures(inventory: dict) -> list[dict[str, Any]]:
    selected = {spec["source"] for spec in SLICES}
    result = []
    for failure in inventory.get("failures", []):
        path = failure.get("path", "")
        if path in selected:
            impact = "blocks_selected_consumer_contract"
        elif "/dna_data/" in path:
            impact = "limits_character_DNA_coverage; selected_consumer_sources_unaffected"
        elif "/portraits/" in path:
            impact = "limits_portrait_asset_coverage; selected_consumer_sources_unaffected"
        elif "/licenses/" in path:
            impact = "limits_license_text_decoding; selected_consumer_sources_unaffected"
        elif path.endswith("localization/languages.yml"):
            impact = "language_registry_format; localization_activation_remains_unknown"
        else:
            impact = "unclassified_requires_review"
        result.append(
            {
                "failure": failure,
                "impact": impact,
                "disposition": "retained_known_limitation; not_suppressed",
            }
        )
    return result


def observation_inventory(inventory: dict, game: Path) -> dict[str, Any]:
    universe = inventory["actor_universe"]
    actors = universe["actors"]
    if len(actors) != len(set(actors)):
        raise ValueError("duplicate actor IDs in static universe")
    definitions: dict[str, list] = {}
    for item in universe["definitions"]:
        definitions.setdefault(item["actor"], []).append(item["source"])
    rows: list[dict[str, Any]] = []
    for actor in [*sorted(actors), "*DYNAMIC_COUNTRY*"]:
        rows.extend(
            {
                "actor": actor,
                "actor_source": definitions.get(actor, []),
                "actor_kind": "dynamic_wildcard" if actor == "*DYNAMIC_COUNTRY*" else "static_tag",
                "slice_id": spec["id"],
                "contract": f"{CONTRACT}#{spec['id'].lower()}",
                "objective_id": spec["objective_id"],
                "consumer_source": spec["source"],
                "consumer_field": spec["field"],
                "fact_source_ids": spec["facts"],
                "actor_scope": spec["actor"],
                "target_scope": spec["target"],
                "observation_model": "consumer_immediate_read; proposed_not_connected",
                "ttl": "this_consumer_evaluation",
                "refresh": "runtime-unknown",
                "budget_id": "A0-BUDGET-LOCAL-ONLY",
                "runtime_observation": "unknown",
                "native_eligibility": "unknown_per_actor_and_candidate",
                "disposition": "native_preserved_pending_integration",
                "interest_source": spec["interest_source"],
                "consumer_wiring": "not_connected_1.15",
                "objective_wiring": "not_connected_1.15",
            }
            for spec in SLICES
        )
    return {
        "schema": "situated-ai.a0-observation-coverage/1",
        "evidence_kind": "static_check",
        "native_inventory_identity": inventory["inventory_sha256"],
        "actor_count": len(actors),
        "static_rows": len(actors) * len(SLICES),
        "dynamic_rows": len(SLICES),
        "excluded_actors": [],
        "runtime_actor_set": universe["runtime_actor_set"],
        "fact_sources": fact_sources(game),
        "rows": rows,
        "scan_limitations": classify_failures(inventory),
        "coverage_meaning": "enumeration_only; no runtime coverage or completed integration claim",
    }


def objectives(observation: dict) -> dict[str, Any]:
    return {
        "schema": "situated-ai.a0-actor-objectives/1",
        "evidence_kind": "static_check",
        "contract": CONTRACT,
        "objectives": [
            {
                "id": spec["objective_id"],
                "slice_id": spec["id"],
                "source": spec["interest_source"],
                "fact_source_ids": spec["facts"],
                "wiring": "not_connected_1.15",
                "actor_value": "unknown",
            }
            for spec in SLICES
        ],
        "actors": [
            {
                "actor": row["actor"],
                "objective_id": row["objective_id"],
                "slice_id": row["slice_id"],
                "status": "static_template_runtime_unknown",
            }
            for row in observation["rows"]
        ],
    }


def configuration_inventory(native_inventory: dict) -> dict[str, Any]:
    sources = []
    for relative in (
        "mod/decisions/fiscal.toml",
        "mod/decisions/extensions.toml",
        "mod/decisions/information.toml",
        "mod/decisions/adapters.toml",
        "mod/decisions/country_state.toml",
        "src/pdx/decisions.py",
        "src/pdx/cli.py",
        "src/pdx/localization_languages.py",
    ):
        raw = (ROOT / relative).read_bytes()
        sources.append({"path": relative, "sha256": digest(raw)})
    localization = native_inventory["localization"]
    return {
        "schema": "situated-ai.a0-configuration/1",
        "evidence_kind": "static_check",
        "sources": sources,
        "entry": "build_time_TOML_configuration_then_Python_generation",
        "native_UI_entry": "not_claimed_or_required_for_build_time_route",
        "old_contract": {
            "version": "1.14.5",
            "loaders": ["pdx.decisions.load", "pdx.decisions.load_extensions"],
            "release_profile": "extensions.toml/profiles/release overrides development enabled flags",
            "type_validation": "existing loaders reject unknown fields/types; not inherited as 1.15 contract",
            "generation": "pdx.cli modgen --check; current local 1.15 rejects old generation lock",
        },
        "new_1_15_configuration": "not_implemented; A1 must define typed core/module switches and legal combinations",
        "localization": {
            "languages": localization["languages"],
            "header_sources": localization["header_sources"],
            "registry_sources": localization.get("registry_sources", []),
            "configuration_entry_status": localization["configuration_entry_status"],
            "coverage": "installed language directories and headers only; own 1.15 keys not generated",
            "old_defaults": "pdx.localization_languages.DEFAULT_LANGUAGES is frozen 1.14.5; never used as new denominator",
        },
    }


def measure(command: list[str], *, cwd: Path = ROOT, game: Path | None = None) -> dict[str, Any]:
    """Serial sampled RSS of the command's process tree; do not include observer."""
    with tempfile.TemporaryFile() as output:
        started = time.perf_counter()
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        if game is not None:
            env["V3_ROOT"] = str(game.resolve())
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=output,
            stderr=subprocess.STDOUT,
            env=env,
        )
        peak = 0
        samples = 0
        while True:
            try:
                parent = psutil.Process(process.pid)
                processes = [parent, *parent.children(recursive=True)]
            except psutil.NoSuchProcess:
                processes = []
            total = 0
            for member in processes:
                with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                    total += member.memory_info().rss
            peak = max(peak, total)
            samples += 1
            if process.poll() is not None:
                break
            time.sleep(0.01)
        wall = time.perf_counter() - started
        output.seek(0)
        raw = output.read()
    return {
        "command": command,
        "V3_ROOT": env.get("V3_ROOT"),
        "cwd": str(cwd),
        "exit_code": process.returncode,
        "wall_seconds": wall,
        "sampled_peak_tree_rss_bytes": peak,
        "sample_interval_seconds": 0.01,
        "samples": samples,
        "rss_measurement": "sampled_lower_bound; observer_excluded",
        "output_sha256": digest(raw),
        "output": raw.decode("utf-8", errors="replace"),
    }


def worker(kind: str, game: Path) -> None:
    if kind == "parse_samples":
        print(json.dumps(static_samples(game), ensure_ascii=False, sort_keys=True))
    elif kind == "offline_model":
        from pdx.situated.compiler import load_model  # noqa: PLC0415

        model = load_model()
        print(
            json.dumps(
                {
                    "action_instances": len(model.action_instances),
                    "writers": len(model.consumer_ir.writers) if model.consumer_ir else None,
                    "meaning": "old offline IR construction; not native regeneration",
                }
            )
        )
    else:
        raise ValueError(f"unknown worker: {kind}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inventory", type=Path, default=ROOT / "tools/out/version-1150/inventory.json"
    )
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "tools/out/version-1150")
    parser.add_argument("--measure", action="store_true")
    parser.add_argument("--worker", choices=("parse_samples", "offline_model"))
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, args.game_root)
        return 0
    validate_output(args.game_root, args.output)
    if args.inventory.resolve().is_relative_to(args.output.resolve()) and args.inventory.name in {
        "migration.json",
        "observation.json",
        "actor-objectives.json",
        "static-baseline.json",
        "cost-baseline.json",
    }:
        raise ValueError("output would overwrite input inventory")
    inventory_raw = args.inventory.read_bytes()
    inventory = read_inventory(inventory_raw)
    validate_inventory(inventory, args.game_root)
    migration = migration_inventory()
    observation = observation_inventory(inventory, args.game_root)
    static = static_samples(args.game_root)
    validate_inventory(inventory, args.game_root)
    for name, data in (
        ("migration", migration),
        ("observation", observation),
        ("actor-objectives", objectives(observation)),
        ("static-baseline", static),
        ("configuration-baseline", configuration_inventory(inventory)),
    ):
        data["producer_sha256"] = digest(Path(__file__).read_bytes())
        data["input_inventory_sha256"] = digest(inventory_raw)
        write_json(args.output / f"{name}.json", data)
    if args.measure:
        prefix = [sys.executable, "-B", "-X", "utf8"]
        base = [str(Path(__file__).resolve()), "--game-root", str(args.game_root)]
        commands = [
            ("native_and_frozen_parse", [*prefix, *base, "--worker", "parse_samples"]),
            ("frozen_offline_model_build", [*prefix, *base, "--worker", "offline_model"]),
            ("old_generator_on_local_1.15", [*prefix, "-m", "pdx.cli", "modgen", "--check"]),
        ]
        measurements = []
        for identity, command in commands:
            result = measure(command, game=args.game_root)
            result["id"] = identity
            log = args.output.resolve() / f"cost-{identity}.log"
            log.write_text(result.pop("output"), encoding="utf-8", newline="\n")
            result["log"] = log.relative_to(ROOT).as_posix()
            measurements.append(result)
        write_json(
            args.output / "cost-baseline.json",
            {
                "schema": "situated-ai.a0-offline-cost/1",
                "evidence_kind": "measured_offline",
                "producer_sha256": digest(Path(__file__).read_bytes()),
                "python": sys.version,
                "platform": platform.platform(),
                "parallelism": 1,
                "sample_identities": static["samples"],
                "measurements": measurements,
                "interpretation": "different workloads; no speedup claim; no game runtime performance evidence",
            },
        )
    print(
        json.dumps(
            {
                "migration": migration["counts"],
                "actors": observation["actor_count"],
                "observation_rows": len(observation["rows"]),
                "measure": args.measure,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
