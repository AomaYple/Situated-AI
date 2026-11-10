"""R2 feature support, with production permission separate from core lowering.

The fixed adapter contract grants only reviewed operations in exact consumers.
Rows are derived from canonical programs; a caller cannot supply support labels.
Reference support does not grant a new physical writer or native operation.
"""

from __future__ import annotations

from dataclasses import is_dataclass
from typing import TYPE_CHECKING, get_args, get_type_hints

from . import action_network as net
from . import core_contracts as core
from . import expressions as ex

if TYPE_CHECKING:
    from .production_profile import ProductionProfile

CONSUMERS = ("a0-econ-road", "a0-pol-schools", "a0-dip-relations")
FEATURES = (
    "node.action",
    "node.network",
    "node.network_program",
    "node.assessment_term",
    "node.effect_registry",
    "node.effect_instance",
    "node.contribution",
    "node.budget",
    "node.fact",
    "node.objective",
    "node.effect_account",
    "node.lineage",
    "node.assessment_group",
    "node.derived_predicate",
    "path.direct",
    "path.derived",
    "path.interaction",
    "operator.add",
    "operator.multiply",
    "operator.compare.eq",
    "operator.compare.ne",
    "operator.compare.lt",
    "operator.compare.le",
    "operator.compare.gt",
    "operator.compare.ge",
    "operator.all",
    "operator.any",
    "operator.not",
    "operator.known",
    "operator.literal",
    "operator.constant",
    "operator.specialize",
    "role.benefit",
    "role.cost",
    "role.risk",
    "baseline.new_consideration",
    "baseline.conditional_correction",
    "baseline.intentional_reweight",
    "relation.dependency_dag",
    "relation.variant",
    "relation.alias",
    "relation.replacement",
    "relation.residual",
    "relation.overlap.independent",
    "relation.overlap.replacement",
    "relation.overlap.residual",
    "relation.objective.conflicts",
    "relation.objective.coexists",
    "relation.objective.tradeoff",
    "relation.objective.priority",
    "reference.observation_batch",
    "reference.evaluation_result",
    "reference.selection",
)
_MODELS = {
    "ActionBridge": "path.direct",
    "ActionDefinition": "node.action",
    "ActionInstance": "node.action",
    "ActionNetwork": "node.network",
    "AssessmentGroup": "node.assessment_group",
    "AssessmentTerm": "node.assessment_term",
    "Constant": "operator.constant",
    "DerivedPredicate": "node.derived_predicate",
    "EffectAccount": "node.effect_account",
    "EffectAlias": "relation.alias",
    "EffectInstance": "node.effect_instance",
    "EffectRegistry": "node.effect_registry",
    "EvaluationResult": "reference.evaluation_result",
    "EvidenceLineage": "node.lineage",
    "FactKnown": "operator.known",
    "LoweredContribution": "operator.specialize",
    "NetworkBudget": "node.budget",
    "NetworkProgram": "node.network_program",
    "ObjectiveTemplate": "node.objective",
    "ObservationBatch": "reference.observation_batch",
    "OverlapReview": "relation.overlap.independent",
    "ProgramContribution": "node.contribution",
    "Replacement": "relation.replacement",
    "ReplacementActivation": "relation.replacement",
    "Residual": "relation.residual",
    "SpecializedProgram": "operator.specialize",
    "TruthTest": "operator.known",
}


def validate_catalog() -> None:
    """New public nodes or enum alternatives require an explicit support review."""
    models = {name for name in net.__all__ if is_dataclass(getattr(net, name))}
    enums = (
        (get_args(net.PathKind), "path."),
        (get_args(net.Operation), "operator."),
        (get_args(net.TermKind), "role."),
        (get_args(get_type_hints(ex.Compare)["operator"]), "operator.compare."),
        (get_args(get_type_hints(net.AssessmentTerm)["baseline_relation"]), "baseline."),
        (get_args(get_type_hints(net.OverlapReview)["relation"]), "relation.overlap."),
        (get_args(get_type_hints(core.ObjectiveRelation)["kind"]), "relation.objective."),
    )
    expressions = {name for name in ex.__all__ if is_dataclass(getattr(ex, name))}
    if (
        models != _MODELS.keys()
        or expressions != {"All", "Any", "Not", "Compare", "BooleanLiteral"}
        or not set(_MODELS.values()) <= set(FEATURES)
        or len(set(FEATURES)) != len(FEATURES)
        or frozenset(FEATURES) != _COMMON | REFERENCE_ONLY
        or _COMMON & REFERENCE_ONLY
        or any(
            {prefix + value for value in values}
            != {feature for feature in FEATURES if feature.startswith(prefix)}
            for values, prefix in enums
            # operator includes other families; check that enum separately.
            if prefix != "operator."
        )
        or set(get_args(net.Operation)) != {"add", "multiply"}
        or set(get_args(get_type_hints(net.TruthTest)["state"])) != {"true", "false", "known"}
    ):
        raise ValueError("R2 support catalog has an unclassified public node or enum value")


