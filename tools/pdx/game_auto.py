"""Victoria 3 自动化：窗口级截图 + 图像匹配 + 前进点击 + 日志真值。

为什么需要这个模块
------------------
阶段 3 的判据要求「固定开局、同一套指令序列跑 A/B 两遍」—— 一局是分钟级到小时级，
靠人坐在电脑前点是不行的。而**官方流水线只差一击**：

    实测 ``binaries\\victoria3.exe -gdpr-compliant -debug_mode -scripted_tests``
    会自己生成开局、存初始档、读回、进到引擎日志里的 ``ingame-idler``
    （成绩单见 ``logs/custom_automated_stats.log`` 的 ``time-to-reach-ingame-idler``），
    然后**停在选择国家界面等人点**。

所以本模块承担的角色很窄：**点火**。点火之后跑与判定全部交回引擎
（``-scripted_tests`` 自己写 ``Documents\\…\\tests.txt`` 与 ``binaries\\*_GameTests_testoutput.xml``），
本模块只负责"读它写了什么"。判定绝不自己做 —— 那是假红/假绿的来源。

三条硬约束（都是实测踩出来的，各自标了出处）
--------------------------------------------
1. **点击前必须确认游戏是前台**。``SetForegroundWindow`` 在调用进程自己不是前台进程时
   **静默失败**（返回 0）。实测：前台被 Edge 占着时点「观察」按钮毫无反应，
   截图与点击前逐像素相同 —— 而当时把原因误判成"坐标不准"，白跑了一轮。
2. **"日志没长"不能证明"点击没生效"**：游戏暂停时不写日志。
   所以"点击是否生效"必须用**截图对比**或 **tick 真值**判定。
3. **键盘这条路走不通**（实测）：窗口在 Win32 层面确实是 active+focus
   （``GetGUIThreadInfo`` 的 ``hwndActive == hwndFocus == 游戏窗口``），
   但 ``keybd_event`` 与 ``SendInput`` 发的空格一律**不被引擎接受**
   （用 tick 判据验证：按空格后时间照常推进，说明暂停快捷键根本没被收到）。
   鼠标点击**有效** —— 引擎读的是光标位置与按键状态，不是注入的键盘事件。
   因此本模块只用鼠标；控制台路线随之不可用（见 `docs/design/exec/自动化范式.md` §3）。

与假红有关的一条
----------------
``-scripted_tests`` 的 ``tests.txt`` 末尾会带一行 ``[ FAIL ] Error log: N errors``，
那是 harness 在数**整份** ``error.log``（原版自身就有几十条噪音）。
判定只许数"我们命名空间内的错误"，那行本身**不是**我们的失败。
"""

from __future__ import annotations

import argparse
import ctypes
import re
import subprocess
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

import cv2
import numpy as np
import pydirectinput as directinput
from PIL import Image

from . import config, experiments

#: `pydirectinput` 的两个开关必须由我们定死：
#: * `FAILSAFE`：鼠标移到屏幕角落就抛异常中断 —— 自动化里这是**随机失败源**，关掉；
#: * `PAUSE`：库默认每次调用后 sleep 0.1 秒 —— 一次点击要调 `moveTo` + `click` 两次，
#:   留着它每点一下多花 0.2 秒，且与调用方自己的 `settle` 重复。
directinput.FAILSAFE = False
directinput.PAUSE = 0.0

if TYPE_CHECKING:
    from collections.abc import Callable

    # 注入缝的类型别名：**只给类型检查器看**，运行期不存在这两个名字。
    # 为什么不在运行期定义：`collections.abc.Callable` 若只用在注解里，
    # ruff 的 TC003 会要求它进 type-checking 块（本仓既有口径）。
    Clock = Callable[[], float]
    Sleeper = Callable[[float], None]

# ────────────────────────── 常量 ──────────────────────────

#: 游戏窗口标题与窗口类（实测：``SDL_app``）。
WINDOW_TITLE = "Victoria 3"
WINDOW_CLASS = "SDL_app"

#: 模块自带的按钮模板目录（小 PNG）。
UI_DIR = config.REPO / "tools" / "probe" / "zz_probe_ab" / "ui"

#: 失败时的证据截图落这里（``tools/out`` 已 gitignore）。
SHOT_DIR = config.OUT / "auto"

#: 官方自动化开关。
SCRIPTED_TESTS_ARG = "-scripted_tests"

#: 引擎逐 tick 写的时间真值（比 debug.log 细，不必等月度边界）。
TICK_LOG = config.USERDIR / "logs" / "dedicated_server.log"

#: 探针的月度自报（``debug_log`` 效果写出来的）。
DEBUG_LOG = config.USERDIR / "logs" / "debug.log"

#: ``Processing Tick: 1836.5.31.12``
TICK_RE = re.compile(r"Processing Tick:\s*(\d+(?:\.\d+)*)")

#: ``[23:37:07][jomini_effect_impl.cpp:454]: <文件>:<行>: ZZPROBE AB;ROLE;RUS``
PROBE_RE = re.compile(r"ZZPROBE\s+AB;ROLE;(\w+)")

#: 找不到 tick 时的返回值。**空串不是"时间没走"，是"读不到"** —— 两者必须分开。
NO_TICK = ""

#: 图像匹配阈值。实测同机同分辨率下匹配分数 >0.95；0.75 是给缩放/抗锯齿留余量。
DEFAULT_THRESHOLD = 0.75

#: 允许的缩放档：不同分辨率 / ``GUI.scale`` 下模板会等比变化。
DEFAULT_SCALES: tuple[float, ...] = (1.0, 0.9, 1.1, 0.8, 1.25, 1.5)

#: 「观察」按钮在底部条 / 播放键在右上角 —— 限定搜索范围能显著降误匹配。
BOTTOM_ROI = (0.0, 0.90, 1.0, 1.0)
TOP_RIGHT_ROI = (0.80, 0.0, 1.0, 0.12)

#: 官方流水线实测要 ~137 秒才到 ingame idler，所以等待给足余量。
LOBBY_TIMEOUT = 300.0
WINDOW_TIMEOUT = 180.0
RUN_TIMEOUT = 90.0
POLL_INTERVAL = 2.0

