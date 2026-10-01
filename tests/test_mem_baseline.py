"""`tools/probe/mem_baseline.py` 的第一批用例（B107 / B108 / B109 三条硬伤的看门狗）。

为什么要单独给它开一个文件：它是一把**量尺**，而量尺自己的三条硬伤已经真实咬过两次
（`t13`：单组 `run` 把冻结的多组基线截断成一组；同一 tag 的第二条臂把第一条臂的明细覆盖掉），
第三条是**跨平台硬伤**（`t14` 实测：GBK 控制台下 `print('✅')` 抛 `UnicodeEncodeError` ⇒
同一条命令在 Windows 默认控制台判红、在 UTF-8 环境判绿）。它此前**一个用例都没有**。
三条逐条登记在 `docs/design/backlog.md` 附⑤（B107 / B108 / B109）。

⚠️ 本文件**不碰** `tools/out/mem/` 下任何冻结文件：单测把模块的 `OUT_DIR` 指到 `tmp_path`，
子进程用例显式把 `--index` 指到临时目录（`check` 只读不写）。
"""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import pytest

from pdx import config

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path
    from types import ModuleType

pytestmark = pytest.mark.unit

_SCRIPT = config.REPO / "tools" / "probe" / "mem_baseline.py"
_IS_WIN = sys.platform == "win32"


