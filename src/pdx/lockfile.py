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
   （先按当前平台、解释器与已请求 extras 求值；条件不成立的依赖排除，
   任何适用依赖缺失、版本冲突或元数据读取失败都中止生成）；
3. 按名字排序写成 ``requirements.lock``：``name==version``，外加一段文件头
   说明生成方式与解释器版本。

口径与边界
----------
* 锁描述的是**本机解析出来的闭包**，含平台相关依赖（例如 Windows 上会有
  ``colorama``）。在别的平台上装它会多装一个无害的包，不会少装；
* 标记求值由 `packaging` 按 PEP 508 解析，支持平台、版本、AND/OR；
  未请求的 extra 不纳入，非法标记明确报错。Windows 锁只承诺 Windows 环境。
* ``v3 lock`` 默认**核对**，``--write`` 在仓库根目录暂存并原子替换现有锁。
"""

from __future__ import annotations

import sys
import tempfile
import tomllib
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, requires, version
from pathlib import Path
from typing import TYPE_CHECKING

from packaging.markers import Marker
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import InvalidName, canonicalize_name
from packaging.version import InvalidVersion, Version

from . import config

if TYPE_CHECKING:
    from collections.abc import Iterable

#: 锁文件名（仓库根目录）。
LOCK_FILE = "requirements.lock"

#: 头部标记：只认自己写的文件，别人的 `requirements.lock` 不去动。
HEADER = "# 由 `v3 lock --write` 生成 —— 手改会被 `v3 lock`（不带参数）对账时报出来。"


def requires_python(root: Path | None = None) -> str:
    """读取 ``pyproject.toml`` 中唯一维护的 Python 版本要求。"""
    base = config.REPO if root is None else root
    project = tomllib.loads((base / "pyproject.toml").read_text(encoding="utf-8")).get(
        "project", {}
    )
    requirement = project.get("requires-python")
    if not isinstance(requirement, str) or not requirement.strip():
        raise ValueError("pyproject.toml 缺少有效的 project.requires-python")
    return requirement.strip()


def current_python_version() -> tuple[int, int, int]:
    """当前生成器解释器的稳定三段版本。"""
    return (sys.version_info.major, sys.version_info.minor, sys.version_info.micro)


def validate_python_version(
    actual: tuple[int, int, int] | None = None,
    requirement: str | None = None,
) -> None:
    """拒绝不满足项目合同的解释器，避免生成不可用的锁。"""
    version = current_python_version() if actual is None else actual
    expected = requires_python() if requirement is None else requirement
    if SpecifierSet(expected).contains(".".join(map(str, version)), prereleases=True):
        return
    actual_text = ".".join(map(str, version))
    raise RuntimeError(
        f"锁生成器解释器版本不满足项目要求：实际 Python {actual_text}；要求 {expected}"
    )


def normalize(name: str) -> str:
    """包名规范化（``Foo_Bar`` 与 ``foo-bar`` 是同一个包）。"""
    return canonicalize_name(name.strip())


def _marker_allows(marker: Marker | str, *, extra: str = "") -> bool:
    """使用 PEP 508 的 AND/OR、平台和版本语义；坏标记明确报错。"""
    return (Marker(marker) if isinstance(marker, str) else marker).evaluate({"extra": extra})


def _active_requirements(
    specs: Iterable[str], *, extras: Iterable[str] = ("",)
) -> list[Requirement]:
    """过滤不适用的 PEP 508 依赖，保留版本约束和 extras。"""
    out: list[Requirement] = []
    contexts = tuple(extras)
    for raw in specs:
        line = raw.strip()
        if not line:
            continue
        requirement = Requirement(line)
        marker = requirement.marker
        if marker is None or any(_marker_allows(marker, extra=extra) for extra in contexts):
            out.append(requirement)
    return out


def _direct_requirements() -> list[Requirement]:
    data = tomllib.loads((config.REPO / "pyproject.toml").read_text(encoding="utf-8"))
    project = data.get("project", {})
    runtime = _active_requirements(project.get("dependencies", []))
    development = _active_requirements(
        project.get("optional-dependencies", {}).get("dev", []), extras=("", "dev")
    )
    return runtime + development


def direct_requirements() -> list[str]:
    """``pyproject.toml`` 直接依赖的包名及所请求的 extras。"""
    return [
        f"{req.name}[{','.join(sorted(req.extras))}]" if req.extras else req.name
        for req in _direct_requirements()
    ]


def resolve() -> dict[str, str]:
    """本机已安装的依赖闭包：``{规范化包名: 版本}``。"""
    pinned: dict[str, str] = {}
    queue = _direct_requirements()
    direct_names = {normalize(requirement.name) for requirement in queue}
    expanded: dict[str, set[str]] = {}
    while queue:
        requirement = queue.pop()
        name = requirement.name
        key = normalize(name)
        if key not in pinned:
            try:
                pinned[key] = version(name)
            except PackageNotFoundError:
                kind = "直接依赖" if key in direct_names else "依赖闭包成员"
                raise RuntimeError(f"{kind}未安装，不能生成不完整锁：{name}") from None
        installed = pinned[key]
        if requirement.specifier and not requirement.specifier.contains(
            installed, prereleases=True
        ):
            raise RuntimeError(f"已安装 {name}=={installed} 不满足依赖约束 {requirement}")
        contexts = {"", *requirement.extras} - expanded.get(key, set())
        if not contexts:
            continue
        # Process newly requested extras even when the base distribution was
        # already visited. Unknown metadata never proves an empty closure.
        children = requires(name) or []
        expanded.setdefault(key, set()).update(contexts)
        queue.extend(_active_requirements(children, extras=contexts))
    return dict(sorted(pinned.items()))


def render(pinned: dict[str, str]) -> str:
    """把闭包渲染成锁文件文本（含头部说明）。"""
    requirement = requires_python()
    interpreter = current_python_version()
    lines = [
        HEADER,
        "#",
        "# 口径：从 pyproject.toml 的直接依赖出发，沿 Requires-Dist 展开本机已安装的闭包。",
        "# 它描述的是**这台机器解析出来的版本组合**，含平台相关依赖（如 Windows 上的 colorama）。",
        "# `v3 lock`（不带参数）会拿它与当前环境对账；不一致时先想清楚再 `--write`。",
        f"# Python 要求：{requirement}",
        f"# 解释器：Python {'.'.join(map(str, interpreter))}",
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
    lines = target.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != HEADER:
        return {}
    requirement_line = next((line for line in lines if line.startswith("# Python 要求：")), None)
    interpreter_line = next((line for line in lines if line.startswith("# 解释器：Python ")), None)
    if requirement_line is None or interpreter_line is None:
        return {}
    recorded_requirement = requirement_line.removeprefix("# Python 要求：").strip()
    if recorded_requirement != requires_python():
        return {}
    try:
        recorded_version = tuple(
            int(part)
            for part in interpreter_line.removeprefix("# 解释器：Python ").strip().split(".")
        )
        if len(recorded_version) != 3:
            return {}
        validate_python_version(recorded_version, recorded_requirement)
    except ValueError, RuntimeError:
        return {}
    out: dict[str, str] = {}
    for line in lines:
        if not line or line.startswith("#"):
            continue
        name, separator, ver = line.partition("==")
        if not separator:
            return {}
        try:
            key = canonicalize_name(name.strip(), validate=True)
            Version(ver)
        except InvalidName, InvalidVersion:
            return {}
        if key in out:
            return {}
        out[key] = ver.strip()
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
    validate_python_version()
    data = resolve() if pinned is None else pinned
    text = render(data)
    destination = config.REPO / LOCK_FILE
    with tempfile.TemporaryDirectory(
        dir=destination.parent, prefix=f".{destination.name}."
    ) as temp:
        staged = Path(temp) / destination.name
        staged.write_text(text, encoding="utf-8", newline="\n")
        staged.replace(destination)
    return len(data)


__all__ = [
    "HEADER",
    "LOCK_FILE",
    "Drift",
    "compare",
    "current_python_version",
    "direct_requirements",
    "normalize",
    "read",
    "render",
    "requires_python",
    "resolve",
    "validate_python_version",
    "write",
]
