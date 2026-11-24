"""Build and verify the isolated D06 transport works candidate."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
from dataclasses import dataclass, replace
from decimal import Decimal
from itertools import product
from pathlib import Path
from zipfile import ZipFile, ZipInfo

from pdx.distribution import METADATA_NAME, payloads
from pdx.localization import parse_loc_entries
from pdx.localization_languages import DEFAULT_LANGUAGES, localization_path
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_bytes

SOURCE = Path(__file__).resolve().parent / "payload"
DECREE = "sitai_decree_transport_works"
ROAD = "decree_road_maintenance"
SCRIPT = "common/decrees/zz_sitai_transport_works.txt"
VALUES = "common/script_values/sitai_d06_transport_works_values.txt"
RELEASE = "sitai_d06_transport_works_release_threshold"
ICON = "gfx/interface/icons/decree/decree_road_maintenance.dds"
MOD_ID = "situated-ai-d06-transport-works-candidate"
VERSION = "0.1.0-d06.rc2"
GAME_VERSION = "1.15.2"
STEAM_BUILD = "26763837"
AI_WEIGHT_BLOCK = re.compile(rb"(?ms)^    ai_weight = \{\n.*?^    \}")
LOCALIZATIONS = {
    localization_path(language, "sitai_transport_works"): language.header
    for language in DEFAULT_LANGUAGES
}


def require(condition: bool, message: object) -> None:
    if not condition:
        raise ValueError(message)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_payload() -> dict[str, bytes]:
    paths = {
        path.relative_to(SOURCE).as_posix(): path.read_bytes()
        for path in SOURCE.rglob("*")
        if path.is_file()
    }
    require(set(paths) == {METADATA_NAME, SCRIPT, VALUES, *LOCALIZATIONS}, "候选源文件集合漂移")
    texts = {name: raw.decode("utf-8") for name, raw in paths.items()}
    require(
        all(
            "\ufeff" not in text and "\r" not in text and text.endswith("\n")
            for text in texts.values()
        ),
        "候选源码须采用 UTF-8 无 BOM、LF",
    )
    return payloads(texts)


def children(block: Block) -> list[Assignment]:
    assignments = list(block.assignments())
    require(len(assignments) == len(block.items), f"脚本行 {block.line} 含非赋值项目")
    require(all(entry.prefix is None for entry in assignments), "候选含引擎覆盖前缀")
    return assignments


def named(block: Block, keys: set[str]) -> dict[str, Assignment]:
    entries = children(block)
    require(len(entries) == len(keys) and {entry.key for entry in entries} == keys, keys)
    result = {entry.key: entry for entry in entries}
    require(all(entry.op == "=" for entry in entries), keys)
    return result


def scalar(entry: Assignment) -> str:
    if not isinstance(entry.value, Scalar):
        raise ValueError(f"脚本行 {entry.line} 缺少原子值")
    return entry.value.unquoted


def body(entry: Assignment) -> Block:
    if not isinstance(entry.value, Block):
        raise ValueError(f"脚本行 {entry.line} 缺少块")
    return entry.value


@dataclass(frozen=True)
class State:
    capacity: Decimal
    balance: Decimal
    original: bool = False
    road: bool = False
    multiplier: Decimal = Decimal(0)


def trigger(entry: Assignment, state: State) -> bool:
    match entry.key, entry.op:
        case (("OR" | "AND" | "NOT"), "="):
            clauses = children(body(entry))
            if entry.key == "OR":
                return any(trigger(clause, state) for clause in clauses)
            if entry.key == "AND":
                return all(trigger(clause, state) for clause in clauses)
            require(len(clauses) == 1, "NOT 只接收一个条件")
            return not trigger(clauses[0], state)
        case "has_decree", "=":
            return {DECREE: state.original, ROAD: state.road}[scalar(entry)]
        case "infrastructure", ">":
            return state.capacity > Decimal(scalar(entry))
        case "state_infrastructure_balance", "<=":
            return state.balance <= Decimal(scalar(entry))
        case "state_infrastructure_balance", "<":
            require(scalar(entry) == RELEASE, "在位门须使用自己的动态阈值")
            return state.balance < 5 * max(1, 1 + state.multiplier) + 3
        case _:
            raise ValueError(f"脚本行 {entry.line} 含未知条件 {entry.key} {entry.op}")


def score(weight: Block, state: State, *, off: bool) -> int:
    entries = named(weight, {"value"} if off else {"value", "if"})
    value = int(scalar(entries["value"]))
    if off:
        require(value == 0, "零组必须保持 0")
        return value
    tier = named(body(entries["if"]), {"limit", "add"})
    limit = children(body(tier["limit"]))
    require(len(limit) == 1, "重度短缺档只接收一个条件")
    return value + int(scalar(tier["add"])) * trigger(limit[0], state)


def check_threshold(raw: bytes) -> None:
    parsed = parse_bytes(raw, VALUES)
    parsed.require_complete()
    threshold = body(named(parsed.root, {RELEASE})[RELEASE])
    require(
        [(entry.key, entry.op, scalar(entry)) for entry in children(threshold)]
        == [
            ("value", "=", "modifier:state_infrastructure_mult"),
            ("add", "=", "1"),
            ("min", "=", "1"),
            ("multiply", "=", "5"),
            ("add", "=", "3"),
        ],
        "州修饰读取或动态回收计算漂移",
    )


def check_rule(raw: bytes, *, off: bool) -> int:
    parsed = parse_bytes(raw, SCRIPT)
    parsed.require_complete()
    decree = body(named(parsed.root, {DECREE})[DECREE])
    entries = named(
        decree,
        {"texture", "modifier", "unlocking_technologies", "cost", "state_trigger", "ai_weight"},
    )
    tech = body(entries["unlocking_technologies"])
    require(
        scalar(entries["texture"]) == ICON
        and scalar(entries["cost"]) == "60"
        and scalar(
            named(body(entries["modifier"]), {"state_infrastructure_add"})[
                "state_infrastructure_add"
            ]
        )
        == "5"
        and len(tech.items) == 1
        and [item.unquoted for item in tech.scalars()] == ["centralization"],
        "候选图标、基础成本、效果或科技漂移",
    )
    gates = children(body(entries["state_trigger"]))
    weight = body(entries["ai_weight"])

    def eligible(state: State) -> bool:
        return all(trigger(gate, state) for gate in gates)

    capacities = [Decimal(reading) for reading in ("-1", "0", "0.00001", "34")]
    balances = [
        Decimal(reading)
        for reading in (
            "-50",
            "-15.00001",
            "-15",
            "-14.99999",
            "-5.00001",
            "-5",
            "-4.99999",
            "0",
            "2.99999",
            "3",
            "100",
        )
    ]
    multipliers = [Decimal(value) for value in ("-1", "-0.1", "0", "0.59999", "0.6", "1", "19")]
    observations = 0
    for capacity, balance, original, road, multiplier in product(
        capacities, balances, (False, True), (False, True), multipliers
    ):
        state = State(capacity, balance, original, road, multiplier)
        bound = max(Decimal(5), (1 + multiplier) * 5)
        expected_gate = (
            not road and capacity > 0 and (balance < 3 + bound if original else balance <= -5)
        )
        expected_score = 0 if off else 75 + 25 * (balance <= -15)
        require(eligible(state) == expected_gate, state)
        require(score(weight, state, off=off) == expected_score, state)
        observations += 1

    for multiplier in multipliers:
        opening = State(Decimal(28), Decimal(-5), multiplier=multiplier)
        gain = max(0, 1 + multiplier) * 5
        on = State(opening.capacity + gain, opening.balance + gain, True, False, multiplier)
        # With stable external inputs the original instance survives each check,
        # even when its own gain reaches the diagnostic's old release gate.
        require(eligible(opening), opening)
        active = True
        for _ in range(3):
            active = active and eligible(on)
            require(active, on)
            observations += 1
        threshold = 3 + 5 * max(1, 1 + multiplier)
        just_below = replace(on, balance=threshold - Decimal("0.00001"))
        recovered = replace(on, balance=threshold)
        after_release = replace(recovered, balance=recovered.balance - gain, original=False)
        require(eligible(just_below) and not eligible(recovered), recovered)
        for _ in range(3):
            require(not eligible(after_release), after_release)
            observations += 1
        require(eligible(replace(after_release, balance=Decimal(-5))), after_release)
        require(not eligible(replace(on, road=True)), on)
        require(not eligible(replace(opening, road=True)), opening)
    return observations


def pack(data: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        for name, raw in sorted(data.items()):
            info = ZipInfo(name)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, raw)
    return stream.getvalue()


def read_archive(path: Path, expected: dict[str, bytes], *, off: bool) -> dict[str, object]:
    with ZipFile(path) as archive:
        names = archive.namelist()
        require(names == sorted(expected) and archive.testzip() is None, f"ZIP 文件集合漂移 {path}")
        data = {name: archive.read(name) for name in names}
    require(data == expected, f"ZIP 成员字节漂移 {path}")
    metadata = json.loads(data[METADATA_NAME])
    require(
        (metadata["id"], metadata["version"], metadata["supported_game_version"])
        == (MOD_ID, VERSION, GAME_VERSION)
        and metadata["relationships"] == [],
        "候选加载身份漂移",
    )
    check_threshold(data[VALUES])
    observations = check_rule(data[SCRIPT], off=off)
    for name, expected_header in LOCALIZATIONS.items():
        header, entries = parse_loc_entries(data[name].decode("utf-8-sig"))
        require(header == expected_header, name)
        require([key for key, _ in entries] == [DECREE, f"{DECREE}_desc"], name)
        require(all(value.strip() for _, value in entries), name)
    return {
        "filename": path.name,
        "sha256": digest(path.read_bytes()),
        "members": {name: digest(raw) for name, raw in data.items()},
        "rule_observations": observations,
    }


def freeze(path: Path, raw: bytes, *, verify: bool) -> None:
    if verify or path.exists():
        require(path.read_bytes() == raw, f"已有产物的字节不同 {path}")
    else:
        with path.open("xb") as stream:
            stream.write(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "verify"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    verify = args.action == "verify"
    if not verify:
        args.directory.mkdir(parents=True, exist_ok=True)

    moderate = load_payload()
    off_script, changed = AI_WEIGHT_BLOCK.subn(b"    ai_weight = { value = 0 }", moderate[SCRIPT])
    require(changed == 1, "中等组必须仅有一个 AI 权重块")
    off = {**moderate, SCRIPT: off_script}
    artifacts = {}
    for arm, data in (("moderate", moderate), ("off", off)):
        path = args.directory / f"{MOD_ID}-{VERSION}-{arm}.zip"
        freeze(path, pack(data), verify=verify)
        artifacts[arm] = read_archive(path, data, off=arm == "off")
    receipt = {
        "schema": 1,
        "game_version": GAME_VERSION,
        "steam_build": STEAM_BUILD,
        "mod_id": MOD_ID,
        "version": VERSION,
        "evidence": "static_check",
        "artifacts": artifacts,
    }
    encoded = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    freeze(args.directory / "candidate-receipt.json", encoded, verify=verify)
    print(encoded.decode("utf-8").rstrip())


if __name__ == "__main__":
    main()