def _load() -> ModuleType:
    """按路径 import（`tools/probe/` 不是包 —— 与 `test_probe_stage3.py` 同法）。"""
    spec = importlib.util.spec_from_file_location("probe_mem_baseline", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mem(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    """加载被测脚本，并把**产物目录指到临时目录**（冻结基线一个字节都不许动）。"""
    module = _load()
    monkeypatch.setattr(module, "OUT_DIR", tmp_path)
    return module


# ────────────────────────── 造数：一份「达标」的组读数与索引 ──────────────────────────


def _summary(*, tag: str, group: str, peak: float = 900.0, per_worker: float = 100.0) -> dict:
    """一份能过 `judge()` 的组读数（n=4 ⇒ 上限 1024+4×512）。"""
    return {
        "tag": tag,
        "group": group,
        "n_workers": 4,
        "peak_total_mb": peak,
        "per_worker_peak_mb": per_worker,
        "sum_hwm_mb": peak * 2,
        "exit_code": 0,
        "counts": {"passed": 10},
        "worker_pids": [11, 12, 13, 14],
        "killed_by_watchdog": False,
        "killed_reason": "",
        "classifier_note": "test",
        "wall_s": 1.0,
        "randomly_seed": None,
    }


def _write_index(path: Path, pairs: Sequence[tuple[str, str]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": "test",
        "covers_groups": [group for _tag, group in pairs],
        "groups": [_summary(tag=tag, group=group) for tag, group in pairs],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_psutil_reader_self_and_missing_process(mem) -> None:
    reader = mem.MemReader()
    sample = reader.read(os.getpid())
    assert sample is not None
    assert sample[0] > 0
    assert reader.read_cpu(os.getpid()) is not None
    assert reader.read(2147483647) is None
    assert reader.read_cpu(2147483647) is None
    reader.close()
    assert any(pid == os.getpid() for pid, _parent, _name in mem.list_procs())
    assert mem.sys_mem()["total_mb"] > 0
    assert mem.sys_mem()["commit_mb"] is None


def module_artifact_stem(mem: ModuleType, tag: str, group: str) -> str:
    """被测脚本的命名函数（单测只经这一个入口取前缀，免得两处各写一遍）。"""
    stem: str = mem.artifact_stem(tag, group)
    return stem


def _args(mem: ModuleType, argv: Sequence[str]) -> Any:
    """按命令行那套解析参数（`build_parser` 是动态属性 ⇒ 返回 Any，别装成 Namespace）。"""
    parsed: Any = mem.build_parser().parse_args(list(argv))
    return parsed


def _fake_pipeline(
    mem: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> list[tuple[str, str | None]]:
    """把 `run` 的重活（真跑 pytest + 采样）换掉，只留**落盘与索引**这条路径。

    返回一个记录 `(group, stem)` 的列表：用它断言「拒绝时一次都没跑」。
    """
    calls: list[tuple[str, str | None]] = []

    def fake_run_group(group: str, *, tag: str | None = None, **kwargs: object) -> dict:
        stem = module_artifact_stem(mem, tag or group, group)
        calls.append((group, stem))
        return _summary(tag=stem, group=group)

    monkeypatch.setattr(mem, "sys_mem", lambda: {"total_mb": 16000.0})
    monkeypatch.setattr(mem, "cache_state", lambda: {"layout": "test"})
    monkeypatch.setattr(mem, "machine_info", lambda: {"cpu": "test"})
    monkeypatch.setattr(mem, "run_group", fake_run_group)
    return calls


# ────────────────────────── B107：单组 run 不许动冻结索引 ──────────────────────────


def test_单组run默认写自己的json而冻结索引逐字节不变(
    mem: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B107 的主判据：**跑完之后冻结索引的 sha256 不变**。"""
    frozen = mem.OUT_DIR / "baseline.json"
    before = _write_index(frozen, [("n4", "n4"), ("n4-nocache", "n4-nocache"), ("n1", "n1")])
    calls = _fake_pipeline(mem, monkeypatch)

    assert mem.cmd_run(_args(mem, ["run", "--groups", "n4-nocache"])) == 0
    assert calls == [("n4-nocache", "n4-nocache")]
    assert _sha(frozen) == before, "单组 run 把冻结索引改了（B107 复发）"
    own = mem.OUT_DIR / "n4-nocache.json"
    assert own.is_file(), "单组的索引应当落在 <前缀>.json 上"
    assert json.loads(own.read_text(encoding="utf-8"))["covers_groups"] == ["n4-nocache"]


def test_多组run仍然写baseline并写明覆盖了哪几组(
    mem: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_pipeline(mem, monkeypatch)
    assert mem.cmd_run(_args(mem, ["run", "--groups", "n4,n4-nocache"])) == 0
    payload = json.loads((mem.OUT_DIR / "baseline.json").read_text(encoding="utf-8"))
    assert payload["covers_groups"] == ["n4", "n4-nocache"], "索引必须写明自己覆盖哪几组"


def test_默认路径由组数决定() -> None:
    mem = _load()
    assert mem.default_index_path(["n4"], ["n4"]).name == "n4.json"
    assert mem.default_index_path(["n4", "n1"], ["n4", "n1"]).name == "baseline.json"


def test_要覆盖更全的索引时拒绝而且一次都不跑(
    mem: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """显式指到冻结索引上也不行 —— 除非 `--force`。"""
    frozen = mem.OUT_DIR / "baseline.json"
    before = _write_index(frozen, [("n4", "n4"), ("n4-nocache", "n4-nocache"), ("n1", "n1")])
    calls = _fake_pipeline(mem, monkeypatch)

    rc = mem.cmd_run(_args(mem, ["run", "--groups", "n4", "--index", str(frozen)]))
    assert rc == 2, "覆盖更全的索引必须拒绝（exit 2）"
    assert calls == [], "拒绝要发生在跑之前（跑完一小时才拒绝 = 白跑）"
    assert _sha(frozen) == before
    err = capsys.readouterr().err
    assert "拒绝覆盖索引" in err
    assert "--force" in err, "拒绝时必须写出两条走法（换路径 / --force）"


def test_force越过闸门是有意的覆盖(mem: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    frozen = mem.OUT_DIR / "baseline.json"
    _write_index(frozen, [("n4", "n4"), ("n4-nocache", "n4-nocache"), ("n1", "n1")])
    _fake_pipeline(mem, monkeypatch)

    assert (
        mem.cmd_run(_args(mem, ["run", "--groups", "n4", "--index", str(frozen), "--force"])) == 0
    )
    payload = json.loads(frozen.read_text(encoding="utf-8"))
    assert payload["covers_groups"] == ["n4"], "--force 之后覆盖是**写明的**行为，不是意外"


def test_重跑同一组允许覆盖自己的索引(mem: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """单组索引重跑两次是正常迭代，不该被闸门挡住。"""
    _fake_pipeline(mem, monkeypatch)
    assert mem.cmd_run(_args(mem, ["run", "--groups", "n4"])) == 0
    assert mem.cmd_run(_args(mem, ["run", "--groups", "n4"])) == 0
    assert json.loads((mem.OUT_DIR / "n4.json").read_text(encoding="utf-8"))["covers_groups"] == [
        "n4"
    ]


def test_闸门对读不出的索引也不放行(mem: ModuleType) -> None:
    bad = mem.OUT_DIR / "broken.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{ 这不是 JSON", encoding="utf-8", newline="\n")
    reason = mem.index_overwrite_guard(bad, ["n4"], force=False)
    assert reason is not None
    assert "读不出组清单" in reason
    assert mem.index_overwrite_guard(bad, ["n4"], force=True) is None


# ────────────────────────── B108：同一 tag 的两条臂互不覆盖 ──────────────────────────


def test_产物前缀在tag与组名不同时带上组名() -> None:
    mem = _load()
    assert mem.artifact_stem("n4", "n4") == "n4", "日常用法（tag = 组名）路径不许变"
    assert mem.artifact_stem("arm", "n4") == "arm-n4"
    assert mem.artifact_stem("arm", "n4-nocache") == "arm-n4-nocache"


def test_两组产物的路径两两不同() -> None:
    mem = _load()
    first = set(mem.group_artifact_paths(mem.artifact_stem("arm", "n4")).values())
    second = set(mem.group_artifact_paths(mem.artifact_stem("arm", "n4-nocache")).values())
    assert len(first) == 4
    assert not (first & second), "同一个 tag 的两条臂不许有任何一个同名产物"


class _FakePipe:
    """假的子进程：`run_group` 只用到 pid / stdout / wait。"""

    def __init__(self, pid: int, lines: Sequence[str]) -> None:
        self.pid = pid
        self.stdout = list(lines)
        self.returncode: int | None = None

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.returncode = 0
        return 0


class _FakeLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.text = ""

    def write(self, line: str) -> None:
        self.text += line

    def close(self) -> None:
        self.path.write_text(self.text, encoding="utf-8", newline="\n")


class _FakeSampler:
    """假采样器：返回一份固定的统计与两张 CSV（内容带**本次序号**，两次跑必然不同）。"""

    def __init__(self, run_index: int, **kwargs: object) -> None:
        self.run_index = run_index
        self.kwargs = kwargs

    def start(self) -> None:
        return None

    def finish(self) -> dict:
        return {
            "n_workers": 4,
            "worker_pids": [11, 12, 13, 14],
            "peak_total_mb": 900.0,
            "per_worker_peak_mb": 100.0,
            "sum_hwm_mb": 1800.0,
            "killed_by_watchdog": False,
            "kill_reason": "",
            "classifier_note": "fake",
        }

    def procs_table(self) -> list[dict]:
        return [{"pid": 11, "hwm_mb": 100.0}]

    def timeline_csv(self) -> str:
        return f"t_s,nproc,total_rss_mb\n0,4,run{self.run_index}\n"

    def procs_csv(self) -> str:
        return f"pid,name,role,hwm_mb\n11,worker,worker,{self.run_index}\n"


def _fake_run_pipeline(mem: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """把 `run_group` 里真正起进程的那几件换掉，**保留**落盘 / 命名 / 摘要这条路径。"""
    monkeypatch.setattr(mem, "foreign_heavy", lambda *_a, **_k: [])
    monkeypatch.setattr(mem, "ensure_quiet", lambda **_k: None)
    monkeypatch.setattr(mem, "kill_tree", lambda _pid: None)
    monkeypatch.setattr(mem, "sys_mem", lambda: {"total_mb": 16000.0})
    monkeypatch.setattr(mem, "machine_info", lambda: {"cpu": "test"})

    def fake_spawn(
        argv: Sequence[str], env: dict[str, str], log_path: Path
    ) -> tuple[_FakePipe, _FakeLog]:
        del argv, env
        return _FakePipe(4242, ["5 passed in 1.0s\n"]), _FakeLog(log_path)

    monkeypatch.setattr(mem, "spawn", fake_spawn)

    runs = itertools.count(1)

    def fake_sampler(
        pid: int,
        *,
        interval_s: float,
        watch_mb: float,
        watch_avail_mb: float,
        killer: object,
    ) -> _FakeSampler:
        del pid, interval_s, watch_mb, watch_avail_mb, killer
        return _FakeSampler(next(runs))

    monkeypatch.setattr(mem, "TreeSampler", fake_sampler)


def test_同一tag的两条臂明细同时存在且内容不同(
    mem: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B108 的主判据：连跑两组之后，两组的 summary/procs/samples 都还在，且内容不同。"""
    _fake_run_pipeline(mem, monkeypatch)

    first = mem.run_group(
        "n4",
        tag="arm",
        target="tests",
        inproc=False,
        interval_ms=250,
        timeout_s=60.0,
        watch_mb=1000.0,
        watch_avail_mb=700.0,
        quiet_poll_mb=200.0,
        min_avail_mb=1024.0,
        wait_s=0.0,
        allow_concurrent=True,
        echo=False,
    )
    second = mem.run_group(
        "n4-nocache",
        tag="arm",
        target="tests",
        inproc=False,
        interval_ms=250,
        timeout_s=60.0,
        watch_mb=1000.0,
        watch_avail_mb=700.0,
        quiet_poll_mb=200.0,
        min_avail_mb=1024.0,
        wait_s=0.0,
        allow_concurrent=True,
        echo=False,
    )

    stems = [mem.artifact_stem("arm", "n4"), mem.artifact_stem("arm", "n4-nocache")]
    for stem in stems:
        paths = mem.group_artifact_paths(stem)
        for name in ("summary", "procs", "samples", "log"):
            assert paths[name].is_file(), f"{stem} 的 {name} 没了（B108 复发）"
    assert mem.group_artifact_paths(stems[0])["procs"].read_text(
        encoding="utf-8"
    ) != mem.group_artifact_paths(stems[1])["procs"].read_text(encoding="utf-8")
    assert first["group"] == "n4"
    assert second["group"] == "n4-nocache"
    assert set(second["groups_seen"]) == {"n4", "n4-nocache"}, (
        "summary 里要读得出「本 tag 跑过哪些组」（顺序按文件名，别把顺序也钉死）"
    )
    assert second["tag_arg"] == "arm", "认亲用的是用户给的那个 tag，不是产物前缀"
    assert set(second["artifacts"]) == {"summary", "procs", "samples", "log"}


def test_同tag的两条臂在索引里也是两个条目(
    mem: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_pipeline(mem, monkeypatch)

    assert mem.cmd_run(_args(mem, ["run", "--groups", "n4", "--tag", "arm"])) == 0
    assert mem.cmd_run(_args(mem, ["run", "--groups", "n4-nocache", "--tag", "arm"])) == 0
    # 索引也跟着**产物前缀**走（与明细同前缀）：两条臂各有各的索引，谁也不覆盖谁。
    first = json.loads((mem.OUT_DIR / "arm-n4.json").read_text(encoding="utf-8"))
    second = json.loads((mem.OUT_DIR / "arm-n4-nocache.json").read_text(encoding="utf-8"))
    assert first["covers_groups"] == ["n4"]
    assert second["covers_groups"] == ["n4-nocache"]
    assert "arm" not in mem.GROUPS, (
        "别名不该被塞进全局组表（`--tag` 与真组名撞车时会改掉真组的定义）"
    )


# ────────────────────────── 索引读写路径 ──────────────────────────


def test_check读索引的三种退出码(mem: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    good = mem.OUT_DIR / "good.json"
    _write_index(good, [("n4", "n4")])
    assert mem.cmd_check(_args(mem, ["check", "--index", str(good)])) == 0

    over = mem.OUT_DIR / "over.json"
    _write_index(over, [("n4", "n4")])
    payload = json.loads(over.read_text(encoding="utf-8"))
    payload["groups"][0]["peak_total_mb"] = 99_999.0
    over.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8", newline="\n")
    assert mem.cmd_check(_args(mem, ["check", "--index", str(over)])) == 1

    assert mem.cmd_check(_args(mem, ["check", "--index", str(mem.OUT_DIR / "缺.json")])) == 2
    capsys.readouterr()


def test_check的参考索引要求用例数不减(mem: ModuleType) -> None:
    ref = mem.OUT_DIR / "ref.json"
    _write_index(ref, [("n4", "n4")])
    payload = json.loads(ref.read_text(encoding="utf-8"))
    payload["groups"][0]["counts"]["passed"] = 999
    ref.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8", newline="\n")
    cur = mem.OUT_DIR / "cur.json"
    _write_index(cur, [("n4", "n4")])
    assert mem.cmd_check(_args(mem, ["check", "--index", str(cur), "--reference", str(ref)])) == 1


# ────────────────────────── B109：GBK 控制台下不许崩 ──────────────────────────


class _EncodedStream:
    """只有 `encoding` 属性的假 stdout（`_mark` 只读这一个属性）。"""

    def __init__(self, encoding: str) -> None:
        self.encoding = encoding


def test_mark按控制台编码退回ASCII(monkeypatch: pytest.MonkeyPatch) -> None:
    mem = _load()
    monkeypatch.setattr(sys, "stdout", _EncodedStream("cp936"))
    assert mem._mark("✅", "[OK]") == "[OK]"
    assert mem._mark("❌", "[NG]") == "[NG]"
    assert mem._mark("⚠️", "[!]") == "[!]"
    assert mem._mark("↳", "->") == "->"
    monkeypatch.setattr(sys, "stdout", _EncodedStream("utf-8"))
    assert mem._mark("✅", "[OK]") == "✅", "UTF-8 控制台上那些标记是可读的，不许一律降级"


def _run_check_in_console(tmp_path: Path, *, encoding: str) -> subprocess.CompletedProcess[bytes]:
    """在**子进程**里跑一次会打印汇总的调用，并强制 stdout 用 `encoding`（B109 的复现口）。"""
    index = tmp_path / f"index-{encoding}.json"
    _write_index(index, [("n4", "n4")])
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = encoding
    return subprocess.run(
        [sys.executable, str(_SCRIPT), "check", "--index", str(index)],
        capture_output=True,
        env=env,
        check=False,
    )


def test_GBK编码的stdout下打印汇总不崩(tmp_path: Path) -> None:
    """B109 的主判据：`PYTHONIOENCODING=cp936`（= GBK 控制台的口径）下 exit 0。

    为什么用 `PYTHONIOENCODING=cp936` 而不是 `chcp`：它把"控制台编码"这件事**钉死在用例里**，
    在任何机器上都是同一条（`chcp` 那一路另有一条 Windows 专用用例）。修之前这里必然是
    `UnicodeEncodeError` + exit 1（`mem_baseline.py` 打印 ✅/❌ 的那两行），修之后 = 0。
    """
    proc = _run_check_in_console(tmp_path, encoding="cp936")
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-500:]
    assert b"[OK]" in proc.stdout, "GBK 控制台上应当退成 ASCII 标记（可读，而不是 '?'）"


def test_GBK下判红仍然是判红(tmp_path: Path) -> None:
    """修法不许把判据吞掉：不达标的索引在 GBK 下仍要 exit 1 + `[NG]`。"""
    index = tmp_path / "bad.json"
    _write_index(index, [("n4", "n4")])
    payload = json.loads(index.read_text(encoding="utf-8"))
    payload["groups"][0]["per_worker_peak_mb"] = 99_999.0
    index.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8", newline="\n")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp936"
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "check", "--index", str(index)],
        capture_output=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 1
    assert b"[NG]" in proc.stdout


@pytest.mark.skipif(not _IS_WIN, reason="chcp 是 Windows 控制台的东西（Linux/macOS 不适用）")
def test_真实GBK控制台chcp936下不崩(tmp_path: Path) -> None:
    """backlog 附⑤ 的复算入口：`cmd /c chcp 936` 之后跑同一条命令，断言 exit 0。

    控制台代码页是**进程外**的共享状态 ⇒ 用前先读、用完立刻还原（别把 pytest 自己的输出弄花）。
    """
    index = tmp_path / "console.json"
    _write_index(index, [("n4", "n4")])
    before = subprocess.run(["cmd", "/c", "chcp"], capture_output=True, check=False).stdout.decode(
        "ascii", "replace"
    )
    cp = "".join(ch for ch in before if ch.isdigit()) or "936"
    python = str(config.REPO / ".venv" / "Scripts" / "python.exe")
    script = str(_SCRIPT)
    try:
        proc = subprocess.run(
            f'chcp 936 >nul & "{python}" "{script}" check --index "{index}"',
            shell=True,
            capture_output=True,
            check=False,
        )
    finally:
        subprocess.run(["cmd", "/c", "chcp", cp], capture_output=True, check=False)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-500:]
