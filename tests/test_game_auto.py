"""``pdx.game_auto`` 的用例。

分两层，**界限要清楚**：

* **纯逻辑**（本文件绝大部分）：坐标换算、模板匹配封装、状态判定、
  超时与失败路径。全部用合成图 / 假时钟 / 假的 Win32 缝隙函数驱动，
  **不需要真游戏，也不会碰键盘鼠标**。
* **真游戏**（文件末尾，``V3_AUTO_LIVE=1`` 才跑）：会真的起游戏、点按钮、
  等时间推进 —— 分钟级，且要求"当前 0 个 victoria3 进程"。
  默认跳过，所以本文件在 CI 上是纯离线的。

为什么把缝隙函数（``_foreground_window`` / ``_set_cursor`` / ``screenshot`` …）
单独测：它们各自对应一条**实测踩过的失败**（前台被抢、坐标不是屏幕坐标、
抓图全黑），而这些失败在真机上表现为"点了没反应"，最容易被人误读成"坐标不对"。
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import pytest
from PIL import Image

from pdx import config, h1_probe
from pdx import game_auto as ga
from pdx.platform_support import UnavailableWindowsModule

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

# ────────────────────────── 合成素材 ──────────────────────────

#: 真模板（入库的小 PNG）。用例用它们贴进合成画面，走**完整**的匹配路径，
#: 而不是把 locate 也换成假的 —— 那样就只剩同义反复了。
OBSERVE_TPL = ga.UI_DIR / "btn_observe.png"
#: 「观察」模板的高度（合成画面里要用它反推坐标；读不到就给一个保守值）
OBSERVE_TPL_HEIGHT = 36
PLAY_TPL = ga.UI_DIR / "btn_play.png"

needs_templates = pytest.mark.skipif(
    not (OBSERVE_TPL.is_file() and PLAY_TPL.is_file()),
    reason=f"按钮模板缺失（{ga.UI_DIR}）—— 模板是入库产物，缺了说明仓库不完整",
)


def textured(width: int = 1920, height: int = 1080, seed: int = 7) -> Image.Image:
    """造一张有纹理的假画面（``is_blank`` 不认它，模板匹配有干扰项）。"""
    rng = np.random.default_rng(seed)
    noise = rng.integers(40, 200, size=(height, width, 3), dtype=np.uint8)
    return Image.fromarray(noise, "RGB")


def paste(base: Image.Image, template: Path, left: int, top: int) -> tuple[int, int]:
    """把模板贴到画面上，返回贴上去的**中心**坐标。"""
    with Image.open(template) as handle:
        patch = handle.convert("RGB")
    base.paste(patch, (left, top))
    return (left + patch.width // 2, top + patch.height // 2)


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """把所有等待变成零耗时。"""
    monkeypatch.setattr(ga, "_sleep", lambda _seconds: None)


@pytest.fixture(autouse=True)
def _window_handles_are_synthetic(monkeypatch: pytest.MonkeyPatch) -> None:
    """让**窗口句柄**在单测里是确定性的，且绝不碰真实 Win32。

    为什么需要（2026-09-22 实机踩到后补的）：``_live_window()`` 现在会用
    ``win32gui.IsWindow()`` 判句柄是否还有效 —— 而用例传进来的句柄是 ``4242``
    / ``999`` 这种**合成值**，真实的 ``IsWindow`` 一律返回 0，于是刷新逻辑会去
    ``find_window()``，单测里那又是真的枚举桌面窗口 ⇒ 行为取决于桌面上有没有游戏。

    这条 fixture 把两件事钉住：

    * ``_is_alive`` 对**非零句柄**恒为真（合成句柄一律当作活着）；
      ``0`` 仍为假（"没有句柄"这个语义要保住）；
    * ``find_window()`` 默认找不到 —— 与"单测环境里没有游戏"一致。

    要测"句柄被重建"的用例，自己覆盖 ``_is_alive`` / ``find_window`` 即可
    （显式覆盖会盖掉本 fixture，monkeypatch 按调用顺序生效）。
    """
    monkeypatch.setattr(ga, "_is_alive", lambda hwnd: bool(hwnd))  # noqa: PLW0108
    monkeypatch.setattr(ga, "find_window", lambda *_a, **_kw: 0)
    monkeypatch.setattr(ga, "_foreground_window", lambda: 0)
    monkeypatch.setattr(ga, "_is_iconic", lambda _hwnd: False)
    # 原生适配器的少数用例注入这些 API；Linux/macOS 不安装 Win32 库。
    # 所有默认 API 均明确失败，防止缺少 mock 时静默假通过。
    if isinstance(ga.directinput, UnavailableWindowsModule):

        def unavailable(*args, **kwargs):
            pytest.fail("测试必须显式注入原生 API")

        monkeypatch.setitem(ga.directinput.__dict__, "keyDown", unavailable)
        monkeypatch.setitem(ga.directinput.__dict__, "keyUp", unavailable)
        for name in ("GetWindowRect", "WindowFromPoint", "GetAncestor"):
            monkeypatch.setitem(ga.win32gui.__dict__, name, unavailable)
        monkeypatch.setitem(ga.win32con.__dict__, "GA_ROOT", ga.GA_ROOT)


# ────────────────────────── 时间真值：解析与比较 ──────────────────────────


class TestTickParsing:
    def test_解析成整数元组(self) -> None:
        assert ga.parse_tick_date("1836.5.31.12") == (1836, 5, 31, 12)
        assert ga.parse_tick_date("1836.1.1") == (1836, 1, 1)

    def test_两边空格被忽略(self) -> None:
        assert ga.parse_tick_date("  1836.1.1\n") == (1836, 1, 1)

    @pytest.mark.parametrize("bad", ["", "   ", "abc", "1836.1.x", "1836..1", "<none>"])
    def test_解析不出来给空元组(self, bad: str) -> None:
        assert ga.parse_tick_date(bad) == ()

    def test_字典序会骗人但函数不会被骗(self) -> None:
        """**本模块最关键的一条**：10 月晚于 9 月，而字典序说反。

        如果哪天有人把 ``is_later`` 改成 `after > before` 的字符串比较，
        这一条会红 —— 而那正是它存在的理由。
        """
        # 这两边就是**故意**写成常量的：要展示的正是"字典序给出错答案"。
        assert "1836.10.1" < "1836.9.1"  # noqa: PLR0133
        assert ga.is_later("1836.9.1", "1836.10.1") is True
        assert ga.is_later("1836.10.1", "1836.9.1") is False

    def test_更细的日内刻度也算推进(self) -> None:
        assert ga.is_later("1836.1.1", "1836.1.1.6") is True

    def test_相等不算推进(self) -> None:
        assert ga.is_later("1836.1.1", "1836.1.1") is False

    @pytest.mark.parametrize(
        ("before", "after"),
        [("", "1836.1.1"), ("1836.1.1", ""), ("<读不到>", "1836.1.1")],
    )
    def test_读不到就不装作知道(self, before: str, after: str) -> None:
        assert ga.is_later(before, after) is False


class TestTickReading:
    def test_取最后一条(self) -> None:
        text = (
            "[1] Processing Tick: 1836.1.1\n"
            "[2] Processing Tick: 1836.2.1\n"
            "[3] Processing Tick: 1836.3.1.6\n"
        )
        assert ga.last_tick_in(text) == "1836.3.1.6"

    def test_没有就是空串而不是零(self) -> None:
        assert ga.last_tick_in("nothing here") == ga.NO_TICK
        assert ga.last_tick_in("") == ""

    def test_真日志的整行格式(self) -> None:
        line = "[23:37:23][jominiapplication.cpp:539]: Processing Tick: 1836.6.9\n"
        assert ga.last_tick_in(line) == "1836.6.9"

    def test_TickMark_的可读性(self) -> None:
        assert ga.TickMark("1836.1.1", 0.0).readable is True
        assert ga.TickMark(ga.NO_TICK, 0.0).readable is False

    def test_tick_mark_文件不存在时不抛(self, tmp_path: Path) -> None:
        mark = ga.tick_mark(tmp_path / "nope.log")
        assert mark.tick == ga.NO_TICK
        assert mark.readable is False

    def test_tick_mark_读得到(self, tmp_path: Path) -> None:
        log = tmp_path / "t.log"
        log.write_text("Processing Tick: 1837.4.10\n", encoding="utf-8")
        assert ga.tick_mark(log).tick == "1837.4.10"


class TestProbeReading:
    def test_取国家标签(self) -> None:
        text = (
            "[t][jomini_effect_impl.cpp:454]: common/on_actions/x.txt:23: "
            "ZZPROBE AB;ROLE;RUS;俄罗斯\n"
            "[t][jomini_effect_impl.cpp:454]: common/on_actions/x.txt:31: "
            "ZZPROBE AB;ROLE;RUS;俄罗斯\n"
        )
        assert ga.probe_roles_in(text) == ["RUS", "RUS"]

    def test_别的探针行不算(self) -> None:
        text = "ZZPROBE AB;PLAYER;yes;俄罗斯\nZZPROBE AB;LAW;law_serfdom;俄罗斯\n"
        assert ga.probe_roles_in(text) == []


class TestProcessListing:
    def test_从_CSV_取_PID(self) -> None:
        text = '"victoria3.exe","19084","Console","1","6,612 K"\n'
        assert ga.parse_tasklist_pids(text) == [19084]

    def test_没有任务时是空列表(self) -> None:
        # 中文 Windows 的本地化文案 + GBK 残字节：只认数字字段才不会误判
        text = "INFO: No tasks are running which match the specified criteria.\n"
        assert ga.parse_tasklist_pids(text) == []

    def test_坏字节不影响(self) -> None:
        text = 'INFO: \ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\n"victoria3.exe","42","C","1","1 K"\n'
        assert ga.parse_tasklist_pids(text) == [42]

    def test_字段里带逗号不会被当分隔符(self) -> None:
        """``tasklist`` 的内存列就是 ``"6,612 K"`` —— 引号里的逗号不是分隔符。"""
        text = '"victoria3.exe","19084","Console","1","6,612 K"\n'
        assert ga.parse_tasklist_pids(text) == [19084]

    def test_多行各取一个(self) -> None:
        text = '"a.exe","1","C"\n"b.exe","2","C"\n'
        assert ga.parse_tasklist_pids(text) == [1, 2]

    @pytest.mark.parametrize(
        "text",
        [
            '"a.exe", "7", "Console"\n',  # 逗号后有空格（手写 split('","') 取不到）
            "a.exe,7,Console\n",  # 完全没加引号（手写版同样取不到）
            '"a.exe","7","Console"\n',  # 标准形状
        ],
    )
    def test_容忍真实可能出现的引号形状(self, text: str) -> None:
        """三种形状都要取到 7 —— 换标准库 csv 的收益就在这里。

        旧实现要求**每个字段都带引号**，前两种形状会静默返回 ``[]``，
        而"进程在跑却说没有"会让上层去重复启动一个游戏。
        """
        assert ga.parse_tasklist_pids(text) == [7]

    def test_表头不变成_PID(self) -> None:
        """``/NH`` 之外万一带了表头，也不能把列名当数字（列名本来就不是数字）。"""
        text = '"Image Name","PID","Session Name"\n"a.exe","3","C"\n'
        assert ga.parse_tasklist_pids(text) == [3]


# ────────────────────────── 图像：ROI / 空白 / 通道 ──────────────────────────


class TestRoi:
    def test_相对换算(self) -> None:
        assert ga.roi_box((0.0, 0.5, 1.0, 1.0), 1920, 1080) == (0, 540, 1920, 1080)

    def test_夹到图像内(self) -> None:
        assert ga.roi_box((-0.5, -0.5, 2.0, 2.0), 100, 50) == (0, 0, 100, 50)

    def test_右上角_ROI_就是播放键那个区域(self) -> None:
        left, top, right, bottom = ga.roi_box(ga.TOP_RIGHT_ROI, 1920, 1080)
        assert (left, top, right) == (1536, 0, 1920)
        assert 0 < bottom <= 130

    def test_底部_ROI_含观察按钮的实测坐标(self) -> None:
        left, top, right, bottom = ga.roi_box(ga.BOTTOM_ROI, 1920, 1080)
        assert left <= 755  # 模板实测 box 的左边界
        assert right >= 973  # 右边界
        assert top <= 1037 <= bottom


class TestBlankDetection:
    def test_纯黑判为空白(self) -> None:
        assert ga.is_blank(Image.new("RGB", (200, 200), (0, 0, 0))) is True

    def test_纯色加载画面判为空白(self) -> None:
        assert ga.is_blank(Image.new("RGB", (200, 200), (24, 24, 24))) is True

    def test_有纹理就不是空白(self) -> None:
        assert ga.is_blank(textured(200, 200)) is False


class TestChannels:
    def test_灰度被升成三通道(self) -> None:
        gray = np.zeros((4, 4), dtype=np.uint8)
        assert ga.to_bgr(gray).shape == (4, 4, 3)

    def test_RGBA_被降成三通道(self) -> None:
        rgba = np.zeros((4, 4, 4), dtype=np.uint8)
        assert ga.to_bgr(rgba).shape == (4, 4, 3)

    def test_三通道原样返回(self) -> None:
        bgr = np.zeros((4, 4, 3), dtype=np.uint8)
        assert ga.to_bgr(bgr).shape == (4, 4, 3)


# ────────────────────────── 模板匹配 ──────────────────────────


class TestMatching:
    def test_找到正确中心(self) -> None:
        screen = textured(400, 300, seed=1)
        patch = textured(40, 20, seed=2)
        screen.paste(patch, (100, 50))
        found = ga.match_template(np.array(screen), np.array(patch), name="p", threshold=0.9)
        assert found is not None
        assert (found.x, found.y) == (120, 60)  # 贴图中心 = 100+20, 50+10
        assert found.score > 0.99

    def test_找不到就给_None(self) -> None:
        screen = textured(400, 300, seed=1)
        patch = textured(40, 20, seed=99)
        found = ga.match_template(np.array(screen), np.array(patch), name="p", threshold=0.95)
        assert found is None

    def test_阈值是硬门(self) -> None:
        screen = textured(200, 200, seed=5)
        patch = np.array(screen)[100:120, 100:140].copy()
        # 同一块图像自匹配必然 1.0；把阈值抬到 1.0 以上就该被挡掉
        assert ga.match_template(np.array(screen), patch, threshold=1.5) is None

    def test_ROI_之外的同款贴图不会被误认(self) -> None:
        screen = textured(400, 300, seed=3)
        patch = np.array(textured(30, 10, seed=4))
        screen.paste(Image.fromarray(patch), (20, 20))  # 在左上角
        found = ga.match_template(
            np.array(screen),
            patch,
            name="p",
            threshold=0.9,
            roi=(0.5, 0.5, 1.0, 1.0),  # 只搜右下角
        )
        assert found is None

    def test_ROI_内的贴图坐标要加回偏移(self) -> None:
        screen = textured(400, 300, seed=6)
        patch = np.array(textured(30, 10, seed=8))
        screen.paste(Image.fromarray(patch), (300, 200))
        found = ga.match_template(
            np.array(screen),
            patch,
            name="p",
            threshold=0.9,
            roi=(0.5, 0.5, 1.0, 1.0),
        )
        assert found is not None
        assert (found.x, found.y) == (315, 205)

    def test_多尺度能认缩放过的贴图(self) -> None:
        screen = textured(600, 400, seed=11)
        patch = textured(80, 40, seed=12)
        shrunk = patch.resize((64, 32), Image.Resampling.LANCZOS)
        screen.paste(shrunk, (200, 150))
        found = ga.match_template(
            np.array(screen),
            np.array(patch),
            name="p",
            threshold=0.8,
            scales=(1.0, 0.8),
        )
        assert found is not None
        assert found.scale == pytest.approx(0.8)
        assert abs(found.x - (200 + 32)) <= 1
        assert abs(found.y - (150 + 16)) <= 1

    def test_模板比搜索区大时不炸(self) -> None:
        screen = textured(100, 100, seed=13)
        patch = textured(300, 300, seed=14)
        assert ga.match_template(np.array(screen), np.array(patch), threshold=0.1) is None

    def test_零尺度被跳过(self) -> None:
        screen = textured(100, 100, seed=15)
        patch = textured(10, 10, seed=16)
        assert ga.match_template(np.array(screen), np.array(patch), scales=(0.0, -1.0)) is None

    def test_找不到必须报错而不是给个默认坐标(self) -> None:
        """P13：按钮没找到就报错。**绝不允许**"点了就算了"。"""
        screen = textured(300, 300, seed=17)
        patch = textured(30, 30, seed=18)
        with pytest.raises(ga.TemplateNotFoundError, match="没匹配上"):
            ga.find_template(np.array(screen), np.array(patch), name="btn_x")

    def test_灰度截图与灰度模板也能配(self) -> None:
        """单通道这条支路要走通（``to_bgr`` 的 ``ndim == 2`` 分支）。

        真机上截图是 RGB，但壁纸/加载画面可能被系统降成灰度，
        而通道数不一致时 ``matchTemplate`` 会直接抛 —— 所以这里钉住"能配上"。
        """
        screen = textured(300, 300, seed=19).convert("L")
        patch_img = textured(20, 20, seed=20).convert("L")
        screen.paste(patch_img, (77, 88))
        found = ga.match_template(np.array(screen), np.array(patch_img), threshold=0.8)
        assert found is not None
        assert (found.x, found.y) == (87, 98)

    def test_四通道模板不会让匹配抛异常(self) -> None:
        """通道数不一致时**不许抛** —— 归一化是 ``to_bgr`` 的职责。"""
        screen = textured(200, 200, seed=21)
        rgba = np.dstack([np.array(textured(20, 20, seed=22)), np.full((20, 20, 1), 255)])
        assert rgba.shape[2] == 4
        result = ga.match_template(np.array(screen), rgba.astype(np.uint8), threshold=0.9)
        assert result is None or result.score >= 0.9


@needs_templates
class TestRealTemplates:
    """用**入库的真模板**在合成画面上走完整路径（load_template → 匹配）。"""

    def test_观察按钮能被定位在贴上去的地方(self) -> None:
        screen = textured()
        cx, cy = paste(screen, OBSERVE_TPL, 800, 1030)
        found = ga.locate(screen, "btn_observe", roi=ga.BOTTOM_ROI)
        assert abs(found.x - cx) <= 2
        assert abs(found.y - cy) <= 2
        assert found.score > 0.95

    def test_观察按钮不在时_locate_报错(self) -> None:
        with pytest.raises(ga.TemplateNotFoundError):
            ga.locate(textured(), "btn_observe", roi=ga.BOTTOM_ROI)

    def test_观察按钮不在时_locate_optional_给_None(self) -> None:
        assert ga.locate_optional(textured(), "btn_observe", roi=ga.BOTTOM_ROI) is None

    def test_播放键在右上_ROI_里被定位(self) -> None:
        screen = textured()
        cx, cy = paste(screen, PLAY_TPL, 1712, 46)
        found = ga.locate(screen, "btn_play", roi=ga.TOP_RIGHT_ROI)
        assert abs(found.x - cx) <= 2
        assert abs(found.y - cy) <= 2

    def test_播放键不会被底部_ROI_找到(self) -> None:
        """ROI 是真的在起作用：贴在图上的播放键，用底部 ROI 搜不到。"""
        screen = textured()
        paste(screen, PLAY_TPL, 1712, 46)
        assert ga.locate_optional(screen, "btn_play", roi=ga.BOTTOM_ROI) is None

    def test_模板文件缺失时报错(self, tmp_path: Path) -> None:
        with pytest.raises(ga.TemplateNotFoundError, match="模板文件不存在"):
            ga.load_template("btn_nope", tmp_path)

    def test_load_template_给的是三通道数组(self) -> None:
        assert ga.load_template("btn_observe").shape[2] == 3


# ────────────────────────── 等待与超时 ──────────────────────────


class TestWaitUntil:
    def test_立刻为真(self) -> None:
        assert (
            ga.wait_until(lambda: True, timeout=10, clock=lambda: 0.0, sleeper=lambda _s: None)
            is True
        )

    def test_超时返回最后一次假值(self) -> None:
        ticks = iter([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])

        def clock() -> float:
            return next(ticks, 99.0)

        assert (
            ga.wait_until(lambda: False, timeout=2.0, clock=clock, sleeper=lambda _s: None) is False
        )

    def test_非可调用直接拒绝(self) -> None:
        with pytest.raises(TypeError, match="predicate"):
            ga.wait_until(42, timeout=1)

    def test_时钟不可调用也拒绝(self) -> None:
        with pytest.raises(TypeError, match="clock"):
            ga.wait_until(lambda: True, timeout=1, clock=42)


class TestWaitUntilRunning:
    def test_tick_前进即成功(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        log = tmp_path / "t.log"
        log.write_text("Processing Tick: 1836.5.1\n", encoding="utf-8")
        before = ga.tick_mark(log)
        log.write_text("Processing Tick: 1836.5.1\nProcessing Tick: 1836.6.1\n", encoding="utf-8")
        advance = ga.wait_until_running(
            before,
            timeout=5,
            interval=0,
            log=log,
            clock=lambda: 0.0,
            sleeper=lambda _s: None,
        )
        assert advance.advanced is True
        assert (advance.before, advance.after) == ("1836.5.1", "1836.6.1")

    def test_超时要报错并说清现状(self, tmp_path: Path) -> None:
        log = tmp_path / "t.log"
        log.write_text("Processing Tick: 1836.5.1\n", encoding="utf-8")
        seen = iter([0.0, 1.0, 2.0, 3.0, 4.0, 99.0])

        def clock() -> float:
            return next(seen, 99.0)

        with pytest.raises(ga.NotRunningError, match=r"1836\.5\.1"):
            ga.wait_until_running(
                timeout=2.0, interval=0, log=log, clock=clock, sleeper=lambda _s: None
            )

    def test_日志读不到时也报错而不是假装在跑(self, tmp_path: Path) -> None:
        seen = iter([0.0, 1.0, 2.0, 3.0, 4.0, 99.0])
        with pytest.raises(ga.NotRunningError, match="读不到"):
            ga.wait_until_running(
                timeout=2.0,
                interval=0,
                log=tmp_path / "missing.log",
                clock=lambda: next(seen, 99.0),
                sleeper=lambda _s: None,
            )

    def test_is_running_用_tick_而不是日志长度(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """暂停时不写日志 —— 所以"日志没长"根本不能当判据。"""
        log = tmp_path / "t.log"
        log.write_text("Processing Tick: 1836.5.1\n", encoding="utf-8")
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        assert ga.is_running(1.0, log=log).advanced is False


# ────────────────────────── 前台：那条踩过的坑 ──────────────────────────


class TestForeground:
    def test_已经是前台就直接过(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "_foreground_window", lambda: 777)
        monkeypatch.setattr(ga, "_set_foreground", lambda _h: pytest.fail("已经是前台，不该再抢"))
        ga.ensure_foreground(777)  # 不抛就是过

    def test_已经是前台但窗口最小化也必须报错(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """t29 的"假成功"（2026-10-01 实测）：最小化窗口上 `SetForegroundWindow` 会成功。

        `GetForegroundWindow()` 返回了它 ⇒ 老判据放行 ⇒ 恢复路径**不会被调用** ⇒
        实机链最后死在「客户区尺寸非法: 0x0」。所以"已经是前台"这条早退也要看 `IsIconic`。
        """
        monkeypatch.setattr(ga, "_foreground_window", lambda: 777)
        monkeypatch.setattr(ga, "_is_iconic", lambda _h: True)
        monkeypatch.setattr(ga, "_window_title", lambda _h: "Victoria 3")
        monkeypatch.setattr(ga, "_set_foreground", lambda _h: pytest.fail("已经是前台，不该再抢"))
        with pytest.raises(ga.ForegroundLostError, match="最小化"):
            ga.ensure_foreground(777)

    def test_循环里拿到前台但窗口还最小化也要报错(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """同一族的第二条出口：置前循环"成功"之后也要复查窗口状态。"""
        monkeypatch.setattr(ga, "ALLOW_REAL_INPUT", True)
        monkeypatch.setattr(ga, "_window_title", lambda _h: "Victoria 3")
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        monkeypatch.setattr(ga, "FOREGROUND_SETTLE", 0.0)
        monkeypatch.setattr(ga, "WINDOW_SHOW_SETTLE", 0.0)
        monkeypatch.setattr(ga, "_restore", lambda _h: None)  # 还原动作本身不真做
        monkeypatch.setattr(ga, "_set_foreground", lambda _h: True)
        seen: list[int] = []

        def fg() -> int:
            seen.append(1)
            return 777 if len(seen) > 1 else 1234  # 抢之前不是它，抢之后是它（但最小化）

        monkeypatch.setattr(ga, "_foreground_window", fg)
        monkeypatch.setattr(ga, "_is_iconic", lambda _h: True)
        with pytest.raises(ga.ForegroundLostError, match="最小化"):
            ga.ensure_foreground(777, attempts=1)

    def test_等到前台的循环也不收最小化窗口(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """另一处"等到前台"的出口（`_ensure_live_foreground`）同族，同样要查 `IsIconic`。"""
        monkeypatch.setattr(ga, "_live_window", lambda h: h)
        monkeypatch.setattr(ga, "_foreground_window", lambda: 777)
        monkeypatch.setattr(ga, "_is_iconic", lambda _h: True)
        monkeypatch.setattr(ga, "_window_title", lambda _h: "Victoria 3")
        monkeypatch.setattr(ga, "_set_foreground", lambda _h: True)
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        monkeypatch.setattr(ga, "FOREGROUND_SETTLE", 0.0)
        monkeypatch.setattr(ga, "FOREGROUND_POLL", 0.0)
        with pytest.raises(ga.ForegroundLostError, match="最小化"):
            ga._ensure_live_foreground(777)

    def test_抢不到必须报错而不是照点(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """这正是当初把"点击无效"误判成"坐标不准"的那个坑。"""
        monkeypatch.setattr(ga, "ALLOW_REAL_INPUT", True)  # 显式入口：允许借前台
        monkeypatch.setattr(ga, "_set_foreground", lambda _h: False)
        monkeypatch.setattr(ga, "_foreground_window", lambda: 1234)
        monkeypatch.setattr(ga, "_window_title", lambda _h: "Edge")
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        monkeypatch.setattr(ga, "FOREGROUND_SETTLE", 0.0)
        with pytest.raises(ga.ForegroundLostError, match="抢不到前台"):
            ga.ensure_foreground(777, attempts=2)

    def test_判据是前台窗口不是库的返回值(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`activate()` 不抛异常 ≠ 抢到了：Windows 前台锁定会**静默失败**。

        所以这里让库调用"成功"、而 `GetForegroundWindow()` 始终不是游戏 —— 必须报错。
        """
        monkeypatch.setattr(ga, "ALLOW_REAL_INPUT", True)
        monkeypatch.setattr(ga, "_set_foreground", lambda _h: True)
        monkeypatch.setattr(ga, "_foreground_window", lambda: 1234)
        monkeypatch.setattr(ga, "_window_title", lambda _h: "DeepSeek Harness")
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        monkeypatch.setattr(ga, "FOREGROUND_SETTLE", 0.0)
        with pytest.raises(ga.ForegroundLostError, match="抢不到前台"):
            ga.ensure_foreground(777, attempts=1)

    def test_没授权就借前台必须拒绝(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "ALLOW_REAL_INPUT", False)
        monkeypatch.setattr(ga, "_set_foreground", lambda _h: pytest.fail("不许碰真实窗口"))
        with pytest.raises(ga.RealInputBlockedError):
            ga.ensure_foreground(777)


