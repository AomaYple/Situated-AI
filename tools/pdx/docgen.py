"""「哪些文档里有工具生成的表格」的**唯一登记处**。

为什么单独一个模块
------------------
生成逻辑分散在各领域模块里（defines 的 5 张表在 :mod:`pdx.defines`，
game 根目录与 ``paths.settings`` 在 :mod:`pdx.game_root`，
安装树与各目录统计在 :mod:`pdx.install_tree`），但**登记表**
必须只有一份 —— 否则「哪些表是生成的」会散落在 CLI、测试与文档三处，
而漏掉一处就意味着那张表回到无人重跑的状态（doc 05 就是这么落后了一个
游戏版本的；doc 08 则整整漂了 8 处，包括两个写错的版本修订哈希）。

本模块依赖各领域模块，反过来不成立；:mod:`pdx.defines` 依赖
:mod:`pdx.doc_tables` 但不依赖本模块，所以没有循环导入。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import config, defines, game_root, install_tree, modifiers, usage
from .doc_tables import KeyedTableSpec, TableSpec, check_doc, patch_doc

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(slots=True, frozen=True)
class DocTarget:
    """一份文档 + 它里面全部「由工具生成」的表。"""

    path: Path
    specs: tuple[TableSpec | KeyedTableSpec, ...]

    @property
    def name(self) -> str:
        return self.path.name


def targets() -> tuple[DocTarget, ...]:
    """全部登记在案的生成表。新增一张表 = 在这里多一项。"""
    return (
        DocTarget(
            path=config.DOCS / "05-defines与修饰符.md",
            # 两份来源拼在一起：defines 的表在前，modifiers 的表在后。
            # 合成一个 DocTarget 而不是登记两份同路径的 target —— 后者会让
            # `write_all` 对同一份文档写两遍（第一遍改过行号，第二遍得从头再找表）。
            specs=tuple(defines.doc_table_specs()) + tuple(modifiers.doc_table_specs()),
        ),
        DocTarget(
            path=config.DOCS / "19-game根级文件与工具链.md",
            specs=tuple(game_root.doc_table_specs()),
        ),
        DocTarget(
            path=config.DOCS / "08-目录全量清单.md",
            specs=tuple(install_tree.doc_table_specs()),
        ),
        DocTarget(
            # doc 04 / 14 / 16 的「用了多少次」类表（它们还没有各自的领域模块）
            path=config.DOCS / "04-脚本系统.md",
            specs=tuple(s for s in usage.doc_table_specs() if "doc04" in s.name),
        ),
        DocTarget(
            path=config.DOCS / "14-经济与生产系统.md",
            specs=tuple(s for s in usage.doc_table_specs() if "doc14" in s.name),
        ),
        DocTarget(
            path=config.DOCS / "16-外交军事与地图.md",
            specs=tuple(s for s in usage.doc_table_specs() if "doc16" in s.name),
        ),
    )


def check_all() -> list[tuple[str, int, str, str]]:
    """核对全部生成表，返回 ``[(文档名, 行号, 文档现值, 生成值), …]``。"""
    out: list[tuple[str, int, str, str]] = []
    for target in targets():
        out.extend(check_doc(target.path, target.specs))
    return out


def write_all() -> dict[str, int]:
    """重算并写回全部生成表，返回 ``{文档名 + 表名: 行数}``。"""
    out: dict[str, int] = {}
    for target in targets():
        for name, n in patch_doc(target.path, target.specs, write=True).items():
            out[f"{target.name} · {name}"] = n
    return out


__all__ = ["DocTarget", "check_all", "targets", "write_all"]
