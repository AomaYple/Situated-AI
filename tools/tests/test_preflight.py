"""开局前置条件自检的测试（`pdx.preflight`）。

这一组里**有一条是从真实事故里长出来的**（`test_探针态绝不能报成通过`）：
2026-09-24 一次会话被中途强杀，`finally` 没跑，用户的 23 条 Workshop 配置留在
"只剩探针"的状态里；而当时的自检只看 ``.v3probe-backup`` 这一个后缀，
备份文件却叫 ``.sitai-backup``（更早一轮的命名）⇒ 它报了 ✅。
教训写进代码了：**判据要盯状态本身（列表内容），不能只盯"有没有留下痕迹"**。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from pdx import preflight

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _write_config(path: Path, mods: list[str]) -> None:
    path.write_text(
        json.dumps({"enabledMods": [{"path": m} for m in mods]}, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )


@pytest.fixture
def userdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 `content_load.json` 与备份的落点指到临时目录（不碰用户的真配置）。"""
    from pdx import experiments

    target = tmp_path / "content_load.json"
    monkeypatch.setattr(experiments, "CONTENT_LOAD", target)
    return target


class TestUserConfig:
    def test_正常配置通过(self, userdir: Path) -> None:
        _write_config(userdir, [f"C:/w/{n}" for n in range(23)])
        check = preflight.check_user_config()
        assert check.ok, check.describe()
        assert "23 个 mod" in check.detail

    def test_探针态绝不能报成通过(self, userdir: Path) -> None:
        """**回归**：探针态 + 备份叫别的名字时，也必须报出来。

        旧版只看 `content_load.json.v3probe-backup`，而事故里那份备份叫
        `.sitai-backup` ⇒ 检查报了 ✅「启用 2 个 mod，无残留备份」。
        """
        _write_config(userdir, ["C:/w/sitai-all", "C:/w/zz_probe_ab"])
        backup = userdir.with_name(userdir.name + ".sitai-backup")
        _write_config(backup, [f"C:/w/{n}" for n in range(23)])
        check = preflight.check_user_config()
        assert not check.ok, check.describe()
        assert "探针态" in check.detail
        assert check.level == preflight.WRONG
        assert backup.name in check.fix, "要指出拿哪份备份还原"

    def test_探针态但一个备份都没有时要人先查清(self, userdir: Path) -> None:
        _write_config(userdir, ["C:/w/zz_probe_ab"])
        check = preflight.check_user_config()
        assert not check.ok
        assert "没找到备份文件" in check.detail
        assert "v3 mods" in check.fix

    def test_配置太短也不像用户那套(self, userdir: Path) -> None:
        _write_config(userdir, ["C:/w/only-one"])
        check = preflight.check_user_config()
        assert not check.ok
        assert "只启用了 1 个 mod" in check.detail

    def test_配置正常但旁边留着旧备份只是提示(self, userdir: Path) -> None:
        """备份文件本身无害 —— 而且它往往正是用户原列表的唯一副本，不该拦路。"""
        _write_config(userdir, [f"C:/w/{n}" for n in range(23)])
        _write_config(userdir.with_name(userdir.name + ".sitai-backup"), ["C:/w/a"])
        check = preflight.check_user_config()
        assert not check.ok
        assert check.level == preflight.INFO
        assert "留着备份" in check.detail

    def test_没有配置文件是跑不了(self, userdir: Path) -> None:
        check = preflight.check_user_config()
        assert not check.ok
        assert check.level == preflight.BLOCKING


class TestProbeStateRecovery:
    def test_探针态时给出该还原的那份备份(self, userdir: Path) -> None:
        _write_config(userdir, ["C:/w/zz_probe_ab"])
        backup = userdir.with_name(userdir.name + ".sitai-backup")
        _write_config(backup, ["C:/w/real"])
        assert preflight.probe_state_backup() == backup

    def test_正常态不给备份(self, userdir: Path) -> None:
        _write_config(userdir, [f"C:/w/{n}" for n in range(23)])
        _write_config(userdir.with_name(userdir.name + ".sitai-backup"), ["C:/w/a"])
        assert preflight.probe_state_backup() is None

    def test_探针态但没备份时给None(self, userdir: Path) -> None:
        """**没有备份就不许自动"修"** —— 那会把用户配置写成空的。"""
        _write_config(userdir, ["C:/w/zz_probe_ab"])
        assert preflight.probe_state_backup() is None


class TestArchive:
    def test_真实档案都有国家与两条读数(self) -> None:
        check = preflight.check_archive("tr_defeat")
        assert check.ok, check.describe()

    def test_不存在的档案报出可选项(self) -> None:
        check = preflight.check_archive("no_such_archive")
        assert not check.ok
        assert check.level == preflight.BLOCKING
        assert "tr_defeat" in check.fix


