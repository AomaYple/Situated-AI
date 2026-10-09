"""通用处境决策：真实财政状态与外部风险影响原版外交倾向。

生成完整默认策略的版本锁定副本，仅在两个已验证为相加的字段尾部追加条件。
不占三个策略槽，不改变重抽节奏，不保存或恢复开局牌。底本逐字保留并通过哈希
守住升级边界；该覆盖与其他修改 ai_strategy_default 的模组有兼容成本。
"""

from __future__ import annotations

import hashlib
import json
import math
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import config
from .lexer import LBRACE, RBRACE, tokenize
from .model import Block
from .parser import parse_text
from .textio import normalized_text
from .vanilla_index import (
    KEY_DIRS,
    VARIABLE_POOL_DIRS,
    VOCABULARY_DIRS,
    game_index,
    vocabulary_dir,
)

if TYPE_CHECKING:
    from pathlib import Path

SOURCE = config.REPO / "mod" / "decisions" / "fiscal.toml"
PRODUCT = config.REPO / "mod"
BASELINE = config.REPO / "research" / "vanilla-ai" / "1.14.5" / "00_default_strategy.txt"
RISK_VAR = "sitai_fiscal_risk"
ACTIVE_TRIGGER = "sitai_fiscal_external_risk"
VERSION = "0.2.0"
EXTENSIONS = SOURCE.with_name("extensions.toml")


@dataclass(frozen=True, slots=True)
class Policy:
    game_version: str
    baseline_sha256: str
    entry_weeks: int
    exit_weeks: int
    ttl_days: int
    neutrality: float
    aggression: float


@dataclass(frozen=True, slots=True)
class Extensions:
    reform_enabled: bool = False
    reform_legitimacy: int = 75
    fragile_legitimacy: int = 25
    reform_bonus: float = 1
    fragile_penalty: float = -0.5
    market_enabled: bool = False
    market_multiplier: float = 5


