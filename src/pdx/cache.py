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

* **内存层** —— 标准库 :func:`functools.lru_cache`（**有上限**，见
  :data:`MEMO_MAX_ENTRIES`），不自己维护字典。
  命中率统计由 ``cache_info()`` 提供，与 :func:`stats` 的三个字段一一对应；
  线程安全由 ``lru_cache`` 内部的锁保证。
* **磁盘层** —— 键是 ``sha256(路径 + mtime_ns + size + 引擎指纹)``（下称**世代键**：
  它标识的是「哪一代的输入」，不是内容本身），
  值是 ``pickle`` 过的 :class:`~pdx.model.ParsedFile`，原子写（临时文件 + ``os.replace``）。
  放在**系统临时目录**下，按仓库路径分桶 —— 不往仓库里塞可再生文件
  （``tools/out`` 下有入库产物与产物检查，缓存混进去只会互相干扰）。

磁盘层的物理布局（2026-09-25 起）
---------------------------------
**一片两个文件**：

* ``shard-NN.bin`` —— **数据段**：一条一条各自 zlib 压缩的 pickle 首尾相接；
* ``shard-NN.idx`` —— **偏移索引**：``{格式, 条目: {指纹: (偏移, 字节数, 序号)}}``。

为什么要拆开（本模块**最大的一处内存教训**，改这里之前先读这一节）：
旧布局把一个分片压成**一个** zlib 流 + **一个** dict，于是「查其中一条」只能把
**整片**解压 + 反序列化。16 片一旦都被碰过，``_state`` 里就常驻着**全量条目对象** ——
实测 **20,595 条 / 2402.5 MB**（占一个 worker 峰值 2811.6 MB 的 86%），
而且在正常解析过程中**会被持续填满**（清空后再解析又回到 20,595 条）。
磁盘层本来是为了省内存（见上面的动机），旧布局让它同时成了**最大的内存主犯**，
并且在 xdist 下被**乘以 worker 数**（每个 worker 都有自己的进程内状态）。
现在的判据是：**内存里只留索引（每片 0.1 MB 量级），不留条目对象**；
条目按偏移**单条取**，要不要留在内存中由内存层决定（而内存层有上限）。

正确性（这一节是重点，缓存一旦不透明，全量分析的数字会随「跑第几遍」而变）
------------------------------------------------------------------------
* ``parse_cached`` 对调用方的语义**完全等价于** ``parse_file``：
  任何一层命中都返回**同一个** ``ParsedFile`` 结构，测试逐字段比对（``test_cache.py``）；
* **每次入口验证当前内容**：memo 键包含 SHA-256，磁盘键还包含路径和实现指纹。
  同大小、同时间戳改写、删除和同进程重新读取都不能返回旧树；读取途中元数据变化
  或未命中后二次读取摘要变化明确失败。原文字节只用于本次验证，不随 LRU 长期保留。
  历史陈旧命中反例见 `docs/reports/缓存跨代读-独立验证.md`，2026-10-09 已补回归修复；
* **解析器一变，键也变**：``引擎指纹`` 取 ``parser.py`` / ``model.py`` / ``lexer.py`` /
  ``cache.py`` 的源码内容与 :data:`PARSE_CACHE_FORMAT`；每个进程冻结一次，热改实现须重启。
  **布局版本也进指纹**：``shard-NN.idx`` 里记着
  ``格式``，对不上就整片作废（不试图兼容旧文件）；
* **磁盘层坏了不影响正确性**：读失败 / 反序列化失败 / 结构不对，一律当作未命中
  并删掉那条，然后正常解析；
* **反序列化限制全局对象**：只允许当前模型类，不按缓存中的模块名导入或执行任意函数；
  缓存仍属于本工具的临时目录，内容摘要不认证写入者，不能把第三方缓存当可信证据；
* **身份不对的条目也当作未命中**（:func:`_same_identity`）：本包有 ``pdx`` 与
  ``tools.pdx`` 两个合法导入名，它们各自拥有一套 ``Block`` / ``Assignment`` /
  ``Scalar`` 类对象，而 pickle 按模块名还原。若不管这一层，
  ``isinstance(v, Block)`` 会静默全判否、整棵 AST 被下游过滤掉，
  数字变小却毫无报错 —— 实测把快照的 ``fields`` 域从 27,476 个键打到 4,285。
  判据是「三个类对象是否为同一批」，不看名字；
