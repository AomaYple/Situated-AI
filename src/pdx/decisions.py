"""生产 Mod 生成器：整合处境信息、规则和原版消费者适配器。

以锁定原版底本为基础生成策略、触发器、脚本值、事件与完整本地化。
只为 AI 增加有界倾向，保留玩家路径与原版行动执行，按源和底本指纹拒绝漂移。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tomllib
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path

from packaging.version import InvalidVersion, Version

from . import (
    __version__,
    config,
    decision_adapters,
    decision_diplomacy,
    decision_economy,
    decision_interfaces,
    decision_rules,
    decision_security,
    decision_subjects,
)
from .lexer import LBRACE, RBRACE, tokenize
from .localization_languages import (
    DEFAULT_LANGUAGES,
    Language,
    localization_path,
)
from .localization_languages import (
    normalize as normalize_languages,
)
from .model import Block
from .parser import parse_text
from .textio import normalized_text
from .vanilla_index import (
    KEY_DIRS,
    SCRIPT_VALUE_ACCESSOR_DIR,
    VARIABLE_POOL_DIRS,
    VOCABULARY_DIRS,
    game_index,
    script_value_accessors,
    vocabulary_dir,
)

SOURCE = config.REPO / "mod" / "decisions" / "fiscal.toml"
PRODUCT = config.REPO / "mod"
BASELINE = config.REPO / "research" / "vanilla-ai" / "1.14.5" / "00_default_strategy.txt"
RISK_VAR = "sitai_fiscal_risk"
ACTIVE_TRIGGER = "sitai_fiscal_external_risk"
TOOL_VERSION = __version__
EXTENSIONS = SOURCE.with_name("extensions.toml")
PACKAGE_STATUSES = frozenset({"experimental", "candidate", "accepted"})
SAVE_COMPATIBILITY = frozenset({"new-game-only", "same-version-new-game", "same-candidate-save"})
SUPPORTED_PLATFORMS = frozenset({"windows", "macos", "linux"})

# 生产本地化集合跟随当前锁定的 Victoria 3 本体语言。
LANGUAGES: dict[str, str] = {language.directory: language.header for language in DEFAULT_LANGUAGES}

_DECISION_LOCALIZATION: dict[str, dict[str, str]] = {
    "SITAI_RULE_IDENTITY_FEASIBLE_HOMELAND_REASON": {
        "english": "Homeland ties and feasible national priorities (candidate)",
        "braz_por": "Laços com a pátria e prioridades nacionais viáveis (candidato)",
        "french": "Liens avec la patrie et priorités nationales réalisables (candidat)",
        "german": "Heimatbindungen und umsetzbare nationale Prioritäten (Kandidat)",
        "japanese": "故郷との結び付きと実行可能な国家の優先事項（候補ルール）",
        "korean": "본토 유대와 실행 가능한 국가 우선순위(후보 규칙)",
        "polish": "Więzi z ojczyzną i wykonalne priorytety narodowe (kandydat)",
        "russian": "Связи с родиной и осуществимые национальные приоритеты (кандидат)",
        "simp_chinese": "本土联系与可行的国家优先事项（候选规则）",
        "spanish": "Vínculos con la patria y prioridades nacionales viables (candidato)",
        "turkish": "Anavatan bağları ve uygulanabilir ulusal öncelikler (aday)",
    },
    "SITAI_RULE_GEOGRAPHIC_ISOLATION_FINANCIAL_COST_REASON": {
        "english": "Isolation and financial commitment costs (candidate)",
        "braz_por": "Isolamento e custos de compromissos financeiros (candidato)",
        "french": "Isolement et coûts des engagements financiers (candidat)",
        "german": "Geografische Isolation und Kosten finanzieller Verpflichtungen (Kandidat)",
        "japanese": "孤立と財政上の負担（候補ルール）",
        "korean": "고립과 재정적 부담 비용(후보 규칙)",
        "polish": "Izolacja i koszty zobowiązań finansowych (kandydat)",
        "russian": "Изоляция и стоимость финансовых обязательств (кандидат)",
        "simp_chinese": "地理孤立与财政承诺成本（候选规则）",
        "spanish": "Aislamiento y costes de los compromisos financieros (candidato)",
        "turkish": "Coğrafi izolasyon ve mali taahhüt maliyetleri (aday)",
    },
    "SITAI_RULE_GEOGRAPHIC_PORT_CONTINUITY_REASON": {
        "english": "Treaty port position and fiscal capacity (candidate)",
        "braz_por": "Posição do porto de tratado e capacidade fiscal (candidato)",
        "french": "Position du port de traité et capacité budgétaire (candidat)",
        "german": "Lage des Vertragshafens und finanzielle Kapazität (Kandidat)",
        "japanese": "条約港の位置と財政能力（候補ルール）",
        "korean": "조약항의 위치와 재정 역량(후보 규칙)",
        "polish": "Położenie portu traktatowego i możliwości fiskalne (kandydat)",
        "russian": "Положение договорного порта и финансовые возможности (кандидат)",
        "simp_chinese": "条约港位置与财政能力（候选规则）",
        "spanish": "Posición del puerto de tratado y capacidad fiscal (candidato)",
        "turkish": "Antlaşma limanının konumu ve mali kapasite (aday)",
    },
    "SITAI_MARKET_DEPENDENCE_SUPPORT_REASON": {
        "english": "Economic exposure to both sides",
        "braz_por": "Exposição econômica aos dois lados",
        "french": "Exposition économique aux deux camps",
        "german": "Wirtschaftliche Abhängigkeit von beiden Seiten",
        "japanese": "双方への経済的な依存",
        "korean": "양측에 대한 경제적 노출",
        "polish": "Gospodarcza zależność od obu stron",
        "russian": "Экономическая зависимость от обеих сторон",
        "simp_chinese": "对博弈双方的经济依赖",
        "spanish": "Exposición económica a ambos bandos",
        "turkish": "İki tarafa ekonomik maruziyet",
    },
    "SITAI_SECURITY_COMMITMENT_REASON": {
        "english": "Defense commitment (candidate)",
        "braz_por": "Compromisso de defesa (candidato)",
        "french": "Engagement de défense (candidat)",
        "german": "Verteidigungsverpflichtung (Kandidat)",
        "japanese": "防衛上の約束（候補ルール）",
        "korean": "방위 공약(후보 규칙)",
        "polish": "Zobowiązanie obronne (kandydat)",
        "russian": "Оборонное обязательство (кандидат)",
        "simp_chinese": "防御承诺（候选规则）",
        "spanish": "Compromiso defensivo (candidato)",
        "turkish": "Savunma taahhüdü (aday)",
    },
    "SITAI_SECURITY_NEIGHBOR_REASON": {
        "english": "Neighbor defense exposure (candidate)",
        "braz_por": "Risco de defesa de vizinho (candidato)",
        "french": "Exposition à la défense d'un voisin (candidat)",
        "german": "Sicherheitsrisiko durch die Bedrohung eines Nachbarlandes (Kandidat)",
        "japanese": "隣国防衛への関与（候補ルール）",
        "korean": "이웃 국가 방위 노출(후보 규칙)",
        "polish": "Ryzyko dla bezpieczeństwa związane z zagrożeniem sąsiada (kandydat)",
        "russian": "Риск для безопасности при угрозе соседней стране (кандидат)",
        "simp_chinese": "邻国受侵略的安全风险（候选规则）",
        "spanish": "Riesgo de defensa de un vecino (candidato)",
        "turkish": "Komşu savunma riski (aday)",
    },
    "SITAI_ECONOMY_CAPACITY_REASON": {
        "english": "Economic and administrative capacity (candidate)",
        "braz_por": "Capacidade econômica e administrativa (candidato)",
        "french": "Capacité économique et administrative (candidat)",
        "german": "Wirtschaftliche und administrative Kapazität (Kandidat)",
        "japanese": "経済・行政能力（候補ルール）",
        "korean": "경제 및 행정 역량(후보 규칙)",
        "polish": "Zdolność gospodarcza i administracyjna (kandydat)",
        "russian": "Экономическая и административная способность (кандидат)",
        "simp_chinese": "经济与行政能力（候选规则）",
        "spanish": "Capacidad económica y administrativa (candidato)",
        "turkish": "Ekonomik ve idari kapasite (aday)",
    },
    "SITAI_DIPLOMACY_BURDEN_REASON": {
        "english": "War burden and diplomatic capacity (candidate)",
        "braz_por": "Custo da guerra e capacidade diplomática (candidato)",
        "french": "Charge de guerre et capacité diplomatique (candidat)",
        "german": "Kriegslast und diplomatische Kapazität (Kandidat)",
        "japanese": "戦争負担と外交能力（候補ルール）",
        "korean": "전쟁 부담과 외교 역량(후보 규칙)",
        "polish": "Obciążenie wojną i zdolność dyplomatyczna (kandydat)",
        "russian": "Военная нагрузка и дипломатический потенциал (кандидат)",
        "simp_chinese": "战争负担与外交能力（候选规则）",
        "spanish": "Carga bélica y capacidad diplomática (candidato)",
        "turkish": "Savaş yükü ve diplomatik kapasite (aday)",
    },
    "SITAI_SUBJECT_RELATION_REASON": {
        "english": "Overlord and subject relationship (candidate)",
        "braz_por": "Relação entre suserano e súdito (candidato)",
        "french": "Relation suzerain-sujet (candidat)",
        "german": "Verhältnis zwischen Oberherr und Untertan (Kandidat)",
        "japanese": "宗主国と従属国の関係（候補ルール）",
        "korean": "종주국과 종속국 관계(후보 규칙)",
        "polish": "Relacja zwierzchnik–podmiot (kandydat)",
        "russian": "Отношения сюзерена и субъекта (кандидат)",
        "simp_chinese": "宗主国与属国关系（候选规则）",
        "spanish": "Relación entre soberano y súbdito (candidato)",
        "turkish": "Süzeren ve tabi ülke ilişkisi (aday)",
    },
}


def _localized_decision_text(key: str, language: Language) -> str:
    """返回一个有明确英语回退的生产本地化值。

    当前实验候选先保证本体的全部语言都有同一组键；正式发布前必须把
    ``fallback_languages`` 中的英语回退替换为经过审校的译文。
    """

    values = _DECISION_LOCALIZATION[key]
    return values.get(language.directory, values["english"])


@dataclass(frozen=True, slots=True)
class PackageContract:
    """由生产数据源声明的可追溯交付契约。"""

    product_version: str
    status: str
    parent: str
    save_compatibility: str
    platforms: tuple[str, ...]
    platform_notes: str


@dataclass(frozen=True, slots=True)
class Policy:
    enabled: bool
    game_version: str
    baseline_sha256: str
    entry_weeks: int
    exit_weeks: int
    ttl_days: int
    neutrality: float
    aggression: float
    package: PackageContract
    source_sha256: str = ""


@dataclass(frozen=True, slots=True)
class Extensions:
    reform_enabled: bool = False
    reform_legitimacy: int = 75
    fragile_legitimacy: int = 25
    reform_bonus: float = 1
    fragile_penalty: float = -0.5
    market_enabled: bool = False
    market_multiplier: float = 5
    source_sha256: str = ""
    security_enabled: bool = False
    security_commitment_bonus: float = 25
    security_threat_bonus: float = 15
    economy_enabled: bool = False
    diplomacy_enabled: bool = False
    subjects_enabled: bool = False


@dataclass(frozen=True, slots=True)
class SupportArbitration:
    """外交博弈支持字段的离线仲裁结果。

    ``market`` 与 ``security`` 都是同一原版字段的候选贡献。仲裁器只接受
    已知双方和 AI 作用域；安全理由按绝对值取一个最高理由，并按键去重，
    这样调用方不会把同一原因重复计分。
    """

    value: float
    reasons: tuple[str, ...]


def merge_diplomatic_play_support(
    *,
    market: float | None = None,
    security: Mapping[str, float | None] | None = None,
    has_sides: bool = True,
    is_ai: bool = True,
) -> SupportArbitration:
    """合并市场/安全对 ``diplomatic_play_support`` 的有限贡献。

    玩家、缺少博弈双方或任何未知安全输入都返回零贡献；市场贡献可以为
    负值，安全贡献只选一个最高的已知理由。该函数不创建资格、不代表参战。
    """

    if not is_ai or not has_sides:
        return SupportArbitration(0.0, ())
    value = 0.0
    reasons: list[str] = []
    if market is not None:
        if isinstance(market, bool) or not isinstance(market, (int, float)):
            raise ValueError("市场支持贡献必须是有限数值或未知")
        if not math.isfinite(market):
            raise ValueError("市场支持贡献必须是有限数值或未知")
        value += float(market)
        reasons.append("market")
    if security:
        candidates: list[tuple[float, str]] = []
        for reason, amount in security.items():
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("安全理由必须是非空字符串")
            if amount is None:
                return SupportArbitration(0.0, ())
            if isinstance(amount, bool) or not isinstance(amount, (int, float)):
                raise TypeError("安全支持贡献必须是有限数值")
            if not math.isfinite(amount):
                raise ValueError("安全支持贡献必须是有限数值")
            if amount:
                candidates.append((float(amount), reason))
        if candidates:
            amount, reason = max(candidates, key=lambda item: (item[0], item[1]))
            value += amount
            if reason not in reasons:
                reasons.append(reason)
    return SupportArbitration(value, tuple(reasons))


def player_boundary_issues(strategy: str) -> list[str]:
    """静态检查所有新增默认策略字段块都显式约束 ``is_ai``。"""

    marker = re.compile(r"# SITAI BEGIN ([^\n]+)\n(.*?)# SITAI END \1\n", re.DOTALL)
    return [
        f"{match.group(1)} 新增字段块缺少 is_ai = yes 玩家边界"
        for match in marker.finditer(strategy)
        if "is_ai = yes" not in match.group(2)
    ]


MODULE_LIFECYCLE_CONTRACT: dict[str, dict[str, object]] = {
    "fiscal": {
        "stateful": True,
        "direct_read": False,
        "hooks": [
            "on_monthly_pulse_country",
            "on_country_default",
            "on_country_no_longer_default",
        ],
        "ttl_or_none": "policy.ttl_days",
        "clear_on_disable": True,
    },
    "reform": {
        "stateful": False,
        "direct_read": True,
        "hooks": [],
        "ttl_or_none": None,
        "clear_on_disable": True,
    },
    "market": {
        "stateful": False,
        "direct_read": True,
        "hooks": [],
        "ttl_or_none": None,
        "clear_on_disable": True,
    },
    "security": {
        "stateful": False,
        "direct_read": True,
        "hooks": [],
        "ttl_or_none": None,
        "clear_on_disable": True,
    },
    "economy": {
        "stateful": False,
        "direct_read": True,
        "hooks": [],
        "ttl_or_none": None,
        "clear_on_disable": True,
    },
    "diplomacy": {
        "stateful": False,
        "direct_read": True,
        "hooks": [],
        "ttl_or_none": None,
        "clear_on_disable": True,
    },
    "subjects": {
        "stateful": False,
        "direct_read": True,
        "hooks": [],
        "ttl_or_none": None,
        "clear_on_disable": True,
    },
}

FULL_INFORMATION_DOMAINS = (
    "political",
    "fiscal",
    "economy",
    "market",
    "diplomacy",
    "subjects",
    "military",
    "geography",
    "identity",
)


def information_contract() -> dict[str, object]:
    """生产候选携带的全量信息实现契约。

    这份契约描述 F0 的实现边界，不把静态目录或脚本加载宣称为行为质量；
    未确认的运行时消费者必须继续回退原版。
    """

    return {
        "schema": 1,
        "domains": list(FULL_INFORMATION_DOMAINS),
        "states": [
            "discovered",
            "runtime_readable",
            "derived",
            "consumer_mapped",
            "behavior_verified",
            "unsupported",
        ],
        "impact_levels": {
            "A": "direct",
            "B": "strategy",
            "C": "qualification",
            "D": "explanation",
            "E": "no_consumer",
        },
        "unknown_policy": "preserve_unknown_and_fallback_vanilla",
        "domain_list_kind": "target_scope_not_implementation_claim",
        "arbitration": "see_candidate_decision_rules_contract",
        "player_boundary": "is_ai_only",
        "behavior_quality": "user_long_term_review_pending",
    }


def module_lifecycle_contract(
    policy: Policy, _extensions: Extensions
) -> dict[str, dict[str, object]]:
    """返回各决策模块的状态、钩子、TTL、关闭清理和存档契约。"""

    contract = deepcopy(MODULE_LIFECYCLE_CONTRACT)
    contract["fiscal"]["ttl_or_none"] = policy.ttl_days if policy.enabled else None
    for item in contract.values():
        item["save_compatibility"] = policy.package.save_compatibility
    return contract


def load_extensions(source: Path = EXTENSIONS) -> Extensions:
    raw = source.read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))
    allowed = {
        "schema_version",
        "reform",
        "market",
        "security",
        "economy",
        "diplomacy",
        "subjects",
    }
    if (
        not set(data) <= allowed
        or not {"schema_version", "reform", "market"} <= set(data)
        or type(data["schema_version"]) is not int
        or data["schema_version"] != 1
    ):
        raise ValueError("扩展参数 schema 无效")
    reform, market = data["reform"], data["market"]
    if (
        not isinstance(reform, dict)
        or not isinstance(market, dict)
        or set(reform) != {"enabled", "legitimacy", "fragile_legitimacy", "bonus", "penalty", "why"}
        or set(market) != {"enabled", "multiplier", "why"}
    ):
        raise ValueError("扩展参数包含未知或缺失字段")
    if any(type(v) is not bool for v in (reform["enabled"], market["enabled"])):
        raise ValueError("扩展开关必须是布尔值")
    if (
        any(type(v) is not int for v in (reform["legitimacy"], reform["fragile_legitimacy"]))
        or not 0 <= reform["fragile_legitimacy"] < reform["legitimacy"] <= 100
    ):
        raise ValueError("合法性阈值必须是0到100的有序整数")
    amounts = (reform["bonus"], reform["penalty"], market["multiplier"])
    if (
        any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in amounts
        )
        or not 0 <= reform["bonus"] <= 5
        or not -0.9 <= reform["penalty"] <= 0
        or not 0 <= market["multiplier"] <= 10
    ):
        raise ValueError("扩展偏置必须有限且位于保守范围内")
    if any(not isinstance(v, str) or not v.strip() for v in (reform["why"], market["why"])):
        raise ValueError("扩展参数必须给出依据")
    security = data.get(
        "security",
        {
            "enabled": False,
            "commitment_bonus": 25,
            "threat_bonus": 15,
            "why": "旧配置：外部模块关闭",
        },
    )
    if (
        not isinstance(security, dict)
        or set(security) != {"enabled", "commitment_bonus", "threat_bonus", "why"}
        or type(security["enabled"]) is not bool
        or not isinstance(security["why"], str)
        or not security["why"].strip()
    ):
        raise ValueError("外部防御配置字段、开关或依据无效")
    for amount in (security["commitment_bonus"], security["threat_bonus"]):
        if (
            isinstance(amount, bool)
            or not isinstance(amount, (int, float))
            or not 0 <= amount <= 50
            or not math.isfinite(amount)
        ):
            raise ValueError("外部防御权重必须是 0 到 50 的有限数值")
    optional = {name: data.get(name, {}) for name in ("economy", "diplomacy", "subjects")}
    for name, value in optional.items():
        if value and (not isinstance(value, dict) or set(value) != {"enabled"}):
            raise ValueError(f"{name} 扩展只允许声明 enabled；具体参数由模块数据源维护")
    return Extensions(
        reform_enabled=reform["enabled"],
        reform_legitimacy=reform["legitimacy"],
        fragile_legitimacy=reform["fragile_legitimacy"],
        reform_bonus=reform["bonus"],
        fragile_penalty=reform["penalty"],
        market_enabled=market["enabled"],
        market_multiplier=market["multiplier"],
        source_sha256=hashlib.sha256(raw).hexdigest(),
        security_enabled=security["enabled"],
        security_commitment_bonus=security["commitment_bonus"],
        security_threat_bonus=security["threat_bonus"],
        economy_enabled=bool(optional["economy"].get("enabled", False)),
        diplomacy_enabled=bool(optional["diplomacy"].get("enabled", False)),
        subjects_enabled=bool(optional["subjects"].get("enabled", False)),
    )


def extension_triggers(policy: Extensions) -> str:
    return f"""# 由 pdx.decisions 生成；改革派IG身份是机会代理，不指定法律。
