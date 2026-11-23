"""具体付费动员的材料权衡，保留编队 ROOT 与所属国家角色。

Bind original source and AST digests, derive joint-program inputs, and retain
native utility multiplication, monetary costs, eligibility and effects.
The bounded comparison is for diagnostic replay. Engine execution is native.
"""

from __future__ import annotations

import hashlib
import json
import math
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING, Any, Literal, cast

from . import config, decision_rules, version_contracts
from .model import Assignment, Block, Scalar
from .parser import parse_text
from .situated.core_contracts import stable_id
from .textio import normalized_text

if TYPE_CHECKING:
    from pathlib import Path

    from .situated.core_contracts import EntityKey, TimeIdentity

BASELINE_SHA256 = "46a17a140bd2a7e38acdc2faed1d8838238353d07a8175ae60c67f8a2247257b"


def baseline_path() -> Path:
    return version_contracts.research_path("situated", "mobilization-opportunities.json")


def baseline_sha256() -> str:
    version_contracts.require_current()
    return BASELINE_SHA256


PARAMETERS = config.REPO / "mod/decisions/mobilization_opportunities.toml"
SOURCE = "common/mobilization_options/00_mobilization_option.txt"
_DOC = "common/mobilization_options/mobilization_options.md"
_OWNER = "common/on_actions/00_code_on_actions.txt"
_COUNTRY = "events/tech_events/trench_warfare.txt"
_MODIFIER = "common/modifier_type_definitions/00_modifier_types.txt"
_REQUIRED = frozenset({SOURCE, _DOC, _OWNER, _COUNTRY, _MODIFIER})
_AI_DEFINES = "common/defines/00_ai.txt"
_AI_DEFINES_SHA256 = "a1c49bb95f9c3cd57375253fce7026ff90f5ca11635f61bfca95799ca029eff8"
_OPTION_DEFINES = {
    "MOBILIZATION_OPTION_RANDOM_FACTOR": Fraction(1, 2),
    "MOBILIZATION_OPTION_MONEY_COST_FACTOR": Fraction(20),
    "MOBILIZATION_OPTION_NUM_ACTIVE_OPTIONS_DIVISOR": Fraction(1, 4),
    "MOBILIZATION_OPTION_GOODS_SHORTAGE_MULT": Fraction(0),
    "MOBILIZATION_OPTIONS_MIN_EXTRA_EXPENSE_RATIO": Fraction(1, 10),
    "MOBILIZATION_OPTIONS_MAX_EXTRA_EXPENSE_RATIO": Fraction(1),
    "MOBILIZATION_OPTIONS_EXPENSE_HYSTERESIS": Fraction(1, 10),
}
_BASKETS = {
    "mobilization_option_first_aid": {"fabric": "1", "liquor": "2"},
    "mobilization_option_field_hospitals": {"opium": "2", "tools": "1"},
}
_RECOVERY = {
    "mobilization_option_first_aid": "0.10",
    "mobilization_option_field_hospitals": "0.20",
}
# 只处理原版有已证非零效用且具有直接投入的可选项。未按编制缩放的
# 武器加成取决于实际单位组成；没有组成观测时保留原版货币比较，不猜数量。
_ADDITIONAL_BASKETS = {
    "extra_supplies": {"groceries": "1.5"},
    "luxurious_supplies": {"meat": "1.5", "wine": "1.5"},
    "chocolate": {"sugar": "1"},
    "tobacco": {"tobacco": "0.5"},
    "liquor": {"liquor": "0.5"},
    "opium": {"opium": "0.5"},
    "truck_transport": {"automobiles": "0.5"},
    "rail_transport": {"engines": "0.5"},
    "machinegunners": {"small_arms": "1", "ammunition": "1"},
    "chemical_weapons": {"fertilizer": "2"},
    "flamethrowers": {"oil": "1"},
    "motorized_recon": {"automobiles": "1", "oil": "0.5"},
    "balloon_recon": {"fabric": "2", "oil": "0.5"},
}
_ALL_BASKETS = {
    **_BASKETS,
    **{f"mobilization_option_{name}": goods for name, goods in _ADDITIONAL_BASKETS.items()},
}
CANDIDATE_IDS = frozenset(_ALL_BASKETS)
_UTILITY = {
    "extra_supplies": ("unit_offense_mult", "0.1", "10000"),
    "luxurious_supplies": ("unit_offense_mult", "0.1", "10000"),
    "chocolate": ("unit_morale_recovery_mult", "0.1", "5000"),
    "tobacco": ("unit_morale_recovery_mult", "0.1", "5000"),
    "liquor": ("unit_morale_recovery_mult", "0.1", "5000"),
    "opium": ("unit_morale_recovery_mult", "0.1", "5000"),
    "truck_transport": ("military_formation_army_movement_speed_mult", "0.3", "10000"),
    "rail_transport": ("military_formation_army_movement_speed_mult", "0.2", "10000"),
    "machinegunners": ("unit_defense_add", "10", "100"),
    "chemical_weapons": ("unit_offense_add", "20", "100"),
    "flamethrowers": ("unit_offense_add", "15", "100"),
    "motorized_recon": ("military_formation_army_movement_speed_mult", "0.3", "10000"),
    "balloon_recon": ("military_formation_attrition_risk_mult", "-0.2", "-5000"),
}
_CONTRACT = {
    "native_root": "military_formation",
    "actor": "country",
    "actor_path": ["owner"],
    "target": "none",
    "candidate": "static_definition",
    "field": "ai_weight",
    "operation": "multiplicative_score",
    "supported_shape": "block",
    "native_comparison": "ai_weight_times_unit_modifier_ai_value_then_monetary_cost",
    "evidence": "native_documentation_and_exact_script_not_runtime",
}
_PARAMETERS = frozenset(
    {
        "priority_base",
        "war_need_multiplier",
        "scarcity_multiplier",
        "price_pressure_multiplier",
        "default_multiplier",
        "pressure_price_threshold",
    }
)


