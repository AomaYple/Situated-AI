"""Current standard writes keep final drift failures inside ledger rollback."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pdx import cli, decisions, distribution, version_contracts
from pdx.generation_transaction import GenerationTransaction

pytestmark = pytest.mark.unit


@pytest.fixture
def standard_tree(tmp_path, monkeypatch):
    target = tmp_path / "mod"
    (target / "common").mkdir(parents=True)
    (target / "common/current.txt").write_bytes(b"old-production\n")
    (target / "generation-lock.json").write_bytes(b"old-lock\n")
    (target / "user-note.bin").write_bytes(b"keep-user-bytes\x00")
    ledger = tmp_path / "ledger.toml"
    ledger.write_bytes(b"old-ledger\n")
    monkeypatch.setattr(decisions, "product_path", lambda: target)
    monkeypatch.setattr(
        distribution,
        "package_inputs",
        lambda **_kwargs: (
            None,
            None,
            {"common/current.txt": "new-production\n", "README.md": "guide\n"},
        ),
    )
    monkeypatch.setattr(distribution, "_release_files", dict)

    def lock(files=None):
        if files is None:
            files = distribution.read_production_files()
        return (
            json.dumps(
                {
                    "source": hashlib.sha256(ledger.read_bytes()).hexdigest(),
                    "files": {
                        name: hashlib.sha256(
                            raw if isinstance(raw, bytes) else raw.encode()
                        ).hexdigest()
                        for name, raw in sorted(files.items())
                    },
                },
                sort_keys=True,
            )
            + "\n"
        )

    monkeypatch.setattr(distribution, "generation_lock", lock)
    monkeypatch.setattr(distribution, "verify_compatibility_installation", lambda: None)
    with version_contracts.select_version("1.15.1"):
        yield target, ledger


def _tree(target):
    return {
        path.relative_to(target).as_posix(): path.read_bytes()
        for path in target.rglob("*")
        if path.is_file()
    }


def _write_standard_with_shared_ledger(ledger):
    with GenerationTransaction() as transaction:
        transaction.replace({ledger: b"new-ledger\n"})
        distribution.write_standard_outputs(transaction=transaction)


@contextmanager
def _directory_redirect(link, destination):
    """Create a real platform directory link and remove only that link."""
    assert link.parent.is_dir()
    assert not link.exists()
    assert not link.is_symlink()
    destination = destination.resolve(strict=True)
    assert destination.is_dir()
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(destination)],
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    else:
        link.symlink_to(destination, target_is_directory=True)
    try:
        assert link.resolve(strict=True) == destination
        assert link.absolute() != destination
        yield link
    finally:
        # TemporaryDirectory may already have removed a staging child. Never
        # recurse into a target, or remove a replacement ordinary directory.
        with suppress(FileNotFoundError):
            info = link.lstat()
            if stat.S_ISLNK(info.st_mode):
                link.unlink()
            else:
                assert os.name == "nt"
                assert getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                link.rmdir()


@pytest.fixture
def aliased_temporary_parent(tmp_path, monkeypatch):
    base = tmp_path.resolve(strict=True)
    physical = base / "physical-temporary-parent"
    physical.mkdir()
    with _directory_redirect(base / "temporary-parent-alias", physical) as alias:
        monkeypatch.setattr(distribution.tempfile, "gettempdir", lambda: str(alias))
        yield physical
        assert list(physical.iterdir()) == []


@pytest.mark.parametrize("drift", [False, True])
def test_standard_internal_temp_parent_alias_preserves_generation_and_source_drift(
    standard_tree, aliased_temporary_parent, monkeypatch, drift
):
    target, ledger = standard_tree
    stale = target / "common/scripted_triggers/sitai_country_triggers.txt"
    stale.parent.mkdir()
    stale.write_bytes(b"retired\n")
    before = _tree(target)
    write = decisions.write
    staged_roots = []

    def record_staging(root, files):
        staged_roots.append(root)
        assert root.parent.parent == aliased_temporary_parent
        assert root.resolve(strict=True) == root.absolute()
        result = write(root, files)
        if drift:
            ledger.write_bytes(b"changed-during-staging\n")
        return result

    monkeypatch.setattr(decisions, "write", record_staging)
    if drift:
        with pytest.raises(ValueError, match="源码发生漂移"):
            distribution.write_standard_outputs()
        assert _tree(target) == before
        assert ledger.read_bytes() == b"changed-during-staging\n"
    else:
        files = distribution.write_standard_outputs()
        assert files == {"common/current.txt": "new-production\n"}
        assert not stale.exists()
        assert (target / "user-note.bin").read_bytes() == b"keep-user-bytes\x00"
        assert (target / "common/current.txt").read_bytes() == b"new-production\n"
        assert ledger.read_bytes() == b"old-ledger\n"
        distribution.check_generation_lock()
    assert len(staged_roots) == 1
    assert not staged_roots[0].parent.exists()
    assert not list(target.rglob(".sitai-generation-*"))


@pytest.mark.parametrize("placement", ["root", "parent", "nested"])
def test_standard_user_output_redirect_is_rejected_and_shared_ledger_restored(
    standard_tree, tmp_path, monkeypatch, placement
):
    target, ledger = standard_tree
    before = _tree(target)
    base = tmp_path.resolve(strict=True)
    external = base / "external"
    external.mkdir()
    sentinel = external / "sentinel.txt"
    sentinel.write_bytes(b"external original\n")
    if placement == "root":
        link, destination = base / "linked-output", target
        selected = link
    elif placement == "parent":
        link, destination = base / "linked-parent", target.parent
        selected = link / target.name
    else:
        link, destination = target / "linked-child", external
        selected = target
    monkeypatch.setattr(decisions, "product_path", lambda: selected)
    with _directory_redirect(link, destination):
        with pytest.raises(ValueError, match="符号链接或重解析点"):
            _write_standard_with_shared_ledger(ledger)
        assert ledger.read_bytes() == b"old-ledger\n"
        assert sentinel.read_bytes() == b"external original\n"
        assert list(external.iterdir()) == [sentinel]
    assert _tree(target) == before
    assert not list(base.rglob(".sitai-generation-*"))


def test_standard_staging_redirect_is_rejected_with_canonical_temp_parent(
    standard_tree, aliased_temporary_parent, tmp_path, monkeypatch
):
    target, ledger = standard_tree
    before = _tree(target)
    external = tmp_path.resolve(strict=True) / "staging-external"
    external.mkdir()
    sentinel = external / "sentinel.txt"
    sentinel.write_bytes(b"external original\n")
    write = decisions.write
    staged_roots = []
    with ExitStack() as redirects:

        def inject(root, files):
            assert root.parent.parent == aliased_temporary_parent
            result = write(root, files)
            staged_roots.append(root)
            redirects.enter_context(_directory_redirect(root / "linked-child", external))
            return result

        monkeypatch.setattr(decisions, "write", inject)
        with pytest.raises(ValueError, match="符号链接或重解析点"):
            _write_standard_with_shared_ledger(ledger)
    assert len(staged_roots) == 1
    assert not staged_roots[0].parent.exists()
    assert ledger.read_bytes() == b"old-ledger\n"
    assert _tree(target) == before
    assert sentinel.read_bytes() == b"external original\n"
    assert list(external.iterdir()) == [sentinel]
    assert not list(target.rglob(".sitai-generation-*"))


def test_standard_redirect_during_final_verification_rolls_back_outputs_and_ledger(
    standard_tree, tmp_path, monkeypatch
):
    target, ledger = standard_tree
    before = _tree(target)
    external = tmp_path.resolve(strict=True) / "late-external"
    external.mkdir()
    sentinel = external / "sentinel.txt"
    sentinel.write_bytes(b"external original\n")
    with ExitStack() as redirects:

        def inject():
            redirects.enter_context(_directory_redirect(target / "linked-child", external))

        monkeypatch.setattr(distribution, "verify_compatibility_installation", inject)
        with pytest.raises(ValueError, match="符号链接或重解析点"):
            _write_standard_with_shared_ledger(ledger)
        assert ledger.read_bytes() == b"old-ledger\n"
    assert _tree(target) == before
    assert sentinel.read_bytes() == b"external original\n"
    assert list(external.iterdir()) == [sentinel]
    assert not list(target.rglob(".sitai-generation-*"))


def test_standard_retains_user_bytes_and_retires_only_declared_stale_files(standard_tree):
    target, _ = standard_tree
    stale = target / "common/scripted_triggers/sitai_country_triggers.txt"
    stale.parent.mkdir()
    stale.write_bytes(b"retired\n")
    files = distribution.write_standard_outputs()
    assert files == {"common/current.txt": "new-production\n"}
    assert not stale.exists()
    assert (target / "user-note.bin").read_bytes() == b"keep-user-bytes\x00"
    assert (target / "common/current.txt").read_bytes() == b"new-production\n"
    distribution.check_generation_lock()
    assert not list(target.rglob(".sitai-generation-*"))


@pytest.mark.parametrize("timing", ["existing", "during-transaction"])
def test_standard_rejects_unowned_same_prefix_file(standard_tree, monkeypatch, timing):
    target, _ = standard_tree
    before = _tree(target)
    extra = target / "common/.sitai-generation-external"
    if timing == "existing":
        extra.write_bytes(b"external\n")
    else:
        replace = GenerationTransaction.replace

        def inject(transaction, files):
            replace(transaction, files)
            extra.write_bytes(b"external\n")

        monkeypatch.setattr(GenerationTransaction, "replace", inject)
    with pytest.raises(ValueError, match=r"额外文件|文件集合.*漂移"):
        distribution.write_standard_outputs()
    assert _tree(target) == {**before, "common/.sitai-generation-external": b"external\n"}


@pytest.mark.parametrize("damage", ["source", "output", "lock"])
@pytest.mark.parametrize("stage", ["after-lock", "during-live"])
def test_final_drift_restores_shared_ledger_and_entire_tree(
    standard_tree, tmp_path, monkeypatch, damage, stage
):
    target, ledger = standard_tree
    before = _tree(target)
    view = tmp_path / "changed-view"
    view.write_bytes(b"concurrently changed\n")
    damaged = {
        "source": ledger,
        "output": target / "common/current.txt",
        "lock": target / "generation-lock.json",
    }[damage]
    opened = Path.open
    changed = False

    def open_view(path, *args, **kwargs):
        return opened(view if changed and path == damaged else path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_view)
    original = (
        distribution.check_generation_lock
        if stage == "after-lock"
        else distribution.verify_compatibility_installation
    )

    def drift(*args, **kwargs):
        nonlocal changed
        result = original(*args, **kwargs)
        changed = True
        return result

    monkeypatch.setattr(
        distribution,
        "check_generation_lock" if stage == "after-lock" else "verify_compatibility_installation",
        drift,
    )

    def generate():
        with GenerationTransaction() as transaction:
            transaction.replace({ledger: b"new-ledger\n"})
            distribution.write_standard_outputs(transaction=transaction)

    with pytest.raises(ValueError, match=r"漂移|不一致"):
        generate()
    assert changed
    changed = False
    assert ledger.read_bytes() == b"old-ledger\n"
    assert _tree(target) == before
    assert not list(tmp_path.rglob(".sitai-generation-*"))


def test_source_drift_during_staging_cannot_be_absorbed_into_new_lock(standard_tree, monkeypatch):
    target, ledger = standard_tree
    before = _tree(target)
    write = decisions.write

    def drift(root, files):
        result = write(root, files)
        ledger.write_bytes(b"changed-during-staging\n")
        return result

    monkeypatch.setattr(decisions, "write", drift)
    with pytest.raises(ValueError, match="源码发生漂移"):
        distribution.write_standard_outputs()
    assert _tree(target) == before
    # A concurrent source edit belongs to its writer; output rollback retains it.
    assert ledger.read_bytes() == b"changed-during-staging\n"
    assert not list(target.rglob(".sitai-generation-*"))


def test_current_cli_keeps_generated_ledgers_in_standard_writer_transaction(tmp_path, monkeypatch):
    game = tmp_path / "game"
    (game / "common").mkdir(parents=True)
    binding, domain = tmp_path / "binding.toml", tmp_path / "domain.toml"
    binding.write_bytes(b"old-binding\n")
    domain.write_bytes(b"old-domain\n")
    monkeypatch.setattr(cli.config, "GAME", game)
    monkeypatch.setattr(cli, "_production_profile", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli, "_modgen_verify_sources", lambda: None)
    monkeypatch.setattr(cli.situated_bindings, "source_path", lambda: binding)
    monkeypatch.setattr(cli.situated_bindings, "build", lambda: ("one",))
    monkeypatch.setattr(cli.situated_bindings, "render", lambda _rows: "new-binding\n")
    monkeypatch.setattr(cli.situated_domain_coverage, "source_path", lambda: domain)
    monkeypatch.setattr(cli.situated_domain_coverage, "render_counts", lambda _path: "new-domain\n")
    called = False

    def reject(*, configuration, transaction):
        nonlocal called
        called = True
        assert configuration == cli.profile_configuration.ProfileConfiguration()
        assert isinstance(transaction, GenerationTransaction)
        assert binding.read_bytes() == b"new-binding\n"
        assert domain.read_bytes() == b"new-domain\n"
        raise ValueError("final-current-boundary-drift")

    monkeypatch.setattr(distribution, "write_standard_outputs", reject)
    with version_contracts.select_version("1.15.1"):
        result = CliRunner().invoke(cli.app, ["modgen", "--write"])
    assert called
    assert result.exit_code == 1, result.output
    assert "final-current-boundary-drift" in result.output
    assert binding.read_bytes() == b"old-binding\n"
    assert domain.read_bytes() == b"old-domain\n"
    assert not list(tmp_path.rglob(".sitai-generation-*"))
