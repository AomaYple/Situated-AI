"""离线表格核对（`v3 tables --offline`）的测试。

要证明的性质
-----------
1. **比对是对的**：文档里被手改一行就报出来，没改就不报；
2. **恢复是无损的**：`restore()` 只动表格的数据行，表头、分隔线与**散文**原样；
3. **快照缺表不当成不一致**：新增规格还没有进快照时，只列为「缺」而不是「错」
   —— 否则每次加一张表都要先重建快照才能跑 CI；
4. **反向也要看得见**：快照里有、登记表里没有的表（规格被删/改名）要报出来。
"""

from __future__ import annotations

import pytest

from pdx import docgen, tables_offline
from pdx.doc_tables import TableMalformedError, TableSpec

pytestmark = pytest.mark.unit


class _FakeTarget:
    """替身：只提供一个文档路径与一条规格。"""

    def __init__(self, path, specs, name):
        self.path = path
        self.specs = tuple(specs)
        self.name = name


def _doc_text(rows: list[str]) -> str:
    return (
        "# 测试文档\n\n"
        "前言。\n\n"
        "| 名字 | 数量 |\n"
        "| --- | ---: |\n" + "".join(f"{row}\n" for row in rows) + "\n后记（不许被生成器碰）。\n"
    )


def _setup(tmp_path, rows, monkeypatch, spec_rows=None):
    doc = tmp_path / "99-测试.md"
    doc.write_text(_doc_text(rows), encoding="utf-8")
    spec = TableSpec("测试表", "| 名字 | 数量 |", lambda: list(spec_rows or rows))
    target = _FakeTarget(doc, [spec], "99-测试.md")
    monkeypatch.setattr(tables_offline.docgen, "targets", lambda: (target,))
    return doc, spec


def test_一致时不报差异(tmp_path, monkeypatch) -> None:
    rows = ["| alpha | 1 |", "| beta | 2 |"]
    _setup(tmp_path, rows, monkeypatch)
    recorded = {"99-测试.md::测试表": rows}
    diffs, missing, orphans = tables_offline.compare(recorded)
    assert not diffs
    assert not missing
    assert not orphans


def test_文档被手改就报出来(tmp_path, monkeypatch) -> None:
    rows = ["| alpha | 1 |", "| beta | 2 |"]
    doc, _spec = _setup(tmp_path, ["| alpha | 999 |", "| beta | 2 |"], monkeypatch)
    recorded = {"99-测试.md::测试表": rows}
    diffs, _missing, _orphans = tables_offline.compare(recorded)
    assert len(diffs) == 1
    assert diffs[0].line == 1
    assert "999" in diffs[0].actual
    assert "1" in diffs[0].expected
    assert doc.read_text(encoding="utf-8").count("999") == 1, "只读比对不该改文件"


def test_行数不同也算不一致(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, ["| alpha | 1 |"], monkeypatch)
    recorded = {"99-测试.md::测试表": ["| alpha | 1 |", "| beta | 2 |"]}
    diffs, _m, _o = tables_offline.compare(recorded)
    assert [d.expected for d in diffs] == ["| beta | 2 |"]


def test_恢复只动数据行(tmp_path, monkeypatch) -> None:
    rows = ["| alpha | 1 |", "| beta | 2 |"]
    doc, _spec = _setup(tmp_path, ["| alpha | 999 |", "| beta | 2 |"], monkeypatch)
    before = doc.read_text(encoding="utf-8")
    assert "前言。" in before
    assert "后记（不许被生成器碰）。" in before

    done = tables_offline.restore({"99-测试.md::测试表": rows})
    after = doc.read_text(encoding="utf-8")
    assert done == {"99-测试.md::测试表": 2}
    assert "| alpha | 1 |" in after
    assert "999" not in after
    assert "前言。" in after
    assert "后记（不许被生成器碰）。" in after
    assert after.count("| --- | ---: |") == 1