#: 速度档 V（扇形最右扇区）的**实测客户区坐标**（1920x1080、简体中文，
#: 见 `docs/design/exec/自动化范式.md` §4.3）。⚠️ 它没走模板匹配，所以分辨率 /
#: UI 缩放 / 界面语言一变就失效（backlog B34）—— 传 `speed_xy=None` 可以跳过这一步。
SPEED_V_XY = (1851, 52)


# ────────────────────────── 异常 ──────────────────────────
#
# P13：失败要出声。下面每一个都是"不确定就别继续"的产物 ——
# 尤其 TemplateNotFoundError 与 ForegroundLostError：这两种情况下点击会**静默落空**，
# 若吞掉异常，上层会拿到一个"跑完了但全是空的"结果而毫不知情。


class GameAutoError(RuntimeError):
    """本模块所有失败的基类。"""


class GameRunningError(GameAutoError):
    """已经有 victoria3 进程在跑 —— 不许再起一个。"""


class WindowNotFoundError(GameAutoError):
    """找不到游戏窗口。"""


class ForegroundLostError(GameAutoError):
    """抢不到前台。**此时点击会送给别的窗口**，必须中止而不是照点。"""


class TemplateNotFoundError(GameAutoError):
    """模板没匹配上 —— 按钮不在预期位置（分辨率 / UI 缩放 / 界面语言变了）。"""


class NotRunningError(GameAutoError):
    """点了播放键，但时间没有真的开始推进。"""


class CaptureFailedError(GameAutoError):
    """抓图失败，或抓到近乎纯色的画面（加载中 / 最小化）。"""


# ────────────────────────── 数据结构 ──────────────────────────


@dataclass(frozen=True, slots=True)
class Match:
    """一次模板匹配的结果。``x``/``y`` 是**客户区**坐标下的中心点。"""

    name: str
    x: int
    y: int
    score: float
    scale: float
    box: tuple[int, int, int, int]  # left, top, right, bottom（客户区）

    def describe(self) -> str:
        return (
            f"{self.name} @ ({self.x},{self.y}) "
            f"score={self.score:.3f} scale={self.scale:.2f} box={self.box}"
        )


@dataclass(frozen=True, slots=True)
class TickMark:
    """某一刻的时间真值。``tick`` 为空表示**读不到**，不是"没走"。"""

    tick: str
    mtime: float

    @property
    def readable(self) -> bool:
        return self.tick != NO_TICK

    def describe(self) -> str:
        return f"tick={self.tick or '<读不到>'} mtime={self.mtime:.0f}"


@dataclass(frozen=True, slots=True)
class Advance:
    """一次"确认时间在推进"的结果 —— 带够证据，便于直接写进汇报。"""

    advanced: bool
    before: str
    after: str
    seconds: float
    source: str

    def describe(self) -> str:
        verdict = "推进" if self.advanced else "未推进"
        return f"[{self.source}] {self.before} -> {self.after} ({self.seconds:.1f}s) {verdict}"


# ────────────────────────── 纯逻辑（不碰系统，便于用例覆盖）──────────────────────────


def parse_tick_date(text: str) -> tuple[int, ...]:
    """把 ``1836.5.31.12`` 解析成可比较的整数元组；解析不出来给空元组。

    ⚠️ **不能直接拿字符串比大小**：``"1836.10.1" < "1836.9.1"`` 在字典序下成立，
    而在时间上恰好相反（10 月晚于 9 月）。这是本模块最容易埋进去的静默错误，
    所以单独一个函数，并有用例钉住。
    """
    parts = text.strip().split(".")
    if not parts or not all(p.isdigit() for p in parts):
        return ()
    return tuple(int(p) for p in parts)


def is_later(before: str, after: str) -> bool:
    """``after`` 在 ``before`` 之后吗？任一解析不出来 → False（不装作知道）。"""
    first, second = parse_tick_date(before), parse_tick_date(after)
    if not first or not second:
        return False
    return second > first


def last_tick_in(text: str) -> str:
    """从日志文本里取最后一条 tick；没有则返回 :data:`NO_TICK`。"""
    hits = TICK_RE.findall(text)
    return hits[-1] if hits else NO_TICK


def probe_roles_in(text: str) -> list[str]:
    """从 debug.log 文本里取探针的月度自报国家（``ZZPROBE AB;ROLE;<TAG>``）。"""
    return PROBE_RE.findall(text)


def parse_tasklist_pids(text: str) -> list[int]:
    """从 ``tasklist /FO CSV /NH`` 的输出里取 PID。

    中文 Windows 上"没有运行的任务"那句是本地化的、编码是 GBK，
    所以这里**只认纯数字字段**，其余一律忽略 —— 不去猜文案。
    """
    pids: list[int] = []
    for line in text.splitlines():
        for col in (c.strip().strip('"') for c in line.split('","')):
            if col.isdigit():
                pids.append(int(col))
                break
    return pids


def roi_box(
    roi: tuple[float, float, float, float], width: int, height: int
) -> tuple[int, int, int, int]:
    """把相对 ROI（0~1）换算成像素框，并夹到图像范围内。"""
    left = max(0, min(width, round(roi[0] * width)))
    top = max(0, min(height, round(roi[1] * height)))
    right = max(left, min(width, round(roi[2] * width)))
    bottom = max(top, min(height, round(roi[3] * height)))
    return (left, top, right, bottom)


def to_bgr(array: np.ndarray) -> np.ndarray:
    """统一成 3 通道 —— 模板与截图的通道数必须一致，否则 matchTemplate 直接抛。"""
    if array.ndim == 2:
        return np.asarray(cv2.cvtColor(array, cv2.COLOR_GRAY2BGR))
    if array.shape[2] == 4:
        return np.asarray(cv2.cvtColor(array, cv2.COLOR_RGBA2BGR))
    return array


def is_blank(image: Image.Image, *, min_std: float = 6.0) -> bool:
    """近乎纯色的画面（加载中 / 最小化）判为空白。

    用途：模板没匹配上时区分「界面变了」与「画面还没出来」——
    两者的处理完全不同，不能合并成一句"没找到"。
    """
    arr = np.asarray(image.convert("L"), dtype=np.float32)
    return bool(arr.std() < min_std)


