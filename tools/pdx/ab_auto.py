"""阶段 3 自动实验的**编排器骨架**（状态机 + 文件操作，不碰游戏本体）。

它要解决的问题
--------------
阶段 3 的 A/B 实验原来靠人：开一局、点决议、等几个月、退出、归档、跑 `v3 ab`、
把结论抄进文档 —— 每一步都要人守着。这个模块把"守着"变成一条可测的流水线：

```text
断言 0 个游戏进程 → 启动（交给 game_auto，接口留空）→ 轮询探针月度行判断进度
→ 到目标月数杀进程 → 归档 logs → 调 pdx.ab.analyze 出报告
→ 追加进 exec/阶段3-实验记录.md → 装下一臂
```

**为什么要依赖注入**（而不是直接 `import game_auto`）
----------------------------------------------------
1. **可测**：状态机的每一条路径（进程还在跑 / 提前退出 / 观测不流动 / 到点收工 /
   归档失败）都必须有用例覆盖，而跑用例的机器上不能也不需要开游戏；
2. **解耦**：`game_auto` 由并行轨（游戏自动化）提供，本模块只约定**四个动作**的签名
   （查进程 / 启动 / 杀进程 / 归档），谁实现都行；
3. **失败出声**（P13）：接口没接上时**当场报错**，不是静默跳过 ——
   静默跳过会让"自动化跑完了"这句话变成假的。

状态机（:data:`STATES`）
-----------------------
``preflight`` 断言 0 个游戏进程 → ``start`` → ``poll``（每次读一次日志目录）→
``stop`` → ``archive`` → ``analyze`` → ``record`` → ``next`` / ``done``。
任何一步失败，这一臂就地结束并把**失败原因**写进记录（不吞异常、不假装成功）。

判进度的口径：**探针自己报的月度块**（`pdx.ab.analyze` 去重后的观测），
不是墙钟时间 —— 游戏暂停着的时候墙钟照走，而月度块不走。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pdx import ab, ab_probe, config, h1_probe

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

#: 实验记录（由本模块追加；人只读不写）。
RECORD_PATH = config.REPO / "docs" / "design" / "exec" / "阶段3-实验记录.md"

#: 状态机走过的一步（顺序即执行顺序）。
#: ``poll`` 内部还会记四个**子状态**（`wait` / `done` / `gone` / `limit`）——
#: 它们回答"这一臂是到点收的工，还是游戏提前没了"，比一个笼统的 poll 有用得多。
STATES = (
    "preflight",
    "start",
    "poll",
    "stop",
    "archive",
    "analyze",
    "record",
)

#: 主流水线的状态 = :data:`STATES` 去掉 ``record``（那一步由调用方在 :func:`run_arm`
#: 之后做，见 :func:`run_queue`）。中断时用"第一个还没走过的状态"定位断在哪一步 ——
#: 比一个笼统的"失败了"有用得多（P13）。``analyze`` 在里面：归档之后的复算**属于**
#: 这一臂的流水线，它失败时也要能说清断在哪。
_PIPELINE = STATES[:-1]


def _failed_state(steps: Sequence[Step]) -> str:
    """中断发生在哪一步：已走过的状态之后的**第一个**主流水线状态。"""
    done = {step.state for step in steps}
    return next((state for state in _PIPELINE if state not in done), "poll")


#: 轮询默认间隔（秒）与上限（防呆：真跑起来一局 5–6 年 ≈ 十分钟量级）。
POLL_INTERVAL = 30.0
MAX_POLLS = 240


class OrchestratorError(RuntimeError):
    """编排中断（进程没清干净、接口没接上、归档失败…）。

    刻意不吞：这一层替人执行的每一步都必须**出声**，否则"自动跑完了"没有意义。
    """


@dataclass(frozen=True, slots=True)
class Arm:
    """一次要跑的实验臂（一局 = 一条阶梯，所以这里的一臂通常是"整条阶梯跑 N 月"）。"""

    name: str
    months: int
    #: 预期跑到哪一臂（`A` / `B` / `B2`）—— 到点了但没跑到，说明阶梯没走起来。
    expect: str = "B2"
    note: str = ""

    def __post_init__(self) -> None:
        if self.months <= 0:
            raise OrchestratorError(f"{self.name}：目标月数必须是正数（现在 {self.months}）")
        if self.expect not in ab_probe.ROLES:
            raise OrchestratorError(
                f"{self.name}：expect={self.expect!r} 不是阶梯上的臂（{ab_probe.ROLES}）"
            )


@dataclass(frozen=True, slots=True)
class Ports:
    """外部世界：四个动作 + 两个目录（全部可替换，见模块文档）。"""

    #: 现在有没有游戏进程（前置断言与轮询都用它）。
    running: Callable[[], bool]
    #: 启动游戏（`game_auto` 的实现；没接上时应当抛 :class:`OrchestratorError`）。
    start: Callable[[], None]
    #: 杀进程。
    stop: Callable[[], None]
    #: 读日志目录 → `ab.Result`。
    analyze: Callable[[Path], ab.Result]
    #: 归档当前日志，返回归档目录（默认 `h1_probe.archive_logs`）。
    archive: Callable[[str], Path]
    #: 日志目录。
    log_dir: Path
    #: 睡（测试里替换成不睡的假实现）。
    sleep: Callable[[float], None] = time.sleep


@dataclass(frozen=True, slots=True)
class Step:
    """状态机走过的一步（进记录、也进用例断言）。"""

    state: str
    detail: str


@dataclass(frozen=True, slots=True)
class ArmRun:
    """一臂的结果。``ok`` 为假时 ``reason`` 一定有话说（P13）。"""

    arm: Arm
    steps: tuple[Step, ...]
    months: int
    reached: str
    archive: Path | None
    report: str
    verdict: str
    ok: bool
    reason: str = ""

    @property
    def states(self) -> tuple[str, ...]:
        return tuple(step.state for step in self.steps)


def default_ports(
    *,
    log_dir: Path | None = None,
    analyze: Callable[[Path], ab.Result] | None = None,
    running: Callable[[], bool] | None = None,
    start: Callable[[], None] | None = None,
    stop: Callable[[], None] | None = None,
    archive: Callable[[str], Path] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Ports:
    """默认端口：能接上的接上，接不上的**留空函数**（调用时抛错，不是静默跳过）。

    `game_auto` 由并行轨提供，所以这里**懒加载**：模块不在也能 import 本模块、
    也能跑用例；真跑的时候没接上就会得到一句可执行的报错。
    """

    def _unwired(action: str) -> Callable[[], None]:
        def call() -> None:
            raise OrchestratorError(
                f"{action} 还没接上：把 game_auto 的实现（或你自己的函数）传给 Ports —— "
                "本模块刻意不 import 它，见 tools/pdx/ab_auto.py 的模块文档"
            )

        return call

    return Ports(
        running=running or h1_probe.game_running,
        start=start or _unwired("启动游戏"),
        stop=stop or _unwired("杀进程"),
        analyze=analyze or ab.analyze,
        archive=archive or (lambda tag: h1_probe.archive_logs(tag, log_dir=log_dir)[0]),
        log_dir=log_dir or config.USERDIR / "logs",
        sleep=sleep,
    )


def current_arm(result: ab.Result) -> str:
    """这次观测跑到阶梯的哪一臂（取阶梯上**已出现**的最后一臂）。

    为什么用"阶梯上最后一臂"而不是"日志里最后一个 RUN 标记"：轮转会把开头的
    `RUN;A` 吃掉（实测：归档里常见"无标记段"），而阶梯的顺序是已知的 ——
    按阶梯取最大值比按日志顺序取更稳。
    """
    return next(
        (role for role in reversed(ab_probe.ROLES) if result.months_of(role) > 0),
        "",
    )


def preflight(ports: Ports) -> Step:
    """跑之前断言"0 个游戏进程"：否则这一局的数据会与上一次的混在同一个日志目录里。"""
    if ports.running():
        raise OrchestratorError(
            "已经有一个游戏进程在跑 —— 先关掉它：同一个日志目录里混两局，"
            "归档与统计都会把两次启动的样本池倒在一起"
        )
    return Step("preflight", "0 个游戏进程 ✅")


def poll_until_done(
    arm: Arm,
    ports: Ports,
    *,
    interval: float,
    max_polls: int,
    observed: Callable[[int, str], None] | None = None,
) -> tuple[Step, ...]:
    """轮询到目标月数（或游戏提前退出）。

    三种收工方式，每一种都记一步（事后能看出**为什么**收的工）：

    * ``done``：观测月数到了目标；
    * ``gone``：游戏进程没了（崩了 / 被人关了）—— 照样往下走，让分析器去说数据够不够；
    * ``limit``：轮询次数用尽（防呆，不静默无限等）。

    每读到一次就把读数回调给 ``observed(月数, 臂)``：:func:`run_arm` 用它把"已经数到多少"
    留在**中断记录**里 —— 否则失败的一臂只剩原因、没有读数，记录就缺了一半。
    """
    steps: list[Step] = []
    rounds = 0
    while rounds < max_polls:
        rounds += 1
        result = ports.analyze(ports.log_dir)
        reached = current_arm(result)
        months = result.months
        if observed is not None:
            observed(months, reached)
        steps.append(Step("poll", f"第 {rounds} 轮：观测 {months} 个月（{reached or '未武装'}）"))
        if months >= arm.months:
            steps.append(Step("done", f"观测 {months} ≥ 目标 {arm.months} → 可以收工"))
            return tuple(steps)
        if not ports.running():
            steps.append(Step("gone", f"第 {rounds} 轮发现游戏已退出（观测 {months} 个月）"))
            return tuple(steps)
        if rounds >= max_polls:
            # 下一轮就是 limit：不再空睡一次（睡醒也只为了写一行"用尽了"）
            break
        steps.append(Step("wait", f"睡 {interval:.0f} 秒再看"))
        ports.sleep(interval)
    steps.append(Step("limit", f"轮询 {max_polls} 次仍未到 {arm.months} 个月 → 收工"))
    return tuple(steps)


def run_arm(
    arm: Arm,
    ports: Ports,
    *,
    interval: float = POLL_INTERVAL,
    max_polls: int = MAX_POLLS,
) -> ArmRun:
    """跑一臂：前置断言 → 启动 → 轮询 → 杀进程 → 归档 → 分析。

    任何一步抛错都**不吞**：包成 ``ok=False`` 的 :class:`ArmRun` 交给上层写进记录 ——
    记录里必须留下"哪一步断的"**和"已经数到多少"**，否则下次还是要人来猜。
    归档之后的分析也在这条流水线上（它失败时口径与归档失败一致，不把异常丢给调用方）。
    """
    steps: list[Step] = []
    archive_dir: Path | None = None
    seen_months = 0
    seen_reached = ""

    def remember(months: int, reached: str) -> None:
        nonlocal seen_months, seen_reached
        seen_months, seen_reached = months, reached

    try:
        steps.append(preflight(ports))
        ports.start()
        steps.append(Step("start", f"已启动（目标 {arm.months} 个月，预期跑到 {arm.expect}）"))
        steps.extend(
            poll_until_done(arm, ports, interval=interval, max_polls=max_polls, observed=remember)
        )
        ports.stop()
        steps.append(Step("stop", "已杀进程"))
        archive_dir = ports.archive(arm.name)
        steps.append(Step("archive", f"日志已归档 → {archive_dir}"))
        result = ports.analyze(archive_dir)
        reached = current_arm(result)
        steps.append(
            Step("analyze", f"归档目录复算：{result.months} 个月（{reached or '未武装'}）")
        )
        report = ab.format_report(result)
    except OrchestratorError as exc:
        steps.append(Step(_failed_state(steps), f"❌ 中断：{exc}"))
        return ArmRun(
            arm=arm,
            steps=tuple(steps),
            months=seen_months,
            reached=seen_reached,
            archive=archive_dir,
            report="",
            verdict="",
            ok=False,
            reason=str(exc),
        )

    ok = result.months >= arm.months and ab_probe.ROLES.index(reached or "A") >= (
        ab_probe.ROLES.index(arm.expect)
    )
    reason = (
        ""
        if ok
        else (
            f"只跑到 {reached or '未武装'}（预期 {arm.expect}）、观测 {result.months} 个月"
            f"（目标 {arm.months}）"
        )
    )
    return ArmRun(
        arm=arm,
        steps=tuple(steps),
        months=result.months,
        reached=reached,
        archive=archive_dir,
        report=report,
        verdict=result.verdict,
        ok=ok,
        reason=reason,
    )


def record_text(run: ArmRun) -> str:
    """把一臂写成 markdown 小节（追加进 :data:`RECORD_PATH`）。"""
    status = "✅" if run.ok else "❌"
    lines = [
        f"## {run.arm.name}　{status}",
        "",
        f"* **目标**：{run.arm.months} 个月、预期跑到 `{run.arm.expect}`"
        + (f"　**备注**：{run.arm.note}" if run.arm.note else ""),
        (
            f"* **实测**：{run.months} 个月、跑到 `{run.reached or '未武装'}`、"
            f"判定 `{run.verdict or '—'}`"
        ),
        f"* **归档**：`{run.archive}`" if run.archive else "* **归档**：—",
        f"* **状态机**：{' → '.join(run.states)}",
    ]
    if run.reason:
        lines.append(f"* **为什么没达标**：{run.reason}")
    lines += [
        "",
        "<details><summary>分析报告</summary>",
        "",
        run.report or "（没有报告）",
        "",
        "</details>",
        "",
    ]
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class QueueReport:
    """整条臂队列的结果。"""

    runs: tuple[ArmRun, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return bool(self.runs) and all(run.ok for run in self.runs)

    @property
    def stopped_early(self) -> bool:
        """是不是有臂没达标就停了（后续臂**不会**再跑：数据不干净时继续只是浪费一局）。"""
        return any(not run.ok for run in self.runs)


def _header() -> str:
    """实验记录的开头（只在文件不存在时写）。"""
    return "\n".join(
        [
            "# exec · 阶段 3 实验记录（自动追加）",
            "",
            "> ⚠️ 本文件由 `v3 ab-auto`（`tools/pdx/ab_auto.py`）**追加**，不要手改。",
            "> 每一节 = 一次 `run_arm`：臂队列 → 断言 0 个游戏进程 → 启动 → 轮询探针月度行",
            "> → 到目标月数杀进程 → 归档 `logs\\` → 分析 → 追加到本文件。",
            "> 结论与诊断链在 `阶段3-结果.md`（人写的），本文件只放**原始读数**。",
            "",
            "## 口径",
            "",
            "* **一臂 = 一局**：一局里探针按月份自动换臂（A 第 1–12 月 → B 第 13 月 → B2 第 37 月），",
            "  所以「一次启动」就能拿到整条阶梯；队列里的第二臂是**重复一局**（G2 要求两次同向）。",
            "* **进度按探针自己报的月度块算**，不按墙钟：游戏暂停时墙钟照走、月度块不走。",
            "* **失败即停**：某臂没达标就不再跑后面的（数据不干净时继续只是浪费一局）。",
            "",
            "---",
            "",
        ]
    )


def append_record(run: ArmRun, path: Path | None = None) -> Path:
    """把一臂追加进实验记录（文件不存在时先写表头）。"""
    target = path or RECORD_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    head = "" if target.is_file() else _header()
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(head + record_text(run))
    return target


def run_queue(
    arms: Sequence[Arm],
    *,
    ports_for: Callable[[Arm], Ports],
    path: Path | None = None,
    interval: float = POLL_INTERVAL,
    max_polls: int = MAX_POLLS,
) -> QueueReport:
    """按队列跑：一臂一局，每臂跑完就归档 + 分析 + 写记录。

    ``ports_for`` 按臂给端口（每臂的归档标签/日志目录都可能不同）；某臂没达标即停。
    """
    runs: list[ArmRun] = []
    for arm in arms:
        run = run_arm(arm, ports_for(arm), interval=interval, max_polls=max_polls)
        append_record(run, path)
        runs.append(run)
        if not run.ok:
            break
    return QueueReport(runs=tuple(runs))


def format_queue(report: QueueReport) -> str:
    """队列摘要（给 CLI 打屏）。"""
    if not report.runs:
        return "一臂都没跑。"
    lines = ["| 臂 | 目标月数 | 实测月数 | 跑到 | 判定 | 结论 |", "|---|---:|---:|---|---|---|"]
    lines += [
        f"| {run.arm.name} | {run.arm.months} | {run.months} | `{run.reached or '未武装'}` | "
        f"`{run.verdict or '—'}` | {'✅' if run.ok else '❌ ' + (run.reason or '未达标')} |"
        for run in report.runs
    ]
    lines += [
        "",
        "**总判定**：" + ("全部达标 ✅" if report.ok else "有臂未达标 ❌（后面的臂没有跑）"),
    ]
    return "\n".join(lines)


__all__ = [
    "MAX_POLLS",
    "POLL_INTERVAL",
    "RECORD_PATH",
    "STATES",
    "Arm",
    "ArmRun",
    "OrchestratorError",
    "Ports",
    "QueueReport",
    "Step",
    "append_record",
    "current_arm",
    "default_ports",
    "format_queue",
    "poll_until_done",
    "preflight",
    "record_text",
    "run_arm",
    "run_queue",
]
