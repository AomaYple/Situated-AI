"""标准候选必须携带实际使用的共享策略来源，而不是无消费者的设计声明。"""

import hashlib
import json
from pathlib import Path

import pytest

from pdx import decision_intents, distribution
from pdx.situated import pdx_eval


@pytest.mark.integration
def test_release_freezes_shared_strategy_and_actual_consumers():
    _, _, files = distribution.package_inputs(include_engineering_metadata=True)
    metadata = json.loads(files[".metadata/metadata.json"])
    strategy = decision_intents.load()
    contract = metadata["strategic_coordination"]
    assert contract["runtime_state"] == "none"
    assert contract["source_sha256"] == strategy.source_sha256
    assert {row["id"] for row in contract["intents"]} == {intent.id for intent in strategy.intents}
    fingerprint = metadata["source_fingerprint"]
    assert (
        fingerprint["strategic_source_sha256"]
        == hashlib.sha256(decision_intents.SOURCE.read_bytes()).hexdigest()
    )
    assert (
        fingerprint["strategic_generator_sha256"]
        == hashlib.sha256(Path(decision_intents.__file__).read_bytes()).hexdigest()
    )
    assert metadata["version"] == distribution.RELEASE_VERSION
    values_path = "common/script_values/sitai_adapter_values.txt"
    assert (
        "protect_supply = sitai_adapter_fleet_supply_weight"
        in files["common/ai_strategies/00_default_strategy.txt"]
    )
    assert "sitai_adapter_fleet_supply_weight = { value = 1.0" in files[values_path]
    fleet_field = (
        "ai_strategy_default.fleet_compositions.secondary_fleet.mission_type_weights.protect_supply"
    )
    program = (
        "program_"
        + hashlib.sha256(
            f"common/ai_strategies/00_default_strategy.txt:{fleet_field}".encode()
        ).hexdigest()[:16]
    )
    script = files[values_path]
    assert isinstance(script, str)
    overlay = pdx_eval.marked_block(script, program)
    actual = pdx_eval.select(
        overlay,
        {
            "ROOT": {
                "is_ai": True,
                "is_at_war": True,
                "navy_size": 1,
                "market": {"mg:steamers": {"market_goods_pricier": 0.3, "market_goods_delta": -1}},
            }
        },
    )
    assert actual.operation == "multiply"
    assert actual.delta == pytest.approx(1.25)
    assert contract["behavior_verified"] is False
    assert contract["rules_with_intent"] > len(strategy.intents)


@pytest.mark.integration
def test_release_is_the_public_full_candidate():
    _, _, files = distribution.package_inputs(include_engineering_metadata=True)
    metadata = json.loads(files[".metadata/metadata.json"])
    assert metadata["version"] == distribution.RELEASE_VERSION
    assert metadata["status"] == "candidate"
    assert set(metadata["enabled_modules"]) == {
        "fiscal",
        "reform",
        "market",
        "security",
        "economy",
        "diplomacy",
        "information_rules",
        "consumer_adapters",
        "country_state",
    }
    assert metadata["localization"]["fallback_languages"] == []
    assert all("probe" not in name.lower() for name in files)


@pytest.mark.parametrize("key", ["fallback_languages", "production_fallback_languages"])
def test_release_rejects_localization_fallback_instead_of_erasing_it(monkeypatch, key):
    metadata: dict[str, dict[str, list[str]]] = {
        "localization": {
            "fallback_languages": [],
            "production_fallback_languages": [],
        }
    }
    metadata["localization"][key] = ["french"]
    files = {".metadata/metadata.json": json.dumps(metadata)}
    monkeypatch.setattr(distribution.decisions, "build", lambda *_args, **_kwargs: files)
    monkeypatch.setattr(distribution.country_state, "validate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(distribution.engine_scope, "verify_strategy_game", lambda *_args: None)
    monkeypatch.setattr(distribution.engine_scope, "verify_company_game", lambda *_args: None)
    monkeypatch.setattr(
        distribution.engine_scope, "verify_company_defaults_game", lambda *_args: None
    )
    monkeypatch.setattr(distribution.company_sectors, "verify_game", lambda *_args: None)
    with pytest.raises(ValueError, match="未翻译"):
        distribution.package_inputs()
    assert json.loads(files[".metadata/metadata.json"]) == metadata


def test_production_generation_rejects_unproven_engine_before_build(monkeypatch):
    def reject(_game):
        raise ValueError("策略引擎证据漂移")

    def must_not_build(*_args, **_kwargs):
        pytest.fail("unverified engine reached the production generator")

    monkeypatch.setattr(distribution.engine_scope, "verify_strategy_game", reject)
    monkeypatch.setattr(distribution.decisions, "build", must_not_build)
    with pytest.raises(ValueError, match="策略引擎证据漂移"):
        distribution.package_inputs()
