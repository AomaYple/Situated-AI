"""Independent profile boundary checks; native behavior is not simulated."""

from __future__ import annotations

import hashlib
import json
import shutil
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import production_profile as profile
from pdx.situated.decision_ir import (
    ConsumerIRBundle,
    ContextBinding,
    LegacyDecisionIR,
    WriterDecisionIR,
)

GAME = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Victoria 3")


def _at_line(prefix: str, line: int, body: str, suffix: str) -> bytes:
    return (prefix + "\n" * (line - prefix.count("\n") - 1) + body + suffix).encode()


@pytest.fixture
def installation(tmp_path: Path) -> tuple[Path, Path]:
    source = profile.DECLARATION.read_text(encoding="utf-8")
    data = tomllib.loads(source)
    raw: dict[str, bytes] = {}
    for item in data["identity"]:
        if item["path"].endswith("launcher-settings.json"):
            raw[item["path"]] = json.dumps({"rawVersion": "1.15.0"}).encode()
        else:
            raw[item["path"]] = (item["value"] + "\n").encode()
    raw["game/common/decrees/00_decree.txt"] = _at_line(
        "decree_road_maintenance = {\n", 22, "ai_weight = { value = 25 }\n", "}\n"
    )
    raw["game/common/ai_strategies/00_default_strategy.txt"] = _at_line(
        "ai_strategy_default = {\ninstitution_scores = {\n",
        1598,
        "institution_schools = { value = 10 }\n",
        "}\n}\n",
    )
    raw["game/common/diplomatic_actions/00_relations_actions.txt"] = _at_line(
        "increase_relations = {\nai = {\n", 92, "propose_score = { value = 5 }\n", "}\n}\n"
    )
    raw["game/common/ai_strategies/03_political_strategies.txt"] = (
        b"strategy = { institution_scores = { institution_schools = { value = 100 } } }\n"
    )
    for item in (*data["identity"], *data["input"]):
        rel = item["path"]
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw[rel])
        source = source.replace(item["sha256"], hashlib.sha256(raw[rel]).hexdigest())
    declaration = tmp_path / "architecture_115.toml"
    declaration.write_text(source, encoding="utf-8", newline="\n")
    return tmp_path, declaration


@pytest.fixture
def frozen_native_copy(tmp_path: Path) -> Path:
    """Real reviewed native bytes, explicitly not a newly verified installation."""
    destination = tmp_path / "native-input"
    shutil.copytree(profile.BASELINE_ROOT, destination)
    profile.verify_baseline(destination)
    return destination


def test_capture_baseline_reproduces_complete_real_native_bytes(frozen_native_copy, tmp_path):
    destination = tmp_path / "captured"
    expected = profile.verify_baseline(frozen_native_copy)
    manifest = profile.capture_baseline(frozen_native_copy, destination)
    assert manifest == expected == profile.verify_baseline(destination)
    assert profile.load_profile(destination) == profile.load_profile(frozen_native_copy)
    assert (destination / "baseline-manifest.json").read_bytes() == (
        frozen_native_copy / "baseline-manifest.json"
    ).read_bytes()
    expected_paths = {item["path"] for item in manifest["files"]}
    assert {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    } == expected_paths | {"baseline-manifest.json"}
    for relative in expected_paths:
        assert (destination / relative).read_bytes() == (frozen_native_copy / relative).read_bytes()
    assert not destination.with_name(destination.name + ".staging").exists()


@pytest.mark.parametrize("existing", ["destination", "staging"])
def test_capture_baseline_refuses_existing_paths_without_removing_bytes(
    frozen_native_copy, tmp_path, existing
):
    destination = tmp_path / "captured"
    protected = destination if existing == "destination" else tmp_path / "captured.staging"
    protected.mkdir()
    marker = protected / "user-evidence.txt"
    marker.write_bytes(b"existing evidence must survive\n")
    with pytest.raises(ValueError, match="已存在"):
        profile.capture_baseline(frozen_native_copy, destination)
    assert marker.read_bytes() == b"existing evidence must survive\n"
    assert {path.name for path in protected.iterdir()} == {"user-evidence.txt"}
    if existing == "staging":
        assert not destination.exists()


