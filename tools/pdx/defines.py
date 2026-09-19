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
from .doc_tables import TableSpec
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
    value: str = ""  # 标量时是字面量；列表/块时是元素个数说明
    elements: int = 0  # 列表元素数或子键数
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

    @property
    def counts(self) -> dict[str, int]:
        """按形态分组的参数计数（``{标量: n, 内联列表: n, 嵌套块: n}``）。

        doc 05 的 §2.1/§2.2/§2.5/§2.6 四张表都要这三项，
        口径统一由 :func:`_classify` 决定，不在这里重算。
        """
        out = {SCALAR: 0, INLINE_LIST: 0, NESTED_BLOCK: 0}
        for p in self.params:
            out[p.kind] = out.get(p.kind, 0) + 1
        return out

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
            "跨文件重复的命名空间": {k: v for k, v in self.namespace_files.items() if len(v) > 1},
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
            result.append(
                {
                    "命名空间": a.key,
                    "状态": "原版不存在（新建）",
                    "覆盖参数": [],
                    "新增参数": a.value.keys(),
                }
            )
            continue
        existing = set()
        for ns in target:
            existing.update(ns.param_names)
        mine = set(a.value.keys())
        result.append(
            {
                "命名空间": a.key,
                "状态": "与原版合并",
                "覆盖参数": sorted(mine & existing),
                "新增参数": sorted(mine - existing),
                "原版参数数": len(existing),
            }
        )
    return {"命名空间数": len(result), "明细": result}


# ── doc 05 的表格：由本模块生成，而不是手抄 ──────────────────
#: doc 05 里**由本模块生成**的 5 张表。键是表头首行（用于定位），值是该表的数据行。
#:
#: 为什么要有这个：这 5 张表原先由一批已退休的 PowerShell 脚本产出，之后再没人
#: 重跑过 —— 于是它们整整落后了一个游戏版本（1.14.3 给 NMilitary +1、
#: NDiplomacy +39 个参数，总数 3434 应当变 3488，而文档里一直写着 3434）。
#: 现在口径只有一处（:func:`_classify`），表格可以随时重算。
DOC_TABLES: tuple[str, ...] = (
    "| Namespace | Blocks | Params | File(s) |",
    "| 文件（相对 `common\\defines\\`） | 顶层块数 | 标量参数 | 内联列表 | 嵌套块 | 条目合计 |",
    "| File | Namespace block | Line | Scalar | Inline list | Nested | Total |",
    "| # | 命名空间 | 块起始行 | 该命名空间的块数 | 参数合计 |",
    "| 命名空间块 | 起始行 | 标量 | 内联列表 | 嵌套 | 合计 |",
)


def doc_table_rows() -> dict[str, list[str]]:
    """生成 doc 05 五张表的**数据行**（含合计行），键为表头首行。

    与 :data:`DOC_TABLES` 一一对应；找不到某个表时由调用方报错，
    不静默跳过 —— 静默跳过正是这类生成器腐烂的方式。
    """
    report = extract_defines()
    by_file: dict[str, list[Namespace]] = {}
    for ns in report.namespaces:
        by_file.setdefault(ns.file, []).append(ns)

    rows: dict[str, list[str]] = {h: [] for h in DOC_TABLES}

    # §1.6 —— 按命名空间名聚合（同名多块累加）
    agg: dict[str, list[Namespace]] = {}
    for ns in report.namespaces:
        agg.setdefault(ns.name, []).append(ns)
    for name in sorted(agg):
        group = agg[name]
        params = sum(ns.count for ns in group)
        files = ", ".join(sorted({ns.file for ns in group}))
        rows[DOC_TABLES[0]].append(f"| `{name}` | {len(group)} | {params} | {files} |")

    # §2.1 —— 逐文件
    tb = ts = ti = tn = 0
    for rel in sorted(by_file):
        b = len(by_file[rel])
        s = i = n = 0
        for ns in by_file[rel]:
            s += ns.counts[SCALAR]
            i += ns.counts[INLINE_LIST]
            n += ns.counts[NESTED_BLOCK]
        tb += b
        ts += s
        ti += i
        tn += n
        rows[DOC_TABLES[1]].append(f"| `{rel}` | {b} | {s} | {i} | {n} | **{s + i + n}** |")
    rows[DOC_TABLES[1]].append(
        f"| **合计** | **{tb}** | **{ts}** | **{ti}** | **{tn}** | **{ts + ti + tn}** |"
    )

    # §2.2 —— 逐块
    for ns in report.namespaces:
        s = ns.counts[SCALAR]
        i = ns.counts[INLINE_LIST]
        n = ns.counts[NESTED_BLOCK]
        rows[DOC_TABLES[2]].append(
            f"| `{ns.file}` | `{ns.name}` | {ns.line} | {s} | {i} | {n} | {s + i + n} |"
        )

    # §2.5 / §2.6 —— 单文件的两张表
    for header, rel in ((DOC_TABLES[3], "00_defines.txt"), (DOC_TABLES[4], "00_graphics.txt")):
        groups: dict[str, list[Namespace]] = {}
        for ns in by_file.get(rel, []):
            groups.setdefault(ns.name, []).append(ns)
        total_blocks = total_params = 0
        for idx, (name, group) in enumerate(groups.items(), start=1):
            line_list = ", ".join(str(ns.line) for ns in group)
            counts = [ns.count for ns in group]
            total_blocks += len(group)
            total_params += sum(counts)
            if header == DOC_TABLES[3]:
                if len(group) == 1:
                    rows[header].append(f"| {idx} | `{name}` | {line_list} | 1 | {counts[0]} |")
                else:
                    plus = " + ".join(str(p) for p in counts)
                    rows[header].append(
                        f"| {idx} | `{name}` | {line_list} | **{len(group)}** | "
                        f"{plus} = {sum(counts)} |"
                    )
            else:
                s = i = n = 0
                for ns in group:
                    s += ns.counts[SCALAR]
                    i += ns.counts[INLINE_LIST]
                    n += ns.counts[NESTED_BLOCK]
                rows[header].append(f"| `{name}` | {line_list} | {s} | {i} | {n} | {s + i + n} |")
        if header == DOC_TABLES[3]:
            rows[header].append(f"| | **合计** | | **{total_blocks} 块** | **{total_params}** |")
        else:
            s = i = n = 0
            for ns in by_file.get(rel, []):
                s += ns.counts[SCALAR]
                i += ns.counts[INLINE_LIST]
                n += ns.counts[NESTED_BLOCK]
            rows[header].append(f"| | | **{s}** | **{i}** | **{n}** | **{s + i + n}** |")

    return rows


