"""纯原版环境基线的 CLI 隔离契约；不启动游戏。"""

from __future__ import annotations

import sys

import pytest

from tools.probe import decision_stability

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("ok", [False, True])
def test_纯原版入口不生成或加载观察器(tmp_path, monkeypatch, ok):
    monkeypatch.setattr(decision_stability.config, "OUT", tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["decision_stability.py", "--arm", "vanilla", "--vanilla-baseline"]
    )
    monkeypatch.setattr(
        decision_stability, "parse_file", lambda *_: pytest.fail("不能读取仪器输入")
    )
    monkeypatch.setattr(
        decision_stability.decisions, "write", lambda *_: pytest.fail("不能生成 Mod")
    )

    def run(sources, **kwargs):
        assert sources == {}
        assert kwargs["vanilla_baseline"] is True
        assert "experiment" not in kwargs
        assert "load_save" not in kwargs
        return {"ok": ok}

    monkeypatch.setattr(decision_stability.game_run, "run", run)
    assert decision_stability.main() == (0 if ok else 1)


@pytest.mark.parametrize(
    "extra",
    [
        ["--arm", "fiscal"],
        ["--save", "input.v3"],
        ["--purpose", "M4"],
        ["--months", "7"],
        ["--months", "nan"],
        ["--resource-baseline"],
        ["--localization-baseline"],
        ["--natural-diplomacy"],
        ["--war-calibration"],
        ["--approval-igs", "ig_a"],
        ["--keep-save"],
        ["--observation-package", "vanilla-performance"],
    ],
)
def test_纯原版入口在生成和运行前拒绝混用(tmp_path, monkeypatch, extra):
    monkeypatch.setattr(decision_stability.config, "OUT", tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["decision_stability.py", "--arm", "vanilla", "--vanilla-baseline", *extra],
    )
    monkeypatch.setattr(
        decision_stability.game_run, "run", lambda *_a, **_kw: pytest.fail("必须先拒绝")
    )
    with pytest.raises(SystemExit) as exc:
        decision_stability.main()
    assert exc.value.code == 2
    assert list(tmp_path.iterdir()) == []
