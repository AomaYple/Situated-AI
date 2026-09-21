"""基准测试（pytest-benchmark）。

为什么需要
----------
「速度第二」不等于不关心速度 —— 而是**先保证正确，再基于数据优化**。
没有基准，优化就只能凭感觉，也说不清到底快了多少。

用法
----
    # 只跑基准（**必须清掉 addopts**：仓库默认带 -n auto，xdist 开着时
    # pytest-benchmark 会自动禁用自己；`-n0` 不管用，实测报
    # "Can't have both --benchmark-only and --benchmark-disable"）
    pytest tools/tests/test_benchmarks.py -o addopts="" --benchmark-only -q

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

import numpy as np
import pytest
from PIL import Image

from pdx import config
from pdx.lexer import tokenize
from pdx.parser import parse_text

pytestmark = [pytest.mark.benchmark, pytest.mark.slow]

_needs_game = pytest.mark.skipif(not (config.GAME / "common").is_dir(), reason="游戏目录不可用")

#: 代表中小型 PDX 文件规模
SMALL = (
    "root = {\n"
    + "\n".join(f"\tkey_{i} = {{ a = 1  b = {i}  c = {{ d = 2 }} }}" for i in range(50))
    + "\n}\n"
)

MEDIUM = (
    "root = {\n"
    + "\n".join(
        f'\tkey_{i} = {{ a = 1  b = {i}  c = {{ d = {i}  e = "x#{i}" }} }}' for i in range(500)
    )
    + "\n}\n"
)

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
        return [(p.name, p.read_bytes().decode("utf-8-sig")) for p in picks if p.is_file()]

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
            clear()  # 强制真实解析，避免缓存命中掩盖成本
            return extract_dir(target)

        result = benchmark(run)
        assert result.unique_entries > 6000


class TestAutoCaptureBenchmarks:
    """游戏自动化的**热路径**：找按钮 = 抓图 + 模板匹配。

    为什么单列一组：这条路径以前是"整屏抓图 + 6 个尺度全试"，而等界面时一秒要跑好几遍。
    2026-09-21 的优化把它改成"**只抓需要的 ROI** + **命中即停** + **模板只读一次盘**"。
    P5 要求"每一项优化都要有前后对照" —— 这组基准就是那份对照数据，跑法：

        pytest tools/tests/test_benchmarks.py -q --benchmark-only \\
               --benchmark-save=auto-capture

    数字（本机 2026-09-21，`--benchmark-only`，均值 / 最坏）：
    见 `docs/design/exec/自动化范式.md` §4.7 —— 那张表里的数就是这里跑出来的。
    匹配 1146.5 ms → 15.3 ms（75×）；模板读盘 315.7 µs → 1.05 µs（300×）。
    """

    #: 底部状态栏 ROI（实测「观察」按钮在那里）：整屏的 1/10 面积
    BOTTOM = (0.0, 0.90, 1.0, 1.0)

    @staticmethod
    def _frame_and_template():
        from pdx import game_auto as ga

        rng = np.random.default_rng(20260921)
        frame = Image.fromarray(rng.integers(0, 255, (1080, 1920, 3), dtype=np.uint8), "RGB")
        # 用一个真实的按钮模板贴进底部条：走完整路径，不拿假图案自欺
        template_path = ga.UI_DIR / "btn_observe.png"
        if template_path.is_file():
            with Image.open(template_path) as handle:
                patch = handle.convert("RGB")
            frame.paste(patch, (755, 1037))
        else:  # pragma: no cover - 模板是入库产物，缺了说明仓库不完整
            patch = frame.crop((755, 1037, 973, 1073))
        return np.array(frame), np.array(patch)

    def test_match_fullframe_all_scales(self, benchmark) -> None:
        """优化**前**的口径：整屏 + 6 个尺度全试。"""
        from pdx import game_auto as ga

        image, template = self._frame_and_template()
        result = benchmark(
            ga.match_template, image, template, name="btn_observe", scales=ga.DEFAULT_SCALES
        )
        assert result is not None

    def test_match_roi_first_hit(self, benchmark) -> None:
        """优化**后**的口径：只匹配底部条 + 命中即停。"""
        from pdx import game_auto as ga

        image, template = self._frame_and_template()
        result = benchmark(
            ga.match_template,
            image,
            template,
            name="btn_observe",
            scales=ga.DEFAULT_SCALES,
            roi=self.BOTTOM,
            first_hit=True,
        )
        assert result is not None

    def test_load_template_cached(self, benchmark) -> None:
        """模板命中缓存（等待界面时每帧都要取一次模板，重复读盘纯属浪费）。"""
        from pdx import game_auto as ga

        if not (ga.UI_DIR / "btn_observe.png").is_file():  # pragma: no cover
            pytest.skip("按钮模板缺失")
        ga.clear_template_cache()
        ga.load_template("btn_observe")  # 预热
        result = benchmark(ga.load_template, "btn_observe")
        assert result.shape[2] == 3

    def test_load_template_uncached(self, benchmark) -> None:
        """优化**前**的口径：每次都 `open` + 解码 PNG（清缓存来还原旧行为）。"""
        from pdx import game_auto as ga

        if not (ga.UI_DIR / "btn_observe.png").is_file():  # pragma: no cover
            pytest.skip("按钮模板缺失")

        def read_from_disk():
            ga.clear_template_cache()
            return ga.load_template("btn_observe")

        result = benchmark(read_from_disk)
        assert result.shape[2] == 3
