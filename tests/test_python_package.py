"""Python wheel 的包发现配置必须覆盖 src 布局下的所有子包。"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_setuptools_package_discovery_includes_all_project_subpackages() -> None:
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    setuptools = config["tool"]["setuptools"]
    discovery = setuptools["packages"]["find"]

    assert setuptools["package-dir"] == {"": "src"}
    assert discovery["where"] == ["src"]
    assert "pdx*" in discovery["include"]
    assert not isinstance(setuptools["packages"], list)

    package_paths = (root / "src" / "pdx").rglob("__init__.py")
    discovered = {".".join(path.relative_to(root / "src").parent.parts) for path in package_paths}
    assert {"pdx", "pdx.situated"} <= discovered
