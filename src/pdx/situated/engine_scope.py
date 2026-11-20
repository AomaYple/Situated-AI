"""版本固定的只读引擎取证；字段范围证明不授权额外 getter 或 lowering。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import engine_scope_115, engine_strategy_115

if TYPE_CHECKING:
    from collections.abc import Mapping

REPO = Path(__file__).resolve().parents[3]


def _company_manifest(*, default: bool = False) -> tuple[Path, str, str]:
    return engine_scope_115.manifest("company-default" if default else "company")


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
            stream.seek(int(point["file_offset"], 16))
            if "bytes" in point:
                expected = bytes.fromhex(point["bytes"])
                matches = stream.read(len(expected)) == expected
            else:
                size = point["size"]
                if type(size) is not int or size <= 0:
                    raise ValueError(f"{label}观察范围不合法：{point['label']}")
                actual = stream.read(size)
                matches = (
                    len(actual) == size and hashlib.sha256(actual).hexdigest() == point["sha256"]
                )
            if not matches:
                raise ValueError(f"{label}字节不一致：{point['label']}")
    verified = all(
        source in inputs and hashlib.sha256(inputs[source]).hexdigest() == digest
        for source, digest in data["script_hashes"].items()
    )
    return data, tuple(sorted(hashes.items())), verified


def _validate_strategy_contracts(data: Mapping[str, Any]) -> None:
    """Keep each additional exact consumer and dynamic object identity pinned."""
    engine_strategy_115.validate(data)


def _strategy_manifest() -> tuple[Path, str, str]:
    return engine_scope_115.manifest("strategy")


def strategy_evidence(game: Path, inputs: Mapping[str, bytes]) -> StrategyScopeEvidence:
    """逐字段核对策略成员、真实消费者及原字节，不能从容器推导其他字段。"""
    manifest, manifest_id, manifest_hash = _strategy_manifest()
    data, hashes, verified = _verified_manifest(
        game,
        inputs,
        manifest,
        manifest_id,
        manifest_hash,
        "锁定策略作用域证据",
    )
    _validate_strategy_contracts(data)
    if not verified:
        return StrategyScopeEvidence(False, hashes)
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
                    f"{manifest_id}:sha256={manifest_hash}",
                    f"@engine/binaries/victoria3.exe:{contract['consumer_va']}",
                ),
            )
            for field, contract in sorted(data["consumers"].items())
        ),
    )


def strategy_snapshot() -> bytes:
    """Read the selected version's evidence without claiming EXE verification."""
    manifest, _, expected_hash = _strategy_manifest()
    raw = manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_hash:
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


def _company_score_contract() -> dict[str, str]:
    """Exact reviewed score coordinates, selected independently for each EXE."""
    return {
        "field": "ai_weight",
        "actor": "country",
        "target": "definition_only:company_type",
        "operation": "base_candidate_score",
        "capability": "direct",
        "consumer": "0x1417573f0",
        "actual_call": "0x14164e836",
        "numeric_member": "0x390",
        "parser": "0x141755340",
        "parser_receiver": "0x598",
        "nonpositive_rejection": "0x14165e5b3",
    }


def _validate_company_score_contract(data: Mapping[str, Any]) -> None:
    """A new digest cannot authorize a different company score consumer."""
    matches = [row for row in data["contracts"] if row.get("field") == "ai_weight"]
    if len(matches) != 1:
        raise ValueError("公司基础评分缺少唯一作用域合同")
    row = matches[0]
    if any(row.get(key) != value for key, value in _company_score_contract().items()):
        raise ValueError("公司基础评分作用域合同漂移")


def company_snapshot() -> bytes:
    """固定公司候选证据；不把定义身份当作脚本 company 目标。"""
    manifest, _, digest = _company_manifest()
    raw = manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("锁定公司作用域证据已变化，必须重新独立复核")
    _validate_company_score_contract(json.loads(raw))
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
    manifest, _, digest = _company_manifest(default=True)
    raw = manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("锁定公司缺省权重证据已变化，必须重新独立复核")
    data = json.loads(raw)
    score_contract = _company_score_contract()
    expected = {
        "field": "ai_weight",
        "actor": "country",
        "target": "definition_only:company_type",
        "operation": "missing_base_candidate_score",
        "capability": "exact_default_initializer",
        "consumer": score_contract["consumer"],
        "numeric_member": score_contract["numeric_member"],
        "empty_expression_member": "0xa8",
        "empty_expression_branch": "0x14175741d",
        "nonempty_expression_branch": "0x141757435",
        "default_load": "0x141757426",
        "default_global": "0x145c1f628",
        "result_store": "0x14175742d",
        "result_return": "0x141757571",
        "define_namespace": "NAI",
        "define_key": "COMPANY_TYPE_DEFAULT_BASE_WEIGHT",
        "define_field": "NAI.COMPANY_TYPE_DEFAULT_BASE_WEIGHT",
        "define_source": "common/defines/00_ai.txt",
        "define_line": 1146,
        "default_value": 1,
        "define_setter": "0x14119b680",
        "define_global_write": "0x14119b6b6",
        "define_binding": "0x14119b6d0",
        "define_registration": "0x14119b6f0",
        "actual_call": score_contract["actual_call"],
        "nonpositive_rejection": score_contract["nonpositive_rejection"],
        "source_requirement": "exactly_missing_ai_weight_only",
        "explicit_empty_requirement": "reject_initializer",
        "explicit_nonpositive_requirement": "preserve_native_score_and_rejection",
    }
    identities = (
        ("company_basic_agriculture_1", 1),
        ("company_basic_agriculture_2", 60),
        ("company_basic_fabrics", 122),
        ("company_basic_colonial_plantations_1", 182),
        ("company_basic_colonial_plantations_2", 240),
        ("company_basic_silk_and_dye", 301),
        ("company_basic_wine_and_fruit", 350),
        ("company_basic_fishing", 398),
        ("company_basic_forestry", 458),
        ("company_basic_oil", 509),
        ("company_basic_gold_mining", 552),
        ("company_basic_metal_mining", 596),
        ("company_basic_mineral_mining", 647),
        ("company_basic_food", 695),
        ("company_basic_paper", 753),
        ("company_basic_home_goods", 808),
        ("company_basic_textiles", 868),
        ("company_basic_steel", 924),
        ("company_basic_metalworks", 980),
        ("company_basic_shipyards", 1037),
        ("company_basic_chemicals", 1081),
        ("company_basic_motors", 1141),
        ("company_basic_munitions", 1190),
        ("company_basic_electrics", 1250),
        ("company_basic_weapons", 1295),
        ("company_construction_power_bloc", 1356),
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
    _, parent_id, parent_digest = _company_manifest()
    if data.get("parent_scope_manifest") != {"path": parent_id, "sha256": parent_digest}:
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
        *_company_manifest(default=True),
        "锁定公司缺省权重证据",
    )
    if not verified:
        raise ValueError("当前公司缺省权重来源或 EXE 与锁定证据不一致")
    parent = verify_company_game(game)
    _, manifest_id, digest = _company_manifest(default=True)
    contract = data["contracts"][0]
    return CompanyScopeEvidence(
        True,
        tuple(sorted({**dict(parent.source_hashes), **dict(hashes)}.items())),
        tuple(sorted(set(parent.sources) | set(data["script_hashes"]))),
        (
            *parent.references,
            f"{manifest_id}:sha256={digest}",
            *(
                f"@engine/binaries/victoria3.exe:{contract[key]}"
                for key in ("empty_expression_branch", "default_load", "define_global_write")
            ),
        ),
    )


