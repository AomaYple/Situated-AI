"""Read-only, per-writer evidence for the 3.4.0 to original-company candidate transition."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from collections import Counter
from typing import TYPE_CHECKING

from pdx import distribution, version_contracts
from pdx.model import Block
from pdx.parser import parse_text
from pdx.situated import engine_scope

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

LEDGER = "writer-dispositions-3.4.0.tsv"
LEDGER_SHA256 = "237a678d72735586bcd7c4728070f32c5e87a0852033c066aa7e6d5b0e3361d6"
CLOSURE_SHA256 = "593bc3ef324ce915ef57f93df94c3d80bd3c4e3642ac73eb6270e76fcc42788d"
BASE_ZIP_SHA256 = "a5ccf61255338ade0bdd6d71eaf9e22cbdb90a71c6090d9bd3ff3e706c25507e"
BASE_WRITER_OUTPUTS_SHA256 = "2b5ac0cdb4ac1f7c3199463e3ccf0a240e5c781bb28d2564123d01d8a4413d0c"
CANDIDATE_ZIP_SHA256 = "9f3bb81b687f523112e8e0bab6f6cfc9c7e642a09c892756b0cdbede33af95ce"
REVIEW_SHA256 = "1677f15aa9294060736755d5371de8bef301eaade5feee76ec016665b85f4549"
SOURCE = "common/company_types/99_basic_companies.txt"
MEMBER = "common/company_types/zz_sitai_company_ai_weights.txt"
MEMBER_SHA256 = "c5678d1baa434cd0abe6272af683ce9e55970342f9b8f9fc38ed74b13cb3e282"
COLUMNS = (
    "source",
    "definition",
    "field",
    "owner",
    "transform",
    "placement",
    "published_output",
    "readback_line",
    "phase",
    "candidate_disposition",
)


def _inventory(raw: bytes) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8")), delimiter="\t")
    if tuple(reader.fieldnames or ()) != COLUMNS:
        raise ValueError("Unexpected writer inventory columns")
    rows = list(reader)
    identities = set()
    for row in rows:
        if row.keys() != set(COLUMNS) or not all(row.values()):
            raise ValueError("Incomplete writer evidence")
        identity = (row["source"], row["definition"], row["field"])
        if identity in identities:
            raise ValueError(f"Duplicate physical writer: {identity}")
        identities.add(identity)
    return rows


def _projected_targets(member: bytes) -> set[str]:
    parsed = parse_text(member.decode("utf-8-sig"), MEMBER)
    parsed.require_complete()
    targets: set[str] = set()
    for op in parsed.top_assignments:
        if (
            op.prefix != "INJECT"
            or op.op != "="
            or op.key in targets
            or not isinstance(op.value, Block)
            or len(op.value.items) != 1
        ):
            raise ValueError("Candidate must inject each company exactly once")
        score = op.value.first("ai_weight")
        if (
            score is None
            or score.prefix is not None
            or score.op != "="
            or not isinstance(score.value, Block)
        ):
            raise ValueError(f"Unexpected candidate field: {op.key}")
        targets.add(op.key)
    if len(parsed.root.items) != len(targets):
        raise ValueError("Unexpected candidate top-level contents")
    return targets


def _reconcile(rows: Sequence[Mapping[str, str]], authority: set[str], observed: set[str]) -> None:
    if observed != authority:
        raise ValueError("Candidate script and independently locked company targets differ")
    mapped = set()
    for row in rows:
        company = row["definition"]
        projected = (
            row["source"] == SOURCE
            and company in authority
            and row["field"] == "ai_weight"
            and row["phase"] == "new_direct_property"
            and row["published_output"] == SOURCE
            and row["owner"] == "consumer_adapters"
        )
        expected = "candidate_static_projection" if projected else "pending"
        if row["candidate_disposition"] != expected:
            raise ValueError(f"Unproved disposition: {row['source']}/{company}/{row['field']}")
        if projected:
            mapped.add(company)
    if mapped != observed:
        raise ValueError("Candidate projection missing from predecessor writer inventory")


def _check_retirements(rows: Sequence[Mapping[str, str]], removed: set[str]) -> None:
    covered = {row[key] for row in rows for key in ("source", "published_output")}
    unmapped = sorted(removed - covered)
    blocked = [
        row
        for row in rows
        if {row["source"], row["published_output"]} & removed
        and row["candidate_disposition"] == "pending"
    ]
    issues = []
    if blocked:
        first = blocked[0]
        issues.append(
            f"{len(blocked)} pending writers on retiring paths; first: "
            f"{first['source']}/{first['definition']}/{first['field']} "
            f"({first['owner']}, {first['phase']})"
        )
    if unmapped:
        issues.append(f"{len(unmapped)} further removed paths require individual disposition:")
        issues.extend(unmapped)
    if issues:
        raise ValueError("\n".join(issues))


def verify_package_sources(
    archive: bytes, review: bytes, *, trusted_review_sha256: str
) -> dict[str, bytes]:
    """Compare the exact frozen ZIP with an external, independently pinned source review."""
    if hashlib.sha256(review).hexdigest() != trusted_review_sha256:
        raise ValueError("Package source review differs from independent approval")
    record = json.loads(review)
    if record["schema"] != 1 or hashlib.sha256(archive).hexdigest() != record["archive_sha256"]:
        raise ValueError("Package differs from reviewed archive")
    members = record["members"]
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        names = bundle.namelist()
        distribution._validate_paths(names)
        if set(names) != {*members, distribution.MANIFEST_NAME}:
            raise ValueError("Package source coverage differs from archive members")
        manifest = bundle.read(distribution.MANIFEST_NAME)
        if hashlib.sha256(manifest).hexdigest() != record["manifest_sha256"]:
            raise ValueError("Package manifest differs from reviewed bytes")
        actual = {name: bundle.read(name) for name in members}
    hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in actual.items()}
    if json.loads(manifest)["files"] != hashes or any(
        hashes[name] != row["delivery_sha256"] or not row["origin"].strip()
        for name, row in members.items()
    ):
        raise ValueError("Package member differs from reviewed source or manifest")
    return actual


def check_candidate(
    archive: Path,
    *,
    successor_files: Mapping[str, str] | None = None,
    previous_files: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Bind the admitted archive, field inventory and actual candidate script before reporting."""
    raw = version_contracts.research_path("situated", LEDGER).read_bytes()
    if hashlib.sha256(raw).hexdigest() != LEDGER_SHA256:
        raise ValueError("Reviewed writer inventory changed")
    rows = _inventory(raw)
    authority = {
        row["id"]
        for row in json.loads(engine_scope.company_default_snapshot())["implicit_companies"]
    }
    if len(rows) != 981 or len(authority) != 26:
        raise ValueError("Unexpected 3.4.0 writer or reviewed company denominator")
    with archive.open("rb") as stream:
        # Read the bounded, reviewed snapshot once, including its actual ZIP identity.
        payload = stream.read(862336 + 1)
    if hashlib.sha256(payload).hexdigest() != CANDIDATE_ZIP_SHA256:
        raise ValueError("Candidate ZIP differs from the independently reviewed archive")
    review = version_contracts.research_path("situated", "original-company-package-sources.json")
    members = verify_package_sources(
        payload, review.read_bytes(), trusted_review_sha256=REVIEW_SHA256
    )
    member = members[MEMBER]
    if successor_files is not None:
        files = {}
        for name, data in members.items():
            if name == "README.md":
                continue
            repo_bytes = (
                data.decode("utf-8-sig").encode() if name.endswith((".txt", ".yml")) else data
            )
            files[name] = hashlib.sha256(repo_bytes).hexdigest()
        if successor_files != files:
            raise ValueError("Successor lock does not describe the verified candidate payload")
    if hashlib.sha256(member).hexdigest() != MEMBER_SHA256:
        raise ValueError("Candidate company payload differs from its reviewed delivery bytes")
    _reconcile(rows, authority, _projected_targets(member))
    if successor_files is not None:
        previous_paths = {row[key] for row in rows for key in ("source", "published_output")}
        if previous_files is None or not previous_paths <= previous_files.keys():
            raise ValueError("Missing predecessor writer path coverage")
        actual = {name: previous_files[name] for name in previous_paths}
        encoded = json.dumps(actual, sort_keys=True, separators=(",", ":")).encode()
        if hashlib.sha256(encoded).hexdigest() != BASE_WRITER_OUTPUTS_SHA256:
            raise ValueError("Previous writer outputs differ from the reviewed 3.4.0 generation")
        _check_retirements(rows, previous_files.keys() - successor_files.keys())
    counts = Counter(row["candidate_disposition"] for row in rows)
    return {
        "schema": 1,
        "baseline_zip_sha256": BASE_ZIP_SHA256,
        "candidate_zip_sha256": CANDIDATE_ZIP_SHA256,
        "candidate_member_sha256": MEMBER_SHA256,
        "reviewed_payload_members": len(members),
        "package_source_review_sha256": REVIEW_SHA256,
        "writer_closure_sha256": CLOSURE_SHA256,
        "disposition_inventory_sha256": LEDGER_SHA256,
        "writers": len(rows),
        "source_paths": len({row["source"] for row in rows}),
        "published_output_paths": len({row["published_output"] for row in rows}),
        "candidate_static_projection": counts["candidate_static_projection"],
        "pending": counts["pending"],
        "pending_by_phase": dict(
            sorted(
                Counter(
                    row["phase"] for row in rows if row["candidate_disposition"] == "pending"
                ).items()
            )
        ),
        "release_disposition": "pending_product_evidence",
    }
