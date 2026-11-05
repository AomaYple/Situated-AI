"""Country ROOT tradeoffs for exact native diplomatic proposal scores."""

from __future__ import annotations

import hashlib
import json
import math
import tomllib
from typing import TYPE_CHECKING, Any

from . import config
from .model import Assignment, Block, Scalar
from .parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .decision_rules import RuleSet
    from .situated.decision_ir import EvaluationContext

PARAMETERS = config.REPO / "mod/decisions/native_action_opportunities.toml"
FROZEN = config.REPO / "research/vanilla-ai/1.15.0/native-action-opportunities.json"
FROZEN_SHA256 = "08026f41a051b14ea78b6f10d75e14448ed502d6d1339d40f3c7c6608b02287e"
README = "common/diplomatic_actions/diplomatic_action.md"
KNOWLEDGE = "da_knowledge_sharing"
KNOWLEDGE_SOURCE = "common/diplomatic_actions/40_subjects_knowledge_sharing.txt"
EXEMPT = "exempt_from_service"
SOVEREIGNTY = "violate_sovereignty"
RAISE = "raise_payments"
BATCH_CANDIDATES = {
    EXEMPT: "common/diplomatic_actions/34_subjects_exempt_from_service.txt",
    SOVEREIGNTY: "common/diplomatic_actions/03_violate_sovereignty.txt",
    RAISE: "common/diplomatic_actions/32_subjects_raise_payments.txt",
}
ON_ACTIONS = "common/on_actions/00_code_on_actions.txt"
FINANCE = "events/iberia_events/negotiation_events.txt"
POPULATION = "common/script_values/building_values.txt"
TRIGGERS = "common/trigger_localization/00_trigger_localization.txt"
TRIGGER_UNITS = "localization/english/triggers_l_english.yml"
# These inputs document why an unproven second capacity penalty is withheld.
CAPACITY_CANDIDATES = {
    "increase_relations": ("common/diplomatic_actions/00_relations_actions.txt", "150", "0.25"),
    "damage_relations": ("common/diplomatic_actions/00_relations_actions.txt", "100", "0.15"),
    "da_evangelize": ("common/diplomatic_actions/41_subjects_evangelize.txt", "25", "0.05"),
    "da_support_regime": ("common/diplomatic_actions/39_subjects_support_regime.txt", "50", "0.1"),
    "support_separatism": ("common/diplomatic_actions/52_nationalism_actions.txt", "100", "0.25"),
}
BATCH_READERS: dict[str, dict[str, Any]] = {
    "war": {"engine": "is_at_war", "scope": "root", "kind": "boolean", "unit": "boolean"},
    "war_defeat": {
        "engine": "has_variable",
        "scope": "root",
        "kind": "boolean",
        "unit": "boolean",
        "argument": "recently_lost_war",
    },
    "default": {"engine": "in_default", "scope": "root", "kind": "boolean", "unit": "boolean"},
    "net_surplus": {
        "engine": "net_total_income",
        "scope": "root",
        "kind": "number",
        "unit": "currency_per_week",
    },
    "cost_country_population": {
        "engine": "total_population",
        "scope": "root",
        "kind": "number",
        "unit": "persons",
        "minimum": 0,
    },
    "raise_target_liberty": {
        "engine": "liberty_desire",
        "scope": "target_country",
        "kind": "number",
        "unit": "liberty_0_100",
        "minimum": 0,
        "maximum": 100,
    },
    "raise_target_population": {
        "engine": "total_population",
        "scope": "target_country",
        "kind": "number",
        "unit": "persons",
        "minimum": 0,
    },
}
KNOWLEDGE_READERS: dict[str, dict[str, Any]] = {
    "knowledge_donor_spread": {
        "engine": "modifier:country_tech_spread_mult",
        "scope": "root",
        "unit": "modifier_ratio",
        "kind": "number",
    },
    "knowledge_donor_population": {
        "engine": "total_population",
        "scope": "root",
        "unit": "persons",
        "kind": "number",
        "minimum": 0,
    },
}
CANDIDATES = {
    **BATCH_CANDIDATES,
    KNOWLEDGE: KNOWLEDGE_SOURCE,
    "da_increase_autonomy_of_self": "common/diplomatic_actions/38_subjects_increase_autonomy.txt",
    "decrease_payments": "common/diplomatic_actions/33_subjects_decrease_payments.txt",
    "join_power_bloc": "common/diplomatic_actions/26_join_power_bloc.txt",
}
SOURCE_HASHES = {
    "common/diplomatic_actions/00_relations_actions.txt": "71b29f5d0c160cb178cdf45fea2af6591449f0f99aefda67a0747aee59ed7104",
    "common/diplomatic_actions/03_violate_sovereignty.txt": "82f1b0cf35891986e024b571cd0b08162ad665a703c5dff6423f38a9effb0a81",
    "common/diplomatic_actions/26_join_power_bloc.txt": "a66a61d5ee5a86282cec8f09b38bd0e58f3f12ac170f080499b3126370a9c28e",
    "common/diplomatic_actions/32_subjects_raise_payments.txt": "7dc051b8613e44d3c5831e0bed185ee042fbd17db20e36f4b0f099e3ecc6a890",
    "common/diplomatic_actions/33_subjects_decrease_payments.txt": "af342203edff8a52b5e265803f372939342e315750d74b4842e7759d1d54c2df",
    "common/diplomatic_actions/34_subjects_exempt_from_service.txt": "ccf74b2d6b2fa89aed685c441c4731e3ccdcec1aca13ea47990bcec543295335",
    "common/diplomatic_actions/38_subjects_increase_autonomy.txt": "78f5829b7d9b32ae93880b890bfb1b1a40d7606b670b29a9e60804c8ab5f989f",
    "common/diplomatic_actions/39_subjects_support_regime.txt": "7fc411abe56a7068b47752d572b20a217e98c8155cc6d8447025ea64a3ea74d7",
    "common/diplomatic_actions/40_subjects_knowledge_sharing.txt": "bbbb6e12e9dea1f48a0e3226b895c3854554b8ed1435ae071f17b2e72a3a102e",
    "common/diplomatic_actions/41_subjects_evangelize.txt": "f6f34c2169b69e35a16370edc56fc2c5d52a49f9f1c8bb510f1f85bb4bc3133a",
    "common/diplomatic_actions/52_nationalism_actions.txt": "6609ecafba7c840685c9716b8a1d414a2043c06ed1f6e79327679b13d9cce9ed",
    "common/diplomatic_actions/diplomatic_action.md": "9f146dd9e108d9753747efb1bf0671a18e19e728f6916a1fcd58c4d0b76fb69c",
    "common/on_actions/00_code_on_actions.txt": "ceebee2c1b4846ba1ad11a78093bb85b619b911c92c414c9f3f8e8bfb6e8510e",
    "common/script_values/building_values.txt": "ad61e13b0762f6c174c091c76f406d4bca1d27fddea94b185eba3139dbcc6cf0",
    "events/iberia_events/negotiation_events.txt": "f738d3fe8d5d828460033d4d4b6b39437021a7f76dc80a2f9e48620a4cccc6ee",
    "common/trigger_localization/00_trigger_localization.txt": "1f2de59b73a1649f5ba37e1ab0824c5b826acf7e538e84d941a7dc18ab88a070",
    "localization/english/triggers_l_english.yml": "26ef51fe5dbab2e5009191087329b54bef84fdf28e68e4c2dc0f0e670b1301d6",
}
DOCUMENTATION = {
    "actor": "# IMPORTANT: In the AI block, the AI country is always root and the other country always scope:target, regardless of who proposed the diplomatic action",
    "score": "propose_score = {} # This determines how much the AI will prioritize proposing this particular deal",
}