def match_template(
    image: np.ndarray,
    template: np.ndarray,
    *,
    name: str = "template",
    threshold: float = DEFAULT_THRESHOLD,
    scales: tuple[float, ...] = (1.0,),
    roi: tuple[float, float, float, float] | None = None,
) -> Match | None:
    """在 ``image`` 里找 ``template``，返回**最佳**匹配（低于阈值给 ``None``）。

    多尺度是必要的：``pdx_settings.json`` 的 ``GUI.scale`` 与分辨率都会等比改变
    按钮大小，而模板是某一台机器上量出来的。按**模板**缩放（而不是缩放截图），
    这样候选尺寸少、也不会把大图反复重采样。
    """
    screen = to_bgr(np.ascontiguousarray(image))
    height, width = screen.shape[:2]

    if roi is not None:
        left, top, right, bottom = roi_box(roi, width, height)
        screen = screen[top:bottom, left:right]
    else:
        left = top = 0

    base = to_bgr(np.ascontiguousarray(template))
    best: Match | None = None

    for scale in scales:
        if scale <= 0:
            continue
        tpl = base
        if scale != 1.0:
            tpl = cv2.resize(
                base,
                (max(1, round(base.shape[1] * scale)), max(1, round(base.shape[0] * scale))),
                interpolation=cv2.INTER_AREA,
            )
        tpl_h, tpl_w = tpl.shape[:2]
        if tpl_h > screen.shape[0] or tpl_w > screen.shape[1]:
            continue  # 模板比搜索区还大：这一档不可能匹配
        result = cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        score = float(max_val)
        if best is not None and score <= best.score:
            continue
        # 匹配到的是左上角；点击要点中心
        origin_x = left + int(max_loc[0])
        origin_y = top + int(max_loc[1])
        best = Match(
            name=name,
            x=origin_x + tpl_w // 2,
            y=origin_y + tpl_h // 2,
            score=score,
            scale=scale,
            box=(origin_x, origin_y, origin_x + tpl_w, origin_y + tpl_h),
        )

    if best is None or best.score < threshold:
        return None
    return best


def find_template(
    image: np.ndarray,
    template: np.ndarray,
    *,
    name: str,
    threshold: float = DEFAULT_THRESHOLD,
    scales: tuple[float, ...] = DEFAULT_SCALES,
    roi: tuple[float, float, float, float] | None = None,
) -> Match:
    """:func:`match_template` 的"必须找到"版本 —— 找不到就报错（P13）。"""
    found = match_template(image, template, name=name, threshold=threshold, scales=scales, roi=roi)
    if found is None:
        raise TemplateNotFoundError(
            f"模板 {name!r} 没匹配上（阈值 {threshold}，尺度 {scales}）—— "
            f"按钮不在预期位置：分辨率 / UI 缩放 / 界面语言变了？"
        )
    return found


def wait_until(
    predicate: object,
    *,
    timeout: float,
    interval: float = POLL_INTERVAL,
    clock: object = time.monotonic,
    sleeper: object = time.sleep,
) -> object:
    """轮询 ``predicate()`` 直到真值或超时；超时返回最后一次的假值。

    形参标成 ``object`` 再在函数内断言可调用：本模块开着 ``warn_return_any``，
    用 ``Callable`` 泛型在这里只会让调用点更难读，而调用点全是内部的。
    """
    if not callable(predicate):
        raise TypeError("predicate 必须可调用")
    if not callable(clock) or not callable(sleeper):
        raise TypeError("clock/sleeper 必须可调用")
    deadline = clock() + timeout
    last = predicate()
    while not last and clock() < deadline:
        sleeper(interval)
        last = predicate()
    return last


# ────────────────────────── Win32 缝隙（用例里替换这些）──────────────────────────
#
# 每个"会碰真实系统"的动作都收在一个小函数里：测试用 monkeypatch 换掉它们，
# 就不需要真游戏，也不需要真的等 90 秒超时。

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
_user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.c_void_p]

_PW_RENDERFULLCONTENT = 0x00000002


class _BitmapInfoHeader(ctypes.Structure):
    """``BITMAPINFOHEADER``。"""

    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BitmapInfo(ctypes.Structure):
    """``BITMAPINFO``（只用得到头部，颜色槽留 3 个 DWORD 占位）。"""

    _fields_ = [("bmiHeader", _BitmapInfoHeader), ("bmiColors", wintypes.DWORD * 3)]


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _monotonic() -> float:
    return time.monotonic()


def _foreground_window() -> int:
    return int(_user32.GetForegroundWindow())


def _window_title(hwnd: int) -> str:
    length = _user32.GetWindowTextLengthW(wintypes.HWND(hwnd))
    buf = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(wintypes.HWND(hwnd), buf, length + 1)
    return buf.value


def _window_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(wintypes.HWND(hwnd), buf, 256)
    return buf.value


def _is_visible(hwnd: int) -> bool:
    return bool(_user32.IsWindowVisible(wintypes.HWND(hwnd)))


def _client_origin(hwnd: int) -> tuple[int, int]:
    """客户区左上角在屏幕上的坐标。**不能假定窗口在 (0,0)**。"""
    point = wintypes.POINT(0, 0)
    _user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(point))
    return (int(point.x), int(point.y))


def _set_cursor(x: int, y: int) -> None:
    _user32.SetCursorPos(int(x), int(y))


def _mouse_click() -> None:
    _user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
    _sleep(0.05)
    _user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP


def _enum_windows() -> list[int]:
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd: int, _param: int) -> bool:
        found.append(int(hwnd))
        return True

    _user32.EnumWindows(callback, 0)
    return found


