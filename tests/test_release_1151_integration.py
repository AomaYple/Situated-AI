"""Current release boundaries and independent numeric PDX witnesses.

Frozen source and instrumented CLI tests establish generation semantics and
routing only; they do not claim execution inside the game or ZIP acceptance.
"""

from __future__ import annotations

import json
import tomllib
from typing import cast

import pytest
from test_network_profile import _parsed, _score
from typer.testing import CliRunner

from pdx import cli, decisions, distribution, version_contracts
from pdx.model import Block, Scalar
from pdx.situated import network_profile as network
from pdx.situated import production_profile as native
from pdx.situated.profile_configuration import ProfileConfiguration, validate_coverage


@pytest.fixture(autouse=True)
def current_version():
    with version_contracts.select_version("1.15.1"):
        yield


@pytest.fixture
def profile():
    return native.load_profile(native.baseline_root())


@pytest.fixture
def school(profile):
    return next(
        program
        for program in network.compile_profile(profile)
        if program.network.actions[0].definition.consumer_id == "a0-pol-schools"
    )


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 2),
        ({"bureaucracy": 1}, 2.25),
        ({"net-surplus": 1}, 2.5),
        ({"bureaucracy": 1, "net-surplus": 1}, 2.75),
        ({"bureaucracy": 1, "net-surplus": 1, "school-agenda": True}, 3.75),
        ({"bureaucracy": -1, "default": True}, -2),
        ({"literacy": 0.5}, 0),
        ({"population": 0}, 0),
        ({"population": 0, "bureaucracy": -1, "default": True}, -4),
        ({"ai": False, "bureaucracy": -1, "default": True}, 0),
    ],
)
def test_school_additive_policy_has_literal_independent_pdx_witness(school, changes, expected):
    facts: dict[str, object] = {
        "ai": True,
        "literacy": 0.4,
        "population": 1,
        "bureaucracy": 0,
        "default": False,
        "net-surplus": 0,
        "school-agenda": False,
        **changes,
    }
    # The interpreter reads emitted PDX in source order; no reference network
    # evaluator or producer score is used to derive these literal expectations.
    assert _score(_parsed(network.render_program(school)), facts) == expected


@pytest.mark.parametrize("missing", ["literacy", "population", "bureaucracy", "default"])
def test_school_missing_required_fact_withdraws_complete_writer(school, missing):
    available = tuple(fact.id for fact in school.network.facts if fact.id != missing)
    assert _score(_parsed(network.render_program(school, available=available)), {"ai": True}) == 0


def test_school_missing_optional_fiscal_fact_retains_independent_admin_capacity(school):
    available = tuple(fact.id for fact in school.network.facts if fact.id != "net-surplus")
    facts: dict[str, object] = {
        "ai": True,
        "literacy": 0.4,
        "population": 1,
        "bureaucracy": 1,
        "default": False,
        "school-agenda": False,
    }
    assert _score(_parsed(network.render_program(school, available=available)), facts) == 2.25


def test_composition_preserves_native_bytes_and_existing_unrelated_writers(profile):
    files = {
        row.source.removeprefix("game/"): (
            (native.baseline_root() / row.source).read_text(encoding="utf-8-sig")
            + "\n# independent legacy writer\nsitai_preserved = { value = 17 }\n"
        )
        for row in profile.declarations
    }
    before = dict(files)
    audit = network.compose(files, profile)
    assert audit["integration"] == "complete-production-single-writer"
    assert len(cast("list[dict[str, object]]", audit["writers"])) == 3
    for row in profile.declarations:
        name = row.source.removeprefix("game/")
        # Exact reversal checks every original sibling and comment, including
        # any unrelated writer already present when the R2 pass started.
        assert native.strip_policy(files[name], row) == before[name]
        assert f"SITAI POLICY 1.15.1 BEGIN {row.id}" in files[name]
    with pytest.raises(ValueError, match="another writer already changed"):
        network.compose(files, profile)


