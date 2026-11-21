"""Validated identity shared by every selected publication channel."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

CHANNELS = frozenset({"github", "local", "workshop"})


@dataclass(frozen=True, slots=True)
class ReleaseIdentity:
    version: str
    tag: str
    commit: str
    github_repo: str
    channels: Sequence[str]
    publication_dir: Path | None = None
    local_root: Path | None = None
    local_previous_sha256: str | None = None
    workshop_item: str | None = None
    workshop_owner: str | None = None
    workshop_helper: Path | None = None

    def validate(self, *, applying: bool) -> None:
        if (
            re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", self.version)
            is None
        ):
            raise ValueError("版本必须是 MAJOR.MINOR.PATCH")
        if self.tag != f"v{self.version}":
            raise ValueError("正式标签必须严格等于 v<version>")
        if self.commit and re.fullmatch(r"[0-9a-f]{40}", self.commit) is None:
            raise ValueError("源提交必须是完整 40 位小写 Git SHA")
        if len(set(self.channels)) != len(self.channels) or set(self.channels) - CHANNELS:
            raise ValueError("发布渠道重复或未知")
        if self.github_repo and (
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", self.github_repo)
            is None
            or self.github_repo.rsplit("/", 1)[-1] in {".", ".."}
        ):
            raise ValueError("GitHub 仓库必须是 OWNER/REPO")
        if (
            self.local_previous_sha256 not in (None, "absent")
            and re.fullmatch(r"[a-f0-9]{64}", self.local_previous_sha256) is None
        ):
            raise ValueError("本地旧目录摘要必须是 SHA-256 或 absent")
        if (
            self.workshop_item is not None
            and re.fullmatch(r"[1-9][0-9]{0,19}", self.workshop_item) is None
        ):
            raise ValueError("Workshop item ID 格式不正确")
        if (
            self.workshop_owner is not None
            and re.fullmatch(r"[1-9][0-9]{0,19}", self.workshop_owner) is None
        ):
            raise ValueError("Workshop owner ID 格式不正确")
        if self.workshop_helper is not None and not self.workshop_helper.is_absolute():
            raise ValueError("--workshop-helper 必须是绝对路径")
        if applying:
            if not self.channels:
                raise ValueError("执行发布必须显式选择至少一个 --channel")
            if not self.commit:
                raise ValueError("执行发布必须明确提供源提交")
            if self.publication_dir is None:
                raise ValueError("执行发布必须提供持久收据目录")
        for channel, missing in (
            ("github", ["--github-repo"] if not self.github_repo else []),
            (
                "local",
                [
                    name
                    for name, value in (
                        ("--local-root", self.local_root),
                        ("--local-previous-sha256", self.local_previous_sha256),
                    )
                    if value is None
                ],
            ),
            (
                "workshop",
                [
                    name
                    for name, value in (
                        ("--workshop-item", self.workshop_item),
                        ("--workshop-owner", self.workshop_owner),
                    )
                    if not value
                ],
            ),
        ):
            if applying and channel in self.channels and missing:
                raise ValueError(f"{channel} 身份不完整：" + ", ".join(missing))

    def receipt(self) -> dict[str, object]:
        payload: dict[str, object] = asdict(self)
        payload["publication_dir"] = (
            str(self.publication_dir.absolute()) if self.publication_dir else None
        )
        payload["local_root"] = str(self.local_root) if self.local_root else None
        payload["workshop_helper"] = str(self.workshop_helper) if self.workshop_helper else None
        payload["publication_channel"] = "stable"
        return payload

    def digest(self) -> str:
        raw = json.dumps(
            self.receipt(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(raw).hexdigest()
