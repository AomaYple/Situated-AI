"""Bounded static interface investigation is never a capability declaration."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from pdx.situated import interface_boundaries as boundaries

pytestmark = pytest.mark.unit


def test_offline_contract_has_exact_eight_unproven_topics_and_no_runtime_authority():
    reports = boundaries.verify_inputs(boundaries.frozen_inputs())
    assert {row.id for row in reports} == {
        "strata_tax_amounts",
        "qualification_stock",
        "innovation_cap_gap",
        "mobilized_workers",
        "precise_peace_writer",
        "dynamic_pm_writer",
        "direct_trade_route_writer",
        "convoy_loss_amount",
    }
    assert {row.status for row in reports} == {"bounded_unproven"}
    assert all(row.creates_reader is False and row.creates_writer is False for row in reports)


@pytest.mark.parametrize("topic", sorted(boundaries.TOPICS))
def test_each_topic_requires_complete_frozen_source_identity(topic):
    data = boundaries.load()
    row = next(row for row in data["boundaries"] if row["id"] == topic)
    source = row["examined_sources"][0]
    changed = boundaries.frozen_inputs()
    changed[source] += "\n# source drift\n"
    with pytest.raises(ValueError, match="来源漂移"):
        boundaries.verify_inputs(changed)


def test_repinning_a_source_does_not_hide_new_active_getter_candidates(monkeypatch):
    data = deepcopy(boundaries.load())
    changed = boundaries.frozen_inputs()
    row = next(row for row in data["boundaries"] if row["id"] == "qualification_stock")
    source = row["examined_sources"][0]
    changed[source] += "\nqualification_probe = { qualified_population = 10 }\n"
    data["sources"][source]["normalized_sha256"] = hashlib.sha256(
        changed[source].encode()
    ).hexdigest()
    monkeypatch.setattr(boundaries, "load", lambda: data)
    with pytest.raises(ValueError, match="有限查询集合变化"):
        boundaries.verify_inputs(changed)


@pytest.mark.parametrize("mutation", ["unsupported", "missing_topic", "external_carrier"])
def test_unproven_boundary_cannot_grant_runtime_authority_or_omit_a_topic(
    monkeypatch, tmp_path, mutation
):
    data = deepcopy(boundaries.load())
    if mutation == "unsupported":
        data["boundaries"][0]["status"] = "unsupported"
    elif mutation == "missing_topic":
        data["boundaries"].pop()
    else:
        data["sources"][next(iter(data["sources"]))]["carrier"] = "../outside.json"
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(boundaries, "CONTRACT", path)
    with pytest.raises(ValueError):
        boundaries.load()
