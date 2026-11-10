"""Country population signatures stay versioned across generation and evaluation."""

import hashlib
from copy import deepcopy
from dataclasses import replace

import pytest

from pdx import decision_adapters, decision_interfaces, decision_rules, version_contracts
from pdx.parser import parse_text
from pdx.situated import native_treatments, pdx_eval, vanilla_inventory


def _declaration(version, pop_type="peasants"):
    current = version == "1.15.0"
    return {
        "schema": 1,
        "baseline_sha256": "0" * 64,
        "domains": {"political": True},
        "readers": {
            "population": {
                "engine": "pop_type_percent_country",
                "scope": "root",
                "unit": "ratio",
                "kind": "number",
                "minimum": 0,
                "maximum": 1,
                "value_field": "value" if current else "percent",
                "parameters": {"target": f"pop_type:{pop_type}"}
                if current
                else {"pop_type": pop_type},
            }
        },
        "rules": [
            {
                "id": "population_need",
                "domain": "political",
                "field": "law_demo.ai_enact_weight_modifier",
                "priority": 1,
                "operation": "add",
                "value": 5,
                "conditions": [{"fact": "population", "op": ">=", "value": 0.6}],
                "why": "合成人口比例跨版本合同",
                "counterexample": "合成求值不构成游戏实机证明",
            }
        ],
    }


@pytest.mark.parametrize("version", ["1.14.5", "1.15.0"])
@pytest.mark.parametrize("pop_type", ["peasants", "laborers", "machinists"])
def test_selected_population_signature_round_trips_independent_pdx(version, pop_type):
    with version_contracts.select_version(version):
        policy = decision_rules.from_data(_declaration(version, pop_type), source_sha256="0" * 64)
        reader = policy.readers[0]
        assert decision_interfaces.reader_scope(reader, ()) == "country"
        script = reader.expression(">=", 0.6)
        parsed = parse_text(script)
        assert not parsed.errors
        for share, expected in ((0.59, False), (0.6, True), (0.9, True), (None, None)):
            assert (
                pdx_eval.condition(parsed.root, {reader.engine: {reader.parameters: share}})
                is expected
            )
        assert pdx_eval.condition(parsed.root, {reader.engine: {}}) is None


@pytest.mark.parametrize("version", ["1.14.5", "1.15.0"])
def test_wrong_version_population_signature_is_rejected_everywhere(version):
    other = "1.14.5" if version == "1.15.0" else "1.15.0"
    with version_contracts.select_version(other):
        other_policy = decision_rules.from_data(_declaration(other), source_sha256="0" * 64)
        other_reader = other_policy.readers[0]
        other_script = other_reader.expression(">=", 0.6)
    with version_contracts.select_version(version):
        with pytest.raises(ValueError):
            decision_rules.from_data(_declaration(other), source_sha256="0" * 64)
        with pytest.raises(ValueError):
            decision_interfaces.reader_scope(other_reader, ())
        with pytest.raises(ValueError):
            other_reader.expression(">=", 0.6)
        # Syntax validation must still reject a wrong signature with no facts.
        with pytest.raises(pdx_eval.UnsupportedPdxError):
            pdx_eval.condition(parse_text(other_script).root, {})


@pytest.mark.parametrize(
    ("parameters", "value_field"),
    [
        ({"target": "peasants"}, "value"),
        ({"target": "pop_type:slaves"}, "value"),
        ({"target": "pop_type:peasants"}, "percent"),
        ({"pop_type": "peasants"}, "value"),
        ({"target": "pop_type:peasants", "pop_type": "peasants"}, "value"),
    ],
)
def test_current_population_rejects_mixed_or_unregistered_argument(parameters, value_field):
    with version_contracts.select_version("1.15.0"):
        data = _declaration("1.15.0")
        data["readers"]["population"].update(parameters=parameters, value_field=value_field)
        with pytest.raises(ValueError):
            decision_rules.from_data(data, source_sha256="0" * 64)
        valid = decision_rules.from_data(_declaration("1.15.0"), source_sha256="0" * 64).readers[0]
        wrong = replace(
            valid, parameters=tuple(sorted(parameters.items())), value_field=value_field
        )
        with pytest.raises(ValueError):
            decision_interfaces.reader_scope(wrong, ())
        with pytest.raises(ValueError):
            wrong.expression(">=", 0.6)
        body = " ".join(f"{key}={value}" for key, value in parameters.items())
        script = f"pop_type_percent_country={{{body} {value_field}>=0.6}}"
        with pytest.raises(pdx_eval.UnsupportedPdxError):
            pdx_eval.condition(parse_text(script).root, {})


