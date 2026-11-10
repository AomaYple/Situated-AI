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
import re
import subprocess
import sys
import tempfile
import time
import tomllib
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import psutil

from pdx.model import Block, Scalar
from pdx.parser import parse_bytes

if TYPE_CHECKING:
    from pdx.situated.action_network import NetworkProgram

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
R2_CAPABILITY_SOURCES = {
    "game/common/decrees/00_decree.txt": ("cost", "relative_infrastructure", "has_decree"),
    "game/common/ai_strategies/03_political_strategies.txt": (
        "institution_schools",
        "has_journal_entry",
    ),
    "game/common/ai_strategies/01_admin_strategies.txt": ("literacy_rate", "c:FRA"),
    "game/common/alert_types/00_alert_types.txt": ("script_context", "in_default"),
    "game/common/scripted_triggers/05_tsarpoints_scripted_triggers.txt": ("bureaucracy",),
    "game/common/diplomatic_actions/00_relations_actions.txt": (
        "has_attitude",
        "has_diplomatic_pact",
        "cost",
    ),
    "game/common/diplomatic_actions/01_expel_diplomats.txt": ("influence", "has_diplomatic_pact"),
}
R2_DOCUMENTATION_ANCHORS = {
    "game/common/diplomatic_actions/diplomatic_action.md": (
        "In the AI block, the AI country is always root",
        "will_propose = {}",
        "propose_score = {}",
    ),
    "game/common/scripted_buttons/scripted_buttons.md": ("#Country scope", "bureaucracy > 0"),
}
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


def migration_inventory(root: Path = ROOT, *, version: str = "1.14.5") -> dict[str, Any]:
    """Include raw declarations and actual expanded frozen compiler identities."""
    from pdx import decision_adapters  # noqa: PLC0415
    from pdx.situated.compiler import load_model  # noqa: PLC0415
    from pdx.version_contracts import select_version  # noqa: PLC0415

    rows: list[dict[str, Any]] = []
    sources = []
    for path in sorted((root / "mod/decisions").glob("*.toml")):
        raw = path.read_bytes()
        relative = path.relative_to(root).as_posix()
        sources.append({"path": relative, "sha256": digest(raw), "bytes": len(raw)})
        rows.extend(declaration_rows(tomllib.loads(raw.decode("utf-8")), relative))
    # The old denominator must not inherit an ambient 1.15 selection. Current
    # compatibility identities are captured separately with an explicit version.
    with select_version(version):
        model = load_model()
        native_adapter_sources = dict(decision_adapters.load().sources)
    if version == "1.15.0":
        # These versioned ledgers are consumed by the selected compiler; keep
        # their identity separate from the frozen historical declaration rows.
        sources.extend(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": digest(path.read_bytes()),
                "bytes": path.stat().st_size,
            }
            for path in sorted((root / "mod/decisions/1.15.0").glob("*.toml"))
        )
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
        "baseline": (
            "frozen 1.14.5 production declarations and offline compiler; not local 1.15 proof"
            if version == "1.14.5"
            else f"{version} engineering compatibility compiler; not R2 production policy"
        ),
        "contract": CONTRACT,
        "sources": sources,
        "generator_sources": generator_sources,
        "model_source_fingerprints": dict(model.source_sha256),
        "native_adapter_sources": native_adapter_sources,
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


