"""Victoria 3 自动化：把一局"跑起来"（起游戏 → 观察 → 按 5 速 → 空格 → 切回后台）。

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
      → 确认游戏在前台，然后：点「观察」→ 按 5 速快捷键 → 按空格
      → 立刻把游戏切回后台（还原用户原来的前台窗口，再最小化游戏窗口）
      → 后台验证：时间真的在走吗、速率多少
      →（``run --wait-tests N``）再验一次"缩着也在跑" → 等官方套件判定 → 读产物给结论

最后那一步是**闭环的收口**（`自动化范式.md` §6 的后两步）：判据全部来自引擎自己写的
``tests.txt`` 与 ``binaries/*_GameTests_testoutput.xml``，本模块只解析、不判分。
默认不等 —— 成绩单什么时候写完由套件的 ``last_date`` 决定，可能是**小时级**，
不该由工具替调用方定这个时长。

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
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import cv2
import numpy as np
import psutil
from PIL import Image, ImageGrab

from . import config, experiments
from .automation_contract import AutomationPhase, AutomationTrace
from .console import enable_utf8_stdio
from .platform_support import UnavailableWindowsModule, WindowsOnlyError

if TYPE_CHECKING:
    from collections.abc import Sequence

# 本模块本次 Popen 创建的根进程；失败清理只针对这些 PID。
_OWNED_GAME_PIDS: set[int] = set()


@dataclass(frozen=True, slots=True)
class OwnedProcess:
    """启动时记录的进程身份，防止 PID 复用导致误杀。"""

    pid: int
    create_time: float | None = None
    executable: str = ""


_OWNED_GAME_META: dict[int, OwnedProcess] = {}
LAST_QUARANTINE_ERRORS: list[str] = []
LAST_KILL_ALIVE: list[int] = []

if sys.platform == "win32" or TYPE_CHECKING:
    import pydirectinput as directinput
    import pygetwindow as gw
    import win32api
    import win32con
    import win32gui
    import win32process
else:
    directinput = UnavailableWindowsModule("pydirectinput")
    gw = UnavailableWindowsModule("pygetwindow")
    win32api = UnavailableWindowsModule("win32api")
    win32con = UnavailableWindowsModule("win32con")
    win32gui = UnavailableWindowsModule("win32gui")
    win32process = UnavailableWindowsModule("win32process")

#: `pydirectinput` 的两个开关必须由我们定死：
#: * `FAILSAFE`：鼠标移到屏幕角落就抛异常中断 —— 自动化里这是**随机失败源**，关掉；
#: * `PAUSE`：库默认每次调用后 sleep 0.1 秒 —— 一次点击要调 `moveTo` + `click` 两次，
#:   留着它每点一下多花 0.2 秒，且与调用方自己的 `settle` 重复。
directinput.FAILSAFE = False
directinput.PAUSE = 0.0

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Literal

    # 注入缝的类型别名：**只给类型检查器看**，运行期不存在这两个名字。
    # 为什么不在运行期定义：`collections.abc.Callable` 若只用在注解里，
    # ruff 的 TC003 会要求它进 type-checking 块（本仓既有口径）。
    Clock = Callable[[], float]
    Sleeper = Callable[[float], None]

    #: 「抓图失败」怎么处置：``"raise"``（默认）出声、``"miss"`` 退化成"不命中"。
    #: 之所以要把这件事变成**签名上的显式选择**（t19）：两者的区别是
    #: "看不到"与"没有"，把后者写成默认会让每个调用点都默默继承同一个病。
    CapturePolicy = Literal["raise", "miss"]

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
#: 普通主菜单「新游戏」按钮的已证 ROI（1920×1080 实测 x=236..520, y=414..454）。
MAIN_MENU_ROI = (0.105, 0.350, 0.290, 0.455)
#: 主菜单模板在悬停/缩放后分数低于观察者模板，ROI 已收紧后取 0.55。
NEW_GAME_THRESHOLD = 0.55
#: 普通新游戏设置页「开始游戏」按钮 ROI（2026-10-02 实机帧提取）。
SETUP_START_ROI = (0.80, 0.58, 0.98, 0.72)
#: 2026-10-04 实测 1.14.5 中文目标页同一按钮在未悬停状态为 0.5905；
#: ROI 只覆盖右下角开始按钮，0.55 保留与主菜单相同的抗锯齿余量，
#: 后续仍必须找到「观察」并验证游戏时间推进，低分误匹配不会形成假成功。
START_GAME_THRESHOLD = 0.55

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

# 控制台开合之后等它画出来（控制台是个大面板，实测 1.5 秒足够；之后仍以 ROI 判据为准）。
CONSOLE_SETTLE = 1.5


#: 等"画面不再变"的上限（秒）与判据（帧间平均差 ≤ 这个比例即算稳定）。
#: 规则窗里点一下 ‹ › 之后档名/说明要过一帧才画出来 —— 这是 :func:`wait_stable` 存在的理由。
STABLE_TIMEOUT = 8.0
STABLE_DIFF = 0.002

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

#: 等到"忙完"之后，再等「观察」出现的上限（秒）。原值 **45.0**：这段时间用户屏幕被游戏
#: 占着，前面已经用"完全不碰屏幕"的信号等过一轮，所以这里通常几秒内就命中。
#: 2026-09-30 改成 **180.0**（t9 阶段 4 ④ 判决批，队长条件授权）：实测两次栽在这里
#: （runC 23:50:59 / runD `ours #5` 02:00:50，同一栈 `perf_compare.run_once` →
#: `start_session` → `_step_look`）—— `wait_for_boot_settle` 的"日志安静 20 秒"判据会落进
#: **加载停顿**，随后这 45 秒要独力覆盖整段世界初始化 + UI 渲染（失败臂 debug.log 末行
#: 正是世界初始化，收尾只比它晚十几秒）。改的是**启动等待预算**，不改被测量：每帧 AI 时间
#: 从进入 session 之后才开始记，CSV 内容不受影响。
LOOK_TIMEOUT = 180.0

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

# 原版 game/input_profile/default.profile 的 speed_5 快捷键：物理数字键 5。
# 键盘路径不依赖分辨率、UI 缩放、界面语言或光标位置；最终仍以真实 tick 速率验收。
SPEED_5_KEY = "5"

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


def _require_input(force: bool) -> None:
    """没有真实输入授权就**当场报错**（每个注入点都必须先过这一关）。"""
    if not _input_allowed(force):
        raise RealInputBlockedError(
            "没有授权就投真实键盘输入：这会让用户正在打的字跑到游戏里。"
            "显式入口请打开 `ALLOW_REAL_INPUT` 或传 `force=True`。"
        )


def press_key(key: str, *, force: bool = False) -> None:
    """按一次**真实**键（扫描码，`pydirectinput`）—— 和点击共用同一道输入闸门。

    为什么要收成一个函数：`directinput.press` 直接调用会**绕过** :func:`_input_allowed`，
    于是"什么时候可以碰真实键盘"就漏了一个口子（测试里少打一个桩，用户就会看到
    自己正在打的字跑到游戏里）。收成一处，闸门才真的是闸门。
    """
    _require_input(force)
    directinput.press(key)


def press_chord(chord: str, *, force: bool = False) -> None:
    """按一次组合键：``"`"`` 或 ``"shift+`"``（同样是真实扫描码）。

    为什么需要它：`pydirectinput` 的键表按**扫描码**给，上档字符（``~`` / ``^`` /
    ``_``）**根本不在表里** —— 想敲上档就得自己按住 Shift。收成一处，
    :func:`type_text` 与探针的按键扫描走的是同一条路，不会各自实现一遍。
    """
    _require_input(force)
    if "+" not in chord:
        directinput.press(chord)
        return
    mods, _, key = chord.rpartition("+")
    for mod in mods.split("+"):
        directinput.keyDown(mod)
    try:
        directinput.press(key)
    finally:
        # 一定要抬起：不然"按住的 Shift"会漏到后面的所有输入里（用户看到的
        # 是"我打的字全变大了"，而且游戏里也会一直被当成按住 Shift）。
        for mod in reversed(mods.split("+")):
            directinput.keyUp(mod)


#: 上档字符 → 不带 Shift 的那个键位。
#:
#: 为什么需要这张表：`pydirectinput` 的键表里**只有不带 Shift 的单字符键** ——
#: 实测 ``_`` / ``~`` / ``^`` 与大写字母**都不在表里**，直接
#: `directinput.write("dump_ticktask_timings")` 会在下划线那一格抛 `KeyError`。
#: 表里只放我们要敲的字符集（控制台命令名用的那一套），多写的没人验证过就没意义。
SHIFT_CHARS: dict[str, str] = {
    "_": "-",
    "~": "`",
    ":": ";",
    "?": "/",
    '"': "'",
    "+": "=",
    "(": "9",
    ")": "0",
    " ": "space",
}


def type_text(text: str, *, force: bool = False) -> None:
    """像人一样**逐字**敲入一个字符串（真实扫描码输入；上档字符自动带上 Shift）。

    用它而不是 `pydirectinput.write()`：后者对不在键表里的字符会抛 `KeyError`，
    而我们要敲的控制台命令名里就有下划线。这里把"要不要按 Shift"显式写出来，
    闸门与 :func:`press_key` / :func:`press_chord` 是同一道。
    """
    _require_input(force)
    for char in text:
        if char in SHIFT_CHARS:
            press_chord(f"shift+{SHIFT_CHARS[char]}", force=True)
        elif char.isupper():
            press_chord(f"shift+{char.lower()}", force=True)
        else:
            directinput.press(char)


# ────────────────────────── 游戏内控制台 ──────────────────────────
#
# 为什么值得在这里收一层：**引擎自带的性能仪表只在控制台里**（
# `dump_ticktask_timings` 把逐帧逐任务的计时落成 `ticktask_timings.csv`，
# `log_ticktask_performance` 开持续日志）。GUI 注入那条路九条候选全判死（backlog B64），
# 命令行 `-run_console_action*` 又"跑完即退"（取不到跑一段之后的读数）—— 于是
# "能不能自动敲进控制台"直接决定性能预算量不量得出来。实测（2026-09-23，backlog B66）：
#
#   * **反引号**开控制台（`shift+\`` / `/` / `f12` 都量过：上半屏像素差 0.000，没反应）；
#   * 合成的扫描码键盘**能**进输入框（截图里逐字读得到命令名）；
#   * **要按两次回车** —— 第一次被自动补全吃掉（exe 明文有
#     `SETTING_CONSOLE_AUTOCOMPLETE_MODE` 一族设置），第二次才执行。
#
# 判据全部走**画面**（不猜也不目测）：控制台开着时输入框那块 ROI 是暗的（均值 ≈31–48），
# 关着时地图透出来（≈190）；输入框有字时标准差 ≈43–55、空的 ≈7–18。

#: 开控制台的键。
CONSOLE_KEY = "`"

#: 控制台输入框（`gui/console.gui` 的 `console_edit`）在**客户区**里的像素矩形。
#: 实测口径：1920x1080、界面缩放 100%。
CONSOLE_EDIT_ROI = (8, 568, 428, 606)

#: 控制台输出区**顶部**（命令的回话写在这儿，例如 `Wrote 14792 rows to …`）。
CONSOLE_OUTPUT_ROI = (8, 0, 340, 120)

#: 输入框标准差低于这个数 = 已经空了（提交成功的第一条判据）。
CONSOLE_CLEARED_STD = 30.0

#: 输入框 ROI 均值低于这个数 = 控制台开着（暗面板），高于它 = 关着（地图透出来）。
CONSOLE_OPEN_MEAN = 90.0


def _roi_stats(hwnd: int, roi_px: tuple[int, int, int, int]) -> tuple[float, float, int]:
    """**像素** ROI 的 (均值, 标准差, 亮像素数)。

    ⚠️ `screenshot` 要的是**分数**矩形，所以这里必须换算 —— 直接把像素传进去会
    bbox 乘出天文数字、PIL 抛 `DecompressionBombError`（实测踩过，报错指不到原因）。
    """
    width, height = _client_size(hwnd)
    x0, y0, x1, y1 = roi_px
    image = screenshot(hwnd, roi=(x0 / width, y0 / height, x1 / width, y1 / height))
    box = np.asarray(image.convert("L"), dtype=np.float32)
    return (float(box.mean()), float(box.std()), int((box > 140).sum()))


def console_open(hwnd: int) -> bool:
    """控制台现在开着吗？（判据：输入框 ROI 的均值，实测开着 ≈31–48、关着 ≈190）"""
    mean, _std, _ink = _roi_stats(hwnd, CONSOLE_EDIT_ROI)
    return mean < CONSOLE_OPEN_MEAN


def console_output_ink(hwnd: int) -> int:
    """输出区顶部的亮像素数 —— 命令回话就会让它跳（提交成功的第二条判据）。"""
    _mean, _std, ink = _roi_stats(hwnd, CONSOLE_OUTPUT_ROI)
    return ink


def open_console(hwnd: int, *, key: str = CONSOLE_KEY, force: bool = False) -> bool:
    """把控制台打开；已经开着就直接返回 ``True``，没打开就**如实返回 False**（不假装）。"""
    if console_open(hwnd):
        return True
    press_chord(key, force=force)
    _sleep(CONSOLE_SETTLE)
    return console_open(hwnd)


def _focus_editbox(hwnd: int, *, force: bool) -> None:
    """把键盘焦点交给控制台输入框，并清空它（免得新命令粘在旧的后面）。

    为什么必须点一下：控制台一旦打开就**关不掉**（实测 escape / 反引号 / shift+escape
    都没用），于是它会在整局里一直挂着；而"让时间跑起来"那一步要按 5 速快捷键、按空格 ——
    焦点就此离开输入框。下一次敲命令时字会**打进游戏而不是控制台**，
    `submit_console_command` 就会一直判"没提交成功"。**实测踩过**：一局里
    `clear` 成功、跑完 12 个月后的 `dump` 失败 ⇒ `ticktask_timings.csv` 没出现。

    ⚠️ **清空只能用 `backspace`，绝对不能用 `delete`**：`pydirectinput` 发扫描码时
    **不带扩展位**，而 Delete 的扫描码 `0x53` 在不带扩展位时就是**小键盘的 `.`** ——
    实测后果是控制台收到 `.clear_ticktask_timings` 并回 **`Unknown command`**
    （画面证据：`tools/out/auto/perf-vanilla-after-dump.png`）。
    """
    x0, y0, x1, y1 = CONSOLE_EDIT_ROI
    click_client(hwnd, (x0 + x1) // 2, (y0 + y1) // 2, force=force)
    _sleep(STEP_SETTLE)
    press_chord("ctrl+a", force=force)  # 先全选，免得新命令粘在旧的后面
    _sleep(0.1)
    press_key("backspace", force=force)  # 删掉选中内容（**不是 delete**，见上）
    _sleep(0.2)


def submit_console_command(
    hwnd: int,
    command: str,
    *,
    force: bool = False,
    attempts: int = 2,
    settle: float = 2.0,
) -> bool:
    """敲一条控制台命令并**提交**，返回是否确认被执行（`输入框清空` 且 `输出区有回话`）。

    ⚠️ **两次回车**不是随手写的：按一次时输入框标准差 44.9 → 44.0（字一个没少、
    输出区一动不动），连按两次 43.0 → 7.5 且输出区亮像素 322 → 1732。第一次被
    控制台的**自动补全**吃掉 —— 这条坑在 backlog B66 里。

    ⚠️ 调用方要先保证**游戏是前台**（`ensure_foreground`）：合成键盘只送给前台窗口。
    """
    for _ in range(max(1, attempts)):
        if not open_console(hwnd, force=force):
            return False
        _focus_editbox(hwnd, force=force)
        before_ink = console_output_ink(hwnd)
        type_text(command, force=force)
        _sleep(0.6)
        press_key("enter", force=force)
        _sleep(0.35)
        press_key("enter", force=force)
        _sleep(settle)
        _mean, std, _ink = _roi_stats(hwnd, CONSOLE_EDIT_ROI)
        if std < CONSOLE_CLEARED_STD and console_output_ink(hwnd) > before_ink + 20:
            return True
        # 没提交成功就把输入框清干净，免得下一条命令粘在后面。
        for _ in range(len(command) + 8):
            press_key("backspace", force=force)
        _sleep(0.4)
    return False


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
    命中即停 15.3 ms（**75×**，见 `tests/test_benchmarks.py::TestAutoCaptureBenchmarks`）。
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
    if not all(0.0 <= value <= 1.0 for value in (left, top, right, bottom)):
        # 实测踩过：把**像素**坐标当分数传进来（例如 (8, 568, 428, 606)），
        # bbox 会乘出一个天文数字，PIL 直接抛 `DecompressionBombError`
        # （"Image size (33094656000 pixels) exceeds limit"）——
        # 那句报错完全指不到真正的原因。这里就地把它说清楚。
        raise CaptureFailedError(
            f"roi 必须是**分数**矩形（0–1），收到 {roi} —— 像素坐标请先除以客户区尺寸"
            f"（当前客户区 {width}x{height}）"
        )
    x0 = origin_x + int(left * width)
    y0 = origin_y + int(top * height)
    x1 = origin_x + max(int(right * width), int(left * width) + 1)
    y1 = origin_y + max(int(bottom * height), int(top * height) + 1)
    return ImageGrab.grab(bbox=(x0, y0, x1, y1), all_screens=True).convert("RGB")


def _process_pids(image_name: str | None = None) -> list[int]:
    """psutil 枚举匹配进程，不启动平台命令；忽略枚举期间已退出的进程。"""
    wanted = image_name or ("victoria3.exe" if sys.platform == "win32" else "victoria3")
    return sorted(
        process.pid
        for process in psutil.process_iter(["name"])
        if (process.info["name"] or "").casefold() == wanted.casefold()
    )


def _capture_process_identity(pid: int) -> OwnedProcess:
    """尽力记录 pid 的创建时间和可执行文件；权限不足时保留可用字段。"""
    create_time: float | None = None
    executable = ""
    try:
        process = psutil.Process(pid)
        with suppress(AttributeError, OSError, psutil.Error):
            create_time = float(process.create_time())
        try:
            executable = str(process.exe())
        except (AttributeError, OSError, psutil.Error):
            executable = str(getattr(process, "name", lambda: "")())
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        pass
    return OwnedProcess(pid=pid, create_time=create_time, executable=executable)


def _owned_identity_matches(process: object, expected: OwnedProcess) -> bool:
    """校验当前 PID 仍是启动时的进程；缺少字段时不凭空拒绝清理。"""
    if expected.create_time is not None:
        try:
            actual = float(process.create_time())  # type: ignore[attr-defined]
        except (AttributeError, OSError, psutil.Error):
            return False
        if abs(actual - expected.create_time) > 0.01:
            return False
    if expected.executable:
        try:
            actual_exe = str(process.exe())  # type: ignore[attr-defined]
        except (AttributeError, OSError, psutil.Error):
            return False
        if (
            actual_exe
            and Path(actual_exe).name.casefold() != Path(expected.executable).name.casefold()
        ):
            return False
    return True


def _wait_for_pids(pids: Sequence[int], *, timeout: float = 5.0) -> list[int]:
    """等待一组已终止的 PID 真正退出，返回仍存活的 PID。

    清理不能把 kill 请求当作进程已经退出：Windows 日志句柄在这段窗口
    里仍可能被占用，紧接着归档会产生假阴性。测试桩若没有 is_running 能力
    会被视为“不提供确认”，不阻断原有的纯逻辑测试。
    """
    remaining = {pid for pid in pids if isinstance(pid, int) and pid > 0}
    if not remaining:
        return []
    deadline = time.monotonic() + max(0.0, timeout)
    while remaining:
        for pid in tuple(remaining):
            try:
                process = psutil.Process(pid)
            except psutil.NoSuchProcess:
                remaining.discard(pid)
                continue
            is_running = getattr(process, "is_running", None)
            if not callable(is_running):
                return []
            try:
                if not is_running():
                    remaining.discard(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                remaining.discard(pid)
        if not remaining or time.monotonic() >= deadline:
            break
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
    return sorted(remaining)


# ────────────────────────── 窗口与前台 ──────────────────────────


def _window_pid(hwnd: int) -> int | None:
    """读取窗口所属 PID；非 Windows 或读取失败返回 ``None``。"""
    try:
        _thread, pid = win32process.GetWindowThreadProcessId(hwnd)
        return int(pid)
    except (AttributeError, OSError, WindowsOnlyError):
        return None


def find_window(
    title: str = WINDOW_TITLE, window_class: str = WINDOW_CLASS, *, pid: int | None = None
) -> int:
    """按标题、类和可选 PID 找可见的游戏窗口；找不到给 0。"""
    for hwnd in _enum_windows():
        if not _is_visible(hwnd):
            continue
        if title in _window_title(hwnd) and _window_class(hwnd) == window_class:
            if pid is not None and _window_pid(hwnd) != pid:
                continue
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
    *,
    timeout: float = WINDOW_TIMEOUT,
    clock: object = None,
    sleeper: object = None,
    pid: int | None = None,
) -> int:
    """等游戏窗口出现（官方流水线到标题菜单实测要 ~124 秒）。"""
    tick_clock: Clock = cast("Clock", _resolve(clock, _monotonic, "clock"))
    pause: Sleeper = cast("Sleeper", _resolve(sleeper, _sleep, "sleeper"))
    deadline = tick_clock() + timeout
    while tick_clock() < deadline:
        hwnd = find_window(pid=pid) if pid is not None else find_window()
        if hwnd:
            return hwnd
        pause(POLL_INTERVAL)
    raise WindowNotFoundError(f"{timeout:.0f} 秒内没等到 {WINDOW_TITLE!r} 窗口")


def _require_foreground_usable(hwnd: int) -> None:
    """前台名义上拿到了、但窗口**最小化**着 —— 这种"假成功"必须报错。

    实测（t29 warmup-01，2026-10-01）：`SetForegroundWindow` 对最小化窗口会"成功"，
    `GetForegroundWindow()` 真的返回它，但 `IsIconic` 仍为 True、客户区是 0x0。
    这条路径比"抢不到前台"更难查：`ensure_foreground` 不抛 ⇒ 置前权的合成输入恢复
    （:func:`recover_foreground`）**根本不会被调用**，实机链继续往下走，最后死在
    「客户区尺寸非法: 0x0（窗口最小化了？）」上（那一次 `look` 就是这么烧掉 180 秒的）。

    所以判据在这里补齐：**前台是它** 且 **它不是最小化的**，两个都成立才算拿到了能用的前台。
    """
    if _is_iconic(hwnd):
        front = _foreground_window()
        raise ForegroundLostError(
            f"前台名义上在游戏上，但窗口仍是最小化的（hwnd={hwnd}，IsIconic=True，"
            f"当前前台={front}，标题={_window_title(front)!r}）—— 最小化窗口的客户区是 0x0，"
            "抓图与点击都会落空，已中止"
        )


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
        # **"已经是前台"也要看窗口状态**：最小化窗口是"假成功"（见
        # :func:`_require_foreground_usable`），放它过去等于把真因糊成"坐标不对"。
        _require_foreground_usable(hwnd)
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
            _require_foreground_usable(hwnd)
            return

    front = _foreground_window()
    raise ForegroundLostError(
        f"抢不到前台（游戏 hwnd={hwnd}，当前前台={front}，标题={_window_title(front)!r}）"
        " —— 此时点击会送给别的窗口，已中止"
    )


# ──────────── 置前权的合成输入恢复（D28：t4 实机验证过的手法的正式版） ────────────
#
# 本机当前的前台是 Win11 的 shell 岛（`XamlExplorerHostIslandWindow_WASDK`），**没有前台
# 应用**时我们这条进程链一律抢不到前台 —— 连用户自己的 DSH 窗口都抢不到，与游戏无关，
# 是这条链的环境属性（t4 实测：`_set_foreground` 返回 False、`ensure_foreground` 抛
# `ForegroundLostError`）。于是 `ensure_foreground` 的判据永远失败，实机链一步都走不动。
#
# 出路只有一条，而且必须是**显式**的：先用一次**最不侵入的合成输入**把前台拿回来，
# 然后**照原样**再走既有路由（不复制任何会话逻辑）。三条硬边界：
#   * 有界：最多 FOREGROUND_RECOVERY_ATTEMPTS（3）次，每次之间把游戏**杀掉**重启
#     —— t4 之前那版 v1 在这里重试了 337 次、烧掉 180 s 与 7 GB RSS，换来一个必然的失败；
#   * 命中测试：落点必须先用 WindowFromPoint 命中游戏窗口，否则**一下都不点**；
#   * 可追溯：每次实际使用留一行 JSON（哪种注入 / hwnd / 注入前后前台 / IsIconic），
#     让证据能回答"这一局的焦点是怎么来的"。

#: 抢不到前台时的合成输入恢复上限。**3** 是硬上限，不是"再多试几次"的旋钮。
FOREGROUND_RECOVERY_ATTEMPTS = 3

#: 标题栏（非客户区）单击所需的最小带高（px）。
#: 低于它一律不点：无边框窗口 band=0，退化成点客户区就会把点击送给游戏里的按钮。
TITLEBAR_MIN_BAND_PX = 20

#: `Alt` 轻敲的按住时长与之后的静置（t4 实机值：连做两次，`attempts=1` 成功）。
ALT_TAP_HOLD = 0.08
ALT_TAP_SETTLE = 0.3

#: 标题栏单击前把鼠标挪过去的静置、点完之后的静置（t4 实机值）。
TITLEBAR_MOVE_SETTLE = 0.15
TITLEBAR_CLICK_SETTLE = 1.0

#: 每次实际使用写一行的落点（`tools/out` 是证据区，已 gitignore）。
FOREGROUND_RECOVERY_LOG = config.OUT / "foreground-recovery.jsonl"


@dataclass(frozen=True, slots=True)
class ForegroundAttempt:
    """一次"只用于取得置前权"的合成输入。

    ``performed=False`` 表示**被纪律拒绝、什么都没注入**（最小化 / 无标题栏 / 命中测试
    失败 / 句柄失效）；它与"注入了但没换来前台"必须分开记：前者是"没做"，后者是"做了没用"。
    """

    kind: str
    performed: bool
    refused_why: str
    hwnd: int
    foreground_before: int
    foreground_after: int
    is_iconic: bool
    point: tuple[int, int] | None = None
    hit: int = 0
    root: int = 0

    @property
    def ok(self) -> bool:
        """判据是**前台窗口真的换成了游戏**，不是任何一种注入的返回值。"""
        return bool(self.hwnd) and self.foreground_after == self.hwnd

    def describe(self) -> str:
        """一行读数（异常消息与报告都用它，措辞即证据面的词汇）。"""
        where = f"落点=({self.point[0]},{self.point[1]})" if self.point else "未落坐标"
        hit = f"命中测试=hwnd {self.hit}/root {self.root}" if self.point else "未点击（无命中测试）"
        why = f"、拒绝理由={self.refused_why}" if self.refused_why else ""
        return (
            f"{self.kind}：注入={'是' if self.performed else '否'}、{where}、{hit}、"
            f"注入前前台={self.foreground_before}、注入后前台={self.foreground_after}、"
            f"IsIconic={self.is_iconic}{why}"
        )

    def as_dict(self) -> dict[str, object]:
        """日志行主体（字段名固定，便于事后按 kind/hit 过滤）。"""
        return {
            "kind": self.kind,
            "injected": self.performed,
            "refused_why": self.refused_why,
            "hwnd": self.hwnd,
            "foreground_before": self.foreground_before,
            "foreground_after": self.foreground_after,
            "is_iconic": self.is_iconic,
            "point": list(self.point) if self.point else None,
            "hit": self.hit,
            "root": self.root,
        }


def _window_rect_visible(hwnd: int) -> tuple[bool, str]:
    """窗口 rect 是否落在**虚拟屏幕**内、且尺寸正常。

    为什么先卡这一条：注入是**全局**的（`SetCursorPos` + 鼠标事件），窗口在屏外或 rect
    退化时那一击会打到别的窗口上 —— 而"打到了别处"在截图里看起来跟"没生效"一模一样。
    """
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    if right - left <= 0 or bottom - top <= 0:
        return False, f"窗口 rect 退化：({left},{top},{right},{bottom})"
    vx = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
    vy = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
    vw = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
    vh = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
    if right <= vx or bottom <= vy or left >= vx + vw or top >= vy + vh:
        return False, f"窗口 rect ({left},{top},{right},{bottom}) 不在屏幕 ({vx},{vy}) {vw}x{vh} 内"
    return True, f"rect ({left},{top},{right},{bottom}) 在屏内"


def _acquire_foreground_by_input(hwnd: int, *, force: bool) -> ForegroundAttempt:
    """**一次**最不侵入的合成输入 —— 只为取得置前权，不做任何"点击语义"上的事。

    顺序（最不侵入优先）：

    ① `Alt` 轻敲：**不落任何坐标**，对游戏界面完全无副作用（t4 走的就是这条）；
    ② 标题栏（非客户区）单击：只有在 ① 没换来前台、窗口**有**非客户区带
       （≥ :data:`TITLEBAR_MIN_BAND_PX`）、且落点**命中测试**确实是游戏窗口时才点；
       **客户区永不点** —— 点了就是把这一击送给游戏界面里的某个按钮。

    注入同样要过输入闸门（:func:`_require_input`）：这条函数**不是**"顺手碰一下鼠标"的场合。
    """
    before = _foreground_window()
    iconic = _is_iconic(hwnd)

    def refused(kind: str, why: str) -> ForegroundAttempt:
        return ForegroundAttempt(
            kind=kind,
            performed=False,
            refused_why=why,
            hwnd=hwnd,
            foreground_before=before,
            foreground_after=_foreground_window(),
            is_iconic=iconic,
        )

    if not _is_alive(hwnd):
        return refused("none", f"句柄已失效（hwnd={hwnd}）")
    if iconic:
        return refused("none", "窗口最小化（IsIconic=True）—— 按纪律不做任何注入")
    visible, why = _window_rect_visible(hwnd)
    if not visible:
        return refused("none", why)
    _require_input(force)

    # ① Alt 轻敲：按住 → 松开 → 静置，然后**只**看 `GetForegroundWindow()`。
    directinput.keyDown("alt")
    _sleep(ALT_TAP_HOLD)
    directinput.keyUp("alt")
    _sleep(ALT_TAP_SETTLE)
    after = _foreground_window()
    if after == hwnd:
        return ForegroundAttempt(
            kind="alt",
            performed=True,
            refused_why="",
            hwnd=hwnd,
            foreground_before=before,
            foreground_after=after,
            is_iconic=iconic,
        )

    # ② 退到标题栏（非客户区）单击 —— 先量带高，再命中测试，两道都过了才落点。
    left, top, right, _bottom = win32gui.GetWindowRect(hwnd)
    _ox, oy = _client_origin(hwnd)
    band = max(0, oy - top)
    if band < TITLEBAR_MIN_BAND_PX:
        return ForegroundAttempt(
            kind="alt",
            performed=True,
            refused_why=f"没有非客户区标题栏（band={band}px，无边框窗口）—— 客户区永不点",
            hwnd=hwnd,
            foreground_before=before,
            foreground_after=after,
            is_iconic=iconic,
        )
    x = (left + right) // 2
    y = top + band // 2
    hit = int(win32gui.WindowFromPoint((int(x), int(y))))
    root = int(win32gui.GetAncestor(hit, win32con.GA_ROOT)) if hit else 0
    if hwnd not in (hit, root):
        return ForegroundAttempt(
            kind="titlebar",
            performed=False,
            refused_why=(
                f"命中测试失败：({x},{y}) 上是 hwnd={hit}/root={root}，不是游戏窗口 —— 一下都不点"
            ),
            hwnd=hwnd,
            foreground_before=before,
            foreground_after=after,
            is_iconic=iconic,
            point=(x, y),
            hit=hit,
            root=root,
        )
    _set_cursor(x, y)
    _sleep(TITLEBAR_MOVE_SETTLE)
    _mouse_click()
    _sleep(TITLEBAR_CLICK_SETTLE)
    return ForegroundAttempt(
        kind="titlebar",
        performed=True,
        refused_why="",
        hwnd=hwnd,
        foreground_before=before,
        foreground_after=_foreground_window(),
        is_iconic=iconic,
        point=(x, y),
        hit=hit,
        root=root,
    )


@dataclass(frozen=True, slots=True)
class ForegroundRecovery:
    """:func:`recover_foreground` 的结果：合成输入流水 + 之后路由的读数。"""

    hwnd: int
    previous: int
    attempts_used: int
    injections: tuple[ForegroundAttempt, ...]
    killed: tuple[int, ...]
    restarts: int
    ok: bool
    seconds: float
    why: str

    def describe(self) -> str:
        state = "成功" if self.ok else "失败"
        head = (
            f"合成输入恢复：{state}（用了 {self.attempts_used} 次、重启 {self.restarts} 次、"
            f"杀进程 {len(self.killed)} 个、{self.seconds:.1f} 秒）"
        )
        lines = [head]
        lines.extend(
            f"  · 第 {i} 次 {shot.describe()}" for i, shot in enumerate(self.injections, 1)
        )
        if self.why:
            lines.append(f"  · {self.why}")
        return "\n".join(lines)


def _log_foreground_recovery(path: Path | None, record: dict[str, object]) -> None:
    """每次实际使用**留一行**（append / LF / UTF-8）。

    日志写不进去**不许**打断实机链（盘满、只读挂载都会让它失败）—— 但也**不许**静默：
    一行 stderr 说明"这一局的焦点没有留痕"。
    """
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError as exc:
        print(f"[置前] 恢复日志写不进去（{path}）：{exc}", file=sys.stderr)


def recover_foreground(
    hwnd: int,
    previous: int = 0,
    *,
    attempts: int = FOREGROUND_RECOVERY_ATTEMPTS,
    force: bool = True,
    relaunch: Callable[[], tuple[int, int]] | None = None,
    log_path: Path | None = FOREGROUND_RECOVERY_LOG,
    trigger: str = "",
) -> ForegroundRecovery:
    """抢不到前台后的**有界**恢复：一次合成输入 → 照原样再走既有路由。

    调用点只有一处（`start_session` 的 `foreground_recovery=True` 分支），而且是
    `_route_to_foreground(force=True)` **已经失败**之后的最后手段。它**不复制**会话逻辑：
    拿回前台之后走的是同一条 `_route_to_foreground`，后面的「观察 / 速度 / 空格」照旧由
    `start_session` 往下执行 —— 这条函数的全部职责就是"把焦点还给游戏"。

    ``relaunch`` 为空 ⇒ **只试一次**：没有干净重启的手段时，重复同一场景换来的只是一堆
    相同的读数（t4 之前那版 v1 就是这样重试了 337 次）。重启之后 `hwnd` 会换成新句柄，
    并且调用方**必须**重新量一次 boot-settle（旧读数已经作废，见 `start_session`）。

    ``trigger`` 是**调用点**给的那条失败读数（既有异常的原话）：它进日志，用来回答
    "这一局为什么动了手" —— 没有它，日志只能证明"注入过"，不能证明"当时真的抢不到"。
    """
    started = _monotonic()
    bound = max(1, int(attempts))
    injections: list[ForegroundAttempt] = []
    killed: list[int] = []
    restarts = 0
    why = ""
    for attempt in range(1, bound + 1):
        shot = _acquire_foreground_by_input(hwnd, force=force)
        injections.append(shot)
        base: dict[str, object] = {
            "when": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "attempt": attempt,
            "attempts_bound": bound,
            "trigger": trigger,
            **shot.as_dict(),
        }
        try:
            routed = _route_to_foreground(hwnd, previous, force=force)
        except ForegroundLostError as exc:
            why = str(exc)
            _log_foreground_recovery(
                log_path,
                dict(base, route_ok=False, why=why, killed=list(killed), restarts=restarts),
            )
            if not shot.performed:
                # 纪律拒绝（最小化 / 句柄失效 / 屏外）：换一次重启也还是同一条读数，立刻停手。
                break
            if attempt >= bound or relaunch is None:
                break
            killed.extend(kill_game())
            wait_until(
                lambda stale=hwnd: not _is_alive(stale),
                timeout=WINDOW_SHOW_SETTLE,
                interval=CONDITION_POLL,
            )
            hwnd, previous = relaunch()
            restarts += 1
            continue
        _log_foreground_recovery(
            log_path, dict(base, route_ok=True, why="", killed=list(killed), restarts=restarts)
        )
        return ForegroundRecovery(
            hwnd=routed,
            previous=previous,
            attempts_used=attempt,
            injections=tuple(injections),
            killed=tuple(killed),
            restarts=restarts,
            ok=True,
            seconds=_monotonic() - started,
            why="",
        )

    front = _foreground_window()
    last = injections[-1] if injections else None
    hit_read = last.describe() if last is not None else "（一次都没走到注入）"
    raise ForegroundLostError(
        f"合成输入也没抢到前台（试了 {len(injections)} 次、重启 {restarts} 次）—— "
        f"hwnd={hwnd}、当前前台={front}（{_window_title(front)!r}）、命中测试={hit_read}"
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
    directory: Path | None = None,
    on_capture_failure: CapturePolicy = "raise",
) -> Match | None:
    """只在 ``roi`` 里找模板：**只抓那一块**再匹配（P2：热路径只读需要的像素）。

    收益量级见 :func:`_grab`：抓图省 2.3%，匹配省 75×（1146.5 ms → 15.3 ms）。

    ``directory`` 是模板目录（缺省 :data:`UI_DIR`）。为什么要这个口子（2026-09-25）：
    阶段 6 的取证要**两套语言的模板**（`tools/probe/sitai_ui/{zh,en}/`），混在一个
    目录里会出现"中文模板匹配到英文界面"这种最难查的假绿。:func:`locate` /
    :func:`load_template` 早就支持 `directory=`，只有这条最常用的入口漏了。

    **抓图失败与"模板不在"是两件事，返回值必须分得开**（t19 修的就是这一条）：

    * 抓图失败（不是前台 / 最小化 / 整块还是近纯色）⇒ 默认抛
      :class:`CaptureFailedError`，消息带模板名、``roi`` 与底层原因 —— 这是
      "看不到"，不是"没有"（P13）。旧口径把两者都写成 ``return None``，
      下游据此继续点，就是最贵的那种假绿。
    * 真没匹配上 ⇒ 返回 ``None``（这是本函数唯一的"没有"）。

    确实按**轮询**语义用（"还没画出来就下一轮再看"）的调用方，显式传
    ``on_capture_failure="miss"`` —— 那一行代码本身就是声明"我知道这一轮抓不到
    不算结论"。别无脑传：它的代价正是上面那条判据。
    """
    try:
        image = screenshot(hwnd, roi=roi)
    except CaptureFailedError as exc:
        if on_capture_failure == "miss":
            return None
        raise CaptureFailedError(
            f"找「{name}」（roi={roi}）时抓图失败：{exc} —— 这是**看不到**，不是**没有**；"
            "要按「不命中」处理请显式传 on_capture_failure='miss'（轮询语义）"
        ) from exc
    found = locate_optional(image, name, threshold=threshold, first_hit=True, directory=directory)
    if found is None:
        return None
    dx, dy = _roi_offset(hwnd, roi)
    return _shift_match(found, dx, dy)


def mouse_drag(
    hwnd: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    *,
    steps: int = 12,
    settle: float = 0.02,
    force: bool = False,
) -> None:
    """按住左键把光标从客户区 ``(x0, y0)`` 拖到 ``(x1, y1)``。

    为什么需要它（2026-09-25 第九遍实测，硬事实）：**注入的滚轮到不了引擎** ——
    `21-rules-window.png` 与滚过一格之后的 `22-rule-sitai-scroll-1.png` **逐字节相同**
    （同 sha256 `414f481b56c870e5`、同 1,934,985 B）。这与本模块早已证实的"键盘注入
    （`keybd_event` / `SendInput`）不被接受"同族；而**移动与点击**是实机反复证明可用的
    通道（本模块只用它）。规则窗右侧就是 scrollbox 的滚动条 ⇒ 拖它。

    与点击/滚轮同一条纪律：先确认游戏在**前台**，再把光标放到起点、确认**真的停到了那里**，
    然后按住 → **分步**移动 → 抬起。分步是必要的：引擎读的是它自己帧里的光标位置，
    一次跳到底它可能只看到起点与终点（甚至只看到抬起那一瞬）。
    """
    _require_input(force)
    live = _live_window(hwnd)
    if _foreground_window() != live:
        raise ForegroundLostError(
            f"要拖动时游戏已经不在前台（游戏 hwnd={hwnd}，前台={_foreground_window()}）"
            "—— 真实鼠标事件会送给前台窗口（用户正在用的那个），已中止"
        )
    _set_cursor(x0, y0)
    if not _wait_cursor_at(x0, y0):
        raise RealInputBlockedError(
            f"光标没能停到拖动起点 ({x0}, {y0}) —— 拖动会从别的地方开始，已中止（P13）"
        )
    directinput.mouseDown()
    try:
        for i in range(1, steps + 1):
            _set_cursor(
                round(x0 + (x1 - x0) * i / steps),
                round(y0 + (y1 - y0) * i / steps),
            )
            _sleep(settle)
    finally:
        # 无论中途出什么事都要抬键 —— 留着按下的左键会把后面每一步都变成拖动。
        directinput.mouseUp()
    if settle:
        _sleep(settle)


def wait_stable(
    hwnd: int,
    *,
    roi: tuple[float, float, float, float],
    timeout: float = STABLE_TIMEOUT,
    interval: float = CONDITION_POLL,
    settle_frames: int = 2,
) -> bool:
    """等 ``roi`` 里的画面**连着 ``settle_frames`` 帧不再变**（返回是否等到）。

    为什么不是"睡一觉"（用户口径：不要直接 sleep）：规则窗里点一下 ‹ › 之后，
    档名与说明是**下一帧**才画出来的；睡固定时长要么不够（读到的还是上一档 ⇒
    把三档取证做成"同一档三张图"这种假绿），要么白等。所以用**帧稳定**当条件。

    判据是"帧间平均差 ≤ :data:`STABLE_DIFF`"（比例），不是"逐像素相同" ——
    界面有动效与抗锯齿，逐像素相同这个条件永远不成立。

    ⚠️ **"一帧都没抓到"不许报"没稳定"**（t19）：那是"看不到"，不是"不稳定"。
    首帧抓不到就继续试到超时，一次都没抓成 ⇒ 抛 :class:`CaptureFailedError`
    并把最后一条原因带上（P13），而不是返回一个下游会当结论的 ``False``。
    循环中途的偶发抓图失败仍按"这一帧不算数"跳过（转场时的近纯色是正常的）。
    """
    deadline = _monotonic() + timeout
    last_error = ""
    before: np.ndarray | None = None
    while before is None and _monotonic() < deadline:
        try:
            before = np.asarray(screenshot(hwnd, roi=roi).convert("L"), dtype=np.int16)
        except CaptureFailedError as exc:
            last_error = str(exc)
            _sleep(interval)
    if before is None:
        raise CaptureFailedError(
            f"{timeout:.0f} 秒内一次都没抓成 {roi} —— 看不到就**判不出稳定不稳定**，"
            f"不能报「没稳定」（那是把「看不到」当结论）；最后一条原因：{last_error or '无'}"
        )
    stable = 0
    while _monotonic() < deadline:
        _sleep(interval)
        try:
            after = np.asarray(screenshot(hwnd, roi=roi).convert("L"), dtype=np.int16)
        except CaptureFailedError:
            continue
        if before.shape != after.shape:
            stable = 0
        else:
            diff = float(np.abs(after - before).mean()) / 255.0
            stable = stable + 1 if diff <= STABLE_DIFF else 0
        before = after
        if stable >= settle_frames:
            return True
    return False


def save_shot(image: Image.Image, tag: str) -> Path:
    """把证据截图落盘（``tools/out/auto/``），返回路径。"""
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SHOT_DIR / f"{tag}.png"
    image.save(path)
    return path


#: 证据帧**没落成**的记录（t19）：:func:`_shot_or_note` 抓不到就往这里写一笔。
#: 为什么要记：证据帧不承载判据，但它少了之后**必须查得出来是哪一步、什么原因** ——
#: 静默 `suppress` 会把一次真的抓图失败变成"那张图本来就不存在"。
CAPTURE_FAULTS: list[str] = []

#: 「抓图失败被吞掉」之处**全清单**（t19 同族扫描）。每项 = ``(函数名, 处置)``。
#:
#: 这张表不是散文：``tests/test_game_auto.py`` 里的
#: ``test_扫描表覆盖了每一个吞掉抓图失败的函数`` 会用 :mod:`ast` 重新枚举源文件里的
#: ``except CaptureFailedError`` / ``suppress(CaptureFailedError)``（按**所在函数**归类）
#: 并与本表逐项对账 —— 于是"以后谁再悄悄吞一处"会当场变红，登记过期也同样变红。
#:
#: 同族但**不吞**、因此不在表里的地方：:func:`find_observe` 只转发（自带
#: ``on_capture_failure`` 参数）、:func:`_step_observe` 的判定在 `did_settle` 里。
#: 另有一条**跨卡**待办：`tools/probe/stage6_ui_rerun.py` 有四处 ``find_in_roi`` 是
#: 轮询语义（转场瞬时空白要继续等，不是"没有"），那四处属 t26 的文件，
#: 要在那边显式写 ``on_capture_failure="miss"``（本卡不改别人的文件）。
CAPTURE_FAMILY_SCAN: tuple[tuple[str, str], ...] = (
    ("find_in_roi", "默认出声（本卡）；'miss' 是调用点上的显式例外"),
    ("wait_stable", "首帧重试到超时；一次都没抓到 ⇒ 抛，不报「没稳定」；循环中途按这一帧不算数"),
    (
        "speed_widget_xy",
        "豁免：下游用**实测速率**兜底，吞掉不会造成假成功（理由在该函数 docstring）",
    ),
    ("_shot_or_note", "证据帧：抓不到不带崩整局，但记进 CAPTURE_FAULTS（哪张图、什么原因）"),
    ("_step_look", "既有的正确样板：按「还没画好」处理，最后把原因写进异常（P13）"),
    ("_step_observe", "内含 did_settle：抓图失败记原因、这一轮算假，最后连原因一起抛"),
    ("did_settle", "同上"),
)


def _shot_or_note(hwnd: int, tag: str) -> Path | None:
    """存一张证据帧；抓不到就记进 :data:`CAPTURE_FAULTS` 并返回 ``None``。

    与 :func:`find_in_roi` 的默认出声不同：证据帧是**附带**的，抓不到不该把整局
    带崩（那样反而丢了后面的取证）；但它也**不许无声无息**。
    """
    try:
        return save_shot(screenshot(hwnd), tag)
    except CaptureFailedError as exc:
        CAPTURE_FAULTS.append(f"{tag}：{exc}")
        return None


def _window_note(hwnd: int, tag: str) -> str:
    """一行窗口/前台状态（失败取证用）。**自己吞掉查询异常**：取证不许把真异常换掉。

    2026-09-30 加（t9 条件授权）：原来失败截图由外层 wrapper 在 `finally` 杀完游戏之后拍，
    画面里已经没有游戏（实测 `前台=cmd`、`victoria3_count=0`），等于没留。现在在异常路径里、
    杀进程**之前**先落一张证据帧（:data:`SHOT_DIR` 下的 ``<tag>.png``），再把这一行打进日志。
    """
    try:
        return (
            f"[失败取证] {tag} hwnd={hwnd} live={_live_window(hwnd)} "
            f"foreground={_foreground_window()} iconic={_is_iconic(hwnd)} "
            f"shot={SHOT_DIR / (tag + '.png')}"
        )
    except Exception as exc:  # 取证是附带的：查不到就照实说，绝不掩盖真正的失败
        return f"[失败取证] {tag} 窗口状态查不到：{exc!r}"


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


def click_client(
    hwnd: int,
    x: int,
    y: int,
    *,
    settle: float = 0.0,
    previous: int = 0,
    force: bool = False,
) -> None:
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

    标准流程里游戏从启动到三下点完一直是前台，所以**不需要** ``previous``；
    它是给**探针**留的口子：探针在自己的一局里连点几个 debug 按钮，点完要把前台还给用户。
    传 ``previous`` 就点完还原，不传就什么都不动 —— **不用一个 `give_back=True` 默认值**，
    因为"默认还前台"与"默认不还"只差一个字符，而后果差很远。
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
    if previous and previous != hwnd:
        _set_foreground(previous)


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
    """从尾部按块找最新 tick；无 tick 时扫描至文件头，内存保持有界。"""
    path = log or TICK_LOG
    try:
        with path.open("rb") as stream:
            stream.seek(0, 2)
            end = stream.tell()
            overlap = b""
            tick = NO_TICK
            while end:
                start = max(0, end - 65536)
                stream.seek(start)
                raw = stream.read(end - start) + overlap
                tick = last_tick_in(raw.decode("utf-8", errors="replace"))
                if tick:
                    break
                # 数字、前缀可跨块；重叠只保留短前缀，不累计整个文件。
                overlap = raw[:256]
                end = start
        mtime = path.stat().st_mtime
    except OSError:
        return TickMark(NO_TICK, 0.0)
    return TickMark(tick, mtime)


def is_running(seconds: float = 6.0, *, log: Path | None = None, sleeper: object = None) -> Advance:
    """时间在推进吗？**用逐 tick 行判定**（暂停不写日志，日志增长不能当判据）。

    ``sleeper`` 与 :func:`wait_until_running` / :func:`wait_for_boot_settle` 同口径，
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


