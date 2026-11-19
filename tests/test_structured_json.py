"""Structured JSON research preserves all nodes without granting identity authority."""

import importlib
import json
from copy import deepcopy
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    import types
    from collections.abc import Callable


def api() -> types.ModuleType:
    from pdx import structured_json

    return structured_json


def test_reader_preserves_duplicate_members_and_every_node() -> None:
    assert importlib.util.find_spec("pdx.structured_json") is not None
    result = api().parse_json(b'{"a":1,"\\u0061":2,"A":[],"nested":{"x":true,"x":null}}')
    assert result.parse_status == "complete"
    document = result.document
    assert document is not None
    assert [(n.key, n.kind, n.scalar) for n in document.children(())] == [
        ("a", "number", "1"),
        ("a", "number", "2"),
        ("A", "array", None),
        ("nested", "object", None),
    ]
    assert [n.address for n in document.members((), "a")] == [(0,), (1,)]
    assert document.node((3, 1)).kind == "null"
    assert document.parent((3, 1)).address == (3,)
    assert len(document.nodes) == 7
    assert any("duplicate" in d for d in result.diagnostics)
    assert all(n.line is None for n in document.nodes)
    assert api().load_payload(document.to_payload()) == document


def test_number_lexemes_unicode_and_encoding_boundary() -> None:
    result = api().parse_json(b'\xef\xbb\xbf\r\n[9007199254740993,-0,1.00,1e400,true,"\\ud800"]')
    assert result.had_bom is True
    assert result.root_line == 2
    assert [n.scalar for n in result.document.children(())] == [
        "9007199254740993",
        "-0",
        "1.00",
        "1e400",
        "true",
        "\ud800",
    ]
    payload = result.document.to_payload()
    payload.encode("ascii")
    assert api().load_payload(payload).node((5,)).scalar == "\ud800"
    assert any("surrogate" in d for d in result.diagnostics)
    long_number = b"1" * 5000
    assert api().parse_json(long_number).document.node(()).scalar == long_number.decode()


@pytest.mark.parametrize(
    "raw", [b"{", b"{} []", b"[NaN]", b"[Infinity]", b"[1,]", b'"\\x"', b'"a\nb"']
)
def test_invalid_syntax_remains_failed(raw: bytes) -> None:
    result = api().parse_json(raw)
    assert result.decode_status == "complete"
    assert result.parse_status == "failed"
    assert result.document is None
    assert result.diagnostics


@pytest.mark.parametrize("raw", [b"\xff", "{}".encode("utf-16"), "{}".encode("utf-32")])
def test_invalid_encoding_is_not_unsupported(raw: bytes) -> None:
    result = api().parse_json(raw)
    assert result.decode_status == "failed"
    assert result.parse_status == "failed"
    assert result.document is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(schema=True),
        lambda p: p["nodes"][1].update(address=[True]),
        lambda p: p["nodes"][1].update(parent=[0]),
        lambda p: p["nodes"][0].update(child_count=True),
        lambda p: p["nodes"][1].update(kind="number", scalar="NaN"),
        lambda p: p["nodes"][1].update(extra="hidden"),
        lambda p: p["nodes"].pop(),
    ],
)
def test_payload_rejects_omissions_wrong_types_and_parent_forgery(
    mutate: Callable[[dict[str, Any]], object],
) -> None:
    original = json.loads(api().parse_json(b'{"a":1,"b":2}').document.to_payload())
    value = deepcopy(original)
    mutate(value)
    with pytest.raises(ValueError):
        api().load_payload(json.dumps(value))


@pytest.mark.parametrize(("raw", "offset"), [(b"\xef\xbb\xbf\xff", 3), (b"\xef\xbb\xbf[\xff]", 4)])
def test_bom_decode_errors_report_raw_byte_offsets(raw: bytes, offset: int) -> None:
    result = api().parse_json(raw)
    assert result.decode_status == "failed"
    assert result.parse_status == "failed"
    assert result.diagnostics[0].startswith(f"utf8_decode_failed:bytes={offset}:{offset + 1}:")


@pytest.mark.parametrize(("raw", "offset"), [(b"\xff", 0), (b"[\xff]", 1)])
def test_plain_decode_errors_keep_raw_byte_offsets(raw: bytes, offset: int) -> None:
    assert (
        api()
        .parse_json(raw)
        .diagnostics[0]
        .startswith(f"utf8_decode_failed:bytes={offset}:{offset + 1}:")
    )


def test_single_bom_accepted_and_repeated_bom_rejected() -> None:
    assert api().parse_json(b"\xef\xbb\xbf{}").parse_status == "complete"
    result = api().parse_json(b"\xef\xbb\xbf\xef\xbb\xbf{}")
    assert result.decode_status == "complete"
    assert result.parse_status == "failed"
