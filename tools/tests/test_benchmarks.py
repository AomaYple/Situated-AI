"""基准测试（pytest-benchmark）。

为什么需要
----------
「速度第二」不等于不关心速度 —— 而是**先保证正确，再基于数据优化**。
没有基准，优化就只能凭感觉，也说不清到底快了多少。

用法
----
    # 只跑基准
    pytest tools/tests/test_benchmarks.py --benchmark-only -q

    # 与上次结果对比（自动，结果存在 .benchmarks/）
    pytest tools/tests/test_benchmarks.py --benchmark-only --benchmark-compare

    # 存为基线
    pytest tools/tests/test_benchmarks.py --benchmark-only --benchmark-save=baseline

基准不参与常规测试
------------------
默认 ``--benchmark-disable`` 之外，本文件所有用例都带 ``benchmark`` marker，
常规运行时会因未启用插件而跳过 —— 避免拖慢日常测试。
"""

from __future__ import annotations

import pytest

from pdx import config
from pdx.lexer import tokenize
from pdx.parser import parse_text

pytestmark = [pytest.mark.benchmark, pytest.mark.slow]

_needs_game = pytest.mark.skipif(
    not (config.GAME / "common").is_dir(), reason="游戏目录不可用"
)

#: 代表中小型 PDX 文件规模
SMALL = "root = {\n" + "\n".join(
    f"\tkey_{i} = {{ a = 1  b = {i}  c = {{ d = 2 }} }}" for i in range(50)
) + "\n}\n"

MEDIUM = "root = {\n" + "\n".join(
    f"\tkey_{i} = {{ a = 1  b = {i}  c = {{ d = {i}  e = \"x#{i}\" }} }}" for i in range(500)
) + "\n}\n"

#: 含各类边角语法，用于保证基准测的是真实路径
TRICKY = (
    "\ufeff"
    'quoted = "has # hash"\n'
    "hyphen-key = { x = 1 }\n"
    "c:SWE ?= { y = 2 }\n"
    "INJECT:foo = { z = 3 }\n"
    "@var = 0.5\n"
    "bare = { a b c }\n"
    "split =\n{\n  inner = 1\n}\n"
    "# comment with { braces }\n"
)

class TestLexerBenchmarks:
    def test_tokenize_small(self, benchmark):
        benchmark(tokenize, SMALL)

    def test_tokenize_medium(self, benchmark):
        benchmark(tokenize, MEDIUM)

    def test_tokenize_tricky(self, benchmark):
        benchmark(tokenize, TRICKY)

class TestParserBenchmarks:
    def test_parse_small(self, benchmark):
        benchmark(parse_text, SMALL)

    def test_parse_medium(self, benchmark):
        benchmark(parse_text, MEDIUM)

    def test_parse_tricky(self, benchmark):
        benchmark(parse_text, TRICKY)

@_needs_game
class TestRealFileBenchmarks:
    """真实游戏文件 —— 比合成数据更能反映实际负载。"""

    @pytest.fixture(scope="class")
    def samples(self):
        common = config.GAME / "common"
        picks = [
            common / "static_modifiers" / "00_code_static_modifiers.txt",
            common / "defines" / "00_defines.txt",
            common / "buildings" / "00_buildings.txt",
        ]
        return [(p.name, p.read_bytes().decode("utf-8-sig"))
                for p in picks if p.is_file()]

    def test_tokenize_real(self, benchmark, samples):
        if not samples:
            pytest.skip("样本文件不存在")
        name, text = samples[0]
        benchmark.extra_info["file"] = name
        benchmark(tokenize, text)

    def test_parse_real(self, benchmark, samples):
        if not samples:
            pytest.skip("样本文件不存在")
        name, text = samples[0]
        benchmark.extra_info["file"] = name
        benchmark(parse_text, text)

    def test_parse_all_samples(self, benchmark, samples):
        if not samples:
            pytest.skip("样本文件不存在")
        benchmark(lambda: [parse_text(t) for _, t in samples])

@_needs_game
class TestPipelineBenchmarks:
    """端到端：解析整个 static_modifiers 目录。"""

    def test_extract_dir(self, benchmark):
        from pdx.cache import clear
        from pdx.extract import extract_dir

        target = config.GAME / "common" / "static_modifiers"

        def run():
            clear()            # 强制真实解析，避免缓存命中掩盖成本
            return extract_dir(target)

        result = benchmark(run)
        assert result.unique_entries > 6000
