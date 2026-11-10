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

from . import config, version_contracts
from .model import Block, Scalar
from .parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Mapping

PARAMETERS = config.REPO / "mod/decisions/law_opportunities.toml"

SOURCE_HASHES_115 = {
    "common/laws/01_policing.txt": "ce9b5e661196a0ff4dbca693f05a23709958d281ffaa8cadb0995786f575dc4e",
    "common/laws/00_citizenship.txt": "fe6fc8a3e716ae19181df9c6c71ff44b317a837874db8fbc124f077024c20e76",
    "common/laws/00_church_and_state.txt": "1483d4e2aa2a42ec0e13bf843b8d4d5941553796787f0bcb5d78cdd2aab78d50",
    "common/laws/01_taxation.txt": "1f4b3d25b80277a43eacf7f7640dbcb7f0a24b35e107f7bb3baa5364c5ffdbae",
    "common/laws/01_trade_policy.txt": "1746b95df101101845abbcfd5b56306ec9646891302ce09b0895e453f4cac5f3",
    "common/laws/02_labour_associations.txt": "5b50400f5e9be0d70a75f1b13c902ee817384473c64ab12bf52935ea98cf23b5",
    "common/laws/02_migration.txt": "1ac367f9983e9542ee68a27c188f35669b0101cc2df6014c7499f1a5365b54a5",
    "common/laws/01_land_reform.txt": "dfb2105060dab608a938c8e40be82ced1c7717d5a975e3204247c8180ebc8174",
    "common/laws/01_economic_system.txt": "ccc2a84f1776e08a65fc105f0143bcac7f2f2b782523ddca48877f187d54b194",
}

_NATIVE_RETAINED_115 = {
    "law_official_nationality": "common/laws/00_citizenship.txt",
    "law_caesaropapism": "common/laws/00_church_and_state.txt",
}


def native_retained_candidates() -> dict[str, str]:
    """Additional 1.15 consumers are counted and retain their entire native policy."""
    return dict(_NATIVE_RETAINED_115) if version_contracts.active_version() == "1.15.0" else {}


# Exact modifier values in the complete hash-locked labour source. Omitted
# modifier keys have zero contribution; guild qualifications are not reused.
LABOUR_EFFECTS = {
    "law_guild_system": (0.0, 0.0),
    "law_combination_acts": (0.25, -0.25),
    "law_anti_strike_laws": (0.10, -0.10),
    "law_right_to_associate": (-0.10, 0.10),
    "law_corporatized_unions": (0.0, 0.0),
    "law_factory_councils": (0.0, 0.25),
}
AUTHORITY_EFFECTS = {
    "common/laws/00_citizenship.txt": {
        "law_subjecthood": 100,  # Current origin only: no native score field.
        "law_ethnostate": 200,
        "law_national_supremacy": 150,
        "law_racial_segregation": 100,
        "law_cultural_exclusion": 50,
        "law_multicultural": 0,
    },
    "common/laws/00_church_and_state.txt": {
        "law_state_religion": 200,
        "law_millet_system": 200,
        "law_people_of_the_book": 200,
        "law_freedom_of_conscience": 100,
        "law_total_separation": 0,
        "law_state_atheism": 200,
    },
}
POLICING_SOURCE = "common/laws/01_policing.txt"
# Per invested institution level: turmoil losses, movement radicalization,
# and turmoil mortality. Shared dedicated/militarized effects subtract to zero.
POLICING_EFFECTS = {
    "law_no_police": (0.0, 0.0, 0.0),
    "law_local_police": (-0.05, 0.0, 0.0),
    "law_dedicated_police": (0.0, -0.05, 0.0),
    "law_militarized_police": (0.0, -0.05, 0.004),
}


def load() -> dict[str, Any]:
    data = tomllib.loads(PARAMETERS.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "tuning", "sources", "candidates"}
        or type(data["schema"]) is not int
        or data["schema"] != 3
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
    if len(data["sources"]) != 9 or len(data["candidates"]) != 52:
        raise ValueError("具体法律机会必须保留原37候选并扩展公民权5、宗教6及警务4候选")
    if {law for law, name in data["candidates"].items() if name == POLICING_SOURCE} != set(
        POLICING_EFFECTS
    ):
        raise ValueError("警务法律必须保留四个精确原版评分消费者")
    for source, effects in AUTHORITY_EFFECTS.items():
        expected_laws = set(effects) - {"law_subjecthood"}
        if {law for law, name in data["candidates"].items() if name == source} != expected_laws:
            raise ValueError("身份及宗教法律必须保留精确原版评分消费者分母")
    if set(data["candidates"].values()) != set(data["sources"]):
        raise ValueError("具体法律候选与锁定原版来源不一致")
    if any(not re.fullmatch(r"law_[a-z_]+", law) for law in data["candidates"]):
        raise ValueError("具体法律候选身份无效")
    if version_contracts.active_version() == "1.15.0":
        data["sources"] = dict(SOURCE_HASHES_115)
    return data


