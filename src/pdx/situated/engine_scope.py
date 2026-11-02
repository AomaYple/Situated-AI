"""版本固定的只读引擎取证；字段范围证明不授权额外 getter 或 lowering。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

REPO = Path(__file__).resolve().parents[3]
MANIFEST = REPO / "research/situated/victoria3-1.14.5-technology-scope.json"
MANIFEST_ID = "research/situated/victoria3-1.14.5-technology-scope.json"
MANIFEST_SHA256 = "de12ca6de8d06b54f40f78e3fe807e15c271b987fafb45b576b896bc21284c90"
STRATEGY_MANIFEST_ID = "research/situated/victoria3-1.14.5-strategy-scope.json"
STRATEGY_MANIFEST = REPO / STRATEGY_MANIFEST_ID
STRATEGY_MANIFEST_SHA256 = "93947c66bfddd6123633528d66b10a15f334a925b6800ccfa8a4413db85b1944"
COUNTRY_MANIFEST_ID = "research/situated/victoria3-1.14.5-country-definition-scope.json"
COUNTRY_MANIFEST = REPO / COUNTRY_MANIFEST_ID
COUNTRY_MANIFEST_SHA256 = "55aca9f3024ce6d7c607926838df778e1711d5eaad6fcad307acbcf485734a88"
COMPANY_MANIFEST_ID = "research/situated/victoria3-1.14.5-company-scope.json"
COMPANY_MANIFEST = REPO / COMPANY_MANIFEST_ID
COMPANY_MANIFEST_SHA256 = "fb28823262158216c31b892e3f8fae62852e14d9b79a14f7e75c0adcc8229f8d"
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
    "company_evidence",
    "country_evidence",
    "law_evidence",
    "strategy_evidence",
    "technology_evidence",
]
