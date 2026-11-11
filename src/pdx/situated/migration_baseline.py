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
from typing import TYPE_CHECKING, Any, cast

from pdx import version_contracts

if TYPE_CHECKING:
    from .decision_ir import ConsumerIRBundle, WriterDecisionIR

DEFAULT_SOURCE = Path(__file__).resolve().parents[3] / "research/situated/v3.0.1-migration.json"
RETIREMENTS_SOURCE = DEFAULT_SOURCE.with_name("a2-retirements.json")
_MANIFEST_SHA256 = "fcce11e045e9933c13644a361da3a448330208c0b712ac3df615eed307aa55e6"
_RETIREMENTS_SHA256 = "ff40ad701d19c16d08b5c246a4b9f34c3b3a21bf2199e0d4ab2e95f972d7c77b"
_COMMIT = "74492fc05321c0767cb07202a91797a7663e7ee0"
_FIELDS = ("source", "definition", "field", "actor", "target", "operation")
_TAIL = "retain_original_qualification_cost_random_execution"
_DEFAULT_NATIVE_SOURCE = "research/vanilla-ai/1.14.5/00_default_strategy.txt"
_DEFAULT_NATIVE_SHA256 = "a817c27fdd1aee4929680338abc07ac8fefd168b24a7617eacf459d923851be2"
_VERSION_115_SOURCE = DEFAULT_SOURCE.parent / "1.15.0/migration-retentions.json"
_VERSION_1151_SHA256 = "c6cc8f3ec838e3fff2f4f04a0958f4f32d2a665859f08445655a6945602fd0af"
_VERSION_115_SHA256 = "23eafb2070c1ab4aa3508e5258516a21ec6c54040b68490f28f58785b9c3ed29"


def _versioned_contract() -> dict[str, Any] | None:
    if version_contracts.active_version() == "1.14.5":
        return None
    raw = (
        version_contracts.research_path("situated", "migration-retentions.json")
        if version_contracts.active_version() == "1.15.1"
        else _VERSION_115_SOURCE
    ).read_bytes()
    if hashlib.sha256(raw).hexdigest() != (
        _VERSION_1151_SHA256
        if version_contracts.active_version() == "1.15.1"
        else _VERSION_115_SHA256
    ):
        raise ValueError("1.15 历史迁移延续合同字节漂移")
    data = json.loads(raw, object_pairs_hook=_unique_json_object)
    if (
        data["schema"] != 1
        or data["version"] != version_contracts.active_version()
        or data["evidence_kind"] != "native_static"
        or data["runtime"] != "unknown"
        or data["historical_retirements_sha256"] != _RETIREMENTS_SHA256
    ):
        raise ValueError("1.15 历史迁移延续合同身份漂移")
    return cast("dict[str, Any]", data)


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