def load() -> dict[str, Any]:
    data = tomllib.loads(PARAMETERS.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "sources", "tuning"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or data["sources"] != SOURCE_HASHES
        or set(data["tuning"])
        != {
            "autonomy_need",
            "autonomy_recovery",
            "payments_default",
            "payments_deficit",
            "bloc_default",
            "bloc_deficit",
            "bloc_recovery",
            "knowledge_spread_margin",
            "knowledge_spread_weak",
            "exempt_service_war",
            "sovereignty_default",
            "sovereignty_deficit",
            "sovereignty_recovery",
            "raise_income_need",
            "raise_liberty_risk",
            "raise_liberty_high",
        }
    ):
        raise ValueError("原生外交行动schema或精确来源无效")
    for key, value in data["tuning"].items():
        if type(value) not in {int, float} or not math.isfinite(value):
            raise ValueError("原生外交行动倾向须有限")
        if not (
            1 < value <= 1.2 if key in {"autonomy_need", "raise_income_need"} else 0.8 <= value < 1
        ):
            raise ValueError("原生外交行动需求或成本方向及边界无效")
    if not data["tuning"]["knowledge_spread_weak"] < data["tuning"]["knowledge_spread_margin"]:
        raise ValueError("科技共享传播成本须按同因有序分档")
    if not data["tuning"]["raise_liberty_high"] < data["tuning"]["raise_liberty_risk"]:
        raise ValueError("提高付款的同因目标风险须有序分档")
    return data


