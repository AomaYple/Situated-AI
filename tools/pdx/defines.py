"""defines 专用提取。

取代原先的 ``dump_defines.ps1`` / ``dump_precise.ps1`` / ``extract_defines.ps1``
三个 PowerShell 脚本。

defines 与普通 PDX 数据的区别
-----------------------------
* 顶层是**命名空间块**（大写字母开头，惯例 ``N`` 前缀），不是数据条目
* 块内是**扁平参数**：``KEY = value``，几乎不含嵌套
* 文件中可能混有 ``@变量`` 定义 —— 它们是脚本变量，**不是命名空间**
  （``00_defines.txt`` 顶部有 22 个，误计会让块数从 75 变成 97）
* 参数值分三类：标量、内联列表、嵌套块

覆盖机制
--------
引擎按「命名空间块名合并、参数名覆盖」解析，**与文件名无关**。
证据：``NCamera`` 被 ``jomini/.../camera.txt`` 与 ``game/.../00_graphics.txt``
两个不同文件名声明；``NPops`` 在同一文件里出现两次。

因此 mod 只需在自己的 ``common/defines/`` 里写
``NXXX = { KEY = 新值 }``，**不需要复制整份原版文件**。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import config
from .cache import parse_cached
from .model import Block, Scalar
from .parser import parse_text
from .scan import walk_files

if TYPE_CHECKING:
    from pathlib import Path

#: 参数值的三种形态
SCALAR = "标量"
INLINE_LIST = "内联列表"
NESTED_BLOCK = "嵌套块"


@dataclass(slots=True)
class Param:
    """defines 里的一个参数。"""

    name: str
    kind: str
    value: str = ""            # 标量时是字面量；列表/块时是元素个数说明
    elements: int = 0          # 列表元素数或子键数
    line: int = 0

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {"参数": self.name, "形态": self.kind, "行": self.line}
        if self.kind == SCALAR:
            d["值"] = self.value
        else:
            d["元素数"] = self.elements
        return d


@dataclass(slots=True)
class Namespace:
    """一个命名空间块。"""

    name: str
    file: str
    line: int
    params: list[Param] = field(default_factory=list)
    comment: str = ""

    @property
    def param_names(self) -> list[str]:
        return [p.name for p in self.params]

    @property
    def count(self) -> int:
        return len(self.params)

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "命名空间": self.name,
            "文件": self.file,
            "行": self.line,
            "参数数": self.count,
            "参数": [p.name for p in self.params],
        }
        if self.comment:
            d["前置注释"] = self.comment
        return d


@dataclass(slots=True)
class DefinesReport:
    """defines 全量提取结果。"""

    namespaces: list[Namespace] = field(default_factory=list)
    variables: list[tuple[str, str, int]] = field(default_factory=list)
    #: 文件 -> 块数
    per_file: Counter = field(default_factory=Counter)
    #: 参数名 -> 出现次数（跨命名空间）
    param_usage: Counter = field(default_factory=Counter)
    #: 同一个命名空间名出现在几个文件里（合并机制的直接证据）
    namespace_files: dict[str, list[str]] = field(default_factory=dict)

    @property
    def unique_namespaces(self) -> list[str]:
        return sorted({n.name for n in self.namespaces})

    @property
    def total_params(self) -> int:
        return sum(n.count for n in self.namespaces)

    def get(self, name: str) -> list[Namespace]:
        return [n for n in self.namespaces if n.name == name]

    def summary(self) -> dict[str, object]:
        return {
            "命名空间块数": len(self.namespaces),
            "去重命名空间": len(self.unique_namespaces),
            "参数总数": self.total_params,
            "@变量数": len(self.variables),
            "涉及文件": len(self.per_file),
            "跨文件重复的命名空间": {
                k: v for k, v in self.namespace_files.items() if len(v) > 1
            },
        }


def _classify(block: Block) -> list[Param]:
    """判定块内每个参数的形态。

    返回值原先是个 ``(str, list[Param])`` 元组，但那个字符串**恒为空**，
    调用方也从没读过它 —— 是重构留下的残骸，已去掉。
    """
    params: list[Param] = []
    for a in block.assignments():
        v = a.value
        if isinstance(v, Block):
            subs = len(list(v.assignments()))
            bare = sum(1 for _ in v.scalars())
            if subs == 0 and bare > 0:
                params.append(Param(a.key, INLINE_LIST, elements=bare, line=a.line))
            else:
                params.append(Param(a.key, NESTED_BLOCK, elements=subs, line=a.line))
        elif isinstance(v, Scalar):
            params.append(Param(a.key, SCALAR, value=v.text, line=a.line))
        else:
            # 空值：``KEY =`` 后面什么都没有
            params.append(Param(a.key, SCALAR, value="", line=a.line))
    return params


def extract_defines(root: Path | None = None) -> DefinesReport:
    """提取一个 defines 目录下的全部命名空间与参数。

    ``root`` 默认为 ``game/common/defines``。传 ``jomini/common/defines``
    可提取 Jomini 层。
    """
    root = root or (config.GAME / "common" / "defines")
    report = DefinesReport()
    if not root.is_dir():
        return report

    for f in sorted(walk_files(root, suffix=".txt"), key=lambda e: str(e.path)):
        pf = parse_cached(f.path)
        rel = str(f.path.relative_to(root)).replace("\\", "/")

        for a in pf.top_assignments:
            # @变量：脚本变量，不是命名空间
            if a.is_variable:
                val = a.value.text if isinstance(a.value, Scalar) else ""
                report.variables.append((a.key, val, a.line))
                continue

            if not isinstance(a.value, Block):
                continue
            # 只有大写开头的块算命名空间
            if not a.key[:1].isupper():
                continue

            params = _classify(a.value)
            ns = Namespace(name=a.key, file=rel, line=a.line, params=params)
            report.namespaces.append(ns)
            report.per_file[rel] += 1
            report.namespace_files.setdefault(a.key, []).append(rel)
            for p in params:
                report.param_usage[p.name] += 1

    return report


def extract_all_defines() -> dict[str, DefinesReport]:
    """同时提取游戏层与 Jomini 层。"""
    return {
        "game": extract_defines(config.GAME / "common" / "defines"),
        "jomini": extract_defines(config.JOMINI / "common" / "defines"),
    }


def overlay(vanilla: DefinesReport, mod_text: str) -> dict[str, object]:
    """预览一段 mod defines 文本会覆盖哪些原版参数。

    用于「写 mod 前先确认覆盖范围」，避免盲目复制整份原版文件。
    """
    pf = parse_text(mod_text, "<mod>")
    result: list[dict[str, object]] = []
    for a in pf.top_assignments:
        if a.is_variable or not isinstance(a.value, Block):
            continue
        target = vanilla.get(a.key)
        if not target:
            result.append({"命名空间": a.key, "状态": "原版不存在（新建）",
                           "覆盖参数": [], "新增参数": a.value.keys()})
            continue
        existing = set()
        for ns in target:
            existing.update(ns.param_names)
        mine = set(a.value.keys())
        result.append({
            "命名空间": a.key,
            "状态": "与原版合并",
            "覆盖参数": sorted(mine & existing),
            "新增参数": sorted(mine - existing),
            "原版参数数": len(existing),
        })
    return {"命名空间数": len(result), "明细": result}
