"""Exact event-option AIWeight bridge, using the shared scalar program.

AIWeight uses base/modifier/trigger/scalar add rather than ScriptValue if/add.
Only finite linear programs whose final clamp is provably inactive lower here.
Plague's complete three-option policy intentionally defines new AI weights;
it does not claim equivalence to the unknown omitted native AIWeight default.
"""

from __future__ import annotations

import hashlib
import json
import math
import tomllib
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, cast

from pdx import config
from pdx.lexer import ATOM, LBRACE, OP, RBRACE, tokenize
from pdx.model import Block, Scalar
from pdx.parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pdx.decision_rules import Reader
    from pdx.situated import programs
    from pdx.situated.decision_ir import EvaluationContext, WriterDecisionIR

PARAMETERS = config.REPO / "mod/decisions/event_opportunities.toml"
FROZEN = config.REPO / "research/vanilla-ai/1.15.0/event-opportunities.json"
SOURCE = "events/law_events/healthcare_laws.txt"
MODIFIERS = "common/static_modifiers/content_4_modifiers.txt"
ON_ACTIONS = "common/on_actions/00_code_on_actions.txt"
SYNTAX = "events/iberia_events/negotiation_events.txt"
PLAGUE = "events/spanish_flu_events.txt"
HEALTH = "common/laws/01_health_system.txt"
PLAGUE_DECISION = "common/decisions/spanish_flu_decisions.txt"
PLAGUE_MODIFIERS = "common/static_modifiers/02_event_modifiers.txt"
PLAGUE_EFFECTS = "common/scripted_effects/00_spanish_flu_effects.txt"
PLAGUE_JOURNAL = "common/journal_entries/00_plague.txt"
FINANCE = "events/brazil/amazonas.txt"
DISASTERS = "events/natural_disasters_events.txt"
YEARLY = "common/on_actions/00_on_actions_yearly.txt"
EVENT_VALUES = "common/script_values/event_values.txt"
STATE_POPULATION = "events/american_civil_war/acw_wild_west_events.txt"
SOL = "events/standard_of_living_events.txt"
SOL_JOURNAL = "common/journal_entries/00_standard_of_living.txt"
SOL_JOURNAL_DOC = "common/journal_entries/journal_entries.md"
SOL_JOURNAL_GROUP = "common/journal_entry_groups/00_journal_entries.txt"
SOL_OWNER = "events/tech_events/nursing_events.txt"
SOL_EVENT = "sol_events.6"
SOL_OPTIONS = ("sol_events.6.a", "sol_events.6.b")
SOL_PARENT_SHAPE = "46e09d1737ef7caf53446896f2bea78e547523305bc0753ae4978df2ee59b9fb"
LEGACY_SOURCES = frozenset(
    {
        SOURCE,
        MODIFIERS,
        ON_ACTIONS,
        SYNTAX,
        PLAGUE,
        HEALTH,
        PLAGUE_DECISION,
        PLAGUE_MODIFIERS,
        PLAGUE_EFFECTS,
        PLAGUE_JOURNAL,
        FINANCE,
        DISASTERS,
        YEARLY,
        EVENT_VALUES,
        STATE_POPULATION,
    }
)
SOL_SOURCES = frozenset(
    {
        SOL,
        SOL_JOURNAL,
        SOL_JOURNAL_DOC,
        SOL_JOURNAL_GROUP,
        PLAGUE_MODIFIERS,
        EVENT_VALUES,
        FINANCE,
        STATE_POPULATION,
        SOL_OWNER,
    }
)
HOKKAIDO = "events/japan_events/ep2_hokkaido_events.txt"
HOKKAIDO_EVENT = "hokkaido_events.3"
HOKKAIDO_OPTIONS = tuple(HOKKAIDO_EVENT + "." + suffix for suffix in ("a", "b", "c", "e", "g"))
HOKKAIDO_SOURCES = frozenset(
    (
        "common/building_groups/00_building_groups.txt",
        "common/buildings/09_misc_resource.txt",
        "common/buildings/12_subsistence.txt",
        "events/australia_events.txt",
        "common/journal_entry_groups/00_journal_entries.txt",
        "events/japan_events/ep2_hokkaido_events.txt",
        "common/scripted_buttons/07_japan_buttons.txt",
        "common/scripted_buttons/scripted_buttons.md",
        "common/journal_entries/07_hokkaido.txt",
        "common/static_modifiers/00_ep2_02_modifiers.txt",
        "common/script_values/event_values.txt",
        "common/scripted_triggers/00_scripted_triggers.txt",
        "events/agitators_events/algeria_events.txt",
        "common/decisions/west_america_expidition_decision.txt",
        "common/buildings/02_agro.txt",
        "common/buildings/04_plantations.txt",
        "common/production_methods/02_agro.txt",
        "common/production_methods/04_plantations.txt",
        "common/production_method_groups/02_agro.txt",
        "common/production_method_groups/04_plantations.txt",
        "common/alert_types/00_alert_types.txt",
        "common/objective_subgoals/00_subgoals_tutorial.txt",
    )
)
FAMILIES = frozenset({"healthcare", "plague", "disaster", "sol_response", "hokkaido"})
DISASTER_QUERY_PARAMETER = "event_disaster_query"
DISASTER_EVENTS = tuple(f"natural_disaster_events.{i}" for i in range(1, 9))
DISASTER_OPTIONS = tuple(f"{name}.{suffix}" for name in DISASTER_EVENTS for suffix in ("a", "b"))
DISASTER_SCOPES = (
    "earthquake_state",
    "flood_state",
    "mega_flood_state",
    "mega_earthquake_state",
    "crop_fail_state",
    "cyclone_state",
    "volcanic_state",
    "mega_volcanic_state",
)
DISASTER_SAVED_LINES = (40, 105, 178, 267, 359, 440, 503, 592)
DISASTER_RELIEF = (
    "earthquake",
    "flood",
    "mega_flood",
    "mega_earthquake",
    "crop_failure",
    "cyclone",
    "volcano",
    "mega_volcanic",
)
PLAGUE_EVENT = "plague.5"
PLAGUE_OPTIONS = ("plague.5.a", "plague.5.b", "plague.5.c")
QUERY_PARAMETER = "event_plague_query"
EVENT = "healthcare_laws.5"
OPTIONS = ("healthcare_laws.5.a", "healthcare_laws.5.b")
DOMAIN = "political"


def load() -> dict[str, Any]:
    data = tomllib.loads(PARAMETERS.read_text(encoding="utf-8"))
    if (
        set(data)
        != {
            "schema",
            "sources",
            "tuning",
            "plague_policy",
            "disaster_policy",
            "sol_response_policy",
            "hokkaido_policy",
        }
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or set(data["sources"]) != LEGACY_SOURCES | SOL_SOURCES | HOKKAIDO_SOURCES
        or set(data["tuning"]) != {"reform_need", "ignored_opponent_cost", "heard_opponent_benefit"}
    ):
        raise ValueError("事件机会schema/来源/参数不完整")
    if any(
        type(v) not in {int, float} or not math.isfinite(v) or not 0 < v <= 10
        for v in data["tuning"].values()
    ):
        raise ValueError("事件机会倾向必须为有限有界正数")
    if any(
        not isinstance(v, str) or len(v) != 64 or any(c not in "0123456789abcdef" for c in v)
        for v in data["sources"].values()
    ):
        raise ValueError("事件机会完整源哈希无效")
    policy = data["plague_policy"]
    if set(policy) != {
        "base",
        "lockdown_health",
        "measures_health",
        "no_response_health_cost",
        "lockdown_throughput",
        "measures_throughput",
        "lockdown_financing",
        "measures_financing",
        "response_continuity",
        "recovery_exit",
    } or any(
        type(v) not in {int, float} or not math.isfinite(v) or not 0 < v <= 50
        for v in policy.values()
    ):
        raise ValueError("疫情三选项显式政策必须具有完整有限有界参数")
    if any(
        policy[f"lockdown_{axis}"] < policy[f"measures_{axis}"]
        for axis in ("health", "throughput", "financing")
    ):
        raise ValueError("较强封锁的已声明健康/吞吐/融资档不能小于较轻措施")
    disaster = data["disaster_policy"]
    if (
        set(disaster)
        != {
            "base",
            "ordinary_relief",
            "mega_relief",
            "crop_throughput_relief",
            "crop_welfare",
            "ordinary_high_exposure",
            "mega_high_exposure",
            "crop_high_exposure",
            "small_recurring_cost",
            "medium_recurring_cost",
            "large_recurring_cost",
            "solvent_cost_fraction",
        }
        or any(
            type(v) not in {int, float} or not math.isfinite(v) or not 0 < v <= 50
            for v in disaster.values()
        )
        or not 0 < disaster["solvent_cost_fraction"] <= 1
    ):
        raise ValueError("灾害完整配对显式政策参数无效")
    if not (
        disaster["small_recurring_cost"]
        < disaster["medium_recurring_cost"]
        < disaster["large_recurring_cost"]
        and disaster["ordinary_relief"] < disaster["mega_relief"]
    ):
        raise ValueError("灾害减损及经常费用档方向漂移")
    sol = data["sol_response_policy"]
    if (
        set(sol)
        != {
            "base",
            "lower_sol",
            "high_exposure",
            "avoided_radicals",
            "recurring_cost",
            "solvent_refund",
        }
        or any(
            type(v) not in {int, float} or not math.isfinite(v) or not 0 < v <= 50
            for v in sol.values()
        )
        or sol["solvent_refund"] >= sol["recurring_cost"]
    ):
        raise ValueError("面包骚乱完整配对政策必须具有独立有限福利、激进化及经常费用参数")
    hokkaido = data["hokkaido_policy"]
    if hokkaido != {
        "recurring_cost": 2,
        "covered_cost_refund": 1,
        "throughput": 2,
        "high_operation": 2,
        "potential_demand": 2,
        "acute_demand": 2,
        "wheat_replacement": 8,
        "wheat_large": 20,
        "wheat_operating": 4,
    } or any(type(v) is not int for v in hokkaido.values()):
        raise ValueError("北海道有界政策参数或安全区间漂移")
    return data


def _block(parent: Block, key: str) -> Block:
    rows = parent.all(key)
    if len(rows) != 1 or rows[0].op != "=" or not isinstance(rows[0].value, Block):
        raise ValueError(f"事件原版块不唯一：{key}")
    return rows[0].value


def _scalar(parent: Block, key: str, value: str, op: str = "=") -> None:
    rows = parent.all(key)
    if (
        len(rows) != 1
        or rows[0].op != op
        or not isinstance(rows[0].value, Scalar)
        or rows[0].value.unquoted != value
    ):
        raise ValueError(f"事件原版标量漂移：{key}")


def _options(event: Block) -> dict[str, Block]:
    result = {}
    for row in event.all("option"):
        if not isinstance(row.value, Block):
            raise ValueError("事件选项不是块")
        names = row.value.all("name")
        if len(names) != 1 or not isinstance(names[0].value, Scalar):
            raise ValueError("事件选项必须具有唯一常量name")
        name = names[0].value.unquoted
        if name in result:
            raise ValueError("事件选项name重复")
        result[name] = row.value
    return result


