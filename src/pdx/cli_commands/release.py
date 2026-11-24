"""Commands for standard Mod generation, packaging, and release checks."""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003 - Typer resolves annotations at runtime.
from typing import Annotated, Literal

import typer
from rich.markup import escape

from pdx import (
    config,
    country_state,
    decision_report,
    decisions,
    distribution,
    law_opportunities,
    technology_opportunities,
    vanilla_index,
    version_contracts,
)
from pdx.generation_transaction import GenerationTransaction
from pdx.parser import parse_text
from pdx.situated import bindings as situated_bindings
from pdx.situated import domain_coverage as situated_domain_coverage
from pdx.situated import production_profile as situated_production_profile
from pdx.situated import profile_configuration
lazy from pdx import company_sectors

from .common import EXIT_FAILED, console, require_workspace
from .common import fail as _fail
from .common import write_json as _write_json


def _modgen_verify_sources() -> None:
    """Verify existing independent pins before exposing new generated ledgers."""
    distribution.engine_scope.verify_strategy_game(config.GAME)
    distribution.decision_interfaces.verify_scripted_trigger_game(config.GAME)
    distribution.engine_scope.verify_company_defaults_game(config.GAME)
    company_sectors.verify_game(config.GAME)
    distribution.equipment_opportunities.verify_game(config.GAME)
    distribution.treaty_opportunities.verify_game(config.GAME)
    distribution.mobilization_opportunities.verify_game(config.GAME)
    country_state.validate(country_state.load(), config.GAME)
    # This also checks every source of adapter-specific queries and readers.
    adapters = decisions.decision_adapters.load()
    inputs = decisions.decision_adapters.read_inputs(adapters)
    law_opportunities.verify_inputs(inputs)
    technology_opportunities.verify_inputs(inputs)


def _production_profile(name: str | None, *, offline: bool = False) -> None:
    """Verify the current production contract and its installation when required."""
    version_contracts.require_current(name)
    if not offline:
        distribution.check_profile_installation(situated_production_profile.declared_profile())


def _profile_configuration(path: Path | None, *, mode: Literal["policy", "neutral"] = "policy"):
    """Resolve configuration once at the CLI boundary."""
    if path is None:
        return profile_configuration.ProfileConfiguration(mode=mode)
    return profile_configuration.load(path)


def modgen_cmd(
    write: Annotated[bool, typer.Option("--write", help="生成唯一正式 Mod 的仓库产物")] = False,
    check: Annotated[bool, typer.Option("--check", help="逐字节核对生成物，不写盘")] = False,
    profile: Annotated[str | None, typer.Option("--profile", help="断言当前生产版本")] = None,
    configuration: Annotated[
        Path | None, typer.Option("--configuration", help="1.15 profile TOML 配置")
    ] = None,
) -> None:
    """从生产 TOML 和锁定原版底本生成标准 Mod；生成物禁止手改。"""
    require_workspace()
    if write and check:
        _fail("--write 与 --check 互斥：先写盘，再另跑一次核对")
    try:
        _production_profile(profile)
        if not (config.GAME / "common").is_dir():
            raise ValueError(f"缺少锁定游戏原件：{config.GAME / 'common'}")
        if write:
            _modgen_verify_sources()
            bindings = situated_bindings.build()
            ledgers = {
                situated_bindings.source_path(): situated_bindings.render(bindings).encode("utf-8"),
                situated_domain_coverage.source_path(): situated_domain_coverage.render_counts(
                    situated_domain_coverage.source_path()
                ).encode("utf-8"),
            }
            # Strict production readers need the updated generated counts and
            # bindings. Expose only these reversible inputs after source pin
            # verification; any later error restores their original bytes.
            with GenerationTransaction() as transaction:
                transaction.replace(ledgers)
                production = distribution.write_standard_outputs(
                    configuration=_profile_configuration(configuration), transaction=transaction
                )
            console.print(
                f"[green]已重建 {len(bindings)} 条原版消费者绑定和 "
                f"{len(situated_domain_coverage.FAMILIES)} 个领域统计[/]"
            )
            console.print(f"[green]已生成 {len(production)} 个生产文件：UTF-8 无 BOM、LF[/]")
            return
        if check:
            source_problems = [
                *situated_bindings.check(),
                *situated_domain_coverage.check_counts(),
            ]
            if source_problems:
                _fail("生成合同不一致：\n" + "\n".join(source_problems), EXIT_FAILED)
        _, _, files = distribution.package_inputs(
            configuration=_profile_configuration(configuration)
        )
        production = {name: text for name, text in files.items() if name != "README.md"}
        if check:
            problems = decisions.check(decisions.PRODUCT, production)
            distribution.check_generation_lock()
            if problems:
                _fail("生成物不一致：\n" + "\n".join(problems), EXIT_FAILED)
            console.print(f"[green]{len(production)} 个生产文件与源逐字节一致[/]")
        else:
            console.print(
                f"Situated AI {distribution.RELEASE_VERSION}：{len(production)} 个生产文件；--write 生成 / --check 核对"
            )
    except (ValueError, OSError) as exc:
        _fail(f"生成失败：{exc}", EXIT_FAILED)


