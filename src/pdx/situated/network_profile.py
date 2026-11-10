"""R2 declaration -> shared symbolic program -> the three native consumers.

Readers are a closed, audited adapter capability set. Policy thresholds, effect
accounts and interactions live only in action_network_115.toml. No game state
is sampled or assumed at generation time.
"""

from __future__ import annotations

import hashlib
import math
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from pdx import decision_rules
from pdx.model import Block
from pdx.parser import parse_text

from . import action_network as net
from . import core_contracts as core
from . import expressions as ex
from . import production_profile as native
from . import r2_reader_authority as authority
from .profile_configuration import ProfileConfiguration

if TYPE_CHECKING:
    from pathlib import Path

SOURCE = native.ROOT / "mod/decisions/action_network_115.toml"
PROOF = "docs/design/exec/1.15-R2-A0-结果.md"
# docs/design/exec/1.15-A0-纵切合同.md#A0-BUDGET-LOCAL-ONLY
_ADDITIONAL_BLOCK_DEPTH = 3


@dataclass(frozen=True, slots=True)
class ReaderCapability:
    consumer: str
    reader: decision_rules.Reader
    binding: str
    kind: str
    unit: str
    source: str
    line: int

    def fact(self, ident: str) -> core.FactSpec:
        return core.FactSpec(
            ident,
            ident,
            cast("Any", self.kind),
            cast("Any", self.unit),
            "state" if self.binding == "target" and self.consumer == "a0-econ-road" else "country",
            cast("Any", self.binding),
            (self.consumer,),
            (core.EvidenceRef(self.source, self.line),),
            self.reader.minimum,
            self.reader.maximum,
        )


def _reader(
    consumer: str,
    engine: str,
    kind: str,
    unit: str,
    source: str,
    line: int,
    *,
    binding: str = "actor",
    path: tuple[str, ...] = (),
    argument: str | None = None,
    parameters: tuple[tuple[str, str], ...] = (),
    minimum: float | None = None,
    maximum: float | None = None,
) -> ReaderCapability:
    return ReaderCapability(
        consumer,
        decision_rules.Reader(
            engine,
            engine,
            "root",
            unit,
            kind,
            argument=argument,
            path=path,
            parameters=parameters,
            minimum=minimum,
            maximum=maximum,
        ),
        binding,
        "ratio" if unit == "ratio" else "boolean" if kind == "boolean" else "number",
        unit,
        source,
        line,
    )


# Capability evidence is scoped to exact native contexts; scope transfer proof
# and its limits are in the A0 receipt. No DLC ownership is inferred.
READERS = {
    "infrastructure": _reader(
        "a0-econ-road",
        "relative_infrastructure",
        "number",
        "ratio",
        "game/common/decrees/00_decree.txt",
        42,
        binding="target",
        minimum=0,
    ),
    "road-present": _reader(
        "a0-econ-road",
        "has_decree",
        "boolean",
        "boolean",
        "game/common/decrees/00_decree.txt",
        32,
        binding="target",
        argument="decree_road_maintenance",
    ),
    "literacy": _reader(
        "a0-pol-schools",
        "literacy_rate",
        "number",
        "ratio",
        "game/common/ai_strategies/01_admin_strategies.txt",
        79,
        minimum=0,
        maximum=1,
    ),
    "bureaucracy": _reader(
        "a0-pol-schools",
        "bureaucracy",
        "number",
        "points",
        "game/common/scripted_buttons/scripted_buttons.md",
        85,
    ),
    "default": _reader(
        "a0-pol-schools",
        "in_default",
        "boolean",
        "boolean",
        "game/common/alert_types/00_alert_types.txt",
        40,
    ),
    "school-agenda": _reader(
        "a0-pol-schools",
        "has_journal_entry",
        "boolean",
        "boolean",
        "game/common/ai_strategies/03_political_strategies.txt",
        135,
        argument="je_tp_pool_educational_reform",
    ),
    "protective": _reader(
        "a0-dip-relations",
        "has_attitude",
        "boolean",
        "boolean",
        "game/common/diplomatic_actions/00_relations_actions.txt",
        109,
        parameters=(("who", "scope:target_country"), ("attitude", "protective")),
    ),
    "influence": _reader(
        "a0-dip-relations",
        "influence",
        "number",
        "points",
        "game/common/diplomatic_actions/01_expel_diplomats.txt",
        153,
    ),
    "target-interference": _reader(
        "a0-dip-relations",
        "has_diplomatic_pact",
        "boolean",
        "boolean",
        "game/common/diplomatic_actions/01_expel_diplomats.txt",
        158,
        binding="target",
        path=("scope:target_country",),
        parameters=(("who", "root"), ("type", "support_separatism")),
    ),
}


