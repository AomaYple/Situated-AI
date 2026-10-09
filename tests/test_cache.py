"""缓存透明性测试。

要证明的性质
------------
``parse_cached`` 对调用方必须**完全等价于** ``parse_file``：
返回同样的内容，且不因缓存状态而产生可观察差异。
这条一旦破了，全量分析的数字就会随「跑第几遍」而变 —— 那是最难查的一类 bug。

另外钉住 :mod:`pdx.cache` 的命中率统计口径，因为剖析结论依赖它。
"""

from __future__ import annotations

import os
import pickle
import zlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest
from _helpers import signature

from pdx import cache
from pdx.model import Assignment, Block, ParsedFile, Scalar
from pdx.parser import parse_file

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

# 一段覆盖主要语法形态的小脚本
_SAMPLE = """\
@base = 10
NCountry = {
    tax = 0.2
    list = { a b c }
}
Foo = { x = @base }
REPLACE:Bar = { y = 1 }
INJECT:Baz = { z = { } }
"quoted key" = 1
bare_scalar
"""


@pytest.fixture(autouse=True)
def _fresh_cache():
    """每条用例都从空缓存开始，杜绝用例间隐式依赖。"""
    cache.clear()
    yield
    cache.clear()


def _reset_disk_state() -> None:
    """模拟「另一个进程」：内存层、索引视图与待落盘区都丢掉，只剩磁盘上的文件。"""
    cache.clear()
    cache._state.pending.clear()
    cache._state.indexes.clear()
    cache._state.dirty.clear()
    cache._state.parsed_total = 0
    cache._state.seq = 0


def _same_shard_paths(root: Path, count: int) -> list[Path]:
    """造出 ``count`` 个**落在同一分片**的文件路径。

    分片号是「路径的 sha256 取模」，不能假定相邻文件在同一片 ——
    想要「一片里有好几条」就必须按哈希凑。
    """
    out: list[Path] = []
    index = 0
    while len(out) < count:
        path = root / f"s{index}.txt"
        if not out or cache._shard_of(str(path)) == cache._shard_of(str(out[0])):
            out.append(path)
        index += 1
    return out


@dataclass
class _LookalikeBlock:
    """长得像 ``Block`` 的替身 —— 只换**叶子**的类，容器仍用真的 ``Block`` / ``Assignment``。

    必须是**模块级**的类：身份判据要连着「盘上往返」一起测，而函数内定义的局部类
    ``pickle`` 不了（实测：``_write_shard`` 会静默返回 False，flush 计数变 0 ——
    写这条用例时先踩过一次）。
    """

    items: list = field(default_factory=list)
    line: int = 0


def _lookalike_tree(path: Path) -> ParsedFile:
    """构造一棵**长得一样、类却不一样**的树（双模块身份造成的形态）。

    ⚠️ 容器必须用真的 ``Block`` / ``Assignment``：``top_assignments()`` 自带
    ``isinstance(a, Assignment)`` 过滤，连赋值语句都用替身类的话它会筛出空列表，
    判据就恒真了（写这条用例时先踩过一次）。
    """
    return ParsedFile(
        path=str(path),
        # 这一处**故意**违反类型：替身类就是被测对象，改成真 Block 就测不到身份判据了
        root=Block(items=[Assignment("nope", "=", _LookalikeBlock())]),  # type: ignore[arg-type]
    )


@pytest.fixture
def disk_dir(tmp_path, monkeypatch):
    """把磁盘缓存指到临时目录，别动本机那份真缓存。

    同时**清掉 xdist worker 标记**：整套测试默认并行跑，而 worker 进程按设计
    只读不写（见 `cache.flush`），不清掉的话「写盘」相关的用例全都测不到东西。
    需要验证「worker 不写」的用例自己把变量设回去。
    """
    target = tmp_path / "cache"
    monkeypatch.setattr(cache, "cache_dir", lambda: target)
    monkeypatch.delenv(cache.WORKER_ENV, raising=False)
    _reset_disk_state()
    yield target
    _reset_disk_state()


def test_缓存命中返回同一对象(tmp_path) -> None:
    p = tmp_path / "a.txt"
    p.write_text(_SAMPLE, encoding="utf-8")
    first = cache.parse_cached(p)
    second = cache.parse_cached(p)
    assert first is second, "第二次应直接返回缓存里的同一对象"


@pytest.mark.parametrize("disk_enabled", [True, False])
def test_同进程等长复原时间戳改写必须失效(tmp_path, disk_dir, monkeypatch, disk_enabled):
    monkeypatch.setenv(cache.CACHE_ENV, "1" if disk_enabled else "0")
    path = tmp_path / "changing.txt"
    path.write_bytes(b"before = 1\n")
    first = cache.parse_cached(path)
    previous = path.stat()
    path.write_bytes(b"after_ = 2\n")
    os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    second = cache.parse_cached(path)
    assert first.top_keys == ["before"]
    assert second.top_keys == ["after_"]
    assert second is not first
    path.unlink()
    with pytest.raises(FileNotFoundError):
        cache.parse_cached(path)


def test_身份判据拒绝外来根和深层外来值(tmp_path):
    # 故意破坏模型类型契约，验证运行时的深层身份防线。
    foreign_root = ParsedFile(path="root", root=cast("Block", _LookalikeBlock()))
    assert not cache._same_identity(foreign_root)
    nested = ParsedFile(
        path="nested",
        root=Block(
            items=[
                Assignment(
                    "a", "=", Block(items=[Assignment("b", "=", cast("Block", _LookalikeBlock()))])
                )
            ]
        ),
    )
    assert not cache._same_identity(nested)


def _write_pickle_marker(path):
    from pathlib import Path

    Path(path).write_text("executed", encoding="utf-8")
    return {}


class _UnsafeCachePayload:
    def __init__(self, marker):
        self.marker = str(marker)

    def __reduce__(self):
        return _write_pickle_marker, (self.marker,)


