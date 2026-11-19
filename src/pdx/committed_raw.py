"""Read the schema-3 contents of an explicitly selected committed local raw epoch."""

import hashlib
import json
import re
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from .input_contracts import (
    ArtifactRef,
    ConsumerClosure,
    InputContractError,
    InputIdentity,
    InputInventory,
    dumps_contract,
    is_contract_path,
    loads_contract,
    validate_handoff,
)
from .input_inventory import open_inventory_source

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import BinaryIO

    from .input_contracts import InventoryRecord

_SCHEMA = 3
_DIGEST = re.compile(r"[0-9a-f]{64}")
_CHUNK = 1024 * 1024


class RawEvidenceError(ValueError):
    """稳定 code 区分容量阻塞、输入漂移、目标安全和证据损坏。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class RawIdentitySource:
    """安装分母外的身份原件；reference.path 相对于显式命名空间 root。

    只授权读取/本机保全一个原件，不授权扫描 root 或公开分发。
    真实来源位置与原字节身份在 capture context 中一起冻结。
    """

    reference: ArtifactRef
    root: Path
    authorization: str
    size: int

    def __post_init__(self) -> None:
        if (
            self.reference.namespace not in {"evidence", "repository"}
            or not isinstance(self.root, Path)
            or type(self.authorization) is not str
            or not self.authorization.strip()
            or type(self.size) is not int
            or self.size < 0
        ):
            raise RawEvidenceError(
                "invalid_identity_source", "身份原件须有来源根、授权和原字节大小"
            )
        _relative(self.reference.path)
        _hex(self.reference.sha256)
        if not self.root.is_absolute() or ".." in self.root.parts:
            raise RawEvidenceError("invalid_target", "外部身份来源须为安全绝对路径")


def _json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _metadata(content: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise RawEvidenceError("duplicate_json_key", key)
            result[key] = value
        return result

    try:
        value = json.loads(content, object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RawEvidenceError("invalid_metadata", "证据元数据不是有效 JSON") from error
    if not isinstance(value, dict):
        raise RawEvidenceError("invalid_metadata", "证据元数据必须是对象")
    return value


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hex(value: str) -> str:
    if _DIGEST.fullmatch(value) is None:
        raise RawEvidenceError("invalid_digest", "必须是小写 SHA-256")
    return value


def identity_sources_digest(references: tuple[ArtifactRef, ...]) -> str:
    """身份来源的独立命名空间分母；同路径不能跨 namespace 相互覆盖。"""
    keys = [(ref.namespace, ref.path.casefold()) for ref in references]
    if not references or len(keys) != len(set(keys)):
        raise RawEvidenceError("invalid_identity_source", "身份来源缺失、重复或大小写歧义")
    for ref in references:
        if ref.namespace not in {"installation", "repository", "evidence"}:
            raise RawEvidenceError("invalid_identity_source", "身份来源必须是可回读的原件")
        _relative(ref.path)
        _hex(ref.sha256)
    return _digest(_json(sorted((ref.namespace, ref.path, ref.sha256) for ref in references)))


def _relative(value: str) -> tuple[str, ...]:
    parts = value.split("/")
    if not is_contract_path(value):
        raise RawEvidenceError("invalid_path", f"无效相对路径：{value!r}")
    return tuple(parts)


def validate_inputs(identity: InputIdentity, inventory: InputInventory) -> None:
    # 复用四合同唯一校验，空闭包只用于规范身份/分母验证，不宣称消费完整。
    validate_handoff(
        identity,
        inventory,
        (),
        ConsumerClosure(identity.epoch_id, "information_catalog", (), (), (), "unknown"),
    )


def _marker(identity: InputIdentity, inventory: InputInventory, context: bytes) -> bytes:
    return _json(
        {
            "schema": _SCHEMA,
            "identity_sha256": _digest(dumps_contract(identity).encode("utf-8")),
            "inventory_sha256": _digest(dumps_contract(inventory).encode("utf-8")),
            "context_sha256": _digest(context),
        }
    )


def _context_metadata(context: bytes) -> dict[str, Any]:
    metadata = _metadata(context)
    if type(metadata.get("schema")) is int and metadata["schema"] != _SCHEMA:
        raise RawEvidenceError(
            "unsupported_schema", "旧或未知 raw 辅助 schema 不能迁移、恢复或证明零引用"
        )
    expected_fields = {
        "schema",
        "source_layer",
        "source_root",
        "source_authorization",
        "is_installation",
        "directories",
        "write_target",
        "allowed_root",
        "target_volume",
        "copy_authorized",
        "access_boundary",
        "policy",
        "identity_sources",
    }
    text_fields = (
        "source_layer",
        "source_root",
        "source_authorization",
        "write_target",
        "allowed_root",
        "access_boundary",
    )
    if (
        set(metadata) != expected_fields
        or type(metadata["schema"]) is not int
        or metadata["schema"] != _SCHEMA
        or any(
            type(metadata[name]) is not str or not metadata[name].strip() for name in text_fields
        )
        or metadata["source_layer"] != "installation"
        or metadata["is_installation"] is not True
        or metadata["copy_authorized"] is not True
        or type(metadata["policy"]) is not dict
        or set(metadata["policy"]) != {"max_store_bytes", "reserve_bytes", "chunk_size"}
        or any(type(value) is not int or value <= 0 for value in metadata["policy"].values())
        or type(metadata["target_volume"]) is not dict
        or set(metadata["target_volume"]) != {"anchor", "device"}
        or type(metadata["target_volume"]["anchor"]) is not str
        or not metadata["target_volume"]["anchor"]
        or type(metadata["target_volume"]["device"]) is not int
        or metadata["target_volume"]["device"] < 0
    ):
        raise RawEvidenceError("invalid_manifest", "未知、损坏或未授权的 capture context")
    directories = metadata.get("directories")
    if (
        type(directories) is not list
        or any(type(value) is not str for value in directories)
        or len(directories) != len(set(directories))
        or "." not in directories
    ):
        raise RawEvidenceError("invalid_manifest", "缺少已绑定的完整目录分母")
    result = set(directories)
    for value in result - {"."}:
        _relative(value)
    if any(
        parent.as_posix() not in result for path in result for parent in PurePosixPath(path).parents
    ):
        raise RawEvidenceError("invalid_manifest", "目录分母没有包含全部父目录")
    _metadata_sources(metadata)
    return metadata


def _metadata_sources(metadata: dict[str, Any]) -> tuple[RawIdentitySource, ...]:
    rows = metadata.get("identity_sources")
    if type(rows) is not list:
        raise RawEvidenceError("invalid_manifest", "外部身份原件分母缺失")
    sources = []
    roots: dict[str, Path] = {}
    for row in rows:
        if (
            type(row) is not dict
            or set(row) != {"reference", "root", "authorization", "size", "raw"}
            or type(row["reference"]) is not dict
            or set(row["reference"]) != {"namespace", "path", "sha256"}
            or any(type(value) is not str for value in row["reference"].values())
            or type(row["root"]) is not str
            or not Path(row["root"]).is_absolute()
            or type(row["raw"]) is not dict
        ):
            raise RawEvidenceError("invalid_manifest", "外部身份来源字段无效或未知")
        reference = ArtifactRef(**row["reference"])
        source = RawIdentitySource(reference, Path(row["root"]), row["authorization"], row["size"])
        if row["raw"] != asdict(
            ArtifactRef("evidence", f"objects/{reference.sha256}", reference.sha256)
        ):
            raise RawEvidenceError("invalid_manifest", "外部原件必须映射到对应内容寻址对象")
        if reference.namespace in roots and roots[reference.namespace] != source.root:
            raise RawEvidenceError("invalid_manifest", "同一 namespace 不能使用不同来源根")
        roots[reference.namespace] = source.root
        sources.append(source)
    if sources:
        identity_sources_digest(tuple(source.reference for source in sources))
    return tuple(sources)


def _bound_sources(
    identity: InputIdentity, metadata: dict[str, Any]
) -> tuple[RawIdentitySource, ...]:
    sources = _metadata_sources(metadata)
    actual = {source.reference for source in sources}
    expected = {ref for ref in identity.identity_sources if ref.namespace != "installation"}
    identity_sources_digest(identity.identity_sources)
    if actual != expected:
        raise RawEvidenceError("identity_mismatch", "外部来源原件绑定与唯一身份分母不一致")
    return sources


def _source_directories(context: bytes, inventory: InputInventory) -> set[str]:
    result = set(_context_metadata(context)["directories"])
    paths = (record.path for record in inventory.records)
    if any(
        parent.as_posix() not in result for path in paths for parent in PurePosixPath(path).parents
    ):
        raise RawEvidenceError("invalid_manifest", "目录分母没有包含全部父目录")
    return result


@contextmanager
def open_committed_capture(
    raw_root: Path, epoch: str
) -> Iterator[tuple[InputIdentity, InputInventory]]:
    """Read only canonical capture metadata, never traverse/hash all raw objects.

    The existing raw helpers own the auxiliary metadata contract.
    """
    if re.fullmatch(r"[0-9a-f]{64}", epoch) is None:
        raise ValueError("capture epoch 不是内容身份")
    captured: dict[str, bytes] = {}

    def read(relative: str) -> bytes:
        try:
            with open_inventory_source(raw_root, relative) as stream:
                data = stream.read()
        except OSError as error:
            raise ValueError(f"capture metadata/对象缺失或不可安全读取：{relative}") from error
        captured[relative] = data
        return data

    prefix = f"epochs/{epoch}"
    identity_bytes = read(f"{prefix}/identity.json")
    inventory_bytes = read(f"{prefix}/inventory.json")
    identity = loads_contract(identity_bytes.decode("utf-8"))
    inventory = loads_contract(inventory_bytes.decode("utf-8"))
    if not isinstance(identity, InputIdentity) or not isinstance(inventory, InputInventory):
        raise ValueError("capture 的 canonical identity/inventory 类型不符")
    if (
        dumps_contract(identity).encode("utf-8") != identity_bytes
        or dumps_contract(inventory).encode("utf-8") != inventory_bytes
        or hashlib.sha256(identity_bytes).hexdigest() != epoch
        or identity.epoch_id != epoch
        or identity.completeness != "complete"
        or inventory.completeness != "complete"
    ):
        raise ValueError("capture 不是已提交的完整 canonical 身份/分母")
    validate_inputs(identity, inventory)
    context = read(f"{prefix}/context.json")
    metadata = _context_metadata(context)
    context_sha = hashlib.sha256(context).hexdigest()
    context_ref = ArtifactRef("evidence", f"raw/context/{context_sha}.json", context_sha)
    if context_ref not in identity.contracts or read(context_ref.path) != context:
        raise ValueError("capture context 未绑定 canonical 身份")
    marker = read(f"{prefix}/COMMITTED.json")
    _metadata(marker)  # reject duplicate keys before the exact canonical marker check
    if marker != _marker(identity, inventory, context):
        raise ValueError("capture COMMITTED 与 canonical 身份/分母/context 不符")
    if (
        Path(metadata["write_target"]).resolve() != raw_root.resolve()
        or Path(metadata["source_root"]).resolve() != Path(identity.installation_root).resolve()
    ):
        raise ValueError("capture 的实际 raw root/原安装根与授权 context 不符")
    _source_directories(context, inventory)
    for source in _bound_sources(identity, metadata):
        raw = read(f"objects/{source.reference.sha256}")
        if (len(raw), hashlib.sha256(raw).hexdigest()) != (source.size, source.reference.sha256):
            raise ValueError("capture 外部身份对象不符")
    if any(
        check.status != "stable"
        or check.file_set_sha256 != identity.file_set_sha256
        or check.installation_sha256 != identity_sources_digest(identity.identity_sources)
        for check in (identity.start, identity.end)
    ):
        raise ValueError("capture 开始/结束身份没有绑定完整分母")
    if any(
        row.read_status != "read"
        or row.raw != ArtifactRef("evidence", f"objects/{row.sha256}", row.sha256 or "")
        for row in inventory.records
    ):
        raise ValueError("capture 分母存在未保全的原件处置")
    try:
        yield identity, inventory
    finally:
        # Stream the manifest again instead of retaining another 28MB copy.
        for relative, data in captured.items():
            try:
                with open_inventory_source(raw_root, relative) as stream:
                    hasher = hashlib.sha256()
                    for chunk in iter(lambda: stream.read(_CHUNK), b""):
                        hasher.update(chunk)
                    digest = hasher.hexdigest()
            except OSError as error:
                raise ValueError("capture metadata/提交标记在当前审计期间消失") from error
            if digest != hashlib.sha256(data).hexdigest():
                raise ValueError("capture metadata/提交标记在当前审计期间漂移")


@contextmanager
def verified_catalog_inputs(
    identity: InputIdentity, inventory: InputInventory, *, raw_root: Path
) -> Iterator[None]:
    """Verify that the entire derived denominator is the exact committed capture."""
    with open_committed_capture(raw_root, identity.epoch_id) as (parent, records):
        if (identity, inventory) != (parent, records):
            raise ValueError("研究目录分母与已提交的原件不一致")
        yield


def _object_path(record: InventoryRecord) -> str:
    if record.raw is None or record.raw.namespace != "evidence":
        raise InputContractError("missing_raw", f"缺少可回读 raw 来源：{record.path}")
    return record.raw.path


def read_source(
    record: InventoryRecord,
    *,
    raw_root: Path,
    retain: bool,
    prefix_size: int | None = None,
) -> bytes | None:
    """安全流式核对同一份源字节；仅格式 reader 需要时常驻单文件。"""
    if record.read_status != "read":
        return None
    return read_record(
        record, root=raw_root, relative=_object_path(record), retain=retain, prefix_size=prefix_size
    )


def read_record(
    record: InventoryRecord,
    *,
    root: Path,
    relative: str,
    retain: bool,
    prefix_size: int | None = None,
) -> bytes | None:
    hasher, size, chunks = hashlib.sha256(), 0, []
    with open_inventory_source(root, relative) as stream:
        for chunk in iter(lambda: stream.read(_CHUNK), b""):
            hasher.update(chunk)
            if retain:
                if prefix_size is None:
                    chunks.append(chunk)
                elif size < prefix_size:
                    chunks.append(chunk[: prefix_size - size])
            size += len(chunk)
    if (size, hasher.hexdigest()) != (record.size, record.sha256):
        raise InputContractError("source_mismatch", f"原字节大小/摘要不符：{record.path}")
    return b"".join(chunks) if retain else None


@contextmanager
def verified_source(record: InventoryRecord, *, raw_root: Path) -> Iterator[BinaryIO]:
    """给需要 seek 的成熟格式 reader 同一安全句柄，前后核对原字节摘要。"""
    with verified_record(record, root=raw_root, relative=_object_path(record)) as stream:
        yield stream


@contextmanager
def verified_record(record: InventoryRecord, *, root: Path, relative: str) -> Iterator[BinaryIO]:
    with open_inventory_source(root, relative) as stream:

        def verify() -> None:
            stream.seek(0)
            hasher = hashlib.sha256()
            for chunk in iter(lambda: stream.read(_CHUNK), b""):
                hasher.update(chunk)
            digest = hasher.hexdigest()
            if (stream.tell(), digest) != (record.size, record.sha256):
                raise InputContractError("source_mismatch", f"容器原字节摘要漂移：{record.path}")
            stream.seek(0)

        verify()
        try:
            yield stream
        finally:
            verify()
