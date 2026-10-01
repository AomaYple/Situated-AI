"""UI 模板的**信息量闸门**：平底误裁不许进 ``tools/probe/sitai_ui/``（B118 / 阶段6 §3.10）。

为什么要有这条闸门（现场，不是假想）
------------------------------------

阶段 6 的 UI 流程靠**模板匹配**定位控件。模板一旦是「平底误裁」——截到的是一块没有
文字、没有图形的背景——匹配就退化成「哪里都一样」：它会**自证** 1.0000，而在阴性图上
还能报出 0.7489 / 0.5635 这种看着不错的分数，于是整条链路读出**假绿**。实测（队长
2026-09-25 08:33 现测，`阶段6-实机读数.md` §3.10）：``zh/`` 当时 11 张模板里有 3 张是
这样 —— ``rule_row_sitai.png``（96×30，L 标准差 2.0、亮像素 0、琥珀像素 0）、
``btn_rule_prev.png``（std 4.0、0/0）、``btn_rule_next.png``（std 4.4、0/0），而真模板
``card_country_rus.png`` 是 std 58.9 / 亮像素 1019。这三张直接污染了 L7（行定位）与
L8（逐档箭头）的读数 —— **假绿不是流程的错，是输入没料**。

判据（写死在这里，别处不许另立一套）
------------------------------------

逐张图算四个数：

* ``mean`` / ``std``：``L`` 的均值与**总体**标准差（除以 N，不是 N−1）；
* ``bright``：``L ≥ 150`` 的像素数；
* ``amber``：``R−B ≥ 45 且 R ≥ 130 且 G ≥ 90`` 的像素数（这个 UI 的强调色）。

**一张模板被判「有信息」的下界 = ``bright ≥ 10`` 或 ``amber ≥ 10``。**

``L`` 的定义是 **``(R+G+B)/3``（三通道算术平均）—— 不是 ``PIL.Image.convert("L")``**。
后者是 ITU-R 601 加权亮度（``0.299R+0.587G+0.114B``），对金色箭头能差出 ~4.6 个标准差
（功能工程师用 601 量到 40.7，队长用平均法量到 36.1 —— 不是谁错，是两把尺子）。
本文件的读数基准 = 审计脚本 ``tools/out/auto/b118_template_audit.py`` 与 §3.10 那张表，
两者都用**平均法**；:func:`test_尺子口径_必须用三通道算术平均` 用一个纯红像素把这件事钉住。

为什么这个下界说得过去：这个界面是**暗底 + 亮字/亮图形**（按钮文字、标题、卡面文字都是
浅色，强调态是琥珀色）⇒ 任何**真的截到控件**的模板都会带相当数量的亮像素或琥珀像素；
而「平底误裁」的亮/琥珀像素数**恰好是 0**（三张坏样本的实测值）。两条下界同时给，是因为
有的模板几乎全是琥珀底色（``btn_rules_apply.png``：琥珀 789、亮 264）。

⚠️ **这是下界，不是充分条件**：它拦的是「完全没料」，拦不住「料不对」——例如截到了别的
控件，或者一块**均匀的琥珀色**（均匀琥珀会把图判成有信息，因为 ``amber`` 够）。「结构对
不对」要靠 L7/L8 的**阴性最差**读数去看，不在本用例的判据里。

白名单自清（不留暗门）
----------------------

``WHITELIST`` 只允许出现「**现在仍然**判无信息」的模板：条目还在、而模板已经被换掉 ⇒
用例判红，逼人把条目删掉。理由：那三张的处境是**暂时**的（功能工程师已按 §3.10 的实测
坐标重裁完毕），白名单若能永久留着，它就变成「坏模板永久豁免」的暗门 —— 比没有闸门更坏。
反过来，白名单里的名字在盘上找不到也要判红：改名/删文件之后条目会静默失效。

阴性对照（判据不许当橡皮图章）
------------------------------

两类都在：① B118 现场那两张平底标本（``tools/out/evidence/b117-arrow-left-958x740.png``
与 ``b117-arrow-right-1266x740.png``，各 1,413 B / 1,217 B）—— 它们的**字节逐字嵌在本文件
里**（见 ``_ARCHIVE_PNG``）。为什么嵌进来：``tools/out/*`` 被 ``.gitignore:43`` 挡住，
干净克隆上根本没有这两个文件，而契约不许用 skip 绕过去 ⇒ 嵌进来之后「同一批像素」在任何
机器上都被判一次；盘上那份还在时再逐字节对一次（防归档被换掉或损坏）。② 内存里合成的
平底图与「只有 9 个亮像素」的边界图（不写盘）。另有两条**正向**对照：真模板
``card_country_rus.png`` 必须判有信息，以及合成一张刚好 10 个亮像素的图必须判有信息
（证明判据不是恒假，边界口径也钉住）。
"""