def test_current_adapter_projection_covers_all_production_population_readers():
    with version_contracts.select_version("1.15.0"):
        readers = {
            reader.key: reader
            for _, policy in decision_adapters.load().policies
            for reader in policy.readers
            if reader.engine == "pop_type_percent_country"
        }
        assert {
            key: (reader.parameters, reader.value_field) for key, reader in readers.items()
        } == {
            key: ((("target", f"pop_type:{pop_type}"),), "value")
            for key, pop_type in {
                "peasant_share": "peasants",
                "industrial_workforce": "laborers",
                "skilled_workforce": "machinists",
            }.items()
        }
        for reader in readers.values():
            assert decision_interfaces.reader_scope(reader, ()) == "country"


@pytest.mark.parametrize("pop_type", ["peasants", "laborers", "machinists"])
def test_current_population_patch_binds_native_typed_template_and_definition(pop_type):
    source = "law_demo={ai_enact_weight_modifier={value=0}}"
    evidence = (
        "pop_type_percent_country={target=pop_type:peasants value>0.6} "
        "peasants={} laborers={} machinists={}"
    )
    with version_contracts.select_version("1.15.0"):
        data = _declaration("1.15.0", pop_type)
        data["baseline_sha256"] = hashlib.sha256(source.encode()).hexdigest()
        policy = decision_rules.from_data(data, source_sha256="0" * 64)
        patched = decision_rules.patch(
            source, policy, baseline=source, default_strategy=False, reader_evidence=evidence
        )
        assert f"target = pop_type:{pop_type} value >= 0.6" in patched
        with pytest.raises(ValueError, match="读取器没有锁定原版依据"):
            decision_rules.patch(
                source,
                policy,
                baseline=source,
                default_strategy=False,
                reader_evidence="pop_type_percent_country={} peasants={} laborers={} machinists={}",
            )


def test_current_projection_rejects_historical_declaration_drift():
    from pdx.situated.engine_reader_115 import project_population_readers

    readers = deepcopy(_declaration("1.14.5")["readers"])
    readers["population"]["parameters"] = {"pop_type": "slaves"}
    with pytest.raises(ValueError, match="historical declaration drift"):
        project_population_readers(readers)


@pytest.mark.parametrize("version", ["1.14.5", "1.15.0"])
def test_native_population_proof_rejects_wrong_version_ast_even_with_correct_hash(
    version, monkeypatch
):
    source = "common/journal_entries/00_urbanization.txt"
    definition = "common/pop_types/peasants.txt"
    current = version == "1.15.0"
    correct = b"target=pop_type:peasants value>0.6" if current else b"pop_type=peasants percent>0.6"
    wrong = b"pop_type=peasants percent>0.6" if current else b"target=pop_type:peasants value>0.6"
    pins: dict[str, str] = {}
    monkeypatch.setattr(vanilla_inventory, "_parameter_evidence_contract", lambda: pins)

    def dependencies(fragment):
        raw = {
            source: b"je_urbanization_events_1={possible={pop_type_percent_country={"
            + fragment
            + b"}}}",
            definition: b"peasants={wage_weight=1}",
        }
        pins.update({name: hashlib.sha256(value).hexdigest() for name, value in raw.items()})
        native = native_treatments._Sources(raw)
        return native_treatments._Dependencies(
            native,
            native_treatments._Sources(raw, reuse=native),
            raw,
            raw,
            dict(pins),
            production_complete=True,
        )

    with version_contracts.select_version(version):
        reader = decision_rules.from_data(_declaration(version), source_sha256="0" * 64).readers[0]
        assert set(dependencies(correct).population_parameter_sources(reader)) == {
            source,
            definition,
        }
        assert dependencies(wrong).population_parameter_sources(reader) == {}
