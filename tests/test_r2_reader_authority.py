"""Reader authority survives neither source drift nor a rewritten manifest."""

from __future__ import annotations

import hashlib
import json
import shutil
from typing import TYPE_CHECKING

import pytest

from pdx import version_contracts
from pdx.situated import r2_reader_authority as authority

if TYPE_CHECKING:
    from pathlib import Path

EXPEL = "game/common/diplomatic_actions/01_expel_diplomats.txt"


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    destination = tmp_path / "snapshot"
    shutil.copytree(authority.FROZEN_ROOT, destination)
    return destination


def test_frozen_reader_authorities_cover_all_native_readers():
    # Import the adapter here, never from the authority module itself.
    from pdx.situated import network_profile

    manifest = authority.verify_frozen()
    assert manifest["game_version"] == "1.15.0"
    assert manifest["runtime"] == "unknown"
    assert {
        name: capability.source for name, capability in network_profile.READERS.items()
    } == authority.READER_SOURCES
    assert set(authority.READER_SOURCES.values()) <= authority.SOURCE_SHA256.keys()


@pytest.mark.parametrize(
    "relative",
    [EXPEL, "game/common/scripted_buttons/scripted_buttons.md", "caligula_rev.txt"],
)
def test_frozen_missing_authority_fails(snapshot: Path, relative: str):
    (snapshot / relative).unlink()
    with pytest.raises(ValueError, match="file set"):
        authority.verify_frozen(snapshot)


def test_changed_raw_bytes_fail_both_frozen_and_live_verification(snapshot: Path):
    source = snapshot / EXPEL
    source.write_bytes(source.read_bytes() + b"\n# changed reader evidence\n")
    with pytest.raises(ValueError, match="source drift"):
        authority.verify_frozen(snapshot)
    with pytest.raises(ValueError, match="source drift"):
        authority.verify_installation(snapshot)


def test_manifest_cannot_reauthorize_tampered_bytes(snapshot: Path):
    source = snapshot / EXPEL
    source.write_bytes(source.read_bytes() + b"\n# changed\n")
    path = snapshot / authority.MANIFEST_NAME
    manifest = json.loads(path.read_bytes())
    row = next(item for item in manifest["files"] if item["path"] == EXPEL)
    row["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="reviewed declaration"):
        authority.verify_frozen(snapshot)


def test_manifest_duplicate_key_is_rejected(snapshot: Path):
    path = snapshot / authority.MANIFEST_NAME
    raw = path.read_text(encoding="utf-8")
    path.write_text('{"runtime":"known",' + raw[1:], encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate manifest key"):
        authority.verify_frozen(snapshot)


def test_manifest_missing_or_invalid_is_rejected(snapshot: Path):
    path = snapshot / authority.MANIFEST_NAME
    path.unlink()
    with pytest.raises(ValueError, match="missing"):
        authority.verify_frozen(snapshot)
    path.write_bytes(b"not-json")
    with pytest.raises(ValueError, match="invalid manifest"):
        authority.verify_frozen(snapshot)


def test_undeclared_frozen_file_is_rejected(snapshot: Path):
    (snapshot / "unreviewed.txt").write_text("extra", encoding="utf-8")
    with pytest.raises(ValueError, match="file set"):
        authority.verify_frozen(snapshot)


def test_capture_is_reproducible_and_refuses_existing_destination(snapshot: Path, tmp_path: Path):
    destination = tmp_path / "captured"
    manifest = authority.capture(snapshot, destination)
    assert manifest == authority.verify_installation(snapshot)
    assert manifest == authority.verify_frozen(destination)
    assert (destination / authority.MANIFEST_NAME).read_bytes() == (
        authority.FROZEN_ROOT / authority.MANIFEST_NAME
    ).read_bytes()
    for relative in authority.SOURCE_SHA256:
        assert (destination / relative).read_bytes() == (snapshot / relative).read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        authority.capture(snapshot, destination)


def test_capture_rejects_live_drift_before_creating_output(snapshot: Path, tmp_path: Path):
    (snapshot / EXPEL).write_bytes(b"wrong source")
    destination = tmp_path / "not-created"
    with pytest.raises(ValueError, match="source drift"):
        authority.capture(snapshot, destination)
    assert not destination.exists()


def test_live_identity_drift_is_rejected(snapshot: Path):
    path = snapshot / "launcher/launcher-settings.json"
    document = json.loads(path.read_bytes())
    document["rawVersion"] = "1.15.1"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="source drift"):
        authority.verify_installation(snapshot)


@pytest.fixture(autouse=True)
def _historical_1150_contract():
    """Keep the exact archived witness under its original version identity."""
    with version_contracts.select_version("1.15.0"):
        yield
