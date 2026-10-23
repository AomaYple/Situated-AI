"""纯合成候选覆盖连接；不依赖游戏安装或同名词袋。"""

from __future__ import annotations

import copy
import json
from dataclasses import replace

import pytest
from typer.testing import CliRunner

from pdx import candidate_coverage, cli, config
from pdx.information_catalog import InformationCatalog, InformationItem, InformationStatus

SOURCE = "common/ai_strategies/00_default_strategy.txt"


def _item(name="ai_strategy_default.state_value", *, source=SOURCE, status=None):
    return InformationItem(
        id=f"stable:{source}:{name}",
        domain="game/common/ai_strategies",
        name=name,
        source=f"game/{source}",
        source_sha256="a" * 64,
        source_line=42,
        status=status or InformationStatus.DISCOVERED,
    )


def _contract(field, *, source=None):
    result = {
        "schema": 1,
        "baseline_sha256": "b" * 64,
        "enabled_domains": ["political"],
        "active_rule_count": 1,
        "source_sha256": "c" * 64,
        "generator_sha256": "d" * 64,
        "readers": [
            {
                "key": "debt",
                "engine": "scaled_debt",
                "scope": "root",
                "unit": "ratio",
                "kind": "number",
            },
            {
                "key": "unused",
                "engine": "gdp",
                "scope": "root",
                "unit": "currency",
                "kind": "number",
            },
        ],
        "rules": [
            {
                "id": "example",
                "field": field,
                "domain": "political",
                "inputs": ["debt"],
                "consumer": {"role": "strategy", "impact": "B"},
            }
        ],
    }
    if source is not None:
        result["source"] = source
    return result


@pytest.fixture
def inputs():
    item = _item()
    catalog = InformationCatalog(
        version={"caligula_branch": "release/1.14.5"}, roots={}, items=(item, _item("static"))
    )
    metadata = {
        "id": config.MOD_ID,
        "version": "0.1.0",
        "supported_game_version": "1.14.5",
        "enabled_modules": ["information_rules", "consumer_adapters"],
        "source_fingerprint": {
            "information_rules_source_sha256": "c" * 64,
            "information_rules_generator_sha256": "d" * 64,
            "consumer_adapters_source_sha256": "c" * 64,
            "consumer_adapters_generator_sha256": "d" * 64,
        },
        "decision_rules": _contract("state_value"),
        "consumer_adapters": {
            "schema": 1,
            "source_sha256": "c" * 64,
            "generator_sha256": "d" * 64,
            "sources": {SOURCE: "b" * 64},
            "consumers": [_contract("ai_strategy_default.state_value.extra", source=SOURCE)],
            "field_owners": [
                {
                    "source": SOURCE,
                    "field": "ai_strategy_default.state_value.extra",
                    "owner": "adapter",
                }
            ],
        },
        "vanilla_field_coverage": [
            {
                "source": SOURCE,
                "field": "negotiation_chance",
                "line": 140,
                "status": "retained_vanilla_not_new_mod_implementation",
            },
            {
                "source": SOURCE,
                "field": "state_value",
                "line": 1401,
                "status": "generated_intervention",
            },
        ],
    }
    return catalog, metadata


def test_exact_source_and_nearest_ancestor_preserve_depth_and_reader_dependencies(inputs):
    catalog, metadata = inputs
    before = copy.deepcopy(metadata)
    report = candidate_coverage.build(catalog, metadata)
    exact, deep = report["links"]
    assert exact["information_id"] == catalog.items[0].id
    assert exact["match"] == "exact"
    assert deep["match"] == "catalog_ancestor_only"
    assert deep["matched_depth"] == 2
    assert deep["requested_depth"] == 3
    assert deep["unmatched_suffix"] == ["extra"]
    assert deep["subtree_coverage"] == "not_claimed"
    assert [row["key"] for row in deep["readers"]] == ["debt"]
    assert report["discovered_not_in_candidate"] == [catalog.items[1].id]
    assert metadata == before
    deep["readers"][0]["key"] = "changed"
    assert metadata == before