# These core features have reference tests, but the current declaration/native
# adapter supplies no production permission or consumer-specific PDX witness.
REFERENCE_ONLY = frozenset(
    {
        "operator.multiply",
        "relation.alias",
        "relation.replacement",
        "relation.overlap.replacement",
        "relation.objective.conflicts",
        "relation.objective.coexists",
        "relation.objective.tradeoff",
        "relation.objective.priority",
        "reference.observation_batch",
        "reference.evaluation_result",
        "reference.selection",
    }
)
_COMMON = frozenset(
    {
        "node.action",
        "node.network",
        "node.network_program",
        "node.assessment_term",
        "node.effect_registry",
        "node.effect_instance",
        "node.contribution",
        "node.budget",
        "node.fact",
        "node.objective",
        "node.effect_account",
        "node.lineage",
        "node.assessment_group",
        "node.derived_predicate",
        "path.direct",
        "path.derived",
        "path.interaction",
        "operator.add",
        "operator.compare.eq",
        "operator.compare.ne",
        "operator.compare.lt",
        "operator.compare.le",
        "operator.compare.gt",
        "operator.compare.ge",
        "operator.all",
        "operator.any",
        "operator.not",
        "operator.known",
        "operator.literal",
        "operator.constant",
        "operator.specialize",
        "role.benefit",
        "role.cost",
        "role.risk",
        "baseline.new_consideration",
        "baseline.conditional_correction",
        "baseline.intentional_reweight",
        "relation.dependency_dag",
        "relation.variant",
        "relation.residual",
        "relation.overlap.independent",
        "relation.overlap.residual",
    }
)
_BASE_PROVEN = frozenset(
    {
        "node.action",
        "node.network",
        "node.network_program",
        "node.assessment_term",
        "node.effect_registry",
        "node.effect_instance",
        "node.contribution",
        "node.budget",
        "node.fact",
        "node.objective",
        "node.effect_account",
        "node.lineage",
        "node.assessment_group",
        "node.derived_predicate",
        "path.direct",
        "path.derived",
        "operator.add",
        "operator.compare.eq",
        "operator.compare.lt",
        "operator.all",
        "operator.any",
        "operator.known",
        "operator.constant",
        "operator.specialize",
        "role.benefit",
        "role.cost",
        "baseline.intentional_reweight",
        "relation.dependency_dag",
        "relation.overlap.independent",
    }
)
_PROVEN = {
    "a0-econ-road": _BASE_PROVEN | {"operator.not", "operator.compare.ge", "relation.variant"},
    "a0-pol-schools": _BASE_PROVEN
    | {"path.interaction", "relation.residual", "relation.overlap.residual", "role.risk"},
    "a0-dip-relations": _BASE_PROVEN
    | {"path.interaction", "relation.residual", "relation.overlap.residual", "role.risk"},
}
_LOWERABLE = {
    consumer: proven
    | {"operator.compare." + operator for operator in ("eq", "ne", "lt", "le", "gt", "ge")}
    | ({"path.interaction"} if consumer == "a0-econ-road" else set())
    for consumer, proven in _PROVEN.items()
}
_WITNESS = {
    "a0-econ-road": "tests/test_network_profile.py::test_road_literal_tiers_boundaries_recovery_and_actor_guard",
    "a0-pol-schools": "tests/test_network_profile.py::test_school_complete_costs_and_agenda_residual",
    "a0-dip-relations": "tests/test_network_profile.py::test_diplomacy_actual_influence_and_observed_target_pact",
}


def _used(program: net.NetworkProgram) -> dict[str, tuple[str, ...]]:
    """Record actual declaration/IR identities, including erased semantic nodes."""
    used: dict[str, set[str]] = {}

    def record(feature: str, identity: str) -> None:
        if feature not in FEATURES:
            raise ValueError(f"R2 support matrix: unknown feature {feature}")
        used.setdefault(feature, set()).add(identity)

    def expression(item: ex.Expression, identity: str) -> None:
        if isinstance(item, ex.Compare):
            record("operator.compare." + item.operator, identity)
        elif isinstance(item, (ex.All, ex.Any)):
            record("operator.all" if isinstance(item, ex.All) else "operator.any", identity)
            for child in item.items:
                expression(child, identity)
        elif isinstance(item, ex.Not):
            record("operator.not", identity)
            expression(item.item, identity)
        elif isinstance(item, net.TruthTest):
            record("operator.known", identity)
            expression(item.expression, identity)
        elif isinstance(item, net.FactKnown):
            record("operator.known", identity)
        elif isinstance(item, ex.BooleanLiteral):
            record("operator.literal", identity)
        else:
            raise ValueError("R2 support matrix: expression has no reviewed feature identity")

    network = program.network
    for feature in (
        "node.network",
        "node.network_program",
        "node.budget",
        "node.effect_registry",
        "operator.specialize",
    ):
        record(feature, network.actions[0].definition.id)
    for action in network.actions:
        record("node.action", action.definition.id)
        record("operator." + action.definition.operation, action.definition.id)
    for fact in network.facts:
        record("node.fact", fact.id)
    for objective in network.objectives:
        record("node.objective", objective.id)
        for relation in objective.relations:
            record("relation.objective." + relation.kind, objective.id)
    for account in network.registry.accounts:
        record("node.effect_account", account.id)
    for group in network.groups:
        record("node.assessment_group", group.id)
    for predicate in network.predicates:
        record("node.derived_predicate", predicate.id)
        record("relation.dependency_dag", predicate.id)
        expression(predicate.expression, predicate.id)
    for bridge in network.bridges:
        record("node.assessment_term", bridge.term.id)
        record("operator.constant", bridge.term.id)
        record("role." + bridge.term.kind, bridge.term.id)
        record("baseline." + bridge.term.baseline_relation, bridge.term.id)
        record("path." + bridge.path, bridge.id)
        record("relation.dependency_dag", bridge.id)
        expression(bridge.condition, bridge.id)
        if bridge.term.variant_group is not None:
            record("relation.variant", bridge.id)
    for alias in network.registry.aliases:
        record("relation.alias", alias.alias_id)
    for review in network.registry.overlaps:
        record("relation.overlap." + review.relation, review.left + ":" + review.right)
    for replacement in network.replacements:
        record("relation.replacement", replacement.id)
    for residual in network.residuals:
        record("relation.residual", residual.id)
    for contribution in program.contributions:
        record("node.effect_instance", contribution.effect.account_id)
        record("node.contribution", contribution.effect.account_id)
        record("node.lineage", contribution.effect.account_id)
        expression(contribution.guard, contribution.effect.account_id)
    return {name: tuple(sorted(identities)) for name, identities in used.items()}


