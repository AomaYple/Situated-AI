"""Country ROOT tradeoffs for exact native diplomatic proposal scores."""

from __future__ import annotations

import hashlib
import json
import math
import tomllib
from typing import TYPE_CHECKING, Any

from . import config
from .model import Block, Scalar
from .parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Mapping

PARAMETERS = config.REPO / "mod/decisions/native_action_opportunities.toml"
FROZEN = config.REPO / "research/vanilla-ai/1.14.5/native-action-opportunities.json"
FROZEN_SHA256 = "4ff80d1ff31b3e92c19130abeab3bb746ff45c8ac9c2f1c5498a86c9f7bfc928"
README = "common/diplomatic_actions/diplomatic_action.md"
KNOWLEDGE = "da_knowledge_sharing"
KNOWLEDGE_SOURCE = "common/diplomatic_actions/40_subjects_knowledge_sharing.txt"
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
    KNOWLEDGE: KNOWLEDGE_SOURCE,
    "da_increase_autonomy_of_self": "common/diplomatic_actions/38_subjects_increase_autonomy.txt",
    "decrease_payments": "common/diplomatic_actions/33_subjects_decrease_payments.txt",
    "join_power_bloc": "common/diplomatic_actions/26_join_power_bloc.txt",
}
SOURCE_HASHES = {
    KNOWLEDGE_SOURCE: "0e8d089a62180b570dfba7b1bb644238fa3dab6f936d12af9f21b5cedcc5afcd",
    README: "9f146dd9e108d9753747efb1bf0671a18e19e728f6916a1fcd58c4d0b76fb69c",
    CANDIDATES[
        "da_increase_autonomy_of_self"
    ]: "533689cd0cb50a664fc7c9b35a9b7ee125080aae27d12c60e2060fbdaa786a0c",
    CANDIDATES[
        "decrease_payments"
    ]: "af342203edff8a52b5e265803f372939342e315750d74b4842e7759d1d54c2df",
    CANDIDATES[
        "join_power_bloc"
    ]: "a66a61d5ee5a86282cec8f09b38bd0e58f3f12ac170f080499b3126370a9c28e",
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
        }
    ):
        raise ValueError("原生外交行动schema或精确来源无效")
    for key, value in data["tuning"].items():
        if type(value) not in {int, float} or not math.isfinite(value):
            raise ValueError("原生外交行动倾向须有限")
        if not (1 < value <= 1.2 if key == "autonomy_need" else 0.8 <= value < 1):
            raise ValueError("原生外交行动需求或成本方向及边界无效")
    if not data["tuning"]["knowledge_spread_weak"] < data["tuning"]["knowledge_spread_margin"]:
        raise ValueError("科技共享传播成本须按同因有序分档")
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
    for identity, source in CANDIDATES.items():
        parsed = parse_text(inputs[source])
        if parsed.errors:
            raise ValueError("原生外交行动完整源解析失败")
        action = _block(parsed.root, identity)
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


def load_baseline() -> dict[str, Any]:
    raw = FROZEN.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FROZEN_SHA256:
        raise ValueError("原生外交行动冻结完整源身份漂移")
    data: dict[str, Any] = json.loads(raw)
    if (
        set(data) != {"schema", "encoding", "sources", "texts"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or data["encoding"] != "utf8_without_bom_lf_preserve_whitespace"
        or data["sources"] != load()["sources"]
        or set(data["texts"]) != set(data["sources"])
    ):
        raise ValueError("原生外交行动冻结完整源schema无效")
    verify_inputs(data["texts"])
    return data


def consumer_catalog() -> dict[str, dict[str, Any]]:
    """Exact country proposal roles; no target alias or acceptance authorization."""
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
            "target_binding": "unsupported_not_consumed",
        }
        for identity, source in CANDIDATES.items()
    }


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
    )
    rules = []
    for index, (identity, name, cause, role, conditions) in enumerate(rows):
        reasons = {
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
    used = {condition["fact"] for rule in rules for condition in rule["conditions"]}
    used.update(key for rule in rules for key in rule.get("unknown_cost_required_known_facts", ()))
    available = dict(adapters["readers"])
    for key, spec in KNOWLEDGE_READERS.items():
        if key in available and available[key] != spec:
            raise ValueError("科技共享精确ROOT读取器身份漂移")
        available[key] = dict(spec)
    readers = {key: available[key] for key in sorted(used)}
    if any(reader["scope"] != "root" or reader.get("path") for reader in readers.values()):
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