* **落盘是合并写**：v2 内存里不再持有整片，所以写盘 = 「盘上原有条目（**按字节复制**，
  不解压、不反序列化）+ 本进程新解析的条目」（:func:`_write_shard`）；
* **脏数据先落盘再淘汰**：给「待落盘区」设上限时先把脏片写出去（:func:`_disk_store`），
  绝不为省内存丢掉尚未落盘的写 —— 那是本模块开头承诺「不会发生」的那类失效；
* **写失败静默**：只读文件系统、磁盘满、权限不足都只是「没有磁盘缓存」，
  绝不让缓存故障变成解析故障。

关闭与清理
----------
``V3_PARSE_CACHE=0`` 关闭磁盘层（内存层照旧）；``v3 cache --clear`` 清空磁盘层 ——
含**更早布局**的残留（两位十六进制名的分片目录/文件，里面是 ``<64 位十六进制>.pkl``）：
它们不被 :func:`disk_entries` 认、也不再被任何读数用，但会一直把「缓存目录有多少文件」
这一格抬高一截，所以 :func:`clear_disk` 顺手清掉（判据与实测见那里的 docstring
与 :func:`_is_stale_shard_name`）。
"""

from __future__ import annotations

import atexit
import contextlib
import hashlib
import io
import os
import pickle
import tempfile
import zlib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import cast

from . import config
from .model import Assignment, Block, Node, ParsedFile, Scalar
from .parser import parse_bytes

#: 磁盘缓存的**布局版本**。结构变了、或**文件布局**变了就 +1
#: （v2 = 逐条存储 + 偏移索引，见模块文档「磁盘层的物理布局」）。
#: 与引擎指纹配合：改代码时 mtime 会让旧条目失效，改结构时这里是双保险。
PARSE_CACHE_FORMAT = 2

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

#: **内存层（memo）的条目上限。**
#:
#: 为什么要有上限（2026-09-25，内存优化那一轮）：``functools.cache`` 无上限，
#: 于是一个 worker 只要扫过全树，就会把整棵语的解析结果**永久留在一个进程里** ——
#: 实测 6,252 个结果 ≈ **605.7 MB**（单进程两臂实验的 `retain` 臂）。
#: 定 1024 的取值依据：实测每条约 **0.117 MB** ⇒ 上限约 **120 MB**，
#: 占「每 worker ≤ 512 MiB」这条预算的 1/4，剩下的留给解析结果、分析中间结构与分配器抖动。
#: 再大就顶预算；再小则连「同一个文件在一次运行里被重复请求」都保不住
#: （``cache.py`` 的动机那一节讲的就是这种重复）。跨进程的重复由磁盘层兜住。
MEMO_MAX_ENTRIES = 1_024

#: **待落盘区的条目上限**（未落盘的新解析结果）。
#:
#: 只有「会写盘」的进程需要这块内存（xdist worker 只读、不攒）；
#: 超上限就把脏片先写出去（:func:`_disk_store`），于是常驻量有上界而不是随着
#: 「解析了多少文件」一路涨。取 1024 与内存层同量级（约 120 MB）。
MAX_PENDING_ENTRIES = 1_024

#: 本次进程解析到这个数量才值得写盘（理由见 :func:`flush`）。
MIN_ENTRIES_TO_PERSIST = 200

#: **内存层上限的实验旋钮**（照 :data:`CACHE_ENV` / :data:`WORKER_ENV` 的写法）。
#:
#: 为什么要有它：上限值同时决定**内存**与**速度** —— 上限越小，同一次运行里
#: 同一个文件越可能被再次重新解析（或从磁盘层单条重读）。要判「慢的那部分里
#: 有多少是上限造成的」，就必须能在**不改代码**的前提下把它调大调小。
#:
#: 取值：正整数字符串；``0`` = 无上限（仅实验用）；读不到 / 非法 ⇒ 退回
#: :data:`MEMO_MAX_ENTRIES`。⚠️ **在 import 时读一次** —— ``lru_cache`` 的上限
#: 不能事后修改，所以它只影响「进程起点」，不是运行期开关。
MEMO_ENV = "V3_PARSE_MEMO"


def _memo_maxsize() -> int | None:
    """按 :data:`MEMO_ENV` 决定内存层上限（见那里的 why）。"""
    raw = os.environ.get(MEMO_ENV, "").strip()
    if not raw:
        return MEMO_MAX_ENTRIES
    try:
        value = int(raw)
    except ValueError:
        return MEMO_MAX_ENTRIES
    return value if value > 0 else None


#: 参与「引擎指纹」的模块文件。改了任何一个，整个磁盘缓存自动失效。
_ENGINE_SOURCES = ("parser.py", "model.py", "lexer.py", "cache.py")

#: 一条解析结果里合法的节点类型。**必须是本模块导入的那三个类对象**，
#: 见 :func:`_same_identity` —— 这正是 2026-09-24 那次「同一棵树、两份数字」
#: 事故的判据。
_NODE_TYPES = (Assignment, Block, Scalar)

#: 数据段文件名后缀 / 偏移索引文件名后缀（一片两个文件，见模块文档）。
_DATA_SUFFIX = ".bin"
_INDEX_SUFFIX = ".idx"

#: 索引头里最多允许多少字节（防「坏文件被当成长度巨大的头」把内存吃光）。
_MAX_INDEX_BYTES = 64 * 1024 * 1024


def _same_identity(pf: ParsedFile) -> bool:
    """反序列化出来的节点类，是否就是本模块这一套？若不是，这条缓存不能用。

    为什么需要这一条（真实事故，不是假想）
    ------------------------------------
    本包有**两个合法的导入名**：``pdx``（pytest 的 rootdir 机制把 ``tools/``
    加进 ``sys.path``，于是 ``from pdx import ...`` 到处可用）与 ``tools.pdx``
    （``python -m tools.pdx.cli`` 走这条）。两者都指向同一份源码，但 CPython
    会把它当成**两个模块对象**，于是 ``pdx.model.Block`` 与
    ``tools.pdx.model.Block`` 是**两个互不相认的类**。

    磁盘缓存按模块名 pickle：谁先写进去，后来者就拿到谁的身份。实测后果是
    静默而严重的 —— ``isinstance(v, Block)`` 全判否，于是
    ``snapshot._field_names`` 把整棵 AST 都过滤掉：``fields`` 域从
    27,476 个键掉到 4,285 个，``acceptance_statuses`` 5 个块一个不留，
    ``defines`` 命名空间从 67 掉到 23。**没有任何异常、没有任何日志**，
    只是数字变小了 —— 正是本模块开头承诺「不会发生」的那类失效。

    判据取「三个类对象是否为同一批」而不是比 ``__module__`` 字符串：
    名字可以相同而对象不同（这就是事故本身），身份则不会骗人。

    从根开始迭代检查 Block.items 与 Assignment.value，拒绝外来身份和循环图；
    不使用会先过滤异类节点的 top_assignments 视图建立判据。
    """
    if type(pf) is not ParsedFile or type(getattr(pf, "root", None)) is not Block:
        return False
    stack: list[Node | None] = [pf.root]
    seen: set[int] = set()
    while stack:
        node = stack.pop()
        if node is None:
            continue
        if type(node) not in _NODE_TYPES or id(node) in seen:
            return False
        seen.add(id(node))
        if isinstance(node, Block):
            if not isinstance(getattr(node, "items", None), list):
                return False
            stack.extend(node.items)
        elif isinstance(node, Assignment):
            stack.append(getattr(node, "value", None))
    return True


class _CacheUnpickler(pickle.Unpickler):
    """只恢复本工具的数据类；不按缓存内容导入或调用任意全局对象。"""

    def find_class(self, module: str, name: str) -> type:
        allowed = {item.__name__: item for item in (ParsedFile, Assignment, Block, Scalar)}
        if module == ParsedFile.__module__ and name in allowed:
            return allowed[name]
        raise pickle.UnpicklingError(f"缓存含不允许的全局对象：{module}.{name}")


def _cache_loads(raw: bytes) -> object:
    return _CacheUnpickler(io.BytesIO(raw)).load()


@dataclass
class _DiskState:
    """磁盘层的进程内状态。

    用一个对象而不是几个模块级全局：`global` 语句容易在重构时被漏掉
    （ruff 的 PLW0603 就是冲这个来的），而这里的几个量本来就是一体的 ——
    「待落盘的有哪些、改了哪些片、序号到几、这轮解析了几个文件」。

    ⚠️ **这里装什么，决定了「一个 worker 占多少内存」**（2026-09-25 的内存优化）：

    * ``pending`` 只装**本进程新解析、还没落盘**的条目 —— 旧实现（v1）叫 ``shards``，
      装的是**整片**（读一片就把该片全部条目反序列化并永久留下），
      16 片被碰过就是 20,595 条 / 2402.5 MB；
    * ``indexes`` 装**偏移索引**（指纹 → 偏移/字节数/序号），每片 0.1 MB 量级，
      条目对象**不在这里**，用到哪条才按偏移取哪条。
    """

    #: 本进程新解析、**待落盘**的条目：``{分片号: {指纹: (写入序号, 解析结果)}}``。
    #: 读盘取到的条目**不**进这里（那是 v1 的病根：读一条 = 留一片）。
    pending: dict[int, dict[str, tuple[int, ParsedFile]]] = field(default_factory=dict)
    #: 分片的偏移索引视图：``{分片号: {指纹: (偏移, 字节数, 写入序号)}}``。
    indexes: dict[int, dict[str, tuple[int, int, int]]] = field(default_factory=dict)
    #: 待落盘的分片号。
    dirty: set[int] = field(default_factory=set)
    #: 单调递增的写入序号（瘦身时按「新近」排序用）。
    seq: int = 0
    #: 本次进程真正解析过（未命中）的文件数 —— 决定要不要写盘。
    parsed_total: int = 0


#: 磁盘层的状态（测试通过它模拟「另一个进程」：清空即等于换进程）。
_state = _DiskState()


def _pending_total() -> int:
    """待落盘区一共多少条（用来判要不要先落盘腾地方）。"""
    return sum(len(chunk) for chunk in _state.pending.values())


@lru_cache(maxsize=_memo_maxsize())
def _parse_by_key(key: str, content_digest: str) -> ParsedFile:
    """真正干活的那一层。键必须是 ``str`` —— ``Path`` 与 ``str`` 会算成两条。

    当前内容摘要也是 memo 键的一部分。单独抽一层的原因：``lru_cache`` 按实参做键，若直接装饰
    ``parse_cached``，``Path("a")`` 与 ``"a"`` 会各缓存一份，
    白白解析两次（实测确实如此）。统一在入口处 ``str()`` 化即可避免。

    **上限**（:data:`MEMO_MAX_ENTRIES`）是 2026-09-25 加的：无上限时
    「扫过全树」就等于「把全树的解析结果永久留在这个进程里」（实测 605.7 MB）。
    超上限之后旧条目会被淘汰，重复请求由磁盘层按需单条取回来。
    """
    sig = _signature(key, content_digest=content_digest)
    shard = _shard_of(key)
    if sig is not None:
        hit = _disk_load(sig, shard)
        if hit is not None:
            return hit
    raw = Path(key).read_bytes()
    if hashlib.sha256(raw).hexdigest() != content_digest:
        raise OSError(f"源文件读取期间发生变化，拒绝缓存：{key}")
    parsed = parse_bytes(raw, str(Path(key)))
    if sig is not None:
        _state.parsed_total += 1
        _disk_store(sig, shard, parsed)
    return parsed


def parse_cached(path: str | Path) -> ParsedFile:
    """以当前内容验证 memo 与磁盘命中；原文字节不随 LRU 长期保留。"""
    key = str(path)
    source = Path(key)
    before = source.stat()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    after = source.stat()
    if any(
        getattr(before, attr) != getattr(after, attr)
        for attr in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    ):
        raise OSError(f"源文件读取期间发生变化，拒绝缓存：{key}")
    return _parse_by_key(key, digest)


def clear() -> None:
    """清空**内存**缓存并重置统计。磁盘层不受影响（用 :func:`clear_disk`）。"""
    _parse_by_key.cache_clear()


def memo_maxsize() -> int | None:
    """当前**生效**的内存层上限（``None`` = 无上限）。实验与报告用它记口径。"""
    return _parse_by_key.cache_info().maxsize


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


@lru_cache(maxsize=1)
def _engine_stamp() -> str:
    """本进程加载实现的源码内容指纹；热改源码须重启解释器。"""
    parts = [str(PARSE_CACHE_FORMAT)]
    base = Path(__file__).parent
    for name in _ENGINE_SOURCES:
        try:
            parts.append(f"{name}:{hashlib.sha256((base / name).read_bytes()).hexdigest()}")
        except OSError:  # pragma: no cover - 模块文件必然存在
            parts.append(f"{name}:?")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _signature(path: str, *, content_digest: str | None = None) -> str | None:
    """路径、当前内容与实现指纹；同大小同时间戳的改写也必须失效。"""
    if not _enabled():
        return None
    try:
        digest = content_digest or hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None
    raw = f"{path}\0{digest}\0{_engine_stamp()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _shard_of(path: str) -> int:
    """文件属于哪个分片。**不能用内置 hash()** —— 它带进程随机化，跨进程不稳定。"""
    return int(hashlib.sha256(path.encode("utf-8")).hexdigest()[:8], 16) % SHARDS


def _shard_path(index: int) -> Path:
    """分片的**数据段**（逐条压缩的 pickle 首尾相接）。"""
    return cache_dir() / f"shard-{index:02d}{_DATA_SUFFIX}"


def _index_path(index: int) -> Path:
    """分片的**偏移索引**（指纹 → (偏移, 字节数, 序号)）。"""
    return cache_dir() / f"shard-{index:02d}{_INDEX_SUFFIX}"


def _load_index(index: int) -> dict[str, tuple[int, int, int]]:
    """惰性读一个分片的**偏移索引**（只读索引文件，不碰数据段、不反序列化任何条目）。

    文件不存在 / 坏了 / 格式对不上，一律返回空字典并把这一对文件删掉
    （坏缓存不是错误，重算即可）。
    """
    cached = _state.indexes.get(index)
    if cached is not None:
        return cached
    entries: dict[str, tuple[int, int, int]] = {}
    try:
        index_path = _index_path(index)
        if index_path.stat().st_size > _MAX_INDEX_BYTES:
            raise ValueError("缓存索引过大")
        body = _cache_loads(index_path.read_bytes())
        if isinstance(body, dict) and body.get("格式") == PARSE_CACHE_FORMAT:
            raw = body.get("条目")
            if isinstance(raw, dict):
                entries = {
                    str(sig): (int(meta[0]), int(meta[1]), int(meta[2]))
                    for sig, meta in raw.items()
                    if isinstance(meta, (tuple, list)) and len(meta) == 3
                }
        else:  # 布局/结构版本不同 —— 整片作废，不试图兼容
            _drop_shard_files(index)
    except FileNotFoundError:
        # 没有索引的数据段是**用不了的**（偏移无处可查）：v1 的单文件残留、
        # 或「数据写成功了、索引没写成」的半截写。顺手清掉，免得它一直占着
        # 「分片数」还被当成可用缓存。
        _silent_unlink(_shard_path(index))
    except Exception:  # 坏缓存不是错误，删掉重算即可（含 unpickle 失败）
        _drop_shard_files(index)
    _state.indexes[index] = entries
    return entries


def _read_entry(index: int, meta: tuple[int, int, int], sig: str) -> ParsedFile | None:
    """按索引里的偏移**只读那一条**（这是 v2 布局存在的全部意义），并**验证它确实是那一条**。

    为什么必须验证（2026-09-25 实测踩到，属本模块最贵的一类失效）：
    「索引」与「数据」是**两个文件**，而写盘是「先替换数据、再替换索引」。
    读者若先读了旧索引、再打开**已被替换的新数据文件**，按旧偏移切出来的字节
    可能正好是**另一条**合法的压缩 pickle：`zlib.decompress` 不报错、`pickle.loads`
    也不报错，于是**静默返回了另一棵树的解析结果**。

    真实症状（两处，都是实测）：`test_cache.py::test_缓存不改变全语料的聚合结果`
    两次聚合差 2 个顶层键（85683 vs 85685）；同一条路径还表现为**反常时长**
    （`-n 0` 跑 `test_cache.py` >173 s）与**解析缓存目录秒级缩减**
    （读者把「对不上」的片反复判坏并删掉，与写者互相打架）。

    写入时将包含内容摘要的条目指纹放进 payload，读回必须相等；
    它既防索引/数据错配，也绑定当前入口校验的源内容，不认证缓存写入者。
    对不上 = 这一条不能用（当作未命中），并**只让本进程的索引视图失效**，
    **不去删盘上的文件** —— 删不删是写者的事（见 :func:`_drop_shard_files`）。
    """
    offset, length, _seq = meta
    if offset < 0 or length <= 0:
        return None
    try:
        with _shard_path(index).open("rb") as handle:
            handle.seek(offset)
            blob = handle.read(length)
        if len(blob) != length:
            return None
        payload = _cache_loads(zlib.decompress(blob))
    except Exception:
        return None
    if not (isinstance(payload, tuple) and len(payload) == 3 and payload[0] == sig):
        return None
    entry = payload[2]
    # 这里**故意**不判 ``isinstance(entry, ParsedFile)``：身份错位的形态正是
    # 「长得一样、类不是同一批」，那种条目要由 `_same_identity` 判否并删掉
    # （它才是这条路径的判据，见模块文档的「身份不对的条目也当作未命中」）。
    # 用 isinstance 当第一道闸会把「外来身份」变成「永远未命中且不自愈」。
    return cast("ParsedFile", entry)


def _drop_shard_files(index: int) -> None:
    """让一片作废：**写者**删掉两个文件，**读者只清掉自己的索引视图**。

    为什么读者不许删（2026-09-25 实测）：读者是 16 个 xdist worker 那种只读进程，
    它们**不写盘**（见 :func:`flush`）。若它们也能删共享缓存文件，就会出现
    「一个 worker 判某片对不上 → 删掉 → 别的进程正在写同一片」的互相打架：
    磁盘缓存目录的**文件数与字节数在秒级剧烈缩减**、反复重建，整套因此变慢。
    v1 只有一个文件、且只在 unpickle 失败时才删，所以没暴露这个问题。
    """
    if not _is_xdist_worker():
        _silent_unlink(_index_path(index))
        _silent_unlink(_shard_path(index))
    _state.indexes[index] = {}


def _disk_load(sig: str, shard: int) -> ParsedFile | None:
    """按**世代键**取一条；取不到、或取到的**不是同一套类**时返回 ``None``。

    身份不对的那条会被就地删掉：它永远不会变对，留着只会让同一个文件
    在每次运行里都被判一次否（而且它对应的正是「另一套导入名」写下的
    结果，下一次同名的调用者还会撞上）。删掉之后这一轮照常解析并重新
    入库 —— 缓存自愈，不需要人工 ``v3 cache --clear``。

    查找顺序：**待落盘区**（本进程刚解析的）→ **盘上那条**（按偏移单条取）。
    取到的条目**不会**被留进 ``_state``（它就是内存层的活）；
    v1 那种「读一条 = 整片常驻」的做法正是这次要修的病。
    """
    pending = _state.pending.get(shard)
    if pending is not None:
        entry = pending.get(sig)
        if entry is not None:
            pending_tree: ParsedFile = entry[1]
            if _same_identity(pending_tree):
                return pending_tree
            del pending[sig]
            _state.dirty.add(shard)
            return None

    meta = _load_index(shard).get(sig)
    if meta is None:
        return None
    parsed: ParsedFile | None = _read_entry(shard, meta, sig)
    if parsed is None:
        # 判据自证对不上（见 _read_entry：索引与数据来自两次不同的盘状态）
        # ⇒ 这条不能用，**只让本进程的索引视图失效**、当作未命中，别删别人的文件。
        _drop_shard_files(shard)
        return None
    if not _same_identity(parsed):
        # 身份不对（另一套导入名写下的结果）：只丢那一条，同 v1 的判据与动作。
        _state.indexes.get(shard, {}).pop(sig, None)
        _state.dirty.add(shard)
        return None
    return parsed


def _disk_store(sig: str, shard: int, parsed: ParsedFile) -> None:
    """放一条进**待落盘区**（不立即落盘 —— 进程退出时统一 flush）。

    与 v1 的差别是这次省内存的关键之一：v1 把「本进程解析的」和「盘上原有的整片」
    混在同一个字典里（于是内存里同时躺着整棵树）；v2 只留本进程新解析、还没落盘的那些，
    并且给它一个显式上限（:data:`MAX_PENDING_ENTRIES`）—— 到上限就**先把脏片写出去**，
    而不是把写丢掉（丢掉未落盘的写是本模块最贵的一类 bug）。
    """
    _state.seq += 1
    _state.pending.setdefault(shard, {})[sig] = (_state.seq, parsed)
    _state.dirty.add(shard)
    if _pending_total() < MAX_PENDING_ENTRIES:
        return
    if flush(force=True) == 0:
        # 写不出去（xdist worker 只读 / 盘不可用）：攒着也不会落盘，直接放下，
        # 免得「解析了多少文件」把常驻量一路推上去。
        _state.pending.clear()
        _state.dirty.clear()


def _write_shard(index: int) -> bool:
    """把一个脏片写回盘：**盘上原有条目（按字节复制）+ 本进程新解析的条目**。

    三个要点：

    * 旧条目**只搬字节**（它们已经是逐条压缩的），不解压、不反序列化 ——
      合并的成本与「读一片」无关；
    * 瘦身：条目数超过 :data:`MAX_ENTRIES_PER_SHARD` 时按写入序号丢最旧的
      （旧指纹永远命中不了，只是占地方）；
    * 写失败（只读盘 / 磁盘满 / 权限）只是「这一片没写成功」，绝不影响解析。

    先写数据段、再写索引，两个都用 tmp + ``os.replace``。中间崩了会留下
    「索引与数据对不上」的一对文件 —— 下次读到的条目对不上就整片作废
    （见 :func:`_disk_load`），自愈。
    """
    path = _shard_path(index)
    index_path = _index_path(index)
    old = dict(_load_index(index))
    pending = dict(_state.pending.get(index) or {})

    # 合并顺序表：旧条目（没被本次覆盖的）+ 新条目
    order: dict[str, int] = {sig: meta[2] for sig, meta in old.items() if sig not in pending}
    order.update({sig: seq for sig, (seq, _obj) in pending.items()})
    if len(order) > MAX_ENTRIES_PER_SHARD:
        newest = sorted(order, key=order.__getitem__)[-MAX_ENTRIES_PER_SHARD:]
        order = {sig: order[sig] for sig in newest}

    tmp_data = path.with_suffix(f".{os.getpid()}.bin.tmp")
    tmp_index = index_path.with_suffix(f".{os.getpid()}.idx.tmp")
    entries: dict[str, tuple[int, int, int]] = {}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        cursor = 0
        src = None
        try:
            src = path.open("rb")
        except OSError:
            src = None  # 没有旧数据段（第一次写）：旧条目只能放弃
        try:
            with tmp_data.open("wb") as dst:
                for sig, seq in order.items():
                    if sig in pending:
                        # payload = (本条自己的**世代键**, 写入序号, 解析结果)：
                        # 那把键是**读回来时的世代自证**（见 _read_entry），
                        # 没有它，索引/数据两次盘状态的错位会静默换成另一棵树。
                        blob = zlib.compress(
                            pickle.dumps(
                                (sig, pending[sig][0], pending[sig][1]),
                                protocol=pickle.HIGHEST_PROTOCOL,
                            ),
                            1,
                        )
                    else:
                        meta = old[sig]
                        if src is None:
                            continue
                        src.seek(meta[0])
                        blob = src.read(meta[1])
                        if len(blob) != meta[1]:  # 旧文件被截断：这条不要了
                            continue
                    dst.write(blob)
                    entries[sig] = (cursor, len(blob), seq)
                    cursor += len(blob)
        finally:
            if src is not None:
                src.close()
        tmp_index.write_bytes(
            pickle.dumps(
                {"格式": PARSE_CACHE_FORMAT, "条目": entries},
                protocol=pickle.HIGHEST_PROTOCOL,
            )
        )
        tmp_data.replace(path)
        tmp_index.replace(index_path)
    except Exception:  # 缓存写失败不能影响解析（只读盘 / 磁盘满 / 权限）
        _silent_unlink(tmp_data)
        _silent_unlink(tmp_index)
        return False
    _state.indexes[index] = entries
    return True


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

    ⚠️ 落到盘上的只有「本进程新解析的」那些条目（v2 不再在内存里持有整片），
    写的时候与盘上原有条目**合并**（见 :func:`_write_shard`），所以不会把别人的
    条目冲掉。
    """
    if not _enabled() or _is_xdist_worker():
        return 0
    if not force and _state.parsed_total < MIN_ENTRIES_TO_PERSIST:
        return 0
    written = 0
    for index in sorted(_state.dirty):
        if _write_shard(index):
            _state.pending.pop(index, None)
            written += 1
    _state.dirty.clear()
    return written


