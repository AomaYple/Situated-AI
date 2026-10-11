"""正式资格验证的合成成本基线；串行测时间、Python 分配和进程树采样 RSS。"""

from __future__ import annotations

import argparse
import json
import platform
import runpy
import sys
import tempfile
from functools import partial
from pathlib import Path

from pdx import experiment_evidence, game_run, performance

ROOT = Path(__file__).resolve().parents[2]


def validate(root: Path, kind: str = "qualification") -> object:
    registration = json.loads((root / "registration.json").read_bytes())
    context = {key: registration[key] for key in experiment_evidence.CONTEXT_FIELDS}
    context.update(
        game_version=json.loads((root / "run/report.json").read_bytes())["game_version"],
        months=1,
        arm="control",
    )
    if kind == "preparation":
        context["checkpoint_sha256"] = game_run.file_sha(root / "input.v3")
        qualification = json.loads((root / "qualification.json").read_bytes())
        result = experiment_evidence.validate_preparation(
            (root / "registration.json").read_bytes(),
            game_files={
                name: root / ref["path"] for name, ref in qualification["game_files"].items()
            },
            context=context,
        )
    elif kind == "control":
        context["pair"] = 0
        result = experiment_evidence.review_control(
            root / "control/report.json",
            qualification_report=root / "qualification.json",
            checkpoint_sha256=game_run.file_sha(root / "input.v3"),
            expected_version="1.14.5",
            purpose="M3-A",
            context=context,
        )
    else:
        result = experiment_evidence.validate(
            root / "qualification.json",
            checkpoint_sha256=game_run.file_sha(root / "input.v3"),
            expected_version="1.14.5",
            purpose="M3-A",
            context=context,
        )
    if not result["allowed"]:
        raise ValueError(f"合成资格负载不能通过：{result['reasons']}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes-mib", type=int, nargs="+", default=[8, 64])
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument(
        "--output", type=Path, default=Path("tools/out/benchmarks/experiment-evidence.json")
    )
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument(
        "--kind", choices=("qualification", "preparation", "control"), help=argparse.SUPPRESS
    )
    args = parser.parse_args()
    if args.worker is not None:
        validate(args.worker, args.kind or "qualification")
        return 0
    if args.rounds < 3 or any(size <= 0 for size in args.sizes_mib):
        parser.error("基线至少三轮，日志大小必须为正整数")
    fixture = runpy.run_path(str(ROOT / "tests/test_experiment_evidence.py"))
    output: dict[str, object] = {
        "schema": 2,
        "environment": {"python": sys.version, "platform": platform.platform()},
        "provenance": game_run.execution_provenance(validate),
        "scope": "合成原件成本基线；不是实机、旧实现对照或加速倍数",
        "cache": "热磁盘；不清系统页缓存；重复仍全量散列和复核",
        "rss_scope": "独立子进程含 Python/库导入；采样 RSS 不等于精确高水位",
        "inputs": {
            str(path.relative_to(ROOT)): game_run.file_sha(path)
            for path in (
                Path(__file__),
                ROOT / "tests/test_experiment_evidence.py",
                ROOT / "src/pdx/experiment_evidence.py",
            )
        },
        "workloads": {},
    }
    workloads: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="sitai-evidence-benchmark-") as directory:
        for size in args.sizes_mib:
            root = Path(directory) / str(size)
            bundle = fixture["_bundle"](root)
            log = root / "run/logs/debug.log"
            # 普通短行保证测的是实际逐行日志路径，而不是一个超长字符串。
            line = b"synthetic benchmark padding; no observation or error\n"
            block = line * (65536 // len(line))
            remaining = size * 1024**2
            with log.open("ab") as stream:
                while remaining:
                    chunk = block[:remaining]
                    stream.write(chunk)
                    remaining -= len(chunk)
                stream.write(b"\n")
            fixture["_refresh"](bundle)
            fixture["_control_report"](bundle)
            validate(root)
            workloads[f"log-{size}mib"] = workload = {
                "actual_debug_bytes": log.stat().st_size,
                "calls": {},
            }
            calls: dict[str, object] = {}
            for kind in ("qualification", "preparation", "control"):
                timing = performance.measure(partial(validate, root, kind), rounds=args.rounds)
                rss = [
                    performance.command(
                        [
                            sys.executable,
                            "-X",
                            "utf8",
                            str(Path(__file__).resolve()),
                            "--worker",
                            str(root),
                            "--kind",
                            kind,
                        ],
                        args.output.parent / f"evidence-{size}mib-{kind}-rss-{index + 1}.log",
                        timeout=1200,
                        interval=0.02,
                    )
                    for index in range(args.rounds)
                ]
                if any(run["exit_code"] or run["timed_out"] for run in rss):
                    raise RuntimeError("独立 RSS 测量失败，拒绝形成通过基线")
                calls[kind] = {"timing": timing, "rss_runs": rss}
            workload["calls"] = calls
            print(f"{size} MiB 合成资格成本测量完成", flush=True)
    output["workloads"] = workloads
    game_run.write_json(args.output, output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
