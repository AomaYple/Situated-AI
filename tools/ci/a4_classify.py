"""Finite classification of the accepted capture, without new discovery or authority.

Syntax, exact native knowledge, and product acceptance are separate axes. The
classification is reproducible from the immutable capture and curated selectors;
neither literal syntax nor a matching native field signs a product obligation.
"""

from __future__ import annotations

import argparse
import dataclasses
import io
import re
import zipfile
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

from tools.ci import a4_discovery as discovery
from tools.ci.a4_schema import goal_stage

DIRECTORY = "research/vanilla-ai/1.15.0/classification"
ROOT_PATH = f"{DIRECTORY}/root.json"
TARGET_PATH = f"{DIRECTORY}/target-inputs.json"
MIGRATION_PATH = f"{DIRECTORY}/migration-objectives.json"
MIGRATION_RECEIPT = f"{DIRECTORY}/evidence/migration-final/receipt.json"
MIGRATION_ACCEPTANCE = f"{DIRECTORY}/migration-acceptance.json"
STAGES_PATH = f"{DIRECTORY}/stage-assignments.json"
TASK6_LOCK_SHA256 = "5eacc1f98babf85d8223328ca8d51556c33417afda1b088155c4e4a72eb96816"
CURRENT_LOCK_SHA256 = "60ce9c4392c1831b91947b89aee212795d1f9b7953e920edf1565e6b6abf3b9b"
REPORT_PATH = f"{DIRECTORY}/investigation.json"
INPUTS = ("tools/ci/a4_classify.py", "tests/test_a4_classify.py", TARGET_PATH, MIGRATION_PATH)
REPEATED = f"{DIRECTORY}/evidence/repeated/candidate.json"
TASK6_PACKAGE = f"{DIRECTORY}/evidence/task6-package.zip.gz"
TASK6_PACKAGE_SHA256 = "f0820cad970ab6eb78c5827e9dda8421bb2e3520b78f0ceae1694b78889e3d2b"
TASK6_LOCK = f"{DIRECTORY}/evidence/task6-generation-lock.json.gz"
PACKAGE = f"{DIRECTORY}/evidence/task8-package.zip.gz"
PACKAGE_SHA256 = "afba2c1212a239ba4f95f4312e13ab7357a46d884010766a3e50c2998cf879f6"
PACKAGE_BYTES = 1392670
CURRENT_DIRECTORY = f"{DIRECTORY}/current"
CURRENT_INTAKE = f"{CURRENT_DIRECTORY}/intake.json"
CURRENT_ROOT = f"{CURRENT_DIRECTORY}/root.json"
CURRENT_REPORT = f"{CURRENT_DIRECTORY}/investigation.json"
CURRENT_NATIVE_REPORT = f"{CURRENT_DIRECTORY}/native-investigation.json"
CONSTRUCTION_CHANGES = {
    "remaining_industrial_construction_need",
    "remaining_industrial_construction_need_funded",
    "remaining_reconstruction_need",
    "remaining_reconstruction_need_funded",
    "fiscal_construction_guard",
    "liquidity_construction_guard",
}
CONTRACTS = {
    "ai_strategies": ("victoria3-1.15.0-strategy-scope.json", "consumers"),
    "technology": ("victoria3-1.15.0-technology-scope.json", "consumer"),
    "company_types": ("victoria3-1.15.0-company-scope.json", "contracts"),
    "country_creation": ("victoria3-1.15.0-country-definition-scope.json", "contracts"),
    "country_formation": ("victoria3-1.15.0-country-definition-scope.json", "contracts"),
    "laws": ("victoria3-1.15.0-law-scope.json", "contract"),
}
# These are syntax roles, not assertions about an undocumented native evaluator.
PREDICATES = {
    "possible",
    "can_build",
    "ai_possible",
    "will_propose",
    "will_accept",
    "will_break",
    "will_propose_with_states",
    "ai_will_cancel_for_transportation",
    "potential",
    "complete",
    "state_target",
    "country_target",
    "is_significant_demand",
    "settles_grievance",
}
CALLBACKS = {"on_create", "on_complete", "on_fail", "on_cancel"}
STATIC_FAMILIES = {
    "defines",
    "modifier_type_definitions",
    "country_ranks",
    "subject_types",
    "diplomatic_plays",
    "ship_types",
    "production_method_groups",
    "ai_strategic_region_stance_types",
    "cohesion_levels",
}


