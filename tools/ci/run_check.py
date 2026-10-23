"""三平台检查入口；优先使用仓库虚拟环境，不依赖激活脚本。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMMANDS = {
    "lint": ["ruff", "check", "--force-exclude"],
    "format": ["ruff", "format", "--force-exclude"],
    "types": ["mypy"],
    "test": ["pytest"],
    "full-acceptance": ["tools.ci.test_suite"],
    # 用参数列表传递 marker 表达式，避免 Windows shell 把空格拆成路径。
    "test-offline": ["pytest", "-m", "not integration and not benchmark"],
    "offline": ["pdx.cli", "verify", "--from-snapshot"],
    "decision-audit": ["pdx.cli", "decision-audit"],
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
    ("情境决策合同", ["pdx.cli", "decision-audit"]),
    ("离线 AI 可执行面", ["pdx.cli", "ai-surface", "--check", "--offline"]),
    ("死代码审计", ["tools.ci.deadcode_audit", "--check"]),
]


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
    python = interpreter()
    env = dict(os.environ)
    # A shared editable installation can point at another checkout. Every child
    # must inspect this worktree, including nested pytest and resource processes.
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT), env.get("PYTHONPATH", "")])
    if sys.argv[1] == "baseline":
        for label, command in BASELINE_COMMANDS:
            print(f"[baseline] {label}", flush=True)
            result = subprocess.run(
                [str(python), "-X", "utf8", "-m", *command],
                cwd=ROOT,
                check=False,
                env=env,
            )
            if result.returncode:
                print(f"[baseline] {label} 失败（退出码 {result.returncode}）", file=sys.stderr)
                return result.returncode
        return 0
    command = COMMANDS[sys.argv[1]]
    bytecode_flag = ["-B"] if sys.argv[1] == "hygiene" else []
    return subprocess.run(
        [str(python), *bytecode_flag, "-X", "utf8", "-m", *command, *sys.argv[2:]],
        cwd=ROOT,
        check=False,
        env=env,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