def test_capture_baseline_rejects_changed_input_before_creating_output(
    frozen_native_copy, tmp_path
):
    source = frozen_native_copy / "game/common/decrees/00_decree.txt"
    source.write_bytes(source.read_bytes() + b"\n# input drift\n")
    destination = tmp_path / "captured"
    with pytest.raises(ValueError, match="SHA-256 漂移"):
        profile.capture_baseline(frozen_native_copy, destination)
    assert not destination.exists()
    assert not (tmp_path / "captured.staging").exists()


def test_capture_baseline_verifies_copied_bytes_before_publishing(
    frozen_native_copy, tmp_path, monkeypatch
):
    copyfile = shutil.copyfile

    def corrupt_copy(source, target):
        result = copyfile(source, target)
        if Path(target).name == "00_decree.txt":
            path = Path(target)
            path.write_bytes(path.read_bytes() + b"\n# raced copy\n")
        return result

    monkeypatch.setattr(shutil, "copyfile", corrupt_copy)
    destination = tmp_path / "captured"
    with pytest.raises(ValueError, match="manifest hash 与独立声明不一致"):
        profile.capture_baseline(frozen_native_copy, destination)
    assert not destination.exists()
    assert not (tmp_path / "captured.staging").exists()


def _bundle(loaded: profile.ProductionProfile, *, semantic: bool = True) -> ConsumerIRBundle:
    writers = []
    for declaration, consumer in zip(loaded.declarations, loaded.contracts.consumers, strict=True):
        legacy = LegacyDecisionIR(
            action_id=declaration.id,
            source=declaration.source,
            definition=declaration.definition,
            domain=declaration.domain,
            consumer_id=declaration.id,
            field=".".join(declaration.field),
            actor=declaration.actor,
            target=declaration.target,
            operation="add",
            value=0.0,
            predicates=(),
            vanilla_tail="retain_original_qualification_cost_random_execution",
        )
        writers.append(
            WriterDecisionIR(
                writer_id=declaration.id,
                kind="rule_action",
                source=declaration.source,
                definition=declaration.definition,
                consumer_id=declaration.id,
                field=".".join(declaration.field),
                actor=declaration.actor,
                target=declaration.target,
                operation="add",
                vanilla_tail="retain_original_qualification_cost_random_execution",
                owner=declaration.domain,
                legacy=legacy if semantic else None,
                evaluation_context=consumer.context,
            )
        )
    return ConsumerIRBundle(1, (), tuple(writers))


def test_profile_loads_exact_scopes_and_retains_existing_ir(installation):
    root, declaration = installation
    loaded = profile.load_profile(root, declaration)
    road, schools, relations = loaded.contracts.consumers
    assert road.context.actor_scope is not None
    assert (
        road.context.actor_scope.name,
        road.context.targets[0].name,
        road.context.targets[0].kind,
    ) == ("country", "root", "state")
    assert schools.context.targets[0].kind == "institution"
    assert "additive_other_strategies" in schools.vanilla_tail
    assert relations.context.targets[0].name == "target_country"
    assert loaded.build_id.startswith("caligula:633854")
    bundle = _bundle(loaded)
    attachment = profile.attach_profile(bundle, loaded)
    assert attachment.bundle is bundle
    assert attachment.production_connected
    assert "bilateral-relations" not in {fact.id for fact in loaded.contracts.facts}


@pytest.mark.parametrize(
    "change", ["hash", "version", "unknown", "duplicate", "missing_identity", "writepoint", "tail"]
)
def test_profile_rejects_drift_and_invalid_declarations(installation, change):
    root, declaration = installation
    source = declaration.read_text(encoding="utf-8")
    if change == "hash":
        (root / "game/common/decrees/00_decree.txt").write_bytes(b"drift")
    elif change == "version":
        source = source.replace('game_version = "1.15.0"', 'game_version = "1.14.5"')
    elif change == "unknown":
        source = "not_a_field = true\n" + source
    elif change == "duplicate":
        source += '\n[[consumer]]\nid = "a0-econ-road"\n'
    elif change == "missing_identity":
        source = source.replace('path = "caligula_rev.txt"', 'path = "other_rev.txt"')
    elif change == "writepoint":
        source = source.replace('field = ["ai_weight"]', 'field = ["other_weight"]')
    elif change == "tail":
        source = source.replace('"zero_protection"', '"drop_zero"')
    declaration.write_text(source, encoding="utf-8", newline="\n")
    with pytest.raises(ValueError):
        profile.load_profile(root, declaration)


