"""Effective switches must survive the entire generation/check/package chain."""

from __future__ import annotations

import json
import zipfile

import pytest
from typer.testing import CliRunner

from pdx import cli, decisions, distribution, version_contracts
from pdx.situated import network_profile, production_profile
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


@pytest.mark.integration
def test_configured_generation_check_and_package_share_identity(tmp_path, monkeypatch):
    product = tmp_path / "mod"
    monkeypatch.setattr(decisions, "product_path", lambda: product)
    profile = production_profile.declared_profile()
    selected = ProfileConfiguration(domains=frozenset({"economy"}))
    files = distribution.write_standard_outputs(configuration=selected)
    for row in profile.declarations:
        text = files[row.source.removeprefix("game/")]
        assert (f"SITAI POLICY {profile.game_version} BEGIN" in text) is (row.domain == "economy")
    custom = json.loads(files[distribution.METADATA_NAME])["game_custom_data"]
    assert custom["configuration"] == selected.identity()
    assert set(custom["configuration"]) == {"core", "domains", "enabled_domains", "mode"}
    distribution.check_generation_lock()
    distribution.check_configuration_identity(distribution.read_production_files(), selected)
    with pytest.raises(ValueError, match="完整配置身份不一致"):
        distribution.check_configuration_identity(files, ProfileConfiguration())
    target = distribution.package(tmp_path / "configured.zip", configuration=selected)
    with zipfile.ZipFile(target) as archive:
        packaged = json.loads(archive.read(distribution.METADATA_NAME))
    assert packaged["game_custom_data"]["configuration"] == selected.identity()
    wrong = tmp_path / "wrong.zip"
    with pytest.raises(ValueError, match="生成物不一致"):
        distribution.package(wrong)
    assert not wrong.exists()


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
