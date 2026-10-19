"""完整测试验收：一次 pytest 生成覆盖率、JUnit、身份与资源证据。

普通反馈仍用 run_check test/test-offline；本入口只允许并发和随机种子诊断参数。
报告根目录下每轮创建独立子目录，失败产物与原始退出码继续保留。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
import subprocess
import sys
import time
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

# 探针是可独立执行的脚本；按运行时接口复用，不把其历史单点实验纳入包类型检查。
mem = importlib.import_module("tools.probe.mem_baseline")

ROOT = Path(__file__).resolve().parents[2]
_COLLECTION_ENV = "SITAI_TEST_COLLECTION"


def _write(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def create_run_dir(root: Path) -> Path:
    name = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:12]
    target = root.resolve() / name
    target.mkdir(parents=True, exist_ok=False)
    return target


def validate_pytest_args(args: list[str]) -> list[str]:
    """只允许不会改变用例集合及执行次数的调度与种子参数。"""
    seen: set[str] = set()
    index = 0
    while index < len(args):
        token = args[index]
        option, separator, value = token.partition("=")
        if option in {"-n", "--numprocesses", "--dist", "--randomly-seed"}:
            if not separator:
                index += 1
                if index == len(args):
                    raise ValueError(f"pytest 参数缺少值：{option}")
                value = args[index]
        elif token.startswith("-n") and token[2:].isdigit():
            option, value = "-n", token[2:]
        else:
            raise ValueError(f"完整验收不允许筛选或重定义门禁：{token}")
        key = "-n" if option == "--numprocesses" else option
        if key in seen:
            raise ValueError(f"完整验收不允许重复声明调度参数：{option}")
        seen.add(key)
        if key == "-n":
            valid = value in {"auto", "logical"} or value.isdigit()
        elif key == "--dist":
            valid = value in {"no", "load", "loadscope", "loadfile", "loadgroup", "worksteal"}
        else:
            valid = value.isdigit() or value == "last"
        if not valid:
            raise ValueError(f"pytest 参数值无效或改变执行次数：{token}={value}")
        index += 1
    return list(args)


class ExecutionRecorder:
    """controller 接收串行或 xdist 转发的真实执行事件，不从收集数量推断执行。"""

    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state

    def pytest_runtest_logstart(self, nodeid: str, location: Any) -> None:
        del location  # pytest hookspec 参数名必须保持。
        self.state["started"].append(nodeid)

    def pytest_runtest_logfinish(self, nodeid: str, location: Any) -> None:
        del location
        self.state["finished"].append(nodeid)

    def pytest_runtest_logreport(self, report: Any) -> None:
        worker = getattr(report, "worker_id", None)
        node = getattr(report, "node", None)
        if worker is None and node is not None:
            gateway = getattr(node, "gateway", None)
            worker = getattr(gateway, "id", None)
        self.state["reports"].append(
            {
                "nodeid": report.nodeid,
                "when": report.when,
                "outcome": report.outcome,
                "worker": worker or "master",
                "subtest": hasattr(report, "context") or type(report).__name__ == "SubTestReport",
            }
        )


def _effective_config(config: Any) -> dict[str, Any]:
    option = getattr(config, "option", None)
    workers = getattr(option, "numprocesses", 0) or 0
    dist = getattr(option, "dist", "no")
    repeat = getattr(option, "count", 1)
    if dist == "each" or repeat != 1:
        raise pytest.UsageError("完整验收拒绝 dist=each 或重复执行配置")
    return {
        "numprocesses": workers,
        "dist": dist,
        "repeat": repeat,
        "basetemp": str(getattr(option, "basetemp", None)),
        "rootpath": str(getattr(config, "rootpath", "")),
    }


def pytest_configure(config: Any) -> None:
    if os.environ.get(_COLLECTION_ENV):
        effective = _effective_config(config)
        config._sitai_collection = {
            "nodeids": [],
            "mismatches": [],
            "workers": [],
            "started": [],
            "finished": [],
            "reports": [],
            "effective": effective,
        }
        if not hasattr(config, "workerinput") and hasattr(config, "pluginmanager"):
            config.pluginmanager.register(ExecutionRecorder(config._sitai_collection))


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_protocol(item: Any) -> Any:
    """被测用例的普通子进程不继承本轮验收输出；本进程探针仍使用已初始化状态。"""
    if not hasattr(item.config, "_sitai_collection"):
        yield
        return
    names = {
        "MEMBASELINE_OUT",
        "MEMBASELINE_TAG",
        _COLLECTION_ENV,
        "COVERAGE_FILE",
        "COVERAGE_PROCESS_CONFIG",
        "COVERAGE_PROCESS_START",
    }
    names.update(name for name in os.environ if name.startswith("COV_CORE_"))
    saved = {name: os.environ.pop(name) for name in names if name in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)


def pytest_collection_finish(session: Any) -> None:
    config = session.config
    if hasattr(config, "_sitai_collection") and not hasattr(config, "workerinput"):
        config._sitai_collection["nodeids"] = [item.nodeid for item in session.items]


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_node_collection_finished(node: Any, ids: list[str]) -> None:
    state = getattr(node.config, "_sitai_collection", None)
    if state is None:
        return
    if state["workers"] and state["nodeids"] != ids:
        state["mismatches"].append(node.gateway.id)
    if not state["workers"]:
        state["nodeids"] = list(ids)
    state["workers"].append(node.gateway.id)


def pytest_sessionfinish(session: Any, exitstatus: Any) -> None:
    config = session.config
    if hasattr(config, "workerinput") or not hasattr(config, "_sitai_collection"):
        return
    state = config._sitai_collection
    state["exitstatus"] = int(exitstatus)
    state["effective"] = _effective_config(config)
    for key in ("started", "finished"):
        state[key + "_counts"] = dict(sorted(Counter(state[key]).items()))
    state["counts"] = dict(sorted(Counter(state["nodeids"]).items()))
    state["sha256"] = hashlib.sha256(
        json.dumps(state["counts"], sort_keys=True).encode("utf-8")
    ).hexdigest()
    _write(Path(os.environ[_COLLECTION_ENV]), state)


def _number(value: Any, *, positive: bool = False, integer: bool = False) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"无效数值：{value!r}")
    if value < 0 or (positive and value == 0) or (integer and type(value) is not int):
        raise ValueError(f"无效数值范围或整数类型：{value!r}")
    return float(value)


def _resource_evidence(out: Path, summary: dict[str, Any]) -> dict[str, Any]:
    """核对双路采样 PID，以二者较高的 OS 高水位执行预算。"""
    rows = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(out.glob("inproc-full-*.json"))
    ]
    if not rows:
        raise ValueError("缺少进程内采样")
    by_worker: dict[str, Any] = {}
    for row in rows:
        worker = row["worker"]
        if worker in by_worker:
            raise ValueError("进程内 worker 身份重复")
        _number(row["pid"], positive=True, integer=True)
        _number(row["peak_ws_mb"], positive=True)
        _number(row["final_ws_mb"])
        if row["peak_ws_mb"] < row["final_ws_mb"]:
            raise ValueError("进程内高水位小于最终 RSS")
        if row["errors"] or type(row["exitstatus"]) is not int or row["exitstatus"] != 0:
            raise ValueError(f"进程内采样失败：{worker}")
        by_worker[worker] = row
    master = by_worker.pop("master")
    _number(summary["controller_pid"], positive=True, integer=True)
    for pid in summary["worker_pids"]:
        _number(pid, positive=True, integer=True)
    if master["pid"] != summary["controller_pid"]:
        raise ValueError("进程内 controller PID 与外部分类不一致")
    reported = [row["pid"] for row in by_worker.values()]
    if len(set(reported)) != len(reported) or set(reported) != set(summary["worker_pids"]):
        raise ValueError("进程内 worker PID 与外部分类不一致")
    if len(reported) != summary["n_workers"]:
        raise ValueError("进程内 worker 数与外部并发分类不一致")
    processes = summary["processes"]
    external = {row["pid"]: row for row in processes}
    if len(external) != len(processes):
        raise ValueError("外部进程 PID 重复")
    pairs = []
    for row in [master, *by_worker.values()]:
        process = external[row["pid"]]
        expected_role = "root" if row["worker"] == "master" else "worker"
        if process["role"] != expected_role:
            raise ValueError("进程角色与自报身份不一致")
        peak = _number(process["hwm_mb"], positive=True)
        pairs.append(
            {
                "worker": row["worker"],
                "pid": row["pid"],
                "external_hwm_mb": peak,
                "inproc_hwm_mb": row["peak_ws_mb"],
                "budget_peak_mb": max(peak, row["peak_ws_mb"]),
            }
        )
    executing = [pair for pair in pairs if pair["worker"] != "master"] or pairs
    return {
        "inproc": rows,
        "peak_pairs": pairs,
        "execution_peak_mb": max(pair["budget_peak_mb"] for pair in executing),
    }


def finalize(out: Path, summary: dict[str, Any], *, reference: Path | None = None) -> int:
    """每个门禁独立执行，即使 pytest 或某份产物失败仍保全其它证据。"""
    # 本模块也是 pytest 插件；门禁依赖延迟到父进程，避免在 coverage 启动前导入业务模块。
    from pdx import covgate  # noqa: PLC0415
    from tools.ci.test_summary import summarize  # noqa: PLC0415

    errors: list[str] = []
    report: dict[str, Any] = {"groups": [summary], "errors": errors, "output": str(out)}
    try:
        for field in ("peak_total_mb", "per_worker_peak_mb", "n_workers", "samples"):
            value = summary[field]
            _number(value, integer=field in {"n_workers", "samples"})
        if not summary["peak_total_mb"]:
            raise ValueError("RSS 峰值缺失")
        evidence = _resource_evidence(out, summary)
        report["resources"] = evidence
        budget_summary = dict(summary)
        budget_summary["per_worker_peak_mb"] = max(
            summary["per_worker_peak_mb"], evidence["execution_peak_mb"]
        )
        verdict = mem.judge(budget_summary)
    except Exception as exc:
        verdict = {"ok": False, "checks": [], "error": str(exc)}
        errors.append(f"RSS 门禁无法判定：{exc}")
    report["verdict"] = [verdict]
    if not verdict["ok"]:
        errors.append("pytest 或 RSS 预算未通过")
    errors.extend(
        f"{field}: {summary[field]}"
        for field in ("timed_out", "killed_by_watchdog", "sampler_errors", "execution_error")
        if summary.get(field)
    )
    if not summary.get("samples"):
        errors.append("RSS 无有效采样")
    try:
        tests = summarize(out / "junit.xml")
        report["tests"] = tests
        _write(out / "test-summary.json", tests)
        if not tests["tests"] or tests["errors"] or tests["failures"]:
            errors.append("JUnit 为空或存在失败/错误")
        if tests["unknown_skip_reasons"]:
            errors.append("存在未分类跳过")
    except Exception as exc:
        errors.append(f"JUnit 门禁无法读取：{exc}")
    try:
        collection = json.loads((out / "collection.json").read_text(encoding="utf-8"))
        report["collection"] = collection
        nodeids = collection["nodeids"]
        expected = Counter(nodeids)
        if any(row["outcome"] == "failed" for row in collection["reports"]):
            errors.append("执行阶段或子断言报告存在失败")
        if collection["exitstatus"] != summary.get("exit_code"):
            errors.append("收集报告与进程退出码不一致")
        if (
            Counter(collection["started"]) != expected
            or Counter(collection["finished"]) != expected
        ):
            errors.append("真实执行身份/重复次数与收集集合不一致")
        for phase in ("setup", "teardown"):
            actual = Counter(row["nodeid"] for row in collection["reports"] if row["when"] == phase)
            if actual != expected:
                errors.append(f"执行 {phase} 身份/重复次数不一致")
        calls = Counter(
            row["nodeid"]
            for row in collection["reports"]
            if row["when"] == "call" and not row.get("subtest", False)
        )
        skipped_setup = Counter(
            row["nodeid"]
            for row in collection["reports"]
            if row["when"] == "setup" and row["outcome"] == "skipped"
        )
        if calls + skipped_setup != expected:
            errors.append("执行 call/skip 身份/重复次数不一致")
        if report.get("tests", {}).get("tests") != sum(expected.values()):
            errors.append("JUnit 用例次数与收集集合不一致")
        effective = collection["effective"]
        if effective["dist"] == "each" or effective["repeat"] != 1:
            errors.append("调度配置改变测试执行次数")
        summary["worker_selection_effective"] = effective
        summary["group"] = "serial" if not effective["numprocesses"] else "xdist"
        if not nodeids or collection["mismatches"]:
            errors.append("测试收集为空或 worker 身份不一致")
        if reference is not None:
            prior = json.loads(reference.read_text(encoding="utf-8"))["collection"]["nodeids"]
            if Counter(prior) != Counter(nodeids):
                errors.append("与参考运行的测试身份/重复次数不一致")
        workers = collection.get("workers", [])
        summary["workers_actual_pytest"] = len(workers)
        inproc_workers = {
            row["worker"]
            for row in report.get("resources", {}).get("inproc", [])
            if row["worker"] != "master"
        }
        if set(workers) != inproc_workers or len(workers) != summary.get("n_workers"):
            errors.append("RSS worker 分类与 pytest 实际 worker 身份/数量不一致")
        if effective["numprocesses"] != len(workers):
            errors.append("配置选择的 worker 数与实际执行数不一致")
        allowed_workers = set(workers) or {"master"}
        if any(row["worker"] not in allowed_workers for row in collection["reports"]):
            errors.append("执行报告出现未收集的 worker 身份")
    except Exception as exc:
        errors.append(f"收集身份门禁无法读取：{exc}")
    try:
        path = out / "coverage.json"
        coverage = json.loads(path.read_text(encoding="utf-8"))
        rows = covgate.load_coverage(path)
        percent = float(coverage["totals"]["percent_covered"])
        floor = covgate.overall_floor()
        failed = [row.module for row in covgate.check(rows)]
        missing = covgate.missing_floors(rows)
        report["coverage"] = {
            "percent": percent,
            "floor": floor,
            "failed_modules": failed,
            "missing_modules": missing,
            "branch": coverage["meta"]["branch_coverage"],
        }
        if (
            not math.isfinite(percent)
            or percent < floor
            or failed
            or missing
            or coverage["meta"]["branch_coverage"] is not True
        ):
            errors.append("覆盖率总量、分支或核心模块门槛未通过")
    except Exception as exc:
        errors.append(f"覆盖率门禁无法读取：{exc}")
    report["ok"] = not errors
    raw_exit = summary.get("exit_code")
    code = raw_exit if type(raw_exit) is int and raw_exit else (1 if errors else 0)
    report["exit_code"] = code
    _write(out / "full-acceptance.json", report)
    return code


def execute(out: Path, args: argparse.Namespace, pytest_args: list[str]) -> dict[str, Any]:
    env = dict(os.environ)
    # 子验收是独立 controller，不能继承外层 pytest worker 的身份。
    for variable in (
        "PYTEST_XDIST_WORKER",
        "PYTEST_XDIST_WORKER_COUNT",
        "PYTEST_XDIST_TESTRUNUID",
        "PYTEST_CURRENT_TEST",
    ):
        env.pop(variable, None)
    env.update(
        {
            "COVERAGE_FILE": str(out / ".coverage"),
            "PYTHONIOENCODING": "utf-8",
            _COLLECTION_ENV: str(out / "collection.json"),
            "MEMBASELINE_OUT": str(out),
            "MEMBASELINE_TAG": "full",
        }
    )
    argv = [
        sys.executable,
        "-X",
        "utf8",
        "-m",
        "pytest",
        "-q",
        "-p",
        "tools.ci.test_suite",
        "-p",
        "tools.probe.mem_baseline",
        "--cov=pdx",
        "--cov-report=json:" + str(out / "coverage.json"),
        "--junitxml=" + str(out / "junit.xml"),
        *pytest_args,
    ]
    environment = {
        name: {
            "present": name in env,
            "sha256": hashlib.sha256(env.get(name, "").encode("utf-8")).hexdigest(),
        }
        for name in (
            "PYTHONPATH",
            "PYTEST_DEBUG_TEMPROOT",
            "COVERAGE_FILE",
            "PYTHONIOENCODING",
            _COLLECTION_ENV,
            "MEMBASELINE_OUT",
            "MEMBASELINE_TAG",
            "SITAI_XDIST_WORKERS",
            "PYTEST_XDIST_AUTO_NUM_WORKERS",
        )
    }
    machine = mem.machine_info()
    physical = mem.sys_mem().get("total_mb")
    if physical is None or physical <= 0:
        raise RuntimeError("无法读取物理内存，看门狗不能安全启用")
    summary: dict[str, Any] = {
        "tag": "full",
        "group": "auto",
        "argv": argv,
        "command": subprocess.list2cmdline(argv),
        "cwd": str(ROOT),
        "machine": machine,
        "environment": environment,
        "environment_sha256": hashlib.sha256(
            json.dumps(environment, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "versions": {
            name: importlib.metadata.version(name)
            for name in ("pytest", "pytest-xdist", "pytest-cov", "coverage")
        },
        "worker_selection_inputs": {
            name: env.get(name) for name in ("SITAI_XDIST_WORKERS", "PYTEST_XDIST_AUTO_NUM_WORKERS")
        },
        "python": sys.version,
        "config_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in (
                "pyproject.toml",
                "pytest.ini",
                ".coveragerc",
                "tests/conftest.py",
                "src/pdx/parallel.py",
                "tools/probe/mem_baseline.py",
            )
            if (ROOT / name).is_file()
        },
        "watch_mb": physical * 0.85,
        "watch_avail_mb": 700.0,
        "cache_before": mem.cache_state(),
        "mem_before": mem.sys_mem(),
        "concurrent_before_mb0": mem.foreign_heavy(0.0, ignore={os.getpid()}),
    }
    _write(out / "invocation.json", summary)
    mem.ensure_quiet(quiet_mb=200.0, min_avail_mb=4096.0, wait_s=0, allow=args.allow_concurrent)
    started = time.monotonic()
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        creationflags = 0
    with (out / "pytest.log").open("w", encoding="utf-8", newline="\n") as log:
        process = subprocess.Popen(
            argv,
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            start_new_session=sys.platform != "win32",
        )
        sampler = None
        timed_out = False
        try:
            sampler = mem.TreeSampler(
                process.pid,
                watch_mb=summary["watch_mb"],
                watch_avail_mb=700.0,
                killer=lambda: mem.kill_tree(process.pid),
            )
            sampler.start()
            try:
                exit_code = process.wait(timeout=args.timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                mem.kill_tree(process.pid)
                exit_code = process.wait(timeout=30)
        except BaseException:
            mem.kill_tree(process.pid)
            process.wait(timeout=30)
            raise
        finally:
            if sampler is not None and sampler.ident is not None:
                stats = sampler.finish()
    if sampler is None:
        raise RuntimeError("RSS 采样器未启动")
    text = (out / "pytest.log").read_text(encoding="utf-8")
    if not args.quiet:
        print(text, end="", flush=True)
    counts, failed = mem.parse_pytest_tail(text)
    summary.update(stats)
    summary["processes"] = sampler.procs_table()
    summary.update(
        {
            "exit_code": exit_code,
            "timed_out": timed_out,
            "wall_s": time.monotonic() - started,
            "counts": counts,
            "failed_names": failed,
            "randomly_seed": mem.parse_randomly_seed(text),
            "cache_after": mem.cache_state(),
            "mem_after": mem.sys_mem(),
            "concurrent_after_mb0": mem.foreign_heavy(0.0, ignore={os.getpid()}),
        }
    )
    (out / "samples.csv").write_text(sampler.timeline_csv(), encoding="utf-8", newline="\n")
    (out / "procs.csv").write_text(sampler.procs_csv(), encoding="utf-8", newline="\n")
    _write(out / "resource-summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    # 此模块也是早期 pytest 插件；业务导入只能发生在父进程入口，保持导入期覆盖。
    from pdx.console import enable_utf8_stdio  # noqa: PLC0415

    enable_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=ROOT / "tools/out/test-runs")
    parser.add_argument("--timeout-s", type=float, default=3600.0)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--allow-concurrent", action="store_true")
    parser.add_argument("--reference", type=Path)
    raw = list(sys.argv[1:] if argv is None else argv)
    split = raw.index("--") if "--" in raw else len(raw)
    args = parser.parse_args(raw[:split])
    try:
        pytest_args = validate_pytest_args(raw[split + 1 :])
        if os.environ.get("PYTEST_ADDOPTS"):
            raise ValueError("完整验收拒绝外部 PYTEST_ADDOPTS；请显式声明诊断参数")
        if os.environ.get("PYTEST_PLUGINS") or os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD"):
            raise ValueError("完整验收拒绝外部插件覆盖")
        if any(
            os.environ.get(name)
            for name in ("COVERAGE_RCFILE", "COVERAGE_PROCESS_START", "COVERAGE_PROCESS_CONFIG")
        ):
            raise ValueError("完整验收拒绝外部覆盖率配置覆盖")
        if not math.isfinite(args.timeout_s) or not 0 < args.timeout_s <= 3600:
            raise ValueError("timeout-s 必须在 (0, 3600]，不得提高原验收预算")
    except ValueError as exc:
        parser.error(str(exc))
    out = create_run_dir(args.output_root)
    print(f"[full-acceptance] 输出目录：{out}", flush=True)
    try:
        summary = execute(out, args, pytest_args)
    except (Exception, SystemExit) as exc:
        summary = {"tag": "full", "exit_code": 2, "execution_error": str(exc)}
    code = finalize(out, summary, reference=args.reference)
    print(f"[full-acceptance] exit={code}，报告：{out / 'full-acceptance.json'}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
