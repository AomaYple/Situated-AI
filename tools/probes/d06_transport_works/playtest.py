"""Prepare D06 playtest profiles and read fixed-format Victoria 3 1.15.2 debug saves."""

from __future__ import annotations

import argparse
import json
import re
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile

from candidate import (
    DECREE,
    GAME_VERSION,
    LOCALIZATIONS,
    MOD_ID,
    SCRIPT,
    STEAM_BUILD,
    VALUES,
    VERSION,
    digest,
    freeze,
    require,
)

from pdx.distribution import METADATA_NAME, payloads
from pdx.parser import parse_bytes

BASE_NAME = "sa_shared.v3"
BASE_SHA = "9cded8a012578b4cf35bcb659c820d7b8b2c422809ee9278a9e9121eb48df34e"
EXE_SHA = "57c4950e9f1046d61729e8faeedbbdbb7aa30ff2a45788217285eb735491ad36"
PLAYTHROUGH = "9d01754a-87d1-450a-a522-c7b2b5e19f7f"
FRANCE = 5
REGIONS = (b"STATE_RIO_DE_JANEIRO", b"STATE_BAHIA")
GAMEPLAY_DLC = {
    "Voice of the People Preorder",
    "State and Revolution",
    "Pivot of Empire",
    "National Awakening",
    "The Great Wave",
    "Region Pack 1",
    "Sphere of Influence",
    "Charters of Commerce",
    "Voice of the People",
    "American Buildings Pack",
    "Iberian Twilight",
}
# All 18 mount directories observed in each of the three frozen 1.15.2 diagnostic logs.
DLC_MOUNTS = (
    "dlc001_preorder",
    "dlc002_american_buildings",
    "dlc003_melodies_for_the_masses",
    "dlc004_voice_of_the_people",
    "dlc006_voice_of_the_people_preorder",
    "dlc007_ap1",
    "dlc008_rp1",
    "dlc009_trains_pack",
    "dlc010_ep1",
    "dlc011_ip2",
    "dlc012_trade_ships_bonus_pack",
    "dlc013_mp1",
    "dlc014_ip3",
    "dlc015_songs_of_the_homeland",
    "dlc016_ip4",
    "dlc017_warships_bonus_pack",
    "dlc018_ep2",
    "dlc019_ip5",
)
BASE_MOUNTS = ("clausewitz", "jomini", "platform_specific_game_data", "game")
FIXTURE_ID = "situated-ai-d06-playtest"
FIXTURE_SCRIPT = "common/static_modifiers/sitai_d06_playtest_modifiers.txt"
PROFILES = {
    "vanilla": (None, False),
    "off": ("off", False),
    "moderate": ("moderate", False),
    "player": ("off", False),
    "controlled-player": ("off", True),
    "controlled-ai-off": ("off", True),
    "controlled-ai-moderate": ("moderate", True),
}
ROOT_END = re.compile(rb"^\}\n(?=[a-z_][a-z_\d]*=)", re.MULTILINE)
RECORD = re.compile(rb"^(\d+)=\{\n(.*?)^\}$", re.MULTILINE | re.DOTALL)
DEATH = re.compile(rb"object=(\d+)\n\t+death_date=([\d.]+)")
SPENDING = re.compile(
    rb"^\tspending_variables=\{\n\t\tcountry=(\d+)\n(.*?)^\t\}$", re.MULTILINE | re.DOTALL
)


def json_bytes(data: object) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def fingerprint(path: Path) -> str:
    return digest(path.read_bytes())


def build_fixture() -> dict[str, bytes]:
    source = Path(__file__).resolve().parent / "fixture" / FIXTURE_SCRIPT
    raw = source.read_text(encoding="utf-8")
    parse_bytes(raw.encode(), str(source)).require_complete()
    metadata = {
        "id": FIXTURE_ID,
        "name": "Situated AI D06 Playtest Controls",
        "version": "0.1.0",
        "supported_game_version": GAME_VERSION,
        "short_description": "Controlled diagnostic inputs for the D06 playtest.",
        "tags": [],
        "relationships": [],
    }
    return payloads({FIXTURE_SCRIPT: raw, METADATA_NAME: json_bytes(metadata)})