@pytest.mark.parametrize("location", ["index", "entry"])
def test_缓存反序列化不得执行任意全局函数(tmp_path, disk_dir, location):
    marker = tmp_path / "side-effect.txt"
    disk_dir.mkdir()
    path = tmp_path / "source.txt"
    path.write_bytes(b"valid = 1\n")
    sig = cache._signature(str(path))
    shard = cache._shard_of(str(path))
    if location == "index":
        cache._index_path(shard).write_bytes(pickle.dumps(_UnsafeCachePayload(marker)))
    else:
        blob = zlib.compress(pickle.dumps((sig, 1, _UnsafeCachePayload(marker))))
        cache._shard_path(shard).write_bytes(blob)
        cache._index_path(shard).write_bytes(
            pickle.dumps({"格式": cache.PARSE_CACHE_FORMAT, "条目": {sig: (0, len(blob), 1)}})
        )
    assert cache.parse_cached(path).top_keys == ["valid"]
    assert not marker.exists()


def test_缓存结果与直连解析逐字段一致(tmp_path) -> None:
    p = tmp_path / "a.txt"
    p.write_text(_SAMPLE, encoding="utf-8")
    cached = cache.parse_cached(p)
    direct = parse_file(p)
    assert signature(cached) == signature(direct)
    assert cached.had_bom == direct.had_bom
    assert cached.errors == direct.errors
    assert cached.path == direct.path


def test_清空缓存后结果不变(tmp_path) -> None:
    p = tmp_path / "a.txt"
    p.write_text(_SAMPLE, encoding="utf-8")
    before = signature(cache.parse_cached(p))
    cache.clear()
    after = signature(cache.parse_cached(p))
    assert before == after


def test_不同路径不互相污染(tmp_path) -> None:
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("alpha = 1\n", encoding="utf-8")
    b.write_text("beta = 2\n", encoding="utf-8")
    assert signature(cache.parse_cached(a)) != signature(cache.parse_cached(b))
    assert {x.key for x in cache.parse_cached(a).top_assignments} == {"alpha"}
    assert {x.key for x in cache.parse_cached(b).top_assignments} == {"beta"}


def test_命中率统计正确(tmp_path) -> None:
    p = tmp_path / "a.txt"
    p.write_text(_SAMPLE, encoding="utf-8")
    cache.parse_cached(p)  # 未命中
    cache.parse_cached(p)  # 命中
    cache.parse_cached(p)  # 命中
    assert cache.stats() == {"条目": 1, "命中": 2, "未命中": 1}


def test_字符串与Path两种键形式等价(tmp_path) -> None:
    """``parse_cached`` 内部按 ``str(path)`` 建键，两种写法必须指向同一条目。

    这条曾经会失败：若直接把 ``lru_cache`` 装饰在 ``parse_cached`` 上，
    ``Path("a")`` 与 ``"a"`` 是两个不同的键，同一个文件会被解析两遍。
    """
    p = tmp_path / "a.txt"
    p.write_text(_SAMPLE, encoding="utf-8")
    a = cache.parse_cached(p)
    b = cache.parse_cached(str(p))
    assert a is b
    assert cache.stats()["条目"] == 1, "两种写法不应各占一条缓存"


def test_clear同时清零计数(tmp_path) -> None:
    p = tmp_path / "a.txt"
    p.write_text(_SAMPLE, encoding="utf-8")
    cache.parse_cached(p)
    cache.clear()
    assert cache.stats() == {"条目": 0, "命中": 0, "未命中": 0}


# ── 身份判据（2026-09-24 那次「同一棵树、两份数字」事故的回归）──


def test_自己解析出来的结果通过身份判据(tmp_path) -> None:
    p = tmp_path / "a.txt"
    p.write_text(_SAMPLE, encoding="utf-8")
    assert cache._same_identity(parse_file(p)) is True


def test_外来身份的解析结果要被判否(tmp_path) -> None:
    """构造一棵**长得一样、类却不一样**的树 —— 正是双模块身份造成的形态。

    ``pdx`` 与 ``tools.pdx`` 都指向同一份源码（pytest 的 rootdir 机制让前者
    可用，``python -m tools.pdx.cli`` 走后者），于是 ``Block`` 有两个互不相认
    的类对象，而磁盘缓存按模块名 pickle。后果不是报错而是**静默变小**：
    ``isinstance(v, Block)`` 全判否，``snapshot._field_names`` 把整棵 AST
    过滤掉（``fields`` 域 27,476 → 4,285 个键）。所以判据必须是「类对象是不是
    同一批」，比 ``__module__`` 字符串会被名字骗过去。
    """
    assert cache._same_identity(_lookalike_tree(tmp_path / "a.txt")) is False


def test_身份不对的缓存条目被丢弃并重算(tmp_path) -> None:
    """磁盘上那条身份不对的条目必须**被删掉**，而不是每次运行都被判否一遍。

    同时验证自愈：删掉之后这一轮照常解析，拿到的还是正确结果。
    """
    p = tmp_path / "a.txt"
    p.write_text(_SAMPLE, encoding="utf-8")
    good = parse_file(p)
    sig = cache._signature(str(p))
    assert sig is not None
    shard = cache._shard_of(str(p))

    cache._disk_store(sig, shard, _lookalike_tree(p))
    assert cache._disk_load(sig, shard) is None, "身份不对的条目必须当作未命中"
    assert sig not in cache._state.pending[shard], "而且要从待落盘区里删掉（否则每轮都白判一次）"

    cache._disk_store(sig, shard, good)
    assert cache._disk_load(sig, shard) is not None
    assert signature(cache.parse_cached(p)) == signature(good)


