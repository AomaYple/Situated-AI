"""处境生成与tick轮询的速度/内存基准；使用独立临时文件，不接触游戏日志。"""

from __future__ import annotations

import argparse
import hashlib
import platform
import statistics
import tempfile
import time
import tracemalloc
from pathlib import Path

from pdx import (
    behavior_probe,
    config,
    decision_probe,
    decisions,
    extension_probe,
    game_auto,
    game_run,
)
from pdx.parser import parse_file


def measure(action, rounds: int) -> dict[str, float]:
    action()
    samples = []
    for _ in range(rounds):
        started = time.perf_counter()
        action()
        samples.append(time.perf_counter() - started)
    tracemalloc.start()
    try:
        action()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return {"median_seconds": statistics.median(samples), "python_peak_mib": peak / 1024**2}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size-mib", type=int, default=32)
    parser.add_argument("--rounds", type=int, default=7)
    parser.add_argument(
        "--output", type=Path, default=Path("tools/out/benchmarks/decision-runtime.json")
    )
    parser.add_argument("--save", type=Path, help="额外测有限头读取；不修改存档")
    parser.add_argument("--behavior-logs", type=Path, help="额外测真实机会日志解析")
    parser.add_argument("--reform-logs", type=Path, help="额外测真实政治日志解析")
    parser.add_argument(
        "--localization-baseline", action="store_true", help="额外测原版中文缺键仪器生成"
    )
    args = parser.parse_args()
    if args.size_mib <= 0 or args.rounds <= 0:
        parser.error("大小与轮数必须为正整数")
    laws: list[str] = []
    for path in sorted((config.GAME / "common/laws").glob("*.txt")):
        tree = parse_file(path)
        if tree.errors:
            raise ValueError(f"原版法律无法解析：{path}")
        laws.extend(key for key in tree.top_keys if key.startswith("law_"))
    if not laws:
        laws = ["law_autocracy", "law_census_suffrage"]
    with tempfile.TemporaryDirectory(prefix="sitai-tick-bench-") as directory:
        log = Path(directory) / "tick.log"
        with log.open("wb") as stream:
            for _ in range(args.size_mib):
                stream.write(b"x" * (1024**2))
            stream.write(b"\nProcessing Tick: 1900.12.1\n")

        def previous():
            return game_auto.last_tick_in(log.read_text(encoding="utf-8", errors="replace"))

        def current():
            return game_auto.tick_mark(log).tick

        if previous() != current():
            raise AssertionError("新旧轮询结果不一致")
        report = {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "log_bytes": log.stat().st_size,
            "rounds": args.rounds,
            "memory_scope": "tracemalloc Python allocations; excludes OS cache and native RSS",
            "source_sha256": hashlib.sha256(Path(game_auto.__file__).read_bytes()).hexdigest(),
            "previous_full_read": measure(previous, args.rounds),
            "current_reverse_chunks": measure(current, args.rounds),
            "decision_build": measure(decisions.build, args.rounds),
            "streaming_hash": measure(lambda: game_run.hashes(Path(directory)), args.rounds),
            "behavior_instrument_build": measure(behavior_probe.build, args.rounds),
            "reform_instrument_build": measure(lambda: extension_probe.build(laws), args.rounds),
            "reform_law_keys": len(laws),
        }
        if args.save:
            report["save_header"] = measure(lambda: game_run.save_header(args.save), args.rounds)
            report["save_bytes"] = args.save.stat().st_size
        if args.behavior_logs:
            report["behavior_analyze"] = measure(
                lambda: behavior_probe.analyze(args.behavior_logs), args.rounds
            )
        if args.reform_logs:
            report["reform_analyze"] = measure(
                lambda: extension_probe.analyze(args.reform_logs), args.rounds
            )
        if args.localization_baseline:
            report["localization_baseline_build"] = measure(
                lambda: decision_probe.build_localization_baseline(config.GAME), args.rounds
            )
    game_run.write_json(args.output, report)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
