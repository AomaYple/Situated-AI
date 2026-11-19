"""Live CLI admits the reviewed 1.15.1 installation and its platform aliases."""

from __future__ import annotations

import json
import shutil
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from pdx import cli, config, distribution, version_contracts
from pdx.situated import r2_reader_authority

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def installation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "installation"
    shutil.copytree(r2_reader_authority.frozen_root("1.15.1"), root)
    monkeypatch.setattr(config, "ROOT", root)
    monkeypatch.setattr(config, "GAME", root / "game")
    monkeypatch.setattr(config, "OUT", tmp_path / "out")
    return root


@pytest.mark.parametrize(
    "arguments",
    [
        ["analyze"],
        ["information-catalog"],
        ["defines"],
        ["index", "--dry-run"],
        ["snapshot", "create"],
        ["snapshot", "verify"],
        ["mirror", "write"],
        ["refresh", "--dry-run"],
        ["tables"],
        ["verify"],
        ["strings"],
        ["evidence", "example"],
        ["prefixes"],
        ["assets"],
        ["csv", "table.csv"],
        ["ai-surface"],
        ["political-surface"],
        ["situated", "report", "--native"],
    ],
)
def test_live_command_rejects_unreviewed_build(installation: Path, arguments: list[str]) -> None:
    (installation / "caligula_rev.txt").write_bytes(b"unreviewed")
    result = CliRunner().invoke(cli.app, arguments)
    assert result.exit_code == cli.EXIT_USAGE, result.output
    assert "caligula_rev.txt" in result.output
    assert not config.OUT.exists()


@pytest.mark.parametrize(
    "exe", ["../binaries/victoria3", "../Victoria3.app/Contents/MacOS/victoria3"]
)
def test_live_csv_accepts_launcher_platform_paths(installation: Path, exe: str) -> None:
    launcher = installation / "launcher/launcher-settings.json"
    payload = json.loads(launcher.read_bytes())
    payload["exePath"] = exe
    launcher.write_text(json.dumps(payload), encoding="utf-8")
    (installation / "game/table.csv").write_bytes(b"Name;Count\nSample;1\n")
    result = CliRunner().invoke(cli.app, ["csv", "table.csv", "--column", "Name"])
    assert result.exit_code == 0, result.output
    assert "Sample" in result.output


@pytest.mark.parametrize("environment", ["", "1.14.5", "1.15.0", "unknown"])
def test_explicit_current_does_not_override_old_online_environment(
    environment: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(version_contracts.ENVIRONMENT_VARIABLE, environment)
    target = tmp_path / "package.zip"
    result = CliRunner().invoke(
        cli.app, ["package", "--profile", "1.15.1", "--output", str(target)]
    )
    assert result.exit_code == cli.EXIT_FAILED, result.output
    assert "合同版本" in result.output
    assert not target.exists()


@pytest.mark.parametrize(
    "arguments",
    [["modgen", "--write"], ["package"], ["modguard"], ["decision-audit"]],
)
def test_public_online_commands_reject_historical_profile(
    arguments: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("historical invocation reached production")

    monkeypatch.setattr(distribution, "check_profile_installation", forbidden)
    result = CliRunner().invoke(cli.app, [*arguments, "--profile", "1.15.0"])
    assert result.exit_code == cli.EXIT_FAILED, result.output
    assert "合同版本" in result.output