def _fields(
    row: object, required: set[str], optional: set[str] | frozenset[str] = frozenset()
) -> dict[str, Any]:
    if type(row) is not dict or not required <= row.keys() or row.keys() - required - optional:
        raise ValueError(f"R2 declaration fields: expected {sorted(required)}")
    return row


def _ident(value: object, path: str) -> str:
    if type(value) is not str:
        raise ValueError(f"R2 {path}: stable id must be a string")
    core.stable_id(value, f"R2 {path}")
    return value


def _text(value: object, path: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"R2 {path}: nonempty text required")
    return value


def _array(value: object, path: str, *, nonempty: bool = True) -> list[Any]:
    if type(value) is not list or (nonempty and not value) or len(value) > 128:
        raise ValueError(f"R2 {path}: bounded {'nonempty ' if nonempty else ''}array required")
    return value


def _ids(value: object, path: str) -> tuple[str, ...]:
    result = tuple(_ident(item, path) for item in _array(value, path))
    if len(set(result)) != len(result):
        raise ValueError(f"R2 {path}: duplicate id")
    return result


def _number(value: object, path: str) -> float:
    try:
        valid = type(value) in (int, float) and math.isfinite(cast("float", value))
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"R2 {path}: finite numeric value required, never bool")
    return cast("float", value)


def _enum(value: object, allowed: set[str], path: str) -> str:
    if type(value) is not str or value not in allowed:
        raise ValueError(f"R2 {path}: unsupported value")
    return value


def _conditions(rows: object) -> tuple[ex.Expression, tuple[str, ...]]:
    comparisons = []
    identities = set()
    for item in _array(rows, "condition"):
        row = _fields(item, {"fact", "op", "value"})
        name = _ident(row["fact"], "condition.fact")
        operator = _enum(row["op"], {"eq", "ne", "gt", "ge", "lt", "le"}, "condition.op")
        value = row["value"]
        if type(value) is bool:
            if operator not in {"eq", "ne"}:
                raise ValueError("R2 boolean predicates support equality only")
        else:
            _number(value, "condition.value")
        identity = name, operator, type(value), value
        if identity in identities:
            raise ValueError("R2 duplicate condition")
        identities.add(identity)
        comparisons.append(ex.Compare(name, cast("Any", operator), value))
    return (
        comparisons[0] if len(comparisons) == 1 else ex.All(tuple(comparisons)),
        tuple(sorted({item.fact_id for item in comparisons})),
    )


