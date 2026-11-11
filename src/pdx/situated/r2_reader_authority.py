"""Pinned native bytes supporting the R2 readers and their scope arguments.

This is an independent authority declaration, not a cache of a local inventory.
The snapshot records static source evidence only; it proves no live game values,
active DLC or successful execution. Existing native baselines remain untouched.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pdx import version_contracts

from . import production_profile

FROZEN_ROOT = Path(__file__).resolve().parents[3] / "research/vanilla-ai/1.15.0/r2-readers"
MANIFEST_NAME = "reader-authority-manifest.json"

# These hashes were measured from the identity-verified 1.15.0 installation.
# Changes require a new source review, not a manifest/hash refresh at generation.
SOURCE_SHA256 = {
    "binaries/checksum.txt": "7d1e8421e8f37c4cd71d3d6fa016e1f5730aef669c9eee786b1cfbce83a0a8d6",
    "caligula_branch.txt": "d63c818d818af02cdb1d59d338ca1b68420421ccdcf1b131193f58e191eb6ca8",
    "caligula_rev.txt": "41646ad1bb09180c7ce218ed46af8d9143c54dc3b69dfc0fba6254db65ad299d",
    "clausewitz_branch.txt": "673cffa83790df7106aa75435d0a8bee40d68c6cf5cfe6d47cd89df223ff2294",
    "clausewitz_rev.txt": "1085952c68b4ffa4ebab5d7ebd017e7a6492e22511494e0b371120a8f56a8107",
    "game/common/ai_strategies/00_default_strategy.txt": "83a9e8b7b568967ea9ae10df63ee18ed9b069ff69a5a31a23d35cc129b89ce73",
    "game/common/ai_strategies/01_admin_strategies.txt": "dd95f5586a9fb105adddf890612aa5b4f3970314855ba8a8cee42247db7ed741",
    "game/common/ai_strategies/03_political_strategies.txt": "2b0b83d06cc4ef8fb1bc58902ca4f90cf0723838afef6d81854e301f5f7c62f4",
    "game/common/alert_types/00_alert_types.txt": "ca60cb0f7425744d2695560d905f4ec58bbeb9dd3e6f1aedfcc891ceb23a55e3",
    "game/common/decrees/00_decree.txt": "3d2427216709844f4233649208efad0056b8a09608eb078249aeb6ff855c2445",
    "game/common/diplomatic_actions/00_relations_actions.txt": "6cd5d572ae976a2e1f4f4af5c81fb577ed4804bace442e6fa31bace09881749b",
    "game/common/diplomatic_actions/01_expel_diplomats.txt": "634b87f8eb3a55d4742e5bf724d6b993c570736765898a97070cebea75893d4f",
    "game/common/diplomatic_actions/diplomatic_action.md": "9f146dd9e108d9753747efb1bf0671a18e19e728f6916a1fcd58c4d0b76fb69c",
    "game/common/journal_entries/08_tsarpoints.txt": "db66b50a602e3951102f20be863c43681587026fe71afa821c13fc7b8b93e636",
    "game/common/scripted_buttons/scripted_buttons.md": "596e62f265e277b5a7e9881d1f319ddea0af4189befc76eb9b96eba52a989b26",
    "game/common/scripted_triggers/05_tsarpoints_scripted_triggers.txt": "4d22469ebc817d730a0c5789b6e5bdfb0edc3087f417beb4e06f3322e3b98868",
    "launcher/launcher-settings.json": "4b7032eeb5fc7f0f64b60690d5d2b1bbc4b7ca5119b44bb76eb2f7788a9fd91c",
}

SOURCE_SHA256_1151 = {
    "binaries/checksum.txt": "2dc9ed5946fe105d8143a3eebdd7a9d6417f0333ee468a3b81892a6ab6c60325",
    "caligula_branch.txt": "b9ed9070caf21333852ae4c658359e3babd04b9625dcf7146f6b32d99b45a565",
    "caligula_rev.txt": "9cb420ce9ae7ddde03ae8ced02cf2da9fcb7fe70b311877be6c98717e7a38b98",
    "clausewitz_branch.txt": "563a1baf6a4b11be321c25dbef63a2f9ffd6d3bf0888f3c74116579ac966508f",
    "clausewitz_rev.txt": "7b01c7e17e500a28904d6f00d5dcbbcaa6d5b23ac6ae55d8a9f4d176797697fd",
    "game/common/ai_strategies/00_default_strategy.txt": "38e7aadd1be9465f3ab423f61fa8e9e8206b8d98f523979e8e43c42cc18753ba",
    "game/common/ai_strategies/01_admin_strategies.txt": "1ad973d0398acced05da72f6fe49e7b08d0a9c02f5406a694c69d789c4d6bffe",
    "game/common/ai_strategies/03_political_strategies.txt": "2b0b83d06cc4ef8fb1bc58902ca4f90cf0723838afef6d81854e301f5f7c62f4",
    "game/common/alert_types/00_alert_types.txt": "ca60cb0f7425744d2695560d905f4ec58bbeb9dd3e6f1aedfcc891ceb23a55e3",
    "game/common/decrees/00_decree.txt": "3d2427216709844f4233649208efad0056b8a09608eb078249aeb6ff855c2445",
    "game/common/diplomatic_actions/00_relations_actions.txt": "6cd5d572ae976a2e1f4f4af5c81fb577ed4804bace442e6fa31bace09881749b",
    "game/common/diplomatic_actions/01_expel_diplomats.txt": "634b87f8eb3a55d4742e5bf724d6b993c570736765898a97070cebea75893d4f",
    "game/common/diplomatic_actions/diplomatic_action.md": "9f146dd9e108d9753747efb1bf0671a18e19e728f6916a1fcd58c4d0b76fb69c",
    "game/common/journal_entries/08_tsarpoints.txt": "16156cd6b66b6104f195fa1df382491ed751c11405d5868ee32911bc3ffe473c",
    "game/common/scripted_buttons/scripted_buttons.md": "596e62f265e277b5a7e9881d1f319ddea0af4189befc76eb9b96eba52a989b26",
    "game/common/scripted_triggers/05_tsarpoints_scripted_triggers.txt": "4d22469ebc817d730a0c5789b6e5bdfb0edc3087f417beb4e06f3322e3b98868",
    "launcher/launcher-settings.json": "e5719ec975d35fed526338c7e2176baeda126ad55a2bea38869d17f4a1a20d99",
}

SOURCE_SHA256_1151["game/common/journal_entries/06_portugal_politics.txt"] = (
    "6b985f022065b56cca0ee6cb4bb238b662a0edb3ff7fb124b50154d0274788da"
)


def frozen_root(version: str | None = None) -> Path:
    selected = (
        production_profile.expected_version()
        if version is None
        else version_contracts.active_version(version)
    )
    if selected not in {"1.15.0", "1.15.1"}:
        raise ValueError("R2 reader authority 仅支持 1.15.0 与 1.15.1")
    return production_profile.ROOT / "research/vanilla-ai" / selected / "r2-readers"


def source_hashes() -> dict[str, str]:
    return (
        SOURCE_SHA256_1151 if production_profile.expected_version() == "1.15.1" else SOURCE_SHA256
    )


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
}


def reader_sources() -> dict[str, str]:
    if production_profile.expected_version() != "1.15.1":
        return READER_SOURCES
    return {
        **READER_SOURCES,
        "population": "game/common/ai_strategies/00_default_strategy.txt",
        "net-surplus": "game/common/journal_entries/06_portugal_politics.txt",
    }


def _manifest() -> dict[str, object]:
    return {
        "schema": "situated-ai.r2-reader-authority/1",
        "game_version": production_profile.expected_version(),
        "evidence_kind": "static_native_source",
        "runtime": "unknown",
        "files": [{"path": name, "sha256": sha} for name, sha in sorted(source_hashes().items())],
        "readers": dict(sorted(reader_sources().items())),
    }


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"R2 reader authority: duplicate manifest key {key}")
        result[key] = value
    return result


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
    _verified_bytes(Path(root).absolute())
    return _manifest()


def verify_frozen(root: Path | None = None) -> dict[str, object]:
    """Verify the exact file set, manifest declaration and all frozen raw bytes."""
    root = (frozen_root() if root is None else Path(root)).absolute()
    raw = _read(root, MANIFEST_NAME)
    try:
        manifest = json.loads(raw, object_pairs_hook=_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("R2 reader authority: invalid manifest JSON") from exc
    expected = _manifest()
    if manifest != expected:
        raise ValueError("R2 reader authority: manifest differs from reviewed declaration")
    files = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if files != {*source_hashes(), MANIFEST_NAME}:
        raise ValueError("R2 reader authority: frozen file set mismatch")
    _verified_bytes(root)
    return expected


def capture(installation: Path, destination: Path | None = None) -> dict[str, object]:
    """Capture verified original bytes once, refusing every existing destination."""
    destination = (frozen_root() if destination is None else Path(destination)).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("R2 reader authority: capture destination already exists")
    originals = _verified_bytes(Path(installation).absolute())
    destination.mkdir(parents=True)
    for relative, raw in originals.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    (destination / MANIFEST_NAME).write_text(
        json.dumps(_manifest(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return verify_frozen(destination)
