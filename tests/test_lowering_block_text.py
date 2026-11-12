"""Block extraction keeps exact legacy boundaries without copying the suffix."""

import pytest

from pdx.situated import lowering


@pytest.mark.parametrize(
    ("lines", "start", "expected"),
    [
        (["# first", "if = { add = 1 }", "# second", "if = { add = 2 }"], 1, "if = { add = 1 }"),
        (["# first", "if = { add = 1 }", "# second", "if = { add = 2 }"], 3, "if = { add = 2 }"),
        (
            ["# comment", "", "if = {", " add = 1", "}", "tail"],
            0,
            "# comment\n\nif = {\n add = 1\n}",
        ),
        (["if = {", " add = 1", "tail"], 0, "if = {\n add = 1\ntail"),
        (["# no braces", "tail"], 0, "# no braces\ntail"),
        (["# }", "if = {", "tail"], 0, "# }\nif = {"),
        (["if = {} # {", "}", "tail"], 0, "if = {} # {\n}"),
        (["if = {}", "not = { closed = no }"], 0, "if = {}"),
        (["a", "if = {}", "tail"], -2, "if = {}"),
        (["a", "if = {}"], -99, "a\nif = {}"),
        (["if = {}"], 1, ""),
        (["if = {}"], 99, ""),
        ([], 0, ""),
    ],
)
def test_block_text_exact_legacy_scan_boundaries(lines, start, expected):
    assert lowering._block_text(lines, start) == expected


def test_early_closed_block_does_not_slice_or_scan_remaining_lines():
    class Lines(list):
        def __getitem__(self, index):
            assert not isinstance(index, slice), "Do not copy the file tail"
            assert index < 2, "Do not scan beyond the first closed block"
            return super().__getitem__(index)

    assert lowering._block_text(Lines(["# marker", "if = {}", "unvisited"]), 1) == "if = {}"


def test_invalid_start_retains_slice_type_error():
    with pytest.raises(TypeError):
        # Deliberately pass an invalid index to retain the original slice error.
        lowering._block_text(["if = {}"], 0.5)  # type: ignore[arg-type]
