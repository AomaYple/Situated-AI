"""确定性的构建期领域注册；只依赖公开合同，不反向导入领域政策。"""

from __future__ import annotations

from collections.abc import Mapping  # noqa: TC003
from dataclasses import dataclass

from .core_contracts import (
    CapabilityProfile,
    ConfigurationOption,
    ConfigurationSpec,
    FactSpec,
    Scalar,
    StrictContract,
    WriteOwnership,
    stable_id,
    unique,
)


@dataclass(frozen=True, slots=True)
class DomainManifest(StrictContract):
    id: str
    provides: tuple[str, ...]
    consumes: tuple[str, ...]
    dependencies: tuple[str, ...]
    requires_capabilities: tuple[str, ...]
    facts: tuple[FactSpec, ...]
    action_ids: tuple[str, ...]
    relation_ids: tuple[str, ...]
    writes: tuple[WriteOwnership, ...]
    object_budget: int
    witness_ids: tuple[str, ...]
    configuration: ConfigurationSpec | None = None

    def _check(self) -> None:
        stable_id(self.id, "DomainManifest.id")
        if self.object_budget < 1:
            raise ValueError(f"DomainManifest.{self.id}.object_budget: 必须有界且为正数")
        for name in (
            "provides",
            "consumes",
            "dependencies",
            "requires_capabilities",
            "action_ids",
            "relation_ids",
            "witness_ids",
        ):
            values = getattr(self, name)
            unique(values, f"DomainManifest.{self.id}.{name}")
            for value in values:
                stable_id(value, f"DomainManifest.{self.id}.{name}")
        unique(tuple(item.id for item in self.facts), f"DomainManifest.{self.id}.facts")
        unique(tuple(item.write_point for item in self.writes), f"DomainManifest.{self.id}.writes")


@dataclass(frozen=True, slots=True)
class ValidatedModel:
    manifests: tuple[DomainManifest, ...]
    profile: CapabilityProfile
    configuration: tuple[tuple[str, Scalar], ...]


def _order(manifests: tuple[DomainManifest, ...]) -> tuple[DomainManifest, ...]:
    lookup = {item.id: item for item in manifests}
    complete: set[str] = set()
    pending: list[str] = []
    result: list[DomainManifest] = []

    def visit(key: str) -> None:
        if key in complete:
            return
        if key in pending:
            raise ValueError(f"DomainManifest.dependencies: 循环 {' -> '.join((*pending, key))}")
        if key not in lookup:
            raise ValueError(f"DomainManifest.dependencies: 缺少 {' -> '.join((*pending, key))}")
        pending.append(key)
        for dependency in sorted(lookup[key].dependencies):
            visit(dependency)
        pending.pop()
        complete.add(key)
        result.append(lookup[key])

    for key in sorted(lookup):
        visit(key)
    return tuple(result)


def validate(
    manifests: tuple[DomainManifest, ...],
    profile: CapabilityProfile,
    *,
    configuration: Mapping[str, object] | None = None,
) -> ValidatedModel:
    """验证依赖、公开接口、能力、全局身份与单写者；不签发引擎或生产接线证明。"""
    unique(tuple(item.id for item in manifests), "DomainManifest.id")
    ordered = _order(manifests)
    providers: dict[str, str] = {}
    writes: dict[tuple[str, str, tuple[str, ...]], str] = {}
    identities: dict[str, str] = {}
    options: list[ConfigurationOption] = []
    exclusions: list[tuple[str, ...]] = []
    for item in ordered:
        missing = set(item.requires_capabilities) - profile.available
        if missing:
            raise ValueError(
                f"DomainManifest.{item.id}.requires_capabilities: 能力不足 {sorted(missing)}"
            )
        for interface in item.provides:
            if interface in providers:
                raise ValueError(
                    f"DomainManifest.{item.id}.provides.{interface}: 重复提供者 {providers[interface]}"
                )
            providers[interface] = item.id
        for identity in (
            *tuple(fact.id for fact in item.facts),
            *item.action_ids,
            *item.relation_ids,
        ):
            if identity in identities:
                raise ValueError(
                    f"DomainManifest.{item.id}.{identity}: 稳定 ID 与 {identities[identity]} 重复"
                )
            identities[identity] = item.id
        for write in item.writes:
            if write.write_point in writes:
                raise ValueError(
                    f"DomainManifest.{item.id}.writes: 重复写点 {write.write_point}, 已由 {writes[write.write_point]} 声明"
                )
            writes[write.write_point] = item.id
        if item.configuration is not None:
            options.extend(item.configuration.options)
            exclusions.extend(item.configuration.exclusions)
    for item in ordered:
        for interface in item.consumes:
            provider = providers.get(interface)
            if provider is None or provider not in (*item.dependencies, item.id):
                raise ValueError(
                    f"DomainManifest.{item.id}.consumes.{interface}: 缺少公开提供者或显式依赖 {provider}"
                )
    combined = ConfigurationSpec(tuple(options), tuple(exclusions))
    selected = combined.resolve(
        configuration or {},
        modules=frozenset(item.id for item in ordered),
        capabilities=profile.available,
    )
    return ValidatedModel(ordered, profile, selected)