def compile_profile(
    profile: native.ProductionProfile,
    *,
    source: Path = SOURCE,
    configuration: ProfileConfiguration | None = None,
) -> tuple[net.NetworkProgram, ...]:
    """Create one symbolic program per physical consumer, with one policy source."""
    authority.verify_frozen()
    if {
        name: capability.source for name, capability in READERS.items()
    } != authority.READER_SOURCES:
        raise ValueError("R2 reader authority coverage differs from adapter capabilities")
    configuration = ProfileConfiguration() if configuration is None else configuration
    if type(configuration) is not ProfileConfiguration:
        raise ValueError("R2 configuration must use the strict profile contract")
    with source.open("rb") as handle:
        declaration = tomllib.load(handle)
    _fields(declaration, {"schema", "game_version", "action"})
    if (
        declaration["schema"] != 2
        or type(declaration["schema"]) is not int
        or type(declaration["game_version"]) is not str
        or declaration["game_version"] != profile.game_version
    ):
        raise ValueError("R2 declaration version mismatch")
    programs = []
    seen = set()
    seen_actions = set()
    actions = _array(declaration["action"], "action")
    for raw_data in actions:
        data = _fields(
            raw_data,
            {"id", "consumer", "bounds", "required_facts", "objective", "bridge"},
            {"predicate", "overlap", "residual"},
        )
        action_id = _ident(data["id"], "action.id")
        consumer_id = _ident(data["consumer"], "action.consumer")
        required_facts = _ids(data["required_facts"], "action.required_facts")
        if action_id in seen_actions:
            raise ValueError("R2 duplicate action definition")
        seen_actions.add(action_id)
        if not set(required_facts) <= READERS.keys():
            raise ValueError("R2 required_facts must name canonical raw readers")
        row = next((item for item in profile.declarations if item.id == consumer_id), None)
        if row is None or row.id in seen:
            raise ValueError("R2 unknown consumer or second physical writer")
        seen.add(row.id)
        predicates = []
        for raw_item in _array(data.get("predicate", []), "action.predicate", nonempty=False):
            item = _fields(raw_item, {"id", "all"})
            condition, roots = _conditions(item["all"])
            predicates.append(
                net.DerivedPredicate(_ident(item["id"], "predicate.id"), condition, roots)
            )
        context = next(item.context for item in profile.contracts.consumers if item.id == row.id)
        binding = context.targets[0]
        kind = cast("core.EntityKind", "scalar" if binding.kind == "institution" else binding.kind)
        bounds = _array(data["bounds"], "action.bounds")
        if len(bounds) != 2:
            raise ValueError("R2 consumer bounds missing")
        lower, upper = (_number(value, "action.bounds") for value in bounds)
        definition = net.ActionDefinition(
            action_id, row.id, "add", "consumer_score", kind, 0, lower, upper
        )
        action = net.ActionInstance(
            definition,
            core.EntityKey("country", "actor"),
            core.EntityKey(kind, binding.name),
            core.TimeIdentity("native-on-demand", 0),
        )
        objectives = []
        for raw_objective in _array(data["objective"], "action.objective"):
            item = _fields(
                raw_objective,
                {
                    "id",
                    "actor",
                    "target",
                    "source_facts",
                    "baseline_fact",
                    "horizon",
                    "lifetime",
                    "rationale",
                },
            )
            if (
                _text(item["actor"], "objective.actor") != action.actor.id
                or action.target is None
                or _text(item["target"], "objective.target") != action.target.id
            ):
                raise ValueError("R2 objective actor/target differs from the native candidate")
            if item["horizon"] != "current" or item["lifetime"] != "evaluation":
                raise ValueError("R2 objective supports only the current evaluation lifetime")
            objectives.append(
                net.ObjectiveTemplate(
                    _ident(item["id"], "objective.id"),
                    action,
                    _ids(item["source_facts"], "objective.source_facts"),
                    _ident(item["baseline_fact"], "objective.baseline_fact"),
                    action.time,
                    action.time,
                    (_text(item["rationale"], "objective.rationale"), PROOF),
                )
            )
        accounts: dict[str, net.EffectAccount] = {}
        bridges = []
        for raw_item in _array(data["bridge"], "action.bridge"):
            item = _fields(
                raw_item,
                {
                    "id",
                    "path",
                    "effect",
                    "mechanism",
                    "objective",
                    "kind",
                    "value",
                    "all",
                    "rationale",
                },
                {"variant_group", "rank"},
            )
            bridge_id = _ident(item["id"], "bridge.id")
            effect_id = _ident(item["effect"], "bridge.effect")
            mechanism_id = _ident(item["mechanism"], "bridge.mechanism")
            objective_id = _ident(item["objective"], "bridge.objective")
            path = cast(
                "net.PathKind",
                _enum(item["path"], {"direct", "derived", "interaction"}, "bridge.path"),
            )
            role = cast(
                "net.TermKind", _enum(item["kind"], {"benefit", "cost", "risk"}, "bridge.kind")
            )
            value = _number(item["value"], "bridge.value")
            rationale = _text(item["rationale"], "bridge.rationale")
            if ("variant_group" in item) != ("rank" in item):
                raise ValueError("R2 variant_group and rank must be declared together")
            variant = (
                _ident(item["variant_group"], "bridge.variant_group")
                if "variant_group" in item
                else None
            )
            rank = item.get("rank", 0)
            if type(rank) is not int or rank < 0:
                raise ValueError("R2 variant rank must be a nonnegative integer, never bool")
            condition, roots = _conditions(item["all"])
            proof = (
                f"mod/decisions/action_network_115.toml#{bridge_id}: {rationale}",
                PROOF,
            )
            account = net.EffectAccount(
                effect_id,
                mechanism_id,
                role,
                row.id,
                "consumer_score",
                "current",
                "retained-native",
                (PROOF,),
                objective_id,
            )
            if account.id in accounts and accounts[account.id] != account:
                raise ValueError("R2 same effect has contradictory dimensions")
            accounts[account.id] = account
            term = net.AssessmentTerm(
                bridge_id + ".term",
                account.id,
                role,
                net.Constant(value),
                action_id + (".interaction" if path == "interaction" else ".complete"),
                variant_group=variant,
                variant_rank=rank,
                variant_review=proof if "variant_group" in item else (),
                baseline_relation="intentional_reweight",
            )
            bridges.append(
                net.ActionBridge(
                    bridge_id,
                    action,
                    path,
                    account.id,
                    term,
                    roots,
                    condition,
                    roots,
                    roots if path != "direct" else (),
                )
            )
        fact_ids = {root for bridge in bridges for root in bridge.source_ids}
        fact_ids.update(root for predicate in predicates for root in predicate.source_ids)
        fact_ids.update(required_facts)
        fact_ids.update(name for objective in objectives for name in objective.source_fact_ids)
        fact_ids -= {item.id for item in predicates}
        if any(name not in READERS or READERS[name].consumer != row.id for name in fact_ids):
            raise ValueError("R2 reader has no authority in this native consumer")
        facts = tuple(READERS[name].fact(name) for name in sorted(fact_ids))
        groups = tuple(
            net.AssessmentGroup(
                group_id,
                tuple(item.term.id for item in bridges if item.term.group_id == group_id),
                required_fact_ids=required_facts,
                review_sources=(PROOF,),
            )
            for group_id in sorted({item.term.group_id for item in bridges})
        )
        overlaps = tuple(
            net.OverlapReview(
                _ident(item["left"], "overlap.left"),
                _ident(item["right"], "overlap.right"),
                cast(
                    "Any",
                    _enum(
                        item["relation"],
                        {"independent", "replacement", "residual"},
                        "overlap.relation",
                    ),
                ),
                (_text(item["rationale"], "overlap.rationale"),),
            )
            for item in (
                _fields(value, {"left", "right", "relation", "rationale"})
                for value in _array(data.get("overlap", []), "action.overlap", nonempty=False)
            )
        )
        residuals = tuple(
            net.Residual(
                _ident(item["id"], "residual.id"),
                _ids(item["bases"], "residual.bases"),
                _ident(item["effect"], "residual.effect"),
                net.Constant(_number(item["complete"], "residual.complete")),
                (_text(item["rationale"], "residual.rationale"),),
            )
            for item in (
                _fields(value, {"id", "bases", "effect", "complete", "rationale"})
                for value in _array(data.get("residual", []), "action.residual", nonempty=False)
            )
        )
        network = net.ActionNetwork(
            (action,),
            tuple(bridges),
            groups,
            net.EffectRegistry(tuple(accounts.values()), overlaps=overlaps),
            facts=facts,
            predicates=tuple(predicates),
            residuals=residuals,
            objectives=tuple(objectives),
            budget=net.NetworkBudget(
                max_bridges=16, max_edges=48, max_fanout=12, max_depth=8, max_guard_nodes=2048
            ),
        )
        program = net.compile_action_network(network)
        if row.domain in configuration.enabled_domains:
            programs.append(program)
    if seen != {item.id for item in profile.declarations}:
        raise ValueError("R2 missing physical consumer declaration")
    return tuple(programs)