def test_盘上身份不对的条目也要被丢掉(tmp_path, disk_dir) -> None:
    """落盘之后再读到身份不对的条目，要**从索引里删掉**（v1 的行为在 v2 下落到了盘上）。"""
    p = tmp_path / "a.txt"
    p.write_text(_SAMPLE, encoding="utf-8")
    sig = cache._signature(str(p))
    assert sig is not None
    shard = cache._shard_of(str(p))

    cache._disk_store(sig, shard, _lookalike_tree(p))
    assert cache.flush(force=True) == 1
    _reset_disk_state()

    assert cache._disk_load(sig, shard) is None, "盘上那条身份不对，必须判未命中"
    assert sig not in cache._state.indexes.get(shard, {}), "坏条目或其索引视图必须失效"
    assert cache._state.parsed_total == 0, "这一步不该触发真正的解析"

    # 随后照常解析并入库，缓存自愈
    pf = cache.parse_cached(p)
    assert pf.top_keys, "自愈之后仍应解析出内容"


# ── v2 布局：内存里留什么（2026-09-25 内存优化那一轮的回归）──


def test_读一条不把整片装进内存(tmp_path, disk_dir) -> None:
    """**核心不变式**：读盘取一条，不许把整片条目材料化并留在内存里。

    旧实现（v1）的 ``_load_shard()`` 为查一条把整片解压 + 反序列化，并永久留在
    ``_state.shards`` 里 —— 实测 16 片全被碰过就是 **20,595 条 / 2402.5 MB**
    （占一个 worker 峰值的 86%）。现在内存里只该有：偏移索引 + 本进程新解析的待落盘条目。
    """
    paths = _same_shard_paths(tmp_path, 12)
    for i, path in enumerate(paths):
        path.write_text(f"k{i} = {i}\n", encoding="utf-8")
        cache.parse_cached(path)
    shard = cache._shard_of(str(paths[0]))
    assert cache.flush(force=True) == 1, "同一片的 12 条应当只写一片"
    _reset_disk_state()

    assert cache.parse_cached(paths[0]).top_keys == ["k0"]
    assert cache._state.pending.get(shard, {}) == {}, "读盘取到的条目不进待落盘区"
    index = cache._state.indexes[shard]
    assert len(index) == 12, "索引里记着整片的键"
    assert all(len(meta) == 3 for meta in index.values()), "每条只留 (偏移, 字节数, 序号)"
    assert not any(hasattr(meta, "top_keys") for meta in index.values()), "索引里不许有解析结果"


def test_内存层有上限(tmp_path, disk_dir) -> None:
    """内存层（``lru_cache``）必须**有界**：无界时「扫过全树」= 永久留住全树的解析结果。

    实测口径（t11 的两臂实验）：6,252 个结果全留住 ≈ 605.7 MB；
    所以上限按 :data:`cache.MEMO_MAX_ENTRIES` 卡住，超出部分由磁盘层按需单条取回。
    """
    count = cache.MEMO_MAX_ENTRIES + 8
    paths = []
    for i in range(count):
        path = tmp_path / f"m{i}.txt"
        path.write_text(f"k{i} = {i}\n", encoding="utf-8")
        paths.append(path)
        cache.parse_cached(path)

    assert cache.stats()["条目"] == cache.MEMO_MAX_ENTRIES, "条目数必须被上限卡住"
    assert (
        sum(len(chunk) for chunk in cache._state.pending.values()) <= cache.MAX_PENDING_ENTRIES
    ), "待落盘区也必须被上限卡住（到上限先落盘，而不是丢写）"
    assert cache.parse_cached(paths[0]).top_keys == ["k0"], "被淘汰后再读仍要拿到正确结果"


def test_待落盘区到上限先落盘而不是丢写(tmp_path, disk_dir, monkeypatch) -> None:
    """上限生效的方式是**先把脏片写出去**，不是把没落盘的写丢掉。

    丢掉未落盘的写会静默退化：内存降了、结果也对，只是缓存永远不生效
    —— 那正是 ``cache.py`` 开头承诺「不会发生」的那类失效。
    """
    monkeypatch.setattr(cache, "MAX_PENDING_ENTRIES", 4)
    paths = _same_shard_paths(tmp_path, 6)
    for i, path in enumerate(paths):
        path.write_text(f"k{i} = {i}\n", encoding="utf-8")
        cache.parse_cached(path)

    assert sum(len(chunk) for chunk in cache._state.pending.values()) <= 4
    _reset_disk_state()
    counts = cache.disk_counts()
    assert counts["条目"] >= 4, f"触顶时写出去的条目不许丢，实得 {counts}"


def test_落盘是合并写_旧条目不会被冲掉(tmp_path, disk_dir) -> None:
    """v2 里内存不再持有整片，所以写盘必须把**盘上原有的**条目按字节带过去。

    这条守的是一个很隐蔽的退化：只写「本进程新解析的」，旧条目会**静默消失** ——
    缓存文件还在、结果也对，只是每次都重新解析（速度账），没人会发现。
    """
    paths = _same_shard_paths(tmp_path, 2)
    for i, path in enumerate(paths):
        path.write_text(f"k{i} = {i}\n", encoding="utf-8")

    cache.parse_cached(paths[0])
    assert cache.flush(force=True) == 1
    _reset_disk_state()

    # 第二个「进程」：只解析第二个文件，然后落盘 —— 第一个文件的条目在盘上
    cache.parse_cached(paths[1])
    assert cache.flush(force=True) == 1
    _reset_disk_state()

    assert cache.disk_counts()["条目"] == 2, "两轮写的条目都要在（合并写没把旧的冲掉）"
    assert cache.parse_cached(paths[0]).top_keys == ["k0"]
    assert cache.parse_cached(paths[1]).top_keys == ["k1"]
    assert cache._state.parsed_total == 0, "两条都该命中盘，不该重新解析"


