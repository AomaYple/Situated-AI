"""The live CLI enforces the current installation identity and accepts launcher platform paths."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from conftest import configure_current_identity
from typer.testing import CliRunner

from pdx import (
    ai_surface,
    cli,
    config,
    distribution,
    docs_mirror,
    political_surface,
    version_contracts,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@pytest.fixture
def installation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "installation"
    configure_current_identity(root, monkeypatch)
    (root / "game").mkdir()
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
    "read",
    [
        ai_surface.strategy_files,
        ai_surface.read_cards,
        ai_surface.read_defines,
        ai_surface.build,
        ai_surface.snapshot_section,
        political_surface.strategy_files,
        political_surface.read_strategies,
        political_surface.read_default_strategy,
        political_surface.build,
        docs_mirror.iter_docs,
        docs_mirror.build_manifest,
    ],
)
def test_default_read_rejects_unreviewed_build(
    installation: Path, read: Callable[[], object]
) -> None:
    (installation / "caligula_rev.txt").write_bytes(b"unreviewed")
    with pytest.raises(ValueError, match=r"caligula_rev\.txt"):
        read()


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


@pytest.mark.parametrize("environment", ["", "1.14.5", "1.15.0", "1.15.1", "unknown"])
def test_explicit_current_does_not_override_old_online_environment(
    environment: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(version_contracts.ENVIRONMENT_VARIABLE, environment)
    target = tmp_path / "package.zip"
    result = CliRunner().invoke(
        cli.app,
        ["package", "--profile", version_contracts.CURRENT_VERSION, "--output", str(target)],
    )
    assert result.exit_code == cli.EXIT_FAILED, result.output
    assert f"合同版本：{environment!r}" in result.output
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