def r2_program_metrics(program: NetworkProgram) -> dict[str, Any]:
    """Report the same structural counts guarded by the declared core budget.

    This is cost accounting, not a second semantic evaluator. Expansion sizes
    deliberately use the compiler's counting functions and are labelled as such.
    """
    from pdx.situated import action_network as net  # noqa: PLC0415

    network = program.network
    aliases = dict(network.fact_aliases)
    graph = {
        node.id: {aliases.get(name, name) for name in node.source_ids}
        for node in network.predicates
    }
    for bridge in network.bridges:
        dependencies = {
            aliases.get(name, name)
            for name in (*bridge.source_ids, *bridge.depends_on, *bridge.condition_fact_ids)
        }
        objective = net._bridge_objective(network, bridge)
        if objective is not None:
            dependencies.update(objective.source_fact_ids)
        graph[bridge.id] = dependencies
    graph.update(
        (f"replacement:{item.id}", {aliases.get(name, name) for name in item.condition_fact_ids})
        for item in network.replacements
    )
    depths: dict[str, int] = {}

    def depth(node: str) -> int:
        if node not in depths:
            depths[node] = 1 + max((depth(child) for child in graph.get(node, ())), default=0)
        return depths[node]

    fanout = Counter(child for dependencies in graph.values() for child in dependencies)
    guards = [item.guard for item in program.contributions]
    guards.extend(guard for _, guard in program.group_guards)
    guards.extend(item.guard for item in program.replacements)
    overlap_seen: dict[tuple[object, ...], set[str]] = {}
    overlap_checks = 0
    for item in program.contributions:
        for root in item.lineage.roots:
            seen = overlap_seen.setdefault((item.effect.action.key, root), set())
            overlap_checks += len(seen - {item.effect_id})
            seen.add(item.effect_id)
    actual = {
        "max_bridges": len(network.bridges),
        "max_edges": sum(map(len, graph.values())),
        "max_fanout": max(fanout.values(), default=0),
        "max_depth": max((depth(name) for name in graph), default=0),
        "max_guard_nodes": sum(net._guard_count(guard) for guard in guards),
        "max_overlap_checks": overlap_checks,
    }
    expansion_costs: dict[str, tuple[int, int]] = {}
    expressions = [
        (node.id, node.expression)
        for node in sorted(network.predicates, key=lambda node: depth(node.id))
    ]
    expressions.extend((bridge.id, bridge.condition) for bridge in network.bridges)
    expressions.extend((f"replacement:{item.id}", item.condition) for item in network.replacements)
    expansion_rows = {}
    for name, expression in expressions:
        cost = net._expression_cost(
            expression, expansion_costs, aliases, network.budget.max_guard_nodes
        )
        expansion_rows[name] = {"nodes": cost[0], "depth": cost[1]}
        if name in {node.id for node in network.predicates}:
            expansion_costs[name] = cost
    limits = asdict(network.budget)
    checks = {
        name: {"actual": value, "limit": limits[name], "passed": value <= limits[name]}
        for name, value in actual.items()
    }
    for name, actual_value, limit in (
        (
            "pre_expansion_guard_nodes",
            max((row["nodes"] for row in expansion_rows.values()), default=0),
            network.budget.max_guard_nodes,
        ),
        (
            "pre_expansion_expression_depth",
            max((row["depth"] for row in expansion_rows.values()), default=0),
            network.budget.max_depth * 2,
        ),
    ):
        checks[name] = {"actual": actual_value, "limit": limit, "passed": actual_value <= limit}
    return {
        "raw_facts": len(network.facts),
        "derived_predicates": len(network.predicates),
        "dag_nodes": len(set(graph) | {item.id for item in network.facts}),
        "dag_edges": actual["max_edges"],
        "dag_depth": actual["max_depth"],
        "fanout": dict(sorted(fanout.items())),
        "expanded_guard_nodes": actual["max_guard_nodes"],
        "pre_expansion_expressions": expansion_rows,
        "contributions": len(program.contributions),
        "assessment_groups": len(network.groups),
        "replacements": len(network.replacements),
        "residuals": len(network.residuals),
        "declared_budget": limits,
        "budget_checks": checks,
        "counting_basis": "compiler DAG and occurrence-based expanded guard accounting; not engine work",
    }


