"""ENG-00 的唯一输入交接 schema；不授予原版 reader 或生产写入权限。

四份合同共享同一 epoch。枚举明确区分读取、解析、语义、合法性和接线；
序列化入口拒绝未知字段、重复键、错误类型及非有限数值。生产者须先建立
真实分母和证据，本模块只核验声明的一致性，不代签证据的真实性。
"""

import hashlib
import json
import math
import re
import types
from dataclasses import asdict, dataclass, fields, is_dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Literal, NoReturn, Union, get_args, get_origin, get_type_hints

if TYPE_CHECKING:
    from collections.abc import Iterable

SCHEMA: Literal[1] = 1
Availability = Literal["yes", "no", "unknown"]
Completeness = Literal["complete", "partial", "failed", "unknown"]
ParseStatus = Literal["not_attempted", "failed", "partial", "complete", "not_applicable"]
ProofStatus = Literal["proven", "unknown", "unsupported", "not_implemented", "not_applicable"]
EvidenceKind = Literal["static_check", "snapshot", "simulation", "runtime", "inference"]
EdgeRelation = Literal["binds", "reads", "depends_on", "generates", "packages"]


class InputContractError(ValueError):
    """稳定 code 供调用方映射：检查失败 1，装载/用法或缺前置条件 2。

    不改写现有 CLI 的退出码 3（crosscheck 的输入不可比）。研究合同保留
    unknown 不等于失败；只有调用方要求完整交接时才拒绝不完整声明。
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def _fail(code: str, message: str) -> NoReturn:
    raise InputContractError(code, message)


def _text(value: str, name: str) -> None:
    if not value.strip() or "\x00" in value:
        _fail("invalid_value", f"{name} 必须是非空文本")


def _digest(value: str) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        _fail("invalid_digest", "摘要必须是小写 SHA-256")


def _path(value: str) -> None:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or ":" in value
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or "\x00" in value
    ):
        _fail("invalid_path", f"相对 POSIX 路径无效：{value!r}")


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """命名空间内的原始字节身份；path 不能跨命名空间解释。"""

    namespace: Literal["installation", "evidence", "repository", "generated", "package"]
    path: str
    sha256: str

    def __post_init__(self) -> None:
        _path(self.path)
        _digest(self.sha256)


@dataclass(frozen=True, slots=True)
class DlcState:
    id: str
    installed: Availability
    owned: Availability
    enabled: Availability
    script_available: Availability


@dataclass(frozen=True, slots=True)
class CaptureCheck:
    """开始/结束独立盘点身份；unknown 或 changed 不能签完整 epoch。"""

    checked_at: str
    installation_sha256: str
    file_set_sha256: str
    status: Literal["stable", "changed", "unknown"]

    def __post_init__(self) -> None:
        _digest(self.installation_sha256)
        _digest(self.file_set_sha256)


@dataclass(frozen=True, slots=True)
class SnapshotProvenance:
    kind: Literal["installation", "raw_epoch", "snapshot"]
    source: str
    artifact: ArtifactRef | None
    parent_epoch_id: str | None

    def __post_init__(self) -> None:
        if self.parent_epoch_id is not None:
            _digest(self.parent_epoch_id)
        if self.kind != "installation" and self.artifact is None:
            _fail("missing_evidence", "快照和 raw epoch 必须保留来源摘要")


@dataclass(frozen=True, slots=True)
class InputIdentity:
    installation_root: str
    version: str
    build_id: str
    branch: str
    dlcs: tuple[DlcState, ...]
    identity_sources: tuple[ArtifactRef, ...]
    file_count: int
    file_set_sha256: str
    implementation: tuple[ArtifactRef, ...]
    contracts: tuple[ArtifactRef, ...]
    start: CaptureCheck
    end: CaptureCheck
    provenance: SnapshotProvenance
    completeness: Completeness
    schema: Literal[1] = SCHEMA
    kind: Literal["input_identity"] = "input_identity"

    def __post_init__(self) -> None:
        _digest(self.file_set_sha256)

    @property
    def epoch_id(self) -> str:
        """规范 JSON 的内容身份，不接受调用方另填自由 epoch 标签。"""
        return hashlib.sha256(dumps_contract(self).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    message: str
    evidence: ArtifactRef | None


@dataclass(frozen=True, slots=True)
class InventoryRecord:
    path: str
    size: int | None
    sha256: str | None
    category: str
    source_layer: str
    read_status: Literal["read", "failed", "not_read"]
    parse_status: ParseStatus
    raw: ArtifactRef | None
    diagnostics: tuple[Diagnostic, ...]
    packages: tuple[str, ...]
    dlcs: tuple[str, ...]
    overrides: tuple[str, ...]
    completeness: Completeness

    def __post_init__(self) -> None:
        _path(self.path)
        if self.sha256 is not None:
            _digest(self.sha256)
        if self.read_status == "read" and (self.sha256 is None or self.size is None):
            _fail("incomplete_record", "已读取文件必须有大小和原字节摘要")
        if self.raw is not None and self.raw.sha256 != self.sha256:
            _fail("identity_mismatch", "raw 原件摘要与文件摘要不一致")
        if self.read_status != "read" and not self.diagnostics:
            _fail("missing_diagnostic", "未读取/读取失败必须有诊断")
        if self.parse_status in {"failed", "partial"} and not self.diagnostics:
            _fail("missing_diagnostic", "解析失败/部分解析必须有诊断")


@dataclass(frozen=True, slots=True)
class InputInventory:
    epoch_id: str
    records: tuple[InventoryRecord, ...]
    completeness: Completeness
    diagnostics: tuple[Diagnostic, ...]
    schema: Literal[1] = SCHEMA
    kind: Literal["input_inventory"] = "input_inventory"

    def __post_init__(self) -> None:
        _digest(self.epoch_id)


@dataclass(frozen=True, slots=True)
class RoleBinding:
    role: str
    object_type: str


@dataclass(frozen=True, slots=True)
class DlcCondition:
    id: str
    field: Literal["installed", "owned", "enabled", "script_available"]
    required: Availability


@dataclass(frozen=True, slots=True)
class CapabilityKey:
    """ARC-C01 的完整精确键；名称相同不能跨上下文借用合法性。"""

    version: str
    build_id: str
    source: ArtifactRef
    operation: str
    reader: str | None
    consumer: str
    actor: RoleBinding
    targets: tuple[RoleBinding, ...]
    auxiliaries: tuple[RoleBinding, ...]
    scope_path: tuple[str, ...]
    timing: str
    dlc_conditions: tuple[DlcCondition, ...]


@dataclass(frozen=True, slots=True)
class CapabilityStages:
    discovered: bool
    legality: ProofStatus
    implementation: ProofStatus
    lowering: ProofStatus
    production: ProofStatus
    runtime: ProofStatus


@dataclass(frozen=True, slots=True)
class CostRecord:
    status: Literal["known", "unknown"]
    unit: str
    amount: float | None
    budget: float | None
    notes: str

    def __post_init__(self) -> None:
        if self.status == "unknown" and self.amount is not None:
            _fail("unknown_cost", "未知成本不能填数值或当作零")
        if self.status == "known" and self.amount is None:
            _fail("unknown_cost", "已知成本必须有数值")


@dataclass(frozen=True, slots=True)
class CapabilityRecord:
    epoch_id: str
    key: CapabilityKey
    parse_status: ParseStatus
    semantic_status: Literal["recognized", "partial", "unknown", "unsupported"]
    stages: CapabilityStages
    unit: str
    availability: str
    freshness: str
    unknown_policy: str
    cost: CostRecord
    dispositions: tuple[
        Literal[
            "legal_read_candidate",
            "legal_write_candidate",
            "static_context",
            "research_only",
            "native_retained",
            "excluded_with_reason",
            "unresolved",
        ],
        ...,
    ]
    evidence_kind: EvidenceKind
    evidence: tuple[ArtifactRef, ...]
    diagnostics: tuple[Diagnostic, ...]
    schema: Literal[1] = SCHEMA
    kind: Literal["capability_record"] = "capability_record"

    def __post_init__(self) -> None:
        _digest(self.epoch_id)
        if not self.dispositions:
            _fail("missing_disposition", "能力记录必须至少登记一种用途，待研究可使用 unresolved")
        if self.stages.legality == "proven":
            if not self.evidence:
                _fail("missing_evidence", "合法能力证明必须有对应原版证据")
            if self.key.reader is None and not {
                "legal_write_candidate",
                "native_retained",
            }.intersection(self.dispositions):
                _fail("invalid_operation", "无 reader 的合法操作必须明确写操作或原版保留用途")
        if self.stages.lowering == "proven" and (
            self.stages.legality != "proven" or self.stages.implementation != "proven"
        ):
            _fail("invalid_stage", "降低证明必须有合法且已实现的能力")
        if self.stages.production == "proven" and self.stages.lowering != "proven":
            _fail("invalid_stage", "生产绑定必须有降低证明")
        if self.stages.runtime == "proven" and self.evidence_kind != "runtime":
            _fail("invalid_stage", "运行证明必须标明 runtime 证据")

    @property
    def capability_id(self) -> str:
        return hashlib.sha256(_json(asdict(self.key)).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ClosureNode:
    id: str
    role: Literal["action", "reader", "native_source", "dependency", "generated", "package"]
    artifact: ArtifactRef | None
    capability_id: str | None


@dataclass(frozen=True, slots=True)
class ClosureEdge:
    source: str
    target: str
    relation: EdgeRelation


@dataclass(frozen=True, slots=True)
class UnknownFrontier:
    node_id: str
    reason: str
    blocks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConsumerClosure:
    epoch_id: str
    consumer: str
    nodes: tuple[ClosureNode, ...]
    edges: tuple[ClosureEdge, ...]
    unknown_frontier: tuple[UnknownFrontier, ...]
    completeness: Completeness
    schema: Literal[1] = SCHEMA
    kind: Literal["consumer_closure"] = "consumer_closure"

    def __post_init__(self) -> None:
        _digest(self.epoch_id)


Contract = InputIdentity | InputInventory | CapabilityRecord | ConsumerClosure
_CONTRACTS = {
    "input_identity": InputIdentity,
    "input_inventory": InputInventory,
    "capability_record": CapabilityRecord,
    "consumer_closure": ConsumerClosure,
}


def _json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _typed(annotation: object, value: object, location: str, *, decode: bool) -> object:
    """只支持本模块冻结的数据形状，不解析开放式或任意外部 schema。"""
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Literal:
        if not any(type(value) is type(item) and value == item for item in args):
            _fail("invalid_enum", location)
        return value
    if origin in {types.UnionType, Union}:
        errors = []
        for option in args:
            try:
                return _typed(option, value, location, decode=decode)
            except InputContractError as error:
                errors.append(error)
        raise errors[0]
    if origin is tuple:
        expected = list if decode else tuple
        if type(value) is not expected:
            _fail("invalid_type", location)
        assert isinstance(value, (tuple, list))
        return tuple(
            _typed(args[0], item, f"{location}[{index}]", decode=decode)
            for index, item in enumerate(value)
        )
    if isinstance(annotation, type) and is_dataclass(annotation):
        if decode:
            if type(value) is not dict:
                _fail("invalid_type", location)
            assert isinstance(value, dict)
            expected_fields = {field.name for field in fields(annotation)}
            if set(value) != expected_fields:
                _fail("invalid_fields", f"{location}: {sorted(set(value) ^ expected_fields)}")
            hints = get_type_hints(annotation)
            return annotation(
                **{
                    name: _typed(hints[name], item, f"{location}.{name}", decode=True)
                    for name, item in value.items()
                }
            )
        if type(value) is not annotation:
            _fail("invalid_type", location)
        hints = get_type_hints(annotation)
        return annotation(
            **{
                field.name: _typed(
                    hints[field.name],
                    getattr(value, field.name),
                    f"{location}.{field.name}",
                    decode=False,
                )
                for field in fields(annotation)
            }
        )
    if annotation is float:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            _fail("invalid_number", location)
        try:
            number = float(value)
        except OverflowError:
            _fail("invalid_number", location)
        if not math.isfinite(number) or number < 0:
            _fail("invalid_number", location)
        return number
    if type(value) is not annotation:
        _fail("invalid_type", location)
    if isinstance(value, str):
        _text(value, location)
    if type(value) is int and value < 0:
        _fail("invalid_number", location)
    return value


def dumps_contract(contract: Contract) -> str:
    """输出无 BOM 的规范 JSON；严格核验并把受支持成本数值归一为有限 float。"""
    if type(contract) not in _CONTRACTS.values():
        _fail("invalid_contract", "未知交接合同")
    normalized = _typed(type(contract), contract, contract.kind, decode=False)
    assert isinstance(
        normalized, (InputIdentity, InputInventory, CapabilityRecord, ConsumerClosure)
    )
    return _json(asdict(normalized))


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate_json_key", key)
        result[key] = value
    return result


def loads_contract(text: str) -> Contract:
    """只接受四份 schema 1 合同；调用方用 validate_handoff 核对整个交接。"""
    try:
        value = json.loads(text, object_pairs_hook=_unique_object)
    except (ValueError, TypeError) as error:
        if isinstance(error, InputContractError):
            raise
        raise InputContractError("invalid_json", "交接合同不是有效 JSON") from error
    if (
        type(value) is not dict
        or type(value.get("kind")) is not str
        or value["kind"] not in _CONTRACTS
    ):
        _fail("invalid_contract", "缺少已知 kind")
    contract = _typed(_CONTRACTS[value["kind"]], value, value["kind"], decode=True)
    assert isinstance(contract, (InputIdentity, InputInventory, CapabilityRecord, ConsumerClosure))
    return contract


def file_set_digest(records: Iterable[InventoryRecord]) -> str:
    """独立分母的唯一摘要口径：排序后路径、大小、原字节摘要（含未知）。"""
    rows = sorted((record.path, record.size, record.sha256) for record in records)
    paths = [row[0] for row in rows]
    if len(paths) != len(set(paths)) or len(paths) != len({path.casefold() for path in paths}):
        _fail("duplicate_path", "安装路径重复或大小写冲突")
    return hashlib.sha256(_json(rows).encode("utf-8")).hexdigest()


def validate_handoff(
    identity: InputIdentity,
    inventory: InputInventory,
    capabilities: tuple[CapabilityRecord, ...],
    closure: ConsumerClosure,
    *,
    require_complete: bool = False,
) -> None:
    """核验 epoch、分母、原件引用、能力精确键、闭包及未知前沿。

    partial 可被研究工具消费。生产或冻结完整证据的调用方必须显式要求
    require_complete；即使如此也只证明声明闭合，不证明真实引擎行为。
    """
    all_contracts: tuple[Contract, ...] = (identity, inventory, *capabilities, closure)
    for item in all_contracts:
        dumps_contract(item)
    epoch = identity.epoch_id
    dependents: tuple[InputInventory | CapabilityRecord | ConsumerClosure, ...] = (
        inventory,
        *capabilities,
        closure,
    )
    if any(item.epoch_id != epoch for item in dependents):
        _fail("epoch_mismatch", "四份交接合同必须来自同一 epoch")
    actual_digest = file_set_digest(inventory.records)
    if identity.file_count != len(inventory.records) or identity.file_set_sha256 != actual_digest:
        _fail("denominator_mismatch", "安装分母的数量或摘要不匹配")
    if len({dlc.id for dlc in identity.dlcs}) != len(identity.dlcs):
        _fail("duplicate_dlc", "DLC 身份重复")
    files = {record.path: record for record in inventory.records}
    known_dlcs = {dlc.id for dlc in identity.dlcs}
    for record in inventory.records:
        if not set(record.dlcs) <= known_dlcs:
            _fail("unknown_dlc", "安装记录引用未登记 DLC")
        for override in record.overrides:
            _path(override)
            if override not in files:
                _fail("dangling_override", "覆盖关系引用不在完整分母中的路径")

    def installation_ref(reference: ArtifactRef) -> None:
        if reference.namespace != "installation":
            return
        record = files.get(reference.path)
        if record is None or record.sha256 != reference.sha256:
            _fail("source_mismatch", f"原版来源不在当前分母或摘要漂移：{reference.path}")

    for reference in identity.identity_sources:
        installation_ref(reference)
    capability_ids = {capability.capability_id for capability in capabilities}
    if len(capability_ids) != len(capabilities):
        _fail("duplicate_capability", "完整精确能力键重复")
    for capability in capabilities:
        if (capability.key.version, capability.key.build_id) != (
            identity.version,
            identity.build_id,
        ):
            _fail("identity_mismatch", "能力版本/构建与输入身份不符")
        installation_ref(capability.key.source)
        for reference in capability.evidence:
            installation_ref(reference)
        role_names = [
            role.role
            for role in (capability.key.actor, *capability.key.targets, *capability.key.auxiliaries)
        ]
        if len(role_names) != len(set(role_names)):
            _fail("duplicate_role", "精确上下文的角色名重复")
        if any(condition.id not in known_dlcs for condition in capability.key.dlc_conditions):
            _fail("unknown_dlc", "能力引用未登记 DLC")
    nodes = {node.id: node for node in closure.nodes}
    if len(nodes) != len(closure.nodes):
        _fail("duplicate_node", "闭包节点重复")
    frontier = {item.node_id for item in closure.unknown_frontier}
    if len(frontier) != len(closure.unknown_frontier) or not frontier <= nodes.keys():
        _fail("invalid_frontier", "未知前沿必须唯一且引用真实节点")
    for node in closure.nodes:
        if node.artifact is None and node.id not in frontier:
            _fail("missing_evidence", f"闭包节点缺少路径/摘要或未知前沿：{node.id}")
        if node.artifact is not None:
            installation_ref(node.artifact)
        if node.role == "reader" and node.capability_id not in capability_ids:
            _fail("dangling_capability", "reader 节点必须引用本次交接的精确能力")
        if node.capability_id is not None:
            if node.capability_id not in capability_ids:
                _fail("dangling_capability", "闭包能力引用不存在")
            capability = next(
                item for item in capabilities if item.capability_id == node.capability_id
            )
            if capability.key.consumer != closure.consumer:
                _fail("consumer_mismatch", "闭包不能借用另一消费者的能力证明")
            if node.role == "reader" and capability.key.reader is None:
                _fail("invalid_operation", "闭包 reader 节点不能引用纯写入或原版保留操作")
    edge_keys = [(edge.source, edge.target, edge.relation) for edge in closure.edges]
    if len(edge_keys) != len(set(edge_keys)):
        _fail("duplicate_edge", "闭包边重复")
    legal_endpoints = {
        "binds": {("action", "reader")},
        "reads": {("reader", "native_source")},
        "depends_on": {
            ("native_source", "native_source"),
            ("native_source", "dependency"),
            ("dependency", "native_source"),
            ("dependency", "dependency"),
        },
        "generates": {("native_source", "generated"), ("dependency", "generated")},
        "packages": {("generated", "package")},
    }
    outgoing: dict[str, set[str]] = {node: set() for node in nodes}
    incoming: dict[str, set[str]] = {node: set() for node in nodes}
    for edge in closure.edges:
        if edge.source not in nodes or edge.target not in nodes:
            _fail("dangling_edge", "闭包边引用不存在的节点")
        endpoints = nodes[edge.source].role, nodes[edge.target].role
        if endpoints not in legal_endpoints[edge.relation]:
            _fail("invalid_edge", "闭包关系与端点类型不符")
        outgoing[edge.source].add(edge.target)
        incoming[edge.target].add(edge.source)
    pending = [node for node in nodes if not incoming[node]]
    degrees = {node: len(parents) for node, parents in incoming.items()}
    visited = 0
    while pending:
        source = pending.pop()
        visited += 1
        for target in outgoing[source]:
            degrees[target] -= 1
            if degrees[target] == 0:
                pending.append(target)
    if visited != len(nodes):
        _fail("cyclic_closure", "消费闭包不能含同轮循环依赖")

    def reachable_from(roots: set[str], graph: dict[str, set[str]]) -> set[str]:
        reachable = set(roots)
        stack = list(roots)
        while stack:
            for target in graph[stack.pop()] - reachable:
                reachable.add(target)
                stack.append(target)
        return reachable

    if require_complete:
        if any(item.completeness != "complete" for item in (identity, inventory, closure)):
            _fail("incomplete_handoff", "要求完整交接但合同仍为不完整")
        if (
            frontier
            or not identity.identity_sources
            or not identity.implementation
            or not identity.contracts
        ):
            _fail("incomplete_handoff", "完整交接不能缺少来源/工具/合同或保留未知前沿")
        if any(record.read_status != "read" or record.raw is None for record in inventory.records):
            _fail("incomplete_handoff", "完整 epoch 必须可回读每个原字节输入")
        if any(check.status != "stable" for check in (identity.start, identity.end)) or (
            identity.start.installation_sha256 != identity.end.installation_sha256
            or identity.start.file_set_sha256 != actual_digest
            or identity.end.file_set_sha256 != actual_digest
        ):
            _fail("input_drift", "epoch 开始/结束身份或完整分母漂移")
        roles = {node.role for node in closure.nodes}
        if not {"action", "reader", "native_source", "generated", "package"} <= roles:
            _fail("incomplete_closure", "完整消费闭包缺少必要生产路径节点")
        actions = {node.id for node in closure.nodes if node.role == "action"}
        packages = {node.id for node in closure.nodes if node.role == "package"}
        if (
            reachable_from(actions, outgoing) != nodes.keys()
            or reachable_from(packages, incoming) != nodes.keys()
        ):
            _fail("incomplete_closure", "每个闭包节点必须位于实际行动到生成与标准包的完整路径")
        dlcs = {dlc.id: dlc for dlc in identity.dlcs}
        for node in closure.nodes:
            if node.role != "reader":
                continue
            capability = next(
                item for item in capabilities if item.capability_id == node.capability_id
            )
            if not any(
                nodes[target].artifact == capability.key.source for target in outgoing[node.id]
            ):
                _fail(
                    "source_mismatch",
                    "完整 reader 的 reads 来源必须精确匹配能力键的命名空间/路径/摘要",
                )
            if any(
                getattr(capability.stages, stage) != "proven"
                for stage in ("legality", "implementation", "lowering", "production")
            ):
                _fail("incomplete_capability", "必要 reader 仍缺合法性/实现/降低/生产证明")
            if any(
                condition.required == "unknown"
                or getattr(dlcs[condition.id], condition.field) != condition.required
                for condition in capability.key.dlc_conditions
            ):
                _fail("unavailable_dlc", "DLC 条件未知或与当前可用性不符")
