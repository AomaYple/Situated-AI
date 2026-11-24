"""Render the original D09 diagnostic overlays outside the production tree."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

GOODS = ("oil", "radios", "telephones")
ARMS = (
    "fixture-base",
    "fixture-repeat-field",
    "fixture-repeat-good",
    "fixture-positive",
    "fixture-first-round",
    "native-base",
    "native-flag",
    "native-market",
)
FIXTURE = "sitai_d09_fixture"
REPEAT = "sitai_d09_repeat"
CLEAN = "sitai_d09_clean"
REFERENCE = "sitai_d09_reference"
SHADOW = "sitai_d09_shadow"
BASE_FLAG = "has_variable = sitai_d09_base"
ADDED_FLAG = "is_ai = yes has_variable = sitai_d09_added"
ICON = '"gfx/interface/icons/ai_strategy_icons/placate_population.dds"'


def entry(good: str, stance: str, trigger: str = "") -> str:
    condition = f" trigger = {{ {trigger} }}" if trigger else ""
    return f"{good} = {{ stance = {stance}{condition} }}"


def field(*entries: str) -> str:
    return "goods_stances = {\n\t\t" + "\n\t\t".join(entries) + "\n\t}"


def strategy(name: str, *fields: str) -> str:
    body = (
        f"icon = {ICON}",
        "type = administrative",
        f"possible = {{ is_ai = yes has_variable = {name}_on }}",
        "weight = { value = 10000 }",
        *fields,
    )
    return f"{name} = {{\n\t" + "\n\t".join(body) + "\n}\n"


def inject(name: str, *entries: str) -> str:
    return f"INJECT:{name} = {{\n\t{field(*entries)}\n}}\n"


def scarcity(good: str) -> str:
    return (
        "is_ai = yes exists = market "
        f"market = {{ exists = mg:{good} mg:{good} = {{ "
        "market_goods_pricier > 0.25 market_goods_delta < 0 } }"
    )


def observe(good: str) -> str:
    # Recompute flags even after reloading an earlier sample or changing control.
    return (
        "sitai_d09_sample_market = {\n"
        "\tset_variable = { name = sitai_d09_sampled value = 1 }\n"
        "\tremove_variable = sitai_d09_sample_available\n"
        "\tremove_variable = sitai_d09_sample_scarce\n"
        "\tif = {\n"
        "\t\tlimit = { exists = market "
        f"market = {{ exists = mg:{good} }} }}\n"
        "\t\tset_variable = { name = sitai_d09_sample_available value = 1 }\n"
        "\t}\n"
        "\tif = {\n"
        f"\t\tlimit = {{ {scarcity(good)} }}\n"
        "\t\tset_variable = { name = sitai_d09_sample_scarce value = 1 }\n"
        "\t}\n"
        "}\n"
    )


def render(arm: str, good: str) -> dict[str, str]:
    if arm not in ARMS or good not in GOODS:
        raise ValueError("Unknown D09 diagnostic arm or good")

    base = entry(good, "wants_high_supply", BASE_FLAG)
    base_sentinel = entry("porcelain", "wants_high_supply")
    added = entry(good, "wants_high_supply", ADDED_FLAG)
    added_sentinel = entry("fine_art", "wants_export", "is_ai = yes")
    files = {
        ".metadata/metadata.json": json.dumps(
            {
                "name": f"D09 diagnostic {good} {arm}",
                "id": f"sitai-d09-diagnostic-{good}-{arm}",
                "version": "0.1.0",
                "supported_game_version": "1.15.2",
                "short_description": "Isolated D09 diagnostic",
                "tags": [],
                "relationships": [],
                "game_custom_data": {},
            },
            indent=2,
        )
        + "\n",
        "common/scripted_effects/sitai_d09_sample.txt": observe(good),
    }
    fixture_fields = [field(base, base_sentinel)]
    if arm == "fixture-repeat-good":
        fixture_fields = [field(base, base_sentinel, added, added_sentinel)]
    if arm in {"fixture-positive", "fixture-first-round"}:
        union = entry(good, "wants_high_supply", f"OR = {{ {BASE_FLAG} AND = {{ {ADDED_FLAG} }} }}")
        fixture_fields = [field(union, base_sentinel, added_sentinel)]
    files["common/ai_strategies/sitai_d09_00_strategies.txt"] = "\n".join(
        (
            strategy(FIXTURE, *fixture_fields),
            strategy(CLEAN),
            strategy(REFERENCE, field(added_sentinel)),
            strategy(SHADOW, field(entry(good, "wants_export", "is_ai = yes"))),
        )
    )
    if arm == "fixture-first-round":
        files["common/ai_strategies/sitai_d09_01_repeat.txt"] = strategy(
            REPEAT, field(base, base_sentinel, added, added_sentinel)
        )
    if arm == "fixture-repeat-field":
        files["common/ai_strategies/sitai_d09_99_inject.txt"] = inject(
            FIXTURE, added, added_sentinel
        )
    if arm in {"native-flag", "native-market"}:
        predicate = ADDED_FLAG if arm == "native-flag" else scarcity(good)
        probe = "has_variable = sitai_d09_native_probe"
        trigger = f"{probe} {predicate}"
        files["common/ai_strategies/sitai_d09_99_inject.txt"] = inject(
            "ai_strategy_default",
            entry(good, "wants_high_supply", trigger),
            entry("fine_art", "wants_export", f"is_ai = yes {probe}"),
        )
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arm", choices=ARMS)
    parser.add_argument("good", choices=GOODS)
    parser.add_argument("output", type=Path, help="New diagnostic directory under tools/out")
    args = parser.parse_args()
    diagnostics = Path(__file__).resolve().parents[3] / "tools" / "out"
    output = args.output.resolve()
    if diagnostics not in output.parents:
        parser.error(f"Output must be inside {diagnostics}")
    output.mkdir(parents=True, exist_ok=False)
    for name, source in render(args.arm, args.good).items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        encoding = "utf-8-sig" if path.suffix == ".txt" else "utf-8"
        path.write_text(source, encoding=encoding, newline="\n")


if __name__ == "__main__":
    main()
