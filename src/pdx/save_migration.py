"""可重复的 Victoria 3 存档版本盘点。

这个模块只读取存档头和 SHA-256，不改写存档，也不把 ``--allow-save-upgrade``
当成已经完成的迁移能力。它的输出用于在运行真实跨版本实验前确认输入满足门禁。
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import config
from .game_run import save_header

if TYPE_CHECKING:
    from pathlib import Path


def current_game_version() -> str:
    """返回当前安装的游戏分支版本，供迁移审计使用。"""

    branch = str(config.game_version().get("caligula_branch", ""))
    return branch.rsplit("/", 1)[-1]


@dataclass(frozen=True)
class SaveInventoryEntry:
    """单个存档的可审计信息。"""

    path: str
    sha256: str
    header: dict[str, str]
    parse_error: str = ""

    @property
    def version(self) -> str:
        return self.header.get("version", "")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "path": self.path,
            "sha256": self.sha256,
            "header": dict(self.header),
        }
        if self.parse_error:
            data["parse_error"] = self.parse_error
        return data


@dataclass(frozen=True)
class SaveInventory:
    """存档盘点结果及其迁移候选分组。"""

    root: str
    expected_version: str
    entries: tuple[SaveInventoryEntry, ...]

    @property
    def versions(self) -> dict[str, int]:
        return dict(sorted(Counter(e.version for e in self.entries if e.version).items()))

    @property
    def parse_errors(self) -> tuple[SaveInventoryEntry, ...]:
        return tuple(e for e in self.entries if e.parse_error)

    @property
    def cross_version_entries(self) -> tuple[SaveInventoryEntry, ...]:
        return tuple(
            e
            for e in self.entries
            if e.version and self.expected_version and e.version != self.expected_version
        )

    @property
    def observer_entries(self) -> tuple[SaveInventoryEntry, ...]:
        return tuple(e for e in self.entries if e.header.get("observer") == "yes")

    @property
    def invalid_rule_entries(self) -> tuple[SaveInventoryEntry, ...]:
        return tuple(e for e in self.entries if e.header.get("invalid_rules"))

    @property
    def legacy_state_entries(self) -> tuple[SaveInventoryEntry, ...]:
        return tuple(e for e in self.entries if e.header.get("legacy_mod_state"))

    @property
    def eligible_upgrade_entries(self) -> tuple[SaveInventoryEntry, ...]:
        """返回可提交真实升级实验的输入候选，不代表升级已经成功。"""

        return tuple(
            e
            for e in self.cross_version_entries
            if not e.parse_error
            and e.header.get("observer") == "yes"
            and not e.header.get("invalid_rules")
            and not e.header.get("legacy_mod_state")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "root": self.root,
            "expected_version": self.expected_version,
            "total": len(self.entries),
            "versions": self.versions,
            "parse_errors": len(self.parse_errors),
            "observers": len(self.observer_entries),
            "invalid_rules": len(self.invalid_rule_entries),
            "legacy_mod_state": len(self.legacy_state_entries),
            "cross_version": len(self.cross_version_entries),
            "eligible_upgrade_inputs": len(self.eligible_upgrade_entries),
            "entries": [entry.to_dict() for entry in self.entries],
        }


def scan(root: Path, *, expected_version: str | None = None) -> SaveInventory:
    """递归盘点 ``root`` 下的 ``*.v3`` 文件。

    所有路径都相对 ``root`` 且使用 POSIX 分隔符，以便报告可在三平台比较。
    解析失败的文件仍保留 SHA-256 和错误文本，避免审计时静默丢失输入。
    """

    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"存档盘点根目录不存在或不是目录：{root}")
    expected = current_game_version() if expected_version is None else expected_version
    entries: list[SaveInventoryEntry] = []
    for path in sorted(root.rglob("*.v3")):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        try:
            header = save_header(path)
            error = ""
        except (OSError, ValueError) as exc:
            header = {}
            error = f"{type(exc).__name__}: {exc}"
        entries.append(
            SaveInventoryEntry(
                path=path.relative_to(root).as_posix(),
                sha256=digest,
                header=header,
                parse_error=error,
            )
        )
    return SaveInventory(str(root), expected, tuple(entries))


def dump_json(inventory: SaveInventory, output: Path) -> None:
    """以稳定格式写出审计报告。"""

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(inventory.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


__all__ = [
    "SaveInventory",
    "SaveInventoryEntry",
    "current_game_version",
    "dump_json",
    "scan",
]
