"""A4 delivery checks use offline transports and real local byte fixtures."""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import UTC, datetime
from email.message import Message
from types import SimpleNamespace

import pytest

from pdx import config, distribution, publishing_contract

HEAD = "a" * 40
MERGE = "b" * 40
MAIN = "c" * 40


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value) + "\n").encode()
    path.write_bytes(raw)
    return {"path": path.name, "sha256": hashlib.sha256(raw).hexdigest()}


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    delivery = importlib.import_module("tools.ci.a4_delivery")
    materials = config.REPO / "docs/publishing"
    descriptions = publishing_contract.load_descriptions(materials)
    item = publishing_contract.publication_config(materials)["published_file_id"]
    monkeypatch.setattr(delivery, "load_descriptions", lambda _path: descriptions)
    monkeypatch.setattr(delivery, "publication_config", lambda _path: {"published_file_id": item})
    monkeypatch.setattr(delivery.deployment, "assert_game_stopped", lambda: None)
    data = {
        ".metadata/metadata.json": b'{"id":"situated-ai","version":"4.0.0"}\n',
        "README.md": b"release fixture\n",
        "common/fixture.txt": b"\xef\xbb\xbfvalue = yes\n",
    }
    manifest = {
        "schema": 2,
        "mod_id": "situated-ai",
        "install_directory": "Situated AI",
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in data.items()},
    }
    data["DISTRIBUTION-MANIFEST.json"] = json.dumps(manifest).encode()
    run = tmp_path / "tools/out/publish-run"
    run.mkdir(parents=True)
    archive = run / "package.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        for name, raw in sorted(data.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            zipped.writestr(info, raw)
    package = archive.read_bytes()
    digest = hashlib.sha256(package).hexdigest()
    expected_files = {name: hashlib.sha256(raw).hexdigest() for name, raw in data.items()}
    userdir = tmp_path / "user"
    target = userdir / "mod/Situated AI"
    for folder in (target, run / "content"):
        for name, raw in data.items():
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
    receipt = {
        "schema": 1,
        "status": "succeeded",
        "execute": True,
        "target": "all",
        "receipt": str(run / "receipt.json"),
        "evidence": "publication_operation",
        "behavior_quality": "not_evaluated",
        "started_at": "2026-11-06T00:00:00+00:00",
        "finished_at": "2026-11-06T00:01:00+00:00",
        "package": {"sha256": digest, "manifest": manifest, "files": expected_files},
        "descriptions": {
            lang: {
                "sha256": hashlib.sha256(body.encode()).hexdigest(),
                "utf8_bytes": len(body.encode()),
            }
            for lang, body in descriptions.items()
        },
        "operations": [
            {
                "name": "local",
                "status": "succeeded",
                "result": {
                    "status": "succeeded",
                    "target": str(target),
                    "backup": None,
                    "file_count": len(data),
                },
            },
            {
                "name": "workshop",
                "status": "succeeded",
                "result": {
                    "result": 1,
                    "item_id": item,
                    "submitted": True,
                    "content_verified": "steam_callback",
                    "remote_bytes_verified": False,
                },
            },
            *({"name": f"description:{lang}", "status": "unchanged"} for lang in descriptions),
        ],
    }
    write_json(run / "receipt.json", receipt)
    recovery_ref = write_json(
        tmp_path / "recovery.json",
        {
            "schema": 1,
            "target": str(target),
            "backup": None,
            "backup_files": {},
            "reason": "fresh_install",
        },
    )
    cleanup_ref = write_json(
        tmp_path / "cleanup.json",
        {"schema": 1, "status": "complete", "absent": [], "remaining": []},
    )
    request = {
        "schema": 1,
        "mode": "offline_fixture",
        "repository": "owner/repo",
        "pull_request": 7,
        "base": "main",
        "head_sha": HEAD,
        "merge_sha": MERGE,
        "main_sha": MAIN,
        "tag": "v4.0.0",
        "version": "v4.0.0",
        "asset_name": "situated-ai-4.0.0.zip",
        "checksum_name": "situated-ai-4.0.0.zip.sha256",
        "run_dir": "tools/out/publish-run",
        "userdir": str(userdir),
        "local_target": str(target),
        "lock_paths": [
            str(userdir / ".situated-ai-publish.lock"),
            str(userdir / ".situated-ai-deploy.lock"),
        ],
        "cleanup_paths": [],
        "expected_languages": list(descriptions),
        "descriptions": descriptions,
        "allowed_followup_paths": [],
        "production_snapshot": {"src/pdx/fixture.py": "d" * 64},
        "recovery": recovery_ref,
        "cleanup": cleanup_ref,
    }
    routes = {
        "repository": {"id": 2, "full_name": "owner/repo", "default_branch": "main"},
        "pr:7": {
            "number": 7,
            "merged": True,
            "merged_at": "2026-11-06T00:00:00Z",
            "base": {"ref": "main", "repo": {"full_name": "owner/repo", "id": 2}},
            "head": {"sha": HEAD},
            "merge_commit_sha": MERGE,
        },
        "main": {"commit": {"sha": MAIN}},
        "protection": {
            "required_status_checks": {"checks": [{"context": "tests", "app_id": 15368}]}
        },
        "rules": [],
        f"checks:{HEAD}": [
            {
                "id": 1,
                "head_sha": HEAD,
                "name": "tests",
                "app": {"id": 15368},
                "status": "completed",
                "conclusion": "success",
            }
        ],
        f"checks:{MERGE}": [
            {
                "id": 2,
                "head_sha": MERGE,
                "name": "tests",
                "app": {"id": 15368},
                "status": "completed",
                "conclusion": "success",
            }
        ],
        "tag:v4.0.0": {"object": {"type": "commit", "sha": MERGE}},
        "release:v4.0.0": {
            "id": 4,
            "tag_name": "v4.0.0",
            "draft": False,
            "prerelease": False,
            "assets": [
                {
                    "id": 10,
                    "name": request["asset_name"],
                    "size": len(package),
                    "state": "uploaded",
                },
                {"id": 11, "name": request["checksum_name"], "size": 0, "state": "uploaded"},
            ],
        },
        "asset:10": package,
        "asset:11": f"{digest}  {request['asset_name']}\n".encode(),
    }
    routes["release:v4.0.0"]["assets"][1]["size"] = len(routes["asset:11"])
    git = SimpleNamespace(
        live=False,
        remote_repository=lambda: "owner/repo",
        snapshot=lambda _commit: request["production_snapshot"],
        is_ancestor=lambda a, b: (a, b) in {(HEAD, MERGE), (MERGE, MAIN)},
        verify_current=lambda _merge, _snapshot, **_kwargs: None,
    )
    observed = {
        "item_id": item,
        "owner_matches": True,
        "creator_app_id": config.APP_ID,
        "consumer_app_id": config.APP_ID,
        "descriptions": descriptions.copy(),
    }
    workshop = SimpleNamespace(live=False, inspect=lambda _languages: observed)
    monkeypatch.setattr(distribution, "validate_package", lambda _archive: manifest)
    return SimpleNamespace(
        delivery=delivery,
        root=tmp_path,
        request=request,
        routes=routes,
        git=git,
        workshop=workshop,
        observed=observed,
        receipt=receipt,
        run=run,
        target=target,
        data=data,
        authorized_userdir=userdir,
    )