class TestReport:
    def _report(self, *checks: preflight.Check) -> preflight.Report:
        return preflight.Report(list(checks))

    def test_全通过时退出码0(self) -> None:
        report = self._report(preflight.Check("a", True, "ok"))
        assert report.ok
        assert report.exit_code() == 0

    def test_提示不拦路(self) -> None:
        report = self._report(
            preflight.Check("a", True, "ok"),
            preflight.Check("b", False, "旧日志", level=preflight.INFO),
        )
        assert report.exit_code() == 0
        assert [c.name for c in report.notes] == ["b"]

    def test_该修的问题是1(self) -> None:
        report = self._report(preflight.Check("a", False, "产物被手改"))
        assert report.exit_code() == 1
        assert [c.name for c in report.wrong] == ["a"]

    def test_缺前置条件是2而不是1(self) -> None:
        """口径：2 = 这台机器现在跑不了（与其余命令一致）。"""
        report = self._report(
            preflight.Check("a", False, "没游戏", level=preflight.BLOCKING),
            preflight.Check("b", False, "产物被手改"),
        )
        assert report.exit_code() == 2

    def test_描述里提示用警示符不用红叉(self) -> None:
        """⚠️ = 提示（不拦路），❌ = 真的该修 —— 用红叉报提示会让人以为开局被挡住了。"""
        note = preflight.Check("b", False, "旧日志", fix="加 --fresh-logs", level=preflight.INFO)
        assert note.describe().startswith("⚠️")
        assert "→ 加 --fresh-logs" in note.describe()
        assert preflight.Check("c", False, "产物被手改").describe().startswith("❌")
        assert preflight.Check("a", True, "ok").describe().startswith("✅")

    def test_报告行里把两类不满足分开说(self) -> None:
        report = self._report(
            preflight.Check("a", False, "没游戏", level=preflight.BLOCKING),
            preflight.Check("b", False, "旧日志", level=preflight.INFO),
        )
        text = "\n".join(report.lines())
        assert "1 条不满足" in text
        assert "另有 1 条提示" in text


class TestRealEnvironment:
    """在**本机真实环境**上跑一遍（有游戏时）：结论必须是"能开局"或"提示"。

    这条不是"环境检查"而是**自检自己的回归网**：`run()` 里任何一条检查写崩了
    （路径拼错、API 改名）都会在这里红，而不会等到开局前才发现。
    """

    def test_run_不抛异常且结论可用(self) -> None:
        report = preflight.run()
        assert report.checks, "自检至少要给出几条结论"
        assert report.exit_code() in {0, 1, 2}
        for check in report.checks:
            assert check.name
            assert check.detail
            if not check.ok:
                assert check.fix, f"{check.name} 不通过却没说怎么修"


class TestEnvironmentFailures:
    """把各条检查的**失败分支**逐个演一遍（这些分支平时跑不到，而正是它们值钱）。"""

    def test_没有游戏是跑不了(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(preflight.config, "GAME", tmp_path / "无")
        check = preflight.check_game()
        assert not check.ok
        assert check.level == preflight.BLOCKING
        assert "V3_ROOT" in check.fix or "v3 doctor" in check.fix

    def test_版本不一致要说清怎么修(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(preflight, "_game_version", lambda: "1.15.0")
        monkeypatch.setattr(
            preflight, "_mod_metadata", lambda: {"supported_game_version": "1.14.4"}
        )
        check = preflight.check_version_matches_mod()
        assert not check.ok
        assert "1.15.0" in check.detail
        assert "modgen --write" in check.fix

    def test_产物被手改要报出来(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """**不碰真产物**：把 `modgen.check` 换成"报一处不一致"。"""
        monkeypatch.setattr(preflight.modgen, "check", lambda _built: ["mod/x.txt 与数据源不一致"])
        check = preflight.check_products()
        assert not check.ok
        assert "1 处不一致" in check.detail
        assert "modgen --write" in check.fix

    def test_数据源坏了是跑不了(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom() -> list[object]:
            raise ValueError("坏 TOML")

        monkeypatch.setattr(preflight.modgen, "load_all", boom)
        check = preflight.check_products()
        assert not check.ok
        assert check.level == preflight.BLOCKING
        assert "坏 TOML" in check.detail

    def test_有残留进程要人先关游戏(self) -> None:
        check = preflight.check_no_leftover_game([4242])
        assert not check.ok
        assert "4242" in check.detail
        assert "存档会丢" in check.fix

    def test_日志里有上一局自报时给提示而不是拦路(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pdx import game_auto

        (tmp_path / "debug.log").write_text("zz ZZPROBE AB;ROLE;RUS\n", encoding="utf-8")
        monkeypatch.setattr(game_auto, "DEBUG_LOG", tmp_path / "debug.log")
        check = preflight.check_logs_fresh()
        assert not check.ok
        assert check.level == preflight.INFO
        assert "1 行上一局" in check.detail
        assert "--fresh-logs" in check.fix

    def test_盘上探针盯错国家时给提示(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pdx import ab_probe

        root = tmp_path / "zz_probe_ab"
        (root / "common" / "on_actions").mkdir(parents=True)
        (root / "common" / "on_actions" / "zz_probe_ab_on_actions.txt").write_text(
            "c:RUS ?= this\n", encoding="utf-8"
        )
        monkeypatch.setattr(ab_probe, "PROBE_DIR", root)
        check = preflight.check_probe("tr_defeat")
        assert not check.ok
        assert check.level == preflight.INFO
        assert "c:TUR" in check.detail
        assert "ab-probe --archive tr_defeat" in check.fix

    def test_探针目录不在时给提示(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from pdx import ab_probe

        monkeypatch.setattr(ab_probe, "PROBE_DIR", tmp_path / "无")
        check = preflight.check_probe("tr_defeat")
        assert not check.ok
        assert check.level == preflight.INFO

    def test_没声明探针读数的档案要说清哪一格不判(self) -> None:
        """空 `[probe]` 字段是**合法**的，但要知道那一格不会被判 —— 所以要带条件地报"可跑"。"""
        check = preflight.check_archive("brz_market_loss")
        assert not check.ok
        assert "reform_card" in check.detail, "巴西留空的正是牌那一格，必须点出来"
        assert "modgen --write" in check.fix

    def test_不用探针时不查探针(self) -> None:
        check = preflight.check_probe(None)
        assert check.ok
        assert check.level == preflight.INFO
