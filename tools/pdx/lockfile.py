"""依赖锁：把「本机这套环境到底是哪几个版本」写成可核对的文件。

为什么需要它
------------
``pyproject.toml`` 里全是下限（``typer>=0.27`` 这种）。下限保证「装得上」，
**不保证「装出来是同一套」**：CI 与本地、今天与三个月后，解析出来的
pytest / ruff / hypothesis 版本可能各不相同，于是「本地过了、CI 红」或者
反过来的事就会发生 —— 而这类失败最难查，因为代码一行没改。

做法
----
不引入 pip-tools / uv（那是又一个需要装、需要维护的工具）：

1. 从 ``pyproject.toml`` 读出**直接依赖**（运行期 + ``dev`` extra）；
2. 用 :mod:`importlib.metadata` 沿着 ``Requires-Dist`` 递归展开**闭包**
   （只统计**本机真的装了**的那些 —— 没装的多半是别的平台/别的 Python 版本的
   条件依赖，锁里不该凭空写一个版本号）;
3. 按名字排序写成 ``requirements.lock``：``name==version``，外加一段文件头
   说明生成方式与解释器版本。

口径与边界
----------
* 锁描述的是**本机解析出来的闭包**，含平台相关依赖（例如 Windows 上会有
  ``colorama``）。在别的平台上装它会多装一个无害的包，不会少装；
* 判定「哪些包该进锁」时只做**保守的**标记求值：``extra ==`` 一律跳过
  （可选额外依赖没被请求），``python_version`` 按当前解释器比较，
  其余奇奇怪怪的标记一律**当作成立**（宁可多写一行，不可漏）；
* ``v3 lock`` 默认**核对**，``--write`` 才写盘 —— 与 ``v3 tables`` 同一套约定：
  门禁不该顺手改文件。
"""

from __future__ import annotations

import re
import sys
import tomllib
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, requires, version
from pathlib import Path
from typing import TYPE_CHECKING

from . import config

if TYPE_CHECKING:
    from collections.abc import Iterable

#: 锁文件名（仓库根目录）。
LOCK_FILE = "requirements.lock"

#: 头部标记：只认自己写的文件，别人的 `requirements.lock` 不去动。
HEADER = "# 由 `v3 lock --write` 生成 —— 手改会被 `v3 lock`（不带参数）对账时报出来。"

_NAME = re.compile(r"[A-Za-z0-9._-]+")
_PY_MARKER = re.compile(r"""python_version\s*(==|>=|<=|>|<|!=)\s*["']([\d.]+)["']""")


def normalize(name: str) -> str:
    """包名规范化（``Foo_Bar`` 与 ``foo-bar`` 是同一个包）。"""
    return name.strip().lower().replace("_", "-")


def _marker_allows(marker: str) -> bool:
    """保守地判断环境标记是否成立。

    * ``extra == ...`` → 不成立（可选额外依赖没被请求）；
    * ``python_version`` → 按当前解释器比较；
    * 其它 → **当作成立**（宁可多写一行，也不漏掉一个真依赖）。
    """
    if "extra" in marker:
        return False
    current = f"{sys.version_info.major}.{sys.version_info.minor}"
    verdict = True
    for op, want in _PY_MARKER.findall(marker):
        got = tuple(int(x) for x in current.split("."))
        ref = tuple(int(x) for x in want.split("."))
        verdict = (
            verdict
            and {
                "==": got == ref,
                "!=": got != ref,
                ">=": got >= ref,
                "<=": got <= ref,
                ">": got > ref,
                "<": got < ref,
            }[op]
        )
    return verdict


def _requirement_names(specs: Iterable[str]) -> list[str]:
    """从 PEP 508 依赖串里取包名（丢掉版本号、extra、标记）。"""
    out: list[str] = []
    for raw in specs:
        line = raw.strip()
        if not line:
            continue
        marker = line.split(";", 1)[1] if ";" in line else ""
        if marker and not _marker_allows(marker):
            continue
        match = _NAME.match(line)
        if match:
            out.append(match.group(0))
    return out


def direct_requirements() -> list[str]:
    """``pyproject.toml`` 里的直接依赖（运行期 + ``dev`` extra）。"""
    data = tomllib.loads((config.REPO / "pyproject.toml").read_text(encoding="utf-8"))
    project = data.get("project", {})
    specs = list(project.get("dependencies", []))
    specs += list(project.get("optional-dependencies", {}).get("dev", []))
    return _requirement_names(specs)


def resolve() -> dict[str, str]:
    """本机已安装的依赖闭包：``{规范化包名: 版本}``。"""
    pinned: dict[str, str] = {}
    queue = direct_requirements()
    while queue:
        name = queue.pop()
        key = normalize(name)
        if key in pinned:
            continue
        try:
            pinned[key] = version(name)
        except PackageNotFoundError:
            continue  # 条件依赖（别的平台 / 别的 Python）没装，锁里不写
        try:
            children = requires(name) or []
        except Exception:  # pragma: no cover - 元数据损坏的极端情况
            children = []
        queue.extend(_requirement_names(children))
    return dict(sorted(pinned.items()))


def render(pinned: dict[str, str]) -> str:
    """把闭包渲染成锁文件文本（含头部说明）。"""
    lines = [
        HEADER,
        "#",
        "# 口径：从 pyproject.toml 的直接依赖出发，沿 Requires-Dist 展开本机已安装的闭包。",
        "# 它描述的是**这台机器解析出来的版本组合**，含平台相关依赖（如 Windows 上的 colorama）。",
        "# `v3 lock`（不带参数）会拿它与当前环境对账；不一致时先想清楚再 `--write`。",
        f"# 解释器：Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "",
    ]
    lines += [f"{name}=={ver}" for name, ver in pinned.items()]
    return "\n".join(lines) + "\n"


def read(path: str | Path | None = None) -> dict[str, str]:
    """读锁文件；文件不存在或不是本工具生成的，返回空字典。

    `path` 给相对名时按仓库根解析（默认就是 `requirements.lock`），
    也给绝对路径 —— 测试拿它读临时文件。
    """
    target = Path(path) if path is not None else config.REPO / LOCK_FILE
    if not target.is_absolute():
        target = config.REPO / target
    if not target.is_file():
        return {}
    text = target.read_text(encoding="utf-8")
    if HEADER not in text:
        return {}
    out: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        name, _, ver = line.partition("==")
        if name and ver:
            out[normalize(name)] = ver.strip()
    return dict(sorted(out.items()))


@dataclass(frozen=True, slots=True)
class Drift:
    """锁与当前环境的一处差异。"""

    name: str
    locked: str
    actual: str

    @property
    def kind(self) -> str:
        if not self.locked:
            return "新增（锁里没有）"
        if not self.actual:
            return "多余（环境里没有）"
        return "版本不同"


def compare(pinned: dict[str, str], locked: dict[str, str]) -> list[Drift]:
    """比较两份闭包，返回全部差异（按包名排序）。"""
    out: list[Drift] = []
    for name in sorted(set(pinned) | set(locked)):
        actual = pinned.get(name, "")
        was = locked.get(name, "")
        if actual != was:
            out.append(Drift(name, was, actual))
    return out


def write(pinned: dict[str, str] | None = None) -> int:
    """写锁文件，返回写入的条目数。"""
    data = resolve() if pinned is None else pinned
    (config.REPO / LOCK_FILE).write_text(render(data), encoding="utf-8", newline="\n")
    return len(data)


__all__ = [
    "HEADER",
    "LOCK_FILE",
    "Drift",
    "compare",
    "direct_requirements",
    "normalize",
    "read",
    "render",
    "resolve",
    "write",
]