from __future__ import annotations

import base64
import hashlib
import io
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image

from pdx import config

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

#: 模板根目录：**按语言分子目录**（``zh/``，将来加 ``en/``；口径见本目录 README §「目录结构」，
#: 两套语言混在一起会出「中文模板匹配到英文界面」的假绿）。
TEMPLATE_ROOT = config.REPO / "tools" / "probe" / "sitai_ui"

#: B118 归档件所在目录（``tools/out/*`` 被 .gitignore 挡住 ⇒ 只在有现场记录的机器上存在）。
ARCHIVE_DIR = config.REPO / "tools" / "out" / "evidence"

#: 判据的三条阈值。**改这里等于改判据**，必须同时改模块 docstring 里那段说明。
BRIGHT_L = 150.0
BRIGHT_MIN = 10
AMBER_MIN = 10
AMBER_RB = 45
AMBER_R = 130
AMBER_G = 90

#: 白名单：只有「**现在仍然**判无信息」的模板才许留在这里（理由见模块 docstring）。
#:
#: 2026-09-25 起它是**空的**：那三张平底误裁已按 §3.10 的实测坐标重裁完毕，并且新增了
#: ``tier_uniform_name.png`` ⇒ 现读 ``zh/`` 共 12 张、**全部有信息**（平均法读数：
#: ``rule_row_sitai.png`` 73×22 / std 40.1 / 亮 117 / 琥珀 0；``btn_rule_prev.png`` 13×22 /
#: std 36.1 / 亮 10 / 琥珀 125；``btn_rule_next.png`` 13×22 / std 36.2 / 亮 10 / 琥珀 125；
#: ``tier_uniform_name.png`` 72×21 / std 32.8 / 亮 76 / 琥珀 0）。
#: 换掉之前的读数留痕（**只写在注释里**，不进判据）：``rule_row_sitai.png`` 96×30 /
#: std 2.0 / 0 / 0；``btn_rule_prev.png`` std 4.0 / 0 / 0；``btn_rule_next.png`` std 4.4 / 0 / 0。
WHITELIST: dict[str, str] = {}