#: 引擎日志的落地目录（用户目录下的 `logs/`）—— 走 `config.USERDIR`：默认路径的解析只有
#: 一处（环境变量优先 → 平台候选 → 确定的回落值），原先这里自己又写了一遍 `V3_USERDIR`
#: 的默认值 + 一个机器专属绝对路径（P9；本文件其它用户目录早就都走 `config.USERDIR`）。
USER_LOGS_DIR = config.USERDIR / "logs"


#: 归档名里的时间戳格式（UTC）：`20260928-231500`。格式只有这一处（P9），用例可注入 `now`。
ARCHIVE_STAMP_FORMAT = "%Y%m%d-%H%M%S"


def archive_stamp(*, now: datetime | None = None) -> str:
    """归档名用的 UTC 时间戳（形如 ``20260928-231500``）。

    为什么由本模块生成：归档名是**判据的一部分**（哪一份属于哪一次会话），两处各写一个
    ``strftime`` 迟早漂移成两个格式；``now`` 可注入，用例不必等真时钟。
    """
    return (now or datetime.now(UTC)).strftime(ARCHIVE_STAMP_FORMAT)


def unused_path(path: Path, *, stamp: str, limit: int = 99) -> Path:
    """返回一个**没被占用**的落地路径：空着就用 ``path`` 本身，被占则把 ``stamp`` 插到扩展名前。

    ``debug.log`` → ``debug.20260928-231500.log``；再冲突 → ``…-2.log``；到 ``limit`` 还冲突就抛
    ``FileExistsError``。**换名或报错，二者必居其一 —— 绝不覆盖**（也不动盘上已有的那一份）。

    为什么必须有这条（t71 / 证据蒸发，两条路径都实测过）：① 目标**文件**已存在时
    ``shutil.move`` 一声不响地**覆盖**它（Windows 上 ``os.rename`` 抛 ``FileExistsError``
    后退回 ``copy2`` + ``unlink``）⇒ 上一代归档件被无声替换，调用方拿到的名字看不出任何异常；
    ② 目标是个**目录**、里面已有同名项时它抛 ``shutil.Error``，而它是 ``OSError`` 的子类 ⇒
    被调用点 ``except OSError`` 的兜底吞掉，文件**留在原地**、悄悄混进下一局的取证。
    原始读数见 ``tools/out/t15-drill/drill.log`` 的 seq7。名字带时间戳之后，同一个目标目录可以
    重复归档任意多代，谁都不覆盖谁、谁也不被留在原地。
    """
    if not path.exists():
        return path
    suffix = path.suffix
    stem = path.name[: -len(suffix)] if suffix else path.name
    for seq in range(1, limit + 1):
        extra = "" if seq == 1 else f"-{seq}"
        candidate = path.with_name(f"{stem}.{stamp}{extra}{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"{path} 与它 {limit} 个带时间戳的候选名都被占用：{path.parent}")


def quarantine_logs(dest: Path | None = None, *, stamp: str | None = None) -> list[str]:
    """把引擎日志挪去临时目录，返回**归档目录里的实际文件名**（没冲突就是原名）。

    为什么每次会话都要挪：`debug.log` 按大小轮转，上一局的尾巴会留在 `debug.1.log`… 里，
    于是"这一局有没有挂上 mod""占槽率是多少"这类取证会**混进上一局的记录**（阶段 4
    实测踩过："原版局看起来也挂了 mod"）。

    ⚠️ **被占用的文件跳过、不报错**（实测两次踩到）：上一次跑批留下的进程会握着
    `ai.log` 的句柄，`shutil.move` 抛 `PermissionError: [WinError 32]`。
    跳过是安全的：判据用到的是 `debug.log` / `system.log` / `error.log`。

    ⚠️ **同名不覆盖**（t71）：目标目录里已经有同名文件时**换名**（``debug.log`` →
    ``debug.20260928-231500.log``，见 :func:`unused_path`）—— 两条证据蒸发路径都堵上：
    同名**文件**已存在时 `shutil.move` 会静默覆盖它（上一代归档件被无声替换），同名项在
    **目录**里时它会抛 `shutil.Error`（`OSError` 的子类）⇒ 被上面那条"跳过被占用"的兜底吞掉、
    文件留在原地混进下一局。默认目标目录 `%TEMP%\\v3_quarantine_logs` 会攒下很多代，
    返回的名字就是去那里读的入口。
    """
    LAST_QUARANTINE_ERRORS.clear()
    target = dest or (Path(tempfile.gettempdir()) / "v3_quarantine_logs")
    target.mkdir(parents=True, exist_ok=True)
    stamp = stamp or archive_stamp()
    moved: list[str] = []
    errors: list[str] = []
    if not USER_LOGS_DIR.is_dir():
        return moved
    for path in sorted(USER_LOGS_DIR.glob("*.log")):
        landing = unused_path(target / path.name, stamp=stamp)
        try:
            shutil.move(str(path), str(landing))
        except (PermissionError, OSError) as exc:
            errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
            continue
        moved.append(landing.name)
    LAST_QUARANTINE_ERRORS.extend(errors)
    return moved


def kill_owned_game() -> list[int]:
    """只终止本模块本次启动的游戏进程及其子进程，并确认它们已退出。"""
    LAST_KILL_ALIVE.clear()
    requested: list[int] = []
    roots = sorted(_OWNED_GAME_PIDS)
    for root_pid in roots:
        pids = [root_pid]
        keep_owned = False
        try:
            process = psutil.Process(root_pid)
            expected = _OWNED_GAME_META.get(root_pid)
            if expected is not None and not _owned_identity_matches(process, expected):
                print(f"跳过 PID {root_pid}：进程身份已变化，拒绝误杀", file=sys.stderr)
                continue
            children = getattr(process, "children", None)
            if callable(children):
                pids.extend(child.pid for child in children(recursive=True))
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            keep_owned = True
            print(f"无法读取本会话游戏进程 {root_pid}：权限不足", file=sys.stderr)
        for pid in reversed(dict.fromkeys(pids)):
            try:
                psutil.Process(pid).kill()
            except psutil.NoSuchProcess:
                continue
            except psutil.AccessDenied:
                print(f"无法终止本会话游戏进程 {pid}：权限不足", file=sys.stderr)
            else:
                requested.append(pid)
        if not keep_owned:
            _OWNED_GAME_PIDS.discard(root_pid)
            _OWNED_GAME_META.pop(root_pid, None)
    alive = _wait_for_pids(requested)
    LAST_KILL_ALIVE.extend(alive)
    if alive:
        print(f"本会话游戏进程在清理等待后仍存活：{alive}", file=sys.stderr)
    return requested


def kill_game() -> list[int]:
    """尝试终止所有同名游戏进程，返回已发出终止请求的 PID 列表。

    为什么收进这个模块：会话收尾**必须**做到"不留进程"—— 留一个进程会握着
    ``logs/*.log`` 的句柄（`shutil.move` 抛 `WinError 32`），下一次会话的取证
    还会混进它的残留。而 ``tools/probe/`` 下每个探针都各抄了一份 ``_kill_game``；
    收成一处，这条纪律才守得住（探针只负责调用）。

    使用 psutil，进程已退出时略过；权限不足时明确出声，不能把失败写成已终止。
    返回值表明请求已发出，不代替调用方对进程实际退出的验证。
    """
    requested: list[int] = []
    for pid in _process_pids():
        try:
            psutil.Process(pid).kill()
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            print(f"无法终止游戏进程 {pid}：权限不足", file=sys.stderr)
        else:
            requested.append(pid)
    alive = _wait_for_pids(requested)
    if alive:
        print(f"游戏进程在清理等待后仍存活：{alive}", file=sys.stderr)
    return requested


def platform_capabilities() -> dict[str, object]:
    """返回当前平台可用的自动化能力，不触碰窗口或输入设备。"""
    windows = sys.platform == "win32"
    return {
        "platform": sys.platform,
        "gui_automation": windows,
        # 后台验证需要窗口与输入后端；非 Windows 只支持日志/tick 的无头验证。
        "background_validation": windows,
        "headless_log_validation": True,
        "reason": (
            "Windows GUI backend: pygetwindow + pydirectinput"
            if windows
            else "当前平台没有受支持的 Victoria 3 GUI 输入后端"
        ),
    }


def launch(
    *,
    scripted_tests: bool = True,
    debug: bool = True,
    extra_args: tuple[str, ...] = (),
    wait: bool = True,
    timeout: float = WINDOW_TIMEOUT,
) -> int | None:
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

    ``wait=False`` 返回 ``None``，与 :func:`find_window` 的 ``0`` 哨兵区分开；
    调用方不会再把“没有等待窗口”误判成“窗口不存在”。
    """
    assert_no_game_running()
    command = experiments.launch_command(debug=debug)
    if scripted_tests:
        command.append(SCRIPTED_TESTS_ARG)
    command.extend(extra_args)
    if not Path(command[0]).is_file():
        raise GameAutoError(f"找不到游戏可执行文件：{command[0]}")
    process = subprocess.Popen(command, cwd=str(config.ROOT), close_fds=True)
    pid = getattr(process, "pid", None)
    if isinstance(pid, int) and pid > 0:
        _OWNED_GAME_PIDS.add(pid)
        _OWNED_GAME_META[pid] = _capture_process_identity(pid)
    if not wait:
        return None
    if isinstance(pid, int):
        try:
            return wait_for_window(timeout=timeout, pid=pid)
        except TypeError as exc:
            # 兼容旧的注入桩（只接受 timeout），真实实现仍会按 PID 过滤窗口。
            if "pid" not in str(exc):
                raise
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
    force: bool = False,
) -> Advance:
    """把前台让给别的窗口，验证**模拟是否继续**（实测：是）。

    意义：点火之后就不必让游戏一直占着前台 —— 轮询可以完全在后台做。

    ``force`` 只应由显式 CLI/实机流程开启；它把用户已经授权的前台切换
    传给输入安全闸门。默认 ``False``，这样库调用不会悄悄抢占用户桌面。
    """
    other = other_window(hwnd)
    if not other:
        raise GameAutoError("找不到可用的非游戏窗口来让出前台 —— 无法验证后台模拟")
    before = tick_mark(log)
    ensure_foreground(other, force=force)
    _sleep(2.0)
    if _foreground_window() == hwnd:  # pragma: no cover - 抢不走的极端情况
        raise ForegroundLostError("没能把前台让出去，后台结论不可信")
    # 真实游戏会在启动期重建窗口；有进程时必须重新确认句柄仍然有效。
    if _process_pids():
        hwnd = _live_window(hwnd)
    _sleep(seconds)
    if _process_pids():
        hwnd = _live_window(hwnd)
    after = tick_mark(log)
    if restore:
        ensure_foreground(hwnd, force=force)
    return Advance(
        advanced=is_later(before.tick, after.tick),
        before=before.tick,
        after=after.tick,
        seconds=seconds,
        source=f"后台（前台让给 hwnd={other}）",
    )


# ── 路线 A 的后两步：等官方套件判定 + 读它的产物 ──────────────────────
#
# `自动化范式.md` §6 那张闭环图的**后两步原先一直是手动的**：等 `-scripted_tests`
# 自己判定并落盘、读 `tests.txt` 与 `binaries/*_GameTests_testoutput.xml`。
# 这一段把它们补上。判据全部来自**引擎自己写的文件** —— 本模块只解析、不判分
# （自己判分就是假红/假绿的来源，见模块头）。

#: 官方 harness 的**文本**成绩单（**仓库外**：用户目录）。原文样例见 `自动化范式.md` §1.2。
TESTS_TXT = config.USERDIR / "tests.txt"

#: 官方 harness 的**机器可读**成绩单（**仓库外**：游戏安装目录 `binaries/`）。
#: 文件名带随机 uuid ⇒ 每局都是新文件，只能靠"点火之前它不存在"来认。
TESTOUTPUT_GLOB = "*_GameTests_testoutput.xml"

#: 判定"这条 error.log 是不是在说我们"的标记：
#: `sitai_` 覆盖脚本 / 本地化 / 策略键名（F7 命名空间），`SITAI` 覆盖 mod 名本身。
OUR_MARKS: tuple[str, ...] = (config.NAMESPACE_PREFIX, "SITAI")

#: 等成绩单"写完"的轮询间隔与要求：引擎是**先建文件、再写内容**。
#: 判据用"大小连续两次不变"，不是"睡一觉"（用户口径：等状态一律条件等待）。
VERDICT_STABLE_POLL = 0.5


def binaries_dir() -> Path:
    """游戏安装目录下的 ``binaries/`` —— 官方成绩单唯一会落的地方。"""
    return config.ROOT / "binaries"


def error_log_path() -> Path:
    """用户目录下的 ``logs/error.log`` —— "有没有我们的报错"唯一的真值来源。"""
    return config.USERDIR / "logs" / "error.log"


def rotated_logs(base: Path, stem: str) -> list[Path]:
    """引擎的**轮转日志**，按时间从旧到新：``<stem>.N.log``（N 大在前）+ ``<stem>.log``。

    ⚠️ **不许直接 `sorted()`**（实测踩过两次，backlog **B85**）：轮转副本叫
    ``debug.1.log`` …，当前那份叫 ``debug.log`` —— 字典序把**当前那份排在最后、
    次新的排在最前**，拼出来的文本时间顺序是错的，再叠上"按标记切片"就会读出一段
    **不连续的切片**（实测：盘上 1,401 行只读了 402 行，还报出一个假的窗口翻转顺序）。

    第二次踩是在 **`error.log`** 上：`read_verdict` 只读了 `error.log` 那一份，
    于是那些被轮转进 `error.1.log` 的行读不到 —— **"我们在 error.log 里没看到"被当成了
    "这一局我们没有报错"**。两处现在共用这一条排序规则。
    """
    numbered = sorted(
        (p for p in base.glob(f"{stem}.[0-9]*.log") if p.stem.rsplit(".", 1)[-1].isdigit()),
        key=lambda p: -int(p.stem.rsplit(".", 1)[-1]),
    )
    current = [base / f"{stem}.log"]
    return [*numbered, *(p for p in current if p.is_file())]


def error_logs() -> list[Path]:
    """``error.log`` 及其轮转副本，按时间从旧到新（判据口径见 :func:`rotated_logs`）。"""
    return rotated_logs(error_log_path().parent, "error")


#: `error.log` 里**已知无害**的那一类：JE 的 `_goal` 槽被引擎判成 redundant。
#:
#: 口径见 backlog **B74**（已实测并定过口径）：「上屏」以 `_reason` 为准，`_goal` 只当加分项 ——
#: 原版自己也大量用 `je_*_goal`，这句 `redundant` 取决于 JE 形态，**不是我们的缺陷**。
#: 实测：九份档案各一行，每次装载都会写一遍。
#:
#: ⚠️ **这是"分类"，不是"忽略"**（P13）：带我们命名空间的**其他**任何一行照样算失败；
#: 而且这一类的条数会照实报出来（`SuiteVerdict.benign_errors`），不是藏起来。
BENIGN_ERROR_RE = re.compile(r"Journal entry has redundant loc for \w+_goal\b")


def our_error_lines(text: str) -> tuple[str, ...]:
    """``error.log`` 里**属于我们命名空间**的行（其余是原版噪音），**不含已知无害的那一类**。

    为什么必须自己数这一遍：harness 那行 ``[ FAIL ] Error log: N errors`` 数的是
    **整份** error.log，而原版自己就有几十条（实测 85 条）⇒ 照它判**每次假红**。
    已知无害的那一类见 :data:`BENIGN_ERROR_RE`（由 :func:`benign_error_lines` 单独报）。
    """
    return tuple(
        line
        for line in text.splitlines()
        if any(mark in line for mark in OUR_MARKS) and not BENIGN_ERROR_RE.search(line)
    )


def benign_error_lines(text: str) -> tuple[str, ...]:
    """带我们命名空间、但**属于已知无害**那一类的行（B74：`_goal` 槽 redundant）。

    单独列出来是为了让"分类"看得见 —— 读数里会同时报"我们的报错 N 条"与
    "已知无害 M 条"，而不是把 M 悄悄减掉。
    """
    return tuple(
        line
        for line in text.splitlines()
        if any(mark in line for mark in OUR_MARKS) and BENIGN_ERROR_RE.search(line)
    )


def testoutput_files() -> list[Path]:
    """``binaries/`` 下已有的官方成绩单，按 mtime 从旧到新。"""
    root = binaries_dir()
    if not root.is_dir():
        return []
    return sorted(
        (p for p in root.glob(TESTOUTPUT_GLOB) if p.is_file()),
        key=lambda p: (p.stat().st_mtime, p.name),
    )


def _int_attr(node: ET.Element, key: str, default: int) -> int:
    """读一个整数属性；**缺**就用 ``default``，**有但不是数**就报错（P13，不猜）。"""
    raw = node.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise GameAutoError(f"官方成绩单里 {key}={raw!r} 不是整数") from exc


def _suite_counts(suite: ET.Element) -> tuple[int, int, int]:
    """一个套件的 ``(tests, failures, errors)``。

    优先用官方写在属性上的数（那是引擎自己的计数）；属性缺了就**数子元素** ——
    两种来源都在官方格式里，谁在就用谁，不混着加（混着加会重复计数）。
    """
    cases = suite.findall("testcase")
    tests = _int_attr(suite, "tests", len(cases))
    failures = _int_attr(suite, "failures", sum(1 for c in cases if c.find("failure") is not None))
    errors = _int_attr(suite, "errors", sum(1 for c in cases if c.find("error") is not None))
    return tests, failures, errors


def parse_testoutput(path: Path) -> tuple[tuple[str, ...], int, int, int]:
    """解析官方 XML 成绩单 → ``(套件名, tests, failures, errors)``。

    只认官方那一种结构（``<testsuites>`` → ``<testsuite name=…>`` → ``<testcase>``）：
    根元素不对就**报错**，不按"猜一个"的方式往下走（P13）。
    """
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:  # pragma: no cover - 文件存在但读不了（权限/占用）
        raise GameAutoError(f"读不了官方成绩单 {path}：{exc}") from exc
    except ET.ParseError as exc:
        raise GameAutoError(f"官方成绩单 {path} 不是合法 XML：{exc}") from exc
    if root.tag != "testsuites":
        raise GameAutoError(f"{path.name} 的根元素是 <{root.tag}>，不是 <testsuites> —— 格式变了")
    suites: list[str] = []
    tests = failures = errors = 0
    for suite in root.findall("testsuite"):
        suites.append(suite.get("name") or "（无名套件）")
        one_tests, one_failures, one_errors = _suite_counts(suite)
        tests += one_tests
        failures += one_failures
        errors += one_errors
    return tuple(suites), tests, failures, errors


@dataclass(slots=True)
class SuiteVerdict:
    """一次 ``-scripted_tests`` 会话的判定结果（**引擎判的**，这里只解析）。"""

    xml: Path
    suites: tuple[str, ...]
    tests: int
    failures: int
    errors: int
    our_errors: tuple[str, ...]
    #: 带我们命名空间、但**已知无害**的那些行（B74：`_goal` 槽 redundant）。
    #: **照实报出来**，不是悄悄减掉 —— 分类与忽略是两件事（P13）。
    benign_errors: tuple[str, ...]
    #: ``error.log`` 到底读没读到。**读不到 ≠ 没有我们的错** —— 两者必须分开
    #: （与 :data:`NO_TICK` 同一条纪律），所以它是 :attr:`ok` 的一部分。
    error_log_read: bool
    tests_txt: str

    @property
    def ok(self) -> bool:
        """三条同时成立才算过：套件真的跑了 · 引擎没判失败 · error.log 里没有我们。

        「套件真的跑了」这一条不能省：``failures == 0 and errors == 0`` 在
        **一个套件都没跑**时也为真 —— 那是最危险的一种"绿"。
        ``benign_errors`` **不参与**判定（它们是已知无害的那一类，口径见 B74），
        但会照实打印出来。
        """
        return (
            bool(self.suites)
            and self.failures == 0
            and self.errors == 0
            and self.error_log_read
            and not self.our_errors
        )

    def describe(self) -> str:
        head = "通过 ✅" if self.ok else "不通过 ❌"
        lines = [
            f"官方套件判定  : {head}",
            f"  成绩单      : {self.xml.name}（{len(self.suites)} 个套件 / {self.tests} 个用例）",
            f"  引擎判定    : failures={self.failures} errors={self.errors}",
        ]
        if self.suites:
            # 套件名要打出来：出问题时第一个要回答的就是"跑的是哪一份套件"。
            lines.append("  套件        : " + "、".join(self.suites[:4]))
        if not self.suites:
            lines.append("  ⚠️ 一个套件都没跑 —— 这种『零失败』不算通过")
        if not self.error_log_read:
            lines.append("  ⚠️ 读不到 error.log ⇒ 无法确认有没有我们的报错 ⇒ 不算通过")
        elif self.our_errors:
            lines.append(f"  我们的报错  : {len(self.our_errors)} 条（error.log 里含 {OUR_MARKS}）")
            lines.extend(f"    {line[:160]}" for line in self.our_errors[:5])
        else:
            lines.append("  我们的报错  : 0 条")
        if self.benign_errors:
            lines.append(
                f"  已知无害    : {len(self.benign_errors)} 条（JE 的 `_goal` 槽 redundant，"
                "口径见 backlog B74 —— 上屏以 `_reason` 为准）"
            )
        if self.tests_txt:
            tail = [ln for ln in self.tests_txt.splitlines() if ln.strip()][-3:]
            lines.append("  tests.txt   : " + " | ".join(tail))
        return "\n".join(lines)

    def as_dict(self) -> dict[str, object]:
        """扁平化（CLI 打印 / 探针记档用）—— 与 :meth:`SessionStart.as_dict` 同款。"""
        return {
            "suite_xml": self.xml.name,
            "suite_count": len(self.suites),
            "suite_names": "、".join(self.suites),
            "suite_tests": self.tests,
            "suite_failures": self.failures,
            "suite_errors": self.errors,
            "suite_our_errors": len(self.our_errors),
            "suite_benign_errors": len(self.benign_errors),
            "suite_error_log_read": self.error_log_read,
            "suite_ok": self.ok,
        }


def read_verdict(xml: Path) -> SuiteVerdict:
    """把一局的判定产物读成结论（**只读**，不改任何东西）。

    ⚠️ ``error.log`` 要读**整组**（含轮转副本），不能只读当前那一份 —— 实测踩过（B85 的
    第二次）：只读 `error.log` 时，被轮转进 `error.1.log` 的行读不到，于是
    **"我们在 error.log 里没看到"被当成了"这一局我们没有报错"**
    （同一局的两种读法给出 0 条与 9 条）。
    """
    suites, tests, failures, errors = parse_testoutput(xml)
    logs = error_logs()
    text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in logs)
    return SuiteVerdict(
        xml=xml,
        suites=suites,
        tests=tests,
        failures=failures,
        errors=errors,
        our_errors=our_error_lines(text),
        benign_errors=benign_error_lines(text),
        error_log_read=bool(logs),
        tests_txt=TESTS_TXT.read_text(encoding="utf-8-sig") if TESTS_TXT.is_file() else "",
    )


def _wait_size_stable(path: Path, *, timeout: float, poll: float = VERDICT_STABLE_POLL) -> None:
    """等文件**写完**：大小连续两次相同（引擎先建文件、再写内容）。

    为什么不能只看"文件在不在"：实测那一下能读到**半截** XML，解析失败会让人
    以为是格式变了 —— 其实只是还没写完。
    """
    last = -1

    def stable() -> bool:
        nonlocal last
        try:
            size = path.stat().st_size
        except OSError:  # pragma: no cover - 刚被挪走/占用
            return False
        done = size > 0 and size == last
        last = size
        return done

    if not wait_until(stable, timeout=timeout, interval=poll):
        raise GameAutoError(f"{path.name} 在 {timeout:.0f} 秒内没写完（大小一直在变）")


def wait_for_testoutput(
    known: frozenset[Path] = frozenset(), *, timeout: float, poll: float = POLL_INTERVAL
) -> Path:
    """等官方写出**新的**成绩单，并等它写完。

    ``known`` 是点火**之前**就存在的那批文件。引擎每局换一个新 uuid，
    所以"出现了一个 ``known`` 里没有的文件"才是可靠判据 —— 只看"最新的那个"会把
    上一局留下的成绩单当成这一局的。
    """
    fresh: list[Path] = []

    def appeared() -> bool:
        found = [p for p in testoutput_files() if p not in known]
        fresh[:] = found
        return bool(found)

    if not wait_until(appeared, timeout=timeout, interval=poll):
        raise GameAutoError(
            f"{timeout:.0f} 秒内没等到新的官方成绩单（{binaries_dir()}\\{TESTOUTPUT_GLOB}）—— "
            "套件没跑起来？先看 tests.txt 与引擎日志"
        )
    xml = fresh[-1]
    _wait_size_stable(xml, timeout=timeout)
    return xml


def wait_for_verdict(known: frozenset[Path] = frozenset(), *, timeout: float) -> SuiteVerdict:
    """**闭环的最后一步**：等套件判定 → 读产物 → 给结论。"""
    return read_verdict(wait_for_testoutput(known, timeout=timeout))


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

    （t19 的同族扫描把这一处**记为豁免**：它与 :func:`find_in_roi` 的区别是
    "有没有能力自证失败"——这里返回的是"坐标不知道"，而速率兜底会把真实速率
    **实测**出来；那条实测就是这一处的判据，抓图失败不会让它变成假绿。）
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


# ────────────────────────── 会话流程：起游戏 → 观察/按键 → 切回后台 ──────────────────────────


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
    #: 后台继续模拟的证据（`background_ok(..., restore=False)`）—— 只有要求
    #: 等判定时才会填：等判定意味着"要相信后台真的在跑"。
    background: Advance | None = None
    #: 官方套件的判定（**引擎自己判的**）—— 只有要求等判定时才会填。
    verdict: SuiteVerdict | None = None
    #: 标准流程的不可变阶段轨迹，便于实机报告定位最后完成的步骤。
    trace: AutomationTrace | None = None
    #: 使用键盘速度快捷键时记录实际按键；旧的鼠标路径为 ``None``。
    speed_key: str | None = None

    def as_dict(self) -> dict[str, object]:
        """扁平化（CLI 打印 / 探针记档用）。"""
        out: dict[str, object] = {
            "hwnd": self.hwnd,
            "previous": self.previous,
            "boot_settle": self.settle.why,
            "observe": self.observe.describe(),
            "speed_source": self.speed_source,
            "speed_xy": "" if self.speed_xy is None else f"{self.speed_xy[0]},{self.speed_xy[1]}",
            "speed_key": self.speed_key or "",
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
        if self.background is not None:
            out["background"] = self.background.describe()
            out["background_advanced"] = self.background.advanced
        if self.verdict is not None:
            out.update(self.verdict.as_dict())
        if self.trace is not None:
            out["automation_phase"] = self.trace.current.value
            out["automation_phases"] = cast("list[str]", self.trace.as_dict()["phases"])
        return out


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
    if hwnd is None:  # pragma: no cover - wait=True 总是返回句柄
        raise WindowNotFoundError("启动后未取得游戏窗口句柄")
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
            # 同 `ensure_foreground`：**最小化的窗口"是前台"也是假的** —— 客户区 0x0，
            # 屏幕抓取只会得到"客户区尺寸非法"（t29 warmup-01 就是这么烧掉 180 秒的）。
            _require_foreground_usable(hwnd)
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


#: 光标停靠（cursor park）的日志（一行一次，append-only）—— 与
#: :data:`FOREGROUND_RECOVERY_LOG` 同一风格，都在 `tools/out` 这个证据区。
CURSOR_PARK_LOG = config.OUT / "cursor-park.jsonl"

#: 停靠点与 ROI 之间至少留的像素：ROI 按这个值外扩成"禁区"，落点必须在禁区外。
CURSOR_PARK_MARGIN = 24

#: 停靠之后静置多久（让界面把上一处 hover 的 tooltip 收回去）再抓确认帧。
CURSOR_PARK_SETTLE = 0.35


@dataclass(frozen=True, slots=True)
class CursorPark:
    """一次「光标停靠」的结果 —— 只移不点，带够证据。

    ``performed=False`` 表示**一次都没移**（句柄失效 / 没有合格落点），它与"移了但落点
    仍在禁区里"必须分开记：前者是"没做"，后者是"做了没用"。
    """

    hwnd: int
    roi: tuple[float, float, float, float]
    performed: bool
    kind: str
    point: tuple[int, int] | None
    cursor_before: tuple[int, int] | None
    moved: bool
    clear_of_roi: bool
    shot: bool
    why: str

    def describe(self) -> str:
        """一行读数（报告与异常消息都用它，措辞即证据面的词汇）。"""
        point = "未落坐标" if self.point is None else f"落点=({self.point[0]},{self.point[1]})"
        before = (
            "读不到"
            if self.cursor_before is None
            else f"({self.cursor_before[0]},{self.cursor_before[1]})"
        )
        return (
            f"停靠[{self.kind}]：{point}、移动={'是' if self.moved else '否'}、"
            f"光标原位置={before}、落点在 ROI 外={self.clear_of_roi}、"
            f"落帧={'是' if self.shot else '否'}（{self.why}）"
        )

    def as_dict(self) -> dict[str, object]:
        """日志行主体（字段名固定，便于事后按 kind/clear_of_roi 过滤）。"""
        return {
            "kind": self.kind,
            "performed": self.performed,
            "hwnd": self.hwnd,
            "roi": list(self.roi),
            "point": list(self.point) if self.point else None,
            "cursor_before": list(self.cursor_before) if self.cursor_before else None,
            "moved": self.moved,
            "clear_of_roi": self.clear_of_roi,
            "shot": self.shot,
            "why": self.why,
        }


def _log_cursor_park(path: Path | None, record: dict[str, object]) -> None:
    """每次调用**留一行**（append / LF / UTF-8）—— 口径同 :func:`_log_foreground_recovery`。"""
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError as exc:
        print(f"[光标停靠] 日志写不进去（{path}）：{exc}", file=sys.stderr)


def _virtual_screen() -> tuple[int, int, int, int]:
    """虚拟屏（多显示器）的 ``(left, top, right, bottom)``，屏幕坐标。"""
    left = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
    top = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
    width = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
    height = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
    return left, top, left + width, top + height


def _cursor_pos() -> tuple[int, int]:
    """当前光标的屏幕坐标（读不到就抛 —— 调用方自己决定怎么记）。"""
    x, y = win32gui.GetCursorPos()
    return int(x), int(y)


def _roi_screen_box(hwnd: int, roi: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    """相对 ROI（0~1）换算成**屏幕**像素框 —— 先按客户区尺寸算，再加客户区原点。"""
    width, height = _client_size(hwnd)
    left, top, right, bottom = roi_box(roi, width, height)
    origin_x, origin_y = _client_origin(hwnd)
    return left + origin_x, top + origin_y, right + origin_x, bottom + origin_y


def _park_candidates(
    box: tuple[int, int, int, int], client_top: int, *, margin: int
) -> list[tuple[str, tuple[int, int]]]:
    """按「离 ROI 越远越优先」给出停靠候选（屏幕坐标）。

    顺序的理由：底部条这类 ROI 的**上方**是大地图，而地图的 hover tooltip 往**下**长
    （2026-10-01 实测：鼠标停在大西洋上，省份 tooltip 一直铺到 y≈1080，把「观察」的左半
    盖住 ⇒ 模板匹配从 1.000 掉到 0.5665）。所以第一个候选是**客户区最上沿居中** —— 离得
    最远、tooltip 再长也够不着；其后才是 ROI 上/下/左/右的空处。
    """
    left, top, right, bottom = box
    center_x = (left + right) // 2
    center_y = (top + bottom) // 2
    return [
        ("client-top", (center_x, client_top + margin)),
        ("above-roi", (center_x, top - margin - 1)),
        ("below-roi", (center_x, bottom + margin + 1)),
        ("left-of-roi", (left - margin - 1, center_y)),
        ("right-of-roi", (right + margin + 1, center_y)),
    ]


def find_observe(
    hwnd: int,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    on_capture_failure: CapturePolicy = "raise",
) -> Match | None:
    """只抓底部条、找「观察」按钮 —— **找不到返回 ``None``**（不抛），供自适应调用。

    ⚠️ 这里的"找不到"只指**真没匹配上**（t19）：抓图失败默认沿 :func:`find_in_roi`
    的出声口径；只有显式 ``on_capture_failure="miss"`` 才退化成 ``None``。
    """
    return find_in_roi(
        hwnd,
        "btn_observe",
        roi=BOTTOM_ROI,
        threshold=threshold,
        on_capture_failure=on_capture_failure,
    )


def park_cursor_clear_of(
    hwnd: int,
    roi: tuple[float, float, float, float],
    *,
    margin: int = CURSOR_PARK_MARGIN,
    settle: float = CURSOR_PARK_SETTLE,
    confirm_shot: bool = True,
    shot_tag: str = "00-cursor-park",
    log_path: Path | None = CURSOR_PARK_LOG,
    why: str = "",
) -> CursorPark:
    """把光标停到**不可能遮住 ``roi``** 的地方 —— 等按钮类 ROI 之前的正式前置步骤。

    为什么要有这一步（2026-10-01 实机第一次撞上，不是假想）：:func:`_step_look` 靠模板匹配
    底部条上的「观察」按钮，而鼠标停在大地图上时游戏会画一块**几百像素高的省份 tooltip**；
    那次它一直铺到 y≈1080，把「观察」的左半盖住 ⇒ 同款匹配从 1.000 掉到 0.5665
    （< :data:`DEFAULT_THRESHOLD`），600 秒预算全打空、整批热身失败。同一晚同一屏的对照帧
    仍是 1.000 ⇒ 与模板/阈值/ROI **无关**，要修的是环境：等按钮之前先把光标挪开。

    纪律：

    * **只移不点**：一次 ``SetCursorPos``，没有按下、没有拖动、没有键盘；
    * **有界**：至多一次移动 + 一张确认帧（``confirm_shot``），失败不重试；
    * **可追溯**：每次调用往 :data:`CURSOR_PARK_LOG` 写一行（落点 / 光标原位置 / 是否在
      ROI 外 / 是否落帧 / 原因）；写不进去只报一行 stderr，不打断实机链（口径同
      :func:`_log_foreground_recovery`）；
    * **不碰判据**：模板名、阈值、ROI、``lobby_timeout`` 与 :func:`find_observe` 的语义都
      不因它改变 —— 它只把环境摆正。

    停靠失败（句柄失效 / 没有合格落点）**不抛异常**：它只是前置整理，真正的判据仍在
    :func:`_step_look` 里；但会原样记进返回值与日志（P13：失败要出声）。
    """
    try:
        cursor_before: tuple[int, int] | None = _cursor_pos()
    except Exception:  # pragma: no cover - 读光标失败极罕见，不因此中断实机链
        cursor_before = None

    base: dict[str, object] = {
        "at": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "hwnd": hwnd,
        "roi": list(roi),
        "cursor_before": list(cursor_before) if cursor_before else None,
        "reason": why,
    }

    def finish(
        *,
        kind: str,
        performed: bool,
        point: tuple[int, int] | None,
        clear: bool,
        shot: bool,
        moved: bool = False,
        why_text: str = "",
    ) -> CursorPark:
        park = CursorPark(
            hwnd=hwnd,
            roi=roi,
            performed=performed,
            kind=kind,
            point=point,
            cursor_before=cursor_before,
            moved=moved,
            clear_of_roi=clear,
            shot=shot,
            why=why_text,
        )
        _log_cursor_park(log_path, {**base, **park.as_dict()})
        return park

    try:
        alive = _is_alive(hwnd)
    except Exception:  # 查询失败就是"窗口不在了"：前置整理不许把整局带崩
        alive = False
    if not alive:
        return finish(
            kind="none",
            performed=False,
            point=None,
            clear=False,
            shot=False,
            why_text=f"句柄已失效（hwnd={hwnd}）—— 一次都没移",
        )

    try:
        box = _roi_screen_box(hwnd, roi)
        client_top = _client_origin(hwnd)[1]
    except Exception as exc:  # 假句柄 / 窗口正在销毁：记实话，一次都不移
        return finish(
            kind="none",
            performed=False,
            point=None,
            clear=False,
            shot=False,
            why_text=f"取窗口几何失败：{exc!r} —— 一次都没移",
        )
    guard = (box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin)
    screen_left, screen_top, screen_right, screen_bottom = _virtual_screen()

    chosen: tuple[str, tuple[int, int]] | None = None
    for kind, (x, y) in _park_candidates(box, client_top, margin=margin):
        if x < screen_left or y < screen_top or x >= screen_right or y >= screen_bottom:
            continue
        if guard[0] <= x <= guard[2] and guard[1] <= y <= guard[3]:
            continue
        chosen = (kind, (x, y))
        break

    if chosen is None:
        return finish(
            kind="none",
            performed=False,
            point=None,
            clear=False,
            shot=False,
            why_text=f"没有合格落点（ROI 屏幕框={box}、留白={margin}px）—— 一次都没移",
        )

    kind, point = chosen
    moved = cursor_before != point
    _set_cursor(point[0], point[1])
    if settle > 0:
        _sleep(settle)
    shot = False
    if confirm_shot:
        try:
            shot = _shot_or_note(hwnd, shot_tag) is not None
        except Exception as exc:  # pragma: no cover - 落帧是附带的，不该打断实机链
            print(f"[光标停靠] 确认帧没做成：{exc!r}", file=sys.stderr)
    return finish(
        kind=kind,
        performed=True,
        point=point,
        clear=True,
        shot=shot,
        moved=moved,
        why_text=why or f"挪出 [{box}] 外扩 {margin}px 的禁区（hover tooltip 会盖住它）",
    )


def _step_look(
    hwnd: int,
    *,
    threshold: float,
    lobby_timeout: float = LOOK_TIMEOUT,
    force: bool = False,
    auto_new_game: bool = True,
) -> tuple[Match, int]:
    """① 确认「观察」出现；返回 ``(匹配, 当前句柄)``。

    频率自己负责（P2）：只抓底部条 :data:`BOTTOM_ROI`，抓图间隔从
    :data:`CAPTURE_INTERVAL_START` 按 :data:`CAPTURE_INTERVAL_GROWTH` 放慢到
    :data:`CAPTURE_INTERVAL_MAX` —— 不是固定 2 秒整屏抓，也不是每个尺度都试
    （``first_hit=True``：一个可信命中就够）。

    普通主菜单没有「观察」按钮时，默认在已证的 :data:`MAIN_MENU_ROI` 内寻找
    「新游戏」并点击一次，再继续等待观察者按钮；`auto_new_game=False` 保留
    旧的观察者局入口。新游戏的点击也必须经过模板命中，绝不退化成盲点坐标。

    抓图失败按"还没画好"处理并**记下最后一条错误**：界面在切换时会短暂近纯色，
    那不是失败；但一直在失败就必须把原因带进异常里（P13），否则只剩一句"没找到"。
    """
    tick_clock: Clock = _monotonic
    hwnd = _ensure_live_foreground(hwnd)
    # 前置整理：先把光标挪出底部条 —— 鼠标停在地图上时，那块几百像素高的省份 tooltip 会把
    # 「观察」盖住（2026-10-01 实测：匹配 1.000 → 0.5665、600 秒预算全打空）。只移不点、
    # 有界；没做成也**不抛**，真正的判据仍是下面这个循环。
    park = park_cursor_clear_of(
        hwnd, BOTTOM_ROI, why="等「观察」按钮之前：地图 hover tooltip 会盖住底部条"
    )
    if not park.performed:
        print(f"[光标停靠] 没做成：{park.why}", flush=True)
    deadline = tick_clock() + lobby_timeout
    interval = CAPTURE_INTERVAL_START
    last_error = ""
    new_game_clicked = False
    setup_clicked = False
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

        if new_game_clicked and not setup_clicked:
            try:
                setup = screenshot(hwnd, roi=SETUP_START_ROI)
                start_game = locate_optional(
                    setup,
                    "btn_start_game",
                    threshold=START_GAME_THRESHOLD,
                    first_hit=True,
                )
            except CaptureFailedError as exc:
                last_error = str(exc)
                start_game = None
            if start_game is not None:
                dx, dy = _roi_offset(hwnd, SETUP_START_ROI)
                shifted = _shift_match(start_game, dx, dy)
                click_match(hwnd, shifted, force=force)
                _shot_or_note(hwnd, "09-start-game-click")
                setup_clicked = True
                # 设置页到国家/观察者界面也可能经过一段载入，重新给完整预算。
                deadline = tick_clock() + lobby_timeout
                interval = CAPTURE_INTERVAL_START
                continue

        if auto_new_game and not new_game_clicked:
            try:
                menu = screenshot(hwnd, roi=MAIN_MENU_ROI)
                new_game = locate_optional(
                    menu,
                    "btn_new_game",
                    threshold=NEW_GAME_THRESHOLD,
                    first_hit=True,
                )
            except CaptureFailedError as exc:
                last_error = str(exc)
                new_game = None
            if new_game is not None:
                dx, dy = _roi_offset(hwnd, MAIN_MENU_ROI)
                shifted = _shift_match(new_game, dx, dy)
                click_match(hwnd, shifted, force=force)
                _shot_or_note(hwnd, "09-new-game-click")
                new_game_clicked = True
                # 点击后重新给完整大厅预算，加载期不因主菜单等待耗尽而误报。
                deadline = tick_clock() + lobby_timeout
                interval = CAPTURE_INTERVAL_START
                continue
        _sleep(interval)
        interval = min(interval * CAPTURE_INTERVAL_GROWTH, CAPTURE_INTERVAL_MAX)
    # 失败取证（2026-09-30 t9 条件授权）：**在异常路径里、杀进程之前**落一张证据帧 + 一行窗口状态。
    # 这张证据原先由外层 wrapper 在 `finally` 杀完游戏之后拍，画面里已经没有游戏（实测
    # `前台=cmd`、`victoria3_count=0`）⇒ 等于没留。取证**不许**把下面这条错误换掉。
    try:
        _shot_or_note(hwnd, "09-look-timeout")
        print(_window_note(hwnd, "09-look-timeout"), flush=True)
    except Exception as exc:
        print(f"[失败取证] 09-look-timeout 没做成：{exc!r}", flush=True)
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

    ⚠️ 抓图失败**不是**"按钮没了"（t19）：这一轮记成假并留下原因，若最后真的没切走，
    把原因写进异常（照 :func:`_step_look` 的口径），否则只剩一句"界面没切走"没法查。
    """
    _shot_or_note(hwnd, "10-lobby")  # 证据：整屏一张（一次性，不是热路径）
    click_match(hwnd, match, force=force)
    capture_error = ""

    def did_settle() -> bool:
        nonlocal capture_error
        if tick_mark().readable:
            return True
        try:
            return find_in_roi(hwnd, "btn_observe", roi=BOTTOM_ROI) is None
        except CaptureFailedError as exc:
            capture_error = str(exc)
            return False

    settled = wait_until(did_settle, timeout=settle_timeout, interval=CONDITION_POLL)
    _shot_or_note(hwnd, "11-after-observe")
    if not settled:
        front = _foreground_window()
        raise TemplateNotFoundError(
            f"点了「观察」({match.describe()}) 但 {settle_timeout:.0f} 秒后界面没切走"
            "（底部按钮还在、时间也没开始走）—— 这一下点空了；"
            f"最后抓图错误：{capture_error or '无'}；"
            f"点完的焦点读数：前台={front}，游戏 hwnd={hwnd}、IsIconic={_is_iconic(hwnd)}"
            "（前台不是游戏时，点击位置对也没用 —— 事件会送给别的窗口；t29 实测）；"
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


def _step_speed_key(
    hwnd: int, *, speed_key: str = SPEED_5_KEY, force: bool = False
) -> tuple[str, None]:
    """用原版 ``speed_5`` 快捷键切到 V 档。

    按键前重新核实前台，避免焦点被抢走时把数字键发送到错误的程序；是否被游戏接受
    仍由后续真实 tick 速率确认。
    """
    if _foreground_window() != hwnd:
        raise ForegroundLostError(
            f"要按速度快捷键 {speed_key} 时游戏已经不在前台（游戏 hwnd={hwnd}，"
            f"前台={_foreground_window()}）——已中止"
        )
    press_key(speed_key, force=force)
    _sleep(STEP_SETTLE)
    return f"快捷键 {speed_key}", None


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
    speed_key: str = SPEED_5_KEY,
    speed_keyboard: bool = True,
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
    # D28：抢不到前台时的**最后手段**（见 :func:`recover_foreground`）。默认**开** ——
    # 本机的环境属性就是"这条进程链没有置前权"，关掉它等于让每一局实机都停在第一步；
    # 而它只在前台真的抢不到时才动手，正常局一行日志都不会多出来。
    foreground_recovery: bool = True,
    foreground_relaunch: Callable[[], tuple[int, int]] | None = None,
    loaded_observer: bool = False,
) -> SessionStart:
    """**标准流程**：确认「观察」→ 点它 → 按 5 速快捷键 → 按空格 → 切回后台。

    流程与用户口径逐条对应（2026-09-22）：

    1. **游戏已经在前台**（由 ``launch_to_foreground`` 负责；加载期不碰窗口）；
    2. 点「观察」（:func:`_step_observe`）—— 判据是**界面真的切走了**；
    3. 优先按原版 5 速快捷键（:func:`_step_speed_key`）—— 判据是**按完量出来的速率**；
       键盘路径失败后才回退到鼠标表盘；
    4. 按空格开始（:func:`_step_unpause`）—— 已经在跑就**不按**（空格是暂停开关）；
    5. **切回后台**（:func:`switch_to_background`）：还前台 + 缩窗口；
    6. **缩着也要推进**：这是必须实测的一条（有些游戏一缩下去就不渲染），
       所以缩完之后再量一次；验不过就**当场恢复**并如实写进 ``handover.minimized``。

    失败即抛错，**不返回半个结果**（P13）。这里没有回落链 —— 见模块开头的设计口径。
    """
    trace = AutomationTrace()
    try:
        hwnd = _route_to_foreground(hwnd, previous, force=force)
    except ForegroundLostError as exc:
        # 抢不到前台。既有判据与异常类型**一字不改**：开关关着就照原样抛出去；
        # 开着才走那条"一次合成输入 → 照原样再走既有路由"的有界恢复。
        if not foreground_recovery:
            raise
        recovery = recover_foreground(
            hwnd, previous, force=force, relaunch=foreground_relaunch, trigger=str(exc)
        )
        hwnd, previous = recovery.hwnd, recovery.previous
        if recovery.restarts:
            # 重启过 ⇒ 之前那份 boot-settle 读数已经作废：**重新量一次**，
            # 宁可多等一轮，也不把旧读数和新局面拼在一起。
            settle = wait_for_boot_settle()
    trace = trace.advance(AutomationPhase.FOREGROUND_READY)
    boot = settle if settle is not None else wait_for_boot_settle()
    trace = trace.advance(AutomationPhase.BOOT_SETTLED)
    # 已保存的观察者世界重载后仍进入国家选择界面，必须重新选择观察。
    # 重载流程禁用“新游戏”入口，加载失败不能静默变成另一局。
    match, hwnd = _step_look(
        hwnd,
        threshold=threshold,
        lobby_timeout=lobby_timeout,
        force=force,
        auto_new_game=not loaded_observer,
    )
    _step_observe(hwnd, match, settle_timeout=settle_timeout, force=force)
    trace = trace.advance(AutomationPhase.OBSERVE_SELECTED)

    rate = 0.0
    attempts = 0
    source = "跳过（skip_speed）"
    point: tuple[int, int] | None = None
    speed_key_used: str | None = None
    if not skip_speed:
        attempts = 1
        if speed_keyboard and speed_xy is None:
            source, point = _step_speed_key(hwnd, speed_key=speed_key, force=force)
            speed_key_used = speed_key
        else:
            source, point = _step_speed(
                hwnd, speed_xy=speed_xy, threshold=threshold, index=0, force=force
            )
    trace = trace.advance(AutomationPhase.SPEED_SET)

    unpause_note, pressed, advance = _step_unpause(
        hwnd,
        key_timeout=key_timeout,
        run_timeout=run_timeout,
        key=unpause_key,
        force=force,
    )
    trace = trace.advance(AutomationPhase.RUNNING)
    _shot_or_note(hwnd, "12-after-space")

    # 速率：**在切回后台之前**先量一次 —— 这时窗口还在前台、像素与输入都最干净；
    # 切回去之后再量一次（`verify_minimized`），两次都算"实测"，不是二选一。
    if not skip_speed:
        rate = measure_rate(measure_seconds)
        while rate < min_rate and attempts < speed_attempts:
            if speed_keyboard and speed_xy is None and speed_key_used is not None and attempts == 1:
                # 键盘动作只重试一次；仍未达到速率才进入坐标回退，避免无意义连按。
                source, point = _step_speed_key(hwnd, speed_key=speed_key, force=force)
            else:
                source, point = _step_speed(
                    hwnd,
                    speed_xy=speed_xy,
                    threshold=threshold,
                    index=max(0, attempts - 1),
                    force=force,
                )
            attempts += 1
            rate = measure_rate(measure_seconds)

    handover = switch_to_background(hwnd, previous, minimize=not keep_foreground)
    trace = trace.advance(AutomationPhase.BACKGROUND)
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
    trace = trace.advance(AutomationPhase.VERIFIED)
    trace = trace.advance(AutomationPhase.COMPLETE)

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
        speed_key=speed_key_used,
        trace=trace,
    )


