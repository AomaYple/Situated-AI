"""A5 选中国家的只读解释候选；显式生成隔离实验 ZIP，不安装或运行游戏。

控件作用域、隐藏控件求值及帧成本尚未通过引擎验证。探针组件只读；
实验 ZIP 包含所选生产变体，保证配置说明与随包玩法来自同一输入。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from . import decisions, distribution

PREFIX = "sitai_explain_probe"
GUI = f"gui/{PREFIX}.gui"
SGUI = f"common/scripted_guis/{PREFIX}.txt"


def _choice(condition: str, yes: str, no: str) -> str:
    return (
        f"    if = {{ limit = {{ {condition} }} custom_tooltip = {PREFIX}_{yes} }}\n"
        f"    else = {{ custom_tooltip = {PREFIX}_{no} }}\n"
    )


def _script(policy: decisions.Policy) -> str:
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
    body += f"    custom_tooltip = {PREFIX}_boundary\n"
    return f"{PREFIX} = {{\n    scope = country\n    effect = {{\n{body}    }}\n}}\n"


def _localization(policy: decisions.Policy, extra: decisions.Extensions) -> dict[str, str]:
    state_zh = "启用" if policy.enabled else "关闭"
    state_en = "enabled" if policy.enabled else "disabled"
    config_zh = (
        f"配置：财政{state_zh}；改革{'启用' if extra.reform_enabled else '关闭'}；"
        f"市场{'启用' if extra.market_enabled else '关闭'}。"
    )
    config_en = (
        f"Configuration: fiscal {state_en}; reform "
        f"{'enabled' if extra.reform_enabled else 'disabled'}; market "
        f"{'enabled' if extra.market_enabled else 'disabled'}."
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
    result = {}
    for column, language in enumerate(("simp_chinese", "english")):
        lines = [f"l_{language}:"]
        for key, pair in rows.items():
            # 游戏本地化使用带引号单行文本；按 JSON 的共同转义子集处理引号与换行。
            value = json.dumps(pair[column], ensure_ascii=False)
            lines.append(f" {PREFIX}_{key}:0 {value}")
        result[f"localization/{language}/{PREFIX}_l_{language}.yml"] = "\n".join(lines) + "\n"
    return result


def build(policy: decisions.Policy, extra: decisions.Extensions) -> dict[str, str]:
    """只返回命名空间隔离的只读组件；不生成生产机制或覆盖国家面板。"""
    files = {
        f"gui/scripted_widgets/{PREFIX}.txt": f"{GUI} = {PREFIX}\n",
        GUI: f"""types {PREFIX}_types {{
    type {PREFIX} = widget {{
        name = "{PREFIX}"
        size = {{ 620 460 }}
        position = {{ 700 160 }}
        visible = "[InformationPanelBar.IsPanelOpen('country_panel')]"
        widget = {{
            datacontext = "[CountryPanel.GetCountry]"
            size = {{ 100% 100% }}
            vbox = {{
                visible = "[Country.IsValid]"
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
}}
""",
        SGUI: _script(policy),
    }
    files.update(_localization(policy, extra))
    return files


def package(destination: Path, *, variant: str = "disabled") -> Path:
    """显式生成自包含实验包；保留生产变体字节，仅追加只读组件及探针身份。"""
    policy, extra, files = distribution.package_inputs(variant)
    files.update(build(policy, extra))
    metadata = json.loads(files[".metadata/metadata.json"])
    metadata["id"] = "sitai.explanation-probe"
    metadata["name"] = "Situated AI - A5 未验证解释探针"
    metadata["status"] = "experimental"
    metadata["game_custom_data"]["multiplayer_synchronized"] = False
    metadata.setdefault("game_custom_data", {})["explanation_probe"] = {
        "schema": 1,
        "variant": variant,
        "engine_verified": False,
        "quality_improvement_proven": False,
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "fiscal": asdict(policy),
        "extensions": asdict(extra),
    }
    files[".metadata/metadata.json"] = json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
    files["README.md"] = (
        "A5 未验证解释探针 / Unverified A5 explanation probe\n\n"
        "本 ZIP 自包含所选生产变体与只读说明组件；只挂载这一包，不与生产包或其他变体并挂。"
        "生成不安装、不启动、不登记游戏实验，也不解除已停止窗口。\n"
        "在合法实机窗口依次检查无国家面板、两个 AI 国家切换、玩家/观察者、开/关、"
        "状态退出、中英语言与可见/隐藏帧成本；发现错误停止并保留原件。"
        "控件当前使用固定位置/尺寸，仅供作用域否证，不是可发布布局。\n"
        "Self-contained: mount this ZIP alone, never alongside production or another variant. "
        "Generation does not install, launch, register a run or reopen stopped windows. "
        "Context, refresh, layout and frame cost remain unverified; this is not a release.\n\n"
        + files["README.md"]
    )
    return distribution.write_zip(
        files, destination, generation={"purpose": "a5-explanation-instrument", "variant": variant}
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
