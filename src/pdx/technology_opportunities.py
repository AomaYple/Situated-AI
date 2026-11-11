"""Finite research opportunities derived from the locked native mechanisms.

Research changes a country's options and direct modifiers. It does not buy a
future building, production method, army or ship. The frozen mechanism catalog
is an offline input; production generation independently rebuilds it from the
supplied native sources. Candidate definitions never become runtime scopes.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from . import company_observations, config, version_contracts
from ._query_parse import parse_query_source
from .model import Assignment, Block, Scalar
from .parser import parse_text
from .textio import normalized_text

if TYPE_CHECKING:
    from pathlib import Path

PARAMETERS = config.REPO / "mod/decisions/technology_opportunities.toml"
PARAMETERS_115 = config.REPO / "mod/decisions/technology_opportunities_115.toml"


def parameter_path() -> Path:
    """Keep the migrated native catalog separate from the historical policy source."""
    return PARAMETERS_115 if version_contracts.active_version() == "1.15.0" else PARAMETERS


_FAMILIES = frozenset(
    {
        "technologies",
        "production_methods",
        "production_method_groups",
        "buildings",
        "building_groups",
        "goods",
        "combat_unit_types",
        "ship_types",
        "ship_modifications",
        "mobilization_options",
        "laws",
        "decrees",
    }
)
_NAME = re.compile(r"[a-z][a-z0-9_-]*\Z")


@cache
def _company():
    # Lazy import keeps observation query registration below decision_rules.
    return importlib.import_module("pdx.company_sectors")


def _family(source: str) -> str | None:
    path = PurePosixPath(source)
    if path.is_absolute() or ".." in path.parts or "\\" in source or ":" in source:
        raise ValueError("科技机制原件路径无效")
    if source.startswith("common/technology/technologies/") and path.suffix == ".txt":
        return "technologies"
    if len(path.parts) == 3 and path.parts[0] == "common" and path.suffix == ".txt":
        return path.parts[1] if path.parts[1] in _FAMILIES else None
    return None


def _child(block: Block, key: str) -> Block | None:
    # Share the company's strict unique-reference/list/recipe contracts. This
    # adapter only indexes additional native families; it is not a PDX parser.
    row = _company()._one(block, key)
    if row is None:
        return None
    if row.op != "=" or row.prefix is not None or not isinstance(row.value, Block):
        raise ValueError(f"科技机制字段必须是唯一普通块：{key}")
    return row.value


def _scalar(block: Block, key: str, default: str = "") -> str:
    row = _company()._one(block, key)
    if row is None:
        return default
    if row.op != "=" or row.prefix is not None or not isinstance(row.value, Scalar):
        raise ValueError(f"科技机制字段必须是唯一普通标量：{key}")
    return row.value.unquoted


def _numeric(block: Block | None) -> dict[str, float]:
    result: dict[str, float] = {}
    if block is None:
        return result
    for row in block.assignments():
        if (
            row.key in result
            or row.op != "="
            or row.prefix is not None
            or not isinstance(row.value, Scalar)
        ):
            raise ValueError("科技直接modifier必须为唯一数值常量")
        try:
            value = float(row.value.unquoted)
        except ValueError as exc:
            raise ValueError("科技直接modifier不能猜测变量值") from exc
        if not math.isfinite(value):
            raise ValueError("科技直接modifier必须有限")
        result[row.key] = value
    return dict(sorted(result.items()))


def _index(inputs: Mapping[str, str]) -> tuple[dict[str, Any], dict[str, str]]:
    indices: dict[str, Any] = {family: {} for family in _FAMILIES}
    sources = {}
    for source, text in sorted(inputs.items()):
        family = _family(source)
        if family is None:
            continue
        if not isinstance(text, str):
            raise ValueError("科技机制原件必须是文本")
        normalized = normalized_text(text)
        parsed = parse_text(normalized, path=source)
        if parsed.errors:
            raise ValueError(f"科技机制原件解析失败：{source}")
        sources[source] = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        for row in parsed.root.items:
            if not isinstance(row, Assignment):
                raise ValueError("科技机制顶层必须是定义")
            if row.is_variable:
                continue
            if (
                row.op != "="
                or row.prefix is not None
                or not isinstance(row.value, Block)
                or row.key in indices[family]
            ):
                raise ValueError(f"科技机制定义重复或不是普通块：{source}:{row.key}")
            indices[family][row.key] = (source, row)
    return indices, sources


def _basket(recipe: Mapping[str, Any], role: str) -> dict[str, float]:
    result: dict[str, float] = {}
    prefix = f"goods_{role}_"
    for row in recipe["modifiers"]:
        if row["key"].startswith(prefix) and row["key"].endswith("_add"):
            key = row["key"][len(prefix) : -4]
            result[key] = result.get(key, 0.0) + row["value"]
    return dict(sorted(result.items()))


def _services(definition: Block) -> dict[str, float]:
    result: dict[str, float] = {}

    def visit(block: Block) -> None:
        for row in block.assignments():
            if row.op != "=" or row.prefix is not None:
                raise ValueError("科技PM服务修饰器必须为普通赋值")
            if isinstance(row.value, Block):
                if row.key not in {
                    "workforce_scaled",
                    "level_scaled",
                    "throughput_scaled",
                    "unscaled",
                }:
                    raise ValueError("科技PM服务修饰器缩放不明")
                visit(row.value)
            elif isinstance(row.value, Scalar) and not row.key.startswith(
                ("goods_", "building_employment_")
            ):
                if row.key.endswith("_bool") and row.value.unquoted in {"yes", "no"}:
                    # Native flags (for example strait control) are not numeric
                    # service increments and never become research scores.
                    continue
                try:
                    value = float(row.value.unquoted)
                except ValueError as exc:
                    raise ValueError("科技PM服务修饰器不能猜测变量值") from exc
                if not math.isfinite(value):
                    raise ValueError("科技PM服务修饰器必须有限")
                result[row.key] = result.get(row.key, 0.0) + value

    for key in ("building_modifiers", "country_modifiers", "state_modifiers"):
        block = _child(definition, key)
        if block is not None:
            visit(block)
    return dict(sorted(result.items()))


def inventory(inputs: Mapping[str, str], consumers: Mapping[str, str]) -> dict[str, Any]:
    """Derive exact mechanisms from supplied native ASTs, without runtime I/O.

    A production opportunity is one new method versus one earlier method in
    the same actual building/PMG. Output and employment differences are computed
    from those two recipes, never inferred from the technology's name.
    """
    indices, sources = _index(inputs)
    technologies: dict[str, Any] = {}
    all_technologies = {}
    for identity, (source, definition) in sorted(indices["technologies"].items()):
        all_technologies[identity] = list(
            _company()._list(definition.value, "unlocking_technologies")
        )
        if identity not in consumers:
            continue
        if consumers[identity] != source or _child(definition.value, "ai_weight") is None:
            raise ValueError("科技消费者没有匹配的真实ai_weight定义")
        modifier_blocks = []
        for modifier in definition.value.all("modifier"):
            if (
                modifier.op != "="
                or modifier.prefix is not None
                or not isinstance(modifier.value, Block)
            ):
                raise ValueError("科技modifier容器必须是普通块")
            modifier_blocks.append(_numeric(modifier.value))
        technologies[identity] = {
            "source": source,
            "line": definition.line,
            "era": _scalar(definition.value, "era"),
            "category": _scalar(definition.value, "category"),
            "prerequisites": all_technologies[identity],
            "modifier": modifier_blocks[0] if len(modifier_blocks) == 1 else {},
            "modifier_blocks": modifier_blocks,
            "opportunities": [],
            "military": [],
            "unlocks": [],
        }
    if set(consumers) != set(technologies):
        raise ValueError("科技消费者缺少引用或原版定义")

    def closure(identity: str, seen: frozenset[str] = frozenset()) -> frozenset[str]:
        if identity in seen or identity not in all_technologies:
            raise ValueError("科技前置引用缺失或循环")
        result = {identity}
        for parent in all_technologies[identity]:
            result.update(closure(parent, seen | {identity}))
        return frozenset(result)

    recipes = {
        identity: _company()._recipe(indices, identity)
        for identity in sorted(indices["production_methods"])
    }
    methods = {}
    for identity, recipe in recipes.items():
        definition = indices["production_methods"][identity][1]
        methods[identity] = {
            "source": recipe["source"],
            "line": recipe["line"],
            "technologies": list(_company()._list(definition.value, "unlocking_technologies")),
            "outputs": _basket(recipe, "output"),
            "inputs": _basket(recipe, "input"),
            "employment": sum(
                row["value"]
                for row in recipe["modifiers"]
                if row["key"].startswith("building_employment_")
            ),
            "services": _services(definition.value),
            "law_gates": {
                key: list(_company()._list(definition.value, key))
                for key in ("unlocking_laws", "disallowing_laws")
            },
            "special_gates": [
                key
                for key in ("unlocking_laws", "disallowing_laws", "unlocking_principles")
                if definition.value.all(key)
            ],
        }
    groups = {}
    for identity, (source, definition) in sorted(indices["production_method_groups"].items()):
        selected = _company()._list(definition.value, "production_methods", required=True)
        for method in selected:
            _company()._reference(indices, "production_methods", method)
        groups[identity] = {"source": source, "line": definition.line, "methods": list(selected)}
    buildings = {}

    def group_flag(identity: str, key: str, seen: frozenset[str] = frozenset()) -> bool:
        if not identity:
            return False
        if identity in seen or identity not in indices["building_groups"]:
            raise ValueError("科技建筑组父链缺失或循环")
        block = indices["building_groups"][identity][1].value
        return _scalar(block, key) == "yes" or group_flag(
            _scalar(block, "parent_group"), key, seen | {identity}
        )

    for building, (source, definition) in sorted(indices["buildings"].items()):
        group_ids = _company()._list(definition.value, "production_method_groups")
        prerequisites = list(_company()._list(definition.value, "unlocking_technologies"))
        buildings[building] = {
            "source": source,
            "line": definition.line,
            "groups": list(group_ids),
            "technologies": prerequisites,
            "group": _scalar(definition.value, "building_group"),
            "scale": (
                group_flag(_scalar(definition.value, "building_group"), "economy_of_scale")
                and not group_flag(_scalar(definition.value, "building_group"), "is_subsistence")
            )
            if indices["building_groups"]
            else False,
            "common_outputs": [],
        }
        common_outputs = set()
        for group_id in group_ids:
            if group_id not in groups:
                raise ValueError(f"科技机制缺少引用：PMG:{group_id}")
            order = groups[group_id]["methods"]
            if all(
                any(amount > 0 for amount in methods[method]["outputs"].values())
                for method in order
            ):
                shared = {
                    good for good, amount in methods[order[0]]["outputs"].items() if amount > 0
                }
                for method in order[1:]:
                    shared.intersection_update(
                        good for good, amount in methods[method]["outputs"].items() if amount > 0
                    )
                common_outputs.update(shared)
            for index, method in enumerate(order):
                candidate = methods[method]
                for technology in set(candidate["technologies"]) & technologies.keys():
                    for prior in order[:index] or [""]:
                        previous: dict[str, Any] = (
                            methods[prior]
                            if prior
                            else {
                                "technologies": [],
                                "outputs": {},
                                "inputs": {},
                                "employment": 0,
                                "services": {},
                            }
                        )
                        if technology in previous["technologies"]:
                            continue
                        outputs = {
                            good: amount - previous["outputs"].get(good, 0)
                            for good, amount in candidate["outputs"].items()
                            if amount > previous["outputs"].get(good, 0)
                        }
                        losses = {
                            good: amount - candidate["outputs"].get(good, 0)
                            for good, amount in previous["outputs"].items()
                            if amount > candidate["outputs"].get(good, 0)
                        }
                        inputs_delta = {
                            good: amount - previous["inputs"].get(good, 0)
                            for good, amount in candidate["inputs"].items()
                            if amount > previous["inputs"].get(good, 0)
                        }
                        technologies[technology]["opportunities"].append(
                            {
                                "kind": "method",
                                "building": building,
                                "group": group_id,
                                "method": method,
                                "prior": prior,
                                "outputs": dict(sorted(outputs.items())),
                                "losses": dict(sorted(losses.items())),
                                "inputs": dict(sorted(inputs_delta.items())),
                                "services": {
                                    key: value - previous["services"].get(key, 0)
                                    for key, value in candidate["services"].items()
                                    if value != previous["services"].get(key, 0)
                                },
                                "labor_saved": max(
                                    0, previous["employment"] - candidate["employment"]
                                ),
                                "requirements": sorted(
                                    (set(candidate["technologies"]) | set(prerequisites))
                                    - closure(technology)
                                ),
                                "special_gates": candidate["special_gates"],
                            }
                        )
            for technology in set(prerequisites) & technologies.keys():
                # Only methods already enabled by the candidate's actual
                # prerequisite closure count as a new-building base option.
                for method in order:
                    candidate = methods[method]
                    if (
                        set(candidate["technologies"]) <= closure(technology)
                        and not candidate["special_gates"]
                    ):
                        technologies[technology]["opportunities"].append(
                            {
                                "kind": "building",
                                "building": building,
                                "group": group_id,
                                "method": method,
                                "prior": "",
                                "outputs": candidate["outputs"],
                                "losses": {},
                                "inputs": candidate["inputs"],
                                "labor_saved": 0,
                                "services": candidate["services"],
                                "requirements": sorted(set(prerequisites) - closure(technology)),
                                "special_gates": [],
                            }
                        )
                        break
        buildings[building]["common_outputs"] = sorted(common_outputs)
    goods = {
        identity: {
            "source": source,
            "line": definition.line,
            "market": _company()._market_reason(indices, identity) is None,
            "local": _scalar(definition.value, "local") == "yes",
        }
        for identity, (source, definition) in sorted(indices["goods"].items())
    }
    objects = {}
    for family in (
        "combat_unit_types",
        "ship_types",
        "ship_modifications",
        "mobilization_options",
        "laws",
        "decrees",
    ):
        for identity, (source, definition) in sorted(indices[family].items()):
            prerequisites = _company()._list(definition.value, "unlocking_technologies")
            relevant = set(prerequisites) & technologies.keys()
            if not relevant:
                continue
            row = {
                "id": identity,
                "family": family,
                "source": source,
                "line": definition.line,
                "technologies": list(prerequisites),
            }
            if family in {
                "combat_unit_types",
                "ship_types",
                "ship_modifications",
                "mobilization_options",
            }:
                goods_paid = {}
                for key in ("upkeep_modifier", "construction_goods", "materiel_goods"):
                    basket = _numeric(_child(definition.value, key))
                    goods_paid.update(
                        {
                            name.removeprefix("goods_input_").removesuffix("_add"): amount
                            for name, amount in basket.items()
                            if name.startswith("goods_input_") and amount > 0
                        }
                    )
                row["goods"] = dict(sorted(goods_paid.items()))
                row["branch"] = (
                    "army" if family in {"combat_unit_types", "mobilization_options"} else "navy"
                )
                for technology in relevant:
                    technologies[technology]["military"].append(row)
            for technology in relevant:
                technologies[technology]["unlocks"].append(identity)
            objects[identity] = row
    return {
        "schema": 1,
        "sources": sources,
        "technologies": technologies,
        "goods": goods,
        "buildings": buildings,
        "groups": groups,
        "methods": methods,
        "native_objects": objects,
    }


def _parameters(values: Mapping[str, object]) -> dict[str, float]:
    expected = {
        "priority_base",
        "borrowing_base",
        "borrowing_pressure",
        "debt_threshold",
        "literacy_multiplier",
        "literacy_threshold",
        "tax_capacity_multiplier",
        "company_base",
        "company_pressure",
        "market_base",
        "market_pressure",
        "supply_base",
        "supply_pressure",
        "supply_active",
        "supply_ready",
        "price_threshold",
        "labor_base",
        "labor_ready",
        "option_base",
        "option_pressure",
        "military_base",
        "military_pressure",
    }
    if set(values) != expected:
        raise ValueError("科技机会参数必须为完整有限数字映射")
    result: dict[str, float] = {}
    for key, value in values.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("科技机会参数必须为完整有限数字映射")
        result[key] = float(value)
    if not result["priority_base"].is_integer() or not 100000 <= result["priority_base"] <= 1000000:
        raise ValueError("科技机会优先级必须为独立高段整数")
    if any(
        not 1 < value <= 1.5
        for key, value in result.items()
        if key not in {"priority_base", "debt_threshold", "literacy_threshold", "price_threshold"}
    ):
        raise ValueError("科技需求倍率必须在(1,1.5]内")
    if not 0 < result["debt_threshold"] < 1 or not 0 < result["literacy_threshold"] < 1:
        raise ValueError("科技机会比例阈值必须在(0,1)内")
    if not 0 < result["price_threshold"] <= 0.75:
        raise ValueError("科技商品高价阈值必须在(0,.75]内")
    for low, high in (
        ("borrowing_base", "borrowing_pressure"),
        ("company_base", "company_pressure"),
        ("market_base", "market_pressure"),
    ):
        if result[low] >= result[high]:
            raise ValueError("科技机会升档必须比基础档强")
    return result


def load_parameters(path: Path = PARAMETERS) -> dict[str, float]:
    data = tomllib.loads(
        (parameter_path() if path == PARAMETERS else path).read_text(encoding="utf-8")
    )
    if set(data) != {"schema", "parameters", "catalog_json"} or data["schema"] != 1:
        raise ValueError("科技机会配置schema无效")
    return _parameters(data["parameters"])


def load_catalog(path: Path = PARAMETERS) -> dict[str, Any]:
    data = tomllib.loads(
        (parameter_path() if path == PARAMETERS else path).read_text(encoding="utf-8")
    )
    if set(data) != {"schema", "parameters", "catalog_json"} or data["schema"] != 1:
        raise ValueError("科技机会配置schema无效")
    catalog = json.loads(data["catalog_json"])
    if not isinstance(catalog, dict):
        raise ValueError("科技机制目录必须为映射")
    _validate_catalog(catalog)
    return catalog


def _validate_catalog(catalog: Mapping[str, Any]) -> None:
    """Reject malformed offline data before any reader or rule is derived.

    Source byte identity and complete native semantics are additionally rebuilt
    by verify_inputs; these checks protect offline generation and query setup.
    """
    tables = {"technologies", "goods", "buildings", "groups", "methods", "native_objects"}
    if (
        set(catalog) - {"native_retained"} != tables | {"schema", "sources", "legacy_rules"}
        or type(catalog["schema"]) is not int
        or catalog["schema"] != 1
    ):
        raise ValueError("科技机制目录schema无效")
    sources = catalog["sources"]
    if not isinstance(sources, dict) or not sources:
        raise ValueError("科技机制目录来源必须为非空映射")
    for source, digest in sources.items():
        if (
            not isinstance(source, str)
            or _family(source) is None
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise ValueError("科技机制目录来源身份无效")
    retained = catalog.get("native_retained", {})
    if (
        not isinstance(retained, dict)
        or set(retained) & set(catalog["technologies"])
        or any(
            not isinstance(identity, str)
            or not _NAME.fullmatch(identity)
            or not isinstance(source, str)
            or source not in sources
            or _family(source) != "technologies"
            for identity, source in retained.items()
        )
    ):
        raise ValueError("科技机制原版保留候选身份无效")

    def identifiers(value: Any) -> bool:
        return (
            isinstance(value, list)
            and all(isinstance(item, str) and _NAME.fullmatch(item) for item in value)
            and len(set(value)) == len(value)
        )

    def numeric(value: Any) -> bool:
        return isinstance(value, dict) and all(
            isinstance(key, str)
            and _NAME.fullmatch(key)
            and type(number) in (int, float)
            and math.isfinite(number)
            for key, number in value.items()
        )

    required = {
        "technologies": {
            "source",
            "line",
            "era",
            "category",
            "prerequisites",
            "modifier",
            "modifier_blocks",
            "opportunities",
            "military",
            "unlocks",
        },
        "goods": {"source", "line", "market", "local"},
        "buildings": {
            "source",
            "line",
            "groups",
            "technologies",
            "group",
            "scale",
            "common_outputs",
        },
        "groups": {"source", "line", "methods"},
        "methods": {
            "source",
            "line",
            "technologies",
            "outputs",
            "inputs",
            "employment",
            "services",
            "special_gates",
            "law_gates",
        },
    }
    for table in tables:
        rows = catalog[table]
        if not isinstance(rows, dict):
            raise ValueError("科技机制目录对象表必须为映射")
        for identity, row in rows.items():
            if (
                not isinstance(identity, str)
                or not _NAME.fullmatch(identity)
                or not isinstance(row, dict)
            ):
                raise ValueError("科技机制目录对象身份无效")
            if table in required and set(row) != required[table]:
                raise ValueError("科技机制目录对象字段无效")
            if (
                row.get("source") not in sources
                or type(row.get("line")) is not int
                or row["line"] < 1
            ):
                raise ValueError("科技机制目录对象来源无效")
            for key in ("outputs", "inputs", "services", "modifier", "goods"):
                if key in row and not numeric(row[key]):
                    raise ValueError("科技机制目录数值必须为有限映射")
            for key in (
                "technologies",
                "prerequisites",
                "groups",
                "methods",
                "special_gates",
                "unlocks",
                "common_outputs",
            ):
                if key in row and not identifiers(row[key]):
                    raise ValueError("科技机制目录引用列表无效")
            if table == "methods":
                if type(row["employment"]) not in (int, float) or not math.isfinite(
                    row["employment"]
                ):
                    raise ValueError("科技机制目录雇员数无效")
                if set(row["law_gates"]) != {"unlocking_laws", "disallowing_laws"} or not all(
                    identifiers(x) for x in row["law_gates"].values()
                ):
                    raise ValueError("科技机制目录法律条件无效")
            if table == "goods" and any(type(row[k]) is not bool for k in ("market", "local")):
                raise ValueError("科技机制目录商品分类无效")
    for group in catalog["groups"].values():
        if not set(group["methods"]) <= catalog["methods"].keys():
            raise ValueError("科技机制目录PMG缺少真实PM成员")
    for building in catalog["buildings"].values():
        if (
            not set(building["groups"]) <= catalog["groups"].keys()
            or not set(building["common_outputs"]) <= catalog["goods"].keys()
            or type(building["scale"]) is not bool
        ):
            raise ValueError("科技机制目录建筑引用无效")
    for method in catalog["methods"].values():
        if not (method["outputs"].keys() | method["inputs"].keys()) <= catalog["goods"].keys():
            raise ValueError("科技机制目录PM引用未知商品")
    opportunity_fields = {
        "kind",
        "building",
        "group",
        "method",
        "prior",
        "outputs",
        "losses",
        "inputs",
        "services",
        "labor_saved",
        "requirements",
        "special_gates",
    }
    for technology in catalog["technologies"].values():
        if not isinstance(technology["modifier_blocks"], list) or not all(
            numeric(block) for block in technology["modifier_blocks"]
        ):
            raise ValueError("科技机制目录modifier块无效")
        if not isinstance(technology["opportunities"], list):
            raise ValueError("科技机制目录机会必须为列表")
        for row in technology["opportunities"]:
            if (
                not isinstance(row, dict)
                or set(row) != opportunity_fields
                or row["kind"] not in {"method", "building"}
            ):
                raise ValueError("科技机制目录机会字段无效")
            building = catalog["buildings"].get(row["building"])
            if (
                building is None
                or row["group"] not in building["groups"]
                or row["method"] not in catalog["groups"][row["group"]]["methods"]
                or (row["prior"] and row["prior"] not in catalog["groups"][row["group"]]["methods"])
            ):
                raise ValueError("科技机制目录机会不属于真实建筑PMG")
            if not all(
                numeric(row[k]) for k in ("outputs", "losses", "inputs", "services")
            ) or not all(identifiers(row[k]) for k in ("requirements", "special_gates")):
                raise ValueError("科技机制目录机会数值或条件无效")
            if (
                not (row["outputs"].keys() | row["losses"].keys() | row["inputs"].keys())
                <= catalog["goods"].keys()
                or type(row["labor_saved"]) not in (int, float)
                or not math.isfinite(row["labor_saved"])
                or row["labor_saved"] < 0
            ):
                raise ValueError("科技机制目录机会商品或省工数无效")
    legacy = catalog["legacy_rules"]
    if not isinstance(legacy, list) or any(
        not isinstance(row, dict) or set(row) != {"id", "source", "field"} for row in legacy
    ):
        raise ValueError("科技机制目录旧规则清单无效")
    identities = set()
    for row in legacy:
        if (
            row["id"] in identities
            or row["source"] not in sources
            or row["field"] not in {f"{key}.ai_weight" for key in catalog["technologies"]}
        ):
            raise ValueError("科技机制目录旧规则身份重复或引用漂移")
        identities.add(row["id"])


with version_contracts.select_version("1.14.5"):
    _QUERY_CATALOG = load_catalog()
with version_contracts.select_version("1.15.0"):
    _QUERY_CATALOG_115 = load_catalog()


def _query_catalog() -> dict[str, Any]:
    return _QUERY_CATALOG_115 if version_contracts.active_version() == "1.15.0" else _QUERY_CATALOG


_ART = "common/journal_entries/00_art_jes.txt"
_CULTURE = "common/script_values/cultural_community_values.txt"
_SLAVE = "common/political_movements/05_slave_revolt_movements.txt"
_COMPANY = "common/company_types/00_companies_soi.txt"
_OPIUM = "common/journal_entries/00_opium.txt"
QUERY_SOURCE_HASHES = {
    _ART: "e0e281573697439d31145c5bdbebb0298ce753acb54be894f9ce6c4f8fc230c5",
    _CULTURE: "1aaedb1f2760af4e991dc587416d1c3c68f7dc2beea5f825319e6cb660491402",
    _SLAVE: "14ea7992d4905c694faf204c644f71ae96bcc5be757a57e3d9cf4a7bab2b2303",
    _COMPANY: "59546f6105092bad8935498d917a6012aa508c58bea873e462dd66a5850f2f1d",
    _OPIUM: "c8e51f799ffe192b1789c91ab6d0772d9dd028b5610529907e6a1a7760509dc8",
}
QUERY_SOURCE_HASHES_115 = {
    "common/journal_entries/00_art_jes.txt": "300104c4016f3a6037fa38b81e0ee3d52363fd47615a4344d1691bc4938fbd8f",
    "common/script_values/cultural_community_values.txt": "ba52c106fcba3189c069efcc5af89a3880ff00439f9c5f51a159bdda5278ec30",
    "common/political_movements/05_slave_revolt_movements.txt": "8ce8f69cdf1ca623ed84e475f1721e9c7945998a687a1f099da0c70f44431968",
    "common/company_types/00_companies_soi.txt": "5d96e85f5fb786240b201e98d900d9a1e88fff9287389a4a12886e874130f46f",
    "common/journal_entries/00_opium.txt": "4c78209754e956f3823fea1f8595e81508fc887e5b6b9b223119411a783ceaa1",
}


def query_source_hashes() -> dict[str, str]:
    return (
        QUERY_SOURCE_HASHES_115
        if version_contracts.active_version() == "1.15.0"
        else QUERY_SOURCE_HASHES
    )


UNKNOWN_POLICY = company_observations.UNKNOWN_POLICY
_PURPOSES = frozenset(
    {
        "productive",
        "productive_ready",
        "labor",
        "labor_ready",
        "administration",
        "knowledge",
        "knowledge_ready",
        "infrastructure",
        "local_supply",
        "throughput",
        "trade",
        "construction",
        "resource",
        "infrastructure_direct",
        "scale",
    }
)


@dataclass(frozen=True, slots=True)
class TechnologyBuildingQuery:
    building_id: str
    method_id: str | None = None
    labor_tight: bool = False


@dataclass(frozen=True, slots=True)
class TechnologyUseQuery:
    technology: str
    purpose: str


TechnologyQuery = TechnologyBuildingQuery | TechnologyUseQuery


@dataclass(frozen=True, slots=True)
class CompiledTechnologyQuery:
    expression: str
    references: tuple[str, ...]
    source_hashes: tuple[tuple[str, str], ...]
    local_collections: tuple[str, ...]
    scope_chain: tuple[str, ...]
    actor: str = "country"
    kind: str = "boolean"
    unknown_policy: str = UNKNOWN_POLICY
    world_scans: int = 0
    runtime_cost: str = "finite existential traversal of owned candidates; not constant time"


def query_from_reader(engine: str, parameters: Mapping[str, str]) -> TechnologyQuery:
    if not isinstance(parameters, Mapping) or any(
        type(k) is not str or type(v) is not str for k, v in parameters.items()
    ):
        raise ValueError("科技查询必须使用完整字符串参数映射")
    tag = parameters.get("technology_query")
    query: TechnologyQuery
    if (
        tag == "existing_building"
        and engine == "any_scope_building"
        and set(parameters) == {"technology_query", "building"}
    ):
        query = TechnologyBuildingQuery(parameters["building"])
    elif (
        tag in {"existing_method", "labor_saving"}
        and engine == ("any_scope_state" if tag == "labor_saving" else "any_scope_building")
        and set(parameters) == {"technology_query", "building", "method"}
    ):
        query = TechnologyBuildingQuery(
            parameters["building"], parameters["method"], tag == "labor_saving"
        )
    elif (
        tag == "technology_use"
        and set(parameters) == {"technology_query", "technology", "purpose"}
        and engine
        == (
            "any_scope_state"
            if parameters["purpose"]
            in {
                "labor",
                "labor_ready",
                "infrastructure",
                "local_supply",
                "resource",
                "infrastructure_direct",
            }
            else "any_scope_building"
        )
    ):
        query = TechnologyUseQuery(parameters["technology"], parameters["purpose"])
    else:
        raise ValueError("科技查询参数形状或引擎未登记")
    render_query(query)
    return query


def _valid_building(building: str, method: str | None = None) -> None:
    if not isinstance(building, str) or building not in _query_catalog()["buildings"]:
        raise ValueError("科技查询建筑ID未登记")
    if method is not None and (
        not isinstance(method, str)
        or not any(
            method in _query_catalog()["groups"][group]["methods"]
            for group in _query_catalog()["buildings"][building]["groups"]
        )
    ):
        raise ValueError("科技查询PM不属于真实建筑PM组")


def query_members(
    query: TechnologyUseQuery, catalog: Mapping[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Expose the finite catalog members for external independent witnesses.

    Each member has kind/building/group/method/prior, positive output deltas,
    displaced output deltas, added input deltas, employment saved, services and
    extra technology requirements. External oracles must interpret those data
    independently, rather than treating this function as a truth evaluator.
    """
    frozen = _query_catalog() if catalog is None else catalog
    if query.technology not in frozen["technologies"] or query.purpose not in _PURPOSES:
        raise ValueError("科技或用途不在有限冻结目录内")
    profile = frozen["technologies"][query.technology]
    rows = []
    for row in profile["opportunities"]:
        services = row.get("services", {})
        if "unlocking_principles" in row["special_gates"]:
            continue
        take = False
        if query.purpose.startswith("productive"):
            take = row["kind"] == "method" and any(
                frozen["goods"][good]["market"] for good in row["outputs"]
            )
        elif query.purpose.startswith("labor"):
            take = row["labor_saved"] > 0 and bool(row["prior"])
        elif query.purpose == "administration":
            take = row["kind"] == "method" and services.get("country_bureaucracy_add", 0) > 0
        elif query.purpose in {"knowledge", "knowledge_ready"}:
            take = row["kind"] == "method" and services.get("country_weekly_innovation_add", 0) > 0
            if query.purpose == "knowledge_ready":
                take = (
                    take
                    and row["building"] == "building_university"
                    and bool(row["prior"])
                    and row["inputs"].get("paper", 0) > 0
                )
        elif query.purpose == "infrastructure":
            take = services.get("state_infrastructure_add", 0) > 0
        elif query.purpose == "local_supply":
            take = any(frozen["goods"][good]["local"] for good in row["outputs"])
        elif query.purpose == "trade":
            take = (
                row.get("services", {}).get("state_trade_quantity_mult", 0) > 0
                and row["kind"] == "method"
            )
        elif query.purpose == "resource":
            take = (
                row["kind"] == "building"
                and row.get("services", {}).get("country_minting_add", 0) > 0
            )
        if take:
            rows.append(row)
    if query.purpose == "throughput":
        for key, value in profile["modifier"].items():
            if not key.startswith("building_") or not key.endswith("_throughput_add") or value <= 0:
                continue
            building = key.removesuffix("_throughput_add")
            if building not in frozen["buildings"]:
                continue
            outputs = {}
            for group in frozen["buildings"][building]["groups"]:
                for method in frozen["groups"][group]["methods"]:
                    outputs.update(
                        {
                            good: amount
                            for good, amount in frozen["methods"][method]["outputs"].items()
                            if amount > 0 and frozen["goods"][good]["market"]
                        }
                    )
            if outputs:
                rows.append(
                    {
                        "kind": "throughput",
                        "building": building,
                        "group": "",
                        "method": "",
                        "prior": "",
                        "outputs": outputs,
                        "losses": {},
                        "inputs": {},
                        "services": {},
                        "labor_saved": 0,
                        "requirements": [],
                        "special_gates": [],
                    }
                )
    if query.purpose == "construction" and (
        profile["modifier"].get("building_construction_sector_throughput_add", 0) > 0
        or profile["modifier"].get("country_max_weekly_construction_progress_add", 0) > 0
    ):
        rows.append(
            {
                "kind": "construction",
                "building": "building_construction_sector",
                "group": "",
                "method": "",
                "prior": "",
                "outputs": {},
                "losses": {},
                "inputs": {},
                "services": {},
                "labor_saved": 0,
                "requirements": [],
                "special_gates": [],
            }
        )
    if (
        query.purpose == "scale"
        and profile["modifier"].get("building_economy_of_scale_level_cap_add", 0) > 0
    ):
        for building, definition in frozen["buildings"].items():
            outputs = {
                good: 1.0
                for good in definition.get("common_outputs", [])
                if frozen["goods"][good]["market"]
            }
            if definition.get("scale") and outputs:
                rows.append(
                    {
                        "kind": "scale",
                        "building": building,
                        "group": "",
                        "method": "",
                        "prior": "",
                        "outputs": outputs,
                        "losses": {},
                        "inputs": {},
                        "services": {},
                        "labor_saved": 0,
                        "requirements": [],
                        "special_gates": [],
                    }
                )
    if query.purpose == "infrastructure_direct" and any(
        profile["modifier"].get(key, 0) > 0
        for key in (
            "state_infrastructure_add",
            "state_infrastructure_from_population_add",
            "state_infrastructure_from_population_max_add",
        )
    ):
        rows.append(
            {
                "kind": "infrastructure_direct",
                "building": "",
                "group": "",
                "method": "",
                "prior": "",
                "outputs": {},
                "losses": {},
                "inputs": {},
                "services": {},
                "labor_saved": 0,
                "requirements": [],
                "special_gates": [],
            }
        )
    # Identical physical opportunity branches occur for shared PM groups and
    # different candidate methods. One observed fact is evaluated only once.
    unique = {json.dumps(row, sort_keys=True): row for row in rows}
    return [unique[key] for key in sorted(unique)]