def test_restore_validates_selected_batch_before_writing(tmp_path, monkeypatch) -> None:
    first = tmp_path / "a.md"
    last = tmp_path / "z.md"
    first.write_text(
        _doc_text(["| alpha | 1 |"]) + "\n" + _doc_text(["| beta | 1 |"]), encoding="utf-8"
    )
    last.write_text("| 名字 | 数量 |\n缺少分隔行\n| z | 1 |\n", encoding="utf-8")
    spec = TableSpec("first", "| 名字 | 数量 |", list)
    second = TableSpec("second", "| 名字 | 数量 |", list, occurrence=1)
    monkeypatch.setattr(
        docgen,
        "targets",
        lambda: (
            docgen.DocTarget(first, (spec,)),
            docgen.DocTarget(first, (second,)),
            docgen.DocTarget(last, (spec,)),
        ),
    )
    recorded = {
        "a.md::first": ["| alpha | 2 |", "| extra | 3 |"],
        "a.md::second#1": ["| beta | 2 |"],
        "z.md::first": ["| z | 2 |"],
    }
    before = first.read_bytes(), last.read_bytes()
    with pytest.raises(TableMalformedError):
        tables_offline.restore(recorded)
    assert (first.read_bytes(), last.read_bytes()) == before
    assert tables_offline.restore(recorded, only="a.md") == {"a.md::first": 2, "a.md::second#1": 1}
    assert first.read_text(encoding="utf-8") == (
        _doc_text(["| alpha | 2 |", "| extra | 3 |"]) + "\n" + _doc_text(["| beta | 2 |"])
    )
    assert last.read_bytes() == before[1]
    assert tables_offline.restore(recorded, only="a.md") == {}


def test_快照缺表只算缺不算错(tmp_path, monkeypatch) -> None:
    rows = ["| alpha | 1 |"]
    _setup(tmp_path, rows, monkeypatch)
    diffs, missing, orphans = tables_offline.compare({})
    assert not diffs, "快照里没有这张表时不该报「不一致」"
    assert missing == ["99-测试.md::测试表"]
    assert not orphans


def test_快照里有但登记表没有的表会被报出来(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, ["| alpha | 1 |"], monkeypatch)
    diffs, _missing, orphans = tables_offline.compare({"99-测试.md::已删除的表": ["| x | 1 |"]})
    assert not diffs
    assert orphans == ["99-测试.md::已删除的表"]


def test_真实仓库的快照里记着全部生成表() -> None:
    """线上检查：入库快照必须覆盖登记在案的每一张表。

    这条不读游戏（只读快照与 `docgen.targets()` 的**规格清单**），
    因此 CI 上也能跑 —— 它守的是「加了表却忘了重建快照」。
    """
    recorded = tables_offline.load_tables()
    assert recorded, "入库的精简快照（tools/out/snapshots/*.compact.json）缺失或没有生成表记录"
    _diffs, missing, orphans = tables_offline.compare(recorded)
    assert not missing, f"这些登记在案的表不在快照里（本机跑 v3 refresh 后重建快照）：{missing}"
    assert not orphans, f"快照里有这些表已不在登记表里（规格被删或改名）：{orphans}"


def test_生成表规格数没变() -> None:
    """顺手钉一个总量：规格数量突然变化说明有张表被悄悄摘掉了。"""
    assert sum(len(t.specs) for t in docgen.targets()) >= 150


@pytest.mark.parametrize(
    "branches",
    [{}, {"caligula_branch": "release/1.15.0", "clausewitz_branch": "caligula/release/1.15.0"}],
)
def test_live_doc08_version_refuses_missing_or_other_installation(monkeypatch, tmp_path, branches):
    from pdx import install_tree
    from pdx.doc_tables import TableMalformedError

    monkeypatch.setattr(install_tree.config, "ROOT", tmp_path)
    monkeypatch.setattr(install_tree.config, "game_version", lambda: branches)
    with pytest.raises(TableMalformedError):
        install_tree._spec_version_fingerprint().cells()


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        ({"game/gfx/map/../a.md": {}}, "official-document entry is malformed"),
        ({"game/gfx/map/a.md": 1}, "official-document entry is malformed"),
        ({}, "narrative metadata is incomplete"),
    ],
)
def test_current_doc08_map_table_rejects_malformed_manifest(
    tmp_path, monkeypatch, entries, message
):
    from pdx import install_tree
    from pdx.doc_tables import KeyedTableSpec, TableMalformedError

    (tmp_path / "gfx" / "map").mkdir(parents=True)
    monkeypatch.setattr(install_tree.config, "GAME", tmp_path)
    monkeypatch.setattr(install_tree.docs_mirror, "load_manifest", lambda: {"文档": entries})
    table = next(spec for spec in install_tree.doc_table_specs() if spec.name == "doc08 gfx 子目录")
    assert isinstance(table, KeyedTableSpec)
    with pytest.raises(TableMalformedError, match=message):
        table.cells()
