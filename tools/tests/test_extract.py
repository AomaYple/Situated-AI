"""提取模块测试。

分两层：
* **合成测试** —— 用自造 PDX 文本验证语义，不依赖游戏安装。
* **集成测试** —— 对真实游戏目录断言已知数字，安装不存在时自动跳过。
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from pdx.extract import (
    DirExtract,
    extract_dir,
    extract_file,
    global_usage,
)
from pdx.parser import parse_text


class Sandbox:
    """在受控目录里建文件树。

    用 :mod:`tempfile` 而不是自建计数器命名 —— 后者在 pytest-xdist 的
    并行 worker 之间会撞名，详见 ``test_scan.TempTree`` 的说明。
    """

    def __init__(self, spec: dict[str, str]) -> None:
        self.spec = spec
        self.root = Path()

    def __enter__(self) -> Path:
        self.root = Path(tempfile.mkdtemp(prefix="v3-extract-"))
        for rel, content in self.spec.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return self.root

    def __exit__(self, *exc) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


class TestExtractFile(unittest.TestCase):
    def _extract(self, text: str) -> DirExtract:
        res = DirExtract(name="x", path=Path())
        extract_file(parse_text(text, "synthetic"), res)
        return res

    def test_single_entry(self):
        res = self._extract("alpha = { a = 1 }")
        self.assertEqual(res.unique_entries, 1)
        self.assertIn("alpha", res.entries)

    def test_multiple_entries(self):
        res = self._extract("a = { }\nb = { }\nc = { }")
        self.assertEqual(sorted(res.entries), ["a", "b", "c"])

    def test_fields_collected_per_entry(self):
        res = self._extract("a = { x = 1  y = 2 }\nb = { x = 3 }")
        self.assertEqual(res.fields["a"], {"x", "y"})
        self.assertEqual(res.fields["b"], {"x"})

    def test_field_usage_counts(self):
        res = self._extract("a = { x = 1 }\nb = { x = 2 }\nc = { x = 3 }")
        self.assertEqual(res.field_usage["x"], 3)

    def test_nested_fields_not_collected(self):
        """只收第一层字段 —— 子块的键属于子结构，不是该类型的字段。"""
        res = self._extract("a = { outer = { inner = 1 } }")
        self.assertEqual(res.fields["a"], {"outer"})
        self.assertNotIn("inner", res.fields["a"])

    def test_scalar_entry_has_no_fields(self):
        res = self._extract("a = 1")
        self.assertIn("a", res.entries)
        self.assertNotIn("a", res.fields)

    def test_prefixed_entry_goes_to_prefixed(self):
        res = self._extract("INJECT:foo = { a = 1 }")
        self.assertEqual(res.unique_entries, 0)
        self.assertEqual(res.prefixed["INJECT:foo"], 1)

    def test_prefixed_and_plain_mixed(self):
        res = self._extract("foo = { }\nREPLACE:bar = { }")
        self.assertEqual(list(res.entries), ["foo"])
        self.assertEqual(list(res.prefixed), ["REPLACE:bar"])

    def test_bom_file_counted(self):
        res = self._extract("\ufeffa = { }")
        self.assertEqual(res.bom_files, 1)

    def test_errors_recorded(self):
        res = self._extract("a = {\n b = 1\n")
        self.assertTrue(res.errors)

    def test_max_depth_tracked(self):
        res = self._extract("a = { b = { c = { d = 1 } } }")
        self.assertGreaterEqual(res.max_depth, 3)


class TestVariableSeparation(unittest.TestCase):
    """``@变量`` 是脚本变量，不是数据条目 —— 必须分开计数。

    这条规则来自真实错误：`coat_of_arms` 目录里有大量 ``@坐标`` 定义，
    混入 entries 会让条目数虚高。
    """

    def _extract(self, text: str) -> DirExtract:
        res = DirExtract(name="x", path=Path())
        extract_file(parse_text(text, "synthetic"), res)
        return res

    def test_variable_not_counted_as_entry(self):
        res = self._extract("@offset_x = 0.5\nreal_entry = { a = 1 }")
        self.assertEqual(list(res.entries), ["real_entry"])
        self.assertEqual(list(res.variables), ["@offset_x"])

    def test_unique_entries_excludes_variables(self):
        res = self._extract("@a = 1\n@b = 2\nentry = { }")
        self.assertEqual(res.unique_entries, 1)

    def test_variables_counted_separately(self):
        res = self._extract("@a = 1\n@b = 2\n@c = 3")
        self.assertEqual(len(res.variables), 3)
        self.assertEqual(res.unique_entries, 0)

    def test_variable_has_no_fields(self):
        """@变量 即使值是块，也不该把子键记成「字段」。"""
        res = self._extract("@v = { x = 1 }")
        self.assertNotIn("@v", res.fields)
        self.assertEqual(res.unique_entries, 0)

    def test_summary_reports_variables(self):
        res = self._extract("@a = 1\nentry = { }")
        self.assertIn("@变量", res.summary())
        self.assertEqual(res.summary()["@变量"], 1)


class TestExtractDir(unittest.TestCase):
    def test_merges_across_files(self):
        with Sandbox(
            {
                "d/one.txt": "a = { x = 1 }",
                "d/two.txt": "b = { y = 2 }",
            }
        ) as root:
            res = extract_dir(root / "d")
        self.assertEqual(sorted(res.entries), ["a", "b"])
        self.assertEqual(res.files, 2)

    def test_recurses_subdirs(self):
        with Sandbox({"d/sub/deep.txt": "z = { }"}) as root:
            res = extract_dir(root / "d")
        self.assertIn("z", res.entries)

    def test_duplicate_entry_across_files_counted(self):
        with Sandbox({"d/1.txt": "same = { }", "d/2.txt": "same = { }"}) as root:
            res = extract_dir(root / "d")
        self.assertEqual(res.unique_entries, 1)
        self.assertEqual(res.entries["same"], 2)

    def test_only_txt_parsed(self):
        with Sandbox({"d/a.txt": "a = { }", "d/b.md": "b = { }"}) as root:
            res = extract_dir(root / "d")
        self.assertEqual(list(res.entries), ["a"])

    def test_missing_dir_yields_empty(self):
        res = extract_dir(Path("Z:/nope"))
        self.assertEqual(res.files, 0)
        self.assertTrue(res.is_clean)

    def test_summary_shape(self):
        with Sandbox({"d/a.txt": "a = { x = 1 }"}) as root:
            s = extract_dir(root / "d").summary()
        for k in ("目录", "文件", "顶层条目", "字段数", "解析错误"):
            self.assertIn(k, s)

    def test_clean_flag(self):
        with Sandbox({"d/ok.txt": "a = { }"}) as root:
            self.assertTrue(extract_dir(root / "d").is_clean)
        with Sandbox({"d/bad.txt": "a = {\n"}) as root:
            self.assertFalse(extract_dir(root / "d").is_clean)


class TestGlobalUsage(unittest.TestCase):
    def test_global_usage(self):
        """跨目录汇总字段使用次数 —— 这是 ``analyze.GameAnalysis.field_usage`` 的实现。"""
        with Sandbox(
            {
                "tree/x/a.txt": "e = { shared = 1 }",
                "tree/y/b.txt": "e = { shared = 2 }",
            }
        ) as root:
            extracts = [extract_dir(root / "tree" / name) for name in ("x", "y")]
            total = global_usage(extracts)
        self.assertEqual(total["shared"], 2)


class TestRealGameCounts(unittest.TestCase):
    """集成测试：与知识库中已核实的数字对齐。

    这些数字经过多轮独立复核，其中 6128 修正了早期缩进法得出的 6121。
    """

    KNOWN = {
        "buildings": 115,
        "production_methods": 436,
        "production_method_groups": 197,
        "goods": 53,
        "company_types": 221,
        "laws": 138,
        "interest_groups": 8,
        "technology": 184,
        "character_traits": 121,
        "modifier_type_definitions": 2365,
        "static_modifiers": 6128,
        "character_templates": 2011,
    }

    common: Path

    @classmethod
    def setUpClass(cls):
        from pdx.config import GAME

        if not (GAME / "common").is_dir():
            raise unittest.SkipTest("游戏目录不可用")
        cls.common = GAME / "common"

    def test_known_entry_counts(self):
        for name, want in self.KNOWN.items():
            with self.subTest(directory=name):
                res = extract_dir(self.common / name)
                self.assertEqual(
                    res.unique_entries, want, f"{name}: 期望 {want}，实得 {res.unique_entries}"
                )

    def test_all_common_dirs_parse_without_crash(self):
        """136 个目录全部可解析，不抛异常。"""
        for child in sorted(p for p in self.common.iterdir() if p.is_dir()):
            with self.subTest(directory=child.name):
                res = extract_dir(child)
                self.assertEqual(res.files, len(list(child.rglob("*.txt"))))

    def test_bom_ratio_reported(self):
        res = extract_dir(self.common / "static_modifiers")
        self.assertEqual(res.files, 68)
        self.assertEqual(res.bom_files, 68, "实测该目录 68/68 全部带 BOM")


if __name__ == "__main__":
    unittest.main(verbosity=2)
