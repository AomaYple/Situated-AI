"""Independent source identities for production coverage assertions.

Read only the two authored TOML files, never compiler models or generated bindings.
Information rules use their authored-file identity; adapters retain each explicit
native source. Duplicate source/rule keys must fail before set construction can
hide them, including duplicates that disagree on their field.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_INFORMATION_SOURCE = "mod/decisions/information.toml"


@dataclass(frozen=True)
class ProductionSources:
    rules: frozenset[tuple[str, str, str]]

    @property
    def consumers(self) -> frozenset[tuple[str, str]]:
        return frozenset((source, field) for source, _rule_id, field in self.rules)


def production_sources(
    information: Path = _ROOT / _INFORMATION_SOURCE,
    adapters: Path = _ROOT / "mod/decisions/adapters.toml",
) -> ProductionSources:
    """Return current authored identities, rejecting incomplete denominators."""
    identities: set[tuple[str, str, str]] = set()
    seen: set[tuple[str, str]] = set()
    for path, fixed_source in ((information, _INFORMATION_SOURCE), (adapters, None)):
        with path.open("rb") as stream:
            data = tomllib.load(stream)
        rows = data.get("rules")
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"{path}: rules must be a nonempty array")
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"{path}: rules[{index}] must be a table")
            values: dict[str, str] = {}
            for name in ("source", "id", "field"):
                value = (
                    fixed_source if name == "source" and fixed_source is not None else row.get(name)
                )
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{path}: rules[{index}].{name} must be a nonempty string")
                values[name] = value
            source, rule_id, field = (values[name] for name in ("source", "id", "field"))
            identity = (source, rule_id)
            if identity in seen:
                raise ValueError(f"{path}: duplicate source/rule identity {identity}")
            seen.add(identity)
            identities.add((source, rule_id, field))
    return ProductionSources(frozenset(identities))
