"""检查入口保留平台无关的参数边界和子进程退出码。"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from tools.ci import run_check


@pytest.mark.parametrize("profile", ["test", "test-offline", "full-acceptance"])
def test_profiles_preserve_arguments_and_exit_status(monkeypatch, profile):
    supplied = (
        ["--", "-n", "0"]
        if profile == "full-acceptance"
        else [
            "tests/a path.py",
            "-k",
            'name and "中文"',
        ]
    )
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=5)

    monkeypatch.setattr(sys, "argv", ["run_check.py", profile, *supplied])
    monkeypatch.setattr(run_check.subprocess, "run", run)
    assert run_check.main() == 5
    assert len(calls) == 1
    assert calls[0][0][-len(supplied) :] == supplied
    assert calls[0][1]["cwd"] == run_check.ROOT
    assert calls[0][1]["check"] is False
