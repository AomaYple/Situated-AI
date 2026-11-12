"""生成结果与元数据必须绑定同次输入，独立调用仍重新读取模型。"""

import json
from dataclasses import replace

import pytest

from pdx import decisions, version_contracts

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module", autouse=True)
def historical_assembly_contract():
    """Exercise input identity assembly with the frozen offline 1.14.5 contract.

    Current generation verifies live sources and is covered by release integration.
    """
    with version_contracts.select_version("1.14.5"):
        yield


@pytest.fixture(scope="module")
def model(historical_assembly_contract):
    return decisions.load_situated_model()


def test_build_metadata_uses_the_model_that_generated_the_scripts(model, monkeypatch):
    calls = []

    def load(**kwargs):
        calls.append(kwargs)
        return replace(
            model, source_sha256={**model.source_sha256, "identity_probe": str(len(calls))}
        )

    monkeypatch.setattr(decisions, "load_situated_model", load)
    files = decisions.build()
    metadata = json.loads(files[".metadata/metadata.json"])
    assert metadata["source_fingerprint"]["situated_identity_probe_source_sha256"] == "1"
    assert len(calls) == 1
    assert metadata["situated_actions"]["action_instances"]["count"] == len(model.action_instances)


def test_standalone_metadata_reads_fresh_inputs_on_every_call(model, monkeypatch):
    calls = []

    def load(**kwargs):
        calls.append(kwargs)
        return replace(
            model, source_sha256={**model.source_sha256, "identity_probe": str(len(calls))}
        )

    monkeypatch.setattr(decisions, "load_situated_model", load)
    first = decisions.metadata_payload()["source_fingerprint"]
    second = decisions.metadata_payload()["source_fingerprint"]
    assert isinstance(first, dict)
    assert isinstance(second, dict)
    assert first["situated_identity_probe_source_sha256"] == "1"
    assert second["situated_identity_probe_source_sha256"] == "2"
    assert len(calls) == 2


def test_invalid_model_still_stops_generation_before_output(monkeypatch):
    def invalid(**kwargs):
        raise ValueError("invalid current model")

    monkeypatch.setattr(decisions, "load_situated_model", invalid)
    with pytest.raises(ValueError, match="invalid current model"):
        decisions.build()
