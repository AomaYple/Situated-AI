"""Generated country parameters close only against exact native/lifecycle contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from pdx import country_interfaces, country_state, version_contracts
from pdx.situated.native_treatments import native_treatments
from pdx.situated.vanilla_inventory import VanillaInventory, VanillaSurface

pytestmark = pytest.mark.unit


def test_native_parameter_evidence_extends_hashes_without_discovering_consumers(
    tmp_path, monkeypatch
):
    from pdx.situated import vanilla_inventory

    name = "common/goods/fixture.txt"
    raw = b"tools={market_goods_pricier=yes}"
    path = tmp_path / name
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    expected = {name: hashlib.sha256(raw).hexdigest()}
    monkeypatch.setattr(vanilla_inventory, "_parameter_evidence_contract", lambda: expected)
    assert vanilla_inventory.parameter_evidence_hashes(tmp_path) == expected


@pytest.mark.parametrize("fault", ["missing", "drift"])
def test_native_parameter_evidence_never_licenses_missing_or_drifted_bytes(
    tmp_path, monkeypatch, fault
):
    from pdx.situated import vanilla_inventory

    name = "common/goods/fixture.txt"
    raw = b"tools={}"
    monkeypatch.setattr(
        vanilla_inventory,
        "_parameter_evidence_contract",
        lambda: {name: hashlib.sha256(raw).hexdigest()},
    )
    if fault == "missing":
        assert vanilla_inventory.parameter_evidence_hashes(tmp_path) == {}
    else:
        path = tmp_path / name
        path.parent.mkdir(parents=True)
        path.write_bytes(raw + b"\n# drift")
        with pytest.raises(ValueError, match="参数原版证据漂移"):
            vanilla_inventory.parameter_evidence_hashes(tmp_path)


@pytest.fixture
def parameter_case(tmp_path, monkeypatch):
    policy = country_state.load()
    source = "common/ai_strategies/fixture.txt"
    evidence_source = "common/on_actions/00_code_on_actions.txt"
    parameters = "common/ai_strategies/native_parameters.txt"
    technology = "common/technology/technologies/fixture.txt"
    observations = (
        "native_interface_sample={"
        + " ".join(f"{reader['engine']}=yes" for reader in policy.readers.values())
        + "}"
    )
    memory = (
        "on_capitulation={effect={set_variable={name=recently_lost_war days=1825 value=yes}}}\n"
        "on_lost_war={effect={if={limit={exists=scope:victim_of_wargoal} "
        "set_variable={name=recently_lost_war days=1825 value=yes}}}}\n"
    )
    sources = {
        source: b"candidate={weight={value=10}}",
        evidence_source: (memory + observations).encode(),
        parameters: (
            b"ai_strategy_industrial_expansion={} ai_strategy_resource_expansion={} "
            b"ai_strategy_territorial_expansion={}"
        ),
        technology: b"artillery={}",
    }
    interfaces: dict[str, dict[str, str | int]] = {}
    arguments = []
    for name, raw in sources.items():
        words, args = country_interfaces._observations(raw, name)
        for reader in policy.readers.values():
            if reader["engine"] in words:
                interfaces.setdefault(
                    reader["engine"], {"source": name, "line": words[reader["engine"]]}
                )
        for (engine, argument), line in args.items():
            arguments.append({"engine": engine, "argument": argument, "source": name, "line": line})
    evidence = {
        "schema": 1,
        "sources": {name: hashlib.sha256(raw).hexdigest() for name, raw in sources.items()},
        "interfaces": interfaces,
        "arguments": arguments,
    }
    if version_contracts.active_version() == "1.15.0":
        evidence["baseline_version"] = "1.15.0"
    evidence_path = tmp_path / "country-interfaces.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    monkeypatch.setattr(country_interfaces, "evidence_file", lambda: evidence_path)
    monkeypatch.setattr(
        country_interfaces,
        "EVIDENCE_115_SHA256",
        hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
    )
    generated = {name: text.encode() for name, text in country_state.files(policy).items()}
    generated[source] = (
        b"candidate={weight={value=10 if={limit={ROOT={sitai_context_need_industry=yes}} add=2}}}"
    )
    generated[".metadata/metadata.json"] = json.dumps(
        {
            "country_state": country_state.contract(policy),
            "source_fingerprint": {
                "country_state_source_sha256": policy.source_sha256,
                "country_state_generator_sha256": hashlib.sha256(
                    Path(country_state.__file__).read_bytes()
                ).hexdigest(),
            },
            "enabled_modules": ["country_state"],
        }
    ).encode()
    surface = VanillaSurface(
        surface_id="parameter_consumer",
        source=source,
        definition="candidate",
        field="weight",
        actor_scope="country",
        target_scope="none",
        operation="score",
        capability="direct",
        status="pending",
        getter=None,
        getter_note="fixture",
        scope_evidence=(f"{source}:1",),
        responsibility_step="D0",
        source_line=1,
    )
    inventory = VanillaInventory(
        baseline_id="fixture",
        source_hashes={name: hashlib.sha256(raw).hexdigest() for name, raw in sources.items()},
        scope_hash="c" * 64,
        surfaces=(surface,),
        scanned_directories=("ai_strategies",),
        content_roots=("game",),
        parsed_files=len(sources),
    )
    return inventory, sources, generated, evidence_path


def _report(case, *, complete=True):
    inventory, sources, generated, _path = case
    coverage = {
        "baseline_id": inventory.baseline_id,
        "scope_hash": inventory.scope_hash,
        "source_hashes": inventory.source_hashes,
        "denominator": 1,
        "rows": [
            {
                **asdict(inventory.surfaces[0]),
                "coverage_status": "actual_covered",
                "covered_actions": ["actual_writer"],
                "matched_actions": ["actual_writer"],
                "legal": True,
                "unknown_scope": False,
                "binding_issues": {},
            }
        ],
    }
    coverage["rows"][0]["declaration_id"] = inventory.surfaces[0].declaration_id
    return native_treatments(
        inventory, sources, generated, coverage=coverage, production_complete=complete
    )["rows"][0]


@pytest.mark.parametrize(
    "helper",
    [
        "sitai_context_need_industry",
        "sitai_context_need_overseas",
    ],
)
def test_exact_stateless_parameter_helpers_bind_native_arguments(parameter_case, helper):
    inventory, _sources, generated, _path = parameter_case
    source = inventory.surfaces[0].source
    generated[source] = generated[source].replace(b"sitai_context_need_industry", helper.encode())
    row = _report(parameter_case)
    assert row["status"] == "implemented_numeric"
    assert row["interface"]["control_authorized"]
    assert not row["business_complete"]
    proof = next(p for p in row["dependencies"] if p["definition"] == helper)
    assert proof["status"] == "proven_generated"
    assert proof["parameter_contract"]["native_sources"]


@pytest.fixture
def current_parameter_case(monkeypatch, request):
    monkeypatch.setenv("V3_CONTRACT_PROFILE", "1.15.0")
    return request.getfixturevalue("parameter_case")


def test_current_country_parameters_select_current_authority(
    current_parameter_case, monkeypatch, tmp_path
):
    monkeypatch.setattr(country_interfaces, "EVIDENCE", tmp_path / "unavailable-historical.json")
    row = _report(current_parameter_case)
    assert row["status"] == "implemented_numeric"
    assert row["interface"]["control_authorized"]
    proof = next(
        proof
        for proof in row["dependencies"]
        if proof["definition"] == "sitai_context_need_industry"
    )
    assert proof["status"] == "proven_generated"
    assert proof["parameter_contract"]["native_sources"]


@pytest.mark.parametrize("fault", ["digest", "version", "missing_version"])
def test_current_country_parameters_reject_authority_drift(
    current_parameter_case, monkeypatch, fault
):
    _inventory, _sources, _generated, path = current_parameter_case
    if fault == "digest":
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        evidence = json.loads(path.read_bytes())
        if fault == "version":
            evidence["baseline_version"] = "1.14.5"
        else:
            evidence.pop("baseline_version")
        path.write_text(json.dumps(evidence), encoding="utf-8")
        monkeypatch.setattr(
            country_interfaces, "EVIDENCE_115_SHA256", hashlib.sha256(path.read_bytes()).hexdigest()
        )
    row = _report(current_parameter_case)
    assert not row["interface"]["control_authorized"]
    assert row["active_unknown_usage"]
    proof = next(
        proof
        for proof in row["dependencies"]
        if proof["definition"] == "sitai_context_need_industry"
    )
    assert proof["status"] == "unproven"
    assert "authoritative_country_program_unproven" in proof["issues"]


@pytest.mark.parametrize("helper", ["sitai_route_industry", "sitai_context_invented"])
def test_unregistered_country_helpers_cannot_gain_parameter_authority(parameter_case, helper):
    inventory, _sources, generated, _path = parameter_case
    source = inventory.surfaces[0].source
    generated[source] = generated[source].replace(b"sitai_context_need_industry", helper.encode())
    trigger = "common/scripted_triggers/sitai_country_triggers.txt"
    generated[trigger] += f"\n{helper}={{is_ai=yes}}\n".encode()
    row = _report(parameter_case)
    assert not row["interface"]["control_authorized"]
    assert row["active_unknown_usage"]


@pytest.mark.parametrize("fault", ["schema", "persistent_variables"])
def test_stateless_parameter_metadata_rejects_retired_state_contract(parameter_case, fault):
    _inventory, _sources, generated, _path = parameter_case
    metadata = json.loads(generated[".metadata/metadata.json"])
    metadata["country_state"][fault] = 1 if fault == "schema" else ["sitai_route_industry"]
    generated[".metadata/metadata.json"] = json.dumps(metadata).encode()
    row = _report(parameter_case)
    assert not row["interface"]["control_authorized"]
    assert row["active_unknown_usage"]


@pytest.mark.parametrize(
    "fault",
    [
        "wrong_argument",
        "wrong_scope",
        "new_helper_field",
        "missing_native",
        "duplicate_strategy",
        "missing_metadata",
        "wrong_metadata",
        "unknown_local",
        "incomplete",
    ],
)
def test_parameter_helper_proof_rejects_broken_identity_scope_or_lifecycle(parameter_case, fault):
    inventory, sources, generated, _path = parameter_case
    source = inventory.surfaces[0].source
    trigger = "common/scripted_triggers/sitai_country_triggers.txt"
    if fault == "wrong_argument":
        generated[trigger] = generated[trigger].replace(
            b"has_strategy = ai_strategy_industrial_expansion", b"has_strategy = invented_strategy"
        )
    elif fault == "wrong_scope":
        generated[source] = generated[source].replace(b"ROOT={", b"scope:target_country={")
    elif fault == "new_helper_field":
        generated[trigger] = generated[trigger].replace(
            b"sitai_context_need_industry = {",
            b"sitai_context_need_industry = { new_permission=yes",
        )
    elif fault == "missing_native":
        sources.pop("common/on_actions/00_code_on_actions.txt")
    elif fault == "duplicate_strategy":
        generated["common/ai_strategies/duplicate.txt"] = b"ai_strategy_industrial_expansion={}"
    elif fault == "missing_metadata":
        generated.pop(".metadata/metadata.json")
    elif fault == "wrong_metadata":
        metadata = json.loads(generated[".metadata/metadata.json"])
        metadata["country_state"]["source_sha256"] = "a" * 64
        generated[".metadata/metadata.json"] = json.dumps(metadata).encode()
    elif fault == "unknown_local":
        generated[trigger] = generated[trigger].replace(
            b"has_variable = recently_lost_war", b"has_variable = invented_local"
        )
    row = _report(parameter_case, complete=fault != "incomplete")
    assert not row["interface"]["control_authorized"]
    assert row["active_unknown_usage"]


@pytest.mark.parametrize(
    "fault", ["wrong_days", "wrong_guard", "duplicate_write", "wrong_native_sha"]
)
def test_memory_parameter_requires_original_exact_1825_day_writes(
    parameter_case, monkeypatch, fault
):
    inventory, sources, generated, evidence_path = parameter_case
    memory = "common/on_actions/00_code_on_actions.txt"
    if fault == "wrong_days":
        sources[memory] = sources[memory].replace(b"days=1825", b"days=100", 1)
    elif fault == "wrong_guard":
        sources[memory] = sources[memory].replace(b"exists=scope:victim_of_wargoal", b"always=yes")
    elif fault == "duplicate_write":
        sources[memory] += (
            b"on_won_war={effect={set_variable={name=recently_lost_war days=1825 value=yes}}}"
        )
    else:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["sources"][memory] = "f" * 64
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    if fault != "wrong_native_sha":
        parameter_case = (
            replace(
                inventory,
                source_hashes={
                    name: hashlib.sha256(raw).hexdigest() for name, raw in sources.items()
                },
            ),
            sources,
            generated,
            evidence_path,
        )
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["sources"][memory] = hashlib.sha256(sources[memory]).hexdigest()
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    monkeypatch.setattr(
        country_interfaces,
        "EVIDENCE_115_SHA256",
        hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
    )
    row = _report(parameter_case)
    assert not row["interface"]["control_authorized"]


def test_country_helper_at_building_owner_uses_the_exact_state_to_country_path(
    parameter_case, monkeypatch
):
    inventory, sources, generated, path = parameter_case
    old = inventory.surfaces[0].source
    source = "common/buildings/fixture.txt"
    sources[source] = sources.pop(old).replace(b"weight=", b"ai_value=")
    generated[source] = (
        generated.pop(old)
        .replace(b"weight=", b"ai_value=")
        .replace(
            b"ROOT={sitai_context_need_industry=yes}",
            b"ROOT={exists=owner owner={sitai_context_need_industry=yes}}",
        )
    )
    evidence = json.loads(path.read_text(encoding="utf-8"))
    evidence["sources"].pop(old)
    evidence["sources"][source] = hashlib.sha256(sources[source]).hexdigest()
    path.write_text(json.dumps(evidence), encoding="utf-8")
    monkeypatch.setattr(
        country_interfaces, "EVIDENCE_115_SHA256", hashlib.sha256(path.read_bytes()).hexdigest()
    )
    surface = replace(inventory.surfaces[0], source=source, field="ai_value", actor_scope="state")
    inventory = replace(
        inventory,
        surfaces=(surface,),
        source_hashes={name: hashlib.sha256(raw).hexdigest() for name, raw in sources.items()},
    )
    row = _report((inventory, sources, generated, path))
    assert row["status"] == "implemented_numeric"
    assert row["interface"]["control_authorized"]
    generated[source] = generated[source].replace(b"exists=owner owner={", b"exists=owner market={")
    assert not _report((inventory, sources, generated, path))["interface"]["control_authorized"]


def test_new_memory_writer_cannot_override_the_proven_native_ttl(parameter_case):
    _inventory, _sources, generated, _path = parameter_case
    generated["events/rogue_memory.txt"] = (
        b"rogue_event={immediate={set_variable={name=recently_lost_war value=yes days=999}}}"
    )
    assert not _report(parameter_case)["interface"]["control_authorized"]


@pytest.fixture
def support_case():
    from pdx import config, decision_security, decisions
    from pdx.model import Block
    from pdx.parser import parse_bytes
    from pdx.situated import compiler, support_program
    from pdx.situated.decision_ir import (
        ConsumerIRBundle,
        WriterDecisionIR,
    )
    from pdx.situated.support_program import SupportProgram

    source = "common/ai_strategies/00_default_strategy.txt"
    sources = {
        name: (config.GAME / name).read_bytes()
        for name in (
            source,
            "common/script_values/01_power_bloc_values.txt",
            "common/scripted_triggers/00_scripted_triggers.txt",
            "common/scripted_triggers/00_spanish_new_world_triggers.txt",
        )
    }
    program = SupportProgram.from_extensions(
        replace(decisions.Extensions(), market_enabled=True, security_enabled=True)
    )
    parsed = parse_bytes(sources[source], path=source)
    definitions = parsed.root.all("ai_strategy_default")
    assert not parsed.errors
    assert len(definitions) == 1
    assert isinstance(definitions[0].value, Block)
    fields = definitions[0].value.all("diplomatic_play_support")
    assert len(fields) == 1
    assert isinstance(fields[0].value, Block)
    source_line = fields[0].line
    writer = WriterDecisionIR(
        writer_id=program.writer_id,
        kind="support_program",
        source="mod/decisions/extensions.toml",
        definition=program.writer_id,
        consumer_id="diplomatic_play_support",
        field="diplomatic_play_support",
        actor="root",
        target="target_country",
        operation="add",
        vanilla_tail="preserve",
        owner="situated_kernel",
        program=program,
        evaluation_context=compiler.support_evaluation_context(),
    )
    surface = VanillaSurface(
        surface_id="support",
        source=source,
        definition="ai_strategy_default",
        field="diplomatic_play_support",
        actor_scope="country",
        target_scope="scope:country=country;scope:enemy_country=country",
        operation="additive_score",
        capability="direct",
        status="pending",
        getter=None,
        getter_note="exact native consumer",
        scope_evidence=(f"{source}:{source_line}",),
        responsibility_step="S3",
        source_line=source_line,
    )
    inventory = VanillaInventory(
        "support-fixture",
        {name: hashlib.sha256(raw).hexdigest() for name, raw in sources.items()},
        "support-scope",
        (surface,),
        ("ai_strategies", "script_values", "scripted_triggers"),
        ("game",),
        len(sources),
    )
    metadata = {
        "situated_actions": {"consumer_ir": ConsumerIRBundle(1, (), (writer,)).as_dict()},
        "default_field_owners": {"diplomatic_play_support": "situated_kernel"},
        "source_fingerprint": {
            "security_generator_sha256": hashlib.sha256(
                Path(decision_security.__file__).read_bytes()
            ).hexdigest(),
            "support_program_generator_sha256": hashlib.sha256(
                Path(support_program.__file__).read_bytes()
            ).hexdigest(),
        },
    }
    generated = {
        source: decisions.patch_default(
            decisions.baseline_path().read_text(encoding="utf-8"),
            replace(decisions.load(), enabled=False),
            replace(decisions.Extensions(), market_enabled=True, security_enabled=True),
        ).encode(),
        "common/scripted_triggers/sitai_security_triggers.txt": decision_security.triggers().encode(),
        ".metadata/metadata.json": json.dumps(metadata).encode(),
    }
    return inventory, sources, generated, None


@pytest.mark.integration
def test_exact_support_program_closes_new_getters_and_parameterized_helpers(support_case):
    row = _report(support_case)
    assert row["status"] == "implemented_numeric", row["issues"]
    assert row["interface"]["control_authorized"]
    assert not row["active_unknown_usage"]
    assert not row["business_complete"]


@pytest.mark.integration
@pytest.mark.parametrize(
    "fault",
    ["getter", "parameter", "helper", "duplicate_helper", "metadata", "native_getter", "tail"],
)
def test_support_program_proof_rejects_unregistered_queries_or_output(support_case, fault):
    inventory, sources, generated, _ = support_case
    source = inventory.surfaces[0].source
    helper = "common/scripted_triggers/sitai_security_triggers.txt"
    if fault == "getter":
        generated[source] = generated[source].replace(
            b"ROOT.economic_dependence(scope:country)", b"ROOT.economic_dependence(scope:invented)"
        )
    elif fault == "parameter":
        generated[source] = generated[source].replace(b"PARTNER = scope:country", b"PARTNER = ROOT")
    elif fault == "helper":
        generated[helper] = generated[helper].replace(b"binds = $PARTNER$", b"binds = ROOT")
    elif fault == "duplicate_helper":
        generated["common/scripted_triggers/duplicate.txt"] = (
            b"sitai_defense_commitment={always=yes}"
        )
    elif fault == "metadata":
        metadata = json.loads(generated[".metadata/metadata.json"])
        metadata["source_fingerprint"]["support_program_generator_sha256"] = "a" * 64
        generated[".metadata/metadata.json"] = json.dumps(metadata).encode()
    elif fault == "native_getter":
        getter = "common/script_values/01_power_bloc_values.txt"
        sources[getter] += b"\n# drift\n"
        inventory = replace(
            inventory,
            source_hashes={name: hashlib.sha256(raw).hexdigest() for name, raw in sources.items()},
        )
        support_case = inventory, sources, generated, None
    else:
        generated[source] = generated[source].replace(b"value = 0", b"value = 1", 1)
    row = _report(support_case)
    assert not row["interface"]["control_authorized"]
    assert row["active_unknown_usage"]


@pytest.mark.parametrize("metadata", [True, False])
def test_authoritative_parameter_helper_cannot_fall_back_to_a_simpler_body(
    parameter_case, metadata
):
    _inventory, _sources, generated, _path = parameter_case
    trigger = "common/scripted_triggers/sitai_country_triggers.txt"
    generated[trigger] = b"sitai_context_need_industry={is_ai=yes}"
    if not metadata:
        generated.pop(".metadata/metadata.json")
    assert not _report(parameter_case)["interface"]["control_authorized"]


@pytest.fixture(params=["query", "production", "resource"])
def reader_case(request, tmp_path, monkeypatch):
    return _reader_case(request.param, tmp_path, monkeypatch)


def _reader_case(kind, tmp_path, monkeypatch):
    from pdx import (
        decision_adapters,
        decision_rules,
        observation_queries,
        production_inputs,
        version_contracts,
    )
    from pdx.textio import normalized_text

    production = kind in {"production", "resource"}
    resource = kind == "resource"
    source = "common/buildings/fixture.txt" if production else "common/ai_strategies/fixture.txt"
    field = "ai_value" if production else "weight"
    raw = f"candidate={{{field}={{value=10}}}}".encode()
    sources = {source: raw}
    if resource:
        sources["common/goods/parameters.txt"] = b"tools={}"
        reader = decision_rules.Reader(
            "price",
            "market_goods_pricier",
            "root",
            "price_above_base_ratio",
            "number",
            path=("owner", "market", "mg:tools"),
        )
    elif production:
        sources["common/buildings/parameters.txt"] = (
            b"building_tools={production_method_groups={pmg_tools}}"
        )
        sources["common/production_method_groups/parameters.txt"] = (
            b"pmg_tools={production_methods={pm_tools}}"
        )
        sources["common/production_methods/parameters.txt"] = b"pm_tools={}"
        reader = decision_rules.Reader(
            "active",
            "is_production_method_active",
            "root",
            "boolean",
            "boolean",
            parameters=(("building_type", "building_tools"), ("production_method", "pm_tools")),
        )
    else:
        native_query = "common/journal_entries/06_portugal_politics.txt"
        completion = "NOT={any_scope_state={market_access<1}}"
        body = (
            "outcome={header=je_standard_completion_header "
            "effect_header=je_standard_on_completion_header trigger={" + completion + "}}"
            if version_contracts.active_version() == "1.15.0"
            else "complete={" + completion + "}"
        )
        sources[native_query] = ("je_portugal_regeneration_public_works={" + body + "}").encode()
        monkeypatch.setitem(
            observation_queries.source_hashes(),
            native_query,
            hashlib.sha256(sources[native_query]).hexdigest(),
        )
        reader = decision_rules.Reader(
            "access",
            "any_scope_state",
            "root",
            "boolean",
            "boolean",
            parameters=(("threshold", "1.0"),),
        )
    rule = decision_rules.Rule(
        "fixture_rule",
        "fixture",
        ("candidate", field),
        1,
        2,
        (
            decision_rules.Predicate(
                reader.key, "<=" if resource else "=", 0.25 if resource else True
            ),
        ),
        "fixture",
        "fixture",
        operation="add",
    )
    policy = decision_rules.RuleSet(
        (reader,),
        (rule,),
        hashlib.sha256(raw).hexdigest(),
        "b" * 64,
        frozenset({"fixture"}),
        actor_path=("owner",) if production else (),
        native_root="state" if production else "country",
    )
    adapters = decision_adapters.AdapterSet(
        tuple(
            (name, hashlib.sha256(normalized_text(data.decode()).encode()).hexdigest())
            for name, data in sources.items()
        ),
        ((source, policy),),
        "a" * 64,
    )
    monkeypatch.setattr(decision_adapters, "load", lambda: adapters)
    statement = decision_rules._scoped_conditions(
        {
            (reader.scope, reader.path): [
                reader.expression("<=" if resource else "=", 0.25 if resource else True)
            ]
        }
    )
    generated = {
        source: f"candidate={{{field}={{value=10 if={{limit={{{statement}}} add=2}}}}}}".encode()
    }
    generated[".metadata/metadata.json"] = json.dumps(
        {
            "consumer_adapters": {
                "schema": 1,
                "source_sha256": adapters.source_sha256,
                "generator_sha256": hashlib.sha256(
                    Path(decision_adapters.__file__).read_bytes()
                ).hexdigest(),
                "sources": dict(adapters.sources),
                "production_inputs_generator_sha256": hashlib.sha256(
                    Path(production_inputs.__file__).read_bytes()
                ).hexdigest(),
                "consumers": [
                    {
                        "source": source,
                        **decision_rules.contract(policy, owner="consumer_adapters", source=source),
                    }
                ],
            }
        }
    ).encode()
    surface = VanillaSurface(
        surface_id="reader_consumer",
        source=source,
        definition="candidate",
        field=field,
        actor_scope=policy.native_root,
        target_scope="none",
        operation="score",
        capability="direct",
        status="pending",
        getter=None,
        getter_note="fixture",
        scope_evidence=(f"{source}:1",),
        responsibility_step="D0",
        source_line=1,
    )
    inventory = VanillaInventory(
        baseline_id="fixture",
        source_hashes={name: hashlib.sha256(data).hexdigest() for name, data in sources.items()},
        scope_hash="c" * 64,
        surfaces=(surface,),
        scanned_directories=("buildings" if production else "ai_strategies",),
        content_roots=("game",),
        parsed_files=len(sources),
    )
    return inventory, sources, generated, tmp_path / "unused"


def test_exact_actual_query_or_production_parameter_gets_independent_contract(reader_case):
    row = _report(reader_case)
    assert row["status"] == "implemented_numeric"
    proof = next(p for p in row["dependencies"] if p["family"] == "parameter_readers")
    assert proof["status"] == "proven_parameter_reader"
    assert proof["native_sources"]


def _joint_reader_metadata(case):
    from pdx import decision_adapters, decision_rules
    from pdx.situated import programs
    from pdx.situated.ir import from_rule

    inventory, _sources, generated, _path = case
    source = inventory.surfaces[0].source
    policy = dict(decision_adapters.load().policies)[source]
    compiled = programs.enable(
        replace(
            policy,
            semantic_ir=tuple(
                replace(from_rule(rule, source=source), origin_priority=rule.priority)
                for rule in policy.rules
            ),
        ),
        source=source,
    )
    metadata = json.loads(generated[".metadata/metadata.json"])
    metadata["consumer_adapters"]["consumers"] = [
        {
            "source": source,
            **decision_rules.contract(compiled, owner="consumer_adapters", source=source),
        }
    ]
    generated[".metadata/metadata.json"] = json.dumps(metadata).encode()


def test_joint_compiled_metadata_preserves_exact_parameter_reader_proof(reader_case):
    _joint_reader_metadata(reader_case)
    row = _report(reader_case)
    assert row["implemented_numeric"]
    assert row["interface"]["control_authorized"]
    assert not row["active_unknown_usage"]


@pytest.mark.parametrize("fault", ["value", "priority", "scope", "extra_variant"])
def test_joint_metadata_drift_cannot_license_parameter_readers(reader_case, fault):
    _joint_reader_metadata(reader_case)
    generated = reader_case[2]
    metadata = json.loads(generated[".metadata/metadata.json"])
    contract = metadata["consumer_adapters"]["consumers"][0]
    variants = contract["consumer_programs"]["programs"][0]["groups"][0]["variants"]
    if fault == "extra_variant":
        variants.append(dict(variants[0]))
    elif fault == "scope":
        contract["readers"][0]["scope"] = "target_country"
    else:
        variants[0]["value" if fault == "value" else "origin_priority"] = 900
    generated[".metadata/metadata.json"] = json.dumps(metadata).encode()
    row = _report(reader_case)
    assert not row["interface"]["control_authorized"]
    assert row["active_unknown_usage"]


@pytest.mark.parametrize(
    "fault",
    [
        "missing_native",
        "wrong_parameter",
        "wrong_scope",
        "extra_parameter",
        "missing_metadata",
        "wrong_contract",
        "duplicate_definition",
        "missing_guard",
        "wrong_input_generator",
        "incomplete",
    ],
)
def test_new_parameter_requires_exact_consumer_source_scope_and_argument(reader_case, fault):
    inventory, sources, generated, _path = reader_case
    source = inventory.surfaces[0].source
    production = inventory.surfaces[0].actor_scope == "state"
    resource = b"mg:tools" in generated[source]
    if fault == "missing_native":
        sources.pop(next(name for name in sources if name != source))
    elif fault == "wrong_parameter":
        generated[source] = (
            generated[source].replace(b"mg:tools", b"mg:unknown")
            if resource
            else (
                generated[source].replace(
                    b"production_method = pm_tools", b"production_method = unknown"
                )
                if production
                else generated[source].replace(b"market_access < 1.0", b"market_access < 0.5")
            )
        )
    elif fault == "wrong_scope":
        generated[source] = generated[source].replace(
            b"ROOT = {", b"ROOT = { owner = {" if production else b"scope:target_country = {"
        )
        if production:
            generated[source] = generated[source].replace(b" add=2", b"} add=2")
    elif fault == "extra_parameter":
        generated[source] = (
            generated[source].replace(
                b"market_goods_pricier <= 0.25", b"market_goods_pricier <= 0.75"
            )
            if resource
            else (
                generated[source].replace(
                    b"is_production_method_active = {", b"is_production_method_active = { extra=yes"
                )
                if production
                else generated[source].replace(
                    b"any_scope_state = {", b"any_scope_state = { extra=yes"
                )
            )
        )
    elif fault == "missing_metadata":
        generated.pop(".metadata/metadata.json")
    elif fault == "wrong_contract":
        metadata = json.loads(generated[".metadata/metadata.json"])
        metadata["consumer_adapters"]["consumers"][0]["source_sha256"] = "f" * 64
        generated[".metadata/metadata.json"] = json.dumps(metadata).encode()
    elif fault == "duplicate_definition":
        generated["common/buildings/duplicate.txt"] = (
            b"building_tools={}" if production else b"candidate={}"
        )
        if resource:
            generated["common/goods/duplicate.txt"] = b"tools={}"
        if not production:
            generated["common/ai_strategies/duplicate.txt"] = b"candidate={}"
    elif fault == "missing_guard":
        generated[source] = generated[source].replace(b"exists = ROOT", b"always = yes")
    elif fault == "wrong_input_generator":
        metadata = json.loads(generated[".metadata/metadata.json"])
        metadata["consumer_adapters"]["production_inputs_generator_sha256"] = "e" * 64
        generated[".metadata/metadata.json"] = json.dumps(metadata).encode()
    row = _report(reader_case, complete=fault != "incomplete")
    assert not row["interface"]["control_authorized"]


@pytest.mark.parametrize("kind", ["production", "resource"])
def test_optional_building_query_protects_sibling_without_denominator_or_control(
    kind, tmp_path, monkeypatch
):
    from pdx import decision_adapters, decision_rules

    inventory, sources, generated, _path = _reader_case(kind, tmp_path, monkeypatch)
    source = inventory.surfaces[0].source
    sources[source] = b"candidate={unknown=1}"
    generated[source] = generated[source].replace(b"candidate={", b"candidate={unknown=1 ")
    docs = "common/buildings/buildings.md"
    sources[docs] = (
        b"# base AI value, default NAI.BUILDING_BASE_VALUE or NAI.GOVERNMENT_BUILDING_BASE_VALUE\n"
        b"# scope is state the building is located in\nai_value = script value\n"
    )
    old = decision_adapters.load()
    policy = replace(
        old.policies[0][1], baseline_sha256=hashlib.sha256(sources[source]).hexdigest()
    )
    adapters = replace(
        old,
        sources=tuple((name, hashlib.sha256(sources[name]).hexdigest()) for name, _ in old.sources),
        policies=((source, policy),),
    )
    monkeypatch.setattr(decision_adapters, "load", lambda: adapters)
    metadata = json.loads(generated[".metadata/metadata.json"])
    metadata["consumer_adapters"]["sources"] = dict(adapters.sources)
    metadata["consumer_adapters"]["consumers"] = [
        {
            "source": source,
            **decision_rules.contract(policy, owner="consumer_adapters", source=source),
        }
    ]
    generated[".metadata/metadata.json"] = json.dumps(metadata).encode()
    observer = replace(
        inventory.surfaces[0],
        field="unknown",
        actor_scope="unknown",
        target_scope="unknown",
        operation="declared_field",
        capability="pending",
    )
    inventory = replace(
        inventory,
        surfaces=(observer,),
        source_hashes={name: hashlib.sha256(raw).hexdigest() for name, raw in sources.items()},
    )
    coverage = {
        "baseline_id": inventory.baseline_id,
        "scope_hash": inventory.scope_hash,
        "source_hashes": inventory.source_hashes,
        "denominator": 1,
        "rows": [],
        "implicit_rows": [
            {
                "source": source,
                "definition": "candidate",
                "field": "ai_value",
                "actor_scope": "state",
                "target_scope": "none",
                "operation": "score",
                "default": "NAI.BUILDING_BASE_VALUE_or_NAI.GOVERNMENT_BUILDING_BASE_VALUE",
                "evidence": [f"{docs}:1", f"{docs}:2", f"{docs}:3", f"{source}:1"],
                "matched_actions": ["writer"],
                "covered_actions": ["writer"],
                "binding_issues": {},
            }
        ],
    }
    report = native_treatments(
        inventory, sources, generated, coverage=coverage, production_complete=True
    )
    assert len(report["rows"]) == 1
    row = report["rows"][0]
    assert row["source_protection"]["proven"]
    assert not row["interface"]["control_authorized"]
    generated[source] = generated[source].replace(b"exists = ROOT", b"always = yes")
    row = native_treatments(
        inventory, sources, generated, coverage=coverage, production_complete=True
    )["rows"][0]
    assert not row["source_protection"]["proven"]
