"""检查入口保留平台无关的参数边界和子进程退出码。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from pdx import version_contracts
from tools.ci import run_check


@pytest.fixture(autouse=True)
def _dispatch_tests_use_supported_interpreter(monkeypatch):
    """命令分发测试不依赖工作区虚拟环境。"""
    monkeypatch.delenv(version_contracts.ENVIRONMENT_VARIABLE, raising=False)
    monkeypatch.setattr(run_check, "interpreter", lambda: Path(sys.executable))
    monkeypatch.setattr(run_check, "ensure_supported_interpreter", lambda *_args: None)


_ensure_supported_interpreter = run_check.ensure_supported_interpreter


def test_native_interpreter_matches_project_contract() -> None:
    assert run_check.project_requires_python() == "==3.15.2"
    _ensure_supported_interpreter(Path(sys.executable))


@pytest.mark.parametrize(
    "identity",
    [
        "cpython 3.14.7 final",
        "cpython 3.15.1 final",
        "cpython 3.15.3 final",
        "cpython 3.16.0 final",
        "cpython 3.15.2 candidate",
        "pypy 3.15.2 final",
    ],
)
def test_interpreter_probe_rejects_unsupported_identity(tmp_path, monkeypatch, identity):
    monkeypatch.setattr(
        run_check.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=identity, stderr=""),
    )
    with pytest.raises(RuntimeError, match=r"要求 CPython 3\.15\.2 正式版"):
        _ensure_supported_interpreter(tmp_path / "python")


def test_interpreter_probe_rejects_stale_venv_metadata(tmp_path, monkeypatch):
    candidate = tmp_path / ".venv" / "Scripts" / "python.exe"
    candidate.parent.mkdir(parents=True)
    (candidate.parent.parent / "pyvenv.cfg").write_text("version = 3.14.7\n", encoding="utf-8")
    monkeypatch.setattr(
        run_check.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout="cpython 3.15.2 final\n", stderr=""
        ),
    )
    with pytest.raises(RuntimeError, match=r"pyvenv\.cfg 为 3\.14\.7，实际探针为 3\.15\.2"):
        _ensure_supported_interpreter(candidate)


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
    assert version_contracts.ENVIRONMENT_VARIABLE not in calls[0][1]["env"]


@pytest.mark.parametrize("command", ["baseline", "baseline-offline"])
def test_baseline_stops_at_first_failure(monkeypatch, command):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0 if len(calls) == 1 else 7)

    monkeypatch.setattr(sys, "argv", ["run_check.py", command])
    monkeypatch.setattr(run_check.subprocess, "run", run)
    assert run_check.main() == 7
    assert len(calls) == 2
    assert all(call[1]["env"]["PYTHONDONTWRITEBYTECODE"] == "1" for call in calls)


def test_python_package_uses_existing_module_and_preserves_exit_status(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(sys, "argv", ["run_check.py", "python-package"])
    monkeypatch.setattr(run_check.subprocess, "run", run)
    assert run_check.main() == 7
    assert len(calls) == 1
    argv, options = calls[0]
    assert argv[1:] == ["-B", "-X", "utf8", "-m", "tools.ci.python_package"]
    assert options["cwd"] == run_check.ROOT
    assert options["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
    assert options["check"] is False


@pytest.mark.parametrize("profile", [version_contracts.CURRENT_VERSION, None])
def test_versioned_baseline_retains_every_existing_gate_and_adds_profile_checks(
    monkeypatch, profile
):
    selected = profile or version_contracts.CURRENT_VERSION
    calls = []

    def run(argv, **kwargs):
        assert version_contracts.ENVIRONMENT_VARIABLE not in kwargs["env"]
        calls.append(argv[argv.index("-m") + 1 :])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(
        sys, "argv", ["run_check.py", "baseline", *(["--profile", profile] if profile else [])]
    )
    monkeypatch.setattr(run_check.subprocess, "run", run)
    assert run_check.main() == 0
    original = [command for _, command in run_check.BASELINE_COMMANDS]
    assert calls[: len(original)] == original
    assert calls[len(original) :] == [
        ["pdx.cli", "modgen", "--profile", selected, "--check"],
        ["pdx.cli", "modguard", "--profile", selected, "--offline"],
        ["pdx.cli", "decision-audit", "--profile", selected, "--offline"],
    ]


def test_offline_baseline_runs_the_shared_gates_without_live_generation(monkeypatch):
    selected = version_contracts.CURRENT_VERSION
    calls = []

    def run(argv, **kwargs):
        assert version_contracts.ENVIRONMENT_VARIABLE not in kwargs["env"]
        calls.append(argv[argv.index("-m") + 1 :])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(sys, "argv", ["run_check.py", "baseline-offline", "--profile", selected])
    monkeypatch.setattr(run_check.subprocess, "run", run)

    assert run_check.main() == 0
    assert calls == [command for _, command in run_check.BASELINE_COMMANDS]


@pytest.mark.parametrize(
    "extra", [["--profile", "1.15.0"], ["--profile", "1.15.1"], ["--unknown"], ["--profile"]]
)
def test_baseline_rejects_ignored_or_unsupported_arguments(monkeypatch, extra):
    monkeypatch.setattr(sys, "argv", ["run_check.py", "baseline", *extra])
    monkeypatch.setattr(
        run_check.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("launch")
    )
    with pytest.raises(SystemExit) as caught:
        run_check.main()
    assert caught.value.code == 2


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


@pytest.mark.parametrize("selected", ["1.14.5", "1.15.0", "1.15.1", "", "unknown", "1.16.0"])
@pytest.mark.parametrize("explicit", [False, True])
def test_baseline_rejects_invalid_environment_before_launch(monkeypatch, selected, explicit):
    monkeypatch.setenv("V3_CONTRACT_PROFILE", selected)
    arguments = ["run_check.py", "baseline"]
    if explicit:
        arguments.extend(["--profile", version_contracts.CURRENT_VERSION])
    monkeypatch.setattr(sys, "argv", arguments)
    monkeypatch.setattr(
        run_check.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("launch")
    )
    with pytest.raises(SystemExit) as caught:
        run_check.main()
    assert caught.value.code == 2


@pytest.mark.parametrize("command", ["test", "test-offline"])
def test_pytest_routes_reject_historical_environment_before_launch(monkeypatch, command):
    monkeypatch.setenv(version_contracts.ENVIRONMENT_VARIABLE, "1.15.1")
    monkeypatch.setattr(sys, "argv", ["run_check.py", command])
    monkeypatch.setattr(
        run_check.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("launch")
    )
    assert run_check.main() == 2


def test_interpreter_rejects_non_exact_project_requirement(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=3.15.2"\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="必须使用 == 固定三段版本"):
        _ensure_supported_interpreter(Path(sys.executable), tmp_path)
