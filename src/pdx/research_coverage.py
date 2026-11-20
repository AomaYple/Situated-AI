"""按独立安装分母汇总研究证据与逐文件缺口。"""

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Literal

from .capability_catalog import LayerCoverage
from .input_contracts import file_set_digest

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .capability_catalog import FileDisposition
    from .input_contracts import (
        ArtifactRef,
        CapabilityRecord,
        Completeness,
        InputInventory,
        InventoryRecord,
        ParseStatus,
    )


@dataclass(frozen=True, slots=True)
class FormatStructureEvidence:
    """特定读取器能证明的结构范围及原始来源身份。"""

    source: ArtifactRef
    format: str
    structure_status: ParseStatus
    scope: Literal["file", "metadata"]


@dataclass(slots=True)
class _Counts:
    files: int = 0
    bytes: int = 0
    read_status: Counter[str] = field(default_factory=Counter)
    decode_status: Counter[str] = field(default_factory=Counter)
    parse_status: Counter[str] = field(default_factory=Counter)
    files_with_proven_semantics: int = 0
    proven_semantic_objects: int = 0
    anomalous_files: int = 0
    gap_counts: Counter[str] = field(default_factory=Counter)

    def to_dict(self, status: Completeness) -> dict[str, object]:
        def layer(name: str, counts: Counter[str], complete: str) -> dict[str, object]:
            known = counts[complete]
            not_applicable = counts["not_applicable"]
            item = LayerCoverage(
                name,
                "installation_files",
                self.files,
                known,
                self.files - known - not_applicable,
                not_applicable,
                status,
            )
            return {**asdict(item), "ratio": item.ratio}

        return {
            "denominator": self.files,
            "known_bytes": self.bytes,
            "read_status": dict(sorted(self.read_status.items())),
            "decode_status": dict(sorted(self.decode_status.items())),
            "parse_status": dict(sorted(self.parse_status.items())),
            "coverage": [
                layer("source_bytes", self.read_status, "read"),
                layer("decode", self.decode_status, "complete"),
                layer("structure", self.parse_status, "complete"),
            ],
            "semantic": {
                "files_with_proven_objects": self.files_with_proven_semantics,
                "files_without_proven_objects": self.files - self.files_with_proven_semantics,
                "proven_objects": self.proven_semantic_objects,
                "object_denominator_status": "unknown",
                "ratio": None,
            },
            "anomalous_files": self.anomalous_files,
            "gap_counts": dict(sorted(self.gap_counts.items())),
        }


@dataclass(frozen=True, slots=True)
class ResearchCoverage:
    epoch_id: str
    file_set_sha256: str
    denominator_status: Completeness
    totals: _Counts
    by_category: dict[str, _Counts]
    by_format: dict[tuple[str, str], _Counts]
    format_evidence: tuple[FormatStructureEvidence, ...]
    semantic_evidence: dict[str, tuple[str, ...]]
    gaps: dict[str, tuple[str, ...]]

    def to_dict(self) -> dict[str, object]:
        summaries: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
        for item in self.format_evidence:
            summaries[item.format, item.scope][item.structure_status] += 1
        return {
            "schema": 1,
            "epoch_id": self.epoch_id,
            "file_set_sha256": self.file_set_sha256,
            "denominator_status": self.denominator_status,
            "totals": self.totals.to_dict(self.denominator_status),
            "by_category": {
                category: row.to_dict(self.denominator_status)
                for category, row in sorted(self.by_category.items())
            },
            "by_format": [
                {"category": category, "suffix": suffix, **row.to_dict(self.denominator_status)}
                for (category, suffix), row in sorted(self.by_format.items())
            ],
            "format_structure_evidence": [
                {
                    "format": format_name,
                    "scope": scope,
                    "status_counts": dict(sorted(counts.items())),
                }
                for (format_name, scope), counts in sorted(summaries.items())
            ],
            "format_structure_sources": [asdict(item) for item in self.format_evidence],
            "semantic_sources": self.semantic_evidence,
            "gaps": self.gaps,
        }


