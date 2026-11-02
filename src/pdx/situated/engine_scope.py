"""版本固定的只读引擎取证；字段范围证明不授权额外 getter 或 lowering。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

REPO = Path(__file__).resolve().parents[3]
MANIFEST = REPO / "research/situated/victoria3-1.14.5-technology-scope.json"
MANIFEST_ID = "research/situated/victoria3-1.14.5-technology-scope.json"
MANIFEST_SHA256 = "de12ca6de8d06b54f40f78e3fe807e15c271b987fafb45b576b896bc21284c90"
STRATEGY_MANIFEST_ID = "research/situated/victoria3-1.14.5-strategy-scope-r7.json"
STRATEGY_MANIFEST = REPO / STRATEGY_MANIFEST_ID
STRATEGY_MANIFEST_SHA256 = "3f295f0a1a8fc1bd964ebe0949f81352de60fb3f28fa0b761358ba154aeab3f1"
COUNTRY_MANIFEST_ID = "research/situated/victoria3-1.14.5-country-definition-scope.json"
COUNTRY_MANIFEST = REPO / COUNTRY_MANIFEST_ID
COUNTRY_MANIFEST_SHA256 = "55aca9f3024ce6d7c607926838df778e1711d5eaad6fcad307acbcf485734a88"
COMPANY_MANIFEST_ID = "research/situated/victoria3-1.14.5-company-scope.json"
COMPANY_MANIFEST = REPO / COMPANY_MANIFEST_ID
COMPANY_MANIFEST_SHA256 = "fb28823262158216c31b892e3f8fae62852e14d9b79a14f7e75c0adcc8229f8d"
COMPANY_DEFAULT_MANIFEST_ID = "research/situated/victoria3-1.14.5-company-default-scope.json"
COMPANY_DEFAULT_MANIFEST = REPO / COMPANY_DEFAULT_MANIFEST_ID
COMPANY_DEFAULT_MANIFEST_SHA256 = "3295f597b36c531ca9ae671240bae0f0fa6a698ca9a67cf2c095927bd0378c6e"
LAW_MANIFEST_ID = "research/situated/victoria3-1.14.5-law-scope.json"
LAW_MANIFEST = REPO / LAW_MANIFEST_ID
LAW_MANIFEST_SHA256 = "eb96a222582705af59147adc6da9e6f2b11533e05a73eb9583e55171f79b0ba9"


@dataclass(frozen=True, slots=True)
class TechnologyScopeEvidence:
    verified: bool
    source_hashes: tuple[tuple[str, str], ...]
    references: tuple[str, ...] = ()
    technology_sources: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StrategyConsumerEvidence:
    field: str
    actor: str
    target: str
    operation: str
    capability: str
    references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StrategyScopeEvidence:
    verified: bool
    source_hashes: tuple[tuple[str, str], ...]
    strategy_sources: tuple[str, ...] = ()
    consumers: tuple[StrategyConsumerEvidence, ...] = ()


@dataclass(frozen=True, slots=True)
class CountryScopeEvidence:
    verified: bool
    source_hashes: tuple[tuple[str, str], ...]
    sources: tuple[str, ...] = ()
    references: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CompanyScopeEvidence:
    verified: bool
    source_hashes: tuple[tuple[str, str], ...]
    sources: tuple[str, ...] = ()
    references: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LawScopeEvidence:
    verified: bool
    source_hashes: tuple[tuple[str, str], ...]
    sources: tuple[str, ...] = ()
    references: tuple[str, ...] = ()


def _verified_manifest(
    game: Path,
    inputs: Mapping[str, bytes],
    manifest: Path,
    manifest_id: str,
    expected_hash: str,
    label: str,
) -> tuple[dict[str, Any], tuple[tuple[str, str], ...], bool]:
    """共享原字节校验机制；每个 consumer 的许可仍由独立 manifest 决定。"""
    manifest_bytes = manifest.read_bytes()
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest_hash != expected_hash:
        raise ValueError(f"{label}已变化，必须重新独立复核")
    data = json.loads(manifest_bytes)
    hashes = {f"@evidence/{manifest_id}": manifest_hash}
    executable = game.parent / "binaries/victoria3.exe"
    try:
        stream = executable.open("rb")
    except FileNotFoundError:
        return data, tuple(sorted(hashes.items())), False
    with stream:
        exe_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        hashes["@engine/binaries/victoria3.exe"] = exe_hash
        if exe_hash != data["exe"]["sha256"]:
            return data, tuple(sorted(hashes.items())), False
        stream.seek(0, 2)
        if stream.tell() != data["exe"]["bytes"]:
            raise ValueError(f"{label}的文件长度不一致")
        for point in data["observations"]:
            expected = bytes.fromhex(point["bytes"])
            stream.seek(int(point["file_offset"], 16))
            if stream.read(len(expected)) != expected:
                raise ValueError(f"{label}字节不一致：{point['label']}")
    verified = all(
        source in inputs and hashlib.sha256(inputs[source]).hexdigest() == digest
        for source, digest in data["script_hashes"].items()
    )
    return data, tuple(sorted(hashes.items())), verified


def _validate_strategy_contracts(data: Mapping[str, Any]) -> None:
    """Keep each additional exact consumer and dynamic object identity pinned."""
    expected = {
        "wanted_construction_output": {
            "actor_scope": "country",
            "target_scope": "none",
            "operation": "additive_construction_output_target",
            "unit": "construction_output",
            "capability": "direct",
            "consumer_va": "0x141646580",
            "parser_va": "0x14164185e",
            "member_offset": "0x16a0",
        },
        "institution_scores": {
            "actor_scope": "country",
            "target_scope": "definition_only:institution_type",
            "operation": "additive_score",
            "unit": "score",
            "capability": "direct",
            "consumer_va": "0x141644a3a",
            "parser_va": "0x1416417cc",
            "member_offset": "0x3d0",
            "definition_key": "resolved institution definition pointer; not a named script scope",
        },
        "min_law_chance_to_pass": {
            "actor_scope": "country",
            "target_scope": "scope:law=law",
            "operation": "override_pass_chance_threshold",
            "capability": "direct",
            "unit": "pass_chance",
            "consumer_va": "0x141646d23",
            "parser_va": "0x1416418b2",
            "member_offset": "0x9b8",
        },
    }
    expected.update(
        {
            "wargoal_scores": {
                "actor_scope": "country",
                "target_scope": "scope:target_country=country;scope:target_state=state",
                "operation": "additive_score",
                "unit": "score",
                "capability": "direct",
                "parser_va": "0x141641285",
                "consumer_va": "0x1416438ea",
                "member_offset": "0x1d8",
                "child_projection": "exact enum child numeric body",
            },
            "secret_goal_scores": {
                "actor_scope": "country",
                "target_scope": "scope:target_country=country",
                "operation": "additive_score",
                "unit": "score",
                "capability": "direct",
                "parser_va": "0x141641481",
                "consumer_va": "0x1416436fd",
                "member_offset": "0x2a0",
                "child_projection": "exact enum child.score only; trigger remains native filter",
            },
            "wanted_navy_size": {
                "actor_scope": "country",
                "target_scope": "none",
                "operation": "additive_navy_size_target",
                "unit": "naval_administration_levels",
                "capability": "direct",
                "parser_va": "0x141641888",
                "member_offset": "0x1a60",
                "consumer_va": "0x1415ad3b7",
            },
            "ship_construction_output_multiplier": {
                "actor_scope": "country",
                "target_scope": "none",
                "operation": "additive_ship_construction_output_multiplier",
                "unit": "multiplier",
                "capability": "direct",
                "parser_va": "0x141641cb2",
                "member_offset": "0x1be0",
                "consumer_va": "0x1415adadb",
            },
        }
    )
    expected.update(
        {
            "aggression": {
                "actor_scope": "country",
                "target_scope": "scope:target_country=country",
                "operation": "additive_aggression",
                "unit": "play_start_tendency",
                "capability": "direct",
                "parser_va": "0x14164154a",
                "member_offset": "0x1160",
                "consumer_va": "0x14164546f",
            },
            "nationalization_desire": {
                "actor_scope": "country",
                "target_scope": "none",
                "operation": "additive_nationalization_desire",
                "unit": "desire",
                "capability": "direct",
                "parser_va": "0x141641a74",
                "member_offset": "0xd78",
                "consumer_va": "0x141647ecd",
            },
            "max_active_stances": {
                "actor_scope": "country",
                "target_scope": "none",
                "operation": "additive_active_stance_limit",
                "unit": "count",
                "capability": "direct",
                "parser_va": "0x141641ca0",
                "member_offset": "0x498",
                "consumer_va": "0x14164805c",
            },
            "wanted_marines": {
                "actor_scope": "country",
                "target_scope": "none",
                "operation": "additive_marine_size_target",
                "unit": "barracks_levels",
                "capability": "direct",
                "parser_va": "0x141641b77",
                "member_offset": "0x18e0",
                "consumer_va": "0x14164441d",
            },
            "economic_vs_government_spending_balance": {
                "actor_scope": "country",
                "target_scope": "none",
                "operation": "additive_spending_balance",
                "unit": "debt_threshold_ratio",
                "capability": "direct",
                "parser_va": "0x141641b62",
                "member_offset": "0x1760",
                "consumer_va": "0x14164684d",
            },
            "target_marine_formation_size": {
                "actor_scope": "country",
                "target_scope": "none",
                "operation": "additive_marine_formation_size_target",
                "unit": "units_per_formation",
                "capability": "direct",
                "parser_va": "0x141641b8c",
                "member_offset": "0x19a0",
                "consumer_va": "0x1416445ad",
            },
            "unacceptable_infamy_level": {
                "actor_scope": "country",
                "target_scope": "none",
                "operation": "first_positive_infamy_limit_override",
                "unit": "infamy",
                "capability": "direct",
                "parser_va": "0x14164145d",
                "member_offset": "0xfe0",
                "consumer_va": "0x1416440fd",
            },
            "undesirable_infamy_level": {
                "actor_scope": "country",
                "target_scope": "none",
                "operation": "first_positive_infamy_limit_override",
                "unit": "infamy",
                "capability": "direct",
                "parser_va": "0x14164146f",
                "member_offset": "0xf20",
                "consumer_va": "0x141643f6d",
            },
            "diplomatic_play_neutrality": {
                "actor_scope": "country",
                "target_scope": "none",
                "operation": "additive_positive_active_neutrality",
                "unit": "score",
                "capability": "direct",
                "parser_va": "0x141641834",
                "member_offset": "0x608",
                "consumer_va": "0x14164783c",
            },
            "diplomatic_play_boldness": {
                "actor_scope": "country",
                "target_scope": "scope:diplomatic_play=diplomatic_play",
                "operation": "native_randomized_additive_boldness",
                "unit": "score",
                "capability": "direct",
                "parser_va": "0x141641849",
                "member_offset": "0x6c0",
                "consumer_va": "0x1416476aa",
            },
        }
    )
    expected.update(
        {
            "treaty_category_scores": {
                "actor_scope": "country",
                "target_scope": "none",
                "operation": "additive_treaty_category_score",
                "unit": "score",
                "capability": "direct",
                "parser_va": "0x141640e0a",
                "consumer_va": "0x141643aa9",
                "member_offset": "0x1f0",
                "child_projection": "exact enum child numeric body",
            },
            "strategic_region_stance_type_scores": {
                "actor_scope": "country",
                "target_scope": "scope:target_region=strategic_region;scope:region_score=scalar",
                "operation": "additive_region_stance_score",
                "unit": "score",
                "capability": "direct",
                "parser_va": "0x141641aa8",
                "consumer_va": "0x14164842a",
                "member_offset": "0x470",
                "child_projection": "exact stance definition child numeric body",
                "definition_key": "resolved strategic region stance definition pointer; not a named script scope",
            },
            "wanted_num_supply_ships": {
                "actor_scope": "country",
                "target_scope": "none",
                "operation": "additive_supply_ship_count_target",
                "unit": "ships",
                "capability": "direct",
                "parser_va": "0x141641bcb",
                "consumer_va": "0x1415ad63f",
                "member_offset": "0x1b20",
            },
            "max_ship_design_complexity": {
                "actor_scope": "country",
                "target_scope": "none",
                "operation": "additive_ship_design_complexity_limit",
                "unit": "modification_levels",
                "capability": "direct",
                "parser_va": "0x141641bb6",
                "consumer_va": "0x1414b716c",
                "member_offset": "0x1d60",
            },
        }
    )
    for field, contract in expected.items():
        if data.get("consumers", {}).get(field) != contract:
            raise ValueError(f"锁定策略消费者字段合同不一致：{field}")
    if set(data.get("consumers", {})) != {
        "diplomatic_play_neutrality",
        "obligation_value",
        "wargoal_maneuvers_fraction",
        "max_regressiveness",
        "wanted_army_size",
        "weight",
        "recklessness",
        "change_law_chance",
        "subject_value",
        "revolution_aversion",
        "wargoal_scores",
        "target_marine_formation_size",
        "unacceptable_infamy_level",
        "secret_goal_scores",
        "nationalization_desire",
        "possible",
        "ship_construction_output_multiplier",
        "diplomatic_play_boldness",
        "wanted_marines",
        "become_subject_value",
        "min_law_chance_to_pass",
        "institution_scores",
        "economic_vs_government_spending_balance",
        "undesirable_infamy_level",
        "max_progressiveness",
        "max_active_stances",
        "aggression",
        "wanted_navy_size",
        "wanted_construction_output",
        "treaty_category_scores",
        "strategic_region_stance_type_scores",
        "wanted_num_supply_ships",
        "max_ship_design_complexity",
    }:
        raise ValueError("锁定策略消费者字段合同集合不一致")
    if data.get("strategy_score_keys") != {
        "wargoal_scores": [
            "annex_country",
            "ban_slavery",
            "break_enforced_treaties",
            "colonization_rights",
            "conquer_state",
            "contain_threat",
            "demand_no_strait_closure",
            "demand_no_tolls",
            "demand_strait_access",
            "demand_toll_exemption",
            "enforce_treaty_article",
            "force_nationalization",
            "foreign_investment_rights",
            "humiliation",
            "increase_autonomy",
            "independence",
            "join_power_bloc",
            "leave_power_bloc",
            "liberate_country",
            "liberate_subject",
            "make_subject",
            "open_market",
            "reduce_autonomy",
            "regime_change",
            "release_as_subject",
            "return_state",
            "revoke_all_claims",
            "revoke_claim",
            "secession",
            "take_treaty_port",
            "transfer_subject",
            "unification",
            "unification_leadership",
            "custom",
        ],
        "treaty_category_scores": [
            "economy",
            "trade",
            "military",
            "military_defense",
            "ideology",
            "expansion",
            "power_bloc",
            "other",
            "none",
        ],
        "secret_goal_scores": [
            "none",
            "befriend",
            "reconcile",
            "protect",
            "antagonize",
            "conquer",
            "dominate",
            "comply",
            "defy",
        ],
    }:
        raise ValueError("锁定策略评分枚举证据不一致")
    if data.get("native_unprojected_contexts") != {
        "wargoal_scores": {
            "diplomatic_play": {
                "status": "unprojected_unknown",
                "scope_tag": "0x1c",
                "key_va": "0x145a94914",
                "registration_va": "0x1416438d0",
                "condition": "play id != -1",
                "reader_authorization": False,
            }
        }
    }:
        raise ValueError("锁定策略未投影上下文证据不一致")
    if data.get("diplomatic_play_instance_type") != {
        "scope_tag": "0x1c",
        "native_type": "CDiplomaticPlay",
        "type_descriptor_va": "0x14546bc20",
        "link_type_descriptor_va": "0x145720d10",
        "link_col_va": "0x144c31608",
        "link_vftable_va": "0x144716e80",
        "link_method_va": "0x14277ac90",
        "resolver_va": "0x1407e7250",
    }:
        raise ValueError("锁定策略外交博弈实例类型证据不一致")
    if data.get("law_instance_type") != {
        "scope_tag": "0x31",
        "native_type": "CCountryLaw",
        "type_descriptor_va": "0x14546c288",
        "link_type_descriptor_va": "0x145720b00",
        "link_vftable_va": "0x144717330",
        "link_method_va": "0x14277b340",
        "resolver_va": "0x140cb3cc0",
        "law_type_output_tag": "0x32",
    }:
        raise ValueError("锁定策略法律实例类型证据不一致")

    if data.get("strategic_region_type") != {
        "scope_tag": "0x52",
        "native_database": "CStrategicRegionsDatabase",
        "link_type_descriptor_va": "0x145721980",
        "link_col_va": "0x144c32f08",
        "link_vftable_va": "0x14471a600",
        "link_method_va": "0x142784d40",
        "resolver_va": "0x1411352c0",
        "id_member": "0x10",
    }:
        raise ValueError("锁定策略区域实例类型证据不一致")
    if data.get("stance_definition_sources") != {
        "common/ai_strategic_region_stance_types/00_ai_strategic_region_stance_types.txt": "add54c251b0fb2a37a6038b308ed9e67709d44f7ec0a5aac0bc03346afccb91d"
    }:
        raise ValueError("锁定策略区域 stance 定义来源证据不一致")
    if data.get("stance_definitions") != {
        "stance_none": {
            "source": "common/ai_strategic_region_stance_types/00_ai_strategic_region_stance_types.txt",
            "line": 3,
        },
        "stance_conquer_region": {
            "source": "common/ai_strategic_region_stance_types/00_ai_strategic_region_stance_types.txt",
            "line": 7,
        },
        "stance_protect_region": {
            "source": "common/ai_strategic_region_stance_types/00_ai_strategic_region_stance_types.txt",
            "line": 14,
        },
        "stance_colonize_region": {
            "source": "common/ai_strategic_region_stance_types/00_ai_strategic_region_stance_types.txt",
            "line": 21,
        },
    }:
        raise ValueError("锁定策略区域 stance 定义身份证据不一致")
    stance_bytes = data.get("stance_definition_bytes", {})
    if set(stance_bytes) != set(data["stance_definition_sources"]) or any(
        hashlib.sha256(bytes.fromhex(raw)).hexdigest() != data["stance_definition_sources"][source]
        for source, raw in stance_bytes.items()
    ):
        raise ValueError("锁定策略区域 stance 定义原始字节不一致")
    if data.get("strategy_field_merges") != {
        "treaty_category_scores": {
            "default_call": "0x141598094",
            "active_call": "0x1415980ba",
            "add_va": "0x1415980bf",
            "operation": "additive_treaty_category_score",
        },
        "strategic_region_stance_type_scores": {
            "default_insert": "0x1415ca52d",
            "active_append": "0x1415ca548",
            "debug_call": "0x1415ca5c2",
            "call": "0x1415ca65d",
            "add_va": "0x1415ca666",
            "operation": "additive_region_stance_score",
        },
        "wanted_num_supply_ships": {
            "default_call": "0x1415ad63f",
            "active_call": "0x1415ad7f2",
            "add_va": "0x1415ad8cf",
            "operation": "additive_supply_ship_count_target",
        },
        "max_ship_design_complexity": {
            "default_call": "0x1414b716c",
            "active_call": "0x1414b730f",
            "add_va": "0x1414b73e3",
            "operation": "additive_ship_design_complexity_limit",
        },
    }:
        raise ValueError("锁定策略同字段默认及活动策略合并证据不一致")


def strategy_evidence(game: Path, inputs: Mapping[str, bytes]) -> StrategyScopeEvidence:
    """逐字段核对策略成员、真实消费者及原字节，不能从容器推导其他字段。"""
    data, hashes, verified = _verified_manifest(
        game,
        inputs,
        STRATEGY_MANIFEST,
        STRATEGY_MANIFEST_ID,
        STRATEGY_MANIFEST_SHA256,
        "锁定策略作用域证据",
    )
    _validate_strategy_contracts(data)
    if not verified:
        return StrategyScopeEvidence(False, hashes)
    manifest_hash = STRATEGY_MANIFEST_SHA256
    return StrategyScopeEvidence(
        True,
        hashes,
        tuple(sorted(data["script_hashes"])),
        tuple(
            StrategyConsumerEvidence(
                field,
                contract["actor_scope"],
                contract["target_scope"],
                contract["operation"],
                contract["capability"],
                (
                    f"{STRATEGY_MANIFEST_ID}:sha256={manifest_hash}",
                    f"@engine/binaries/victoria3.exe:{contract['consumer_va']}",
                ),
            )
            for field, contract in sorted(data["consumers"].items())
        ),
    )


def strategy_snapshot() -> bytes:
    """Read pinned historical evidence, without claiming current EXE verification."""
    raw = STRATEGY_MANIFEST.read_bytes()
    if hashlib.sha256(raw).hexdigest() != STRATEGY_MANIFEST_SHA256:
        raise ValueError("锁定策略作用域证据已变化，必须重新独立复核")
    _validate_strategy_contracts(json.loads(raw))
    return raw


def verify_strategy_game(game: Path) -> StrategyScopeEvidence:
    """Require actual pinned scripts and EXE at the production boundary."""
    data = json.loads(strategy_snapshot())
    inputs = {source: (game / source).read_bytes() for source in data["script_hashes"]}
    proof = strategy_evidence(game, inputs)
    if not proof.verified:
        raise ValueError("当前原版策略脚本或 EXE 与锁定策略作用域证据不一致")
    definition_sources = data["institution_definition_sources"]
    actual_sources = {
        path.relative_to(game).as_posix()
        for path in game.rglob("*.txt")
        if path.is_file() and "/common/institutions/" in "/" + path.relative_to(game).as_posix()
    }
    if actual_sources != set(definition_sources):
        raise ValueError("当前制度定义原件集合与锁定策略证据不同，可能存在新增或覆盖定义")
    for source, digest in definition_sources.items():
        if hashlib.sha256((game / source).read_bytes()).hexdigest() != digest:
            raise ValueError("当前制度定义原件与锁定策略作用域证据不一致")
    stance_sources = data["stance_definition_sources"]
    actual_stance_sources = {
        path.relative_to(game).as_posix()
        for path in game.rglob("*.txt")
        if path.is_file()
        and "/common/ai_strategic_region_stance_types/" in "/" + path.relative_to(game).as_posix()
    }
    if actual_stance_sources != set(stance_sources):
        raise ValueError("当前区域 stance 定义原件集合与锁定策略证据不同")
    for source, digest in stance_sources.items():
        if hashlib.sha256((game / source).read_bytes()).hexdigest() != digest:
            raise ValueError("当前区域 stance 定义原件与锁定策略作用域证据不一致")
    return replace(
        proof,
        source_hashes=tuple(
            sorted((*proof.source_hashes, *definition_sources.items(), *stance_sources.items()))
        ),
    )


def company_snapshot() -> bytes:
    """固定公司候选证据；不把定义身份当作脚本 company 目标。"""
    raw = COMPANY_MANIFEST.read_bytes()
    if hashlib.sha256(raw).hexdigest() != COMPANY_MANIFEST_SHA256:
        raise ValueError("锁定公司作用域证据已变化，必须重新独立复核")
    return raw


def verify_company_game(game: Path) -> CompanyScopeEvidence:
    """生产公司选择必须重新核对当前原版脚本和引擎字节。"""
    data = json.loads(company_snapshot())
    expected = set(data["script_hashes"])
    actual = {
        path.relative_to(game).as_posix()
        for path in game.rglob("*.txt")
        if path.is_file() and "/common/company_types/" in "/" + path.relative_to(game).as_posix()
    }
    if actual != expected:
        raise ValueError("当前公司原件集合与锁定作用域证据不同，可能存在新增或覆盖定义")
    inputs = {source: (game / source).read_bytes() for source in data["script_hashes"]}
    proof = company_evidence(game, inputs)
    if not proof.verified:
        raise ValueError("当前原版公司脚本或 EXE 与锁定公司作用域证据不一致")
    return proof


def company_default_snapshot() -> bytes:
    """Authorize only exactly missing company scores, never empty/nonpositive replacements."""
    raw = COMPANY_DEFAULT_MANIFEST.read_bytes()
    if hashlib.sha256(raw).hexdigest() != COMPANY_DEFAULT_MANIFEST_SHA256:
        raise ValueError("锁定公司缺省权重证据已变化，必须重新独立复核")
    data = json.loads(raw)
    expected = {
        "field": "ai_weight",
        "actor": "country",
        "target": "definition_only:company_type",
        "operation": "missing_base_candidate_score",
        "capability": "exact_default_initializer",
        "consumer": "0x14169a3b0",
        "numeric_member": "0x390",
        "empty_expression_member": "0xa8",
        "empty_expression_branch": "0x14169a3dd",
        "nonempty_expression_branch": "0x14169a3f5",
        "default_load": "0x14169a3e6",
        "default_global": "0x1459d2a08",
        "result_store": "0x14169a3ed",
        "result_return": "0x14169a531",
        "define_namespace": "NAI",
        "define_key": "COMPANY_TYPE_DEFAULT_BASE_WEIGHT",
        "define_field": "NAI.COMPANY_TYPE_DEFAULT_BASE_WEIGHT",
        "define_source": "common/defines/00_ai.txt",
        "define_line": 1161,
        "default_value": 1,
        "define_setter": "0x140975a20",
        "define_global_write": "0x140975a56",
        "define_binding": "0x140975a70",
        "define_registration": "0x140975a90",
        "actual_call": "0x1415c9855",
        "nonpositive_rejection": "0x141510b30",
        "source_requirement": "exactly_missing_ai_weight_only",
        "explicit_empty_requirement": "reject_initializer",
        "explicit_nonpositive_requirement": "preserve_native_score_and_rejection",
    }
    identities = (
        ("company_basic_agriculture_1", 1),
        ("company_basic_agriculture_2", 68),
        ("company_basic_fabrics", 139),
        ("company_basic_colonial_plantations_1", 207),
        ("company_basic_colonial_plantations_2", 273),
        ("company_basic_silk_and_dye", 343),
        ("company_basic_wine_and_fruit", 400),
        ("company_basic_fishing", 456),
        ("company_basic_forestry", 524),
        ("company_basic_oil", 583),
        ("company_basic_gold_mining", 631),
        ("company_basic_metal_mining", 680),
        ("company_basic_mineral_mining", 737),
        ("company_basic_food", 793),
        ("company_basic_paper", 857),
        ("company_basic_home_goods", 918),
        ("company_basic_textiles", 987),
        ("company_basic_steel", 1049),
        ("company_basic_metalworks", 1111),
        ("company_basic_shipyards", 1178),
        ("company_basic_chemicals", 1228),
        ("company_basic_motors", 1297),
        ("company_basic_munitions", 1355),
        ("company_basic_electrics", 1424),
        ("company_basic_weapons", 1473),
        ("company_construction_power_bloc", 1543),
    )
    if data.get("contracts") != [expected] or data.get("implicit_companies") != [
        {"id": key, "line": line} for key, line in identities
    ]:
        raise ValueError("锁定公司缺省权重的精确合同或定义身份不一致")
    if set(data.get("script_hashes", {})) != {
        "common/defines/00_ai.txt",
        "common/company_types/99_basic_companies.txt",
    }:
        raise ValueError("锁定公司缺省权重的精确原件来源不一致")
    if data.get("parent_scope_manifest") != {
        "path": COMPANY_MANIFEST_ID,
        "sha256": COMPANY_MANIFEST_SHA256,
    }:
        raise ValueError("锁定公司缺省权重的父作用域证据身份不一致")
    company_snapshot()
    return raw


def verify_company_defaults_game(game: Path) -> CompanyScopeEvidence:
    """Require both exact default evidence and the full parent company scope proof."""
    data = json.loads(company_default_snapshot())
    inputs = {source: (game / source).read_bytes() for source in data["script_hashes"]}
    _, hashes, verified = _verified_manifest(
        game,
        inputs,
        COMPANY_DEFAULT_MANIFEST,
        COMPANY_DEFAULT_MANIFEST_ID,
        COMPANY_DEFAULT_MANIFEST_SHA256,
        "锁定公司缺省权重证据",
    )
    if not verified:
        raise ValueError("当前公司缺省权重来源或 EXE 与锁定证据不一致")
    parent = verify_company_game(game)
    return CompanyScopeEvidence(
        True,
        tuple(sorted({**dict(parent.source_hashes), **dict(hashes)}.items())),
        tuple(sorted(set(parent.sources) | set(data["script_hashes"]))),
        (
            *parent.references,
            f"{COMPANY_DEFAULT_MANIFEST_ID}:sha256={COMPANY_DEFAULT_MANIFEST_SHA256}",
            "@engine/binaries/victoria3.exe:0x14169a3dd",
            "@engine/binaries/victoria3.exe:0x14169a3e6",
            "@engine/binaries/victoria3.exe:0x140975a56",
        ),
    )


def company_default_evidence(game: Path, inputs: Mapping[str, bytes]) -> CompanyScopeEvidence:
    """Inventory proof requires the actual define, exact company set and parent chain."""
    company_default_snapshot()
    data, hashes, verified = _verified_manifest(
        game,
        inputs,
        COMPANY_DEFAULT_MANIFEST,
        COMPANY_DEFAULT_MANIFEST_ID,
        COMPANY_DEFAULT_MANIFEST_SHA256,
        "锁定公司缺省权重证据",
    )
    parent = company_evidence(game, inputs)
    parent_data = json.loads(company_snapshot())
    actual = {
        source
        for source in inputs
        if source.endswith(".txt") and "/common/company_types/" in "/" + source
    }
    sources = set(parent_data["script_hashes"]) | set(data["script_hashes"])
    actual_hashes = {
        source: hashlib.sha256(inputs[source]).hexdigest() for source in sources if source in inputs
    }
    merged_hashes = tuple(
        sorted({**dict(parent.source_hashes), **dict(hashes), **actual_hashes}.items())
    )
    if not verified or not parent.verified or actual != set(parent_data["script_hashes"]):
        return CompanyScopeEvidence(False, merged_hashes)
    return CompanyScopeEvidence(
        True,
        merged_hashes,
        tuple(sorted(sources)),
        (
            *parent.references,
            f"{COMPANY_DEFAULT_MANIFEST_ID}:sha256={COMPANY_DEFAULT_MANIFEST_SHA256}",
            "@engine/binaries/victoria3.exe:0x14169a3dd",
            "@engine/binaries/victoria3.exe:0x14169a3e6",
            "@engine/binaries/victoria3.exe:0x140975a56",
        ),
    )


def country_evidence(game: Path, inputs: Mapping[str, bytes]) -> CountryScopeEvidence:
    """固定两类国家定义的实际消费者和全部来源。"""
    data, hashes, verified = _verified_manifest(
        game,
        inputs,
        COUNTRY_MANIFEST,
        COUNTRY_MANIFEST_ID,
        COUNTRY_MANIFEST_SHA256,
        "锁定国家定义作用域证据",
    )
    if not verified:
        return CountryScopeEvidence(False, hashes)
    return CountryScopeEvidence(
        True,
        hashes,
        tuple(sorted(data["script_hashes"])),
        (f"{COUNTRY_MANIFEST_ID}:sha256={COUNTRY_MANIFEST_SHA256}",),
    )


def company_evidence(game: Path, inputs: Mapping[str, bytes]) -> CompanyScopeEvidence:
    """仅许可已证明的公司准入与数值成员，不扩散到章程或建设目标。"""
    data, hashes, verified = _verified_manifest(
        game,
        inputs,
        COMPANY_MANIFEST,
        COMPANY_MANIFEST_ID,
        COMPANY_MANIFEST_SHA256,
        "锁定公司作用域证据",
    )
    if not verified:
        return CompanyScopeEvidence(False, hashes)
    return CompanyScopeEvidence(
        True,
        hashes,
        tuple(sorted(data["script_hashes"])),
        (f"{COMPANY_MANIFEST_ID}:sha256={COMPANY_MANIFEST_SHA256}",),
    )


def law_evidence(game: Path, inputs: Mapping[str, bytes]) -> LawScopeEvidence:
    """仅证明法律候选的国家资格门与定义身份，不授予脚本 law 目标。"""
    data, hashes, verified = _verified_manifest(
        game,
        inputs,
        LAW_MANIFEST,
        LAW_MANIFEST_ID,
        LAW_MANIFEST_SHA256,
        "锁定法律作用域证据",
    )
    if data.get("contract") != {
        "family": "laws",
        "hook": "ai_will_do",
        "actor": "country",
        "target": "definition_only:law_type",
        "operation": "eligibility",
        "capability": "direct",
        "named_targets_proven": [],
    }:
        raise ValueError("锁定法律作用域证据的字段合同不一致")
    if not verified:
        return LawScopeEvidence(False, hashes)
    return LawScopeEvidence(
        True,
        hashes,
        tuple(sorted(data["script_hashes"])),
        (
            f"{LAW_MANIFEST_ID}:sha256={LAW_MANIFEST_SHA256}",
            "@engine/binaries/victoria3.exe:0x141548e39",  # 实际候选资格门
            "@engine/binaries/victoria3.exe:0x14170c2a0",  # 国家触发器包装器
            "@engine/binaries/victoria3.exe:0x141709d64",  # ai_will_do 精确解析分支
        ),
    )


def technology_evidence(game: Path, inputs: Mapping[str, bytes]) -> TechnologyScopeEvidence:
    """核对原始字节而不执行游戏；缺少对应平台证据时保持未证明。

    证据只覆盖已观察的科技候选调用点及定义身份，不将本地 candidate
    指针当作脚本可寻址 saved scope。公式下游成本、随机及命令仍归原版。
    """
    data, hashes, verified = _verified_manifest(
        game, inputs, MANIFEST, MANIFEST_ID, MANIFEST_SHA256, "锁定引擎作用域证据"
    )
    if not verified:
        return TechnologyScopeEvidence(False, hashes)
    manifest_hash = MANIFEST_SHA256
    return TechnologyScopeEvidence(
        True,
        hashes,
        (
            f"{MANIFEST_ID}:sha256={manifest_hash}",
            "@engine/binaries/victoria3.exe:0x141783e29",  # exact technology parser
            "@engine/binaries/victoria3.exe:0x14161a8c0",  # Country scope tag
            "@engine/binaries/victoria3.exe:0x141538b90",  # base formula evaluation
        ),
        tuple(
            sorted(
                source
                for source in data["script_hashes"]
                if source.startswith("common/technology/technologies/")
            )
        ),
    )


__all__ = [
    "CompanyScopeEvidence",
    "CountryScopeEvidence",
    "LawScopeEvidence",
    "StrategyConsumerEvidence",
    "StrategyScopeEvidence",
    "TechnologyScopeEvidence",
    "company_default_evidence",
    "company_default_snapshot",
    "company_evidence",
    "company_snapshot",
    "country_evidence",
    "law_evidence",
    "strategy_evidence",
    "strategy_snapshot",
    "technology_evidence",
    "verify_company_defaults_game",
    "verify_company_game",
    "verify_strategy_game",
]
