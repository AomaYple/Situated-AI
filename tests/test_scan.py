"""扫描模块测试。

用临时目录构造可控的文件树，避免测试结果依赖游戏安装。
另有一组集成测试跑真实游戏目录，安装不存在时自动跳过。
"""

from __future__ import annotations

import contextlib
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pdx import scan
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
        """深层统计包含全部子目录，但不包含被统计目录本身。"""
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

    def test_common_has_138_subdirs(self):
        from pdx.config import GAME

        common = GAME / "common"
        n = sum(1 for p in common.iterdir() if p.is_dir())
        self.assertEqual(n, 138)

    def test_common_txt_count(self):
        """common 下 .txt 数。

        注意区分：**.txt 数**与 **全部文件数**是两个口径，
        极易混淆（doc 08 与 doc 13 用的就不是同一个）。

        本值随游戏版本变化：1.14.2 是 3024，1.14.3 是 3026，1.14.4 是 3028。
        改这个数字前请先确认游戏版本，不要为了让测试通过而改。
        """
        from pdx.config import GAME

        n = count_files(GAME / "common", ".txt")
        self.assertEqual(n, 3030)

    def test_common_total_file_count(self):
        from pdx.config import GAME

        self.assertEqual(count_files(GAME / "common"), 3107)

    def test_common_md_count_is_77(self):
        from pdx.config import GAME

        self.assertEqual(count_files(GAME / "common", ".md"), 77)

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


@pytest.mark.parametrize("deep", [False, True])
@pytest.mark.parametrize("kind", ["empty", "file", "missing"])
def test_stats_empty_or_non_directory(tmp_path, kind, deep):
    path = tmp_path / kind
    if kind == "empty":
        path.mkdir()
    elif kind == "file":
        path.write_bytes(b"abc")
    assert stats_for(path, deep=deep) == scan.DirStats(name=kind, path=path)


def test_deep_stats_retains_all_fields_and_suffix_order(tmp_path):
    (tmp_path / "empty").mkdir()
    (tmp_path / "nested" / "empty").mkdir(parents=True)
    for rel, content in {
        "UPPER.TXT": b"abc",
        "nested/中文.md": b"xy",
        "nested/texture.dds": b"1234",
        ".hidden": b"5",
        "no_suffix": b"67",
    }.items():
        (tmp_path / rel).write_bytes(content)
    result = stats_for(tmp_path)
    assert (result.files, result.dirs, result.size) == (5, 3, 12)
    assert (result.text_files, result.binary_files) == (2, 3)
    assert result.by_suffix == {".txt": 1, ".md": 1, ".dds": 1, "": 2}
    # 与公开文件流的首次出现顺序一致，避免序列化顺序漂移。
    assert list(result.by_suffix) == list(dict.fromkeys(f.suffix for f in walk_files(tmp_path)))


def test_shallow_stats_retains_unclassified_fields(tmp_path):
    (tmp_path / "child").mkdir()
    (tmp_path / "child" / "nested.md").write_bytes(b"hidden")
    (tmp_path / "direct.TXT").write_bytes(b"abc")
    result = stats_for(tmp_path, deep=False)
    assert (result.files, result.dirs, result.size) == (1, 1, 3)
    assert (result.text_files, result.binary_files) == (0, 0)
    assert not result.by_suffix


def test_stats_counts_hard_links_as_distinct_paths(tmp_path):
    source = tmp_path / "source.txt"
    source.write_bytes(b"abc")
    try:
        (tmp_path / "alias.txt").hardlink_to(source)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"当前平台不支持硬链接：{exc}")
    result = stats_for(tmp_path)
    assert (result.files, result.dirs, result.size) == (2, 0, 6)
    assert result.by_suffix == {".txt": 2}


@pytest.mark.parametrize("blocked_child", [False, True])
def test_stats_isolates_unreadable_directories(tmp_path, monkeypatch, blocked_child):
    blocked = tmp_path / "blocked" if blocked_child else tmp_path
    (tmp_path / "blocked").mkdir()
    (tmp_path / "blocked" / "secret.txt").write_bytes(b"hidden")
    (tmp_path / "peer.txt").write_bytes(b"ok")
    original = scan.os.scandir

    def scandir(path):
        if Path(path) == blocked:
            raise PermissionError("拒绝读取目录")
        return original(path)

    monkeypatch.setattr(scan.os, "scandir", scandir)
    result = stats_for(tmp_path)
    assert (result.files, result.dirs, result.size) == ((1, 1, 2) if blocked_child else (0, 0, 0))
    assert result.by_suffix == ({".txt": 1} if blocked_child else {})


@pytest.mark.parametrize("operation", ["is_dir", "is_file", "stat"])
def test_stats_isolates_entry_metadata_errors(tmp_path, monkeypatch, operation):
    bad = SimpleNamespace(
        name="bad.txt",
        path=str(tmp_path / "bad.txt"),
        is_dir=Mock(return_value=False),
        is_file=Mock(return_value=True),
        stat=Mock(return_value=SimpleNamespace(st_size=100)),
    )
    getattr(bad, operation).side_effect = FileNotFoundError("扫描过程中条目消失")
    good = SimpleNamespace(
        name="peer.txt",
        path=str(tmp_path / "peer.txt"),
        is_dir=Mock(return_value=False),
        is_file=Mock(return_value=True),
        stat=Mock(return_value=SimpleNamespace(st_size=2)),
    )

    @contextmanager
    def scandir(_path):
        yield iter([bad, good])

    monkeypatch.setattr(scan.os, "scandir", scandir)
    result = stats_for(tmp_path)
    assert (result.files, result.dirs, result.size) == (1, 0, 2)
    assert (result.text_files, result.binary_files) == (1, 0)
    assert result.by_suffix == {".txt": 1}


def test_stats_keeps_partial_results_and_closes_failed_iteration(tmp_path, monkeypatch):
    entry = SimpleNamespace(
        name="seen.txt",
        path=str(tmp_path / "seen.txt"),
        is_dir=Mock(return_value=False),
        is_file=Mock(return_value=True),
        stat=Mock(return_value=SimpleNamespace(st_size=3)),
    )
    closed = []

    def entries():
        yield entry
        raise PermissionError("目录枚举中途失败")

    @contextmanager
    def scandir(_path):
        try:
            yield entries()
        finally:
            closed.append(True)

    monkeypatch.setattr(scan.os, "scandir", scandir)
    result = stats_for(tmp_path)
    assert (result.files, result.dirs, result.size) == (1, 0, 3)
    assert result.by_suffix == {".txt": 1}
    assert closed == [True]


def test_stats_ignores_child_links_but_allows_link_as_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "real").mkdir()
    (root / "real" / "file.txt").write_bytes(b"ok")
    linked_root = tmp_path / "linked-root"
    try:
        linked_root.symlink_to(root, target_is_directory=True)
        (root / "dir-link").symlink_to(root / "real", target_is_directory=True)
        (root / "cycle").symlink_to(root, target_is_directory=True)
        (root / "file-link.txt").symlink_to(root / "real" / "file.txt")
        (root / "dangling").symlink_to(root / "missing")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"当前平台未授予符号链接能力：{exc}")
    for path in (root, linked_root):
        result = stats_for(path)
        assert (result.files, result.dirs, result.size) == (1, 1, 2)
        assert result.by_suffix == {".txt": 1}


if __name__ == "__main__":
    unittest.main(verbosity=2)