def _run_session_impl(
    *,
    scripted_tests: bool = True,
    lobby_timeout: float = LOBBY_TIMEOUT,
    speed_xy: tuple[int, int] | None = None,
    speed_key: str = SPEED_5_KEY,
    speed_keyboard: bool = True,
    skip_speed: bool = False,
    verify_minimized: bool = True,
    keep_foreground: bool = False,
    force: bool = False,
    foreground_recovery: bool = True,
    wait_tests: float = 0.0,
    background_seconds: float = 8.0,
    save_name: str | None = None,
) -> SessionStart:
    """端到端一条命令：起游戏 → 等加载 → 观察/速度/空格 → 切回后台 →（可选）等判定。

    这是 CLI ``run`` 与探针共用的入口，**内部没有第二条路**。

    ``wait_tests`` > 0 时把闭环的**最后两步**也做掉（`自动化范式.md` §6）：
    验一次后台仍在模拟 → 等官方写出新的成绩单 → 读它给结论。默认 0 = 不等：
    成绩单什么时候写完由套件的 ``last_date`` 决定，跑的可能是**小时级**，
    不能替调用方定这个时长。
    """
    if sys.platform != "win32":
        raise WindowsOnlyError(
            "run 需要 Windows GUI 输入后端；当前平台仍可使用 capabilities、status 和日志/判定解析。"
        )
    # 点火**之前**先记下已有的成绩单 —— 引擎每局换一个新 uuid，
    # "出现了一个先前没有的文件"才是这一局的成绩单。
    known = frozenset(testoutput_files())
    extra_args = (f"-loadsave={save_name}",) if save_name else ()
    hwnd, previous = launch_to_foreground(
        scripted_tests=scripted_tests, timeout=lobby_timeout, extra_args=extra_args
    )
    settle = wait_for_boot_settle(timeout=lobby_timeout)
    if save_name and DEBUG_LOG.is_file():
        with DEBUG_LOG.open(encoding="utf-8-sig", errors="replace") as stream:
            if any("Could not load save game" in line for line in stream):
                raise GameAutoError(f"引擎拒绝载入检查点：{save_name}；保留日志并停止启动输入")

    def _relaunch_for_recovery() -> tuple[int, int]:
        """恢复流程专用：把游戏**干净重启**一次（进程与窗口句柄都换新的）。

        这里只做"起 + 取当前句柄"：boot-settle 交给 `start_session` 在恢复之后**重新量**
        （见那里 `recovery.restarts` 的分支），免得两头各等一轮。
        """
        again, prev_again = launch_to_foreground(
            scripted_tests=scripted_tests, timeout=lobby_timeout, extra_args=extra_args
        )
        return again, prev_again

    started = start_session(
        hwnd,
        previous,
        settle=settle,
        speed_xy=speed_xy,
        speed_key=speed_key,
        speed_keyboard=speed_keyboard,
        skip_speed=skip_speed,
        lobby_timeout=lobby_timeout,
        verify_minimized=verify_minimized,
        keep_foreground=keep_foreground,
        force=force,
        foreground_recovery=foreground_recovery,
        foreground_relaunch=_relaunch_for_recovery if foreground_recovery else None,
        loaded_observer=save_name is not None,
    )
    if wait_tests <= 0 or not scripted_tests:
        return started
    # `restore=False`：**不许把前台抢回游戏** —— 用户口径是点火之后就把机器还给人。
    # `SessionStart` 是 frozen 的：后两步的结果用 `replace` 挂上去，不改原对象。
    return replace(
        started,
        background=background_ok(
            started.hwnd,
            seconds=background_seconds,
            restore=False,
            force=force,
        ),
        verdict=wait_for_verdict(known, timeout=wait_tests),
    )


