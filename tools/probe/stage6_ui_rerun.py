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
    "je_panel": (0.64, 0.04, 1.00, 0.98),
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
        #    (970,676,1066,706)，实测阈值 0.90），不是原来的 `rule_card_title_sitai`
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
    evidence = Path(args.evidence)
    evidence.mkdir(parents=True, exist_ok=True)
    report = Summary(tier=args.tier, lang=args.lang, recon=bool(args.recon))
    started = time.monotonic()
    previous = 0
    hwnd = 0
    stamp = datetime.now(UTC).astimezone().strftime("%Y%m%d-%H%M%S")
    summary_path = evidence / f"stage6-ui-{stamp}.md"
    extra: dict[str, object] = {"tier": args.tier, "lang": args.lang, "recon": bool(args.recon)}

    # ── 环境纪律：改动之前不许有会抛的操作（B79）────────────────────────────
    if not args.skip_preflight:
        pre = preflight.run()
        for line in pre.lines():
            print(f"  {line}")
        if pre.exit_code():
            report.note(f"preflight 没过（退出码 {pre.exit_code()}）—— 按口径 §7 照抄它的码退出")
            summary_path.write_text(report.render(extra=extra), encoding="utf-8", newline="\n")
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
                ① `find_in_roi` 把**抓图失败**（不是前台/最小化）也返回 `None` —— 它自己的
                docstring 就写着「要区分『看不到』与『没有』的调用方请直接用 screenshot」
                ⇒ 一次瞬时抓图失败会被读成「上一屏已消失」；
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
                    hit = ga.find_in_roi(hwnd, template, roi=ROIS[roi_name], directory=template_dir)
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
                """**拖动滚动条**直到定位到我们那一行（`rule_row_sitai`，阈值 0.90）。

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
                    hit = ga.find_in_roi(
                        hwnd,
                        "rule_row_sitai",
                        roi=ROIS["rules_window"],
                        threshold=ROW_LOCATOR_THRESHOLD,
                        directory=template_dir,
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
            while time.monotonic() < deadline:
                hit = ga.find_in_roi(
                    hwnd, "btn_new_game", roi=ROIS["main_menu"], directory=template_dir
                )
                if hit is not None:
                    break
                time.sleep(1.0)
            if hit is None:
                image, _ = grab()
                if image is not None:
                    ga.save_shot(image, "19-main-menu-NO-TEMPLATE-HIT")
                raise RuntimeError(
                    f"L4：等了 {LOAD_TIMEOUT:.0f} 秒也没在 `main_menu` ROI 里命中 "
                    "`btn_new_game` 模板 —— 主菜单没画出来（或模板不对），不写 ✅"
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
                    # 必须命中。阈值 0.90 是**量出来的**：正帧 1.0000、最近的假命中 0.7659
                    # （`tools/out/auto/crop_row_locator.py` 可复算）—— 不是把默认 0.75 放宽。
                    hit = ga.find_in_roi(
                        hwnd,
                        "rule_row_sitai",
                        roi=ROIS["rules_window"],
                        threshold=ROW_LOCATOR_THRESHOLD,
                        directory=template_dir,
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
                    ext_steps: tuple[
                        tuple[str, str, object, tuple[float, float, float, float]], ...
                    ] = (
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
                            report.note(
                                ("模板命中但画面没变 ⇒ **未变（边界或不可用）**，不是点空")
                                if kind == "template"
                                else "模板没命中且画面没变 ⇒ **点空**"
                            )
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
                report.note(
                    "取证模式：模板前置检查已在上游通过（模板齐了才会走到这里）——"
                    "接下来按 `STEPS` 表逐步执行 L4–L15。"
                )
        finally:
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


def main(argv: Sequence[str] | None = None) -> int:
    # 控制台编码：本机 cmd 是 GBK，而 preflight 的报告里有 ✅/❌ —— 不换 UTF-8 会在
    # **打印报告**那一步抛 `UnicodeEncodeError`（实测踩到，而且它盖住了真正的退出码）。
    # `-X utf8` 只覆盖"用 `-X utf8` 起"的那条走法；口径 §10 写的入口命令不带它，
    # 所以要在进程内自己修。
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="stage6_ui_rerun", description=__doc__)
    parser.add_argument("--tier", default="harsh", choices=sorted(TIERS), help="要落定的难度档")
    parser.add_argument("--lang", default="l_simp_chinese", choices=sorted(LANGS), help="界面语言")
    parser.add_argument("--evidence", default="tools/out/auto", help="证据目录（帧 + 运行摘要）")
    parser.add_argument("--archive", default="", help="探针盯哪份档案（缺省=数据源里第一份）")
    parser.add_argument(
        "--recon", action="store_true", help="侦察模式：按估计 ROI 点、不要模板命中"
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
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
