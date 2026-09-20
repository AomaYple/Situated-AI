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

from . import (
    ai,
    assets,
    config,
    defines,
    doc04,
    doc15,
    doc16,
    doc17,
    doc18,
    docs_mirror,
    game_root,
    install_tree,
    localization,
    modifiers,
    tabular,
    usage,
)
from .doc_tables import (
    KeyedTableSpec,
    TableSpec,
    check_doc,
    current_rows,
    merge_rows,
    patch_doc,
    spec_key,
    split_row,
)

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
            # doc 17 整族（25 张表里接了 24 张）—— 口径有四种，故单独一个模块。
            path=config.DOCS / "17-角色科技与呈现.md",
            specs=tuple(doc17.doc_table_specs()),
        ),
        DocTarget(
            # doc 06（本地化与界面资源）：安装树那四张表在 install_tree，
            # 两张本地化表在 localization，DDS 头普查在 assets —— 同一棵树的三面，
            # 口径各自写在模块里。
            path=config.DOCS / "06-本地化与界面资源.md",
            specs=tuple(install_tree.doc06_table_specs())
            + tuple(localization.doc_table_specs())
            + tuple(assets.doc_table_specs())
            + tuple(tabular.doc_table_specs()),
        ),
        DocTarget(
            # doc 15（政治人口与社会）：§0 的 25 目录总览 + 四节里的六张表。
            path=config.DOCS / "15-政治人口与社会.md",
            specs=tuple(doc15.doc_table_specs()),
        ),
        DocTarget(
            # doc 04（脚本系统）：scripted_* / events / journal_entries / effect_localization
            # 四块共 15 张表。含 6 张字段表 + 2 张命名形态 + JE 分组两栏。
            path=config.DOCS / "04-脚本系统.md",
            specs=tuple(doc04.doc_table_specs()),
        ),
        DocTarget(
            # doc 16 剩下的八张「统计单位不是字段」的表（文本级 / 任意深度）。
            # 前面那 23 张在 usage.py 的 doc16 规格里。
            path=config.DOCS / "16-外交军事与地图.md",
            specs=tuple(s for s in usage.doc_table_specs() if "doc16" in s.name)
            + tuple(doc16.doc_table_specs()),
        ),
        DocTarget(
            # doc 07（官方文档索引）：§0 那张统计总览 —— 8 行全部由**入库清单**现算，
            # 不需要游戏（这也是它第一次进生成器）。
            path=config.DOCS / "07-官方文档索引.md",
            specs=tuple(docs_mirror.doc_table_specs()),
        ),
        # 散落的单表文档：doc 03 / 09 / 10（AI）、doc 11 / 18 / 20（子目录文件数）。
        # 它们各只有一两张表，为每篇建一个模块是过度设计 —— 按名字前缀分发给各自的目标。
        *(
            DocTarget(
                path=config.DOCS / f"{doc}.md",
                specs=tuple(s for s in (_misc_specs()) if s.name.startswith(f"doc{num} ")),
            )
            for doc, num in (
                ("03-AI系统", "03"),
                ("09-AI-mod实战技法", "09"),
                ("10-AI策略字段参考", "10"),
                ("11-历史初始状态与AI策略分配", "11"),
                ("18-history初始状态系统", "18"),
                ("20-引擎共享层jomini与clausewitz", "20"),
            )
        ),
    )


def _misc_specs() -> list[TableSpec | KeyedTableSpec]:
    """那几篇「只有一两张表」的文档的规格合集（AI + 目录文件数 + doc 18 效果表 + doc 06 的 DDS 普查）。"""
    return [*ai.doc_table_specs(), *install_tree.doc_misc_specs(), *doc18.doc_table_specs()]


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


def render_all() -> dict[str, list[str]]:
    """把**每一张**生成表算成数据行，返回 ``{表标识: [行文本, …]}``。

    用途是让快照带上「这批表当时长什么样」：CI 上没有游戏，算不出这些行，
    但**可以**拿入库快照里的这份记录回头核对文档是否被手改过
    （``v3 tables --offline``）。这跟 `v3 verify --from-snapshot` 是同一个思路：
    真值入一份精简快照，离线只做比对，不假装能重算。
    """
    out: dict[str, list[str]] = {}
    for target in targets():
        for spec in target.specs:
            key = spec_key(target.name, spec)
            try:
                out[key] = _render_one(target.path, spec)
            except Exception as exc:  # 单张表取不到不该让快照整体失败
                out[key] = [f"<未取到：{type(exc).__name__}: {exc}>"]
    return out


def _render_one(doc: Path, spec: TableSpec | KeyedTableSpec) -> list[str]:
    """算出单张表的数据行。``KeyedTableSpec`` 要读文档现值来保留散文列。"""
    if isinstance(spec, TableSpec):
        return spec.rows()
    existing = current_rows(doc, spec)
    return merge_rows(
        spec,
        [split_row(ln) for ln in existing],
        width=len(split_row(spec.header)),
        raw=existing,
    )


__all__ = ["DocTarget", "check_all", "render_all", "targets", "write_all"]
