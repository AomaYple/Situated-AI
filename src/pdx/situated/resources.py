"""Static generation budgets; these are syntax costs, never engine timings."""

from __future__ import annotations

import hashlib
import json
import tomllib
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pdx.model import Assignment, Block, Node, Scalar
from pdx.parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .compiler import SituatedModel

SOURCE = Path(__file__).resolve().parents[3] / "mod/decisions/static_resources.toml"
PERSISTENT_WRITES = frozenset(
    {
        "set_variable",
        "change_variable",
        "remove_variable",
        "clamp_variable",
        "set_global_variable",
        "change_global_variable",
        "remove_global_variable",
    }
)
SCAN_PREFIXES = ("any_", "every_", "random_", "ordered_")
WORLD_SCANS = frozenset({"any_country", "every_country", "random_country", "ordered_country"})
METRICS = frozenset(
    {
        "script_bytes",
        "assignment_nodes",
        "block_nodes",
        "scalar_nodes",
        "max_depth",
        "object_scan_sites",
        "persistent_write_sites",
        "world_country_scan_sites",
        "reader_declarations",
        "unique_reader_signatures",
        "reader_path_length",
        "explicit_relations",
    }
)


def pdx_metrics(text: str) -> dict[str, Any]:
    """Count one exact parsed AST; comments and quoted lookalikes are harmless."""
    parsed = parse_text(text)
    if parsed.errors:
        raise ValueError(f"生成脚本解析失败: {parsed.errors}")
    counts: Counter[str] = Counter()
    writes: Counter[str] = Counter()
    scans: Counter[str] = Counter()
    stack: list[Any] = [parsed.root]
    while stack:
        node = stack.pop()
        if isinstance(node, Assignment):
            counts["assignment_nodes"] += 1
            if node.key in PERSISTENT_WRITES:
                writes[node.key] += 1
            if node.key.startswith(SCAN_PREFIXES):
                scans[node.key] += 1
            if node.value is not None:
                stack.append(node.value)
        elif isinstance(node, Block):
            counts["block_nodes"] += 1
            stack.extend(node.items)
        elif isinstance(node, Scalar):
            counts["scalar_nodes"] += 1
    return {
        **{name: counts[name] for name in ("assignment_nodes", "block_nodes", "scalar_nodes")},
        "max_depth": parsed.max_depth,
        "object_scan_sites": sum(scans.values()),
        "object_scan_keys": dict(sorted(scans.items())),
        "persistent_write_sites": sum(writes.values()),
        "persistent_write_keys": dict(sorted(writes.items())),
    }


def load(path: Path = SOURCE) -> dict[str, Any]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if set(data) != {"schema", "baseline", "basis", "limits"} or data["schema"] != 1:
        raise ValueError("静态资源预算schema无效")
    if any(
        not isinstance(data[key], str) or not data[key].strip() for key in ("baseline", "basis")
    ):
        raise ValueError("静态资源预算必须声明独立基线和门限依据")
    if not isinstance(data["limits"], dict) or set(data["limits"]) != METRICS:
        raise ValueError("静态资源预算维度不能遗漏或暗加")
    if any(type(value) is not int or value < 0 for value in data["limits"].values()):
        raise ValueError("静态资源预算必须为非负整数")
    return data


def validate_metrics(metrics: Mapping[str, int], limits: Mapping[str, int]) -> None:
    if set(metrics) != METRICS or set(limits) != METRICS:
        raise ValueError("静态资源计数维度不完整")
    if any(type(value) is not int or value < 0 for value in metrics.values()):
        raise ValueError("静态资源计数不能缺失、为负或非整数")
    if exceeded := {
        key: (metrics[key], limits[key]) for key in sorted(METRICS) if metrics[key] > limits[key]
    }:
        raise ValueError(f"生成物超过冻结静态资源预算，须先复核语义和成本: {exceeded}")


def measure(files: Mapping[str, str], model: SituatedModel) -> dict[str, int]:
    totals = dict.fromkeys(METRICS, 0)
    for name, text in files.items():
        if not name.endswith(".txt") or not name.startswith(("common/", "events/")):
            continue
        metrics = pdx_metrics(text)
        totals["script_bytes"] += len(text.encode("utf-8"))
        for key in (
            "assignment_nodes",
            "block_nodes",
            "scalar_nodes",
            "object_scan_sites",
            "persistent_write_sites",
        ):
            totals[key] += metrics[key]
        totals["max_depth"] = max(totals["max_depth"], metrics["max_depth"])
        totals["world_country_scan_sites"] += sum(
            metrics["object_scan_keys"].get(key, 0) for key in WORLD_SCANS
        )
    observations = model.observation_contracts
    totals["reader_declarations"] = len(observations)
    totals["unique_reader_signatures"] = len({signature for _, _, signature in observations})
    totals["reader_path_length"] = max(
        (len(cast("tuple[str, ...]", signature[7])) for _, _, signature in observations), default=0
    )
    totals["explicit_relations"] = len(model.relations)
    return totals