def load_extensions(source: Path = EXTENSIONS) -> Extensions:
    data = tomllib.loads(source.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema_version", "reform", "market"}
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
    return Extensions(
        reform["enabled"],
        reform["legitimacy"],
        reform["fragile_legitimacy"],
        reform["bonus"],
        reform["penalty"],
        market["enabled"],
        market["multiplier"],
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
    data = tomllib.loads(source.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema_version", "game_version", "baseline_sha256", "fiscal", "fields"}
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
        or not isinstance(data["fiscal"], dict)
        or not isinstance(data["fields"], dict)
    ):
        raise ValueError("决策版本、底本指纹或参数表无效；升级需重新审查")
    fiscal, fields = data["fiscal"], data["fields"]
    if set(fiscal) != {"entry_weeks", "exit_weeks", "ttl_days", "why"} or set(fields) != {
        "diplomatic_play_neutrality",
        "aggression",
        "why",
    }:
        raise ValueError("决策数据源含缺失或未知字段")
    if any(not isinstance(v, str) or not v.strip() for v in (fiscal["why"], fields["why"])):
        raise ValueError("每组决策参数必须给出依据")
    policy = Policy(
        data["game_version"],
        data["baseline_sha256"],
        fiscal["entry_weeks"],
        fiscal["exit_weeks"],
        fiscal["ttl_days"],
        fields["diplomatic_play_neutrality"],
        fields["aggression"],
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


def triggers(policy: Policy) -> str:
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
    return f"""# 由 pdx.decisions 生成；只有本更新器写入财政状态。
sitai_update_fiscal = {{
    if = {{
        limit = {{ is_ai = yes OR = {{ sitai_fiscal_entry = yes AND = {{ has_variable = {RISK_VAR} sitai_fiscal_hold = yes }} }} }}
        set_variable = {{ name = {RISK_VAR} value = 1 days = {policy.ttl_days} }}
    }}
    else = {{ remove_variable = {RISK_VAR} }}
}}
"""


def on_actions() -> str:
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
        raise ValueError("默认策略必须为块")
    lines = text.splitlines(keepends=True)
    changes: list[tuple[int, str]] = []
    additions = {
        field: f"\t\tif = {{\n\t\t\tlimit = {{ ROOT ?= {{ {ACTIVE_TRIGGER} = yes }} }}\n\t\t\tadd = {amount:g}\n\t\t}}\n"
        for field, amount in (
            ("diplomatic_play_neutrality", policy.neutrality),
            ("aggression", policy.aggression),
        )
        if amount != 0
    }
    if extensions and extensions.reform_enabled:
        additions["change_law_chance"] = (
            "\t\tif = { limit = { ROOT ?= { is_ai = yes } } add = sitai_reform_default_delta }\n"
        )
    if extensions and extensions.market_enabled:
        additions["diplomatic_play_support"] = f"""\t\tif = {{
\t\t\tlimit = {{ ROOT ?= {{ is_ai = yes }} exists = scope:country exists = scope:enemy_country }}
\t\t\tadd = {{
\t\t\t\tvalue = "ROOT.economic_dependence(scope:country)"
\t\t\t\tsubtract = "ROOT.economic_dependence(scope:enemy_country)"
\t\t\t\tmultiply = {extensions.market_multiplier:g}
\t\t\t\tdesc = SITAI_MARKET_DEPENDENCE_SUPPORT_REASON
\t\t\t}}
\t\t}}
"""
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
            extra = f"\t\t# SITAI BEGIN {field}\n{additions[field]}\t\t# SITAI END {field}\n"
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


def metadata_payload(policy: Policy | None = None) -> dict[str, object]:
    policy = policy or load()
    return {
        "name": "Situated AI · 处境决策",
        "id": "sitai.decisions",
        "version": VERSION,
        "supported_game_version": policy.game_version,
        "short_description": "真实财政与外部风险影响原版外交倾向；保留国家原有策略路线。",
        "tags": [],
        "relationships": [],
        "game_custom_data": {"multiplayer_synchronized": True},
    }


def build(
    policy: Policy | None = None,
    baseline: str | None = None,
    *,
    extensions: Extensions | None = None,
) -> dict[str, str]:
    policy = policy or load()
    baseline = baseline if baseline is not None else BASELINE.read_text(encoding="utf-8")
    extensions = extensions or load_extensions()
    files = {
        "common/ai_strategies/00_default_strategy.txt": patch_default(baseline, policy, extensions),
        "common/scripted_triggers/sitai_fiscal_triggers.txt": triggers(policy),
        "common/scripted_effects/sitai_fiscal_effects.txt": effects(policy),
        "common/on_actions/sitai_fiscal_on_actions.txt": on_actions(),
        ".metadata/metadata.json": json.dumps(
            metadata_payload(policy), ensure_ascii=False, indent=2
        )
        + "\n",
    }
    if extensions.reform_enabled:
        files["common/scripted_triggers/sitai_reform_triggers.txt"] = extension_triggers(extensions)
        files["common/script_values/sitai_reform_values.txt"] = extension_values(extensions)
    if extensions.market_enabled:
        for language, label in (
            ("english", "Economic exposure to both sides"),
            ("simp_chinese", "对博弈双方的经济依赖"),
        ):
            files[f"localization/{language}/sitai_decisions_l_{language}.yml"] = (
                f'l_{language}:\n SITAI_MARKET_DEPENDENCE_SUPPORT_REASON: "{label}"\n'
            )
    return files


def write(root: Path, files: Mapping[str, str] | None = None) -> list[Path]:
    files = files if files is not None else build()
    written: list[Path] = []
    for name, text in sorted(files.items()):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)
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
) -> list[str]:
    """检查决策生成器实际生成的引擎接口及锁定底本。

    只凭目标词汇表集合无法验证所有产品接口：新生成的改革/市场字段需要
    对应 API 词汇证据；脚本解析成功不是引擎证据。快照域必须覆盖
    ``vocabulary``、``vanilla_keys`` 和 ``vanilla_variables``。
    """
    interfaces = {
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
    extensions = load_extensions()
    if extensions.reform_enabled:
        interfaces |= {"legitimacy", "any_insurrection_ongoing", "is_in_government"}
    if extensions.market_enabled:
        interfaces |= {"economic_dependence", "diplomatic_play_support"}
    # 财政值属于独立的原版 script value 参考，而不是四个通用词汇目录。
    fiscal_words = vocabulary_dir(BASELINE.parent)
    fiscal_words |= {
        "credit",
        "weeks_until_bankruptcy",
    }
    if vocabulary is None:
        vocabulary_words: set[str] = set()
        vocabulary_uncovered = True
    else:
        vocabulary_words = vocabulary
        vocabulary_uncovered = False
    key_words = vocabulary_dir(BASELINE.parent)
    variable_words: set[str] = set()
    variable_uncovered = False
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
    else:
        # 兼容以往只检查通用词汇的调用，但把底本自带证据与自产物词汇分开；
        # 新模块所需接口不会被“所有目标词都存在于目标里”这件事验证。
        vocabulary_uncovered = True

    evidence_words = vocabulary_words | key_words | variable_words | fiscal_words
    issues = [
        f"决策生成接口未被原版证据覆盖：{name}" for name in sorted(interfaces - evidence_words)
    ]
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
        path = game / "common/script_values/war_support_values.txt"
        reference = BASELINE.parent / "war_support_values.txt"
        if not path.is_file() or normalized_text(
            path.read_text(encoding="utf-8-sig")
        ) != reference.read_text(encoding="utf-8"):
            issues.append("本机财政接口参考与锁定底本不一致，需重审版本")
    return issues
