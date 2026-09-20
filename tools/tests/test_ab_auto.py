"""``pdx.ab_auto`` 的用例：编排器的**状态机全路径**，用假数据跑，不开游戏。

为什么这个文件必须存在（而不是"等真跑一次看看"）：编排器替人做的每一步都发生在
**游戏进程之外**，而它的失效方式很安静 —— 轮询条件写错就一直等、归档标签写错就把
两次实验倒进一个目录、接口没接上却"跑完了"。所以在接真游戏之前，先把每条路径用
假端口走一遍：

```text
preflight（有进程 → 中断）→ start（未接 → 中断）→ poll（到点 / 进程没了 / 轮询用尽）
→ stop → archive → analyze → record（表头 + 追加）→ 队列（一臂不达标即停）
```

假端口只有四个动作：查进程 / 启动 / 杀进程 / 归档 —— 这就是本模块与 `game_auto`
之间的**全部接口**，用例把这个接口的形状也一并钉住。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from pdx import ab, ab_auto, ab_probe
from pdx.cli import app

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = pytest.mark.unit

runner = CliRunner()

_HEAD = "[12:00:{sec:02d}][jomini_effect_impl.cpp:454]: "
_PATH = "common/on_actions/zz_probe_ab_on_actions.txt:30: "
_TAG = "俄罗斯"


def _line(sec: int, kind: str, value: str) -> str:
    return f"{_HEAD.format(sec=sec)}{_PATH}ZZPROBE AB;{kind};{value};{_TAG}"


def _month(sec: int, *, role_input: bool, je: bool) -> str:
    rows = [
        ("SHOCK", "yes"),
        ("INPUT", "yes" if role_input else "no"),
        ("JE", "active" if je else "inactive"),
        ("LAW", "law_serfdom"),
        ("POLI", "conservative_agenda"),
        ("ADMI", "agricultural_expansion"),
        ("DIPL", "colonial_expansion"),
    ]
    return "\n".join(_line(sec, kind, value) for kind, value in rows)


def _segments(a: int = 12, b: int = 24, b2: int = 0) -> str:
    """一局的日志：A 段 + B 段（+ 可选 B2 段）。"""
    text = [_line(0, "RUN", "A")]
    text += [_month(index + 1, role_input=False, je=False) for index in range(a)]
    text.append(_line(20, "RUN", "B"))
    text += [_month(21 + index, role_input=False, je=False) for index in range(b)]
    if b2:
        text.append(_line(60, "RUN", "B2"))
        text += [_month(61 + index, role_input=True, je=True) for index in range(b2)]
    return "\n".join(text)


class _Logs:
    """假日志目录：每次 `analyze` 之前把"游戏已经写出来的月份"增长一批。"""

    def __init__(self, script: list[str]) -> None:
        self.script = script
        self.round = 0
        self.calls = 0

    def take(self) -> str:
        self.calls += 1
        index = min(self.round, len(self.script) - 1)
        self.round += 1
        return self.script[index]


def _ports(
    tmp_path: Path,
    *,
    running: bool = False,
    logs: _Logs | None = None,
    start: object = None,
    stop: object = None,
    archive: object = None,
) -> tuple[ab_auto.Ports, dict[str, list[str]]]:
    """一套假端口 + 调用记录。"""
    events: dict[str, list[str]] = {"start": [], "stop": [], "sleep": [], "archive": []}
    resolved = logs or _Logs([_segments(a=12, b=24, b2=12)])

    def do_start() -> None:
        events["start"].append("start")

    def do_stop() -> None:
        events["stop"].append("stop")

    def do_archive(tag: str) -> Path:
        events["archive"].append(tag)
        return tmp_path / "archive" / tag

    def do_analyze(_path: Path) -> ab.Result:
        return ab.analyze_text(resolved.take())

    ports = ab_auto.Ports(
        running=lambda: running,
        start=start or do_start,  # type: ignore[arg-type]
        stop=stop or do_stop,  # type: ignore[arg-type]
        analyze=do_analyze,
        archive=archive or do_archive,  # type: ignore[arg-type]
        log_dir=tmp_path / "logs",
        sleep=lambda _seconds: events["sleep"].append("sleep"),
    )
    return ports, events


def _arm(**over: object) -> ab_auto.Arm:
    values: dict[str, object] = {"name": "ladder-1", "months": 48, "expect": "B2"}
    values.update(over)
    return ab_auto.Arm(**values)  # type: ignore[arg-type]


# ── 臂与队列的形状 ───────────────────────────────────────────


def test_臂的构造会挡住明显写错的参数() -> None:
    with pytest.raises(ab_auto.OrchestratorError, match="必须是正数"):
        _arm(months=0)
    with pytest.raises(ab_auto.OrchestratorError, match="不是阶梯上的臂"):
        _arm(expect="B3")


def test_当前臂取阶梯上已出现的最后一臂() -> None:
    """轮转会吃掉开头的 RUN 行，所以"跑到哪一臂"按**阶梯顺序**取，不按日志顺序。"""
    assert ab_auto.current_arm(ab.analyze_text(_segments(b2=3))) == "B2"
    assert ab_auto.current_arm(ab.analyze_text(_segments(b2=0))) == "B"
    assert ab_auto.current_arm(ab.analyze_text("")) == ""
    # 只有 B2 段（开头被轮转切掉）时不能退化成"A"
    only_b2 = "\n".join([_line(0, "RUN", "B2"), _month(1, role_input=True, je=True)])
    assert ab_auto.current_arm(ab.analyze_text(only_b2)) == "B2"


# ── preflight ────────────────────────────────────────────────


def test_前置断言_已经没有游戏进程时通过() -> None:
    ports, _events = _ports(Path())
    step = ab_auto.preflight(ports)
    assert step.state == "preflight"
    assert "0 个游戏进程" in step.detail


def test_前置断言_有游戏进程时中断(tmp_path: Path) -> None:
    ports, events = _ports(tmp_path, running=True)
    with pytest.raises(ab_auto.OrchestratorError, match="已经有一个游戏进程"):
        ab_auto.preflight(ports)
    assert events["start"] == [], "前置断言不过时**不许**启动"


def test_有游戏进程时整臂不达标且不写报告(tmp_path: Path) -> None:
    ports, events = _ports(tmp_path, running=True)
    run = ab_auto.run_arm(_arm(), ports)
    assert not run.ok
    assert run.states == ("preflight",)
    assert "已经有一个游戏进程" in run.reason
    assert run.report == ""
    assert events["start"] == []


# ── start / stop 的接线 ──────────────────────────────────────


def test_启动接口没接上时当场报错(tmp_path: Path) -> None:
    """P13：接口留空 = 调用时出声，不是静默跳过。"""
    ports = ab_auto.default_ports(log_dir=tmp_path, analyze=lambda _p: ab.analyze_text(""))
    with pytest.raises(ab_auto.OrchestratorError, match="启动游戏 还没接上"):
        ports.start()
    with pytest.raises(ab_auto.OrchestratorError, match="杀进程 还没接上"):
        ports.stop()


def test_默认端口接上进程查询与归档(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, Path | None]] = []

    def fake_archive(tag: str, *, log_dir: Path | None = None) -> tuple[Path, int, int]:
        seen.append((tag, log_dir))
        return tmp_path / tag, 1, 0

    monkeypatch.setattr(ab_auto.h1_probe, "archive_logs", fake_archive)
    ports = ab_auto.default_ports(log_dir=tmp_path)
    assert ports.running is ab_auto.h1_probe.game_running
    assert ports.analyze is ab.analyze
    assert ports.archive("t") == tmp_path / "t"
    assert seen == [("t", tmp_path)]


def test_启动失败时把哪一步断的写进原因(tmp_path: Path) -> None:
    def boom() -> None:
        raise ab_auto.OrchestratorError("启动游戏 还没接上")

    ports, events = _ports(tmp_path, start=boom)
    run = ab_auto.run_arm(_arm(), ports)
    assert not run.ok
    # 断在哪一步要记下来：preflight 走过，start 是断的那一步
    assert run.states == ("preflight", "start")
    assert "中断" in run.steps[-1].detail
    assert "启动游戏 还没接上" in run.reason
    assert events["stop"] == [], "启动都没成功，不该去杀进程"


# ── poll：三种收工方式 ───────────────────────────────────────


def test_轮询到目标月数就收工(tmp_path: Path) -> None:
    ports, events = _ports(
        tmp_path, running=True, logs=_Logs([_segments(a=12, b=24), _segments(a=12, b=24, b2=12)])
    )
    steps = ab_auto.poll_until_done(_arm(months=40), ports, interval=1.0, max_polls=5)
    assert [step.state for step in steps][-1] == "done"
    assert events["sleep"], "第一次没到目标，应该睡一次再看"


def test_轮询发现游戏提前退出也往下走(tmp_path: Path) -> None:
    """崩了 / 被人关了：照样归档 + 分析，让报告去说数据够不够（不是静默成功）。"""
    ports, _events = _ports(tmp_path, running=False, logs=_Logs([_segments(a=12, b=3)]))
    steps = ab_auto.poll_until_done(_arm(months=48), ports, interval=1.0, max_polls=5)
    assert [step.state for step in steps][-1] == "gone"
    assert "游戏已退出" in steps[-1].detail


def test_轮询次数用尽不无限等(tmp_path: Path) -> None:
    ports, _events = _ports(tmp_path, running=True, logs=_Logs([_segments(a=12, b=3)]))
    steps = ab_auto.poll_until_done(_arm(months=48), ports, interval=1.0, max_polls=2)
    assert [step.state for step in steps][-1] == "limit"
    assert "轮询 2 次" in steps[-1].detail


def test_轮询按探针自己的月度块算而不是墙钟(tmp_path: Path) -> None:
    """日志不增长时，睡多少次都不算进度（游戏暂停着的时候墙钟照走）。"""
    ports, events = _ports(tmp_path, running=True, logs=_Logs([_segments(a=6, b=0)]))
    steps = ab_auto.poll_until_done(_arm(months=48), ports, interval=1.0, max_polls=3)
    assert steps[-1].state == "limit"
    assert len(events["sleep"]) == 2  # 3 轮 → 睡 2 次（最后一轮不再空睡一次）


# ── run_arm：整条流水线 ──────────────────────────────────────


def test_整臂跑通_状态顺序与归档标签(tmp_path: Path) -> None:
    ports, events = _ports(tmp_path, logs=_Logs([_segments(a=12, b=24, b2=12)]))
    run = ab_auto.run_arm(_arm(months=48), ports)
    assert run.ok, run.reason
    assert run.months == 48
    assert run.reached == "B2"
    assert run.archive == tmp_path / "archive" / "ladder-1"
    assert run.verdict == "no_diff"
    assert run.states == ("preflight", "start", "poll", "done", "stop", "archive", "analyze")
    assert events["archive"] == ["ladder-1"]
    assert events["stop"] == ["stop"]
    assert "A 对照组" in run.report


def test_没跑到目标臂时判不达标并给出原因(tmp_path: Path) -> None:
    """观测月数够了但**没换到 B2**（阶梯没走起来）—— 这一臂不算达标。"""
    ports, _events = _ports(tmp_path, logs=_Logs([_segments(a=12, b=40)]))
    run = ab_auto.run_arm(_arm(months=48), ports)
    assert run.months == 52
    assert run.reached == "B"
    assert not run.ok
    assert "预期 B2" in run.reason


def test_观测不够月数时不达标(tmp_path: Path) -> None:
    ports, _events = _ports(tmp_path, running=False, logs=_Logs([_segments(a=12, b=3)]))
    run = ab_auto.run_arm(_arm(months=48), ports)
    assert not run.ok
    assert "观测 15 个月（目标 48）" in run.reason


def _live_ports(
    tmp_path: Path, analyze: Callable[[Path], ab.Result], *, log_dir: Path | None = None
) -> tuple[ab_auto.Ports, list[float]]:
    """假端口：**启动前没有进程**（preflight 得先过），启动后一直在跑；睡只记账不真睡。

    这正是"游戏在跑但观测不推进"要的形状 —— 若让 ``running`` 一开始就为真，
    挡住的会是 preflight，测的就不是轮询了（第一版用例踩过这个坑）。
    """
    started = False
    sleeps: list[float] = []
    target = log_dir or tmp_path / "logs"

    def do_start() -> None:
        nonlocal started
        started = True

    ports = ab_auto.Ports(
        running=lambda: started,
        start=do_start,
        stop=lambda: None,
        analyze=analyze,
        archive=lambda tag: target / tag,
        log_dir=target,
        sleep=sleeps.append,
    )
    return ports, sleeps


def test_观测永不推进时整臂判红而不是静默结束(tmp_path: Path) -> None:
    """月度行一直不动（游戏卡住 / 被暂停）：轮询到上限就收工，但这一臂必须**判红**。

    这是本模块最危险的失效方式 —— "睡够了就当跑完了"会产出一次没有数据的实验，
    而记录里那一节看起来是成功的。
    """
    stuck = ab.analyze_text(_segments(a=6, b=0))
    ports, sleeps = _live_ports(tmp_path, lambda _path: stuck)
    run = ab_auto.run_arm(_arm(name="stuck", months=48), ports, interval=1.0, max_polls=3)
    assert not run.ok
    assert "limit" in run.states, "轮询用尽要留下 limit 这一步（不是当成收工）"
    assert "观测 6 个月（目标 48）" in run.reason
    assert len(sleeps) == 2, "3 轮只睡 2 次：最后一轮直接判 limit"
    text = ab_auto.record_text(run)
    assert "## stuck　❌" in text
    assert "**为什么没达标**" in text


# ── 失败路径：归档 / 日志目录 ─────────────────────────────────


def test_归档失败时中断并把原因写进记录(tmp_path: Path) -> None:
    """归档是流水线最后一道外部动作：它失败 = 这一臂当场中断，且断在哪一步要写清楚。"""

    def boom(tag: str) -> Path:
        raise ab_auto.OrchestratorError(f"归档失败：{tag} 的日志目录不存在")

    ports, events = _ports(tmp_path, logs=_Logs([_segments(a=12, b=24, b2=12)]), archive=boom)
    run = ab_auto.run_arm(_arm(name="no-logs"), ports)
    assert not run.ok
    assert run.states == (
        "preflight",
        "start",
        "poll",
        "done",
        "stop",
        "archive",
    ), "断在 archive 这一步（前面的步骤照旧留下）"
    assert "中断" in run.steps[-1].detail
    assert "归档失败" in run.reason
    assert run.archive is None
    assert run.report == ""
    assert events["stop"] == ["stop"], "归档失败发生在杀进程之后"
    text = ab_auto.record_text(run)
    assert "## no-logs　❌" in text
    assert "归档失败" in text, "原因必须进记录，否则下次还要人来猜"
    assert "* **归档**：—" in text


def test_归档后分析失败也要写进记录而不是抛出去(tmp_path: Path) -> None:
    """归档之后的分析**也在 run_arm 的流水线里**：它失败时的口径必须与归档失败一致 ——
    写进记录、``ok=False``、断在 ``analyze``，而不是把异常丢给调用方（那一臂会连记录都没有）。"""
    good = ab.analyze_text(_segments(a=12, b=24, b2=12))
    rounds = {"n": 0}

    def analyze(_path: Path) -> ab.Result:
        rounds["n"] += 1
        if rounds["n"] == 1:  # 轮询那一次照常（48 个月，一轮就收工）
            return good
        raise ab_auto.OrchestratorError("分析失败：归档目录里的日志读不动")

    ports, _sleeps = _live_ports(tmp_path, analyze)
    run = ab_auto.run_arm(_arm(name="analyze-boom"), ports)
    assert not run.ok
    assert run.states == ("preflight", "start", "poll", "done", "stop", "archive", "analyze")
    assert "中断" in run.steps[-1].detail
    assert "分析失败" in run.reason
    assert run.archive == tmp_path / "logs" / "analyze-boom"
    assert run.report == ""
    assert "分析失败" in ab_auto.record_text(run)


def test_中断时保留轮询已观测的月数(tmp_path: Path) -> None:
    """归档失败时这一臂已经数到 48 个月 —— 记录里必须留下读数，不许因为中断就写 0。"""

    def boom(tag: str) -> Path:
        raise ab_auto.OrchestratorError(f"归档失败：{tag} 的磁盘满了")

    ports, _events = _ports(tmp_path, logs=_Logs([_segments(a=12, b=24, b2=12)]), archive=boom)
    run = ab_auto.run_arm(_arm(name="kept"), ports)
    assert not run.ok
    assert run.months == 48, "轮询已经数到 48 个月，中断时不许丢"
    assert run.reached == "B2", "跑到哪一臂同样是读数，不许丢"
    text = ab_auto.record_text(run)
    assert "**实测**：48 个月" in text
    assert "归档失败" in text


def test_日志目录缺失时判红而不是静默成功(tmp_path: Path) -> None:
    """日志目录不在时 :func:`ab.analyze` 给**空结果**（实测不抛错）。

    所以判据必须落在"月数不够"上：一臂读不到任何月度块时要是判绿，记录里就会出现
    一次没有数据的"成功"。这里用真的 ``ab.analyze``，不用假实现。
    """
    ports, _sleeps = _live_ports(
        tmp_path, ab.analyze, log_dir=tmp_path / "gone" / "logs"
    )  # 归档目标目录同样不存在
    run = ab_auto.run_arm(_arm(name="no-dir", months=48), ports, interval=1.0, max_polls=1)
    assert not run.ok
    assert run.months == 0
    assert run.reached == ""
    assert "limit" in run.states
    assert "观测 0 个月（目标 48）" in run.reason
    text = ab_auto.record_text(run)
    assert "## no-dir　❌" in text
    assert "未武装" in text


# ── 记录文件 ─────────────────────────────────────────────────


def test_记录文件先写表头再追加(tmp_path: Path) -> None:
    target = tmp_path / "rec.md"
    ports, _events = _ports(tmp_path, logs=_Logs([_segments(a=12, b=24, b2=12)]))
    first = ab_auto.run_arm(_arm(name="ladder"), ports)
    ab_auto.append_record(first, target)
    text = target.read_text(encoding="utf-8")
    assert text.startswith("# exec · 阶段 3 实验记录（自动追加）")
    assert "## ladder　✅" in text
    assert "A 对照组" in text  # 报告全文进了折叠块

    second = ab_auto.run_arm(_arm(name="ladder-repeat"), ports)
    ab_auto.append_record(second, target)
    text = target.read_text(encoding="utf-8")
    assert text.count("# exec · 阶段 3 实验记录") == 1, "表头只能写一次"
    assert "## ladder-repeat　✅" in text


def test_追加记录不改动既有内容(tmp_path: Path) -> None:
    """已有内容必须**逐字保留**：实验记录是原始读数，追加不许重写（也不许吃掉换行）。"""
    target = tmp_path / "rec.md"
    old = "# 别人写的表头\n\n> 已有内容不该被动\n"
    target.write_text(old, encoding="utf-8")
    ports, _events = _ports(tmp_path, logs=_Logs([_segments(a=12, b=24, b2=12)]))
    run = ab_auto.run_arm(_arm(name="append-only"), ports)
    ab_auto.append_record(run, target)
    text = target.read_text(encoding="utf-8")
    assert text.startswith(old), "既有内容必须原样在前"
    assert text.removeprefix(old) == ab_auto.record_text(run), "新增部分只能接在末尾"
    assert text.count("# 别人写的表头") == 1, "只追加、不重复既有内容"


def test_记录里必须留下失败原因(tmp_path: Path) -> None:
    ports, _events = _ports(tmp_path, running=True)
    run = ab_auto.run_arm(_arm(name="blocked"), ports)
    text = ab_auto.record_text(run)
    assert "## blocked　❌" in text
    assert "**为什么没达标**" in text
    assert "已经有一个游戏进程" in text
    assert "状态机" in text
    assert "（没有报告）" in text


# ── run_queue：一臂不达标即停 ────────────────────────────────


def test_队列跑完两臂(tmp_path: Path) -> None:
    target = tmp_path / "rec.md"
    ports, _events = _ports(tmp_path, logs=_Logs([_segments(a=12, b=24, b2=12)]))
    report = ab_auto.run_queue(
        [_arm(name="run-1"), _arm(name="run-2")], ports_for=lambda _arm: ports, path=target
    )
    assert report.ok
    assert not report.stopped_early
    assert [run.arm.name for run in report.runs] == ["run-1", "run-2"]
    assert target.read_text(encoding="utf-8").count("## run-") == 2


def test_队列在第一臂不达标时就停(tmp_path: Path) -> None:
    """数据不干净时继续跑后面的臂只是浪费一局的时间。"""
    target = tmp_path / "rec.md"
    ports, _events = _ports(tmp_path, running=True)
    report = ab_auto.run_queue(
        [_arm(name="run-1"), _arm(name="run-2")], ports_for=lambda _arm: ports, path=target
    )
    assert not report.ok
    assert report.stopped_early
    assert [run.arm.name for run in report.runs] == ["run-1"]
    assert "run-2" not in target.read_text(encoding="utf-8")


def test_队列摘要表(tmp_path: Path) -> None:
    ports, _events = _ports(tmp_path, logs=_Logs([_segments(a=12, b=24, b2=12)]))
    report = ab_auto.run_queue(
        [_arm(name="run-1")], ports_for=lambda _arm: ports, path=tmp_path / "rec.md"
    )
    text = ab_auto.format_queue(report)
    assert "| 臂 | 目标月数 |" in text
    assert "全部达标 ✅" in text
    assert ab_auto.format_queue(ab_auto.QueueReport()) == "一臂都没跑。"


def test_每臂可以有各自的端口(tmp_path: Path) -> None:
    """`ports_for` 按臂给端口：归档标签/日志目录都可能不一样。"""
    seen: list[str] = []
    base, _events = _ports(tmp_path, logs=_Logs([_segments(a=12, b=24, b2=12)]))

    def ports_for(arm: ab_auto.Arm) -> ab_auto.Ports:
        seen.append(arm.name)
        return base

    ab_auto.run_queue(
        [_arm(name="a"), _arm(name="b")], ports_for=ports_for, path=tmp_path / "rec.md"
    )
    assert seen == ["a", "b"]


# ── CLI（`v3 ab-auto`）───────────────────────────────────────


def test_CLI的plan什么都不做(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "rec.md"
    result = runner.invoke(app, ["ab-auto", "--plan", "--record", str(target), "--repeat", "2"])
    assert result.exit_code == 0, result.output
    assert "臂队列" in result.output
    assert not target.exists(), "--plan 不该写记录"


def test_CLI在启动接口没接上时退出码1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """没接 game_auto 就真跑 = 当场红（退出码 1），并把失败写进记录。"""
    target = tmp_path / "rec.md"
    ports = ab_auto.default_ports(log_dir=tmp_path, analyze=lambda _p: ab.analyze_text(""))
    monkeypatch.setattr(ab_auto, "default_ports", lambda **_kw: ports)
    result = runner.invoke(
        app, ["ab-auto", "--record", str(target), "--months", "48", "--arm", "unwired"]
    )
    assert result.exit_code == 1, result.output
    assert "## unwired　❌" in target.read_text(encoding="utf-8")


def test_实验记录路径在exec目录下() -> None:
    assert ab_auto.RECORD_PATH.name == "阶段3-实验记录.md"
    assert ab_auto.RECORD_PATH.parent.name == "exec"
    assert ab_probe.PROBE_DIR.is_dir(), "探针目录应当已经生成（生成物由 v3 ab-probe 产出）"
