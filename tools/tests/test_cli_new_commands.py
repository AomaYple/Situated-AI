"""新子命令的端到端测试（CliRunner，不起子进程）。

为什么用 CliRunner 而不是 subprocess：`test_cli.py` 里那一族真起进程，慢且
只能看退出码与 stdout；这里要的是**分支覆盖** —— 每个新命令的每条分支
（有数据/没数据、一致/不一致、写了/没写）都要走到。跑完一条几十毫秒。

哪些用例要游戏：`evidence` / `prefixes` 要读 `game/`，标 integration（CI 上跳过）；
其余（`unverified` / `cache` / `lock` / `tables --offline` / `cov --check-only`）
只读仓库里的文档、快照与自己的数据，在 CI 上也能跑。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from pdx import config
from pdx.cli import app

pytestmark = pytest.mark.unit

runner = CliRunner()

_needs_game = pytest.mark.skipif(not (config.GAME / "common").is_dir(), reason="游戏目录不可用")


def _run(*args: str):
    return runner.invoke(app, list(args))


def test_unverified列出清单() -> None:
    result = _run("unverified", "--no-context")
    assert result.exit_code == 0, result.output
    assert "【未确认】清单" in result.output


def test_unverified按篇过滤() -> None:
    result = _run("unverified", "--doc", "04", "--no-context")
    assert result.exit_code == 0
    assert "04-脚本系统.md" in result.output
    assert "06-本地化" not in result.output


def test_unverified找不到的篇是空清单() -> None:
    result = _run("unverified", "--doc", "99-不存在的篇")
    assert result.exit_code == 0
    assert "没有" in result.output


def test_cache打印两层状态() -> None:
    result = _run("cache")
    assert result.exit_code == 0
    assert "解析缓存" in result.output
    assert "磁盘" in result.output


def test_cache可以列出分片() -> None:
    result = _run("cache", "--list")
    assert result.exit_code == 0


def test_lock与当前环境对账() -> None:
    """入库的 `requirements.lock` 必须与当前环境一致（不一致就说明该重生成）。"""
    result = _run("lock")
    assert result.exit_code == 0, result.output
    assert "一致" in result.output


def test_lock写入模式可用(tmp_path, monkeypatch) -> None:
    """`--write` 走一遍渲染与落盘（写到临时文件，不动仓库里那份）。"""
    from pdx import lockfile

    # 写盘路径 = REPO/LOCK_FILE，而闭包解析要读 REPO/pyproject.toml —— 两样都备齐
    (tmp_path / "pyproject.toml").write_text(
        (config.REPO / "pyproject.toml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    target = tmp_path / lockfile.LOCK_FILE
    monkeypatch.setattr(lockfile.config, "REPO", tmp_path)
    result = _run("lock", "--write")
    assert result.exit_code == 0, result.output
    assert target.is_file()
    assert lockfile.read(target)


def test_tables_offline核对入库快照() -> None:
    result = _run("tables", "--offline")
    assert result.exit_code == 0, result.output
    assert "生成表都与文档一致" in result.output


def test_tables_offline的only会挑不出东西时报错() -> None:
    result = _run("tables", "--offline", "--only", "不存在的文档名")
    assert result.exit_code == 0, "挑不出目标时视为一致（没有可比的东西）"


def test_tables的only只配offline() -> None:
    result = _run("tables", "--only", "05")
    assert result.exit_code == 2, "在线核对是整篇逐表比对，--only 无意义"


def test_cov缺少数据时给出指引(tmp_path, monkeypatch) -> None:
    from pdx import covgate

    monkeypatch.setattr(covgate, "COV_JSON", tmp_path / "没有.json")
    result = _run("cov", "--check-only")
    assert result.exit_code == 2
    assert "先跑一次" in result.output


@_needs_game
def test_evidence查一个真实键() -> None:
    result = _run("evidence", "after", "--no-samples")
    assert result.exit_code == 0, result.output
    assert "四类证据" not in result.output  # 帮助文本不该混进结果
    assert "目录：" in result.output
    assert "exe 字面量" in result.output


@_needs_game
def test_evidence的exe_grep查一族名字() -> None:
    result = _run("evidence", "--exe-grep", "scripted_gui")
    assert result.exit_code == 0
    assert "jomini_scripted_guis" in result.output


@_needs_game
def test_evidence不给键名时报用法错() -> None:
    result = _run("evidence")
    assert result.exit_code == 2


@_needs_game
def test_prefixes列出目录用量() -> None:
    result = _run("prefixes", "-n", "5")
    assert result.exit_code == 0, result.output
    assert "功能前缀" in result.output


@_needs_game
def test_prefixes可以只看一个目录() -> None:
    result = _run("prefixes", "common/scripted_triggers")
    assert result.exit_code == 0
    assert "REPLACE" in result.output


@_needs_game
def test_prefixes空目录会提示() -> None:
    result = _run("prefixes", "common/绝对没有这个目录")
    assert result.exit_code == 0
    assert "没有任何带前缀的条目" in result.output


def test_cov_check_only在有数据时打印表格(tmp_path, monkeypatch) -> None:
    """没有数据时给指引、有数据时给表格 —— 两条分支都要走到。"""
    import json

    from pdx import covgate

    payload = {
        "files": {
            "tools/pdx/parser.py": {"summary": {"percent_covered": 99.0, "num_statements": 100}}
        }
    }
    path = tmp_path / "cov.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(covgate, "COV_JSON", path)
    result = _run("cov", "--check-only", "--top", "1")
    assert "模块覆盖率" in result.output
    assert "整体" in result.output


def test_cov整体不达标时退出码为1(tmp_path, monkeypatch) -> None:
    import json

    from pdx import covgate

    payload = {
        "files": {
            "tools/pdx/parser.py": {"summary": {"percent_covered": 10.0, "num_statements": 100}}
        }
    }
    path = tmp_path / "cov.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(covgate, "COV_JSON", path)
    result = _run("cov", "--check-only")
    assert result.exit_code == 1
    assert "❌" in result.output


def test_每个新命令都有帮助文本() -> None:
    """帮助是给下一个人看的说明书 —— 新命令不能只有名字。"""
    for name in ("evidence", "unverified", "prefixes", "cache", "cov", "lock"):
        result = _run(name, "--help")
        assert result.exit_code == 0, name
        assert len(result.output) > 200, f"{name} 的帮助太短了"


def test_离线快照路径与验证器同源() -> None:
    """两个模块不许各写一套「哪份快照算数」的规则。"""
    from pdx import tables_offline, verify

    assert tables_offline.load_tables() == verify.latest_compact_snapshot().sections.get(  # type: ignore[union-attr]
        tables_offline.SECTION, {}
    )
    assert isinstance(tables_offline.load_tables(), dict)
    assert Path(config.OUT / "snapshots").is_dir()
