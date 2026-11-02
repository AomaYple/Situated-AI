"""Immutable historical identities, independent of the current production source.

The manifest was extracted from the published v3.0.1 commit, not reconstructed
from today's rules. It freezes identities and consumer contracts, not values:
intentional semantic repairs still require their own counterfactual receipts.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .decision_ir import ConsumerIRBundle, WriterDecisionIR

DEFAULT_SOURCE = Path(__file__).resolve().parents[3] / "research/situated/v3.0.1-migration.json"
RETIREMENTS_SOURCE = DEFAULT_SOURCE.with_name("a2-retirements.json")
_MANIFEST_SHA256 = "fcce11e045e9933c13644a361da3a448330208c0b712ac3df615eed307aa55e6"
_RETIREMENTS_SHA256 = "11672a5d20bd20d9d21db36858ba5ded7a9e659462e2a26c3f5470941e8766f1"
_COMMIT = "74492fc05321c0767cb07202a91797a7663e7ee0"
_FIELDS = ("source", "definition", "field", "actor", "target", "operation")
_TAIL = "retain_original_qualification_cost_random_execution"


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"历史规则退役 manifest JSON 键重复：{key}")
        result[key] = value
    return result


def _string_list(value: Any, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
        or len(value) != len(set(value))
    ):
        raise ValueError(f"历史规则退役 {label} 必须是非空且无重复的字符串列表")
    return value


def _validate_test_identity(identity: str) -> None:
    source, *names = identity.split("::")
    relative = PurePosixPath(source)
    repo = DEFAULT_SOURCE.parents[2]
    test = (repo / source).resolve()
    if (
        relative.is_absolute()
        or "\\" in source
        or ".." in relative.parts
        or not relative.parts
        or relative.parts[0] != "tests"
        or not relative.name.startswith("test_")
        or relative.suffix != ".py"
        or not test.is_relative_to((repo / "tests").resolve())
        or not test.is_file()
        or len(names) > 2
    ):
        raise ValueError(f"历史规则退役测试身份不存在或不合法：{identity}")
    try:
        tree = ast.parse(test.read_text(encoding="utf-8"), filename=str(test))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise ValueError(f"历史规则退役测试来源无法解析：{identity}") from exc
    body = tree.body
    if len(names) == 2:
        classes = [
            item for item in body if isinstance(item, ast.ClassDef) and item.name == names[0]
        ]
        if len(classes) != 1:
            raise ValueError(f"历史规则退役测试类身份不存在：{identity}")
        body = classes[0].body
    functions = [
        item for item in ast.walk(tree) if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if names:
        functions = [
            item
            for item in body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == names[-1]
        ]
    if not any(item.name.startswith("test_") for item in functions):
        raise ValueError(f"历史规则退役测试函数身份不存在：{identity}")


def _retired_identities(
    historical: dict[str, Any],
    current: dict[tuple[str, str], WriterDecisionIR],
    present: set[tuple[str, str]],
    *,
    path: Path,
) -> set[tuple[str, str]]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError(f"历史规则退役 manifest 缺失：{path}") from exc
    # Explicit alternate paths permit isolated contract fixtures. The published
    # historical manifest remains pinned for every path, including fixtures.
    if (
        path.resolve() == RETIREMENTS_SOURCE.resolve()
        and hashlib.sha256(raw).hexdigest() != _RETIREMENTS_SHA256
    ):
        raise ValueError("历史规则退役 manifest 原始字节漂移：A2")
    try:
        data = json.loads(raw, object_pairs_hook=_unique_json_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("历史规则退役 manifest 无法解析") from exc
    if (
        not isinstance(data, dict)
        or set(data) != {"schema", "baseline_tag", "retirements"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or data["baseline_tag"] != "v3.0.1"
        or not isinstance(data["retirements"], list)
    ):
        raise ValueError("历史规则退役 manifest 身份或 schema 无效")
    published = {(row["source"], row["definition"]): row for row in historical["rules"]}
    retired: set[tuple[str, str]] = set()
    validated_tests: set[str] = set()
    for row in data["retirements"]:
        if (
            not isinstance(row, dict)
            or set(row) != {*_FIELDS, "reason", "replacements", "validation"}
            or any(not isinstance(row[field], str) or not row[field].strip() for field in _FIELDS)
            or not isinstance(row["reason"], str)
            or not row["reason"].strip()
        ):
            raise ValueError("历史规则退役条目字段、身份或理由无效")
        identity = (row["source"], row["definition"])
        if identity in retired:
            raise ValueError(f"历史规则退役身份重复：{identity}")
        original = published.get(identity)
        if original is None or any(row[field] != original[field] for field in _FIELDS):
            raise ValueError(f"历史规则退役不是原历史消费者合同：{identity}")
        if identity in present:
            raise ValueError(f"历史规则退役后仍存在：{identity}")
        for definition in _string_list(row["replacements"], "replacements"):
            replacement = current.get((row["source"], definition))
            if replacement is None:
                raise ValueError(f"历史规则退役替代身份缺失：{identity} -> {definition}")
            if (
                any(
                    getattr(replacement, field) != row[field]
                    for field in _FIELDS
                    if field != "definition"
                )
                or not replacement.owner.strip()
                or replacement.vanilla_tail != _TAIL
                or (replacement.legacy is not None and replacement.legacy.vanilla_tail != _TAIL)
            ):
                raise ValueError(
                    f"历史规则退役替代消费者或原版资格成本尾部漂移：{identity} -> {definition}"
                )
        for proof in _string_list(row["validation"], "validation"):
            if proof not in validated_tests:
                _validate_test_identity(proof)
                validated_tests.add(proof)
        retired.add(identity)
    return retired


def _validate_bundle(
    bundle: ConsumerIRBundle,
    *,
    path: Path = DEFAULT_SOURCE,
    retirements_path: Path = RETIREMENTS_SOURCE,
) -> frozenset[tuple[str, str]]:
    """Reject lost historical identities even when today's total count is unchanged."""

    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != _MANIFEST_SHA256:
        raise ValueError("历史迁移 manifest 原始字节漂移：v3.0.1")
    historical = json.loads(raw)
    if (
        historical["schema"] != 1
        or historical["tag"] != "v3.0.1"
        or historical["commit"] != _COMMIT
        or len(historical["rules"]) != 1401
        or len(historical["cards"]) != 7
    ):
        raise ValueError("历史迁移 manifest 身份无效：v3.0.1")
    current = {
        (writer.source, writer.definition): writer
        for writer in bundle.writers
        if writer.kind == "rule_action"
    }
    if len(current) != sum(writer.kind == "rule_action" for writer in bundle.writers):
        raise ValueError("历史迁移当前规则身份重复")
    retired = _retired_identities(
        historical,
        current,
        {(writer.source, writer.definition) for writer in bundle.writers},
        path=retirements_path,
    )
    for row in historical["rules"]:
        identity = (row["source"], row["definition"])
        if identity in retired:
            continue
        writer = current.get(identity)
        if writer is None:
            raise ValueError(f"历史迁移身份缺失：{identity}")
        if any(getattr(writer, field) != row[field] for field in _FIELDS):
            raise ValueError(f"历史迁移消费者合同漂移：{identity}")
    cards = {writer.definition: writer for writer in bundle.writers if writer.kind == "action_card"}
    for row in historical["cards"]:
        writer = cards.get(row["definition"])
        if writer is None:
            raise ValueError(f"历史显式卡身份缺失：{row['definition']}")
        if writer.field != row["field"] or writer.operation != row["operation"]:
            raise ValueError(f"历史显式卡消费者合同漂移：{row['definition']}")
    return frozenset(retired)


def validate_bundle(
    bundle: ConsumerIRBundle,
    *,
    path: Path = DEFAULT_SOURCE,
    retirements_path: Path = RETIREMENTS_SOURCE,
) -> None:
    """Validate all surviving published identities and explicitly retired rules."""
    _validate_bundle(bundle, path=path, retirements_path=retirements_path)


def validated_retirements(
    bundle: ConsumerIRBundle,
    *,
    path: Path = DEFAULT_SOURCE,
    retirements_path: Path = RETIREMENTS_SOURCE,
) -> frozenset[tuple[str, str]]:
    """Return immutable retirement IDs only after the complete baseline gate passes."""
    return _validate_bundle(bundle, path=path, retirements_path=retirements_path)


__all__ = ["DEFAULT_SOURCE", "RETIREMENTS_SOURCE", "validate_bundle", "validated_retirements"]
