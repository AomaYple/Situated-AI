"""全量信息目录的契约测试。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from pdx import information_catalog

if TYPE_CHECKING:
    from pathlib import Path


def _write_fixture(root: Path) -> Path:
    game = root / "game"
    (game / "common" / "ai_strategies").mkdir(parents=True)
    (game / "common" / "buildings").mkdir(parents=True)
    (game / "localization" / "english").mkdir(parents=True)
    (game / "common" / "ai_strategies" / "demo.txt").write_text(
        """
ai_strategy_demo = {
    type = political
    weight = { value = 1 }
    possible = { has_law = law_type:law_x }
}
""".lstrip(),
        encoding="utf-8",
        newline="\n",
    )
    (game / "common" / "buildings" / "demo.txt").write_text(
        """
building_demo = {
    building_group = bg_test
    production_method_groups = { pmg_test }
}
""".lstrip(),
        encoding="utf-8",
        newline="\n",
    )
    (game / "localization" / "english" / "demo_l_english.yml").write_text(
        'l_english:\n demo_key:0 "Demo"\n', encoding="utf-8", newline="\n"
    )
    return game


def test_build_catalog_has_stable_ids_and_explicit_unknowns(tmp_path: Path) -> None:
    game = _write_fixture(tmp_path)
    catalog = information_catalog.build(roots={"game": game}, version={"branch": "test"})

    assert catalog.version == {"branch": "test"}
    assert len({item.id for item in catalog.items}) == len(catalog.items)
    second = information_catalog.build(roots={"game": game}, version={"branch": "test"})
    assert [item.id for item in catalog.items] == [item.id for item in second.items]

    building = next(item for item in catalog.items if item.name == "building_demo")
    assert building.id == "game/common/buildings:game/common/buildings/demo.txt:building_demo"
    assert building.status is information_catalog.InformationStatus.DISCOVERED
    assert building.impact is information_catalog.ImpactLevel.NO_CONSUMER
    assert building.scope == "unknown"
    assert len(building.source_sha256) == 64

    localization = next(item for item in catalog.items if item.domain == "game/localization")
    assert localization.visibility == "public_localization"
    assert localization.scope == "language"


def test_ai_strategy_consumers_are_mapped_without_claiming_runtime_readability(
    tmp_path: Path,
) -> None:
    game = _write_fixture(tmp_path)
    catalog = information_catalog.build(roots={"game": game})

    strategy = next(item for item in catalog.items if item.name == "ai_strategy_demo")
    assert strategy.status is information_catalog.InformationStatus.DISCOVERED
    assert strategy.scope == "unknown"
    assert "ai_strategy:ai_strategy_demo" in strategy.consumers
    assert strategy.impact is information_catalog.ImpactLevel.STRATEGY
    assert "运行时作用域" in strategy.notes


def test_write_is_deterministic_utf8_without_bom_and_lf(tmp_path: Path) -> None:
    game = _write_fixture(tmp_path / "fixture")
    catalog = information_catalog.build(roots={"game": game}, version={"branch": "test"})
    first = tmp_path / "one.json"
    second = tmp_path / "two.json"
    catalog.write(first)
    catalog.write(second)

    first_bytes = first.read_bytes()
    second_bytes = second.read_bytes()
    assert first_bytes == second_bytes
    assert not first_bytes.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in first_bytes
    payload = json.loads(first.read_text(encoding="utf-8"))
    assert payload["格式版本"] == information_catalog.CATALOG_FORMAT
    assert payload["概览"]["条目"] == len(catalog.items)


def test_parser_errors_are_explicitly_unsupported(tmp_path: Path) -> None:
    game = tmp_path / "game"
    target = game / "common" / "buildings" / "broken.txt"
    target.parent.mkdir(parents=True)
    target.write_text("broken = {\n", encoding="utf-8", newline="\n")

    catalog = information_catalog.build(roots={"game": game}, include_localization=False)

    assert len(catalog.items) == 1
    item = catalog.items[0]
    assert item.status is information_catalog.InformationStatus.UNSUPPORTED
    assert item.unit == "parse_error"
    assert "没有闭合" in item.notes


def test_localization_key_catalog_is_streamed_and_auditable(tmp_path: Path) -> None:
    game = _write_fixture(tmp_path / "fixture")
    target = tmp_path / "localization.jsonl"

    stats = information_catalog.write_localization_catalog(
        target, roots={"game": game}, version={"branch": "test"}
    )

    lines = target.read_bytes().splitlines()
    assert stats == {"files": 1, "keys": 1, "errors": 0}
    assert len(lines) == 2
    assert not target.read_bytes().startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in target.read_bytes()
    header = json.loads(lines[0])
    item = json.loads(lines[1])
    assert header["类型"] == "header"
    assert header["版本"] == {"branch": "test"}
    assert item["name"] == "demo_key"
    assert item["source_line"] == 2
    assert item["scope"] == "language"


def test_localization_missing_language_header_is_unsupported(tmp_path: Path) -> None:
    game = tmp_path / "game"
    target = game / "localization" / "english" / "broken_l_english.yml"
    target.parent.mkdir(parents=True)
    target.write_text('demo_key:0 "Demo"\n', encoding="utf-8", newline="\n")
    output = tmp_path / "localization.jsonl"

    stats = information_catalog.write_localization_catalog(output, roots={"game": game})
    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

    assert stats["errors"] == 1
    assert any(record["status"] == "unsupported" for record in records[1:])


@pytest.mark.parametrize("reader", ["cards", "political"])
def test_consumer_index_read_errors_cannot_be_silently_reported_complete(
    tmp_path, monkeypatch, reader
):
    game = _write_fixture(tmp_path)

    def fail(*args, **kwargs):
        raise OSError("fixture read denied")

    if reader == "cards":
        monkeypatch.setattr(information_catalog.ai_surface, "read_cards", fail)
    else:
        monkeypatch.setattr(information_catalog.political_surface, "read_strategies", fail)
    with pytest.raises(ValueError, match="索引读取失败"):
        information_catalog.build(roots={"game": game})


def test_selected_missing_root_is_an_explicit_failure(tmp_path):
    with pytest.raises(FileNotFoundError, match="内容根"):
        information_catalog.build(roots={"game": tmp_path / "missing"})
