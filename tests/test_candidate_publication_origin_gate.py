"""Executable synthetic proof of the proposed publication origin check."""

import io
import json
import zipfile
from dataclasses import asdict, dataclass
from hashlib import sha256

import pytest

from pdx.distribution import _validate_paths


@dataclass(frozen=True)
class Origin:
    path: str
    payload_sha256: str
    disposition: str
    evidence_sha256: str


def digest(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def make_archive(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for path, payload in files.items():
            archive.writestr(zipfile.ZipInfo(path), payload)
    return output.getvalue()


def attestation(archive: bytes, source: str, source_lock: bytes, rows: list[Origin]) -> str:
    document = {
        "archive_sha256": digest(archive),
        "source_commit": source,
        "generation_lock_sha256": digest(source_lock),
        "origins": [asdict(row) for row in sorted(rows, key=lambda row: row.path)],
    }
    return digest(json.dumps(document, sort_keys=True, separators=(",", ":")).encode())


def public_payload_gate(
    archive: bytes,
    source: str,
    source_lock: bytes,
    rows: list[Origin],
    trusted_attestation: str,
) -> None:
    paths = [row.path for row in rows]
    _validate_paths(paths)
    if attestation(archive, source, source_lock, rows) != trusted_attestation:
        raise ValueError("origin attestation changed")
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        members = bundle.namelist()
        _validate_paths(members)
        if set(paths) != set(members):
            raise ValueError("incomplete origin coverage")
        for row in rows:
            if row.payload_sha256 != digest(bundle.read(row.path)):
                raise ValueError(f"payload bytes changed: {row.path}")
            if row.disposition != "original":
                raise ValueError(f"{row.disposition}: {row.path}")


class TestSyntheticOriginGate:
    source = "a" * 40
    lock = b"fixture generation identity"
    path = "common/shared.txt"
    original = b"newly authored local fixture"
    evidence = digest(b"fixture source review")

    def check(self, files: dict[str, bytes], rows: list[Origin]) -> None:
        archive = make_archive(files)
        expected = attestation(archive, self.source, self.lock, rows)
        public_payload_gate(archive, self.source, self.lock, rows, expected)

    def test_original_at_stock_path_can_publish_and_retry(self) -> None:
        files = {self.path: self.original}
        rows = [Origin(self.path, digest(self.original), "original", self.evidence)]
        self.check(files, rows)
        self.check(files, rows)

    def test_retained_native_content_even_at_another_path(self) -> None:
        files = {"common/new.txt": b"synthetic retained stock fixture and a new field"}
        rows = [
            Origin(path, digest(raw), "retained_native", self.evidence)
            for path, raw in files.items()
        ]
        with pytest.raises(ValueError, match="retained_native"):
            self.check(files, rows)

    def test_missing_unknown_and_path_aliases_fail(self) -> None:
        files = {self.path: self.original}
        valid = Origin(self.path, digest(self.original), "original", self.evidence)
        with pytest.raises(ValueError, match="incomplete origin coverage"):
            self.check(files, [])
        with pytest.raises(ValueError, match="unknown"):
            self.check(files, [Origin(self.path, digest(self.original), "unknown", self.evidence)])
        for alias in (self.path, self.path.upper(), "common/../shared.txt"):
            with pytest.raises(ValueError):
                self.check(
                    files, [valid, Origin(alias, valid.payload_sha256, "original", self.evidence)]
                )

    def test_retry_detects_replaced_archive_lock_payload_or_review(self) -> None:
        files = {self.path: self.original}
        archive = make_archive(files)
        rows = [Origin(self.path, digest(self.original), "original", self.evidence)]
        expected = attestation(archive, self.source, self.lock, rows)
        variants = (
            (make_archive({self.path: b"different payload"}), self.source, self.lock, rows),
            (archive, "b" * 40, self.lock, rows),
            (archive, self.source, b"different lock", rows),
            (
                archive,
                self.source,
                self.lock,
                [
                    Origin(
                        self.path, rows[0].payload_sha256, "original", digest(b"different review")
                    )
                ],
            ),
        )
        for candidate, source, lock, reviewed in variants:
            with pytest.raises(ValueError):
                public_payload_gate(candidate, source, lock, reviewed, expected)

    def test_independent_attestation_still_needs_exact_member_bytes(self) -> None:
        with pytest.raises(ValueError, match="payload bytes changed"):
            self.check(
                {self.path: self.original},
                [Origin(self.path, digest(b"old fixture"), "original", self.evidence)],
            )
