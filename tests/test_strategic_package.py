"""标准候选必须携带实际使用的共享策略来源，而不是无消费者的设计声明。"""

import hashlib
import json
from pathlib import Path

import pytest

from pdx import decision_intents, distribution


@pytest.mark.integration
def test_integrated_freezes_shared_strategy_and_actual_consumers():
    _, _, files = distribution.package_inputs("integrated")
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
    assert metadata["version"] == "2.0.0.dev3"
    assert contract["behavior_verified"] is False
    assert contract["rules_with_intent"] > len(strategy.intents)


def test_historical_package_has_no_new_strategy_contract():
    _, _, files = distribution.package_inputs("disabled")
    metadata = json.loads(files[".metadata/metadata.json"])
    assert "strategic_coordination" not in metadata
    assert "strategic_source_sha256" not in metadata["source_fingerprint"]
