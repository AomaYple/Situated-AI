"""Isolated regional resource opportunity: physical cases, not generated expectations."""

from __future__ import annotations

from dataclasses import replace

import pytest
from regional_physical_reference import evaluate as actual_pdx
from regional_physical_reference import stance

from pdx import regional_resource_opportunities


def _regional():
    return regional_resource_opportunities


def test_one_real_regional_resource_opportunity_is_sufficient():
    regional = _regional()
    program = regional.compile_program()
    root = {"id": "A", "technologies": {"pumpjacks": True, "rubber_mastication": False}}
    region = {
        "states": [
            {
                "owner": {"id": "B", "country_type": "decentralized"},
                "potential_resources": {"building_oil_rig": 1, "building_rubber_plantation": 0},
            }
        ]
    }
    observed = regional.observe_query(regional.RegionalResourceQuery(), root, region)
    assert observed is True
    assert program.evaluate({"regional_resource_opportunity": observed}, is_ai=True) == 15


@pytest.fixture(scope="module")
def regional():
    return _regional()


@pytest.fixture(scope="module")
def native(regional):
    return regional.frozen_inputs()


@pytest.fixture(scope="module")
def patched(regional, native):
    return regional.patch(native)[regional.SOURCE]


def _state(oil=0, rubber=0, owner_type="decentralized"):
    return {
        "id": "S",
        "owner": {"id": "B", "country_type": owner_type},
        "potential_resources": {"building_oil_rig": oil, "building_rubber_plantation": rubber},
    }


def _world():
    region = {"id": "region_equatorial_africa", "states": [_state(oil=1)]}
    actor = {
        "id": "A",
        "is_ai": True,
        "country_type": "recognized",
        "navy_size": 50,
        "country_rank": 10,
        "capital_region": {"id": "region_other"},
        "neighbours": [],
        "country_is_colonial_or_company": False,
        "technologies": {
            "colonization": True,
            "pumpjacks": True,
            "rubber_mastication": False,
            "civilizing_mission": False,
            "quinine": False,
        },
        "laws": {"law_type:law_no_colonial_affairs": False},
        "strategies": {"ai_strategy_colonial_expansion": False},
        "journal": {"je_scramble_for_africa": False},
    }
    return actor, region


CASES = [
    ("oil_only", 300, 315, True),
    ("rubber_only", 300, 315, True),
    ("both", 300, 315, True),
    ("neither", 300, 300, False),
    ("oil_without_pumpjacks", 300, 300, False),
    ("rubber_without_rubber_tech", 300, 300, False),
    ("wrong_tech", 300, 300, False),
    ("unknown_oil_tech", 300, 300, None),
    ("unknown_oil_potential", 300, 300, None),
    ("unknown_tech_but_rubber_known", 300, 315, True),
    ("unknown_rubber_but_oil_known", 300, 315, True),
    ("unknown_state_but_oil_known", 300, 315, True),
    ("missing_owner", 300, 300, None),
    ("recognized_resource_owner", 300, 300, False),
    ("split_states", 500, 515, True),
    ("huge_potential", 300, 315, True),
    ("no_colonization", 0, 0, True),
    ("unknown_colonization", 0, 0, True),
    ("no_colonial_law", 0, 0, True),
    ("unrecognized_actor", 0, 0, True),
    ("no_navy_or_neighbour", 0, 0, True),
    ("neighbour_at_49_navy", 300, 315, True),
    ("small_country_overseas", 0, 0, True),
    ("small_country_home_region", 300, 315, True),
    ("colonial_company", 500, 515, True),
    ("colonial_strategy", 900, 915, True),
    ("civilizing", 1500, 1515, True),
    ("quinine", 750, 765, True),
    ("scramble", 3000, 3015, True),
    ("combined_native_multipliers", 45000, 45015, True),
    ("player", 300, 300, True),
    ("empty_region", 0, 0, False),
    ("missing_region", 0, 0, None),
]


