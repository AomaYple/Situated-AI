"""扫描模块测试。

用临时目录构造可控的文件树，避免测试结果依赖游戏安装。
另有一组集成测试跑真实游戏目录，安装不存在时自动跳过。
"""

from __future__ import annotations

import contextlib
import shutil
import unittest
from pathlib import Path

from pdx.scan import (
    TEXT_SUFFIXES,
    count_files,
    find_by_name,
    stats_for,
    subdir_stats,
    total_size,
    walk_files,
)


class TempTree:
    """搭建临时文件树的上下文管理器。

    刻意**不用** ``tempfile``：它创建目录时会设置受限权限（0o700），
    而沙箱既拒绝 chmod、也拒绝向那种目录写入 —— 实测持续 PermissionError。
    改用普通目录，自己管清理。
    """

    BASE = Path(__file__).resolve().parents[2] / ".testtmp"
    _seq = 0

    def __init__(self, spec: dict[str, str | bytes]) -> None:
        self.spec = spec
        self.root: Path = Path()

    def __enter__(self) -> Path:
        TempTree._seq += 1
        self.BASE.mkdir(parents=True, exist_ok=True)
        self.root = self.BASE / f"t{TempTree._seq:04d}"
        self.root.mkdir(parents=True, exist_ok=True)
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
        with TempTree(
            {"a.txt": "12345", "b.md": "123", "sub/c.txt": "1"}
        ) as root:
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

class TestHelpers(unittest.TestCase):
    def test_count_files(self):
        with TempTree({"a.txt": "x", "b.txt": "y", "c.md": "z"}) as root:
            self.assertEqual(count_files(root), 3)
            self.assertEqual(count_files(root, ".txt"), 2)

    def test_total_size(self):
        with TempTree({"a": "12345", "b": "123"}) as root:
            self.assertEqual(total_size(root), 8)

    def test_find_by_name_case_insensitive(self):
        with TempTree({"ReadMe.md": "x", "OTHER.txt": "y"}) as root:
            hits = find_by_name(root, ["readme"])
        self.assertEqual([p.name for p in hits], ["ReadMe.md"])

    def test_find_by_name_multiple_patterns(self):
        with TempTree({"a_readme.md": "x", "b_changelog.md": "y", "c.txt": "z"}) as root:
            hits = find_by_name(root, ["readme", "changelog"])
        self.assertEqual(len(hits), 2)

class TestTextSuffixes(unittest.TestCase):
    def test_contains_core_extensions(self):
        for ext in (".txt", ".md", ".gui", ".yml"):
            self.assertIn(ext, TEXT_SUFFIXES)

class TestRealGameTree(unittest.TestCase):
    """集成测试：对真实游戏目录做结构断言。"""

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
