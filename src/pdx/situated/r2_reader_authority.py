"""Pinned native bytes supporting the R2 readers and their scope arguments.

This is an independent authority declaration, not a cache of a local inventory.
The snapshot records static source evidence only; it proves no live game values,
active DLC or successful execution. Existing native baselines remain untouched.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from pdx import version_contracts

from . import production_profile

CURRENT_SOURCE_SHA256 = {
    **version_contracts.INSTALLATION_IDENTITY_SHA256,
    "game/common/ai_strategies/00_default_strategy.txt": "7fa4e018a796b1f1c04275e7fbc712ac39a4376e86db311f31079b12a8337760",
    "game/common/ai_strategies/01_admin_strategies.txt": "1ad973d0398acced05da72f6fe49e7b08d0a9c02f5406a694c69d789c4d6bffe",
    "game/common/ai_strategies/03_political_strategies.txt": "89b9878d2d8a7166549dcd62d6855de6a59eb6d4e4913823cc7a554f753dfab6",
    "game/common/alert_types/00_alert_types.txt": "74cbfaa21e54a8ca96be89aedf50b290baad2ca51e18825ceae70caad51a514a",
    "game/common/decrees/00_decree.txt": "0116013dac7fd94fe6c4f2bf6d5e0cb7220cdebb94827ad4ba5bffb500f25721",
    "game/common/diplomatic_actions/00_relations_actions.txt": "6cd5d572ae976a2e1f4f4af5c81fb577ed4804bace442e6fa31bace09881749b",
    "game/common/diplomatic_actions/01_expel_diplomats.txt": "634b87f8eb3a55d4742e5bf724d6b993c570736765898a97070cebea75893d4f",
    "game/common/diplomatic_actions/diplomatic_action.md": "9f146dd9e108d9753747efb1bf0671a18e19e728f6916a1fcd58c4d0b76fb69c",
    "game/common/journal_entries/06_portugal_politics.txt": "6b985f022065b56cca0ee6cb4bb238b662a0edb3ff7fb124b50154d0274788da",
    "game/common/journal_entries/08_tsarpoints.txt": "c118f0c75460674c0bc435dd45751ee21c2a484749d3816b21da915ff53715e0",
    "game/common/scripted_buttons/scripted_buttons.md": "596e62f265e277b5a7e9881d1f319ddea0af4189befc76eb9b96eba52a989b26",
    "game/common/scripted_triggers/05_tsarpoints_scripted_triggers.txt": "4d22469ebc817d730a0c5789b6e5bdfb0edc3087f417beb4e06f3322e3b98868",
}


def source_hashes() -> dict[str, str]:
    version_contracts.require_current()
    return CURRENT_SOURCE_SHA256


# Keep consumer policy out of this module. This maps the audited reader names
# to native sources so the adapter can verify its entire capability set.
READER_SOURCES = {
    "infrastructure": "game/common/decrees/00_decree.txt",
    "road-present": "game/common/decrees/00_decree.txt",
    "literacy": "game/common/ai_strategies/01_admin_strategies.txt",
    "bureaucracy": "game/common/scripted_buttons/scripted_buttons.md",
    "default": "game/common/alert_types/00_alert_types.txt",
    "school-agenda": "game/common/ai_strategies/03_political_strategies.txt",
    "protective": "game/common/diplomatic_actions/00_relations_actions.txt",
    "influence": "game/common/diplomatic_actions/01_expel_diplomats.txt",
    "target-interference": "game/common/diplomatic_actions/01_expel_diplomats.txt",
    "population": "game/common/ai_strategies/00_default_strategy.txt",
    "net-surplus": "game/common/journal_entries/06_portugal_politics.txt",
}


def reader_sources() -> dict[str, str]:
    return READER_SOURCES


def _manifest() -> dict[str, object]:
    return {
        "schema": "situated-ai.r2-reader-authority/1",
        "game_version": production_profile.expected_version(),
        "evidence_kind": "static_native_source",
        "runtime": "unknown",
        "files": [{"path": name, "sha256": sha} for name, sha in sorted(source_hashes().items())],
        "readers": dict(sorted(reader_sources().items())),
    }


def _read(root: Path, relative: str) -> bytes:
    path = root / relative
    if not path.is_file() or path.is_symlink() or path.resolve() != path.absolute():
        raise ValueError(f"R2 reader authority: missing or linked source {relative}")
    return path.read_bytes()


def _verified_bytes(root: Path) -> dict[str, bytes]:
    result = {}
    for relative, expected in source_hashes().items():
        raw = _read(root, relative)
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f"R2 reader authority: source drift {relative}")
        result[relative] = raw
    # Reuse the current strict version/build and original write-point contract.
    # Its source set is a subset of this independently pinned evidence closure.
    production_profile.load_profile(root)
    return result


def verify_installation(root: Path) -> dict[str, object]:
    """Reject live 1.15 identity or reader-evidence drift against reviewed bytes."""
    _verified_bytes(Path(root).resolve())
    return _manifest()