def _silent_unlink(path: Path) -> None:
    with contextlib.suppress(OSError):  # 并发删同一个文件
        path.unlink()


def disk_entries() -> list[tuple[Path, float, int]]:
    """磁盘缓存分片：``[(数据段路径, mtime, 字节), …]``（目录不存在时为空）。

    ``字节`` 是该片的**索引 + 数据**合计（一片两个文件，见模块文档）。
    """
    base = cache_dir()
    out: list[tuple[Path, float, int]] = []
    if not base.is_dir():
        return out
    for path in sorted(base.glob(f"shard-*{_DATA_SUFFIX}")):
        try:
            st = path.stat()
        except OSError:  # pragma: no cover - 并发删除
            continue
        size = st.st_size
        with contextlib.suppress(OSError):
            size += path.with_suffix(_INDEX_SUFFIX).stat().st_size
        out.append((path, st.st_mtime, size))
    return out


def disk_counts() -> dict[str, int]:
    """磁盘缓存里**可命中的条目数**（分片数 / 条目数 / 字节）。

    与「分片文件数」不同：分片里可能留着**源文件已变（世代键对不上）**的旧条目，
    那些永远命中不了，只是等下次 flush 时被瘦身掉。

    ⚠️ 2026-09-25 起它**只读索引**：旧实现为了数条目会把 16 片全部反序列化
    （实测顺手把 2.4 GB 装进内存，`v3 cache` 一条查询就能顶起一整个进程），
    现在读的是 ``shard-NN.idx``（每片 0.1 MB 量级）。
    """
    files = disk_entries()
    entries = 0
    for index in range(SHARDS):
        if _index_path(index).is_file():
            entries += len(_load_index(index))
    return {
        "分片": len(files),
        "条目": entries,
        "字节": sum(size for _p, _m, size in files),
    }


