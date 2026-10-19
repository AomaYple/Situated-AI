"""完整验收在一个运行目录汇合报告，任何失败都不能被后续门禁覆盖。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pdx import covgate
from tools.ci import test_suite


def test_plugin_import_does_not_preload_business_modules_before_coverage():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import tools.ci.test_suite; "
                "assert not any(name == 'pdx' or name.startswith('pdx.') for name in sys.modules)"
            ),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _evidence(out: Path, *, skipped="", failures=False, collected=True):
    out.mkdir(parents=True, exist_ok=True)
    case = '<testcase classname="unit" name="test_ok">'
    if skipped:
        case += f'<skipped message="{skipped}"/>'
    if failures:
        case += '<failure message="broken"/>'
    (out / "junit.xml").write_text(
        "<testsuite>" + case + "</testcase></testsuite>", encoding="utf-8"
    )
    files = {
        "src/" + module: {
            "summary": {
                "percent_covered": 100,
                "num_statements": 1,
                "covered_lines": 1,
                "num_branches": 0,
                "covered_branches": 0,
            }
        }
        for module in covgate.FLOORS
    }
    (out / "coverage.json").write_text(
        json.dumps(
            {
                "meta": {"branch_coverage": True},
                "files": files,
                "totals": {"percent_covered": 100},
            }
        ),
        encoding="utf-8",
    )
    (out / "collection.json").write_text(
        json.dumps(
            {
                "nodeids": ["tests/a.py::test_ok"] if collected else [],
                "mismatches": [],
                "workers": [],
                "exitstatus": 0,
                "started": ["tests/a.py::test_ok"],
                "finished": ["tests/a.py::test_ok"],
                "reports": [
                    {
                        "nodeid": "tests/a.py::test_ok",
                        "when": phase,
                        "outcome": "passed",
                        "worker": "master",
                    }
                    for phase in ("setup", "call", "teardown")
                ],
                "effective": {"numprocesses": 0, "dist": "no", "repeat": 1},
            }
        ),
        encoding="utf-8",
    )
    (out / "inproc-full-master.json").write_text(
        json.dumps(
            {
                "worker": "master",
                "pid": 123,
                "peak_ws_mb": 50,
                "final_ws_mb": 40,
                "errors": [],
                "exitstatus": 0,
            }
        ),
        encoding="utf-8",
    )
    return {
        "tag": "full",
        "exit_code": 0,
        "n_workers": 0,
        "controller_pid": 123,
        "worker_pids": [],
        "processes": [{"pid": 123, "hwm_mb": 50, "role": "root"}],
        "peak_total_mb": 100,
        "per_worker_peak_mb": 50,
        "samples": 3,
        "sampler_errors": [],
        "killed_by_watchdog": False,
        "timed_out": False,
    }


def test_success_and_independent_run_directories(tmp_path):
    first = test_suite.create_run_dir(tmp_path)
    second = test_suite.create_run_dir(tmp_path)
    assert first != second
    summary = _evidence(first)
    assert test_suite.finalize(first, summary) == 0
    report = json.loads((first / "full-acceptance.json").read_text(encoding="utf-8"))
    assert report["collection"]["nodeids"] == ["tests/a.py::test_ok"]
    assert report["tests"]["tests"] == 1
    assert report["ok"] is True
    assert not (second / "full-acceptance.json").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("exit_code", 5),
        ("exit_code", -15),
        ("timed_out", True),
        ("killed_by_watchdog", True),
        ("sampler_errors", ["denied"]),
        ("samples", 0),
        ("peak_total_mb", 100000),
        ("per_worker_peak_mb", 100000),
    ],
)
def test_process_and_resource_failures_cannot_pass(tmp_path, field, value):
    summary = _evidence(tmp_path)
    summary[field] = value
    code = test_suite.finalize(tmp_path, summary)
    assert code != 0
    if field == "exit_code":
        assert code == value
    report = json.loads((tmp_path / "full-acceptance.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["groups"][0][field] == value


@pytest.mark.parametrize(
    "broken",
    [
        "unknown_skip",
        "empty_collection",
        "empty_junit",
        "core",
        "overall",
        "branch",
        "missing",
        "malformed",
        "identity",
    ],
)
def test_all_gates_fail_closed_and_keep_other_reports(tmp_path, broken):
    summary = _evidence(
        tmp_path,
        skipped="unclassified" if broken == "unknown_skip" else "",
        collected=broken != "empty_collection",
    )
    if broken == "empty_junit":
        (tmp_path / "junit.xml").write_text("<testsuite/>", encoding="utf-8")
    elif broken in {"missing", "malformed"}:
        (tmp_path / "coverage.json").unlink()
        if broken == "malformed":
            (tmp_path / "coverage.json").write_text("{", encoding="utf-8")
    elif broken in {"core", "overall", "branch"}:
        path = tmp_path / "coverage.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        if broken == "core":
            data["files"] = {}
        elif broken == "overall":
            data["totals"]["percent_covered"] = 85
        else:
            data["meta"]["branch_coverage"] = False
        path.write_text(json.dumps(data), encoding="utf-8")
    elif broken == "identity":
        (tmp_path / "collection.json").write_text(
            '{"nodeids":["a"],"mismatches":["gw1"]}', encoding="utf-8"
        )
    assert test_suite.finalize(tmp_path, summary) != 0
    report = json.loads((tmp_path / "full-acceptance.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["errors"]
    assert "tests" in report
    assert "verdict" in report
    assert (tmp_path / "test-summary.json").exists()


def test_multiple_failures_are_all_preserved(tmp_path):
    summary = _evidence(tmp_path, skipped="unexplained", failures=True)
    summary["exit_code"] = 1
    (tmp_path / "coverage.json").unlink()
    assert test_suite.finalize(tmp_path, summary) == 1
    report = json.loads((tmp_path / "full-acceptance.json").read_text(encoding="utf-8"))
    assert len(report["errors"]) >= 3
    assert report["tests"]["failures"] == 1
    assert report["tests"]["unknown_skip_reasons"]


@pytest.mark.parametrize(
    "args",
    [
        ["tests/a.py"],
        ["-k", "yes"],
        ["-m", "unit"],
        ["--ignore=x"],
        ["--deselect=x"],
        ["--lf"],
        ["--no-cov"],
        ["-o", "addopts="],
        ["-p", "no:cov"],
        ["--cov-fail-under=0"],
        ["-c", "other.ini"],
        ["--dist=each"],
        ["--dist", "each"],
        ["--dist=invalid"],
        ["-n", "2", "--numprocesses=3"],
        ["--dist=loadscope", "--dist=loadfile"],
        ["--count=2"],
    ],
)
def test_full_profile_rejects_selection_or_gate_overrides(args):
    with pytest.raises(ValueError, match=r"完整验收|pytest 参数"):
        test_suite.validate_pytest_args(args)


def test_diagnostic_arguments_preserve_windows_argument_boundaries():
    args = ["-n", "0", "--dist=loadscope", "--randomly-seed", "42"]
    assert test_suite.validate_pytest_args(args) == args


@pytest.mark.parametrize("workers", [0, 2])
@pytest.mark.parametrize("subtest_failure", [False, True])
def test_real_pytest_records_collection_multiplicity_and_reports(
    tmp_path, monkeypatch, workers, subtest_failure
):
    project = tmp_path / "project with 空格"
    project.mkdir()
    (project / "pytest.ini").write_text(f"[pytest]\naddopts = -n {workers}\n", encoding="utf-8")
    (project / "collect_probe.py").write_text("def test_probe():\n    pass\n", encoding="utf-8")
    (project / "test_example.py").write_text(
        "import pytest\n@pytest.mark.parametrize('value',[1,2],ids=['a','a'])\n"
        "def test_example(value, subtests):\n"
        "    import os, subprocess, sys\n"
        "    from pathlib import Path\n"
        "    from pdx.console import enable_utf8_stdio\n"
        "    enable_utf8_stdio()\n"
        "    assert 'SITAI_TEST_COLLECTION' not in os.environ\n"
        "    assert 'MEMBASELINE_OUT' not in os.environ\n"
        "    child = subprocess.run([sys.executable, '-c',\n"
        "        \"import os; assert 'SITAI_TEST_COLLECTION' not in os.environ; \"\n"
        "        \"assert 'MEMBASELINE_OUT' not in os.environ; assert 'COVERAGE_FILE' not in os.environ\"], check=False)\n"
        "    assert child.returncode == 0\n"
        "    if value == 1:\n"
        "        child = subprocess.run([sys.executable, '-m', 'pytest', '--collect-only', '-q', '-n0',\n"
        "            '-p', 'tools.ci.test_suite', '-p', 'tools.probe.mem_baseline', 'collect_probe.py'],\n"
        "            capture_output=True, text=True, encoding='utf-8', check=False)\n"
        "        assert child.returncode == 0, child.stdout + child.stderr\n"
        "    for child in (1, 2):\n"
        "        with subtests.test(child=child):\n"
        f"            assert not {subtest_failure!r} or child != 2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(test_suite, "ROOT", project)
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gwInherited")
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
    out = test_suite.create_run_dir(tmp_path / "reports")
    summary = test_suite.execute(
        out, Namespace(timeout_s=30, quiet=True, allow_concurrent=True), []
    )
    collection = json.loads((out / "collection.json").read_text(encoding="utf-8"))
    assert len(collection["nodeids"]) == 2
    assert set(collection["counts"].values()) == {1}
    assert collection["nodeids"][0].startswith("test_example.py::test_example[")
    assert collection["mismatches"] == []
    assert collection["started_counts"] == collection["counts"]
    assert collection["finished_counts"] == collection["counts"]
    primary = [row for row in collection["reports"] if not row["subtest"]]
    children = [row for row in collection["reports"] if row["subtest"]]
    assert len(primary) == 6
    assert len(children) == 4
    assert any(row["outcome"] == "failed" for row in children) is subtest_failure
    assert collection["effective"]["numprocesses"] == workers
    assert len(collection["workers"]) == workers
    assert "environment_sha256" in summary
    assert summary["versions"]["pytest-xdist"]
    assert len(list(out.glob("inproc-full-*.json"))) == workers + 1
    # 假装继承外层 worker 也必须创建独立 master 证据。
    assert (out / "inproc-full-master.json").is_file()
    assert summary["samples"] > 0
    assert (out / "coverage.json").is_file()
    assert (out / "junit.xml").is_file()
    assert (out / "samples.csv").is_file()
    assert summary["exit_code"] == (1 if subtest_failure else 0)
    assert type(summary["controller_pid"]) is int
    assert len(summary["worker_pids"]) == workers
    if not subtest_failure:
        resources = test_suite._resource_evidence(out, summary)
        assert len(resources["peak_pairs"]) == workers + 1
        assert resources["execution_peak_mb"] > 0
    assert test_suite.finalize(out, summary) != 0  # 小项目不能冒充完整覆盖率验收。
    assert not summary["timed_out"]


def test_collection_hook_retains_repeated_ids_and_worker_disagreement(tmp_path, monkeypatch):
    monkeypatch.setenv("SITAI_TEST_COLLECTION", str(tmp_path / "collection.json"))
    config = SimpleNamespace()
    test_suite.pytest_configure(config)
    node = SimpleNamespace(config=config, gateway=SimpleNamespace(id="gw0"))
    test_suite.pytest_xdist_node_collection_finished(node, ["test_a", "test_a", "test_b"])
    node.gateway.id = "gw1"
    test_suite.pytest_xdist_node_collection_finished(node, ["test_a", "test_b"])
    test_suite.pytest_sessionfinish(SimpleNamespace(config=config), 0)
    report = json.loads((tmp_path / "collection.json").read_text(encoding="utf-8"))
    assert report["nodeids"] == ["test_a", "test_a", "test_b"]
    assert report["counts"] == {"test_a": 2, "test_b": 1}
    assert report["mismatches"] == ["gw1"]


def test_silent_subprocess_timeout_is_reported(tmp_path, monkeypatch):
    project = tmp_path / "silent"
    project.mkdir()
    (project / "pytest.ini").write_text("[pytest]\naddopts = -n 0\n", encoding="utf-8")
    (project / "test_wait.py").write_text(
        "import time\ndef test_wait():\n    time.sleep(30)\n", encoding="utf-8"
    )
    monkeypatch.setattr(test_suite, "ROOT", project)
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
    out = test_suite.create_run_dir(tmp_path / "reports")
    summary = test_suite.execute(out, Namespace(timeout_s=2, quiet=True, allow_concurrent=True), [])
    assert summary["timed_out"] is True
    assert summary["exit_code"] != 0
    assert summary["wall_s"] < 15
    assert (out / "resource-summary.json").is_file()


@pytest.mark.parametrize("bad", [None, float("nan"), -1, "unknown", True])
def test_invalid_resource_measurement_fails_without_losing_junit(tmp_path, bad):
    summary = _evidence(tmp_path)
    summary["peak_total_mb"] = bad
    assert test_suite.finalize(tmp_path, summary) != 0
    report = json.loads((tmp_path / "full-acceptance.json").read_text(encoding="utf-8"))
    assert report["tests"]["tests"] == 1
    assert report["ok"] is False


def test_reference_compares_duplicate_multiplicity(tmp_path):
    summary = _evidence(tmp_path)
    reference = tmp_path / "prior.json"
    reference.write_text(
        '{"collection":{"nodeids":["tests/a.py::test_ok","tests/a.py::test_ok"]}}', encoding="utf-8"
    )
    assert test_suite.finalize(tmp_path, summary, reference=reference) != 0
    report = json.loads((tmp_path / "full-acceptance.json").read_text(encoding="utf-8"))
    assert any("重复次数" in error for error in report["errors"])


@pytest.mark.parametrize(
    "variable",
    [
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
        "COVERAGE_RCFILE",
        "COVERAGE_PROCESS_START",
        "COVERAGE_PROCESS_CONFIG",
    ],
)
def test_external_selection_and_coverage_config_rejected_before_start(
    tmp_path, monkeypatch, variable
):
    def unexpected_launch(*_args):
        raise AssertionError("验证失败前不能启动测试")

    monkeypatch.setattr(test_suite, "execute", unexpected_launch)
    monkeypatch.setenv(variable, "untrusted")
    out = tmp_path / "runs"
    with pytest.raises(SystemExit) as caught:
        test_suite.main(["--output-root", str(out)])
    assert caught.value.code == 2
    assert not out.exists()


def test_main_keeps_launch_failure_report(tmp_path, monkeypatch):
    def unavailable(*_args):
        raise OSError("启动失败")

    monkeypatch.setattr(test_suite, "execute", unavailable)
    assert test_suite.main(["--output-root", str(tmp_path)]) == 2
    reports = list(tmp_path.glob("*/full-acceptance.json"))
    assert len(reports) == 1
    payload = json.loads(reports[0].read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["groups"][0]["execution_error"] == "启动失败"


@pytest.mark.parametrize(
    "broken", ["missing", "pid", "workers", "peak", "error", "exit", "external", "role"]
)
def test_inproc_resource_disagreement_fails_closed(tmp_path, broken):
    summary = _evidence(tmp_path)
    path = tmp_path / "inproc-full-master.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if broken == "missing":
        path.unlink()
    elif broken == "external":
        summary["processes"] = []
    elif broken == "role":
        summary["processes"][0]["role"] = "helper"
    else:
        key, value = {
            "pid": ("pid", 456),
            "workers": ("worker", "gw0"),
            "peak": ("peak_ws_mb", float("nan")),
            "error": ("errors", ["sampling failed"]),
            "exit": ("exitstatus", 1),
        }[broken]
        payload[key] = value
        path.write_text(json.dumps(payload), encoding="utf-8")
    assert test_suite.finalize(tmp_path, summary) != 0
    report = json.loads((tmp_path / "full-acceptance.json").read_text(encoding="utf-8"))
    assert report["tests"]["tests"] == 1
    assert not report["ok"]


@pytest.mark.parametrize("source", ["external", "inproc"])
def test_serial_executor_uses_per_process_budget_below_tree_budget(tmp_path, source):
    summary = _evidence(tmp_path)
    summary["peak_total_mb"] = 1800
    if source == "external":
        summary["processes"][0]["hwm_mb"] = 1700
    else:
        path = tmp_path / "inproc-full-master.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["peak_ws_mb"] = 1700
        path.write_text(json.dumps(payload), encoding="utf-8")
    assert test_suite.finalize(tmp_path, summary) != 0
    report = json.loads((tmp_path / "full-acceptance.json").read_text(encoding="utf-8"))
    checks = {check["name"]: check for check in report["verdict"][0]["checks"]}
    assert checks["peak_total_mb"]["ok"]
    assert not checks["per_worker_peak_mb"]["ok"]
    assert summary["per_worker_peak_mb"] == 50  # 原始外部读数仍保留。


@pytest.mark.parametrize(
    "broken",
    ["started", "finished", "setup", "call", "teardown", "worker", "each", "count", "selected"],
)
def test_actual_execution_identity_and_multiplicity_are_gated(tmp_path, broken):
    summary = _evidence(tmp_path)
    path = tmp_path / "collection.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if broken in {"started", "finished"}:
        data[broken] *= 2
    elif broken in {"setup", "call", "teardown"}:
        data["reports"] += [row for row in data["reports"] if row["when"] == broken]
    elif broken == "worker":
        data["reports"][0]["worker"] = "gwUnexpected"
    else:
        key, value = {
            "each": ("dist", "each"),
            "count": ("repeat", 2),
            "selected": ("numprocesses", 1),
        }[broken]
        data["effective"][key] = value
    path.write_text(json.dumps(data), encoding="utf-8")
    assert test_suite.finalize(tmp_path, summary) != 0
    report = json.loads((tmp_path / "full-acceptance.json").read_text(encoding="utf-8"))
    assert report["errors"]
    assert report["tests"]["tests"] == 1


@pytest.mark.parametrize(("option", "value"), [("dist", "each"), ("count", 2)])
def test_effective_configuration_rejects_inherited_repetition(tmp_path, monkeypatch, option, value):
    monkeypatch.setenv("SITAI_TEST_COLLECTION", str(tmp_path / "collection.json"))
    config = SimpleNamespace(option=SimpleNamespace(**{option: value}))
    with pytest.raises(pytest.UsageError, match="重复执行"):
        test_suite.pytest_configure(config)


def test_sampler_startup_failure_stops_started_child(tmp_path, monkeypatch):
    process = Mock(pid=123)
    sampler = Mock(ident=None)
    sampler.start.side_effect = OSError("sampler start failed")
    monkeypatch.setattr(test_suite.mem, "TreeSampler", Mock(return_value=sampler))
    monkeypatch.setattr(test_suite.subprocess, "Popen", Mock(return_value=process))
    kill = Mock()
    monkeypatch.setattr(test_suite.mem, "kill_tree", kill)
    monkeypatch.setattr(test_suite.mem, "ensure_quiet", Mock())
    with pytest.raises(OSError, match="sampler start failed"):
        test_suite.execute(tmp_path, Namespace(timeout_s=30, quiet=True, allow_concurrent=True), [])
    kill.assert_called_once_with(123)
    process.wait.assert_called_once_with(timeout=30)


def test_subtest_reports_do_not_count_as_duplicate_test_invocations(tmp_path):
    summary = _evidence(tmp_path)
    path = tmp_path / "collection.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["reports"].extend(
        [
            {
                "nodeid": "tests/a.py::test_ok",
                "when": "call",
                "outcome": "passed",
                "worker": "master",
                "subtest": True,
            },
            {
                "nodeid": "tests/a.py::test_ok",
                "when": "call",
                "outcome": "passed",
                "worker": "master",
                "subtest": True,
            },
        ]
    )
    path.write_text(json.dumps(data), encoding="utf-8")
    assert test_suite.finalize(tmp_path, summary) == 0


def test_failed_subtest_event_cannot_be_hidden_by_successful_junit(tmp_path):
    summary = _evidence(tmp_path)
    path = tmp_path / "collection.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["reports"].append(
        {
            "nodeid": "tests/a.py::test_ok",
            "when": "call",
            "outcome": "failed",
            "worker": "master",
            "subtest": True,
        }
    )
    path.write_text(json.dumps(data), encoding="utf-8")
    assert test_suite.finalize(tmp_path, summary) != 0
    report = json.loads((tmp_path / "full-acceptance.json").read_text(encoding="utf-8"))
    assert any("子断言" in error for error in report["errors"])


def test_test_subprocess_environment_isolated_and_restored(monkeypatch):
    names = [
        "MEMBASELINE_OUT",
        "MEMBASELINE_TAG",
        "SITAI_TEST_COLLECTION",
        "COVERAGE_FILE",
        "COV_CORE_DATAFILE",
    ]
    for name in names:
        monkeypatch.setenv(name, "outer-evidence")
    item = SimpleNamespace(config=SimpleNamespace(_sitai_collection={}))
    protocol = test_suite.pytest_runtest_protocol(item)
    next(protocol)
    assert all(name not in os.environ for name in names)
    with pytest.raises(StopIteration):
        next(protocol)
    assert all(os.environ[name] == "outer-evidence" for name in names)
