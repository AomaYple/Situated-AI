"""Private parse ownership for one synchronous installation verification."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import version_contracts
from .parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .model import ParsedFile

_Key = tuple[str, str, str]
_Parses = dict[_Key, tuple[str, "ParsedFile"]]


@dataclass(slots=True)
class _Owner:
    thread_id: int
    parses: _Parses
    active: bool = True


_current: ContextVar[_Owner | None] = ContextVar("query_parses", default=None)


@contextmanager
def query_parse_scope() -> Iterator[None]:
    """Own fresh parses until this verification ends, including failure exits."""
    owner = _Owner(threading.get_ident(), {})
    token = _current.set(owner)
    try:
        yield
    finally:
        owner.active = False
        owner.parses.clear()
        _current.reset(token)


def parse_query_source(text: str, source: str, digest: str) -> ParsedFile:
    """Reuse only a successful exact-text parse after the caller's hash check.

    Query compilers still check every required source and its pinned hash before
    this call, and still enforce every query's complete AST predicates afterward.
    Parsed nodes stay private to those read-only compilers. A copied context on
    another thread cannot borrow this verification's mutable trees.
    """
    scope = _current.get()
    if scope is None or not scope.active or scope.thread_id != threading.get_ident():
        return parse_text(text, path=source)
    parses = scope.parses
    key = (version_contracts.active_version(), source, digest)
    previous = parses.get(key)
    if previous is not None and previous[0] == text:
        return previous[1]
    parsed = parse_text(text, path=source)
    if not parsed.errors:
        parses[key] = (text, parsed)
    return parsed