def test_missing_consumer_is_explicit_unresolved_without_false_field_match(inputs):
    catalog, metadata = inputs
    changed = replace(catalog, items=(_item("ai_strategy_default.state_value_extra"),))
    report = candidate_coverage.build(changed, metadata)
    assert report["links"] == []
    assert {row["reason"] for row in report["unresolved"]} == {"catalog_consumer_not_found"}
    assert report["discovered_not_in_candidate"] == [changed.items[0].id]


def test_same_name_in_another_source_never_matches(inputs):
    catalog, metadata = inputs
    changed = replace(catalog, items=(_item(source="common/ai_strategies/other.txt"),))
    assert candidate_coverage.build(changed, metadata)["links"] == []


def test_nearest_explicit_ancestor_wins_without_covering_the_parent_subtree(inputs):
    catalog, metadata = inputs
    parent = _item("ai_strategy_default")
    changed = replace(catalog, items=(*catalog.items, parent))
    report = candidate_coverage.build(changed, metadata)
    assert {row["information_id"] for row in report["links"]} == {catalog.items[0].id}
    assert parent.id in report["discovered_not_in_candidate"]


@pytest.mark.parametrize("status", list(InformationStatus))
def test_states_unknowns_and_sha_contracts_are_not_promoted_or_compared(inputs, status):
    catalog, metadata = inputs
    changed = replace(catalog, items=(_item(status=status),))
    report = candidate_coverage.build(changed, metadata)
    assert changed.items[0].status is status
    for row in report["links"]:
        assert row["catalog_status"] == status.value
        assert row["catalog_scope"] == "unknown"
        assert row["source_catalog_raw_sha256"] == "a" * 64
        digest_field = (
            "source_adapter_normalized_sha256"
            if row["manifest_section"] == "consumer_adapters"
            else "source_information_normalized_sha256"
        )
        assert row[digest_field] == "b" * 64
    assert report["status_promotion"] == "none"


def test_duplicate_catalog_ids_are_rejected_even_after_catalog_creation(inputs):
    catalog, metadata = inputs
    object.__setattr__(catalog, "items", (catalog.items[0], catalog.items[0]))
    with pytest.raises(ValueError, match="ID 重复"):
        candidate_coverage.build(catalog, metadata)


def test_ambiguous_catalog_path_is_unresolved(inputs):
    catalog, metadata = inputs
    changed = replace(catalog, items=(catalog.items[0], replace(catalog.items[0], id="other")))
    report = candidate_coverage.build(changed, metadata)
    assert report["links"] == []
    assert {row["reason"] for row in report["unresolved"]} == {"ambiguous_catalog_path"}


def test_disabled_rules_are_not_counted_as_candidate_intervention(inputs):
    catalog, metadata = inputs
    metadata["decision_rules"]["enabled_domains"] = []
    metadata["decision_rules"]["active_rule_count"] = 0
    report = candidate_coverage.build(catalog, metadata)
    assert len(report["links"]) == 1
    assert report["links"][0]["manifest_section"] == "consumer_adapters"


def test_non_rule_writer_does_not_inherit_a_reader_contract_and_retained_fields_are_listed(inputs):
    catalog, metadata = inputs
    metadata["consumer_adapters"]["field_owners"].append(
        {
            "source": SOURCE,
            "field": "ai_strategy_default.goods_stances.coal",
            "owner": "supply_plan",
        }
    )
    report = candidate_coverage.build(catalog, metadata)
    assert report["unresolved"][0]["reason"] == "manifest_writer_without_rule_reader_contract"
    assert "readers" not in report["unresolved"][0]
    assert [row["field"] for row in report["retained_vanilla_fields"]] == ["negotiation_chance"]


