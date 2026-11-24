"""Check synthetic field/phase/caller counterexamples against the migration contract."""

import hashlib
import json
import zipfile

import pytest
from typer.testing import CliRunner

from pdx import cli, version_contracts
from pdx import writer_transition as tr


def row(source, definition, field, phase, *, output=None, state="pending"):
    return dict(
        zip(
            tr.COLUMNS,
            (
                source,
                definition,
                field,
                "consumer_adapters",
                "example-transform",
                "sample-position",
                output or source,
                "7",
                phase,
                state,
            ),
            strict=True,
        )
    )


def test_frozen_inventory_counts_every_unique_source_definition_and_field():
    raw = version_contracts.research_path("situated", tr.LEDGER).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == tr.LEDGER_SHA256
    rows = tr._inventory(raw)
    assert len(rows) == 981
    assert len({item["source"] for item in rows}) == 77
    assert len({item["published_output"] for item in rows}) == 78
    assert sum(r["candidate_disposition"] == "pending" for r in rows) == 955
    with pytest.raises(ValueError, match="Duplicate"):
        tr._inventory(raw + raw.splitlines(keepends=True)[1])


def test_preserving_source_filename_does_not_cover_an_external_helper():
    source = "common/ai_strategies/sample.txt"
    helper = "common/script_values/original_helper.txt"
    records = [
        row(source, "strategy", "fleet.protect_supply", "existing_scalar_type", output=helper)
    ]
    for path in (helper, source):
        with pytest.raises(ValueError, match="1 pending writers"):
            tr._check_retirements(records, {path})
    with pytest.raises(ValueError, match="1 further removed paths") as error:
        tr._check_retirements(records, {"common/company_types/unrelated.txt"})
    assert "common/company_types/unrelated.txt" in str(error.value).splitlines()
    tr._check_retirements(records, set())


@pytest.mark.parametrize(
    "mutation", ["phase", "owner", "published_output", "field", "source", "definition"]
)
def test_company_name_alone_cannot_authorize_a_field(mutation):
    candidate = row(
        tr.SOURCE,
        "company_a",
        "ai_weight",
        "new_direct_property",
        state="candidate_static_projection",
    )
    tr._reconcile([candidate], {"company_a"}, {"company_a"})
    candidate[mutation] = "unproved"
    with pytest.raises(ValueError, match="Unproved"):
        tr._reconcile([candidate], {"company_a"}, {"company_a"})


@pytest.mark.parametrize(
    "text",
    [
        "INJECT:a = { other = {} }",
        "a = { ai_weight = {} }",
        "INJECT:a = { ai_weight = {} } INJECT:a = { ai_weight = {} }",
        "INJECT:a = { ai_weight = {} sibling = yes }",
    ],
)
def test_modified_injection_shape_is_rejected(text):
    with pytest.raises(ValueError):
        tr._projected_targets(text.encode())


def test_synthetic_zip_and_lock_bind_real_cli_and_retirement(tmp_path, monkeypatch):
    raw = version_contracts.research_path("situated", tr.LEDGER).read_bytes()
    targets = [
        r["definition"]
        for r in tr._inventory(raw)
        if r["candidate_disposition"] == "candidate_static_projection"
    ]
    script = (
        "\ufeff"
        + "\n".join(f"INJECT:{target} = {{ ai_weight = {{ value = 1 }} }}" for target in targets)
    ).encode()
    archive = tmp_path / "fixture.zip"
    manifest = json.dumps({"files": {tr.MEMBER: hashlib.sha256(script).hexdigest()}}).encode()
    with zipfile.ZipFile(archive, "w") as writer:
        writer.writestr(tr.MEMBER, script)
        writer.writestr(tr.distribution.MANIFEST_NAME, manifest)
    monkeypatch.setattr(
        tr, "CANDIDATE_ZIP_SHA256", hashlib.sha256(archive.read_bytes()).hexdigest()
    )
    monkeypatch.setattr(tr, "MEMBER_SHA256", hashlib.sha256(script).hexdigest())
    review = {
        "schema": 1,
        "archive_sha256": tr.CANDIDATE_ZIP_SHA256,
        "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
        "members": {tr.MEMBER: {"origin": "fixture", "delivery_sha256": tr.MEMBER_SHA256}},
    }
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    monkeypatch.setattr(tr, "REVIEW_SHA256", hashlib.sha256(review_path.read_bytes()).hexdigest())
    original_path = version_contracts.research_path
    monkeypatch.setattr(
        version_contracts,
        "research_path",
        lambda category, name: (
            review_path
            if name == "original-company-package-sources.json"
            else original_path(category, name)
        ),
    )
    result = CliRunner().invoke(cli.app, ["modguard", "--writer-transition", str(archive)])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert (report["candidate_static_projection"], report["pending"]) == (26, 955)
    with pytest.raises(ValueError, match="does not describe"):
        tr.check_candidate(archive, successor_files={})
    files = {tr.MEMBER: hashlib.sha256(script.decode("utf-8-sig").encode()).hexdigest()}
    paths = {row[key] for row in tr._inventory(raw) for key in ("source", "published_output")}
    previous = dict.fromkeys(paths, "0" * 64)
    with pytest.raises(ValueError, match="Missing predecessor"):
        tr.check_candidate(archive, successor_files=files)
    with pytest.raises(ValueError, match="Previous writer outputs"):
        tr.check_candidate(archive, successor_files=files, previous_files=previous)
    monkeypatch.setattr(
        tr,
        "BASE_WRITER_OUTPUTS_SHA256",
        hashlib.sha256(
            json.dumps(previous, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    )
    with pytest.raises(ValueError, match="955 pending writers"):
        tr.check_candidate(archive, successor_files=files, previous_files=previous)
    incomplete = json.dumps({**review, "members": {}}).encode()
    with pytest.raises(ValueError, match="coverage"):
        tr.verify_package_sources(
            archive.read_bytes(),
            incomplete,
            trusted_review_sha256=hashlib.sha256(incomplete).hexdigest(),
        )
    with pytest.raises(ValueError, match="independent approval"):
        tr.verify_package_sources(
            archive.read_bytes(), incomplete, trusted_review_sha256=tr.REVIEW_SHA256
        )
    with archive.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="reviewed archive"):
        tr.check_candidate(archive)
