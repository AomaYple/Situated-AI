"""The current doc17 tables account for incomplete files without reading partial trees."""

import json
from dataclasses import replace
from hashlib import sha256
from re import escape

import pytest

from pdx import cache, config, doc17, doc17_receipt, tables_offline, verify, version_contracts
from pdx.model import ParseError
from pdx.snapshot import SnapshotFormatError

pytestmark = pytest.mark.unit


@pytest.fixture
def dna_source(tmp_path, monkeypatch):
    directory = tmp_path / "common/dna_data"
    directory.mkdir(parents=True)
    (directory / "one.txt").write_text("one={portrait_info={} enabled=yes}", encoding="utf-8")
    (directory / "empty.txt").write_text("# comment", encoding="utf-8")
    partial = directory / "partial.txt"
    body = b"partial={portrait_info={} enabled=yes dna=example"
    partial.write_bytes(body)
    monkeypatch.setattr(config, "GAME", tmp_path)
    monkeypatch.setattr(
        doc17, "FROZEN_PARTIAL_DNA_SHA256", {"dna_data/partial.txt": sha256(body).hexdigest()}
    )
    return partial


def test_current_doc17_accounts_for_partial_without_counting_it(dna_source):
    with version_contracts.select_version("1.15.1"):
        fields = next(s for s in doc17.doc_table_specs() if s.name.startswith("doc17 字段表1 "))
        assert dict(fields.cells()) == {
            "portrait_info": {2: "1"},
            "enabled": {2: "1"},
            "dna": {2: "0"},
        }
        assert dict(doc17._overview_table_rows())["`dna_data`"] == {
            2: "3（2 完整，1 部分）",
            3: "1",
        }
        assert doc17._overview_counts() == (3, 1)
        with pytest.raises(ParseError, match="parse_status=partial"):
            cache.parse_cached(dna_source).require_complete()


@pytest.mark.parametrize(
    ("name", "raw"),
    [
        ("partial.txt", b"changed={portrait_info={}"),
        ("partial.txt", b"changed={portrait_info={}}"),
        ("unknown.txt", b"partial={portrait_info={} enabled=yes dna=example"),
        ("damaged.txt", b"partial={\xff"),
    ],
)
def test_current_doc17_rejects_unverified_incomplete_sources(dna_source, name, raw):
    dna_source.with_name(name).write_bytes(raw)
    with version_contracts.select_version("1.15.1"), pytest.raises(ParseError, match=escape(name)):
        doc17._overview_counts()


def test_doc17_observation_binds_frozen_sources_and_keeps_the_historical_rows():
    with version_contracts.select_version("1.15.1"):
        snapshot_path = verify.latest_compact_snapshot_path()
        assert snapshot_path is not None
        snap = verify.latest_compact_snapshot()
        assert snap is not None
        historical = tables_offline.load_tables(snapshot_path)
        current = tables_offline.load_tables(only="17-")
        field_table = next(key for key in doc17_receipt.TABLE_KEYS if "字段表" in key)
        assert "| `portrait_info` | ✅ | 642 | 肖像数据容器 |" in historical[field_table]
        assert "| `portrait_info` | ✅ | 636 | 肖像数据容器 |" in current[field_table]
        assert tables_offline.compare(only="17-") == ([], [], [])

        sources = dict(snap.sections["source_identity"])
        path = "game/common/dna_data/00_abraham_lincoln.txt"
        sources[path] = [
            value if value.startswith("size:") else "sha256:" + "0" * 64 for value in sources[path]
        ]
        modified = replace(snap, sections={**snap.sections, "source_identity": sources})
        with pytest.raises(SnapshotFormatError, match="冻结来源身份不符"):
            doc17_receipt.load(modified)


@pytest.mark.parametrize(
    ("original_value", "modified_value"),
    [
        ("| 636 | 肖像", "| 999 | 肖像"),
        ("643（637 完整，6 部分）", "643（636 完整，7 部分）"),
    ],
)
def test_doc17_rejects_matching_edits_to_receipt_and_doc(
    tmp_path, monkeypatch, original_value, modified_value
):
    with version_contracts.select_version("1.15.1"):
        original = json.loads(doc17_receipt._path().read_text(encoding="utf-8"))
        document = (config.docs_root() / doc17_receipt.DOC).read_text(encoding="utf-8")
        assert original_value in document
        (tmp_path / doc17_receipt.DOC).write_text(
            document.replace(original_value, modified_value), encoding="utf-8"
        )
        tables = {
            key: [row.replace(original_value, modified_value) for row in rows]
            for key, rows in original["tables"].items()
        }
        assert tables != original["tables"]
        receipt = tmp_path / "doc17.json"
        receipt.write_text(json.dumps(original | {"tables": tables}), encoding="utf-8")
        monkeypatch.setattr(doc17_receipt, "_path", lambda: receipt)
        monkeypatch.setattr(config, "DOCS", tmp_path)
        with pytest.raises(SnapshotFormatError, match="冻结表值身份不符"):
            tables_offline.compare(only="17-")
