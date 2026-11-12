"""Strict artifact text checks with bounded temporary byte and Unicode buffers."""

from __future__ import annotations

from pathlib import Path

import pytest
import test_golden as golden

pytestmark = pytest.mark.unit


def test_artifact_utf8_check_reads_in_bounded_chunks(monkeypatch, tmp_path):
    artifact = tmp_path / "complete.txt"
    artifact.write_bytes(b"a" * (1 << 20) + "尾部".encode())

    def whole_file_read(_path):
        pytest.fail("UTF-8 check retains the complete artifact byte buffer")

    monkeypatch.setattr(Path, "read_bytes", whole_file_read)
    golden.test_报告是合法UTF8且无乱码({"complete": artifact})


@pytest.mark.parametrize("chunk_bytes", [1, 2, 3, 4, 7])
@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"ASCII\r\n",
        "中文€😀末尾".encode(),
        b"abc" + b"\xef\xbb\xbf" + b"tail",
        b"valid\xffinvalid",
        b"abc\xe4\xb8",
        b"abc\xed\xa0\x80",
        b"abc\xf4\x90\x80\x80",
        b"abc\xc0\xaf",
        b"abc\x80",
    ],
)
def test_artifact_utf8_matches_complete_strict_decode(tmp_path, payload, chunk_bytes):
    from _artifact_text import assert_utf8_no_bom

    artifact = tmp_path / "text.txt"
    artifact.write_bytes(payload)
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError:
        with pytest.raises(UnicodeDecodeError):
            assert_utf8_no_bom(artifact, name="text", chunk_bytes=chunk_bytes)
    else:
        assert_utf8_no_bom(artifact, name="text", chunk_bytes=chunk_bytes)


@pytest.mark.parametrize("chunk_bytes", [1, 2, 3, 7])
def test_artifact_utf8_rejects_initial_bom(tmp_path, chunk_bytes):
    from _artifact_text import assert_utf8_no_bom

    artifact = tmp_path / "bom.txt"
    artifact.write_bytes(b"\xef\xbb\xbf" + "合法正文".encode())
    with pytest.raises(AssertionError, match="bom 不应带 BOM"):
        assert_utf8_no_bom(artifact, name="bom", chunk_bytes=chunk_bytes)


def test_artifact_utf8_rejects_invalid_bytes_after_multiple_chunks(tmp_path):
    from _artifact_text import assert_utf8_no_bom

    artifact = tmp_path / "bad-tail.txt"
    artifact.write_bytes(b"a" * 100 + b"\xff")
    with pytest.raises(UnicodeDecodeError):
        assert_utf8_no_bom(artifact, name="bad-tail", chunk_bytes=7)


def test_artifact_utf8_consumes_every_byte_with_bounded_reads(monkeypatch):
    import io

    from _artifact_text import assert_utf8_no_bom

    payload = ("首😀尾" * 9).encode()
    reads = []

    class TrackedStream(io.BytesIO):
        def read(self, size=-1):
            assert 0 < size <= 7
            chunk = super().read(size)
            reads.append(chunk)
            return chunk

    def open_stream(_path, mode):
        assert mode == "rb"
        return TrackedStream(payload)

    monkeypatch.setattr(Path, "open", open_stream)
    assert_utf8_no_bom(Path("all-bytes.txt"), name="all-bytes", chunk_bytes=7)
    assert b"".join(reads) == payload
    assert reads[-1] == b""
