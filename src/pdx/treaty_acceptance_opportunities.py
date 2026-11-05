"""Exact directed article acceptance; ROOT is the country being checked.

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
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, TypeGuard, cast

from . import config
from .lexer import ATOM, LBRACE, RBRACE, tokenize
from .model import Block, Scalar
from .parser import parse_text


@dataclass(frozen=True, slots=True)
class ExistingMilitarySourceCommitmentQuery:
    """ROOT's bounded current treaties, including frozen/unknown status."""


@dataclass(frozen=True, slots=True)
class ExistingCommitmentQuery:
    """Exact candidate other party in ROOT's existing treaty collection."""

    definition: str


from .situated import programs  # noqa: E402

if TYPE_CHECKING:
    from .decision_rules import Reader
    from .observation_queries import CompiledQuery
    from .situated.decision_ir import EvaluationContext, WriterDecisionIR

PARAMETERS = config.REPO / "mod/decisions/treaty_acceptance_opportunities.toml"
FROZEN = config.REPO / "research/vanilla-ai/1.15.0/treaty-acceptance-opportunities.json"
SOURCE = "common/treaty_articles/21_no_tariffs.txt"
DOC = "common/treaty_articles/treaty_articles.md"
GOODS_TRANSFER = "common/treaty_articles/13_goods_transfer.txt"
MONEY_TRANSFER = "common/treaty_articles/05_transfer_money.txt"
INCOME = "common/journal_entries/06_portugal_politics.txt"
MILITARY_SOURCE = "common/treaty_articles/12_military_assistance.txt"
POWER_VALUES = "common/script_values/01_power_bloc_values.txt"
JOIN_BLOC = "common/treaty_articles/09_join_power_bloc.txt"
HOST_EMBASSY = "common/treaty_articles/10_host_power_bloc_embassy.txt"
COMMITMENTS = {
    "alliance": ("common/treaty_articles/00_alliance.txt", "mutual", 150, 343),
    "defensive_pact": ("common/treaty_articles/01_defensive_pact.txt", "mutual", 100, 222),
    "guarantee_independence": (
        "common/treaty_articles/02_guarantee_independence.txt",
        "directed",
        50,
        213,
    ),
    "support_independence": (
        "common/treaty_articles/03_support_independence.txt",
        "directed",
        50,
        218,
    ),
}
DEFEAT_SOURCE = "common/on_actions/00_code_on_actions.txt"
COMMITMENT_PARAMETERS = "military_commitment_query"
SOURCES = frozenset(
    {
        SOURCE,
        DOC,
        GOODS_TRANSFER,
        MONEY_TRANSFER,
        INCOME,
        MILITARY_SOURCE,
        POWER_VALUES,
        JOIN_BLOC,
        HOST_EMBASSY,
        *(meta[0] for meta in COMMITMENTS.values()),
        DEFEAT_SOURCE,
    }
)
DEFINITION = "no_tariffs"
FIELD = "no_tariffs.ai.inherent_accept_score"
DOMAIN = "diplomacy"
ACTION = "treaty_acceptance_no_tariffs"
MILITARY_DEFINITION = "military_assistance"
MILITARY_ACTION = "treaty_acceptance_military_assistance"


@dataclass(frozen=True, slots=True)
class AcceptanceSpec:
    definition: str
    source: str
    action: str

    @property
    def field(self) -> str:
        return f"{self.definition}.ai.inherent_accept_score"


SPECS = (
    AcceptanceSpec(DEFINITION, SOURCE, ACTION),
    AcceptanceSpec(MILITARY_DEFINITION, MILITARY_SOURCE, MILITARY_ACTION),
    *(
        AcceptanceSpec(name, meta[0], f"treaty_acceptance_{name}")
        for name, meta in COMMITMENTS.items()
    ),
)


def _spec(definition: str) -> AcceptanceSpec:
    matches = [spec for spec in SPECS if spec.definition == definition]
    if len(matches) != 1:
        raise ValueError("条约接受程序必须使用精确登记定义")
    return matches[0]


INPUT_MARKET = "scope:article.input_market_goods(root)"