def _shape(block: Block) -> tuple:
    rows = []
    for row in block.assignments():
        if isinstance(row.value, Block):
            value: str | tuple = _shape(row.value)
        elif isinstance(row.value, Scalar):
            value = row.value.unquoted
        else:
            raise ValueError("事件原版证据无值")
        rows.append((row.key, row.op, value))
    if len(rows) != len(block.items):
        raise ValueError("事件原版证据含非赋值项")
    return tuple(rows)


def _verify_plague(roots: Mapping[str, Block]) -> None:
    plague = _block(roots[PLAGUE], PLAGUE_EVENT)
    _scalar(plague, "type", "country_event")
    _scalar(plague, "placement", "ROOT")
    if _block(plague, "trigger").items:
        raise ValueError("疫情响应原版空事件trigger漂移")
    options = _options(plague)
    if tuple(options) != PLAGUE_OPTIONS or any(
        option.all("ai_chance") for option in options.values()
    ):
        raise ValueError("疫情完整三选项未声明AI权重底本漂移")
    for name, variable in zip(
        PLAGUE_OPTIONS[:2], ("plague_lockdown", "plague_measures"), strict=True
    ):
        _scalar(_block(options[name], "set_variable"), "name", variable)
        states = _block(options[name], "every_scope_state")
        _scalar(_block(states, "limit"), "has_modifier", "plague_modifier")
        _scalar(_block(states, "add_modifier"), "name", variable + "_mod")
        _scalar(_block(states, "add_modifier"), "months", "6")
        # Native removal is inside each state, not a country-level exclusive switch.
        if not any(
            isinstance(row.value, Block) and row.value.all("remove_variable")
            for row in states.all("if")
        ) or options[name].all("remove_variable"):
            raise ValueError("疫情响应国家/州变量写入范围漂移")
    _scalar(options[PLAGUE_OPTIONS[1]], "default_option", "yes")
    if options[PLAGUE_OPTIONS[0]].all("default_option") or options[PLAGUE_OPTIONS[2]].all(
        "default_option"
    ):
        raise ValueError("疫情原版默认选项漂移")
    removes = options[PLAGUE_OPTIONS[2]].all("remove_variable")
    if [row.value.unquoted for row in removes if isinstance(row.value, Scalar)] != [
        "plague_measures",
        "plague_lockdown",
    ]:
        raise ValueError("不响应原版国家变量清除漂移")
    for modifier, key, amount in (
        ("plague_modifier", "state_mortality_mult", "0.5"),
        ("plague_lockdown_mod", "building_throughput_add", "-0.5"),
        ("plague_measures_mod", "building_throughput_add", "-0.25"),
    ):
        _scalar(_block(roots[PLAGUE_MODIFIERS], modifier), key, amount)
    decision = _block(roots[PLAGUE_DECISION], "spanish_flu_response")
    _scalar(
        _block(_block(decision, "is_shown"), "any_scope_state"), "has_modifier", "plague_modifier"
    )
    taken = _block(decision, "when_taken")
    _scalar(_block(taken, "set_variable"), "name", "plague_response_cooldown")
    _scalar(_block(taken, "set_variable"), "days", "182")
    _scalar(_block(_block(taken, "hidden_effect"), "trigger_event"), "id", PLAGUE_EVENT)
    _scalar(_block(decision, "ai_chance"), "value", "10")
    effect = _block(roots[PLAGUE_EFFECTS], "randomize_plague_level_effect")
    for variable, amount in (("plague_lockdown", "-3"), ("plague_measures", "-1")):
        expected = (
            ("limit", "=", (("owner", "=", (("has_variable", "=", variable),)),)),
            ("change_variable", "=", (("name", "=", "plague_level"), ("add", "=", amount))),
        )
        if (
            sum(
                isinstance(row.value, Block) and _shape(row.value) == expected
                for row in effect.all("if")
            )
            != 1
        ):
            raise ValueError("疫情原版后继保护强度/owner响应范围漂移")
    _block(roots[PLAGUE_JOURNAL], "je_spanish_flu")
    finance = _block(roots[FINANCE], "amazonas.1")
    _scalar(finance, "type", "country_event")
    _scalar(_block(finance, "trigger"), "in_default", "no")


DISASTER_PARENT_SHAPES = {
    "natural_disaster_events.1": "ed4e78199a230ec3ac0f1cfa0cbebbc9ed28e605efa34169010da3d0fa6c4b51",
    "natural_disaster_events.2": "e686360f7dac53f71da43e87442043cad50cae24481837b14795667d236effb1",
    "natural_disaster_events.3": "2525f39b6214078d51c895e7cdb6afa7d676b4e2150a570282596f4c9c323fea",
    "natural_disaster_events.4": "a420602ccb9b3f954052f6d676faeca2f88ee0226dc6aa1fa3aade4273075bda",
    "natural_disaster_events.5": "4f552a0153352c9ca213a12b9e0da7b166918440fa03a55514d019ba53566bec",
    "natural_disaster_events.6": "b8cf95270870ad224463d71c1d45491e0db8eac4e61dfbd6c7d1b5defdce4694",
    "natural_disaster_events.7": "e78554a0131cd1348b105c235c06223fdaf850a4b75415ad33e3dbea840aed11",
    "natural_disaster_events.8": "e5d8b2c0114b36c986f0c290311954e7787e4cb056cbc7a1a00483aae3cb892c",
}


def _verify_disasters(roots: Mapping[str, Block], inputs: Mapping[str, str]) -> None:
    from pdx.situated.native_treatments import _digest  # noqa: PLC0415

    for index, name in enumerate(DISASTER_EVENTS):
        event = _block(roots[DISASTERS], name)
        digest = _digest(roots[DISASTERS].all(name)[0])
        if digest != DISASTER_PARENT_SHAPES[name]:
            raise ValueError(f"灾害完整父事件AST漂移：{name}")
        _scalar(event, "type", "country_event")
        _scalar(event, "placement", "scope:" + DISASTER_SCOPES[index])
        options = _options(event)
        if tuple(options) != (name + ".a", name + ".b") or any(
            option.all("ai_chance") for option in options.values()
        ):
            raise ValueError("灾害完整双选项未声明权重底本漂移")
        _scalar(
            _block(roots[PLAGUE_MODIFIERS], "modifier_" + DISASTER_RELIEF[index] + "_relief"),
            "country_expenses_add",
            "1",
        )
    for modifier, amount in (
        ("modifier_crop_failure", "-0.6"),
        ("modifier_crop_failure_relief_effect", "-0.3"),
    ):
        for group in ("agriculture", "plantations"):
            _scalar(
                _block(roots[PLAGUE_MODIFIERS], modifier),
                f"building_group_bg_{group}_throughput_add",
                amount,
            )
    _scalar(
        _block(roots[PLAGUE_MODIFIERS], "modifier_crop_failure_relief_effect"),
        "state_welfare_payments_add",
        "0.15",
    )
    values = roots[EVENT_VALUES]
    _scalar(values, "short_modifier_time", "913")
    _scalar(values, "normal_modifier_time", "1825")
    for size, divisor, factor, rounded in (
        ("small", "100000", "0.15", "100"),
        ("medium", "100000", "0.25", "100"),
        ("large", "1000000", "0.5", "1000"),
    ):
        expected = (
            ("value", "=", "root.gdp"),
            ("divide", "=", divisor),
            ("multiply", "=", factor),
            ("round", "=", "yes"),
            ("multiply", "=", rounded),
            ("min", "=", "100"),
        )
        if _shape(_block(values, "money_amount_multiplier_" + size)) != expected:
            raise ValueError("灾害GDP经常费用脚本值AST漂移")
    yearly = _block(_block(roots[YEARLY], "on_yearly_events"), "random_events")
    _scalar(yearly, "chance_to_happen", "65")
    for name, weight in zip(
        DISASTER_EVENTS, ("3", "3", "1", "1", "20", "3", "3", "1"), strict=True
    ):
        if (
            sum(
                row.key == weight and isinstance(row.value, Scalar) and row.value.unquoted == name
                for row in yearly.assignments()
            )
            != 1
        ):
            raise ValueError("灾害实际年度国家调用权重漂移")
    pulse = _block(_block(roots[ON_ACTIONS], "on_yearly_pulse_country"), "on_actions")
    if sum(
        isinstance(row, Scalar) and row.unquoted == "on_yearly_events" for row in pulse.items
    ) != 1 or not inputs[YEARLY].startswith("# Fired off on_yearly_pulse_country"):
        raise ValueError("灾害年度国家ROOT调用链漂移")
    population = _block(
        _block(_block(roots[STATE_POPULATION], "wild_west.1"), "trigger"), "any_scope_state"
    )
    _scalar(population, "state_population", "100000", "<")


def _source_roots(inputs: Mapping[str, str], sources: frozenset[str]) -> dict[str, Block]:
    roots = {}
    hashes = load()["sources"]
    for name in sorted(sources):
        digest = hashes[name]
        text = inputs.get(name)
        if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != digest:
            raise ValueError(f"事件完整原版来源漂移：{name}")
        if name in {SOL_JOURNAL_DOC, "common/scripted_buttons/scripted_buttons.md"}:
            # Native documentation is evidence, never a PDX script to parse.
            continue
        parsed = parse_text(text)
        if parsed.errors:
            raise ValueError(f"事件完整原版解析失败：{name}")
        roots[name] = parsed.root
    return roots


def _verify_legacy_inputs(inputs: Mapping[str, str]) -> None:
    roots = _source_roots(inputs, LEGACY_SOURCES)
    event = _block(roots[SOURCE], EVENT)
    _scalar(event, "type", "country_event")
    _scalar(event, "placement", "ROOT")
    _scalar(_block(event, "trigger"), "is_enacting_law", "law_type:law_public_health_insurance")
    _block(event, "cancellation_trigger")
    saved = _block(_block(event, "immediate"), "random_interest_group")
    _scalar(saved, "save_scope_as", "anti_public_healthcare_ig")
    _scalar(_block(saved, "limit"), "ig_counts_as_marginal", "no")
    _scalar(_block(_block(saved, "limit"), "law_stance"), "value", "neutral", "<")
    options = _options(event)
    if tuple(options) != OPTIONS:
        raise ValueError("医疗事件完整选项分母漂移")
    for name, option in options.items():
        chance = _block(option, "ai_chance")
        _scalar(chance, "base", "50")
        if name == OPTIONS[0]:
            _scalar(option, "default_option", "yes")
            native = _block(chance, "modifier")
            _scalar(native, "add", "-25")
            _scalar(
                _block(_block(native, "trigger"), "scope:anti_public_healthcare_ig"),
                "ig_approval",
                "-5",
                "<",
            )
        elif chance.all("modifier") or option.all("default_option"):
            raise ValueError("医疗事件原版第二选项权重/default漂移")
    _scalar(
        _block(roots[MODIFIERS], "opening_up_healthcare"),
        "country_law_enactment_success_add",
        "0.1",
    )
    _scalar(
        _block(roots[MODIFIERS], "healthcare_debate_ig_ignored"),
        "interest_group_approval_add",
        "-4",
    )
    _scalar(
        _block(roots[MODIFIERS], "healthcare_debate_ig_concerns_heard"),
        "interest_group_approval_add",
        "2",
    )
    hook = _block(roots[ON_ACTIONS], "on_law_checkpoint_debate")
    if (
        sum(
            isinstance(r.value, Scalar) and r.value.unquoted == EVENT and r.key == "10"
            for r in _block(hook, "random_events").assignments()
        )
        != 1
    ):
        raise ValueError("医疗debate事件唯一调用权重漂移")
    hook_line = roots[ON_ACTIONS].all("on_law_checkpoint_debate")[0].line
    if (
        inputs[ON_ACTIONS].splitlines()[hook_line - 3].strip()
        != "# Root = owner Country of the Law"
    ):
        raise ValueError("法律debate事件调用ROOT说明漂移")
    # Independent native AIWeight supports scalar additive modifiers and
    # country observations. It does not prove ScriptValue operands or defaults.
    negotiation = _block(roots[SYNTAX], "negotiation.1")
    bureaucracy = _options(negotiation)["negotiation.1.o2"]
    native_mods = _block(bureaucracy, "ai_chance").all("modifier")
    if not any(
        isinstance(m.value, Block) and m.value.all("trigger") and m.value.all("add")
        for m in native_mods
    ):
        raise ValueError("事件AIWeight独立语法证据漂移")
    _verify_plague(roots)
    _verify_disasters(roots, inputs)
    _scalar(
        _block(_block(roots[HEALTH], "law_public_health_insurance"), "institution_modifier"),
        "state_standard_of_living_add",
        "0.5",
    )