def _block(parent: Block, key: str) -> Block:
    rows = parent.all(key)
    if len(rows) != 1 or rows[0].op != "=" or not isinstance(rows[0].value, Block):
        raise ValueError(f"原生外交行动原版结构不唯一：{key}")
    return rows[0].value


def _scalar(parent: Block, key: str, expected: str, op: str = "=") -> None:
    rows = parent.all(key)
    if (
        len(rows) != 1
        or rows[0].op != op
        or not isinstance(rows[0].value, Scalar)
        or rows[0].value.unquoted != expected
    ):
        raise ValueError(f"原生外交行动原版效果或资格漂移：{key}")


def _shape(node: Assignment | Block | Scalar) -> list[Any]:
    if isinstance(node, Scalar):
        return ["scalar", node.text]
    if isinstance(node, Assignment):
        if not isinstance(node.value, (Block, Scalar)):
            raise ValueError("外交完整原版AST缺少值")
        return ["assignment", node.key, node.op, node.prefix, _shape(node.value)]
    return ["block", *(_shape(item) for item in node.items)]


def _verify_batch(identity: str, action: Block) -> None:
    ai = _block(action, "ai")
    _scalar(_block(ai, "propose_score"), "value", "100" if identity == SOVEREIGNTY else "10")
    if len(_block(ai, "propose_score").items) != 1:
        raise ValueError("外交新增提案的完整固定原生评分漂移")
    if identity == EXEMPT:
        _scalar(action, "requires_approval", "no")
        pact = _block(action, "pact")
        _scalar(pact, "cost", "0")
        _scalar(pact, "forced_duration", "12")
        _scalar(pact, "exempt_from_service", "yes")
        _scalar(_block(pact, "second_modifier"), "country_liberty_desire_add", "-0.05")
        _scalar(_block(ai, "evaluation_chance"), "value", "0.25")
    elif identity == SOVEREIGNTY:
        _scalar(action, "requires_approval", "yes")
        _scalar(action, "violates_sovereignty", "yes")
        _scalar(_block(action, "potential"), "is_at_war", "yes")
        for effect, value, joins in (
            ("accept_effect", "15", "yes"),
            ("decline_effect", "10", "no"),
        ):
            body = _block(action, effect)
            _scalar(_block(body, "create_incident"), "value", value)
            joining = _block(_block(body, "scope:target_country"), "violate_sovereignty_join")
            _scalar(joining, "violator", "root")
            _scalar(joining, "target", "scope:target_country")
            _scalar(joining, "join_violator", joins)
    else:
        _scalar(action, "requires_approval", "no")
        pact = _block(action, "pact")
        _scalar(pact, "cost", "25")
        _scalar(pact, "maintenance_paid_by", "first_country")
        _scalar(pact, "income_transfer", "0.1")
        _scalar(pact, "second_country_gets_income_transfer", "no")
        _scalar(pact, "income_transfer_based_on_second_country", "yes")
        _scalar(_block(pact, "second_modifier"), "country_liberty_desire_add", "0.10")
        _scalar(ai, "max_influence_spending_fraction", "0.1")
        target_checks = _block(action, "possible").all("scope:target_country")
        if len(target_checks) != 2 or any(
            not isinstance(row.value, Block) for row in target_checks
        ):
            raise ValueError("提高付款目标资格结构漂移")
        liberty_check, default_check = (row.value for row in target_checks)
        if not isinstance(liberty_check, Block) or not isinstance(default_check, Block):
            raise ValueError("提高付款目标资格缺少数值块")
        _scalar(liberty_check, "liberty_desire", "75", "<")
        _scalar(default_check, "in_default", "no")
        _scalar(_block(ai, "will_propose"), "exists", "scope:target_country")
        # Same exact AI parent: source-specific alias and actual target getter.
        breaks = _block(_block(ai, "will_break"), "OR").all("AND")
        if len(breaks) != 1 or not isinstance(breaks[0].value, Block):
            raise ValueError("提高付款AI终止目标父结构漂移")
        target_rows = breaks[0].value.all("scope:target_country")
        if (
            len(target_rows) != 1
            or target_rows[0].op != "?="
            or not isinstance(target_rows[0].value, Block)
        ):
            raise ValueError("提高付款AI目标alias与可选作用域操作符漂移")
        target = target_rows[0].value
        _scalar(target, "liberty_desire", "50", ">=")