def verify(c):
    return c.delivery.verify_delivery(
        c.root,
        c.request,
        github=c.routes,
        git=c.git,
        workshop=c.workshop,
        authorized_userdir=c.authorized_userdir,
    )


def test_offline_complete_identity_chain_never_signs_actual_delivery(candidate):
    result = verify(candidate)
    assert result["status"] == "verified"
    assert result["delivery_complete"] is False
    assert result["remote_bytes_verified"] is False
    assert result["language_count"] == 11


@pytest.mark.parametrize(
    "fault",
    [
        "repo",
        "base",
        "head",
        "unmerged",
        "merge",
        "main",
        "required_empty",
        "required_missing",
        "check_app",
        "check_sha",
        "check_missing",
        "check_failed",
        "check_skipped",
        "draft",
        "prerelease",
        "tag",
        "asset_name",
        "asset_size",
        "checksum",
        "zip",
        "tree",
        "content",
        "partial",
        "callback",
        "language",
        "body",
        "unchanged_body",
        "lock",
        "recovery",
        "cleanup",
    ],
)
def test_each_broken_identity_or_byte_link_fails_closed(candidate, fault):
    c = candidate
    if fault == "repo":
        c.routes["repository"]["full_name"] = "wrong/repo"
    elif fault == "base":
        c.routes["pr:7"]["base"]["ref"] = "other"
    elif fault == "head":
        c.routes["pr:7"]["head"]["sha"] = "f" * 40
    elif fault == "unmerged":
        c.routes["pr:7"]["merged"] = False
    elif fault == "merge":
        c.routes["pr:7"]["merge_commit_sha"] = "f" * 40
    elif fault == "main":
        c.git.is_ancestor = lambda _a, _b: False
    elif fault == "required_empty":
        c.routes["protection"]["required_status_checks"]["checks"] = []
    elif fault == "required_missing":
        c.routes["protection"] = {}
    elif fault == "check_app":
        c.routes[f"checks:{MERGE}"][0]["app"]["id"] = 4
    elif fault == "check_sha":
        c.routes[f"checks:{MERGE}"][0]["head_sha"] = HEAD
    elif fault == "check_missing":
        c.routes[f"checks:{MERGE}"] = []
    elif fault in {"check_failed", "check_skipped"}:
        c.routes[f"checks:{MERGE}"][0]["conclusion"] = fault.removeprefix("check_")
    elif fault in {"draft", "prerelease"}:
        c.routes["release:v4.0.0"][fault] = True
    elif fault == "tag":
        c.routes["tag:v4.0.0"]["object"]["sha"] = HEAD
    elif fault == "asset_name":
        c.routes["release:v4.0.0"]["assets"][0]["name"] = "wrong.zip"
    elif fault == "asset_size":
        c.routes["release:v4.0.0"]["assets"][0]["size"] += 1
    elif fault == "checksum":
        c.routes["asset:11"] = b"0" * 64 + b"  wrong.zip\n"
    elif fault == "zip":
        c.routes["asset:10"] = b"bad zip"
    elif fault == "tree":
        (c.target / "extra.txt").write_bytes(b"extra")
    elif fault == "content":
        (c.run / "content/README.md").write_bytes(b"changed")
    elif fault == "partial":
        c.receipt["operations"][0]["status"] = "uncertain"
    elif fault == "callback":
        c.receipt["operations"][1]["result"]["item_id"] = 1
    elif fault == "language":
        c.observed["descriptions"].pop("english")
    elif fault in {"body", "unchanged_body"}:
        c.observed["descriptions"]["english"] = "different"
    elif fault == "lock":
        (c.root / "user/.situated-ai-publish.lock").write_text("123")
    elif fault == "recovery":
        (c.root / "recovery.json").write_bytes(b"changed")
    elif fault == "cleanup":
        (c.root / "cleanup.json").write_bytes(b"changed")
    write_json(c.run / "receipt.json", c.receipt)
    with pytest.raises(ValueError):
        verify(c)


