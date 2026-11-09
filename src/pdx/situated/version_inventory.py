"""独立底本盘点：读取实际安装，不消费或刷新旧生成锁。

这是静态发现入口，不证明字段的引擎语义或消费者可写性。所有发现都指向
同一份已哈希原始字节；部分解析结果保留，但不能作为完整能力合同消费。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pdx.lexer import ATOM, EOF, LBRACE, OP, RBRACE, STRING, tokenize
from pdx.localization_languages import LANGUAGE_HEADER_RE
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_bytes
from pdx.scan import TEXT_SUFFIXES

SCHEMA = "situated-ai.native-inventory/1"
CONTENT_ROOTS = ("game", "clausewitz", "jomini")
REQUIRED_ROOTS = ("game/common", "game/events", "game/localization", "game/dlc", "launcher")
TEXT_EXTENSIONS = TEXT_SUFFIXES | {".dlc", ".gfx", ".lua", ".shader", ".fx", ".hlsl"}
PDX_EXTENSIONS = frozenset({".txt", ".gui", ".gfx", ".asset", ".settings", ".profile", ".dlc"})
IDENTITY_PATHS = (
    "launcher/launcher-settings.json",
    "binaries/checksum.txt",
    "caligula_branch.txt",
    "caligula_rev.txt",
    "clausewitz_branch.txt",
    "clausewitz_rev.txt",
)
# 非 ai_ 字段亦进入静态候选。字段名不是消费者合法性证明；所有其它字段
# 仍计入 field_index，避免把这个启发式集合冒充全量消费者分母。
CANDIDATE_FIELDS = frozenset(
    {
        "weight",
        "score",
        "chance",
        "random",
        "random_list",
        "random_valid",
        "selection_weight",
        "acceptance",
        "acceptance_score",
        "priority",
        "potential",
        "possible",
        "is_shown",
        "can_use",
        "on_action",
        "on_actions",
        "on_monthly_pulse",
        "on_weekly_pulse",
    }
)
REFERENCE_FIELDS = frozenset(
    {"has_dlc_feature", "has_dlc", "scripted_trigger", "scripted_effect", "scripted_value"}
)


def canonical_json(value: object) -> str:
    """稳定 JSON；不带机器路径、时间戳或运行耗时。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _linked_component(path: Path, installation: Path) -> str | None:
    """在读取身份文件之前检查每个组件，不能跟随父目录 junction。"""
    current = installation
    for part in path.relative_to(installation).parts:
        current /= part
        if current.is_symlink() or current.resolve() != current.absolute():
            return current.relative_to(installation).as_posix()
    return None


def _structure_diagnostics(raw: bytes) -> list[dict[str, Any]]:
    """补充宽容 AST 不报告的多余右括号、孤立运算符与缺失赋值。

    使用现有词法器，字符串与注释中的括号不会参与诊断；裸标量列表、
    匿名块和 hsv 等带类型的块保持合法。未闭合块继续由现有 parser 报告。
    """
    tokens = tokenize(raw.decode("utf-8-sig"))
    errors: list[dict[str, Any]] = []
    depth = 0
    for index, token in enumerate(tokens):
        if token.kind == LBRACE:
            depth += 1
        elif token.kind == RBRACE:
            if depth:
                depth -= 1
            else:
                errors.append(
                    {"kind": "unexpected_closing_brace", "line": token.line, "column": token.col}
                )
        elif token.kind == OP:
            previous_kind = tokens[index - 1].kind if index else EOF
            if previous_kind not in {ATOM, STRING}:
                errors.append(
                    {"kind": "missing_assignment_key", "line": token.line, "column": token.col}
                )
            if tokens[index + 1].kind not in {ATOM, STRING, LBRACE}:
                errors.append(
                    {"kind": "missing_assignment_value", "line": token.line, "column": token.col}
                )
    return errors