def _negate_boolean(condition: ex.Expression) -> ex.Expression:
    """对已专门化的二值 guard 取对偶，不分配条件组合或真值表。"""
    if isinstance(condition, ex.BooleanLiteral) and type(condition.value) is bool:
        return ex.BooleanLiteral(not condition.value)
    if isinstance(condition, ex.Not):
        return condition.item
    if isinstance(condition, ex.All):
        return ex.Any(tuple(_negate_boolean(item) for item in condition.items))
    if isinstance(condition, ex.Any):
        return ex.All(tuple(_negate_boolean(item) for item in condition.items))
    return ex.Not(condition)


def _simplify_boolean(condition: ex.Expression) -> ex.Expression:
    """仅在 knownness 专门化之后应用二值恒等式，保持线性形式的 DAG。

    合取/析取同类展开、幂等、互补和吸收不枚举条件子集。原始三值
    条件不能直接经过此函数；unknown 的局部退出先由 specialize 保证。
    """
    if isinstance(condition, ex.Not):
        if isinstance(condition.item, ex.Compare):
            return condition
        return _simplify_boolean(_negate_boolean(condition.item))
    if not isinstance(condition, (ex.All, ex.Any)):
        return condition
    conjunction = isinstance(condition, ex.All)
    kind = ex.All if conjunction else ex.Any
    identity = ex.BooleanLiteral(conjunction)
    absorbing = ex.BooleanLiteral(not conjunction)
    items: list[ex.Expression] = []
    for child in condition.items:
        simplified = _simplify_boolean(child)
        if simplified == absorbing:
            return absorbing
        if simplified == identity:
            continue
        items.extend(simplified.items if isinstance(simplified, kind) else (simplified,))
    unique = tuple(dict.fromkeys(items))
    available = set(unique)
    kept = []
    for item in unique:
        inverse = _negate_boolean(item)
        # A and not A, or A or not A. For an opposite junction, its
        # flattened dual can occur as several siblings: (a and b) or !a or !b.
        if inverse in available or (isinstance(inverse, kind) and set(inverse.items) <= available):
            return absorbing
        # a and (a or b) = a; a or (a and b) = a.
        if (
            isinstance(item, (ex.All, ex.Any))
            and not isinstance(item, kind)
            and any(child in available for child in item.items)
        ):
            continue
        kept.append(item)
    if not kept:
        return identity
    return kept[0] if len(kept) == 1 else kind(tuple(kept))