def test_fixture_transport_cannot_claim_live_delivery(candidate):
    candidate.request["mode"] = "live"
    with pytest.raises(ValueError, match="live"):
        verify(candidate)


def test_live_git_reader_cannot_prove_a_different_checkout(candidate, monkeypatch):
    c = candidate
    c.request["mode"] = "live"
    monkeypatch.setattr(config, "REPO", c.root)
    monkeypatch.setattr(config, "OUT", c.run)
    monkeypatch.setattr(c.delivery.GitReader, "remote_repository", lambda _self: "owner/repo")
    github = c.delivery.GitHubReader("owner/repo")
    git = c.delivery.GitReader(c.root / "another-clone")
    workshop = c.delivery.WorkshopReader(c.observed["item_id"], c.run)
    monkeypatch.setattr(
        github,
        "get",
        lambda _route: pytest.fail("mismatched checkout must fail before network reads"),
    )
    with pytest.raises(ValueError, match="checkout"):
        c.delivery.verify_delivery(
            c.root,
            c.request,
            github=github,
            git=git,
            workshop=workshop,
            authorized_userdir=c.authorized_userdir,
        )


def test_sidecar_cannot_retarget_the_independently_authorized_userdir(candidate):
    c = candidate
    replacement = c.root / "substitute-userdir"
    new_target = replacement / "mod" / distribution.INSTALL_DIRECTORY_NAME
    new_target.parent.mkdir(parents=True)
    c.target.rename(new_target)
    c.request.update(
        userdir=str(replacement),
        local_target=str(new_target),
        lock_paths=[
            str(replacement / ".situated-ai-publish.lock"),
            str(replacement / ".situated-ai-deploy.lock"),
        ],
    )
    c.receipt["operations"][0]["result"]["target"] = str(new_target)
    write_json(c.run / "receipt.json", c.receipt)
    c.request["recovery"] = write_json(
        c.root / "recovery.json",
        {
            "schema": 1,
            "target": str(new_target),
            "backup": None,
            "backup_files": {},
            "reason": "fresh_install",
        },
    )
    with pytest.raises(ValueError, match="authorized userdir"):
        verify(c)


