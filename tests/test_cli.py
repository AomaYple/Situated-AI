"""命令行端到端测试。

为什么要单独测 CLI
------------------
``pdx/cli.py`` 有近 400 条语句，是包内最大的单个模块，但它此前**零覆盖**：
所有测试都在直接调用库函数，命令行这一层从未被执行过。而这层恰恰是
用户唯一真正接触的界面 —— 参数名写错、退出码不对、缺产物时抛裸异常，
库测试一个都发现不了。

两个层次
--------
* :class:`typer.testing.CliRunner`  **进程内**调用。快，能覆盖大量分支，
  适合验证参数解析、退出码、输出内容。
* ``subprocess``  **真起进程**跑 ``python -m pdx.cli``。慢，但它验证的是
  另一件事：装出来的入口点在真实环境里能不能跑、编码兜底有没有生效。
  进程内测试永远发现不了这两类问题。

退出码约定（与 ``cli.py`` 实现一致）
------------------------------------
0 = 成功；1 = 检查未通过；2 = 用法错误或前置条件缺失（如产物不存在）；
**3 = 检查跑了，但输入使结论不可得**（今天只有 crosscheck 的"行号不可比"一档：
被核对的文件被 mod 覆盖、与原版不是同一套行号）。

第三档为什么必须存在
--------------------
把"核对不了"写成"对不上"，与 B85 那一族是同一个病：
``pdx/game_auto.py:1848`` 的"不许直接 ``sorted()``，否则轮转副本里的行读不到
⇒『我们在 error.log 里没看到』被当成了『没有』"。同一族的还有 t19（抓图失败
≠ 模板不命中）、t17/t90（找不到 ≠ 没有）。所以 3 既不能读成 0（那会把"没核对"
说成"核对通过"），也不能读成 1（那会把两套行号的差记到解析器头上）。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pdx import cli, config, verify

pytestmark = pytest.mark.cli

runner = CliRunner()

_needs_game = pytest.mark.skipif(not (config.GAME / "common").is_dir(), reason="游戏目录不可用")


def _invoke(*args: str):
    return runner.invoke(cli.app, list(args))


def _flat(text: str) -> str:
    """把 rich 表格按 80 列折行的输出摊平，好断整句。

    ⚠️ 为什么必须有它：本命令的"原因"行（``文件 日志第 N 行 'TOKEN' —— …``）
    在窄终端里会被折成两三行，直接 ``in`` 一个长句会假红 —— 那是**测试**的脆，
    不是实现的错。摊平（ANSI 去掉、连续空白含换行折成一个空格）之后按整句断，
    断的东西没变松：句子里的每个数字仍然逐字来自报告对象。
    """
    plain = re.sub(r"\x1b\[[0-9;]*m", "", text)
    return re.sub(r"\s+", " ", plain)


# ── 基本可用性 ──────────────────────────────────────────────
def test_help_exit0() -> None:
    r = _invoke("--help")
    assert r.exit_code == 0, r.output
    for cmd in (
        "analyze",
        "defines",
        "index",
        "snapshot",
        "verify",
        "crosscheck",
        "check-outputs",
        "show",
    ):
        assert cmd in r.output, f"--help 里没有列出 {cmd}"


@pytest.mark.parametrize(
    "cmd",
    ["analyze", "defines", "index", "snapshot", "verify", "crosscheck", "check-outputs", "show"],
)
def test_每个子命令的help都可用(cmd: str) -> None:
    r = _invoke(cmd, "--help")
    assert r.exit_code == 0, r.output
    assert cmd in r.output or "Usage" in r.output


def test_未知子命令返回用法错误() -> None:
    r = _invoke("no-such-command")
    assert r.exit_code == 2, "用法错误必须是 2，不能是 1"


def test_未知选项返回用法错误() -> None:
    r = _invoke("analyze", "--bogus-option")
    assert r.exit_code == 2, r.output


def test_未给子命令时不算崩溃() -> None:
    """typer 在无子命令时会打印帮助并退出，不能是未捕获异常。"""
    r = _invoke()
    assert r.exit_code in (0, 2)


# ── verify ──────────────────────────────────────────────────
@_needs_game
def test_verify_fast_全部通过() -> None:
    r = _invoke("verify", "--fast")
    assert r.exit_code == 0, r.output
    assert "失败 0" in r.output or "通过" in r.output


@_needs_game
def test_verify_only_单条断言() -> None:
    r = _invoke("verify", "--fast", "--only", "env.common_dirs")
    assert r.exit_code == 0, r.output
    assert "env.common_dirs" in r.output


@_needs_game
def test_verify_only_不存在的id() -> None:
    r = _invoke("verify", "--fast", "--only", "no.such.claim")
    assert r.exit_code == 2, "找不到指定断言属于前置条件缺失，应为 2"


@_needs_game
def test_verify_json_落盘(tmp_path) -> None:
    out = tmp_path / "verify.json"
    r = _invoke("verify", "--fast", "--json", str(out))
    assert r.exit_code == 0, r.output
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    summary = data["summary"]
    assert summary["总数"] > 0
    assert summary["失败"] == 0


# ── crosscheck（引擎交叉验证）────────────────────────────────
#: 夹具里的 Workshop mod 目录名。**故意不用本机那个 ``3007678964``**（Ultra Historical
#: Warfare 的覆盖版）：断言里出现这个名字，就说明读数来自夹具、不是宿主机装了什么。
_FIXTURE_MOD = "fixture_workshop_mod"

#: 合成日志里的游戏版本。它和宿主机真日志的版本**可能一样**（同一个 1.14.5），
#: 所以"读的是夹具"由断言**条数**背书（宿主机真日志有几百条 token 断言），不由版本号。
_FIXTURE_VERSION = "1.14.5"

#: 原版 ``gui/panel.gui``：4 行，KEY_ALPHA / KEY_BETA / KEY_GAMMA / KEY_DELTA 各占一行。
_VANILLA_GUI = 'a = "KEY_ALPHA"\nb = "KEY_BETA"\nc = "KEY_GAMMA"\nd = "KEY_DELTA"\n'


def _engine_log(*tokens: tuple[str, int, str]) -> str:
    """合成一份引擎日志：版本行 + 一条 ``gui`` 枚举 + 若干 ``(文件, 行, token)`` 断言。

    格式逐字取自真日志（读取正则见 ``src/pdx/engine_log.py:46-58``）：枚举行是
    ``Starting pre-enumerating 'gui'(.gui, , 0)``，token 行是
    ``Unlocalized text 'KEY' at gui/panel.gui:2``。
    """
    head = [
        f"[16:20:31][pdx_pdx.cpp:312]: Feeding game version into checksum: {_FIXTURE_VERSION}",
        "[16:20:36][pdx_scan.cpp:44]: Starting pre-enumerating 'gui'(.gui, , 0)",
    ]
    body = [
        f"[16:20:37][pdx_gui_localize.cpp:88]: Unlocalized text '{tok}' at {rel}:{line}"
        for rel, line, tok in tokens
    ]
    return "\n".join(head + body) + "\n"


def _crosscheck_fixture(
    base: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    vanilla: str,
    effective: str | None,
    log: str,
) -> None:
    """造一棵**自带**的核对现场（原版 + 覆盖版 + 引擎日志），并把 ``config`` 接上去。

    为什么必须自带
    --------------
    改造前这条用例直接读宿主机：``parse_logs()`` 读 ``Documents/.../logs``、
    ``build_override_map()`` 读 ``steamapps/workshop``。于是**同一份代码**在
    "装了 Workshop 覆盖版"的机器上退 3、在"没装覆盖版"的机器上退 1 ——
    用例的红/绿成了"宿主机装过什么 mod"的函数（D29 演练先把它读成"实现红了"，
    实机附判才查清是环境差）。夹具把四个根都指到 ``tmp_path``，结论只由输入决定。

    四个根各有分工，都不是随手指的：
    * ``game/gui/panel.gui`` —— **原版**，行号比较的基准；
    * ``workshop/<mod>/gui/panel.gui`` —— **生效文件**（``effective=None`` ⇒ 没有覆盖版）；
    * ``userdir/logs/debug.log`` —— 合成的引擎日志（``default_log_dir()`` 的真实来源）；
    * ``userdir/mod`` —— 空的本地 mod 目录（免得撞上宿主机装的本地 mod：
      d4 那种"workshop 里没有这个文件"的方向，宿主机本地 mod 会渗进来当覆盖版）。
    """
    root = base / "game"
    (root / "gui").mkdir(parents=True)
    (root / "gui" / "panel.gui").write_text(vanilla, encoding="utf-8")

    workshop = base / "workshop"
    (workshop / _FIXTURE_MOD / "gui").mkdir(parents=True)
    if effective is not None:
        (workshop / _FIXTURE_MOD / "gui" / "panel.gui").write_text(effective, encoding="utf-8")

    userdir = base / "userdir"
    (userdir / "logs").mkdir(parents=True)
    (userdir / "logs" / "debug.log").write_text(log, encoding="utf-8")
    (userdir / "mod").mkdir()  # 本地 mod：空的

    monkeypatch.setattr(config, "GAME", root)
    monkeypatch.setattr(config, "WORKSHOP", workshop)
    monkeypatch.setattr(config, "LOCAL_MODS", userdir / "mod")
    monkeypatch.setattr(config, "USERDIR", userdir)

    # 自检：四个根真的接上了。少了这一段，monkeypatch 一旦失效（改名、换写法），
    # 用例会**静默退回读宿主机** —— 那正是它改造前的病，不许再复发。
    from pdx import engine_log

    assert engine_log.default_log_dir() == userdir / "logs", "日志根没接上：会去读宿主机"
    # ⚠️ 值写左边、``config.XXX`` 写右边：全大写的属性在 ruff 眼里是常量，
    # 反过来写会踩 SIM300（Yoda 条件）。
    assert root == config.GAME, "原版根没接上"
    assert workshop == config.WORKSHOP, "Workshop 根没接上"
    assert userdir / "mod" == config.LOCAL_MODS, "本地 mod 根没接上"


def test_crosscheck_与引擎日志一致(tmp_path, monkeypatch) -> None:
    """三档结论都由**自带夹具**决定，不再随宿主机装没装覆盖版红/绿。

    函数名保留（外部有引用，如 ``tools/probe/perf_compare.py:50``），语义按
    2026-09-28 的口径：**"与引擎日志一致"不等于"退出码 0"** —— 被覆盖文件那一档的
    结论是"不可核对"（退出码 3）。

    ⚠️ 退出码与三态**一一对应**：0 = 全部匹配；1 = 有覆盖面缺口或**行号可比**的真错配；
    3 = 至少一条不可核对（行号不可比，或 token 在当前安装里整份都找不到）。

    ⚠️ 为什么改成夹具（D29）：旧版读宿主机真日志，于是"装了覆盖版"的机器退 3、
    "没装"的机器退 1，"两个方向"里只有宿主机碰巧满足的那一支真被跑到 ——
    用例的红/绿成了**环境**的函数。现在原版／覆盖版／日志三份输入都在 ``tmp_path``
    里现造，四个方向各钉一次，三态两端都有人看守。

    与相邻用例的分工（不许混说）：
    * ``test_engine_log_offline.py`` 夹的是 ``cross_check`` 这个纯函数；
    * ``test_crosscheck_真错配仍判红_阴性对照`` 夹的是**命令层**对报告对象的消费；
    * 本用例夹的是**整条命令链**（真 ``parse_logs`` → 真 ``build_override_map``
      → 真 ``cross_check`` → 真 ``token_verdicts``），只把文件系统换成夹具；
    * 真日志那一路的外部背书由 ``test_engine_crosscheck.py`` 看守（按 integration
      跳过）。本用例**不再声称**自己核过宿主机真日志。
    """

    def _run(tag: str):
        """跑一次真命令，返回 ``(结果, --json 落盘的读数)``。"""
        out = tmp_path / f"{tag}.json"
        result = _invoke("crosscheck", "--json", str(out))
        return result, json.loads(out.read_text(encoding="utf-8"))

    def _squash(text: str) -> str:
        """去掉**所有**空白：超长的绝对路径会被 rich 硬折行，折在哪不可预测。"""
        return re.sub(r"\s+", "", _flat(text))

    # ① 行号不可比 ⇒ 不可核对（退出码 3），既不是 0 也不是 1。
    #    生效版 6 行 vs 原版 4 行：KEY_ALPHA 被挤到第 5 行、KEY_BETA 整份没有；
    #    而原版第 2 行**有** KEY_BETA ⇒ 这不该被读成"日志比安装旧"，是"覆盖版删掉了它"。
    _crosscheck_fixture(
        tmp_path / "d1",
        monkeypatch,
        vanilla=_VANILLA_GUI,
        effective='a = "F1"\nb = "F2"\nc = "F3"\nd = "F4"\ne = "KEY_ALPHA"\nf = "F6"\n',
        log=_engine_log(
            ("gui/panel.gui", 2, "KEY_ALPHA"),
            ("gui/panel.gui", 3, "KEY_BETA"),
        ),
    )
    r1, d1 = _run("d1")
    assert r1.exit_code == 3, f"行号不可比必须报「不可核对」（既不是 0 也不是 1）：\n{r1.output}"
    flat1 = _flat(r1.output)
    # 读的必须是夹具那份日志：宿主机真日志在这里有几百条 token 断言。
    assert d1["日志版本"] == _FIXTURE_VERSION
    assert f"日志版本 {_FIXTURE_VERSION}" in flat1
    assert d1["概览"]["token 断言"] == 2, d1["概览"]
    assert d1["概览"]["覆盖面缺口"] == 0, "退出码不许被覆盖面缺口推成 1"
    assert d1["概览"]["三态·不可核对"] == 2, d1["概览"]
    assert d1["概览"]["三态·判红（行号可比却对不上）"] == 0, d1["概览"]
    assert d1["token分类"]["不可核对（行号不可比）"] == 2
    assert d1["token分类"]["真错配（行号可比）"] == 0
    assert "结论 = 不可核对" in flat1
    assert "既不是通过，也不是不一致" in flat1
    assert "覆盖面缺口：" not in flat1, "这一档不是覆盖面缺口推出来的红"
    assert "真错配" not in flat1, "行号不可比不许被说成真错配"
    assert "日志比安装旧" not in flat1, "KEY_BETA 在原版里有 ⇒ 不属于那一档"
    # 逐条给出原因：日志说的行 + 我们给出的行（就是我们与引擎读的不是同一份内容）
    assert "gui/panel.gui 日志第 2 行 'KEY_ALPHA' —— 覆盖版里别处有（第 5 行）" in flat1
    assert "gui/panel.gui 日志第 3 行 'KEY_BETA' —— 覆盖版整份都没有" in flat1
    # 覆盖来源：必须写出是哪个 mod 的哪份文件顶替了原版（不写就读成"不知道在跟谁对"）
    assert "覆盖来源（引擎读的是它，我们读的也是它）：" in flat1
    assert _FIXTURE_MOD in _squash(r1.output), f"没写出覆盖来源：\n{r1.output}"
    sources = [v["覆盖来源"] for v in d1["token分类"]["不可核对"]]
    assert sources, "不可核对那一档必须逐条给出覆盖来源"
    assert all(_FIXTURE_MOD in str(s) for s in sources), sources

    # ② 行号**可比**却对不上 ⇒ 真错配（退出码 1）。被覆盖不是免责牌：
    #    生效版 4 行 = 原版 4 行 ⇒ 同一套行号，KEY_ALPHA 却在第 3 行而不是第 2 行；
    #    同一份文件里另外两条命中 ⇒ 匹配，说明判红只针对对不上的那一条。
    _crosscheck_fixture(
        tmp_path / "d2",
        monkeypatch,
        vanilla=_VANILLA_GUI,
        effective='a = "KEY_GAMMA"\nb = "F2"\nc = "KEY_ALPHA"\nd = "KEY_DELTA"\n',
        log=_engine_log(
            ("gui/panel.gui", 2, "KEY_ALPHA"),  # 引擎说第 2 行，我们给出第 3 行
            ("gui/panel.gui", 1, "KEY_GAMMA"),
            ("gui/panel.gui", 4, "KEY_DELTA"),
        ),
    )
    r2, d2 = _run("d2")
    assert r2.exit_code == 1, f"行号可比的真错配必须判红：\n{r2.output}"
    flat2 = _flat(r2.output)
    assert d2["概览"]["token 断言"] == 3, d2["概览"]
    assert d2["概览"]["三态·判红（行号可比却对不上）"] == 1, d2["概览"]
    assert d2["概览"]["三态·匹配"] == 2, d2["概览"]
    assert d2["概览"]["三态·不可核对"] == 0, d2["概览"]
    assert d2["概览"]["覆盖面缺口"] == 0, "判红必须是真错配推的，不是覆盖面缺口"
    assert d2["token分类"]["真错配（行号可比）"] == 1
    assert "真错配" in flat2
    assert "我们给出：第 3 行" in flat2, "判红时要写出我们给出的行号"
    assert "结论 = 不可核对" not in flat2, "真错配不许被软化进不可核对那一档"

    # ③ 全部命中 ⇒ 退出码 0。三态可区分的那一端：判据不许被放宽成"永远报不可核对"。
    _crosscheck_fixture(
        tmp_path / "d3",
        monkeypatch,
        vanilla=_VANILLA_GUI,
        effective=_VANILLA_GUI,  # 覆盖版与原版逐行相同 ⇒ 行号可比
        log=_engine_log(
            ("gui/panel.gui", 1, "KEY_ALPHA"),
            ("gui/panel.gui", 3, "KEY_GAMMA"),
        ),
    )
    r3, d3 = _run("d3")
    assert r3.exit_code == 0, f"全部命中却报了红：\n{r3.output}"
    flat3 = _flat(r3.output)
    assert "与引擎日志完全一致" in flat3
    assert d3["概览"]["三态·匹配"] == 2, d3["概览"]
    assert d3["概览"]["三态·不可核对"] == 0, d3["概览"]
    assert "真错配" not in flat3
    assert "结论 = 不可核对" not in flat3

    # ④ "日志比安装旧"那一支（token 在生效版与原版里整份都找不到）同样是不可核对 ⇒ 3。
    #    旧用例这一支要靠宿主机日志碰运气（本机今天 0 条），夹具把它钉成确定的一档。
    _crosscheck_fixture(
        tmp_path / "d4",
        monkeypatch,
        vanilla='a = "KEY_A"\nb = "KEY_B"\n',
        effective=None,  # 没有覆盖版：原版就是生效版
        log=_engine_log(
            ("gui/panel.gui", 1, "KEY_A"),
            ("gui/panel.gui", 2, "KEY_GONE"),
        ),
    )
    r4, d4 = _run("d4")
    assert r4.exit_code == 3, f"日志比安装旧必须报不可核对：\n{r4.output}"
    flat4 = _flat(r4.output)
    assert "日志比安装旧" in flat4
    assert "在当前安装中整份文件都找不到" in flat4
    assert "0 条 token 行号不可比" in flat4, "这一档一条也不该算成行号不可比"
    assert "另有 1 条 token" in flat4
    assert "跑一次常规游戏" in flat4, "提示必须可操作"
    assert len(d4["token分类"]["整份文件都没有"]) == 1, d4["token分类"]
    assert d4["概览"]["三态·不可核对"] == 1, d4["概览"]
    assert d4["概览"]["覆盖面缺口"] == 0, d4["概览"]
    assert "真错配" not in flat4


def test_crosscheck_真错配仍判红_阴性对照(monkeypatch) -> None:
    """**阴性对照**：真错配必须仍然判红，证明"把这一档改成不可核对"没把判据放宽。

    夹具**离线、确定性**：把 ``cli.engine_log`` 的日志读取与核对整条换成构造对象，
    所以不依赖本机有没有日志、也不需要游戏。夹具只造 ``cross_check`` 真能产生的状态
    （``overridden_files`` 由行数派生，见下面 ``_report`` 的说明）。四个方向各钉一次
    （形状取自 ``test_engine_log_offline.py`` 的用例）：

    * 行数**相同** + token 在别的行 ⇒ 真错配：退出码 1、打印"我们给出 N"；
    * 行数**不同** + token 在别的行 ⇒ 不可核对：退出码 3、打印"覆盖版里别处有"；
    * 命中同一行 / 前缀关系 ⇒ 匹配：退出码 0（判据不许被放宽的那一侧）；
    * 生效文件**整份缺失** ⇒ 不可核对（不是真错配）—— 改前分析器与命令层结论相反的
      那一处（旧命令层读 ``line_counts`` 两值相等 ⇒ 判成真错配）。

    再直接夹**唯一判据**（``engine_log.token_verdicts()`` 的四条分支）与"命令层不许
    再有自己的判据函数"。

    ⑥ 那一次「真报告上的钳子」（行号不可比的条目一条也不许把退出码推成 1）
    **D34 起挪到** :func:`test_crosscheck_行号不可比不判红_真报告阴性对照`：
    旧写法读宿主机真日志，外面套 `claims` 非空 / 不是探针会话 / 真报告里真有不可核对
    条目三道**宿主闸门** —— 条件不成立时整段**一条断言都不跑**，
    那正是"静默过 = 假绿"（B114、t39/D3 同族）。挪走后它自带夹具、断言无条件执行。
    """
    from pdx import engine_log

    def _report(
        line_counts: dict[str, tuple[int, int]],
        *,
        prefix_on_line: bool = False,
        missing: bool = False,
        got: int | None = None,
        tokens_anywhere: int | None = 1,
    ) -> engine_log.CrossCheckReport:
        """真的报告对象（不是假的替身）：判据只读 line_counts / tokens_anywhere。

        ``overridden_files`` **由行数派生**，与 ``cross_check`` 的登记口径一致
        （``src/pdx/engine_log.py:676``：``before != after`` 才登记）—— 夹具不许造出
        真代码产生不了的状态。第一版夹具写成 ``overridden=True`` 配 ``line_counts=(2, 2)``，
        那正是这种不可能状态，结果把「行号可比的真错配」也判成了不可核对。
        """
        counts = line_counts.get("gui/panel.gui", (0, 0))
        return engine_log.CrossCheckReport(
            coverage={("gui", ".gui"): (1, 1, 1)},
            tokens=[("gui/panel.gui", 2, "KEY_HERE", got)],
            tokens_anywhere={("gui/panel.gui", "KEY_HERE"): tokens_anywhere},
            prefix_on_line={("gui/panel.gui", "KEY_HERE"): prefix_on_line},
            vanilla_anywhere={("gui/panel.gui", "KEY_HERE"): 2},
            overridden_files={"gui/panel.gui"} if counts[0] != counts[1] else set(),
            missing_files={"gui/panel.gui"} if missing else set(),
            line_counts=line_counts,
            log_version="1.14.4",
        )

    claim = engine_log.EngineClaim(
        kind="token_at", detail="", file_rel="gui/panel.gui", line=2, token="KEY_HERE"
    )
    monkeypatch.setattr(cli.engine_log, "parse_logs", lambda: ([claim], "1.14.4"))
    # 覆盖来源要给得出（"不可核对"那一档的输出要求写出它）。
    monkeypatch.setattr(
        cli.engine_log,
        "build_override_map",
        lambda: {"gui/panel.gui": config.GAME / "gui" / "panel.gui"},
    )

    # ① 行数相同 ⇒ 行号可比 ⇒ 真错配，必须判红。
    monkeypatch.setattr(
        cli.engine_log, "cross_check", lambda *_args, **_kwargs: _report({"gui/panel.gui": (2, 2)})
    )
    r = _invoke("crosscheck")
    assert r.exit_code == 1, f"行号可比的真错配没判红：\n{r.output}"
    assert "真错配" in _flat(r.output)
    assert "我们给出：第 1 行" in _flat(r.output), "判红时要写出我们给出的行号"
    assert "结论 = 不可核对" not in _flat(r.output), "真错配不许被软化进不可核对那一档"

    # ② 行数不同 ⇒ 行号不可比 ⇒ 不可核对，退出码 3（不是 1）。
    monkeypatch.setattr(
        cli.engine_log, "cross_check", lambda *_args, **_kwargs: _report({"gui/panel.gui": (2, 1)})
    )
    r3 = _invoke("crosscheck")
    assert r3.exit_code == 3, f"行号不可比却没报不可核对：\n{r3.output}"
    assert "覆盖版里别处有（第 1 行）" in _flat(r3.output)
    assert "结论 = 不可核对" in _flat(r3.output)

    # ③ 前缀关系（引擎报的 token 是同一行上更长 token 的前缀）⇒ 断言成立，
    #    既不判红也不用报不可核对 —— 三态只动"行号可不可比"，不碰"断言成不成立"。
    monkeypatch.setattr(
        cli.engine_log,
        "cross_check",
        lambda *_args, **_kwargs: _report({"gui/panel.gui": (2, 2)}, prefix_on_line=True),
    )
    r_prefix = _invoke("crosscheck")
    assert r_prefix.exit_code == 0, f"前缀关系被判红了（旧病复发）：\n{r_prefix.output}"
    assert "真错配" not in _flat(r_prefix.output)
    assert "结论 = 不可核对" not in _flat(r_prefix.output)

    # ④ 直接夹**唯一判据**（engine_log 的三态；命令层已不再有自己的判据函数）：
    #    · 命中同一行 ⇒ 匹配（判据不许被放宽的那一侧）；
    #    · 行数相同、token 在别处 ⇒ 真错配（判红那一档）；
    #    · 行数不同 ⇒ 不可核对（行号不可比）；
    #    · 生效文件整份缺失 ⇒ 也要判不可核对 —— 这曾经是两套判据的**真实分歧点**
    #      （分析器判不可核对，命令层因 `line_counts.get(rel, (0, 0))` 两值相等判真错配）。
    matched = _report({}, got=2)
    assert [v.state for v in matched.token_verdicts()] == [engine_log.TOKEN_MATCH]
    comparable = _report({"gui/panel.gui": (2, 2)})
    assert [v.state for v in comparable.token_verdicts()] == [engine_log.TOKEN_MISPLACED]
    assert comparable.token_verdicts()[0].ours == 1
    shorter = _report({"gui/panel.gui": (2, 1)})
    assert [v.state for v in shorter.token_verdicts()] == [engine_log.TOKEN_UNVERIFIABLE]
    assert [v.kind for v in shorter.token_verdicts()] == [engine_log.KIND_LINES_INCOMPARABLE]
    assert "别处有（第 1 行）" in shorter.token_verdicts()[0].reason
    gone = _report({"gui/panel.gui": (2, 2)}, missing=True, tokens_anywhere=None)
    assert [v.state for v in gone.token_verdicts()] == [engine_log.TOKEN_UNVERIFIABLE]
    assert [v.kind for v in gone.token_verdicts()] == [engine_log.KIND_STALE_NO_EFFECTIVE]
    assert not hasattr(cli, "_judge_token_line"), "命令层不许再留自己的判据（双判据病根）"

    # ⑤ 生效文件整份缺失：命令层同样必须说「不可核对」，不许说成真错配
    #    （这正是改前分析器与命令层结论相反的那一处：夹具的 line_counts 两值相等，
    #    旧命令层判据 `line_counts.get(rel, (0, 0))` 会判「真错配」）。
    monkeypatch.setattr(
        cli.engine_log,
        "cross_check",
        lambda *_args, **_kwargs: _report(
            {"gui/panel.gui": (2, 2)}, missing=True, tokens_anywhere=None
        ),
    )
    r_gone = _invoke("crosscheck")
    assert r_gone.exit_code == 3, f"文件整份缺失却判了红：\n{r_gone.output}"
    assert "结论 = 不可核对" in _flat(r_gone.output)
    assert "真错配" not in _flat(r_gone.output)

    # ⑥（原「真报告上的钳子」）**D34 起挪到**
    #    `test_crosscheck_行号不可比不判红_真报告阴性对照`：旧写法读宿主机真日志，
    #    外面套三道宿主闸门，条件不成立就整段不跑（静默过）；现在自带夹具、断言无条件执行。


def test_crosscheck_行号不可比不判红_真报告阴性对照(tmp_path, monkeypatch) -> None:
    """**真报告**上的钳子（D34 夹具版）：行号不可比的条目一条也不许把退出码推成 1。

    这一段原本长在 ``test_crosscheck_真错配仍判红_阴性对照`` 的 ⑥：读**宿主机真日志**，
    外面套 `claims` 非空 / 不是探针会话 / 真报告里真有不可核对条目三道**宿主闸门** ——
    宿主机没日志（或日志是探针会话、或真报告里没有那一档）时**一条断言都不跑**，
    也就是"什么都不验就过"（B114、t39/D3 同族）。现在现场由
    :func:`_crosscheck_fixture` 现造，三道闸门全部升级成**断言**：
    夹具日志必须被读到、必须不是探针会话、真报告里必须真有"行号不可比"这一档。

    与相邻用例的分工（不许混说）：同文件那条负对照是把 ``cross_check`` **整条换成**
    构造对象（夹的是命令层怎么消费报告）；本用例走的是**真** ``parse_logs`` → 真
    ``build_override_map`` → 真 ``cross_check`` → 真 ``token_verdicts``，
    只把 ``config`` 的四个根指到 ``tmp_path``。
    """
    from pdx import engine_log

    _crosscheck_fixture(
        tmp_path / "d6",
        monkeypatch,
        vanilla=_VANILLA_GUI,
        # 生效版 6 行 vs 原版 4 行 ⇒ 两套行号不可换算（输入同 ①，实测两条都落不可核对）。
        effective='a = "F1"\nb = "F2"\nc = "F3"\nd = "F4"\ne = "KEY_ALPHA"\nf = "F6"\n',
        log=_engine_log(
            ("gui/panel.gui", 2, "KEY_ALPHA"),
            ("gui/panel.gui", 3, "KEY_BETA"),
        ),
    )

    # 前置条件也是断言：读到的必须只有夹具那两条 token 断言 + 一条枚举
    # （宿主机真日志有几百条 token 断言）。
    claims, version = engine_log.parse_logs()
    assert claims, "夹具日志没被读到：现场没接上（旧病就是退回读宿主机）"
    token_claims = [c for c in claims if c.kind == "token_at"]
    assert len(token_claims) == 2, f"读到的不是夹具那两条：{[c.detail for c in claims]}"
    assert version == _FIXTURE_VERSION, f"日志版本读的不是夹具那份：{version}"
    assert not engine_log.probe_session(), "夹具被当成探针会话 ⇒ 真核对本来就没意义"

    rep = engine_log.cross_check(
        claims, log_version=version, overrides=engine_log.build_override_map()
    )
    assert rep.incomparable_tokens, "夹具没造出「行号不可比」这一档，钳子就无从夹起"
    assert not rep.misplaced_tokens, "行号不可比的条目不许同时进真错配那一档"

    r = _invoke("crosscheck")
    assert r.exit_code == 3, f"行号不可比的条目被拿来判红了：\n{r.output}"
    assert "结论 = 不可核对" in _flat(r.output)
    assert "真错配" not in _flat(r.output)


def test_crosscheck_无日志时返回2(tmp_path, monkeypatch) -> None:
    """日志不是仓库的一部分，缺失是正常情况 —— 必须报前置条件缺失而非假装通过。"""
    monkeypatch.setattr(cli.engine_log, "default_log_dir", lambda: tmp_path / "nope")
    r = _invoke("crosscheck")
    assert r.exit_code == 2, r.output
    assert "找不到引擎日志" in r.output


# ── check-outputs ───────────────────────────────────────────
def test_check_outputs_缺产物时返回2(tmp_path, monkeypatch) -> None:
    """产物不存在必须是 2 并给出可操作的提示，而不是抛裸 traceback。"""
    monkeypatch.setattr(config, "OUT_GAME", tmp_path / "nope")
    monkeypatch.setattr(cli.config, "OUT_GAME", tmp_path / "nope")
    r = _invoke("check-outputs")
    assert r.exit_code == 2, r.output
    assert "缺少产物" in r.output or "analyze" in r.output


@_needs_game
def test_check_outputs_有产物时通过() -> None:
    if not (config.OUT_GAME / "游戏本体.json").is_file():
        pytest.skip("尚无产物，先跑 v3 analyze")
    r = _invoke("check-outputs")
    assert r.exit_code == 0, r.output


# ── ai-surface ──────────────────────────────────────────────
def test_ai_surface_没有游戏时返回2(tmp_path, monkeypatch) -> None:
    """P13：本命令的三件事全部枚举自原版文件 —— 没有游戏必须报前置条件缺失。

    实测过不挡的后果：`--check` 在读 `common/defines/00_ai.txt` 时抛
    `FileNotFoundError`，把 traceback 打到用户脸上（退出码 1），
    与 `v3 modguard` / `v3 tables` 的"缺前置条件是 2、不是失败"口径不一致。
    """
    monkeypatch.setattr(cli.config, "GAME", tmp_path / "nope")
    r = _invoke("ai-surface", "--check")
    assert r.exit_code == 2, r.output
    assert "前置条件缺失" in r.output
    assert "V3_ROOT" in r.output, "提示要给出可操作的下一步（怎么指定游戏根目录）"


# ── show ────────────────────────────────────────────────────
@_needs_game
def test_show_能转储产物结构() -> None:
    if not (config.OUT_GAME / "游戏本体.json").is_file():
        pytest.skip("尚无产物，先跑 v3 analyze")
    r = _invoke("show")
    assert r.exit_code == 0, r.output
    assert "游戏本体" in r.output


# ── defines ─────────────────────────────────────────────────
@_needs_game
def test_defines_指定命名空间() -> None:
    r = _invoke("defines", "--ns", "NAI")
    assert r.exit_code == 0, r.output
    assert "NAI" in r.output


@_needs_game
def test_defines_不存在的命名空间返回2() -> None:
    r = _invoke("defines", "--ns", "NO_SUCH_NAMESPACE_XYZ")
    assert r.exit_code == 2, "找不到命名空间属于前置条件缺失，应为 2"


@_needs_game
def test_defines_json_落盘(tmp_path) -> None:
    out = tmp_path / "defines.json"
    r = _invoke("defines", "--ns", "NAI", "--json", str(out))
    assert r.exit_code == 0, r.output
    assert out.is_file()
    json.loads(out.read_text(encoding="utf-8"))  # 必须是合法 JSON


# ── index ───────────────────────────────────────────────────
@_needs_game
def test_index_dry_run_不写文件() -> None:
    target = config.DOCS / "13-common全量键名索引.md"
    before = target.read_bytes() if target.is_file() else b""
    r = _invoke("index", "--dry-run")
    assert r.exit_code == 0, r.output
    after = target.read_bytes() if target.is_file() else b""
    assert before == after, "--dry-run 不该改写文档"


# ── snapshot ────────────────────────────────────────────────
@_needs_game
def test_snapshot_list_列出快照() -> None:
    r = _invoke("snapshot", "list")
    assert r.exit_code == 0, r.output


def test_snapshot_create_输出口径不互相覆盖(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pdx import cli as cli_module
    from pdx import snapshot as snapshot_module

    monkeypatch.setattr(snapshot_module, "SNAPSHOT_DIR", tmp_path)
    full = cli_module._snapshot_output_path("probe", compact=False)
    compact = cli_module._snapshot_output_path("probe", compact=True)
    assert full == tmp_path / "probe.json"
    assert compact == tmp_path / "probe.compact.json"
    assert full != compact


@_needs_game
def test_snapshot_diff_缺快照时返回2() -> None:
    r = _invoke("snapshot", "diff", "no_such_snapshot_a", "no_such_snapshot_b")
    assert r.exit_code == 2, "快照不存在属于前置条件缺失，应为 2"


# ── snapshot（cli.py 里最大的未覆盖区）──────────────────────
@_needs_game
@pytest.mark.slow
def test_snapshot_创建_自检_差分_全链路(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """一条链路覆盖三个子命令：create -> verify -> diff。

    snapshot create 要跑一遍完整分析（约 30 秒），所以三个子命令合在一个
    用例里跑，避免重复付费。

    ⚠️ **产物隔离到本用例自己的临时目录**（t95，2026-09-25 修）。原来它用固定 label
    ``cli-test-tmp`` 写进**共享**的 ``tools/out/snapshots/``，并在开头/结尾按前缀
    删同名文件 —— 于是只要同一台机器上有**第二个 pytest 进程**（另一个人/另一个 agent
    在这一棵树上跑全量），两条用例就会互相删对方刚建好的产物。实测：错峰 35 秒起两条
    并发跑，后一条在 ``:269`` 报
    ``快照不存在：…\\tools\\out\\snapshots\\cli-test-tmp.json``（exit 2）—— 与 ``t19``
    全量里那条红**逐字同形**；而单跑 ``-n 0`` 必绿（没有第二个进程）。

    ``_invoke`` 是**进程内**调用（``CliRunner``），所以把 ``snapshot.SNAPSHOT_DIR``
    指到 ``tmp_path`` 就够了：产物既不进共享平面、也不受任何并发进程影响
    （同文件里 ``verify.SNAPSHOT_DIR`` 已有同款先例，见 :func:`test_from_snapshot_没有快照时仍核验清单并提示补快照`）。
    末了两条断言把「隔离」变成**可复算的读数**：产物在私有目录里，且共享目录的文件集合
    跑前跑后逐个名字相同。
    """
    from pdx import snapshot

    shared = config.OUT / "snapshots"
    before = sorted(p.name for p in shared.glob("*.json")) if shared.is_dir() else []
    monkeypatch.setattr(snapshot, "SNAPSHOT_DIR", tmp_path)
    label = "cli-test-tmp"

    r = _invoke("snapshot", "create", "--label", label)
    assert r.exit_code == 0, r.output
    assert (tmp_path / f"{label}.json").is_file(), "产物必须落在本用例自己的临时目录里"

    # 自检：同环境重复构建必须逐字节相同
    r = _invoke("snapshot", "verify")
    assert r.exit_code == 0, r.output

    # 差分：自己跟自己比，必须"完全一致"且退出码 0
    r = _invoke("snapshot", "diff", label, label)
    assert r.exit_code == 0, r.output
    assert "一致" in r.output

    after = sorted(p.name for p in shared.glob("*.json")) if shared.is_dir() else []
    assert after == before, (
        "本用例的产物跑到仓库共享快照目录里去了 —— 那样并行的另一条用例/另一局全量会互相删（t95 实测）"
    )


@_needs_game
def test_snapshot_list_输出快照表() -> None:
    r = _invoke("snapshot", "list")
    assert r.exit_code == 0, r.output


# ── defines 的其余分支 ──────────────────────────────────────
@_needs_game
def test_defines_overlay_预览覆盖范围(tmp_path) -> None:
    """--overlay 是「写 mod 前先看清会覆盖什么」的入口，此前零覆盖。"""
    mod = tmp_path / "mymod.txt"
    mod.write_text("NAI = { SOME_EXISTING = 1  MY_NEW_ONE = 2 }\n", encoding="utf-8")
    r = _invoke("defines", "--overlay", str(mod))
    assert r.exit_code == 0, r.output
    assert "NAI" in r.output


@_needs_game
def test_defines_默认摘要() -> None:
    r = _invoke("defines")
    assert r.exit_code == 0, r.output


# ── verify 的三个分支（漂移扫描 / 未登记扫描 / 关掉漂移）────
@_needs_game
@pytest.mark.slow
def test_verify_默认包含漂移扫描() -> None:
    """``v3 verify`` 必须真的跑文档漂移扫描。

    这条守的是一个**真实发生过的**失效：``find_doc_drift`` 曾经只被测试调用，
    ``v3 verify`` 一路报「全绿」而文档里躺着几十个过期数字。
    现在默认跑，且结果会打在输出里。
    """
    r = _invoke("verify", "--fast")
    assert r.exit_code == 0, r.output
    assert "文档正文" in r.output, "verify 的输出里必须体现漂移扫描的结果"


@_needs_game
@pytest.mark.slow
def test_verify_no_drift_跳过漂移扫描() -> None:
    r = _invoke("verify", "--fast", "--no-drift")
    assert r.exit_code == 0, r.output
    assert "文档正文" not in r.output, "--no-drift 时不应再输出漂移结论"


@_needs_game
def test_verify_unregistered_列出未登记断言() -> None:
    """``--unregistered`` 是排查工具，退出码必须是 0（不是门禁）。"""
    r = _invoke("verify", "--unregistered")
    assert r.exit_code == 0, r.output


@_needs_game
def test_verify_不存在的_only_返回失败() -> None:
    """``--only`` 拼错时不能静默「全部通过」退出 0。"""
    r = _invoke("verify", "--only", "no-such-claim-id")
    assert r.exit_code == 2, r.output


# ── verify --from-snapshot（不读游戏，CI 走这条）───────────
def test_from_snapshot_不读游戏也能核验() -> None:
    """这条**不需要游戏** —— 它就是精简快照入库的理由。

    注意这里刻意不加 ``@_needs_game``：CI 上没有游戏，而这条必须能跑。

    ⚠️ 断言的 id **必须能在 80 列的表格里完整显示**：离线覆盖的断言从 39 条涨到 43 条
    之后，rich 为了塞下更长的「断言」列把 ID 列省略成了 ``docs.total_b…``，
    于是这条断言挂在**显示层**而不是逻辑层（实测踩过）。这里改判「行数对得上」+
    抽样长 id 的前缀 —— 显示细节不该决定这条测试的成败。
    """
    r = _invoke("verify", "--from-snapshot")
    assert r.exit_code == 0, r.output
    assert "离线核验" in r.output
    assert "离线真值覆盖" in r.output, "应说明覆盖了多少条，别让人以为全查过了"
    # 官方文档清单是第二份离线真值：没有游戏也能多核验那几条（表格里显示的是 id）。
    for cid in ("env.md_total", "docs.total_b", "docs.max_b"):
        assert cid in r.output, f"{cid} 来自入库清单，应当也能核验：{r.output}"


def test_from_snapshot_只有时不存在的_id_返回用法错误() -> None:
    r = _invoke("verify", "--from-snapshot", "--only", "no-such-claim-id")
    assert r.exit_code == 2, r.output


def test_from_snapshot_没有快照时仍核验清单并提示补快照(tmp_path, monkeypatch) -> None:
    """没有快照**不再整体失败** —— 官方文档清单照样能核验。

    旧行为是一见没有快照就退出码 2，于是那几条不需要游戏的断言也跟着丢。
    现在改成：照常核验清单那几条，并在输出里提示怎么补一份快照。
    仍然不能静默通过 —— 提示必须在。

    条数**不写死**：它等于「走官方文档清单那几条断言」的个数
    （``_MANIFEST_GETTERS`` 里那几种类型），加一条 md 断言就该跟着涨 ——
    写死 3 的结果是每加一条相关的断言都要来改一次测试。
    """
    monkeypatch.setattr(verify, "SNAPSHOT_DIR", tmp_path)
    r = _invoke("verify", "--from-snapshot")
    assert r.exit_code == 0, r.output
    assert "snapshot create --compact" in r.output, f"提示里应给出重建命令：{r.output}"
    assert "env.md_total" in r.output, f"清单那几条应当照常核验：{r.output}"
    n = sum(1 for c in verify.CLAIMS if c.kind in verify._MANIFEST_GETTERS)
    assert f"通过 {n} / {n}" in r.output, f"清单恰好覆盖 {n} 条：{r.output}"


def test_from_snapshot_快照缺域时大声失败(tmp_path, monkeypatch) -> None:
    """快照在、但域是空的 —— 每条都报「快照里没有对应域」，退出码 1。

    刻意**不**静默跳过：一份缺域的残缺快照应当吵，而不是让 CI 报绿。
    """
    from pdx import snapshot as _snap

    empty = _snap.Snapshot(version={"caligula_branch": "test"}, sections={}, compact=True)
    empty.write(tmp_path / "x.compact.json")
    monkeypatch.setattr(verify, "SNAPSHOT_DIR", tmp_path)
    r = _invoke("verify", "--from-snapshot")
    assert r.exit_code == 1, r.output
    assert "快照里没有对应域或条目" in r.output


def test_from_snapshot_筛出的断言都不被快照覆盖时报错() -> None:
    """``--only`` 筛到一批「快照注定覆盖不了」的断言时，要报错而不是报 0 通过。"""
    r = _invoke("verify", "--from-snapshot", "--only", "pfx.")
    assert r.exit_code == 2, r.output
    assert "_SNAPSHOT_GETTERS" in r.output, f"提示应指向取值器表：{r.output}"
    assert "_MANIFEST_GETTERS" in r.output, f"也要提到清单那份取值器：{r.output}"


# ── index 真正写盘的那条路 ──────────────────────────────────
@_needs_game
@pytest.mark.slow
def test_index_写盘后内容自洽() -> None:
    """--dry-run 已测过；这条走真实写盘路径，并确认产物首行与统计对得上。"""
    target = config.DOCS / "13-common全量键名索引.md"
    before = target.read_bytes()
    try:
        r = _invoke("index")
        assert r.exit_code == 0, r.output
        text = target.read_text(encoding="utf-8")
        assert text.startswith("# 13 · common 全量键名索引")
        assert "数据版本" in text, "生成的索引必须带版本溯源"
    finally:
        target.write_bytes(before)


# ── analyze（慢，只跑最省的一种组合）────────────────────────
@_needs_game
@pytest.mark.slow
def test_analyze_不写盘不跑mod() -> None:
    r = _invoke("analyze", "--no-mods", "--no-write", "--quiet")
    assert r.exit_code == 0, r.output


# ── 真起进程：验证装出来的入口点与编码兜底 ──────────────────
class TestSubprocess:
    """进程内测试看不到的两件事：入口点是否装好、编码兜底是否生效。"""

    def _run(self, *args: str, env_extra: dict[str, str] | None = None):
        import os

        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, "-m", "pdx.cli", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=300,
            check=False,
        )

    def test_module_help(self) -> None:
        p = self._run("--help")
        assert p.returncode == 0, p.stderr
        assert "analyze" in p.stdout

    def test_用法错误退出码为2(self) -> None:
        p = self._run("no-such-command")
        assert p.returncode == 2, p.stderr

    @_needs_game
    def test_gbk_控制台下不因编码崩溃(self) -> None:
        """GBK 是中文 Windows 的默认控制台编码，``✅`` 这类字符会直接抛异常。

        库里的 ``enable_utf8_stdio()`` 就是为这一条存在的；
        ``rich`` 替代不了它 —— 实测 ``Console().print("✅")`` 同样会炸。
        """
        p = self._run(
            "verify", "--fast", "--only", "env.common_dirs", env_extra={"PYTHONIOENCODING": "gbk"}
        )
        assert p.returncode == 0, f"GBK 下崩溃了：{p.stderr[:400]}"
        assert "UnicodeEncodeError" not in p.stderr

    def test_安装的入口点可用(self) -> None:
        """``[project.scripts]`` 装出来的 ``v3`` 必须真能跑。

        这条能抓到「改了 pyproject 但没重新 pip install -e .」这类问题。

        入口点照着**当前解释器的安装方案**找，不走 ``PATH`` ——
        虚拟环境通常不激活就调 pytest，这时 ``shutil.which("v3")`` 找不到，
        测试会永远静默跳过，等于没有这条检查（实测踩过）。
        """
        scripts = Path(sysconfig.get_path("scripts"))
        candidates = [scripts / "v3.exe", scripts / "v3"]
        exe = next((c for c in candidates if c.is_file()), None)
        if exe is None:
            pytest.fail(
                f"v3 入口点不存在于 {scripts}；"
                "请运行 pip install -e . 重新生成（改了 pyproject 后必须重装）"
            )
        p = subprocess.run(
            [str(exe), "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
        assert p.returncode == 0, p.stderr
        assert "analyze" in p.stdout