def _owned_building(building: str, prior: str = "", *, occupied: bool = False) -> str:
    _valid_building(building, prior or None)
    method = f" has_active_production_method = {prior}" if prior else ""
    occupancy = " occupancy >= 0.9" if occupied else ""
    return f"any_scope_building = {{ is_building_type = {building}{method}{occupancy} level >= 1 }}"


def _or(expressions: list[str]) -> str:
    unique = sorted(set(expressions))
    if not unique:
        raise ValueError("科技查询没有真实机制成员")
    return unique[0] if len(unique) == 1 else "OR = { " + " ".join(unique) + " }"


def _law_and_technology_gates(row: Mapping[str, Any]) -> str:
    clauses = [f"has_technology_researched = {key}" for key in row["requirements"]]
    if row["method"]:
        method = _query_catalog()["methods"][row["method"]]
        gates = method.get("law_gates", {})
        required = gates.get("unlocking_laws", [])
        if required:
            clauses.append(_or([f"has_law_or_variant = law_type:{law}" for law in required]))
        clauses.extend(
            f"NOT = {{ has_law_or_variant = law_type:{law} }}"
            for law in gates.get("disallowing_laws", [])
        )
    return " ".join(clauses)


def render_query(query: TechnologyQuery) -> str:
    """Render fixed frozen templates without filesystem or game access."""
    if type(query) is TechnologyBuildingQuery:
        if type(query.labor_tight) is not bool or (query.labor_tight and not query.method_id):
            raise ValueError("省工查询必须绑定真实低级PM")
        building = _owned_building(
            query.building_id, query.method_id or "", occupied=query.labor_tight
        )
        if not query.labor_tight:
            return building
        return (
            "any_scope_state = { state_unemployment_rate < 0.02 "
            "pop_type_percent_state = { target = pop_type:peasants value < 0.02 } "
            + building
            + " }"
        )
    if type(query) is not TechnologyUseQuery:
        raise ValueError("科技查询类型未登记")
    expressions = []
    purpose = query.purpose
    if purpose in {"labor", "labor_ready", "productive", "productive_ready"}:
        labor = purpose.startswith("labor")
        for row in query_members(query):
            clauses = [f"is_building_type = {row['building']}"]
            if row["prior"]:
                clauses.append(f"has_active_production_method = {row['prior']}")
            country = [_law_and_technology_gates(row)]
            if not labor:
                country.append(
                    _or(
                        [
                            f"market = {{ mg:{good} = {{ market_goods_delta < 0 }} }}"
                            for good in row["outputs"]
                            if _query_catalog()["goods"][good]["market"]
                        ]
                    )
                )
            if purpose.endswith("_ready"):
                usable = True
                # The prepared-use tier also preserves outputs displaced by
                # this exact recipe; researching pays no future adoption bill.
                for good, amount in (row["inputs"] | row["losses"]).items():
                    if amount <= 0:
                        continue
                    if not _query_catalog()["goods"][good]["market"]:
                        usable = False
                        break
                    country.append(f"market = {{ mg:{good} = {{ market_goods_delta >= 0 }} }}")
                if not usable:
                    continue
            country = [condition for condition in country if condition]
            if country:
                clauses.append("ROOT = { " + " ".join(country) + " }")
            expressions.append("AND = { " + " ".join(clauses) + " }")
        building = (
            "any_scope_building = { level >= 1 "
            + ("occupancy >= 0.9 " if labor else "")
            + _or(expressions)
            + " }"
        )
        if labor:
            return (
                "any_scope_state = { state_unemployment_rate < 0.02 "
                "pop_type_percent_state = { target = pop_type:peasants value < 0.02 } "
                + building
                + " }"
            )
        return building
    if purpose == "scale":
        by_good: dict[str, list[str]] = {}
        for row in query_members(query):
            for good in row["outputs"]:
                by_good.setdefault(good, []).append(f"is_building_type = {row['building']}")
        alternatives = [
            "AND = { "
            + _or(types)
            + f" ROOT = {{ market = {{ mg:{good} = {{ market_goods_delta < 0 }} }} }} }}"
            for good, types in sorted(by_good.items())
        ]
        return "any_scope_building = { level >= 20 occupancy >= 0.75 " + _or(alternatives) + " }"
    for row in query_members(query):
        clauses = []
        gates = _law_and_technology_gates(row)
        building = (
            _owned_building(row["building"], row["prior"], occupied=purpose.startswith("labor"))
            if row["building"]
            else ""
        )
        if purpose.startswith("productive") or purpose == "throughput":
            clauses.append(
                _or(
                    [
                        f"market = {{ mg:{good} = {{ market_goods_delta < 0 }} }}"
                        for good in row["outputs"]
                        if _query_catalog()["goods"][good]["market"]
                    ]
                )
            )
            clauses.append(building)
        elif purpose.startswith("labor"):
            clauses.extend(
                [
                    "state_unemployment_rate < 0.02",
                    "pop_type_percent_state = { target = pop_type:peasants value < 0.02 }",
                    building,
                ]
            )
        elif purpose == "infrastructure":
            clauses.append("infrastructure_delta < 0")
            if row["kind"] == "method":
                clauses.append(building)
        elif purpose == "local_supply":
            clauses.append(
                _or(
                    [
                        f"sg:{good} = {{ state_goods_pricier > 0.25 }}"
                        for good in row["outputs"]
                        if _query_catalog()["goods"][good]["local"]
                    ]
                )
            )
            if row["kind"] == "method":
                clauses.append(building)
        elif purpose == "trade":
            clauses.append(building.removesuffix(" }") + " occupancy >= 0.75 weekly_profit > 0 }")
        elif purpose == "construction":
            clauses.append(building.removesuffix(" }") + " occupancy >= 0.75 }")
        elif purpose == "resource":
            clauses.append(f"has_potential_resource = {row['building']}")
        elif purpose == "infrastructure_direct":
            clauses.append("infrastructure_delta < 0")
        else:
            clauses.append(building)
        is_state = purpose in {
            "labor",
            "labor_ready",
            "infrastructure",
            "local_supply",
            "resource",
            "infrastructure_direct",
        }
        if gates:
            clauses.append(f"ROOT = {{ {gates} }}" if is_state else gates)
        if purpose.endswith("_ready"):
            for good, amount in row["inputs"].items():
                if amount <= 0:
                    continue
                if _query_catalog()["goods"][good]["market"]:
                    expression = f"market = {{ mg:{good} = {{ market_goods_delta >= 0 }} }}"
                    clauses.append(f"ROOT = {{ {expression} }}" if is_state else expression)
                    if purpose == "knowledge_ready":
                        clauses.append(
                            f"market = {{ mg:{good} = {{ market_goods_pricier <= 0.25 }} }}"
                        )
                elif _query_catalog()["goods"][good]["local"]:
                    expression = f"sg:{good} = {{ state_goods_pricier <= 0.25 }}"
                    if is_state:
                        clauses.append(expression)
                    else:
                        # An aggregate country market cannot prove a local
                        # input. This higher tier remains unavailable here.
                        clauses = []
                        break
                else:
                    clauses = []
                    break
        if not clauses:
            continue
        joined = " ".join(clauses)
        expressions.append(
            f"any_scope_state = {{ {joined} }}" if is_state else f"AND = {{ {joined} }}"
        )
    return _or(expressions)