def _grab(hwnd: int) -> Image.Image:
    """``PrintWindow(…, PW_RENDERFULLCONTENT)`` —— 实测能抓**被遮挡**的窗口（不是黑图）。

    这一点很关键：它让"截图找按钮"可以在后台做，不必把游戏抢到前台。
    """
    rect = wintypes.RECT()
    if not _user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        raise CaptureFailedError(f"GetClientRect 失败: hwnd={hwnd}")
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width <= 0 or height <= 0:
        raise CaptureFailedError(f"客户区尺寸非法: {width}x{height}（窗口最小化了？）")

    hdc = _user32.GetDC(wintypes.HWND(hwnd))
    mem = _gdi32.CreateCompatibleDC(hdc)
    bitmap = _gdi32.CreateCompatibleBitmap(hdc, width, height)
    try:
        _gdi32.SelectObject(mem, bitmap)
        if not _user32.PrintWindow(wintypes.HWND(hwnd), mem, _PW_RENDERFULLCONTENT):
            raise CaptureFailedError(f"PrintWindow 返回 0: hwnd={hwnd}")

        header = _BitmapInfo()
        header.bmiHeader.biSize = ctypes.sizeof(_BitmapInfoHeader)
        header.bmiHeader.biWidth = width
        header.bmiHeader.biHeight = -height  # 负数 = top-down，省一次翻转
        header.bmiHeader.biPlanes = 1
        header.bmiHeader.biBitCount = 32
        header.bmiHeader.biCompression = 0
        buffer = ctypes.create_string_buffer(width * height * 4)
        got = _gdi32.GetDIBits(mem, bitmap, 0, height, buffer, ctypes.byref(header), 0)
        if got != height:
            raise CaptureFailedError(f"GetDIBits 只拿到 {got}/{height} 行")
        # memoryview 而不是 buffer.raw：后者会把 8 MB 的位图再复制一份，
        # 而等待界面时一秒要抓一帧（最多上百帧），没必要制造这份垃圾。
        return Image.frombytes(
            "RGBA", (width, height), memoryview(buffer), "raw", "BGRA", 0, 1
        ).convert("RGB")
    finally:
        _gdi32.DeleteObject(bitmap)
        _gdi32.DeleteDC(mem)
        _user32.ReleaseDC(wintypes.HWND(hwnd), hdc)


def _process_pids(image_name: str = "victoria3.exe") -> list[int]:
    """当前同名进程的 PID 列表。``tasklist`` 跑不了时返回空列表（不假装知道）。"""
    try:
        done = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
            capture_output=True,
            check=False,
        )
    except OSError:  # pragma: no cover - 没有 tasklist 的极端环境
        return []
    return parse_tasklist_pids(done.stdout.decode("utf-8", errors="replace"))


# ────────────────────────── 窗口与前台 ──────────────────────────


def find_window(title: str = WINDOW_TITLE, window_class: str = WINDOW_CLASS) -> int:
    """按标题 + 类找可见的游戏窗口；找不到给 0。"""
    for hwnd in _enum_windows():
        if not _is_visible(hwnd):
            continue
        if title in _window_title(hwnd) and _window_class(hwnd) == window_class:
            return hwnd
    return 0


def _resolve(candidate: object, fallback: object, name: str) -> object:
    """取"调用方能注入的时钟/睡眠"：没给就用模块级默认。

    ⚠️ 必须是**调用时**解析，不能写成 ``def f(*, sleeper: object = _sleep)``：
    默认值在**函数定义时**就绑定了，之后 ``monkeypatch.setattr(ga, "_sleep", …)``
    对它**完全无效** —— 用例于是"以为打了补丁"，实际还在真等（本模块前四版都踩这个）。
    统一走这里之后，四种等待函数的睡眠缝口径一致。

    返回值仍是 ``object`` —— 形参保持 ``object`` 是有意的：用例需要能传
    ``wait_until(42, …)`` 这种"类型不对的调用"来验证运行期的 ``callable()`` 兜底
    （``test_game_auto.py`` 有两条断言钉住它）。所以类型信息在**调用点**补回来：
    ``tick_clock: Clock = cast("Clock", _resolve(…))`` —— 这里是我们唯一
    "把运行期已经校验过的东西告诉类型检查器"的地方。
    """
    chosen = fallback if candidate is None else candidate
    if not callable(chosen):
        raise TypeError(f"{name} 必须可调用")
    return chosen


def wait_for_window(
    *, timeout: float = WINDOW_TIMEOUT, clock: object = None, sleeper: object = None
) -> int:
    """等游戏窗口出现（官方流水线到标题菜单实测要 ~124 秒）。"""
    tick_clock: Clock = cast("Clock", _resolve(clock, _monotonic, "clock"))
    pause: Sleeper = cast("Sleeper", _resolve(sleeper, _sleep, "sleeper"))
    deadline = tick_clock() + timeout
    while tick_clock() < deadline:
        hwnd = find_window()
        if hwnd:
            return hwnd
        pause(POLL_INTERVAL)
    raise WindowNotFoundError(f"{timeout:.0f} 秒内没等到 {WINDOW_TITLE!r} 窗口")


def ensure_foreground(hwnd: int, *, attempts: int = 5) -> None:
    """把游戏抢到前台；抢不到就**报错**。

    ``SetForegroundWindow`` 会静默失败（Windows 前台锁定：调用进程自己不是前台进程时
    被拒），于是后续点击会送给**别的窗口** —— 而截图看起来毫无变化，
    极容易被误读成"坐标不对"。实测为此白跑一整轮。所以必须断言，不能只看返回值。
    """
    for _ in range(max(1, attempts)):
        if _foreground_window() == hwnd:
            return
        current = _foreground_window()
        me = ctypes.windll.kernel32.GetCurrentThreadId()
        others = {
            _user32.GetWindowThreadProcessId(wintypes.HWND(handle), None)
            for handle in (current, hwnd)
            if handle
        }
        attached: list[int] = []
        for tid in others:
            if tid and tid != me:
                _user32.AttachThreadInput(me, tid, True)
                attached.append(tid)
        try:
            _user32.ShowWindow(wintypes.HWND(hwnd), 9)  # SW_RESTORE
            _user32.BringWindowToTop(wintypes.HWND(hwnd))
            _user32.SetForegroundWindow(wintypes.HWND(hwnd))
            _user32.SetFocus(wintypes.HWND(hwnd))
        finally:
            for tid in attached:
                _user32.AttachThreadInput(me, tid, False)
        _sleep(0.4)

    front = _foreground_window()
    raise ForegroundLostError(
        f"抢不到前台（游戏 hwnd={hwnd}，当前前台={front}，标题={_window_title(front)!r}）"
        " —— 此时点击会送给别的窗口，已中止"
    )


