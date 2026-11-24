"""Freeze original D01.budget diagnostic Mod archives without the production package path."""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from pdx.model import Block
from pdx.parser import parse_text
from pdx.textio import text_bytes
from pdx.version_contracts import CURRENT_VERSION

SOURCE = Path(__file__).resolve().parent
ARMS = ("a", "b", "calibration", "observer")
STRATEGY = "ai_strategy_agricultural_expansion"
FIELD = "economic_vs_government_spending_balance"
SCRIPT = "common/ai_strategies/zz_sitai_d01_budget.txt"
OBSERVER = "common/scripted_effects/sitai_d01_observe_budget.txt"
DECISION_OBSERVER_MEMBERS = {
    "common/decisions/sitai_d01_budget_observer.txt": "sitai_d01_budget_observer_decision",
    "common/journal_entries/sitai_d01_budget_observer.txt": "je_sitai_d01_budget_observer",
    "common/scripted_effects/sitai_d01_budget_observer.txt": "sitai_d01_budget_log_conditions",
}
DECISION_OBSERVER_LOCALIZATION = "localization/english/sitai_d01_budget_observer_l_english.yml"


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


def decision_observer_members() -> dict[str, bytes]:
    source = SOURCE / "decision_observer"
    members = {}
    for path in (*DECISION_OBSERVER_MEMBERS, DECISION_OBSERVER_LOCALIZATION):
        script = (source / path).read_bytes().decode("utf-8")
        if script.startswith("\ufeff") or "\r" in script:
            raise ValueError(f"{path}: expected UTF-8 without BOM and with LF")
        if path in DECISION_OBSERVER_MEMBERS:
            parsed = parse_text(script, path=path)
            parsed.require_complete()
            if len(parsed.root.items) != 1 or parsed.root.keys() != [
                DECISION_OBSERVER_MEMBERS[path]
            ]:
                raise ValueError(f"{path}: expected one original definition")
        members[path] = text_bytes(script, game=True)
    metadata = {
        "name": "Situated AI D01 Budget Decision Observer",
        "id": "sitai-d01-budget-decision-observer",
        "version": "0.0.1",
        "supported_game_version": CURRENT_VERSION,
        "short_description": "Single-player diagnostic for AI Mingrelia budget conditions.",
        "tags": [],
        "relationships": [],
        "game_custom_data": {"multiplayer_synchronized": False},
    }
    members[".metadata/metadata.json"] = text_bytes(json.dumps(metadata, indent=2) + "\n")
    return members


def freeze_archives(output: Path, arms: dict[str, dict[str, bytes]]) -> dict[str, dict[str, str]]:
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
            if archive.namelist() != sorted(members) or archive.testzip() is not None:
                raise ValueError(f"{arm}: archive member list or CRC differs from the probe")
            if any(archive.read(name) != raw for name, raw in members.items()):
                raise ValueError(f"{arm}: archive readback differs from the probe")
        manifest[archive_path.name] = {
            "sha256": sha256(archive_path.read_bytes()).hexdigest(),
            **{name: sha256(raw).hexdigest() for name, raw in members.items()},
        }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return manifest


def freeze(output: Path) -> dict[str, dict[str, str]]:
    return freeze_archives(output, {arm: archive_members(arm) for arm in ARMS})


def freeze_decision_observer(output: Path) -> dict[str, dict[str, str]]:
    return freeze_archives(output, {"decision-observer": decision_observer_members()})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new output directory")
    parser.add_argument(
        "--decision-observer", action="store_true", help="freeze only the decision observer"
    )
    arguments = parser.parse_args()
    build = freeze_decision_observer if arguments.decision_observer else freeze
    print(json.dumps(build(arguments.output), indent=2))
