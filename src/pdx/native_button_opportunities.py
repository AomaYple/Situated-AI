"""Three exact country buttons: observed costs through the common rule algebra.

This module supplies rules and immutable native evidence, never a new scorer.
Hokkaido covers the commitment to start only; event_opportunities owns its five
subsequent option policies. Population is an entity anchor, never a solvency observation.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tomllib
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, cast

from . import config
from .model import Assignment, Block, Scalar
from .parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .decision_rules import Reader
    from .situated.decision_ir import EvaluationContext

PARAMETERS = config.REPO / "mod/decisions/native_button_opportunities.toml"
FROZEN = config.REPO / "research/vanilla-ai/1.15.0/native-button-opportunities.json"
FROZEN_SHA256 = "e96069841231c8382fca4c89d63cb258fa5195f86dbde474271fcf9cf043675a"
ACTOR_SOURCE = "common/decisions/west_america_expidition_decision.txt"
HELP = "common/scripted_buttons/scripted_buttons.md"
HAITI = "common/scripted_buttons/00_hispaniola_buttons.txt"
MIGRATION = "common/scripted_buttons/southamerica_migration_button.txt"
HOKKAIDO = "common/scripted_buttons/07_japan_buttons.txt"
HAITI_JE = "common/journal_entries/01_hispaniola.txt"
MIGRATION_JE = "common/journal_entries/02_south_america_migration.txt"
HOKKAIDO_JE = "common/journal_entries/07_hokkaido.txt"
HAITI_MOD = "common/static_modifiers/agitators_2_modifiers.txt"
MIGRATION_MOD = "common/static_modifiers/brazil_1_modifiers.txt"
HOKKAIDO_MOD = "common/static_modifiers/00_ep2_02_modifiers.txt"
MIGRATION_EVENT = "events/brazil/south_america_migration.txt"
HOKKAIDO_EVENT = "events/japan_events/ep2_hokkaido_events.txt"
VALUES = "common/script_values/event_values.txt"
EXPEL = "common/diplomatic_actions/01_expel_diplomats.txt"
ACTION_HELP = "common/diplomatic_actions/diplomatic_action.md"
AUTHORITY = "common/journal_entries/00_tutorial.txt"
FINANCE = "events/brazil/amazonas.txt"
POPULATION = "common/script_values/building_values.txt"
SOURCES = frozenset(
    {
        ACTOR_SOURCE,
        HELP,
        HAITI,
        MIGRATION,
        HOKKAIDO,
        HAITI_JE,
        MIGRATION_JE,
        HOKKAIDO_JE,
        HAITI_MOD,
        MIGRATION_MOD,
        HOKKAIDO_MOD,
        MIGRATION_EVENT,
        HOKKAIDO_EVENT,
        VALUES,
        EXPEL,
        ACTION_HELP,
        AUTHORITY,
        FINANCE,
        POPULATION,
    }
)


@dataclass(frozen=True, slots=True)
class ButtonSpec:
    source: str
    definition: str
    native_base: int
    callers: tuple[tuple[str, str], ...]
    obligation: str

    @property
    def field(self) -> str:
        return f"{self.definition}.ai_chance"


SPECS = (
    ButtonSpec(
        HAITI, "je_haitian_debt_payment_button", 50, ((HAITI_JE, "je_haitian_debt"),), "B01.4.2"
    ),
    ButtonSpec(
        MIGRATION,
        "southamerica_migration_button",
        50,
        tuple(
            (MIGRATION_JE, name)
            for name in (
                "je_south_america_migration",
                "je_central_america_migration",
                "je_american_west_migration",
            )
        ),
        "B06.4.2",
    ),
    ButtonSpec(
        HOKKAIDO,
        "button_je_taming_the_north_agriculture_potentials",
        10,
        ((HOKKAIDO_JE, "je_taming_the_north"),),
        "B02.1.2",
    ),
)
RESERVES = "native_button_reserves"
INFLUENCE = "native_button_influence"
ANCHOR = "cost_country_population"
ACTOR = "native_button_actor_ai"
READERS: dict[str, dict[str, Any]] = {
    ACTOR: {"engine": "is_ai", "scope": "root", "unit": "boolean", "kind": "boolean"},
    RESERVES: {
        "engine": "gold_reserves",
        "scope": "root",
        "unit": "currency",
        "kind": "number",
        "minimum": 0,
    },
    "authority": {
        "engine": "authority",
        "scope": "root",
        "unit": "capacity_balance",
        "kind": "number",
    },
    INFLUENCE: {
        "engine": "influence",
        "scope": "root",
        "unit": "capacity_balance",
        "kind": "number",
    },
    "default": {"engine": "in_default", "scope": "root", "unit": "boolean", "kind": "boolean"},
    ANCHOR: {
        "engine": "total_population",
        "scope": "root",
        "unit": "persons",
        "kind": "number",
        "minimum": 0,
    },
}
_TUNING = {
    "haiti_thin_buffer",
    "haiti_very_thin_buffer",
    "migration_authority_thin",
    "migration_authority_short",
    "migration_influence_thin",
    "migration_influence_short",
    "hokkaido_commitment",
    "hokkaido_financing_pressure",
}


def load() -> dict[str, Any]:
    data = tomllib.loads(PARAMETERS.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "sources", "tuning"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or set(data["sources"]) != SOURCES
        or any(
            not isinstance(v, str) or re.fullmatch(r"[a-f0-9]{64}", v) is None
            for v in data["sources"].values()
        )
        or set(data["tuning"]) != _TUNING
        or any(
            type(v) not in {int, float} or not math.isfinite(v) or not 0.8 <= v < 1
            for v in data["tuning"].values()
        )
    ):
        raise ValueError("原生按钮schema/完整来源/正成本倍率边界无效")
    t = data["tuning"]
    if any(
        t[strong] >= t[weak]
        for strong, weak in (
            ("haiti_very_thin_buffer", "haiti_thin_buffer"),
            ("migration_authority_short", "migration_authority_thin"),
            ("migration_influence_short", "migration_influence_thin"),
            ("hokkaido_financing_pressure", "hokkaido_commitment"),
        )
    ):
        raise ValueError("原生按钮同因风险分档强弱边界无效")
    return data


def _shape(node: Assignment | Block | Scalar) -> list[Any]:
    if isinstance(node, Scalar):
        return ["scalar", node.text]
    if isinstance(node, Assignment):
        if not isinstance(node.value, (Block, Scalar)):
            raise ValueError("原生按钮原版AST缺少值")
        return ["assignment", node.key, node.op, node.prefix, _shape(node.value)]
    return ["block", *(_shape(item) for item in node.items)]


def _block(parent: Block, key: str) -> Block:
    rows = parent.all(key)
    if len(rows) != 1 or rows[0].op != "=" or not isinstance(rows[0].value, Block):
        raise ValueError(f"原生按钮原版唯一块漂移：{key}")
    return rows[0].value


def _scalar(parent: Block, key: str, value: str, op: str = "=") -> None:
    rows = parent.all(key)
    if (
        len(rows) != 1
        or rows[0].op != op
        or not isinstance(rows[0].value, Scalar)
        or rows[0].value.unquoted != value
    ):
        raise ValueError(f"原生按钮原版实际标量漂移：{key}")


def _snapshot() -> dict[str, Any]:
    raw = FROZEN.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FROZEN_SHA256:
        raise ValueError("原生按钮冻结原版身份漂移")
    data = json.loads(raw)
    if (
        set(data)
        != {
            "schema",
            "evidence",
            "normalization",
            "source_hashes",
            "raw_source_hashes",
            "inputs",
            "contracts",
        }
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or data["evidence"] != "static_complete_native_sources_not_engine_execution"
        or data["normalization"] != "utf8_without_bom_lf_preserve_whitespace"
        or data["source_hashes"] != load()["sources"]
        or set(data["inputs"]) != SOURCES
        or set(data["raw_source_hashes"]) != SOURCES
    ):
        raise ValueError("原生按钮冻结完整来源合同无效")
    return cast("dict[str, Any]", data)


def verify_inputs(inputs: Mapping[str, str]) -> tuple[str, ...]:
    """Pin whole sources and exact actor/caller/effect/real-cost witnesses."""
    snapshot = _snapshot()
    roots = {}
    for source, digest in load()["sources"].items():
        text = inputs.get(source)
        if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != digest:
            raise ValueError(f"原生按钮完整原版来源漂移：{source}")
        if source in {HELP, ACTION_HELP}:
            continue
        parsed = parse_text(text, path=source)
        if parsed.errors:
            raise ValueError(f"原生按钮原版解析失败：{source}")
        roots[source] = parsed.root
    if "#Country scope\n          ai_chance" not in inputs[HELP]:
        raise ValueError("原生按钮country ROOT帮助证据漂移")
    if (
        "In the AI block, the AI country is always root and the other country always "
        "scope:target, regardless of who proposed the diplomatic action"
    ) not in inputs[ACTION_HELP]:
        raise ValueError("影响力getter原版AI actor ROOT文档漂移")
    for identity, expected in snapshot["contracts"].items():
        source, definition = identity.split("#", 1)
        if source not in roots or _shape(_block(roots[source], definition)) != expected:
            raise ValueError(f"原生按钮精确完整父结构漂移：{identity}")
    evidence = []
    for spec in SPECS:
        button = _block(roots[spec.source], spec.definition)
        _scalar(_block(button, "ai_chance"), "value", str(spec.native_base))
        if len(_block(button, "ai_chance").items) != 1:
            raise ValueError("原生按钮原版完整固定权重漂移")
        for source, caller in spec.callers:
            references = _block(roots[source], caller).all("scripted_button")
            matches = [
                r
                for r in references
                if isinstance(r.value, Scalar) and r.value.unquoted == spec.definition
            ]
            if len(matches) != 1:
                raise ValueError("原生按钮实际JE调用者漂移")
            evidence.append(f"{source}:{matches[0].line}")
        evidence.append(f"{spec.source}:{button.all('ai_chance')[0].line}")
    # Independent effects, not annotations or speculative benefit arithmetic.
    haiti = _block(roots[HAITI], SPECS[0].definition)
    _scalar(_block(haiti, "effect"), "add_treasury", "-500000")
    _scalar(_block(haiti, "possible"), "gold_reserves", "500000", ">=")
    for tier in range(1, 5):
        _scalar(
            _block(roots[HAITI_MOD], f"modifier_french_independence_payments_{tier}"),
            "country_expenses_add",
            str(500 * tier),
        )
    migration_cost = _block(roots[MIGRATION_MOD], "sa_migration_cost")
    _scalar(migration_cost, "country_influence_mult", "-0.25")
    _scalar(migration_cost, "country_authority_cost_add", "100")
    _scalar(roots[VALUES], "normal_modifier_time", "1825")
    _scalar(
        _block(roots[HOKKAIDO_MOD], "modifier_introducing_new_crops"), "country_expenses_add", "1"
    )
    options = _block(roots[HOKKAIDO_EVENT], "hokkaido_events.3").all("option")
    names = []
    for option in options:
        if not isinstance(option.value, Block):
            raise ValueError("北海道实际option缺少完整块")
        name = option.value.all("name")[0].value
        if not isinstance(name, Scalar):
            raise ValueError("北海道实际option身份漂移")
        names.append(name.unquoted)
        cost = _block(option.value, "add_modifier")
        _scalar(cost, "name", "modifier_introducing_new_crops")
        _scalar(cost, "days", "normal_modifier_time")
        _scalar(
            cost,
            "multiplier",
            "money_amount_multiplier_large"
            if name.unquoted == "hokkaido_events.3.a"
            else "money_amount_multiplier_medium",
        )
    if names != [f"hokkaido_events.3.{suffix}" for suffix in ("a", "b", "c", "e", "g")]:
        raise ValueError("北海道完整实际可选分支集合漂移")
    for macro in ("money_amount_multiplier_medium", "money_amount_multiplier_large"):
        _scalar(_block(roots[VALUES], macro), "min", "100")
    # influence must occur on the native AI actor, not inside target_country.
    expel = _block(_block(_block(roots[EXPEL], "expel_diplomats"), "ai"), "will_propose")
    branches = _block(expel, "OR").all("AND")
    influence_branches = cast("Block", branches[1].value).all("OR")
    if len(influence_branches) != 2 or not isinstance(influence_branches[1].value, Block):
        raise ValueError("影响力getter原版AI actor分支漂移")
    influence = influence_branches[1].value
    _scalar(influence, "influence", "200", "<")
    _scalar(_block(_block(roots[FINANCE], "amazonas.1"), "trigger"), "in_default", "no")
    for source, text, statement in (
        (HELP, inputs[HELP], "#Country scope"),
        (EXPEL, inputs[EXPEL], "influence < 200 # Not enough to damage relations normally"),
        (FINANCE, inputs[FINANCE], "in_default = no"),
        (POPULATION, inputs[POPULATION], "total_population > 0"),
        (AUTHORITY, inputs[AUTHORITY], "authority > 0"),
    ):
        lines = [i + 1 for i, line in enumerate(text.splitlines()) if line.strip() == statement]
        if len(lines) != 1:
            raise ValueError(f"原生按钮reader精确来源行漂移：{statement}")
        evidence.append(f"{source}:{lines[0]}")
    return tuple(evidence)


def frozen_inputs() -> dict[str, str]:
    inputs = _snapshot()["inputs"]
    verify_inputs(inputs)
    return cast("dict[str, str]", inputs)


def consumer_catalog() -> tuple[dict[str, Any], ...]:
    inputs = frozen_inputs()
    help_line = next(
        i + 1
        for i, line in enumerate(inputs[HELP].splitlines())
        if line.strip() == "#Country scope"
    )
    rows = []
    for spec in SPECS:
        button = _block(parse_text(inputs[spec.source]).root, spec.definition)
        rows.append(
            {
                "source": spec.source,
                "field": spec.field,
                "definition": spec.definition,
                "actor": "root",
                "actor_path": [],
                "target": "none",
                "native_root": "country",
                "native_unit": "relative_weight",
                "operation": "multiply",
                "vanilla_tail": "retain",
                "native_base": spec.native_base,
                "scope_source": HELP,
                "scope_evidence": HELP,
                "scope_evidence_line": help_line,
                "score_evidence_line": button.all("ai_chance")[0].line,
                "obligation": spec.obligation,
                "calibration": "bounded_design_assumption_not_affordability_or_expected_bill",
                "coverage": "start_commitment_only_not_five_options"
                if spec.source == HOKKAIDO
                else "exact_button_cost",
            }
        )
    return tuple(rows)


def evaluation_context(source: str, field: str) -> EvaluationContext:
    from .situated.decision_ir import ContextBinding, EvaluationContext  # noqa: PLC0415

    row = next(
        (r for r in consumer_catalog() if (r["source"], r["field"]) == (source, field)), None
    )
    if row is None:
        raise ValueError("原生按钮仅授权三个精确country ROOT消费者")
    line = row["scope_evidence_line"]
    return EvaluationContext(
        actor_scope=ContextBinding("root", "country", "actor", HELP, line),
        evidence=(
            f"{HELP}:{line}",
            f"{source}:{row['score_evidence_line']}",
            f"{source}:sha256={load()['sources'][source]}",
        ),
    )


def validate_reader(
    reader: Reader,
    source: str,
    field: str,
    *,
    actor_path: tuple[str, ...] = (),
    native_root: str = "country",
) -> None:
    """An exact optional integration guard; this does not alter shared permissions."""
    allowed = {
        SPECS[0].field: {RESERVES, ANCHOR},
        SPECS[1].field: {"authority", INFLUENCE, ANCHOR},
        SPECS[2].field: {"default", ANCHOR, ACTOR},
    }
    pairs = {(spec.source, spec.field) for spec in SPECS}
    if (
        (source, field) not in pairs
        or actor_path
        or native_root != "country"
        or reader.key not in allowed[field]
    ):
        raise ValueError("原生按钮reader越过精确ROOT消费者权限")
    actual = asdict(reader)
    expected = asdict(type(reader)(key=reader.key, **READERS[reader.key]))
    if actual != expected:
        raise ValueError("原生按钮reader完整身份漂移")


def derive(adapters: Mapping[str, Any]) -> dict[str, Any]:
    data = load()
    consumer_catalog()
    for key, expected in READERS.items():
        if key in adapters["readers"] and adapters["readers"][key] != expected:
            raise ValueError(f"原生按钮Reader完整身份冲突：{key}")
    # source, suffix, tuning, cause, observations, conservative pressure keys.
    definitions: tuple[tuple[int, str, str, list[tuple[str, str, int | bool]], list[str]], ...] = (
        (0, "haiti_thin_buffer", "haiti_cash_buffer", [(RESERVES, "<", 1000000)], []),
        (0, "haiti_very_thin_buffer", "haiti_cash_buffer", [(RESERVES, "<", 600000)], [RESERVES]),
        (
            1,
            "migration_authority_thin",
            "migration_authority_commitment",
            [("authority", "<", 200)],
            [],
        ),
        (
            1,
            "migration_authority_short",
            "migration_authority_commitment",
            [("authority", "<", 100)],
            ["authority"],
        ),
        (
            1,
            "migration_influence_thin",
            "migration_influence_commitment",
            [(INFLUENCE, "<", 200)],
            [],
        ),
        (
            1,
            "migration_influence_short",
            "migration_influence_commitment",
            [(INFLUENCE, "<", 0)],
            [INFLUENCE],
        ),
        (2, "hokkaido_commitment", "hokkaido_recurring_commitment", [(ACTOR, "=", True)], []),
        (
            2,
            "hokkaido_financing_pressure",
            "hokkaido_recurring_commitment",
            [("default", "=", True)],
            ["default"],
        ),
    )
    rules = []
    for offset, (index, tuning, cause, conditions, pressure) in enumerate(definitions):
        spec = SPECS[index]
        rule: dict[str, Any] = {
            "id": f"native_button_{tuning}",
            "source": spec.source,
            "field": spec.field,
            "domain": "political",
            "priority": 88200 + offset,
            "operation": "multiply",
            "value": data["tuning"][tuning],
            "semantic_role": "cost",
            "contribution_group": f"native_button_{cause}",
            "conditions": [
                {"fact": fact, "op": op, "value": value} for fact, op, value in conditions
            ],
            "why": (
                "真实500000即时付款后的薄现金缓冲；只评价当下风险，不预测500每周回本。"
                if index == 0
                else "五年权威固定100与影响力乘数-0.25是不同资源原因；余额只作有界压力，不算精确执行后余额。"
                if index == 1
                else "五个实际合法候选都具有五年正费用；启动承诺按有界财政压力分档，不假定已选medium/large或期望账单。"
            ),
            "counterexample": "仅影响精确按钮AI评分；保留原资格、实际效果、变量、原扫描、冷却与原尾零；玩家/关闭不变。人口仅实体锚，未知不假健康；已知成本不依赖人口，已知false成本退出并恢复。北海道五选项B02.1.3仍未实现。",
        }
        if pressure:
            rule.update(
                conservative_unknown_facts=pressure,
                unknown_cost_required_known_facts=[ANCHOR],
                unknown_cost_basis="实际一次现金或五年资源承诺已证；成本观察未知且本国实体锚已知时保留有限成本，不推定违约/资源亏空；二者都未知局部回原版。",
            )
        rules.append(rule)
    return {
        "sources": dict(data["sources"]),
        "readers": {k: dict(v) for k, v in READERS.items()},
        "rules": rules,
        "covered": [
            {"id": spec.definition, "source": spec.source, "field": spec.field} for spec in SPECS
        ],
    }