def check(files: Mapping[str, str], model: SituatedModel) -> dict[str, object]:
    verify_inherited_writes(files)
    budget = load()
    metrics = measure(files, model)
    validate_metrics(metrics, budget["limits"])
    return {
        "evidence": "static_check",
        "metrics": metrics,
        "limits": budget["limits"],
        "baseline": budget["baseline"],
        "boundary": "AST/reader sites are not runtime calls, game duration or process memory",
    }


_NATIVE_SOURCE = SOURCE.parents[2] / "research/situated/victoria3-1.15.0-production-resources.json"
_NATIVE_SHA256 = "b7ca11e4210306601e6e86bfc363987985104b95b2bbc06e0ed144ebc4b72da0"
_NATIVE_SOURCES_SHA256 = "efbe20cb38a7d4531e9f2cd60c4e091490d33c98f9b319cb7620d1c65199f892"


def native_baseline() -> dict[str, Any]:
    """Pinned current sources authorize only their exact inherited operations."""
    raw = _NATIVE_SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != _NATIVE_SHA256:
        raise ValueError("当前原版资源基线漂移")
    data: dict[str, Any] = json.loads(raw)
    if (
        set(data)
        != {
            "schema",
            "evidence",
            "version",
            "candidate_files_sha256",
            "production_inputs_sha256",
            "metrics",
            "source_hashes",
            "inputs",
            "inherited_totals",
        }
        or data["schema"] != 1
        or data["version"] != "1.15.0"
        or data["evidence"] != "static_exact_current_native_operations_not_runtime"
        or data["inherited_totals"]
        != {"source_files": 17, "persistent_write_sites": 113, "world_country_scan_sites": 14}
        or set(data["metrics"]) != METRICS
        or hashlib.sha256(
            json.dumps(data["source_hashes"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        != _NATIVE_SOURCES_SHA256
        or set(data["inputs"]) != set(data["source_hashes"])
        or any(
            hashlib.sha256(text.encode()).hexdigest() != data["source_hashes"][source]
            for source, text in data["inputs"].items()
        )
    ):
        raise ValueError("当前原版资源基线来源或语义合同无效")
    return data


def _operations(text: str) -> Counter:
    def shape(node: Node | None) -> tuple | None:
        if node is None:
            return None
        if isinstance(node, Assignment):
            return (node.key, node.op, node.prefix, shape(node.value))
        if isinstance(node, Block):
            return tuple(shape(item) for item in node.items)
        return (node.text, node.quoted)

    parsed = parse_text(text)
    if parsed.errors:
        raise ValueError("继承原版变量写入的来源解析失败")
    result: Counter = Counter()
    stack: list[tuple[Node, tuple]] = [(parsed.root, ())]
    while stack:
        node, path = stack.pop()
        if isinstance(node, Assignment):
            if node.key in PERSISTENT_WRITES | WORLD_SCANS:
                result[(path, shape(node))] += 1
            if node.value is not None:
                stack.append((node.value, path))
        elif isinstance(node, Block):
            occurrences: Counter[str] = Counter()
            for index, item in enumerate(node.items):
                if isinstance(item, Assignment):
                    occurrences[item.key] += 1
                    identity = (item.key, item.op, item.prefix, occurrences[item.key])
                    stack.append((item, (*path, identity)))
                elif isinstance(item, Block):
                    # Anonymous blocks retain their exact sibling identity too.
                    stack.append((item, (*path, ("@anonymous", index))))
    return result


def verify_inherited_writes(files: Mapping[str, str]) -> None:
    """Every supplied script keeps exact native operations or has none.

    The 17 current native sources are finite identities, never spare slots.
    Unknown and Mod-owned scripts have no inherited write or world-scan rights.
    """
    inherited = native_baseline()["inputs"]
    for source, text in files.items():
        if not source.endswith(".txt") or not source.startswith(("common/", "events/")):
            continue
        actual = _operations(text)
        expected = _operations(inherited[source]) if source in inherited else Counter()
        if actual != expected:
            raise ValueError(
                f"继承变量或世界扫描身份、值或父路径改变：{source}；禁止借用原版额度新增状态或扫描"
            )