type SupplyOption = Literal["extra_supplies", "luxurious_supplies"]
type SupplyControl = Literal["ai", "player", "unknown"]

EXTRA_SUPPLIES = "extra_supplies"
LUXURIOUS_SUPPLIES = "luxurious_supplies"
_SUPPLY_TECH = {EXTRA_SUPPLIES: "army_reserves", LUXURIOUS_SUPPLIES: "military_statistics"}
_SUPPLY_GOODS = {EXTRA_SUPPLIES: ("groceries",), LUXURIOUS_SUPPLIES: ("meat", "wine")}
_SUPPLY_SECTIONS = {
    EXTRA_SUPPLIES: {
        "possible": "e17eb44754eaf1fb94edb97617429a14c5b5d2593eb74502986438fea5a6ceac",
        "unlocking_technologies": "9caf52afd3fabdd812234510862293a53e3b06a4d296d74689af3480012b4019",
    },
    LUXURIOUS_SUPPLIES: {
        "possible": "44cf676127884b0d5a8d234f5f60d521996b5d278d5f05607b4c05c7d13e3964",
        "unlocking_technologies": "3426c41db31b39092dfbe3c6b0ead91899f94020bc1174791cf87ae6e3897429",
    },
}
_SUPPLY_WITHDRAWAL = "4aad402343d34bf38f0e1c980f2da465cd6b2324ca03248d23c0ff840d03c39e"


@dataclass(frozen=True, slots=True)
class SupplyOpportunity:
    """Actual native consideration of one option for the current formation.

    The time epoch identifies the current game timeline. The control epoch
    covers uninterrupted control and ownership of this formation.
    """

    actor: EntityKey
    formation: EntityKey
    option: SupplyOption
    time: TimeIdentity
    control: SupplyControl
    control_epoch: str
    provided: bool

    def __post_init__(self) -> None:
        if (
            self.actor.kind != "country"
            or self.formation.kind != "military_formation"
            or self.option not in _SUPPLY_GOODS
            or self.control not in {"ai", "player", "unknown"}
        ):
            raise ValueError("补给机会的国家、编队或相位无效")
        stable_id(self.control_epoch, "SupplyOpportunity.control_epoch")


@dataclass(frozen=True, slots=True)
class SupplyObservation:
    """Locally known state captured within the continuous control epoch.

    Reacquire observations when the game timeline or formation control changes.
    """

    actor: EntityKey
    formation: EntityKey
    occurred_at: int
    learned: TimeIdentity
    control_epoch: str
    valid_until: int
    extra_enabled: bool | None
    extra_in_effect: bool | None
    technologies: frozenset[str] | None
    potential_supply: frozenset[str] | None

    def __post_init__(self) -> None:
        if (
            self.actor.kind != "country"
            or self.formation.kind != "military_formation"
            or not 0 <= self.occurred_at <= self.learned.evaluation <= self.valid_until
            or (self.extra_in_effect is True and self.extra_enabled is not True)
        ):
            raise ValueError("补给观察的主体、时序或生效状态无效")
        stable_id(self.control_epoch, "SupplyObservation.control_epoch")


