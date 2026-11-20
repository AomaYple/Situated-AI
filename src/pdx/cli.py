"""Typer entry point for the Victoria 3 research and Mod toolchain."""

import typer

from pdx import cache, version_contracts
from pdx.cli_commands import (
    analysis_outputs,
    documentation,
    engine_evidence,
    game_data,
    maintenance,
    release,
    research,
    situated,
    snapshots,
    verification,
)
from pdx.cli_commands.common import EXIT_FAILED, EXIT_UNVERIFIABLE, EXIT_USAGE

__all__ = ["EXIT_FAILED", "EXIT_UNVERIFIABLE", "EXIT_USAGE", "app"]


app = typer.Typer(
    name="v3",
    help="Victoria 3 mod 开发研究工具链：全量分析、defines 提取、断言核对与产物核验。",
    # typer 默认会为 `--install-completion` 生成补全脚本并写进用户目录
    # （~/.bash_completion 等）。工具链不该在用户不知情时接管家目录，
    # 因此关掉 —— 代价是没有 shell 补全，换来的是「装包不留痕」。
    add_completion=False,
    no_args_is_help=True,
)


@app.callback()
def _command_lifetime(context: typer.Context) -> None:
    """Validate the contract assertion and release the memo on exit."""
    context.call_on_close(cache.release_memo)
    try:
        version_contracts.require_current()
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_USAGE) from exc


situated_app = typer.Typer(
    help="处境行动内核的静态审计、报告和解释。",
    no_args_is_help=True,
)
situated_app.command("audit")(situated.situated_audit_cmd)
situated_app.command("inventory")(situated.situated_inventory_cmd)
situated_app.command("report")(situated.situated_report_cmd)
situated_app.command("explain")(situated.situated_explain_cmd)
app.add_typer(situated_app, name="situated")


snapshot_app = typer.Typer(
    help="捕获、验证和比较当前原版安装的 Mod 相关信息。",
    add_completion=False,
    no_args_is_help=True,
)
snapshot_app.command("create")(snapshots.snap_create)
snapshot_app.command("list")(snapshots.snap_list)
snapshot_app.command("diff")(snapshots.snap_diff)
snapshot_app.command("verify")(snapshots.snap_verify)
app.add_typer(snapshot_app, name="snapshot")


mirror_app = typer.Typer(help="官方 .md 的清单与本地镜像。", no_args_is_help=True)
mirror_app.command("check")(documentation.mirror_check)
mirror_app.command("write")(documentation.mirror_write)
app.add_typer(mirror_app, name="mirror")


app.command("analyze")(research.analyze_cmd)
app.command("research-query")(research.research_query_cmd)
app.command("input-inventory")(research.input_inventory_cmd)
app.command("information-catalog")(research.information_catalog_cmd)
app.command("defines")(game_data.defines_cmd)
app.command("index")(documentation.index_cmd)
app.command("refresh")(documentation.refresh_cmd)
app.command("tables")(documentation.tables_cmd)
app.command("verify")(verification.verify_cmd)
app.command("crosscheck")(engine_evidence.crosscheck_cmd)
app.command("check-outputs")(analysis_outputs.check_outputs_cmd)
app.command("strings")(engine_evidence.strings_cmd)
app.command("lock")(maintenance.lock_cmd)
app.command("cov")(maintenance.cov_cmd)
app.command("cache")(maintenance.cache_cmd)
app.command("evidence")(engine_evidence.evidence_cmd)
app.command("prefixes")(game_data.prefixes_cmd)
app.command("assets")(game_data.assets_cmd)
app.command("csv")(game_data.csv_cmd)
app.command("ai-surface")(game_data.ai_surface_cmd)
app.command("political-surface")(game_data.political_surface_cmd)
app.command("modgen")(release.modgen_cmd)
app.command("package")(release.package_cmd)
app.command("citations")(documentation.citations_cmd)
app.command("modguard")(release.modguard_cmd)
app.command("decision-audit")(release.decision_audit_cmd)
app.command("unverified")(documentation.unverified_cmd)
app.command("show")(analysis_outputs.show_cmd)


if __name__ == "__main__":  # pragma: no cover - 手工运行入口
    app()
