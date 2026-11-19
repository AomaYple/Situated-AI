"""三平台检查入口；优先使用仓库虚拟环境，不依赖激活脚本。"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMMANDS = {
    "lint": ["ruff", "check", "--force-exclude"],
    "format": ["ruff", "format", "--force-exclude"],
    "types": ["mypy"],
    "test": ["pytest"],
    "full-acceptance": ["tools.ci.test_suite"],
    "python-package": ["tools.ci.python_package"],
    # 用参数列表传递 marker 表达式，避免 Windows shell 把空格拆成路径。
    "test-offline": ["pytest", "-m", "not integration and not benchmark"],
    "offline": ["pdx.cli", "verify", "--from-snapshot"],
    "decision-audit": ["pdx.cli", "decision-audit", "--offline"],
    "encoding": [
        "pdx.repo_audit",
        "--project-only",
        "--output",
        "tools/out/repository-audit/source-encoding.json",
    ],
    "deadcode": ["tools.ci.deadcode_audit", "--check"],
    "hygiene": [
        "tools.ci.repo_hygiene",
        "--output",
        "tools/out/ci/repo-hygiene.json",
    ],
}

BASELINE_COMMANDS = [
    ("依赖一致性", ["pip", "check"]),
    ("离线断言", ["pdx.cli", "verify", "--from-snapshot"]),
    ("离线生成表格", ["pdx.cli", "tables", "--offline"]),
    ("离线 Mod 门禁", ["pdx.cli", "modguard", "--offline"]),
    ("情境决策合同", ["pdx.cli", "decision-audit", "--offline"]),
    ("离线 AI 可执行面", ["pdx.cli", "ai-surface", "--check", "--offline"]),
    ("死代码审计", ["tools.ci.deadcode_audit", "--check"]),
]


def project_requires_python(root: Path = ROOT) -> str:
    """读取项目唯一维护的 Python 版本合同。"""
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8")).get(
        "project", {}
    )
    requirement = project.get("requires-python")
    if not isinstance(requirement, str) or not requirement.strip():
        raise ValueError("pyproject.toml 缺少有效的 project.requires-python")
    return requirement.strip()


def ensure_supported_interpreter(candidate: Path, root: Path = ROOT) -> None:
    """在启动仓库工具前核对正式 CPython 及虚拟环境记录。"""
    requirement = project_requires_python(root)
    match = re.fullmatch(r"==([0-9]+\.[0-9]+\.[0-9]+)", requirement)
    if match is None:
        raise ValueError(f"project.requires-python 必须使用 == 固定三段版本：{requirement!r}")
    expected = match[1]
    probe = subprocess.run(
        [
            str(candidate),
            "-I",
            "-B",
            "-S",
            "-c",
            (
                "import sys; "
                "print(sys.implementation.name, '.'.join(map(str, sys.version_info[:3])), "
                "sys.version_info.releaselevel)"
            ),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if probe.returncode:
        detail = (probe.stderr or "").strip()
        raise RuntimeError(f"无法读取解释器版本：{candidate}（退出码 {probe.returncode}）{detail}")
    identity = probe.stdout.strip()
    if identity != f"cpython {expected} final":
        raise RuntimeError(
            f"要求 CPython {expected} 正式版，实际探针为 {identity!r}（路径：{candidate}）"
        )
    config_path = candidate.parent.parent / "pyvenv.cfg"
    if config_path.is_file():
        for line in config_path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip().lower() == "version":
                recorded = value.strip()
                if recorded != expected:
                    raise RuntimeError(
                        f"解释器版本记录不一致：pyvenv.cfg 为 {recorded}，"
                        f"实际探针为 {expected}（路径：{candidate}）"
                    )
                break


def interpreter(root: Path = ROOT) -> Path:
    relative = ".venv/Scripts/python.exe" if sys.platform == "win32" else ".venv/bin/python"
    candidate = root / relative
    if candidate.is_file():
        return candidate
    return Path(sys.executable)


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in (*COMMANDS, "baseline"):
        print(f"检查种类：{', '.join((*COMMANDS, 'baseline'))}", file=sys.stderr)
        return 2
    if sys.argv[1] == "baseline":
        parser = argparse.ArgumentParser(description="完整静态基线；版本门追加到现有门禁之后。")
        parser.add_argument("--profile", choices=("1.15.1",), default="1.15.1")
        args = parser.parse_args(sys.argv[2:])
        selected_environment = os.environ.get("V3_CONTRACT_PROFILE")
        if selected_environment is not None and selected_environment != args.profile:
            parser.error(f"未支持的原版合同版本：{selected_environment!r}")
    try:
        python = interpreter()
        ensure_supported_interpreter(python)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"检查入口拒绝解释器：{exc}", file=sys.stderr)
        return 2
    env = dict(os.environ)
    # A shared editable installation can point at another checkout. Every child
    # must inspect this worktree, including nested pytest and resource processes.
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT), env.get("PYTHONPATH", "")])
    # -B applies to this child; the environment also covers nested Python tools.
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if sys.argv[1] == "baseline":
        commands = list(BASELINE_COMMANDS)
        if args.profile:
            # 原有离线断言、表格和 AI 面也消费相同版本合同；完整集合继续保留。
            env["V3_CONTRACT_PROFILE"] = args.profile
            commands.extend(
                (
                    f"{args.profile} {name}",
                    ["pdx.cli", name, "--profile", args.profile, *options],
                )
                for name, options in (
                    ("modgen", ["--check"]),
                    ("modguard", ["--offline"]),
                    ("decision-audit", ["--offline"]),
                )
            )
        for label, command in commands:
            print(f"[baseline] {label}", flush=True)
            result = subprocess.run(
                [str(python), "-B", "-X", "utf8", "-m", *command],
                cwd=ROOT,
                check=False,
                env=env,
            )
            if result.returncode:
                print(f"[baseline] {label} 失败（退出码 {result.returncode}）", file=sys.stderr)
                return result.returncode
        return 0
    command = COMMANDS[sys.argv[1]]
    return subprocess.run(
        [str(python), "-B", "-X", "utf8", "-m", *command, *sys.argv[2:]],
        cwd=ROOT,
        check=False,
        env=env,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
