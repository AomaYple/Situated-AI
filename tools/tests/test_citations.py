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


class TestSupportDomain:
    """入库的「引用支撑域」：让 P10 在**没有游戏的机器**上也守得住（B77）。

    没有它，`v3 citations` 是当前 CI 的最后一个实质缺口 —— 其余门禁都有离线通道。
    """

    def _domain(self, tmp_path: Path) -> dict[str, list[str]]:
        """造一份**临时数据源**（里面引了 `00_ai.txt:2`）+ 一棵假游戏树，返回支撑域。

        ⚠️ 不能拿仓库里的 `mod/data` 去配假游戏树 —— 那扫出来的是真实档案的引用，
        里面当然没有 `00_ai.txt`（第一版就是这么写错的）。
        """
        data = tmp_path / "mod" / "data"
        data.mkdir(parents=True, exist_ok=True)
        (data / "t.toml").write_text('why = "见 00_ai.txt:2"\n', encoding="utf-8")
        root = _fake_game(tmp_path, {"common/defines/00_ai.txt": "第一行\n第二行\n第三行\n"})
        return citations.support_domain([data], root=root)

    def test_记下行数与每一行的指纹(self, tmp_path: Path) -> None:
        # `support_domain` 扫的是**数据源里的引用**，所以先在 tmp 里放一份数据源
        data = tmp_path / "mod" / "data"
        data.mkdir(parents=True)
        (data / "t.toml").write_text('why = "见 00_ai.txt:2 与 00_ai.txt:1-3"\n', encoding="utf-8")
        root = _fake_game(tmp_path, {"common/defines/00_ai.txt": "第一行\n第二行\n第三行\n"})
        domain = citations.support_domain([data], root=root)
        body = domain["00_ai.txt"]
        assert "lines=3" in body
        assert citations.line_digest("第二行") in " ".join(body)
        # 区间引用把区间里每一行都记上
        assert sum(1 for item in body if ":" in item) == 3

    def test_指纹忽略首尾空白但不忽略内容(self) -> None:
        assert citations.line_digest("  abc  ") == citations.line_digest("abc")
        assert citations.line_digest("abc") != citations.line_digest("abd")

    def test_解析回来是行数与指纹表(self, tmp_path: Path) -> None:
        domain = self._domain(tmp_path)
        total, digests = citations.parse_support(domain["00_ai.txt"])
        assert total == 3
        assert digests[2] == citations.line_digest("第二行")

    def test_域里没有的引用不算通过(self, tmp_path: Path) -> None:
        root = _fake_game(tmp_path, {"common/defines/00_ai.txt": "a\nb\nc\n"})
        found = citations.scan_text("见 00_ai.txt:2", where="x", root=root)
        bad = citations.unsupported(found, {})
        assert len(bad) == 1
        assert "不在入库支撑域里" in bad[0][1]

    def test_超出入库时的行数要报出来(self, tmp_path: Path) -> None:
        root = _fake_game(tmp_path, {"common/defines/00_ai.txt": "a\nb\nc\n"})
        support = {"00_ai.txt": ["lines=2", "1:abc", "2:def"]}
        found = citations.scan_text("见 00_ai.txt:3", where="x", root=root)
        bad = citations.unsupported(found, support)
        assert len(bad) == 1
        assert "只有 2 行" in bad[0][1]

    def test_离线不看现在的文件只看入库记录(self, tmp_path: Path) -> None:
        """离线（CI）证明的是**与入库快照一致**，不是与现在的游戏一致。"""
        root = _fake_game(tmp_path, {"common/defines/00_ai.txt": "改过了\n第二行\n第三行\n"})
        support = {
            "00_ai.txt": [
                "lines=3",
                f"1:{citations.line_digest('第一行')}",
                f"2:{citations.line_digest('第二行')}",
            ]
        }
        found = citations.scan_text("见 00_ai.txt:1-2", where="x", root=root)
        assert citations.unsupported(found, support) == []

    def test_在线核出被引那一行变了(self, tmp_path: Path) -> None:
        """原版更新把我们的依据挪走了 —— 这条只有有游戏的机器才判得了。"""
        root = _fake_game(tmp_path, {"common/defines/00_ai.txt": "改过了\n第二行\n第三行\n"})
        support = {
            "00_ai.txt": [
                "lines=3",
                f"1:{citations.line_digest('第一行')}",
                f"2:{citations.line_digest('第二行')}",
            ]
        }
        found = citations.scan_text("见 00_ai.txt:1-2", where="x", root=root)
        bad = citations.unsupported(found, support, live=True, root=root)
        assert len(bad) == 1
        assert "内容变了" in bad[0][1]

    def test_区间里有一行没被记进支撑域也要报(self, tmp_path: Path) -> None:
        root = _fake_game(tmp_path, {"common/defines/00_ai.txt": "a\nb\nc\n"})
        support = {"00_ai.txt": ["lines=3", f"1:{citations.line_digest('a')}"]}  # 少了第 2 行
        found = citations.scan_text("见 00_ai.txt:1-2", where="x", root=root)
        bad = citations.unsupported(found, support, live=True, root=root)
        assert len(bad) == 1
        assert "没被记进支撑域" in bad[0][1]

    def test_在线时现在解析不到也要报(self, tmp_path: Path) -> None:
        """入库时解析得到、现在解析不到了（文件被改名/挪走）—— 也是漂移的一种。"""
        root = _fake_game(tmp_path, {"common/defines/00_ai.txt": "a\n"})
        support = {"00_gone.txt": ["lines=1", f"1:{citations.line_digest('a')}"]}
        found = citations.scan_text("见 00_gone.txt:1", where="x", root=root)
        bad = citations.unsupported(found, support, live=True, root=root)
        assert len(bad) == 1
        assert "现在解析不到了" in bad[0][1]

    def test_真实数据源的支撑域与在线核对一致(self) -> None:
        """**真实数据源**上的看守：入库的支撑域必须覆盖每一条引用，且与现场对得上。

        这条比对的是"记录"与"现场"—— 一边坏了两边都会响（只测一边等于没测）。
        """
        data = Path(__file__).resolve().parents[2] / "mod" / "data"
        if not data.is_dir():  # pragma: no cover
            pytest.skip("没有 mod/data")
        if not citations.config.GAME.is_dir():  # pragma: no cover
            pytest.skip("本机没有游戏本体，核对不了现场")
        found = citations.scan_paths([data])
        domain = citations.support_domain([data])
        bad = citations.unsupported(found, domain, live=True)
        assert not bad, "支撑域与现场对不上：\n" + "\n".join(
            f"{item.describe()} —— {detail}" for item, detail in bad[:10]
        )

    def test_入库快照带着这个域(self) -> None:
        """CI 靠的是**入库快照**里那一份，所以它也必须在场（B77 的落点在快照里）。"""
        from pdx import verify

        snap = verify.latest_compact_snapshot()
        if snap is None:  # pragma: no cover
            pytest.skip("仓库里没有精简快照")
        body = snap.sections.get(citations.SECTION)
        assert body, f"精简快照里没有 {citations.SECTION} 域 —— 跑 `v3 snapshot create --compact`"
        assert any(item.startswith("lines=") for values in body.values() for item in values)


