"""M2 正式实机冒烟脚本的无游戏单元契约。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _module():
    path = Path(__file__).parents[1] / "tools" / "probe" / "m2_formal_smoke.py"
    spec = importlib.util.spec_from_file_location("m2_formal_smoke", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_冒烟只部署生产产物不混入旧档案(tmp_path, monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "RESULT_DIR", tmp_path)

    def fake_run(sources, **kwargs):
        root = sources[module.MOD_NAME]
        assert set(module.game_run.hashes(root)) == set(module.decisions.build())
        assert kwargs["months"] == 2
        return {"ok": True}

    monkeypatch.setattr(module.game_run, "run", fake_run)
    assert module.run(2)["ok"]


def test_失败的实机报告返回非零退出码(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "run", lambda _: {"failure": "test"})
    assert module.main(["--months", "2", "--fresh-logs"]) == 1
