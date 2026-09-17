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
0 = 成功；1 = 检查未通过；2 = 用法错误或前置条件缺失（如产物不存在）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pdx import cli, config

pytestmark = pytest.mark.cli

runner = CliRunner()

_needs_game = pytest.mark.skipif(not (config.GAME / "common").is_dir(), reason="游戏目录不可用")


def _invoke(*args: str):
    return runner.invoke(cli.app, list(args))


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
@_needs_game
def test_crosscheck_与引擎日志一致() -> None:
    """唯一由外部背书的核对：清单来自引擎日志，不是我们自己的目录表。"""
    from pdx import engine_log

    if not engine_log.parse_logs()[0]:
        pytest.skip("本机没有引擎日志（需要运行过一次游戏）")
    r = _invoke("crosscheck")
    assert r.exit_code == 0, r.output
    assert "覆盖面缺口" in r.output


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


@_needs_game
def test_snapshot_diff_缺快照时返回2() -> None:
    r = _invoke("snapshot", "diff", "no_such_snapshot_a", "no_such_snapshot_b")
    assert r.exit_code == 2, "快照不存在属于前置条件缺失，应为 2"


# ── snapshot（cli.py 里最大的未覆盖区）──────────────────────
@_needs_game
@pytest.mark.slow
def test_snapshot_创建_自检_差分_全链路() -> None:
    """一条链路覆盖三个子命令：create -> verify -> diff。

    snapshot create 要跑一遍完整分析（约 30 秒），所以三个子命令合在一个
    用例里跑，避免重复付费。用带前缀的临时快照名，跑完删掉。
    """
    from pdx import snapshot

    label = "cli-test-tmp"
    paths = snapshot.list_snapshots()
    for p in paths:
        if p.stem.startswith(label):
            p.unlink(missing_ok=True)
    try:
        r = _invoke("snapshot", "create", "--label", label)
        assert r.exit_code == 0, r.output

        # 自检：同环境重复构建必须逐字节相同
        r = _invoke("snapshot", "verify")
        assert r.exit_code == 0, r.output

        # 差分：自己跟自己比，必须"完全一致"且退出码 0
        r = _invoke("snapshot", "diff", label, label)
        assert r.exit_code == 0, r.output
        assert "一致" in r.output
    finally:
        for p in snapshot.list_snapshots():
            if p.stem.startswith(label):
                p.unlink(missing_ok=True)


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

        入口点直接照着**当前解释器所在的 Scripts 目录**找，不走 ``PATH`` ——
        虚拟环境通常不激活就调 pytest，这时 ``shutil.which("v3")`` 找不到，
        测试会永远静默跳过，等于没有这条检查（实测踩过）。
        """
        scripts = Path(sys.executable).parent
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
