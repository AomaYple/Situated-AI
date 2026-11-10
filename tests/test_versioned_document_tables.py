"""Current document tables own complete native sets while preserving old layouts."""

from collections import Counter

import pytest

from pdx import config, doc04, doc17, doc_tables, version_contracts

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("directory", "body", "expected"),
    [
        ("events", "fixture.1={fire_only_once=yes}", {"fire_only_once"}),
        (
            "common/scripted_progress_bars",
            'bar={progress_texture="native.dds" marker=yes}',
            {"progress_texture", "marker"},
        ),
    ],
)
def test_current_field_table_adds_native_fields_and_removes_retired_fields(
    tmp_path, monkeypatch, directory, body, expected
):
    source = tmp_path / directory / "fixture.txt"
    source.parent.mkdir(parents=True)
    source.write_text(body, encoding="utf-8")
    monkeypatch.setattr(config, "GAME", tmp_path)
    with version_contracts.select_version("1.15.0"):
        spec = next(s for s in doc04._doc04_field_specs() if s.name.endswith(directory))
        assert {name for name, _ in spec.cells()} == expected
        rendered = doc_tables.merge_rows(spec, [["retired_field", "1", "old:1", "old"]], width=4)
        assert {doc_tables.split_row(row)[0].strip("`") for row in rendered} == expected
        assert all("fixture.txt:1" in row for row in rendered)
    with version_contracts.select_version("1.14.5"):
        historical = next(s for s in doc04._doc04_field_specs() if s.name.endswith(directory))
        assert historical.append_new is False
        assert historical.allow_drop is False


def test_current_je_table_keeps_every_group_including_the_unpaired_last_group(monkeypatch):
    expected = {f"`je_group_{index:02}`": index + 1 for index in range(31)}
    counter = Counter(expected)
    monkeypatch.setattr(doc04, "je_group_counts", lambda: counter)
    with version_contracts.select_version("1.15.0"):
        specs = doc04._je_group_specs()
        assert len(specs) == 1
        assert isinstance(specs[0], doc_tables.TableSpec)
        rows = [doc_tables.split_row(row) for row in specs[0].rows()]
        actual = {
            row[column]: int(row[column + 1]) for row in rows for column in (0, 3) if row[column]
        }
        assert actual == expected
        assert len(rows) == 16
        original = specs[0].rows()
        counter = Counter(dict(reversed(list(counter.items()))))
        assert specs[0].rows() == original
    with version_contracts.select_version("1.14.5"):
        assert len(doc04._je_group_specs()) == 2
        assert all(isinstance(spec, doc_tables.KeyedTableSpec) for spec in doc04._je_group_specs())


def test_current_doc17_overview_counts_repeated_blocks_and_preserves_author_columns(
    tmp_path, monkeypatch
):
    fixtures = {
        "genes/fixture.txt": "@variable=1 gene={} gene={}",
        "technology/technologies/one.txt": "one={}",
        "technology/technologies/two.txt": "two={}",
        "technology/technologies/three.txt": "three={}",
        "technology/eras/eras.txt": "era={}",
    }
    for name, text in fixtures.items():
        source = tmp_path / "common" / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(text, encoding="utf-8")
    monkeypatch.setattr(config, "GAME", tmp_path)
    with version_contracts.select_version("1.15.0"):
        cells = dict(doc17._overview_table_rows())
        assert cells["`genes`"] == {2: "1", 3: "1 个块名（2 处定义）"}
        assert cells["`technology`"] == {2: "3 + `eras/`1", 3: "3 + 1"}
        assert doc17._overview_counts() == (5, 6)
        spec = next(s for s in doc17.doc_table_specs() if s.name == "doc17 §0 目录总览")
        rows = doc_tables.merge_rows(
            spec, [["1", "`genes`", "8", "5 个块名（9 处定义）", "官方引用", "作者用途"]], width=6
        )
        row = doc_tables.split_row(rows[0])
        assert row[2:4] == ["1", "1 个块名（2 处定义）"]
        assert row[4:] == ["官方引用", "作者用途"]
    with version_contracts.select_version("1.14.5"):
        assert all(s.name != "doc17 §0 目录总览" for s in doc17.doc_table_specs())
