"""CLI generation failures preserve frozen sources and existing output bytes."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pdx import cli, version_contracts
from pdx.generation_transaction import GenerationTransaction

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def historical_cli_contract():
    # These fixtures model the legacy ledger CLI; current profile transactions
    # have independent complete-tree/live-installation tests.
    with version_contracts.select_version("1.14.5"):
        yield


@pytest.mark.parametrize("rollback", [False, True])
def test_owned_temporary_paths_are_exact_and_cleaned_on_commit_or_rollback(tmp_path, rollback):
    target = tmp_path / "generated.txt"
    target.write_bytes(b"original\n")
    unowned = tmp_path / ".sitai-generation-external"
    unowned.write_bytes(b"external\n")
    transaction = GenerationTransaction()
    owned: frozenset[Path] = frozenset()
    try:
        with transaction:
            transaction.replace({target: b"replacement\n"})
            owned = transaction.temporary_paths
            assert len(owned) == 1
            assert unowned not in owned
            assert next(iter(owned)).read_bytes() == b"original\n"
            assert isinstance(owned, frozenset)
            if rollback:
                raise ValueError("injected rollback")
    except ValueError:
        assert rollback
    assert transaction.temporary_paths == frozenset()
    assert not any(path.exists() for path in owned)
    assert target.read_bytes() == (b"original\n" if rollback else b"replacement\n")
    assert unowned.read_bytes() == b"external\n"
    assert set(tmp_path.iterdir()) == {target, unowned}


def _tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def generation(tmp_path, monkeypatch):
    game = tmp_path / "game"
    (game / "common").mkdir(parents=True)
    root = tmp_path / "mod"
    binding = root / "decisions/action_bindings.toml"
    domain = root / "decisions/domain_actions.toml"
    initial = {
        "decisions/action_bindings.toml": b"old-bindings\r\n",
        "decisions/domain_actions.toml": b"old-domains\n",
        "common/old.txt": b"old-production\n",
        "generation-lock.json": b"old-lock\n",
        "common/scripted_triggers/sitai_country_triggers.txt": b"retired\n",
        "user-note.bin": b"keep-user-bytes\x00",
    }
    for name, raw in initial.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    monkeypatch.setattr(cli.config, "GAME", game)
    monkeypatch.setattr(cli.decisions, "PRODUCT", root)
    monkeypatch.setattr(cli.situated_bindings, "DEFAULT_SOURCE", binding)
    monkeypatch.setattr(cli.situated_domain_coverage, "DEFAULT_SOURCE", domain)
    monkeypatch.setattr(cli.situated_bindings, "build", lambda: ("new-binding",))
    monkeypatch.setattr(cli.situated_bindings, "render", lambda _rows: "new-bindings\n")
    monkeypatch.setattr(
        cli.situated_domain_coverage, "render_counts", lambda _path: "new-domains\n"
    )
    monkeypatch.setattr(cli, "_modgen_verify_sources", lambda: None)
    monkeypatch.setattr(cli.distribution, "generation_lock", lambda _files: "new-lock\n")

    def build():
        # Production's normal strict readers see only canonical new ledgers.
        assert binding.read_bytes() == b"new-bindings\n"
        assert domain.read_bytes() == b"new-domains\n"
        # Even after ledger derivation no production output has changed.
        assert (root / "common/old.txt").read_bytes() == initial["common/old.txt"]
        return None, None, {"common/new.txt": "new-production\n", "README.md": "guide\n"}

    monkeypatch.setattr(cli.distribution, "package_inputs", build)
    for module in (
        cli.company_sectors,
        cli.distribution.equipment_opportunities,
        cli.distribution.treaty_opportunities,
        cli.distribution.mobilization_opportunities,
    ):
        monkeypatch.setattr(
            module,
            "write_baseline",
            lambda *_: pytest.fail("ordinary generation repinned frozen sources"),
        )
    return root, initial, binding, domain


def _run():
    return CliRunner().invoke(cli.app, ["modgen", "--write"])


def test_valid_rule_change_refreshes_stale_ledgers_and_preserves_user_files(generation):
    root, initial, _, _ = generation
    result = _run()
    assert result.exit_code == 0, result.output
    expected = {
        **initial,
        "decisions/action_bindings.toml": b"new-bindings\n",
        "decisions/domain_actions.toml": b"new-domains\n",
        "common/new.txt": b"new-production\n",
        "generation-lock.json": b"new-lock\n",
    }
    expected.pop("common/scripted_triggers/sitai_country_triggers.txt")
    assert _tree(root) == expected


@pytest.mark.parametrize(
    "stage", ["preflight", "binding", "domain", "build", "staged_write", "lock"]
)
def test_every_generation_failure_leaves_original_artifacts_unchanged(
    generation, monkeypatch, stage
):
    root, initial, _, _ = generation

    def fail(*args, **kwargs):
        raise ValueError(f"{stage}-source-drift")

    owner, attribute = {
        "preflight": (cli, "_modgen_verify_sources"),
        "binding": (cli.situated_bindings, "render"),
        "domain": (cli.situated_domain_coverage, "render_counts"),
        "build": (cli.distribution, "package_inputs"),
        "staged_write": (cli.decisions, "write"),
        "lock": (cli.distribution, "generation_lock"),
    }[stage]
    monkeypatch.setattr(owner, attribute, fail)
    result = _run()
    assert result.exit_code == 1, result.output
    assert f"{stage}-source-drift" in result.output
    assert _tree(root) == initial


@pytest.mark.parametrize("failure_index", [1, 2, 3, 4])
def test_replace_failure_restores_prior_ledgers_outputs_and_deleted_stale_files(
    generation, monkeypatch, failure_index
):
    root, initial, _, _ = generation
    original = os.replace
    calls = 0

    def fail_once(source, target):
        nonlocal calls
        calls += 1
        if calls == failure_index:
            raise PermissionError("injected replacement failure")
        return original(source, target)

    monkeypatch.setattr(os, "replace", fail_once)
    result = _run()
    assert result.exit_code == 1, result.output
    assert "injected replacement failure" in result.output
    assert _tree(root) == initial


def test_failure_restores_missing_ledger_existence(generation, monkeypatch):
    root, initial, binding, _ = generation
    binding.unlink()
    initial.pop("decisions/action_bindings.toml")

    def fail():
        raise OSError("missing-artifact build failure")

    monkeypatch.setattr(cli.distribution, "package_inputs", fail)
    result = _run()
    assert result.exit_code == 1
    assert _tree(root) == initial


def test_readonly_preflight_verifies_existing_pins_without_loading_generated_ledgers(monkeypatch):
    calls = []
    for module, name in (
        (cli.distribution.engine_scope, "verify_strategy_game"),
        (cli.distribution.decision_interfaces, "verify_scripted_trigger_game"),
        (cli.distribution.engine_scope, "verify_company_defaults_game"),
        (cli.company_sectors, "verify_game"),
        (cli.distribution.equipment_opportunities, "verify_game"),
        (cli.distribution.treaty_opportunities, "verify_game"),
        (cli.distribution.mobilization_opportunities, "verify_game"),
        (cli.country_state, "validate"),
        (cli.law_opportunities, "verify_inputs"),
        (cli.technology_opportunities, "verify_inputs"),
    ):
        label = f"{module.__name__}.{name}"
        monkeypatch.setattr(module, name, lambda *_args, label=label: calls.append(label))
    monkeypatch.setattr(cli.country_state, "load", object)
    monkeypatch.setattr(cli.decisions.decision_adapters, "load", object)
    monkeypatch.setattr(cli.decisions.decision_adapters, "read_inputs", lambda _adapters: {})
    monkeypatch.setattr(
        cli.situated_bindings,
        "load",
        lambda *_a, **_k: pytest.fail("stale binding required before derivation"),
    )
    monkeypatch.setattr(
        cli.situated_domain_coverage,
        "load",
        lambda *_a, **_k: pytest.fail("stale count required before derivation"),
    )
    cli._modgen_verify_sources()
    assert len(calls) == 10
    assert sum("verify_game" in name for name in calls) == 4


def test_staging_failure_never_starts_batch_and_cleans_temporary_files(tmp_path, monkeypatch):
    one, two = tmp_path / "one", tmp_path / "nested/two"
    one.write_bytes(b"one-before")
    original = Path.write_bytes
    calls = 0

    def fail_once(path, data):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("staging full")
        return original(path, data)

    monkeypatch.setattr(Path, "write_bytes", fail_once)
    with pytest.raises(OSError, match="staging full"), GenerationTransaction() as transaction:
        transaction.replace({one: b"one-after", two: b"two-after"})
    assert _tree(tmp_path) == {"one": b"one-before"}
    assert not two.parent.exists()


def test_output_delete_failure_rolls_back_earlier_replacements(generation, monkeypatch):
    root, initial, _, _ = generation
    original = Path.unlink
    stale = root / "common/scripted_triggers/sitai_country_triggers.txt"

    def fail(path, *args, **kwargs):
        if path == stale:
            raise PermissionError("stale cleanup blocked")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail)
    result = _run()
    assert result.exit_code == 1, result.output
    assert "stale cleanup blocked" in result.output
    assert _tree(root) == initial


def test_failure_to_restore_original_is_explicit_and_retains_recovery_bytes(tmp_path, monkeypatch):
    target = tmp_path / "output"
    target.write_bytes(b"original")
    original = Path.replace
    calls = 0

    def fail_rollback(path, destination):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise PermissionError("persistent lock")
        return original(path, destination)

    monkeypatch.setattr(Path, "replace", fail_rollback)

    def generate():
        with GenerationTransaction() as transaction:
            transaction.replace({target: b"replacement"})
            raise ValueError("later build failed")

    with pytest.raises(OSError, match=r"回滚失败.*原件备份"):
        generate()
    assert target.read_bytes() == b"replacement"
    backups = [p for p in tmp_path.glob(".sitai-generation-*") if p.read_bytes() == b"original"]
    assert len(backups) == 1


def test_multiple_batches_restore_exact_original_and_remove_new_directory(tmp_path):
    target = tmp_path / "output"
    created = tmp_path / "new/created"
    target.write_bytes(b"original\r\n")

    def generate():
        with GenerationTransaction() as transaction:
            transaction.replace({target: b"first"})
            transaction.replace({target: b"second", created: b"new"})
            raise ValueError("later failure")

    with pytest.raises(ValueError, match="later failure"):
        generate()
    assert _tree(tmp_path) == {"output": b"original\r\n"}
    assert not created.parent.exists()


def test_check_keeps_existing_strict_ledger_validation_and_never_writes(generation, monkeypatch):
    root, initial, _, _ = generation
    monkeypatch.setattr(cli.situated_bindings, "check", lambda: ["stale binding"])
    monkeypatch.setattr(cli.situated_domain_coverage, "check_counts", list)
    result = CliRunner().invoke(cli.app, ["modgen", "--check"])
    assert result.exit_code == 1
    assert "stale binding" in result.output
    assert _tree(root) == initial


def test_failed_staged_write_cannot_leave_its_partial_files(generation, monkeypatch):
    root, initial, _, _ = generation

    def fail(staged, _files):
        (staged / "partial.txt").write_bytes(b"partial staged output")
        (staged / "common/old.txt").write_bytes(b"damaged staged output")
        raise OSError("disk full in stage")

    monkeypatch.setattr(cli.decisions, "write", fail)
    result = _run()
    assert result.exit_code == 1
    assert "disk full in stage" in result.output
    assert _tree(root) == initial


@pytest.mark.parametrize("failed_source", ["company", "equipment", "treaty", "mobilization"])
def test_preflight_cannot_refresh_or_skip_a_drifted_frozen_source(monkeypatch, failed_source):
    for name in ("verify_strategy_game", "verify_company_defaults_game"):
        monkeypatch.setattr(cli.distribution.engine_scope, name, lambda *_: None)
    monkeypatch.setattr(
        cli.distribution.decision_interfaces, "verify_scripted_trigger_game", lambda *_: None
    )

    def fail():
        pytest.fail("source verification attempted a frozen baseline write")

    for label, module in (
        ("company", cli.company_sectors),
        ("equipment", cli.distribution.equipment_opportunities),
        ("treaty", cli.distribution.treaty_opportunities),
        ("mobilization", cli.distribution.mobilization_opportunities),
    ):

        def verify(_game, label=label):
            if label == failed_source:
                raise ValueError(f"{label} native source drift")

        monkeypatch.setattr(module, "verify_game", verify)
        monkeypatch.setattr(module, "write_baseline", fail)
    with pytest.raises(ValueError, match=f"{failed_source} native source drift"):
        cli._modgen_verify_sources()


def test_backup_cleanup_failure_reports_completed_commit_and_retains_backup(
    tmp_path, monkeypatch, caplog
):
    target = tmp_path / "output"
    target.write_bytes(b"original")
    original = Path.unlink

    def fail_backup_cleanup(path, *args, **kwargs):
        if path.name.startswith(".sitai-generation-"):
            raise PermissionError("temporary file locked")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_backup_cleanup)
    with GenerationTransaction() as transaction:
        transaction.replace({target: b"committed"})
    assert target.read_bytes() == b"committed"
    assert "临时文件清理失败" in caplog.text
    assert any(p.read_bytes() == b"original" for p in tmp_path.glob(".sitai-generation-*"))
