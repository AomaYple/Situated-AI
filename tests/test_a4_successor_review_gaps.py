"""Fully rebound review counterexamples, independent of stale envelope hashes."""

from copy import deepcopy

import pytest
from test_a4_successor import _bind, _case

from tools.ci import a4_discovery as discovery
from tools.ci import a4_successor as successor
from tools.ci.a4_scope import Sources


def _resign(sources, transition, intake):
    raw = {**sources.bytes, "transition.json": discovery.encoded(transition)}
    result = Sources(sources.root, raw)
    intake["successor"] = result.reference("transition.json")
    return result


@pytest.mark.parametrize(
    "fault",
    [
        "package_only",
        "other_writer",
        "other_context",
        "other_getter",
        "wrong_role",
        "wrong_side",
        "missing_producer",
        "missing_context",
        "missing_getter",
        "missing_native",
        "missing_production",
        "wrong_native_consumer",
        "native_context_open",
        "native_role_unknown",
        "row_payload",
        "whole_row_file",
    ],
)
def test_review_authority_relevance_rejects_fully_resigned_unrelated_proofs(tmp_path, fault):
    sources, before, after, transition, intake = _case(tmp_path)
    sources = _bind(sources, before, after, transition, intake)
    change = transition["changes"][0]
    entries = change["authority"]
    raw = dict(sources.bytes)
    if fault == "package_only":
        change["authority"] = [sources.reference("current.zip")]
    elif fault.startswith("missing_"):
        role = fault.removeprefix("missing_")
        change["authority"] = [entry for entry in entries if entry["role"] != role]
    elif fault in {"other_writer", "other_context", "row_payload", "whole_row_file"}:
        endpoint = deepcopy(after)
        endpoint["migration_writers"]["writer:other"] = deepcopy(
            endpoint["migration_writers"]["writer:domain"]
        )
        endpoint["migration_writers"]["writer:other"]["consumer_id"] = "other.unknown"
        if fault == "row_payload":
            endpoint["migration_writers"]["writer:domain"]["semantic_role"] = "wrong_role"
        raw["rebound-endpoint.json"] = discovery.encoded(endpoint)
        revised = Sources(tmp_path, raw)
        role = "context" if fault == "other_context" else "producer"
        entry = next(item for item in entries if item["role"] == role)
        if fault == "whole_row_file":
            entry["reference"] = revised.reference("rebound-endpoint.json")
        else:
            name = "writer:other" if fault != "row_payload" else "writer:domain"
            entry["reference"] = revised.reference(
                "rebound-endpoint.json", f"migration_writers/{name}", "json"
            )
    elif fault == "other_getter":
        raw["other-getter.json"] = discovery.encoded(
            {"fact:other": {"getter": "wrong_country_getter"}}
        )
        revised = Sources(tmp_path, raw)
        next(item for item in entries if item["role"] == "getter")["reference"] = revised.reference(
            "other-getter.json", "fact:other", "json"
        )
    elif fault == "wrong_role":
        next(item for item in entries if item["role"] == "getter")["role"] = "producer"
    elif fault == "wrong_side":
        entries[0]["side"] = "before"
    else:
        report = deepcopy(sources.json("native-proof.json"))
        row = report["native_treatments"]["rows"][0]
        if fault == "wrong_native_consumer":
            row["definition"] = "unrelated_consumer"
        elif fault == "native_context_open":
            row["source_protection"]["context_closed"] = False
        else:
            row["source_protection"]["proven"] = False
            row["interface"]["control_authorized"] = False
        raw["native-proof.json"] = discovery.encoded(report)
        transition["native_proof"] = Sources(tmp_path, raw).reference("native-proof.json")
        next(item for item in entries if item["role"] == "native")["reference"] = transition[
            "native_proof"
        ]
    sources = _resign(Sources(tmp_path, raw), transition, intake)

    def gate():
        successor.contract(sources, intake)
        return successor.admit(sources, before, after, transition, frozen=sources)

    with pytest.raises(ValueError, match=r"authority|schema fields"):
        gate()


def test_review_complete_current_producer_repin_is_endpoint_only_not_product_acceptance(tmp_path):
    sources, before, after, transition, intake = _case(tmp_path)
    raw = dict(sources.bytes)
    raw["src/pdx/producer.py"] += b"# reviewed new normal producer\n"
    raw["mod/generation-lock.json"] = discovery.encoded(
        {
            "sources": {"src/pdx/producer.py": discovery.sha(raw["src/pdx/producer.py"])},
            "files": {},
        }
    )
    sources = _bind(Sources(tmp_path, raw), before, after, transition, intake)
    successor.contract(sources, intake)
    assert successor.admit(sources, before, after, transition, frozen=sources) == (
        ["writer:domain"],
        {},
    )
    # Normal production/native reconstruction and independent witness gates
    # remain separate; this finite admission never claims product completion.


def test_review_omitted_producer_entry_rejected_after_lock_and_declaration_resigned(tmp_path):
    sources, before, after, transition, intake = _case(tmp_path)
    raw = dict(sources.bytes)
    raw["src/pdx/hidden_producer.py"] = b"def actual_helper():\n    return 1\n"
    # Keep a valid nonempty, fully rehashed lock which omits the helper.
    sources = _bind(Sources(tmp_path, raw), before, after, transition, intake)
    successor.contract(sources, intake)
    with pytest.raises(ValueError, match="complete production source inventory"):
        successor.admit(sources, before, after, transition, frozen=sources)


@pytest.mark.parametrize("wrong_old_lock", [False, True])
def test_removed_writer_binds_its_own_frozen_production_closure(tmp_path, wrong_old_lock):
    original, before, after, transition, intake = _case(tmp_path)
    frozen = Sources(tmp_path, dict(original.bytes))
    after["migration_writers"]["writer:new"] = after["migration_writers"].pop("writer:domain")
    transition["tombstones"] = [
        {
            "writer_id": "writer:domain",
            "before_sha256": discovery.digest(before["migration_writers"]["writer:domain"]),
            "successor_ids": ["writer:new"],
            "reason": "reviewed replacement",
            "witness_nodes": intake["witness_nodes"],
        }
    ]
    raw = dict(original.bytes)
    raw["src/pdx/producer.py"] += b"# new current producer\n"
    raw["mod/generation-lock.json"] = discovery.encoded(
        {
            "sources": {"src/pdx/producer.py": discovery.sha(raw["src/pdx/producer.py"])},
            "files": {},
        }
    )
    raw["old-production-lock.json"] = (
        raw["mod/generation-lock.json"]
        if wrong_old_lock
        else frozen.read("mod/generation-lock.json")
    )
    sources = _bind(Sources(tmp_path, raw), before, after, transition, intake)
    removed = next(item for item in transition["changes"] if item["identity"] == "writer:domain")
    next(item for item in removed["authority"] if item["role"] == "production")["reference"] = (
        sources.reference("old-production-lock.json")
    )
    sources = _resign(sources, transition, intake)
    successor.contract(sources, intake)
    if wrong_old_lock:
        with pytest.raises(ValueError, match="production lock differs from exact endpoint"):
            successor.admit(sources, before, after, transition, frozen=frozen)
    else:
        changed, registry = successor.admit(sources, before, after, transition, frozen=frozen)
        assert changed == ["writer:domain", "writer:new"]
        assert registry["writer:domain"]["product_authority"] is False
