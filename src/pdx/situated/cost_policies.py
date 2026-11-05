"""Explicit, bounded cost unknown policies applied before typed rule parsing."""

from __future__ import annotations

import copy
import hashlib
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SOURCE = Path(__file__).resolve().parents[3] / "mod/decisions/cost_policies.toml"


@dataclass(frozen=True, slots=True)
class CostAudit:
    rule_id: str
    source: str
    family: str
    mode: str
    pressure: tuple[str, ...]
    core: tuple[str, ...]
    basis: str
    unknown_anchor: tuple[str, ...] = ()
    limitation: str = ""


def digest() -> str:
    return hashlib.sha256(
        SOURCE.read_bytes() + b"\0generator:" + Path(__file__).read_bytes()
    ).hexdigest()


def _families() -> tuple[tuple[dict[str, Any], ...], tuple[str, ...], tuple[str, ...]]:
    data = tomllib.loads(SOURCE.read_text(encoding="utf-8"))
    if set(data) != {"schema", "families", "benefit_ids", "anchors"} or data["schema"] != 1:
        raise ValueError("成本策略schema无效")
    seen = set()
    for family in data["families"]:
        if set(family) != {"id", "groups", "ids", "pressure", "mode", "requires_core", "basis"}:
            raise ValueError("成本策略族字段不完整")
        if family["id"] in seen or family["mode"] not in {
            "conservative",
            "known_only",
            "withdrawal",
        }:
            raise ValueError("成本策略族重复或模式无效")
        seen.add(family["id"])
        if not family["basis"].strip() or type(family["requires_core"]) is not bool:
            raise ValueError("成本策略必须具有依据和明确实体锚")
        for key in ("groups", "ids", "pressure"):
            for pattern in family[key]:
                re.compile(pattern)
    return tuple(data["families"]), tuple(data["benefit_ids"]), tuple(data["anchors"])


def audit(data: dict[str, Any], *, source: str) -> tuple[CostAudit, ...]:
    """Classify every rule by declared semantics, never by numeric direction."""
    if source not in {"information", "adapters"}:
        raise ValueError("成本策略来源必须为information/adapters")
    families, benefits, anchors = _families()
    rows = []
    for rule in data["rules"]:
        if rule.get("semantic_role") == "benefit" or any(
            re.fullmatch(pattern, rule["id"]) for pattern in benefits
        ):
            rows.append(
                CostAudit(
                    rule["id"],
                    rule.get("source", source),
                    "observed_saving",
                    "benefit",
                    (),
                    (),
                    "已观察成本节约是收益，不把同组负成本政策传播到正向节约。",
                )
            )
            continue
        matches = [
            family
            for family in families
            if any(
                re.fullmatch(pattern, rule.get("contribution_group", ""))
                for pattern in family["groups"]
            )
            or (
                not rule.get("contribution_group")
                and any(re.fullmatch(pattern, rule["id"]) for pattern in family["ids"])
            )
        ]
        if len(matches) > 1:
            raise ValueError(f"成本策略语义族重叠：{rule['id']}")
        if not matches:
            rows.append(
                CostAudit(
                    rule["id"],
                    rule.get("source", source),
                    "unclassified",
                    "unchanged",
                    (),
                    (),
                    "未声明成本语义，不从数值方向推断。",
                )
            )
            continue
        family = matches[0]
        direct = {condition["fact"] for condition in rule["conditions"]}
        hard = set(rule.get("required_known_facts", [])) | set(rule.get("auxiliary_facts", []))
        for context in rule.get("contexts", []):
            hard.update(item["fact"] for item in data.get("contexts", {}).get(context, []))
        if rule.get("intent"):
            from pdx import decision_intents  # noqa: PLC0415

            hard.update(item["fact"] for item in decision_intents.load().expand(rule["intent"]))
        pressure = tuple(
            sorted(
                key
                for key in direct
                if key not in hard
                if any(re.fullmatch(pattern, key) for pattern in family["pressure"])
            )
        )
        core = set(direct) - set(pressure)
        core.update(rule.get("required_known_facts", []))
        mode = family["mode"]
        anchored = any(re.fullmatch(pattern, key) for key in core for pattern in anchors)
        unknown_anchor: tuple[str, ...] = ()
        limitation = ""
        if mode == "conservative" and not pressure:
            mode = "known_only"
            limitation = "hard_context_or_no_separable_pressure"
        elif mode == "conservative" and family["requires_core"] and not anchored:
            actor_source = rule.get("source", source)
            owner = actor_source.startswith(("common/buildings/", "common/mobilization_options/"))
            unknown_anchor = ("cost_owner_population" if owner else "cost_country_population",)
            mode = "conservative_anchor"
        elif mode == "known_only":
            limitation = "identity_relationship_or_observed_transition_must_be_known"
        rows.append(
            CostAudit(
                rule["id"],
                rule.get("source", source),
                family["id"],
                mode,
                pressure,
                tuple(sorted(core)),
                family["basis"],
                unknown_anchor,
                limitation,
            )
        )
    return tuple(rows)


def apply(data: dict[str, Any], *, source: str) -> dict[str, Any]:
    """Copy raw inputs, add justified declarations, retain all original predicates."""
    result = copy.deepcopy(data)
    for rule, row in zip(result["rules"], audit(data, source=source), strict=True):
        if row.mode not in {"conservative", "conservative_anchor"}:
            continue
        # The normal parser still rejects shared hard contexts, mixed relative
        # dependencies, identity readers and inconsistent semantic declarations.
        prior = rule.get("conservative_unknown_facts", [])
        if prior and (rule.get("semantic_role") != "cost" or set(prior) != set(row.pressure)):
            raise ValueError(f"成本策略与已有声明冲突：{row.rule_id}")
        rule["semantic_role"] = "cost"
        rule["conservative_unknown_facts"] = list(row.pressure)
        rule["unknown_cost_basis"] = row.basis
        if row.unknown_anchor:
            for key in row.unknown_anchor:
                reader = {
                    "engine": "total_population",
                    "scope": "root",
                    "unit": "persons",
                    "kind": "number",
                    "minimum": 0,
                }
                if key == "cost_owner_population":
                    reader["path"] = ["owner"]
                prior_reader = result["readers"].get(key)
                if prior_reader is not None and prior_reader != reader:
                    raise ValueError(f"未知成本专用实体锚Reader冲突：{key}")
                result["readers"][key] = reader
            rule["unknown_cost_required_known_facts"] = list(row.unknown_anchor)
    return result