def test_磁盘统计不把条目装进内存(tmp_path, disk_dir) -> None:
    """``disk_counts()`` 只读 ``.idx``：旧实现会把 16 片全部反序列化（顺手装 2.4 GB）。"""
    paths = _same_shard_paths(tmp_path, 4)
    for i, path in enumerate(paths):
        path.write_text(f"k{i} = {i}\n", encoding="utf-8")
        cache.parse_cached(path)
    assert cache.flush(force=True) == 1
    _reset_disk_state()

    assert cache.disk_counts()["条目"] == 4
    assert cache._state.pending == {}, "数条目不该把条目录进待落盘区"
    assert cache.stats()["条目"] == 0, "也不该碰内存层"
    assert len(cache._state.indexes[cache._shard_of(str(paths[0]))]) == 4


def test_旧布局的分片整片作废(tmp_path, disk_dir) -> None:
    """布局版本进了 ``格式`` 字段：对不上就整片作废（不试图兼容 v1 的单文件）。"""
    p = tmp_path / "a.txt"
    p.write_text(_SAMPLE, encoding="utf-8")
    sig = cache._signature(str(p))
    assert sig is not None
    shard = cache._shard_of(str(p))
    cache.cache_dir().mkdir(parents=True, exist_ok=True)  # 手工造文件前先把桶建出来

    # v1 的单文件残留：没有 .idx，.bin 里是旧格式
    cache._shard_path(shard).write_bytes(
        zlib.compress(pickle.dumps({"格式": 1, "条目": {sig: (1, None)}}), 1)
    )
    assert cache._disk_load(sig, shard) is None
    assert not cache._shard_path(shard).is_file(), (
        "用不了的数据段要顺手清掉（否则它一直占着分片数）"
    )

    # 索引存在但格式对不上：同样整片作废
    cache._shard_path(shard).write_bytes(b"")
    cache._index_path(shard).write_bytes(pickle.dumps({"格式": 0, "条目": {}}))
    cache._state.indexes.clear()
    assert cache._disk_load(sig, shard) is None
    assert not cache._index_path(shard).is_file()


@pytest.mark.integration
def test_真实语料上缓存与直连完全一致(corpus_files) -> None:
    """全语料逐个比对 —— 缓存绝不能改变任何文件的结果。"""
    if not corpus_files:
        pytest.skip("语料不可用")
    for p in corpus_files:
        direct = parse_file(p)
        cached = cache.parse_cached(p)
        assert signature(cached) == signature(direct), f"{p} 缓存与直连结果不同"
    # 第二遍应当全部命中
    cache.clear()
    for p in corpus_files:
        cache.parse_cached(p)
    stats = cache.stats()
    assert stats["未命中"] == len(corpus_files)


@pytest.mark.integration
@pytest.mark.slow
def test_缓存不改变全语料的聚合结果(corpus_texts) -> None:
    """更强的性质：算出来的**聚合数字**也不受缓存影响。

    单文件一致还不够 —— 若缓存把对象返回错位（例如路径键冲突），
    单看某个文件可能仍然「碰巧一致」，但聚合起来就露馅。
    """
    if not corpus_texts:
        pytest.skip("语料不可用")

    def aggregate() -> dict[str, int]:
        keys: set[str] = set()
        entries = 0
        for path, _text in corpus_texts:
            pf = cache.parse_cached(path)
            keys.update(pf.top_keys)
            entries += len(pf.top_keys)
        return {"去重顶层键": len(keys), "顶层键总数": entries}

    cache.clear()
    cold = aggregate()
    warm = aggregate()  # 这一遍几乎全命中
    assert cold == warm


# ────────────────────────── 磁盘层 ──────────────────────────


def test_磁盘层跨进程可用(tmp_path, disk_dir) -> None:
    """第一遍写盘、第二遍（模拟新进程）应当**不再解析**就从磁盘拿到结果。"""
    p = tmp_path / "a.txt"
    p.write_text(_SAMPLE, encoding="utf-8")
    first = cache.parse_cached(p)
    assert cache.flush(force=True) == 1, "强制 flush 应写出一个分片"

    _reset_disk_state()
    second = cache.parse_cached(p)
    assert cache._state.parsed_total == 0, "这一遍不应真的解析文件"
    assert signature(second) == signature(first)


def test_源文件一变缓存就失效(tmp_path, disk_dir) -> None:
    """键里带 mtime 与 size，所以改写文件后必须重新解析。"""
    p = tmp_path / "a.txt"
    p.write_text("alpha = 1\n", encoding="utf-8")
    cache.parse_cached(p)
    cache.flush(force=True)
    _reset_disk_state()

    p.write_text("beta = 2\n", encoding="utf-8")
    pf = cache.parse_cached(p)
    assert {x.key for x in pf.top_assignments} == {"beta"}
    assert cache._state.parsed_total == 1, "内容变了就该重新解析"


def test_坏分片不影响解析(tmp_path, disk_dir) -> None:
    """缓存文件损坏只是未命中，绝不能让解析失败。"""
    p = tmp_path / "a.txt"
    p.write_text(_SAMPLE, encoding="utf-8")
    cache.parse_cached(p)
    cache.flush(force=True)

    shard = next(disk_dir.glob("shard-*.bin"))
    shard.write_bytes(b"not a pickle at all")
    _reset_disk_state()

    pf = cache.parse_cached(p)
    assert pf.top_keys, "坏缓存之后仍应解析出内容"
    assert cache._state.parsed_total == 1


def test_环境变量可关闭磁盘层(tmp_path, disk_dir, monkeypatch) -> None:
    """``V3_PARSE_CACHE=0`` 时只走内存层，也不写盘。"""
    monkeypatch.setenv(cache.CACHE_ENV, "0")
    p = tmp_path / "a.txt"
    p.write_text(_SAMPLE, encoding="utf-8")
    cache.parse_cached(p)
    assert cache.flush(force=True) == 0
    assert not list(disk_dir.glob("shard-*.bin"))
    assert cache.disk_counts()["条目"] == 0


def test_小任务默认不写盘(tmp_path, disk_dir) -> None:
    """低于阈值的一次解析不值得付写盘成本（实测见 ``cache.flush`` 的说明）。"""
    p = tmp_path / "a.txt"
    p.write_text(_SAMPLE, encoding="utf-8")
    cache.parse_cached(p)
    assert cache.flush() == 0, "解析量低于阈值时不该写盘"


