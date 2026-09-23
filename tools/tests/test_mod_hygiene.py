"""P3 / G-EXIT-4：`mod/` 下的文件必须**正好**等于生成器的产出（不许有手写产物）。

为什么需要这条等式
------------------
`v3 modgen --check` 与 `v3 modguard` 都只认**本档案命名空间**（`sitai_` 前缀）。
实测（阶段 4 收口时真跑过）：

```text
mod/common/scripted_effects/zz_stray_handwritten.txt   # 别的前缀
  → v3 modgen --check  exit 0   盘上 9 个产物与数据源逐字节一致 ✅
  → v3 modguard        exit 0   五道闸门全过 ✅

mod/common/scripted_effects/sitai_stray_handwritten.txt  # 本档案前缀
  → v3 modgen --check  exit 1   （产物不许手改）
  → v3 modguard        exit 1   （有闸门不过）
```

也就是说：**换一个前缀手写一个游戏侧文件，两道门禁都看不见**。它会照样被打进
mod、可能与原版或第三方内容撞名 —— 而那正是闸门 ①（F7 命名空间）存在的理由。
这道缺口用最朴素的等式补上：`盘上文件集 == {生成结果} ∪ {数据源}`。

边界
----
* 这条等式只管**文件面**（有没有多余/缺失的文件），与 `modgen --check` 的
  **内容面**（逐字节一致）互补，两者都要有。
* 它不判断"这个文件合法吗" —— 合法性归闸门 ① / ②。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from pdx import modgen

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _relative_files(root: Path) -> set[str]:
    """``root`` 下所有普通文件的相对路径（posix 分隔符，便于跨平台比较）。"""
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def test_mod_目录里的文件正好等于生成器产出(tmp_path: Path) -> None:
    """盘上 `mod/`（除数据源）必须与"现在重新生成一遍"的文件集**逐个对上**。"""
    built = modgen.build_all(modgen.load_all())
    modgen.write(built, tmp_path)

    expected = _relative_files(tmp_path)
    source = {"data/" + p.name for p in modgen.DATA_DIR.glob(f"*{modgen.DATA_SUFFIX}")}
    actual = _relative_files(modgen.PRODUCT_DIR)

    extra = sorted(actual - expected - source)
    missing = sorted(expected - actual)
    assert not extra, (
        "mod/ 下有生成器不认识的文件（手写产物？）—— P3 要求游戏侧文件全部由 "
        f"`v3 modgen` 产出：{extra}"
    )
    assert not missing, (
        f"生成器该产出但盘上没有的文件（被手删了？）—— 跑 `v3 modgen --write`：{missing}"
    )
    assert actual == expected | source


def test_多余的手写文件会被这条等式抓住(tmp_path: Path) -> None:
    """阳性对照：证明上面那条等式**不是空断言**（换前缀也一样抓得住）。"""
    built = modgen.build_all(modgen.load_all())
    modgen.write(built, tmp_path)
    baseline = _relative_files(tmp_path)

    stray = tmp_path / "common" / "scripted_effects" / "zz_stray_handwritten.txt"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text("zz_stray = { }\n", encoding="utf-8")

    assert _relative_files(tmp_path) - baseline == {
        "common/scripted_effects/zz_stray_handwritten.txt"
    }, "换了前缀的手写文件也必须进入差集 —— 否则这条等式形同虚设"


def test_数据源目录也在文件面之内(tmp_path: Path) -> None:
    """数据源本身不许出现在产物目录里（它是输入，不是产物）—— 反向的一半。"""
    built = modgen.build_all(modgen.load_all())
    modgen.write(built, tmp_path)
    assert not list(tmp_path.glob(f"**/{modgen.DATA_SUFFIX}")), (
        "产物目录里出现了数据源文件：说明生成器把输入也当产物写出去了"
    )


def _our_modifier_fields() -> dict[str, list[str]]:
    """数据源里用到的**修正字段** → 用它的档案 id（``[pressure]`` 与 ``reform_inputs``）。"""
    fields: dict[str, list[str]] = {}
    for archive in modgen.load_all():
        for table in (archive.pressure, archive.inputs):
            if table is None:
                continue
            for effect in getattr(table, "effects", ()):
                fields.setdefault(effect.key, []).append(archive.id)
    return fields


def _vanilla_field_uses(field: str) -> int:
    """原版**脚本**里用了这个字段多少次（排除 ``modifier_type_definitions`` 自己）。"""
    from pdx import config

    hits = 0
    for path in config.GAME.rglob("*.txt"):
        if "modifier_type_definitions" in str(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:  # pragma: no cover - 读不动的文件跳过
            continue
        hits += len(re.findall(rf"^\s*{re.escape(field)}\s*=", text, re.MULTILINE))
    return hits


@pytest.mark.skipif(
    not (modgen.config.GAME / "common").is_dir(), reason="游戏目录不可用（要扫原版脚本）"
)
def test_我们用的修正字段原版真的在用() -> None:
    """**每个字段都必须「接上线」**：原版脚本用过它，**或** exe 里有它的字面量。

    为什么这条比闸门 ① 更严（2026-09-24，B88 那一轮发现）：闸门 ① 查的是
    `modifier_type_definitions` 那个**定义池** —— 而「有定义」不等于「引擎会读」。
    实测反例：`state_pop_support_movement_land_reform_add` 与 `country_institution_impact_add`
    在定义池里都**有**，但**原版脚本 0 处、exe 无字面量** ⇒ 用了它，五道闸门全绿，
    游戏里却很可能什么都不发生（这类键正是「声明了没接线」）。

    判据本身就是上面那句话，所以它是**可复算的**：不需要人去记哪些键可信。
    """
    from pdx import exe_strings

    identifiers = exe_strings.exe_identifiers() if exe_strings.exe_path().is_file() else frozenset()
    fields = _our_modifier_fields()
    assert len(fields) >= 10, f"只读到 {len(fields)} 个字段 —— 数据源的形状变了吗？"

    unwired = [
        (field, users)
        for field, users in sorted(fields.items())
        if not _vanilla_field_uses(field) and field not in identifiers
    ]
    assert not unwired, (
        "以下修正字段在原版里**没有接线**（脚本 0 处、exe 无字面量）—— "
        "定义池里有不等于引擎会读，换一个字段，或在 why 里写明为什么仍要用它：\n  "
        + "\n  ".join(f"{field}（{','.join(users)}）" for field, users in unwired)
    )
