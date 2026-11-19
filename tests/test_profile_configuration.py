"""Effective switches must survive the entire generation/check/package chain."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from pdx import cli, config, distribution, version_contracts
from pdx.situated import network_profile, production_profile, r2_reader_authority
from pdx.situated.profile_configuration import ProfileConfiguration, load


def test_configuration_is_strict_and_core_off_is_effective(tmp_path):
    path = tmp_path / "profile.toml"
    path.write_text(
        'schema = 1\ncore = false\ndomains = ["economy"]\nmode = "policy"\n', encoding="utf-8"
    )
    selected = load(path)
    assert selected.domains == frozenset({"economy"})
    assert selected.enabled_domains == frozenset()
    for contents in (
        'schema=1\ncore=1\ndomains=[]\nmode="policy"',
        'schema=1\ncore=true\ndomains=["unknown"]\nmode="policy"',
        'schema=1\ncore=true\ndomains=["economy","economy"]\nmode="policy"',
        'schema=1\ncore=true\ndomains=[]\nmode="unknown"',
        'schema=1\ncore=true\ndomains=[]\nmode="policy"\nextra=true',
    ):
        path.write_text(contents, encoding="utf-8")
        with pytest.raises(ValueError):
            load(path)


def test_configured_generation_check_and_package_share_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", r2_reader_authority.FROZEN_ROOT)
    monkeypatch.setattr(config, "OUT", tmp_path / "out")
    profile = production_profile.load_profile(production_profile.BASELINE_ROOT)
    selected = ProfileConfiguration(domains=frozenset({"economy"}))
    files = distribution.write_profile_outputs(profile, configuration=selected)
    for row in profile.declarations:
        text = files[row.source.removeprefix("game/")]
        assert ("SITAI POLICY 1.15.0 BEGIN" in text) is (row.domain == "economy")
    custom = json.loads(files[distribution.METADATA_NAME])["game_custom_data"]
    assert custom["configuration"] == selected.identity()
    assert distribution.check_profile_outputs(profile, configuration=selected)
    with pytest.raises(ValueError, match="漂移"):
        distribution.check_profile_outputs(profile)
    target = distribution.profile_package(
        tmp_path / "configured.zip", profile, configuration=selected
    )
    assert target.is_file()
    with pytest.raises(ValueError, match="漂移"):
        distribution.profile_package(tmp_path / "wrong.zip", profile)


def test_cli_audit_resolves_configuration_once_for_current_network(tmp_path, monkeypatch):
    path = tmp_path / "profile.toml"
    path.write_text('schema=1\ncore=true\ndomains=["economy"]\nmode="policy"\n', encoding="utf-8")
    selected = load(path)
    resolver = cli._profile_configuration
    resolved = []

    def resolve(*args, **kwargs):
        configuration = resolver(*args, **kwargs)
        resolved.append(configuration)
        path.write_text(
            'schema=1\ncore=true\ndomains=["politics"]\nmode="policy"\n', encoding="utf-8"
        )
        return configuration

    def source_metadata(*, configuration):
        return {
            "configuration": configuration.identity(),
            "action_network": network_profile.audit(
                production_profile.declared_profile(), configuration=configuration
            ),
        }

    monkeypatch.setattr(cli, "_profile_configuration", resolve)
    monkeypatch.setattr(cli.decision_report, "source_metadata", source_metadata)

    def build(metadata):
        return {
            **metadata,
            "domains": {"economy": {"status": "consumer_mapped"}},
            "reader_count": 0,
            "information_reader_count": 0,
            "consumer_reader_count": 0,
            "information_rule_count": 0,
            "consumer_rule_count": 0,
        }

    monkeypatch.setattr(cli.decision_report, "build", build)
    report_path = tmp_path / "audit.json"
    result = CliRunner().invoke(
        cli.app,
        [
            "decision-audit",
            "--profile",
            version_contracts.CURRENT_VERSION,
            "--configuration",
            str(path),
            "--offline",
            "--output",
            str(report_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert resolved == [selected]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["configuration"] == selected.identity()
    assert [row["consumer"] for row in report["action_network"]["programs"]] == ["a0-econ-road"]


@pytest.mark.parametrize(
    "selected", [ProfileConfiguration(core=False), ProfileConfiguration(mode="neutral")]
)
def test_disabled_policy_has_no_nonzero_overlay(selected):
    profile = production_profile.load_profile(production_profile.BASELINE_ROOT)
    files = distribution.profile_outputs(profile, configuration=selected)
    assert not any(
        "SITAI POLICY 1.15.0 BEGIN" in value for value in files.values() if isinstance(value, str)
    )
    if not selected.core:
        for row in profile.declarations:
            original = (production_profile.BASELINE_ROOT / row.source).read_text(
                encoding="utf-8-sig"
            )
            assert files[row.source.removeprefix("game/")] == original


@pytest.fixture(autouse=True)
def _historical_1150_contract(request):
    """Retain the original version identity for historical artifact tests."""
    if (
        request.node.originalname
        == "test_cli_audit_resolves_configuration_once_for_current_network"
    ):
        yield
    else:
        with version_contracts.select_version("1.15.0"):
            yield
