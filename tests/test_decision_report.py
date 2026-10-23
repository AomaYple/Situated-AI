from __future__ import annotations

import json
from typing import Any

import pytest

from pdx import decision_report, distribution


@pytest.fixture(scope="module")
def engineering_metadata() -> dict[str, Any]:
    _, _, files = distribution.package_inputs(include_engineering_metadata=True)
    value = json.loads(files[".metadata/metadata.json"])
    assert isinstance(value, dict)
    return value


def test_decision_report_covers_all_declared_domains(engineering_metadata: dict[str, Any]) -> None:
    report = decision_report.build(engineering_metadata)

    assert report["goal"].startswith("基于国家处境")
    assert report["behavior_verified"] is False
    assert set(report["domains"]) == set(decision_report.DOMAINS)
    assert all(row["status"] == "consumer_mapped" for row in report["domains"].values())
    assert report["reader_count"] >= 1
    assert report["consumer_rule_count"] >= 1


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
