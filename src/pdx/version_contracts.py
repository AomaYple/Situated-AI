"""Explicit version selection for native compatibility contracts.

The environment is read at the call boundary so pytest workers and child
processes select the same contract without rewriting historical evidence.
Selecting a version never authorizes an unverified reader or source.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from .model import Block, Scalar

if TYPE_CHECKING:
    from collections.abc import Iterator

ENVIRONMENT_VARIABLE = "V3_CONTRACT_PROFILE"
SUPPORTED_VERSIONS = frozenset({"1.14.5", "1.15.0"})
_selected: ContextVar[str | None] = ContextVar("native_contract_version", default=None)


def active_version(version: str | None = None) -> str:
    """Resolve a strict version, retaining the historical default."""
    result = version if version is not None else _selected.get()
    if result is None:
        result = os.environ.get(ENVIRONMENT_VARIABLE, "1.14.5")
    if result not in SUPPORTED_VERSIONS:
        raise ValueError(f"未支持的原版合同版本：{result!r}")
    return result


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
