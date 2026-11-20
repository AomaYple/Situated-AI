"""Verify the installed native scope, archived identities, and regression cases."""

from __future__ import annotations

import gzip
import hashlib
import json
import struct
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any

import pytest
import test_decision_adapters as adapter_tests

from pdx import config, decisions, version_contracts
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_bytes, parse_text
from pdx.situated import compiler, engine_scope, migration_baseline, pdx_eval, vanilla_inventory
from pdx.situated.receipts import digest

if TYPE_CHECKING:
    from pathlib import Path

real_generated_branches = adapter_tests.real_generated_branches

ROOT = config.REPO.resolve()
ARCHIVE_COMMIT = "c91569521ab4aad9cd38db0b242836cf8bda64ab"
# Handwritten frozen identities, independently reviewed against the old Git tree.
ARCHIVES = (
    (
        "docs/design/exec/mod重设计-实施计划.md",
        "6661104271c30e93779dfb774eda0da8e9e85d843db62516ded1330004623365",
        130854,
    ),
    (
        "docs/design/架构主计划.md",
        "7087f800dcf417dbb01c7125bed6f39cddaefd3760ce91601019b849183ab4a6",
        39543,
    ),
    (
        "docs/design/架构子计划.md",
        "50d26df22efca8c6602ff04e36afe5c5e1b6a4df02376439e557f719cf227c7a",
        22575,
    ),
    (
        "docs/design/03-处境决策设计.md",
        "07df1c15a53490a5b4f739a668981154cd8c3e6bc5851e19906503e1bea9c060",
        18573,
    ),
    (
        "docs/design/04-行动覆盖与验收.md",
        "038b68c6513c66294906e3172bd5a8fdaaa8a85ff38172ecab5f75cf3f79a31b",
        28759,
    ),
    (
        "docs/design/05-行动层深化设计.md",
        "054e7cb1c716f4bfd401d3bcf7dd6079a77d04526c3f6e34111a19af2fc6fb58",
        15487,
    ),
    (
        "docs/design/当前工作清单.md",
        "16a9f048c4bcca4601cf11f852e48c475e4803804b25fa6d696041a91b32b96f",
        11518,
    ),
)
FIELDS = ("source", "definition", "field", "actor", "target", "operation")
TAIL = "retain_original_qualification_cost_random_execution"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(scope="module")
def actual_scope() -> vanilla_inventory.VanillaInventory:
    return vanilla_inventory.discover()


def _source_path(name: str) -> Path:
    if name.startswith("@evidence/"):
        return ROOT / name.removeprefix("@evidence/")
    if name.startswith("@engine/"):
        return config.GAME.parent / name.removeprefix("@engine/")
    if name.startswith("@version/"):
        return config.GAME.parent / name.removeprefix("@version/")
    return config.GAME / name


def _actual_sources(inventory: vanilla_inventory.VanillaInventory) -> dict[str, str]:
    return {name: _sha(_source_path(name).read_bytes()) for name in inventory.source_hashes}


def _field_locations(block: Block, prefix: tuple[str, ...] = ()):
    for assignment in block.assignments():
        path = (*prefix, assignment.key)
        yield ".".join(path), assignment
        if isinstance(assignment.value, Block):
            yield from _field_locations(assignment.value, path)


def _ast_bytes(node: Assignment | Block | Scalar | None) -> object:
    if isinstance(node, Assignment):
        return ["assignment", node.key, node.op, node.prefix, _ast_bytes(node.value)]
    if isinstance(node, Block):
        return ["block", [_ast_bytes(child) for child in node.items]]
    if isinstance(node, Scalar):
        return ["scalar", node.text, node.quoted]
    return None


def _native_field_hash(path: Path, definition: str, field: str) -> str:
    parsed = parse_bytes(path.read_bytes(), path=path.name)
    assert not parsed.errors
    definitions = parsed.root.all(definition)
    assert len(definitions) == 1
    node = definitions[0]
    for key in field.split("."):
        assert isinstance(node.value, Block)
        children = node.value.all(key)
        assert len(children) == 1
        node = children[0]
    return _sha(
        json.dumps(_ast_bytes(node.value), ensure_ascii=False, separators=(",", ":")).encode()
    )


