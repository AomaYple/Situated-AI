"""Read-only, per-writer evidence for successors of the 3.4.0 release."""

from __future__ import annotations

import codecs
import csv
import hashlib
import io
import json
import stat
import zipfile
from collections import Counter
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from pdx import config, distribution, version_contracts
from pdx.input_inventory import open_inventory_source
from pdx.model import Assignment, Block, Node, Scalar
from pdx.parser import parse_text
from pdx.situated import engine_scope
from pdx.successor_sources import object_from_json, sha256

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

BASE_RELEASE_COMMIT = "e14d5bd1085e5727274f74c5f82876608df148f0"
BASE_WRITERS = 981
# Raw hashes for the 77 ledger sources, selected from the frozen installation catalog
# fixed by COMPLETE.json d20a3022b4b4dc6a6b04722d75feadc135fb343634f757c2960153fa0c89e315.
BASE_NATIVE_SOURCES_SHA256 = "e497e11556ca99eb93a0e9f6e7dff50e2790a79e79e92f010c52e443f9d42665"
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
    record = object_from_json(review)
    if record.get("schema") not in (1, 2) or sha256(archive) != record.get("archive_sha256"):
        raise ValueError("Package differs from reviewed archive")
    members = _required_record(record, "members")
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        entries = bundle.infolist()
        names = [entry.filename for entry in entries]
        if any(
            entry.orig_filename != entry.filename
            or entry.is_dir()
            or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG)
            for entry in entries
        ):
            raise ValueError("ZIP contains a redirected or non-regular member")
        distribution._validate_paths(names)
        name_set = {name.casefold() for name in names}
        if any(
            parent.as_posix().casefold() in name_set
            for name in names
            for parent in PurePosixPath(name).parents
        ):
            raise ValueError("ZIP file conflicts with an ancestor path")
        if set(names) != {*members, distribution.MANIFEST_NAME}:
            raise ValueError("Package source coverage differs from archive members")
        manifest = bundle.read(distribution.MANIFEST_NAME)
        if hashlib.sha256(manifest).hexdigest() != record.get("manifest_sha256"):
            raise ValueError("Package manifest differs from reviewed bytes")
        actual = {name: bundle.read(name) for name in members}
    hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in actual.items()}
    description = object_from_json(manifest)
    if description.get("files") != hashes or any(
        not isinstance(row, dict)
        or hashes[name] != row.get("delivery_sha256")
        or not isinstance(row.get("origin"), str)
        or not row["origin"].strip()
        for name, row in members.items()
    ):
        raise ValueError("Package member differs from reviewed source or manifest")
    if record["schema"] == 2:
        generation = description.get("generation")
        if generation is not None and not isinstance(generation, dict):
            raise ValueError("Invalid candidate manifest generation")
        expected = distribution._manifest_for_payloads(actual, generation=generation)
        if description != expected:
            raise ValueError("Candidate manifest differs from the standard package contract")
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
    if len(rows) != BASE_WRITERS or len(authority) != 26:
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


def _writer_id(row: Mapping[str, str]) -> tuple[str, str, str]:
    return row["source"], row["definition"], row["field"]


def _database(path: str) -> str:
    parts = path.split("/")
    return "/".join(parts[:2]) if len(parts) >= 3 and parts[0] == "common" else ""


def _shape(node: Node | None) -> object:
    if isinstance(node, Assignment):
        return [node.full_key, node.op, _shape(node.value)]
    if isinstance(node, Block):
        return [_shape(item) for item in node.items]
    if isinstance(node, Scalar):
        return node.text
    return None


def _ast_sha256(node: Node | None) -> str:
    return sha256(json.dumps(_shape(node), ensure_ascii=False, separators=(",", ":")).encode())


