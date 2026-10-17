"""确定性游戏 ZIP：仓库无 BOM，交付脚本与本地化带 BOM。"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import zipfile
from dataclasses import asdict, replace
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from pdx import decisions, explanation_probe
from pdx.textio import GAME_SUFFIXES, text_bytes

if TYPE_CHECKING:
    from collections.abc import Mapping

PACKAGE_VARIANTS = (
    "current",
    "control",
    "disabled",
    "complete",
    "fiscal",
    "security",
    "market",
    "reform",
    "economy",
    "diplomacy",
    "subjects",
    "full",
)


def player_guide(
    policy: decisions.Policy,
    extensions: decisions.Extensions,
    modules: list[str],
    *,
    variant: str,
) -> str:
    """为每个交付变体生成准确的中英使用说明。

    说明是包的一部分而不是仓库手写副本，所有数值和启用模块都来自实际
    打包参数。它解释规则和边界，不把建议、评分或加载成功写成 AI 行动。
    """
    if variant not in PACKAGE_VARIANTS:
        raise ValueError("说明变体无效：" + "、".join(PACKAGE_VARIANTS))
    module_text = "、".join(modules) if modules else "无（安全包）"
    module_text_en = ", ".join(modules) if modules else "none (safe package)"
    fiscal_state = "启用" if policy.enabled else "关闭"
    bias = (
        f"外交博弈中立偏置 +{policy.neutrality:g}，攻击性偏置 {policy.aggression:g}"
        if policy.enabled
        else "不写入财政状态或外交偏置"
    )
    bias_en = (
        f"diplomatic-play neutrality +{policy.neutrality:g}; aggression {policy.aggression:g}"
        if policy.enabled
        else "no fiscal state or diplomatic bias is written"
    )
    return (
        "Situated AI · 处境决策\n"
        "===========================\n"
        f"变体：{variant}\n"
        f"产品版本 / Product version：{policy.package.product_version}\n"
        f"父包 / Parent：{policy.package.parent}\n"
        f"游戏版本：{policy.game_version}\n"
        f"启用模块：{module_text}\n"
        f"财政模块：{fiscal_state}\n"
        f"状态 / Status：{policy.package.status}\n"
        f"存档兼容声明 / Save compatibility：{policy.package.save_compatibility}\n\n"
        "【中文】\n"
        "本说明描述本 ZIP 的规则配置，不显示任何国家当前的实时状态。生成包不代表"
        "V0.1 或 AI 行为质量已经验收；experimental 和 candidate 包仅供隔离测试。\n"
        "以下财政规则仅在财政模块启用时执行，零偏置控制包也不产生新增外交倾向。\n"
        f"AI 国家违约时进入财政风险；未违约时，需要正在借款、信用大于 0，且破产周数"
        f"非负并小于 {policy.entry_weeks} 周。已有风险使用 {policy.exit_weeks} 周的维持线，"
        "达到该线、不再借款或缺少必要的有效财政读数时不再维持；违约分支优先。\n"
        f"月度以及违约/结束违约事件重新评估；最后一次续期后 {policy.ttl_days} 天没有更新，"
        "风险状态自然失效。只有 AI 当前同时满足财政风险、维持条件与外部暴露条件时，"
        f"才追加原版字段偏置：{bias}。这是倾向值，不是概率，也不表示已经加入或退出博弈。\n"
        "外部暴露包括战争、外交博弈发起方、目标方、已承诺参与者和未选边参与者。"
        "未选边表示风险暴露，不表示已作出承诺。上述状态不等于行动收益、净代价或不利结果。\n"
        "该规则保留原版策略牌、国家身份、玩家和 AI 的共同世界规则；不提供免费资源、"
        "强制行动或固定国家剧本。\n"
        "安装：先退出游戏并保留原有配置与处理前存档，将 ZIP 解压至独立本地 Mod 目录，"
        "在启动器的独立 playset 中登记并启用；不要覆盖游戏本体，也不要同时挂载本包的多个变体。"
        "本包覆盖原版 00_default_strategy.txt；其他修改同一策略的 Mod 有兼容冲突风险。\n"
        "回退：退出游戏后禁用或移除本 Mod；全关包仍含默认策略底本，因此不等于完全零 Mod。"
        "已有变量可按剩余 TTL 失效，但关闭或卸载不会撤回已经发生的世界变化；"
        "恢复处理前存档与当时挂载才是对应回退点。不承诺任意旧存档可安全迁移。\n"
        "变体说明：current 是当前实验参数；control 保留财政生命周期但把新增偏置置零；"
        "disabled 关闭本 Mod 的财政及扩展逻辑，可作为安全基线。\n\n"
        f"扩展实际配置：reform={'启用' if extensions.reform_enabled else '关闭'}，"
        f"market={'启用' if extensions.market_enabled else '关闭'}。"
        f"security={'启用' if extensions.security_enabled else '关闭'}。"
        f" economy={'启用' if extensions.economy_enabled else '关闭'}，"
        f"diplomacy={'启用' if extensions.diplomacy_enabled else '关闭'}，"
        f"subjects={'启用' if extensions.subjects_enabled else '关闭'}。"
        "扩展关闭时不执行相应干预。改革扩展启用时，脆弱条件优先："
        f"合法性低于 {extensions.fragile_legitimacy}、战争或叛乱使 change_law_chance 的"
        f" default 贡献增加 {extensions.fragile_penalty:g}；否则合法性至少"
        f" {extensions.reform_legitimacy}、和平、无叛乱且实业家或知识分子在政府内，"
        f"增加 {extensions.reform_bonus:g}。市场扩展启用时，diplomatic_play_support 的"
        f" default 贡献增加（对己方依赖−对敌方依赖）×{extensions.market_multiplier:g}。"
        "这些贡献不是最终概率，也不证明具体法律或外交行动已发生。\n"
        f"外部模块启用时，防御条约/联盟贡献为 {extensions.security_commitment_bonus:g}，"
        f"相邻防御方遭征服/附庸目标威胁的贡献为 {extensions.security_threat_bonus:g}；"
        "同时满足只取较大值。支持防御方加分、评价进攻方减分，仍由原版判断资格与行动。"
        "complete 是四模块完整实验候选；fiscal/security/market/reform 是隔离变体，均未验收。\n\n"
        "[English]\n"
        "This guide describes the rules configured in this ZIP, not the live state of any country."
        " Building a package does not prove V0.1 completion or AI behavior quality; experimental"
        " and candidate packages are for isolated testing.\n"
        "The following fiscal rules run only while the fiscal module is enabled. The zero-bias"
        " control package also adds no diplomatic tendency.\n"
        f"An AI country in default enters fiscal risk. Otherwise it must be borrowing, have credit"
        f" greater than 0, and have non-negative weeks to bankruptcy below {policy.entry_weeks}."
        f" Existing risk uses a {policy.exit_weeks}-week hold threshold. Reaching it, no longer"
        " borrowing, or missing required valid readings ends the hold; default takes precedence.\n"
        "Monthly and default/end-of-default events reassess risk. The state expires"
        f" {policy.ttl_days} days after the last renewal without another update. Only an AI country"
        " currently meeting fiscal risk, hold, and external-exposure conditions receives the added"
        f" vanilla-field bias: {bias_en}. This is a tendency, not a probability or proof of joining"
        " or leaving a play.\n"
        "External exposure includes war, diplomatic-play initiator, target, committed participant,"
        " and undecided participant. Undecided means exposure, not a commitment. These states do"
        " not measure action benefit, net cost, or adverse outcome.\n"
        "Vanilla strategy cards, country identity, and the shared player/AI world rules remain in"
        " place. The package does not grant free resources, force actions, or hard-code a country"
        " script.\n"
        "Install: exit the game, preserve your configuration and a pre-treatment save, extract"
        " this ZIP into a separate local Mod directory, and register/enable it in an isolated"
        " launcher playset. Do not overwrite the game installation or enable multiple variants"
        " together. This package overrides vanilla 00_default_strategy.txt and may conflict with"
        " other Mods that modify the same strategy.\n"
        "Rollback: exit and disable/remove this Mod. The disabled package still contains the"
        " vanilla strategy baseline, so it is not a zero-Mod environment. Existing variables can"
        " expire by their remaining TTL, but disabling/uninstalling does not undo world changes."
        " Restore the pre-treatment save and its original mounts for that rollback point."
        " Arbitrary old-save migration is not guaranteed.\n"
        f"Variant: current uses the experimental parameters; control keeps the fiscal lifecycle"
        " with added bias set to zero; disabled turns off fiscal and extension logic for a safe"
        " baseline.\n"
        f"Enabled modules in this package: {module_text_en}.\n"
        f"Actual extension configuration: reform={'enabled' if extensions.reform_enabled else 'disabled'};"
        f" market={'enabled' if extensions.market_enabled else 'disabled'};"
        f" economy={'enabled' if extensions.economy_enabled else 'disabled'};"
        f" diplomacy={'enabled' if extensions.diplomacy_enabled else 'disabled'};"
        f" subjects={'enabled' if extensions.subjects_enabled else 'disabled'}. Disabled extensions do"
        " not intervene. For enabled reform, fragile conditions take precedence: legitimacy below"
        f" {extensions.fragile_legitimacy}, war, or insurrection adds {extensions.fragile_penalty:g}"
        " to the default change_law_chance contribution. Otherwise legitimacy of at least"
        f" {extensions.reform_legitimacy}, peace, no insurrection, and industrialists or"
        f" intelligentsia in government adds {extensions.reform_bonus:g}. Enabled market adds"
        f" (dependence on own side minus dependence on enemy side) x {extensions.market_multiplier:g}"
        " to default diplomatic_play_support. These contributions are not final probabilities"
        " or evidence of an enacted law or diplomatic action.\n"
        f"Security is {'enabled' if extensions.security_enabled else 'disabled'}: defense commitments"
        f" contribute {extensions.security_commitment_bonus:g}, threatened-neighbor defense"
        f" contributes {extensions.security_threat_bonus:g}; only the maximum reason applies,"
        " positive for the defender and negative for the attacker. This does not grant eligibility"
        " or force participation. complete enables all four experimental modules;"
        " fiscal/security/market/reform isolate one module for testing. The full candidate"
        " adds economy, diplomacy, and subjects and is still subject to F1/F2 validation.\n"
    )


def payloads(files: Mapping[str, str]) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    portable_names: set[str] = set()
    for name, text in sorted(files.items()):
        if name.casefold() == "distribution-manifest.json":
            raise ValueError("交付清单文件名为保留名称")
        path = PurePosixPath(name)
        if (
            not name
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in name
            or ":" in name
        ):
            raise ValueError(f"非法交付路径：{name!r}")
        if path.as_posix() != name:
            raise ValueError(f"交付路径必须规范化：{name!r}")
        reserved = {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }
        if any(
            part.rstrip(" .") != part
            or part.split(".")[0].upper() in reserved
            or any(c in part for c in '<>"|?*\0')
            for part in path.parts
        ):
            raise ValueError(f"交付路径不兼容 Windows：{name!r}")
        if name.casefold() in portable_names:
            raise ValueError(f"交付路径大小写冲突：{name!r}")
        portable_names.add(name.casefold())
        result[name] = text_bytes(text, game=path.suffix.lower() in GAME_SUFFIXES)
    return result


def write_zip(
    files: Mapping[str, str],
    destination: Path,
    *,
    generation: Mapping[str, object] | None = None,
) -> Path:
    """先完成并核验临时 ZIP，再原子替换目标；不修改仓库产物。"""
    data = payloads(files)
    manifest = {
        "schema": 2,
        "encoding": "游戏 .txt/.yml：UTF-8 含 BOM、LF；其他文本：UTF-8 无 BOM、LF",
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in data.items()},
    }
    metadata = files.get(".metadata/metadata.json")
    if metadata:
        try:
            contract = json.loads(metadata)
        except json.JSONDecodeError as exc:
            raise ValueError("交付元数据不是有效 JSON") from exc
        required = {
            "version",
            "tool_version",
            "status",
            "supported_game_version",
            "enabled_modules",
            "parent_package",
            "save_compatibility",
            "platforms",
            "platform_notes",
            "source_fingerprint",
        }
        if not isinstance(contract, dict):
            raise ValueError("交付元数据必须是 JSON 对象")
        if contract.get("id") == "sitai.decisions":
            if not required <= contract.keys():
                raise ValueError("交付元数据缺少 A1 包契约字段")
            if (
                not isinstance(contract["enabled_modules"], list)
                or not isinstance(contract["source_fingerprint"], dict)
                or not contract["source_fingerprint"]
            ):
                raise ValueError("交付元数据的启用模块或源指纹无效")
            manifest["contract"] = {
                "product_version": contract["version"],
                "tool_version": contract["tool_version"],
                "status": contract["status"],
                "game_version": contract["supported_game_version"],
                "enabled_modules": contract["enabled_modules"],
                "parent_package": contract["parent_package"],
                "save_compatibility": contract["save_compatibility"],
                "platforms": contract["platforms"],
                "platform_notes": contract["platform_notes"],
                "source_fingerprint": contract["source_fingerprint"],
            }
    if generation is not None:
        manifest["generation"] = dict(generation)
    data["DISTRIBUTION-MANIFEST.json"] = text_bytes(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent, suffix=".zip", delete=False
    ) as stream:
        temporary = Path(stream.name)
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for name, raw in sorted(data.items()):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, raw)
        with zipfile.ZipFile(temporary) as archive:
            broken = archive.testzip()
            if broken:
                raise ValueError(f"交付 ZIP 校验失败：{broken}")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def package_inputs(
    variant: str,
) -> tuple[decisions.Policy, decisions.Extensions, dict[str, str]]:
    """校验生产源后返回实际变体；隔离仪器复用同一转换，避免说明漂移。"""
    if variant not in PACKAGE_VARIANTS:
        raise ValueError("包变体无效：" + "、".join(PACKAGE_VARIANTS))
    policy, extensions = decisions.load(), decisions.load_extensions()
    current = decisions.build(policy, extensions=extensions)
    issues = decisions.check(decisions.PRODUCT, current)
    if issues:
        raise ValueError("生成物不一致，拒绝打包：\n" + "\n".join(issues))
    if variant == "control":
        policy = replace(policy, enabled=True, neutrality=0, aggression=0)
        extensions = replace(
            extensions,
            reform_enabled=False,
            market_enabled=False,
            security_enabled=False,
            economy_enabled=False,
            diplomacy_enabled=False,
            subjects_enabled=False,
        )
    elif variant == "disabled":
        policy = replace(policy, enabled=False)
        extensions = replace(
            extensions,
            reform_enabled=False,
            market_enabled=False,
            security_enabled=False,
            economy_enabled=False,
            diplomacy_enabled=False,
            subjects_enabled=False,
        )
    elif variant != "current":
        policy = replace(
            policy,
            enabled=variant
            in {"complete", "fiscal", "economy", "diplomacy", "subjects", "full"},
            aggression=0,
            package=replace(
                policy.package,
                status="candidate" if variant == "full" else "experimental",
                product_version="1.0.0"
                if variant == "full"
                else policy.package.product_version,
            ),
        )
        extensions = replace(
            extensions,
            reform_enabled=variant in {"complete", "reform", "full"},
            market_enabled=variant in {"complete", "market", "full"},
            security_enabled=variant in {"complete", "security", "full"},
            economy_enabled=variant in {"economy", "full"},
            diplomacy_enabled=variant in {"diplomacy", "full"},
            subjects_enabled=variant in {"subjects", "full"},
        )
    full_localization = variant == "full"
    files = (
        current
        if variant == "current"
        else decisions.build(
            policy, extensions=extensions, complete_localization=full_localization
        )
    )
    if variant == "full":
        metadata = json.loads(files[".metadata/metadata.json"])
        localization = metadata.setdefault("localization", {})
        localization["production_fallback_languages"] = list(
            localization.get("production_fallback_languages", [])
        )
        localization["explanation_fallback_languages"] = (
            explanation_probe.localization_fallback_languages()
        )
        localization["explanation_review_languages"] = (
            explanation_probe.localization_review_languages()
        )
        localization["fallback_languages"] = sorted(
            set(localization["production_fallback_languages"])
            | set(localization["explanation_fallback_languages"])
        )
        files[".metadata/metadata.json"] = (
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
        )
    modules = json.loads(files[".metadata/metadata.json"])["enabled_modules"]
    files["README.md"] = player_guide(policy, extensions, modules, variant=variant)
    return policy, extensions, files


def package(destination: Path, *, variant: str = "disabled") -> Path:
    policy, extensions, files = package_inputs(variant)
    if variant in {"complete", "full"}:
        files = explanation_probe.attach(files, policy, extensions)
        files["README.md"] += (
            "\n完整实验包包含原生国家面板的只读解释候选；覆盖 country_panel.gui，"
            "不与其它同路径界面覆盖兼容。上下文、布局、刷新和成本尚未实机验收。\n"
            "The complete experimental package includes an unverified read-only explanation"
            " and overrides country_panel.gui; other overrides of that panel conflict.\n"
        )
    return write_zip(
        files,
        destination,
        generation={
            "variant": variant,
            "fiscal": {
                key: value
                for key, value in asdict(policy).items()
                if key not in {"package", "source_sha256"}
            },
            "extensions": {
                key: value
                for key, value in asdict(extensions).items()
                if key != "source_sha256"
            },
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variant", choices=PACKAGE_VARIANTS, default="disabled")
    args = parser.parse_args()
    print(package(args.output, variant=args.variant))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
