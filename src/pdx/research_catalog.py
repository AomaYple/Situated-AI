"""Build a local research catalog from verified installation or committed raw sources."""

import hashlib
import json
import tempfile
from contextlib import ExitStack
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from . import information_catalog, version_contracts
from .committed_raw import identity_sources_digest, open_committed_capture
from .input_contracts import (
    ArtifactRef,
    CaptureCheck,
    InputIdentity,
    InputInventory,
    SnapshotProvenance,
)
from .input_inventory import (
    DEFAULT_STRATEGY_ANCHOR,
    _check_components,
    _root_path,
    inventory_installation,
    matches_default_strategy,
)
from .research_output import open_local_evidence_output, validate_local_output


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
    catalog_path = staging / "information-catalog.json"
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
                index_path=staging / "occurrences.sqlite",
            )
            files, encoded = _products(catalog, staging, destination.root)
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
            identity, inventory, staging / "occurrences.sqlite", raw_root=None
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
        catalog = replace(catalog, final_installation_check=final_check)
        files, encoded = _products(catalog, staging, destination.root)
        return destination.publish(files, encoded, scratch=staging)
