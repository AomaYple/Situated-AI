"""Explicit version selection for native compatibility contracts.

The environment is read at the call boundary so pytest workers and child
processes select the same contract without rewriting historical evidence.
Selecting a version never authorizes an unverified reader or source.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .model import Block, Scalar

if TYPE_CHECKING:
    from collections.abc import Iterator

ENVIRONMENT_VARIABLE = "V3_CONTRACT_PROFILE"
CURRENT_VERSION = "1.15.1"


@dataclass(frozen=True, slots=True)
class VersionContract:
    """One explicitly reviewed native identity and its evidence locations."""

    version: str
    uses_115_native: bool
    docs_subdir: str
    official_manifest_name: str
    snapshot_label: str
    # Original installed bytes (including BOM/newlines), distinct from the normalized baseline.
    default_strategy_sha256: str
    baseline_strategy_sha256: str


VERSION_SPECS = {
    "1.14.5": VersionContract(
        "1.14.5",
        False,
        "victoria3-modding",
        "official-docs.manifest.json",
        "release-1.14.5",
        "fd4b531d39bcd85c3491c703ecb08ea739094f795b13a176765cf559ece3fbee",
        "a817c27fdd1aee4929680338abc07ac8fefd168b24a7617eacf459d923851be2",
    ),
    "1.15.0": VersionContract(
        "1.15.0",
        True,
        "victoria3-modding-1.15.0",
        "official-docs-1.15.0.manifest.json",
        "release-1.15.0",
        "83a9e8b7b568967ea9ae10df63ee18ed9b069ff69a5a31a23d35cc129b89ce73",
        "6d0b4569b3f3b35f2ca1aab51ff71f2417b41e51c01379ee340394dee1f5f431",
    ),
    "1.15.1": VersionContract(
        "1.15.1",
        True,
        "victoria3-modding-1.15.1",
        "official-docs-1.15.1.manifest.json",
        "release-1.15.1",
        "38e7aadd1be9465f3ab423f61fa8e9e8206b8d98f523979e8e43c42cc18753ba",
        "e0e2cc9762f2d1e07deeb45091ca2e317e3771038851b840232d5f80538210c0",
    ),
}
SUPPORTED_VERSIONS = frozenset(VERSION_SPECS)
_selected: ContextVar[str | None] = ContextVar("native_contract_version", default=None)


def active_version(version: str | None = None) -> str:
    """Resolve one supported exact identity, defaulting to the current release."""
    result = version if version is not None else _selected.get()
    if result is None:
        result = os.environ.get(ENVIRONMENT_VARIABLE, CURRENT_VERSION)
    if result not in SUPPORTED_VERSIONS:
        raise ValueError(f"未支持的原版合同版本：{result!r}")
    return result


def contract(version: str | None = None) -> VersionContract:
    """Return the explicit specification; unknown future versions hard fail."""
    return VERSION_SPECS[active_version(version)]


def is_115(version: str | None = None) -> bool:
    """Select reviewed 1.15 syntax without authorizing an unreviewed release."""
    return contract(version).uses_115_native


def research_path(category: str, filename: str, version: str | None = None) -> Path:
    """Resolve a versioned evidence path, never reuse another release's identity."""
    if category not in {"situated", "vanilla-ai"}:
        raise ValueError(f"不支持的版本证据类别：{category!r}")
    relative = Path(filename)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"版本证据路径越界：{filename!r}")
    return (
        Path(__file__).resolve().parents[2]
        / "research"
        / category
        / active_version(version)
        / relative
    )


@contextmanager
def select_version(version: str) -> Iterator[None]:
    """Select one contract for a bounded operation, restoring it on failure."""
    token = _selected.set(active_version(version))
    try:
        yield
    finally:
        _selected.reset(token)


def journal_completion(journal: Block, *, effect: bool = False) -> Block:
    """Locate the exact 1.15 completion outcome, never the first outcome.

    1.15 moved journal completion predicates/effects into repeated outcome
    blocks. Header and effect-header jointly identify the completion role;
    duplicate, conditional and prefixed structures cannot supply evidence.
    """
    matches: list[Block] = []
    for entry in journal.all("outcome"):
        if entry.op != "=" or entry.prefix is not None or not isinstance(entry.value, Block):
            raise ValueError("原版查询证据缺少唯一普通outcome块")
        headers = entry.value.all("header")
        if not headers:
            continue
        if (
            len(headers) != 1
            or headers[0].op != "="
            or headers[0].prefix is not None
            or not isinstance(headers[0].value, Scalar)
        ):
            raise ValueError("原版查询outcome缺少唯一普通header")
        if headers[0].value.unquoted != "je_standard_completion_header":
            continue
        effect_headers = entry.value.all("effect_header")
        if (
            len(effect_headers) != 1
            or effect_headers[0].op != "="
            or effect_headers[0].prefix is not None
            or not isinstance(effect_headers[0].value, Scalar)
            or effect_headers[0].value.unquoted != "je_standard_on_completion_header"
        ):
            raise ValueError("原版查询outcome完成角色不一致")
        matches.append(entry.value)
    if len(matches) != 1:
        raise ValueError("原版查询证据缺少唯一完成outcome块")
    fields = matches[0].all("effect" if effect else "trigger")
    if (
        len(fields) != 1
        or fields[0].op != "="
        or fields[0].prefix is not None
        or not isinstance(fields[0].value, Block)
    ):
        raise ValueError("原版查询outcome缺少唯一普通完成字段")
    return fields[0].value