def prepare(packages: Path, baseline: Path, install: Path, output: Path) -> None:
    source_save = baseline.read_bytes()
    require(digest(source_save) == BASE_SHA, "共同起点的 SHA-256 不符")
    exe = install.resolve() / "binaries" / "victoria3.exe"
    require(fingerprint(exe) == EXE_SHA, "Victoria 3 可执行文件指纹不符")
    steam = exe.parents[3] / "appmanifest_529340.acf"
    build_pattern = rf'"buildid"\s+"{STEAM_BUILD}"'
    require(
        re.search(build_pattern, steam.read_text(encoding="utf-8")) is not None, "Steam 构建不符"
    )

    receipt_path = packages / "candidate-receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    require(
        (receipt["mod_id"], receipt["version"], receipt["game_version"], receipt["steam_build"])
        == (MOD_ID, VERSION, GAME_VERSION, STEAM_BUILD),
        "候选收据身份不符",
    )
    arms = {}
    members = sorted({METADATA_NAME, SCRIPT, VALUES, *LOCALIZATIONS})
    for arm in ("off", "moderate"):
        artifact = receipt["artifacts"][arm]
        archive = packages / f"{MOD_ID}-{VERSION}-{arm}.zip"
        require(archive.name == artifact["filename"], f"{arm} 收据文件名不符")
        require(fingerprint(archive) == artifact["sha256"], f"{arm} ZIP 指纹不符")
        with ZipFile(archive) as payload:
            require(payload.namelist() == members, f"{arm} 载荷路径不符")
            data = {name: payload.read(name) for name in payload.namelist()}
        require({name: digest(raw) for name, raw in data.items()} == artifact["members"], arm)
        arms[arm] = data
    fixture = build_fixture()
    output = output.resolve()
    profiles = {}
    for profile, (arm, controlled) in PROFILES.items():
        userdir = output / profile
        mount = []
        mods = {}
        if arm is not None:
            mods[MOD_ID] = arms[arm]
        if controlled:
            mods[FIXTURE_ID] = fixture
        for mod_id, data in mods.items():
            mod_dir = userdir / "mod" / mod_id
            for name, raw in data.items():
                path = mod_dir / name
                path.parent.mkdir(parents=True, exist_ok=True)
                freeze(path, raw, verify=False)
            mount.append({"path": str(mod_dir)})
        config = userdir / "content_load.json"
        save_dir = userdir / "save games"
        save_dir.mkdir(parents=True, exist_ok=True)
        freeze(save_dir / BASE_NAME, source_save, verify=False)
        freeze(
            config,
            json_bytes({"disabledDLC": [], "enabledMods": mount, "enabledUGC": []}),
            verify=False,
        )
        profiles[profile] = {
            "executable": str(exe),
            "arguments": [f"--userdir={userdir}", "-debug_mode"],
            "content_load_sha256": fingerprint(config),
            "arm": arm,
            "mods": {
                mod_id: {name: digest(raw) for name, raw in data.items()}
                for mod_id, data in mods.items()
            },
        }
    manifest = {
        "candidate_receipt_sha256": fingerprint(receipt_path),
        "baseline_sha256": BASE_SHA,
        "steam_public_build": STEAM_BUILD,
        "executable_sha256": EXE_SHA,
        "profiles": profiles,
    }
    freeze(output / "prepared.json", json_bytes(manifest), verify=False)


def root_block(raw: bytes, key: bytes) -> bytes:
    start = raw.index(b"\n" + key + b"={\n") + len(key) + 3
    end = ROOT_END.search(raw, start)
    if end is None:
        raise ValueError(f"存档缺少 {key!r} 的段落结尾")
    return raw[start : end.start()]


