"""Analysis and verified research catalog commands."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path  # noqa: TC003 - Typer resolves annotations at runtime.
from typing import Annotated, Any, Literal, NoReturn

import typer
from rich.markup import escape
from rich.table import Table

from pdx import (
    analyze,
    candidate_coverage,
    config,
    consumer_matrix,
    distribution,
    information_catalog,
    input_inventory,
    research_catalog,
    script_research_index,
    version_contracts,
)

from . import common
from .common import EXIT_FAILED, EXIT_USAGE, console
from .common import fail as _fail
from .common import relative as _relative
from .common import write_json as _write_json


def _profile_run(
    *, with_mods: bool, with_cross: bool
) -> tuple[analyze.GameAnalysis, analyze.ModsAnalysis, analyze.CrossAnalysis, Any]:
    """用 pyinstrument 包住整个分析流程。

    pyinstrument 给的是**调用树**而不是我自己分段的粗粒度计时 —— 能直接
    看到时间花在哪个函数上，比手工埋点精确得多。

    ``--profile`` 下同样尊重 ``--no-mods`` / ``--no-cross``：旧脚本在剖析
    分支里漏判了 ``--no-cross``，两条路径的口径不该有差别。
    """
    # pyinstrument 是 dev 依赖。顶层导入会让没装 dev extras 的环境连
    # `v3 --help` 都跑不起来，所以只在这里按需导入。
    try:
        from pyinstrument import Profiler  # noqa: PLC0415
    except ImportError as exc:
        _fail(f'--profile 需要 pyinstrument，请先 pip install -e ".[dev]"：{exc}')

    profiler = Profiler(interval=0.001)
    profiler.start()

    ga = analyze.game_analysis()
    ma = analyze.ModsAnalysis()
    ca = analyze.CrossAnalysis()
    if with_mods:
        ma = analyze.mods_analysis()
        if with_cross:
            ca = analyze.cross_analysis(ma, verbose=False)

    profiler.stop()
    return ga, ma, ca, profiler


def _research_inputs(
    raw_root: Path | None, epoch: str | None, output_dir: Path | None
) -> tuple[Path, str, Path] | None:
    if raw_root is None and epoch is None and output_dir is None:
        return None
    if raw_root is None or epoch is None or output_dir is None:
        _fail("规范研究模式须同时提供 --raw-root、--epoch 和 --output-dir")
    return raw_root, epoch, output_dir


def _write_research_catalog(raw_root: Path, epoch: str, output_dir: Path) -> None:
    try:
        marker = research_catalog.write(raw_root, epoch, output_dir)
    except (OSError, ValueError) as exc:
        _fail(f"规范研究构建失败：{exc}", EXIT_FAILED)
    console.print(f"[green]规范研究目录已写入[/] {escape(str(marker.parent))}")


def analyze_cmd(
    ctx: typer.Context,
    mods: Annotated[
        bool, typer.Option("--mods/--no-mods", help="分析全部 mod（关闭则只看游戏本体）")
    ] = True,
    cross: Annotated[
        bool, typer.Option("--cross/--no-cross", help="做 mod 与原版的交叉分析")
    ] = True,
    write: Annotated[
        bool, typer.Option("--write/--no-write", help="把 JSON 与 Markdown 落盘")
    ] = True,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="不打印进度")] = False,
    profile: Annotated[
        bool, typer.Option("--profile", help="用 pyinstrument 输出调用树剖析")
    ] = False,
    raw_root: Annotated[
        Path | None, typer.Option("--raw-root", help="完整安装研究模式的只读 raw 根")
    ] = None,
    epoch: Annotated[
        str | None, typer.Option("--epoch", help="已提交 raw epoch 的 SHA-256")
    ] = None,
    output_dir: Annotated[
        Path | None, typer.Option("--output-dir", help="研究结果的本机新目录")
    ] = None,
    installation: Annotated[
        bool, typer.Option("--installation", help="只读全量分析 V3_ROOT 并保存来源位置")
    ] = False,
) -> None:
    """分析已提交的完整游戏安装，或生成现场原版及 Mod 概览。

    完整安装研究同时使用 --raw-root、--epoch、--output-dir，生成逐文件处置和
    SQLite 出现位置索引。现场概览默认依次分析原版、Mod 和交叉关系，可用
    --no-mods、--no-cross、--no-write 或 --profile 调整，--quiet 关闭进度行。
    """
    if installation:
        if raw_root is not None or epoch is not None or output_dir is None:
            _fail("--installation 须提供 --output-dir，且与 --raw-root / --epoch 互斥")
        research = None
    else:
        research = _research_inputs(raw_root, epoch, output_dir)
    if installation or research is not None:
        if not write or profile:
            _fail("完整安装研究模式不能使用 --no-write 或 --profile")
        if any(
            enabled
            and (origin := ctx.get_parameter_source(name)) is not None
            and origin.name == "COMMANDLINE"
            for name, enabled in (("mods", mods), ("cross", cross))
        ):
            _fail("完整安装研究模式不接受 --mods 或 --cross")
        if research is not None:
            _write_research_catalog(*research)
        else:
            assert output_dir is not None
            try:
                marker = research_catalog.write_installation(config.ROOT, output_dir)
            except (OSError, ValueError) as exc:
                _fail(f"现场研究构建失败：{exc}", EXIT_FAILED)
            console.print(f"[green]安装研究目录已写入[/] {escape(str(marker.parent))}")
        return
    if write:
        common.require_workspace()
    common.require_game()
    started = time.perf_counter()

    if profile:
        ga, ma, ca, profiler = _profile_run(with_mods=mods, with_cross=cross)
        elapsed = time.perf_counter() - started
        console.print()
        # 剖析结果是预格式化文本：关掉 markup/highlight/折行，免得被 rich 重排。
        console.print(
            profiler.output_text(unicode=True, color=False, show_all=False),
            markup=False,
            highlight=False,
            soft_wrap=True,
        )
    else:
        if not quiet:
            console.print("[cyan]▶ 分析游戏本体 …[/]")
        ga = analyze.game_analysis()
        ma = analyze.ModsAnalysis()
        ca = analyze.CrossAnalysis()

        if mods:
            if not quiet:
                console.print("[cyan]▶ 分析 mod …[/]")
            ma = analyze.mods_analysis()

        if mods and cross:
            if not quiet:
                console.print("[cyan]▶ 交叉分析 …[/]")
            ca = analyze.cross_analysis(ma, verbose=False)

        elapsed = time.perf_counter() - started

    if write:
        paths = analyze.write_reports(ga, ma, ca)
        table = Table(title="产出", show_lines=False)
        table.add_column("类型")
        table.add_column("文件", style="cyan")
        table.add_column("字节", justify="right")
        for name, path in paths.items():
            table.add_row(escape(name), escape(_relative(path)), f"{path.stat().st_size:,}")
        console.print(table)

    console.print(f"\n总耗时 {elapsed:.1f} 秒")


def research_query_cmd(
    directory: Annotated[Path, typer.Argument(help="包含 COMPLETE.json 的本机研究目录")],
    source: Annotated[list[str] | None, typer.Option(help="来源相对路径，可重复")] = None,
    key: Annotated[str | None, typer.Option(help="精确结构键")] = None,
    symbol: Annotated[list[str] | None, typer.Option(help="脚本符号名称，可重复")] = None,
    script_references: Annotated[
        bool, typer.Option("--script-references", help="包括 --source 所选文件的全部脚本引用候选")
    ] = False,
    reference_after: Annotated[
        str | None, typer.Option(help="引用续页位置，格式为 occurrence_id:ordinal")
    ] = None,
    source_details: Annotated[
        bool, typer.Option("--source-details", help="包括 --source 所选文件的格式元数据")
    ] = False,
    after: Annotated[str, typer.Option(help="上一页的最后一个位置 ID")] = "",
    limit: Annotated[int, typer.Option(min=1, max=10000, help="每组查询的最大行数")] = 100,
    coverage_report: Annotated[
        bool, typer.Option("--coverage-report", help="包含按独立分母汇总的全部逐项覆盖与缺口")
    ] = False,
    historical_locators: Annotated[
        bool, typer.Option("--historical-locators", help="读取已登记的旧实现位置索引")
    ] = False,
) -> None:
    """核对完整研究目录，返回覆盖统计和所选位置的 JSON。"""

    def fail_query(message: str, code: int = EXIT_USAGE) -> NoReturn:
        typer.echo(message, err=True)
        raise typer.Exit(code)

    if source_details and not source:
        fail_query("--source-details 须提供 --source")
    if script_references and not source:
        fail_query("--script-references 须提供 --source")
    if reference_after is not None:
        if not (symbol or script_references):
            fail_query("--reference-after 须提供 --symbol 或 --script-references")
        try:
            symbol_cursor = script_research_index.reference_cursor(reference_after)
        except ValueError as exc:
            fail_query(str(exc))
    else:
        symbol_cursor = ("", -1)
    try:
        with research_catalog.open_published(
            directory, historical_locators=historical_locators
        ) as (publication, connection):
            sources: list[str | None] = list(source) if source else [None]
            queries = [
                {
                    "source": path,
                    "key": key,
                    "occurrences": [
                        asdict(row)
                        for row in publication.index.find_in_connection(
                            connection, source=path, key=key, after=after, limit=limit
                        )
                    ],
                }
                for path in sources
                if path is not None or key is not None
            ]
            result: dict[str, object] = {
                "epoch_id": publication.index.epoch_id,
                "file_set_sha256": publication.index.file_set_sha256,
                "implementation_sha256": publication.index.implementation_sha256,
                "implementation_status": publication.implementation_status,
                "index_projection": publication.projection,
                "coverage": publication.coverage,
                "queries": queries,
            }
            if coverage_report:
                result["research_coverage"] = publication.research_coverage
            if source_details:
                assert source
                result["source_details"] = {
                    path: publication.index.source_metadata_in_connection(connection, path)
                    for path in source
                }
            if symbol or script_references:
                if publication.implementation_status == "historical_locators":
                    result["script_symbols"] = {"status": "historical_locators_only", "queries": []}
                else:
                    result["script_symbols"] = {
                        "status": "static_candidates",
                        "incomplete_definition_sources": (
                            script_research_index.incomplete_definition_sources(connection)
                        ),
                        "queries": [
                            script_research_index.query_symbol(
                                connection, name, limit=limit, after=symbol_cursor
                            )
                            for name in (symbol or [])
                        ],
                        "source_references": [
                            script_research_index.query_source(
                                connection, path, limit=limit, after=symbol_cursor
                            )
                            for path in (source or [])
                            if script_references
                        ],
                    }
    except (OSError, ValueError, sqlite3.Error) as exc:
        fail_query(f"研究目录读取失败：{exc}", EXIT_FAILED)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


def input_inventory_cmd() -> None:
    """按 V3_ROOT 只读盘点安装根，将原字节的文件元数据写到标准输出。"""
    try:
        verified = version_contracts.verify_installation_identity(config.ROOT)
    except (OSError, ValueError) as exc:
        typer.echo(
            f"V3_ROOT 安装身份校验失败，盘点要求 Victoria 3 {version_contracts.CURRENT_VERSION}。",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE) from exc
    contract = version_contracts.contract(version_contracts.CURRENT_VERSION)
    scan = input_inventory.inventory_installation(verified.root, verified=verified)
    version_matched = input_inventory.matches_default_strategy(
        scan, contract.default_strategy_sha256
    )
    payload = {
        "schema": 1,
        "evidence_kind": "static_check",
        "scan_status": scan.scan_status,
        "expected_version": contract.version,
        "version_anchor": {
            "path": input_inventory.DEFAULT_STRATEGY_ANCHOR,
            "matched": version_matched,
        },
        "file_set_sha256": scan.file_set_sha256,
        "summary": asdict(scan.summary),
        "blocked_directories": scan.blocked_directories,
        "unrecorded_paths": [
            path.encode("unicode_escape").decode("ascii")
            for path in sorted(
                set(scan.observed_paths).difference(record.path for record in scan.records)
            )
        ],
        "diagnostic_codes": sorted({diagnostic.code for diagnostic in scan.diagnostics}),
        "records": [
            {
                "path": record.path,
                "size": record.size,
                "sha256": record.sha256,
                "category": record.category,
                "read_status": record.read_status,
                "diagnostic_codes": sorted({diagnostic.code for diagnostic in record.diagnostics}),
            }
            for record in scan.records
        ],
    }
    typer.echo(json.dumps(payload, separators=(",", ":")))
    if scan.scan_status != "complete" or not version_matched:
        raise typer.Exit(EXIT_FAILED)


def information_catalog_cmd(
    ctx: typer.Context,
    raw_root: Annotated[
        Path | None, typer.Option("--raw-root", help="规范研究模式的只读 raw 根")
    ] = None,
    epoch: Annotated[
        str | None, typer.Option("--epoch", help="已提交 raw epoch 的 SHA-256")
    ] = None,
    output_dir: Annotated[
        Path | None, typer.Option("--output-dir", help="研究结果的本机新目录")
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="能力目录 JSON 输出路径；默认写入 tools/out/game/"),
    ] = None,
    localization: Annotated[
        bool,
        typer.Option(
            "--localization/--no-localization",
            help="是否登记本体本地化文件入口并生成键级目录",
        ),
    ] = True,
    localization_keys_output: Annotated[
        Path | None,
        typer.Option(
            "--localization-keys-output",
            help="键级本地化 JSONL 输出路径；默认与主目录一起写入 tools/out/game/",
        ),
    ] = None,
    consumer_matrix_output: Annotated[
        Path | None,
        typer.Option(
            "--consumer-matrix-output",
            help="静态同名候选关联矩阵 JSON；不表示运行时消费者已接通",
        ),
    ] = None,
    candidate_metadata: Annotated[
        Path | None,
        typer.Option(
            "--candidate-metadata",
            help="读取实际 integrated 候选合同；启动器 descriptor metadata 不含此合同",
        ),
    ] = None,
    candidate_production: Annotated[
        bool,
        typer.Option(
            "--candidate-production",
            help="从当前生产源生成 integrated 合同并连接，不手工导出候选 metadata",
        ),
    ] = False,
    candidate_coverage_output: Annotated[
        Path | None,
        typer.Option("--candidate-coverage-output", help="候选规则与目录的精确连接和未覆盖差集"),
    ] = None,
    candidate_dispositions_output: Annotated[
        Path | None,
        typer.Option(
            "--candidate-dispositions-output", help="每条目录信息的静态处置 JSONL/JSONL.GZ"
        ),
    ] = None,
) -> None:
    """生成锁定游戏版本的静态信息与消费者目录。

    该命令只声明静态发现及原版文件中的同名候选关联；
    运行时读取、行为质量和实机验证由用户在标准包上推进；本命令只登记静态能力，
    后续按权威实施计划逐步核对；静态登记不等于运行期行为通过。
    """

    research = _research_inputs(raw_root, epoch, output_dir)
    if research is not None:
        localization_source = ctx.get_parameter_source("localization")
        if (
            any(
                value is not None
                for value in (
                    output,
                    localization_keys_output,
                    consumer_matrix_output,
                    candidate_metadata,
                    candidate_coverage_output,
                    candidate_dispositions_output,
                )
            )
            or candidate_production
            or (localization_source is not None and localization_source.name == "COMMANDLINE")
        ):
            _fail("规范研究模式不能混用现场目录、候选或本地化选项")
        _write_research_catalog(*research)
        return

    if candidate_metadata is not None and candidate_production:
        console.print("[red]--candidate-metadata 与 --candidate-production 只能选一个[/]")
        raise typer.Exit(EXIT_USAGE)
    has_candidate = candidate_metadata is not None or candidate_production
    if candidate_coverage_output is not None and not has_candidate:
        console.print(
            "[red]--candidate-coverage-output 需要 --candidate-metadata 或 --candidate-production[/]"
        )
        raise typer.Exit(EXIT_USAGE)
    if candidate_dispositions_output is not None and not has_candidate:
        console.print(
            "[red]--candidate-dispositions-output 需要 --candidate-metadata 或 --candidate-production[/]"
        )
        raise typer.Exit(EXIT_USAGE)
    if (
        output is None
        or consumer_matrix_output is None
        or (localization and localization_keys_output is None)
        or candidate_production
    ):
        common.require_workspace()
    target = output or (config.OUT_GAME / "information-catalog.json")
    matrix_target = consumer_matrix_output or (config.OUT_GAME / "consumer-matrix.json")
    coverage_target = candidate_coverage_output or target.with_name("candidate-coverage.json")
    dispositions_target = candidate_dispositions_output or target.with_name(
        "candidate-dispositions.jsonl.gz"
    )
    disposition_stem = dispositions_target.name.removesuffix(".jsonl.gz").removesuffix(".jsonl")
    disposition_summary_target = dispositions_target.with_name(f"{disposition_stem}-summary.json")
    localization_target = localization_keys_output or (
        config.OUT_GAME / "information-localization.jsonl"
    )
    output_paths = [target, matrix_target]
    if has_candidate:
        output_paths.extend((coverage_target, dispositions_target, disposition_summary_target))
    if localization:
        output_paths.append(localization_target)
    resolved = [path.resolve() for path in output_paths]
    if len(set(resolved)) != len(resolved) or (
        candidate_metadata is not None and candidate_metadata.resolve() in resolved
    ):
        console.print("[red]各输出路径和候选输入路径必须互不相同[/]")
        raise typer.Exit(EXIT_USAGE)
    metadata = None
    metadata_origin: Literal["caller_supplied", "current_production_sources"] = (
        "current_production_sources" if candidate_production else "caller_supplied"
    )
    common.require_game()
    if candidate_metadata is not None:
        try:
            metadata = json.loads(candidate_metadata.read_text(encoding="utf-8"))
            if not isinstance(metadata, dict):
                raise ValueError("候选清单必须为 JSON 对象")
        except (OSError, ValueError) as exc:
            console.print(f"[red]候选清单不可读：{escape(str(exc))}[/]")
            raise typer.Exit(EXIT_USAGE) from exc
    elif candidate_production:
        try:
            _, _, production_files = distribution.package_inputs(include_engineering_metadata=True)
            metadata_text = production_files.get(".metadata/metadata.json")
            if metadata_text is None:
                raise ValueError("生产候选缺少 integrated metadata")
            metadata = json.loads(metadata_text)
            if not isinstance(metadata, dict):
                raise ValueError("生产候选合同必须为 JSON 对象")
        except (KeyError, OSError, ValueError) as exc:
            console.print(f"[red]当前生产候选合同不可用：{escape(str(exc))}[/]")
            raise typer.Exit(EXIT_USAGE) from exc
    started = time.perf_counter()
    catalog = information_catalog.build(include_localization=localization)
    if metadata is not None:
        try:
            coverage_report = candidate_coverage.build(
                catalog, metadata, metadata_origin=metadata_origin
            )
            try:
                catalog_artifact = target.resolve().relative_to(config.REPO.resolve()).as_posix()
            except ValueError:
                catalog_artifact = target.name
            try:
                disposition_summary = candidate_coverage.write_dispositions(
                    catalog,
                    coverage_report,
                    dispositions_target,
                    catalog_artifact=catalog_artifact,
                )
            except OSError as exc:
                _fail(
                    f"无法写入 {dispositions_target}：{type(exc).__name__}: {exc}",
                    EXIT_FAILED,
                )
        except ValueError as exc:
            console.print(
                f"[red]候选连接失败：{escape(str(exc))}[/]；本次未写入报告，已有文件仅属于先前运行"
            )
            raise typer.Exit(EXIT_USAGE) from exc
        _write_json(coverage_target, coverage_report)
        _write_json(disposition_summary_target, disposition_summary)
        console.print(
            f"候选连接已生成：{_relative(coverage_target)}，"
            f"{len(coverage_report['links'])} 条规则连接，"
            f"{len(coverage_report['unresolved'])} 条未解决连接；不提升证据等级"
        )
        console.print(
            f"信息处置清单已生成：{_relative(dispositions_target)}，"
            f"{disposition_summary['item_count']} 条；摘要："
            f"{_relative(disposition_summary_target)}"
        )
    catalog.write(target)
    consumer_matrix.ConsumerMatrix.from_catalog(catalog).write(matrix_target)
    localization_stats: dict[str, int] | None = None
    if localization:
        localization_stats = information_catalog.write_localization_catalog(localization_target)
    elapsed = time.perf_counter() - started
    console.print(
        f"[green]能力目录已生成[/] {_relative(target)}："
        f"{len(catalog.items):,} 条，耗时 {elapsed:.1f} 秒"
    )
    if localization_stats is not None:
        console.print(
            f"键级本地化目录已生成：{localization_stats['files']:,} 个文件，"
            f"{localization_stats['keys']:,} 个键，"
            f"{localization_stats['errors']:,} 个 unsupported 记录"
        )
    console.print(f"静态消费者矩阵已生成：{_relative(matrix_target)}")
    console.print(
        "静态发现不等于运行时可读或行为通过；未确认项保持 discovered/unknown，"
        "候选连接只证明静态合同映射；后续阶段按权威实施计划推进。"
    )