def _verify_knowledge(action: Block) -> None:
    groups = _block(action, "groups").items
    if (
        len(groups) != 2
        or any(not isinstance(item, Scalar) for item in groups)
        or [str(item) for item in groups] != ["power_bloc_leader", "overlord"]
    ):
        raise ValueError("科技共享捐助方角色漂移")
    _scalar(action, "requires_approval", "no")
    pact = _block(action, "pact")
    _scalar(pact, "cost", "50")
    _scalar(pact, "maintenance_paid_by", "first_country")
    _scalar(pact, "forced_duration", "12")
    _scalar(_block(pact, "first_modifier"), "country_tech_spread_mult", "-0.10")
    recipient = _block(pact, "second_modifier")
    _scalar(recipient, "country_tech_spread_mult", "0.25")
    _scalar(recipient, "country_liberty_desire_add", "-0.05")
    ai = _block(action, "ai")
    _scalar(ai, "max_influence_spending_fraction", "0.1")
    _scalar(_block(ai, "evaluation_chance"), "value", "0.25")
    score = _block(ai, "propose_score")
    _scalar(score, "value", "1")
    rank = _block(score, "add")
    _scalar(rank, "value", "scope:target_country.country_rank")
    _scalar(rank, "multiply", "1")
    _scalar(_block(ai, "will_propose"), "modifier:country_tech_spread_mult", "-0.25", ">")
    _scalar(
        _block(_block(ai, "will_break"), "OR"), "modifier:country_tech_spread_mult", "-0.5", "<="
    )
    _block(ai, "accept_score")


