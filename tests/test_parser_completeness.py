"""语法完整性与旧版容错树使用同一个解析器。"""

import pytest

from pdx.model import ParseError
from pdx.parser import parse_bytes, parse_text


@pytest.mark.parametrize(
    ("text", "kind", "position", "rejected", "token_count"),
    [
        ("}\nkept = 1", "unexpected_closing_brace", (1, 1), [("RBRACE", "}", 1, 1)], 4),
        ("= 2\nkept = 1", "missing_assignment_key", (1, 1), [("OP", "=", 1, 1)], 5),
        ("root = { missing = }", "missing_assignment_value", (1, 18), [], 6),
        ("root = { kept = 1", "unclosed_block", (1, 8), [], 6),
        ('kept = "escaped\\"', "unclosed_string", (1, 8), [], 3),
        ('kept = "', "unclosed_string", (1, 8), [], 3),
    ],
)
def test_partial_parse_retains_positions_and_token_accounting(
    text: str,
    kind: str,
    position: tuple[int, int],
    rejected: list[tuple[str, str, int, int]],
    token_count: int,
) -> None:
    parsed = parse_text(text, path="example.txt")

    assert parsed.parse_status == "partial"
    assert parsed.diagnostics == [{"kind": kind, "line": position[0], "column": position[1]}]
    assert parsed.unconsumed_tokens == rejected
    assert parsed.token_count == token_count
    assert parsed.consumed_token_count == token_count - len(rejected)
    assert parsed.top_keys == (["root"] if text.startswith("root") else ["kept"])
    with pytest.raises(ParseError, match=kind) as raised:
        parsed.require_complete()
    assert raised.value.path == "example.txt"
    assert raised.value.line == position[0]


def test_complete_parse_preserves_repeated_keys_and_multiline_string() -> None:
    parsed = parse_text('key = "first\n"\nkey = { a b }')

    assert parsed.parse_status == "complete"
    assert parsed.top_keys == ["key", "key"]
    assert [item.line for item in parsed.top_assignments] == [1, 3]
    assert parsed.consumed_token_count == parsed.token_count == 9
    parsed.require_complete()


def test_invalid_utf8_legacy_ast_cannot_satisfy_completeness_gate() -> None:
    parsed = parse_bytes(b'kept=1\nother="\xa9"', "invalid.txt")

    assert parsed.parse_status == "failed"
    assert parsed.top_keys == ["kept", "other"]
    assert parsed.errors == []
    with pytest.raises(ParseError, match="UnicodeDecodeError"):
        parsed.require_complete()


def test_declared_encoding_decodes_strictly() -> None:
    raw = b'value="\xa9"'
    invalid = parse_bytes(raw, "example.txt", encoding="utf-8")
    parsed = parse_bytes(raw, "example.txt", encoding="cp1252")

    assert invalid.parse_status == "failed"
    assert invalid.root.items == []
    assert invalid.token_count == 0
    assert parsed.parse_status == "complete"
    assert parsed.encoding == "cp1252"
    value = parsed.top_assignments[0].value
    assert getattr(value, "text", None) == '"©"'