def reader_spec(query: TechnologyQuery) -> dict[str, Any]:
    render_query(query)
    if isinstance(query, TechnologyUseQuery):
        parameters = {
            "technology_query": "technology_use",
            "technology": query.technology,
            "purpose": query.purpose,
        }
        state = query.purpose in {
            "labor",
            "labor_ready",
            "infrastructure",
            "local_supply",
            "resource",
            "infrastructure_direct",
        }
    else:
        parameters = {
            "technology_query": "labor_saving"
            if query.labor_tight
            else "existing_method"
            if query.method_id
            else "existing_building",
            "building": query.building_id,
        }
        if query.method_id:
            parameters["method"] = query.method_id
        state = query.labor_tight
    return {
        "engine": "any_scope_state" if state else "any_scope_building",
        "scope": "root",
        "kind": "boolean",
        "unit": "boolean",
        "parameters": parameters,
    }


def required_query_sources(query: TechnologyQuery) -> tuple[str, ...]:
    render_query(query)
    sources = {_ART}
    state = isinstance(query, TechnologyBuildingQuery) and query.labor_tight
    rows = (
        [{"building": query.building_id, "prior": query.method_id or "", "method": "", "group": ""}]
        if isinstance(query, TechnologyBuildingQuery)
        else query_members(query)
    )
    if isinstance(query, TechnologyUseQuery):
        sources.add(_query_catalog()["technologies"][query.technology]["source"])
        state = query.purpose in {
            "labor",
            "labor_ready",
            "infrastructure",
            "local_supply",
            "resource",
            "infrastructure_direct",
        }
        if query.purpose == "resource":
            sources.add(_OPIUM)
        if query.purpose == "scale":
            sources.add("common/building_groups/00_building_groups.txt")
    if state:
        sources.add(_COMPANY)
    if (isinstance(query, TechnologyBuildingQuery) and query.labor_tight) or (
        isinstance(query, TechnologyUseQuery) and query.purpose.startswith("labor")
    ):
        sources.update({_CULTURE, _SLAVE})
    for row in rows:
        if not row["building"]:
            continue
        building = _query_catalog()["buildings"][row["building"]]
        sources.add(building["source"])
        for group in building["groups"]:
            if (
                row["prior"] and row["prior"] in _query_catalog()["groups"][group]["methods"]
            ) or group == row["group"]:
                sources.add(_query_catalog()["groups"][group]["source"])
        for method in (row["method"], row["prior"]):
            if method:
                sources.add(_query_catalog()["methods"][method]["source"])
    sources.add("common/goods/00_goods.txt")
    return tuple(sorted(sources))