def _case(name):
    actor, region = _world()
    tech = actor["technologies"]
    if name in {"rubber_only", "rubber_without_rubber_tech"}:
        region["states"] = [_state(rubber=1)]
        tech["rubber_mastication"] = name == "rubber_only"
    elif name == "both":
        region["states"] = [_state(1, 1)]
        tech["rubber_mastication"] = True
    elif name == "neither":
        region["states"] = [_state()]
    elif name == "oil_without_pumpjacks":
        tech["pumpjacks"] = False
    elif name == "wrong_tech":
        tech.update(pumpjacks=False, rubber_mastication=True)
    elif name == "unknown_oil_tech":
        tech["pumpjacks"] = None
    elif name == "unknown_oil_potential":
        region["states"] = [_state(oil=None)]
    elif name == "unknown_tech_but_rubber_known":
        tech.update(pumpjacks=None, rubber_mastication=True)
        region["states"] = [_state(oil=None, rubber=1)]
    elif name == "unknown_rubber_but_oil_known":
        tech["rubber_mastication"] = None
    elif name == "unknown_state_but_oil_known":
        region["states"].append(None)
    elif name == "missing_owner":
        region["states"] = [
            _state(),
            {
                "owner": None,
                "potential_resources": {"building_oil_rig": 1, "building_rubber_plantation": 0},
            },
        ]
    elif name == "recognized_resource_owner":
        region["states"] = [_state(), _state(oil=100, owner_type="recognized")]
    elif name == "split_states":
        region["states"] = [_state(1), _state(1)]
    elif name == "huge_potential":
        region["states"] = [_state(oil=100000000)]
    elif name == "no_colonization":
        tech["colonization"] = False
    elif name == "unknown_colonization":
        tech["colonization"] = None
    elif name == "no_colonial_law":
        actor["laws"]["law_type:law_no_colonial_affairs"] = True
    elif name == "unrecognized_actor":
        actor["country_type"] = "unrecognized"
    elif name == "no_navy_or_neighbour":
        actor["navy_size"] = 49
    elif name == "neighbour_at_49_navy":
        actor["navy_size"] = 49
        actor["neighbours"] = [{"region": region}]
    elif name == "small_country_overseas":
        actor["country_rank"] = 4
    elif name == "small_country_home_region":
        actor["country_rank"] = 4
        actor["capital_region"] = region
    elif name == "colonial_company":
        actor["country_is_colonial_or_company"] = True
    elif name == "colonial_strategy":
        actor["strategies"]["ai_strategy_colonial_expansion"] = True
    elif name in {"civilizing", "quinine"}:
        tech["civilizing_mission" if name == "civilizing" else "quinine"] = True
    elif name == "scramble":
        actor["journal"]["je_scramble_for_africa"] = True
    elif name == "combined_native_multipliers":
        actor["strategies"]["ai_strategy_colonial_expansion"] = True
        tech.update(civilizing_mission=True, quinine=True)
        actor["journal"]["je_scramble_for_africa"] = True
    elif name == "player":
        actor["is_ai"] = False
    elif name == "empty_region":
        region["states"] = []
    elif name == "missing_region":
        region = None
    return actor, region


@pytest.mark.parametrize(("case", "before", "after", "observation"), CASES)
def test_literal_worlds_run_complete_original_and_patched_numeric_ast(
    regional, native, patched, case, before, after, observation
):
    actor, region = _case(case)
    query_result = regional.observe_query(regional.RegionalResourceQuery(), actor, region)
    assert query_result is observation
    assert actual_pdx(native[regional.SOURCE], actor, region) == before
    assert actual_pdx(patched, actor, region) == after
    program = regional.compile_program()
    expected_delta = 15 if observation is True and actor["is_ai"] else 0
    assert (
        program.evaluate({"regional_resource_opportunity": query_result}, is_ai=actor["is_ai"])
        == expected_delta
    )


def test_scope_isolation_unknown_recovery_and_no_national_proxy(regional, patched):
    actor, rich = _world()
    empty_potential = {"id": "other", "states": [_state()]}
    actor["states"] = [_state(oil=999)]
    actor["regions"] = [rich, empty_potential]
    for region, expected in ((rich, 315), (empty_potential, 300), (rich, 315)):
        assert actual_pdx(patched, actor, region) == expected
    for value, expected in ((True, 15), (None, 0), (False, 0), (True, 15)):
        assert (
            regional.compile_program().evaluate(
                {"regional_resource_opportunity": value}, is_ai=True
            )
            == expected
        )
    actor["technologies"]["pumpjacks"] = False
    assert actual_pdx(patched, actor, rich) == 300
    assert regional.observe_query(regional.RegionalResourceQuery(), actor, {"states": None}) is None
    assert regional.observe_query(regional.RegionalResourceQuery(), None, rich) is None