def test_userdir_defaults_to_config_and_accepts_independently_authorized_alternate(
    candidate, monkeypatch
):
    c = candidate
    monkeypatch.setattr(config, "USERDIR", c.root / "configured-userdir")
    with pytest.raises(ValueError, match="authorized userdir"):
        c.delivery.verify_delivery(
            c.root, c.request, github=c.routes, git=c.git, workshop=c.workshop
        )
    assert verify(c)["status"] == "verified"
    monkeypatch.setattr(config, "USERDIR", c.authorized_userdir)
    assert (
        c.delivery.verify_delivery(
            c.root, c.request, github=c.routes, git=c.git, workshop=c.workshop
        )["status"]
        == "verified"
    )


def test_annotated_tag_resolves_to_actual_commit(candidate):
    c = candidate
    c.routes["tag:v4.0.0"] = {"object": {"type": "tag", "sha": "e" * 40}}
    c.routes[f"tag_object:{'e' * 40}"] = {"object": {"type": "commit", "sha": MERGE}}
    assert verify(c)["status"] == "verified"


def test_receipt_only_followup_requires_unchanged_production(candidate):
    c = candidate
    c.git.verify_current = lambda _merge, _snapshot, **_kwargs: (_ for _ in ()).throw(
        ValueError("production drift")
    )
    with pytest.raises(ValueError, match="production drift"):
        verify(c)


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b"\xff"])
def test_delivery_json_rejects_ambiguous_or_nonfinite_data(raw):
    delivery = importlib.import_module("tools.ci.a4_delivery")
    with pytest.raises(ValueError):
        delivery.strict_json(raw)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.github.com/repos/owner/repo/../other/pulls/1",
        "https://api.github.com/repos/owner/repo/%2e%2e/other",
        "https://api.github.com/repos/owner/repo/pulls?secret=1",
        "https://api.github.com/repos/owner/repo/pulls?per_page=101",
    ],
)
def test_github_route_rejects_path_and_query_escape(url):
    delivery = importlib.import_module("tools.ci.a4_delivery")
    with pytest.raises(ValueError):
        delivery.GitHubReader("owner/repo").check_url(url, asset=False)


def test_asset_redirect_never_forwards_api_credential(monkeypatch):
    delivery = importlib.import_module("tools.ci.a4_delivery")
    requests = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    class Opener:
        def open(self, request, *, timeout):
            assert timeout <= 40
            requests.append(request)
            if len(requests) == 1:
                headers = Message()
                headers["Location"] = (
                    "https://release-assets.githubusercontent.com/github-production-release-asset/1/asset?signature=safe"
                )
                raise urllib.error.HTTPError(
                    request.full_url,
                    302,
                    "redirect",
                    headers,
                    None,
                )
            return Response(b"asset bytes")

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args: Opener())
    reader = delivery.GitHubReader("owner/repo", credential="test-secret")
    assert (
        reader.get_bytes("https://api.github.com/repos/owner/repo/releases/assets/10")
        == b"asset bytes"
    )
    assert requests[0].get_header("Authorization") == "Bearer test-secret"
    assert requests[1].get_header("Authorization") is None
    assert all(request.get_method() == "GET" for request in requests)


