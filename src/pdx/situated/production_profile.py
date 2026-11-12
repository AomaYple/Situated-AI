"""Strict 1.15 production profile for the three A0 consumers.

The profile is an identity and contract boundary.  It deliberately does not
contain policy weights or a second action IR: policy remains in the existing
``ConsumerIRBundle`` supplied by the producer.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from pdx import decision_rules, version_contracts
from pdx.model import Assignment, Block
from pdx.parser import parse_bytes

from . import core_contracts, domain_registry, programs, semantic_core
from .core_contracts import (
    CapabilityProfile,
    CapabilitySpec,
    ConsumerSpec,
    ContractAttachment,
    CoreContracts,
    EvaluationSchedule,
    EvidenceRef,
    FactSpec,
    StrictContract,
    WriteOwnership,
)
from .decision_ir import (
    ConsumerIRBundle,
    ContextBinding,
    EvaluationContext,
    LegacyDecisionIR,
    WriterDecisionIR,
    lower_legacy,
)
from .domain_registry import DomainManifest, ValidatedModel
from .schema import UnknownPolicy  # noqa: TC001

ROOT = Path(__file__).resolve().parents[3]
DECLARATION = ROOT / "mod" / "decisions" / "architecture_115.toml"
EXPECTED_VERSION = "1.15.0"


def expected_version() -> str:
    version = version_contracts.active_version()
    return version if version_contracts.is_115(version) else EXPECTED_VERSION


def declaration_path(version: str | None = None) -> Path:
    selected = expected_version() if version is None else version_contracts.active_version(version)
    if selected not in {"1.15.0", "1.15.1"}:
        raise ValueError("production profile 仅支持 1.15.0 与 1.15.1")
    return (
        DECLARATION
        if selected == EXPECTED_VERSION
        else ROOT / "mod/decisions/architecture_1151.toml"
    )


def baseline_root(version: str | None = None) -> Path:
    selected = expected_version() if version is None else version_contracts.active_version(version)
    if selected not in {"1.15.0", "1.15.1"}:
        raise ValueError("production baseline 仅支持 1.15.0 与 1.15.1")
    return ROOT / "research/vanilla-ai" / selected / "native"


_SCHEMA = 1
_HEX = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class ConsumerDeclaration(StrictContract):
    id: str
    domain: str
    source: str
    definition: str
    field: tuple[str, ...]
    actor: str
    target: str
    actor_line: int
    target_line: int
    operation: Literal["add"]
    neutral: float
    bounds: tuple[float, float]
    vanilla_tail: tuple[str, ...]
    comparator: str
    candidate_set: str
    eligibility: str
    tie_break: str
    random: str
    all_zero: str
    unknown_policy: UnknownPolicy
    baseline_line: int

    def _check(self) -> None:
        expected = {
            "a0-econ-road": (
                "economy",
                "game/common/decrees/00_decree.txt",
                "decree_road_maintenance",
                ("ai_weight",),
                "country",
                "root",
            ),
            "a0-pol-schools": (
                "politics",
                "game/common/ai_strategies/00_default_strategy.txt",
                "ai_strategy_default",
                ("institution_scores", "institution_schools"),
                "root",
                "institution_schools",
            ),
            "a0-dip-relations": (
                "diplomacy",
                "game/common/diplomatic_actions/00_relations_actions.txt",
                "increase_relations",
                ("ai", "propose_score"),
                "root",
                "target_country",
            ),
        }
        actual = self.domain, self.source, self.definition, self.field, self.actor, self.target
        if expected.get(self.id) != actual or self.neutral != 0.0:
            raise ValueError("ConsumerDeclaration: 不属于冻结三写点或中性操作漂移")
        # ``architecture_115.toml`` is the mechanical neutral profile.  Its
        # bounds remain zero even though the independent policy slice has its
        # own reviewed envelopes.  Keeping the two contracts separate lets
        # ``build_neutral`` continue to prove byte-for-byte reversibility while
        # ``build_policy_115`` opts in to non-zero contributions explicitly.
        if self.bounds != (0.0, 0.0):
            raise ValueError("ConsumerDeclaration.bounds: 中性 profile 必须保持零边界")
        for line in (self.actor_line, self.target_line, self.baseline_line):
            if line < 1:
                raise ValueError("ConsumerDeclaration: 缺少正数来源行号")
        required = {"qualification", "execution", "zero_protection"}
        required |= (
            {"default_component", "additive_other_strategies"}
            if self.id == "a0-pol-schools"
            else {"cost", "random", "ordered_tail"}
        )
        if not required <= set(self.vanilla_tail):
            raise ValueError("ConsumerDeclaration.vanilla_tail: 保护尾部不完整")

    @property
    def write_point(self) -> tuple[str, str, tuple[str, ...]]:
        return self.source, self.definition, self.field


@dataclass(frozen=True, slots=True)
class ProductionProfile:
    schema: int
    game_version: str
    build_id: str
    source_hashes: tuple[tuple[str, str], ...]
    declarations: tuple[ConsumerDeclaration, ...]
    contracts: CoreContracts
    registry: ValidatedModel
    bindings: tuple[tuple[str, str, str], ...]

    @property
    def consumer_ids(self) -> tuple[str, ...]:
        return tuple(item.id for item in self.declarations)


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _fail(path: str, message: str) -> ValueError:
    return ValueError(f"production_profile.{path}: {message}")


def _strict_table(data: dict[str, Any], allowed: set[str], path: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise _fail(path, f"未知字段 {sorted(unknown)}")


def _text(value: Any, path: str) -> str:
    if type(value) is not str or not value.strip():
        raise _fail(path, "需要非空字符串")
    return value


def _sha(value: Any, path: str) -> str:
    if type(value) is not str or not _HEX.fullmatch(value):
        raise _fail(path, "需要小写 SHA-256")
    return value


def _load_declaration(path: Path) -> tuple[dict[str, Any], tuple[ConsumerDeclaration, ...]]:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise _fail(str(path), f"无法读取严格 TOML: {exc}") from exc
    if type(data) is not dict:
        raise _fail("root", "必须是表")
    _strict_table(
        data, {"schema", "profile", "game_version", "identity", "input", "consumer"}, "root"
    )
    if (
        type(data.get("schema")) is not int
        or data.get("schema") != _SCHEMA
        or data.get("profile") != "situated-ai/production/1.15"
    ):
        raise _fail("root", "schema/profile 不匹配")
    if data.get("game_version") not in {"1.15.0", "1.15.1"}:
        raise _fail("game_version", "必须锁定 1.15.0")
    identities = data.get("identity")
    inputs = data.get("input")
    rows = data.get("consumer")
    if (
        not isinstance(identities, list)
        or not isinstance(inputs, list)
        or not isinstance(rows, list)
    ):
        raise _fail("root", "identity/input/consumer 必须为非空数组")
    seen_paths: set[str] = set()
    for index, row in enumerate(identities):
        if type(row) is not dict:
            raise _fail(f"identity[{index}]", "必须是表")
        _strict_table(row, {"path", "sha256", "raw_version", "value"}, f"identity[{index}]")
        rel = _text(row.get("path"), f"identity[{index}].path")
        if rel in seen_paths:
            raise _fail("identity", f"重复路径 {rel}")
        seen_paths.add(rel)
        _sha(row.get("sha256"), f"identity[{index}].sha256")
        if rel.endswith("launcher-settings.json"):
            if row.get("raw_version") != data["game_version"]:
                raise _fail(f"identity[{index}].raw_version", "必须为 1.15.0")
        elif "value" not in row:
            raise _fail(f"identity[{index}]", "非 launcher 身份必须声明 value")
    input_rows: list[dict[str, Any]] = []
    for index, row in enumerate(inputs):
        if type(row) is not dict:
            raise _fail(f"input[{index}]", "必须是表")
        _strict_table(row, {"path", "sha256"}, f"input[{index}]")
        rel = _text(row.get("path"), f"input[{index}].path")
        if rel in seen_paths:
            raise _fail("input", f"路径与身份重复 {rel}")
        seen_paths.add(rel)
        input_rows.append(
            {"path": rel, "sha256": _sha(row.get("sha256"), f"input[{index}].sha256")}
        )
    if {item["path"] for item in identities} != {
        "launcher/launcher-settings.json",
        "caligula_branch.txt",
        "caligula_rev.txt",
        "clausewitz_branch.txt",
        "clausewitz_rev.txt",
        "binaries/checksum.txt",
    }:
        raise _fail("identity", "必须包含全部六个版本身份来源")
    if {item["path"] for item in input_rows} != {
        "game/common/decrees/00_decree.txt",
        "game/common/ai_strategies/00_default_strategy.txt",
        "game/common/ai_strategies/03_political_strategies.txt",
        "game/common/diplomatic_actions/00_relations_actions.txt",
    }:
        raise _fail("input", "必须包含三个写点及非默认学校策略来源")
    declarations: list[ConsumerDeclaration] = []
    for index, row in enumerate(rows):
        if type(row) is not dict:
            raise _fail(f"consumer[{index}]", "必须是表")
        declarations.append(ConsumerDeclaration.from_mapping(row))
    if tuple(item.id for item in declarations) != (
        "a0-econ-road",
        "a0-pol-schools",
        "a0-dip-relations",
    ):
        raise _fail("consumer", "必须按固定顺序声明三个 A0 写点")
    return {
        "game_version": data["game_version"],
        "identity": identities,
        "input": input_rows,
    }, tuple(declarations)


def _unique_assignment(block: Block, key: str, path: str) -> Assignment:
    matches = [item for item in block.items if isinstance(item, Assignment) and item.key == key]
    if len(matches) != 1:
        raise _fail(path, f"期望一个 {key}，实际 {len(matches)}")
    return matches[0]


def _select(root: Block, keys: tuple[str, ...], source: str) -> Assignment:
    current = root
    for index, key in enumerate(keys):
        item = _unique_assignment(current, key, f"{source}:{'.'.join(keys[: index + 1])}")
        if index == len(keys) - 1:
            return item
        if not isinstance(item.value, Block):
            raise _fail(source, f"{'.'.join(keys[: index + 1])} 不是 block")
        current = item.value
    raise AssertionError


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _fail("identity", f"重复 JSON 字段 {key}")
        result[key] = value
    return result


def _verify_native(
    installation: Path, declaration_data: dict[str, Any], rows: tuple[ConsumerDeclaration, ...]
) -> tuple[tuple[str, str], ...]:
    installation = installation.resolve()
    if not installation.is_dir():
        raise _fail("installation", "安装目录不存在")
    expected_hashes = [*declaration_data["identity"], *declaration_data["input"]]
    actual: list[tuple[str, str]] = []
    for item in expected_hashes:
        rel = item["path"]
        if not rel or "\\" in rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
            raise _fail("input", f"不安全路径 {rel}")
        source = installation / Path(*rel.split("/"))
        if source.is_symlink() or not source.is_file() or source.resolve() != source.absolute():
            raise _fail(rel, "缺少文件或检测到链接")
        raw = source.read_bytes()
        digest = _digest(raw)
        if digest != item["sha256"]:
            raise _fail(rel, f"原始字节 SHA-256 漂移，期望 {item['sha256']} 实际 {digest}")
        actual.append((rel, digest))
        if rel.endswith("launcher-settings.json"):
            try:
                document = json.loads(
                    raw.decode("utf-8-sig"),
                    object_pairs_hook=_json_object,
                )
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise _fail(rel, f"JSON 身份无效: {exc}") from exc
            if (
                type(document) is not dict
                or document.get("rawVersion") != declaration_data["game_version"]
            ):
                raise _fail(rel, "rawVersion 不是 1.15.0")
        elif rel.endswith("_rev.txt") or rel == "binaries/checksum.txt":
            text = raw.decode("utf-8-sig").strip()
            expected = next(
                item["value"] for item in declaration_data["identity"] if item["path"] == rel
            )
            if text != expected:
                raise _fail(rel, "revision 身份与声明不一致")
        elif rel.endswith("_branch.txt"):
            text = raw.decode("utf-8-sig").strip()
            expected = next(
                item["value"] for item in declaration_data["identity"] if item["path"] == rel
            )
            if text != expected or declaration_data["game_version"] not in text:
                raise _fail(rel, "branch 身份与声明不一致")
    for row in rows:
        raw = (installation / Path(*row.source.split("/"))).read_bytes()
        parsed = parse_bytes(raw, row.source)
        if parsed.errors:
            raise _fail(row.source, f"PDX 解析失败 {parsed.errors}")
        assignment = _select(parsed.root, (row.definition, *row.field), row.source)
        if not isinstance(assignment.value, Block):
            raise _fail(row.id, "消费者必须为数值脚本 block")
        if assignment.line != row.baseline_line:
            raise _fail(row.id, f"写点行号漂移，期望 {row.baseline_line} 实际 {assignment.line}")
        if row.id == "a0-econ-road" and (row.actor_line, row.target_line) != (84, 22):
            raise _fail(row.id, "道路上下文见证行漂移")
        if row.id == "a0-pol-schools" and (row.actor_line, row.target_line) != (1598, 1598):
            raise _fail(row.id, "学校上下文见证行漂移")
        if row.id == "a0-dip-relations" and (row.actor_line, row.target_line) != (92, 98):
            raise _fail(row.id, "外交上下文见证行漂移")
    return tuple(actual)


def _context(row: ConsumerDeclaration) -> EvaluationContext:
    if row.id == "a0-econ-road":
        actor = ContextBinding("country", "country", "actor", row.source, row.actor_line)
        targets = (ContextBinding("root", "state", "target", row.source, row.target_line),)
    elif row.id == "a0-pol-schools":
        actor = ContextBinding("root", "country", "actor", row.source, row.actor_line)
        targets = (
            ContextBinding(
                "institution_schools", "institution", "candidate", row.source, row.target_line
            ),
        )
    else:
        actor = ContextBinding("root", "country", "actor", row.source, row.actor_line)
        targets = (
            ContextBinding("target_country", "country", "target", row.source, row.target_line),
        )
    return EvaluationContext(
        actor_scope=actor,
        targets=targets,
        evidence=(f"{actor.source}:{actor.line}", f"{targets[0].source}:{targets[0].line}"),
    )


def _contracts(rows: tuple[ConsumerDeclaration, ...]) -> CoreContracts:
    consumers: list[ConsumerSpec] = []
    schedules: list[EvaluationSchedule] = []
    facts: list[FactSpec] = []
    for row in rows:
        context = _context(row)
        schedule_id = f"schedule.{row.id}"
        consumers.append(
            ConsumerSpec(
                id=row.id,
                source=row.source,
                definition=row.definition,
                field=row.field,
                context=context,
                operation="add",
                unit="consumer_score",
                neutral=0.0,
                bounds=row.bounds,
                vanilla_tail=row.vanilla_tail,
                comparator=row.comparator,
                candidate_set=row.candidate_set,
                eligibility=row.eligibility,
                tie_break=row.tie_break,
                random=row.random,
                all_zero=row.all_zero,
                unknown_policy=row.unknown_policy,
                baseline=EvidenceRef(row.source, row.baseline_line),
                schedule_id=schedule_id,
            )
        )
        schedules.append(
            EvaluationSchedule(
                id=schedule_id,
                consumer_id=row.id,
                sources=(EvidenceRef(row.source, row.baseline_line),),
            )
        )
    # Only native same-consumer evidence enters the usable fact catalog.
    # Bilateral relation values remain pending reproof in propose_score.
    for ident, consumer, source, line, kind, unit, entity, binding in (
        (
            "relative-infrastructure",
            "a0-econ-road",
            rows[0].source,
            28,
            "ratio",
            "ratio",
            "state",
            "target",
        ),
        (
            "road-decree-present",
            "a0-econ-road",
            rows[0].source,
            30,
            "boolean",
            "boolean",
            "state",
            "target",
        ),
        (
            "school-agenda",
            "a0-pol-schools",
            "game/common/ai_strategies/03_political_strategies.txt",
            135,
            "boolean",
            "boolean",
            "country",
            "actor",
        ),
        (
            "diplomatic-attitude-protective",
            "a0-dip-relations",
            rows[2].source,
            109,
            "boolean",
            "boolean",
            "country",
            "target",
        ),
    ):
        facts.append(
            FactSpec.from_mapping(
                {
                    "id": ident,
                    "reader_id": f"reader.{ident}",
                    "kind": kind,
                    "unit": unit,
                    "entity_kind": entity,
                    "binding": binding,
                    "consumer_ids": [consumer],
                    "sources": [{"source": source, "line": line}],
                }
            )
        )
    return CoreContracts(facts=tuple(facts), consumers=tuple(consumers), schedules=tuple(schedules))


def load_profile(installation: Path, declaration: Path | None = None) -> ProductionProfile:
    declaration = declaration_path() if declaration is None else Path(declaration)
    data, rows = _load_declaration(declaration)
    hashes = _verify_native(Path(installation), data, rows)
    values = {item["path"]: item.get("value", "") for item in data["identity"]}
    build_id = f"caligula:{values.get('caligula_rev.txt', '')};clausewitz:{values.get('clausewitz_rev.txt', '')}"
    capabilities = tuple(
        CapabilitySpec(f"consumer.{row.id}", "known", (EvidenceRef(row.source, row.baseline_line),))
        for row in rows
    )
    capability = CapabilityProfile(data["game_version"], build_id, hashes, (), capabilities)
    contracts = _contracts(rows)
    manifests = tuple(
        DomainManifest(
            id=row.domain,
            provides=(f"consumer.{row.id}",),
            consumes=(),
            dependencies=(),
            requires_capabilities=(f"consumer.{row.id}",),
            facts=tuple(item for item in contracts.facts if row.id in item.consumer_ids),
            action_ids=(),
            relation_ids=(),
            writes=(WriteOwnership(row.source, row.definition, row.field, row.id),),
            object_budget=1,
            witness_ids=(f"consumer.{row.id}",),
        )
        for row in rows
    )
    registry = domain_registry.validate(manifests, capability)
    return ProductionProfile(
        1,
        data["game_version"],
        build_id,
        hashes,
        rows,
        contracts,
        registry,
        tuple((row.id, row.source, row.definition) for row in rows),
    )


def attach_profile(bundle: ConsumerIRBundle, profile: ProductionProfile) -> ContractAttachment:
    """Attach contracts to the existing bundle, requiring all three real writers."""
    policy_ids = {item.id for item in load_policy_115() if item.status == "observed"}
    if any(writer.writer_id in policy_ids for writer in bundle.writers):
        return attach_policy_profile(bundle, profile)
    expected = {row.id: row for row in profile.declarations}
    if bundle.schema != 1:
        raise ValueError("production_profile: 未支持的 bundle schema")
    if tuple(writer.consumer_id for writer in bundle.writers) != tuple(expected):
        raise ValueError("production_profile: bundle 必须按 profile 顺序包含三个消费者 writer")
    for writer in bundle.writers:
        row = expected.get(writer.consumer_id)
        if (
            row is None
            or (writer.source, writer.definition, tuple(writer.field.split("."))) != row.write_point
        ):
            raise ValueError(f"production_profile.{writer.writer_id}: 写点与 profile 不匹配")
        if (
            writer.actor != row.actor
            or writer.target != row.target
            or writer.operation != row.operation
            or writer.vanilla_tail != "retain_original_qualification_cost_random_execution"
        ):
            raise ValueError(
                f"production_profile.{writer.writer_id}: actor/target/operation/tail 不匹配"
            )
        if not any(
            value is not None
            for value in (writer.action, writer.legacy, writer.program, writer.supply_program)
        ):
            raise ValueError(f"production_profile.{writer.writer_id}: 仅有元数据，未接入现有 IR")
    return core_contracts.attach_bundle(bundle, profile.contracts)


__all__ = [
    "ConsumerDeclaration",
    "ProductionProfile",
    "attach_policy_profile",
    "attach_profile",
    "load_profile",
    "policy_contracts",
]


# The frozen native corpus is deliberately kept outside ``research/`` (which
# contains the historical 1.14.5 excerpts).  Keeping the declaration's path
# hierarchy under a versioned directory also prevents a future baseline from
# overwriting an older receipt when both are present in one checkout.
# Keep the native corpus in its own directory.  The version directory already
# contains historical classification receipts, which are not source inputs.
BASELINE_ROOT = ROOT / "research" / "vanilla-ai" / EXPECTED_VERSION / "native"
BASELINE_MANIFEST = BASELINE_ROOT / "baseline-manifest.json"
POLICY_DECLARATION = ROOT / "mod" / "decisions" / "policy_115.toml"


@dataclass(frozen=True, slots=True)
class PolicyVariant:
    """A small, explicitly evidenced non-neutral consumer variant.

    The variant is policy input, while its source/field/domain identity is
    checked against the frozen profile before it reaches the shared program
    compiler.  Guards are intentionally closed over a tiny allow-list below;
    this file is not a free-form PDX escape hatch.
    """

    id: str
    consumer_id: str
    value: float
    priority: int
    contribution_group: str
    fact: str
    operator: Literal["<", ">=", "="]
    predicate_value: bool | float
    guard: str
    evidence_source: str
    evidence_line: int
    status: Literal["observed", "pending_reproof"]


_POLICY_ALLOWED = {
    "road-deficit-moderate": ("a0-econ-road", "relative-infrastructure", "<", 0.5),
    "road-deficit-severe": ("a0-econ-road", "relative-infrastructure", "<", 0.25),
    "road-recovery": ("a0-econ-road", "road-decree-present", "=", True),
    "schools-low-literacy": ("a0-pol-schools", "literacy-rate", "<", 0.5),
    "schools-strategy": ("a0-pol-schools", "school-agenda", "=", True),
    "relations-protective": ("a0-dip-relations", "diplomatic-attitude-protective", "=", True),
    "relations-hostile": ("a0-dip-relations", "diplomatic-attitude-hostile", "=", True),
}
_POLICY_GUARDS = {
    "road-deficit-moderate": "relative_infrastructure < 0.5",
    "road-deficit-severe": "relative_infrastructure < 0.25",
    "road-recovery": "has_decree = decree_road_maintenance relative_infrastructure >= 0.75",
    "schools-low-literacy": "literacy_rate < 0.5",
    "schools-strategy": "has_journal_entry = je_tp_pool_educational_reform",
    "relations-protective": "has_attitude = { who = scope:target_country attitude = protective }",
    "relations-hostile": "has_attitude = { who = scope:target_country attitude = belligerent }",
}
_POLICY_STATUS = {
    "road-deficit-moderate": "observed",
    "road-deficit-severe": "observed",
    "road-recovery": "observed",
    "schools-low-literacy": "pending_reproof",
    "schools-strategy": "observed",
    "relations-protective": "observed",
    "relations-hostile": "pending_reproof",
}
_POLICY_EXPECTED: dict[str, tuple[float, int, str, str, int]] = {
    "road-deficit-moderate": (2.0, 20, "road-deficit", "game/common/decrees/00_decree.txt", 42),
    "road-deficit-severe": (4.0, 30, "road-deficit", "game/common/decrees/00_decree.txt", 56),
    "road-recovery": (-2.0, 10, "road-recovery", "game/common/decrees/00_decree.txt", 58),
    "schools-low-literacy": (
        2.0,
        10,
        "schools-need",
        "game/common/ai_strategies/00_default_strategy.txt",
        1598,
    ),
    "schools-strategy": (
        2.0,
        20,
        "schools-agenda",
        "game/common/ai_strategies/03_political_strategies.txt",
        135,
    ),
    "relations-protective": (
        2.0,
        20,
        "relations-attitude",
        "game/common/diplomatic_actions/00_relations_actions.txt",
        109,
    ),
    "relations-hostile": (
        -2.0,
        10,
        "relations-attitude",
        "game/common/diplomatic_actions/00_relations_actions.txt",
        299,
    ),
}


def load_policy_115(path: Path = POLICY_DECLARATION) -> tuple[PolicyVariant, ...]:
    """Read the reviewed non-zero vertical slice with a strict TOML schema."""
    try:
        with Path(path).open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"1.15 policy 无法读取：{path}") from exc
    if set(data) != {"schema", "profile", "game_version", "variant"}:
        raise ValueError("1.15 policy schema 不匹配")
    if (
        data["schema"] != 1
        or data["profile"] != "situated-ai/production/1.15"
        or data["game_version"] != EXPECTED_VERSION
    ):
        raise ValueError("1.15 policy profile/version 不匹配")
    rows = data["variant"]
    if not isinstance(rows, list) or tuple(
        item.get("id") for item in rows if isinstance(item, dict)
    ) != tuple(_POLICY_ALLOWED):
        raise ValueError("1.15 policy 必须按固定顺序声明七个纵切变体")
    result: list[PolicyVariant] = []
    allowed_fields = {
        "id",
        "consumer_id",
        "value",
        "priority",
        "contribution_group",
        "fact",
        "operator",
        "predicate_value",
        "guard",
        "evidence_source",
        "evidence_line",
        "status",
    }
    for index, item in enumerate(rows):
        if not isinstance(item, dict) or set(item) != allowed_fields:
            raise ValueError(f"1.15 policy variant[{index}] 字段不完整")
        ident = item["id"]
        if ident not in _POLICY_ALLOWED:
            raise ValueError(f"1.15 policy 未知变体：{ident}")
        expected_consumer, expected_fact, expected_operator, expected_value = _POLICY_ALLOWED[ident]
        expected_value_delta, expected_priority, expected_group, expected_source, expected_line = (
            _POLICY_EXPECTED[ident]
        )
        if (item["consumer_id"], item["fact"], item["operator"], item["predicate_value"]) != (
            expected_consumer,
            expected_fact,
            expected_operator,
            expected_value,
        ):
            raise ValueError(f"1.15 policy {ident}: fact/consumer/predicate 不匹配")
        if type(item["value"]) not in (int, float) or not (-100.0 <= float(item["value"]) <= 100.0):
            raise ValueError(f"1.15 policy {ident}: value 必须在 [-100,100]")
        if (
            float(item["value"]) != expected_value_delta
            or item["priority"] != expected_priority
            or item["contribution_group"] != expected_group
            or item["evidence_source"] != expected_source
            or item["evidence_line"] != expected_line
        ):
            raise ValueError(f"1.15 policy {ident}: delta/group/evidence 未通过固定审查")
        if (
            type(item["priority"]) is not int
            or type(item["evidence_line"]) is not int
            or item["evidence_line"] < 1
        ):
            raise ValueError(f"1.15 policy {ident}: priority/evidence_line 无效")
        if (
            item["guard"] != _POLICY_GUARDS[ident]
            or not item["evidence_source"]
            or item["status"] != _POLICY_STATUS[ident]
        ):
            raise ValueError(f"1.15 policy {ident}: guard/evidence 无效")
        result.append(PolicyVariant(**item))
    return tuple(result)


_POLICY_BOUNDS: dict[str, tuple[float, float]] = {
    "a0-econ-road": (-4.0, 4.0),
    "a0-pol-schools": (0.0, 2.0),
    "a0-dip-relations": (-3.0, 3.0),
}


def policy_contracts(profile: ProductionProfile) -> CoreContracts:
    """Return the policy slice's independently reviewed score envelopes.

    The neutral production profile intentionally keeps zero bounds.  Policy
    writers use this separate contract so attaching a non-zero bundle cannot
    silently widen the neutral declaration.
    """
    consumers = tuple(
        replace(item, bounds=_POLICY_BOUNDS[item.id]) for item in profile.contracts.consumers
    )
    return replace(profile.contracts, consumers=consumers)


def _policy_reader(fact: str) -> decision_rules.Reader:
    """Return the closed reader set used by the reviewed 1.15 guards."""
    if fact == "relative-infrastructure":
        return decision_rules.Reader(
            fact, "relative_infrastructure", "root", "ratio", "number", minimum=0.0
        )
    if fact == "road-decree-present":
        return decision_rules.Reader(
            fact, "has_decree", "root", "boolean", "boolean", argument="decree_road_maintenance"
        )
    if fact == "literacy-rate":
        return decision_rules.Reader(
            fact, "literacy_rate", "root", "ratio", "number", minimum=0.0, maximum=1.0
        )
    if fact == "school-agenda":
        return decision_rules.Reader(
            fact,
            "has_journal_entry",
            "root",
            "boolean",
            "boolean",
            argument="je_tp_pool_educational_reform",
        )
    if fact == "diplomatic-attitude-protective":
        return decision_rules.Reader(
            fact,
            "has_attitude",
            "root",
            "boolean",
            "boolean",
            parameters=(("who", "scope:target_country"), ("attitude", "protective")),
        )
    if fact == "diplomatic-attitude-hostile":
        return decision_rules.Reader(
            fact,
            "has_attitude",
            "root",
            "boolean",
            "boolean",
            parameters=(("who", "scope:target_country"), ("attitude", "belligerent")),
        )
    raise ValueError(f"1.15 policy 未知 fact：{fact}")


def _policy_predicates(variant: PolicyVariant) -> tuple[tuple[str, str, object], ...]:
    predicates: list[tuple[str, str, object]] = [
        (variant.fact, variant.operator, variant.predicate_value)
    ]
    if variant.id == "road-recovery":
        predicates.append(("relative-infrastructure", ">=", 0.75))
    return tuple(predicates)


def _policy_semantic_rows(
    profile: ProductionProfile | None,
    row: ConsumerDeclaration,
    variant: PolicyVariant,
) -> tuple[semantic_core.ActionSpec, LegacyDecisionIR]:
    """Build the semantic action and legacy lowering from one policy row.

    ``ActionSpec`` is the source of truth for eligibility and contribution
    evidence.  The legacy record only serializes the same predicates and
    value for the existing PDX lowering path.
    """
    predicates = _policy_predicates(variant)
    target_binding = None
    if profile is not None:
        consumer = next(item for item in profile.contracts.consumers if item.id == row.id)
        target_binding = consumer.context.targets[0]
    target_kinds: dict[str, core_contracts.EntityKind] = {
        "country": "country",
        "state": "state",
        "institution": "scalar",
    }
    if target_binding is None:
        target_kind: core_contracts.EntityKind = "scalar"
        target_name = row.target
    else:
        if target_binding.kind not in target_kinds:
            raise ValueError(f"{row.id}: unsupported semantic target kind {target_binding.kind}")
        target_kind = target_kinds[target_binding.kind]
        target_name = target_binding.name
    actor = core_contracts.EntityKey("country", f"policy-{row.id}")
    target = core_contracts.EntityKey(target_kind, target_name)
    compare_operators: dict[str, Literal["eq", "lt", "ge"]] = {
        "=": "eq",
        "<": "lt",
        ">=": "ge",
    }
    expression_items = tuple(
        semantic_core.Compare(fact_id, compare_operators[operator], expected)
        for fact_id, operator, expected in predicates
    )
    eligibility = (
        expression_items[0] if len(expression_items) == 1 else semantic_core.All(expression_items)
    )
    # Boolean gates are valid evidence sources for the score term.  Numeric
    # ratios remain eligibility facts; attaching them to a consumer_score
    # term would falsely claim a unit conversion.
    source_ids: tuple[str, ...] = ()
    if profile is not None:
        fact_map = {item.id: item for item in profile.contracts.facts}
        source_ids = tuple(
            fact_id
            for fact_id, _, _ in predicates
            if fact_map.get(fact_id) is not None and fact_map[fact_id].kind == "boolean"
        )
    term = semantic_core.AssessmentTerm(
        f"{variant.id}.contribution",
        "benefit" if variant.value >= 0 else "cost",
        "consumer_score",
        "target",
        abs(float(variant.value)),
        "known",
        source_ids,
        "current",
    )
    action = semantic_core.ActionSpec(
        variant.id,
        row.id,
        actor,
        target,
        benefits=(term,) if variant.value >= 0 else (),
        costs=(term,) if variant.value < 0 else (),
        eligibility=eligibility,
        eligibility_facts=tuple(fact_id for fact_id, _, _ in predicates),
    )
    legacy = LegacyDecisionIR(
        action_id=variant.id,
        source=row.source,
        definition=variant.id,
        domain=row.domain,
        consumer_id=row.id,
        field=".".join(row.field),
        actor=row.actor,
        target=row.target,
        operation=row.operation,
        value=variant.value,
        predicates=predicates,
        vanilla_tail="retain_original_qualification_cost_random_execution",
        priority=variant.priority,
        why=variant.guard,
        counterexample="unknown fact returns vanilla",
        contexts=(row.id, variant.id),
        auxiliary_facts=(variant.fact,),
        required_known_facts=tuple(predicate[0] for predicate in predicates),
        contribution_group=variant.contribution_group,
    )
    return action, legacy


def _policy_bundle(
    profile: ProductionProfile,
    row: ConsumerDeclaration,
    variants: tuple[PolicyVariant, ...],
    semantic_rows: tuple[tuple[semantic_core.ActionSpec, LegacyDecisionIR], ...] | None = None,
) -> ConsumerIRBundle:
    writers: list[WriterDecisionIR] = []
    context = next(item.context for item in profile.contracts.consumers if item.id == row.id)
    if semantic_rows is None:
        semantic_rows = tuple(_policy_semantic_rows(profile, row, item) for item in variants)
    if len(semantic_rows) != len(variants):
        raise ValueError(f"{row.id}: policy semantic row count drift")
    for variant, (_, legacy) in zip(variants, semantic_rows, strict=True):
        writers.append(
            WriterDecisionIR(
                writer_id=variant.id,
                kind="rule_action",
                source=row.source,
                definition=variant.id,
                consumer_id=row.id,
                field=".".join(row.field),
                actor=row.actor,
                target=row.target,
                operation=row.operation,
                vanilla_tail=legacy.vanilla_tail,
                owner=row.domain,
                legacy=legacy,
                evaluation_context=context,
                predicates=legacy.predicates,
            )
        )
    return ConsumerIRBundle(1, (), tuple(writers))


def attach_policy_profile(
    bundle: ConsumerIRBundle, profile: ProductionProfile
) -> ContractAttachment:
    """Attach observed policy writers to the separate non-zero contract."""
    contracts = policy_contracts(profile)
    consumers = {item.id: item for item in contracts.consumers}
    if bundle.schema != 1 or not bundle.writers:
        raise ValueError("1.15 policy bundle 不能为空")
    claimed: set[str] = set()
    for writer in bundle.writers:
        consumer = consumers.get(writer.consumer_id)
        legacy = writer.legacy
        if (
            consumer is None
            or legacy is None
            or writer.kind != "rule_action"
            or writer.source != consumer.source
            or writer.field != ".".join(consumer.field)
            or writer.consumer_id != legacy.consumer_id
            or writer.definition != legacy.definition
            or writer.writer_id != legacy.action_id
            or writer.operation != consumer.operation
            or writer.evaluation_context != consumer.context
            or writer.vanilla_tail != "retain_original_qualification_cost_random_execution"
        ):
            raise ValueError(f"1.15 policy writer 未通过非零合同：{writer.writer_id}")
        if writer.writer_id in claimed:
            raise ValueError(f"1.15 policy writer 重复：{writer.writer_id}")
        claimed.add(writer.writer_id)
    expected = {item.id for item in load_policy_115() if item.status == "observed"}
    observed_consumers = {
        item.consumer_id for item in load_policy_115() if item.status == "observed"
    }
    connected = {writer.consumer_id for writer in bundle.writers}
    if not connected <= set(consumers) or not claimed <= expected:
        raise ValueError("1.15 policy bundle 包含未知消费者或 pending 变体")
    return ContractAttachment(bundle, contracts, connected == observed_consumers)


def _validate_policy_semantic_contract(
    profile: ProductionProfile,
    row: ConsumerDeclaration,
    variants: tuple[PolicyVariant, ...],
    semantic_rows: tuple[tuple[semantic_core.ActionSpec, LegacyDecisionIR], ...],
) -> None:
    """Validate the exact semantic actions that will be lowered to PDX."""
    if not variants:
        return
    if len(variants) != len(semantic_rows):
        raise ValueError(f"{row.id}: semantic policy row count drift")
    contracts = profile.contracts
    schedule = next(item for item in contracts.schedules if item.consumer_id == row.id)
    facts = tuple(item for item in contracts.facts if row.id in item.consumer_ids)
    fact_map = {item.id: item for item in facts}
    for variant, (action, _legacy) in zip(variants, semantic_rows, strict=True):
        for fact_id in action.eligibility_facts:
            if fact_id not in fact_map:
                raise ValueError(f"{variant.id}: semantic policy fact 未声明: {fact_id}")
        actor = action.actor
        target = action.target
        if target is None:
            raise ValueError(f"{variant.id}: semantic target missing")
        time = core_contracts.TimeIdentity("policy", 1)
        observations: list[core_contracts.Observation] = []
        for fact in facts:
            entity = actor if fact.binding == "actor" else target
            value: bool | float
            if fact.kind == "boolean":
                value = True
            elif fact.kind == "ratio":
                value = 0.2 if variant.id != "road-recovery" else 0.8
            else:
                raise ValueError(f"{row.id}: semantic policy fact kind unsupported: {fact.kind}")
            observations.append(
                core_contracts.Observation(
                    fact.id, entity, fact.unit, "known", time, value, fact.sources
                )
            )
        snapshot = core_contracts.SituationSnapshot(
            actor, target, row.id, time, "country", tuple(observations), schedule.id
        )
        evaluation = semantic_core.recompute(snapshot, facts, (), (action,), schedule)
        assessment = evaluation.actions[0]
        if (
            assessment.candidate_id != variant.id
            or assessment.qualification != "known"
            or assessment.eligible is not True
        ):
            raise ValueError(f"{variant.id}: semantic policy eligibility is not proven")


def compile_policy_115(
    profile: ProductionProfile,
    baseline_root: Path | None = None,
    *,
    declaration: Path | None = None,
    policy: Path | None = None,
    enabled_domains: frozenset[str] | None = None,
) -> tuple[ConsumerIRBundle, tuple[decision_rules.RuleSet, ...]]:
    """Compile observed 1.15 variants through the shared legacy lowering path.

    ``pending_reproof`` variants are deliberately omitted.  The engine then
    evaluates the untouched native consumer for those facts, which is the
    required fail-closed behaviour for literacy and hostile attitudes.
    """
    baseline_root = globals()["baseline_root"]() if baseline_root is None else Path(baseline_root)
    verify_baseline(baseline_root, declaration=declaration)
    frozen = load_profile(baseline_root, declaration)
    if profile != frozen:
        raise ValueError("profile 与锁定 native baseline 不一致")
    variants = load_policy_115(POLICY_DECLARATION if policy is None else Path(policy))
    known_domains = {row.domain for row in profile.declarations}
    selected_domains = known_domains if enabled_domains is None else set(enabled_domains)
    if not selected_domains <= known_domains:
        raise ValueError(
            f"1.15 policy enabled_domains 未登记：{sorted(selected_domains - known_domains)}"
        )
    by_consumer = {
        row.id: tuple(
            item
            for item in variants
            if item.consumer_id == row.id
            and item.status == "observed"
            and row.domain in selected_domains
        )
        for row in profile.declarations
    }
    semantic_by_consumer: dict[
        str, tuple[tuple[semantic_core.ActionSpec, LegacyDecisionIR], ...]
    ] = {}
    policy_writers: list[WriterDecisionIR] = []
    for row in profile.declarations:
        selected = by_consumer[row.id]
        semantic_rows = tuple(_policy_semantic_rows(profile, row, item) for item in selected)
        semantic_by_consumer[row.id] = semantic_rows
        _validate_policy_semantic_contract(profile, row, selected, semantic_rows)
        policy_writers.extend(_policy_bundle(profile, row, selected, semantic_rows).writers)
    policy_bundle = ConsumerIRBundle(1, (), tuple(policy_writers))
    if (
        enabled_domains is None
        and not attach_policy_profile(policy_bundle, profile).production_connected
    ):
        raise ValueError("1.15 policy bundle 未完整接线")
    compiled: list[decision_rules.RuleSet] = []
    for row in profile.declarations:
        selected = by_consumer[row.id]
        if not selected:
            continue
        semantic_rows = semantic_by_consumer[row.id]
        readers = {
            fact: _policy_reader(fact)
            for item in selected
            for fact in {p[0] for p in _policy_predicates(item)}
        }
        actions = tuple(legacy.to_action_ir() for _, legacy in semantic_rows)
        rules = tuple(action.to_rule() for action in actions)
        source_path = POLICY_DECLARATION if policy is None else Path(policy)
        raw = (Path(baseline_root) / Path(*row.source.split("/"))).read_bytes()
        ruleset = decision_rules.RuleSet(
            readers=tuple(readers.values()),
            rules=rules,
            baseline_sha256=_digest(raw),
            source_sha256=_digest(source_path.read_bytes()),
            enabled_domains=frozenset({row.domain}),
            actor_path=("country",) if row.actor == "country" else (),
            semantic_ir=actions,
            native_root="state" if row.actor == "country" else "country",
        )
        lowered = lower_legacy(ruleset, policy_bundle, source=row.source)
        enabled = programs.enable(lowered, source=row.source)
        programs.validate(enabled)
        if len(enabled.consumer_programs) != 1:
            raise ValueError(f"{row.id}: expected one policy contribution program")
        bounds = _POLICY_BOUNDS[row.id]
        program = enabled.consumer_programs[0]
        if not (bounds[0] <= program.lower <= program.upper <= bounds[1]):
            raise ValueError(f"{row.id}: policy envelope exceeds reviewed bounds {bounds}")
        compiled.append(enabled)
    return policy_bundle, tuple(compiled)


def _policy_marker(row: ConsumerDeclaration, program_text: str) -> str:
    return (
        f"\n\t# SITAI POLICY {expected_version()} BEGIN {row.id}\n"
        + program_text
        + f"\t# SITAI POLICY {expected_version()} END {row.id}\n"
    )


def _insert_policy(text: str, row: ConsumerDeclaration, program_text: str) -> str:
    parsed = parse_bytes(text.encode("utf-8"), row.source)
    if parsed.errors:
        raise ValueError(f"{row.id}: native PDX parse failed: {parsed.errors}")
    _select(parsed.root, (row.definition, *row.field), row.source)
    marker = _policy_marker(row, program_text)
    if row.id == "a0-econ-road":
        value = _select(parsed.root, (row.definition, *row.field, "value"), row.source)
        if getattr(value.value, "text", None) != "25":
            raise ValueError(f"{row.id}: expected native value = 25 before policy insertion")
        lines = text.splitlines(keepends=True)
        offset = sum(len(line) for line in lines[: value.line])
        return text[:offset] + marker + text[offset:]
    position = decision_rules._offsets(text, {(row.definition, *row.field)})[
        (row.definition, *row.field)
    ]
    return text[:position] + marker + text[position:]


def strip_policy(text: str, row: ConsumerDeclaration) -> str:
    marker = re.compile(
        rf"\n\t# SITAI POLICY 1\.15\.[01] BEGIN {re.escape(row.id)}\n"
        r"[\s\S]*?"
        rf"\t# SITAI POLICY 1\.15\.[01] END {re.escape(row.id)}\n"
    )
    restored, count = marker.subn("", text)
    if count != 1:
        raise ValueError(f"{row.id}: expected exactly one policy marker, got {count}")
    return restored


def build_policy_115(
    profile: ProductionProfile,
    baseline_root: Path | None = None,
    *,
    declaration: Path | None = None,
    policy: Path | None = None,
    core_enabled: bool = True,
    enabled_domains: frozenset[str] | None = None,
) -> dict[str, str]:
    """Render the observed policy slice while preserving native tails."""
    baseline_root = globals()["baseline_root"]() if baseline_root is None else Path(baseline_root)
    _, policies = compile_policy_115(
        profile,
        baseline_root,
        declaration=declaration,
        policy=policy,
        enabled_domains=enabled_domains,
    )
    by_source = {item.consumer_programs[0].source: item for item in policies}
    variants = load_policy_115(POLICY_DECLARATION if policy is None else Path(policy))
    files: dict[str, str] = {}
    for row in profile.declarations:
        raw = (Path(baseline_root) / Path(*row.source.split("/"))).read_bytes()
        text = raw.decode("utf-8-sig")
        rendered = text
        ruleset = by_source.get(row.source)
        if core_enabled and ruleset is not None:
            program = ruleset.consumer_programs[0]
            selected = tuple(
                item
                for item in variants
                if item.consumer_id == row.id
                and item.status == "observed"
                and (enabled_domains is None or row.domain in enabled_domains)
            )
            guards = {item.id: item.guard for item in selected}
            ai_guard = (
                "exists = scope:country scope:country = { is_ai = yes }"
                if row.actor == "country"
                else "exists = ROOT ROOT = { is_ai = yes }"
            )
            program_text = programs.render(
                program, guards=guards, ai_guard=ai_guard, descriptions={}, producer_markers={}
            )
            rendered = _insert_policy(text, row, program_text)
            restored = strip_policy(rendered, row)
            prefix = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
            if prefix + restored.encode("utf-8") != raw:
                raise ValueError(f"{row.id}: policy insertion is not reversible")
        files[row.source.removeprefix("game/")] = rendered
        if parse_bytes(rendered.encode("utf-8"), row.source).errors:
            raise ValueError(f"{row.id}: generated policy PDX parse failed")
    return files


def _declared_files(declaration: Path | None = None) -> tuple[str, ...]:
    data, _ = _load_declaration(declaration_path() if declaration is None else Path(declaration))
    return tuple(item["path"] for item in (*data["identity"], *data["input"]))


def capture_baseline(
    installation: Path,
    destination: Path | None = None,
    *,
    declaration: Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Copy the complete declared 1.15 native inputs and write a manifest.

    This function only records bytes after :func:`load_profile` has verified
    their hashes.  It never repairs or rewrites an existing historical
    baseline; callers must opt in to ``overwrite`` and the manifest is still
    checked for exact path/hash coverage before replacement.
    """

    profile = load_profile(installation, declaration)
    declaration = declaration_path() if declaration is None else Path(declaration)
    paths = _declared_files(declaration)
    destination = baseline_root() if destination is None else Path(destination)
    if destination.exists() and not overwrite:
        if not BASELINE_MANIFEST.exists() or destination.resolve() != BASELINE_ROOT.resolve():
            raise ValueError("1.15 baseline 已存在；必须显式 overwrite 才能替换")
        existing = json.loads(BASELINE_MANIFEST.read_text(encoding="utf-8"))
        if existing.get("game_version") == EXPECTED_VERSION:
            raise ValueError("1.15 baseline 已存在，拒绝静默刷新")
    staging = destination.with_name(destination.name + ".staging")
    if staging.exists():
        raise ValueError("1.15 baseline staging 已存在，拒绝删除或覆盖")
    records: list[dict[str, str]] = []
    try:
        for rel in paths:
            source = Path(installation) / Path(*rel.split("/"))
            target = staging / Path(*rel.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            raw = target.read_bytes()
            records.append({"path": rel, "sha256": _digest(raw)})
        manifest = {
            "schema": 1,
            "profile": "situated-ai/production/1.15",
            "game_version": profile.game_version,
            "build_id": profile.build_id,
            "files": records,
        }
        (staging / "baseline-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        # Copying can race with source changes. Do not let freshly calculated
        # manifest hashes reauthorize bytes that differ from the declaration.
        verify_baseline(staging, declaration=declaration)
        if destination.exists():
            if overwrite:
                shutil.rmtree(destination)
            else:
                raise ValueError("1.15 baseline 已存在，拒绝覆盖")
        staging.replace(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return manifest


def _insert_neutral(text: str, row: ConsumerDeclaration, program_text: str) -> str:
    parsed = parse_bytes(text.encode("utf-8"), row.source)
    if parsed.errors:
        raise ValueError(f"{row.id}: native PDX parse failed: {parsed.errors}")
    assignment = _select(parsed.root, (row.definition, *row.field), row.source)
    if not isinstance(assignment.value, Block) or assignment.line != row.baseline_line:
        raise ValueError(f"{row.id}: exact write-point drift")
    # The profile is zero-only. Append after native evaluation without
    # generalizing any of the historical writer placement contracts.
    position = decision_rules._offsets(text, {(row.definition, *row.field)})[
        (row.definition, *row.field)
    ]
    marker = (
        f"\n\t# SITAI PROFILE {expected_version()} BEGIN {row.id}\n"
        + program_text
        + f"\t# SITAI PROFILE {expected_version()} END {row.id}\n"
    )
    return text[:position] + marker + text[position:]


def strip_neutral(text: str, row: ConsumerDeclaration) -> str:
    marker = re.compile(
        rf"\n\t# SITAI PROFILE 1\.15\.[01] BEGIN {re.escape(row.id)}\n"
        r"[\s\S]*?"
        rf"\t# SITAI PROFILE 1\.15\.[01] END {re.escape(row.id)}\n"
    )
    restored, count = marker.subn("", text)
    if count != 1:
        raise ValueError(f"{row.id}: expected exactly one neutral marker, got {count}")
    return restored


def compile_neutral(
    profile: ProductionProfile,
    baseline_root: Path | None = None,
    *,
    declaration: Path | None = None,
) -> tuple[ConsumerIRBundle, tuple[decision_rules.RuleSet, ...]]:
    """Lower the declared neutral policy through the existing RuleSet and IR."""
    baseline_root = globals()["baseline_root"]() if baseline_root is None else Path(baseline_root)
    verify_baseline(baseline_root, declaration=declaration)
    frozen = load_profile(baseline_root, declaration)
    if profile != frozen:
        raise ValueError("profile 与锁定 native baseline 不一致")
    writers = []
    policies = []
    for row in profile.declarations:
        legacy = LegacyDecisionIR(
            action_id=row.id,
            source=row.source,
            definition=row.definition,
            domain=row.domain,
            consumer_id=row.id,
            field=".".join(row.field),
            actor=row.actor,
            target=row.target,
            operation=row.operation,
            value=row.neutral,
            predicates=(),
            vanilla_tail="retain_original_qualification_cost_random_execution",
        )
        context = next(c.context for c in profile.contracts.consumers if c.id == row.id)
        writers.append(
            WriterDecisionIR(
                writer_id=row.id,
                kind="rule_action",
                source=row.source,
                definition=row.definition,
                consumer_id=row.id,
                field=".".join(row.field),
                actor=row.actor,
                target=row.target,
                operation=row.operation,
                vanilla_tail=legacy.vanilla_tail,
                owner=row.domain,
                legacy=legacy,
                evaluation_context=context,
            )
        )
        action_ir = legacy.to_action_ir()
        raw = (baseline_root / row.source).read_bytes()
        policies.append(
            decision_rules.RuleSet(
                readers=(),
                rules=(action_ir.to_rule(),),
                baseline_sha256=_digest(raw),
                source_sha256=_digest(
                    (DECLARATION if declaration is None else declaration).read_bytes()
                ),
                enabled_domains=frozenset({row.domain}),
                actor_path=("country",) if row.actor == "country" else (),
                semantic_ir=(action_ir,),
                native_root="state" if row.actor == "country" else "country",
            )
        )
    bundle = ConsumerIRBundle(1, (), tuple(writers))
    if not attach_profile(bundle, profile).production_connected:
        raise ValueError("1.15 profile: neutral bundle is not production-connected")
    compiled = []
    for row, policy in zip(profile.declarations, policies, strict=True):
        lowered = lower_legacy(policy, bundle, source=row.source)
        enabled = programs.enable(lowered, source=row.source)
        programs.validate(enabled)
        if len(enabled.consumer_programs) != 1:
            raise ValueError(f"{row.id}: expected one physical contribution program")
        program = enabled.consumer_programs[0]
        if (program.lower, program.upper) != (0.0, 0.0) or program.neutral != row.neutral:
            raise ValueError(f"{row.id}: contribution program exceeds zero-only profile")
        compiled.append(enabled)
    bundle.as_dict()
    return bundle, tuple(compiled)


def build_neutral(
    profile: ProductionProfile,
    baseline_root: Path | None = None,
    *,
    declaration: Path | None = None,
    core_enabled: bool = True,
) -> dict[str, str]:
    """Render real zero-bound programs, or restore native bytes with core off."""
    baseline_root = globals()["baseline_root"]() if baseline_root is None else Path(baseline_root)
    _, policies = compile_neutral(profile, baseline_root, declaration=declaration)
    files: dict[str, str] = {}
    for row, policy in zip(profile.declarations, policies, strict=True):
        source = baseline_root / Path(*row.source.split("/"))
        raw = source.read_bytes()
        text = raw.decode("utf-8-sig")
        if "\r" in text:
            raise ValueError(f"{row.id}: unsupported native newline normalization")
        actor = "country" if row.actor == "country" else "ROOT"
        guard = f"exists = {actor} {actor} = {{ is_ai = yes }}"
        program = programs.render(
            policy.consumer_programs[0],
            guards={rule.id: guard for rule in policy.rules},
            ai_guard=guard,
            descriptions={},
            producer_markers={},
        )
        rendered = _insert_neutral(text, row, program) if core_enabled else text
        restored = strip_neutral(rendered, row) if core_enabled else rendered
        prefix = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
        if prefix + restored.encode("utf-8") != raw:
            raise ValueError(f"{row.id}: neutral insertion is not reversible")
        files[row.source.removeprefix("game/")] = rendered
        if parse_bytes(rendered.encode("utf-8"), row.source).errors:
            raise ValueError(f"{row.id}: generated PDX parse failed")
    return files


__all__ += [
    "BASELINE_MANIFEST",
    "BASELINE_ROOT",
    "POLICY_DECLARATION",
    "PolicyVariant",
    "build_neutral",
    "build_policy_115",
    "capture_baseline",
    "compile_neutral",
    "compile_policy_115",
    "load_policy_115",
    "strip_neutral",
    "strip_policy",
    "verify_baseline",
]


def verify_baseline(root: Path | None = None, *, declaration: Path | None = None) -> dict[str, Any]:
    """Verify a frozen baseline's exact path and byte hashes."""

    root = baseline_root() if root is None else Path(root)
    manifest_path = root / "baseline-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"baseline manifest 无效：{manifest_path}") from exc
    if type(manifest) is not dict or set(manifest) != {
        "schema",
        "profile",
        "game_version",
        "build_id",
        "files",
    }:
        raise ValueError("baseline manifest schema 不匹配")
    if (
        manifest.get("schema") != 1
        or manifest.get("game_version")
        != _load_declaration(declaration_path() if declaration is None else Path(declaration))[0][
            "game_version"
        ]
        or manifest.get("profile") != "situated-ai/production/1.15"
    ):
        raise ValueError("baseline manifest profile/version 不匹配")
    expected = _declared_files(declaration)
    rows = manifest.get("files")
    if (
        not isinstance(rows, list)
        or any(type(row) is not dict or set(row) != {"path", "sha256"} for row in rows)
        or tuple(row.get("path") for row in rows) != expected
    ):
        raise ValueError("baseline manifest 路径集合或顺序与声明不一致")
    data, declarations = _load_declaration(
        declaration_path() if declaration is None else Path(declaration)
    )
    pinned = tuple((item["path"], item["sha256"]) for item in (*data["identity"], *data["input"]))
    if tuple((row["path"], row["sha256"]) for row in rows) != pinned:
        raise ValueError("baseline manifest hash 与独立声明不一致")
    for row in rows:
        rel, digest = row.get("path"), row.get("sha256")
        path = root / Path(*rel.split("/"))
        if path.is_symlink() or not path.is_file() or _digest(path.read_bytes()) != digest:
            raise ValueError(f"baseline 字节漂移：{rel}")
    _verify_native(root, data, declarations)
    loaded = load_profile(root, declaration)
    if manifest["build_id"] != loaded.build_id:
        raise ValueError("baseline manifest build_id 不一致")
    return manifest