def package_cmd(
    output: Annotated[Path, typer.Option("--output", help="正式 ZIP 输出路径")] = (
        distribution.DEFAULT_PACKAGE_PATH
    ),
    profile: Annotated[str | None, typer.Option("--profile", help="断言当前生产版本")] = None,
    configuration: Annotated[
        Path | None, typer.Option("--configuration", help="1.15 profile TOML 配置")
    ] = None,
    original_candidate: Annotated[
        bool, typer.Option("--original-candidate", help="从原创生成器冻结独立候选安装树和 ZIP")
    ] = False,
) -> None:
    """核对生产生成物后打包；仅在游戏交付边界添加 BOM。"""
    require_workspace()
    try:
        if original_candidate:
            if output != distribution.DEFAULT_PACKAGE_PATH or configuration is not None:
                raise ValueError("原创候选使用固定的隔离目录与已审功能范围")
            version_contracts.require_current(profile)
            from pdx import original_candidate as candidate  # noqa: PLC0415

            target = candidate.build()
            console.print(f"[green]已冻结原创本地候选[/] {escape(str(target))}")
            return
        _production_profile(profile)
        target = distribution.package(output, configuration=_profile_configuration(configuration))
    except (ValueError, OSError) as exc:
        _fail(f"打包失败：{exc}", EXIT_FAILED)
    console.print(f"[green]已生成[/] {escape(str(target))}")


def modguard_cmd(
    offline: Annotated[bool, typer.Option("--offline", help="从入库快照核对原版接口")] = False,
    profile: Annotated[str | None, typer.Option("--profile", help="断言当前生产版本")] = None,
    configuration: Annotated[
        Path | None, typer.Option("--configuration", help="1.15 profile TOML 配置")
    ] = None,
    writer_transition: Annotated[
        Path | None,
        typer.Option("--writer-transition", help="从冻结原创候选 ZIP 核对 3.4.0 逐写点处置"),
    ] = None,
) -> None:
    """检查唯一生产包的生成、语法、底本和原版接口；不推断 AI 行为质量。"""
    require_workspace()
    try:
        if writer_transition is not None:
            from pdx.writer_transition import check_candidate  # noqa: PLC0415

            version_contracts.require_current(profile)
            if configuration is not None:
                raise ValueError("逐写点核对使用已冻结候选的配置")
            console.print_json(data=check_candidate(writer_transition))
            return
        _production_profile(profile, offline=offline)
        if offline:
            distribution.check_generation_lock()
            policy, extensions = distribution.production_configuration(
                configuration=_profile_configuration(configuration)
            )
            production = distribution.read_production_files()
            distribution.check_configuration_identity(
                production, _profile_configuration(configuration)
            )
            problems = []
        else:
            policy, extensions, files = distribution.package_inputs(
                configuration=_profile_configuration(configuration)
            )
            production = {name: text for name, text in files.items() if name != "README.md"}
            problems = decisions.check(decisions.PRODUCT, production)
        index = vanilla_index.load(offline=offline)
        if index is None:
            _fail("缺少原版接口证据：请提供锁定游戏或使用入库快照")
        problems.extend(
            decisions.validate(
                index.vocabulary(),
                game=None if offline else config.GAME,
                snapshot={"域": index.sections} if offline else None,
                policy=policy,
                extensions=extensions,
                country_policy=country_state.load(),
            )
        )
        for name, text in production.items():
            if name.endswith(".txt") and isinstance(text, str):
                problems.extend(f"{name}: {error}" for error in parse_text(text, name).errors)
        if problems:
            _fail("生产工程检查失败：\n" + "\n".join(problems), EXIT_FAILED)
    except (ValueError, OSError) as exc:
        _fail(f"生产工程检查失败：{exc}", EXIT_FAILED)
    console.print(
        "[green]冻结源码/产物、脚本语法与快照接口检查通过[/]"
        if offline
        else "[green]生产生成、脚本语法、锁定底本与原版接口检查通过[/]"
    )
    console.print("证据：" + ("入库快照（不证明当前游戏内容）" if offline else "本机原版目录"))
    console.print("长期行为、平衡、玩家体验和游戏性能由用户验收。")


def decision_audit_cmd(
    output: Annotated[
        Path | None,
        typer.Option("--output", help="情境决策报告 JSON 输出路径；默认写入 tools/out/ci/"),
    ] = None,
    offline: bool = typer.Option(
        False,
        "--offline",
        help="从入库生产源和原版声明核对静态合同；适用于无游戏目录的 CI",
    ),
    profile: Annotated[str | None, typer.Option("--profile", help="断言当前生产版本")] = None,
    configuration: Annotated[
        Path | None, typer.Option("--configuration", help="1.15 profile TOML 配置")
    ] = None,
) -> None:
    """核对情境决策合同并生成可解释报告。

    默认复用一次生产构建得到的 engineering metadata。``--offline`` 从入库生产源和
    原版声明核对静态合同，供无游戏目录的 CI 使用。AI 行为和平衡仍需实机验收。
    """
    require_workspace()
    target = output or (config.OUT / "ci" / "decision-audit.json")
    try:
        _production_profile(profile, offline=offline)
        if offline:
            metadata = decision_report.source_metadata(
                configuration=_profile_configuration(configuration)
            )
        else:
            _, _, files = distribution.package_inputs(
                include_engineering_metadata=True,
                configuration=_profile_configuration(configuration),
            )
            metadata = json.loads(files[".metadata/metadata.json"])
            if not isinstance(metadata, dict):
                raise ValueError("工程 metadata 顶层必须是对象")
        report = decision_report.build(metadata)
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
        _fail(f"情境决策合同检查失败：{exc}", EXIT_FAILED)
    _write_json(target, report)
    domains = report["domains"]
    mapped = sum(row["status"] == "consumer_mapped" for row in domains.values())
    console.print(
        f"[green]情境决策合同通过[/]：{mapped}/{len(domains)} 个域已连接原版消费者，"
        f"{report['reader_count']} 个读取器（信息 {report['information_reader_count']}、"
        f"消费者 {report['consumer_reader_count']}），"
        f"{report['information_rule_count'] + report['consumer_rule_count']} 条规则"
    )
    console.print("证据：静态生成合同；行为、平衡和长期性能仍由用户实机验收。")
