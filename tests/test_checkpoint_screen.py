"""真实形状的小型存档反例：字节筛选不能产生正式或未决资格。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from pdx import checkpoint_catalog, checkpoint_screen, game_run
from pdx.engineering import require_skip_category

pytestmark = pytest.mark.unit

# 对应已核对 SAV0100 原件：直属 definition/budget、country_records 匿名块数组。
SAVE = b"""SAV0100ac5d6c1a00000321
meta_data={save_game_version=1790665805 version="1.14.5" game_date=1836.2.1}
player_manager={database={}}
country_manager={database={
0=none
1={definition="GBR" ruler=3854 budget={
    weekly_income={0 20 30}
    money=50 credit=200 principal=100 balance_trend={current=-5}
}}
2={definition="FRA" government="gov_monarchy" budget={
    money=30 credit=300 principal=200 balance_trend={current=-10}
}}
}}
diplomatic_plays={database={
0={initiator=1 target=2 type=dp_revolution
   country_records={ {country=1 side=initiator} {country=2 side=target} }
   key="first_carlist_war" war=0 escalation=100 start_date=1836.1.1 end_date=1.1.1}
}}
"""


@pytest.fixture
def original(tmp_path):
    path = tmp_path / "original.v3"
    path.write_bytes(SAVE)
    return path


def screen(path, *, reports=()):
    return checkpoint_screen.screen(
        [(path, hashlib.sha256(path.read_bytes()).hexdigest())],
        expected_version="1.14.5",
        origin_report_paths=reports,
    )["entries"][0]


def preparation(tmp_path, raw=SAVE):
    """用原版准备真实来源合同与日志让既有审查器独立复核。"""
    root = tmp_path / "preparation"
    path = root / "saves" / "checkpoint.v3"
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    logs = root / "logs"
    logs.mkdir()
    (logs / "debug.log").write_bytes(b"Mounted Data: base\n")
    (logs / "error.log").write_bytes(b"")
    report = {
        "kind": "vanilla_checkpoint_preparation",
        "ok": True,
        "content_load": "vanilla_only",
        "session_requested": True,
        "logs_isolated": True,
        "cleanup_errors": [],
        "source_hashes": {},
        "deployed_hashes": {},
        "game_version": {"caligula_branch": "release/1.14.5"},
        "mount_allowlist": ["base"],
        "log_hashes": game_run.hashes(logs),
        "checkpoint": {
            "header": game_run.save_header(path),
            "hashes": {path.name: game_run.file_sha(path)},
        },
    }
    report_path = root / "report.json"
    game_run.write_json(report_path, report)
    return path, report_path


def test_财政排序保持引擎与正式资格未知(original):
    result = screen(original)
    assert result["source_allowed"] is False
    assert result["inspection"]["instrument_suitable"] is True
    assert result["formal_pair_suitable"] is False
    assert result["opportunity_count"] is None
    assert result["state"] == "no-supported-nomination"
    countries = result["countries"]
    assert [row["id"] for row in countries] == ["0", "1", "2"]
    assert countries[0]["fiscal_state"] == "tombstone"
    assert countries[1]["screen_remaining_credit_weeks"] == 20
    assert countries[2]["screen_remaining_credit_weeks"] == 10
    start, end = countries[1]["budget_span"]
    assert original.read_bytes()[start:end].startswith(b"{")
    assert result["diplomatic_plays"][0]["phase"] == "war"
    assert not result["nominations"]
    assert not result["risk_nominations"]


def test_真实来源合同只允许财政提名不允许联合实机提名(tmp_path):
    path, report = preparation(tmp_path)
    initial = path.read_bytes(), report.read_bytes()
    result = screen(path)
    assert result["source_allowed"] is True
    assert result["risk_screen_state"] == "risk-screen-only"
    assert result["risk_nominations"] == ["2", "1"]
    assert result["nominations"] == []
    assert result["state"] == "no-supported-nomination"
    assert result["formal_pair_suitable"] is False
    assert (path.read_bytes(), report.read_bytes()) == initial


@pytest.mark.parametrize(
    "replacement", [b"war=none escalation=30", b"escalation=30", b"war=4294967295 escalation=30"]
)
def test_未核实非战形状不能推导未决支持(tmp_path, replacement):
    path, _ = preparation(tmp_path, SAVE.replace(b"war=0 escalation=100", replacement))
    result = screen(path)
    assert result["diplomatic_plays"][0]["phase"] == "unknown"
    assert not result["nominations"]
    assert result["risk_nominations"] == ["2", "1"]
    assert result["formal_pair_suitable"] is False


def test_注释引号伪同名及邻国不误配(original):
    raw = SAVE.replace(
        b'1={definition="GBR"',
        b'1={note="} budget={money=9 credit=9 principal=0}" # definition="BAD" }\n definition="GBR"',
    ).replace(b"money=50 credit=200 principal=100", b"money=50 credit=200")
    raw = raw.replace(
        b"country_manager={",
        b'fake={country_manager={database={1={definition="BAD"}}}}\ncountry_manager={',
    )
    original.write_bytes(raw)
    result = screen(original)
    gbr, fra = result["countries"][1:]
    assert gbr["tag"] == "GBR"
    assert fra["tag"] == "FRA"
    assert gbr["values"]["principal"] is None
    assert gbr["fiscal_state"] == "unknown"
    assert fra["values"]["principal"] == 200


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        (b"principal=100", b"principal=100 principal=0", "field.principal.duplicate"),
        (b"credit=200", b"credit=yes", "field.credit.invalid_number"),
        (b"credit=200", b"credit=-200", "field.credit.invalid_number"),
        (b"principal=100", b"principal=NaN", "field.principal.invalid_number"),
        (b"money=50", b"money=Infinity", "field.money.invalid_number"),
        (b"money=50", b"money=1e999", "field.money.invalid_number"),
        (b"current=-5", b'current="-5"', "field.current.invalid_number"),
        (b"current=-5", b"current=-5 current=0", "field.current.duplicate"),
        (b"principal=100", b"principal=-100", "field.principal.invalid_number"),
        (b"current=-5", b"current=\xff", "utf-8"),
    ],
)
def test_缺项重复和非法数值保留未知(original, old, new, reason):
    original.write_bytes(SAVE.replace(old, new))
    row = screen(original)["countries"][1]
    assert row["fiscal_state"] == "unknown"
    assert row["screen_remaining_credit_weeks"] is None
    assert any(reason in item for item in row["reasons"])


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (b"2={definition", b"1={definition"),
        (b'definition="FRA"', b'definition="GBR"'),
        (b'definition="GBR"', b'definition="GBR" definition="GER"'),
    ],
)
def test_重复身份不能last_wins(original, old, new):
    original.write_bytes(SAVE.replace(old, new))
    result = screen(original)
    assert any(row["fiscal_state"] == "unknown" for row in result["countries"])
    assert not result["risk_nominations"]


@pytest.mark.parametrize(
    "raw",
    [b"", b"ZIPinvalid", SAVE[:-3], SAVE + b"}", SAVE.replace(b"money=50", b'money="unterminated')],
)
def test_空容器截断和未闭合不得当partial真值(original, raw):
    original.write_bytes(raw)
    result = screen(original)
    assert result["unknown_reasons"]
    assert result["state"] == "no-supported-nomination"
    assert not result["risk_nominations"]


def test_预算超窗保留偏移而不解析截断(original):
    original.write_bytes(SAVE.replace(b"weekly_income={0 20 30}", b"#" + b"x" * 16384 + b"\n"))
    result = screen(original)
    row = result["countries"][1]
    assert row["budget_span"][1] - row["budget_span"][0] > 16384
    assert "field.budget.byte_limit" in row["reasons"]
    assert row["values"] == {}
    assert result["countries"][2]["screen_remaining_credit_weeks"] == 10


def test_外交超窗不截断为已知表(original):
    original.write_bytes(
        SAVE.replace(
            b"diplomatic_plays={database={",
            b"diplomatic_plays={database={#" + b"x" * 262144 + b"\n",
        )
    )
    result = screen(original)
    assert result["diplomatic_plays"] == []
    assert "field.database.byte_limit" in result["unknown_reasons"]


def test_结构化头绑定排除regex诱饵(original):
    original.write_bytes(
        SAVE.replace(
            b"player_manager={database={}}",
            b'note="player_manager={database={}}"\nplayer_manager={database={1={country=1}}}',
        )
    )
    result = screen(original)
    assert "header.not_observer" in result["unknown_reasons"]
    assert not result["risk_nominations"]


def test_完整散列和读取变化拒绝(original, monkeypatch):
    result = checkpoint_screen.screen([(original, "a" * 64)], expected_version="1.14.5")["entries"][
        0
    ]
    assert "input.sha256_mismatch" in result["unknown_reasons"]
    original_digest = checkpoint_screen.digest
    calls = 0

    def changed(path):
        nonlocal calls
        if path == original:
            calls += 1
            if calls == 2:
                original.write_bytes(SAVE + b"# changed\n")
        return original_digest(path)

    monkeypatch.setattr(checkpoint_screen, "digest", changed)
    result = screen(original)
    assert "input.changed_during_read" in result["unknown_reasons"]
    assert not result["risk_nominations"]


def test_链接拒绝(original, tmp_path):
    link = tmp_path / "linked.v3"
    try:
        link.symlink_to(original)
    except OSError:
        if sys.platform != "win32":
            raise
        reason = "Windows 符号链接权限不足"
        assert require_skip_category(reason) == "platform"
        pytest.skip(reason)
    result = screen(link)
    assert not result["source_allowed"]
    assert any("链接" in reason for reason in result["unknown_reasons"])


def test_失败来源复制改名仍拒绝(tmp_path):
    path, report = preparation(tmp_path)
    (report.parent / "logs" / "error.log").write_bytes(b"Assertion failed: dirty\n")
    copy = tmp_path / "renamed.v3"
    shutil.copyfile(path, copy)
    result = screen(copy, reports=[report])
    assert result["inspection"]["instrument_suitable"] is False
    assert result["source_allowed"] is False
    assert result["origin_reports"][0]["clean"] is False
    assert not result["risk_nominations"]


def test_损坏来源和未知来源不等于无注入(tmp_path):
    path, report = preparation(tmp_path)
    raw = json.loads(report.read_bytes())
    raw["source_hashes"] = {"fiscal": {"injection.txt": "a" * 64}}
    game_run.write_json(report, raw)
    result = screen(path)
    assert result["source_allowed"] is False
    assert not result["risk_nominations"]


def test_数量上限输入和全球提名(tmp_path):
    # 每个小型国家独立 literal shape；不借用实现生成预期。
    records = b"\n".join(
        f'{n}={{definition="C{n}" budget={{money=5 credit=100 principal=90 balance_trend={{current=-2}}}}}}'.encode()
        for n in range(1, 10)
    )
    raw = (
        SAVE[: SAVE.index(b"country_manager=")]
        + b"country_manager={database={"
        + records
        + b"}}\ndiplomatic_plays={database={}}\n"
    )
    left, _ = preparation(tmp_path, raw)
    right_root = tmp_path / "right"
    right_root.mkdir()
    right, _ = preparation(right_root, raw)
    result = checkpoint_screen.screen(
        [(path, game_run.file_sha(path)) for path in (left, right)], expected_version="1.14.5"
    )
    assert sum(len(entry["risk_nominations"]) for entry in result["entries"]) == 8
    assert all(len(entry["countries"]) == 9 for entry in result["entries"])
    assert not any(entry["nominations"] for entry in result["entries"])
    with pytest.raises(ValueError, match="一至两"):
        checkpoint_screen.screen([(left, game_run.file_sha(left))] * 3, expected_version="1.14.5")
    with pytest.raises(ValueError, match="完整"):
        checkpoint_screen.screen([(left, "123")], expected_version="1.14.5")


def test_国家超过1024保留未知而不静默采样(original):
    records = b"\n".join(f"{n}=none".encode() for n in range(1025))
    original.write_bytes(
        SAVE[: SAVE.index(b"country_manager=")]
        + b"country_manager={database={"
        + records
        + b"}}\ndiplomatic_plays={database={}}\n"
    )
    result = screen(original)
    assert len(result["countries"]) == 1024
    assert "country.record_limit" in result["unknown_reasons"]
    assert not result["risk_nominations"]


def test_确定性阈值复用和无默认扫描(original, monkeypatch):
    monkeypatch.setattr(Path, "rglob", lambda *_args: pytest.fail("筛选不能递归扫描"))
    first = checkpoint_screen.screen(
        [(original, game_run.file_sha(original))], expected_version="1.14.5"
    )
    second = checkpoint_screen.screen(
        [(original, game_run.file_sha(original))], expected_version="1.14.5"
    )
    assert first == second
    assert first["thresholds"] == {"entry_weeks": 26, "exit_weeks": 52}


def test_CLI筛选模式兼容默认目录模式(original, tmp_path, monkeypatch):
    monkeypatch.setattr("pdx.save_migration.current_game_version", lambda: "1.14.5")
    output = tmp_path / "screen.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "checkpoint_catalog",
            "--screen-save",
            str(original),
            "--expected-sha256",
            game_run.file_sha(original),
            "--output",
            str(output),
        ],
    )
    assert checkpoint_catalog.main() == 0
    assert json.loads(output.read_bytes())["mode"] == "bounded-checkpoint-screen"
    monkeypatch.setattr(sys, "argv", ["checkpoint_catalog", str(tmp_path), "--output", str(output)])
    assert checkpoint_catalog.main() == 0
    assert "mode" not in json.loads(output.read_bytes())
    monkeypatch.setattr(sys, "argv", ["checkpoint_catalog", "--output", str(output)])
    with pytest.raises(SystemExit):
        checkpoint_catalog.main()


def test_预算恰好16KiB仍完整读取(original):
    start = SAVE.index(b"budget={") + len(b"budget=")
    end = SAVE.index(b"\n}}", start) + 2
    budget = SAVE[start:end]
    padding = b"#" + b"x" * (16384 - len(budget) - 2) + b"\n"
    raw = SAVE[: start + 1] + padding + SAVE[start + 1 :]
    original.write_bytes(raw)
    row = screen(original)["countries"][1]
    assert row["budget_span"][1] - row["budget_span"][0] == 16384
    assert row["screen_remaining_credit_weeks"] == 20


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        (b"credit=200", b"credit=200 credit=201", "field.credit.duplicate"),
        (
            b"balance_trend={current=-5}",
            b"balance_trend={current=-5} balance_trend={current=-4}",
            "field.balance_trend.duplicate",
        ),
        (b'definition="GBR"', b'definition="G\xffR"', "utf-8"),
        (b"principal=100", b"principal=yes", "field.principal.invalid_number"),
    ],
)
def test_财政字段边界保持未知(original, old, new, reason):
    original.write_bytes(SAVE.replace(old, new))
    row = screen(original)["countries"][1]
    assert row["fiscal_state"] == "unknown"
    assert any(reason in item for item in row["reasons"])


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        (b"war=0", b"war=0 war=1", "field.war.duplicate"),
        (b"escalation=100", b"escalation=NaN", "field.escalation.invalid_number"),
        (b"country=2 side=target", b"country=1 side=target", "diplomacy.duplicate_country"),
        (b"country=2 side=target", b"country=2 side=unverified", "diplomacy.sides_missing"),
    ],
)
def test_外交字段未知保存其余原始读数(original, old, new, reason):
    original.write_bytes(SAVE.replace(old, new))
    play = screen(original)["diplomatic_plays"][0]
    assert play["phase"] == "unknown"
    assert reason in play["reasons"]
    assert play["initiator"] == "1"
    assert play["target"] == "2"
    assert len(play["country_records"]) == 2
    assert play["span"][1] > play["span"][0]


def test_缺失外交表与空表明确区别(original):
    original.write_bytes(SAVE[: SAVE.index(b"diplomatic_plays=")])
    result = screen(original)
    assert "field.diplomatic_plays.missing" in result["unknown_reasons"]
    original.write_bytes(
        SAVE[: SAVE.index(b"diplomatic_plays=")] + b"diplomatic_plays={database={}}\n"
    )
    result = screen(original)
    assert result["diplomatic_plays"] == []
    assert "field.diplomatic_plays.missing" not in result["unknown_reasons"]
    assert result["sha256_after"] == result["sha256"]


def test_容器异常仍完成后完整SHA检查(original):
    original.write_bytes(SAVE + b"}")
    result = screen(original)
    assert result["unknown_reasons"]
    assert result["sha256_after"] == result["sha256"]
    assert result["identity_before"] == result["identity_after"]


def test_正式头字段重复不取最后值(original):
    original.write_bytes(SAVE.replace(b'version="1.14.5"', b'version="1.14.5" version="1.14.5"'))
    result = screen(original)
    assert "field.version.duplicate" in result["unknown_reasons"]
    assert not result["risk_nominations"]


def test_较差代理不能挤掉另一原件更近的财政候选(tmp_path):
    left, _ = preparation(tmp_path)
    root = tmp_path / "right"
    root.mkdir()
    right, _ = preparation(
        root, SAVE.replace(b"credit=200 principal=100", b"credit=101 principal=100")
    )
    result = checkpoint_screen.screen(
        [(left, game_run.file_sha(left)), (right, game_run.file_sha(right))],
        expected_version="1.14.5",
    )
    assert result["entries"][1]["risk_nominations"][0] == "1"


def test_CLI拒绝覆写原件或来源报告(tmp_path, monkeypatch):
    path, report = preparation(tmp_path)
    monkeypatch.setattr("pdx.save_migration.current_game_version", lambda: "1.14.5")
    initial = path.read_bytes(), report.read_bytes()
    for output in (path, report):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "checkpoint_catalog",
                "--screen-save",
                str(path),
                "--expected-sha256",
                game_run.file_sha(path),
                "--output",
                str(output),
            ],
        )
        with pytest.raises(SystemExit):
            checkpoint_catalog.main()
    assert (path.read_bytes(), report.read_bytes()) == initial


def test_CLI不接受缺少SHA或混合递归root(original, tmp_path, monkeypatch):
    monkeypatch.setattr("pdx.save_migration.current_game_version", lambda: "1.14.5")
    for args in (
        ["--screen-save", str(original)],
        [
            str(tmp_path),
            "--screen-save",
            str(original),
            "--expected-sha256",
            game_run.file_sha(original),
        ],
    ):
        monkeypatch.setattr(
            sys, "argv", ["checkpoint_catalog", *args, "--output", str(tmp_path / "screen.json")]
        )
        with pytest.raises(SystemExit):
            checkpoint_catalog.main()


@pytest.mark.parametrize(
    "member",
    [
        Path("logs") / "error.log",
        Path("sources") / "observer.txt",
        Path("deployment") / "manifest.json",
        Path("state-backups") / "ledger.json",
    ],
)
def test_CLI保护显式来源证据根成员(tmp_path, monkeypatch, member):
    path, report = preparation(tmp_path)
    external = tmp_path / "external.v3"
    shutil.copyfile(path, external)
    target = report.parent / member
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"frozen evidence\n")
    original = {
        str(p.relative_to(report.parent)): p.read_bytes()
        for p in report.parent.rglob("*")
        if p.is_file()
    }
    monkeypatch.setattr("pdx.save_migration.current_game_version", lambda: "1.14.5")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "checkpoint_catalog",
            "--screen-save",
            str(external),
            "--expected-sha256",
            game_run.file_sha(path),
            "--origin-report",
            str(report),
            "--output",
            str(target),
        ],
    )
    with pytest.raises(SystemExit):
        checkpoint_catalog.main()
    assert {
        str(p.relative_to(report.parent)): p.read_bytes()
        for p in report.parent.rglob("*")
        if p.is_file()
    } == original


@pytest.mark.parametrize(
    "member",
    [
        Path("logs") / "error.log",
        Path("sources") / "observer.txt",
        Path("deployment") / "manifest.json",
        Path("state-backups") / "ledger.json",
    ],
)
def test_CLI保护自动发现来源证据根成员(tmp_path, monkeypatch, member):
    path, report = preparation(tmp_path)
    target = report.parent / member
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"frozen evidence\n")
    original = {
        str(p.relative_to(report.parent)): p.read_bytes()
        for p in report.parent.rglob("*")
        if p.is_file()
    }
    monkeypatch.setattr("pdx.save_migration.current_game_version", lambda: "1.14.5")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "checkpoint_catalog",
            "--screen-save",
            str(path),
            "--expected-sha256",
            game_run.file_sha(path),
            "--output",
            str(target),
        ],
    )
    with pytest.raises(SystemExit):
        checkpoint_catalog.main()
    assert {
        str(p.relative_to(report.parent)): p.read_bytes()
        for p in report.parent.rglob("*")
        if p.is_file()
    } == original


def test_CLI允许来源根旁邻输出且报告保持不变(tmp_path, monkeypatch):
    path, report = preparation(tmp_path)
    output = tmp_path / "screen.json"
    report_before = report.read_bytes()
    monkeypatch.setattr("pdx.save_migration.current_game_version", lambda: "1.14.5")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "checkpoint_catalog",
            "--screen-save",
            str(path),
            "--expected-sha256",
            game_run.file_sha(path),
            "--origin-report",
            str(report),
            "--output",
            str(output),
        ],
    )
    assert checkpoint_catalog.main() == 0
    assert output.exists()
    assert report.read_bytes() == report_before


@pytest.mark.parametrize("path_style", ["relative", "absolute"])
def test_CLI相对绝对路径仍保护来源根(tmp_path, monkeypatch, path_style):
    path, report = preparation(tmp_path)
    # GitHub Windows runner 的仓库和 pytest 临时目录可能位于不同盘符；
    # 在证据根内生成相对参数，仍测试 CLI 的相对路径合同。
    monkeypatch.chdir(tmp_path)
    target = report.parent / "logs" / "error.log"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"frozen evidence\n")
    original = target.read_bytes()
    monkeypatch.setattr("pdx.save_migration.current_game_version", lambda: "1.14.5")

    def argument(value):
        return os.path.relpath(value, Path.cwd()) if path_style == "relative" else str(value)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "checkpoint_catalog",
            "--screen-save",
            argument(path),
            "--expected-sha256",
            game_run.file_sha(path),
            "--origin-report",
            argument(report),
            "--output",
            argument(target),
        ],
    )
    with pytest.raises(SystemExit):
        checkpoint_catalog.main()
    assert target.read_bytes() == original


def test_CLIWindows大小写别名仍保护来源根(tmp_path, monkeypatch):
    if sys.platform != "win32":
        pytest.skip("Windows 大小写路径合同")
    path, report = preparation(tmp_path)
    target = report.parent / "logs" / "error.log"
    original = target.read_bytes(), report.read_bytes()
    monkeypatch.setattr("pdx.save_migration.current_game_version", lambda: "1.14.5")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "checkpoint_catalog",
            "--screen-save",
            str(path),
            "--expected-sha256",
            game_run.file_sha(path),
            "--origin-report",
            str(report),
            "--output",
            str(target).upper(),
        ],
    )
    with pytest.raises(SystemExit):
        checkpoint_catalog.main()
    assert (target.read_bytes(), report.read_bytes()) == original


def test_CLI输出重解析点遵守已有plain_path合同(original, tmp_path, monkeypatch):
    output = tmp_path / "alias" / "screen.json"
    target = output.parent
    target.mkdir()
    # Windows junction/symlink 的安全拒绝由既有 plain_path 负责；此处提供其实际 tag。
    lstat = Path.lstat
    from types import SimpleNamespace

    def reparse_info(path):
        if path == target:
            return SimpleNamespace(st_reparse_tag=0xA0000003)
        return lstat(path)

    monkeypatch.setattr(Path, "lstat", reparse_info)
    monkeypatch.setattr(Path, "is_symlink", lambda _path: False)
    monkeypatch.setattr("pdx.save_migration.current_game_version", lambda: "1.14.5")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "checkpoint_catalog",
            "--screen-save",
            str(original),
            "--expected-sha256",
            game_run.file_sha(original),
            "--output",
            str(output),
        ],
    )
    with pytest.raises(SystemExit):
        checkpoint_catalog.main()
    assert not output.exists()


@pytest.mark.parametrize("second_id", [b"0", b"00"])
def test_外交对象数值身份重复不得用前导零绕过(original, second_id):
    start = SAVE.index(b"0={initiator=")
    end = SAVE.index(b"\n}}", start)
    play = SAVE[start:end]
    original.write_bytes(SAVE[:end] + b"\n" + second_id + play[1:] + SAVE[end:])
    result = screen(original)
    assert [row["id"] for row in result["diplomatic_plays"]] == ["0", second_id.decode()]
    assert all(row["phase"] == "unknown" for row in result["diplomatic_plays"])
    assert all("diplomacy.duplicate_id" in row["reasons"] for row in result["diplomatic_plays"])
    assert all(row["initiator"] == "1" for row in result["diplomatic_plays"])
    assert all(len(row["country_records"]) == 2 for row in result["diplomatic_plays"])
    assert "diplomacy.fields_unknown" in result["unknown_reasons"]
    assert not result["nominations"]


def test_国家引用数值别名重复保留原值并未知(original):
    original.write_bytes(SAVE.replace(b"{country=2 side=target}", b"{country=01 side=target}"))
    play = screen(original)["diplomatic_plays"][0]
    assert play["phase"] == "unknown"
    assert [row["country"] for row in play["country_records"]] == ["1", "01"]
    assert "diplomacy.country_record_invalid" in play["reasons"]
    assert "diplomacy.duplicate_country" in play["reasons"]


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        (b"initiator=1", b"initiator=01", "diplomacy.invalid_country_id"),
        (b"target=2", b"target=02", "diplomacy.invalid_country_id"),
        (b"war=0", b"war=00", "diplomacy.phase_unverified"),
        (b"0={initiator=", "٠={initiator=".encode(), "diplomacy.invalid_id"),
        (
            b"country=2 side=target",
            "country=٢ side=target".encode(),
            "diplomacy.country_record_invalid",
        ),
    ],
)
def test_外交身份只接受ASCII规范整数(original, old, new, reason):
    original.write_bytes(SAVE.replace(old, new))
    play = screen(original)["diplomatic_plays"][0]
    assert play["phase"] == "unknown"
    assert reason in play["reasons"]
    assert len(play["country_records"]) == 2
