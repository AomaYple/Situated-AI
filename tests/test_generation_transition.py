"""Synthetic Git histories for the generated-output transition preflight."""

import hashlib
import json
import shutil
import stat
import subprocess
import zlib
from pathlib import Path
lazy import os

import pytest

from tools.ci.generation_transition import LOCK, plan_transition


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def lock(files: dict[str, bytes]) -> bytes:
    return json.dumps(
        {
            "schema": 1,
            "evidence": "frozen_generation_not_current_game_verification",
            "files": {path: digest(raw) for path, raw in files.items()},
            "sources": {},
        }
    ).encode()


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], encoding="utf-8").strip()


@pytest.fixture
def history(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "core.autocrlf", "false")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "fixture@example.invalid")
    git(tmp_path, "config", "commit.gpgsign", "false")
    previous = {"common/keep.txt": b"k", "common/replace.txt": b"x", "common/retire.txt": b"y"}
    for name, raw in {**previous, LOCK: lock(previous)}.items():
        path = tmp_path / "mod" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    git(tmp_path, "add", "mod")
    git(tmp_path, "commit", "-qm", "previous")
    return tmp_path, git(tmp_path, "rev-parse", "HEAD"), previous


def test_plans_all_four_actions_and_preserves_files_and_index(history):
    repo, commit, old = history
    new = lock({"common/keep.txt": b"k", "common/replace.txt": b"z", "common/added.txt": b"a"})
    git(repo, "commit", "--allow-empty", "-qm", "later")
    (repo / "other").write_bytes(b"unrelated work")
    git(repo, "add", "other")
    (repo / "intent-only").touch()
    git(repo, "add", "--intent-to-add", "intent-only")
    before = git(repo, "status", "--porcelain")
    report = plan_transition(repo, commit, new, digest(new))
    assert report["head"] == git(repo, "rev-parse", "HEAD")
    assert report["check_scope"] == "file_ownership_only"
    assert report["retirement_authorized"] is False
    assert report["previous_lock_sha256"] == digest(lock(old))
    rows = report["outputs"]
    assert isinstance(rows, list)
    assert {row["path"]: row["action"] for row in rows} == {
        "common/added.txt": "add",
        "common/keep.txt": "keep",
        "common/replace.txt": "replace",
        "common/retire.txt": "retire",
    }
    retired = next(row for row in rows if row["action"] == "retire")
    assert retired["previous_blob"] == git(repo, "rev-parse", f"{commit}:mod/common/retire.txt")
    assert retired["previous_sha256"] == digest(b"y")
    assert retired["successor_sha256"] is None
    assert git(repo, "status", "--porcelain") == before


@pytest.mark.parametrize(
    "change", ["edit", "missing", "untracked", "staged", "working-lock", "staged-revert"]
)
def test_requires_current_ownership(history, change):
    repo, commit, previous = history
    new = lock(previous)
    target = repo / "mod/common/retire.txt"
    if change == "missing":
        target.unlink()
    elif change == "working-lock":
        (repo / "mod" / LOCK).write_bytes(new + b" ")
    elif change == "untracked":
        (repo / "mod/common/local.txt").write_bytes(b"user")
    else:
        target.write_bytes(b"change")
        if change in {"staged", "staged-revert"}:
            git(repo, "add", "mod")
            if change == "staged-revert":
                git(repo, "commit", "-qm", "intervening output edit")
                target.write_bytes(b"y")
                git(repo, "add", "mod")
            else:
                target.write_bytes(b"y")
    before = git(repo, "status", "--porcelain")
    with pytest.raises(ValueError):
        plan_transition(repo, commit, new, digest(new))
    assert git(repo, "status", "--porcelain") == before


def test_binds_successor_and_requires_predecessor_ancestry(history):
    repo, commit, previous = history
    new = lock(previous)
    with pytest.raises(ValueError, match="reviewed digest"):
        plan_transition(repo, commit, new + b" ", digest(new))
    git(repo, "commit", "--allow-empty", "-qm", "future")
    future = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "--detach", commit)
    with pytest.raises(ValueError, match="merge-base"):
        plan_transition(repo, future, new, digest(new))


