"""Publish one frozen release identity to explicitly selected channels."""

from __future__ import annotations

from typing import Annotated
lazy from pathlib import Path

import typer

from pdx import distribution
from pdx.cli_commands.common import EXIT_FAILED, console, fail, require_workspace
from pdx.publishing.runner import CHANNELS, ReleaseIdentity, plan_release, run_release


def publish_cmd(
    version: Annotated[
        str, typer.Option(help="正式版本，例如 3.3.1")
    ] = distribution.RELEASE_VERSION,
    tag: Annotated[str | None, typer.Option(help="不可移动正式标签，默认 v<version>")] = None,
    commit: Annotated[str | None, typer.Option(help="40 位源提交，默认当前 HEAD")] = None,
    github_repo: Annotated[
        str | None, typer.Option("--github-repo", help="GitHub OWNER/REPO")
    ] = None,
    channel: Annotated[
        list[str] | None,
        typer.Option("--channel", help="重复指定 github、local 或 workshop"),
    ] = None,
    publication_dir: Annotated[
        Path | None, typer.Option("--publication-dir", help="持久包与收据目录")
    ] = None,
    local_root: Annotated[
        Path | None, typer.Option("--local-root", help="明确的用户 mod 根目录")
    ] = None,
    local_previous_sha256: Annotated[
        str | None,
        typer.Option("--local-previous-sha256", help="Situated AI 旧树 SHA-256，或 absent"),
    ] = None,
    workshop_item: Annotated[
        str | None, typer.Option("--workshop-item", help="已存在的 Workshop item ID")
    ] = None,
    workshop_owner: Annotated[
        str | None, typer.Option("--workshop-owner", help="已确认的 Workshop owner ID")
    ] = None,
    workshop_helper: Annotated[
        Path | None, typer.Option("--workshop-helper", help="Steamworks SDK 助手的绝对路径")
    ] = None,
    apply: Annotated[bool, typer.Option("--apply", help="执行已计划的外部操作")] = False,
) -> None:
    """Build, validate, publish, and install the same release package."""
    require_workspace()
    selected = tuple(dict.fromkeys(channel or ()))
    unknown = set(selected) - CHANNELS
    if unknown:
        fail("未知发布渠道：" + ", ".join(sorted(unknown)))
    try:
        identity = ReleaseIdentity(
            version=version,
            tag=tag or f"v{version}",
            commit=commit or "",
            github_repo=github_repo or "",
            channels=selected,
            publication_dir=publication_dir,
            local_root=local_root,
            local_previous_sha256=local_previous_sha256,
            workshop_item=workshop_item,
            workshop_owner=workshop_owner,
            workshop_helper=workshop_helper,
        )
        if apply:
            result = run_release(identity)
        else:
            result = plan_release(identity)
    except (ValueError, OSError, RuntimeError) as exc:
        fail(f"发布受阻：{exc}", EXIT_FAILED)
    console.print_json(data=result)
    if result["status"] not in {"planned", "verified"}:
        raise typer.Exit(EXIT_FAILED)