sitai_reform_fragile = {{
    is_ai = yes
    OR = {{ legitimacy < {policy.fragile_legitimacy} is_at_war = yes any_insurrection_ongoing = yes }}
}}
sitai_reform_opportunity = {{
    is_ai = yes
    legitimacy >= {policy.reform_legitimacy}
    is_at_war = no
    any_insurrection_ongoing = no
    OR = {{
        ig:ig_industrialists ?= {{ is_in_government = yes }}
        ig:ig_intelligentsia ?= {{ is_in_government = yes }}
    }}
}}
"""


def extension_values(policy: Extensions) -> str:
    return f"""# 由 pdx.decisions 生成；本项是default贡献，不是最终AI总概率。
sitai_reform_default_delta = {{
    value = 0
    if = {{ limit = {{ sitai_reform_fragile = yes }} add = {policy.fragile_penalty:g} }}
    else_if = {{ limit = {{ sitai_reform_opportunity = yes }} add = {policy.reform_bonus:g} }}
}}
"""


def market_delta(own: float, other: float, *, multiplier: float) -> float:
    """依赖为0到5的方向性标度，双方差值的参考契约。"""
    if (
        any(not math.isfinite(v) for v in (own, other, multiplier))
        or not 0 <= own <= 5
        or not 0 <= other <= 5
        or not 0 <= multiplier <= 10
    ):
        raise ValueError("市场依赖必须在0到5，权重必须在0到10，所有数值有限")
    return (own - other) * multiplier


def load(source: Path = SOURCE) -> Policy:
    raw = source.read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))
    if (
        set(data)
        != {
            "schema_version",
            "game_version",
            "baseline_sha256",
            "package",
            "fiscal",
            "fields",
        }
        or type(data["schema_version"]) is not int
        or data["schema_version"] != 1
    ):
        raise ValueError("决策数据源的 schema 或字段无效")
    if (
        not isinstance(data["game_version"], str)
        or data["game_version"] != "1.14.5"
        or not isinstance(data["baseline_sha256"], str)
        or len(data["baseline_sha256"]) != 64
        or any(c not in "0123456789abcdef" for c in data["baseline_sha256"])
        or not isinstance(data["package"], dict)
        or not isinstance(data["fiscal"], dict)
        or not isinstance(data["fields"], dict)
    ):
        raise ValueError("决策版本、底本指纹或参数表无效；升级需重新审查")
    package, fiscal, fields = data["package"], data["fiscal"], data["fields"]
    if (
        set(package)
        != {
            "product_version",
            "status",
            "parent",
            "save_compatibility",
            "platforms",
            "platform_notes",
        }
        or set(fiscal) != {"enabled", "entry_weeks", "exit_weeks", "ttl_days", "why"}
        or set(fields)
        != {
            "diplomatic_play_neutrality",
            "aggression",
            "why",
        }
    ):
        raise ValueError("决策数据源含缺失或未知字段")
    try:
        product_version = Version(package["product_version"])
    except (InvalidVersion, TypeError) as exc:
        raise ValueError("产品版本必须是有效的 Python 打包版本") from exc
    if (
        not isinstance(package["product_version"], str)
        or not isinstance(package["status"], str)
        or not isinstance(package["save_compatibility"], str)
        or not isinstance(package["platform_notes"], str)
        or str(product_version) != package["product_version"]
        or package["status"] not in PACKAGE_STATUSES
        or package["save_compatibility"] not in SAVE_COMPATIBILITY
        or not isinstance(package["parent"], str)
        or not package["parent"].strip()
        or not isinstance(package["platforms"], list)
        or not package["platforms"]
        or any(not isinstance(platform, str) for platform in package["platforms"])
        or len(set(package["platforms"])) != len(package["platforms"])
        or any(platform not in SUPPORTED_PLATFORMS for platform in package["platforms"])
        or not package["platform_notes"].strip()
    ):
        raise ValueError("产品交付契约无效：版本、状态、父包、存档或平台声明不可靠")
    if (
        any(
            not isinstance(v, str) or not v.strip()
            for v in (
                package["parent"],
                package["platform_notes"],
                fiscal["why"],
                fields["why"],
            )
        )
        or type(fiscal["enabled"]) is not bool
    ):
        raise ValueError("每组决策参数必须给出依据")
    contract = PackageContract(
        package["product_version"],
        package["status"],
        package["parent"],
        package["save_compatibility"],
        tuple(package["platforms"]),
        package["platform_notes"],
    )
    policy = Policy(
        fiscal["enabled"],
        data["game_version"],
        data["baseline_sha256"],
        fiscal["entry_weeks"],
        fiscal["exit_weeks"],
        fiscal["ttl_days"],
        fields["diplomatic_play_neutrality"],
        fields["aggression"],
        contract,
        hashlib.sha256(raw).hexdigest(),
    )
    if (
        any(
            type(v) is not int or v <= 0
            for v in (policy.entry_weeks, policy.exit_weeks, policy.ttl_days)
        )
        or policy.exit_weeks <= policy.entry_weeks
        or policy.ttl_days < 32
    ):
        raise ValueError("财政阈值必须为正整数，退出线高于进入线，TTL覆盖一个月")
    if (
        any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in (policy.neutrality, policy.aggression)
        )
        or not 0 <= policy.neutrality <= 100
        or not -1 <= policy.aggression <= 0
    ):
        raise ValueError("外交偏置必须为有限数且位于声明方向的保守范围内")
    return policy


def risk_next(
    active: bool,
    *,
    in_default: bool,
    taking_loans: bool,
    credit: float | None,
    weeks: float | None,
    policy: Policy,
) -> bool:
    """与脚本共享的有限状态契约；未知读数停止干预，不默认为安全。"""
    if not policy.enabled:
        return False
    if in_default:
        return True
    if not taking_loans or credit is None or not math.isfinite(credit) or credit <= 0:
        return False
    if weeks is None or not math.isfinite(weeks) or weeks < 0:
        return False
    return weeks < (policy.exit_weeks if active else policy.entry_weeks)


def fiscal_condition(weeks: int) -> str:
    """复用相同原生输入条件；它不包含迟滞记忆、TTL 或策略状态。"""
    if type(weeks) is not int or weeks <= 0:
        raise ValueError("财政条件周数必须是正整数")
    return f"""    OR = {{
        in_default = yes
        AND = {{ taking_loans = yes credit > 0 weeks_until_bankruptcy >= 0 weeks_until_bankruptcy < {weeks} }}
    }}"""


def diplomatic_play_support_addition(extensions: Extensions) -> str:
    """为共享的 ``diplomatic_play_support`` 字段生成唯一写入块。

    市场差值与安全理由在同一 AI/双方上下文中评估；安全的承诺/威胁使用
    ``else_if``，因此同一防御事实最多贡献一次，且按配置权重取最高理由。
    """

    if not (extensions.market_enabled or extensions.security_enabled):
        return ""
    amounts = (extensions.security_commitment_bonus, extensions.security_threat_bonus)
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 <= value <= 50
        or not math.isfinite(value)
        for value in amounts
    ):
        raise ValueError("外部防御权重必须是 0 到 50 的有限数值")
    lines = [
        "\t\tif = {\n",
        "\t\t\tlimit = { ROOT ?= { is_ai = yes } exists = scope:country exists = scope:enemy_country }\n",
    ]
    if extensions.market_enabled:
        lines.extend(
            [
                "\t\t\tif = {\n",
                "\t\t\t\tlimit = { ROOT ?= { exists = scope:country exists = scope:enemy_country } }\n",
                "\t\t\t\tadd = {\n",
                '\t\t\t\t\tvalue = "ROOT.economic_dependence(scope:country)"\n',
                '\t\t\t\t\tsubtract = "ROOT.economic_dependence(scope:enemy_country)"\n',
                f"\t\t\t\t\tmultiply = {extensions.market_multiplier:g}\n",
                "\t\t\t\t\tdesc = SITAI_MARKET_DEPENDENCE_SUPPORT_REASON\n",
                "\t\t\t\t}\n",
                "\t\t\t}\n",
            ]
        )
    if extensions.security_enabled:

        def side(partner: str, opponent: str, sign: int) -> list[str]:
            reasons = [
                (
                    amounts[0],
                    f"sitai_defense_commitment = {{ PARTNER = {partner} }}",
                    "COMMITMENT",
                ),
                (
                    amounts[1],
                    f"sitai_neighbor_defense = {{ PARTNER = {partner} OPPONENT = {opponent} }}",
                    "NEIGHBOR",
                ),
            ]
            result: list[str] = []
            for amount, condition, reason in sorted(reasons, key=lambda row: -row[0]):
                if amount == 0:
                    continue
                branch = "if" if not result else "else_if"
                result.extend(
                    [
                        f"\t\t\t\t{branch} = {{\n",
                        f"\t\t\t\t\tlimit = {{ ROOT ?= {{ {condition} }} }}\n",
                        f"\t\t\t\t\tadd = {{ value = {sign * amount:g} desc = SITAI_SECURITY_{reason}_REASON }}\n",
                        "\t\t\t\t}\n",
                    ]
                )
            return result

        lines.extend(
            [
                "\t\t\tif = {\n",
                "\t\t\t\tlimit = { NOT = { exists = scope:is_initiator } }\n",
                *side("scope:country", "scope:enemy_country", 1),
                "\t\t\t}\n",
                "\t\t\telse = {\n",
                *side("scope:enemy_country", "scope:country", -1),
                "\t\t\t}\n",
            ]
        )
    lines.append("\t\t}\n")
    return "".join(lines)


def triggers(policy: Policy) -> str:
    if not policy.enabled:
        return ""
    return f"""# 由 pdx.decisions 生成；所有国家共享同一规则。
