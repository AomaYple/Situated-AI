"""Current binary evidence identities remain independent from historical fixtures."""

from __future__ import annotations

import hashlib
import json

import pytest

from pdx import version_contracts
from pdx.situated import engine_scope, engine_scope_115

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "kind", ["company", "company-default", "technology", "law", "country-definition"]
)
def test_current_manifest_pins_independent_binary_points(kind):
    path, identity, digest = engine_scope_115.manifest(kind)
    raw = path.read_bytes()
    data = json.loads(raw)
    assert hashlib.sha256(raw).hexdigest() == digest
    assert identity.endswith(f"1.15.0-{kind}-scope.json")
    assert data["exe"]["sha256"] == engine_scope_115.EXE_SHA256
    assert data["exe"]["bytes"] == engine_scope_115.EXE_BYTES
    assert data["runtime"] == "unknown"
    assert data["evidence_kind"] == "binary_static"
    assert data["build_identity"]["caligula_branch"] == "release/1.15.0"
    for point in data["observations"]:
        assert int(point["va"], 16) - int(point["rva"], 16) == 0x140000000
        assert bytes.fromhex(point["bytes"])


@pytest.mark.parametrize(
    ("kind", "method"),
    [
        ("company", engine_scope.company_evidence),
        ("technology", engine_scope.technology_evidence),
        ("law", engine_scope.law_evidence),
        ("country-definition", engine_scope.country_evidence),
    ],
)
def test_current_missing_executable_never_falls_back_to_old_proof(tmp_path, kind, method):
    with version_contracts.select_version("1.15.0"):
        proof = method(tmp_path / "game", {})
    _, identity, digest = engine_scope_115.manifest(kind)
    assert proof.verified is False
    assert proof.source_hashes == ((f"@evidence/{identity}", digest),)


@pytest.mark.parametrize(
    "kind", ["company", "company-default", "technology", "law", "country-definition"]
)
def test_current_manifest_drift_is_rejected_before_executable_lookup(tmp_path, monkeypatch, kind):
    path, identity, digest = engine_scope_115.manifest(kind)
    changed = tmp_path / "changed.json"
    changed.write_bytes(path.read_bytes() + b" ")
    monkeypatch.setitem(engine_scope_115.MANIFESTS, kind, (str(changed), digest))
    with version_contracts.select_version("1.15.0"):
        if kind == "company-default":
            with pytest.raises(ValueError, match="变化"):
                engine_scope.company_default_snapshot()
        else:
            method = getattr(engine_scope, f"{kind.replace('-definition', '')}_evidence")
            with pytest.raises(ValueError, match="变化"):
                method(tmp_path / "game", {})
    assert "1.15.0" in identity


def test_current_company_default_is_the_exact_new_initializer():
    with version_contracts.select_version("1.15.0"):
        data = json.loads(engine_scope.company_default_snapshot())
    contract = data["contracts"][0]
    assert contract["source_requirement"] == "exactly_missing_ai_weight_only"
    assert contract["explicit_empty_requirement"] == "reject_initializer"
    assert contract["define_field"] == "NAI.COMPANY_TYPE_DEFAULT_BASE_WEIGHT"
    assert len(data["implicit_companies"]) == 26


def test_unknown_current_family_has_no_historical_permission():
    with pytest.raises(ValueError, match="尚无独立引擎"):
        engine_scope_115.manifest("unreviewed-field")


@pytest.fixture(autouse=True)
def _historical_1150_contract():
    """Keep the exact archived witness under its original version identity."""
    with version_contracts.select_version("1.15.0"):
        yield
