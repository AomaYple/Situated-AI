"""Current Victoria 3 build selection and installed identity."""

from pathlib import Path
from typing import Any, cast

import pytest
from typer.testing import CliRunner

from pdx import cli, version_contracts
from pdx.situated import network_profile, production_profile


def test_1152_is_the_current_build_for_default_and_explicit_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(version_contracts.ENVIRONMENT_VARIABLE, raising=False)
    assert version_contracts.require_current() == "1.15.2"
    assert version_contracts.require_current("1.15.2") == "1.15.2"
    assert version_contracts.contract().default_strategy_sha256 == (
        "7fa4e018a796b1f1c04275e7fbc712ac39a4376e86db311f31079b12a8337760"
    )


@pytest.mark.parametrize("historical", ["1.14.5", "1.15.0", "1.15.1"])
def test_online_selection_refuses_retired_build_before_reading_identity(
    monkeypatch: pytest.MonkeyPatch, historical: str
) -> None:
    monkeypatch.setenv(version_contracts.ENVIRONMENT_VARIABLE, historical)
    with pytest.raises(ValueError, match=r"当前仅维护 1\.15\.2"):
        version_contracts.verify_installation_identity(Path("should-not-be-read"))


@pytest.mark.parametrize(
    "arguments",
    [
        ["modgen", "--check"],
        ["modguard", "--offline"],
        ["decision-audit", "--offline"],
    ],
)
def test_public_production_commands_refuse_explicit_historical_profile(
    arguments: list[str],
) -> None:
    result = CliRunner().invoke(cli.app, [*arguments, "--profile", "1.15.0"])
    assert result.exit_code == cli.EXIT_FAILED, result.output
    assert "当前仅维护 1.15.2" in result.output


def test_current_script_profile_preserves_three_r2_consumers_in_offline_audit() -> None:
    profile = production_profile.declared_profile()
    report = network_profile.audit(profile)
    assert profile.game_version == "1.15.2"
    programs = cast("list[dict[str, Any]]", report["programs"])
    assert {row["consumer"] for row in programs} == {
        "a0-econ-road",
        "a0-pol-schools",
        "a0-dip-relations",
    }
    assert report["runtime"] == "unknown"