@pytest.mark.parametrize(
    "path",
    [
        "decisions/source.toml",
        "common/../foo",
        "common/RETIRE.txt",
        "common/keep.txt/child",
        "common/alias/file.txt",
        "common/con.txt",
        "common/CONIN$.txt",
        "common/CON .txt",
    ],
)
def test_rejects_conflicting_or_out_of_scope_successor(history, path):
    repo, commit, _ = history
    new = lock({path: b"value", "common/Alias/witness.txt": b"synthetic"})
    with pytest.raises(ValueError):
        plan_transition(repo, commit, new, digest(new))


def test_rejects_duplicate_json_and_forged_historical_ownership(history):
    repo, _, previous = history
    commit = git(repo, "rev-parse", "HEAD")
    new = lock(previous)
    ambiguous = new.replace(b'"files":', b'"files": {}, "files":', 1)
    with pytest.raises(ValueError, match="duplicate"):
        plan_transition(repo, commit, ambiguous, digest(ambiguous))
    (repo / "mod" / LOCK).write_bytes(lock({**previous, "common/retire.txt": b"wrong digest"}))
    git(repo, "add", "mod")
    git(repo, "commit", "-qm", "inconsistent prior lock")
    with pytest.raises(ValueError, match="bytes"):
        plan_transition(repo, git(repo, "rev-parse", "HEAD"), new, digest(new))


def test_reserved_successor_path_is_an_existing_directory(history):
    repo, commit, previous = history
    directory = repo / "mod/common/added.txt"
    directory.mkdir()
    new = lock({**previous, "common/added.txt": b"addition"})
    with pytest.raises(ValueError, match="existing path"):
        plan_transition(repo, commit, new, digest(new))
    assert directory.is_dir()


@pytest.mark.parametrize("damage", ["truncated", "checksum", "wrong-object"])
def test_reads_historical_blob_body(history, damage):
    repo, commit, previous = history
    target = "common/retire.txt"
    oid = git(repo, "rev-parse", f"{commit}:mod/{target}")
    obj = repo / ".git/objects" / oid[:2] / oid[2:]
    compressed = obj.read_bytes()
    if damage == "truncated":
        corrupted = compressed[:-2]
    elif damage == "checksum":
        corrupted = compressed[:-1] + bytes([compressed[-1] ^ 1])
    else:
        corrupted = zlib.compress(b"blob 1\0z")
    obj.chmod(stat.S_IREAD | stat.S_IWRITE)
    obj.write_bytes(corrupted)
    new = lock({name: raw for name, raw in previous.items() if name != target})
    with pytest.raises(ValueError):
        plan_transition(repo, commit, new, digest(new))


