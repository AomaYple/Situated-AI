"""Audit every historical A0 identity against engineering and R2 boundaries.

The old 22,258 rows remain the denominator, independently pinned before the
current model is inspected. Equal signatures prove an identity comparison only.
The three-consumer R2 source grants no write permission to the broad compiler.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pdx.version_contracts import select_version
from tools.ci import architecture_inventory as a0

ROOT = a0.ROOT
AUTHORITY = ROOT / "research/situated/1.15.0/a0-disposition-authority.json"
AUTHORITY_SHA256 = "a710ec85e1c2efbe21ae63bd996846c2d25d5e659d115e6b8a07add51910c01f"

if TYPE_CHECKING:
    from pdx.situated.production_profile import ProductionProfile


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def identity(row: dict[str, Any]) -> tuple[str, ...]:
    """Stable namespaces; array offsets remain evidence, not matching keys."""
    kind = row["kind"]
    if kind == "physical_consumer":
        return kind, row["original"]["id"]
    if kind == "compiled_reader_binding":
        return kind, row["original_source"], row["id"]
    return tuple(row[key] for key in ("kind", "original_source", "original_pointer", "id"))


def semantic_record(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    if row["kind"] == "physical_consumer":
        result.pop("id")
    if row["kind"] == "compiled_reader_binding":
        result.pop("original_pointer")
    return result


def indexed(rows: list[dict[str, Any]]) -> dict[tuple[str, ...], dict[str, Any]]:
    result = {}
    for row in rows:
        key = identity(row)
        if key in result:
            raise ValueError(f"duplicate migration identity: {key}")
        result[key] = row
    return result


def load_authority(path: Path = AUTHORITY) -> dict[str, Any]:
    raw = path.read_bytes()
    if a0.digest(raw) != AUTHORITY_SHA256:
        raise ValueError("migration disposition authority byte drift")
    data = a0.read_inventory(raw)
    if (
        data.get("schema") != "situated-ai.a0-disposition-authority/1"
        or data.get("historical_version") != "1.14.5"
        or data.get("current_version") != "1.15.0"
        or data.get("runtime") != "unknown"
    ):
        raise ValueError("invalid migration disposition authority")
    return data


def validate_historical(historical: dict[str, Any], authority: dict[str, Any]) -> None:
    sources = {row["path"]: row for row in historical["sources"]}
    if (
        fingerprint(historical["rows"]) != authority["historical_rows_sha256"]
        or historical["counts"] != authority["historical_counts"]
        or any(sources.get(row["path"]) != row for row in authority["historical_sources"])
    ):
        raise ValueError("historical migration denominator or declaration source drift")
    indexed(historical["rows"])


def field_key(row: dict[str, Any]) -> tuple[str, tuple[str, ...]] | None:
    """Only exact physical fields can be linked to a new policy consumer."""
    value = row.get("original", {})
    source = row["original_source"]
    field = row.get("consumer_field")
    if row["kind"] == "physical_consumer":
        field = value["field"]
    elif row["kind"] in {
        "declared_binding",
        "declared_rule",
        "declared_initial_writer",
        "declared_scalar_writer",
    }:
        source = value.get("source", source)
        field = value.get("field")
    if not source or not field:
        return None
    parts = tuple(field.split(".")) if isinstance(field, str) else tuple(field)
    return source.removeprefix("game/"), parts


def r2_contract() -> dict[str, Any]:
    from pdx.situated import network_profile as net  # noqa: PLC0415
    from pdx.situated import production_profile as native  # noqa: PLC0415
    from pdx.situated import r2_reader_authority  # noqa: PLC0415

    with select_version("1.15.0"):
        native.verify_baseline()
        profile = native.load_profile(native.BASELINE_ROOT)
        programs = net.compile_profile(profile)
        generated = net.build(profile)
    by_consumer = {
        program.network.actions[0].definition.consumer_id: program for program in programs
    }
    rows = []
    for consumer in profile.declarations:
        program = by_consumer[consumer.id]
        rows.append(
            {
                "id": consumer.id,
                "source": consumer.source,
                "source_sha256": dict(profile.source_hashes)[consumer.source],
                "field": [consumer.definition, *consumer.field],
                "action": program.network.actions[0].definition.id,
                "bridges": [bridge.id for bridge in program.network.bridges],
                "policy_pointer": f"action/{program.network.actions[0].definition.id}",
                "runtime": "unknown",
            }
        )
    return {
        "source": net.SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256": a0.digest(net.SOURCE.read_bytes()),
        "adapter": "src/pdx/situated/network_profile.py",
        "adapter_sha256": a0.digest((ROOT / "src/pdx/situated/network_profile.py").read_bytes()),
        "reader_authority": r2_reader_authority.verify_frozen(),
        "consumers": rows,
        "native_preservation": native_preservation(profile, generated, native.BASELINE_ROOT),
    }


def native_preservation(
    profile: ProductionProfile, generated: dict[str, str], baseline: Path
) -> list[dict[str, Any]]:
    from pdx.situated import production_profile as native  # noqa: PLC0415

    if set(generated) != {row.source.removeprefix("game/") for row in profile.declarations}:
        raise ValueError("R2 output file set changes the reviewed native-retained boundary")
    result = []
    for row in profile.declarations:
        raw = (baseline / row.source).read_bytes()
        original = raw.decode("utf-8-sig")
        text = generated[row.source.removeprefix("game/")]
        restored = native.strip_policy(text, row)
        if restored != original:
            raise ValueError(f"R2 altered protected native content: {row.source}")
        result.append(
            {
                "source": row.source,
                "raw_native_sha256": a0.digest(raw),
                "generated_utf8_sha256": a0.digest(text.encode("utf-8")),
                "restored_utf8_sha256": a0.digest(restored.encode("utf-8")),
                "restored_equals_native": True,
                "boundary": "Exact text excluding the one identified R2 insertion; all other native text, qualifications, costs, random and execution tails are preserved.",
            }
        )
    return result


def validate_r2(r2: dict[str, Any], authority: dict[str, Any]) -> None:
    expected = {spec["id"].lower(): (spec["source"], tuple(spec["field"])) for spec in a0.SLICES}
    actual = {row["id"]: (row["source"], tuple(row["field"])) for row in r2["consumers"]}
    protection = r2.get("native_preservation", [])
    if (
        len(actual) != len(r2["consumers"])
        or actual != expected
        or sorted(actual) != sorted(authority["scope_decision"]["r2_production_consumers"])
        or r2["source"] != authority["scope_decision"]["policy_source"]
        or any(not row["action"] or not row["bridges"] for row in r2["consumers"])
        or len(protection) != len(actual)
        or {row["source"] for row in protection} != {row["source"] for row in r2["consumers"]}
        or any(row["restored_equals_native"] is not True for row in protection)
    ):
        raise ValueError("R2 policy consumer/action/bridge boundary drift")


def review(
    historical: dict[str, Any],
    current: dict[str, Any],
    authority: dict[str, Any],
    r2: dict[str, Any],
) -> dict[str, Any]:
    validate_historical(historical, authority)
    validate_r2(r2, authority)
    old_index = indexed(historical["rows"])
    current_index = indexed(current["rows"])
    exceptions = {}
    for entry in authority["exceptions"]:
        key = tuple(entry["identity"])
        if key in exceptions or key not in old_index:
            raise ValueError(f"duplicate or unknown disposition exception: {key}")
        exceptions[key] = entry
    used = set()
    declaration_hashes = {entry["path"]: entry["sha256"] for entry in historical["sources"]}
    policy_fields = {
        (row["source"].removeprefix("game/"), tuple(row["field"])): row for row in r2["consumers"]
    }
    redirects = {}
    for entry in authority.get("physical_redirects", []):
        point = entry["historical_source"], tuple(entry["historical_field"])
        policies = [row for row in r2["consumers"] if row["id"] == entry["r2_consumer"]]
        if point in redirects or len(policies) != 1 or not entry["rationale"]:
            raise ValueError("contradictory historical physical field redirect")
        redirects[point] = policies[0]
    rows = []
    for key, original in old_index.items():
        equivalent = current_index.get(key)
        old_sha = fingerprint(semantic_record(original))
        new_sha = fingerprint(semantic_record(equivalent)) if equivalent is not None else None
        change = exceptions.get(key)
        if old_sha != new_sha:
            if (
                change is None
                or change["historical_sha256"] != old_sha
                or change["current_sha256"] != new_sha
                or not change["rationale"].strip()
                or change["engineering_disposition"]
                != (
                    "retired_generated_identity"
                    if equivalent is None
                    else "version_specific_replacement"
                )
            ):
                raise ValueError(f"unreviewed engineering source/field/writer change: {key}")
            used.add(key)
        elif change is not None:
            raise ValueError(f"obsolete disposition exception: {key}")
        source = original["original_source"]
        declaration = declaration_hashes.get(source)
        source_sha = declaration or authority["historical_generated_sources"].get(
            source.removeprefix("mod/")
        )
        if source_sha is None:
            raise ValueError(f"historical source has no frozen artifact hash: {source}")
        original_point = field_key(original)
        policy = (
            (policy_fields.get(original_point) or redirects.get(original_point))
            if original_point is not None
            else None
        )
        rows.append(
            {
                "identity": list(key),
                "original": original,
                "original_record_sha256": fingerprint(original),
                "original_source_sha256": source_sha,
                "original_hash_kind": "declaration_bytes"
                if declaration
                else "historical_generated_artifact_bytes",
                "original_native_bytes": "not_claimed_by_generated_artifact_hash",
                "engineering_disposition": change["engineering_disposition"]
                if change
                else "identity_retained_in_compatibility_compiler",
                "engineering_current_identity": list(identity(equivalent)) if equivalent else None,
                "engineering_current_record_sha256": fingerprint(equivalent)
                if equivalent
                else None,
                "engineering_rationale": change["rationale"]
                if change
                else "Exact normalized identity/signature comparison; broad engineering compatibility only. This is not an unchanged policy or runtime semantic proof.",
                "r2_disposition": "replaced_by_action_bridge_policy"
                if policy
                else "retired_from_r2_policy_native_retained",
                "r2_mapping": policy,
                "r2_rationale": "Exact historical physical field is owned by the identified new action and bridges; old numerical policy is not inherited."
                if policy
                else authority["scope_decision"]["rationale"],
                "r2_business_semantics_inherited": False,
                "requirement_gap": False,
                "requirement_scope": "Explicit R2 three-consumer scope; native retention is signed only after all three real generated files restore their complete native text. This does not declare the historical broad policy portfolio implemented in R2.",
                "runtime": "unknown",
            }
        )
    if used != exceptions.keys():
        raise ValueError("unused migration disposition exception")
    return {
        "schema": "situated-ai.a0-current-dispositions/1",
        "evidence_kind": "static_check",
        "historical_rows_sha256": authority["historical_rows_sha256"],
        "historical_count": len(rows),
        "current_engineering_count": len(current_index),
        "engineering_dispositions": dict(Counter(row["engineering_disposition"] for row in rows)),
        "r2_dispositions": dict(Counter(row["r2_disposition"] for row in rows)),
        "scope_decision": authority["scope_decision"],
        "r2_contract": r2,
        "current_declaration_sources": current["sources"],
        "current_generator_sources": current.get("generator_sources", []),
        "current_model_source_fingerprints": current.get("model_source_fingerprints", {}),
        "current_native_adapter_sources": current.get("native_adapter_sources", {}),
        "current_native_adapter_hash_kind": "normalized UTF-8 text without BOM; original raw native hashes are recorded separately in current_native_sources",
        "historical_generator_sources": authority.get("historical_generators", []),
        "rows": rows,
        "new_engineering_identities": [
            list(key) for key in sorted(current_index.keys() - old_index.keys())
        ],
        "runtime": "unknown",
    }


def failure_dispositions(
    native: dict[str, Any], authority: dict[str, Any], consumed: set[str]
) -> list[dict[str, Any]]:
    files = {entry["path"]: entry for entry in native["files"]}
    expected = authority["original_scan_failures"]
    failures = {entry["path"]: entry for entry in native["failures"]}
    if len(failures) != len(native["failures"]) or set(failures) != {
        entry["failure"]["path"] for entry in expected
    }:
        raise ValueError("original scanner failure disappeared, duplicated or changed")
    results = []
    for entry in expected:
        path = entry["failure"]["path"]
        if (
            failures[path] != entry["failure"]
            or files[path]["sha256"] != entry["source_sha256"]
            or files[path]["bytes"] != entry["source_bytes"]
        ):
            raise ValueError(f"original scanner failure source/diagnostic drift: {path}")
        if path in consumed:
            raise ValueError(f"scanner failure overlaps consumed reader/writer source: {path}")
        impact = a0.classify_failures({"failures": [entry["failure"]]})[0]["impact"]
        if impact == "unclassified_requires_review":
            raise ValueError(f"unclassified scanner failure: {path}")
        results.append(
            {
                **entry,
                "impact": impact,
                "consumed_reader_writer_overlap": [],
                "closure": "Retain original failure and incomplete global catalog. No overlap with the captured source closure; selected consumer proof is independent. No claim that all engine consumers have been discovered.",
                "global_catalog": "incomplete",
                "runtime": "unknown",
            }
        )
    return results


def validate_report(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    indexed([row["original"] for row in actual["rows"]])
    if actual != expected:
        raise ValueError("missing, contradictory or drifted migration disposition")


def actor_boundary(observation: dict[str, Any]) -> dict[str, Any]:
    dynamic = [row for row in observation["rows"] if row["actor"] == "*DYNAMIC_COUNTRY*"]
    if (
        observation["dynamic_rows"] != len(a0.SLICES)
        or len(dynamic) != len(a0.SLICES)
        or {row["slice_id"] for row in dynamic} != {spec["id"] for spec in a0.SLICES}
    ):
        raise ValueError("dynamic country disposition coverage is incomplete")
    return {
        "static_actor_count": observation["actor_count"],
        "dynamic_rows": observation["dynamic_rows"],
        "runtime_actor_set": observation["runtime_actor_set"],
        "meaning": "All static tags and the dynamic wildcard share the same consumer contexts. Runtime existence, qualification and observations remain unknown.",
    }


def current_sources(native: dict[str, Any], consumed: set[str], game: Path) -> list[dict[str, str]]:
    """Bind every referenced native file, independently of the selected slices."""
    files = {entry["path"]: entry for entry in native["files"]}
    rows = []
    for relative in sorted(consumed):
        path = game / relative
        expected = files.get(relative)
        if (
            expected is None
            or not path.is_file()
            or path.resolve() != path.absolute()
            or not path.resolve().is_relative_to(game.resolve())
            or a0.digest(path.read_bytes()) != expected["sha256"]
        ):
            raise ValueError(f"consumed source identity drift: {relative}")
        rows.append({"path": relative, "sha256": expected["sha256"]})
    return rows


def consumed_sources(
    current: dict[str, Any], r2: dict[str, Any], engineering_hashes: dict[str, str]
) -> set[str]:
    """Keep every physical native root; only virtual evidence keys are excluded."""
    result = set()
    for source in {*engineering_hashes, *current.get("native_adapter_sources", {})}:
        if source.startswith("@"):
            continue
        path = Path(source)
        if path.is_absolute() or ".." in path.parts or "\\" in source:
            raise ValueError(f"invalid native source identity: {source}")
        result.add(
            source if source.startswith(("game/", "jomini/", "clausewitz/")) else "game/" + source
        )
    result.update(entry["path"] for entry in r2["reader_authority"]["files"])
    for row in current["rows"]:
        source = row["original_source"]
        if source.startswith("mod/"):
            continue
        if source.startswith("@"):
            raise ValueError(f"virtual identity used as a consumed row source: {source}")
        result.add(
            source if source.startswith(("game/", "jomini/", "clausewitz/")) else "game/" + source
        )
    return result


def validate_historical_artifacts(authority: dict[str, Any], root: Path = ROOT) -> None:
    for relative, expected in authority["historical_generated_sources"].items():
        path = root / "mod" / relative
        if (
            not path.is_file()
            or path.resolve() != path.absolute()
            or a0.digest(path.read_bytes()) != expected
        ):
            raise ValueError(f"historical generated artifact drift: {relative}")


def main() -> int:
    from pdx.situated import vanilla_inventory  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (
        args.output.resolve() == args.inventory.resolve()
        or args.output.resolve() != args.output.absolute()
    ):
        raise ValueError("disposition output would overwrite input or follow an unreviewed link")
    a0.validate_output(args.game_root, args.output.parent)
    inventory_raw = args.inventory.read_bytes()
    native = a0.read_inventory(inventory_raw)
    a0.validate_inventory(native, args.game_root)
    authority = load_authority()
    validate_historical_artifacts(authority)
    historical = a0.migration_inventory(version="1.14.5")
    current = a0.migration_inventory(version="1.15.0")
    r2 = r2_contract()
    report = review(historical, current, authority, r2)
    with select_version("1.15.0"):
        engineering_native = vanilla_inventory.discover(game=args.game_root / "game")
    report["engineering_native_source_hashes"] = engineering_native.source_hashes
    consumed = consumed_sources(current, r2, engineering_native.source_hashes)
    report["scan_failures"] = failure_dispositions(native, authority, consumed)
    report["current_native_sources"] = current_sources(native, consumed, args.game_root)
    observation = a0.observation_inventory(native, args.game_root)
    report["actor_boundary"] = actor_boundary(observation)
    report["authority_sha256"] = a0.digest(AUTHORITY.read_bytes())
    report["input_inventory_sha256"] = a0.digest(inventory_raw)
    report["producer_sha256"] = a0.digest(Path(__file__).read_bytes())
    a0.validate_inventory(native, args.game_root)
    if current_sources(native, consumed, args.game_root) != report["current_native_sources"]:
        raise ValueError("consumed native source closure changed during disposition generation")
    a0.write_json(args.output, report)
    print(
        json.dumps(
            {
                key: report[key]
                for key in ("historical_count", "engineering_dispositions", "r2_dispositions")
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
