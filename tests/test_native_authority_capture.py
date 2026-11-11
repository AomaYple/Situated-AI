"""Authority recapture requires an explicit current identity and isolated output."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from pdx import config, version_contracts
from pdx import native_authority_capture as capture
from pdx import technology_opportunities as technology
from pdx.situated import (
    compatibility_115,
    migration_baseline,
    native_treatments,
    r2_reader_authority,
    vanilla_inventory,
)

pytestmark = pytest.mark.unit

KINDS = ("parameters", "retentions-native-subset", "compatibility", "technology-catalog")
STRATEGY = "common/ai_strategies/00_default_strategy.txt"
TECHNOLOGY = "common/technology/technologies/30_society.txt"


def test_module_cli_help_exposes_four_real_candidates_without_requiring_installation():
    result = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", "-m", "pdx.native_authority_capture", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert all(kind in result.stdout for kind in KINDS)
    assert "--profile" in result.stdout
    assert "--installation" in result.stdout
    assert "--output" in result.stdout


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    installation = tmp_path / "installation"
    game = installation / "game"
    game.mkdir(parents=True)
    monkeypatch.setattr(config, "REPO", repo)
    verified = []

    def verify(root):
        assert root == installation
        assert version_contracts.active_version() == "1.15.1"
        verified.append(root)
        return {"runtime": "unknown"}

    monkeypatch.setattr(r2_reader_authority, "verify_installation", verify)
    return repo, installation, verified


def _argv(installation, kind, output):
    return [
        "--profile",
        "1.15.1",
        "--installation",
        str(installation),
        "--kind",
        kind,
        "--output",
        str(output),
    ]


@pytest.mark.parametrize("missing", ["--profile", "--installation", "--kind", "--output"])
def test_cli_requires_every_selection_even_when_environment_has_current_profile(sandbox, missing):
    repo, installation, verified = sandbox
    args = _argv(installation, "parameters", repo / "tools/out/capture/parameters.json")
    position = args.index(missing)
    del args[position : position + 2]
    with pytest.raises(SystemExit) as exc:
        capture.main(args)
    assert exc.value.code == 2
    assert verified == []
    assert not (repo / "tools/out").exists()


@pytest.mark.parametrize("profile", ["1.14.5", "1.15.0", "1.15.2"])
def test_cli_rejects_noncurrent_explicit_profile_before_reads_or_writes(sandbox, profile):
    repo, installation, verified = sandbox
    args = _argv(installation, "parameters", repo / "tools/out/capture/parameters.json")
    args[1] = profile
    with pytest.raises(SystemExit) as exc:
        capture.main(args)
    assert exc.value.code == 2
    assert verified == []
    assert not (repo / "tools/out").exists()


def test_cli_rejects_unknown_kind_before_reads_or_writes(sandbox):
    repo, installation, verified = sandbox
    with pytest.raises(SystemExit) as exc:
        capture.main(_argv(installation, "all", repo / "tools/out/capture/all.json"))
    assert exc.value.code == 2
    assert verified == []
    assert not (repo / "tools/out").exists()


@pytest.fixture
def native_inputs(sandbox, monkeypatch):
    repo, installation, _ = sandbox
    game = installation / "game"
    strategy = (
        "ai_strategy_default = {\n"
        "retained = { value = 2 }\n"
        + "\n".join(f"{field} = {{ value = 1 }}" for field in sorted(compatibility_115.FIELDS))
        + "\n}\n"
    )
    inputs = {
        STRATEGY: strategy,
        "common/on_actions/00_code_on_actions.txt": "\n".join(
            f"# Root = Country\n{hook} = {{ effect = {{ }} }}"
            for hook in sorted(compatibility_115.HOOKS)
        ),
        "common/script_values/war_support_values.txt": "war_support = { value = 1 }\n",
        TECHNOLOGY: "banking = { era = era_1 category = society ai_weight = { value = 1 } }\n",
    }
    for source, text in inputs.items():
        path = game / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    baseline_root = repo / "research/vanilla-ai/1.15.1"
    baseline_root.mkdir(parents=True)
    for source in (STRATEGY, "common/script_values/war_support_values.txt"):
        (baseline_root / Path(source).name).write_text(inputs[source], encoding="utf-8")
    monkeypatch.setattr(
        version_contracts, "research_path", lambda _category, name: baseline_root / name
    )
    monkeypatch.setattr(
        vanilla_inventory, "_PARAMETER_EVIDENCE_HASHES", {STRATEGY: "historical-hash-unused"}
    )
    historical = repo / "historical-retentions.json"
    root = capture._root(game, STRATEGY)
    historical.write_text(
        json.dumps(
            {
                "schema": 1,
                "version": "1.15.0",
                "evidence_kind": "native_static",
                "runtime": "unknown",
                "source": "historical-baseline",
                "source_sha256": "old",
                "definition": "ai_strategy_default",
                "retentions": {
                    "retained": native_treatments._digest(
                        capture._node(root, ("ai_strategy_default", "retained")).value
                    )
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(migration_baseline, "_VERSION_115_SOURCE", historical)
    catalog = technology.inventory({TECHNOLOGY: inputs[TECHNOLOGY]}, {"banking": TECHNOLOGY})
    catalog["legacy_rules"] = []
    template = repo / "technology_historical.toml"
    template.write_text(
        "schema = 1\ncatalog_json = '''"
        + json.dumps(catalog)
        + "'''\n\n[parameters]\nreviewed = 7\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(technology, "PARAMETERS_115", template)
    return inputs


@pytest.mark.parametrize("kind", KINDS)
def test_cli_runs_each_capture_to_explicit_candidate_and_restores_profile(
    sandbox, native_inputs, capsys, kind
):
    repo, installation, verified = sandbox
    suffix = ".toml" if kind == "technology-catalog" else ".json"
    output = repo / "tools/out/capture" / (kind + suffix)
    with version_contracts.select_version("1.15.0"):
        assert capture.main(_argv(installation, kind, output)) == 0
        assert version_contracts.active_version() == "1.15.0"
    assert verified == [installation]
    summary = json.loads(capsys.readouterr().out)
    assert summary["artifact_role"] == "review_candidate"
    assert summary["runtime"] == "unknown"
    assert summary["output"] == str(output)
    assert output.read_bytes().endswith(b"\n")
    assert b"\r\n" not in output.read_bytes()
    assert not output.read_bytes().startswith(b"\xef\xbb\xbf")
    if kind == "technology-catalog":
        data = tomllib.loads(output.read_text(encoding="utf-8"))
        assert data["parameters"] == {"reviewed": 7}
        assert (
            json.loads(data["catalog_json"])["sources"][TECHNOLOGY]
            == hashlib.sha256(native_inputs[TECHNOLOGY].encode()).hexdigest()
        )
    else:
        data = json.loads(output.read_bytes())
        assert data["version"] == "1.15.1"
        assert data["runtime"] == "unknown"
        if kind == "parameters":
            assert data["sources"] == {
                STRATEGY: hashlib.sha256(native_inputs[STRATEGY].encode()).hexdigest()
            }
        elif kind == "retentions-native-subset":
            assert data["capture_scope"] == "native_retention_subset_not_full_migration_contract"
            assert set(data["retentions"]) == {"retained"}
            assert "school_policy_migration" not in data
        else:
            assert set(data["fields"]) == compatibility_115.FIELDS
            assert set(data["hooks"]) == compatibility_115.HOOKS


@pytest.mark.parametrize("kind", KINDS)
def test_candidate_is_idempotent_but_never_replaces_different_bytes(sandbox, native_inputs, kind):
    repo, installation, _ = sandbox
    suffix = ".toml" if kind == "technology-catalog" else ".json"
    output = repo / "tools/out/capture" / (kind + suffix)
    args = _argv(installation, kind, output)
    assert capture.main(args) == 0
    original = output.read_bytes()
    before = output.stat().st_mtime_ns
    assert capture.main(args) == 0
    assert output.stat().st_mtime_ns == before
    assert output.read_bytes() == original
    output.write_bytes(b"reviewed-content-must-remain\n")
    assert capture.main(args) == 1
    assert output.read_bytes() == b"reviewed-content-must-remain\n"


@pytest.mark.parametrize(
    "relative",
    [
        "research/situated/1.15.0/migration-retentions.json",
        "research/situated/1.15.1/inventory-parameters.json",
        "mod/decisions/technology_opportunities_1151.toml",
        "tools/out/snapshots/release-1.15.1.compact.json",
        "tools/out/evidence/not-yet-created/authority.json",
        "tools/out/../outside.json",
        "tools/out/candidate.txt",
        "tools/out/CON.json",
    ],
)
def test_cli_rejects_protected_or_unsafe_output_before_installation_reads(sandbox, relative):
    repo, installation, verified = sandbox
    output = repo / relative
    assert capture.main(_argv(installation, "parameters", output)) == 1
    assert verified == []
    assert not (repo / "tools/out").exists()
    assert not output.exists()


def test_cli_rejects_directory_output_without_modifying_it(sandbox):
    repo, installation, verified = sandbox
    output = repo / "tools/out/existing.json"
    output.mkdir(parents=True)
    assert capture.main(_argv(installation, "parameters", output)) == 1
    assert verified == []
    assert output.is_dir()
    assert list(output.iterdir()) == []


def test_cli_rejects_linked_output_and_preserves_target(sandbox):
    repo, installation, verified = sandbox
    target = repo / "reviewed.json"
    target.write_bytes(b"reviewed original bytes\n")
    output = repo / "tools/out/link.json"
    output.parent.mkdir(parents=True)
    try:
        output.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    assert capture.main(_argv(installation, "parameters", output)) == 1
    assert verified == []
    assert target.read_bytes() == b"reviewed original bytes\n"


def test_cli_rejects_output_inside_installation_even_under_tools_out(sandbox):
    repo, _, verified = sandbox
    installation = repo / "tools/out/installation"
    (installation / "game").mkdir(parents=True)
    output = installation / "candidate.json"
    assert capture.main(_argv(installation, "parameters", output)) == 1
    assert verified == []
    assert not output.exists()


@pytest.mark.parametrize("kind", KINDS)
def test_direct_capture_rejects_historical_context_before_identity_or_output(sandbox, kind):
    repo, installation, verified = sandbox
    suffix = ".toml" if kind == "technology-catalog" else ".json"
    output = repo / "tools/out/candidate" / (kind + suffix)
    functions = {
        "parameters": capture.capture_parameters,
        "retentions-native-subset": capture.capture_retentions,
        "compatibility": capture.capture_compatibility,
        "technology-catalog": technology.write_catalog_1151,
    }
    with (
        version_contracts.select_version("1.15.0"),
        pytest.raises(ValueError, match="只接受当前"),
    ):
        functions[kind](installation / "game", output=output)
    assert verified == []
    assert not output.parent.exists()


@pytest.mark.parametrize("kind", KINDS)
def test_installation_drift_fails_before_any_candidate_is_created(sandbox, monkeypatch, kind):
    repo, installation, _ = sandbox
    suffix = ".toml" if kind == "technology-catalog" else ".json"
    output = repo / "tools/out/capture" / (kind + suffix)
    # Use the real verifier against an incomplete installation, not a fake success.
    monkeypatch.undo()
    monkeypatch.setattr(config, "REPO", repo)
    assert capture.main(_argv(installation, kind, output)) == 1
    assert not output.parent.exists()


def test_changed_retained_ast_fails_without_creating_candidate(sandbox, native_inputs):
    repo, installation, _ = sandbox
    source = installation / "game" / STRATEGY
    source.write_text(native_inputs[STRATEGY].replace("value = 2", "value = 3"), encoding="utf-8")
    output = repo / "tools/out/capture/retentions.json"
    assert capture.main(_argv(installation, "retentions-native-subset", output)) == 1
    assert not output.parent.exists()


def test_unknown_hook_scope_fails_without_creating_candidate(sandbox, native_inputs):
    repo, installation, _ = sandbox
    source = installation / "game/common/on_actions/00_code_on_actions.txt"
    source.write_text(
        source.read_text(encoding="utf-8").replace("Root = Country", "Root = State"),
        encoding="utf-8",
    )
    output = repo / "tools/out/capture/compatibility.json"
    assert capture.main(_argv(installation, "compatibility", output)) == 1
    assert not output.parent.exists()


def test_hook_at_first_line_cannot_borrow_country_comment_from_end(sandbox, native_inputs):
    repo, installation, _ = sandbox
    source = installation / "game/common/on_actions/00_code_on_actions.txt"
    source.write_text(
        source.read_text(encoding="utf-8").removeprefix("# Root = Country\n")
        + "\n# Root = Country\n",
        encoding="utf-8",
    )
    output = repo / "tools/out/capture/compatibility.json"
    assert capture.main(_argv(installation, "compatibility", output)) == 1
    assert not output.parent.exists()


def test_output_parent_redirect_is_rejected_without_symlink_privileges(sandbox, monkeypatch):
    repo, installation, verified = sandbox
    output = repo / "tools/out/capture/parameters.json"
    actual_resolve = Path.resolve

    def redirected_resolve(path, *args, **kwargs):
        if path == output:
            return repo / "research/situated/1.15.0/inventory-parameters.json"
        return actual_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", redirected_resolve)
    assert capture.main(_argv(installation, "parameters", output)) == 1
    assert verified == []
    assert not output.parent.exists()


@pytest.mark.parametrize("kind", KINDS)
def test_source_redirect_fails_even_after_installation_identity_check(
    sandbox, native_inputs, monkeypatch, kind
):
    repo, installation, verified = sandbox
    source = installation / "game" / (TECHNOLOGY if kind == "technology-catalog" else STRATEGY)
    actual_resolve = Path.resolve

    def redirected_resolve(path, *args, **kwargs):
        if path == source:
            return repo / "elsewhere.txt"
        return actual_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", redirected_resolve)
    suffix = ".toml" if kind == "technology-catalog" else ".json"
    output = repo / "tools/out/capture" / (kind + suffix)
    assert capture.main(_argv(installation, kind, output)) == 1
    assert verified == [installation]
    assert not output.parent.exists()


def test_new_technology_consumer_requires_review_before_writing(sandbox, native_inputs):
    repo, installation, _ = sandbox
    source = installation / "game" / TECHNOLOGY
    source.write_text(
        native_inputs[TECHNOLOGY] + "new_native = { ai_weight = { value = 1 } }", encoding="utf-8"
    )
    output = repo / "tools/out/capture/technology.toml"
    assert capture.main(_argv(installation, "technology-catalog", output)) == 1
    assert not output.parent.exists()