#: doc 05 §3.2 的表头：``NAI`` 参数按命名前缀分组。
#:
#: 这张表**曾经号称「脚本直接落盘的」而实际无人重跑** —— doc 05 §1 里写着
#: 「由脚本机械生成的表头保持英文（如 ``Namespace block``、``Leading prefix``）」，
#: 但产出它的 PowerShell 脚本早已退休，表还留在文档里。实测漂了 3 处
#: （``DIPLO_*`` 209→210、``SELL_*`` 4→6、``STRATEGIC_*`` 2→3，合计 1,013→1,017）。
#: 现在接进 :mod:`pdx.docgen`，那句声明才重新成立。
PREFIX_TABLE = "| Leading prefix | Param count |"

#: 无下划线的参数归到这一组（实测 NAI 里没有这种，但留着以防原版改名）
NO_PREFIX = "（无前缀）"


def prefix_rows() -> list[str]:
    """``NAI`` 命名空间的参数按「第一个下划线之前」聚类的计数。

    口径：``AI_FOO`` → ``AI_*``；无下划线的归 :data:`NO_PREFIX`。
    排序：计数降序，同计数按前缀名升序 —— **确定性**排序。
    文档原先的并列顺序是随机的（``FLEET_*`` 30 排在 ``AUTONOMOUS_*`` 30 之前），
    照抄那个顺序会让每次重算都产生无意义的 diff。
    """
    groups: Counter[str] = Counter()
    for ns in extract_defines().get("NAI"):
        for p in ns.params:
            groups[f"{p.name.split('_', 1)[0]}_*" if "_" in p.name else NO_PREFIX] += 1
    return [
        f"| `{name}` | {n:,} |"
        for name, n in sorted(groups.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def doc_table_specs() -> list[TableSpec]:
    """doc 05 的表的登记表（供 ``v3 tables`` 统一驱动）。

    生成逻辑仍在本模块（它拥有 defines 的提取口径），但**替换算法**
    交给 :mod:`pdx.doc_tables` —— 同一套机制也用在 doc 08 / doc 19 上。

    包含 :data:`PREFIX_TABLE` —— 它此前是一张「无人重跑」的手抄表。
    """
    rows = doc_table_rows()
    specs: list[TableSpec] = [
        TableSpec(
            name=f"doc05 表{n}",
            header=header,
            # 用默认参数把 header 绑进闭包 —— 直接在 lambda 里捕获会拿到循环末值
            rows=lambda h=header: list(rows[h]),  # type: ignore[misc]
        )
        for n, header in enumerate(DOC_TABLES, start=1)
    ]
    specs.append(TableSpec(name="doc05 参数前缀分组", header=PREFIX_TABLE, rows=prefix_rows))
    return specs
