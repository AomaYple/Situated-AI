"""Current package inputs and frozen output checks."""

from __future__ import annotations

import hashlib
import json

import pytest

from pdx import config, decisions, distribution
from pdx.situated import network_profile, production_profile, r2_reader_authority


@pytest.mark.integration
def test_current_delivery_is_deterministic_and_includes_its_thumbnail():
    _, _, files = distribution.package_inputs()
    assert distribution.package_inputs()[2] == files
    metadata = json.loads(files[distribution.METADATA_NAME])
    thumbnail = metadata["picture"]
    assert thumbnail == distribution.THUMBNAIL_NAME
    assert files[thumbnail] == (decisions.PRODUCT / thumbnail).read_bytes()
    assert all("probe" not in name.lower() for name in files)


def test_standard_lock_pins_policy_reader_authority_and_actual_source_bytes():
    lock = json.loads(distribution.generation_lock({}))
    for source in (
        production_profile.declaration_path(),
        network_profile.source_path(),
        config.REPO / "src/pdx/situated/r2_reader_authority.py",
    ):
        relative = source.relative_to(config.REPO).as_posix()
        assert lock["sources"][relative] == hashlib.sha256(source.read_bytes()).hexdigest()
    # Exact installed reader bytes are verified at materialization, while the
    # standard generation lock pins the Python declaration that authorizes them.
    assert {source for source in lock["sources"] if source.startswith("game/")} == set()
    assert r2_reader_authority.source_hashes()
