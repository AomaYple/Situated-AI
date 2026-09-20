"""覆盖率门禁：整体下限之外，再给**核心模块**各钉一条下限。

为什么需要它
------------
``pyproject.toml`` 的 ``fail_under = 86`` 是**整体**门禁，而整体数字会掩盖
结构性问题：删掉 200 行 cli.py 的测试、再给某个小模块补 200 行测试，总数
可以纹丝不动。这个仓库里最要紧的几个模块（解析器、断言注册表、归属标记、
表格生成）恰恰都是**大模块**，它们的回退必须单独看得见。

口径
----
* 数据来源就是 ``pytest --cov`` 的那份 JSON（分支覆盖率，与 ``fail_under`` 同源），
  这里**不重新定义**覆盖率是什么；
* 每个模块一条下限，取「实测值向下取整再留 2 个点」—— 留余量是因为
  分支覆盖对用例顺序与随机化（``pytest-randomly``）有轻微敏感性，
  卡在实测值上会让门禁变成噪音源；
* 下限**只许上调**：做了一批测试之后应当把它抬到新的实测值附近。

用法
----
``v3 cov`` 跑整套测试（带覆盖率）并按模块核对下限；``v3 cov --check-only``
只读上一次的数据，不重跑。
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import config

if TYPE_CHECKING:
    from collections.abc import Iterable

#: 模块 → 覆盖率下限（分支覆盖率，%）。**只许上调。**
#:
#: 这些模块是「错了会静默错」的那一类：解析器错了全库数字都错、断言注册表错了
#: 门禁就形同虚设、表格生成错了文档会悄悄漂。其余模块由整体 86% 兜着。
#:
#: 取值口径：首次实跑（2026-09，`v3 cov`）的实测值**向下取整再留 2 个点** ——
#: 分支覆盖对用例顺序（`pytest-randomly`）有轻微敏感性，卡在实测值上会让门禁
#: 变成噪音源。括号里是那次实测值。
FLOORS: dict[str, float] = {
    "pdx/parser.py": 94.0,  # 96.9%
    "pdx/lexer.py": 98.0,  # 100.0%
    "pdx/model.py": 88.0,  # 90.6%
    "pdx/doc_tables.py": 91.0,  # 93.6%
    "pdx/markers.py": 93.0,  # 95.5%
    "pdx/verify.py": 91.0,  # 93.5%
    "pdx/cache.py": 92.0,  # 94.0%
    "pdx/h1.py": 93.0,  # 95.8%（阶段 2 的分析器：解析 + 统计 + 报告）
    "pdx/h1_probe.py": 95.0,  # 98.9%（阶段 2 的探针生成器）
}

#: 门禁使用的覆盖率 JSON（`v3 cov` 每次覆盖写）。
COV_JSON = config.OUT / "cov.json"


@dataclass(frozen=True, slots=True)
class ModuleCoverage:
    """一个模块的实测覆盖率。"""

    module: str
    percent: float
    statements: int

    @property
    def floor(self) -> float | None:
        return FLOORS.get(self.module)

    @property
    def ok(self) -> bool:
        floor = self.floor
        return floor is None or self.percent + 1e-9 >= floor


def run_pytest(*, extra: Iterable[str] = ()) -> int:
    """跑整套测试并写覆盖率 JSON，返回 pytest 退出码。

    **为什么显式给 `-n 4`**：`addopts` 里的默认是 `-n auto`，而本机 16 核下
    "覆盖率 + `-n auto`" 恰好是最差的组合 —— 每个 worker 都要自己写 coverage
    数据、还要各自重跑那份 16 秒的全量分析（xdist 的 worker 不共享解析缓存）。
    实测同一台机器、同一套测试：

    | 配置 | 墙钟 | 结果 |
    |---|---|---|
    | 覆盖率 + `-n auto`（默认） | 376 秒 | 偶发红：worker `INTERNALERROR`、负载敏感用例假红 |
    | 覆盖率 + `-n 4` | 185 秒 | 841 通过 / 8 跳过 / 0 失败 |

    （`pyproject.toml` 里那条 "-n auto 比串行快 58%" 的实测口径是 `--no-cov`，
    与这里不矛盾：不开覆盖率时多 worker 才划算。）
    """
    COV_JSON.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-n",
        "4",
        f"--cov-report=json:{COV_JSON}",
        "--cov",
        *extra,
    ]
    return subprocess.run(cmd, cwd=str(config.REPO), check=False).returncode


def load_coverage(path: Path | None = None) -> list[ModuleCoverage]:
    """读覆盖率 JSON 里的 ``pdx`` 模块（按模块名排序）。"""
    target = path or COV_JSON
    if not target.is_file():
        return []
    data = json.loads(target.read_text(encoding="utf-8"))
    rows: list[ModuleCoverage] = []
    for file, info in data.get("files", {}).items():
        posix = Path(file).as_posix()
        marker = "tools/pdx/"
        index = posix.find(marker)
        if index < 0:
            continue
        rest = posix[index + len(marker) :]
        if not rest.endswith(".py") or "/" in rest:
            continue  # 只算包顶层模块（与 FLOORS 的键一致）
        summary = info.get("summary", {})
        rows.append(
            ModuleCoverage(
                module="pdx/" + rest,
                percent=float(summary.get("percent_covered", 0.0)),
                statements=int(summary.get("num_statements", 0)),
            )
        )
    return sorted(rows, key=lambda r: r.module)


def check(rows: list[ModuleCoverage]) -> list[ModuleCoverage]:
    """返回**不达标**的那些（未登记下限的模块不参与判定）。"""
    return [r for r in rows if r.floor is not None and not r.ok]


def missing_floors(rows: list[ModuleCoverage]) -> list[str]:
    """登记了下限、但这次数据里没有的模块（改名/删文件会让门禁悄悄失效）。"""
    seen = {r.module for r in rows}
    return sorted(m for m in FLOORS if m not in seen)


def total_percent(rows: list[ModuleCoverage]) -> float:
    """整体覆盖率（按语句数加权，与 coverage 自己的口径一致）。"""
    total = sum(r.statements for r in rows)
    if not total:
        return 0.0
    return sum(r.percent * r.statements for r in rows) / total


def overall_floor() -> float:
    """整体下限：直接读 ``pyproject.toml`` 的 ``[tool.coverage.report] fail_under``。

    不在这里再写一遍数字 —— 两个地方各写一份，迟早会出现「pytest 报 86、
    `v3 cov` 报 84」这种自相矛盾的门禁。
    """
    data = tomllib.loads((config.REPO / "pyproject.toml").read_text(encoding="utf-8"))
    return float(data.get("tool", {}).get("coverage", {}).get("report", {}).get("fail_under", 0))


__all__ = [
    "COV_JSON",
    "FLOORS",
    "ModuleCoverage",
    "check",
    "load_coverage",
    "missing_floors",
    "overall_floor",
    "run_pytest",
    "total_percent",
]
