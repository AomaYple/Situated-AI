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


class TestClickObserver:
    def _stage(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> tuple[list[str], dict[str, int]]:
        """搭一个假台子：第一帧是 lobby（有观察按钮），之后是观察者模式。"""
        lobby = textured()
        paste(lobby, OBSERVE_TPL, 755, 1037)
        observer = textured(seed=99)
        frames: list[Image.Image] = [lobby, lobby, observer, observer, observer]
        state = {"n": 0}

        def screenshot(_hwnd: int) -> Image.Image:
            index = min(state["n"], len(frames) - 1)
            state["n"] += 1
            return frames[index]

        clicks: list[str] = []
        monkeypatch.setattr(ga, "screenshot", screenshot)
        monkeypatch.setattr(ga, "click_match", lambda _h, m: clicks.append(m.describe()))
        monkeypatch.setattr(ga, "save_shot", lambda _img, _tag: tmp_path / "x.png")
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        return clicks, state

    @needs_templates
    def test_点中观察按钮并确认它消失了(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        clicks, _ = self._stage(monkeypatch, tmp_path)
        match = ga.click_observer(1)
        assert len(clicks) == 1
        assert abs(match.x - (755 + 218 // 2)) <= 2
        assert abs(match.y - (1037 + 36 // 2)) <= 2

    @needs_templates
    def test_点了但按钮没消失要报错(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """点击落空**绝对不能**静默通过 —— 这是 P13 的正面用例。"""
        lobby = textured()
        paste(lobby, OBSERVE_TPL, 755, 1037)
        monkeypatch.setattr(ga, "screenshot", lambda _hwnd: lobby)
        monkeypatch.setattr(ga, "click_match", lambda _h, _m: None)
        monkeypatch.setattr(ga, "save_shot", lambda _img, _tag: tmp_path / "x.png")
        clock = FakeClock()
        monkeypatch.setattr(ga, "_monotonic", clock)
        monkeypatch.setattr(ga, "_sleep", clock.advance)
        with pytest.raises(ga.TemplateNotFoundError, match="按钮仍在"):
            ga.click_observer(1, verify_timeout=5.0)

    @needs_templates
    def test_lobby_里没有观察按钮时报错(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(ga, "screenshot", lambda _hwnd: textured())
        monkeypatch.setattr(ga, "save_shot", lambda _img, _tag: tmp_path / "x.png")
        with pytest.raises(ga.TemplateNotFoundError):
            ga.click_observer(1, verify=False)


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


class TestUnpause:
    @needs_templates
    def test_点播放键并靠_tick_确认跑起来了(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ticks = TickLog(tmp_path / "t.log")
        monkeypatch.setattr(ga, "TICK_LOG", ticks.path)

        paused = textured()
        paste(paused, PLAY_TPL, 1712, 46)
        monkeypatch.setattr(ga, "screenshot", lambda _hwnd: paused)
        monkeypatch.setattr(ga, "save_shot", lambda _img, _tag: tmp_path / "x.png")
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)

        def click(_hwnd: int, _match: ga.Match) -> None:
            ticks.set("1836.3.1")  # 引擎"开始跑"了

        monkeypatch.setattr(ga, "click_match", click)

        advance = ga.unpause(1, settle=1.0, timeout=10.0)
        assert advance.advanced is True
        assert (advance.before, advance.after) == ("1836.1.1", "1836.3.1")

    @needs_templates
    def test_点了但时间没动要报错(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        ticks = TickLog(tmp_path / "t.log")
        monkeypatch.setattr(ga, "TICK_LOG", ticks.path)
        paused = textured()
        paste(paused, PLAY_TPL, 1712, 46)
        monkeypatch.setattr(ga, "screenshot", lambda _hwnd: paused)
        monkeypatch.setattr(ga, "save_shot", lambda _img, _tag: tmp_path / "x.png")
        monkeypatch.setattr(ga, "click_match", lambda _h, _m: None)
        clock = FakeClock()
        # ⚠️ 假时钟必须由 ``_sleep`` 推着走：``wait_until_running`` 的超时判据是
        # ``tick_clock() - started < timeout``，若 ``_sleep`` 只是空转，
        # 假时钟永远停在 0 ⇒ 条件恒真 ⇒ **死循环**（本用例曾因此把全量跑批
        # 拖成 300 秒超时失败）。假时钟 + 空转睡眠是踩过的坑，别再写回去。
        monkeypatch.setattr(ga, "_sleep", clock.advance)
        monkeypatch.setattr(ga, "_monotonic", clock)
        with pytest.raises(ga.NotRunningError):
            ga.unpause(1, settle=1.0, timeout=5.0)

    def test_已经在跑就不要再点(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """幂等：再点一次播放键会把它**暂停**，所以必须先探一下。"""
        ticks = TickLog(tmp_path / "t.log")
        monkeypatch.setattr(ga, "TICK_LOG", ticks.path)

        def sleeper(_seconds: float) -> None:
            ticks.set("1836.9.1")  # 假装时间在走

        monkeypatch.setattr(ga, "_sleep", sleeper)
        clicked: list[str] = []
        monkeypatch.setattr(ga, "click_match", lambda _h, m: clicked.append(m.describe()))

        advance = ga.unpause(1, settle=1.0)
        assert advance.advanced is True
        assert "已经在跑" in advance.source
        assert clicked == []

    @needs_templates
    def test_暂停画面里找不到播放键要报错(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ticks = TickLog(tmp_path / "t.log")
        monkeypatch.setattr(ga, "TICK_LOG", ticks.path)
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        monkeypatch.setattr(ga, "screenshot", lambda _hwnd: textured(seed=42))
        monkeypatch.setattr(ga, "save_shot", lambda _img, _tag: tmp_path / "x.png")
        with pytest.raises(ga.TemplateNotFoundError):
            ga.unpause(1, settle=1.0)


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


class TestWaitForLobby:
    @needs_templates
    def test_等到了就返回匹配(self, monkeypatch: pytest.MonkeyPatch) -> None:
        lobby = textured()
        paste(lobby, OBSERVE_TPL, 755, 1037)
        # 现在抓图是"只抓底部 ROI"，所以桩要接受 roi 形参（返回的图就当它已经是那一块）
        monkeypatch.setattr(ga, "screenshot", lambda _hwnd, **_kw: lobby)
        # 现在要算 ROI 偏移 ⇒ 客户区尺寸也要打桩（否则会去碰真窗口）
        monkeypatch.setattr(ga, "_client_size", lambda _h: (1920, 1080))
        clock = FakeClock()
        found = ga.wait_for_lobby(1, timeout=5.0, clock=clock, sleeper=clock.advance)
        assert found.name == "btn_observe"

    def test_抓图一直失败也要报出最后原因(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(_hwnd: int, **_kw: object) -> Image.Image:
            raise ga.CaptureFailedError("加载中")

        monkeypatch.setattr(ga, "screenshot", boom)
        clock = FakeClock()
        with pytest.raises(ga.TemplateNotFoundError, match="加载中"):
            ga.wait_for_lobby(1, timeout=5.0, clock=clock, sleeper=clock.advance)


class TestRunUntilRunning:
    def test_闭环把四步串起来并交回证据(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "launch", lambda **_kw: 4242)
        monkeypatch.setattr(
            ga,
            "wait_for_lobby",
            lambda *_a, **_kw: ga.Match(
                "btn_observe", 864, 1055, 0.99, 1.0, (755, 1037, 973, 1073)
            ),
        )
        monkeypatch.setattr(
            ga,
            "click_observer",
            lambda *_a, **_kw: ga.Match(
                "btn_observe", 864, 1055, 0.99, 1.0, (755, 1037, 973, 1073)
            ),
        )
        monkeypatch.setattr(
            ga,
            "unpause",
            lambda *_a, **_kw: ga.Advance(True, "1836.1.1", "1836.2.1", 3.0, "test"),
        )
        monkeypatch.setattr(ga, "probe_months", lambda **_kw: ["RUS", "RUS", "RUS"])
        monkeypatch.setattr(ga, "tick_mark", lambda *_a, **_kw: ga.TickMark("1836.2.1", 0.0))

        result = ga.run_until_running()
        assert result["hwnd"] == 4242
        assert result["probe_month_lines"] == 3
        assert result["tick"] == "1836.2.1"
        assert "btn_observe" in str(result["observe_match"])

    def test_中途失败就整体抛出而不是交半个结果(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "launch", lambda **_kw: 4242)
        monkeypatch.setattr(
            ga,
            "wait_for_lobby",
            lambda *_a, **_kw: (_ for _ in ()).throw(ga.TemplateNotFoundError("没到选择国家界面")),
        )
        with pytest.raises(ga.TemplateNotFoundError):
            ga.run_until_running()


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


@live
@pytest.mark.integration
@pytest.mark.slow
class TestLive:
    def test_闭环到时间在推进(self) -> None:
        """起游戏 → 等到选择国家 → 点观察 → 解除暂停 → 用 tick 确认在跑。"""
        result = ga.run_until_running()
        months = result["probe_month_lines"]
        assert result["hwnd"], "没拿到窗口句柄"
        assert result["tick"], "没有读到 tick —— 时间没在走"
        assert isinstance(months, int)
        assert months >= 0

    def test_后台仍在模拟(self) -> None:
        hwnd = ga.find_window()
        assert hwnd, "游戏没在跑 —— 先跑 test_闭环到时间在推进"
        assert ga.background_ok(hwnd, seconds=15.0).advanced is True


class TestClickGiveBack:
    """点一次要借前台（引擎读原始输入，窗口消息一律不认），但**借了必须还**。"""

    def _patch(self, monkeypatch: pytest.MonkeyPatch, restored: list[int]) -> None:
        from types import SimpleNamespace

        monkeypatch.setattr(ga, "ALLOW_REAL_INPUT", True)  # 显式入口才允许投真实输入
        monkeypatch.setattr(ga, "_foreground_window", lambda: 4242)
        monkeypatch.setattr(ga, "ensure_foreground", lambda _hwnd, **_kw: None)
        monkeypatch.setattr(ga, "_client_origin", lambda _hwnd: (0, 0))
        monkeypatch.setattr(ga, "_sleep", lambda _seconds: None)

        # 还前台走的是成熟库那条缝（`_set_foreground`，内部 `Window.activate()`），
        # 不再是我们手写的 `user32.SetForegroundWindow` —— 打桩点跟着换。
        def remember(handle: int) -> bool:
            restored.append(handle)
            return True

        monkeypatch.setattr(ga, "_set_foreground", remember)
        monkeypatch.setattr(
            ga,
            "directinput",
            SimpleNamespace(
                moveTo=lambda _x, _y: None, click=lambda: None, position=lambda: (0, 0)
            ),
        )

    def test_点完把前台还回去(self, monkeypatch: pytest.MonkeyPatch) -> None:
        restored: list[int] = []
        self._patch(monkeypatch, restored)
        ga.click_client(1, 10, 20)
        assert restored == [4242], "点完必须把原来的前台窗口设回去"

    def test_可以要求不还(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """连着点几下时不必每下都还（还了反而要重新强激活）—— 显式关掉才不还。"""
        restored: list[int] = []
        self._patch(monkeypatch, restored)
        ga.click_client(1, 10, 20, give_back=False)
        assert restored == []

    def test_前台本来就是游戏时不还(self, monkeypatch: pytest.MonkeyPatch) -> None:
        restored: list[int] = []
        self._patch(monkeypatch, restored)
        monkeypatch.setattr(ga, "_foreground_window", lambda: 1)  # 就是 hwnd=1
        ga.click_client(1, 10, 20)
        assert restored == [], "前台本来就是游戏，没有「还」这回事"

    def test_没授权就点必须当场拒绝(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """忘了打桩的用例会走到这里 —— 必须**报错**，绝不能真的动用户的鼠标。

        实测踩过（2026-09-21）：`TestClickGiveBack` 当时还在给 `_set_cursor`/`_mouse_click`
        打桩，可那两个函数早换成了 `pydirectinput` ⇒ 三条用例各点了一次**真实鼠标**，
        把用户正在用的窗口挤到后面。用户当场发现"没开游戏也会这样"。
        """
        restored: list[int] = []
        self._patch(monkeypatch, restored)
        monkeypatch.setattr(ga, "ALLOW_REAL_INPUT", False)
        with pytest.raises(ga.RealInputBlockedError):
            ga.click_client(1, 10, 20)


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


class TestRunCommand:
    """`python -m pdx.game_auto run` 必须走**后台优先的收敛闭环**。

    流程口径（用户 2026-09-21）：后台起游戏 → 后台等启动忙完（只看进程/日志）→
    **一次前台访问**里做完"观察 / 5 档速度 / 空格"→ 立刻还前台 → 后台量速率。
    `main()` 以前完全没有用例（核查报告点名过），这里把它钉住。
    """

    def _stub(self, monkeypatch: pytest.MonkeyPatch, seen: dict[str, object]) -> None:
        monkeypatch.setattr(ga, "assert_no_game_running", lambda: None)
        monkeypatch.setattr(ga, "launch", lambda **_kw: 4242)
        monkeypatch.setattr(
            ga,
            "wait_for_boot_settle",
            lambda **_kw: ga.BootSettle(
                settled=True,
                waited=12.0,
                log_bytes=4096,
                quiet_seconds=8.0,
                processes=1,
                why="进程 1 个；日志 4096 字节",
            ),
        )
        monkeypatch.setattr(
            ga,
            "start_background_session",
            lambda hwnd, **kw: (
                seen.update({"hwnd": hwnd, **kw})
                or {
                    "speed_ok": True,
                    "speed_days_per_second": 2.5,
                    "borrows": 1,
                    "borrow_seconds": 1.2,
                    "background": "推进",
                }
            ),
        )

    def test_run_走收敛版并透传开关(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        seen: dict[str, object] = {}
        self._stub(monkeypatch, seen)
        code = ga.main(["run", "--skip-speed", "--keep-foreground"])
        assert code == 0
        assert seen["hwnd"] == 4242
        assert seen["skip_speed"] is True
        assert seen["give_back"] is False
        out = capsys.readouterr().out
        assert "speed_ok" in out
        assert "闭环完成" in out
        assert "闭环完成" in out

    def test_run_默认会还前台并切速度(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, object] = {}
        self._stub(monkeypatch, seen)
        assert ga.main(["run"]) == 0
        assert seen["skip_speed"] is False
        assert seen["give_back"] is True
        assert seen["speed_xy"] is None
        assert seen["force"] is True, "显式入口才允许注入真实输入（不靠改模块开关）"

    def test_run_可以显式给速度坐标(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, object] = {}
        self._stub(monkeypatch, seen)
        assert ga.main(["run", "--speed-xy", "1800,40"]) == 0
        assert seen["speed_xy"] == (1800, 40)

    def test_失败时退出码是一(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        """任何一步失败都退 1，不打印"完成"（P13）。"""

        def boom(**_kw: object) -> int:
            raise ga.GameRunningError("已经有 victoria3 在跑")

        monkeypatch.setattr(ga, "launch", boom)
        monkeypatch.setattr(ga, "assert_no_game_running", lambda: None)
        assert ga.main(["run"]) == 1
        err = capsys.readouterr().err
        assert "失败" in err
        assert "GameRunningError" in err


class TestEnsureVisible:
    """最小化启动之后，要点击时怎么把窗口"显示出来又不抢前台"。

    这条是用户口径的关键接缝：①起游戏不占屏 ⇒ 但②要点击 ⇒ 中间必须有一次"显示"，
    而显示**不该顺手把焦点抢走**（除非 `SW_SHOWNOACTIVATE` 解不开最小化，那时才
    `SW_RESTORE` 并**立刻把前台还回去**）。
    """

    def _patch_user32(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        iconic_first: bool,
        iconic_after_show: bool,
        shown: list[str],
        foreground_calls: list[int],
    ) -> None:
        """打桩点跟着实现走：现在这些动作都在**成熟库缝隙**上（`_is_iconic` /
        `_show_no_activate` / `_restore` / `_set_foreground`），不再是我们手写的 `user32`。"""
        state = {"iconic": iconic_first}

        def show_no_activate(_hwnd: object) -> None:
            shown.append("show_no_activate")
            state["iconic"] = iconic_after_show

        def restore(_hwnd: object) -> None:
            shown.append("restore")
            state["iconic"] = False

        monkeypatch.setattr(ga, "_is_iconic", lambda _hwnd: state["iconic"])
        monkeypatch.setattr(ga, "_show_no_activate", show_no_activate)
        monkeypatch.setattr(ga, "_restore", restore)

        def remember_foreground(handle: int) -> bool:
            foreground_calls.append(handle)
            return True

        monkeypatch.setattr(ga, "_set_foreground", remember_foreground)
        monkeypatch.setattr(ga, "_foreground_window", lambda: 4242)
        monkeypatch.setattr(ga, "_sleep", lambda _s: None)
        monkeypatch.setattr(ga, "WINDOW_SHOW_SETTLE", 0.0)

    def test_没最小化就什么都不做(self, monkeypatch: pytest.MonkeyPatch) -> None:
        shown: list[str] = []
        self._patch_user32(
            monkeypatch,
            iconic_first=False,
            iconic_after_show=False,
            shown=shown,
            foreground_calls=[],
        )
        assert "本来就不是最小化" in ga.ensure_visible_for_capture(1)
        assert shown == []

    def test_最小化时显示但不抢前台(self, monkeypatch: pytest.MonkeyPatch) -> None:
        shown: list[str] = []
        fg: list[int] = []
        self._patch_user32(
            monkeypatch,
            iconic_first=True,
            iconic_after_show=False,
            shown=shown,
            foreground_calls=fg,
        )
        note = ga.ensure_visible_for_capture(1)
        assert shown == ["show_no_activate"], "先试不激活的显示"
        assert fg == [], "没抢前台就不该动前台"
        assert "没有抢前台" in note

    def test_不激活解不开最小化时才恢复并立刻还前台(self, monkeypatch: pytest.MonkeyPatch) -> None:
        shown: list[str] = []
        fg: list[int] = []
        self._patch_user32(
            monkeypatch, iconic_first=True, iconic_after_show=True, shown=shown, foreground_calls=fg
        )
        note = ga.ensure_visible_for_capture(1)
        assert shown == ["show_no_activate", "restore"]
        assert fg == [4242], "restore() 会激活窗口 ⇒ 必须立刻把前台还回去"
        assert "还回去" in note


# ────────────────────────── 前台借用：后台优先的最后一道保证 ──────────────────────────


class TestBorrowForeground:
    """`borrow_foreground` 是**唯一**碰前台的入口（用户口径：只在需要点击时切前台）。

    它必须是结构性的，不能靠"每个调用点记得还"：进了必还、出借用期输入立刻收紧。
    """

    def _patch(self, monkeypatch: pytest.MonkeyPatch, foreground: list[int]) -> None:
        from types import SimpleNamespace

        monkeypatch.setattr(ga, "ALLOW_REAL_INPUT", True)
        monkeypatch.setattr(ga, "_foreground_window", lambda: foreground[-1])
        monkeypatch.setattr(
            ga,
            "ensure_foreground",
            lambda hwnd, **_kw: foreground.append(hwnd),  # 借 = 游戏变成前台
        )

        def remember(handle: int) -> bool:
            foreground.append(handle)
            return True

        monkeypatch.setattr(ga, "_set_foreground", remember)
        monkeypatch.setattr(
            ga, "directinput", SimpleNamespace(press=lambda _key: foreground.append(-1))
        )

    def test_借了必还并把时长记账(self, monkeypatch: pytest.MonkeyPatch) -> None:
        foreground = [777]
        self._patch(monkeypatch, foreground)
        with ga.borrow_foreground(4242) as visit:
            assert visit.previous == 777
            assert ga._INPUT_GATE.borrow_depth == 1, "借用期内输入必须自动放行"
            ga.press_key("space")  # 借用期内的按键不该被闸门拦下
        assert foreground[-1] == 777, "退出时**一定**要把前台还给原来那个窗口"
        assert visit.restored is True
        assert visit.seconds >= 0.0
        assert ga._INPUT_GATE.borrow_depth == 0, "出了借用期，借用深度必须归零"

    def test_没授权就借前台必须拒绝(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ga, "ALLOW_REAL_INPUT", False)
        monkeypatch.setattr(ga, "ensure_foreground", lambda _h, **_kw: pytest.fail("不许碰窗口"))
        with pytest.raises(ga.RealInputBlockedError), ga.borrow_foreground(4242):
            pass

    def test_可以显式要求不还(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """探针要连着做几步时可以不还，但这必须是**显式**的（默认一定还）。"""
        foreground = [777]
        self._patch(monkeypatch, foreground)
        with ga.borrow_foreground(4242, give_back=False) as visit:
            assert foreground[-1] == 4242
        assert foreground[-1] == 4242, "显式关掉才允许留在游戏上"
        assert visit.restored is True

    def test_嵌套借用退出后仍然收紧(self, monkeypatch: pytest.MonkeyPatch) -> None:
        foreground = [777]
        self._patch(monkeypatch, foreground)
        with ga.borrow_foreground(4242):
            with ga.borrow_foreground(4242):
                assert ga._INPUT_GATE.borrow_depth == 2
            assert ga._INPUT_GATE.borrow_depth == 1, "外层还在借用期内"
        assert ga._INPUT_GATE.borrow_depth == 0


class TestSessionFlow:
    """闭环：**首选不抢前台**做完"观察 → 5 档速度 → 空格"，失效才回落借前台，然后后台验证。

    这条用例把用户口径的**顺序**、**借用次数**与**回落条件**钉住：
    顺序错了（比如先按空格再切速度）或者动不动就借前台（用户会看到闪动）都要红。
    """

    def _patch(self, monkeypatch: pytest.MonkeyPatch, calls: list[str], borrows: list[int]) -> None:
        from contextlib import contextmanager

        @contextmanager
        def fake_borrow(hwnd: int, **_kw: object):
            borrows.append(hwnd)
            calls.append("borrow")
            try:
                yield ga.ForegroundVisit(previous=777, seconds=0.5, restored=True)
            finally:
                calls.append("give_back")

        monkeypatch.setattr(ga, "borrow_foreground", fake_borrow)
        monkeypatch.setattr(ga, "screenshot", lambda _h, **_kw: textured())
        monkeypatch.setattr(
            ga,
            "locate",
            lambda *_a, **_k: ga.Match(
                name="btn_observe", x=864, y=1055, score=0.98, scale=1.0, box=(755, 1037, 973, 1073)
            ),
        )
        monkeypatch.setattr(ga, "save_shot", lambda _img, _tag: None)
        # **首选路线**：不抢前台点击 / 不抢前台按键
        monkeypatch.setattr(
            ga, "click_client_nosteal", lambda _h, x, y, **_kw: calls.append(f"click:{x},{y}")
        )
        monkeypatch.setattr(ga, "press_key_at", lambda _h, key, **_kw: calls.append(f"press:{key}"))
        # **回落路线**（借前台那条）
        monkeypatch.setattr(
            ga, "click_match", lambda _h, _m, **_kw: calls.append("click_foreground")
        )
        monkeypatch.setattr(ga, "click_client", lambda _h, x, _y, **_kw: calls.append(f"fg:{x}"))
        monkeypatch.setattr(ga, "press_key", lambda key, **_kw: calls.append(f"press_fg:{key}"))

        def show(_h: int) -> str:
            calls.append("show")
            return "显示"

        monkeypatch.setattr(ga, "ensure_visible_for_capture", show)
        monkeypatch.setattr(ga, "lobby_visible", lambda _h, **_kw: None)
        # 回落路径找播放键走 `locate_optional`（找不到不算致命，速率才是最终判据）
        monkeypatch.setattr(
            ga,
            "locate_optional",
            lambda *_a, **_k: ga.Match(
                name="btn_play", x=1851, y=52, score=0.99, scale=1.0, box=(1840, 40, 1862, 64)
            ),
        )
        monkeypatch.setattr(
            ga,
            "wait_for_lobby",
            lambda _h, **_kw: ga.Match(
                name="btn_observe", x=864, y=1055, score=0.98, scale=1.0, box=(755, 1037, 973, 1073)
            ),
        )
        monkeypatch.setattr(
            ga, "speed_candidates", lambda _h, **_kw: [("模板匹配 (1851, 52)", (1851, 52))]
        )
        monkeypatch.setattr(ga, "tick_mark", lambda *_a, **_k: ga.TickMark("1836.1.1", 0.0))
        monkeypatch.setattr(ga, "_minimize", lambda _h: calls.append("minimize"))
        monkeypatch.setattr(ga, "_show_no_activate", lambda _h: calls.append("show_no_activate"))
        monkeypatch.setattr(
            ga,
            "wait_until_running",
            lambda *_a, **_k: ga.Advance(
                advanced=True, before="1836.1.1", after="1836.1.8", seconds=1.0, source="log"
            ),
        )
        monkeypatch.setattr(
            ga,
            "background_ok",
            lambda *_a, **_k: ga.Advance(
                advanced=True, before="1836.1.8", after="1836.2.1", seconds=20.0, source="log"
            ),
        )

    def test_首选路线不抢前台且顺序是观察_速度_空格(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        borrows: list[int] = []
        self._patch(monkeypatch, calls, borrows)
        monkeypatch.setattr(ga, "measure_rate", lambda *_a, **_k: 3.0)

        result = ga.start_background_session(4242, force=True)

        assert calls[:3] == ["click:864,1055", "click:1851,52", "press:space"]
        assert "minimize" in calls, "验证完把窗口缩回后台"
        assert borrows == [], "首选路线不该借前台（实测：不抢前台也能点中）"
        assert result["borrows"] == 0
        assert result["speed_ok"] is True
        assert result["speed_days_per_second"] == 3.0

    def test_观察没生效才回落借前台(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """首选路线点不动（按钮还在）⇒ 借一次前台重做「观察」，并把回落写进现场。"""
        calls: list[str] = []
        borrows: list[int] = []
        self._patch(monkeypatch, calls, borrows)
        monkeypatch.setattr(ga, "measure_rate", lambda *_a, **_k: 3.0)
        # 让"界面切走"这一判据**判不出来**（wait_until 给 False）⇒ 走回落分支。
        # 为什么不用调用计数模拟：`_step_observe` 的判据是
        # `lobby_visible(...) is None or tick_mark().readable`，tick 一可读就短路成"切走"，
        # 计数法根本模拟不出"没生效"。
        monkeypatch.setattr(ga, "wait_until", lambda *_a, **_k: False)

        result = ga.start_background_session(4242, force=True)

        assert borrows == [4242], "首选失效时借一次前台"
        assert calls.count("click_foreground") == 1, "回落后用借前台那条路点「观察」"
        assert "借前台重做" in str(result.get("fallback", "")), result.get("fallback")

    def test_速率不够只再借一次点速度(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        borrows: list[int] = []
        self._patch(monkeypatch, calls, borrows)
        rates = iter([1.0, 3.0])
        monkeypatch.setattr(ga, "measure_rate", lambda *_a, **_k: next(rates))

        result = ga.start_background_session(4242, force=True)

        assert borrows == [], "补点速度也走不抢前台 ⇒ 一次前台都不用借"
        assert calls.count("click:864,1055") == 1, "观察只点一次"
        assert calls.count("press:space") == 1, "空格也只按一次"
        assert calls.count("click:1851,52") == 2, "速度点了两次（第一次没到 5 档）"
        assert result["speed_attempts"] == 2
        assert result["speed_ok"] is True

    def test_空格没被接受就借一次点播放键(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        borrows: list[int] = []
        self._patch(monkeypatch, calls, borrows)
        monkeypatch.setattr(ga, "measure_rate", lambda *_a, **_k: 3.0)
        attempts = {"n": 0}

        def running(*_a: object, **_k: object) -> ga.Advance:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise ga.NotRunningError("第一次没动")
            return ga.Advance(
                advanced=True, before="1836.1.1", after="1836.1.8", seconds=1.0, source="log"
            )

        monkeypatch.setattr(ga, "wait_until_running", running)

        result = ga.start_background_session(4242, force=True)

        assert borrows == [4242], "回落找播放键时才借前台"
        assert "播放键" in str(result["unpause"])

    def test_两步都不动就报错不交半个结果(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        borrows: list[int] = []
        self._patch(monkeypatch, calls, borrows)
        monkeypatch.setattr(ga, "measure_rate", lambda *_a, **_k: 3.0)

        def stuck(*_a: object, **_k: object) -> ga.Advance:
            raise ga.NotRunningError("没动")

        monkeypatch.setattr(ga, "wait_until_running", stuck)
        with pytest.raises(ga.NotRunningError, match="时间没有推进"):
            ga.start_background_session(4242, force=True, run_timeout=1.0)

    def test_skip_speed_时不动速度档(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        borrows: list[int] = []
        self._patch(monkeypatch, calls, borrows)

        result = ga.start_background_session(4242, skip_speed=True, force=True)

        assert not [c for c in calls if c.startswith(("click:1851", "fg:1851"))]
        assert result["speed_ok"] is True
        assert result["speed_source"] == "跳过（skip_speed）"
        assert result["speed_attempts"] == 0


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


class TestCaptureCostAndGuards:
    """抓图的两条硬口径：**只抓需要的区域** + **不是前台就报错**（P2 + P13）。"""

    def test_不是前台就拒绝抓图(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`ImageGrab` 抓的是屏幕：**那块像素不属于这个窗口**时宁可报错也不猜。

        判据是"采样点上压着的窗口是不是它"（`WindowFromPoint`）—— 不是"它是不是前台"：
        看一眼界面不需要焦点，用前台当判据会把等待逼进借前台期间（实测 ⇒ 用户黑屏几十秒）。
        """
        monkeypatch.setattr(ga, "_client_size", lambda _h: (1920, 1080))
        monkeypatch.setattr(ga, "_client_origin", lambda _h: (0, 0))
        monkeypatch.setattr(ga.win32gui, "WindowFromPoint", lambda _pt: 999)
        monkeypatch.setattr(ga.win32gui, "GetAncestor", lambda _h, _flag: 999)
        with pytest.raises(ga.CaptureFailedError, match="像素"):
            ga._grab(4242)

    def test_ROI_只抓那一块(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from types import SimpleNamespace

        monkeypatch.setattr(ga, "_client_size", lambda _h: (1920, 1080))
        monkeypatch.setattr(ga, "_client_origin", lambda _h: (100, 50))
        monkeypatch.setattr(ga.win32gui, "WindowFromPoint", lambda _pt: 4242)
        seen: dict[str, object] = {}

        def fake_grab(*, bbox: tuple[int, int, int, int], all_screens: bool) -> Image.Image:
            seen["bbox"] = bbox
            return Image.new("RGB", (bbox[2] - bbox[0], bbox[3] - bbox[1]), (9, 9, 9))

        monkeypatch.setattr(ga, "ImageGrab", SimpleNamespace(grab=fake_grab))
        image = ga._grab(4242, ga.BOTTOM_ROI)
        assert seen["bbox"] == (100, 50 + 972, 2020, 50 + 1080), "底部条：只有整屏的 1/10"
        assert image.size == (1920, 108)


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
