"""Read every artifact byte without retaining an entire decoded document."""

from __future__ import annotations

import codecs
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def assert_utf8_no_bom(path: Path, *, name: str, chunk_bytes: int = 1 << 20) -> None:
    """Preserve strict whole-file UTF-8 validity, including a partial final sequence."""
    if chunk_bytes <= 0:
        raise ValueError("chunk_bytes must be positive")
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    with path.open("rb") as stream:
        prefix = stream.read(len(codecs.BOM_UTF8))
        assert not prefix.startswith(codecs.BOM_UTF8), f"{name} 不应带 BOM"
        decoder.decode(prefix)
        for chunk in iter(lambda: stream.read(chunk_bytes), b""):
            decoder.decode(chunk)
        decoder.decode(b"", final=True)