def test_requires_physical_repository_root_and_its_own_index(history, monkeypatch):
    repo, commit, previous = history
    new = lock(previous)
    nested = repo / "child"
    shutil.copytree(repo / "mod", nested / "mod")
    monkeypatch.setenv("GIT_DIR", str(repo / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(nested))
    with pytest.raises(ValueError, match="physical root"):
        plan_transition(nested, commit, new, digest(new))
    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_WORK_TREE")
    clean_index = repo / "clean-index"
    shutil.copyfile(repo / ".git/index", clean_index)
    target = repo / "mod/common/retire.txt"
    target.write_bytes(b"staged")
    git(repo, "add", "mod")
    target.write_bytes(previous["common/retire.txt"])
    monkeypatch.setenv("GIT_INDEX_FILE", str(clean_index))
    with pytest.raises(ValueError, match="index"):
        plan_transition(repo, commit, new, digest(new))


@pytest.mark.parametrize("existing", ["Localization/notes.txt", "common/Notes"])
def test_rejects_occupied_directory_aliases(history, existing):
    repo, commit, previous = history
    occupied = repo / "mod" / existing
    if occupied.suffix:
        occupied.parent.mkdir()
        occupied.write_bytes(b"user")
    else:
        occupied.mkdir()
    new = lock({**previous, "common/notes/added.txt": b"new"})
    with pytest.raises(ValueError, match="casing"):
        plan_transition(repo, commit, new, digest(new))


def test_rejects_tag_objects_and_staged_gitlinks_despite_diff_configuration(history):
    repo, commit, previous = history
    new = lock(previous)
    git(repo, "tag", "-a", "example", "-m", "example")
    tag = git(repo, "rev-parse", "example")
    with pytest.raises(ValueError, match="commit object"):
        plan_transition(repo, tag, new, digest(new))
    git(repo, "config", "diff.ignoreSubmodules", "all")
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{commit},mod/common/extra")
    with pytest.raises(ValueError, match="regular generated blob"):
        plan_transition(repo, commit, new, digest(new))


def test_unmerged_generated_index_entry_is_rejected(history):
    repo, commit, previous = history
    new = lock(previous)
    path = "mod/common/retire.txt"
    oid = git(repo, "rev-parse", f"{commit}:{path}")
    git(repo, "update-index", "--force-remove", "--", path)
    subprocess.run(
        ["git", "-C", str(repo), "update-index", "--index-info"],
        input=f"100644 {oid} 2\t{path}\n".encode(),
        check=True,
    )
    with pytest.raises(ValueError, match="unmerged"):
        plan_transition(repo, commit, new, digest(new))


def test_rejects_an_intent_to_add_entry_for_an_empty_historical_blob(history):
    repo, _, previous = history
    path = "common/empty.txt"
    previous[path] = b""
    (repo / "mod" / path).touch()
    new = lock(previous)
    (repo / "mod" / LOCK).write_bytes(new)
    git(repo, "add", "mod")
    git(repo, "commit", "-qm", "empty generated blob")
    commit = git(repo, "rev-parse", "HEAD")
    index_entries = git(repo, "ls-files", "--stage", "-z", "mod")
    plan_transition(repo, commit, new, digest(new))

    git(repo, "update-index", "--force-remove", "--", f"mod/{path}")
    git(repo, "add", "--intent-to-add", "--", f"mod/{path}")
    assert git(repo, "ls-files", "--stage", "-z", "mod") == index_entries
    before = (repo / ".git/index").read_bytes()
    with pytest.raises(ValueError, match="intent-to-add"):
        plan_transition(repo, commit, new, digest(new))
    assert (repo / ".git/index").read_bytes() == before


def test_rejects_a_short_alias_of_an_existing_output_parent(history, monkeypatch):
    repo, commit, previous = history
    common = repo.resolve() / "mod/common"
    directory = common / "Long Output Subdirectory"
    directory.mkdir()
    alias = common / "LONGOU~1"
    current_lstat = Path.lstat

    def lstat_through_alias(path: Path) -> os.stat_result:
        # Directory enumeration yields the long name, while lookup accepts the short alias.
        return current_lstat(directory if path == alias else path)

    monkeypatch.setattr(Path, "lstat", lstat_through_alias)
    new = lock({**previous, "common/LONGOU~1/missing/added.txt": b"new"})
    with pytest.raises(ValueError, match="existing path"):
        plan_transition(repo, commit, new, digest(new))


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("valid", None),
        ("valid_same_source_retention", None),
        ("false_vanilla_hash", "differs from the locked native field"),
        ("false_vanilla_hash_other", "differs from the locked native field"),
        ("drifted_vanilla", "differ from the frozen installation"),
        ("masked_vanilla", "masks the native source path"),
        ("missing_named_helper", "missing, ambiguous or changed helper"),
        ("present_named_helper", None),
        ("retired_localization", "pending"),
        ("changed_localization", "pending"),
        ("same_name_field_removed", "pending"),
        ("same_name_definition_removed", "pending"),
        ("same_name_auxiliary_changed", "pending"),
        ("static_projection", "pending"),
        ("withdraw_without_authority", "product authorization"),
        ("auxiliary", "pending"),
        ("duplicate", "duplicate"),
        ("ambiguous_file", "ambiguous"),
        ("wrong_order", "load order"),
        ("wrong_mapping", "AST mapping"),
        ("wrong_scope", "outside equivalence mechanism"),
        ("unknown_sources", "recoverable original source"),
        ("missing_row", "coverage differs"),
        ("bytes_mismatch", "Git/lock projection"),
        ("untrusted_review", "independent approval"),
        ("wrong_baseline", "frozen predecessor"),
        ("new_claims_old", "cannot dispose an old writer"),
    ],
)
def test_successor_cli_reconciles_a_second_database(tmp_path, monkeypatch, capsys, mutation, error):
    import csv
    import io
    import sys
    import zipfile
    from types import SimpleNamespace

    from pdx import distribution
    from pdx import writer_transition as tr
    from tools.ci import generation_transition as gt

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "commit.gpgsign", "false")

    common = "common/laws"
    original = f"{common}/01_fixture.txt"
    hook = f"{common}/{'00' if mutation == 'wrong_order' else 'zz'}_fixture.txt"
    helper = "common/script_values/fixture_auxiliary.txt"
    native = b"law_one = { score = 1 avoid = 4 }\n"
    previous = {original: b"law_one = { score = 1 avoid = 2 }\n"}
    linked = mutation in {"missing_named_helper", "present_named_helper"}
    if linked:
        previous[original] = b"law_one = { score = fixture_value avoid = 2 }\n"
        previous[helper] = b"fixture_value = { value = 3 }\n"
    previous_loc = "localization/english/author_l_english.yml"
    if mutation in {"retired_localization", "changed_localization"}:
        previous[previous_loc] = b'l_english:\n author_custom: "Before"\n'
    if mutation in {"auxiliary", "same_name_auxiliary_changed"}:
        previous[helper] = b"fixture_value = 2\n"

    def write_files(files):
        for name, raw in files.items():
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)

    write_files(
        {**{f"mod/{name}": raw for name, raw in previous.items()}, f"mod/{LOCK}": lock(previous)}
    )
    git(repo, "add", "mod")
    git(repo, "commit", "-qm", "previous")
    prior = git(repo, "rev-parse", "HEAD")

    installation = tmp_path / "native"
    native_path = installation / "game" / original
    native_path.parent.mkdir(parents=True)
    native_path.write_bytes(native + (b"# changed" if mutation == "drifted_vanilla" else b""))
    monkeypatch.setattr(
        tr.version_contracts,
        "verify_installation_identity",
        lambda root: SimpleNamespace(root=root),
    )
    monkeypatch.setattr(
        tr,
        "BASE_NATIVE_SOURCES_SHA256",
        digest(
            json.dumps({original: digest(native)}, sort_keys=True, separators=(",", ":")).encode()
        ),
    )

    rows = [
        {
            "source": original,
            "definition": "law_one",
            "field": field,
            "owner": "consumer_adapters",
            "transform": "direct_script_value",
            "placement": "explicit_block_end",
            "published_output": helper if linked and field == "score" else original,
            "readback_line": "1",
            "phase": "direct_value_tail",
            "candidate_disposition": "pending",
        }
        for field in ("score", "avoid")
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, tr.COLUMNS, delimiter="\t")
    writer.writeheader()
    writer.writerows(rows)
    ledger = tmp_path / "writers.tsv"
    ledger.write_bytes(buffer.getvalue().encode())
    baseline_zip = tmp_path / "published.zip"
    with zipfile.ZipFile(baseline_zip, "w"):
        pass
    monkeypatch.setattr(tr, "BASE_RELEASE_COMMIT", prior)
    monkeypatch.setattr(tr, "BASE_ZIP_SHA256", digest(baseline_zip.read_bytes()))
    monkeypatch.setattr(tr, "BASE_WRITERS", len(rows))
    monkeypatch.setattr(tr, "LEDGER_SHA256", digest(ledger.read_bytes()))
    monkeypatch.setattr(gt.version_contracts, "research_path", lambda *_args: ledger)

    metadata = dict.fromkeys(distribution.LAUNCHER_METADATA_KEYS, "fixture")
    metadata.update(id=distribution.MOD_ID, tags=[], relationships=[], game_custom_data={})
    projection = "INJECT:law_one = { score = { value = 1 add = 3 } }\n"
    new_script = "law_two = { approved = yes }\n"
    if linked:
        projection = "INJECT:law_one = { score = fixture_value }\n"
    if mutation == "duplicate":
        projection *= 2
    new_files = {
        hook: (projection + new_script).encode(),
        distribution.METADATA_NAME: json.dumps(metadata).encode(),
    }
    if mutation == "present_named_helper":
        new_files[helper] = previous[helper]
    if mutation == "valid_same_source_retention":
        new_files[original] = b"# independently restated fixture\n" + native
        new_files[hook] = new_script.encode()
    if mutation == "masked_vanilla":
        new_files[original] = b"law_three = { updated = yes }\n"
    if mutation == "changed_localization":
        new_files[previous_loc] = b'l_english:\n author_custom: "After"\n'
    if mutation == "ambiguous_file":
        new_files[f"{common}/zz_duplicate.txt"] = projection.encode()
    if mutation == "same_name_field_removed":
        new_files = {
            original: b"law_one = { avoid = 2 }\n",
            distribution.METADATA_NAME: new_files[distribution.METADATA_NAME],
        }
    if mutation == "same_name_definition_removed":
        new_files = {
            original: new_script.encode(),
            distribution.METADATA_NAME: new_files[distribution.METADATA_NAME],
        }
    if mutation == "same_name_auxiliary_changed":
        new_files[helper] = b"fixture_value = 3\n"
    authored = {"src/rules.txt": b"original test rule\n", "README.md": b"guide\n"}
    evidence_path = "audit/evidence.json"
    evidence = {"path": evidence_path, "sha256": digest(b"independent fixture readback\n")}
    lock_record = json.loads(lock(new_files))
    lock_record["sources"] = {"src/rules.txt": digest(authored["src/rules.txt"])}
    successor_lock = json.dumps(lock_record).encode()

    for name in previous.keys() - new_files.keys():
        (repo / "mod" / name).unlink()
    write_files(
        {
            **authored,
            **{f"mod/{name}": raw for name, raw in new_files.items()},
            f"mod/{LOCK}": successor_lock,
            evidence_path: b"independent fixture readback\n",
        }
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "successor")
    candidate_commit = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "--detach", prior)

    source_map = {**{name: raw.decode() for name, raw in new_files.items()}, "README.md": "guide\n"}
    payload = distribution.payloads(distribution._release_files(source_map))
    if mutation == "bytes_mismatch":
        payload[hook] += b"# changed"
    manifest = json.dumps(distribution._manifest_for_payloads(payload)).encode()
    archive = tmp_path / "candidate.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for name, raw in {**payload, distribution.MANIFEST_NAME: manifest}.items():
            bundle.writestr(name, raw)
    source_records = {
        name: {
            "origin": "original",
            "delivery_sha256": digest(raw),
            "source_files": {"src/rules.txt": digest(authored["src/rules.txt"])},
        }
        for name, raw in payload.items()
    }
    source_records["README.md"].update(
        repository_path="README.md", source_files={"README.md": digest(authored["README.md"])}
    )
    if mutation == "unknown_sources":
        source_records[hook]["source_files"] = {}

    target_script = tr._script_index({hook: (projection + new_script).encode()})[hook]
    projected = target_script["law_one"][0]
    target = {
        "member": f"{common}/zz_wrong.txt" if mutation == "wrong_mapping" else hook,
        "prefix": "INJECT",
        "definition_sha256": tr._ast_sha256(projected),
    }
    identity = [
        {"source": row["source"], "definition": row["definition"], "field": row["field"]}
        for row in rows
    ]
    writer_rows = [
        {
            **identity[0],
            "status": "equivalent",
            "target": target,
            "mechanism": "direct-legal-score",
            "scope": "country",
            "original_value_sha256": {
                "false_vanilla_hash": "0" * 64,
                "false_vanilla_hash_other": "a" * 64,
            }.get(mutation, tr._ast_sha256(tr.Scalar("1"))),
            "contribution_sha256": tr._ast_sha256(tr._field(projected, "score")),
        },
        {
            **identity[1],
            "status": "retain_vanilla",
            "reason": "restored engine value",
            "evidence": evidence,
        },
    ]
    if mutation == "valid_same_source_retention":
        writer_rows[0] = {
            **identity[0],
            "status": "retain_vanilla",
            "reason": "restored engine value",
            "evidence": evidence,
        }
    if mutation == "masked_vanilla":
        writer_rows[0] = {**identity[0], "status": "pending"}
    if mutation.startswith("same_name_"):
        writer_rows = [{**key, "status": "pending"} for key in identity]
    elif mutation == "static_projection":
        writer_rows[0]["status"] = "static_projection"
    elif mutation == "withdraw_without_authority":
        writer_rows[1]["status"] = "withdrawn"
    elif mutation == "missing_row":
        writer_rows.pop()
    opportunities = [
        {
            "member": hook,
            "prefix": None,
            "definition": "law_two",
            "field": "approved",
            "definition_sha256": tr._ast_sha256(target_script["law_two"][0]),
            "evidence": evidence,
        }
    ]
    if mutation.startswith("same_name_"):
        opportunities = []
    elif mutation == "new_claims_old":
        opportunities = [{**target, "definition": "law_one", "field": "score"}]

    review_doc = {
        "schema": 2,
        "baseline": {
            "commit": prior,
            "release_commit": prior,
            "archive_sha256": tr.BASE_ZIP_SHA256,
            "generation_lock_sha256": digest(lock(previous)),
            "writer_inventory_sha256": tr.LEDGER_SHA256,
        },
        "source_commit": candidate_commit,
        "generation_lock_sha256": digest(successor_lock),
        "archive_sha256": digest(archive.read_bytes()),
        "manifest_sha256": digest(manifest),
        "members": source_records,
        "writers": writer_rows,
        "mechanisms": {
            "direct-legal-score": {
                "database": common,
                "depth": 1,
                "phase": "direct_value_tail",
                "placement": "explicit_block_end",
                "transform": "direct_script_value",
                "prefix": "INJECT",
                "scope": "state" if mutation == "wrong_scope" else "country",
                "load_order": "after_original",
                "evidence": evidence,
            }
        },
        "opportunities": opportunities,
        "auxiliary_retirements": [],
    }
    if mutation == "wrong_baseline":
        review_doc["baseline"]["release_commit"] = "0" * 40
    review = tmp_path / "review.json"
    review.write_bytes(json.dumps(review_doc).encode())
    reviewed_sha = "0" * 64 if mutation == "untrusted_review" else digest(review.read_bytes())
    proposed = tmp_path / "generation-lock.json"
    proposed.write_bytes(successor_lock)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generation_transition",
            "--repo",
            str(repo),
            "--previous-commit",
            prior,
            "--successor-lock",
            str(proposed),
            "--successor-sha256",
            digest(successor_lock),
            "--successor-archive",
            str(archive),
            "--baseline-archive",
            str(baseline_zip),
            "--successor-review",
            str(review),
            "--successor-review-sha256",
            reviewed_sha,
            "--installation",
            str(installation),
        ],
    )
    if error and error != "pending":
        with pytest.raises(SystemExit) as stopped:
            gt.main()
        assert stopped.value.code == 1
        assert error in capsys.readouterr().err
        return
    assert gt.main() == (1 if error else 0)
    result = json.loads(capsys.readouterr().out)["writer_transition"]
    assert result["reviewed_payload_members"] == len(payload)
    assert result["writer_disposition_complete"] is not bool(error)
    if mutation == "same_name_field_removed":
        assert result["writers"][0]["previous_site"] == "field_removed"
    elif mutation == "same_name_definition_removed":
        assert result["writers"][0]["previous_site"] == "definition_removed"
    elif mutation in {"auxiliary", "same_name_auxiliary_changed"}:
        assert result["unresolved_auxiliary_retirements"] == [helper]
    elif mutation in {"retired_localization", "changed_localization"}:
        assert result["unresolved_auxiliary_retirements"] == [previous_loc]
    elif mutation == "valid_same_source_retention":
        assert result["writer_counts"] == {"retain_vanilla": 2}
    elif mutation in {"valid", "present_named_helper"}:
        assert result["verified_original_sources"] == 1
        assert result["writer_counts"] == {"equivalent": 1, "retain_vanilla": 1}
        assert result["equivalence_groups"] == {"direct-legal-score": 1}
        assert result["new_opportunities"][0]["site"] == [hook, "law_two", "approved"]