def test_xdist的worker只读不写(tmp_path, disk_dir, monkeypatch) -> None:
    """16 个 worker 各写一遍同一批分片会把整套测试拖垮（实测 4 分钟 → 20 分钟以上）。"""
    monkeypatch.setenv(cache.WORKER_ENV, "gw3")
    p = tmp_path / "a.txt"
    p.write_text(_SAMPLE, encoding="utf-8")
    cache.parse_cached(p)
    assert cache.flush(force=True) == 0, "worker 进程不该写盘"
    assert not list(disk_dir.glob("shard-*.bin"))
    assert cache.describe_state().startswith("只读")


def test_清理磁盘缓存(tmp_path, disk_dir) -> None:
    p = tmp_path / "a.txt"
    p.write_text(_SAMPLE, encoding="utf-8")
    cache.parse_cached(p)
    cache.flush(force=True)
    assert cache.disk_counts()["条目"] == 1

    assert cache.clear_disk() == 1
    assert cache.disk_counts() == {"分片": 0, "条目": 0, "字节": 0}


def test_分片函数跨进程稳定() -> None:
    """分片号必须可复现 —— 用内置 ``hash()`` 会带进程随机化，那是隐蔽的 bug。"""
    assert cache._shard_of("game/events/foo.txt") == cache._shard_of("game/events/foo.txt")
    assert 0 <= cache._shard_of("x") < cache.SHARDS


def test_磁盘统计与清空对得上(tmp_path, disk_dir) -> None:
    for i in range(3):
        p = tmp_path / f"f{i}.txt"
        p.write_text(f"k{i} = {i}\n", encoding="utf-8")
        cache.parse_cached(p)
    cache.flush(force=True)
    counts = cache.disk_counts()
    assert counts["条目"] == 3
    assert counts["分片"] == len({cache._shard_of(str(tmp_path / f"f{i}.txt")) for i in range(3)})


# ────────────────── 覆盖率补口（t58，2026-09-25）──────────────────
#
# 为什么要这一节：`v3 cov --check-only` 实测 `pdx/cache.py` **90.8% < 92.0%**，
# 缺 **22 行 + 13 分支**。这里**只新增**用例去盖那些**真有行为**的分支
# （错误路径 / 上限边界 / 读者与写者分叉）—— 不为凑数写无判别力的断言，
# 也不加 `# pragma: no cover`（那等于把代码藏起来，不是把行为测出来）。
#
# 每条的 docstring 都写明它盖的是哪个函数、哪一行，便于 `v3 cov` 的缺口表逐条对上。


class _LookalikeAssignment(Assignment):
    """`Assignment` 的**子类**：`isinstance(a, Assignment)` 过、`type(a) is Assignment` 不过。

    身份判据的第一条早退（`:199`）比的正是**类对象本身** —— 而 `Block.assignments()`
    是用 `isinstance` 过滤放进来的，所以「子类」这条路真实存在、值得钉住。
    必须是模块级类（函数内定义的局部类除 `pickle` 之外，也让「身份」这件事更难读）。
    """


def test_身份判据_顶层赋值是子类也要判否() -> None:
    """盖 `_same_identity()` 的第一条早退（`:198-199`）：不是**同一个类对象**就判否。"""
    pf = ParsedFile(
        path="mem://sub", root=Block(items=[_LookalikeAssignment(key="a", op="=", value=None)])
    )
    assert cache._same_identity(pf) is False


def test_身份判据_没有值的赋值不算违规() -> None:
    """盖 `_same_identity()` 的 `node is None` 跳过（`:203-204`）。

    `a.value` 完全可以是 `None`（裸键），这时要**跳过**而不是判否 ——
    判否会让一整类合法条目永远命中不了。
    """
    pf = ParsedFile(path="mem://bare", root=Block(items=[Assignment("bare", "=", None)]))
    assert cache._same_identity(pf) is True


def test_memo上限的三个取值(monkeypatch) -> None:
    """盖 `_memo_maxsize()` 的非空环境变量那条路（`:148` 的假分支 → `:150-154`）。

    三条语义：**非数字退回默认**、`0` = 无上限（只给实验用）、正数 = 该值。
    它是唯一「不改代码就能把内存层上限调大调小」的旋钮，实验口径全靠它读得准。
    """
    monkeypatch.setenv(cache.MEMO_ENV, "不是数字")
    assert cache._memo_maxsize() == cache.MEMO_MAX_ENTRIES
    monkeypatch.setenv(cache.MEMO_ENV, "0")
    assert cache._memo_maxsize() is None, "0 = 无上限"
    monkeypatch.setenv(cache.MEMO_ENV, "256")
    assert cache._memo_maxsize() == 256


def test_memo上限报的是本进程生效值() -> None:
    """盖 `memo_maxsize()` 本体（`:288`）：报告里那一格就是 `lru_cache` 的 `maxsize`。

    ⚠️ 它读的是 **import 时**定下的值（`lru_cache` 的上限不能事后改），
    所以用例断言「与 `cache_info()` 一致、且是整数」，不断言等于常量 ——
    本进程被 `V3_PARSE_MEMO` 覆盖过时，报的就该是覆盖值。
    """
    info = cache._parse_by_key.cache_info()
    assert cache.memo_maxsize() == info.maxsize
    assert isinstance(cache.memo_maxsize(), int), "默认路径下它必须是整数（不是无上限）"