def verify_sol_inputs(inputs: Mapping[str, str]) -> None:
    """Prove this exact pair and all nine caller/effect/reader sources."""
    from pdx.situated.native_treatments import _digest  # noqa: PLC0415

    roots = _source_roots(inputs, SOL_SOURCES)
    event = _block(roots[SOL], SOL_EVENT)
    if _digest(roots[SOL].all(SOL_EVENT)[0]) != SOL_PARENT_SHAPE:
        raise ValueError("面包骚乱完整父事件AST漂移")
    _scalar(event, "type", "country_event")
    saved = _block(_block(event, "immediate"), "random_scope_state")
    _scalar(_block(saved, "limit"), "is_capital", "yes")
    _scalar(saved, "save_scope_as", "slums_state")
    options = _options(event)
    if tuple(options) != SOL_OPTIONS:
        raise ValueError("面包骚乱完整双选项身份漂移")
    for name, trigger in zip(SOL_OPTIONS, ("ai_avoids_radicals", "ai_wants_radicals"), strict=True):
        if _shape(_block(options[name], "ai_chance")) != (
            ("base", "=", "1"),
            ("modifier", "=", (("trigger", "=", ((trigger, "=", "yes"),)), ("add", "=", "10"))),
        ):
            raise ValueError("面包骚乱当前显式原版权重完整AST漂移")
    _scalar(options[SOL_OPTIONS[0]], "default_option", "yes")
    expense = _block(options[SOL_OPTIONS[0]], "add_modifier")
    _scalar(expense, "name", "starvation_palliative_modifier")
    _scalar(expense, "multiplier", "money_amount_multiplier_small")
    _scalar(expense, "days", "normal_modifier_time")
    welfare = _block(_block(options[SOL_OPTIONS[0]], "scope:slums_state"), "add_modifier")
    _scalar(welfare, "name", "bread_riots_modifier")
    _scalar(welfare, "days", "normal_modifier_time")
    radical = _block(_block(options[SOL_OPTIONS[1]], "scope:slums_state"), "add_radicals_in_state")
    _scalar(radical, "strata", "lower")
    _scalar(radical, "value", "medium_radicals")
    _scalar(
        _block(roots[PLAGUE_MODIFIERS], "bread_riots_modifier"),
        "state_lower_strata_standard_of_living_add",
        "1",
    )
    _scalar(
        _block(roots[PLAGUE_MODIFIERS], "starvation_palliative_modifier"),
        "country_expenses_add",
        "1",
    )
    _scalar(roots[EVENT_VALUES], "medium_radicals", "0.05")
    _scalar(roots[EVENT_VALUES], "normal_modifier_time", "1825")
    if _shape(_block(roots[EVENT_VALUES], "money_amount_multiplier_small")) != (
        ("value", "=", "root.gdp"),
        ("divide", "=", "100000"),
        ("multiply", "=", "0.15"),
        ("round", "=", "yes"),
        ("multiply", "=", "100"),
        ("min", "=", "100"),
    ):
        raise ValueError("面包骚乱GDP经常费用脚本值AST漂移")
    journal = _block(roots[SOL_JOURNAL], "je_sol_1")
    _scalar(journal, "group", "je_group_crises")
    calls = _block(_block(journal, "on_monthly_pulse"), "random_events")
    if _shape(calls) != (
        ("100", "=", "0"),
        ("10", "=", "sol_events.3"),
        ("10", "=", "sol_events.4"),
        ("10", "=", "sol_events.5"),
        ("10", "=", SOL_EVENT),
    ):
        raise ValueError("面包骚乱JE月度调用分布漂移")
    _scalar(_block(roots[SOL_JOURNAL_GROUP], "je_group_crises"), "context", "country")
    doc = inputs[SOL_JOURNAL_DOC].splitlines()
    if doc[333:335] != [
        "        # root = owning country or no scope",
        "        on_monthly_pulse = {",
    ]:
        raise ValueError("面包骚乱JE月度ROOT原版说明漂移")
    nursing_state = _block(
        _block(
            _block(_block(roots[SOL_OWNER], "nursing_events.2"), "immediate"), "ordered_scope_war"
        ),
        "random_scope_front",
    )
    _scalar(_block(_block(nursing_state, "random_scope_state"), "limit"), "owner", "root")
    population = _block(
        _block(_block(roots[STATE_POPULATION], "wild_west.1"), "trigger"), "any_scope_state"
    )
    _scalar(population, "state_population", "100000", "<")
    finance = _block(roots[FINANCE], "amazonas.1")
    _scalar(finance, "type", "country_event")
    _scalar(_block(finance, "trigger"), "in_default", "no")


def verify_inputs(inputs: Mapping[str, str]) -> None:
    _verify_legacy_inputs(inputs)
    verify_sol_inputs(inputs)
    verify_hokkaido_inputs(inputs)


def frozen_inputs() -> dict[str, str]:
    data = json.loads(FROZEN.read_text(encoding="utf-8"))
    if (
        set(data)
        != {"schema", "evidence", "normalization", "source_hashes", "raw_source_hashes", "inputs"}
        or data["schema"] != 1
        or data["evidence"] != "static_complete_native_sources_not_engine_execution"
        or data["normalization"] != "utf8_without_bom_lf_preserve_whitespace"
        or data["source_hashes"] != load()["sources"]
        or set(data["inputs"]) != set(data["source_hashes"])
    ):
        raise ValueError("事件冻结完整底本schema漂移")
    verify_inputs(data["inputs"])
    return cast("dict[str, str]", data["inputs"])


@dataclass(frozen=True, slots=True)
class EventPolicyIdentity:
    source: str
    event: str
    family: str
    explicit: bool
    saved_state: str | None = None


POLICIES = {
    **{
        name: EventPolicyIdentity(
            HOKKAIDO, HOKKAIDO_EVENT, "hokkaido", False, "hokkaido_state_scope"
        )
        for name in HOKKAIDO_OPTIONS
    },
    **{name: EventPolicyIdentity(SOURCE, EVENT, "healthcare", False) for name in OPTIONS},
    **{name: EventPolicyIdentity(PLAGUE, PLAGUE_EVENT, "plague", True) for name in PLAGUE_OPTIONS},
    **{
        option: EventPolicyIdentity(DISASTERS, name, "disaster", True, scope)
        for name, scope in zip(DISASTER_EVENTS, DISASTER_SCOPES, strict=True)
        for option in (name + ".a", name + ".b")
    },
    **{
        name: EventPolicyIdentity(SOL, SOL_EVENT, "sol_response", False, "slums_state")
        for name in SOL_OPTIONS
    },
}


def required_program_sources(program: EventProgram) -> tuple[str, ...]:
    """Keep existing 21 programs' exact 15-source contracts unchanged."""
    return tuple(
        sorted(
            HOKKAIDO_SOURCES
            if program.identity.family == "hokkaido"
            else SOL_SOURCES
            if program.identity.family == "sol_response"
            else LEGACY_SOURCES
        )
    )