def records(block: bytes) -> dict[int, bytes]:
    return {int(row[1]): row[2] for row in RECORD.finditer(block)}


def field(block: bytes, key: bytes, *, depth: int = 1, default: str | None = None) -> str:
    match = re.search(rb"^" + b"\t" * depth + key + rb"=(.+)$", block, re.MULTILINE)
    if match is None:
        if default is not None:
            return default
        raise ValueError(f"存档缺少 {key!r}")
    return match[1].decode().strip('"')


def inspect_save(path: Path, *, fresh: bool = False) -> dict:
    raw = path.read_bytes()
    require(raw.startswith(b"SAV") and b"\nmeta_data={\n" in raw[:128], "需要明文 Victoria 3 存档")
    meta = root_block(raw, b"meta_data")
    version = field(meta, b"version")
    dlcs = sorted(re.findall(r'"([^"]+)"', field(meta, b"dlcs")))
    require(
        version == GAME_VERSION and set(dlcs) == GAMEPLAY_DLC, f"版本或 11 项玩法 DLC 不符 {path}"
    )
    playthrough = field(raw, b"playthrough_id", depth=0)
    seed = int(field(raw, b"seed", depth=0))
    if not fresh:
        require(playthrough == PLAYTHROUGH and seed == 1137923771, f"存档游戏线或种子不符 {path}")

    states = {}
    for instance, entry in records(root_block(raw, b"states")).items():
        region = field(entry, b"region", default="")
        if region.encode() not in REGIONS:
            continue
        infrastructure = Decimal(field(entry, b"infrastructure"))
        usage = Decimal(field(entry, b"infrastructure_usage"))
        states[instance] = {
            "region": region,
            "owner": int(field(entry, b"country")),
            "capacity": str(infrastructure),
            "usage": str(usage),
            "balance": str(infrastructure - usage),
        }

    players = [
        int(field(entry, b"country"))
        for entry in records(root_block(raw, b"player_manager")).values()
    ]
    manager = root_block(raw, b"decree_manager")
    dead = {int(row[1]): row[2].decode() for row in DEATH.finditer(manager)}
    decrees = []
    for instance, entry in records(manager).items():
        state = int(field(entry, b"state"))
        kind = field(entry, b"type")
        if state in states or kind == DECREE:
            decrees.append(
                {
                    "instance": instance,
                    "state": state,
                    "owner": int(field(entry, b"owner")),
                    "type": kind,
                    "death_date": dead.get(instance),
                }
            )

    selected_countries = {202, *players, *(state["owner"] for state in states.values())}
    tech = {
        int(field(entry, b"country")): "centralization"
        in field(entry, b"acquired_technologies", default="").split()
        for entry in records(root_block(raw, b"technology")).values()
    }
    cached_authority = {
        int(row[1]): field(row[2], b"authority_balance", depth=2, default="") or None
        for row in SPENDING.finditer(raw)
        if int(row[1]) in selected_countries
    }
    tick = field(root_block(raw, b"counters"), b"tick", depth=0, default="")
    return {
        "path": str(path),
        "sha256": digest(raw),
        "date": field(meta, b"game_date"),
        "tick": int(tick) if tick else None,
        "version": version,
        "playthrough": playthrough,
        "seed": seed,
        "seed_count": int(field(raw, b"seed_count", depth=0)),
        "dlcs": dlcs,
        "mods": re.findall(r'"([^"]+)"', field(meta, b"mods", default="")),
        "players": players,
        "number_of_players": int(field(meta, b"number_of_players")),
        "states": states,
        "decrees": sorted(decrees, key=lambda decree: decree["instance"]),
        "technology_centralization": {country: tech.get(country) for country in selected_countries},
        "cached_authority_balance": cached_authority,
    }


