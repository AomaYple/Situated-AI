"""确定性游戏 ZIP：仓库无 BOM，交付脚本与本地化带 BOM。"""

from __future__ import annotations

import argparse
import codecs
import hashlib
import json
import re
import struct
import tempfile
import zipfile
from dataclasses import asdict, replace
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from pdx import config, country_state, decision_intents, decisions
from pdx.localization import parse_loc_entries
from pdx.textio import GAME_SUFFIXES, text_bytes

if TYPE_CHECKING:
    from collections.abc import Mapping

MOD_ID = config.MOD_ID
RELEASE_VERSION = "1.4.0"
MANIFEST_NAME = "DISTRIBUTION-MANIFEST.json"
RELEASE_VARIANT = "release"
METADATA_NAME = ".metadata/metadata.json"
THUMBNAIL_NAME = "thumbnail.png"
LAUNCHER_METADATA_KEYS = (
    "name",
    "id",
    "version",
    "supported_game_version",
    "short_description",
    "picture",
    "tags",
    "relationships",
    "game_custom_data",
)

# 用户可见的本地 Mod 目录名，与启动器 metadata.id 分开维护。
INSTALL_DIRECTORY_NAME = "Situated AI"
DEFAULT_PACKAGE_PATH = Path("dist") / f"situated-ai-{RELEASE_VERSION}.zip"


