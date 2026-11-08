"""检查入口保留平台无关的参数边界和子进程退出码。"""

from __future__ import annotations

import os
import subprocess
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
    monkeypatch.setenv("PYTHONPATH", "preserved-path")

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
    assert calls[0][1]["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
    assert calls[0][1]["env"]["PYTHONPATH"].split(os.pathsep) == [
        str(run_check.ROOT / "src"),
        str(run_check.ROOT),
        "preserved-path",
    ]


def test_baseline_stops_at_first_failure(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0 if len(calls) == 1 else 7)

    monkeypatch.setattr(sys, "argv", ["run_check.py", "baseline"])
    monkeypatch.setattr(run_check.subprocess, "run", run)
    assert run_check.main() == 7
    assert len(calls) == 2
    assert all(call[1]["env"]["PYTHONDONTWRITEBYTECODE"] == "1" for call in calls)


def test_nested_python_import_does_not_leave_bytecode(tmp_path, monkeypatch):
    module = tmp_path / "cleanup_probe.py"
    module.write_text("VALUE = 42\n", encoding="utf-8", newline="\n")
    script = tmp_path / "child.py"
    script.write_text(
        "import subprocess, sys\n"
        "subprocess.run([sys.executable, '-c', 'import cleanup_probe; "
        "assert cleanup_probe.VALUE == 42'], check=True)\n",
        encoding="utf-8",
        newline="\n",
    )
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setitem(run_check.COMMANDS, "bytecode-probe", ["child"])
    monkeypatch.setattr(sys, "argv", ["run_check.py", "bytecode-probe"])
    # Preserve the real subprocess call: exercise environment inheritance too.
    assert run_check.subprocess.run is subprocess.run
    assert run_check.main() == 0
    assert not (tmp_path / "__pycache__").exists()