def test_s0_archive_identity() -> None:
    manifest = ROOT / "docs/design/archive/manifest.json"
    data = json.loads(manifest.read_bytes())
    expected = [
        {"path": path, "sha256": sha, "bytes": size, "commit": ARCHIVE_COMMIT}
        for path, sha, size in ARCHIVES
    ]
    observed = []
    for path, expected_sha, _ in ARCHIVES:
        # Independent storage reader: no production loader, Git object or network.
        raw = gzip.decompress(
            (ROOT / f"docs/design/archive/objects/{ARCHIVE_COMMIT}/{expected_sha}.gz").read_bytes()
        )
        observed.append(
            {
                "path": path,
                "sha256": _sha(raw),
                "bytes": len(raw),
                "commit": ARCHIVE_COMMIT,
            }
        )
    assert data["schema"] == 1
    assert data["role"] == "historical_reference_only"
    assert expected == data["files"], "frozen-seven-originals"
    assert expected == observed, "frozen-seven-originals"


@pytest.mark.integration
def test_s0_independent_scope(
    actual_scope: vanilla_inventory.VanillaInventory,
) -> None:
    inventory = actual_scope
    expected = {
        "declarations": 9797,
        "legal": 5745,
        "capabilities": {
            "direct": 2901,
            "indirect": 2844,
            "observation": 3416,
            "pending": 636,
            "unexposed": 0,
        },
        "parsed_files": 1878,
        "content_roots": ["common"],
        "parse_failures": [],
    }
    observed = {
        "declarations": len(inventory.surfaces),
        "legal": sum(
            s.capability in {"direct", "indirect"}
            and s.actor_scope != "unknown"
            and s.target_scope != "unknown"
            and bool(s.scope_evidence)
            for s in inventory.surfaces
        ),
        "capabilities": dict(Counter(s.capability for s in inventory.surfaces)) | {"unexposed": 0},
        "parsed_files": sum(
            name.endswith(".txt")
            for name in inventory.source_hashes
            if not name.startswith("@")
            and any(name.startswith(directory + "/") for directory in inventory.scanned_directories)
        ),
        "content_roots": list(inventory.content_roots),
        "parse_failures": [],
    }
    reference = {
        "declarations": inventory.discovered_count,
        "legal": inventory.legal_count,
        "capabilities": inventory.capability_counts,
        "parsed_files": inventory.parsed_files,
        "content_roots": list(inventory.content_roots),
        "parse_failures": list(inventory.parse_failures),
    }
    assert expected == reference, "installed-native-denominator"
    assert expected == observed, "installed-native-denominator"
    native_sources = _actual_sources(inventory)
    # Complete achievement and population sources prove reader scopes without
    # entering consumer discovery or changing its reviewed declaration count.
    assert len(native_sources) == 1960
    # Each of the six script hashes was independently rechecked on the installed 1.15.2.
    expected_pins = {
        "common/achievements/ep1_sphere_of_influence_achievements.txt": "323263f0483c14145c79b2a054bc7dd04aee5783731e5204604861d602cd4969",
        "common/achievements/ip4_iberian_twilight_achievements.txt": "0fb91eda557761442864e4e18a4a5c7be3dace31ac9b423b2581bfab8b986268",
        "common/pop_types/laborers.txt": "3b136e31556cd483ea213c82eef47c93f9774490775870622331f6139160d9f2",
        "common/pop_types/peasants.txt": "1d544a332f7c628b5f832f2a2033c25fafde6d9ed5e629b829432a57419f0c42",
        "common/pop_types/machinists.txt": "5960f8b6cc15e67b1305bf5d0d74368d2004572099b87ce4c6c827818497c39f",
        "common/journal_entries/00_urbanization.txt": "dff544be003ef9c6283132b38696bf2b765f170aa0a06771a6ce4afc820fd622",
    }
    assert {name: native_sources[name] for name in expected_pins} == expected_pins
    assert native_sources == inventory.source_hashes, "every-bound-source-byte"
    # Independently walk actual syntax, resolving all discovered declarations by
    # definition, full field path, line and occurrence. No Mod rule supplies this
    # syntax index or the denominator.
    surfaces_by_source: dict[str, list[Any]] = defaultdict(list)
    for surface in inventory.surfaces:
        surfaces_by_source[surface.source].append(surface)
    observed_ids: list[str] = []
    for source, surfaces in surfaces_by_source.items():
        raw = _source_path(source).read_bytes()
        parsed = parse_bytes(raw, path=source)
        assert not parsed.errors, source
        locations: dict[tuple[str, str, int], list[Assignment]] = defaultdict(list)
        for definition in parsed.top_assignments:
            locations[(definition.key, "__body__", definition.line)].append(definition)
            if isinstance(definition.value, Block):
                for field, node in _field_locations(definition.value):
                    locations[(definition.key, field, node.line)].append(node)
        occurrences: dict[tuple[str, str], list[int]] = defaultdict(list)
        for surface in surfaces:
            assert locations[(surface.definition, surface.field, surface.source_line)], (
                source,
                surface.definition,
                surface.field,
                surface.source_line,
            )
            occurrences[(surface.definition, surface.field)].append(surface.declaration_occurrence)
            identity = (source, surface.definition, surface.field, surface.declaration_occurrence)
            assert surface.declaration_id == digest(identity)
            if surface.parent_field is not None:
                assert locations[
                    (surface.definition, surface.parent_field, surface.parent_source_line)
                ]
            observed_ids.append(surface.declaration_id)
        for numbers in occurrences.values():
            assert sorted(numbers) == list(range(1, len(numbers) + 1))
    assert len(observed_ids) == len(set(observed_ids)) == expected["declarations"]


