"""Current Victoria 3 build selection and installed identity."""

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from typer.testing import CliRunner

from pdx import (
    cli,
    decision_adapters,
    decision_interfaces,
    decisions,
    distribution,
    version_contracts,
)
from pdx.situated import network_profile, production_profile, profile_configuration

if TYPE_CHECKING:
    from collections.abc import Callable


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


def test_current_adapter_authority_proves_default_strategy_field_shapes() -> None:
    authority = decision_adapters.native_authority_115()
    assert authority["game_version"] == "1.15.2"
    assert authority["sources"]["common/ai_strategies/00_default_strategy.txt"] == (
        "42088c06f326a6fd1f01ed120928c8888d29b776c9bacb9795c63f9c390d7d40"
    )


def test_current_scripted_predicate_uses_the_current_version_inventory() -> None:
    assert decision_interfaces.scripted_predicate_path().parent.name == "1.15.2"
    assert decision_interfaces.scripted_trigger_snapshot()


def test_configuration_identity_mismatch_rejects_current_profile() -> None:
    files = {distribution.METADATA_NAME: '{"game_custom_data": {"configuration": {}}}'}
    with pytest.raises(ValueError, match="完整配置身份不一致"):
        distribution.check_configuration_identity(
            files, profile_configuration.ProfileConfiguration()
        )


@pytest.mark.parametrize("drift", ["before-archive", "before-replace"])
def test_current_package_rejects_drift_and_preserves_previous_package(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, drift: str
) -> None:
    product = tmp_path / "mod"
    generated = product / ".metadata/metadata.json"
    generated.parent.mkdir(parents=True)
    generated.write_bytes(b"{}\n")
    files = {distribution.METADATA_NAME: "{}\n"}
    lock = product / "generation-lock.json"
    package = tmp_path / "candidate.zip"
    package.write_bytes(b"previous package")
    monkeypatch.setattr(decisions, "PRODUCT", product)
    monkeypatch.setattr(distribution, "package_inputs", lambda **_: (None, None, files))
    monkeypatch.setattr(distribution, "_release_files", dict)
    monkeypatch.setattr(distribution, "_release_generation", lambda *_: {})
    monkeypatch.setattr(distribution, "verify_compatibility_installation", lambda: None)
    lock.write_bytes(distribution.generation_lock().encode())

    def check_replacement(
        _files: object, destination: Path, *, before_replace: Callable[[], None], **_options: object
    ) -> Path:
        if drift == "before-archive":
            pytest.fail("a drifted lock reached the archive writer")
        lock.write_bytes(b"drift")
        before_replace()
        destination.write_bytes(b"unexpected replacement")
        return destination

    monkeypatch.setattr(distribution, "write_zip", check_replacement)
    if drift == "before-archive":
        lock.write_bytes(b"drift")
    with pytest.raises(ValueError, match="生产源码或产物与冻结记录不一致"):
        distribution.package(package)
    assert package.read_bytes() == b"previous package"


@pytest.mark.parametrize("damage", [None, "normalized-only-match", "different-content"])
def test_current_default_strategy_accepts_only_pinned_raw_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str | None
) -> None:
    game = tmp_path / "game"
    original = game / "common/ai_strategies/00_default_strategy.txt"
    original.parent.mkdir(parents=True)
    normalized = b"example = { always = yes }\n"
    raw = b"\xef\xbb\xbf" + normalized.replace(b"\n", b"\r\n")
    original.write_bytes(raw)
    current = version_contracts.contract()
    monkeypatch.setitem(
        version_contracts.VERSION_SPECS,
        current.version,
        replace(
            current,
            default_strategy_sha256=sha256(raw).hexdigest(),
            baseline_strategy_sha256=sha256(normalized).hexdigest(),
        ),
    )
    if damage is None:
        assert version_contracts.read_default_strategy(game) == normalized.decode()
    else:
        broken = normalized if damage == "normalized-only-match" else b"other"
        original.write_bytes(broken)
        with pytest.raises(ValueError, match="默认策略原始字节"):
            version_contracts.read_default_strategy(game)