def _script_index(members: Mapping[str, bytes]) -> dict[str, dict[str, list[Assignment]]]:
    scripts: dict[str, dict[str, list[Assignment]]] = {}
    for name, raw in members.items():
        if not _database(name) or not name.lower().endswith(".txt"):
            continue
        script = parse_text(raw.decode("utf-8-sig"), name)
        script.require_complete()
        definitions: dict[str, list[Assignment]] = {}
        for definition in script.top_assignments:
            definitions.setdefault(definition.key, []).append(definition)
        scripts[name] = definitions
    return scripts


def _native_sources(
    rows: Sequence[Mapping[str, str]], installation: Path | None
) -> dict[str, bytes]:
    verified = version_contracts.verify_installation_identity(
        config.ROOT if installation is None else installation
    )
    originals = {}
    for path in sorted({row["source"] for row in rows}):
        with open_inventory_source(verified.root, f"game/{path}") as stream:
            originals[path] = stream.read()
    raw_hashes = {path: sha256(raw) for path, raw in originals.items()}
    aggregate = sha256(json.dumps(raw_hashes, sort_keys=True, separators=(",", ":")).encode())
    if aggregate != BASE_NATIVE_SOURCES_SHA256:
        raise ValueError("Locked original writer sources differ from the frozen installation")
    if version_contracts.verify_installation_identity(verified.root) != verified:
        raise ValueError("Original installation identity changed during writer verification")
    return originals


def _require_original_slot(
    source: str, originals: Mapping[str, bytes], successor: Mapping[str, bytes]
) -> None:
    overwritten = next((path for path in successor if path.casefold() == source.casefold()), None)
    if overwritten is None:
        return
    old = parse_text(originals[source].decode("utf-8-sig"), source)
    new = parse_text(successor[overwritten].decode("utf-8-sig"), overwritten)
    old.require_complete()
    new.require_complete()
    if _shape(old.root) != _shape(new.root):
        raise ValueError(f"Candidate masks the native source path: {source}")


def _references(node: Node | None, name: str) -> bool:
    if isinstance(node, Scalar):
        return node.unquoted == name
    if isinstance(node, Assignment):
        return _references(node.value, name)
    return isinstance(node, Block) and any(_references(item, name) for item in node.items)


def _require_linked_helper(
    assignment: Assignment,
    helper: Assignment | None,
    scripts: Mapping[str, dict[str, list[Assignment]]],
) -> None:
    if helper is None or not _references(assignment, helper.key):
        return
    candidates = _definitions(scripts, "common/script_values", helper.key)
    if len(candidates) != 1 or _shape(candidates[0][1]) != _shape(helper):
        raise ValueError(
            f"Projected writer has a missing, ambiguous or changed helper: {helper.key}"
        )


def _field(definition: Assignment, name: str) -> Assignment | None:
    result = definition
    for key in name.split(".") if name else ():
        matches = result.value.all(key) if isinstance(result.value, Block) else []
        if len(matches) > 1:
            raise ValueError(f"Ambiguous field {definition.key}.{name}")
        if not matches:
            return None
        result = matches[0]
    return result


def _previous_assignment(
    row: Mapping[str, str], scripts: Mapping[str, dict[str, list[Assignment]]]
) -> tuple[Assignment, Assignment | None]:
    path, definition, field = _writer_id(row)
    matches = scripts[path].get(definition, [])
    assignment = _field(matches[0], field) if len(matches) == 1 else None
    if assignment is None:
        raise ValueError(f"Cannot resolve predecessor field: {path}/{definition}.{field}")
    if row["published_output"] == path:
        return assignment, None
    linked = assignment.value
    if isinstance(linked, Scalar):
        helpers = scripts[row["published_output"]].get(linked.unquoted, [])
        if len(helpers) == 1:
            return assignment, helpers[0]
    raise ValueError(f"Cannot resolve predecessor helper: {path}/{definition}.{field}")


def _definitions(
    scripts: Mapping[str, dict[str, list[Assignment]]], database: str, definition: str
) -> list[tuple[str, Assignment]]:
    return [
        (path, entry)
        for path, contents in scripts.items()
        if _database(path) == database
        for entry in contents.get(definition, ())
    ]


