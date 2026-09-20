"""`v3` 子命令的补充覆盖（CliRunner，不起子进程）。

`test_cli.py` 覆盖了主路径，`test_cli_new_commands.py` 覆盖了这一轮新加的命令；
这里补的是**剩下的分支**：取值分布的 `csv`、普查 `assets`、清单 `backlog`、
离线核验 `mirror check`、维护入口 `refresh --dry-run`、快照 diff/verify、
以及 `verify --fix` 在「本来就一致」时的早退分支。

为什么值得单独一个文件：`cli.py` 是全包最大的模块（890 条语句），
它的缺口一度占到整体未覆盖语句的一半 —— 而这些分支**都能零成本跑到**
（进程内调用、只读命令），没有理由留着不测。
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from pdx import config
from pdx.cli import app

pytestmark = pytest.mark.unit

runner = CliRunner()
_needs_game = pytest.mark.skipif(not (config.GAME / "common").is_dir(), reason="游戏目录不可用")


def _run(*args: str):
    return runner.invoke(app, list(args))


# ────────────────────────── backlog ──────────────────────────


def test_backlog_给出单一数字() -> None:
    result = _run("backlog")
    assert result.exit_code == 0, result.output
    assert "还开着的条目" in result.output
    assert "文档" in result.output


def test_backlog_按篇过滤() -> None:
    result = _run("backlog", "-d", "04")
    assert result.exit_code == 0
    assert "04-脚本系统.md" in result.output


def test_backlog_列出条目() -> None:
    result = _run("backlog", "-d", "04", "--list", "-n", "3")
    assert result.exit_code == 0
    assert "条：" in result.output


def test_backlog_不存在的篇是空清单() -> None:
    result = _run("backlog", "-d", "99-没有这篇")
    assert result.exit_code == 0
    assert "没有还开着的条目" in result.output


# ────────────────────────── assets / csv ──────────────────────────


@_needs_game
def test_assets_普查能跑并给出关键数字(tmp_path) -> None:
    out = tmp_path / "dds.json"
    result = _run("assets", "--no-examples", "--json", str(out))
    assert result.exit_code == 0, result.output
    assert "DDS 头普查" in result.output
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["找到"] >= payload["可解析"] > 0
    assert payload["可解析"] == sum(payload["格式"].values())
    assert payload["非2幂"] + payload["可解析"] - payload["非2幂"] == payload["可解析"]


@_needs_game
def test_csv_逐列分布() -> None:
    result = _run("csv", "map_data/adjacencies.csv")
    assert result.exit_code == 0, result.output
    assert "逐列取值分布" in result.output
    assert "Type" in result.output


@_needs_game
def test_csv_单列取值() -> None:
    result = _run("csv", "map_data/adjacencies.csv", "-c", "Through", "-n", "3")
    assert result.exit_code == 0
    assert "不同取值 1" in result.output
    assert "-1" in result.output


@_needs_game
def test_csv_列名不存在时报用法错误() -> None:
    result = _run("csv", "map_data/adjacencies.csv", "-c", "NO_SUCH_COLUMN")
    assert result.exit_code == 2
    assert "没有列" in result.output


def test_csv_文件不存在时报用法错误() -> None:
    result = _run("csv", "map_data/no_such_file.csv")
    assert result.exit_code == 2


@_needs_game
def test_strings_按族聚类() -> None:
    result = _run("strings", "--families", "--min", "50", "-n", "5", "--no-list")
    assert result.exit_code == 0, result.output
    assert "聚出的族" in result.output
    assert "command" in result.output


@_needs_game
def test_strings_前缀族() -> None:
    result = _run("strings", "--families", "--by", "prefix", "--min", "50", "-n", "3", "--no-list")
    assert result.exit_code == 0
    assert "按前缀聚出的族" in result.output


# ────────────────────────── 维护入口（只读分支）──────────────────────────


@_needs_game
def test_mirror_check_一致() -> None:
    result = _run("mirror", "check")
    assert result.exit_code == 0, result.output
    assert "一致" in result.output


@_needs_game
def test_refresh_dry_run_只报告() -> None:
    result = _run("refresh", "--dry-run")
    assert result.exit_code == 0, result.output
    assert "全部一致" in result.output or "需要改" in result.output


def test_verify_fix_在一致时早退() -> None:
    """`--fix` 会写盘，但「本来就一致」时应当早退、一个字节都不改。"""
    before = (config.DOCS / "04-脚本系统.md").read_text(encoding="utf-8")
    result = _run("verify", "--fix")
    after = (config.DOCS / "04-脚本系统.md").read_text(encoding="utf-8")
    assert after == before, "--fix 在一致时不该改文档"
    assert result.exit_code == 0, result.output
    assert "无需改动" in result.output or "已改写" in result.output


@_needs_game
def test_snapshot_diff_自己与自己无差异() -> None:
    """snapshot diff 收的是**快照名**（不含 .json），不是路径。"""
    snaps = sorted(config.OUT.joinpath("snapshots").glob("*.compact.json"))
    if not snaps:
        pytest.skip("没有精简快照")
    label = snaps[-1].name.removesuffix(".compact.json")
    result = _run("snapshot", "diff", label, label)
    assert result.exit_code == 0, result.output
    assert "无差异" in result.output or "0" in result.output


@_needs_game
def test_snapshot_verify_自检() -> None:
    result = _run("snapshot", "verify")
    assert result.exit_code == 0, result.output


@_needs_game
def test_snapshot_list_可读() -> None:
    result = _run("snapshot", "list")
    assert result.exit_code == 0
    assert ".json" in result.output