def _render_condition(
    condition: ex.Expression, consumer: str, *, implicit_and: bool = False
) -> str:
    if isinstance(condition, ex.BooleanLiteral) and type(condition.value) is bool:
        return "always = yes" if condition.value else "always = no"
    if isinstance(condition, ex.Compare):
        capability = READERS.get(condition.fact_id)
        if capability is None or capability.consumer != consumer:
            raise ValueError("R2 predicate reader has no authority in this consumer")
        operators = {"eq": "=", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}
        if condition.operator not in operators:
            raise ValueError("R2 unsupported predicate operator")
        operator = operators[condition.operator]
        value = condition.expected
        if not capability.reader.accepts(value):
            raise ValueError("R2 predicate value outside reader domain")
        statement = capability.reader.expression(
            "=" if operator == "!=" else operator, cast("Any", value)
        )
        for scope in reversed(capability.reader.path):
            statement = f"{scope} = {{ {statement} }}"
        return f"NOT = {{ {statement} }}" if operator == "!=" else statement
    if isinstance(condition, (ex.All, ex.Any)):
        operator = "AND" if isinstance(condition, ex.All) else "OR"
        contents = " ".join(_render_condition(item, consumer) for item in condition.items)
        if implicit_and and isinstance(condition, ex.All):
            return contents
        return operator + " = { " + contents + " }"
    if isinstance(condition, ex.Not):
        return "NOT = { " + _render_condition(condition.item, consumer) + " }"
    raise ValueError("R2 expression is reference-only, no PDX lowering")