def verify_inputs(inputs: Mapping[str, str]) -> None:
    """Prove complete native consumer identities, not just discovered words."""
    data = load()
    found = {}
    roots = {}
    for source, digest in data["sources"].items():
        text = inputs.get(source)
        if text is None or hashlib.sha256(text.encode("utf-8")).hexdigest() != digest:
            raise ValueError(f"具体法律机会原版来源漂移：{source}")
        parsed = parse_text(text)
        if parsed.errors:
            raise ValueError(f"具体法律机会原版无法解析：{source}")
        roots[source] = parsed.root
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
    if found != {**data["candidates"], **native_retained_candidates()}:
        raise ValueError("具体法律机会原版独立候选分母漂移")
    _verify_mechanisms(roots)


def _verify_mechanisms(roots: Mapping[str, Block]) -> None:
    """Reprove each numeric mechanism used by the migrated transition rules."""

    def value(source: str, law: str, channel: str, key: str) -> float:
        definitions = roots[source].all(law)
        if (
            len(definitions) != 1
            or definitions[0].op != "="
            or definitions[0].prefix is not None
            or not isinstance(definitions[0].value, Block)
        ):
            raise ValueError(f"具体法律机会缺少唯一普通法律定义：{law}")
        modifiers = definitions[0].value.all(channel)
        if not modifiers:
            return 0
        if (
            len(modifiers) != 1
            or modifiers[0].op != "="
            or modifiers[0].prefix is not None
            or not isinstance(modifiers[0].value, Block)
        ):
            raise ValueError(f"具体法律机会修正块形状漂移：{law}/{channel}")
        fields = modifiers[0].value.all(key)
        if not fields:
            return 0
        if (
            len(fields) != 1
            or fields[0].op != "="
            or fields[0].prefix is not None
            or not isinstance(fields[0].value, Scalar)
        ):
            raise ValueError(f"具体法律机会机制缺少唯一普通数值：{law}/{key}")
        try:
            number = float(fields[0].value.unquoted)
        except ValueError as error:
            raise ValueError(f"具体法律机会机制不是有限数值：{law}/{key}") from error
        if not math.isfinite(number):
            raise ValueError(f"具体法律机会机制不是有限数值：{law}/{key}")
        return number

    for source, laws in AUTHORITY_EFFECTS.items():
        for law, expected in laws.items():
            if value(source, law, "modifier", "country_authority_add") != expected:
                raise ValueError(f"具体法律机会权威机制漂移：{law}")
    labour = "common/laws/02_labour_associations.txt"
    for law, expected_pair in LABOUR_EFFECTS.items():
        actual = tuple(
            value(labour, law, "modifier", key)
            for key in (
                "state_radicals_from_political_movements_mult",
                "interest_group_ig_trade_unions_pol_str_mult",
            )
        )
        if actual != expected_pair:
            raise ValueError(f"具体法律机会劳动机制漂移：{law}")
    for law, expected_triple in POLICING_EFFECTS.items():
        actual = tuple(
            value(POLICING_SOURCE, law, "institution_modifier", key)
            for key in (
                "state_turmoil_effects_mult",
                "state_radicals_from_political_movements_mult",
                "state_mortality_turmoil_mult",
            )
        )
        if actual != expected_triple:
            raise ValueError(f"具体法律机会警务机制漂移：{law}")


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
            if (
                law in LABOUR_EFFECTS
                or law in POLICING_EFFECTS
                or data["candidates"][law] in AUTHORITY_EFFECTS
            ):
                # Withdrawal is explicit so an unknown current identity does
                # not erase an independently observed agenda. Both directions
                # use the same strongest tier, so known adoption cancels once.
                add(
                    law,
                    f"adopted_agenda_{tier}",
                    "law_observed_agenda",
                    -tuning[f"agenda_{tier}"],
                    [_condition(fact, "=", True), _condition(current(law), "=", True)],
                    "候选已实际生效时撤回相同档的议程偏好；未知当前法不抹去独立已知诉求",
                )
        # The newly expanded sources retain their existing named crisis
        # writers, including immutable published migration identities.
        if data["candidates"][law] in AUTHORITY_EFFECTS or law in POLICING_EFFECTS:
            continue
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

    for authority_effects in AUTHORITY_EFFECTS.values():
        for law, authority in authority_effects.items():
            if law not in data["candidates"]:
                continue
            for origin, old_authority in authority_effects.items():
                delta = authority - old_authority
                if delta == 0:
                    continue
                add(
                    law,
                    f"{origin}_authority_transition",
                    "law_authority_transition",
                    -8 if delta < 0 else 6,
                    [
                        _condition(current(origin), "=", True),
                        _condition("authority", "<", -delta if delta < 0 else 0),
                    ],
                    "比较现行到候选的原版权威常数差：余额不足覆盖实际损失时计机会成本，反向恢复只响应已知短缺；不推断人口歧视、移民、热情或税收收益",
                )

    for law, effects in POLICING_EFFECTS.items():
        for origin, old_effects in POLICING_EFFECTS.items():
            if law == origin:
                continue
            transition = [_condition(current(origin), "=", True)]
            if origin == "law_no_police":
                for fact, value in (("bureaucracy", -6), ("default", -8)):
                    add(
                        law,
                        f"new_institution_{fact}",
                        f"law_police_new_institution_{fact}",
                        value,
                        [
                            *transition,
                            _condition(
                                fact,
                                "<" if fact == "bureaucracy" else "=",
                                0 if fact == "bureaucracy" else True,
                            ),
                        ],
                        "从无警察建立真实新制度时，已知行政短缺与违约分别形成独立承载成本；既存同价制度转换不重复收取新制度成本",
                    )
            for index, mechanism in enumerate(
                ("turmoil_protection", "movement_radicalization", "mortality")
            ):
                difference = effects[index] - old_effects[index]
                if difference == 0:
                    continue
                for tier, investment in (("base", 1), ("invested", 3)):
                    improving = difference < 0
                    if mechanism == "movement_radicalization":
                        value = (12 if tier == "base" else 14) if improving else -6
                        group = "law_observed_agenda" if improving else "law_police_movement_loss"
                        exposure = [
                            _condition(f"law_context_{law}_movement_base", "=", True),
                            _condition("radical_share", ">=", 0.25),
                        ]
                    else:
                        magnitude = (
                            (8 if tier == "base" else 12)
                            if mechanism == "mortality"
                            else (6 if tier == "base" else 9)
                        )
                        value = magnitude if improving else -magnitude
                        group = f"law_police_{mechanism}"
                        exposure = [_condition("owned_state_turmoil", "=", True)]
                    add(
                        law,
                        f"{origin}_{mechanism}_{tier}",
                        group,
                        value,
                        [*transition, _condition("police_investment", ">=", investment), *exposure],
                        "现行与候选逐项比较实际制度修正：地方动乱损失保护、运动激进化及军警附带死亡风险分开；实际投资只升同因暴露档，不代表上限、未来投资或死亡人数",
                    )

    for law, (radicalization, union_strength) in LABOUR_EFFECTS.items():
        for origin, (old_radicalization, old_union_strength) in LABOUR_EFFECTS.items():
            if origin == law:
                continue
            transition = [_condition(current(origin), "=", True)]
            if radicalization != old_radicalization:
                add(
                    law,
                    f"{origin}_movement_radicalization",
                    "law_observed_agenda"
                    if radicalization < old_radicalization
                    else "law_movement_radicalization_loss",
                    14 if radicalization < old_radicalization else -6,
                    [
                        *transition,
                        _condition(f"law_context_{law}_movement_base", "=", True),
                        _condition("radical_share", ">=", 0.25),
                    ],
                    "比较现行到候选的原版运动激进化修正；真实候选诉求与激进人口仅表明暴露，改善升级同因档，恶化形成独立转换损失",
                )
            if union_strength > old_union_strength:
                for tier, cost in (("base", -6), ("government", -9)):
                    conditions = [
                        *transition,
                        _condition("union_approval", "<", 0),
                        _condition("union_clout", ">=", 0.2),
                    ]
                    if tier == "government":
                        conditions.append(_condition("union_government", "=", True))
                    add(
                        law,
                        f"{origin}_union_adjustment_{tier}",
                        "law_union_transition_adjustment",
                        cost,
                        conditions,
                        "实际提高工会政治强度时，仅已知不满且有显著影响力的工会形成有限调整成本；入阁升同因档，不把工会强大普遍当作损失或反叛预测",
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
