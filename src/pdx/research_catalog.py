"""Build a local research catalog from verified installation or committed raw sources."""

import hashlib
import json
import re
import tempfile
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import information_catalog, version_contracts
from .capability_catalog import INDEX_SCHEMA, OccurrenceIndex
from .committed_raw import identity_sources_digest, open_committed_capture, validate_inputs
from .input_contracts import (
    ArtifactRef,
    CaptureCheck,
    InputIdentity,
    InputInventory,
    SnapshotProvenance,
    loads_contract,
)
from .input_inventory import (
    DEFAULT_STRATEGY_ANCHOR,
    _check_components,
    _root_path,
    inventory_installation,
    matches_default_strategy,
    open_inventory_source,
)
from .research_coverage import build_research_coverage
from .research_output import open_local_evidence_output, validate_local_output

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator


_CATALOG_NAME = "information-catalog.json"
_INDEX_NAME = "occurrences.sqlite"
_COMPLETE_NAME = "COMPLETE.json"


@dataclass(frozen=True, slots=True)
class PublishedResearch:
    index: OccurrenceIndex
    projection: str
    implementation_status: str
    coverage: list[dict[str, Any]]
    research_coverage: dict[str, Any] | None


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("研究目录记录不是 JSON 对象")
    return value


def _sha256(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("研究目录包含无效的 SHA-256")
    return value


def _count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("研究目录包含无效的计数")
    return value


@contextmanager
def open_published(
    directory: Path, *, historical_locators: bool = False
) -> Iterator[tuple[PublishedResearch, sqlite3.Connection]]:
    """Read one completed publication using one verified index connection."""
    root = directory.absolute()
    with (
        open_inventory_source(root, _COMPLETE_NAME) as marker_stream,
        open_inventory_source(root, _CATALOG_NAME) as catalog_stream,
    ):
        marker = _object(json.load(marker_stream))
        files = _object(marker.get("files"))
        if (
            type(marker.get("schema")) is not int
            or marker["schema"] != 1
            or set(marker) != {"schema", "epoch_id", "file_set_sha256", "files"}
            or set(files) != {_CATALOG_NAME, _INDEX_NAME}
        ):
            raise ValueError("完整研究标记不符合发布合同")
        raw = catalog_stream.read()
        if hashlib.sha256(raw).hexdigest() != _sha256(files[_CATALOG_NAME]):
            raise ValueError("研究目录 JSON 摘要漂移")
        layered = _object(_object(json.loads(raw)).get("分层目录"))
        del raw
        identity = loads_contract(json.dumps(layered.get("input_identity")))
        inventory = loads_contract(json.dumps(layered.get("input_inventory")))
        if not isinstance(identity, InputIdentity) or not isinstance(inventory, InputInventory):
            raise ValueError("研究目录缺少完整输入身份或盘点")
        version_contracts.require_current(identity.version)
        validate_inputs(identity, inventory)
        indexed = _object(layered.get("index"))
        index = OccurrenceIndex(
            root / _INDEX_NAME,
            _sha256(indexed.get("epoch_id")),
            _sha256(indexed.get("file_set_sha256")),
            _sha256(indexed.get("implementation_sha256")),
            _sha256(indexed.get("sha256")),
            _count(indexed.get("occurrence_count")),
            _count(indexed.get("file_count")),
        )
        if (
            indexed.get("schema") != INDEX_SCHEMA
            or index.epoch_id != layered.get("epoch_id")
            or index.epoch_id != marker.get("epoch_id")
            or index.epoch_id != identity.epoch_id
            or index.file_set_sha256 != marker.get("file_set_sha256")
            or index.file_set_sha256 != identity.file_set_sha256
            or index.sha256 != _sha256(files[_INDEX_NAME])
            or index.file_count != identity.file_count
        ):
            raise ValueError("研究目录与索引 epoch/分母/摘要不相同")
        projection = layered.get("index_projection")
        if projection not in ("source_locators", "full_private_index"):
            raise ValueError("研究目录包含未知的索引投影")
        status = index.implementation_status(historical_locators=historical_locators)
        if status == "historical_locators" and projection != "source_locators":
            raise ValueError("历史读取仅支持已登记的现场定位索引")
        coverage = layered.get("coverage")
        if not isinstance(coverage, list):
            raise ValueError("研究目录缺少覆盖统计")
        report_payload = layered.get("research_coverage")
        report = None if report_payload is None else _object(report_payload)
        if report is not None and (
            report.get("epoch_id") != index.epoch_id
            or report.get("file_set_sha256") != index.file_set_sha256
        ):
            raise ValueError("研究覆盖分母与索引身份不相同")
        published = PublishedResearch(
            index, projection, status, [_object(row) for row in coverage], report
        )
        del layered, inventory
        with index.connect(historical_locators=historical_locators) as connection:
            yield published, connection


def _check_boundaries(output: Path, staging: Path, *sources: Path) -> None:
    for path in sources:
        source = path.resolve()
        if (
            output.is_relative_to(source)
            or source.is_relative_to(output)
            or staging.is_relative_to(source)
        ):
            raise ValueError("研究输出须与 raw 和原安装目录分离")
    if output.exists() or output.is_symlink():
        raise ValueError("研究输出目录必须尚不存在")


def _stage(parent: Path, scope: ExitStack) -> Path:
    staging = Path(
        scope.enter_context(tempfile.TemporaryDirectory(prefix="sitai-research-", dir=parent))
    )
    validate_local_output(staging)
    return staging


def _products(
    catalog: information_catalog.ResearchInformationCatalog, staging: Path, destination: Path
) -> tuple[tuple[tuple[Path, str], ...], bytes]:
    catalog_path = staging / _CATALOG_NAME
    layer = catalog.layered
    index = replace(layer.index, path=destination / layer.index.path.name)
    replace(catalog, layered=replace(layer, index=index)).write(catalog_path)
    with catalog_path.open("rb") as stream:
        catalog_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    files = ((catalog_path, catalog_sha256), (layer.index.path, index.sha256))
    marker = {
        "schema": 1,
        "epoch_id": index.epoch_id,
        "file_set_sha256": index.file_set_sha256,
        "files": {path.name: digest for path, digest in files},
    }
    return files, (json.dumps(marker, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write(raw_root: Path, epoch: str, output_dir: Path) -> Path:
    """Publish JSON and SQLite only after raw verification finishes."""
    staging_parent = Path(tempfile.gettempdir()).resolve(strict=True)
    with open_local_evidence_output(output_dir) as destination, ExitStack() as staging_scope:
        with open_committed_capture(raw_root, epoch) as (identity, inventory):
            version_contracts.require_current(identity.version)
            installed = {row.path: row.sha256 for row in inventory.records}
            for path, expected in version_contracts.INSTALLATION_IDENTITY_SHA256.items():
                if installed.get(path) != expected:
                    raise ValueError(f"raw epoch 与冻结安装身份不符：{path}")
            _check_boundaries(
                destination.root, staging_parent, raw_root, Path(identity.installation_root)
            )
            staging = _stage(staging_parent, staging_scope)
            catalog = information_catalog._build_from_raw(
                identity=identity,
                inventory=inventory,
                raw_root=raw_root,
                index_path=staging / _INDEX_NAME,
            )
            report = build_research_coverage(
                inventory.records,
                inventory,
                catalog.layered.dispositions,
                denominator_status=inventory.completeness,
                format_evidence=catalog.format_evidence,
            )
            files, encoded = _products(
                replace(catalog, research_coverage=report), staging, destination.root
            )
        return destination.publish(files, encoded, scratch=staging)


def write_installation(installation: Path, output_dir: Path) -> Path:
    """Project only source locators from a closed read-only installation observation."""
    root = _root_path(installation)
    _check_components(root)
    version = version_contracts.require_current()
    expected_strategy = version_contracts.contract(version).default_strategy_sha256
    start_at = datetime.now(UTC).isoformat()
    verified = version_contracts.verify_installation_identity(root)
    staging_parent = Path(tempfile.gettempdir()).resolve(strict=True)
    with open_local_evidence_output(output_dir) as destination, ExitStack() as staging_scope:
        _check_boundaries(destination.root, staging_parent, root)
        scan = inventory_installation(root, verified=verified)
        if scan.scan_status != "complete" or scan.file_set_sha256 is None:
            raise ValueError(f"安装盘点不完整：{len(scan.diagnostics)} 项诊断")
        if not matches_default_strategy(scan, expected_strategy):
            raise ValueError(f"安装缺少当前锁定策略或其摘要漂移：{DEFAULT_STRATEGY_ANCHOR}")
        end_at = datetime.now(UTC).isoformat()
        references = tuple(
            ArtifactRef("installation", row.path, row.sha256) for row in verified.sources
        )
        identity_digest = identity_sources_digest(references)
        identity = InputIdentity(
            scan.root,
            version,
            "unknown",
            f"release/{version}",
            (),
            references,
            len(scan.records),
            scan.file_set_sha256,
            (),
            (),
            CaptureCheck(start_at, identity_digest, scan.file_set_sha256, "stable"),
            CaptureCheck(end_at, identity_digest, scan.file_set_sha256, "stable"),
            SnapshotProvenance("installation", "read_only_installation_locators", None, None),
            "complete",
        )
        inventory = InputInventory(identity.epoch_id, scan.records, "complete", ())
        staging = _stage(staging_parent, staging_scope)
        catalog = information_catalog._build_research_index(
            identity, inventory, staging / _INDEX_NAME, raw_root=None
        )
        checked = inventory_installation(root, verified=verified)
        if checked.scan_status != "complete" or (
            checked.file_set_sha256,
            checked.directories,
            checked.observed_paths,
        ) != (scan.file_set_sha256, scan.directories, scan.observed_paths):
            raise ValueError("分析期间安装字节、文件或目录分母变化")
        final_check = CaptureCheck(
            datetime.now(UTC).isoformat(), identity_digest, scan.file_set_sha256, "stable"
        )
        report = build_research_coverage(
            checked.records,
            inventory,
            catalog.layered.dispositions,
            denominator_status=inventory.completeness,
            format_evidence=catalog.format_evidence,
        )
        catalog = replace(catalog, final_installation_check=final_check, research_coverage=report)
        files, encoded = _products(catalog, staging, destination.root)
        return destination.publish(files, encoded, scratch=staging)