def compile_query(query: TechnologyQuery, inputs: Mapping[str, str]) -> CompiledTechnologyQuery:
    """Check complete native collection consumers and exact graph memberships."""
    expression = render_query(query)
    hashes = []
    roots = {}
    for source in required_query_sources(query):
        text = inputs.get(source)
        if not isinstance(text, str):
            raise ValueError(f"科技查询缺少必需原版来源：{source}")
        normalized = normalized_text(text)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        if digest != {**_query_catalog()["sources"], **query_source_hashes()}[source]:
            raise ValueError(f"科技查询原版来源漂移：{source}")
        parsed = parse_query_source(normalized, source, digest)
        if parsed.errors:
            raise ValueError("科技查询原版来源解析失败")
        roots[source] = parsed.root
        hashes.append((source, digest))
    references = []
    journal = company_observations._child(roots[_ART], "je_romanticism")
    native = (
        version_contracts.journal_completion(journal)
        if version_contracts.active_version() == "1.15.0"
        else company_observations._child(journal, "complete")
    )
    line = company_observations._exact(
        native,
        "any_scope_building",
        "is_building_type = building_art_academy has_active_production_method = pm_traditional_art occupancy >= 0.9 level >= 2",
    )
    references.append(f"{_ART}:{line}")
    if _COMPANY in roots:
        native = company_observations._child(
            company_observations._child(roots[_COMPANY], "company_tashkent_railroad"), "possible"
        )
        line = company_observations._exact(
            native,
            "any_scope_state",
            "state_region = s:STATE_FERGANA is_incorporated = yes has_building = building_railway "
            "custom_tooltip = { text = has_at_least_5_levels_of_railway_tt "
            "any_scope_building = { is_building_type = building_railway level >= 5 } }",
        )
        references.append(f"{_COMPANY}:{line}")
    if _CULTURE in roots:
        line = company_observations._exact(
            roots[_CULTURE], "if", "limit = { state_unemployment_rate >= 0.1 } multiply = 0.5"
        )
        references.append(f"{_CULTURE}:{line}")
        line = company_observations._exact(
            roots[_SLAVE],
            "any_scope_state",
            "pop_type_percent_state = { target = pop_type:slaves value >= 0.55 }",
        )
        references.append(f"{_SLAVE}:{line}")
    if _OPIUM in roots:
        native = company_observations._child(
            company_observations._child(roots[_OPIUM], "je_opium"), "is_shown_when_inactive"
        )
        line = company_observations._exact(
            native, "any_scope_state", "has_potential_resource = building_opium_plantation"
        )
        references.append(f"{_OPIUM}:{line}")
    rows = (
        [{"building": query.building_id, "prior": query.method_id or "", "method": "", "group": ""}]
        if isinstance(query, TechnologyBuildingQuery)
        else query_members(query)
    )
    for row in rows:
        if not row["building"]:
            continue
        frozen = _query_catalog()["buildings"][row["building"]]
        building = company_observations._child(roots[frozen["source"]], row["building"])
        if list(_company()._list(building, "production_method_groups")) != frozen["groups"]:
            raise ValueError("科技查询建筑PMG成员漂移")
        references.append(f"{frozen['source']}:{frozen['line']}")
        for group in frozen["groups"]:
            expected = _query_catalog()["groups"][group]
            if expected["source"] not in roots:
                continue
            actual = company_observations._child(roots[expected["source"]], group)
            if list(_company()._list(actual, "production_methods")) != expected["methods"]:
                raise ValueError("科技查询PMG实际PM成员漂移")
            references.append(f"{expected['source']}:{expected['line']}")
    state = _COMPANY in roots
    return CompiledTechnologyQuery(
        expression,
        tuple(sorted(set(references))),
        tuple(hashes),
        ("owned_states", "owned_state_buildings") if state else ("owned_buildings",),
        ("country:any_scope_state->owned_state", "state:any_scope_building->same_state_building")
        if state
        else ("country:any_scope_building->owned_building",),
    )