@dataclass(frozen=True, slots=True)
class SupplyEligibility:
    """Facts usable by the two native readers and by settlement evaluation."""

    eligible: bool | None
    extra_in_effect: bool | None


def supply_eligibility(
    opportunity: SupplyOpportunity, observation: SupplyObservation | None
) -> SupplyEligibility:
    """Check the named native gates at an actual AI opportunity."""
    if (
        not opportunity.provided
        or opportunity.control != "ai"
        or observation is None
        or (opportunity.actor, opportunity.formation) != (observation.actor, observation.formation)
        or opportunity.time.epoch != observation.learned.epoch
        or opportunity.control_epoch != observation.control_epoch
        or not observation.learned.evaluation
        <= opportunity.time.evaluation
        <= observation.valid_until
    ):
        return SupplyEligibility(None, None)
    technology = _SUPPLY_TECH[opportunity.option]
    goods = _SUPPLY_GOODS[opportunity.option]
    gates = [
        None if observation.technologies is None else technology in observation.technologies,
        None
        if observation.potential_supply is None
        else set(goods) <= observation.potential_supply,
    ]
    if opportunity.option == LUXURIOUS_SUPPLIES:
        gates.append(observation.extra_enabled)
    eligible = False if False in gates else True if all(gates) else None
    return SupplyEligibility(eligible, observation.extra_in_effect)


def supply_withdrawal_morale_change(morale: Fraction, *, mobilized: bool) -> Fraction:
    """Reference value for one observed vanilla deactivation, per combat unit."""
    if morale < 0:
        raise ValueError("撤销前的士气不能为负")
    return -morale / 2 if mobilized else Fraction(0)


@dataclass(frozen=True, slots=True)
class SupplyComparisonObservation:
    """Same-call original candidate inputs for the unactivated option comparison.

    Count all options the engine classifies as already active in this formation.
    Input shortage is the engine classification for this option's inputs.
    A partial option list, trade deficit or potential supply cannot fill these facts.
    The evidence recorder assigns a stable ID unique to each evaluation within the
    timeline, even when the game time, formation and candidate are identical.
    """

    opportunity: SupplyOpportunity
    evaluation_id: str
    candidate_active: bool | None
    active_options: int | None
    input_shortage: bool | None
    weighted_utility: Fraction | None = None
    monetary_cost: Fraction | None = None

    def __post_init__(self) -> None:
        stable_id(self.evaluation_id, "SupplyComparisonObservation.evaluation_id")
        if self.active_options is not None and (
            type(self.active_options) is not int or self.active_options < 0
        ):
            raise ValueError("已启用选项数量必须为非负整数")
        if self.monetary_cost is not None and self.monetary_cost < 0:
            raise ValueError("原版货币成本必须为非负数")


@dataclass(frozen=True, slots=True)
class SupplyComparison:
    """Bounds on only the documented adjustments, before unverified engine stages."""

    active_option_factor: tuple[Fraction, Fraction]
    adjusted_utility: tuple[Fraction, Fraction] | None
    scaled_monetary_cost: Fraction | None


def compare_supply_activation(
    opportunity: SupplyOpportunity,
    observed: SupplyComparisonObservation | None,
    *,
    evaluation_id: str,
) -> SupplyComparison | None:
    """Replay documented factors using the original recorded evaluation identity."""
    stable_id(evaluation_id, "compare_supply_activation.evaluation_id")
    if (
        not opportunity.provided
        or opportunity.control != "ai"
        or observed is None
        or observed.opportunity != opportunity
        or observed.evaluation_id != evaluation_id
        or observed.candidate_active is not False
    ):
        return None
    zero, one = Fraction(0), Fraction(1)
    count = observed.active_options
    if count is None:
        active_option_factor = (zero, one)
    else:
        factor = one / (
            one + count * _OPTION_DEFINES["MOBILIZATION_OPTION_NUM_ACTIVE_OPTIONS_DIVISOR"]
        )
        active_option_factor = (factor, factor)
    lower, upper = active_option_factor
    shortage_factor = _OPTION_DEFINES["MOBILIZATION_OPTION_GOODS_SHORTAGE_MULT"]
    if observed.input_shortage is True:
        lower *= shortage_factor
        upper *= shortage_factor
    elif observed.input_shortage is None:
        lower *= shortage_factor

    utility = observed.weighted_utility
    if zero in (upper, utility):
        adjusted = (zero, zero)
    elif utility is None:
        adjusted = None
    else:
        adjusted = (min(utility * lower, utility * upper), max(utility * lower, utility * upper))
    cost = observed.monetary_cost
    return SupplyComparison(
        active_option_factor,
        adjusted,
        None if cost is None else cost * _OPTION_DEFINES["MOBILIZATION_OPTION_MONEY_COST_FACTOR"],
    )


