"""缓存透明性测试。

要证明的性质
------------
``parse_cached`` 对调用方必须**完全等价于** ``parse_file``：
返回同样的内容，且不因缓存状态而产生可观察差异。
这条一旦破了，全量分析的数字就会随「跑第几遍」而变 —— 那是最难查的一类 bug。

另外钉住 :mod:`pdx.cache` 的命中率统计口径，因为剖析结论依赖它。
"""

from __future__ import annotations

import pytest
from _helpers import signature

from pdx import cache
from pdx.parser import parse_file

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
    """模拟「另一个进程」：内存缓存与分片视图都丢掉，只剩磁盘上的文件。"""
    cache.clear()
    cache._state.shards.clear()
    cache._state.dirty.clear()
    cache._state.parsed_total = 0
    cache._state.seq = 0


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
