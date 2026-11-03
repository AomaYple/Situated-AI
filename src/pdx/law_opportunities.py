"""Finite legal transitions: observed agendas, actual effects and independent costs.

The module derives preferences, not tax-revenue predictions. It never reads an
installation while loading a policy; production verifies the supplied locked
native inputs separately. Legal eligibility, political support, enactment and
all native modifiers remain owned by the original consumer.
"""

from __future__ import annotations

import hashlib
import math
import re
import tomllib
from typing import TYPE_CHECKING, Any

from . import config
from .model import Block
from .parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Mapping

PARAMETERS = config.REPO / "mod/decisions/law_opportunities.toml"


def load() -> dict[str, Any]:
    data = tomllib.loads(PARAMETERS.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "tuning", "sources", "candidates"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
    ):
        raise ValueError("具体法律机会schema无效")
    expected = {
        "agenda_base",
        "agenda_strong",
        "crisis_cost",
        "trade_base",
        "trade_strong",
        "administration_change",
    }
    if set(data["tuning"]) != expected:
        raise ValueError("具体法律机会参数集合无效")
    tuning = data["tuning"]
    if any(
        type(value) not in {int, float} or not math.isfinite(value) for value in tuning.values()
    ):
        raise ValueError("具体法律机会参数必须为有限数值")
    if not (
        0 < tuning["agenda_base"] <= tuning["agenda_strong"] <= 15
        and 0 < tuning["trade_base"] <= tuning["trade_strong"] <= 20
        and -16 <= tuning["crisis_cost"] < 0
        and 0 < tuning["administration_change"] <= 10
    ):
        raise ValueError("具体法律机会参数越界")
    if len(data["sources"]) != 6 or len(data["candidates"]) != 37:
        raise ValueError("具体法律机会必须保留六族37候选独立分母")
    if set(data["candidates"].values()) != set(data["sources"]):
        raise ValueError("具体法律候选与锁定原版来源不一致")
    if any(not re.fullmatch(r"law_[a-z_]+", law) for law in data["candidates"]):
        raise ValueError("具体法律候选身份无效")
    return data


def verify_inputs(inputs: Mapping[str, str]) -> None:
    """Prove complete native consumer identities, not just discovered words."""
    data = load()
    found = {}
    for source, digest in data["sources"].items():
        text = inputs.get(source)
        if text is None or hashlib.sha256(text.encode("utf-8")).hexdigest() != digest:
            raise ValueError(f"具体法律机会原版来源漂移：{source}")
        parsed = parse_text(text)
        if parsed.errors:
            raise ValueError(f"具体法律机会原版无法解析：{source}")
        for definition in parsed.root.assignments():
            if not isinstance(definition.value, Block):
                continue
            fields = definition.value.all("ai_enact_weight_modifier")
            if not fields:
                continue
            if (
                definition.key in found
                or len(fields) != 1
                or fields[0].op != "="
                or not isinstance(fields[0].value, Block)
            ):
                raise ValueError("具体法律机会原版消费者重复或形状漂移")
            found[definition.key] = source
    if found != data["candidates"]:
        raise ValueError("具体法律机会原版独立候选分母漂移")


def _condition(fact: str, op: str, value: object) -> dict[str, object]:
    return {"fact": fact, "op": op, "value": value}


