"""全局 fixture。

临时目录
--------
直接用 pytest 的 ``tmp_path``，但在未显式指定 ``--basetemp`` 时，
先为本轮测试选择仓库外的系统临时根；受限 Windows 运行器无法访问系统 Temp 时，
才回退到带专用前缀、已忽略且会话结束清理的仓库临时根。

游戏可用性
----------
依赖真实游戏安装的测试统一打 ``integration`` 标记。游戏不在本机时，
:func:`pytest_collection_modifyitems` 会**自动跳过**它们，而不是让整套
测试报错 —— 这样在别的机器上仍能跑单元测试与属性测试。
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from collections.abc import Iterator, Sequence
from functools import lru_cache
from pathlib import Path
from typing import overload

import pytest

from pdx import analyze, parallel
from pdx import config as pdx_config
from pdx.scan import walk_files

# pytest 在某些 Windows + xdist + coverage 组合下会把默认 basetemp 解析到
# 当前工作树。仓库卫生测试必须扫描未忽略的工作区文件，因此临时文件一旦落在
# 仓库内就会与其他 worker 产生真实竞态。每个主测试进程分配一个系统临时根，
# 让 worker 的子目录仍由 pytest 管理，同时不污染仓库扫描范围。显式传入
# ``--basetemp`` 时保持调用方的调试选择，不覆盖它。
_AUTO_BASETEMPS: list[Path] = []


def _系统临时根() -> Path:
    """选择不位于仓库内的平台临时根，避免 pytest 回退污染工作树。"""
    repo = pdx_config.REPO.resolve()
    candidates = [os.environ.get(name) for name in ("TMPDIR", "TEMP", "TMP")]
    if os.name == "nt":
        candidates.append(str(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Temp"))
    else:
        candidates.append("/tmp")
    for raw in candidates:
        if not raw:
            continue
        try:
            candidate = Path(raw).expanduser().resolve()
            if candidate == repo or repo in candidate.parents:
                continue
            candidate.mkdir(parents=True, exist_ok=True)
            if candidate.is_dir():
                return candidate
        except OSError:
            continue
    raise RuntimeError("找不到位于仓库外且可写的平台临时目录")


def _创建临时根(parent: Path) -> Path:
    """在平台临时根下创建唯一目录，并容忍 Windows 瞬时权限竞争。"""
    for _ in range(64):
        candidate = parent / f"sitai-pytest-{uuid.uuid4().hex[:12]}"
        try:
            candidate.mkdir(mode=0o700)
        except OSError:
            continue
        return candidate
    raise RuntimeError(f"无法在平台临时目录创建测试根：{parent}")


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """把未指定的 pytest 临时根固定在系统临时目录。"""
    if config.getoption("basetemp", default=None) is not None:
        return
    # xdist worker 会继承 master 的命令行选项；只有极少数旧版本在 worker
    # 侧重新初始化时才会走这里，届时各 worker 也会得到独立的系统临时根。
    try:
        root = _系统临时根()
        base = _创建临时根(root)
    except RuntimeError:
        # 某些 Windows 沙箱允许普通 pytest 访问系统 Temp，却拒绝 v3.exe
        # 子进程创建目录。回退目录带专用前缀，已在 .gitignore 中声明，且由
        # pytest_sessionfinish 清理，避免把测试运行态混入仓库审计。
        root = pdx_config.REPO
        base = _创建临时根(root)
    # pytest 的 tmp_path、嵌套 pytest 以及仓库代码中的 tempfile 调用都应共享
    # 这个明确的外部根；不依赖 tempfile 在当前平台上的隐式回退策略。
    tempfile.tempdir = str(root)
    config.option.basetemp = str(base)
    if getattr(config, "workerinput", None) is None:
        _AUTO_BASETEMPS.append(base)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """清理由本进程创建的自动临时根；不触碰显式调试目录。"""
    del exitstatus
    while _AUTO_BASETEMPS:
        shutil.rmtree(_AUTO_BASETEMPS.pop(), ignore_errors=True)


@lru_cache(maxsize=64)
def _read_corpus_text(path: Path) -> tuple[str, str]:
    return str(path), path.read_text(encoding="utf-8-sig", errors="replace")


class LazyCorpusTexts(Sequence[tuple[str, str]]):
    """真实语料的惰性只读序列。

    旧 fixture 会把约 6250 个文件全文同时保存在每个 xdist worker 中。
    这里只保留路径，按索引读取，且最多缓存 64 个文本；因此全量差分测试
    仍然逐文件看到同样的 ``(路径, 文本)``，但不会把整棵语料树常驻内存。
    """

    def __init__(self, paths: Sequence[Path]) -> None:
        self._paths = tuple(paths)

    def _item(self, index: int) -> tuple[str, str]:
        return _read_corpus_text(self._paths[index])

    @overload
    def __getitem__(self, index: int) -> tuple[str, str]: ...

    @overload
    def __getitem__(self, index: slice) -> list[tuple[str, str]]: ...

    def __getitem__(self, index: int | slice) -> tuple[str, str] | list[tuple[str, str]]:
        if isinstance(index, slice):
            return [self._item(i) for i in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        return self._item(index)

    def __len__(self) -> int:
        return len(self._paths)

    def __iter__(self) -> Iterator[tuple[str, str]]:
        for index in range(len(self)):
            yield self._item(index)


#: 游戏内容层是否可用（mod 相关文件都在 game/ 下）
GAME_OK = (pdx_config.GAME / "common").is_dir()


@pytest.hookimpl(tryfirst=True, optionalhook=True)
def pytest_xdist_auto_num_workers(config: pytest.Config) -> int:
    """给 ``-n auto`` 加内存护栏，避免按逻辑 CPU 盲目复制重型 fixture。

    无论是否存在游戏树，都按 CPU 和可用内存预算计算。
    ``PYTEST_XDIST_AUTO_NUM_WORKERS`` 仍由
    xdist 自己处理，项目专用的 ``SITAI_XDIST_WORKERS`` 可强制指定数量。
    """
    del config
    return parallel.auto_worker_count()


def pytest_collection_modifyitems(config, items):
    """游戏不在本机时，自动跳过所有 integration 测试。

    ⚠️ **形参必须叫 ``config``** —— pluggy 按 hookspec 的形参名注入，
    pytest 会把**自己的 ``Config`` 对象**塞进来，于是这个形参**遮蔽**
    ``pdx.config`` 模块。因此本模块把包内配置导入为 ``pdx_config``。

    这个坑在装了游戏的机器上**永远不会暴露**：函数在执行到 ``config.GAME``
    之前就 ``if GAME_OK: return`` 了。只有在 CI / 新克隆这类没有游戏的环境里
    才会炸成 ``INTERNALERROR: 'Config' object has no attribute 'GAME'`` ——
    也就是说，**整套测试「换台机器就自动跳过集成用例」的设计全靠这一行**，
    而它此前是坏的。``tests/test_conftest.py`` 专门看守它。
    """
    if GAME_OK:
        return
    skip = pytest.mark.skip(reason=f"游戏目录不可用：{pdx_config.GAME}")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


# ── 真实语料 ────────────────────────────────────────────────
@pytest.fixture(scope="session")
def corpus_files() -> list[Path]:
    """游戏本体中所有需要深度解析的文件（实测 **6,250** 个）。

    这是差分测试与模糊测试的**真实输入来源** —— 用真实语料而不是
    自造样本，才能覆盖官方脚本里那些古怪写法。
    """
    if not GAME_OK:
        return []
    out: list[Path] = []
    for root in (pdx_config.GAME, pdx_config.JOMINI, pdx_config.CLAUSEWITZ):
        if not root.is_dir():
            continue
        for f in walk_files(root):
            try:
                rel = f.path.relative_to(root)
            except ValueError:
                continue
            if pdx_config.is_scriptable(rel.parts, f.suffix):
                out.append(f.path)
    return sorted(out)


@pytest.fixture(scope="session")
def corpus_texts(corpus_files: list[Path]) -> LazyCorpusTexts:
    """语料文本，``(路径, 内容)``；按需读取并有界缓存。"""
    readable: list[Path] = []
    for path in corpus_files:
        try:
            with path.open("rb"):
                pass
        except OSError:
            continue
        readable.append(path)
    return LazyCorpusTexts(readable)


# ── 全量分析结果（整轮只跑一次）────────────────────────────
@pytest.fixture(scope="session")
def ga():
    """游戏本体分析结果。"""
    return analyze.game_analysis()


@pytest.fixture(scope="session")
def ma():
    """mod 分析结果。"""
    return analyze.mods_analysis()


@pytest.fixture(scope="session")
def ca(ga, ma):
    """交叉分析结果。"""
    return analyze.cross_analysis(ma)
