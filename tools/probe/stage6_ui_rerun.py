"""阶段 6 ②：**以真玩家国家开新局**的实机驱动（口径：`docs/design/exec/阶段6-国家身份开局-取证口径.md`）。

这一份与观察者局那条闭环（`game_auto.start_session` / `run_session`）**互不依赖**：口径 §8 定的
是"独立驱动 + `game_auto` 只加原语"，所以本文件**不碰**那条闭环，也不新增 `game_auto` 子命令。

两种模式
--------
``--recon``（侦察：**首跑必须走这条**）
    按口径 §9：目标屏/规则窗这些界面**从没被实测过**，模板还不存在（`tools/probe/sitai_ui/`
    是空的）。侦察模式因此**允许按估计 ROI 点**、**不要求模板命中**，但每一步都抓一张整屏帧
    落进证据目录，并把"这一步看到了什么"写进运行摘要 —— 收模板与校正 ROI 就靠这些帧。

``--recon`` 之外的（取证）
    每一步都要模板命中（`tools/probe/sitai_ui/<lang>/<name>.png`），**缺模板即报错退出**
    （P13）：阶段 6 的取证据此只认"画面 ROI + 模板分数"，不认"看起来对了"。

环境纪律（口径 §6，顺序不许反：B79）
------------------------------------
`preflight`（只读）→ 探针态自愈 → 收掉残留进程 → **挪日志**（只动临时目录）→ **部署**
（第一次改 `content_load.json`）→ 跑 → `finally`：杀进程 + 还前台 + 还原 + 逐字节核对。

产物（口径 §2.1）
-----------------
证据帧与运行摘要落在 `--evidence` 指向的目录（缺省 `tools/out/auto/`）；模板本体落在
`tools/probe/sitai_ui/{zh,en}/`（**仓库内**，与证据帧分开：模板是判据本体，帧是证据）。
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from io import TextIOWrapper
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageChops, ImageStat

from pdx import ab_probe, config, experiments, preflight
from pdx import game_auto as ga

if TYPE_CHECKING:
    from collections.abc import Sequence

#: 模板目录（仓库内，按语言分；口径 §4.2：两套模板混在一个目录里会出假绿）。
TEMPLATE_ROOT = config.REPO / "tools" / "probe" / "sitai_ui"

#: 语言 → 模板子目录名。
LANGS: dict[str, str] = {"l_simp_chinese": "zh", "l_english": "en"}

#: 难度三档 → 归档用的短名（帧名用得上，见口径 §2.1 的 `23a-c`）。
TIERS: dict[str, str] = {
    "history_friendly": "history_friendly",
    "uniform": "uniform",
    "harsh": "harsh",
}

#: 载入画面基准帧（**64×36 缩略图**，2026-09-25 02:43 由整帧 `loading-ref.png` 降采样而来）。
#: 为什么它必须进仓库：盒①第二遍的 `19/20/21` **三帧同哈希** `fa2fab91382e…`
#: （3,832,482 B）—— 全是那张「初始化游戏……」载入画面，而运行摘要里 L4–L7 四行都写了 ✅。
#: 载入画面是**静态大图**，而且载入期引擎**不写 debug.log** ⇒ 「睡够」与「日志 30 秒
#: 不变」两条判据都判不出它来（这是队长复核时点破的那条）。唯一可靠的判据是**比内容**。
#: 整帧（3.8 MB）**不进仓库**（用户口径：不必要的不要提交），留档在 gitignore 内的
#: `tools/out/evidence/loading-ref-full-20260925.png`；判据与整帧基准**逐位等价**的理由
#: 见 :func:`_mean_diff` 的 docstring（先缩后差）。
LOADING_REF = TEMPLATE_ROOT / "loading-ref-64x36.png"
#: 落帧的子目录名前缀。B114：`tools/out/auto/` 曾经是**扁平**目录，每遍都写同样的文件名
#: （`19-main-menu.png` / `20-setup-screen.png` / …）⇒ 后一遍**静默覆盖**前一遍，到想引用
#: 「这一帧与更早某遍逐字节相同」时盘上已无孪生帧可复算（该 claim 只能撤回）。
#: ⇒ 每遍的帧落进 `<evidence>/<pass-id>/`，**不同 pass 不互相覆盖**。
#: ⚠️ **既有扁平证据一个都不动**（那是已经引用过的历史；本文件只**新增**子目录）。
PASS_DIR_PREFIX = "pass-"


def pass_dir_name(tier: str, *, now: datetime | None = None) -> str:
    """这一遍的 pass-id（= 落帧子目录名）：`pass-<本地时间戳>-<tier>`。

    为什么时间戳必须进名字（B114 的根因）：同一个 tier 今天要跑很多遍（第二遍 L4→L10 还要
    再跑），只按 tier 命名**照样跨遍覆盖**；带上开始时刻之后，"这一帧属于哪一遍"是**自证**的，
    于是「A 遍的 22 与 B 遍的 22 逐字节相同」这条 claim **事后可由盘上两帧复算** ——
    被撤回的那条正是因为缺了这个对应关系（`backlog.md` B114）。
    """
    stamp = (now or datetime.now(UTC).astimezone()).strftime("%Y%m%d-%H%M%S")
    return f"{PASS_DIR_PREFIX}{stamp}-{tier}"


def pass_dir(evidence_root: Path | str, pass_id: str) -> Path:
    """给这一遍分一个**独有**的落帧目录并建出来：`<evidence_root>/<pass-id>/`（重名就顺位）。

    为什么要顺位而不是直接用 pass-id（B114 的硬要求）：pass-id 的粒度是「秒 + tier」，
    同一秒里起两遍（用例、或人工连跑）就会撞名 —— **撞名等于后一遍覆盖前一遍的帧**，
    而那正是 B114 让一条「跨遍逐字节相同」的 claim 被撤回的成因。顺位分配把「不同 pass
    不互相覆盖」从"人不会在同一秒跑两遍"这种口头保证，变成**由代码保证的性质**。
    ⚠️ 只**新建**子目录：根目录里既有的扁平帧一个都不碰（不删、不改、不移动）。
    """
    root = Path(evidence_root)
    index = 1
    while True:
        name = pass_id if index == 1 else f"{pass_id}-{index}"
        candidate = root / name
        if not candidate.exists():
            candidate.mkdir(parents=True)
            return candidate
        index += 1


#: 帧间比例平均差的上限：低于它就算「还是那张载入画面」。取 0.01 而不是「逐像素相同」，
#: 因为载入画面上的省略号动画会让同一张图差出 193 字节（`22-rule-sitai.png` 实测）。
LOADING_DIFF = 0.01
#: 等「不再是载入画面」的上限。给得宽：外部 `projects\quant` 16 worker / ≈3.2 GB 时
#: 实测载入约 2 分钟。到点还没过就**报错**，不写 ✅。
LOAD_TIMEOUT = 300.0
#: 等「点完之后画面真的变了」的上限：到点还没变 = 这一击没生效 ⇒ **报错**。
CHANGE_TIMEOUT = 90.0
#: 「中央区标准差」下限：低于它判「这一帧还没画出来」（启发式，不是口径阈值）。
BLANK_STD = 3.0
#: 规则窗**滚动条**的位置（比例；2026-09-25 队长从第九遍 21 帧量的全分辨率值换算）：
#: 滚动条列 x ≈ 1423/1920；滑块起始 y ≈ 430/1080；一次拖动往下走 0.12 屏高。
#: 为什么用拖动而不是滚轮：第九遍实测 `21` 与滚过之后的 `22-rule-sitai-scroll-1`
#: **逐字节相同**（同 sha256 `414f481b56c870e5`、同 1,934,985 B）⇒ 注入的滚轮到不了引擎。
SCROLLBAR_X = 0.741
SCROLLBAR_TOP = 0.398
SCROLLBAR_STEP = 0.12
#: 我们那一行的定位模板 `rule_row_sitai` 的阈值 —— **只给行定位器用，别的模板不许跟着降**
#: （作用域写清：驱动里其它模板的正分 1.0 / 负分 ≤0.43，**0.90 是对它们量的**；见各处调用点的
#: `threshold=` 实参）。
#: 🔧 2026-09-25 08:3x **重推**（旧值 0.90 随"平底误裁"模板一起作废，见 §3.10 / B118）：
#: 新模板 = 真标题「处境难度」，像框 **(1144,683,1217,705)**、std 40.4（旧的是平底、std 2.0）。
#: 用仓库同一个匹配器在帧上量（复算脚本 `tools/out/auto/retake_l7.py`）：
#: **正（最小）= 1.000000**（`22` / `23` 两帧；⚠️ 这两帧是**自匹配**，正侧是**平凡满分**）、
#: **负（最大）= 0.270209**（无规则窗的 `19` 0.2454 / `20` 0.2602、同帧左列别条标题 0.2702）
#: ⇒ 正负**不交叠**，取中点 **0.64**（两侧余量各 ≥0.365）。
#: ⚠️ 阈值推导的强度**全在负侧**；**第一个非自匹配的正分要在第二遍那一局现读并记进读数页**，
#: 若那一个分 **< 0.64 ⇒ 停下上报**，**不许调阈值让它过**。
ROW_LOCATOR_THRESHOLD = 0.64

#: 标题命中点 → **行心**的纵向偏移（命名常量，别把 48 散在代码里）。
#: 现读实测（帧 `22`）：新模板命中点 y = **694** 是**标题**（真框 y 685–702），而**行带 y 731–751**
#: ⇒ 行心 y = 标题命中 y + **48**（694 + 48 = 742 ≈ 行带中心 741）。
#: ⚠️ 这一对数值是**行定位后**才成立的（y 必须由**定位到的那一行**给出，**不许写死**）。
ROW_TITLE_TO_ROW_CENTER_DY = 48
#: 行带上两个箭头的 x（现读实测、琥珀镜像三角：◀ 1006–1017 / ▶ 1343–1354）⇒ 取各自中心。
ROW_ARROW_PREV_X = 1011
ROW_ARROW_NEXT_X = 1348
#: 自检的哨兵窗口半宽（**哨兵，不是自变量**）：`(x0, y0)` 的约定位置是**正中心**，所以两个
#: `ROW_ARROW_*` 谁写错，就落在自己那 23×31 的窗外 ⇒ 那里读到的琥珀像素是 0。
#: ⚠️ 窗口内的琥珀像素数**随真实渲染变化**（实测我们的行：◀ 125 / ▶ 125，2026-09-25
#: `22-rule-sitai.png`；阴性即 0）—— **这条只禁「与 0 相消的写法」**，别拿它当模板。
#: 行带高取 2×ROW_ARROW_DY_HALF+1 = **21**（真控件 20 行、上边被行带切掉 1 行，与 §3.10 一致）。
ROW_ARROW_X_HALF = 11
ROW_ARROW_DY_HALF = 15

#: 自检前的**中性点**（t41 的修因，判据一字不动）：光标停在这里时规则窗里没有控件处于悬停态。
#: 实测（Pass A `26-tier-prev-candidate.png`）：点完 ◀ 之后光标就压在 ◀ 上，悬停高亮把它的
#: 抗锯齿边缘多照亮一列 ⇒ 琥珀 125→130、簇宽 11→12 列，而没被悬停的 ▶ 一个像素没变，
#: 于是「两枚互成镜像」的**等宽**要求假红（12 vs 11）—— 两枚箭头各自的形状体检当时都合规。
NEUTRAL_CURSOR_XY = (60, 60)
#: 中性重抓的采样间隔与上限；「等够」的判据是**连续两帧中性一致**（不是拍一个固定秒数）
NEUTRAL_POLL = 0.2
NEUTRAL_TRIES = 10
#: 逐档导航时**每个方向**最多点几次箭头（t41 的执行器）。为什么是 4：规则窗一次只显示一档，
#: 三档环状排列 ⇒ 从当前档走到任意另一档**最多 2 步**；留一倍余量（4）是为了「先走错方向」也
#: 还能回头走到。⚠️ 用尽仍到不了目标档 ⇒ 报「该档未取到」，**不许**用别档顶替（口径页 §3.3）。
TIER_NAV_TRIES = 4
#: 一枚箭头「真的在那儿」的琥珀像素下限。取这个数**不是拍脑袋**：判据 `bright ≥ 10 或
#: amber ≥ 10`（`tests/test_ui_templates.py` 的 `BRIGHT_MIN` / `AMBER_MIN`）用在**整张
#: 模板**上，而箭头是模板里的一小块，照抄 10 会正好把噪声放进来；三支实测读数都是 125
#: （◀/▶ + 上一行的同名箭头，§3.10），阴性是 0 ⇒ 这里取 **10**（`AMBER_MIN` 同值），
#: 量级上留 12× 余量。⚠️ 本判据**故意不要 `bright` 那一支**：理由见 :data:`ROW_ARROW_PROFILES_MIRROR`。
ROW_ARROW_MIN_AMBER = 10
#: 两枚箭头的「同形镜像」容差。**只减空列、不裁列内空隙**：`_trim_zeros` 会把两端的 0 拿掉、
#: 留下中间的真实剖面，于是「逐行重现」这条判据在这里是**免费的**（剖面必须相等）。
#: ⚠️ 2 是**定义**，不是拟合值：真帧的相位差是**精确的 1 列**（◀ 剖面 `[3..20,0]`、▶ 是
#: `[0,20..3]`，B118 的 §3.10 就写着"只差一个列相位"），2 只是给渲染留一格。
ROW_ARROW_PROFILES_MIRROR = 2
#: ⚠️ **为什么这里另立一套**：`test_ui_templates.py` 那条是给**读盘模板**用的，要求
#: `bright ≥ 10 或 amber ≥ 10`。**逐像素**照搬到这里是错的 —— 行带里有**标题原文**（亮字），
#: 于是「窗前挪个 40 px、窗口里全是亮字、琥珀 0」会**照样放行**，而那正是要拦的。
#: 所以本自检**只用 `amber` 那一支**，含义是「**琥珀**的镜像三角」，与那条闸门的**目的**
#: （不拿平底/无控件像素当判据）一致。共用的是数值（45 / 130 / 90 / 10），一字不改。
ROW_ARROW_AMBER_RULE = "琥珀判据：R−B ≥ 45 且 R ≥ 130 且 G ≥ 90（与 test_ui_templates.py 同值）"

#: 一枚箭头**形状/大小**的界（t24 修 F1，t8 的独立复核找出来的洞）。
#: 为什么必须有这一族：`row_arrow_profiles_mirror` 判的是「两窗剖面互为镜像」，而**平剖面的
#: 镜像恒真**（两侧都平 ⇒ 处处相等）⇒ 竖条、等宽矩形、整窗平色全都能自证满分；`:data:`
#: `ROW_ARROW_MIN_AMBER` 只管「够不够大」、不管「像不像」。所以这里补**连续**判据（宽/高/比/
#: 剖面形状），**不是**尺寸白名单（白名单会被"表外尺寸"当场问住）。
#: 界怎么定的（全部锚在现读实测上，可复算 ⇒ `tests/test_probe_stage6.py` 的样本 +
#: 那张形状动物园跑；t24 报告里有 54 格前后对照）：
#:   * 真箭头（`22-rule-sitai.png`，行心 y=742）＝ 宽 **11**（◀ 1006–1016／▶ 1343–1353）、
#:     高 **20**（真控件 20 行，行带 y 731–751 = 21 行）、宽高比 **11/20 = 0.55**、
#:     剖面 `[3,4,6,8,9,11,13,15,17,19,20]`（**跨度 20−3 = 17**、单调增、中间没有 0 列）。
#:   * ⇒ 宽界 **5–16**（真值 −6/+5）、高界 **10–26**（真值 −10/+6）、比界 **0.40–0.75**、
#:     剖面跨度下界 **4**。留这些余量是给渲染抖动与"真控件比像框多半行"的：
#:     与真箭头**同比的缩放**（5×10 / 7×14 / 11×20 / 13×24）一律放行；
#:     明显偏离尺寸或比例的（3×6、16×30、20×30）按界拒 —— 界写在上面，t25 可复算。
#:   * ⚠️ 为什么敢用**绝对像素**界：同一条链上更早的 L7 用**同一张**模板（`rule_row_sitai`，
#:     阈值见 `ROW_LOCATOR_THRESHOLD`）定位这一行，模板匹配对缩放不宽容 ⇒ UI 真缩放的话
#:     那一步先失配，走不到这里来。所以这里的界**不会**变成"实机误拒"，只挡"窗里有琥珀但
#:     明显不是这枚控件"的东西（B118 的同族病：退化读数自证满分）。
ROW_ARROW_WIDTH_MIN = 5
ROW_ARROW_WIDTH_MAX = 16
ROW_ARROW_HEIGHT_MIN = 10
ROW_ARROW_HEIGHT_MAX = 26
ROW_ARROW_ASPECT_MIN = 0.40
ROW_ARROW_ASPECT_MAX = 0.75
#: 剖面「确实有形状」的下界：真箭头跨度 17 ⇒ 4 是"明显不是平剖面"的低门槛
#: （竖条 / 等宽矩形 / 整窗平色的跨度都是 **0** ⇒ 一律出局）。
ROW_ARROW_PROFILE_SPREAD_MIN = 4
#: **填充/密度**下界（t24/amend 2）：`amber / (宽 × 高)`。真箭头 125 / (11×20 = 220) = **0.568**；
#: 1 px 空心轮廓（左竖边 20 + 底边 10 = 30 px，同 bbox）= **0.136** ⇒ 取中点 **0.35**（上下各留
#: ≥0.21 余量）。为什么非有它不可：空心轮廓的宽/高/比/跨度/单调**全都合规**（剖面 20,1,1,…,1），
#: 只有"它里面几乎没东西"这一条拦得住 —— 而一枚箭头是**实心面**，不是描边。
ROW_ARROW_FILL_MIN = 0.35


class RowArrowCheckError(RuntimeError):
    """点击前的自检没过 —— **这一步不许点鼠标**。

    消息自带「x 区间 + 行带 y + 实测像素计数」（见 :func:`row_arrow_failure_text`），
    所以不看代码也能判两种相反的情形：**没找到**（窗外计数 0）、**找错了位置**
    （窗外计数 > 0，说明东西在，是坐标写偏了）。
    """

    def __init__(self, reason: str, text: str) -> None:
        super().__init__(text)
        self.reason = reason
        self.text = text


@dataclass(frozen=True, slots=True)
class RowArrowSpot:
    """一支检出的箭头：**位置 + 实测像素计数 + 剖面的哈希**（全进证据，便于事后判位移）。

    `x0/x1` 是**实测像框**（不是常量），`profile` 是各列的琥珀像素数（`_trim_zeros` 之后）。
    `x` 是**点击点 = 实测像框的水平中心**（B118 的 1011 / 1348 正是这么来的）。
    """

    label: str
    x: int
    x0: int
    x1: int
    amber: int
    width: int
    height: int
    profile: tuple[int, ...]

    @property
    def profile_digest(self) -> str:
        """剖面摘要（进证据文本用；别用它判镜像 —— 判镜像请用 `profile`）。"""
        return hashlib.sha256(bytes(self.profile)).hexdigest()[:8]

    def report_line(self) -> str:
        return (
            f"{self.label}：像框 x {self.x0}–{self.x1}（中心 {self.x}）、"
            f"琥珀 {self.amber} 像素、{self.width}×{self.height}、"
            f"剖面 {list(self.profile)}（摘要 {self.profile_digest}）"
        )


@dataclass(frozen=True, slots=True)
class RowArrowProbe:
    """一处哨兵窗的读数（**阴性也要有读数**：窗外计数 0 与"没量"必须分得开）。"""

    label: str
    x0: int
    x1: int
    amber: int
    spot: RowArrowSpot | None
    why: str = ""
    #: 窗内**旁路**琥珀（除去 `clusters[0]` 之外、≥`ROW_ARROW_MIN_AMBER` 的连通域）的说明 ——
    #: **只作说明、不进判据**：它们是"窗里别的东西"，不影响这枚箭头的读数（t24/amend 1：
    #: 旧版把它们一并算进**整窗**剖面 ⇒ 真箭头 + 旁路小块会让剖面冒出中间 0 列 ⇒ 误判
    #: "形状不符"，还说成"窗里有琥珀但不像那枚控件"—— 把话说反了）。
    aside: str = ""

    @property
    def centre_x(self) -> int:
        """这一处的**期望 x**（哨兵窗的中心）—— 判"附近有没有琥珀"必须从它量起。"""
        return (self.x0 + self.x1) // 2

    def report_line(self) -> str:
        """阴性也要有**读数**：报**窗内实测计数**（0 与"有 5 个像素但不成形"必须分得开）。

        ⚠️ 早先这里印的是"窗外计数 0" —— 那句在"C 形：窗里有琥珀但连通域 < 下限"时**是假的**
        （`amber` 明明是 5），而"没找到 vs 找错了位置"正是靠这一行判的（B118 的教训：
        读数说错话比没有读数更坏）。
        """
        if self.spot is not None:
            line = self.spot.report_line()
            return f"{line}（{self.aside}）" if self.aside else line
        return (
            f"{self.label}：窗内琥珀 {self.amber} 像素、未成「一枚箭头」"
            f"（{self.why or '没量到原因'}）；窗 x {self.x0}–{self.x1}"
        )


def _amber_rule_text() -> str:
    """把判据原样印进消息（**读者不用跳文件**；也逼改动者改一处就够）。"""
    return (
        f"琥珀判据 `R−B ≥ 45 且 R ≥ 130 且 G ≥ 90`（R/G/B 为 0–255 的三通道算术读法，"
        f"与 tests/test_ui_templates.py:{AMBER_RULE_SRC_LINE} 同值、同一套读数）"
    )


#: `ROW_ARROW_AMBER_RULE` 里那三条数在 `tests/test_ui_templates.py` 的行号锚点。
#: 本文件**不 import 那张测试**（测试不进口驱动），所以拿行号当锚、由用例核锚点没漂。
AMBER_RULE_SRC_LINE = 22


def amber_mask(image: Image.Image) -> list[list[bool]]:
    """按上面那条琥珀判据给一块像素打标（**返回纯 Python 二维布尔表**，驱动不带 numpy 依赖）。

    逐像素判 `(R−B) ≥ 45 且 R ≥ 130 且 G ≥ 90`。**不用 `convert("L")`** —— 那是 601 加权，
    与判据的算术读法不是一把尺子（`test_ui_templates.py` 的 docstring 量过：对金色差 ~4.6σ）。
    """
    rgb = image.convert("RGB")
    width, height = rgb.size
    pixels = rgb.load()
    if pixels is None:  # pragma: no cover - PIL 只在关了图之后给 None
        raise RuntimeError("图像已关闭，读不到像素")
    return [
        [
            (pixels[x, y][0] - pixels[x, y][2]) >= 45
            and pixels[x, y][0] >= 130
            and pixels[x, y][1] >= 90
            for x in range(width)
        ]
        for y in range(height)
    ]


def amber_clusters(mask: list[list[bool]]) -> list[tuple[int, int, int, int, int]]:
    """连通域（4 邻接）—— 返回 `(琥珀计数, x0, y0, x1, y1)`，按像素数从多到少。

    **为什么非要连通域**：窗口里出现「两支半支箭头」「箭头 + 一小块别的琥珀」时，"总计数够"
    是**假绿**（B118 现场就是被这类退化读数带偏的）。这里只认**一块**够大的连通域。
    """
    height = len(mask)
    width = len(mask[0]) if height else 0
    seen = [[False] * width for _ in range(height)]
    found: list[tuple[int, int, int, int, int]] = []
    for y0 in range(height):
        for x0 in range(width):
            if not mask[y0][x0] or seen[y0][x0]:
                continue
            stack = [(x0, y0)]
            seen[y0][x0] = True
            count = 0
            minx = maxx = x0
            miny = maxy = y0
            while stack:
                x, y = stack.pop()
                count += 1
                minx, maxx = min(minx, x), max(maxx, x)
                miny, maxy = min(miny, y), max(maxy, y)
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if 0 <= nx < width and 0 <= ny < height and mask[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            found.append((count, minx, miny, maxx, maxy))
    found.sort(key=lambda item: -item[0])
    return found


def _column_profile(mask: list[list[bool]]) -> tuple[int, ...]:
    width = len(mask[0]) if mask else 0
    return tuple(sum(1 for row in mask if row[x]) for x in range(width))


#: 「窗外没读数」时还往外找多远（px）。**只用来判「是不是位置写偏了」**，不进判据：
#: 实测我们那一行附近最近的非箭头琥珀是滚动条滑块 x 1417/1418（§3.10；离 ▶ 期望位置 69 px）
#: ⇒ 40 px 的半径不会把滚动条拖进来当证据。
ROW_ARROW_NEARBY_SEARCH = 40


def amber_runs(mask: list[list[bool]]) -> list[tuple[int, int, int]]:
    """把二维布尔表按**列**折成一维"琥珀游程"：`[(x0, x1, 计数)]`（判"哪里有一坨琥珀"用）。

    列计数只算一次（`_column_profile`），游程按"连续非空列"切。
    """
    profile = _column_profile(mask)
    out: list[tuple[int, int, int]] = []
    start: int | None = None
    for x in range(len(profile) + 1):
        count = profile[x] if x < len(profile) else 0
        if count and start is None:
            start = x
        elif not count and start is not None:
            out.append((start, x - 1, sum(profile[start:x])))
            start = None
    return out


def nearest_amber_run(
    image: Image.Image,
    *,
    row_center_y: int,
    x: int,
    radius: int = ROW_ARROW_NEARBY_SEARCH,
) -> str:
    """在行带里、`x ± radius` 的范围内找**最近的**琥珀连通域（找不到返回 `""`）。

    为什么要有它：`ROW_ARROW_*` 写偏时，哨兵窗里的读数是 **0** —— 与"这一屏真的没箭头"
    **同形**（B118 的仪器问题就是这么发生的）。把"附近的琥珀在哪"印进失败文本，这两种情形
    就分得开了，而**判据一个字不改**（它只是诊断）。
    """
    x0, y0, x1, y1 = row_arrow_crop_box(x=x, y=row_center_y, x_half=radius)
    mask = amber_mask(image.convert("RGB").crop((x0, y0, x1, y1)))
    best: tuple[int, int, int, int] | None = None
    centre = radius
    for run_x0, run_x1, count in amber_runs(mask):
        if count < ROW_ARROW_MIN_AMBER:
            continue
        distance = max(0, max(centre - run_x1, run_x0 - centre) - 1)
        if best is None or distance < best[0]:
            best = (distance, run_x0, run_x1, count)
    if best is None:
        return ""
    distance, run_x0, run_x1, count = best
    return f"x {x0 + run_x0}–{x0 + run_x1}（离期望 x={x} 差 {distance} px、琥珀 {count} 像素）"


def _trim_zeros(profile: tuple[int, ...]) -> tuple[int, ...]:
    """去掉两端的 0 列，**中间的 0 保留**（"只减空列、不裁列内空隙"）。

    ⚠️ 这一步就是 B118「阴性对照里含有目标」那条教训的落地：上一行的**同一支箭头**在
    窗外 186 px 处（`addrow`），而哨兵窗只有 23 px —— 剥掉两端 0 之后，**窗内的剖面**才是
    被检查的东西，窗外的像素一个也不进判据。
    """
    start, end = 0, len(profile)
    while start < end and profile[start] == 0:
        start += 1
    while end > start and profile[end - 1] == 0:
        end -= 1
    return profile[start:end]


def row_arrow_profiles_mirror(
    left: tuple[int, ...], right: tuple[int, ...], *, tolerance: int | None = None
) -> bool:
    """:data:`ROW_ARROW_PROFILES_MIRROR` 的**定义为真**的那件事（箭头形状的镜像判据）。

    只比长度与「右剖面倒过来 == 左剖面」（逐列容差 `tolerance`）。**不读常量、不碰像素**，
    所以它是纯净的：用例里能用它把"互成镜像"与"形状不同"分开证。
    """
    tolerance = ROW_ARROW_PROFILES_MIRROR if tolerance is None else tolerance
    return len(left) == len(right) and all(
        abs(a - b) <= tolerance for a, b in zip(left, reversed(right), strict=True)
    )


def row_arrow_assert_mirror(
    prev: tuple[int, ...], next_: tuple[int, ...], *, tolerance: int | None = None
) -> bool:
    """`RowArrowSpot.profile` 那一对（**已剥零**）是否互成镜像 —— 判据的入口。"""
    return row_arrow_profiles_mirror(prev, next_, tolerance=tolerance)


def row_arrow_crop_box(
    *,
    x: int,
    y: int,
    x_half: int | None = None,
    dy_half: int | None = None,
) -> tuple[int, int, int, int]:
    """哨兵窗（像素）—— **约定 `(x, y)` 是窗外接矩形的正中心**，不是左上角。

    ⚠️ 半宽/半高走 `None` 哨兵、**在调用时**读模块常量，而不是写成值默认值：
    值默认值在 `def` 执行（= import 本模块）时就**绑死**了，改常量对它无效 ——
    那正是 B118 的"常量写对了、仪器读的是别处"。哨兵让"读常量"成为唯一路径。
    """
    x_half = ROW_ARROW_X_HALF if x_half is None else x_half
    dy_half = ROW_ARROW_DY_HALF if dy_half is None else dy_half
    return (x - x_half, y - dy_half, x + x_half, y + dy_half)


def row_arrow_spot(image: Image.Image, *, label: str, x: int, y: int) -> RowArrowProbe:
    """在 `(x, y)` 的哨兵窗里找**一块**够大的琥珀连通域；找不到就**如实报 0**（不抛）。

    ⚠️ **几何与剖面取的是同一个东西**（t24/amend 1）：两者都限在 `clusters[0]` 自己的外接框里。
    旧版剖面取**整窗**（22×30），于是「真箭头完整在窗内 + 窗里另有一小块琥珀（隔一列空白）」
    会让整窗剖面冒出**中间 0 列** ⇒ 判红，而失败文本还说成"窗里有琥珀但不像那枚控件"——
    把话说反了（像的**就是**它）。4 连通域的外接框内部**不可能**出现整列为空的列（连通路径
    逐列走过），所以限到框内之后，"中间 0 列"只在**簇自己长出来的**断续形状上出现。
    窗里另有 ≥`ROW_ARROW_MIN_AMBER` 的旁路簇时，如实写进 :attr:`RowArrowProbe.aside`（说明）。
    """
    x0, y0, x1, y1 = row_arrow_crop_box(x=x, y=y)
    crop = image.convert("RGB").crop((x0, y0, x1, y1))
    mask = amber_mask(crop)
    clusters = amber_clusters(mask)
    if not clusters:
        return RowArrowProbe(label, x0, x1, 0, None, "窗内一个琥珀像素都没有")
    count, cx0, cy0, cx1, cy1 = clusters[0]
    width, height = cx1 - cx0 + 1, cy1 - cy0 + 1
    if count < ROW_ARROW_MIN_AMBER:
        return RowArrowProbe(
            label, x0, x1, count, None, f"最大连通域只有 {count} 像素（<{ROW_ARROW_MIN_AMBER}）"
        )
    own = [row[cx0 : cx1 + 1] for row in mask[cy0 : cy1 + 1]]
    spot = RowArrowSpot(
        label=label,
        x=x0 + (cx0 + cx1 + 1) // 2,
        x0=x0 + cx0,
        x1=x0 + cx1,
        amber=count,
        width=width,
        height=height,
        profile=_trim_zeros(_column_profile(own)),
    )
    strays = [c for c in clusters[1:] if c[0] >= ROW_ARROW_MIN_AMBER]
    aside = ""
    if strays:
        where = "、".join(
            f"{c} 像素 @ x {x0 + bx0}–{x0 + bx1} / y {y0 + by0}–{y0 + by1}"
            for c, bx0, by0, bx1, by1 in strays
        )
        aside = f"窗内另有 {len(strays)} 处琥珀（{where}）—— 窗里别的东西，不进这枚箭头的读数"
    return RowArrowProbe(label, x0, x1, count, spot, aside=aside)


def _profile_monotone(profile: tuple[int, ...], *, up: bool) -> bool:
    """剖面是否单调（`up=True` 非减、`False` 非增）。**允许相等步**：真箭头是 3→4→6→…→20。

    为什么单调是承重的：矩形/平色在剖面上是**常数**（跨度 0，已被跨度下界拦掉），而"断续"
    （隔列有、隔列无）与"锯齿"（高矮交替）跨度**不小**、只有单调性拦得住。
    """
    steps = list(itertools.pairwise(profile))
    return all(a <= b for a, b in steps) if up else all(a >= b for a, b in steps)


def row_arrow_shape_faults(spot: RowArrowSpot) -> tuple[str, ...]:
    """一枚箭头的**形状/大小**逐项体检：返回不过的项（空元组 = 合规）。**纯函数**（只读读数）。

    这是 t24 补的那一族判据的**唯一出口**（`require_row_arrows` 与失败文本都走它），
    所以"放宽/收紧"只可能发生在一处；界全在 `ROW_ARROW_WIDTH_*` / `HEIGHT_*` / `ASPECT_*` /
    `PROFILE_SPREAD_MIN` 里，**没有散在代码里的数字**。
    """
    faults: list[str] = []
    aspect = spot.width / spot.height if spot.height else 0.0
    fill = spot.amber / (spot.width * spot.height) if spot.width and spot.height else 0.0
    profile = spot.profile
    spread = (max(profile) - min(profile)) if profile else 0
    if not ROW_ARROW_WIDTH_MIN <= spot.width <= ROW_ARROW_WIDTH_MAX:
        faults.append(f"宽 {spot.width} 不在 {ROW_ARROW_WIDTH_MIN}–{ROW_ARROW_WIDTH_MAX}")
    if not ROW_ARROW_HEIGHT_MIN <= spot.height <= ROW_ARROW_HEIGHT_MAX:
        faults.append(f"高 {spot.height} 不在 {ROW_ARROW_HEIGHT_MIN}–{ROW_ARROW_HEIGHT_MAX}")
    if not ROW_ARROW_ASPECT_MIN <= aspect <= ROW_ARROW_ASPECT_MAX:
        faults.append(
            f"宽高比 {aspect:.2f} 不在 {ROW_ARROW_ASPECT_MIN:.2f}–{ROW_ARROW_ASPECT_MAX:.2f}"
        )
    if fill < ROW_ARROW_FILL_MIN:
        faults.append(
            f"填充 {spot.amber}/{spot.width}×{spot.height} = {fill:.3f} < {ROW_ARROW_FILL_MIN}"
            "（**空心描边/轮廓**：宽、高、比、跨度、单调**全都合规**，只有这一条拦得住 ——"
            "一枚箭头是**实心面**，不是描边）"
        )
    if spread < ROW_ARROW_PROFILE_SPREAD_MIN:
        faults.append(
            f"剖面跨度 {spread} < {ROW_ARROW_PROFILE_SPREAD_MIN}"
            "（平剖面：竖条/等宽矩形/整窗平色都长这样，且平剖面的镜像恒真）"
        )
    if 0 in profile:
        faults.append("剖面中间夹着 0 列（断续形状 ⇒ 不是一枚实心箭头）")
    if not (_profile_monotone(profile, up=True) or _profile_monotone(profile, up=False)):
        faults.append(f"剖面既不单调增也不单调减（{list(profile)}）")
    return tuple(faults)


def row_arrow_shape_ok(spot: RowArrowSpot) -> bool:
    """形状/大小合规 = 上面那族体检一项不过都没有（判据入口；**阴性也要有读数**见下）。"""
    return not row_arrow_shape_faults(spot)


def row_arrow_shape_note(spot: RowArrowSpot) -> str:
    """把「形状/大小」的**实测 + 界 + 逐项结论**印成一行 —— 合规也印（阴性也要有读数）。

    有了它，失败文本能当场分开两件**动作不同**的事：**窗内琥珀不足**（`spot is None`：
    查坐标/查这一屏）与**形状/大小不符**（东西在、读数也进了判据，只是它不像那枚控件）。
    """
    profile = spot.profile
    spread = (max(profile) - min(profile)) if profile else 0
    aspect = spot.width / spot.height if spot.height else 0.0
    fill = spot.amber / (spot.width * spot.height) if spot.width and spot.height else 0.0
    measured = (
        f"实测 宽 {spot.width}／高 {spot.height}／比 {aspect:.2f}／琥珀 {spot.amber} px／"
        f"填充 {fill:.3f}／剖面跨度 {spread}／剖面 {list(profile)}"
    )
    bounds = (
        f"界：宽 {ROW_ARROW_WIDTH_MIN}–{ROW_ARROW_WIDTH_MAX}、高 {ROW_ARROW_HEIGHT_MIN}–"
        f"{ROW_ARROW_HEIGHT_MAX}、比 {ROW_ARROW_ASPECT_MIN:.2f}–{ROW_ARROW_ASPECT_MAX:.2f}、"
        f"填充 ≥{ROW_ARROW_FILL_MIN:.2f}、剖面跨度 ≥{ROW_ARROW_PROFILE_SPREAD_MIN}、"
        f"单调、无中间 0 列"
    )
    faults = row_arrow_shape_faults(spot)
    if not faults:
        return f"  · {spot.label}：形状/大小**合规**（{measured}；{bounds}）"
    return f"  · {spot.label}：**形状/大小不符** —— {'；'.join(faults)}（{measured}；{bounds}）"


def row_arrow_failure_text(
    *,
    reason: str,
    image: Image.Image,
    row_center_y: int,
    x_prev: int,
    x_next: int,
    prev: RowArrowProbe,
    next_: RowArrowProbe,
) -> str:
    """失败文本：**x 区间 + 行带 y + 实测像素计数**（不看代码就能判"没找到"还是"找错了位置"）。

    「找错了位置」长什么样：窗外计数 > 0 —— 有琥珀、只是不在哨兵窗正中 ⇒ 坐标常数写偏了。
    """
    y0, y1 = (
        row_center_y - ROW_ARROW_DY_HALF,
        row_center_y + ROW_ARROW_DY_HALF,
    )
    lines = [
        f"[失败] 点 ◀/▶ 之前的自检没过（{reason}）—— **一个鼠标键也没送出去**。",
        f"  行带 y {y0}–{y1}（行心 y={row_center_y}，由 L7 定位到的那一行给出：",
        f"    `rule_row_sitai` 命中 y + ROW_TITLE_TO_ROW_CENTER_DY({ROW_TITLE_TO_ROW_CENTER_DY})）；",
        (
            f"  期望的 x 区间：◀ {x_prev - ROW_ARROW_X_HALF}–{x_prev + ROW_ARROW_X_HALF}"
            f"（`ROW_ARROW_PREV_X`={x_prev}）／"
            f"▶ {x_next - ROW_ARROW_X_HALF}–{x_next + ROW_ARROW_X_HALF}"
            f"（`ROW_ARROW_NEXT_X`={x_next}）；哨兵窗 ±{ROW_ARROW_X_HALF}×±{ROW_ARROW_DY_HALF} px"
        ),
        f"  实测：{prev.report_line()}",
        f"  实测：{next_.report_line()}",
        (
            f"  判据：{_amber_rule_text()}，且要求**互成镜像**（"
            f"`row_arrow_profiles_mirror`，逐列容差 {ROW_ARROW_PROFILES_MIRROR}）；"
            f"一枚箭头的琥珀下限 {ROW_ARROW_MIN_AMBER} 像素；"
            f"并且**形状/大小**要落在界内（`row_arrow_shape_faults`）——"
            f"平剖面的镜像**恒真**，所以「互镜像」这一条单独认不出一枚箭头（t24 修的 F1）。"
        ),
    ]
    # ── 逐窗归因（**每一侧只看自己那一窗的证据**）──────────────────────────────
    # 为什么要分开：B118 的现场，「缺一支」与「位置写偏了」在**汇总**读数上同形
    # （各窗都是 0），于是"缺 ◀"曾被读成"坐标不对"。这里按侧印：有琥珀的一侧说
    # "位置/形状"，没有的一侧说"这个 x 上没有" —— 两种情形由**证据自己**分开。
    drift = False
    for probe in (prev, next_):
        if probe.spot is not None:
            continue
        near = nearest_amber_run(image, row_center_y=row_center_y, x=probe.centre_x)
        if probe.amber:
            drift = True
            lines.append(
                f"  · {probe.label}：窗内**有** {probe.amber} 像素琥珀，但不成「一枚箭头」"
                f"（{probe.why}）⇒ 位置没写偏，没过的是**形状/大小**那一条。"
            )
        elif near:
            drift = True
            lines.append(
                f"  · {probe.label}：窗内 0；但 ±{ROW_ARROW_NEARBY_SEARCH} px 内有琥珀 "
                f"{near} ⇒ **位置写偏了**（改 `ROW_ARROW_*` 常量，**别改判据**）。"
            )
        else:
            lines.append(
                f"  · {probe.label}：窗内 0，且 ±{ROW_ARROW_NEARBY_SEARCH} px 内也没有琥珀 "
                "⇒ **这一个 x 上没有**。"
            )
    # ── 形状/大小的逐窗读数（**合规也印**：阴性也要有读数）──────────────────────
    shape_bad = [
        spot
        for spot in (prev.spot, next_.spot)
        if spot is not None and not row_arrow_shape_ok(spot)
    ]
    lines.extend(row_arrow_shape_note(spot) for spot in (prev.spot, next_.spot) if spot is not None)
    if shape_bad:
        detected = "、".join(spot.label for spot in shape_bad)
        lines.append(
            f"  ⇒ **不是「这一屏没有箭头」**：{detected} 确实检出了候选、整块读数也进了判据，"
            "拦住的是**形状/大小/填充**那一条 —— 上面逐窗印的「实测 ／ 界」就是原因。"
            "（t8 的形状动物园：竖条 / 等宽矩形 / 整窗平色 / 1 px 空心轮廓都能骗过「只比镜像」的"
            "旧判据；真箭头是 11 列 × 20 行、**125 像素**、填充 0.57、剖面单调增、跨度 17。）"
        )
    elif drift:
        lines.append(
            "  ⇒ **不是「这一屏没有箭头」**：上面标了「有琥珀」的那一处，东西在而读数没进判据 "
            "⇒ 先查**坐标**与**形状**（B118：颜色不特异、退化的读数会自证满分）。"
        )
    else:
        lines.append(
            f"  ⇒ **上面每一处「窗内 0」的哨兵窗、连同它 ±{ROW_ARROW_NEARBY_SEARCH} px 的范围，"
            "一个琥珀像素都没有** —— 这一条**不下**「这一屏没有箭头」的结论，只下得了"
            "「**这些 x 上没有**」（同族：搜不到文件时点名搜过哪些路径）。"
        )
        lines.append(
            "  ⇒ 先判这一帧是不是真的停在规则窗、我们那一行在不在画面里；"
            "**不许**为了让它过而改判据（B118）。"
        )
    return "\n".join(lines)


def require_row_arrows(
    image: Image.Image,
    *,
    row_center_y: int,
    x_prev: int | None = None,
    x_next: int | None = None,
) -> tuple[RowArrowSpot, RowArrowSpot]:
    """点击前的自检：两枚箭头都在、且互成镜像 ⇒ 放行；否则抛 :class:`RowArrowCheckError`。

    ⚠️ `x_prev` / `x_next` 缺省（`None`）＝**在调用时**读 :data:`ROW_ARROW_PREV_X` /
    :data:`ROW_ARROW_NEXT_X` —— **不是**写成值默认值。理由不是风格：值默认值在 `def` 执行时
    就绑死了，之后改常量对判据**无效**，于是"常量写对了、仪器读的是别处"又能发生（B118 的
    病根）。用例正是拿 monkeypatch 把常量改错、要求自检**当场转红**，来证明这条路径真的被走。
    """
    x_prev = ROW_ARROW_PREV_X if x_prev is None else x_prev
    x_next = ROW_ARROW_NEXT_X if x_next is None else x_next
    prev = row_arrow_spot(image, label="◀（ROW_ARROW_PREV_X）", x=x_prev, y=row_center_y)
    next_ = row_arrow_spot(image, label="▶（ROW_ARROW_NEXT_X）", x=x_next, y=row_center_y)
    missing = [probe.label for probe in (prev, next_) if probe.spot is None]
    if missing:
        raise RowArrowCheckError(
            "没找到箭头",
            row_arrow_failure_text(
                reason="缺 " + "、".join(missing),
                image=image,
                row_center_y=row_center_y,
                x_prev=x_prev,
                x_next=x_next,
                prev=prev,
                next_=next_,
            ),
        )
    assert prev.spot is not None  # 上面已排除 None
    assert next_.spot is not None
    # ⚠️ 次序是承重的：**形状/大小**在**镜像**之前判。平剖面（竖条 / 等宽矩形 / 整窗平色）
    #    的镜像恒真，先判镜像就等于没判 —— t8 的 54 格形状动物园是这么全绿穿过去的（t24/F1）。
    shape_bad = [spot for spot in (prev.spot, next_.spot) if not row_arrow_shape_ok(spot)]
    if shape_bad:
        raise RowArrowCheckError(
            "形状不符",
            row_arrow_failure_text(
                reason="形状/大小不符：" + "、".join(spot.label for spot in shape_bad),
                image=image,
                row_center_y=row_center_y,
                x_prev=x_prev,
                x_next=x_next,
                prev=prev,
                next_=next_,
            ),
        )
    if not row_arrow_assert_mirror(prev.spot.profile, next_.spot.profile):
        raise RowArrowCheckError(
            "镜像不过",
            row_arrow_failure_text(
                reason="两枚箭头的列剖面不互成镜像",
                image=image,
                row_center_y=row_center_y,
                x_prev=x_prev,
                x_next=x_next,
                prev=prev,
                next_=next_,
            ),
        )
    return prev.spot, next_.spot


def unhover_frame(
    hwnd: int,
    *,
    image: Image.Image,
    tries: int | None = None,
    poll: float | None = None,
) -> Image.Image:
    """把光标停到中性点、**等够**、重新抓一张给自检用的帧（t41 的**修因**，判据一字不动）。

    为什么必须修因（Pass A 实测，`tools/out/auto/pass-20260929-024847-harsh/`）：点完 ◀ 之后
    光标正压在 ◀ 上，悬停高亮把那枚箭头的抗锯齿边缘多照亮一列 —— ◀ 琥珀 125→130、簇 11→12 列；
    没被悬停的 ▶ 一个像素没变。`row_arrow_profiles_mirror` 要求两枚**等宽**，于是 12 vs 11 判红，
    而那两枚箭头**各自的**形状体检当天都合规 ⇒ 那是**假阴性**，不是「这一屏没有箭头」。

    修的是**输入条件**（把悬停解掉），不是判据：

    * 不许放宽 `row_arrow_profiles_mirror`，也不许动 `ROW_ARROW_*` 常量；
    * 中性点重抓之后**仍不镜像就照红**（调用方照旧走 `require_row_arrows`，**不拿旧帧顶替**）；
    * 重抓失败时**不抛**、回落成传进来的那张 —— 那是**更严**的方向：悬停态只会更容易判红。

    「等够」的判据是**连续两帧中性一致**（不是拍一个固定秒数）：采样到两张逐字节相同的帧就返回
    后一张；`tries` 张都等不到一致时返回最后一张（光标已经在中性点上、箭头照样是冷的），
    结果交给判据决定 —— 等待时长因此是**量出来的**，不是猜的。

    `tries` / `poll` 缺省时**在调用时**读模块常量（不是定义时绑定）⇒ 用例能把「等不到」那条路
    也量出来（把 `NEUTRAL_TRIES` 压到 1 ⇒ 退回手里那张 ⇒ 悬停帧照样判红）。
    """
    cap = NEUTRAL_TRIES if tries is None else tries
    gap = NEUTRAL_POLL if poll is None else poll
    fallback = image
    ga._set_cursor(*NEUTRAL_CURSOR_XY)
    previous: str | None = None
    latest = image
    for _ in range(max(1, cap)):
        time.sleep(gap)
        try:
            frame = ga.screenshot(hwnd)
        except ga.GameAutoError:
            return fallback
        digest = hashlib.sha256(frame.tobytes()).hexdigest()
        if previous is not None and digest == previous:
            return frame  # 连续两帧中性一致 ⇒ 等够了
        previous = digest
        latest = frame
    return latest


def click_row_arrow(
    hwnd: int,
    *,
    which: str,
    image: Image.Image | None,
    row_center_y: int,
    settle: float = 0.25,
) -> RowArrowSpot:
    """点我们那一行的 ◀/▶：**先自检、后点**；自检不过就抛（**一个鼠标键也不送出去**）。

    这是点这两支箭头的唯一入口。两条硬约束都长在这里：

    * **点击点来自自检的实测像框中心**（`spot.x`），不是任何常量、更不是估计坐标 ——
      第十六遍点 `(958,740)` / `(1266,740)` 时"命中也有真变化、下一支却不动"，
      根因就是那两个是**相邻行**的灰箭头（B118 §3.10 的现读：真控件在我们那一行、
      x 是 1006–1016 / 1343–1353）。坐标正确与否**由自检当时量出来**，事后不靠回忆。
    * **`image is None`（抓不到图）也抛**：没有帧就没有读数，此时唯一正确的动作是出声，
      不是"按估计坐标点一下"（`screenshot` 的两种正确拒绝：前台不是游戏 / 近乎纯色）。
    """
    if which not in ("prev", "next"):
        raise ValueError(f"which 只能是 'prev' 或 'next'，给了 {which!r}")
    if image is None:
        raise RowArrowCheckError(
            "抓不到图",
            "[失败] 点 ◀/▶ 之前的自检没过（**抓不到图**：前台不是游戏 / 被遮挡 / 近乎纯色）"
            " —— **一个鼠标键也没送出去**。\n"
            f"  期望的行带 y {row_center_y - ROW_ARROW_DY_HALF}–"
            f"{row_center_y + ROW_ARROW_DY_HALF}（行心 y={row_center_y}）；"
            f"期望的 x 区间：◀ {ROW_ARROW_PREV_X - ROW_ARROW_X_HALF}–"
            f"{ROW_ARROW_PREV_X + ROW_ARROW_X_HALF}／▶ {ROW_ARROW_NEXT_X - ROW_ARROW_X_HALF}–"
            f"{ROW_ARROW_NEXT_X + ROW_ARROW_X_HALF}；实测像素计数：**没有帧，量不到**。\n"
            "  ⇒ 先修抓图（前台 / 窗口尺寸 / 纯色），**不许**改用估计坐标点（B118 的点击落错行"
            "就是这么来的）。",
        )
    # 🔧 t41：自检前先把光标挪到中性点并**重新抓图** —— 点完上一支箭头之后光标就压在它上面，
    #    悬停高亮会让那一枚多出一列琥珀（125→130、11→12 列），而另一枚一个像素没变，
    #    「两枚互等宽」的镜像要求于是假红（见 `unhover_frame` 的 docstring）。
    #    这一步只改**输入条件**：判据、阈值、常量一个不动；重抓后仍不镜像就照红。
    image = unhover_frame(hwnd, image=image)
    prev_spot, next_spot = require_row_arrows(image, row_center_y=row_center_y)
    spot = prev_spot if which == "prev" else next_spot
    # ⚠️ `_set_cursor` 的签名是 `(x, y)` —— **没有 hwnd**（game_auto 里就是这个签名；
    #    第八遍在这里 TypeError 死过一次）。先把光标放到位、给引擎一帧时间读到它，再送按键。
    ga._set_cursor(spot.x, row_center_y)
    time.sleep(0.3)
    ga.click_client(hwnd, spot.x, row_center_y, settle=settle, force=True)
    return spot


def row_arrow_probe_minimal(prev_profile: tuple[int, ...], next_profile: tuple[int, ...]) -> bool:
    """**阴性的最小定义**：只是"有没有琥珀"与"两头方向对不对"（真判据见 :func:`require_row_arrows`）。

    存在理由（用例的**阴性对照**）：驱动里那一条是**合取**（窗内计数 + 连通域形状 + 镜像），
    用例若只拿"缺一/缺二"当阴性，就说不出**是哪一条**把假样本拦住的。这条最小判据专门接受
    「一支够大、另一支是 0」这种输入（因为它不做镜像），所以它能**证明镜像那一条确实在出力**
    —— 两个箭头形状不同（琥珀都有、镜像不过）时，最小判据 True 而真判据抛
    :class:`RowArrowCheckError`。
    """
    left = _trim_zeros(prev_profile)
    right = _trim_zeros(next_profile)
    return (
        sum(left) >= ROW_ARROW_MIN_AMBER
        and sum(right) >= ROW_ARROW_MIN_AMBER
        and (len(left) < 2 or left[-1] > left[0])
        and (len(right) < 2 or right[0] > right[-1])
    )


def _sig(image: Image.Image) -> bytes:
    """画面指纹（64×36 灰度）—— 只用于判「变了没有」，**不参与任何判据阈值**。"""
    return image.convert("L").resize((64, 36)).tobytes()


def _mean_diff(image: Image.Image, ref: Image.Image) -> float:
    """两张图的比例平均差（0–1）；**先各自降采样到 64×36，再作差**。

    ⚠️ 次序不是小事（2026-09-25 实测）：`|A−B|` 再降采样 **≠** 各自降采样再 `|A−B|`
    —— 19 帧上分别是 0.24003 与 0.50375（`ImageChops.difference` 取绝对值，不是线性算子）。
    选「先缩后差」的理由：仓库里的基准帧是**64×36 缩略图**（`loading-ref-64x36.png`，
    1,889 B —— 用户口径「不必要的不要提交到 git」，队长 02:39 采纳），只有这个次序才与
    它**逐位等价**。判别力不变：载入帧≈0，其余屏 ≥0.19 ⟫ `LOADING_DIFF=0.01`。
    """
    thumb = image.convert("L").resize((64, 36))
    other = ref.convert("L").resize((64, 36))
    return float(ImageStat.Stat(ImageChops.difference(thumb, other)).mean[0]) / 255.0


def _center_std(image: Image.Image) -> float:
    """画面**中央一半**的灰度标准差 —— 用来判「这一帧其实什么都没画」。

    为什么需要这一条（第五遍的硬事实）：`19-main-menu.png` 是**黑屏 + 只有页脚**
    （102 KB；整屏 std 11.19 因页脚那几个亮图标而虚高），它既不是载入画面、又与上一帧
    不同 ⇒ 旧的两条判据全过，可主菜单**根本没画出来**。中央区判据抓得住它
    （中央全黑 ⇒ std≈0），而整屏 std 抓不住。
    """
    width, height = image.size
    box = (int(width * 0.25), int(height * 0.25), int(width * 0.75), int(height * 0.75))
    thumb = image.convert("L").crop(box).resize((64, 36))
    return float(ImageStat.Stat(thumb).stddev[0])


def _is_blank(image: Image.Image) -> bool:
    """中央区近乎纯色 ⇒ 判「还没画出来」（阈值是启发式，不是口径阈值）。"""
    return _center_std(image) < BLANK_STD


#: 口径 §2 的 ROI 起始值（**比例矩形**，与观察者局的 `BOTTOM_ROI` 同一手法）。
#: ⚠️ 首跑校正改的是这些常量，判据一个字不改（口径 §2 的原话）。
ROIS: dict[str, tuple[float, float, float, float]] = {
    # 🔧 2026-09-25 首跑侦察实机校正（口径 §2「起始值，首跑校正」）：原来的
    #    (0.00,0.15,0.45,0.95) 中心落在 (432,594) —— 主菜单左栏按钮下方**空白处**，
    #    点在「新游戏」与「账号」图标之间，两帧都没走到目标屏（21 帧拍到的其实是
    #    被误点的「Paradox 账号」对话框）。据 19-main-menu.png 实测：「新游戏」按钮
    #    的像框是 x∈[236,520], y∈[414,454]（1920×1080），故把 ROI 收紧到按钮本身：
    #    中心 (378,434) = 按钮正中，同时它也是 L4 的判据区（模板只在这一带搜）。
    "main_menu": (0.105, 0.350, 0.290, 0.455),
    # 🔧 2026-09-25 03:0x 第二处实机校正（据第六遍的 `20-setup-screen.png` —— 那一帧**真的**
    #    是「目标」屏）：底栏的「游戏规则」按钮实测在 x∈[465,594], y∈[807,847]（1920×1080），
    #    即中心 ≈(526,827)。原来的 ROI 中心 (384,874) 在它**左下方**，所以 L6 点空
    #    （它现在还两次点在主菜单的「账号」图标上 —— 那条路径已由 L4 的模板判据挡住）。
    "setup_rules": (0.230, 0.740, 0.325, 0.795),
    # 同一帧量的「开始游戏」（绿色，右侧）在 x∈[1666,1819], y∈[654,702] ⇒ 中心 ≈(1743,678)；
    # 原来的 (0.60,0.68,1.00,0.94) 中心 (1536,875) 落在按钮**下方**的说明文字上。
    "setup_start": (0.855, 0.595, 0.965, 0.665),
    "rules_window": (0.22, 0.06, 0.78, 0.94),
    # 日志条目面板实测开在**左侧**（t38 量测：left 53 / top 73 / right 612，bottom=994 是约定值
    # ——那帧下沿描边量不出来，依据是内容末行 856 + 余量，理由见 docs/design/exec/阶段6-实机读数.md §5）。
    # 旧值 (0.64, 0.04, 1.00, 0.98) 会按**右半屏**找三行 ⇒ 必 MISS（只是坐标修正，判定语义未改）。
    "je_panel": (0.0276, 0.0676, 0.3188, 0.9204),
}


#: **正向判据表**：这一步点完之后，**目标屏的哪个模板必须出现**（模板名, ROI 名）。
#: 为什么只有 L5 现在有：目标屏（「目标」屏）的 `btn_game_rules` 已裁好且自证过
#: （1.0000 自匹配 / 主菜单上 0.0145）⇒ L5 可以用它当「真的到了目标屏」的凭据。
#: L6 还没有规则窗的模板（正是这一遍要收的素材），故退到「变了 + 画好了 + **画面停下来了**」；
#: 等规则窗模板裁出来，L6 也能装正向判据。
#: 🚫 **不要用「上一屏的模板消失」当判据**（第七遍那样写过，被实机否掉）：
#: `find_in_roi` 把抓图失败也返回 `None`，而且模板对悬停/高亮态敏感 —— 两个漏洞都会
#: 把「其实还在主菜单」读成「已经离开了」。
NEXT_SCREEN: dict[str, tuple[str, str]] = {
    "L5 点「新游戏」": ("btn_game_rules", "setup_rules"),
}


@dataclass
class Step:
    """一步：名字 / 要点的模板 / 判据 ROI / 证据帧 / 说明。"""

    name: str
    template: str
    roi: str
    frame: str
    why: str


#: 口径 §2 的步骤表（L 编号与那份文档逐条对应）。`template == ""` = 这一步不靠模板
#: （启动、等待、切换后台这类），侦察模式下唯一允许"点估计坐标"的是带 `est` 的步骤。
STEPS: tuple[Step, ...] = (
    Step(
        "L4 启动到主菜单", "", "main_menu", "19-main-menu", "起游戏（不加载期碰窗口），等启动安静"
    ),
    Step("L5 点「新游戏」", "btn_new_game", "main_menu", "20-setup-screen", "主菜单左栏 → 目标屏"),
    Step(
        "L6 打开规则窗",
        "btn_game_rules",
        "setup_rules",
        "21-rules-window",
        "目标屏底栏左半 → 规则窗",
    ),
    Step(
        "L7 定位我们的卡片",
        # 🔧 2026-09-25 订正：定位物是**行标题**「处境难度」（`rule_row_sitai`，像框
        #    (970,676,1066,706)，阈值 = `ROW_LOCATOR_THRESHOLD`（真值只在 :141 = **0.64**；
        #    t24/F3 把这里旧注释里的 0.90 改准 —— 0.90 是**别的模板**量的），不是原来的
        #    `rule_card_title_sitai`
        #    （那个名字从没落盘过 ⇒ 两段式检查会把它报成"缺模板"，而其实我们已经有定位物了）。
        "rule_row_sitai",
        "rules_window",
        "22-rule-sitai",
        "卡片可能在折叠线下 ⇒ 拖滚动条到命中为止",
    ),
    Step(
        "L8 逐档读到", "tier_*", "rules_window", "23-tier", "档名 + 说明首段 + 说明尾段三条都命中"
    ),
    Step(
        "L9 应用并落定",
        "btn_rules_apply",
        "rules_window",
        "24-after-apply",
        "**必须点「应用」**（只关窗不生效）",
    ),
    Step(
        "L10 选 RUS",
        "card_country_rus",
        "setup_rules",
        "25-country-rus-selected",
        "推荐国家卡片（不靠地图点选）",
    ),
    Step(
        "L11 开始游戏",
        "btn_start_game",
        "setup_start",
        "26-ingame-after-start",
        "启动要可行（没选国时它是灰的）",
    ),
    Step(
        "L12 放冲击",
        "btn_probe_decision",
        "bottom",
        "27-decisions-armed",
        "点探针决议：不点就没有记忆变量",
    ),
    Step("L14 G3 三行", "je_line_*", "je_panel", "28-je-panel", "三行各自的首段模板都命中"),
    Step("L15 修正旁证", "chip_tier_*", "je_panel", "29-modifier-chip", "旁证，不是承重墙"),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_load() -> Path:
    return experiments.CONTENT_LOAD


def parse_xy(text: str) -> tuple[int, int] | None:
    """``--click 864,1055`` 这类显式坐标（侦察用：模板还没收时的唯一合法入口）。"""
    if not text:
        return None
    left, _, right = text.partition(",")
    return int(left), int(right)


def estimate_xy(
    roi: tuple[float, float, float, float], *, size: tuple[int, int]
) -> tuple[int, int]:
    """ROI 的**几何中心**当成侦察点击点（首跑唯一的依据：口径 §2 的 ROI 起始值）。"""
    width, height = size
    x0, y0, x1, y1 = roi
    return int((x0 + x1) / 2 * width), int((y0 + y1) / 2 * height)


#: 模板查找的**三态**（2026-09-25，队长 ③c 要求显式化）：
#: `game_auto.find_in_roi` 把「**抓不到图**」与「**确实没有**」都折成 `None` —— 它自己的
#: docstring 就写了「要区分『看不到』与『没有』的调用方请直接用 `screenshot`」。这两态导出
#: **相反的行动**：一个该继续等、一个该报错。混在一起时日志里长得一模一样，正是今天一路在
#: 清的那族假信号（同族：文件名≠内容、mtime≠走到哪一屏、`error.log` 干净≠修好了）。
LOOKUP_HIT = "命中"
LOOKUP_ABSENT = "确实没有"
LOOKUP_UNSEEN = "抓不到图"


def locate_state(
    hwnd: int,
    name: str,
    *,
    roi: tuple[float, float, float, float],
    threshold: float = ga.DEFAULT_THRESHOLD,
    directory: Path | None = None,
) -> tuple[str, object, str]:
    """三态查找：返回 `(状态, Match 或 None, 说明)`。

    抓不到图（不是前台 / 被遮挡 / 近乎纯色）**不当作"没有"**：它单独一态，调用方必须
    **出声**（P13）而不是静默当成"这一步没达成"。命中时 Match 的坐标已经**按 ROI 位移回
    全屏坐标系**（与 `find_in_roi` 同一手法，否则点击会打到 ROI 左上角）。

    ⚠️ **第四种情形不在三态里**：`hwnd` 失效（窗口没了、游戏退出）时 `_client_size` 会抛
    `pywintypes.error`（实测：`GetClientRect` ⇒ `(1400, '无效的窗口句柄。')`）—— 它**直接
    往外抛**，因为那种时候"继续等"没有意义、必须立刻出声。⇒ 三态描述的是"**这一瞬读不到
    屏幕**"，不是"窗口不存在"。
    """
    try:
        image = ga.screenshot(hwnd, roi=roi)
    except ga.CaptureFailedError as exc:
        return LOOKUP_UNSEEN, None, str(exc)
    found = ga.locate_optional(
        image, name, threshold=threshold, first_hit=True, directory=directory
    )
    if found is None:
        return LOOKUP_ABSENT, None, ""
    dx, dy = ga._roi_offset(hwnd, roi)
    return LOOKUP_HIT, ga._shift_match(found, dx, dy), ""


def locate_in_frame(
    image: Image.Image,
    name: str,
    *,
    roi: tuple[float, float, float, float],
    threshold: float = ga.DEFAULT_THRESHOLD,
    directory: Path | None = None,
) -> tuple[object | None, float]:
    """在**已经在手上的这一帧**里找模板：返回 `（命中或 None，最高分）`（t41）。

    与 :func:`locate_state` 的分工：那条走「**再抓一张图**」（适合「等某屏出现」的轮询），
    这条走「**就是这一帧**」—— L8 的「档名 + 说明首段 + 说明尾段在**同一帧**里各自命中」与
    L9 的「关窗重开后读到的还是刚才那一档」都必须同帧；反复抓图会把两帧之间的差（悬停、动画、
    光标、加载）混进判据里，那正是这一路假信号的来源。

    返回 `None` 只表示「这一帧里没到阈值」，**不表示抓图失败** —— 抓图失败是调用方拿到 `None` 帧时
    就该处理的事（P13：看不到 ≠ 没有）。分数读数**总是**给出（没过阈值时再按 `threshold=0.0`
    取一次最高分），让判据列能点名「差多少」，不让报告里只剩一句「不命中」。
    """
    box = ga.roi_box(roi, *image.size)
    crop = image.crop(box)
    found = ga.locate_optional(crop, name, threshold=threshold, first_hit=True, directory=directory)
    if found is not None:
        return ga._shift_match(found, box[0], box[1]), float(found.score)
    best = ga.locate_optional(crop, name, threshold=0.0, first_hit=True, directory=directory)
    return None, (float(best.score) if best is not None else 0.0)


def read_tier(
    image: Image.Image,
    *,
    tiers: Sequence[str],
    roi: tuple[float, float, float, float],
    directory: Path | None = None,
) -> tuple[str, str]:
    """读出这一帧显示的是**哪一档**：几张档名模板里**恰一张**命中才算读到（t41）。

    零张（模板都没命中）与多张（两张同时过阈值）**都算读不出** —— 读不出就报，
    **绝不**假定默认中间档（口径 §3.2 / §7）。返回 `（档名或 ""，为什么）`。
    提到模块级是因为这条判据**必须能单独被测**：承重遍「读不出是哪一档」的处置是
    「报错停手」，不是「用默认档接着跑」。
    """
    hits: list[str] = []
    for name in tiers:
        tmpl = f"tier_{name}_name"
        if directory is not None and not (directory / f"{tmpl}.png").is_file():
            continue  # 没这张模板就无从读它（承重遍走不到：缺模板检查已拦在前面）
        found, score = locate_in_frame(image, tmpl, roi=roi, directory=directory)
        if found is not None:
            hits.append(f"`{name}` {score:.6f}")
    if len(hits) == 1:
        return hits[0].split("`")[1], f"档名读数 {hits[0]}"
    if not hits:
        return "", "三张档名模板**一张都没命中** ⇒ 读不出是哪一档"
    return "", f"多张档名模板同时命中（{'、'.join(hits)}）⇒ 读不出是哪一档"


def tier_evidence(
    image: Image.Image,
    name: str,
    *,
    roi: tuple[float, float, float, float],
    directory: Path | None = None,
) -> tuple[bool, str]:
    """**同帧**判据：`tier_<name>` 的档名 + 说明首段 + 说明尾段三块各自命中（t41）。

    「同一帧」是承重的：三块分别抓三次图，中间任何一次悬停/动画/光标变化都会混进判据里。
    缺模板文件**不是**「没命中」：`load_template` 会抛 `TemplateNotFoundError`。收料遍
    （`--collect`）的善意目标是「缺模板也留帧」⇒ 缺文件记 `缺模板✗` 并**照样**判不过
    （判据一点不放松，只是把 traceback 换成能读的一句话）。
    """
    parts: list[str] = []
    ok = True
    for suffix in ("name", "desc_head", "desc_tail"):
        tmpl = f"tier_{name}_{suffix}"
        if directory is not None and not (directory / f"{tmpl}.png").is_file():
            parts.append(f"{suffix} 缺模板✗")
            ok = False
            continue
        found, score = locate_in_frame(image, tmpl, roi=roi, directory=directory)
        parts.append(f"{suffix} {score:.6f}{'✓' if found is not None else '✗'}")
        ok = ok and found is not None
    return ok, "、".join(parts)


def apply_outcome(*, want: str, after: str, evidence_ok: bool) -> tuple[str, str]:
    """点「应用」→ 关窗 → 重开之后**读回来的那一档**就是判据（t41 / 口径 §3.2）。

    返回 `（判据，说明）`：读回来等于 `want` ⇒ `"过"`；不等 ⇒ `"不过"`，并点名这正是
    「**只 Hide 没 ApplySettings**」的形态（关窗与点背景都只 `Hide`，不落定）；读不出来
    （`after == ""`）也 `"不过"` —— 量不到就不许当它过了（P13）。
    """
    if not after:
        return "不过", f"重开之后读不出是哪一档 ⇒ 应用 `{want}` 落没落定量不到"
    if after != want:
        return "不过", f"应用 `{want}`、关窗重开之后读到 `{after}` ⇒ **只 Hide 没 ApplySettings**"
    if not evidence_ok:
        return "不过", f"重开读到 `{after}`，但它的三块模板没在同一帧各自命中"
    return "过", f"应用 `{want}` → 关窗 → 重开读到的还是 `{want}`"


def tick_outcome(before: ga.TickMark, after: ga.TickMark) -> tuple[str, str]:
    """L11「时间真的在往前走」的判词：**先显式取 `.tick`** 再比（t48）。

    返回 `（判据，说明）`。`ga.is_later(before: str, after: str)` 只吃**字符串** —— 它内部
    第一句就是 `parse_tick_date` 的 `text.strip()` —— 把 `TickMark` 对象直接喂进去必
    `AttributeError`，而那个异常会把 L12–L16 整段挡在 `finally` 后面（**链断在这里**，
    不是判红）。所以这一层必须存在，且必须**显式**取 `.tick`。

    点击前**读不到** tick 时不走递增判：quarantine 之后日志本该是空的，这一遍的真判据是
    `wait_until_readable` 的「`Processing Tick:` 从无到有」；读得到就得**真的**往前
    （停在同一 tick 不算推进，`is_later` 对解析不出的字符串一律给 False）。
    """
    if not before.readable:
        return "过", f"点击前读不到 tick ⇒ 这一遍按「从无到有」判（{after.describe()}）"
    if ga.is_later(before.tick, after.tick):
        return "过", f"{before.describe()} → {after.describe()}"
    return "不过", f"tick 没往前走：{before.describe()} → {after.describe()}"


def roi_of(name: str) -> tuple[float, float, float, float]:
    """按名字取 ROI：驱动自己的 :data:`ROIS` 优先，缺的按名字回落到 `game_auto` 的同名 ROI。

    存在的理由（t41）：`STEPS` 表里 L12 的 ROI 写作 `"bottom"` —— 那是 `game_auto` 的
    `BOTTOM_ROI`（决议弹窗在屏幕底部），驱动从来没把它抄进 `ROIS`。取证执行器走表执行，
    所以这层查找必须**显式**存在：查不到就抛，**不许**悄悄退回全帧（全帧会把任何角落的
    噪声当成命中，那是假绿的常见来源）。
    """
    if name in ROIS:
        return ROIS[name]
    if name == "bottom":
        return ga.BOTTOM_ROI
    raise KeyError(f"ROI 未定义：{name!r}（`ROIS` 与 `game_auto` 里都没有这个名字）")


def template_dir(lang: str) -> Path:
    return TEMPLATE_ROOT / LANGS[lang]


def require_templates(lang: str, names: Sequence[str]) -> list[str]:
    """取证模式：缺哪个模板就点名报错（P13 —— 不许静默降级成"估计坐标点一下"）。"""
    base = template_dir(lang)
    missing = [name for name in names if not (base / f"{name}.png").is_file()]
    if missing:
        raise SystemExit(
            f"[失败] 模板缺失（{base}）：{'、'.join(missing)}\n"
            "  ⇒ 先跑一次侦察（`--recon`）收帧，再把模板裁进 "
            f"{base}/；缺模板时**不许**按估计坐标取证（口径 §7：不许静默降级）。"
        )
    return []


#: **硬模板**：走到规则窗为止所需的那些 —— 缺了必须在**第一次改动用户环境之前**拒。
#: 其余模板是 LATER：缺了**在走到那一步时**点名报「未达成」，既不静默跳过、也不整局挡住。
#: 为什么分两段（2026-09-25，队长批准并加三条硬条件）：in-game 那几个模板只能从"跑到
#: in-game 的帧"里裁；若要求全齐才开跑，连 L8/L9（`rule_row_sitai` 与 `btn_rules_apply`
#: 都已在盘上）都跑不了 —— 而"缺哪几个就报哪几个"本身就是下一遍的施工清单。
HARD_TEMPLATES: tuple[str, ...] = ("btn_new_game", "btn_game_rules")


def step_template_gaps(lang: str) -> list[tuple[str, str]]:
    """LATER 级的缺口清单：`[(步骤名, 缺的模板名), …]`（只报缺口，判据不动）。"""
    base = template_dir(lang)
    gaps: list[tuple[str, str]] = []
    for step in STEPS:
        if not step.template or "*" in step.template:
            continue  # 通配的（`tier_*` / `je_line_*` / `chip_tier_*`）由各步自己展开后核
        if step.template in HARD_TEMPLATES:
            continue
        if not (base / f"{step.template}.png").is_file():
            gaps.append((step.name, step.template))
    return gaps


#: **通配步的展开表**（2026-09-25 队长 ③b：静态缺口表看不见这三步，牙必须长在运行时）。
#: 这三步都是"跑起来之后才知道自己需要哪些模板"的那种：`tier_*` 三档 × 三段文案、
#: `je_line_*` 三行、`chip_tier_*` 三档旁证。
WILDCARD_EXPAND: dict[str, tuple[str, ...]] = {
    "tier_*": (
        "tier_history_friendly_name",
        "tier_history_friendly_desc_head",
        "tier_history_friendly_desc_tail",
        "tier_uniform_name",
        "tier_uniform_desc_head",
        "tier_uniform_desc_tail",
        "tier_harsh_name",
        "tier_harsh_desc_head",
        "tier_harsh_desc_tail",
    ),
    "je_line_*": ("je_line_goal", "je_line_pressure", "je_line_last_change"),
    "chip_tier_*": ("chip_tier_history_friendly", "chip_tier_uniform", "chip_tier_harsh"),
}


def step_templates(step: Step) -> tuple[str, ...]:
    """这一步**真正需要**的模板名（通配按 :data:`WILDCARD_EXPAND` 展开成具体名字）。"""
    name = step.template
    if not name:
        return ()
    if "*" in name:
        return WILDCARD_EXPAND.get(name, ())
    return (name,)


def step_missing_templates(step: Step, lang: str) -> tuple[str, ...]:
    """**运行时牙**：这一步缺哪些模板（通配步也能点名 —— 静态表覆盖不到它们）。

    调用方在**走到这一步**时调它：非空就判「未达成（缺模板 …）」并**出声**，
    既不静默跳过、也不假装通过（队长 04:2x 硬条件 2）。
    """
    base = template_dir(lang)
    return tuple(n for n in step_templates(step) if not (base / f"{n}.png").is_file())


def missing_template_policy(step: Step, lang: str, *, discovery: bool) -> tuple[str, bool]:
    """缺模板时的**处置**：返回 `(判据列文本, 是否停)`。

    ⚠️ **两态必须分开**（队长 06:5x 点破的一处自锁）：若"缺模板即停"对所有遍都生效，
    **发现式那一遍会在 L8 停住 ⇒ 永远走不到国家屏**，而 `card_country_rus`(L10) /
    `btn_start_game`(L11) 与 L8 那 9 个逐档模板要裁的帧**一张都拿不到** ——
    两遍式的第一遍**全部意义**就是产出这些素材。所以：

    * **发现式**（``discovery=True``）：缺模板**照样往前走**，判据列如实写「未判定（缺模板 …）」——
      不盲试、不静默跳过，但**也不停**；
    * **有判据的一遍**（``discovery=False``）：缺模板**停** —— 不许在没有判据的情况下往前走。

    与方案 (A) 那一遍的经验一致：那次 `btn_rules_close` 缺席**该停**，是因为**那条路已经走完了**；
    而通往国家屏的路还没走完。
    """
    missing = step_missing_templates(step, lang)
    if not missing:
        return "", False
    names = "、".join(f"`{name}`" for name in missing)
    if discovery:
        note = (
            f"未判定（缺模板 {names}）—— **发现式继续前进**（不停：停下就永远拿不到 "
            "`card_country_rus` / `btn_start_game` / 逐档模板的素材）"
        )
        return note, False
    return (
        f"未达成（缺模板 {names}）—— **有判据的一遍在此停**（不许无判据前进）",
        True,
    )


def teeth_table(lang: str) -> list[tuple[str, str, str]]:
    """逐步骤的**牙清单**：`[(步骤名, 牙的档位, 说明), …]`（只供报告与复核，不参与判定）。

    档位：`静态牙（起局前拒）` / `静态牙（走到时点名）` / `运行时牙（通配展开）` /
    `无模板步骤（判据在代码里）`。
    """
    rows: list[tuple[str, str, str]] = []
    # ⚠️ 这张表的第一版在这里错了一次（值得留着）：`step_template_gaps` 返回的是
    #    `(步骤名, 模板名)`，我却拿**模板名**去查一张**按步骤名做键**的字典 ⇒ 条件恒真、
    #    于是每个具名步都报「齐」—— 连 L10/L11/L12 那三个确实缺模板的也报齐。
    #    「检查器报了错误的事实」正是今天一路在清的那一族 ⇒ 这里改成按**模板名集合**查。
    gapped_templates = {tpl for _name, tpl in step_template_gaps(lang)}
    for step in STEPS:
        needed = step_templates(step)
        if not needed:
            rows.append((step.name, "无模板步骤（判据在代码里）", f"template={step.template!r}"))
            continue
        if step.template in HARD_TEMPLATES:
            rows.append((step.name, "静态牙（起局前拒）", f"缺 ⇒ 起局前拒：{step.template}"))
            continue
        if "*" in step.template:
            missing = step_missing_templates(step, lang)
            detail = f"通配 {step.template} ⇒ 需 {len(needed)} 个"
            detail += f"；**现在缺 {len(missing)}**：{'、'.join(missing)}" if missing else "；齐"
            rows.append((step.name, "运行时牙（通配展开）", detail))
            continue
        detail = (
            f"**现在缺** {step.template}"
            if step.template in gapped_templates
            else f"齐（{step.template}）"
        )
        rows.append((step.name, "静态牙（走到时点名）", detail))
    return rows


#: L13（口径 `:81`）= **脚本侧判据**：它不是截图步，是**日志行牙**（口径 `:83` 还写明 L15 只是
#: 旁证、「真正承重的是 L13」）。所以要显式列出"期望哪几行、值是什么"，缺行与值错**分开报**。
PROBE_LINE = re.compile(r"ZZPROBE AB;(?P<kind>[A-Z]+);(?P<rest>[^\"\r\n]*)")


@dataclass(frozen=True)
class LogFact:
    """一条日志行牙：要在 `debug.log` 里看到 `ZZPROBE AB;<kind>;<rest…>`，且某字段等于期望值。

    ``setting`` 非空时还要**先按 `rest[0]` 认行**（`RULE;<设置名>;<yes|no>;<国名>`）——
    这一点自检第一版做错了：不认设置名 ⇒ 三档的期望全拿去比**同一行**，于是**正确的日志
    也被判成错的**（检查器又报了错误的事实，与今天其他几次同族）。
    """

    name: str
    kind: str
    want: str
    where: int  # 取值在 rest 里的第几段（0 起）
    why: str
    setting: str | None = None


def difficulty_log_expectations(tier: str) -> tuple[LogFact, ...]:
    """本局档位 = ``tier`` 时要看到的行 —— **按两族分开**（口径 `:81` 与 §3.3）。

    ⚠️ 自检第二版在这里纠过一个**模型错**（值钱的教训，留痕）：我原先写成"三档各一条 `RULE`
    行、另两档写 `no`" —— **错的**。互斥链是 `if / else_if / else_if / else`，**只写命中的
    那一档**（`RULE;<设置名>;yes`），一档都没命中才写 `RULE;none;yes`；另两档**根本没有
    `RULE` 行**。「另两档是 `no`」是**第二族**（逐档 `if/else`，kind = `RULEHISTORY` /
    `RULEUNIFORM` / `RULEHARSH`）写出来的 —— 那正是第二族存在的理由。
    """
    setting_of = dict(zip(ab_probe.RULE_SHORTS, ab_probe.DIFFICULTY_SETTINGS, strict=True))
    facts = [
        LogFact(
            "真玩家国家", "PLAYER", "yes", 0, "观察者局这一行恒为 0 行（自动化范式.md:386-388）"
        ),
        LogFact("冲击落地", "SHOCK", "yes", 0, "不点探针决议就没有这一行 ⇒ L12 不能省"),
        # 家族 1：互斥链 —— **只有本档这一条**（另两档没有行；都没命中才 `RULE;none;yes`）。
        LogFact(
            f"难度档 {tier}（互斥链）",
            "RULE",
            "yes",
            1,
            "这一局挂在哪一档",
            setting_of[tier],
        ),
    ]
    # 家族 2：逐档 if/else —— 每档一条 yes/no，「另两档是 no」这条承重组合靠它。
    facts.extend(
        LogFact(
            f"难度档 {short}（逐档）",
            ab_probe.RULE_KINDS[short],
            ("yes" if short == tier else "no"),
            0,
            "逐档读数：这一档在不在；另两档必须显式写 no（否则「没记」与「没有」分不开）",
        )
        for short in ab_probe.RULE_SHORTS
    )
    return tuple(facts)


def read_probe_facts(log_text: str, facts: Sequence[LogFact]) -> tuple[list[str], list[str]]:
    """读 `debug.log` 文本，逐条判牙。返回 `(判据行, 问题行)`。

    **缺行与值错分开写**，因为两者的处置完全不同（口径 §7：不许静默降级、更不许把工具的毛病
    记到被测对象头上）：

    * 「一行都没有」或「只看到 `RULE;none;yes`」⇒ 先排**钩子/字面量失配**（t90 那族静默失真的
      形状），**不许**写成"难度没生效"；
    * 行在、值不对 ⇒ 那才是这一局的事实（例如另两档没有 `no` ⇒ 互斥链没生效）。
    """
    parsed: dict[str, list[list[str]]] = {}
    for line in log_text.splitlines():
        found = PROBE_LINE.search(line)
        if found is None:
            continue
        parsed.setdefault(found.group("kind"), []).append(found.group("rest").split(";"))

    rows: list[str] = []
    problems: list[str] = []
    none_only = any(rest and rest[0].strip() == "none" for rest in parsed.get("RULE", []))
    for fact in facts:
        same_kind = parsed.get(fact.kind, [])
        if fact.setting is None:
            selected = [rest for rest in same_kind if len(rest) > fact.where]
        else:
            # 先按**设置名**认行（`RULE;<设置名>;<yes|no>;<国名>`），否则三档的期望会互相串味。
            selected = [
                rest
                for rest in same_kind
                if rest and rest[0].strip() == fact.setting and len(rest) > fact.where
            ]
        if not selected:
            # **缺行的解释按族分开**（自检第二版纠正）：把每类都写成"先排字面量失配"是错的 ——
            # 逐档链缺一行只是"这一档没被写出来"，与字面量无关；PLAYER/SHOCK 缺行各指别的原因。
            if fact.kind == "RULE" and none_only:
                note = "只看到 `RULE;none;yes` ⇒ **先排字面量失配**（t90 那族），不是「难度没生效」"
            elif fact.kind == "RULE":
                note = "缺行 ⇒ 先排**钩子/字面量失配**（t90 那族），不是「难度没生效」"
            elif fact.kind.startswith("RULE"):
                note = "缺行 ⇒ 这一档**没被写出来**（逐档 if/else 没生效）—— 与字面量无关"
            elif fact.kind == "PLAYER":
                note = "缺行 ⇒ 这一局**没有玩家国家**（观察者局）—— 检查是否按真玩家国家开局"
            elif fact.kind == "SHOCK":
                note = "缺行 ⇒ **冲击没放**（L12 那一步没做）—— 不是难度问题"
            else:
                note = "缺行"
            rows.append(f"{fact.name}: ✗ 缺行")
            problems.append(f"{fact.name}：缺行 —— {note}；{fact.why}")
            continue
        matched = [rest for rest in selected if rest[fact.where].strip() == fact.want]
        if matched:
            rows.append(f"{fact.name}: ✓ {fact.want}（{len(matched)} 行）")
        else:
            seen = "、".join(sorted({rest[fact.where].strip() for rest in selected}) or {"—"})
            rows.append(f"{fact.name}: ✗ 取值={seen}（期望 {fact.want}）")
            problems.append(f"{fact.name}：取值 {seen} ≠ {fact.want} —— {fact.why}")
    return rows, problems


class Summary:
    """运行摘要（口径 §2.1：每步的判据与分数都要落进 `stage6-ui-<时间戳>.md`）。"""

    def __init__(self, *, tier: str, lang: str, recon: bool) -> None:
        self.tier = tier
        self.lang = lang
        self.recon = recon
        self.lines: list[str] = []
        self.rows: list[tuple[str, str, str]] = []
        self.notes: list[str] = []

    def note(self, text: str) -> None:
        self.notes.append(text)
        print(f"  {text}")

    def step(self, name: str, verdict: str, detail: str) -> None:
        self.rows.append((name, verdict, detail))
        print(f"  {name:28s}: {verdict}  {detail}")

    def render(self, *, extra: dict[str, object]) -> str:
        head = [
            "# 阶段 6 实机运行摘要（stage6_ui_rerun）",
            "",
            f"- 时间：{datetime.now(UTC).astimezone().strftime('%Y-%m-%d %H:%M:%S')}",
            f"- 模式：{'侦察（--recon：允许按估计 ROI 点，不要模板命中）' if self.recon else '取证'}",
            f"- 档案：`{self.tier}` ｜ 语言：`{self.lang}` ｜ 模板目录：`{template_dir(self.lang)}`",
            "",
            "## 逐步结果",
            "",
            "| 步 | 判据 | 详情 |",
            "|---|---|---|",
        ]
        body = [f"| {name} | {verdict} | {detail} |" for name, verdict, detail in self.rows]
        tail = ["", "## 说明", ""]
        tail += [f"- {note}" for note in self.notes] or ["- （无）"]
        tail += [
            "",
            "## 环境与读数",
            "",
            "```json",
            json.dumps(extra, ensure_ascii=False, indent=2),
            "```",
            "",
        ]
        return "\n".join([*head, *body, *tail])


def run(args: argparse.Namespace) -> int:
    evidence_root = Path(args.evidence)
    # ── B114：**每遍一个子目录**，帧名不再跨遍覆盖（根目录本身不再放帧）────────────
    # 为什么 pass-id 里带时间戳而不是只写 `--tier`：同一个 tier 今天会跑很多遍（第二遍 L4→L10
    # 还要再跑），只按 tier 命名照样覆盖。时间戳 + tier 让"这一帧属于哪一遍"自证，于是
    # 「A 遍的 22 与 B 遍的 22 逐字节相同」这条 claim **事后可复算**（撤回的那条正是缺它）。
    stamp = datetime.now(UTC).astimezone().strftime("%Y%m%d-%H%M%S")
    evidence = pass_dir(evidence_root, pass_dir_name(args.tier))
    pass_id = evidence.name  # ⚠️ 用**分到的**名字（重名时 pass_dir 会顺位加 -2/-3…）
    # 落帧的唯一出口是 `game_auto.save_shot`，它读的是**模块级** `SHOT_DIR` ⇒ 把出口指到本遍
    # 子目录，于是**所有**调用点自动按遍归档，没有"漏改一处"的可能（本文件已有同类先例：
    # `ga.ALLOW_REAL_INPUT = True`）。finally 里放回原值 —— 出口指错=证据落错地方，与没落等价。
    shot_dir_before = ga.SHOT_DIR
    ga.SHOT_DIR = evidence
    report = Summary(tier=args.tier, lang=args.lang, recon=bool(args.recon))
    started = time.monotonic()
    previous = 0
    hwnd = 0
    summary_path = evidence / f"stage6-ui-{stamp}.md"
    report.note(
        f"落帧目录：`{evidence}`（**按遍归档**，B114；本轮 pass-id = `{pass_id}`）"
        f"—— 根目录 `{evidence_root}` 里既有的扁平帧**一个不动**"
    )
    extra: dict[str, object] = {
        "tier": args.tier,
        "lang": args.lang,
        "recon": bool(args.recon),
        "collect": bool(args.collect),
        "pass_id": pass_id,
        "evidence_dir": str(evidence),
    }

    # ── 环境纪律：改动之前不许有会抛的操作（B79）────────────────────────────
    if not args.skip_preflight:
        pre = preflight.run()
        for line in pre.lines():
            print(f"  {line}")
        if pre.exit_code():
            report.note(f"preflight 没过（退出码 {pre.exit_code()}）—— 按口径 §7 照抄它的码退出")
            summary_path.write_text(report.render(extra=extra), encoding="utf-8", newline="\n")
            ga.SHOT_DIR = shot_dir_before  # 这条早退没走 finally ⇒ 出口在这里自己还回去
            return pre.exit_code()
    backup = preflight.probe_state_backup()
    if backup is not None:
        report.note(f"上次会话把配置留在探针态 —— 先用 {backup.name} 还原再继续")

    before_hash = sha256(content_load()) if content_load().is_file() else ""
    extra["content_load_sha256_before"] = before_hash
    # ⚠️ 便宜的**前置条件**要排在"改用户环境"之前（B79 的同一条道理：第一次改动之前不许有
    # 会抛的操作）：**硬模板**齐不齐，读一次目录就知道 —— 不该等部署完、游戏起来了才发现。
    # 其余模板（LATER：in-game 那批等）缺失**不挡开跑**，改在走到那一步时点名报「未达成」；
    # 摘要里先列清单，读者一眼能看出"这次跑到哪、哪些因缺模板没到"（队长 04:2x 第 3 条）。
    if not args.recon:
        require_templates(args.lang, HARD_TEMPLATES)
        gaps = step_template_gaps(args.lang)
        if gaps:
            report.note(
                "⚠️ 以下步骤**因缺模板**会在走到时判「未达成」（点名、不静默跳过）："
                + "；".join(f"{name} ⇒ 缺 `{tpl}`" for name, tpl in gaps)
            )
    ga.ALLOW_REAL_INPUT = True

    leftover = ga._process_pids()
    if leftover:
        report.note(f"起前有残留 victoria3：{leftover} —— 先收掉")
        ga.kill_game()
        time.sleep(3)

    moved = ga.quarantine_logs()
    report.note(f"已把 {len(moved)} 个旧日志挪去临时目录（这一局的读数只可能来自这一局）")
    for _note in args.note:
        report.note(f"现场注记（--note，调用方给的，不是探针测的）：{_note}")

    with tempfile.TemporaryDirectory(prefix="stage6-deploy-") as _tmp:
        deploy_note = ab_probe.deploy(archive_id=args.archive or None)
        report.note(deploy_note)
        try:
            previous = ga._foreground_window()
            hwnd = ga.launch(
                scripted_tests=False,
                extra_args=(f"-language={args.lang}",),
                timeout=args.window_timeout,
            )
            report.note(
                f"窗口 hwnd={hwnd}（语言开关 `-language={args.lang}`；不动 pdx_settings.json）"
            )
            settle = ga.wait_for_boot_settle(timeout=args.boot_timeout)
            report.note(f"启动期：{settle.why}")
            ga.ensure_foreground(hwnd, attempts=5, force=True)
            size = ga._client_size(hwnd)
            extra["client_size"] = list(size)

            # ── 内容判据（2026-09-25 队长复核后重写）─────────────────────────────────
            # 硬事实：盒①第二遍的 `19/20/21` **三帧同哈希** `fa2fab91382e…`（3,832,482 B）
            # —— 全是「初始化游戏……」载入画面，而运行摘要里 L4–L7 四行都写了 ✅。根因是
            # 判据只证明「截了一张图」，没证明「图里是目标 UI」；而载入期引擎不写
            # debug.log，「日志 30 秒不变」这条 settle 在载入期**永远会说就绪**。
            # ⇒ 从此每一步抓帧都过**内容**判据：① 不是载入画面（与基准帧比相似度）；
            #   ② 点完之后画面**真的变了**；③ 超时就判「本步未达成」并抛错（P13：出声）。
            loading_ref = Image.open(LOADING_REF).convert("L") if LOADING_REF.is_file() else None
            if loading_ref is None:
                report.note(
                    f"⚠️ 缺载入画面基准帧 `{LOADING_REF.name}` —— 载入判据退化，"
                    "只剩「画面变了」这一道（别把这一局当强证据）"
                )

            def grab() -> tuple[Image.Image | None, bytes]:
                """抓一帧；**抓不到就返回 `None`**（不要抛）。

                `screenshot` 有两种"正确地拒绝"：被遮挡（前台不是游戏）与**近乎纯色的
                画面**（加载中的黑场/淡入淡出）。等待循环要的是"继续轮询"，不是把整局
                判死 —— 第四遍就死在这一点上（L5 之后抓到了纯色帧，整局抛错收场）。
                """
                ga.ensure_foreground(hwnd, attempts=5, force=True)
                try:
                    image = ga.screenshot(hwnd)
                except ga.CaptureFailedError:
                    return None, b""
                return image, _sig(image)

            def is_loading(image: Image.Image) -> bool:
                return loading_ref is not None and _mean_diff(image, loading_ref) <= LOADING_DIFF

            def wait_loaded(frame: str) -> tuple[Image.Image, bytes]:
                """等到画面**画出来了**：不是载入画面、中央区也不空。

                ⚠️ 第五遍的硬事实：只判「不是载入画面」**不够** —— 那一遍的
                `19-main-menu.png` 是黑屏+页脚（102 KB），判据全过，可菜单还没画出来，
                于是 L5 那一点落在黑屏上（什么都没发生），真正生效的是 L6（点在主菜单的
                「账号」图标上）⇒ `21/22` 拍成「主菜单 + 账号对话框」。
                """
                image, sig = grab()
                deadline = time.monotonic() + LOAD_TIMEOUT
                while (
                    image is None or is_loading(image) or _is_blank(image)
                ) and time.monotonic() < deadline:
                    time.sleep(1.0)
                    image, sig = grab()
                if image is None or is_loading(image) or _is_blank(image):
                    if image is not None:
                        ga.save_shot(image, f"{frame}-NOT-READY")
                    raise RuntimeError(
                        f"{frame}：等了 {LOAD_TIMEOUT:.0f} 秒画面还是载入画面/空白帧 —— "
                        "这一步没达成，不写 ✅"
                    )
                return image, sig

            def wait_changed(frame: str, prev: bytes) -> tuple[Image.Image, bytes]:
                """等画面**真的变了**再走（实测坑：点完之后帧滞后于点击，拍到的还是上一屏）。"""
                image, sig = grab()
                deadline = time.monotonic() + CHANGE_TIMEOUT
                while (image is None or sig == prev) and time.monotonic() < deadline:
                    time.sleep(0.8)
                    image, sig = grab()
                if image is None or sig == prev:
                    if image is not None:
                        ga.save_shot(image, f"{frame}-UNCHANGED")
                    raise RuntimeError(
                        f"{frame}：点完之后 {CHANGE_TIMEOUT:.0f} 秒画面没变（或一直抓不到图）"
                        " —— 这一击没生效，不写 ✅"
                    )
                return image, sig

            def wait_for_screen(
                template: str, roi_name: str, frame: str, prev_sig: bytes
            ) -> tuple[Image.Image, bytes]:
                """等到**目标屏自己的特征出现**（正向判据）+ 画好了，然后才截。

                ⚠️ 为什么不用「上一屏的特征消失」（第七遍我就是那么写的，被实机否掉）：
                ① 抓图失败（不是前台/最小化）与「确实没有」必须分得开（P13）—— 本处**显式**选
                `on_capture_failure="miss"`（轮询语义，见下方注释，t33）⇒ 一次瞬时抓图失败
                只会被读成「这一轮不算命中」；若判据写成「上一屏的特征消失」，同一个瞬时
                失败就会被读成「已消失」；
                ② 模板对**悬停/高亮态**敏感：点完之后鼠标就停在那个按钮上，按钮换了样子
                ⇒ 匹配不上，「消失」也是假的。
                正向判据两个漏洞都没有：抓图失败在正向判据里只会让我们**继续等**，
                绝不会造成假通过。
                """
                deadline = time.monotonic() + CHANGE_TIMEOUT
                while time.monotonic() < deadline:
                    image, sig = grab()
                    if image is None or is_loading(image) or _is_blank(image) or sig == prev_sig:
                        time.sleep(0.8)
                        continue
                    # 🔧 t33：这里**要**轮询语义（「还没画出来」≠「这一屏没有」），所以显式声明。
                    #    t19 之后 `find_in_roi` 抓图失败默认**抛**（看不到 ≠ 没有）；本行显式选
                    #    "miss" ⇒ 行为与改造前的默认值逐字相同（等价性已逐帧复算，见 t33 报告）。
                    hit = ga.find_in_roi(
                        hwnd,
                        template,
                        roi=ROIS[roi_name],
                        directory=template_dir,
                        on_capture_failure="miss",
                    )
                    if hit is None:
                        time.sleep(0.8)
                        continue
                    report.note(f"{frame}：正向判据命中 `{template}` {hit}")
                    return image, sig
                image, _ = grab()
                if image is not None:
                    ga.save_shot(image, f"{frame}-NO-TEMPLATE-HIT")
                raise RuntimeError(
                    f"{frame}：等了 {CHANGE_TIMEOUT:.0f} 秒也没等到 `{template}` 在"
                    f"「{roi_name}」ROI 里命中 —— 这一击没生效（或没走到那一屏），不写 ✅"
                )

            def locate_our_row(frame: str) -> tuple[bool, list[str], list[str]]:
                """**拖动滚动条**直到定位到我们那一行（`rule_row_sitai`，阈值
                `ROW_LOCATOR_THRESHOLD` = 0.64，真值只在 :141）。

                返回 `(是否命中, 留下的帧名, 每步整帧 sha256 链)` —— 结果**回传**给调用方写判据列，
                这样侦察与取证两条路**共用同一份探索逻辑**（队长 07:1x：能复用就复用、别复制粘贴；
                判据列各自写，那部分是取证分支的核心）。

                ⚠️ 滚轮在这台机器上是 **no-op**（第九遍实测：`21` 与滚过之后的
                `22-rule-sitai-scroll-1` **逐字节相同**，同 sha256 `414f481b56c870e5`）⇒ 只能拖动
                滚动条，走**已被证明可用**的鼠标通道（按下 → 分步移动 → `finally` 抬键，见
                `game_auto.mouse_drag`）。
                """
                ga.ensure_foreground(hwnd, attempts=5, force=True)
                sx = int(size[0] * SCROLLBAR_X)
                thumb = SCROLLBAR_TOP
                kept: list[str] = []
                chain: list[str] = []
                for k in range(1, args.scrolls + 1):
                    before, _ = grab()
                    hb = hashlib.sha256(before.tobytes()).hexdigest() if before else ""
                    thumb_to = min(thumb + SCROLLBAR_STEP, 0.95)
                    ga.mouse_drag(
                        hwnd,
                        sx,
                        int(size[1] * thumb),
                        sx,
                        int(size[1] * thumb_to),
                        steps=14,
                        settle=0.02,
                        force=True,
                    )
                    time.sleep(0.6)
                    ga.wait_stable(hwnd, roi=ROIS["rules_window"], timeout=20.0, settle_frames=2)
                    after, _sig = grab()
                    if after is None:
                        continue
                    ha = hashlib.sha256(after.tobytes()).hexdigest()
                    moved = ha != hb
                    chain.append(f"{hb[:8]}→{ha[:8]}{'✓动了' if moved else '✗没动'}")
                    # 🔧 t33：拖滚动条期间窗口会瞬时抓不到图（拖拽中 / 重绘中），这**必须**继续拖，
                    #    不能中止整局 ⇒ 显式选轮询语义（t19 之后 `find_in_roi` 的默认是抛）。
                    hit = ga.find_in_roi(
                        hwnd,
                        "rule_row_sitai",
                        roi=ROIS["rules_window"],
                        threshold=ROW_LOCATOR_THRESHOLD,
                        directory=template_dir,
                        on_capture_failure="miss",
                    )
                    if hit is not None:
                        ga.save_shot(after, frame)
                        return True, kept, chain
                    kept.append(ga.save_shot(after, f"{frame}-scroll-{k}").name)
                    if not moved:
                        break  # 拖了也不动 ⇒ 到底了（或拖动没生效），再拖没意义
                    thumb = thumb_to
                return False, kept, chain

            # L4：主菜单帧 —— **强判据**：模板 `btn_new_game` 在 `main_menu` ROI 里命中。
            # 为什么不用「不是载入画面」当判据：第五遍那张**黑屏+页脚**帧把它证伪了
            # （见 `wait_loaded` 的 docstring：黑屏既非载入、又与上一帧不同，判据全过而
            # 菜单根本没画出来）。模板目录按语言取，zh/en 两套不混。
            template_dir = TEMPLATE_ROOT / LANGS[args.lang]
            deadline = time.monotonic() + LOAD_TIMEOUT
            hit = None
            unseen = 0
            unseen_why = ""
            while time.monotonic() < deadline:
                # 🔧 t33：启动期**不能**用 `find_in_roi` —— 窗口还在画 / 被遮挡 / 近乎纯色时，
                #    「抓不到图」与「主菜单没命中」是两件事：前者要**继续等**，后者才让判据为假。
                #    t19 之后前者默认要出声（抛），所以走驱动自己的三态 `locate_state`：
                #    抓不到图 ⇒ 继续等 + 记账，超时文本里点名（看不到 ≠ 没有）。
                state, match, why = locate_state(
                    hwnd, "btn_new_game", roi=ROIS["main_menu"], directory=template_dir
                )
                if state == LOOKUP_HIT:
                    hit = match
                    break
                if state == LOOKUP_UNSEEN:
                    unseen += 1
                    unseen_why = why
                time.sleep(1.0)
            if hit is None:
                image, _ = grab()
                if image is not None:
                    ga.save_shot(image, "19-main-menu-NO-TEMPLATE-HIT")
                raise RuntimeError(
                    f"L4：等了 {LOAD_TIMEOUT:.0f} 秒也没在 `main_menu` ROI 里命中 "
                    "`btn_new_game` 模板 —— 主菜单没画出来（或模板不对），不写 ✅"
                    + (
                        f"（其中 {unseen} 次是**抓不到图**：看不到 ≠ 没有；"
                        f"最后一条原因：{unseen_why}）"
                        if unseen
                        else ""
                    )
                )
            main_menu, prev = grab()
            shot = ga.save_shot(main_menu, "19-main-menu")
            report.step(
                "L4 启动到主菜单",
                "帧（内容已核：btn_new_game 命中）",
                f"{shot.name}（{size[0]}x{size[1]}；模板命中 {hit}）",
            )

            if args.recon:
                # 侦察：按 ROI 中心点，点完各抓一帧。**不做判据**，只收素材。
                clicks = (
                    ("L5 点「新游戏」", "btn_new_game", "main_menu", "20-setup-screen"),
                    ("L6 打开规则窗", "btn_game_rules", "setup_rules", "21-rules-window"),
                )
                for name, _template, roi_name, frame in clicks:
                    x, y = estimate_xy(ROIS[roi_name], size=size)
                    report.note(f"{name}：按 ROI「{roi_name}」中心点 ({x},{y}) 点一下（侦察口径）")
                    # ⚠️ 第七遍实测：**点击会偶尔被吞**（同一个坐标第六遍生效、第七遍没生效，
                    #    帧里还是主菜单）。所以点之前先把光标放到位、给它一点时间被引擎的帧读到，
                    #    再把按键送出去 —— 引擎读的是光标位置 + 按键状态，不是注入的坐标。
                    # ⚠️ 第八遍实测：`_set_cursor` 的签名是 `(x, y)` —— **没有 hwnd**
                    #    （`game_auto.py:915`）。我第一版写成 `(hwnd, x, y)` ⇒ 当场 TypeError，
                    #    那一遍就死在这里（好的一面：判据列如实写了「未达成」、失败也留了摘要、
                    #    收尾三件照常干净）。
                    ga._set_cursor(x, y)
                    time.sleep(0.3)
                    ga.click_client(hwnd, x, y, settle=0.25, force=True)
                    nxt = NEXT_SCREEN.get(name)
                    if nxt is not None:
                        # ① 正向判据：目标屏自己的模板**出现**才算走到了（第七遍用「上一屏
                        #    模板消失」被否掉，理由见 `NEXT_SCREEN` 的注释）。
                        image, prev = wait_for_screen(nxt[0], nxt[1], frame, prev)
                    else:
                        # 没有目标屏模板的步（规则窗模板要等这一遍的帧裁出来）：退到
                        # 「变了 + 画好了 + **画面停下来了**」——`wait_stable` 补的正是
                        # 「淡入还没结束就截图」这一课。
                        image, prev = wait_changed(frame, prev)
                        image, prev = wait_loaded(frame)
                        ga.wait_stable(
                            hwnd,
                            roi=(0.0, 0.0, 1.0, 1.0),
                            timeout=30.0,
                            settle_frames=3,
                        )
                    shot = ga.save_shot(image, frame)
                    report.step(
                        name,
                        "帧（内容已核：画面已变）",
                        f"{shot.name}（估计点 {x},{y}）",
                    )
                # 规则窗：滚一格再抓一帧（卡片可能在折叠线下）
                ga.ensure_foreground(hwnd, attempts=5, force=True)
                x, y = estimate_xy(ROIS["rules_window"], size=size)
                # L7：**拖动滚动条**（滚轮已被逐字节同哈希证明到不了引擎）+ 两道内容判据。
                #     判据（队长 03:2x 认可、写死）：拖动**前后整帧 sha256 必须不同**；
                #     没动 ⇒ 判未达成，**不写 ✅**（第九遍就是靠这条抓出滚轮是 no-op 的）。
                ga.ensure_foreground(hwnd, attempts=5, force=True)
                sx = int(size[0] * SCROLLBAR_X)
                thumb = SCROLLBAR_TOP
                kept: list[str] = []
                chain: list[str] = []
                locator_hit = False
                row_hit: object | None = None
                for k in range(1, args.scrolls + 1):
                    before, _ = grab()
                    hb = hashlib.sha256(before.tobytes()).hexdigest() if before else ""
                    thumb_to = min(thumb + SCROLLBAR_STEP, 0.95)
                    ga.mouse_drag(
                        hwnd,
                        sx,
                        int(size[1] * thumb),
                        sx,
                        int(size[1] * thumb_to),
                        steps=14,
                        settle=0.02,
                        force=True,
                    )
                    time.sleep(0.6)
                    ga.wait_stable(hwnd, roi=ROIS["rules_window"], timeout=20.0, settle_frames=2)
                    after, sig = grab()
                    if after is None:
                        continue
                    ha = hashlib.sha256(after.tobytes()).hexdigest()
                    moved = ha != hb
                    chain.append(f"{hb[:8]}→{ha[:8]}{'✓动了' if moved else '✗没动'}")
                    # **L7 的承重判据**：我们那一行的定位模板（`rule_row_sitai`，框 (970,676,1066,706)）
                    # 必须命中。阈值 = `ROW_LOCATOR_THRESHOLD`（**真值只在 :141 = 0.64**；
                    # 这里原先印的「0.90…假命中 0.7659」是**别的模板**的正负分，t24/F3 按实值
                    # 改准）：正（最小）1.000000（`22` / `23` 两帧，**自匹配、平凡满分**）、
                    # 负（最大）0.270209 ⇒ 取中点 0.64（两侧余量各 ≥0.365；旧值 0.90 随"平底误裁"
                    # 模板作废，见 §3.10 / B118；`tools/out/auto/retake_l7.py` 可复算）——
                    # 不是把默认 0.75 放宽。
                    # 🔧 t33：同上一处 —— 拖动期间瞬时抓不到图必须**继续拖**（不能中止整局），
                    #    所以显式选轮询语义（t19 之后 `find_in_roi` 的默认是抛）。
                    hit = ga.find_in_roi(
                        hwnd,
                        "rule_row_sitai",
                        roi=ROIS["rules_window"],
                        threshold=ROW_LOCATOR_THRESHOLD,
                        directory=template_dir,
                        on_capture_failure="miss",
                    )
                    if hit is not None:
                        shot = ga.save_shot(after, "22-rule-sitai")
                        report.step(
                            "L7 定位我们的卡片",
                            "帧（内容已核：rule_row_sitai 命中）",
                            f"{shot.name} —— 拖第 {k} 次后命中我们那一行 {hit}；"
                            f"整帧 sha256：{'；'.join(chain)}",
                        )
                        locator_hit = True
                        row_hit = hit
                        break
                    kept.append(ga.save_shot(after, f"22-rule-sitai-scroll-{k}").name)
                    prev = sig
                    if not moved:
                        break  # 拖了也不动 ⇒ 到底了（或拖动没生效），再拖没意义
                    thumb = thumb_to
                if not locator_hit:
                    report.step(
                        "L7 定位我们的卡片",
                        "未达成（滚到底也没命中定位模板）",
                        f"拖滚动条 {len(kept)} 次、每步整帧 sha256：{('；'.join(chain)) or '（没抓到帧）'}；"
                        f"留帧 {kept or '（无）'} —— 命中 `rule_row_sitai`（阈值 {ROW_LOCATOR_THRESHOLD}）"
                        "才算「已定位」，不写 ✅",
                    )
                # ── 侦察延伸（队长 05:5x 批准方案 (A) 的三条约束，07:1x 按路线订正到 **L10**）──
                #    目的：**国家选择屏的第一批真帧** —— 它是裁 `card_country_rus`(L10) 与
                #    `btn_start_game`(L11) 的唯一来源（模板裁不出来、也猜不出来）。
                #    约束 1：**先落「点完必须画面真的变了」的判据**（整帧 sha256），点空当场出声；
                #            落下的帧一律标「**候选帧、未判**」，**不许**写成"到达 L10/L11"。
                #    约束 2：**估计值必须标成估计值**（坐标怎么量的、是估的）。
                #    约束 3：**一次会话内到时即停**（点空/没变就 break，不盲试）。
                #    🔧 07:1x 路线订正（队长批准，依据 §3.7 的实测）：**「应用」自带关窗**
                #    ⇒ 原来那一步「点 btn_rules_close」必然 `LOOKUP_ABSENT`、把整段提前 break、
                #    **走不到 L10**（上一遍就是这样白停在 apply 之后）。⇒ 删掉它，并按发现式
                #    在 apply **之前**加两下逐档箭头（估计坐标），这样这一遍的素材包含
                #    `23-tier-*-candidate` + `24-after-apply` + **`25-country-screen-candidate`**。
                if locator_hit:
                    # 🔧 阶段 6 仪器（1/4，B118）：逐档箭头那两步的**点击前自检**已就位，但缺省
                    #    **仍然不点** —— 点 ◀ 会把选中档位挪走，而这一遍的 `--tier` 是调用方指定
                    #    的：让侦察遍顺手改档位，`24` 之后 apply 落定的档就与 `--tier` 不符，
                    #    而"落定哪一档"正是**被读的东西**（不许被顺手改掉）。要试逐档机制就显式
                    #    加 `--row-arrows` ⇒「点箭头」成为一个**声明过的**动作，而不是副作用。
                    #    ⇒ 置于表首：它们必须在规则窗还没关的时候点（`btn_rules_apply` 自带关窗，
                    #    那一课见下面 08:1x 的注释）。
                    arrow_steps: tuple[
                        tuple[str, str, object, tuple[float, float, float, float]], ...
                    ] = (
                        (
                            (
                                "26-tier-prev-candidate",
                                "row_arrow",
                                "prev",
                                ROIS["rules_window"],
                            ),
                            (
                                "27-tier-next-candidate",
                                "row_arrow",
                                "next",
                                ROIS["rules_window"],
                            ),
                        )
                        if args.row_arrows
                        else ()
                    )
                    ext_steps: tuple[
                        tuple[str, str, object, tuple[float, float, float, float]], ...
                    ] = (
                        *arrow_steps,
                        # 🔧 08:1x 队长重排：**逐档两步先撤出主线** —— 它们只是"局部机制未判清"
                        #    的小问题，而 `25-country-screen-candidate.png` 才是阶段 6 出口的
                        #    拦路石（`card_country_rus` / `btn_start_game` 的唯一来源）。
                        #    三档素材已有一帧在手（`23-tier-1-candidate.png`），逐档机制按
                        #    blocker 单独追（第十六遍读数：`◀` 命中 (958,740) 有真变化、
                        #    随后 `▶` 命中 (1266,740) 却没变 ⇒ 疑为相邻行的灰箭头，待读屏判）。
                        #    ⇒ 主线直接走 **L9 应用 → L10 目标卡**。
                        (
                            "24-after-apply-candidate",
                            "template",
                            "btn_rules_apply",
                            ROIS["rules_window"],
                        ),
                        (
                            "25-country-screen-candidate",
                            "estimate",
                            (1014, 510),
                            ROIS["setup_rules"],
                        ),
                    )
                    for frame, kind, target, roi in ext_steps:
                        before, _ = grab()
                        hb = hashlib.sha256(before.tobytes()).hexdigest() if before else ""
                        already_clicked = False  # `row_arrow` 在自己的分支里点（自检通过才点）
                        if kind == "template":
                            state, match, why = locate_state(
                                hwnd, str(target), roi=roi, directory=template_dir
                            )
                            if state != LOOKUP_HIT or match is None:
                                report.note(
                                    f"侦察延伸 {frame}：模板 `{target}` ⇒ {state}"
                                    + (f"（{why}）" if why else "")
                                    + " ⇒ **停手**（约束 3：不盲试）"
                                )
                                break
                            x, y = int(match.x), int(match.y)  # type: ignore[attr-defined]
                            how = f"模板命中 `{target}`（x/y = 框中心）"
                        elif kind == "row_arrow":
                            # ── 我们那一行的逐档箭头：**先自检、后点**（本卡 ①）─────────────
                            # 行心 y **必须由定位到的那一行给出**（`ROW_TITLE_TO_ROW_CENTER_DY`
                            # 的 docstring 写着"不许写死"）⇒ 取 L7 定位模板的命中点。
                            if row_hit is None:  # 结构上到不了这里（locator_hit ⇒ row_hit 已设）
                                raise RowArrowCheckError(
                                    "没有行定位",
                                    "[失败] 点 ◀/▶ 之前拿不到**行心 y**：L7 没定位到我们那一行，"
                                    "就没有行带可查 —— **一个鼠标键也没送出去**。"
                                    "不许写死 y、也不许照抄上一遍的坐标（B118）。",
                                )
                            row_match_y = int(row_hit.y)  # type: ignore[attr-defined]
                            row_center_y = row_match_y + ROW_TITLE_TO_ROW_CENTER_DY
                            spot = click_row_arrow(
                                hwnd,
                                which=str(target),
                                image=before,
                                row_center_y=row_center_y,
                            )
                            x, y = spot.x, row_center_y  # 点击点 = **自检量出来的**像框中心
                            already_clicked = True
                            how = (
                                f"**实测值**（点击前自检放行：{spot.report_line()}；"
                                f"行心 y={row_center_y} = L7 定位命中 y {row_match_y} + "
                                f"ROW_TITLE_TO_ROW_CENTER_DY({ROW_TITLE_TO_ROW_CENTER_DY})）"
                            )
                        else:
                            x, y = int(target[0]), int(target[1])  # type: ignore[index]
                            # ⚠️ provenance **按步给**，不许一条句子套用所有 estimate 步：
                            #    第十三遍两条 estimate 步都印了目标卡那句出处 —— 复制粘贴留下的
                            #    **错标**（箭头步不是按卡片坐标量的）。「错标出处的证据比没有出处更坏」。
                            if frame.startswith("23-tier"):
                                how = (
                                    "**估计值**（逐档箭头 `◀`：取自第十遍 `scroll-4/5` 帧的实测 "
                                    "(958,740)；**未用模板核对**）"
                                )
                            else:
                                how = (
                                    "**估计值**（目标卡在 1066×600 预览的 (563,283) ×1.8011 "
                                    "⇒ (1014,510)，**未用模板核对**）"
                                )
                        if not already_clicked:
                            # 公共尾巴：`template` / `estimate` 两步在这里点（坐标来自上面）；
                            # `row_arrow` 已经在自己的分支里**过了自检**才点 ⇒ 不再点第二次。
                            ga._set_cursor(x, y)
                            time.sleep(0.3)
                            ga.click_client(hwnd, x, y, settle=0.25, force=True)
                        time.sleep(0.6)
                        after, sig = grab()
                        ha = hashlib.sha256(after.tobytes()).hexdigest() if after else ""
                        moved = bool(ha) and ha != hb
                        if after is not None:
                            # 🔧 08:2x 队长要求的 2 行（第十四/十六遍各犯过一次）：**未变就不许落
                            #    「进展名」帧** —— 否则产物树会冒充"这一档已拿到"，而下一轮正是拿
                            #    这些帧去裁逐档模板 ⇒ 「错标出处比没有出处更坏」。变了才落原名；
                            #    没变就落 `…-noop`（证据保留、名字不冒充）。
                            ga.save_shot(after, frame if moved else f"{frame}-noop")
                        report.note(
                            f"侦察延伸 {frame}：点 ({x},{y})；{how}；整帧 sha256 "
                            f"{hb[:8]}→{ha[:8]} "
                            + (
                                "✓变了"
                                if moved
                                else (
                                    "✗**未变（模板命中 ⇒ 边界或不可用）**"
                                    if kind == "template"
                                    else "✗**没变（点空）**"
                                )
                            )
                            + "；**候选帧、未判**（不许据此推 L8+ 结论）"
                        )
                        if not moved:
                            # ⚠️ 「画面没变」**至少两种原因**（队长 08:1x 立）：① **点空**（模板没命中）；
                            # ② **命中但值不变**（边界/按钮不可用）。只看画面这两者**同形**，
                            # 而"模板命中这件事本身"把它们分开 ⇒ **只有没命中才许叫"点空"**。
                            if kind == "template":
                                unchanged = (
                                    "模板命中但画面没变 ⇒ **未变（边界或不可用）**，不是点空"
                                )
                            elif kind == "row_arrow":
                                unchanged = (
                                    "自检放行（箭头确实在那儿）但画面没变 ⇒ "
                                    "**未变（边界或不可用）**，不是点空"
                                )
                            else:
                                unchanged = "模板没命中且画面没变 ⇒ **点空**"
                            report.note(unchanged)
                            report.note("**停手**（约束 1/3：不盲试）")
                            break
                        prev = sig
                # 发现式的**判据列**：把「未判定（缺模板 X）」**写进摘要的判据列**（不是只写 note）——
                # 用刚落的 `missing_template_policy(discovery=True)`，于是"缺模板不停"这条语义
                # 在产物里**看得见**（队长 04:2x 硬条件 3：别让一次部分完成被读成 L8–L15 全过）。
                # 这些步本遍**不判**：素材（`23-tier-*` / `25-country-screen-candidate`）要到手、
                # 裁出模板之后，第二遍才谈判据。
                for step in STEPS:
                    if not step.name.startswith(("L8", "L10", "L11", "L12", "L14", "L15")):
                        continue
                    text, _stop = missing_template_policy(step, args.lang, discovery=True)
                    if text:
                        report.step(
                            step.name,
                            text,
                            "发现式：本遍不判该步（模板要从本遍的候选帧里裁，第二遍才判）",
                        )
                report.note(
                    "侦察到此为止：**三档逐档/双语/G3 三行都要模板**，"
                    "而模板必须从上面这些帧里裁出来（口径 §9 的六件事也靠它们判）"
                )
            else:
                # ── L5–L16 取证执行器（t41）────────────────────────────────────────────
                # 出处：`docs/design/exec/阶段6-国家身份开局-取证口径.md`
                #   §3.1/§3.2 三档**逐档可见** = 档名 + 说明首段 + 说明尾段三块模板**同帧**
                #            各自命中，靠卡片两侧 ‹ › 逐档导航（只能在开局前改）
                #   §3.3 承重 = 引擎日志的难度读数；旁证 = 修正列表；存档一条待首跑
                #   §4 双语（模板按 zh/en 分目录）·§5 G3 三行（三块首段模板同帧命中于 je_panel）
                #   §6 环境纪律（部署与收尾在 run() 上下游）·§7 失败出声表（读不出就报，不盲走）
                # 事实记账（队长 m02173）：t41 之前，非侦察路径在 L4 之后**一条执行语句都没有**
                # （L5–L15 全在 `if args.recon:` 里）⇒「国家屏链 L4→L10 已通」只能按侦察模式读。
                # 分工写死：侦察 = 收候选帧、不作达成声明；取证 = 每步给判据与出处，读不出出声。
                step_of = {step.name: step for step in STEPS}
                l5 = step_of["L5 点「新游戏」"]
                l6 = step_of["L6 打开规则窗"]
                l7 = step_of["L7 定位我们的卡片"]
                l8 = step_of["L8 逐档读到"]
                l9 = step_of["L9 应用并落定"]
                l10 = step_of["L10 选 RUS"]
                l11 = step_of["L11 开始游戏"]
                l12 = step_of["L12 放冲击"]
                l14 = step_of["L14 G3 三行"]
                l15 = step_of["L15 修正旁证"]
                # 三档名单**从展开表算出来**（不手写：表与代码只有一处真值）
                tiers = [
                    n[len("tier_") : -len("_name")]
                    for n in WILDCARD_EXPAND["tier_*"]
                    if n.endswith("_name")
                ]
                target = (
                    args.tier
                )  # 本遍要**落定**的档（`--tier` 只进目录名/元数据，落定靠 L9 点应用）

                def retry_frame(
                    *, tries: int = 3, wait: float = 1.0
                ) -> tuple[Image.Image | None, bytes]:
                    """抓一张（抓不到就重试几次）：`(None, b"")` = **确实量不到**（不是没到）。"""
                    for _ in range(tries):
                        frame, sig = grab()
                        if frame is not None:
                            return frame, sig
                        time.sleep(wait)
                    return None, b""

                def fail(name: str, detail: str, *, verdict: str = "不过") -> None:
                    """记一行判据 + **当场停**（总是抛）。

                    与 L4 超时、`RowArrowCheckError` 同一条路：异常由 `finally`（L16 收尾）照常
                    处理、摘要照留，退出码 1（口径 §7「任一步失败不许返回半个结果」）。
                    """
                    report.step(name, verdict, detail)
                    raise RuntimeError(f"{name}：{detail}")

                def waited(
                    tmpl: str,
                    roi_name: str,
                    *,
                    timeout: float = CHANGE_TIMEOUT,
                    threshold: float = ga.DEFAULT_THRESHOLD,
                ) -> tuple[Image.Image | None, str]:
                    """等 `tmpl` 在 `roi_name` 里出现：`(那一帧, 说明)`；等不到给 `(None, 为什么)`。

                    `roi_name` 走 :func:`roi_of`（**不能**直接用 `ROIS[...]`：L12 的 `bottom`
                    不在那张表里）。抓不到图只记数、继续等（P13：看不到 ≠ 没有）。
                    """
                    deadline = time.monotonic() + timeout
                    unseen = 0
                    score = 0.0
                    while time.monotonic() < deadline:
                        frame, _sig = grab()
                        if frame is None:
                            unseen += 1
                            time.sleep(1.0)
                            continue
                        found, score = locate_in_frame(
                            frame,
                            tmpl,
                            roi=roi_of(roi_name),
                            threshold=threshold,
                            directory=template_dir,
                        )
                        if found is not None:
                            return frame, f"`{tmpl}` 命中（分 {score:.6f}）"
                        time.sleep(0.8)
                    why = (
                        f"等了 {timeout:.0f} 秒，`{tmpl}` 在「{roi_name}」里没命中"
                        f"（最后一张读 {score:.6f}，阈值 {threshold:.2f}）"
                        + (f"；其中 {unseen} 次**抓不到图**（看不到 ≠ 没有）" if unseen else "")
                    )
                    return None, why

                def click_at(x: int, y: int, *, settle: float = 0.25) -> None:
                    """点一个**实测**出来的坐标（模板命中处 / 发现式的 ROI 中心）。"""
                    # ⚠️ `_set_cursor` 的签名是 `(x, y)` —— **没有 hwnd**（game_auto.py:921）
                    ga._set_cursor(int(x), int(y))
                    time.sleep(0.3)
                    ga.click_client(hwnd, int(x), int(y), settle=settle, force=True)

                def note_missing(step: Step) -> str:
                    """缺模板的统一处置：返回判据列文本（空串＝模板齐）。

                    收料遍（`--collect`）记「未达成（缺模板 …）」但**继续**（第二遍才有素材）；
                    承重遍**当场停** —— 没有判据就不许往前走。
                    """
                    if not step_missing_templates(step, args.lang):
                        return ""
                    text, stop = missing_template_policy(step, args.lang, discovery=args.collect)
                    if stop:
                        fail(step.name, text, verdict="未达成")
                    return text

                report.note(
                    "取证模式：模板前置检查已在上游通过 —— 逐步执行 L5–L15；点击点一律取自"
                    "**实测**（模板命中处），读不出哪一档、量不到哪一步就判「不过」并停。"
                )

                # ── L5 点「新游戏」：点 L4 **实测**到的按钮位置（不是 ROI 中心）──────────
                if hit is None:  # 结构上到不了这里（L4 命中才会走到这一行）
                    fail(l5.name, "L4 没给出 `btn_new_game` 的命中位置 ⇒ 点不了（不盲点）")
                hit_x, hit_y = int(hit.x), int(hit.y)  # type: ignore[attr-defined]
                click_at(hit_x, hit_y)
                # 🔧 t8 修：这里原来传的是 `l5.roi`（= `main_menu`，**L5 自己那一屏**的 ROI），
                #    而 `btn_game_rules` 是**目标屏**（「目标」屏）上的按钮，它的 ROI 是
                #    `setup_rules` ⇒ 每次都等满 90 s 超时，Pass B 首跑 exit 1（证据：
                #    `tools/out/auto/pass-20261001-055543-harsh/stage6-ui-20261001-055543.md`）。
                #    `NEXT_SCREEN`（`:955-957`）早就把「目标屏模板, 目标屏 ROI」写对了，改成用它
                #    —— 与下面 L6 在 `l6.roi` 里找 `btn_game_rules` 的口径一致。
                l5_next_roi = NEXT_SCREEN[l5.name][1]
                image, prev = wait_for_screen("btn_game_rules", l5_next_roi, l5.frame, prev)
                shot = ga.save_shot(image, l5.frame)
                report.step(
                    l5.name,
                    "过",
                    f"{shot.name}；点 L4 实测的 ({hit_x},{hit_y})；正向判据 = `btn_game_rules` "
                    f"在「{l5_next_roi}」里出现（口径 §7：不许用「上一屏的模板消失」）",
                )

                # ── L6 打开规则窗：点目标屏上**实测**到的按钮位置 ───────────────────────
                found6, _s6 = locate_in_frame(
                    image, "btn_game_rules", roi=roi_of(l6.roi), directory=template_dir
                )
                if found6 is None:
                    fail(l6.name, "目标屏上没有 `btn_game_rules`（找不到就不点）")
                click_at(found6.x, found6.y)  # type: ignore[attr-defined]
                # 🔧 t8 修：判据 ROI 原来传 `l6.roi`（= `setup_rules`，**点击发生的那一屏**），
                #    但 `btn_rules_close` 是**规则窗**自己的凭据，落在 `rules_window` ROI
                #    （实测规则窗 X ≈ (1399,164)，`setup_rules` = x 442-624 / y 799-859 里没有它）
                #    ⇒ 同一类超时。与 L5 的修法同源：判据 ROI 用**目标屏**的，不用点击屏的。
                image, prev = wait_for_screen("btn_rules_close", "rules_window", l6.frame, prev)
                shot = ga.save_shot(image, l6.frame)
                report.step(
                    l6.name,
                    "过",
                    f"{shot.name}；判据 = 规则窗自己的凭据 `btn_rules_close` 出现",
                )

                # ── L7 定位我们的卡片（复用侦察那套探索逻辑）────────────────────────────
                locator_hit, kept7, chain7 = locate_our_row(l7.frame)
                if not locator_hit:
                    fail(
                        l7.name,
                        f"滚到底也没命中 `rule_row_sitai`（阈值 {ROW_LOCATOR_THRESHOLD}）"
                        f"⇒ 规则窗里没找到我们那一行；留帧 {kept7 or '（无）'}",
                    )
                row_frame, _ = retry_frame()
                row_match = None
                row_score = 0.0
                if row_frame is not None:
                    row_match, row_score = locate_in_frame(
                        row_frame,
                        "rule_row_sitai",
                        roi=roi_of(l7.roi),
                        threshold=ROW_LOCATOR_THRESHOLD,
                        directory=template_dir,
                    )
                if row_match is None:
                    fail(
                        l7.name,
                        f"命中之后**再量一次**却没读到行标题（分 {row_score:.6f}，阈值 "
                        f"{ROW_LOCATOR_THRESHOLD}）⇒ 行心 y 给不出，L8 的箭头点不了",
                    )
                row_y = int(row_match.y)  # type: ignore[attr-defined]
                row_center_y = row_y + ROW_TITLE_TO_ROW_CENTER_DY
                shot = ga.save_shot(row_frame, l7.frame)
                report.step(
                    l7.name,
                    "过",
                    f"{shot.name}；命中 y={row_y}（分 {row_score:.6f} ≥ {ROW_LOCATOR_THRESHOLD}）"
                    f"⇒ 行心 y={row_center_y} = y + ROW_TITLE_TO_ROW_CENTER_DY"
                    f"({ROW_TITLE_TO_ROW_CENTER_DY})；拖动 sha 链 {chain7 or '（无）'}",
                )

                def tier_of(frame: Image.Image) -> tuple[str, str]:
                    """读出这一帧显示的是**哪一档**：判据在 :func:`read_tier`（恰一张命中才算读到）。

                    零张（模板都没命中）与多张（两张同时过阈值）**都算读不出** —— 读不出就报，
                    **绝不**假定默认中间档（口径 §3.2/§7）。
                    """
                    return read_tier(frame, tiers=tiers, roi=roi_of(l8.roi), directory=template_dir)

                def tier_reading(frame: Image.Image, name: str) -> tuple[bool, str]:
                    """**同帧**判据（实现与理由在 :func:`tier_evidence`）。"""
                    return tier_evidence(frame, name, roi=roi_of(l8.roi), directory=template_dir)

                def arrow_once(
                    direction: str, *, tag: str
                ) -> tuple[Image.Image | None, bytes, RowArrowSpot]:
                    """点一次 ◀/▶：帧从**实测**来、点完核对「画面真的变了」。"""
                    before, sig_before = retry_frame()
                    if before is None:
                        fail(l8.name, f"{tag}：连续 3 次抓不到图 ⇒ 量不到就不点（看不到 ≠ 没有）")
                    spot = click_row_arrow(
                        hwnd, which=direction, image=before, row_center_y=row_center_y
                    )
                    time.sleep(0.6)
                    after, sig_after = retry_frame()
                    if after is None:
                        fail(l8.name, f"{tag}：{direction} 点完之后抓不到图 ⇒ 中没中量不到")
                    if sig_after == sig_before:
                        report.note(
                            f"{tag}：{direction}（x={spot.x}）点完画面**逐字节没变** ⇒ 这一支到头"
                        )
                        return None, sig_after, spot
                    return after, sig_after, spot

                def land_on(want: str, *, tag: str) -> tuple[Image.Image, str]:
                    """用 ◀/▶ 把选中档挪到 `want`：**每一步都读档名核对**，落地即判三块模板。

                    返回 `(落地那一帧, 说明)`；走不到就抛。方向先右后左各试
                    `TIER_NAV_TRIES` 次（口径：◀/▶ 导航最多 4 次）。
                    """
                    frame_now, _sig_now = retry_frame()
                    if frame_now is None:
                        fail(l8.name, f"{tag}：抓不到图 ⇒ 读不出当前是哪一档")
                    now, why = tier_of(frame_now)
                    if not now:
                        fail(l8.name, f"{tag}：{why}")
                    for direction in ("next", "prev"):
                        for _try in range(TIER_NAV_TRIES):
                            if now == want:
                                return frame_now, f"{tag}：选中档 = `{want}`（{why}）"
                            step_frame, _sig, spot = arrow_once(direction, tag=tag)
                            if step_frame is None:
                                break  # 这一支到头，换方向
                            now, why = tier_of(step_frame)
                            if not now:
                                fail(l8.name, f"{tag}：{direction} 点完 {why}")
                            frame_now = step_frame
                            report.note(
                                f"{tag}：{direction}（x={spot.x}）之后读到 `{now}`（{why}）"
                            )
                    if now == want:
                        return frame_now, f"{tag}：选中档 = `{want}`（{why}）"
                    fail(
                        l8.name,
                        f"{tag}：◀/▶ 各试了 {TIER_NAV_TRIES} 次也没能选中 `{want}`"
                        f"（最后读到 `{now}`）—— 读不出/走不到就报，**不许**用别档顶替",
                    )
                    raise AssertionError("fail() 一定抛；这一行只为让「路径终止」写在纸面上")

                def judge_here(frame: Image.Image, name: str, *, tag: str) -> str:
                    """判 `name` 的三块模板并落帧，返回读数说明（不过就抛）。"""
                    ok, reading = tier_reading(frame, name)
                    shot = ga.save_shot(frame, tag)
                    if not ok:
                        fail(l8.name, f"`{name}` 三块模板没在同一帧各自命中：{reading}")
                    return f"{shot.name}；{reading}"

                # ── L8 逐档读到（三档 × 三块模板，同帧；缺模板按口径出声）──────────────
                missing8 = note_missing(l8)
                if missing8:
                    # 收料遍：缺逐档模板 ⇒ 不判，但把手上这一帧留下（L7 已停在我们那一行上，
                    # 这一帧就够裁「当前那一档」的模板；**不点、不改状态**）。
                    only = ga.save_shot(row_frame, f"{l8.frame}-collect-{args.lang}")
                    report.step(
                        l8.name,
                        "未达成",
                        f"{missing8}；收料遍留帧 {only.name}（L7 那一帧，**不当读数**）",
                    )
                    seen: dict[str, str] = {}
                else:
                    first, why_first = tier_of(row_frame)
                    if not first:
                        fail(l8.name, f"{why_first}（L8 要逐档读全，**不许**假定默认中间档）")
                    reading = judge_here(row_frame, first, tag=f"{l8.frame}-{first}-{args.lang}")
                    report.step(f"{l8.name}：{first}", "过", f"起点档；{reading}")
                    seen = {first: reading}
                    for other in tiers:
                        if other in seen:
                            continue
                        frame_at, why_at = land_on(other, tag=f"{l8.name}→{other}")
                        reading = judge_here(frame_at, other, tag=f"{l8.frame}-{other}-{args.lang}")
                        report.step(f"{l8.name}：{other}", "过", f"{why_at}；{reading}")
                        seen[other] = reading
                    if len(seen) < len(tiers):
                        fail(
                            l8.name,
                            f"三档没读全：读到 {sorted(seen)}；缺 "
                            f"{sorted(set(tiers) - set(seen))} —— 读不出的档如实缺席，"
                            "**不许**用别档顶替",
                        )
                    report.step(
                        l8.name,
                        "过",
                        "三档逐档读到（每档三块模板同帧）："
                        + "；".join(f"{t} = {seen[t]}" for t in tiers),
                    )

                # ── L9 应用并落定：**必须点「应用」**（只关窗不生效）────────────────────
                missing9 = note_missing(l9)
                if missing9:
                    report.step(l9.name, "未达成", f"{missing9}；收料遍不判该步")
                elif not seen:
                    report.step(
                        l9.name,
                        "未达成",
                        "L8 没读到任何一档 ⇒ 「应用后还是那一档」无从比对（**不当读数**）",
                    )
                else:

                    def apply_cycle(want: str, *, tag: str) -> str:
                        """把选中档挪到 `want` → 点「应用」→ 等窗关 → 重开 → **读回来核对**。"""
                        frame_before, why_land = land_on(want, tag=f"{tag} 选档")
                        apply_hit, apply_score = locate_in_frame(
                            frame_before,
                            "btn_rules_apply",
                            roi=roi_of(l9.roi),
                            directory=template_dir,
                        )
                        if apply_hit is None:
                            fail(
                                l9.name,
                                f"{tag}：「{l9.roi}」里没有 `btn_rules_apply`（分 "
                                f"{apply_score:.6f}）⇒ 不点，也不假装点过",
                            )
                        click_at(apply_hit.x, apply_hit.y)  # type: ignore[attr-defined]
                        closed = False
                        deadline = time.monotonic() + CHANGE_TIMEOUT
                        while time.monotonic() < deadline:
                            now_frame, now_sig = retry_frame(tries=1, wait=0.5)
                            if now_frame is None:
                                time.sleep(0.5)
                                continue
                            gone, _gone_score = locate_in_frame(
                                now_frame,
                                "btn_rules_close",
                                roi=roi_of(l6.roi),
                                directory=template_dir,
                            )
                            if gone is None:
                                closed = True
                                prev_sig_now = now_sig
                                break
                            time.sleep(0.5)
                        if not closed:
                            fail(
                                l9.name,
                                f"{tag}：点了「应用」，{CHANGE_TIMEOUT:.0f} 秒里规则窗没关 ⇒ "
                                "落没落定量不到（不许当它过了）",
                            )
                        # 重开：`btn_game_rules` 得**重新实测**（不许用上一次的坐标）
                        reopen_hit, reopen_score = locate_in_frame(
                            now_frame,
                            "btn_game_rules",
                            roi=roi_of(l6.roi),
                            directory=template_dir,
                        )
                        if reopen_hit is None:
                            fail(
                                l9.name,
                                f"{tag}：关窗之后「{l6.roi}」里没有 `btn_game_rules`"
                                f"（分 {reopen_score:.6f}）⇒ 重开不了，落定读不回来",
                            )
                        click_at(reopen_hit.x, reopen_hit.y)  # type: ignore[attr-defined]
                        # 🔧 t8 修：与 L6 同源 —— `btn_rules_close` 是规则窗的凭据，判据 ROI 是
                        #    `rules_window`，不是点击发生的那一屏（`l6.roi` = `setup_rules`）。
                        opened, prev_sig_now = wait_for_screen(
                            "btn_rules_close", "rules_window", f"{l9.frame}-reopen", prev_sig_now
                        )
                        after_tier, why_after = tier_of(opened)
                        if after_tier:
                            ok, reading = tier_reading(opened, after_tier)
                        else:
                            ok, reading = False, why_after
                        shot = ga.save_shot(
                            opened, f"{l9.frame}-{after_tier or 'unreadable'}-{args.lang}"
                        )
                        # 判据在 :func:`apply_outcome`（读回来≠刚才那一档 ⇒ 点名「只 Hide」）
                        verdict, why_text = apply_outcome(
                            want=want, after=after_tier, evidence_ok=ok
                        )
                        if verdict != "过":
                            fail(
                                l9.name,
                                f"{tag}：{why_text}（{shot.name}；{reading}）",
                                verdict=verdict,
                            )
                        return (
                            f"{tag}：{why_land} → 点「应用」→ 关窗 → 重开读到 `{after_tier}`"
                            f"（{shot.name}；{reading}）"
                        )

                    others = [t for t in tiers if t != target]
                    alt = others[0] if others else ""
                    # 先落一档**不是**目标档的（这一步才咬得住「只关窗」：只 Hide 的话重开读到的是
                    # 上一档，与刚才选的那一档不等 ⇒ 当场红），再落目标档
                    if alt:
                        report.step(
                            f"{l9.name}：先落 `{alt}`（咬「只关窗」）",
                            "过",
                            apply_cycle(alt, tag=f"{l9.name}[咬合]"),
                        )
                    report.step(
                        f"{l9.name}：再落 `{target}`",
                        "过",
                        apply_cycle(target, tag=f"{l9.name}[落定]"),
                    )

                # ── L10 选 RUS（点推荐国家卡片；进没进选中态如实说）──────────────────
                missing10 = note_missing(l10)
                if missing10:
                    report.step(l10.name, "未达成", f"{missing10}；收料遍不判该步")
                else:
                    landed, why10 = waited("card_country_rus", l10.roi)
                    if landed is None:
                        fail(l10.name, why10)
                    card_hit, card_score = locate_in_frame(
                        landed, "card_country_rus", roi=roi_of(l10.roi), directory=template_dir
                    )
                    if card_hit is None:
                        fail(l10.name, f"没读到 RUS 卡片的位置（分 {card_score:.6f}）⇒ 不点")
                    _, sig10 = retry_frame()
                    click_at(card_hit.x, card_hit.y)  # type: ignore[attr-defined]
                    time.sleep(args.step_wait)
                    after10, sig10_after = retry_frame()
                    if after10 is None:
                        fail(l10.name, "点了 RUS 卡片之后抓不到图 ⇒ 进没进选中态量不到")
                    changed = sig10_after != (sig10 or sig10_after)
                    still, still_score = locate_in_frame(
                        after10, "card_country_rus", roi=roi_of(l10.roi), directory=template_dir
                    )
                    shot = ga.save_shot(after10, l10.frame)
                    if not changed:
                        report.step(
                            l10.name,
                            "未达成",
                            f"{shot.name}；点 ({(card_hit.x, card_hit.y)}) 之后画面**逐字节没变**"
                            f"（卡片仍在：{still is not None}，分 {still_score:.6f}）⇒ "
                            "「进选中态」量不到，不写成过",
                        )
                    else:
                        report.step(
                            l10.name,
                            "过",
                            f"{shot.name}；点 ({(card_hit.x, card_hit.y)})（实测，分 "
                            f"{card_score:.6f}）之后画面变了；卡片仍在（分 {still_score:.6f}）"
                            "；选中态另由 L11 的「开始游戏」可用与真开局背书",
                        )

                # ── L11 开始游戏：真判据 = 引擎的 `Processing Tick:` **从无到有** ──────
                missing11 = note_missing(l11)
                if missing11:
                    report.step(l11.name, "未达成", f"{missing11}；收料遍不判该步")
                else:
                    before_tick = ga.tick_mark()
                    report.note(f"L11 点击前的时间真值：{before_tick.describe()}")
                    if before_tick.readable:
                        report.note(
                            "⚠️ 点击前就已经读得到 tick —— quarantine 之后本该是空的；"
                            "这一遍的「从无到有」因此按**递增**判（`is_later`）"
                        )
                    setup_frame, why11 = waited("btn_start_game", l11.roi, timeout=CHANGE_TIMEOUT)
                    if setup_frame is None:
                        fail(l11.name, why11)
                    start_hit, start_score = locate_in_frame(
                        setup_frame, "btn_start_game", roi=roi_of(l11.roi), directory=template_dir
                    )
                    if start_hit is None:
                        fail(l11.name, f"没读到「开始游戏」的位置（分 {start_score:.6f}）⇒ 不点")
                    click_at(start_hit.x, start_hit.y)  # type: ignore[attr-defined]
                    try:
                        after_tick = ga.wait_until_readable(timeout=LOAD_TIMEOUT)
                    except ga.NotRunningError as exc:
                        fail(
                            l11.name,
                            f"点了「开始游戏」之后 {LOAD_TIMEOUT:.0f} 秒里引擎一行 "
                            f"`Processing Tick:` 都没有 ⇒ 这一局**没起来**（{exc}）",
                        )
                    tick_verdict, tick_why = tick_outcome(before_tick, after_tick)
                    if tick_verdict != "过":
                        fail(l11.name, tick_why)
                    ingame, _sig11 = retry_frame()
                    shot = ga.save_shot(ingame, l11.frame) if ingame is not None else None
                    report.step(
                        l11.name,
                        "过",
                        f"{shot.name if shot else '（抓不到图，只有日志读数）'}；"
                        f"`Processing Tick:` {before_tick.describe()} → {after_tick.describe()}"
                        f"（点 ({(start_hit.x, start_hit.y)})，分 {start_score:.6f}）",
                    )

                # ── L12 放冲击（点探针决议；不点就没有记忆变量）────────────────────────
                missing12 = note_missing(l12)
                if missing12:
                    report.step(l12.name, "未达成", f"{missing12}；收料遍不判该步")
                else:
                    armed, why12 = waited("btn_probe_decision", l12.roi, timeout=CHANGE_TIMEOUT)
                    if armed is None:
                        fail(l12.name, why12)
                    dec_hit, dec_score = locate_in_frame(
                        armed, "btn_probe_decision", roi=roi_of(l12.roi), directory=template_dir
                    )
                    if dec_hit is None:
                        fail(l12.name, f"没读到决议按钮的位置（分 {dec_score:.6f}）⇒ 不点")
                    _, sig12 = retry_frame()
                    click_at(dec_hit.x, dec_hit.y)  # type: ignore[attr-defined]
                    image, prev = wait_changed(l12.frame, sig12 or prev)
                    shot = ga.save_shot(image, l12.frame)
                    still, still_score12 = locate_in_frame(
                        image, "btn_probe_decision", roi=roi_of(l12.roi), directory=template_dir
                    )
                    report.step(
                        l12.name,
                        "过",
                        f"{shot.name}；点 ({(dec_hit.x, dec_hit.y)})（实测，分 {dec_score:.6f}）"
                        f"之后画面变了；决议项仍在={still is not None}（分 {still_score12:.6f}）"
                        "—— 记忆变量由 L14 三行背书",
                    )

                # ── L13 引擎日志的难度读数（承重：两族都要）────────────────────────────
                facts = difficulty_log_expectations(target)
                deadline = time.monotonic() + CHANGE_TIMEOUT
                rows: list[str] = []
                problems: list[str] = [f"还没读到（{ga.DEBUG_LOG}）"]
                while time.monotonic() < deadline:
                    text = (
                        ga.DEBUG_LOG.read_text(encoding="utf-8", errors="replace")
                        if ga.DEBUG_LOG.is_file()
                        else ""
                    )
                    rows, problems = read_probe_facts(text, facts)
                    if not problems:
                        break
                    time.sleep(2.0)
                if problems:
                    fail(
                        "L13 引擎日志读数",
                        "；".join(problems)
                        + f"（读到 {len(rows)} 行；日志 {ga.DEBUG_LOG}；期望档 `{target}`）",
                    )
                report.step(
                    "L13 引擎日志读数",
                    "过",
                    "两族读数齐（" + "；".join(str(row) for row in rows) + "）",
                )

                # ── L14 G3 三行（JE 面板：三块首段模板**同帧**各自命中）────────────────
                missing14 = note_missing(l14)
                if missing14:
                    report.step(l14.name, "未达成", f"{missing14}；收料遍不判该步")
                else:
                    line_names = WILDCARD_EXPAND["je_line_*"]
                    deadline = time.monotonic() + CHANGE_TIMEOUT
                    frame14 = None
                    reading14 = "（还没量到）"
                    while time.monotonic() < deadline:
                        now_frame, _sig14 = retry_frame(tries=1, wait=0.5)
                        if now_frame is None:
                            time.sleep(1.0)
                            continue
                        parts14: list[str] = []
                        missing_lines: list[str] = []
                        for line_name in line_names:
                            found, score = locate_in_frame(
                                now_frame,
                                line_name,
                                roi=roi_of(l14.roi),
                                directory=template_dir,
                            )
                            parts14.append(
                                f"{line_name} {score:.6f}{'✓' if found is not None else '✗'}"
                            )
                            if found is None:
                                missing_lines.append(line_name)
                        reading14 = "、".join(parts14)
                        if not missing_lines:
                            frame14 = now_frame
                            break
                        time.sleep(2.0)
                    if frame14 is None:
                        fail(
                            l14.name,
                            f"「{l14.roi}」里三行**没有同帧读全**：{reading14} "
                            "（缺一行即红；三行的前置：RUS + 冲击已放出 + 在对的那页）",
                        )
                    shot = ga.save_shot(frame14, l14.frame)
                    report.step(l14.name, "过", f"{shot.name}；三行同帧命中：{reading14}")

                # ── L15 修正旁证（**只是旁证**，不出「不过」）────────────────────────────
                chip = f"chip_tier_{target}"
                chip_frame, _sig15 = retry_frame(tries=1, wait=0.5)
                if chip_frame is None:
                    report.step(l15.name, "未达成", "抓不到图 ⇒ 旁证量不到（本来就不出「不过」）")
                elif not (template_dir / f"{chip}.png").is_file():
                    report.step(l15.name, "未达成", f"缺模板 `{chip}` ⇒ 旁证量不到")
                else:
                    found15, score15 = locate_in_frame(
                        chip_frame, chip, roi=roi_of(l15.roi), directory=template_dir
                    )
                    shot = ga.save_shot(chip_frame, l15.frame)
                    report.step(
                        l15.name,
                        "过" if found15 is not None else "未达成",
                        f"{shot.name}；`{chip}` 读 {score15:.6f}"
                        f"（{'命中' if found15 is not None else '没命中'}；旁证，不是承重墙）",
                    )
        finally:
            ga.SHOT_DIR = shot_dir_before  # 落帧出口还原（进程内状态一并还回，别留给下一次调用）
            killed = ga.kill_game()
            time.sleep(2)
            if previous:
                ga._set_foreground(previous)
            restored = "按 --no-restore 保留安装" if args.no_restore else None
            if not args.no_restore:
                restored = experiments.restore_content_load()
                restored = (
                    "content_load.json 已还原" if restored else "content_load.json 本来就一致"
                )
            after = sha256(content_load()) if content_load().is_file() else ""
            extra["content_load_sha256_after"] = after
            extra["content_load_same"] = bool(before_hash) and before_hash == after
            extra["victoria3_alive_after"] = ga._process_pids()
            extra["elapsed_seconds"] = round(time.monotonic() - started, 1)
            report.step(
                "收尾三件",
                "过"
                if (not extra["victoria3_alive_after"] and extra["content_load_same"])
                else "不过",
                f"杀 {killed or '（没有）'}；{restored}；sha256 一致={extra['content_load_same']}；"
                f"残留={extra['victoria3_alive_after']}",
            )
            # **失败也要留摘要**：异常正在飞的时候，把「跑到哪一步、为什么没达成」落到盘上。
            # 没有这一条，崩溃遍在产物里**没有痕迹**（第四遍就是这样：纯色帧抛错 ⇒ 无摘要）。
            if sys.exc_info()[0] is not None:
                report.step("本步未达成", "未达成", f"{sys.exc_info()[1]}")
                summary_path.write_text(report.render(extra=extra), encoding="utf-8", newline="\n")
                print(f"运行摘要（失败也留）：{summary_path}")

    summary_path.write_text(report.render(extra=extra), encoding="utf-8", newline="\n")
    print(f"运行摘要：{summary_path}")
    failed = any(verdict == "不过" for _n, verdict, _d in report.rows)
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    """命令行接口（**单独一个函数**：用例按同一份定义构造 `args`，不会与真入口漂开）。"""
    parser = argparse.ArgumentParser(prog="stage6_ui_rerun", description=__doc__)
    parser.add_argument("--tier", default="harsh", choices=sorted(TIERS), help="要落定的难度档")
    parser.add_argument("--lang", default="l_simp_chinese", choices=sorted(LANGS), help="界面语言")
    parser.add_argument("--evidence", default="tools/out/auto", help="证据目录（帧 + 运行摘要）")
    parser.add_argument("--archive", default="", help="探针盯哪份档案（缺省=数据源里第一份）")
    parser.add_argument(
        "--recon", action="store_true", help="侦察模式：按估计 ROI 点、不要模板命中"
    )
    parser.add_argument(
        "--collect",
        action="store_true",
        help=(
            "收料遍：缺模板时**不止步**，按 ROI 中心点下去并把帧留下（判据列如实写"
            "「未达成（缺模板 …）」，**不当读数**）。承重遍不许带它 —— 没有判据就不许往前走"
        ),
    )
    parser.add_argument("--wheel", type=int, default=3, help="侦察时在规则窗里滚几格")
    parser.add_argument(
        "--scrolls",
        type=int,
        default=4,
        help=(
            "L7 最多滚几次（**每次留一帧**）。第七遍的教训：滚 3 格不够 —— `22` 里还是"
            "原版行、我们那一行没进画面；而「找到为止」需要先有「我们那一行」的定位物，"
            "所以这一步先**收素材**，不许在没有定位物时写「已定位」"
        ),
    )
    parser.add_argument("--step-wait", type=float, default=2.0, help="点点之间等画面稳定")
    parser.add_argument("--window-timeout", type=float, default=300.0)
    parser.add_argument("--boot-timeout", type=float, default=300.0)
    parser.add_argument("--skip-preflight", action="store_true", help="跳过只读自检（不建议）")
    parser.add_argument(
        "--row-arrows",
        action="store_true",
        help=(
            "允许点我们那一行的逐档箭头（◀/▶）—— **每一次点击前都过琥珀镜像三角自检**，"
            "检不到就不点、报明确失败。缺省不点：点 ◀ 会挪走选中档位，而 `--tier` 是调用方"
            "指定的档，顺手改掉会让「落定哪一档」这件事失去出处"
        ),
    )
    parser.add_argument("--no-restore", action="store_true", help="跑完不还原 mod 配置（调试用）")
    parser.add_argument(
        "--note",
        action="append",
        default=[],
        help=(
            "写进运行摘要「说明」栏的自由文本（可给多次）。"
            "**外部负载规模必须走这里**：否则事后谁也分不清"
            "「帧不对」是驱动错还是环境扰动（队长 02:29 的要求）"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # 控制台编码：本机 cmd 是 GBK，而 preflight 的报告里有 ✅/❌ —— 不换 UTF-8 会在
    # **打印报告**那一步抛 `UnicodeEncodeError`（实测踩到，而且它盖住了真正的退出码）。
    # `-X utf8` 只覆盖"用 `-X utf8` 起"的那条走法；口径 §10 写的入口命令不带它，
    # 所以要在进程内自己修。
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