sitai_fiscal_entry = {{
{fiscal_condition(policy.entry_weeks)}
}}
sitai_fiscal_hold = {{
{fiscal_condition(policy.exit_weeks)}
}}
sitai_external_exposure = {{
    OR = {{
        is_at_war = yes
        is_diplomatic_play_initiator = yes
        is_diplomatic_play_target = yes
        is_diplomatic_play_committed_participant = yes
        is_diplomatic_play_undecided_participant = yes
    }}
}}
{ACTIVE_TRIGGER} = {{
    is_ai = yes
    sitai_external_exposure = yes
    has_variable = {RISK_VAR}
    sitai_fiscal_hold = yes
}}
"""


def effects(policy: Policy) -> str:
    if not policy.enabled:
        return ""
    return f"""# 由 pdx.decisions 生成；只有本更新器写入财政状态。
sitai_update_fiscal = {{
    if = {{
        limit = {{ is_ai = yes OR = {{ sitai_fiscal_entry = yes AND = {{ has_variable = {RISK_VAR} sitai_fiscal_hold = yes }} }} }}
        set_variable = {{ name = {RISK_VAR} value = 1 days = {policy.ttl_days} }}
    }}
    else = {{ remove_variable = {RISK_VAR} }}
}}
"""


def on_actions(policy: Policy | None = None) -> str:
    policy = policy or load()
    if not policy.enabled:
        return ""
    return """# 由 pdx.decisions 生成；追加子钩子，不替换原版 effect。