def _validate_program(program: net.NetworkProgram, *, production: bool) -> None:
    validate_catalog()
    if type(program) is not net.NetworkProgram or len(program.network.actions) != 1:
        raise ValueError("R2 support matrix requires one canonical consumer program")
    if net.compile_action_network(program.network) != program:
        raise ValueError("R2 support matrix requires the canonical compiled program")
    consumer = program.network.actions[0].definition.consumer_id
    allowed = (_PROVEN if production else _LOWERABLE).get(consumer, frozenset())
    unproved = set(_used(program)) - allowed
    if consumer not in CONSUMERS or unproved:
        raise ValueError(
            f"R2 feature has no {'production_bound' if production else 'lowerable'} permission "
            f"in {consumer}: {sorted(unproved)}"
        )


def validate_production(program: net.NetworkProgram) -> None:
    """An accepted core program cannot self-authorize an unproved native feature."""
    _validate_program(program, production=True)


def validate_lowering(program: net.NetworkProgram) -> None:
    """The public native renderer cannot grant reference-only core capabilities."""
    _validate_program(program, production=False)


def matrix(
    profile: ProductionProfile, programs: tuple[net.NetworkProgram, ...]
) -> list[dict[str, object]]:
    """One row for every public feature and physical consumer, including disabled ones."""
    validate_catalog()
    declarations = {row.id: row for row in profile.declarations}
    if set(declarations) != set(CONSUMERS):
        raise ValueError("R2 support matrix consumer boundary differs from the reviewed adapter")
    active = {}
    for program in programs:
        validate_production(program)
        consumer = program.network.actions[0].definition.consumer_id
        if consumer in active:
            raise ValueError("R2 support matrix has a second physical writer")
        active[consumer] = _used(program)
    rows: list[dict[str, object]] = []
    for consumer in CONSUMERS:
        declaration = declarations[consumer]
        for feature in FEATURES:
            identities = active.get(consumer, {}).get(feature, ())
            lowered = feature in _LOWERABLE[consumer]
            status = (
                "production_bound" if identities else "lowerable" if lowered else "reference_only"
            )
            proof = (
                "tests/test_network_profile.py::test_supported_comparisons_have_independent_pdx_witness"
                if feature.startswith("operator.compare.")
                else "tests/test_network_profile.py::test_lowerable_path_does_not_authorize_production_policy"
                if consumer == "a0-econ-road" and feature == "path.interaction"
                else _WITNESS[consumer]
            )
            rows.append(
                {
                    "feature": feature,
                    "public_models": [name for name, value in _MODELS.items() if value == feature],
                    "consumer": consumer,
                    "status": status,
                    "adapter": "src/pdx/situated/network_profile.py",
                    "lowerer": "network_profile.render_program" if lowered else None,
                    "native_context": {
                        "actor": "scope:country" if consumer == "a0-econ-road" else "root",
                        "target": declaration.target,
                        "field": [declaration.definition, *declaration.field],
                        "source": declaration.source,
                    },
                    "source_maps": list(identities),
                    "witnesses": list(dict.fromkeys((_WITNESS[consumer], proof)))
                    if lowered
                    else ["tests/test_core_contracts.py"]
                    if feature == "reference.selection"
                    else ["tests/test_action_network.py"],
                    "production_eligible": feature in _PROVEN[consumer],
                    "boundary": "Current additive native adapter only; erased nodes map to guards, net contributions or retained context. Lowerable never grants a writer."
                    if lowered
                    else "Reference core only; no reviewed production operation or declaration-to-native binding.",
                    "runtime": "unknown",
                }
            )
    return rows