@pytest.mark.parametrize(
    "location",
    [
        "http://release-assets.githubusercontent.com/github-production-release-asset/1/a",
        "https://evil.test/a",
        "https://api.github.com/repos/other/repo/releases/assets/1",
    ],
)
def test_asset_redirect_rejects_unsafe_target_before_second_request(monkeypatch, location):
    delivery = importlib.import_module("tools.ci.a4_delivery")
    requests = []

    class Opener:
        def open(self, request, *, timeout):
            requests.append((request, timeout))
            headers = Message()
            headers["Location"] = location
            raise urllib.error.HTTPError(request.full_url, 302, "redirect", headers, None)

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args: Opener())
    reader = delivery.GitHubReader("owner/repo", credential="test-secret")
    with pytest.raises(ValueError) as error:
        reader.get_bytes("https://api.github.com/repos/owner/repo/releases/assets/10")
    assert "test-secret" not in str(error.value)
    assert len(requests) == 1


def test_asset_reader_enforces_actual_byte_bound(monkeypatch):
    delivery = importlib.import_module("tools.ci.a4_delivery")

    class Opener:
        def open(self, _request, *, timeout):
            assert timeout > 0
            return io.BytesIO(b"four")

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args: Opener())
    monkeypatch.setattr(delivery, "MAX_ASSET_BYTES", 3)
    with pytest.raises(ValueError, match="bound"):
        delivery.GitHubReader("owner/repo").get_bytes(
            "https://api.github.com/repos/owner/repo/releases/assets/10"
        )


def test_required_checks_pagination_is_complete(monkeypatch):
    delivery = importlib.import_module("tools.ci.a4_delivery")
    reader = delivery.GitHubReader("owner/repo")
    calls = []

    def page(route):
        calls.append(route)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(route).query)
        return {"check_runs": list(range(100)) if query["page"] == ["1"] else [100]}

    monkeypatch.setattr(reader, "get_json", page)
    assert reader.get(f"checks:{MERGE}") == list(range(101))
    assert len(calls) == 2


