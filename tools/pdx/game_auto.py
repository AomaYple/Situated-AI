"""Victoria 3 自动化：把一局"跑起来"（起游戏 → 观察 → 5 档速度 → 空格 → 切回后台）。

为什么需要这个模块
------------------
阶段判据要求「固定开局、同一套指令序列跑 A/B 两遍」—— 一局是分钟级到小时级，
靠人坐在电脑前点是不行的。而**官方流水线只差一击**：

    实测 ``binaries\\victoria3.exe -gdpr-compliant -debug_mode -scripted_tests``
    会自己生成开局、存初始档、读回、进到引擎日志里的 ``ingame-idler``
    （成绩单见 ``logs/custom_automated_stats.log`` 的 ``time-to-reach-ingame-idler``），
    然后**停在选择国家界面等人点**。

所以本模块承担的角色很窄：**点火**。点火之后跑与判定全部交回引擎
（``-scripted_tests`` 自己写 ``Documents\\…\\tests.txt`` 与 ``binaries\\*_GameTests_testoutput.xml``），
本模块只负责"读它写了什么"。判定绝不自己做 —— 那是假红/假绿的来源。

标准流程（用户口径 2026-09-22，**唯一一条路**）
----------------------------------------------
    起游戏（正常前台启动）
      → 加载期**完全不碰窗口**（只看进程与日志大小这类免费信号）
      → 确认游戏在前台，然后：点「观察」→ 点 5 档速度 → 按空格
      → 立刻把游戏切回后台（还原用户原来的前台窗口，再最小化游戏窗口）
      → 后台验证：时间真的在走吗、速率多少

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

⚠️ **空格是"暂停开关"，不是"开始"**：如果此时游戏**已经在跑**，按空格会把它**暂停**。
   所以 :func:`_step_unpause` 先量一次速率，已经在跑就**不按**。

设计口径：**不做回落链**（P14 的推论）
--------------------------------------
这个模块以前长着"不抢前台点一次 → 失败再借前台重做 → 再失败改点播放键"的回落阶梯。
实测（`docs/design/exec/自动化范式.md`）那套阶梯一次都没走完过，却让每次改动都要在
两条路之间反复对齐，还把"到底哪条路在生效"变得不可知。现在只剩一条路：
**任一步失败就抛错，把现场留给下一次修**（P13：失败要出声，不许静默降级）。

与假红有关的一条
----------------
``-scripted_tests`` 的 ``tests.txt`` 末尾会带一行 ``[ FAIL ] Error log: N errors``，
那是 harness 在数**整份** ``error.log``（原版自身就有几十条噪音）。
判定只许数"我们命名空间内的错误"，那行本身**不是**我们的失败。
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import cv2
import numpy as np
import pydirectinput as directinput
import pygetwindow as gw
import win32api
import win32con
import win32gui
import win32process
from PIL import Image, ImageGrab

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

# 抢前台的等待口径：**只等条件成立，不"睡一觉再说"**（用户口径：不要直接 sleep）。
# 窗口管理器处理激活是异步的，给它一个短窗口，成立就立刻往下走。
FOREGROUND_SETTLE = 0.5
FOREGROUND_POLL = 0.02

# 条件等待的轮询间隔（`wait_until`）与窗口显示/还原的等待上限。
CONDITION_POLL = 0.02
WINDOW_SHOW_SETTLE = 1.0

# 步骤之间的**最小停顿**：真实点击要过引擎那一帧才被读到，连着投三下会有一下落空。
# 判据仍然是"状态变化"（界面切走 / 速率上来），这个停顿只是给引擎一帧的时间。
STEP_SETTLE = 0.35

# 启动期"事件驱动"等待：不看像素，只看**便宜的进程/日志信号**（P2）。
#   ① 进程在不在（`tasklist`）；
#   ② 逐 tick 真值文件 `dedicated_server.log` 的**大小**多久没变。
# ⚠️ ② 是**启发式**、不是判据：暂停时这文件本来就不写（实测），所以"没变"只能当
#    "可以去看一眼了"，**真正的判据永远是界面本身**（借到前台之后的那次匹配）。
#: "安静"窗口。**实测值**：8 秒会假阳性（日志 0 字节、启动 8.7 秒就判忙完 ⇒ 提前借前台
#: 去点「观察」，按钮还没出现）；启动期引擎一直在写日志，20 秒的安静已经足够接近
#: "载入结束"，而多等的这 12 秒换掉一次白借前台。
BOOT_QUIET = 20.0
BOOT_POLL = 1.0

#: 启动期盯着看的日志（相对游戏日志目录）：逐 tick 真值 + 启动期一直在写的 debug 日志。
#: 为什么要两个：只盯逐 tick 文件时实测出现过**假阳性**（0 字节、8.7 秒就判"忙完"）。
BOOT_LOGS = ("dedicated_server.log", "debug.log")

#: 启动至少要过这么久（秒）才允许判"忙完"。**实测值**：官方流水线从进程启动到选国家
#: 界面约 137 秒；只靠"日志安静"会在 8.7 秒 / 20 秒两次假阳性（提前借前台 ⇒ 白占屏幕）。
BOOT_MIN_SECONDS = 120.0

#: 等到"忙完"之后，再等「观察」出现的上限（秒）。**必须短**：这段时间用户屏幕被游戏占着；
#: 前面已经用"完全不碰屏幕"的信号等过一轮，所以这里通常几秒内就命中。
LOOK_TIMEOUT = 45.0

# 找按钮时抓图的间隔**自适应**（P2「频率自己负责」）：第一次马上抓，
# 没找到就逐步放慢到上限，不在固定 2 秒上一直整屏抓。
CAPTURE_INTERVAL_START = 0.25
CAPTURE_INTERVAL_MAX = 2.0
CAPTURE_INTERVAL_GROWTH = 1.6

#: 点了「观察」之后，等界面切到地图的上限（判据是"按钮消失 / 时间开始走"，不是睡固定秒数）。
#: 点完「观察」之后等**世界载入**的上限（秒）。**实测教训**：原来给 30 秒，结果点完观察
#: 世界还在载入，8 秒的 tick 判定必然失败、回落去找播放键又撞上加载画面 ⇒ 整局误报失败。
#: 观实机截图（`tools/out/auto/10-lobby.png`）：那一刻大厅确实在，说明点击没错，错在**等太短**。
MAP_SETTLE_TIMEOUT = 120.0

#: 是否允许碰**真实**的窗口与输入。默认 **False**：只有显式入口（CLI / 探针脚本）才把它打开。
#:
#: 为什么必须有这一层：单测里**少打一个桩**，代码就会真的移动鼠标、真的点一下、真的把某个
#: 窗口提到最前。实测踩过（2026-09-21）：`TestClickGiveBack` 还在给 `_set_cursor` /
#: `_mouse_click` 打桩 —— 那两个函数早换成 `pydirectinput` 了 —— 于是三条用例各点了一次
#: **真实鼠标**，把用户正在用的 DeepSeek Harness 窗口挤到了后面。用户当场发现"没开游戏
#: 也会被切到后台"。有了这个开关，**忘了打桩只会当场报错，不会动用户的桌面**。
ALLOW_REAL_INPUT = False

#: `STARTUPINFO.wShowWindow` 的取值（来自 `winuser.h`）。
#: `SW_SHOWNOACTIVATE`（4）= 照常显示但**不激活**。
#:
#: ⚠️ **不要用 `SW_SHOWMINNOACTIVE`（7）启动**：实测（2026-09-21 21:57）最小化启动会让引擎在
#: 建渲染上下文时崩 —— 崩溃转储 `crashes\victoria3_three_01260821_215742\exception.txt`：
#: `Unhandled Exception C0000005 (EXCEPTION_ACCESS_VIOLATION)`，栈全在 `nvoglv64.dll`
#: （NVIDIA OpenGL 驱动）。那一次还让 `find_window()` 找不到窗口（它要求窗口可见），
#: 整条流程卡死。**启动这一步不加戏**：普通 `Popen` 最稳。
SW_SHOWNOACTIVATE = 4
#: `GetAncestor` 的取值：取顶层窗口。win32con 里也有（GA_ROOT）。
GA_ROOT = 2

#: 速度档 V 在**速度表盘模板**里的相对位置（模板 `ui/btn_speed.png` 的左下为原点）。
#:
#: 这个数不是拍的：模板是按客户区 `(1700,18)-(1858,86)` 裁的，而**实测能点中 V 档**的
#: 那一点是 `(1851,52)`（范式文档 §4.3），于是相对位置 = `(1851-1700)/158, (52-18)/68`
#: = `(0.956, 0.500)`。反算校验：模板在 1.0 尺度上匹配到 box=(1700,18,1858,86) 时，
#: 算出来的点**正好是 (1851,52)** —— 见 `tools/probe/calibrate_speed_template.py` 的输出。
#:
#: 为什么不直接写死 `(1851,52)`：那个点只在"这一台机器、这一种分辨率/UI 缩放/界面语言"
#: 下成立；而"表盘在哪"由模板匹配回答之后，V 档的位置就跟着走。实测把画面缩到 90% / 110%
#: 再匹配，分数仍有 0.969 / 0.970，算出的点也跟着平移。
SPEED_V_REL = (0.956, 0.500)

#: 兜底用的**硬编码坐标**（客户区，1920x1080 简体中文）。现在只有显式传
#: `speed_xy=SPEED_V_XY` 时才会走它 —— 默认路径是模板匹配（见 `speed_widget_xy`）。
#: ⚠️ 分辨率 / UI 缩放 / 界面语言一变就失效（backlog B34）。
SPEED_V_XY = (1851, 52)

#: 判定"速度确实切到 V 档"的**速率下限**（天/秒）。V 档按 §4.3 的实测是
#: 「50 秒推进 5 个月」≈ 3 天/秒；取 1.5 是留一半余量（机器快慢、前线加载都会影响）。
#: 低于它的常见原因：那一下点空了（实机踩过，只有 0.5 天/秒）。
SPEED_V_MIN_RATE = 1.5

#: 点了但速率不够时，在算出来的点周围试的**水平抖动**（像素）。命中偏差往往只有几像素，
#: 抖动一圈比"整段重来"便宜得多，也让这步**自纠**而不是自认失败。
SPEED_JITTER_PX = (0, -6, 6, -12, 12)


# ────────────────────────── 异常 ──────────────────────────
#
# P13：失败要出声。下面每一个都是"不确定就别继续"的产物 ——
# 尤其 TemplateNotFoundError 与 ForegroundLostError：这两种情况下点击会**静默落空**，
# 若吞掉异常，上层会拿到一个"跑完了但全是空的"结果而毫不知情。


class GameAutoError(RuntimeError):
    """本模块所有失败的基类。"""


class RealInputBlockedError(GameAutoError):
    """没显式授权就想碰真实窗口/输入 —— 直接拒绝，绝不动用户的桌面。"""


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

    切分走标准库 :mod:`csv`（不再手写 ``line.split('","')``）：手写版要求
    **每个字段都带引号**，于是 `"a.exe", "7", "Console"`（逗号后有空格）
    与 `a.exe,7,Console`（没加引号）这两种真实可能出现的形状都取不到 PID，
    而 csv（带 ``skipinitialspace``）能；同时字段里带逗号（``"2,345,678 K"``）
    两边都不会把它当分隔符。实测 9 种输入形状两边结果一致或 csv 更宽
    （见 ``test_game_auto`` 的用例）。
    """
    pids: list[int] = []
    reader = csv.reader(io.StringIO(text, newline=""), skipinitialspace=True)
    for row in reader:
        for cell in row:
            col = cell.strip()
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
    first_hit: bool = False,
) -> Match | None:
    """在 ``image`` 里找 ``template``，返回**最佳**匹配（低于阈值给 ``None``）。

    多尺度是必要的：``pdx_settings.json`` 的 ``GUI.scale`` 与分辨率都会等比改变
    按钮大小，而模板是某一台机器上量出来的。按**模板**缩放（而不是缩放截图），
    这样候选尺寸少、也不会把大图反复重采样。

    ``first_hit=True``：某个尺度一旦命中阈值就**立刻返回**，不试剩下的尺度 ——
    轮询"按钮在不在"只要一个可信命中就够，不必求跨尺度最优（P2：热路径少算，
    一次匹配从 6 档降到 1 档）。要"跨尺度最优"的判定/取证路径保持默认 ``False``，
    准确率优先（P5：提速不许动准确率，所以这是**显式开关**、不是偷偷改行为）。
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
        if first_hit and score >= threshold:
            return best

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
    first_hit: bool = False,
) -> Match:
    """:func:`match_template` 的"必须找到"版本 —— 找不到就报错（P13）。"""
    found = match_template(
        image, template, name=name, threshold=threshold, scales=scales, roi=roi, first_hit=first_hit
    )
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

# 窗口 / 输入**全部走成熟库**，不留手写的 ctypes 绑定（P3 + P4，用户口径：
# "不要使用其他代码例如 win32，完全使用 python"）：
#
#   pygetwindow   —— 枚举窗口、标题、激活（它内部自己处理 AttachThreadInput）、最小化/还原
#   pywin32       —— 补 pygetwindow 没暴露的几个**只读量**（客户区坐标 / 类名 / 图标化判断）
#   PIL.ImageGrab —— 截图（``bbox`` 直接只抓目标区域）
#   pydirectinput —— 真实输入（扫描码键盘 + ``SendInput`` 鼠标）
#
# ⚠️ **换了抓图方式，代价必须写在这**（P5：不拿准确率换速度）：
# 原先手写的 ``PrintWindow(PW_RENDERFULLCONTENT)`` 能抓**被遮挡**的窗口，即"后台截图判定"；
# ``ImageGrab`` 是**屏幕抓取**，被挡住的部分抓到的是**压在它上面的窗口** —— 拿这种像素
# 去判"按钮在不在"会得到**静默错误**的结论。所以：
#   ① 抓图前断言"这个窗口就是前台窗口"，不是就**报错**（P13，绝不用来源可疑的像素下判断）；
#   ② 等待界面的主判据改成**事件驱动**（便宜的进程/日志信号），不再按固定 2 秒轮询整屏。


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _input_allowed(force: bool) -> bool:
    """现在允许投真实输入吗？只有两个来源：**模块开关**或**调用点的显式授权**。

    为什么不做成"借用期内自动放行"那样更"方便"的东西：那会让"什么时候能碰真实输入"
    变成一个**时间窗口**而不是一个**决定** —— 窗口一开，窗口内所有代码都能动用户的桌面。
    现在的口径是：每一个会注入输入的调用点都必须自己说清楚（`force=True`），
    而唯一会说 `force=True` 的是 CLI / 探针这些**显式入口**（见 :func:`main`）。
    """
    return bool(ALLOW_REAL_INPUT or force)


def _monotonic() -> float:
    return time.monotonic()


def press_key(key: str, *, force: bool = False) -> None:
    """按一次**真实**键（扫描码，`pydirectinput`）—— 和点击共用同一道输入闸门。

    为什么要收成一个函数：`directinput.press` 直接调用会**绕过** :func:`_input_allowed`，
    于是"什么时候可以碰真实键盘"就漏了一个口子（测试里少打一个桩，用户就会看到
    自己正在打的字跑到游戏里）。收成一处，闸门才真的是闸门。
    """
    if not _input_allowed(force):
        raise RealInputBlockedError(
            "没有授权就投真实键盘输入：这会让用户正在打的字跑到游戏里。"
            "显式入口请打开 `ALLOW_REAL_INPUT` 或传 `force=True`。"
        )
    directinput.press(key)


def _window(hwnd: int) -> gw.Win32Window:
    """pygetwindow 的窗口对象（找不到会抛 ``PyGetWindowException``）。"""
    return gw.Win32Window(hwnd)


def _foreground_window() -> int:
    return int(win32gui.GetForegroundWindow())


def _window_title(hwnd: int) -> str:
    return str(win32gui.GetWindowText(hwnd))


def _window_class(hwnd: int) -> str:
    return str(win32gui.GetClassName(hwnd))


def _is_visible(hwnd: int) -> bool:
    return bool(win32gui.IsWindowVisible(hwnd))


def _is_iconic(hwnd: int) -> bool:
    """窗口是否处于最小化（图标）状态。"""
    return bool(win32gui.IsIconic(hwnd))


def _client_origin(hwnd: int) -> tuple[int, int]:
    """客户区左上角在屏幕上的坐标。**不能假定窗口在 (0,0)**。"""
    x, y = win32gui.ClientToScreen(hwnd, (0, 0))
    return (int(x), int(y))


def _client_size(hwnd: int) -> tuple[int, int]:
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    return (int(right - left), int(bottom - top))


def _set_foreground(hwnd: int) -> bool:
    """把 ``hwnd`` 提到前台，返回**是否真成了前台**。

    库调用不抛异常 **不等于** 成功了（Windows 前台锁定会静默失败），所以判据是
    ``GetForegroundWindow()``，不是返回值 —— 见 :func:`ensure_foreground`。
    """
    with suppress(gw.PyGetWindowException, OSError):
        _window(hwnd).activate()
    if _foreground_window() == hwnd:
        return True
    # 兜底：Windows 前台锁定会**静默拒绝**后台进程的置前请求（实测：前台一度是 0，
    # 于是 5 次重试全失败 ⇒ 整轮误报 ForegroundLostError）。pywin32 暴露了
    # AttachThreadInput，接上目标线程的输入队列再置前，成功率明显更高。
    try:
        target_tid, _pid = win32process.GetWindowThreadProcessId(hwnd)
        me = win32api.GetCurrentThreadId()
        attached = bool(target_tid) and bool(win32process.AttachThreadInput(me, target_tid, True))
        try:
            win32gui.SetWindowPos(
                hwnd,
                win32con.HWND_TOP,
                0,
                0,
                0,
                0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
            )
            win32gui.SetForegroundWindow(hwnd)
        finally:
            if attached:
                win32process.AttachThreadInput(me, target_tid, False)
    except Exception:
        return False
    return _foreground_window() == hwnd


def _restore(hwnd: int) -> None:
    _window(hwnd).restore()


def _minimize(hwnd: int) -> None:
    """把窗口缩下去（"切回后台"的最后一步）。

    `pygetwindow.minimize()` 就是 `ShowWindow(SW_MINIMIZE)`；不自己拼 Win32 调用。
    """
    _window(hwnd).minimize()


def _owns_pixels(hwnd: int, origin_x: int, origin_y: int, width: int, height: int) -> bool:
    """客户区那几个采样点上压着的窗口，是不是（属于）``hwnd``？

    这是 :func:`_grab` 的判据。为什么不用"必须前台"：**看一眼界面不需要焦点** —— 只要
    窗口露在最上面，`ImageGrab` 拿到的就是它的像素。用前台当判据会把"等待"逼进抢前台
    期间，实测后果是**用户黑屏几十秒**（载入画面全屏盖住桌面）。采四个角而不是一个点：
    窗口可能被别的小窗口压住一角。
    """
    inset_x = max(1, width // 10)
    inset_y = max(1, height // 10)
    points = (
        (origin_x + inset_x, origin_y + inset_y),
        (origin_x + width - inset_x, origin_y + inset_y),
        (origin_x + inset_x, origin_y + height - inset_y),
        (origin_x + width - inset_x, origin_y + height - inset_y),
    )
    for x, y in points:
        under = int(win32gui.WindowFromPoint((x, y)))
        if not under:
            return False
        if under == hwnd or int(win32gui.GetAncestor(under, GA_ROOT)) == hwnd:
            continue
        return False
    return True


def _set_cursor(x: int, y: int) -> None:
    directinput.moveTo(int(x), int(y))


def _mouse_click() -> None:
    directinput.click()


def _enum_windows() -> list[int]:
    return [int(window._hWnd) for window in gw.getAllWindows()]


def _grab(hwnd: int, roi: tuple[float, float, float, float] | None = None) -> Image.Image:
    """抓客户区画面；给了 ``roi``（分数矩形）就**只抓那一块**。

    两条断言都是"宁可报错，也不拿来源可疑的像素下判断"（P5 + P13）：

    * 客户区尺寸合法 —— 尺寸为 0 通常是窗口最小化了；
    * ``hwnd`` 必须**就是当前前台窗口** —— ``ImageGrab`` 抓的是屏幕，窗口被遮挡时
      抓到的是**压在上面的那个窗口**的像素，据此判"按钮在不在"会得到静默错误的结论。
      标准流程里三下点击期间游戏**就是**前台，所以这条断言在正常路径上不会被触发；
      它的作用是挡住"以为点完了、其实屏幕上是别的窗口"这种静默错误。

    只抓 ROI 的收益**是实测的，而且结论与直觉不一样**（`tools/probe/measure_capture_cost.py`，
    1920×1080 屏、20 轮）：**抓图成本由固定开销主导** —— 全屏 22.8 ms vs 1920×108 横条
    22.3 ms，只差 2.3%。真正省下来的是**匹配**时间：整屏 6 尺度 1146.5 ms → 底部条 +
    命中即停 15.3 ms（**75×**，见 `tools/tests/test_benchmarks.py::TestAutoCaptureBenchmarks`）。
    所以 ROI 与"命中即停"要一起用，别只留一半。
    """
    width, height = _client_size(hwnd)
    if width <= 0 or height <= 0:
        raise CaptureFailedError(f"客户区尺寸非法: {width}x{height}（窗口最小化了？）")
    front = _foreground_window()
    if front != hwnd:
        raise CaptureFailedError(
            f"抓图要求 hwnd={hwnd} **就是当前前台窗口**（现在前台是 {front}）—— "
            "ImageGrab 抓的是屏幕，拿被遮挡的像素判界面会得到静默错误的结论"
        )
    origin_x, origin_y = _client_origin(hwnd)
    left, top, right, bottom = roi or (0.0, 0.0, 1.0, 1.0)
    x0 = origin_x + int(left * width)
    y0 = origin_y + int(top * height)
    x1 = origin_x + max(int(right * width), int(left * width) + 1)
    y1 = origin_y + max(int(bottom * height), int(top * height) + 1)
    return ImageGrab.grab(bbox=(x0, y0, x1, y1), all_screens=True).convert("RGB")


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


def ensure_foreground(hwnd: int, *, attempts: int = 5, force: bool = False) -> None:
    """把游戏抢到前台；抢不到就**报错**。

    ``force=False`` 且 :data:`ALLOW_REAL_INPUT` 为假时**直接拒绝**（见
    :class:`RealInputBlockedError`）：把某个窗口提到最前会**把用户正在用的窗口挤到后面**，
    这件事不许"顺手"发生 —— 必须由显式入口（CLI / 探针）打开开关。

    ``Window.activate()``（pygetwindow，内部自己做 ``AttachThreadInput`` + 置顶 + 置前）
    会**静默失败** —— Windows 有前台锁定，调用进程自己不是前台进程时会被拒；
    于是后续点击送给**别的窗口**，而截图看起来毫无变化，极容易被误读成"坐标不对"
    （实测为此白跑一整轮）。所以判据是 ``GetForegroundWindow()``，不是库调用的返回值。
    """
    if _foreground_window() == hwnd:
        return
    if not ALLOW_REAL_INPUT and not force:
        raise RealInputBlockedError(
            "没有授权就抢前台：这会把用户正在用的窗口挤到后面。"
            "要走点击阶段就显式打开 —— CLI 用 `python -m pdx.game_auto run`，"
            "代码里传 `force=True`。"
        )
    if _is_iconic(hwnd):
        # **最小化的窗口激活不了**（实测：`background=True` 起游戏后第一次借前台直接
        # ForegroundLostError）。所以先把窗口还原成普通窗口，再谈置前 ——
        # 这一条也是"默认后台启动"必须配套的动作。
        _restore(hwnd)
        wait_until(
            lambda: not _is_iconic(hwnd), timeout=WINDOW_SHOW_SETTLE, interval=CONDITION_POLL
        )
    for _ in range(max(1, attempts)):
        # **不看库调用的返回值**：`activate()` 在 Windows 前台锁定下会静默失败，
        # 所以判据只有 `GetForegroundWindow()`。下面的条件等待就是这条判据。
        _set_foreground(hwnd)
        if wait_until(
            lambda: _foreground_window() == hwnd, timeout=FOREGROUND_SETTLE, interval=CONDITION_POLL
        ):
            return

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


def _is_alive(hwnd: int) -> bool:
    """句柄现在还有效吗（``IsWindow``）。

    为什么要单独判：Victoria 3 在启动过程中**销毁并重建窗口**，而窗口重建是**不固定时刻**的
    （实测：``launch`` 返回的 5178844 在 173 秒的加载跑完之后已失效）。
    光靠"按标题找窗口"不够 —— 窗口被最小化/隐藏时会找不到，于是调用方会退回一个死句柄。
    """
    return bool(hwnd) and bool(win32gui.IsWindow(hwnd))


def _live_window(hwnd: int) -> int:
    """取**当前**的游戏窗口句柄。

    为什么需要：Victoria 3 在启动过程中会**销毁并重建窗口**（实测：launch 返回的
    1901988 在激活时已失效，当前窗口是 198050）。拿过期句柄去激活只会得到
    ``ForegroundLostError``，而那个报错看起来像抢不到前台，把人引向错误的方向。

    ⚠️ **找不到时抛错，不静默退回传入的句柄**（2026-09-22 实测踩到）：
    旧实现是 ``find_window() or hwnd`` —— 句柄已经死了也照样返回它，
    于是下一步在 ``GetClientRect`` 上抛 ``error 1400 无效的窗口句柄``。
    那个报错**指向完全错误的方向**（看起来像坐标/尺寸问题，实际是句柄过期），
    与本函数文档里批评 ``ForegroundLostError`` 的毛病一模一样。
    """
    if _is_alive(hwnd):
        return hwnd
    current = find_window()
    if current:
        if current != hwnd:
            _REBUILDS.append((hwnd, current))
        return current
    raise WindowNotFoundError(
        f"游戏窗口句柄 {hwnd} 已失效，且按标题+类（{WINDOW_TITLE!r}/{WINDOW_CLASS!r}）"
        "找不到新的可见窗口 —— 窗口可能刚被重建、或已被最小化/关闭。"
        "（窗口重建是启动期的正常现象，所以这里报「句柄过期」而不是「抢不到前台」。）"
    )


#: 实测发生过的"窗口被重建"记录：``(旧句柄, 新句柄)``。测试与探针可据此判断
#: 本次运行到底有没有遇到重建（不猜，有据）。
_REBUILDS: list[tuple[int, int]] = []


def screenshot(hwnd: int, roi: tuple[float, float, float, float] | None = None) -> Image.Image:
    """抓一帧客户区画面（给了 ``roi`` 就**只抓那一块**），并挡住"近乎纯色"这种假成功。"""
    image = _grab(hwnd, roi)
    if is_blank(image):
        raise CaptureFailedError(
            "抓到的是近乎纯色的画面（加载中 / 最小化 / 抓图失效）—— 不敢据此判定"
        )
    return image


def _roi_offset(hwnd: int, roi: tuple[float, float, float, float]) -> tuple[int, int]:
    """ROI 裁剪图左上角在**客户区**里的偏移。

    为什么必须有它：抓图改成"只抓 ROI"之后，匹配出来的坐标是**裁剪图内**的相对坐标。
    实测踩过这个坑（2026-09-21 实机）：`btn_observe` 匹配到 `(864, 83)`（裁剪图内），
    直接拿去点击 ⇒ 打在屏幕顶部，而按钮其实在底部 `y≈1053`，于是"点了没反应"。
    """
    width, height = _client_size(hwnd)
    left, top, _right, _bottom = roi
    return (int(left * width), int(top * height))


def _shift_match(match: Match, dx: int, dy: int) -> Match:
    """把裁剪图内的匹配坐标平移回客户区坐标（`box` 一起平移，避免"改了 x 忘了 box"）。"""
    x0, y0, x1, y1 = match.box
    return replace(
        match,
        x=match.x + dx,
        y=match.y + dy,
        box=(x0 + dx, y0 + dy, x1 + dx, y1 + dy),
    )


def find_in_roi(
    hwnd: int,
    name: str,
    *,
    roi: tuple[float, float, float, float],
    threshold: float = DEFAULT_THRESHOLD,
) -> Match | None:
    """只在 ``roi`` 里找模板：**只抓那一块**再匹配（P2：热路径只读需要的像素）。

    收益量级见 :func:`_grab`：抓图省 2.3%，匹配省 75×（1146.5 ms → 15.3 ms）。

    抓图失败（不是前台 / 最小化）按"没找到"返回 ``None``；要区分"看不到"与"没有"的
    调用方请直接用 :func:`screenshot`，让它出声（P13）。
    """
    try:
        image = screenshot(hwnd, roi=roi)
    except CaptureFailedError:
        return None
    found = locate_optional(image, name, threshold=threshold, first_hit=True)
    if found is None:
        return None
    dx, dy = _roi_offset(hwnd, roi)
    return _shift_match(found, dx, dy)


def save_shot(image: Image.Image, tag: str) -> Path:
    """把证据截图落盘（``tools/out/auto/``），返回路径。"""
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SHOT_DIR / f"{tag}.png"
    image.save(path)
    return path


#: 模板进程内缓存：等待界面时一秒可能匹配好几帧，每次都 `open` + 解码纯属浪费
#: （P2「热路径只读预存值」）。缓存的是**只读**数组 —— 调用方不要就地改它。
_TEMPLATE_CACHE: dict[tuple[str, str], np.ndarray] = {}


def clear_template_cache() -> None:
    """清空模板缓存（探针换模板、用例改临时目录时用）。"""
    _TEMPLATE_CACHE.clear()


def load_template(name: str, directory: Path | None = None) -> np.ndarray:
    """读按钮模板（``tools/probe/zz_probe_ab/ui/<name>.png``）；**同一份只读一次盘**。"""
    base = directory or UI_DIR
    path = base / f"{name}.png"
    key = (str(base), name)
    cached = _TEMPLATE_CACHE.get(key)
    if cached is not None:
        return cached
    if not path.is_file():
        raise TemplateNotFoundError(f"模板文件不存在：{path}")
    with Image.open(path) as handle:
        array = np.array(handle.convert("RGB"))
    _TEMPLATE_CACHE[key] = array
    return array


def locate(
    image: Image.Image,
    name: str,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    scales: tuple[float, ...] = DEFAULT_SCALES,
    roi: tuple[float, float, float, float] | None = None,
    directory: Path | None = None,
    first_hit: bool = False,
) -> Match:
    """在画面里定位按钮模板；找不到抛 :class:`TemplateNotFoundError`。"""
    return find_template(
        np.array(image),
        load_template(name, directory),
        name=name,
        threshold=threshold,
        scales=scales,
        roi=roi,
        first_hit=first_hit,
    )


def locate_optional(
    image: Image.Image,
    name: str,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    scales: tuple[float, ...] = DEFAULT_SCALES,
    roi: tuple[float, float, float, float] | None = None,
    directory: Path | None = None,
    first_hit: bool = False,
) -> Match | None:
    """同 :func:`locate`，但"找不到"是正常结果（用于判定按钮**已消失**）。"""
    return match_template(
        np.array(image),
        load_template(name, directory),
        name=name,
        threshold=threshold,
        scales=scales,
        roi=roi,
        first_hit=first_hit,
    )


def click_client(hwnd: int, x: int, y: int, *, settle: float = 0.0, force: bool = False) -> None:
    """在客户区 ``(x, y)`` 处做一次**真前台左键点击**。

    **鼠标注入走成熟库 `pydirectinput`**（`moveTo` + `click`），不再自己拼
    `SetCursorPos` + `mouse_event`：它内部用的也是 `SendInput`，但由库维护
    （含 `FAILSAFE` / `PAUSE` 这两个该由库管的开关），我们不再自己维护这段 Win32 细节。

    两条"别的路"的口径（都实测过，别重试）：

    * **合成键盘**（`keybd_event` / 虚拟键 `SendInput`）**实测无效** —— 用 tick 判据验过；
      换成 **scancode 版**（`pydirectinput`，源码里确实带 `KEYEVENTF_SCANCODE`）**也没能唤起
      控制台**（4 个候选键各试一次，判据是"控制台命令执行后会写的文件有没有变"）——
      但那次**不能区分**"键被忽略"与"这个界面本来就不让开控制台"，故记作**未证实**而不是判死；
    * **后台点击（不进系统输入队列）实测无效** —— 2026-09-21 三种变体各试一次：
      `PostMessage(WM_LBUTTONDOWN/UP)`、`SendMessage`、`SendMessage` + 先发
      `WM_ACTIVATE`/`WM_SETFOCUS`；判据不是"像素差"（大厅界面**自己在动**，3 秒不动
      两张截图也不同 —— 这个假阳性我踩过），而是**目标按钮还在不在**：三种变体点完
      「观察」按钮的匹配分数**一模一样**（0.855），界面没有切走。
      引擎读的是**原始输入状态**（光标位置 + 按键状态），不是窗口消息，这一条与用什么库无关。

    所以"点一次"这件事只能**真前台**。标准流程里游戏从启动到三下点完一直是前台，
    因此不再有"点完把前台还回去"这个动作 —— **还前台统一在流程末尾做一次**
    （:func:`switch_to_background`），而不是每点一下闪一次。
    """
    if not _input_allowed(force):
        raise RealInputBlockedError(
            "没有授权就投真实鼠标输入：这会让用户的鼠标自己动起来。"
            "显式入口（CLI / 探针）请打开 `ALLOW_REAL_INPUT` 或传 `force=True`。"
        )
    ensure_foreground(hwnd, force=force)
    origin_x, origin_y = _client_origin(hwnd)
    directinput.moveTo(origin_x + x, origin_y + y)
    _wait_cursor_at(origin_x + x, origin_y + y)
    directinput.click()
    if settle:
        _sleep(settle)


def _wait_cursor_at(x: int, y: int, *, timeout: float = 1.0) -> bool:
    """等光标真的到达 ``(x, y)`` —— **不要用固定 sleep 等输入生效**。

    返回是否到达（超时返回 False，调用方自己决定要不要报错）。用条件等待的理由：
    `mouse_event` 把移动投进系统输入队列，落到哪儿是**可观测**的（`position()`），
    而"睡 0.15 秒"既不能保证到了、又固定拖慢每一次点击。
    """
    started = _monotonic()
    while _monotonic() - started < timeout:
        if directinput.position() == (x, y):
            return True
        _sleep(0.01)
    return False


def click_match(hwnd: int, match: Match, *, force: bool = False) -> None:
    """点一个已经匹配好的位置（坐标已经在**客户区**坐标系里）。"""
    click_client(hwnd, match.x, match.y, force=force)


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

    **启动方式就用之前那套探针/测试的那一套**（用户口径："直接用之前那套测试的怎么启动
    就怎么启动"）：``experiments.launch_command()`` + ``-scripted_tests`` + 普通
    ``Popen``，**不碰任何窗口样式**。为什么把自创的变体全部删掉 —— 都实测过：

    * ``SW_SHOWMINNOACTIVE``（创建时就最小化）：游戏**当场崩** ——
      ``crashes\\victoria3_01260821_215742\\exception.txt`` 是
      ``Unhandled Exception C0000005 (EXCEPTION_ACCESS_VIOLATION)``，栈在
      ``nvoglv64.dll``（NVIDIA OpenGL 在 0 尺寸窗口上初始化失败）；
    * ``SW_SHOWNOACTIVATE``（显示但不激活）：窗口照常铺满屏幕盖在最上面，
      用户当场指出"发现还是直接前台启动了"；
    * "窗口出现后再最小化"：能缩下去（实测安全），但用户看到的是"游戏一闪就没了"，
      也不是他要的。

    ⇒ 结论：**启动这一步不加戏**，普通启动最稳、窗口正常出现。"不打扰用户"由后面的
    两步保证：**加载期完全不碰窗口**（:func:`wait_for_boot_settle`：只看进程与日志大小），
    **三下点完之后立刻切回后台**（:func:`switch_to_background`：还前台 + 缩窗口）。

    ⚠️ **已知缺口（未修，故意留白不如记下来）**：``wait=False`` 时返回 ``0``，
    而 ``0`` 同时是 :func:`find_window` 的"没找到"哨兵 —— 调用方分不清
    "没等窗口"与"没找到窗口"。正确修法是返回 ``int | None``（``None`` = 没等），
    但那会改掉公开返回类型并要同步改 ``tools/tests/test_game_auto.py`` 里两处
    ``== 0`` 断言。当前调用点都用 ``wait=True``，不受影响。
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


@dataclass(frozen=True)
class BootSettle:
    """启动期"便宜信号"的观测结果。

    ⚠️ 它是**启发式**，不是界面判据：界面判据永远是"回到前台之后那一次匹配"。
    """

    settled: bool
    waited: float
    log_bytes: int
    quiet_seconds: float
    processes: int
    why: str


def _log_size(path: Path) -> int:
    """逐 tick 真值文件的字节数；读不到给 ``-1``（**不假装是 0**）。"""
    try:
        return path.stat().st_size
    except OSError:
        return -1


def wait_for_boot_settle(
    *,
    timeout: float = LOBBY_TIMEOUT,
    quiet: float = BOOT_QUIET,
    interval: float = BOOT_POLL,
    minimum: float = BOOT_MIN_SECONDS,
    log: Path | None = None,
    clock: object = None,
    sleeper: object = None,
) -> BootSettle:
    """等"启动期忙完了"：**进程在** + **启动日志真的在写、然后连续 ``quiet`` 秒没再变**。

    为什么不看像素：抓图只能抓**前台**窗口，而起游戏不许占用户的前台（拿被遮挡的像素
    判界面会得出静默错误的结论，P5）。而日志 ``size`` 是**免费**的（一次 ``stat``）——
    这就是 P2 的"事件驱动 + 频率自己负责"：等待期不烧 CPU、不抓整屏、不猜。

    ⚠️ **实测踩过（2026-09-21）**：只看"逐 tick 文件没变"会**假阳性** —— 那次
    ``dedicated_server.log = 0 字节``、启动才 8.7 秒就判"忙完"，于是提前借前台去点
    「观察」，按钮当然还没出现（`TemplateNotFoundError`）。所以现在必须先看到
    **至少一次 size 变化**（证明引擎真的在写日志、在推进启动），再谈"安静"。
    看的是两个文件：逐 tick 的 ``dedicated_server.log`` 与启动期一直在写的 ``debug.log``。

    ⚠️ 另一条已知边界（实测）：暂停时逐 tick 文件**本来就不写**，所以"安静"**不能**证明
    "界面已经到选择国家"；它只说明"可以去看一眼了"。真正的判据是借到前台之后那一次匹配。
    """
    tick_clock: Clock = cast("Clock", _resolve(clock, _monotonic, "clock"))
    pause: Sleeper = cast("Sleeper", _resolve(sleeper, _sleep, "sleeper"))
    paths = (log,) if log is not None else tuple(TICK_LOG.parent / name for name in BOOT_LOGS)
    started = tick_clock()
    sizes = tuple(_log_size(item) for item in paths)
    last_change = started
    progressed = False
    processes = 0
    while tick_clock() - started < timeout:
        processes = len(_process_pids())
        now_sizes = tuple(_log_size(item) for item in paths)
        now = tick_clock()
        if now_sizes != sizes:
            sizes = now_sizes
            last_change = now
            progressed = True
        quiet_for = now - last_change
        if now - started >= minimum and processes and progressed and quiet_for >= quiet:
            detail = "、".join(
                f"{item.name}={size}" for item, size in zip(paths, now_sizes, strict=True)
            )
            return BootSettle(
                True,
                now - started,
                max(now_sizes),
                quiet_for,
                processes,
                f"进程 {processes} 个；{detail}；已连续 {quiet_for:.1f} 秒没变",
            )
        pause(interval)
    quiet_for = tick_clock() - last_change
    last_size = max(sizes)
    detail = "、".join(f"{item.name}={size}" for item, size in zip(paths, sizes, strict=True))
    return BootSettle(
        False,
        tick_clock() - started,
        last_size,
        quiet_for,
        processes,
        f"超时：进程 {processes} 个；{detail}；最后安静 {quiet_for:.1f} 秒"
        + ("（**没看到日志推进过** ⇒ 引擎可能还没开始写）" if not progressed else ""),
    )


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


def tick_day(tick: str) -> float | None:
    """把 ``1836.1.12.12`` 折成"第几天"（够算速率就行，不做精确日历）。读不到返回 ``None``。"""
    parts = tick.split(".")
    if len(parts) < 3:
        return None
    try:
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None
    return (year - 1836) * 365.25 + (month - 1) * 30.44 + (day - 1)


def measure_rate(seconds: float = 8.0) -> float:
    """量"游戏时间推进得多快"，单位**天/秒**（读不到 tick 时返回 ``0.0``）。

    为什么要它：速度档点没点中，**只能靠速率证明**。实机踩过一次 —— 点了一下 V 档坐标，
    界面看不出异常，速率却只有 0.5 天/秒（V 档按 §4.3 实测 ≈3 天/秒），也就是那一下点空了
    却毫无提示。所以"切速度"必须带上这个判据，并把测出来的速率写进返回值。
    """
    start = tick_mark()
    if not start.readable:
        return 0.0
    start_day = tick_day(start.tick)
    if start_day is None:
        return 0.0
    _sleep(seconds)
    end_day = tick_day(tick_mark().tick)
    if end_day is None or seconds <= 0:
        return 0.0
    return round((end_day - start_day) / seconds, 3)


def speed_widget_xy(hwnd: int, *, threshold: float = DEFAULT_THRESHOLD) -> tuple[int, int] | None:
    """速度表盘 V 档的位置：**能模板匹配就用模板，匹配不上返回 ``None``**（由调用方回落）。

    ⚠️ **为什么这里必须允许失败**：表盘会跟着「运行 / 暂停」「当前是哪一档」变色 ——
    2026-09-21 实测：暂停态收的模板拿去匹配运行态，分数只有 **0.327**；连中央那枚
    看起来像纯装饰的齿轮，跨状态也只有 **0.551**（它会随整体亮度变）。所以**没有**一个
    "整块表盘"的模板能同时覆盖两种状态，模板只能当**首选**，不能当唯一依据。

    返回的是**客户区坐标**；找不到时给 ``None``，绝不让调用方拿到一个乱猜的点。

    抓图失败（窗口最小化 / 界面还没画出来）也算"定位不到" —— 调用方会用**速率兜底**，
    所以这里吞掉它不会造成假成功；反过来，让一个抓图异常把整局带崩才是真问题。
    """
    try:
        match = locate(screenshot(hwnd), "btn_speed", threshold=threshold, roi=TOP_RIGHT_ROI)
    except (TemplateNotFoundError, CaptureFailedError, OSError):
        return None
    width = match.box[2] - match.box[0]
    height = match.box[3] - match.box[1]
    return (
        round(match.box[0] + SPEED_V_REL[0] * width),
        round(match.box[1] + SPEED_V_REL[1] * height),
    )


def speed_candidates(
    hwnd: int, *, speed_xy: tuple[int, int] | None, threshold: float
) -> list[tuple[str, tuple[int, int]]]:
    """把"该往哪儿点"排成一个**候选序列**：先模板（匹配得上时）、再实测坐标、再小幅抖动。

    这就是这一步的收敛做法 —— **不赌某一个点**，而是"点一个 → 量速率 → 不够就换下一个"，
    最多试 `SPEED_JITTER_PX` 那么多个位置，最后把**真实速率**如实报出来。
    """
    out: list[tuple[str, tuple[int, int]]] = []
    if speed_xy is not None:
        out.append((f"显式坐标 {speed_xy}", speed_xy))
        out.extend(
            (f"显式坐标 {j:+d}px", (speed_xy[0] + j, speed_xy[1])) for j in SPEED_JITTER_PX if j
        )
        return out

    found = speed_widget_xy(hwnd, threshold=threshold)
    if found is not None:
        out.append((f"模板匹配 {found}", found))
    out.extend(
        (f"实测坐标 {SPEED_V_XY[0] + j},{SPEED_V_XY[1]}", (SPEED_V_XY[0] + j, SPEED_V_XY[1]))
        for j in SPEED_JITTER_PX
    )
    return out


# ────────────────────────── 会话流程：起游戏 → 三下点击 → 切回后台 ──────────────────────────


@dataclass(frozen=True, slots=True)
class ForegroundHandover:
    """一次"游戏 → 后台"的交接账。

    ``previous`` 是**起游戏之前**的前台窗口 —— 那才是真正"用户的窗口"。
    为什么不在交接时现取一次前台：游戏加载结束时**会自己抢前台**（B50 实测），
    交接那一刻取到的其实是游戏自己，拿它去"还原"等于什么都没做。
    """

    previous: int
    after: int
    restored: bool
    minimized: bool
    seconds: float

    def describe(self) -> str:
        where = "已最小化" if self.minimized else "仍显示（没有可还原的窗口）"
        return (
            f"前台 {self.previous} → {self.after}（还原{'成功' if self.restored else '未做'}，"
            f"{where}，耗时 {self.seconds:.1f}s）"
        )


@dataclass(frozen=True, slots=True)
class SessionStart:
    """一局的"点火"结果 —— 每一步都带够证据，可以直接写进汇报。

    字段名与含义（不要为了好看改名）：``hwnd`` 是**当前**句柄（启动期窗口会被重建）；
    ``unpause`` 说明那一按到底按没按；``rate`` 是**量出来的**速率，不是设出来的。
    """

    hwnd: int
    previous: int
    settle: BootSettle
    observe: Match
    speed_source: str
    speed_xy: tuple[int, int] | None
    unpause: str
    pressed: bool
    advance: Advance | None
    rate: float
    rate_ok: bool
    attempts: int
    handover: ForegroundHandover
    tick: str

    def as_dict(self) -> dict[str, object]:
        """扁平化（CLI 打印 / 探针记档用）。"""
        return {
            "hwnd": self.hwnd,
            "previous": self.previous,
            "boot_settle": self.settle.why,
            "observe": self.observe.describe(),
            "speed_source": self.speed_source,
            "speed_xy": "" if self.speed_xy is None else f"{self.speed_xy[0]},{self.speed_xy[1]}",
            "speed_attempts": self.attempts,
            "speed_days_per_second": self.rate,
            "speed_ok": self.rate_ok,
            "unpause": self.unpause,
            "unpause_pressed": self.pressed,
            "running": self.advance.describe() if self.advance else "（按空格前时间就已经在走）",
            "handover": self.handover.describe(),
            "foreground_restored": self.handover.restored,
            "minimized": self.handover.minimized,
            "tick": self.tick,
        }


def launch_to_foreground(
    *,
    scripted_tests: bool = True,
    debug: bool = True,
    timeout: float = WINDOW_TIMEOUT,
    extra_args: tuple[str, ...] = (),
) -> tuple[int, int]:
    """起游戏并等窗口出现，返回 ``(当前句柄, 起游戏之前的前台窗口)``。

    **启动这一步不加戏**（用户口径："直接启动游戏到前台"）：普通 ``Popen``，窗口正常出现。
    自创的启动变体都删掉了，各自的原因写在 :data:`SW_SHOWNOACTIVATE` 的注释里
    （最小化启动会让引擎在 `nvoglv64.dll` 里崩）。

    第二个返回值是**给收尾用的**：加载结束时游戏会自己抢前台，「切回后台」要还的是
    **用户原来的窗口**，不是"此刻的前台"。
    """
    previous = _foreground_window()
    hwnd = launch(
        scripted_tests=scripted_tests,
        debug=debug,
        extra_args=extra_args,
        wait=True,
        timeout=timeout,
    )
    return _live_window(hwnd), previous


def _route_to_foreground(hwnd: int, previous: int, *, force: bool) -> int:
    """确保游戏在前台（先刷新句柄），返回**当前**句柄。

    为什么必须先刷新：加载要 170+ 秒，而 ``launch()`` 2 秒时就返回了句柄，中间窗口会被
    **销毁重建**（实测：5178844 → 另一个句柄），拿死句柄去激活只会得到
    ``ForegroundLostError`` / ``error 1400``，两个报错都指向错误的方向。
    """
    hwnd = _live_window(hwnd)
    if _foreground_window() != hwnd:
        if previous and _is_alive(previous):
            # 有"用户的窗口"可以归还：先把它还给用户，再明确地把游戏提到前台。
            # 为什么多此一举：Windows 的前台锁定会**静默拒绝**非前台进程的置前请求；
            # 先把前台还给原来那个窗口，我们这条置前请求的成功率明显更高（实测）。
            _set_foreground(previous)
        ensure_foreground(hwnd, force=force)
    return hwnd


def switch_to_background(
    hwnd: int,
    previous: int,
    *,
    restore: bool = True,
    minimize: bool = True,
    settle: float = 1.0,
) -> ForegroundHandover:
    """**切回后台**：把前台还给用户原来的窗口，再把游戏窗口缩下去。

    两步都要，因为两步管的是不同的事：

    * **还前台**：焦点与键盘归用户。这是用户口径里"再切回后台"的字面要求；
    * **缩窗口**：游戏窗口不再占着屏幕。⚠️ 实测过"缩下去会不会不推进"是**必须验**的一条
      （有些游戏一缩下去就不渲染），所以调用方要在缩完之后**量一次速率**
      （:func:`start_session` 的 ``verify_minimized``），验不过就当场恢复。

    找不到可还原的窗口（``previous`` 为 0 或已经关掉）时**如实报** ``restored=False``，
    不假装还成功了。
    """
    started = _monotonic()
    restored = False
    if restore and previous and previous != hwnd and _is_alive(previous):
        restored = _set_foreground(previous)
    if minimize and not _is_iconic(hwnd):
        _minimize(hwnd)
        wait_until(lambda: _is_iconic(hwnd), timeout=WINDOW_SHOW_SETTLE, interval=CONDITION_POLL)
    if settle:
        _sleep(settle)
    return ForegroundHandover(
        previous=previous,
        after=_foreground_window(),
        restored=restored,
        minimized=_is_iconic(hwnd),
        seconds=_monotonic() - started,
    )


def _ensure_live_foreground(hwnd: int) -> int:
    """等到"窗口活着且是前台"（最长 :data:`LOOK_TIMEOUT` 秒），返回当前句柄。

    ⚠️ 抓图用的是屏幕抓取（``ImageGrab``），只有**前台**窗口的像素可信；加载刚结束时
    另有一个窗口压在游戏上面是实测见过的（B50），所以这一步不能省。
    """
    tick_clock: Clock = _monotonic
    deadline = tick_clock() + LOOK_TIMEOUT
    hwnd = _live_window(hwnd)
    _set_foreground(hwnd)  # 加载结束时游戏自己会抢前台；这里只是"万一它没抢"时补上
    wait_until(
        lambda: _foreground_window() == _live_window(hwnd),
        timeout=FOREGROUND_SETTLE,
        interval=FOREGROUND_POLL,
    )
    attempts = 0
    while tick_clock() < deadline:
        hwnd = _live_window(hwnd)
        if _foreground_window() == hwnd:
            return hwnd
        attempts += 1
        _set_foreground(hwnd)
        # 把 hwnd 绑成默认参数：lambda 里直接引用 hwnd 会被 ruff 的 B023 判为"绑了循环变量"
        # （下一轮它就被重新赋值了）—— 这里其实每轮都同步求值，但显式绑定更省事也更好读。
        wait_until(
            lambda target=hwnd: _foreground_window() == target,
            timeout=FOREGROUND_SETTLE,
            interval=CONDITION_POLL,
        )
    front = _foreground_window()
    raise ForegroundLostError(
        f"{LOOK_TIMEOUT:.0f} 秒内游戏没能拿到前台（游戏 hwnd={hwnd}，前台={front}，"
        f"标题={_window_title(front)!r}，试了 {attempts} 次）—— 此时点击会送给别的窗口，已中止"
    )


def find_observe(hwnd: int, *, threshold: float = DEFAULT_THRESHOLD) -> Match | None:
    """只抓底部条、找「观察」按钮 —— **找不到返回 ``None``**（不抛），供自适应调用。"""
    return find_in_roi(hwnd, "btn_observe", roi=BOTTOM_ROI, threshold=threshold)


def _step_look(
    hwnd: int, *, threshold: float, lobby_timeout: float = LOOK_TIMEOUT
) -> tuple[Match, int]:
    """① 确认「观察」出现；返回 ``(匹配, 当前句柄)``。

    频率自己负责（P2）：只抓底部条 :data:`BOTTOM_ROI`，抓图间隔从
    :data:`CAPTURE_INTERVAL_START` 按 :data:`CAPTURE_INTERVAL_GROWTH` 放慢到
    :data:`CAPTURE_INTERVAL_MAX` —— 不是固定 2 秒整屏抓，也不是每个尺度都试
    （``first_hit=True``：一个可信命中就够）。

    抓图失败按"还没画好"处理并**记下最后一条错误**：界面在切换时会短暂近纯色，
    那不是失败；但一直在失败就必须把原因带进异常里（P13），否则只剩一句"没找到"。
    """
    tick_clock: Clock = _monotonic
    hwnd = _ensure_live_foreground(hwnd)
    deadline = tick_clock() + lobby_timeout
    interval = CAPTURE_INTERVAL_START
    last_error = ""
    while tick_clock() < deadline:
        try:
            image = screenshot(hwnd, roi=BOTTOM_ROI)
        except CaptureFailedError as exc:
            last_error = str(exc)
            image = None
        found = (
            None
            if image is None
            else locate_optional(image, "btn_observe", threshold=threshold, first_hit=True)
        )
        if found is not None:
            # 坐标是**裁剪图内**的 ⇒ 加回 ROI 偏移才是客户区坐标（否则点击会打到别处）
            dx, dy = _roi_offset(hwnd, BOTTOM_ROI)
            return _shift_match(found, dx, dy), hwnd
        _sleep(interval)
        interval = min(interval * CAPTURE_INTERVAL_GROWTH, CAPTURE_INTERVAL_MAX)
    raise TemplateNotFoundError(
        f"{lobby_timeout:.0f} 秒内没在底部找到「观察」按钮（最后抓图错误："
        f"{last_error or '无'}）—— 游戏没走到选择国家界面，或界面语言/分辨率变了"
    )


def _step_observe(
    hwnd: int, match: Match, *, settle_timeout: float, force: bool = False
) -> dict[str, object]:
    """② 点「观察」进入观察者模式，并确认**界面真的切走了**。

    ⚠️ 判据不能用"日志有没有新行"：暂停时不写日志（实测）。所以判据是
    "底部那个按钮没了"，**外加**"时间开始走了"这条更硬的真值（任一成立即算切走）。
    """
    with suppress(CaptureFailedError):
        save_shot(screenshot(hwnd), "10-lobby")  # 证据：整屏一张（一次性，不是热路径）
    click_match(hwnd, match, force=force)
    settled = wait_until(
        lambda: find_in_roi(hwnd, "btn_observe", roi=BOTTOM_ROI) is None or tick_mark().readable,
        timeout=settle_timeout,
        interval=CONDITION_POLL,
    )
    with suppress(CaptureFailedError):
        save_shot(screenshot(hwnd), "11-after-observe")
    if not settled:
        raise TemplateNotFoundError(
            f"点了「观察」({match.describe()}) 但 {settle_timeout:.0f} 秒后界面没切走"
            "（底部按钮还在、时间也没开始走）—— 这一下点空了；"
            "证据帧：tools/out/auto/10-lobby.png 与 11-after-observe.png"
        )
    return {"observe": match.describe(), "lobby_settled": "大厅界面已切走"}


def _step_speed(
    hwnd: int,
    *,
    speed_xy: tuple[int, int] | None,
    threshold: float,
    index: int,
    force: bool = False,
) -> tuple[str, tuple[int, int]]:
    """③ 点速度档（用户口径就是 **5 档**）；点哪个位置由**候选序列**决定，不赌某一个点。

    表盘会随「运行/暂停 + 当前档」变色 —— 实测暂停态的模板拿去匹配运行态只有 0.327，
    所以"点哪里"只能当**首选**，最终判据永远是点完量出来的速率（见 :func:`measure_rate`）。
    """
    candidates = speed_candidates(hwnd, speed_xy=speed_xy, threshold=threshold)
    label, point = candidates[min(index, len(candidates) - 1)]
    click_client(hwnd, point[0], point[1], force=force)
    _sleep(STEP_SETTLE)
    return label, point


def _step_unpause(
    hwnd: int, *, key_timeout: float, run_timeout: float, key: str = "space", force: bool = False
) -> tuple[str, bool, Advance | None]:
    """④ 按空格开始（**已经在跑就不按**），返回 ``(说明, 按没按, 推进证据)``。

    ⚠️ **空格是暂停开关，不是"开始"**：此时若时间已经在走，再按一下会把它**暂停**。
    所以先等一次"tick 越过基线"；等到了就直接返回，一个键都不按。

    为什么不用"看播放键在不在"来判断：那是**像素**判据，而暂停与否有更硬的真值
    （逐 tick 日志）。能用真值就不用代理 —— 代理必须标注（F6），这里连标注都不需要，
    因为真值本来就在手边。

    两个超时是分开的：按之前给 ``key_timeout``（世界可能还在载入，实测 8 秒太短），
    按之后给 ``run_timeout``（真按中了应该很快就有 tick，等太久说明没按中）。

    按之前还要断言**游戏仍在前台**：空格是真实键盘事件，送给前台窗口；前台要是被别人
    抢走了，这一按会打给那个窗口（用户正在用的窗口），必须当场停下。
    """
    _sleep(STEP_SETTLE)
    if _foreground_window() != hwnd:
        raise ForegroundLostError(
            f"要按 {key} 时游戏已经不在前台（游戏 hwnd={hwnd}，前台={_foreground_window()}）——"
            "真实键盘事件会送给前台窗口，这一按会打到别处，已中止"
        )
    advance = _wait_running(tick_mark(), timeout=key_timeout)
    if advance is not None:
        return f"时间已经在走 ⇒ 没有按 {key}（空格是暂停开关，按下去反而会停）", False, advance
    press_key(key, force=force)
    _sleep(STEP_SETTLE)
    after = _wait_running(tick_mark(), timeout=run_timeout)
    if after is None:
        raise NotRunningError(
            f"按了 {key} 之后 {run_timeout:.0f} 秒内时间仍没有推进 —— "
            "空格没被引擎接受（进度条可能还在载入），或游戏被别的东西暂停了"
        )
    return f"已按 {key} 开始推进", True, after


def _wait_running(before: TickMark, *, timeout: float) -> Advance | None:
    """等"时间真的在走"（判据 = 逐 tick 日志）；超时给 ``None``。

    为什么"读不到基线"要单独处理：会话刚起时日志里**一行 tick 都没有**，"越过基线"无从
    谈起（实测栽过：时间明明在走却永远判不出来，于是误报"播放键没点中"）。
    那种情况改判"从读不到变成读得到"。
    """
    try:
        if before.readable:
            return wait_until_running(before, timeout=timeout)
        mark = wait_until_readable(timeout=timeout)
    except NotRunningError:
        return None
    return Advance(
        advanced=True,
        before=before.tick,
        after=mark.tick,
        seconds=timeout,
        source="dedicated_server.log（首次可读）",
    )


def start_session(
    hwnd: int,
    previous: int = 0,
    *,
    settle: BootSettle | None = None,
    speed_xy: tuple[int, int] | None = None,
    skip_speed: bool = False,
    min_rate: float = SPEED_V_MIN_RATE,
    speed_attempts: int = 3,
    measure_seconds: float = 8.0,
    unpause_key: str = "space",
    threshold: float = DEFAULT_THRESHOLD,
    # 空格之后第一次判定给足时间：世界可能还在载入。实测 8 秒太短（点完观察 8 秒内
    # 没有 tick 是**正常**的），45 秒才够"载入完 + 解暂停 + 写出第一行 tick"。
    key_timeout: float = 45.0,
    run_timeout: float = RUN_TIMEOUT,
    lobby_timeout: float = LOOK_TIMEOUT,
    settle_timeout: float = MAP_SETTLE_TIMEOUT,
    verify_minimized: bool = True,
    keep_foreground: bool = False,
    force: bool = False,
) -> SessionStart:
    """**标准流程**：确认「观察」→ 点它 → 点 5 档速度 → 按空格 → 切回后台。

    流程与用户口径逐条对应（2026-09-22）：

    1. **游戏已经在前台**（由 ``launch_to_foreground`` 负责；加载期不碰窗口）；
    2. 点「观察」（:func:`_step_observe`）—— 判据是**界面真的切走了**；
    3. 点 5 档速度（:func:`_step_speed`）—— 判据是**点完量出来的速率**；
    4. 按空格开始（:func:`_step_unpause`）—— 已经在跑就**不按**（空格是暂停开关）；
    5. **切回后台**（:func:`switch_to_background`）：还前台 + 缩窗口；
    6. **缩着也要推进**：这是必须实测的一条（有些游戏一缩下去就不渲染），
       所以缩完之后再量一次；验不过就**当场恢复**并如实写进 ``handover.minimized``。

    失败即抛错，**不返回半个结果**（P13）。这里没有回落链 —— 见模块开头的设计口径。
    """
    hwnd = _route_to_foreground(hwnd, previous, force=force)
    boot = settle if settle is not None else wait_for_boot_settle()
    match, hwnd = _step_look(hwnd, threshold=threshold, lobby_timeout=lobby_timeout)
    _step_observe(hwnd, match, settle_timeout=settle_timeout, force=force)

    rate = 0.0
    attempts = 0
    source = "跳过（skip_speed）"
    point: tuple[int, int] | None = None
    if not skip_speed:
        attempts = 1
        source, point = _step_speed(
            hwnd, speed_xy=speed_xy, threshold=threshold, index=0, force=force
        )

    unpause_note, pressed, advance = _step_unpause(
        hwnd,
        key_timeout=key_timeout,
        run_timeout=run_timeout,
        key=unpause_key,
        force=force,
    )
    with suppress(CaptureFailedError):
        save_shot(screenshot(hwnd), "12-after-space")

    # 速率：**在切回后台之前**先量一次 —— 这时窗口还在前台、像素与输入都最干净；
    # 切回去之后再量一次（`verify_minimized`），两次都算"实测"，不是二选一。
    if not skip_speed:
        rate = measure_rate(measure_seconds)
        while rate < min_rate and attempts < speed_attempts:
            source, point = _step_speed(
                hwnd, speed_xy=speed_xy, threshold=threshold, index=attempts, force=force
            )
            attempts += 1
            rate = measure_rate(measure_seconds)

    handover = switch_to_background(hwnd, previous, minimize=not keep_foreground)
    if verify_minimized and handover.minimized:
        after = measure_rate(measure_seconds)
        if after <= 0.0:
            # 缩下去不推进 —— 这是**游戏行为**，不是我们的 bug；当场恢复成普通窗口再量一次，
            # 并把结论如实写进返回值（不静默降级）。
            _restore(hwnd)
            wait_until(
                lambda: not _is_iconic(hwnd), timeout=WINDOW_SHOW_SETTLE, interval=CONDITION_POLL
            )
            handover = replace(
                handover,
                minimized=False,
                seconds=handover.seconds + measure_seconds,
            )
            after = measure_rate(measure_seconds)
        rate = after if after > 0.0 else rate

    return SessionStart(
        hwnd=hwnd,
        previous=previous,
        settle=boot,
        observe=match,
        speed_source=source,
        speed_xy=point,
        unpause=unpause_note,
        pressed=pressed,
        advance=advance,
        rate=rate,
        rate_ok=skip_speed or rate >= min_rate,
        attempts=attempts,
        handover=handover,
        tick=tick_mark().tick,
    )


def run_session(
    *,
    scripted_tests: bool = True,
    lobby_timeout: float = LOBBY_TIMEOUT,
    speed_xy: tuple[int, int] | None = None,
    skip_speed: bool = False,
    verify_minimized: bool = True,
    keep_foreground: bool = False,
    force: bool = False,
) -> SessionStart:
    """端到端一条命令：起游戏 → 等加载 → 观察/速度/空格 → 切回后台。

    这是 CLI ``run`` 与探针共用的入口，**内部没有第二条路**。
    """
    hwnd, previous = launch_to_foreground(scripted_tests=scripted_tests, timeout=lobby_timeout)
    settle = wait_for_boot_settle(timeout=lobby_timeout)
    return start_session(
        hwnd,
        previous,
        settle=settle,
        speed_xy=speed_xy,
        skip_speed=skip_speed,
        lobby_timeout=LOOK_TIMEOUT,
        verify_minimized=verify_minimized,
        keep_foreground=keep_foreground,
        force=force,
    )


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

    只做四件事：看状态、跑一局（标准流程）、抓图（收模板用）、验后台。
    **任何一步失败都返回退出码 1**，不打印"完成"。
    """
    parser = argparse.ArgumentParser(
        prog="python -m pdx.game_auto",
        description="Victoria 3 自动化：起游戏 → 观察 → 5 档速度 → 空格 → 切回后台",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="只读：报告 tick / 探针月度行 / 时间是否在推进")
    sub.add_parser("check", help="断言当前没有 victoria3 在跑")

    run_parser = sub.add_parser(
        "run",
        help="标准流程：起游戏（前台）→ 等加载 → 点观察 → 点 5 档速度 → 按空格 → 切回后台",
    )
    run_parser.add_argument(
        "--no-scripted-tests", action="store_true", help="不带官方 -scripted_tests 开关"
    )
    run_parser.add_argument("--lobby-timeout", type=float, default=LOBBY_TIMEOUT)
    run_parser.add_argument(
        "--skip-speed", action="store_true", help="不切速度档（只观察 + 解暂停）"
    )
    run_parser.add_argument(
        "--keep-foreground",
        action="store_true",
        help="跑完**不**切回后台（默认会切：还前台 + 缩窗口）",
    )
    run_parser.add_argument(
        "--no-verify-minimized",
        action="store_true",
        help="跳过「缩着也在推进」那一步实测（默认实测，验不过当场恢复）",
    )
    run_parser.add_argument("--speed-xy", default="", help="显式指定速度档 V 的客户区坐标 X,Y")

    cap_parser = sub.add_parser("capture", help="抓游戏窗口到 PNG（收模板/留证据用）")
    cap_parser.add_argument("out", help="输出 PNG 路径")
    cap_parser.add_argument("--tag", default="manual", help="证据截图的名字前缀")

    bg_parser = sub.add_parser("background", help="把前台让出去，验证模拟是否继续")
    bg_parser.add_argument("--seconds", type=float, default=20.0)

    args = parser.parse_args(argv)
    command: str = args.command

    # 只有显式入口才允许碰真实窗口/输入：不开模块开关，而是**把 force 传到会注入输入的那一步**
    # （抢前台、点击、按键）。为什么要这样：模块级开关要 `global` 才能改，改出来的效果是
    # "整个进程从此都可以动用户的桌面"；传参的效果是"只有这一条路径可以"，边界清楚。
    force = command in {"run", "capture", "background"}

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

        # 只剩 "run"：标准流程 —— 起游戏（前台）→ 等加载（**完全不碰窗口**，只用进程 +
        # 日志这些免费信号，至少 BOOT_MIN_SECONDS 秒；实测到选国家界面约 137 秒）
        # → 点观察 → 点 5 档速度 → 按空格 → 切回后台（还前台 + 缩窗口）。
        hwnd, previous = launch_to_foreground(
            scripted_tests=not bool(args.no_scripted_tests),
            timeout=float(args.lobby_timeout),
        )
        settle = wait_for_boot_settle(timeout=float(args.lobby_timeout))
        print(f"加载等待（不碰窗口）：{settle.why}")
        speed_xy: tuple[int, int] | None = None
        if args.speed_xy:
            left, _, right = str(args.speed_xy).partition(",")
            speed_xy = (int(left), int(right))
        result = start_session(
            hwnd,
            previous,
            settle=settle,
            speed_xy=speed_xy,
            skip_speed=bool(args.skip_speed),
            verify_minimized=not bool(args.no_verify_minimized),
            keep_foreground=bool(args.keep_foreground),
            force=force,
        )
        print("闭环完成，证据：")
        for key, value in result.as_dict().items():
            print(f"  {key:22s}: {value}")
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
    "BootSettle",
    "CaptureFailedError",
    "ForegroundHandover",
    "ForegroundLostError",
    "GameAutoError",
    "GameRunningError",
    "Match",
    "NotRunningError",
    "SessionStart",
    "TemplateNotFoundError",
    "TickMark",
    "WindowNotFoundError",
    "assert_no_game_running",
    "click_client",
    "click_match",
    "ensure_foreground",
    "find_observe",
    "find_template",
    "find_window",
    "is_blank",
    "is_later",
    "is_running",
    "last_tick_in",
    "launch",
    "launch_to_foreground",
    "load_template",
    "locate",
    "locate_optional",
    "match_template",
    "measure_rate",
    "other_window",
    "parse_tasklist_pids",
    "parse_tick_date",
    "press_key",
    "probe_months",
    "probe_roles_in",
    "roi_box",
    "run_session",
    "screenshot",
    "speed_candidates",
    "speed_widget_xy",
    "start_session",
    "status_report",
    "switch_to_background",
    "tick_day",
    "tick_mark",
    "wait_for_boot_settle",
    "wait_for_window",
    "wait_until",
    "wait_until_readable",
    "wait_until_running",
]
