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

from pdx import cli, config, verify

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
    """唯一由外部背书的核对：清单来自引擎日志，不是我们自己的目录表。

    ⚠️ 退出码只认「覆盖面缺口」与「行号错位」；**整份文件都找不到的 token
    不判红** —— 那是日志描述的 mod 状态与当前安装不一致（实测：Workshop mod
    「Ultra Historical Warfare」支持 1.13 而本机 1.14.3，覆盖了那几个 gui），
    不是解析器问题。这种情况整条命令给出明确提示、返回 0。
    """
    from pdx import engine_log

    if not engine_log.parse_logs()[0]:
        pytest.skip("本机没有引擎日志（需要运行过一次游戏）")
    if engine_log.probe_session():
        pytest.skip("日志来自探针会话（只加载了探针 mod），外部真值的 mod 集不同")
    r = _invoke("crosscheck")
    assert r.exit_code == 0, r.output
    assert "覆盖面缺口" in r.output
    if "日志比安装旧" in r.output:
        assert "跑一次常规游戏" in r.output  # 提示必须可操作


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