def other_window(exclude: int) -> int:
    """找一个**能抢到前台**的非游戏窗口（用于验证后台是否继续模拟）。"""
    for hwnd in _enum_windows():
        if hwnd == exclude or not _is_visible(hwnd) or not _window_title(hwnd):
            continue
        if _window_class(hwnd) in {"Progman", "WorkerW", "Shell_TrayWnd"}:
            continue
        return hwnd
    return 0


# ────────────────────────── 抓图 / 匹配 / 点击 ──────────────────────────


def screenshot(hwnd: int) -> Image.Image:
    """抓一帧客户区画面，并顺带挡住"全黑"这种假成功。"""
    image = _grab(hwnd)
    if is_blank(image):
        raise CaptureFailedError(
            "抓到的是近乎纯色的画面（加载中 / 最小化 / PrintWindow 失效）—— 不敢据此判定"
        )
    return image


def save_shot(image: Image.Image, tag: str) -> Path:
    """把证据截图落盘（``tools/out/auto/``），返回路径。"""
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SHOT_DIR / f"{tag}.png"
    image.save(path)
    return path


def load_template(name: str, directory: Path | None = None) -> np.ndarray:
    """读按钮模板（``tools/probe/zz_probe_ab/ui/<name>.png``）。"""
    base = directory or UI_DIR
    path = base / f"{name}.png"
    if not path.is_file():
        raise TemplateNotFoundError(f"模板文件不存在：{path}")
    with Image.open(path) as handle:
        return np.array(handle.convert("RGB"))


def locate(
    image: Image.Image,
    name: str,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    scales: tuple[float, ...] = DEFAULT_SCALES,
    roi: tuple[float, float, float, float] | None = None,
    directory: Path | None = None,
) -> Match:
    """在画面里定位按钮模板；找不到抛 :class:`TemplateNotFoundError`。"""
    return find_template(
        np.array(image),
        load_template(name, directory),
        name=name,
        threshold=threshold,
        scales=scales,
        roi=roi,
    )


def locate_optional(
    image: Image.Image,
    name: str,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    scales: tuple[float, ...] = DEFAULT_SCALES,
    roi: tuple[float, float, float, float] | None = None,
    directory: Path | None = None,
) -> Match | None:
    """同 :func:`locate`，但"找不到"是正常结果（用于判定按钮**已消失**）。"""
    return match_template(
        np.array(image),
        load_template(name, directory),
        name=name,
        threshold=threshold,
        scales=scales,
        roi=roi,
    )


def click_client(hwnd: int, x: int, y: int, *, settle: float = 0.2, give_back: bool = True) -> None:
    """在客户区 ``(x, y)`` 处做一次**真前台左键点击**；点完把前台**还回去**。

    **鼠标注入走成熟库 `pydirectinput`**（`moveTo` + `click`），不再自己拼
    `SetCursorPos` + `mouse_event`：它内部用的也是 `SendInput`，但由库维护
    （含 `FAILSAFE` / `PAUSE` 这两个该由库管的开关），我们不再自己维护这段 Win32 细节。

    两条"别的路"的口径（都实测过，别重试）：

    * **合成键盘**（`keybd_event` / 虚拟键 `SendInput`）**实测无效** —— 用 tick 判据验过；
      换成 **scancode 版**（`pydirectinput`，源码里确实带 `KEYEVENTF_SCANCODE`）**也没能唤起
      控制台**（4 个候选键各试一次，判据是"控制台命令执行后会写的文件有没有变"）——
      但那次**不能区分**"键被忽略"与"这个界面本来就不让开控制台"，故记作**未证实**而不是判死，
      见 `tools/probe/console_key_test.py`；
    * **后台点击（不进系统输入队列）实测无效** —— 2026-09-21 三种变体各试一次：
      `PostMessage(WM_LBUTTONDOWN/UP)`、`SendMessage`、`SendMessage` + 先发
      `WM_ACTIVATE`/`WM_SETFOCUS`；判据不是"像素差"（大厅界面**自己在动**，3 秒不动
      两张截图也不同 —— 这个假阳性我踩过），而是**目标按钮还在不在**：三种变体点完
      「观察」按钮的匹配分数**一模一样**（0.855），界面没有切走。
      引擎读的是**原始输入状态**（光标位置 + 按键状态），不是窗口消息，这一条与用什么库无关。

    所以"点一次"这件事只能**借前台**。借了就要还：`give_back=True` 时点完立刻把
    原先的前台窗口设回去（用户看到的是约 1 秒的焦点闪动，而不是鼠标被夺走）。
    """
    previous = _foreground_window() if give_back else 0
    ensure_foreground(hwnd)
    try:
        origin_x, origin_y = _client_origin(hwnd)
        directinput.moveTo(origin_x + x, origin_y + y)
        _sleep(0.15)
        directinput.click()
        _sleep(settle)
    finally:
        if previous and previous != hwnd:
            _user32.SetForegroundWindow(wintypes.HWND(previous))


def click_match(hwnd: int, match: Match, *, give_back: bool = True) -> None:
    """点一个已经匹配好的位置。"""
    click_client(hwnd, match.x, match.y, give_back=give_back)


# ────────────────────────── 日志真值 ──────────────────────────


def tick_mark(log: Path | None = None) -> TickMark:
    """读最新 tick 与文件修改时间。读不到时 ``tick`` 为空串。"""
    path = log or TICK_LOG
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        mtime = path.stat().st_mtime
    except OSError:
        return TickMark(NO_TICK, 0.0)
    return TickMark(last_tick_in(text), mtime)


def is_running(seconds: float = 6.0, *, log: Path | None = None, sleeper: object = None) -> Advance:
    """时间在推进吗？**用逐 tick 行判定**（暂停不写日志，日志增长不能当判据）。

    ``sleeper`` 与 :func:`wait_until_running` / :func:`wait_for_lobby` 同口径，
    且**调用时解析**（见 :func:`_resolve`）—— 否则用例漏打一个补丁就要真等。
    """
    pause: Sleeper = cast("Sleeper", _resolve(sleeper, _sleep, "sleeper"))
    before = tick_mark(log)
    pause(seconds)
    after = tick_mark(log)
    return Advance(
        advanced=is_later(before.tick, after.tick),
        before=before.tick,
        after=after.tick,
        seconds=seconds,
        source="dedicated_server.log",
    )


