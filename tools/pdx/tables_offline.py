"""生成表的**离线**核对：拿入库快照里的记录回头比文档，不读游戏。

为什么需要它
------------
169 张生成表是文档里大部分数字的来源，但算它们要读游戏本体 ——
CI runner 上没有游戏，于是「表格是否与生成结果一致」这件事一直只能在
本机用 `v3 tables` 回答。而表格被手改、或改了生成器却忘了重跑，
恰恰是最常见的漏检：正文数字有 `v3 verify --from-snapshot`（43 条断言）
守着，表格却没人守。

做法（与 `v3 verify --from-snapshot` 同一个思路）
-----------------------------------------------
1. 生成快照时把**每张表当时的数据行**记进 ``域.doc_tables``（:mod:`pdx.snapshot`）；
2. 离线时只读文档 + 快照，逐行比对；
3. ``--write`` 时按快照里的行把文档恢复成当时的样子 —— 这就是「没有游戏也能
   把表恢复到最后一次已知正确状态」的能力。

边界（**必须说清楚，否则它会被当成 `v3 tables`**）
------------------------------------------------
* 它证明不了「表与**现在的游戏**一致」，只证明「表与**入库快照**一致」；
* 游戏升级后表该变，这时正确流程仍是本机 `v3 refresh` 重生成表 + 重建快照；
* 快照里没有的表（新增的规格）会被单列为「快照缺这一张」，不算不一致。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import docgen
from .doc_tables import current_rows, spec_key, write_rows
from .snapshot import Snapshot
from .verify import latest_compact_snapshot

if TYPE_CHECKING:
    from pathlib import Path

#: 快照里存生成表的域。
SECTION = "doc_tables"


def _latest() -> Snapshot | None:
    """最新一份**入库**精简快照。

    直接用 :func:`pdx.verify.latest_compact_snapshot` 而不是自己再写一遍
    「哪份快照算数」的规则 —— 两处各写一份，迟早会出现「verify 认、tables 不认」。
    """
    return latest_compact_snapshot()


@dataclass(frozen=True, slots=True)
class TableDiff:
    """一张表的不一致。"""

    key: str
    doc: str
    line: int
    actual: str
    expected: str


def load_tables(path: Path | None = None) -> dict[str, list[str]]:
    """从快照里取生成表记录（默认取最新的那份入库精简快照）。"""
    snap = Snapshot.load(path) if path is not None else _latest()
    if snap is None:
        return {}
    return snap.sections.get(SECTION, {})


def compare(
    recorded: dict[str, list[str]] | None = None, *, only: str = ""
) -> tuple[list[TableDiff], list[str], list[str]]:
    """核对全部生成表。

    返回 ``(不一致, 快照里缺的表, 快照里有但登记表里没有的表)``。
    第三项是**反向**检查：有人删了生成器规格却没更新快照时看得见。
    """
    recorded = load_tables() if recorded is None else recorded
    diffs: list[TableDiff] = []
    known: set[str] = set()
    for target in docgen.targets():
        if only and only not in target.name:
            continue
        for spec in target.specs:
            key = spec_key(target.name, spec)
            known.add(key)
            want = recorded.get(key)
            if want is None:
                continue
            actual = current_rows(target.path, spec)
            if actual == want:
                continue
            for n in range(max(len(actual), len(want))):
                got = actual[n] if n < len(actual) else "<文档里没有这一行>"
                exp = want[n] if n < len(want) else "<快照里没有这一行>"
                if got != exp:
                    diffs.append(TableDiff(key, target.name, n + 1, got, exp))
    missing = sorted(
        spec_key(t.name, s)
        for t in docgen.targets()
        if not only or only in t.name
        for s in t.specs
        if spec_key(t.name, s) not in recorded
    )
    orphans = sorted(k for k in recorded if k not in known)
    return diffs, missing, orphans


def restore(recorded: dict[str, list[str]] | None = None, *, only: str = "") -> dict[str, int]:
    """按快照里的行把文档表格写回去，返回 ``{表标识: 行数}``。"""
    recorded = load_tables() if recorded is None else recorded
    out: dict[str, int] = {}
    for target in docgen.targets():
        if only and only not in target.name:
            continue
        for spec in target.specs:
            key = spec_key(target.name, spec)
            rows = recorded.get(key)
            if rows is None:
                continue
            if current_rows(target.path, spec) == rows:
                continue
            out[key] = write_rows(target.path, spec, rows)
    return out


__all__ = ["SECTION", "TableDiff", "compare", "load_tables", "restore"]
