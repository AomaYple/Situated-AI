"""Freeze original D01.budget diagnostic Mod archives without the production package path."""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from pdx.model import Block
from pdx.parser import parse_text
from pdx.version_contracts import CURRENT_VERSION

SOURCE = Path(__file__).resolve().parent
ARMS = ("a", "b", "calibration", "observer")
STRATEGY = "ai_strategy_agricultural_expansion"
FIELD = "economic_vs_government_spending_balance"
SCRIPT = "common/ai_strategies/zz_sitai_d01_budget.txt"
OBSERVER = "common/scripted_effects/sitai_d01_observe_budget.txt"


def archive_members(arm: str) -> dict[str, bytes]:
    raw = (SOURCE / f"{arm}.txt").read_bytes()
    script = raw.decode("utf-8")
    parsed = parse_text(script)
    parsed.require_complete()
    if script.startswith("\ufeff") or "\r" in script:
        raise ValueError(f"{arm}: expected UTF-8 without BOM and with LF")
    if arm == "observer":
        if parsed.root.keys() != ["sitai_d01_observe_budget"] or len(parsed.root.items) != 1:
            raise ValueError("observer: expected one original scripted effect")
        script_path = OBSERVER
    else:
        strategy = parsed.root.first(STRATEGY)
        if (
            len(parsed.root.items) != 1
            or strategy is None
            or strategy.prefix != "INJECT"
            or not isinstance(strategy.value, Block)
        ):
            raise ValueError(f"{arm}: expected the existing agricultural strategy")
        if len(strategy.value.items) != 1 or strategy.value.keys() != [FIELD]:
            raise ValueError(f"{arm}: expected only the budget field")
        script_path = SCRIPT
    metadata = {
        "name": f"Situated AI D01 Budget Probe {arm.upper()}",
        "id": f"sitai-d01-budget-{arm}",
        "version": "0.0.1",
        "supported_game_version": CURRENT_VERSION,
        "short_description": "Single-player diagnostic for an existing AI strategy field.",
        "tags": [],
        "relationships": [],
        "game_custom_data": {"multiplayer_synchronized": False},
    }
    return {
        ".metadata/metadata.json": (json.dumps(metadata, indent=2) + "\n").encode("utf-8"),
        script_path: script.encode("utf-8-sig"),
    }


def freeze(output: Path) -> dict[str, dict[str, str]]:
    arms = {arm: archive_members(arm) for arm in ARMS}
    output.mkdir()
    manifest = {}
    for arm, members in arms.items():
        archive_path = output / f"sitai-d01-budget-{arm}.zip"
        with ZipFile(archive_path, "x", compression=ZIP_STORED) as archive:
            for name, raw in sorted(members.items()):
                entry = ZipInfo(name)
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, raw)
        with ZipFile(archive_path) as archive:
            actual = {name: archive.read(name) for name in archive.namelist()}
            if archive.testzip() is not None or actual != members:
                raise ValueError(f"{arm}: archive readback differs from the probe")
        manifest[archive_path.name] = {
            "sha256": sha256(archive_path.read_bytes()).hexdigest(),
            **{name: sha256(raw).hexdigest() for name, raw in members.items()},
        }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new output directory")
    arguments = parser.parse_args()
    print(json.dumps(freeze(arguments.output), indent=2))