def status_report() -> list[str]:
    """只读地把"时间在不在走"这件事说清楚（不点任何东西）。"""
    if sys.platform != "win32":
        mark = tick_mark()
        return [
            f"平台          : {sys.platform}",
            "游戏窗口      : （GUI 状态不可用）",
            f"游戏进程      : {len(_process_pids())} 个",
            f"最近 tick     : {mark.tick or '（读不到）'}   ← {TICK_LOG}",
            f"当前时间在走  : {is_running(4.0).describe()}",
        ]
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


def run_session(
    *,
    scripted_tests: bool = True,
    lobby_timeout: float = LOBBY_TIMEOUT,
    speed_xy: tuple[int, int] | None = None,
    speed_key: str = SPEED_5_KEY,
    speed_keyboard: bool = True,
    skip_speed: bool = False,
    verify_minimized: bool = True,
    keep_foreground: bool = False,
    force: bool = False,
    foreground_recovery: bool = True,
    wait_tests: float = 0.0,
    background_seconds: float = 8.0,
    save_name: str | None = None,
) -> SessionStart:
    """运行一次会话；失败时只清理本模块启动的进程。"""
    try:
        return _run_session_impl(
            scripted_tests=scripted_tests,
            lobby_timeout=lobby_timeout,
            speed_xy=speed_xy,
            speed_key=speed_key,
            speed_keyboard=speed_keyboard,
            skip_speed=skip_speed,
            verify_minimized=verify_minimized,
            keep_foreground=keep_foreground,
            force=force,
            foreground_recovery=foreground_recovery,
            wait_tests=wait_tests,
            background_seconds=background_seconds,
            save_name=save_name,
        )
    except BaseException:
        with suppress(Exception):
            kill_owned_game()
        raise