def _known_failure_observations(branches) -> None:
    from hypothesis.vendor.pretty import pretty

    scripts = [
        "if = { limit = { always = yes } if = { limit = { always = yes } add = 2 } }",
        "if = { limit = { always = yes } if = { limit = { always = no } add = 2 } } else_if = { limit = { always = yes } add = 3 } else = { add = 4 }",
        "if = { limit = { always = no } add = 2 } else_if = { limit = { always = yes } if = { limit = { always = no } add = 3 } else = { multiply = 1.3 } } else = { add = 4 }",
        "if = { limit = { always = no } add = 2 } else_if = { limit = { always = no } add = 3 } else = { add = 4 }",
    ]
    for number, (script, expected) in enumerate(
        zip(scripts, [("add", 2.0), None, ("multiply", 1.3), ("add", 4.0)], strict=True)
    ):
        parsed = parse_text(script)
        assert not parsed.errors
        reference = adapter_tests._interpret_adjustments(parsed.root, {})
        result = pdx_eval.evaluate("# ACTION nested_regression [oracle];\n" + script, {})
        selected = [item for item in result if item.fallback == "selected"]
        observed = (selected[0].operation, selected[0].delta) if selected else None
        assert expected == reference, f"historical-nested-chain-{number}"
        assert expected == observed, f"historical-nested-chain-{number}"
    # Replay the actual saved Hypothesis example against the unchanged, complete
    # generated adapter fixture and the original independent oracle assertions.
    adapter_tests.test_every_actual_adapter_branch_matches_reference_with_typed_inputs.hypothesis.inner_test(
        branches, seed=284, is_ai=True, missing_target=False
    )
    # Exercise diagnostics with the real full fixture, preserving its payload.
    assert len(branches.branches) > 20
    expected_diagnostics = {
        "repr": "_GeneratedBranches()",
        "pretty": f"_GeneratedBranches(policies={len(branches.branches)})",
        "payload_retained": True,
    }
    reference_diagnostics = {
        "repr": repr(branches),
        "pretty": pretty(branches),
        "payload_retained": bool(branches.scripts),
    }
    observed_diagnostics = {
        "repr": repr(branches),
        "pretty": pretty(branches),
        "payload_retained": all(id(policy) in branches.scripts for policy, _ in branches.branches),
    }
    assert expected_diagnostics == reference_diagnostics, "bounded-real-fixture-diagnostics"
    assert expected_diagnostics == observed_diagnostics, "bounded-real-fixture-diagnostics"
    law_manifest = version_contracts.research_path("situated", "engine-law.json")
    expected_manifest_sha = "1e7c0e640d6cde80fcece6951bb26c3ff26b5bbb3eb8daae7c582517e265cec7"
    manifest_bytes = law_manifest.read_bytes()
    assert _sha(manifest_bytes) == expected_manifest_sha
    data = json.loads(manifest_bytes)
    assert data["baseline"] == f"victoria3-{version_contracts.active_version()}-windows-x64"
    inputs = {source: (config.GAME / source).read_bytes() for source in data["script_hashes"]}
    actual_hashes = {source: _sha(raw) for source, raw in inputs.items()}
    expected_sources = 25
    assert len(actual_hashes) == expected_sources
    assert actual_hashes == data["script_hashes"]
    proof = engine_scope.law_evidence(config.GAME, inputs)
    assert proof.verified
    # Independently checked edges in the installed executable's reviewed windows.
    edges = (
        ("law parser thunk", "0x1408492c3", "e9e885fc00", "0x1418118b0"),
        ("law exact token dispatch", "0x141811ad7", "0f8447010000", "0x141811c24"),
        ("law qualification wrapper", "0x14163e349", "e852621d00", "0x1418145a0"),
        ("actual law AI candidate consumer", "0x1415fcd19", "e842140400", "0x14163e160"),
        ("actual law AI candidate consumer", "0x1415fcd25", "0f848d020000", "0x1415fcfb8"),
    )
    control_flow_checks = [
        {
            "label": label,
            "instruction_va": address,
            "instruction_bytes": instruction,
            "target_va": target,
        }
        for label, address, instruction, target in edges
    ]
    executable = config.GAME.parent / "binaries/victoria3.exe"
    assert executable.stat().st_size == data["exe"]["bytes"]
    windows = {}
    with executable.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == data["exe"]["sha256"]
        for point in data["observations"]:
            stream.seek(int(point["file_offset"], 16))
            raw = stream.read(point["size"])
            assert len(raw) == point["size"]
            assert _sha(raw) == point["sha256"]
            windows[point["label"]] = (int(point["va"], 16), raw)
    for check in control_flow_checks:
        start, window = windows[check["label"]]
        offset = int(check["instruction_va"], 16) - start
        instruction = bytes.fromhex(check["instruction_bytes"])
        assert offset >= 0
        assert window[offset : offset + len(instruction)] == instruction
    for check in control_flow_checks:
        raw = bytes.fromhex(check["instruction_bytes"])
        assert int(check["instruction_va"], 16) + len(raw) + struct.unpack_from(
            "<i", raw, len(raw) - 4
        )[0] == int(check["target_va"], 16)
    expected_contract = {
        "family": "laws",
        "hook": "ai_will_do",
        "actor": "country",
        "target": "definition_only:law_type",
        "operation": "eligibility",
        "capability": "direct",
        "named_targets_proven": [],
    }
    assert data["contract"] == expected_contract
    assert len(proof.sources) == expected_sources