@dataclass(frozen=True, slots=True)
class EventProgram:
    option: str
    scalar: programs.ScalarProgram

    @property
    def identity(self) -> EventPolicyIdentity:
        try:
            return POLICIES[self.option]
        except KeyError as exc:
            raise ValueError("事件选项没有精确注册政策身份") from exc

    @property
    def source(self) -> str:
        return self.identity.source

    @property
    def event(self) -> str:
        return self.identity.event

    @property
    def field_path(self) -> tuple[str, ...]:
        # Event IDs contain dots and option is a repeated key, not a dotted path.
        return (self.event, f"option[{self.option}]", "ai_chance")

    @property
    def field(self) -> str:
        return ".".join(self.field_path)

    @property
    def writer_id(self) -> str:
        return self.scalar.action_id

    @property
    def consumer_id(self) -> str:
        return f"event_option:{self.option}"

    def validate(self) -> None:
        if self not in compile_programs():
            raise ValueError("事件完整程序与生产参数或精确选项身份不一致")
        if self.identity.family == "hokkaido":
            for reader in self.readers():
                validate_hokkaido_reader(
                    reader, self.source, self.field_path, self.evaluation_context()
                )

    def evaluation_context(self) -> EvaluationContext:
        from pdx.situated.decision_ir import ContextBinding, EvaluationContext  # noqa: PLC0415

        if self.identity.family == "hokkaido":
            return EvaluationContext(
                actor_scope=ContextBinding(
                    "root", "country", "actor", "common/scripted_buttons/scripted_buttons.md", 19
                ),
                auxiliary_scopes=(
                    ContextBinding("hokkaido_state_scope", "state", "auxiliary", HOKKAIDO, 477),
                ),
                evidence=(
                    "common/scripted_buttons/scripted_buttons.md:19",
                    "common/scripted_buttons/07_japan_buttons.txt:414",
                    "common/journal_entries/07_hokkaido.txt:9",
                    f"{HOKKAIDO}:477",
                ),
            )
        if self.identity.family == "sol_response":
            return EvaluationContext(
                actor_scope=ContextBinding("root", "country", "actor", SOL_JOURNAL_GROUP, 108),
                auxiliary_scopes=(ContextBinding("slums_state", "state", "auxiliary", SOL, 622),),
                evidence=(
                    f"{SOL_JOURNAL_GROUP}:108",
                    f"{SOL_JOURNAL_DOC}:334",
                    f"{SOL_JOURNAL}:4",
                    f"{SOL_JOURNAL}:78",
                    f"{SOL}:622",
                ),
            )
        if self.identity.family == "disaster":
            line = DISASTER_SAVED_LINES[DISASTER_EVENTS.index(self.event)]
            return EvaluationContext(
                actor_scope=ContextBinding("root", "country", "actor", ON_ACTIONS, 1580),
                auxiliary_scopes=(
                    ContextBinding(
                        cast("str", self.identity.saved_state),
                        "state",
                        "auxiliary",
                        DISASTERS,
                        line,
                    ),
                ),
                evidence=(
                    f"{ON_ACTIONS}:1580",
                    f"{ON_ACTIONS}:1840",
                    f"{YEARLY}:4",
                    f"{DISASTERS}:{line}",
                ),
            )
        if self.identity.family == "plague":
            return EvaluationContext(
                actor_scope=ContextBinding("root", "country", "actor", PLAGUE_DECISION, 1),
                evidence=(f"{PLAGUE_DECISION}:1", f"{PLAGUE_DECISION}:25", f"{PLAGUE}:365"),
            )
        return EvaluationContext(
            actor_scope=ContextBinding("root", "country", "actor", ON_ACTIONS, 4670),
            auxiliary_scopes=(
                ContextBinding(
                    "anti_public_healthcare_ig", "interest_group", "auxiliary", SOURCE, 403
                ),
            ),
            evidence=(f"{ON_ACTIONS}:4670", f"{ON_ACTIONS}:4712", f"{SOURCE}:403"),
        )

    def reader_bindings(self) -> tuple[tuple[str, str, str, str], ...]:
        if self.identity.family in {"disaster", "sol_response", "hokkaido"}:
            return tuple(
                (
                    reader.key,
                    reader.scope,
                    "country" if reader.scope == "root" else "state",
                    "actor" if reader.scope == "root" else "auxiliary",
                )
                for reader in self.readers()
            )
        if self.identity.family == "plague":
            return tuple((reader.key, "root", "country", "actor") for reader in self.readers())
        return (
            ("average_sol", "root", "country", "actor"),
            ("opponent_exists", "anti_public_healthcare_ig", "interest_group", "auxiliary"),
            ("opponent_clout", "anti_public_healthcare_ig", "interest_group", "auxiliary"),
        )

    def evaluate(self, values: Mapping[str, object], *, is_ai: bool, enabled: bool = True) -> float:
        """Evaluate this exact IR-owned scalar, without recompiling a second plan."""
        from pdx.situated import programs  # noqa: PLC0415

        if type(is_ai) is not bool or type(enabled) is not bool:
            raise ValueError("事件AI身份与开关必须为已知布尔")
        return (
            programs.evaluate_scalar(self.scalar, _guards(values, self))
            if is_ai and enabled
            else 0.0
        )

    def readers(self) -> tuple[Reader, ...]:
        from pdx.decision_rules import Reader  # noqa: PLC0415

        if self.identity.family == "hokkaido":
            return hokkaido_readers(self.option)
        if self.identity.family == "sol_response":
            return (
                Reader(
                    "sol_response_state_exists",
                    "exists",
                    "root",
                    "boolean",
                    "boolean",
                    argument="scope:slums_state",
                ),
                Reader(
                    "sol_response_state_owned",
                    "owner",
                    "slums_state",
                    "boolean",
                    "boolean",
                    argument="root",
                ),
                Reader(
                    "sol_response_state_population",
                    "state_population",
                    "slums_state",
                    "persons",
                    "number",
                    minimum=0,
                ),
                Reader("sol_response_default", "in_default", "root", "boolean", "boolean"),
            )
        if self.identity.family == "disaster":
            scope = cast("str", self.identity.saved_state)
            readers: tuple[Reader, ...] = (
                Reader(
                    "disaster_" + scope + "_exists",
                    "exists",
                    "root",
                    "boolean",
                    "boolean",
                    argument="scope:" + scope,
                ),
                Reader(
                    "disaster_" + scope + "_population",
                    "state_population",
                    scope,
                    "persons",
                    "number",
                    minimum=0,
                ),
                Reader("disaster_default", "in_default", "root", "boolean", "boolean"),
            )
            if self.event == "natural_disaster_events.5":
                readers += tuple(
                    Reader(
                        "disaster_" + scope + "_farm_" + mode,
                        "any_scope_building",
                        scope,
                        "boolean",
                        "boolean",
                        parameters=((DISASTER_QUERY_PARAMETER, mode),),
                    )
                    for mode in ("qualified", "high")
                )
            return readers
        if self.identity.family == "plague":
            return (
                *(
                    Reader(
                        "plague_" + mode,
                        "any_scope_state",
                        "root",
                        "boolean",
                        "boolean",
                        parameters=((QUERY_PARAMETER, mode),),
                    )
                    for mode in ("infected", "restricted", "lockdown")
                ),
                *(
                    Reader(
                        "plague_response_" + mode,
                        "has_variable",
                        "root",
                        "boolean",
                        "boolean",
                        argument="plague_" + mode,
                    )
                    for mode in ("lockdown", "measures")
                ),
                Reader("plague_default", "in_default", "root", "boolean", "boolean"),
            )
        return (
            Reader("average_sol", "average_sol", "root", "standard_of_living", "number", minimum=0),
            Reader(
                "opponent_exists",
                "exists",
                "root",
                "boolean",
                "boolean",
                argument="scope:anti_public_healthcare_ig",
            ),
            Reader(
                "opponent_clout",
                "ig_clout",
                "anti_public_healthcare_ig",
                "ratio",
                "number",
                minimum=0,
                maximum=1,
            ),
        )

    def writer_ir(self) -> WriterDecisionIR:
        from pdx.situated.decision_ir import WriterDecisionIR  # noqa: PLC0415

        self.validate()
        return WriterDecisionIR(
            writer_id=self.writer_id,
            kind="event_program",
            source=self.source,
            definition=self.option,
            consumer_id=self.consumer_id,
            field=self.field,
            actor="root",
            target="none",
            operation="add",
            vanilla_tail="preserve",
            owner="event_opportunities",
            event_program=self,
            evaluation_context=self.evaluation_context(),
            reader_context_bindings=self.reader_bindings(),
        )

    def as_dict(self) -> dict[str, object]:
        hashes = load()["sources"]
        return {
            "option": self.option,
            "event": self.event,
            "source": self.source,
            "field": self.field,
            "field_path": list(self.field_path),
            "writer_id": self.writer_id,
            "consumer_id": self.consumer_id,
            "domain": DOMAIN,
            "operation": "add",
            "vanilla_tail": "preserve",
            "scalar": asdict(self.scalar),
            "evaluation_context": self.evaluation_context().as_dict(),
            "reader_context_bindings": [list(row) for row in self.reader_bindings()],
            "readers": [asdict(reader) for reader in self.readers()],
            "source_hashes": {name: hashes[name] for name in required_program_sources(self)},
            "policy": (
                "explicit_new_three_option_policy_native_default_unknown"
                if self.identity.family == "plague"
                else "explicit_new_paired_policy_native_default_unknown"
                if self.identity.explicit
                else "additive_to_explicit_native_weight"
            ),
        }


def compile_programs() -> tuple[EventProgram, ...]:
    from pdx.situated import programs  # noqa: PLC0415

    tuning = load()["tuning"]
    result = []
    for option in OPTIONS:
        early = option == OPTIONS[0]
        benefit = tuning["reform_need"] * (1 if early else -1)
        political = -tuning["ignored_opponent_cost"] if early else tuning["heard_opponent_benefit"]
        term = (
            programs.ScalarTerm(
                "opponent_exists",
                "event_healthcare_opposition_cost",
                political,
                (programs.ScalarEffect("opponent_cheap", -political),),
            )
            if early
            else programs.ScalarTerm(
                "opponent_powerful", "event_healthcare_opposition_benefit", political
            )
        )
        scalar = programs.ScalarProgram(
            f"event_healthcare_{'advance' if early else 'listen'}",
            "add",
            0.0,
            -10.0,
            10.0,
            (
                programs.ScalarGroup(
                    "actual_social_need",
                    (
                        programs.ScalarTerm(
                            "social_need",
                            f"event_healthcare_need_{'advance' if early else 'listen'}",
                            benefit,
                        ),
                    ),
                ),
                programs.ScalarGroup("actual_opposition", (term,)),
            ),
        )
        result.append(EventProgram(option, scalar))
    return (
        *result,
        *_compile_plague_programs(),
        *_compile_disaster_programs(),
        *_compile_sol_programs(),
        *_compile_hokkaido_programs(),
    )


def _compile_sol_programs() -> tuple[EventProgram, ...]:
    from pdx.situated import programs  # noqa: PLC0415

    policy = load()["sol_response_policy"]
    result = []
    for suffix, sign in (("a", 1), ("b", -1)):
        groups = (
            programs.ScalarGroup(
                "actual_saved_lower_strata_sol",
                (
                    programs.ScalarTerm(
                        "sol_response_core",
                        f"sol_response_{suffix}_lower_sol",
                        sign * policy["lower_sol"],
                        (
                            programs.ScalarEffect(
                                "sol_response_high", sign * policy["high_exposure"]
                            ),
                        ),
                    ),
                ),
            ),
            programs.ScalarGroup(
                "avoided_saved_lower_strata_radicalization",
                (
                    programs.ScalarTerm(
                        "sol_response_core",
                        f"sol_response_{suffix}_radicals",
                        sign * policy["avoided_radicals"],
                    ),
                ),
            ),
            programs.ScalarGroup(
                "independent_five_year_country_recurring_expense",
                (
                    programs.ScalarTerm(
                        "sol_response_country_cost",
                        f"sol_response_{suffix}_financing",
                        -sign * policy["recurring_cost"],
                        (
                            programs.ScalarEffect(
                                "sol_response_solvent", sign * policy["solvent_refund"]
                            ),
                        ),
                    ),
                ),
            ),
        )
        result.append(
            EventProgram(
                SOL_EVENT + "." + suffix,
                programs.ScalarProgram(
                    f"event_sol_response_{suffix}", "add", policy["base"], 12, 88, groups
                ),
            )
        )
    return tuple(result)


def _compile_plague_programs() -> tuple[EventProgram, ...]:
    from pdx.situated import programs  # noqa: PLC0415

    policy = load()["plague_policy"]
    result = []
    for index, option in enumerate(PLAGUE_OPTIONS):
        lockdown, measures = index == 0, index == 1
        health = (
            policy["lockdown_health"]
            if lockdown
            else policy["measures_health"]
            if measures
            else -policy["no_response_health_cost"]
        )
        groups = [
            programs.ScalarGroup(
                "actual_epidemic_health_need",
                (programs.ScalarTerm("plague_infected", f"{option}_health_need", health),),
            )
        ]
        if index < 2:
            mode = "lockdown" if lockdown else "measures"
            financing = policy[mode + "_financing"]
            groups.extend(
                (
                    programs.ScalarGroup(
                        "actual_six_month_throughput_cost",
                        (
                            programs.ScalarTerm(
                                "plague_infected",
                                f"{option}_throughput",
                                -policy[mode + "_throughput"],
                            ),
                        ),
                    ),
                    programs.ScalarGroup(
                        "independent_financing_cost",
                        (
                            programs.ScalarTerm(
                                "plague_infected",
                                f"{option}_financing",
                                -financing,
                                (programs.ScalarEffect("plague_solvent", financing),),
                            ),
                        ),
                    ),
                    programs.ScalarGroup(
                        "observed_response_continuity",
                        (
                            programs.ScalarTerm(
                                "plague_continue_" + mode,
                                f"{option}_continuity",
                                policy["response_continuity"],
                            ),
                        ),
                    ),
                )
            )
        else:
            groups.extend(
                (
                    programs.ScalarGroup(
                        "observed_throughput_release",
                        (
                            programs.ScalarTerm(
                                "plague_restricted",
                                f"{option}_throughput_release",
                                policy["measures_throughput"],
                                (
                                    programs.ScalarEffect(
                                        "plague_lockdown",
                                        policy["lockdown_throughput"]
                                        - policy["measures_throughput"],
                                    ),
                                ),
                            ),
                        ),
                    ),
                    programs.ScalarGroup(
                        "observed_recovery_exit",
                        (
                            programs.ScalarTerm(
                                "plague_recovered_response",
                                f"{option}_recovery_exit",
                                policy["recovery_exit"],
                            ),
                        ),
                    ),
                )
            )
        result.append(
            EventProgram(
                option,
                programs.ScalarProgram(
                    f"event_plague_{('lockdown', 'measures', 'release')[index]}",
                    "add",
                    policy["base"],
                    0,
                    100,
                    tuple(groups),
                ),
            )
        )
    return tuple(result)


