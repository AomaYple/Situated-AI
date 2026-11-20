"""Statically audit current production R2 reader, graph and overlay budgets."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pdx import config, distribution
from pdx.console import enable_utf8_stdio
from pdx.model import Block
from pdx.parser import parse_bytes

if TYPE_CHECKING:
    from pdx.situated.action_network import NetworkProgram

ROOT = Path(__file__).resolve().parents[2]


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

    game = game.resolve()
    if game != config.ROOT.resolve():
        raise ValueError("R2 budget requires the configured production installation")
    authority = r2_reader_authority.verify_installation(game)
    profile = production_profile.load_profile(game)
    reader_sources = cast("list[dict[str, str]]", authority["files"])
    parsed_sources: dict[str, Block] = {}
    for source in reader_sources:
        name = source["path"]
        if name.startswith("game/") and name.endswith(".txt"):
            raw = (game / name).read_bytes()
            if hashlib.sha256(raw).hexdigest() != source["sha256"]:
                raise ValueError(f"R2 native reader source drift: {name}")
            parsed = parse_bytes(raw, name)
            if parsed.errors:
                raise ValueError(f"R2 native reader parse failure: {name}: {parsed.errors}")
            parsed_sources[name] = parsed.root
    programs = network_profile.compile_profile(profile)
    _, _, generated = distribution.package_inputs(profile=profile)
    rows = []
    violations = []
    for program in programs:
        action = program.network.actions[0]
        declaration = next(
            row for row in profile.declarations if row.id == action.definition.consumer_id
        )
        field = [declaration.definition, *declaration.field]
        original = select_block(parsed_sources[declaration.source], field)
        generated_raw = generated[declaration.source.removeprefix("game/")]
        text = generated_raw.decode("utf-8") if isinstance(generated_raw, bytes) else generated_raw
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
                "local_budget_source": "R2 local overlay checks",
                "local_budget_checks": checks,
            }
        )
    generated_files = {}
    for name, value in sorted(generated.items()):
        raw = value if isinstance(value, bytes) else value.encode("utf-8")
        generated_files[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    return {
        "schema": "situated-ai.r2-static-cost/1",
        "evidence_kind": "static_check",
        "game_version": profile.game_version,
        "build_id": profile.build_id,
        "reader_authority": authority,
        "native_parsed_sources": sorted(parsed_sources),
        "policy_source_sha256": hashlib.sha256(network_profile.SOURCE.read_bytes()).hexdigest(),
        "generator_sources": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in sorted((ROOT / "src/pdx").rglob("*.py"))
        ],
        "generated_files": generated_files,
        "programs": rows,
        "budget_violations": violations,
        "budget_status": "failed" if violations else "passed",
        "runtime": "unknown; Python compilation and generation do not measure engine execution",
    }


def main(argv: list[str] | None = None) -> int:
    enable_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = r2_profile_baseline(config.ROOT)
        payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output is None:
            sys.stdout.write(payload)
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(payload, encoding="utf-8", newline="\n")
    except (KeyError, OSError, ValueError) as exc:
        print(f"[R2 budget] {exc}", file=sys.stderr)
        return 2
    return 1 if report["budget_violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
