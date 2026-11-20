from dataclasses import replace

import pytest

from pdx.capability_catalog import FileDisposition
from pdx.input_contracts import (
    ArtifactRef,
    CapabilityKey,
    CapabilityRecord,
    CapabilityStages,
    CostRecord,
    Diagnostic,
    InputInventory,
    InventoryRecord,
    ParseStatus,
    RoleBinding,
    file_set_digest,
)
from pdx.research_coverage import FormatStructureEvidence, build_research_coverage

_EPOCH = "a" * 64
_DIGEST = "b" * 64
_OTHER_DIGEST = "c" * 64


def _source(path: str, category: str = "script_candidate") -> InventoryRecord:
    return InventoryRecord(
        path,
        10,
        _DIGEST,
        category,
        "base",
        "read",
        "not_attempted",
        None,
        (),
        (),
        (),
        (),
        "complete",
    )


def _disposition(
    row: InventoryRecord,
    parse_status: ParseStatus = "complete",
    decode_status: str = "complete",
) -> FileDisposition:
    return FileDisposition(
        row.path,
        row.category,
        "observed",
        decode_status,
        parse_status,
        "recognized",
        "research_only",
        "synthetic",
    )


def _capability(source: ArtifactRef) -> CapabilityRecord:
    return CapabilityRecord(
        _EPOCH,
        CapabilityKey(
            "1.15.2",
            "unknown",
            source,
            "synthetic_operation",
            "synthetic_reader",
            "synthetic_consumer",
            RoleBinding("actor", "country"),
            (),
            (),
            (),
            "synthetic_timing",
            (),
        ),
        "complete",
        "recognized",
        CapabilityStages(True, "unknown", "unknown", "unknown", "unknown", "unknown"),
        "synthetic_unit",
        "unknown",
        "unknown",
        "unknown",
        CostRecord("unknown", "unknown", None, None, ""),
        ("research_only",),
        "static_check",
        (source,),
        (),
    )


def _report_object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def _coverage_rows(totals: dict[str, object]) -> list[dict[str, object]]:
    rows = totals["coverage"]
    assert isinstance(rows, list)
    return [_report_object(row) for row in rows]


@pytest.mark.unit
def test_independent_denominator_retains_missing_and_mismatched_files():
    good = _source("base/good.txt")
    stale = _source("base/stale.txt")
    missing = _source("base/missing.txt", "unknown")
    blocked = _source("base/blocked.txt")
    strayed = _source("other/extra.txt")
    no_disposition = _source("base/no-disposition.txt")
    denominator = (missing, blocked, stale, good, no_disposition)
    observed = InputInventory(
        _EPOCH,
        (
            replace(stale, sha256=_OTHER_DIGEST),
            strayed,
            good,
            no_disposition,
            replace(
                blocked,
                sha256=None,
                read_status="failed",
                diagnostics=(Diagnostic("failure", "synthetic", None),),
            ),
        ),
        "partial",
        (),
    )
    report = build_research_coverage(
        denominator,
        observed,
        [_disposition(good), _disposition(stale), _disposition(strayed)],
        denominator_status="complete",
    )
    payload = report.to_dict()
    assert report.file_set_sha256 == file_set_digest(denominator)
    totals = _report_object(payload["totals"])
    assert totals["denominator"] == 5
    coverage = _coverage_rows(totals)
    assert coverage[0]["ratio"] == 2 / 5
    assert coverage[2]["ratio"] == 1 / 5
    assert totals["read_status"] == {"failed": 1, "read": 2, "unverified": 2}
    assert totals["parse_status"] == {"complete": 1, "unobserved": 4}
    categories = _report_object(payload["by_category"])
    assert _report_object(categories["unknown"])["denominator"] == 1
    assert payload["gaps"] == {
        blocked.path: ("source_failed",),
        missing.path: ("missing_observation", "unknown_format"),
        no_disposition.path: ("missing_disposition",),
        stale.path: ("source_identity_mismatch",),
        strayed.path: ("outside_denominator",),
    }


