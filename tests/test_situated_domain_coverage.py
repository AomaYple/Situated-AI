"""D6-D8 领域覆盖目录和联合链合同。"""

import pytest
from _situated_sources import production_policy_sources

from pdx.situated import domain_coverage
from pdx.situated.compiler import load_model
from pdx.situated.domain_coverage import CHAINS, contract, load

pytestmark = pytest.mark.unit


def test_十九领域保留范围且时间域无规则实例时如实待完成():
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
    assert {key for key, item in coverage.items() if item.production_instances} == set(coverage) - {
        "temporal"
    }
    assert coverage["temporal"].production_instances == 0
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
        row["declared_instances"] == row["actual_instances"] for row in summary["domains"].values()
    )
    assert {key for key, row in summary["domains"].items() if row["owners"]} == set(
        summary["domains"]
    ) - {"temporal"}
    temporal = summary["domains"]["temporal"]
    assert temporal["declared_status"] == "pending"
    assert temporal["declared_instances"] == temporal["actual_instances"] == 0
    assert temporal["targets"] == temporal["explicit_targets"] == []


def test_领域覆盖逐目标保留消费者作用域成本和回退责任():
    coverage = load()
    model = load_model()
    summary = contract(coverage, model.action_instances)
    targets = [target for row in summary["domains"].values() for target in row["targets"]]
    assert len(targets) == len(production_policy_sources().rules)
    assert {
        (target["source"], target["definition"], target["consumer_id"]) for target in targets
    } == production_policy_sources().rules
    assert len({target["target_id"] for target in targets}) == len(targets)
    assert all(
        target["consumer_id"]
        and target["actor"]
        and target["target"]
        and target["owner"]
        and target["unknown_policy"] == "vanilla"
        and target["cost_contract"]
        and target["fallback"]
        for target in targets
    )
    cards = [target for row in summary["domains"].values() for target in row["explicit_targets"]]
    assert len(cards) == 11
    assert len({target["target_id"] for target in cards}) == len(cards)


def test_联合链字段被篡改时合同拒绝(tmp_path):
    source = tmp_path / "domain_actions.toml"
    text = domain_coverage.source_path().read_text(encoding="utf-8")
    source.write_text(
        text.replace(
            'description = "raw_material_to_industry"',
            'description = "tampered"',
            1,
        ),
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(ValueError, match="联合链字段与合同不一致"):
        load(source)