@pytest.mark.parametrize(
    "fault",
    [
        "missing_local",
        "missing_workshop",
        "missing_language",
        "duplicate_operation",
        "callback_remote_bytes",
        "wrong_steam_owner",
        "wrong_steam_app",
        "description_result",
        "source_body",
        "wrong_remote",
        "snapshot",
        "head_ancestry",
        "extra_rule",
        "tag_cycle",
        "lock_omission",
        "cleanup_residue",
        "zip_symlink",
        "zip_duplicate",
        "zip_bomb",
    ],
)
def test_additional_delivery_boundaries_fail_closed(candidate, fault, monkeypatch):
    c = candidate
    if fault.startswith("missing_"):
        name = {
            "missing_local": "local",
            "missing_workshop": "workshop",
            "missing_language": "description:english",
        }[fault]
        c.receipt["operations"] = [row for row in c.receipt["operations"] if row["name"] != name]
    elif fault == "duplicate_operation":
        c.receipt["operations"].append(c.receipt["operations"][0])
    elif fault == "callback_remote_bytes":
        c.receipt["operations"][1]["result"]["remote_bytes_verified"] = True
    elif fault == "wrong_steam_owner":
        c.observed["owner_matches"] = False
    elif fault == "wrong_steam_app":
        c.observed["creator_app_id"] = 4
    elif fault == "description_result":
        c.receipt["operations"][2] = {
            "name": c.receipt["operations"][2]["name"],
            "status": "succeeded",
            "result": {"readback_verified": True},
        }
    elif fault == "source_body":
        c.request["descriptions"] = {**c.request["descriptions"], "english": "changed source"}
    elif fault == "wrong_remote":
        c.git.remote_repository = lambda: "wrong/repo"
    elif fault == "snapshot":
        c.git.snapshot = lambda _commit: {"src/pdx/fixture.py": "e" * 64}
    elif fault == "head_ancestry":
        c.git.is_ancestor = lambda a, b: a == MERGE and b == MAIN
    elif fault == "extra_rule":
        c.routes["rules"] = [{"type": "required_workflows"}]
    elif fault == "tag_cycle":
        c.routes["tag:v4.0.0"] = {"object": {"type": "tag", "sha": "e" * 40}}
        c.routes[f"tag_object:{'e' * 40}"] = c.routes["tag:v4.0.0"]
    elif fault == "lock_omission":
        c.request["lock_paths"] = []
    elif fault == "cleanup_residue":
        (c.target.parent / "sitai-probe-mount").mkdir()
    elif fault.startswith("zip_"):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as zipped:
            for name, raw in c.data.items():
                zipped.writestr(name, raw)
            if fault == "zip_symlink":
                info = zipfile.ZipInfo("linked")
                info.create_system = 3
                info.external_attr = 0o120777 << 16
                zipped.writestr(info, b"target")
            elif fault == "zip_duplicate":
                with pytest.warns(UserWarning, match="Duplicate"):
                    zipped.writestr("README.md", b"duplicate")
        raw = output.getvalue()
        c.routes["asset:10"] = raw
        c.routes["asset:11"] = (
            f"{hashlib.sha256(raw).hexdigest()}  {c.request['asset_name']}\n".encode()
        )
        for item in c.routes["release:v4.0.0"]["assets"]:
            item["size"] = len(c.routes[f"asset:{item['id']}"])
        if fault == "zip_bomb":
            monkeypatch.setattr(c.delivery, "MAX_ZIP_UNCOMPRESSED", 1)
    write_json(c.run / "receipt.json", c.receipt)
    with pytest.raises(ValueError):
        verify(c)


@pytest.mark.parametrize(
    "rule",
    [
        {"type": "future_required_attestation"},
        {},
        {"type": None},
        {"type": "required_status_checks", "parameters": None},
        {"type": "required_status_checks", "parameters": {"required_status_checks": [None]}},
        {
            "type": "required_status_checks",
            "parameters": {"required_status_checks": [{"integration_id": 15368}]},
        },
        {
            "type": "required_status_checks",
            "parameters": {"required_status_checks": [{"context": "extra"}]},
        },
    ],
)
def test_unknown_or_malformed_branch_rule_cannot_disappear(candidate, rule):
    candidate.routes["rules"] = [rule]
    with pytest.raises(ValueError, match=r"branch rule|required check"):
        verify(candidate)


def test_supported_branch_status_rule_adds_an_actual_required_check(candidate):
    c = candidate
    c.routes["rules"] = [
        {
            "type": "required_status_checks",
            "parameters": {
                "required_status_checks": [{"context": "extra", "integration_id": 57789}]
            },
        }
    ]
    for sha in (HEAD, MERGE):
        c.routes[f"checks:{sha}"].append(
            {
                "head_sha": sha,
                "name": "extra",
                "app": {"id": 57789},
                "status": "completed",
                "conclusion": "success",
            }
        )
    assert verify(c)["status"] == "verified"
    c.routes[f"checks:{MERGE}"][-1]["conclusion"] = "failure"
    with pytest.raises(ValueError, match="required check is not successful: extra"):
        verify(c)


def test_archive_level_comment_is_rejected_even_when_all_raw_hashes_are_refreshed(candidate):
    c = candidate
    archive = c.run / "package.zip"
    with zipfile.ZipFile(archive, "a") as zipped:
        zipped.comment = b"unexpected archive comment"
    raw = archive.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    c.routes["asset:10"] = raw
    c.routes["asset:11"] = f"{digest}  {c.request['asset_name']}\n".encode()
    for asset in c.routes["release:v4.0.0"]["assets"]:
        asset["size"] = len(c.routes[f"asset:{asset['id']}"])
    c.receipt["package"]["sha256"] = digest
    write_json(c.run / "receipt.json", c.receipt)
    with pytest.raises(ValueError, match="archive comment"):
        verify(c)


