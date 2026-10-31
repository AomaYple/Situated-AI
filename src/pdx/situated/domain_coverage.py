"""19 个细分领域和 14 条局部联合链的生产覆盖合同。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from pdx import decision_adapters, decision_rules

from .action_instances import build
from .families import FAMILIES

REPO = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE = REPO / "mod" / "decisions" / "domain_actions.toml"


@dataclass(frozen=True, slots=True)
class DomainCoverage:
    id: str
    production_instances: int
    status: str
    unknown_policy: str
    evidence_contract: str


@dataclass(frozen=True, slots=True)
class JointChain:
    id: str
    domain_ids: tuple[str, ...]
    description: str
    break_case: str
    cost_case: str
    unknown_case: str


class DomainSummary(TypedDict):
    declared_status: str
    unknown_policy: str
    declared_instances: int
    actual_instances: int
    owners: list[str]
    action_ids: list[str]


class ChainSummary(TypedDict):
    id: str
    domains: list[str]
    description: str
    break_case: str
    cost_case: str
    unknown_case: str


class CoverageContract(TypedDict):
    schema: int
    domain_count: int
    domains: dict[str, DomainSummary]
    chains: list[ChainSummary]
    evidence: str


CHAINS: tuple[JointChain, ...] = (
    JointChain(
        "LJ01",
        ("resources", "industry", "market"),
        "raw_material_to_industry",
        "upstream_break",
        "maintenance_cost",
        "unknown_local_fallback",
    ),
    JointChain(
        "LJ02",
        ("resources", "industry", "geography"),
        "energy_to_transport",
        "transport_break",
        "infrastructure_cost",
        "unknown_local_fallback",
    ),
    JointChain(
        "LJ03",
        ("education", "research", "industry"),
        "education_to_research",
        "literacy_break",
        "institution_cost",
        "unknown_local_fallback",
    ),
    JointChain(
        "LJ04",
        ("administrative", "political", "social"),
        "administration_to_welfare",
        "capacity_break",
        "bureaucracy_cost",
        "unknown_local_fallback",
    ),
    JointChain(
        "LJ05",
        ("fiscal", "industry", "administrative"),
        "fiscal_to_construction",
        "budget_break",
        "debt_cost",
        "unknown_local_fallback",
    ),
    JointChain(
        "LJ06",
        ("population", "industry", "research"),
        "employment_to_mechanization",
        "labor_break",
        "transition_cost",
        "unknown_local_fallback",
    ),
    JointChain(
        "LJ07",
        ("resources", "social", "political"),
        "food_to_stability",
        "supply_break",
        "welfare_cost",
        "unknown_local_fallback",
    ),
    JointChain(
        "LJ08",
        ("political", "administrative", "research"),
        "coalition_to_reform",
        "support_break",
        "reform_cost",
        "unknown_local_fallback",
    ),
    JointChain(
        "LJ09",
        ("market", "diplomacy", "navy"),
        "trade_to_diplomacy",
        "route_break",
        "security_cost",
        "unknown_local_fallback",
    ),
    JointChain(
        "LJ10",
        ("fiscal", "army", "war"),
        "fiscal_to_armament",
        "mobilization_break",
        "military_cost",
        "unknown_local_fallback",
    ),
    JointChain(
        "LJ11",
        ("war", "industry", "fiscal"),
        "war_to_recovery",
        "recovery_break",
        "reconstruction_cost",
        "unknown_local_fallback",
    ),
    JointChain(
        "LJ12",
        ("subjects", "diplomacy", "political"),
        "subject_to_autonomy",
        "dependency_break",
        "autonomy_cost",
        "unknown_local_fallback",
    ),
    JointChain(
        "LJ13",
        ("navy", "overseas", "geography"),
        "navy_to_overseas",
        "projection_break",
        "naval_cost",
        "unknown_local_fallback",
    ),
    JointChain(
        "LJ14",
        ("identity", "geography", "population"),
        "identity_to_migration",
        "identity_break",
        "integration_cost",
        "unknown_local_fallback",
    ),
)


def load(path: Path = DEFAULT_SOURCE) -> dict[str, DomainCoverage]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or set(data) != {"schema", "domains", "chains"}:
        raise ValueError("domain_actions.toml schema 无效")
    raw_domains = data["domains"]
    if not isinstance(raw_domains, dict) or set(raw_domains) != set(FAMILIES):
        raise ValueError("领域覆盖必须精确覆盖19个行动族")
    counts = dict.fromkeys(FAMILIES, 0)
    for item in build(decision_rules.load(), decision_adapters.load()):
        counts[item.family_id] += 1
    result: dict[str, DomainCoverage] = {}
    for key in FAMILIES:
        raw = raw_domains[key]
        if not isinstance(raw, dict) or set(raw) != {
            "production_instances",
            "status",
            "unknown_policy",
            "evidence_contract",
        }:
            raise ValueError(f"领域覆盖字段无效：{key}")
        if (
            type(raw["production_instances"]) is not int
            or raw["production_instances"] != counts[key]
        ):
            raise ValueError(f"领域 {key} 的生产实例数与规则目录不一致")
        if raw["status"] not in {"pending", "implemented"} or raw["unknown_policy"] != "vanilla":
            raise ValueError(f"领域 {key} 必须保留生产和未知回退合同")
        result[key] = DomainCoverage(
            key,
            raw["production_instances"],
            raw["status"],
            raw["unknown_policy"],
            raw["evidence_contract"],
        )
    if not isinstance(data["chains"], list) or len(data["chains"]) != len(CHAINS):
        raise ValueError("联合链必须恰有14条")
    expected = {item.id: item for item in CHAINS}
    for raw in data["chains"]:
        if not isinstance(raw, dict) or set(raw) != {
            "id",
            "domains",
            "description",
            "break_case",
            "cost_case",
            "unknown_case",
        }:
            raise ValueError("联合链字段无效")
        if raw["id"] not in expected or tuple(raw["domains"]) != expected[raw["id"]].domain_ids:
            raise ValueError(f"联合链身份或领域顺序不一致：{raw.get('id')}")
    return result


def contract(
    coverage: dict[str, DomainCoverage], instances: tuple[object, ...]
) -> CoverageContract:
    """导出逐实例覆盖摘要；声明状态与实际生产计数分开保存。"""

    by_domain: dict[str, list[object]] = {name: [] for name in FAMILIES}
    for instance in instances:
        if getattr(instance, "kind", "rule_action") != "rule_action":
            continue
        domain = getattr(instance, "family_id", "")
        if domain in by_domain:
            by_domain[domain].append(instance)
    domains: dict[str, DomainSummary] = {
        name: {
            "declared_status": row.status,
            "unknown_policy": row.unknown_policy,
            "declared_instances": row.production_instances,
            "actual_instances": len(by_domain[name]),
            "owners": sorted({getattr(item, "owner", "") for item in by_domain[name]}),
            "action_ids": sorted(getattr(item, "action_id", "") for item in by_domain[name]),
        }
        for name, row in sorted(coverage.items())
    }
    chains: list[ChainSummary] = [
        {
            "id": item.id,
            "domains": list(item.domain_ids),
            "description": item.description,
            "break_case": item.break_case,
            "cost_case": item.cost_case,
            "unknown_case": item.unknown_case,
        }
        for item in CHAINS
    ]
    return {
        "schema": 1,
        "domain_count": len(domains),
        "domains": domains,
        "chains": chains,
        "evidence": "static_production_inventory_not_behavior_quality",
    }


__all__ = ["CHAINS", "DEFAULT_SOURCE", "DomainCoverage", "JointChain", "contract", "load"]