#: B118 两张平底标本的**逐字节**拷贝（base64）—— 见模块 docstring「阴性对照」。
_ARCHIVE_PNG: dict[str, str] = {
    "b117-arrow-left-958x740.png": (
        "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"
        "L7s9hyP/BzHD+h/wnHhwAAAAAElFTkSuQmCC"
    ),
    "b117-arrow-right-1266x740.png": (
        "iVBORw0KGgoAAAANSUhEUgAAACgAAAAoCAIAAAADnC86AAAEiElEQVR42n1YS5LdOAwDGK2ncpQsJvc/03yybGIW"
        "/Mp+mddV3XZbFiUQAKnHH3/+BAkAyL8SSEiIGxr7eo+Mf5IACEBx/xqTI+//Azi/fv2b94AAgoLiGsoH+UYN6Cjo"
        "N+tZ/n58dI8EAByj9ZvMGNyDV+gOV4v/GGZFEa4l7/WdP75/f+AsibzmG+Tfn8ZwZ4jP5ewZYn5D5UbKZOyoJHe+"
        "J9jjYqcUH0OvhUqQDkmQicS6iKixPrMVC+h7PaZnJYac2BJISTM/SeAEaXOXcl5JaxIxKQDwxea145tCAQCJiFoQ"
        "QpJkciW88ljtUOfOSqL0Rvjj9b7lmlaKdRzkVj1X+spTJF7vRC42JZIS4vn/UCsRoUGlFy65BrlVEZmTPsmtG1zy"
        "ivpbMlKSzUsE2AQhuBgG0uwZbwNbT9mQrpS9JUCjNcLyMqrAS4umkNyhCpZb19wCtN+EqQvVWgPFk5QhB/6kJ4HQ"
        "tNq7yMQTbV1BWqMyF28D46RDKmJHYN6eGK5CAZQW6eJX6CiTmVyTe4MFffaN7RCSLPENzEkQOUsC8VKLIPfZ8axJ"
        "0CtqK3BJKyRgu4Kw1ktLcmkVlsAZDKJxwhSAkq6y1SH50hV5coyHBJOKctHswjlS28VF+OgbXTJ3KULKUvkDArC0"
        "JGJJpyiaPNctOHRSPtAn60paVVcYZjZH8zY2m7bPgktbyFePkQ6Dt4MKkLvq83pxULFSZKlXgmqV3Om9Ogr1WxM1"
        "eRv7fPilHj0LcSJxTCmr60EnVM3MlI9YGKqtSp672r1O7TSFV70XSAoWtUKrbEkuSf41wHLVxhZJb03CWLTQaUPk"
        "zoaPa0Gni/PS/rgY9GqrggQP2YwXdqWfBDPXtspCtz4ar4Z9s2LmXQl2ZTNbRWkZBTgel4vOBO8WVNIZxPIJr4a2"
        "QVwcurvdi2O8ZAaUblnKDx8GYQ+uQ0rL7Ki6GmNNZ5CJ7A2t1NQ7ykENftofUtRSm1H3FTFF9wIRwrXqALuP2bVA"
        "7jEsOgmSAlyV+1K/FR1sNL933wWglD5+zn2MWO7Qx4KLcXtGQTKA/vUl+dJDKV7bLBEV1300oSWgBVKaGpcuiCFC"
        "ZNyyQ3O5e/BK8qtBwvYQkhRS6t23lDnP3GhczMxsvN6y2bJMvhGkFxJX43jLeQ9A+8JIJudnoZQbG6t1uRDO5XJJ"
        "VearRoFTm7LnxJ3ehnB5FpvIszK5+Dw+qrwiTggSAHdvEt89goY9taFUPZfUVqt0HUiy2hOAmZke59ZMuUuO7rAY"
        "uW+Qu9/mbqe0OslMqlnjrzo7xYjD2Vx1lMIqw6yODLTAUZmFLlBtZ2HAZdhFB25PZRXVUxUJ04mwXH5Xt9kIPFKQ"
        "gpntch14qUaKq6az2/DjZT2uAmQZQsSP3nNsZJUp7QTv3pKqqPc5IWHSkRzqpqGWv74ygSA4QxMM21E1uvXVhbxP"
        "pONuksxTidTsAoTcwkirLHCEHIeGqpVJdddSCwR47MjYiksSsRRF6nG6kwCef/76e5+z+ajBni3RALbVcrUPewya"
        "hjnGr4MWhP8A9F4zNH9vOFoAAAAASUVORK5CYII="
    ),
}
#: 上面这些字节的 sha256（防嵌入时抄错；也用来跟盘上那份对账）。
_ARCHIVE_SHA256: dict[str, str] = {
    "b117-arrow-left-958x740.png": "8cf32fef35cfde5cf2de884cede48f30c633c3cdaf135e8158b938c00c7e8d54",
    "b117-arrow-right-1266x740.png": "378cfdf638eaa077d5cd12ece0ff9c845983c93396a5e65b804752cb87916fff",
}


