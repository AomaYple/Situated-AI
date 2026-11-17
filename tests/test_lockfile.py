"""依赖锁的测试。

要证明的性质
-----------
1. **锁与 pyproject 对得上**：直接依赖一条不少（少一条 = 有人加了依赖却忘了
   重新生成锁，锁就从「可复现」退化成「看着像」）；
2. **锁文件可解析**：格式稳定、没有重复条目 —— `read()` 是唯一的解析入口，
   它认不出自己的输出就说明渲染或解析有一边坏了；
3. **标记求值是保守的**：只跳过 `extra ==` 与明确不成立的 `python_version`，
   其余一律当作成立（宁可多写一行，也不漏掉一个真依赖）。

⚠️ 这里**不**比较版本号是否等于本机当前版本：CI 是按 `pyproject.toml` 的
下限现解析的，与「这台机器锁住的组合」本来就可能不同。版本对账是本地命令
`v3 lock`（不带参数）的活，它的输出是给人看的。
"""

import sys

import pytest

from pdx import lockfile

pytestmark = pytest.mark.unit


def test_锁文件存在且可解析() -> None:
    locked = lockfile.read()
    assert locked, f"{lockfile.LOCK_FILE} 读不出来（文件缺失或头部标记被改）"
    assert all(name and ver for name, ver in locked.items())
    assert len(set(locked)) == len(locked), "锁里有重复条目"


@pytest.mark.parametrize("version", [(3, 14, 7), (3, 15, 2)])
def test_锁生成器版本合同(version) -> None:
    requirement = lockfile.requires_python()
    if version == (3, 14, 7):
        with pytest.raises(RuntimeError, match=r"实际 Python 3\.14\.7.*要求 >=3\.15\.2"):
            lockfile.validate_python_version(version, requirement)
    else:
        lockfile.validate_python_version(version, requirement)


def test_锁头记录_python_要求和生成解释器() -> None:
    text = lockfile.render({"sample-package": "1.0"})
    assert "# Python 要求: >=3.15.2" not in text
    assert "# Python 要求：>=3.15.2" in text
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
def test_dependency_metadata_failure_is_not_an_empty_closure(monkeypatch, error: Exception) -> None:
    monkeypatch.setattr(lockfile, "direct_requirements", lambda: ["fixture"])
    monkeypatch.setattr(lockfile, "version", lambda _name: "1.0")

    def broken_requires(_name: str) -> list[str]:
        raise error

    monkeypatch.setattr(lockfile, "requires", broken_requires)
    with pytest.raises(type(error), match=str(error)):
        lockfile.resolve()


def test_missing_direct_dependency_is_not_an_empty_closure(monkeypatch) -> None:
    monkeypatch.setattr(lockfile, "direct_requirements", lambda: ["fixture"])

    def missing(_name: str) -> str:
        raise lockfile.PackageNotFoundError("fixture")

    monkeypatch.setattr(lockfile, "version", missing)
    with pytest.raises(RuntimeError, match="直接依赖未安装"):
        lockfile.resolve()


def test_known_empty_dependency_metadata_is_valid(monkeypatch) -> None:
    monkeypatch.setattr(lockfile, "direct_requirements", lambda: ["fixture"])
    monkeypatch.setattr(lockfile, "version", lambda _name: "1.0")
    monkeypatch.setattr(lockfile, "requires", lambda _name: None)
    assert lockfile.resolve() == {"fixture": "1.0"}


def test_missing_active_transitive_dependency_rejects_incomplete_lock(monkeypatch) -> None:
    monkeypatch.setattr(lockfile, "direct_requirements", lambda: ["root"])

    def installed(name: str) -> str:
        if name == "child":
            raise lockfile.PackageNotFoundError(name)
        return "1.0"

    monkeypatch.setattr(lockfile, "version", installed)
    monkeypatch.setattr(lockfile, "requires", lambda name: ["child"] if name == "root" else [])
    with pytest.raises(RuntimeError, match=r"依赖闭包成员未安装.*child"):
        lockfile.resolve()


def test_extras_reached_after_base_visit_extend_closure_and_cycles_terminate(monkeypatch) -> None:
    monkeypatch.setattr(lockfile, "direct_requirements", lambda: ["root", "shared"])
    monkeypatch.setattr(lockfile, "version", lambda _name: "1.0")
    metadata = {
        "root": ["shared[feature]"],
        "shared": ["root", "optional; extra == 'feature'", "inactive; python_version < '3.0'"],
        "optional": ["shared[feature]"],
    }
    monkeypatch.setattr(lockfile, "requires", lambda name: metadata[name])
    assert lockfile.resolve() == {"optional": "1.0", "root": "1.0", "shared": "1.0"}
