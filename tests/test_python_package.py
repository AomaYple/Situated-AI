"""Python wheel 的包发现配置必须覆盖 src 布局下的所有子包。"""

from __future__ import annotations

import tomllib
import warnings
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.ci import python_package

pytestmark = pytest.mark.unit


def test_setuptools_package_discovery_includes_all_project_subpackages() -> None:
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    setuptools = config["tool"]["setuptools"]
    discovery = setuptools["packages"]["find"]

    assert setuptools["package-dir"] == {"": "src"}
    assert discovery["where"] == ["src"]
    assert "pdx*" in discovery["include"]
    assert discovery["namespaces"] is False
    assert config["project"]["dependencies"]
    assert set(config["project"]["urls"]) == {"Homepage", "Repository", "Issues"}
    assert not isinstance(setuptools["packages"], list)

    package_paths = (root / "src" / "pdx").rglob("__init__.py")
    discovered = {".".join(path.relative_to(root / "src").parent.parts) for path in package_paths}
    assert {"pdx", "pdx.situated"} <= discovered


def test_wheel_validation_checks_bytes_missing_and_unexpected_modules(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pdx"
    source.mkdir(parents=True)
    (source / "__init__.py").write_bytes(b"VALUE = 1\n")
    (source / "missing.py").write_bytes(b"VALUE = 2\n")
    wheel = tmp_path / "candidate.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("pdx/__init__.py", b"VALUE = 0\n")
        archive.writestr("pdx/stale.py", b"VALUE = 3\n")
    assert set(python_package.wheel_issues(wheel, source)) == {
        "changed: pdx/__init__.py",
        "missing: pdx/missing.py",
        "unexpected: pdx/stale.py",
    }


def test_wheel_validation_rejects_duplicate_entries(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pdx"
    source.mkdir(parents=True)
    (source / "__init__.py").write_bytes(b"")
    wheel = tmp_path / "candidate.whl"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("pdx/__init__.py", b"")
            archive.writestr("pdx/__init__.py", b"")
    assert python_package.wheel_issues(wheel, source) == ("duplicate: pdx/__init__.py",)


def test_wheel_validation_rejects_non_module_payload(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pdx"
    source.mkdir(parents=True)
    (source / "__init__.py").write_bytes(b"")
    wheel = tmp_path / "situated_ai_v3tools-0.3.0-py3-none-any.whl"
    metadata = "situated_ai_v3tools-0.3.0.dist-info"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("pdx/__init__.py", b"")
        archive.writestr(f"{metadata}/WHEEL", b"Wheel-Version: 1.0\n")
        archive.writestr(f"{metadata}/licenses/LICENSE", b"")
    assert python_package.wheel_issues(wheel, source) == ()

    unexpected = {
        "pdx/analysis-cache.sqlite",
        "research/original.txt",
        "pdx_stale-0.3.0.dist-info/WHEEL",
        f"{metadata}/licenses/appendix.txt",
    }
    with zipfile.ZipFile(wheel, "a") as archive:
        for name in sorted(unexpected):
            archive.writestr(name, b"")
    assert set(python_package.wheel_issues(wheel, source)) == {
        f"unexpected: {name}" for name in unexpected
    }


def test_wheel_validation_reports_corrupt_python_module(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pdx"
    source.mkdir(parents=True)
    data = b"UNIQUE_MODULE_SOURCE = 'original'"
    (source / "__init__.py").write_bytes(data)
    wheel = tmp_path / "candidate.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("pdx/__init__.py", data)
    content = wheel.read_bytes()
    assert content.count(data) == 1
    wheel.write_bytes(content.replace(data, data.replace(b"original", b"corrupt!")))

    assert python_package.wheel_issues(wheel, source) == ("corrupt: pdx/__init__.py",)


def test_build_uses_disposable_source_and_disables_nested_bytecode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repository"
    source = root / "src" / "pdx"
    source.mkdir(parents=True)
    (source / "__init__.py").write_bytes(b"VALUE = 1\n")
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        (root / name).write_bytes(b"input\n")
    monkeypatch.setattr(python_package, "REPO", root)
    monkeypatch.setattr(python_package, "SOURCE", source)

    def build(argv, **kwargs):
        staging = Path(argv[-1])
        assert staging != root
        assert kwargs["cwd"] == staging
        assert kwargs["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
        assert (staging / "src/pdx/__init__.py").read_bytes() == b"VALUE = 1\n"
        (staging / "build").mkdir()
        output = Path(argv[argv.index("--wheel-dir") + 1])
        with zipfile.ZipFile(output / "candidate.whl", "w") as archive:
            archive.writestr("pdx/__init__.py", b"VALUE = 1\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(python_package.subprocess, "run", build)
    assert python_package.main([]) == 0
    assert not (root / "build").exists()
