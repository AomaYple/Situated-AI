"""扫描模块测试。

用临时目录构造可控的文件树，避免测试结果依赖游戏安装。
另有一组集成测试跑真实游戏目录，安装不存在时自动跳过。
"""

from __future__ import annotations

import contextlib
import shutil
import tempfile
import unittest
from pathlib import Path

from pdx.scan import (
    TEXT_SUFFIXES,
    count_files,
    stats_for,
    subdir_stats,
    walk_files,
)


class TempTree:
    """搭建临时文件树的上下文管理器。

    用标准库 :mod:`tempfile` 申请目录 —— 目录名由操作系统保证**全局唯一**，
    因此在 pytest-xdist 的并行 worker 之间也不会撞名。

    早先这里是「类变量计数器 + 固定前缀」的自家实现。那在单进程下没问题，
    但 worker 之间计数器各自从 0 开始，两个 worker 会同时占用 ``t0001``，
    互相看到对方建的文件 —— 这个隔离缺陷正是并行跑测试时暴露出来的。
    当时避开 tempfile 的理由（沙箱按 ``mkdir`` 的 0o700 模式施加 ACL）
    已不成立。
    """

    def __init__(self, spec: dict[str, str | bytes]) -> None:
        self.spec = spec
        self.root: Path = Path()

    def __enter__(self) -> Path:
        self.root = Path(tempfile.mkdtemp(prefix="v3-scan-"))
        for rel, content in self.spec.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                p.write_bytes(content)
            else:
                p.write_text(content, encoding="utf-8")
        return self.root

    def __exit__(self, *exc) -> None:
        with contextlib.suppress(OSError):
            shutil.rmtree(self.root, ignore_errors=True)


class TestWalkFiles(unittest.TestCase):
    def test_finds_nested_files(self):
        with TempTree({"a.txt": "x", "sub/b.txt": "y", "sub/deep/c.txt": "z"}) as root:
            found = {f.path.relative_to(root).as_posix() for f in walk_files(root)}
        self.assertEqual(found, {"a.txt", "sub/b.txt", "sub/deep/c.txt"})

    def test_suffix_filter(self):
        with TempTree({"a.txt": "x", "b.md": "y", "c.dds": "z"}) as root:
            found = {f.path.name for f in walk_files(root, suffix=".txt")}
        self.assertEqual(found, {"a.txt"})

    def test_empty_dir(self):
        with TempTree({}) as root:
            self.assertEqual(list(walk_files(root)), [])

    def test_missing_dir_returns_nothing(self):
        self.assertEqual(list(walk_files(Path("Z:/definitely/not/here"))), [])

    def test_sizes_reported(self):
        with TempTree({"a.txt": "hello"}) as root:
            f = next(iter(walk_files(root)))
        self.assertEqual(f.size, 5)

    def test_suffix_lowercased(self):
        with TempTree({"A.TXT": "x"}) as root:
            f = next(iter(walk_files(root)))
        self.assertEqual(f.suffix, ".txt")