def _validate_native_retention(row: dict[str, Any], writers: tuple[WriterDecisionIR, ...]) -> None:
    """Restore an exact frozen native field without claiming an implementation.

    A removal is never a replacement decision. The historical identity stays
    pinned, and no differently named writer may continue changing that physical
    field. Current generated-byte preservation is checked independently by the
    native protection audit and production witnesses.
    """
    from pdx.model import Block  # noqa: PLC0415
    from pdx.parser import parse_bytes  # noqa: PLC0415

    from .native_treatments import _digest  # noqa: PLC0415

    evidence = row["native_retention"]
    adapter_restoration = row["source"] == "common/ai_strategies/00_default_strategy.txt" and row[
        "field"
    ] in {
        "ai_strategy_default.combat_unit_group_weights.combat_unit_group_infantry",
        "ai_strategy_default.combat_unit_group_weights.combat_unit_group_cavalry",
        "ai_strategy_default.strategic_region_stance_type_scores.stance_colonize_region",
    }
    native_field = (
        row["field"].removeprefix("ai_strategy_default.") if adapter_restoration else row["field"]
    )
    if (
        not isinstance(evidence, dict)
        or set(evidence)
        != {"source", "source_sha256", "definition", "field", "ast_sha256", "business_complete"}
        or evidence["business_complete"] is not False
        or row["replacements"] != []
        or (row["source"] != "mod/decisions/information.toml" and not adapter_restoration)
        or evidence["source"] != _DEFAULT_NATIVE_SOURCE
        or evidence["source_sha256"] != _DEFAULT_NATIVE_SHA256
        or evidence["definition"] != "ai_strategy_default"
        or evidence["field"] != native_field
    ):
        raise ValueError("历史规则退役原版恢复身份、证据或业务边界无效")
    native = DEFAULT_SOURCE.parents[2] / _DEFAULT_NATIVE_SOURCE
    raw = native.read_bytes()
    if hashlib.sha256(raw).hexdigest() != _DEFAULT_NATIVE_SHA256:
        raise ValueError("历史规则退役原版恢复来源字节漂移")
    parsed = parse_bytes(raw, path=_DEFAULT_NATIVE_SOURCE)
    definition = parsed.root.all(evidence["definition"])
    if parsed.errors or len(definition) != 1 or not isinstance(definition[0].value, Block):
        raise ValueError("历史规则退役原版恢复定义不唯一或无法解析")
    block = definition[0].value
    for part in native_field.split("."):
        matches = block.all(part)
        if (
            len(matches) != 1
            or matches[0].op != "="
            or matches[0].prefix is not None
            or not isinstance(matches[0].value, Block)
        ):
            raise ValueError("历史规则退役原版恢复字段缺失或不唯一")
        block = matches[0].value
    if _digest(block) != evidence["ast_sha256"]:
        raise ValueError("历史规则退役原版恢复AST漂移")
    current = _versioned_contract()
    if current is not None:
        # Historical restoration remains independently pinned above. A new
        # version must additionally retain that physical field in its actual
        # default AST; selecting a version cannot imply continued equivalence.
        current_path = DEFAULT_SOURCE.parents[2] / current["source"]
        current_raw = current_path.read_bytes()
        if hashlib.sha256(current_raw).hexdigest() != current["source_sha256"]:
            raise ValueError("1.15 原版恢复来源字节漂移")
        parsed_current = parse_bytes(current_raw, path=current["source"])
        definitions = parsed_current.root.all(current["definition"])
        if parsed_current.errors or len(definitions) != 1:
            raise ValueError("1.15 原版恢复定义不唯一或无法解析")
        node = definitions[0]
        for part in native_field.split("."):
            if not isinstance(node.value, Block):
                raise ValueError("1.15 原版恢复字段不是普通块")
            children = node.value.all(part)
            if len(children) != 1 or children[0].op != "=" or children[0].prefix is not None:
                raise ValueError("1.15 原版恢复字段缺失或不唯一")
            node = children[0]
        if (
            not isinstance(node.value, Block)
            or _digest(node.value) != current["retentions"].get(native_field)
            or current["retentions"][native_field] != evidence["ast_sha256"]
        ):
            raise ValueError("1.15 原版恢复AST与历史保留字段不一致")
    if any(
        writer.field == prefix or writer.field.startswith(prefix + ".")
        for writer in writers
        for prefix in (row["field"], f"ai_strategy_default.{row['field']}")
    ):
        raise ValueError("历史规则退役原版恢复字段仍有活跃作者")


