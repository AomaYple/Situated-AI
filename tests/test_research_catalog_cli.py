"""The research command consumes an actual committed synthetic raw epoch."""

import errno
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import zipfile
from contextlib import closing
from dataclasses import asdict
from io import BytesIO
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner, Result

from pdx import cli, config, research_output, version_contracts
from pdx.capability_catalog import indexed_lines, indexed_parsed_file, structured_json_source
from pdx.committed_raw import open_committed_capture
from pdx.information_catalog import _build_from_raw
from pdx.input_contracts import (
    ArtifactRef,
    CaptureCheck,
    InputIdentity,
    InputInventory,
    InventoryRecord,
    SnapshotProvenance,
    dumps_contract,
    file_set_digest,
)
from pdx.input_inventory import PDX_RESOURCE_CATEGORIES, classify_path
from pdx.parser import parse_bytes

_PRIVATE = "%LOCALAPPDATA%/PDX/SDK/victoria3/private.json"
_PRIVATE_TXT = "%LOCALAPPDATA%/PDX/SDK/victoria3/private.txt"
_SENTINEL = "private_value_not_for_projection"
_PARTIAL = "game/common/sample/partial.txt"
_BAD_PDX = "game/common/sample/bad_encoding.txt"


_IDENTITY_SOURCE = {
    relative: f"synthetic build identity {relative}".encode()
    for relative in version_contracts.INSTALLATION_IDENTITY_SHA256
}
_EXTERNAL_REF = "identity-sources/steam-appmanifest.acf"
_FORMATS = tuple(PDX_RESOURCE_CATEGORIES)


def _graphics_resource(suffix: str) -> str:
    if suffix == ".skin":
        return "game/dlc/sample/gfx/skins/sample.skin"
    if suffix == ".terrain":
        return "game/gfx/map/terrain/sample.terrain"
    return f"game/gfx/sample{suffix}"


@pytest.fixture(autouse=True)
def synthetic_installation_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        version_contracts,
        "INSTALLATION_IDENTITY_SHA256",
        {relative: _sha(data) for relative, data in _IDENTITY_SOURCE.items()},
    )


@pytest.fixture
def capture(tmp_path: Path) -> tuple[Path, Path, str, int]:
    return _committed_fixture(tmp_path)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(data: object) -> bytes:
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _committed_fixture(
    tmp_path: Path,
    *,
    version: str = version_contracts.CURRENT_VERSION,
    drift: bool = False,
    extra_sources: dict[str, bytes] | None = None,
) -> tuple[Path, Path, str, int]:
    installation = tmp_path / "installation"
    store = tmp_path / "raw"
    object_root = store / "objects"
    object_root.mkdir(parents=True)
    sources = {
        **_IDENTITY_SOURCE,
        _PRIVATE: json.dumps({"private": _SENTINEL}).encode(),
        _PRIVATE_TXT: f"private = {_SENTINEL}".encode(),
        _PARTIAL: b"partial = { leaf = 1",
        _BAD_PDX: b"preserved = { value = 1 }\xff",
        "game/common/sample/complete.txt": b"active = { leaf = 1 }",
        "game/sample.json": b'{"repeat":1,"repeat":2}',
        "game/broken.json": b'{"open":',
        "game/docs/sample.md": b"# original document\nline 2",
        "game/localization/english/sample_l_english.yml": b'l_english:\n RAW_KEY:0 "sample"\n',
        "game/bin/unknown.raw": b"\x00\xff",
        "game/localization/english/bad_l_english.yml": b'l_english:\n BAD:0 "open\n',
        "game/common/script_values/scores.txt": b"score = { value = 1 }",
        "game/common/example/score.txt": b"# lookup\nentry = { value = score }",
        "game/documents.zip": _zip_sample(),
    }
    sources.update(
        {
            _graphics_resource(ext): b"resource = { setting = yes }"
            if ext not in {".skin", ".terrain"}
            else b"setting = yes"
            for ext in _FORMATS
        }
    )
    sources.update(extra_sources or {})
    if drift:
        sources["caligula_rev.txt"] = b"another-build"

    records = []
    directories = {"."}
    for name, data in sorted(sources.items()):
        digest = _sha(data)
        (object_root / digest).write_bytes(data)
        path = installation / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        directories.update(parent.as_posix() for parent in PurePosixPath(name).parents)
        records.append(
            InventoryRecord(
                name,
                len(data),
                digest,
                "unknown" if Path(name).suffix in _FORMATS else classify_path(name),
                "installation",
                "read",
                "not_attempted",
                ArtifactRef("evidence", f"objects/{digest}", digest),
                (),
                (),
                (),
                (),
                "partial",
            )
        )
    external_payload = b"synthetic external Steam metadata"
    external_sha = _sha(external_payload)
    (object_root / external_sha).write_bytes(external_payload)
    external = ArtifactRef("evidence", _EXTERNAL_REF, external_sha)
    context = _canonical(
        {
            "schema": 3,
            "source_layer": "installation",
            "source_root": str(installation),
            "source_authorization": "synthetic fixture",
            "is_installation": True,
            "directories": sorted(directories),
            "write_target": str(store),
            "allowed_root": str(tmp_path),
            "target_volume": {"anchor": store.anchor, "device": store.stat().st_dev},
            "copy_authorized": True,
            "access_boundary": "temporary fixture only",
            "policy": {"max_store_bytes": 1048576, "reserve_bytes": 1024, "chunk_size": 127},
            "identity_sources": [
                {
                    "reference": asdict(external),
                    "root": str(tmp_path),
                    "authorization": "synthetic external observation",
                    "size": len(external_payload),
                    "raw": asdict(ArtifactRef("evidence", f"objects/{external_sha}", external_sha)),
                }
            ],
        }
    )
    context_hash = _sha(context)
    context_ref = ArtifactRef("evidence", f"raw/context/{context_hash}.json", context_hash)
    context_object = store / context_ref.path
    context_object.parent.mkdir(parents=True)
    context_object.write_bytes(context)
    identity_sources = (
        *(ArtifactRef("installation", name, _sha(sources[name])) for name in _IDENTITY_SOURCE),
        external,
    )
    file_set = file_set_digest(records)
    check = CaptureCheck(
        "2026-11-19T00:00:00+00:00",
        _sha(_canonical(sorted((ref.namespace, ref.path, ref.sha256) for ref in identity_sources))),
        file_set,
        "stable",
    )
    historical = ArtifactRef("repository", "src/recorded_implementation.py", _sha(b"former"))
    identity = InputIdentity(
        str(installation),
        version,
        "synthetic-build",
        "synthetic-branch",
        (),
        identity_sources,
        len(records),
        file_set,
        (historical,),
        (context_ref,),
        check,
        check,
        SnapshotProvenance("installation", "synthetic fixture", None, None),
        "complete",
    )
    inventory = InputInventory(identity.epoch_id, tuple(records), "complete", ())
    epoch_path = store / "epochs" / identity.epoch_id
    epoch_path.mkdir(parents=True)
    identity_bytes = dumps_contract(identity).encode("utf-8")
    inventory_bytes = dumps_contract(inventory).encode("utf-8")
    (epoch_path / "identity.json").write_bytes(identity_bytes)
    (epoch_path / "inventory.json").write_bytes(inventory_bytes)
    (epoch_path / "context.json").write_bytes(context)
    (epoch_path / "COMMITTED.json").write_bytes(
        _canonical(
            {
                "schema": 3,
                "identity_sha256": _sha(identity_bytes),
                "inventory_sha256": _sha(inventory_bytes),
                "context_sha256": context_hash,
            }
        )
    )
    return installation, store, identity.epoch_id, len(records)


