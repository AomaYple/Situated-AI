"""Large immutable receipts may be compressed without weakening their identity."""

import gzip
import hashlib
import json

import pytest

from pdx.situated import architecture_receipts as receipts

pytestmark = pytest.mark.unit


def test_compressed_receipt_preserves_payload_and_raw_artifact_identity(tmp_path):
    payload = {"scope": ["真实原版", "unknown"], "denominator": 8856}
    raw = json.dumps(payload, ensure_ascii=False).encode()
    path = tmp_path / "native.json.gz"
    compressed = gzip.compress(raw, mtime=0)
    path.write_bytes(compressed)
    ref = {"path": path.name, "sha256": hashlib.sha256(compressed).hexdigest()}
    assert receipts._json(receipts._artifact(tmp_path, ref)) == payload
    path.write_bytes(gzip.compress(raw, mtime=1))
    with pytest.raises(ValueError, match="stale artifact"):
        receipts._artifact(tmp_path, ref)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b'{"same":1,"same":2}', "duplicate JSON key"),
        (b"[]", "JSON receipt must be an object"),
        (b"not JSON", "Expecting value"),
    ],
)
def test_compression_keeps_strict_json_contract(tmp_path, raw, message):
    path = tmp_path / "invalid.json.gz"
    path.write_bytes(gzip.compress(raw, mtime=0))
    with pytest.raises(ValueError, match=message):
        receipts._json(path)


@pytest.mark.parametrize(
    "raw",
    [
        b"not gzip",
        gzip.compress(b"{}", mtime=0)[:-4],
        b"\x1f\x8b\x08\x00" + b"\x00" * 6 + b"\xff" * 20,
    ],
)
def test_corrupt_compressed_evidence_fails_explicitly(tmp_path, raw):
    path = tmp_path / "corrupt.json.gz"
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="compressed"):
        receipts._json(path)