def test_supply_writer_connects_its_own_explicit_market_contract(inputs):
    catalog, metadata = inputs
    catalog = replace(catalog, items=(*catalog.items, _item("ai_strategy_default.goods_stances")))
    adapters = metadata["consumer_adapters"]
    adapters["supply_plan"] = {
        "source": SOURCE,
        "field": "ai_strategy_default.goods_stances",
        "goods": ["coal"],
        "price_threshold": 0.25,
        "stance": "wants_high_supply",
        "conditions": [
            "is_ai",
            "existing_market_goods",
            "price_above_threshold",
            "negative_market_goods_delta",
        ],
    }
    adapters["field_owners"].append(
        {
            "source": SOURCE,
            "field": "ai_strategy_default.goods_stances.coal",
            "owner": "supply_plan",
        }
    )
    report = candidate_coverage.build(catalog, metadata)
    row = next(row for row in report["links"] if row["rule_id"] == "supply:coal")
    assert row["match"] == "catalog_ancestor_only"
    assert row["unmatched_suffix"] == ["coal"]
    assert row["readers"][0]["scope"] == "root.market.mg:coal"
    assert row["readers"][1]["threshold"] == 0
    assert report["unresolved"] == []
    adapters["supply_plan"]["conditions"] = []
    with pytest.raises(ValueError, match="供给合同"):
        candidate_coverage.build(catalog, metadata)


@pytest.mark.parametrize(
    "field",
    [
        "version",
        "supported_game_version",
        "decision_rules",
        "consumer_adapters",
        "vanilla_field_coverage",
    ],
)
def test_missing_manifest_sections_are_rejected(inputs, field):
    catalog, metadata = inputs
    del metadata[field]
    with pytest.raises(ValueError):
        candidate_coverage.build(catalog, metadata)


@pytest.mark.parametrize(
    "change",
    [
        "schema",
        "reader",
        "duplicate_reader",
        "duplicate_rule",
        "active_count",
        "digest",
        "consumer",
    ],
)
def test_malformed_contract_is_rejected(inputs, change):
    catalog, metadata = inputs
    contract = metadata["decision_rules"]
    if change == "schema":
        contract["schema"] = True
    elif change == "reader":
        contract["rules"][0]["inputs"] = ["invented"]
    elif change == "duplicate_reader":
        contract["readers"].append(contract["readers"][0])
    elif change == "duplicate_rule":
        contract["rules"].append(contract["rules"][0])
    elif change == "active_count":
        contract["active_rule_count"] = 5
    elif change == "digest":
        contract["baseline_sha256"] = "invalid"
    else:
        contract["rules"][0]["consumer"] = {}
    with pytest.raises(ValueError):
        candidate_coverage.build(catalog, metadata)


@pytest.mark.parametrize("version", [{}, {"caligula_branch": "release/1.14.4"}])
def test_missing_or_mismatched_game_version_is_rejected(inputs, version):
    catalog, metadata = inputs
    with pytest.raises(ValueError, match="版本"):
        candidate_coverage.build(replace(catalog, version=version), metadata)


@pytest.mark.parametrize(
    "change", ["source_digest", "source_missing", "duplicate_writer", "duplicate_retained"]
)
def test_bad_adapter_or_coverage_metadata_cannot_be_silently_skipped(inputs, change):
    catalog, metadata = inputs
    if change == "source_digest":
        metadata["consumer_adapters"]["sources"][SOURCE] = "c" * 64
    elif change == "source_missing":
        metadata["consumer_adapters"]["sources"] = {}
    elif change == "duplicate_writer":
        rows = metadata["consumer_adapters"]["field_owners"]
        rows.append(rows[0])
    else:
        metadata["vanilla_field_coverage"].append(metadata["vanilla_field_coverage"][0])
    with pytest.raises(ValueError):
        candidate_coverage.build(catalog, metadata)