def _walk(root: Path, installation: Path, failures: list[dict[str, Any]]) -> list[Path]:
    """严格枚举；复用扫描模块的文本分类，补上其宽容遍历不报告的失败。"""
    paths: list[Path] = []
    if root.is_symlink() or root.resolve() != root.absolute():
        failures.append(
            {"kind": "unfollowed_link", "path": root.relative_to(installation).as_posix()}
        )
        return paths

    def on_error(error: OSError) -> None:
        filename = Path(error.filename) if error.filename else root
        failures.append(
            {
                "kind": "enumeration",
                "path": filename.relative_to(installation).as_posix(),
                "error": type(error).__name__,
                "errno": error.errno,
            }
        )

    for directory, directories, filenames in os.walk(root, followlinks=False, onerror=on_error):
        current = Path(directory)
        for name in list(directories):
            child = current / name
            if child.is_symlink() or child.resolve() != child.absolute():
                directories.remove(name)
                failures.append(
                    {"kind": "unfollowed_link", "path": child.relative_to(installation).as_posix()}
                )
        for name in filenames:
            child = current / name
            if child.is_symlink():
                failures.append(
                    {"kind": "unfollowed_link", "path": child.relative_to(installation).as_posix()}
                )
            else:
                paths.append(child)
    return sorted(paths)


def _source(
    path: str, sha256: str, assignment: Assignment, address: list[int], parents: list[str]
) -> dict[str, Any]:
    return {
        "path": path,
        "sha256": sha256,
        "line": assignment.line,
        "address": address,
        "parents": parents,
        "key": assignment.full_key,
        "operator": assignment.op,
    }


def _walk_ast(
    block: Block,
    path: str,
    sha256: str,
    result: dict[str, Any],
    field_counts: Counter[str],
    field_samples: dict[str, dict[str, Any]],
    address: list[int] | None = None,
    parents: list[str] | None = None,
) -> None:
    address = [] if address is None else address
    parents = [] if parents is None else parents
    siblings: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, item in enumerate(block.items):
        current_address = [*address, index]
        if isinstance(item, Block):
            _walk_ast(
                item,
                path,
                sha256,
                result,
                field_counts,
                field_samples,
                current_address,
                [*parents, "<anonymous>"],
            )
            continue
        if not isinstance(item, Assignment):
            continue
        source = _source(path, sha256, item, current_address, parents)
        siblings[item.full_key].append(source)
        field_counts[item.full_key] += 1
        field_samples.setdefault(item.full_key, source)
        if item.key.startswith("ai_") or item.key in CANDIDATE_FIELDS:
            result["consumer_candidates"].append(
                {
                    **source,
                    "value_kind": "block" if item.is_block else "scalar",
                    "scalar": item.value.unquoted if isinstance(item.value, Scalar) else None,
                    "discovery": "ai_field" if item.key.startswith("ai_") else "non_ai_field",
                    "semantic_status": "unknown",
                    "runtime_status": "unknown",
                }
            )
        if item.key in REFERENCE_FIELDS:
            result["reference_candidates"].append(
                {
                    **source,
                    "value": item.value.unquoted if isinstance(item.value, Scalar) else None,
                    "resolution_status": "unknown",
                }
            )
        if isinstance(item.value, Block):
            _walk_ast(
                item.value,
                path,
                sha256,
                result,
                field_counts,
                field_samples,
                current_address,
                [*parents, item.full_key],
            )
    for key, occurrences in sorted(siblings.items()):
        if len(occurrences) > 1:
            result["duplicate_fields"].append(
                {
                    "path": path,
                    "parents": parents,
                    "block_address": address,
                    "key": key,
                    "occurrences": occurrences,
                    "semantic_status": "unknown",
                }
            )


def _countries(root: Block, path: str, sha256: str, result: dict[str, Any]) -> None:
    for index, item in enumerate(root.items):
        if not isinstance(item, Assignment):
            continue
        if item.is_variable:
            result["actor_universe"]["excluded_definitions"].append(
                {
                    "key": item.key,
                    "path": path,
                    "line": item.line,
                    "reason": "script_variable_not_country_definition",
                }
            )
            continue
        source = _source(path, sha256, item, [index], [])
        if not isinstance(item.value, Block):
            result["failures"].append({"kind": "country_definition_shape", **source})
            continue
        country_types = [
            a.value.unquoted for a in item.value.all("country_type") if isinstance(a.value, Scalar)
        ]
        result["actor_universe"]["definitions"].append(
            {
                "actor": item.key,
                "source": source,
                "country_types": country_types,
                "eligibility": "unknown",
                "coverage_status": "unknown",
                "disposition": "vanilla_preserved_pending_actor_and_consumer_proof",
            }
        )