@dataclass(frozen=True, slots=True)
class Stats:
    """一张模板的读数（判据只用到这四个数）。"""

    name: str
    width: int
    height: int
    mean: float
    std: float
    bright: int
    amber: int

    @property
    def carries_information(self) -> bool:
        """下界判据：``bright ≥ 10`` **或** ``amber ≥ 10``（见模块 docstring 的两条理由）。"""
        return self.bright >= BRIGHT_MIN or self.amber >= AMBER_MIN

    def line(self) -> str:
        return (
            f"{self.name}：{self.width}×{self.height} / L 均值 {self.mean:.1f} / "
            f"标准差 {self.std:.1f} / 亮像素 {self.bright} / 琥珀像素 {self.amber}"
        )


def _stats(image: Image.Image, name: str) -> Stats:
    """按判据算四个数（``L`` 用三通道算术平均，见模块 docstring）。"""
    arr: np.ndarray = np.asarray(image.convert("RGB"), dtype=np.int16)
    red, green, blue = arr[..., 0], arr[..., 1], arr[..., 2]
    lum = (red + green + blue) / 3.0
    amber = ((red - blue) >= AMBER_RB) & (red >= AMBER_R) & (green >= AMBER_G)
    height, width = arr.shape[0], arr.shape[1]
    return Stats(
        name=name,
        width=int(width),
        height=int(height),
        mean=float(lum.mean()),
        std=float(lum.std()),
        bright=int((lum >= BRIGHT_L).sum()),
        amber=int(amber.sum()),
    )


def _load(path: Path) -> Image.Image:
    """读盘上的图（``convert`` 会强制解码，所以退出 ``with`` 之后图仍然可用）。"""
    with Image.open(path) as img:
        return img.convert("RGB")


def _from_bytes(payload: bytes, name: str) -> Image.Image:
    """从内存里的字节解码（**不写盘**：``io.BytesIO`` 就是文件对象）。"""
    with Image.open(io.BytesIO(payload)) as img:
        return img.convert("RGB")


def _template_dirs() -> list[Path]:
    """**带模板的语言目录**（按目录遍历，不写死清单 ⇒ 将来加 ``en/`` 无需改用例）。"""
    if not TEMPLATE_ROOT.is_dir():  # pragma: no cover - 模板目录整棵没了才会走到
        return []
    return sorted(
        d
        for d in TEMPLATE_ROOT.iterdir()
        if d.is_dir() and any(p.suffix == ".png" for p in d.iterdir())
    )


def _template_pngs() -> list[Path]:
    """所有模板（每个语言目录下每张 ``.png``），按路径排序。"""
    return sorted(p for d in _template_dirs() for p in d.glob("*.png"))