def verify_inputs(inputs: Mapping[str, str]) -> None:
    """Require full normalized installed sources, then prove exact role and effects."""
    data = load()
    for source, expected in data["sources"].items():
        text = inputs.get(source)
        if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != expected:
            raise ValueError(f"原生外交行动完整原版来源漂移：{source}")
    for statement in DOCUMENTATION.values():
        if sum(line.strip() == statement for line in inputs[README].splitlines()) != 1:
            raise ValueError("原生外交行动README的AI ROOT/提案优先单位合同漂移")
    roots = {}
    for source, text in inputs.items():
        if source not in SOURCE_HASHES or not source.endswith(".txt"):
            continue
        parsed = parse_text(text, path=source)
        if parsed.errors:
            raise ValueError(f"外交冻结完整原版解析失败：{source}")
        roots[source] = parsed.root
    for identity, expected in _snapshot()["contracts"].items():
        source, definition = identity.split("#", 1)
        if source not in roots or _shape(_block(roots[source], definition)) != expected:
            raise ValueError(f"外交冻结完整父结构漂移：{identity}")
    for statement in (
        'TRIGGER_NET_TOTAL_INCOME: "Weekly total income after expenses is $COMPARATOR$ @money!$NUM|vK$ (Currently @money!$CURRENT_VALUE|vK$)"',
        'TRIGGER_LIBERTY_DESIRE: "[concept_liberty_desire] is $COMPARATOR$ $NUM|v0$"',
    ):
        if sum(line.strip() == statement for line in inputs[TRIGGER_UNITS].splitlines()) != 1:
            raise ValueError("外交读数单位与真实国家量级证据漂移")
    for identity, (source, cost, fraction) in CAPACITY_CANDIDATES.items():
        action = _block(roots[source], identity)
        _scalar(_block(action, "pact"), "cost", cost)
        _scalar(_block(action, "ai"), "max_influence_spending_fraction", fraction)
    lost = _block(_block(_block(roots[ON_ACTIONS], "on_lost_war"), "effect"), "if")
    remembered = _block(lost, "set_variable")
    _scalar(remembered, "name", "recently_lost_war")
    _scalar(remembered, "days", "1825")
    _scalar(remembered, "value", "yes")
    for identity, source in CANDIDATES.items():
        parsed = parse_text(inputs[source])
        if parsed.errors:
            raise ValueError("原生外交行动完整源解析失败")
        action = _block(parsed.root, identity)
        if identity in BATCH_CANDIDATES:
            _verify_batch(identity, action)
            continue
        if identity == KNOWLEDGE:
            _verify_knowledge(action)
            continue
        group = {
            "da_increase_autonomy_of_self": "subject",
            "decrease_payments": "overlord",
            "join_power_bloc": "general",
        }[identity]
        values = _block(action, "groups").items
        if len(values) != 1 or not isinstance(values[0], Scalar) or values[0].unquoted != group:
            raise ValueError("原生外交行动提议方宗属角色漂移")
        ai = _block(action, "ai")
        score = _block(ai, "propose_score")
        _scalar(score, "value", {"subject": "100", "overlord": "10", "general": "20"}[group])
        will_propose = _block(ai, "will_propose")
        _scalar(_block(ai, "evaluation_chance"), "value", "0.01" if group == "general" else "0.25")
        if group == "subject":
            _scalar(action, "requires_approval", "yes")
            _scalar(_block(action, "potential"), "is_subject", "yes")
            _scalar(_block(action, "possible"), "liberty_desire", "75", ">=")
            for effect, amount in (("accept_effect", "-20"), ("decline_effect", "-30")):
                body = _block(action, effect)
                relations = _block(_block(body, "scope:target_country"), "change_relations")
                _scalar(relations, "country", "root")
                _scalar(relations, "value", amount)
            _block(ai, "accept_score")
        elif group == "overlord":
            _scalar(action, "requires_approval", "no")
            pact = _block(action, "pact")
            _scalar(pact, "income_transfer", "-0.1")
            _scalar(pact, "second_country_gets_income_transfer", "no")
            _scalar(pact, "income_transfer_based_on_second_country", "yes")
            _scalar(_block(pact, "second_modifier"), "country_liberty_desire_add", "-0.05")
        else:
            _scalar(action, "requires_approval", "yes")
            _scalar(_block(action, "accept_effect"), "join_power_bloc", "scope:target_country")
            relations = _block(_block(action, "decline_effect"), "change_relations")
            _scalar(relations, "country", "scope:target_country")
            _scalar(relations, "value", "-20")
            acceptance = _block(will_propose, "would_accept_diplomatic_action")
            _scalar(acceptance, "actor", "scope:target_country")
            _scalar(acceptance, "type", "invite_to_power_bloc")
            _block(ai, "accept_score")