def test_complete_parent_native_text_and_small_country_tail_are_untouched(
    regional, native, patched
):
    rendered = regional.render(regional.compile_program())
    assert patched.count(rendered) == 1
    assert patched.replace(rendered, "") == native[regional.SOURCE]
    body = stance(patched)
    branches = body.all("if")
    assert len(branches) == 2
    native_body = stance(native[regional.SOURCE])
    assert regional._shape(branches[1].value) == regional._shape(native_body.all("if")[1].value)
    assert rendered.count("scope:target_region = { any_scope_state") == 1
    assert all(
        token not in rendered
        for token in (
            "any_country",
            "any_market",
            "every_country",
            "set_variable",
            "state_region =",
            "war_support",
        )
    )
    assert len(regional.compile_program().scalar.groups) == 1
    assert regional.compile_program().scalar.lower == 0
    assert regional.compile_program().scalar.upper == 15
    assert regional.patch(native, enabled_domains=frozenset()) == {}
    actor, region = _world()
    assert actual_pdx(native[regional.SOURCE], actor, region) == 300
    assert (
        regional.compile_program().evaluate(
            {"regional_resource_opportunity": True}, is_ai=True, enabled=False
        )
        == 0
    )
    assert (
        regional.compile_program().evaluate(
            {"regional_resource_opportunity": True}, is_ai=True, native_eligible=False
        )
        == 0
    )


def test_proof_uses_trigger_scope_not_effect_only_and_rejects_mutation(regional, native):
    (reader,) = regional.compile_program().readers()
    query = regional.query_from_reader(reader.engine, dict(reader.parameters))
    assert regional.required_query_sources(query) == tuple(sorted(native))
    compiled = regional.compile_query(regional.RegionalResourceQuery(), native)
    assert regional.render_query(query) == compiled.expression
    assert compiled.world_scans == 0
    assert compiled.local_collections == ("target_region.any_scope_state",)
    assert compiled.target == "scope:target_region=strategic_region"
    assert any(ref.endswith(":5104") for ref in compiled.references)
    assert regional.compile_program().evaluation_context().targets[0].kind == "strategic_region"
    for key in regional.SOURCES:
        changed = dict(native)
        changed[key] += "\n# changed full parent/caller\n"
        with pytest.raises(ValueError, match="漂移"):
            regional.compile_query(regional.RegionalResourceQuery(), changed)
    for engine, params in (
        ("any_scope_state", {"regional_resource_query": "oil_or_rubber"}),
        ("scope:target_region", {"regional_resource_query": "all_resources"}),
        ("scope:target_region", {"regional_resource_query": "oil_or_rubber", "target": "africa"}),
    ):
        with pytest.raises(ValueError, match="固定typed"):
            regional.query_from_reader(engine, params)


def test_patch_rejects_duplicate_or_other_author_and_preserves_unrelated_overlay(
    regional, native, patched
):
    with pytest.raises(ValueError, match="重复"):
        regional.patch(native, overlays={regional.SOURCE: patched})
    other = native[regional.SOURCE].replace(
        "AI_REGION_STANCE_CIVILIZING_MISSION_RESEARCHED", "other_author"
    )
    with pytest.raises(ValueError, match="其他作者"):
        regional.patch(native, overlays={regional.SOURCE: other})
    overlay = native[regional.SOURCE] + "\n# unrelated sibling writer already integrated\n"
    result = regional.patch(native, overlays={regional.SOURCE: overlay})[regional.SOURCE]
    assert result.replace(regional.render(regional.compile_program()), "") == overlay
    with pytest.raises(ValueError, match="身份"):
        regional.patch(
            native, consumer_program=replace(regional.compile_program(), target="target_state")
        )


