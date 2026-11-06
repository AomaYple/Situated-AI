"""Small independent lossless projection fixtures; never scans an installation."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from tools.ci import a4_discovery as discovery
from tools.ci import a4_scope as gate


def captured_fixture() -> dict:
    sources = ["common/sample/example.txt", "events/example.txt", "dlc/example/example.dlc"]
    hashes = {source: discovery.digest(source) for source in sources}
    definitions, surfaces, slots, options = [], [], [], []
    syntax = {}

    def scalar(text, line):
        return {"kind": "scalar", "text": text, "line": line, "quoted": False}

    def block(items, line):
        return {"kind": "block", "line": line, "items": items}

    def assignment(key, value, line):
        return {
            "kind": "assignment",
            "key": key,
            "operator": "=",
            "prefix": None,
            "value": value,
            "line": line,
        }

    def retain(source, tree):
        stack: list[tuple[dict[str, Any], tuple[int, ...]]] = [(tree, ())]
        count = 0
        while stack:
            node, position = stack.pop()
            count += 1
            node.update(node_position=list(position), node_id=discovery.digest((source, position)))
            if node["kind"] == "assignment":
                stack.append((node["value"], (*position, -1)))
            elif node["kind"] == "block":
                stack.extend(
                    (child, (*position, index)) for index, child in enumerate(node["items"])
                )
        text = discovery.encoded(tree).decode()
        syntax[source] = {
            "syntax_json": text,
            "syntax_sha256": discovery.sha(text.encode()),
            "source_sha256": hashes[source],
            "node_count": count,
        }

    common = sources[0]
    for index, name in enumerate(("empty", "data")):
        definitions.append(
            {
                "declaration_id": discovery.digest((common, name, 1)),
                "source": common,
                "directory": "sample",
                "definition": name,
                "definition_index": index,
                "source_line": index + 1,
                "declaration_occurrence": 1,
                "operator": "=",
                "prefix": None,
                "is_block": True,
                "surface_declaration_ids": [],
            }
        )
    retain(
        common,
        block(
            [
                assignment("empty", block([], 1), 1),
                assignment("data", block([scalar("unknown_bare", 3)], 2), 2),
            ],
            1,
        ),
    )
    event_items = []
    occurrence = 0
    for index, weights in enumerate(([5, 6], [])):
        line = index * 10 + 1
        owner = discovery.digest((sources[1], "duplicated_event", index + 1))
        members = []
        event_surfaces = []
        for _ in range(max(1, len(weights))):
            occurrence += 1
            identity = discovery.digest(
                (sources[1], "duplicated_event", "option.ai_chance", occurrence)
            )
            members.append(identity)
            surface_id = discovery.digest((identity, "unverified"))
            event_surfaces.append(surface_id)
            surfaces.append(
                {
                    "declaration_id": identity,
                    "surface_id": surface_id,
                    "source": sources[1],
                    "definition": "duplicated_event",
                    "field": "option.ai_chance",
                    "declaration_occurrence": occurrence,
                    "legal": False,
                    "capability": "pending",
                    "status": "pending",
                    "getter": None,
                    "scope_evidence": [],
                    "ambiguity": "duplicate_field_merge_semantics_unknown",
                }
            )
        definitions.append(
            {
                "declaration_id": owner,
                "source": sources[1],
                "directory": "events",
                "definition": "duplicated_event",
                "definition_index": index,
                "source_line": line,
                "declaration_occurrence": index + 1,
                "operator": "=",
                "prefix": None,
                "is_block": True,
                "surface_declaration_ids": members,
            }
        )
        slots.append(
            {
                "slot_id": discovery.digest((owner, 0)),
                "owner_declaration_id": owner,
                "owner_definition_index": index,
                "owner_declaration_occurrence": index + 1,
                "source": sources[1],
                "definition": "duplicated_event",
                "option_index": 0,
                "source_line": line + 1,
                "surface_declaration_ids": members,
                "surface_ids": event_surfaces,
                "ambiguities": ["duplicate"],
            }
        )
        options.append(
            {
                "source": sources[1],
                "definition": "duplicated_event",
                "option_index": 0,
                "source_line": line + 1,
                "weight_lines": weights,
                "option_name": None,
            }
        )
        event_items.append(
            assignment(
                "duplicated_event",
                block(
                    [
                        assignment(
                            "option",
                            block(
                                [
                                    assignment("ai_chance", scalar("1", weight), weight)
                                    for weight in weights
                                ],
                                line + 1,
                            ),
                            line + 1,
                        )
                    ],
                    line,
                ),
                line,
            )
        )
    retain(sources[1], block(event_items, 1))
    retain(sources[2], block([assignment("name", scalar("dlc", 1), 1)], 1))
    return {
        "target_version": "1.15.0",
        "actual_version": {"caligula_branch": "release/1.15.0"},
        "authorization": "none",
        "discovery_mode": "unverified",
        "baseline_id": "victoria3-1.15.0:" + discovery.digest(hashes),
        "source_hashes": hashes,
        "scope_hash": discovery.digest("fixture capture"),
        "definitions": definitions,
        "surfaces": surfaces,
        "references": [
            {"reference_id": "ref-physical", "source": common, "line": 3, "expression": "x"}
        ],
        "event_slots": slots,
        "event_options": options,
        "source_syntax": syntax,
        "unsupported_structures": [
            {"source": common, "syntax": {"kind": "scalar", "text": "unknown_bare"}}
        ],
        "scanned_directories": ["common/sample", "events", "dlc"],
        "parse_failures": [],
    }


def test_projection_preserves_physical_and_bare_members() -> None:
    raw = captured_fixture()
    projected = discovery.project(raw)
    assert projected["node_count"] == sum(
        value["node_count"] for value in raw["source_syntax"].values()
    )
    assert sum(":slot:" in group for group in projected["groups"]) == 2
    assert sum(entry["kind"] == "surface" for entry in projected["entries"].values()) == 3
    assert sum(entry["kind"] == "definition" for entry in projected["entries"].values()) == 4
    assert sum(entry["kind"] == "unclassified" for entry in projected["entries"].values()) == 1
    assert len(projected["raw_duplicates"]) == 4
    assert set(projected["unresolved_groups"]) == set(projected["groups"])
    assert projected["dlc_ids"] == ["dlc/example/example.dlc"]


@pytest.mark.parametrize(
    "change",
    [
        "empty_definition",
        "owner",
        "slot_weight",
        "syntax_member",
        "mixed_version",
        "native_authority",
        "duplicate_id",
        "source",
    ],
)
def test_projection_rejects_omissions_and_false_ownership(change) -> None:
    raw = captured_fixture()
    if change == "empty_definition":
        raw["definitions"].pop(0)
    elif change == "owner":
        raw["event_slots"][0]["owner_declaration_id"] = "missing"
    elif change == "slot_weight":
        raw["event_slots"][0]["surface_declaration_ids"].pop()
    elif change == "syntax_member":
        item = next(iter(raw["source_syntax"].values()))
        item["node_count"] -= 1
    elif change == "mixed_version":
        raw["actual_version"]["caligula_branch"] = "release/1.14.5"
    elif change == "native_authority":
        raw["surfaces"][0]["legal"] = True
    elif change == "duplicate_id":
        raw["references"].append(copy.deepcopy(raw["references"][0]))
    else:
        raw["source_hashes"].pop(next(iter(raw["source_hashes"])))
    with pytest.raises(ValueError):
        discovery.project(raw)


@pytest.fixture
def imported(tmp_path, monkeypatch):
    for path in discovery.PROJECTOR_INPUTS:
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        names = [
            node.split("::")[1]
            for node in discovery.CROSSCHECK_NODES
            if node.split("::")[0] == path
        ]
        destination.write_text(
            "\n".join(f"def {name}():\n    pass\n" for name in names) or "# controlled fixture\n",
            encoding="utf8",
        )
    capture = tmp_path / "fixed.json"
    capture.write_bytes(discovery.encoded(captured_fixture()))
    identity = discovery.sha(capture.read_bytes())
    monkeypatch.setattr(discovery, "CAPTURE_SHA256", identity)
    discovery.import_capture(tmp_path, capture, expected_sha256=identity)
    return tmp_path, capture, identity


def test_import_is_deterministic_and_offline(imported) -> None:
    root, capture, identity = imported
    before = {
        path.relative_to(root).as_posix(): discovery.sha(path.read_bytes())
        for path in (root / discovery.DIRECTORY).rglob("*")
        if path.is_file()
    }
    discovery.import_capture(root, capture, expected_sha256=identity)
    after = {
        path.relative_to(root).as_posix(): discovery.sha(path.read_bytes())
        for path in (root / discovery.DIRECTORY).rglob("*")
        if path.is_file()
    }
    assert before == after
    sources = gate.Sources(root)
    report = sources.json(discovery.REPORT_PATH)
    assert discovery.validate_projection(sources, report)["node_count"] > 0
    assert not (root / ".venv").exists()


@pytest.mark.parametrize(
    "change",
    [
        "catalog",
        "report",
        "inputs",
        "missing_shard",
        "shard_corrupt",
        "root_version",
        "code",
        "cycle",
        "raw_hash",
    ],
)
def test_archive_catalog_report_closure_failures(imported, change) -> None:
    root, _, _ = imported
    sources = gate.Sources(root)
    report = copy.deepcopy(sources.json(discovery.REPORT_PATH))
    manifest = sources.json(discovery.ROOT_PATH)
    if change == "catalog":
        catalog = sources.json(discovery.CATALOG_PATH)
        catalog["entries"].pop(next(iter(catalog["entries"])))
        discovery.write_json(root / discovery.CATALOG_PATH, catalog)
    elif change == "report":
        report["discoveries"].pop()
    elif change == "inputs":
        report["source_inputs"].pop()
    elif change == "missing_shard":
        manifest["shards"] = []
        discovery.write_json(root / discovery.ROOT_PATH, manifest)
    elif change == "shard_corrupt":
        (root / manifest["shards"][0]["path"]).write_bytes(b"corrupt")
    elif change == "root_version":
        manifest["source_version"] = "1.14.5"
        discovery.write_json(root / discovery.ROOT_PATH, manifest)
    elif change == "code":
        (root / discovery.PROJECTOR_INPUTS[0]).write_text("# drift\n", encoding="utf8")
    elif change == "cycle":
        manifest["shards"][0]["path"] = discovery.ROOT_PATH
        discovery.write_json(root / discovery.ROOT_PATH, manifest)
    else:
        manifest["raw_sha256"] = "0" * 64
        discovery.write_json(root / discovery.ROOT_PATH, manifest)
    with pytest.raises(ValueError):
        discovery.validate_projection(gate.Sources(root), report)


def test_bounded_archives_and_duplicate_json_keys() -> None:
    with pytest.raises(ValueError, match="duplicate JSON key"):
        discovery.strict_json('{"same":1,"same":2}')
    with pytest.raises(ValueError, match="oversized"):
        discovery.unpack(discovery.pack(b"x" * 1024), 2)
    with pytest.raises(ValueError, match="oversized"):
        discovery.unpack(b"x", discovery.CHUNK_BYTES + 1)
    with pytest.raises(ValueError, match="corrupt"):
        discovery.unpack(b"not gzip", 2)
