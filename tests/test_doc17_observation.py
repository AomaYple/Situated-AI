"""The current doc17 tables account for incomplete files without reading partial trees."""

from hashlib import sha256
from re import escape

import pytest

from pdx import cache, config, doc17, tables_offline, verify
from pdx.model import ParseError

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


def test_doc17_accounts_for_partial_without_counting_it(dna_source):
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
    with pytest.raises(ParseError, match=escape(name)):
        doc17._overview_counts()


def test_current_doc17_rejects_a_missing_reviewed_source(dna_source):
    dna_source.unlink()
    with pytest.raises(ParseError, match=r"缺少冻结 DNA 来源.*partial\.txt"):
        doc17._overview_counts()


def test_doc17_snapshot_keeps_frozen_source_identities_and_reported_denominators():
    snapshot_path = verify.latest_compact_snapshot_path()
    assert snapshot_path is not None
    snap = verify.latest_compact_snapshot()
    assert snap is not None
    identities = snap.sections["source_identity"]
    assert len(doc17.FROZEN_PARTIAL_DNA_SHA256) == 6
    for path, digest in doc17.FROZEN_PARTIAL_DNA_SHA256.items():
        assert "sha256:" + digest in identities["game/common/" + path]
    key = "17-角色科技与呈现.md::doc17 字段表1 common/dna_data"
    tables = tables_offline.load_tables(snapshot_path)
    assert "| `portrait_info` | ✅ | 636 | 肖像数据容器 |" in tables[key]
    assert any("643（637 完整，6 部分）" in row for rows in tables.values() for row in rows)
    assert tables_offline.compare(only="17-") == ([], [], [])