def _candidate_sites(
    definitions: Sequence[tuple[str, Assignment]], field: str
) -> list[tuple[str, Assignment, Assignment]]:
    sites = []
    for member, entry in definitions:
        assignment = _field(entry, field)
        if assignment is not None:
            sites.append((member, entry, assignment))
    return sites


def _original_site(
    scripts: Mapping[str, dict[str, list[Assignment]]],
    key: tuple[str, str, str],
    old: Assignment,
    helper_path: str,
    helper: Assignment | None,
) -> str:
    path, definition, field = key
    if path not in scripts:
        return "path_removed"
    definitions = scripts[path].get(definition, [])
    if not definitions:
        return "definition_removed"
    if len(definitions) != 1:
        return "ambiguous_definition"
    current = _field(definitions[0], field)
    if current is None:
        return "field_removed"
    if helper is not None:
        helpers = scripts.get(helper_path, {}).get(helper.key, [])
        if len(helpers) != 1 or _shape(helpers[0]) != _shape(helper):
            return "helper_removed_or_changed"
    return "field_unchanged" if _shape(current) == _shape(old) else "field_changed"


def _projection(
    target: Mapping[str, Any],
    sites: Sequence[tuple[str, Assignment, Assignment]],
    definitions: Sequence[tuple[str, Assignment]],
) -> tuple[str, Assignment]:
    if len(sites) != 1 or len(definitions) != 1:
        raise ValueError("Missing, duplicate or ambiguous projected writer")
    path, definition, assignment = sites[0]
    if (
        target.get("member") != path
        or target.get("prefix") != definition.prefix
        or target.get("definition_sha256") != _ast_sha256(definition)
        or definition.op != "="
        or assignment.op != "="
    ):
        raise ValueError(
            f"Projected writer differs from reviewed AST mapping: {path}/{definition.key}"
        )
    return path, definition


def _check_equivalence(
    row: Mapping[str, str],
    decision: Mapping[str, Any],
    mechanisms: Mapping[str, Any],
    path: str,
    definition: Assignment,
    original: Assignment | None,
) -> str:
    mechanism_id = decision.get("mechanism")
    mechanism = mechanisms.get(mechanism_id) if isinstance(mechanism_id, str) else None
    if mechanism is None:
        raise ValueError("Missing independently reviewed equivalence mechanism")
    database = _database(row["source"])
    expected = {
        "database": database,
        "depth": len(row["field"].split(".")),
        "phase": row["phase"],
        "placement": row["placement"],
        "transform": row["transform"],
        "prefix": definition.prefix,
    }
    if any(mechanism.get(key) != value for key, value in expected.items()):
        raise ValueError(f"Inapplicable reviewed equivalence mechanism: {mechanism_id}")
    if mechanism.get("scope") != decision.get("scope") or not mechanism.get("scope"):
        raise ValueError(f"Writer scope is outside equivalence mechanism: {mechanism_id}")
    load_order = mechanism.get("load_order")
    after_original = (
        definition.prefix in {"INJECT", "REPLACE"} and path.casefold() > row["source"].casefold()
    )
    same_path = definition.prefix is None and path == row["source"]
    if not (
        (load_order == "after_original" and after_original)
        or (load_order == "same_source_slot" and same_path)
    ):
        raise ValueError(f"Projected writer has an unproved load order: {path}")
    original_value = None if original is None else original.value
    if decision.get("original_value_sha256") != _ast_sha256(original_value):
        raise ValueError("Reviewed original value differs from the locked native field")
    assert isinstance(mechanism_id, str)
    return mechanism_id


def _required_record(record: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = record.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"Expected reviewed object: {key}")
    return value