@pytest.mark.parametrize("bad", [True, -1, float("nan"), float("inf"), "1"])
def test_malformed_resource_amount_is_not_an_unknown_or_reward(regional, bad):
    actor, region = _world()
    region["states"][0]["potential_resources"]["building_oil_rig"] = bad
    with pytest.raises(ValueError, match="有限非负"):
        regional.observe_query(regional.RegionalResourceQuery(), actor, region)


def test_source_identity_cannot_be_resigned_in_toml(regional, native, tmp_path):
    original = regional.PARAMETERS
    changed = tmp_path / "params.toml"
    content = original.read_text(encoding="utf-8")
    old_digest = regional.load()["sources"][regional.SOURCE]
    changed.write_text(content.replace(old_digest, "0" * 64), encoding="utf-8")
    try:
        regional.PARAMETERS = changed
        with pytest.raises(ValueError, match="不能重签"):
            regional.verify_inputs(native)
    finally:
        regional.PARAMETERS = original


def test_shared_typed_reader_and_ir_require_exact_consumer_and_current_program(regional, native):
    from pdx import decision_interfaces, observation_queries
    from pdx.situated.decision_ir import ConsumerIRBundle

    program = regional.compile_program()
    (reader,) = program.readers()
    query = observation_queries.from_reader(reader.engine, dict(reader.parameters))
    assert observation_queries.compile_query(query, native).world_scans == 0
    assert reader.expression("=", True) == regional.render_query(query)
    context = program.evaluation_context()
    assert (
        decision_interfaces.reader_scope(
            reader, (), source=program.source, field=program.field_path, context=context
        )
        == "country"
    )
    for changed in (
        replace(reader, scope="target_state"),
        replace(reader, key="alias"),
        replace(reader, engine="any_scope_state"),
    ):
        with pytest.raises(ValueError):
            decision_interfaces.reader_scope(
                changed, (), source=program.source, field=program.field_path, context=context
            )
    for source, field, ctx in (
        (None, program.field_path, context),
        (program.source, ("ai_strategy_default", "state_value"), context),
        (program.source, program.field_path, None),
    ):
        with pytest.raises(ValueError):
            decision_interfaces.reader_scope(reader, (), source=source, field=field, context=ctx)
    writer = program.writer_ir()
    bundle = ConsumerIRBundle(1, (), (writer,))
    assert bundle.as_dict()["regional_resource_program_writer_count"] == 1
    for changed in (
        replace(writer, definition="alias"),
        replace(writer, target="none"),
        replace(writer, regional_resource_program=None),
        replace(writer, regional_resource_program=replace(program, unit="other")),
    ):
        with pytest.raises(ValueError):
            ConsumerIRBundle(1, (), (changed,)).as_dict()
    with pytest.raises(ValueError, match="重复"):
        ConsumerIRBundle(
            1, (), (writer, replace(writer, writer_id="alias", definition="alias"))
        ).as_dict()


def test_shared_adapter_compiles_same_physical_patch_and_respects_domain(regional, native):
    from pdx import decision_adapters
    from pdx.situated.decision_ir import ConsumerIRBundle

    program = regional.compile_program()
    adapters = decision_adapters.AdapterSet(
        tuple(sorted(regional.load()["sources"].items())),
        (),
        "isolated",
        regional_resource_programs=(program,),
    )
    bundle = ConsumerIRBundle(1, (), (program.writer_ir(),))
    files, contract = decision_adapters.build(
        adapters, texts=native, enabled_domains=frozenset({"economy"}), consumer_ir=bundle
    )
    assert files == regional.patch(native)
    assert contract["regional_resource_programs"] == [program.as_dict()]
    assert decision_adapters.writes(adapters, frozenset()) == ()
    assert (
        decision_adapters.build(
            adapters, texts=native, enabled_domains=frozenset(), consumer_ir=bundle
        )[0]
        == {}
    )
    with pytest.raises(ValueError, match="缺失"):
        decision_adapters.build(
            adapters,
            texts=native,
            enabled_domains=frozenset({"economy"}),
            consumer_ir=ConsumerIRBundle(1, (), ()),
        )