def test_successful_description_operation_also_requires_fresh_full_readback(candidate):
    c = candidate
    operation = next(row for row in c.receipt["operations"] if row["name"] == "description:english")
    operation.update(
        status="succeeded",
        result={
            "result": 1,
            "item_id": c.observed["item_id"],
            "language": "english",
            "readback_verified": True,
        },
    )
    write_json(c.run / "receipt.json", c.receipt)
    assert verify(c)["status"] == "verified"
    c.observed["descriptions"]["english"] = "remote changed after publication"
    with pytest.raises(ValueError, match="readback"):
        verify(c)


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "changed_worktree",
        "untracked",
        "source_followup",
        "receipt_followup",
        "unapproved_receipt",
        "wrong_head",
    ],
)
def test_git_reader_binds_current_bytes_and_only_exact_receipt_followups(
    tmp_path, monkeypatch, fault
):
    delivery = importlib.import_module("tools.ci.a4_delivery")
    reader = delivery.GitReader(tmp_path)
    source = tmp_path / "src/pdx/input.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"value = 1\n")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    base_tree = {"src/pdx/input.py": ("100644", "1" * 40)}
    current_tree = base_tree.copy()
    allowed = []
    if fault == "source_followup":
        current_tree["src/pdx/input.py"] = ("100644", "2" * 40)
    if fault in {"receipt_followup", "unapproved_receipt"}:
        current_tree["docs/design/exec/A4-delivery/receipt.json"] = ("100644", "3" * 40)
        if fault == "receipt_followup":
            allowed = ["docs/design/exec/A4-delivery/receipt.json"]
    monkeypatch.setattr(
        reader, "tree", lambda commit: base_tree if commit == MERGE else current_tree
    )
    monkeypatch.setattr(reader, "snapshot", lambda _commit: {"src/pdx/input.py": digest})
    monkeypatch.setattr(
        reader, "_run", lambda *_args: (HEAD if fault == "wrong_head" else MAIN).encode()
    )
    if fault == "changed_worktree":
        source.write_bytes(b"value = 2\n")
    if fault == "untracked":
        (source.parent / "untracked.py").write_bytes(b"extra")
    if fault in {"none", "receipt_followup"}:
        reader.verify_current(
            MERGE, {"src/pdx/input.py": digest}, main=MAIN, followup_paths=allowed
        )
    else:
        with pytest.raises(ValueError):
            reader.verify_current(
                MERGE, {"src/pdx/input.py": digest}, main=MAIN, followup_paths=allowed
            )


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        ("https://github.com/owner/repo.git", "owner/repo"),
        ("git@github.com:owner/repo.git", "owner/repo"),
        ("https://github.com/owner/repo", "owner/repo"),
        ("https://secret@github.com/owner/repo.git", None),
        ("https://evil.test/owner/repo.git", None),
    ],
)
def test_git_remote_repository_is_read_from_config_without_userinfo(
    tmp_path, monkeypatch, remote, expected
):
    delivery = importlib.import_module("tools.ci.a4_delivery")
    reader = delivery.GitReader(tmp_path)
    monkeypatch.setattr(reader, "_run", lambda *_args: remote.encode())
    if expected is None:
        with pytest.raises(ValueError):
            reader.remote_repository()
    else:
        assert reader.remote_repository() == expected