def test_索引指向别人的数据段时必须判未命中而不是返回外来树(tmp_path, disk_dir) -> None:
    """**本轮修掉的静默错误**：拿 A 的指纹去读**别人的**那段字节。

    做法：数据段一个字不动，只把索引里 A 的 `(偏移, 字节数)` 换成 B 的
    —— 于是 `zlib.decompress` 与 `pickle.loads` **都会成功**（那是一段合法的
    压缩 pickle），只有 payload 里的自证指纹能挡住它。

    盖的是 `_read_entry()` 的自证早退（`:428-429`）。这条用例守的是
    「旧索引 + 新数据 ⇒ 静默返回另一棵树」那个事故：**宁可判未命中，绝不返回外来树**。
    """
    paths = _same_shard_paths(tmp_path, 2)
    for i, path in enumerate(paths):
        path.write_text(f"k{i} = {i}\n", encoding="utf-8")
        cache.parse_cached(path)
    shard = cache._shard_of(str(paths[0]))
    assert cache.flush(force=True) == 1, "两条同片，应当只写一片"

    sig_a = cache._signature(str(paths[0]))
    sig_b = cache._signature(str(paths[1]))
    assert sig_a
    assert sig_b
    assert sig_a != sig_b
    index = dict(cache._load_index(shard))
    meta_b = index[sig_b]

    # 反证（否则这条用例是空的）：同一段字节配上它**自己的**指纹就应当读得出来
    assert cache._read_entry(shard, meta_b, sig_b) is not None
    # 正题：拿 A 的指纹去读 B 的字节 ⇒ 判未命中，**不许**返回 B 那棵树
    assert cache._read_entry(shard, meta_b, sig_a) is None

    # 再把「旧索引」这个真实场景补上：索引文件里 A 的偏移被写成 B 的
    stale = dict(index)
    stale[sig_a] = meta_b
    body = {"格式": cache.PARSE_CACHE_FORMAT, "条目": stale}
    cache._index_path(shard).write_bytes(pickle.dumps(body, protocol=pickle.HIGHEST_PROTOCOL))
    _reset_disk_state()  # 模拟「另一个进程」：内存层与待落盘区都丢掉，只剩盘上的文件

    assert cache._disk_load(sig_a, shard) is None, "旧索引指向别人的字节 ⇒ 必须判未命中"
    assert cache.parse_cached(paths[0]).top_keys == ["k0"], "判未命中之后仍要自愈到正确结果"


def test_数据段被截断之后判未命中而不是返回外来树(tmp_path, disk_dir) -> None:
    """把 data 段砍短几字节 ⇒ 同一条必须**判未命中**（盖 `:423-424` 的「读不够长」早退）。

    这是 `t39` 修的静默错误的第一种破坏形态；下一轮读要能自愈成**正确**那棵树。
    """
    paths = _same_shard_paths(tmp_path, 2)
    for i, path in enumerate(paths):
        path.write_text(f"k{i} = {i}\n", encoding="utf-8")
        cache.parse_cached(path)
    shard = cache._shard_of(str(paths[0]))
    assert cache.flush(force=True) == 1
    sig_a = cache._signature(str(paths[0]))
    assert sig_a is not None

    data = cache._shard_path(shard)
    offset_a, length_a, _seq_a = cache._load_index(shard)[sig_a]
    # 砍到**第一条自己那段的中间**：这样读 A 时「读不够长」，而不是砍到别人那一截
    data.write_bytes(data.read_bytes()[: offset_a + length_a - 2])
    _reset_disk_state()  # 丢掉内存层与待落盘区，否则会从待落盘区命中、根本走不到盘上那条
    assert cache._disk_load(sig_a, shard) is None, "截断之后只能判未命中"
    assert cache.parse_cached(paths[0]).top_keys == ["k0"], "自愈要拿到正确那棵树"


def test_数据段被同长度改坏之后判未命中(tmp_path, disk_dir) -> None:
    """**同长度**改坏（长度判据拦不住）⇒ 解压/反序列化抛异常也要被吃掉，判未命中。

    与截断那条的区别：这里 `len(blob) == length`，所以只能靠 `except`（`:426-427`）
    兜住。两种形态都必须是「未命中」，不许把半截/乱码字节当成树返回。
    """
    paths = _same_shard_paths(tmp_path, 2)
    for i, path in enumerate(paths):
        path.write_text(f"k{i} = {i}\n", encoding="utf-8")
        cache.parse_cached(path)
    shard = cache._shard_of(str(paths[0]))
    assert cache.flush(force=True) == 1
    sig_a = cache._signature(str(paths[0]))
    assert sig_a is not None

    data = cache._shard_path(shard)
    blob = bytearray(data.read_bytes())
    for i in range(4, min(len(blob), 40)):
        blob[i] ^= 0xFF
    data.write_bytes(bytes(blob))
    _reset_disk_state()
    assert cache._disk_load(sig_a, shard) is None
    assert cache.parse_cached(paths[0]).top_keys == ["k0"]


def test_偏移或长度非法时直接判未命中(tmp_path, disk_dir) -> None:
    """盖 `_read_entry()` 的第一条早退（`:417-418`）：偏移为负 / 长度为 0 ⇒ 不碰盘就判未命中。"""
    p = tmp_path / "a.txt"
    p.write_text(_SAMPLE, encoding="utf-8")
    sig = cache._signature(str(p))
    assert sig is not None
    shard = cache._shard_of(str(p))
    assert cache._read_entry(shard, (0, 0, 1), sig) is None
    assert cache._read_entry(shard, (-1, 10, 1), sig) is None


def test_坏索引整片作废(tmp_path, disk_dir) -> None:
    """盖 `_load_index()` 的 `except Exception`（`:392-393`）：索引解不开 ⇒ 整片作废。

    为什么必须作废而不是「每轮判一次」：坏索引永远好不了，留着只会让同一个文件
    在每次运行里都被白判一遍（而且数据段还占着分片数）。
    """
    p = tmp_path / "a.txt"
    p.write_text(_SAMPLE, encoding="utf-8")
    cache.parse_cached(p)
    assert cache.flush(force=True) == 1
    shard = cache._shard_of(str(p))

    cache._state.indexes.clear()
    cache._index_path(shard).write_bytes(b"\x00not a pickle")
    assert cache._load_index(shard) == {}
    assert not cache._index_path(shard).is_file(), "坏索引要顺手清掉"
    assert not cache._shard_path(shard).is_file(), "同一片的数据段一起作废"


