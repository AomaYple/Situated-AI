"""从 PDX 文件提取结构化信息。

这是取代原先 ``dump_*.ps1`` 与 ``make_frags.ps1`` 的核心层。所有提取都
走 :mod:`pdx.parser`，因此自动获得 BOM 剥离、引号感知注释、花括号深度
判定、连字符键名支持这几项保证。

统一约定
--------
* **顶层键** = 根块中的赋值键，与缩进无关。
* **字段** = 某个条目块内部出现过的赋值键（即该类型支持的字段名）。
* **条目** = 顶层块本身。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

from .cache import parse_cached
from .model import Assignment, Block, ParsedFile
from .scan import walk_files


@dataclass(slots=True)
class DirExtract:
    """一个数据目录的提取结果。"""

    name: str
    path: Path
    files: int = 0
    #: 顶层条目名 → 出现次数（正常情况下都是 1）
    entries: Counter = field(default_factory=Counter)
    #: ``@变量`` 名 → 出现次数。**不计入 entries** —— 它们是脚本变量而非数据条目。
    #: `coat_of_arms` 目录里有大量这种定义，混入会让条目数虚高。
    variables: Counter = field(default_factory=Counter)
    #: 条目名 → 该条目内出现过的字段集合
    fields: dict[str, set[str]] = field(default_factory=dict)
    #: 各字段被使用的次数
    field_usage: Counter = field(default_factory=Counter)
    #: 带功能前缀的条目：完整键（如 REPLACE:foo）→ 次数
    prefixed: Counter = field(default_factory=Counter)
    #: 解析报错（文件, 消息）
    errors: list[tuple[Path, str]] = field(default_factory=list)
    #: 带 BOM 的文件数
    bom_files: int = 0
    #: 最大嵌套深度
    max_depth: int = 0

    @property
    def unique_entries(self) -> int:
        return len(self.entries)

    @property
    def is_clean(self) -> bool:
        return not self.errors

    def summary(self) -> dict[str, object]:
        return {
            "目录": self.name,
            "文件": self.files,
            "顶层条目": self.unique_entries,
            "@变量": len(self.variables),
            "字段数": len(self.fields),
            "带前缀条目": sum(self.prefixed.values()),
            "带BOM文件": self.bom_files,
            "解析错误": len(self.errors),
            "最大深度": self.max_depth,
        }


def _collect_fields(block: Block) -> Iterator[str]:
    """产出某个条目块**内部**出现过的赋值键（只看第一层）。"""
    for a in block.assignments():
        yield a.key


def extract_file(pf: ParsedFile, result: DirExtract) -> None:
    """把一个已解析文件的内容并入目录级提取结果。"""
    result.files += 1
    if pf.had_bom:
        result.bom_files += 1
    result.max_depth = max(result.max_depth, pf.max_depth())
    for err in pf.errors:
        result.errors.append((Path(pf.path), err))

    for a in pf.top_assignments:
        # @变量：脚本变量，不是数据条目 —— 单独计数，不混入 entries
        if a.is_variable:
            result.variables[a.key] += 1
            continue

        if a.prefix:
            result.prefixed[f"{a.prefix}:{a.key}"] += 1
        else:
            result.entries[a.key] += 1

        if a.is_block:
            fset = result.fields.setdefault(a.key, set())
            for fname in _collect_fields(a.value):
                fset.add(fname)
                result.field_usage[fname] += 1


def extract_dir(path: Path) -> DirExtract:
    """提取一个数据目录（递归其子目录）。"""
    result = DirExtract(name=path.name, path=path)
    if not path.is_dir():
        return result
    for entry in walk_files(path, suffix=".txt"):
        try:
            pf = parse_cached(entry.path)
        except Exception as exc:  # 单文件失败不应中断整轮
            result.errors.append((entry.path, f"未捕获异常: {exc}"))
            continue
        extract_file(pf, result)
    return result


def extract_tree(root: Path) -> dict[str, DirExtract]:
    """提取 root 下每个直接子目录。"""
    out: dict[str, DirExtract] = {}
    if not root.is_dir():
        return out
    for child in sorted(p for p in root.iterdir() if p.is_dir()):
        out[child.name] = extract_dir(child)
    return out


def all_top_keys(root: Path) -> dict[str, list[str]]:
    """``目录名 -> 排序后的顶层条目名列表``。机器可读版的全量索引。"""
    out: dict[str, list[str]] = {}
    for name, res in extract_tree(root).items():
        out[name] = sorted(res.entries)
    return out


def all_field_names(root: Path) -> dict[str, list[str]]:
    """``目录名 -> 该目录下出现过的全部字段名``。"""
    out: dict[str, list[str]] = {}
    for name, res in extract_tree(root).items():
        merged: set[str] = set()
        for fset in res.fields.values():
            merged |= fset
        out[name] = sorted(merged)
    return out


def global_usage(extracts: Iterable[DirExtract]) -> Counter:
    """跨目录汇总某个字段名被用到的总次数（判断字段是否真的在用）。"""
    total: Counter = Counter()
    for e in extracts:
        total.update(e.field_usage)
    return total
