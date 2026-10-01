"""词法分析器测试。

覆盖：注释剥离、引号处理、运算符识别、标识符字符集、行号追踪、
畸形输入不死循环。
"""

from __future__ import annotations

import unittest

from pdx.lexer import (
    ATOM,
    EOF,
    LBRACE,
    OP,
    RBRACE,
    STRING,
    tokenize,
)


def kinds(text: str) -> list[str]:
    return [t.kind for t in tokenize(text) if t.kind != EOF]


def values(text: str) -> list[str]:
    return [t.value for t in tokenize(text) if t.kind != EOF]


class TestBraces(unittest.TestCase):
    def test_single_block(self):
        self.assertEqual(kinds("a = { }"), [ATOM, OP, LBRACE, RBRACE])
        self.assertEqual(values("a = { }"), ["a", "=", "{", "}"])

    def test_nested_blocks(self):
        self.assertEqual(kinds("{{}}"), [LBRACE, LBRACE, RBRACE, RBRACE])

    def test_adjacent_braces_no_whitespace(self):
        self.assertEqual(values("a={b=1}"), ["a", "=", "{", "b", "=", "1", "}"])


class TestOperators(unittest.TestCase):
    def test_all_operators(self):
        for op in ("=", "?=", "==", "!=", ">", "<", ">=", "<="):
            with self.subTest(op=op):
                toks = tokenize(f"a {op} 1")
                self.assertEqual(toks[1].kind, OP)
                self.assertEqual(toks[1].value, op)

    def test_safe_assignment_not_split(self):
        """?= 必须是一个 token，不能被切成 ? 和 =。"""
        self.assertEqual(values("c:SWE ?= { }"), ["c:SWE", "?=", "{", "}"])

    def test_operators_not_greedy_across_space(self):
        self.assertEqual(values("a = = b"), ["a", "=", "=", "b"])


class TestComments(unittest.TestCase):
    def test_line_comment_removed(self):
        self.assertEqual(values("a = 1 # b = 2"), ["a", "=", "1"])

    def test_comment_only_line(self):
        self.assertEqual(kinds("# just a comment"), [])

    def test_hash_in_string_kept(self):
        toks = [t for t in tokenize('a = "x # y"') if t.kind == STRING]
        self.assertEqual(len(toks), 1)
        self.assertEqual(toks[0].value, '"x # y"')

    def test_comment_with_braces_does_not_emit_braces(self):
        self.assertEqual(kinds("a = 1 # { { } }"), [ATOM, OP, ATOM])

    def test_multiple_comments(self):
        self.assertEqual(values("# a\nb = 1 # c\n# d"), ["b", "=", "1"])


class TestStrings(unittest.TestCase):
    def test_simple_string(self):
        t = next(x for x in tokenize('s = "hello"') if x.kind == STRING)
        self.assertEqual(t.value, '"hello"')

    def test_string_with_spaces(self):
        t = next(x for x in tokenize('s = "a b c"') if x.kind == STRING)
        self.assertEqual(t.value, '"a b c"')

    def test_string_with_braces(self):
        t = next(x for x in tokenize('s = "{ }"') if x.kind == STRING)
        self.assertEqual(t.value, '"{ }"')

    def test_string_with_equals(self):
        t = next(x for x in tokenize('s = "a=b"') if x.kind == STRING)
        self.assertEqual(t.value, '"a=b"')

    def test_escaped_quote(self):
        t = next(x for x in tokenize(r's = "a\"b"') if x.kind == STRING)
        self.assertEqual(t.value, r'"a\"b"')

    def test_unterminated_string_does_not_hang(self):
        toks = tokenize('s = "unclosed')
        self.assertTrue(any(t.kind == STRING for t in toks))


class TestAtoms(unittest.TestCase):
    def test_hyphen_in_atom(self):
        self.assertEqual(values("pm_a-b = 1"), ["pm_a-b", "=", "1"])

    def test_colon_in_atom(self):
        self.assertEqual(values("c:SWE = 1"), ["c:SWE", "=", "1"])

    def test_dots_in_atom(self):
        self.assertEqual(values("a.b.c = 1"), ["a.b.c", "=", "1"])

    def test_numbers(self):
        self.assertEqual(values("a = -1.5"), ["a", "=", "-1.5"])

    def test_at_variable(self):
        self.assertEqual(values("@var = 1"), ["@var", "=", "1"])

    def test_dollar_parameter(self):
        self.assertEqual(values("$PARAM$ = 1"), ["$PARAM$", "=", "1"])


class TestBOM(unittest.TestCase):
    def test_bom_is_skipped(self):
        self.assertEqual(values("\ufeffa = 1"), ["a", "=", "1"])

    def test_bom_not_part_of_atom(self):
        t = next(x for x in tokenize("\ufeffabc = 1") if x.kind == ATOM)
        self.assertEqual(t.value, "abc")


class TestLineTracking(unittest.TestCase):
    def _idents(self, text: str) -> list[str]:
        """只取标识符类原子（字母开头），排除数字与符号。"""
        return [t.value for t in tokenize(text) if t.kind == ATOM and t.value[:1].isalpha()]

    def _lines(self, text: str) -> list[int]:
        return [t.line for t in tokenize(text) if t.kind == ATOM and t.value[:1].isalpha()]

    def test_line_numbers(self):
        self.assertEqual(self._lines("a = 1\nb = 2\nc = 3"), [1, 2, 3])

    def test_blank_lines_counted(self):
        self.assertEqual(self._lines("a\n\n\nb"), [1, 4])

    def test_line_number_after_multiline_block(self):
        text = "a = {\n  b = 1\n  c = 2\n}\nd = 3"
        self.assertEqual(self._lines(text), [1, 2, 3, 5])

    def test_line_start_resets_after_newline(self):
        toks = tokenize("aaa = 1\nb = 2")
        b = next(t for t in toks if t.value == "b")
        self.assertEqual(b.col, 1)

    def test_col_tracks_position(self):
        toks = tokenize("abc = 1")
        by_val = {t.value: t for t in toks}
        self.assertEqual(by_val["abc"].col, 1)
        self.assertEqual(by_val["="].col, 5)
        self.assertEqual(by_val["1"].col, 7)


class TestRobustness(unittest.TestCase):
    def test_empty_input(self):
        self.assertEqual([t.kind for t in tokenize("")], [EOF])

    def test_only_whitespace(self):
        self.assertEqual([t.kind for t in tokenize("   \n\t\r\n")], [EOF])

    def test_stray_operator_produces_token(self):
        self.assertTrue(any(t.kind == OP for t in tokenize("==")))

    def test_no_infinite_loop_on_odd_input(self):
        for text in ("?", "!", "???", "@", "$", "\\", "`", "\x00"):
            with self.subTest(text=text):
                toks = tokenize(text)
                self.assertEqual(toks[-1].kind, EOF)

    def test_crlf_handled(self):
        self.assertEqual(values("a = 1\r\nb = 2"), ["a", "=", "1", "b", "=", "2"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