def test_索引里的条目不是字典时整片作废(tmp_path, disk_dir) -> None:
    """格式号对、但 `条目` 不是 dict ⇒ 走 `:379` 的假分支（不删文件、只当空）。"""
    p = tmp_path / "a.txt"
    p.write_text(_SAMPLE, encoding="utf-8")
    cache.parse_cached(p)
    assert cache.flush(force=True) == 1
    shard = cache._shard_of(str(p))

    cache._state.indexes.clear()
    body = {"格式": cache.PARSE_CACHE_FORMAT, "条目": ["不是 dict"]}
    cache._index_path(shard).write_bytes(pickle.dumps(body, protocol=pickle.HIGHEST_PROTOCOL))
    assert cache._load_index(shard) == {}
    assert cache._index_path(shard).is_file(), "这一路只是「读不出条目」，不该删别人的文件"


def test_条目数超上限时只留最新若干条(tmp_path, disk_dir, monkeypatch) -> None:
    """盖 `_write_shard()` 的瘦身（`:536-538`）：超上限就按写入序号丢最旧的。"""
    monkeypatch.setattr(cache, "MAX_ENTRIES_PER_SHARD", 2)
    paths = _same_shard_paths(tmp_path, 4)
    for i, path in enumerate(paths):
        path.write_text(f"k{i} = {i}\n", encoding="utf-8")
        cache.parse_cached(path)
    shard = cache._shard_of(str(paths[0]))
    assert cache._write_shard(shard) is True

    kept = set(cache._load_index(shard))
    newest = {cache._signature(str(paths[2])), cache._signature(str(paths[3]))}
    assert kept == newest, "只留最新 2 条（按写入序号）"


def test_没有旧数据段时旧条目只能放弃(tmp_path, disk_dir) -> None:
    """盖 `_write_shard()` 的 `src is None` 分支（`:567-568`）。

    索引里记着旧条目、数据段文件却没了（半截写 / 被清过）⇒ 那些条目**只能放弃**，
    但不能因此挡住本次的新条目。
    """
    paths = _same_shard_paths(tmp_path, 2)
    for i, path in enumerate(paths):
        path.write_text(f"k{i} = {i}\n", encoding="utf-8")
    cache.parse_cached(paths[0])
    assert cache.flush(force=True) == 1
    shard = cache._shard_of(str(paths[0]))
    sig_a = cache._signature(str(paths[0]))
    sig_b = cache._signature(str(paths[1]))
    assert sig_a
    assert sig_b
    assert cache._load_index(shard), "索引视图里还留着旧条目"
    cache._shard_path(shard).unlink()

    cache.parse_cached(paths[1])
    assert cache._write_shard(shard) is True
    kept = set(cache._load_index(shard))
    assert sig_a not in kept, "数据段没了 ⇒ 旧条目放弃"
    assert sig_b in kept, "本次新条目要照写"


def test_旧数据段被截断的那条不要了(tmp_path, disk_dir) -> None:
    """盖 `_write_shard()` 的「旧字节读不够长」分支（`:571-572`）。

    旧数据段被从尾巴上砍掉 ⇒ 最后那条搬不过去（搬一半会写出**索引与数据对不上**的片子），
    其余完好的条目照搬。
    """
    paths = _same_shard_paths(tmp_path, 3)
    for i, path in enumerate(paths):
        path.write_text(f"k{i} = {i}\n", encoding="utf-8")
        cache.parse_cached(path)
    shard = cache._shard_of(str(paths[0]))
    assert cache.flush(force=True) == 1
    before = set(cache._load_index(shard))
    assert len(before) == 3

    data = cache._shard_path(shard)
    end = max(offset + length for offset, length, _seq in cache._load_index(shard).values())
    data.write_bytes(data.read_bytes()[: end - 2])

    assert cache._write_shard(shard) is True
    after = set(cache._load_index(shard))
    assert len(after) == 2, "被截断的那一条不搬，其余两条照搬"
    assert after <= before


def test_落盘失败只影响这一片且不抛(tmp_path, disk_dir) -> None:
    """盖 `_write_shard()` 的 `except Exception`（`:587-590`）与 `flush` 的假分支（`:619`）。

    造法：把「缓存目录」变成一个**文件** ⇒ `mkdir` 必炸。要守的性质是：
    写不出去**只**意味着这一片没写成功 —— 不抛异常、不把待落盘的写丢掉（丢了就是静默退化）。
    """
    seen: dict[int, Path] = {}
    for index in range(50):
        path = tmp_path / f"d{index}.txt"
        path.write_text(f"k{index} = {index}\n", encoding="utf-8")
        cache.parse_cached(path)
        seen.setdefault(cache._shard_of(str(path)), path)
        if len(seen) == 2:  # 两个脏片：让 flush 的假分支真的回到循环头（`:619` → `:618`）
            break
    assert len(seen) == 2, "没凑出两个不同的分片"

    cache.cache_dir().write_bytes(b"not a directory")
    assert cache.flush(force=True) == 0, "写不出去就是 0，不是异常"
    for shard in seen:
        assert shard in cache._state.pending, "写失败的片不许被 pop 掉（否则写就静默丢了）"
    # ⚠️ 只断言「待落盘的写没丢」。`flush` 无论成败都会清 `dirty`（`cache.py` 的既有行为，
    #    不在本卡范围）：重试靠下一次 `_disk_store()` 再标脏，`pending` 才是那份写的本体。


def test_缓存目录不存在时清空也不报错(tmp_path, disk_dir) -> None:
    """盖 `clear_disk()` 的 `base.is_dir()` 假分支（`:680` → `:683`）：目录还没建也能清。"""
    assert not cache.cache_dir().exists()
    assert cache.clear_disk() == 0
    assert cache._state.pending == {}
    assert cache._state.indexes == {}