def test_school_migration_names_exactly_the_six_frozen_multiplier_rules():
    expected = {
        "remaining_school_catchup_need",
        "remaining_school_fiscal",
        "remaining_school_administrative",
        "remaining_school_capacity",
        "school_default_pressure",
        "school_administrative_pressure",
    }
    with (native.ROOT / "mod/decisions/information.toml").open("rb") as handle:
        declaration = tomllib.load(handle)
    school_rules = {
        rule["id"]
        for rule in declaration["rules"]
        if rule["field"] == "institution_scores.institution_schools"
    }
    assert school_rules == expected == set(network.SCHOOL_MIGRATION)


def test_configuration_mapping_covers_actual_legacy_declarations():
    # Read authoritative declarations independently of the production mapping.
    domains: set[str] = set()
    for path in (native.ROOT / "mod/decisions").glob("*.toml"):
        with path.open("rb") as handle:
            declaration = tomllib.load(handle)
        domains.update(rule["domain"] for rule in declaration.get("rules", []))
    modules = frozenset(decisions.EXTENSION_PROFILE_MODULES)
    validate_coverage(frozenset(domains), modules)
    for bad_domains, bad_modules in (
        (frozenset(domains | {"unknown"}), modules),
        (frozenset(domains - {"fiscal"}), modules),
        (frozenset(domains), modules | {"unknown"}),
        (frozenset(domains), modules - {"economy"}),
    ):
        with pytest.raises(ValueError, match="映射漂移"):
            validate_coverage(bad_domains, bad_modules)


@pytest.mark.parametrize(
    "configuration", [ProfileConfiguration(core=False), ProfileConfiguration(mode="neutral")]
)
def test_disabled_configuration_withdraws_all_legacy_extensions_and_r2(profile, configuration):
    assert (
        configuration.enabled_domains
        == configuration.legacy_domains
        == configuration.extension_modules
        == frozenset()
    )
    policy, extensions = distribution.production_configuration(configuration=configuration)
    assert policy.enabled is False
    assert not any(
        (
            extensions.reform_enabled,
            extensions.economy_enabled,
            extensions.market_enabled,
            extensions.security_enabled,
            extensions.diplomacy_enabled,
        )
    )
    files: dict[str, str] = {}
    audit = network.compose(files, profile, configuration=configuration)
    assert all(row["enabled"] is False for row in cast("list[dict[str, object]]", audit["writers"]))
    assert all("SITAI POLICY" not in text for text in files.values())


def test_historical_configuration_identity_retains_exact_four_keys():
    with version_contracts.select_version("1.15.0"):
        assert set(ProfileConfiguration().identity()) == {
            "core",
            "domains",
            "enabled_domains",
            "mode",
        }


@pytest.mark.parametrize("disabled", ["economy", "politics", "diplomacy"])
def test_domain_switch_controls_legacy_modules_and_r2_consumer(profile, disabled):
    selected = ProfileConfiguration(
        domains=frozenset({"economy", "politics", "diplomacy"} - {disabled})
    )
    policy, extensions = distribution.production_configuration(configuration=selected)
    assert policy.enabled is (disabled != "economy")
    assert extensions.economy_enabled is (disabled != "economy")
    assert extensions.market_enabled is (disabled != "economy")
    assert extensions.reform_enabled is (disabled != "politics")
    assert extensions.security_enabled is (disabled != "diplomacy")
    assert extensions.diplomacy_enabled is (disabled != "diplomacy")
    files: dict[str, str] = {}
    audit = network.compose(files, profile, configuration=selected)
    expected_disabled = {
        "economy": "a0-econ-road",
        "politics": "a0-pol-schools",
        "diplomacy": "a0-dip-relations",
    }[disabled]
    assert {
        row["id"] for row in cast("list[dict[str, object]]", audit["writers"]) if not row["enabled"]
    } == {expected_disabled}


