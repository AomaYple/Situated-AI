"""Narrow event retention binds current bytes and unambiguous native ownership."""

from __future__ import annotations

import hashlib

import pytest

from pdx import config
from pdx.situated import business_review as business
from pdx.situated.native_treatments import native_treatments
from pdx.situated.vanilla_inventory import VanillaEventOption, VanillaInventory

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def retained_event():
    data = business.load()
    row = next(row for row in data["retained_event_rows"] if not row["named_reference_proof_ids"])
    data = {**data, "rows": [], "parent_contexts": {}, "retained_event_rows": [row]}
    source = row["source"]
    native = {source: (config.GAME / source).read_bytes()}
    candidate = VanillaEventOption(
        source=source,
        definition=row["definition"],
        field=f"option[{row['option_name']}].ai_chance",
        option_index=row["option_index"],
        option_name=row["option_name"],
        event_type=None,
        source_line=row["option_line"],
        weight_lines=(),
        default_option=None,
    )
    inventory = VanillaInventory(
        baseline_id=data["baseline_id"],
        source_hashes={source: hashlib.sha256(native[source]).hexdigest()},
        scope_hash=data["common_scope_hash"],
        surfaces=(),
        scanned_directories=("events",),
        content_roots=("events",),
        parsed_files=1,
        event_options=(candidate,),
    )
    return data, inventory, native


def test_unchanged_event_with_current_complete_candidate_is_retained(retained_event):
    data, inventory, native = retained_event
    receipt = native_treatments(inventory, native, {}, production_complete=True)
    result = business.review(inventory, native, {}, receipt, data=data)
    assert result["counts"] == {data["retained_event_rows"][0]["disposition"]: 1}
    assert result["event_review_rows"][0]["counts_as_new_capability"] is False


@pytest.mark.parametrize("fault", ["stale_receipt", "duplicate_owner", "source_variable"])
def test_retained_event_rejects_stale_receipt_ambiguous_owner_and_source_variable(
    retained_event, fault
):
    data, inventory, native = retained_event
    row = data["retained_event_rows"][0]
    if fault == "source_variable":
        output = {row["source"]: native[row["source"]] + b"\n@forged = 1\n"}
    elif fault == "duplicate_owner":
        output = {"events/forged.txt": (row["definition"] + " = { option = {} }\n").encode()}
    else:
        output = {"events/unrelated.txt": b"unrelated = { option = {} }\n"}
    receipt = native_treatments(
        inventory, native, {} if fault == "stale_receipt" else output, production_complete=True
    )
    result = business.review(inventory, native, output, receipt, data=data)
    assert result["counts"] == {"production_protection_unproven": 1}
