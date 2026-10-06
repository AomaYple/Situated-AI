"""仓库审计脚本的目录迁移防线。"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


def _load_audit():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "probe" / "audit_repo.py"
    spec = importlib.util.spec_from_file_location("situated_audit_repo", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_审计扫描真实源码和测试目录():
    module = _load_audit()
    modules, tests = module._scan_targets(Path(__file__).resolve().parents[1])
    assert len(modules) >= 70
    assert len(tests) >= 100
    assert all(path.parent.name == "pdx" for path in modules)
    assert all(path.parent.name == "tests" for path in tests)


@pytest.mark.parametrize("missing", ["src/pdx", "tests"])
def test_迁移后缺目录不能静默通过(tmp_path, missing):
    module = _load_audit()
    (tmp_path / "src/pdx").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / missing).rmdir()
    with pytest.raises(ValueError, match="审计目标"):
        module._scan_targets(tmp_path)


def test_迁移后空扫描不能静默通过(tmp_path):
    module = _load_audit()
    (tmp_path / "src/pdx").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    with pytest.raises(ValueError, match="扫描为空"):
        module._scan_targets(tmp_path)


def test_命令输出使用新目录且不再把空旧路径当通过():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "tools/probe/audit_repo.py"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0
    assert "模块 0 个" not in result.stdout
    assert "测试文件 0 个" not in result.stdout
    assert "src/pdx" in result.stdout
    assert "扫描源码目录：src/pdx" in result.stdout
    assert "扫描测试目录：tests" in result.stdout
