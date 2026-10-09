"""阶段 6 实机驱动的两组看守：**点击前自检**（B118）与**落帧按遍归档**（B114）。

为什么守这两处：

* **点击前自检**：真控件是**我们那一行**的琥珀镜像三角（`docs/design/exec/阶段6-实机读数.md`
  §3.10 现读：◀ x 1006–1017 / ▶ x 1343–1354，行带 y 731–751）。现场最容易出的事故不是
  「屏幕上没有箭头」，而是**坐标写偏了** —— 那时鼠标**照样点出去了**，要等下一支读数不动才
  暴露（第十六遍点 (958,740) / (1266,740) 落到相邻行的灰箭头就是这么发生的）。所以判据必须
  钉在**驱动真走的路径**上：单元级拿内嵌合成帧钉判据与失败文本，驱动级拿替身把 `run()` 走到底、
  钉「自检不过 ⇒ 一个鼠标键也没送出去、既有收尾照走、失败文本进归档」。
* **落帧按遍归档**：`tools/out/evidence/` 早先是扁平目录，同一 tier 跑第二遍就**静默覆盖**第一遍
  的帧 ⇒「A 遍的那一帧与 B 遍逐字节相同」事后无法复算（被撤回的那条 claim 正是缺这个对应关系，
  `backlog.md` B114）。触发点不只在「同名目录」：`pass-id` 的粒度是「秒 + tier」，**同一秒起两遍
  就撞名** —— 所以这条性质必须由代码保证（撞名顺位），不能靠"人不会在同一秒跑两遍"。

本文件**不读 `tools/out/**`**（那里的帧不在版本控制内、随时会变）：样本全部是**内嵌合成帧**
（先例：`tests/test_ui_templates.py` 的内嵌平样本）。合成帧的几何**照 §3.10 的现读读数**
摆，于是「自检正是拿那两个常量、在那两窗上放行」这件事在合成帧上可复现、可反复跑。
"""

from __future__ import annotations

import ast
import importlib.util
import random
import sys
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from PIL import Image, ImageDraw

from pdx import config

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from types import ModuleType

pytestmark = pytest.mark.unit

_PROBE = config.REPO / "tools" / "probe" / "stage6_ui_rerun.py"

# ── 合成帧的几何：**照 §3.10 的现读读数**（改这里＝改样本，不是改判据）────────────────
_ROW_CENTER_Y = 742  # 行心 = L7 命中 y 694 + ROW_TITLE_TO_ROW_CENTER_DY(48)
_PREV_X0 = 1006  # ◀ 像框左沿（真控件 1006–1017）
_NEXT_X0 = 1343  # ▶ 像框左沿（真控件 1343–1354）
_PREV_X = 1011  # ◀ 的**中心** = ROW_ARROW_PREV_X（哨兵窗 `row_arrow_crop_box` 的正中心）
_NEXT_X = 1348  # ▶ 的中心 = ROW_ARROW_NEXT_X
#: 逐列高度（尖→根）：和 = **125** —— 与 §3.10 现读的「琥珀 125 像素」同值
_PROFILE = (3, 4, 6, 8, 9, 11, 13, 15, 17, 19, 20)
#: 够大、也是"根粗尖细"，但**不镜像**（用证「镜像那一条在出力」的假样本）
_PROFILE_UNMIRRORED = (20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10)
_AMBER = (214, 160, 40)  # R−B=174、R=214 ≥ 130、G=160 ≥ 90 ⇒ 过琥珀判据
_BASE = (24, 26, 30)  # 底色：R−B < 0 ⇒ 一个像素都不算琥珀
_SIZE = (1920, 1080)


def _arrow(draw: ImageDraw.ImageDraw, *, x0: int, y: int, profile: tuple[int, ...]) -> None:
    """画一支箭头：一列一个矩形、**垂直居中在行心 y**。

    居中是必须的：相邻列的像素行要共享，才形成一个 4 邻接连通域（不居中就会被切成两半、
    每半都过不了 `ROW_ARROW_MIN_AMBER`，于是样本自己把自己判成"没有箭头"）。
    """
    for offset, height in enumerate(profile):
        half = height // 2
        draw.rectangle((x0 + offset, y - half, x0 + offset, y - half + height - 1), fill=_AMBER)


def _frame(
    marker: int = 0,
    *,
    prev_profile: tuple[int, ...] | None = _PROFILE,
    next_profile: tuple[int, ...] | None = tuple(reversed(_PROFILE)),
    prev_x0: int = _PREV_X0,
    next_x0: int = _NEXT_X0,
    row_center_y: int = _ROW_CENTER_Y,
) -> Image.Image:
    """一帧合成画面：行带上的两枚琥珀三角 + 不判「空白」的灰块 + 随 `marker` 移动的白块。

    * 灰块：`_is_blank()` 看**中央区灰度 std < 3.0** ⇒ 平底帧会让驱动以为自己还停在载入画面；
    * 白块：每次抓图**指纹都不同**（`wait_changed` / `wait_for_screen` 靠"与上一帧不同"往前走，
      吐同一张图会让那些轮询一直等到超时才结束）；
    * 白块与灰块**都不算琥珀**（R−B ≤ 0）⇒ 判据里只有那两枚箭头。
    """
    image = Image.new("RGB", _SIZE, _BASE)
    draw = ImageDraw.Draw(image)
    for index, gray in enumerate((40, 90, 150, 210)):
        left = 480 + index * 240
        draw.rectangle((left, 270, left + 239, 809), fill=(gray, gray, gray))
    white = 120 + (marker % 60) * 24
    draw.rectangle((white, 100, white + 11, 111), fill=(255, 255, 255))
    if prev_profile is not None:
        _arrow(draw, x0=prev_x0, y=row_center_y, profile=prev_profile)
    if next_profile is not None:
        _arrow(draw, x0=next_x0, y=row_center_y, profile=next_profile)
    return image


def _frame_without_prev() -> Image.Image:
    """缺 ◀（`ROW_ARROW_PREV_X` 那个窗里一个琥珀像素都没有）。"""
    return _frame(prev_profile=None)


def _frame_without_next() -> Image.Image:
    """缺 ▶。"""
    return _frame(next_profile=None)


def _frame_unmirrored() -> Image.Image:
    """两枚都在、都够大，但**形状不互成镜像**。"""
    return _frame(next_profile=_PROFILE_UNMIRRORED)


class _FrameFeed:
    """每次被 `ga.screenshot` 调用就吐一帧：**同一场景、`marker` 递增**。"""

    def __init__(self, factory: Callable[[int], Image.Image]) -> None:
        self.factory = factory
        self.calls = 0

    def __call__(self, _hwnd: int = 0, roi: object = None) -> Image.Image:
        self.calls += 1
        return self.factory(self.calls)


class _MouseLog:
    """驱动里的鼠标动作只有两个出口：`_set_cursor`（放光标）、`click_client`（送键）。

    「自检不过 ⇒ 不点」这条判据就靠它 —— 断言的是**实际发生的调用**，不是代码里有没有 `return`。
    """

    def __init__(self) -> None:
        self.cursor: list[tuple[int, int]] = []
        self.clicks: list[tuple[int, int]] = []


class _Match:
    """`find_in_roi` / `locate_state` 的替身返回值（只用到 `.x` / `.y`）。"""

    def __init__(self, x: int, y: int) -> None:
        self.x = x
        self.y = y

    def __str__(self) -> str:
        return f"(x={self.x}, y={self.y})"


def _fake_find_in_roi(_hwnd: int, name: str, **_kw: object) -> _Match:
    """`ga.find_in_roi` 的替身：**只给位置、不读像素**（真读盘模板的那条路不在本文件里）。

    `rule_row_sitai` 的 y 给 **694** —— 那是 §3.10 的现读命中点（行标题），行心 = 694 + 48 = 742，
    于是驱动里「**行心由定位到的那一行给出**」这条路径是真的被走的（不是拿常量糊过去）。
    """
    if name == "rule_row_sitai":
        return _Match(1018, 694)
    if name == "btn_new_game":
        return _Match(378, 434)
    return _Match(526, 827)


