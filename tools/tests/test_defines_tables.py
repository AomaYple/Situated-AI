"""doc 05 的 5 张统计表由 `v3 defines --tables` 生成，这里守住生成器。

为什么单独一个文件
------------------
那 5 张表原先由一批已退休的 PowerShell 脚本产出，之后再没人重跑过 ——
于是它们整整落后了一个游戏版本（1.14.3 给 `NMilitary` +1、`NDiplomacy` +39，
总数 3434 应当变 3488，文档里却一直写着 3434）。现在它们由
:func:`pdx.defines.patch_doc_tables` 生成，所以必须有人守着这条生成链：

* 表头还在不在文档里（文档结构被改过时，生成器要**报错而不是静默跳过**）
* 生成结果是不是文档的现值（否则说明有人手改了表，下次生成会覆盖掉）
* 是不是幂等（跑两次不该有变化）
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

from pdx import config, defines, doc_tables

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

DOC = config.DOCS / "05-defines与修饰符.md"


@pytest.fixture
def 文档副本(tmp_path: Path) -> Path:
    """把 doc 05 复制到临时目录，避免测试真的改动入库文档。"""
    if not DOC.is_file():
        pytest.skip("doc 05 不存在")
    if not (config.GAME / "common" / "defines").is_dir():
        pytest.skip("游戏目录不可用")
    target = tmp_path / DOC.name
    shutil.copyfile(DOC, target)
    return target


def test_五张表的表头都在文档里() -> None:
    text = DOC.read_text(encoding="utf-8")
    missing = [h for h in defines.DOC_TABLES if h not in text]
    assert not missing, f"doc 05 里找不到这些表头，生成器会直接报错：{missing}"
    # 参数前缀分组表曾是一张「号称脚本生成、实际无人重跑」的手抄表（漂了 3 处），
    # 现在也是生成表 —— 表头必须在文档里找得到。
    assert defines.PREFIX_TABLE in text, (
        f"doc 05 里找不到 {defines.PREFIX_TABLE!r} —— 前缀分组表被移走了？"
    )


def test_生成器不写盘(文档副本: Path) -> None:
    before = 文档副本.read_text(encoding="utf-8")
    specs = defines.doc_table_specs()
    replaced = doc_tables.patch_doc(文档副本, specs, write=False)
    # 断言「每条 spec 都改到了」，而不是跟 DOC_TABLES 比长度 ——
    # 后者只数得起 defines 那 5 张，前缀分组表不在其中（它在同一模块里生成，
    # 但不属于 DOC_TABLES 那组逐文件/逐命名空间的统计）。
    assert len(replaced) == len(specs)
    assert 文档副本.read_text(encoding="utf-8") == before, "write=False 却改了文件"


def test_生成是幂等的(文档副本: Path) -> None:
    doc_tables.patch_doc(文档副本, defines.doc_table_specs(), write=True)
    once = 文档副本.read_text(encoding="utf-8")
    doc_tables.patch_doc(文档副本, defines.doc_table_specs(), write=True)
    assert 文档副本.read_text(encoding="utf-8") == once, "跑两次结果不同"


def test_文档里的表就是生成器的输出() -> None:
    """**这条是核心**：文档现值必须等于重新生成的结果。

    失败说明有人手改了表 —— 下次 `v3 defines --tables --write` 会把它覆盖掉，
    所以要么跑一次生成器，要么改生成器。
    """
    if not (config.GAME / "common" / "defines").is_dir():
        pytest.skip("游戏目录不可用")
    rows = defines.doc_table_rows()
    text = DOC.read_text(encoding="utf-8").splitlines()
    stale: list[str] = []
    for header, want in rows.items():
        start = next((n for n, ln in enumerate(text) if ln.startswith(header)), None)
        assert start is not None, header
        n = start + 2
        for expected in want:
            actual = text[n] if n < len(text) else "<文档结束>"
            if actual != expected:
                stale.append(f"{header[:32]}…\n    文档: {actual}\n    生成: {expected}")
            n += 1
    assert not stale, (
        f"doc 05 有 {len(stale)} 行与生成器输出不一致"
        f"（跑 `v3 defines --tables --write` 可修）：\n" + "\n".join(stale[:6])
    )


def test_表头被改动时报错而不是静默跳过(tmp_path: Path) -> None:
    """生成器的失败必须是响的 —— 静默跳过正是它上一轮腐烂的原因。"""
    broken = tmp_path / "broken.md"
    broken.write_text("# 没有表格的文档\n", encoding="utf-8")
    with pytest.raises(doc_tables.TableNotFoundError):
        doc_tables.patch_doc(broken, defines.doc_table_specs(), write=False)