def load() -> dict[str, Any]:
    data = tomllib.loads(PARAMETERS.read_text(encoding="utf-8"))
    if (
        set(data)
        != {"schema", "sources", "tuning", "military_tuning", "commitment_tuning", "parent_hashes"}
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
    military = data["military_tuning"]
    if (
        set(military) != {"source_deficit_cost", "source_default_cost"}
        or any(type(v) not in {int, float} or not math.isfinite(v) for v in military.values())
        or not 0 < military["source_deficit_cost"] <= military["source_default_cost"] <= 10
    ):
        raise ValueError("军事援助接受成本必须保持有限且有界")
    costs = data["commitment_tuning"]
    if (
        set(costs) != {"default_cost", "deficit_cost", "recovery_cost"}
        or any(type(v) not in {int, float} or not math.isfinite(v) for v in costs.values())
        or not 0 < costs["deficit_cost"] <= costs["default_cost"] <= 10
        or not 0 < costs["recovery_cost"] <= 3
    ):
        raise ValueError("军事新增义务有限成本参数无效")
    if set(data["parent_hashes"]) != set(COMMITMENTS):
        raise ValueError("军事接受父结构哈希集合漂移")
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
    _verify_military(roots, doc)
    _verify_commitments(roots, doc)
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


def _verify_military(roots: Mapping[str, Block], doc: str) -> None:
    article = _block(roots[MILITARY_SOURCE], MILITARY_DEFINITION)
    _scalar(article, "kind", "directed")
    _scalar(article, "cost", "25")
    _scalar(article, "maintenance_paid_by", "source_country")
    source = _block(article, "source_modifier")
    _scalar(source, "country_military_goods_cost_mult", "0.10")
    targets = article.all("target_modifier")
    if not any(
        isinstance(row.value, Block)
        and _contains(row.value, "country_military_goods_cost_mult", "=", "-0.1")
        for row in targets
    ):
        raise ValueError("军事援助真实target军需减费漂移")
    native = _block(_block(article, "ai"), "inherent_accept_score")
    # The first native if is the ROOT/source branch; the later if owns the
    # binding-period tail is now a separate contextual field and remains native.
    branches = native.all("if")
    if len(branches) != 1 or not isinstance(branches[0].value, Block):
        raise ValueError("军事援助完整inherent父结构漂移")
    source_branch = branches[0].value
    _scalar(_block(source_branch, "limit"), "scope:source_country", "this", "?=")
    if not any(
        isinstance(row.value, Block) and _contains(row.value, "has_type", "=", MILITARY_DEFINITION)
        for row in source_branch.all("if")
    ):
        raise ValueError("军事援助ROOT既有条约集合证据漂移")
    ratify = _block(article, "can_ratify")
    if not _contains(ratify, "source_country", "=", "scope:source_country"):
        raise ValueError("军事援助既有article真实source_country链接证据漂移")
    helper = _block(roots[POWER_VALUES], "ai_accept_join_request_score_treaties")
    if not _contains(helper, "military_expenses", "<", "2000"):
        raise ValueError("军事援助实际总军费getter证据漂移")
    for path, definition in (
        (JOIN_BLOC, "join_power_bloc"),
        (HOST_EMBASSY, "host_power_bloc_embassy"),
    ):
        inherent = _block(_block(_block(roots[path], definition), "ai"), "inherent_accept_score")
        if not _contains(inherent, "add", "=", "ai_accept_join_request_score_treaties"):
            raise ValueError("军事援助同阶段军费getter调用证据漂移")
    for required in (
        "`scope:is_treaty_active`: only set when the treaty is already in force",
        "`scope:is_renegotiation`: only set when the treaty is being renegotiated",
        'article (in other words: it applies to the "giving" party).',
    ):
        if required not in doc:
            raise ValueError("军事援助source/生命周期原版文档证据漂移")
    if _contains(native, "in_default", "=", "yes") or _contains(
        native, "net_total_income", "<", "0"
    ):
        raise ValueError("军事援助财政成本已被原版覆盖，须重新审查")


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
        return self.field.split(".")[0]

    @property
    def consumer_id(self) -> str:
        return _spec(self.definition).action

    @property
    def field_path(self) -> tuple[str, ...]:
        return (self.definition, "ai", "inherent_accept_score")

    def validate(self) -> None:
        if self != compile_program(self.definition):
            raise ValueError("条约接受程序身份/参数/分组漂移")

    def evaluation_context(self) -> EvaluationContext:
        from .situated.decision_ir import ContextBinding, EvaluationContext  # noqa: PLC0415

        if self.definition in COMMITMENTS:
            return _commitment_context(self.definition)
        if self.definition == MILITARY_DEFINITION:
            return EvaluationContext(
                actor_scope=ContextBinding("root", "country", "actor", DOC, 559),
                auxiliary_scopes=(
                    ContextBinding("article", "treaty_article_options", "auxiliary", DOC, 560),
                    ContextBinding("source_country", "country", "auxiliary", DOC, 575),
                    ContextBinding("target_country", "country", "auxiliary", DOC, 576),
                ),
                evidence=(
                    f"{DOC}:559",
                    f"{DOC}:560",
                    f"{DOC}:561",
                    f"{DOC}:562",
                    f"{DOC}:565",
                    f"{DOC}:575",
                    f"{DOC}:576",
                    f"{MILITARY_SOURCE}:27",
                    f"{MILITARY_SOURCE}:29",
                    f"{MILITARY_SOURCE}:109",
                    f"{MILITARY_SOURCE}:329",
                    f"{POWER_VALUES}:1231",
                    f"{JOIN_BLOC}:346",
                    f"{HOST_EMBASSY}:389",
                ),
            )
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

        if self.definition in COMMITMENTS:
            return _commitment_readers(self.definition)
        if self.definition == MILITARY_DEFINITION:
            return (
                Reader(
                    "military_article_exists",
                    "exists",
                    "root",
                    "boolean",
                    "boolean",
                    argument="scope:article",
                ),
                Reader(
                    "military_source_exists",
                    "exists",
                    "root",
                    "boolean",
                    "boolean",
                    argument="scope:source_country",
                ),
                Reader(
                    "military_target_exists",
                    "exists",
                    "root",
                    "boolean",
                    "boolean",
                    argument="scope:target_country",
                ),
                Reader(
                    "military_active_exists",
                    "exists",
                    "root",
                    "boolean",
                    "boolean",
                    argument="scope:is_treaty_active",
                ),
                Reader(
                    "military_renegotiation_exists",
                    "exists",
                    "root",
                    "boolean",
                    "boolean",
                    argument="scope:is_renegotiation",
                ),
                Reader("military_default", "in_default", "root", "boolean", "boolean"),
                Reader(
                    "military_income", "net_total_income", "root", "currency_per_week", "number"
                ),
                Reader(
                    "military_expenses", "military_expenses", "root", "currency_per_week", "number"
                ),
                Reader(
                    "military_existing_source_commitment",
                    "any_scope_treaty",
                    "root",
                    "boolean",
                    "boolean",
                    parameters=((QUERY_PARAMETER, "existing_source_commitment"),),
                ),
            )
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
        if self.definition in COMMITMENTS:
            return _commitment_bindings(self.definition)
        if self.definition == MILITARY_DEFINITION:
            return (
                ("military_article_exists", "article", "treaty_article_options", "auxiliary"),
                ("military_source_exists", "source_country", "country", "auxiliary"),
                ("military_target_exists", "target_country", "country", "auxiliary"),
                *(
                    (key, "root", "country", "actor")
                    for key in (
                        "military_active_exists",
                        "military_renegotiation_exists",
                        "military_default",
                        "military_income",
                        "military_expenses",
                        "military_existing_source_commitment",
                    )
                ),
            )
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


def compile_program(definition: str = DEFINITION) -> AcceptanceProgram:
    spec = _spec(definition)
    if definition in COMMITMENTS:
        return _compile_commitment(definition)
    if definition == MILITARY_DEFINITION:
        data = load()["military_tuning"]
        return AcceptanceProgram(
            programs.ScalarProgram(
                spec.action,
                "add",
                0,
                -data["source_default_cost"],
                0,
                (
                    programs.ScalarGroup(
                        "source_goods_financing",
                        (
                            programs.ScalarTerm(
                                "military_source_default", spec.action, -data["source_default_cost"]
                            ),
                            programs.ScalarTerm(
                                "military_source_deficit", spec.action, -data["source_deficit_cost"]
                            ),
                        ),
                    ),
                ),
            ),
            source=spec.source,
            field=spec.field,
        )
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


def compile_programs() -> tuple[AcceptanceProgram, ...]:
    return tuple(compile_program(spec.definition) for spec in SPECS)


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
QUERY_PARAMETER = "military_assistance_query"


def query_from_reader(
    engine: str, parameters: Mapping[str, str]
) -> ExistingMilitarySourceCommitmentQuery | ExistingCommitmentQuery:
    if engine == "any_scope_treaty" and set(parameters) == {COMMITMENT_PARAMETERS}:
        definition = parameters[COMMITMENT_PARAMETERS]
        if definition not in COMMITMENTS:
            raise ValueError("军事接受查询定义无效")
        return ExistingCommitmentQuery(definition)
    if engine != "any_scope_treaty" or parameters != {
        QUERY_PARAMETER: "existing_source_commitment"
    }:
        raise ValueError("军事援助查询只接受精确既有source承诺身份")
    return ExistingMilitarySourceCommitmentQuery()


def render_query(query: ExistingMilitarySourceCommitmentQuery | ExistingCommitmentQuery) -> str:
    if type(query) is ExistingCommitmentQuery:
        return render_commitment_query(query)
    if type(query) is not ExistingMilitarySourceCommitmentQuery:
        raise ValueError("军事援助只授权ROOT既有source承诺固定查询")
    # Existing TreatyArticle has source_country; candidate TreatyArticleOptions
    # never supplies a treaty link. Missing existing source blocks firstness.
    return (
        "any_scope_treaty = { any_scope_article = { has_type = military_assistance "
        "OR = { NOT = { exists = source_country } source_country = ROOT } } }"
    )


def compile_query(
    query: ExistingMilitarySourceCommitmentQuery | ExistingCommitmentQuery,
    inputs: Mapping[str, str],
) -> CompiledQuery:
    from .observation_queries import CompiledQuery  # noqa: PLC0415

    if type(query) is ExistingCommitmentQuery:
        return compile_commitment_query(query, inputs)
    expression = render_query(query)
    verify_inputs(inputs)
    return CompiledQuery(
        expression=expression,
        references=(
            f"{MILITARY_SOURCE}:97",
            f"{MILITARY_SOURCE}:107",
            f"{MILITARY_SOURCE}:109",
            f"{MILITARY_SOURCE}:329",
            f"{MILITARY_SOURCE}:331",
        ),
        source_hashes=tuple(sorted(load()["sources"].items())),
        local_collections=("country.any_scope_treaty", "treaty.any_scope_article"),
    )


MILITARY_CORE_GUARD = (
    _SOURCE_ROLE
    + " NOT = { exists = scope:is_treaty_active } NOT = { exists = scope:is_renegotiation }"
    + " military_expenses > 0 NOT = { "
    + render_query(ExistingMilitarySourceCommitmentQuery())
    + " }"
)
MILITARY_GUARDS = {
    "military_source_default": MILITARY_CORE_GUARD + " in_default = yes",
    "military_source_deficit": MILITARY_CORE_GUARD + " net_total_income < 0",
}

AI_GUARD = "exists = ROOT ROOT = { is_ai = yes } exists = scope:article exists = scope:source_country exists = scope:target_country"


def _finite(value: object) -> TypeGuard[int | float]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


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
    selected = compile_program() if consumer_program is None else consumer_program
    selected.validate()
    if selected.definition in COMMITMENTS:
        return _evaluate_commitment(values, selected)
    if selected.definition == MILITARY_DEFINITION:
        return _evaluate_military(values, selected)
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


def _evaluate_military(values: Mapping[str, Any], selected: AcceptanceProgram) -> float:
    root, source, target = (values.get(key) for key in ("root", "source", "target"))
    if values.get("first") is not None or values.get("second") is not None:
        raise ValueError("军事援助directed上下文不得使用mutual角色")
    identities = all(isinstance(value, str) and value for value in (root, source, target))
    treaties = values.get("existing_treaties")
    if treaties is not None and not isinstance(treaties, (list, tuple)):
        raise ValueError("军事援助既有条约必须是完整集合或未知")
    new = treaties is not None
    for treaty in treaties or ():
        if not isinstance(treaty, Mapping):
            raise ValueError("军事援助既有条约成员必须是映射")
        articles = treaty.get("articles")
        if articles is None:
            new = False
            continue
        if not isinstance(articles, (list, tuple)):
            raise ValueError("军事援助既有条款必须是完整集合或未知")
        for article in articles:
            if not isinstance(article, Mapping):
                raise ValueError("军事援助既有条款成员必须是映射")
            kind = article.get("type")
            if kind is None:
                new = False
                continue
            if not isinstance(kind, str) or not kind:
                raise ValueError("军事援助既有条款type必须是非空身份或未知")
            if kind == MILITARY_DEFINITION:
                existing_source = article.get("source")
                if existing_source is not None and (
                    not isinstance(existing_source, str) or not existing_source
                ):
                    raise ValueError("军事援助既有source必须是非空身份或未知")
                if existing_source is None or existing_source == root:
                    new = False
    for key in ("is_treaty_active_exists", "is_renegotiation_exists", "in_default"):
        if values.get(key) is not None and type(values[key]) is not bool:
            raise ValueError("军事援助标记和default必须是布尔或未知")
    expenses, income = values.get("military_expenses"), values.get("net_total_income")
    core = (
        identities
        and root == source
        and root != target
        and values.get("article_exists") is True
        and values.get("is_treaty_active_exists") is False
        and values.get("is_renegotiation_exists") is False
        and new
        and _finite(expenses)
        and expenses > 0
    )
    return programs.evaluate_scalar(
        selected.scalar,
        {
            "military_source_default": bool(core and values.get("in_default") is True),
            "military_source_deficit": bool(core and _finite(income) and income < 0),
        },
    )


def render(program: AcceptanceProgram) -> str:
    program.validate()
    return (
        f"\n\t\t# SITAI BEGIN treaty_acceptance:{program.definition}\n"
        f"\t\t# ACTION {program.writer_id} [{DOMAIN}];\n"
        + programs.render_scalar(
            program.scalar,
            _commitment_guards(program.definition)
            if program.definition in COMMITMENTS
            else (MILITARY_GUARDS if program.definition == MILITARY_DEFINITION else GUARDS),
            ai_guard=_commitment_ai_guard(program.definition)
            if program.definition in COMMITMENTS
            else AI_GUARD,
            style="cards",
            domain=DOMAIN,
        )
        + f"\t\t# SITAI END treaty_acceptance:{program.definition}\n\t\t"
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
    selected = compile_program() if consumer_program is None else consumer_program
    selected.validate()
    source, definition = selected.source, selected.definition
    text = (overlays or {}).get(source, inputs[source])
    if f"SITAI BEGIN treaty_acceptance:{definition}" in text:
        raise ValueError("条约接受物理writer已由本程序写入，拒绝重复作者")
    parsed = parse_text(text)
    if parsed.errors:
        raise ValueError("条约接受overlay解析失败")
    ai = _block(_block(parsed.root, definition), "ai")
    native = _block(ai, "inherent_accept_score")
    original = _block(
        _block(_block(parse_text(inputs[source]).root, definition), "ai"), "inherent_accept_score"
    )
    if _shape(native) != _shape(original):
        raise ValueError("条约接受物理评分已有其他改动，拒绝双作者")
    offset = _close_offset(text, ai.all("inherent_accept_score")[0].line)
    selected = compile_program() if consumer_program is None else consumer_program
    return {source: text[:offset] + render(selected) + text[offset:]}


def consumer_catalog() -> dict[str, dict[str, Any]]:
    inputs = frozen_inputs()
    ai = _block(_block(parse_text(inputs[SOURCE]).root, DEFINITION), "ai")
    lines = inputs[DOC].splitlines()
    result = {
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

    military_ai = _block(
        _block(parse_text(inputs[MILITARY_SOURCE]).root, MILITARY_DEFINITION), "ai"
    )
    result[MILITARY_DEFINITION] = {
        "source": MILITARY_SOURCE,
        "definition": MILITARY_DEFINITION,
        "field": _spec(MILITARY_DEFINITION).field,
        "native_root": "country",
        "actor": "root",
        "kind": "directed",
        "native_unit": "acceptance_score",
        "operation": "add",
        "placement": "after_complete_native_inherent_score",
        "source_country": "giving_party_pays_actual_country_military_goods_cost_mult_plus_0.10",
        "target_country": "receiving_party_gets_country_military_goods_cost_mult_minus_0.10",
        "treaty_scope": "unavailable_not_consumed",
        "input": "no article input; bounded ROOT existing treaty/article/source_country only",
        "scope_evidence": [
            f"{DOC}:558",
            f"{MILITARY_SOURCE}:{military_ai.all('inherent_accept_score')[0].line}",
            f"{MILITARY_SOURCE}:109",
            f"{POWER_VALUES}:1231",
            f"{JOIN_BLOC}:346",
            f"{HOST_EMBASSY}:389",
        ],
        "unknown_policy": "missing_roles_article_newness_or_positive_finite_expenses=local_exit; known_default=-10; else_known_deficit=-6; otherwise=0; target=0",
        "cost_basis": "first source +0.10 military goods multiplier commitment; total military_expenses>0 is only an explicit soft financing exposure proxy, not goods spending or forecast; -6/-10 design preferences; no influence cost",
        "source_sha256": load()["sources"][MILITARY_SOURCE],
    }
    for definition, (source, kind, _cost, line) in COMMITMENTS.items():
        result[definition] = {
            "source": source,
            "definition": definition,
            "field": _spec(definition).field,
            "native_root": "country",
            "actor": "root",
            "kind": kind,
            "native_unit": "acceptance_score",
            "operation": "add",
            "placement": "after_complete_native_inherent_score",
            "treaty_scope": "unavailable_not_consumed",
            "scope_evidence": [f"{DOC}:559", f"{DOC}:561", f"{DOC}:562", f"{source}:{line}"],
            "unknown_policy": "unknown_identity_or_newness=local_exit; known_default_and_deficit_independent_of_recovery; known_recovery_independent_of_finance; no_guessed_war",
            "cost_basis": "bounded preference for a new obligation to this exact other party; financing tiers same cause, observed defeat recovery independent; no maintenance currency, no goods expense forecast",
            "source_sha256": load()["sources"][source],
        }
    return result


def _parent_digest(block: Block) -> str:
    def shape(node):
        if isinstance(node, Block):
            return [shape(item) for item in node.items]
        if isinstance(node, Scalar):
            return [node.text, node.quoted]
        return [node.key, node.op, node.prefix, shape(node.value)]

    return hashlib.sha256(
        json.dumps(shape(block), ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _verify_commitments(roots: Mapping[str, Block], doc: str) -> None:
    for required in (
        "`scope:first_country` is one of the parties that would be bound",
        "`scope:second_country` is the other party that would be bound",
        "- `source_country` - if directed",
        "There is no `scope:treaty` here",
        "source/target. Mutual articles have first/second.",
        "- `freeze`: causes the contravening party to have to keep up their end",
    ):
        if required not in doc:
            raise ValueError("军事接受角色/冻结义务合同漂移")
    for definition, (source, kind, cost, _line) in COMMITMENTS.items():
        article = _block(roots[source], definition)
        if _parent_digest(article) != load()["parent_hashes"][definition]:
            raise ValueError(f"军事接受完整父结构漂移：{definition}")
        _scalar(article, "kind", kind)
        _scalar(article, "cost", str(cost))
        if kind == "directed":
            _scalar(article, "maintenance_paid_by", "source_country")
        ai = _block(article, "ai")
        native = _block(ai, "inherent_accept_score")
        if _contains(native, "in_default", "=", "yes") or _contains(
            native, "net_total_income", "<", "0"
        ):
            raise ValueError("军事接受已有同因融资原式，须重新审查")
        if kind == "directed":
            branch = native.all("if")[0]
            assert isinstance(branch.value, Block)
            _scalar(_block(branch.value, "limit"), "scope:source_country", "this", "?=")
            if not _contains(
                _block(article, "can_ratify"), "source_country", "=", "scope:source_country"
            ):
                raise ValueError("军事接受真实既有条款来源链接漂移")
        if definition == "support_independence":
            support = _block(article, "automatically_support")
            if tuple(s.unquoted for s in support.scalars()) != (
                "dp_independence",
                "dp_increase_autonomy",
                "dp_annex_subject",
                "dp_hungarian_revolution",
                "dp_sepoy_mutiny",
            ):
                raise ValueError("支持独立真实自动支持义务漂移")
        if article.all("source_modifier") or _contains(
            article, "country_military_goods_cost_mult", "=", "0.10"
        ):
            raise ValueError("军事义务来源不能假装存在军援军需费用")
    lost = _block(roots[DEFEAT_SOURCE], "on_lost_war")
    if not (
        _contains(lost, "name", "=", "recently_lost_war") and _contains(lost, "days", "=", "1825")
    ):
        raise ValueError("真实败战记忆生命周期漂移")


def _commitment_context(definition: str) -> EvaluationContext:
    from .situated.decision_ir import ContextBinding, EvaluationContext  # noqa: PLC0415

    roles = (
        (("first_country", 571), ("second_country", 572))
        if COMMITMENTS[definition][1] == "mutual"
        else (("source_country", 575), ("target_country", 576))
    )
    return EvaluationContext(
        actor_scope=ContextBinding("root", "country", "actor", DOC, 559),
        auxiliary_scopes=(
            ContextBinding("article", "treaty_article_options", "auxiliary", DOC, 560),
            *(ContextBinding(role, "country", "auxiliary", DOC, line) for role, line in roles),
        ),
        evidence=(
            f"{DOC}:559",
            f"{DOC}:560",
            f"{DOC}:561",
            f"{DOC}:562",
            f"{DOC}:565",
            *(f"{DOC}:{line}" for _, line in roles),
            f"{COMMITMENTS[definition][0]}:{COMMITMENTS[definition][3]}",
        ),
    )


def _commitment_readers(definition: str) -> tuple[Reader, ...]:
    from .decision_rules import Reader  # noqa: PLC0415

    roles = (
        ("first_country", "second_country")
        if COMMITMENTS[definition][1] == "mutual"
        else ("source_country", "target_country")
    )
    return (
        Reader(
            "commitment_article_exists",
            "exists",
            "root",
            "boolean",
            "boolean",
            argument="scope:article",
        ),
        *(
            Reader(
                f"commitment_{role}_exists",
                "exists",
                "root",
                "boolean",
                "boolean",
                argument=f"scope:{role}",
            )
            for role in roles
        ),
        Reader(
            "commitment_active_exists",
            "exists",
            "root",
            "boolean",
            "boolean",
            argument="scope:is_treaty_active",
        ),
        Reader(
            "commitment_renegotiation_exists",
            "exists",
            "root",
            "boolean",
            "boolean",
            argument="scope:is_renegotiation",
        ),
        Reader("commitment_default", "in_default", "root", "boolean", "boolean"),
        Reader("commitment_income", "net_total_income", "root", "currency_per_week", "number"),
        Reader(
            "commitment_defeat",
            "has_variable",
            "root",
            "boolean",
            "boolean",
            argument="recently_lost_war",
        ),
        Reader(
            "commitment_existing",
            "any_scope_treaty",
            "root",
            "boolean",
            "boolean",
            parameters=((COMMITMENT_PARAMETERS, definition),),
        ),
    )


def _commitment_bindings(definition: str) -> tuple[tuple[str, str, str, str], ...]:
    roles = (
        ("first_country", "second_country")
        if COMMITMENTS[definition][1] == "mutual"
        else ("source_country", "target_country")
    )
    return (
        ("commitment_article_exists", "article", "treaty_article_options", "auxiliary"),
        *((f"commitment_{role}_exists", role, "country", "auxiliary") for role in roles),
        *(
            (key, "root", "country", "actor")
            for key in (
                "commitment_active_exists",
                "commitment_renegotiation_exists",
                "commitment_default",
                "commitment_income",
                "commitment_defeat",
                "commitment_existing",
            )
        ),
    )


def _compile_commitment(definition: str) -> AcceptanceProgram:
    spec = _spec(definition)
    tuning = load()["commitment_tuning"]
    default, deficit, recovery = (
        tuning[key] for key in ("default_cost", "deficit_cost", "recovery_cost")
    )
    return AcceptanceProgram(
        programs.ScalarProgram(
            spec.action,
            "add",
            0,
            -default - recovery,
            0,
            (
                programs.ScalarGroup(
                    "new_obligation_financing",
                    (
                        programs.ScalarTerm("commitment_default", spec.action, -default),
                        programs.ScalarTerm("commitment_deficit", spec.action, -deficit),
                    ),
                ),
                programs.ScalarGroup(
                    "observed_defeat_recovery",
                    (programs.ScalarTerm("commitment_recovery", spec.action, -recovery),),
                ),
            ),
        ),
        source=spec.source,
        field=spec.field,
        kind=COMMITMENTS[definition][1],
    )


def render_commitment_query(query: ExistingCommitmentQuery) -> str:
    if type(query) is not ExistingCommitmentQuery or query.definition not in COMMITMENTS:
        raise ValueError("军事接受仅授权精确四定义查询")
    definition = query.definition

    def clause(other: str) -> str:
        source = (
            " OR = { NOT = { exists = source_country } source_country = ROOT }"
            if COMMITMENTS[definition][1] == "directed"
            else ""
        )
        return f"any_scope_treaty = {{ binds = scope:{other} any_scope_article = {{ has_type = {definition}{source} }} }}"

    if COMMITMENTS[definition][1] == "directed":
        return clause("target_country")
    return (
        "OR = { AND = { scope:first_country ?= this "
        + clause("second_country")
        + " } AND = { scope:second_country ?= this "
        + clause("first_country")
        + " } }"
    )


def compile_commitment_query(
    query: ExistingCommitmentQuery, inputs: Mapping[str, str]
) -> CompiledQuery:
    from .observation_queries import CompiledQuery  # noqa: PLC0415

    verify_inputs(inputs)
    source, _kind, _cost, line = COMMITMENTS[query.definition]
    return CompiledQuery(
        expression=render_commitment_query(query),
        references=(f"{DOC}:37", f"{DOC}:575", f"{source}:{line}"),
        source_hashes=tuple(sorted(load()["sources"].items())),
        local_collections=("country.any_scope_treaty", "treaty.any_scope_article"),
    )


def _commitment_role(definition: str) -> str:
    if COMMITMENTS[definition][1] == "directed":
        return _SOURCE_ROLE
    return "OR = { scope:first_country ?= this scope:second_country ?= this } NOT = { scope:first_country ?= scope:second_country }"


def _commitment_ai_guard(definition: str) -> str:
    roles = (
        ("first_country", "second_country")
        if COMMITMENTS[definition][1] == "mutual"
        else ("source_country", "target_country")
    )
    return "exists = ROOT ROOT = { is_ai = yes } exists = scope:article " + " ".join(
        f"exists = scope:{role}" for role in roles
    )


def _commitment_guards(definition: str) -> dict[str, str]:
    core = (
        _commitment_role(definition)
        + " NOT = { exists = scope:is_treaty_active } NOT = { exists = scope:is_renegotiation } NOT = { "
        + render_commitment_query(ExistingCommitmentQuery(definition))
        + " }"
    )
    return {
        "commitment_default": core + " in_default = yes",
        "commitment_deficit": core + " net_total_income < 0",
        "commitment_recovery": core + " has_variable = recently_lost_war",
    }


def _new_obligation(values: Mapping[str, Any], definition: str, other: str) -> bool:
    treaties = values.get("existing_treaties")
    if treaties is None:
        return False
    if not isinstance(treaties, (list, tuple)):
        raise ValueError("军事既有条约须是完整集合或未知")
    root = values["root"]
    for treaty in treaties:
        if not isinstance(treaty, Mapping):
            raise ValueError("军事既有条约成员须是映射")
        binds = treaty.get("binds")
        if binds is not None and (
            not isinstance(binds, (list, tuple))
            or any(not isinstance(key, str) or not key for key in binds)
        ):
            raise ValueError("军事既有条约双方须是身份列表或未知")
        if binds is not None and other not in binds:
            continue
        articles = treaty.get("articles")
        if articles is None:
            return False
        if not isinstance(articles, (list, tuple)):
            raise ValueError("军事既有条款须是完整集合或未知")
        for article in articles:
            if not isinstance(article, Mapping):
                raise ValueError("军事既有条款成员须是映射")
            kind = article.get("type")
            if kind is None:
                return False
            if not isinstance(kind, str) or not kind:
                raise ValueError("军事既有条款类型须是身份或未知")
            if kind != definition:
                continue
            if COMMITMENTS[definition][1] == "mutual":
                return False
            source = article.get("source")
            if source is not None and (not isinstance(source, str) or not source):
                raise ValueError("军事既有条款source须是身份或未知")
            if source is None or source == root:
                return False
    return True


def _evaluate_commitment(values: Mapping[str, Any], selected: AcceptanceProgram) -> float:
    definition = selected.definition
    mutual = COMMITMENTS[definition][1] == "mutual"
    invalid_roles = ("source", "target") if mutual else ("first", "second")
    if any(values.get(key) is not None for key in invalid_roles):
        raise ValueError("军事接受mutual/direct角色不可混用")
    roles = ("root", "first", "second") if mutual else ("root", "source", "target")
    root, a, b = (values.get(key) for key in roles)
    if not all(isinstance(key, str) and key for key in (root, a, b)):
        return 0.0
    for key in (
        "article_exists",
        "is_treaty_active_exists",
        "is_renegotiation_exists",
        "in_default",
        "war_defeat",
    ):
        if values.get(key) is not None and type(values[key]) is not bool:
            raise ValueError("军事接受布尔事实必须明确布尔或未知")
    identity = a != b and (root in {a, b} if mutual else root == a)
    if not identity:
        return 0.0
    other = b if root == a else a
    if not isinstance(other, str):
        return 0.0
    core = (
        values.get("article_exists") is True
        and values.get("is_treaty_active_exists") is False
        and values.get("is_renegotiation_exists") is False
        and _new_obligation(values, definition, other)
    )
    income = values.get("net_total_income")
    return programs.evaluate_scalar(
        selected.scalar,
        {
            "commitment_default": bool(core and values.get("in_default") is True),
            "commitment_deficit": bool(core and _finite(income) and income < 0),
            "commitment_recovery": bool(core and values.get("war_defeat") is True),
        },
    )