class TestStats(unittest.TestCase):
    def test_counts_and_size(self):
        with TempTree({"a.txt": "12345", "b.md": "123", "sub/c.txt": "1"}) as root:
            st = stats_for(root)
        self.assertEqual(st.files, 3)
        self.assertEqual(st.size, 9)
        self.assertEqual(st.text_files, 3)
        self.assertEqual(st.binary_files, 0)
        self.assertEqual(st.dirs, 1)

    def test_binary_extension_classified(self):
        with TempTree({"a.dds": b"\x00\x01\x02"}) as root:
            st = stats_for(root)
        self.assertEqual(st.binary_files, 1)
        self.assertEqual(st.text_files, 0)

    def test_suffix_histogram(self):
        with TempTree({"a.txt": "x", "b.txt": "y", "c.md": "z"}) as root:
            st = stats_for(root)
        self.assertEqual(st.by_suffix[".txt"], 2)
        self.assertEqual(st.by_suffix[".md"], 1)

    def test_size_mb_rounding(self):
        with TempTree({"a.bin": b"x" * 1024}) as root:
            st = stats_for(root)
        self.assertEqual(st.size_mb, 0.0)

    def test_non_deep_only_counts_direct(self):
        with TempTree({"a.txt": "x", "sub/b.txt": "y", "sub/c.txt": "z"}) as root:
            st = stats_for(root, deep=False)
        self.assertEqual(st.files, 1)
        self.assertEqual(st.dirs, 1)

    def test_missing_dir(self):
        st = stats_for(Path("Z:/nope"))
        self.assertEqual(st.files, 0)

    def test_subdir_stats_sorted(self):
        with TempTree({"b/1.txt": "x", "a/2.txt": "y", "c/3.txt": "z"}) as root:
            names = [s.name for s in subdir_stats(root)]
        self.assertEqual(names, ["a", "b", "c"])

    def test_subdir_stats_深层统计目录数(self):
        """深层统计必须靠 `_walk_dirs` 递归数出全部层级的目录。

        这条对着一个真实踩过的坑：`_walk_dirs` 从手写栈换成 `os.walk` 之后，
        符号链接目录的过滤语义要**保持不变**，否则同一个树在深浅两种口径下
        会给出不同的目录数。
        """
        with TempTree({"a/b/c/x.txt": "1", "a/y.txt": "2", "d/z.txt": "3"}) as root:
            stats = {s.name: s for s in subdir_stats(root)}
        self.assertEqual(sorted(stats), ["a", "d"])
        self.assertEqual(stats["a"].files, 2, "a 下应有 x.txt 与 y.txt")
        self.assertEqual(stats["a"].dirs, 2, "a 下应有 b 与 c 两层目录")
        self.assertEqual(stats["d"].dirs, 0)

    def test_subdir_stats_浅层只数直接子项(self):
        with TempTree({"a/b/c/x.txt": "1"}) as root:
            stats = {s.name: s for s in subdir_stats(root, deep=False)}
        self.assertEqual(stats["a"].dirs, 1)
        self.assertEqual(stats["a"].files, 0, "浅层不应数到 a/b/c/x.txt")

    def test_subdir_stats_目录不存在时返回空表(self):
        self.assertEqual(subdir_stats(Path("Z:/definitely/not/here")), [])


class TestHelpers(unittest.TestCase):
    def test_count_files(self):
        with TempTree({"a.txt": "x", "b.txt": "y", "c.md": "z"}) as root:
            self.assertEqual(count_files(root), 3)
            self.assertEqual(count_files(root, ".txt"), 2)


class TestTextSuffixes(unittest.TestCase):
    def test_contains_core_extensions(self):
        for ext in (".txt", ".md", ".gui", ".yml"):
            self.assertIn(ext, TEXT_SUFFIXES)


class TestRealGameTree(unittest.TestCase):
    """集成测试：对真实游戏目录做结构断言。"""

    game: Path

    @classmethod
    def setUpClass(cls):
        from pdx.config import GAME

        cls.game = GAME
        if not cls.game.is_dir():
            raise unittest.SkipTest("游戏目录不可用")

    def test_common_has_136_subdirs(self):
        from pdx.config import GAME

        common = GAME / "common"
        n = sum(1 for p in common.iterdir() if p.is_dir())
        self.assertEqual(n, 136)

    def test_common_txt_count(self):
        """common 下 .txt 数。

        注意区分：**.txt 数**与 **全部文件数**是两个口径，
        极易混淆（doc 08 与 doc 13 用的就不是同一个）。

        本值随游戏版本变化：1.14.2 是 3024，1.14.3 是 3026。
        改这个数字前请先确认游戏版本，不要为了让测试通过而改。
        """
        from pdx.config import GAME

        n = count_files(GAME / "common", ".txt")
        self.assertEqual(n, 3026)

    def test_common_total_file_count(self):
        from pdx.config import GAME

        self.assertEqual(count_files(GAME / "common"), 3101)

    def test_common_md_count_is_75(self):
        from pdx.config import GAME

        self.assertEqual(count_files(GAME / "common", ".md"), 75)

    def test_game_root_files_present(self):
        from pdx.config import GAME

        for name in ("checksum_manifest.txt", "paths.settings"):
            with self.subTest(name=name):
                self.assertTrue((GAME / name).is_file())

    def test_checksum_manifest_lists_five_dirs(self):
        from pdx.config import GAME

        text = (GAME / "checksum_manifest.txt").read_text(encoding="utf-8-sig")
        for d in ("common", "events", "map_data", "gui", "localization"):
            self.assertIn(f"name = {d}", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
