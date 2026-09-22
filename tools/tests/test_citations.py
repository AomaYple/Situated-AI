"""`pdx.citations` 的看守：把"依据指得到真实文件的那一行"变成可回归的检查。

这一组的存在理由就是它抓到的东西（2026-09-23 首次上线即命中 5 处）：
`mod/data/ru_defeat.toml` 与 `tr_defeat.toml` 里
  * `00_sikh_empire.txt:20` —— 游戏里**没有这个文件**（真名 `04_sikh_empire.txt`）；
  * `ai_strategies/03_political_strategies.txt` 等 4 处少了 `common/` 前缀。
这些引用会随生成物进入 `mod/*.md`（给人看的档案文档），错了没人发现就是"依据是编的"。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pdx import citations


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


class TestRealArchives:
    """**真实数据源**上的看守：这条断言就是"依据不许是编的"（P10）。"""

    def test_两份档案的引用全部指得到(self) -> None:
        data = Path(__file__).resolve().parents[2] / "mod" / "data"
        if not data.is_dir():  # pragma: no cover - 换机器时才走到
            pytest.skip("没有 mod/data")
        if not citations.config.GAME.is_dir():  # pragma: no cover
            pytest.skip("本机没有游戏本体，引用无法解析")
        found = citations.scan_paths([data])
        problems = [item for item in found if not item.ok]
        assert found, "一份引用都没扫到 —— 说明扫描本身坏了，不是'干净'"
        assert not problems, "这些引用指不到唯一一行：\n" + "\n".join(
            item.describe() for item in problems
        )
