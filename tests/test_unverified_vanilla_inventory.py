"""Current native discovery is independent of frozen authorization proofs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from pdx.situated import vanilla_inventory as inventory

pytestmark = pytest.mark.unit


def _write(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _game(tmp_path):
    for name, value in {
        "caligula_branch": "release/1.15.0",
        "caligula_rev": "fixture-game-revision",
        "clausewitz_branch": "caligula/release/1.15.0",
        "clausewitz_rev": "fixture-engine-revision",
    }.items():
        _write(tmp_path, f"{name}.txt", value)
    game = tmp_path / "game"
    _write(
        game, "common/laws/a.txt", "law = { ai_weight = 1 ai_weight = 2 }\nlaw = { ai_weight = 3 }"
    )
    _write(game, "common/buildings/a.txt", "building = { ai_value = { value = 4 } }")
    _write(
        game,
        "common/buildings/buildings.md",
        "# base AI value\n# scope is state the building is located in\nai_value = script value\n",
    )
    _write(
        game,
        "common/ai_strategies/a.txt",
        "strategy = { cossack_score = 1 ai_ship_modification = 2 submarine_score = 3 "
        "goods_stances = { copper = { value = 4 } } }",
    )
    _write(game, "common/scripted_effects/a.txt", "effect = { ai_test = yes ai_test = yes }")
    _write(
        game,
        "events/a.txt",
        "event.1 = { option = { name = a } option = { name = b ai_chance = 2 } }",
    )
    _write(game, "dlc/a.dlc", 'path = "dlc/mounted"')
    _write(game, "dlc/mounted/events/a.txt", "event.1 = { option = { name = a } }")
    return game


def test_new_version_discovery_never_invokes_authorization_and_preserves_denominator(
    tmp_path, monkeypatch
):
    game = _game(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("unverified discovery called a frozen authorization proof")

    for name in (
        "parameter_evidence_hashes",
        "_proven_event_surfaces",
        "_scope",
        "_strategy_scopes",
        "_doc_scope",
        "_scripted_trigger_definition_scope",
    ):
        monkeypatch.setattr(inventory, name, forbidden)
    for name in (
        "technology_evidence",
        "strategy_evidence",
        "country_evidence",
        "company_evidence",
        "company_default_evidence",
        "law_evidence",
    ):
        monkeypatch.setattr(inventory.engine_scope, name, forbidden)
    result = inventory.discover_unverified(target_version="1.15.0", game=game)
    assert result.baseline_id.startswith("victoria3-1.15.0:")
    assert result.legal_count == 0
    assert result.pending_count == result.discovered_count == 11
    assert result.parsed_files == 6
    assert result.parse_failures == ()
    assert set(result.content_roots) == {"common", "events", "dlc/mounted/events"}
    assert len(result.event_options) == 3
    assert sum(not row.weight_lines for row in result.event_options) == 2
    assert len([row for row in result.references if row.expression == "ai_test"]) == 2
    assert {row.field for row in result.surfaces if row.definition == "strategy"} == {
        "cossack_score",
        "ai_ship_modification",
        "submarine_score",
        "goods_stances.copper",
    }
    assert len(result.definitions) == 7
    laws = [row for row in result.definitions if row.definition == "law"]
    assert [row.declaration_occurrence for row in laws] == [1, 2]
    assert [row.definition_index for row in laws] == [0, 1]
    assert len({row.declaration_id for row in laws}) == 2
    rows = [row for row in result.surfaces if row.definition == "law"]
    assert {row.declaration_occurrence for row in rows} == {1, 2, 3}
    assert all(row.ambiguity for row in rows)
    assert len({row.declaration_id for row in result.surfaces}) == 11
    assert {
        identity
        for definition in result.definitions
        for identity in definition.surface_declaration_ids
    } == {row.declaration_id for row in result.surfaces}
    for row in result.surfaces:
        assert (row.actor_scope, row.target_scope, row.operation) == (
            "unknown",
            "unknown",
            "declared_field",
        )
        assert row.capability == row.status == "pending"
        assert not row.scope_evidence
        assert row.getter is None
        assert not row.legal
        assert replace(row, actor_scope="country").declaration_id == row.declaration_id
    payload = result.as_dict()
    assert payload["discovery_mode"] == "unverified"
    assert payload["authorization"] == "none"
    assert payload["actual_version"]["caligula_branch"] == "release/1.15.0"
    assert payload["target_version"] == "1.15.0"
    assert "unverified" in payload["evidence"]
    assert payload["definition_count"] == 7
    assert (
        payload["source_hashes"]["common/laws/a.txt"]
        == hashlib.sha256((game / "common/laws/a.txt").read_bytes()).hexdigest()
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("caligula_branch", "release/1.14.5"),
        ("caligula_rev", ""),
        ("clausewitz_branch", "caligula/release/1.14.5"),
        ("clausewitz_rev", ""),
    ],
)
def test_unverified_discovery_rejects_wrong_or_missing_identity(tmp_path, name, value):
    game = _game(tmp_path)
    _write(tmp_path, f"{name}.txt", value)
    with pytest.raises(ValueError, match="版本"):
        inventory.discover_unverified(target_version="1.15.0", game=game)


@pytest.mark.parametrize("target", ["", "release/1.15.0", "../1.15.0", "1.15"])
def test_unverified_discovery_requires_explicit_complete_target(tmp_path, target):
    with pytest.raises(ValueError, match="目标版本"):
        inventory.discover_unverified(target_version=target, game=_game(tmp_path))


def test_unverified_discovery_rejects_malformed_sources_and_unsafe_mounts(tmp_path):
    game = _game(tmp_path)
    _write(game, "common/laws/a.txt", "law = { ai_weight = {")
    with pytest.raises(ValueError, match="解析失败"):
        inventory.discover_unverified(target_version="1.15.0", game=game)
    _write(game, "common/laws/a.txt", "law = { ai_weight = 1 }")
    _write(game, "dlc/a.dlc", 'path = "../outside"')
    with pytest.raises(ValueError, match="相对路径"):
        inventory.discover_unverified(target_version="1.15.0", game=game)


def test_unverified_discovery_reports_unsupported_root_syntax(tmp_path):
    game = _game(tmp_path)
    _write(game, "common/laws/unsupported.txt", "bare_token { nested = { ai_weight = 1 } }")
    result = inventory.discover_unverified(target_version="1.15.0", game=game)
    assert result.unsupported_structures
    assert all(
        row["source"] == "common/laws/unsupported.txt" for row in result.unsupported_structures
    )


def test_unverified_discovery_records_unclassified_strategy_maps_without_authority(tmp_path):
    game = _game(tmp_path)
    _write(
        game,
        "common/ai_strategies/new-map.txt",
        "strategy_new = { unfamiliar_policy_map = { first = { value = 1 } "
        "first = { value = 2 } bare_member } }",
    )
    result = inventory.discover_unverified(target_version="1.15.0", game=game)
    root = next(row for row in result.surfaces if row.field == "unfamiliar_policy_map")
    record = next(row for row in result.unsupported_structures if row.get("field") == root.field)
    assert record["declaration_id"] == root.declaration_id
    assert record["source"] == "common/ai_strategies/new-map.txt"
    assert record["source_line"] == 1
    assert record["kind"] == "unexpanded_strategy_structure"
    assert record["child_keys"] == ["first", "first"]
    assert [row["kind"] for row in record["syntax"]["items"]] == [
        "assignment",
        "assignment",
        "scalar",
    ]
    assert record["syntax"]["items"][1]["value"]["items"][0]["value"]["text"] == "2"
    assert root.capability == "pending"
    assert not root.legal


def test_verified_discovery_still_rejects_current_version(tmp_path):
    with pytest.raises(ValueError, match=r"1\.14\.5"):
        inventory.discover(game=_game(tmp_path))


def test_unverified_and_verified_discovery_preserve_the_same_declaration_identities(tmp_path):
    game = _game(tmp_path)
    _write(tmp_path, "caligula_branch.txt", "release/1.14.5")
    _write(tmp_path, "clausewitz_branch.txt", "caligula/release/1.14.5")
    verified = inventory.discover(game=game)
    unverified = inventory.discover_unverified(target_version="1.14.5", game=game)
    assert {row.declaration_id for row in verified.surfaces} == {
        row.declaration_id for row in unverified.surfaces
    }
    assert verified.legal_count > 0
    assert unverified.legal_count == 0
    assert verified.scope_hash != unverified.scope_hash


def test_unverified_discovery_rejects_absent_version_file(tmp_path):
    game = _game(tmp_path)
    (tmp_path / "caligula_rev.txt").unlink()
    with pytest.raises(ValueError, match="版本指纹缺失"):
        inventory.discover_unverified(target_version="1.15.0", game=game)


@pytest.mark.parametrize(
    ("source", "text", "container"),
    [
        (
            "common/ai_strategies/known-map.txt",
            "strategy = { goods_stances = { copper = { value = 1 } bare_member } }",
            "goods_stances",
        ),
        (
            "common/buildings/unknown-map.txt",
            (
                "building = { ai_new_map = { first = { value = 1 } "
                "first = { value = 2 } bare_member } }"
            ),
            "ai_new_map",
        ),
    ],
)
def test_every_candidate_structure_retains_full_syntax_even_when_frontier_does_not_expand_it(
    tmp_path, source, text, container
):
    game = _game(tmp_path)
    _write(game, source, text)
    result = inventory.discover_unverified(target_version="1.15.0", game=game)
    retained = result.source_syntax[source]
    assert retained["source_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    syntax = json.loads(retained["syntax_json"])
    assert retained["syntax_sha256"] == hashlib.sha256(retained["syntax_json"].encode()).hexdigest()
    candidate = next(row for row in syntax["items"][0]["value"]["items"] if row["key"] == container)
    members = candidate["value"]["items"]
    assert members[-1]["text"] == "bare_member"
    assert members[-1]["node_position"] == [0, -1, 0, -1, len(members) - 1]
    assert len({row["node_id"] for row in members}) == len(members)
    if container == "ai_new_map":
        assert [row["key"] for row in members[:-1]] == ["first", "first"]
        assert [row["value"]["items"][0]["value"]["text"] for row in members[:-1]] == ["1", "2"]
    assert result.as_dict()["source_syntax"][source] == retained
    assert result.legal_count == 0


def test_top_level_repeated_bare_nodes_retain_order_identity_and_nested_syntax(tmp_path):
    game = _game(tmp_path)
    source = "common/laws/bare-nodes.txt"
    _write(game, source, "bare bare { nested = { unexpected unexpected } }")
    result = inventory.discover_unverified(target_version="1.15.0", game=game)
    syntax = json.loads(result.source_syntax[source]["syntax_json"])
    assert [row["node_position"] for row in syntax["items"]] == [[0], [1], [2]]
    assert syntax["items"][0]["text"] == syntax["items"][1]["text"] == "bare"
    assert syntax["items"][0]["node_id"] != syntax["items"][1]["node_id"]
    assert [row["text"] for row in syntax["items"][2]["items"][0]["value"]["items"]] == [
        "unexpected",
        "unexpected",
    ]


@pytest.mark.parametrize(
    ("second_weights", "counts"),
    [("", (1, 1)), ("ai_chance = 1 ai_chance = 2", (1, 2))],
)
def test_duplicate_same_line_event_slots_have_distinct_stable_owners_and_all_weight_surfaces(
    tmp_path, second_weights, counts
):
    game = _game(tmp_path)
    source = "events/duplicate.txt"
    _write(
        game,
        source,
        f"e.1 = {{ option = {{ name = a }} }} e.1 = {{ option = {{ name = a {second_weights} }} }}",
    )
    result = inventory.discover_unverified(target_version="1.15.0", game=game)
    slots = [row for row in result.event_slots if row.source == source]
    owners = [row for row in result.definitions if row.source == source]
    assert len(slots) == 2
    assert len({row.slot_id for row in slots}) == 2
    assert [row.owner_declaration_id for row in slots] == [row.declaration_id for row in owners]
    assert [row.owner_declaration_occurrence for row in slots] == [1, 2]
    assert [row.owner_definition_index for row in slots] == [0, 1]
    assert tuple(len(row.surface_declaration_ids) for row in slots) == counts
    assert all(
        "duplicate_event_definition_merge_semantics_unknown" in row.ambiguities for row in slots
    )
    if second_weights:
        assert "duplicate_event_option_ai_chance" in slots[1].ambiguities
    surfaces = {row.declaration_id: row for row in result.surfaces}
    for slot, owner in zip(slots, owners, strict=True):
        assert slot.surface_declaration_ids == owner.surface_declaration_ids
        assert slot.surface_ids == tuple(
            surfaces[row].surface_id for row in slot.surface_declaration_ids
        )
    first_id = slots[0].slot_id
    assert replace(slots[0], surface_ids=("different-semantic-id",)).slot_id == first_id
    _write(game, source, "\n" + (game / source).read_text(encoding="utf-8"))
    second = inventory.discover_unverified(target_version="1.15.0", game=game)
    assert [row.slot_id for row in second.event_slots if row.source == source] == [
        row.slot_id for row in slots
    ]
    assert len(result.as_dict()["event_slots"]) == len(result.event_options)
