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

import os
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import pytest
from PIL import Image

from pdx import game_auto as ga

if TYPE_CHECKING:
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
        assert ga.launch(wait=False) == 0
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
        assert ga.launch(wait=False) == 0
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
#     $env:V3_AUTO_LIVE=1; python -m pytest tools/tests/test_game_auto.py -n0 -q -k live

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
        monkeypatch.setattr(ga, "_set_foreground", lambda h: called.append(f"set:{h}") or True)
        monkeypatch.setattr(ga, "ensure_foreground", lambda h, **_kw: called.append(f"ensure:{h}"))
        assert ga._route_to_foreground(4242, 777, force=True) == 4242
        assert called == ["set:777", "ensure:4242"]

    def test_用户窗口已经关掉就只提游戏(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "_is_alive", lambda h: h == 4242)
        monkeypatch.setattr(ga, "_foreground_window", lambda: 999)
        called: list[str] = []
        monkeypatch.setattr(ga, "_set_foreground", lambda h: called.append(f"set:{h}") or True)
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