def render_program(program: net.NetworkProgram, *, available: tuple[str, ...] | None = None) -> str:
    """Lower one audited context using either supported numeric algebra.

    Multiplication here is a shared lowering capability. The three installed
    profile declarations authorize additive overlays only; this function does
    not grant a different write operation to those physical insertion points.
    """
    if type(program) is not net.NetworkProgram or len(program.network.actions) != 1:
        raise ValueError("R2 renderer requires exactly one action in one consumer")
    if not program.network.objectives:
        raise ValueError(
            "R2 renderer requires a real ObjectiveTemplate; relative preference is reference-only"
        )
    if net.compile_action_network(program.network) != program:
        raise ValueError("R2 renderer requires the canonical compiled program")
    action = program.network.actions[0]
    consumer = action.definition.consumer_id
    contexts = {
        "a0-econ-road": ("state", "root"),
        "a0-pol-schools": ("scalar", "institution_schools"),
        "a0-dip-relations": ("country", "target_country"),
    }
    if (
        consumer not in contexts
        or action.actor != core.EntityKey("country", "actor")
        or action.time != core.TimeIdentity("native-on-demand", 0)
        or action.target is None
        or (action.target.kind, action.target.id) != contexts[consumer]
        or action.bindings
    ):
        raise ValueError("R2 renderer has no native authority for this candidate context")
    for fact in program.network.facts:
        capability = READERS.get(fact.id)
        if (
            capability is None
            or capability.consumer != consumer
            or fact != capability.fact(fact.id)
        ):
            raise ValueError("R2 renderer fact declaration differs from audited reader capability")
    known = tuple(fact.id for fact in program.network.facts) if available is None else available
    lowered = net.specialize_program(program, known)
    operation = action.definition.operation
    if operation not in {"add", "multiply"}:
        raise ValueError("R2 renderer has no lowering for this numeric algebra")
    ai = (
        "exists = country country = { is_ai = yes }"
        if action.target and action.target.kind == "state"
        else "is_ai = yes"
    )
    # Schools has a depth-zero native numeric body. Its ordinary country
    # readers also apply to player countries, so put AI on each contribution.
    # No active terms leaves the neutral inside the declared bounds. Keep the
    # outer guard for road/diplomacy: their native depth allows it and this does
    # not grant AI-only diplomacy reader contexts to players or assume trigger
    # short-circuiting. Only the bounded add/multiply block owns the score.
    outer_ai_guard = consumer != "a0-pol-schools"
    prefix = "\t\t\t" if outer_ai_guard else "\t\t"
    lines = [f"\t\tif = {{ limit = {{ {ai} }}"] if outer_ai_guard else []
    lines += [f"{prefix}{operation} = {{", f"{prefix}\tvalue = {action.definition.neutral:.17g}"]
    for item in lowered.contributions:
        lines.append(
            f"{prefix}\t# effect {item.effect.account_id}; bridges {','.join(item.bridge_ids)}"
        )
        condition = _render_condition(_simplify_boolean(item.guard), consumer, implicit_and=True)
        lines.append(
            f"{prefix}\tif = {{ limit = {{ "
            + ("" if outer_ai_guard else ai + " ")
            + condition
            + f" }} {operation} = {item.value:.17g} }}"
        )
    lines += [
        f"{prefix}\tmin = {action.definition.lower:.17g}",
        f"{prefix}\tmax = {action.definition.upper:.17g}",
        f"{prefix}}}",
    ]
    if outer_ai_guard:
        lines.append("\t\t}")
    return "\n".join(lines) + "\n"


def _native_tail_impact(action: net.ActionInstance) -> dict[str, object]:
    """Bound a same-observation delta at this physical consumer, not AI outcomes.

    The frozen insertion points are deliberately different: road maintenance
    inserts after its initial value, while schools and relations append after
    their complete native numeric bodies. These statements rely on the pinned
    native bytes verified by compile_profile, not on sampled engine state.
    """
    definition = action.definition
    impact: dict[str, object] = {
        "evidence": "static_native_source_arithmetic",
        "runtime": "unknown",
        "comparison": "generated minus native consumer value at the same observations",
        "selection_and_execution_effect": "unknown",
    }
    if definition.consumer_id == "a0-econ-road":
        impact.update(
            {
                "insertion_position": "after initial value = 25, before the native tail",
                "delta_formula": "insertion_delta * native_zero_factor * capital_factor * home_state_factor",
                "native_zero_factor": [0, 1],
                "capital_factor": [1, 1.5],
                "home_state_factor": [1, 1.5],
                "conservative_delta_envelope": [definition.lower * 2.25, definition.upper * 2.25],
                "envelope_kind": "conservative; endpoints need not be reachable by the declared policy",
                "zero_behavior": (
                    "Native multiply = 0 cancels the insertion delta. Later native journal "
                    "additions can restore the total native score and remain unchanged."
                ),
            }
        )
    else:
        impact.update(
            {
                "insertion_position": "end of the complete native consumer numeric body",
                "delta_formula": "insertion_delta",
                "conservative_delta_envelope": [definition.lower, definition.upper],
                "envelope_kind": "physical consumer only; not a final AI decision bound",
                "following_numeric_operations": [],
            }
        )
        impact["native_context"] = (
            "The default school score starts at 10; other strategies contribute additively. "
            "Their active values and subsequent engine selection are unknown."
            if definition.consumer_id == "a0-pol-schools"
            else "The native subject-relation multiply = 2 precedes this insertion, so it "
            "does not scale the insertion delta. Eligibility, probability and execution "
            "remain native; their downstream effect is unknown."
        )
    return impact


