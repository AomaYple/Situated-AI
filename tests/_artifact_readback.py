"""Full artifact deserialization with process-owned temporary object lifetime.

The child remains in the pytest process tree and its memory is included by the
normal tree sampler. No detached process, resource exclusion or parser shortcut.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def assert_artifacts_readback(artifacts: dict[str, Path], *, timeout_s: float) -> None:
    """Propagate the complete failing child traceback, including artifact identity."""
    from tools.ci import mem_baseline as mem

    budget = timeout_s
    assert budget > 0, "A positive pytest timeout is required"
    # Leave time inside the unchanged pytest budget to terminate/reap the tree.
    cleanup_grace = min(5.0, budget / 10)
    with subprocess.Popen(
        [sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve())],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    ) as process:
        try:
            stdout, stderr = process.communicate(
                json.dumps({name: str(path) for name, path in artifacts.items()}),
                timeout=budget - cleanup_grace,
            )
        except BaseException:
            mem.kill_tree(process.pid)
            process.communicate()
            raise
    assert process.returncode == 0, (
        f"Artifact readback exited {process.returncode}\n{stdout}\n{stderr}"
    )
    # Preserve the child's exact HWM/authority receipt in normal pytest capture.
    print(stdout, end="")


def _assert_artifact_readback(name: str, path: Path) -> None:
    # Keep the original strict UTF-8 decode and full standard JSON parse. A new
    # function call releases the previous file's objects before reading the next.
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        obj = json.loads(text)
        assert isinstance(obj, dict), f"{name} 顶层应为对象"
    else:
        assert text.lstrip().startswith("#"), f"{name} 应是 Markdown"
    # On sampled platforms read RSS while the complete text/tree are still live.
    _check_memory()


def _check_memory() -> None:
    from tools.ci import mem_baseline as mem

    rss, peak, _private = mem._self_read()
    receipt = {
        "pid": __import__("os").getpid(),
        "rss_mb": rss,
        "peak_mb": peak,
        "limit_mb": mem.BUDGET_PER_WORKER_MB,
        "peak_source": mem.MemReader().peak_source,
    }
    print(json.dumps({"artifact_readback_memory": receipt}), flush=True)
    assert peak <= mem.BUDGET_PER_WORKER_MB, f"Artifact readback memory budget exceeded: {receipt}"


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    for name, filename in json.load(sys.stdin).items():
        path = Path(filename)
        try:
            _assert_artifact_readback(name, path)
            _check_memory()
        except BaseException:
            print(f"Artifact readback failed: {name}: {path}", file=sys.stderr)
            raise
    _check_memory()