def _simple(engine: str, unit: str, kind: str = "number", **extra: Any) -> dict[str, Any]:
    return {"engine": engine, "scope": "root", "kind": kind, "unit": unit, **extra}


def _facts() -> dict[str, Any]:
    return {
        "loans": _simple("taking_loans", "boolean", "boolean"),
        "debt_ratio": _simple("scaled_debt", "debt_to_credit_ratio", minimum=0),
        "literacy": _simple("literacy_rate", "ratio", minimum=0, maximum=1),
        "owned_incorporated_tax_shortfall": _simple(
            "any_scope_state",
            "boolean",
            "boolean",
            parameters={"state_query": "tax_capacity_shortfall"},
        ),
        "num_companies": _simple("num_companies", "company_count", minimum=0),
        "max_num_companies": _simple("max_num_companies", "company_count", minimum=0),
        "own_state_market_exposure": _simple(
            "any_scope_state",
            "boolean",
            "boolean",
            parameters={"threshold": "1.0"},
        ),
        "own_state_deep_market_exposure": _simple(
            "any_scope_state",
            "boolean",
            "boolean",
            parameters={"threshold": "0.9"},
        ),
        "bureaucracy": _simple("bureaucracy", "capacity_balance"),
        "war": _simple("is_at_war", "boolean", "boolean"),
        "own_army": _simple("army_size", "battalions", minimum=0),
        "own_navy": _simple("navy_size", "ships", minimum=0),
        "schools_present": _simple(
            "has_institution", "boolean", "boolean", argument="institution_schools"
        ),
        "health_present": _simple(
            "has_institution", "boolean", "boolean", argument="institution_health_system"
        ),
        "schools_investment": _simple(
            "institution_investment_level",
            "institution_level",
            minimum=0,
            value_field="value",
            parameters={"institution": "institution_schools"},
        ),
        "health_investment": _simple(
            "institution_investment_level",
            "institution_level",
            minimum=0,
            value_field="value",
            parameters={"institution": "institution_health_system"},
        ),
    }


