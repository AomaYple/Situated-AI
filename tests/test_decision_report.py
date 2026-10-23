from __future__ import annotations

import json
from typing import Any

import pytest

from pdx import decision_adapters, decision_intents, decision_report, decision_rules


@pytest.fixture(scope="module")
def engineering_metadata() -> dict[str, Any]:
    return decision_report.source_metadata()


def test_decision_report_covers_all_declared_domains(engineering_metadata: dict[str, Any]) -> None:
    report = decision_report.build(engineering_metadata)

    assert report["goal"].startswith("基于国家处境")
    assert report["behavior_verified"] is False
    assert set(report["domains"]) == set(decision_report.DOMAINS)
    assert all(row["status"] == "consumer_mapped" for row in report["domains"].values())
    assert report["reader_count"] == (
        report["information_reader_count"] + report["consumer_reader_count"]
    )
    assert report["information_reader_count"] >= 1
    assert report["consumer_reader_count"] >= 1
    assert report["consumer_rule_count"] >= 1


def test_offline_metadata_reuses_the_shared_rule_contract(
    engineering_metadata: dict[str, Any],
) -> None:
    strategy = decision_intents.load()
    information = decision_rules.load(strategy=strategy)
    adapters = decision_adapters.load(strategy=strategy)

    assert engineering_metadata["decision_rules"] == decision_rules.contract(information)
    assert engineering_metadata["consumer_adapters"]["consumers"] == [
        {"source": source, **decision_rules.contract(rules, owner="consumer_adapters")}
        for source, rules in adapters.policies
    ]


def test_decision_report_rejects_missing_rationale(engineering_metadata: dict[str, Any]) -> None:
    broken = json.loads(json.dumps(engineering_metadata))
    broken["decision_rules"]["rules"][0]["why"] = ""

    with pytest.raises(ValueError, match="why"):
        decision_report.build(broken)


def test_decision_report_rejects_missing_vanilla_consumer(
    engineering_metadata: dict[str, Any],
) -> None:
    broken = json.loads(json.dumps(engineering_metadata))
    broken["decision_rules"]["rules"][0].pop("consumer")

    with pytest.raises(ValueError, match="consumer"):
        decision_report.build(broken)
