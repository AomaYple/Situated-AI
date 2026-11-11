"""One resolved build configuration shared by profile generation and delivery.

These switches select generated scripts, not persistent game variables.  DLC
ownership is deliberately not inferred from locally installed DLC content.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pdx import version_contracts

from .core_contracts import ConfigurationOption, ConfigurationSpec

if TYPE_CHECKING:
    from pathlib import Path

DOMAINS = ("diplomacy", "economy", "politics")
# Complete current production mapping; this does not claim the planned 25
# domains have acquired R2 depth. Cross-domain observations remain facts and
# cannot restore a disabled consumer writer.
LEGACY_DOMAINS = {
    "economy": frozenset({"fiscal", "economy", "market", "geography"}),
    "politics": frozenset({"political", "identity"}),
    "diplomacy": frozenset({"diplomacy", "subjects", "military"}),
}
EXTENSION_MODULES = {
    "economy": frozenset({"economy", "market"}),
    "politics": frozenset({"reform"}),
    "diplomacy": frozenset({"security", "diplomacy"}),
}


def _switch(name: str) -> ConfigurationOption:
    return ConfigurationOption(name, "boolean", True, (), None, None, (), (), (), False)


SPEC = ConfigurationSpec(tuple(_switch(name) for name in ("core", *DOMAINS)), ())


@dataclass(frozen=True, slots=True)
class ProfileConfiguration:
    """Validated effective selection; disabled core disables all domains."""

    core: bool = True
    domains: frozenset[str] = frozenset(DOMAINS)
    mode: Literal["policy", "neutral"] = "policy"

    def __post_init__(self) -> None:
        if type(self.core) is not bool or not isinstance(self.domains, frozenset):
            raise ValueError("profile configuration core/domains 类型无效")
        if not self.domains <= set(DOMAINS) or self.mode not in ("policy", "neutral"):
            raise ValueError("profile configuration 包含未知领域或模式")
        SPEC.resolve(
            {"core": self.core, **{name: name in self.domains for name in DOMAINS}},
            modules=frozenset(DOMAINS),
            capabilities=frozenset(),
        )

    @property
    def enabled_domains(self) -> frozenset[str]:
        return self.domains if self.core and self.mode == "policy" else frozenset()

    @property
    def legacy_domains(self) -> frozenset[str]:
        return frozenset().union(*(LEGACY_DOMAINS[name] for name in self.enabled_domains))

    @property
    def extension_modules(self) -> frozenset[str]:
        return frozenset().union(*(EXTENSION_MODULES[name] for name in self.enabled_domains))

    def identity(self) -> dict[str, object]:
        identity: dict[str, object] = {
            "core": self.core,
            "domains": sorted(self.domains),
            "enabled_domains": sorted(self.enabled_domains),
            "mode": self.mode,
        }
        if version_contracts.active_version() == "1.15.1":
            identity.update(
                legacy_domains=sorted(self.legacy_domains),
                extension_modules=sorted(self.extension_modules),
                domain_mapping={name: sorted(LEGACY_DOMAINS[name]) for name in DOMAINS},
                cross_domain_policy="observations do not re-enable disabled writers",
            )
        return identity


def validate_coverage(domains: frozenset[str], modules: frozenset[str]) -> None:
    mapped = frozenset().union(*LEGACY_DOMAINS.values())
    mapped_modules = frozenset().union(*EXTENSION_MODULES.values())
    if mapped != domains or mapped_modules != modules:
        raise ValueError(
            f"完整生产配置映射漂移：domains={sorted(domains ^ mapped)}, modules={sorted(modules ^ mapped_modules)}"
        )
    if sum(len(items) for items in LEGACY_DOMAINS.values()) != len(mapped):
        raise ValueError("完整生产域只能有一个配置 owner")


def load(path: Path | None = None) -> ProfileConfiguration:
    if path is None:
        return ProfileConfiguration()
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    if set(data) != {"schema", "core", "domains", "mode"} or type(data["schema"]) is not int:
        raise ValueError("profile configuration 字段不匹配")
    domains = data["domains"]
    if (
        data["schema"] != 1
        or not isinstance(domains, list)
        or any(not isinstance(name, str) for name in domains)
        or len(set(domains)) != len(domains)
    ):
        raise ValueError("profile configuration schema/domains 无效")
    return ProfileConfiguration(data["core"], frozenset(domains), data["mode"])