def pointer(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def native_contracts(sources: Any) -> dict[str, Any]:
    return {
        family: {
            "path": f"research/situated/{filename}",
            "data": sources.json(f"research/situated/{filename}"),
            "member": member,
        }
        for family, (filename, member) in CONTRACTS.items()
    }


def applicable_contract(
    surface: dict[str, Any], source_hash: str, contracts: dict[str, Any]
) -> dict[str, Any] | None:
    """Reuse only the exact owning family/field and actual complete source pin."""
    family = surface["family"]
    record = contracts.get(family)
    if record is None:
        return None
    data, field = record["data"], surface["field"]
    if data["script_hashes"].get(surface["source"]) != source_hash:
        return None
    if family == "ai_strategies":
        # Nested map members inherit a *container* reference, never writer authority.
        field = field.split(".", 1)[0]
        if field not in data["consumers"]:
            return None
        identity = f"consumers/{pointer(field)}"
        contract = data["consumers"][field]
    elif family == "technology":
        if field != "ai_weight":
            return None
        identity, contract = "consumer", data["consumer"]
    elif family in {"country_creation", "country_formation", "company_types"}:
        allowed = {"ai_will_do", "ai_weight"} if family == "company_types" else {"ai_will_do"}
        if field not in allowed:
            return None
        # Preserve the exact contract object. Its schema differs between owning classes.
        selected = [
            item
            for item in data["contracts"]
            if item.get("field", item.get("hook")) == field and item.get("family", family) == family
        ]
        if len(selected) != 1:
            raise ValueError("native contract field/owner is not unique")
        identity, contract = "contracts", selected[0]
    else:
        if field != "ai_will_do":
            return None
        identity, contract = "contract", data["contract"]
    return {
        "path": record["path"],
        "identity": identity,
        "contract_sha256": discovery.digest(contract),
        "owning_family": family,
        "owning_field": field,
        "applicability": "exact_source_and_owner_field",
        "actor": contract.get("actor_scope", contract.get("actor", "pending")),
        "target": contract.get("target_scope", contract.get("target", "pending")),
        "operation": contract.get("operation", "pending"),
        "unit": contract.get("unit", "pending"),
        "merge": data.get("strategy_field_merges", {}).get(field, "see_exact_contract"),
        "permission": "none; classification is not producer integration",
    }


def syntax_kind(family: str, field: str, node: dict[str, Any] | None) -> str:
    if node is None:
        return "missing_field"
    if family in {"script_values", "scripted_triggers"}:
        return "source_helper"
    if field.rsplit(".", maxsplit=1)[-1] in CALLBACKS:
        return "source_callback"
    value = node["value"] if node["kind"] == "assignment" else node
    if value["kind"] == "scalar":
        token = value["text"]
        if token in {"yes", "no"}:
            return "literal_boolean"
        try:
            Decimal(token)
        except InvalidOperation:
            return "literal_enum_or_reference"
        return "literal_constant"
    if value["kind"] != "block":
        return "unresolved_syntax"
    items = value["items"]
    if all(item["kind"] == "scalar" for item in items) and items:
        return "literal_list"
    keys = {item.get("key") for item in items}
    if family in STATIC_FAMILIES:
        return "literal_map"
    if field.rsplit(".", maxsplit=1)[-1] in PREDICATES:
        return "predicate_expression"
    if keys & {"base", "add", "factor", "multiply", "value", "min", "max"}:
        return "numeric_expression"
    return "structured_map_or_predicate_pending"


def walk(node: dict[str, Any]):
    yield node
    if node["kind"] == "assignment":
        yield from walk(node["value"])
    elif node["kind"] == "block":
        for child in node["items"]:
            yield from walk(child)


def select(records: dict[str, Any], selectors: list[dict[str, str]]) -> list[str]:
    """Expand curated object selectors to physical IDs; never match a display name."""
    return sorted(
        identity
        for identity, item in records.items()
        if any(
            re.fullmatch(rule["family"], item["family"])
            and re.search(rule["definition"], item["definition"])
            and re.search(rule["field"], item["field"])
            for rule in selectors
        )
    )


def classify(
    raw: dict[str, Any], catalog: dict[str, Any], contracts: dict[str, Any]
) -> dict[str, Any]:
    """Classify all raw discoveries; bind exact AST owner, parent and references."""
    owners = discovery.unique(raw["definitions"], "declaration_id")
    surfaces = discovery.unique(raw["surfaces"], "declaration_id")
    slots = {
        member: slot for slot in raw["event_slots"] for member in slot["surface_declaration_ids"]
    }
    options = {
        (o["source"], o["definition"], o["option_index"], o["source_line"]): o
        for o in raw["event_options"]
    }
    references: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ref in raw["references"]:
        references[ref["source"]].append(ref)
    definitions_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for owner in owners.values():
        definitions_by_source[owner["source"]].append(owner)
    observations: dict[str, Any] = {}
    for identity, entry in catalog["entries"].items():
        # Canonical ID/source/raw identity remain in the accepted catalog. Store
        # only the classification axis instead of duplicating that entire index.
        observations[identity] = {
            "source": "parent_source",
            "definition": "parent_structure",
            "syntax": "complete_syntax",
            "reference": "reference_protection",
            "unclassified": "unresolved_observation",
            "slot": "physical_option",
            "surface": "surface",
        }[entry["kind"]]
    physical: dict[str, Any] = {}
    structures: dict[str, Any] = {}
    for source, syntax in sorted(raw["source_syntax"].items()):
        tree = discovery.strict_json(syntax["syntax_json"])
        source_owners = definitions_by_source[source]
        sibling_hash = discovery.digest([n["node_id"] for n in tree["items"]])
        for owner in source_owners:
            parent = tree["items"][owner["definition_index"]]
            if parent["key"] != owner["definition"] or parent["line"] != owner["source_line"]:
                raise ValueError("classification wrong owner/AST binding")
            nodes = list(walk(parent))
            by_line: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for node in nodes:
                if node["kind"] == "assignment":
                    by_line[node["line"]].append(node)
            node_lines = {n["line"] for n in nodes}
            source_refs = [
                ref["reference_id"] for ref in references[source] if ref["line"] in node_lines
            ]
            owner_id = owner["declaration_id"]
            structures[owner_id] = {
                "family": owner["directory"],
                "field": "__definition__",
                "source": source,
                "source_sha256": raw["source_hashes"][source],
                "definition": owner["definition"],
                "definition_index": owner["definition_index"],
                "node_id": parent["node_id"],
                "node_position": parent["node_position"],
                "complete_parent_sha256": discovery.digest(parent),
                "source_syntax_sha256": syntax["syntax_sha256"],
                "sibling_membership_sha256": sibling_hash,
                "sibling_count": len(tree["items"]),
                "reference_ids": sorted(source_refs),
                "reference_resolution": "pending; lexical references are not a closed call graph",
                "protection_acceptance": "pending; closed/player paths and exact product need require separate witnesses",
            }
            for member in owner["surface_declaration_ids"]:
                surface = surfaces[member]
                family = owner["directory"]
                field = surface["field"]
                slot = slots.get(member)
                option = None
                if slot:
                    option = options[
                        (source, owner["definition"], slot["option_index"], slot["source_line"])
                    ]
                if field == "__body__":
                    candidates = [parent["value"]]
                elif option and not option["weight_lines"]:
                    candidates = []
                else:
                    key = field.rsplit(".", 1)[-1]
                    candidates = [n for n in by_line[surface["source_line"]] if n["key"] == key]
                if not candidates and not (option and not option["weight_lines"]):
                    raise ValueError(
                        f"classification missing physical field: {source}:{field}:{surface['source_line']}"
                    )
                record = {
                    "raw_discovery_id": f"D:native:{raw['target_version']}:surface:{member}",
                    "canonical_id": catalog["entries"][
                        f"D:native:{raw['target_version']}:surface:{member}"
                    ]["group"],
                    "owner_id": owner_id,
                    "family": family,
                    "source": source,
                    "source_sha256": raw["source_hashes"][source],
                    "definition": owner["definition"],
                    "field": field,
                    "field_occurrence": surface["declaration_occurrence"],
                    "source_line": surface["source_line"],
                    "node_ids": [n["node_id"] for n in candidates],
                    "node_positions": [n["node_position"] for n in candidates],
                    "syntax_kind": syntax_kind(
                        family, field, candidates[0] if len(candidates) == 1 else None
                    ),
                    "original_ambiguity": surface["ambiguity"],
                    "ownership_resolution": "unique_physical_slot"
                    if slot
                    else "exact_owner_occurrence",
                    "interface_status": "pending",
                    "obligation_status": "pending",
                    "role": "caller_context_pending"
                    if family in {"script_values", "scripted_triggers"}
                    else "exact_native_role_pending",
                    "contract": None,
                    "writer_authority": False,
                    "getter_authority": False,
                    "question_owner": "controller/native-interface; product owner for objective applicability",
                    "question": f"{family}.{field}: exact consumer/role/default/reject and objective applicability remain unsigned",
                    "slot": None,
                }
                if option:
                    assert slot is not None
                    option_nodes = [n for n in by_line[slot["source_line"]] if n["key"] == "option"]
                    if len(option_nodes) != 1:
                        raise ValueError("physical option AST ownership is not unique")
                    record["slot"] = {
                        "slot_id": slot["slot_id"],
                        "option_index": slot["option_index"],
                        "event_type": option["event_type"],
                        "explicit_weight": bool(option["weight_lines"]),
                        "default_option": option["default_option"],
                        "original_ambiguities": slot["ambiguities"],
                        "node_id": option_nodes[0]["node_id"],
                        "node_position": option_nodes[0]["node_position"],
                    }
                contract = applicable_contract(record, raw["source_hashes"][source], contracts)
                if contract:
                    record.update(
                        contract=contract,
                        interface_status="exact_contract_reuse_candidate",
                        role=f"actor={contract['actor']}; target={contract['target']}",
                        question="Exact native contract exists; integrate only at its owning field, role and source; product need/writer witness pending",
                    )
                physical[member] = record
    if set(physical) != set(surfaces):
        raise ValueError("classification lost physical surfaces")
    return {
        "observations": observations,
        "physical": physical,
        "structures": structures,
        "raw_duplicates": catalog["raw_duplicates"],
        "unexpanded_observations": raw["unsupported_structures"],
    }


def product_maps(
    physical: dict[str, Any],
    targets: dict[str, Any],
    old: list[dict[str, Any]],
    structures: dict[str, Any],
    migrations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for goal, target in targets["directions"].items():
        members = select(physical, target["selectors"])
        if not members:
            raise ValueError(f"target has no actual physical members: {goal}")
        result[goal] = {
            **target,
            "kind": "product_direction",
            "physical_ids": members,
            "structural_ids": select(structures, target["structure_selectors"]),
            "canonical_ids": sorted({physical[m]["canonical_id"] for m in members}),
            "status": "pending",
            "stage": "A4-3",
        }
    for goal, target in targets["relations"].items():
        ends = {
            name: sorted({m for direction in directions for m in result[direction]["physical_ids"]})
            for name, directions in target["endpoints"].items()
        }
        structural_ends = {
            name: sorted(
                {m for direction in directions for m in result[direction]["structural_ids"]}
            )
            for name, directions in target["endpoints"].items()
        }
        result[goal] = {
            **target,
            "kind": "product_relation",
            "physical_endpoints": ends,
            "physical_ids": sorted({m for ids in ends.values() for m in ids}),
            "structural_endpoints": structural_ends,
            "structural_ids": sorted({m for ids in structural_ends.values() for m in ids}),
            "status": "pending",
            "stage": "A4-4",
        }
    for goal, target in targets["crosscutting"].items():
        result[goal] = {
            **target,
            "kind": "product_crosscutting",
            "physical_ids": sorted(physical),
            "structural_ids": [],
            "status": "pending",
            "stage": "A4-5",
        }
    for goal, target in targets["program"].items():
        result[goal] = {
            **target,
            "kind": "program_goal",
            "physical_ids": sorted(physical),
            "structural_ids": [],
            "status": "pending",
            "stage": goal_stage(goal),
        }
    predecessors = {}
    for item in old:
        parent = item["parent"]
        target_id = parent if parent in result else item["id"].rsplit(".", 1)[0]
        if parent.startswith("C"):
            target_id = {
                "C1": "G02",
                "C2": "G03",
                "C3": "G04",
                "C4": "G04",
                "C5": "G04",
                "C6": "G05",
                "C7": "G06",
                "C8": "G07",
                "C9": "G07",
            }.get(parent, "G07")
        members = result[target_id]["physical_ids"] if target_id in result else sorted(physical)
        # Exact investigations narrow old implemented objectives; unmatched questions stay pending.
        text = item["consumer_investigation"]
        sources = re.findall(r"(?:common|events)/[A-Za-z0-9_./-]+\.txt", text)
        narrowed = [m for m in members if physical[m]["source"] in sources]
        parents = result[target_id]["structural_ids"] if target_id in result else sorted(structures)
        narrowed_parents = [m for m in parents if structures[m]["source"] in sources]
        exact = (migrations or {}).get(item["id"])
        if exact:
            narrowed = select(physical, exact["selectors"])
            if not narrowed:
                raise ValueError(
                    f"implemented predecessor has no exact current physical consumer: {item['id']}"
                )
        predecessors[item["id"]] = {
            "kind": "predecessor_objective",
            "old_id": item["id"],
            "old_status": item["status"],
            "parent": parent,
            "title": item["title"],
            "question": item["question"],
            "acceptance": item["acceptance"],
            "original_object_sha256": discovery.digest(item),
            "current_target": target_id,
            "physical_ids": narrowed or members,
            "structural_ids": narrowed_parents if sources else parents,
            "source_paths": item["source_paths"],
            "consumer_investigation": text,
            "status": "pending",
            "mapping_precision": "exact_source_owner_field_role"
            if exact
            else "exact_investigated_source_candidates"
            if narrowed
            else "direction_members_require_objective_split",
            "remaining": "Reverify exact original objective against current reader/writer/AST/package and case coverage; mapping does not inherit historical status",
            "migration_contract": exact,
        }
    return {"targets": result, "predecessors": predecessors}


def verify_product_maps(
    maps: dict[str, Any], physical: dict[str, Any], goals: set[str], old_ids: set[str]
) -> None:
    if set(maps["targets"]) != goals or set(maps["predecessors"]) != old_ids:
        raise ValueError("classification original goal/predecessor coverage")
    for item in [*maps["targets"].values(), *maps["predecessors"].values()]:
        if not item["physical_ids"] or set(item["physical_ids"]) - set(physical):
            raise ValueError("classification dangling physical product mapping")
        if item["status"] != "pending":
            raise ValueError("classification cannot sign product completion")


def migration_files(sources: Any) -> dict[str, Any]:
    """Bind the actual current package and preserve the immutable Task6 comparison."""
    from pdx.parser import parse_text  # noqa: PLC0415

    packed = sources.read(PACKAGE)
    package = discovery.unpack(packed, PACKAGE_BYTES)
    if discovery.sha(package) != PACKAGE_SHA256:
        raise ValueError("fixed current migration package identity")
    historical_package = discovery.unpack(sources.read(TASK6_PACKAGE), 1392674)
    historical_lock_raw = discovery.unpack(sources.read(TASK6_LOCK), 42856)
    if (
        discovery.sha(historical_package) != TASK6_PACKAGE_SHA256
        or discovery.sha(historical_lock_raw) != TASK6_LOCK_SHA256
    ):
        raise ValueError("immutable Task6 historical package/lock identity")
    historical_lock = discovery.strict_json(historical_lock_raw)
    if sources.hash("mod/generation-lock.json") != CURRENT_LOCK_SHA256:
        raise ValueError("current migration lock differs from fixed selector-proof candidate")
    lock = sources.json("mod/generation-lock.json")
    if lock["files"] != historical_lock["files"]:
        raise ValueError("proof-only selector integration changed production payloads")
    for path, digest in lock["sources"].items():
        if sources.hash(path) != digest:
            raise ValueError(f"migration source after repin: {path}")
    result = {}
    with (
        zipfile.ZipFile(io.BytesIO(package)) as archive,
        zipfile.ZipFile(io.BytesIO(historical_package)) as historical,
    ):
        if len(set(archive.namelist())) != len(archive.namelist()):
            raise ValueError("duplicate fixed migration package member")
        for path, digest in lock["files"].items():
            generated = sources.read(f"mod/{path}")
            if discovery.sha(generated) != digest:
                raise ValueError(f"migration generated byte drift: {path}")
            delivered = archive.read(path)
            if delivered != historical.read(path):
                raise ValueError(f"proof-only selector integration changed Task6 payload: {path}")
            # The package boundary adds BOM to game text. Compare the entire
            # normalized payload, never just generated marker counts.
            if path.endswith((".txt", ".yml")):
                if delivered != b"\xef\xbb\xbf" + generated:
                    raise ValueError(f"migration package text differs: {path}")
            elif delivered != generated:
                raise ValueError(f"migration package member differs: {path}")
            result[path] = {
                "generated_sha256": digest,
                "package_sha256": discovery.sha(delivered),
                "task6_generated_sha256": historical_lock["files"][path],
                "task6_package_sha256": discovery.sha(historical.read(path)),
                "bytes": len(generated),
                "ast_sha256": discovery.digest(
                    dataclasses.asdict(parse_text(generated.decode()).root)
                )
                if path.endswith(".txt")
                else None,
            }
    return result


def program_reader_facts(writer: dict[str, Any]) -> dict[str, Any]:
    """Keep existing program-local getters in their exact writer context."""
    programs = [
        writer[name]
        for name in ("event_program", "acceptance_program", "regional_resource_program")
        if name in writer
    ]
    if not programs:
        return {}
    if len(programs) != 1:
        raise ValueError("ambiguous current program reader owner")
    program = programs[0]
    readers = {reader["key"]: reader for reader in program["readers"]}
    bindings = {
        key: (scope, kind, role) for key, scope, kind, role in writer["reader_context_bindings"]
    }
    if len(readers) != len(program["readers"]) or set(readers) != set(bindings):
        raise ValueError("current program reader/binding coverage mismatch")
    if writer["reader_context_bindings"] != program["reader_context_bindings"]:
        raise ValueError("current program reader binding differs from production program")
    context = writer["evaluation_context"]
    if context is None or context["status"] != "observed":
        raise ValueError("current program reader lacks exact context")
    scopes = {
        row["name"]: (row["name"], row["kind"], row["role"])
        for row in [context["actor_scope"], *context["targets"], *context["auxiliary_scopes"]]
    }
    result = {}
    for key, reader in readers.items():
        # The existing program owns this binding: e.g. ROOT.exists(scope:article)
        # observes an auxiliary article even though the getter evaluates on ROOT.
        if bindings[key] != scopes.get(bindings[key][0]):
            raise ValueError("current program reader scope/role drift")
        identity = f"program:{writer['source']}#{writer['writer_id']}:{key}"
        result[key] = {
            "id": identity,
            "identity": identity,
            "raw_key": key,
            "writer_id": writer["writer_id"],
            "source": writer["source"],
            "scope": reader["scope"],
            "unit": reader["unit"],
            "kind": reader["kind"],
            "reader_contracts": [{"source": writer["source"], "reader": reader}],
            "evaluation_context": context,
            "reader_context_binding": list(bindings[key]),
        }
    return result


def migration_writers(
    ir: Any, physical: dict[str, Any], structures: dict[str, Any]
) -> dict[str, Any]:
    physical_fields: dict[tuple[str, str], list[str]] = defaultdict(list)
    parents: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for identity, row in physical.items():
        physical_fields[(row["source"], f"{row['definition']}.{row['field']}")].append(identity)
    for identity, row in structures.items():
        parents[row["source"]].append((row["definition"], identity))
    result = {}
    for typed, writer in zip(ir.writers, ir.as_dict()["writers"], strict=True):
        fact_ids = {binding[0] for binding in typed.reader_context_bindings}
        if typed.legacy is not None:
            if (typed.actor, typed.target) != (typed.legacy.actor, typed.legacy.target):
                raise ValueError("current legacy writer actor/target drift")
            # Use the production Rule input contract, including RHS FactReference
            # and unknown-cost entity anchors. A missing EvaluationContext does
            # not erase these inputs or create a new context/getter permission.
            fact_ids.update(typed.legacy.to_action_ir().to_rule().input_keys())
            fact_ids.update(typed.legacy.auxiliary_facts)
            fact_ids.update(typed.legacy.conservative_unknown_facts)
        local = program_reader_facts(writer)
        keys = {key: local[key]["id"] if key in local else key for key in fact_ids}
        source, field = writer["source"], writer["field"]
        if source.startswith("mod/decisions/"):
            source = "common/ai_strategies/00_default_strategy.txt"
            field = f"ai_strategy_default.{field}"
        direct = physical_fields.get((source, field), [])
        owners = [
            identity
            for definition, identity in parents[source]
            if field.startswith(definition + ".")
        ]
        if not owners:
            raise ValueError(f"current writer lacks actual native parent: {writer['writer_id']}")
        result[writer["writer_id"]] = {
            **{
                key: writer[key]
                for key in (
                    "kind",
                    "source",
                    "definition",
                    "consumer_id",
                    "field",
                    "actor",
                    "target",
                    "operation",
                    "owner",
                    "vanilla_tail",
                    "evaluation_context",
                    "reader_context_bindings",
                    "chain_refs",
                )
            },
            "semantic_ir_sha256": discovery.digest(writer),
            **(
                {"port_contributions": writer["port_contributions"]}
                if writer.get("port_contributions")
                else {}
            ),
            "semantics": {
                key: value
                for key, value in writer.items()
                if key
                in {
                    "legacy_action",
                    "predicates",
                    "action_card",
                    "supply_program",
                    "event_program",
                    "acceptance_program",
                    "regional_resource_program",
                }
            },
            "fact_ids": sorted(keys.values()),
            "fact_key_bindings": keys,
            "cause_ids": [writer["legacy_action"]["contribution_group"]]
            if writer.get("legacy_action") and writer["legacy_action"].get("contribution_group")
            else [],
            "native_source": source,
            "native_field": field,
            "native_physical_ids": sorted(direct),
            "native_parent_ids": sorted(owners),
            "mapping": "exact_physical_field"
            if direct
            else "explicit_new_field_or_child_on_exact_native_parent",
            "generated_path": f"mod/{source}",
            "migration_status": "pending_objective_and_witness_acceptance",
        }
    # The canonical production IR contains tuples inside a few program payloads.
    # Normalize at the JSON boundary so a read-back projection has the same types.
    return cast("dict[str, Any]", discovery.strict_json(discovery.encoded(result)))


def current_files(sources: Any, package_path: str) -> dict[str, Any]:
    """Bind a normal current package; fixed historical equality grants no authority."""
    from pdx import distribution  # noqa: PLC0415
    from pdx.parser import parse_text  # noqa: PLC0415
    from tools.ci.a4_scope import safe_path  # noqa: PLC0415

    package = safe_path(sources.root, package_path)
    # This is the ordinary complete production/package validator, including
    # original-input preflight, release paths, language/BOM and generation.
    distribution.validate_package(package)
    lock = sources.json("mod/generation-lock.json")
    for path, digest in lock["sources"].items():
        if sources.hash(path) != digest:
            raise ValueError(f"current candidate generation source drift: {path}")
    historical = discovery.strict_json(discovery.unpack(sources.read(TASK6_LOCK), 42856))
    baseline = discovery.unpack(sources.read(TASK6_PACKAGE), 1392674)
    if discovery.sha(baseline) != TASK6_PACKAGE_SHA256:
        raise ValueError("immutable Task6 package drift")
    result = {}
    with zipfile.ZipFile(package) as archive, zipfile.ZipFile(io.BytesIO(baseline)) as old:
        for path, digest in lock["files"].items():
            generated = sources.read(f"mod/{path}")
            delivered = archive.read(path)
            if discovery.sha(generated) != digest:
                raise ValueError(f"current generated byte drift: {path}")
            expected = b"\xef\xbb\xbf" + generated if path.endswith((".txt", ".yml")) else generated
            if delivered != expected:
                raise ValueError(f"current package/generated mismatch: {path}")
            parsed = parse_text(generated.decode()) if path.endswith(".txt") else None
            if parsed is not None and parsed.errors:
                raise ValueError(f"current generated AST parse failure: {path}")
            result[path] = {
                "generated_sha256": digest,
                "package_sha256": discovery.sha(delivered),
                "task6_generated_sha256": historical["files"].get(path),
                "task6_package_sha256": discovery.sha(old.read(path))
                if path in old.namelist()
                else None,
                "bytes": len(generated),
                "ast_sha256": discovery.digest(dataclasses.asdict(parsed.root)) if parsed else None,
            }
    return result


def historical_checkpoint(sources: Any, commit: str) -> tuple[Any, dict[str, Any]]:
    """Read immutable Task8 objects from its actual accepted Git tree.

    Historical test source bindings remain attached to historical bytes. They
    are never replayed against changed current source or treated as new passes.
    """
    from tools.ci import a4_history  # noqa: PLC0415
    from tools.ci.a4_schema import RECEIPT, check_shape  # noqa: PLC0415
    from tools.ci.a4_scope import Sources, git, junit_results  # noqa: PLC0415

    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("current candidate requires exact accepted Task8 commit")
    git(sources.root, "merge-base", "--is-ancestor", commit, "HEAD")
    root = discovery.strict_json(git(sources.root, "show", f"{commit}:{ROOT_PATH}"))
    receipt = discovery.strict_json(git(sources.root, "show", f"{commit}:{MIGRATION_RECEIPT}"))
    check_shape(receipt, RECEIPT)
    refs = [*root["inputs"], *root["artifacts"].values(), *receipt["bindings"], receipt["junit"]]
    paths = {ROOT_PATH, REPORT_PATH, MIGRATION_RECEIPT, *(ref["path"] for ref in refs)}
    raw = a4_history.tree(git, sources.root, commit, tuple(sorted(paths)))
    frozen = Sources(sources.root, raw)
    if frozen.hash("mod/generation-lock.json") != CURRENT_LOCK_SHA256:
        raise ValueError("historical checkpoint is not the accepted Task8 migration lock")
    for reference in refs:
        if reference["path"] not in raw:
            raise ValueError("historical checkpoint input missing from accepted commit")
        frozen.verify(reference)
    # Accepted checkpoint/report/JUnit/package files themselves remain exact;
    # evolving production and test sources are read only from the frozen tree.
    immutable = {
        ROOT_PATH,
        REPORT_PATH,
        MIGRATION_RECEIPT,
        receipt["junit"]["path"],
        PACKAGE,
        TASK6_PACKAGE,
        TASK6_LOCK,
        *(ref["path"] for ref in root["artifacts"].values()),
        *(ref["path"] for ref in root["inputs"] if ref["path"].startswith(f"{DIRECTORY}/")),
    }
    for path in immutable:
        if sources.read(path) != raw[path]:
            raise ValueError(f"immutable Task8 historical evidence changed: {path}")
    values = {name: frozen.json(ref["path"]) for name, ref in root["artifacts"].items()}
    if values["migration_files"] != migration_files(frozen):
        raise ValueError("historical Task6/8 exact payload comparison changed")
    contracts = frozen.json(MIGRATION_PATH)["objectives"]
    expected = sorted(
        {node for contract in contracts.values() for node in contract["witness_nodes"]}
    )
    passed, failed = junit_results(sources.root / receipt["junit"]["path"])
    if (
        receipt["exit_code"]
        or receipt["failed"]
        or failed
        or sorted(receipt["selection"]) != expected
        or sorted(receipt["passed"]) != expected
        or sorted(passed) != expected
    ):
        raise ValueError("historical Task8 original witness evidence failed or incomplete")
    return frozen, values


def current_differences(
    before: dict[str, Any],
    after: dict[str, Any],
    declared: list[dict[str, Any]],
) -> list[str]:
    """Protect every writer identity and unrelated semantics in the first slice."""
    old, now = before["migration_writers"], after["migration_writers"]
    if set(old) != set(now):
        raise ValueError("current candidate dropped or introduced unreviewed writer IDs")
    declarations = {item["writer_id"]: item for item in declared}
    if len(declarations) != len(declared):
        raise ValueError("duplicate current change declaration")
    changed = []
    for identity, writer in now.items():
        previous = old[identity]
        protected = {
            "kind",
            "source",
            "definition",
            "consumer_id",
            "field",
            "actor",
            "target",
            "operation",
            "owner",
            "vanilla_tail",
            "evaluation_context",
            "chain_refs",
            "native_source",
            "native_field",
            "native_physical_ids",
            "native_parent_ids",
            "generated_path",
            "mapping",
            "product_bindings",
        }
        if any(previous.get(key) != writer.get(key) for key in protected):
            raise ValueError(
                f"current candidate writer/object/role/native authority drift: {identity}"
            )
        left = discovery.strict_json(discovery.encoded(previous["semantics"]))
        right = discovery.strict_json(discovery.encoded(writer["semantics"]))
        construction = (
            writer["source"] == "mod/decisions/information.toml"
            and writer["definition"] in CONSTRUCTION_CHANGES
        )
        removed_strategy = (
            construction and writer["definition"] == "remaining_industrial_construction_need"
        )
        prior_context = previous.get("reader_context_bindings")
        if removed_strategy and prior_context is not None:
            prior_context = [
                binding for binding in prior_context if binding[0] != "industrial_route"
            ]
        if prior_context != writer.get("reader_context_bindings"):
            raise ValueError(f"current candidate reader scope/role binding drift: {identity}")
        for key in ("fact_ids", "fact_key_bindings"):
            previous_facts, current_facts = previous.get(key), writer.get(key)
            if removed_strategy and previous_facts is not None:
                previous_facts = (
                    {
                        name: fact
                        for name, fact in previous_facts.items()
                        if name != "industrial_route"
                    }
                    if isinstance(previous_facts, dict)
                    else [fact for fact in previous_facts if fact != "industrial_route"]
                )
            if previous_facts != current_facts:
                raise ValueError(f"current candidate fact/object binding drift: {identity}")
        if construction:
            for semantics in (left, right):
                semantics.pop("predicates", None)
                for key in ("predicates", "contribution_group", "why", "counterexample"):
                    semantics["legacy_action"].pop(key, None)
        if left != right or (not construction and previous["cause_ids"] != writer["cause_ids"]):
            raise ValueError(f"current candidate unrelated semantic drift: {identity}")
        if previous["semantic_ir_sha256"] != writer["semantic_ir_sha256"]:
            changed.append(identity)
            item = declarations.get(identity)
            if (
                item is None
                or set(item) != {"writer_id", "before", "after", "reason", "witness_nodes"}
                or item["before"] != previous["semantic_ir_sha256"]
                or item["after"] != writer["semantic_ir_sha256"]
                or not item["reason"].strip()
                or not item["witness_nodes"]
            ):
                raise ValueError(
                    f"current candidate change lacks exact identity and independent witnesses: {identity}"
                )
    if set(declarations) != set(changed):
        raise ValueError("current candidate change declaration coverage drift")
    if set(before["migration_files"]) != set(after["migration_files"]):
        raise ValueError("current candidate generated path coverage drift")
    return changed


def protect_current_native(sources: Any, frozen: Any, values: dict[str, Any]) -> None:
    from pdx.parser import parse_text  # noqa: PLC0415
    from pdx.situated.native_treatments import _digest  # noqa: PLC0415

    target = "common/ai_strategies/00_default_strategy.txt"
    marker = re.compile(
        r"(?ms)^\s*# SITAI BEGIN information:wanted_construction_output\n.*?"
        r"^\s*# SITAI END information:wanted_construction_output\n"
    )
    for path in values["migration_files"]:
        before, after = frozen.read(f"mod/{path}"), sources.read(f"mod/{path}")
        if path != target:
            if before != after:
                raise ValueError(f"current candidate changed unrelated generated file: {path}")
            continue
        native = []
        for raw in (before, after):
            stripped, count = marker.subn("\n", raw.decode())
            parsed = parse_text(stripped)
            if count != 1 or parsed.errors:
                raise ValueError("construction overlay missing/duplicated or native AST damaged")
            native.append(_digest(parsed.root))
        if native[0] != native[1]:
            raise ValueError(
                "current candidate damaged original tail/parent/sibling or unrelated field"
            )


def current_evidence_ports(model: Any, target: str) -> dict[str, Any]:
    """Project the actual production graph and generated slice through its JSON contract."""
    if model.port_graph is None:
        raise ValueError("current evidence-port projection lacks the production graph")
    graph = model.port_graph
    start = target.index("# SITAI BEGIN information:wanted_construction_output")
    end = target.index("# SITAI END information:wanted_construction_output", start)
    overlay = "\n".join(target[start:end].splitlines()[1:])
    from pdx.model import Assignment, Block, Scalar  # noqa: PLC0415
    from pdx.parser import parse_text  # noqa: PLC0415

    parsed = parse_text(overlay)
    if parsed.errors:
        raise ValueError("current construction overlay cannot parse")
    stack: list[tuple[Assignment | Block | Scalar, int]] = [(parsed.root, 0)]
    nodes = branches = max_depth = 0
    while stack:
        node, depth = stack.pop()
        nodes += 1
        max_depth = max(max_depth, depth)
        if isinstance(node, Block):
            stack.extend((child, depth + 1) for child in node.items)
        elif isinstance(node, Assignment):
            branches += node.key in {"if", "else_if", "else"}
            if node.value is not None:
                stack.append((node.value, depth + 1))
    result = {
        "graph": graph.contract(),
        "contributions": {
            writer.writer_id: [dataclasses.asdict(item) for item in writer.port_contributions]
            for writer in model.consumer_ir.writers
            if writer.port_contributions
        },
        "slice": {
            "actor": "root",
            "target": "none",
            "field": "wanted_construction_output",
            "source": "mod/decisions/information.toml",
            "unit": "multiplier_delta",
        },
        "static_budget": {
            "ports": len(graph.ports),
            "uses": len(graph.uses),
            "max_expanded_leaves": max(dict(graph.expansions).values()),
            "max_evaluation_cost": max(dict(graph.costs).values()),
            "construction_nodes": nodes,
            "construction_depth": max_depth,
            "construction_branches": branches,
            "construction_bytes": len(overlay.encode()),
            "object_iterations": 0,
            "world_scans": 0,
            "mod_persistent_writes": 0,
        },
        "scope": "actual static production graph/IR/generated AST; no game performance claim",
    }
    return cast("dict[str, Any]", discovery.strict_json(discovery.encoded(result)))


def artifacts(
    sources: Any, *, current_package: str | None = None, successor: bool = False
) -> dict[str, Any]:
    from pdx import building_defaults  # noqa: PLC0415
    from pdx.situated.compiler import load_model  # noqa: PLC0415
    from tools.ci.a4_scope import original_a3, plan_goals  # noqa: PLC0415

    raw = discovery.load_capture(sources)
    catalog = sources.json(discovery.CATALOG_PATH)
    _, old = original_a3(sources)
    result = classify(raw, catalog, native_contracts(sources))
    result["semantic_resolutions"] = repeated_resolutions(sources, result["physical"])
    result["shared_native_atoms"] = shared_atoms(sources, result["physical"])
    model = load_model()
    if model.consumer_ir is None:
        raise ValueError("current production has no consumer IR")
    result["migration_writers"] = migration_writers(
        model.consumer_ir, result["physical"], result["structures"]
    )
    result["migration_files"] = (
        migration_files(sources)
        if current_package is None
        else current_files(sources, current_package)
    )
    defaults = discovery.strict_json(building_defaults.snapshot())
    selector = sources.json(building_defaults.SELECTOR_ID)
    result["current_native_boundaries"] = {
        "existing_building_initializers": {
            "defaults": sources.reference(building_defaults.MANIFEST_ID),
            "selector": sources.reference(building_defaults.SELECTOR_ID),
            "initializer_ids": [row["id"] for row in defaults["initializers"]],
            "reviewed_candidate_sha256": selector["lineage"]["reviewed_candidate_sha256"],
            "effective_member": selector["contract"]["effective_expression_member"],
            "raw_spans": len(selector["observations"]),
            "copper_initializer_permission": False,
            "dynamic_local_writer_permission": False,
            "scope": "Exact eleven existing normal named static initializers only; source/type/parent/lifecycle validated through the production building_defaults path",
        }
    }
    if successor:
        if sources.read(building_defaults.MANIFEST_ID) != building_defaults.snapshot():
            raise ValueError("current initializer proof differs from normal production snapshot")
        if selector != building_defaults._selector_data():
            raise ValueError("current initializer selector differs from normal production proof")
        # snapshot() above independently revalidates the pinned native default
        # and selector proof; an intake initializer claim cannot replace it.
        result["current_native_boundaries"] = {
            "existing_building_initializers": {
                "defaults": sources.reference(building_defaults.MANIFEST_ID),
                "selector": sources.reference(building_defaults.SELECTOR_ID),
                "initializer_ids": [row["id"] for row in defaults["initializers"]],
                "reviewed_candidate_sha256": selector["lineage"]["reviewed_candidate_sha256"],
                "effective_member": selector["contract"]["effective_expression_member"],
                "raw_spans": len(selector["observations"]),
                "dynamic_local_writer_permission": False,
                "scope": "exact normal production snapshot; static named absent-field initializers only",
            }
        }
    getter_contracts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source, key, signature in model.observation_contracts:
        getter_contracts[key].append({"source": source, "signature": signature})
    result["facts"] = {
        fact.id: {**dataclasses.asdict(fact), "reader_contracts": getter_contracts[fact.id]}
        for fact in model.facts
    }
    for writer in model.consumer_ir.as_dict()["writers"]:
        for fact in program_reader_facts(writer).values():
            if fact["id"] in result["facts"]:
                raise ValueError("duplicate current program-local fact identity")
            result["facts"][fact["id"]] = fact
    actual_getters = {(source, key) for source, key, _ in model.observation_contracts}
    for writer in model.consumer_ir.writers:
        if writer.legacy is not None and any(
            (writer.source, key) not in actual_getters
            for key in result["migration_writers"][writer.writer_id]["fact_key_bindings"]
        ):
            raise ValueError("current legacy input lacks exact source getter")
    result["facts"] = discovery.strict_json(discovery.encoded(result["facts"]))
    if any(
        key not in result["facts"]
        for writer in result["migration_writers"].values()
        for key in writer["fact_ids"]
    ):
        raise ValueError("current writer input lacks an actual production fact")
    maps = product_maps(
        result["physical"],
        sources.json(TARGET_PATH),
        old,
        result["structures"],
        sources.json(MIGRATION_PATH)["objectives"],
    )
    bind_product_writers(
        result["physical"], result["structures"], result["migration_writers"], maps
    )
    goals = {goal for goal in plan_goals(sources) if goal[0] in "GBRU"}
    verify_product_maps(maps, result["physical"], goals, {item["id"] for item in old})
    result["responsibilities"] = responsibilities(
        result["physical"], result["migration_writers"], maps
    )
    if current_package is not None:
        result["evidence_ports"] = current_evidence_ports(
            model, sources.read("mod/common/ai_strategies/00_default_strategy.txt").decode()
        )
    return {**result, **maps}


def writer_product_edges(
    physical: dict[str, Any],
    structures: dict[str, Any],
    writers: dict[str, Any],
    maps: dict[str, Any],
) -> dict[str, dict[str, str]]:
    """Bind actual child writers to explicit native structures, never invent surfaces."""
    result: dict[str, dict[str, str]] = {identity: {} for identity in writers}
    physical_fields: dict[tuple[str, str], set[str]] = defaultdict(set)
    parents_by_source: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key, row in physical.items():
        physical_fields[(row["source"], f"{row['definition']}.{row['field']}")].add(key)
    for key, row in structures.items():
        parents_by_source[row["source"]].append((key, row["definition"]))
    targets = [
        (
            name,
            goal,
            target,
            set(target["physical_ids"]),
            set(target["structural_ids"]),
        )
        for name in ("targets", "predecessors")
        for goal, target in maps[name].items()
    ]
    for identity, writer in writers.items():
        source, field = writer["native_source"], writer["native_field"]
        expected_source, expected_field = writer["source"], writer["field"]
        if expected_source.startswith("mod/decisions/"):
            expected_source = "common/ai_strategies/00_default_strategy.txt"
            expected_field = f"ai_strategy_default.{expected_field}"
        parents = set(writer["native_parent_ids"])
        expected_parents = {
            key
            for key, definition in parents_by_source[source]
            if field.startswith(definition + ".")
        }
        expected_physical = physical_fields[(source, field)]
        if (
            not parents
            or (source, field) != (expected_source, expected_field)
            or parents != expected_parents
            or set(writer["native_physical_ids"]) != expected_physical
        ):
            raise ValueError(f"current writer native source/parent/child field drift: {identity}")
        for name, goal, target, members, parent_members in targets:
            if expected_physical.intersection(members):
                basis = "exact_physical_field"
            elif name == "targets" and goal.startswith(("G", "U")):
                basis = "all_current_writers"
            elif (
                not expected_physical
                and not target.get("migration_contract")
                and parents.intersection(parent_members)
            ):
                basis = "exact_native_parent_child_field"
            else:
                continue
            result[identity][goal if name == "targets" else f"predecessor:{goal}"] = basis
    return result


def bind_product_writers(
    physical: dict[str, Any],
    structures: dict[str, Any],
    writers: dict[str, Any],
    maps: dict[str, Any],
) -> None:
    edges = writer_product_edges(physical, structures, writers, maps)
    for identity, writer in writers.items():
        writer["product_bindings"] = {
            "status": "pending",
            "writer_authority": False,
            "goal_edges": edges[identity],
        }
    for name in ("targets", "predecessors"):
        for goal, target in maps[name].items():
            key = goal if name == "targets" else f"predecessor:{goal}"
            target["current_writer_ids"] = sorted(
                identity for identity, linked in edges.items() if key in linked
            )
    verify_writer_product_closure(physical, structures, writers, maps)


def verify_writer_product_closure(
    physical: dict[str, Any],
    structures: dict[str, Any],
    writers: dict[str, Any],
    maps: dict[str, Any],
) -> None:
    expected = writer_product_edges(physical, structures, writers, maps)
    all_writers = set(writers)
    for name in ("targets", "predecessors"):
        for goal, target in maps[name].items():
            key = goal if name == "targets" else f"predecessor:{goal}"
            if target["current_writer_ids"] != sorted(
                identity for identity, linked in expected.items() if key in linked
            ):
                raise ValueError(f"current writer product responsibility closure drift: {key}")
            if (
                name == "targets"
                and goal.startswith(("G", "U"))
                and set(target["current_writer_ids"]) != all_writers
            ):
                raise ValueError(f"global current writer responsibility omission: {goal}")
    for identity, writer in writers.items():
        if writer["product_bindings"] != {
            "status": "pending",
            "writer_authority": False,
            "goal_edges": expected[identity],
        }:
            raise ValueError(f"current writer product edge/status/authority drift: {identity}")
        if not writer["native_physical_ids"] and not any(
            goal.startswith("B") for goal in expected[identity]
        ):
            raise ValueError(f"parent-only writer lacks concrete B responsibility: {identity}")


def responsibilities(
    physical: dict[str, Any], writers: dict[str, Any], maps: dict[str, Any]
) -> dict[str, Any]:
    """Do not collapse differing source/field/role/qualification responsibilities."""
    by_physical: dict[str, list[str]] = defaultdict(list)
    for identity, writer in writers.items():
        for member in writer["native_physical_ids"]:
            by_physical[member].append(identity)
    target_members: dict[str, list[str]] = defaultdict(list)
    for goal, target in maps["targets"].items():
        for member in target["physical_ids"]:
            target_members[member].append(goal)
    result = {}
    for identity, row in physical.items():
        actual = [writers[writer] for writer in by_physical[identity]]
        result[identity] = {
            "canonical_id": row["canonical_id"],
            "owner_id": row["owner_id"],
            "source_sha256": row["source_sha256"],
            "field": row["field"],
            "writer_ids": sorted(by_physical[identity]),
            "goal_ids": sorted(target_members[identity]),
            "role_bindings": sorted(
                {
                    discovery.encoded(
                        {
                            "actor": w["actor"],
                            "target": w["target"],
                            "context": w["evaluation_context"],
                        }
                    ).decode()
                    for w in actual
                }
            ),
            "fact_ids": sorted({fact for w in actual for fact in w["fact_ids"]}),
            "cause_ids": sorted({cause for w in actual for cause in w["cause_ids"]}),
            "qualification": "exact complete native parent retained; producer witness required"
            if actual
            else "pending exact owner qualification and caller role",
            "reference_closure": "pending objective-specific closure; captured lexical references remain available on parent",
            "product_status": "pending",
            "unit": "see exact native contract and typed facts"
            if row["contract"]
            else "pending exact consumer unit",
            "U_obligations": "U01-U10 apply independently to this exact physical consumer and each actual actor/target role; cases remain pending",
            "owner": "A4 product owner"
            if actual
            else "native interface owner then A4 product owner",
            "next_question": row["question"],
        }
    return result


def migration_bindings(
    sources: Any, *, package_path: str = PACKAGE, extra_nodes: tuple[str, ...] = ()
) -> list[dict[str, str]]:
    """Bind the real production closure and independent witness sources, without a report cycle."""
    from tools.ci.a4_scope import GATE_INPUTS  # noqa: PLC0415

    lock = sources.json("mod/generation-lock.json")
    paths = {
        MIGRATION_PATH,
        package_path,
        TASK6_PACKAGE,
        TASK6_LOCK,
        "mod/generation-lock.json",
        *INPUTS,
        *GATE_INPUTS,
        *lock["sources"],
        *(f"mod/{path}" for path in lock["files"]),
    }
    paths.update(
        path.relative_to(sources.root).as_posix()
        for path in (sources.root / "research/vanilla-ai/1.15.0").glob("*.json")
    )
    # Test helpers are executable inputs as well. Bind their complete files,
    # rather than pretending a single function's text covers imported helpers.
    paths.update(
        path.relative_to(sources.root).as_posix() for path in (sources.root / "tests").glob("*.py")
    )
    if package_path != PACKAGE and sources.json(CURRENT_INTAKE)["schema"] == 2:
        from tools.ci import a4_successor  # noqa: PLC0415

        intake = sources.json(CURRENT_INTAKE)
        transition = a4_successor.contract(sources, intake)
        paths.update({CURRENT_INTAKE, "tools/ci/a4_successor.py", intake["successor"]["path"]})
        paths.update(ref["path"] for ref in a4_successor.references(transition)[1:])
    refs = [sources.reference(path) for path in sorted(paths)]
    for contract in sources.json(MIGRATION_PATH)["objectives"].values():
        for node in contract["witness_nodes"]:
            path, function = node.split("::", 1)
            refs.append(sources.reference(path, function.split("[", 1)[0], "python"))
    for node in extra_nodes:
        path, function = node.split("::", 1)
        refs.append(sources.reference(path, function.split("[", 1)[0], "python"))
    return list({discovery.encoded(ref): ref for ref in refs}.values())


def migration_acceptance(
    sources: Any,
    values: dict[str, Any],
    *,
    replay: bool,
    receipt_path: str | None = MIGRATION_RECEIPT,
    package_path: str = PACKAGE,
    extra_nodes: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Accept current migration chains only after real JUnit and independent witnesses.

    This receipt does not close new product directions or unknown DLC/engine
    applicability. Those remain visible on the ordinary objective rows.
    """
    from tools.ci.a4_scope import (  # noqa: PLC0415
        junit_results,
        verify_receipt,
        witness_command_refs,
    )

    contracts = sources.json(MIGRATION_PATH)["objectives"]
    nodes = sorted(
        {
            *extra_nodes,
            *(node for contract in contracts.values() for node in contract["witness_nodes"]),
        }
    )
    if receipt_path is None:
        if replay:
            raise ValueError("pending migration cannot claim replayed acceptance")
        return {
            identity: {
                "old_id": identity,
                "migration_status": "pending_current_witnesses",
                "writer_ids": values["predecessors"][identity]["current_writer_ids"],
                "witness_nodes": sorted({*contract["witness_nodes"], *extra_nodes}),
                "receipt": None,
            }
            for identity, contract in contracts.items()
        }
    receipt = sources.json(receipt_path)
    if (
        receipt["exit_code"]
        or receipt["failed"]
        or sorted(receipt["selection"]) != nodes
        or sorted(receipt["passed"]) != nodes
    ):
        raise ValueError("migration witness selection failed or incomplete")
    sources.verify(receipt["junit"])
    passed, failed = junit_results(sources.root / receipt["junit"]["path"])
    if failed or sorted(passed) != nodes:
        raise ValueError("migration JUnit failed or incomplete")
    needed = [
        *migration_bindings(sources, package_path=package_path, extra_nodes=extra_nodes),
        *witness_command_refs(sources, receipt),
    ]
    if {discovery.encoded(ref) for ref in needed} != {
        discovery.encoded(ref) for ref in receipt["bindings"]
    }:
        raise ValueError("migration complete production/witness bindings drift")
    for reference in needed:
        sources.verify(reference)
    if replay:
        verify_receipt(
            sources,
            {
                "id": receipt["id"],
                "path": receipt_path,
                "sha256": sources.hash(receipt_path),
            },
            needed,
            nodes,
        )
    implemented = {
        identity: row
        for identity, row in values["predecessors"].items()
        if row["old_status"] == "implemented"
    }
    if set(implemented) != set(contracts) or len(implemented) != 17:
        raise ValueError("original implemented migration denominator")
    result = {}
    for identity, row in implemented.items():
        selected = {
            writer: values["migration_writers"][writer] for writer in row["current_writer_ids"]
        }
        if not selected or any(
            writer["actor"] != contracts[identity]["actor"]
            or writer["target"] != contracts[identity]["target"]
            for writer in selected.values()
        ):
            raise ValueError(f"migration wrong owner/role/current writer: {identity}")
        result[identity] = {
            "old_id": identity,
            "old_object_sha256": row["original_object_sha256"],
            "decision": "migrate",
            "migration_status": "verified_current_source_ir_ast_package",
            "objective": row["title"],
            "physical_ids": row["physical_ids"],
            "canonical_ids": sorted(
                {values["physical"][member]["canonical_id"] for member in row["physical_ids"]}
            ),
            "writer_ids": sorted(selected),
            "writer_semantic_sha256": discovery.digest(selected),
            "native_parent_ids": sorted(
                {parent for writer in selected.values() for parent in writer["native_parent_ids"]}
            ),
            "generated_files": {
                path: values["migration_files"][path.removeprefix("mod/")]
                for path in sorted({writer["generated_path"] for writer in selected.values()})
            },
            "fact_ids": sorted(
                {fact for writer in selected.values() for fact in writer["fact_ids"]}
            ),
            "cause_ids": sorted(
                {cause for writer in selected.values() for cause in writer["cause_ids"]}
            ),
            "receipt": sources.reference(receipt_path),
            "witness_nodes": (
                sorted({*contracts[identity]["witness_nodes"], *extra_nodes})
                if extra_nodes
                else contracts[identity]["witness_nodes"]
            ),
            "scope": "static migration acceptance; no game execution or new G/B/R/U product completion; configuration applicability remains separately pending",
        }
    return result


def stage_assignments(
    sources: Any,
    values: dict[str, Any],
    *,
    directory: str = DIRECTORY,
    artifact_paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    from tools.ci import a4_scope as gate  # noqa: PLC0415

    _, originals = gate.original_a3(sources)
    old = {row["id"]: row for row in originals}
    discoveries = gate.discover(sources, originals, gate.changes(sources.root))
    discoveries.extend(
        classification_discoveries(
            sources, values, directory=directory, artifact_paths=artifact_paths
        )
    )
    result = {}
    for item in discoveries:
        stage, duty = gate.responsibility_stage(item, old)
        result[f"O:{item['id']}"] = {
            "before": (
                "A4-1"
                if item["origin"] != "goal"
                else "A4-3"
                if item["identity"].startswith("B")
                else "A4-4"
                if item["identity"].startswith("R")
                else "A4-5"
                if item["identity"].startswith("U")
                else "A4-6"
                if item["identity"] in {"G08", "C8"}
                else "A4-2"
            ),
            "after": stage,
            "responsibility": duty,
            "discovery_ids": [item["id"]],
            "source": item["source"],
            "old_status": old[item["identity"]]["status"] if item["origin"] == "a3" else None,
        }
    catalog = sources.json(discovery.CATALOG_PATH)
    for domain, members in catalog["groups"].items():
        result[f"O:{domain}"] = {
            "before": "A4-1",
            "after": "A4-1",
            "responsibility": "index",
            "discovery_ids": members,
            "source": sources.reference(
                discovery.CATALOG_PATH, f"groups/{pointer(domain)}", "json"
            ),
            "old_status": None,
        }
    return result


def index_checkpoint(
    values: dict[str, Any], accepted: dict[str, Any], *, successor: bool = False
) -> dict[str, Any]:
    """Compute the enabling contract independently of any product-row status."""
    if (
        len(values["observations"]) != 56196
        or len(values["physical"]) != 14924
        or len(values["structures"]) != 22465
        or len(values["unexpanded_observations"]) != 71
        or len(values["semantic_resolutions"]) != 34
        or len(accepted) != 17
        or len(values["predecessors"]) != 96
        or len(values["targets"]) != 94
        or (not successor and len(values["migration_writers"]) != 6193)
        or (not successor and len(values["migration_files"]) != 117)
    ):
        raise ValueError("incomplete raw/classification/current writer/migration denominator")
    implemented = {
        identity
        for identity, row in values["predecessors"].items()
        if row["old_status"] == "implemented"
    }
    if implemented != set(accepted):
        raise ValueError("original implemented migration lineage mismatch")
    verify_writer_product_closure(
        values["physical"], values["structures"], values["migration_writers"], values
    )
    boundary = values.get("current_native_boundaries", {}).get("existing_building_initializers", {})
    if not successor and (
        len(boundary.get("initializer_ids", [])) != 11
        or boundary.get("raw_spans") != 46
        or boundary.get("reviewed_candidate_sha256")
        != "72848291b6183759d96160f9ea8192317be7297394809016ce4f027002c75176"
        or boundary.get("copper_initializer_permission") is not False
        or boundary.get("dynamic_local_writer_permission") is not False
    ):
        raise ValueError("current building initializer expression-source boundary is unresolved")
    if any(
        not row["question"]
        or not row["question_owner"]
        or not row["owner_id"]
        or row["syntax_kind"] == "unresolved_syntax"
        for row in values["physical"].values()
    ):
        raise ValueError("unclassified observation or missing physical question/owner")
    for observation in values["unexpanded_observations"]:
        row = values["physical"].get(observation["declaration_id"])
        if not row or any(
            row[key] != observation[key] for key in ("source", "definition", "field", "source_line")
        ):
            raise ValueError("unexpanded observation lost exact physical classification")
    if sum(bool(row["original_ambiguity"]) for row in values["physical"].values()) != 42:
        raise ValueError("original repeated/name ambiguity observation lost")
    for writer in values["migration_writers"].values():
        if (
            not writer["native_parent_ids"]
            or not writer["semantic_ir_sha256"]
            or writer["generated_path"].removeprefix("mod/") not in values["migration_files"]
        ):
            raise ValueError("unmapped current producer source/IR/AST/package")
    return {
        "status": "verified",
        "evidence": "static_check",
        "raw_observations_preserved": True,
        "unknown_future_interfaces": "pending with exact physical question and owner; no writer permission",
        "current_ir_writers": len(values["migration_writers"]),
        "old_implemented_migrations": 17,
        "product_completion": False,
    }


def shared_atoms(sources: Any, physical: dict[str, Any]) -> dict[str, Any]:
    event_dir = f"{DIRECTORY}/evidence/event"
    candidate = sources.json(f"{event_dir}/candidate.json")
    manifest = sources.json(f"{event_dir}/evidence-manifest.json")
    if (
        sources.hash(f"{event_dir}/candidate.json")
        != "95e5ee17183821c92bdc2bc485cfc35da37ba3b6345ddf604915e26eb2de24ea"
        or sources.hash(f"{event_dir}/evidence-manifest.json") != candidate["manifest_sha256"]
        or sources.hash(f"{event_dir}/anchor-slots.json") != manifest["anchor_sha256"]
        or sources.hash(f"{event_dir}/source-applicability.json")
        != manifest["applicability_sha256"]
    ):
        raise ValueError("reviewed shared event atom identity")
    indexed = {
        row["slot"]["slot_id"]: (identity, row) for identity, row in physical.items() if row["slot"]
    }
    bindings = {}
    for slot in sources.json(f"{event_dir}/anchor-slots.json")["slots"]:
        identity, row = indexed[slot["slot_id"]]
        if (
            row["owner_id"] != slot["owner_declaration_id"]
            or row["source"] != slot["source"]
            or row["definition"] != slot["definition"]
            or row["slot"]["option_index"] != slot["option_index"]
        ):
            raise ValueError("event shared atom applied to wrong physical slot")
        bindings[identity] = {
            "slot_id": slot["slot_id"],
            "event_type": row["slot"]["event_type"],
            "actor_scheduling": "unknown",
            "writer_permission": False,
        }
    for source in manifest["sources"]:
        if sources.json(discovery.ROOT_PATH)["source_hashes"][source["source"]] != source["sha256"]:
            raise ValueError("event source applicability after repin")
    innovation = sources.json(f"{DIRECTORY}/evidence/innovation/candidate.json")
    if (
        sources.hash(f"{DIRECTORY}/evidence/innovation/candidate.json")
        != "f7725e07fd318d1e1c54aa86543bf3f2a19b9cb829d3383d43abc4b200e27e66"
    ):
        raise ValueError("reviewed innovation numeric flag atom identity")
    definition = innovation["definition"]
    cap = [
        identity
        for identity, row in physical.items()
        if row["source"] == definition["source"]
        and row["definition"] == definition["owner"]
        and row["source_sha256"] == definition["complete_source_sha256"]
        and row["field"] == "game_data.ai_value"
    ]
    if len(bindings) != 41 or len(cap) != 1:
        raise ValueError("shared atom physical applicability denominator")
    return {
        "event": {
            "physical_bindings": bindings,
            "proven_atoms": candidate["proven_atoms"],
            "unknowns": candidate["unknowns"],
            "authorization": candidate["authorization"],
        },
        "innovation": {
            "physical_ids": cap,
            "exact_atom": innovation["exact_atom"],
            "production_writer": False,
            "B04_2_complete": False,
            "remaining": "Integrate exact innovation/max_innovation readers and raw-minus-cap with valid-country unknown policy; implement actual university/cost/saturation consumer and U witnesses",
        },
    }


def repeated_resolutions(sources: Any, physical: dict[str, Any]) -> dict[str, Any]:
    """Integrate the reviewed exact duplicate atom without erasing observations."""
    candidate = sources.json(REPEATED)
    if sources.hash(REPEATED) != "2602ec7f89c00753b4e461d9157203a6f9a9f53e1405d1b8e23b929ae3fcc99a":
        raise ValueError("reviewed repeated-field candidate identity")
    parent = str(Path(REPEATED).parent).replace("\\", "/")
    for member in candidate["inputs"]:
        if sources.hash(f"{parent}/{member['path']}") != member["sha256"]:
            raise ValueError("repeated-field evidence closure")
    result = {}
    for family in ("scripted_buttons", "diplomatic_catalysts"):
        proof = candidate[family]
        for owner in proof["owners"]:
            for field in owner["fields"]:
                identity = field["original_ambiguity"]["declaration_id"]
                observed = physical[identity]
                if (
                    observed["family"] != family
                    or observed["source"] != owner["source"]
                    or observed["definition"] != owner["owner"]
                    or observed["field"] != field["field"]
                    or observed["source_line"] != field["span"]["start_line"]
                    or observed["node_positions"]
                    != [[owner["owner_ast_assignment_index"], -1, field["ast_item_index"]]]
                    or observed["original_ambiguity"] != field["original_ambiguity"]["ambiguity"]
                ):
                    raise ValueError("repeated proof applied to wrong owner/field/occurrence")
                result[identity] = {
                    "class": proof["class"],
                    "field": field["field"],
                    "original_observation_preserved": True,
                    "semantic_resolution": proof["repetition"],
                    "root": proof["root"],
                    "chance": proof.get("unit", proof.get("chance")),
                    "candidate": sources.reference(REPEATED, family, "json"),
                    "source_span": field["span"],
                    "record_ordinal": field["ordinal"],
                    "product_status": "pending",
                    "writer_authority": False,
                    "remaining": "Exact objective/qualification/cost/player path and producer integration require separate acceptance",
                }
    if len(result) != 34:
        raise ValueError("repeated physical evidence denominator")
    return result


def manifest(sources: Any, values: dict[str, Any]) -> dict[str, Any]:
    paths = {
        *INPUTS,
        discovery.ROOT_PATH,
        discovery.CATALOG_PATH,
        *(record["path"] for record in native_contracts(sources).values()),
        "mod/generation-lock.json",
        PACKAGE,
        TASK6_PACKAGE,
        TASK6_LOCK,
        *sources.json("mod/generation-lock.json")["sources"],
        *(f"mod/{path}" for path in sources.json("mod/generation-lock.json")["files"]),
    }
    evidence_directory = sources.root / DIRECTORY / "evidence"
    paths.update(
        path.relative_to(sources.root).as_posix() for path in evidence_directory.rglob("*.json")
    )
    return {
        "schema": 1,
        "capture_sha256": discovery.CAPTURE_SHA256,
        "classification_status": "current_migration_verified_future_product_pending",
        "inputs": [sources.reference(path) for path in sorted(paths)],
        "artifacts": {
            **{name: sources.reference(f"{DIRECTORY}/{name}.json") for name in sorted(values)},
            "migration_acceptance": sources.reference(MIGRATION_ACCEPTANCE),
            "stage_assignments": sources.reference(STAGES_PATH),
        },
        "counts": {name: len(value) for name, value in values.items()},
        "authority": "none; native candidates and syntax do not grant producer permissions",
    }


def classification_discoveries(
    sources: Any,
    values: dict[str, Any],
    *,
    directory: str = DIRECTORY,
    artifact_paths: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for name in ("targets", "predecessors", "migration_acceptance"):
        for identity in values[name]:
            goals = [identity] if name == "targets" else ["G01", "G07"]
            if name == "predecessors":
                goals = sorted({*goals, values[name][identity]["current_target"]})
            rows.append(
                {
                    "id": f"D:classification:{name}:{identity}",
                    "kind": "discovery",
                    "origin": "classification_product_mapping",
                    "identity": f"{name}:{identity}",
                    "goal_ids": goals,
                    "source": sources.reference(
                        artifact_paths[name]
                        if artifact_paths is not None
                        else f"{directory}/migration-acceptance.json"
                        if name == "migration_acceptance"
                        else f"{directory}/{name}.json",
                        pointer(identity),
                        "json",
                    ),
                }
            )
    if directory == CURRENT_DIRECTORY:
        rows.append(
            {
                "id": "D:current-product:construction-evidence-ports",
                "kind": "discovery",
                "origin": "current_product_slice",
                "identity": "construction-evidence-ports",
                "goal_ids": [
                    "G03",
                    "G04",
                    "G05",
                    "G06",
                    "G07",
                    "C2",
                    "C3",
                    "C5",
                    "C6",
                    "C7",
                    "C9",
                    "C11",
                ],
                "source": sources.reference(CURRENT_INTAKE),
            }
        )
    return rows


def report_for(sources: Any, root: dict[str, Any]) -> dict[str, Any]:
    from tools.ci.a4_schema import INVESTIGATION, check_shape  # noqa: PLC0415

    values = {name: sources.json(ref["path"]) for name, ref in root["artifacts"].items()}
    rows = classification_discoveries(sources, values)
    capture = sources.json(discovery.ROOT_PATH)
    result = {
        "schema": 1,
        "source_version": "1.15.0",
        "source_inputs": [
            sources.reference(ROOT_PATH),
            *root["inputs"],
            *root["artifacts"].values(),
        ],
        "scanned_directories": capture["scanned_directories"],
        "parse_failures": capture["parse_failures"],
        "unrecognized": sorted({r["question"] for r in values["physical"].values()}),
        "duplicates": values["raw_duplicates"],
        "discoveries": rows,
        "dlc_ids": sources.json(discovery.CATALOG_PATH)["dlc_ids"],
        "writer_ids": [],
        "consumer_ids": [],
        "crosscheck_receipt_ids": [],
    }
    check_shape(result, INVESTIGATION)
    return result


def current_intake(sources: Any) -> dict[str, Any]:
    """A finite, source-bound declaration of intentional current differences."""
    from tools.ci.a4_schema import HASH, REFERENCE, TEXT, check_shape  # noqa: PLC0415

    value = sources.json(CURRENT_INTAKE)
    successor = value.get("schema") == 2
    basic = {key: item for key, item in value.items() if key != "successor"} if successor else value
    if successor and set(value) != {*basic, "successor"}:
        raise ValueError("successor intake fields drift")
    check_shape(
        basic,
        {
            "schema": {2} if successor else {1},
            "historical_commit": TEXT,
            "package": REFERENCE,
            "status": {"pending", "verified"},
            "receipt_path": TEXT,
            "witness_nodes": [TEXT],
            "crosscheck_nodes": [TEXT],
            "changes": [
                {
                    "writer_id": TEXT,
                    "before": HASH,
                    "after": HASH,
                    "reason": TEXT,
                    "witness_nodes": [TEXT],
                }
            ],
        },
    )
    if not re.fullmatch(r"[0-9a-f]{40}", value["historical_commit"]):
        raise ValueError("current intake lacks exact accepted historical commit")
    if value["package"]["kind"] != "file" or value["package"]["identity"] != "whole_file":
        raise ValueError("current package requires complete artifact identity")
    sources.verify(value["package"])
    nodes = value["witness_nodes"]
    if not nodes or len(set(nodes)) != len(nodes):
        raise ValueError("current candidate requires unique independent current witness nodes")
    for node in nodes:
        if not re.fullmatch(
            r"tests/test_[a-z0-9_]+\.py::test_[a-zA-Z0-9_]+(?:\[[^\r\n]+\])?", node
        ):
            raise ValueError("current witness must name a real independently selected test")
        path, function = node.split("::", 1)
        sources.verify(sources.reference(path, function.split("[", 1)[0], "python"))
    if any(set(item["witness_nodes"]) - set(nodes) for item in value["changes"]):
        raise ValueError("current change witness missing from exact current selection")
    if (
        not value["crosscheck_nodes"]
        or set(value["crosscheck_nodes"]) - set(nodes)
        or any("[" in node for node in value["crosscheck_nodes"])
    ):
        raise ValueError("current report needs independently replayed nonparametrized crosschecks")
    if value["status"] == "pending" and value["receipt_path"] != "pending":
        raise ValueError("pending current migration cannot carry a passed receipt")
    if value["status"] == "verified" and not value["receipt_path"].startswith(
        f"{CURRENT_DIRECTORY}/evidence/"
    ):
        raise ValueError(
            "current acceptance requires distinct current receipt; history cannot sign it"
        )
    if successor:
        from tools.ci import a4_successor  # noqa: PLC0415

        a4_successor.contract(sources, value)
    return cast("dict[str, Any]", value)


def current_artifacts(
    sources: Any, *, replay: bool
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    """Reconstruct the current view while preserving accepted historical bytes."""
    from tools.ci.a4_scope import Sources  # noqa: PLC0415

    intake = current_intake(sources)
    frozen, before = historical_checkpoint(sources, intake["historical_commit"])
    successor = intake["schema"] == 2
    base_paths = {name: f"{DIRECTORY}/{name}.json" for name in before}
    if successor:
        from tools.ci import a4_successor  # noqa: PLC0415

        transition = a4_successor.contract(sources, intake)
        frozen, before = a4_successor.base(sources, intake, transition)
        base_paths = {
            name: ref["path"] for name, ref in frozen.json(CURRENT_ROOT)["artifacts"].items()
        }
    values = artifacts(sources, current_package=intake["package"]["path"], successor=successor)
    if successor:
        changed, registry = a4_successor.admit(sources, before, values, transition, frozen=frozen)
        a4_successor.native_protection(sources, frozen, before, values, transition)
        values["successor_registry"] = registry
    else:
        changed = current_differences(before, values, intake["changes"])
        protect_current_native(sources, frozen, values)
    # No permission, native inventory, predecessor mapping or DLC classification
    # can change as a side effect of this construction-only current refresh.
    evolving = {
        "facts",
        "migration_writers",
        "migration_files",
        "responsibilities",
        "evidence_ports",
    }
    for name, value in values.items():
        if not successor and name not in evolving and value != before[name]:
            raise ValueError(
                f"current candidate changed native scope/role/DLC/product mapping: {name}"
            )
    accepted = migration_acceptance(
        sources,
        values,
        replay=replay and intake["status"] == "verified",
        receipt_path=intake["receipt_path"] if intake["status"] == "verified" else None,
        package_path=intake["package"]["path"],
        extra_nodes=tuple(intake["witness_nodes"]),
    )
    # All discovery IDs remain present while current acceptance is pending.
    paths = {
        name: (
            base_paths[name]
            if name in base_paths and value == before.get(name)
            else f"{CURRENT_DIRECTORY}/{name}.json"
        )
        for name, value in values.items()
    }
    paths["migration_acceptance"] = f"{CURRENT_DIRECTORY}/migration-acceptance.json"
    values["migration_acceptance"] = accepted
    projected = Sources(
        sources.root,
        {
            **sources.bytes,
            **{paths[name]: discovery.encoded(value) + b"\n" for name, value in values.items()},
        },
    )
    stages = stage_assignments(projected, values, directory=CURRENT_DIRECTORY, artifact_paths=paths)
    paths["stage_assignments"] = f"{CURRENT_DIRECTORY}/stage-assignments.json"
    values["stage_assignments"] = stages
    checkpoint = index_checkpoint(values, accepted, successor=successor)
    checkpoint.update(
        current_migration_status=intake["status"],
        changed_writer_ids=changed,
        historical_commit=intake["historical_commit"],
    )
    return values, checkpoint, paths


def current_manifest(
    sources: Any, values: dict[str, Any], checkpoint: dict[str, Any], paths: dict[str, str]
) -> dict[str, Any]:
    intake = sources.json(CURRENT_INTAKE)
    inputs = {
        CURRENT_INTAKE,
        ROOT_PATH,
        REPORT_PATH,
        *[
            ref["path"]
            for ref in migration_bindings(sources, package_path=intake["package"]["path"])
        ],
    }
    if intake["status"] == "verified":
        receipt = sources.json(intake["receipt_path"])
        inputs.update((intake["receipt_path"], receipt["junit"]["path"]))
    return {
        "schema": 1,
        "capture_sha256": discovery.CAPTURE_SHA256,
        "classification_status": "current_witnessed"
        if intake["status"] == "verified"
        else "current_migration_pending",
        "historical_commit": intake["historical_commit"],
        "inputs": [sources.reference(path) for path in sorted(inputs)],
        "artifacts": {name: sources.reference(path) for name, path in sorted(paths.items())},
        "counts": {name: len(value) for name, value in values.items()},
        "checkpoint": checkpoint,
        "authority": "none; historical classification and current migration do not sign future product duties",
    }


def current_report_for(sources: Any, root: dict[str, Any]) -> dict[str, Any]:
    from tools.ci.a4_schema import INVESTIGATION, check_shape  # noqa: PLC0415

    values = {name: sources.json(ref["path"]) for name, ref in root["artifacts"].items()}
    paths = {name: ref["path"] for name, ref in root["artifacts"].items()}
    capture = sources.json(discovery.ROOT_PATH)
    witnesses = []
    for node in sources.json(CURRENT_INTAKE)["crosscheck_nodes"]:
        path, function = node.split("::", 1)
        witnesses.append(sources.reference(path, function.split("[", 1)[0], "python"))
    result = {
        "schema": 1,
        "source_version": "1.15.0",
        "source_inputs": [
            sources.reference(CURRENT_ROOT),
            *root["inputs"],
            *root["artifacts"].values(),
            *witnesses,
        ],
        "scanned_directories": capture["scanned_directories"],
        "parse_failures": capture["parse_failures"],
        "unrecognized": sorted({row["question"] for row in values["physical"].values()}),
        "duplicates": values["raw_duplicates"],
        "discoveries": classification_discoveries(
            sources, values, directory=CURRENT_DIRECTORY, artifact_paths=paths
        ),
        "dlc_ids": sources.json(discovery.CATALOG_PATH)["dlc_ids"],
        "writer_ids": [],
        "consumer_ids": [],
        "crosscheck_receipt_ids": [],
    }
    check_shape(result, INVESTIGATION)
    return result


def validate_current_classification(sources: Any, report: dict[str, Any]) -> None:
    values, checkpoint, paths = current_artifacts(sources, replay=True)
    for name, value in values.items():
        if sources.json(paths[name]) != value:
            raise ValueError(f"current classification projection drift: {name}")
    root = sources.json(CURRENT_ROOT)
    if root != current_manifest(sources, values, checkpoint, paths):
        raise ValueError("current classification root/input coverage drift")
    expected = current_report_for(sources, root)
    expected["crosscheck_receipt_ids"] = report["crosscheck_receipt_ids"]
    if report != expected:
        raise ValueError("current classification investigation/source closure drift")
    sources.jsons["a4:classification-checkpoint"] = checkpoint
    sources.jsons["a4:stage-assignments"] = values["stage_assignments"]


def validate_classification(sources: Any, report: dict[str, Any]) -> None:
    root = sources.json(ROOT_PATH)
    values = artifacts(sources)
    for name, value in values.items():
        if sources.json(f"{DIRECTORY}/{name}.json") != value:
            raise ValueError(f"classification physical/source/owner/target drift: {name}")
    accepted = migration_acceptance(sources, values, replay=True)
    if sources.json(MIGRATION_ACCEPTANCE) != accepted:
        raise ValueError("migration acceptance source/writer/role/witness drift")
    values["migration_acceptance"] = accepted
    stages = stage_assignments(sources, values)
    if sources.json(STAGES_PATH) != stages:
        raise ValueError("classification stage/source/responsibility drift")
    checkpoint = index_checkpoint(values, accepted)
    # The gate may consume only the result of this independent reconstruction.
    sources.jsons["a4:classification-checkpoint"] = checkpoint
    sources.jsons["a4:stage-assignments"] = stages
    values.pop("migration_acceptance")
    if root != manifest(sources, values):
        raise ValueError("classification root/input coverage drift")
    expected = report_for(sources, root)
    expected["crosscheck_receipt_ids"] = report["crosscheck_receipt_ids"]
    if report != expected:
        raise ValueError("classification investigation/source closure drift")


def preview_current(sources: Any, destination: Path) -> dict[str, Any]:
    """Emit only changed projections; registration still uses ordinary reconcile."""
    from tools.ci.a4_scope import Sources  # noqa: PLC0415

    values, checkpoint, paths = current_artifacts(sources, replay=False)
    raw = {
        paths[name]: discovery.encoded(value) + b"\n"
        for name, value in values.items()
        if paths[name].startswith(f"{CURRENT_DIRECTORY}/")
    }
    projected = Sources(sources.root, {**sources.bytes, **raw})
    root = current_manifest(projected, values, checkpoint, paths)
    raw[CURRENT_ROOT] = discovery.encoded(root) + b"\n"
    projected = Sources(sources.root, {**sources.bytes, **raw})
    report = current_report_for(projected, root)
    # Preview never borrows Task8's old crosscheck pass. A distinct report
    # receipt is registered later against this exact report and source closure.
    raw[CURRENT_REPORT] = discovery.encoded(report) + b"\n"
    # Refresh the native projector's code/history bindings in a distinct
    # current report; its accepted historical report remains byte-identical.
    native_report = discovery.report_for(
        projected, projected.json(discovery.ROOT_PATH), projected.json(discovery.CATALOG_PATH)
    )
    raw[CURRENT_NATIVE_REPORT] = discovery.encoded(native_report) + b"\n"
    for path, data in raw.items():
        target = destination / Path(path).relative_to(CURRENT_DIRECTORY)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return checkpoint


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "check"))
    parser.add_argument("--output", default="tools/out/a4-task8/classification-preview")
    parser.add_argument(
        "--current",
        action="store_true",
        help="source-bound current candidate view; preserve immutable Task8",
    )
    arguments = parser.parse_args()
    from tools.ci.a4_scope import ROOT, Sources  # noqa: PLC0415

    sources = Sources(ROOT)
    if arguments.current:
        if arguments.action == "preview":
            print(discovery.encoded(preview_current(sources, ROOT / arguments.output)).decode())
        else:
            validate_current_classification(sources, sources.json(CURRENT_REPORT))
        return 0
    result = artifacts(sources)
    destination = ROOT / arguments.output
    for name, value in result.items():
        if arguments.action == "preview":
            discovery.write_json(destination / f"{name}.json", value)
        elif sources.json(f"{DIRECTORY}/{name}.json") != value:
            raise ValueError(f"classification projection drift: {name}")
    print(
        discovery.encoded(
            {
                "physical": len(result["physical"]),
                "syntax_kinds": dict(
                    Counter(r["syntax_kind"] for r in result["physical"].values())
                ),
                "targets": len(result["targets"]),
                "predecessors": len(result["predecessors"]),
            }
        ).decode()
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
