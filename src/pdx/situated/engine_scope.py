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
STRATEGY_MANIFEST_ID = "research/situated/victoria3-1.14.5-strategy-scope-r3.json"
STRATEGY_MANIFEST = REPO / STRATEGY_MANIFEST_ID
STRATEGY_MANIFEST_SHA256 = "83b369cd1f40e588428410912cfb9fcea43f823f0604ee38283bcbf7677adba3"
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
    for field, contract in expected.items():
        if data.get("consumers", {}).get(field) != contract:
            raise ValueError(f"锁定策略消费者字段合同不一致：{field}")
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
    return replace(
        proof,
        source_hashes=tuple(sorted((*proof.source_hashes, *definition_sources.items()))),
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