def validate_opening(saves: list[dict]) -> dict:
    for save in saves:
        require(
            save["sha256"] == BASE_SHA
            and save["tick"] is None
            and not save["mods"]
            and save["players"] == [FRANCE]
            and save["number_of_players"] == 1,
            f"开局模式只接受未经改写的共同起点 {save['path']}",
        )
    return {"scenario": "frozen_opening", "saves": saves}


def compare(saves: list[dict]) -> dict:
    first = saves[0]
    phase = [first[key] for key in ("date", "tick", "players", "number_of_players")]
    for save in saves:
        require(save["tick"] is not None, f"存档未记录游戏刻 {save['path']}")
        require(
            [save[key] for key in ("date", "tick", "players", "number_of_players")] == phase,
            f"只允许同一刻和同一玩家控制配置的对照 {save['path']}",
        )
    rows = []
    for state_id, state in first["states"].items():
        for save in saves:
            other = save["states"].get(state_id)
            if other is None or state["owner"] != other["owner"]:
                continue
            rows.append(
                {
                    "save": save["path"],
                    "state": state_id,
                    "capacity_delta_to_first": str(
                        Decimal(other["capacity"]) - Decimal(state["capacity"])
                    ),
                    "usage_delta_to_first": str(Decimal(other["usage"]) - Decimal(state["usage"])),
                }
            )
    return {"phase": phase[:2], "states_with_matching_owner": rows, "saves": saves}


def profile_readback(profile: Path) -> dict:
    manifest = json.loads((profile.parent / "prepared.json").read_bytes())
    require(
        manifest["steam_public_build"] == STEAM_BUILD
        and manifest["executable_sha256"] == EXE_SHA
        and manifest["baseline_sha256"] == BASE_SHA,
        "预装收据的游戏或共同起点身份不符",
    )
    prepared = manifest["profiles"][profile.name]
    arm, controlled = PROFILES[profile.name]
    expected_ids = []
    if arm is not None:
        expected_ids.append(MOD_ID)
    if controlled:
        expected_ids.append(FIXTURE_ID)
    require(
        prepared["arm"] == arm
        and set(prepared["mods"]) == set(expected_ids)
        and prepared["arguments"] == [f"--userdir={profile}", "-debug_mode"],
        f"预装收据的组别、挂载集合或目录不符 {profile}",
    )
    content = profile / "content_load.json"
    require(fingerprint(content) == prepared["content_load_sha256"], "实机内容配置有漂移")
    expected_dirs = {mod_id: (profile / "mod" / mod_id).resolve() for mod_id in expected_ids}
    expected_config = {
        "disabledDLC": [],
        "enabledMods": [{"path": str(expected_dirs[mod_id])} for mod_id in expected_ids],
        "enabledUGC": [],
    }
    require(json.loads(content.read_bytes()) == expected_config, "实机内容配置启用集合不符")

    log_dir = profile / "logs"
    debug = log_dir / "debug.log"
    lines = debug.read_text(encoding="utf-8", errors="replace").splitlines()
    install = Path(prepared["executable"]).resolve().parents[1]
    official_dirs = {(install / name).resolve() for name in BASE_MOUNTS}
    official_dirs.update((install / "game" / "dlc" / name).resolve() for name in DLC_MOUNTS)
    expected_mounts = official_dirs | set(expected_dirs.values())
    actual_mounts = {}
    for line_number, line in enumerate(lines, 1):
        _, marker, path = line.partition("Mounted Data: ")
        if marker:
            directory = Path(path)
            require(directory.is_absolute(), f"日志挂载路径不是绝对路径 {path}")
            directory = directory.resolve()
            require(directory not in actual_mounts, f"日志重复记录挂载 {directory}")
            actual_mounts[directory] = line_number
    missing = expected_mounts - actual_mounts.keys()
    extra = actual_mounts.keys() - expected_mounts
    require(
        not missing and not extra,
        f"日志挂载集合不符，缺少 {sorted(map(str, missing))}，额外 {sorted(map(str, extra))}",
    )

    mod_names = []
    for mod_id, directory in expected_dirs.items():
        expected = prepared["mods"][mod_id]
        installed = {
            path.relative_to(directory).as_posix(): fingerprint(path)
            for path in directory.rglob("*")
            if path.is_file()
        }
        require(installed == expected, f"实机挂载载荷有漂移 {mod_id}")
        metadata = json.loads((directory / METADATA_NAME).read_bytes())
        require(metadata["id"] == mod_id, f"实机挂载 Mod ID 不符 {mod_id}")
        mod_names.append(metadata["name"])
    return {
        "profile": str(profile),
        "arm": arm,
        "save_mod_names": sorted(mod_names),
        "content_load_sha256": fingerprint(content),
        "debug_mount_lines": sorted(
            actual_mounts[directory] for directory in expected_dirs.values()
        ),
        "debug_official_mount_count": len(official_dirs),
        "error_log": (log_dir / "error.log")
        .read_text(encoding="utf-8", errors="replace")
        .splitlines(),
        "logs": {path.name: fingerprint(path) for path in sorted(log_dir.glob("*.log"))},
    }


