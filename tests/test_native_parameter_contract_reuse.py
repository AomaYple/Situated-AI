"""Call-local reader contract reuse retains exact source and failure identity."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from pdx import decision_adapters, decision_rules, production_inputs
from pdx.situated import native_treatments, programs
from pdx.situated.ir import from_rule
from pdx.situated.native_treatments import _Dependencies, _Sources

pytestmark = pytest.mark.unit
METADATA = ".metadata/metadata.json"
SOURCES = ("common/buildings/first.txt", "common/buildings/second.txt")


def _wire_contract(source, policy, joint):
    if joint:
        policy = programs.enable(
            replace(
                policy,
                semantic_ir=tuple(
                    replace(from_rule(rule, source=source), origin_priority=rule.priority)
                    for rule in policy.rules
                ),
            ),
            source=source,
        )
    return json.loads(
        json.dumps(
            {
                "source": source,
                **decision_rules.contract(policy, owner="consumer_adapters", source=source),
            }
        )
    )


@pytest.fixture(params=[False, True], ids=["legacy", "joint"])
def candidate(request, monkeypatch):
    reader = decision_rules.Reader(
        "price",
        "market_goods_pricier",
        "root",
        "price_above_base_ratio",
        "number",
        path=("owner", "market", "mg:tools"),
    )
    native = {"common/goods/fixture.txt": b"tools={}"}
    policies = []
    identities: list[tuple[str, str, str, str]] = []
    for index, source in enumerate(SOURCES):
        definition = f"building_{index}"
        native[source] = f"{definition}={{weight={{value=10}} other={{value=20}}}}".encode()
        rules = tuple(
            decision_rules.Rule(
                f"reader_{index}_{field}",
                "fixture",
                (definition, field),
                priority,
                2,
                (decision_rules.Predicate("price", "<=", 0.25),),
                "fixture",
                "fixture",
                operation="add",
            )
            for field, priority in (("weight", 20), ("other", 10))
        )
        policy = decision_rules.RuleSet(
            (reader,),
            rules,
            hashlib.sha256(native[source]).hexdigest(),
            str(index) * 64,
            frozenset({"fixture"}),
            actor_path=("owner",),
            native_root="state",
        )
        policies.append((source, policy))
        identities.extend((source, definition, field, "state") for field in ("weight", "other"))
    adapters = decision_adapters.AdapterSet(
        tuple((source, hashlib.sha256(raw).hexdigest()) for source, raw in native.items()),
        tuple(policies),
        "a" * 64,
    )
    monkeypatch.setattr(decision_adapters, "load", lambda: adapters)
    metadata = {
        "consumer_adapters": {
            "schema": 1,
            "source_sha256": adapters.source_sha256,
            "generator_sha256": hashlib.sha256(
                Path(decision_adapters.__file__).read_bytes()
            ).hexdigest(),
            "production_inputs_generator_sha256": hashlib.sha256(
                Path(production_inputs.__file__).read_bytes()
            ).hexdigest(),
            "sources": dict(adapters.sources),
            "consumers": [
                _wire_contract(source, policy, request.param) for source, policy in policies
            ],
        }
    }
    effective = {**native, METADATA: json.dumps(metadata).encode()}
    return native, effective, identities, metadata, request.param


def _dependencies(candidate):
    native, effective, *_ = candidate
    return _Dependencies(
        _Sources(native),
        _Sources(effective),
        native,
        effective,
        {source: hashlib.sha256(raw).hexdigest() for source, raw in native.items()},
        production_complete=True,
    )


def _counts(monkeypatch, effective):
    calls: Counter[str] = Counter()
    load = json.loads
    contract = decision_rules.contract
    enable = programs.enable

    def counted_load(raw, *args, **kwargs):
        if raw is effective[METADATA]:
            calls["metadata"] += 1
        return load(raw, *args, **kwargs)

    def counted_contract(policy, *, owner, source):
        calls[source] += 1
        return contract(policy, owner=owner, source=source)

    def counted_enable(policy, *, source):
        calls["program:" + source] += 1
        return enable(policy, source=source)

    monkeypatch.setattr(native_treatments.json, "loads", counted_load)
    monkeypatch.setattr(decision_rules, "contract", counted_contract)
    monkeypatch.setattr(programs, "enable", counted_enable)
    return calls


def test_metadata_once_and_complete_contract_once_per_source(candidate, monkeypatch):
    deps = _dependencies(candidate)
    calls = _counts(monkeypatch, candidate[1])
    proofs = [deps.parameter_readers(*identity) for identity in candidate[2]]
    assert all(proof["bindings"] and proof["native_sources"] for proof in proofs)
    expected_calls = {"metadata": 1, **dict.fromkeys(SOURCES, 2 if candidate[4] else 1)}
    if candidate[4]:
        expected_calls.update(dict.fromkeys(("program:" + source for source in SOURCES), 1))
    assert calls == expected_calls
    # Fresh audit instances rebuild every identity, with byte-for-byte equal
    # proof payloads; this reuse never survives an audit invocation.
    for identity, expected in zip(candidate[2], proofs, strict=True):
        assert _dependencies(candidate).parameter_readers(*identity) == expected
    assert calls["metadata"] == 5


@pytest.mark.parametrize("fault", ["json", "header", "contract", "duplicate", "program"])
def test_bad_metadata_rejection_cannot_be_repaired_by_another_field_or_source(
    candidate, monkeypatch, fault
):
    _, effective, identities, metadata, joint = candidate
    consumers = metadata["consumer_adapters"]["consumers"]
    if fault == "json":
        effective[METADATA] = b"{broken"
    elif fault == "header":
        metadata["consumer_adapters"]["source_sha256"] = "f" * 64
    elif fault == "contract":
        consumers[0]["source_sha256"] = "f" * 64
    elif fault == "duplicate":
        consumers.append(dict(consumers[0]))
    elif joint:
        consumers[0]["consumer_programs"]["programs"][0]["groups"][0]["variants"][0][
            "origin_priority"
        ] = 999
    else:
        consumers[0]["unexpected_permission"] = True
    if fault != "json":
        effective[METADATA] = json.dumps(metadata).encode()
    deps = _dependencies(candidate)
    calls = _counts(monkeypatch, effective)
    assert deps.parameter_readers(*identities[0]) == {}
    assert deps.parameter_readers(*identities[1]) == {}
    assert bool(deps.parameter_readers(*identities[2])) == (fault not in {"json", "header"})
    assert calls["metadata"] == 1
    assert calls[SOURCES[0]] <= (2 if joint else 1)


@pytest.mark.parametrize("mapping", ["native", "metadata", "effective"])
def test_input_mapping_mutation_rejects_even_an_already_cached_field(candidate, mapping):
    native, effective, identities, *_ = candidate
    deps = _dependencies(candidate)
    assert deps.parameter_readers(*identities[0])
    if mapping == "native":
        native[SOURCES[0]] += b"\n# drift"
    elif mapping == "metadata":
        effective[METADATA] = b"{}"
    else:
        effective[SOURCES[0]] += b"\n# drift"
    assert deps.parameter_readers(*identities[0]) == {}
    assert deps.parameter_readers(*identities[1]) == {}
    assert deps.parameter_readers(*identities[2]) == {}


@pytest.mark.parametrize("module", [decision_adapters, production_inputs])
def test_generator_drift_rejects_cached_contract_and_field(
    candidate, monkeypatch, tmp_path, module
):
    deps = _dependencies(candidate)
    identities = candidate[2]
    assert deps.parameter_readers(*identities[0])
    changed = tmp_path / "changed_generator.py"
    changed.write_bytes(Path(module.__file__).read_bytes() + b"\n# drift")
    monkeypatch.setattr(module, "__file__", str(changed))
    assert deps.parameter_readers(*identities[0]) == {}
    assert deps.parameter_readers(*identities[1]) == {}
    assert deps.parameter_readers(*identities[2]) == {}


def test_source_scope_field_and_native_hash_are_checked_after_contract_reuse(candidate):
    deps = _dependencies(candidate)
    first, second = candidate[2][:2]
    assert deps.parameter_readers(*first)
    assert deps.parameter_readers(*(*second[:3], "country")) == {}
    assert deps.parameter_readers(*(*second[:2], "invented", second[3])) == {}
    assert deps.parameter_readers(SOURCES[1], first[1], first[2], first[3]) == {}
    # A newly created audit must reject drift even when the caller repins its
    # inventory hash: the locked adapter source/base identity still differs.
    candidate[0][SOURCES[0]] += b"\n# repinned inventory drift"
    fresh = _dependencies(candidate)
    assert fresh.parameter_readers(*second) == {}


def test_missing_metadata_is_not_licensed_by_another_audit(candidate):
    native, effective, identities, *_ = candidate
    first = _dependencies(candidate)
    assert first.parameter_readers(*identities[0])
    missing = {name: raw for name, raw in effective.items() if name != METADATA}
    changed = (native, missing, *candidate[2:])
    second = _dependencies(changed)
    assert second.parameter_readers(*identities[0]) == {}
    assert second.parameter_readers(*identities[2]) == {}
    assert first.parameter_readers(*identities[0])
