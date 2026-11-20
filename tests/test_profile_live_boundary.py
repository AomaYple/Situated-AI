"""Online production requires installed originals; frozen checks stay offline.

The installation fixture copies reviewed native bytes into a temporary tree.
It tests filesystem/version contracts, never game execution or sampled values.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import configure_current_identity
from test_compatibility_live_boundary import complete_inputs, standard_tree  # noqa: F401
from typer.testing import CliRunner

from pdx import cli, config, distribution, version_contracts
from pdx.situated import r2_reader_authority as authority


@pytest.mark.parametrize("selected", [None, "1.14.5", "1.15.0", "1.15.1", "unknown"])
def test_cli_offline_profile_asserts_current_without_installation(monkeypatch, selected):
    if selected is None:
        monkeypatch.delenv("V3_CONTRACT_PROFILE", raising=False)
    else:
        monkeypatch.setenv("V3_CONTRACT_PROFILE", selected)
    with pytest.raises(ValueError, match="合同版本"):
        cli._production_profile("1.15.0", offline=True)
    if selected is None:
        cli._production_profile(None, offline=True)
    else:
        with pytest.raises(ValueError, match="合同版本"):
            cli._production_profile(None, offline=True)


def test_fresh_cli_does_not_allow_explicit_current_to_hide_unknown_environment():
    environment = {**os.environ, "V3_CONTRACT_PROFILE": "unknown"}
    code = (
        "from pdx import cli\n"
        "from pdx.version_contracts import CURRENT_VERSION\n"
        "for profile in (None, CURRENT_VERSION):\n"
        "    try:\n"
        "        cli._production_profile(profile, offline=True)\n"
        "    except ValueError as error:\n"
        "        assert '合同版本' in str(error)\n"
        "    else:\n"
        "        raise AssertionError('unknown profile environment must fail')\n"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", "-c", code],
        cwd=config.REPO,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "arguments",
    [
        ["modgen", "--write"],
        ["modgen", "--check"],
        ["package"],
        ["modguard"],
        ["decision-audit"],
    ],
)
@pytest.mark.parametrize("damage", ["missing-installation", "reader-drift", "version-drift"])
def test_every_online_entry_fails_before_writing_when_installed_inputs_are_invalid(
    arguments, damage, tmp_path, monkeypatch
):
    current = tmp_path / "current-installation"
    configure_current_identity(current, monkeypatch)
    sources = {
        "game/common/diplomatic_actions/01_expel_diplomats.txt": b"example = { always = yes }\n",
    }
    for name, raw in sources.items():
        path = current / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    monkeypatch.setattr(
        authority,
        "CURRENT_SOURCE_SHA256",
        {name: hashlib.sha256(raw).hexdigest() for name, raw in sources.items()},
    )
    monkeypatch.setattr(config, "ROOT", current)
    monkeypatch.setattr(config, "GAME", current / "game")
    monkeypatch.setattr(config, "OUT", tmp_path / "out")
    if damage == "missing-installation":
        monkeypatch.setattr(config, "ROOT", tmp_path / "absent-installation")
    else:
        relative = (
            "launcher/launcher-settings.json"
            if damage == "version-drift"
            else "game/common/diplomatic_actions/01_expel_diplomats.txt"
        )
        target = current / relative
        if damage == "version-drift":
            document = json.loads(target.read_bytes())
            document["rawVersion"] = "1.15.0"
            target.write_text(json.dumps(document), encoding="utf-8")
        else:
            target.write_bytes(target.read_bytes() + b"\n# installed drift\n")
    result = CliRunner().invoke(
        cli.app, [*arguments, "--profile", version_contracts.CURRENT_VERSION]
    )
    assert result.exit_code == 1, result.output
    if damage == "version-drift":
        assert "launcher-settings.json" in result.output
        assert "漂移" in result.output
    else:
        assert "R2 reader authority" in result.output or "原版安装" in result.output
    assert not config.OUT.exists()


@pytest.mark.integration
@pytest.mark.usefixtures("standard_tree")
def test_profile_generation_binds_source_before_compilation(tmp_path, monkeypatch, request):
    target = request.getfixturevalue("standard_tree")
    before = {path: path.read_bytes() for path in target.rglob("*") if path.is_file()}
    source = config.REPO / "src/pdx/situated/network_profile.py"
    view = tmp_path / "changed-source.py"
    view.write_bytes(b"changed immediately after compilation\n")
    opened = Path.open
    changed = False

    def open_view(path, *args, **kwargs):
        return opened(view if changed and path == source else path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_view)
    build = distribution.package_inputs

    def drift_after_build(*args, **kwargs):
        nonlocal changed
        result = build(*args, **kwargs)
        changed = True
        return result

    monkeypatch.setattr(distribution, "package_inputs", drift_after_build)
    with pytest.raises(ValueError, match="标准生产生成期间源码发生漂移"):
        distribution.write_standard_outputs()
    assert changed
    changed = False
    assert {path: path.read_bytes() for path in target.rglob("*") if path.is_file()} == before
