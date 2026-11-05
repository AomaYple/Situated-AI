"""Join exact native business reviews to current physical and production proof.

This adds no discovery scanner, runtime permission or product completion claim.
Unreviewed candidates remain explicit, including omitted event weight slots.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

from pdx import config
from pdx.model import Assignment, Block, Scalar

from .native_treatments import (
    _acceptance_program_proof,
    _ast,
    _companion_fields,
    _declaration,
    _Dependencies,
    _digest,
    _event_program_proofs,
    _family,
    _numeric_shape,
    _path,
    _registered_numeric_value,
    _resolve,
    _Sources,
    _support_program_proof,
    _variable_boundary,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from .vanilla_inventory import VanillaInventory

CONTRACT = config.REPO / "research/situated/a3-native-business-review.json"
_COMMON_IDENTITIES = "8a55029fbcbcc7307aff5eb8cd47256a222cc0a3993f3607cfc3c21444bfeb61"
_RETENTION_IDENTITIES = "b19ccbc944a5175a397d6d7e5fa9a1f380e87f2c74a7cbb239ca0a5c88c49f5e"
_RETENTION_EVIDENCE = "b431daf4f8d5cff99c0220f59e4e0c28a20b141ed4ca3518f31ff9e5104a42a6"


def search_inputs(game: Path | None = None) -> dict[str, bytes]:
    """Read the frozen no-caller search scope without granting runtime access.

    Inventory inputs include verified declared DLC mounts and relevant docs;
    all root common/events text is also required because an unrelated AI-free
    file can still introduce a journal-entry invocation.
    """
    from .vanilla_inventory import _contained, _inputs  # noqa: PLC0415

    root = config.GAME if game is None else game
    inputs, _, _ = _inputs(root)
    for directory in ("common", "events"):
        for path in sorted((root / directory).rglob("*.txt")):
            _contained(root, path)
            inputs[path.relative_to(root).as_posix()] = path.read_bytes()
    return inputs


def _identities(values) -> str:
    return hashlib.sha256(json.dumps(sorted(values), separators=(",", ":")).encode()).hexdigest()


def load(path: Path = CONTRACT) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        data.get("schema") != 1
        or data.get("C1_complete") is not False
        or data.get("business_complete") is not False
        or data.get("common_denominator") != 8856
        or data.get("event_option_denominator") != 4840
        or len(data.get("rows", ())) != 1107
        or len(data.get("retained_event_rows", ())) != 395
        or len(data.get("unresolved_common_ids", ())) != 472
        or len(data.get("unresolved_event_option_rows", ())) != 4445
    ):
        raise ValueError("A3业务复核必须保持独立冻结分母和真实未决状态")
    ids = [row["surface_id"] for row in data["rows"]] + data["unresolved_common_ids"]
    migrated = [
        row for row in data["rows"] if row.get("business_family") == "common_tail_exact_retention"
    ]
    if (
        _identities(ids) != _COMMON_IDENTITIES
        or _identities(row["surface_id"] for row in migrated) != _RETENTION_IDENTITIES
        or len(migrated) != 21
        or len({row["reason_index"] for row in migrated}) != 21
        or any(not row.get("business_support_ids") for row in migrated)
        or any(
            identity not in data.get("business_supports", {})
            for row in migrated
            for identity in row["business_support_ids"]
        )
    ):
        raise ValueError("A3业务迁移必须保持旧身份全集及21项精确处置")
    evidence = {
        "rows": migrated,
        "contexts": {
            row["parent_context"]: data["parent_contexts"].get(row["parent_context"])
            for row in migrated
        },
        "supports": data.get("business_supports"),
        "group": data["groups"].get("common_tail_exact_retention"),
        "change": data.get("common_retention_change"),
    }
    if (
        hashlib.sha256(
            json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        != _RETENTION_EVIDENCE
    ):
        raise ValueError("A3业务精确保留理由和支持闭包身份漂移")
    if len(set(ids)) != len(ids):
        raise ValueError("A3业务复核重复或混淆具体候选身份")
    for row in data["rows"]:
        group = data["groups"].get(row["business_family"])
        if (
            not group
            or group["counts_as_new_capability"] is not False
            or group["new_behavior"] is not False
            or type(row["reason_index"]) is not int
            or not 0 <= row["reason_index"] < len(group["reasons"])
            or not group["reasons"][row["reason_index"]].strip()
            or row["parent_context"] not in data["parent_contexts"]
        ):
            raise ValueError("A3业务保留必须有精确父结构和具体理由，不计新增能力")
    return cast("dict[str, Any]", data)


def review(
    inventory: VanillaInventory,
    native_sources: Mapping[str, bytes],
    generated_sources: Mapping[str, bytes],
    treatments: Mapping[str, Any],
    *,
    data: Mapping[str, Any] | None = None,
    search_sources: Mapping[str, bytes] | None = None,
) -> dict[str, Any]:
    """Validate current bytes; native/native identity alone never signs a row."""
    data = load() if data is None else data
    native = _Sources(native_sources)
    effective = _Sources({**native_sources, **generated_sources}, reuse=native)
    if native.failures or effective.failures:
        raise ValueError("A3业务完整来源解析失败")
    surfaces = {surface.surface_id: surface for surface in inventory.surfaces}
    protected = {row["surface_id"]: row for row in treatments["rows"]}
    source_hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in native_sources.items()}
    # Search-only bytes prove the absence of callers; they do not become
    # declarations, readers or members of the decision inventory denominator.
    search_bytes = dict(native_sources if search_sources is None else search_sources)
    aliases: dict[str, str] = {}
    for name, raw in search_bytes.items():
        _path(name)
        if not isinstance(raw, bytes) or aliases.get(name.casefold(), name) != name:
            raise ValueError("A3调用搜索来源必须是无路径别名的完整字节")
        aliases[name.casefold()] = name
    search_hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in search_bytes.items()}
    inherited = _Dependencies(native, native, native_sources, native_sources, source_hashes)
    current = _Dependencies(
        effective,
        effective,
        {**native_sources, **generated_sources},
        {**native_sources, **generated_sources},
        source_hashes,
    )
    reference_cache: dict[str, bool] = {}
    event_proofs: dict[str, dict[str, Any]] | None = None
    support_cache: dict[str, bool] = {}
    production_hashes = {
        name: hashlib.sha256(raw).hexdigest() for name, raw in generated_sources.items()
    }
    candidate_bound = (
        treatments.get("production_hashes") == production_hashes
        and treatments.get("source_hashes_verified") == source_hashes
        and all(
            source_hashes.get(name) == digest
            for name, digest in inventory.source_hashes.items()
            if not name.startswith("@")
        )
    )
    child_dependencies = _Dependencies(
        native,
        effective,
        native_sources,
        {**native_sources, **generated_sources},
        inventory.source_hashes,
        production_complete=treatments.get("production_manifest_complete_asserted") is True,
    )

    def child_receipt_current(surface, before: Assignment, after: Assignment, child) -> bool:
        """Re-run existing dependency rules, including whole-program proof paths.

        Rebuilding receipts from this invocation binds source ownership, original
        opaque call contexts, recursive references, and specialized Reader/program
        evidence. A copied success status cannot stand in for current bytes.
        """
        consumer = after
        continuous = _support_program_proof(
            surface, inventory, child_dependencies, generated_sources
        ) or _acceptance_program_proof(surface, inventory, child_dependencies, generated_sources)
        if continuous:
            proofs, valid = child_dependencies.check(before, before, numeric=True, surface=surface)
            proofs.append(continuous)
        else:
            if not _numeric_shape(after, before):
                resolved = _registered_numeric_value(surface, after, effective, generated_sources)
                if resolved is None or resolved != child.get("resolved_numeric_value"):
                    return False
                helper, state = _resolve(
                    effective.roots[resolved["source"]], resolved["definition"], "__body__"
                )
                if helper is None or state != "found":
                    return False
                consumer = helper
            proofs, valid = child_dependencies.check(
                before, consumer, numeric=True, surface=surface
            )
        combined = {(item["family"], item["definition"]): item for item in proofs}
        for field in _companion_fields(surface):
            original, bstate = _resolve(native.roots[surface.source], surface.definition, field)
            actual, astate = _resolve(effective.roots[surface.source], surface.definition, field)
            if original is None and actual is None and bstate == astate == "missing":
                continue
            if (
                original is None
                or actual is None
                or bstate != astate
                or _ast(original) != _ast(actual)
            ):
                return False
            companion, closed = child_dependencies.check(
                original, actual, numeric=False, surface=surface
            )
            valid = valid and closed
            combined.update(((item["family"], item["definition"]), item) for item in companion)
        expected = [combined[key] for key in sorted(combined)]
        # Receipts may have completed a JSON roundtrip before this join.
        return valid and json.dumps(expected, sort_keys=True) == json.dumps(
            child.get("dependencies"), sort_keys=True
        )

    def parent(source: str, definition: str, digest: str, source_hash: str):
        if source_hashes.get(source) != source_hash:
            raise ValueError(f"A3业务原版完整源身份漂移：{source}")
        root = native.roots.get(source)
        if root is None:
            raise ValueError(f"A3业务缺少完整原版父结构：{source}")
        node, status = _resolve(root, definition, "__body__")
        if status != "found" or _digest(node) != digest:
            raise ValueError(f"A3业务父结构AST漂移：{source}#{definition}")
        return node

    def reference(identity: str) -> bool:
        if identity in reference_cache:
            return reference_cache[identity]
        proof = data["reference_proofs"][identity]
        raw = json.dumps(proof, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        if hashlib.sha256(raw).hexdigest() != identity:
            raise ValueError("A3业务引用证明身份漂移")
        source = proof["native_source"]
        if source not in native.roots or source_hashes[source] != proof["native_source_sha256"]:
            raise ValueError("A3业务缺少完整引用原件")
        if proof.get("origin") == "native_opaque_operand":
            # These digests identify the native caller, not a declaration of
            # the opaque operand. Protect its exact inherited context without
            # granting a reader permission or guessing its engine semantics.
            callers = [
                node
                for node in native.roots[source].assignments()
                if _digest(node) == proof["native_ast_sha256"]
            ]
            if len(callers) != 1:
                raise ValueError("A3业务不透明操作数缺少唯一原版调用者")
            before, state = _resolve(native.roots[source], callers[0].key, "__body__")
            expected, _ = inherited.opaque_proofs(before, before, numeric=True, source=source)
            if state != "found" or expected.get(("script_values", proof["definition"])) != proof:
                raise ValueError("A3业务不透明操作数原调用位置或权限漂移")
            after, state = _resolve(effective.roots[source], callers[0].key, "__body__")
            preserved = (
                state == "found"
                and after is not None
                and _digest(before) == _digest(after)
                and current.opaque_operands(after, numeric=True).get(proof["definition"])
                == proof["native_occurrences"]
                and native.owners.get((_family(source), callers[0].key))
                == effective.owners.get((_family(source), callers[0].key))
                == [source]
                and _variable_boundary(native.roots[source], effective.roots[source])
            )
        else:
            before, state = _resolve(native.roots[source], proof["definition"], "__body__")
            if state != "found" or _digest(before) != proof["native_ast_sha256"]:
                raise ValueError("A3业务引用AST漂移")
            after, state = _resolve(effective.roots[source], proof["definition"], "__body__")
            owner = (proof["family"], proof["definition"])
            preserved = (
                state == "found"
                and _digest(before) == _digest(after)
                and native.owners.get(owner) == effective.owners.get(owner) == [source]
                and _variable_boundary(native.roots[source], effective.roots[source])
            )
        reference_cache[identity] = preserved
        return preserved

    def references(ids: list[str]) -> bool:
        # Validate every frozen proof even when a sibling is unproven.
        checked = [reference(identity) for identity in ids]
        return all(checked)

    def invocation_boundary(closed: Mapping[str, Any]) -> bool:
        """Recheck the finite exact caller set behind an unreachable test JE."""
        # No-call evidence requires every raw file from the frozen mounted
        # inventory and complete root common/events search, including no-hit
        # sources and DLC descriptors. Extra supplied files are scanned too.
        if (
            not candidate_bound
            or any(
                search_hashes.get(source) != digest
                for source, digest in closed["source_hashes"].items()
            )
            or any(search_bytes.get(source, raw) != raw for source, raw in native_sources.items())
        ):
            return False
        names = set(closed["names"])
        occurrences = []

        def visit(value, source, path):
            if isinstance(value, Assignment):
                if value.key in names:
                    occurrences.append([source, list(path), value.key, "definition_or_call"])
                visit(value.value, source, (*path, value.key))
            elif isinstance(value, Block):
                for index, child in enumerate(value.items):
                    visit(child, source, (*path, index))
            elif isinstance(value, Scalar) and value.unquoted in names:
                occurrences.append([source, list(path), value.unquoted, "operand"])

        # A raw no-hit is sufficient for unrelated syntax (for example DNA
        # payloads). Every possible hit must parse, including newly supplied
        # native files and current output; a malformed hit remains unproven.
        needles = tuple(name.encode("utf-8") for name in names)
        candidates = {}
        for source, raw in {**search_bytes, **native_sources, **generated_sources}.items():
            if not source.endswith(".txt"):
                continue
            try:
                raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                return False
            if any(needle in raw for needle in needles):
                candidates[source] = raw
        callers = _Sources(candidates)
        if callers.failures:
            return False
        for source, root in sorted(callers.roots.items()):
            visit(root, source, ())
        return bool(occurrences == closed["occurrences"])

    def business_support(identity: str) -> bool:
        """Preserve explicit rationale witnesses, including actual JE callers.

        These static definitions grant no runtime permissions. The one changed
        plague event is accepted only by the existing complete EventProgram proof.
        """
        nonlocal event_proofs
        if identity in support_cache:
            return support_cache[identity]
        # A cycle is not a license to skip the child witness.
        support_cache[identity] = False
        support = data["business_supports"][identity]
        if "closed_invocations" in support and not invocation_boundary(
            support["closed_invocations"]
        ):
            return False
        source, definition = support["source"], support["definition"]
        before = parent(source, definition, support["parent_ast_sha256"], support["source_sha256"])
        owner = (_family(source), definition)
        if native.owners.get(owner) != [source] or effective.owners.get(owner) != [source]:
            return False
        after, state = _resolve(effective.roots[source], definition, "__body__")
        references_preserved = references(support["named_reference_proof_ids"])
        if (
            not references_preserved
            or state != "found"
            or not _variable_boundary(native.roots[source], effective.roots[source])
        ):
            return False
        child_checks = [business_support(child) for child in support["supporting_definition_ids"]]
        children_preserved = all(child_checks)
        if not children_preserved:
            return False
        if _ast(before) == _ast(after):
            support_cache[identity] = True
            return True
        if (source, definition) != (
            "events/spanish_flu_events.txt",
            "plague.5",
        ) or not candidate_bound:
            return False
        if event_proofs is None:
            event_proofs = _event_program_proofs(inventory, child_dependencies, generated_sources)
        matches = [
            s for s in inventory.surfaces if s.source == source and s.definition == definition
        ]
        support_cache[identity] = len(matches) == 3 and all(
            s.surface_id in event_proofs for s in matches
        )
        return support_cache[identity]

    def source_projection(surface, proof: Mapping[str, Any], *, container: bool) -> bool:
        """Recheck all registered leaves and the entire ordered current source."""
        source = "common/ai_strategies/00_default_strategy.txt"
        if (
            surface.source != source
            or surface.definition != "ai_strategy_default"
            or (
                container
                and surface.field
                not in {"wargoal_scores", "treaty_category_scores", "institution_scores"}
            )
            or (container and proof.get("native_role") != "structural_container")
            or (container and proof.get("interface", {}).get("control_authorized") is not False)
            or treatments.get("production_manifest_complete_asserted") is not True
            or not candidate_bound
        ):
            return False
        protection = proof.get("source_protection", {})
        composition = protection.get("structural_composition")
        actual_hash = hashlib.sha256(
            generated_sources.get(source, native_sources[source])
        ).hexdigest()
        if (
            (
                container
                and (
                    not isinstance(composition, dict)
                    or composition.get("family") != "structural_composition"
                    or composition.get("definition") != f"{surface.definition}.{surface.field}"
                    or composition.get("native_source") != source
                    or composition.get("effective_source") != source
                    or composition.get("status") != "proven_generated"
                    or composition.get("interface_authorized") is not False
                    or protection.get("proven") is not True
                    or protection.get("structural_projection") is not True
                )
            )
            or protection.get("context_closed") is not True
            or protection.get("dependencies_closed") is not True
            or protection.get("native_source_sha256") != source_hashes[source]
            or protection.get("effective_source_sha256") != actual_hash
            or treatments.get("production_hashes", {}).get(source) != actual_hash
        ):
            return False
        masks_before: dict[int, str] = {}
        masks_after: dict[int, str] = {}
        expected_children = []
        accepted = {"retained", "retained_opaque", "proven_generated", "proven_parameter_reader"}
        for child in treatments["rows"]:
            if child.get("source") != source or child.get("status") != "implemented_numeric":
                continue
            identity = child.get("surface_id")
            actual_surface = surfaces.get(identity)
            if (
                actual_surface is None
                or (actual_surface.source, actual_surface.definition, actual_surface.field)
                != (child["source"], child["definition"], child["field"])
                or not actual_surface.legal
                or actual_surface.ambiguity
                or child.get("interface", {}).get("control_authorized") is not True
            ):
                return False
            before, bstate = _resolve(native.roots[source], child["definition"], child["field"])
            after, astate = _resolve(effective.roots[source], child["definition"], child["field"])
            if (
                before is None
                or after is None
                or bstate != "found"
                or astate != "found"
                or actual_surface.declaration_id != child.get("declaration_id")
                or child.get("implemented_numeric") is not True
                or child.get("issues") != []
                or not child.get("numeric_actions")
                or child.get("native_ast_sha256") != _digest(before)
                or child.get("effective_ast_sha256") != _digest(after)
                or any(item.get("status") not in accepted for item in child["dependencies"])
                or not child_receipt_current(actual_surface, before, after, child)
            ):
                return False
            masks_before[id(before)] = child["declaration_id"]
            masks_after[id(after)] = child["declaration_id"]
            if child["definition"] == surface.definition and child["field"].startswith(
                surface.field + "."
            ):
                expected_children.append(
                    {
                        key: child[key]
                        for key in (
                            "declaration_id",
                            "field",
                            "native_ast_sha256",
                            "effective_ast_sha256",
                            "numeric_actions",
                            "dependencies",
                        )
                    }
                )
        if container and (
            not expected_children or composition.get("children") != expected_children
        ):
            return False
        if sorted(masks_before.values()) != protection.get("controlled_numeric_declarations"):
            return False
        additions: set[int] = set()
        for addition in [
            *protection.get("implicit_numeric_projections", []),
            *protection.get("implicit_enum_projections", []),
        ]:
            before, bstate = _resolve(
                native.roots[source], addition["definition"], addition["field"]
            )
            after, astate = _resolve(
                effective.roots[source], addition["definition"], addition["field"]
            )
            if (
                before is not None
                or bstate != "missing"
                or after is None
                or astate != "found"
                or _digest(after) != addition.get("effective_ast_sha256")
            ):
                return False
            additions.add(id(after))

        def boundary(value, masks):
            if isinstance(value, Assignment):
                if id(value) in masks:
                    return [
                        "typed_numeric_change",
                        value.key,
                        value.op,
                        value.prefix,
                        masks[id(value)],
                    ]
                return [
                    "assignment",
                    value.key,
                    value.op,
                    value.prefix,
                    boundary(value.value, masks),
                ]
            if isinstance(value, Block):
                return [
                    "block",
                    [boundary(item, masks) for item in value.items if id(item) not in additions],
                ]
            return _ast(value)

        before, bstate = _resolve(native.roots[source], surface.definition, surface.field)
        after, astate = _resolve(effective.roots[source], surface.definition, surface.field)
        return (
            bstate == astate == "found"
            and (
                not container
                or (
                    composition.get("native_ast_sha256") == _digest(before)
                    and composition.get("effective_ast_sha256") == _digest(after)
                )
            )
            and proof.get("effective_ast_sha256") == _digest(after)
            and boundary(native.roots[source], masks_before)
            == boundary(effective.roots[source], masks_after)
        )

    def changed_numeric_implementation(
        surface, proof: Mapping[str, Any], row: Mapping[str, Any]
    ) -> bool:
        """Accept a changed frozen field only as a verified numeric implementation.

        This disposition preserves the frozen native-policy rationale while
        explicitly recording that the current field changed. It requires the
        current registered action mapping and complete source/dependency closure;
        it never turns the changed field into exact native retention.
        """
        if (
            row.get("business_family") != "native_specialized_strategy_additive"
            or surface.source != "common/ai_strategies/00_default_strategy.txt"
            or surface.definition != "ai_strategy_default"
            or surface.field
            not in {
                "secret_goal_scores.protect.score",
                "secret_goal_scores.reconcile.score",
                "diplomatic_play_support",
            }
            or proof.get("status") != "implemented_numeric"
            or proof.get("implemented_numeric") is not True
            or not proof.get("numeric_actions")
            or proof.get("interface", {}).get("known") is not True
            or proof.get("interface", {}).get("control_authorized") is not True
        ):
            return False
        before, bstate = _resolve(native.roots[surface.source], surface.definition, surface.field)
        after, astate = _resolve(effective.roots[surface.source], surface.definition, surface.field)
        if before is None or after is None or bstate != "found" or astate != "found":
            return False
        if surface.field == "diplomatic_play_support":
            registered = _support_program_proof(
                surface, inventory, child_dependencies, generated_sources
            )
            if not registered or proof["numeric_actions"] != [registered["definition"]]:
                return False
        else:
            from .action_instances import _id  # noqa: PLC0415

            contract = child_dependencies._parameter_contract(surface.source)
            if contract is None:
                return False
            _policy, groups, identity = contract
            path = (surface.definition, *surface.field.split("."))
            rules = groups.get(path, ())
            if not rules or sorted(proof["numeric_actions"]) != sorted(
                _id(surface.source, rule.id) for rule in rules
            ):
                return False
            # Compare the whole actually emitted field, not just the Reader
            # occurrences or an action-ID label copied from a coverage receipt.
            expected_root = child_dependencies._parameter_program_root(surface.source, identity)
            if expected_root is None:
                return False
            expected, state = _resolve(expected_root, surface.definition, surface.field)
            if state != "found" or _ast(after) != _ast(expected):
                return False
        protection = proof.get("source_protection", {})
        return (
            protection.get("proven") is False
            and protection.get("context_closed") is True
            and protection.get("dependencies_closed") is True
            and protection.get("structural_projection") is False
            and "native_declaration_changed_or_unresolved" in protection.get("issues", [])
            and proof.get("native_ast_sha256") == row.get("field_ast_sha256")
            and proof.get("effective_ast_sha256") != row.get("field_ast_sha256")
            and all(
                dependency.get("status")
                in {"retained", "retained_opaque", "proven_generated", "proven_parameter_reader"}
                for dependency in proof.get("dependencies", [])
            )
            and source_projection(surface, proof, container=False)
        )

    def registered_sibling_ir_current(source: str, policy) -> bool:
        from pdx import decision_rules  # noqa: PLC0415

        from . import action_instances, bindings, compiler, decision_ir, ir  # noqa: PLC0415

        contexts = (
            compiler._frozen_native_decision_contexts()
            if source == "common/decisions/00_decisions.txt"
            else compiler._frozen_mobilization_contexts()
            if source == "common/mobilization_options/00_mobilization_option.txt"
            else {}
        )
        if not contexts:
            return False
        empty = decision_rules.RuleSet((), (), "0" * 64, "0" * 64, frozenset())
        adapters = replace(
            child_dependencies.parameter_adapters,
            policies=((source, policy),),
            event_programs=(),
            acceptance_programs=(),
            supply=None,
        )
        rules = {rule.id: rule for rule in policy.rules}
        readers = {reader.key: reader for reader in policy.readers}
        instances = tuple(
            replace(
                instance,
                evaluation_context=contexts.get((source, instance.consumer_field)),
            )
            for instance in action_instances.build(empty, adapters)
        )
        if any(instance.evaluation_context is None for instance in instances):
            return False
        bundle = decision_ir.compile_consumer_ir(
            (),
            (),
            (),
            ir.from_rules((source, rule) for rule in policy.rules),
            bindings.build(information=empty, adapters=adapters),
            instances,
        )
        bundle = replace(
            bundle,
            writers=tuple(
                replace(
                    writer,
                    reader_context_bindings=compiler.validate_context_readers(
                        writer.field,
                        contexts[source, writer.field],
                        readers,
                        rules[writer.definition].conditions,
                        actor_path=policy.actor_path,
                        input_keys=tuple(rules[writer.definition].input_keys()),
                        source=source,
                        native_root=policy.native_root,
                    ),
                )
                for writer in bundle.writers
            ),
        )
        expected = bundle.as_dict()
        metadata = json.loads(generated_sources[".metadata/metadata.json"])
        actual = metadata["situated_actions"]["consumer_ir"]
        rows = actual["writers"]
        ids = [row["writer_id"] for row in rows]
        current = sorted(
            (row for row in rows if row.get("source") == source), key=lambda row: row["writer_id"]
        )
        return (
            type(actual["schema"]) is int
            and actual["schema"] == 1
            and type(actual["writer_count"]) is int
            and actual["writer_count"] == len(rows)
            and len(ids) == len(set(ids))
            and json.dumps(current, sort_keys=True)
            == json.dumps(expected["writers"], sort_keys=True)
            and all(actual["field_owners"].get(k) == v for k, v in expected["field_owners"].items())
            and all(
                actual["source_field_owners"].get(k) == v
                for k, v in expected["source_field_owners"].items()
            )
        )

    def retained_source_with_registered_siblings(source: str) -> bool:
        """A retained sibling may coexist with other exactly registered writers.

        Recompute the complete source oracle and every controlled child's
        dependency proof. Native identity or a copied parent receipt alone
        cannot authorize a sibling's current change.
        """
        if _ast(native.roots[source]) == _ast(effective.roots[source]):
            return True
        contract = child_dependencies._parameter_contract(source)
        if not contract:
            return False
        policy, groups, identity = contract
        oracle = child_dependencies._parameter_program_root(source, identity)
        if (
            oracle is None
            or _ast(oracle) != _ast(effective.roots[source])
            or not _variable_boundary(native.roots[source], effective.roots[source])
            or not registered_sibling_ir_current(source, policy)
        ):
            return False
        for path in groups:
            definition, *parts = path
            field = ".".join(parts)
            matches = [
                surface
                for surface in inventory.surfaces
                if (surface.source, surface.definition, surface.field)
                == (source, definition, field)
            ]
            if len(matches) != 1:
                return False
            surface = matches[0]
            child = protected.get(surface.surface_id, {})
            before, bstate = _resolve(native.roots[source], definition, field)
            after, astate = _resolve(effective.roots[source], definition, field)
            if (
                before is None
                or after is None
                or bstate != astate
                or bstate != "found"
                or child.get("status") != "implemented_numeric"
                or child.get("interface", {}).get("control_authorized") is not True
                or not child_receipt_current(surface, before, after, child)
            ):
                return False
        return True

    parents = {}
    for identity, context in data["parent_contexts"].items():
        parents[identity] = parent(
            context["source"],
            context["definition"],
            context["parent_ast_sha256"],
            context["source_sha256"],
        )
    result = []
    for row in data["rows"]:
        surface = surfaces.get(row["surface_id"])
        context = data["parent_contexts"][row["parent_context"]]
        if surface is None or (
            surface.source,
            surface.definition,
            surface.field,
            surface.source_line,
            surface.declaration_occurrence,
        ) != (
            context["source"],
            context["definition"],
            row["field"],
            row["source_line"],
            row["declaration_occurrence"],
        ):
            raise ValueError("A3业务候选不匹配独立原版库存")
        node = _declaration(native.roots[surface.source], surface)
        if _digest(node) != row["field_ast_sha256"]:
            raise ValueError("A3业务精确字段AST漂移")
        proof = protected.get(surface.surface_id, {})
        references_preserved = references(context["named_reference_proof_ids"])
        support_checks = [
            business_support(identity) for identity in row.get("business_support_ids", [])
        ]
        support_preserved = all(support_checks)
        preserved = (
            treatments.get("production_manifest_complete_asserted") is True
            and candidate_bound
            and support_preserved
            and (
                row.get("business_family") != "common_tail_exact_retention"
                or retained_source_with_registered_siblings(surface.source)
            )
            and proof.get("source_protection", {}).get("proven") is True
            and proof.get("native_ast_sha256") == row["field_ast_sha256"]
            and proof.get("effective_ast_sha256") == row["field_ast_sha256"]
            and references_preserved
        )
        composed = references_preserved and source_projection(surface, proof, container=True)
        changed_numeric = references_preserved and changed_numeric_implementation(
            surface, proof, row
        )
        result.append(
            {
                "surface_id": surface.surface_id,
                "business_family": row["business_family"],
                "reason": data["groups"][row["business_family"]]["reasons"][row["reason_index"]],
                "disposition": "retained_exact_native_policy"
                if preserved
                else "retained_native_structure_with_verified_numeric_children"
                if composed
                else "verified_numeric_implementation_preserving_native_context"
                if changed_numeric
                else "production_protection_unproven",
                "counts_as_new_capability": False,
            }
        )
    options = {
        (option.source, option.definition, option.option_index): option
        for option in inventory.event_options
    }
    event_result = []
    for row in data["retained_event_rows"]:
        identity = (row["source"], row["definition"], row["option_index"])
        candidate = options.get(identity)
        node = parent(
            row["source"], row["definition"], row["parent_ast_sha256"], row["source_sha256"]
        )
        if node is None or not isinstance(node.value, Block) or candidate is None:
            raise ValueError("A3业务事件候选原版身份缺失")
        option = node.value.all("option")[row["option_index"] - 1]
        if (
            candidate.option_name != row["option_name"]
            or candidate.source_line != row["option_line"]
            or _digest(option) != row["option_ast_sha256"]
        ):
            raise ValueError("A3业务事件选项AST或对象漂移")
        if row["disposition"] == "preserve_single_declared_option":
            if len(node.value.all("option")) != 1:
                raise ValueError("单选保留不能隐藏新增替代项")
        elif row["disposition"] == "preserve_explicit_player_country_trigger":
            trigger = node.value.first("trigger")
            kind = node.value.first("type")
            player = (
                trigger.value.first("is_player")
                if trigger is not None and isinstance(trigger.value, Block)
                else None
            )
            if (
                kind is None
                or not isinstance(kind.value, Scalar)
                or kind.value.unquoted != "country_event"
                or player is None
                or player.op != "="
                or not isinstance(player.value, Scalar)
                or player.value.unquoted != "yes"
            ):
                raise ValueError("玩家事件必须有country ROOT的直接is_player正条件")
        else:
            raise ValueError("A3事件只接受逐原件单选或明确玩家边界")
        after, state = _resolve(effective.roots[row["source"]], row["definition"], "__body__")
        references_preserved = references(row["named_reference_proof_ids"])
        preserved = (
            treatments.get("production_manifest_complete_asserted") is True
            and candidate_bound
            and native.owners[_family(row["source"]), row["definition"]] == [row["source"]]
            and effective.owners[_family(row["source"]), row["definition"]] == [row["source"]]
            and _variable_boundary(native.roots[row["source"]], effective.roots[row["source"]])
            and state == "found"
            and _digest(after) == _digest(node)
            and references_preserved
        )
        event_result.append(
            {
                **dict(zip(("source", "definition", "option_index"), identity, strict=True)),
                "disposition": row["disposition"]
                if preserved
                else "production_protection_unproven",
                "counts_as_new_capability": False,
            }
        )
    return {
        "evidence_category": "static_check",
        "common_review_rows": result,
        "event_review_rows": event_result,
        "counts": dict(Counter(row["disposition"] for row in result + event_result)),
        "unresolved_common_ids": data["unresolved_common_ids"],
        "unresolved_event_option_rows": data["unresolved_event_option_rows"],
        "C1_complete": False,
        "business_complete": False,
        "limits": data["limitations"],
    }