def _condition(fact: str, op: str, value: Any) -> dict[str, Any]:
    return {"fact": fact, "op": op, "value": value}


def derive(
    adapters: Mapping[str, Any],
    catalog: Mapping[str, Any] | None = None,
    *,
    parameters: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Return exact mergeable readers/rules; never read the game installation."""
    frozen = load_catalog() if catalog is None else catalog
    chosen = load_parameters() if parameters is None else _parameters(parameters)
    readers = _facts()
    rules: list[dict[str, Any]] = []
    covered = []
    existing_groups = {
        (r["source"], r["field"], r.get("contribution_group")) for r in adapters["rules"]
    }
    for technology, row in sorted(frozen["technologies"].items()):
        source, field = row["source"], f"{technology}.ai_weight"
        if (
            source in adapters["sources"]
            and adapters["sources"][source] != frozen["sources"][source]
        ):
            raise ValueError("科技机会消费者原版身份漂移")
        modifier = row["modifier"]

        def rule(
            suffix,
            group,
            value,
            conditions,
            why,
            domain="economy",
            *,
            source=source,
            field=field,
            technology=technology,
        ):
            if (source, field, group) in existing_groups:
                return
            rules.append(
                {
                    "id": f"technology_{technology.replace('-', '_')}_{suffix}",
                    "source": source,
                    "field": field,
                    "domain": domain,
                    "operation": "multiply",
                    "value": value,
                    "priority": int(chosen["priority_base"]) + len(rules),
                    "contribution_group": group,
                    "conditions": conditions,
                    "why": why,
                    "counterexample": "未知仅退出本项，饱和退出；研究不支付未来采用费用，保留原版资格、研究点、前置、时代惩罚、随机与执行",
                }
            )

        before = len(rules)
        if modifier.get("country_loan_interest_rate_add", 0) < 0:
            borrowing = [_condition("loans", "=", True)]
            rule(
                "borrowing",
                "borrowing_interest",
                chosen["borrowing_base"],
                borrowing,
                "原版直接降低贷款利率，国家确实正在借款",
                "fiscal",
            )
            rule(
                "borrowing_pressure",
                "borrowing_interest",
                chosen["borrowing_pressure"],
                [*borrowing, _condition("debt_ratio", ">=", chosen["debt_threshold"])],
                "同一借款原因的高债务压力档；不与基础档累加",
                "fiscal",
            )
        if any(
            modifier.get(key, 0) > 0
            for key in (
                "state_education_access_wealth_add",
                "state_literacy_growth_add",
            )
        ):
            rule(
                "literacy",
                "direct_literacy_need",
                chosen["literacy_multiplier"],
                [_condition("literacy", "<", chosen["literacy_threshold"])],
                "原版直接教育可及性或识字增长修复实际低识字，正常借款、战争或违约不取消知识收益",
            )
        if modifier.get("state_tax_capacity_add", 0) > 0:
            rule(
                "tax_capacity",
                "state_tax_capacity_need",
                chosen["tax_capacity_multiplier"],
                [_condition("owned_incorporated_tax_shortfall", "=", True)],
                "原版直接州税容量增加，响应本国已合并州同州税容低于用量；不以全国官僚余额代替",
                "fiscal",
            )
        if modifier.get("country_max_companies_add", 0) > 0:
            companies = [_condition("num_companies", ">", 0)]
            rule(
                "companies",
                "company_slot_pressure",
                chosen["company_base"],
                companies,
                "已使用公司槽位，原版科技直接增加公司上限",
                "market",
            )
            rule(
                "company_limit",
                "company_slot_pressure",
                chosen["company_pressure"],
                [*companies, _condition("num_companies", ">=", {"fact": "max_num_companies"})],
                "实际公司数达到当前公司上限，升档同一个容量原因",
                "market",
            )
        if modifier.get("state_market_access_price_impact", 0) > 0:
            for tier, fact in (
                ("base", "own_state_market_exposure"),
                ("pressure", "own_state_deep_market_exposure"),
            ):
                rule(
                    f"market_{tier}",
                    "local_market_exposure",
                    chosen[f"market_{tier}"],
                    [_condition(fact, "=", True)],
                    "原版直接提升本地价格市场传导，响应本国实际市场接入不足；不推断利息、铸币或财政收入",
                    "market",
                )
        for institution, present, level, context in (
            ("schools", "schools_present", "schools_investment", "education_capacity_use"),
            ("health_system", "health_present", "health_investment", "health_capacity_use"),
        ):
            if modifier.get(f"country_institution_{institution}_max_investment_add", 0) <= 0:
                continue
            conditions = [_condition(present, "=", True), _condition(level, ">=", 1)]
            rule(
                f"{institution}_capacity",
                context,
                chosen["option_base"],
                conditions,
                "原版直接增加该制度投资上限，国家确实已建立并使用相应制度；不把低生活水平猜成疾病暴发",
            )
            rule(
                f"{institution}_capacity_pressure",
                context,
                chosen["option_pressure"],
                [_condition(present, "=", True), _condition(level, ">=", 3)],
                "已使用更高制度投资层级，升档同一个容量采用机会，不伪称已达到全部原版动态上限",
            )

        goods = sorted(
            {
                good
                for opportunity in row["opportunities"]
                for good, amount in opportunity["outputs"].items()
                if amount > 0 and frozen["goods"][good]["market"]
            }
        )
        for good in goods:
            for tier, engine, unit in (
                ("balance", "market_goods_delta", "sell_minus_buy_orders"),
                ("price", "market_goods_pricier", "price_above_base_ratio"),
            ):
                readers[f"country_goods_{good}_{tier}"] = _simple(
                    engine, unit, path=["market", f"mg:{good}"]
                )
            shortage = [_condition(f"country_goods_{good}_balance", "<", 0)]
            rule(
                f"supply_{good}",
                "productive_option_need",
                chosen["supply_base"],
                shortage,
                f"真实新配方或建筑正产出{good}，当前市场缺口形成研究供给选项；不是实际已建造或已启用",
                "market",
            )
            rule(
                f"supply_{good}_pressure",
                "productive_option_need",
                chosen["supply_pressure"],
                [
                    *shortage,
                    _condition(f"country_goods_{good}_price", ">", chosen["price_threshold"]),
                ],
                f"{good}缺口与高价升档同一供给原因；不同替代方式或同配方多种产出不累加",
                "market",
            )

        def use(
            purpose,
            multiplier,
            group,
            conditions=(),
            domain="economy",
            *,
            technology=technology,
            rule=rule,
        ):
            # These auxiliary supply-ready tiers repeat large native member
            # sets. Keep all basic mechanisms and actual uses while honoring
            # the existing expanded per-consumer 160-predicate budget.
            if (
                technology == "compression_ignition"
                and purpose in {"productive_ready", "labor_ready"}
            ) or (technology == "mechanized_workshops" and purpose == "productive_ready"):
                return
            query = TechnologyUseQuery(technology, purpose)
            if not query_members(query, frozen):
                return
            try:
                spec = reader_spec(query)
            except ValueError as exc:
                if "没有真实机制成员" in str(exc):
                    return
                raise
            fact = f"technology_use_{technology.replace('-', '_')}_{purpose}"
            readers[fact] = spec
            rule(
                purpose,
                group,
                multiplier,
                [_condition(fact, "=", True), *conditions],
                f"锁定真实{purpose}机会成员与本国实际使用匹配；同州、同建筑、低级PM与目标产出不跨成员拼接，未知局部退出",
                domain,
            )

        use("productive", chosen["supply_active"], "productive_option_need", domain="market")
        use("productive_ready", chosen["supply_ready"], "productive_option_need", domain="market")
        use("labor", chosen["labor_base"], "observed_labor_saving")
        use("labor_ready", chosen["labor_ready"], "observed_labor_saving")
        use(
            "administration",
            chosen["option_base"],
            "administration_method_option",
            [_condition("bureaucracy", "<", 0)],
            "fiscal",
        )
        use(
            "knowledge",
            chosen["option_base"],
            "university_method_option",
            [_condition("literacy", "<", chosen["literacy_threshold"])],
        )
        use(
            "knowledge_ready",
            chosen["option_pressure"],
            "university_method_option",
            [_condition("literacy", "<", chosen["literacy_threshold"])],
        )
        use("infrastructure", chosen["option_pressure"], "local_infrastructure_need")
        use("local_supply", chosen["supply_pressure"], "local_goods_supply_need", domain="market")
        use("throughput", chosen["supply_pressure"], "productive_option_need", domain="market")
        use("trade", chosen["option_base"], "observed_trade_method_option", domain="market")
        use("construction", chosen["option_base"], "observed_construction_capacity")
        use("infrastructure_direct", chosen["option_pressure"], "local_infrastructure_need")
        use("resource", chosen["option_base"], "known_resource_minting_option", domain="fiscal")
        use("scale", chosen["option_base"], "observed_scale_expansion_option")
        if any(
            o["services"].get("country_bureaucracy_add", 0) > 0 and o["kind"] == "building"
            for o in row["opportunities"]
        ):
            rule(
                "administration_building",
                "administration_building_option",
                chosen["option_pressure"],
                [_condition("bureaucracy", "<", 0)],
                "原版解锁真实产官僚的政府设施，实际全国官僚缺口形成建筑选项；不是科技直接生产官僚",
                "fiscal",
            )

        branches = {entry["branch"] for entry in row.get("military", [])}
        if any(
            key.startswith(
                ("unit_army_", "unit_combat_unit_", "country_general_", "state_conscription_")
            )
            or key in {"unit_kill_rate_add", "unit_experience_gain_mult", "unit_morale_loss_mult"}
            for key in modifier
        ):
            branches.add("army")
        if any(key.startswith(("ship_", "country_admiral_", "country_ship_")) for key in modifier):
            branches.add("navy")
        if any(key.startswith("country_war_support_") for key in modifier):
            branches.add("army")
        if any(o["services"].get("country_sailors_max_add", 0) > 0 for o in row["opportunities"]):
            branches.add("navy")
        for branch in sorted(branches):
            force = "own_army" if branch == "army" else "own_navy"
            current_force = [_condition(force, ">", 0)]
            rule(
                f"{branch}_use",
                f"current_{branch}_option",
                chosen["military_base"],
                current_force,
                f"国家实际拥有{branch}，原版直接军事增益或具体装备/部队/保障解锁与现有力量相关；研究不即时扩军付费",
                "military",
            )
            rule(
                f"{branch}_war",
                f"current_{branch}_option",
                chosen["military_pressure"],
                [*current_force, _condition("war", "=", True)],
                "实际拥有相应军种且正在战争，升档同一军事使用原因；战争标记不推断完整敌情或装备已采用",
                "military",
            )

        if technology == "currency_standards":
            support = "technology_per_capita_reform_support"
            current = "technology_current_per_capita_taxation"
            readers[support] = _simple(
                "any_political_movement",
                "boolean",
                "boolean",
                parameters={"law": "law_per_capita_based_taxation", "minimum_support": "0.1"},
            )
            readers[current] = _simple(
                "has_law_or_variant",
                "boolean",
                "boolean",
                argument="law_type:law_per_capita_based_taxation",
            )
            rule(
                "supported_tax_option",
                "supported_tax_reform_option",
                chosen["option_base"],
                [_condition(support, "=", True), _condition(current, "=", False)],
                "原版解锁人头税法且存在真实支持该法的运动；只表达受支持政策选项，不宣称贷款必然产生净税收",
                "political",
            )
        covered.append(
            {
                "id": technology,
                "source": source,
                "field": field,
                "rule_ids": [r["id"] for r in rules[before:]],
            }
        )
    used = {condition["fact"] for rule in rules for condition in rule["conditions"]}
    used.update(
        condition["value"]["fact"]
        for rule in rules
        for condition in rule["conditions"]
        if isinstance(condition["value"], dict)
    )
    for key in used:
        if key in adapters["readers"] and adapters["readers"][key] != readers[key]:
            raise ValueError(f"科技机会读取器身份漂移：{key}")
    result = {
        "sources": {**dict(frozen["sources"]), **query_source_hashes()},
        "readers": {key: readers[key] for key in sorted(used)},
        "rules": rules,
        "covered": covered,
        "uncovered": [],
    }
    result["complexity"] = validate_complexity(result)
    result["replacements"] = [
        {
            **old,
            "replacement_rule_ids": [r["id"] for r in rules if r["field"] == old["field"]],
            "reason": "exact_native_mechanisms_replace_legacy_tags_routes_and_unrelated_gates",
        }
        for old in frozen.get("legacy_rules", [])
    ]
    return result


def validate_complexity(derived: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    """Count outer rules, logical clauses, expanded leaves and OR branches."""
    from . import decision_rules  # noqa: PLC0415

    def count(block: Block) -> tuple[int, int]:
        leaves = branches = 0
        for row in block.assignments():
            if isinstance(row.value, Block):
                child_leaves, child_branches = count(row.value)
                leaves += child_leaves
                branches += child_branches
                if row.key == "OR":
                    branches += sum(1 for _ in row.value.assignments())
            else:
                leaves += 1
        return leaves, branches

    costs = {}
    for key, spec in derived["readers"].items():
        if "technology_query" in spec.get("parameters", {}):
            query = query_from_reader(spec["engine"], spec["parameters"])
            costs[key] = count(parse_text(render_query(query)).root)
    results: dict[str, dict[str, int]] = {}
    for rule in derived["rules"]:
        row = results.setdefault(
            rule["field"],
            {"rules": 0, "logical_predicates": 0, "expanded_leaves": 0, "or_branches": 0},
        )
        row["rules"] += 1
        row["logical_predicates"] += len(rule["conditions"])
        for condition in rule["conditions"]:
            leaves, branches = costs.get(condition["fact"], (1, 0))
            row["expanded_leaves"] += leaves
            row["or_branches"] += branches
        if (
            row["rules"] > decision_rules.STATIC_BUDGET["candidates_per_field"]
            or row["logical_predicates"] > decision_rules.STATIC_BUDGET["predicates_per_field"]
            or row["expanded_leaves"] > decision_rules.STATIC_BUDGET["predicates_per_field"]
            or row["or_branches"] > decision_rules.STATIC_BUDGET["predicates_per_field"]
        ):
            raise ValueError(f"科技机会实际展开超过现有消费者静态预算：{rule['field']}")
    return results


def verify_inputs(inputs: Mapping[str, str]) -> dict[str, Any]:
    """Rebuild the entire offline mechanism artifact from locked native texts."""
    frozen = load_catalog()
    focused = {}
    for source, expected in frozen["sources"].items():
        text = inputs.get(source)
        if not isinstance(text, str):
            raise ValueError(f"科技机会缺少锁定原版输入：{source}")
        normalized = normalized_text(text)
        if hashlib.sha256(normalized.encode("utf-8")).hexdigest() != expected:
            raise ValueError(f"科技机会原版来源漂移：{source}")
        focused[source] = normalized
    current = inventory(
        focused, {key: row["source"] for key, row in frozen["technologies"].items()}
    )
    if "native_retained" in frozen:
        discovered = {}
        for source, text in focused.items():
            if _family(source) != "technologies":
                continue
            for entry in parse_text(text, path=source).root.assignments():
                if isinstance(entry.value, Block) and entry.value.all("ai_weight"):
                    discovered[entry.key] = source
        claimed = {
            **{key: row["source"] for key, row in frozen["technologies"].items()},
            **frozen["native_retained"],
        }
        if discovered != claimed:
            raise ValueError("科技机制原生评分消费者分母漂移")
        current["native_retained"] = dict(frozen["native_retained"])
    expected = {key: value for key, value in frozen.items() if key != "legacy_rules"}
    if current != expected:
        raise ValueError("科技机会冻结机制与原版完整派生不一致")
    return current