class TestRelocate:
    """行号漂移的**找回**（`citations.relocate`）。

    为什么要有它：编辑一个被大量引用的文件（`docs/design/backlog.md`、`tools/pdx/ab_probe.py`
    这类）会让行号整体平移而内容一个字没变，闸门只说"第 N 行的内容变了（原版更新？）"——
    那句话把人的注意力引到**错的方向**上（去看原版更新），而真相是自己刚编辑过那个文件。
    本轮实测踩过两次（`ab_probe.py:805→852`、`backlog.md:161→168`）。
    """

    def _support(self, text: str) -> dict[str, list[str]]:
        lines = text.splitlines()
        return {
            "00_ai.txt": [
                f"lines={len(lines)}",
                *(f"{n}:{citations.line_digest(line)}" for n, line in enumerate(lines, start=1)),
            ]
        }

    def test_内容没变只是行号平移时找回新行号(self, tmp_path: Path) -> None:
        before = "alpha\nbeta\ngamma\n"
        support = self._support(before)
        after = "新插入的一行\n又一行\nalpha\nbeta\ngamma\n"
        root = _fake_game(tmp_path, {"common/defines/00_ai.txt": after})
        found = citations.scan_text("00_ai.txt:2", where="t.toml:3", root=root)
        moves = citations.relocate(found, support, root=root)
        assert [(m.old_line, m.new_line) for m in moves] == [(2, 4)]
        assert moves[0].where == "t.toml:3"
        assert "→" in moves[0].describe()

    def test_内容真的变了就不编一个位置(self, tmp_path: Path) -> None:
        """改的是**内容**（不是位置）时，`relocate` 必须闭嘴 —— 那要人判断。"""
        support = self._support("alpha\nbeta\ngamma\n")
        root = _fake_game(tmp_path, {"common/defines/00_ai.txt": "alpha\n换了\ngamma\n"})
        found = citations.scan_text("00_ai.txt:2", where="t", root=root)
        assert citations.relocate(found, support, root=root) == []

    def test_同文多处取最近的一处并说明(self, tmp_path: Path) -> None:
        support = self._support("x\n同文\nx\n同文\nx\n")
        root = _fake_game(tmp_path, {"common/defines/00_ai.txt": "新\nx\n同文\nx\n同文\nx\n"})
        found = citations.scan_text("00_ai.txt:2", where="t", root=root)
        moves = citations.relocate(found, support, root=root)
        assert len(moves) == 1
        assert moves[0].new_line == 3, moves
        assert "出现 2 次" in moves[0].note

    def test_入库记的是空行时要说这条引用本来就指错了(self, tmp_path: Path) -> None:
        """实测那一处：`backlog.md:161` 的 why 写着「（B22）」，而行号落在**空行**上。

        空行不可能是依据 ⇒ 报"漂移"是把人往错方向引；这里要的是一句**指错了**。
        造法：入库时第 2 行是空行，之后在文件**开头**插了一行 ⇒ 原行号上已不是空行，
        而空行在文件里有多处（多处 + 全是空行 = 这条引用本来就指错了）。
        """
        support = self._support("a\n\nb\n\nc\n")
        root = _fake_game(tmp_path, {"common/defines/00_ai.txt": "x\na\n\nb\n\nc\n"})
        found = citations.scan_text("00_ai.txt:2", where="t", root=root)
        moves = citations.relocate(found, support, root=root)
        assert len(moves) == 1
        assert "空行" in moves[0].note
        assert "指错" in moves[0].note

    def test_没漂移的不出现在清单里(self, tmp_path: Path) -> None:
        text = "a\nb\nc\n"
        root = _fake_game(tmp_path, {"common/defines/00_ai.txt": text})
        found = citations.scan_text("00_ai.txt:2", where="t", root=root)
        assert citations.relocate(found, self._support(text), root=root) == []

    def test_区间引用逐行找(self, tmp_path: Path) -> None:
        """区间引用逐行核：**第一处对不上**的那一行就是被报出来的那一行。"""
        support = self._support("a\nb\nc\nd\n")
        root = _fake_game(tmp_path, {"common/defines/00_ai.txt": "a\nb\n插入\nc\nd\n"})
        found = citations.scan_text("00_ai.txt:2-4", where="t", root=root)
        moves = citations.relocate(found, support, root=root)
        # 第 2 行（b）没动；第 3 行（c）被挤到第 4 行 —— 报的是它
        assert [(m.old_line, m.new_line) for m in moves] == [(3, 4)]

    def test_域里没有这条引用时不报(self, tmp_path: Path) -> None:
        root = _fake_game(tmp_path, {"common/defines/00_ai.txt": "a\nb\n"})
        found = citations.scan_text("00_ai.txt:1", where="t", root=root)
        assert citations.relocate(found, {}, root=root) == []