def wait_until_readable(
    *,
    timeout: float = RUN_TIMEOUT,
    interval: float = POLL_INTERVAL,
    log: Path | None = None,
    clock: object = None,
    sleeper: object = None,
) -> TickMark:
    """等 tick **第一次可读**。超时抛 :class:`NotRunningError`。

    为什么必须有这个：会话刚起时 ``dedicated_server.log`` 里**一行 tick 都没有**
    （引擎要等到真的开始跑才写）。此时"推进"这件事**没有基线可比** ——
    实测就栽在这里：``unpause`` 取了基线 ``<读不到>``，而
    :func:`wait_until_running` 的推进条件要求基线可读，于是**时间明明在走**
    （引擎已推进到 1836.3.3.6）也永远判不出来，90 秒后误报"播放键没点中"。
    这是"判定把成功读成失败"，比漏判更危险：它会让人去修根本没坏的东西。
    """
    tick_clock: Clock = cast("Clock", _resolve(clock, _monotonic, "clock"))
    pause: Sleeper = cast("Sleeper", _resolve(sleeper, _sleep, "sleeper"))
    started = tick_clock()
    while tick_clock() - started < timeout:
        mark = tick_mark(log)
        if mark.readable:
            return mark
        pause(interval)
    raise NotRunningError(
        f"{timeout:.0f} 秒内 {log or TICK_LOG} 里始终读不到 tick —— "
        "游戏没跑起来，或日志路径不是这一个"
    )


def wait_until_running(
    before: TickMark | None = None,
    *,
    timeout: float = RUN_TIMEOUT,
    interval: float = POLL_INTERVAL,
    log: Path | None = None,
    clock: object = None,
    sleeper: object = None,
) -> Advance:
    """等到 tick 越过 ``before``（默认取当前值）。超时抛 :class:`NotRunningError`。

    ⚠️ ``before`` 读不到时本函数**必定超时**（没有基线就没有"越过"可言）。
    会话刚起、日志里还没有 tick 时请改用 :func:`wait_until_readable`。
    """
    tick_clock: Clock = cast("Clock", _resolve(clock, _monotonic, "clock"))
    pause: Sleeper = cast("Sleeper", _resolve(sleeper, _sleep, "sleeper"))
    start = before or tick_mark(log)
    started = tick_clock()
    while tick_clock() - started < timeout:
        now = tick_mark(log)
        if start.tick and is_later(start.tick, now.tick):
            return Advance(
                advanced=True,
                before=start.tick,
                after=now.tick,
                seconds=tick_clock() - started,
                source="dedicated_server.log",
            )
        pause(interval)
    now = tick_mark(log)
    raise NotRunningError(
        f"{timeout:.0f} 秒内 tick 没有越过 {start.tick or '<读不到>'}（现在 "
        f"{now.tick or '<读不到>'}）—— 播放键没点中，或游戏被暂停/卡住了"
    )


def probe_months(*, log: Path | None = None) -> list[str]:
    """探针收了多少个月（``ZZPROBE AB;ROLE;<TAG>`` 行）。"""
    path = log or DEBUG_LOG
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return probe_roles_in(text)


# ────────────────────────── 动作（推荐闭环的每一步）──────────────────────────


def assert_no_game_running() -> None:
    """起游戏前断言"0 个 victoria3 进程"——两个实例会互相抢前台与存档。"""
    pids = _process_pids()
    if pids:
        raise GameRunningError(
            f"已经有 victoria3 在跑（PID {pids}）—— 先关掉再起，否则两个实例会抢前台/存档"
        )


def launch(
    *,
    scripted_tests: bool = True,
    debug: bool = True,
    extra_args: tuple[str, ...] = (),
    wait: bool = True,
    timeout: float = WINDOW_TIMEOUT,
) -> int:
    """以调试模式起游戏（可选带官方自动化开关），返回窗口句柄。

    复用 :mod:`pdx.experiments` 的启动命令 —— 那是"怎么起游戏"的**唯一**出处
    （``content_load.json`` 决定启用哪些 mod，``-debug_mode`` 决定调试模式）。

    ⚠️ **已知缺口（未修，故意留白不如记下来）**：``wait=False`` 时返回 ``0``，
    而 ``0`` 同时是 :func:`find_window` 的"没找到"哨兵 —— 调用方分不清
    "没等窗口"与"没找到窗口"。正确修法是返回 ``int | None``（``None`` = 没等），
    但那会改掉公开返回类型并要同步改 ``tools/tests/test_game_auto.py`` 里两处
    ``== 0`` 断言，而该文件在本次收口时已移交他人独占，故**登记为缺口**而不是硬改。
    当前调用点（``run_until_running`` / CLI）都只用 ``wait=True``，不受影响。
    """
    assert_no_game_running()
    command = experiments.launch_command(debug=debug)
    if scripted_tests:
        command.append(SCRIPTED_TESTS_ARG)
    command.extend(extra_args)
    if not Path(command[0]).is_file():
        raise GameAutoError(f"找不到游戏可执行文件：{command[0]}")
    subprocess.Popen(command, cwd=str(config.ROOT), close_fds=True)
    if not wait:
        return 0
    return wait_for_window(timeout=timeout)


def wait_for_lobby(
    hwnd: int,
    *,
    timeout: float = LOBBY_TIMEOUT,
    threshold: float = DEFAULT_THRESHOLD,
    clock: object = None,
    sleeper: object = None,
) -> Match:
    """等"选择国家"界面出现（判据 = 底部「观察」按钮能被匹配到）。

    官方流水线实测从进程启动到 ``ingame-idler`` 要 ~137 秒，所以默认给 300 秒。
    """
    tick_clock: Clock = cast("Clock", _resolve(clock, _monotonic, "clock"))
    pause: Sleeper = cast("Sleeper", _resolve(sleeper, _sleep, "sleeper"))
    started = tick_clock()
    last_error = ""
    while tick_clock() - started < timeout:
        try:
            found = locate_optional(
                screenshot(hwnd), "btn_observe", threshold=threshold, roi=BOTTOM_ROI
            )
        except CaptureFailedError as exc:
            last_error = str(exc)
            found = None
        if found is not None:
            return found
        pause(POLL_INTERVAL)
    raise TemplateNotFoundError(
        f"{timeout:.0f} 秒内没在底部找到「观察」按钮（最后抓图错误："
        f"{last_error or '无'}）—— 游戏没走到选择国家界面，或界面语言/分辨率变了"
    )


