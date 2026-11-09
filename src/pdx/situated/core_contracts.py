"""1.15 核心的不可变声明合同；不包含政策、行动表达式或引擎能力推断。

模式 1 的公开映射入口统一拒绝未知字段和隐式转换。破坏性字段、单位或
生命周期变更必须增加模式版本；本模块不自动迁移旧模式。行动及程序仍由
``decision_ir.ConsumerIRBundle`` 和 ``programs.ConsumerProgram`` 唯一承载。
"""

from __future__ import annotations

import math
import re
import types
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from pathlib import PurePosixPath
from typing import Literal, Self, Union, cast, get_args, get_origin, get_type_hints

from .decision_ir import ConsumerIRBundle, EvaluationContext  # noqa: TC001
from .schema import EvidenceKind, UnknownPolicy  # noqa: TC001

EntityKind = Literal[
    "country",
    "state",
    "building",
    "law",
    "good",
    "interest_group",
    "military_formation",
    "market",
    "strategic_region",
    "diplomatic_play",
    "ship_modification",
    "scalar",
]
Unit = Literal[
    "boolean",
    "ratio",
    "percent",
    "currency_per_week",
    "people",
    "points",
    "consumer_score",
    "multiplier",
    "enum",
]
Knowledge = Literal["known", "unknown", "stale", "unsupported", "invalid"]
Scalar = bool | int | float | str
_ID = re.compile(r"[a-z][a-z0-9_.-]*\Z")
_ENTITY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*\Z")


def stable_id(value: str, path: str) -> None:
    if not _ID.fullmatch(value):
        raise ValueError(f"{path}: 非法稳定 ID {value!r}")