def _compile_disaster_programs() -> tuple[EventProgram, ...]:
    from pdx.situated import programs  # noqa: PLC0415

    policy = load()["disaster_policy"]
    result = []
    for index, event in enumerate(DISASTER_EVENTS):
        mega, crop = index in {2, 3, 7}, index == 4
        size = "large" if mega else "medium" if index in {0, 1} else "small"
        prefix = event.replace(".", "_")
        for suffix, sign in (("a", -1), ("b", 1)):
            groups = []
            axes = (
                (
                    ("crop_throughput_relief", "actual_saved_crop_throughput"),
                    ("crop_welfare", "actual_saved_crop_welfare"),
                )
                if crop
                else (
                    (
                        "mega_relief" if mega else "ordinary_relief",
                        "actual_saved_region_devastation",
                    ),
                )
            )
            for key, cause in axes:
                groups.append(
                    programs.ScalarGroup(
                        cause,
                        (
                            programs.ScalarTerm(
                                prefix + "_exposed",
                                f"{prefix}_{suffix}_{cause}",
                                sign * policy[key],
                            ),
                        ),
                    )
                )
            high = policy[
                "crop_high_exposure"
                if crop
                else "mega_high_exposure"
                if mega
                else "ordinary_high_exposure"
            ]
            groups.append(
                programs.ScalarGroup(
                    "observed_exact_saved_exposure",
                    (
                        programs.ScalarTerm(
                            prefix + "_high", f"{prefix}_{suffix}_exposure", sign * high
                        ),
                    ),
                )
            )
            if suffix == "b":
                cost = policy[size + "_recurring_cost"]
                refund = cost * (1 - policy["solvent_cost_fraction"])
                groups.append(
                    programs.ScalarGroup(
                        "independent_country_recurring_expense",
                        (
                            programs.ScalarTerm(
                                prefix + "_exposed",
                                f"{prefix}_{suffix}_financing",
                                -cost,
                                (programs.ScalarEffect("disaster_solvent", refund),),
                            ),
                        ),
                    )
                )
            result.append(
                EventProgram(
                    event + "." + suffix,
                    programs.ScalarProgram(
                        f"event_disaster_{index + 1}_{suffix}",
                        "add",
                        policy["base"],
                        0,
                        100,
                        tuple(groups),
                    ),
                )
            )
    return tuple(result)


def _valid_number(value: object, minimum: float, maximum: float = math.inf) -> bool:
    if type(value) not in {int, float}:
        return False
    try:
        return math.isfinite(cast("float", value)) and minimum <= cast("float", value) <= maximum
    except OverflowError:
        return False


def _guards(values: Mapping[str, object], program: EventProgram) -> dict[str, bool]:
    sol, clout = values.get("average_sol"), values.get("opponent_clout")
    exists = values.get("opponent_exists") is True
    infected = values.get("plague_infected")
    result = {
        "social_need": _valid_number(sol, 0) and cast("float", sol) < 8,
        "opponent_exists": exists,
        "opponent_cheap": exists and _valid_number(clout, 0, 1) and cast("float", clout) < 0.2,
        "opponent_powerful": exists and _valid_number(clout, 0, 1) and cast("float", clout) >= 0.2,
        "plague_infected": infected is True,
        "plague_restricted": values.get("plague_restricted") is True,
        "plague_lockdown": values.get("plague_lockdown") is True,
        "plague_solvent": values.get("plague_default") is False,
        "plague_continue_lockdown": infected is True
        and values.get("plague_response_lockdown") is True,
        "plague_continue_measures": infected is True
        and values.get("plague_response_measures") is True,
        "plague_recovered_response": infected is False
        and (
            values.get("plague_response_lockdown") is True
            or values.get("plague_response_measures") is True
        ),
    }
    result["disaster_solvent"] = values.get("disaster_default") is False
    population = values.get("sol_response_state_population")
    core = (
        program.identity.family == "sol_response"
        and values.get("sol_response_state_exists") is True
        and values.get("sol_response_state_owned") is True
        and _valid_number(population, 1)
    )
    result["sol_response_core"] = core
    result["sol_response_high"] = core and _valid_number(population, 100000)
    # The native country expense is unconditional; saved-state uncertainty
    # removes only the state benefits, never this independent commitment.
    result["sol_response_country_cost"] = program.identity.family == "sol_response"
    result["sol_response_solvent"] = values.get("sol_response_default") is False
    for index, event in enumerate(DISASTER_EVENTS):
        fact_prefix = "disaster_" + DISASTER_SCOPES[index]
        population = values.get(fact_prefix + "_population")
        exposed = (
            program.event == event
            and values.get(fact_prefix + "_exists") is True
            and _valid_number(population, 1)
            and (index != 4 or values.get(fact_prefix + "_farm_qualified") is True)
        )
        prefix = event.replace(".", "_")
        result[prefix + "_exposed"] = exposed
        result[prefix + "_high"] = exposed and (
            values.get(fact_prefix + "_farm_high") is True
            if index == 4
            else _valid_number(population, 100000)
        )
    result.update(_hokkaido_guards(values, program))
    return result


def evaluate(
    values: Mapping[str, object],
    *,
    is_ai: bool | None,
    enabled_domains: frozenset[str] = frozenset({DOMAIN}),
    enabled_families: frozenset[str] = FAMILIES,
    consumer_programs: tuple[EventProgram, ...] | None = None,
) -> dict[str, float]:
    if is_ai is None:
        return {}
    if type(is_ai) is not bool:
        raise ValueError("事件AI身份必须为已知布尔")
    if not is_ai or DOMAIN not in enabled_domains:
        return {}
    selected = compile_programs() if consumer_programs is None else consumer_programs
    if not enabled_families <= FAMILIES:
        raise ValueError("事件政策family开关含未知身份")
    return {
        row.option: row.evaluate(values, is_ai=is_ai)
        for row in selected
        if row.identity.family in enabled_families
    }


GUARDS = {
    "sol_response_core": "exists = scope:slums_state scope:slums_state = { owner = root state_population >= 1 }",
    "sol_response_high": "exists = scope:slums_state scope:slums_state = { owner = root state_population >= 100000 }",
    # The exact event context already proves country ROOT. This actor guard
    # deliberately has no saved-state dependency, matching native add_modifier.
    "sol_response_country_cost": "is_ai = yes",
    "sol_response_solvent": "in_default = no",
    "social_need": "average_sol >= 0 average_sol < 8",
    "opponent_exists": "exists = scope:anti_public_healthcare_ig",
    "opponent_cheap": "exists = scope:anti_public_healthcare_ig scope:anti_public_healthcare_ig = { ig_clout >= 0 ig_clout < 0.2 }",
    "opponent_powerful": "exists = scope:anti_public_healthcare_ig scope:anti_public_healthcare_ig = { ig_clout >= 0.2 ig_clout <= 1 }",
    "plague_infected": "any_scope_state = { has_modifier = plague_modifier }",
    "plague_restricted": "any_scope_state = { OR = { has_modifier = plague_lockdown_mod has_modifier = plague_measures_mod } }",
    "plague_lockdown": "any_scope_state = { has_modifier = plague_lockdown_mod }",
    "plague_solvent": "in_default = no",
    "plague_continue_lockdown": "any_scope_state = { has_modifier = plague_modifier } has_variable = plague_lockdown",
    "plague_continue_measures": "any_scope_state = { has_modifier = plague_modifier } has_variable = plague_measures",
    "plague_recovered_response": "NOT = { any_scope_state = { has_modifier = plague_modifier } } OR = { has_variable = plague_lockdown has_variable = plague_measures }",
}

for _event, _saved in zip(DISASTER_EVENTS, DISASTER_SCOPES, strict=True):
    _prefix = _event.replace(".", "_")
    _core = f"exists = scope:{_saved} scope:{_saved} = {{ state_population >= 1 }}"
    if _event == "natural_disaster_events.5":
        _core += f" scope:{_saved} = {{ any_scope_building = {{ is_farm_building = yes occupancy >= 0.1 }} }}"
    GUARDS[_prefix + "_exposed"] = _core
    _high = (
        "any_scope_building = { is_farm_building = yes occupancy >= 0.5 }"
        if _event == "natural_disaster_events.5"
        else "state_population >= 100000"
    )
    GUARDS[_prefix + "_high"] = _core + f" scope:{_saved} = {{ {_high} }}"
GUARDS["disaster_solvent"] = "in_default = no"


@dataclass(frozen=True, slots=True)
class DisasterFarmQuery:
    observation: Literal["qualified", "high"]


@dataclass(frozen=True, slots=True)
class CompiledDisasterFarmQuery:
    expression: str
    references: tuple[str, ...]
    source_hashes: tuple[tuple[str, str], ...]
    local_collections: tuple[str, ...] = ("saved_state_buildings",)
    actor: str = "state"
    kind: str = "boolean"
    unknown_policy: str = (
        "known_farm_above_threshold=true; complete_empty=false; no_true_with_unknown=unknown"
    )
    world_scans: int = 0
    runtime_cost: str = (
        "bounded exact saved-state building existential; no world scan or persistent state"
    )


def disaster_query_from_reader(engine: str, parameters: Mapping[str, str]) -> DisasterFarmQuery:
    if (
        engine != "any_scope_building"
        or set(parameters) != {DISASTER_QUERY_PARAMETER}
        or parameters[DISASTER_QUERY_PARAMETER] not in {"qualified", "high"}
    ):
        raise ValueError("灾害农业查询必须是固定已保存州的真实农场占用率")
    return DisasterFarmQuery(
        cast("Literal['qualified', 'high']", parameters[DISASTER_QUERY_PARAMETER])
    )


def render_disaster_query(query: DisasterFarmQuery) -> str:
    if type(query) is not DisasterFarmQuery or query.observation not in {"qualified", "high"}:
        raise ValueError("灾害农业查询身份无效")
    threshold = "0.1" if query.observation == "qualified" else "0.5"
    return f"any_scope_building = {{ is_farm_building = yes occupancy >= {threshold} }}"


def required_disaster_query_sources(query: DisasterFarmQuery) -> tuple[str, ...]:
    render_disaster_query(query)
    return tuple(sorted(LEGACY_SOURCES))


def compile_disaster_query(
    query: DisasterFarmQuery, inputs: Mapping[str, str]
) -> CompiledDisasterFarmQuery:
    expression = render_disaster_query(query)
    _verify_legacy_inputs(inputs)
    return CompiledDisasterFarmQuery(
        expression,
        (f"{DISASTERS}:334", f"{DISASTERS}:349"),
        tuple((name, load()["sources"][name]) for name in sorted(LEGACY_SOURCES)),
    )


@dataclass(frozen=True, slots=True)
class PlagueStateQuery:
    observation: Literal["infected", "restricted", "lockdown"]


