"""19 个细分领域和 14 条局部联合链的生产覆盖合同。"""

from __future__ import annotations

import re
import tomllib
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TypedDict

from pdx import decision_adapters, decision_rules

from .action_instances import ActionInstance, build
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
class TargetCoverage:
    """一个真实生产 writer 的 D4 目标责任行。

    目标身份来自 source + rule/action ID，而不是来自卡数量或领域标签。
    consumer、作用域和 owner 直接取生产实例；unknown/cost/fallback 是该
    writer 的显式责任，便于编译合同和审计逐行回查。
    """

    target_id: str
    source: str
    definition: str
    consumer_id: str
    actor: str
    target: str
    owner: str
    unknown_policy: str
    cost_contract: str
    fallback: str


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
    targets: list[dict[str, str]]
    explicit_targets: list[dict[str, str]]


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


def render_counts(path: Path = DEFAULT_SOURCE) -> str:
    """Update only generated per-domain instance counts in the source ledger."""

    text = path.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    if data.get("schema") != 1 or not isinstance(data.get("domains"), dict):
        raise ValueError("领域覆盖源无法安全更新：schema/domains 无效")
    if set(data["domains"]) != set(FAMILIES):
        raise ValueError("领域覆盖必须精确覆盖19个行动族")

    counts: Counter[str] = Counter()
    for item in build(decision_rules.load(), decision_adapters.load()):
        counts[item.family_id] += 1

    lines = text.splitlines()
    current_domain: str | None = None
    seen: set[str] = set()
    for index, line in enumerate(lines):
        section = re.fullmatch(r"\[domains\.([a-z][a-z0-9_]*)\]", line)
        if section:
            current_domain = section[1]
        elif line.startswith("["):
            current_domain = None
        elif current_domain is not None and line.startswith("production_instances"):
            if current_domain in seen or not re.fullmatch(r"production_instances\s*=\s*\d+", line):
                raise ValueError(f"领域生产数量字段无效：{current_domain}")
            lines[index] = f"production_instances = {counts[current_domain]}"
            seen.add(current_domain)
    if seen != set(FAMILIES):
        raise ValueError(f"领域生产数量字段不完整：缺失={sorted(set(FAMILIES) - seen)}")
    return "\n".join(lines) + ("\n" if text.endswith(("\n", "\r")) else "")


def write_counts(path: Path = DEFAULT_SOURCE) -> int:
    """Refresh generated counts while preserving manually maintained contracts."""

    content = render_counts(path)
    path.write_text(content, encoding="utf-8", newline="\n")
    return len(FAMILIES)


def check_counts(path: Path = DEFAULT_SOURCE) -> list[str]:
    """Return a clear error when checked-in generated counts are stale."""

    try:
        actual = path.read_text(encoding="utf-8")
        expected = render_counts(path)
    except FileNotFoundError:
        return [f"领域覆盖源缺失：{path}"]
    except (OSError, UnicodeError, ValueError) as exc:
        return [f"领域覆盖源不可核对：{path}: {exc}"]
    if actual != expected:
        return [f"领域生产实例数与当前规则不一致：{path}"]
    return []


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
    seen_chains: set[str] = set()
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
        expected_chain = expected.get(raw["id"])
        if expected_chain is None or tuple(raw["domains"]) != expected_chain.domain_ids:
            raise ValueError(f"联合链身份或领域顺序不一致：{raw.get('id')}")
        if raw["id"] in seen_chains:
            raise ValueError(f"联合链身份重复：{raw['id']}")
        seen_chains.add(raw["id"])
        for field in ("description", "break_case", "cost_case", "unknown_case"):
            if raw[field] != getattr(expected_chain, field):
                raise ValueError(f"联合链字段与合同不一致：{raw.get('id')}.{field}")
    return result


def contract(
    coverage: dict[str, DomainCoverage], instances: tuple[ActionInstance, ...]
) -> CoverageContract:
    """导出逐实例覆盖摘要；声明状态与实际生产计数分开保存。"""

    by_domain: dict[str, list[ActionInstance]] = {name: [] for name in FAMILIES}
    explicit_by_domain: dict[str, list[ActionInstance]] = {name: [] for name in FAMILIES}
    for instance in instances:
        domain = getattr(instance, "family_id", "")
        if domain in by_domain and getattr(instance, "kind", "rule_action") == "rule_action":
            by_domain[domain].append(instance)
        elif domain in explicit_by_domain and getattr(instance, "kind", "") == "action_card":
            explicit_by_domain[domain].append(instance)
    domains: dict[str, DomainSummary] = {
        name: {
            "declared_status": row.status,
            "unknown_policy": row.unknown_policy,
            "declared_instances": row.production_instances,
            "actual_instances": len(by_domain[name]),
            "owners": sorted({getattr(item, "owner", "") for item in by_domain[name]}),
            "action_ids": sorted(getattr(item, "action_id", "") for item in by_domain[name]),
            "targets": [
                asdict(
                    TargetCoverage(
                        target_id=(
                            f"{getattr(item, 'source', '')}:{getattr(item, 'rule_id', '')}:"
                            f"{getattr(item, 'consumer_field', '')}:"
                            f"{getattr(item, 'actor_scope', '')}:"
                            f"{getattr(item, 'target_scope', '')}"
                        ),
                        source=getattr(item, "source", ""),
                        definition=getattr(item, "rule_id", ""),
                        consumer_id=getattr(item, "consumer_field", ""),
                        actor=getattr(item, "actor_scope", ""),
                        target=getattr(item, "target_scope", ""),
                        owner=getattr(item, "owner", ""),
                        unknown_policy=row.unknown_policy,
                        cost_contract="retained_vanilla_cost_and_qualification",
                        fallback=getattr(item, "vanilla_tail", ""),
                    )
                )
                for item in sorted(by_domain[name], key=lambda value: value.action_id)
            ],
            "explicit_targets": [
                asdict(
                    TargetCoverage(
                        target_id=(
                            f"{getattr(item, 'source', '')}:{getattr(item, 'rule_id', '')}:"
                            f"{getattr(item, 'consumer_field', '')}:root:none"
                        ),
                        source=getattr(item, "source", ""),
                        definition=getattr(item, "rule_id", ""),
                        consumer_id=getattr(item, "consumer_field", ""),
                        actor="root",
                        target="none",
                        owner=getattr(item, "owner", ""),
                        unknown_policy="vanilla",
                        cost_contract="retained_vanilla_cost_and_qualification",
                        fallback=getattr(item, "vanilla_tail", ""),
                    )
                )
                for item in sorted(explicit_by_domain[name], key=lambda value: value.action_id)
            ],
        }
        for name, row in sorted(coverage.items())
    }
    for name, summary in domains.items():
        targets = summary["targets"]
        target_ids = [item["target_id"] for item in targets]
        if len(target_ids) != len(set(target_ids)):
            raise ValueError(f"领域目标身份重复：{name}")
        if any(
            not item["consumer_id"] or not item["owner"] or not item["fallback"] for item in targets
        ):
            raise ValueError(f"领域目标缺少 consumer 或 owner：{name}")
        if summary["declared_instances"] != len(targets):
            raise ValueError(f"领域目标数量与声明不一致：{name}")
        explicit_ids = [item["target_id"] for item in summary["explicit_targets"]]
        if len(explicit_ids) != len(set(explicit_ids)):
            raise ValueError(f"显式行动目标身份重复：{name}")
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


__all__ = [
    "CHAINS",
    "DEFAULT_SOURCE",
    "DomainCoverage",
    "JointChain",
    "TargetCoverage",
    "contract",
    "load",
]
