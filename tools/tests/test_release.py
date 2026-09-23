"""发布流程的机械部分（`v3 release`）—— 阶段 7 的最后一件。

为什么值得单独一组用例
----------------------
它守的是**玩家唯一会读的那一份文档**。它原来只有一条人工纪律
（「`mod/data/<id>.toml` 的 id 必须出现在 changelog 条目里」），而
`01-大方向.md` §1 说过：**没有检查方式的原则不算原则**。这一组用例把那条纪律的
四个面各钉一条（版本 / 覆盖 / 幽灵 / 归档物），外加一条跑在**真实 CHANGELOG** 上的看守。

构造方式：不手搓 `modgen.Archive`（它有二十来个字段），而是拿**真实档案**当输入、
在 `tmp_path` 里写变体的 changelog —— 这样测的是检查逻辑本身，不是夹具。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pdx import modgen, release

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _archives() -> tuple[modgen.Archive, ...]:
    loaded = tuple(modgen.load_all())
    assert loaded, "一份档案都没有 —— 检查逻辑没得测"
    return loaded


def _changelog(tmp_path: Path, *, version: str = "0.1.0", drop: str = "", extra: str = "") -> Path:
    """按**真实档案**生成一份变体 changelog：`drop` 去掉一份，`extra` 追加一行。"""
    archives = _archives()
    entries = "\n".join(
        f"- `{archive.id}` — {archive.title}：一句话" for archive in archives if archive.id != drop
    )
    path = tmp_path / "CHANGELOG.md"
    path.write_text(
        f"# 发布说明\n\n## [{version}] - 2026-09-23\n\n### 处境档案\n\n{entries}\n{extra}\n",
        encoding="utf-8",
    )
    return path


class TestParsing:
    def test_版本标题按出现顺序(self) -> None:
        text = "## [0.2.0] - 2026-10-01\n…\n## [0.1.0] - 2026-09-23\n"
        assert release.parse_versions(text) == ("0.2.0", "0.1.0")

    def test_版本标题也认不带方括号的写法(self) -> None:
        assert release.parse_versions("## 0.1.0\n") == ("0.1.0",)

    def test_档案条目只认反引号加破折号那种(self) -> None:
        text = "- `ru_defeat` — 俄罗斯 · 战败求存：说明\n- 没有反引号的一行\n- `brz_market_loss`：冒号不算\n"
        assert release.parse_entries(text) == ("ru_defeat",)


class TestCheck:
    def test_三边一致时通过(self, tmp_path: Path) -> None:
        report = release.check(_changelog(tmp_path), archives=_archives())
        assert report.ok, report.problems
        assert report.missing == ()
        assert report.orphans == ()
        assert report.versions == ("0.1.0",)

    def test_版本对不上要报(self, tmp_path: Path) -> None:
        report = release.check(_changelog(tmp_path, version="0.2.0"), archives=_archives())
        assert not report.ok
        assert any("最新一节写的是 0.2.0" in item for item in report.problems)

    def test_少写一份档案要报(self, tmp_path: Path) -> None:
        report = release.check(_changelog(tmp_path, drop="brz_market_loss"), archives=_archives())
        assert not report.ok
        assert report.missing == ("brz_market_loss",)
        assert any("没有出现在发布说明里" in item for item in report.problems)

    def test_幽灵条目要报(self, tmp_path: Path) -> None:
        """删了档案却留着发布说明 = 说明在骗人。"""
        report = release.check(
            _changelog(tmp_path, extra="- `zz_gone_forever` — 幽灵：已经没有这份档案了"),
            archives=_archives(),
        )
        assert not report.ok
        assert report.orphans == ("zz_gone_forever",)

    def test_没有发布说明要报(self, tmp_path: Path) -> None:
        report = release.check(tmp_path / "不存在.md", archives=_archives())
        assert not report.ok
        assert report.missing  # 一份都没写进去
        assert any("没有发布说明" in item for item in report.problems)

    def test_没有版本标题要报(self, tmp_path: Path) -> None:
        path = tmp_path / "C.md"
        path.write_text("- `ru_defeat` — x：y\n", encoding="utf-8")
        report = release.check(path, archives=_archives())
        assert not report.ok
        assert any("没有任何版本标题" in item for item in report.problems)

    def test_档案声明的游戏版本不一致要报(self, tmp_path: Path) -> None:
        import dataclasses

        archives = list(_archives())
        archives[0] = dataclasses.replace(archives[0], game_version="1.15.3")
        report = release.check(_changelog(tmp_path), archives=archives)
        assert not report.ok
        assert any("game_version 不一致" in item for item in report.problems)

    def test_骨架只列缺的那些(self, tmp_path: Path) -> None:
        report = release.check(_changelog(tmp_path, drop="eg_debt"), archives=_archives())
        text = release.template(report, archives=_archives())
        assert "`eg_debt`" in text
        assert "埃及 · 债务危机" in text, "骨架要带上数据源里的标题，别让人再打一遍"
        assert text.count("\n") == 0, "只缺一份时不该多出行"

    def test_一份都不缺时不给骨架(self, tmp_path: Path) -> None:
        report = release.check(_changelog(tmp_path), archives=_archives())
        assert "都已经写进发布说明" in release.template(report, archives=_archives())


class TestDescribe:
    """`describe()` 是给人看的那一段 —— 有问题的那些分支也要走到（不然它只是摆设）。"""

    def test_有问题时逐条报出来(self, tmp_path: Path) -> None:
        import dataclasses

        archives = list(_archives())
        archives[0] = dataclasses.replace(archives[0], game_version="1.15.3")
        report = release.check(
            _changelog(tmp_path, drop="eg_debt", extra="- `zz_gone` — 幽灵：已经没有了"),
            archives=archives,
        )
        text = report.describe()
        assert "没写进发布说明" in text
        assert "eg_debt" in text
        assert "幽灵条目" in text
        assert "zz_gone" in text
        assert "各档案声明的游戏版本不一致" in text

    def test_一切正常时不出现那些警报行(self, tmp_path: Path) -> None:
        text = release.check(_changelog(tmp_path), archives=_archives()).describe()
        assert "没写进发布说明" not in text
        assert "幽灵条目" not in text
        assert "不一致" not in text

    def test_没有发布说明时的描述也不会炸(self, tmp_path: Path) -> None:
        report = release.check(tmp_path / "没有.md", archives=_archives())
        assert "（没有版本标题）" in report.describe()
        assert not report.ok


def test_真实发布说明通过检查() -> None:
    """**仓库里那一份**也要过 —— 不然这套检查只是自娱自乐。"""
    if not release.CHANGELOG.is_file():  # pragma: no cover
        pytest.skip("仓库里没有 CHANGELOG.md")
    report = release.check()
    assert report.ok, "真实 CHANGELOG.md 与档案/元数据对不上：\n  " + "\n  ".join(report.problems)
    assert report.missing == ()
    assert report.orphans == ()
    assert report.versions[0] == report.metadata_version