def build_research_coverage(
    denominator: Iterable[InventoryRecord],
    observed: InputInventory,
    dispositions: Iterable[FileDisposition],
    *,
    denominator_status: Completeness,
    format_evidence: Iterable[FormatStructureEvidence] = (),
    capabilities: Iterable[CapabilityRecord] = (),
) -> ResearchCoverage:
    """按路径、大小和 SHA-256 核对既有读入。空检索和文件分类仅保留来源记录。"""
    denominator = tuple(denominator)
    expected_by_path = {row.path: row for row in denominator}
    if len({row.path.casefold() for row in denominator}) != len(denominator):
        raise ValueError("独立安装分母包含重复或大小写冲突路径")
    file_set_sha256 = file_set_digest(denominator)
    observed_by_path = {row.path: row for row in observed.records}
    disposition_rows = tuple(dispositions)
    dispositions_by_path = {row.path: row for row in disposition_rows}
    if len(observed_by_path) != len(observed.records) or len(dispositions_by_path) != len(
        disposition_rows
    ):
        raise ValueError("研究读入包含重复路径")

    gaps: dict[str, set[str]] = defaultdict(set)
    for path in (observed_by_path.keys() | dispositions_by_path.keys()) - expected_by_path.keys():
        gaps[path].add("outside_denominator")

    # 单独建立原字节核对集合，后续结构或对象证据必须引用该集合。
    read_sources: dict[str, str] = {}
    for path, expected in expected_by_path.items():
        actual = observed_by_path.get(path)
        if expected.category == "unknown":
            gaps[path].add("unknown_format")
        if actual is None:
            gaps[path].add("missing_observation")
        elif actual.read_status != "read":
            gaps[path].add(f"source_{actual.read_status}")
        elif expected.sha256 is None or expected.size is None:
            gaps[path].add("denominator_identity_unavailable")
        elif (actual.size, actual.sha256) != (expected.size, expected.sha256):
            gaps[path].add("source_identity_mismatch")
        else:
            read_sources[path] = expected.sha256

    def matches_source(reference: ArtifactRef) -> bool:
        return (
            reference.namespace == "installation"
            and read_sources.get(reference.path) == reference.sha256
        )

    verified_formats: dict[tuple[str, str, str], FormatStructureEvidence] = {}
    for item in format_evidence:
        path = item.source.path
        if not matches_source(item.source):
            gaps[path].add("format_evidence_source_mismatch")
            continue
        key = (path, item.format, item.scope)
        previous = verified_formats.get(key)
        if previous is not None and previous != item:
            raise ValueError(f"同一来源的格式结构证据互相冲突：{path}")
        verified_formats[key] = item
        if item.structure_status in {"partial", "failed", "not_attempted"}:
            gaps[path].add(f"format_structure_{item.structure_status}")

    semantic_sources: dict[str, set[str]] = defaultdict(set)
    for capability in capabilities:
        path = capability.key.source.path
        if capability.semantic_status != "recognized" or capability.evidence_kind == "inference":
            continue
        if capability.epoch_id != observed.epoch_id or not matches_source(capability.key.source):
            gaps[path].add("semantic_evidence_source_mismatch")
            continue
        if not capability.evidence or any(
            not matches_source(ref)
            for ref in capability.evidence
            if ref.namespace == "installation"
        ):
            gaps[path].add("semantic_evidence_missing_or_mismatched")
            continue
        disposition = dispositions_by_path.get(path)
        if (
            capability.parse_status != "complete"
            or disposition is None
            or disposition.parse_status != "complete"
        ):
            gaps[path].add("semantic_evidence_structure_unverified")
            continue
        semantic_sources[path].add(capability.capability_id)

    totals = _Counts()
    by_category: dict[str, _Counts] = defaultdict(_Counts)
    by_format: dict[tuple[str, str], _Counts] = defaultdict(_Counts)
    for path, expected in expected_by_path.items():
        actual = observed_by_path.get(path)
        disposition = dispositions_by_path.get(path)
        read_status = "unverified"
        decode_status = parse_status = "unobserved"
        if path in read_sources:
            read_status = "read"
            if disposition is None:
                gaps[path].add("missing_disposition")
            else:
                decode_status = disposition.decode_status
                parse_status = disposition.parse_status
                if disposition.diagnostics:
                    gaps[path].add("analysis_diagnostics")
        elif actual is not None and actual.read_status != "read":
            read_status = actual.read_status

        if decode_status == "failed":
            gaps[path].add("decode_failed")
        if parse_status in {"failed", "partial", "not_attempted"}:
            gaps[path].add(f"structure_{parse_status}")

        reasons = gaps.get(path, ())
        anomalous = any(
            reason not in {"structure_not_attempted", "format_structure_not_attempted"}
            for reason in reasons
        )
        proven_objects = len(semantic_sources.get(path, ()))
        suffix = PurePosixPath(path).suffix.casefold()
        for counts in (
            totals,
            by_category[expected.category],
            by_format[expected.category, suffix],
        ):
            counts.files += 1
            counts.bytes += expected.size or 0
            counts.read_status[read_status] += 1
            counts.decode_status[decode_status] += 1
            counts.parse_status[parse_status] += 1
            counts.files_with_proven_semantics += bool(proven_objects)
            counts.proven_semantic_objects += proven_objects
            counts.anomalous_files += anomalous
            counts.gap_counts.update(reasons)

    return ResearchCoverage(
        observed.epoch_id,
        file_set_sha256,
        denominator_status,
        totals,
        dict(by_category),
        dict(by_format),
        tuple(item for _, item in sorted(verified_formats.items())),
        {path: tuple(sorted(ids)) for path, ids in sorted(semantic_sources.items())},
        {path: tuple(sorted(codes)) for path, codes in sorted(gaps.items())},
    )
