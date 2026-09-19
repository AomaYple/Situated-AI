"""解析缓存：内存记忆化 + 可选的**磁盘**层。

动机
----
剖析发现全量分析里有大量时间是**纯浪费** —— ``vanilla_prefix_count``
把整个游戏树又解析了一遍，而 ``game_analysis`` 刚刚才解析过。
mod 分析同理：多个 mod 覆盖同一个原版文件时，那个文件会被反复解析。

内存层（``lru_cache``）解决了同一次进程内的重复；但**跨进程**没有解决：
``pytest -n auto`` 的 16 个 worker 各自从零解析同一批 6 千个文件，
``v3 tables`` / ``v3 verify`` / ``v3 refresh`` 每次重跑也都要重解析。
磁盘层就是为这两件事加的。

实现
----
两层，都是**按文件内容寻址**，而不是按时间或路径记账：

* **内存层** —— 标准库 :func:`functools.cache`，不自己维护字典。
  命中率统计由 ``cache_info()`` 提供，与 :func:`stats` 的三个字段一一对应；
  线程安全由 ``lru_cache`` 内部的锁保证。
* **磁盘层** —— 键是 ``sha256(路径 + mtime_ns + size + 引擎指纹)``，
  值是 ``pickle`` 过的 :class:`~pdx.model.ParsedFile`，原子写（临时文件 + ``os.replace``）。
  放在**系统临时目录**下，按仓库路径分桶 —— 不往仓库里塞可再生文件
  （``tools/out`` 下有入库产物与产物检查，缓存混进去只会互相干扰）。

正确性（这一节是重点，缓存一旦不透明，全量分析的数字会随「跑第几遍」而变）
------------------------------------------------------------------------
* ``parse_cached`` 对调用方的语义**完全等价于** ``parse_file``：
  任何一层命中都返回**同一个** ``ParsedFile`` 结构，测试逐字段比对（``test_cache.py``）；
* **源文件一变，键就变**：``mtime_ns`` 与 ``size`` 都进了键，所以「改写文件再读」
  不会读到旧结果；
* **解析器一变，键也变**：``引擎指纹`` 取 ``parser.py`` / ``model.py`` / ``lexer.py``
  三个模块的 mtime 与 :data:`PARSE_CACHE_FORMAT`，改了实现就整体失效
  —— 这比「记得手动清缓存」可靠；
* **磁盘层坏了不影响正确性**：读失败 / 反序列化失败 / 结构不对，一律当作未命中
  并删掉那条，然后正常解析；
* **写失败静默**：只读文件系统、磁盘满、权限不足都只是「没有磁盘缓存」，
  绝不让缓存故障变成解析故障。

关闭与清理
----------
``V3_PARSE_CACHE=0`` 关闭磁盘层（内存层照旧）；``v3 cache --clear`` 清空磁盘层。
"""

from __future__ import annotations

import atexit
import contextlib
import hashlib
import os
import pickle
import tempfile
import zlib
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from . import config
from .parser import parse_file as _parse_file

if TYPE_CHECKING:
    from .model import ParsedFile

#: 磁盘缓存的结构版本。**解析结果的结构变了就 +1**（字段增删、语义变化）。
#: 与引擎指纹配合：改代码时 mtime 会让旧条目失效，改结构时这里是双保险。
PARSE_CACHE_FORMAT = 1

#: 关闭磁盘层的环境变量（值为 ``0`` / ``false`` / ``no`` / ``off`` 时关闭）。
CACHE_ENV = "V3_PARSE_CACHE"

#: pytest-xdist 给 worker 进程设的变量。存在时**只读缓存、不写**（见 :func:`flush`）。
WORKER_ENV = "PYTEST_XDIST_WORKER"

#: 分片数。实测（3,960 个脚本文件、1.14.3）：全部解析 65.0 s →
#: ``pickle.dumps`` 9.7 s → ``zlib -1`` 0.6 s（208 MB → 59.6 MB）→ 读回 2.8 s。
#: **一片一条文件**（3,960 个小文件）反而比重新解析更慢（实测 7.7 s vs 2.3 s，
#: 小文件读放大），所以按分片打包。
SHARDS = 16

#: 一片里最多留多少条（超了就丢最旧的）。旧条目的指纹永远命中不了，只是占地方。
MAX_ENTRIES_PER_SHARD = 4_000

#: 本次进程解析到这个数量才值得写盘（理由见 :func:`flush`）。
MIN_ENTRIES_TO_PERSIST = 200

#: 参与「引擎指纹」的模块文件。改了任何一个，整个磁盘缓存自动失效。
_ENGINE_SOURCES = ("parser.py", "model.py", "lexer.py", "cache.py")


