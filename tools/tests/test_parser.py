"""PDX 解析器单元测试。

每个测试用例都对应一个**实际踩过的坑**，不是凭空构造的。
运行：

    .venv\\Scripts\\python.exe -m unittest discover -s tools/tests -v
"""

from __future__ import annotations

import unittest

from _helpers import block_of, first_assignment, scalar_of

from pdx import parse_text
from pdx.parser import PREFIXES


class TestBOM(unittest.TestCase):
    """坑 1：common/ 下 3024 个 .txt 有 3000 个带 BOM。"""

    def test_bom_stripped_from_first_key(self):
        pf = parse_text("\ufeffalpha = { x = 1 }")
        self.assertEqual(pf.top_keys, ["alpha"])
        self.assertTrue(pf.had_bom)

    def test_bom_flag_false_when_absent(self):
        pf = parse_text("alpha = { x = 1 }")
        self.assertFalse(pf.had_bom)

    def test_bom_does_not_leak_into_key(self):
        pf = parse_text("\ufefffoo = { }")
        self.assertNotIn("\ufeff", pf.top_keys[0])


class TestComments(unittest.TestCase):
    """坑 2：注释必须引号感知，且必须在括号计数之前剥离。"""

    def test_comment_ignored(self):
        pf = parse_text("a = 1 # b = 2\n")
        self.assertEqual(pf.top_keys, ["a"])

    def test_hash_inside_string_is_not_comment(self):
        pf = parse_text('a = "value # not a comment"\n')
        self.assertEqual(pf.top_keys, ["a"])
        self.assertEqual(scalar_of(first_assignment(pf)).unquoted, "value # not a comment")

    def test_braces_inside_commented_block_do_not_drift_depth(self):
        """官方 00_flag_definitions.txt 有 21 行注释内含花括号。"""
        text = """
# commented_out = { {
#   nested = { }
# }
real_key = { a = 1 }
"""
        pf = parse_text(text)
        self.assertEqual(pf.top_keys, ["real_key"])
        self.assertEqual(pf.errors, [])


class TestKeys(unittest.TestCase):
    """坑 3：键名字符集不能枚举 —— 存在含连字符的键。"""

    def test_hyphenated_key(self):
        pf = parse_text("pm_ammonia-soda_process = { }\n")
        self.assertEqual(pf.top_keys, ["pm_ammonia-soda_process"])

    def test_dotted_key(self):
        pf = parse_text("modifier.foo = 1\n")
        self.assertEqual(pf.top_keys, ["modifier.foo"])

    def test_scoped_reference_is_not_a_prefix(self):
        """c:SWE 是作用域引用，不是功能前缀。"""
        pf = parse_text("c:SWE ?= { a = 1 }\n")
        a = pf.top_assignments[0]
        self.assertIsNone(a.prefix)
        self.assertEqual(a.key, "c:SWE")
        self.assertEqual(a.op, "?=")


class TestPrefixes(unittest.TestCase):
    """坑 4：6 个引擎级功能前缀。"""

    def test_all_prefixes_recognized(self):
        for p in PREFIXES:
            with self.subTest(prefix=p):
                pf = parse_text(f"{p}:foo = {{ bar = 1 }}\n")
                a = pf.top_assignments[0]
                self.assertEqual(a.prefix, p)
                self.assertEqual(a.key, "foo")
                self.assertEqual(a.full_key, f"{p}:foo")

    def test_prefix_list_is_exactly_six(self):
        self.assertEqual(len(PREFIXES), 6)