def unique(values: tuple[object, ...], path: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{path}: 重复身份")


def safe_path(value: str, path: str) -> None:
    parts = PurePosixPath(value).parts
    if not value or "\\" in value or ":" in value or value.startswith("/") or ".." in parts:
        raise ValueError(f"{path}: 必须是安全的相对 POSIX 路径")


def _typed(value: object, annotation: object, path: str, *, decode: bool) -> object:
    """严格转换只在映射入口允许 JSON list → tuple；从不转换布尔或字符串数值。"""
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is Literal:
        if not any(type(value) is type(choice) and value == choice for choice in args):
            raise ValueError(f"{path}: 非法枚举 {value!r}")
        return value
    if origin in (Union, types.UnionType):
        for choice in args:
            try:
                return _typed(value, choice, path, decode=decode)
            except ValueError:
                pass
        raise ValueError(f"{path}: 类型或有限数无效")
    if origin is tuple:
        if not isinstance(value, tuple) and not (decode and isinstance(value, list)):
            raise ValueError(f"{path}: 必须是不可变 tuple")
        sequence = cast("tuple[object, ...] | list[object]", value)
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(
                _typed(item, args[0], f"{path}[{i}]", decode=decode)
                for i, item in enumerate(sequence)
            )
        if len(sequence) != len(args):
            raise ValueError(f"{path}: tuple 长度无效")
        return tuple(
            _typed(item, arg, f"{path}[{i}]", decode=decode)
            for i, (item, arg) in enumerate(zip(sequence, args, strict=True))
        )
    if annotation is type(None):
        if value is not None:
            raise ValueError(f"{path}: 必须为 null")
        return None
    if isinstance(annotation, type) and is_dataclass(annotation):
        if decode and isinstance(value, Mapping):
            return _decode(annotation, value, path)
        if not isinstance(value, annotation):
            raise ValueError(f"{path}: 必须为 {annotation.__name__}")
        return value
    if annotation in (bool, int, float, str):
        allowed = (int, float) if annotation is float else (annotation,)
        if type(value) not in allowed:
            raise ValueError(f"{path}: 类型无效")
        if type(value) in (int, float) and not math.isfinite(cast("float", value)):
            raise ValueError(f"{path}: 必须是有限数")
        return value
    raise ValueError(f"{path}: 未支持的模式类型 {annotation}")


def _decode(cls: type, data: Mapping[object, object], path: str) -> object:
    declared = {field.name for field in fields(cls)}
    unknown = set(data) - declared
    if unknown:
        raise ValueError(f"{path}: 未知字段 {sorted(map(str, unknown))}")
    hints = get_type_hints(cls)
    result = {
        name: _typed(value, hints[name], f"{path}.{name}", decode=True)
        for name, value in data.items()
        if isinstance(name, str)
    }
    try:
        return cls(**result)
    except TypeError as exc:
        raise ValueError(f"{path}: 缺少必需字段或模式不匹配: {exc}") from exc


def _encode(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _encode(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class StrictContract:
    schema_version: Literal[1] = 1

    def __post_init__(self) -> None:
        hints = get_type_hints(type(self))
        for field in fields(self):
            _typed(
                getattr(self, field.name),
                hints[field.name],
                f"{type(self).__name__}.{field.name}",
                decode=False,
            )
        self._check()

    def _check(self) -> None:
        """子类的语义约束；通用类型与冻结约束已完成。"""

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> Self:
        if not isinstance(data, Mapping):
            raise ValueError(f"{cls.__name__}: 需要 mapping")
        return cast("Self", _decode(cls, cast("Mapping[object, object]", data), cls.__name__))

    def as_dict(self) -> dict[str, object]:
        return cast("dict[str, object]", _encode(self))


@dataclass(frozen=True, slots=True)
class EvidenceRef(StrictContract):
    source: str
    line: int

    def _check(self) -> None:
        safe_path(self.source, "EvidenceRef.source")
        if self.line < 1:
            raise ValueError("EvidenceRef.line: 需要正数行号")


@dataclass(frozen=True, slots=True)
class EntityKey(StrictContract):
    kind: EntityKind
    id: str

    def _check(self) -> None:
        if not _ENTITY_ID.fullmatch(self.id):
            raise ValueError("EntityKey.id: 缺少精确实体身份")


@dataclass(frozen=True, slots=True)
class TimeIdentity(StrictContract):
    epoch: str
    evaluation: int

    def _check(self) -> None:
        stable_id(self.epoch, "TimeIdentity.epoch")
        if self.evaluation < 0:
            raise ValueError("TimeIdentity.evaluation: 不能为负数")


@dataclass(frozen=True, slots=True)
class CapabilitySpec(StrictContract):
    id: str
    status: Literal["known", "unknown", "unsupported"]
    evidence: tuple[EvidenceRef, ...]

    def _check(self) -> None:
        stable_id(self.id, "CapabilitySpec.id")
        if self.status != "unknown" and not self.evidence:
            raise ValueError(f"CapabilitySpec.{self.id}: 已知或不支持状态需要证据")


@dataclass(frozen=True, slots=True)
class CapabilityProfile(StrictContract):
    game_version: str
    build_id: str
    input_hashes: tuple[tuple[str, str], ...]
    dlc: tuple[str, ...]
    capabilities: tuple[CapabilitySpec, ...]

    def _check(self) -> None:
        if not self.game_version or not self.build_id or not self.input_hashes:
            raise ValueError("CapabilityProfile: 游戏、构建及输入身份不能缺失")
        unique(tuple(path for path, _ in self.input_hashes), "CapabilityProfile.input_hashes")
        unique(tuple(item.id for item in self.capabilities), "CapabilityProfile.capabilities")
        unique(self.dlc, "CapabilityProfile.dlc")
        for path, digest in self.input_hashes:
            safe_path(path, "CapabilityProfile.input_hashes")
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError(f"CapabilityProfile.input_hashes.{path}: 非法 SHA-256")

    @property
    def available(self) -> frozenset[str]:
        return frozenset(item.id for item in self.capabilities if item.status == "known")


@dataclass(frozen=True, slots=True)
class Observation(StrictContract):
    spec_id: str
    entity: EntityKey
    unit: Unit
    status: Knowledge
    time: TimeIdentity
    value: Scalar | None
    sources: tuple[EvidenceRef, ...]

    def _check(self) -> None:
        stable_id(self.spec_id, "Observation.spec_id")
        if self.status == "invalid":
            raise ValueError(f"Observation.{self.spec_id}: invalid 输入必须在边界失败")
        if self.status == "known" and (self.value is None or not self.sources):
            raise ValueError(f"Observation.{self.spec_id}: known 需要值和来源")
        if self.status in {"unknown", "unsupported"} and self.value is not None:
            raise ValueError(f"Observation.{self.spec_id}: {self.status} 不能携带已知值")
        if self.status == "unsupported" and not self.sources:
            raise ValueError("Observation.unsupported: 需要能力证据")

    def usable_at(self, time: TimeIdentity) -> bool:
        return self.status == "known" and self.time == time


@dataclass(frozen=True, slots=True)
class FactSpec(StrictContract):
    id: str
    reader_id: str
    kind: EvidenceKind
    unit: Unit
    entity_kind: EntityKind
    binding: Literal["actor", "target"]
    consumer_ids: tuple[str, ...]
    sources: tuple[EvidenceRef, ...]
    minimum: float | None = None
    maximum: float | None = None
    enum_values: tuple[str, ...] = ()
    timing: Literal["consumer_on_demand"] = "consumer_on_demand"
    unknown_policy: UnknownPolicy = "vanilla"

    def _check(self) -> None:
        stable_id(self.id, "FactSpec.id")
        stable_id(self.reader_id, f"FactSpec.{self.id}.reader_id")
        if not self.sources or not self.consumer_ids:
            raise ValueError(f"FactSpec.{self.id}: 缺少来源或合法消费者")
        unique(self.consumer_ids, f"FactSpec.{self.id}.consumer_ids")
        for consumer in self.consumer_ids:
            stable_id(consumer, f"FactSpec.{self.id}.consumer_ids")
        if (
            (self.kind == "boolean") != (self.unit == "boolean")
            or (self.kind == "enum") != (self.unit == "enum")
            or (self.kind == "ratio" and self.unit != "ratio")
        ):
            raise ValueError(f"FactSpec.{self.id}: 类型与单位不一致")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError(f"FactSpec.{self.id}: 边界倒置")
        if (self.kind == "enum") != bool(self.enum_values):
            raise ValueError(f"FactSpec.{self.id}: 枚举值域缺失或不适用")
        unique(self.enum_values, f"FactSpec.{self.id}.enum_values")

    def validate_observation(
        self,
        observation: Observation,
        *,
        actor: EntityKey,
        target: EntityKey | None,
        consumer_id: str,
        time: TimeIdentity,
    ) -> None:
        expected = actor if self.binding == "actor" else target
        if (
            observation.spec_id != self.id
            or observation.unit != self.unit
            or observation.entity.kind != self.entity_kind
            or observation.entity != expected
            or observation.time != time
            or consumer_id not in self.consumer_ids
        ):
            raise ValueError(f"FactSpec.{self.id}: 单位、对象、消费者或时间串接")
        value = observation.value
        if value is None:
            return
        if self.kind == "boolean":
            valid = type(value) is bool
        elif self.kind == "enum":
            valid = isinstance(value, str) and value in self.enum_values
        else:
            valid = type(value) in (int, float)
            if valid:
                number = cast("float", value)
                valid = (self.minimum is None or number >= self.minimum) and (
                    self.maximum is None or number <= self.maximum
                )
        if not valid:
            raise ValueError(f"FactSpec.{self.id}: 值类型或单位范围无效")


@dataclass(frozen=True, slots=True)
class EvaluationSchedule(StrictContract):
    id: str
    consumer_id: str
    sources: tuple[EvidenceRef, ...]
    trigger: Literal["consumer_on_demand"] = "consumer_on_demand"
    ttl: Literal["current_evaluation"] = "current_evaluation"
    invalidates: tuple[Literal["new_evaluation", "fact_change", "target_change", "load"], ...] = (
        "new_evaluation",
        "fact_change",
        "target_change",
        "load",
    )
    idempotency: Literal["same_inputs_same_result"] = "same_inputs_same_result"
    save_boundary: Literal["discard"] = "discard"
    runtime_status: Literal["unknown"] = "unknown"

    def _check(self) -> None:
        stable_id(self.id, "EvaluationSchedule.id")
        stable_id(self.consumer_id, f"EvaluationSchedule.{self.id}.consumer_id")
        if not self.sources or set(self.invalidates) != {
            "new_evaluation",
            "fact_change",
            "target_change",
            "load",
        }:
            raise ValueError(f"EvaluationSchedule.{self.id}: 来源或失效边界不完整")
        unique(self.invalidates, f"EvaluationSchedule.{self.id}.invalidates")


@dataclass(frozen=True, slots=True)
class SituationSnapshot(StrictContract):
    actor: EntityKey
    target: EntityKey | None
    consumer_id: str
    time: TimeIdentity
    aggregation: Literal["country", "local", "non_aggregable"]
    observations: tuple[Observation, ...]
    schedule_id: str
    missing_policy: Literal["vanilla"] = "vanilla"

    def _check(self) -> None:
        if self.actor.kind != "country":
            raise ValueError("SituationSnapshot.actor: 必须为国家")
        stable_id(self.consumer_id, "SituationSnapshot.consumer_id")
        stable_id(self.schedule_id, "SituationSnapshot.schedule_id")
        identities = tuple((item.spec_id, item.entity) for item in self.observations)
        unique(identities, "SituationSnapshot.observations")
        if any(item.time != self.time for item in self.observations):
            raise ValueError("SituationSnapshot: 禁止混入其他求值时点")
        if self.aggregation == "local" and self.target is None:
            raise ValueError("SituationSnapshot.local: 需要地方目标")

    def validate(self, facts: tuple[FactSpec, ...], schedule: EvaluationSchedule) -> None:
        if schedule.id != self.schedule_id or schedule.consumer_id != self.consumer_id:
            raise ValueError("SituationSnapshot: 重评合同不匹配")
        unique(tuple(item.id for item in facts), "SituationSnapshot.facts")
        specs = {item.id: item for item in facts}
        for item in self.observations:
            if item.spec_id not in specs:
                raise ValueError(f"SituationSnapshot: 未声明事实 {item.spec_id}")
            specs[item.spec_id].validate_observation(
                item,
                actor=self.actor,
                target=self.target,
                consumer_id=self.consumer_id,
                time=self.time,
            )

    def usable_at(self, time: TimeIdentity) -> bool:
        return self.time == time


@dataclass(frozen=True, slots=True)
class ObjectiveRelation(StrictContract):
    other_id: str
    kind: Literal["conflicts", "coexists", "tradeoff", "priority"]
    reason: str

    def _check(self) -> None:
        stable_id(self.other_id, "ObjectiveRelation.other_id")
        if not self.reason.strip():
            raise ValueError("ObjectiveRelation.reason: 缺少权衡依据")


@dataclass(frozen=True, slots=True)
class InterestSpec(StrictContract):
    id: str
    actor: EntityKey
    target: EntityKey | None
    source_fact_ids: tuple[str, ...]
    starts: TimeIdentity
    deadline: TimeIdentity
    baseline: Observation
    relations: tuple[ObjectiveRelation, ...]
    consumer_ids: tuple[str, ...]
    status: Literal["known", "unknown", "unwired"]

    def _check(self) -> None:
        stable_id(self.id, "InterestSpec.id")
        if self.actor.kind != "country":
            raise ValueError(f"InterestSpec.{self.id}.actor: 必须为国家")
        if (
            self.starts.epoch != self.deadline.epoch
            or self.deadline.evaluation < self.starts.evaluation
        ):
            raise ValueError(f"InterestSpec.{self.id}: 期限与开始时点不兼容")
        if (
            self.baseline.time != self.starts
            or self.baseline.entity not in (self.actor, self.target)
            or self.baseline.spec_id not in self.source_fact_ids
        ):
            raise ValueError(f"InterestSpec.{self.id}: 现状基准对象、来源或时点不一致")
        if self.status == "known" and (
            not self.source_fact_ids or not self.consumer_ids or self.baseline.status != "known"
        ):
            raise ValueError(f"InterestSpec.{self.id}: 已知利益需要来源、基准和消费者接线")
        if self.status == "unwired" and self.consumer_ids:
            raise ValueError(f"InterestSpec.{self.id}: 未接线利益不能声明消费者")
        unique(self.source_fact_ids, f"InterestSpec.{self.id}.source_fact_ids")
        unique(self.consumer_ids, f"InterestSpec.{self.id}.consumer_ids")
        unique(tuple(item.other_id for item in self.relations), f"InterestSpec.{self.id}.relations")
        if any(item.other_id == self.id for item in self.relations):
            raise ValueError(f"InterestSpec.{self.id}: 不能与自身建立冲突关系")


ActorObjectiveSpec = InterestSpec


@dataclass(frozen=True, slots=True)
class ConsumerSpec(StrictContract):
    id: str
    source: str
    definition: str
    field: tuple[str, ...]
    context: EvaluationContext
    operation: Literal["add", "multiply"]
    unit: Literal["consumer_score", "multiplier"]
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
    baseline: EvidenceRef
    schedule_id: str

    def _check(self) -> None:
        stable_id(self.id, "ConsumerSpec.id")
        stable_id(self.schedule_id, f"ConsumerSpec.{self.id}.schedule_id")
        safe_path(self.source, f"ConsumerSpec.{self.id}.source")
        if not self.definition or not self.field or any(not item for item in self.field):
            raise ValueError(f"ConsumerSpec.{self.id}: 缺少物理写点")
        expected = (0.0, "consumer_score") if self.operation == "add" else (1.0, "multiplier")
        if (self.neutral, self.unit) != expected:
            raise ValueError(f"ConsumerSpec.{self.id}: 操作、neutral 与单位不匹配")
        if not self.bounds[0] <= self.neutral <= self.bounds[1] or (
            self.operation == "multiply" and self.bounds[0] <= 0
        ):
            raise ValueError(f"ConsumerSpec.{self.id}: 非法消费者边界")
        if (
            self.context.status != "observed"
            or not self.vanilla_tail
            or any(
                not item.strip()
                for item in (
                    self.comparator,
                    self.candidate_set,
                    self.eligibility,
                    self.tie_break,
                    self.random,
                    self.all_zero,
                    *self.vanilla_tail,
                )
            )
        ):
            raise ValueError(f"ConsumerSpec.{self.id}: 缺少已证实上下文或原版比较/尾部语义")

    @property
    def write_point(self) -> tuple[str, str, tuple[str, ...]]:
        return self.source, self.definition, self.field


@dataclass(frozen=True, slots=True)
class SelectionWitness(StrictContract):
    consumer_id: str
    candidates: tuple[EntityKey, ...]
    eligible: tuple[EntityKey, ...]
    comparator: str
    objective_ids: tuple[str, ...]
    unknown_policy: UnknownPolicy
    neutral: float
    tie_break: str
    random: str
    all_zero: str
    baseline: EvidenceRef

    def _check(self) -> None:
        stable_id(self.consumer_id, "SelectionWitness.consumer_id")
        unique(self.candidates, "SelectionWitness.candidates")
        unique(self.eligible, "SelectionWitness.eligible")
        unique(self.objective_ids, "SelectionWitness.objective_ids")
        if not set(self.eligible) <= set(self.candidates):
            raise ValueError("SelectionWitness.eligible: 原版资格集合不能引入额外候选")

    def validate(self, consumer: ConsumerSpec) -> None:
        for name in (
            "comparator",
            "unknown_policy",
            "neutral",
            "tie_break",
            "random",
            "all_zero",
            "baseline",
        ):
            if getattr(self, name) != getattr(consumer, name):
                raise ValueError(f"SelectionWitness.{name}: 消费者原版语义不一致")
        if self.consumer_id != consumer.id:
            raise ValueError("SelectionWitness: 禁止跨消费者构造国家赢家")


@dataclass(frozen=True, slots=True)
class WriteOwnership(StrictContract):
    source: str
    definition: str
    field: tuple[str, ...]
    owner: str

    def _check(self) -> None:
        safe_path(self.source, "WriteOwnership.source")
        stable_id(self.owner, "WriteOwnership.owner")
        if not self.definition or not self.field or any(not item for item in self.field):
            raise ValueError("WriteOwnership: 缺少物理定义或字段路径")

    @property
    def write_point(self) -> tuple[str, str, tuple[str, ...]]:
        return self.source, self.definition, self.field


@dataclass(frozen=True, slots=True)
class ConfigurationOption(StrictContract):
    id: str
    kind: Literal["boolean", "number", "enum"]
    default: Scalar
    choices: tuple[str, ...]
    minimum: float | None
    maximum: float | None
    requires_modules: tuple[str, ...]
    requires_capabilities: tuple[str, ...]
    requires_options: tuple[str, ...]
    disabled_value: Scalar | None
    fallback: Literal["vanilla"] = "vanilla"

    def _check(self) -> None:
        stable_id(self.id, "ConfigurationOption.id")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError(f"ConfigurationOption.{self.id}: 范围倒置")
        if (self.kind == "enum") != bool(self.choices):
            raise ValueError(f"ConfigurationOption.{self.id}: 枚举值域无效")
        unique(self.choices, f"ConfigurationOption.{self.id}.choices")
        for dependencies in (
            self.requires_modules,
            self.requires_capabilities,
            self.requires_options,
        ):
            unique(dependencies, f"ConfigurationOption.{self.id}.dependencies")
            for dependency in dependencies:
                stable_id(dependency, f"ConfigurationOption.{self.id}.dependencies")
        self.validate_value(self.default)
        if self.disabled_value is not None:
            self.validate_value(self.disabled_value)

    def validate_value(self, value: object) -> None:
        if self.kind == "boolean":
            valid = type(value) is bool
        elif self.kind == "enum":
            valid = isinstance(value, str) and value in self.choices
        else:
            valid = type(value) in (int, float)
            if valid:
                number = cast("float", value)
                valid = (
                    math.isfinite(number)
                    and (self.minimum is None or number >= self.minimum)
                    and (self.maximum is None or number <= self.maximum)
                )
        if not valid:
            raise ValueError(f"ConfigurationOption.{self.id}: 非法配置值 {value!r}")


@dataclass(frozen=True, slots=True)
class ConfigurationSpec(StrictContract):
    options: tuple[ConfigurationOption, ...]
    exclusions: tuple[tuple[str, ...], ...]

    def _check(self) -> None:
        unique(tuple(item.id for item in self.options), "ConfigurationSpec.options")
        ids = {item.id for item in self.options}
        for item in self.options:
            if not set(item.requires_options) <= ids or item.id in item.requires_options:
                raise ValueError(f"ConfigurationSpec.{item.id}: 未声明或自依赖选项")
        for group in self.exclusions:
            unique(group, "ConfigurationSpec.exclusions")
            if len(group) < 2 or not set(group) <= ids:
                raise ValueError("ConfigurationSpec.exclusions: 非法配置组合")

    def resolve(
        self,
        values: Mapping[str, object],
        *,
        modules: frozenset[str],
        capabilities: frozenset[str],
    ) -> tuple[tuple[str, Scalar], ...]:
        options = {item.id: item for item in self.options}
        if set(values) - set(options):
            raise ValueError(f"ConfigurationSpec: 未知配置 {sorted(set(values) - set(options))}")
        selected: dict[str, Scalar] = {}
        for item in self.options:
            value = values.get(item.id, item.default)
            item.validate_value(value)
            selected[item.id] = cast("Scalar", value)
        enabled = {
            key
            for key, value in selected.items()
            if options[key].disabled_value is None or value != options[key].disabled_value
        }
        for key in sorted(enabled):
            item = options[key]
            if (
                not set(item.requires_modules) <= modules
                or not set(item.requires_capabilities) <= capabilities
                or not set(item.requires_options) <= enabled
            ):
                raise ValueError(f"ConfigurationSpec.{key}: 模块、能力或配置依赖未启用")
        if any(len(set(group) & enabled) > 1 for group in self.exclusions):
            raise ValueError("ConfigurationSpec: 互斥配置不能同时启用")
        return tuple(sorted(selected.items()))


@dataclass(frozen=True, slots=True)
class LocalizationEntry(StrictContract):
    language: str
    key: str
    text: str
    header: str
    path: str

    def _check(self) -> None:
        stable_id(self.language, "LocalizationEntry.language")
        stable_id(self.key, "LocalizationEntry.key")
        safe_path(self.path, "LocalizationEntry.path")
        if (
            not self.key.startswith("sitai_")
            or not self.text.strip()
            or "\ufeff" in self.text
            or "\r" in self.text
            or self.header != f"l_{self.language}:"
            or self.path != f"localization/{self.language}/sitai_l_{self.language}.yml"
        ):
            raise ValueError(
                f"LocalizationEntry.{self.language}.{self.key}: 键、语言头、文本或路径无效"
            )

    @property
    def placeholders(self) -> tuple[str, ...]:
        return tuple(sorted(re.findall(r"\$([^$\n]+)\$", self.text)))


@dataclass(frozen=True, slots=True)
class LocalizationContract(StrictContract):
    languages: tuple[str, ...]
    language_source: EvidenceRef
    owned_keys: tuple[str, ...]
    entries: tuple[LocalizationEntry, ...]
    source_encoding: Literal["utf-8"] = "utf-8"
    delivery_encoding: Literal["utf-8-sig"] = "utf-8-sig"

    def _check(self) -> None:
        unique(self.languages, "LocalizationContract.languages")
        unique(self.owned_keys, "LocalizationContract.owned_keys")
        if not self.languages:
            raise ValueError("LocalizationContract: 独立语言分母不能为空")
        expected = {(language, key) for language in self.languages for key in self.owned_keys}
        actual = tuple((item.language, item.key) for item in self.entries)
        unique(actual, "LocalizationContract.entries")
        if set(actual) != expected:
            raise ValueError("LocalizationContract: 语言分母与自有键集合不一致")
        for key in self.owned_keys:
            placeholders = {item.placeholders for item in self.entries if item.key == key}
            if len(placeholders) != 1:
                raise ValueError(f"LocalizationContract.{key}: 各语言占位符不一致")


@dataclass(frozen=True, slots=True)
class CoreContracts(StrictContract):
    facts: tuple[FactSpec, ...]
    consumers: tuple[ConsumerSpec, ...]
    schedules: tuple[EvaluationSchedule, ...]
    objectives: tuple[InterestSpec, ...] = ()
    configuration: ConfigurationSpec | None = None
    localization: LocalizationContract | None = None

    def _check(self) -> None:
        for name in ("facts", "consumers", "schedules", "objectives"):
            unique(tuple(item.id for item in getattr(self, name)), f"CoreContracts.{name}")
        consumers = {item.id: item for item in self.consumers}
        schedules = {item.id: item for item in self.schedules}
        facts = {item.id: item for item in self.facts}
        unique(tuple(item.write_point for item in self.consumers), "CoreContracts.write_points")
        unique(
            tuple(item.consumer_id for item in self.schedules), "CoreContracts.schedule_consumers"
        )
        for item in self.consumers:
            schedule = schedules.get(item.schedule_id)
            if schedule is None or schedule.consumer_id != item.id:
                raise ValueError(f"CoreContracts.consumers.{item.id}: 缺少持续评估合同")
        if {item.consumer_id for item in self.schedules} != set(consumers):
            raise ValueError("CoreContracts.schedules: 孤立消费者")
        for fact in self.facts:
            if not set(fact.consumer_ids) <= set(consumers):
                raise ValueError(f"CoreContracts.facts.{fact.id}: 未声明消费者")
        objective_ids = {objective.id for objective in self.objectives}
        for objective in self.objectives:
            if (
                not set(objective.source_fact_ids) <= set(facts)
                or not set(objective.consumer_ids) <= set(consumers)
                or any(relation.other_id not in objective_ids for relation in objective.relations)
            ):
                raise ValueError(
                    f"CoreContracts.objectives.{objective.id}: 未声明事实、消费者或目标关系"
                )
            for consumer in objective.consumer_ids:
                facts[objective.baseline.spec_id].validate_observation(
                    objective.baseline,
                    actor=objective.actor,
                    target=objective.target,
                    consumer_id=consumer,
                    time=objective.starts,
                )


@dataclass(frozen=True, slots=True)
class ContractAttachment:
    """附着现有唯一 IR；空 bundle 不构成生产接线证据。"""

    bundle: ConsumerIRBundle
    contracts: CoreContracts
    production_connected: bool


def attach_bundle(bundle: ConsumerIRBundle, contracts: CoreContracts) -> ContractAttachment:
    """检查已有 writer 与声明的精确写点，不构造第二份行动或程序。"""
    consumers = {item.id: item for item in contracts.consumers}
    claimed: set[tuple[str, str, tuple[str, ...]]] = set()
    for writer in bundle.writers:
        consumer = consumers.get(writer.consumer_id)
        if consumer is None:
            raise ValueError(f"attach_bundle.{writer.writer_id}: 缺少消费者合同")
        if (
            (writer.source, writer.definition, tuple(writer.field.split(".")))
            != consumer.write_point
            or writer.operation != consumer.operation
            or writer.evaluation_context != consumer.context
        ):
            raise ValueError(f"attach_bundle.{writer.writer_id}: 原 IR 写点、操作或上下文不匹配")
        if consumer.write_point in claimed:
            raise ValueError(f"attach_bundle.{writer.writer_id}: 物理消费者重复写入")
        claimed.add(consumer.write_point)
    return ContractAttachment(bundle, contracts, bool(claimed) and len(claimed) == len(consumers))