def generation_contract() -> dict[str, object]:
    """返回生成、部署、测试和发布共用的候选契约。

    目录名是用户可见的交付接口；``MOD_ID`` 才是稳定的引擎/元数据身份。
    当前生成链只输出标准 Mod，长期行为验收由用户完成。
    """
    return {
        "schema": "sitai-distribution-v1",
        "mod_id": MOD_ID,
        "install_directory": INSTALL_DIRECTORY_NAME,
        "variant": RELEASE_VARIANT,
        "candidate_kind": "production_candidate",
        "delivery_kind": "standard_mod",
        "with_explanation_probe": False,
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
    metadata = data.get(METADATA_NAME)
    if metadata is not None:
        try:
            contract = json.loads(metadata.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("交付元数据不是有效 JSON") from exc
        required = {
            "name",
            "id",
            "version",
            "supported_game_version",
            "short_description",
            "picture",
            "tags",
            "relationships",
        }
        if (
            not isinstance(contract, dict)
            or contract.get("id") != MOD_ID
            or not isinstance(contract.get("name"), str)
        ):
            raise ValueError("交付元数据缺少稳定 Mod 身份")
        manifest["mod_id"] = contract["id"]
        if not required <= contract.keys():
            raise ValueError("交付元数据缺少包契约字段")
        if not isinstance(contract["tags"], list) or not isinstance(
            contract["relationships"], list
        ):
            raise ValueError("启动器元数据的标签或关系字段无效")
        manifest["contract"] = {
            "product_version": contract["version"],
            "game_version": contract["supported_game_version"],
        }
    if generation is not None:
        manifest["generation"] = dict(generation)
        product_contract = generation.get("product_contract")
        if product_contract is not None:
            if not isinstance(product_contract, dict):
                raise ValueError("发布生成契约无效")
            release_contract = manifest.setdefault("contract", {})
            if not isinstance(release_contract, dict):
                raise ValueError("发布包契约无效")
            release_contract.update(product_contract)
    return manifest


def _validate_archive(
    archive_path: Path,
    *,
    expected_data: Mapping[str, bytes] | None,
    expected_generation: Mapping[str, object] | None,
    release: bool,
) -> dict[str, object]:
    """校验 ZIP；公开发布校验额外要求与当前生产源逐字节一致。"""
    with zipfile.ZipFile(archive_path) as archive:
        broken = archive.testzip()
        if broken:
            raise ValueError(f"交付 ZIP 校验失败：{broken}")
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("交付 ZIP 含重复路径")
        _validate_paths(names)
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
        if mod_id != MOD_ID:
            raise ValueError("交付清单的稳定 Mod 身份不符")
        if manifest.get("install_directory") != INSTALL_DIRECTORY_NAME:
            raise ValueError("交付清单的安装目录不符")
        generation = manifest.get("generation")
        if expected_generation is not None:
            if generation != dict(expected_generation):
                raise ValueError("交付包生成契约与当前生产源不一致")
        elif generation is not None and not isinstance(generation, dict):
            raise ValueError("交付清单的生成契约无效")
        files = manifest.get("files")
        if not isinstance(files, dict) or set(files) != set(names) - {MANIFEST_NAME}:
            raise ValueError("交付清单文件集合与 ZIP 不一致")
        data = {}
        for name, expected in files.items():
            raw = archive.read(name)
            if not isinstance(expected, str) or hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError(f"交付文件指纹不符：{name}")
            data[name] = raw
        for name, raw in {**data, MANIFEST_NAME: archive.read(MANIFEST_NAME)}.items():
            # thumbnail.png 是二进制展示资源；其余交付条目是受控 UTF-8 文本。
            if name == THUMBNAIL_NAME:
                continue
            game = PurePosixPath(name).suffix.lower() in GAME_SUFFIXES
            try:
                decoded = raw.decode("utf-8-sig" if game else "utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(f"交付文件不是 UTF-8：{name}") from exc
            if raw.startswith(codecs.BOM_UTF8) != game or "\ufeff" in decoded or "\r" in decoded:
                raise ValueError(f"交付文件 BOM/LF 不符：{name}")
        regenerated = _manifest_for_payloads(data, generation=generation)
        if manifest != regenerated:
            raise ValueError("交付清单与元数据契约不一致")
        if expected_data is not None:
            if set(data) != set(expected_data):
                raise ValueError("交付文件集合与当前生产源不一致")
            for name, raw in expected_data.items():
                if data[name] != raw:
                    raise ValueError(f"交付内容与当前生产源不一致：{name}")
        if release:
            contract = manifest.get("contract")
            if not isinstance(contract, dict):
                raise ValueError("正式包缺少发布契约")
            _validate_release(data, contract)
        return manifest


def validate_package(archive_path: Path) -> dict[str, object]:
    """校验正式 ZIP，并拒绝任何偏离当前生产源的内容。"""
    policy, extensions, internal_files = package_inputs(include_engineering_metadata=True)
    metadata = json.loads(internal_files[METADATA_NAME])
    files = _release_files(internal_files)
    return _validate_archive(
        archive_path,
        expected_data=payloads(files),
        expected_generation=_release_generation(policy, extensions, metadata),
        release=True,
    )


def _validate_release(data: Mapping[str, bytes], contract: Mapping[str, object]) -> None:
    """正式包只允许标准游戏目录、完整语言和固定发布身份。"""
    required = {".metadata/metadata.json", "README.md"}
    if not required <= data.keys():
        raise ValueError("正式包缺少元数据或安装说明")
    if any(
        name not in required
        and not (name.startswith("common/") and name.endswith(".txt"))
        and not (name.startswith("localization/") and name.endswith(".yml"))
        and name != THUMBNAIL_NAME
        for name in data
    ):
        raise ValueError("正式包包含非生产路径")
    if any("probe" in name.casefold() for name in data):
        raise ValueError("正式包不能包含探针")
    _validate_thumbnail(data.get(THUMBNAIL_NAME))
    metadata = json.loads(data[METADATA_NAME])
    if set(metadata) != set(LAUNCHER_METADATA_KEYS):
        raise ValueError("正式包元数据必须只包含启动器字段")
    if (
        metadata.get("id") != MOD_ID
        or metadata.get("version") != RELEASE_VERSION
        or metadata.get("supported_game_version") != "1.14.5"
        or metadata.get("picture") != THUMBNAIL_NAME
    ):
        raise ValueError("正式包版本与锁定游戏不符")
    if contract.get("fallback_languages") != []:
        raise ValueError("正式包不能包含缺译回退")
    # 使用同一个锁定语言来源，避免另维护一份语言列表。
    expected = set(decisions.LANGUAGES)
    declared_languages = contract.get("languages")
    if (
        not isinstance(declared_languages, list)
        or not all(isinstance(language, str) for language in declared_languages)
        or len(declared_languages) != len(expected)
        or set(declared_languages) != expected
    ):
        raise ValueError("正式包语言契约不完整")
    languages = {PurePosixPath(name).parts[1] for name in data if name.startswith("localization/")}
    if languages != expected or not any(name.startswith("common/") for name in data):
        raise ValueError("正式包脚本或本地化不完整")
    localized: dict[str, dict[str, str]] = {}
    for language, header in decisions.LANGUAGES.items():
        name = f"localization/{language}/sitai_decisions_l_{language}.yml"
        paths = [path for path in data if path.startswith(f"localization/{language}/")]
        if paths != [name]:
            raise ValueError(f"正式包本地化路径不符：{language}")
        text = data[name].decode("utf-8-sig")
        lines = [
            line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")
        ]
        if not lines or lines[0] != f"{header}:":
            raise ValueError(f"正式包语言头不符：{language}")
        if any(
            re.fullmatch(r'\s+[A-Za-z0-9_.-]+:(?:[0-9]+)?\s+"(?:[^"\\]|\\.)*"\s*', line) is None
            for line in lines[1:]
        ):
            raise ValueError(f"正式包本地化语法不符：{language}")
        _, entries = parse_loc_entries(text)
        values = dict(entries)
        if (
            not values
            or len(values) != len(entries)
            or any(not value.strip() for value in values.values())
        ):
            raise ValueError(f"正式包本地化为空或键重复：{language}")
        localized[language] = values
    reference = localized["english"]
    for language, values in localized.items():
        if values.keys() != reference.keys():
            raise ValueError(f"正式包本地化键集合不符：{language}")
        for key, value in values.items():
            # 同时保留 $KEY$ 替换和 PDX 数据绑定；文字顺序可以因语言变化。
            pattern = r"\$[^$\n]+\$|\[[^]\n]+\]"
            if sorted(re.findall(pattern, value)) != sorted(re.findall(pattern, reference[key])):
                raise ValueError(f"正式包本地化占位符不符：{language}/{key}")


def _validate_thumbnail(raw: bytes | None) -> None:
    """校验启动器/Workshop 封面是可移植且低于 1 MB 的方形 PNG。"""
    if raw is None:
        raise ValueError("正式包缺少 thumbnail.png")
    if len(raw) >= 1_000_000:
        raise ValueError("thumbnail.png 必须小于 1 MB，符合 Workshop 预览图限制")
    signature = b"\x89PNG\r\n\x1a\n"
    if not raw.startswith(signature) or len(raw) < 24:
        raise ValueError("thumbnail.png 不是有效 PNG")
    width, height = struct.unpack(">II", raw[16:24])
    if not (256 <= width <= 4096 and 256 <= height <= 4096 and width == height):
        raise ValueError("thumbnail.png 必须是 256-4096 像素的方形图片")


def player_guide(
    policy: decisions.Policy,
    extensions: decisions.Extensions,
    modules: list[str],
) -> str:
    """生成面向玩家的简明中英安装说明。"""
    module_text = "、".join(modules)
    module_text_en = ", ".join(modules)
    diplomacy_note = (
        "宗属倾向由声明式原版消费者适配器统一实现。\n" if extensions.diplomacy_enabled else ""
    )
    diplomacy_note_en = (
        "Subject tendencies use declarative adapters for vanilla consumers.\n"
        if extensions.diplomacy_enabled
        else ""
    )
    return (
        f"Situated AI {RELEASE_VERSION}\n"
        "=================\n"
        f"产品版本 / Product version：{policy.package.product_version}\n"
        f"支持的游戏版本 / Supported game version：{policy.game_version}\n"
        f"启用模块 / Enabled modules：{module_text} / {module_text_en}\n"
        f"存档兼容 / Save compatibility：{policy.package.save_compatibility}\n\n"
        "【中文】\n"
        f"这是唯一正式生产包（当前 {RELEASE_VERSION} 交付候选）。它依据国家的政治、人口、财政、经济、市场、贸易、"
        "外交、宗属、军事、战争、殖民、地理、身份与科技处境调整原版 AI 权重。"
        "原版资格、成本、效果与行动流程继续生效；本 Mod 不提供免费资源、不强制行动，"
        "也不按国家编写固定剧本。\n"
        f"模块开关：reform={'启用' if extensions.reform_enabled else '关闭'}，"
        f"market={'启用' if extensions.market_enabled else '关闭'}，"
        f"security={'启用' if extensions.security_enabled else '关闭'}，"
        f"economy={'启用' if extensions.economy_enabled else '关闭'}，"
        f"diplomacy={'启用' if extensions.diplomacy_enabled else '关闭'}。\n"
        f"{diplomacy_note}"
        f"财政风险在违约，或正在借款且距破产少于 {policy.entry_weeks} 周时进入；"
        f"使用 {policy.exit_weeks} 周退出线与 {policy.ttl_days} 天状态有效期。"
        f"外交博弈中立偏置为 {policy.neutrality:g}，攻击性偏置为 {policy.aggression:g}。"
        "同一字段按优先级使用第一条匹配规则；倍率保留原版零值。\n"
        "安装：退出游戏，将 ZIP 解压到文档目录的 `Paradox Interactive/Victoria 3/mod/"
        f"{INSTALL_DIRECTORY_NAME}`，在启动器中登记并启用独立 playset。不要覆盖游戏本体。"
        "本包覆盖部分原版 AI 消费者文件；其它 Mod 不在兼容范围内。支持锁定版本的全部 11 种本体语言。\n"
        "回退：退出游戏后禁用或删除本 Mod，并恢复安装前存档。任意旧存档迁移不受保证。"
        "游戏更新后应停用旧包，等待针对新版本重新生成。\n"
        "工程检查证明生成、打包和锁定原版接口符合自动化契约；AI 长期行为、平衡、后期性能、"
        "玩家体验与创意工坊发布由用户验收。\n\n"
        "[English]\n"
        f"This is the only standard production package (the Situated AI {RELEASE_VERSION} delivery candidate). "
        "It adjusts vanilla AI weights using political,"
        " population, fiscal, economic, market, trade, diplomatic, subject, military, war, colonial,"
        " geographic, identity, and technology context. Vanilla eligibility, costs, effects, and actions"
        " remain in force. The Mod grants no free resources, forces no action, and uses only a bounded\n"
        "country-state script for AI route memory; it does not replace the vanilla AI.\n"
        f"Module switches: reform={'enabled' if extensions.reform_enabled else 'disabled'}; "
        f"market={'enabled' if extensions.market_enabled else 'disabled'}; "
        f"security={'enabled' if extensions.security_enabled else 'disabled'}; "
        f"economy={'enabled' if extensions.economy_enabled else 'disabled'}; "
        f"diplomacy={'enabled' if extensions.diplomacy_enabled else 'disabled'}.\n"
        f"{diplomacy_note_en}"
        f"Fiscal risk enters on default, or while borrowing with fewer than {policy.entry_weeks} weeks"
        f" to bankruptcy. It uses a {policy.exit_weeks}-week exit threshold and a {policy.ttl_days}-day"
        f" state lifetime. Diplomatic-play neutrality is {policy.neutrality:g}; aggression is"
        f" {policy.aggression:g}. The first matching rule per field wins; multipliers preserve vanilla zero values.\n"
        "Install after exiting the game. Extract the ZIP to the documents directory at"
        f" `Paradox Interactive/Victoria 3/mod/{INSTALL_DIRECTORY_NAME}` and enable it in an isolated"
        " launcher playset. Do not overwrite the game installation. Other Mods are outside the"
        " compatibility scope. To roll back, exit, disable or remove this Mod, and restore a"
        " pre-installation save. Disable the package after a game update until a matching release exists.\n"
        "The package supports all 11 languages in the locked game version. Engineering checks cover"
        " generation, archive structure, and locked vanilla interfaces. Long-run AI behavior, balance,"
        " late-game performance, localization presentation, and Workshop publication remain for player acceptance.\n"
    )


def launcher_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
    """只保留 Paradox Launcher 使用的 Mod 元数据字段。"""
    missing = set(LAUNCHER_METADATA_KEYS) - metadata.keys()
    if missing:
        raise ValueError("启动器元数据缺少字段：" + "、".join(sorted(missing)))
    result = {key: metadata[key] for key in LAUNCHER_METADATA_KEYS}
    if not isinstance(result["game_custom_data"], dict):
        raise ValueError("启动器自定义数据必须为对象")
    return result


def _release_files(files: Mapping[str, str | bytes]) -> dict[str, str | bytes]:
    """返回不含生成器审计数据的标准 Mod 文件集。"""
    result = dict(files)
    metadata = json.loads(result[METADATA_NAME])
    result[METADATA_NAME] = (
        json.dumps(launcher_metadata(metadata), ensure_ascii=False, indent=2) + "\n"
    )
    return result


def _validate_paths(names: list[str]) -> None:
    """生成与外部 ZIP 校验共用的可移植文件路径约束。"""
    portable_names: set[str] = set()
    for name in names:
        if not isinstance(name, str):
            raise ValueError("交付路径必须是文本")
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
            *(f"{prefix}{number}" for prefix in ("COM", "LPT") for number in "¹²³"),
        }
        if any(
            part.rstrip(" .") != part
            or part.split(".")[0].upper() in reserved
            or any(c in part for c in '<>"|?*')
            or any(ord(c) < 32 or ord(c) == 127 for c in part)
            for part in path.parts
        ):
            raise ValueError(f"交付路径不兼容 Windows：{name!r}")
        if name.casefold() in portable_names:
            raise ValueError(f"交付路径大小写冲突：{name!r}")
        portable_names.add(name.casefold())


def payloads(files: Mapping[str, str | bytes]) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    _validate_paths(list(files))
    for name, text in sorted(files.items()):
        if name.casefold() == MANIFEST_NAME.casefold():
            raise ValueError("交付清单文件名为保留名称")
        path = PurePosixPath(name)
        result[name] = (
            text
            if isinstance(text, bytes)
            else text_bytes(text, game=path.suffix.lower() in GAME_SUFFIXES)
        )
    return result


def write_zip(
    files: Mapping[str, str | bytes],
    destination: Path,
    *,
    generation: Mapping[str, object] | None = None,
    release: bool = False,
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
        _validate_archive(
            temporary,
            expected_data=payloads(files),
            expected_generation=generation,
            release=release,
        )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def production_configuration() -> tuple[decisions.Policy, decisions.Extensions]:
    """读取唯一发布 profile；读取配置不需要本机原版。"""
    policy, extensions = decisions.load(), decisions.load_extensions(profile="release")
    policy = replace(
        policy,
        enabled=True,
        aggression=0,
        package=replace(policy.package, product_version=RELEASE_VERSION, status="candidate"),
    )
    return policy, extensions


def read_production_files() -> dict[str, str | bytes]:
    """读取受控生成物原始 UTF-8 字节，不折叠 CRLF 或移除 BOM。"""
    files: dict[str, str | bytes] = {
        path.relative_to(decisions.PRODUCT).as_posix(): path.read_bytes().decode("utf-8")
        for directory in ("common", "localization", ".metadata")
        for path in sorted((decisions.PRODUCT / directory).rglob("*"))
        if path.is_file()
    }
    thumbnail = decisions.PRODUCT / THUMBNAIL_NAME
    if thumbnail.is_file():
        files[THUMBNAIL_NAME] = thumbnail.read_bytes()
    return files


def generation_lock(files: Mapping[str, str | bytes] | None = None) -> str:
    """冻结源码和产物字节；离线只能核对冻结一致性，不能重建原版。"""
    root = decisions.PRODUCT.parent
    sources = [
        *sorted((root / "src/pdx").glob("*.py")),
        *sorted((root / "mod/decisions").glob("*.toml")),
        *sorted(decisions.BASELINE.parent.glob("*.txt")),
        *sorted(decisions.BASELINE.parent.glob("*.json")),
    ]
    if files is None:
        files = read_production_files()
    return (
        json.dumps(
            {
                "schema": 1,
                "evidence": "frozen_generation_not_current_game_verification",
                "sources": {
                    path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sources
                },
                "files": {
                    name: hashlib.sha256(
                        text if isinstance(text, bytes) else text.encode("utf-8")
                    ).hexdigest()
                    for name, text in sorted(files.items())
                    if name != "README.md"
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def check_generation_lock() -> None:
    """拒绝未冻结的源码或产物漂移；原版 SHA 仍由有游戏生成链核验。"""
    path = decisions.PRODUCT / "generation-lock.json"
    if path.read_bytes() != generation_lock().encode("utf-8"):
        raise ValueError("生产源码或产物与冻结记录不一致：用锁定原版运行 modgen --write")


def package_inputs(
    *, include_engineering_metadata: bool = False
) -> tuple[decisions.Policy, decisions.Extensions, dict[str, str | bytes]]:
    """构建当前版本的生产文件；需要锁定原版，不静默回退冻结产物。"""
    policy, extensions = production_configuration()
    country_policy = country_state.load()
    country_state.validate(country_policy, config.GAME)
    if not country_policy.enabled:
        raise ValueError("正式包必须启用 country_state")
    strategy = decision_intents.load()
    information = decisions.decision_rules.load(strategy=strategy)
    adapters = decisions.decision_adapters.load(strategy=strategy)
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
    files: dict[str, str | bytes] = dict(
        decisions.build(
            policy,
            extensions=extensions,
            complete_localization=True,
            information_rules=information,
            consumer_adapters=adapters,
            country_policy=country_policy,
        )
    )
    metadata = json.loads(files[".metadata/metadata.json"])
    localization = metadata["localization"]
    if localization["fallback_languages"] or localization["production_fallback_languages"]:
        raise ValueError("正式包不能包含未翻译的生产本地化")
    modules = metadata["enabled_modules"]
    files["README.md"] = player_guide(policy, extensions, modules)
    thumbnail = decisions.PRODUCT / THUMBNAIL_NAME
    if not thumbnail.is_file():
        raise ValueError(f"缺少正式包封面：{thumbnail}")
    files[THUMBNAIL_NAME] = thumbnail.read_bytes()
    if not include_engineering_metadata:
        files[METADATA_NAME] = (
            json.dumps(launcher_metadata(metadata), ensure_ascii=False, indent=2) + "\n"
        )
    return policy, extensions, files


def _release_generation(
    policy: decisions.Policy,
    extensions: decisions.Extensions,
    metadata: Mapping[str, Any],
) -> dict[str, object]:
    """返回正式包的完整、可比较生成参数。"""
    return {
        **generation_contract(),
        "fiscal": {
            key: value
            for key, value in asdict(policy).items()
            if key not in {"package", "source_sha256"}
        },
        "extensions": {
            key: value for key, value in asdict(extensions).items() if key != "source_sha256"
        },
        "product_contract": {
            "tool_version": metadata["tool_version"],
            "status": metadata["status"],
            "enabled_modules": metadata["enabled_modules"],
            "parent_package": metadata["parent_package"],
            "save_compatibility": metadata["save_compatibility"],
            "platforms": metadata["platforms"],
            "platform_notes": metadata["platform_notes"],
            "source_fingerprint": metadata["source_fingerprint"],
            "languages": metadata["localization"]["languages"],
            "fallback_languages": metadata["localization"]["fallback_languages"],
            "field_owner_count": len(metadata["default_field_owners"]),
            "vanilla_field_count": len(metadata["vanilla_field_coverage"]),
            "information_rule_count": metadata["decision_rules"]["active_rule_count"],
            "consumer_count": len(metadata["consumer_adapters"]["consumers"]),
            "consumer_rule_count": sum(
                len(consumer["rules"]) for consumer in metadata["consumer_adapters"]["consumers"]
            ),
            "strategic_intent_count": len(metadata["strategic_coordination"]["intents"]),
            "country_state": metadata["country_state"],
            "country_coordination": metadata["country_coordination"],
            "behavior_quality": "not_evaluated",
        },
    }


def package(destination: Path) -> Path:
    """核对仓库生成物后，生成唯一正式包。"""
    policy, extensions, internal_files = package_inputs(include_engineering_metadata=True)
    metadata = json.loads(internal_files[METADATA_NAME])
    files = _release_files(internal_files)
    production_files = {name: text for name, text in files.items() if name != "README.md"}
    issues = decisions.check(decisions.PRODUCT, production_files)
    if issues:
        raise ValueError("生成物不一致，拒绝打包：\n" + "\n".join(issues))
    return write_zip(
        files,
        destination,
        generation=_release_generation(policy, extensions, metadata),
        release=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(package(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