def verify_save_profile(save: dict, profile: Path, readback: dict) -> None:
    require(
        Path(save["path"]).resolve().parent == (profile / "save games").resolve(),
        f"存档不在该组的 save games 目录 {save['path']}",
    )
    require(
        sorted(save["mods"]) == readback["save_mod_names"],
        f"存档头记录的 Mod 集合不符 {save['path']}",
    )


def compare_profiles(saves: list[dict], *, controlled: bool) -> dict:
    profiles = [Path(save["path"]).resolve().parent.parent for save in saves]
    profile_names = {profile.name for profile in profiles}
    required = (
        {"controlled-ai-off", "controlled-ai-moderate"} if controlled else {"off", "moderate"}
    )
    optional = set() if controlled else {"vanilla"}
    require(
        len({profile.parent for profile in profiles}) == 1
        and len(profile_names) == len(profiles)
        and required <= profile_names <= required | optional,
        "对照须来自同一次预装的相应不同执行组",
    )
    for save in saves:
        require(
            save["players"] == [FRANCE] and save["number_of_players"] == 1,
            f"AI 对照要求法国为唯一玩家 {save['path']}",
        )
    result = compare(saves)
    for save, profile in zip(saves, profiles, strict=True):
        readback = profile_readback(profile)
        verify_save_profile(save, profile, readback)
        save["profile"] = readback
    result["scenario"] = "controlled_ai" if controlled else "natural_ai"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    setup = actions.add_parser("prepare")
    for key in ("packages", "baseline", "install", "output"):
        setup.add_argument(key, type=Path)
    for action in ("opening", "inspect", "compare"):
        read = actions.add_parser(action)
        read.add_argument("saves", nargs="+", type=Path)
        read.add_argument("--output", type=Path)
        if action == "inspect":
            read.add_argument("--profile", type=Path, required=True)
            read.add_argument("--fresh", action="store_true", help="新局不限定共同游戏线或种子")
        if action == "compare":
            read.add_argument("--controlled", action="store_true", help="对照两组受控 AI 分支")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.packages, args.baseline, args.install, args.output)
        print(args.output.resolve() / "prepared.json")
        return

    saves = [inspect_save(path, fresh=getattr(args, "fresh", False)) for path in args.saves]
    if args.action == "opening":
        result = validate_opening(saves)
    elif args.action == "compare":
        result = compare_profiles(saves, controlled=args.controlled)
    else:
        profile = args.profile.resolve()
        readback = profile_readback(profile)
        for save in saves:
            require(save["tick"] is not None, f"存档未记录游戏刻 {save['path']}")
            verify_save_profile(save, profile, readback)
        result = {"scenario": "inspection", "profile": readback, "saves": saves}
    raw = json_bytes(result)
    if args.output:
        freeze(args.output, raw, verify=False)
    else:
        print(raw.decode().rstrip())


if __name__ == "__main__":
    main()