@dataclass(frozen=True, slots=True)
class CompiledPlagueStateQuery:
    expression: str
    references: tuple[str, ...]
    source_hashes: tuple[tuple[str, str], ...]
    local_collections: tuple[str, ...] = ("owned_states",)
    actor: str = "country"
    kind: str = "boolean"
    unknown_policy: str = (
        "any_observed_member=true; complete_empty=false; no_true_with_unknown_member=unknown"
    )
    world_scans: int = 0
    runtime_cost: str = (
        "bounded existential owned-state traversal; no world scan or persistent state"
    )


def query_from_reader(engine: str, parameters: Mapping[str, str]) -> PlagueStateQuery:
    if engine != "any_scope_state" or set(parameters) != {QUERY_PARAMETER}:
        raise ValueError("疫情观测只支持精确本国州查询")
    mode = parameters[QUERY_PARAMETER]
    if mode not in {"infected", "restricted", "lockdown"}:
        raise ValueError("疫情观测只支持固定原版modifier身份")
    return PlagueStateQuery(cast("Literal['infected', 'restricted', 'lockdown']", mode))


def render_query(query: PlagueStateQuery) -> str:
    if type(query) is not PlagueStateQuery or query.observation not in {
        "infected",
        "restricted",
        "lockdown",
    }:
        raise ValueError("疫情观测类型或固定本国州签名无效")
    return GUARDS["plague_" + query.observation]


def required_query_sources(query: PlagueStateQuery) -> tuple[str, ...]:
    render_query(query)
    return tuple(sorted(LEGACY_SOURCES))


def compile_query(query: PlagueStateQuery, inputs: Mapping[str, str]) -> CompiledPlagueStateQuery:
    expression = render_query(query)
    _verify_legacy_inputs(inputs)
    return CompiledPlagueStateQuery(
        expression,
        (f"{PLAGUE_DECISION}:3", f"{PLAGUE}:403", f"{PLAGUE}:480", f"{PLAGUE_MODIFIERS}:728"),
        tuple((name, load()["sources"][name]) for name in sorted(LEGACY_SOURCES)),
    )


def render(program: EventProgram) -> str:
    """Lower only proven linear AIWeight; reject a binding final clamp.

    Sum independent term extrema as a generation-time interval proof, rather
    than emit truth-table branches. Runtime growth is linear in terms.
    """
    from pdx.situated import programs  # noqa: PLC0415

    scalar = program.scalar
    new_policy = program.identity.explicit
    if (
        scalar.operation != "add"
        or (scalar.neutral != 0 and not new_policy and program.identity.family != "sol_response")
        or len(scalar.groups)
        > (
            3
            if program.identity.family == "hokkaido"
            else 4
            if new_policy or program.identity.family == "sol_response"
            else 2
        )
    ):
        raise ValueError("事件AIWeight桥只支持已证有限线性加法")
    chunks = [
        f"\n\t\t# SITAI BEGIN event:{program.option}\n\t\t# ACTION {program.writer_id} [political];\n"
    ]
    if new_policy:
        chunks.append(
            "\t\tai_chance = {\n\t\t\tbase = 0\n"
            "\t\t\t# Intentional AI-only policy; omitted native default is unknown.\n"
            f"\t\t\tmodifier = {{ trigger = {{ is_ai = yes }} add = {programs.numeric_literal(scalar.neutral)} }}\n"
        )
    if program.identity.family == "sol_response":
        chunks.append(
            f"\t\tmodifier = {{ trigger = {{ is_ai = yes }} add = {programs.numeric_literal(scalar.neutral)} }}\n"
        )
    minimum = maximum = Decimal(str(scalar.neutral))
    for group in scalar.groups:
        if group.selection != "first" or len(group.terms) != 1:
            raise ValueError("事件AIWeight不支持未经证明的极值/变体")
        term = group.terms[0]
        if term.preceding or term.id not in GUARDS:
            raise ValueError("事件AIWeight守卫或前序未证")
        amounts = [Decimal(str(term.amount))]
        for effect in term.effects:
            if effect.guard not in GUARDS or effect.otherwise:
                raise ValueError("事件AIWeight效果不支持else或未知守卫")
            amounts = [
                v + addition
                for v in amounts
                for addition in (Decimal(0), Decimal(str(effect.amount)))
            ]
        minimum += min(Decimal(0), *amounts)
        maximum += max(Decimal(0), *amounts)
        contributions = [(GUARDS[term.id], Decimal(str(term.amount)))]
        contributions.extend(
            (GUARDS[term.id] + " " + GUARDS[e.guard], Decimal(str(e.amount))) for e in term.effects
        )
        for guard, amount in contributions:
            if amount:
                chunks.append(
                    f"\t\tmodifier = {{ trigger = {{ is_ai = yes {guard} }} add = {programs.numeric_literal(amount)} }}\n"
                )
    if minimum < Decimal(str(scalar.lower)) or maximum > Decimal(str(scalar.upper)):
        raise ValueError("事件AIWeight最终限幅会生效，未证原生clamp语法")
    if new_policy:
        chunks.append("\t\t}\n")
    chunks.append(f"\t\t# SITAI END event:{program.option}\n\t\t")
    return "".join(chunks)


def _close_offset(text: str, line: int, key: str = "ai_chance") -> int:
    tokens = tokenize(text)
    matches = [
        i for i, t in enumerate(tokens) if t.kind == ATOM and t.value == key and t.line == line
    ]
    if len(matches) != 1:
        raise ValueError("事件精确权重行定位不唯一")
    start = matches[0]
    if tokens[start + 1].kind != OP or tokens[start + 2].kind != LBRACE:
        raise ValueError("事件权重不是显式块")
    depth = 0
    starts = [0]
    for fragment in text.splitlines(keepends=True):
        starts.append(starts[-1] + len(fragment))
    for token in tokens[start + 2 :]:
        depth += token.kind == LBRACE
        depth -= token.kind == RBRACE
        if depth == 0:
            return starts[token.line - 1] + token.col - 1
    raise ValueError("事件权重块未闭合")


def patch(
    inputs: Mapping[str, str],
    *,
    enabled_domains: frozenset[str] = frozenset({DOMAIN}),
    enabled_families: frozenset[str] = FAMILIES,
    consumer_programs: tuple[EventProgram, ...] | None = None,
) -> dict[str, str]:
    verify_inputs(inputs)
    if DOMAIN not in enabled_domains:
        return {}
    if not enabled_families <= FAMILIES:
        raise ValueError("事件政策family开关含未知身份")
    selected = compile_programs() if consumer_programs is None else consumer_programs
    if {row.option: row for row in selected} != {
        row.option: row for row in compile_programs()
    } or len(selected) != len(POLICIES):
        raise ValueError("事件选项程序集合缺失、重复或漂移")
    selected = tuple(program for program in selected if program.identity.family in enabled_families)
    result = {}
    for source in sorted({program.source for program in selected}):
        text = inputs[source]
        parsed = parse_text(text).root
        insertions = []
        for program in selected:
            if program.source != source:
                continue
            event = _block(parsed, program.event)
            options = _options(event)
            if program.identity.explicit:
                option = next(
                    row for row in event.all("option") if row.value is options[program.option]
                )
                insertions.append((_close_offset(text, option.line, "option"), render(program)))
            else:
                chance = options[program.option].all("ai_chance")[0]
                insertions.append((_close_offset(text, chance.line), render(program)))
        for offset, suffix in sorted(insertions, reverse=True):
            text = text[:offset] + suffix + text[offset:]
        result[source] = text
    return result


def consumer_catalog() -> dict[str, dict[str, Any]]:
    inputs = frozen_inputs()
    event = _block(parse_text(inputs[SOURCE]).root, EVENT)
    options = _options(event)
    hook_lines = inputs[ON_ACTIONS].splitlines()
    root_line = (
        next(
            i + 1
            for i, line in enumerate(hook_lines)
            if line.strip() == "on_law_checkpoint_debate = {"
        )
        - 2
    )
    catalog = {
        name: {
            "source": SOURCE,
            "definition": EVENT,
            "field": f"option[{name}].ai_chance",
            "selector": {"event": EVENT, "option_name": name},
            "native_root": "country",
            "actor": "root",
            "target_scope": "scope:anti_public_healthcare_ig=interest_group",
            "native_unit": "event_option_weight",
            "operation": "add",
            "placement": "after_existing_aiweight_modifiers",
            "scope_evidence": [
                f"{ON_ACTIONS}:{root_line}",
                f"{ON_ACTIONS}:4712",
                f"{SOURCE}:403",
                f"{SOURCE}:{options[name].all('ai_chance')[0].line}",
            ],
            "source_line": options[name].all("ai_chance")[0].line,
            "auxiliary_entity": "scope:anti_public_healthcare_ig; saved by this event immediate random_interest_group",
            "unknown_policy": "need_unknown=local_exit; opponent_missing=local_exit; clout_unknown_with_proven_entity=cost",
            "default_weight": "unsupported_not_consumed",
            "source_sha256": load()["sources"][SOURCE],
        }
        for name in OPTIONS
    }
    plague_event = _block(parse_text(inputs[PLAGUE]).root, PLAGUE_EVENT)
    plague_options = _options(plague_event)
    for name in PLAGUE_OPTIONS:
        line = next(
            row.line for row in plague_event.all("option") if row.value is plague_options[name]
        )
        catalog[name] = {
            "source": PLAGUE,
            "definition": PLAGUE_EVENT,
            "field": f"option[{name}].ai_chance",
            "selector": {"event": PLAGUE_EVENT, "option_name": name},
            "native_root": "country",
            "actor": "root",
            "native_unit": "event_option_weight",
            "target_scope": "none",
            "operation": "add",
            "placement": "new_explicit_complete_three_option_ai_policy",
            "scope_evidence": [
                f"{PLAGUE_DECISION}:1",
                f"{PLAGUE_DECISION}:25",
                f"{PLAGUE}:365",
                f"{PLAGUE}:{line}",
            ],
            "source_line": line,
            "auxiliary_entity": "none; actual owned-state aggregate observations",
            "unknown_policy": "health_unknown=local_exit; restriction_unknown=local_exit; financing_unknown=retain_cost; response_flags_independent",
            "default_weight": "unknown_not_inferred; intentional_new_explicit_ai_policy",
            "source_sha256": load()["sources"][PLAGUE],
        }
    disaster_root = parse_text(inputs[DISASTERS]).root
    for name in DISASTER_OPTIONS:
        identity = POLICIES[name]
        parent = _block(disaster_root, identity.event)
        option = _options(parent)[name]
        line = next(row.line for row in parent.all("option") if row.value is option)
        index = DISASTER_EVENTS.index(identity.event)
        size = "large" if index in {2, 3, 7} else "medium" if index in {0, 1} else "small"
        catalog[name] = {
            "source": DISASTERS,
            "definition": identity.event,
            "field": f"option[{name}].ai_chance",
            "selector": {"event": identity.event, "option_name": name},
            "native_root": "country",
            "actor": "root",
            "target_scope": "none",
            "native_unit": "event_option_weight",
            "operation": "add",
            "placement": "new_explicit_complete_paired_ai_policy",
            "scope_evidence": [
                f"{ON_ACTIONS}:1580",
                f"{ON_ACTIONS}:1840",
                f"{YEARLY}:{98 + index}",
                f"{DISASTERS}:{line}",
            ],
            "source_line": line,
            "auxiliary_entity": f"scope:{identity.saved_state}=state; exact event immediate random_scope_state",
            "unknown_policy": "saved_exposure_unknown=pair_neutral; farm_qualification_unknown=pair_neutral; financing_unknown=retain_declared_recurring_cost",
            "default_weight": "unknown_not_inferred; intentional_new_explicit_ai_policy",
            "cost_semantics": {
                "kind": "country_expenses_add",
                "modifier_value": 1,
                "gdp_multiplier": "money_amount_multiplier_" + size,
                "duration_days": 1825 if size == "large" else 913,
                "applies_to": identity.event + ".b",
            },
            "source_sha256": load()["sources"][DISASTERS],
        }
    sol_event = _block(parse_text(inputs[SOL]).root, SOL_EVENT)
    sol_options = _options(sol_event)
    for name in SOL_OPTIONS:
        line = sol_options[name].all("ai_chance")[0].line
        catalog[name] = {
            "source": SOL,
            "definition": SOL_EVENT,
            "field": f"option[{name}].ai_chance",
            "selector": {"event": SOL_EVENT, "option_name": name},
            "native_root": "country",
            "actor": "root",
            "target_scope": "none",
            "native_unit": "event_option_weight",
            "operation": "add",
            "placement": "after_complete_native_aiweight",
            "scope_evidence": [
                f"{SOL_JOURNAL_GROUP}:108",
                f"{SOL_JOURNAL_DOC}:334",
                f"{SOL_JOURNAL}:78",
                f"{SOL}:622",
                f"{SOL}:{line}",
            ],
            "source_line": line,
            "auxiliary_entity": "scope:slums_state=state; exact event immediate random_scope_state capital; require current owner=ROOT",
            "unknown_policy": "saved_state_missing_or_owner_or_population_unknown=state_benefits_exit_country_cost_retained; high_exposure_unknown=base_welfare_only; financing_unknown=retain_declared_recurring_cost",
            "default_weight": "native_base_1_plus_contextual_radicalization_10_preserved; paired_ai_baseline_50_added",
            "benefit_semantics": {
                "relief_option": SOL_OPTIONS[0],
                "lower_strata_standard_of_living_add": 1,
                "relief_duration_days": 1825,
                "rejection_option": SOL_OPTIONS[1],
                "rejection_radical_strata": "lower",
                "rejection_radical_operand": "medium_radicals=0.05",
                "high_exposure": "saved_state_total_population>=100000; bounded_proxy_not_lower_strata_count",
            },
            "cost_semantics": {
                "kind": "country_expenses_add",
                "modifier_value": 1,
                "gdp_multiplier": "money_amount_multiplier_small",
                "duration_days": 1825,
                "applies_to": SOL_OPTIONS[0],
            },
            "source_sha256": load()["sources"][SOL],
        }
    catalog.update(hokkaido_catalog(inputs))
    return catalog