def _id(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


def _whitelist_problem(name: str, stats: Stats | None, why: str) -> str | None:
    """白名单条目的问题（``None`` = 这条合格）。

    拆成纯函数是为了让「两种状态都绿」这两句话**可执行**：真盘上只有一种状态
    （现在是 (b)：三张都换掉了 ⇒ 白名单空），另一种状态只能用合成读数撞。
    """
    if stats is None:
        return (
            f"白名单里的 `{name}` 在盘上找不到（登记理由：{why}）⇒ 删掉这条 —— "
            "条目指向一个不存在的模板，它会**静默失效**（改名/换掉之后没人会回来删）"
        )
    if stats.carries_information:
        return (
            f"白名单条目过期：{stats.line()} ⇒ 这张模板**已经有信息**了，"
            f"`WHITELIST` 里的 `{name}` 必须删掉（留着就是「坏模板永久豁免」的暗门）"
        )
    return None


# ────────────────────────── 扫描口径 ──────────────────────────


def test_扫描按语言目录遍历而不是写死清单() -> None:
    """扫描面本身也是判据：目录结构变了（多语言、模板搬走）要立刻看得见。"""
    dirs = _template_dirs()
    pngs = _template_pngs()
    assert dirs, f"{TEMPLATE_ROOT} 下没有任何语言目录带模板 —— 扫描面没了，闸门等于不存在"
    assert pngs, "一张模板都没扫到"
    assert {p.parent.name for p in pngs} == {d.name for d in dirs}, "有语言目录没被扫到"

    # 根目录下那张 `loading-ref-64x36.png` 是**载入画面基准**（README §「载入画面基准」：
    # 它是盒① 第二遍的判据，64×36 灰度缩略图），**不是模板** ⇒ 故意不扫它。
    # 这一条把「故意」写出来：谁要是把扫描改成递归 glob，就会把它当成模板来判。
    root_pngs = sorted(p.name for p in TEMPLATE_ROOT.glob("*.png"))
    assert root_pngs, "根目录那张载入基准不见了 —— 目录结构变了，扫描口径要重新看一遍"
    assert all(p.parent != TEMPLATE_ROOT for p in pngs), (
        "模板不该出现在根目录（只有载入基准在那儿）"
    )


# ────────────────────────── 主闸门 ──────────────────────────


@pytest.mark.parametrize("path", _template_pngs(), ids=_id)
def test_每张模板都必须携带信息(path: Path) -> None:
    stats = _stats(_load(path), _id(path))
    assert stats.carries_information, (
        f"{stats.line()} ⇒ 判「**无信息**」（下界：亮像素 ≥ {BRIGHT_MIN} 或琥珀像素 ≥ {AMBER_MIN}）。"
        "两条路，按实际情形挑一条：\n"
        "  ① 这张模板**真的是平底误裁** ⇒ 重新裁一张带控件的（L7/L8 的假绿就是它给的，"
        "口径见 `阶段6-国家身份开局-取证口径.md` §2/§9）；\n"
        f"  ② 你**刚把它换掉**、白名单里还留着名字 ⇒ 删掉 `WHITELIST` 里那一/几条"
        "（本文件顶部「白名单自清」那段写了为什么）。"
    )


def test_白名单自清_条目必须仍然无信息且仍在盘上() -> None:
    """白名单只许放「现在仍然无信息」的模板：换掉了还留着 ⇒ 判红（不留永久豁免的暗门）。"""
    for name, why in sorted(WHITELIST.items()):
        candidates = [p for p in _template_pngs() if p.name == name]
        stats = _stats(_load(candidates[0]), _id(candidates[0])) if candidates else None
        problem = _whitelist_problem(name, stats, why)
        assert problem is None, problem


def test_白名单机制_两个方向都被撞到() -> None:
    """用**合成读数**把白名单的两种状态各撞一次（真盘上只有一种状态，测不全）。

    状态 (a) 模板未换（仍然无信息）⇒ 条目合格；状态 (b) 模板已换（有信息）⇒ 条目必须删掉；
    外加「条目指向不存在的模板」⇒ 也要判红。这三条是「两种状态都绿 + 过期即红」的可执行版。
    """
    flat = Stats(name="zh/坏模板.png", width=96, height=30, mean=18.0, std=2.0, bright=0, amber=0)
    good = Stats(
        name="zh/好模板.png", width=73, height=22, mean=63.0, std=40.1, bright=117, amber=0
    )

    assert _whitelist_problem("坏模板.png", flat, "平底误裁，等重裁") is None, (
        "仍无信息的条目应当被允许"
    )
    expired = _whitelist_problem("好模板.png", good, "平底误裁，等重裁")
    assert expired is not None, "模板已经有信息了，白名单条目必须被判过期"
    assert "必须删掉" in expired
    assert "暗门" in expired
    missing = _whitelist_problem("没了.png", None, "平底误裁，等重裁")
    assert missing is not None, "条目指向不存在的模板，必须判红"
    assert "找不到" in missing


# ────────────────────────── 阴性 / 阳性对照 ──────────────────────────


@pytest.mark.parametrize("name", sorted(_ARCHIVE_PNG))
def test_阴性对照_归档平底标本必须判无信息(name: str) -> None:
    """B118 现场那两张平底标本（字节嵌在本文件里）必须被判「无信息」。"""
    payload = base64.b64decode(_ARCHIVE_PNG[name])
    assert hashlib.sha256(payload).hexdigest() == _ARCHIVE_SHA256[name], (
        f"嵌进来的 {name} 与记录的 sha256 不符 —— 嵌入时抄错了"
    )
    stats = _stats(_from_bytes(payload, name), name)
    assert not stats.carries_information, (
        f"{stats.line()} ⇒ 这两张是**已证平底**的标本，必须判无信息；判成有信息说明判据退化了"
    )
    on_disk = ARCHIVE_DIR / name
    if on_disk.is_file():
        assert on_disk.read_bytes() == payload, (
            f"盘上的 {on_disk} 与本文件嵌入的字节不一致 —— 归档被换掉或改了："
            "要么更新嵌入的字节与 sha256，要么说明为什么归档该变"
        )


def test_阴性对照_合成平底图必须判无信息() -> None:
    """自己造平底图（不写盘）：完全平底、以及「只有 9 个亮像素」的边界。"""
    flat = _stats(Image.new("RGB", (96, 30), (18, 18, 22)), "合成平底（暗底）")
    assert not flat.carries_information, f"{flat.line()} ⇒ 平底必须判无信息"

    nearly = Image.new("RGB", (96, 30), (18, 18, 22))
    for x in range(BRIGHT_MIN - 1):  # 9 个亮像素：差一个不到下界
        nearly.putpixel((x, 0), (255, 255, 255))
    stats = _stats(nearly, f"合成平底（{BRIGHT_MIN - 1} 个亮像素）")
    assert not stats.carries_information, f"{stats.line()} ⇒ 不到下界就不算有信息（边界口径）"


def test_阳性对照_真模板必须判有信息() -> None:
    """§3.10 的阳性对照：``card_country_rus.png``（当时读到 std 58.9 / 亮 1019）。"""
    path = TEMPLATE_ROOT / "zh" / "card_country_rus.png"
    assert path.is_file(), f"缺阳性对照件 {path}（§3.10 记的是 std 58.9 / 亮像素 1019）"
    stats = _stats(_load(path), "zh/card_country_rus.png")
    assert stats.carries_information, f"{stats.line()} ⇒ 真模板必须判有信息（判据恒假了）"
    assert stats.bright >= 100, f"{stats.line()} ⇒ 与 §3.10 的 1019 差得太远，先核对是不是同一张图"


def test_阳性对照_合成亮块图必须判有信息() -> None:
    """边界口径的另一半：刚好 ``BRIGHT_MIN`` 个亮像素就要判有信息。"""
    img = Image.new("RGB", (40, 40), (18, 18, 22))
    for x in range(BRIGHT_MIN):
        img.putpixel((x, 0), (240, 240, 240))
    stats = _stats(img, f"合成亮块（{BRIGHT_MIN} 个亮像素）")
    assert stats.carries_information, f"{stats.line()} ⇒ 刚好到下界就应判有信息"


def test_尺子口径_必须用三通道算术平均() -> None:
    """``L`` 必须是 ``(R+G+B)/3``，不是 ``convert("L")`` 的 ITU-R 601 加权。

    纯红像素：平均法 = 85.0；601 加权 = ``0.299×255`` = 76.2。差 8.8 —— 对金色箭头
    能放大成 ~4.6 个标准差的读数差（功能工程师 40.7 vs 队长 36.1）。
    """
    red = _stats(Image.new("RGB", (4, 4), (255, 0, 0)), "合成纯红")
    assert abs(red.mean - 85.0) < 0.01, (
        f"{red.line()} ⇒ 均值不是 85.0 ⇒ 用的不是三通道算术平均（601 会给 76.2）"
    )
    blue = _stats(Image.new("RGB", (4, 4), (0, 0, 255)), "合成纯蓝")
    assert abs(blue.mean - 85.0) < 0.01, f"{blue.line()} ⇒ 重算一遍：算术平均对纯蓝也是 85.0"
