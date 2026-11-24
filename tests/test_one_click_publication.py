"""Publication retry and drift tests using disposable files and a fake GitHub."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from pdx import cli, config, distribution
from pdx.publishing import local, runner
from pdx.publishing.github import GitHubClient
from pdx.publishing.identity import ReleaseIdentity
from pdx.publishing.ledger import open_ledger
from pdx.publishing.local import install, tree, tree_digest

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


@pytest.fixture
def bundle(tmp_path: Path) -> runner.FrozenPackage:
    archive = distribution.write_zip(
        {
            "common/example.txt": "example = yes\n",
            distribution.METADATA_NAME: json.dumps(
                {
                    "id": distribution.MOD_ID,
                    "name": "Situated AI",
                    "version": distribution.RELEASE_VERSION,
                    "supported_game_version": "1.15.2",
                    "short_description": "example",
                    "picture": "thumbnail.png",
                    "tags": [],
                    "relationships": [],
                }
            ),
        },
        tmp_path / "test.zip",
        generation=distribution.generation_contract(),
    )
    return runner._read_bundle(archive.read_bytes(), distribution.RELEASE_VERSION)


@pytest.fixture
def identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ReleaseIdentity:
    repo = tmp_path / "source"
    repo.mkdir()

    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(repo), *args], encoding="utf-8").strip()

    git("init", "-b", "main")
    git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--allow-empty",
        "-m",
        "fixture",
    )
    monkeypatch.setattr(config, "REPO", repo)
    monkeypatch.setattr(GitHubClient, "check_public_source", lambda _client, _commit: None)
    root = tmp_path / "mod"
    root.mkdir()
    return ReleaseIdentity(
        version=distribution.RELEASE_VERSION,
        tag=f"v{distribution.RELEASE_VERSION}",
        commit=git("rev-parse", "HEAD"),
        github_repo="Example/Mod",
        channels=("local",),
        local_root=root,
        local_previous_sha256="absent",
        publication_dir=tmp_path / "release",
    )


class FakeGitHub(GitHubClient):
    def __init__(self, identity: ReleaseIdentity) -> None:
        super().__init__(identity.github_repo)
        self.tag = identity.tag
        self.source_commit = identity.commit
        self.remote_tag: str | None = None
        self.release: dict[str, Any] | None = None
        self.blobs: dict[int, bytes] = {}
        self.mutations: list[str] = []
        self.lose_upload_response = False

    def _api(
        self,
        resource: str,
        *,
        method: str = "GET",
        data: Mapping[str, object] | bytes | None = None,
        **options: Any,
    ) -> Any:
        if method != "GET":
            self.mutations.append(f"{method} {resource}")
        if resource == "":
            return {
                "full_name": self.repo,
                "visibility": "public",
                "permissions": {"push": True},
            }, {"x-oauth-scopes": "repo"}
        if resource == f"compare/{self.source_commit}...main":
            return {"status": "identical"}
        if resource == f"git/ref/tags/{self.tag}":
            return (
                {
                    "ref": f"refs/tags/{self.tag}",
                    "object": {"type": "commit", "sha": self.remote_tag},
                }
                if self.remote_tag
                else None
            )
        if resource == "git/refs":
            assert isinstance(data, dict)
            self.remote_tag = str(data["sha"])
            return {}
        if resource == "releases?per_page=100":
            return [[self.release]] if self.release is not None else [[]]
        if resource == "releases" and method == "POST":
            assert isinstance(data, dict)
            self.release = {"id": 42, "assets": [], **data}
            return self.release
        if resource.startswith("releases/assets/"):
            assert options["binary"] is True
            return self.blobs[int(resource.rsplit("/", maxsplit=1)[-1])]
        if resource == "releases/42" and method == "PATCH":
            assert self.release is not None
            self.release["draft"] = False
            return self.release
        raise AssertionError(resource)

    def _upload(self, release_id: int, name: str, raw: bytes) -> None:
        assert self.release is not None
        assert release_id == self.release["id"]
        self.mutations.append(f"upload {name}")
        asset_id = len(self.blobs) + 1
        self.blobs[asset_id] = raw
        self.release["assets"].append({"id": asset_id, "name": name, "state": "uploaded"})
        if self.lose_upload_response:
            self.lose_upload_response = False
            raise RuntimeError("simulated lost upload response")


def test_github_reconciles_lost_upload_and_verifies_original_bytes(identity, bundle):
    gh = FakeGitHub(identity)
    gh.lose_upload_response = True
    checkpoints: list[Mapping[str, object]] = []
    arguments = {
        "tag": identity.tag,
        "commit": identity.commit,
        "files": bundle.assets,
        "draft_body": "release identity",
        "checkpoint": checkpoints.append,
    }
    with pytest.raises(RuntimeError, match="lost upload"):
        gh.publish(**arguments)
    assert checkpoints[-1]["status"] == "uploading_asset"
    assert gh.publish(**arguments, previous=checkpoints[-1])["status"] == "verified"
    assert gh.mutations == [
        "POST git/refs",
        "POST releases",
        f"upload {bundle.name}",
        f"upload {bundle.name}.sha256",
        "PATCH releases/42",
    ]
    gh.publish(**arguments)
    assert len(gh.mutations) == 5
    gh.blobs[1] = b"external drift"
    with pytest.raises(ValueError, match="附件字节不同"):
        gh.publish(**arguments)
    assert len(gh.mutations) == 5


def test_github_http_transport_preserves_body_length_type_and_exact_bytes(monkeypatch, bundle):
    client = GitHubClient("Example/Mod")
    records: list[tuple[list[str], bytes]] = []

    def capture(arguments, payload):
        records.append((arguments, payload))
        return subprocess.CompletedProcess(arguments, 0, b"{}", b"")

    monkeypatch.setattr(client, "_run", capture)
    for name, raw in bundle.assets.items():
        client._upload(42, name, raw)
    client._api("releases", method="POST", data={"body": "发布"})
    for index, (name, raw) in enumerate(bundle.assets.items()):
        arguments, payload = records[index]
        assert (
            arguments[0]
            == f"https://uploads.github.com/repos/Example/Mod/releases/42/assets?name={name}"
        )
        media = "application/zip" if name.endswith(".zip") else "text/plain; charset=utf-8"
        assert arguments[1:] == [
            "--method",
            "POST",
            "--input",
            "-",
            "--header",
            f"Content-Type: {media}",
            "--header",
            f"Content-Length: {len(raw)}",
        ]
        assert payload == raw
    arguments, payload = records[-1]
    assert "Content-Type: application/json; charset=utf-8" in arguments
    assert f"Content-Length: {len(payload)}" in arguments
    assert json.loads(payload) == {"body": "发布"}


def test_github_starter_asset_blocks_with_release_and_asset_identity(identity, bundle):
    gh = FakeGitHub(identity)
    gh.remote_tag = identity.commit
    gh.release = {
        "id": 42,
        "assets": [{"id": 18, "name": bundle.name, "state": "starter"}],
        "tag_name": identity.tag,
        "draft": True,
        "prerelease": False,
        "body": "release identity",
        "target_commitish": identity.commit,
    }
    with pytest.raises(ValueError, match=r"Release 42 的附件 18.*starter"):
        gh.inspect(identity.tag, identity.commit, bundle.assets, owned_draft="release identity")
    assert gh.mutations == []


def test_existing_git_tag_or_foreign_draft_is_not_rewritten(identity, bundle):
    gh = FakeGitHub(identity)
    gh.remote_tag = "0" * 40
    with pytest.raises(ValueError, match="拒绝移动"):
        gh.inspect(identity.tag, identity.commit, bundle.assets)
    gh.remote_tag = identity.commit
    gh.release = {
        "id": 9,
        "assets": [],
        "tag_name": identity.tag,
        "draft": True,
        "prerelease": False,
        "body": "foreign",
    }
    with pytest.raises(ValueError, match="已有其他"):
        gh.inspect(identity.tag, identity.commit, bundle.assets, owned_draft="own")
    assert gh.mutations == []


def test_replaced_github_draft_cannot_receive_assets(identity, bundle):
    gh = FakeGitHub(identity)
    gh.remote_tag = identity.commit
    gh.release = {
        "id": 99,
        "assets": [],
        "tag_name": identity.tag,
        "draft": True,
        "prerelease": False,
        "body": "release identity",
        "target_commitish": identity.commit,
    }
    with pytest.raises(ValueError, match="ID 发生变化"):
        gh.publish(
            tag=identity.tag,
            commit=identity.commit,
            files=bundle.assets,
            draft_body="release identity",
            checkpoint=lambda _value: None,
            previous={"status": "uploading_asset", "release_id": 42},
        )
    assert gh.mutations == []


def test_single_run_applies_selected_channels_then_reads_back_and_resumes(
    tmp_path, monkeypatch, identity, bundle
):
    identity = replace(identity, channels=("github", "local"))
    gh = FakeGitHub(identity)
    gh.lose_upload_response = True
    monkeypatch.setattr(runner, "GitHubClient", lambda _repo: gh)
    monkeypatch.setattr(runner, "_build", lambda _version: bundle)
    validated_snapshots = []

    def validate_snapshot(path):
        validated_snapshots.append(path.read_bytes())

    monkeypatch.setattr(distribution, "validate_package", validate_snapshot)
    assert identity.local_root is not None
    target = identity.local_root / distribution.INSTALL_DIRECTORY_NAME
    first = runner.run_release(identity)
    assert first["status"] == "partial"
    assert not target.exists()
    second = runner.run_release(identity)
    assert second["status"] == "verified"
    assert identity.publication_dir is not None
    assert (identity.publication_dir / bundle.name).read_bytes() == bundle.archive
    assert (target / distribution.MANIFEST_NAME).read_bytes() == bundle.files[
        distribution.MANIFEST_NAME
    ]
    again = runner.run_release(identity)
    assert again["status"] == "verified"
    assert len(gh.mutations) == 5
    (target / "user-change.txt").write_bytes(b"user edit")
    assert runner.run_release(identity)["status"] == "blocked"
    assert (target / "user-change.txt").read_bytes() == b"user edit"
    assert validated_snapshots == [bundle.archive] * 3


def test_preflight_block_prevents_any_channel_mutation(monkeypatch, identity, bundle):
    identity = replace(identity, channels=("github", "local"), local_previous_sha256="f" * 64)
    gh = FakeGitHub(identity)
    monkeypatch.setattr(runner, "GitHubClient", lambda _repo: gh)
    monkeypatch.setattr(runner, "_build", lambda _version: bundle)
    result = runner.run_release(identity)
    assert result["status"] == "blocked"
    assert gh.mutations == []


@pytest.mark.parametrize("channel", ["github", "workshop"])
def test_known_payload_blocks_public_writes_even_after_package_metadata_changes(
    monkeypatch, identity, bundle, channel
):
    identity = replace(identity, channels=(channel,))
    if channel == "workshop":
        identity = replace(identity, workshop_item="123", workshop_owner="76561198000000001")
    historical_path = next(
        path
        for path in runner._RETAINED_VANILLA_PAYLOADS.values()
        if path != "common/ai_strategies/00_default_strategy.txt"
    )
    retained = b"\xef\xbb\xbfsynthetic = yes\n"
    monkeypatch.setitem(
        runner._RETAINED_VANILLA_PAYLOADS, hashlib.sha256(retained).hexdigest(), historical_path
    )
    assert identity.publication_dir is not None
    version_metadata = bundle.files[distribution.METADATA_NAME]
    repacked = distribution.write_zip(
        {
            distribution.METADATA_NAME: version_metadata.replace(b"example", b"changed metadata"),
            "common/renamed.txt": retained,
            "common/independent.txt": "independent = yes\n",
        },
        identity.publication_dir.parent / "repacked.zip",
        generation=distribution.generation_contract(),
    )
    repacked_bundle = runner._read_bundle(repacked.read_bytes(), identity.version)
    assert repacked_bundle.sha256 != bundle.sha256
    monkeypatch.setattr(runner, "_build", lambda _version: repacked_bundle)
    monkeypatch.setattr(distribution, "validate_package", lambda _path: None)

    def fail_if_channel_reached(*_args, **_kwargs):
        pytest.fail("A blocked payload reached channel preflight or apply")

    with monkeypatch.context() as apply:
        apply.setattr(runner, "_preflight", fail_if_channel_reached)
        apply.setattr(runner, "_apply_channels", fail_if_channel_reached)
        for _ in range(2):
            result = runner.run_release(identity)
            assert result["status"] == "blocked"
            error = result["error"]
            assert isinstance(error, str)
            assert "common/renamed.txt" in error
            assert historical_path in error

    receipt = identity.publication_dir / "publication.json"
    before = receipt.read_bytes()
    monkeypatch.setattr(runner, "_preflight", lambda *_args, **_kwargs: {"status": "ready"})
    monkeypatch.setattr(runner, "_apply_channels", fail_if_channel_reached)
    planned = runner.plan_release(identity)
    assert planned["status"] == "planned"
    assert planned["package"] == repacked_bundle.receipt()
    assert receipt.read_bytes() == before


def test_original_bytes_at_a_registered_path_follow_existing_publication_checks(
    monkeypatch, identity, bundle
):
    identity = replace(identity, channels=("github",))
    historical_path = next(iter(runner._RETAINED_VANILLA_PAYLOADS.values()))
    assert identity.publication_dir is not None
    archive = distribution.write_zip(
        {
            distribution.METADATA_NAME: bundle.files[distribution.METADATA_NAME],
            historical_path: "independently_authored = yes\n",
        },
        identity.publication_dir.parent / "original.zip",
        generation=distribution.generation_contract(),
    )
    original = runner._read_bundle(archive.read_bytes(), identity.version)
    gh = FakeGitHub(identity)
    monkeypatch.setattr(runner, "GitHubClient", lambda _repo: gh)
    monkeypatch.setattr(runner, "_build", lambda _version: original)
    assert runner.run_release(identity)["status"] == "verified"
    assert gh.mutations


def test_bad_local_staging_blocks_before_github_write(monkeypatch, identity, bundle):
    identity = replace(identity, channels=("github", "local"))
    gh = FakeGitHub(identity)
    monkeypatch.setattr(runner, "GitHubClient", lambda _repo: gh)
    monkeypatch.setattr(runner, "_build", lambda _version: bundle)
    assert identity.local_root is not None
    switch = identity.local_root / f".situated-ai-publish-{identity.digest()[:24]}"
    switch.mkdir()
    staging = switch / "staging"
    staging.mkdir()
    (staging / "unexpected").write_bytes(b"keep me")
    receipt = runner.run_release(identity)
    assert receipt["status"] == "blocked"
    assert gh.mutations == []
    assert (staging / "unexpected").read_bytes() == b"keep me"


def test_frozen_zip_is_production_validated_when_receipt_is_replaced(monkeypatch, identity, bundle):
    assert identity.publication_dir is not None
    build = replace(bundle, archive=b"tampered bytes")
    with open_ledger(identity.publication_dir, identity.digest()) as ledger:
        (ledger.root / bundle.name).write_bytes(build.archive)
        ledger.data["package"] = build.receipt()
        ledger.write()

    def reject(path: Path) -> None:
        assert path.read_bytes() == build.archive
        raise ValueError("production source mismatch")

    monkeypatch.setattr(distribution, "validate_package", reject)
    receipt = runner.run_release(identity)
    assert receipt["status"] == "blocked"
    assert receipt["error"] == "production source mismatch"


def test_planning_has_no_external_writes(monkeypatch, identity, bundle):
    monkeypatch.setattr(runner, "_build", lambda _version: bundle)
    result = runner.plan_release(identity)
    assert result["status"] == "planned"
    assert identity.publication_dir is not None
    assert not identity.publication_dir.exists()
    assert identity.local_root is not None
    assert not (identity.local_root / distribution.INSTALL_DIRECTORY_NAME).exists()
    cli_result = CliRunner().invoke(cli.app, ["publish", "--apply"])
    assert cli_result.exit_code == cli.EXIT_FAILED
    assert "必须显式选择" in cli_result.output


def test_github_notes_are_bound_to_release_and_verified_on_resume(
    tmp_path, monkeypatch, identity, bundle
):
    gh = FakeGitHub(identity)
    gh.lose_upload_response = True
    monkeypatch.setattr(runner, "GitHubClient", lambda _repo: gh)
    monkeypatch.setattr(runner, "_build", lambda _version: bundle)
    monkeypatch.setattr(distribution, "validate_package", lambda _path: None)

    notes = "## 实测记录\r\n\r\n- 单人模式\r\n"
    original = notes.encode("utf-8")
    path = tmp_path / "notes.md"
    path.write_bytes(original)
    arguments = [
        "publish",
        "--channel",
        "github",
        "--github-repo",
        identity.github_repo,
        "--publication-dir",
        str(identity.publication_dir),
        "--github-notes-file",
        str(path),
    ]
    apply = [*arguments, "--commit", identity.commit, "--apply"]
    cli_runner = CliRunner()
    plan = cli_runner.invoke(cli.app, arguments)
    assert plan.exit_code == 0, plan.output
    declared = json.loads(plan.output)["identity"]
    assert declared["github_notes_sha256"] == hashlib.sha256(original).hexdigest()
    assert declared["commit"] == identity.commit
    assert gh.mutations == []

    checked_apply = [*apply, "--expected-github-notes-sha256", declared["github_notes_sha256"]]
    path.write_bytes(original.replace(b"\r\n", b"\n"))
    replaced = cli_runner.invoke(cli.app, checked_apply)
    assert replaced.exit_code == cli.EXIT_FAILED
    assert "GitHub 发布说明的 SHA-256 与预审摘要不同" in replaced.output
    assert gh.mutations == []
    assert identity.publication_dir is not None
    assert not identity.publication_dir.exists()

    path.write_bytes(original)
    first = cli_runner.invoke(cli.app, checked_apply)
    assert first.exit_code == cli.EXIT_FAILED
    assert gh.release is not None
    assert gh.release["draft"] is True
    expected_body = (
        f"Situated AI {identity.version} 正式版本。\n\n"
        f"源提交 `{identity.commit}`。Mod ZIP SHA-256 `{bundle.sha256}`。\n\n{notes}"
    )
    assert gh.release["body"] == expected_body
    assert json.loads(first.output)["identity"] == declared

    writes = gh.mutations.copy()
    path.write_bytes(original + b"\n")
    changed = cli_runner.invoke(cli.app, apply)
    assert changed.exit_code == cli.EXIT_FAILED
    assert "已有发布收据绑定了不同的发布身份" in changed.output
    assert gh.mutations == writes

    path.write_bytes(original)
    assert cli_runner.invoke(cli.app, arguments).exit_code == 0
    resumed = cli_runner.invoke(cli.app, checked_apply)
    assert resumed.exit_code == 0, resumed.output
    assert gh.release["draft"] is False
    assert gh.release["body"] == expected_body
    assert json.loads(resumed.output)["status"] == "verified"

    writes = gh.mutations.copy()
    gh.release["body"] = "modified on GitHub"
    drifted = cli_runner.invoke(cli.app, apply)
    assert drifted.exit_code == cli.EXIT_FAILED
    assert "正文与冻结发布说明不同" in drifted.output
    assert gh.mutations == writes


def test_local_second_rename_failure_restores_original(tmp_path, identity, bundle, monkeypatch):
    root = identity.local_root
    assert root is not None
    target = root / distribution.INSTALL_DIRECTORY_NAME
    target.mkdir()
    (target / "empty").mkdir()
    (target / "old.txt").write_bytes(b"\xef\xbb\xbfprior\r\n")
    old = tree(target)
    previous = tree_digest(old)
    evidence = tmp_path / "local-evidence"
    evidence.mkdir()
    state: dict[str, object] = {}
    rename = local._rename_exclusive

    def rename_failure(path: Path, destination: Path) -> None:
        if path.name == "staging":
            raise OSError("forced swap failure")
        rename(path, destination)

    monkeypatch.setattr(local, "_rename_exclusive", rename_failure)
    with pytest.raises(OSError, match="forced swap failure"):
        install(bundle.files, root, previous, evidence, "fixture", {}, state.update)
    assert tree(target) == old
    assert tree(evidence / "local-previous") == old
    monkeypatch.setattr(local, "_rename_exclusive", rename)
    receipt = install(bundle.files, root, previous, evidence, "fixture", state, state.update)
    assert receipt["status"] == "verified"
    assert tree(evidence / "local-previous") == old


def test_local_recovers_after_process_dies_between_renames(tmp_path, identity, bundle, monkeypatch):
    root = identity.local_root
    assert root is not None
    target = root / distribution.INSTALL_DIRECTORY_NAME
    target.mkdir()
    (target / "old.txt").write_bytes(b"prior")
    previous = tree_digest(tree(target))
    evidence = tmp_path / "local-evidence"
    evidence.mkdir()
    state: dict[str, object] = {}
    rename = local._rename_exclusive

    def interrupted_rename(path: Path, destination: Path) -> None:
        if path.name == "staging":
            raise KeyboardInterrupt
        rename(path, destination)

    monkeypatch.setattr(local, "_rename_exclusive", interrupted_rename)
    with pytest.raises(KeyboardInterrupt):
        install(bundle.files, root, previous, evidence, "fixture", {}, state.update)
    assert not target.exists()
    monkeypatch.setattr(local, "_rename_exclusive", rename)
    receipt = install(bundle.files, root, previous, evidence, "fixture", state, state.update)
    assert receipt["status"] == "verified"
    assert (target / "common/example.txt").read_bytes() == bundle.files["common/example.txt"]


def test_exclusive_rename_preserves_an_existing_empty_destination(tmp_path):
    source = tmp_path / "staging"
    source.mkdir()
    (source / "frozen.txt").write_bytes(b"release")
    destination = tmp_path / "external"
    destination.mkdir()
    with pytest.raises(FileExistsError):
        local._rename_exclusive(source, destination)
    assert not list(destination.iterdir())
    assert (source / "frozen.txt").read_bytes() == b"release"


@pytest.mark.parametrize("persist_activated", [False, True])
def test_local_rejects_user_restoring_old_tree_after_activation(
    tmp_path, identity, bundle, monkeypatch, persist_activated
):
    root = identity.local_root
    assert root is not None
    target = root / distribution.INSTALL_DIRECTORY_NAME
    target.mkdir()
    (target / "old.txt").write_bytes(b"prior")
    previous = tree_digest(tree(target))
    evidence = tmp_path / "local-evidence"
    evidence.mkdir()
    state: dict[str, object] = {}

    def stop_after_activation(checkpoint: Mapping[str, object]) -> None:
        if checkpoint["status"] == "activated":
            if persist_activated:
                state.update(checkpoint)
            raise KeyboardInterrupt
        state.update(checkpoint)

    with pytest.raises(KeyboardInterrupt):
        install(bundle.files, root, previous, evidence, "fixture", {}, stop_after_activation)
    assert tree_digest(tree(target)) == state["release_tree_sha256"]
    assert (root / ".situated-ai-publish-fixture" / "previous" / "old.txt").read_bytes() == b"prior"
    target.rename(root / "user-moved-release")
    target.mkdir()
    (target / "old.txt").write_bytes(b"prior")
    with pytest.raises(ValueError, match="拒绝再次替换"):
        install(bundle.files, root, previous, evidence, "fixture", state, state.update)
    assert tree_digest(tree(target)) == previous


def test_local_resumes_cleanup_after_durable_activation(tmp_path, identity, bundle):
    root = identity.local_root
    assert root is not None
    target = root / distribution.INSTALL_DIRECTORY_NAME
    target.mkdir()
    (target / "old.txt").write_bytes(b"prior")
    previous = tree_digest(tree(target))
    evidence = tmp_path / "local-evidence"
    evidence.mkdir()
    state: dict[str, object] = {}

    def stop_after_activation(checkpoint: Mapping[str, object]) -> None:
        state.update(checkpoint)
        if checkpoint["status"] == "activated":
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        install(bundle.files, root, previous, evidence, "fixture", {}, stop_after_activation)
    assert state["status"] == "activated"
    assert (
        install(bundle.files, root, previous, evidence, "fixture", state, state.update)["status"]
        == "verified"
    )
    assert (evidence / "local-previous" / "old.txt").read_bytes() == b"prior"
    assert not (root / ".situated-ai-publish-fixture").exists()


def test_publication_ledger_serializes_processes(tmp_path):
    root = tmp_path / "evidence"
    with (
        open_ledger(root, "x" * 64),
        pytest.raises(ValueError, match="另一发布进程"),
        open_ledger(root, "x" * 64),
    ):
        pytest.fail("concurrent access succeeded")
    with open_ledger(root, "x" * 64) as opened:
        assert opened.data["status"] == "preparing"