def verify_hokkaido_inputs(inputs: Mapping[str, str]) -> None:
    """Pin all complete caller/effect/query/PM sources before reading their AST."""
    roots = _source_roots(inputs, HOKKAIDO_SOURCES)
    _scalar(
        _block(
            roots["common/journal_entry_groups/00_journal_entries.txt"],
            "je_group_historical_content",
        ),
        "context",
        "country",
    )
    journal = _block(roots["common/journal_entries/07_hokkaido.txt"], "je_taming_the_north")
    _scalar(journal, "group", "je_group_historical_content")
    buttons = [
        row.value.unquoted
        for row in journal.all("scripted_button")
        if isinstance(row.value, Scalar)
    ]
    if "button_je_taming_the_north_agriculture_potentials" not in buttons:
        raise ValueError("北海道JE调用按钮漂移")
    button = _block(
        roots["common/scripted_buttons/07_japan_buttons.txt"],
        "button_je_taming_the_north_agriculture_potentials",
    )
    _scalar(_block(_block(button, "effect"), "trigger_event"), "id", HOKKAIDO_EVENT)
    event = _block(roots[HOKKAIDO], HOKKAIDO_EVENT)
    _scalar(event, "type", "country_event")
    _scalar(event, "placement", "scope:hokkaido_state_scope")
    state = _block(_block(_block(event, "immediate"), "s:STATE_HOKKAIDO"), "random_scope_state")
    _scalar(_block(state, "limit"), "owner", "root")
    _scalar(state, "save_scope_as", "hokkaido_state_scope")
    _scalar(_block(state, "set_variable"), "name", "optimization_counter_var")
    _scalar(_block(state, "set_variable"), "value", "0")
    options = _options(event)
    if tuple(options) != HOKKAIDO_OPTIONS:
        raise ValueError("北海道完整五选项漂移")
    optimize = _block(_block(options[HOKKAIDO_OPTIONS[0]], "scope:hokkaido_state_scope"), "if")
    _scalar(_block(optimize, "limit"), "var:optimization_counter_var", "0")
    _scalar(_block(optimize, "add_modifier"), "multiplier", "0.5")
    rice = _block(options[HOKKAIDO_OPTIONS[1]], "scope:hokkaido_state_scope")
    replace = _block(rice, "if")
    _scalar(_block(replace, "limit"), "has_building", "building_wheat_farm")
    _scalar(replace, "remove_building", "building_wheat_farm")
    _scalar(_block(replace, "create_building"), "building", "building_rice_farm")
    _scalar(_block(replace, "create_building"), "level", "3")
    for suffix, potential in (
        ("c", "dye_plantation"),
        ("e", "opium_plantation"),
        ("g", "vineyard"),
    ):
        _scalar(
            _block(options[HOKKAIDO_EVENT + "." + suffix], "s:STATE_HOKKAIDO"),
            "add_resource_potential",
            "building_" + potential,
        )
    for name, base in zip(HOKKAIDO_OPTIONS, (10, 70, 5, 10, 10), strict=True):
        option = options[name]
        _scalar(_block(option, "ai_chance"), "base", str(base))
        fee = _block(option, "add_modifier")
        _scalar(fee, "name", "modifier_introducing_new_crops")
        _scalar(fee, "days", "normal_modifier_time")
        _scalar(
            fee,
            "multiplier",
            "money_amount_multiplier_" + ("large" if name.endswith(".a") else "medium"),
        )
    values = roots[EVENT_VALUES]
    _scalar(values, "normal_modifier_time", "1825")
    for kind, divisor, coefficient, rounding in (
        ("medium", "100000", "0.25", "100"),
        ("large", "1000000", "0.5", "1000"),
    ):
        if _shape(_block(values, "money_amount_multiplier_" + kind)) != (
            ("value", "=", "root.gdp"),
            ("divide", "=", divisor),
            ("multiply", "=", coefficient),
            ("round", "=", "yes"),
            ("multiply", "=", rounding),
            ("min", "=", "100"),
        ):
            raise ValueError("北海道实际取整费用AST漂移")
    modifiers = roots["common/static_modifiers/00_ep2_02_modifiers.txt"]
    _scalar(_block(modifiers, "modifier_introducing_new_crops"), "country_expenses_add", "1")
    for group in ("agriculture", "plantations"):
        _scalar(
            _block(modifiers, "modifier_opimizing_existing_variants"),
            "building_group_bg_" + group + "_throughput_add",
            "0.04",
        )
    # Actual group ancestry is authoritative. Scripted is_farm_building includes
    # ranching and is_plantation_building includes rubber extraction; neither
    # receives the native agriculture/plantations throughput modifier.
    group_root = roots["common/building_groups/00_building_groups.txt"]
    parents: dict[str, str | None] = {}
    for row in group_root.assignments():
        if isinstance(row.value, Block):
            parent = row.value.all("parent_group")
            if len(parent) > 1 or (parent and not isinstance(parent[0].value, Scalar)):
                raise ValueError("北海道建筑组父关系不唯一")
            parent_value = parent[0].value if parent else None
            if parent_value is not None and not isinstance(parent_value, Scalar):
                raise ValueError("北海道建筑组父关系必须为标量")
            parents[row.key] = parent_value.unquoted if parent_value is not None else None
    affected: set[str] = set()
    for group in parents:
        chain: set[str] = set()
        current: str | None = group
        while current is not None:
            if current in chain or current not in parents:
                raise ValueError("北海道建筑组父关系循环或缺失")
            chain.add(current)
            current = parents[current]
        if chain & {"bg_agriculture", "bg_plantations"}:
            affected.add(group)
    if affected != set(HOKKAIDO_CROP_GROUPS):
        raise ValueError("北海道真实农业/种植园建筑组闭包漂移")
    _scalar(
        _block(roots["common/buildings/02_agro.txt"], "building_livestock_ranch"),
        "building_group",
        "bg_ranching",
    )
    _scalar(
        _block(roots["common/buildings/09_misc_resource.txt"], "building_rubber_plantation"),
        "building_group",
        "bg_rubber",
    )
    australia = _block(
        _block(
            _block(_block(roots["events/australia_events.txt"], "emu_war.1"), "trigger"),
            "any_scope_state",
        ),
        "any_scope_building",
    )
    group_queries = _block(australia, "OR").all("is_building_group")
    if [row.value.unquoted for row in group_queries if isinstance(row.value, Scalar)] != [
        "bg_agriculture",
        "bg_ranching",
        "bg_plantations",
    ]:
        raise ValueError("北海道建筑组查询原版同形证据漂移")


HOKKAIDO_QUERY_PARAMETER = "event_hokkaido_query"
HOKKAIDO_CROP_GROUPS = (
    "bg_agriculture",
    "bg_staple_crops",
    "bg_subsistence_agriculture",
    "bg_plantations",
)
_HOKKAIDO_GROUP_QUERY = (
    "OR = { " + " ".join("is_building_group = " + group for group in HOKKAIDO_CROP_GROUPS) + " }"
)
HOKKAIDO_QUERIES = {
    "optimization_zero": "has_variable = optimization_counter_var var:optimization_counter_var = 0",
    "crops": "any_scope_building = { " + _HOKKAIDO_GROUP_QUERY + " occupancy >= 0.1 }",
    "crops_high": "any_scope_building = { " + _HOKKAIDO_GROUP_QUERY + " occupancy >= 0.5 }",
    "wheat": "has_building = building_wheat_farm",
    "wheat_absent": "NOT = { has_building = building_wheat_farm }",
    "wheat_large": "any_scope_building = { is_building_type = building_wheat_farm level > 3 }",
    "wheat_operating": "any_scope_building = { is_building_type = building_wheat_farm occupancy >= 0.5 }",
    "finance_large": "in_default = no net_fixed_income > money_amount_multiplier_large",
    "finance_medium": "in_default = no net_fixed_income > money_amount_multiplier_medium",
}
for _good in ("grain", "dye", "opium", "wine"):
    HOKKAIDO_QUERIES[_good + "_demand"] = (
        f"market = {{ exists = mg:{_good} mg:{_good} = {{ market_goods_delta < 0 }} }}"
    )
    HOKKAIDO_QUERIES[_good + "_acute"] = (
        f"market = {{ exists = mg:{_good} mg:{_good} = {{ market_goods_pricier > 0.25 }} }}"
    )


@dataclass(frozen=True, slots=True)
class HokkaidoQuery:
    observation: str


@dataclass(frozen=True, slots=True)
class CompiledHokkaidoQuery:
    expression: str
    source_hashes: tuple[tuple[str, str], ...]
    actor: str
    local_collections: tuple[str, ...]
    references: tuple[str, ...] = (
        "common/scripted_buttons/scripted_buttons.md:19",
        "common/scripted_buttons/07_japan_buttons.txt:414",
        "common/journal_entries/07_hokkaido.txt:9",
        f"{HOKKAIDO}:477",
    )
    kind: str = "boolean"
    world_scans: int = 0
    runtime_cost: str = (
        "bounded exact saved-state buildings and actor market observations; not constant time"
    )
    unknown_policy: str = (
        "true_requires_known_witness; complete_false=false; incomplete_without_witness=unknown"
    )


