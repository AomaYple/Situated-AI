"""Recheck preserved archive bytes using their historical manifest identities."""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
from pathlib import Path


def test_全部归档原字节在没有Git对象的源码副本可核验(tmp_path):
    source = Path(__file__).resolve().parents[1] / "docs/design/archive"
    target = tmp_path / "docs/design/archive"
    shutil.copytree(source, target)
    assert not (tmp_path / ".git").exists()

    total = 0
    for filename, expected in (
        ("manifest.json", "7534d0d45f7c1aa2ebefec699ece385f5d61cdf793332eda6c9b8318aca65440"),
        ("A2-manifest.json", "500f6b57180a9ae57a6977c26f8ee32c17a64b56543b3f79bc1a7fb7f0cbfbb9"),
    ):
        raw_manifest = (target / filename).read_bytes()
        assert hashlib.sha256(raw_manifest).hexdigest() == expected
        data = json.loads(raw_manifest)
        for item in data.get("files", data.get("originals", [])):
            commit = item.get("commit", data.get("commit"))
            # Independent original-byte observation, without the production decoder.
            raw = gzip.decompress(
                (target / "objects" / commit / f"{item['sha256']}.gz").read_bytes()
            )
            assert len(raw) == item["bytes"]
            assert hashlib.sha256(raw).hexdigest() == item["sha256"]
            total += 1
    assert total == 12