@pytest.mark.parametrize(
    "fault",
    [
        "bool_schema",
        "bool_pr",
        "snapshot_path",
        "relative_lock",
        "duplicate_lock",
        "unsafe_followup",
        "absolute_run",
        "asset_subdir",
        "unknown_reference",
        "description_key",
    ],
)
def test_strict_sidecar_rejects_unsafe_or_ambiguous_inputs(candidate, fault):
    c = candidate
    if fault == "bool_schema":
        c.request["schema"] = True
    elif fault == "bool_pr":
        c.request["pull_request"] = True
    elif fault == "snapshot_path":
        c.request["production_snapshot"] = {"../escape": "d" * 64}
    elif fault == "relative_lock":
        c.request["lock_paths"][0] = "relative.lock"
    elif fault == "duplicate_lock":
        c.request["lock_paths"].append(c.request["lock_paths"][0])
    elif fault == "unsafe_followup":
        c.request["allowed_followup_paths"] = ["src/pdx/input.py"]
    elif fault == "absolute_run":
        c.request["run_dir"] = str(c.run)
    elif fault == "asset_subdir":
        c.request["asset_name"] = "dir/name.zip"
    elif fault == "unknown_reference":
        c.request["cleanup"]["verified"] = True
    elif fault == "description_key":
        c.request["expected_languages"].append("unrecognized")
    with pytest.raises(ValueError):
        verify(c)


def _preserved_backup(c, metadata=b'{"id":"situated-ai","version":"3.9.0"}\n'):
    backup = c.root / "user/.situated-ai-backups/run1/Situated AI"
    backup.mkdir(parents=True)
    files = {"common/old.txt": b"old bytes"}
    if metadata is not None:
        files[distribution.METADATA_NAME] = metadata
    for name, raw in files.items():
        path = backup / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    c.receipt["operations"][0]["result"]["backup"] = str(backup)
    write_json(c.run / "receipt.json", c.receipt)
    c.request["recovery"] = write_json(
        c.root / "recovery.json",
        {
            "schema": 1,
            "target": str(c.target),
            "backup": str(backup),
            "backup_files": {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()},
            "reason": "preserved_backup",
        },
    )
    return backup


def test_backup_bytes_and_receipt_must_match_actual_recovery_tree(candidate):
    c = candidate
    backup = _preserved_backup(c)
    assert verify(c)["status"] == "verified"
    (backup / "common/old.txt").write_bytes(b"changed")
    with pytest.raises(ValueError, match="backup identity"):
        verify(c)


@pytest.mark.parametrize("metadata", [None, b'{"id":"another-mod"}', b"not JSON"])
def test_backup_needs_real_mod_identity_even_with_matching_self_reported_hashes(
    candidate, metadata
):
    _preserved_backup(candidate, metadata)
    with pytest.raises(ValueError, match=r"Mod 身份|backup identity"):
        verify(candidate)


def test_game_conflict_remains_failure(candidate, monkeypatch):
    def conflict():
        raise ValueError("game conflict")

    monkeypatch.setattr(candidate.delivery.deployment, "assert_game_stopped", conflict)
    with pytest.raises(ValueError, match="game conflict"):
        verify(candidate)


def test_receipt_cannot_claim_reversed_operation_time(candidate):
    c = candidate
    c.receipt["started_at"] = datetime(2026, 11, 6, 1, tzinfo=UTC).isoformat()
    write_json(c.run / "receipt.json", c.receipt)
    with pytest.raises(ValueError, match="time"):
        verify(c)


def test_delivery_request_rejects_unknown_fields() -> None:
    spec = importlib.util.find_spec("tools.ci.a4_delivery")
    assert spec is not None, "independent A4 delivery verifier is missing"
    delivery = importlib.import_module("tools.ci.a4_delivery")
    with pytest.raises(ValueError, match="fields"):
        delivery.validate_request({"schema": 1, "verified": True})


@pytest.mark.parametrize(
    "url",
    [
        "http://api.github.com/repos/owner/repo/pulls/1",
        "https://evil.test/repos/owner/repo/pulls/1",
        "https://api.github.com/repos/other/repo/pulls/1",
        "https://token@api.github.com/repos/owner/repo/pulls/1",
        "https://api.github.com:444/repos/owner/repo/pulls/1",
    ],
)
def test_github_reader_rejects_routes_before_any_network(url: str) -> None:
    spec = importlib.util.find_spec("tools.ci.a4_delivery")
    assert spec is not None, "safe GitHub reader is missing"
    delivery = importlib.import_module("tools.ci.a4_delivery")
    reader = delivery.GitHubReader("owner/repo")
    with pytest.raises(ValueError):
        reader.check_url(url, asset=False)