@pytest.fixture(scope="module")
def regional_exact_proof(regional, native):
    import hashlib
    import json
    from pathlib import Path

    from pdx import decision_adapters, decision_interfaces
    from pdx.situated import vanilla_inventory

    program = regional.compile_program()
    from pdx import config

    inputs = {
        name: (config.REPO / name if name == regional.R7 else config.GAME / name).read_bytes()
        for name in native
    }
    context = json.loads(native[regional.R7])["consumers"]["strategic_region_stance_type_scores"]
    from pdx.parser import parse_bytes
    from pdx.situated import engine_scope

    definition = parse_bytes(inputs[regional.SOURCE], path=regional.SOURCE).root.first(
        "ai_strategy_default"
    )
    assert definition is not None
    scope = vanilla_inventory._scope(
        "ai_strategies",
        tuple(regional.FIELD.split(".")[1:]),
        inputs,
        {},
        definition,
        regional.SOURCE,
        strategy_proof=engine_scope.StrategyScopeEvidence(
            True,
            (),
            (regional.SOURCE,),
            (
                engine_scope.StrategyConsumerEvidence(
                    "strategic_region_stance_type_scores",
                    context["actor_scope"],
                    context["target_scope"],
                    context["operation"],
                    context["capability"],
                    (
                        f"{engine_scope.STRATEGY_MANIFEST_ID}:sha256={engine_scope.STRATEGY_MANIFEST_SHA256}",
                        f"@engine/binaries/victoria3.exe:{context['consumer_va']}",
                    ),
                ),
            ),
        ),
    )
    surface = vanilla_inventory._surface(
        regional.SOURCE,
        "ai_strategy_default",
        regional.FIELD.removeprefix("ai_strategy_default."),
        5088,
        scope,
    )
    inventory = vanilla_inventory.VanillaInventory(
        "regional_exact",
        {name: hashlib.sha256(raw).hexdigest() for name, raw in inputs.items()},
        "b" * 64,
        (surface,),
        ("ai_strategies",),
        ("common",),
        len(inputs),
    )
    digest = hashlib.sha256(
        regional.PARAMETERS.read_bytes()
        + b"\0baseline:"
        + regional.FROZEN.read_bytes()
        + b"\0generator:"
        + Path(regional.__file__).read_bytes()
    ).hexdigest()
    adapters = decision_adapters.AdapterSet(
        tuple(sorted(regional.load()["sources"].items())),
        (),
        "isolated",
        regional_resource_programs=(program,),
        regional_resource_opportunities_sha256=digest,
    )
    from pdx.situated.decision_ir import ConsumerIRBundle

    bundle = ConsumerIRBundle(1, (), (program.writer_ir(),))
    files, contract = decision_adapters.build(
        adapters, texts=native, enabled_domains=frozenset({"economy"}), consumer_ir=bundle
    )
    metadata = {
        "situated_actions": {"consumer_ir": bundle.as_dict()},
        "consumer_adapters": contract,
        "source_fingerprint": {
            "consumer_adapters_generator_sha256": contract["generator_sha256"],
            "consumer_interfaces_sha256": hashlib.sha256(
                Path(decision_interfaces.__file__).read_bytes()
            ).hexdigest(),
        },
    }
    output = {name: text.encode() for name, text in files.items()}
    output[".metadata/metadata.json"] = json.dumps(metadata).encode()
    return program, surface, inventory, inputs, output


def _exact_proof(case, output=None, native=None):
    from pdx.situated.native_treatments import (
        _Dependencies,
        _regional_resource_program_proof,
        _Sources,
    )

    _, surface, inventory, inputs, original_output = case
    output = original_output if output is None else output
    inputs = inputs if native is None else native
    before = _Sources(inputs)
    effective = {**inputs, **output}
    deps = _Dependencies(
        before,
        _Sources(effective, reuse=before),
        inputs,
        effective,
        inventory.source_hashes,
        production_complete=True,
    )
    return _regional_resource_program_proof(surface, inventory, deps, output)