def test_profile_rejects_wrong_and_metadata_only_writers(installation):
    loaded = profile.load_profile(*installation)
    with pytest.raises(ValueError, match="未接入"):
        profile.attach_profile(_bundle(loaded, semantic=False), loaded)
    bundle = _bundle(loaded)
    for wrong in (
        replace(bundle.writers[0], actor="owner"),
        replace(bundle.writers[0], target="target_state"),
        replace(bundle.writers[0], field="other"),
        replace(bundle.writers[0], vanilla_tail="replace"),
    ):
        with pytest.raises(ValueError):
            profile.attach_profile(replace(bundle, writers=(wrong, *bundle.writers[1:])), loaded)
    with pytest.raises(ValueError):
        profile.attach_profile(ConsumerIRBundle(1, (), ()), loaded)


def test_new_context_shapes_do_not_broaden_root_type():
    ContextBinding("root", "country", "actor", "native", 1)
    ContextBinding("root", "state", "target", "native", 1)
    with pytest.raises(ValueError):
        ContextBinding("root", "state", "actor", "native", 1)


def test_policy_slice_compiles_only_observed_variants_and_preserves_native_order():
    root = profile.BASELINE_ROOT
    loaded = profile.load_profile(root)
    _, compiled = profile.compile_policy_115(loaded, root)
    assert len(compiled) == 3
    by_field = {item.consumer_programs[0].field: item for item in compiled}
    road = by_field[("ai_weight",)].consumer_programs[0]
    assert {item.action_id for item in road.variants} == {
        "road-deficit-moderate",
        "road-deficit-severe",
        "road-recovery",
    }
    assert (road.lower, road.upper) == (-2.0, 4.0)
    schools = by_field[("institution_scores", "institution_schools")].consumer_programs[0]
    assert [item.action_id for item in schools.variants] == ["schools-strategy"]
    relations = by_field[("ai", "propose_score")].consumer_programs[0]
    assert [item.action_id for item in relations.variants] == ["relations-protective"]

    outputs = profile.build_policy_115(loaded, root)
    road_text = outputs["common/decrees/00_decree.txt"]
    assert (
        road_text.index("value = 25")
        < road_text.index("SITAI POLICY")
        < road_text.index("relative_infrastructure < 1")
    )
    relations_text = outputs["common/diplomatic_actions/00_relations_actions.txt"]
    assert relations_text.index("multiply = 2") < relations_text.index("SITAI POLICY")
    for declaration in loaded.declarations:
        output = outputs[declaration.source.removeprefix("game/")]
        assert output.count(f"SITAI POLICY 1.15.0 BEGIN {declaration.id}") == 1
        restored = profile.strip_policy(output, declaration)
        raw = (root / Path(*declaration.source.split("/"))).read_bytes()
        assert restored.encode("utf-8") == raw.removeprefix(b"\xef\xbb\xbf")


def test_policy_pending_facts_fail_closed():
    variants = profile.load_policy_115()
    assert {item.id for item in variants if item.status == "pending_reproof"} == {
        "schools-low-literacy",
        "relations-hostile",
    }
    loaded = profile.load_profile(profile.BASELINE_ROOT)
    _, compiled = profile.compile_policy_115(loaded, profile.BASELINE_ROOT)
    action_ids = {
        item.action_id
        for ruleset in compiled
        for program in ruleset.consumer_programs
        for item in program.variants
    }
    assert "schools-low-literacy" not in action_ids
    assert "relations-hostile" not in action_ids


def _policy_root(text: str, consumer_id: str) -> Block:
    begin = f"# SITAI POLICY 1.15.0 BEGIN {consumer_id}"
    end = f"# SITAI POLICY 1.15.0 END {consumer_id}"
    body = text.split(begin, 1)[1].split(end, 1)[0]
    parsed = parse_text(body, path=consumer_id)
    assert not parsed.errors
    return parsed.root