def audit(
    profile: native.ProductionProfile,
    *,
    configuration: ProfileConfiguration | None = None,
    source: Path = SOURCE,
) -> dict[str, object]:
    """Describe the actual lowered programs, never the old neutral contract bounds."""
    programs = compile_profile(profile, configuration=configuration, source=source)
    return {
        "architecture": "R2/action-network-v2",
        "source": source.relative_to(native.ROOT).as_posix(),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "evidence": "static_symbolic_lowering",
        "runtime": "unknown",
        "programs": [
            {
                "consumer": program.network.actions[0].definition.consumer_id,
                "action": program.network.actions[0].definition.id,
                "insertion_bounds": [
                    program.network.actions[0].definition.lower,
                    program.network.actions[0].definition.upper,
                ],
                "native_tail": _native_tail_impact(program.network.actions[0]),
                "readers": [
                    {
                        "id": fact.id,
                        "binding": fact.binding,
                        "source": READERS[fact.id].source,
                        "line": READERS[fact.id].line,
                    }
                    for fact in program.network.facts
                ],
                "bridges": [
                    {
                        "id": bridge.id,
                        "path": bridge.path,
                        "effect": bridge.effect_id,
                        "group": bridge.term.group_id,
                    }
                    for bridge in program.network.bridges
                ],
                "objectives": [
                    {
                        "id": objective.id,
                        "actor": {
                            "kind": objective.action.actor.kind,
                            "id": objective.action.actor.id,
                        },
                        "target": {
                            "kind": objective.action.target.kind,
                            "id": objective.action.target.id,
                        }
                        if objective.action.target is not None
                        else None,
                        "sources": list(objective.source_fact_ids),
                        "baseline_fact": objective.baseline_fact_id,
                        "baseline_value": "read from the same evaluation; never sampled at generation",
                        "horizon": objective.horizon,
                        "lifetime": objective.lifetime,
                        "score_comparison_baseline": "retained-native",
                    }
                    for objective in program.network.objectives
                ],
                "effects": [
                    {
                        "account": item.effect.account_id,
                        "value": item.value,
                        "bridges": list(item.bridge_ids),
                    }
                    for item in net.specialize_program(
                        program, tuple(fact.id for fact in program.network.facts)
                    ).contributions
                ],
            }
            for program in programs
        ],
    }


def _consumer_block_depth(text: str, row: native.ConsumerDeclaration) -> int:
    """从实际输出独立解析物理消费者；根块深度为零，包含匿名块。"""
    parsed = parse_text(text, row.source)
    if parsed.errors:
        raise ValueError("R2 generated PDX failed parsing")
    current = parsed.root
    for key in (row.definition, *row.field):
        matches = current.all(key)
        if len(matches) != 1 or not isinstance(matches[0].value, Block):
            raise ValueError("R2 generated consumer missing or ambiguous during depth check")
        current = matches[0].value
    pending = [(current, 0)]
    maximum = 0
    while pending:
        block, depth = pending.pop()
        maximum = max(maximum, depth)
        pending.extend(
            (item.value, depth + 1) for item in block.assignments() if isinstance(item.value, Block)
        )
        pending.extend((item, depth + 1) for item in block.items if isinstance(item, Block))
    return maximum


def build(
    profile: native.ProductionProfile,
    *,
    configuration: ProfileConfiguration | None = None,
    baseline_root: Path = native.BASELINE_ROOT,
    source: Path = SOURCE,
) -> dict[str, str]:
    native.verify_baseline(baseline_root)
    if profile != native.load_profile(baseline_root):
        raise ValueError("R2 profile differs from frozen native contract")
    by_consumer = {
        item.network.actions[0].definition.consumer_id: item
        for item in compile_profile(profile, source=source, configuration=configuration)
    }
    files = {}
    for row in profile.declarations:
        raw = (baseline_root / row.source).read_bytes()
        original = raw.decode("utf-8-sig")
        program = by_consumer.get(row.id)
        text = (
            original
            if program is None
            else native._insert_policy(original, row, render_program(program))
        )
        if program is not None and native.strip_policy(text, row) != original:
            raise ValueError("R2 insertion changed native protected content")
        native_depth = _consumer_block_depth(original, row)
        generated_depth = _consumer_block_depth(text, row)
        if generated_depth > native_depth + _ADDITIONAL_BLOCK_DEPTH:
            raise ValueError(
                f"R2 A0-BUDGET-LOCAL-ONLY block depth exceeded for {row.id}: "
                f"native={native_depth}, generated={generated_depth}, "
                f"maximum additional={_ADDITIONAL_BLOCK_DEPTH}"
            )
        files[row.source.removeprefix("game/")] = text
    return files