def _localization(raw: bytes, path: str, sha256: str, result: dict[str, Any]) -> None:
    text = raw.decode("utf-8-sig")
    headers = [
        {"header": match.group(1), "line": number, "path": path, "sha256": sha256}
        for number, line in enumerate(text.splitlines(), 1)
        if (match := LANGUAGE_HEADER_RE.match(line))
    ]
    result["localization"]["header_sources"].extend(headers)
    if not headers:
        result["localization"]["unclassified_files"].append(path)
    elif len(headers) != 1 and path.rsplit("/", 1)[-1] != "languages.yml":
        result["failures"].append({"kind": "localization_multiple_headers", "path": path})
    if path.rsplit("/", 1)[-1] == "languages.yml":
        result["localization"]["registry_sources"].extend(headers)


def _json_document(raw: bytes, path: str, result: dict[str, Any]) -> Any:
    """JSON 重复项也明确失败，避免 launcher 版本被最后一个同名键冒充。"""

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for key, value in pairs:
            if key in values:
                result["failures"].append(
                    {
                        "kind": "duplicate_json_field",
                        "path": path,
                        "key": key,
                        "previous": values[key],
                        "next": value,
                    }
                )
            values[key] = value
        return values

    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=object_pairs)


def _identity(
    raw: bytes, path: str, sha256: str, result: dict[str, Any], document: Any = None
) -> None:
    text = raw.decode("utf-8-sig")
    if path == "launcher/launcher-settings.json":
        data = document
        if not isinstance(data, dict):
            raise ValueError("launcher settings root must be an object")
        result["version_identity"]["launcher"] = {
            "path": path,
            "sha256": sha256,
            "fields": {
                key: data.get(key)
                for key in ("gameId", "version", "rawVersion", "dlcPath", "exePath", "gameDataPath")
            },
        }
    else:
        result["version_identity"]["files"].append(
            {"path": path, "sha256": sha256, "value": text.strip()}
        )


def _finish_languages(result: dict[str, Any]) -> None:
    directories: dict[str, set[str]] = defaultdict(set)
    for source in result["localization"]["header_sources"]:
        parts = source["path"].split("/")
        if (
            len(parts) > 3
            and parts[:2] == ["game", "localization"]
            and parts[2] not in {"jomini", "modifiers"}
        ):
            directories[parts[2]].add(source["header"])
    result["localization"]["languages"] = [
        {"directory": directory, "headers": sorted(headers), "evidence_status": "static_discovery"}
        for directory, headers in sorted(directories.items())
    ]
    for directory, headers in sorted(directories.items()):
        if len(headers) != 1:
            result["failures"].append(
                {
                    "kind": "localization_directory_conflict",
                    "directory": directory,
                    "headers": sorted(headers),
                }
            )
    if not directories:
        result["failures"].append(
            {"kind": "localization_no_languages", "path": "game/localization"}
        )