class TestClick:
    """点击的注入走成熟库 `pydirectinput`（`moveTo` + `click`），所以这里打的是它的桩。

    换库的理由与"它能不能解决后台点击"无关（那条已被实测判死，见 `click_client` 的 docstring）——
    只是这段 Win32 细节该由库维护，不该我们自己拼 `SetCursorPos` + `mouse_event`。
    """

    def _patch_input(
        self, monkeypatch: pytest.MonkeyPatch, moved: list[tuple[int, int]], events: list[str]
    ) -> None:
        from types import SimpleNamespace

        at: dict[str, tuple[int, int]] = {"xy": (0, 0)}

        def move_to(x: int, y: int) -> None:
            moved.append((x, y))
            at["xy"] = (x, y)
            events.append("cursor")

        def click() -> None:
            events.append("mouse")

        monkeypatch.setattr(ga, "ALLOW_REAL_INPUT", True)  # 显式入口才允许投真实输入
        monkeypatch.setattr(
            ga,
            "directinput",
            # `position()` 是"等光标真的到了"那条条件等待的判据（不再用固定 sleep）。
            SimpleNamespace(moveTo=move_to, click=click, position=lambda: at["xy"]),
        )

    def test_客户区坐标要加上窗口原点(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """窗口不在 (0,0) 时，客户区坐标 ≠ 屏幕坐标 —— 这里必须换算。"""
        moved: list[tuple[int, int]] = []
        events: list[str] = []
        monkeypatch.setattr(ga, "ensure_foreground", lambda _hwnd, **_kw: None)
        monkeypatch.setattr(ga, "_client_origin", lambda _hwnd: (100, 50))
        self._patch_input(monkeypatch, moved, events)
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)

        ga.click_client(1, 10, 20)

        assert moved == [(110, 70)]
        assert events == ["cursor", "mouse"]

    def test_窗口在原点时坐标不变(self, monkeypatch: pytest.MonkeyPatch) -> None:
        moved: list[tuple[int, int]] = []
        monkeypatch.setattr(ga, "ensure_foreground", lambda _hwnd, **_kw: None)
        monkeypatch.setattr(ga, "_client_origin", lambda _hwnd: (0, 0))
        self._patch_input(monkeypatch, moved, [])
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        ga.click_client(1, 864, 1055)
        assert moved == [(864, 1055)]

    def test_先抢前台再点(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        moved: list[tuple[int, int]] = []
        monkeypatch.setattr(ga, "ensure_foreground", lambda _hwnd, **_kw: calls.append("fg"))
        monkeypatch.setattr(ga, "_client_origin", lambda _hwnd: (0, 0))
        self._patch_input(monkeypatch, moved, calls)
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        ga.click_client(1, 0, 0)
        assert calls == ["fg", "cursor", "mouse"]


# ────────────────────────── 抓图 ──────────────────────────


class TestScreenshot:
    def test_全黑画面被挡住(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            ga, "_grab", lambda _hwnd, _roi=None: Image.new("RGB", (100, 100), (0, 0, 0))
        )
        with pytest.raises(ga.CaptureFailedError, match="纯色"):
            ga.screenshot(1)

    def test_有内容就放行(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "_grab", lambda _hwnd, _roi=None: textured(100, 100))
        assert ga.screenshot(1).size == (100, 100)


# ────────────────────────── 动作：观察者 / 暂停 / 后台 ──────────────────────────


class FakeClock:
    """假时钟：``sleep`` 推进它，于是超时逻辑不需要真的等。"""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TickLog:
    """可控的 tick 日志。"""

    def __init__(self, path: Path, value: str = "1836.1.1") -> None:
        self.path = path
        self.value = value
        self.write()

    def write(self) -> None:
        self.path.write_text(f"Processing Tick: {self.value}\n", encoding="utf-8")

    def set(self, value: str) -> None:
        self.value = value
        self.write()


class TestBackground:
    def test_后台仍在推进(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        ticks = TickLog(tmp_path / "t.log", "1836.9.20")
        monkeypatch.setattr(ga, "TICK_LOG", ticks.path)
        monkeypatch.setattr(ga, "other_window", lambda _exclude: 55)
        monkeypatch.setattr(ga, "ensure_foreground", lambda _hwnd, **_kw: None)
        monkeypatch.setattr(ga, "_foreground_window", lambda: 55)
        monkeypatch.setattr(ga, "_sleep", lambda _s: ticks.set("1836.11.11"))

        advance = ga.background_ok(777, seconds=20.0)
        assert advance.advanced is True
        assert "后台" in advance.source

    def test_显式授权会传给让出和恢复前台(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ticks = TickLog(tmp_path / "t.log", "1836.9.20")
        calls: list[tuple[int, bool]] = []
        monkeypatch.setattr(ga, "TICK_LOG", ticks.path)
        monkeypatch.setattr(ga, "other_window", lambda _exclude: 55)

        def fake_foreground(hwnd: int, *, force: bool = False) -> None:
            calls.append((hwnd, force))

        monkeypatch.setattr(ga, "ensure_foreground", fake_foreground)
        monkeypatch.setattr(ga, "_foreground_window", lambda: 55)
        monkeypatch.setattr(ga, "_sleep", lambda _s: ticks.set("1836.11.11"))

        advance = ga.background_ok(777, seconds=20.0, force=True)

        assert advance.advanced is True
        assert calls == [(55, True), (777, True)]

    def test_默认不授权仍传入安全闸门(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ticks = TickLog(tmp_path / "t.log", "1836.9.20")
        calls: list[tuple[int, bool]] = []
        monkeypatch.setattr(ga, "TICK_LOG", ticks.path)
        monkeypatch.setattr(ga, "other_window", lambda _exclude: 55)

        def fake_foreground(hwnd: int, *, force: bool = False) -> None:
            calls.append((hwnd, force))

        monkeypatch.setattr(ga, "ensure_foreground", fake_foreground)
        monkeypatch.setattr(ga, "_foreground_window", lambda: 55)
        monkeypatch.setattr(ga, "_sleep", lambda _s: ticks.set("1836.11.11"))

        ga.background_ok(777, seconds=20.0)

        assert calls == [(55, False), (777, False)]

    def test_后台期间会刷新仍存活游戏的窗口句柄(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ticks = TickLog(tmp_path / "t.log", "1836.9.20")
        calls: list[int] = []
        monkeypatch.setattr(ga, "TICK_LOG", ticks.path)
        monkeypatch.setattr(ga, "other_window", lambda _exclude: 55)
        monkeypatch.setattr(ga, "_process_pids", lambda: [123])

        def live_window(hwnd: int) -> int:
            calls.append(hwnd)
            return 888

        monkeypatch.setattr(ga, "_live_window", live_window)
        monkeypatch.setattr(ga, "ensure_foreground", lambda _hwnd, **_kw: None)
        monkeypatch.setattr(ga, "_foreground_window", lambda: 55)
        monkeypatch.setattr(ga, "_sleep", lambda _s: ticks.set("1836.11.11"))

        advance = ga.background_ok(777, seconds=1.0)

        assert advance.advanced is True
        assert calls == [777, 888]

    def test_没有别的窗口可用时报错(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(ga, "TICK_LOG", tmp_path / "t.log")
        monkeypatch.setattr(ga, "other_window", lambda _exclude: 0)
        with pytest.raises(ga.GameAutoError, match="非游戏窗口"):
            ga.background_ok(777)

    def test_前台没让出去就不敢下结论(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(ga, "TICK_LOG", tmp_path / "t.log")
        monkeypatch.setattr(ga, "other_window", lambda _exclude: 55)
        monkeypatch.setattr(ga, "ensure_foreground", lambda _hwnd, **_kw: None)
        monkeypatch.setattr(ga, "_foreground_window", lambda: 777)  # 还是游戏
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        with pytest.raises(ga.ForegroundLostError, match="让出去"):
            ga.background_ok(777)


# ────────────────────────── 启动 ──────────────────────────


class FakeLaunchCommand:
    """替掉 ``experiments.launch_command``：只回一条含假 exe 的命令。

    用类而不是 lambda：``debug`` 形参在这里是"故意不用"的（本组用例只关心
    最终命令行长什么样），写成方法可以让 ARG002 这条豁免（测试目录已忽略）生效，
    而不是塞一个 `lambda *, debug=True:` 让 ruff 报未使用形参。
    """

    def __init__(self, exe: Path) -> None:
        self.exe = exe

    def __call__(self, *, debug: bool = True) -> list[str]:
        del debug
        return [str(self.exe)]


class MissingExeLaunchCommand:
    """回一条指向不存在文件的命令，用来打"可执行文件不存在"这条支路。"""

    def __call__(self, *, debug: bool = True) -> list[str]:
        del debug
        return [r"C:\nope\victoria3.exe"]


def _record_popen(seen: dict[str, object]) -> object:
    """造一个只记账的 ``subprocess.Popen`` 替身。"""

    def fake_popen(command: list[str], **kwargs: object) -> object:
        seen["command"] = command
        seen["kwargs"] = kwargs
        return object()

    return fake_popen


def _recorder(sink: list[str], *, prefix: str = "set:") -> Callable[[int], bool]:
    """造一个"记一笔并返回 True"的桩。

    为什么不写 `lambda h: sink.append(f"{prefix}{h}") or True`：`list.append` 只返回
    `None`，在布尔表达式里用它的返回值会被 mypy 判 `func-returns-value`
    （实测：这类写法在 `.mypy_cache` 里躲了很久，重跑整张图才露出来）。
    """

    def record(value: int) -> bool:
        sink.append(f"{prefix}{value}")
        return True

    return record


def _screenshot_stub(seen: list[tuple[float, float, float, float]], image: Image.Image):
    """记下 ROI 再返回一张假图（同上的理由：不要在 lambda 里用 list 方法返回值）。

    形参类型写成**精确的 ROI 元组**而不是 `list[object]`：`list` 不变，
    传 `list[tuple[float, float, float, float]]` 进去会被 mypy 判 `arg-type`
    （它给的建议是改用 `Sequence`，但这里要的正是"能 append 的那个 list"）。
    """

    def grab(_hwnd: int, roi: tuple[float, float, float, float] | None = None) -> Image.Image:
        assert roi is not None, "这个桩只在带 ROI 调用时用"
        seen.append(roi)
        return image

    return grab


class TestQuarantineLogs:
    """挪日志的纪律：**被占用的文件跳过、不报错**（实测两次踩到 `WinError 32`）。"""

    def test_把日志挪走并返回文件名(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        logs = tmp_path / "logs"
        logs.mkdir()
        (logs / "debug.log").write_text("a", encoding="utf-8")
        (logs / "ai.log").write_text("b", encoding="utf-8")
        monkeypatch.setattr(ga, "USER_LOGS_DIR", logs)
        dest = tmp_path / "quarantine"
        assert ga.quarantine_logs(dest) == ["ai.log", "debug.log"]
        assert (dest / "debug.log").read_text(encoding="utf-8") == "a"
        assert not list(logs.glob("*.log")), "挪完原目录不该还剩日志"

    def test_被占用的文件跳过而不是整局崩掉(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """`ai.log` 被别的进程握着时 `shutil.move` 抛 `PermissionError` ——
        阶段 3 重做的脚本因此**整局还没开始就崩**（而且崩的时候用户配置已经被改了）。"""
        logs = tmp_path / "logs"
        logs.mkdir()
        (logs / "ai.log").write_text("b", encoding="utf-8")
        (logs / "system.log").write_text("c", encoding="utf-8")
        monkeypatch.setattr(ga, "USER_LOGS_DIR", logs)

        real_move = ga.shutil.move

        def flaky_move(src: str, dst: str) -> str:
            if src.endswith("ai.log"):
                raise PermissionError(32, "另一个程序正在使用此文件")
            return real_move(src, dst)

        monkeypatch.setattr(ga.shutil, "move", flaky_move)
        assert ga.quarantine_logs(tmp_path / "q") == ["system.log"]

    def test_没有日志目录时给空列表(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(ga, "USER_LOGS_DIR", tmp_path / "不存在")
        assert ga.quarantine_logs(tmp_path / "q") == []


class Test日志归档不丢证据:
    """t71：轮转 / 同名冲突下**不许丢证据** —— 归档件逐字节等于挪走前那一份。

    为什么落在本文件：t71 的 inScope 就是 `game_auto` + `h1_probe` + 本文件三个
    （h1 那两处走它们自己的公开入口练，不新增第四个文件）。

    病根（要修的那条路径，两条都实测过，原始读数见 `tools/out/t15-drill/drill.log` 的 seq7）：
    ① 目标**文件**已存在时 `shutil.move` 一声不响地**覆盖**它 —— 上一代归档件被无声替换、这一份
    又从原目录消失，两边都看不出来；② 目标是个**目录**、里面已有同名项时它抛 `shutil.Error`，而它
    是 `OSError` 的子类 ⇒ 被调用点 `except OSError` 的兜底吞掉、文件**留在原地**混进下一局。
    """

    @staticmethod
    def _sha256_dir(directory: Path) -> dict[str, str]:
        """目录里每个 `*.log` 的 sha256 —— "逐字节相同"的原始读数。"""
        return {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.glob("*.log"))
        }

    def test_归档件与挪走前逐字节相同(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        logs = tmp_path / "logs"
        logs.mkdir()
        (logs / "debug.log").write_bytes(
            "".join(f"第 {i} 行：debug 的尾巴\n" for i in range(400)).encode()
        )
        (logs / "error.1.log").write_bytes(b"error rotated\n")
        monkeypatch.setattr(ga, "USER_LOGS_DIR", logs)
        before = self._sha256_dir(logs)
        dest = tmp_path / "q"
        assert ga.quarantine_logs(dest) == ["debug.log", "error.1.log"]
        assert self._sha256_dir(dest) == before, "挪走的是**字节**，不是名字"
        assert not list(logs.glob("*.log")), "原目录不该还留着日志（留着就等于混进下一局）"

    def test_同名目标已存在时换名_不覆盖也不留在原地(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """同名冲突**不是**"被占用"：这一份也必须进归档目录，旧的那一份一个字节不动。"""
        logs = tmp_path / "logs"
        logs.mkdir()
        (logs / "debug.log").write_text("这一局", encoding="utf-8")
        monkeypatch.setattr(ga, "USER_LOGS_DIR", logs)
        dest = tmp_path / "q"
        dest.mkdir()
        (dest / "debug.log").write_text("上一局（一个字节都不许动）", encoding="utf-8")
        assert ga.quarantine_logs(dest, stamp="20260928-231500") == ["debug.20260928-231500.log"]
        assert (dest / "debug.log").read_text(encoding="utf-8") == "上一局（一个字节都不许动）"
        assert (dest / "debug.20260928-231500.log").read_text(encoding="utf-8") == "这一局"
        assert not list(logs.glob("*.log")), "冲突 ≠ 跳过：静默留在原地就是证据蒸发"

    def test_同一时间戳连着归档三代_退到减2减3(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """时间戳只到秒：同一秒里的第二、第三代必须继续退（`-2`、`-3`），一个都不许覆盖。"""
        logs = tmp_path / "logs"
        logs.mkdir()
        monkeypatch.setattr(ga, "USER_LOGS_DIR", logs)
        dest = tmp_path / "q"
        dest.mkdir()
        (dest / "debug.log").write_text("第 0 代", encoding="utf-8")
        names: list[str] = []
        for generation in ("第 1 代", "第 2 代", "第 3 代"):
            (logs / "debug.log").write_text(generation, encoding="utf-8")
            names += ga.quarantine_logs(dest, stamp="20260928-231500")
        assert names == [
            "debug.20260928-231500.log",
            "debug.20260928-231500-2.log",
            "debug.20260928-231500-3.log",
        ]
        assert (dest / "debug.log").read_text(encoding="utf-8") == "第 0 代"
        assert [(dest / name).read_text(encoding="utf-8") for name in names] == [
            "第 1 代",
            "第 2 代",
            "第 3 代",
        ]

    def test_unused_path_空着用原名_被占插时间戳(self, tmp_path: Path) -> None:
        free = tmp_path / "debug.log"
        assert ga.unused_path(free, stamp="20260928-231500") == free
        free.write_text("占住", encoding="utf-8")
        first = ga.unused_path(free, stamp="20260928-231500")
        assert first.name == "debug.20260928-231500.log", "时间戳插在扩展名前，名字还能认出来"
        first.write_text("再占住", encoding="utf-8")
        assert ga.unused_path(free, stamp="20260928-231500").name == "debug.20260928-231500-2.log"

    def test_时间戳是_UTC_而且可注入(self) -> None:
        assert (
            ga.archive_stamp(now=datetime(2026, 9, 28, 23, 15, 0, tzinfo=UTC)) == "20260928-231500"
        )

    def test_h1_归档同一个tag第二次不覆盖旧的那一代(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """`archive_logs` 的 `skipped` 曾经把"同名冲突"混进"被游戏占用"里 —— 现在换目录。"""
        monkeypatch.setattr(config, "USERDIR", tmp_path)
        logs = tmp_path / "logs"
        logs.mkdir()
        (logs / "debug.log").write_text("第一代", encoding="utf-8")
        first, moved, skipped = h1_probe.archive_logs(
            "run-1", log_dir=logs, stamp="20260928-231500"
        )
        assert (moved, skipped) == (1, 0)
        assert first.name == "run-1"
        (logs / "debug.log").write_text("第二代", encoding="utf-8")
        second, moved2, skipped2 = h1_probe.archive_logs(
            "run-1", log_dir=logs, stamp="20260928-231500"
        )
        assert (moved2, skipped2) == (1, 0), "同名冲突不许记成'被占用'，更不许留在原地"
        assert second.name == "run-1.20260928-231500"
        assert (first / "debug.log").read_text(encoding="utf-8") == "第一代"
        assert (second / "debug.log").read_text(encoding="utf-8") == "第二代"

    def test_h1_监视器同名快照不覆盖(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """`copy2` 默认**静默覆盖** —— 同一个 tag 跑第二次时，旧快照必须原样还在。"""
        monkeypatch.setattr(config, "USERDIR", tmp_path)
        monkeypatch.setattr(ga, "archive_stamp", lambda **_kw: "20260928-231500")
        logs = tmp_path / "logs"
        logs.mkdir()
        (logs / "debug.log").write_text("第一轮", encoding="utf-8")
        first, rounds, copied, skipped = h1_probe.watch(
            "tag-1",
            log_dir=logs,
            interval=0.0,
            max_minutes=0.02,
            sleep=lambda _s: None,
            running=lambda: True,
        )
        assert (rounds, copied, skipped) == (1, 1, 0)
        snapshot = first / "s0001-debug.log"
        assert snapshot.read_text(encoding="utf-8") == "第一轮"
        (logs / "debug.log").write_text("第二轮", encoding="utf-8")
        second, *_ = h1_probe.watch(
            "tag-1",
            log_dir=logs,
            interval=0.0,
            max_minutes=0.02,
            sleep=lambda _s: None,
            running=lambda: True,
        )
        assert second == first
        assert snapshot.read_text(encoding="utf-8") == "第一轮", "旧快照被静默覆盖 = 证据蒸发"
        assert (first / "s0001-debug.20260928-231500.log").read_text(encoding="utf-8") == "第二轮"


class TestKillGame:
    """收尾纪律：会话结束后**不能留进程**（它会握着日志句柄、污染下一次取证）。"""

    def test_每个进程都杀一遍并返回_PID(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "_process_pids", lambda: [111, 222])
        seen: list[int] = []

        class FakeProcess:
            def __init__(self, pid: int) -> None:
                self.pid = pid

            def kill(self) -> None:
                seen.append(self.pid)

        monkeypatch.setattr(ga.psutil, "Process", FakeProcess)
        assert ga.kill_game() == [111, 222]
        assert seen == [111, 222]

    def test_没在跑就一条命令都不发(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "_process_pids", list)

        def boom(*args: object, **kwargs: object) -> object:
            pytest.fail("没有进程时不该创建进程句柄")

        monkeypatch.setattr(ga.psutil, "Process", boom)
        assert ga.kill_game() == []

    def test_杀不掉也要如实返回_PID(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        """权限不足不该让**收尾**这一步炸掉 ——
        调用方在 `finally` 里用它，抛异常会把"还前台"那一步一起带走。"""
        monkeypatch.setattr(ga, "_process_pids", lambda: [333])

        def boom(*args: object, **kwargs: object) -> object:
            raise ga.psutil.AccessDenied(333)

        monkeypatch.setattr(ga.psutil, "Process", boom)
        assert ga.kill_game() == []
        assert "333" in capsys.readouterr().err

    def test_只清理本模块登记的进程(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ga._OWNED_GAME_PIDS.clear()
        ga._OWNED_GAME_PIDS.add(111)
        seen: list[int] = []

        class Child:
            def __init__(self, pid: int) -> None:
                self.pid = pid

        class FakeProcess:
            def __init__(self, pid: int) -> None:
                self.pid = pid

            def children(self, recursive: bool = False) -> list[Child]:
                assert recursive
                return [Child(222)] if self.pid == 111 else []

            def kill(self) -> None:
                seen.append(self.pid)

        monkeypatch.setattr(ga.psutil, "Process", FakeProcess)
        monkeypatch.setattr(ga, "_wait_for_pids", lambda _pids: [])
        assert ga.kill_owned_game() == [222, 111]
        assert seen == [222, 111]
        assert not ga._OWNED_GAME_PIDS

    def test_清理后仍存活的进程会出声(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ga._OWNED_GAME_PIDS.clear()
        ga._OWNED_GAME_PIDS.add(111)

        class FakeProcess:
            def __init__(self, pid: int) -> None:
                self.pid = pid

            def children(self, recursive: bool = False) -> list[object]:
                del recursive
                return []

            def kill(self) -> None:
                return None

        monkeypatch.setattr(ga.psutil, "Process", FakeProcess)
        monkeypatch.setattr(ga, "_wait_for_pids", lambda _pids: [111])
        assert ga.kill_owned_game() == [111]
        assert "仍存活" in capsys.readouterr().err


class TestLaunch:
    def test_有进程在跑就拒绝启动(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """两个实例会互相抢前台与存档 —— 起之前必须断言 0 个进程。"""
        monkeypatch.setattr(ga, "_process_pids", lambda: [19084])
        with pytest.raises(ga.GameRunningError, match="19084"):
            ga.launch(wait=False)

    def test_零进程时放行并带上自动化开关(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fake_exe = tmp_path / "victoria3.exe"
        fake_exe.write_bytes(b"MZ")
        monkeypatch.setattr(ga.experiments, "launch_command", FakeLaunchCommand(fake_exe))
        monkeypatch.setattr(ga, "_process_pids", list)
        seen: dict[str, object] = {}

        def fake_popen(command: list[str], **kwargs: object) -> object:
            seen["command"] = command
            seen["kwargs"] = kwargs
            return object()

        monkeypatch.setattr(ga.subprocess, "Popen", fake_popen)
        assert ga.launch(wait=False) is None
        assert seen["command"] == [str(fake_exe), ga.SCRIPTED_TESTS_ARG]
        # 启动就是**普通启动**（用户口径："直接用之前那套测试的怎么启动就怎么启动"）：
        # 不带任何窗口样式变体。三种变体都实测过并已删：创建时最小化（游戏**崩**，
        # 栈在 nvoglv64.dll）、显示但不激活（照样铺满屏幕）、出现后再最小化（不是用户要的）。
        assert "startupinfo" not in cast("dict[str, object]", seen["kwargs"])
        kwargs = cast("dict[str, object]", seen["kwargs"])
        assert kwargs["cwd"] == str(ga.config.ROOT)
        assert kwargs["close_fds"] is True

    def test_启动不碰任何窗口样式(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """显式断言：`Popen` 只收到 `cwd` / `close_fds`，没有 `startupinfo`。"""
        fake_exe = tmp_path / "victoria3.exe"
        fake_exe.write_bytes(b"MZ")
        monkeypatch.setattr(ga.experiments, "launch_command", FakeLaunchCommand(fake_exe))
        monkeypatch.setattr(ga, "_process_pids", list)
        seen: dict[str, object] = {}

        def fake_popen(command: list[str], **kwargs: object) -> object:
            seen["kwargs"] = kwargs
            return object()

        monkeypatch.setattr(ga.subprocess, "Popen", fake_popen)
        assert ga.launch(wait=False) is None
        assert set(cast("dict[str, object]", seen["kwargs"])) == {"cwd", "close_fds"}

    def test_不带自动化开关时就不加(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        fake_exe = tmp_path / "victoria3.exe"
        fake_exe.write_bytes(b"MZ")
        monkeypatch.setattr(ga.experiments, "launch_command", FakeLaunchCommand(fake_exe))
        monkeypatch.setattr(ga, "_process_pids", list)
        seen: dict[str, object] = {}
        monkeypatch.setattr(ga.subprocess, "Popen", _record_popen(seen))
        ga.launch(scripted_tests=False, wait=False)
        assert seen["command"] == [str(fake_exe)]

    def test_额外参数被附加(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        fake_exe = tmp_path / "victoria3.exe"
        fake_exe.write_bytes(b"MZ")
        monkeypatch.setattr(ga.experiments, "launch_command", FakeLaunchCommand(fake_exe))
        monkeypatch.setattr(ga, "_process_pids", list)
        seen: dict[str, object] = {}
        monkeypatch.setattr(ga.subprocess, "Popen", _record_popen(seen))
        ga.launch(extra_args=("no_save_after_failed_test",), wait=False)
        assert seen["command"] == [
            str(fake_exe),
            ga.SCRIPTED_TESTS_ARG,
            "no_save_after_failed_test",
        ]

    def test_可执行文件不存在时报错(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "_process_pids", list)
        monkeypatch.setattr(
            ga.experiments,
            "launch_command",
            MissingExeLaunchCommand(),
        )
        with pytest.raises(ga.GameAutoError, match="找不到游戏可执行文件"):
            ga.launch(wait=False)

    def test_等待窗口时把超时透传(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        fake_exe = tmp_path / "victoria3.exe"
        fake_exe.write_bytes(b"MZ")
        monkeypatch.setattr(ga.experiments, "launch_command", FakeLaunchCommand(fake_exe))
        monkeypatch.setattr(ga, "_process_pids", list)
        monkeypatch.setattr(ga.subprocess, "Popen", _record_popen({}))
        seen: dict[str, float] = {}
        monkeypatch.setattr(
            ga, "wait_for_window", lambda *, timeout: seen.update(timeout=timeout) or 4321
        )
        assert ga.launch(timeout=12.0) == 4321
        assert seen["timeout"] == 12.0


class TestWaitForWindow:
    def test_等不到窗口要报错(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "find_window", lambda: 0)
        clock = FakeClock()
        with pytest.raises(ga.WindowNotFoundError, match="没等到"):
            ga.wait_for_window(timeout=5.0, clock=clock, sleeper=clock.advance)

    def test_等到就立刻返回(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "find_window", lambda: 4242)
        clock = FakeClock()
        assert ga.wait_for_window(timeout=5.0, clock=clock, sleeper=clock.advance) == 4242


class TestDescribe:
    def test_Match_描述里有坐标与分数(self) -> None:
        text = ga.Match("btn", 1, 2, 0.5, 1.0, (0, 1, 2, 3)).describe()
        assert "btn" in text
        assert "(1,2)" in text
        assert "0.500" in text

    def test_Advance_描述带结论(self) -> None:
        assert "推进" in ga.Advance(True, "a", "b", 1.0, "src").describe()
        assert "未推进" in ga.Advance(False, "a", "b", 1.0, "src").describe()

    def test_TickMark_读不到时如实写(self) -> None:
        assert "读不到" in ga.TickMark(ga.NO_TICK, 0.0).describe()


# ────────────────────────── 真游戏（默认跳过）──────────────────────────
#
# 这一组会**真的起游戏、真的点鼠标**，分钟级，而且要求当前没有别的 victoria3 在跑。
# 所以只有显式 V3_AUTO_LIVE=1 才收集执行 —— CI 上永远是跳过的。
# 跑法：
#     $env:V3_AUTO_LIVE=1; python -m pytest tests/test_game_auto.py -n0 -q -k live

live = pytest.mark.skipif(
    os.environ.get("V3_AUTO_LIVE") != "1",
    reason="真游戏用例：设 V3_AUTO_LIVE=1 才跑（会真的启动 Victoria 3）",
)


class TestSpeedRate:
    """切速度这件事**只能靠速率证明**：实机踩过"点了但没生效、界面看不出异常"。"""

    def test_tick_折成天数(self) -> None:
        assert ga.tick_day("1836.1.1") == 0.0
        assert ga.tick_day("1836.1.12.12") == pytest.approx(11.0)
        assert ga.tick_day("1837.1.1") == pytest.approx(365.25)
        assert ga.tick_day("读不到") is None
        assert ga.tick_day("") is None

    def test_量速率(self, monkeypatch: pytest.MonkeyPatch) -> None:
        marks = iter(
            [ga.TickMark(tick="1836.1.1", mtime=0.0), ga.TickMark(tick="1836.1.11", mtime=0.0)]
        )
        monkeypatch.setattr(ga, "tick_mark", lambda *_a, **_k: next(marks))
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        assert ga.measure_rate(10.0) == pytest.approx(1.0), "10 天 / 10 秒 = 1 天/秒"

    def test_读不到_tick_时速率为零(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "tick_mark", lambda *_a, **_k: ga.TickMark(tick="", mtime=0.0))
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        assert ga.measure_rate(5.0) == 0.0


class TestSpeedCandidates:
    """找速度档的**候选序列**：模板只能当首选 —— 表盘会随「运行/暂停 + 当前档」变色，
    实测暂停态模板匹配运行态只有 0.327，所以必须有回落，而且每个候选都要靠速率验证。"""

    def test_显式坐标优先且带抖动(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "speed_widget_xy", lambda *_a, **_k: (999, 999))
        found = ga.speed_candidates(1, speed_xy=(100, 200), threshold=0.75)
        assert found[0] == ("显式坐标 (100, 200)", (100, 200))
        assert {point[0] for _label, point in found} == {100 + j for j in ga.SPEED_JITTER_PX}
        assert all(point[1] == 200 for _label, point in found)

    def test_模板匹配不到时回落到实测坐标(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "speed_widget_xy", lambda *_a, **_k: None)
        found = ga.speed_candidates(1, speed_xy=None, threshold=0.75)
        assert all(not label.startswith("模板匹配") for label, _ in found)
        assert found[0][1] == ga.SPEED_V_XY

    def test_模板匹配到就排在第一个(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "speed_widget_xy", lambda *_a, **_k: (500, 60))
        found = ga.speed_candidates(1, speed_xy=None, threshold=0.75)
        assert found[0] == ("模板匹配 (500, 60)", (500, 60))
        assert found[1][1] == ga.SPEED_V_XY, "模板后面仍要留着实测坐标兜底"

    def test_模板不存在时不是抛异常而是回落(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """模板文件被删/没装时 `locate` 会抛 —— 这一步必须吞掉它并回落，不能把整局带崩。"""

        def boom(*_a: object, **_k: object) -> object:
            raise ga.TemplateNotFoundError("没有 btn_speed")

        # 抓图也要打桩：这一步现在**只抓右上角那一块**，而"游戏不在前台"时抓图会报错
        # （真实截图只是探针/实机路径上的事，单测不该碰真窗口）。
        monkeypatch.setattr(ga, "screenshot", lambda _hwnd, **_kw: textured())
        monkeypatch.setattr(ga, "locate", boom)
        assert ga.speed_widget_xy(1) is None


# ────────────────────────── 前台借用：后台优先的最后一道保证 ──────────────────────────


class TestBootSettle:
    """启动期用**便宜信号**等（进程 + 日志大小），不抓图、不占屏（P2）。"""

    def _patch(self, monkeypatch: pytest.MonkeyPatch, log: Path, pids: list[int]) -> None:
        monkeypatch.setattr(ga, "TICK_LOG", log)
        monkeypatch.setattr(ga, "_process_pids", lambda: list(pids))

    def test_日志写过又安静下来才算忙完(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """必须先看到**引擎真的在写**（至少一次 size 变化），再谈"安静"。

        为什么这么严：实测踩过假阳性 —— 逐 tick 文件 0 字节、启动 8.7 秒就判"忙完"，
        于是提前借前台去点「观察」，按钮根本没出现。这里用一个"第一轮写一次、
        之后不动"的 sleeper 复现真实形状（启动期写日志 → 忙完 → 安静）。
        """
        # 用**规范文件名**：`wait_for_boot_settle` 默认盯的是日志目录下的
        # `BOOT_LOGS`（tick 文件 + debug 日志），名字不对就永远读不到。
        log = tmp_path / ga.BOOT_LOGS[0]
        log.write_text("Processing Tick: 1836.1.1\n", encoding="utf-8")
        self._patch(monkeypatch, log, [1234])
        clock = FakeClock()
        rounds = {"n": 0}

        def write_once(seconds: float) -> None:
            clock.advance(seconds)
            rounds["n"] += 1
            if rounds["n"] == 1:
                # 注意：**长度要变**（判据是 size 变化；等长重写是看不见的，真实日志只会变长）
                log.write_text("Processing Tick: 1836.1.2\n" + "x" * 64, encoding="utf-8")

        # `minimum` 是"至少启动这么久"的实测护栏（默认 120 秒，实测到大厅约 137 秒）；
        # 这条用例测的是"写过又安静"这条逻辑本身，所以把护栏调到 0，别让它等两分钟。
        result = ga.wait_for_boot_settle(timeout=60.0, minimum=0.0, clock=clock, sleeper=write_once)
        assert result.settled is True
        assert result.processes == 1

    def test_日志从来没变过就不算忙完(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """日志一直不动 ⇒ **不能**判忙完（这正是实机踩到的那个假阳性）。"""
        log = tmp_path / ga.BOOT_LOGS[0]
        log.write_text("", encoding="utf-8")
        self._patch(monkeypatch, log, [1234])
        clock = FakeClock()
        result = ga.wait_for_boot_settle(timeout=20.0, clock=clock, sleeper=clock.advance)
        assert result.settled is False
        assert "没看到日志推进过" in result.why

    def test_没有进程就不算忙完(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        log = tmp_path / "t.log"
        log.write_text("x", encoding="utf-8")
        self._patch(monkeypatch, log, [])
        clock = FakeClock()
        result = ga.wait_for_boot_settle(timeout=5.0, clock=clock, sleeper=clock.advance)
        assert result.settled is False
        assert "超时" in result.why

    def test_日志一直在长就继续等(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        log = tmp_path / "t.log"
        log.write_text("", encoding="utf-8")
        self._patch(monkeypatch, log, [1234])
        clock = FakeClock()

        def growing(seconds: float) -> None:
            clock.advance(seconds)
            log.write_text("x" * int(clock.now * 10), encoding="utf-8")

        result = ga.wait_for_boot_settle(timeout=5.0, clock=clock, sleeper=growing)
        assert result.settled is False, "日志还在长 ⇒ 启动还没忙完"

    def test_日志读不到不假装是零(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self._patch(monkeypatch, tmp_path / "没有这个文件.log", [1234])
        clock = FakeClock()
        result = ga.wait_for_boot_settle(timeout=3.0, clock=clock, sleeper=clock.advance)
        assert result.log_bytes == -1


class TestRoiCoordinateShift:
    """**回归**：只抓 ROI 之后，匹配坐标必须加回裁剪偏移。

    实机踩过（2026-09-21）：`btn_observe` 在裁剪图里匹配到 `(864, 83)`，直接拿去点击 ⇒
    打在屏幕顶部，而按钮其实在底部 `y≈1053` ⇒ 表现为"点了没反应"，还差点被误判成
    "后台点击无效"。
    """

    @needs_templates
    def test_底部_roi_匹配出来的坐标要平移回客户区(self, monkeypatch: pytest.MonkeyPatch) -> None:
        lobby = textured(1920, 108)  # 裁剪图：只有底部那一条
        paste(lobby, OBSERVE_TPL, 755, 29)  # 在这条里贴在 (755, 29)

        def fake(roi: tuple[float, float, float, float]) -> Image.Image:
            return lobby

        monkeypatch.setattr(ga, "screenshot", lambda _h, roi=None, **_kw: fake(roi))
        monkeypatch.setattr(ga, "_client_size", lambda _h: (1920, 1080))

        found = ga.find_in_roi(1, "btn_observe", roi=ga.BOTTOM_ROI)

        assert found is not None
        assert found.y > 900, f"按钮在底部，坐标却算成了 {found.y} —— ROI 偏移没加回去"
        assert found.y == 29 + int(0.90 * 1080) + OBSERVE_TPL_HEIGHT // 2
        assert found.box[1] == 29 + int(0.90 * 1080)

    def test_坐标平移不动别的字段(self) -> None:
        original = ga.Match(name="x", x=10, y=20, score=0.9, scale=1.0, box=(5, 15, 25, 35))
        moved = ga._shift_match(original, 100, 900)
        assert (moved.x, moved.y) == (110, 920)
        assert moved.box == (105, 915, 125, 935)
        assert (moved.name, moved.score, moved.scale) == ("x", 0.9, 1.0)


class Test抓图失败不是不命中:
    """t19：``find_in_roi`` 的两种「没拿到」必须分得开 —— **看不到 ≠ 没有**。

    旧口径把抓图失败也写成 ``return None``，于是「窗口最小化 / 界面还没画出来」与
    「这一屏真的没有这个按钮」在调用点长得一模一样：下游拿着这个 ``None`` 继续点，
    就是最贵的那种假绿（P13）。现在默认出声，``on_capture_failure="miss"`` 才是
    显式的轮询例外。
    """

    @staticmethod
    def _boom(_h: int, **_kw: object) -> Image.Image:
        raise ga.CaptureFailedError("抓到的是近乎纯色的画面（加载中 / 最小化 / 抓图失效）")

    def test_抓图失败默认出声_而且带出原因与位置(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """**阴性对照**：真造一次抓图失败 ⇒ 必须是异常（旧口径在这里返回 ``None``）。"""
        monkeypatch.setattr(ga, "screenshot", self._boom)

        with pytest.raises(ga.CaptureFailedError) as err:
            ga.find_in_roi(4242, "btn_observe", roi=ga.BOTTOM_ROI)

        text = str(err.value)
        assert "btn_observe" in text, "消息里要有是哪个模板"
        assert str(ga.BOTTOM_ROI) in text, "ROI 也要印出来 —— 哪一块没看到"
        assert "近乎纯色" in text, "底层原因必须带出来（P13），否则只剩「抓图失败」四个字"

    def test_显式轮询语义才允许退化成没找到(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """例外必须写在**调用点**上（``on_capture_failure="miss"``），不是默认行为。"""
        monkeypatch.setattr(ga, "screenshot", self._boom)

        lenient = ga.find_in_roi(4242, "btn_observe", roi=ga.BOTTOM_ROI, on_capture_failure="miss")
        assert lenient is None

    @needs_templates
    def test_真不命中只返回None_不抛(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """反向对照：抓图正常、这一屏确实没有那个按钮 ⇒ ``None``（与上面那条形状不同）。"""
        monkeypatch.setattr(ga, "screenshot", lambda _h, **_kw: textured(1920, 108))
        monkeypatch.setattr(ga, "_client_size", lambda _h: (1920, 1080))

        assert ga.find_in_roi(4242, "btn_observe", roi=ga.BOTTOM_ROI) is None

    def test_find_observe_沿同一条口径(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "screenshot", self._boom)

        with pytest.raises(ga.CaptureFailedError, match="btn_observe"):
            ga.find_observe(4242)
        assert ga.find_observe(4242, on_capture_failure="miss") is None

    def test_wait_stable_首帧看不到会重试_拿到了才判稳定(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``wait_stable`` 的两种假结果也得分得开：**没稳定 ≠ 判不出来**。"""
        clock = FakeClock()
        monkeypatch.setattr(ga, "_monotonic", clock)
        monkeypatch.setattr(ga, "_sleep", clock.advance)
        one = textured(64, 64, seed=5)
        tries = {"n": 0}

        def flaky(_h: int, **_kw: object) -> Image.Image:
            tries["n"] += 1
            if tries["n"] == 1:
                raise ga.CaptureFailedError("抓到的是近乎纯色的画面")
            return one

        monkeypatch.setattr(ga, "screenshot", flaky)

        assert ga.wait_stable(4242, roi=ga.BOTTOM_ROI, timeout=1.0, interval=0.01, settle_frames=1)
        assert tries["n"] >= 2, "首帧失败要重试，而不是当场判「没稳定」"

    def test_wait_stable_一次都没抓到就抛_不报没稳定(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = FakeClock()
        monkeypatch.setattr(ga, "_monotonic", clock)
        monkeypatch.setattr(ga, "_sleep", clock.advance)
        tries = {"n": 0}

        def boom(_h: int, **_kw: object) -> Image.Image:
            tries["n"] += 1
            raise ga.CaptureFailedError("抓到的是近乎纯色的画面")

        monkeypatch.setattr(ga, "screenshot", boom)

        with pytest.raises(ga.CaptureFailedError, match="判不出稳定不稳定"):
            ga.wait_stable(4242, roi=ga.BOTTOM_ROI, timeout=0.05, interval=0.02)
        assert tries["n"] >= 2, "必须真的重试过才下结论"

    def test_证据帧抓不到要留痕_抓得到就落盘(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        notes: list[str] = []
        monkeypatch.setattr(ga, "CAPTURE_FAULTS", notes)
        monkeypatch.setattr(ga, "save_shot", lambda _img, tag: tmp_path / f"{tag}.png")
        monkeypatch.setattr(ga, "screenshot", lambda _h, **_kw: textured(32, 32))

        assert ga._shot_or_note(4242, "10-lobby") is not None
        assert notes == [], "抓得到就不许留痕"

        monkeypatch.setattr(ga, "screenshot", self._boom)
        assert ga._shot_or_note(4242, "11-after-observe") is None
        assert "11-after-observe" in notes[0], "少了哪张图必须查得出来"
        assert "近乎纯色" in notes[0], "连同原因一起记"

    def test_观察时看不到的原因要写进异常(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """同族：``_step_observe`` 的判定里，抓图失败**不是**「按钮没了」。"""
        monkeypatch.setattr(ga, "CAPTURE_FAULTS", [])
        monkeypatch.setattr(ga, "screenshot", self._boom)
        monkeypatch.setattr(ga, "click_match", lambda _h, _m, **_kw: None)
        monkeypatch.setattr(ga, "tick_mark", lambda *_a, **_k: ga.TickMark(ga.NO_TICK, 0.0))

        def boom_find(*_a: object, **_kw: object) -> object:
            raise ga.CaptureFailedError("抓到的是近乎纯色的画面")

        monkeypatch.setattr(ga, "find_in_roi", boom_find)

        with pytest.raises(ga.TemplateNotFoundError) as err:
            ga._step_observe(4242, _observe_match(), settle_timeout=0.0)

        text = str(err.value)
        assert "界面没切走" in text
        assert "近乎纯色" in text, "看不到的原因必须带进异常，否则这一条没法查"
        assert len(ga.CAPTURE_FAULTS) == 2, "两张证据帧各自留了一笔"

    def test_点空了的异常要带焦点读数(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """t29 实测：位置对、游戏不收（前台不在它身上时点击送给别的窗口）。

        这一条**不是**静默路径（:func:`_step_observe` 抛 `TemplateNotFoundError`），
        但光说"这一下点空了"会把真因（焦点）说成"坐标不对" —— 所以异常里必须带
        `前台=` / `IsIconic=` 三个读数，让调用方一眼能分辨这两种情况。
        """
        monkeypatch.setattr(ga, "CAPTURE_FAULTS", [])
        monkeypatch.setattr(ga, "screenshot", lambda _h, **_kw: textured(32, 32))
        monkeypatch.setattr(ga, "click_match", lambda _h, _m, **_kw: None)
        monkeypatch.setattr(ga, "save_shot", lambda _img, tag: tag)
        monkeypatch.setattr(ga, "tick_mark", lambda *_a, **_k: ga.TickMark(ga.NO_TICK, 0.0))
        monkeypatch.setattr(ga, "find_in_roi", lambda *_a, **_kw: _observe_match())
        monkeypatch.setattr(ga, "_foreground_window", lambda: 1509322)  # 别人的窗口
        monkeypatch.setattr(ga, "_is_iconic", lambda _h: False)

        with pytest.raises(ga.TemplateNotFoundError) as err:
            ga._step_observe(4242, _observe_match(), settle_timeout=0.0)

        text = str(err.value)
        assert "这一下点空了" in text
        assert "前台=1509322" in text, "聚焦读数必须写进异常"
        assert "IsIconic=False" in text


class Test扫描表与源文件对账:
    """扫描表要**自己会红**：以后谁再悄悄吞一处抓图失败，这张表就对不上（t19 判据③）。"""

    @staticmethod
    def _swallow_sites() -> set[str]:
        """用 AST 现算：源文件里哪些函数内部有「吞掉抓图失败」的地方。

        ``except CaptureFailedError`` 与 ``suppress(CaptureFailedError)`` 都算；
        按**所在函数**归类（嵌套的子函数各自算一处，比如 `_step_observe` 里的
        `did_settle`）。
        """
        src = (config.REPO / "src" / "pdx" / "game_auto.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        found: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for sub in ast.walk(node):
                handled = isinstance(sub, ast.Try) and any(
                    handler.type is not None and "CaptureFailedError" in ast.dump(handler.type)
                    for handler in sub.handlers
                )
                suppressed = isinstance(sub, ast.With) and any(
                    "CaptureFailedError" in ast.dump(item.context_expr) for item in sub.items
                )
                if handled or suppressed:
                    found.add(node.name)
        return found

    def test_扫描表覆盖了每一个吞掉抓图失败的函数(self) -> None:
        registered = {name for name, _ in ga.CAPTURE_FAMILY_SCAN}

        found = self._swallow_sites()

        assert found == registered, (
            f"源文件里的吞点与扫描表不一致 —— 只在源文件里（漏登记）：{sorted(found - registered)}；"
            f"只在表里（登记过期）：{sorted(registered - found)}"
        )

    def test_扫描表里每一处都写了处置(self) -> None:
        for name, how in ga.CAPTURE_FAMILY_SCAN:
            assert how.strip(), f"{name} 登记了却没写怎么处置"


class TestSingleHitFastPath:
    """命中就停：轮询"按钮在不在"不需要跨尺度最优（P2），但这必须是**显式开关**（P5）。"""

    @needs_templates
    def test_命中就停只跑一次匹配(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = {"n": 0}
        real = ga.cv2.matchTemplate

        def counting(image: Any, templ: Any, method: int) -> Any:
            calls["n"] += 1
            return real(image, templ, method)

        monkeypatch.setattr(ga.cv2, "matchTemplate", counting)
        base = textured(400, 300, seed=11)
        template = np.array(base.crop((100, 100, 140, 140)))
        image = np.array(base)

        quick = ga.match_template(
            image, template, name="t", scales=ga.DEFAULT_SCALES, first_hit=True
        )
        assert quick is not None
        assert quick.scale == 1.0
        assert calls["n"] == 1, "first_hit=True 时命中即返回"

        calls["n"] = 0
        ga.match_template(image, template, name="t", scales=ga.DEFAULT_SCALES)
        assert calls["n"] == len(ga.DEFAULT_SCALES), "默认口径不变：所有尺度都试"

    def test_模板只读一次盘(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        textured(20, 20, seed=3).save(tmp_path / "t.png")
        ga.clear_template_cache()
        first = ga.load_template("t", tmp_path)
        (tmp_path / "t.png").unlink()  # 盘上删掉也不该再读
        assert ga.load_template("t", tmp_path) is first


class TestPressKeyGate:
    """按键和点击共用一道闸门：没授权就**报错**，绝不把用户正在打的字送进游戏。"""

    def test_没授权就必须拒绝(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from types import SimpleNamespace

        monkeypatch.setattr(ga, "ALLOW_REAL_INPUT", False)
        monkeypatch.setattr(
            ga, "directinput", SimpleNamespace(press=lambda _k: pytest.fail("真按键"))
        )
        with pytest.raises(ga.RealInputBlockedError):
            ga.press_key("space")


class TestTypeText:
    """敲字符串：上档字符要自己配 Shift —— `pydirectinput` 的键表里没有它们。"""

    @staticmethod
    def _spy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
        from types import SimpleNamespace

        seen: list[tuple[str, str]] = []
        monkeypatch.setattr(ga, "ALLOW_REAL_INPUT", True)
        monkeypatch.setattr(
            ga,
            "directinput",
            SimpleNamespace(
                press=lambda key: seen.append(("press", key)),
                keyDown=lambda key: seen.append(("down", key)),
                keyUp=lambda key: seen.append(("up", key)),
            ),
        )
        return seen

    def test_普通字符直接敲(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = self._spy(monkeypatch)
        ga.type_text("abc")
        assert seen == [("press", "a"), ("press", "b"), ("press", "c")]

    def test_下划线要配_Shift(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`_` 不在 `pydirectinput` 的键表里 —— 直接 `write()` 会抛 KeyError。"""
        seen = self._spy(monkeypatch)
        ga.type_text("a_b")
        assert seen == [
            ("press", "a"),
            ("down", "shift"),
            ("press", "-"),
            ("up", "shift"),
            ("press", "b"),
        ]

    def test_大写字母要配_Shift(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = self._spy(monkeypatch)
        ga.type_text("Ab")
        assert seen == [("down", "shift"), ("press", "a"), ("up", "shift"), ("press", "b")]

    def test_空格走_space_键名(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = self._spy(monkeypatch)
        ga.type_text("a b")
        assert ("press", "space") in seen

    def test_Shift_一定会被抬起(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """敲到一半炸了也必须抬起 Shift —— 否则整个桌面后面的输入都变成大写。"""
        from types import SimpleNamespace

        events: list[str] = []

        def boom(key: str) -> None:
            raise RuntimeError("注入失败")

        monkeypatch.setattr(ga, "ALLOW_REAL_INPUT", True)
        monkeypatch.setattr(
            ga,
            "directinput",
            SimpleNamespace(
                press=boom,
                keyDown=lambda key: events.append(f"down:{key}"),
                keyUp=lambda key: events.append(f"up:{key}"),
            ),
        )
        with pytest.raises(RuntimeError):
            ga.type_text("_")
        assert events == ["down:shift", "up:shift"]

    def test_没授权就整串都不敲(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from types import SimpleNamespace

        monkeypatch.setattr(ga, "ALLOW_REAL_INPUT", False)
        monkeypatch.setattr(
            ga, "directinput", SimpleNamespace(press=lambda _k: pytest.fail("真按键"))
        )
        with pytest.raises(ga.RealInputBlockedError):
            ga.type_text("dump_ticktask_timings")


class TestPressChord:
    """组合键：`pydirectinput` 的键表按扫描码给，上档字符不在表里，要自己按 Shift。"""

    @staticmethod
    def _spy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
        from types import SimpleNamespace

        seen: list[tuple[str, str]] = []
        monkeypatch.setattr(ga, "ALLOW_REAL_INPUT", True)
        monkeypatch.setattr(
            ga,
            "directinput",
            SimpleNamespace(
                press=lambda key: seen.append(("press", key)),
                keyDown=lambda key: seen.append(("down", key)),
                keyUp=lambda key: seen.append(("up", key)),
            ),
        )
        return seen

    def test_单键就是按一下(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = self._spy(monkeypatch)
        ga.press_chord("f12")
        assert seen == [("press", "f12")]

    def test_加号写法按顺序按下与抬起(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = self._spy(monkeypatch)
        ga.press_chord("shift+ctrl+a")
        assert seen == [
            ("down", "shift"),
            ("down", "ctrl"),
            ("press", "a"),
            ("up", "ctrl"),
            ("up", "shift"),
        ]

    def test_敲不下去也要抬起修饰键(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from types import SimpleNamespace

        events: list[str] = []

        def boom(key: str) -> None:
            raise RuntimeError("注入失败")

        monkeypatch.setattr(ga, "ALLOW_REAL_INPUT", True)
        monkeypatch.setattr(
            ga,
            "directinput",
            SimpleNamespace(
                press=boom,
                keyDown=lambda key: events.append(f"down:{key}"),
                keyUp=lambda key: events.append(f"up:{key}"),
            ),
        )
        with pytest.raises(RuntimeError):
            ga.press_chord("shift+`")
        assert events == ["down:shift", "up:shift"]

    def test_没授权也要拒绝(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from types import SimpleNamespace

        monkeypatch.setattr(ga, "ALLOW_REAL_INPUT", False)
        monkeypatch.setattr(
            ga, "directinput", SimpleNamespace(press=lambda _k: pytest.fail("真按键"))
        )
        with pytest.raises(ga.RealInputBlockedError):
            ga.press_chord("`")


# ────────────────────────── 标准流程（单路，无回落链）──────────────────────────
#
# 这一组钉住用户口径的**顺序**与**收尾**：
#     起游戏（前台）→ 加载期不碰窗口 → 点观察 → 点 5 档速度 → 按空格 → 切回后台
# 顺序错了、或者收尾漏了"还前台 / 缩窗口"，都要红。


def _observe_match() -> ga.Match:
    return ga.Match(
        name="btn_observe", x=864, y=1055, score=0.98, scale=1.0, box=(755, 1037, 973, 1073)
    )


def _settle() -> ga.BootSettle:
    return ga.BootSettle(
        settled=True,
        waited=130.0,
        log_bytes=4096,
        quiet_seconds=21.0,
        processes=1,
        why="进程 1 个；日志 4096 字节",
    )


def _handover(*, restored: bool = True, minimized: bool = True) -> ga.ForegroundHandover:
    return ga.ForegroundHandover(
        previous=777, after=777, restored=restored, minimized=minimized, seconds=1.2
    )


def _session_start(**overrides: object) -> ga.SessionStart:
    base: dict[str, object] = {
        "hwnd": 4242,
        "previous": 777,
        "settle": _settle(),
        "observe": _observe_match(),
        "speed_source": "模板匹配 (1851, 52)",
        "speed_xy": (1851, 52),
        "unpause": "已按 space 开始推进",
        "pressed": True,
        "advance": ga.Advance(True, "1836.1.1", "1836.1.8", 1.0, "log"),
        "rate": 3.0,
        "rate_ok": True,
        "attempts": 1,
        "handover": _handover(),
        "tick": "1836.1.8",
    }
    base.update(overrides)
    return ga.SessionStart(**base)  # type: ignore[arg-type]


class TestSwitchToBackground:
    """`switch_to_background` = 还前台 + 缩窗口；两步都要，且都要**如实报**。"""

    def _patch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        alive: dict[int, bool],
        foreground: list[int],
        iconic: dict[int, bool],
        calls: list[str],
    ) -> None:
        monkeypatch.setattr(ga, "_is_alive", lambda h: alive.get(h, False))
        monkeypatch.setattr(ga, "_foreground_window", lambda: foreground[-1])
        monkeypatch.setattr(ga, "_is_iconic", lambda h: iconic.get(h, False))
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        monkeypatch.setattr(ga, "WINDOW_SHOW_SETTLE", 0.0)

        def set_foreground(handle: int) -> bool:
            calls.append(f"set_foreground:{handle}")
            foreground.append(handle)
            return True

        def minimize(handle: int) -> None:
            calls.append(f"minimize:{handle}")
            iconic[handle] = True

        monkeypatch.setattr(ga, "_set_foreground", set_foreground)
        monkeypatch.setattr(ga, "_minimize", minimize)

    def test_还前台并缩窗口(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        foreground = [4242]
        iconic: dict[int, bool] = {}
        self._patch(
            monkeypatch, alive={777: True}, foreground=foreground, iconic=iconic, calls=calls
        )
        handover = ga.switch_to_background(4242, 777)
        assert calls == ["set_foreground:777", "minimize:4242"]
        assert handover.restored is True
        assert handover.minimized is True
        assert handover.after == 777, "交完之后前台应该是用户的窗口"
        assert "还原成功" in handover.describe()

    def test_没有可还原的窗口时如实报没还(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``previous`` 为 0 或已关掉 ⇒ 只能缩窗口，`restored` **不许**谎报成 True。"""
        calls: list[str] = []
        foreground = [4242]
        iconic: dict[int, bool] = {}
        self._patch(monkeypatch, alive={}, foreground=foreground, iconic=iconic, calls=calls)
        handover = ga.switch_to_background(4242, 0)
        assert calls == ["minimize:4242"]
        assert handover.restored is False
        assert "还原未做" in handover.describe()

    def test_可以只要缩窗口不要还前台(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        foreground = [4242]
        iconic: dict[int, bool] = {}
        self._patch(
            monkeypatch, alive={777: True}, foreground=foreground, iconic=iconic, calls=calls
        )
        handover = ga.switch_to_background(4242, 777, restore=False)
        assert calls == ["minimize:4242"]
        assert handover.restored is False

    def test_可以只还前台不缩窗口(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        foreground = [4242]
        iconic: dict[int, bool] = {}
        self._patch(
            monkeypatch, alive={777: True}, foreground=foreground, iconic=iconic, calls=calls
        )
        handover = ga.switch_to_background(4242, 777, minimize=False)
        assert calls == ["set_foreground:777"]
        assert handover.minimized is False


class TestLaunchToForeground:
    """起游戏必须**记住起之前的前台窗口**：加载结束时游戏会自己抢前台（B50 实测），
    那一刻再取前台只会取到游戏自己，"还原"就成了空动作。"""

    def test_记住起之前的前台并交回实时句柄(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, object] = {}
        monkeypatch.setattr(ga, "_foreground_window", lambda: 999)
        monkeypatch.setattr(ga, "_is_alive", lambda h: h == 4242)
        monkeypatch.setattr(ga, "launch", lambda **kw: seen.update(kw) or 4242)
        hwnd, previous = ga.launch_to_foreground(timeout=12.0)
        assert (hwnd, previous) == (4242, 999)
        assert seen["wait"] is True
        assert seen["timeout"] == 12.0

    def test_句柄失效时按标题找回来(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "_foreground_window", lambda: 999)
        monkeypatch.setattr(ga, "_is_alive", lambda _h: False)
        monkeypatch.setattr(ga, "find_window", lambda *_a, **_kw: 5150)
        monkeypatch.setattr(ga, "launch", lambda **_kw: 4242)
        monkeypatch.setattr(ga, "_REBUILDS", [])
        hwnd, _prev = ga.launch_to_foreground()
        assert hwnd == 5150, "launch 拿到的句柄在加载期会被重建，必须换成当前的"
        assert ga._REBUILDS == [(4242, 5150)]


class TestForegroundRouting:
    """`_route_to_foreground`：句柄先刷新；有用户的窗口就先还给他，再明确把游戏提到前台。"""

    def test_已经是前台就什么都不做(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "_is_alive", lambda _h: True)
        monkeypatch.setattr(ga, "_foreground_window", lambda: 4242)
        monkeypatch.setattr(ga, "find_window", lambda *_a, **_kw: 0)
        called: list[str] = []
        monkeypatch.setattr(ga, "_set_foreground", lambda h: called.append(f"set:{h}"))
        assert ga._route_to_foreground(4242, 777, force=True) == 4242
        assert called == []

    def test_先把前台还给用户再提游戏(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Windows 前台锁定会静默拒绝非前台进程的置前请求；先归还一次成功率更高。"""
        monkeypatch.setattr(ga, "_is_alive", lambda _h: True)
        monkeypatch.setattr(ga, "_foreground_window", lambda: 999)
        called: list[str] = []
        monkeypatch.setattr(ga, "_set_foreground", _recorder(called))
        monkeypatch.setattr(ga, "ensure_foreground", lambda h, **_kw: called.append(f"ensure:{h}"))
        assert ga._route_to_foreground(4242, 777, force=True) == 4242
        assert called == ["set:777", "ensure:4242"]

    def test_用户窗口已经关掉就只提游戏(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "_is_alive", lambda h: h == 4242)
        monkeypatch.setattr(ga, "_foreground_window", lambda: 999)
        called: list[str] = []
        monkeypatch.setattr(ga, "_set_foreground", _recorder(called))
        monkeypatch.setattr(ga, "ensure_foreground", lambda h, **_kw: called.append(f"ensure:{h}"))
        ga._route_to_foreground(4242, 777, force=True)
        assert called == ["ensure:4242"]


class TestEnsureLiveForeground:
    """抢不到前台就必须报错 —— 此时的点击/按键会送给**别的窗口**。"""

    def test_抢不到就报前台丢失(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "_is_alive", lambda _h: True)
        monkeypatch.setattr(ga, "_foreground_window", lambda: 999)
        monkeypatch.setattr(ga, "_window_title", lambda _h: "别的窗口")
        monkeypatch.setattr(ga, "_set_foreground", lambda _h: False)
        monkeypatch.setattr(ga, "LOOK_TIMEOUT", 0.0)
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        with pytest.raises(ga.ForegroundLostError, match="没能拿到前台"):
            ga._ensure_live_foreground(4242)

    def test_拿到就返回当前句柄(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "_is_alive", lambda _h: True)
        monkeypatch.setattr(ga, "_foreground_window", lambda: 4242)
        monkeypatch.setattr(ga, "_set_foreground", lambda _h: True)
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        assert ga._ensure_live_foreground(4242) == 4242


def _fake_attempt(*, kind: str = "titlebar", performed: bool = True) -> ga.ForegroundAttempt:
    """合成一条"注入过、但没换来前台"的读数（桩用，字段齐全、含命中测试）。"""
    return ga.ForegroundAttempt(
        kind=kind,
        performed=performed,
        refused_why="" if performed else "命中测试失败：点在别处",
        hwnd=4242,
        foreground_before=5768114,
        foreground_after=999,
        is_iconic=False,
        point=(960, 115) if kind == "titlebar" else None,
        hit=777,
        root=888,
    )


class TestForegroundRecovery:
    """D28：抢不到前台时的**有界**合成输入恢复（t4 实机验证过的手法，正式版）。

    这几条就是它的全部纪律：有界（最多 3 次、每次之间重启）、命中测试（点上不是游戏就
    一下都不点）、**永不点客户区**、每次实际使用留一行可追溯日志、开关关掉时**一字不改**
    地抛既有异常。全部用桩，**不真起游戏、不真碰键鼠**。
    """

    def test_有界_最多三次不搞重试风暴(self, monkeypatch: pytest.MonkeyPatch) -> None:
        shots: list[int] = []
        relaunches: list[str] = []
        killed: list[int] = []

        def shoot(_hwnd: int, *, force: bool) -> ga.ForegroundAttempt:
            del force
            shots.append(1)
            return _fake_attempt()

        def route(_hwnd: int, _previous: int, *, force: bool) -> int:
            del force
            raise ga.ForegroundLostError("抢不到前台（测试桩）")

        def relaunch() -> tuple[int, int]:
            relaunches.append("relaunch")
            return 5150, 5768114

        def kill() -> list[int]:
            killed.append(1)
            return []

        monkeypatch.setattr(ga, "_acquire_foreground_by_input", shoot)
        monkeypatch.setattr(ga, "_route_to_foreground", route)
        monkeypatch.setattr(ga, "kill_game", kill)
        monkeypatch.setattr(ga, "_is_alive", lambda _h: False)
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        monkeypatch.setattr(ga, "_foreground_window", lambda: 999)
        monkeypatch.setattr(ga, "_window_title", lambda _h: "别的窗口")

        with pytest.raises(ga.ForegroundLostError) as err:
            ga.recover_foreground(4242, 5768114, attempts=3, relaunch=relaunch, log_path=None)

        assert len(shots) == 3, "上限是 3 次 —— 第 4 次不许再试（t4 之前那版在这里试了 337 次）"
        assert len(relaunches) == 2, "每次之间干净重启一次（3 次尝试 ⇒ 2 次重启）"
        assert killed == [1, 1], "重启之前先把旧进程杀掉（进程与句柄都要清）"
        message = str(err.value)
        assert "hwnd=5150" in message, "异常消息要带**当前**句柄（重启换过句柄）"
        assert "当前前台=999" in message
        assert "命中测试=hwnd 777/root 888" in message

    def test_命中测试不通过就一下都不点(self, monkeypatch: pytest.MonkeyPatch) -> None:
        taps: list[str] = []
        monkeypatch.setattr(ga, "_is_alive", lambda _h: True)
        monkeypatch.setattr(ga, "_is_iconic", lambda _h: False)
        monkeypatch.setattr(ga, "_window_rect_visible", lambda _h: (True, "rect 在屏内"))
        monkeypatch.setattr(ga, "_require_input", lambda _force: None)
        monkeypatch.setattr(ga, "_foreground_window", lambda: 999)
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        monkeypatch.setattr(ga.directinput, "keyDown", lambda key: taps.append(f"down:{key}"))
        monkeypatch.setattr(ga.directinput, "keyUp", lambda key: taps.append(f"up:{key}"))
        monkeypatch.setattr(ga, "_client_origin", lambda _h: (0, 130))
        monkeypatch.setattr(ga.win32gui, "GetWindowRect", lambda _h: (0, 100, 1920, 1180))
        monkeypatch.setattr(ga.win32gui, "WindowFromPoint", lambda _pt: 777)
        monkeypatch.setattr(ga.win32gui, "GetAncestor", lambda _h, _flags: 888)
        monkeypatch.setattr(
            ga, "_set_cursor", lambda _x, _y: pytest.fail("命中测试没过，一下都不点")
        )
        monkeypatch.setattr(ga, "_mouse_click", lambda: pytest.fail("命中测试没过，一下都不点"))

        shot = ga._acquire_foreground_by_input(4242, force=True)

        assert taps == ["down:alt", "up:alt"], "先 Alt 轻敲（不落任何坐标）"
        assert shot.kind == "titlebar", "Alt 没换来前台才退到标题栏这条"
        assert shot.performed is False, "命中测试没过 ⇒ 什么都没注入"
        assert "命中测试失败" in shot.refused_why
        assert shot.point == (960, 115), "落点是标题栏中线（rect 顶 + band/2）"
        assert (shot.hit, shot.root) == (777, 888), "读数要原样带出来，供事后追查"

    def test_Alt_轻敲拿到前台就不点标题栏(self, monkeypatch: pytest.MonkeyPatch) -> None:
        taps: list[str] = []
        front = {"hwnd": 999}

        def key_up(key: str) -> None:
            taps.append(f"up:{key}")
            front["hwnd"] = 4242  # 真实链路里：松开 Alt 之后前台就成了游戏

        monkeypatch.setattr(ga, "_is_alive", lambda _h: True)
        monkeypatch.setattr(ga, "_is_iconic", lambda _h: False)
        monkeypatch.setattr(ga, "_window_rect_visible", lambda _h: (True, "rect 在屏内"))
        monkeypatch.setattr(ga, "_require_input", lambda _force: None)
        monkeypatch.setattr(ga, "_foreground_window", lambda: front["hwnd"])
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        monkeypatch.setattr(ga.directinput, "keyDown", lambda key: taps.append(f"down:{key}"))
        monkeypatch.setattr(ga.directinput, "keyUp", key_up)
        monkeypatch.setattr(ga, "_set_cursor", lambda _x, _y: pytest.fail("Alt 就成了，不该再落点"))
        monkeypatch.setattr(ga, "_mouse_click", lambda: pytest.fail("Alt 就成了，不该再落点"))

        shot = ga._acquire_foreground_by_input(4242, force=True)

        assert shot.kind == "alt"
        assert shot.performed is True
        assert shot.ok is True, "判据是前台窗口真的换了，不是注入了就算"
        assert shot.point is None, "Alt 这条路**不落任何坐标**（对界面零副作用）"

    def test_每次实际使用留一行日志(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """证据要能回答"这一局的焦点是怎么来的"—— 所以每次实际使用都落一行 JSON。"""
        monkeypatch.setattr(ga, "_acquire_foreground_by_input", lambda _h, **_kw: _fake_attempt())
        monkeypatch.setattr(ga, "_route_to_foreground", lambda _h, _p, **_kw: 4242)
        log = tmp_path / "fg.jsonl"

        recovery = ga.recover_foreground(4242, 0, log_path=log, trigger="抢不到前台（测试桩）")

        assert recovery.ok is True
        assert recovery.attempts_used == 1
        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        for field in (
            "kind",
            "injected",
            "hwnd",
            "foreground_before",
            "foreground_after",
            "is_iconic",
            "route_ok",
            "attempt",
            "trigger",
        ):
            assert field in record, f"日志行缺字段 {field}"
        assert record["route_ok"] is True
        assert record["kind"] == "titlebar"
        assert record["trigger"] == "抢不到前台（测试桩）", "把调用点那条失败读数原话记下来"
        assert log.read_bytes().endswith(b"\n"), "append-only、末尾 LF（台账口径）"

    def test_恢复不了就抛既有异常带三个读数(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """三次都失败：异常里必须有 hwnd / 当前前台 hwnd / 命中测试读数 —— 一个都不许少。"""
        monkeypatch.setattr(ga, "_acquire_foreground_by_input", lambda _h, **_kw: _fake_attempt())
        monkeypatch.setattr(
            ga,
            "_route_to_foreground",
            lambda _h, _p, **_kw: (_ for _ in ()).throw(
                ga.ForegroundLostError("抢不到前台（测试桩）")
            ),
        )
        monkeypatch.setattr(ga, "_foreground_window", lambda: 999)
        monkeypatch.setattr(ga, "_window_title", lambda _h: "别的窗口")
        log = tmp_path / "fg.jsonl"

        with pytest.raises(ga.ForegroundLostError) as err:
            # 不给 relaunch ⇒ 只试一次（没有干净重启的手段时，重复同一场景没有意义）
            ga.recover_foreground(4242, 0, attempts=3, log_path=log)

        message = str(err.value)
        assert "hwnd=4242" in message
        assert "当前前台=999" in message
        assert "命中测试=hwnd 777/root 888" in message
        assert len(log.read_text(encoding="utf-8").splitlines()) == 1
        assert json.loads(log.read_text(encoding="utf-8").splitlines()[0])["route_ok"] is False

    def test_重启之后拿到前台就返回新句柄(self, monkeypatch: pytest.MonkeyPatch) -> None:
        shots: list[int] = []
        calls = {"n": 0}

        def shoot(_hwnd: int, *, force: bool) -> ga.ForegroundAttempt:
            del force
            shots.append(1)
            return _fake_attempt()

        def route(_hwnd: int, _previous: int, *, force: bool) -> int:
            del force
            calls["n"] += 1
            if calls["n"] < 3:
                raise ga.ForegroundLostError("抢不到前台（测试桩）")
            return 5150

        monkeypatch.setattr(ga, "_acquire_foreground_by_input", shoot)
        monkeypatch.setattr(ga, "_route_to_foreground", route)
        monkeypatch.setattr(ga, "kill_game", list)
        monkeypatch.setattr(ga, "_is_alive", lambda _h: False)
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)

        recovery = ga.recover_foreground(
            4242, 5768114, attempts=3, relaunch=lambda: (5150, 5768114), log_path=None
        )

        assert recovery.ok is True
        assert recovery.attempts_used == 3
        assert recovery.restarts == 2
        assert recovery.hwnd == 5150, "恢复后要走**新**句柄（重启会换窗口）"
        assert recovery.previous == 5768114
        assert len(shots) == len(recovery.injections) == 3

    def test_开关关掉就照原样抛既有异常(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`foreground_recovery=False` 时既有行为**一字不改**：异常类型与措辞都不动。"""

        def route(_hwnd: int, _previous: int, *, force: bool) -> int:
            del force
            raise ga.ForegroundLostError("抢不到前台（测试桩）")

        monkeypatch.setattr(ga, "_route_to_foreground", route)
        monkeypatch.setattr(ga, "recover_foreground", lambda *_a, **_kw: pytest.fail("开关关着"))

        with pytest.raises(ga.ForegroundLostError, match="抢不到前台（测试桩）"):
            ga.start_session(4242, force=True, foreground_recovery=False)


def _fake_park(*, performed: bool = True, kind: str = "client-top") -> ga.CursorPark:
    """合成一条"停靠过"的读数（桩用，字段齐全）。"""
    return ga.CursorPark(
        hwnd=4242,
        roi=ga.BOTTOM_ROI,
        performed=performed,
        kind=kind,
        point=(960, 24) if performed else None,
        cursor_before=(500, 900),
        moved=performed,
        clear_of_roi=performed,
        shot=False,
        why="测试桩",
    )


class TestCursorPark:
    """D28：等按钮类 ROI 之前的**光标停靠** —— 2026-10-01 第一次撞上 tooltip 遮挡后正式化。

    那次的热身读数：鼠标停在大西洋上，省份 tooltip 一直铺到 y≈1080，把底部条上的「观察」
    左半盖住 ⇒ 模板匹配 1.000 → **0.5665** < 0.75，600 秒预算全打空。同一晚同一屏的对照帧
    仍是 1.000 ⇒ 与模板/阈值/ROI 无关，要修的是环境。

    这几条就是它的全部纪律：**只移不点**、有界（一次移动 + 至多一张确认帧）、每次留一行
    可追溯日志、失败**不抛**（它只是前置整理）。全部用桩，**不真起游戏、不真碰键鼠**。
    """

    def _patch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        moves: list[tuple[int, int]],
        cursor: tuple[int, int] = (500, 900),
        client_top: int = 0,
    ) -> None:
        monkeypatch.setattr(ga, "_is_alive", lambda _h: True)
        monkeypatch.setattr(ga, "_client_size", lambda _h: (1920, 1080))
        monkeypatch.setattr(ga, "_client_origin", lambda _h: (0, client_top))
        monkeypatch.setattr(ga, "_virtual_screen", lambda: (0, 0, 1920, 1080))
        monkeypatch.setattr(ga, "_cursor_pos", lambda: cursor)
        monkeypatch.setattr(ga, "_set_cursor", lambda x, y: moves.append((x, y)))
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        monkeypatch.setattr(ga, "_shot_or_note", lambda _h, _tag: None)
        monkeypatch.setattr(ga, "_mouse_click", lambda *_a, **_k: pytest.fail("停靠只移不点"))
        monkeypatch.setattr(ga, "click_client", lambda *_a, **_k: pytest.fail("停靠只移不点"))
        monkeypatch.setattr(ga, "_require_input", lambda _force=True: None)

    def test_只移不点_落点在底部条之外(self, monkeypatch: pytest.MonkeyPatch) -> None:
        moves: list[tuple[int, int]] = []
        self._patch(monkeypatch, moves=moves)
        log: list[dict[str, object]] = []
        monkeypatch.setattr(ga, "_log_cursor_park", lambda _p, rec: log.append(rec))

        park = ga.park_cursor_clear_of(4242, ga.BOTTOM_ROI, log_path=None)

        assert park.performed is True
        assert park.kind == "client-top", "第一候选是客户区最上沿居中 —— 离底部条最远"
        assert park.point == (960, 24), "底部条中心 x=960；客户区上沿 + 留白 24"
        assert park.clear_of_roi is True
        assert park.cursor_before == (500, 900)
        assert park.moved is True
        assert moves == [(960, 24)], "**一次**移动（有界：不重试、不拖拽）"
        assert len(log) == 1, "每次调用留一行"
        assert log[0]["clear_of_roi"] is True

    def test_没有合格落点就一次都不移(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """整屏都是 ROI 时**不许**硬挑一个点 —— 记实话、不移动。"""
        moves: list[tuple[int, int]] = []
        self._patch(monkeypatch, moves=moves)

        park = ga.park_cursor_clear_of(4242, (0.0, 0.0, 1.0, 1.0), log_path=None)

        assert park.performed is False
        assert "没有合格落点" in park.why
        assert moves == [], "没有合格落点时一次都不移（不许挑个「差不多」的点）"

    def test_句柄失效就一次都不移(self, monkeypatch: pytest.MonkeyPatch) -> None:
        moves: list[tuple[int, int]] = []
        self._patch(monkeypatch, moves=moves)
        monkeypatch.setattr(ga, "_is_alive", lambda _h: False)

        park = ga.park_cursor_clear_of(4242, ga.BOTTOM_ROI, log_path=None)

        assert park.performed is False
        assert "句柄已失效" in park.why
        assert moves == []

    def test_取窗口几何失败也不抛(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """假句柄 / 窗口正在销毁时 `GetClientRect` 会抛 —— 停靠**不许**把整局带崩。"""
        moves: list[tuple[int, int]] = []
        self._patch(monkeypatch, moves=moves)

        def boom(_h: int) -> tuple[int, int]:
            raise RuntimeError("GetClientRect 失败：无效的窗口句柄")

        monkeypatch.setattr(ga, "_client_size", boom)

        park = ga.park_cursor_clear_of(4242, ga.BOTTOM_ROI, log_path=None)

        assert park.performed is False
        assert "取窗口几何失败" in park.why
        assert moves == []

    def test_每次调用留一行日志(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """真写一行 JSON（不桩日志函数）：字段固定、末尾 LF、append-only。"""
        moves: list[tuple[int, int]] = []
        self._patch(monkeypatch, moves=moves)
        log_path = tmp_path / "cursor-park.jsonl"

        ga.park_cursor_clear_of(4242, ga.BOTTOM_ROI, log_path=log_path, why="测试：先停靠再等按钮")
        first = log_path.read_bytes()
        ga.park_cursor_clear_of(4242, ga.BOTTOM_ROI, log_path=log_path, why="第二行")
        second = log_path.read_bytes()

        assert second.startswith(first), "append-only"
        assert first.endswith(b"\n"), "末尾 LF"
        assert second.endswith(b"\n"), "末尾 LF"
        lines = [json.loads(line) for line in second.decode("utf-8").splitlines()]
        assert len(lines) == 2
        record = lines[0]
        assert record["kind"] == "client-top"
        assert record["performed"] is True
        assert record["point"] == [960, 24]
        assert record["cursor_before"] == [500, 900]
        assert record["moved"] is True
        assert record["clear_of_roi"] is True
        assert record["roi"] == list(ga.BOTTOM_ROI)
        assert record["reason"] == "测试：先停靠再等按钮"
        assert record["at"], "留时间戳（事后按窗口对账）"
        assert record["why"]

    def test_确认帧只落一张_落帧失败不影响停靠(self, monkeypatch: pytest.MonkeyPatch) -> None:
        moves: list[tuple[int, int]] = []
        self._patch(monkeypatch, moves=moves)
        tags: list[str] = []

        def shot(_h: int, tag: str) -> Path:
            tags.append(tag)
            return config.OUT / f"{tag}.png"

        monkeypatch.setattr(ga, "_shot_or_note", shot)

        park = ga.park_cursor_clear_of(
            4242, ga.BOTTOM_ROI, log_path=None, shot_tag="00-cursor-park"
        )

        assert tags == ["00-cursor-park"], "有界：只落一张"
        assert park.shot is True

        monkeypatch.setattr(ga, "_shot_or_note", lambda _h, _tag: None)
        assert ga.park_cursor_clear_of(4242, ga.BOTTOM_ROI, log_path=None).shot is False, (
            "抓不到帧就照实记 False（不许假报落帧）"
        )

        def boom(_h: int, _tag: str) -> None:
            raise RuntimeError("抓图失败")

        monkeypatch.setattr(ga, "_shot_or_note", boom)
        park3 = ga.park_cursor_clear_of(4242, ga.BOTTOM_ROI, log_path=None)
        assert park3.performed is True, "落帧是附带的：失败也要停靠成功"
        assert park3.shot is False


class TestStepLook:
    """确认「观察」出现：只抓底部条、命中即停、失败要把**最后一条抓图错误**带进异常。"""

    def test_命中即返回客户区坐标(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "_ensure_live_foreground", lambda h: h)
        monkeypatch.setattr(ga, "screenshot", lambda _h, **_kw: textured())
        monkeypatch.setattr(ga, "_roi_offset", lambda _h, _roi: (0, 972))
        monkeypatch.setattr(
            ga,
            "locate_optional",
            lambda *_a, **_k: ga.Match("btn_observe", 864, 83, 0.99, 1.0, (755, 65, 973, 101)),
        )
        match, hwnd = ga._step_look(4242, threshold=0.75)
        assert (match.x, match.y) == (864, 1055), "裁剪图内的坐标必须加回 ROI 偏移"
        assert hwnd == 4242

    def test_一直抓不到就把最后一条抓图错误带出来(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "_ensure_live_foreground", lambda h: h)
        clock = FakeClock()
        monkeypatch.setattr(ga, "_monotonic", clock)

        def boom(_h: int, **_kw: object) -> Image.Image:
            clock.advance(0.5)  # 每抓一次推进一点：循环有时间跑完第二轮
            raise ga.CaptureFailedError("抓到的是近乎纯色的画面")

        monkeypatch.setattr(ga, "screenshot", boom)
        monkeypatch.setattr(ga, "_sleep", clock.advance)
        with pytest.raises(ga.TemplateNotFoundError, match="近乎纯色"):
            ga._step_look(4242, threshold=0.75, lobby_timeout=1.0)

    def test_等按钮之前先停靠光标(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """顺序：**先停靠光标 → 再抓底部条**（2026-10-01 的 hover tooltip 遮挡就是这么来的）。"""
        events: list[str] = []
        monkeypatch.setattr(ga, "_ensure_live_foreground", lambda h: h)

        def park(_h: int, roi: tuple[float, float, float, float], **_kw: object) -> ga.CursorPark:
            events.append(f"park:{roi}")
            return _fake_park()

        def shot(_h: int, **_kw: object) -> Image.Image:
            events.append("shot")
            return textured()

        monkeypatch.setattr(ga, "park_cursor_clear_of", park)
        monkeypatch.setattr(ga, "screenshot", shot)
        monkeypatch.setattr(ga, "_roi_offset", lambda _h, _roi: (0, 972))
        monkeypatch.setattr(
            ga,
            "locate_optional",
            lambda *_a, **_k: ga.Match("btn_observe", 864, 83, 0.99, 1.0, (755, 65, 973, 101)),
        )
        monkeypatch.setattr(ga, "click_client", lambda *_a, **_k: pytest.fail("等按钮不该点"))

        ga._step_look(4242, threshold=0.75)

        assert events[:2] == [f"park:{ga.BOTTOM_ROI}", "shot"], "先停靠、再抓底部条"

    def test_停靠没做成也照抓底部条(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """停靠失败**不许**拦路：它只是前置整理，找不到落点就照原样往下走。"""
        monkeypatch.setattr(ga, "_ensure_live_foreground", lambda h: h)
        monkeypatch.setattr(
            ga, "park_cursor_clear_of", lambda *_a, **_k: _fake_park(performed=False)
        )
        monkeypatch.setattr(ga, "screenshot", lambda _h, **_kw: textured())
        monkeypatch.setattr(ga, "_roi_offset", lambda _h, _roi: (0, 972))
        monkeypatch.setattr(
            ga,
            "locate_optional",
            lambda *_a, **_k: ga.Match("btn_observe", 864, 83, 0.99, 1.0, (755, 65, 973, 101)),
        )

        match, _hwnd = ga._step_look(4242, threshold=0.75)

        assert (match.x, match.y) == (864, 1055), "停靠没成不影响 look 本身"

    def test_普通主菜单先点新游戏再等观察(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """无 ``-scripted_tests`` 时，主菜单也能走到观察者局。"""
        monkeypatch.setattr(ga, "_ensure_live_foreground", lambda h: h)
        monkeypatch.setattr(ga, "park_cursor_clear_of", lambda *_a, **_k: _fake_park())
        monkeypatch.setattr(
            ga,
            "_roi_offset",
            lambda _h, roi: (
                (0, 972)
                if roi == ga.BOTTOM_ROI
                else (100, 200)
                if roi == ga.MAIN_MENU_ROI
                else (200, 300)
            ),
        )
        monkeypatch.setattr(ga, "screenshot", lambda _h, **_kw: textured())
        clicked: list[tuple[int, int]] = []
        shots: list[str] = []
        state = {"new_game": False, "start_game": False}

        def locate(_image: Image.Image, name: str, **_kw: object) -> ga.Match | None:
            if name == "btn_observe":
                return (
                    ga.Match("btn_observe", 864, 83, 0.99, 1.0, (755, 65, 973, 101))
                    if state["start_game"]
                    else None
                )
            if name == "btn_new_game":
                return ga.Match("btn_new_game", 10, 20, 0.80, 1.0, (0, 0, 20, 20))
            if name == "btn_start_game" and state["new_game"]:
                return ga.Match("btn_start_game", 30, 40, 0.80, 1.0, (0, 0, 30, 20))
            return None

        monkeypatch.setattr(ga, "locate_optional", locate)

        def click(_h: int, match: ga.Match, **_kw: object) -> None:
            clicked.append((match.x, match.y))
            if match.name == "btn_new_game":
                state["new_game"] = True
            else:
                state["start_game"] = True

        monkeypatch.setattr(ga, "click_match", click)
        monkeypatch.setattr(ga, "_shot_or_note", lambda _h, tag: shots.append(tag))
        monkeypatch.setattr(ga, "_sleep", lambda _seconds: None)

        match, hwnd = ga._step_look(4242, threshold=0.75, lobby_timeout=1.0, force=True)

        assert hwnd == 4242
        assert match.name == "btn_observe"
        assert clicked == [(110, 220), (230, 340)]
        assert shots == ["09-new-game-click", "09-start-game-click"]


_ADVANCE = ga.Advance(True, "1836.1.1", "1836.1.8", 1.0, "log")


class TestStepOrder:
    """三下的**顺序**与**判据**：观察 → 速度 → 空格，每一步都要有自己的验收。"""

    def _patch(self, monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
        monkeypatch.setattr(ga, "screenshot", lambda _h, **_kw: textured())
        monkeypatch.setattr(ga, "save_shot", lambda _img, _tag: None)
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        monkeypatch.setattr(
            ga, "click_match", lambda _h, m, **_kw: calls.append(f"click_observe:{m.x},{m.y}")
        )
        monkeypatch.setattr(
            ga, "click_client", lambda _h, x, _y, **_kw: calls.append(f"click_speed:{x}")
        )
        monkeypatch.setattr(ga, "press_key", lambda key, **_kw: calls.append(f"press:{key}"))
        monkeypatch.setattr(ga, "wait_for_boot_settle", lambda **_kw: _settle())
        monkeypatch.setattr(ga, "_ensure_live_foreground", lambda h: h)
        monkeypatch.setattr(ga, "_set_foreground", lambda _h: True)
        monkeypatch.setattr(ga, "_foreground_window", lambda: 4242)
        monkeypatch.setattr(ga, "tick_mark", lambda *_a, **_k: ga.TickMark("1836.1.1", 0.0))
        monkeypatch.setattr(ga, "_step_look", lambda *_a, **_kw: (_observe_match(), 4242))
        monkeypatch.setattr(ga, "find_in_roi", lambda *_a, **_kw: None)
        monkeypatch.setattr(
            ga, "speed_candidates", lambda _h, **_kw: [("模板匹配 (1851, 52)", (1851, 52))]
        )
        monkeypatch.setattr(ga, "measure_rate", lambda *_a, **_k: 3.0)
        monkeypatch.setattr(ga, "switch_to_background", lambda *_a, **_k: _handover())
        # 第一次探测：**时间没在走**（所以该按空格）；按完之后的判定：在走。
        answers = iter([None, _ADVANCE, _ADVANCE, _ADVANCE])
        monkeypatch.setattr(ga, "_wait_running", lambda *_a, **_k: next(answers, _ADVANCE))
        monkeypatch.setattr(ga, "wait_until_readable", lambda **_kw: ga.TickMark("1836.1.1", 0.0))

    def test_顺序是观察_速度_空格_且切回后台(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        self._patch(monkeypatch, calls)
        result = ga.start_session(4242, 777, force=True)
        assert calls == ["click_observe:864,1055", "click_speed:1851", "press:space"]
        assert result.rate == 3.0
        assert result.rate_ok is True
        assert result.pressed is True
        assert result.handover.restored is True

    def test_已经在跑就不按空格(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """空格是**暂停开关**，不是"开始"：时间已经在走时按下去会把游戏停住。"""
        calls: list[str] = []
        self._patch(monkeypatch, calls)
        monkeypatch.setattr(ga, "_wait_running", lambda *_a, **_k: _ADVANCE)
        result = ga.start_session(4242, 777, force=True)
        assert result.pressed is False
        assert "没有按" in result.unpause
        assert [c for c in calls if c.startswith("press")] == []

    def test_观察没切走就报错且不继续往下点(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        self._patch(monkeypatch, calls)
        monkeypatch.setattr(ga, "find_in_roi", lambda *_a, **_kw: _observe_match())
        # 让 `wait_until` 至少判断一次"还没切走"（判据本身在 settle_timeout=0 时只会跑一次）
        monkeypatch.setattr(ga, "tick_mark", lambda *_a, **_k: ga.TickMark(ga.NO_TICK, 0.0))
        with pytest.raises(ga.TemplateNotFoundError, match="界面没切走"):
            ga.start_session(4242, 777, settle_timeout=0.0, force=True)
        assert [c for c in calls if c.startswith("click_speed")] == []

    def test_按了空格还是不推进就报错(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        self._patch(monkeypatch, calls)
        monkeypatch.setattr(ga, "_wait_running", lambda *_a, **_k: None)
        with pytest.raises(ga.NotRunningError, match="时间仍没有推进"):
            ga.start_session(4242, 777, force=True)

    def test_点不到观察按钮就不往下点(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """点「观察」那一下抢不到前台 ⇒ 当场中止，**绝不**接着按空格（键盘会打到别处）。

        这条测的是**中止语义**（不是 `ensure_foreground` 本身 —— 那个由
        :class:`TestForeground` 与 `test_按空格前必须重新确认前台` 覆盖）。
        """
        calls: list[str] = []
        self._patch(monkeypatch, calls)

        def lost(_h: int, _m: object = None, **_kw: object) -> None:
            raise ga.ForegroundLostError("抢不到前台：此时点击会送给别的窗口，已中止")

        monkeypatch.setattr(ga, "click_match", lost)
        with pytest.raises(ga.ForegroundLostError):
            ga.start_session(4242, 777, force=True)
        assert [c for c in calls if c.startswith("press")] == []
        assert [c for c in calls if c.startswith("click_speed")] == []

    def test_按空格前必须重新确认前台(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`_step_unpause` 自己也要判一次前台 —— 点击那会儿在前台不等于现在还前台。"""
        monkeypatch.setattr(ga, "_foreground_window", lambda: 999)
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        with pytest.raises(ga.ForegroundLostError, match="不在前台"):
            ga._step_unpause(4242, key_timeout=0.0, run_timeout=0.0, force=True)

    def test_速率不够就补点下一个候选(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        self._patch(monkeypatch, calls)
        # 依次：切回后台前量一次（1.0 不够）→ 补点后再量（3.0）→ 缩窗口后复量（3.0）
        rates = iter([1.0, 3.0, 3.0])
        monkeypatch.setattr(ga, "measure_rate", lambda *_a, **_k: next(rates))
        result = ga.start_session(4242, 777, force=True)
        assert calls.count("click_speed:1851") == 2, "第一次没到 5 档，要补点一次"
        assert result.attempts == 2
        assert result.rate == 3.0

    def test_跳过速度档时不动表盘(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        self._patch(monkeypatch, calls)
        result = ga.start_session(4242, 777, skip_speed=True, force=True)
        assert [c for c in calls if c.startswith("click_speed")] == []
        assert result.speed_source == "跳过（skip_speed）"
        assert result.rate_ok is True

    def test_切回后台之后不推进就当场恢复窗口(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """缩下去不推进是**游戏行为**：当场恢复成普通窗口，并如实报 `minimized=False`。"""
        calls: list[str] = []
        self._patch(monkeypatch, calls)
        rates = iter([3.0, 0.0, 3.0])
        monkeypatch.setattr(ga, "measure_rate", lambda *_a, **_k: next(rates))
        monkeypatch.setattr(ga, "_restore", lambda _h: calls.append("restore"))
        monkeypatch.setattr(ga, "_is_iconic", lambda _h: False)
        result = ga.start_session(4242, 777, force=True)
        assert "restore" in calls
        assert result.handover.minimized is False
        assert result.rate == 3.0

    def test_要求保留前台时就不缩窗口(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, object] = {}
        calls: list[str] = []
        self._patch(monkeypatch, calls)
        monkeypatch.setattr(
            ga,
            "switch_to_background",
            lambda *_a, **_k: seen.update(_k) or _handover(minimized=False),
        )
        ga.start_session(4242, 777, keep_foreground=True, force=True)
        assert seen["minimize"] is False


class TestSessionStartDict:
    """返回值要能直接进汇报：字段齐全、机器可读、没有"看着像成功"的空话。"""

    def test_as_dict_字段齐全(self) -> None:
        payload = _session_start().as_dict()
        for key in (
            "hwnd",
            "previous",
            "boot_settle",
            "observe",
            "speed_source",
            "speed_days_per_second",
            "speed_ok",
            "unpause",
            "running",
            "handover",
            "foreground_restored",
            "minimized",
            "tick",
        ):
            assert key in payload, f"缺字段 {key}"
        assert payload["speed_xy"] == "1851,52"
        assert payload["unpause_pressed"] is True

    def test_跳过速度时坐标是空串而不是_None(self) -> None:
        payload = _session_start(speed_xy=None, speed_source="跳过（skip_speed）").as_dict()
        assert payload["speed_xy"] == ""

    def test_没按空格时如实写(self) -> None:
        payload = _session_start(pressed=False, unpause="时间已经在走 ⇒ 没有按 space").as_dict()
        assert payload["unpause_pressed"] is False
        assert "没有按" in str(payload["unpause"])


class TestRunCommand:
    """`python -m pdx.game_auto run` 必须走**标准流程**（单路，没有回落链）。

    流程口径（用户 2026-09-22）：起游戏到前台 → 加载期不碰窗口 → 点「观察」→
    点 5 档速度 → 按空格 → 切回后台。`main()` 以前完全没有用例，这里把它钉住。
    """

    def _stub(self, monkeypatch: pytest.MonkeyPatch, seen: dict[str, object]) -> None:
        monkeypatch.setattr(ga, "assert_no_game_running", lambda: None)
        monkeypatch.setattr(ga, "launch_to_foreground", lambda **_kw: (4242, 777))
        monkeypatch.setattr(ga, "wait_for_boot_settle", lambda **_kw: _settle())
        monkeypatch.setattr(
            ga,
            "start_session",
            lambda hwnd, previous, **kw: (
                seen.update({"hwnd": hwnd, "previous": previous, **kw}) or _session_start()
            ),
        )

    def test_run_走标准流程并透传开关(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        seen: dict[str, object] = {}
        self._stub(monkeypatch, seen)
        assert ga.main(["run", "--skip-speed", "--keep-foreground"]) == 0
        assert seen["hwnd"] == 4242
        assert seen["previous"] == 777, "要把**起游戏之前**的前台窗口传下去（收尾要还给它）"
        assert seen["skip_speed"] is True
        assert seen["keep_foreground"] is True, "显式要求保留前台时必须传下去"
        assert seen["force"] is True, "显式入口才允许注入真实输入（不靠改模块开关）"
        out = capsys.readouterr().out
        assert "闭环完成" in out
        assert "speed_days_per_second" in out

    def test_run_默认切速度且实测最小化(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, object] = {}
        self._stub(monkeypatch, seen)
        assert ga.main(["run"]) == 0
        assert seen["skip_speed"] is False
        assert seen["verify_minimized"] is True
        assert seen["keep_foreground"] is False

    def test_run_可以关掉最小化实测(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, object] = {}
        self._stub(monkeypatch, seen)
        assert ga.main(["run", "--no-verify-minimized"]) == 0
        assert seen["verify_minimized"] is False

    def test_run_可以显式给速度坐标(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, object] = {}
        self._stub(monkeypatch, seen)
        assert ga.main(["run", "--speed-xy", "1800,40"]) == 0
        assert seen["speed_xy"] == (1800, 40)

    def test_失败时退出码是一(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        """任何一步失败都退 1，不打印"完成"（P13）。"""

        def boom(**_kw: object) -> int:
            raise ga.GameRunningError("已经有 victoria3 在跑")

        monkeypatch.setattr(ga, "launch_to_foreground", boom)
        monkeypatch.setattr(ga, "assert_no_game_running", lambda: None)
        assert ga.main(["run"]) == 1
        err = capsys.readouterr().err
        assert "失败" in err
        assert "GameRunningError" in err


class TestBackgroundCommand:
    def test_background_入口传递真实输入授权(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        seen: dict[str, object] = {}
        monkeypatch.setattr(ga, "find_window", lambda: 4242)

        def fake_background(hwnd: int, **kw: object) -> ga.Advance:
            seen.update({"hwnd": hwnd, **kw})
            return ga.Advance(
                advanced=True,
                before="1836.1.1",
                after="1836.2.1",
                seconds=0.1,
                source="stub",
            )

        monkeypatch.setattr(ga, "background_ok", fake_background)

        assert ga.main(["background", "--seconds", "0.1"]) == 0
        assert seen == {"hwnd": 4242, "seconds": 0.1, "force": True}
        assert "推进" in capsys.readouterr().out


class TestRunSession:
    """`run_session` 是探针共用的入口：起游戏 + 等加载 + 标准流程，一路传参不丢。"""

    def test_把_previous_与开关一起传下去(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, object] = {}
        monkeypatch.setattr(ga, "launch_to_foreground", lambda **_kw: (4242, 777))
        monkeypatch.setattr(ga, "wait_for_boot_settle", lambda **_kw: _settle())
        monkeypatch.setattr(
            ga,
            "start_session",
            lambda hwnd, previous, **kw: (
                seen.update({"hwnd": hwnd, "previous": previous, **kw}) or _session_start()
            ),
        )
        result = ga.run_session(skip_speed=True, keep_foreground=True, force=True)
        assert result.hwnd == 4242
        assert seen["previous"] == 777
        assert seen["skip_speed"] is True
        assert seen["keep_foreground"] is True
        assert seen["settle"] is not None, "等加载的结果要传下去，别在 start_session 里再等一次"
        assert seen["lobby_timeout"] == ga.LOBBY_TIMEOUT, "CLI 的大厅超时不能被 LOOK_TIMEOUT 覆盖"

    def test_失败时清理本会话进程并保留原异常(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[str] = []

        def boom(**_kwargs: object) -> ga.SessionStart:
            raise RuntimeError("流程失败")

        def kill_owned() -> list[int]:
            seen.append("kill")
            return [123]

        monkeypatch.setattr(ga, "_run_session_impl", boom)
        monkeypatch.setattr(ga, "kill_owned_game", kill_owned)
        with pytest.raises(RuntimeError, match="流程失败"):
            ga.run_session()
        assert seen == ["kill"]


class TestClickClientPrevious:
    """`click_client(previous=…)`：给**探针**用的"点完把前台还回去"。

    标准流程不需要它（三下点击期间游戏一直是前台，收尾统一在
    `switch_to_background` 做一次）。但探针会在自己的一局里连点几个 debug 按钮，
    那时点完必须把前台还给用户 —— 所以这个参数存在，且**必须显式传**。
    """

    def _patch(self, monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
        from types import SimpleNamespace

        monkeypatch.setattr(ga, "ALLOW_REAL_INPUT", True)
        monkeypatch.setattr(ga, "ensure_foreground", lambda _h, **_kw: None)
        monkeypatch.setattr(ga, "_client_origin", lambda _h: (0, 0))
        monkeypatch.setattr(ga, "_wait_cursor_at", lambda _x, _y, **_kw: True)
        monkeypatch.setattr(ga, "_set_foreground", _recorder(calls))
        monkeypatch.setattr(
            ga,
            "directinput",
            SimpleNamespace(
                moveTo=lambda x, y: calls.append(f"move:{x},{y}"),
                click=lambda: calls.append("click"),
                position=lambda: (0, 0),
            ),
        )

    def test_不传_previous_就不动前台(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        self._patch(monkeypatch, calls)
        ga.click_client(1, 10, 20)
        assert calls == ["move:10,20", "click"], "标准流程：点完不碰前台（收尾统一做）"

    def test_传了_previous_就点完还原(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        self._patch(monkeypatch, calls)
        ga.click_client(1, 10, 20, previous=777)
        assert calls == ["move:10,20", "click", "set:777"], "探针：点完把前台还给用户"

    def test_previous_就是游戏时不还(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        self._patch(monkeypatch, calls)
        ga.click_client(1, 10, 20, previous=1)
        assert calls == ["move:10,20", "click"]


class _FakeImage:
    """`ImageGrab.grab` 的替身：`_grab` 只用到 `.convert("RGB")`。"""

    def convert(self, _mode: str) -> _FakeImage:
        return self


def _grey_image(
    mean: float, *, spread: float = 0.0, size: tuple[int, int] = (64, 64)
) -> Image.Image:
    """造一张均值/标准差可控的灰度图（拿来喂控制台 ROI 判据）。

    `spread=0` 就是纯色（"空输入框"那种平的画面）；给一点 spread 就相当于"有字"。
    """
    width, height = size
    raw = bytes(
        max(0, min(255, int(mean + (spread if (x + y) % 2 == 0 else -spread))))
        for y in range(height)
        for x in range(width)
    )
    return Image.frombytes("L", size, raw)


class TestConsoleChannel:
    """游戏内控制台：**引擎自带的性能仪表只在控制台里**（backlog B66）。

    这一组钉住三条实测结论：反引号开、合成的字进得去、**要按两次回车才提交**；
    判据全部走画面 ROI（暗面板 = 开着、标准差 = 有没有字），不目测也不猜。
    """

    @staticmethod
    def _stub_rois(
        monkeypatch: pytest.MonkeyPatch, *, edit: Image.Image, output: Image.Image
    ) -> None:
        monkeypatch.setattr(ga, "_client_size", lambda _h: (1920, 1080))

        def fake_screenshot(_hwnd: int, roi: tuple[float, float, float, float]) -> Image.Image:
            # 输入框那个 ROI 落在 y≈0.53 以下；输出区在顶部 —— 用 y0 区分。
            return edit if roi[1] > 0.5 else output

        monkeypatch.setattr(ga, "screenshot", fake_screenshot)

    def test_暗面板判为开着亮面板判为关着(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub_rois(monkeypatch, edit=_grey_image(35.0), output=_grey_image(30.0, spread=60.0))
        assert ga.console_open(4242) is True
        self._stub_rois(monkeypatch, edit=_grey_image(190.0), output=_grey_image(30.0, spread=60.0))
        assert ga.console_open(4242) is False

    def test_已经开着就不再按键(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub_rois(monkeypatch, edit=_grey_image(35.0), output=_grey_image(30.0, spread=60.0))
        monkeypatch.setattr(ga, "press_chord", lambda *_a, **_k: pytest.fail("不该按键"))
        assert ga.open_console(4242, force=True) is True

    def test_关着就按反引号并且看结果(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """判据是 ROI 变暗，**不是**"我按了键" —— 按了没开就如实返回 False。"""
        seen: list[str] = []
        monkeypatch.setattr(ga, "_client_size", lambda _h: (1920, 1080))
        monkeypatch.setattr(ga, "screenshot", lambda _h, roi=None: _grey_image(190.0))  # noqa: ARG005
        monkeypatch.setattr(ga, "press_chord", lambda chord, **_k: seen.append(chord))
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        assert ga.open_console(4242, force=True) is False
        assert seen == [ga.CONSOLE_KEY]
        assert ga.CONSOLE_KEY == "`", "开控制台的键是实测出来的反引号"

    def test_提交要按两次回车(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """实测：按一次 44.9 → 44.0（字一个没少），按两次才 43.0 → 7.5（清空）。"""
        keys: list[str] = []
        inks = iter([244, 1654])
        monkeypatch.setattr(ga, "_client_size", lambda _h: (1920, 1080))
        monkeypatch.setattr(ga, "screenshot", lambda _h, roi=None: _grey_image(35.0))  # noqa: ARG005
        monkeypatch.setattr(ga, "click_client", lambda _h, _x, _y, **_k: None)
        monkeypatch.setattr(ga, "type_text", lambda text, **_k: keys.append(f"type:{text}"))
        monkeypatch.setattr(ga, "press_key", lambda key, **_k: keys.append(key))
        monkeypatch.setattr(ga, "press_chord", lambda *_a, **_k: None)
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        monkeypatch.setattr(ga, "console_output_ink", lambda _h: next(inks))
        monkeypatch.setattr(ga, "_roi_stats", lambda _h, _roi: (35.0, 7.5, 0))
        assert ga.submit_console_command(4242, "dump_ticktask_timings", force=True) is True
        assert keys[-3:] == [
            "type:dump_ticktask_timings",
            "enter",
            "enter",
        ], "敲完必须**连按两次**回车（第一次会被自动补全吃掉）"

    def test_提交前先把焦点交给输入框(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """实测踩过：控制台关不掉 ⇒ 它整局挂着 ⇒ 点过速度表盘之后焦点就不在输入框了，
        下一次敲的命令会**打进游戏**、`dump` 永远"没提交成功"。所以提交前必须先点它一下。"""
        clicks: list[tuple[int, int]] = []
        keys: list[str] = []
        inks = iter([244, 1654])
        monkeypatch.setattr(ga, "_client_size", lambda _h: (1920, 1080))
        monkeypatch.setattr(ga, "screenshot", lambda _h, roi=None: _grey_image(35.0))  # noqa: ARG005
        monkeypatch.setattr(ga, "click_client", lambda _h, x, y, **_k: clicks.append((x, y)))
        monkeypatch.setattr(ga, "type_text", lambda text, **_k: keys.append(f"type:{text}"))
        monkeypatch.setattr(ga, "press_key", lambda key, **_k: keys.append(key))
        monkeypatch.setattr(ga, "press_chord", lambda chord, **_k: keys.append(chord))
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        monkeypatch.setattr(ga, "console_output_ink", lambda _h: next(inks))
        monkeypatch.setattr(ga, "_roi_stats", lambda _h, _roi: (35.0, 7.5, 0))
        assert ga.submit_console_command(4242, "dump_ticktask_timings", force=True) is True
        x0, y0, x1, y1 = ga.CONSOLE_EDIT_ROI
        assert clicks == [((x0 + x1) // 2, (y0 + y1) // 2)], "点的是输入框正中"
        assert keys[:3] == ["ctrl+a", "backspace", "type:dump_ticktask_timings"], "先清空再敲"
        assert "delete" not in keys, (
            "**绝不能用 delete 清空**：pydirectinput 不带扩展位，Delete 的扫描码 0x53 "
            "会变成小键盘的 `.`（实测控制台收到 `.clear_ticktask_timings` → Unknown command）"
        )

    def test_没清空就算没提交(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """输入框没清空 = 命令没执行 —— 不许当成成功（否则会拿着空数据下结论）。"""
        keys: list[str] = []
        monkeypatch.setattr(ga, "_client_size", lambda _h: (1920, 1080))
        monkeypatch.setattr(ga, "screenshot", lambda _h, roi=None: _grey_image(35.0))  # noqa: ARG005
        monkeypatch.setattr(ga, "click_client", lambda _h, _x, _y, **_k: None)
        monkeypatch.setattr(ga, "type_text", lambda text, **_k: keys.append(f"type:{text}"))
        monkeypatch.setattr(ga, "press_key", lambda key, **_k: keys.append(key))
        monkeypatch.setattr(ga, "press_chord", lambda *_a, **_k: None)
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        monkeypatch.setattr(ga, "console_output_ink", lambda _h: 244)
        monkeypatch.setattr(ga, "_roi_stats", lambda _h, _roi: (35.0, 44.0, 900))
        assert ga.submit_console_command(4242, "zzz", force=True, attempts=1) is False
        # 一次"清空"（焦点那一步）+ 一次"失败后擦干净"
        assert keys.count("backspace") == 1 + len("zzz") + 8, "没提交成功要把输入框敲干净"

    def test_ROI_判据走的是分数换算(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`screenshot` 要分数、这里给像素 —— 换算错会炸在 `DecompressionBombError` 上。"""
        seen: list[tuple[float, float, float, float]] = []
        monkeypatch.setattr(ga, "_client_size", lambda _h: (1920, 1080))
        monkeypatch.setattr(ga, "screenshot", _screenshot_stub(seen, _grey_image(35.0)))
        ga.console_open(4242)
        x0, y0, x1, y1 = ga.CONSOLE_EDIT_ROI
        assert seen == [(x0 / 1920, y0 / 1080, x1 / 1920, y1 / 1080)]


class TestGrabGuard:
    """抓图前必须确认**前台就是游戏**：`ImageGrab` 抓的是屏幕，被遮挡时会拿到别的窗口的像素。"""

    def test_不是前台就报错而不是下判断(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "_client_size", lambda _h: (1920, 1080))
        monkeypatch.setattr(ga, "_foreground_window", lambda: 999)
        with pytest.raises(ga.CaptureFailedError, match="就是当前前台窗口"):
            ga._grab(4242, roi=ga.BOTTOM_ROI)

    def test_客户区尺寸非法就报错(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "_client_size", lambda _h: (0, 0))
        with pytest.raises(ga.CaptureFailedError, match="客户区尺寸非法"):
            ga._grab(4242)

    def test_像素当分数传要当场说清楚(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """实测踩过：`roi=(8, 568, 428, 606)` 这种**像素**矩形被当成分数，
        bbox 乘出 330 亿像素，PIL 抛 `DecompressionBombError` ——
        那句报错指不到真正的原因，所以这里要当场拦下来说明白。"""
        monkeypatch.setattr(ga, "_client_size", lambda _h: (1920, 1080))
        monkeypatch.setattr(ga, "_foreground_window", lambda: 4242)
        monkeypatch.setattr(ga, "_client_origin", lambda _h: (0, 0))
        with pytest.raises(ga.CaptureFailedError, match="必须是\\*\\*分数\\*\\*矩形"):
            ga._grab(4242, roi=(8, 568, 428, 606))

    def test_分数矩形照旧放行(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """边界值 0 与 1 都是合法分数，别把守卫写成"必须严格小于 1"。"""
        monkeypatch.setattr(ga, "_client_size", lambda _h: (1920, 1080))
        monkeypatch.setattr(ga, "_foreground_window", lambda: 4242)
        monkeypatch.setattr(ga, "_client_origin", lambda _h: (0, 0))
        monkeypatch.setattr(
            ga, "ImageGrab", type("G", (), {"grab": staticmethod(lambda **_kw: _FakeImage())})
        )
        ga._grab(4242, roi=(0.0, 0.0, 1.0, 1.0))

    def test_是前台才真的抓(self, monkeypatch: pytest.MonkeyPatch) -> None:
        grabbed: list[tuple[int, int, int, int]] = []

        class FakeImage:
            def convert(self, _mode: str) -> FakeImage:
                return self

        def fake_grab(*, bbox: tuple[int, int, int, int], all_screens: bool) -> FakeImage:
            grabbed.append(bbox)
            return FakeImage()

        monkeypatch.setattr(ga, "_client_size", lambda _h: (1920, 1080))
        monkeypatch.setattr(ga, "_foreground_window", lambda: 4242)
        monkeypatch.setattr(ga, "_client_origin", lambda _h: (100, 50))
        monkeypatch.setattr(ga, "ImageGrab", type("G", (), {"grab": staticmethod(fake_grab)}))
        monkeypatch.setattr(ga, "is_blank", lambda _img, **_kw: False)
        ga.screenshot(4242, roi=ga.BOTTOM_ROI)
        assert grabbed == [(100, 50 + 972, 100 + 1920, 50 + 1080)], "ROI 只抓底部那一条"


def test_platform_capabilities_is_read_only() -> None:
    capabilities = ga.platform_capabilities()
    assert capabilities["platform"] == sys.platform
    assert capabilities["background_validation"] is True
    assert capabilities["headless_log_validation"] is True