def _zip_sample() -> bytes:
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("safe/readme.txt", b"not an input member")
        archive.writestr("../outside.txt", b"unsafe path")
    return stream.getvalue()


def _invoke(raw: Path, epoch: str, output: Path, *extra: str) -> Result:
    return CliRunner().invoke(
        cli.app,
        [
            "information-catalog",
            "--raw-root",
            str(raw),
            "--epoch",
            epoch,
            "--output-dir",
            str(output),
            *extra,
        ],
    )


@pytest.mark.parametrize("option", ["--raw-root", "--epoch", "--output-dir"])
def test_research_options_require_complete_group(option: str, tmp_path: Path) -> None:
    result = CliRunner().invoke(cli.app, ["information-catalog", option, str(tmp_path)])
    assert result.exit_code == 2
    assert "同时提供" in result.output


def test_analyze_research_uses_committed_denominator_and_reports_formats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, raw, epoch, count = _committed_fixture(
        tmp_path,
        extra_sources={
            "game/dlc/sample/gfx/skins/one.skin": b"folder = shape",
            "game/dlc/sample/gfx/skins/two.skin": b"shape = {",
        },
    )
    monkeypatch.setattr(config, "GAME", tmp_path / "absent-game")
    output = tmp_path / "analysis"
    result = CliRunner().invoke(
        cli.app,
        [
            "analyze",
            "--raw-root",
            str(raw),
            "--epoch",
            epoch,
            "--output-dir",
            str(output),
            "--no-mods",
            "--quiet",
        ],
    )
    assert result.exit_code == 0, result.output
    catalog = json.loads((output / "information-catalog.json").read_bytes())["分层目录"]
    formats = catalog["coverage_by_format"]
    assert sum(row["sources"] for row in formats) == count
    skins = next(row for row in formats if row["suffix"] == ".skin")
    assert skins == {
        "category": "asset_entity_dna",
        "suffix": ".skin",
        "sources": 3,
        "bytes": 36,
        "decode_status": {"complete": 3},
        "parse_status": {"complete": 2, "partial": 1},
    }
    assert catalog["coverage"][-1]["denominator_status"] == "unknown"


