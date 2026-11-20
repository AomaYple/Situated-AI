"""Strict 1.15 production profile for the three A0 consumers.

The profile is an identity and contract boundary.  It deliberately does not
contain policy weights or a second action IR: policy remains in the existing
``ConsumerIRBundle`` supplied by the producer.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pdx import decision_rules, version_contracts
from pdx.model import Assignment, Block
from pdx.parser import parse_bytes

from . import core_contracts, domain_registry
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
)
from .domain_registry import DomainManifest, ValidatedModel
from .schema import UnknownPolicy  # noqa: TC001

ROOT = Path(__file__).resolve().parents[3]
DECLARATION = ROOT / "mod" / "decisions" / "architecture_1152.toml"


def expected_version() -> str:
    return version_contracts.require_current()


def declaration_path(version: str | None = None) -> Path:
    version_contracts.require_current(version)
    return DECLARATION


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
    if data.get("game_version") != version_contracts.CURRENT_VERSION:
        raise _fail("game_version", "必须为已声明的原版版本")
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
                raise _fail(f"identity[{index}].raw_version", "必须与声明版本一致")
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
                raise _fail(rel, "rawVersion 与声明版本不一致")
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
            if text != expected:
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
    return _profile(data, rows, hashes)


def declared_profile() -> ProductionProfile:
    """Build the current static contract without opening installed scripts."""
    version_contracts.require_current()
    data, rows = _load_declaration(declaration_path())
    if data["game_version"] != version_contracts.CURRENT_VERSION:
        raise _fail("game_version", "当前生产声明版本不匹配")
    hashes = tuple((item["path"], item["sha256"]) for item in (*data["identity"], *data["input"]))
    return _profile(data, rows, hashes)


def _profile(
    data: dict[str, Any],
    rows: tuple[ConsumerDeclaration, ...],
    hashes: tuple[tuple[str, str], ...],
) -> ProductionProfile:
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


__all__ = ["ConsumerDeclaration", "ProductionProfile", "attach_profile", "load_profile"]


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
        rf"\n\t# SITAI POLICY 1\.15\.[012] BEGIN {re.escape(row.id)}\n"
        r"[\s\S]*?"
        rf"\t# SITAI POLICY 1\.15\.[012] END {re.escape(row.id)}\n"
    )
    restored, count = marker.subn("", text)
    if count != 1:
        raise ValueError(f"{row.id}: expected exactly one policy marker, got {count}")
    return restored
