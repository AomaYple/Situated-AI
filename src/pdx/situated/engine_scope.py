"""版本固定的只读引擎取证；字段范围证明不授权额外 getter 或 lowering。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

REPO = Path(__file__).resolve().parents[3]
MANIFEST_ID = "research/situated/victoria3-1.15.0-technology-scope.json"
MANIFEST = REPO / MANIFEST_ID
MANIFEST_SHA256 = "1c928bf462a07b399f9058256c1c97cd85cda6a036aea73bac47eae6dcd44336"
STRATEGY_MANIFEST_ID = "research/situated/victoria3-1.15.0-strategy-scope.json"
STRATEGY_MANIFEST = REPO / STRATEGY_MANIFEST_ID
STRATEGY_MANIFEST_SHA256 = "de0d8bfa8e65ed08d13a57fa2cf2b7d400ffc9eee6932377aab53af4a8ebd9b4"
COUNTRY_MANIFEST_ID = "research/situated/victoria3-1.15.0-country-definition-scope.json"
COUNTRY_MANIFEST = REPO / COUNTRY_MANIFEST_ID
COUNTRY_MANIFEST_SHA256 = "359268ea61b41c02ed5c847a8ea3348709469c7b8443d6679f279d7b85c10562"
COMPANY_MANIFEST_ID = "research/situated/victoria3-1.15.0-company-scope.json"
COMPANY_MANIFEST = REPO / COMPANY_MANIFEST_ID
COMPANY_MANIFEST_SHA256 = "5c3eb599bec7baaed593eba925817e70e59066bb3276691696b1a2b9e033353a"
COMPANY_DEFAULT_MANIFEST_ID = "research/situated/victoria3-1.15.0-company-default-scope.json"
COMPANY_DEFAULT_MANIFEST = REPO / COMPANY_DEFAULT_MANIFEST_ID
COMPANY_DEFAULT_MANIFEST_SHA256 = "dca3d318f98e6dc6848e0c61edc5db448fdb72090bf40805e3672e8d7dd2403e"
LAW_MANIFEST_ID = "research/situated/victoria3-1.15.0-law-scope.json"
LAW_MANIFEST = REPO / LAW_MANIFEST_ID
LAW_MANIFEST_SHA256 = "290f597a250c00c726abbde45282c6d20c0f207a54f6b888506864887f76f2de"


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


def _manifest_data(raw: bytes) -> dict[str, Any]:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"原生证据包含重复字段：{key}")
            result[key] = value
        return result

    data: dict[str, Any] = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(data, dict):
        raise ValueError("原生证据根节点必须是对象")
    return data


def _verified_manifest(
    game: Path,
    inputs: Mapping[str, bytes],
    manifest: Path,
    manifest_id: str,
    expected_hash: str,
    label: str,
    family: str | None = None,
) -> tuple[dict[str, Any], tuple[tuple[str, str], ...], bool]:
    """共享原字节校验机制；每个 consumer 的许可仍由独立 manifest 决定。"""
    manifest_bytes = manifest.read_bytes()
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest_hash != expected_hash:
        raise ValueError(f"{label}已变化，必须重新独立复核")
    data = _manifest_data(manifest_bytes)
    if family is not None:
        _validate_transport(data, family, label)
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
        for source, digest in {
            **data["script_hashes"],
            **data.get("supporting_script_hashes", {}),
        }.items()
    )
    if verified:
        hashes.update(data["script_hashes"])
        hashes.update(data.get("supporting_script_hashes", {}))
    return data, tuple(sorted(hashes.items())), verified


# Reviewed 1.15.0 semantic blocks, independent of mutable EXE/source transport pins.
# Each digest covers the entire named JSON value (sorted keys, compact ASCII JSON).
# This pins all consumers, parser/member/tuple/enum/type/default/merge evidence,
# rather than retaining a partial set of obsolete address comparisons.
_NATIVE_CONTRACT_HASHES: dict[str, dict[str, str]] = {
    "STRATEGY": {
        "schema": "6b86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4b",
        "evidence_category": "1b351803b41a378a9efd4d34f250afe6055d0237c3839890bad2bfd6ca8b0efc",
        "baseline": "3f4cb597b03b781850163772bf023b2a8dbeaffc28c234221b40e3b5f983ace4",
        "consumers": "59da3af21d462edba2bdbc4360e46e9c0f7c2f2c5b412d73c4d2c2563b159be1",
        "rtti": "62b1cc985c5996a363c6cfdf911f6d9bcc55f6f17ab2356cdda54cb44b86c254",
        "scalar_dispatch": "5ac2bbc97af44517d8ed2b93f7db563894c3a7f3e322105daa2937612f25a01f",
        "additional_scalar_consumers": "e3d90cd23e0ea825424bcd9d46030310511aeb13663d24264d672670c85a48fc",
        "additional_scope_registrations": "a275fae2148ff7d06f20b5b959ee38ef26e2dc2c01c813600eda602ee183fe54",
        "institution_definition_sources": "f21785c53b65e2d2efde4b7461bbf233d55f40bed56ce6b19fa5135f9d185481",
        "institution_definitions": "41366b098c0a02e3229b2d42e62001cd2959221a6f4449b52ecc58ffdebdbaf6",
        "institution_definition_bytes": "c0a3788d9e1a94d07b2550cb8911df2ab7c88f5ccb9e12f7aad7c9629bc1d6d3",
        "stance_definition_sources": "ee4d8c6b3868aea41b0453c45fb849731511898dea94d0d4c21bec462641a1cb",
        "stance_definitions": "5ebe21afeb70e1b6693c3b468558f124b90b991dad17ff569b8375546a57ccff",
        "stance_definition_bytes": "375db6ac1a33b95dcc83014a2258a9bb05e4b69c6ca8ca3d37b685c6f3ddedb8",
        "strategy_score_keys": "ce89d742cd883a9b6a42e895b2916c54c16e698b7f70f78d4b844da2f64e19cf",
        "strategy_field_merges": "1197bb03b7d62f2ba057c745e2d123a919c6f69fbf0766ce1cb612bdc46ad726",
        "native_unprojected_contexts": "ed11b96cb44b65400047307b98adac9d0fcced36e4102ab38b960edab3a8ae4c",
        "law_instance_type": "c95fcc55cfee6ae3752f2b5753cb8f09212c85268cb139c1265af9d39b657712",
        "diplomatic_play_instance_type": "97bbb3f44062fbe75bff215dd715c6fb0e010e79c1de65fc38ee6ccb1619e90e",
        "strategic_region_type": "d2b44d46212819d6d5e18da37419ad14e751f3e4675533cc42e43109a41db4a9",
        "native_proof": "fdf059cfa6ea2113f46717f91f53ad94633e67e937c660d50098eb9cdabc625f",
        "supporting_script_hashes": "14626119947549062c961205c7f0e29bc8cc693c39235f3dda402128364cd1ce",
        "configured_default_script_bytes": "ce305205c4876621fea7d944d0c3da60db95b9d137d4d61cf1fb21449def7f3b",
    },
    "COMPANY": {
        "schema": "6b86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4b",
        "evidence_category": "1b351803b41a378a9efd4d34f250afe6055d0237c3839890bad2bfd6ca8b0efc",
        "baseline": "3f4cb597b03b781850163772bf023b2a8dbeaffc28c234221b40e3b5f983ace4",
        "contracts": "e36c90c2c9b5330456f4f18f86b1a1568474a26fed3c48b17f2915b0dbfeaf4f",
        "database_installation": "8fea7e81103da038a7e0b3ea3951e8ab0dcb8a7bcdd1ebeef20a75f8d10506b5",
        "protected_native_boundaries": "15e177a6be369f325f9da37c16c50270b2b03d924e92255405db3704195f4f34",
    },
    "COMPANY_DEFAULT": {
        "schema": "6b86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4b",
        "evidence_category": "1b351803b41a378a9efd4d34f250afe6055d0237c3839890bad2bfd6ca8b0efc",
        "baseline": "3f4cb597b03b781850163772bf023b2a8dbeaffc28c234221b40e3b5f983ace4",
        "contracts": "b5d333f9899cd73e44765a444e16bffa57e972937b3ecdde7008f36307da1386",
        "implicit_companies": "08dbd56cda59fc0f267163fa29fbcf069708d7c610d70ebd5e9a582d399bd534",
    },
    "LAW": {
        "schema": "6b86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4b",
        "evidence_category": "1b351803b41a378a9efd4d34f250afe6055d0237c3839890bad2bfd6ca8b0efc",
        "baseline": "3f4cb597b03b781850163772bf023b2a8dbeaffc28c234221b40e3b5f983ace4",
        "contract": "7f43fb34cc55b5eb31e26d09bd1ec0b049ebc0cf82478181dbfc47e7ead13937",
        "native_contract_detail": "e70543b2577881704cd6e3e494a4783a56319f639da97143525d900f78d7c9b0",
        "database_installation": "a9e299196bae351c241afa1f782752cba84af539775435da577b01d2e6913fa9",
        "protected_native_boundaries": "cbbf883e6ef242e19cd344b164b0e86408b0814e8b0d9534a701c2829313424a",
        "control_flow_checks": "34ae6220ada2c39ff1d470a38b990954992d0ca7c4ed322b6ad97f8835211169",
    },
    "COUNTRY": {
        "schema": "6b86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4b",
        "evidence_category": "1b351803b41a378a9efd4d34f250afe6055d0237c3839890bad2bfd6ca8b0efc",
        "baseline": "3f4cb597b03b781850163772bf023b2a8dbeaffc28c234221b40e3b5f983ace4",
        "contracts": "3189d6155f047e94347793c98cebd7209c0ab2247a2b53736fb1f4678a1990d9",
        "database_installations": "4ebc1ee9e16b8c31a4cb8dce7145a52b25ef9ed0b1ed7396c6efc551194eb267",
        "protected_native_boundaries": "93fce818b43492270ca6f4b02bfa1295de536f002befef1ca194b6af2a22789f",
    },
}


# Descriptive metadata has no reason to vary with synthetic EXE/source transport.
_NATIVE_METADATA_HASHES = {
    "STRATEGY": {
        "limits": "54e194180fc96e20b60beb5703977491b494f839eae52dd7e2e68d922da12db1",
        "historical_comparison": "d483f0f3cf597d6fc8ae165d433e933477755fc824501a8c765c7a9e8ebec2b0",
        "revision": "324e635150952ef001e0318f4c7b3123c033ac061377184146954a60b5878b1b",
    },
    "COMPANY": {
        "status": "3fa80e1e24abf883f5d441fdb87d513547bb3fcc4b625c778dbcd5e172493b7e",
        "limits": "f7c6232c4f7b7bc1ff83f88ca3af8c7f06bccb044e88cc96ec5df54d533d7efe",
    },
    "COMPANY_DEFAULT": {
        "status": "3fa80e1e24abf883f5d441fdb87d513547bb3fcc4b625c778dbcd5e172493b7e",
        "limits": "d036287c8c28cd3b042e813058c89e5a3c02d98f6ebc136e139306d035da648e",
    },
    "LAW": {
        "status": "3fa80e1e24abf883f5d441fdb87d513547bb3fcc4b625c778dbcd5e172493b7e",
        "limits": "49b014a6838fd7262b8975e42e0793011cc31d128dd1def8fa76588099f47760",
        "inventory_snapshot": "3cd23de32446b6b165f99cc65bdffbde633f5ae1e0060cab3d542978e4b122f1",
    },
    "COUNTRY": {
        "status": "3fa80e1e24abf883f5d441fdb87d513547bb3fcc4b625c778dbcd5e172493b7e",
        "limits": "e5704a3dfc03db5d42a0d7edc385f22668914728cfd59bba81e8a70161876ff2",
    },
}
for _family, _metadata in _NATIVE_METADATA_HASHES.items():
    _NATIVE_CONTRACT_HASHES[_family].update(_metadata)


_SOURCE_DIRECTORIES = {
    "STRATEGY": ("common/ai_strategies",),
    "COMPANY": ("common/company_types",),
    "COMPANY_DEFAULT": ("common/company_types", "common/defines"),
    "LAW": ("common/laws",),
    "COUNTRY": ("common/country_creation", "common/country_formation"),
}
_TRANSPORT_KEYS = {
    family: {"exe", "observations", "script_hashes"} for family in _SOURCE_DIRECTORIES
}
_TRANSPORT_KEYS["COMPANY_DEFAULT"].add("parent_scope_manifest")
_TRANSPORT_KEYS["LAW"].add("all_law_source_hashes")


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _is_hex(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"0x[0-9a-fA-F]+", value) is not None


def _validate_transport(data: Mapping[str, Any], family: str, label: str) -> None:
    """Reject unknown family/nested metadata while permitting valid synthetic repins."""

    def require(condition: bool, field: str) -> None:
        if not condition:
            raise ValueError(f"{label}未知字段或元数据形状不一致：{field}")

    require(set(data) == set(_NATIVE_CONTRACT_HASHES[family]) | _TRANSPORT_KEYS[family], "root")
    exe = data["exe"]
    optional_exe = {"path", "image_base"} if family == "COUNTRY" else {"path"}
    require(isinstance(exe, dict), "exe")
    require({"sha256", "bytes"} <= set(exe) <= {"sha256", "bytes"} | optional_exe, "exe")
    require(_is_hash(exe["sha256"]), "exe.sha256")
    require(type(exe["bytes"]) is int and exe["bytes"] > 0, "exe.bytes")
    if "path" in exe:
        require(exe["path"] == "binaries/victoria3.exe", "exe.path")
    if "image_base" in exe:
        require(_is_hex(exe["image_base"]), "exe.image_base")
    observations = data["observations"]
    require(isinstance(observations, list) and bool(observations), "observations")
    for point in observations:
        require(isinstance(point, dict), "observations[]")
        require(
            set(point)
            in ({"label", "file_offset", "bytes"}, {"label", "file_offset", "bytes", "va", "rva"}),
            "observations[]",
        )
        require(isinstance(point["label"], str) and bool(point["label"]), "observations.label")
        require(_is_hex(point["file_offset"]), "observations.file_offset")
        require(
            isinstance(point["bytes"], str)
            and re.fullmatch(r"(?:[0-9a-fA-F]{2})+", point["bytes"]) is not None,
            "observations.bytes",
        )
        if "va" in point:
            require(_is_hex(point["va"]) and _is_hex(point["rva"]), "observations.va/rva")
    for key in ("script_hashes", "all_law_source_hashes"):
        if key not in data:
            continue
        sources = data[key]
        require(isinstance(sources, dict), key)
        for source, digest in sources.items():
            require(
                isinstance(source, str)
                and bool(source)
                and not source.startswith("/")
                and not any(part in {"", ".", ".."} for part in source.split("/"))
                and "\\" not in source
                and ":" not in source
                and source.endswith(".txt")
                and any(
                    f"/{directory}/" in "/" + source for directory in _SOURCE_DIRECTORIES[family]
                ),
                key,
            )
            require(_is_hash(digest), key)
    if family == "LAW":
        require(
            all(
                data["all_law_source_hashes"].get(source) == digest
                for source, digest in data["script_hashes"].items()
            ),
            "all_law_source_hashes.predicate_subset",
        )
    if family == "COMPANY_DEFAULT":
        parent = data["parent_scope_manifest"]
        require(
            isinstance(parent, dict) and set(parent) == {"path", "sha256"}, "parent_scope_manifest"
        )
        require(
            parent["path"] == COMPANY_MANIFEST_ID and _is_hash(parent["sha256"]),
            "parent_scope_manifest",
        )


def _validate_native_contracts(data: Mapping[str, Any], family: str, label: str) -> None:
    _validate_transport(data, family, label)
    for key, expected in _NATIVE_CONTRACT_HASHES[family].items():
        raw = json.dumps(data.get(key), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        if hashlib.sha256(raw.encode()).hexdigest() != expected:
            detail = {
                "consumers": "消费者字段合同",
                "strategy_score_keys": "评分枚举",
                "diplomatic_play_instance_type": "外交博弈实例",
                "contract": "的字段合同",
            }.get(key, key)
            raise ValueError(f"{label}{detail}{'不一致' if key == 'contract' else '证据不一致'}")


def _validate_strategy_contracts(data: Mapping[str, Any]) -> None:
    """Pin all 33 contracts and all current native semantics after transport repinning."""
    _validate_native_contracts(data, "STRATEGY", "锁定策略")


def _source_set(game: Path, directories: tuple[str, ...]) -> set[str]:
    return {
        path.relative_to(game).as_posix()
        for path in game.rglob("*.txt")
        if path.is_file()
        and any(
            f"/{directory}/" in "/" + path.relative_to(game).as_posix() for directory in directories
        )
    }


def _require_source_set(
    game: Path, directories: tuple[str, ...], expected: Mapping[str, str], label: str
) -> None:
    if _source_set(game, directories) != set(expected):
        raise ValueError(f"当前{label}原件集合与锁定证据不同，可能存在新增或覆盖定义")


def _input_source_closure(
    inputs: Mapping[str, bytes], directories: tuple[str, ...], expected: Mapping[str, str]
) -> bool:
    actual = {
        source
        for source in inputs
        if source.endswith(".txt")
        and any(f"/{directory}/" in "/" + source for directory in directories)
    }
    return actual == set(expected) and all(
        source in inputs and hashlib.sha256(inputs[source]).hexdigest() == digest
        for source, digest in expected.items()
    )


def _live_inputs(
    game: Path, directories: tuple[str, ...], required: Mapping[str, str]
) -> dict[str, bytes]:
    return {
        source: (game / source).read_bytes()
        for source in _source_set(game, directories) | set(required)
    }


def strategy_evidence(game: Path, inputs: Mapping[str, bytes]) -> StrategyScopeEvidence:
    """逐字段核对策略成员、真实消费者及原字节，不能从容器推导其他字段。"""
    data, hashes, verified = _verified_manifest(
        game,
        inputs,
        STRATEGY_MANIFEST,
        STRATEGY_MANIFEST_ID,
        STRATEGY_MANIFEST_SHA256,
        "锁定策略作用域证据",
        family="STRATEGY",
    )
    _validate_strategy_contracts(data)
    verified = verified and all(
        _input_source_closure(inputs, directories, expected)
        for directories, expected in (
            (("common/ai_strategies",), data["script_hashes"]),
            (("common/institutions",), data["institution_definition_sources"]),
            (("common/ai_strategic_region_stance_types",), data["stance_definition_sources"]),
        )
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


def strategy_snapshot() -> bytes:
    """Read current pinned static evidence without claiming live EXE verification."""
    raw = STRATEGY_MANIFEST.read_bytes()
    if hashlib.sha256(raw).hexdigest() != STRATEGY_MANIFEST_SHA256:
        raise ValueError("锁定策略作用域证据已变化，必须重新独立复核")
    _validate_strategy_contracts(_manifest_data(raw))
    return raw


def verify_strategy_game(game: Path) -> StrategyScopeEvidence:
    """Require actual pinned scripts and EXE at the production boundary."""
    data = _manifest_data(strategy_snapshot())
    sources = {**data["script_hashes"], **data["supporting_script_hashes"]}
    inputs = _live_inputs(
        game,
        ("common/ai_strategies", "common/institutions", "common/ai_strategic_region_stance_types"),
        sources,
    )
    proof = strategy_evidence(game, inputs)
    if not proof.verified:
        raise ValueError(
            "当前策略、制度定义或区域 stance 定义原件集合、脚本、支持来源或 EXE 与锁定证据不一致"
        )
    return proof


def company_snapshot() -> bytes:
    """固定公司候选证据；不把定义身份当作脚本 company 目标。"""
    raw = COMPANY_MANIFEST.read_bytes()
    if hashlib.sha256(raw).hexdigest() != COMPANY_MANIFEST_SHA256:
        raise ValueError("锁定公司作用域证据已变化，必须重新独立复核")
    _validate_native_contracts(_manifest_data(raw), "COMPANY", "锁定公司作用域证据")
    return raw


def verify_company_game(game: Path) -> CompanyScopeEvidence:
    """生产公司选择必须重新核对当前原版脚本和引擎字节。"""
    data = _manifest_data(company_snapshot())
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
    data = _manifest_data(raw)
    _validate_native_contracts(data, "COMPANY_DEFAULT", "锁定公司缺省权重的精确合同或定义身份")
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
    data = _manifest_data(company_default_snapshot())
    inputs = {source: (game / source).read_bytes() for source in data["script_hashes"]}
    _, hashes, verified = _verified_manifest(
        game,
        inputs,
        COMPANY_DEFAULT_MANIFEST,
        COMPANY_DEFAULT_MANIFEST_ID,
        COMPANY_DEFAULT_MANIFEST_SHA256,
        "锁定公司缺省权重证据",
        family="COMPANY_DEFAULT",
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
            f"@engine/binaries/victoria3.exe:{data['contracts'][0]['empty_expression_branch']}",
            f"@engine/binaries/victoria3.exe:{data['contracts'][0]['default_load']}",
            f"@engine/binaries/victoria3.exe:{data['contracts'][0]['define_global_write']}",
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
        family="COMPANY_DEFAULT",
    )
    parent = company_evidence(game, inputs)
    parent_data = _manifest_data(company_snapshot())
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
            f"@engine/binaries/victoria3.exe:{data['contracts'][0]['empty_expression_branch']}",
            f"@engine/binaries/victoria3.exe:{data['contracts'][0]['default_load']}",
            f"@engine/binaries/victoria3.exe:{data['contracts'][0]['define_global_write']}",
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
        family="COUNTRY",
    )
    _validate_native_contracts(data, "COUNTRY", "锁定国家定义作用域证据")
    actual_sources = {
        source
        for source in inputs
        if source.endswith(".txt")
        and (
            "/common/country_creation/" in "/" + source
            or "/common/country_formation/" in "/" + source
        )
    }
    verified = verified and actual_sources == set(data["script_hashes"])
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
        family="COMPANY",
    )
    _validate_native_contracts(data, "COMPANY", "锁定公司作用域证据")
    actual_sources = {
        source
        for source in inputs
        if source.endswith(".txt") and ("/common/company_types/" in "/" + source)
    }
    verified = verified and actual_sources == set(data["script_hashes"])
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
        family="LAW",
    )
    _validate_native_contracts(data, "LAW", "锁定法律作用域证据")
    sources = data["all_law_source_hashes"]
    verified = verified and _input_source_closure(inputs, ("common/laws",), sources)
    if verified:
        hashes = tuple(sorted({**dict(hashes), **sources}.items()))
    if not verified:
        return LawScopeEvidence(False, hashes)
    return LawScopeEvidence(
        True,
        hashes,
        tuple(sorted(data["script_hashes"])),
        (
            f"{LAW_MANIFEST_ID}:sha256={LAW_MANIFEST_SHA256}",
            f"@engine/binaries/victoria3.exe:{data['native_contract_detail']['qualification_call']}",  # 实际候选资格门
            f"@engine/binaries/victoria3.exe:{data['native_contract_detail']['consumer']}",  # 国家触发器包装器
            f"@engine/binaries/victoria3.exe:{data['native_contract_detail']['parser']}",  # ai_will_do 精确解析分支
        ),
    )


def verify_country_game(game: Path) -> CountryScopeEvidence:
    """Verify both complete current country definition families against real installation bytes."""
    data = _manifest_data(COUNTRY_MANIFEST.read_bytes())
    _validate_native_contracts(data, "COUNTRY", "锁定国家定义作用域证据")
    _require_source_set(
        game,
        ("common/country_creation", "common/country_formation"),
        data["script_hashes"],
        "国家定义",
    )
    proof = country_evidence(
        game, {source: (game / source).read_bytes() for source in data["script_hashes"]}
    )
    if not proof.verified:
        raise ValueError("当前原版国家定义或 EXE 与锁定证据不一致")
    return proof


def verify_law_game(game: Path) -> LawScopeEvidence:
    """Verify all law source files, including definitions without ai_will_do."""
    data = _manifest_data(LAW_MANIFEST.read_bytes())
    _validate_native_contracts(data, "LAW", "锁定法律作用域证据")
    sources = data["all_law_source_hashes"]
    proof = law_evidence(game, _live_inputs(game, ("common/laws",), sources))
    if not proof.verified:
        raise ValueError("当前原版法律原件集合、脚本或 EXE 与锁定证据不一致")
    return proof


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
            "@engine/binaries/victoria3.exe:0x141902e89",  # exact technology parser
            "@engine/binaries/victoria3.exe:0x141791890",  # Country scope tag
            "@engine/binaries/victoria3.exe:0x1415d0690",  # base formula evaluation
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
    "verify_country_game",
    "verify_law_game",
    "verify_strategy_game",
]