def click_observer(
    hwnd: int,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    verify: bool = True,
    verify_timeout: float = 30.0,
) -> Match:
    """点「观察」进入观察者模式，并用**截图对比**确认按钮真的消失了。

    ⚠️ 不能用"日志有没有新行"验证：暂停时不写日志（实测）。验证只能靠截图。
    """
    before = screenshot(hwnd)
    match = locate(before, "btn_observe", threshold=threshold, roi=BOTTOM_ROI)
    save_shot(before, "01-lobby")
    click_match(hwnd, match)

    if verify:
        deadline = _monotonic() + verify_timeout
        while _monotonic() < deadline:
            _sleep(1.0)
            # 抓图失败要**容忍重试**，与 wait_for_lobby 同口径：切换界面时
            # 会短暂抓到近纯色（加载/黑屏），那是"还没画完"，不是"点击没生效"。
            try:
                after = screenshot(hwnd)
            except CaptureFailedError:
                continue
            if locate_optional(after, "btn_observe", threshold=threshold, roi=BOTTOM_ROI) is None:
                save_shot(after, "02-observer")
                return match
        raise TemplateNotFoundError(
            f"点了「观察」({match.describe()}) 但 {verify_timeout:.0f} 秒后按钮仍在 —— 点击没生效"
        )
    return match


def unpause(
    hwnd: int,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    settle: float = 3.0,
    timeout: float = RUN_TIMEOUT,
) -> Advance:
    """解除暂停，并**用逐 tick 日志确认时间真的开始推进**；没推进就报错。

    已经在跑时直接返回（幂等）—— 否则再点一次播放键反而会**暂停**它。

    基线可能**读不到**（会话刚起时日志里一行 tick 都没有），这时改判
    "从读不到变成读得到" —— 详见 :func:`wait_until_readable`。
    实机跑批正是栽在这一点上：点击明明生效（引擎自己写了
    ``Pause Toggled! Paused: false``），却被判成 90 秒超时。
    """
    before = tick_mark()
    probe = is_running(settle)
    if probe.advanced:
        return Advance(
            advanced=True,
            before=probe.before,
            after=probe.after,
            seconds=probe.seconds,
            source="dedicated_server.log（已经在跑，未点击）",
        )

    screen = screenshot(hwnd)
    match = locate(screen, "btn_play", threshold=threshold, roi=TOP_RIGHT_ROI)
    save_shot(screen, "03-paused")
    click_match(hwnd, match)

    if before.readable:
        advance = wait_until_running(before, timeout=timeout)
    else:
        after = wait_until_readable(timeout=timeout)
        advance = Advance(
            advanced=True,
            before=NO_TICK,
            after=after.tick,
            seconds=0.0,
            source="dedicated_server.log（基线读不到，改判首次可读）",
        )
    save_shot(screenshot(hwnd), "04-running")
    return advance


def background_ok(
    hwnd: int,
    *,
    seconds: float = 20.0,
    log: Path | None = None,
    restore: bool = True,
) -> Advance:
    """把前台让给别的窗口，验证**模拟是否继续**（实测：是）。

    意义：点火之后就不必让游戏一直占着前台 —— 轮询可以完全在后台做。
    """
    other = other_window(hwnd)
    if not other:
        raise GameAutoError("找不到可用的非游戏窗口来让出前台 —— 无法验证后台模拟")
    before = tick_mark(log)
    ensure_foreground(other)
    _sleep(2.0)
    if _foreground_window() == hwnd:  # pragma: no cover - 抢不走的极端情况
        raise ForegroundLostError("没能把前台让出去，后台结论不可信")
    _sleep(seconds)
    after = tick_mark(log)
    if restore:
        ensure_foreground(hwnd)
    return Advance(
        advanced=is_later(before.tick, after.tick),
        before=before.tick,
        after=after.tick,
        seconds=seconds,
        source=f"后台（前台让给 hwnd={other}）",
    )


def run_until_running(
    *,
    scripted_tests: bool = True,
    lobby_timeout: float = LOBBY_TIMEOUT,
    run_timeout: float = RUN_TIMEOUT,
) -> dict[str, object]:
    """推荐闭环：起游戏 → 等选择国家 → 点观察 → 解除暂停 → 确认在推进。

    返回值是一份可直接写进汇报的证据字典。
    **任何一步失败都抛异常，不返回半个结果** —— 半成品比失败更危险。
    """
    hwnd = launch(scripted_tests=scripted_tests, wait=True)
    lobby = wait_for_lobby(hwnd, timeout=lobby_timeout)
    observe = click_observer(hwnd)
    advance = unpause(hwnd, timeout=run_timeout)
    return {
        "hwnd": hwnd,
        "lobby_match": lobby.describe(),
        "observe_match": observe.describe(),
        "running": advance.describe(),
        "probe_month_lines": len(probe_months()),
        "tick": tick_mark().tick,
    }


