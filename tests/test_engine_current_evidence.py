"""Current PE contracts bind reviewed fields to one installed build."""

from __future__ import annotations

import hashlib
import json
import re

import pytest

from pdx import version_contracts
from pdx.situated import engine_scope, engine_scope_115, engine_strategy_115

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "kind",
    [
        "building-default",
        "company",
        "company-default",
        "country-definition",
        "defensive-pact-reader",
        "law",
        "strategy",
        "technology",
    ],
)
def test_current_engine_manifest_pins_digest_only_ranges(kind):
    with version_contracts.select_version(version_contracts.CURRENT_VERSION):
        path, identity, digest = engine_scope_115.manifest(kind)
        exe_digest, exe_size = engine_scope_115.executable_identity()
    raw = path.read_bytes()
    data = json.loads(raw)
    assert identity == f"research/situated/{version_contracts.CURRENT_VERSION}/engine-{kind}.json"
    assert hashlib.sha256(raw).hexdigest() == digest
    assert (data["exe"]["sha256"], data["exe"]["bytes"]) == (exe_digest, exe_size)
    assert data["runtime"] == "unknown"
    assert data["evidence_category"] == "static_check"
    assert data["observations"]
    for point in data["observations"]:
        assert set(point) == {"label", "va", "rva", "file_offset", "size", "sha256"}
        assert int(point["va"], 16) - int(point["rva"], 16) == int(data["exe"]["image_base"], 16)
        assert type(point["size"]) is int
        assert 0 < int(point["file_offset"], 16) + point["size"] <= exe_size
        assert re.fullmatch(r"[a-f0-9]{64}", point["sha256"])


@pytest.mark.parametrize("mutation", ["executable", "observation", "active_call"])
def test_current_strategy_rejects_changes_even_if_the_json_is_repinned(mutation):
    with version_contracts.select_version(version_contracts.CURRENT_VERSION):
        strategy = json.loads(engine_scope.strategy_snapshot())
        assert len(strategy["consumers"]) == 33
        if mutation == "executable":
            strategy["exe"]["bytes"] -= 1
        elif mutation == "observation":
            strategy["observations"] = [
                point
                for point in strategy["observations"]
                if "33 token paths" not in point["label"]
            ]
        else:
            row = strategy["strategy_field_merges"]["change_law_chance"]
            row["active_call"], row["default_call"] = row["default_call"], row["active_call"]
        with pytest.raises(ValueError):
            engine_strategy_115.validate(strategy)