def r2_profile_baseline(game: Path) -> dict[str, Any]:
    """Actually verify readers, parse native inputs, compile and build R2 in memory."""
    from pdx.situated import (  # noqa: PLC0415
        action_network,
        network_profile,
        production_profile,
        r2_reader_authority,
    )

    authority = r2_reader_authority.verify_installation(game)
    r2_reader_authority.verify_frozen()
    profile = production_profile.load_profile(game)
    reader_sources = cast("list[dict[str, str]]", authority["files"])
    parsed_sources: dict[str, Block] = {}
    for source in reader_sources:
        name = source["path"]
        if name.startswith("game/") and name.endswith(".txt"):
            parsed = parse_bytes((game / name).read_bytes(), name)
            if parsed.errors:
                raise ValueError(f"R2 native reader parse failure: {name}: {parsed.errors}")
            parsed_sources[name] = parsed.root
    programs = network_profile.compile_profile(profile)
    generated = network_profile.build(profile)
    rows = []
    violations = []
    for program in programs:
        action = program.network.actions[0]
        declaration = next(
            row for row in profile.declarations if row.id == action.definition.consumer_id
        )
        field = [declaration.definition, *declaration.field]
        original = select_block(parsed_sources[declaration.source], field)
        text = generated[declaration.source.removeprefix("game/")]
        parsed = parse_bytes(text.encode("utf-8"), declaration.source)
        if parsed.errors:
            raise ValueError(f"R2 generated parse failure: {declaration.source}: {parsed.errors}")
        consumer = select_block(parsed.root, field)
        matches = list(
            re.finditer(
                rf"# SITAI POLICY {re.escape(profile.game_version)} BEGIN {re.escape(declaration.id)}\n"
                rf"(?P<body>[\s\S]*?)# SITAI POLICY {re.escape(profile.game_version)} END {re.escape(declaration.id)}\n",
                text,
            )
        )
        if len(matches) != 1:
            raise ValueError(f"R2 generated overlay identity mismatch: {declaration.id}")
        overlay = matches[0].group("body")
        overlay_ast = parse_bytes(overlay.encode("utf-8"), "R2 overlay")
        if overlay_ast.errors:
            raise ValueError(f"R2 overlay parse failure: {overlay_ast.errors}")
        metrics = r2_program_metrics(program)
        specialized = action_network.specialize_program(
            program, tuple(fact.id for fact in program.network.facts)
        )
        specialized_nodes = sum(
            action_network._guard_count(item.guard) for item in specialized.contributions
        )
        metrics["specialized_guard_nodes"] = specialized_nodes
        metrics["budget_checks"]["specialized_guard_nodes"] = {
            "actual": specialized_nodes,
            "limit": program.network.budget.max_guard_nodes,
            "passed": specialized_nodes <= program.network.budget.max_guard_nodes,
        }
        original_metrics = block_metrics(original)
        generated_metrics = block_metrics(consumer)
        overlay_metrics = block_metrics(overlay_ast.root)
        manifest = next(
            item for item in profile.registry.manifests if item.id == declaration.domain
        )
        query_count = sum(overlay_metrics["query_forms"].values())
        reader_counts: Counter[str] = Counter()
        scope_hops = 0
        stack = [(overlay_ast.root, 0)]
        engines = {
            fact.id: network_profile.READERS[fact.id].reader.engine
            for fact in program.network.facts
        }
        while stack:
            current, hops = stack.pop()
            for entry in current.assignments():
                reader_counts.update(
                    name for name, engine in engines.items() if entry.key == engine
                )
                next_hops = hops + int(
                    entry.key in {"country", "scope:country", "scope:target_country"}
                )
                scope_hops = max(scope_hops, next_hops)
                if isinstance(entry.value, Block):
                    stack.append((entry.value, next_hops))
        local_checks = {
            "selected_candidates_per_evaluation": (
                len(program.network.actions),
                manifest.object_budget,
            ),
            "additional_iterators": (query_count, 0),
            "additional_candidate_expansion": (query_count, 0),
            "cross_candidate_cartesian_products": (query_count, 0),
            "additional_global_scans": (query_count, 0),
            "additional_scope_path_hops": (scope_hops, 1),
            "additional_consumer_block_depth": (
                max(0, generated_metrics["block_depth"] - original_metrics["block_depth"]),
                3,
            ),
        }
        checks = {
            name: {"actual": actual, "limit": limit, "passed": actual <= limit}
            for name, (actual, limit) in local_checks.items()
        }
        for name, check in {**metrics["budget_checks"], **checks}.items():
            if not check["passed"]:
                violations.append({"consumer": declaration.id, "budget": name, **check})
        rows.append(
            {
                "consumer": declaration.id,
                "source": declaration.source,
                "field": field,
                "network": metrics,
                "original_consumer_ast": original_metrics,
                "generated_consumer_ast": generated_metrics,
                "overlay_ast": overlay_metrics,
                "overlay_bytes": len(overlay.encode("utf-8")),
                "generated_file_bytes": len(text.encode("utf-8")),
                "readers": {
                    "declared": sorted(engines),
                    "generated_occurrences": dict(sorted(reader_counts.items())),
                    "repeated_occurrences": sum(
                        max(0, count - 1) for count in reader_counts.values()
                    ),
                    "evaluation_count_per_tick": "unknown; native consumer on demand",
                },
                "object_budget_source": "ProductionProfile.registry.manifests.object_budget",
                "local_budget_source": f"{CONTRACT}#A0-BUDGET-LOCAL-ONLY",
                "local_budget_checks": checks,
            }
        )
    return {
        "schema": "situated-ai.r2-static-cost/1",
        "evidence_kind": "actual_offline_compile_and_generation",
        "game_version": profile.game_version,
        "build_id": profile.build_id,
        "reader_authority": authority,
        "native_parsed_sources": sorted(parsed_sources),
        "policy_source_sha256": digest(network_profile.SOURCE.read_bytes()),
        "generator_sources": [
            {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path.read_bytes())}
            for path in sorted((ROOT / "src/pdx").rglob("*.py"))
        ],
        "generated_files": {
            name: {"sha256": digest(text.encode("utf-8")), "bytes": len(text.encode("utf-8"))}
            for name, text in sorted(generated.items())
        },
        "programs": rows,
        "budget_violations": violations,
        "budget_status": "failed" if violations else "passed",
        "runtime": "unknown; Python compilation and generation do not measure engine execution",
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
        if failure.get("kind") == "scanner_source_changed_during_scan":
            impact = "blocks_source_identity; rescan_required"
        elif path in selected:
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