def test_磁盘层状态的两句话(tmp_path, disk_dir, monkeypatch) -> None:
    """盖 `describe_state()` 的另外两句（`:694-695` 已关闭、`:696-698` 启用且非 worker）。"""
    monkeypatch.setenv(cache.CACHE_ENV, "0")
    assert cache.describe_state().startswith("已关闭")
    monkeypatch.delenv(cache.CACHE_ENV)
    assert cache.describe_state().startswith("启用（")


# ────────────────── t59：世代键的边界与旧布局残留 ──────────────────


def _scalar_texts(parsed: ParsedFile) -> list[str]:
    """顶层赋值的**标量**原文（`v = 111111` → `["111111"]`）；不是标量就当场失败。

    比在断言里直接点 `a.value.text` 好在：`Assignment.value` 的类型是
    ``Block | Scalar | None``，直接点它 mypy 会给 `union-attr`；这里收窄一次，
    而且「这条该是标量」本身就是用例想钉的性质。
    """
    texts: list[str] = []
    for item in parsed.top_assignments:
        value = item.value
        assert isinstance(value, Scalar), f"期望标量，实得 {type(value).__name__}"
        texts.append(value.text)
    return texts


def test_等长改写并复原mtime时磁盘条目必须失效(tmp_path, disk_dir) -> None:
    """复现历史陈旧命中反例，内容证明必须在模拟新进程后仍成立。"""
    p = tmp_path / "same-len.txt"
    p.write_text("v = 111111\n", encoding="utf-8")
    before = p.stat()
    sig_before = cache._signature(str(p))
    assert sig_before is not None
    cache.parse_cached(p)
    assert cache.flush(force=True) == 1
    _reset_disk_state()  # 模拟新进程：内存层、索引视图与待落盘区都丢掉

    p.write_text("v = 222222\n", encoding="utf-8")  # 等长改写
    os.utime(p, ns=(before.st_atime_ns, before.st_mtime_ns))  # 把时间戳复原
    assert p.stat().st_size == before.st_size, "这条用例的前提是「等长」"
    assert cache._signature(str(p)) != sig_before, "内容改变必须改变磁盘键"

    cached = cache.parse_cached(p)
    fresh = parse_file(p)
    assert _scalar_texts(cached) == ["222222"], "缓存必须返回当前内容"
    assert _scalar_texts(fresh) == ["222222"], "直接解析是**真值**"
    assert cache._state.parsed_total == 1, "旧条目不能复用，必须重新解析"


def test_清磁盘时顺手清掉更早布局的残留(tmp_path, disk_dir) -> None:
    """**更早布局**的残留（两位十六进制名的分片目录/文件）要被 `clear_disk()` 认出来清掉。

    取证：`docs/reports/缓存跨代读-独立验证.md` §6.2 + t59 现读 —— 共享桶 226 个条目里
    **193 个**是这样的目录（每片一个目录，里面是 `<64 位十六进制>.pkl`，合计 368 个 `.pkl`、
    约 3.5 MB，mtime 2026-09-19），`v3 cache --clear` 原先清不掉它们，
    于是「缓存目录有多少文件」这一格被一直抬高。
    **判据 = 名字形状 + （目录时）内容形状**，不是「凡不认识的都删」——
    下面三条反证（认不出名字 / 认不出内容 / 普通文件）都必须留着。
    """
    assert cache._is_stale_shard_name("00")
    assert cache._is_stale_shard_name("0a")
    assert cache._is_stale_shard_name("ff")
    assert not cache._is_stale_shard_name("shard-00.bin")
    assert not cache._is_stale_shard_name("0g")
    assert not cache._is_stale_shard_name("abc")
    assert not cache._is_stale_shard_name("")
    assert cache._is_legacy_entry_name("a" * 62 + ".pkl"), "实测那 368 个就是 62 位"
    assert cache._is_legacy_entry_name("a" * 64 + ".pkl"), "更长也算（区间 32–64）"
    assert cache._is_legacy_entry_name("a" * 32 + ".pkl")
    assert not cache._is_legacy_entry_name("a" * 62 + ".bin")
    assert not cache._is_legacy_entry_name("a" * 31 + ".pkl")
    assert not cache._is_legacy_entry_name("A" * 62 + ".pkl"), "大写不认（实测全是小写）"

    p = tmp_path / "a.txt"
    p.write_text(_SAMPLE, encoding="utf-8")
    cache.parse_cached(p)
    assert cache.flush(force=True) == 1
    base = cache.cache_dir()
    base.mkdir(parents=True, exist_ok=True)

    old_dir = base / "0a"  # 旧布局：一个分片一个目录 + `<sha256>.pkl`
    old_dir.mkdir()
    (old_dir / ("b" * 64 + ".pkl")).write_bytes(b"x")
    empty_dir = base / "ff"  # 清到一半的旧目录（空）
    empty_dir.mkdir()
    old_file = base / "00"  # 旧布局的文件形态也认（t54 报的是这一族的另一形态）
    old_file.write_bytes(b"")
    kept_name = base / "认不出的目录"
    kept_name.mkdir()
    kept_content = base / "ab"  # 名字像旧的、里面装的东西不像 ⇒ 不碰
    kept_content.mkdir()
    (kept_content / "not-our-entry.txt").write_bytes(b"x")
    kept_file = base / "认不出的名字.txt"
    kept_file.write_bytes(b"x")

    assert cache.clear_disk() == 1, "返回值口径不变：还是只数数据段分片"
    assert not old_dir.exists(), "旧布局的目录要清掉"
    assert not empty_dir.exists(), "空的旧目录同样算残留"
    assert not old_file.exists(), "旧布局的文件形态也要清掉"
    assert kept_name.is_dir(), "认不出名字的不碰"
    assert (kept_content / "not-our-entry.txt").is_file(), "认不出内容的不碰"
    assert kept_file.is_file(), "普通文件不删"