def verify_supply_comparison(game: Path) -> dict[str, Any]:
    """Verify independent installed bytes and exact scalar AST for the native operation."""
    version_contracts.require_current()
    raw = (game / _AI_DEFINES).read_bytes()
    if hashlib.sha256(raw).hexdigest() != _AI_DEFINES_SHA256:
        raise ValueError("原版动员比较定义原字节漂移")
    parsed = parse_text(raw.decode("utf-8-sig"), path=_AI_DEFINES)
    if parsed.errors:
        raise ValueError("原版动员比较定义解析失败")
    evidence = {}
    for key, expected in _OPTION_DEFINES.items():
        node = _node(parsed.root, "NAI", key)
        if (
            not isinstance(node.value, Scalar)
            or node.value.quoted
            or Fraction(node.value.text) != expected
        ):
            raise ValueError(f"原版动员比较定义值漂移：{key}")
        evidence[key] = _record(node)
    return evidence


def supply_chain_contract(baseline: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Expose the exact gates and effects for separately owned native phases."""
    data = load_baseline() if baseline is None else _validate(dict(baseline))
    return _supply_chain_contract(data)


def _supply_chain_contract(data: Mapping[str, Any]) -> dict[str, Any]:
    stages = {}
    for option, hashes in _SUPPLY_SECTIONS.items():
        option_id = f"mobilization_option_{option}"
        row = data["candidates"][option_id]
        sections = row["sections"]
        required = {**hashes, "on_deactivate_while_mobilized": _SUPPLY_WITHDRAWAL}
        if any(sections[key]["sha256"] != digest for key, digest in required.items()):
            raise ValueError(f"原版动员补给资格或撤销语义漂移：{option_id}")
        stages[option] = {
            "field": row["field"],
            "definition": dict(row["definition"]),
            "bootstrap_technology": _SUPPLY_TECH[option],
            "potential_supply_goods": list(_SUPPLY_GOODS[option]),
            "upkeep_goods": dict(row["goods"]),
            "proof": {key: dict(sections[key]) for key in required},
        }
    return {
        "source": SOURCE,
        "actor_path": ["owner"],
        "native_root": "military_formation",
        "stages": stages,
        "eligibility_operator": {
            "field": "mobilization_option_luxurious_supplies.possible",
            "scope": "scope:military_formation",
            "trigger": "has_mobilization_option",
            "value": "mobilization_option:mobilization_option_extra_supplies",
        },
        "withdrawal_effect": {"scope": "combat_unit", "morale_change_ratio": "-0.5"},
        "native_activation_comparison": {
            "source": _AI_DEFINES,
            "source_sha256": _AI_DEFINES_SHA256,
            "defines": {key: str(value) for key, value in _OPTION_DEFINES.items()},
            "phase": "non_activated_candidate_on_same_formation",
            "observation_identity": "recorded_evaluation_id_unique_within_timeline",
            "operation": "divide_by_one_plus_active_options_times_define",
            "unverified": ["native_order", "rank", "acceptance", "execution"],
        },
        "projection": "native_rules_only_pending_calibration",
    }


def verify_generated_supply_stages(
    text: str, selected_fields: set[tuple[str, ...]], *, expected: str
) -> dict[str, object]:
    """Check shipped native definitions around the single owned weight extension."""
    contract = supply_chain_contract()
    parsed = parse_text(text, path=SOURCE)
    authorized = parse_text(expected, path=SOURCE)
    if parsed.errors or authorized.errors:
        raise ValueError("生产补给阶段无法回读")
    verified: dict[str, object] = {}
    for option, stage in contract["stages"].items():
        field = tuple(stage["field"].split("."))
        definition = _node(parsed.root, field[0])
        weight = _node(parsed.root, *field)
        emitted = field in selected_fields
        if emitted:
            expected_weight = _node(authorized.root, *field)
            if not isinstance(weight.value, Block) or not isinstance(expected_weight.value, Block):
                raise ValueError(f"生产补给权重不是已核实的脚本块：{option}")
            if (
                not weight.value.items
                or not expected_weight.value.items
                or _ast(weight.value.items[-1]) != _ast(expected_weight.value.items[-1])
            ):
                raise ValueError(f"生产补给权重偏离已授权联合贡献：{option}")
            # Only the bound compiler output may be removed before checking vanilla.
            weight.value.items.pop()
            expected_weight.value.items.pop()
            if _digest(_ast(_node(authorized.root, field[0]))) != stage["definition"]["sha256"]:
                raise ValueError(f"生产补给权重预期未保留原版定义：{option}")
        if _digest(_ast(definition)) != stage["definition"]["sha256"]:
            raise ValueError(f"生产补给阶段原版资格、权重、维持或生命周期漂移：{option}")
        verified[option] = {**stage, "weight_extension_emitted": emitted}
    return verified


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _ast(node: object) -> object:
    if isinstance(node, Scalar):
        return ["scalar", node.text, node.quoted]
    if isinstance(node, Assignment):
        return ["assignment", node.key, node.op, node.prefix, _ast(node.value)]
    if isinstance(node, Block):
        return ["block", [_ast(item) for item in node.items]]
    raise ValueError("动员原件含未知AST节点")


def _one(block: Block, key: str) -> Assignment:
    values = block.all(key)
    if len(values) != 1 or values[0].op != "=" or values[0].prefix is not None:
        raise ValueError(f"动员字段缺失、重复或不是普通赋值：{key}")
    return values[0]


def _node(root: Block, *path: str) -> Assignment:
    current: Assignment | None = None
    for index, key in enumerate(path):
        current = _one(root, key)
        if index < len(path) - 1:
            if not isinstance(current.value, Block):
                raise ValueError("动员证据路径必须经过普通块")
            root = current.value
    if current is None:
        raise ValueError("动员证据路径不能为空")
    return current


def _record(node: Assignment) -> dict[str, Any]:
    ast = _ast(node)
    return {"line": node.line, "sha256": _digest(ast)}


def read_inputs(game: Path) -> dict[str, bytes]:
    """Read exact witnesses and the full native mobilization source set."""
    paths = set((game / "common/mobilization_options").rglob("*.txt"))
    paths.update(
        path
        for path in (game / "dlc").rglob("*.txt")
        if path.parent.name == "mobilization_options" and path.parent.parent.name == "common"
    )
    paths.update(game / source for source in _REQUIRED)
    return {path.relative_to(game).as_posix(): path.read_bytes() for path in sorted(paths)}


def _inventory(inputs: Mapping[str, bytes]) -> dict[str, Any]:
    if set(inputs) != _REQUIRED or any(not isinstance(raw, bytes) for raw in inputs.values()):
        raise ValueError("动员原件集合漂移或不是完整原始字节")
    version_contracts.require_current()
    texts = {source: normalized_text(raw.decode("utf-8-sig")) for source, raw in inputs.items()}
    doc = texts[_DOC]
    if not all(
        marker in doc
        for marker in (
            "script value that multiplies the AI value calculation for a mobilization option",
            "the base AI value that is multiplied is set by the ai_value of the unit_modifier",
            "after multiplication, this is compared against the monetary cost",
            "root = military formation",
        )
    ):
        raise ValueError("动员字段局部ROOT/效用/货币比较合同缺失")
    trees = {}
    for source, text in texts.items():
        if source == _DOC:
            continue
        parsed = parse_text(text, path=source)
        if parsed.errors:
            raise ValueError(f"动员原件解析失败：{source}")
        trees[source] = parsed.root
    if "# Root = Military Formation\non_military_formation_created" not in texts[_OWNER]:
        raise ValueError("动员所属国家证据缺少formation ROOT声明")
    owner = _node(trees[_OWNER], "on_military_formation_created", "effect", "if", "limit", "owner")
    expected_owner = parse_text("owner = { has_journal_entry = je_tutorial_create_formation }").root
    if _ast(owner) != _ast(_one(expected_owner, "owner")):
        raise ValueError("动员formation到owner块证据漂移")
    event = trees[_COUNTRY]
    if _ast(_node(event, "trench_warfare.1", "type")) != [
        "assignment",
        "type",
        "=",
        None,
        ["scalar", "country_event", False],
    ]:
        raise ValueError("动员owner国家ROOT证明漂移")
    country = _node(
        event,
        "trench_warfare.1",
        "trigger",
        "any_scope_war",
        "any_scope_front",
        "any_military_formation",
        "owner",
    )
    if (
        not isinstance(country.value, Scalar)
        or country.value.quoted
        or country.value.text != "ROOT"
    ):
        raise ValueError("动员owner必须指向country_event ROOT")
    modifier = _node(trees[_MODIFIER], "unit_recovery_rate_add")
    ai_value = _node(trees[_MODIFIER], "unit_recovery_rate_add", "game_data", "ai_value")
    if (
        not isinstance(ai_value.value, Scalar)
        or ai_value.value.quoted
        or ai_value.value.text != "5000"
    ):
        raise ValueError("动员恢复率原版非零AI效用漂移")
    native = trees[SOURCE]
    definitions = list(native.assignments())
    if len(definitions) != 18 or len({item.key for item in definitions}) != 18:
        raise ValueError("动员18项原版独立分母漂移")
    candidates = {}
    for identity, basket in _BASKETS.items():
        definition = _one(native, identity)
        if not isinstance(definition.value, Block):
            raise ValueError("动员候选必须为普通定义块")
        weight = _node(native, identity, "ai_weight")
        if _ast(weight.value) != [
            "block",
            [["assignment", "value", "=", None, ["scalar", "1", False]]],
        ]:
            raise ValueError("医疗动员原生权重必须是非零常量脚本块")
        upkeep = _node(native, identity, "upkeep_modifier")
        expected = parse_text(
            "x = { "
            + " ".join(f"goods_input_{good}_add = {quantity}" for good, quantity in basket.items())
            + " }"
        ).root
        if _ast(upkeep.value) != _ast(_one(expected, "x").value):
            raise ValueError("医疗动员真实材料/原始系数漂移")
        recovery = _node(native, identity, "unit_modifier")
        expected = parse_text(f"x = {{ unit_recovery_rate_add = {_RECOVERY[identity]} }}").root
        if _ast(recovery.value) != _ast(_one(expected, "x").value):
            raise ValueError("医疗动员原版恢复率漂移")
        if _ast(_node(native, identity, "group").value) != ["scalar", "medic_support", False]:
            raise ValueError("医疗动员候选家庭漂移")
        candidates[identity] = {
            "source": SOURCE,
            "field": f"{identity}.ai_weight",
            "definition": _record(definition),
            "weight": _record(weight),
            "goods": dict(basket),
            "goods_unit": "native_modifier_quantity_coefficient_not_purchase_or_currency",
            "recovery_rate": _RECOVERY[identity],
            "sections": {item.key: _record(item) for item in definition.value.assignments()},
        }
    data = {
        "schema": 2,
        "contract": dict(_CONTRACT),
        "sources": {
            source: hashlib.sha256(text.encode()).hexdigest()
            for source, text in sorted(texts.items())
        },
        "originals": {
            source: {"sha256": hashlib.sha256(raw).hexdigest()}
            for source, raw in sorted(inputs.items())
        },
        "scope_evidence": {"owner_block": _record(owner), "owner_is_country": _record(country)},
        "utility_evidence": {
            "source": _MODIFIER,
            "modifier": _record(modifier),
            "ai_value": _record(ai_value),
        },
        "candidates": dict(sorted(candidates.items())),
        "native_identities": [item.key for item in definitions],
    }
    data["candidates"] = _candidate_catalog(data, native, trees[_MODIFIER])
    return data


def _validate(data: dict[str, Any]) -> dict[str, Any]:
    """Validate the complete frozen authority by its canonical identity."""
    if hashlib.sha256(_canonical(data).encode()).hexdigest() != baseline_sha256():
        raise ValueError("当前动员权威证据漂移")
    return data


def write_baseline(game: Path) -> Path:
    """Explicitly freeze live originals; pin identity only after independent review."""
    baseline_path().write_text(
        _canonical(_inventory(read_inputs(game))), encoding="utf-8", newline="\n"
    )
    return baseline_path()


def load_baseline(*, raw: bytes | None = None) -> dict[str, Any]:
    raw = baseline_path().read_bytes() if raw is None else raw
    if hashlib.sha256(raw).hexdigest() != baseline_sha256():
        raise ValueError("动员冻结资料身份漂移，必须独立复核后重新pin")
    data = json.loads(raw)
    if raw.decode("utf-8") != _canonical(data):
        raise ValueError("动员冻结资料不是规范JSON")
    return _validate(data)


def verify_game(game: Path) -> dict[str, Any]:
    frozen = load_baseline()
    if _inventory(read_inputs(game)) != frozen:
        raise ValueError("动员当前源集合/原文/AST漂移")
    verify_supply_comparison(game)
    return frozen


def candidate_catalog(baseline: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Return the reviewed military formation candidates and their material evidence."""
    data = load_baseline() if baseline is None else _validate(dict(baseline))
    return cast("dict[str, dict[str, Any]]", data["candidates"])


def _candidate_catalog(
    data: Mapping[str, Any], native: Block, modifiers: Block
) -> dict[str, dict[str, Any]]:
    result = {
        identity: {**row, "utility_evidence": dict(data["utility_evidence"])}
        for identity, row in data["candidates"].items()
    }
    for short, basket in _ADDITIONAL_BASKETS.items():
        identity = f"mobilization_option_{short}"
        definition = _node(native, identity)
        upkeep = _node(native, identity, "upkeep_modifier")
        expected = parse_text(
            "x = { "
            + " ".join(f"goods_input_{good}_add = {quantity}" for good, quantity in basket.items())
            + " }"
        ).root
        if _ast(upkeep.value) != _ast(_one(expected, "x").value):
            raise ValueError(f"动员直接材料合同漂移：{identity}")
        modifier, amount, coefficient = _UTILITY[short]
        effect = _node(native, identity, "unit_modifier", modifier)
        utility = _node(modifiers, modifier, "game_data", "ai_value")
        for node, text in ((effect, amount), (utility, coefficient)):
            if not isinstance(node.value, Scalar) or node.value.quoted or node.value.text != text:
                raise ValueError(f"动员候选非零原版效用证据漂移：{identity}")
        if float(amount) * float(coefficient) <= 0:
            raise ValueError("动员候选效用方向必须由原版系数证明")
        assert isinstance(definition.value, Block)
        result[identity] = {
            "source": SOURCE,
            "field": f"{identity}.ai_weight",
            "definition": _record(definition),
            "weight": _record(_node(native, identity, "ai_weight")),
            "goods": dict(basket),
            "goods_unit": "native_modifier_quantity_coefficient_not_purchase_or_currency",
            "sections": {item.key: _record(item) for item in definition.value.assignments()},
            "utility_evidence": {"effect": _record(effect), "ai_value": _record(utility)},
        }
    return dict(sorted(result.items()))


def _parameters(values: Mapping[str, object]) -> dict[str, float]:
    if set(values) != _PARAMETERS:
        raise ValueError("动员参数键无效")
    result = {}
    for key, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("动员参数必须为有限数字")
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError("动员参数必须为有限数字")
        result[key] = float(value)
    if not result["priority_base"].is_integer() or not 100000 <= result["priority_base"] <= 1000000:
        raise ValueError("动员优先级必须为独立整数段")
    if not (
        1 < result["war_need_multiplier"] <= 1.5
        and 0.5 <= result["price_pressure_multiplier"] < result["scarcity_multiplier"] < 1
        and 0.5 <= result["default_multiplier"] < 1
        and 0 < result["pressure_price_threshold"] <= 0.75
    ):
        raise ValueError("动员收益/成本参数方向或范围无效")
    return dict(sorted(result.items()))


def load_parameters() -> dict[str, float]:
    data = tomllib.loads(PARAMETERS.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "parameters"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or not isinstance(data["parameters"], dict)
    ):
        raise ValueError("动员参数schema无效")
    return _parameters(data["parameters"])


def reader_specs(candidate: str | None = None) -> dict[str, dict[str, Any]]:
    """Exact formation-to-owner readers shared by derivation and context checks."""
    result: dict[str, dict[str, Any]] = {}
    for key, engine in (("owner_ai", "is_ai"), ("war", "is_at_war"), ("default", "in_default")):
        result[f"mobilization_{key}"] = {
            "engine": engine,
            "scope": "root",
            "kind": "boolean",
            "unit": "boolean",
            "path": ["owner"],
        }
    if candidate is not None and candidate not in _ALL_BASKETS:
        raise ValueError("动员读取器候选身份未冻结")
    baskets = _ALL_BASKETS.values() if candidate is None else (_ALL_BASKETS[candidate],)
    for good in sorted({good for basket in baskets for good in basket}):
        for tier, engine, unit in (
            ("balance", "market_goods_delta", "sell_minus_buy_orders"),
            ("price", "market_goods_pricier", "price_above_base_ratio"),
        ):
            result[f"mobilization_{good}_{tier}"] = {
                "engine": engine,
                "scope": "root",
                "kind": "number",
                "unit": unit,
                "path": ["owner", "market", f"mg:{good}"],
            }
    return dict(sorted(result.items()))


def derive(
    adapters: Mapping[str, Any],
    baseline: Mapping[str, Any] | None = None,
    *,
    parameters: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Return source hashes, typed reader specs and ordinary joint contributions.

    Integration supplies native formation ROOT and actor_path=['owner'].
    The two original medical contracts retain their numeric core balances.
    Other candidates require only their owner; missing material data exits the
    corresponding cost rather than blocking unrelated observed contributions.
    """
    frozen = load_baseline() if baseline is None else _validate(dict(baseline))
    chosen = load_parameters() if parameters is None else _parameters(parameters)
    if (
        not isinstance(adapters.get("sources"), Mapping)
        or not isinstance(adapters.get("readers"), Mapping)
        or not isinstance(adapters.get("rules"), list)
    ):
        raise ValueError("动员需要现有适配器映射")
    for source, digest in frozen["sources"].items():
        if source in adapters["sources"] and adapters["sources"][source] != digest:
            raise ValueError("动员与现有适配器来源冲突")
    readers = reader_specs()
    rules: list[dict[str, Any]] = []
    for key, spec in readers.items():
        if key in adapters["readers"] and adapters["readers"][key] != spec:
            raise ValueError("动员reader完整签名漂移")
    candidates = candidate_catalog(frozen)
    supply = _supply_chain_contract(frozen)
    for identity, row in candidates.items():
        supply_stage = supply["stages"].get(identity.removeprefix("mobilization_option_"))
        goods = _ALL_BASKETS[identity] if supply_stage is None else supply_stage["upkeep_goods"]
        field = row["field"] if supply_stage is None else supply_stage["field"]
        core = ["mobilization_owner_ai"]
        if identity in _BASKETS:
            core.extend(f"mobilization_{good}_balance" for good in goods)

        def rule(
            suffix: str,
            value: float,
            cause: str,
            conditions: list[dict[str, Any]],
            why: str,
            *,
            identity: str = identity,
            field: str = field,
            core: list[str] = core,
        ) -> None:
            rules.append(
                {
                    "id": f"mobilization_{identity.removeprefix('mobilization_option_')}_{suffix}",
                    "source": SOURCE,
                    "field": field,
                    "domain": "military",
                    "operation": "multiply",
                    "value": value,
                    "priority": int(chosen["priority_base"]) + len(rules),
                    "contribution_group": cause,
                    "conditions": conditions,
                    "required_known_facts": core,
                    "why": why,
                    "counterexample": "仅所属国家AI偏好；未知核心局部回退，辅助未知仅退出本项；不推断伤亡、编制或实际采购，不改资格/效用/真实成本/启停组织士气；原版负分及零尾保持，不新造冷却或记忆",
                }
            )

        rule(
            "war_need",
            chosen["war_need_multiplier"],
            "mobilization_country_war_need",
            [{"fact": "mobilization_war", "op": "=", "value": True}],
            "所属国家在战争中，仅作已证有效动员的需求代理；各候选具体效用、负面效果与互斥关系仍由原版比较",
        )
        rule(
            "default",
            chosen["default_multiplier"],
            "mobilization_financing_pressure",
            [{"fact": "mobilization_default", "op": "=", "value": True}],
            "所属国家实际违约，新增付费动员有独立融资机会成本；正常贷款不扣，不重复扣真实货币支出",
        )
        for good in goods:
            balance = {"fact": f"mobilization_{good}_balance", "op": "<", "value": 0.0}
            cause = f"mobilization_material_{good}_pressure"
            rule(
                f"{good}_scarcity",
                chosen["scarcity_multiplier"],
                cause,
                [balance],
                f"本候选真实投入{good}的卖单减买单为负，表达独立材料机会成本；原始数量系数{goods[good]}不是采购量或货币",
            )
            rule(
                f"{good}_price_pressure",
                chosen["price_pressure_multiplier"],
                cause,
                [
                    balance,
                    {
                        "fact": f"mobilization_{good}_price",
                        "op": ">",
                        "value": chosen["pressure_price_threshold"],
                    },
                ],
                "同一材料缺口且价格相对基价超过阈值，升档同一原因取强，不重复扣低档",
            )
    for identity in candidates:
        selected = [rule for rule in rules if rule["field"] == f"{identity}.ai_weight"]
        if (
            len(selected) > decision_rules.STATIC_BUDGET["candidates_per_field"]
            or sum(len(rule["conditions"]) for rule in selected)
            > decision_rules.STATIC_BUDGET["predicates_per_field"]
        ):
            raise ValueError("动员派生超过现有消费者静态预算")
    return {
        "sources": dict(frozen["sources"]),
        "readers": dict(sorted(readers.items())),
        "rules": rules,
        "actors": {SOURCE: ["owner"]},
        "supply_chain": supply,
        "covered": [
            {
                "id": identity,
                "source": SOURCE,
                "field": row["field"],
                "goods": dict(row["goods"]),
                "disposition": "new_consumer_integration_no_legacy_identity",
            }
            for identity, row in candidates.items()
        ],
        "uncovered": [
            {
                "id": identity,
                "source": SOURCE,
                "reason": "native_only_no_direct_paid_basket_or_proven_nonzero_utility",
            }
            for identity in frozen["native_identities"]
            if identity not in candidates
        ],
    }
