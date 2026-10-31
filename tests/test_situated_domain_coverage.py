"""D6-D8 领域覆盖目录和联合链合同。"""

import pytest

from pdx.situated.compiler import load_model
from pdx.situated.domain_coverage import CHAINS, contract, load

pytestmark = pytest.mark.unit


def test_十九领域都有真实生产实例和局部未知策略():
    coverage = load()
    assert set(coverage) == {
        "fiscal",
        "administrative",
        "industry",
        "resources",
        "market",
        "research",
        "education",
        "political",
        "population",
        "social",
        "identity",
        "diplomacy",
        "subjects",
        "army",
        "war",
        "navy",
        "overseas",
        "geography",
        "temporal",
    }
    assert all(item.production_instances > 0 for item in coverage.values())
    assert all(item.status == "pending" for item in coverage.values())
    assert all(item.unknown_policy == "vanilla" for item in coverage.values())


def test_联合链恰有十四条且每条有局部断链见证():
    coverage = load()
    assert tuple(item.id for item in CHAINS) == tuple(f"LJ{index:02d}" for index in range(1, 15))
    assert all(item.domain_ids and item.break_case and item.cost_case for item in CHAINS)
    assert all(set(item.domain_ids) <= set(coverage) for item in CHAINS)


def test_领域覆盖合同逐实例回查生产行动():
    model = load_model()
    summary = contract(load(), model.action_instances)
    assert summary["domain_count"] == 19
    assert len(summary["chains"]) == 14
    assert all(
        row["declared_instances"] == row["actual_instances"] and row["owners"]
        for row in summary["domains"].values()
    )
