"""Audit-local AST reuse preserves source identities and rejection semantics."""

from __future__ import annotations

from collections import Counter

import pytest
from test_situated_native_treatments import _case

from pdx.situated import native_treatments as native


@pytest.mark.parametrize("override", [None, b"candidate={ai_will_do={always=yes}}\n"])
def test_identical_native_and_effective_bytes_are_parsed_once(monkeypatch, override):
    inventory, sources, source = _case("company_types", "ai_will_do", "ai_will_do={always=yes}")
    if override is not None:
        # Formatting changes require a separate parse even when the AST agrees.
        generated = {source: override}
    else:
        generated = {}
    calls = []
    original = native.parse_bytes

    def parse(raw, *, path):
        calls.append((path, raw))
        return original(raw, path=path)

    monkeypatch.setattr(native, "parse_bytes", parse)
    first = native.native_treatments(inventory, sources, generated, production_complete=True)
    assert first["rows"][0]["source_protection"]["proven"] is True
    expected = 1 if override is None else 2
    assert Counter(path for path, _ in calls) == {source: expected}
    calls.clear()
    second = native.native_treatments(inventory, sources, generated, production_complete=True)
    assert first == second
    # No cache survives the invocation or bypasses fresh supplied bytes.
    assert Counter(path for path, _ in calls) == {source: expected}


@pytest.mark.parametrize("broken", [b"candidate={", b"\xff"])
def test_reuse_preserves_parse_failures_and_does_not_reuse_changed_bytes(broken, monkeypatch):
    source = "common/company_types/fixture.txt"
    if broken == b"\xff":
        original = native.parse_bytes

        def decode_failure(raw, *, path):
            if raw == broken:
                raise UnicodeDecodeError("utf-8", raw, 0, 1, "injected decoder failure")
            return original(raw, path=path)

        monkeypatch.setattr(native, "parse_bytes", decode_failure)
    supplied = {source: broken}
    before = native._Sources(supplied)
    same = native._Sources(supplied, reuse=before)
    assert same.failures == before.failures == {source}
    assert not same.roots
    supplied[source] = b"candidate={ai_will_do={always=yes}}"
    changed = native._Sources(supplied, reuse=before)
    assert changed.failures == set()
    assert set(changed.roots) == {source}
    assert before.failures == {source}


def test_reuse_preserves_owner_order_duplicates_and_changed_ast():
    first = "common/company_types/first.txt"
    second = "common/company_types/second.txt"
    raw = b"candidate={ai_weight=1}\ncandidate={ai_weight=2}\n"
    sources = {first: raw}
    before = native._Sources(sources)
    before_hash = native._digest(before.roots[first])
    effective = {second: raw, first: raw, "common/company_types/broken.txt": b"x={"}
    actual = native._Sources(effective, reuse=before)
    independent = native._Sources(effective)
    assert actual.roots[first] is before.roots[first]
    assert actual.roots[second] is not before.roots[first]
    assert dict(actual.owners) == dict(independent.owners)
    assert actual.owners["company_types", "candidate"] == [second, second, first, first]
    assert actual.failures == independent.failures
    assert {path: native._digest(root) for path, root in actual.roots.items()} == {
        path: native._digest(root) for path, root in independent.roots.items()
    }
    changed = native._Sources({first: raw.replace(b"=2", b"=3")}, reuse=before)
    assert changed.roots[first] is not before.roots[first]
    assert native._digest(changed.roots[first]) != before_hash
    assert native._digest(before.roots[first]) == before_hash
