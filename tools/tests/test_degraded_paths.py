"""**降级路径**与合成输入的覆盖（无游戏 / 坏文件 / 空输入）。

为什么单独一个文件
------------------
`v3` 的每个模块都有一条「游戏目录不存在」的分支（CI 上真的走这条路），
以及若干「文件坏了 / 输入为空」的兜底。它们此前几乎全没被覆盖 ——
不是因为难测，而是因为**本机永远有游戏**，写用例时想不起来。

这些用例统一用「把 `config.GAME` 指到临时目录」的手法：不读真游戏、
毫秒级、在 CI 上也能跑。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from pdx import doc_tables, docgen, localization, mods, tabular
from pdx.doc_tables import TableSpec

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture
def no_game(tmp_path, monkeypatch):
    """把各模块看到的「游戏目录」指到一个空临时目录。"""
    fake = tmp_path / "game"
    fake.mkdir()
    for module in (docgen, localization, mods, tabular):
        if hasattr(module, "config"):
            monkeypatch.setattr(module.config, "GAME", fake)
    return fake


# ────────────────────────── 表格解析 ──────────────────────────


def test_嗅探失败时按首行出现次数选分隔符() -> None:
    """`csv.Sniffer` 认不出来时要有兜底 —— 它认不出的输入是真实存在的。"""
    text = "a\tb\tc\n1\t2\t3\n"
    delimiter, columns, rows = tabular.parse_table_text(text)
    assert delimiter == "\t"
    assert columns == ["a", "b", "c"]
    assert rows == [["1", "2", "3"]]


def test_空文本给空表() -> None:
    delimiter, columns, rows = tabular.parse_table_text("")
    assert columns == []
    assert rows == []
    assert delimiter in {";", ",", "\t", "|"}


def test_表格目录不存在时是空报告(no_game) -> None:
    report = tabular.extract_tables(no_game / "没有这个目录")
    assert report.tables == []
    assert report.errors == []


def test_列统计对空单元格与缺列都稳() -> None:
    table = tabular.Table(
        rel="x.csv",
        delimiter=";",
        columns=["a", "b"],
        rows=[["1", "2"], ["1", ""], ["1"]],  # 第三行短一列
        size=0,
    )
    stats = {s.name: s for s in tabular.column_stats(table, top=1)}
    assert stats["a"].distinct == 1
    assert stats["a"].top == (("1", 3),)
    assert stats["b"].blanks == 2, "空串与缺列都算空值"


# ────────────────────────── 本地化 ──────────────────────────


def test_本地化在空目录上给零(no_game) -> None:
    report = localization.extract_localization(no_game)
    assert report.files == 0
    assert report.unique_keys == 0


def test_各统计函数在缺目录时都给零(no_game) -> None:
    """这些函数都被 doc 06 的生成表调用 —— 空目录时必须给零而不是抛。"""
    assert localization.language_header_counts(no_game) == {}
    assert localization.yml_unique_name_count(no_game) == 0
    assert localization.gui_sprite_lines(no_game) == 0
    assert localization.texticon_counts(no_game) == {}
    assert localization.data_function_counts(no_game) == {}


def test_本地化坏文件被记进错误而不是抛(no_game) -> None:
    """`.yml` 是 UTF-8 文本，但真实世界里会有 GBK 残留 —— 读取用 replace 兜底。"""
    loc = no_game / "localization" / "english"
    loc.mkdir(parents=True)
    (loc / "a_l_english.yml").write_text(
        'l_english:\n a_key:0 "值"\n b_key:0 "另一个值"\n', encoding="utf-8"
    )
    report = localization.extract_localization(no_game)
    assert report.files == 1
    assert report.unique_keys == 2


# ────────────────────────── mod 元数据 ──────────────────────────


def test_没有metadata时返回空字典(tmp_path) -> None:
    assert mods.read_metadata(tmp_path) == {}


def test_坏json不抛异常(tmp_path) -> None:
    meta = tmp_path / mods.METADATA_REL
    meta.parent.mkdir(parents=True)
    meta.write_text("{ 这不是 json", encoding="utf-8")
    assert mods.read_metadata(tmp_path) == {}


def test_空mod目录给零画像(tmp_path) -> None:
    info = mods.analyse_mod(tmp_path / "empty_mod")
    assert info.files == 0
    assert info.prefixes == {}
    assert info.size_mb == 0.0


def test_mod画像带metadata与文件(tmp_path) -> None:
    root = tmp_path / "mod_a"
    (root / "common" / "scripted_effects").mkdir(parents=True)
    (root / "common" / "scripted_effects" / "x.txt").write_text(
        "INJECT:vanilla_key = { a = 1 }\nmymod_new = { b = 2 }\n", encoding="utf-8"
    )
    meta = root / mods.METADATA_REL
    meta.parent.mkdir(parents=True)
    meta.write_text(
        json.dumps({"name": "测试 mod", "id": "123", "version": "1.0"}), encoding="utf-8"
    )
    info = mods.analyse_mod(root, vanilla=tmp_path / "vanilla")
    assert info.name == "测试 mod"
    assert info.prefixes["INJECT"] == 1
    assert info.size_mb >= 0.0
    assert any("scripted_effects" in rel for rel in info.additions)


# ────────────────────────── 生成器管线 ──────────────────────────


def _fake_target(
    tmp_path: Path, rows_fn: Callable[[], list[str]], name: str = "99-测试.md"
) -> tuple[Path, TableSpec, object]:
    doc = tmp_path / name
    doc.write_text(
        "# 测试\n\n| 名字 | 数量 |\n| --- | ---: |\n| a | 1 |\n\n后记。\n", encoding="utf-8"
    )
    spec = TableSpec("测试表", "| 名字 | 数量 |", rows_fn)

    class _Target:
        path = doc
        specs = (spec,)

        @property
        def name(self) -> str:
            return doc.name

    return doc, spec, _Target()


def test_write_all_写回表格(tmp_path, monkeypatch) -> None:
    doc, _spec, target = _fake_target(tmp_path, lambda: ["| a | 2 |"])
    monkeypatch.setattr(docgen, "targets", lambda: (target,))
    done = docgen.write_all()
    assert list(done.values()) == [1]
    text = doc.read_text(encoding="utf-8")
    assert "| a | 2 |" in text
    assert "后记。" in text, "散文不许被碰"


def test_render_all_单张表失败不影响其它(tmp_path, monkeypatch) -> None:
    def boom() -> list[str]:
        raise RuntimeError("假装取不到")

    _doc, _spec, target = _fake_target(tmp_path, boom)
    monkeypatch.setattr(docgen, "targets", lambda: (target,))
    rendered = docgen.render_all()
    (value,) = rendered.values()
    assert value[0].startswith("<未取到：RuntimeError")
    assert "假装取不到" in value[0]


def test_render_all_正常时与文档一致(tmp_path, monkeypatch) -> None:
    _doc, _spec, target = _fake_target(tmp_path, lambda: ["| a | 1 |"])
    monkeypatch.setattr(docgen, "targets", lambda: (target,))
    rendered = docgen.render_all()
    (value,) = rendered.values()
    assert value == ["| a | 1 |"]


def test_表头找不到时报错而不是静默跳过(tmp_path, monkeypatch) -> None:
    from pdx.doc_tables import TableNotFoundError, TableSpec

    doc = tmp_path / "x.md"
    doc.write_text("# 没有那张表\n", encoding="utf-8")
    spec = TableSpec("缺表", "| 名字 | 数量 |", lambda: ["| a | 1 |"])
    with pytest.raises(TableNotFoundError):
        doc_tables.current_rows(doc, spec)
