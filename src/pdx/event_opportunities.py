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
FROZEN = config.REPO / "research/vanilla-ai/1.14.5/event-opportunities.json"
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
PLAGUE_EVENT = "plague.5"
PLAGUE_OPTIONS = ("plague.5.a", "plague.5.b", "plague.5.c")
QUERY_PARAMETER = "event_plague_query"
EVENT = "healthcare_laws.5"
OPTIONS = ("healthcare_laws.5.a", "healthcare_laws.5.b")
DOMAIN = "political"


def load() -> dict[str, Any]:
    data = tomllib.loads(PARAMETERS.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "sources", "tuning", "plague_policy"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or set(data["sources"])
        != {
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
        }
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


def verify_inputs(inputs: Mapping[str, str]) -> None:
    roots = {}
    for name, digest in load()["sources"].items():
        text = inputs.get(name)
        if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != digest:
            raise ValueError(f"事件完整原版来源漂移：{name}")
        parsed = parse_text(text)
        if parsed.errors:
            raise ValueError(f"事件完整原版解析失败：{name}")
        roots[name] = parsed.root
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
    _scalar(
        _block(_block(roots[HEALTH], "law_public_health_insurance"), "institution_modifier"),
        "state_standard_of_living_add",
        "0.5",
    )


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
class EventProgram:
    option: str
    scalar: programs.ScalarProgram

    @property
    def source(self) -> str:
        return PLAGUE if self.option in PLAGUE_OPTIONS else SOURCE

    @property
    def event(self) -> str:
        return PLAGUE_EVENT if self.option in PLAGUE_OPTIONS else EVENT

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

    def evaluation_context(self) -> EvaluationContext:
        from pdx.situated.decision_ir import ContextBinding, EvaluationContext  # noqa: PLC0415

        if self.option in PLAGUE_OPTIONS:
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
        if self.option in PLAGUE_OPTIONS:
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
        return programs.evaluate_scalar(self.scalar, _guards(values)) if is_ai and enabled else 0.0

    def readers(self) -> tuple[Reader, ...]:
        from pdx.decision_rules import Reader  # noqa: PLC0415

        if self.option in PLAGUE_OPTIONS:
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
            "source_hashes": load()["sources"],
            "policy": "explicit_new_three_option_policy_native_default_unknown"
            if self.option in PLAGUE_OPTIONS
            else "additive_to_explicit_native_weight",
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
    return (*result, *_compile_plague_programs())


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


def _valid_number(value: object, minimum: float, maximum: float = math.inf) -> bool:
    if type(value) not in {int, float}:
        return False
    try:
        return math.isfinite(cast("float", value)) and minimum <= cast("float", value) <= maximum
    except OverflowError:
        return False


def _guards(values: Mapping[str, object]) -> dict[str, bool]:
    sol, clout = values.get("average_sol"), values.get("opponent_clout")
    exists = values.get("opponent_exists") is True
    infected = values.get("plague_infected")
    return {
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


def evaluate(
    values: Mapping[str, object],
    *,
    is_ai: bool,
    enabled_domains: frozenset[str] = frozenset({DOMAIN}),
    consumer_programs: tuple[EventProgram, ...] | None = None,
) -> dict[str, float]:
    if type(is_ai) is not bool:
        raise ValueError("事件AI身份必须为已知布尔")
    if not is_ai or DOMAIN not in enabled_domains:
        return {}
    selected = compile_programs() if consumer_programs is None else consumer_programs
    return {row.option: row.evaluate(values, is_ai=is_ai) for row in selected}


GUARDS = {
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
    return tuple(sorted(load()["sources"]))


def compile_query(query: PlagueStateQuery, inputs: Mapping[str, str]) -> CompiledPlagueStateQuery:
    expression = render_query(query)
    verify_inputs(inputs)
    return CompiledPlagueStateQuery(
        expression,
        (f"{PLAGUE_DECISION}:3", f"{PLAGUE}:403", f"{PLAGUE}:480", f"{PLAGUE_MODIFIERS}:728"),
        tuple(sorted(load()["sources"].items())),
    )


def render(program: EventProgram) -> str:
    """Lower only proven linear AIWeight; reject a binding final clamp.

    Sum independent term extrema as a generation-time interval proof, rather
    than emit truth-table branches. Runtime growth is linear in terms.
    """
    from pdx.situated import programs  # noqa: PLC0415

    scalar = program.scalar
    new_policy = program.option in PLAGUE_OPTIONS
    if (
        scalar.operation != "add"
        or (scalar.neutral != 0 and not new_policy)
        or len(scalar.groups) > (4 if new_policy else 2)
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
    consumer_programs: tuple[EventProgram, ...] | None = None,
) -> dict[str, str]:
    verify_inputs(inputs)
    if DOMAIN not in enabled_domains:
        return {}
    selected = compile_programs() if consumer_programs is None else consumer_programs
    if {row.option: row for row in selected} != {
        row.option: row for row in compile_programs()
    } or len(selected) != len(OPTIONS) + len(PLAGUE_OPTIONS):
        raise ValueError("事件选项程序集合缺失、重复或漂移")
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
            if program.option in PLAGUE_OPTIONS:
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
    return catalog