def _required_rows(record: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    items = record.get(key)
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ValueError(f"Expected reviewed rows: {key}")
    return items


def _read_reviewed_decisions(
    rows: Sequence[Mapping[str, str]], record: Mapping[str, Any]
) -> dict[tuple[str, str, str], dict[str, Any]]:
    decisions: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in _required_rows(record, "writers"):
        source, definition, field = (item.get(key) for key in ("source", "definition", "field"))
        if (
            not isinstance(source, str)
            or not isinstance(definition, str)
            or not isinstance(field, str)
        ):
            raise ValueError("Invalid reviewed writer identity")
        key = (source, definition, field)
        if key in decisions:
            raise ValueError(f"Invalid or duplicate reviewed writer: {key}")
        decisions[key] = item
    expected = {_writer_id(row) for row in rows}
    if decisions.keys() != expected:
        omitted = sorted(expected - decisions.keys())
        extra = sorted(decisions.keys() - expected)
        raise ValueError(
            f"Reviewed writer coverage differs; omitted={omitted[:3]}, extra={extra[:3]}"
        )
    return decisions


def _check_evidence(item: Mapping[str, Any], read_blob: Callable[[str], bytes]) -> str:
    evidence = _required_record(item, "evidence")
    path = evidence.get("path")
    if not isinstance(path, str):
        raise ValueError("Disposition lacks an independently reviewed evidence path")
    distribution._validate_paths([path])
    if sha256(read_blob(path)) != evidence.get("sha256"):
        raise ValueError(f"Disposition evidence bytes differ from review: {path}")
    return path


def _effective_payload(path: str, raw: bytes) -> object:
    if path.startswith(("common/", "localization/")):
        return raw or None
    if path != distribution.METADATA_NAME or not raw:
        return None
    metadata = object_from_json(raw)
    custom = _required_record(metadata, "game_custom_data")
    # Build configuration and presentation fields have their own package-level review.
    return metadata["relationships"], {
        key: value for key, value in custom.items() if key != "configuration"
    }


def reconcile_successor_writers(
    previous: Mapping[str, bytes],
    successor: Mapping[str, bytes],
    rows: Sequence[Mapping[str, str]],
    record: Mapping[str, Any],
    read_blob: Callable[[str], bytes],
    *,
    installation: Path | None = None,
) -> dict[str, object]:
    """Require each frozen old physical writer to receive its own evidenced disposition."""
    old_scripts = _script_index(previous)
    new_scripts = _script_index(successor)
    decisions = _read_reviewed_decisions(rows, record)
    mechanisms = _required_record(record, "mechanisms")
    requires_originals = any(
        item.get("status") in ("equivalent", "retain_vanilla") for item in decisions.values()
    )
    originals = _native_sources(rows, installation) if requires_originals else {}
    native_scripts = _script_index(originals)
    results = []
    occupied: set[tuple[str, str, str]] = set()
    grouped: Counter[str] = Counter()
    checked_original_slots: set[str] = set()
    for row in rows:
        key = _writer_id(row)
        source, name, field = key
        database = _database(source)
        old, helper = _previous_assignment(row, old_scripts)
        definitions = _definitions(new_scripts, database, name)
        sites = _candidate_sites(definitions, field)
        item = decisions[key]
        status = item.get("status")
        native_field = None
        if status in ("equivalent", "retain_vanilla"):
            native = native_scripts[source].get(name, [])
            if len(native) != 1 or native[0].prefix is not None:
                raise ValueError(f"Unproved locked original definition: {key}")
            native_field = _field(native[0], field)
        result: dict[str, object] = {
            "writer": key,
            "status": status,
            "previous_site": _original_site(new_scripts, key, old, row["published_output"], helper),
            "candidate_sites": [path for path, _, _ in sites],
        }
        if status in ("static_projection", "equivalent"):
            location, definition = _projection(_required_record(item, "target"), sites, definitions)
            physical = (location, name, field)
            if physical in occupied:
                raise ValueError(f"Candidate writer maps to multiple old writers: {physical}")
            occupied.add(physical)
            if status == "equivalent":
                mechanism = _check_equivalence(
                    row, item, mechanisms, location, definition, native_field
                )
                if location != source and source not in checked_original_slots:
                    _require_original_slot(source, originals, successor)
                    checked_original_slots.add(source)
                assignment = sites[0][2]
                _require_linked_helper(assignment, helper, new_scripts)
                if item["contribution_sha256"] != _ast_sha256(assignment):
                    raise ValueError(f"Projected contribution AST differs from review: {physical}")
                result["evidence"] = _check_evidence(mechanisms[mechanism], read_blob)
                grouped[mechanism] += 1
        elif status in ("retain_vanilla", "withdrawn"):
            if status == "retain_vanilla":
                if source not in checked_original_slots:
                    _require_original_slot(source, originals, successor)
                    checked_original_slots.add(source)
                top_field = field.split(".", 1)[0]
                if any(
                    path != source and (entry.prefix != "INJECT" or _field(entry, top_field))
                    for path, entry in definitions
                ):
                    raise ValueError(f"Candidate changes the recorded retirement target: {key}")
            elif sites:
                raise ValueError(f"Candidate changes the recorded retirement target: {key}")
            reason = item.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError(f"Disposition requires an independently reviewed reason: {key}")
            if status == "withdrawn":
                authority = item.get("authorized_by")
                if not isinstance(authority, str) or not authority.strip():
                    raise ValueError(f"Withdrawal lacks product authorization: {key}")
            result["evidence"] = _check_evidence(item, read_blob)
        elif status != "pending":
            raise ValueError(f"Invalid writer disposition: {key}/{status}")
        results.append(result)

    legacy_sites = {(_database(path), definition, field) for path, definition, field in decisions}
    opportunities = []
    for item in _required_rows(record, "opportunities"):
        member, new_definition, new_field = (
            item.get(key) for key in ("member", "definition", "field")
        )
        if not (
            isinstance(member, str)
            and isinstance(new_definition, str)
            and isinstance(new_field, str)
            and member
            and new_definition
            and new_field
        ):
            raise ValueError("New opportunity requires its own member, definition and field")
        if (_database(member), new_definition, new_field) in legacy_sites:
            raise ValueError("New opportunity cannot dispose an old writer")
        definitions = _definitions(new_scripts, _database(member), new_definition)
        sites = _candidate_sites(definitions, new_field)
        location, _ = _projection(item, sites, definitions)
        physical = (location, new_definition, new_field)
        if physical in occupied:
            raise ValueError(f"Duplicate new opportunity: {physical}")
        occupied.add(physical)
        opportunities.append({"site": physical, "evidence": _check_evidence(item, read_blob)})
    covered_paths = {row[key] for row in rows for key in ("source", "published_output")}
    retired_payloads = {
        path
        for path in previous.keys() - covered_paths
        if _effective_payload(path, previous[path])
        != _effective_payload(path, successor.get(path, b"").removeprefix(codecs.BOM_UTF8))
    }
    auxiliary = {}
    for item in _required_rows(record, "auxiliary_retirements"):
        path = item.get("path")
        reason = item.get("reason")
        if (
            not isinstance(path, str)
            or path not in retired_payloads
            or path in auxiliary
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise ValueError(f"Invalid auxiliary payload disposition: {path}")
        auxiliary[path] = _check_evidence(item, read_blob)

    counts = Counter(str(item["status"]) for item in results)
    pending = counts["pending"] + counts["static_projection"]
    if not rows:
        raise ValueError("Writer reconciliation requires the frozen predecessor inventory")
    unresolved_payloads = sorted(retired_payloads - auxiliary.keys())
    complete = pending == 0 and not unresolved_payloads
    return {
        "writer_counts": dict(sorted(counts.items())),
        "writers": results,
        "equivalence_groups": dict(sorted(grouped.items())),
        "new_opportunities": opportunities,
        "unresolved_writers": pending,
        "reviewed_auxiliary_retirements": auxiliary,
        "unresolved_auxiliary_retirements": unresolved_payloads,
        "verified_original_sources": len(originals),
        "writer_disposition_complete": complete,
        "acceptance": {
            "E": "frozen_bytes_sources_and_syntax_checked",
            "M": "independent_writer_disposition_checked" if complete else "pending",
            "R": "outside_scope",
            "U": "outside_scope",
        },
    }
