"""Independent profile boundary checks; native behavior is not simulated."""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from pdx import config, version_contracts
from pdx.situated import production_profile as profile
from pdx.situated.decision_ir import (
    ConsumerIRBundle,
    ContextBinding,
    LegacyDecisionIR,
    WriterDecisionIR,
)

if TYPE_CHECKING:
    from pathlib import Path

GAME = config.ROOT


def _at_line(prefix: str, line: int, body: str, suffix: str) -> bytes:
    return (prefix + "\n" * (line - prefix.count("\n") - 1) + body + suffix).encode()


@pytest.fixture
def installation(tmp_path: Path) -> tuple[Path, Path]:
    source = profile.declaration_path().read_text(encoding="utf-8")
    data = tomllib.loads(source)
    raw: dict[str, bytes] = {}
    for item in data["identity"]:
        if item["path"].endswith("launcher-settings.json"):
            raw[item["path"]] = json.dumps(
                {"rawVersion": version_contracts.CURRENT_VERSION}
            ).encode()
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
    declaration = tmp_path / "architecture.toml"
    declaration.write_text(source, encoding="utf-8", newline="\n")
    return tmp_path, declaration


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
    assert loaded.build_id.startswith("caligula:57c82c")
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
        source = source.replace(
            f'game_version = "{version_contracts.CURRENT_VERSION}"', 'game_version = "1.14.5"'
        )
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


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ("extra_input", "必须包含三个写点及非默认学校策略来源"),
        ("replaced_input", "必须包含三个写点及非默认学校策略来源"),
        ("duplicate_path", "路径与身份重复"),
        ("duplicate_key", "无法读取严格 TOML"),
        ("unknown_field", "未知字段"),
    ],
)
def test_profile_input_declaration_rejects_unreviewed_paths_and_fields(
    installation: tuple[Path, Path], change: str, error: str
) -> None:
    root, declaration = installation
    source = declaration.read_text(encoding="utf-8")
    native_path = "game/common/decrees/00_decree.txt"
    extra_path = "game/common/decrees/unreviewed.txt"
    raw = (root / native_path).read_bytes()
    (root / extra_path).write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    reviewed_row = f'path = "{native_path}"\nsha256 = "{digest}"'
    assert source.count(reviewed_row) == 1
    extra_row = reviewed_row.replace(native_path, extra_path)
    replacement = {
        "extra_input": f"{reviewed_row}\n\n[[input]]\n{extra_row}",
        "replaced_input": extra_row,
        "duplicate_path": f"{reviewed_row}\n\n[[input]]\n{reviewed_row}",
        "duplicate_key": f'{reviewed_row}\nsha256 = "{digest}"',
        "unknown_field": f"{reviewed_row}\nunreviewed = true",
    }[change]
    declaration.write_text(
        source.replace(reviewed_row, replacement, 1), encoding="utf-8", newline="\n"
    )

    with pytest.raises(ValueError, match=error):
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


@pytest.mark.integration
@pytest.mark.skipif(not GAME.is_dir(), reason="需要当前锁定原版游戏目录")
def test_actual_installation_profile_smoke():
    loaded = profile.load_profile(GAME)
    declared = profile.declared_profile()
    assert loaded == declared
    assert loaded.game_version == version_contracts.CURRENT_VERSION
    assert len(loaded.source_hashes) == 10
    assert len(loaded.registry.manifests) == 3


@pytest.mark.parametrize("historical", ["1.15.0", "1.15.1"])
def test_current_profile_rejects_historical_installation_bytes(tmp_path, historical):
    launcher = tmp_path / "launcher/launcher-settings.json"
    launcher.parent.mkdir()
    launcher.write_text(json.dumps({"rawVersion": historical}), encoding="utf-8")
    with pytest.raises(ValueError, match=r"launcher/launcher-settings\.json.*SHA-256 漂移"):
        profile.load_profile(tmp_path)
