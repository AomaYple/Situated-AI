from dataclasses import replace

from pdx.capability_catalog import FileDisposition
from pdx.input_contracts import InputInventory, InventoryRecord, file_set_digest
from pdx.research_coverage import build_research_coverage


def test_reclassification_uses_current_category_only_with_matching_source() -> None:
    original = InventoryRecord(
        "game/map_data/nodes.dat",
        10,
        "b" * 64,
        "unknown",
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
    disposition = FileDisposition(
        original.path,
        "map_data",
        "observed",
        "not_attempted",
        "not_attempted",
        "unknown",
        "research_only",
        "recognized map format",
    )
    observed = InputInventory("a" * 64, (original,), "complete", ())
    verified = build_research_coverage(
        (original,), observed, (disposition,), denominator_status="complete"
    )
    assert set(verified.by_category) == {"map_data"}
    assert set(verified.by_format) == {("map_data", ".dat")}
    assert "unknown_format" not in verified.gaps[original.path]
    assert verified.file_set_sha256 == file_set_digest((original,))
    assert original.category == "unknown"

    changed = replace(original, sha256="c" * 64)
    unverified = build_research_coverage(
        (original,),
        replace(observed, records=(changed,)),
        (disposition,),
        denominator_status="complete",
    )
    assert set(unverified.by_category) == {"unknown"}
    assert unverified.gaps[original.path] == ("source_identity_mismatch", "unknown_format")
    assert unverified.file_set_sha256 == verified.file_set_sha256