def capability_inventory(inventory: dict, game: Path) -> dict[str, Any]:
    """Bind R2 scope-transfer arguments to complete, current native source bytes.

    A native example and a preserved scope establish a static argument, never
    engine execution, current balances, activated DLC or successful actions.
    """
    files = {item["path"]: item for item in inventory["files"]}
    failed = {item.get("path") for item in inventory.get("failures", [])}
    sources = []
    for relative in sorted(set(R2_CAPABILITY_SOURCES) | set(R2_DOCUMENTATION_ANCHORS)):
        entry = files.get(relative)
        path = (game / relative).resolve()
        if not path.is_relative_to(game.resolve()):
            raise ValueError(f"capability source outside installation: {relative}")
        if (
            entry is None
            or relative in failed
            or entry.get("parse_status") not in {"parsed", "not_pdx"}
        ):
            raise ValueError(f"missing/incomplete capability source: {relative}")
        raw = path.read_bytes()
        if digest(raw) != entry["sha256"]:
            raise ValueError(f"capability source drift: {relative}")
        if relative in R2_CAPABILITY_SOURCES:
            occurrences = {
                key: source_occurrences(raw, relative, key)
                for key in R2_CAPABILITY_SOURCES[relative]
            }
            if any(not rows for rows in occurrences.values()):
                raise ValueError(f"capability assignment missing: {relative}")
            evidence: dict[str, Any] = {"assignments": occurrences}
        else:
            lines = raw.decode("utf-8-sig").splitlines()
            anchors = []
            for anchor in R2_DOCUMENTATION_ANCHORS[relative]:
                matches = [
                    {"line": n, "text": line} for n, line in enumerate(lines, 1) if anchor in line
                ]
                if not matches:
                    raise ValueError(
                        f"capability documentation anchor missing: {relative}: {anchor}"
                    )
                anchors.extend(matches)
            evidence = {"documentation": anchors}
        sources.append({"path": relative, "sha256": entry["sha256"], **evidence})
    return {
        "schema": "situated-ai.r2-native-capability/1",
        "evidence_kind": "static_check",
        "native_inventory_identity": inventory["inventory_sha256"],
        "sources": sources,
        "reader_contracts": [
            {
                "id": "school_literacy",
                "condition": "literacy_rate < 0.35",
                "actor": "root country",
                "proof": "school institution_scores country journal scope; administrative strategy country weight numeric limit; scope_preserving_transfer",
            },
            {
                "id": "school_default",
                "condition": "in_default = yes",
                "actor": "root country",
                "proof": "school country scope; country_default alert script_context=player_country; scope_preserving_transfer",
            },
            {
                "id": "school_bureaucracy",
                "condition": "bureaucracy < 0",
                "actor": "root country",
                "proof": "school country scope; official scripted button Country scope bureaucracy comparison; native scripted trigger corroboration; scope_preserving_transfer",
            },
            {
                "id": "diplomatic_influence",
                "condition": "influence < 200",
                "actor": "root AI country",
                "proof": "official AI root contract; expel_diplomats will_propose root influence read; same AI scope transferred to increase_relations.propose_score",
            },
            {
                "id": "observed_separatism",
                "condition": "scope:target_country = { has_diplomatic_pact = { who = root type = support_separatism } }",
                "actor": "root AI country",
                "target": "scope:target_country",
                "proof": "expel_diplomats native target-to-root actual pact read; official shared AI scope; scope_preserving_transfer",
            },
        ],
        "unsupported_inferences": [
            "road cost=100 does not prove readable current actor authority balance",
            "school institution_investment_level parameter not established by these sources",
            "planned action or attitude alone is not an observed relationship",
            "score cost terms do not reserve, spend or deduct engine resources",
        ],
        "proposed_minimum": {
            "consumer_extension_required": False,
            "school": "literacy/agenda education benefit opposed independently by default and bureaucracy pressure",
            "diplomacy": "protective objective opposed by influence pressure; observed target separatism pact causes defensive response",
            "direct": "actor literacy/default/bureaucracy/influence reads",
            "derived": "same actor benefit and independently retained resource costs",
            "interaction": "actual target-to-actor support_separatism pact, preserving direction",
            "native_gates": "preserve all; candidate eligibility remains native and runtime unknown",
        },
        "query_budget": {
            "proposal": "consumer immediate root read plus exact target scope; no all-country search",
            "refresh": "this_consumer_evaluation; no engine persistent cache claim",
            "runtime_cost": "unknown; source shape is not measured engine cost",
        },
        "dlc": inventory.get("dlc", {}),
        "localization_languages": inventory.get("localization", {}).get("languages", []),
        "scan_limitations": classify_failures(inventory),
        "runtime": "unknown; game not started",
    }


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
                "consumer_wiring": "not_assessed_by_A0_enumeration",
                "objective_wiring": "not_assessed_by_A0_enumeration",
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
                "wiring": "not_assessed_by_A0_enumeration",
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
        "new_1_15_configuration": "not_assessed_by_A0_inventory; inspect current production profile configuration contract",
        "dlc": native_inventory.get("dlc", {}),
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
    elif kind == "r2_profile":
        result = r2_profile_baseline(game)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if result["budget_violations"]:
            raise ValueError("R2 static cost exceeds declared budgets; see worker JSON")
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
    parser.add_argument(
        "--r2", action="store_true", help="also bind R2 reader scope-transfer evidence"
    )
    parser.add_argument("--worker", choices=("parse_samples", "offline_model", "r2_profile"))
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
        "configuration-baseline.json",
        "cost-baseline.json",
        "capability-baseline.json",
    }:
        raise ValueError("output would overwrite input inventory")
    inventory_raw = args.inventory.read_bytes()
    inventory = read_inventory(inventory_raw)
    validate_inventory(inventory, args.game_root)
    migration = migration_inventory()
    observation = observation_inventory(inventory, args.game_root)
    static = static_samples(args.game_root)
    if args.r2:
        static["r2_profile"] = r2_profile_baseline(args.game_root)
    capability = capability_inventory(inventory, args.game_root) if args.r2 else None
    validate_inventory(inventory, args.game_root)
    reports = [
        ("migration", migration),
        ("observation", observation),
        ("actor-objectives", objectives(observation)),
        ("static-baseline", static),
        ("configuration-baseline", configuration_inventory(inventory)),
    ]
    if capability is not None:
        reports.append(("capability-baseline", capability))
    for name, data in reports:
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
        if args.r2:
            commands.append(
                ("r2_profile_compile_and_generate", [*prefix, *base, "--worker", "r2_profile"])
            )
        measurements = []
        for identity, command in commands:
            result = measure(command, game=args.game_root)
            result["id"] = identity
            log = args.output.resolve() / f"cost-{identity}.log"
            log.write_text(result.pop("output"), encoding="utf-8", newline="\n")
            # Receipts resolve log paths relative to the directory containing
            # cost-baseline.json.  Keep that contract identical for repository
            # and temporary outputs; a ROOT-relative path would be ambiguous
            # when the caller writes evidence outside the repository.
            result["log"] = log.relative_to(args.output.resolve()).as_posix()
            measurements.append(result)
        write_json(
            args.output / "cost-baseline.json",
            {
                "schema": "situated-ai.a0-offline-cost/1",
                "evidence_kind": "measured_offline",
                "producer_sha256": digest(Path(__file__).read_bytes()),
                "input_inventory_sha256": digest(inventory_raw),
                "log_base": "cost-baseline.json parent",
                "python": sys.version,
                "platform": platform.platform(),
                "parallelism": 1,
                "sample_identities": static["samples"],
                "r2_profile": static.get("r2_profile"),
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
    return int(bool(static.get("r2_profile", {}).get("budget_violations")))


if __name__ == "__main__":
    raise SystemExit(main())
