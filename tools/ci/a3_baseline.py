"""Capture A3 independent vanilla inventory and current-source static costs.

This reuses production discovery/model loading and the PDX parser. It never
regenerates Mod files and does not measure engine execution or certify scope.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pdx import config
from pdx.situated import compiler, vanilla_inventory
from pdx.situated.resources import pdx_metrics

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def file_identity(paths: Iterable[Path], *, root: Path) -> dict[str, str]:
    """Fingerprint actual bytes, including existing generated artifacts."""
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(set(paths))
    }


def require_identity(before: Mapping[str, str], after: Mapping[str, str]) -> None:
    """Reject mixed snapshots if a shared source changes while collecting."""
    if before != after:
        changed = sorted(
            key for key in before.keys() | after.keys() if before.get(key) != after.get(key)
        )
        raise ValueError(f"采集中源身份漂移: {changed}")


def reader_metrics(rows: Sequence[tuple[str, str, tuple[Any, ...]]]) -> dict[str, Any]:
    """Use the production complete semantic signature, not only getter names."""
    counts: Counter[str] = Counter()
    declarations = []
    for source, key, signature in rows:
        if len(signature) != 10:
            raise ValueError("生产 reader signature 形状漂移；必须复核指标口径")
        canonical = _json(signature)
        counts[canonical] += 1
        declarations.append(
            {
                "source": source,
                "key": key,
                "signature": signature,
                "signature_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
            }
        )
    return {
        "declarations": len(rows),
        "unique_observation_signatures": len(counts),
        "duplicate_declarations": sum(value - 1 for value in counts.values()),
        "with_object_path": sum(bool(signature[7]) for _, _, signature in rows),
        "with_parameters": sum(bool(signature[9]) for _, _, signature in rows),
        "maximum_object_path_length": max(
            (len(signature[7]) for _, _, signature in rows), default=0
        ),
        "semantics": "duplicate declarations are not measured runtime repeat evaluations",
        "rows": declarations,
    }


def _write(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def capture(*, root: Path, game: Path, output: Path) -> dict[str, Any]:
    """Take one fresh discovery and one model snapshot with before/after hashes."""
    if root.resolve() != ROOT:
        raise ValueError("生产 loader 使用仓库固定入口，不支持混合 root")
    lock_path = root / "mod/generation-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    generated_paths = [root / "mod" / name for name in lock["files"]]
    source_paths = [
        *sorted((root / "src/pdx").rglob("*.py")),
        *sorted((root / "mod/decisions").glob("*.toml")),
        *[root / name for name in lock["sources"]],
        lock_path,
        Path(__file__).resolve(),
        *generated_paths,
    ]
    before = file_identity(source_paths, root=root)
    started = time.perf_counter()
    inventory = vanilla_inventory.discover(game=game)
    discovery_seconds = time.perf_counter() - started
    model_started = time.perf_counter()
    model = compiler.load_model()
    model_seconds = time.perf_counter() - model_started
    contract = model.contract()
    generated = {}
    for path in generated_paths:
        name = path.relative_to(root / "mod").as_posix()
        raw = path.read_bytes()
        row: dict[str, Any] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        if path.suffix == ".txt" and name.startswith(("common/", "events/")):
            row["pdx"] = pdx_metrics(raw.decode("utf-8-sig"))
        generated[name] = row
    bundle = model.consumer_ir
    if bundle is None:
        raise ValueError("缺少统一生产 writer bundle")
    by_consumer: dict[str, dict[str, int]] = {}
    for writer in bundle.writers:
        identity = f"{writer.source}#{writer.field}"
        counts = by_consumer.setdefault(identity, {"writers": 0, "predicate_sites": 0})
        counts["writers"] += 1
        counts["predicate_sites"] += len(
            writer.legacy.predicates if writer.legacy else writer.predicates
        )
    readers = reader_metrics(model.observation_contracts)
    source_mismatches = sorted(
        name for name, digest in lock["sources"].items() if before.get(name) != digest
    )
    generated_mismatches = sorted(
        name for name, digest in lock["files"].items() if generated[name]["sha256"] != digest
    )
    require_identity(before, file_identity(source_paths, root=root))
    vanilla = inventory.as_dict()
    for name, digest in inventory.source_hashes.items():
        if name.startswith("@engine/"):
            source = game.parent / name.removeprefix("@engine/")
        elif name.startswith("@version/"):
            source = game.parent / name.removeprefix("@version/")
        elif name.startswith("@evidence/"):
            source = root / name.removeprefix("@evidence/")
        else:
            source = game / name
        with source.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != digest:
            raise ValueError(f"采集中原版源身份漂移: {name}")
    report = {
        "schema": 1,
        "plan": "A3",
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "evidence": "current_checkout_static_baseline_not_release_or_engine_acceptance",
        "source_identity": before,
        "source_identity_sha256": hashlib.sha256(_json(before).encode()).hexdigest(),
        "generation_lock_source_mismatches": source_mismatches,
        "generation_lock_output_mismatches": generated_mismatches,
        "vanilla_scope_hash": inventory.scope_hash,
        "vanilla_discovered": inventory.discovered_count,
        "discovery_seconds": discovery_seconds,
        "model_seconds": model_seconds,
        "facts": len(model.facts),
        "action_kinds": dict(Counter(item.kind for item in model.action_instances)),
        "writer_kinds": dict(Counter(item.kind for item in bundle.writers)),
        "production_rule_count": model.production_rule_count,
        "production_consumers": len(model.production_consumers),
        "explicit_relations": len(model.relations),
        "relation_max_depth_policy": 2,
        "relation_max_depth_note": "existing contract limit, not measured economic feedback depth",
        "readers": readers,
        "per_consumer_declared_costs": by_consumer,
        "generated_files": generated,
        "generated_total_bytes": sum(row["bytes"] for row in generated.values()),
        "limits": [
            "current source may include in-progress changes; not the released 3.2.0 source",
            "generated artifacts are read as-is; no modgen or current-source equivalence claimed",
            "AST sites, reader declarations and predicate sites are not engine invocation counts",
            "persistent write sites include all selected PDX effects, not independent live states",
            "budget thresholds are not frozen here; no game performance acceptance",
            "runtime object counts, call frequency, effective active-strategy merging remain unknown",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    _write(output / "vanilla-inventory.json", vanilla)
    _write(output / "production-contract.json", contract)
    _write(output / "current-source-baseline.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "tools/out/a3/baseline")
    args = parser.parse_args(argv)
    if config.GAME is None:
        raise ValueError("缺少锁定原版，不能用冻结扫描冒充本次独立盘点")
    report = capture(root=ROOT, game=config.GAME, output=args.output)
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "source_identity_sha256",
                    "vanilla_discovered",
                    "production_rule_count",
                    "writer_kinds",
                    "generated_total_bytes",
                    "generation_lock_source_mismatches",
                    "generation_lock_output_mismatches",
                )
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
