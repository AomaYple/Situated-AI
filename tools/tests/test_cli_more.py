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
def test_verify_漂移分支不会因富文本崩掉(monkeypatch) -> None:
    """回归：漂移分支里有个**悬空的 ``[/]``**，一旦真有漂移，rich 直接抛 MarkupError。

    这条分支此前从没被走到过（漂移数一直是 0），于是「文档正文与断言表脱节」
    这个最要紧的失败提示，第一次真正需要它时打不出来 —— 报出来的是
    ``MarkupError: closing tag '[/]'``，而不是哪篇文档的哪个数字过期了。
    """
    from pdx import verify

    claim = next(c for c in verify.CLAIMS if c.id == "def.param_total")
    drift = verify.DocDrift(
        claim=claim,
        doc="05-defines与修饰符.md",
        line=12,
        text="defines 共 3488 个参数条目",
        found=3488,
    )
    monkeypatch.setattr(verify, "unknown_doc_drift", lambda *_a, **_k: [drift])
    monkeypatch.setattr(verify, "run_claims", lambda *_a, **_k: [])
    monkeypatch.setattr(verify, "check_markers", lambda *_a, **_k: [])
    result = _run("verify", "--no-drift")
    assert result.exit_code == 0, result.output
    result = _run("verify")
    assert "MarkupError" not in result.output
    assert "脱节" in result.output, result.output
    assert drift.describe()[:12] in result.output


def test_verify_fix_claims_在一致时早退() -> None:
    """`--fix-claims` 照单全收实得值 —— 但「本来就一致」时不许动断言表。"""
    table = config.REPO / "tools" / "pdx" / "verify.py"
    before = table.read_text(encoding="utf-8")
    result = _run("verify", "--fix-claims")
    assert table.read_text(encoding="utf-8") == before, "一致时不该改断言表"
    if result.exit_code == 0:
        assert "无需改动" in result.output
    else:  # 本机没有游戏：_require_game 会以「跑不了」退出 2
        assert result.exit_code == 2, result.output


@_needs_game
def test_snapshot_diff_自己与自己无差异() -> None:
    """snapshot diff 收的是**快照名**（不含 .json），不是路径。

    只写了版本号时要能解析到**精简**快照 —— 入库的只有精简那份，
    「拿两个版本比结构」在别的机器上只可能拿到它。
    """
    snaps = sorted(config.OUT.joinpath("snapshots").glob("*.compact.json"))
    if not snaps:
        pytest.skip("没有精简快照")
    label = snaps[-1].name.removesuffix(".compact.json")
    result = _run("snapshot", "diff", label, label)
    assert result.exit_code == 0, result.output
    assert "无差异" in result.output or "完全一致" in result.output


@_needs_game
def test_snapshot_diff_域集合不同时会点明() -> None:
    """两份快照的域集合不同时，差异里混着**格式变化** —— 必须点明，不能静默。

    这不是假想：入库的 `release-1.14.3.compact.json` 是上一轮的域集合（6 个域），
    拿它比 1.14.4（14 个域）会报出百万级「删除」，而真正的原版变化只有几百处。
    """
    snaps = sorted(config.OUT.joinpath("snapshots").glob("*.compact.json"))
    if len(snaps) < 2:
        pytest.skip("少于两份精简快照，比不出「域集合不同」")
    older = snaps[0].name.removesuffix(".compact.json")
    newer = snaps[-1].name.removesuffix(".compact.json")
    result = _run("snapshot", "diff", older, newer)
    assert "MarkupError" not in result.output
    assert result.exit_code == 0, result.output
    if "域集合不同" in result.output:
        assert "可比的是两侧都有的域" in result.output


@_needs_game
def test_snapshot_verify_自检() -> None:
    result = _run("snapshot", "verify")
    assert result.exit_code == 0, result.output


@_needs_game
def test_snapshot_list_可读() -> None:
    result = _run("snapshot", "list")
    assert result.exit_code == 0
    assert ".json" in result.output


def test_ab_probe_写出盯的档案并支持显式指定(monkeypatch) -> None:
    """`v3 ab-probe` 必须**写出它盯的是哪一份档案**，并支持 `--archive` 指定。

    为什么值得一条测试：`ab_probe.load_target()` 的默认值是「数据源里按文件名排序的第一份」，
    而那个默认值**会随着新档案入库而变**（现在是 `au_revolution`，而入库的探针是
    `ru_defeat` 的）—— 不写出来的话，"这个探针在盯谁"就变成一件看不出来的错事（P13）。
    ⚠️ 这里把 `write` monkeypatch 掉：真跑会重写仓库里的探针目录。
    """
    from pdx import ab_probe

    written: list[str | None] = []
    monkeypatch.setattr(
        ab_probe, "write", lambda *, archive_id=None, **_kw: written.append(archive_id) or []
    )
    result = _run("ab-probe", "--archive", "ru_defeat")
    assert result.exit_code == 0, result.output
    assert "ru_defeat" in result.output
    assert written == ["ru_defeat"], written

    result = _run("ab-probe")
    assert result.exit_code == 0, result.output
    assert "按文件名排序的第一份" in result.output
    assert written[-1] is None, written
