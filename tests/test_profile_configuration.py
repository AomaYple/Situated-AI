"""Effective switches must survive the entire generation/check/package chain."""

from __future__ import annotations

import json
import sys

import pytest
from typer.testing import CliRunner

from pdx import cli, config, distribution
from pdx.situated import production_profile
from pdx.situated.profile_configuration import ProfileConfiguration, load


def test_configuration_is_strict_and_core_off_is_effective(tmp_path):
    path = tmp_path / "profile.toml"
    path.write_text('schema = 1\ncore = false\ndomains = ["economy"]\nmode = "policy"\n')
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
        path.write_text(contents)
        with pytest.raises(ValueError):
            load(path)


def test_configured_generation_check_and_package_share_identity(tmp_path, monkeypatch):
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


def test_cli_audit_resolves_configuration_once_for_real_check_and_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUT", tmp_path / "out")
    path = tmp_path / "profile.toml"
    path.write_text('schema=1\ncore=true\ndomains=["economy"]\nmode="policy"\n')
    selected = load(path)
    profile = production_profile.load_profile(production_profile.BASELINE_ROOT)
    files = distribution.write_profile_outputs(profile, configuration=selected)
    generated_identity = json.loads(files[distribution.METADATA_NAME])["game_custom_data"][
        "configuration"
    ]
    resolver = cli._profile_configuration
    resolved = []

    def resolve(*args, **kwargs):
        configuration = resolver(*args, **kwargs)
        resolved.append(configuration)
        # A later filesystem change must not split one audit across two configurations.
        path.write_text('schema=1\ncore=true\ndomains=["politics"]\nmode="policy"\n')
        return configuration

    monkeypatch.setattr(cli, "_profile_configuration", resolve)
    observed: dict[str, list[ProfileConfiguration]] = {"check": [], "audit": []}
    watched = {
        distribution.check_profile_outputs.__code__: "check",
        cli.situated_network_profile.audit.__code__: "audit",
    }

    def observe(frame, event, arg):
        # Observe the real callees without replacing their checks or audit results.
        if event == "call" and frame.f_code in watched:
            observed[watched[frame.f_code]].append(frame.f_locals["configuration"])

    report_path = tmp_path / "audit.json"
    previous_profiler = sys.getprofile()
    sys.setprofile(observe)
    try:
        result = CliRunner().invoke(
            cli.app,
            [
                "decision-audit",
                "--profile",
                "1.15.0",
                "--configuration",
                str(path),
                "--offline",
                "--output",
                str(report_path),
            ],
        )
    finally:
        sys.setprofile(previous_profiler)
    assert result.exit_code == 0, result.output
    assert len(resolved) == 1
    for configurations in observed.values():
        assert len(configurations) == 1
        assert configurations[0] is resolved[0]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["configuration"] == generated_identity == selected.identity()
    assert [row["consumer"] for row in report["action_network"]["programs"]] == ["a0-econ-road"]
    assert {row["id"] for row in report["consumers"] if row["enabled"]} == {"a0-econ-road"}


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