@pytest.mark.unit
def test_counts_distinguish_partial_failed_unattempted_and_not_applicable():
    statuses: list[tuple[str, ParseStatus]] = [
        ("complete", "complete"),
        ("complete", "partial"),
        ("failed", "failed"),
        ("not_attempted", "not_attempted"),
        ("not_attempted", "not_applicable"),
    ]
    rows = tuple(_source(f"base/{index}.txt") for index in range(len(statuses)))
    observed = InputInventory(_EPOCH, rows, "complete", ())
    report = build_research_coverage(
        reversed(rows),
        observed,
        [
            _disposition(row, parsed, decoded)
            for row, (decoded, parsed) in zip(rows, statuses, strict=True)
        ],
        denominator_status="partial",
    ).to_dict()
    totals = _report_object(report["totals"])
    assert totals["decode_status"] == {"complete": 2, "failed": 1, "not_attempted": 2}
    assert totals["parse_status"] == dict.fromkeys(
        ("complete", "failed", "partial", "not_attempted", "not_applicable"), 1
    )
    coverage = _coverage_rows(totals)
    assert all(layer["ratio"] is None for layer in coverage)
    assert coverage[2]["not_applicable"] == 1
    assert coverage[2]["unknown"] == 3


@pytest.mark.unit
def test_format_headers_and_classification_do_not_establish_full_structure_or_semantics():
    image = _source("base/image.dds", "image_map")
    script = _source("base/script.txt")
    rows = (image, script)
    observed = InputInventory(_EPOCH, rows, "complete", ())
    image_ref = ArtifactRef("installation", image.path, _DIGEST)
    script_ref = ArtifactRef("installation", script.path, _DIGEST)
    valid = _capability(script_ref)
    header = FormatStructureEvidence(image_ref, "dds", "complete", "metadata")
    wrong_hash = replace(header, source=replace(image_ref, sha256=_OTHER_DIGEST))
    no_proof = build_research_coverage(
        rows,
        observed,
        [_disposition(image, "not_attempted", "not_attempted"), _disposition(script)],
        denominator_status="complete",
        format_evidence=(header, header, wrong_hash),
        capabilities=(
            replace(valid, evidence=()),
            replace(valid, epoch_id=_OTHER_DIGEST),
            replace(valid, evidence_kind="inference"),
            _capability(image_ref),
        ),
    ).to_dict()
    assert no_proof["format_structure_evidence"] == [
        {"format": "dds", "scope": "metadata", "status_counts": {"complete": 1}}
    ]
    categories = _report_object(no_proof["by_category"])
    assert _report_object(categories["image_map"])["parse_status"] == {"not_attempted": 1}
    semantic = _report_object(_report_object(no_proof["totals"])["semantic"])
    assert semantic["proven_objects"] == 0
    assert semantic["ratio"] is None
    assert no_proof["gaps"] == {
        image.path: (
            "format_evidence_source_mismatch",
            "semantic_evidence_structure_unverified",
            "structure_not_attempted",
        ),
        script.path: (
            "semantic_evidence_missing_or_mismatched",
            "semantic_evidence_source_mismatch",
        ),
    }

    with_proof = build_research_coverage(
        rows,
        observed,
        [_disposition(script), _disposition(image, "not_attempted", "not_attempted")],
        denominator_status="complete",
        capabilities=(valid, valid),
    ).to_dict()
    semantic = _report_object(_report_object(with_proof["totals"])["semantic"])
    assert semantic["proven_objects"] == 1
    assert with_proof["semantic_sources"] == {script.path: (valid.capability_id,)}
    assert semantic["ratio"] is None


@pytest.mark.unit
def test_empty_scope_cannot_report_complete_coverage():
    result = build_research_coverage(
        (), InputInventory(_EPOCH, (), "complete", ()), (), denominator_status="complete"
    ).to_dict()
    totals = _report_object(result["totals"])
    assert totals["denominator"] == 0
    assert all(layer["ratio"] is None for layer in _coverage_rows(totals))
    assert _report_object(totals["semantic"])["ratio"] is None


@pytest.mark.unit
def test_duplicate_dispositions_are_rejected():
    row = _source("base/script.txt")
    inventory = InputInventory(_EPOCH, (row,), "complete", ())
    with pytest.raises(ValueError, match="重复路径"):
        build_research_coverage(
            (row,), inventory, (_disposition(row),) * 2, denominator_status="complete"
        )
