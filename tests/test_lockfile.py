"""依赖锁的测试。

要证明的性质
-----------
1. **锁与 pyproject 对得上**：直接依赖一条不少（少一条 = 有人加了依赖却忘了
   重新生成锁，锁就从「可复现」退化成「看着像」）；
2. **锁文件可解析**：格式稳定、没有重复条目 —— `read()` 是唯一的解析入口，
   它认不出自己的输出就说明渲染或解析有一边坏了；
3. **按 PEP 508 解析闭包**：按平台、解释器和已请求 extras 选择适用依赖，
   核对直接和传递依赖的版本约束。

⚠️ 这里**不**比较版本号是否等于本机当前版本：CI 是按 `pyproject.toml` 的
声明现解析的，与「这台机器锁住的组合」本来就可能不同。版本对账是本地命令
`v3 lock`（不带参数）的活，它的输出是给人看的。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from pdx import lockfile

pytestmark = pytest.mark.unit


def _project_dependencies(tmp_path, monkeypatch, *specs: str) -> None:
    (tmp_path / "pyproject.toml").write_text(
        f"[project]\ndependencies = {json.dumps(specs)}\n", encoding="utf-8"
    )
    monkeypatch.setattr(lockfile.config, "REPO", tmp_path)


def test_锁文件存在且可解析() -> None:
    locked = lockfile.read()
    assert locked, f"{lockfile.LOCK_FILE} 读不出来（文件缺失或头部标记被改）"
    assert all(name and ver for name, ver in locked.items())
    assert len(set(locked)) == len(locked), "锁里有重复条目"


@pytest.mark.parametrize("version", [(3, 14, 7), (3, 15, 2), (3, 15, 3)])
def test_锁生成器版本合同(version) -> None:
    requirement = lockfile.requires_python()
    if version == (3, 15, 2):
        lockfile.validate_python_version(version, requirement)
    else:
        with pytest.raises(RuntimeError, match=r"要求 ==3\.15\.2"):
            lockfile.validate_python_version(version, requirement)


def test_锁头记录_python_要求和生成解释器() -> None:
    text = lockfile.render({"sample-package": "1.0"})
    assert "# Python 要求：==3.15.2" in text
    assert "# 解释器：Python " in text


def test_旧解释器生成的锁不被静默接受(tmp_path) -> None:
    target = tmp_path / lockfile.LOCK_FILE
    current = ".".join(map(str, lockfile.current_python_version()))
    text = lockfile.render({"sample-package": "1.0"}).replace(
        f"# 解释器：Python {current}", "# 解释器：Python 3.14.7"
    )
    target.write_text(text, encoding="utf-8", newline="\n")
    assert lockfile.read(target) == {}


def test_直接依赖一条不少() -> None:
    locked = lockfile.read()
    installed = lockfile.resolve()
    missing = [
        name
        for name in lockfile.direct_requirements()
        if lockfile.normalize(name) in installed and lockfile.normalize(name) not in locked
    ]
    assert not missing, f"这些直接依赖没进锁（跑 `v3 lock --write`）：{missing}"


def test_闭包包含运行期依赖() -> None:
    pinned = lockfile.resolve()
    assert "typer" in pinned
    assert "rich" in pinned
    assert pinned["typer"] == lockfile.resolve()["typer"], "两次解析应当一致"


def test_渲染与解析可以往返(tmp_path) -> None:
    pinned = lockfile.resolve()
    target = tmp_path / "requirements.lock"
    target.write_text(lockfile.render(pinned), encoding="utf-8", newline="\n")
    assert lockfile.read(target) == pinned


def test_只认自己生成的文件(tmp_path) -> None:
    """别人手写的 requirements.txt 不会被误当成锁。"""
    target = tmp_path / "requirements.txt"
    target.write_text("typer\nrich\n", encoding="utf-8")
    assert lockfile.read(target) == {}


@pytest.mark.parametrize("invalid_line", ["Sample_Package==1.0", "malformed row"])
def test_lock_rejects_duplicate_and_malformed_entries(tmp_path, invalid_line: str) -> None:
    target = tmp_path / lockfile.LOCK_FILE
    text = lockfile.render({"sample-package": "1.0"})
    target.write_text(f"{text}{invalid_line}\n", encoding="utf-8", newline="\n")
    assert lockfile.read(target) == {}


def test_failed_replace_preserves_previous_lock(tmp_path, monkeypatch) -> None:
    target = tmp_path / lockfile.LOCK_FILE
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = "==3.15.2"\n', encoding="utf-8"
    )
    monkeypatch.setattr(lockfile.config, "REPO", tmp_path)
    lockfile.write({"sample-package": "1.0"})
    previous = target.read_bytes()

    def deny_replace(self: Path, destination: Path) -> Path:
        raise PermissionError(destination)

    with monkeypatch.context() as denied:
        denied.setattr(Path, "replace", deny_replace)
        with pytest.raises(PermissionError):
            lockfile.write({"sample-package": "2.0"})
    assert target.read_bytes() == previous
    assert {path.name for path in tmp_path.iterdir()} == {"pyproject.toml", lockfile.LOCK_FILE}


@pytest.mark.parametrize("direct_mismatch", [True, False])
def test_installed_versions_must_satisfy_active_requirements(
    tmp_path, monkeypatch, direct_mismatch: bool
) -> None:
    root = "situated-ai-lock-fixture-root"
    child = "situated-ai-lock-fixture-child"
    declaration = f"{root}>=2" if direct_mismatch else root
    _project_dependencies(tmp_path, monkeypatch, declaration)
    for name in (root, child):
        distribution = tmp_path / f"{name.replace('-', '_')}-1.0.dist-info"
        distribution.mkdir()
        metadata = f"Metadata-Version: 2.4\nName: {name}\nVersion: 1.0\n"
        if name == root:
            metadata += f"Requires-Dist: {child}>=2\n"
        (distribution / "METADATA").write_text(metadata, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(RuntimeError, match=rf"{root if direct_mismatch else child}.*>=2"):
        lockfile.resolve()


@pytest.mark.parametrize(
    ("marker", "expected"),
    [
        ("extra == 'dev'", False),
        ('python_version < "3.11"', False),
        ('python_version >= "3.11"', True),
        ('sys_platform == "win32"', sys.platform == "win32"),
    ],
)
def test_PEP508标记求值(marker: str, expected: bool) -> None:
    assert lockfile._marker_allows(marker) is expected


def test_包名规范化() -> None:
    assert lockfile.normalize("PyTest_Cov") == "pytest-cov"
    assert lockfile.normalize(" foo-bar ") == "foo-bar"


def test_差异检测能认出三种情况() -> None:
    pinned = {"a": "2", "b": "1", "c": "3"}
    locked = {"a": "1", "b": "1", "d": "9"}
    kinds = {d.name: d.kind for d in lockfile.compare(pinned, locked)}
    assert kinds == {"a": "版本不同", "c": "新增（锁里没有）", "d": "多余（环境里没有）"}


@pytest.mark.parametrize("error", [OSError("metadata unreadable"), ValueError("bad metadata")])
def test_dependency_metadata_failure_is_not_an_empty_closure(
    tmp_path, monkeypatch, error: Exception
) -> None:
    _project_dependencies(tmp_path, monkeypatch, "fixture")
    monkeypatch.setattr(lockfile, "version", lambda _name: "1.0")

    def broken_requires(_name: str) -> list[str]:
        raise error

    monkeypatch.setattr(lockfile, "requires", broken_requires)
    with pytest.raises(type(error), match=str(error)):
        lockfile.resolve()


def test_missing_direct_dependency_is_not_an_empty_closure(tmp_path, monkeypatch) -> None:
    _project_dependencies(tmp_path, monkeypatch, "fixture")

    def missing(_name: str) -> str:
        raise lockfile.PackageNotFoundError("fixture")

    monkeypatch.setattr(lockfile, "version", missing)
    with pytest.raises(RuntimeError, match="直接依赖未安装"):
        lockfile.resolve()


def test_known_empty_dependency_metadata_is_valid(tmp_path, monkeypatch) -> None:
    _project_dependencies(tmp_path, monkeypatch, "fixture")
    monkeypatch.setattr(lockfile, "version", lambda _name: "1.0")
    monkeypatch.setattr(lockfile, "requires", lambda _name: None)
    assert lockfile.resolve() == {"fixture": "1.0"}


def test_missing_active_transitive_dependency_rejects_incomplete_lock(
    tmp_path, monkeypatch
) -> None:
    _project_dependencies(tmp_path, monkeypatch, "root")

    def installed(name: str) -> str:
        if name == "child":
            raise lockfile.PackageNotFoundError(name)
        return "1.0"

    monkeypatch.setattr(lockfile, "version", installed)
    monkeypatch.setattr(lockfile, "requires", lambda name: ["child"] if name == "root" else [])
    with pytest.raises(RuntimeError, match=r"依赖闭包成员未安装.*child"):
        lockfile.resolve()


def test_extras_reached_after_base_visit_extend_closure_and_cycles_terminate(
    tmp_path, monkeypatch
) -> None:
    _project_dependencies(tmp_path, monkeypatch, "root", "shared")
    monkeypatch.setattr(lockfile, "version", lambda _name: "1.0")
    metadata = {
        "root": ["shared[feature]"],
        "shared": ["root", "optional; extra == 'feature'", "inactive; python_version < '3.0'"],
        "optional": ["shared[feature]"],
    }
    monkeypatch.setattr(lockfile, "requires", lambda name: metadata[name])
    assert lockfile.resolve() == {"optional": "1.0", "root": "1.0", "shared": "1.0"}