@pytest.mark.parametrize("change", ["modules", "source", "generator"])
def test_candidate_identity_and_contract_fingerprints_are_bound(inputs, change):
    catalog, metadata = inputs
    if change == "modules":
        metadata["enabled_modules"] = ["fiscal"]
    else:
        metadata["source_fingerprint"]["information_rules_" + change + "_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        candidate_coverage.build(catalog, metadata)


def test_candidate_rejects_the_previous_release_identity(inputs):
    catalog, metadata = inputs
    metadata["id"] = "sitai.decisions"
    with pytest.raises(ValueError, match="正确的候选身份"):
        candidate_coverage.build(catalog, metadata)


@pytest.fixture
def strategic_inputs(inputs):
    catalog, metadata = inputs
    base = {
        "id": "capacity",
        "requires": [],
        "signals": ["solvent"],
        "conditions": [{"fact": "debt", "op": ">=", "value": 0}],
    }
    development = {
        "id": "development",
        "requires": ["capacity"],
        "signals": ["affordable"],
        "conditions": [*base["conditions"], {"fact": "debt", "op": "<=", "value": 0.4}],
    }
    strategy = {
        "source_sha256": "e" * 64,
        "generator_sha256": "f" * 64,
        "composition": "generation_time_and_dag; nonexclusive_current_input_constraints",
        "priority": "existing_per_field_rule_priority; one_adjustment",
        "graph_budget": {"signals": 32, "intents": 32, "depth": 8},
        "intents": [base, development],
    }
    metadata["strategic_coordination"] = {
        **copy.deepcopy(strategy),
        "rules_with_intent": 2,
        "runtime_state": "none",
        "behavior_verified": False,
    }
    metadata["source_fingerprint"].update(
        strategic_source_sha256="e" * 64, strategic_generator_sha256="f" * 64
    )
    info = metadata["decision_rules"]
    adapter = metadata["consumer_adapters"]["consumers"][0]
    for contract, intent in ((info, development), (adapter, base)):
        contract["strategy"] = copy.deepcopy(strategy)
        if contract is adapter:
            contract["strategy"]["intents"] = [copy.deepcopy(base)]
        contract["rules"][0].update(
            intent=intent["id"], conditions=copy.deepcopy(intent["conditions"])
        )
    return catalog, metadata


def test_strategy_fingerprint_chain_and_optional_adapter_aggregate_are_consistent(
    strategic_inputs,
):
    catalog, metadata = strategic_inputs
    assert len(candidate_coverage.build(catalog, metadata)["links"]) == 2
    metadata["consumer_adapters"]["strategy"] = copy.deepcopy(
        metadata["consumer_adapters"]["consumers"][0]["strategy"]
    )
    assert len(candidate_coverage.build(catalog, metadata)["links"]) == 2


@pytest.mark.parametrize(
    "change",
    [
        "missing_top",
        "null_top",
        "empty_top",
        "missing_source",
        "missing_generator",
        "bad_source",
        "bad_generator",
        "top_source",
        "top_generator",
        "nested_source",
        "nested_generator",
        "missing_nested",
        "null_nested",
        "adapter_source",
        "adapter_generator",
        "missing_adapter_nested",
        "aggregate_source",
        "aggregate_generator",
        "empty_nested",
        "malformed_nested",
    ],
)
def test_strategy_fingerprints_and_required_contracts_cannot_drift(strategic_inputs, change):
    catalog, metadata = strategic_inputs
    top = metadata["strategic_coordination"]
    info = metadata["decision_rules"]
    adapter = metadata["consumer_adapters"]["consumers"][0]
    fingerprint = metadata["source_fingerprint"]
    if change == "missing_top":
        del metadata["strategic_coordination"]
    elif change in {"null_top", "empty_top"}:
        metadata["strategic_coordination"] = None if change == "null_top" else {}
    elif change in {"missing_source", "missing_generator"}:
        del fingerprint[f"strategic_{change.removeprefix('missing_')}_sha256"]
    elif change in {"bad_source", "bad_generator"}:
        fingerprint[f"strategic_{change.removeprefix('bad_')}_sha256"] = "invalid"
    elif change in {"top_source", "top_generator"}:
        top[change.removeprefix("top_") + "_sha256"] = "0" * 64
    elif change in {"nested_source", "nested_generator"}:
        info["strategy"][change.removeprefix("nested_") + "_sha256"] = "0" * 64
    elif change == "missing_nested":
        del info["strategy"]
    elif change in {"null_nested", "empty_nested", "malformed_nested"}:
        info["strategy"] = {"null_nested": None, "empty_nested": {}, "malformed_nested": []}[change]
    elif change in {"adapter_source", "adapter_generator"}:
        adapter["strategy"][change.removeprefix("adapter_") + "_sha256"] = "0" * 64
    elif change == "missing_adapter_nested":
        del adapter["strategy"]
    else:
        metadata["consumer_adapters"]["strategy"] = {
            **adapter["strategy"],
            change.removeprefix("aggregate_") + "_sha256": "0" * 64,
        }
    with pytest.raises(ValueError):
        candidate_coverage.build(catalog, metadata)


@pytest.mark.parametrize("trace", ["source", "generator", "info", "adapter", "aggregate", "intent"])
def test_partial_strategy_metadata_cannot_fall_back_to_legacy_protocol(inputs, trace):
    catalog, metadata = inputs
    if trace in {"source", "generator"}:
        metadata["source_fingerprint"][f"strategic_{trace}_sha256"] = "e" * 64
    elif trace == "intent":
        metadata["decision_rules"]["rules"][0]["intent"] = "capacity"
    else:
        contract = {
            "info": metadata["decision_rules"],
            "adapter": metadata["consumer_adapters"]["consumers"][0],
            "aggregate": metadata["consumer_adapters"],
        }[trace]
        contract["strategy"] = {"source_sha256": "e" * 64, "generator_sha256": "f" * 64}
    with pytest.raises(ValueError):
        candidate_coverage.build(catalog, metadata)


def test_disabled_strategy_contracts_accept_matching_fingerprints_with_inactive_definitions(
    strategic_inputs,
):
    catalog, metadata = strategic_inputs
    metadata["decision_rules"].update(enabled_domains=[], active_rule_count=0)
    metadata["strategic_coordination"]["rules_with_intent"] = 1
    metadata["strategic_coordination"]["intents"].pop()
    assert len(candidate_coverage.build(catalog, metadata)["links"]) == 1


def test_legacy_null_strategy_contracts_remain_compatible(inputs):
    catalog, metadata = inputs
    metadata["decision_rules"]["strategy"] = None
    metadata["decision_rules"]["rules"][0]["intent"] = None
    metadata["consumer_adapters"]["strategy"] = None
    metadata["consumer_adapters"]["consumers"][0]["strategy"] = None
    assert len(candidate_coverage.build(catalog, metadata)["links"]) == 2


def test_deterministic_without_game_or_filesystem_reads(inputs, monkeypatch, tmp_path):
    catalog, metadata = inputs
    monkeypatch.setattr(config, "GAME", tmp_path / "game-does-not-exist")
    first = candidate_coverage.build(catalog, metadata)
    second = candidate_coverage.build(
        replace(catalog, items=tuple(reversed(catalog.items))), metadata
    )
    assert first == second
    assert not config.GAME.exists()


def test_cli_connects_actual_metadata_to_the_same_catalog(inputs, monkeypatch, tmp_path):
    catalog, metadata = inputs
    calls = []

    def build(**kwargs):
        calls.append(kwargs)
        return catalog

    monkeypatch.setattr(cli, "_require_game", lambda: None)
    monkeypatch.setattr(cli.information_catalog, "build", build)
    source = tmp_path / "metadata.json"
    source.write_text(json.dumps(metadata), encoding="utf-8", newline="\n")
    output = tmp_path / "catalog.json"
    matrix = tmp_path / "matrix.json"
    result = CliRunner().invoke(
        cli.app,
        [
            "information-catalog",
            "--no-localization",
            "--output",
            str(output),
            "--consumer-matrix-output",
            str(matrix),
            "--candidate-metadata",
            str(source),
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls == [{"include_localization": False}]
    report = json.loads((tmp_path / "candidate-coverage.json").read_text(encoding="utf-8"))
    assert report == candidate_coverage.build(catalog, metadata)
    assert output.is_file()
    assert matrix.is_file()


@pytest.mark.parametrize("case", ["output_only", "missing", "invalid_json", "wrong_identity"])
def test_cli_rejects_invalid_candidate_instead_of_claiming_coverage(
    inputs, monkeypatch, tmp_path, case
):
    catalog, _metadata = inputs
    monkeypatch.setattr(cli, "_require_game", lambda: None)
    monkeypatch.setattr(cli.information_catalog, "build", lambda **_kwargs: catalog)
    source = tmp_path / "metadata.json"
    if case == "invalid_json":
        source.write_text("{", encoding="utf-8", newline="\n")
    elif case == "wrong_identity":
        source.write_text("{}", encoding="utf-8", newline="\n")
    coverage = tmp_path / "coverage.json"
    args = [
        "information-catalog",
        "--no-localization",
        "--output",
        str(tmp_path / "catalog.json"),
        "--consumer-matrix-output",
        str(tmp_path / "matrix.json"),
        "--candidate-coverage-output",
        str(coverage),
    ]
    if case != "output_only":
        args += ["--candidate-metadata", str(source)]
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 2, result.output
    assert not coverage.exists()


@pytest.mark.parametrize("change", ["identity", "strategic_fingerprint"])
def test_cli_failed_validation_preserves_previous_reports_without_claiming_a_new_run(
    strategic_inputs, monkeypatch, tmp_path, change
):
    catalog, metadata = strategic_inputs
    if change == "identity":
        metadata["id"] = "wrong"
    else:
        metadata["source_fingerprint"]["strategic_source_sha256"] = "0" * 64
    monkeypatch.setattr(cli, "_require_game", lambda: None)
    monkeypatch.setattr(cli.information_catalog, "build", lambda **_kwargs: catalog)
    source = tmp_path / "metadata.json"
    source.write_text(json.dumps(metadata), encoding="utf-8", newline="\n")
    output = tmp_path / "catalog.json"
    coverage = tmp_path / "coverage.json"
    for path in (output, coverage):
        path.write_bytes(b"previous evidence\n")
    result = CliRunner().invoke(
        cli.app,
        [
            "information-catalog",
            "--no-localization",
            "--output",
            str(output),
            "--candidate-metadata",
            str(source),
            "--candidate-coverage-output",
            str(coverage),
        ],
    )
    assert result.exit_code == 2
    assert "已有文件仅属于先前运行" in "".join(result.output.split())
    assert output.read_bytes() == b"previous evidence\n"
    assert coverage.read_bytes() == b"previous evidence\n"


@pytest.mark.parametrize("collision", ["catalog", "matrix", "metadata", "localization"])
def test_cli_rejects_output_aliases_before_touching_inputs_or_outputs(tmp_path, collision):
    metadata = tmp_path / "metadata.json"
    metadata.write_bytes(b"original candidate\n")
    catalog, matrix = tmp_path / "catalog.json", tmp_path / "matrix.json"
    coverage = {
        "catalog": catalog,
        "matrix": matrix,
        "metadata": metadata,
        "localization": tmp_path / "keys.jsonl",
    }[collision]
    result = CliRunner().invoke(
        cli.app,
        [
            "information-catalog",
            "--output",
            str(catalog),
            "--consumer-matrix-output",
            str(matrix),
            "--candidate-metadata",
            str(metadata),
            "--candidate-coverage-output",
            str(coverage),
            "--localization-keys-output",
            str(tmp_path / "keys.jsonl"),
        ],
    )
    assert result.exit_code == 2
    assert "互不相同" in result.output
    assert metadata.read_bytes() == b"original candidate\n"
    assert not catalog.exists()
    assert not matrix.exists()