def derive(adapters: Mapping[str, Any]) -> dict[str, Any]:
    data = load()
    tuning = data["tuning"]
    readers: dict[str, Any] = {}
    rules: list[dict[str, Any]] = []
    readers["law_context_coal_balance"] = {
        **adapters["readers"]["tools_balance"],
        "path": ["market", "mg:coal"],
    }

    def current(law: str) -> str:
        key = f"law_context_current_{law}"
        readers[key] = {
            "engine": "has_law_or_variant",
            "scope": "root",
            "kind": "boolean",
            "unit": "boolean",
            "argument": f"law_type:{law}",
        }
        return key

    def add(
        law: str,
        suffix: str,
        group: str,
        value: float,
        conditions: list[dict[str, object]],
        why: str,
        *,
        domain: str = "political",
    ) -> None:
        rules.append(
            {
                "id": f"law_context_{law}_{suffix}",
                "source": data["candidates"][law],
                "field": f"{law}.ai_enact_weight_modifier",
                "domain": domain,
                "priority": 44000 + len(rules),
                "operation": "add",
                "value": value,
                "contribution_group": group,
                "conditions": conditions,
                "why": why,
                "counterexample": "候选只得到有界偏好；未知分量局部退出，原版资格、支持、成本、概率与执行不变；不预测未观察的税基、收入、移民或利润",
            }
        )

    for law in data["candidates"]:
        for tier, threshold in (("base", "0.1"), ("strong", "0.25")):
            fact = f"law_context_{law}_movement_{tier}"
            readers[fact] = {
                "engine": "any_political_movement",
                "scope": "root",
                "kind": "boolean",
                "unit": "boolean",
                "parameters": {"law": law, "minimum_support": threshold},
            }
            add(
                law,
                f"agenda_{tier}",
                "law_observed_agenda",
                tuning[f"agenda_{tier}"],
                [_condition(fact, "=", True)],
                "本国真实政治运动明确支持这个具体法律候选，按已知支持档回应国内诉求；不将政治诉求冒充税收或国力净收益",
            )
        add(
            law,
            "crisis_cost",
            "law_political_pressure",
            tuning["crisis_cost"],
            [
                _condition("legitimacy", "<", 25),
                _condition("insurrection", "=", True),
                _condition("radical_share", ">=", 0.25),
            ],
            "已知低合法性、叛乱性利益集团与高激进化共同形成额外立法议程风险，独立于本候选的已知需求",
        )

    # Moving away from consumption taxation loses its explicit population
    # administration discount. No wage/dividend/poll/land tax base is invented.
    consumption = "law_consumption_based_taxation"
    for law, source in data["candidates"].items():
        if not source.endswith("/01_taxation.txt"):
            continue
        if law == consumption:
            conditions = [
                _condition(current(consumption), "=", False),
                _condition("bureaucracy", "<", 0),
            ]
            value = tuning["administration_change"]
            why = "消费税法实际减少人口基础行政负担，行政短缺时形成有限节省机会；不宣称总税收增加"
        else:
            conditions = [
                _condition(current(consumption), "=", True),
                _condition("bureaucracy", "<", 0),
            ]
            value = -tuning["administration_change"]
            why = "离开消费税法会失去人口基础行政折扣，实际行政短缺时计入转换成本；贷款不证明新税法增收"
        add(
            law,
            "administration_transition",
            "law_tax_administration_transition",
            value,
            conditions,
            why,
            domain="fiscal",
        )

    # Imported goods are an option, not an already completed trade route.
    for law, origins in (
        ("law_free_trade", ("law_isolationism", "law_mercantilism", "law_protectionism")),
        ("law_protectionism", ("law_isolationism", "law_mercantilism")),
    ):
        for origin in origins:
            for good in ("grain", "tools"):
                for tier in ("base", "strong"):
                    conditions = [
                        _condition(current(origin), "=", True),
                        _condition(f"{good}_balance", "<", 0),
                    ]
                    if tier == "strong":
                        conditions.append(_condition(f"{good}_price", ">", 0.25))
                    add(
                        law,
                        f"{origin}_{good}_{tier}",
                        "law_trade_access_option",
                        tuning[f"trade_{tier}"],
                        conditions,
                        "当前贸易制度到该候选实际改善进口准入或进口优势，响应已观察商品缺口；高价只升级同因，不把战争、借款或低识字作开放总门",
                        domain="market",
                    )

    for law in ("law_tenant_farmers", "law_homesteading", "law_peasant_proprietorship"):
        rural_origins = (
            ("law_serfdom",)
            if law == "law_tenant_farmers"
            else ("law_serfdom", "law_tenant_farmers")
        )
        for origin in rural_origins:
            add(
                law,
                f"{origin}_rural_transition",
                "law_rural_transition",
                12,
                [
                    _condition(current(origin), "=", True),
                    _condition("peasant_share", ">=", 0.6),
                ],
                "当前农奴或佃农制度存在显著农村人口约束；候选实际减少土地就业或迁移限制，保留原版变体与地理资格；不承诺迁移已发生",
            )

    intervention = "law_interventionism"
    for good in ("tools", "iron", "coal"):
        balance = "law_context_coal_balance" if good == "coal" else f"{good}_balance"
        add(
            intervention,
            f"{good}_productive_option",
            "law_productive_constraint_relief",
            10,
            [
                _condition(current("law_traditionalism"), "=", True),
                _condition(balance, "<", 0),
            ],
            "从传统主义转换实际移除投资效率和本地价格传导惩罚，响应具体生产瓶颈；不同商品是同一制度机会，不能无限叠加",
            domain="economy",
        )
    add(
        intervention,
        "tax_capacity_relief",
        "law_tax_capacity_relief",
        6,
        [
            _condition(current("law_traditionalism"), "=", True),
            _condition("owned_incorporated_tax_shortfall", "=", True),
        ],
        "从传统主义转换移除州税容量惩罚，响应同一已整合州真实税容不足；不是全国官僚余额的同义词",
        domain="fiscal",
    )
    add(
        intervention,
        "population_administration_loss",
        "law_population_administration",
        -6,
        [
            _condition(current("law_traditionalism"), "=", True),
            _condition("bureaucracy", "<", 0),
        ],
        "离开传统主义失去人口基础行政折扣，已有行政缺口独立计入，不能被生产需求奖励覆盖",
        domain="fiscal",
    )

    used = {condition["fact"] for rule in rules for condition in rule["conditions"]}
    for key in sorted(used - readers.keys()):
        if key not in adapters["readers"]:
            raise ValueError(f"具体法律机会缺少已证明读取器：{key}")
        readers[key] = adapters["readers"][key]
    return {
        "sources": dict(data["sources"]),
        "readers": readers,
        "rules": rules,
        "covered": [
            {"id": law, "source": source, "field": f"{law}.ai_enact_weight_modifier"}
            for law, source in data["candidates"].items()
        ],
    }