def inventory_installation(
    installation: Path, *, expected_version: str = "1.15.0"
) -> dict[str, Any]:
    """只读盘点完整安装根；不存在/失败均写入结果，结果不完整时不颁发能力。

    输入必须是包含 game/、launcher/ 的安装根。没有旧锁、旧快照或固定国家/
    语言列表回退。DLC 是磁盘内容，不推断所有权、启用状态或引擎覆盖顺序。
    """
    installation = installation.resolve()
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "evidence_kind": "static_check",
        "expected_version": expected_version,
        "scope": {
            "content_roots": list(CONTENT_ROOTS),
            "required_roots": list(REQUIRED_ROOTS),
            "text_extensions": sorted(TEXT_EXTENSIONS),
            "pdx_extensions": sorted(PDX_EXTENSIONS),
            "pdx_syntax_excluded_prefixes": ["game/licenses/"],
            "identity_paths": list(IDENTITY_PATHS),
            "exclusions": [
                "content-root files with unlisted suffixes (binary/media/unknown)",
                "installation paths outside declared content roots and identity paths",
                "symlinks and junctions are not followed and make enumeration incomplete",
            ],
            "consumer_candidate_rule": {"prefix": "ai_", "fields": sorted(CANDIDATE_FIELDS)},
            "field_index_source_sample_limit": 1,
            "consumer_denominator_status": "unknown_requires_semantic_and_indirect_reference_audit",
        },
        "scanner": {
            "module": "pdx.situated.version_inventory",
            "sources": [],
            "source_identity_scope": "all_pdx_python_sources_conservative_superset",
            "python_version": list(sys.version_info[:3]),
        },
        "roots": [],
        "files": [],
        "excluded_files": [],
        "failures": [],
        "version_identity": {"launcher": None, "files": []},
        "consumer_candidates": [],
        "reference_candidates": [],
        "duplicate_fields": [],
        "actor_universe": {
            "basis": "all_static_country_definitions_without_consumer_based_exclusion",
            "runtime_actor_set": "unknown_includes_dynamic_revolutions_and_civil_wars",
            "definitions": [],
            "excluded_definitions": [],
        },
        "localization": {
            "languages": [],
            "header_sources": [],
            "registry_sources": [],
            "unclassified_files": [],
            "configuration_entry_status": "unknown",
        },
        "dlc": {
            "descriptors": [],
            "ownership": "unknown",
            "enabled_state": "unknown",
            "load_order": "unknown",
        },
    }
    source_root = Path(__file__).resolve().parents[1]
    for source_path in sorted(source_root.rglob("*.py")):
        relative = source_path.relative_to(source_root).as_posix()
        result["scanner"]["sources"].append(
            {
                "path": f"src/pdx/{relative}",
                "sha256": _digest(source_path.read_bytes()),
            }
        )
    for root in (*CONTENT_ROOTS, *REQUIRED_ROOTS):
        present = (installation / root).is_dir()
        result["roots"].append({"path": root, "present": present})
        if not present:
            result["failures"].append({"kind": "missing_root", "path": root})
    paths: set[Path] = set()
    for root in CONTENT_ROOTS:
        if (installation / root).is_dir():
            paths.update(_walk(installation / root, installation, result["failures"]))
    for relative in IDENTITY_PATHS:
        path = installation / relative
        link_path = _linked_component(path, installation)
        if link_path is not None:
            result["failures"].append(
                {"kind": "unfollowed_link", "path": relative, "link_path": link_path}
            )
            continue
        if path.is_file() and not path.is_symlink():
            paths.add(path)
        else:
            result["failures"].append({"kind": "missing_identity_file", "path": relative})
    field_counts: Counter[str] = Counter()
    field_samples: dict[str, dict[str, Any]] = {}
    for path in sorted(paths):
        relative = path.relative_to(installation).as_posix()
        if path.suffix.lower() not in TEXT_EXTENSIONS and relative not in IDENTITY_PATHS:
            result["excluded_files"].append(
                {"path": relative, "reason": "unlisted_suffix", "suffix": path.suffix.lower()}
            )
            continue
        try:
            raw = path.read_bytes()
        except OSError as exc:
            result["failures"].append(
                {"kind": "read", "path": relative, "error": type(exc).__name__, "errno": exc.errno}
            )
            continue
        sha256 = _digest(raw)
        record: dict[str, Any] = {
            "path": relative,
            "sha256": sha256,
            "bytes": len(raw),
            "parse_status": "not_pdx",
        }
        result["files"].append(record)
        try:
            raw.decode("utf-8-sig", errors="strict")
            document = (
                _json_document(raw, relative, result) if path.suffix.lower() == ".json" else None
            )
            if relative in IDENTITY_PATHS:
                _identity(raw, relative, sha256, result, document)
            if (
                path.suffix.lower() in {".yml", ".yaml"}
                and "localization" in path.relative_to(installation).parts[:-1]
            ):
                _localization(raw, relative, sha256, result)
            if relative.startswith("game/dlc/") and (
                path.suffix.lower() == ".dlc" or path.name.endswith(".dlc.json")
            ):
                result["dlc"]["descriptors"].append(
                    {"path": relative, "sha256": sha256, "content_condition_status": "unknown"}
                )
            if path.suffix.lower() in PDX_EXTENSIONS and not relative.startswith("game/licenses/"):
                parsed = parse_bytes(raw, relative)
                structure_errors = _structure_diagnostics(raw)
                record["parse_status"] = (
                    "partial" if parsed.errors or structure_errors else "parsed"
                )
                record["parse_errors"] = parsed.errors
                record["structure_errors"] = structure_errors
                if structure_errors:
                    result["failures"].append(
                        {
                            "kind": "strict_parse",
                            "path": relative,
                            "sha256": sha256,
                            "errors": structure_errors,
                        }
                    )
                if parsed.errors:
                    result["failures"].append(
                        {"kind": "parse", "path": relative, "errors": parsed.errors}
                    )
                _walk_ast(parsed.root, relative, sha256, result, field_counts, field_samples)
                if "/common/country_definitions/" in relative:
                    _countries(parsed.root, relative, sha256, result)
        except (UnicodeError, ValueError, RecursionError) as exc:
            record["parse_status"] = "failed"
            result["failures"].append(
                {
                    "kind": "decode_or_parse",
                    "path": relative,
                    "error": type(exc).__name__,
                    "detail": str(exc),
                }
            )
    _finish_languages(result)
    launcher = result["version_identity"]["launcher"]
    actual_version = launcher["fields"].get("rawVersion") if launcher else None
    result["version_identity"]["version_match"] = actual_version == expected_version
    if actual_version != expected_version:
        result["failures"].append(
            {"kind": "version_mismatch", "expected": expected_version, "actual": actual_version}
        )
    for identity in result["version_identity"]["files"]:
        if identity["path"].endswith("_branch.txt"):
            versions = re.findall(r"(?<!\d)(\d+\.\d+\.\d+)(?!\d)", identity["value"])
            if versions and versions != [expected_version]:
                result["failures"].append(
                    {
                        "kind": "version_source_conflict",
                        "path": identity["path"],
                        "expected": expected_version,
                        "found": versions,
                    }
                )
    result["field_index"] = [
        {"key": key, "occurrences": count, "source_sample": field_samples[key]}
        for key, count in sorted(field_counts.items())
    ]
    actors = sorted({definition["actor"] for definition in result["actor_universe"]["definitions"]})
    if not actors:
        result["failures"].append(
            {"kind": "no_country_definitions", "path": "game/common/country_definitions"}
        )
    result["actor_universe"]["actors"] = actors
    result["actor_universe"]["duplicate_actor_definitions"] = [
        {
            "actor": actor,
            "sources": [
                definition["source"]
                for definition in result["actor_universe"]["definitions"]
                if definition["actor"] == actor
            ],
        }
        for actor, count in sorted(
            Counter(
                definition["actor"] for definition in result["actor_universe"]["definitions"]
            ).items()
        )
        if count > 1
    ]
    for source in result["scanner"]["sources"]:
        current = _digest((source_root / source["path"].removeprefix("src/pdx/")).read_bytes())
        if current != source["sha256"]:
            result["failures"].append(
                {"kind": "scanner_source_changed_during_scan", "path": source["path"]}
            )
    result["status"] = (
        "incomplete" if result["failures"] else "static_inventory_complete_semantics_unknown"
    )
    result["failures"].sort(key=canonical_json)
    result["summary"] = {
        "hashed_files": len(result["files"]),
        "hashed_bytes": sum(record["bytes"] for record in result["files"]),
        "excluded_files": len(result["excluded_files"]),
        "failures": len(result["failures"]),
        "consumer_candidates": len(result["consumer_candidates"]),
        "field_names": len(field_counts),
        "assignments": sum(field_counts.values()),
        "duplicate_field_groups": len(result["duplicate_fields"]),
        "country_definitions": len(result["actor_universe"]["definitions"]),
        "actors": len(actors),
        "languages": len(result["localization"]["languages"]),
        "dlc_descriptors": len(result["dlc"]["descriptors"]),
    }
    result["inventory_sha256"] = _digest(canonical_json(result).encode("utf-8"))
    return result


def main() -> int:
    """独立命令入口；失败报告仍可导出，退出码为 1。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installation", type=Path)
    parser.add_argument("--expected-version", default="1.15.0")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if arguments.output and arguments.output.resolve().is_relative_to(
        arguments.installation.resolve()
    ):
        parser.error("output must be outside the read-only game installation")
    result = inventory_installation(
        arguments.installation, expected_version=arguments.expected_version
    )
    output = canonical_json(result)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(output, encoding="utf-8", newline="\n")
    else:
        print(output, end="")
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
