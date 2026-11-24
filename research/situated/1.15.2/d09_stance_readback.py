"""Read a country's serialized AI strategy and indexed stance cache in a text save."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import BinaryIO

SECTION = re.compile(r"([a-z_]+)=\{$")
BRACES = re.compile(r'"(?:\\.|[^"\\])*"|#[^\r\n]*|[{}]')
RECORD = re.compile(r"([0-9]+)=\{$")
SECTIONS = {"ai", "country_manager", "market_manager", "player_manager"}


def read_save(source: BinaryIO, country: str) -> dict[str, object]:
    header = source.readline()
    if not header.startswith(b"SAV"):
        raise ValueError("Expected a Victoria 3 local text save with a SAV header")
    digest = hashlib.sha256(header)
    records: dict[str, list[tuple[int, dict[str, list[str]]]]] = {name: [] for name in SECTIONS}
    fields: dict[str, list[str]] | None = None
    record_id = 0
    record_depth = 0
    ai_block = ""
    depth = 0
    section = ""
    date = ""
    for raw in source:
        digest.update(raw)
        line = raw.rstrip(b"\r\n").decode("utf-8")
        if line.startswith("\tgame_date=") and not date:
            date = line.partition("=")[2]
        if not section:
            match = SECTION.fullmatch(line)
            if match and match[1] in SECTIONS:
                section = match[1]
                depth = 1
            continue

        previous_depth = depth
        if "{" in line or "}" in line:
            for token in BRACES.findall(line):
                depth += (token == "{") - (token == "}")
        if depth == 0:
            section = ""
        elif previous_depth == 2 and (match := RECORD.fullmatch(line)):
            record_id = int(match[1])
            record_depth = depth
            fields = {}
            ai_block = ""
        elif fields is not None:
            if depth < record_depth:
                records[section].append((record_id, fields))
                fields = None
            elif "=" in line:
                key, _, value = line.partition("=")
                if previous_depth == record_depth:
                    if section == "ai":
                        ai_block = key.strip()
                    if key in {"\tdefinition", "\tmarket", "\tcountry", "\towner", "\tenabled"}:
                        fields.setdefault(key, []).append(value)
                if section == "ai" and previous_depth == record_depth + 1:
                    if ai_block == "ai_strategy" and key == "\t\ttype":
                        fields.setdefault("strategies", []).append(value)
                    if ai_block == "spending_variables" and key == "\t\tgoods_stance":
                        fields.setdefault("slots", []).append(value)
                if section == "country_manager" and "sitai_d09_" in line:
                    fields.setdefault("flags", []).append(line.strip())

    if section or fields is not None:
        raise ValueError("Unclosed save database section")
    if not date:
        raise ValueError("Missing save game date")
    states = records["country_manager"]
    country_rows = [
        (ref, row) for ref, row in states if row.get("\tdefinition") == [f'"{country}"']
    ]
    if len(country_rows) != 1:
        raise ValueError("Country tag must identify exactly one country instance")
    country_id, country_fields = country_rows[0]
    (market_id,) = country_fields.get("\tmarket", [])
    market_rows = [row for ref, row in records["market_manager"] if str(ref) == market_id]
    if len(market_rows) != 1:
        raise ValueError("Country market does not identify a unique market")
    ai_rows = [
        (ref, row) for ref, row in records["ai"] if row.get("\tcountry") == [str(country_id)]
    ]
    player_countries = [
        int(value) for _, row in records["player_manager"] for value in row.get("\tcountry", [])
    ]
    player_controlled = country_id in player_countries
    if len(ai_rows) > 1 or (not player_controlled and not ai_rows):
        raise ValueError("Country does not identify a unique AI record")
    ai_id, ai_fields = ai_rows[0] if ai_rows else (None, {})
    slots = ai_fields.get("slots", [])
    if not slots and not player_controlled:
        raise ValueError("Missing serialized goods stance vector")
    return {
        "sha256": digest.hexdigest(),
        "game_date": date,
        "country": country,
        "country_id": country_id,
        "player_countries": player_countries,
        "player_controlled": player_controlled,
        "market": int(market_id),
        "market_owner": market_rows[0].get("\towner", []),
        "ai_record": ai_id,
        "ai_enabled": ai_fields.get("\tenabled", []),
        "strategies": ai_fields.get("strategies", []),
        "diagnostic_flags": country_fields.get("flags", []),
        "stance_slots": slots,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("save", type=Path)
    parser.add_argument("country", help="Country tag, for example JAP")
    args = parser.parse_args()
    with args.save.open("rb") as source:
        print(json.dumps(read_save(source, args.country), indent=2))


if __name__ == "__main__":
    main()
