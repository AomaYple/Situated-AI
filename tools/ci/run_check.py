"""三平台检查入口；优先使用仓库虚拟环境，不依赖激活脚本。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMMANDS = {
    "lint": ["ruff", "check", "--force-exclude"],
    "format": ["ruff", "format", "--force-exclude"],
    "types": ["mypy"],
    "test": ["pytest"],
    # 用参数列表传递 marker 表达式，避免 Windows shell 把空格拆成路径。
    "test-offline": ["pytest", "-m", "not integration and not benchmark"],
    "offline": ["pdx.cli", "verify", "--from-snapshot"],
    "encoding": [
        "pdx.repo_audit",
        "--project-only",
        "--output",
        "tools/out/repository-audit/source-encoding.json",
    ],
    "deadcode": ["tools.ci.deadcode_audit", "--check"],
}

BASELINE_COMMANDS = [
    ("pip check", ["pip", "check"]),
    ("offline verify", ["pdx.cli", "verify", "--from-snapshot"]),
    ("offline tables", ["pdx.cli", "tables", "--offline"]),
    ("generated mod", ["pdx.cli", "modgen", "--check"]),
    ("offline modguard", ["pdx.cli", "modguard", "--offline"]),
    ("offline ai surface", ["pdx.cli", "ai-surface", "--check", "--offline"]),
    ("offline citations", ["pdx.cli", "citations", "--offline"]),
    ("deadcode", ["tools.ci.deadcode_audit", "--check"]),
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
    if sys.argv[1] == "baseline":
        for label, command in BASELINE_COMMANDS:
            print(f"[baseline] {label}", flush=True)
            result = subprocess.run(
                [str(python), "-X", "utf8", "-m", *command],
                cwd=ROOT,
                check=False,
            )
            if result.returncode:
                print(f"[baseline] {label} 失败（退出码 {result.returncode}）", file=sys.stderr)
                return result.returncode
        return 0
    command = COMMANDS[sys.argv[1]]
    return subprocess.run(
        [str(python), "-X", "utf8", "-m", *command, *sys.argv[2:]],
        cwd=ROOT,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