def _policy_condition(block: Block, facts: dict[str, object]) -> bool:
    results: list[bool] = []
    for item in block.assignments():
        if item.key in {"exists", "country", "ROOT"}:
            results.append(bool(facts.get("ai", False)))
        elif item.key == "AND":
            assert isinstance(item.value, Block)
            results.append(_policy_condition(item.value, facts))
        elif item.key == "relative_infrastructure":
            assert isinstance(item.value, Scalar)
            infrastructure = facts["relative_infrastructure"]
            assert isinstance(infrastructure, (int, float))
            results.append(
                float(infrastructure) < float(item.value.text)
                if item.op == "<"
                else float(infrastructure) >= float(item.value.text)
            )
        elif item.key == "has_decree":
            results.append(bool(facts.get("has_decree", False)))
        elif item.key == "has_journal_entry":
            results.append(bool(facts.get("school_agenda", False)))
        elif item.key == "has_attitude":
            results.append(bool(facts.get("protective", False)))
        else:
            raise AssertionError(f"uncovered generated policy predicate: {item.key}")
    return all(results)


def _policy_delta(node: Block, facts: dict[str, object]) -> float:
    """Small independent interpreter for the generated policy AST only."""
    total = 0.0
    items = list(node.items)
    index = 0
    while index < len(items):
        item = items[index]
        if not isinstance(item, Assignment):
            index += 1
            continue
        if item.key in {"if", "else_if"}:
            selected = False
            while index < len(items):
                branch = items[index]
                if not isinstance(branch, Assignment) or branch.key not in {"if", "else_if"}:
                    break
                assert isinstance(branch.value, Block)
                limit = branch.value.first("limit")
                assert limit is not None
                assert isinstance(limit.value, Block)
                if not selected and _policy_condition(limit.value, facts):
                    selected = True
                    total += _policy_delta(branch.value, facts)
                index += 1
                if index >= len(items):
                    break
                next_item = items[index]
                if not isinstance(next_item, Assignment) or next_item.key != "else_if":
                    break
            continue
        if item.key == "add":
            if isinstance(item.value, Scalar):
                total += float(item.value.text)
            else:
                assert isinstance(item.value, Block)
                total += _policy_delta(item.value, facts)
        index += 1
    return total


def _native_condition(block: Block, facts: dict[str, object]) -> bool:
    """Evaluate the closed numeric subset used by the frozen native witnesses."""
    values: list[bool] = []
    for item in block.assignments():
        if item.key in {"OR", "AND"}:
            assert isinstance(item.value, Block)
            nested = [
                _native_condition(Block([child]), facts) for child in item.value.assignments()
            ]
            values.append(any(nested) if item.key == "OR" else all(nested))
        elif item.key == "relative_infrastructure":
            assert isinstance(item.value, Scalar)
            ratio = facts["relative_infrastructure"]
            assert isinstance(ratio, (int, float))
            threshold = float(item.value.text)
            values.append(float(ratio) < threshold if item.op == "<" else float(ratio) >= threshold)
        elif item.key == "has_decree":
            values.append(bool(facts.get("has_decree", False)))
        elif item.key == "has_journal_entry":
            values.append(bool(facts.get("journal", False)))
        elif item.key == "is_capital":
            values.append(bool(facts.get("capital", False)))
        elif item.key in {"exists", "country", "ROOT"}:
            values.append(bool(facts.get("ai", False)))
        elif item.key.startswith("scope:"):
            assert isinstance(item.value, Block)
            values.append(_native_condition(item.value, facts))
        elif item.key == "has_attitude":
            values.append(bool(facts.get("protective", False)))
        else:
            values.append(False)
    return all(values)


def _native_score(node: Block, facts: dict[str, object], initial: float = 0.0) -> float:
    """Evaluate native value/add/multiply/if nodes for numeric witness cases."""
    total = initial
    items = list(node.items)
    index = 0
    while index < len(items):
        item = items[index]
        if not isinstance(item, Assignment):
            index += 1
            continue
        if item.key == "value" and isinstance(item.value, Scalar):
            try:
                total = float(item.value.text)
            except ValueError:
                rank = facts.get("rank", 0)
                assert isinstance(rank, (int, float))
                total = float(rank)
        elif item.key in {"if", "else_if"}:
            selected = False
            while index < len(items):
                branch = items[index]
                if not isinstance(branch, Assignment) or branch.key not in {"if", "else_if"}:
                    break
                assert isinstance(branch.value, Block)
                limit = branch.value.first("limit")
                assert limit is not None
                assert isinstance(limit.value, Block)
                if not selected and _native_condition(limit.value, facts):
                    selected = True
                    body = Block([entry for entry in branch.value.items if entry is not limit])
                    if branch.value.first("value") is not None:
                        total += _native_score(body, facts)
                    else:
                        total = _native_score(body, facts, total)
                index += 1
                if index >= len(items):
                    break
                next_item = items[index]
                if not isinstance(next_item, Assignment) or next_item.key != "else_if":
                    break
            continue
        elif item.key in {"add", "multiply"}:
            if isinstance(item.value, Scalar):
                amount = float(item.value.text)
            elif isinstance(item.value, Block):
                amount = _native_score(item.value, facts)
            else:
                amount = 0.0
            total = total + amount if item.key == "add" else total * amount
        index += 1
    return total


