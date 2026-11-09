"""Delivery checks for the frozen 1.15 production profile."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from pdx import config, distribution
from pdx.situated import production_profile


@pytest.fixture
def profile() -> production_profile.ProductionProfile:
    production_profile.verify_baseline()
    return production_profile.load_profile(production_profile.BASELINE_ROOT)


def test_policy_profile_is_deterministic_and_has_no_missing_thumbnail(profile):
    first = distribution.profile_outputs(profile)
    second = distribution.profile_outputs(profile)
    assert first == second
    metadata = json.loads(first[distribution.METADATA_NAME])
    assert metadata["game_custom_data"]["policy"] == "policy"
    assert metadata["picture"] == ""
    assert distribution.THUMBNAIL_NAME not in first
    assert any(
        "SITAI POLICY 1.15.0 BEGIN" in value for value in first.values() if isinstance(value, str)
    )


def test_profile_lock_covers_policy_source(profile):
    files = distribution.profile_outputs(profile)
    lock = json.loads(distribution.profile_generation_lock(profile, files))
    assert "mod/decisions/architecture_115.toml" in lock["sources"]
    assert "mod/decisions/policy_115.toml" in lock["sources"]
    assert "research/vanilla-ai/1.15.0/native/baseline-manifest.json" in lock["sources"]


def test_profile_write_rejects_extras_and_preserves_existing_output(profile, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUT", tmp_path / "out")
    distribution.write_profile_outputs(profile)
    root = distribution.profile_output_root()
    before = {
        path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }
    (root / "unexpected.txt").write_text("extra", encoding="utf-8")
    with pytest.raises(ValueError, match="额外文件"):
        distribution.write_profile_outputs(profile)
    after = {
        path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }
    assert after == {**before, Path("unexpected.txt"): b"extra"}


def test_profile_check_detects_tamper_and_package_requires_checked_output(
    profile, tmp_path, monkeypatch
):
    monkeypatch.setattr(config, "OUT", tmp_path / "out")
    files = distribution.profile_outputs(profile)
    with pytest.raises(ValueError, match="不存在"):
        distribution.check_profile_outputs(profile)
    distribution.write_profile_outputs(profile)
    checked = distribution.check_profile_outputs(profile)
    metadata = cast("str", files[distribution.METADATA_NAME])
    assert checked[distribution.METADATA_NAME] == metadata.encode("utf-8")
    metadata_path = distribution.profile_output_root() / distribution.METADATA_NAME
    metadata_path.write_text(
        metadata_path.read_text(encoding="utf-8").replace(
            '"policy": "policy"', '"policy": "tampered"'
        ),
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(ValueError, match="漂移"):
        distribution.profile_package(tmp_path / "profile.zip", profile)


def test_profile_write_rolls_back_when_generation_lock_drifts(profile, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUT", tmp_path / "out")
    root = distribution.profile_output_root()
    metadata_path = root / distribution.METADATA_NAME
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_bytes(b"preexisting metadata bytes\n")
    before = {
        path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }

    original_lock = distribution.profile_generation_lock
    calls = 0

    def drifting_lock(profile_arg, files=None):
        nonlocal calls
        calls += 1
        lock = original_lock(profile_arg, files)
        return lock + "drift\n" if calls == 2 else lock

    monkeypatch.setattr(distribution, "profile_generation_lock", drifting_lock)
    with pytest.raises(ValueError, match="源码发生漂移"):
        distribution.write_profile_outputs(profile)

    after = {
        path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }
    assert after == before