@dataclass
class _DiskState:
    """磁盘层的进程内状态。

    用一个对象而不是四个模块级全局：`global` 语句容易在重构时被漏掉
    （ruff 的 PLW0603 就是冲这个来的），而这里的四个量本来就是一体的 ——
    「读了哪些分片、改了哪些、序号到几、这轮解析了几个文件」。
    """

    #: 分片的惰性视图：``{分片号: {指纹: (写入序号, 解析结果)}}``。
    shards: dict[int, dict[str, tuple[int, ParsedFile]]] = field(default_factory=dict)
    #: 待落盘的分片号。
    dirty: set[int] = field(default_factory=set)
    #: 单调递增的写入序号（瘦身时按「新近」排序用）。
    seq: int = 0
    #: 本次进程真正解析过（未命中）的文件数 —— 决定要不要写盘。
    parsed_total: int = 0


#: 磁盘层的状态（测试通过它模拟「另一个进程」：清空即等于换进程）。
_state = _DiskState()


@cache
def _parse_by_key(key: str) -> ParsedFile:
    """真正干活的那一层。键必须是 ``str`` —— ``Path`` 与 ``str`` 会算成两条。

    单独抽一层的原因：``lru_cache`` 按**实参**做键，若直接装饰
    ``parse_cached``，``Path("a")`` 与 ``"a"`` 会各缓存一份，
    白白解析两次（实测确实如此）。统一在入口处 ``str()`` 化即可避免。
    """
    sig = _signature(key)
    shard = _shard_of(key)
    if sig is not None:
        hit = _disk_load(sig, shard)
        if hit is not None:
            return hit
    parsed = _parse_file(key)
    if sig is not None:
        _state.parsed_total += 1
        _disk_store(sig, shard, parsed)
    return parsed


def parse_cached(path: str | Path) -> ParsedFile:
    """解析文件，带记忆化（内存 + 磁盘）。同一路径只真正解析一次。"""
    return _parse_by_key(str(path))


def clear() -> None:
    """清空**内存**缓存并重置统计。磁盘层不受影响（用 :func:`clear_disk`）。"""
    _parse_by_key.cache_clear()


def stats() -> dict[str, int]:
    """内存缓存统计。字段名保持历史口径，避免调用方与文档大改。"""
    info = _parse_by_key.cache_info()
    return {
        "条目": info.currsize,
        "命中": info.hits,
        "未命中": info.misses,
    }


# ────────────────────────── 磁盘层 ──────────────────────────


