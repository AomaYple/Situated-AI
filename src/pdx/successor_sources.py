"""Bind an independently reviewed successor archive to recoverable authored Git inputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from pdx import distribution

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


# Exact 3.4.0 member digests. Evidence in 发布载荷来源校验设计.md.
_RETAINED_VANILLA_PAYLOADS = {
    "64435666ed847f0308d791a9fae211263fa341a0f681e9ced383a007cf6ebcf3": "common/ai_strategies/00_default_strategy.txt",
    "2e9d694393bd63f5ecc0ac42a87b378bdee40b859463ed847a3f29fc05239590": "common/ai_strategies/01_admin_strategies.txt",
    "4c23250b1722d2f6f68dd69d66dabcf239314094791ce08632a4e08284fa69f7": "common/ai_strategies/02_subject_diplomatic_strategies.txt",
    "4b58c6d4318ee8b14b925e07049b9d5ead7cbec45206ea297a36aaa868df93fb": "common/buildings/01_industry.txt",
    "f312edab2d5948d81fb2aab052a0eaea20b08c1567a5584284404d0ee5a855fc": "common/buildings/02_agro.txt",
    "616a9df53f0894147c11218de4e4a0fbecb3179f90768fffd284f32ce7be1964": "common/buildings/03_mines.txt",
    "d439b6c2a433be303a1e9aacfbbca45da47bbc782fa7ca201c6a4986988aa19d": "common/buildings/04_plantations.txt",
    "c69d3d653c97b1f6da9618759f2fa78f13fd8cd7f59c6f225a2656a3971eefea": "common/buildings/06_urban_center.txt",
    "1e37b8ab000055f2081ac3f5c649c55f325cd018e96e2ea4708d8c86f52959aa": "common/buildings/07_government.txt",
    "6bc90d1d000a4ba4a67823647b486f3164c51cb3ed1612fe60db566beb5eafd3": "common/buildings/09_misc_resource.txt",
    "8efd970f69d7179b71aafcf6c25ec9d6aaa84d911158feebedf58ba215b45171": "common/buildings/11_private_infrastructure.txt",
    "161e71ce8e7e97cbdcd0324e811ee108b01a05ff77baa984b7c17aace14bfada": "common/company_types/00_companies_africa.txt",
    "00f50925d1b21e37ad21892b6dea89db6c2f30ef8397d375b88f840c5ef29dc9": "common/company_types/00_companies_americas.txt",
    "51e3bcd5e6008a9783a3a7d25d203a61a683d261e5c600ee1f927ef72291331b": "common/company_types/00_companies_asia.txt",
    "b6fe250a1d07f367dc804ad6aec40283ae54877e256524aafc85c2b2f682f171": "common/company_types/00_companies_austria_hungary.txt",
    "a1ee7f8aa948159750235cbf1c0c0d4d132e98e60ea68e2b0a7138c770a65025": "common/company_types/00_companies_china.txt",
    "faf0db74f133728626b5c081faa2c735e2fc7c53c827d0e436709544f1fb41f4": "common/company_types/00_companies_cots.txt",
    "8ebc0bcc490da9647d8a94896d231d559e5fcf292cd8d6d27db48d2f7096176d": "common/company_types/00_companies_ep2.txt",
    "5f6cd2c1765f2a5566e9d23ebf31bfb82c2fb247906059515e341381497e2ea7": "common/company_types/00_companies_europe.txt",
    "9ab668d8213d2dadc71fffd0e0e6664dc58738e8d35cf6548c58db723bcdaec3": "common/company_types/00_companies_france.txt",
    "a2d550613da0250eed2a0a76096804c1b58cd147c36d2d3b589a731b9dca1215": "common/company_types/00_companies_germany.txt",
    "91f4973b417ad2f06d38c82d9ecd19a6461782a44142211c76682c84d55c0bcc": "common/company_types/00_companies_great_britain.txt",
    "00eb502eeedb5c95055a43568b36803bb4b3d6ceb53278c54a38a6554a69769e": "common/company_types/00_companies_ip2.txt",
    "d7e52cb1ac7ecfca58e2f581ec6c01dfe22c12cc2930f808e3cd1349dfec9f1f": "common/company_types/00_companies_ip3.txt",
    "152e8ac7f37c4234bd7898fcd74c60d58f596e6add5a9ddbdeb36bc475bb5f4f": "common/company_types/00_companies_ip4.txt",
    "a72ef9011c45394eaea8d4b6459d72a6fdaf885d0f3162f2f94d241d9ffc30e6": "common/company_types/00_companies_ip5.txt",
    "d5c8f1ba5d26a6cc4f9597ce8f6e32aab1fae475499608691be09d707ce8a03c": "common/company_types/00_companies_italy.txt",
    "1c307d2a6eff00a3f1cafc118a0088c589f3576b6046aba777cf55869d5ed88d": "common/company_types/00_companies_japan.txt",
    "63511ef33e58b5745807dee3b0fdee4c079024de5c8979d70816555d33356283": "common/company_types/00_companies_mp1.txt",
    "62b1daa2aa6ebb0324c82e0cef5366393059b08674fe120ab9b51c07fb437ea9": "common/company_types/00_companies_russia.txt",
    "5177c92c18cb9bad0f1befe0d7a636d08a5ecad017a27b6e4bcc55ea886ceab8": "common/company_types/00_companies_soi.txt",
    "f61f0712493cc50c591d9131120e8e23be797878adddcd3ff82b7135c3fa19c8": "common/company_types/00_companies_totally_normal.txt",
    "8f26d6209189c3073585969e4a80d49be700c1972f7dbd857480afa6061e6814": "common/company_types/00_companies_usa.txt",
    "d2bdf18f3486a75a72aaab9c583a811f7f82bc8da0042287e3e45420a9869118": "common/company_types/99_basic_companies.txt",
    "69920cf27a4ad4e6f8f84fa00141c4c926b76441a3fcbb7e09ae6c22939d4ace": "common/decrees/00_decree.txt",
    "621aaf26439022469e4f5a9816db2f2ad64e4b139d80b39a628465a61b42a630": "common/diplomatic_actions/00_relations_actions.txt",
    "89ad1187158f257d3d5d3b8eed4293d6493e9b397ad902b22d18bd3ec3c7c614": "common/laws/00_army_model.txt",
    "ca55b3ed67842ee84e699d8aa38fb01f8b77b38d022dc9ffd1cfb508d50f57eb": "common/laws/00_bureaucracy.txt",
    "a0c0973b7d2df718b36f5ff6df8f62244db55f7aeff0f19c4fbd0c98d6c77bf9": "common/laws/00_caste_hegemony.txt",
    "af0abed46fc9fa0e09b0cf8339f81608c10288364f051a3309b2aa551a641ffa": "common/laws/00_church_and_state.txt",
    "d4d704e92849569a9a8c5bc3145f413037e7adaeb876981eab66cb9c389e0eb5": "common/laws/00_citizenship.txt",
    "e44a9b6185eb358588ac248abf69c9f4932a0b42faf34edc0d2e539b5b43453e": "common/laws/00_distribution_of_power.txt",
    "6e3153ccc44fb12a293aaca014c1a72aa170f0fd2030056280dff40648a8b40d": "common/laws/00_governance_principles.txt",
    "357da494791252458276976cc8d240c4efe0f5b80af1d062002202a815e5023b": "common/laws/00_internal_security.txt",
    "29d9e564cd48a0ade92803b203ace174a92e0fd2275cbe9a53445db95ace24b5": "common/laws/00_navy_model.txt",
    "51f7f0df4b2682d3e42aeb7302fbe4996b77d8706e6b0e2f0022c7459ca26beb": "common/laws/01_colonial_affairs.txt",
    "91b14a2c822ba2bb291cedba09049d797ebb1a1ebf96a60b118a6376ac205418": "common/laws/01_economic_system.txt",
    "ca166a7def667015e675b1085771cdf649513b549fb85b75897d427dc38424b7": "common/laws/01_education_system.txt",
    "ee10a3eec09726ed068e87a9501973a2c1661e79bb81f389ce3e8acef009b23b": "common/laws/01_health_system.txt",
    "90d50c257f6484c51da370f45568d52f5cb14e4a3faaeace9972d545f96a018f": "common/laws/01_land_reform.txt",
    "2f816ea57895baef90c53ee3e1764be7da24ebf51e77d85399910ea8f71a15da": "common/laws/01_policing.txt",
    "860be065d57c99c7e30ef00f2ae5cfa391122264bbbdfbf3a6ab49043e5d4000": "common/laws/01_taxation.txt",
    "9902dd5f9c5d4681c69ac791a2c0b7d781007b7854b403b8170915c886bf2bbd": "common/laws/01_trade_policy.txt",
    "8e249d6ce5e003406d20f442f97be37209071191c119c1e2c8e2258e7874445d": "common/laws/02_childrens_rights.txt",
    "99844f99182ccfbeaae8a56c50acc1d0a4cbc31fde185031ff248f29308cc6be": "common/laws/02_free_speech.txt",
    "760fac12719af948d04dd2a51bc02aa743f3304fe2b074cbdc9522a4538c68a8": "common/laws/02_labor_rights.txt",
    "7fffc60be8b8f147e016b83981b302a8acf063a4f0bb210ee7c141822c2a2542": "common/laws/02_labour_associations.txt",
    "c3d480ec0818f02c86c391cf8301868ceb73e460b5305a4905c57c6dc5dfad9d": "common/laws/02_migration.txt",
    "134fdbdacda47bef2f38f1a18447f4df29853527d9a19cf5844d2778b8e2d7e1": "common/laws/02_rights_of_women.txt",
    "41a762f0b5ac29c81d61f08c5b30d84c4a59dc600a8340b507516fe08cb3f365": "common/laws/02_slavery.txt",
    "80c5247da213d0af75f831c8216665a4cf6022fcbf8405f6cb7459d0182b88c1": "common/laws/02_welfare.txt",
    "d2960248bf278dde86a98ed3dd7648c583521b1ac15ce4759c18fb797cb4287e": "common/mobilization_options/00_mobilization_option.txt",
    "cc402a38869610351d1584c797bcee7393e3551eedcda9aafa1998555d5fedb6": "common/ship_modifications/00_ship_modifications.txt",
    "3b569036b159253467cc59aad3e607fa11cdd0cb94e42ea92d27390723805893": "common/ship_modifications/01_utility_modifications.txt",
    "09cb653d4c02cf388a6da2e24908106d4f457b0800d970d3695e538c7b4de9a5": "common/technology/technologies/10_production.txt",
    "a3755220a28853e4c6f58b1b8fdba155f483496aa5f3fa657e977e176e3c7526": "common/technology/technologies/20_military.txt",
    "b17497c524924af874ebb306244d3a90b4cd1ed5b7fce226a9829edc7e83bf6b": "common/technology/technologies/30_society.txt",
    "ec6aab6b2b627297c5e95bcf5081351834b142fb2ffead74f4a914a47bdabd14": "common/treaty_articles/00_alliance.txt",
    "868ea319f4d897cad51f1c7ec041a1df15e94b58b611d8abf7a763189f00d17a": "common/treaty_articles/01_defensive_pact.txt",
    "76f91ccdf3caacab3a0f099375eefe1c0d0db94ba114d50962f9cb32dc855ea1": "common/treaty_articles/02_guarantee_independence.txt",
    "439ac5368733790943aeb5c4ef9ffb221bd4e3bec46b137cb68c96286143c5c7": "common/treaty_articles/07_foreign_investment_rights.txt",
    "22acbc30d6e2929e1e7c4155e29ba17cd1e3fd182a55ea1b94976ca84a475210": "common/treaty_articles/24_transit_rights.txt",
    "98691eff4d5fc52dbbf9b5afcf2aa7b6cfef9225e94ad108869441610c3b9325": "common/treaty_articles/25_trade_privilege.txt",
    "919997b07d68d8d42d23a58fb2178562f81945a4bcd4574921c0e18373da445d": "common/treaty_articles/31_toll_exemption.txt",
    "379908ed998362a730529531994d55fba5415f2b8bc9964094f95e5fa4ca80c5": "common/treaty_articles/32_no_tolls.txt",
    "eb458ff2f798f0291c0b7486943290e982200f761c3b7d1c12c2a99ef99bebfd": "common/treaty_articles/33_strait_access.txt",
    "375cd02d341157dd7ed7a54ac076c0058347b2920a43bec4cc93ced667242e51": "common/treaty_articles/34_no_strait_closure.txt",
}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def object_from_json(raw: bytes) -> dict[str, Any]:
    record = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(record, dict):
        raise ValueError("Expected a JSON object")
    return record


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def check_reviewed_sources(
    members: Mapping[str, bytes],
    listed: Mapping[str, Any],
    locked_files: Mapping[str, str],
    locked_sources: Mapping[str, str],
    read_blob: Callable[[str], bytes],
) -> None:
    """Recover authored inputs and check the canonical delivery bytes against the ZIP."""
    generated = members.keys() - {"README.md"}
    if generated != locked_files.keys():
        raise ValueError("Successor lock does not describe the verified candidate payload")
    required = {"README.md", distribution.METADATA_NAME}
    if not required <= members.keys():
        raise ValueError("Successor payload requires launcher metadata and README")
    if distribution.THUMBNAIL_NAME in members:
        distribution._validate_thumbnail(members[distribution.THUMBNAIL_NAME])
    repository: dict[str, str | bytes] = {}
    for name, raw in members.items():
        parts = PurePosixPath(name).parts
        is_script = len(parts) >= 3 and parts[0] == "common" and name.endswith(".txt")
        is_language = len(parts) >= 3 and parts[0] == "localization" and name.endswith(".yml")
        if (
            name not in required | {distribution.THUMBNAIL_NAME} and not (is_script or is_language)
        ) or "probe" in name.casefold():
            raise ValueError(f"Invalid generated member: {name}")
        record = listed[name]
        if record.get("origin") != "original":
            raise ValueError(f"Member lacks reviewed original provenance: {name}")
        sources = record.get("source_files")
        if not isinstance(sources, dict) or not sources:
            raise ValueError(f"Member lacks recoverable original source: {name}")
        distribution._validate_paths(list(sources))
        generated_path = f"mod/{name}"
        material = generated_path if name in generated else record.get("repository_path")
        if not isinstance(material, str):
            raise ValueError(f"Member lacks a repository path: {name}")
        distribution._validate_paths([material])
        if name == "README.md" and material not in sources:
            raise ValueError("README lacks a reviewed authored Git blob")
        source = read_blob(material)
        if name in locked_files and sha256(source) != locked_files[name]:
            raise ValueError(f"Member Git bytes differ from successor lock: {name}")
        for path, digest in sources.items():
            if path == material:
                if name in generated and name != distribution.THUMBNAIL_NAME:
                    raise ValueError(f"Generated member requires its authored inputs: {name}")
            elif locked_sources.get(path) != digest:
                raise ValueError(f"Member source is absent from the successor lock: {path}")
            if sha256(read_blob(path)) != digest:
                raise ValueError(f"Member source Git bytes differ from review: {path}")
        if name == distribution.THUMBNAIL_NAME:
            repository[name] = source
            continue
        decoded = source.decode("utf-8")
        if "\ufeff" in decoded or "\r" in decoded:
            raise ValueError(f"Invalid repository BOM/LF: {material}")
        repository[name] = decoded
        if not raw:
            raise ValueError(f"Empty package member: {name}")
    expected = distribution.payloads(distribution._release_files(repository))
    for name, raw in members.items():
        if raw != expected[name]:
            raise ValueError(f"Member delivery bytes differ from Git/lock projection: {name}")