@pytest.mark.parametrize(
    "selected", [ProfileConfiguration(core=False), ProfileConfiguration(mode="neutral")]
)
@pytest.mark.integration
def test_complete_disabled_package_has_only_fiscal_state_cleanup(selected):
    # Exercise the actual complete package boundary. No identity, installation,
    # reader authority or binary evidence check is patched out in this test.
    policy, _, files = distribution.package_inputs(
        include_engineering_metadata=True,
        configuration=selected,
    )
    assert policy.enabled is False
    metadata = json.loads(files[distribution.METADATA_NAME])
    assert not metadata["enabled_modules"]
    assert not metadata.get("default_field_owners", {})
    effect_text = files["common/scripted_effects/sitai_fiscal_effects.txt"]
    assert isinstance(effect_text, str)
    effects = _parsed(effect_text)
    update = effects.first("sitai_update_fiscal")
    assert update is not None
    assert isinstance(update.value, Block)
    entries = list(update.value.assignments())
    assert len(entries) == 1
    assert entries[0].key == "remove_variable"
    assert isinstance(entries[0].value, Scalar)
    assert entries[0].value.text == "sitai_fiscal_risk"
    assert "common/scripted_triggers/sitai_fiscal_triggers.txt" not in files
    assert "sitai_fiscal_update" in files["common/on_actions/sitai_fiscal_on_actions.txt"]
    for name, text in files.items():
        if name.startswith("common/") and isinstance(text, str):
            assert "SITAI POLICY" not in text
            if name.startswith(
                (
                    "common/scripted_effects/",
                    "common/scripted_triggers/",
                    "common/script_values/",
                    "common/on_actions/",
                )
            ):
                assert name in {
                    "common/scripted_effects/sitai_fiscal_effects.txt",
                    "common/on_actions/sitai_fiscal_on_actions.txt",
                }


@pytest.mark.integration
def test_complete_default_package_contains_three_unique_current_writers_and_legacy_modules(profile):
    # Keep all installation, native identity, reader authority, historical
    # migration and final complete-composition checks active at this boundary.
    policy, extensions, files = distribution.package_inputs(include_engineering_metadata=True)
    assert policy.enabled
    assert all(
        (
            extensions.reform_enabled,
            extensions.economy_enabled,
            extensions.market_enabled,
            extensions.security_enabled,
            extensions.diplomacy_enabled,
        )
    )
    metadata = json.loads(files[distribution.METADATA_NAME])
    assert metadata["supported_game_version"] == "1.15.1"
    assert metadata["enabled_modules"]
    assert metadata["default_field_owners"]
    assert "common/scripted_effects/sitai_fiscal_effects.txt" in files
    for row in profile.declarations:
        text = files[row.source.removeprefix("game/")]
        assert isinstance(text, str)
        assert text.count(f"SITAI POLICY 1.15.1 BEGIN {row.id}") == 1
        assert text.count(f"SITAI POLICY 1.15.1 END {row.id}") == 1


@pytest.mark.parametrize("name", ["1.15.2", "1.16.0", "../1.15.1", "research/vanilla-ai/1.15.1"])
def test_future_and_path_profile_values_fail_closed(name):
    with pytest.raises(ValueError):
        cli._production_profile(name, offline=True)
    with pytest.raises(ValueError):
        network.source_path(name)


def test_default_and_explicit_current_cli_use_identical_full_package_route(monkeypatch, tmp_path):
    calls = []
    checked: list[native.ProductionProfile] = []
    monkeypatch.setattr(distribution, "check_profile_installation", checked.append)

    def package(output, *, configuration):
        calls.append((output, configuration.identity()))
        return output

    def historical_route(*args, **kwargs):
        pytest.fail("current release incorrectly selected historical three-file package")

    monkeypatch.setattr(distribution, "package", package)
    monkeypatch.setattr(distribution, "profile_package", historical_route)
    output = tmp_path / "current.zip"
    runner = CliRunner()
    for arguments in ([], ["--profile", "1.15.1"]):
        result = runner.invoke(cli.app, ["package", "--output", str(output), *arguments])
        assert result.exit_code == 0, result.output
    assert len(calls) == 2
    assert calls[0] == calls[1]
    assert len(checked) == 2
    assert checked[0] == checked[1]
    assert checked[0].game_version == "1.15.1"