def _is_stale_shard_name(name: str) -> bool:
    """**更早布局**的分片名：两位十六进制、无后缀（``00``…``ff``）。

    2026-09-25 实测共享桶里还留着 **193 个**这样的条目（mtime 2026-09-19）——
    它们是**目录**（每片一个目录，里面装 64 位十六进制名 + ``.pkl`` 的旧条目，
    合计 368 个 ``.pkl`` / 约 3.5 MB）：既不被 :func:`disk_entries` 认、原先也不被
    :func:`clear_disk` 删 ⇒ ``v3 cache --clear`` 清不掉，任何「缓存目录有多少文件」
    的读数都被抬高一截（取证：`docs/reports/缓存跨代读-独立验证.md` §6.2）。
    判据取**名字形状**，不是「凡不认识的都删」：桶是我们自己的
    （``v3-parse-cache-<hash>``），但只删能认出是**旧分片命名**的那些。
    """
    return len(name) == 2 and all(char in "0123456789abcdef" for char in name)


def _is_legacy_entry_name(name: str) -> bool:
    """更早布局的**条目**名：一串小写十六进制 + ``.pkl``。

    实测共享桶里那 368 个全是 **62 位**十六进制（`t59` 现读；t54 报告只按「无后缀」记过它们，
    那其实是**目录**在 `glob('*')` 下的样子）。这里用 32–64 的区间而不是写死 62：
    这一族的键长可能随版本变过，名字要认的是「十六进制摘要」这个**形状**。
    """
    stem, dot, suffix = name.partition(".")
    return (
        dot == "."
        and suffix == "pkl"
        and 32 <= len(stem) <= 64
        and all(char in "0123456789abcdef" for char in stem)
    )