def _snapshot() -> dict[str, Any]:
    raw = FROZEN.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FROZEN_SHA256:
        raise ValueError("原生外交行动冻结完整源身份漂移")
    data: dict[str, Any] = json.loads(raw)
    if (
        set(data) != {"schema", "encoding", "sources", "raw_sources", "texts", "contracts"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or data["encoding"] != "utf8_without_bom_lf_preserve_whitespace"
        or data["sources"] != load()["sources"]
        or set(data["texts"]) != set(data["sources"])
        or set(data["raw_sources"]) != set(data["sources"])
    ):
        raise ValueError("原生外交行动冻结完整源schema无效")
    return data


def load_baseline() -> dict[str, Any]:
    data = _snapshot()
    verify_inputs(data["texts"])
    return data


def consumer_catalog() -> dict[str, dict[str, Any]]:
    """Exact proposal roles; only raise-payments proves its target-country alias."""
    data = load_baseline()
    lines = data["texts"][README].splitlines()
    evidence = {
        key: next(index + 1 for index, line in enumerate(lines) if line.strip() == statement)
        for key, statement in DOCUMENTATION.items()
    }
    return {
        identity: {
            "source": source,
            "field": f"{identity}.ai.propose_score",
            "native_root": "country",
            "actor": "root",
            "actor_path": [],
            "native_unit": "score",
            "operation": "multiply",
            "scope_evidence": README,
            "scope_evidence_sha256": data["sources"][README],
            "scope_evidence_line": evidence["actor"],
            "score_evidence_line": evidence["score"],
            "source_sha256": data["sources"][source],
            "target_binding": "target_country_exact_raise_parent"
            if identity == RAISE
            else "unsupported_not_consumed",
            **(
                {
                    "target_evidence": source,
                    "target_evidence_line": _block(
                        _block(_block(parse_text(data["texts"][source]).root, identity), "ai"),
                        "will_propose",
                    )
                    .all("exists")[0]
                    .line,
                }
                if identity == RAISE
                else {}
            ),
        }
        for identity, source in CANDIDATES.items()
    }


def batch_evaluation_context(source: str, field: str) -> EvaluationContext:
    """Only raise-payments grants its observed same-parent target-country alias."""
    from .situated.decision_ir import ContextBinding, EvaluationContext  # noqa: PLC0415

    rows = consumer_catalog()
    identity = field.split(".", 1)[0]
    row = rows.get(identity)
    if (
        identity not in BATCH_CANDIDATES
        or row is None
        or (row["source"], row["field"]) != (source, field)
    ):
        raise ValueError("外交批次只授权三个精确提案消费者")
    actor = ContextBinding("root", "country", "actor", README, row["scope_evidence_line"])
    targets = (
        (
            ContextBinding(
                "target_country", "country", "target", source, row["target_evidence_line"]
            ),
        )
        if identity == RAISE
        else ()
    )
    return EvaluationContext(
        actor_scope=actor,
        targets=targets,
        evidence=(
            f"{README}:{actor.line}",
            f"{README}:{row['score_evidence_line']}",
            f"{source}:sha256={row['source_sha256']}",
            *(f"{target.source}:{target.line}" for target in targets),
        ),
    )


def validate_batch_policy(policy: RuleSet, source: str) -> None:
    """Exact optional integration guard, with no generic alias authorization."""
    from .decision_rules import Reader  # noqa: PLC0415

    identity = next((key for key, value in BATCH_CANDIDATES.items() if value == source), None)
    allowed = {
        EXEMPT: {"war"},
        SOVEREIGNTY: {"default", "net_surplus", "war_defeat", "cost_country_population"},
        RAISE: {"net_surplus", "raise_target_liberty", "raise_target_population"},
    }
    if identity is None or policy.actor_path or policy.native_root != "country":
        raise ValueError("外交批次偏离精确ROOT/source合同")
    for reader in policy.readers:
        spec = BATCH_READERS.get(reader.key)
        if (
            reader.key not in allowed[identity]
            or spec is None
            or reader != Reader(key=reader.key, **spec)
        ):
            raise ValueError("外交批次reader偏离完整身份或精确目标合同")
    for rule in policy.rules:
        if (
            rule.field != (identity, "ai", "propose_score")
            or rule.operation != "multiply"
            or rule.domain != "diplomacy"
            or rule.semantic_role not in {"cost", "benefit"}
            or not (
                0.8 <= rule.value < 1
                if rule.semantic_role == "cost"
                else identity == RAISE and 1 < rule.value <= 1.2
            )
        ):
            raise ValueError("外交批次偏离精确评分与成本/收益边界")


def derive(adapters: Mapping[str, Any]) -> dict[str, Any]:
    data = load()
    catalog = consumer_catalog()

    def c(fact: str, op: str, value: object) -> dict[str, object]:
        return {"fact": fact, "op": op, "value": value}

    rows = (
        (
            "da_increase_autonomy_of_self",
            "autonomy_need",
            "autonomy_need",
            "benefit",
            [c("liberty", ">=", 90)],
        ),
        (
            "da_increase_autonomy_of_self",
            "autonomy_recovery",
            "autonomy_recovery",
            "cost",
            [c("war_defeat", "=", True)],
        ),
        (
            "decrease_payments",
            "payments_default",
            "payments_financing",
            "cost",
            [c("default", "=", True)],
        ),
        (
            "decrease_payments",
            "payments_deficit",
            "payments_financing",
            "cost",
            [c("net_surplus", "<", 0)],
        ),
        (
            "join_power_bloc",
            "bloc_default",
            "bloc_membership_financing",
            "cost",
            [c("default", "=", True)],
        ),
        (
            "join_power_bloc",
            "bloc_deficit",
            "bloc_membership_financing",
            "cost",
            [c("net_surplus", "<", 0)],
        ),
        (
            "join_power_bloc",
            "bloc_recovery",
            "bloc_membership_recovery",
            "cost",
            [c("war_defeat", "=", True)],
        ),
        (
            KNOWLEDGE,
            "knowledge_spread_margin",
            "knowledge_sharing_donor_spread",
            "cost",
            [c("knowledge_donor_spread", "<", 0.10)],
        ),
        (
            KNOWLEDGE,
            "knowledge_spread_weak",
            "knowledge_sharing_donor_spread",
            "cost",
            [c("knowledge_donor_spread", "<", 0)],
        ),
        (
            EXEMPT,
            "exempt_service_war",
            "exempt_service_existing_war",
            "cost",
            [c("war", "=", True)],
        ),
        (
            SOVEREIGNTY,
            "sovereignty_default",
            "sovereignty_escalation_financing",
            "cost",
            [c("default", "=", True)],
        ),
        (
            SOVEREIGNTY,
            "sovereignty_deficit",
            "sovereignty_escalation_financing",
            "cost",
            [c("net_surplus", "<", 0)],
        ),
        (
            SOVEREIGNTY,
            "sovereignty_recovery",
            "sovereignty_observed_defeat_recovery",
            "cost",
            [c("war_defeat", "=", True)],
        ),
        (
            RAISE,
            "raise_income_need",
            "raise_payments_actor_income_need",
            "benefit",
            [c("net_surplus", "<", 0)],
        ),
        (
            RAISE,
            "raise_liberty_risk",
            "raise_payments_target_instability",
            "cost",
            [c("raise_target_liberty", ">=", 50)],
        ),
        (
            RAISE,
            "raise_liberty_high",
            "raise_payments_target_instability",
            "cost",
            [c("raise_target_liberty", ">=", 65)],
        ),
    )
    rules = []
    for index, (identity, name, cause, role, conditions) in enumerate(rows):
        reasons = {
            EXEMPT: "原版协议真实免除目标军役且强制至少12个月；本国已在战争时，放弃已有可征召关系具有有限机会成本，既有目标军力比较、自由欲望收益与cost0保留，不推算目标实际可派军队。",
            SOVEREIGNTY: "原版侵犯主权接受造成15incident，拒绝也造成10并调用真实参战效果；已观察违约/净收入赤字表示增量升级的同因融资压力，原版败战记忆的恢复成本独立联合，不以已战争资格再惩罚同一战争需求。",
            RAISE: "本国实际net_total_income赤字增加抽取收入的有限需求；同一合法目标自由欲望50至75区间对持续+0.10自由欲望形成独立可持续风险，65以上同因升档。目标违约及>=75已由原资格排除，25影响力配额不重复；不将10%抽取率当作已知税基或英镑收益。",
            KNOWLEDGE: "捐助方实际country_tech_spread_mult余量与原协议-0.10传播修正形成有限机会成本；低于0.10为有限余量、低于0为较弱传播同因升档，不估算科研量或复制影响力配额；目标rank收益、原资格与执行保持原版",
            "da_increase_autonomy_of_self": "本国高自主愿望提高和平自主交涉需求；近期败战恢复期对原版接受或拒绝均有的关系摩擦设置温和风险，独立联合，不视为战争",
            "decrease_payments": "宗主主动减少付款会降低本国抽取收入；本国违约或实际净收入赤字形成让利财政成本，同一融资原因取强",
            "join_power_bloc": "加入新势力集团是本国新增外部成员承诺；违约与实际净收入赤字同因择强，近期败战恢复的机会成本独立联合。仅温和调整提案优先级，不推断固定会费、军事义务或直接付款；原版杠杆、凝聚、态度、恶名和关系收益完整保留",
        }
        rules.append(
            {
                "id": f"native_action_{name}",
                "source": catalog[identity]["source"],
                "field": catalog[identity]["field"],
                "domain": "diplomacy",
                "priority": 79000 + index,
                "operation": "multiply",
                "value": data["tuning"][name],
                "semantic_role": role,
                "contribution_group": cause,
                "conditions": conditions,
                "why": reasons[identity],
                "counterexample": "仅精确propose_score；原版目标资格、will_propose、概率、接受/拒绝、冷却、付款和执行完整保留。未知身份或败战撤相关项；融资压力未知只按有本国实体锚的生产成本合同保留有限档，正常低债借款不罚；不读未证明target_country别名、不改变双方身份、不强制执行。",
            }
        )
        if identity == KNOWLEDGE:
            rules[-1].update(
                conservative_unknown_facts=["knowledge_donor_spread"],
                unknown_cost_required_known_facts=["knowledge_donor_population"],
                unknown_cost_basis="完整原版first_modifier已证明本次捐助实际-0.10传播代价；ROOT传播余量未知但本国实体可读时保留有限较弱传播档，不推定传播健康或免费；未知实体不推定承诺可用。",
                counterexample="仅精确捐助方ROOT提案；同因成本择强，未知传播保留有本国实体锚的有限档，不读target/owner，不估算研究产量或上限，不复写原>-0.25资格、50影响力和0.1配额；目标rank及完整协议/接受/执行/时间尾部不变。",
            )
        elif identity == SOVEREIGNTY and name != "sovereignty_recovery":
            rules[-1].update(
                conservative_unknown_facts=[
                    "default" if name == "sovereignty_default" else "net_surplus"
                ],
                unknown_cost_required_known_facts=["cost_country_population"],
                unknown_cost_basis="完整原版已证新增incident和升级执行；融资观察未知且本国实体已知时保留有限风险，不推定违约或战争结果；二者皆未知只撤该分量。",
            )
        elif identity == RAISE and name == "raise_liberty_high":
            rules[-1].update(
                conservative_unknown_facts=["raise_target_liberty"],
                unknown_cost_required_known_facts=["raise_target_population"],
                unknown_cost_basis="精确AI父结构与原版目标税收抽取/自由欲望持续增加已证；目标实体已知但自由欲望未知时保留有限强风险档，不推定目标稳定；目标实体也未知时只撤目标风险，已知本国需求继续。",
            )
        if identity in BATCH_CANDIDATES:
            rules[-1]["counterexample"] = (
                "仅精确本国propose_score的唯一程序；原资格、目标、接受/拒绝、实际效果、原变量/扫描/零与尾部、玩家及关闭不变。免军役战争与败战记忆须实际已观察；主权融资未知仅有本国实体锚时有限保守。提高付款只读该父AI已证target_country，目标自由欲望未知仅目标实体锚已知时保留成本，不读scope:target/owner替身；已知风险不依赖额外人口读数，恢复后局部退出，收入需求不清除独立目标风险。"
            )
    used = {condition["fact"] for rule in rules for condition in rule["conditions"]}
    used.update(key for rule in rules for key in rule.get("unknown_cost_required_known_facts", ()))
    available = dict(adapters["readers"])
    for key, spec in KNOWLEDGE_READERS.items():
        if key in available and available[key] != spec:
            raise ValueError("科技共享精确ROOT读取器身份漂移")
        available[key] = dict(spec)
    for key, spec in BATCH_READERS.items():
        if key in available and available[key] != spec:
            raise ValueError(f"外交新增提案读取器完整身份冲突：{key}")
        available[key] = dict(spec)
    readers = {key: available[key] for key in sorted(used)}
    if any(
        (
            reader["scope"] != "root"
            and key not in {"raise_target_liberty", "raise_target_population"}
        )
        or reader.get("path")
        for key, reader in readers.items()
    ):
        raise ValueError("原生外交行动只允许已证明本国ROOT观测")
    return {
        "sources": dict(data["sources"]),
        "readers": readers,
        "rules": rules,
        "covered": [
            {"id": identity, "source": row["source"], "field": row["field"]}
            for identity, row in catalog.items()
        ],
    }