on_monthly_pulse_country = { on_actions = { sitai_fiscal_update } }
on_country_default = { on_actions = { sitai_fiscal_update } }
on_country_no_longer_default = { on_actions = { sitai_fiscal_update } }
sitai_fiscal_update = { effect = { sitai_update_fiscal = yes } }
"""


def patch_default(text: str, policy: Policy, extensions: Extensions | None = None) -> str:
    """利用词法器定位闭括号，避免注释/字符串内的括号破坏补丁位置。"""
    text = normalized_text(text)
    if hashlib.sha256(text.encode()).hexdigest() != policy.baseline_sha256:
        raise ValueError("默认策略底本哈希不符；升级需重新审核，拒绝盲生成")
    parsed = parse_text(text, str(BASELINE))
    if (
        parsed.errors
        or len(parsed.top_assignments) != 1
        or parsed.top_keys != ["ai_strategy_default"]
    ):
        raise ValueError("底本必须恰好包含原版默认策略")
    block = parsed.top_assignments[0].value
    if not isinstance(block, Block):
        raise TypeError("默认策略必须为块")
    lines = text.splitlines(keepends=True)
    changes: list[tuple[int, str]] = []
    additions = {
        field: f"\t\tif = {{\n\t\t\tlimit = {{ ROOT ?= {{ is_ai = yes {ACTIVE_TRIGGER} = yes }} }}\n\t\t\tadd = {amount:g}\n\t\t}}\n"
        for field, amount in (
            ("diplomatic_play_neutrality", policy.neutrality),
            ("aggression", policy.aggression),
        )
        if policy.enabled and amount != 0
    }
    if extensions and extensions.reform_enabled:
        additions["change_law_chance"] = (
            "\t\tif = { limit = { ROOT ?= { is_ai = yes } } add = sitai_reform_default_delta }\n"
        )
    if extensions:
        support = diplomatic_play_support_addition(extensions)
        if support:
            additions["diplomatic_play_support"] = support
    if extensions and extensions.economy_enabled:
        additions["economic_vs_government_spending_balance"] = decision_economy.strategy_addition(
            replace(decision_economy.load(), enabled=True)
        )
    if extensions and extensions.diplomacy_enabled:
        additions["recklessness"] = decision_diplomacy.strategy_addition(
            replace(decision_diplomacy.load(), enabled=True)
        )
    if extensions and extensions.subjects_enabled:
        additions["subject_value"] = decision_subjects.subject_addition(
            replace(decision_subjects.load(), enabled=True)
        )
        additions["become_subject_value"] = decision_subjects.become_subject_addition(
            replace(decision_subjects.load(), enabled=True)
        )
    if not additions:
        return text
    fields: list[tuple[int, str]] = []
    for field in additions:
        matches = block.all(field)
        if len(matches) != 1 or not isinstance(matches[0].value, Block):
            raise ValueError(f"底本 {field} 必须为唯一脚本值块")
        fields.append((matches[0].line, field))
    del parsed, block, matches
    pending = iter(sorted(fields))
    current = next(pending)
    depth = 0
    for tok in tokenize(text):
        if depth == 0 and not (tok.line >= current[0] and tok.kind == LBRACE):
            continue
        depth += (tok.kind == LBRACE) - (tok.kind == RBRACE)
        if depth == 0:
            _, field = current
            addition = re.sub(r"(?m)^ +(?=\t)", "", additions[field])
            addition = re.sub(r"(?m)^[\t ]+$", "", addition)
            addition = re.sub(r"[\t ]+(?=\n)", "", addition)
            extra = f"\t\t# SITAI BEGIN {field}\n{addition}\t\t# SITAI END {field}\n"
            changes.append((tok.line - 1, extra))
            following = next(pending, None)
            if following is None:
                break
            current = following
    if len(changes) != len(fields):
        raise ValueError("找不到字段闭括号")
    for index, extra in sorted(changes, reverse=True):
        lines.insert(index, extra)
    result = "".join(lines)
    if parse_text(result).errors:
        raise ValueError("默认策略补丁产物解析失败")
    return result


def source_fingerprint(policy: Policy, extensions: Extensions, baseline: str) -> dict[str, str]:
    """返回生成输入指纹，供 metadata 与交付清单共同引用。"""

    result = {
        "fiscal_source_sha256": policy.source_sha256,
        "extensions_source_sha256": extensions.source_sha256,
        "baseline_sha256": hashlib.sha256(normalized_text(baseline).encode()).hexdigest(),
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    if extensions.security_enabled:
        result["security_generator_sha256"] = hashlib.sha256(
            Path(decision_security.__file__).read_bytes()
        ).hexdigest()
    if extensions.economy_enabled:
        result["economy_source_sha256"] = decision_economy.load().source_sha256
    if extensions.diplomacy_enabled:
        result["diplomacy_source_sha256"] = decision_diplomacy.load().source_sha256
    if extensions.subjects_enabled:
        result["subjects_source_sha256"] = decision_subjects.load().source_sha256
    return result


def _module_names(
    policy: Policy,
    extensions: Extensions,
    files: Mapping[str, str] | None = None,
    languages: tuple[Language, ...] = DEFAULT_LANGUAGES,
) -> list[str]:
    files = files or {}
    modules: list[str] = []
    if policy.enabled and (
        not files
        or {
            "common/scripted_triggers/sitai_fiscal_triggers.txt",
            "common/scripted_effects/sitai_fiscal_effects.txt",
            "common/on_actions/sitai_fiscal_on_actions.txt",
        }
        <= files.keys()
    ):
        modules.append("fiscal")
    if extensions.reform_enabled and (
        not files
        or {
            "common/scripted_triggers/sitai_reform_triggers.txt",
            "common/script_values/sitai_reform_values.txt",
        }
        <= files.keys()
    ):
        modules.append("reform")
    if extensions.market_enabled and (
        not files
        or {localization_path(language, "sitai_decisions") for language in languages}
        <= files.keys()
    ):
        modules.append("market")
    if extensions.security_enabled and (
        not files or "common/scripted_triggers/sitai_security_triggers.txt" in files
    ):
        modules.append("security")
    if extensions.economy_enabled and (
        not files or "common/scripted_triggers/sitai_economy_triggers.txt" in files
    ):
        modules.append("economy")
    if extensions.diplomacy_enabled and (
        not files or "common/scripted_triggers/sitai_diplomacy_triggers.txt" in files
    ):
        modules.append("diplomacy")
    if extensions.subjects_enabled and (
        not files or "common/scripted_triggers/sitai_subjects_triggers.txt" in files
    ):
        modules.append("subjects")
    return modules


def metadata_payload(
    policy: Policy | None = None,
    extensions: Extensions | None = None,
    *,
    enabled_modules: list[str] | None = None,
    baseline: str | None = None,
    languages: tuple[Language, ...] | None = None,
    complete_localization: bool = False,
) -> dict[str, object]:
    policy = policy or load()
    extensions = extensions or load_extensions()
    languages = normalize_languages(DEFAULT_LANGUAGES if languages is None else languages)
    production_fallback_languages = (
        []
        if complete_localization
        else [
            language.directory
            for language in languages
            if language.directory not in {"english", "simp_chinese"}
        ]
    )
    return {
        "name": "Situated AI",
        "id": config.MOD_ID,
        "version": policy.package.product_version,
        "tool_version": TOOL_VERSION,
        "status": policy.package.status,
        "supported_game_version": policy.game_version,
        "short_description": (
            "依据国家处境综合调整政治、经济、外交与军事 AI 倾向，保留原版资格、成本和行动执行。"
        ),
        "tags": [],
        "relationships": [],
        "enabled_modules": enabled_modules
        if enabled_modules is not None
        else _module_names(policy, extensions, languages=languages),
        "localization": {
            "languages": [language.directory for language in languages],
            "headers": [language.header for language in languages],
            # 保留旧消费者字段；生产回退必须如实声明，打包时拒绝缺译。
            "fallback_languages": production_fallback_languages,
            "production_fallback_languages": production_fallback_languages,
            # 生产源不包含解释探针，保留空字段以便核对历史生成合同。
            "explanation_fallback_languages": [],
            "fallback_policy": "none"
            if complete_localization
            else "experimental-only-english-source",
        },
        "parent_package": policy.package.parent,
        "save_compatibility": policy.package.save_compatibility,
        "platforms": list(policy.package.platforms),
        "platform_notes": policy.package.platform_notes,
        "module_contract": module_lifecycle_contract(policy, extensions),
        "information_contract": information_contract(),
        "source_fingerprint": source_fingerprint(
            policy,
            extensions,
            baseline if baseline is not None else BASELINE.read_text(encoding="utf-8"),
        ),
        "game_custom_data": {"multiplayer_synchronized": True},
    }


def build(
    policy: Policy | None = None,
    baseline: str | None = None,
    *,
    extensions: Extensions | None = None,
    languages: tuple[Language, ...] | None = None,
    complete_localization: bool = False,
    information_rules: decision_rules.RuleSet | None = None,
    consumer_adapters: decision_adapters.AdapterSet | None = None,
) -> dict[str, str]:
    policy = policy or load()
    baseline = baseline if baseline is not None else BASELINE.read_text(encoding="utf-8")
    extensions = extensions or load_extensions()
    # 每个输出只允许一个处境规则作者。旧模块不能在适配规则后继续叠加，
    # 否则同一财政/宗属事实可能被重复计分；历史变体保持原实现。
    field_owners: dict[tuple[str, ...], str] = {}
    if policy.enabled:
        field_owners.update(
            {
                ("diplomatic_play_neutrality",): "fiscal",
                ("aggression",): "fiscal",
            }
        )
    for enabled, owner, fields in (
        (extensions.reform_enabled, "reform", ("change_law_chance",)),
        (
            extensions.market_enabled or extensions.security_enabled,
            "support_composer",
            ("diplomatic_play_support",),
        ),
        (extensions.economy_enabled, "economy", ("economic_vs_government_spending_balance",)),
        (extensions.diplomacy_enabled, "diplomacy", ("recklessness",)),
        (extensions.subjects_enabled, "subjects", ("subject_value", "become_subject_value")),
    ):
        if enabled:
            field_owners.update({(field,): owner for field in fields})
    if information_rules is not None:
        for field in information_rules.groups():
            if any(
                field[: len(existing)] == existing or existing[: len(field)] == field
                for existing in field_owners
            ):
                raise ValueError(f"旧模块与全域规则重复写入字段：{'.'.join(field)}")
            field_owners[field] = "information_rules"
    if consumer_adapters is not None:
        for name, field, owner in decision_adapters.writes(consumer_adapters):
            if name != "common/ai_strategies/00_default_strategy.txt":
                continue
            if field[0] != "ai_strategy_default":
                raise ValueError("默认策略适配不能写入其它顶层键")
            path = field[1:]
            if any(
                path[: len(existing)] == existing or existing[: len(path)] == path
                for existing in field_owners
            ):
                raise ValueError(f"旧模块或全域规则与消费者适配重复写入字段：{'.'.join(path)}")
            field_owners[path] = owner
    languages = normalize_languages(DEFAULT_LANGUAGES if languages is None else languages)
    files = {
        "common/ai_strategies/00_default_strategy.txt": patch_default(baseline, policy, extensions),
    }
    adapter_inputs = (
        decision_adapters.read_inputs(consumer_adapters) if consumer_adapters is not None else None
    )
    if information_rules is not None:
        files["common/ai_strategies/00_default_strategy.txt"] = decision_rules.patch(
            files["common/ai_strategies/00_default_strategy.txt"],
            information_rules,
            baseline=baseline,
            reader_words=(
                frozenset(decision_adapters.reader_evidence(adapter_inputs))
                if adapter_inputs is not None
                else None
            ),
        )
    strategy_issues = player_boundary_issues(files["common/ai_strategies/00_default_strategy.txt"])
    if strategy_issues:
        raise ValueError("生产策略违反玩家边界：" + "；".join(strategy_issues))
    if policy.enabled:
        files.update(
            {
                "common/scripted_triggers/sitai_fiscal_triggers.txt": triggers(policy),
                "common/scripted_effects/sitai_fiscal_effects.txt": effects(policy),
                "common/on_actions/sitai_fiscal_on_actions.txt": on_actions(policy),
            }
        )
    if extensions.reform_enabled:
        files["common/scripted_triggers/sitai_reform_triggers.txt"] = extension_triggers(extensions)
        files["common/script_values/sitai_reform_values.txt"] = extension_values(extensions)
    if extensions.security_enabled:
        files["common/scripted_triggers/sitai_security_triggers.txt"] = decision_security.triggers()
    if extensions.economy_enabled:
        files["common/scripted_triggers/sitai_economy_triggers.txt"] = decision_economy.triggers(
            replace(decision_economy.load(), enabled=True)
        )
    if extensions.diplomacy_enabled:
        files["common/scripted_triggers/sitai_diplomacy_triggers.txt"] = (
            decision_diplomacy.triggers(replace(decision_diplomacy.load(), enabled=True))
        )
    if extensions.subjects_enabled:
        files["common/scripted_triggers/sitai_subjects_triggers.txt"] = decision_subjects.triggers(
            replace(decision_subjects.load(), enabled=True)
        )
    if (
        extensions.market_enabled
        or extensions.security_enabled
        or extensions.economy_enabled
        or extensions.diplomacy_enabled
        or extensions.subjects_enabled
        or information_rules is not None
    ):
        reason_keys: list[str] = []
        if extensions.market_enabled:
            reason_keys.append("SITAI_MARKET_DEPENDENCE_SUPPORT_REASON")
        if extensions.security_enabled:
            reason_keys.extend(
                ["SITAI_SECURITY_COMMITMENT_REASON", "SITAI_SECURITY_NEIGHBOR_REASON"]
            )
        if extensions.economy_enabled:
            reason_keys.append("SITAI_ECONOMY_CAPACITY_REASON")
        if extensions.diplomacy_enabled:
            reason_keys.append("SITAI_DIPLOMACY_BURDEN_REASON")
        if extensions.subjects_enabled:
            reason_keys.append("SITAI_SUBJECT_RELATION_REASON")
        if information_rules is not None:
            reason_keys.extend(
                key
                for rule in information_rules.rules
                if rule.domain in information_rules.enabled_domains
                and (key := decision_rules.description_key(rule)) is not None
            )
        for language in languages:
            reasons = {key: _localized_decision_text(key, language) for key in reason_keys}
            files[localization_path(language, "sitai_decisions")] = (
                f"{language.header}:\n"
                + "".join(f' {key}: "{value}"\n' for key, value in reasons.items())
            )
    metadata = metadata_payload(
        policy,
        extensions,
        enabled_modules=_module_names(policy, extensions, files, languages),
        baseline=baseline,
        languages=languages,
        complete_localization=complete_localization,
    )
    if information_rules is not None or consumer_adapters is not None:
        metadata["default_field_owners"] = {
            ".".join(field): owner for field, owner in sorted(field_owners.items())
        }
        metadata["vanilla_field_coverage"] = decision_interfaces.coverage(baseline, field_owners)
    if information_rules is not None:
        rules_contract = decision_rules.contract(information_rules)
        metadata["decision_rules"] = rules_contract
        fingerprint = metadata["source_fingerprint"]
        enabled_modules = metadata["enabled_modules"]
        lifecycle = metadata["module_contract"]
        assert isinstance(fingerprint, dict)
        assert isinstance(enabled_modules, list)
        assert isinstance(lifecycle, dict)
        fingerprint.update(
            information_rules_source_sha256=information_rules.source_sha256,
            information_rules_generator_sha256=rules_contract["generator_sha256"],
        )
        enabled_modules.append("information_rules")
        lifecycle["information_rules"] = {
            "stateful": False,
            "direct_read": True,
            "hooks": [],
            "ttl_or_none": None,
            "clear_on_disable": "no_persistent_state",
            "save_compatibility": policy.package.save_compatibility,
        }
    if consumer_adapters is not None:
        adapter_files, adapter_contract = decision_adapters.build(
            consumer_adapters, overlays=files, texts=adapter_inputs
        )
        collisions = files.keys() & adapter_files.keys()
        if collisions - {"common/ai_strategies/00_default_strategy.txt"}:
            raise ValueError("消费者适配存在多个写入者：" + "、".join(sorted(collisions)))
        files.update(adapter_files)
        metadata["consumer_adapters"] = adapter_contract
        fingerprint = metadata["source_fingerprint"]
        enabled_modules = metadata["enabled_modules"]
        lifecycle = metadata["module_contract"]
        assert isinstance(fingerprint, dict)
        assert isinstance(enabled_modules, list)
        assert isinstance(lifecycle, dict)
        fingerprint.update(
            consumer_adapters_source_sha256=consumer_adapters.source_sha256,
            consumer_adapters_generator_sha256=adapter_contract["generator_sha256"],
            production_inputs_generator_sha256=adapter_contract[
                "production_inputs_generator_sha256"
            ],
            consumer_interfaces_sha256=hashlib.sha256(
                Path(decision_interfaces.__file__).read_bytes()
            ).hexdigest(),
        )
        enabled_modules.append("consumer_adapters")
        lifecycle["consumer_adapters"] = {
            "stateful": False,
            "direct_read": True,
            "hooks": [],
            "ttl_or_none": None,
            "clear_on_disable": "regenerate_without_adapter_files_and_restart",
            "save_compatibility": policy.package.save_compatibility,
        }
        if player_boundary_issues(files["common/ai_strategies/00_default_strategy.txt"]):
            raise ValueError("消费者适配违反玩家边界")
    strategic_policies = ([information_rules] if information_rules is not None else []) + (
        [row for _, row in consumer_adapters.policies] if consumer_adapters is not None else []
    )
    strategies = [row.strategy for row in strategic_policies if row.strategy is not None]
    if strategies:
        strategy = strategies[0]
        if any(other != strategy for other in strategies[1:]):
            raise ValueError("同一候选不能混合不同来源的战略意图")
        active_rules = [
            rule
            for row in strategic_policies
            for rule in row.rules
            if rule.domain in row.enabled_domains and rule.intent is not None
        ]
        strategic_contract = strategy.contract(
            {rule.intent for rule in active_rules if rule.intent}
        )
        metadata["strategic_coordination"] = {
            **strategic_contract,
            "rules_with_intent": len(active_rules),
            "runtime_state": "none",
            "behavior_verified": False,
            "limits": "nonexclusive_constraints; no_global_planner_or_persistent_country_intent",
        }
        fingerprint = metadata["source_fingerprint"]
        assert isinstance(fingerprint, dict)
        fingerprint.update(
            strategic_source_sha256=strategy.source_sha256,
            strategic_generator_sha256=strategic_contract["generator_sha256"],
        )
    files[".metadata/metadata.json"] = (
        json.dumps(
            metadata,
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    for name, text in files.items():
        if name.endswith((".txt", ".yml")):
            files[name] = re.sub(r"(?m)[\t ]+$", "", text)
    return files


def write(root: Path, files: Mapping[str, str] | None = None) -> list[Path]:
    files = files if files is not None else build()
    written: list[Path] = []
    for name, text in sorted(files.items()):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)
    # 新产物写入成功后才删除固定受控的旧文件；探针与用户文件交给 check 报告。
    stale_names = {
        "common/scripted_triggers/sitai_fiscal_triggers.txt",
        "common/scripted_effects/sitai_fiscal_effects.txt",
        "common/on_actions/sitai_fiscal_on_actions.txt",
        "common/scripted_triggers/sitai_reform_triggers.txt",
        "common/script_values/sitai_reform_values.txt",
        "common/scripted_triggers/sitai_security_triggers.txt",
        "common/scripted_triggers/sitai_economy_triggers.txt",
        "common/scripted_triggers/sitai_diplomacy_triggers.txt",
        "common/scripted_triggers/sitai_subjects_triggers.txt",
        *(localization_path(language, "sitai_decisions") for language in DEFAULT_LANGUAGES),
    }
    localization_root = root / "localization"
    if localization_root.is_dir():
        stale_names.update(
            str(path.relative_to(root)).replace("\\", "/")
            for path in localization_root.glob("*/sitai_decisions_l_*.yml")
        )
    for name in stale_names:
        if name not in files:
            (root / name).unlink(missing_ok=True)
    return written


def check(root: Path, files: Mapping[str, str] | None = None) -> list[str]:
    files = files if files is not None else build()
    issues = [
        f"{name} 与决策数据源不一致"
        for name, text in files.items()
        if not (root / name).is_file() or (root / name).read_bytes() != text.encode("utf-8")
    ]
    issues.extend(
        f"{p.relative_to(root)} 是未声明产物"
        for p in root.rglob("*")
        if p.is_file()
        and p.relative_to(root).parts[0] in {"common", "localization", ".metadata"}
        and p.relative_to(root).as_posix() not in files
    )
    return issues


def validate(
    vocabulary: set[str] | None,
    *,
    game: Path | None = None,
    snapshot: object | None = None,
    policy: Policy | None = None,
    extensions: Extensions | None = None,
) -> list[str]:
    """检查决策生成器实际生成的引擎接口及锁定底本。

    只凭目标词汇表集合无法验证所有产品接口：新生成的改革/市场字段需要
    对应 API 词汇证据；脚本解析成功不是引擎证据。快照域必须覆盖
    ``vocabulary``、``vanilla_keys`` 和 ``vanilla_variables``。
    """
    interfaces = set()
    policy = policy or load()
    if policy.enabled:
        interfaces |= {
            "is_ai",
            "is_at_war",
            "is_diplomatic_play_initiator",
            "is_diplomatic_play_target",
            "is_diplomatic_play_committed_participant",
            "has_variable",
            "in_default",
            "taking_loans",
            "credit",
            "weeks_until_bankruptcy",
            "set_variable",
            "remove_variable",
            "on_monthly_pulse_country",
            "on_country_default",
            "on_country_no_longer_default",
        }
    extensions = extensions or load_extensions()
    if extensions.reform_enabled:
        interfaces |= {"legitimacy", "any_insurrection_ongoing", "is_in_government"}
    if extensions.market_enabled:
        interfaces |= {"economic_dependence", "diplomatic_play_support"}
    if extensions.security_enabled:
        interfaces |= {
            "any_scope_treaty",
            "binds",
            "any_scope_article",
            "has_type",
            "is_adjacent_to_country",
            "play_participant_has_war_goal_of_type_against",
        }
    if extensions.economy_enabled:
        interfaces |= {
            "economic_vs_government_spending_balance",
            "taking_loans",
            "bureaucracy",
        }
    if extensions.diplomacy_enabled:
        interfaces |= {"recklessness", "in_default", "taking_loans"}
    if extensions.subjects_enabled:
        interfaces |= {
            "subject_value",
            "become_subject_value",
            "is_subject_of",
            "scope:overlord",
        }
    # 财政值属于独立的原版 script value 参考，而不是四个通用词汇目录。
    fiscal_words = vocabulary_dir(BASELINE.parent) if policy.enabled else set()
    if policy.enabled:
        fiscal_words |= {"credit", "weeks_until_bankruptcy"}
    if vocabulary is None:
        vocabulary_words: set[str] = set()
        vocabulary_uncovered = True
    else:
        vocabulary_words = vocabulary
        vocabulary_uncovered = False
    key_words = vocabulary_dir(BASELINE.parent)
    variable_words: set[str] = set()
    variable_uncovered = False
    script_value_interfaces = interfaces & {"economic_dependence"}
    script_value_words: set[str] = set()
    script_value_uncovered = bool(script_value_interfaces)
    if snapshot is not None:
        if not isinstance(snapshot, Mapping):
            return ["原版接口快照结构无效"]
        sections = snapshot.get("域", snapshot.get("sections"))
        if not isinstance(sections, Mapping):
            return ["原版接口快照缺少域映射"]
        vocabulary_section = sections.get("vocabulary")
        keys_section = sections.get("vanilla_keys")
        variables_section = sections.get("vanilla_variables")
        vocabulary_uncovered = not isinstance(vocabulary_section, Mapping) or any(
            rel not in vocabulary_section for rel in VOCABULARY_DIRS
        )
        if isinstance(vocabulary_section, Mapping):
            vocabulary_words = {
                word
                for rel in VOCABULARY_DIRS
                for word in vocabulary_section.get(rel, [])
                if isinstance(word, str)
            }
        keys_uncovered = not isinstance(keys_section, Mapping) or any(
            rel not in keys_section for rel in KEY_DIRS
        )
        if isinstance(keys_section, Mapping):
            key_words = {
                word
                for rel in KEY_DIRS
                for word in keys_section.get(rel, [])
                if isinstance(word, str)
            }
        variable_uncovered = not isinstance(variables_section, Mapping) or any(
            rel not in variables_section for rel in VARIABLE_POOL_DIRS
        )
        if isinstance(variables_section, Mapping):
            variable_words = {
                word
                for rel in VARIABLE_POOL_DIRS
                for word in variables_section.get(rel, [])
                if isinstance(word, str)
            }
        script_value_section = sections.get("script_value_accessors")
        if (
            script_value_interfaces
            and isinstance(script_value_section, Mapping)
            and SCRIPT_VALUE_ACCESSOR_DIR in script_value_section
        ):
            script_value_words = {
                word
                for word in script_value_section[SCRIPT_VALUE_ACCESSOR_DIR]
                if isinstance(word, str)
            }
            script_value_uncovered = False
        if keys_uncovered:
            return ["原版键快照缺失所需目录，无法校验 on_action / effect 接口"]
    elif game is not None:
        index = game_index(game)
        if index is None:
            return [
                "本机原版目录缺失，无法校验决策接口",
                "原版词汇、键和变量证据均不可用；不能把缺失输入当成通过",
            ]
        key_sets = [index.keys(rel) for rel in KEY_DIRS]
        if any(words is None for words in key_sets):
            return ["原版键目录缺失，无法校验 on_action / effect 接口"]
        key_words = set().union(*(words for words in key_sets if words is not None))
        variables = index.variables()
        if variables is None:
            variable_uncovered = True
        else:
            variable_words = variables
        if script_value_interfaces:
            script_value_words = script_value_accessors(game / SCRIPT_VALUE_ACCESSOR_DIR)
            script_value_uncovered = False
    else:
        # 兼容以往只检查通用词汇的调用，但把底本自带证据与自产物词汇分开；
        # 新模块所需接口不会被“所有目标词都存在于目标里”这件事验证。
        vocabulary_uncovered = True

    evidence_words = vocabulary_words | key_words | variable_words | fiscal_words
    ordinary_interfaces = interfaces - script_value_interfaces
    issues = [
        f"决策生成接口未被原版证据覆盖：{name}"
        for name in sorted(ordinary_interfaces - evidence_words)
    ]
    if script_value_uncovered and script_value_interfaces:
        issues.append("原版脚本值 API 快照缺少 common/script_values 域，读取接口检查未覆盖")
    else:
        issues.extend(
            f"决策生成接口未被原版脚本值证据覆盖：{name}"
            for name in sorted(script_value_interfaces - script_value_words)
        )
    if vocabulary_uncovered:
        issues.append("原版词汇快照缺少所需目录；接口词汇检查未覆盖，不算通过")
    if variable_uncovered and "has_variable" in interfaces:
        issues.append("原版变量写入快照缺失；变量 API 检查未覆盖，不算通过")
    if game is not None:
        path = game / "common/ai_strategies/00_default_strategy.txt"
        if not path.is_file() or normalized_text(
            path.read_text(encoding="utf-8-sig")
        ) != BASELINE.read_text(encoding="utf-8"):
            issues.append("本机默认策略与锁定底本不一致，需重审版本")
    if game is not None and policy.enabled:
        path = game / "common/script_values/war_support_values.txt"
        reference = BASELINE.parent / "war_support_values.txt"
        if not path.is_file() or normalized_text(
            path.read_text(encoding="utf-8-sig")
        ) != reference.read_text(encoding="utf-8"):
            issues.append("本机财政接口参考与锁定底本不一致，需重审版本")
    return issues
