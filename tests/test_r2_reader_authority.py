"""Current R2 authority binds readers to the reviewed native files."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pdx import config, distribution, version_contracts
from pdx.situated import network_profile, production_profile
from pdx.situated import r2_reader_authority as authority

EXPEL = "game/common/diplomatic_actions/01_expel_diplomats.txt"


def test_reader_authority_covers_all_adapter_readers_and_original_write_points():
    hashes = authority.source_hashes()
    assert {name: capability.source for name, capability in network_profile.READERS.items()} == (
        authority.reader_sources()
    )
    profile = production_profile.declared_profile()
    assert set(authority.reader_sources().values()) <= hashes.keys()
    assert dict(profile.source_hashes).items() <= hashes.items()
    assert version_contracts.INSTALLATION_IDENTITY_SHA256.items() <= hashes.items()


@pytest.mark.integration
def test_installed_reader_receipt_covers_reviewed_raw_bytes():
    receipt = authority.verify_installation(config.ROOT)
    assert receipt["game_version"] == version_contracts.CURRENT_VERSION
    assert receipt["evidence_kind"] == "static_native_source"
    assert receipt["runtime"] == "unknown"
    assert receipt["readers"] == authority.reader_sources()
    expected = [
        {
            "path": relative,
            "sha256": hashlib.sha256((config.ROOT / relative).read_bytes()).hexdigest(),
        }
        for relative in sorted(authority.source_hashes())
    ]
    assert receipt["files"] == expected


@pytest.mark.integration
@pytest.mark.parametrize("relative", sorted(authority.source_hashes()))
def test_materialization_rejects_drift_of_each_pinned_reader_or_identity_source(
    monkeypatch, relative
):
    target = (config.ROOT / relative).resolve()
    original_read = Path.read_bytes

    def read(path):
        return b"unreviewed reader or identity bytes" if path == target else original_read(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    with pytest.raises(ValueError, match="R2 reader authority: source drift") as error:
        distribution.check_profile_installation(production_profile.declared_profile())
    assert relative in str(error.value)


@pytest.mark.integration
@pytest.mark.parametrize(
    "relative", [EXPEL, "game/common/scripted_buttons/scripted_buttons.md", "caligula_rev.txt"]
)
def test_missing_live_authority_fails(monkeypatch, relative):
    target = (config.ROOT / relative).resolve()
    is_file = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda path: path != target and is_file(path))
    with pytest.raises(ValueError, match="missing or linked source") as error:
        authority.verify_installation(config.ROOT)
    assert relative in str(error.value)


@pytest.mark.integration
def test_local_manifest_cannot_reauthorize_tampered_reader_bytes(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    tampered = b"unreviewed reader authority"
    manifest = {
        "runtime": "verified",
        "files": [{"path": EXPEL, "sha256": hashlib.sha256(tampered).hexdigest()}],
    }
    (root / "reader-authority-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    read = authority._read

    def local_source(installation, relative):
        # Model a local manifest trust attempt after all earlier sources passed.
        assert installation == root
        if relative == EXPEL:
            return tampered
        return read(config.ROOT.resolve(), relative)

    monkeypatch.setattr(authority, "_read", local_source)
    with pytest.raises(ValueError, match="R2 reader authority: source drift") as error:
        authority.verify_installation(root)
    assert EXPEL in str(error.value)
