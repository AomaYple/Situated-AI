"""Exact internal-security law agendas and observed institutional tradeoffs.

Native effects are inventoried in full. Only the channels with actual exposed
observations receive a score: movement intensity, political-movement sources
of radical/loyalist changes, and starting an institution. The other native
mechanisms remain explicit interface responsibilities, never zero benefits.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import config
from .model import Assignment, Block, Scalar
from .parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Mapping

PARAMETERS = config.REPO / "mod/decisions/internal_security_opportunities.toml"
FROZEN = config.REPO / "research/vanilla-ai/1.15.0/internal-security-opportunities.json"
LAW_SOURCE = "common/laws/00_internal_security.txt"
QUERY_SOURCE = "common/scripted_triggers/00_ai_triggers.txt"
_CANDIDATES = frozenset(
    {
        "law_no_home_affairs",
        "law_national_guard",
        "law_secret_police",
        "law_shinsengumi",
        "law_third_section",
        "law_okhrana",
        "law_extraordinary_commission",
        "law_guaranteed_liberties",
    }
)
_COUP_SOURCES = (
    "common/decisions/ip4_portugal_decisions.txt",
    "common/scripted_effects/00_victoria_ip4_scripted_effects.txt",
    "common/scripted_progress_bars/00_ip4_victoria_progress_bars.txt",
    "common/script_values/ip4_je_values.txt",
    "common/diplomatic_actions/40_subjects_knowledge_sharing.txt",
    "common/journal_entries/01_coup.txt",
)
_COUP_PROOFS = (
    (
        "common/decisions/ip4_portugal_decisions.txt",
        ("decision_depose_ruling_dynasty", "possible"),
        "50e428b44296fb527f30857dd953d1973798df4d33f28f83369f3fdd06127630",
    ),
    (
        "common/scripted_effects/00_victoria_ip4_scripted_effects.txt",
        ("create_coup_from_character",),
        "3350d7b3a90971f1af46bcb2b6b86253d5b1b7599725e5c2eb2af015e128b43b",
    ),
    (
        "common/scripted_progress_bars/00_ip4_victoria_progress_bars.txt",
        ("je_ip4_coup_progress_bar",),
        "4c03b69e3e0ae21210af8dc55930cb07cc093529a4db0930b9dd56b7afb9d563",
    ),
    (
        "common/script_values/ip4_je_values.txt",
        ("country_coup_resistance",),
        "e826ada33ca9c671fff1b43d88e2c2cafd33d0a8de9e77d1ea47628ddc9cc42c",
    ),
    (
        "common/diplomatic_actions/40_subjects_knowledge_sharing.txt",
        ("da_knowledge_sharing",),
        "d01aefd0d2de6e7df86cbf0d1aec2c84820c47827b71a7ed0dc35ee89b6a40f1",
    ),
    (
        "common/journal_entries/01_coup.txt",
        ("je_ip4_coup",),
        "91956aa9de5f5b9fbbd45465f7aa34a21f8bf3cc280aee01ad3da5dd453ed158",
    ),
)
_TUNING = frozenset(
    {
        "coup_change",
        "coup_loss",
        "agenda_base",
        "agenda_strong",
        "movement_change_base",
        "movement_change_invested",
        "movement_loss_base",
        "movement_loss_invested",
        "new_administration_cost",
        "new_financing_cost",
    }
)
_CHANNELS = {
    "political_movement_radicalism_add": "movement_intensity",
    "state_radicals_from_political_movements_mult": "movement_conversion",
    "state_loyalists_from_political_movements_mult": "movement_conversion",
}
_NO_EXPOSURE = {
    "country_soldiers_pol_str_mult": "soldier_population_power_exposure_not_registered",
    "state_political_strength_from_wealth_mult": "population_wealth_power_exposure_not_registered",
    "state_mortality_wealth_mult": "wealth_dependent_mortality_exposure_not_registered",
    "country_institution_cost_institution_home_affairs_mult": "actual_institution_cost_exposure_not_registered",
    "country_institution_home_affairs_max_investment_add": "institution_cap_not_actual_investment_demand",
    "country_officers_pol_str_mult": "officer_population_power_exposure_not_registered",
    "country_shopkeepers_pol_str_mult": "shopkeeper_population_power_exposure_not_registered",
    "interest_group_ig_petty_bourgeoisie_pol_str_mult": "petty_bourgeoisie_power_transition_not_registered",
    "state_conscription_rate_add": "actual_conscription_capacity_demand_not_registered",
    "country_suppression_attraction_factor": "actual_suppression_exposure_not_registered",
    "country_support_separatism_resistance_mult": "actual_separatism_exposure_not_registered",
    "country_support_separatism_strength_mult": "actual_separatism_support_exposure_not_registered",
    "country_amenability_add": "actual_law_negotiation_exposure_not_registered",
    "country_coup_resistance_add": "actual_coup_exposure_not_registered",
    "state_harvest_condition_flood_impact_mult": "actual_flood_exposure_not_registered",
    "state_harvest_condition_wildfire_impact_mult": "actual_wildfire_exposure_not_registered",
    "state_harvest_condition_extreme_winds_impact_mult": "actual_wind_exposure_not_registered",
    "state_harvest_condition_drought_impact_mult": "actual_drought_exposure_not_registered",
}


def load() -> dict[str, Any]:
    data = tomllib.loads(PARAMETERS.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "sources", "candidates", "tuning"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
    ):
        raise ValueError("内部安全机会schema无效")
    if set(data["sources"]) != {LAW_SOURCE, QUERY_SOURCE, *_COUP_SOURCES} or any(
        not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value)
        for value in data["sources"].values()
    ):
        raise ValueError("内部安全机会必须锁定完整法律和原版国家运动消费者")
    if set(data["candidates"]) != _CANDIDATES or set(data["candidates"].values()) != {LAW_SOURCE}:
        raise ValueError("内部安全法律候选分母无效")
    tuning = data["tuning"]
    if set(tuning) != _TUNING or any(
        type(value) not in {int, float} or not math.isfinite(value) or abs(value) > 16
        for value in tuning.values()
    ):
        raise ValueError("内部安全评分参数必须为有限有界数值")
    if not (
        0 < tuning["coup_change"] <= 8
        and -8 <= tuning["coup_loss"] < 0
        and 0 < tuning["agenda_base"] <= tuning["agenda_strong"]
        and 0 < tuning["movement_change_base"] <= tuning["movement_change_invested"]
        and tuning["movement_loss_invested"] <= tuning["movement_loss_base"] < 0
        and tuning["new_administration_cost"] < 0
        and tuning["new_financing_cost"] < 0
    ):
        raise ValueError("内部安全评分方向或档位无效")
    return data


def frozen_inputs() -> dict[str, str]:
    """Load complete normalized evidence without consulting an installation."""
    data = json.loads(FROZEN.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "evidence", "normalization", "source_hashes", "inputs"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or data["evidence"] != "static_complete_native_sources_not_engine_execution"
        or data["normalization"] != "utf8_without_bom_lf_preserve_whitespace"
        or data["source_hashes"] != load()["sources"]
        or not isinstance(data["inputs"], dict)
        or set(data["inputs"]) != set(load()["sources"])
        or any(not isinstance(value, str) for value in data["inputs"].values())
    ):
        raise ValueError("内部安全冻结底本合同无效")
    _roots(data["inputs"])
    return data["inputs"]


def _child(block: Block, name: str) -> Block:
    nodes = block.all(name)
    if len(nodes) != 1 or nodes[0].op != "=" or not isinstance(nodes[0].value, Block):
        raise ValueError(f"内部安全原版缺少唯一完整块：{name}")
    return nodes[0].value


def _roots(inputs: Mapping[str, str]) -> dict[str, Block]:
    roots = {}
    for source, digest in load()["sources"].items():
        text = inputs.get(source)
        if text is None or hashlib.sha256(text.encode()).hexdigest() != digest:
            raise ValueError(f"内部安全原版来源漂移：{source}")
        parsed = parse_text(text)
        if parsed.errors:
            raise ValueError(f"内部安全原版解析失败：{source}")
        roots[source] = parsed.root
    return roots


def _scalar(block: Block, name: str) -> str | None:
    rows = block.all(name)
    if not rows:
        return None
    if len(rows) != 1 or not isinstance(rows[0].value, Scalar):
        raise ValueError(f"内部安全原版标量形状漂移：{name}")
    return rows[0].value.unquoted


def inventory(inputs: Mapping[str, str]) -> dict[str, Any]:
    """Keep all native effects and identify exactly which are safe to score."""
    roots = _roots(inputs)
    laws = {}
    for definition in roots[LAW_SOURCE].assignments():
        if not isinstance(definition.value, Block):
            continue
        law = definition.key
        if not definition.value.all("ai_enact_weight_modifier"):
            continue
        _child(definition.value, "ai_enact_weight_modifier")
        effects = []
        parent = _scalar(definition.value, "parent")
        for container in ("modifier", "institution_modifier"):
            blocks = definition.value.all(container)
            if len(blocks) > 1:
                raise ValueError("内部安全原版修正块重复")
            if not blocks:
                continue
            block = _child(definition.value, container)
            for row in block.assignments():
                if not isinstance(row.value, Scalar):
                    raise ValueError("内部安全效果必须为原版有限常数")
                value = float(row.value.unquoted)
                if not math.isfinite(value):
                    raise ValueError("内部安全效果不是有限值")
                if row.key not in _CHANNELS and row.key not in _NO_EXPOSURE:
                    raise ValueError(f"内部安全新效果尚未登记责任：{row.key}")
                channel = _CHANNELS.get(row.key)
                reason = "observed_movement_exposure" if channel else _NO_EXPOSURE[row.key]
                if (
                    row.key == "country_coup_resistance_add"
                    and parent is None
                    and law
                    in {
                        "law_national_guard",
                        "law_secret_police",
                        "law_guaranteed_liberties",
                        "law_extraordinary_commission",
                    }
                    and container == "institution_modifier"
                ):
                    reason = "observed_active_coup_base_law_transition_only"
                if parent is not None:
                    channel = None
                    reason = "variant_parent_effect_merging_requires_independent_contract"
                effects.append(
                    {
                        "field": row.key,
                        "container": container,
                        "value": value,
                        "unit": "per_invested_level"
                        if container == "institution_modifier"
                        else "flat",
                        "line": row.line,
                        "channel": channel,
                        "responsibility": reason,
                    }
                )
        laws[law] = {
            "parent": parent,
            "institution": _scalar(definition.value, "institution"),
            "effects": effects,
        }
    if set(laws) != _CANDIDATES:
        raise ValueError("内部安全原版完整评分候选分母漂移")
    return {"laws": laws, "source_hashes": dict(load()["sources"])}


def verify_inputs(inputs: Mapping[str, str]) -> None:
    inventory(inputs)
    compile_query(SecurityQuery(0.25), inputs)


@dataclass(frozen=True, slots=True)
class SecurityQuery:
    minimum_radicalism: float


@dataclass(frozen=True, slots=True)
class CompiledSecurityQuery:
    expression: str
    references: tuple[str, ...]
    source_hashes: tuple[tuple[str, str], ...]
    local_collections: tuple[str, ...] = ("owned_political_movements",)
    actor: str = "country"
    kind: str = "boolean"
    unknown_policy: str = "missing_collection=unknown; complete_empty_collection=false"
    world_scans: int = 0
    runtime_cost: str = "existential traversal of owned political movements"


def query_from_reader(
    engine: str, parameters: Mapping[str, str]
) -> SecurityQuery | SecurityCoupQuery:
    if parameters.get("security_query") == "active_coup_positive_resistance":
        if engine != "AND" or set(parameters) != {"security_query"}:
            raise ValueError("政变观测必须保持精确国家AND无参数合同")
        return SecurityCoupQuery()
    if (
        engine != "any_political_movement"
        or set(parameters) != {"security_query", "threshold"}
        or parameters["security_query"] != "radicalism"
        or parameters["threshold"] not in {"0.25", "0.75"}
    ):
        raise ValueError("内部安全查询参数没有原版国家运动消费者依据")
    query = SecurityQuery(float(parameters["threshold"]))
    render_query(query)
    return query


def render_query(query: SecurityQuery | SecurityCoupQuery) -> str:
    if type(query) is SecurityCoupQuery:
        return (
            "AND = { has_journal_entry = je_ip4_coup modifier:country_coup_resistance_mult > -1 }"
        )
    if type(query) is not SecurityQuery or type(query.minimum_radicalism) not in {int, float}:
        raise ValueError("内部安全查询类型无效")
    if query.minimum_radicalism not in {0.25, 0.75}:
        raise ValueError("内部安全运动阈值必须使用原版已证档")
    return (
        "any_political_movement = { "
        f"political_movement_radicalism >= {query.minimum_radicalism} }}"
    )


def required_query_sources(query: SecurityQuery | SecurityCoupQuery) -> tuple[str, ...]:
    if type(query) is SecurityCoupQuery:
        return _COUP_SOURCES
    render_query(query)
    return (QUERY_SOURCE,)


def compile_query(
    query: SecurityQuery | SecurityCoupQuery, inputs: Mapping[str, str]
) -> CompiledSecurityQuery:
    if type(query) is SecurityCoupQuery:
        return _compile_coup_query(query, inputs)
    expression = render_query(query)
    if not isinstance(query, SecurityQuery):
        raise ValueError("内部安全查询类型无效")
    data = load()
    text = inputs.get(QUERY_SOURCE)
    if text is None or hashlib.sha256(text.encode()).hexdigest() != data["sources"][QUERY_SOURCE]:
        raise ValueError("内部安全运动查询原版来源漂移")
    parsed = parse_text(text)
    if parsed.errors:
        raise ValueError("内部安全运动查询原版解析失败")
    generic = _child(parsed.root, "ai_has_reasons_to_not_oppose_law")
    movement = _child(_child(generic, "OR"), "any_political_movement")
    _child(movement, "law_enactment_stance")
    observed = []

    def visit(block: Block) -> None:
        for row in block.assignments():
            if row.key == "political_movement_radicalism":
                if row.op != ">=" or not isinstance(row.value, Scalar):
                    raise ValueError("内部安全原版运动阈值形状漂移")
                observed.append((float(row.value.unquoted), row.line))
            elif isinstance(row.value, Block):
                visit(row.value)

    visit(movement)
    if {value for value, _line in observed} != {0.25, 0.75} or len(observed) != 2:
        raise ValueError("内部安全原版运动阈值分母漂移")
    threshold = query.minimum_radicalism
    line = next(line for value, line in observed if value == threshold)
    return CompiledSecurityQuery(
        expression,
        (f"{QUERY_SOURCE}:{line}",),
        ((QUERY_SOURCE, data["sources"][QUERY_SOURCE]),),
    )


def _condition(fact: str, op: str, value: object) -> dict[str, object]:
    return {"fact": fact, "op": op, "value": value}


def derive(adapters: Mapping[str, Any], inputs: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Derive from complete frozen text; production separately checks live inputs."""
    if inputs is None:
        inputs = frozen_inputs()
    data = load()
    native = inventory(inputs)["laws"]
    tuning = data["tuning"]
    readers: dict[str, Any] = {}
    rules: list[dict[str, Any]] = []

    def current(law: str) -> str:
        key = f"security_current_{law}"
        readers[key] = {
            "engine": "has_law_or_variant",
            "scope": "root",
            "kind": "boolean",
            "unit": "boolean",
            "argument": f"law_type:{law}",
        }
        return key

    def transition(origin: str, candidate: str) -> list[dict[str, object]]:
        result = [
            _condition(current(origin), "=", True),
            _condition(current(candidate), "=", False),
        ]
        if origin == "law_secret_police":
            result.append(_condition(current("law_shinsengumi"), "=", False))
        return result

    def add(
        law: str,
        suffix: str,
        group: str,
        value: float,
        conditions: list[dict[str, object]],
        why: str,
        *,
        semantic_role: str,
    ) -> None:
        rules.append(
            {
                "id": f"internal_security_{law}_{suffix}",
                "source": LAW_SOURCE,
                "field": f"{law}.ai_enact_weight_modifier",
                "domain": "political",
                "priority": 74000 + len(rules),
                "operation": "add",
                "value": value,
                "semantic_role": semantic_role,
                "contribution_group": group,
                "conditions": conditions,
                "why": why,
                "counterexample": "评分是有界设计选择，非通过率或人口结果预测；已观察原法、实际制度投入与具体运动分别读取，未知局部退出。玩家、领域关闭、原版政治支持、法律资格、ai_will_do、JE请愿、成本与执行保留；变体父效果未证不混入制度差。",
            }
        )

    for law in sorted(data["candidates"]):
        for tier, support in (("base", "0.10"), ("strong", "0.25")):
            key = f"security_{law}_movement_{tier}"
            readers[key] = {
                "engine": "any_political_movement",
                "scope": "root",
                "kind": "boolean",
                "unit": "boolean",
                "parameters": {"law": law, "minimum_support": support},
            }
            add(
                law,
                f"agenda_{tier}",
                "law_observed_agenda",
                tuning[f"agenda_{tier}"],
                [_condition(key, "=", True)],
                "本国真实政治运动支持这个具体内部安全候选，按已证支持档回应；不将诉求冒充资格，也不预设镇压或自由路线",
                semantic_role="benefit",
            )
            add(
                law,
                f"adopted_agenda_{tier}",
                "law_observed_agenda",
                -tuning[f"agenda_{tier}"],
                [_condition(key, "=", True), _condition(current(law), "=", True)],
                "候选法已实际生效时撤回同档已观察议程偏好；未知现行法不抹去独立已知的国内诉求",
                semantic_role="benefit",
            )

    for tier, threshold in (("base", "0.25"),):
        readers[f"security_movement_radicalism_{tier}"] = {
            "engine": "any_political_movement",
            "scope": "root",
            "kind": "boolean",
            "unit": "boolean",
            "parameters": {"security_query": "radicalism", "threshold": threshold},
        }

    base_laws = sorted(law for law, row in native.items() if row["parent"] is None)
    for candidate in base_laws:
        for origin in base_laws:
            if candidate == origin:
                continue
            observed_transition = transition(origin, candidate)
            if origin == "law_no_home_affairs" and native[candidate]["institution"]:
                for suffix, fact, op, observed in (
                    ("administration", "bureaucracy", "<", 0),
                    ("financing", "default", "=", True),
                ):
                    add(
                        candidate,
                        f"new_institution_{suffix}",
                        f"law_security_new_institution_{suffix}",
                        tuning[f"new_{suffix}_cost"],
                        [*observed_transition, _condition(fact, op, observed)],
                        "从无内政制度建立新制度，真实行政短缺或违约分别形成新增承诺成本；既存同一制度间转法不重复收取",
                        semantic_role="cost",
                    )
            for mechanism, channel in _CHANNELS.items():
                effects = {
                    law: sum(
                        effect["value"]
                        for effect in row["effects"]
                        if effect["field"] == mechanism and effect["channel"]
                    )
                    for law, row in native.items()
                }
                difference = effects[candidate] - effects[origin]
                if difference == 0:
                    continue
                improving = difference > 0 if "loyalists" in mechanism else difference < 0
                # Radicals and loyalists are the two sides of the same
                # political-movement conversion channel, not duplicate rewards.
                group = (
                    "law_observed_agenda"
                    if improving and channel == "movement_intensity"
                    else f"law_security_{channel}_{'benefit' if improving else 'loss'}"
                )
                for tier, investment in (("base", 1), ("invested", 3)):
                    value = tuning[f"movement_{'change' if improving else 'loss'}_{tier}"]
                    add(
                        candidate,
                        f"from_{origin}_{mechanism}_{tier}",
                        group,
                        value,
                        [
                            *observed_transition,
                            _condition("home_affairs_investment", ">=", investment),
                            _condition("security_movement_radicalism_base", "=", True),
                        ],
                        "比较现行与候选的原版实际制度修正差，并消费已投入等级及本国真实政治运动激进化；运动强度与运动来源激进/忠诚转换分开，收益损失同时权衡，不将全国激进人口冒充运动来源",
                        semantic_role="benefit" if improving else "cost",
                    )

    _derive_coup_rules({"readers": readers, "rules": rules}, inputs)
    used = {condition["fact"] for rule in rules for condition in rule["conditions"]}
    for key in sorted(used - readers.keys()):
        if key not in adapters["readers"]:
            raise ValueError(f"内部安全缺少既有已证读取器：{key}")
        readers[key] = adapters["readers"][key]
    return {
        "sources": dict(data["sources"]),
        "readers": readers,
        "rules": rules,
        "covered": [
            {"id": law, "source": LAW_SOURCE, "field": f"{law}.ai_enact_weight_modifier"}
            for law in sorted(data["candidates"])
        ],
        "native_effects": native,
    }


