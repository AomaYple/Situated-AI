"""跨平台墙钟、进程树采样 RSS 和 Python 分配峰值；不把采样值称为精确高水位。"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, ParamSpec, TypeVar

import psutil

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

P = ParamSpec("P")
T = TypeVar("T")


class StageTimings:
    """单调时钟的阶段区间；保留重叠与异常，不把区间和冒充总墙钟。"""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.started = clock()
        self.intervals: list[dict[str, object]] = []

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        start = self.clock() - self.started
        record: dict[str, object] = {"name": name, "start_s": start, "status": "ok"}
        try:
            yield
        except BaseException as exc:
            record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            end = self.clock() - self.started
            record.update(end_s=end, wall_s=end - start)
            self.intervals.append(record)

    def call(self, name: str, action: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
        with self.phase(name):
            return action(*args, **kwargs)


def measure(function: Callable[[], object], *, rounds: int = 5) -> dict[str, object]:
    """计时与 tracemalloc 分开运行，避免把分配追踪开销算进墙钟。"""
    if rounds < 1:
        raise ValueError("rounds 必须至少为 1")
    times: list[float] = []
    result: object = None
    fingerprint: str | None = None
    for _ in range(rounds):
        start = time.perf_counter()
        result = function()
        times.append(time.perf_counter() - start)
        current = repr(result)
        if fingerprint is not None and current != fingerprint:
            raise ValueError("同一工作负载结果不确定，拒绝形成基线")
        fingerprint = current
    tracemalloc.start()
    try:
        memory_result = function()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    if repr(result) != repr(memory_result):
        raise ValueError("同一工作负载结果不确定，拒绝形成基线")
    return {
        "median_s": statistics.median(times),
        "samples_s": times,
        "python_peak_bytes": peak,
        "result_sha256": hashlib.sha256(repr(result).encode("utf-8")).hexdigest(),
    }


def command(
    argv: Sequence[str], log: Path, *, timeout: float = 1200, interval: float = 0.05
) -> dict[str, object]:
    """测真实命令；stdout/stderr 写盘，避免管道缓冲阻塞和整份输出常驻内存。"""
    if timeout <= 0 or interval <= 0:
        raise ValueError("timeout 和 interval 必须为正")
    log.parent.mkdir(parents=True, exist_ok=True)
    peak = 0
    samples = 0
    start = time.perf_counter()
    timed_out = False
    with (
        log.open("wb") as stream,
        subprocess.Popen(list(argv), stdout=stream, stderr=subprocess.STDOUT) as process,
    ):
        parent = psutil.Process(process.pid)
        while process.poll() is None:
            try:
                tree = [parent, *parent.children(recursive=True)]
            except psutil.NoSuchProcess:
                tree = []
            rss = 0
            for child in tree:
                try:
                    rss += child.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            peak = max(peak, rss)
            samples += 1
            if time.perf_counter() - start > timeout:
                timed_out = True
                for child in reversed(tree):
                    try:
                        child.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                process.kill()
                break
            time.sleep(interval)
        code = process.wait()
    return {
        "argv": list(argv),
        "wall_s": time.perf_counter() - start,
        "sampled_tree_peak_rss_bytes": peak,
        "sample_interval_s": interval,
        "samples": samples,
        "exit_code": code,
        "timed_out": timed_out,
        "log": str(log),
    }


def workloads(*, rounds: int = 5) -> dict[str, object]:
    """有输出指纹的实际功能负载；每项独立，禁止为快而改变结果。"""
    from pdx import citations, localization, modgen  # noqa: PLC0415 - 计时入口不预载生成工具链

    with tempfile.TemporaryDirectory(prefix="sitai-perf-") as folder:
        root = Path(folder)
        target = root / "sample.txt"
        target.write_text("a = 1\n" * 20000, encoding="utf-8", newline="\n")
        refs = "sample.txt:1\n" * 1000
        loc = root / "localization"
        loc.mkdir()
        (loc / "sample.yml").write_text(
            "l_english:\n" + 'key:0 "value"\n' * 500000, encoding="utf-8", newline="\n"
        )

        def reference_scan() -> object:
            result = citations.scan_text(refs, where="benchmark", root=root)
            return (len(result), sum(item.ok for item in result))

        def generator() -> object:
            built = modgen.build_all(modgen.load_all())
            return hashlib.sha256(
                json.dumps(built.files, sort_keys=True).encode("utf-8")
            ).hexdigest()

        return {
            "schema": 1,
            "environment": {
                "python": sys.version,
                "platform": platform.platform(),
                "cpu": platform.processor(),
            },
            "workloads": {
                "citations.repeated_file": measure(reference_scan, rounds=rounds),
                "localization.header_large_file": measure(
                    lambda: dict(localization.language_header_counts(root)), rounds=rounds
                ),
                "modgen.all_archives": measure(generator, rounds=rounds),
            },
        }


def regressions(before: dict, after: dict, *, tolerance: float = 0.1) -> list[str]:
    """同口径结果必须一致；时间和 Python 分配峰值均不能超预算。"""
    if not 0 <= tolerance < 1:
        raise ValueError("tolerance 必须在 [0, 1) 内")
    problems: list[str] = []
    if before.get("environment") != after.get("environment"):
        return ["环境不同，不可直接比较性能"]
    old = before.get("workloads", {})
    new = after.get("workloads", {})
    if old.keys() != new.keys():
        problems.append("工作负载集合不一致")
    for name in sorted(old.keys() & new.keys()):
        a, b = old[name], new[name]
        if a["result_sha256"] != b["result_sha256"]:
            problems.append(f"{name}：结果指纹不同")
        problems.extend(
            f"{name}：{metric} 超过基线 +{tolerance:.0%}"
            for metric in ("median_s", "python_peak_bytes")
            if b[metric] > a[metric] * (1 + tolerance)
        )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    result = (
        command(args.command, args.output.with_suffix(".log"))
        if args.command
        else workloads(rounds=args.rounds)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    if args.compare:
        problems = regressions(json.loads(args.compare.read_text(encoding="utf-8")), result)
        print("\n".join(problems) or "性能与输出指纹一致性检查通过")
        return int(bool(problems))
    print(args.output)
    return int(str(result.get("exit_code", 0)))


if __name__ == "__main__":
    raise SystemExit(main())