@pytest.mark.integration
def test_current_program_physical_projection_and_exact_native_coverage(regional_exact_proof):
    from pdx.situated import action_instances, domain_coverage
    from pdx.situated.native_treatments import native_treatments

    p, _surface, inventory, native, output = regional_exact_proof
    assert _exact_proof(regional_exact_proof)["definition"] == p.writer_id
    instance = action_instances.ActionInstance(
        p.writer_id,
        "regional_resource_program",
        p.source,
        p.definition,
        "economy",
        p.field,
        "add",
        0,
        tuple(r.key for r in p.readers()),
        "regional_resource_opportunities",
        "preserve",
        p.evaluation_context().evidence,
        "overseas",
        "root",
        "target_region",
        p.evaluation_context(),
    )
    coverage = domain_coverage.native_coverage(inventory, (instance,), native_sources=native)
    assert coverage["counts"]["actual_covered"] == 1, coverage["rows"]
    report = native_treatments(
        inventory, native, output, coverage=coverage, production_complete=True
    )
    assert report["rows"][0]["status"] == "implemented_numeric", report["rows"][0]
    assert (
        action_instances.missing_witnesses((instance,), {p.source: output[p.source].decode()}) == ()
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "mutation",
    [
        "no_program",
        "renamed_writer",
        "context",
        "scalar",
        "source",
        "permission_source",
        "tail",
        "moved_suffix",
        "duplicate_suffix",
        "owner",
        "program_digest",
    ],
)
def test_protected_projection_rejects_unproved_or_drifted_authors(regional_exact_proof, mutation):
    import json

    from pdx import regional_resource_opportunities as regional

    p, _, _, native, original = regional_exact_proof
    output = dict(original)
    metadata = json.loads(output[".metadata/metadata.json"])
    writer = metadata["situated_actions"]["consumer_ir"]["writers"][0]
    if mutation == "no_program":
        writer.pop("regional_resource_program")
    elif mutation == "renamed_writer":
        writer["writer_id"] = "renamed"
    elif mutation == "context":
        writer["evaluation_context"]["targets"][0]["kind"] = "state"
    elif mutation == "scalar":
        writer["regional_resource_program"]["scalar"]["upper"] = 999
    elif mutation == "owner":
        writer["owner"] = "other"
    elif mutation == "program_digest":
        metadata["consumer_adapters"]["regional_resource_opportunities_sha256"] = "0" * 64
    elif mutation == "permission_source":
        output[regional.BUILDINGS] = native[regional.BUILDINGS].replace(
            b"rubber_mastication", b"wrong_technology"
        )
    elif mutation == "source":
        changed = dict(native)
        changed[regional.R7] += b"\n"
        assert _exact_proof(regional_exact_proof, native=changed) == {}
        return
    else:
        text = output[p.source].decode()
        suffix = regional.render(p)
        if mutation == "tail":
            text = text.replace(
                "country_rank <= rank_value:minor_power", "country_rank < rank_value:minor_power"
            )
        elif mutation == "moved_suffix":
            text = text.replace(suffix, "") + suffix
        elif mutation == "duplicate_suffix":
            text += suffix
        output[p.source] = text.encode()
    output[".metadata/metadata.json"] = json.dumps(metadata).encode()
    assert _exact_proof(regional_exact_proof, output) == {}


def test_retired_country_routes_accept_only_exact_new_regional_author(regional):
    import json

    from pdx.situated import migration_baseline

    rows = json.loads(migration_baseline.RETIREMENTS_SOURCE.read_bytes())["retirements"]
    rows = [r for r in rows if r["source"] == regional.SOURCE and r["field"] == regional.FIELD]
    assert len(rows) == 4
    writer = regional.compile_program().writer_ir()
    for row in rows:
        migration_baseline._validate_native_retention(row, (writer,))
        migration_baseline._validate_native_retention(row, ())
        for unsafe in (
            replace(writer, kind="rule_action"),
            replace(writer, definition="old_route"),
            replace(writer, target="none"),
            replace(writer, regional_resource_program=None),
        ):
            with pytest.raises(ValueError):
                migration_baseline._validate_native_retention(row, (unsafe,))


@pytest.mark.integration
def test_native_source_loader_keeps_repository_r7_separate_from_game(regional):
    from pdx import decision_adapters

    adapters = decision_adapters.AdapterSet(
        tuple(sorted(regional.load()["sources"].items())), (), "isolated"
    )
    inputs = decision_adapters.read_inputs(adapters)
    assert inputs == regional.frozen_inputs()