def _enabled() -> bool:
    raw = os.environ.get(CACHE_ENV, "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _is_xdist_worker() -> bool:
    """是否是 pytest-xdist 的 worker 进程（worker 只读缓存，理由见 :func:`flush`）。"""
    return bool(os.environ.get(WORKER_ENV))


def cache_dir() -> Path:
    """磁盘缓存目录：系统临时目录下按**仓库路径**分桶。

    为什么不放 ``tools/out/``：那是入库产物与 ``v3 check-outputs`` 的地盘，
    可再生文件混进去会让「产物有哪些」变成不确定的。临时目录也天然
    不会被 ``git status`` 看见。
    """
    bucket = hashlib.sha256(str(config.REPO).encode("utf-8")).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"v3-parse-cache-{bucket}"


@cache
def _engine_stamp() -> str:
    """引擎指纹：登记模块的 mtime + 结构版本。"""
    parts = [str(PARSE_CACHE_FORMAT)]
    base = Path(__file__).parent
    for name in _ENGINE_SOURCES:
        try:
            parts.append(f"{name}:{int((base / name).stat().st_mtime_ns)}")
        except OSError:  # pragma: no cover - 模块文件必然存在
            parts.append(f"{name}:?")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _signature(path: str) -> str | None:
    """文件的**内容指纹**（路径 + mtime + 大小 + 引擎指纹）；取不到时 ``None``。"""
    if not _enabled():
        return None
    try:
        st = Path(path).stat()
    except OSError:
        return None
    raw = f"{path}\0{st.st_mtime_ns}\0{st.st_size}\0{_engine_stamp()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _shard_of(path: str) -> int:
    """文件属于哪个分片。**不能用内置 hash()** —— 它带进程随机化，跨进程不稳定。"""
    return int(hashlib.sha256(path.encode("utf-8")).hexdigest()[:8], 16) % SHARDS


def _shard_path(index: int) -> Path:
    return cache_dir() / f"shard-{index:02d}.bin"


def _load_shard(index: int) -> dict[str, tuple[int, ParsedFile]]:
    """惰性读一个分片；文件不存在或坏了都返回空字典（并删掉坏文件）。"""
    cached = _state.shards.get(index)
    if cached is not None:
        return cached
    entries: dict[str, tuple[int, ParsedFile]] = {}
    path = _shard_path(index)
    try:
        raw = path.read_bytes()
        body = pickle.loads(zlib.decompress(raw))  # 只读本工具自己写的目录
        if isinstance(body, dict) and body.get("格式") == PARSE_CACHE_FORMAT:
            entries = dict(body.get("条目", {}))
        else:  # 结构版本不同 —— 整片作废，不试图兼容
            _silent_unlink(path)
    except FileNotFoundError:
        pass
    except Exception:  # 坏缓存不是错误，删掉重算即可（含 unpickle 失败）
        _silent_unlink(path)
    _state.shards[index] = entries
    return entries


def _disk_load(sig: str, shard: int) -> ParsedFile | None:
    """按内容指纹取一条；取不到返回 ``None``。"""
    entry = _load_shard(shard).get(sig)
    return entry[1] if entry is not None else None


def _disk_store(sig: str, shard: int, parsed: ParsedFile) -> None:
    """放一条进对应分片（**不立即落盘** —— 进程退出时统一 flush）。"""
    _state.seq += 1
    _load_shard(shard)[sig] = (_state.seq, parsed)
    _state.dirty.add(shard)


def flush(*, force: bool = False) -> int:
    """把脏分片落盘，返回写出的分片数。

    两条**不写**的规矩，都是实测逼出来的：

    * **xdist 的 worker 只读不写**（``PYTEST_XDIST_WORKER`` 存在时直接返回）——
      16 个 worker 会把同一批分片各写一遍（每片约 4 MB，合计上 GB 的重复写），
      实测后果是整套测试从 4 分钟涨到 20 分钟以上还在抖。worker 之间不共享
      内存缓存，但**可以共享磁盘缓存**：让它们读、由普通进程（`v3 tables`
      这类命令）负责写，收益还在，抖动没了。
    * **只在本次进程解析过足够多文件时才写**（:data:`MIN_ENTRIES_TO_PERSIST`）：
      实测一次全树解析 65 s、而全部 16 片读回只要 2.8 s，写盘约 10 s ——
      对全树任务这是净赚，对只解析几个文件的短命令（`v3 evidence`）则是纯亏。
    """
    if not _enabled() or _is_xdist_worker():
        return 0
    if not force and _state.parsed_total < MIN_ENTRIES_TO_PERSIST:
        return 0
    written = 0
    for index in sorted(_state.dirty):
        entries = _state.shards.get(index) or {}
        if len(entries) > MAX_ENTRIES_PER_SHARD:
            newest = sorted(entries.items(), key=lambda item: item[1][0])
            entries = dict(newest[len(entries) - MAX_ENTRIES_PER_SHARD :])
            _state.shards[index] = entries
        path = _shard_path(index)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            blob = zlib.compress(
                pickle.dumps(
                    {"格式": PARSE_CACHE_FORMAT, "条目": entries},
                    protocol=pickle.HIGHEST_PROTOCOL,
                ),
                1,
            )
            tmp = path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_bytes(blob)
            tmp.replace(path)
        except Exception:  # 缓存写失败不能影响解析（只读盘 / 磁盘满 / 权限）
            continue
        written += 1
    _state.dirty.clear()
    return written


def _silent_unlink(path: Path) -> None:
    with contextlib.suppress(OSError):  # 并发删同一个文件
        path.unlink()


def disk_entries() -> list[tuple[Path, float, int]]:
    """磁盘缓存分片：``[(路径, mtime, 字节), …]``（目录不存在时为空）。"""
    base = cache_dir()
    out: list[tuple[Path, float, int]] = []
    if not base.is_dir():
        return out
    for path in sorted(base.glob("shard-*.bin")):
        try:
            st = path.stat()
        except OSError:  # pragma: no cover - 并发删除
            continue
        out.append((path, st.st_mtime, st.st_size))
    return out


def disk_counts() -> dict[str, int]:
    """磁盘缓存里**可命中的条目数**（分片数 / 条目数 / 字节）。

    与「分片文件数」不同：分片里可能留着内容已变（指纹对不上）的旧条目，
    那些永远命中不了，只是等下次 flush 时被瘦身掉。
    """
    files = disk_entries()
    entries = 0
    for index in range(SHARDS):
        path = _shard_path(index)
        if path.is_file():
            entries += len(_load_shard(index))
    return {
        "分片": len(files),
        "条目": entries,
        "字节": sum(size for _p, _m, size in files),
    }


def clear_disk() -> int:
    """清空磁盘缓存（分片文件全删 + 内存里的分片视图也清），返回删掉的分片数。"""
    files = disk_entries()
    for path, _mtime, _size in files:
        _silent_unlink(path)
    _state.shards.clear()
    _state.dirty.clear()
    _state.parsed_total = 0
    _parse_by_key.cache_clear()
    return len(files)


#: 供 CLI 展示：解释层为什么可能是空的。
def describe_state() -> str:
    """一句话说明磁盘层当前是否启用。"""
    if not _enabled():
        return f"已关闭（{CACHE_ENV}=0）"
    if _is_xdist_worker():
        return "只读（xdist worker 不写盘，见 pdx.cache.flush）"
    return f"启用（{cache_dir()}）"


#: 进程退出时把脏分片落盘。**注册在这里而不是让调用方显式调用**：
#: 缓存是透明的，任何调用方都不该为了「让缓存生效」多写一行代码。
atexit.register(flush)
