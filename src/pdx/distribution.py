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

from pdx import decision_intents, decisions, explanation_probe
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
    "integrated",
)

MOD_ID = "sitai.decisions"
PROBE_MOD_ID = "sitai.explanation-probe"
MANIFEST_NAME = "DISTRIBUTION-MANIFEST.json"

# 用户可见的本地 Mod 目录名。内部 metadata.id 保持 `sitai.decisions`，用于
# 稳定识别、兼容性校验和既有工具；这个常量只约束生成/部署时的文件夹名称。
INSTALL_DIRECTORY_NAME = "Situated AI"


def generation_contract(*, variant: str, with_explanation_probe: bool) -> dict[str, object]:
    """返回生成、部署、测试和发布共用的候选契约。

    目录名是用户可见的交付接口；``MOD_ID`` 才是稳定的引擎/元数据身份。
    探针只能改变本次候选的证据类型，不能改变生产源或生产包默认值。
    """
    if variant not in PACKAGE_VARIANTS:
        raise ValueError("包变体无效：" + "、".join(PACKAGE_VARIANTS))
    return {
        "schema": "sitai-distribution-v1",
        "mod_id": MOD_ID,
        "install_directory": INSTALL_DIRECTORY_NAME,
        "variant": variant,
        "candidate_kind": (
            "instrumented_candidate" if with_explanation_probe else "production_candidate"
        ),
        "delivery_kind": "instrumented_validation" if with_explanation_probe else "standard_mod",
        "with_explanation_probe": with_explanation_probe,
        "behavior_quality": "not_evaluated",
    }