def _consumer_block(text: str, keys: tuple[str, ...]) -> Block:
    parsed = parse_text(text, path="native-witness")
    assert not parsed.errors
    current = parsed.root
    for key in keys:
        assignment = current.first(key)
        assert assignment is not None
        assert isinstance(assignment.value, Block)
        current = assignment.value
    return current


def test_generated_policy_ast_witnesses_numeric_overlay_and_native_order():
    loaded = profile.load_profile(profile.BASELINE_ROOT)
    outputs = profile.build_policy_115(loaded, profile.BASELINE_ROOT)
    road = _policy_root(outputs["common/decrees/00_decree.txt"], "a0-econ-road")
    assert _policy_delta(road, {"ai": True, "relative_infrastructure": 0.2}) == 4
    assert _policy_delta(road, {"ai": True, "relative_infrastructure": 0.4}) == 2
    assert (
        _policy_delta(road, {"ai": True, "relative_infrastructure": 0.8, "has_decree": True}) == -2
    )
    assert _policy_delta(road, {"ai": True, "relative_infrastructure": 0.8}) == 0
    assert _policy_delta(road, {"ai": False, "relative_infrastructure": 0.2}) == 0
    road_text = outputs["common/decrees/00_decree.txt"]
    assert road_text.index("SITAI POLICY") < road_text.index("relative_infrastructure >= 1.25")
    assert road_text.index("relative_infrastructure >= 1.25") < road_text.index("multiply = 0")

    schools = _policy_root(
        outputs["common/ai_strategies/00_default_strategy.txt"], "a0-pol-schools"
    )
    assert _policy_delta(schools, {"ai": True, "school_agenda": True}) == 2
    assert _policy_delta(schools, {"ai": True, "school_agenda": False}) == 0
    schools_text = outputs["common/ai_strategies/00_default_strategy.txt"]
    assert "institution_police = {\n\t\t\tvalue = 10" in schools_text

    relations = _policy_root(
        outputs["common/diplomatic_actions/00_relations_actions.txt"], "a0-dip-relations"
    )
    assert _policy_delta(relations, {"ai": True, "protective": True}) == 2
    assert _policy_delta(relations, {"ai": True, "protective": False}) == 0
    assert _policy_delta(relations, {"ai": False, "protective": True}) == 0
    relations_text = outputs["common/diplomatic_actions/00_relations_actions.txt"]
    assert relations_text.index("multiply = 2") < relations_text.index("SITAI POLICY")
    assert "add = 5" in relations_text


def test_generated_policy_ast_witnesses_complete_native_numeric_result():
    loaded = profile.load_profile(profile.BASELINE_ROOT)
    outputs = profile.build_policy_115(loaded, profile.BASELINE_ROOT)
    road_keys = ("decree_road_maintenance", "ai_weight")
    road_cases = (
        ({"ai": True, "relative_infrastructure": 0.2}, 329),
        ({"ai": True, "relative_infrastructure": 0.4}, 227),
        ({"ai": True, "relative_infrastructure": 0.8, "has_decree": True}, 123),
        ({"ai": True, "relative_infrastructure": 1.3}, 0),
    )
    for facts, expected in road_cases:
        node = _consumer_block(outputs["common/decrees/00_decree.txt"], road_keys)
        witness_facts: dict[str, object] = dict(facts)
        assert _native_score(node, witness_facts) == expected


@pytest.mark.skipif(not GAME.is_dir(), reason="requires actual 1.15 installation")
def test_actual_installation_profile_smoke():
    loaded = profile.load_profile(GAME)
    assert loaded.game_version == "1.15.0"
    assert len(loaded.source_hashes) == 10
    assert len(loaded.registry.manifests) == 3
