"""审计遗留项的可执行版本（`docs/audits/测试套件审计-重构前.md` §3 的第 10–14 项）。

那份审计列了 17 种「建议补充的测试」，其中大部分早已落地（文档一致性、契约、
CLI 子进程、差分、变形、覆盖率门禁…）。这里补的是当时**没做**的五项：

| # | 审计建议 | 落成什么 |
|---|---|---|
| 10 | 静态检查即测试 | :func:`test_ruff_check_通过`（进程内跑 ruff，本地不依赖 CI 才发现） |
| 11 | doctest | :func:`test_doctest_示例都能跑`（对纯函数模块跑 `doctest`） |
| 12 | 并发/线程安全 | :func:`test_八线程并发解析与串行一致`（cache 在 `ThreadPoolExecutor` 下） |
| 13 | 性能回归门禁 | `tools/tests/test_benchmarks.py` 的基线表 + 本文件的 :func:`test_解析吞吐不低于下限` |
| 14 | ruff 作为用例 | 同 10（两者是一件事，合并实现） |

⚠️ 变异测试（审计第 6 项）不在 pytest 里 —— 它按定义要反复跑整套测试，
放进来会让每次提交都变成几十分钟。配置写在 `pyproject.toml` 的 `[tool.mutmut]`，
用法见 `tools/README.md`；本文件只断言那份配置指向真实模块。
"""

from __future__ import annotations

import concurrent.futures
import doctest
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from pdx import cache, config, doc_tables, markers
from pdx.parser import parse_file

pytestmark = pytest.mark.unit

_SAMPLE = "NCountry = {\n    tax = 0.2\n    list = { a b c }\n}\nFoo = { x = 1 }\n"


# ────────────────────────── 10 / 14：ruff 作为测试 ──────────────────────────


def test_ruff_check_通过() -> None:
    """本地就能拦下 lint 问题，不用等 CI。

    口径与 CI 一致：`ruff check .`（配置全在 pyproject.toml）。
    ruff 未安装时跳过 —— 它属于 dev 依赖，而这条测试不该让「只装运行期依赖」
    的环境变红。
    """
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "."],
        cwd=str(config.REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode not in (0, 1):  # pragma: no cover - ruff 不可用
        pytest.skip(f"ruff 不可用：{result.stderr[-200:]}")
    assert result.returncode == 0, f"ruff 报错：\n{result.stdout[-2000:]}"


def test_ruff_format_通过() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", "."],
        cwd=str(config.REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode not in (0, 1):  # pragma: no cover - ruff 不可用
        pytest.skip(f"ruff 不可用：{result.stderr[-200:]}")
    assert result.returncode == 0, f"格式不一致：\n{result.stdout[-2000:]}"


# ────────────────────────── 11：doctest ──────────────────────────


@pytest.mark.parametrize("module", [doc_tables, markers])
def test_doctest_示例都能跑(module) -> None:
    """对**纯函数**模块跑 doctest。

    只挑没有游戏依赖的模块：`doc_tables` 的表格工具与 `markers` 的标记解析
    都是纯字符串处理，写在文档字符串里的 `>>>` 例子必须真的能跑出那个结果 ——
    这是「文档即测试」最便宜的一档。
    """
    result = doctest.testmod(module, verbose=False, report=False)
    assert result.failed == 0, f"{module.__name__} 里有 {result.failed} 个 doctest 失败"


def test_doctest_至少有一个示例() -> None:
    """防止上面那条变成空跑：模块的文档里得真有 `>>>` 例子。"""
    found = 0
    for module in (doc_tables, markers):
        for name in dir(module):
            doc = getattr(getattr(module, name), "__doc__", "") or ""
            found += doc.count(">>>")
    assert found >= 3, f"doctest 覆盖到的示例只有 {found} 个，太少（至少 3 个）"


# ────────────────────────── 12：并发/线程安全 ──────────────────────────


def _write_batch(root: Path, count: int = 40) -> list[Path]:
    paths: list[Path] = []
    for i in range(count):
        path = root / f"f{i:03d}.txt"
        path.write_text(f"key_{i} = {{ v = {i} }}\nnext_{i} = yes\n", encoding="utf-8")
        paths.append(path)
    return paths


def test_八线程并发解析与串行一致(tmp_path) -> None:
    """`pdx.cache` 声称线程安全（`lru_cache` 内部的锁）—— 这里真并发一次。

    判据是**结果集与串行完全一致**（按文件签名比对），而不是「没抛异常」：
    只断言不抛异常的测试，在缓存串了数据时照样会绿。
    """
    paths = _write_batch(tmp_path)
    cache.clear()
    serial = {p.name: parse_file(p).top_keys for p in paths}

    cache.clear()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(cache.parse_cached, paths))
    parallel = {p.name: pf.top_keys for p, pf in zip(paths, results, strict=True)}
    assert parallel == serial

    # 同一对象被复用（记忆化确实生效），且计数对得上
    again = [cache.parse_cached(p) for p in paths]
    assert all(a is b for a, b in zip(again, results, strict=True))
    stats = cache.stats()
    assert stats["未命中"] == len(paths), "并发下每个文件也只该真正解析一次"


# ────────────────────────── 13：性能回归门禁 ──────────────────────────


@pytest.mark.slow
def test_解析吞吐不低于下限(tmp_path) -> None:
    """解析吞吐的**宽松**门禁：明显退化时红，机器抖动时不红。

    为什么不用基准数字比：CI 与本机的 CPU 差几倍，卡死数字只会制造噪音。
    这里用一个比实测慢一个数量级的下限（实测约 1.5 万行/秒，下限设 1 千），
    够抓住「引入 O(n²) 或每次解析都重读整棵树」这类真退化。
    """
    body = "".join(
        f"block_{i} = {{\n    a = {i}\n    b = {{ c = {i} d = yes }}\n}}\n" for i in range(200)
    )
    path = tmp_path / "big.txt"
    path.write_text(body, encoding="utf-8")
    total_lines = len(body.splitlines())

    cache.clear()
    start = time.perf_counter()
    parsed = parse_file(path)
    elapsed = time.perf_counter() - start
    assert parsed.top_keys, "得真解析出东西，否则测的是空跑"
    rate = total_lines / max(elapsed, 1e-6)
    assert rate > 1_000, f"解析吞吐只有 {rate:,.0f} 行/秒（下限 1,000）—— 检查是否引入了重复解析"


def test_mutmut_配置指向真实模块() -> None:
    """变异测试的配置不能指向空气（配置坏的测试工具等于没配）。"""
    text = (config.REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.mutmut]" in text, "pyproject.toml 里没有 [tool.mutmut] 段"
    for target in ("tools/pdx/lexer.py", "tools/pdx/markers.py"):
        assert (config.REPO / target).is_file(), f"mutmut 配置里的 {target} 不存在"
        assert target in text, f"{target} 没写进 [tool.mutmut]"


def test_性能基准文件可解析且口径齐全() -> None:
    """`tools/benchmarks/parse_baseline.json` 是可入库的基准记录。

    为什么不拿它当断言：CI 与本机 CPU 差几倍。它的用处是**记录**实测值
    （供人工对比），断言由上面那条宽松门禁负责。
    """
    import json

    path = config.REPO / "tools" / "benchmarks" / "parse_baseline.json"
    assert path.is_file(), "基准文件不存在"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["口径"], "得写清怎么复算与门槛口径"
    assert data["记录"], "基准记录不能是空的"
    assert data["记录"][0]["解析吞吐行每秒"] > 0
