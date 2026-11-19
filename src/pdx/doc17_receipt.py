"""Reproduce the doc 17 observations without rewriting the frozen snapshot."""

import argparse
import hashlib
import json
import re
import tempfile
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, cast

from . import config, doc17, docgen, verify
from .doc_tables import spec_key, split_row
from .snapshot import SnapshotFormatError
from .version_contracts import (
    active_version,
    contract,
    require_current,
    verify_installation_identity,
)

if TYPE_CHECKING:
    from .snapshot import Snapshot

DOC = "17-角色科技与呈现.md"
OBSERVATIONS = {
    "doc17 §0 目录总览": (doc17._overview_table_rows, (2, 3)),
    "doc17 字段表1 common/dna_data": (doc17._dna_field_rows, (2,)),
}
TABLE_KEYS = frozenset(f"{DOC}::{name}" for name in OBSERVATIONS)


def _path() -> Path:
    return config.RESEARCH / f"doc17-observation-{active_version()}.json"


def _source_identities(snap: Snapshot) -> dict[str, doc17.SourceIdentity]:
    """Project original bytes and the reviewed status policy for live capture."""
    prefixes = tuple(f"game/common/{name}/" for name in doc17.OVERVIEW_DIRS)
    identities: dict[str, doc17.SourceIdentity] = {}
    partial_paths = set()
    for path, raw_identity in snap.sections.get("source_identity", {}).items():
        if not path.startswith(prefixes) or not path.endswith(".txt"):
            continue
        members = sorted(raw_identity)
        if (
            len(members) != 2
            or re.fullmatch(r"sha256:[0-9a-f]{64}", members[0]) is None
            or re.fullmatch(r"size:(0|[1-9][0-9]*)", members[1]) is None
        ):
            raise SnapshotFormatError(f"doc17 冻结来源原字节身份无效：{path}")
        digest = members[0].removeprefix("sha256:")
        size = int(members[1].removeprefix("size:"))
        frozen = doc17.FROZEN_PARTIAL_DNA_SHA256.get(path.removeprefix("game/common/"))
        if frozen is not None:
            if digest != frozen:
                raise SnapshotFormatError(f"doc17 冻结部分原件 SHA-256 不符：{path}")
            partial_paths.add(path)
        status = "partial" if frozen is not None else "complete"
        identities[path] = (digest, size, status)
    if partial_paths != {f"game/common/{path}" for path in doc17.FROZEN_PARTIAL_DNA_SHA256}:
        raise SnapshotFormatError("doc17 冻结 DNA 部分解析文件分母不符")
    if not all(any(path.startswith(prefix) for path in identities) for prefix in prefixes):
        raise SnapshotFormatError("doc17 冻结目录分母不完整")
    return identities


def _metadata(snap: Snapshot, identities: dict[str, doc17.SourceIdentity]) -> dict[str, object]:
    encoded = json.dumps(identities, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "schema_version": 1,
        "game_identity": snap.version,
        "source_identity_sha256": hashlib.sha256(encoded).hexdigest(),
        "complete_files": sum(status == "complete" for _, _, status in identities.values()),
        "partial_files": sum(status == "partial" for _, _, status in identities.values()),
    }


def capture(snap: Snapshot) -> dict[str, object]:
    """Render both tables from the same files whose identity is verified below."""
    snap.require_version(require_current(active_version()))
    verify_installation_identity(config.ROOT)
    expected = _source_identities(snap)
    target = config.docs_root() / DOC
    rows = {}
    for spec in doc17.doc_table_specs():
        observation = OBSERVATIONS.get(spec.name)
        if observation is None:
            continue
        cells, _ = observation
        observed: dict[str, doc17.SourceIdentity] = {}
        measured = cells(observed)
        expected_for_table = expected
        if cells is doc17._dna_field_rows:
            expected_for_table = {
                path: identity
                for path, identity in expected.items()
                if path.startswith("game/common/dna_data/")
            }
        drift = sorted(
            path
            for path in observed.keys() | expected_for_table.keys()
            if observed.get(path) != expected_for_table.get(path)
        )
        if drift:
            raise SnapshotFormatError("doc17 现读来源与冻结文件分母不符：" + ", ".join(drift))
        rows[spec_key(DOC, spec)] = docgen._render_one(
            target, replace(spec, cells=partial(list, measured))
        )
    metadata = _metadata(snap, expected)
    _validate_table_values(metadata, rows)
    return {**metadata, "tables": rows}


def _table_value_identity(metadata: dict[str, object], tables: object) -> str:
    """Bind generated cells to their source projection, ignoring author-owned columns."""
    if not isinstance(tables, dict) or tables.keys() != TABLE_KEYS:
        raise SnapshotFormatError("doc17 统计收据表分母不符")
    values: dict[str, dict[str, list[str]]] = {}
    for spec in doc17.doc_table_specs():
        observation = OBSERVATIONS.get(spec.name)
        if observation is None:
            continue
        cells, columns = observation
        key = spec_key(DOC, spec)
        rows = tables[key]
        width = len(split_row(spec.header))
        if (
            not isinstance(rows, list)
            or not rows
            or not all(isinstance(row, str) and len(split_row(row)) == width for row in rows)
        ):
            raise SnapshotFormatError(f"doc17 统计收据行无效：{spec.name}")
        keyed = {
            row[spec.key_column].strip("`"): [row[column] for column in columns]
            for row in map(split_row, rows)
        }
        expected_keys = (
            {"portrait_info", "enabled", "dna"}
            if cells is doc17._dna_field_rows
            else set(doc17.OVERVIEW_DIRS)
        )
        if len(rows) != len(expected_keys) or keyed.keys() != expected_keys:
            raise SnapshotFormatError(f"doc17 统计收据行分母不符：{spec.name}")
        values[key] = keyed
    encoded = json.dumps(
        {**metadata, "table_values": values},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_table_values(metadata: dict[str, object], tables: object) -> None:
    if _table_value_identity(metadata, tables) != contract().doc17_table_values_sha256:
        raise SnapshotFormatError("doc17 统计收据与版本合同的冻结表值身份不符")


def load(snap: Snapshot) -> dict[str, list[str]]:
    """Check the archived derivative against its precise frozen source projection."""
    snap.require_version()
    path = _path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SnapshotFormatError(f"doc17 统计收据无法读取：{path}") from exc
    expected = _metadata(snap, _source_identities(snap))
    if (
        not isinstance(payload, dict)
        or payload.keys() != {*expected, "tables"}
        or any(payload[key] != value for key, value in expected.items())
    ):
        raise SnapshotFormatError("doc17 统计收据与冻结来源身份不符")
    tables = payload["tables"]
    _validate_table_values(expected, tables)
    return cast("dict[str, list[str]]", tables)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="生成当前版本的 doc17 统计收据")
    args = parser.parse_args()
    if not args.write:
        parser.error("需要显式指定 --write")
    require_current(active_version())
    snap = verify.latest_compact_snapshot()
    if snap is None:
        parser.error("缺少当前冻结安装快照")
    payload = capture(snap)
    path = _path()
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as stream:
        temporary = Path(stream.name)
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