def _school_network_replacements(
    versioned: dict[str, Any], writers: tuple[WriterDecisionIR, ...]
) -> frozenset[tuple[str, str, str]]:
    """Prove only the reviewed 1.15.1 school successor, without legacy writers.

    The network proof precedes complete production composition. The complete
    package boundary must still verify its actual composed writer and witnesses.
    Historical multipliers are intentionally replaced by bounded additive policy.
    """
    from pdx import config  # noqa: PLC0415

    from . import network_profile, production_profile  # noqa: PLC0415

    if version_contracts.active_version() != "1.15.1":
        raise ValueError("学校网络替代只允许精确1.15.1合同")
    migration = versioned.get("school_policy_migration")
    expected_contract = {
        "source": "mod/decisions/information.toml",
        "field": "institution_scores.institution_schools",
        "actor": "root",
        "target": "none",
        "operation": "multiply",
    }
    retired = {
        "coordinated_layered_information_education_foundation",
        "coordinated_layered_information_education_stable",
        "decisive_school_investment",
        "education_catchup_capacity",
        "route_education_schools",
        "social_school_priority",
    }
    replacement_bridges = {
        "remaining_school_catchup_need": ["school-need"],
        "remaining_school_fiscal": ["school-capacity-fiscal"],
        "remaining_school_administrative": ["school-capacity-administrative"],
        "remaining_school_capacity": ["school-capacity-administrative", "school-capacity-fiscal"],
        "school_default_pressure": ["school-default"],
        "school_administrative_pressure": ["school-administration"],
    }
    successor = {
        "consumer": "a0-pol-schools",
        "action": "school-investment",
        "source": "game/common/ai_strategies/00_default_strategy.txt",
        "definition": "ai_strategy_default",
        "field": ["institution_scores", "institution_schools"],
        "actor": "root",
        "actor_scope": "country",
        "target": "institution_schools",
        "operation": "add",
    }
    if (
        not isinstance(migration, dict)
        or migration.get("historical_contract") != expected_contract
        or migration.get("retired_definitions") != sorted(retired)
        or migration.get("replacement_bridge_ids") != replacement_bridges
        or migration.get("successor") != successor
        or migration.get("semantic_change")
        != "intentional_multiply_to_bounded_add; no_arithmetic_equivalence_or_runtime_claim"
    ):
        raise ValueError("学校网络替代身份或有意语义变更合同漂移")
    if any(
        writer.source == expected_contract["source"]
        and (writer.definition in replacement_bridges or writer.field == expected_contract["field"])
        for writer in writers
    ):
        raise ValueError("学校网络替代不能保留旧学校writer或双重计分")
    source = network_profile.source_path("1.15.1")
    if source.relative_to(config.REPO).as_posix() != migration.get(
        "policy_source"
    ) or hashlib.sha256(source.read_bytes()).hexdigest() != migration.get("policy_sha256"):
        raise ValueError("学校网络替代政策来源漂移")
    profile = production_profile.load_profile(production_profile.baseline_root("1.15.1"))
    rows = [item for item in profile.declarations if item.id == successor["consumer"]]
    if len(rows) != 1:
        raise ValueError("学校网络替代缺少唯一真实消费者")
    row = rows[0]
    if (row.source, row.definition, row.field, row.actor, row.target) != (
        successor["source"],
        successor["definition"],
        tuple(successor["field"]),
        successor["actor"],
        successor["target"],
    ):
        raise ValueError("学校网络替代物理消费者漂移")
    audit = network_profile.audit(profile)
    programs = [
        item
        for item in cast("list[dict[str, Any]]", audit["programs"])
        if item["consumer"] == row.id
    ]
    if len(programs) != 1 or programs[0] != migration.get("program"):
        raise ValueError("学校网络替代实际桥或读取合同漂移")
    if not set().union(*map(set, replacement_bridges.values())) <= {
        item["id"] for item in programs[0]["bridges"]
    }:
        raise ValueError("学校网络替代缺少已审精确桥")
    files = network_profile.build(profile)
    text = files[row.source.removeprefix("game/")]
    original = (
        (production_profile.baseline_root("1.15.1") / row.source).read_bytes().decode("utf-8-sig")
    )
    if production_profile.strip_policy(text, row) != original or hashlib.sha256(
        text.encode()
    ).hexdigest() != migration.get("native_output_sha256"):
        raise ValueError("学校网络替代原版资格成本或完整尾部保护漂移")
    return frozenset(
        (expected_contract["source"], definition, replacement)
        for definition in retired
        for replacement in replacement_bridges
    )


def _retired_identities(
    historical: dict[str, Any],
    current: dict[tuple[str, str], WriterDecisionIR],
    present: set[tuple[str, str]],
    *,
    writers: tuple[WriterDecisionIR, ...],
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
    network_replacements: frozenset[tuple[str, str, str]] | None = None
    for row in data["retirements"]:
        if (
            not isinstance(row, dict)
            or set(row)
            not in (
                {*_FIELDS, "reason", "replacements", "validation"},
                {*_FIELDS, "reason", "replacements", "validation", "native_retention"},
            )
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
        if "native_retention" in row:
            _validate_native_retention(row, writers)
            replacements = []
        else:
            replacements = _string_list(row["replacements"], "replacements")
        versioned = _versioned_contract()
        for definition in replacements:
            current_definition = definition
            if versioned is not None:
                redirects = [
                    item
                    for item in versioned["replacement_redirects"]
                    if item["source"] == row["source"]
                    and item["definition"] == row["definition"]
                    and item["historical_replacement"] == definition
                ]
                if len(redirects) > 1:
                    raise ValueError("1.15 历史替代身份映射重复")
                if redirects:
                    redirect = redirects[0]
                    if any(redirect[key] != row[key] for key in _FIELDS if key != "definition"):
                        raise ValueError("1.15 历史替代物理消费者合同漂移")
                    current_definition = redirect["current_replacement"]
            replacement = current.get((row["source"], current_definition))
            if replacement is None:
                if (
                    version_contracts.active_version() == "1.15.1"
                    and versioned is not None
                    and row["source"] == "mod/decisions/information.toml"
                    and row["field"] == "institution_scores.institution_schools"
                ):
                    if network_replacements is None:
                        network_replacements = _school_network_replacements(versioned, writers)
                    if (*identity, definition) in network_replacements:
                        continue
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
        writers=bundle.writers,
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
