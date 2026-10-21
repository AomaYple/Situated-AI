"""检查原版文件引用的提取、解析、路径唯一性与行号边界。"""

from __future__ import annotations

from pathlib import Path

import pytest

from pdx import citations


def test_可脚本化资源后缀也能识别(tmp_path: Path) -> None:
    found = citations.scan_text(
        "依据 foo.asset:1、bar.font:2、window.layout:3、keys.shortcuts:4",
        where="x",
        root=tmp_path,
    )
    assert [item.file for item in found] == [
        "foo.asset",
        "bar.font",
        "window.layout",
        "keys.shortcuts",
    ]


def test_默认扫描包含引擎内容根并支持前缀(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    game = tmp_path / "game"
    jomini = tmp_path / "jomini"
    clausewitz = tmp_path / "clausewitz"
    for root in (game, jomini, clausewitz):
        root.mkdir()
    (jomini / "gui").mkdir()
    (jomini / "gui" / "shared.gui").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(citations.config, "GAME", game)
    monkeypatch.setattr(citations.config, "JOMINI", jomini)
    monkeypatch.setattr(citations.config, "CLAUSEWITZ", clausewitz)
    found = citations.scan_text("jomini/gui/shared.gui:1", where="x")
    assert found[0].status == "ok"
    assert Path(found[0].resolved) == jomini / "gui" / "shared.gui"


def test_跨内容根同名_basename_必须写前缀(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    roots = [tmp_path / name for name in ("game", "jomini", "clausewitz")]
    for root in roots:
        (root / "gui").mkdir(parents=True)
        (root / "gui" / "same.gui").write_text("x\n", encoding="utf-8")
    (roots[0] / "gui" / "same.gui").unlink()
    monkeypatch.setattr(citations.config, "GAME", roots[0])
    monkeypatch.setattr(citations.config, "JOMINI", roots[1])
    monkeypatch.setattr(citations.config, "CLAUSEWITZ", roots[2])
    found = citations.scan_text("same.gui:1", where="x")
    assert found[0].status == "ambiguous"
    explicit = citations.scan_text("clausewitz/gui/same.gui:1", where="x")
    assert explicit[0].status == "ok"


@pytest.fixture(autouse=True)
def _clear_index() -> None:
    citations.clear_cache()


def _fake_game(tmp_path: Path, files: dict[str, str]) -> Path:
    """造一棵假的"游戏内容层"（`common/` 下两个目录 + 一个同名歧义文件）。"""
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


class TestExtraction:
    def test_认出带行号的引用(self) -> None:
        found = citations.scan_text("依据见 00_defines.txt:12", where="x")
        assert [(item.file, item.start, item.end) for item in found] == [("00_defines.txt", 12, 12)]

    def test_认出区间写法(self) -> None:
        found = citations.scan_text("见 content_1_modifiers.txt:1462-1470 那一族", where="x")
        assert [(item.start, item.end) for item in found] == [(1462, 1470)]

    def test_不带扩展名的冒号数字不算引用(self) -> None:
        """`P2:F9` / `阶段 3：12` 这类是文档章节号，不能当文件引用。"""
        assert citations.scan_text("见 01a 的 P2:F9 与 ULTRA:12", where="x") == []

    def test_文件名里带空格也认(self) -> None:
        """原版历史文件真的叫 `rus - russia.txt`（实测：写全路径时扫描器原样不认，
        `v3 citations` 报了 4 条假 missing）。"""
        found = citations.scan_text("依据：common/history/countries/rus - russia.txt:14", where="x")
        assert len(found) == 1
        assert found[0].file == "common/history/countries/rus - russia.txt"
        assert found[0].start == 14

    def test_中文叙述里的行号照样认得出(self) -> None:
        found = citations.scan_text("原版 `00_corn_laws.txt:79` 就是 `weight = 100`", where="x")
        assert len(found) == 1
        assert found[0].file == "00_corn_laws.txt"


class TestResolve:
    def test_唯一同名文件解析得到(self, tmp_path: Path) -> None:
        root = _fake_game(tmp_path, {"common/defines/00_ai.txt": "a\nb\nc\n"})
        found = citations.scan_text("00_ai.txt:2", where="x", root=root)
        assert found[0].status == "ok"
        assert Path(found[0].resolved) == root / "common" / "defines" / "00_ai.txt"

    def test_同名多个要报歧义而不是碰运气(self, tmp_path: Path) -> None:
        """`modifiers.txt` 这类名字在原版里有几十个 —— 只写 basename 等于没指。"""
        root = _fake_game(
            tmp_path,
            {"common/a/modifiers.txt": "x\n", "common/b/modifiers.txt": "y\n"},
        )
        found = citations.scan_text("modifiers.txt:1", where="x", root=root)
        assert found[0].status == "ambiguous"
        assert "同名 2 个" in found[0].detail

    def test_写了子路径就不再歧义(self, tmp_path: Path) -> None:
        root = _fake_game(
            tmp_path,
            {"common/a/modifiers.txt": "x\n", "common/b/modifiers.txt": "y\n"},
        )
        found = citations.scan_text("common/b/modifiers.txt:1", where="x", root=root)
        assert found[0].status == "ok"

    def test_没有这个文件要报_missing(self, tmp_path: Path) -> None:
        root = _fake_game(tmp_path, {"common/defines/00_ai.txt": "a\n"})
        found = citations.scan_text("00_sikh_empire.txt:20", where="x", root=root)
        assert found[0].status == "missing"
        assert "没有任何文件叫这个名字" in found[0].detail

    def test_少了子路径要报_missing(self, tmp_path: Path) -> None:
        """实测踩过：`ai_strategies/03_political_strategies.txt` 其实在 `common/` 下。"""
        root = _fake_game(tmp_path, {"common/ai_strategies/03_political_strategies.txt": "a\n"})
        found = citations.scan_text(
            "ai_strategies/03_political_strategies.txt:1", where="x", root=root
        )
        assert found[0].status == "missing"

    def test_行号越界要报出来(self, tmp_path: Path) -> None:
        root = _fake_game(tmp_path, {"common/defines/00_ai.txt": "a\nb\n"})
        found = citations.scan_text("00_ai.txt:322", where="x", root=root)
        assert found[0].status == "out_of_range"
        assert "只有 2 行" in found[0].detail

    def test_区间反过来也算坏(self, tmp_path: Path) -> None:
        root = _fake_game(tmp_path, {"common/defines/00_ai.txt": "a\nb\nc\n"})
        found = citations.scan_text("00_ai.txt:3-1", where="x", root=root)
        assert found[0].status == "out_of_range"

    def test_仓库内文件也认(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """`why` 里也会引仓库自己的文件（例如生成器的行号）。"""
        monkeypatch.setattr(citations.config, "REPO", tmp_path)
        (tmp_path / "note.md").write_text("x\n", encoding="utf-8")
        found = citations.scan_text("note.md:1", where="x", root=tmp_path / "nowhere")
        assert found[0].status == "ok"


class TestSummarize:
    def test_计数与问题清单(self, tmp_path: Path) -> None:
        root = _fake_game(tmp_path, {"common/defines/00_ai.txt": "a\nb\n"})
        found = citations.scan_text(
            "好的 00_ai.txt:1，坏的 00_ai.txt:99，没有的 zzz.txt:1", where="x", root=root
        )
        stats = citations.summarize(found)
        assert stats["total"] == 3
        assert stats["by_status"] == {"ok": 1, "out_of_range": 1, "missing": 1}
        assert len(stats["problems"]) == 2  # type: ignore[arg-type]


def test_cli只扫描显式路径并拒绝空引用集(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from pdx import cli

    game = _fake_game(tmp_path / "game", {"common/defines/00_ai.txt": "value = 1\n"})
    source = tmp_path / "notes.md"
    source.write_text("依据见 common/defines/00_ai.txt:1\n", encoding="utf-8")
    monkeypatch.setattr(citations.config, "GAME", game)
    runner = CliRunner()
    assert runner.invoke(cli.app, ["citations", str(source)]).exit_code == 0
    assert runner.invoke(cli.app, ["citations"]).exit_code != 0
    source.write_text("没有文件引用\n", encoding="utf-8")
    empty = runner.invoke(cli.app, ["citations", str(source)])
    assert empty.exit_code != 0
    assert "没有发现文件:行号引用" in empty.output
