"""Exact directed no-tariffs acceptance; ROOT is the country being checked.

Article inputs are optional until proven present. This bridge owns only the
inherent acceptance suffix, never proposal/input selection, eligibility,
ratification, execution or a treaty-wide contextual score.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tomllib
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, TypeGuard, cast

from . import config
from .lexer import ATOM, LBRACE, RBRACE, tokenize
from .model import Block, Scalar
from .parser import parse_text
from .situated import programs

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .decision_rules import Reader
    from .situated.decision_ir import EvaluationContext, WriterDecisionIR

PARAMETERS = config.REPO / "mod/decisions/treaty_acceptance_opportunities.toml"
FROZEN = config.REPO / "research/vanilla-ai/1.14.5/treaty-acceptance-opportunities.json"
SOURCE = "common/treaty_articles/21_no_tariffs.txt"
DOC = "common/treaty_articles/treaty_articles.md"
GOODS_TRANSFER = "common/treaty_articles/13_goods_transfer.txt"
MONEY_TRANSFER = "common/treaty_articles/05_transfer_money.txt"
INCOME = "common/journal_entries/06_portugal_politics.txt"
SOURCES = frozenset({SOURCE, DOC, GOODS_TRANSFER, MONEY_TRANSFER, INCOME})
DEFINITION = "no_tariffs"
FIELD = "no_tariffs.ai.inherent_accept_score"
DOMAIN = "diplomacy"
ACTION = "treaty_acceptance_no_tariffs"
INPUT_MARKET = "scope:article.input_market_goods(root)"


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
        or set(data["tuning"])
        != {"target_input_need", "source_deficit_cost", "source_default_cost"}
    ):
        raise ValueError("条约接受完整来源/schema/参数无效")
    tuning = data["tuning"]
    if (
        any(type(v) not in {int, float} or not math.isfinite(v) for v in tuning.values())
        or not 0 < tuning["target_input_need"] <= 8
        or not 0 < tuning["source_deficit_cost"] <= tuning["source_default_cost"] <= 12
    ):
        raise ValueError("条约接受倾向必须保持有限且有界")
    return data


def _block(parent: Block, key: str) -> Block:
    rows = parent.all(key)
    if len(rows) != 1 or rows[0].op != "=" or not isinstance(rows[0].value, Block):
        raise ValueError(f"条约接受原版唯一块漂移：{key}")
    return rows[0].value


def _scalar(parent: Block, key: str, value: str, op: str = "=") -> int:
    rows = parent.all(key)
    if (
        len(rows) != 1
        or rows[0].op != op
        or not isinstance(rows[0].value, Scalar)
        or rows[0].value.unquoted != value
    ):
        raise ValueError(f"条约接受原版标量漂移：{key}")
    return rows[0].line


def _shape(block: Block) -> tuple:
    result = []
    for row in block.assignments():
        if isinstance(row.value, Block):
            value: str | tuple = _shape(row.value)
        elif isinstance(row.value, Scalar):
            value = row.value.unquoted
        else:
            raise ValueError("条约接受原版AST缺值")
        result.append((row.key, row.op, value))
    return tuple(result)


def _contains(block: Block, key: str, op: str, value: str) -> bool:
    return any(
        (
            row.key == key
            and row.op == op
            and isinstance(row.value, Scalar)
            and row.value.unquoted == value
        )
        or (isinstance(row.value, Block) and _contains(row.value, key, op, value))
        for row in block.assignments()
    )


def _roots(inputs: Mapping[str, str]) -> dict[str, Block]:
    roots = {}
    for source, digest in load()["sources"].items():
        text = inputs.get(source)
        if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != digest:
            raise ValueError(f"条约接受完整原版来源漂移：{source}")
        if source == DOC:
            continue
        parsed = parse_text(text)
        if parsed.errors:
            raise ValueError(f"条约接受完整原版解析失败：{source}")
        roots[source] = parsed.root
    return roots


def verify_inputs(inputs: Mapping[str, str]) -> None:
    roots = _roots(inputs)
    doc = inputs[DOC]
    start = doc.index("#### inherent_accept_score scopes")
    end = doc.index("### contextual_accept_score", start)
    section = doc[start:end]
    for required in (
        "`root`: The country we're looking to check the acceptance on.",
        "`scope:article`: The article in question with whatever inputs it might have",
        "There is no `scope:treaty` here",
        "ONLY for mutual articles:",
        "ONLY for directed articles:",
        "`scope:source_country` is the specific party that would be bound as the source party",
        "`scope:target_country` is the specific party that would be bound as the target party",
    ):
        if required not in section:
            raise ValueError("条约接受原版文档角色/阶段合同漂移")
    article = _block(roots[SOURCE], DEFINITION)
    _scalar(article, "kind", "directed")
    _scalar(article, "maintenance_paid_by", "target_country")
    if tuple(s.unquoted for s in _block(article, "required_inputs").scalars()) != ("goods",):
        raise ValueError("条约接受必须保持真实goods输入")
    effect = _block(_block(article, "on_entry_into_force"), "scope:article_options.source_country")
    branch = _block(effect, "if")
    _scalar(_block(branch, "limit"), "has_any_tariffs_on", "scope:article_options.input_goods")
    for key in ("set_export_tariff_level", "set_import_tariff_level"):
        tariff = _block(branch, key)
        if _shape(tariff) != (
            ("goods", "=", "scope:article_options.input_goods"),
            ("level", "=", "no_tariffs_or_subventions"),
        ):
            raise ValueError("条约接受真实移除关税效果漂移")
    ai = _block(article, "ai")
    _scalar(ai, "combined_acceptance_cap_max", "20")
    _scalar(ai, "combined_acceptance_cap_min", "-500")
    native = _block(ai, "inherent_accept_score")
    _scalar(native, "value", "0")
    _scalar(_block(_block(native, "if"), "limit"), "scope:source_country", "this", "?=")
    if _contains(native, "in_default", "=", "yes") or _contains(
        native, "net_total_income", "<", "0"
    ):
        raise ValueError("条约接受财政分量已被原版覆盖，须重新审查")
    # Independent exact same-stage goods-context evidence; no treaty traversal.
    goods_ai = _block(
        _block(_block(roots[GOODS_TRANSFER], "goods_transfer"), "ai"), "inherent_accept_score"
    )
    if not _contains(goods_ai, "exists", "=", INPUT_MARKET) or not _contains(
        goods_ai, "add", "=", "market_goods_delta"
    ):
        raise ValueError("条约接受输入市场/实际余额getter证据漂移")
    money = _block(
        _block(_block(roots[MONEY_TRANSFER], "money_transfer"), "ai"), "inherent_accept_score"
    )
    if not _contains(money, "in_default", "=", "yes"):
        raise ValueError("条约接受ROOT违约读数证据漂移")
    if not _contains(roots[INCOME], "net_total_income", ">", "0"):
        raise ValueError("条约接受实际净收入读数证据漂移")


def frozen_inputs() -> dict[str, str]:
    data = json.loads(FROZEN.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "evidence", "normalization", "source_hashes", "inputs"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or data["evidence"] != "static_complete_native_sources_not_engine_execution"
        or data["normalization"] != "utf8_without_bom_lf_preserve_whitespace"
        or data["source_hashes"] != load()["sources"]
        or set(data["inputs"]) != SOURCES
    ):
        raise ValueError("条约接受冻结完整底本无效")
    verify_inputs(data["inputs"])
    return cast("dict[str, str]", data["inputs"])


@dataclass(frozen=True, slots=True)
class AcceptanceProgram:
    scalar: programs.ScalarProgram
    source: str = SOURCE
    field: str = FIELD
    actor: str = "root"
    kind: str = "directed"
    unit: str = "acceptance_score"

    @property
    def writer_id(self) -> str:
        return self.scalar.action_id

    @property
    def definition(self) -> str:
        return DEFINITION

    @property
    def consumer_id(self) -> str:
        return ACTION

    @property
    def field_path(self) -> tuple[str, ...]:
        return (DEFINITION, "ai", "inherent_accept_score")

    def validate(self) -> None:
        if self != compile_program():
            raise ValueError("条约接受程序身份/参数/分组漂移")

    def evaluation_context(self) -> EvaluationContext:
        from .situated.decision_ir import ContextBinding, EvaluationContext  # noqa: PLC0415

        return EvaluationContext(
            actor_scope=ContextBinding("root", "country", "actor", DOC, 559),
            auxiliary_scopes=(
                ContextBinding("article", "treaty_article_options", "auxiliary", DOC, 560),
                ContextBinding("source_country", "country", "auxiliary", DOC, 575),
                ContextBinding("target_country", "country", "auxiliary", DOC, 576),
                ContextBinding(
                    "article_input_market_goods", "market_goods", "auxiliary", GOODS_TRANSFER, 259
                ),
            ),
            evidence=(
                f"{DOC}:559",
                f"{DOC}:560",
                f"{DOC}:565",
                f"{DOC}:575",
                f"{DOC}:576",
                f"{GOODS_TRANSFER}:259",
                f"{GOODS_TRANSFER}:271",
            ),
        )

    def readers(self) -> tuple[Reader, ...]:
        from .decision_rules import Reader  # noqa: PLC0415

        return (
            Reader(
                "acceptance_article_exists",
                "exists",
                "root",
                "boolean",
                "boolean",
                argument="scope:article",
            ),
            Reader(
                "acceptance_source_exists",
                "exists",
                "root",
                "boolean",
                "boolean",
                argument="scope:source_country",
            ),
            Reader(
                "acceptance_target_exists",
                "exists",
                "root",
                "boolean",
                "boolean",
                argument="scope:target_country",
            ),
            Reader(
                "acceptance_input_exists",
                "exists",
                "root",
                "boolean",
                "boolean",
                argument=INPUT_MARKET,
            ),
            Reader(
                "acceptance_tariffs",
                "has_any_tariffs_on",
                "root",
                "boolean",
                "boolean",
                argument="scope:article.input_goods",
            ),
            Reader("acceptance_default", "in_default", "root", "boolean", "boolean"),
            Reader("acceptance_income", "net_total_income", "root", "currency_per_week", "number"),
            Reader(
                "acceptance_delta",
                "market_goods_delta",
                "article_input_market_goods",
                "sell_minus_buy_orders",
                "number",
            ),
        )

    def reader_bindings(self) -> tuple[tuple[str, str, str, str], ...]:
        return (
            ("acceptance_article_exists", "article", "treaty_article_options", "auxiliary"),
            ("acceptance_source_exists", "source_country", "country", "auxiliary"),
            ("acceptance_target_exists", "target_country", "country", "auxiliary"),
            ("acceptance_input_exists", "article_input_market_goods", "market_goods", "auxiliary"),
            ("acceptance_tariffs", "root", "country", "actor"),
            ("acceptance_default", "root", "country", "actor"),
            ("acceptance_income", "root", "country", "actor"),
            ("acceptance_delta", "article_input_market_goods", "market_goods", "auxiliary"),
        )

    def writer_ir(self) -> WriterDecisionIR:
        from .situated.decision_ir import WriterDecisionIR  # noqa: PLC0415

        self.validate()
        return WriterDecisionIR(
            writer_id=self.writer_id,
            kind="acceptance_program",
            source=self.source,
            definition=self.definition,
            consumer_id=self.consumer_id,
            field=self.field,
            actor="root",
            target="none",
            operation="add",
            vanilla_tail="preserve",
            owner="treaty_acceptance_opportunities",
            acceptance_program=self,
            evaluation_context=self.evaluation_context(),
            reader_context_bindings=self.reader_bindings(),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "writer_id": self.writer_id,
            "consumer_id": self.consumer_id,
            "domain": DOMAIN,
            "operation": "add",
            "vanilla_tail": "preserve",
            "evaluation_context": self.evaluation_context().as_dict(),
            "reader_context_bindings": [list(row) for row in self.reader_bindings()],
            "readers": [asdict(reader) for reader in self.readers()],
            "role_predicates": {"source": _SOURCE_ROLE, "target": _TARGET_ROLE},
            "source_hashes": load()["sources"],
        }

    def evaluate(self, values: Mapping[str, Any], *, is_ai: bool, enabled: bool = True) -> float:
        return evaluate(
            values,
            is_ai=is_ai,
            enabled_domains=frozenset({DOMAIN}) if enabled else frozenset(),
            consumer_program=self,
        )


def compile_program() -> AcceptanceProgram:
    data = load()["tuning"]
    cost = data["source_default_cost"]
    return AcceptanceProgram(
        programs.ScalarProgram(
            ACTION,
            "add",
            0,
            -cost,
            data["target_input_need"],
            (
                programs.ScalarGroup(
                    "source_financing",
                    (
                        programs.ScalarTerm(
                            "source_tariff_commitment",
                            ACTION,
                            -cost,
                            (
                                programs.ScalarEffect("source_cheap", cost),
                                programs.ScalarEffect(
                                    "source_deficit", cost - data["source_deficit_cost"]
                                ),
                            ),
                        ),
                    ),
                ),
                programs.ScalarGroup(
                    "target_supply",
                    (programs.ScalarTerm("target_input_need", ACTION, data["target_input_need"]),),
                ),
            ),
        )
    )


_SOURCE_ROLE = "scope:source_country ?= this NOT = { scope:target_country ?= this }"
_TARGET_ROLE = "scope:target_country ?= this NOT = { scope:source_country ?= this }"
GUARDS = {
    "source_tariff_commitment": _SOURCE_ROLE
    + f' exists = "{INPUT_MARKET}" has_any_tariffs_on = scope:article.input_goods',
    "source_cheap": "in_default = no net_total_income >= 0",
    "source_deficit": "in_default = no net_total_income < 0",
    "target_input_need": _TARGET_ROLE
    + f' exists = "{INPUT_MARKET}" "{INPUT_MARKET}" = {{ market_goods_delta < 0 }}',
}
AI_GUARD = "exists = ROOT ROOT = { is_ai = yes } exists = scope:article exists = scope:source_country exists = scope:target_country"


def _finite(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def evaluate(
    values: Mapping[str, Any],
    *,
    is_ai: bool,
    enabled_domains: frozenset[str] = frozenset({DOMAIN}),
    consumer_program: AcceptanceProgram | None = None,
) -> float:
    if type(is_ai) is not bool:
        raise ValueError("条约接受AI身份必须为已知布尔")
    if not is_ai or DOMAIN not in enabled_domains:
        return 0
    root, source, target = (values.get(k) for k in ("root", "source", "target"))
    if (
        any(not isinstance(v, str) or not v for v in (root, source, target))
        or values.get("article_exists") is not True
    ):
        return 0
    source_role = root == source and root != target
    target_role = root == target and root != source
    goods_present = values.get("input_market_goods_exists") is True
    default, income, delta = (
        values.get(k) for k in ("in_default", "net_total_income", "input_goods_delta")
    )
    guards = {
        "source_tariff_commitment": source_role
        and goods_present
        and values.get("tariffs_on_input") is True,
        "source_cheap": default is False and _finite(income) and income >= 0,
        "source_deficit": default is False and _finite(income) and income < 0,
        "target_input_need": target_role and goods_present and _finite(delta) and delta < 0,
    }
    selected = compile_program() if consumer_program is None else consumer_program
    return programs.evaluate_scalar(selected.scalar, guards)


def render(program: AcceptanceProgram) -> str:
    program.validate()
    return (
        f"\n\t\t# SITAI BEGIN treaty_acceptance:{DEFINITION}\n"
        f"\t\t# ACTION {program.writer_id} [{DOMAIN}];\n"
        + programs.render_scalar(
            program.scalar, GUARDS, ai_guard=AI_GUARD, style="cards", domain=DOMAIN
        )
        + f"\t\t# SITAI END treaty_acceptance:{DEFINITION}\n\t\t"
    )


def _close_offset(text: str, line: int) -> int:
    tokens = tokenize(text)
    matches = [
        i
        for i, t in enumerate(tokens)
        if t.kind == ATOM and t.value == "inherent_accept_score" and t.line == line
    ]
    if len(matches) != 1 or tokens[matches[0] + 2].kind != LBRACE:
        raise ValueError("条约接受评分精确块定位不唯一")
    starts = [0]
    for fragment in text.splitlines(keepends=True):
        starts.append(starts[-1] + len(fragment))
    depth = 0
    for token in tokens[matches[0] + 2 :]:
        depth += token.kind == LBRACE
        depth -= token.kind == RBRACE
        if depth == 0:
            return starts[token.line - 1] + token.col - 1
    raise ValueError("条约接受评分块未闭合")


def patch(
    inputs: Mapping[str, str],
    *,
    enabled_domains: frozenset[str] = frozenset({DOMAIN}),
    overlays: Mapping[str, str] | None = None,
    consumer_program: AcceptanceProgram | None = None,
) -> dict[str, str]:
    verify_inputs(inputs)
    if DOMAIN not in enabled_domains:
        return {}
    text = (overlays or {}).get(SOURCE, inputs[SOURCE])
    if f"SITAI BEGIN treaty_acceptance:{DEFINITION}" in text:
        raise ValueError("条约接受物理writer已由本程序写入，拒绝重复作者")
    parsed = parse_text(text)
    if parsed.errors:
        raise ValueError("条约接受overlay解析失败")
    ai = _block(_block(parsed.root, DEFINITION), "ai")
    native = _block(ai, "inherent_accept_score")
    original = _block(
        _block(_block(parse_text(inputs[SOURCE]).root, DEFINITION), "ai"), "inherent_accept_score"
    )
    if _shape(native) != _shape(original):
        raise ValueError("条约接受物理评分已有其他改动，拒绝双作者")
    offset = _close_offset(text, ai.all("inherent_accept_score")[0].line)
    selected = compile_program() if consumer_program is None else consumer_program
    return {SOURCE: text[:offset] + render(selected) + text[offset:]}


def consumer_catalog() -> dict[str, dict[str, Any]]:
    inputs = frozen_inputs()
    ai = _block(_block(parse_text(inputs[SOURCE]).root, DEFINITION), "ai")
    lines = inputs[DOC].splitlines()
    return {
        DEFINITION: {
            "source": SOURCE,
            "definition": DEFINITION,
            "field": FIELD,
            "native_root": "country",
            "actor": "root",
            "kind": "directed",
            "native_unit": "acceptance_score",
            "operation": "add",
            "placement": "after_complete_native_inherent_score",
            "source_country": "party_bound_to_remove_actual_input_goods_tariffs",
            "target_country": "party_receiving_no_tariffs_right",
            "treaty_scope": "unavailable_not_consumed",
            "input": "scope:article.input_goods and exact input_market_goods(root), only when observed present",
            "scope_evidence": [
                f"{DOC}:{next(i + 1 for i, t in enumerate(lines) if t == '#### inherent_accept_score scopes')}",
                f"{SOURCE}:{ai.all('inherent_accept_score')[0].line}",
            ],
            "unknown_policy": "missing_roles_or_input=local_exit; tariff_unknown=no_cost_anchor; known_source_tariff_with_unknown_finance=worst_cost; unknown_need=local_exit",
            "cost_basis": "actual source tariff removal relinquishes a revenue policy option while observed deficit/default limits financing; bounded design preference, no predicted tariff revenue or trade outcome",
            "source_sha256": load()["sources"][SOURCE],
        }
    }