def start_background_session(
    hwnd: int,
    *,
    speed_xy: tuple[int, int] | None = SPEED_V_XY,
    unpause_key: str = "space",
    threshold: float = DEFAULT_THRESHOLD,
    key_timeout: float = 8.0,
    run_timeout: float = RUN_TIMEOUT,
    background_seconds: float = 20.0,
) -> dict[str, object]:
    """**借一次前台，把开局做完，再把前台还回去**，之后游戏在后台自己跑。

    用户口径（2026-09-21）：允许切到前台，但要在一次里做完三件事、然后切回来：

    1. 点「观察」进观察者模式；
    2. 把速度切到档 V（默认坐标 `SPEED_V_XY`，客户区坐标）；
    3. 解除暂停 —— **先试空格**（`pydirectinput` 的扫描码版；老的合成虚拟键实测无效），
       用逐 tick 日志判它到底有没有生效；没生效就**回落到点播放键**（那条实测有效）；
    4. 把前台还给**原来那个窗口**；
    5. 用 `background_ok()` 证明"前台不是游戏时它仍在推进"。

    全程只在最外面借一次前台（三次点击各自 `give_back=False`），所以用户的焦点**只闪一下**，
    而不是闪三下。任何一步失败都抛异常，不返回半个结果。
    """
    previous = _foreground_window()
    before = tick_mark()
    advance: Advance
    used_key = False

    ensure_foreground(hwnd)
    try:
        screen = screenshot(hwnd)
        observe = locate(screen, "btn_observe", threshold=threshold)
        save_shot(screen, "10-lobby")
        click_match(hwnd, observe, give_back=False)

        if speed_xy is not None:
            click_client(hwnd, speed_xy[0], speed_xy[1], give_back=False)

        # ① 先试空格（扫描码），判据是逐 tick 日志 —— 不认就回落到播放键
        directinput.press(unpause_key)
        try:
            advance = (
                wait_until_running(before, timeout=key_timeout)
                if before.readable
                else wait_until_readable(timeout=key_timeout)  # type: ignore[assignment]
            )
            used_key = True
        except NotRunningError:
            playing = locate(screenshot(hwnd), "btn_play", threshold=threshold, roi=TOP_RIGHT_ROI)
            click_match(hwnd, playing, give_back=False)
            advance = (
                wait_until_running(before, timeout=run_timeout)
                if before.readable
                else wait_until_readable(timeout=run_timeout)  # type: ignore[assignment]
            )
    finally:
        if previous and previous != hwnd:
            _user32.SetForegroundWindow(wintypes.HWND(previous))

    background = background_ok(hwnd, seconds=background_seconds)
    return {
        "hwnd": hwnd,
        "unpause": "空格（扫描码）" if used_key else "播放键（空格没被接受）",
        "running": advance.describe(),
        "foreground_restored": previous if previous and previous != hwnd else "（本来就是游戏）",
        "background": background.describe(),
        "tick": tick_mark().tick,
    }


def status_report() -> list[str]:
    """只读地把"时间在不在走"这件事说清楚（不点任何东西）。"""
    mark = tick_mark()
    roles = probe_months()
    lines = [
        f"游戏窗口      : {find_window() or '（没找到）'}",
        f"最近 tick     : {mark.tick or '（读不到）'}   ← {TICK_LOG}",
        f"探针月度自报  : {len(roles)} 行（ZZPROBE AB;ROLE）",
    ]
    if roles:
        lines.append(f"              最后一个是 {roles[-1]}")
    lines.append(f"当前时间在走  : {is_running(4.0).describe()}")
    return lines


def main(argv: list[str] | None = None) -> int:
    """命令行入口：``python -m pdx.game_auto <命令>``。

    只做四件事：看状态、跑闭环、抓图（收模板用）、验后台。
    **任何一步失败都返回退出码 1**，不打印"完成"。
    """
    parser = argparse.ArgumentParser(
        prog="python -m pdx.game_auto",
        description="Victoria 3 自动化：截图 + 图像匹配 + 前进点击 + 日志真值",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="只读：报告 tick / 探针月度行 / 时间是否在推进")
    sub.add_parser("check", help="断言当前没有 victoria3 在跑")

    run_parser = sub.add_parser("run", help="完整闭环：起游戏→等选国家→点观察→解除暂停")
    run_parser.add_argument(
        "--no-scripted-tests", action="store_true", help="不带官方 -scripted_tests 开关"
    )
    run_parser.add_argument("--lobby-timeout", type=float, default=LOBBY_TIMEOUT)

    cap_parser = sub.add_parser("capture", help="抓游戏窗口到 PNG（收模板/留证据用）")
    cap_parser.add_argument("out", help="输出 PNG 路径")
    cap_parser.add_argument("--tag", default="manual", help="证据截图的名字前缀")

    bg_parser = sub.add_parser("background", help="把前台让出去，验证模拟是否继续")
    bg_parser.add_argument("--seconds", type=float, default=20.0)

    args = parser.parse_args(argv)
    command: str = args.command

    try:
        if command == "check":
            assert_no_game_running()
            print("0 个 victoria3 进程 —— 可以启动")
            return 0

        if command == "status":
            for line in status_report():
                print(line)
            return 0

        if command == "capture":
            hwnd = find_window()
            if not hwnd:
                raise WindowNotFoundError(f"没找到 {WINDOW_TITLE!r} 窗口")
            image = screenshot(hwnd)
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            image.save(out)
            save_shot(image, args.tag)
            print(f"已保存 {out}（{image.width}x{image.height}）")
            return 0

        if command == "background":
            hwnd = find_window()
            if not hwnd:
                raise WindowNotFoundError(f"没找到 {WINDOW_TITLE!r} 窗口")
            print(background_ok(hwnd, seconds=float(args.seconds)).describe())
            return 0

        # 只剩 "run"
        result = run_until_running(
            scripted_tests=not bool(args.no_scripted_tests),
            lobby_timeout=float(args.lobby_timeout),
        )
        print("闭环完成，证据：")
        for key, value in result.items():
            print(f"  {key:18s}: {value}")
        return 0

    except GameAutoError as exc:
        print(f"[失败] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - 入口
    raise SystemExit(main())


__all__ = [
    "BOTTOM_ROI",
    "DEFAULT_SCALES",
    "DEFAULT_THRESHOLD",
    "TOP_RIGHT_ROI",
    "UI_DIR",
    "Advance",
    "CaptureFailedError",
    "ForegroundLostError",
    "GameAutoError",
    "GameRunningError",
    "Match",
    "NotRunningError",
    "TemplateNotFoundError",
    "TickMark",
    "WindowNotFoundError",
    "assert_no_game_running",
    "background_ok",
    "click_client",
    "click_match",
    "click_observer",
    "ensure_foreground",
    "find_template",
    "find_window",
    "is_blank",
    "is_later",
    "is_running",
    "last_tick_in",
    "launch",
    "load_template",
    "locate",
    "locate_optional",
    "match_template",
    "other_window",
    "parse_tasklist_pids",
    "parse_tick_date",
    "probe_months",
    "probe_roles_in",
    "roi_box",
    "run_until_running",
    "screenshot",
    "tick_mark",
    "unpause",
    "wait_for_lobby",
    "wait_for_window",
    "wait_until",
    "wait_until_readable",
    "wait_until_running",
]