@pytest.fixture(scope="module")
def probe() -> ModuleType:
    """按路径加载驱动（`tools/probe/` 不是包；先例 `tests/test_probe_stage3.py`）。

    ⚠️ **先登记 `sys.modules` 再 `exec_module`**：本驱动里有 `@dataclass(frozen=True, slots=True)`，
    而 `dataclasses` 造 slots 类时要回头从 `sys.modules[cls.__module__]` 取模块 —— 没登记就会
    `AttributeError: 'NoneType' object has no attribute '__dict__'`（实测踩过）。
    """
    spec = importlib.util.spec_from_file_location("probe_stage6_ui_rerun", _PROBE)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def driver(probe: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    """把 `run()` 走一遍：**除 `ga.save_shot` 与 pass 目录逻辑外全是替身**（不碰实机）。

    走真码的部分正是本卡的两件事：`run()` 自己分 pass 目录、自己把 `ga.SHOT_DIR` 指过去、
    自己调 `ga.save_shot` 落帧；箭头那一步自己过自检、自己决定点不点。
    """
    root = tmp_path / "auto"  # --evidence：根目录里**先放一张既有扁平帧**（不许被碰）
    root.mkdir()
    flat = root / "19-main-menu.png"
    Image.new("RGB", (4, 4), _BASE).save(flat)
    flat_before = flat.read_bytes()
    load_file = tmp_path / "content_load.json"
    load_file.write_text('{"（用例）": 1}\n', encoding="utf-8")
    mouse = _MouseLog()
    teardown = SimpleNamespace(kill=0, restore=0)

    def _kill_game() -> list[int]:
        teardown.kill += 1
        return []

    def _restore_content_load() -> bool:
        teardown.restore += 1
        return True

    monkeypatch.setattr(
        probe.preflight, "run", lambda: SimpleNamespace(lines=list, exit_code=lambda: 0)
    )
    monkeypatch.setattr(probe.preflight, "probe_state_backup", lambda: None)
    monkeypatch.setattr(probe, "content_load", lambda: load_file)
    monkeypatch.setattr(probe.ab_probe, "deploy", lambda **_kw: "（用例）部署替身")
    monkeypatch.setattr(probe, "LOADING_REF", tmp_path / "（用例）没有这张载入参考图.png")
    #: 三态查找的**调用脚本**：非空时按序弹出（用例拿它造「启动期一连几次抓不到图」），
    #: 空则一律命中 —— L4 主菜单等待与模板步走的都是这条替身。
    state_script: list[tuple[str, object, str]] = []

    def _locate_state(*_a: object, **_kw: object) -> tuple[str, object, str]:
        if state_script:
            return state_script.pop(0)
        return (probe.LOOKUP_HIT, _Match(900, 500), "")

    monkeypatch.setattr(probe, "locate_state", _locate_state)
    monkeypatch.setattr(probe.ga, "_foreground_window", lambda: 0)
    monkeypatch.setattr(probe.ga, "launch", lambda **_kw: 4242)
    monkeypatch.setattr(
        probe.ga, "wait_for_boot_settle", lambda **_kw: SimpleNamespace(why="（用例）启动期替身")
    )
    monkeypatch.setattr(probe.ga, "ensure_foreground", lambda *_a, **_kw: None)
    monkeypatch.setattr(probe.ga, "_client_size", lambda _hwnd: _SIZE)
    monkeypatch.setattr(probe.ga, "find_in_roi", _fake_find_in_roi)
    monkeypatch.setattr(probe.ga, "mouse_drag", lambda *_a, **_kw: None)
    monkeypatch.setattr(probe.ga, "wait_stable", lambda *_a, **_kw: True)
    monkeypatch.setattr(probe.ga, "_set_foreground", lambda _hwnd: True)
    monkeypatch.setattr(probe.ga, "_set_cursor", lambda x, y: mouse.cursor.append((x, y)))
    monkeypatch.setattr(
        probe.ga, "click_client", lambda _hwnd, x, y, **_kw: mouse.clicks.append((x, y))
    )
    monkeypatch.setattr(probe.ga, "kill_game", _kill_game)
    monkeypatch.setattr(probe.ga, "_process_pids", lambda *_a, **_kw: [])
    monkeypatch.setattr(probe.ga, "quarantine_logs", lambda *_a, **_kw: [])
    monkeypatch.setattr(probe.experiments, "restore_content_load", _restore_content_load)
    # `run()` 会把 `ga.ALLOW_REAL_INPUT` 设成 True 且自己不还原 ⇒ 登记一次值变，
    # 让 monkeypatch 在收尾时把模块级全局还原回去（别把实机开关留给别的用例）。
    monkeypatch.setattr(probe.ga, "ALLOW_REAL_INPUT", False)

    def 跑(
        *,
        frame: Callable[[int], Image.Image] = _frame,
        arrow_steps: bool = True,
        constants: dict[str, object] | None = None,
    ) -> SimpleNamespace:
        """走一遍 `run()`；自检不过时驱动会**抛**，这里接住它（用例要看得到异常，不能让整轮崩掉）。"""
        for name, value in (constants or {}).items():
            monkeypatch.setattr(probe, name, value)
        feed = _FrameFeed(frame)
        monkeypatch.setattr(probe.ga, "screenshot", feed)
        argv = ["--evidence", str(root), "--recon", "--scrolls", "1"]
        if arrow_steps:
            argv.append("--row-arrows")
        record = SimpleNamespace(
            code=None,
            error=None,
            shot_dir_before=probe.ga.SHOT_DIR,
            shot_dir_after=None,
        )
        try:
            record.code = probe.run(probe.build_parser().parse_args(argv))
        except Exception as exc:  # 自检不过 ⇒ 驱动**抛**（这是设计：不许静默按估计坐标点）
            record.error = exc
        record.shot_dir_after = probe.ga.SHOT_DIR
        record.clicks = list(mouse.clicks)
        record.cursor = list(mouse.cursor)
        record.frames = feed.calls
        record.pass_dirs = sorted(p for p in root.iterdir() if p.is_dir())
        record.summaries = sorted(root.rglob("stage6-ui-*.md"))
        record.root = root
        record.flat = flat
        record.flat_before = flat_before
        return record

    return SimpleNamespace(
        跑=跑,
        root=root,
        flat=flat,
        flat_before=flat_before,
        mouse=mouse,
        teardown=teardown,
        state_script=state_script,
    )


# ── 判据（单元级：内嵌合成帧）────────────────────────────────────────────────────


def test_两枚箭头都在_自检放行_且点击点来自实测像框中心(probe: ModuleType) -> None:
    prev, next_ = probe.require_row_arrows(_frame(), row_center_y=_ROW_CENTER_Y)
    assert prev.amber == 125
    assert next_.amber == 125
    assert (prev.x0, prev.x1) == (_PREV_X0, _PREV_X0 + 10)
    assert (next_.x0, next_.x1) == (_NEXT_X0, _NEXT_X0 + 10)
    # 点击点 = **实测像框的水平中心**（B118 的 1011 / 1348 就是这么来的，不是估计坐标）
    assert prev.x == probe.ROW_ARROW_PREV_X
    assert next_.x == probe.ROW_ARROW_NEXT_X
    assert prev.profile == _PROFILE
    assert next_.profile == tuple(reversed(_PROFILE))
    assert probe.row_arrow_assert_mirror(prev.profile, next_.profile) is True


@pytest.mark.parametrize(
    ("label", "make_frame"),
    [
        ("◀（ROW_ARROW_PREV_X）", _frame_without_prev),
        ("▶（ROW_ARROW_NEXT_X）", _frame_without_next),
    ],
)
def test_只有一个_就拦_且消息点名缺的是哪一支(
    probe: ModuleType, label: str, make_frame: Callable[[], Image.Image]
) -> None:
    with pytest.raises(probe.RowArrowCheckError) as caught:
        probe.require_row_arrows(make_frame(), row_center_y=_ROW_CENTER_Y)
    assert caught.value.reason == "没找到箭头"
    text = str(caught.value)
    assert label in text  # **点名缺的是哪一支**（reason 是粗分类，点在文本里）
    assert "窗内琥珀 0 像素" in text  # 缺的那一支：实测 0（与"没量"分得开）
    assert "琥珀 125 像素" in text  # 还在的那一支：**实测计数**在消息里
    assert "一个鼠标键也没送出去" in text


def test_一个都没有_就拦_且两处各自点名(probe: ModuleType) -> None:
    image = _frame(prev_profile=None, next_profile=None)
    with pytest.raises(probe.RowArrowCheckError) as caught:
        probe.require_row_arrows(image, row_center_y=_ROW_CENTER_Y)
    assert caught.value.reason == "没找到箭头"
    text = str(caught.value)
    assert "缺 ◀（ROW_ARROW_PREV_X）、▶（ROW_ARROW_NEXT_X）" in text
    assert text.count("窗内琥珀 0 像素") == 2
    assert text.count("这一个 x 上没有") == 2
    # 两侧窗外都没有琥珀 ⇒ **不许**下"这一屏没有箭头"的结论（只下得了"这些 x 上没有"）
    assert "一个琥珀像素都没有" in text
    assert "位置写偏了" not in text


def test_形状不镜像_镜像那一条在出力(probe: ModuleType) -> None:
    image = _frame_unmirrored()
    # 阴性对照的对照：**最小判据**（只看有没有琥珀、两头方向对不对）在这张图上仍然是 True
    assert probe.row_arrow_probe_minimal(_PROFILE, _PROFILE_UNMIRRORED) is True
    # ⇒ 拦住它的只能是**镜像**那一条（不是计数、也不是"缺一支"）
    with pytest.raises(probe.RowArrowCheckError) as caught:
        probe.require_row_arrows(image, row_center_y=_ROW_CENTER_Y)
    assert caught.value.reason == "镜像不过"
    assert "不互成镜像" in str(caught.value)


def test_失败文本自带x区间_行带y_与实测像素计数(probe: ModuleType) -> None:
    """不看代码就能判「是没找到，还是找错了位置」—— 靠的就是这三样东西都在消息里。"""
    with pytest.raises(probe.RowArrowCheckError) as caught:
        probe.require_row_arrows(_frame_without_next(), row_center_y=_ROW_CENTER_Y)
    text = str(caught.value)
    assert "行带 y 727–757" in text  # 行心 742 ± ROW_ARROW_DY_HALF(15)
    assert "行心 y=742" in text
    assert "◀ 1000–1022" in text  # ROW_ARROW_PREV_X(1011) ± ROW_ARROW_X_HALF(11)
    assert "▶ 1337–1359" in text  # ROW_ARROW_NEXT_X(1348) ± 11
    assert "ROW_ARROW_PREV_X`=1011" in text
    assert "琥珀 125 像素" in text  # 在的那一支：**实测**计数
    assert "窗内琥珀 0 像素" in text  # 缺的那一支：**实测** 0
    assert "一个鼠标键也没送出去" in text


def test_坐标整体写偏20像素_文本指出位置写偏了(probe: ModuleType) -> None:
    image = _frame(prev_x0=_PREV_X0 + 20, next_x0=_NEXT_X0 + 20)
    with pytest.raises(probe.RowArrowCheckError) as caught:
        probe.require_row_arrows(image, row_center_y=_ROW_CENTER_Y)
    text = str(caught.value)
    assert text.count("位置写偏了") == 2  # **每一侧各自归因**，不是一句汇总
    assert "x 1026–1036" in text  # ±40 px 内的最近游程 = 真实像框（1006+20 … 1016+20）
    assert "x 1363–1373" in text  # ▶ 侧同理（1343+20 … 1353+20）
    assert "改 `ROW_ARROW_*` 常量" in text  # 指向**常量**，不是让人改判据


def test_自检真的读常量_把ROW_ARROW_PREV_X改错就当场转红(
    probe: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """常数"值相等"不算数：**改错常量必须当场改判**（B118 的病根是常量对、仪器读别处）。

    若 `require_row_arrows` 把 `ROW_ARROW_PREV_X` 写成值默认值（`def` 时绑死），这里就**不会抛**，
    本用例转红 —— 这就是「真的读常量」的判据本身。
    """
    image = _frame()
    assert probe.require_row_arrows(image, row_center_y=_ROW_CENTER_Y)  # 未改前：放行
    monkeypatch.setattr(probe, "ROW_ARROW_PREV_X", 900)
    with pytest.raises(probe.RowArrowCheckError) as caught:
        probe.require_row_arrows(image, row_center_y=_ROW_CENTER_Y)
    text = str(caught.value)
    assert caught.value.reason == "没找到箭头"
    assert "缺 ◀（ROW_ARROW_PREV_X）" in text
    assert "900" in text  # 改后的值真的进了消息（说明读的就是这个常量）
    assert "ROW_ARROW_PREV_X`=900" in text


def test_自检不过_一个鼠标键也不送出去(probe: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    cursor: list[tuple[int, int]] = []
    clicks: list[tuple[int, int]] = []
    monkeypatch.setattr(probe.ga, "_set_cursor", lambda x, y: cursor.append((x, y)))
    monkeypatch.setattr(probe.ga, "click_client", lambda _h, x, y, **_kw: clicks.append((x, y)))

    def _boom(_hwnd: int = 0, roi: object = None) -> Image.Image:
        raise probe.ga.CaptureFailedError("（用例）抓不到图")

    # 中性重抓在无窗口的用例里必然失败 ⇒ 走的是「退回手里那一帧」那条路（更严的一侧，不抛）
    monkeypatch.setattr(probe.ga, "screenshot", _boom)
    cases = [
        (_frame_without_prev(), "没找到箭头", "缺 ◀（ROW_ARROW_PREV_X）"),
        (_frame_without_next(), "没找到箭头", "缺 ▶（ROW_ARROW_NEXT_X）"),
        (
            _frame(prev_profile=None, next_profile=None),
            "没找到箭头",
            "缺 ◀（ROW_ARROW_PREV_X）、▶（ROW_ARROW_NEXT_X）",
        ),
        (_frame_unmirrored(), "镜像不过", "不互成镜像"),
        (None, "抓不到图", "没有帧，量不到"),
    ]
    for image, reason, needle in cases:
        with pytest.raises(probe.RowArrowCheckError) as caught:
            probe.click_row_arrow(4242, which="next", image=image, row_center_y=_ROW_CENTER_Y)
        # 三种分类必须分得开：动作不同（查坐标 / 查形状 / 修抓图）
        assert caught.value.reason == reason
        assert needle in str(caught.value)
    # 承重那一条：**一个鼠标键也没送出去**（四条"自检不过"的路径一条都不例外）
    assert clicks == []
    # t41 的修因改变了"光标也没挪"这一条：自检**之前**要先挪到中性点（解悬停 —— 光标压在箭头
    # 上时悬停高亮会把剪影多照亮一列，镜像是从"真不一致"变成"假红"）。允许挪光标，但**只许
    # 挪到中性点**；`image=None` 那一条连抓图都没走 ⇒ 只挪了 4 次。
    assert cursor == [probe.NEUTRAL_CURSOR_XY] * 4
    # 反向对照：放行那一次**确实点了**，点的是自检量出来的中心 ⇒ 上面那两条不是"永远不点"的空断言
    spot = probe.click_row_arrow(4242, which="next", image=_frame(), row_center_y=_ROW_CENTER_Y)
    assert spot.x == probe.ROW_ARROW_NEXT_X
    assert clicks == [(probe.ROW_ARROW_NEXT_X, _ROW_CENTER_Y)]
    assert cursor[4:] == [probe.NEUTRAL_CURSOR_XY, (probe.ROW_ARROW_NEXT_X, _ROW_CENTER_Y)]


def test_抓不到图也拦_且文本说明量不到(probe: ModuleType) -> None:
    with pytest.raises(probe.RowArrowCheckError) as caught:
        probe.click_row_arrow(4242, which="prev", image=None, row_center_y=_ROW_CENTER_Y)
    assert caught.value.reason == "抓不到图"
    text = str(caught.value)
    assert "行带 y 727–757" in text
    assert "没有帧，量不到" in text  # 没有帧就没有读数 —— 如实说，别假装量过
    assert "不许" in text  # 明说：不许改用估计坐标点


def test_which只认prev与next(probe: ModuleType) -> None:
    with pytest.raises(ValueError, match="prev"):
        probe.click_row_arrow(4242, which="up", image=_frame(), row_center_y=_ROW_CENTER_Y)


# ── 形状/大小判据（t24 修 F1：平剖面的镜像**恒真** ⇒ 退化形状以前全放行）──────────────
# 现场：`t8` 的形状动物园（`%TEMP%\t8-verify\shapezoo_t8.py`）54 格「两侧对称的退化形状」
# **全绿穿过去**。病根不在颜色判据、也不在镜像判据，而在**没人判形状**：两窗都是平剖面时，
# 逐列相等是免费的。下面这张表就是把那个动物园搬进仓库当**回归夹具**（纯合成帧、不碰
# `tools/out/**`、进程内），并把它做不到的四件事补齐：
#   ① 表外尺寸（rect 11×24 / 16×20、triangle 3×6）也给出红/绿结论，不许「没测」；
#   ② 逐格**理由**（每条红都点名是哪一项界不过）；
#   ③ 「形状不符」与「窗内琥珀不足」在文本里分得开；
#   ④ 界**真的被读**（改界必须当场改判，同 `ROW_ARROW_PREV_X` 那条用例的道理）。


def _draw_columns(draw: ImageDraw.ImageDraw, *, x0: int, y: int, heights: tuple[int, ...]) -> None:
    """逐列画矩形（**高度 0 = 这一列不画**）。

    不复用 `_arrow`：那里对高度 0 会画 `(x, y, x, y-1)`，PIL 把倒序坐标**归一化成一条线** ——
    于是"断续"样本就不断续了，测的就不是想测的东西。
    """
    for offset, height in enumerate(heights):
        if height <= 0:
            continue
        half = height // 2
        draw.rectangle((x0 + offset, y - half, x0 + offset, y - half + height - 1), fill=_AMBER)


def _frame_columns(prev_heights: tuple[int, ...]) -> Image.Image:
    """只有两处哨兵窗里有琥珀：左边逐列按 `prev_heights` 画，右边**取倒序**（＝镜像）。

    倒序就是镜像：每列都垂直居中在行心，所以「列高的序列反过来」＝「沿垂直轴翻面」。
    这样造出来的样本**镜像那一条必过** ⇒ 拦得住它的一定只能是形状判据（阴性对照有牙）。
    """
    image = Image.new("RGB", _SIZE, _BASE)
    draw = ImageDraw.Draw(image)
    _draw_columns(draw, x0=_PREV_X0, y=_ROW_CENTER_Y, heights=prev_heights)
    _draw_columns(draw, x0=_NEXT_X0, y=_ROW_CENTER_Y, heights=tuple(reversed(prev_heights)))
    return image


def _frame_flat_window() -> Image.Image:
    """整窗平色：两处哨兵窗（22×30）**全是**琥珀 —— 剖面是常数 ⇒ 镜像恒真。

    几何照抄实测：`tools/out/auto/bg-click-判定后.png` 的 y 738–793 就是「22 个 30 的平色」，
    修复前它**放行**（t8 的读数）。
    """
    image = Image.new("RGB", _SIZE, _BASE)
    draw = ImageDraw.Draw(image)
    for centre in (_PREV_X, _NEXT_X):
        draw.rectangle(
            (centre - 11, _ROW_CENTER_Y - 15, centre + 10, _ROW_CENTER_Y + 14), fill=_AMBER
        )
    return image


def _strip(width: int) -> tuple[int, ...]:
    """竖条：每列都是满高 20。"""
    return (20,) * width


def _rect(width: int, height: int) -> tuple[int, ...]:
    """等宽矩形：每列等高。"""
    return (height,) * width


def _triangle(width: int, height: int) -> tuple[int, ...]:
    """单调三角（尖端在右）—— 与真箭头同族：逐列高度线性递增。"""
    return tuple(max(1, round(height * (i + 1) / width)) for i in range(width))


def _dash(width: int, height: int) -> tuple[int, ...]:
    """断续：偶数列传、奇数列不传（剖面中间有 0 列）。"""
    return tuple(height if i % 2 == 0 else 0 for i in range(width))


def _zigzag(width: int, height: int) -> tuple[int, ...]:
    """锯齿：高度高矮交替（跨度不小、但**不单调** ⇒ 只有单调那一条拦得住）。"""
    return tuple(max(1, height // 2 if i % 2 else height) for i in range(width))


#: 退化形状族：**必须全红**（形状/大小不符），且两侧互为镜像 ⇒ 镜像那一条不背这个锅。
_ZOO_DEGENERATE: list[tuple[str, tuple[int, ...]]] = [
    *((f"竖条 strip {w}×20", _strip(w)) for w in (1, 2, 3, 5, 7, 9, 11, 13, 15, 17, 20)),
    *((f"等宽矩形 rect 11×{h}", _rect(11, h)) for h in (2, 3, 5, 8, 10, 15, 20, 24, 26, 30)),
    *((f"等宽矩形 rect {w}×{h}", _rect(w, h)) for w in (5, 7, 9, 13, 16, 20) for h in (8, 20, 30)),
    ("表外 rect 11×24（尺寸落在界内、剖面平）", _rect(11, 24)),
    ("表外 rect 16×20（同上）", _rect(16, 20)),
    *((f"断续 dash {w}×20", _dash(w, 20)) for w in (9, 11, 15)),
    *((f"锯齿 zigzag {w}×20", _zigzag(w, 20)) for w in (9, 11, 15)),
]

#: 单调三角的缩放：**同比**的仍要放行（免得实机误拒），明显出尺寸界/比例界的按界拒。
_ZOO_TRIANGLE: list[tuple[str, tuple[int, ...], bool]] = [
    ("triangle 3×6（宽 3 < 5、高 6 < 10 ⇒ 出界）", _triangle(3, 6), False),
    ("triangle 5×10（真箭头同比 50% ⇒ 界内）", _triangle(5, 10), True),
    ("triangle 7×14（同比 64% ⇒ 界内）", _triangle(7, 14), True),
    ("triangle 11×20（真箭头尺寸 ⇒ 放行）", _triangle(11, 20), True),
    ("triangle 13×24（同比 120% ⇒ 界内）", _triangle(13, 24), True),
    ("triangle 16×30（高 30 > 界 26：填满窗 ⇒ 不是行带里那枚控件）", _triangle(16, 30), False),
    ("triangle 20×30（宽 20 > 界 16 ⇒ 出界）", _triangle(20, 30), False),
]


@pytest.mark.parametrize(
    ("label", "heights"), _ZOO_DEGENERATE, ids=[label for label, _ in _ZOO_DEGENERATE]
)
def test_退化形状族一律拒_平剖面骗不过形状判据(
    probe: ModuleType, label: str, heights: tuple[int, ...]
) -> None:
    """这张表就是 t8 那份形状动物园的回归版：**每一格都必须红**，且红的理由是形状/大小。"""
    with pytest.raises(probe.RowArrowCheckError) as caught:
        probe.require_row_arrows(_frame_columns(heights), row_center_y=_ROW_CENTER_Y)
    assert caught.value.reason == "形状不符", label
    text = str(caught.value)
    assert "形状/大小不符" in text, label
    assert "实测 宽" in text, label  # 理由里带**实测**（不是一句"不合格"）
    assert "界：宽" in text, label


def test_整窗平色也拒_两窗剖面都是常数(probe: ModuleType) -> None:
    """实测那条 22×30 的平色带（`bg-click-判定后.png` y 738–793）：修复前放行，现在必须拒。"""
    with pytest.raises(probe.RowArrowCheckError) as caught:
        probe.require_row_arrows(_frame_flat_window(), row_center_y=_ROW_CENTER_Y)
    assert caught.value.reason == "形状不符"
    text = str(caught.value)
    assert "剖面跨度 0" in text
    assert "宽 22 不在 5–16" in text
    assert "高 30 不在 10–26" in text


@pytest.mark.parametrize(
    ("label", "heights", "expect_green"),
    _ZOO_TRIANGLE,
    ids=[label for label, _, _ in _ZOO_TRIANGLE],
)
def test_单调三角缩放_同比的放行_明显出界的拒(
    probe: ModuleType, label: str, heights: tuple[int, ...], expect_green: bool
) -> None:
    """真箭头是**单调三角**：同比缩放（5×10 … 13×24）一律放行 —— 界必须留够余量。

    出界的两个（16×30 / 20×30）拒的理由是**尺寸**：高 30 填满整窗（行带只有 21 行、真控件 20 行）、
    宽 20 超出 22 列窗的余量 —— 界写在 :data:`ROW_ARROW_WIDTH_MAX` 那一段注释里，可复算。
    """
    image = _frame_columns(heights)
    if expect_green:
        prev, next_ = probe.require_row_arrows(image, row_center_y=_ROW_CENTER_Y)
        assert probe.row_arrow_assert_mirror(prev.profile, next_.profile) is True, label
    else:
        with pytest.raises(probe.RowArrowCheckError) as caught:
            probe.require_row_arrows(image, row_center_y=_ROW_CENTER_Y)
        assert caught.value.reason == "形状不符", label


def test_真箭头帧的现读剖面放行_与实测同值(probe: ModuleType) -> None:
    """`22-rule-sitai.png` 的**现读**剖面（§3.10 / t8 复核）：11 列、高 20、和 125。"""
    real = (3, 4, 6, 8, 9, 11, 13, 15, 17, 19, 20)
    assert sum(real) == 125  # 与 §3.10 的「琥珀 125 像素」同值（样本没走样）
    prev, next_ = probe.require_row_arrows(_frame_columns(real), row_center_y=_ROW_CENTER_Y)
    assert prev.amber == 125
    assert (prev.width, prev.height) == (11, 20)
    assert next_.profile == tuple(reversed(real))


def test_形状不符与窗内琥珀不足_两件动作不同的事在文本里分得开(probe: ModuleType) -> None:
    """不看代码也能判「该去修坐标」还是「该去修形状」—— 两边的**理由**必须不同。"""
    with pytest.raises(probe.RowArrowCheckError) as shape_case:
        probe.require_row_arrows(_frame_columns(_rect(11, 20)), row_center_y=_ROW_CENTER_Y)
    shape_text = str(shape_case.value)
    assert shape_case.value.reason == "形状不符"
    assert "形状/大小不符" in shape_text
    assert "剖面跨度 0" in shape_text  # 实测读数在
    assert "窗内琥珀 0 像素" not in shape_text  # 不是"没找到"
    assert "一个鼠标键也没送出去" in shape_text

    with pytest.raises(probe.RowArrowCheckError) as missing_case:
        probe.require_row_arrows(_frame_without_next(), row_center_y=_ROW_CENTER_Y)
    missing_text = str(missing_case.value)
    assert missing_case.value.reason == "没找到箭头"
    assert "窗内琥珀 0 像素" in missing_text
    assert "形状/大小不符" not in missing_text


def test_形状界真的读常量_把宽界改小就当场转红(
    probe: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """界的**值相等**不算数：改界必须当场改判（同 `test_自检真的读常量` 的道理，B118）。"""
    image = _frame()  # 真尺寸：宽 11
    assert probe.require_row_arrows(image, row_center_y=_ROW_CENTER_Y)  # 未改前：放行
    monkeypatch.setattr(probe, "ROW_ARROW_WIDTH_MAX", 10)
    with pytest.raises(probe.RowArrowCheckError) as caught:
        probe.require_row_arrows(image, row_center_y=_ROW_CENTER_Y)
    assert caught.value.reason == "形状不符"
    text = str(caught.value)
    assert "宽 11 不在 5–10" in text  # 改后的界**真的进了判据与消息**
    assert "界：宽 5–10" in text


def test_界把真箭头包住且留够余量_免得实机误拒(probe: ModuleType) -> None:
    """界的**定位**也是判据的一部分：真值 11×20（比 0.55）必须严格在界内、两侧都有余量。"""
    assert probe.ROW_ARROW_WIDTH_MIN <= 11 - 4  # 真值左侧余量 ≥ 4 px
    assert probe.ROW_ARROW_WIDTH_MAX >= 11 + 4  # 右侧同理
    assert probe.ROW_ARROW_HEIGHT_MIN <= 20 - 4
    assert probe.ROW_ARROW_HEIGHT_MAX >= 20 + 4
    assert probe.ROW_ARROW_ASPECT_MIN < 11 / 20 < probe.ROW_ARROW_ASPECT_MAX
    # 真箭头剖面的跨度（20 − 3 = 17）必须**远**高于"不是平剖面"的门槛
    assert 4 * probe.ROW_ARROW_PROFILE_SPREAD_MIN <= 20 - 3
    # 填充（t24/amend 2）：空心轮廓 30/(11×20) = 0.136 与真箭头 125/220 = 0.568 各自离下界 ≥0.15
    assert probe.ROW_ARROW_FILL_MIN - 30 / (11 * 20) >= 0.15  # 空心侧余量
    assert 125 / (11 * 20) - probe.ROW_ARROW_FILL_MIN >= 0.15  # 真箭头侧余量


# ── t24/amend 1：剖面口径与几何口径必须一致（真箭头 + 窗里另有一小块琥珀）──────────────
# 现场（验证员第二批预跑的复现）：真箭头**完整**在窗内、窗里另有一小块琥珀（隔一列空白）时，
# 旧口径的剖面取**整窗**（22×30）⇒ 冒出中间 0 列 ⇒ 判红 `形状不符`，而失败文本还说成
# 「窗里有琥珀但不像那枚控件」—— 把话说反了（像的**就是**它，是读数取错了地方）。
# 4 连通域的外接框内部不可能出现整列为空的列，所以剖面限到 `clusters[0]` 的框内即可：
# 与几何取同一个东西。旁路琥珀如实写进 `RowArrowProbe.aside` 当说明，**不进判据**。


def _frame_arrow_plus_stray() -> Image.Image:
    """真箭头（两窗、互镜像）+ **同一哨兵窗里**另有一小块琥珀（t24/amend 1 的复现样本）。

    旁路块在自己的 x 段（1018–1021、4×4 = 16 px）、与箭头（1006–1016）之间隔着空白列 1017
    ⇒ 4 连通上**不是**一回事，但仍在同一哨兵窗（1000–1021）里。这正是实机的常态：窗不是
    "只有那枚控件"的净土（颜色判据不特异，窗里随时会有别的东西发琥珀光）。
    """
    image = _frame()  # 真箭头：左 1006–1016、右 1343–1353（右窗取镜像）
    draw = ImageDraw.Draw(image)
    draw.rectangle((1018, _ROW_CENTER_Y + 2, 1021, _ROW_CENTER_Y + 5), fill=_AMBER)
    return image


def test_真箭头旁另有小块琥珀_放行_且旧口径的整窗剖面确实会误判(probe: ModuleType) -> None:
    """同一帧上钉两件相反的事：**新口径放行**、**旧口径的那份读数确实是红的**。

    只钉前者就是"自证放行"：说不出修的到底是不是那个病。所以②要用**同一帧**、按旧口径
    （整窗剖面）造一个 `RowArrowSpot`、走**同一个** `row_arrow_shape_faults` —— 它必须红，
    而且红的理由正是"剖面中间夹着 0 列"。
    """
    image = _frame_arrow_plus_stray()
    prev, next_ = probe.require_row_arrows(image, row_center_y=_ROW_CENTER_Y)
    assert (prev.width, prev.height, prev.amber) == (11, 20, 125)
    assert prev.profile == _PROFILE  # 旁路琥珀**没进**这枚箭头的剖面
    assert next_.profile == tuple(reversed(_PROFILE))
    assert prev.x == _PREV_X  # 点击点仍是那枚箭头的中心（旁路块没把像框中心带偏）
    assert prev.x1 == _PREV_X0 + 10  # 外接框只包那枚箭头（到 1016），不含旁路块
    # 旁路琥珀**如实报**（阴性也要有读数），但只是说明：
    assert (
        "另有 1 处琥珀"
        in probe.row_arrow_spot(
            image, label="◀（ROW_ARROW_PREV_X）", x=_PREV_X, y=_ROW_CENTER_Y
        ).aside
    )
    # 旧口径：同一帧、整窗 22×30 的剖面
    x0, y0, x1, y1 = probe.row_arrow_crop_box(x=_PREV_X, y=_ROW_CENTER_Y)
    whole = probe._trim_zeros(probe._column_profile(probe.amber_mask(image.crop((x0, y0, x1, y1)))))
    assert 0 in whole  # ← 旧口径在这张样本上**真的**会看到"中间 0 列"
    assert 0 not in prev.profile  # ← 新口径看不到（同一个东西的两种取法）
    old_spot = probe.RowArrowSpot(
        label="旧口径（整窗剖面）",
        x=prev.x,
        x0=prev.x0,
        x1=prev.x1,
        amber=prev.amber,
        width=prev.width,
        height=prev.height,
        profile=whole,
    )
    old_faults = probe.row_arrow_shape_faults(old_spot)
    assert any("中间夹着 0 列" in fault for fault in old_faults), old_faults


# ── t24/amend 2：填充/密度下界（空心轮廓——宽高比跨度单调全合规，只有它拦得住）─────────


def _outline(
    draw: ImageDraw.ImageDraw, *, x0: int, y: int, width: int, height: int, mirrored: bool
) -> None:
    """1 px **空心**轮廓：一条竖直边（左／右）+ 一条底边，**框内全空**（t24/amend 2 的样本）。"""
    top = y - height // 2
    bottom = top + height - 1
    spine = x0 + width - 1 if mirrored else x0  # 竖边在哪一侧
    far = x0 if mirrored else x0 + width - 1
    draw.rectangle((spine, top, spine, bottom), fill=_AMBER)
    draw.rectangle((min(spine, far), bottom, max(spine, far), bottom), fill=_AMBER)


def _frame_hollow_outline() -> Image.Image:
    """两窗各一个 **1 px 空心轮廓**（11×20，右窗取镜像）⇒ 除了**填充**，所有旧界都合规。

    逐列高度 = `20,1,1,…,1`（竖边 20 + 底边 1）：跨度 19、单调不增、没有中间 0 列、比 0.55、
    宽高都在界内 —— 旧判据**全放行**（这正是 t8 第二批预跑抓到的洞）。
    """
    image = Image.new("RGB", _SIZE, _BASE)
    draw = ImageDraw.Draw(image)
    _outline(draw, x0=_PREV_X0, y=_ROW_CENTER_Y, width=11, height=20, mirrored=False)
    _outline(draw, x0=_NEXT_X0, y=_ROW_CENTER_Y, width=11, height=20, mirrored=True)
    return image


def _frame_symmetric_hollow() -> Image.Image:
    """**对称**空心（U 形：左右竖边 + 底边）—— 剖面 `20,1,…,1,20` ⇒ 单调性先就拦住。"""
    image = Image.new("RGB", _SIZE, _BASE)
    draw = ImageDraw.Draw(image)
    for x0 in (_PREV_X0, _NEXT_X0):
        _outline(draw, x0=x0, y=_ROW_CENTER_Y, width=11, height=20, mirrored=False)
        _outline(draw, x0=x0, y=_ROW_CENTER_Y, width=11, height=20, mirrored=True)
    return image


def test_空心轮廓_旧界全合规_只有填充下界拦得住(
    probe: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """t24/amend 2 的三步证据：**逐项读数 ⇒ 只有填充一条红 ⇒ 放宽它就放行**。"""
    image = _frame_hollow_outline()
    left = probe.row_arrow_spot(image, label="◀（ROW_ARROW_PREV_X）", x=_PREV_X, y=_ROW_CENTER_Y)
    assert left.spot is not None
    spot = left.spot
    assert (spot.width, spot.height, spot.amber) == (11, 20, 30)  # 30 px / 220 = 0.136
    assert spot.profile == (20, *(1,) * 10)  # 竖边 20 + 底边 1
    faults = probe.row_arrow_shape_faults(spot)
    assert len(faults) == 1, faults  # ← 「只有一条」是逐项钉住的
    assert "填充 30/11×20 = 0.136" in faults[0]
    with pytest.raises(probe.RowArrowCheckError) as caught:
        probe.require_row_arrows(image, row_center_y=_ROW_CENTER_Y)
    assert caught.value.reason == "形状不符"
    text = str(caught.value)
    assert "填充 30/11×20 = 0.136" in text
    assert "空心描边" in text
    assert "一个鼠标键也没送出去" in text
    # 把填充下界放宽 ⇒ **整条自检放行**：拦住它的确实只有这一条（别的界都没挡）
    monkeypatch.setattr(probe, "ROW_ARROW_FILL_MIN", 0.0)
    prev, next_ = probe.require_row_arrows(image, row_center_y=_ROW_CENTER_Y)
    assert probe.row_arrow_assert_mirror(prev.profile, next_.profile) is True


def test_填充下界真的读常量_改成0点95真箭头当场转红(
    probe: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """界的**值相等**不算数：改 `ROW_ARROW_FILL_MIN` 必须当场改判（同宽界那条，B118）。"""
    image = _frame()  # 真箭头：125/(11×20) = 0.568
    prev, _ = probe.require_row_arrows(image, row_center_y=_ROW_CENTER_Y)  # 未改前：放行
    assert prev.amber == 125
    monkeypatch.setattr(probe, "ROW_ARROW_FILL_MIN", 0.95)
    with pytest.raises(probe.RowArrowCheckError) as caught:
        probe.require_row_arrows(image, row_center_y=_ROW_CENTER_Y)
    assert caught.value.reason == "形状不符"
    text = str(caught.value)
    assert "填充 125/11×20 = 0.568 < 0.95" in text  # 改后的界**真的进了判据与消息**
    assert "填充 ≥0.95" in text


def test_对称空心_单调与填充两条都点名(probe: ModuleType) -> None:
    """U 形空心：**两条**独立的界都能拦住它（单调性 + 填充），不是靠单点侥幸。"""
    image = _frame_symmetric_hollow()
    with pytest.raises(probe.RowArrowCheckError) as caught:
        probe.require_row_arrows(image, row_center_y=_ROW_CENTER_Y)
    assert caught.value.reason == "形状不符"
    assert "剖面既不单调增也不单调减" in str(caught.value)
    spot = probe.row_arrow_spot(image, label="◀（ROW_ARROW_PREV_X）", x=_PREV_X, y=_ROW_CENTER_Y)
    assert spot.spot is not None
    faults = probe.row_arrow_shape_faults(spot.spot)
    assert any("填充" in fault for fault in faults), faults
    assert any("单调" in fault for fault in faults), faults


# ── 落帧按遍归档（B114）──────────────────────────────────────────────────────────


def test_落帧目录按遍分配_同名顺位不互相覆盖_且既有扁平证据一个字节没动(
    probe: ModuleType, tmp_path: Path
) -> None:
    root = tmp_path / "auto"
    root.mkdir()
    flat = root / "19-main-menu.png"
    Image.new("RGB", (4, 4), _BASE).save(flat)
    flat_before = flat.read_bytes()

    pid = "pass-20260925-081500-harsh"
    first = probe.pass_dir(root, pid)
    second = probe.pass_dir(root, pid)  # 同一秒又起一遍 ⇒ **撞名**（pass-id 粒度就是秒）
    assert first.name == pid
    assert second.name == f"{pid}-2"
    assert first != second

    _frame().save(first / "19-main-menu.png")
    first_bytes = (first / "19-main-menu.png").read_bytes()
    _frame(prev_profile=None).save(second / "19-main-menu.png")
    assert (second / "19-main-menu.png").read_bytes() != first_bytes
    # 后一遍**没碰**前一遍的帧；根目录里既有的扁平证据也没被删改
    assert (first / "19-main-menu.png").read_bytes() == first_bytes
    assert flat.read_bytes() == flat_before
    assert flat.is_file()
    assert {p.name for p in root.iterdir()} >= {flat.name, first.name, second.name}


def test_pass_id自带时间戳与tier_且是合法目录名(probe: ModuleType) -> None:
    name = probe.pass_dir_name("harsh")
    assert name.startswith("pass-")
    assert name.endswith("-harsh")
    assert ":" not in name  # Windows 目录名不许有冒号（写 %H:%M:%S 就会踩）
    stamp = probe.pass_dir_name("harsh", now=datetime(2026, 9, 25, 8, 15, 0, tzinfo=UTC))
    assert stamp == "pass-20260925-081500-harsh"
    # 时间戳进名字的理由：**同一 tier 的两遍不许撞名**（撞名＝后一遍覆盖前一遍）
    later = probe.pass_dir_name("harsh", now=datetime(2026, 9, 25, 8, 15, 1, tzinfo=UTC))
    assert later != stamp
    assert probe.pass_dir_name("harsh") != probe.pass_dir_name("norm")  # tier 也在名字里


# ── 驱动级：`run()` 真的走这两条路（替身不碰实机）────────────────────────────────


def test_驱动一遍_箭头都在就点_帧落进这一遍的子目录(driver: SimpleNamespace) -> None:
    record = driver.跑()
    assert record.error is None
    assert record.code == 0
    # 点的是**自检量出来的**像框中心（§3.10 现读 1011 / 1348），y 是 L7 命中 y 694 + 48
    assert record.clicks.count((1011, _ROW_CENTER_Y)) == 1
    assert record.clicks.count((1348, _ROW_CENTER_Y)) == 1
    assert record.cursor.count((1011, _ROW_CENTER_Y)) == 1
    # 落帧进了**这一遍**的子目录（不是根目录），摘要也在同一遍里
    assert len(record.pass_dirs) == 1
    one = record.pass_dirs[0]
    assert one.name.startswith("pass-")
    for name in (
        "19-main-menu.png",
        "22-rule-sitai.png",
        "26-tier-prev-candidate.png",
        "27-tier-next-candidate.png",
    ):
        assert (one / name).is_file()
    assert len(record.summaries) == 1
    assert record.summaries[0].parent == one
    # 根目录里既有的扁平帧一个字节没动
    assert record.flat.read_bytes() == record.flat_before
    # 收尾把落帧目录还原了（`ga.SHOT_DIR` 是模块级全局，不许留给下一遍）
    assert record.shot_dir_after == record.shot_dir_before


def test_驱动一遍_同一秒跑两遍_两个pass目录各自留帧不互相覆盖(driver: SimpleNamespace) -> None:
    first = driver.跑()
    assert first.error is None
    assert len(first.pass_dirs) == 1
    one = first.pass_dirs[0]
    first_frame = (one / "19-main-menu.png").read_bytes()
    # 第二遍：帧的 marker 整体挪一档 ⇒ 两遍的帧**内容不同**（这样"没覆盖"才是可判的）
    second = driver.跑(frame=lambda marker: _frame(marker + 40))
    assert second.error is None
    assert len(second.pass_dirs) == 2
    assert one in second.pass_dirs
    other = next(p for p in second.pass_dirs if p != one)
    assert (other / "19-main-menu.png").read_bytes() != first_frame
    assert (one / "19-main-menu.png").read_bytes() == first_frame  # 后一遍**没碰**前一遍
    assert second.flat.read_bytes() == second.flat_before  # 扁平证据也没碰


def test_驱动一遍_缺一支就停手_且既有收尾三件照走(
    driver: SimpleNamespace, probe: ModuleType
) -> None:
    record = driver.跑(frame=lambda marker: _frame(marker, next_profile=None))
    assert isinstance(record.error, probe.RowArrowCheckError)
    assert record.error.reason == "没找到箭头"
    assert "缺 ▶（ROW_ARROW_NEXT_X）" in str(record.error)
    # 走到过 L5/L6 两次估计点击（说明不是别的东西提前失败，而是**卡在箭头这一步**）
    assert len(record.clicks) == 2
    assert all(y != _ROW_CENTER_Y for _x, y in record.clicks)  # 行带上**一次鼠标键都没送出去**
    # 既有 `finally` 收尾三件照走：落帧目录还原、杀进程、还原 content_load
    assert record.shot_dir_after == record.shot_dir_before
    assert driver.teardown.kill == 1
    assert driver.teardown.restore == 1
    # 失败也留证据：帧仍在**这一遍**的子目录里，失败文本进了摘要
    assert len(record.pass_dirs) == 1
    one = record.pass_dirs[0]
    assert (one / "22-rule-sitai.png").is_file()
    assert len(record.summaries) == 1
    text = record.summaries[0].read_text(encoding="utf-8")
    assert "本步未达成" in text
    assert "缺 ▶（ROW_ARROW_NEXT_X）" in text


def test_驱动一遍的自检真的读常量_把常量改错就当场转红(
    driver: SimpleNamespace, probe: ModuleType
) -> None:
    record = driver.跑(constants={"ROW_ARROW_PREV_X": 900})
    assert isinstance(record.error, probe.RowArrowCheckError)
    assert record.error.reason == "没找到箭头"
    assert "缺 ◀（ROW_ARROW_PREV_X）" in str(record.error)
    assert "ROW_ARROW_PREV_X`=900" in str(record.error)
    assert len(record.clicks) == 2  # 只走到 L5/L6，箭头那一步被自检拦下


# ── t33：轮询语义显式化（抓图失败 ≠ 不命中）─────────────────────────────────────


class _FakeTime:
    """只给「单调钟 + 睡眠」的假时间：睡眠**推进**单调钟 ⇒ 轮询期限可确定性复算。

    其余属性（`strftime` 之类）原样转发给真模块 —— 别的东西照旧用真时间。
    """

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def __getattr__(self, name: str) -> object:
        return getattr(time, name)


def test_驱动里没有一处find_in_roi靠默认值() -> None:
    """**源文件不变量**：驱动里每次 `ga.find_in_roi` 都必须显式写明抓图失败怎么处置。

    t19 之后 `find_in_roi` 抓图失败默认**抛**（看不到 ≠ 没有，P13）。驱动里四处按轮询语义
    用它：三处「手里已经有帧、只是这一轮不算命中」显式传 `"miss"`；L4 启动等待那处（手里
    没有帧）改走三态 `locate_state`。这条不变量**现算源文件** ⇒ 漏写、写错、随重构过期，
    都当场红。
    """
    tree = ast.parse(_PROBE.read_text(encoding="utf-8"))
    bare: list[int] = []
    miss: list[int] = []
    l4: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "ga"
            and func.attr == "find_in_roi"
        ):
            keywords = {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}
            chosen = keywords.get("on_capture_failure")
            if isinstance(chosen, ast.Constant) and chosen.value == "miss":
                miss.append(node.lineno)
            else:
                bare.append(node.lineno)
        elif isinstance(func, ast.Name) and func.id == "locate_state" and len(node.args) >= 2:
            target = node.args[1]
            if isinstance(target, ast.Constant) and target.value == "btn_new_game":
                l4.append(node.lineno)
    assert bare == [], f"这些行还在靠 find_in_roi 的默认值（抓图失败会抛、会中止整局）：{bare}"
    assert len(miss) == 3, f"显式选轮询语义的调用点应恰好 3 处，实为 {miss}"
    assert len(l4) == 1, f"L4 启动等待应恰好走一次三态 locate_state，实为 {l4}"


def test_抓图失败_轮询版继续_非轮询版抛(probe: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """两方向都钉住：同一个抓图失败，**轮询版继续、非轮询版抛**。"""
    roi = (0.0, 0.15, 0.45, 0.95)

    def _boom(_hwnd: int, roi: object = None) -> Image.Image:
        raise probe.ga.CaptureFailedError("抓到的是近乎纯色的画面（加载中 / 最小化 / 抓图失效）")

    monkeypatch.setattr(probe.ga, "screenshot", _boom)
    # ① 轮询版（驱动自带的三态）：**不抛**，单独一态 + 把原因带出来
    state, match, why = probe.locate_state(4242, "btn_new_game", roi=roi)
    assert state == probe.LOOKUP_UNSEEN
    assert match is None
    assert "近乎纯色" in why
    # ② 非轮询版（t19 之后的默认）：**抛**，并点名找什么、在哪找
    with pytest.raises(probe.ga.CaptureFailedError) as caught:
        probe.ga.find_in_roi(4242, "btn_new_game", roi=roi)
    assert "btn_new_game" in str(caught.value)
    assert "近乎纯色" in str(caught.value)
    # ③ 显式退化成「不命中」（驱动那三处的选择）：返回 None，不抛
    assert probe.ga.find_in_roi(4242, "btn_new_game", roi=roi, on_capture_failure="miss") is None


def test_同帧等价_三态路径与显式miss路径逐字相同(
    probe: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """同一帧、同一模板：`locate_state` 与 `find_in_roi(..., "miss")` 读数**逐字相同**。

    为什么要这条：t33 的改造对**成功路径**必须是零行为变化（t26 要在这条驱动上出正式
    证据）。模板与帧都在 `tmp_path` 里现造（本文件不读 `tools/out/**`），于是走的是**真**
    模板加载、真匹配、真 `_roi_offset`/`_shift_match` 位移。
    """
    patch = Image.new("RGB", (96, 30), (24, 26, 30))
    draw = ImageDraw.Draw(patch)
    for col in range(96):
        draw.line((col, 0, col, 29), fill=(30 + col * 2, 60 + (col * 7) % 180, 90))
    draw.rectangle((10, 8, 40, 21), fill=_AMBER)
    patch.save(tmp_path / "rule_row_sitai.png")
    frame = Image.new("RGB", _SIZE, _BASE)
    frame.paste(patch, (600, 300))
    roi = (0.22, 0.06, 0.78, 0.94)
    monkeypatch.setattr(probe.ga, "screenshot", lambda *_a, **_kw: frame)
    monkeypatch.setattr(probe.ga, "_client_size", lambda _hwnd: _SIZE)
    explicit = probe.ga.find_in_roi(
        4242, "rule_row_sitai", roi=roi, directory=tmp_path, on_capture_failure="miss"
    )
    state, three, why = probe.locate_state(4242, "rule_row_sitai", roi=roi, directory=tmp_path)
    assert state == probe.LOOKUP_HIT
    assert why == ""
    assert explicit is not None
    assert three is not None
    assert (explicit.x, explicit.y, explicit.score, explicit.box) == (
        three.x,
        three.y,
        three.score,
        three.box,
    )
    # 再对一次**原始**读数：两条路都只是「匹配 + 按 ROI 平移」，没有别的手脚
    raw = probe.ga.locate_optional(frame, "rule_row_sitai", first_hit=True, directory=tmp_path)
    assert raw is not None
    dx, dy = probe.ga._roi_offset(4242, roi)
    assert (raw.x + dx, raw.y + dy, raw.score) == (explicit.x, explicit.y, explicit.score)
    assert explicit.box == (
        raw.box[0] + dx,
        raw.box[1] + dy,
        raw.box[2] + dx,
        raw.box[3] + dy,
    )


def test_启动期一次抓不到图_轮询继续_整遍照走(driver: SimpleNamespace, probe: ModuleType) -> None:
    """启动期瞬时抓不到图 ⇒ **继续等**（不中止、不把"看不到"记成"主菜单没画出来"）。

    造法：让驱动自带的三态查找第一次吐 `LOOKUP_UNSEEN`，之后照常命中。
    """
    driver.state_script.append((probe.LOOKUP_UNSEEN, None, "（用例）抓到的是近乎纯色的画面"))
    record = driver.跑()
    assert driver.state_script == []  # 那一态**真的被走过**
    assert record.error is None
    assert record.code == 0
    assert len(record.pass_dirs) == 1


def test_启动期一直抓不到图_超时文本点名次数_收尾照走(
    driver: SimpleNamespace, probe: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """一路抓不到图 ⇒ 超时文本必须**点名这是"看不到"**（与"主菜单没画出来"分开）+ 收尾照走。

    用假时间：睡眠推进单调钟 ⇒ 期限可确定复算（`LOAD_TIMEOUT` = 1.5 ⇒ 恰好两轮）。
    """
    for _ in range(4):
        driver.state_script.append(
            (probe.LOOKUP_UNSEEN, None, "（用例）抓到的是近乎纯色的画面（加载中 / 最小化）")
        )
    monkeypatch.setattr(probe, "time", _FakeTime())
    record = driver.跑(constants={"LOAD_TIMEOUT": 1.5})
    assert isinstance(record.error, RuntimeError)  # 但**不是** CaptureFailedError：轮询没抛
    text = str(record.error)
    assert "主菜单没画出来" in text
    assert "2 次是**抓不到图**" in text
    assert "近乎纯色" in text
    assert "看不到 ≠ 没有" in text
    # 既有收尾三件照走：落帧目录还原、杀进程、还原 content_load
    assert record.shot_dir_after == record.shot_dir_before
    assert driver.teardown.kill == 1
    assert driver.teardown.restore == 1


# ── t41：取证执行器（L5→L16）与「先解悬停、再自检」的修因 ───────────────────────

#: 悬停态 ◀ 的逐列高度：Pass A `26-tier-prev-candidate.png` 的**现读形态** —— 琥珀 **130**、
#: 簇宽 **12** 列（干净态是 125 / 11 列）。多出来的那一列就是光标压在箭头上时多照亮的
#: 抗锯齿边缘（▶ 没被悬停，一个像素没变）⇒ 镜像判据的**等宽**要求当场假红。
_HOVERED_PREV_PROFILE = (1, 3, 5, 7, 8, 10, 12, 13, 15, 17, 19, 20)


def _hovered_frame() -> Image.Image:
    """「点完 ◀、光标还压在 ◀ 上」的那一帧（Pass A 现场复刻）。"""
    return _frame(prev_profile=_HOVERED_PREV_PROFILE)


def test_修因_悬停态旧写法红_中性重抓后放行(
    probe: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pass A 的假阴性现场复刻：**旧写法红、新写法绿**（两条读数都在这里）。

    实机读数（`26-tier-prev-candidate.png`）：悬停态 ◀ = 琥珀 **130** / **12×20**、
    ▶ = 125 / 11×20 ⇒ 两枚**各自的形状体检都合规**，拦住它的只能是镜像那一条。
    """
    hovered = _hovered_frame()
    # ① 旧写法（直接拿悬停那一帧自检）：红 —— 而且理由是**镜像**，不是"没找到""形状不符"
    with pytest.raises(probe.RowArrowCheckError) as caught:
        probe.require_row_arrows(hovered, row_center_y=_ROW_CENTER_Y)
    assert caught.value.reason == "镜像不过"
    assert "不互成镜像" in str(caught.value)
    # 拦住它的**只能是**镜像那一条：干净态互成镜像、最小判据在悬停剖面上仍然是 True
    assert probe.row_arrow_profiles_mirror(_PROFILE, tuple(reversed(_PROFILE))) is True
    assert probe.row_arrow_probe_minimal(_HOVERED_PREV_PROFILE, tuple(reversed(_PROFILE))) is True
    assert (
        probe.row_arrow_profiles_mirror(_HOVERED_PREV_PROFILE, tuple(reversed(_PROFILE))) is False
    )
    # ② 新写法：自检前先挪到中性点、**等到连续两帧一致**、重新抓一张 ⇒ 放行
    feed = _FrameFeed(lambda marker: hovered if marker == 1 else _frame())
    monkeypatch.setattr(probe.ga, "screenshot", feed)
    cursor: list[tuple[int, int]] = []
    clicks: list[tuple[int, int]] = []
    monkeypatch.setattr(probe.ga, "_set_cursor", lambda x, y: cursor.append((x, y)))
    monkeypatch.setattr(probe.ga, "click_client", lambda _h, x, y, **_kw: clicks.append((x, y)))
    spot = probe.click_row_arrow(4242, which="prev", image=hovered, row_center_y=_ROW_CENTER_Y)
    assert spot.x == probe.ROW_ARROW_PREV_X
    assert spot.amber == 125  # 量到的是**解悬停之后**那一枚，不是手里那张悬停帧
    assert clicks == [(probe.ROW_ARROW_PREV_X, _ROW_CENTER_Y)]
    assert cursor[0] == probe.NEUTRAL_CURSOR_XY  # 先去的**中性点**（不是箭头）
    assert cursor[-1] == (probe.ROW_ARROW_PREV_X, _ROW_CENTER_Y)
    # ③「等够」是**量出来的**：1 张悬停 + 连续两张干净 ⇒ 第 3 张就返回（没跑满 NEUTRAL_TRIES）
    assert feed.calls == 3
    # ④ 反照：上限压到 1（等不到"连续两帧一致"）⇒ 退回手里那张悬停帧 ⇒ **照红**（不是橡皮图章）
    monkeypatch.setattr(probe, "NEUTRAL_TRIES", 1)
    monkeypatch.setattr(
        probe.ga, "screenshot", _FrameFeed(lambda marker: hovered if marker == 1 else _frame())
    )
    with pytest.raises(probe.RowArrowCheckError) as caught2:
        probe.click_row_arrow(4242, which="prev", image=hovered, row_center_y=_ROW_CENTER_Y)
    assert caught2.value.reason == "镜像不过"
    assert clicks == [(probe.ROW_ARROW_PREV_X, _ROW_CENTER_Y)]  # ④ 一次都没点（那条是 ② 点的）


def test_修因_真不一致_中性重抓后仍红(probe: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """阴性对照：两枚箭头**真不一样**（不是悬停闹的）⇒ 中性重抓之后**仍必须红**。

    边界就在这里：修因修的是「光标压上去多照亮一列」，**不是**把镜像判据放松成「宽度差一列
    也放过」—— 真不一致必须一路红到底，且一个鼠标键都不送。
    """
    unmirrored = _frame(next_profile=_PROFILE_UNMIRRORED)
    feed = _FrameFeed(lambda _marker: unmirrored)  # 抓多少次都是这张：中性重抓也解不掉
    monkeypatch.setattr(probe.ga, "screenshot", feed)
    cursor: list[tuple[int, int]] = []
    clicks: list[tuple[int, int]] = []
    monkeypatch.setattr(probe.ga, "_set_cursor", lambda x, y: cursor.append((x, y)))
    monkeypatch.setattr(probe.ga, "click_client", lambda _h, x, y, **_kw: clicks.append((x, y)))
    with pytest.raises(probe.RowArrowCheckError) as caught:
        probe.click_row_arrow(4242, which="next", image=unmirrored, row_center_y=_ROW_CENTER_Y)
    assert caught.value.reason == "镜像不过"
    assert clicks == []  # 一个鼠标键也没送出去
    assert cursor == [probe.NEUTRAL_CURSOR_XY]  # 只去了中性点，**没落到箭头上**
    assert feed.calls == 2  # 连续两帧一致 ⇒ 第 2 张就返回（等够即走，不空转）


def test_修因_抓不到图_退回手里那一帧_不抛也不假绿(
    probe: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """中性重抓失败时**退回手里那一帧**：手里干净就照常点，手里是悬停帧就照红（不假绿）。"""

    def _boom(_hwnd: int = 0, roi: object = None) -> Image.Image:
        raise probe.ga.CaptureFailedError("（用例）抓不到图")

    monkeypatch.setattr(probe.ga, "screenshot", _boom)
    cursor: list[tuple[int, int]] = []
    clicks: list[tuple[int, int]] = []
    monkeypatch.setattr(probe.ga, "_set_cursor", lambda x, y: cursor.append((x, y)))
    monkeypatch.setattr(probe.ga, "click_client", lambda _h, x, y, **_kw: clicks.append((x, y)))
    spot = probe.click_row_arrow(4242, which="prev", image=_frame(), row_center_y=_ROW_CENTER_Y)
    assert spot.x == probe.ROW_ARROW_PREV_X
    assert clicks == [(probe.ROW_ARROW_PREV_X, _ROW_CENTER_Y)]
    assert cursor == [probe.NEUTRAL_CURSOR_XY, (probe.ROW_ARROW_PREV_X, _ROW_CENTER_Y)]
    with pytest.raises(probe.RowArrowCheckError) as caught:
        probe.click_row_arrow(
            4242, which="prev", image=_hovered_frame(), row_center_y=_ROW_CENTER_Y
        )
    assert caught.value.reason == "镜像不过"  # 手里那张是悬停帧 ⇒ 照红
    assert clicks == [(probe.ROW_ARROW_PREV_X, _ROW_CENTER_Y)]  # 第二次一个键也没送
    assert cursor == [
        probe.NEUTRAL_CURSOR_XY,
        (probe.ROW_ARROW_PREV_X, _ROW_CENTER_Y),
        probe.NEUTRAL_CURSOR_XY,
    ]


# ── t41：承重判据的单元面（档名读数 / 三块同帧 / 应用 vs 只关窗）────────────────


def _tier_patch(path: Path, *, seed: int = 0) -> Image.Image:
    """造一张「档位模板」用的合成小图（**逐像素噪声**，不同 seed 之间互不相似）。

    早先那版只把每列绿通道按 `seed` 平移（种子之间差 ≤1/255），于是「不该命中的模板」
    也拿 0.999+ ⇒ 用例量到的是**退化匹配**、不是判据本体（`zh/README.md` 专门警告过这条：
    「自证 1.0000」也可能是无信息平底的自匹配）。逐像素噪声下：同 seed 逐像素相同
    （自证 1.0），异 seed 互相关 ≈ 0。
    """
    rng = random.Random(seed)  # 可复现的合成噪声：要的是「互不相似」，不是密码学随机性
    patch = Image.new("RGB", (70, 21), _BASE)
    for y in range(21):
        for x in range(70):
            if rng.random() < 0.5:
                patch.putpixel((x, y), _AMBER)
    patch.save(path)
    return patch


def test_档名读数_恰一张命中才算读到(tmp_path: Path, probe: ModuleType) -> None:
    """L8 的承重判据：**恰一张**命中才算读到；零张与多张**都**报「读不出」。

    零张/多张都返回 `("", 为什么)`，调用方（执行器）拿到空档名就**报错停手** ——
    **绝不**假定默认中间档（口径 §3.2/§7）。
    """
    one = tmp_path / "one"
    one.mkdir()
    frame = Image.new("RGB", _SIZE, _BASE)
    uniform = _tier_patch(one / "tier_uniform_name.png")
    frame.paste(uniform, (600, 300))
    harsh = _tier_patch(one / "tier_harsh_name.png", seed=5)  # 存着、但这一帧上不命中
    history = _tier_patch(one / "tier_history_friendly_name.png", seed=9)
    # 「不该命中的模板」必须**真的不一样**：早先那版种子之间只差 1/255 ⇒ 量的是退化匹配
    assert len({uniform.tobytes(), harsh.tobytes(), history.tobytes()}) == 3
    tiers = ["history_friendly", "uniform", "harsh"]
    roi = (0.2, 0.2, 0.6, 0.5)
    # ① 恰一张 ⇒ 读到，并**点名是哪一档** + 给分数读数
    name, why = probe.read_tier(frame, tiers=tiers, roi=roi, directory=one)
    assert name == "uniform"
    assert "uniform" in why
    assert 0.0 < float(why.rsplit(" ", 1)[-1]) <= 1.0  # 读数末尾是分数，不是一句「读到了」
    # ② 零张 ⇒ 读不出（不返回默认中间档）
    blank = Image.new("RGB", _SIZE, _BASE)
    name0, why0 = probe.read_tier(blank, tiers=tiers, roi=roi, directory=one)
    assert name0 == ""
    assert "一张都没命中" in why0
    # ③ 多张同时命中 ⇒ 也读不出（两张一模一样的模板存成两个名字）
    two = tmp_path / "two"
    two.mkdir()
    shared = _tier_patch(two / "tier_uniform_name.png")
    shared.save(two / "tier_harsh_name.png")
    name1, why1 = probe.read_tier(frame, tiers=tiers, roi=roi, directory=two)
    assert name1 == ""
    assert "多张档名模板同时命中" in why1


def test_档位三块模板_同帧各命中才算过(tmp_path: Path, probe: ModuleType) -> None:
    """L8 逐档判据：档名 + 说明首段 + 说明尾段**必须在同一帧**各自命中（缺一块即不过）。"""
    # 种子必须**逐块**不同：早先取 `seed=len(suffix) + 1`，而 `desc_head` 与 `desc_tail`
    # 同长 ⇒ 两张模板逐字节相同 ⇒「缺尾段」那帧尾段也命中（verify 1 首跑就是这么红的：1262→1277）。
    blocks = ("name", "desc_head", "desc_tail")
    patches = {
        suffix: _tier_patch(tmp_path / f"tier_uniform_{suffix}.png", seed=index + 1)
        for index, suffix in enumerate(blocks)
    }
    roi = (0.2, 0.2, 0.6, 0.5)
    full = Image.new("RGB", _SIZE, _BASE)
    for index, suffix in enumerate(blocks):
        full.paste(patches[suffix], (600, 300 + index * 60))
    ok, reading = probe.tier_evidence(full, "uniform", roi=roi, directory=tmp_path)
    assert ok is True
    assert reading.count("✓") == 3
    # 缺"说明尾段"那一块 ⇒ 整档不过，且读数点名是**哪一块**没命中（不是一句"没过"）
    partial = Image.new("RGB", _SIZE, _BASE)
    partial.paste(patches["name"], (600, 300))
    partial.paste(patches["desc_head"], (600, 360))
    ok2, reading2 = probe.tier_evidence(partial, "uniform", roi=roi, directory=tmp_path)
    assert ok2 is False
    assert "desc_tail" in reading2
    assert "✗" in reading2


def test_L9判据_读回来不等于刚才那一档就判红(probe: ModuleType) -> None:
    """「只关窗」的对照：应用 `harsh` 之后重开读到 `uniform` ⇒ **不过**，且点名只 Hide。

    `Hide` 与点背景都不落定 ⇒「重开读到的那一档」才是「应用」这一步的判据本体。
    """
    verdict, why = probe.apply_outcome(want="harsh", after="uniform", evidence_ok=True)
    assert verdict == "不过"
    assert "只 Hide 没 ApplySettings" in why
    assert probe.apply_outcome(want="harsh", after="harsh", evidence_ok=True)[0] == "过"
    # 读不出（量不到）也**不过** —— 不许把"没量到"当"过了"
    verdict0, why0 = probe.apply_outcome(want="harsh", after="", evidence_ok=False)
    assert verdict0 == "不过"
    assert "读不出是哪一档" in why0
    # 档读对了、但三块模板没同帧命中 ⇒ 也不过
    verdict1, why1 = probe.apply_outcome(want="harsh", after="harsh", evidence_ok=False)
    assert verdict1 == "不过"
    assert "三块模板没在同一帧" in why1


def test_执行器_非侦察路径真的逐级执行L5到L15() -> None:
    """**源文件不变量**：`if args.recon:` 的 `else` 分支里真的逐级执行 L5→L15。

    为什么要有这一条：收尾文档曾把「recon 的候选帧」读成「国家屏链已通」，而取证模式下
    L8–L16 **从来没有执行器**（L4→L7 的执行体只挂在侦察那一支上）。这条不变量把
    「执行器真的在源码里、且逐级都有出处」钉住 —— 想把它退回一句话的注释，当场红。
    """
    tree = ast.parse(_PROBE.read_text(encoding="utf-8"))
    branch: list[ast.stmt] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Attribute):
            test = node.test
            if (
                test.attr == "recon"
                and isinstance(test.value, ast.Name)
                and test.value.id == "args"
            ):
                branch = list(node.orelse)
                break
    assert branch, "`if args.recon:` 的 else 分支不见了（取证执行器没了）"
    called: set[str] = set()
    frame_of: set[str] = set()
    for node in ast.walk(ast.Module(body=branch, type_ignores=[])):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                called.add(f"{func.value.id}.{func.attr}")
        elif (
            isinstance(node, ast.Attribute)
            and node.attr == "frame"
            and isinstance(node.value, ast.Name)
        ):
            frame_of.add(node.value.id)
    need = {
        "click_row_arrow",  # L8 逐档导航：每次点击前都过琥珀镜像三角自检
        "wait_for_screen",  # L6/L9 的正向判据（等下一屏自己的凭据出现）
        "wait_changed",  # L12 放冲击之后画面真的变了
        "locate_our_row",  # L7 定位我们那一行（拖滚动条，不再是死代码）
        "read_tier",  # L8 档名读数（恰一张命中才算读到）
        "tier_evidence",  # L8 三块模板同帧
        "apply_outcome",  # L9 「应用」之后读回来核对
        "ga.tick_mark",  # L11 真判据 = Processing Tick 从无到有
        "ga.wait_until_readable",  # L11 等那一行出现
        "tick_outcome",  # L11 时间判词（显式取 `.tick` 再比，t48）
        "difficulty_log_expectations",  # L13 引擎日志两族期望
        "read_probe_facts",  # L13 逐条核对
        "note_missing",  # 缺模板：承重遍停手、收料遍记「未达成」
        "click_at",
        "waited",
        "fail",
        "retry_frame",
        "land_on",
        "judge_here",
        "apply_cycle",
    }
    missing = sorted(need - called)
    assert missing == [], f"这些逐级动作没进非侦察分支：{missing}"
    # 逐级出处：L5–L15 各自的落帧标签都在（L13 是日志读数、没有帧，所以不在其中）
    assert {"l5", "l6", "l7", "l8", "l9", "l10", "l11", "l12", "l14", "l15"} <= frame_of


# ── t48：L11 的时间判词（`.tick` 与对象之别）────────────────────────────────────


def test_L11时间判词_不往前或读不到都给判词_不是AttributeError(probe: ModuleType) -> None:
    """点击前读得到 tick ⇒ 这一遍按**递增**判（L11 那支写明的状态）。

    停在同一 tick、after 读不到，都必须是**判词**，不许是 `AttributeError` —— 后者会把
    L12–L16 整段挡在 `finally` 后面（链断在那里，不是判红）。
    """
    before = probe.ga.TickMark(tick="1836.5.31.12", mtime=1.0)
    # 正例：真往后走 ⇒ 判过，且判词带够前后两次读数
    verdict, why = probe.tick_outcome(before, probe.ga.TickMark(tick="1836.5.31.13", mtime=2.0))
    assert verdict == "过", why
    assert "1836.5.31.12" in why
    assert "1836.5.31.13" in why
    # 反例 a：同一个 tick（"从有到有"但没推进）⇒ 不过，判词与改前逐字相同
    verdict, why = probe.tick_outcome(before, probe.ga.TickMark(tick="1836.5.31.12", mtime=2.0))
    assert verdict == "不过"
    assert why == "tick 没往前走：tick=1836.5.31.12 mtime=1 → tick=1836.5.31.12 mtime=2"
    # 反例 b：after **读不到**（`NO_TICK`）⇒ 同样给判词，并把"读不到"写出来
    verdict, why = probe.tick_outcome(before, probe.ga.TickMark(tick=probe.ga.NO_TICK, mtime=0.0))
    assert verdict == "不过"
    assert "tick 没往前走" in why
    assert "<读不到>" in why
    # 反例 c：点击前就读不到 ⇒ 不走递增判（这一遍的真判据是「从无到有」）
    verdict, why = probe.tick_outcome(
        probe.ga.TickMark(tick=probe.ga.NO_TICK, mtime=0.0),
        probe.ga.TickMark(tick="1836.5.31.13", mtime=2.0),
    )
    assert verdict == "过", why
    assert "从无到有" in why


def test_L11时间判词_喂对象给is_later必炸_所以必须显式取tick(probe: ModuleType) -> None:
    """**阴性对照（根因）**：`ga.is_later` 走 `parse_tick_date`，第一句是 `text.strip()`。

    ⇒ 直接喂 `TickMark` 对象**必** `AttributeError`；喂 `.tick` 才对。这条钉住的是根因本身：
    修法只能是「显式取 `.tick`」，不是「碰巧不炸」。
    """
    before = probe.ga.TickMark(tick="1836.5.31.12", mtime=1.0)
    later = probe.ga.TickMark(tick="1836.5.31.13", mtime=2.0)
    with pytest.raises(AttributeError) as caught:
        probe.ga.is_later(before, later)
    assert "strip" in str(caught.value)
    assert probe.ga.is_later(before.tick, later.tick) is True
    # 读不到那一侧：`is_later` 对解析不出的字符串给 False（**不装作知道**），不是抛
    assert probe.ga.is_later(before.tick, probe.ga.NO_TICK) is False


def test_驱动里每次is_later的实参都是tick属性_去掉就当场红() -> None:
    """**源文件不变量**：驱动里 `ga.is_later(...)` 的每个实参都必须是 `<x>.tick`。

    把 `.tick` 去掉（回退成喂对象）⇒ 这条当场红；上一条用例证明喂对象**真的**会炸。
    计数断言是防空转：若驱动里一处 `is_later` 都没有，这个循环什么都证明不了。
    """
    tree = ast.parse(_PROBE.read_text(encoding="utf-8"))
    calls: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "ga"
            and func.attr == "is_later"
        ):
            args = [*node.args, *(kw.value for kw in node.keywords)]
            assert len(args) == 2, f":{node.lineno} `is_later` 应恰好两个实参"
            for arg in args:
                assert isinstance(arg, ast.Attribute), (
                    f":{node.lineno} 的实参不是 `<TickMark>.tick` ⇒ 喂对象必 AttributeError"
                )
                assert arg.attr == "tick", (
                    f":{node.lineno} 的实参不是 `<TickMark>.tick` ⇒ 喂对象必 AttributeError"
                )
            calls.append(node.lineno)
    assert len(calls) == 1, f"驱动里 `is_later` 现应恰好 1 处（在 `tick_outcome` 里），实为 {calls}"


class TestWaitForScreenRoi:
    """🔧 t8：判据 ROI 必须取**目标屏**的，不许取**点击发生那一屏**的。

    病害（Pass B 首跑 exit 1，证据 `tools/out/auto/pass-20261001-055543-harsh/`）：L5 用
    `l5.roi`（= `main_menu`，L5 自己那一屏）去等目标屏的 `btn_game_rules`（实测
    0.99999988 @(530,826)，像框 x 455-605 / y 800-852，属 `setup_rules`）⇒ 每次都等满
    90 s 超时；L6 与 L9-重开同型（`btn_rules_close` 实测 1.0 @(1385,159)，属
    `rules_window`，不在 `setup_rules` 的 x 442-624 / y 799-859 里）。修法：判据 ROI 一律
    用目标屏的（`NEXT_SCREEN` 早就把「目标屏模板, 目标屏 ROI」写对了，只有取证分支没用）。
    """

    @staticmethod
    def _wait_for_screen_rois() -> list[tuple[int, str, str]]:
        """取出驱动源码里每处 `wait_for_screen(<模板>, <ROI 表达式>, …)` 的 `(行号, 模板, ROI)`。"""
        tree = ast.parse(_PROBE.read_text(encoding="utf-8"))
        out: list[tuple[int, str, str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or len(node.args) < 2:
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name != "wait_for_screen":
                continue
            tmpl, roi = node.args[0], node.args[1]
            tmpl_txt = tmpl.value if isinstance(tmpl, ast.Constant) else ast.unparse(tmpl)
            out.append((node.lineno, str(tmpl_txt), ast.unparse(roi)))
        return out

    def test_L5等的是目标屏的凭据与ROI(self, probe: ModuleType) -> None:
        assert probe.NEXT_SCREEN["L5 点「新游戏」"] == ("btn_game_rules", "setup_rules")
        calls = [c for c in self._wait_for_screen_rois() if c[1] == "btn_game_rules"]
        assert calls, "驱动里应当有等 `btn_game_rules` 的判据点"
        for lineno, _tmpl, roi in calls:
            assert "l5.roi" not in roi, f":{lineno} 判据 ROI 又取成 L5 自己那一屏（`{roi}`）"
            assert "main_menu" not in roi, (
                f":{lineno} 判据 ROI 取成 `main_menu`（L5 自己那一屏）⇒ 必然等满 90 s 超时"
            )

    def test_规则窗凭据一律在rules_window里找(self, probe: ModuleType) -> None:
        calls = [c for c in self._wait_for_screen_rois() if c[1] == "btn_rules_close"]
        assert len(calls) >= 2, (
            f"`btn_rules_close` 的判据点应 ≥2（L6 与 L9-重开），实为 {len(calls)}"
        )
        for lineno, _tmpl, roi in calls:
            assert roi.strip("'\"") == "rules_window", (
                f":{lineno} 规则窗凭据没在 `rules_window` 里找（`{roi}`）—— 它不在 `setup_rules` 里"
            )

    def test_为什么是rules_window_用实测位置钉住(self, probe: ModuleType) -> None:
        """把实测的「规则窗 X ≈ (1385,159)」编码进用例：落在 `rules_window` 内、不在 `setup_rules` 里。"""
        width, height = 1920, 1080

        def inside(roi: tuple[float, float, float, float], x: int, y: int) -> bool:
            x0, y0, x1, y1 = roi
            return x0 * width <= x <= x1 * width and y0 * height <= y <= y1 * height

        assert inside(probe.ROIS["rules_window"], 1385, 159)
        assert not inside(probe.ROIS["setup_rules"], 1385, 159)

    def test_判据ROI的字面量必须是ROIS里的键(self, probe: ModuleType) -> None:
        """`wait_for_screen` 内部走 `ROIS[roi_name]` ⇒ 传不在表里的字面量会 `KeyError`（不是判据失败）。"""
        for lineno, _tmpl, roi in self._wait_for_screen_rois():
            if roi.startswith('"'):
                key = roi.strip('"')
                assert key in probe.ROIS, f":{lineno} 判据 ROI 字面量 `{key}` 不在 ROIS 里"