def main(argv: list[str] | None = None) -> int:
    """命令行入口：``python -m pdx.game_auto <命令>``。

    只做四件事：看状态、跑一局（标准流程）、抓图（收模板用）、验后台。
    **任何一步失败都返回退出码 1**，不打印"完成"。
    """
    enable_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="python -m pdx.game_auto",
        description="Victoria 3 自动化：起游戏 → 观察 → 按 5 速 → 空格 → 切回后台",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="只读：报告 tick / 探针月度行 / 时间是否在推进")
    sub.add_parser("capabilities", help="只读：报告当前平台的 GUI 与无头验证能力")
    sub.add_parser("check", help="断言当前没有 victoria3 在跑")

    run_parser = sub.add_parser(
        "run",
        help="标准流程：起游戏（前台）→ 等加载 → 点观察 → 按 5 速快捷键 → 按空格 → 切回后台",
    )
    run_parser.add_argument(
        "--no-scripted-tests", action="store_true", help="不带官方 -scripted_tests 开关"
    )
    run_parser.add_argument("--lobby-timeout", type=float, default=LOBBY_TIMEOUT)
    run_parser.add_argument(
        "--no-foreground-recovery",
        action="store_true",
        help="抢不到前台时不尝试「合成输入恢复」（默认会尝试：Alt 轻敲优先，最多 3 次、"
        "每次之间重启游戏；关掉它等于把这条链的环境属性当成失败直接抛出去）",
    )
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
    run_parser.add_argument(
        "--speed-mouse",
        action="store_true",
        help="强制使用旧的鼠标表盘路径；默认优先按原版 5 速快捷键，失败后再回退鼠标",
    )
    run_parser.add_argument("--speed-key", default=SPEED_5_KEY, help="5 速快捷键，默认 5")
    run_parser.add_argument(
        "--wait-tests",
        type=float,
        default=0.0,
        metavar="秒",
        help="等官方套件判定并读产物（闭环的最后两步）。0 = 不等（默认）—— "
        "成绩单什么时候写完由套件的 last_date 决定，可能是小时级",
    )
    run_parser.add_argument(
        "--background-seconds",
        type=float,
        default=8.0,
        help="等判定之前先验一次「缩着也在推进」的秒数（只在 --wait-tests 时用）",
    )

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

        if command == "capabilities":
            for key, value in platform_capabilities().items():
                print(f"{key}: {value}")
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
            print(
                background_ok(
                    hwnd,
                    seconds=float(args.seconds),
                    force=force,
                ).describe()
            )
            return 0

        # 只剩 "run"：标准流程 —— 起游戏（前台）→ 等加载（**完全不碰窗口**，只用进程 +
        # 日志这些免费信号，至少 BOOT_MIN_SECONDS 秒；实测到选国家界面约 137 秒）
        # → 点观察 → 按 5 速快捷键 → 按空格 → 切回后台（还前台 + 缩窗口）
        # →（--wait-tests）验后台仍在跑 → 等官方套件判定 → 读产物给结论。
        #
        # ⚠️ 这段话以前是**第二份实现**（与 `run_session` 各写一遍），于是
        # 「`run_session` 是唯一入口」这句话是假的、`--wait-tests` 也只会在这里生效。
        # 现在只有一条路：CLI 也只调 `run_session`。
        speed_xy: tuple[int, int] | None = None
        if args.speed_xy:
            left, _, right = str(args.speed_xy).partition(",")
            speed_xy = (int(left), int(right))
        result = run_session(
            scripted_tests=not bool(args.no_scripted_tests),
            lobby_timeout=float(args.lobby_timeout),
            speed_xy=speed_xy,
            speed_key=str(args.speed_key),
            speed_keyboard=not bool(args.speed_mouse),
            skip_speed=bool(args.skip_speed),
            verify_minimized=not bool(args.no_verify_minimized),
            keep_foreground=bool(args.keep_foreground),
            force=force,
            foreground_recovery=not bool(args.no_foreground_recovery),
            wait_tests=float(args.wait_tests),
            background_seconds=float(args.background_seconds),
        )
        print(f"加载等待（不碰窗口）：{result.settle.why}")
        print("闭环完成，证据：")
        for key, value in result.as_dict().items():
            print(f"  {key:22s}: {value}")
        if result.verdict is None:
            return 0
        print(result.verdict.describe())
        # 判定不通过就是**这次运行不通过**（P13）：退出码交给调用方，别只打印一句。
        return 0 if result.verdict.ok else 1

    except GameAutoError as exc:
        print(f"[失败] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - 入口
    raise SystemExit(main())


__all__ = [
    "BENIGN_ERROR_RE",
    "BOTTOM_ROI",
    "CAPTURE_FAMILY_SCAN",
    "CAPTURE_FAULTS",
    "CONSOLE_EDIT_ROI",
    "CONSOLE_KEY",
    "CONSOLE_OUTPUT_ROI",
    "CURSOR_PARK_LOG",
    "DEFAULT_SCALES",
    "DEFAULT_THRESHOLD",
    "LAST_KILL_ALIVE",
    "LAST_QUARANTINE_ERRORS",
    "OUR_MARKS",
    "SHIFT_CHARS",
    "SPEED_5_KEY",
    "TESTOUTPUT_GLOB",
    "TESTS_TXT",
    "TOP_RIGHT_ROI",
    "UI_DIR",
    "Advance",
    "AutomationPhase",
    "AutomationTrace",
    "BootSettle",
    "CaptureFailedError",
    "CursorPark",
    "ForegroundAttempt",
    "ForegroundHandover",
    "ForegroundLostError",
    "ForegroundRecovery",
    "GameAutoError",
    "GameRunningError",
    "Match",
    "NotRunningError",
    "OwnedProcess",
    "SessionStart",
    "SuiteVerdict",
    "TemplateNotFoundError",
    "TickMark",
    "WindowNotFoundError",
    "archive_stamp",
    "assert_no_game_running",
    "benign_error_lines",
    "binaries_dir",
    "click_client",
    "click_match",
    "console_open",
    "console_output_ink",
    "ensure_foreground",
    "error_log_path",
    "error_logs",
    "find_observe",
    "find_template",
    "find_window",
    "is_blank",
    "is_later",
    "is_running",
    "kill_game",
    "last_tick_in",
    "launch",
    "launch_to_foreground",
    "load_template",
    "locate",
    "locate_optional",
    "match_template",
    "measure_rate",
    "open_console",
    "other_window",
    "our_error_lines",
    "park_cursor_clear_of",
    "parse_tasklist_pids",
    "parse_testoutput",
    "parse_tick_date",
    "platform_capabilities",
    "press_chord",
    "press_key",
    "probe_months",
    "probe_roles_in",
    "read_verdict",
    "recover_foreground",
    "roi_box",
    "rotated_logs",
    "run_session",
    "screenshot",
    "speed_candidates",
    "speed_widget_xy",
    "start_session",
    "status_report",
    "submit_console_command",
    "switch_to_background",
    "testoutput_files",
    "tick_day",
    "tick_mark",
    "type_text",
    "unused_path",
    "wait_for_boot_settle",
    "wait_for_testoutput",
    "wait_for_verdict",
    "wait_for_window",
    "wait_until",
    "wait_until_readable",
    "wait_until_running",
]
