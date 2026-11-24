"""Publish one frozen release identity to explicitly selected channels."""

from __future__ import annotations

from typing import Annotated
lazy from pathlib import Path

import typer

from pdx import distribution
from pdx.cli_commands.common import EXIT_FAILED, console, fail, require_workspace
from pdx.publishing.runner import (
    CHANNELS,
    ReleaseIdentity,
    SuccessorReview,
    plan_release,
    run_release,
)


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
    github_notes_file: Annotated[
        Path | None,
        typer.Option("--github-notes-file", help="附加到 GitHub Release 的 UTF-8 Markdown"),
    ] = None,
    expected_github_notes_sha256: Annotated[
        str | None,
        typer.Option("--expected-github-notes-sha256", help="预审后的 GitHub 发布说明 SHA-256"),
    ] = None,
    successor_review: Annotated[
        Path | None,
        typer.Option("--successor-review", help="包外后继来源审查 JSON"),
    ] = None,
    successor_review_sha256: Annotated[
        str | None,
        typer.Option("--successor-review-sha256", help="独立固定的审查原字节 SHA-256"),
    ] = None,
    previous_release_zip: Annotated[
        Path | None,
        typer.Option("--previous-release-zip", help="首次切换所用的正式 3.4.0 ZIP"),
    ] = None,
) -> None:
    """Build, validate, publish, and install the same release package."""
    require_workspace()
    selected = tuple(dict.fromkeys(channel or ()))
    unknown = set(selected) - CHANNELS
    if unknown:
        fail("未知发布渠道：" + ", ".join(sorted(unknown)))

    try:
        proof = None
        if (
            successor_review is not None
            or successor_review_sha256 is not None
            or previous_release_zip is not None
        ):
            if successor_review is None or successor_review_sha256 is None:
                raise ValueError("后继来源核对要求同时指定审查文件和独立摘要")
            proof = SuccessorReview(
                successor_review, successor_review_sha256.lower(), previous_release_zip
            )
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
            github_notes=(
                github_notes_file.read_bytes().decode("utf-8")
                if github_notes_file is not None
                else None
            ),
        )
        if expected_github_notes_sha256 is not None:
            if identity.github_notes is None:
                raise ValueError("--expected-github-notes-sha256 需要 --github-notes-file")
            if identity.github_notes_sha256 != expected_github_notes_sha256.lower():
                raise ValueError("GitHub 发布说明的 SHA-256 与预审摘要不同")
        if apply:
            result = run_release(identity, successor_review=proof)
        else:
            result = plan_release(identity, successor_review=proof)
    except (ValueError, OSError, RuntimeError) as exc:
        fail(f"发布受阻：{exc}", EXIT_FAILED)
    console.print_json(data=result)
    if result["status"] not in {"planned", "verified"}:
        raise typer.Exit(EXIT_FAILED)
