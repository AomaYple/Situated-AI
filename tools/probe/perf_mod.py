"""生成"性能取样"本地 mod：给 debug 模式加两个固定坐标的按钮（clear / dump 逐任务计时）。

## 为什么需要它

G-EXIT-3 要"原版一局 + 装我们 mod 一局"的**逐任务计时对照**，而计时的 dump 只能靠
引擎控制台命令 `dump_ticktask_timings`。命令行走不通（`run_console_action` **跑完即退**，
取不到"跑到目标日期之后"的窗口），所以挂一个本地 mod，用 GUI 按钮触发 ——
这正是 `阶段4-性能仪表侦察.md` 实测走通的那条路。

## 与上次侦察的差别（这次做得更"可自动化"）

* 按钮放在**固定位置**（左上角 20,20 起，200x40，间距 10）⇒ 点击坐标是**算出来的**，
  不需要模板匹配，也不会因为分辨率/缩放的匹配误差而点空：
  按钮涂**唯一颜色**（品红 CLEAR / 青 DUMP），驱动脚本抓图找**色块质心**再点。
* 覆写的是 `gui/error_deer.gui`（原版就有、`visible = "[InDebugMode]"`），
  照抄原版写法（`using = default_button` + `onclick = "[ExecuteConsoleCommand(...)]"`）。

⚠️ 这是**探针用**的一次性 mod：不是产品 mod，不进 `mod/`，用完删掉（连同 content_load 还原）。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdx import config

#: 按钮颜色（探针靠**颜色质心**定位按钮，不靠猜坐标）：品红 = CLEAR、青 = DUMP。
CLEAR_RGB = (255, 0, 255)
DUMP_RGB = (0, 255, 255)
COLOR_TOLERANCE = 40

#: 插进原版 `error_deer` 的 flowcontainer 里的两个按钮（制表符缩进与原文件一致）。
BUTTONS = """
		# ── 探针插入：性能取样按钮（品红 = CLEAR、青 = DUMP，靠**颜色**定位）──
		button = {
			onclick = "[ExecuteConsoleCommand('clear_ticktask_timings')]"
			size = { 160 30 }
			background = { color = { 255 0 255 } }
		}

		button = {
			onclick = "[ExecuteConsoleCommand('dump_ticktask_timings')]"
			size = { 160 30 }
			background = { color = { 0 255 255 } }
		}
"""

DESCRIPTOR = """name="Sitai Perf Probe"
path="mod/zz_sitai_perf"
supported_version="1.14.*"
"""

METADATA = {
    "name": "Sitai Perf Probe",
    "id": "",
    "version": "1.0",
    "supported_game_version": "1.14.*",
    "short_description": "G-EXIT-3 取样用：clear/dump 逐任务计时（探针，用完即删）",
    "tags": ["Utilities"],
    "relationships": [],
    "game_custom_data": {"multiplayer_safety": "none"},
}


def probe_mod_dir() -> Path:
    """用户 mod 目录下的探针 mod（**不进仓库**，用完删）。"""
    return (
        Path.home() / "Documents" / "Paradox Interactive" / "Victoria 3" / "mod" / "zz_sitai_perf"
    )


def write_mod(target: Path | None = None) -> Path:
    root = target or probe_mod_dir()
    if root.exists():
        shutil.rmtree(root)
    (root / "gui").mkdir(parents=True)
    (root / "descriptor.mod").write_text(DESCRIPTOR, encoding="utf-8")
    (root / ".metadata").mkdir()
    (root / ".metadata" / "metadata.json").write_text(
        json.dumps(METADATA, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # **覆写原版 + 往它的 flowcontainer 里插按钮**：原版 `error_deer` 在 debug 模式常驻可见，
    # 而**我自建的顶层 widget 不会被实例化**（实测：点了 DUMP 毫无反应）。
    vanilla = config.GAME / "gui" / "error_deer.gui"
    if not vanilla.is_file():
        raise SystemExit(f"找不到原版 gui：{vanilla}")
    base = vanilla.read_text(encoding="utf-8-sig")
    marker = "flowcontainer = {"
    at = base.index(marker) + len(marker)
    (root / "gui" / "error_deer.gui").write_text(base[:at] + BUTTONS + base[at:], encoding="utf-8")
    return root


def main() -> int:
    root = write_mod()
    print(f"探针 mod 已写入：{root}")
    print("  gui/error_deer.gui（覆写原版文件，debug 模式可见）")
    print(f"  按钮颜色：CLEAR={CLEAR_RGB}、DUMP={DUMP_RGB}（靠色块质心定位）")
    print("[注意] 覆写原版 gui 只允许出现在这个**一次性探针**里；产品 mod 走 P1/R3（纯追加）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
