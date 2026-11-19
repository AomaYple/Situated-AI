"""Build a local research catalog from one explicitly identified committed raw epoch."""

import hashlib
import json
import tempfile
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path

from . import information_catalog, version_contracts
from .committed_raw import open_committed_capture
from .research_output import open_local_evidence_output, validate_local_output


def _check_boundaries(output: Path, staging: Path, raw: Path, installation: Path) -> None:
    for source in (raw.resolve(strict=True), installation.resolve()):
        if (
            output.is_relative_to(source)
            or source.is_relative_to(output)
            or staging.is_relative_to(source)
        ):
            raise ValueError("研究输出须与 raw 和原安装目录分离")
    if output.exists() or output.is_symlink():
        raise ValueError("研究输出目录必须尚不存在")


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
            staging = Path(
                staging_scope.enter_context(
                    tempfile.TemporaryDirectory(prefix="sitai-research-", dir=staging_parent)
                )
            )
            validate_local_output(staging)
            index_path = staging / "occurrences.sqlite"
            catalog_path = staging / "information-catalog.json"
            catalog = information_catalog.build_from_raw(
                identity=identity, inventory=inventory, raw_root=raw_root, index_path=index_path
            )
            assert catalog.layered is not None
            index = replace(catalog.layered.index, path=destination.root / index_path.name)
            replace(catalog, layered=replace(catalog.layered, index=index)).write(catalog_path)
            with catalog_path.open("rb") as stream:
                catalog_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
            files = ((catalog_path, catalog_sha256), (index_path, index.sha256))
            marker = {
                "schema": 1,
                "epoch_id": identity.epoch_id,
                "file_set_sha256": identity.file_set_sha256,
                "files": {path.name: digest for path, digest in files},
            }
        encoded = (json.dumps(marker, indent=2, sort_keys=True) + "\n").encode("utf-8")
        return destination.publish(files, encoded, scratch=staging)
