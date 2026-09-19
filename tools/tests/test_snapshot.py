"""快照机制测试。

核心保证有两条，任何一条破了 diff 就失去意义：

1. **确定性** —— 同一环境重复构建的快照必须完全相同
2. **完备性** —— 覆盖全部 mod 相关域，且不遗漏重复块中的参数
"""

from __future__ import annotations

import json
import unittest

from pdx import config, snapshot

#: **不参与「列表已排序」判定**的域。
#:
#: ``doc_tables`` 存的是**生成表的数据行**（`文档名::表名 → [行文本, …]`）：
#: 行的顺序**就是表格的顺序**（按语义排、按体积排……），排序会把表打乱；
#: 重复行也合法（两张表出现同样的行很常见）。它是快照里唯一「顺序本身是数据」
#: 的域，所以这里显式豁免而不是把断言放宽到所有域。
_ORDERED_SECTIONS = frozenset({"doc_tables"})


class TestSnapshotShape(unittest.TestCase):
    snap: snapshot.Snapshot

    @classmethod
    def setUpClass(cls):
        if not (config.GAME / "common").is_dir():
            raise unittest.SkipTest("游戏目录不可用")
        cls.snap = snapshot.build()

    def test_has_all_sections(self):
        for sec in ("common_entries", "fields", "defines", "localization", "dlc", "config"):
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
            if sec in _ORDERED_SECTIONS:
                continue
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


class TestCompactSnapshot(unittest.TestCase):
    """精简快照：体积小到可入库，但必须仍能回答「字段增删」这个核心问题。"""

    snap: snapshot.Snapshot

    @classmethod
    def setUpClass(cls):
        if not (config.GAME / "common").is_dir():
            raise unittest.SkipTest("游戏目录不可用")
        cls.snap = snapshot.build(compact=True)

    def test_用指纹域替代键清单(self):
        """本地化只留「键数 + sha256」，不带 14 万条键名。"""
        self.assertIn("localization_digest", self.snap.sections)
        self.assertNotIn("localization", self.snap.sections)
        digest = self.snap.sections["localization_digest"]
        self.assertEqual(len(digest), 11)  # 11 种语言
        for lang, entry in digest.items():
            with self.subTest(lang=lang):
                self.assertEqual(len(entry), 2)
                self.assertTrue(entry[0].endswith("键"))
                self.assertTrue(entry[1].startswith("sha256:"))

    def test_结构域完整保留(self):
        """「Paradox 增删了哪些字段」靠的是这几个域，一个都不能少。"""
        for sec in ("common_entries", "fields", "defines", "dlc", "config"):
            with self.subTest(section=sec):
                self.assertIn(sec, self.snap.sections)
        self.assertEqual(len(self.snap.sections["common_entries"]), 136)
        self.assertGreater(len(self.snap.sections["fields"]), 20_000)

    def test_与完整快照的结构域一致(self):
        """精简只应影响本地化那一个域 —— 其余域必须逐字节等同。"""
        full = snapshot.build()
        for sec in ("common_entries", "fields", "defines", "dlc", "config"):
            with self.subTest(section=sec):
                self.assertEqual(self.snap.sections[sec], full.sections[sec])

    def test_标记了精简位(self):
        """`精简` 标记要落进文件 —— 否则 diff 时无法判断两边是否同口径。"""
        self.assertTrue(self.snap.compact)
        self.assertTrue(self.snap.to_dict()["精简"])
        self.assertFalse(snapshot.build().to_dict()["精简"])

    def test_往返保住精简标记(self):
        """``load(write(x))`` 必须等价 —— 曾经 ``load`` 会丢掉这个标记。"""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "s.json"
            self.snap.write(p)
            back = snapshot.Snapshot.load(p)
            raw = p.read_bytes()
        self.assertTrue(back.compact)
        self.assertEqual(back.sections, self.snap.sections)
        # 精简快照是**入库**的，而 .gitattributes 规定 eol=lf ——
        # 写成 CRLF 会让 Windows 与 Linux 生成的快照字节不同、diff 整份报差异。
        self.assertNotIn(b"\r\n", raw, "快照里出现了 CRLF：write() 漏了 newline='\\n'")

    def test_同一个域可以自己跟自己比(self):
        """形状与完整版相同，因此 compare 对它照常可用。"""
        self.assertEqual(snapshot.compare(self.snap, self.snap), [])


class TestCommittedCompactSnapshot(unittest.TestCase):
    """入库的那份精简快照必须真的在、且能被读出来。

    它是仓库里**唯一**随版本控制分发的基线 —— 别的地方删了它不会有任何
    症状，直到某天有人想 diff 才发现「新克隆的仓库里一份基线都没有」。
    这条不依赖游戏安装，所以在 CI 上也会跑。
    """

    def test_至少有一份精简快照入库(self):
        tracked = sorted(snapshot.SNAPSHOT_DIR.glob("*.compact.json"))
        self.assertTrue(
            tracked,
            "tools/out/snapshots/ 下没有 *.compact.json —— "
            "跑 `v3 snapshot create --compact` 生成一份（它是入库的）",
        )

    def test_精简快照能被读出来且标记正确(self):
        for path in sorted(snapshot.SNAPSHOT_DIR.glob("*.compact.json")):
            with self.subTest(快照=path.name):
                snap = snapshot.Snapshot.load(path)
                self.assertTrue(snap.compact)
                self.assertIn("localization_digest", snap.sections)
                self.assertNotIn("localization", snap.sections)
                self.assertTrue(snap.version.get("caligula_branch"))
                # 结构域是它的全部价值所在，缺一个就白存了
                for sec in ("common_entries", "fields", "defines", "dlc", "config"):
                    self.assertIn(sec, snap.sections)


if __name__ == "__main__":
    unittest.main(verbosity=2)