class TestTopLevelDetection(unittest.TestCase):
    """坑 5：顶层判定必须用花括号深度，不能用缩进。"""

    def test_indented_top_level_key_is_found(self):
        """02_event_modifiers.txt 有 ' modifier_x = {' 这种带前导空格的顶层键。"""
        pf = parse_text(" modifier_indented = {\n\ticon = x\n}\n")
        self.assertEqual(pf.top_keys, ["modifier_indented"])

    def test_nested_keys_are_not_top_level(self):
        pf = parse_text("outer = {\n\tinner = { deep = 1 }\n}\n")
        self.assertEqual(pf.top_keys, ["outer"])

    def test_equals_and_brace_on_separate_lines(self):
        """00_shaders.txt 用 'NShadersCommon =' 换行 '{' 的写法。"""
        pf = parse_text("NShadersCommon =\n{\n\ta = 1\n}\n")
        self.assertEqual(pf.top_keys, ["NShadersCommon"])
        self.assertTrue(pf.top_assignments[0].is_block)

    def test_mixed_tabs_and_spaces(self):
        pf = parse_text("a = {\n    b = 1\n\tc = 2\n}\n")
        self.assertEqual(pf.top_keys, ["a"])
        self.assertEqual(sorted(block_of(first_assignment(pf)).keys()), ["b", "c"])


class TestValues(unittest.TestCase):
    def test_inline_list_of_scalars(self):
        pf = parse_text("traits = { a b c }\n")
        blk = block_of(first_assignment(pf))
        self.assertEqual([s.text for s in blk.scalars()], ["a", "b", "c"])

    def test_quoted_string_preserved(self):
        pf = parse_text('icon = "gfx/interface/icons/a.dds"\n')
        v = scalar_of(first_assignment(pf))
        self.assertTrue(v.quoted)
        self.assertEqual(v.unquoted, "gfx/interface/icons/a.dds")

    def test_empty_block(self):
        pf = parse_text("a = { }\n")
        self.assertEqual(len(block_of(first_assignment(pf))), 0)

    def test_empty_value(self):
        """``key =`` 后面直接闭合块 —— 值确实为空，可判定。

        注意：``a =`` 换行后紧跟 ``b = 1`` 属于**歧义输入**（b 是 a 的值
        还是下一条语句？），PDX 无法判定，真实文件也不这么写，
        因此不为此行为设断言。见 parser.py 的「已知限制」。
        """
        pf = parse_text("block = {\n  a =\n}\n")
        inner = block_of(first_assignment(pf))
        inner_a = inner.first("a")
        assert inner_a is not None
        self.assertIsNone(inner_a.value)


class TestRobustness(unittest.TestCase):
    """不追求全对全错：畸形输入要尽量保留可用数据。"""

    def test_unbalanced_brace_reports_error_without_crashing(self):
        pf = parse_text("a = {\n b = 1\n")
        self.assertTrue(pf.errors)
        self.assertIn("a", pf.top_keys)

    def test_stray_closing_brace_does_not_loop(self):
        pf = parse_text("}\na = 1\n")
        self.assertEqual(pf.top_keys, ["a"])

    def test_empty_file(self):
        pf = parse_text("")
        self.assertEqual(pf.top_keys, [])

    def test_only_comments(self):
        pf = parse_text("# nothing\n# here\n")
        self.assertEqual(pf.top_keys, [])


class TestKnownCounts(unittest.TestCase):
    """集成测试：用已知正确的数字验证整条解析管线。

    这些数字是本次会话中反复核对确定的，其中 6128 修正了早期
    缩进法得出的错误值 6121。
    """

    EXPECTED = {
        "static_modifiers": 6128,
        "modifier_type_definitions": 2364,
        "production_methods": 436,
        "character_templates": 2011,
        "buildings": 115,
        "laws": 138,
    }

    def test_directory_key_counts(self):
        from pdx.config import GAME

        common = GAME / "common"
        if not common.is_dir():
            self.skipTest("游戏目录不可用")

        from pdx import parse_file

        for name, want in self.EXPECTED.items():
            with self.subTest(directory=name):
                keys: set[str] = set()
                for f in (common / name).rglob("*.txt"):
                    keys.update(parse_file(f).top_keys)
                self.assertEqual(len(keys), want, f"{name} 键数不符")


if __name__ == "__main__":
    unittest.main(verbosity=2)