def company_default_evidence(game: Path, inputs: Mapping[str, bytes]) -> CompanyScopeEvidence:
    """Inventory proof requires the actual define, exact company set and parent chain."""
    company_default_snapshot()
    data, hashes, verified = _verified_manifest(
        game,
        inputs,
        *_company_manifest(default=True),
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
    _, manifest_id, digest = _company_manifest(default=True)
    contract = data["contracts"][0]
    return CompanyScopeEvidence(
        True,
        merged_hashes,
        tuple(sorted(sources)),
        (
            *parent.references,
            f"{manifest_id}:sha256={digest}",
            *(
                f"@engine/binaries/victoria3.exe:{contract[key]}"
                for key in ("empty_expression_branch", "default_load", "define_global_write")
            ),
        ),
    )


def country_evidence(game: Path, inputs: Mapping[str, bytes]) -> CountryScopeEvidence:
    """固定两类国家定义的实际消费者和全部来源。"""
    path, identity, digest = engine_scope_115.manifest("country-definition")
    data, hashes, verified = _verified_manifest(
        game,
        inputs,
        path,
        identity,
        digest,
        "锁定国家定义作用域证据",
    )
    if not verified:
        return CountryScopeEvidence(False, hashes)
    return CountryScopeEvidence(
        True,
        hashes,
        tuple(sorted(data["script_hashes"])),
        (f"{identity}:sha256={digest}",),
    )


def company_evidence(game: Path, inputs: Mapping[str, bytes]) -> CompanyScopeEvidence:
    """仅许可已证明的公司准入与数值成员，不扩散到章程或建设目标。"""
    data, hashes, verified = _verified_manifest(
        game,
        inputs,
        *_company_manifest(),
        "锁定公司作用域证据",
    )
    _validate_company_score_contract(data)
    if not verified:
        return CompanyScopeEvidence(False, hashes)
    _, manifest_id, digest = _company_manifest()
    return CompanyScopeEvidence(
        True,
        hashes,
        tuple(sorted(data["script_hashes"])),
        (f"{manifest_id}:sha256={digest}",),
    )


def law_evidence(game: Path, inputs: Mapping[str, bytes]) -> LawScopeEvidence:
    """仅证明法律候选的国家资格门与定义身份，不授予脚本 law 目标。"""
    path, identity, digest = engine_scope_115.manifest("law")
    data, hashes, verified = _verified_manifest(
        game,
        inputs,
        path,
        identity,
        digest,
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
    references = tuple(data["reference_sites"])
    return LawScopeEvidence(
        True,
        hashes,
        tuple(sorted(data["script_hashes"])),
        (
            f"{identity}:sha256={digest}",
            *(f"@engine/binaries/victoria3.exe:{address}" for address in references),
        ),
    )


def technology_evidence(game: Path, inputs: Mapping[str, bytes]) -> TechnologyScopeEvidence:
    """核对原始字节而不执行游戏；缺少对应平台证据时保持未证明。

    证据只覆盖已观察的科技候选调用点及定义身份，不将本地 candidate
    指针当作脚本可寻址 saved scope。公式下游成本、随机及命令仍归原版。
    """
    path, identity, manifest_hash = engine_scope_115.manifest("technology")
    data, hashes, verified = _verified_manifest(
        game, inputs, path, identity, manifest_hash, "锁定引擎作用域证据"
    )
    if not verified:
        return TechnologyScopeEvidence(False, hashes)
    references = tuple(data["reference_sites"])
    return TechnologyScopeEvidence(
        True,
        hashes,
        (
            f"{identity}:sha256={manifest_hash}",
            *(f"@engine/binaries/victoria3.exe:{address}" for address in references),
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
