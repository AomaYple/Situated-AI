"""19 个细分领域和 14 条局部联合链的生产覆盖合同。"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Any, TypedDict

from pdx import decision_adapters, decision_rules
from pdx.model import Assignment, Block
from pdx.parser import parse_bytes

from . import engine_scope
from .action_instances import ActionInstance, build
from .families import FAMILIES

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .vanilla_inventory import VanillaInventory, VanillaSurface

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


@dataclass(frozen=True, slots=True)
class NativeConsumerBinding:
    """An explicit card's exact native declaration, supplied by its real caller.

    This identity grants no scope or implementation evidence. The independent
    inventory and the production instance still have to agree on those facts.
    """

    source: str
    definition: str
    field: str

    def __post_init__(self) -> None:
        source = PurePosixPath(self.source)
        if (
            not self.source
            or "\\" in self.source
            or source.is_absolute()
            or PureWindowsPath(self.source).drive
            or any(part in {"", ".", ".."} for part in self.source.split("/"))
            or not (self.source.startswith("common/") or "/common/" in self.source)
            or not self.definition
            or any(not part for part in self.field.split("."))
        ):
            raise ValueError("原版消费者必须有精确相对来源、定义与字段")


def _native_binding(instance: ActionInstance) -> NativeConsumerBinding | None:
    if instance.kind != "rule_action":
        return None
    if instance.source == "mod/decisions/information.toml":
        return NativeConsumerBinding(
            "common/ai_strategies/00_default_strategy.txt",
            "ai_strategy_default",
            instance.consumer_field,
        )
    definition, separator, field = instance.consumer_field.partition(".")
    if not separator:
        return None
    return NativeConsumerBinding(instance.source, definition, field)


def _native_context_issue(
    instance: ActionInstance, surface: VanillaSurface, *, state_owner_proven: bool = False
) -> str | None:
    """Check documented object types; writer labels never invent named scopes."""

    if not instance.owner or not instance.vanilla_tail:
        return "production_ownership_or_tail_missing"
    exact_numeric = {
        "subject_value": ("additive_subject_valuation", {"add"}),
        "become_subject_value": ("additive_subject_valuation", {"add"}),
        "wanted_army_size": ("additive_army_size_target", {"multiply"}),
        "wanted_navy_size": ("additive_navy_size_target", {"multiply"}),
        "ship_construction_output_multiplier": (
            "additive_ship_construction_output_multiplier",
            {"multiply"},
        ),
        "wanted_construction_output": ("additive_construction_output_target", {"multiply"}),
        "aggression": ("additive_aggression", {"add"}),
        "nationalization_desire": ("additive_nationalization_desire", {"multiply"}),
        "max_active_stances": ("additive_active_stance_limit", {"multiply"}),
        "wanted_marines": ("additive_marine_size_target", {"multiply"}),
        "economic_vs_government_spending_balance": ("additive_spending_balance", {"add"}),
        "target_marine_formation_size": ("additive_marine_formation_size_target", {"multiply"}),
        "unacceptable_infamy_level": ("first_positive_infamy_limit_override", {"multiply"}),
        "undesirable_infamy_level": ("first_positive_infamy_limit_override", {"multiply"}),
        "diplomatic_play_neutrality": ("additive_positive_active_neutrality", {"add"}),
        "diplomatic_play_boldness": ("native_randomized_additive_boldness", {"add"}),
        "min_law_chance_to_pass": ("override_pass_chance_threshold", {"add"}),
        "revolution_aversion": ("override_revolution_aversion", {"multiply"}),
        "change_law_chance": ("additive_percentage_chance", {"add"}),
        "max_progressiveness": ("override_progressiveness_limit", {"add"}),
        "max_regressiveness": ("override_regressiveness_limit", {"add"}),
        "recklessness": ("additive_strength_estimate_multiplier", {"add"}),
        "wargoal_maneuvers_fraction": ("additive_maneuvers_fraction", {"multiply"}),
    }
    contract = exact_numeric.get(surface.field)
    exact_proven = (
        surface.source == "common/ai_strategies/00_default_strategy.txt"
        and surface.definition == "ai_strategy_default"
        and surface.capability == "direct"
        and surface.legal
        and contract is not None
        and surface.operation == contract[0]
        and instance.operation in contract[1]
    )
    if not exact_proven and (
        instance.operation not in {"add", "multiply"}
        or surface.operation
        not in {
            "additive_score",
            "multiplicative_score",
            "score",
            "chance",
            "base_candidate_score",
            "relative_weight",
            "multiplier",
        }
    ):
        return "numeric_consumer_contract_unproven"
    context = instance.evaluation_context
    if context is not None and context.status != "observed":
        return "evaluation_context_unproven"
    if (
        context is not None
        and context.actor_scope is not None
        and context.actor_scope.name == "root"
        and context.actor_scope.kind == "country"
        and instance.actor_scope != "root"
    ):
        # A country object reached through owner is not the documented ROOT.
        # State/building owner proofs below retain their separate contract.
        return "actor_type_mismatch"
    actor_kind = (
        "state"
        if state_owner_proven
        else "country"
        if instance.actor_scope in {"root", "owner"}
        else instance.actor_scope
    )
    if (
        context is not None
        and context.actor_scope is not None
        and context.actor_scope.kind != actor_kind
    ) or surface.actor_scope != actor_kind:
        return "actor_type_mismatch"
    if surface.target_scope == "none" or surface.target_scope.startswith("definition_only:"):
        # Definition identity is already exact; it is not a script-side target.
        if instance.target_scope not in {"none", "target_or_none"}:
            return "target_type_mismatch"
        return None
    targets = surface.target_scope.split(";")
    expected: dict[str, str] = {}
    for target in targets:
        match = re.fullmatch(r"scope:([a-z][a-z0-9_]*)=([a-z][a-z0-9_]*)", target)
        if match is None:
            return "named_target_contract_unproven"
        expected[match[1]] = match[2]
    if context is None:
        return "evaluation_context_unproven"
    observed = {item.name: item.kind for item in (*context.targets, *context.auxiliary_scopes)}
    if any(observed.get(name) != kind for name, kind in expected.items()):
        return "target_type_mismatch"
    return None


def _ordinary(block: Block, key: str) -> Assignment | None:
    declarations = block.all(key)
    if len(declarations) != 1:
        return None
    item = declarations[0]
    return item if item.op == "=" and item.prefix is None else None


class _NativeBindingProofs:
    """Optional source bytes and real policies, never inferred from writer names."""

    def __init__(
        self,
        inventory: VanillaInventory,
        sources: Mapping[str, bytes],
        policies: Mapping[str, decision_rules.RuleSet],
    ) -> None:
        self.inventory = inventory
        self.sources = dict(sources)
        self.policies = policies
        self.parsed: dict[str, Block] = {}
        self.company_defaults: dict[str, Any] | None = None
        for source, raw in self.sources.items():
            if hashlib.sha256(raw).hexdigest() != inventory.source_hashes.get(source):
                raise ValueError(f"原版覆盖证据与独立盘点字节不一致：{source}")

    def root(self, source: str) -> Block | None:
        if source not in self.sources:
            return None
        if source not in self.parsed:
            parsed = parse_bytes(self.sources[source], path=source)
            if parsed.errors:
                raise ValueError(f"原版覆盖证据解析失败：{source}")
            self.parsed[source] = parsed.root
        return self.parsed[source]

    def definition(self, binding: NativeConsumerBinding) -> Assignment | None:
        root = self.root(binding.source)
        return _ordinary(root, binding.definition) if root is not None else None

    def building_evidence(self) -> tuple[str, ...]:
        source = "common/buildings/buildings.md"
        raw = self.sources.get(source)
        if raw is None:
            return ()
        lines = raw.decode("utf-8-sig").splitlines()
        markers = (
            "# base AI value, default NAI.BUILDING_BASE_VALUE or NAI.GOVERNMENT_BUILDING_BASE_VALUE",
            "# scope is state the building is located in",
            "ai_value = script value",
        )
        locations = [
            [index + 1 for index, line in enumerate(lines) if line.strip() == marker]
            for marker in markers
        ]
        if any(len(found) != 1 for found in locations):
            return ()
        positions = [found[0] for found in locations]
        if positions != sorted(positions) or positions[-1] - positions[0] > 4:
            return ()
        return tuple(f"{source}:{line}" for line in positions)

    def state_owner(self, instance: ActionInstance, binding: NativeConsumerBinding) -> bool:
        if (
            instance.kind != "rule_action"
            or not binding.source.startswith("common/buildings/")
            or binding.field != "ai_value"
            or not self.building_evidence()
        ):
            return False
        policy = self.policies.get(instance.source)
        raw = self.sources.get(binding.source)
        # Adapter baselines intentionally hash read_text(utf-8-sig), including
        # universal-newline decoding, whereas inventory hashes original bytes.
        baseline = (
            hashlib.sha256(
                raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
            ).hexdigest()
            if raw is not None
            else None
        )
        if policy is None or policy.actor_path != ("owner",) or policy.baseline_sha256 != baseline:
            return False
        rules = [item for item in policy.rules if item.id == instance.rule_id]
        return (
            len(rules) == 1
            and ".".join(rules[0].field) == instance.consumer_field
            and rules[0].operation == instance.operation
            and rules[0].value == instance.value
            and tuple(sorted(rules[0].input_keys())) == instance.condition_facts
            and instance.actor_scope == "owner"
        )

    def secret_goal_parent(self, binding: NativeConsumerBinding) -> str | None:
        match = re.fullmatch(r"secret_goal_scores\.([a-z][a-z0-9_]*)\.score", binding.field)
        if match is None or not binding.source.startswith("common/ai_strategies/"):
            return None
        definition = self.definition(binding)
        if definition is None or not isinstance(definition.value, Block):
            return None
        groups = _ordinary(definition.value, "secret_goal_scores")
        if groups is None or not isinstance(groups.value, Block):
            return None
        goal = _ordinary(groups.value, match[1])
        if goal is None or not isinstance(goal.value, Block):
            return None
        score = _ordinary(goal.value, "score")
        if score is None or not isinstance(score.value, Block):
            return None
        return f"secret_goal_scores.{match[1]}"

    def implicit_building(self, binding: NativeConsumerBinding) -> dict[str, Any] | None:
        evidence = self.building_evidence()
        if (
            not evidence
            or not binding.source.startswith("common/buildings/")
            or binding.field != "ai_value"
        ):
            return None
        # All discovered building files must participate, so a duplicate object
        # in another file cannot be hidden by providing only the preferred file.
        all_sources = [
            source
            for source in self.inventory.source_hashes
            if (source.startswith("common/buildings/") or "/common/buildings/" in source)
            and source.endswith(".txt")
        ]
        if any(source not in self.sources for source in all_sources):
            return None
        declarations = [
            (source, item)
            for source in all_sources
            if (root := self.root(source)) is not None
            for item in root.all(binding.definition)
        ]
        if len(declarations) != 1 or declarations[0][0] != binding.source:
            return None
        definition = declarations[0][1]
        if (
            definition.prefix is not None
            or definition.op != "="
            or not isinstance(definition.value, Block)
            or definition.value.all("ai_value")
        ):
            return None
        return {
            **asdict(binding),
            "actor_scope": "state",
            "target_scope": "none",
            "operation": "score",
            "default": "NAI.BUILDING_BASE_VALUE_or_NAI.GOVERNMENT_BUILDING_BASE_VALUE",
            "evidence": [*evidence, f"{binding.source}:{definition.line}"],
        }

    def implicit_company(self, binding: NativeConsumerBinding) -> dict[str, Any] | None:
        """Exact missing fields backed by the pinned consumer/default branch.

        This does not add implicit objects to the discovered declaration
        denominator or authorize arbitrary company fields. Every native
        company file and the define bytes must be independently available.
        """
        if (
            binding.source != "common/company_types/99_basic_companies.txt"
            or binding.field != "ai_weight"
        ):
            return None
        if self.company_defaults is None:
            self.company_defaults = json.loads(engine_scope.company_default_snapshot())
        data = self.company_defaults
        parent = json.loads(engine_scope.company_snapshot())
        expected = {**parent["script_hashes"], **data["script_hashes"]}
        all_company_sources = {
            name
            for name in self.inventory.source_hashes
            if (name.startswith("common/company_types/") or "/common/company_types/" in name)
            and name.endswith(".txt")
        }
        if all_company_sources != set(parent["script_hashes"]):
            return None
        if any(
            name not in self.sources or hashlib.sha256(self.sources[name]).hexdigest() != digest
            for name, digest in expected.items()
        ):
            return None
        permitted = {row["id"]: row["line"] for row in data["implicit_companies"]}
        if binding.definition not in permitted:
            return None
        declarations = [
            (name, item)
            for name in all_company_sources
            if (root := self.root(name)) is not None
            for item in root.all(binding.definition)
        ]
        if len(declarations) != 1 or declarations[0][0] != binding.source:
            return None
        definition = declarations[0][1]
        if (
            definition.prefix is not None
            or definition.op != "="
            or definition.line != permitted[binding.definition]
            or not isinstance(definition.value, Block)
            or definition.value.all("ai_weight")
        ):
            return None
        row = data["contracts"][0]
        return {
            **asdict(binding),
            "actor_scope": "country",
            "target_scope": "definition_only:company_type",
            "operation": "base_candidate_score",
            "default": row["define_field"],
            "default_value": row["default_value"],
            "evidence": [
                engine_scope.COMPANY_DEFAULT_MANIFEST_ID,
                f"{row['define_source']}:{row['define_line']}",
                f"{binding.source}:{definition.line}",
            ],
        }

    def company_actor(self, instance: ActionInstance, binding: NativeConsumerBinding) -> bool:
        policy = self.policies.get(instance.source)
        raw = self.sources.get(binding.source)
        if policy is None or raw is None or policy.actor_path:
            return False
        baseline = hashlib.sha256(
            raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
        ).hexdigest()
        if policy.baseline_sha256 != baseline:
            return False
        rules = [item for item in policy.rules if item.id == instance.rule_id]
        context = instance.evaluation_context
        return (
            len(rules) == 1
            and ".".join(rules[0].field) == instance.consumer_field
            and rules[0].operation == instance.operation == "multiply"
            and rules[0].value == instance.value
            and tuple(sorted(rules[0].input_keys())) == instance.condition_facts
            and instance.actor_scope == "root"
            and instance.target_scope in {"none", "target_or_none"}
            and context is not None
            and context.status == "observed"
            and context.actor_scope is not None
            and context.actor_scope.name == "root"
            and context.actor_scope.kind == "country"
            and context.actor_scope.source == engine_scope.COMPANY_MANIFEST_ID
            and not context.targets
            and not context.auxiliary_scopes
            and f"{engine_scope.COMPANY_MANIFEST_ID}:sha256={engine_scope.COMPANY_MANIFEST_SHA256}"
            in context.evidence
            and f"{engine_scope.COMPANY_MANIFEST_ID}:definition_only:company_type"
            in context.evidence
        )


def native_coverage(
    inventory: VanillaInventory,
    instances: tuple[ActionInstance, ...],
    *,
    explicit_consumers: Mapping[str, NativeConsumerBinding] | None = None,
    native_sources: Mapping[str, bytes] | None = None,
    production_policies: Mapping[str, decision_rules.RuleSet] | None = None,
) -> dict[str, Any]:
    """Join real production bindings to an independently discovered denominator.

    The caller supplies an existing inventory; this function never discovers
    game files or loads the production model. ``actual_covered`` means a legal
    native declaration has an exact production binding with compatible numeric
    and object contracts. It does not prove functional depth, PDX equivalence,
    or engine behavior. Raw pending states and evidence remain in every row.
    Optional ``native_sources`` bytes must match inventory hashes; missing
    sources stay unproven. ``production_policies`` provide real state-owner
    actor paths. Documented implicit consumers are separate from the denominator.
    """

    explicit = dict(explicit_consumers or {})
    proofs = _NativeBindingProofs(inventory, native_sources or {}, production_policies or {})
    by_id = {item.action_id: item for item in instances}
    if len(by_id) != len(instances):
        raise ValueError("原版覆盖映射的生产行动身份重复")
    if set(explicit) - set(by_id) or any(by_id[key].kind != "action_card" for key in explicit):
        raise ValueError("显式消费者映射只能引用实际显式行动卡")
    identities: dict[tuple[str, str, str], list[VanillaSurface]] = {}
    for surface in inventory.surfaces:
        identities.setdefault((surface.source, surface.definition, surface.field), []).append(
            surface
        )
    matches: dict[str, list[ActionInstance]] = {}
    state_owner: set[str] = set()
    projections: dict[str, dict[str, str]] = {}
    implicit: dict[tuple[str, str, str], dict[str, Any]] = {}
    unmatched: list[dict[str, Any]] = []
    for instance in sorted(instances, key=lambda item: item.action_id):
        binding = explicit.get(instance.action_id) or _native_binding(instance)
        if binding is None:
            unmatched.append({"action_id": instance.action_id, "reason": "native_binding_missing"})
            continue
        if instance.kind == "action_card" and binding.field != instance.consumer_field:
            unmatched.append(
                {
                    "action_id": instance.action_id,
                    "reason": "explicit_field_mismatch",
                    "binding": asdict(binding),
                }
            )
            continue
        native_candidates = identities.get((binding.source, binding.definition, binding.field), [])
        if not native_candidates and (parent := proofs.secret_goal_parent(binding)) is not None:
            native_candidates = identities.get((binding.source, binding.definition, parent), [])
            if len(native_candidates) == 1:
                projections[instance.action_id] = {
                    "writer_field": binding.field,
                    "consumer_field": parent,
                }
        if proofs.state_owner(instance, binding):
            state_owner.add(instance.action_id)
        proof = (
            proofs.implicit_building(binding) or proofs.implicit_company(binding)
            if not native_candidates
            else None
        )
        if proof is not None:
            row = implicit.setdefault(
                (binding.source, binding.definition, binding.field),
                {**proof, "matched_actions": [], "covered_actions": [], "binding_issues": {}},
            )
            row["matched_actions"].append(instance.action_id)
            if proof["actor_scope"] == "state" and instance.action_id not in state_owner:
                row["binding_issues"][instance.action_id] = "state_owner_policy_unproven"
            elif proof["actor_scope"] == "country" and not proofs.company_actor(instance, binding):
                row["binding_issues"][instance.action_id] = "company_root_policy_unproven"
            elif (
                not instance.owner
                or not instance.vanilla_tail
                or instance.operation not in {"add", "multiply"}
            ):
                row["binding_issues"][instance.action_id] = "production_contract_unproven"
            else:
                row["covered_actions"].append(instance.action_id)
            continue
        if len(native_candidates) != 1:
            unmatched.append(
                {
                    "action_id": instance.action_id,
                    "reason": "native_identity_ambiguous"
                    if native_candidates
                    else "native_surface_missing",
                    "binding": asdict(binding),
                }
            )
            continue
        matches.setdefault(native_candidates[0].declaration_id, []).append(instance)
    categories: dict[str, list[str]] = {
        name: []
        for name in (
            "actual_covered",
            "unimplemented_legal",
            "pending",
            "unknown",
            "observation",
            "unsupported",
        )
    }
    unknown_scopes = set(inventory.unknown_scopes)
    rows = []
    binding_issue_count = 0
    for surface in sorted(inventory.surfaces, key=lambda item: item.declaration_id):
        candidates = matches.get(surface.declaration_id, [])
        issues = {
            item.action_id: reason
            for item in candidates
            if (
                reason := _native_context_issue(
                    item, surface, state_owner_proven=item.action_id in state_owner
                )
            )
            is not None
        }
        binding_issue_count += len(issues)
        covered = sorted(item.action_id for item in candidates if item.action_id not in issues)
        if surface.ambiguity:
            status = "unknown"
        elif surface.capability == "observation":
            status = "observation"
        elif surface.capability == "unexposed":
            status = "unsupported" if surface.scope_evidence else "unknown"
        elif surface.capability == "pending":
            status = "pending"
        elif surface.legal and surface.surface_id not in unknown_scopes:
            status = "actual_covered" if covered else "unimplemented_legal"
        else:
            status = "unknown"
        categories[status].append(surface.declaration_id)
        rows.append(
            {
                **asdict(surface),
                "declaration_id": surface.declaration_id,
                "legal": surface.legal,
                "unknown_scope": surface.surface_id in unknown_scopes,
                "coverage_status": status,
                "matched_actions": sorted(item.action_id for item in candidates),
                "covered_actions": covered if status == "actual_covered" else [],
                "binding_issues": issues,
                "field_projections": {
                    key: projections[key]
                    for key in sorted(projections)
                    if key in {item.action_id for item in candidates}
                },
            }
        )
    unresolved = (
        len(categories["unimplemented_legal"])
        + len(categories["pending"])
        + len(categories["unknown"])
    )
    implicit_rows = list(implicit.values())
    binding_issue_count += sum(len(row["binding_issues"]) for row in implicit_rows)
    return {
        "schema": 1,
        "baseline_id": inventory.baseline_id,
        "scope_hash": inventory.scope_hash,
        "source_hashes": dict(inventory.source_hashes),
        "denominator": inventory.discovered_count,
        "legal_count": inventory.legal_count,
        "capability_counts": inventory.capability_counts,
        "inventory_status_counts": inventory.status_counts,
        "unknown_scopes": list(inventory.unknown_scopes),
        "parse_failures": list(inventory.parse_failures),
        "counts": {name: len(ids) for name, ids in categories.items()},
        **categories,
        "unmatched_production": unmatched,
        "binding_issue_count": binding_issue_count,
        "rows": rows,
        "implicit_covered": [
            {key: row[key] for key in ("source", "definition", "field")}
            for row in implicit_rows
            if row["covered_actions"]
        ],
        "implicit_rows": implicit_rows,
        "implicit_denominator_policy": "documented_optional_consumers_separate_from_discovered_denominator",
        "binding_complete": bool(inventory.surfaces)
        and not (unresolved or unmatched or binding_issue_count or inventory.parse_failures),
        "evidence": "static_exact_production_binding_not_functional_or_behavior_acceptance",
    }


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
    "NativeConsumerBinding",
    "TargetCoverage",
    "contract",
    "load",
    "native_coverage",
]