def hokkaido_query_from_reader(engine: str, parameters: Mapping[str, str]) -> HokkaidoQuery:
    if engine != "hokkaido_observation" or set(parameters) != {HOKKAIDO_QUERY_PARAMETER}:
        raise ValueError("北海道查询接口身份漂移")
    query = HokkaidoQuery(parameters[HOKKAIDO_QUERY_PARAMETER])
    render_hokkaido_query(query)
    return query


def render_hokkaido_query(query: HokkaidoQuery) -> str:
    if type(query) is not HokkaidoQuery or query.observation not in HOKKAIDO_QUERIES:
        raise ValueError("北海道查询必须为精确固定有界事实")
    return HOKKAIDO_QUERIES[query.observation]


def required_hokkaido_query_sources(query: HokkaidoQuery) -> tuple[str, ...]:
    render_hokkaido_query(query)
    return tuple(sorted(HOKKAIDO_SOURCES))


def compile_hokkaido_query(
    query: HokkaidoQuery, inputs: Mapping[str, str]
) -> CompiledHokkaidoQuery:
    expression = render_hokkaido_query(query)
    verify_hokkaido_inputs(inputs)
    observation = query.observation
    actor = (
        "country"
        if observation.startswith("finance_") or observation.endswith(("_demand", "_acute"))
        else "state"
    )
    collections = (
        ("saved_state_buildings",)
        if observation in {"crops", "crops_high", "wheat_large", "wheat_operating"}
        else ()
    )
    unknown = (
        "complete_known_wheat_absence=true; known_wheat_witness=false; incomplete_without_witness=unknown; never_negate_unknown_to_true"
        if observation == "wheat_absent"
        else "true_requires_known_witness; complete_false=false; incomplete_without_witness=unknown"
    )
    return CompiledHokkaidoQuery(
        expression,
        tuple((name, load()["sources"][name]) for name in sorted(HOKKAIDO_SOURCES)),
        actor,
        collections,
        unknown_policy=unknown,
    )


def hokkaido_readers(option: str) -> tuple[Reader, ...]:
    from pdx.decision_rules import Reader  # noqa: PLC0415

    suffix = option.rsplit(".", 1)[-1]
    if option not in HOKKAIDO_OPTIONS:
        raise ValueError("北海道选项身份未知")
    state = (
        ("optimization_zero", "crops", "crops_high")
        if suffix == "a"
        else ("wheat", "wheat_absent", "wheat_large", "wheat_operating")
        if suffix == "b"
        else ()
    )
    country: tuple[str, ...] = ("finance_large" if suffix == "a" else "finance_medium",)
    if suffix != "a":
        good = {"b": "grain", "c": "dye", "e": "opium", "g": "wine"}[suffix]
        country += (good + "_demand", good + "_acute")
    readers = [
        Reader(
            "hokkaido_exists",
            "exists",
            "root",
            "boolean",
            "boolean",
            argument="scope:hokkaido_state_scope",
        ),
        Reader(
            "hokkaido_owned", "owner", "hokkaido_state_scope", "boolean", "boolean", argument="root"
        ),
    ]
    readers.extend(
        Reader(
            "hokkaido_" + key,
            "hokkaido_observation",
            "hokkaido_state_scope" if key in state else "root",
            "boolean",
            "boolean",
            parameters=((HOKKAIDO_QUERY_PARAMETER, key),),
        )
        for key in (*state, *country)
    )
    return tuple(readers)


def validate_hokkaido_reader(
    reader: Reader,
    source: str | None,
    field: tuple[str, ...] | None,
    context: EvaluationContext | None,
    *,
    actor_path: tuple[str, ...] = (),
    native_root: str = "country",
) -> str:
    """Authorize the complete reader only for its exact event option and proven objects."""
    program = next(
        (
            item
            for item in compile_programs()
            if item.identity.family == "hokkaido"
            and item.source == source
            and item.field_path == field
        ),
        None,
    )
    if (
        program is None
        or native_root != "country"
        or actor_path
        or context != program.evaluation_context()
        or reader not in program.readers()
    ):
        raise ValueError("北海道读取器只授权精确选项、完整签名与已证明国家/保存州上下文")
    return "country" if reader.scope == "root" else "state"


def _compile_hokkaido_programs() -> tuple[EventProgram, ...]:
    from pdx.situated import programs  # noqa: PLC0415

    p = load()["hokkaido_policy"]
    result = []
    for option in HOKKAIDO_OPTIONS:
        suffix = option.rsplit(".", 1)[-1]
        groups = [
            programs.ScalarGroup(
                "independent_actual_five_year_country_expense",
                (
                    programs.ScalarTerm(
                        "hokkaido_country_cost",
                        "hokkaido_" + suffix + "_cost",
                        -p["recurring_cost"],
                        (
                            programs.ScalarEffect(
                                "hokkaido_finance_" + ("large" if suffix == "a" else "medium"),
                                p["covered_cost_refund"],
                            ),
                        ),
                    ),
                ),
            )
        ]
        if suffix == "a":
            groups.append(
                programs.ScalarGroup(
                    "actual_current_operating_crops_two_percent_throughput",
                    (
                        programs.ScalarTerm(
                            "hokkaido_crops",
                            "hokkaido_a_crops",
                            p["throughput"],
                            (programs.ScalarEffect("hokkaido_crops_high", p["high_operation"]),),
                        ),
                    ),
                )
            )
        else:
            good = {"b": "grain", "c": "dye", "e": "opium", "g": "wine"}[suffix]
            guard = "hokkaido_" + good + "_opportunity"
            groups.append(
                programs.ScalarGroup(
                    "potential_only_actual_market_need",
                    (
                        programs.ScalarTerm(
                            guard,
                            "hokkaido_" + suffix + "_potential",
                            p["potential_demand"],
                            (
                                programs.ScalarEffect(
                                    "hokkaido_" + good + "_acute", p["acute_demand"]
                                ),
                            ),
                        ),
                    ),
                )
            )
            if suffix == "b":
                replacement = programs.ScalarTerm(
                    "hokkaido_wheat",
                    "hokkaido_b_replacement",
                    -p["wheat_replacement"],
                    (
                        programs.ScalarEffect("hokkaido_wheat_large", -p["wheat_large"]),
                        programs.ScalarEffect("hokkaido_wheat_operating", -p["wheat_operating"]),
                    ),
                )
                groups.append(
                    programs.ScalarGroup(
                        "destroy_all_wheat_replace_exactly_three_rice", (replacement,)
                    )
                )
        result.append(
            EventProgram(
                option,
                programs.ScalarProgram(
                    "event_hokkaido_" + suffix,
                    "add",
                    0,
                    -34 if suffix == "b" else -2,
                    4,
                    tuple(groups),
                ),
            )
        )
    return tuple(result)


def _hokkaido_guards(values: Mapping[str, object], program: EventProgram) -> dict[str, bool]:
    core = (
        program.identity.family == "hokkaido"
        and values.get("hokkaido_exists") is True
        and values.get("hokkaido_owned") is True
    )
    result = {"hokkaido_country_cost": program.identity.family == "hokkaido"}
    for size in ("medium", "large"):
        result["hokkaido_finance_" + size] = values.get("hokkaido_finance_" + size) is True
    crops = (
        core
        and values.get("hokkaido_optimization_zero") is True
        and values.get("hokkaido_crops") is True
    )
    result["hokkaido_crops"] = crops
    result["hokkaido_crops_high"] = crops and values.get("hokkaido_crops_high") is True
    wheat = core and values.get("hokkaido_wheat") is True
    for key in ("wheat", "wheat_large", "wheat_operating"):
        result["hokkaido_" + key] = wheat and (
            key == "wheat" or values.get("hokkaido_" + key) is True
        )
    for good in ("grain", "dye", "opium", "wine"):
        result["hokkaido_" + good + "_opportunity"] = (
            core
            and values.get("hokkaido_" + good + "_demand") is True
            and (good != "grain" or values.get("hokkaido_wheat_absent") is True)
        )
        result["hokkaido_" + good + "_acute"] = values.get("hokkaido_" + good + "_acute") is True
    return result


_hokkaido_core = "exists = scope:hokkaido_state_scope scope:hokkaido_state_scope = { owner = root }"
GUARDS["hokkaido_country_cost"] = "is_ai = yes"
for _key, _expression in HOKKAIDO_QUERIES.items():
    if _key.startswith("finance_") or _key.endswith(("_demand", "_acute")):
        GUARDS["hokkaido_" + _key] = _expression
    else:
        GUARDS["hokkaido_" + _key] = (
            _hokkaido_core + " scope:hokkaido_state_scope = { " + _expression + " }"
        )
GUARDS["hokkaido_crops"] += (
    " scope:hokkaido_state_scope = { " + HOKKAIDO_QUERIES["optimization_zero"] + " }"
)
for _good in ("grain", "dye", "opium", "wine"):
    GUARDS["hokkaido_" + _good + "_opportunity"] = (
        _hokkaido_core + " " + HOKKAIDO_QUERIES[_good + "_demand"]
    )
    if _good == "grain":
        GUARDS["hokkaido_grain_opportunity"] += (
            " scope:hokkaido_state_scope = { " + HOKKAIDO_QUERIES["wheat_absent"] + " }"
        )


def hokkaido_catalog(inputs: Mapping[str, str]) -> dict[str, dict[str, Any]]:
    event = _block(parse_text(inputs[HOKKAIDO]).root, HOKKAIDO_EVENT)
    return {
        name: {
            "source": HOKKAIDO,
            "definition": HOKKAIDO_EVENT,
            "field": f"option[{name}].ai_chance",
            "selector": {"event": HOKKAIDO_EVENT, "option_name": name},
            "native_root": "country",
            "actor": "root",
            "target_scope": "scope:hokkaido_state_scope=state; exists and owner=root per state benefit",
            "native_unit": "event_option_weight",
            "operation": "add",
            "placement": "after_existing_aiweight_modifiers",
            "source_line": _options(event)[name].all("ai_chance")[0].line,
            "scope_evidence": [
                "common/scripted_buttons/scripted_buttons.md:19",
                "common/scripted_buttons/07_japan_buttons.txt:414",
                f"{HOKKAIDO}:477",
            ],
            "default_weight": "known_native_base_preserved",
            "auxiliary_entity": "exact current saved Hokkaido owned state; not event placement inferred ROOT",
            "unknown_policy": "state_unknown=benefit_exit; auxiliary_unknown=lower_tier; finance_unknown=retain_independent_cost; wheat_business_profit_and_replacement_money=unknown_not_inferred",
            "cost_semantics": {
                "kind": "country_expenses_add",
                "duration_days": 1825,
                "multiplier": "money_amount_multiplier_"
                + ("large" if name.endswith(".a") else "medium"),
                "pressure": "bounded_preference_not_currency; actual_rounded_macro_against_net_fixed_income; no_fixed_large_medium_ratio",
            },
            "source_sha256": load()["sources"][HOKKAIDO],
        }
        for name in HOKKAIDO_OPTIONS
    }
