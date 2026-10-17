"""A5 选中国家的只读解释候选；显式生成隔离实验 ZIP，不安装或运行游戏。

独立根控件已被实机否证；候选在原生国家面板内实例化，作用域及帧成本待验。
探针组件只读；
实验 ZIP 包含所选生产变体，保证配置说明与随包玩法来自同一输入。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from . import config, decisions, distribution
from .lexer import STRING, tokenize
from .localization_languages import DEFAULT_LANGUAGES, Language, localization_path

if TYPE_CHECKING:
    from collections.abc import Mapping

PREFIX = "sitai_explain_probe"
GUI = f"gui/{PREFIX}.gui"
PANEL = "gui/country_panel.gui"
SGUI = f"common/scripted_guis/{PREFIX}.txt"


# 新增模块的提示使用独立的 11 语言源表。旧的财政/基础提示仍保留英语回退，
# 并由 metadata 明确列出回退语言；没有博弈双方或国家上下文时只显示边界说明。
_MODULE_LOCALIZATION: dict[str, dict[str, str]] = {
    "economy_rules": {
        "braz_por": "Economia e administração: contexto econômico ausente; nenhum valor calculado.",
        "english": "Economy and administration: economic context is unavailable; no value calculated.",
        "french": "Économie et administration : le contexte économique est absent ; aucune valeur calculée.",
        "german": "Wirtschaft und Verwaltung: Der Wirtschaftskontext fehlt; kein Wert wird berechnet.",
        "japanese": "経済・行政：経済コンテキストがないため、値は計算しません。",
        "korean": "경제 및 행정: 경제 맥락이 없어 값을 계산하지 않습니다.",
        "polish": "Gospodarka i administracja: brak kontekstu gospodarczego; nie obliczono wartości.",
        "russian": "Экономика и администрация: экономический контекст отсутствует; значение не вычисляется.",
        "simp_chinese": "经济与行政：缺少经济上下文；不计算数值。",
        "spanish": "Economía y administración: falta el contexto económico; no se calcula ningún valor.",
        "turkish": "Ekonomi ve yönetim: ekonomik bağlam yok; değer hesaplanmaz.",
    },
    "diplomacy_rules": {
        "braz_por": "Diplomacia e guerra: faltam os lados do jogo; nenhuma carga é calculada.",
        "english": "Diplomacy and war: play sides are unavailable; no burden is calculated.",
        "french": "Diplomatie et guerre : les parties du jeu sont absentes ; aucune charge calculée.",
        "german": "Diplomatie und Krieg: Die Spielparteien fehlen; keine Belastung wird berechnet.",
        "japanese": "外交・戦争：ゲームの当事者がないため、負担は計算しません。",
        "korean": "외교 및 전쟁: 게임 당사자가 없어 부담을 계산하지 않습니다.",
        "polish": "Dyplomacja i wojna: brak stron rozgrywki; nie obliczono obciążenia.",
        "russian": "Дипломатия и война: стороны игры недоступны; нагрузка не вычисляется.",
        "simp_chinese": "外交与战争：缺少博弈双方；不计算负担。",
        "spanish": "Diplomacia y guerra: faltan las partes de la jugada; no se calcula la carga.",
        "turkish": "Diplomasi ve savaş: oyun tarafları yok; yük hesaplanmaz.",
    },
    "subjects_rules": {
        "braz_por": "Relação de suserano e súdito: contexto bilateral ausente; nenhum valor calculado.",
        "english": "Overlord and subject: bilateral context is unavailable; no value calculated.",
        "french": "Suzerain et sujet : le contexte bilatéral est absent ; aucune valeur calculée.",
        "german": "Oberherr und Untertan: Der bilaterale Kontext fehlt; kein Wert wird berechnet.",
        "japanese": "宗主国・属国：二国間コンテキストがないため、値は計算しません。",
        "korean": "종주국 및 종속국: 양자 맥락이 없어 값을 계산하지 않습니다.",
        "polish": "Zwierzchnik i podmiot: brak kontekstu dwustronnego; nie obliczono wartości.",
        "russian": "Сюзерен и субъект: двусторонний контекст отсутствует; значение не вычисляется.",
        "simp_chinese": "宗主国与属国：缺少双边上下文；不计算数值。",
        "spanish": "Soberano y súbdito: falta el contexto bilateral; no se calcula ningún valor.",
        "turkish": "Süzeren ve tabi ülke: ikili bağlam yok; değer hesaplanmaz.",
    },
}

# F0 要求每种本体语言都有完整的自有键源文本。基础说明键数量较多，先为
# 每种语言提供明确标注为“候选草稿”的本地化句式；F1 再由逐语言审校替换
# 术语和 UI 语境。它们不再静默复用英语源文本，也不会被记录为回退。
_DRAFT_SENTENCE = {
    "braz_por": "Rascunho de explicação para {key}; contexto desconhecido permanece desconhecido.",
    "french": "Brouillon d’explication pour {key} ; le contexte inconnu reste inconnu.",
    "german": "Erklärungsentwurf für {key}; unbekannter Kontext bleibt unbekannt.",
    "japanese": "{key} の説明草稿です。不明なコンテキストは不明のままです。",
    "korean": "{key} 설명 초안입니다. 알 수 없는 맥락은 알 수 없음으로 유지합니다.",
    "polish": "Wersja robocza wyjaśnienia dla {key}; nieznany kontekst pozostaje nieznany.",
    "russian": "Черновик объяснения для {key}; неизвестный контекст остаётся неизвестным.",
    "spanish": "Borrador de explicación para {key}; el contexto desconocido sigue desconocido.",
    "turkish": "{key} için açıklama taslağıdır; bilinmeyen bağlam bilinmiyor olarak kalır.",
}


def _draft_localization(language: Language, rows: Mapping[str, tuple[str, str]]) -> dict[str, str]:
    """为非中英文生成显式候选草稿，避免静默英语回退。"""

    template = _DRAFT_SENTENCE.get(language.directory)
    if template is None:
        return {}
    result: dict[str, str] = {}
    for key, pair in rows.items():
        numbers = " ".join(re.findall(r"[-+]?\d+(?:\.\d+)?", pair[1]))
        suffix = f" ({numbers})" if numbers else ""
        result[key] = template.format(key=key) + suffix
    return result


def localization_fallback_languages(
    languages: tuple[Language, ...] = DEFAULT_LANGUAGES,
) -> list[str]:
    """返回解释探针缺少显式键值的语言目录。

    F0 为所有本体语言生成完整的键集合。部分旧说明的语义仍需要 F1
    逐语言审校，因此另行记录审校清单；语义审校不能伪装成结构性缺键。
    """

    required = set(_localization_keys())
    # 所有当前锁定语言均有显式源文本；若新增语言没有草稿，才算结构回退。
    return sorted(
        language.directory
        for language in languages
        if language.directory not in {"english", "simp_chinese"}
        and (language.directory not in _DRAFT_SENTENCE or not required)
    )


def localization_review_languages(
    languages: tuple[Language, ...] = DEFAULT_LANGUAGES,
) -> list[str]:
    """返回仍需 F1 术语与语境审校的候选草稿语言。"""

    return sorted(
        language.directory
        for language in languages
        if language.directory not in {"english", "simp_chinese"}
    )


def _localization_keys() -> tuple[str, ...]:
    """返回所有基础和扩展解释键，供结构覆盖与回退计算共用。"""

    keys = {
        "title",
        "config",
        "off",
        "ai",
        "human",
        "risk",
        "no_risk",
        "hold",
        "no_hold",
        "exposure",
        "no_exposure",
        "active",
        "inactive",
        "default",
        "not_default",
        "rules",
        "boundary",
        "reform_fragile",
        "reform_not_fragile",
        "reform_opportunity",
        "reform_no_opportunity",
        "market_rules",
        "security_rules",
        "economy_rules",
        "diplomacy_rules",
        "subjects_rules",
    }
    return tuple(sorted(keys))


def _choice(condition: str, yes: str, no: str) -> str:
    return (
        f"    if = {{ limit = {{ {condition} }} custom_tooltip = {PREFIX}_{yes} }}\n"
        f"    else = {{ custom_tooltip = {PREFIX}_{no} }}\n"
    )


def _script(policy: decisions.Policy, extra: decisions.Extensions) -> str:
    # ExecuteTooltip 只构建说明。闭合的效果子集不含 Execute、写变量或扫描。
    body = f"    custom_tooltip = {PREFIX}_config\n"
    if not policy.enabled:
        body += f"    custom_tooltip = {PREFIX}_off\n"
    else:
        body += "    if = { limit = { is_ai = yes }\n"
        body += f"    custom_tooltip = {PREFIX}_ai\n"
        body += _choice(f"has_variable = {decisions.RISK_VAR}", "risk", "no_risk")
        body += _choice("sitai_fiscal_hold = yes", "hold", "no_hold")
        body += _choice("sitai_external_exposure = yes", "exposure", "no_exposure")
        body += _choice(f"{decisions.ACTIVE_TRIGGER} = yes", "active", "inactive")
        body += _choice("in_default = yes", "default", "not_default")
        body += "    } else = { custom_tooltip = " + PREFIX + "_human }\n"
    body += f"    custom_tooltip = {PREFIX}_rules\n"
    if extra.reform_enabled:
        body += "    if = { limit = { is_ai = yes }\n"
        body += _choice("sitai_reform_fragile = yes", "reform_fragile", "reform_not_fragile")
        body += _choice(
            "sitai_reform_opportunity = yes",
            "reform_opportunity",
            "reform_no_opportunity",
        )
        body += "    }\n"
    if extra.market_enabled:
        body += f"    custom_tooltip = {PREFIX}_market_rules\n"
    if extra.security_enabled:
        body += f"    custom_tooltip = {PREFIX}_security_rules\n"
    if extra.economy_enabled:
        body += f"    custom_tooltip = {PREFIX}_economy_rules\n"
    if extra.diplomacy_enabled:
        body += f"    custom_tooltip = {PREFIX}_diplomacy_rules\n"
    if extra.subjects_enabled:
        body += f"    custom_tooltip = {PREFIX}_subjects_rules\n"
    body += f"    custom_tooltip = {PREFIX}_boundary\n"
    return f"{PREFIX} = {{\n    scope = country\n    effect = {{\n{body}    }}\n}}\n"


def _localization(policy: decisions.Policy, extra: decisions.Extensions) -> dict[str, str]:
    state_zh = "启用" if policy.enabled else "关闭"
    state_en = "enabled" if policy.enabled else "disabled"
    config_zh = (
        f"配置：财政{state_zh}；改革{'启用' if extra.reform_enabled else '关闭'}；"
        f"市场{'启用' if extra.market_enabled else '关闭'}；"
        f"security={'启用' if extra.security_enabled else '关闭'}。"
    )
    config_en = (
        f"Configuration: fiscal {state_en}; reform "
        f"{'enabled' if extra.reform_enabled else 'disabled'}; market "
        f"{'enabled' if extra.market_enabled else 'disabled'}; security "
        f"{'enabled' if extra.security_enabled else 'disabled'}."
    )
    rows = {
        "title": ("处境说明 · 未验证探针", "Situated explanation - unverified probe"),
        "config": (config_zh, config_en),
        "off": (
            "财政模块关闭；不判断财政安全或当前风险。",
            "Fiscal module disabled; no claim of fiscal safety or current risk.",
        ),
        "ai": (
            "查看对象为 AI 国家；以下为当前条件。",
            "Viewed country is AI; current conditions follow.",
        ),
        "human": (
            "查看对象不是 AI；财政干预不适用，不代表财政安全。",
            "Viewed country is not AI; fiscal intervention is inapplicable, not proof of fiscal safety.",
        ),
        "risk": (
            "风险记忆：存在（不等于当前偏置生效）。",
            "Risk memory: present (does not imply active bias).",
        ),
        "no_risk": (
            "风险记忆：不存在；可能尚未重评估，不代表安全。",
            "Risk memory: absent; reassessment may be pending, not proof of safety.",
        ),
        "hold": ("维持条件：满足。", "Hold condition: met."),
        "no_hold": (
            "维持条件：未满足；可能缺少有效读数，不代表安全。",
            "Hold condition: not met; valid readings may be unavailable, not proof of safety.",
        ),
        "exposure": (
            "外部暴露：存在；未选边不等于承诺。",
            "External exposure: present; undecided is not committed.",
        ),
        "no_exposure": (
            "外部暴露：当前条件未满足。",
            "External exposure: current condition not met.",
        ),
        "active": (
            f"ACTIVE 条件满足：规则追加中立倾向 {policy.neutrality:+g}、攻击性 {policy.aggression:+g}；不是概率或行动。",
            f"ACTIVE condition met: rule adds neutrality {policy.neutrality:+g}, aggression {policy.aggression:+g}; not a probability or action.",
        ),
        "inactive": (
            "ACTIVE 条件未满足：当前不追加财政偏置，不代表安全。",
            "ACTIVE condition not met: no current fiscal bias; not proof of safety.",
        ),
        "default": (
            "主要条件：违约；优先于借款和破产周数分支。",
            "Main condition: default; takes precedence over borrowing and bankruptcy weeks.",
        ),
        "not_default": (
            "当前未违约；风险进入/维持仍需借款、正信用和有效破产周数。",
            "Not currently in default; entry/hold still requires borrowing, positive credit and valid bankruptcy weeks.",
        ),
        "rules": (
            f"启用时：违约或借款、正信用且破产周数非负并小于 {policy.entry_weeks} 周进入；已有风险使用 {policy.exit_weeks} 周维持线。月度、违约/结束违约重评估；不满足维持条件退出，最后续期后 {policy.ttl_days} 天自然失效。外部暴露包括战争与博弈发起、目标、已承诺、未选边。",
            f"While enabled: default or borrowing with positive credit and non-negative bankruptcy weeks below {policy.entry_weeks} enters risk; existing risk uses a {policy.exit_weeks}-week hold line. Monthly and default/end-of-default events reassess; failing hold exits, and memory expires {policy.ttl_days} days after last renewal. Exposure includes war and play initiator, target, committed or undecided participant.",
        ),
        "boundary": (
            "只读候选：国家上下文/刷新未实机验收；不提供最终评分、净代价、不利结果或 AI 质量结论。未知保持未知。",
            "Read-only candidate: country context/refresh unverified in engine; no final score, net cost, adverse outcome or AI quality conclusion. Unknown remains unknown.",
        ),
    }
    if extra.reform_enabled:
        rows.update(
            {
                "reform_fragile": (
                    f"改革脆弱条件满足：default 启动贡献 {extra.fragile_penalty:+g}。",
                    f"Reform fragile condition met: default start contribution {extra.fragile_penalty:+g}.",
                ),
                "reform_not_fragile": (
                    "改革脆弱条件未满足。",
                    "Reform fragile condition not met.",
                ),
                "reform_opportunity": (
                    f"改革机会代理满足：脆弱条件不满足时 default 贡献 {extra.reform_bonus:+g}；不证明具体法律可行。",
                    f"Reform opportunity proxy met: default contribution {extra.reform_bonus:+g} unless fragile; not proof of a feasible law.",
                ),
                "reform_no_opportunity": (
                    "改革机会代理未满足；不等于没有可行法律。",
                    "Reform opportunity proxy not met; does not prove no law is feasible.",
                ),
            }
        )
    if extra.market_enabled:
        rows["market_rules"] = (
            f"market：双方依赖差×{extra.market_multiplier:g}，支持贡献范围 ±{5 * extra.market_multiplier:g}；国家面板缺少明确博弈双方，不计算本次分数。",
            f"market: dependence difference x {extra.market_multiplier:g}, bounded by +/-{5 * extra.market_multiplier:g}; this panel lacks play-side context and does not calculate a score.",
        )
    if extra.security_enabled:
        rows["security_rules"] = (
            f"security：防御条约/联盟 {extra.security_commitment_bonus:g}，邻国征服/附庸风险 {extra.security_threat_bonus:g}，只取最高理由；进攻方反向。面板缺少博弈双方，不声称当前贡献。",
            f"security: defense treaty/alliance {extra.security_commitment_bonus:g}, threatened-neighbor defense {extra.security_threat_bonus:g}; maximum reason only, opposite sign for attacker. No current contribution without play-side context.",
        )
    for key in ("economy_rules", "diplomacy_rules", "subjects_rules"):
        if getattr(extra, key.removesuffix("_rules") + "_enabled"):
            rows[key] = (
                _MODULE_LOCALIZATION[key]["simp_chinese"],
                _MODULE_LOCALIZATION[key]["english"],
            )
    drafts = {
        language.directory: _draft_localization(language, rows) for language in DEFAULT_LANGUAGES
    }
    result = {}
    for language in DEFAULT_LANGUAGES:
        lines = [f"{language.header}:"]
        for key, pair in rows.items():
            # 游戏本地化使用带引号单行文本；按 JSON 的共同转义子集处理引号与换行。
            draft = drafts.get(language.directory, {}).get(key)
            value = json.dumps(
                _MODULE_LOCALIZATION[key].get(language.directory, pair[1])
                if key in _MODULE_LOCALIZATION
                else (
                    pair[0]
                    if language.directory == "simp_chinese"
                    else pair[1]
                    if language.directory == "english"
                    else draft or pair[1]
                ),
                ensure_ascii=False,
            )
            lines.append(f" {PREFIX}_{key}:0 {value}")
        result[localization_path(language, PREFIX)] = "\n".join(lines) + "\n"
    return result


def build(policy: decisions.Policy, extra: decisions.Extensions) -> dict[str, str]:
    """只返回命名空间隔离的只读组件；不生成生产机制或覆盖国家面板。"""
    files = {
        GUI: f"""types {PREFIX}_types {{
    type {PREFIX} = widget {{
        name = "{PREFIX}"
        size = {{ 620 460 }}
        position = {{ 560 160 }}
        visible = "[Country.IsValid]"
            vbox = {{
                textbox = {{ text = "{PREFIX}_title" autoresize = yes }}
                textbox = {{ raw_text = "[Country.GetNameNoFormatting]" autoresize = yes }}
                textbox = {{
                    size = {{ 600 400 }}
                    multiline = yes
                    raw_text = "[GetScriptedGui('{PREFIX}').ExecuteTooltip(GuiScope.SetRoot(Country.MakeScope).End)]"
                }}
            }}
    }}
}}
""",
        SGUI: _script(policy, extra),
    }
    files.update(_localization(policy, extra))
    return files


def _extend_country_panel(text: str) -> str:
    """只在唯一原生类型内追加实例；引号/注释内的括号不影响边界。

    GUI 有命名 types 等专用语法，不能用通用脚本 AST 猜层级。复用词法器
    定位确切类型与直接国家上下文；任何歧义均拒绝，不做模糊文本替换。
    """
    if "\r" in text or text.startswith("\ufeff"):
        raise ValueError("国家面板底本必须先规范化为 UTF-8 无 BOM、LF")
    tokens = tokenize(text)
    depth = 0
    depths = []
    for token in tokens:
        depths.append(depth)
        if token.kind == STRING:
            # 词法器容错保留未闭合字符串；生成覆盖文件必须拒绝它，包含末尾转义引号。
            before_quote = token.value[:-1]
            escapes = len(before_quote) - len(before_quote.rstrip("\\"))
            if len(token.value) < 2 or not token.value.endswith('"') or escapes % 2:
                raise ValueError("国家面板底本含未闭合字符串")
        elif token.value == "{":
            depth += 1
        elif token.value == "}":
            depth -= 1
            if depth < 0:
                raise ValueError("国家面板底本存在多余闭合边界")
    if depth:
        raise ValueError("国家面板底本缺少闭合边界")
    starts = [
        index
        for index in range(len(tokens) - 2)
        if [token.value for token in tokens[index : index + 3]] == ["type", "country_panel", "="]
    ]
    if len(starts) != 1 or any(token.value.strip('"') == PREFIX for token in tokens):
        raise ValueError("国家面板底本类型不唯一、已注入或接口发生变化")
    declaration = starts[0]
    if depths[declaration] != 1 or [
        token.value for token in tokens[declaration + 3 : declaration + 5]
    ] != ["default_block_window_two_lines", "{"]:
        raise ValueError("国家面板底本类型层级或基类发生变化")
    start = starts[0] + 4
    depth = 0
    contexts = []
    closing = None
    for index in range(start, len(tokens)):
        token = tokens[index]
        if token.value == "{":
            depth += 1
        elif token.value == "}":
            depth -= 1
            if depth == 0:
                closing = token
                break
        elif token.value == "datacontext" and depth == 1:
            contexts.append([item.value for item in tokens[index + 1 : index + 3]])
    if closing is None or contexts != [["=", '"[CountryPanel.GetCountry]"']]:
        raise ValueError("国家面板底本缺少唯一直接国家上下文或闭合边界")
    # 与词法器使用同一种 LF 行号；splitlines 会把字符串内的 U+2028 误算成新行。
    offset = sum(len(line) + 1 for line in text.split("\n")[: closing.line - 1])
    offset += closing.col - 1
    return text[:offset] + f"\n\t\t{PREFIX} = {{}}\n\t" + text[offset:]


def attach(
    files: dict[str, str], policy: decisions.Policy, extra: decisions.Extensions
) -> dict[str, str]:
    """给实际玩法附加同源只读候选；不修改传入映射或安装目录。"""
    files = dict(files)
    installed_version = config.game_version().get("caligula_branch", "").split("/")[-1]
    if installed_version != policy.game_version:
        raise ValueError("解释实验包需要与生产版本一致的本机国家面板底本")
    panel_bytes = (config.GAME / PANEL).read_bytes()
    panel = panel_bytes.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    files[PANEL] = _extend_country_panel(panel)
    files.update(build(policy, extra))
    metadata = json.loads(files[".metadata/metadata.json"])
    metadata["status"] = "experimental"
    metadata["game_custom_data"]["multiplayer_synchronized"] = False
    metadata.setdefault("game_custom_data", {})["explanation_probe"] = {
        "schema": 1,
        "engine_verified": False,
        "quality_improvement_proven": False,
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "country_panel": {
            "path": PANEL,
            "source_sha256": hashlib.sha256(panel_bytes).hexdigest(),
            "normalized_sha256": hashlib.sha256(panel.encode("utf-8")).hexdigest(),
            "generated_sha256": hashlib.sha256(files[PANEL].encode("utf-8")).hexdigest(),
            "compatibility": "overrides_native_country_panel",
        },
        "fiscal": asdict(policy),
        "extensions": asdict(extra),
    }
    localization = metadata.setdefault("localization", {})
    production_fallback = sorted(
        set(
            localization.get(
                "production_fallback_languages",
                localization.get("fallback_languages", []),
            )
        )
    )
    explanation_fallback = localization_fallback_languages()
    localization["production_fallback_languages"] = production_fallback
    localization["explanation_fallback_languages"] = explanation_fallback
    localization["explanation_review_languages"] = localization_review_languages()
    localization["fallback_languages"] = sorted(
        set(production_fallback) | set(explanation_fallback)
    )
    localization["fallback_policy"] = (
        "explicit-production-and-explanation-fallbacks"
        if localization["fallback_languages"]
        else "none"
    )
    metadata["source_fingerprint"]["explanation_generator_sha256"] = hashlib.sha256(
        Path(__file__).read_bytes()
    ).hexdigest()
    metadata["source_fingerprint"]["country_panel_sha256"] = hashlib.sha256(panel_bytes).hexdigest()
    files[".metadata/metadata.json"] = json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
    return files


def package(destination: Path, *, variant: str = "disabled") -> Path:
    """显式生成自包含实验包；保留生产变体字节，仅追加只读组件及探针身份。"""
    policy, extra, files = distribution.package_inputs(variant)
    files = attach(files, policy, extra)
    metadata = json.loads(files[".metadata/metadata.json"])
    metadata["id"] = "sitai.explanation-probe"
    metadata["name"] = "Situated AI - A5 未验证解释探针"
    metadata["game_custom_data"]["explanation_probe"]["variant"] = variant
    files[".metadata/metadata.json"] = json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
    files["README.md"] = (
        "A5 未验证解释探针 / Unverified A5 explanation probe\n\n"
        "本 ZIP 自包含所选生产变体与只读说明组件；只挂载这一包，不与生产包或其他变体并挂。"
        "生成不安装、不启动、不登记游戏实验，也不解除已停止窗口。\n"
        "在合法实机窗口依次检查无国家面板、两个 AI 国家切换、玩家/观察者、开/关、"
        "状态退出、中英语言与可见/隐藏帧成本；发现错误停止并保留原件。"
        "实验包从匹配版本本机底本生成 country_panel.gui 覆盖，只在原生国家上下文内追加实例；"
        "不与其他国家面板覆盖兼容。底本和输出指纹入清单，不修改游戏安装。"
        "控件当前使用固定位置/尺寸，仅供作用域否证，不是可发布布局。\n"
        "Self-contained: mount this ZIP alone, never alongside production or another variant. "
        "Generation does not install, launch, register a run or reopen stopped windows. "
        "The ZIP overrides country_panel.gui generated from a matching local game version; "
        "it conflicts with other country-panel overrides and never edits the game installation. "
        "Context, refresh, layout and frame cost remain unverified; this is not a release.\n\n"
        + files["README.md"]
    )
    return distribution.write_zip(
        files,
        destination,
        generation={"purpose": "a5-explanation-instrument", "variant": variant},
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="隔离实验 ZIP 输出路径")
    parser.add_argument("--variant", choices=("current", "control", "disabled"), default="disabled")
    args = parser.parse_args(argv)
    try:
        target = package(args.output, variant=args.variant)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"解释探针生成失败：{exc}\n")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
