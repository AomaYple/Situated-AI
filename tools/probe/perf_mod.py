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

#: 插进原版 `error_deer` 顶层的两个按钮（制表符缩进与根层一致）。
#:
#: ⚠️ **不要插进 `flowcontainer` 里**（2026-09-22 实测踩到）：插进去之后
#: 抓图里**一个品红/青像素都没有**（`error_deer` 本身可见、`error_counter` 也画出来了，
#: 说明"挂载成功但按钮没被布局"）。改成**自己的容器 + 显式 `size`/`position` + `layer`**
#: 之后不再依赖那个 flowcontainer 的尺寸协商。
#: 另外给每个按钮加一行 `text`：**可见的东西才存在** —— 光有色块容易被后续布局改动吃掉，
#: 而带文字之后人眼在截图里一眼就能确认。
#: 直接改原版 `error_deer` 里**已经存在**的那个按钮的 `onclick`。
#:
#: ⚠️ 为什么不再插入新按钮（三次实测都失败，教训写在这里）：
#: * 插进内层 `flowcontainer` ⇒ 抓图里**一个品红/青像素都没有**（父容器可见、
#:   `error_counter` 也画出来了，说明挂载成功但新按钮没被布局）；
#: * 换成**自己的 widget + 显式 size/position/text/textcolor** ⇒ 仍然一个像素都没有。
#: 结论：`error_deer` 这个 debug 覆写面**不吃新加的控件**（它自己的 `background`
#: 只有 0.4 alpha，新 widget 可能落在它的裁剪区外）。
#:
#: ⇒ 换成**改现有控件的行为**：`error_counter`（那个"我们有 84 个错误？！让我瞧瞧手册！"
#: 的按钮）**一定被布局**（截图里就在那），把它的 `onclick` 加一句
#: `ExecuteConsoleCommand('dump_ticktask_timings')` 即可 —— 点它一次，
#: 既打开错误日志、又把逐任务计时落盘。**不改它的样子、不往界面上加东西。**
#:
#: 探针不需要"clear"那个按钮：`run_once` 是**每局新建一个** `ticktask_timings.csv` 的
#: （跑之前先删旧的），而 `clear` 的作用只是"别让开局加载那段拉花读数" ——
#: 开局那一段只占 **~2 分钟 / 12 个月**的一小截，且**两局都同样包含它**，
#: 对照读的是差值，这一截不改变方向（写在结果文档的口径里）。
#: 覆写 `error_counter` 的 `onclick`：点它 = 把逐任务计时落盘。
#:
#: ⚠️ **整个表达式必须用 `"…"` 包起来**（`onclick = "[ExecuteConsoleCommand('…')]"`）：
#: 第一次写成裸表达式时引擎报 `gui/error_deer.gui:42 - '(' is not a valid widget/type/property`
#: —— 少了外层引号，解析器把 `ExecuteConsoleCommand` 当成控件类型、把括号当成属性名。
DUMP_ONCLICK = """\"[ExecuteConsoleCommand('dump_ticktask_timings')]\""""

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
    # **覆写原版 + 改它已有的那个按钮**：`error_deer` 在 debug 模式常驻可见，
    # 而**我自建的顶层 widget 不会被实例化**（实测：点了 DUMP 毫无反应；
    # 往它内部插新钮也三次都没画出来 —— 细节见 `DUMP_ONCLICK` 的注释）。
    # ⇒ 只改 `error_counter` 的 `onclick`：既不碰它的外观，也不需要新控件被布局。
    vanilla = config.GAME / "gui" / "error_deer.gui"
    if not vanilla.is_file():
        raise SystemExit(f"找不到原版 gui：{vanilla}")
    base = vanilla.read_text(encoding="utf-8-sig")
    marker = 'name = "error_counter"'
    at = base.index(marker)
    # 只在**这一段**里替换 onclick（别动别处的）：把原版那句**注释掉**，换成一整句 DUMP。
    # ⚠️ **不是**加第二句 —— 实测原版没有任何一处 `onclick` 带两条命令，
    # 而"同一属性写两遍"会被解析器只认最后一条（第一次尝试生成物里就是那两行）。
    tail = base[at:]
    on_index = tail.index("onclick =")
    # 连**行首缩进**一起换掉：只从 `onclick` 起替换会让新行落在错误的缩进层级上
    # （生成物里那一行顶格了 —— PDX 不在意缩进，但生成物要能读）。
    line_start = tail.rindex("\n", 0, on_index) + 1
    line_end = tail.index("\n", on_index)
    original = tail[on_index:line_end].strip()
    patched_tail = (
        tail[:line_start]
        + f"\t\t\t# 探针覆写：原版这里是 {original}\n"
        + "\t\t\tonclick = "
        + DUMP_ONCLICK
        + tail[line_end:]
    )
    (root / "gui" / "error_deer.gui").write_text(base[:at] + patched_tail, encoding="utf-8")
    return root


def main() -> int:
    root = write_mod()
    print(f"探针 mod 已写入：{root}")
    print("  gui/error_deer.gui（覆写原版；改的是 error_counter 的 onclick）")
    print(f"  判据：它在屏幕上**一定可见**（截图确认过），点它 = {DUMP_ONCLICK}")
    print("[注意] 覆写原版 gui 只允许出现在这个**一次性探针**里；产品 mod 走 P1/R3（纯追加）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