@pytest.mark.integration
def test_s0_known_failures_migration(
    actual_scope: vanilla_inventory.VanillaInventory,
    real_generated_branches,
) -> None:
    model = compiler.load_model()
    bundle = model.consumer_ir
    assert bundle is not None
    retired = migration_baseline.validated_retirements(bundle)
    historical = json.loads(migration_baseline.DEFAULT_SOURCE.read_bytes())
    retirement_data = json.loads(migration_baseline.RETIREMENTS_SOURCE.read_bytes())
    assert (
        _sha(migration_baseline.DEFAULT_SOURCE.read_bytes())
        == "fcce11e045e9933c13644a361da3a448330208c0b712ac3df615eed307aa55e6"
    )
    assert historical["commit"] == "74492fc05321c0767cb07202a91797a7663e7ee0"
    assert historical["tag"] == "v3.0.1"
    rules = {(w.source, w.definition): w for w in bundle.writers if w.kind == "rule_action"}
    all_ids = {(w.source, w.definition) for w in bundle.writers}
    cards = {w.definition: w for w in bundle.writers if w.kind == "action_card"}
    retirements = {
        (row["source"], row["definition"]): row for row in retirement_data["retirements"]
    }
    versioned = migration_baseline._versioned_contract()
    redirects = {
        (entry["source"], entry["definition"], entry["historical_replacement"]): entry
        for entry in versioned["replacement_redirects"]
    }
    assert len(redirects) == len(versioned["replacement_redirects"])
    assert set(redirects) == {
        (
            "common/technology/technologies/10_production.txt",
            "dough_rollers_ai_weight",
            "technology_dough_rollers_labor_ready",
        )
    }
    current_native = config.GAME / versioned["source"]
    assert _sha(current_native.read_bytes()) == versioned["source_sha256"]
    for field, expected_hash in versioned["retentions"].items():
        assert _native_field_hash(current_native, versioned["definition"], field) == expected_hash
    current_school_replacements = migration_baseline._school_network_replacements(
        versioned, bundle.writers
    )
    school = versioned["school_policy_migration"]
    assert school["successor"] == {
        "consumer": "a0-pol-schools",
        "action": "school-investment",
        "source": "game/common/ai_strategies/00_default_strategy.txt",
        "definition": "ai_strategy_default",
        "field": ["institution_scores", "institution_schools"],
        "actor": "root",
        "actor_scope": "country",
        "target": "institution_schools",
        "operation": "add",
    }
    assert len(current_school_replacements) == 36
    assert len(retirements) == len(retirement_data["retirements"])
    assert retired == set(retirements)
    expected_rows = []
    observed_rows = []
    for row in historical["rules"]:
        identity = (row["source"], row["definition"])
        expected = {field: row[field] for field in FIELDS}
        if identity in retirements:
            assert identity not in all_ids
            retirement = retirements[identity]
            assert {field: retirement[field] for field in FIELDS} == expected
            if "native_retention" in retirement:
                assert retirement["replacements"] == []
                assert retirement["native_retention"]["business_complete"] is False
                evidence = retirement["native_retention"]
                assert (
                    _native_field_hash(current_native, evidence["definition"], evidence["field"])
                    == evidence["ast_sha256"]
                )
                assert (
                    _native_field_hash(
                        decisions.product_path() / "common/ai_strategies/00_default_strategy.txt",
                        evidence["definition"],
                        evidence["field"],
                    )
                    == evidence["ast_sha256"]
                )
                expected_rows.append({**expected, "disposition": "native_retention"})
                observed_rows.append(
                    {
                        **{field: retirement[field] for field in FIELDS},
                        "disposition": "native_retention",
                    }
                )
            else:
                for replacement in retirement["replacements"]:
                    if (*identity, replacement) in current_school_replacements:
                        # Historical multiplier identity is preserved in the
                        # receipt; its actual successor is an additive R2
                        # action, independently validated above. No legacy
                        # rule with the replacement name may remain active.
                        assert row["source"] == "mod/decisions/information.toml"
                        assert row["field"] == "institution_scores.institution_schools"
                        assert row["operation"] == "multiply"
                        assert (row["source"], replacement) not in all_ids
                        continue
                    redirect = redirects.get((row["source"], row["definition"], replacement))
                    current_replacement = replacement
                    if redirect is not None:
                        assert {
                            field: redirect[field] for field in FIELDS if field != "definition"
                        } == {field: row[field] for field in FIELDS if field != "definition"}
                        current_replacement = redirect["current_replacement"]
                        assert (row["source"], replacement) not in all_ids
                    writer = rules[(row["source"], current_replacement)]
                    assert {
                        field: getattr(writer, field) for field in FIELDS if field != "definition"
                    } == {field: row[field] for field in FIELDS if field != "definition"}
                    assert writer.owner.strip()
                    assert writer.vanilla_tail == TAIL
                expected_rows.append({**expected, "disposition": "replaced"})
                observed_rows.append(
                    {**{field: retirement[field] for field in FIELDS}, "disposition": "replaced"}
                )
        else:
            writer = rules[identity]
            expected_rows.append({**expected, "disposition": "retained_identity"})
            observed_rows.append(
                {
                    **{field: getattr(writer, field) for field in FIELDS},
                    "disposition": "retained_identity",
                }
            )
    assert len(expected_rows) == 1401
    assert expected_rows == observed_rows, "all-1401-historical-rule-contracts"
    expected_cards = [
        ("diplomatic_opening", "recklessness", "add"),
        ("diplomatic_restraint", "recklessness", "add"),
        ("education_and_research", "economic_vs_government_spending_balance", "add"),
        ("fiscal_recovery", "diplomatic_play_neutrality", "add"),
        ("industrial_foundation", "economic_vs_government_spending_balance", "add"),
        ("political_reform", "change_law_chance", "add"),
        ("wartime_defense", "diplomatic_play_neutrality", "add"),
    ]
    assert [
        (row["definition"], row["field"], row["operation"]) for row in historical["cards"]
    ] == expected_cards
    assert [
        (name, cards[name].field, cards[name].operation) for name, _, _ in expected_cards
    ] == expected_cards
    source = "common/ai_strategies/00_default_strategy.txt"
    expected_replacements = [
        "military_capacity_ship_need",
        "military_capacity_ship_funded",
        "military_capacity_ship_default_cost",
        "military_capacity_ship_liquidity_cost",
    ]
    row = retirements[(source, "ai_strategy_default_ship_construction_output_multiplier")]
    assert row["replacements"] == expected_replacements
    assert [
        rules[(source, name)].definition for name in expected_replacements
    ] == expected_replacements
    native = retirements[("mod/decisions/information.toml", "colonial_projection_capacity")][
        "native_retention"
    ]
    expected_ast = "4a4a4342151af33b74989498b00e2bd840da9e60862680b47ecbf17e7a4564ba"
    assert native["business_complete"] is False
    assert native["ast_sha256"] == expected_ast
    assert (
        _native_field_hash(decisions.product_path() / source, native["definition"], native["field"])
        == expected_ast
    )
    _known_failure_observations(real_generated_branches)
