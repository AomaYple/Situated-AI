"""One resolved build configuration shared by profile generation and delivery.

These switches select generated scripts, not persistent game variables.  DLC
ownership is deliberately not inferred from locally installed DLC content.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from .core_contracts import ConfigurationOption, ConfigurationSpec

if TYPE_CHECKING:
    from pathlib import Path

DOMAINS = ("diplomacy", "economy", "politics")


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

    def identity(self) -> dict[str, object]:
        return {
            "core": self.core,
            "domains": sorted(self.domains),
            "enabled_domains": sorted(self.enabled_domains),
            "mode": self.mode,
        }


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