def _is_legacy_shard_dir(path: Path) -> bool:
    """更早布局的分片**目录**：名字是两位十六进制，里面装的全是旧条目名。

    里面**空**也算（清到一半的旧目录同样是残留）。认不出内容形状的一律返回 ``False``
    —— 宁可不删，也不碰不是我们写的东西。
    """
    if not path.is_dir() or not _is_stale_shard_name(path.name):
        return False
    try:
        kids = list(path.iterdir())
    except OSError:  # pragma: no cover - 并发删掉
        return False
    if not kids:
        return True
    return all(kid.is_file() and _is_legacy_entry_name(kid.name) for kid in kids)


def clear_disk() -> int:
    """清空磁盘缓存（分片文件全删 + 内存里的索引视图与待落盘区也清），返回删掉的分片数。

    顺手清掉**更早布局**的残留（两位十六进制名的文件或目录，判据见
    :func:`_is_stale_shard_name` / :func:`_is_legacy_shard_dir`）—— 它们不计入返回值
    （返回值仍是**数据段分片**数），但清完「缓存目录文件数」这一格才等于真实占用。
    """
    files = disk_entries()
    for path, _mtime, _size in files:
        _silent_unlink(path)
    base = cache_dir()
    if base.is_dir():
        for stray in base.glob(f"shard-*{_INDEX_SUFFIX}"):
            _silent_unlink(stray)
        try:
            bucket = list(base.iterdir())
        except OSError:  # pragma: no cover - 桶被并发删掉
            bucket = []
        for old in bucket:
            if not _is_stale_shard_name(old.name):
                continue
            if old.is_file():
                _silent_unlink(old)
            elif _is_legacy_shard_dir(old):
                for entry in list(old.iterdir()):  # 里面全是旧条目 .pkl
                    _silent_unlink(entry)
                with contextlib.suppress(OSError):
                    old.rmdir()
    _state.pending.clear()
    _state.indexes.clear()
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