@dataclass(frozen=True, slots=True)
class SecurityCoupQuery:
    """Actual actor-owned coup and a strictly positive resistance multiplier."""


def _compile_coup_query(
    query: SecurityCoupQuery, inputs: Mapping[str, str]
) -> CompiledSecurityQuery:
    hashes = load()["sources"]
    roots = {}
    for source in _COUP_SOURCES:
        text = inputs.get(source)
        if text is None or hashlib.sha256(text.encode()).hexdigest() != hashes[source]:
            raise ValueError(f"政变完整原版来源漂移：{source}")
        parsed = parse_text(text)
        if parsed.errors:
            raise ValueError(f"政变完整原版解析失败：{source}")
        roots[source] = parsed.root
    decision, creation, progress, values, _comparison, journal = _COUP_SOURCES
    possible = _child(_child(roots[decision], "decision_depose_ruling_dynasty"), "possible")
    if _scalar(_child(possible, "NOR"), "has_journal_entry") != "je_ip4_coup":
        raise ValueError("政变JE国家消费者漂移")
    owner = _child(
        _child(_child(roots[creation], "create_coup_from_character"), "$CHARACTER$"), "owner"
    )
    if _scalar(_child(owner, "add_journal_entry"), "type") != "je_ip4_coup":
        raise ValueError("政变JE所有者漂移")
    weekly = _child(
        _child(_child(roots[progress], "je_ip4_coup_progress_bar"), "weekly_progress"), "owner"
    )
    subtracts = [
        row
        for row in weekly.all("subtract")
        if isinstance(row.value, Block)
        and _scalar(row.value, "value") == "owner.country_coup_resistance"
    ]
    if len(subtracts) != 1:
        raise ValueError("政变抵抗消费者漂移")
    resistance = _child(roots[values], "country_coup_resistance")
    if [row.key for row in resistance.assignments()] != ["add", "add", "multiply"]:
        raise ValueError("政变抵抗公式次序漂移")
    additions = resistance.all("add")
    if (
        not isinstance(additions[1].value, Block)
        or _scalar(additions[1].value, "add") != "modifier:country_coup_resistance_add"
    ):
        raise ValueError("政变抵抗加法来源漂移")
    multiplier = _child(resistance, "multiply")
    if (
        _scalar(multiplier, "value") != "1"
        or _scalar(multiplier, "add") != "modifier:country_coup_resistance_mult"
    ):
        raise ValueError("政变抵抗乘数漂移")
    references: list[str] = []
    for source, parts, expected in _COUP_PROOFS:
        parent = roots[source]
        for part in parts:
            parent = _child(parent, part)
        digest = hashlib.sha256(
            json.dumps(_coup_ast(parent), ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        if digest != expected:
            raise ValueError(f"政变完整父AST漂移：{source}:{'.'.join(parts)}")
        references.append(f"{source}:{parent.line}")
    entry = _child(roots[journal], "je_ip4_coup")
    if _scalar(entry, "scripted_progress_bar") != "je_ip4_coup_progress_bar":
        raise ValueError("政变JE到进度条连接漂移")
    outcomes = entry.all("outcome")
    if len(outcomes) != 4:
        raise ValueError("政变结局分母漂移")
    # The whole JE parent above includes the complete >=120 victory and <=0
    # failure triggers/effects. These independent exact subtrees also document
    # and verify which direction the proposed resistance preference serves.
    success = outcomes[0].value
    failure = outcomes[1].value
    if not isinstance(success, Block) or not isinstance(failure, Block):
        raise ValueError("政变结局形状漂移")
    success_progress = _child(
        _child(_child(success, "trigger"), "custom_tooltip"), "scope:journal_entry"
    )
    failure_or = _child(_child(failure, "trigger"), "OR")
    failure_progress = _child(_child(failure_or, "custom_tooltip"), "scope:journal_entry")
    for parent, operator, expected_value in (
        (success_progress, ">=", "120"),
        (failure_progress, "<=", "0"),
    ):
        rows = parent.all("scripted_bar_progress(je_ip4_coup_progress_bar)")
        if (
            len(rows) != 1
            or rows[0].op != operator
            or not isinstance(rows[0].value, Scalar)
            or rows[0].value.unquoted != expected_value
        ):
            raise ValueError("政变推进方向漂移")
        references.append(f"{journal}:{rows[0].line}")
    if (
        _scalar(_child(_child(success, "effect"), "show_as_tooltip"), "ip4_coup_victory_effect")
        != "yes"
    ):
        raise ValueError("政变成功后果漂移")
    failure_effect = _child(failure, "effect")
    if (
        _scalar(failure_effect, "je_ip4_coup_cleanup") != "yes"
        or _scalar(_child(failure_effect, "change_global_variable"), "name") != "failed_coups"
    ):
        raise ValueError("政变失败后果漂移")
    refs = tuple(references)
    return CompiledSecurityQuery(
        render_query(query),
        refs,
        tuple((s, hashes[s]) for s in _COUP_SOURCES),
        local_collections=(),
        unknown_policy="missing_JE_or_multiplier=unknown; absent_active_JE=false",
        runtime_cost="two actor-country scalar predicates; no traversal",
    )


def _derive_coup_rules(result: dict[str, Any], inputs: Mapping[str, str]) -> None:
    compile_query(SecurityCoupQuery(), inputs)
    laws = inventory(inputs)["laws"]
    base = (
        "law_national_guard",
        "law_secret_police",
        "law_guaranteed_liberties",
        "law_extraordinary_commission",
    )
    readers, rules = result["readers"], result["rules"]
    readers["security_active_coup_positive_resistance"] = {
        "engine": "AND",
        "scope": "root",
        "kind": "boolean",
        "unit": "boolean",
        "parameters": {"security_query": "active_coup_positive_resistance"},
    }

    def effect(law: str) -> float:
        rows = [
            row for row in laws[law]["effects"] if row["field"] == "country_coup_resistance_add"
        ]
        if (
            laws[law]["parent"] is not None
            or len(rows) != 1
            or rows[0]["unit"] != "per_invested_level"
        ):
            raise ValueError("政变基础法律效果合同漂移")
        value = rows[0]["value"]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError("政变基础法律效果值必须为数值")
        return float(value)

    for origin in base:
        for candidate in base:
            delta = effect(candidate) - effect(origin)
            if not delta:
                continue
            conditions = [
                _condition(f"security_current_{origin}", "=", True),
                _condition(f"security_current_{candidate}", "=", False),
                _condition("home_affairs_investment", ">=", 1),
                _condition("security_active_coup_positive_resistance", "=", True),
            ]
            if origin == "law_secret_police":
                conditions.extend(
                    _condition(f"security_current_{variant}", "=", False)
                    for variant in ("law_shinsengumi", "law_third_section", "law_okhrana")
                )
            rules.append(
                {
                    "id": f"internal_security_{candidate}_from_{origin}_coup_resistance",
                    "source": LAW_SOURCE,
                    "field": f"{candidate}.ai_enact_weight_modifier",
                    "domain": "political",
                    "priority": 74900 + len(rules),
                    "operation": "add",
                    "value": load()["tuning"]["coup_change" if delta > 0 else "coup_loss"],
                    "semantic_role": "benefit" if delta > 0 else "cost",
                    "contribution_group": "law_security_actual_coup_resistance",
                    "conditions": conditions,
                    "why": "本国活动政变实际消费抵抗，比较基础现行与候选法每级抵抗差；已观察投资和正向乘数守卫方向，不预测法律完成时间或政变结果",
                    "counterexample": "与运动因果分组并一次联合；未知局部退出，变体父合并不代签；原版资格、科技、ai_will_do、请愿、玩家与关闭保留",
                }
            )


def _coup_ast(node: object) -> object:
    if isinstance(node, Scalar):
        return ("scalar", node.text, node.quoted)
    if isinstance(node, Assignment):
        return ("assignment", node.key, node.op, node.prefix, _coup_ast(node.value))
    if isinstance(node, Block):
        return ("block", tuple(_coup_ast(item) for item in node.items))
    return None
