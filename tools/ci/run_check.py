"""三平台检查入口；优先使用仓库虚拟环境，不依赖激活脚本。"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

try:
    from packaging.specifiers import SpecifierSet
except ModuleNotFoundError:  # pragma: no cover - exercised only before dependencies install
    _HAS_PACKAGING = False
else:
    _HAS_PACKAGING = True

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


def _version_tuple(value: str) -> tuple[int, int, int]:
    """解析解释器的稳定三段版本，拒绝无法核验的值。"""
    match = re.fullmatch(r"\s*(\d+)\.(\d+)(?:\.(\d+))?(?:[+].*)?\s*", value)
    if match is None:
        raise ValueError(f"无法解析解释器版本：{value!r}")
    major, minor, micro = match.groups()
    return int(major), int(minor), int(micro or 0)


def _fallback_satisfies(version: tuple[int, int, int], requirement: str) -> bool:
    """无 packaging 时覆盖项目合同所需的 PEP 440 比较子集。

    ``run_check.py`` 必须能在依赖尚未安装的全局解释器下给出清晰的版本错误，
    因此这里保留一个标准库回退；完整的 PEP 508 解析仍由项目依赖提供。
    """
    for raw in requirement.split(","):
        item = raw.strip()
        match = re.fullmatch(r"(<=|>=|==|!=|<|>)[ ]*(\d+(?:\.\d+){0,2})", item)
        if match is None:
            raise ValueError(f"无法在无 packaging 回退中解析 Python 要求：{requirement!r}")
        operator, expected_text = match.groups()
        expected = _version_tuple(expected_text)
        checks = {
            ">=": version >= expected,
            ">": version > expected,
            "<=": version <= expected,
            "<": version < expected,
            "==": version == expected,
            "!=": version != expected,
        }
        if not checks[operator]:
            return False
    return True


def version_satisfies(version: tuple[int, int, int], requirement: str) -> bool:
    """判断解释器版本是否满足 ``requires-python``。"""
    if not _HAS_PACKAGING:
        return _fallback_satisfies(version, requirement)
    return SpecifierSet(requirement).contains(".".join(map(str, version)), prereleases=True)


def validate_interpreter_version(
    version: tuple[int, int, int], requirement: str, *, interpreter: Path | None = None
) -> None:
    """不满足项目版本合同就显式失败，避免静默使用错误虚拟环境。"""
    if version_satisfies(version, requirement):
        return
    actual = ".".join(map(str, version))
    location = f"（路径：{interpreter}）" if interpreter is not None else ""
    raise RuntimeError(
        f"解释器版本不满足项目要求：实际 Python {actual}{location}；要求 {requirement}"
    )


def interpreter_version(candidate: Path) -> tuple[int, int, int]:
    """运行候选解释器探针，并用 ``pyvenv.cfg`` 交叉核对环境记录。"""
    config_version: tuple[int, int, int] | None = None
    config_path = candidate.parent.parent / "pyvenv.cfg"
    if config_path.is_file():
        for line in config_path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip().lower() == "version":
                config_version = _version_tuple(value)
                break
    probe = subprocess.run(
        [str(candidate), "-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if probe.returncode:
        detail = (probe.stderr or "").strip()
        raise RuntimeError(f"无法读取解释器版本：{candidate}（退出码 {probe.returncode}）{detail}")
    actual = _version_tuple((probe.stdout or "").strip())
    if config_version is not None and config_version != actual:
        expected = ".".join(map(str, config_version))
        observed = ".".join(map(str, actual))
        raise RuntimeError(
            f"解释器版本记录不一致：pyvenv.cfg 为 {expected}，实际探针为 {observed}（路径：{candidate}）"
        )
    return actual


def ensure_supported_interpreter(candidate: Path, root: Path = ROOT) -> None:
    """在启动任何仓库工具前核对候选解释器。"""
    requirement = project_requires_python(root)
    validate_interpreter_version(interpreter_version(candidate), requirement, interpreter=candidate)


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