def _manifest_for_payloads(
    data: Mapping[str, bytes], *, generation: Mapping[str, object] | None = None
) -> dict[str, object]:
    """从最终交付字节构造清单；ZIP 与发布校验共用这一份逻辑。"""
    manifest: dict[str, object] = {
        "schema": 2,
        "mod_id": MOD_ID,
        "install_directory": INSTALL_DIRECTORY_NAME,
        "encoding": "游戏 .txt/.yml：UTF-8 含 BOM、LF；其他文本：UTF-8 无 BOM、LF",
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in data.items()},
    }
    metadata = data.get(".metadata/metadata.json")
    if metadata is not None:
        try:
            contract = json.loads(metadata.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("交付元数据不是有效 JSON") from exc
        required = {
            "id",
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
        if not isinstance(contract, dict) or contract.get("id") not in {MOD_ID, PROBE_MOD_ID}:
            raise ValueError("交付元数据缺少稳定 Mod 身份")
        manifest["mod_id"] = contract["id"]
        if not required <= contract.keys():
            raise ValueError("交付元数据缺少包契约字段")
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
    return manifest


def validate_package(
    archive_path: Path,
    *,
    expected_variant: str | None = None,
    allow_probe: bool = False,
) -> dict[str, object]:
    """校验可发布 ZIP 的路径、清单、哈希和探针边界。"""
    with zipfile.ZipFile(archive_path) as archive:
        broken = archive.testzip()
        if broken:
            raise ValueError(f"交付 ZIP 校验失败：{broken}")
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("交付 ZIP 含重复路径")
        for name in names:
            path = PurePosixPath(name)
            if (
                not name
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in name
                or ":" in name
                or path.as_posix() != name
            ):
                raise ValueError(f"交付 ZIP 含非法路径：{name!r}")
        if MANIFEST_NAME not in names:
            raise ValueError(f"交付 ZIP 缺少 {MANIFEST_NAME}")
        try:
            manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("交付清单不是有效 UTF-8 JSON") from exc
        if not isinstance(manifest, dict):
            raise ValueError("交付清单必须是 JSON 对象")
        if manifest.get("schema") != 2:
            raise ValueError("交付清单版本不受支持")
        mod_id = manifest.get("mod_id")
        if mod_id not in {MOD_ID, PROBE_MOD_ID}:
            raise ValueError("交付清单的稳定 Mod 身份不符")
        if manifest.get("install_directory") != INSTALL_DIRECTORY_NAME:
            raise ValueError("交付清单的安装目录不符")
        generation = manifest.get("generation")
        if not isinstance(generation, dict):
            raise ValueError("交付清单缺少生成契约")
        if generation.get("install_directory") != INSTALL_DIRECTORY_NAME:
            raise ValueError("生成契约的安装目录不符")
        variant = generation.get("variant")
        if not isinstance(variant, str) or variant not in PACKAGE_VARIANTS:
            raise ValueError("生成契约的变体无效")
        if expected_variant is not None and variant != expected_variant:
            raise ValueError(f"交付变体为 {variant}，不是期望的 {expected_variant}")
        with_probe = generation.get("with_explanation_probe") is True
        if mod_id == PROBE_MOD_ID and not with_probe:
            raise ValueError("探针身份与生成契约不一致")
        if not allow_probe and with_probe:
            raise ValueError("标准发布包不能包含解释探针")
        files = manifest.get("files")
        if not isinstance(files, dict) or set(files) != set(names) - {MANIFEST_NAME}:
            raise ValueError("交付清单文件集合与 ZIP 不一致")
        for name, expected in files.items():
            if (
                not isinstance(expected, str)
                or hashlib.sha256(archive.read(name)).hexdigest() != expected
            ):
                raise ValueError(f"交付文件指纹不符：{name}")
        return manifest


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
        f"标准安装目录为 `Victoria 3/mod/{INSTALL_DIRECTORY_NAME}`；在启动器的独立 playset 中登记并启用；"
        "不要覆盖游戏本体，也不要同时挂载本包的多个变体。"
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
        f" this ZIP into `Victoria 3/mod/{INSTALL_DIRECTORY_NAME}`, and register/enable it in an isolated"
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
        if name.casefold() == MANIFEST_NAME.casefold():
            raise ValueError("交付清单文件名为保留名称")
        path = PurePosixPath(name)
        if not name or path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
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
    manifest = _manifest_for_payloads(data, generation=generation)
    data[MANIFEST_NAME] = text_bytes(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".zip", delete=False) as stream:
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
        # 在替换目标前校验完整交付清单。这样清单、路径或哈希失败时，
        # 已有目标包仍然可以作为可恢复交付物保留。
        validate_package(temporary, allow_probe=True)
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
            in {"complete", "fiscal", "economy", "diplomacy", "subjects", "full", "integrated"},
            aggression=0,
            package=replace(
                policy.package,
                status="candidate" if variant == "full" else "experimental",
                product_version=(
                    "2.0.0.dev4"
                    if variant == "integrated"
                    else "1.0.0"
                    if variant == "full"
                    else policy.package.product_version
                ),
            ),
        )
        extensions = replace(
            extensions,
            reform_enabled=variant in {"complete", "reform", "full", "integrated"},
            market_enabled=variant in {"complete", "market", "full", "integrated"},
            security_enabled=variant in {"complete", "security", "full", "integrated"},
            economy_enabled=variant in {"economy", "full", "integrated"},
            diplomacy_enabled=variant in {"diplomacy", "full", "integrated"},
            # integrated 的宗属字段由声明式适配器统一负责，不能叠加旧作者。
            subjects_enabled=variant in {"subjects", "full"},
        )
    full_localization = variant in {"full", "integrated"}
    strategy = decision_intents.load() if variant == "integrated" else None
    information = decisions.decision_rules.load(strategy=strategy) if strategy is not None else None
    adapters = decisions.decision_adapters.load(strategy=strategy) if strategy is not None else None
    if strategy is not None and information is not None and adapters is not None:
        consumed = {
            rule.intent
            for policy_rules in (information, *(row for _, row in adapters.policies))
            for rule in policy_rules.rules
            if rule.intent is not None
        }
        if {intent.id for intent in strategy.closure(consumed)} != {
            intent.id for intent in strategy.intents
        }:
            raise ValueError("生产战略意图必须有实际规则消费者")
    files = (
        current
        if variant == "current"
        else decisions.build(
            policy,
            extensions=extensions,
            complete_localization=full_localization,
            information_rules=information,
            consumer_adapters=adapters,
        )
    )
    if variant in {"full", "integrated"}:
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
        files[".metadata/metadata.json"] = json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
    modules = json.loads(files[".metadata/metadata.json"])["enabled_modules"]
    files["README.md"] = player_guide(policy, extensions, modules, variant=variant)
    if variant == "integrated":
        metadata = json.loads(files[".metadata/metadata.json"])
        contract = metadata["decision_rules"]
        files["README.md"] += (
            "\n全域规则实验增量 / Integrated experimental rules\n"
            "同一字段按优先级只使用第一条匹配规则；倍率只改变默认策略贡献，"
            "不代表最终概率或行动。当前规则无持久状态，沿用原版消费者评估时机。"
            "以下覆盖不代表 2.0 全目标已完成或行为已验收。\n"
            "The first matching rule per field changes only the default contribution. "
            "Vanilla qualification, costs, and actions remain in force; behavior is unverified.\n"
            + "".join(
                f"- {rule['id']}：{rule['field']} {rule['operation']} {rule['value']:g}；{rule['why']}。"
                f"反例边界：{rule['counterexample']}。\n"
                for rule in contract["rules"]
            )
        )
        files["README.md"] += (
            "\n锁定原版消费者补丁 / Source-locked consumer adapters\n"
            "本变体从匹配的本体原件生成法律、科技和策略权重补丁；保留原版资格、效果、成本和其余内容。"
            "商品读数属于本国所在市场，不能当作该国自身产量。"
            "倍率保留原值零点；法律和部分外交/宗属评分使用有限增量，政治支持与 ai_will_do 仍由原版决定。"
            "建筑规则读取本州实际启用的主要生产方式；商品供给立场仅追加原版未声明的商品，"
            "不强制切换生产方式或创建贸易路线。"
            "关闭需重新生成不含适配文件的包并重启；游戏更新后旧包不会自行卸载或自动恢复原版，必须停用并重新生成。\n"
            "Source-locked edits retain vanilla qualification, effects and costs. Goods readings describe "
            "the country's market. Adjustments use the declared add or multiply operation. "
            "Building rules inspect active primary production methods; additional goods stances do not force trade. "
            "Disable and rebuild after a game update; an installed ZIP cannot automatically undo its overrides.\n"
            + "".join(
                f"- {consumer['source']} / {rule['id']}：{rule['field']} "
                f"{rule['operation']} {rule['value']:g}；{rule['why']}。反例边界：{rule['counterexample']}。\n"
                for consumer in metadata["consumer_adapters"]["consumers"]
                for rule in consumer["rules"]
            )
        )
    return policy, extensions, files


def package(
    destination: Path,
    *,
    variant: str = "disabled",
    with_explanation_probe: bool | None = None,
) -> Path:
    """生成标准游戏 Mod；解释面板只在显式仪器模式下附加。

    ``complete`` 是既有四模块历史实验变体，继续保留它原来的解释候选。
    新的七模块 ``full`` 默认只包含标准 Mod 内容；实机需要观测解释面板时，
    必须显式传 ``with_explanation_probe=True``，避免把未验收 UI 当作生产内容。
    """
    policy, extensions, files = package_inputs(variant)
    if with_explanation_probe is None:
        with_explanation_probe = variant == "complete"
    if with_explanation_probe:
        files = explanation_probe.attach(files, policy, extensions)
        files["README.md"] += (
            "\n本包包含原生国家面板的只读解释候选；覆盖 country_panel.gui，"
            "不与其它同路径界面覆盖兼容。上下文、布局、刷新和成本尚未实机验收。\n"
            "This package includes an unverified read-only explanation"
            " and overrides country_panel.gui; other overrides of that panel conflict.\n"
        )
    return write_zip(
        files,
        destination,
        generation={
            **generation_contract(variant=variant, with_explanation_probe=with_explanation_probe),
            "fiscal": {
                key: value
                for key, value in asdict(policy).items()
                if key not in {"package", "source_sha256"}
            },
            "extensions": {
                key: value for key, value in asdict(extensions).items() if key != "source_sha256"
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
