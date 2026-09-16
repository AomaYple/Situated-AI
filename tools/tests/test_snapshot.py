"""快照机制测试。

核心保证有两条，任何一条破了 diff 就失去意义：

1. **确定性** —— 同一环境重复构建的快照必须完全相同
2. **完备性** —— 覆盖全部 mod 相关域，且不遗漏重复块中的参数
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdx import config, snapshot  # noqa: E402


class TestSnapshotShape(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (config.GAME / "common").is_dir():
            raise unittest.SkipTest("游戏目录不可用")
        cls.snap = snapshot.build()

    def test_has_all_sections(self):
        for sec in (
            "common_entries", "fields", "defines", "localization", "dlc", "config"
        ):
            with self.subTest(section=sec):
                self.assertIn(sec, self.snap.sections)

    def test_version_recorded(self):
        self.assertTrue(self.snap.version.get("caligula_branch"))
        self.assertTrue(self.snap.version.get("caligula_rev"))

    def test_common_entries_covers_136_dirs(self):
        """必须覆盖全部 136 个数据目录 —— 曾经因路径口径错误变成 0。"""
        self.assertEqual(len(self.snap.sections["common_entries"]), 136)

    def test_common_entries_not_empty(self):
        total = sum(len(v) for v in self.snap.sections["common_entries"].values())
        self.assertGreater(total, 20000, "条目总数异常偏低")

    def test_fields_not_empty(self):
        self.assertGreater(len(self.snap.sections["fields"]), 10000)

    def test_defines_merges_repeated_namespaces(self):
        """NGUI 在 24 个块里出现，必须合并成一个键而非坍缩。
        实测唯一命名空间 50（game）+ 17（jomini）= 67。
        """
        self.assertEqual(len(self.snap.sections["defines"]), 67)

    def test_localization_has_11_languages(self):
        self.assertEqual(len(self.snap.sections["localization"]), 11)

    def test_dlc_count_is_17(self):
        self.assertEqual(len(self.snap.sections["dlc"]), 17)


class TestDeterminism(unittest.TestCase):
    """确定性是 diff 可用的前提。"""

    @classmethod
    def setUpClass(cls):
        if not (config.GAME / "common").is_dir():
            raise unittest.SkipTest("游戏目录不可用")

    def test_two_builds_identical(self):
        a = snapshot.build()
        b = snapshot.build()
        da = json.dumps(a.to_dict(), ensure_ascii=False, sort_keys=True)
        db = json.dumps(b.to_dict(), ensure_ascii=False, sort_keys=True)
        self.assertEqual(da, db)

    def test_lists_are_sorted(self):
        s = snapshot.build()
        for sec, body in s.sections.items():
            for name, names in list(body.items())[:50]:
                with self.subTest(section=sec, name=name):
                    self.assertEqual(names, sorted(names), "列表未排序")
                    self.assertEqual(len(names), len(set(names)), "列表有重复")

    def test_serialization_roundtrip(self):
        s = snapshot.build()
        d = s.to_dict()
        text = json.dumps(d, ensure_ascii=False, sort_keys=True)
        back = json.loads(text)
        self.assertEqual(back["格式版本"], snapshot.FORMAT)
        self.assertEqual(back["版本"], s.version)


class TestCompare(unittest.TestCase):
    """比对逻辑本身。"""

    def _snap(self, sections):
        return snapshot.Snapshot(version={"caligula_branch": "t"}, sections=sections)

    def test_identical_yields_no_changes(self):
        s = self._snap({"x": {"a": ["1", "2"]}})
        self.assertEqual(snapshot.compare(s, s), [])

    def test_detects_addition(self):
        a = self._snap({"x": {"a": ["1"]}})
        b = self._snap({"x": {"a": ["1", "2"]}})
        ch = snapshot.compare(a, b)
        self.assertEqual(len(ch), 1)
        self.assertEqual(ch[0].added, ["2"])
        self.assertEqual(ch[0].removed, [])

    def test_detects_removal(self):
        a = self._snap({"x": {"a": ["1", "2"]}})
        b = self._snap({"x": {"a": ["1"]}})
        ch = snapshot.compare(a, b)
        self.assertEqual(ch[0].removed, ["2"])

    def test_detects_new_group(self):
        a = self._snap({"x": {}})
        b = self._snap({"x": {"new": ["k"]}})
        ch = snapshot.compare(a, b)
        self.assertEqual(len(ch), 1)
        self.assertEqual(ch[0].name, "new")
        self.assertEqual(ch[0].added, ["k"])

    def test_detects_new_section(self):
        a = self._snap({"x": {}})
        b = self._snap({"x": {}, "y": {"n": ["k"]}})
        self.assertEqual(len(snapshot.compare(a, b)), 1)

    def test_summary_counts(self):
        a = self._snap({"x": {"a": ["1"]}})
        b = self._snap({"x": {"a": ["2", "3"]}})
        s = snapshot.diff_summary(snapshot.compare(a, b))
        self.assertEqual(s["变更项数"], 1)
        self.assertEqual(s["新增条目"], 2)
        self.assertEqual(s["删除条目"], 1)

    def test_change_line_format(self):
        a = self._snap({"x": {"a": ["1"]}})
        b = self._snap({"x": {"a": ["1", "2", "3"]}})
        line = snapshot.compare(a, b)[0].line()
        self.assertIn("[x]", line)
        self.assertIn("+2", line)


if __name__ == "__main__":
    unittest.main(verbosity=2)