def test_analyze_research_refuses_to_skip_writing(capture, tmp_path: Path) -> None:
    _root, raw, epoch, _count = capture
    output = tmp_path / "analysis"
    result = CliRunner().invoke(
        cli.app,
        [
            "analyze",
            "--raw-root",
            str(raw),
            "--epoch",
            epoch,
            "--output-dir",
            str(output),
            "--no-write",
        ],
    )
    assert result.exit_code == 2
    assert "--no-write" in result.output
    assert not output.exists()


def test_committed_research_preserves_denominator_without_local_state_values(
    capture: tuple[Path, Path, str, int], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, raw, epoch, count = capture
    absent = tmp_path / "unavailable-installation"
    monkeypatch.setattr(config, "ROOT", absent)
    monkeypatch.setattr(config, "GAME", absent / "game")
    output = tmp_path / "research-output"
    result = _invoke(raw, epoch, output)
    assert result.exit_code == 0, result.output
    catalog_text = (output / "information-catalog.json").read_text(encoding="utf-8")
    assert _SENTINEL not in catalog_text
    catalog = json.loads(catalog_text)["分层目录"]
    marker = json.loads((output / "COMPLETE.json").read_bytes())
    assert marker["epoch_id"] == catalog["epoch_id"] == epoch
    assert catalog["index"]["file_count"] == count
    for name in ("information-catalog.json", "occurrences.sqlite"):
        assert marker["files"][name] == hashlib.sha256((output / name).read_bytes()).hexdigest()
    rows = {row["path"]: row for row in catalog["dispositions"]}
    assert rows[_PARTIAL]["parse_status"] == "partial"
    assert rows[_PARTIAL]["semantic_status"] == "unknown"
    assert rows[_BAD_PDX]["raw_status"] == "proven"
    assert rows[_BAD_PDX]["decode_status"] == "failed"
    assert rows[_BAD_PDX]["parse_status"] == "failed"
    assert any("UnicodeDecodeError" in message for message in rows[_BAD_PDX]["diagnostics"])
    for path in (_PRIVATE, _PRIVATE_TXT):
        assert rows[path]["reason"] == "local_state_not_projected"
        assert rows[path]["raw_status"] == "proven"
        assert rows[path]["parse_status"] == "not_attempted"
        source = next(row for row in catalog["input_inventory"]["records"] if row["path"] == path)
        assert len(source["sha256"]) == 64
    with closing(sqlite3.connect(output / "occurrences.sqlite")) as database:
        assert (
            database.execute(
                "SELECT count(*) FROM occurrences WHERE source IN (?,?)", (_PRIVATE, _PRIVATE_TXT)
            ).fetchone()[0]
            == 0
        )
        assert (
            database.execute(
                "SELECT count(*) FROM sources WHERE path IN (?,?)", (_PRIVATE, _PRIVATE_TXT)
            ).fetchone()[0]
            == 2
        )
        assert (
            database.execute("SELECT count(*) FROM occurrences WHERE key='active'").fetchone()[0]
            == 1
        )
        assert (
            database.execute(
                "SELECT count(*) FROM occurrences WHERE source=?", (_BAD_PDX,)
            ).fetchone()[0]
            == 0
        )
    assert _SENTINEL.encode() not in (output / "occurrences.sqlite").read_bytes()
    legacy = parse_bytes((_root / _BAD_PDX).read_bytes(), _BAD_PDX)
    assert legacy.parse_status == "failed"
    assert "preserved" in legacy.top_keys


def test_formats_diagnostics_and_locators_use_the_same_committed_denominator(
    capture: tuple[Path, Path, str, int], tmp_path: Path
) -> None:
    _root, raw, epoch, count = capture
    with open_committed_capture(raw, epoch) as (identity, inventory):
        catalog = _build_from_raw(
            identity=identity,
            inventory=inventory,
            raw_root=raw,
            index_path=tmp_path / "index.sqlite",
        )
    layer = catalog.layered
    rows = {row.path: row for row in layer.dispositions}
    assert layer.index.file_count == len(rows) == count
    for extension in _FORMATS:
        source = _graphics_resource(extension)
        assert rows[source].category == PDX_RESOURCE_CATEGORIES[extension]
        assert rows[source].parse_status == "complete"
        assert layer.index.find(source=source, key="setting")[0].line == 1
    assert rows["game/broken.json"].parse_status == "failed"
    assert rows["game/bin/unknown.raw"].disposition == "unresolved"
    assert rows["game/localization/english/bad_l_english.yml"].parse_status == "partial"
    assert layer.index.find(key="RAW_KEY")[0].line == 2
    assert layer.index.find(source="game/docs/sample.md", scalar="line 2")[0].line == 2
    document = structured_json_source(layer, "game/sample.json")
    assert [node.scalar for node in document.members((), "repeat")] == ["1", "2"]
    assert rows["game/documents.zip"].parse_status == "partial"
    members = layer.index.container_members("game/documents.zip")
    assert [member["safe_mapping"] for member in members] == [True, False]
    assert all(member["content_status"] == "not_read" for member in members)
    audit = layer.index.audit_dependencies(source="game/common/example/score.txt", path=("entry",))
    assert any(ref.target_ids for ref in audit.references)
    with layer.index.connect() as connection:
        partial = indexed_parsed_file(connection, _PARTIAL)
        assert partial.parse_status == "partial"
        assert partial.diagnostics
        assert indexed_lines(connection, "game/docs/sample.md", documents=True) == [
            "# original document",
            "line 2",
        ]


def test_map_table_preserves_order_empty_cells_and_physical_source_lines(tmp_path: Path) -> None:
    table = "game/map_data/adjacencies.csv"
    _root, raw, epoch, count = _committed_fixture(
        tmp_path,
        extra_sources={
            table: b'\xef\xbb\xbfFrom;To;Comment\r\nx;y;"first;line\r\nsecond"\r\ny;;\r\n'
        },
    )
    output = tmp_path / "research-output"
    result = _invoke(raw, epoch, output)
    assert result.exit_code == 0, result.output
    with closing(sqlite3.connect(output / "occurrences.sqlite")) as database:
        assert database.execute("SELECT count(*) FROM sources").fetchone()[0] == count
        assert database.execute(
            "SELECT parse_status FROM sources WHERE path=?", (table,)
        ).fetchone() == ("complete",)
        assert database.execute(
            "SELECT kind, line FROM occurrences WHERE source=? AND parent_id IS NULL ORDER BY line",
            (table,),
        ).fetchall() == [("csv_header", 1), ("csv_row", 2), ("csv_row", 4)]
        assert database.execute(
            """SELECT c.key, c.scalar, p.line FROM occurrences c
            JOIN occurrences p ON p.id=c.parent_id WHERE c.source=? AND p.kind='csv_row'
            ORDER BY p.line, c.address""",
            (table,),
        ).fetchall() == [
            ("From", "x", 2),
            ("To", "y", 2),
            ("Comment", "first;line\r\nsecond", 2),
            ("From", "y", 4),
            ("To", "", 4),
            ("Comment", "", 4),
        ]


def test_map_table_reports_lexical_and_width_gaps(tmp_path: Path) -> None:
    table = "game/map_data/adjacencies.csv"
    _root, raw, epoch, _count = _committed_fixture(
        tmp_path, extra_sources={table: b'From;To\nx;y;extra\nz;"open\n'}
    )
    output = tmp_path / "research-output"
    result = _invoke(raw, epoch, output)
    assert result.exit_code == 0, result.output
    catalog = json.loads((output / "information-catalog.json").read_bytes())["分层目录"]
    disposition = next(row for row in catalog["dispositions"] if row["path"] == table)
    assert disposition["parse_status"] == "partial"
    assert disposition["semantic_status"] == "unknown"
    assert any("csv_row_width:2:" in value for value in disposition["diagnostics"])
    assert any("csv_syntax:3:" in value for value in disposition["diagnostics"])
    with closing(sqlite3.connect(output / "occurrences.sqlite")) as database:
        assert database.execute(
            "SELECT scalar FROM occurrences WHERE source=? AND kind='csv_cell' AND line=2 ORDER BY address",
            (table,),
        ).fetchall() == [("x",), ("y",), ("extra",)]


@pytest.mark.parametrize(
    ("body", "message", "recovered"),
    [
        (b"From,To\nx,y\n", "csv_header_fields", "x,y"),
        (b"From;To;To\nx;y;z\n", "csv_duplicate_header", "z"),
        (b"From;To;\nx;y;z\n", "csv_empty_header", "z"),
        (b"From;To\nx;\x00y\n", "csv_nul:2:", "\x00y"),
        (b'From;To\nx;"bad"z\ny;ok\n', "csv_syntax:2:", "ok"),
    ],
)
def test_map_table_retains_recoverable_cells_when_reporting_format_gaps(
    tmp_path: Path, body: bytes, message: str, recovered: str
) -> None:
    table = "game/map_data/adjacencies.csv"
    _root, raw, epoch, _count = _committed_fixture(tmp_path, extra_sources={table: body})
    with open_committed_capture(raw, epoch) as (identity, inventory):
        catalog = _build_from_raw(
            identity=identity,
            inventory=inventory,
            raw_root=raw,
            index_path=tmp_path / "index.sqlite",
        )
    layer = catalog.layered
    row = next(row for row in layer.dispositions if row.path == table)
    assert row.parse_status == "partial"
    assert any(value.startswith(message) for value in row.diagnostics)
    assert any(hit.kind == "csv_cell" for hit in layer.index.find(source=table, scalar=recovered))


def test_graphics_flat_formats_reject_loose_nodes_and_unverified_locations(tmp_path: Path) -> None:
    skin = _graphics_resource(".skin")
    terrain = _graphics_resource(".terrain")
    outside = "other/sample.skin"
    _root, raw, epoch, _count = _committed_fixture(
        tmp_path,
        extra_sources={
            skin: b"folder = shape orphan",
            terrain: b"detail_scale = 1 { nested = yes }",
            outside: b"name = standalone",
        },
    )
    with open_committed_capture(raw, epoch) as (identity, inventory):
        catalog = _build_from_raw(
            identity=identity,
            inventory=inventory,
            raw_root=raw,
            index_path=tmp_path / "index.sqlite",
        )
    layer = catalog.layered
    rows = {row.path: row for row in layer.dispositions}
    assert rows[skin].parse_status == rows[terrain].parse_status == "partial"
    assert layer.index.find(source=skin, key="folder")[0].parse_status == "partial"
    assert rows[outside].category == "unknown"
    assert layer.index.find(source=outside) == ()


def test_graphics_resources_distinguish_pdx_json_source_and_binary(tmp_path: Path) -> None:
    skin, terrain, curves, metadata, shader, mesh, animation = (
        _graphics_resource(suffix)
        for suffix in (".skin", ".terrain", ".curves", ".meta", ".fxh", ".mesh", ".anim")
    )
    _root, raw, epoch, _count = _committed_fixture(
        tmp_path,
        extra_sources={
            skin: b"folder = sample",
            terrain: b"detail_scale = 1",
            curves: b"{ type = linear }",
            metadata: b'{"input_needs": ["one", "two"]}',
            shader: b'Includes = { "shared.fxh" }\n[[float f() { return a + 1; }]]',
            mesh: b"@@b@!\x08pdxasseti\x02\x00\x00\x00\x01\x00\x00\x00",
            animation: b"\x00\xff",
        },
    )
    with open_committed_capture(raw, epoch) as (identity, inventory):
        catalog = _build_from_raw(
            identity=identity,
            inventory=inventory,
            raw_root=raw,
            index_path=tmp_path / "index.sqlite",
        )
    layer = catalog.layered
    rows = {row.path: row for row in layer.dispositions}
    for source, key in ((skin, "folder"), (terrain, "detail_scale"), (curves, "type")):
        assert rows[source].parse_status == "complete"
        assert layer.index.find(source=source, key=key)[0].line == 1
    document = structured_json_source(layer, metadata)
    assert len(document.members((), "input_needs")) == 1
    assert rows[shader].decode_status == "complete"
    assert rows[shader].parse_status == "not_attempted"
    shader_hit = layer.index.search_text("return a", source=shader)[0]
    assert (shader_hit.kind, shader_hit.line) == ("source_line", 2)
    for source in (mesh, animation):
        assert rows[source].category == "asset_entity_dna"
        assert rows[source].parse_status == "not_attempted"
        assert rows[source].semantic_status == "unknown"
        assert layer.index.find(source=source) == ()


def test_research_refuses_tampered_external_identity_object(
    capture: tuple[Path, Path, str, int], tmp_path: Path
) -> None:
    _root, raw, epoch, _count = capture
    (raw / "objects" / _sha(b"synthetic external Steam metadata")).write_bytes(b"tampered")
    output = tmp_path / "result"
    result = _invoke(raw, epoch, output)
    assert result.exit_code == 1
    assert "外部身份对象不符" in result.output
    assert not output.exists()


def test_research_entry_is_available_via_the_real_python_module(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "pdx.cli",
            "information-catalog",
            "--raw-root",
            str(tmp_path),
        ],
        cwd=config.REPO,
        env={**os.environ, "PYTHONPATH": str(config.REPO / "src")},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 2
    assert "同时提供" in result.stdout


def test_research_reads_epoch_from_an_older_capture_implementation(tmp_path: Path) -> None:
    _root, raw, epoch, _count = _committed_fixture(tmp_path)

    output = tmp_path / "result"
    result = _invoke(raw, epoch, output)
    assert result.exit_code == 0, result.output
    assert json.loads((output / "COMPLETE.json").read_bytes())["epoch_id"] == epoch


@pytest.mark.parametrize("extra", [("--candidate-production",), ("--no-localization",)])
def test_research_rejects_live_flags(
    capture: tuple[Path, Path, str, int], tmp_path: Path, extra: tuple[str, ...]
) -> None:
    _root, raw, epoch, _count = capture
    output = tmp_path / "result"
    result = _invoke(raw, epoch, output, *extra)
    assert result.exit_code == 2
    assert "不能混用" in result.output
    assert not output.exists()


def test_research_rejects_targets_in_raw_or_original_or_existing(
    capture: tuple[Path, Path, str, int], tmp_path: Path
) -> None:
    root, raw, epoch, _count = capture
    existing = tmp_path / "existing"
    existing.write_bytes(b"keep")
    for output in (root / "result", raw / "result", existing):
        result = _invoke(raw, epoch, output)
        assert result.exit_code != 0
    assert not (root / "result").exists()
    assert not (raw / "result").exists()
    assert existing.read_bytes() == b"keep"


def test_research_rejects_wrong_or_noncommitted_epoch(
    capture: tuple[Path, Path, str, int], tmp_path: Path
) -> None:
    _root, raw, epoch, _count = capture
    output = tmp_path / "result"
    for wrong in ("1.15.1", "0" * 64):
        assert _invoke(raw, wrong, output).exit_code != 0
        assert not output.exists()
    (raw / "epochs" / epoch / "COMMITTED.json").unlink()
    assert _invoke(raw, epoch, output).exit_code != 0
    assert not output.exists()


@pytest.mark.parametrize(
    ("version", "drift", "message"),
    [
        ("1.15.0", False, f"当前仅维护 {version_contracts.CURRENT_VERSION}"),
        (version_contracts.CURRENT_VERSION, True, "caligula_rev.txt"),
    ],
)
def test_research_rejects_unreviewed_captured_installation(
    tmp_path: Path, version: str, drift: bool, message: str
) -> None:
    _root, raw, epoch, _count = _committed_fixture(tmp_path, version=version, drift=drift)
    output = tmp_path / "result"
    result = _invoke(raw, epoch, output)
    assert result.exit_code != 0
    assert message in result.output
    assert not output.exists()


def test_research_checks_private_raw_bytes_without_parsing(
    capture: tuple[Path, Path, str, int], tmp_path: Path
) -> None:
    root, raw, epoch, _count = capture
    digest = hashlib.sha256((root / _PRIVATE).read_bytes()).hexdigest()
    (raw / "objects" / digest).write_bytes(b"drifted-private-file")
    output = tmp_path / "result"
    result = _invoke(raw, epoch, output)
    assert result.exit_code != 0
    assert not output.exists()


def test_research_detects_commit_marker_drift_before_publishing(
    capture: tuple[Path, Path, str, int], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pdx.information_catalog import InformationCatalog

    _root, raw, epoch, _count = capture
    marker = raw / "epochs" / epoch / "COMMITTED.json"
    output = tmp_path / "result"
    original = InformationCatalog.write

    def mutate(self: InformationCatalog, path: Path) -> None:
        assert not (output / "COMPLETE.json").exists()
        original(self, path)
        marker.unlink()

    monkeypatch.setattr(InformationCatalog, "write", mutate)
    result = _invoke(raw, epoch, output)
    assert result.exit_code != 0
    assert "消失" in result.output
    assert not output.exists()


def test_epoch_drift_cannot_replace_a_previous_published_index(
    capture: tuple[Path, Path, str, int], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pdx.information_catalog import InformationCatalog

    _root, raw, epoch, _count = capture
    previous = tmp_path / "previous"
    assert (result := _invoke(raw, epoch, previous)).exit_code == 0, result.output
    before = {path.name: _sha(path.read_bytes()) for path in previous.iterdir()}
    marker = raw / "epochs" / epoch / "COMMITTED.json"
    next_output = tmp_path / "next"
    original = InformationCatalog.write

    def swap(self: InformationCatalog, path: Path) -> None:
        assert not next_output.exists()
        original(self, path)
        marker.write_bytes(b"{}")

    monkeypatch.setattr(InformationCatalog, "write", swap)
    assert _invoke(raw, epoch, next_output).exit_code == 1
    assert not next_output.exists()
    assert {path.name: _sha(path.read_bytes()) for path in previous.iterdir()} == before


def test_linux_uses_deepest_mount_and_refuses_ambiguous_or_network_volumes() -> None:
    root = "1 0 0:1 / / rw - overlay overlay rw"
    escaped_mount = r"2 1 0:2 / /data\040files rw - nfs server:/files rw"
    target = Path("/data files/report")
    assert research_output._linux_mount_is_local(target, root)
    assert not research_output._linux_mount_is_local(target, f"{root}\n{escaped_mount}")
    local_mount = "3 1 0:3 / /data\\040files rw - ext4 /dev/vda rw"
    assert not research_output._linux_mount_is_local(
        target, f"{root}\n{escaped_mount}\n{local_mount}"
    )
    assert research_output._linux_mount_is_local(target, f"{root}\n{local_mount}")
    assert not research_output._linux_mount_is_local(target, "incomplete mountinfo")


@pytest.mark.parametrize("is_local", [True, False])
def test_darwin_output_uses_native_volume_locality(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, is_local: bool
) -> None:
    checks: list[Path] = []

    def detect(path: Path) -> bool:
        checks.append(path)
        return is_local

    monkeypatch.setattr(research_output, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(research_output, "_darwin_volume_is_local", detect)
    if is_local:
        research_output._check_local(tmp_path)
    else:
        with pytest.raises(ValueError, match="未标为本地"):
            research_output._check_local(tmp_path)
    assert checks == [tmp_path]


def test_research_rejects_nonignored_output_in_other_git_worktree(
    capture: tuple[Path, Path, str, int], tmp_path: Path
) -> None:
    _root, raw, epoch, _count = capture
    other = tmp_path / "other-repository"
    other.mkdir()
    subprocess.run(["git", "init", "--quiet", str(other)], check=True)
    output = other / "new-output"
    result = _invoke(raw, epoch, output)
    assert result.exit_code != 0, result.output
    assert "必须被忽略" in result.output
    assert not output.exists()


@pytest.mark.parametrize(
    ("different_volume", "staging_ignored", "success"),
    [(False, False, True), (True, False, False), (True, True, True)],
)
def test_research_keeps_output_and_fallback_stage_git_ignored(
    capture: tuple[Path, Path, str, int],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    different_volume: bool,
    staging_ignored: bool,
    success: bool,
) -> None:
    _root, raw, epoch, _count = capture
    other = tmp_path / "other-repository"
    other.mkdir()
    subprocess.run(["git", "init", "--quiet", str(other)], check=True)
    ignore = "/result/\n"
    if staging_ignored:
        ignore += "/.sitai-research-*.tmp/\n"
    (other / ".gitignore").write_text(ignore, encoding="utf-8")
    output = other / "result"
    original = research_output._DirectoryPins.__enter__

    def different_device(pins: research_output._DirectoryPins) -> research_output._DirectoryPins:
        original(pins)
        if pins.root.name.startswith("sitai-research-"):
            handle, device, inode = pins.directories[pins.root]
            pins.directories[pins.root] = (handle, device + 1, inode)
        return pins

    if different_volume:
        monkeypatch.setattr(research_output._DirectoryPins, "__enter__", different_device)
    result = _invoke(raw, epoch, output)
    if success:
        assert result.exit_code == 0, result.output
        assert (output / "COMPLETE.json").is_file()
    else:
        assert result.exit_code != 0, result.output
        assert "必须被忽略" in result.output
        assert not output.exists()
    assert not list(other.glob(".sitai-research-*.tmp"))


def test_research_cannot_write_to_a_replaced_output_parent(
    capture: tuple[Path, Path, str, int], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pdx.information_catalog import InformationCatalog

    _root, raw, epoch, _count = capture
    parent = tmp_path / "parent"
    parent.mkdir()
    output = parent / "result"
    moved = tmp_path / "moved"
    original = InformationCatalog.write

    def swap(self: InformationCatalog, path: Path) -> None:
        try:
            parent.rename(moved)
        except OSError:
            original(self, path)
            return
        output.mkdir(parents=True)
        (output / "replacement.txt").write_bytes(b"keep")
        original(self, path)

    monkeypatch.setattr(InformationCatalog, "write", swap)
    result = _invoke(raw, epoch, output)
    if moved.exists():
        assert result.exit_code != 0, result.output
        assert {item.name for item in output.iterdir()} == {"replacement.txt"}
        assert (output / "replacement.txt").read_bytes() == b"keep"
    else:
        assert result.exit_code == 0, result.output
        assert (output / "COMPLETE.json").is_file()


def test_research_does_not_clean_a_replaced_destination(
    capture: tuple[Path, Path, str, int], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pdx.information_catalog import InformationCatalog

    _root, raw, epoch, _count = capture
    output = tmp_path / "result"
    moved = tmp_path / "moved"

    def swap_and_fail(_catalog: InformationCatalog, _path: Path) -> None:
        if output.exists():
            output.rename(moved)
        output.mkdir(exist_ok=True)
        (output / "replacement.txt").write_bytes(b"keep")
        raise OSError("synthetic write failure")

    monkeypatch.setattr(InformationCatalog, "write", swap_and_fail)
    result = _invoke(raw, epoch, output)
    assert result.exit_code != 0, result.output
    assert (output / "replacement.txt").read_bytes() == b"keep"
    assert not (output / "COMPLETE.json").exists()


def test_research_does_not_expose_directory_while_writing_products(
    capture: tuple[Path, Path, str, int], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, raw, epoch, _count = capture
    output = tmp_path / "result"
    products = {"information-catalog.json", "occurrences.sqlite"}
    observed = set()
    original = research_output._DirectoryPins.create_member

    def inspect(pins: research_output._DirectoryPins, parent: Path, name: str) -> int:
        if name in products:
            assert not output.exists()
            observed.add(name)
        return original(pins, parent, name)

    monkeypatch.setattr(research_output._DirectoryPins, "create_member", inspect)
    result = _invoke(raw, epoch, output)
    assert result.exit_code == 0, result.exception
    assert observed == products
    assert {path.name for path in output.iterdir()} == products | {"COMPLETE.json"}


@pytest.mark.parametrize("occupied", [False, True])
def test_research_never_overwrites_a_competing_directory(
    capture: tuple[Path, Path, str, int],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    occupied: bool,
) -> None:
    _root, raw, epoch, _count = capture
    output = tmp_path / "result"
    original = research_output.rename_no_replace
    competing_id = []

    def compete(
        source: Path,
        destination: Path,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        assert destination == output
        assert {path.name for path in source.iterdir()} == {
            "information-catalog.json",
            "occurrences.sqlite",
            "COMPLETE.json",
        }
        output.mkdir()
        competing_id.append(output.stat().st_ino)
        if occupied:
            (output / "replacement.txt").write_bytes(b"keep")
        original(source, destination, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr(research_output, "rename_no_replace", compete)
    result = _invoke(raw, epoch, output)
    assert result.exit_code != 0
    assert competing_id == [output.stat().st_ino]
    assert {item.name for item in output.iterdir()} == ({"replacement.txt"} if occupied else set())
    if occupied:
        assert (output / "replacement.txt").read_bytes() == b"keep"


@pytest.mark.parametrize("code", [errno.EXDEV, errno.ENOTSUP])
def test_research_refuses_unsupported_directory_publication(
    capture: tuple[Path, Path, str, int], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    _root, raw, epoch, _count = capture
    output = tmp_path / "result"

    def unsupported(_source: Path, _destination: Path, **_fds: int | None) -> None:
        raise OSError(code, "synthetic exclusive rename failure")

    monkeypatch.setattr(research_output, "rename_no_replace", unsupported)
    result = _invoke(raw, epoch, output)
    assert result.exit_code != 0
    assert "synthetic exclusive rename failure" in result.output
    assert not output.exists()


@pytest.mark.skipif(os.name != "posix", reason="Windows 固定父目录句柄后禁止并发移动")
def test_research_rename_uses_pinned_parent_after_last_check(
    capture: tuple[Path, Path, str, int], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, raw, epoch, _count = capture
    parent = tmp_path / "parent"
    parent.mkdir()
    output = parent / "result"
    moved = tmp_path / "moved"
    original = research_output.rename_no_replace

    def move_parent(
        source: Path,
        destination: Path,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        assert src_dir_fd is not None
        assert dst_dir_fd is not None
        parent.rename(moved)
        parent.mkdir()
        (parent / "keep").write_bytes(b"unrelated")
        original(source, destination, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr(research_output, "rename_no_replace", move_parent)
    result = _invoke(raw, epoch, output)
    assert result.exit_code != 0
    assert not output.exists()
    assert (parent / "keep").read_bytes() == b"unrelated"
    assert (moved / "result" / "information-catalog.json").is_file()
    assert not (moved / "result" / "COMPLETE.json").exists()


@pytest.mark.parametrize(("failed_fd", "replace_marker"), [(10, False), (11, False), (11, True)])
def test_research_revokes_only_its_own_marker_when_directory_sync_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_fd: int, replace_marker: bool
) -> None:
    stage = research_output._DirectoryPins(tmp_path / "stage")
    target = research_output._DirectoryPins(tmp_path)
    stage.kernel = target.kernel = None
    stage.directories[stage.root] = (10, 0, 0)
    target.directories[target.root] = (11, 0, 0)
    stage.root.mkdir()
    payload = stage.root / "payload"
    output = tmp_path / "result"
    final = output / "COMPLETE.json"

    def enter_payload(pins: research_output._DirectoryPins) -> research_output._DirectoryPins:
        state = pins.root.stat()
        pins.directories[pins.root] = (12, state.st_dev, state.st_ino)
        return pins

    def write_marker(
        pins: research_output._DirectoryPins, _files: tuple[tuple[Path, str], ...], marker: bytes
    ) -> os.stat_result:
        path = pins.root / "COMPLETE.json"
        path.write_bytes(marker)
        return path.stat()

    def moved(source: Path, destination: Path, **_fds: int | None) -> None:
        source.rename(destination)

    def sync(descriptor: int) -> None:
        if descriptor == failed_fd:
            if replace_marker:
                final.rename(output / "separate.json")
                final.write_bytes(b"external")
            raise OSError(errno.EIO, "synthetic directory sync failure")

    def marker_member(name: str, directory: int) -> Path:
        assert (name, directory) == ("COMPLETE.json", 12)
        return final

    def marker_stat(name: str, *, dir_fd: int, follow_symlinks: bool) -> os.stat_result:
        assert not follow_symlinks
        return marker_member(name, dir_fd).lstat()

    monkeypatch.setattr(research_output._DirectoryPins, "__enter__", enter_payload)
    monkeypatch.setattr(research_output._DirectoryPins, "check", lambda _pins: None)
    monkeypatch.setattr(
        research_output.LocalEvidenceOutput, "_write_stage", staticmethod(write_marker)
    )
    monkeypatch.setattr(research_output, "_mkdir_output_member", lambda path, _fd: path.mkdir())
    monkeypatch.setattr(research_output, "rename_no_replace", moved)
    monkeypatch.setattr(
        research_output,
        "os",
        SimpleNamespace(
            fsync=sync,
            path=os.path,
            stat=marker_stat,
            unlink=lambda name, *, dir_fd: marker_member(name, dir_fd).unlink(),
        ),
    )
    with pytest.raises(OSError, match="synthetic directory sync failure"):
        research_output.LocalEvidenceOutput(output, target)._publish_stage(
            stage, (), b"local marker"
        )

    assert not payload.exists()
    assert output.is_dir()
    if replace_marker:
        assert final.read_bytes() == b"external"
    else:
        assert not final.exists()
