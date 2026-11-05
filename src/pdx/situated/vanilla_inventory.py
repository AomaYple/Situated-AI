"""D0 原版消费者独立发现，不以 Mod 规则或已修改文件作为发现分母。

扫描 common 全树定位 AI 相关目录，并盘点全部已挂载 events 选项，再解析全部定义。发现的字段和
读取器均保持实现 pending；只有原版文档明确支持的字段级作用域才进入 legal。
字段存在、脚本引用了某个 scope、可从日志观察，均不能证明合法控制能力。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, replace
from dataclasses import field as dataclass_field
from itertools import pairwise
from math import isfinite
from pathlib import PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Any

from .. import config  # noqa: TID252
from ..lexer import ATOM, LBRACE, OP, RBRACE, STRING, tokenize  # noqa: TID252
from ..model import Assignment, Block, Scalar  # noqa: TID252
from ..parser import PREFIXES, parse_bytes  # noqa: TID252
from ..textio import normalized_text  # noqa: TID252
from . import engine_scope

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

SCHEMA = 1
LOCKED_VERSION = "1.14.5"
# 冻结旧集合的迁移分母，绝不作为本模块原版消费者分母。
MIGRATION_DENOMINATOR = 1401
CAPABILITIES = ("direct", "indirect", "observation", "unexposed", "pending")
_AI_ASSIGNMENT = re.compile(
    rb"(?<![\w:])(?:(?:"
    + b"|".join(prefix.encode("ascii") for prefix in PREFIXES)
    + rb"):)?(?:ai|ai_[a-zA-Z0-9_]+)\s*="
)
# Assignment-only discovery misses AI calls, predicates and variables in
# journal entries and scripted infrastructure.  Keep those definitions in the
# audit input set even when they do not introduce a directly controllable
# consumer field.
_AI_REFERENCE = re.compile(rb"(?<![\w:])(?:ai_[a-zA-Z0-9_]+|is_ai)\b|\bai\s*\.")
_REQUIRED_DIRS = frozenset(
    {
        "ai_strategies",
        "laws",
        "buildings",
        "building_groups",
        "interest_groups",
        "institutions",
        "technology",
        "diplomatic_actions",
        "treaty_articles",
        "war_goal_types",
        "defines",
        "script_values",
        "scripted_triggers",
        # Exact event effects need their complete modifier definitions as
        # context evidence; scanning does not authorize modifier writers.
        "static_modifiers",
        # Owning-country context of journal-triggered event opportunities.
        # This evidence directory grants no AI writer permissions by itself.
        "journal_entry_groups",
    }
)
_OBSERVATION_DIRS = frozenset({"script_values", "scripted_triggers"})
_INFRASTRUCTURE_DIRS = frozenset({"scripted_effects", "on_actions", "trigger_localization"})
# Auxiliary 1.14.5 native evidence, independently frozen from installed bytes.
# These declarations establish goods, unit, law and observation arguments; they
# never enter consumer discovery merely because a Mod reader uses them.
_PARAMETER_EVIDENCE_HASHES = {
    "events/brazil/amazonas.txt": "1841eee77acbbea074ca4d9506cce0b3aa391f08bbda21394610af287e9943d2",
    "common/tutorial_lessons/00_tutorial_lessons_promote_ig.txt": "554a34f763aad704582a610450c88f03a009951724c4088f409111543163cd55",
    "common/achievements/base_achievements.txt": "dc5a50c8313fffbe50d68f0a6b8c9b9d05f1794f46725d23f2c0e67f7369799f",
    "common/achievements/ep1_sphere_of_influence_achievements.txt": "aa504255aabcf3cfecf6fc6196cf66803a7e87b8b15c2458034c97a95dec82e0",
    "common/achievements/ip2_pivot_of_empire_achievements.txt": "9ce0330dab546239369a8b916b5ee8fc85ad6de28d5ec5cc60c47c798d271de8",
    "common/achievements/ip4_iberian_twilight_achievements.txt": "0fb91eda557761442864e4e18a4a5c7be3dace31ac9b423b2581bfab8b986268",
    "common/alert_types/00_alert_types.txt": "14ff4bb983f84c17fc2825d79ce93620bc68cde7284f8d1fa2dbba6845420aea",
    "common/combat_unit_types/00_land_combat_unit_types.txt": "ad3ed3d68533cbe6ef05ce014cd88b920b58dc4a42b3e566077cdccee072d86c",
    "common/goods/00_goods.txt": "e5d8ed5e5deaf3d2c7193bc6b749555c63c78631aecaf87784a2e34051ddfa48",
    "common/ideologies/00_ig_ideologies.txt": "4c8bc020d2d1060795e5a615b850736b731a31193862399363ec2e1829639b05",
    "common/ideologies/01_character_ideologies.txt": "ee996f042b387707e5bc305c32bd7e83d9b706aec784cb4e4f35ade0dae98bee",
    "common/journal_entries/00_urbanization.txt": "0be06294448f31679d2b14280b4e6c1991f0d2fa34f97ccc0452068c7cdc5ee6",
    "common/objective_subgoals/00_subgoals_tutorial.txt": "ca2052a10b208fb311e219b9ec2589875b4b0876cc86d92c5728cabaaba080ed",
    "common/political_movements/00_ideological_movements.txt": "834a1b97f09c65b9b64eafdaffe4ee68965aaac262066140793a482eefd23a6b",
    "common/political_movements/05_slave_revolt_movements.txt": "903ca4c58fcbc0a4eded9e0e710ffbf55b27c60fa80ec56d36dca3b4045b0918",
    "common/pop_types/laborers.txt": "90e109f061ca04c308d3d60cf6ba6d91cbe3769759ff28f0a9a0bd34e169a2d5",
    "common/pop_types/machinists.txt": "e0ddad8032fd6be5d0eb77533cf9f711a5baf5fe275d20819bc5ba8e3f6785ee",
    "common/pop_types/peasants.txt": "1d544a332f7c628b5f832f2a2033c25fafde6d9ed5e629b829432a57419f0c42",
    "common/religions/religion.txt": "96ee8ddca57de6957b1a1501f91896e37a086319468312952a1843e5892d1814",
    "events/french_pretenders_pulse.txt": "3ed2ebf66cef1b0159ae352177cebd0a8d5c6e6de1bbab8732ef6a17e82d94bb",
    "events/law_events/children_rights_events.txt": "13414a1a5e817c98a2f2e8244c9ae997bf9d89cf96d1d68b3bd9244bcfaf50b8",
    "events/law_events/state_atheism.txt": "156c7e20ba3326e8aacb0bc3c91acdb9b6bf84988a15d9357467e707ee9e30ec",
    "events/tech_events/trench_warfare.txt": "d859e625e0843d5d56d515b647e7833a0cb5eb3e5d85b233d4d1be697be1a93e",
}
_MAP_FIELDS = frozenset(
    {
        "building_group_weights",
        "goods_stances",
        "institution_scores",
        "secret_goal_scores",
        "secret_goal_weights",
        "wargoal_scores",
        "wargoal_weights",
        "strategic_region_scores",
        "strategic_region_stance_type_scores",
        "liberate_country_scores",
        "treaty_category_scores",
        "ai_ship_category_weights",
        "combat_unit_group_weights",
        "fleet_compositions",
        "strait_scores",
        "ai_construction_targets",
    }
)
_EXPRESSION_KEYS = frozenset(
    {
        "value",
        "base",
        "add",
        "subtract",
        "multiply",
        "divide",
        "if",
        "else_if",
        "else",
        "always",
        "exists",
        "limit",
        "NOT",
        "OR",
        "AND",
        "NOR",
        "NAND",
        "trigger",
    }
)
_DIPLOMATIC_OPERATIONS = {
    "evaluation_chance": "chance",
    "will_select_as_first_state": "predicate",
    "will_select_as_second_state": "predicate",
    "will_propose_with_states": "predicate",
    "will_propose": "predicate",
    "will_break": "predicate",
    "will_propose_even_if_not_accepted": "predicate",
    "accept_score": "score",
    "accept_break_score": "score",
    "propose_score": "score",
    "propose_break_score": "score",
    "use_favor_chance": "chance",
    "owe_favor_chance": "chance",
}


@dataclass(frozen=True, slots=True)
class VanillaSurface:
    surface_id: str
    source: str
    definition: str
    field: str
    actor_scope: str
    target_scope: str
    operation: str
    capability: str
    status: str
    getter: str | None
    getter_note: str
    scope_evidence: tuple[str, ...]
    responsibility_step: str
    source_line: int
    declaration_occurrence: int = 1
    ambiguity: str | None = None
    # Internal syntax observations retain the original discovered row while
    # pointing at the real consumer field; they are never independent writers.
    parent_field: str | None = None
    parent_source_line: int | None = None

    @property
    def declaration_id(self) -> str:
        """声明身份独立于可被新证据修正的 actor/target/operation 语义身份。"""
        return _digest((self.source, self.definition, self.field, self.declaration_occurrence))

    @property
    def legal(self) -> bool:
        return (
            self.capability in {"direct", "indirect"}
            and self.actor_scope != "unknown"
            and self.target_scope != "unknown"
            and bool(self.scope_evidence)
        )


@dataclass(frozen=True, slots=True)
class VanillaReference:
    """原版脚本引用审计记录，不代表可写入的 AI 消费者。"""

    reference_id: str
    source: str
    line: int
    kind: str
    expression: str
    status: str = "reference_only"
    column: int = 1
    occurrence: int = 1


@dataclass(frozen=True, slots=True)
class VanillaEventOption:
    """An actual option declaration, including slots with no declared AI weight.

    Absence of ai_chance never establishes its default weight, write authority,
    or a relationship between default_option and AI selection.
    """

    source: str
    definition: str
    field: str
    option_index: int
    option_name: str | None
    event_type: str | None
    source_line: int
    weight_lines: tuple[int, ...]
    default_option: str | None
    ambiguity: str | None = None


@dataclass(frozen=True, slots=True)
class VanillaInventory:
    baseline_id: str
    source_hashes: dict[str, str]
    scope_hash: str
    surfaces: tuple[VanillaSurface, ...]
    scanned_directories: tuple[str, ...]
    content_roots: tuple[str, ...]
    parsed_files: int
    references: tuple[VanillaReference, ...] = ()
    # Parse failures are part of the receipt even though related-file parse
    # errors remain hard failures.  Keeping this as data prevents the JSON
    # receipt from silently inventing an empty list independently of the
    # discovery result.
    parse_failures: tuple[str, ...] = ()
    event_options: tuple[VanillaEventOption, ...] = ()

    @property
    def discovered_count(self) -> int:
        return len(self.surfaces)

    @property
    def legal_count(self) -> int:
        return sum(item.legal for item in self.surfaces)

    @property
    def pending_count(self) -> int:
        return sum(item.status == "pending" for item in self.surfaces)

    @property
    def unexposed_count(self) -> int:
        return sum(item.capability == "unexposed" for item in self.surfaces)

    @property
    def status_counts(self) -> dict[str, int]:
        return dict(sorted(Counter(item.status for item in self.surfaces).items()))

    @property
    def capability_counts(self) -> dict[str, int]:
        counts = Counter(item.capability for item in self.surfaces)
        return {name: counts[name] for name in CAPABILITIES}

    @property
    def unknown_scopes(self) -> tuple[str, ...]:
        """Surface identities whose scope contract is not fully proven."""
        return tuple(
            sorted(
                item.surface_id
                for item in self.surfaces
                if (
                    item.actor_scope in {"", "unknown"}
                    or item.target_scope in {"", "unknown"}
                    or item.operation in {"", "unknown", "declared_field"}
                    or not item.scope_evidence
                )
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "plan_version": "31.4",
            "evidence": "static_discovery_not_implementation_or_engine_behavior",
            "baseline_id": self.baseline_id,
            "source_hashes": self.source_hashes,
            "scope_hash": self.scope_hash,
            "scanned_directories": list(self.scanned_directories),
            "content_roots": list(self.content_roots),
            "activation_policy": "all_installed_content_not_runtime_activation",
            "parsed_files": self.parsed_files,
            "references": [asdict(item) for item in self.references],
            "reference_count": len(self.references),
            "surfaces": [
                {**asdict(item), "declaration_id": item.declaration_id, "legal": item.legal}
                for item in self.surfaces
            ],
            "discovered_count": self.discovered_count,
            "legal_count": self.legal_count,
            "unexposed_count": self.unexposed_count,
            "pending_count": self.pending_count,
            "status_counts": self.status_counts,
            "capability_counts": self.capability_counts,
            "migration_denominator": MIGRATION_DENOMINATOR,
            "parse_failures": list(self.parse_failures),
            "unknown_scopes": list(self.unknown_scopes),
            "event_options": [asdict(item) for item in self.event_options],
            "event_option_count": len(self.event_options),
            "event_explicit_weight_count": sum(
                len(item.weight_lines) for item in self.event_options
            ),
            "event_undeclared_weight_count": sum(
                not item.weight_lines for item in self.event_options
            ),
            "event_default_semantics": "unknown; default_option is recorded, not interpreted as AI weight",
        }


@dataclass(frozen=True, slots=True)
class VanillaDefinition:
    """Physical definition ownership, independent of merge or scope semantics."""

    source: str
    directory: str
    definition: str
    definition_index: int
    source_line: int
    declaration_occurrence: int
    operator: str
    prefix: str | None
    is_block: bool
    surface_declaration_ids: tuple[str, ...] = ()

    @property
    def declaration_id(self) -> str:
        return _digest((self.source, self.definition, self.declaration_occurrence))


@dataclass(frozen=True, slots=True)
class VanillaEventSlot:
    """Physical slot ownership; identity is independent of inferred scope."""

    slot_id: str
    owner_declaration_id: str
    owner_definition_index: int
    owner_declaration_occurrence: int
    source: str
    definition: str
    option_index: int
    source_line: int
    surface_declaration_ids: tuple[str, ...]
    surface_ids: tuple[str, ...] = ()
    ambiguities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UnverifiedVanillaInventory(VanillaInventory):
    """Discovery only: this result cannot establish reader or writer authority."""

    target_version: str = ""
    actual_version: dict[str, str] | None = None
    definitions: tuple[VanillaDefinition, ...] = ()
    unsupported_structures: tuple[dict[str, Any], ...] = ()
    source_syntax: dict[str, dict[str, Any]] = dataclass_field(default_factory=dict)
    event_slots: tuple[VanillaEventSlot, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        payload = VanillaInventory.as_dict(self)
        payload.update(
            discovery_mode="unverified",
            authorization="none",
            evidence="unverified_native_discovery_not_scope_or_getter_authorization",
            target_version=self.target_version,
            actual_version=self.actual_version,
            definitions=[
                {**asdict(item), "declaration_id": item.declaration_id} for item in self.definitions
            ],
            definition_count=len(self.definitions),
            unsupported_structures=list(self.unsupported_structures),
            scope_hash_semantics="unverified_discovery_result_identity_only",
            source_syntax=self.source_syntax,
            syntax_retention_policy="all_parsed_txt_and_dlc_nodes; preserved syntax is not semantic classification",
            syntax_node_position_policy="zero_based_block_item_indexes; assignment_value_step_is_minus_one",
            event_slots=[asdict(item) for item in self.event_slots],
        )
        return payload


@dataclass(frozen=True, slots=True)
class _Discovery:
    surfaces: list[VanillaSurface]
    parsed_files: int
    parse_failures: tuple[str, ...]
    event_options: tuple[VanillaEventOption, ...]
    definitions: tuple[VanillaDefinition, ...]
    unsupported_structures: tuple[dict[str, Any], ...]
    event_slots: tuple[VanillaEventSlot, ...]


@dataclass(frozen=True, slots=True)
class _Scope:
    actor: str = "unknown"
    target: str = "unknown"
    operation: str = "declared_field"
    capability: str = "pending"
    evidence: tuple[str, ...] = ()
    parent_field: str | None = None
    parent_source_line: int | None = None


def _digest(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _contained(game: Path, path: Path) -> None:
    """Reject aliases as well as escapes: one physical input has one source identity."""
    if not path.resolve().is_relative_to(game.resolve()):
        raise ValueError(f"原版输入超出锁定树：{path}")
    relative = path.relative_to(game)
    current = game
    for part in relative.parts:
        current /= part
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise ValueError(f"原版输入不允许符号链接或 junction 别名：{current}")


def _has_ai_assignment(raw: bytes) -> bool:
    """The regex is only a fast prefilter; comments and string contents are not keys."""
    if _AI_ASSIGNMENT.search(raw) is None:
        return False
    tokens = tokenize(raw.decode("utf-8-sig"))
    for token, following in pairwise(tokens):
        if token.kind != ATOM or following.kind != OP or following.value != "=":
            continue
        key = token.value
        prefix, separator, remainder = key.partition(":")
        if separator and prefix in PREFIXES:
            key = remainder
        if re.fullmatch(r"ai|ai_[a-zA-Z0-9_]+", key):
            return True
    return False


def _inputs(game: Path) -> tuple[dict[str, bytes], tuple[str, ...], tuple[str, ...]]:
    common = game / "common"
    if not common.is_dir():
        raise ValueError(f"原版 common 树不存在：{common}")
    _contained(game, common)
    roots = [common]
    roots.extend(
        candidate
        for candidate in (game / "events", game / "in_game/common", game / "in_game/events")
        if candidate.is_dir()
    )
    dlc = game / "dlc"
    descriptors: dict[str, bytes] = {}
    if dlc.is_dir():
        _contained(game, dlc)
        for descriptor in sorted(dlc.rglob("*.dlc")):
            _contained(game, descriptor)
            source = descriptor.relative_to(game).as_posix()
            raw = descriptor.read_bytes()
            parsed = parse_bytes(raw, path=source)
            if parsed.errors:
                raise ValueError(f"DLC 描述符解析失败：{source}: {'; '.join(parsed.errors)}")
            if any(item.key == "archive" for item in parsed.top_assignments):
                raise ValueError(f"DLC archive 挂载未读取，不能声称完整范围：{source}")
            mounts = [item for item in parsed.top_assignments if item.key == "path"]
            if len(mounts) != 1 or not isinstance(mounts[0].value, Scalar):
                raise ValueError(f"DLC 描述符缺少唯一 path：{source}")
            mount_name = mounts[0].value.unquoted
            if (
                not mount_name
                or PureWindowsPath(mount_name).drive
                or PureWindowsPath(mount_name).root
                or PurePosixPath(mount_name).is_absolute()
                or ".." in mount_name.replace("\\", "/").split("/")
                or "\\" in mount_name
            ):
                raise ValueError(f"DLC 挂载必须是锁定树内的相对路径：{source}: {mount_name}")
            mount = game / mount_name
            _contained(game, mount)
            if not mount.is_dir():
                raise ValueError(f"DLC 挂载目录缺失或超出锁定树：{source}: {mount_name}")
            if mount.name in {"common", "events"}:
                roots.append(mount)
            # A descriptor mounts one content root.  Only its declared root
            # and its direct common trees are in scope; recursively importing
            # arbitrary nested/sibling ``common`` directories would make the
            # inventory claim files the engine does not mount from this DLC.
            roots.extend(
                candidate
                for candidate in (
                    mount / "common",
                    mount / "events",
                    mount / "in_game" / "common",
                    mount / "in_game" / "events",
                )
                if candidate.is_dir()
            )
            descriptors[source] = raw
    roots = sorted(set(roots))
    for content_root in roots:
        _contained(game, content_root)
        for path in content_root.rglob("*"):
            _contained(game, path)
    files = sorted(
        (root, path)
        for root in roots
        for path in root.rglob("*")
        if path.is_file() and path.suffix in {".txt", ".md"}
    )
    related = set(_REQUIRED_DIRS)
    for content_root, path in files:
        if content_root.name == "events":
            continue
        directory = path.relative_to(content_root).parts[0]
        if directory.startswith("ai_"):
            related.add(directory)
        raw = path.read_bytes()
        if (path.suffix == ".txt" and (_has_ai_assignment(raw) or _AI_REFERENCE.search(raw))) or (
            path.suffix == ".md" and re.search(rb"\bAI\b", raw)
        ):
            related.add(directory)
    selected = {
        path.relative_to(game).as_posix(): path.read_bytes()
        for content_root, path in files
        if content_root.name == "events" or path.relative_to(content_root).parts[0] in related
    }
    directories = tuple(
        sorted(
            {
                (
                    content_root
                    if content_root.name == "events"
                    else content_root / path.relative_to(content_root).parts[0]
                )
                .relative_to(game)
                .as_posix()
                for content_root, path in files
                if content_root.name == "events"
                or path.relative_to(content_root).parts[0] in related
            }
        )
    )
    if not any(name.endswith(".txt") for name in selected):
        raise ValueError("原版相关 common 定义缺失，不能生成空范围")
    selected.update(descriptors)
    return selected, directories, tuple(sorted(root.relative_to(game).as_posix() for root in roots))


def _doc_scope(
    inputs: dict[str, bytes],
    source: str,
    markers: tuple[str, ...],
    actor: str,
    target: str,
    operation: str,
    capability: str = "direct",
    *,
    section: str | None = None,
) -> _Scope:
    raw = inputs.get(source)
    if raw is None:
        return _Scope()
    text = raw.decode("utf-8-sig")
    offset = 0
    if section is not None:
        heading = re.search(rf"^###\s+{re.escape(section)}[^\n]*$", text, re.MULTILINE)
        if heading is None:
            return _Scope()
        offset = text[: heading.start()].count("\n")
        text = text[heading.start() :]
        next_heading = re.search(r"\n###\s+", text)
        if next_heading is not None:
            text = text[: next_heading.start()]
    if not all(marker in text for marker in markers):
        return _Scope()
    line = offset + text[: text.index(markers[0])].count("\n") + 1
    return _Scope(actor, target, operation, capability, (f"{source}:{line}",))


def _static_policy_scope(
    directory: str,
    field: tuple[str, ...],
    inputs: dict[str, bytes],
    definition: Assignment,
) -> _Scope:
    """字段级静态配置合同，不授予运行时国家/目标脚本作用域。"""
    if definition.op != "=" or definition.prefix is not None:
        return _Scope()
    current = definition
    for key in field:
        if not isinstance(current.value, Block):
            return _Scope()
        matches = current.value.all(key)
        if len(matches) != 1:
            return _Scope()
        current = matches[0]
        if current.op != "=" or current.prefix is not None:
            return _Scope()
    if directory == "production_method_groups":
        if (
            not isinstance(current.value, Scalar)
            or current.value.quoted
            or current.value.text not in {"most_profitable", "most_productive"}
        ):
            return _Scope()
        return _doc_scope(
            inputs,
            "common/production_method_groups/production_method_groups.md",
            (
                "ai_selection = most_productive",
                "Affects how the AI chooses between PMs.",
                "Current options: most_profitable, most_productive.",
                "Default most_profitable",
            ),
            "global",
            "none",
            "ai_selection_policy",
            "indirect",
        )
    if directory == "war_goal_types" and field == ("ai", "is_significant_demand"):
        if (
            not isinstance(current.value, Scalar)
            or current.value.quoted
            or current.value.text not in {"yes", "no"}
        ):
            return _Scope()
        return _doc_scope(
            inputs,
            "common/war_goal_types/war_goal_types.md",
            (
                "## AI / Is Significant Demand",
                "AI flag that determines how important AI considers this war goal to be.",
                "is_significant_demand = yes",
            ),
            "global",
            "none",
            "significant_demand_flag",
            "indirect",
        )
    if directory == "war_goal_types" and field == ("ai", "settles_grievance"):
        if (
            not isinstance(current.value, Scalar)
            or current.value.quoted
            or current.value.text not in {"yes", "no"}
        ):
            return _Scope()
        return _doc_scope(
            inputs,
            "common/war_goal_types/war_goal_types.md",
            (
                "settles_grievance = no",
                "yes = an AI with an Antagonistic attitude towards the target may still start a diplomatic play for this war goal",
            ),
            "global",
            "none",
            "grievance_start_permission",
            "indirect",
        )
    if not isinstance(current.value, Block) or not current.value.items:
        return _Scope()
    # Stances are references to declared stance types, not arbitrary enums or
    # trigger expressions. Preserve unknown/extra nodes as pending surfaces.
    stance_keys: set[str] = set()
    for source, raw in inputs.items():
        if not source.endswith(".txt") or not (
            source.startswith("common/ai_strategic_region_stance_types/")
            or "/common/ai_strategic_region_stance_types/" in source
        ):
            continue
        parsed = parse_bytes(raw, path=source)
        if parsed.errors:
            return _Scope()
        stance_keys.update(
            item.key
            for item in parsed.top_assignments
            if not item.is_variable
            and item.op == "="
            and item.prefix is None
            and isinstance(item.value, Block)
        )
    if any(
        not isinstance(item, Scalar) or item.quoted or item.text not in stance_keys
        for item in current.value.items
    ):
        return _Scope()
    return _doc_scope(
        inputs,
        "common/ai_regional_objectives/ai_regional_objectives.md",
        (
            "stances = { stance_key ... }",
            "Which regional stances this objective may be drawn for.",
        ),
        "global",
        "none",
        "objective_stance_eligibility",
        "indirect",
    )


def _subject_value_minimum(inputs: dict[str, bytes]) -> tuple[float, str] | None:
    """Freeze the documented static lower bound once per discovery input set.

    This proves admissible configuration only, not the engine's handling of a
    value below the bound. Multiple mounted namespaces have unproved merge semantics.
    """
    namespaces: list[tuple[str, bytes, Assignment]] = []
    for source, raw in inputs.items():
        if not source.endswith(".txt") or not (
            source.startswith("common/defines/") or "/common/defines/" in source
        ):
            continue
        parsed = parse_bytes(raw, path=source)
        if parsed.errors:
            return None
        namespaces.extend(
            (source, raw, item) for item in parsed.top_assignments if item.key == "NAI"
        )
    if len(namespaces) != 1:
        return None
    source, raw, namespace = namespaces[0]
    if (
        namespace.op != "="
        or namespace.prefix is not None
        or not isinstance(namespace.value, Block)
    ):
        return None
    minimum = _ordinary_child(namespace.value, "MIN_SUBJECT_TYPE_VALUE")
    if (
        minimum is None
        or not isinstance(minimum.value, Scalar)
        or minimum.value.quoted
        or re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)", minimum.value.text) is None
    ):
        return None
    value = float(minimum.value.text)
    if not isfinite(value) or value <= 0:
        return None
    line = raw.decode("utf-8-sig").splitlines()[minimum.line - 1]
    before, separator, comment = line.partition("#")
    if (
        not separator
        or comment.strip() != "ai_value for a subject type is never below this"
        or re.search(
            r"\bMIN_SUBJECT_TYPE_VALUE\s*=\s*" + re.escape(minimum.value.text) + r"\s*$",
            before,
        )
        is None
    ):
        return None
    return value, f"{source}:{minimum.line}"


def _static_subject_value_scope(
    inputs: dict[str, bytes],
    definition: Assignment,
    source: str,
    minimum_context: tuple[tuple[float, str] | None, ...] = (),
) -> _Scope:
    """Only a documented, single literal is global configuration, never a country getter."""
    if (
        definition.op != "="
        or definition.prefix is not None
        or not isinstance(definition.value, Block)
    ):
        return _Scope()
    assignment = _ordinary_child(definition.value, "ai_value")
    if (
        assignment is None
        or not isinstance(assignment.value, Block)
        or len(assignment.value.items) != 1
    ):
        return _Scope()
    value = _ordinary_child(assignment.value, "value")
    if (
        value is None
        or not isinstance(value.value, Scalar)
        or value.value.quoted
        or re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)", value.value.text) is None
        or not isfinite(float(value.value.text))
    ):
        return _Scope()
    minimum_contract = minimum_context[0] if minimum_context else _subject_value_minimum(inputs)
    if minimum_contract is None or float(value.value.text) < minimum_contract[0]:
        return _Scope()
    # Duplicate definitions in any mounted source have unproved merge semantics.
    matches = 0
    for candidate, raw in inputs.items():
        if not candidate.endswith(".txt") or not (
            candidate.startswith("common/subject_types/") or "/common/subject_types/" in candidate
        ):
            continue
        parsed = parse_bytes(raw, path=candidate)
        if parsed.errors:
            return _Scope()
        matches += sum(item.key == definition.key for item in parsed.top_assignments)
    if matches != 1:
        return _Scope()
    source_raw = inputs.get(source)
    if source_raw is None:
        return _Scope()
    lines = source_raw.decode("utf-8-sig").splitlines()
    markers = (
        "# Multiplies both subject_value and become_subject_value in AI strategies",
        (
            "# Higher value means AI is more interested in having this type of subject "
            "but less interested in *being* this type of subject"
        ),
        "# Cannot return a value lower than MIN_SUBJECT_TYPE_VALUE",
    )
    start = assignment.line - len(markers) - 1
    if start < 0 or tuple(line.strip() for line in lines[start : assignment.line - 1]) != markers:
        return _Scope()
    return _Scope(
        "global",
        "none",
        "static_subject_type_value_multiplier",
        "indirect",
        (f"{source}:{start + 1}", minimum_contract[1]),
    )


def _scripted_trigger_definition_scope(inputs: dict[str, bytes]) -> _Scope:
    """官方注释中的定义/调用示例只证明源码定义观察，不证明 getter。"""
    source = "common/scripted_triggers/00_scripted_triggers.txt"
    raw = inputs.get(source)
    if raw is None:
        return _Scope(operation="read")
    parsed = parse_bytes(raw, path=source)
    comments = [(line, text.removeprefix("#").strip()) for line, text in parsed.comments]
    nonempty = [(line, text) for line, text in comments if text]
    template = (
        "Example:",
        "example_trigger = {",
        "x = 100",
        "y = 50",
        "}",
        "In a script file:",
        "effect = {",
        "example_trigger = yes",
        "}",
    )
    if parsed.errors or tuple(text for _, text in nonempty[: len(template)]) != template:
        return _Scope(operation="read")
    return _Scope(
        "caller_scope",
        "caller_derived",
        "read",
        "observation",
        (f"{source}:{nonempty[0][0]}",),
    )


def _ordinary_child(block: Block, key: str) -> Assignment | None:
    matches = block.all(key)
    if len(matches) != 1:
        return None
    assignment = matches[0]
    if assignment.op != "=" or assignment.prefix is not None:
        return None
    return assignment


def _declared_type_keys(inputs: dict[str, bytes], directory: str) -> frozenset[str]:
    result: set[str] = set()
    for source, raw in inputs.items():
        if not source.endswith(".txt") or not (
            source.startswith(f"common/{directory}/") or f"/common/{directory}/" in source
        ):
            continue
        parsed = parse_bytes(raw, path=source)
        if parsed.errors:
            return frozenset()
        result.update(
            item.key
            for item in parsed.top_assignments
            if not item.is_variable
            and item.op == "="
            and item.prefix is None
            and isinstance(item.value, Block)
        )
    return frozenset(result)


def _stance_definitions(inputs: dict[str, bytes]) -> dict[str, tuple[str, int]]:
    """Only pinned complete actual stance definitions may select pointer map entries."""
    data = json.loads(engine_scope.strategy_snapshot())
    sources = {
        source: raw
        for source, raw in inputs.items()
        if source.endswith(".txt") and "/common/ai_strategic_region_stance_types/" in "/" + source
    }
    if set(sources) != set(data["stance_definition_sources"]) or any(
        hashlib.sha256(raw).hexdigest() != data["stance_definition_sources"][source]
        for source, raw in sources.items()
    ):
        return {}
    definitions = _ordinary_definitions(sources, "ai_strategic_region_stance_types")
    expected = {
        key: (row["source"], row["line"]) for key, row in data["stance_definitions"].items()
    }
    return definitions if definitions == expected else {}


def _ordinary_definitions(inputs: dict[str, bytes], directory: str) -> dict[str, tuple[str, int]]:
    """Only unique ordinary actual definitions may identify institution map keys."""
    declarations: dict[str, list[tuple[str, Assignment]]] = {}
    for source, raw in inputs.items():
        if not source.endswith(".txt") or f"/common/{directory}/" not in "/" + source:
            continue
        parsed = parse_bytes(raw, path=source)
        if parsed.errors:
            return {}
        for item in parsed.top_assignments:
            if not item.is_variable:
                declarations.setdefault(item.key, []).append((source, item))
    return {
        key: (rows[0][0], rows[0][1].line)
        for key, rows in declarations.items()
        if len(rows) == 1
        and rows[0][1].op == "="
        and rows[0][1].prefix is None
        and isinstance(rows[0][1].value, Block)
    }


def _institution_definitions(inputs: dict[str, bytes]) -> dict[str, tuple[str, int]]:
    """Only unique ordinary actual definitions may identify institution map keys."""
    return _ordinary_definitions(inputs, "institutions")


def _institution_score_map(definition: Assignment, keys: frozenset[str]) -> Block | None:
    """A map selects definitions; only its ordinary numeric children are consumers."""
    if (
        definition.op != "="
        or definition.prefix is not None
        or not isinstance(definition.value, Block)
    ):
        return None
    scores = _ordinary_child(definition.value, "institution_scores")
    if scores is None or not isinstance(scores.value, Block):
        return None
    children = tuple(scores.value.assignments())
    if len(children) != len(scores.value.items) or len({child.key for child in children}) != len(
        children
    ):
        return None
    operations = {
        "value",
        "add",
        "subtract",
        "multiply",
        "divide",
        "min",
        "max",
        "round",
        "ceiling",
        "floor",
        "if",
        "else_if",
        "else",
        "desc",
    }
    for child in children:
        if (
            child.key not in keys
            or child.op != "="
            or child.prefix is not None
            or not isinstance(child.value, Block)
        ):
            return None
        expressions = tuple(child.value.assignments())
        if (
            not expressions
            or len(expressions) != len(child.value.items)
            or any(
                item.key not in operations or item.op != "=" or item.prefix is not None
                for item in expressions
            )
        ):
            return None
    return scores.value


def _strategy_score_map(definition: Assignment, field: str, keys: frozenset[str]) -> Block | None:
    """Validate exact enum elements; secret triggers stay native eligibility filters."""
    if (
        definition.op != "="
        or definition.prefix is not None
        or not isinstance(definition.value, Block)
    ):
        return None
    scores = _ordinary_child(definition.value, field)
    if scores is None or not isinstance(scores.value, Block):
        return None
    children = tuple(scores.value.assignments())
    if len(children) != len(scores.value.items) or len({item.key for item in children}) != len(
        children
    ):
        return None
    operations = {
        "value",
        "add",
        "subtract",
        "multiply",
        "divide",
        "min",
        "max",
        "round",
        "ceiling",
        "floor",
        "if",
        "else_if",
        "else",
        "desc",
    }
    for child in children:
        if (
            child.key not in keys
            or child.op != "="
            or child.prefix is not None
            or not isinstance(child.value, Block)
        ):
            return None
        numeric = child.value
        if field == "secret_goal_scores":
            members = tuple(numeric.assignments())
            if (
                len(members) != len(numeric.items)
                or len({item.key for item in members}) != len(members)
                or any(
                    item.key not in {"trigger", "score"}
                    or item.op != "="
                    or item.prefix is not None
                    or not isinstance(item.value, Block)
                    for item in members
                )
            ):
                return None
            score = _ordinary_child(numeric, "score")
            if score is None or not isinstance(score.value, Block):
                return None
            numeric = score.value
        expressions = tuple(numeric.assignments())
        if (
            not expressions
            or len(expressions) != len(numeric.items)
            or any(
                item.key not in operations or item.op != "=" or item.prefix is not None
                for item in expressions
            )
        ):
            return None
    return scores.value


def _company_construction_doc(inputs: dict[str, bytes]) -> _Scope:
    source = "common/company_types/companies.md"
    raw = inputs.get(source)
    if raw is None:
        return _Scope()
    parsed = parse_bytes(raw, path=source)
    comments = "\n".join(text for _, text in parsed.comments)
    if parsed.errors or not all(
        marker in comments
        for marker in (
            "increased weight for certain building types in certain states",
            "which states (determined through a trigger) and up to which level",
            "empty state trigger will do nothing",
        )
    ):
        return _Scope()
    # Check the actual documented parent/field shape as well as its prose;
    # unrelated field declarations or quoted copies cannot establish it.
    sample = _ordinary_child(parsed.root, "company_key")
    current = sample
    for key in ("ai_construction_targets", "building_iron_mine"):
        if current is None or not isinstance(current.value, Block):
            return _Scope()
        current = _ordinary_child(current.value, key)
    if current is None or not isinstance(current.value, Block):
        return _Scope()
    level = _ordinary_child(current.value, "level")
    trigger = _ordinary_child(current.value, "state_trigger")
    if (
        set(current.value.keys()) != {"level", "state_trigger"}
        or len(current.value.items) != 2
        or level is None
        or not isinstance(level.value, Scalar)
        or level.value.quoted
        or level.value.text != "5"
        or trigger is None
        or not isinstance(trigger.value, Block)
    ):
        return _Scope()
    state_region = _ordinary_child(trigger.value, "state_region")
    if (
        len(trigger.value.items) != 1
        or state_region is None
        or not isinstance(state_region.value, Scalar)
        or state_region.value.quoted
        or state_region.value.text != "s:STATE_NORRLAND"
    ):
        return _Scope()
    return _doc_scope(
        inputs,
        source,
        ("which states (determined through a trigger) and up to which level",),
        "global",
        "none",
        "construction_level_cap",
        "indirect",
    )


def _company_selection_doc(inputs: dict[str, bytes]) -> _Scope:
    source = "common/company_types/companies.md"
    raw = inputs.get(source)
    if raw is None:
        return _Scope()
    parsed = parse_bytes(raw, path=source)
    sample = _ordinary_child(parsed.root, "company_key")
    if parsed.errors or sample is None or not isinstance(sample.value, Block):
        return _Scope()
    field = _ordinary_child(sample.value, "ai_will_do")
    if field is None or not isinstance(field.value, Block) or field.value.items:
        return _Scope()
    lines = raw.decode("utf-8-sig").splitlines()
    comments: list[str] = []
    for line in lines[field.line :]:
        if line.strip() == "}":
            break
        if line.strip() and not line.lstrip().startswith("#"):
            return _Scope()
        comments.append(line)
    text = "\n".join(comments)
    if not all(
        marker in text
        for marker in (
            "If this trigger is true, then the AI will potentially select this company as the next company it will try to form.",
            "To check this trigger, the company must be considered at least 'attainable'",
            "If this trigger is not present, the AI never try to found this company",
        )
    ):
        return _Scope()
    # The operation is documented inside this field, but the scope comments
    # for potential/attainable/possible above it do not establish its actor.
    return _Scope("unknown", "unknown", "predicate", "pending", (f"{source}:{field.line}",))


def _company_construction_scope(
    field: tuple[str, ...],
    definition: Assignment,
    source: str,
    contract: tuple[frozenset[str], _Scope],
) -> _Scope:
    buildings, doc_scope = contract
    if (
        not doc_scope.evidence
        or definition.op != "="
        or definition.prefix is not None
        or not isinstance(definition.value, Block)
        or len(field) < 3
        or field[0] != "ai_construction_targets"
        or field[1] not in buildings
        or field[2] not in {"level", "state_trigger"}
    ):
        return _Scope()
    targets = _ordinary_child(definition.value, "ai_construction_targets")
    if targets is None or not isinstance(targets.value, Block):
        return _Scope()
    target = _ordinary_child(targets.value, field[1])
    if (
        target is None
        or not isinstance(target.value, Block)
        or len(targets.value.items) != len(tuple(targets.value.assignments()))
        or len(target.value.items) != 2
        or set(target.value.keys()) != {"level", "state_trigger"}
    ):
        return _Scope()
    level = _ordinary_child(target.value, "level")
    trigger = _ordinary_child(target.value, "state_trigger")
    if (
        level is None
        or not isinstance(level.value, Scalar)
        or level.value.quoted
        or re.fullmatch(r"[0-9]+", level.value.text) is None
        or int(level.value.text) <= 0
        or trigger is None
        or not isinstance(trigger.value, Block)
        or len(trigger.value.items) != len(tuple(trigger.value.assignments()))
    ):
        return _Scope()
    if field[2] == "level":
        return doc_scope if len(field) == 3 else _Scope()
    # No outer actor/target is documented for state_trigger itself. Only
    # descendants are classified as observations of its source expression.
    if len(field) == 3:
        return _Scope()
    current = trigger
    for key in field[3:]:
        if not isinstance(current.value, Block):
            return _Scope()
        matches = current.value.all(key)
        if len(matches) != 1 or matches[0].prefix is not None:
            return _Scope()
        current = matches[0]
    return _Scope(
        "parent_field_scope",
        "parent_derived",
        "read",
        "observation",
        tuple(
            dict.fromkeys(
                (*doc_scope.evidence, f"{source}:{trigger.line}", f"{source}:{current.line}")
            )
        ),
        ".".join(field[:3]),
        trigger.line,
    )


def _static_building_group_map(definition: Assignment, groups: frozenset[str]) -> Block | None:
    if (
        definition.op != "="
        or definition.prefix is not None
        or not isinstance(definition.value, Block)
    ):
        return None
    assignment = _ordinary_child(definition.value, "building_group_weights")
    if (
        assignment is None
        or not isinstance(assignment.value, Block)
        or not assignment.value.items
        or len(assignment.value.items) != len(tuple(assignment.value.assignments()))
    ):
        return None
    block = assignment.value
    keys = block.keys()
    if len(keys) != len(set(keys)):
        return None
    for child in block.assignments():
        if (
            child.key not in groups
            or child.op != "="
            or child.prefix is not None
            or not isinstance(child.value, Scalar)
            or child.value.quoted
            or re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", child.value.text) is None
            or not isfinite(float(child.value.text))
            or float(child.value.text) <= 0
        ):
            return None
    return block


def _building_group_weight_doc(inputs: dict[str, bytes], groups: frozenset[str]) -> _Scope:
    source = "common/ai_strategies/00_default_strategy.txt"
    raw = inputs.get(source)
    if raw is None:
        return _Scope()
    parsed = parse_bytes(raw, path=source)
    definition = _ordinary_child(parsed.root, "ai_strategy_default")
    if (
        parsed.errors
        or definition is None
        or _static_building_group_map(definition, groups) is None
    ):
        return _Scope()
    assert isinstance(definition.value, Block)
    assignment = definition.value.first("building_group_weights")
    assert assignment is not None
    lines = raw.decode("utf-8-sig").splitlines()
    comments: list[str] = []
    for line in reversed(lines[: assignment.line - 1]):
        if line.strip() and not line.lstrip().startswith("#"):
            break
        comments.append(line)
    text = "\n".join(comments)
    if not all(
        marker in text
        for marker in (
            "Add a multiplier to the score AI assigns to particular building groups (default 1)",
            "Using this value in other strategies will result in several multiplications",
        )
    ):
        return _Scope()
    return _Scope(
        "global",
        "none",
        "building_group_score_multiplier",
        "indirect",
        (f"{source}:{assignment.line}",),
    )


def _static_interest_group_list(
    definition: Assignment, field: str, groups: frozenset[str]
) -> Block | None:
    if (
        definition.op != "="
        or definition.prefix is not None
        or not isinstance(definition.value, Block)
    ):
        return None
    assignment = _ordinary_child(definition.value, field)
    if assignment is None or not isinstance(assignment.value, Block):
        return None
    block = assignment.value
    if any(
        not isinstance(item, Scalar) or item.quoted or item.text not in groups
        for item in block.items
    ):
        return None
    keys = [item.text for item in block.scalars()]
    return block if len(keys) == len(set(keys)) else None


def _interest_group_list_docs(
    inputs: dict[str, bytes], groups: frozenset[str]
) -> dict[str, _Scope]:
    source = "common/ai_strategies/00_default_strategy.txt"
    raw = inputs.get(source)
    if raw is None:
        return {}
    parsed = parse_bytes(raw, path=source)
    definition = _ordinary_child(parsed.root, "ai_strategy_default")
    if parsed.errors or definition is None or not isinstance(definition.value, Block):
        return {}
    lines = raw.decode("utf-8-sig").splitlines()
    result: dict[str, _Scope] = {}
    for field, description, operation in (
        (
            "pro_interest_groups",
            "Which IGs should the AI try to put in power",
            "preferred_government_interest_groups",
        ),
        (
            "anti_interest_groups",
            "Which IGs should the AI try to avoid putting in power",
            "avoided_government_interest_groups",
        ),
    ):
        if _static_interest_group_list(definition, field, groups) is None:
            continue
        assignment = definition.value.first(field)
        assert assignment is not None
        comments: list[str] = []
        for line in reversed(lines[: assignment.line - 1]):
            if line.strip() and not line.lstrip().startswith("#"):
                break
            comments.append(line)
        text = "\n".join(comments)
        if not all(
            marker in text
            for marker in (
                description,
                "Using this value in other strategies will function additively",
            )
        ):
            continue
        result[field] = _Scope(
            "global", "none", operation, "indirect", (f"{source}:{assignment.line}",)
        )
    return result


def _treaty_scope(
    field: tuple[str, ...], inputs: dict[str, bytes], definition: Assignment, source: str
) -> _Scope:
    if len(field) != 2 or field[0] != "ai" or not isinstance(definition.value, Block):
        return _Scope()
    name = field[1]
    doc = "common/treaty_articles/treaty_articles.md"
    if name == "evaluation_chance":
        return _doc_scope(
            inputs,
            doc,
            ("Only has root scope for the country we're looking at.",),
            "country",
            "none",
            "proposal_score",
            section="evaluation_chance",
        )
    input_types = {
        "goods": "goods",
        "state": "state",
        "strategic_region": "strategic_region",
        "company": "company",
        "building_type": "building_type",
        "law_type": "law_type",
        "country": "country",
        "ship": "ship",
    }
    input_type = input_types.get(name.removesuffix("_input_filter"))
    if name.endswith("_input_filter") and input_type is not None:
        markers: tuple[str, ...] = (
            "- `root`: Source country for the article",
            "- `scope:article`: the article in question.",
            "- `scope:input`: the specific input we're looking at right now.",
            "- `scope:other_country`: the other country that isn't the root",
        )
        target = f"scope:article=article;scope:input={input_type};scope:other_country=country"
        if input_type == "goods":
            markers += (
                "- `scope:goods`: the goods input we're looking at",
                "- `scope:market_goods`: the same goods, but as a market goods for the source country market",
            )
            target += ";scope:goods=goods;scope:market_goods=market_goods"
        # The sample must declare this field too; a new input type does not
        # inherit the generic context simply because its name looks familiar.
        declaration = _doc_scope(inputs, doc, (f"{name} = {{}}",), "country", target, "predicate")
        if not declaration.evidence:
            return _Scope()
        scope = _doc_scope(
            inputs, doc, markers, "country", target, "predicate", section="input_filters"
        )
        return (
            replace(scope, evidence=(*scope.evidence, *declaration.evidence))
            if scope.evidence
            else scope
        )
    if name == "quantity_input_value":
        return _doc_scope(
            inputs,
            doc,
            (
                "- `root`: the source country (or first if relevant)",
                "- `scope:other_country`: the other country that isn't the root",
                "- `scope:article`: the article in question.",
            ),
            "country",
            "scope:article=article;scope:other_country=country",
            "value",
            section="Quantity script value",
        )
    if name == "proposal_weight":
        return _doc_scope(
            inputs,
            doc,
            ("proposal_weight = { script value }", "root is composing AI country"),
            "country",
            "none",
            "proposal_score",
        )
    if name in {"treaty_categories", "article_ai_usage"}:
        # These are static AI article metadata values. The official contract
        # defines their vocabulary but no nested script scope.
        return _doc_scope(
            inputs,
            doc,
            (f"{name} = {{",),
            "global",
            "none",
            "ai_metadata",
            "observation",
        )
    if name in {"combined_acceptance_cap_max", "combined_acceptance_cap_min"}:
        return _doc_scope(
            inputs,
            doc,
            (f"{name} = value",),
            "global",
            "none",
            "acceptance_cap",
            "observation",
        )
    if name not in {"inherent_accept_score", "contextual_accept_score", "wargoal_score_multiplier"}:
        return _Scope()
    kinds = definition.value.all("kind")
    if len(kinds) != 1 or not isinstance(kinds[0].value, Scalar):
        return _Scope()
    kind = kinds[0].value.unquoted
    if kind not in {"mutual", "directed"}:
        return _Scope()
    target = "scope:article=article"
    markers = (
        "ONLY for mutual articles:",
        "- `scope:first_country` is one of the parties",
        "- `scope:second_country` is the other party",
        "ONLY for directed articles:",
        "- `scope:source_country` is the specific party",
        "- `scope:target_country` is the specific party",
    )
    if kind == "mutual":
        target += ";scope:first_country=country;scope:second_country=country"
    else:
        target += ";scope:source_country=country;scope:target_country=country"
    if name == "wargoal_score_multiplier":
        markers += (
            "- `root` - the country we're looking at",
            "- `scope:article` refers to the article that is being enforced",
        )
        operation = "wargoal_multiplier"
    else:
        markers += (
            "- `root`: The country we're looking to check the acceptance on",
            "- `scope:article`: The article in question with whatever inputs it might have",
        )
        operation = "acceptance_score"
        if name == "contextual_accept_score":
            markers += ("- `scope:treaty`: The current treaty with any articles",)
            target += ";scope:treaty=treaty"
        else:
            markers += ("There is no `scope:treaty` here",)
    scope = _doc_scope(inputs, doc, markers, "country", target, operation, section=name)
    return (
        replace(scope, evidence=(*scope.evidence, f"{source}:{kinds[0].line}"))
        if scope.evidence
        else scope
    )


def _strategy_scopes(inputs: dict[str, bytes]) -> dict[str, _Scope]:
    source = "common/ai_strategies/00_default_strategy.txt"
    raw = inputs.get(source)
    if raw is None:
        return {}
    parsed = parse_bytes(raw, path=source)
    if parsed.errors:
        raise ValueError(f"原版解析失败：{source}: {'; '.join(parsed.errors)}")
    lines = raw.decode("utf-8-sig").splitlines()
    scopes: dict[str, _Scope] = {}
    # The default file is a source of field-level documentation, not proof
    # that every child is an additive country score. Enums, metadata and
    # future fields stay pending until an explicit contract is added here.
    specs = {
        "will_incorporate_state": (
            "root = country",
            "scope:target_state = the state being considered",
            "scope:target_state=state",
        ),
        "state_value": (
            "scope:target_state = state",
            "scope:target_country = state owner",
            "scope:target_state=state;scope:target_country=country",
        ),
        "treaty_port_value": (
            "scope:target_state = state",
            "scope:target_country = state owner",
            "scope:target_state=state;scope:target_country=country",
        ),
        "interest_group_government_weight": (
            "root = country",
            "scope:interest_group = IG",
            "scope:interest_group=interest_group",
        ),
        "negotiation_chance": (
            "root = country",
            "scope:law = law type being enacted",
            "scope:law=law;scope:interest_group=interest_group",
        ),
        "ai_ship_category_weights": ("root = country", "function additively", "none"),
        "combat_unit_group_weights": (
            "root = country",
            "scope:military_formation = military formation",
            "scope:military_formation=military_formation",
        ),
        "conscript_battalion_ratio": (
            "root = country",
            "scope:military_formation = military formation",
            "scope:military_formation=military_formation",
        ),
        "diplomatic_play_support": (
            "root = supporting country",
            "scope:country = country",
            "scope:country=country;scope:enemy_country=country",
        ),
        "subject_value": (
            "root is the AI doing the evaluation",
            "scope:target_country is prospective subject",
            "scope:target_country=country",
        ),
        "become_subject_value": (
            "root is the AI doing the evaluation",
            "scope:overlord is prospective overlord",
            "scope:overlord=country",
        ),
        "liberate_country_scores": (
            "root = liberator",
            "scope:target = oppressor",
            "scope:target=country",
        ),
        "strait_scores": (
            "root = country",
            "scope:strait = the strait",
            (
                "scope:strait=strait;scope:first_state=state;"
                "scope:second_state=state;scope:is_sole_controller=bool"
            ),
        ),
    }
    for definition in parsed.top_assignments:
        if definition.key != "ai_strategy_default" or not isinstance(definition.value, Block):
            continue
        for assignment in definition.value.assignments():
            spec = specs.get(assignment.key)
            comments: list[str] = []
            for line in reversed(lines[: assignment.line - 1]):
                if line.strip() and not line.lstrip().startswith("#"):
                    break
                comments.append(line)
            text = "\n".join(reversed(comments))
            if spec is None:
                if (
                    assignment.key == "wargoal_scores"
                    and definition.op == assignment.op == "="
                    and definition.prefix is assignment.prefix is None
                    and len(definition.value.all("wargoal_scores")) == 1
                    and isinstance(assignment.value, Block)
                    and all(
                        marker in text
                        for marker in (
                            "How much should the AI value a wargoal against another country/state",
                            "Using this value in other strategies will function additively",
                            "scope:target_country = wargoal target country",
                            "scope:target_state = wargoal target state (if any)",
                            "scope:diplomatic_play = the diplomatic play (if there is one)",
                        )
                    )
                ):
                    scopes[assignment.key] = _Scope(
                        "unknown",
                        "scope:target_country=country;scope:target_state=state(optional);"
                        "scope:diplomatic_play=diplomatic_play(optional)",
                        "additive_score",
                        "pending",
                        (f"{source}:{assignment.line}",),
                    )
                    continue
                # A field-level merge description is useful evidence about
                # the operation, but it does not establish the evaluation
                # actor or target. Keep those dimensions unknown and retain
                # the surface as pending instead of promoting a strategy
                # container's country context to every child field.
                operation = None
                if "Using this value in other strategies will function additively" in text:
                    operation = "additive_score"
                elif "Using this value in other strategies will function multiplicatively" in text:
                    operation = "multiplicative_score"
                elif "Using a different value in a strategy will override" in text:
                    operation = "override_value"
                if operation is not None:
                    scopes[assignment.key] = _Scope(
                        "unknown",
                        "unknown",
                        operation,
                        "pending",
                        (f"{source}:{assignment.line}",),
                    )
                continue
            if assignment.key == "will_incorporate_state":
                if (
                    "root = country" in text
                    and "scope:target_state = the state being considered" in text
                    and "trigger" in text
                ):
                    scopes[assignment.key] = _Scope(
                        "country",
                        "scope:target_state=state",
                        "predicate",
                        "direct",
                        (f"{source}:{assignment.line}",),
                    )
                continue
            if (
                assignment.key in {"state_value", "treaty_port_value"}
                and "root = country" not in text
            ):
                continue
            if assignment.key == "diplomatic_play_support" and (
                "scope:enemy_country = the opposing side's leader" not in text
            ):
                continue
            if assignment.key == "strait_scores" and not all(
                marker in text
                for marker in (
                    "scope:first_state = the first state controlling the strait",
                    "scope:second_state = the second state controlling the strait",
                    "scope:is_sole_controller = yes/no",
                )
            ):
                continue
            if spec[0] in text and spec[1] in text and "function additively" in text:
                scopes[assignment.key] = _Scope(
                    "country", spec[2], "additive_score", "direct", (f"{source}:{assignment.line}",)
                )

        # ``fleet_compositions`` is a nested strategy surface.  Its header
        # documents a different contract from the top-level strategy maps:
        # numeric values are evaluated from country scope, mission weights
        # are multipliers, and ``potential`` is a country-scoped predicate.
        # Keep this deliberately narrow.  The header does not document every
        # other strategy field, nor does it prove that these values are
        # additive across strategies.
        fleet = next(
            (
                item
                for item in definition.value.assignments()
                if item.key == "fleet_compositions" and isinstance(item.value, Block)
            ),
            None,
        )
        if fleet is None:
            continue
        fleet_comments: list[str] = []
        for line in reversed(lines[: fleet.line - 1]):
            if line.strip() and not line.lstrip().startswith("#"):
                break
            fleet_comments.append(line)
        text = "\n".join(reversed(fleet_comments))
        numeric_scope = (
            "All numeric fields accept script values, so weights can be tuned from country scope."
        )
        contracts = {
            "ai_ship_category_weights": (
                "relative_allocation_weight",
                (numeric_scope, "# ai_ship_category_weights:", "weights are summed per category"),
            ),
            "mission_type_weights": (
                "multiplicative_score",
                (
                    numeric_scope,
                    "# mission_type_weights:",
                    "Multiplier applied when a fleet in this role picks which mission to pursue.",
                    "1.0 is",
                    "0.0 disables it for this role",
                    "any mission type not listed is treated as 0",
                    "Omit the whole block to leave every",
                ),
            ),
            "min_ships_wanted": (
                "soft_floor",
                (
                    numeric_scope,
                    "# min_ships_wanted:",
                    "Soft floor on fleet size used during role-fit scoring.",
                ),
            ),
            "num_fleets_wanted": (
                "fleet_count",
                (
                    "# num_fleets_wanted:",
                    "How many fleets should take this role. Omitted means one. Evaluated in country scope",
                    "a value of 0 drops the role for that country",
                ),
            ),
            "potential": (
                "predicate",
                (
                    "# potential:",
                    "Country-scoped trigger. If it fails the role is dropped entirely",
                ),
            ),
        }
        for path, _child in _frontier(fleet, ("fleet_compositions",)):
            if len(path) < 3:
                continue
            kind = path[2]
            contract = contracts.get(kind)
            if contract is None:
                continue
            operation, markers = contract
            expected_depth = (
                4 if kind in {"ai_ship_category_weights", "mission_type_weights"} else 3
            )
            if len(path) != expected_depth or not all(marker in text for marker in markers):
                continue
            evidence = tuple(
                f"{source}:{fleet.line - len(fleet_comments) + text[: text.index(marker)].count(chr(10))}"
                for marker in markers
            )
            scopes[".".join(path)] = _Scope("country", "none", operation, "direct", evidence)
    return scopes


def _decision_chance_scope(inputs: dict[str, bytes]) -> _Scope:
    source = "common/decisions/000_decisions_help.txt"
    raw = inputs.get(source)
    if raw is None:
        return _Scope()
    text = raw.decode("utf-8-sig")
    # The country-scope introduction does not prove every adjacent AI field.
    # Require the named field's own section, including its selection and zero
    # semantics; comments in another section cannot complete this contract.
    section = re.search(
        r"^# `ai_chance` value[ \t]*\r?\n#+[ \t]*\r?\n(?P<body>.*?)(?=^#{3,}|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if section is None:
        return _Scope()
    markers = (
        (
            "The scripted weight which determines how likely AI is to take it amongst all "
            "possible decisions (country scope)."
        ),
        "If it evaluates to 0, AI will not take the decision. Evaluates to 1 if unspecified",
    )
    body = section.group("body")
    if not all(marker in body for marker in markers):
        return _Scope()
    offsets = (section.start(), *(section.start("body") + body.index(marker) for marker in markers))
    lines = (text[:offset].count("\n") + 1 for offset in offsets)
    evidence = tuple(f"{source}:{line}" for line in lines)
    return _Scope("country", "none", "chance", "direct", evidence)


def _ship_modification_formula_doc(inputs: dict[str, bytes]) -> _Scope:
    """Prove the shared formula once, without promoting unrelated fields."""
    documented = _doc_scope(
        inputs,
        "common/ship_modifications/ship_modifications.md",
        (
            "How important is this ship type to build for AI",
            "root - country",
            "ai_weight = fixed_point",
        ),
        "country",
        "unknown",
        "score",
        "pending",
    )
    if not documented.evidence:
        return documented
    helper_name = "ship_mod_market_multiplier"
    helper_source = "common/script_values/ai_script_values.txt"
    raw = inputs.get(helper_source)
    if raw is None:
        return documented
    parsed = parse_bytes(raw, path=helper_source)
    if parsed.errors:
        return documented
    helpers = [
        item
        for item in parsed.top_assignments
        if item.key == helper_name
        and item.op == "="
        and item.prefix is None
        and isinstance(item.value, Block)
    ]
    if len(helpers) != 1:
        return documented
    helper_value = helpers[0].value
    assert isinstance(helper_value, Block)
    # Formula assignments execute in order. The native helper reads a ratio,
    # saves it, then legitimately resets value to 1 before applying a curve.
    formula = helper_value.first("value")
    if (
        formula is None
        or formula.op != "="
        or formula.prefix is not None
        or not isinstance(formula.value, Scalar)
        or not formula.value.quoted
        or formula.value.unquoted
        != "ship_modification_market_demand_ratio(scope:ship_modification_type)"
    ):
        return documented

    formula_scope = _doc_scope(
        inputs,
        "common/script_values/script_values.md",
        ("# Formulas", "the scope you're currently in"),
        "unknown",
        "unknown",
        "formula_scope",
        "observation",
    )
    if not formula_scope.evidence:
        return documented

    return _Scope(
        "country",
        "scope:ship_modification_type=ship_modification",
        "score",
        "direct",
        (
            *documented.evidence,
            f"{helper_source}:{formula.line}",
            *formula_scope.evidence,
        ),
    )


def _ship_modification_scope(
    inputs: dict[str, bytes],
    definition: Assignment,
    source: str,
    formula_doc: _Scope | None = None,
) -> _Scope:
    """Only fields that actually call the proven formula inherit its target."""
    documented = formula_doc if formula_doc is not None else _ship_modification_formula_doc(inputs)
    pending = replace(documented, target="unknown", capability="pending")
    if (
        documented.capability != "direct"
        or definition.op != "="
        or definition.prefix is not None
        or not isinstance(definition.value, Block)
    ):
        return pending
    weight = _ordinary_child(definition.value, "ai_weight")
    if weight is None or not isinstance(weight.value, Block):
        return pending
    multipliers = weight.value.all("multiply")
    market_multipliers = [
        item
        for item in multipliers
        if item.op == "="
        and item.prefix is None
        and isinstance(item.value, Scalar)
        and not item.value.quoted
        and item.value.text == "ship_mod_market_multiplier"
    ]
    if len(market_multipliers) != 1:
        return pending
    return replace(documented, evidence=(*documented.evidence, f"{source}:{weight.line}"))


def _scope(
    directory: str,
    field: tuple[str, ...],
    inputs: dict[str, bytes],
    strategies: dict[str, _Scope],
    definition: Assignment,
    source: str,
    company_construction: tuple[frozenset[str], _Scope] | None = None,
    strategy_building_groups: tuple[frozenset[str], _Scope] | None = None,
    strategy_interest_groups: tuple[frozenset[str], dict[str, _Scope]] | None = None,
    company_selection: _Scope | None = None,
    ship_modification_formula: _Scope | None = None,
    subject_value_minimum: tuple[tuple[float, str] | None, ...] = (),
    technology_proof: engine_scope.TechnologyScopeEvidence | None = None,
    strategy_proof: engine_scope.StrategyScopeEvidence | None = None,
    country_proof: engine_scope.CountryScopeEvidence | None = None,
    company_proof: engine_scope.CompanyScopeEvidence | None = None,
    law_proof: engine_scope.LawScopeEvidence | None = None,
) -> _Scope:
    # 这些消费者的作用域不是由字段名猜出来的，而是由锁定原版随附的
    # ``*.md`` 规范明确给出。把规范证据集中在这里，避免把同一条
    # actor/target 结论复制到多个扫描器；如果底本缺少对应文档，则保持
    # pending，不能因为当前文件恰好有 ``ai_*`` 字段就放行。
    if directory == "laws" and field == ("ai_will_do",):
        if (
            law_proof is None
            or not law_proof.verified
            or source not in law_proof.sources
            or definition.op != "="
            or definition.prefix is not None
            or not isinstance(definition.value, Block)
            or (child := _ordinary_child(definition.value, "ai_will_do")) is None
            or not isinstance(child.value, Block)
        ):
            return _Scope()
        return _Scope(
            "country",
            "definition_only:law_type",
            "eligibility",
            "direct",
            (*law_proof.references, f"{source}:{definition.line}"),
        )
    if directory in {"country_creation", "country_formation"} and field == ("ai_will_do",):
        if (
            country_proof is None
            or not country_proof.verified
            or source not in country_proof.sources
            or not source.startswith(f"common/{directory}/")
            or definition.op != "="
            or definition.prefix is not None
            or not isinstance(definition.value, Block)
            or _ordinary_child(definition.value, "ai_will_do") is None
        ):
            return _Scope()
        consumer = "0x14153796b" if directory == "country_creation" else "0x14153755d"
        return _Scope(
            "country",
            f"definition_only:{directory}",
            "eligibility",
            "direct",
            (
                *country_proof.references,
                f"@engine/binaries/victoria3.exe:{consumer}",
                f"{source}:{definition.line}",
            ),
        )
    if directory == "technology" and field == ("ai_weight",):
        if (
            technology_proof is None
            or not technology_proof.verified
            or source not in technology_proof.technology_sources
            or definition.op != "="
            or definition.prefix is not None
            or not isinstance(definition.value, Block)
            or _ordinary_child(definition.value, "ai_weight") is None
        ):
            return _Scope()
        return _Scope(
            "country",
            "definition_only:technology",
            "base_candidate_score",
            "direct",
            (*technology_proof.references, f"{source}:{definition.line}"),
        )
    if (directory, field) in {
        ("production_method_groups", ("ai_selection",)),
        ("ai_regional_objectives", ("stances",)),
        ("war_goal_types", ("ai", "settles_grievance")),
        ("war_goal_types", ("ai", "is_significant_demand")),
    }:
        return _static_policy_scope(directory, field, inputs, definition)
    if directory == "subject_types" and field == ("ai_value",):
        return _static_subject_value_scope(inputs, definition, source, subject_value_minimum)
    if directory == "decrees" and field == ("ai_weight",):
        if source != "common/decrees/00_decree.txt" or definition.key != "decree_emergency_relief":
            return _Scope()
        raw = inputs.get(source)
        if (
            raw is None
            or hashlib.sha256(normalized_text(raw.decode("utf-8-sig")).encode()).hexdigest()
            != "c0d0ca00271ae9a69a1119122e3392e74040f88c7097ddc5e357654d7a40e883"
        ):
            return _Scope()
        # Full source identity plus explicit field-local state/AI comments;
        # no company/research fallback or family-wide decree authorization.
        return _doc_scope(
            inputs,
            source,
            ("state_trigger", "ai_weight"),
            "state",
            "none",
            "relative_weight",
            "direct",
        )
    if directory == "decisions" and field == ("ai_chance",):
        return _decision_chance_scope(inputs)
    if directory == "ai_strategies" and field[0] in {"pro_interest_groups", "anti_interest_groups"}:
        interest_contract = strategy_interest_groups
        if interest_contract is None:
            groups = _declared_type_keys(inputs, "interest_groups")
            interest_contract = (groups, _interest_group_list_docs(inputs, groups))
        groups, interest_docs = interest_contract
        if len(field) != 1 or _static_interest_group_list(definition, field[0], groups) is None:
            return _Scope()
        return interest_docs.get(field[0], _Scope())
    if directory == "ai_strategies" and field[0] == "building_group_weights":
        group_contract = strategy_building_groups
        if group_contract is None:
            groups = _declared_type_keys(inputs, "building_groups")
            group_contract = (groups, _building_group_weight_doc(inputs, groups))
        groups, group_doc = group_contract
        if len(field) != 2 or not group_doc.evidence:
            return _Scope()
        block = _static_building_group_map(definition, groups)
        return group_doc if block is not None and block.first(field[1]) is not None else _Scope()
    if directory == "company_types":
        if (
            field in {("ai_will_do",), ("ai_weight",)}
            and company_proof is not None
            and company_proof.verified
            and source in company_proof.sources
            and source.startswith("common/company_types/")
            and definition.op == "="
            and definition.prefix is None
            and isinstance(definition.value, Block)
        ):
            child = _ordinary_child(definition.value, field[0])
            if child is not None and isinstance(child.value, Block):
                consumer = "0x1415c9837" if field == ("ai_will_do",) else "0x1415c9855"
                return _Scope(
                    "country",
                    "definition_only:company_type",
                    "eligibility" if field == ("ai_will_do",) else "base_candidate_score",
                    "direct",
                    (
                        *company_proof.references,
                        f"@engine/binaries/victoria3.exe:{consumer}",
                        f"{source}:{definition.line}",
                    ),
                )
        if field == ("ai_will_do",):
            if (
                definition.op != "="
                or definition.prefix is not None
                or not isinstance(definition.value, Block)
            ):
                return _Scope()
            selection = _ordinary_child(definition.value, "ai_will_do")
            if selection is None or not isinstance(selection.value, Block):
                return _Scope()
            return (
                company_selection
                if company_selection is not None
                else _company_selection_doc(inputs)
            )
        if field[0] == "ai_construction_targets":
            construction_contract = company_construction
            if construction_contract is None:
                construction_contract = (
                    _declared_type_keys(inputs, "buildings"),
                    _company_construction_doc(inputs),
                )
            return _company_construction_scope(field, definition, source, construction_contract)
        # The companies guide gives country scope only for the three
        # visibility triggers.  The adjacent AI fields describe behaviour but
        # do not provide a field-level root/target contract; keep them
        # discoverable and pending instead of inheriting the nearest scope.
        if field in {("potential",), ("attainable",), ("possible",)}:
            return _doc_scope(
                inputs,
                "common/company_types/companies.md",
                (
                    f"{field[0]} = {{",
                    "evaluated in country scope",
                ),
                "country",
                "none",
                "predicate",
                "direct",
            )
        if field == ("can_establish_in",):
            return _doc_scope(
                inputs,
                "common/company_types/companies.md",
                (
                    "can_establish_in = {",
                    "evaluated in state scope",
                ),
                "state",
                "none",
                "predicate",
                "direct",
            )
    if directory == "company_charter_types" and field == ("possible",):
        return _doc_scope(
            inputs,
            "common/company_charter_types/company_charter_types.md",
            (
                "possible = {}",
                "evaluated in company scope",
            ),
            "company",
            "none",
            "predicate",
            "direct",
        )
    if directory == "company_charter_types" and field in {
        ("ai_possible",),
        ("ai_weight",),
    }:
        # The template names these as AI selection inputs and describes their
        # operation, but does not document the evaluation actor/target. Do not
        # inherit the adjacent `possible` field's company scope.
        operation, marker = (
            ("predicate", "ai_possible = {} # If this charter is possible to be picked up by AI")
            if field == ("ai_possible",)
            else (
                "relative_weight",
                "ai_weight = {} # Check score for AI to pickup charter, will be scaled by company relative size to other companies",
            )
        )
        return _doc_scope(
            inputs,
            "common/company_charter_types/company_charter_types.md",
            (marker,),
            "unknown",
            "unknown",
            operation,
            "pending",
        )
    if directory == "amendments" and field == ("would_sponsor",):
        return _doc_scope(
            inputs,
            "common/amendments/amendments.md",
            (
                "would_sponsor = {}",
                "root = interest group",
                "scope:approval = IG approval for parent law",
            ),
            "interest_group",
            "scope:approval=approval",
            "predicate",
            "direct",
        )
    if directory == "war_goal_types":
        docs = "common/war_goal_types/war_goal_types.md"
        target = (
            "scope:creator_country=country;scope:target_country=country;"
            "scope:target_state=state;scope:target_region=strategic_region;"
            "scope:stakeholder=country;scope:article_options=article_options"
        )
        if field in {("possible",), ("valid",)}:
            return _doc_scope(
                inputs,
                docs,
                (f"{field[0]} = {{", "scopes: root = holder, creator_country, diplomatic_play"),
                "country",
                target,
                "predicate",
                "indirect",
            )
        if field in {("maneuvers",), ("infamy",), ("impact_mult",)}:
            return _doc_scope(
                inputs,
                docs,
                (f"{field[0]} = {{", "scopes: root = holder, creator_country, diplomatic_play"),
                "country",
                target,
                "value",
                "indirect",
            )
        if field == ("on_enforced",):
            return _doc_scope(
                inputs,
                docs,
                ("on_enforced = {", "scopes: root = holder, creator_country, diplomatic_play"),
                "country",
                target,
                "effect",
                "indirect",
            )
        # The ``ai`` block is static metadata.  The nearby Triggers and
        # Effect scope list belongs to possible/valid/value/effect fields and
        # cannot be transferred to these flags.
    if directory == "modifier_type_definitions" and field == ("game_data", "ai_value"):
        # ``game_data.ai_value`` is a modifier-type metadata hook. It is an
        # indirect engine consumer and has no script actor/target of its own;
        # the official description explicitly limits it to code-side AI
        # handling. Treating it as a global metadata surface is precise and
        # prevents it from being mistaken for a country script getter.
        return _doc_scope(
            inputs,
            "common/modifier_type_definitions/modifier_types.md",
            ("game_data={", "the value to the AI of having this modifier"),
            "global",
            "none",
            "modifier_ai_value",
            "indirect",
        )
    if directory == "scripted_buttons" and field == ("ai_chance",):
        return _doc_scope(
            inputs,
            "common/scripted_buttons/scripted_buttons.md",
            ("#Country scope", "ai_chance = {"),
            "country",
            "none",
            "chance",
        )
    if directory == "ai_strategic_region_stance_types":
        # These are static AI stance capabilities. The official definition
        # documents no script actor or target, so record them as indirect
        # global consumers instead of guessing a country scope.
        if field == ("can_send_fleets",):
            return _doc_scope(
                inputs,
                "common/ai_strategic_region_stance_types/ai_strategic_region_stance_types.md",
                ("can_send_fleets = <yes/no>",),
                "global",
                "none",
                "stance_capability",
                "observation",
            )
        if field == ("add_diplomatic_relevance",):
            return _doc_scope(
                inputs,
                "common/ai_strategic_region_stance_types/ai_strategic_region_stance_types.md",
                ("add_diplomatic_relevance = <yes/no>",),
                "global",
                "none",
                "stance_capability",
                "indirect",
            )
    if directory == "ship_modifications" and field == ("ai_weight",):
        return _ship_modification_scope(inputs, definition, source, ship_modification_formula)
    if directory == "naval_mission_types" and field in {
        ("ai_will_do",),
        ("ai_weight",),
    }:
        # The shipped template defines the selection predicate and relative
        # weight semantics, but gives no evaluation scope for either field.
        # Keep both actor and target unknown; the per-field operation evidence
        # is still useful for the D0 scope ledger.
        operation, marker = (
            ("predicate", "ai_will_do = {} # Trigger to enable/disable this for ai")
            if field == ("ai_will_do",)
            else (
                "relative_weight",
                "# Used after AI has decided what type of mission behavior it wants what mission to pick",
            )
        )
        return _doc_scope(
            inputs,
            "common/naval_mission_types/naval_mission_types.md",
            (marker,),
            "unknown",
            "unknown",
            operation,
            "pending",
        )
    if directory == "diplomatic_plays" and field == ("ai_acceptance_max",):
        return _doc_scope(
            inputs,
            "common/diplomatic_plays/diplomatic_plays.md",
            ("ai_acceptance_max = num", "upper bound for AI acceptance"),
            "global",
            "none",
            "acceptance_cap",
            "observation",
        )
    if directory == "diplomatic_catalysts" and field == ("ai_country_goal_recalculation",):
        return _doc_scope(
            inputs,
            "common/diplomatic_catalysts/diplomatic_catalysts.md",
            (
                "ai_country_goal_recalculation = {",
                "root = the country the catalyst was triggered for",
                "scope:target_country = the country the catayst was triggered by",
            ),
            "country",
            "scope:target_country=country",
            "goal_recalculation",
            "indirect",
        )
    if directory == "ship_types" and field == ("ai_ship_category",):
        return _doc_scope(
            inputs,
            "common/ship_types/ship_types.md",
            (
                "ai_ship_category = <ai ship category key>",
                "AI-only category",
                "used by the AI",
            ),
            "global",
            "none",
            "ai_metadata",
            "observation",
        )
    if directory == "character_interactions" and field[0] in {
        "ai_chance",
        "ai_will_do",
        "ai_considers_exiles",
    }:
        return _doc_scope(
            inputs,
            "common/character_interactions/00_character_interactions.txt",
            ("All scopes are character scopes with the interacting country stored as the actor",),
            "character",
            "scope:actor=country",
            "chance" if field[0] == "ai_chance" else "predicate",
        )
    # The naval mission fields are absent from its shipped AI template.
    # War-goal AI flags are static metadata; the separate "Triggers and
    # Effect" scope section does not establish their evaluation context.
    # A generic AI block proves only the container scope.  The field itself
    # must be one of the documented diplomatic-action consumers before we
    # promote it to a legal surface; unknown keys remain pending even when
    # the surrounding documentation happens to mention the common scope.
    if directory == "diplomatic_actions":
        if len(field) != 2 or field[0] != "ai":
            return _Scope()
        name = field[1]
        diplomatic_operation = _DIPLOMATIC_OPERATIONS.get(name)
        if diplomatic_operation is None:
            return _Scope()
        docs = "common/diplomatic_actions/diplomatic_action.md"
        declaration = f"{name} = {{}}"
        if name == "evaluation_chance":
            return _doc_scope(
                inputs,
                docs,
                (declaration, "AI country is always root", "has no data about targets"),
                "country",
                "none",
                "chance",
            )
        if name in {"will_select_as_first_state", "will_select_as_second_state"}:
            return _doc_scope(
                inputs,
                docs,
                (declaration, "only contain the state as root in the scope and no other data"),
                "state",
                "none",
                "predicate",
            )
        return _doc_scope(
            inputs,
            docs,
            (declaration, "AI country is always root", "other country always scope:target"),
            "country",
            "scope:target=country",
            diplomatic_operation,
        )
    if directory == "treaty_articles":
        return _treaty_scope(field, inputs, definition, source)
    if directory == "ai_strategies":
        if field[0] in {
            "wargoal_scores",
            "secret_goal_scores",
            "treaty_category_scores",
            "strategic_region_stance_type_scores",
        }:
            if (
                strategy_proof is None
                or not strategy_proof.verified
                or source not in strategy_proof.strategy_sources
            ):
                return _Scope()
            goal_contract = next(
                (item for item in strategy_proof.consumers if item.field == field[0]), None
            )
            data = json.loads(engine_scope.strategy_snapshot())
            stance_definitions = (
                _stance_definitions(inputs)
                if field[0] == "strategic_region_stance_type_scores"
                else {}
            )
            keys = (
                stance_definitions
                if field[0] == "strategic_region_stance_type_scores"
                else data["strategy_score_keys"][field[0]]
            )
            if not keys:
                return _Scope()
            goal_scores = _strategy_score_map(definition, field[0], frozenset(keys))
            if goal_contract is None or goal_scores is None:
                return _Scope()
            references = (*goal_contract.references, f"{source}:{definition.line}")
            if len(field) == 1:
                return _Scope(
                    "definition_structure", "none", "strategy_score_map", "observation", references
                )
            child = _ordinary_child(goal_scores, field[1])
            if child is None:
                return _Scope()
            if field[0] == "secret_goal_scores" and len(field) == 2:
                return _Scope(
                    "definition_structure", "none", "secret_goal_entry", "observation", references
                )
            if (field[0] != "secret_goal_scores" and len(field) == 2) or (
                field[0] == "secret_goal_scores" and field[2:] == ("score",)
            ):
                return _Scope(
                    goal_contract.actor,
                    goal_contract.target,
                    goal_contract.operation,
                    goal_contract.capability,
                    (
                        *references,
                        f"{source}:{child.line}",
                        *(
                            (
                                f"{stance_definitions[field[1]][0]}:{stance_definitions[field[1]][1]}",
                            )
                            if field[0] == "strategic_region_stance_type_scores"
                            else ()
                        ),
                    ),
                )
            return _Scope()
        if field[0] == "institution_scores":
            if (
                strategy_proof is None
                or not strategy_proof.verified
                or source not in strategy_proof.strategy_sources
            ):
                return _Scope()
            engine_contract = next(
                (item for item in strategy_proof.consumers if item.field == "institution_scores"),
                None,
            )
            definitions = _institution_definitions(inputs)
            institution_scores = _institution_score_map(definition, frozenset(definitions))
            if engine_contract is None or institution_scores is None:
                return _Scope()
            references = (*engine_contract.references, f"{source}:{definition.line}")
            if len(field) == 1:
                return _Scope(
                    "definition_structure",
                    "definition_only:institution_type",
                    "institution_score_map",
                    "observation",
                    references,
                )
            if len(field) != 2 or (child := _ordinary_child(institution_scores, field[1])) is None:
                return _Scope()
            definition_source, definition_line = definitions[field[1]]
            return _Scope(
                engine_contract.actor,
                engine_contract.target,
                engine_contract.operation,
                engine_contract.capability,
                (*references, f"{source}:{child.line}", f"{definition_source}:{definition_line}"),
            )
        if strategy_proof is not None and strategy_proof.verified and len(field) == 1:
            engine_contract = next(
                (item for item in strategy_proof.consumers if item.field == field[0]), None
            )
            if engine_contract is not None:
                if (
                    source not in strategy_proof.strategy_sources
                    or definition.op != "="
                    or definition.prefix is not None
                    or not isinstance(definition.value, Block)
                    or _ordinary_child(definition.value, field[0]) is None
                ):
                    return _Scope()
                return _Scope(
                    engine_contract.actor,
                    engine_contract.target,
                    engine_contract.operation,
                    engine_contract.capability,
                    (*engine_contract.references, f"{source}:{definition.line}"),
                )
        return strategies.get(".".join(field), strategies.get(field[0], _Scope()))
    if directory == "laws" and field == ("ai_enact_weight_modifier",):
        return _doc_scope(
            inputs,
            "common/laws/readme.md",
            ("Root scope is AI country, scope:law contains the relevant law for that country",),
            "country",
            "scope:law=law",
            "additive_score",
        )
    if directory == "buildings" and field in {
        ("ai_value",),
        ("ai_nationalization_desire",),
    }:
        building_markers: tuple[str, ...]
        if field == ("ai_value",):
            building_markers = (
                "scope is state the building is located in",
                "ai_value = script value",
            )
            actor = "state"
        else:
            # 1.14.5's shipped documentation uses the historical spelling
            # ``ai_privatization_deisre`` while definitions use
            # ``ai_nationalization_desire``. Keep that exact spelling in the
            # evidence marker instead of inferring a name equivalence.
            building_markers = (
                "# how much the AI wants to nationalize/privatize the building",
                "# scope is country the building is located in",
                "ai_privatization_deisre = script value",
            )
            actor = "country"
        return _doc_scope(
            inputs,
            "common/buildings/buildings.md",
            building_markers,
            actor,
            "none",
            "score",
        )
    if directory == "mobilization_options" and field == ("ai_weight",):
        return _doc_scope(
            inputs,
            "common/mobilization_options/mobilization_options.md",
            ("root = military formation", "ai_weight"),
            "military_formation",
            "none",
            "multiplicative_score",
        )
    if directory == "country_ranks" and field == ("ai_pool_character_multiplier",):
        # The shipped rank template gives this field its own actor and
        # operation contract: it is a multiplier on the number of generated
        # pool characters for an AI country of the rank.  There is no
        # script-side target scope; the rank is the definition carrying the
        # scalar, so keep target explicitly ``none`` rather than inventing a
        # country/rank scope object.
        return _doc_scope(
            inputs,
            "common/country_ranks/00_country_ranks.txt",
            (
                "# ai_pool_character_multiplier = Multiplier on how many randomly generated pool characters",
                "ai_pool_character_multiplier =",
            ),
            "country",
            "none",
            "multiplier",
            "indirect",
        )
    if directory == "cohesion_levels" and field == ("ai_unification_support_score",):
        # The source comment is field-local and identifies this scalar as an
        # AI implication for power-bloc unification support. It is fixed
        # configuration consumed by the engine, not a script expression with
        # a country or power-bloc target scope.
        raw = inputs.get(source)
        child = (
            _ordinary_child(definition.value, "ai_unification_support_score")
            if isinstance(definition.value, Block)
            else None
        )
        if (
            raw is not None
            and child is not None
            and child.op == "="
            and child.prefix is None
            and isinstance(child.value, Scalar)
            and re.fullmatch(r"-?\d+(?:\.\d+)?", child.value.text)
        ):
            lines = raw.decode("utf-8-sig").splitlines()
            comments: list[str] = []
            for line in reversed(lines[: child.line - 1]):
                if line.strip() and not line.lstrip().startswith("#"):
                    break
                comments.append(line)
            text = "\n".join(reversed(comments))
            if "AI implications for Power Blocs:" in text and "unification support" in text:
                return _Scope(
                    "global",
                    "none",
                    "unification_support_score",
                    "indirect",
                    (f"{source}:{child.line - len(comments)}",),
                )
    if directory == "ai_regional_objectives":
        contracts = {
            "possible": ("possible = { <trigger> }", "predicate", "direct"),
            "complete": ("complete = { <trigger> }", "predicate", "direct"),
            "invalid": ("invalid = { <trigger> }", "predicate", "direct"),
            "weight": ("weight = <script value>", "relative_weight", "direct"),
            "on_create": ("on_create = { <effect> }", "effect", "indirect"),
            "on_complete": ("on_complete = { <effect> }", "effect", "indirect"),
            "on_invalid": ("on_invalid = { <effect> }", "effect", "indirect"),
        }
        contract = contracts.get(field[0]) if len(field) == 1 else None
        if contract is None:
            return _Scope()
        declaration, operation, capability = contract
        return _doc_scope(
            inputs,
            "common/ai_regional_objectives/ai_regional_objectives.md",
            (
                "root = the AI country",
                "scope:target_region = the strategic region",
                "scope:target_stance = the regional stance",
                declaration,
            ),
            "country",
            "scope:target_region=strategic_region;scope:target_stance=strategic_region_stance",
            operation,
            capability,
        )
    return _Scope()


def _frontier(
    assignment: Assignment, path: tuple[str, ...], *, mapped: bool = False
) -> Iterator[tuple[tuple[str, ...], Assignment]]:
    if len(path) == 3 and path[0] == "fleet_compositions" and path[2] == "potential":
        yield path, assignment
        return
    if isinstance(assignment.value, Block) and (mapped or assignment.key in _MAP_FIELDS):
        children = tuple(assignment.value.assignments())
        if children and not any(
            item.key in _EXPRESSION_KEYS or item.key.startswith("scope:") for item in children
        ):
            for child in children:
                yield from _frontier(child, (*path, child.key), mapped=True)
            return
    yield path, assignment


def _candidates(directory: str, block: Block) -> Iterator[tuple[tuple[str, ...], Assignment]]:
    for assignment in block.assignments():
        if assignment.is_variable:
            continue
        if directory == "ai_strategies" and assignment.key in {
            "wargoal_scores",
            "secret_goal_scores",
            "treaty_category_scores",
            "strategic_region_stance_type_scores",
        }:
            yield (assignment.key,), assignment
            if isinstance(assignment.value, Block):
                for child in assignment.value.assignments():
                    yield (assignment.key, child.key), child
                    if assignment.key == "secret_goal_scores" and isinstance(child.value, Block):
                        for member in child.value.assignments():
                            yield (assignment.key, child.key, member.key), member
            continue
        if directory == "ai_strategies" and assignment.key == "institution_scores":
            yield (assignment.key,), assignment
            if isinstance(assignment.value, Block):
                for child in assignment.value.assignments():
                    yield (assignment.key, child.key), child
            continue
        if assignment.key == "ai" and isinstance(assignment.value, Block):
            for child in assignment.value.assignments():
                yield from _frontier(child, ("ai", child.key))
        elif (
            directory.startswith("ai_") and assignment.key not in {"icon", "type"}
        ) or assignment.key.startswith("ai_"):
            yield from _frontier(assignment, (assignment.key,))
        elif assignment.key == "game_data" and isinstance(assignment.value, Block):
            for path, child in _candidates(directory, assignment.value):
                yield (assignment.key, *path), child


def _surface(
    source: str, definition: str, field: str, line: int, scope: _Scope, *, getter: str | None = None
) -> VanillaSurface:
    identity = (source, definition, field, scope.actor, scope.target, scope.operation)
    getter_note = "未证明存在读取当前消费者分数的合法 getter；不能据此判为引擎未暴露"
    if getter:
        getter_note = "脚本定义可作为 getter；调用方合法作用域尚待核对"
    elif scope.operation == "global_parameter":
        getter_note = "静态全局参数定义；不是国家脚本 getter，也没有生产写入"
    elif scope.operation in {
        "ai_selection_policy",
        "grievance_start_permission",
        "significant_demand_flag",
        "objective_stance_eligibility",
        "construction_level_cap",
        "building_group_score_multiplier",
        "preferred_government_interest_groups",
        "avoided_government_interest_groups",
        "static_subject_type_value_multiplier",
    }:
        getter_note = "静态定义配置；不是国家脚本 getter，也没有生产写入"
    elif scope.actor == "caller_scope" and (
        source.startswith("common/scripted_triggers/") or "/common/scripted_triggers/" in source
    ):
        getter_note = "仅观察调用方依赖的脚本定义；实际调用作用域和参数尚须逐处核对，不授予 getter"
    elif scope.parent_field is not None:
        getter_note = "仅观察父字段内部表达式；不是独立 AI 消费者，也不授予 getter"
    return VanillaSurface(
        surface_id=_digest(identity),
        source=source,
        definition=definition,
        field=field,
        actor_scope=scope.actor,
        target_scope=scope.target,
        operation=scope.operation,
        capability=scope.capability,
        status="pending",
        getter=getter,
        getter_note=getter_note,
        scope_evidence=scope.evidence,
        responsibility_step=(
            "D4.06"
            if scope.actor != "unknown"
            and scope.target != "unknown"
            and scope.operation != "declared_field"
            and scope.evidence
            else "D0.03"
        ),
        source_line=line,
        parent_field=scope.parent_field,
        parent_source_line=scope.parent_source_line,
    )


def _event_candidates(
    source: str, definition: Assignment
) -> tuple[tuple[VanillaEventOption, ...], tuple[VanillaSurface, ...]]:
    """Discover real top-level event options; never recurse through effects.

    Event IDs beginning with ai_ are definitions, not consumer assignments.
    Repeated option keys are selected by unique scalar name when possible and
    otherwise by physical declaration index. Neither form grants write access.
    """
    if not isinstance(definition.value, Block):
        return (), ()
    event = definition.value

    def scalar(block: Block, key: str) -> str | None:
        values = block.all(key)
        if len(values) == 1 and isinstance(values[0].value, Scalar):
            return values[0].value.unquoted
        return None

    options = event.all("option")
    names = [scalar(row.value, "name") if isinstance(row.value, Block) else None for row in options]
    counts = Counter(name for name in names if name is not None)
    records, surfaces = [], []
    for index, (option, name) in enumerate(zip(options, names, strict=True), 1):
        ambiguity = None
        if not isinstance(option.value, Block):
            ambiguity = "event_option_not_block"
        elif name is None or counts[name] != 1:
            ambiguity = "event_option_name_missing_dynamic_or_duplicate"
        identity = f"option[{name}]" if ambiguity is None else f"option[#{index}]"
        weights = option.value.all("ai_chance") if isinstance(option.value, Block) else []
        if len(weights) > 1:
            ambiguity = "duplicate_event_option_ai_chance"
        field = f"{identity}.ai_chance"
        records.append(
            VanillaEventOption(
                source,
                definition.key,
                field,
                index,
                name,
                scalar(event, "type"),
                option.line,
                tuple(row.line for row in weights),
                scalar(option.value, "default_option") if isinstance(option.value, Block) else None,
                ambiguity,
            )
        )
        # Include undeclared numeric slots in the actual denominator while
        # keeping their operation, scope and legal status explicitly unproven.
        candidates: tuple[Assignment | None, ...] = tuple(weights) if weights else (None,)
        for weight in candidates:
            row = _surface(
                source,
                definition.key,
                field,
                weight.line if weight is not None else option.line,
                _Scope(
                    operation="event_option_weight"
                    if weight is not None
                    else "undeclared_event_option_weight",
                    evidence=(f"{source}:{option.line}",),
                ),
            )
            if ambiguity:
                row = replace(row, ambiguity=ambiguity)
            surfaces.append(row)
    return tuple(records), tuple(surfaces)


def _proven_event_surfaces(
    inputs: dict[str, bytes], surfaces: list[VanillaSurface]
) -> list[VanillaSurface]:
    """Authorize exact reviewed event slots after complete native context proof."""
    from pdx import event_opportunities as event  # noqa: PLC0415

    catalog = {}
    verified: set[tuple[str, ...]] = set()
    consumers = event.consumer_catalog()
    for program in event.compile_programs():
        names = tuple(sorted(event.required_program_sources(program)))
        if not set(names) <= inputs.keys():
            continue
        if names not in verified:
            texts = {name: normalized_text(inputs[name].decode("utf-8-sig")) for name in names}
            if program.identity.family == "hokkaido":
                event.verify_hokkaido_inputs(texts)
            elif program.identity.family == "sol_response":
                event.verify_sol_inputs(texts)
            else:
                event._verify_legacy_inputs(texts)
            verified.add(names)
        catalog_row = consumers[program.option]
        catalog[catalog_row["field"]] = catalog_row
    result = []
    for surface in surfaces:
        resolved = surface
        row = catalog.get(surface.field)
        if (
            row is not None
            and surface.source == row["source"]
            and surface.definition == row["definition"]
            and not surface.ambiguity
            and surface.operation in {"event_option_weight", "undeclared_event_option_weight"}
            and surface.source_line == row["source_line"]
        ):
            resolved = replace(
                surface,
                actor_scope="country",
                target_scope=row["target_scope"],
                operation="event_option_weight",
                capability="direct",
                scope_evidence=tuple(row["scope_evidence"]),
                responsibility_step="D4.06",
            )
        result.append(resolved)
    return result


def _references(inputs: dict[str, bytes]) -> tuple[VanillaReference, ...]:
    result: list[VanillaReference] = []
    pattern = re.compile(_AI_REFERENCE.pattern.decode("ascii"))
    for source, raw in sorted(inputs.items()):
        if not source.endswith(".txt"):
            continue
        tokens = tokenize(raw.decode("utf-8-sig"))
        depth = 0
        occurrences: Counter[tuple[int, str, str]] = Counter()
        for index, token in enumerate(tokens):
            if token.kind == LBRACE:
                depth += 1
            elif token.kind == RBRACE:
                depth -= 1
            if token.kind not in {ATOM, STRING}:
                continue
            for match in pattern.finditer(token.value):
                prefix = token.value[: match.start()]
                line = token.line + prefix.count("\n")
                expression = match.group(0)
                if depth == 0 and tokens[index + 1].kind == OP:
                    kind = "declaration_reference"
                elif expression == "is_ai" and token.kind == ATOM:
                    kind = "predicate"
                elif index >= 2 and tokens[index - 2].value == "name":
                    kind = "state_variable"
                elif token.value[match.end() :].startswith("("):
                    kind = "script_call"
                elif token.kind == STRING:
                    kind = "string_reference"
                elif expression.startswith("ai_"):
                    kind = "script_call_or_variable"
                else:
                    kind = "namespace_reference"
                key = (line, kind, expression)
                occurrences[key] += 1
                occurrence = occurrences[key]
                column = (
                    len(prefix.rsplit("\n", 1)[-1]) + 1
                    if "\n" in prefix
                    else token.col + match.start()
                )
                identity = (source, line, kind, expression, occurrence)
                result.append(
                    VanillaReference(
                        reference_id=_digest(identity),
                        source=source,
                        line=line,
                        kind=kind,
                        expression=expression,
                        column=column,
                        occurrence=occurrence,
                    )
                )
    return tuple(sorted(result, key=lambda item: item.reference_id))


def parameter_evidence_hashes(game: Path) -> dict[str, str]:
    """Retain supplied native evidence without creating controllable surfaces.

    Missing auxiliary files remain absent, so dependent parameter proofs fail
    closed. This also supports explicit partial fixtures. Any present source
    must retain the independent version-pinned raw bytes; no adapter claim can
    replace their identity or grant a getter permission.
    """
    hashes = {}
    for name, expected in _PARAMETER_EVIDENCE_HASHES.items():
        path = game / name
        if not path.is_file():
            continue
        _contained(game, path)
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != expected:
            raise ValueError(f"参数原版证据漂移：{name}")
        if parse_bytes(raw, path=name).errors:
            raise ValueError(f"参数原版证据解析失败：{name}")
        hashes[name] = digest
    return hashes


def _record_surface_ownership(
    definitions: list[VanillaDefinition],
    surfaces: list[VanillaSurface],
    occurrences: Counter[tuple[str, str, str]],
) -> None:
    identities = []
    for item in surfaces:
        declaration = (item.source, item.definition, item.field)
        occurrences[declaration] += 1
        identities.append(_digest((*declaration, occurrences[declaration])))
    definitions[-1] = replace(definitions[-1], surface_declaration_ids=tuple(identities))


def _syntax(node: Assignment | Block | Scalar | None) -> dict[str, Any]:
    """Lossless parser structure for an unclassified candidate, without semantics."""
    if isinstance(node, Assignment):
        return {
            "kind": "assignment",
            "key": node.key,
            "operator": node.op,
            "prefix": node.prefix,
            "line": node.line,
            "value": _syntax(node.value),
        }
    if isinstance(node, Block):
        return {"kind": "block", "line": node.line, "items": [_syntax(item) for item in node.items]}
    if isinstance(node, Scalar):
        return {"kind": "scalar", "line": node.line, "text": node.text, "quoted": node.quoted}
    return {"kind": "missing_value"}


def _retained_source_syntax(source: str, raw: bytes, root: Block) -> dict[str, Any]:
    """Retain every parsed node once, including shapes candidate traversal skips."""
    syntax = _syntax(root)
    stack: list[tuple[dict[str, Any], tuple[int, ...]]] = [(syntax, ())]
    node_count = 0
    while stack:
        node, position = stack.pop()
        node_count += 1
        node["node_position"] = list(position)
        node["node_id"] = _digest((source, position))
        if node["kind"] == "assignment":
            stack.append((node["value"], (*position, -1)))
        elif node["kind"] == "block":
            stack.extend((child, (*position, index)) for index, child in enumerate(node["items"]))
    encoded = json.dumps(syntax, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "syntax_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        "node_count": node_count,
        "syntax_json": encoded,
    }


def _event_slot_records(
    owner: VanillaDefinition, options: tuple[VanillaEventOption, ...]
) -> list[VanillaEventSlot]:
    result = []
    offset = 0
    for option in options:
        count = max(1, len(option.weight_lines))
        declaration_ids = owner.surface_declaration_ids[offset : offset + count]
        if len(declaration_ids) != count:
            raise ValueError(
                f"事件槽位缺少物理 surface 所有权：{owner.source}:{option.source_line}"
            )
        result.append(
            VanillaEventSlot(
                slot_id=_digest((owner.declaration_id, option.option_index)),
                owner_declaration_id=owner.declaration_id,
                owner_definition_index=owner.definition_index,
                owner_declaration_occurrence=owner.declaration_occurrence,
                source=owner.source,
                definition=owner.definition,
                option_index=option.option_index,
                source_line=option.source_line,
                surface_declaration_ids=declaration_ids,
                ambiguities=(option.ambiguity,) if option.ambiguity else (),
            )
        )
        offset += count
    if offset != len(owner.surface_declaration_ids):
        raise ValueError(f"事件槽位存在未归属的 surface：{owner.source}:{owner.source_line}")
    return result


def _scan_declarations(
    inputs: dict[str, bytes],
    event_roots: tuple[str, ...],
    surface_scope: Callable[[str, tuple[str, ...], Assignment, Assignment, str], _Scope],
    *,
    retain_source: Callable[[str, bytes, Block], None] | None = None,
) -> _Discovery:
    """One parser/candidate/duplicate pipeline; authorization belongs to its caller."""
    surfaces: list[VanillaSurface] = []
    technology_owners: dict[str, set[tuple[str, int]]] = {}
    strategy_owners: dict[str, set[tuple[str, int]]] = {}
    country_owners: dict[tuple[str, str], set[tuple[str, int]]] = {}
    company_owners: dict[str, set[tuple[str, int]]] = {}
    law_owners: dict[str, set[tuple[str, int]]] = {}
    event_owners: dict[str, set[tuple[str, int]]] = {}
    parsed_files = 0
    parse_failures: list[str] = []
    event_options: list[VanillaEventOption] = []
    event_slots: list[VanillaEventSlot] = []
    definitions: list[VanillaDefinition] = []
    unsupported: list[dict[str, Any]] = []
    definition_occurrences: Counter[tuple[str, str]] = Counter()
    declaration_occurrences: Counter[tuple[str, str, str]] = Counter()
    for source, raw in sorted(inputs.items()):
        if not source.endswith(".txt"):
            continue
        raw.decode("utf-8-sig")
        parsed = parse_bytes(raw, path=source)
        parsed_files += 1
        if parsed.errors:
            failure = f"{source}: {'; '.join(parsed.errors)}"
            parse_failures.append(failure)
            raise ValueError(f"原版解析失败：{failure}")
        if retain_source is not None:
            retain_source(source, raw, parsed.root)
        directory = source.removeprefix("common/").split("/common/")[-1].split("/")[0]
        event_source = any(source.startswith(name + "/") for name in event_roots)
        unsupported.extend(
            {
                "source": source,
                "line": node.line,
                "kind": "unsupported_top_level_" + type(node).__name__.lower(),
                "syntax": _syntax(node),
                "node_position": [index],
                "node_id": _digest((source, (index,))),
            }
            for index, node in enumerate(parsed.root.items)
            if not isinstance(node, Assignment)
        )
        for definition_index, definition in enumerate(parsed.top_assignments):
            if definition.is_variable:
                continue
            definition_occurrences[(source, definition.key)] += 1
            record = VanillaDefinition(
                source,
                directory,
                definition.key,
                definition_index,
                definition.line,
                definition_occurrences[(source, definition.key)],
                definition.op,
                definition.prefix,
                isinstance(definition.value, Block),
            )
            definitions.append(record)
            before_surfaces = len(surfaces)
            if event_source:
                event_owners.setdefault(definition.key, set()).add((source, definition_index))
                options, candidates = _event_candidates(source, definition)
                event_options.extend(options)
                surfaces.extend(candidates)
                _record_surface_ownership(
                    definitions, surfaces[before_surfaces:], declaration_occurrences
                )
                event_slots.extend(_event_slot_records(definitions[-1], options))
                continue
            if "/technology/technologies/" in "/" + source:
                # 多个定义可同处一行；行号不能替代声明位置。
                technology_owners.setdefault(definition.key, set()).add((source, definition_index))
            if directory == "ai_strategies":
                strategy_owners.setdefault(definition.key, set()).add((source, definition_index))
            if directory == "laws":
                law_owners.setdefault(definition.key, set()).add((source, definition_index))
            if directory == "company_types":
                company_owners.setdefault(definition.key, set()).add((source, definition_index))
            if directory in {"country_creation", "country_formation"}:
                country_owners.setdefault((directory, definition.key), set()).add(
                    (source, definition_index)
                )
            if directory in _OBSERVATION_DIRS:
                scope = surface_scope(directory, ("__body__",), definition, definition, source)
                surfaces.append(
                    _surface(
                        source,
                        definition.key,
                        "__body__",
                        definition.line,
                        scope,
                    )
                )
            elif directory == "defines" and isinstance(definition.value, Block):
                surfaces.extend(
                    _surface(
                        source,
                        definition.key,
                        assignment.key,
                        assignment.line,
                        surface_scope(directory, (assignment.key,), definition, assignment, source),
                    )
                    for assignment in definition.value.assignments()
                    if definition.key == "NAI" or assignment.key.startswith("AI_")
                )
            elif directory not in _INFRASTRUCTURE_DIRS and isinstance(definition.value, Block):
                for field, assignment in _candidates(directory, definition.value):
                    surfaces.append(
                        _surface(
                            source,
                            definition.key,
                            ".".join(field),
                            assignment.line,
                            surface_scope(directory, field, definition, assignment, source),
                        )
                    )
                    if (
                        directory == "ai_strategies"
                        and len(field) == 1
                        and field[0] not in _MAP_FIELDS
                        and isinstance(assignment.value, Block)
                        and assignment.value.items
                        and not any(
                            child.key in _EXPRESSION_KEYS or child.key.startswith("scope:")
                            for child in assignment.value.assignments()
                        )
                    ):
                        unsupported.append(
                            {
                                "kind": "unexpanded_strategy_structure",
                                "source": source,
                                "definition": definition.key,
                                "field": ".".join(field),
                                "source_line": assignment.line,
                                "reason": "unclassified nonnumeric strategy block; no map or scope contract inferred",
                                "child_keys": assignment.value.keys(),
                                "syntax": _syntax(assignment.value),
                                "surface_index": len(surfaces) - 1,
                            }
                        )
            _record_surface_ownership(
                definitions, surfaces[before_surfaces:], declaration_occurrences
            )
    # Declaration IDs must survive changes to inferred capability/scope. Count
    # syntax occurrences before semantic identity (including REPLACE) is used.
    counts = Counter((item.source, item.definition, item.field) for item in surfaces)
    occurrences: Counter[tuple[str, str, str]] = Counter()
    resolved: list[VanillaSurface] = []
    for original in surfaces:
        item = original
        declaration = (item.source, item.definition, item.field)
        if counts[declaration] > 1:
            occurrences[declaration] += 1
            occurrence = occurrences[declaration]
            item = replace(
                item,
                surface_id=_digest((item.surface_id, occurrence)),
                declaration_occurrence=occurrence,
                ambiguity="duplicate_field_merge_semantics_unknown",
                capability="pending",
                responsibility_step="D0.03",
            )
        if (
            "/technology/technologies/" in "/" + item.source
            and len(technology_owners[item.definition]) > 1
        ):
            item = replace(
                item,
                ambiguity="duplicate_technology_definition_merge_semantics_unknown",
                capability="pending",
                responsibility_step="D0.03",
            )
        if "/ai_strategies/" in "/" + item.source and len(strategy_owners[item.definition]) > 1:
            item = replace(
                item,
                ambiguity="duplicate_strategy_definition_merge_semantics_unknown",
                capability="pending",
                responsibility_step="D0.03",
            )
        directory = item.source.removeprefix("common/").split("/common/")[-1].split("/")[0]
        if (
            any(item.source.startswith(name + "/") for name in event_roots)
            and len(event_owners[item.definition]) > 1
        ):
            item = replace(
                item,
                ambiguity="duplicate_event_definition_merge_semantics_unknown",
                capability="pending",
                responsibility_step="D0.03",
            )
        if directory == "laws" and len(law_owners[item.definition]) > 1:
            item = replace(
                item,
                ambiguity="duplicate_law_definition_merge_semantics_unknown",
                capability="pending",
                responsibility_step="D0.03",
            )
        if directory == "company_types" and len(company_owners[item.definition]) > 1:
            item = replace(
                item,
                ambiguity="duplicate_company_definition_merge_semantics_unknown",
                capability="pending",
                responsibility_step="D0.03",
            )
        if (
            directory in {"country_creation", "country_formation"}
            and len(country_owners[(directory, item.definition)]) > 1
        ):
            item = replace(
                item,
                ambiguity="duplicate_country_definition_merge_semantics_unknown",
                capability="pending",
                responsibility_step="D0.03",
            )
        resolved.append(item)
    for observation in unsupported:
        if "surface_index" in observation:
            observation["declaration_id"] = resolved[
                observation.pop("surface_index")
            ].declaration_id
    event_slots = [
        replace(
            slot,
            ambiguities=(*slot.ambiguities, "duplicate_event_definition_merge_semantics_unknown"),
        )
        if len(event_owners[slot.definition]) > 1
        else slot
        for slot in event_slots
    ]
    return _Discovery(
        resolved,
        parsed_files,
        tuple(sorted(parse_failures)),
        tuple(event_options),
        tuple(definitions),
        tuple(unsupported),
        tuple(event_slots),
    )


def discover(*, game: Path | None = None) -> VanillaInventory:
    """现读原版完整相关 common 定义；解析不完整或版本漂移均显式失败。"""
    root = game if game is not None else config.GAME
    version = config.game_version(root.parent)
    if version["caligula_branch"] != f"release/{LOCKED_VERSION}":
        raise ValueError(f"原版版本必须锁定 {LOCKED_VERSION}：{version['caligula_branch']!r}")
    missing_version = [name for name, value in version.items() if not value]
    if missing_version:
        raise ValueError(f"原版版本指纹缺失：{', '.join(missing_version)}")
    inputs, directories, content_roots = _inputs(root)
    event_roots = tuple(name for name in content_roots if PurePosixPath(name).name == "events")
    hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in inputs.items()}
    hashes.update(parameter_evidence_hashes(root))
    technology_proof = engine_scope.technology_evidence(root, inputs)
    hashes.update(technology_proof.source_hashes)
    strategy_proof = engine_scope.strategy_evidence(root, inputs)
    hashes.update(strategy_proof.source_hashes)
    country_proof = engine_scope.country_evidence(root, inputs)
    hashes.update(country_proof.source_hashes)
    company_proof = engine_scope.company_evidence(root, inputs)
    hashes.update(company_proof.source_hashes)
    company_default_proof = engine_scope.company_default_evidence(root, inputs)
    hashes.update(company_default_proof.source_hashes)
    law_proof = engine_scope.law_evidence(root, inputs)
    hashes.update(law_proof.source_hashes)
    for name in version:
        hashes[f"@version/{name}.txt"] = hashlib.sha256(
            (root.parent / f"{name}.txt").read_bytes()
        ).hexdigest()
    strategies = _strategy_scopes(inputs)
    trigger_definition_scope = _scripted_trigger_definition_scope(inputs)
    company_construction = (
        _declared_type_keys(inputs, "buildings"),
        _company_construction_doc(inputs),
    )
    company_selection = _company_selection_doc(inputs)
    ship_modification_formula = _ship_modification_formula_doc(inputs)
    subject_value_minimum = (_subject_value_minimum(inputs),)
    building_group_keys = _declared_type_keys(inputs, "building_groups")
    strategy_building_groups = (
        building_group_keys,
        _building_group_weight_doc(inputs, building_group_keys),
    )
    interest_group_keys = _declared_type_keys(inputs, "interest_groups")
    strategy_interest_groups = (
        interest_group_keys,
        _interest_group_list_docs(inputs, interest_group_keys),
    )
    references = _references(inputs)

    def verified_scope(
        directory: str,
        field: tuple[str, ...],
        definition: Assignment,
        assignment: Assignment,
        source: str,
    ) -> _Scope:
        if directory in _OBSERVATION_DIRS:
            if directory == "script_values":
                return _doc_scope(
                    inputs,
                    "common/script_values/script_values.md",
                    ("Formulas", "scope you're currently in"),
                    "caller_scope",
                    "caller_derived",
                    "read",
                    "observation",
                )
            return (
                trigger_definition_scope
                if isinstance(definition.value, Block)
                and definition.op == "="
                and definition.prefix is None
                else _Scope(operation="read")
            )
        if directory == "defines":
            return _Scope(
                "global",
                "none",
                "global_parameter",
                "observation",
                (f"{source}:{assignment.line}",),
            )
        return _scope(
            directory,
            field,
            inputs,
            strategies,
            definition,
            source,
            company_construction,
            strategy_building_groups,
            strategy_interest_groups,
            company_selection,
            ship_modification_formula,
            subject_value_minimum,
            technology_proof,
            strategy_proof,
            country_proof,
            company_proof,
            law_proof,
        )

    discovery = _scan_declarations(inputs, event_roots, verified_scope)
    resolved = discovery.surfaces
    parsed_files = discovery.parsed_files
    parse_failures = discovery.parse_failures
    event_options = discovery.event_options
    surfaces_tuple = tuple(
        sorted(_proven_event_surfaces(inputs, resolved), key=lambda item: item.surface_id)
    )
    scope_hash = _digest(
        {
            "source_hashes": hashes,
            "surfaces": [asdict(item) for item in surfaces_tuple],
            "references": [asdict(item) for item in references],
            "event_options": [asdict(item) for item in event_options],
        }
    )
    return VanillaInventory(
        f"victoria3-{LOCKED_VERSION}:{_digest(hashes)}",
        dict(sorted(hashes.items())),
        scope_hash,
        surfaces_tuple,
        directories,
        content_roots,
        parsed_files,
        references,
        tuple(sorted(parse_failures)),
        tuple(event_options),
    )


def discover_unverified(
    *, target_version: str, game: Path | None = None
) -> UnverifiedVanillaInventory:
    """Inventory a complete explicit native version without running scope proofs.

    This is a separate discovery API, never a relaxed mode of ``discover``.
    Installed documentation and even independently proven native fields remain
    pending here. The result hashes identify observations, not authorization.
    """
    if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", target_version) is None:
        raise ValueError(f"目标版本必须是完整数字版本：{target_version!r}")
    root = game if game is not None else config.GAME
    _contained(root.parent, root)
    version = config.game_version(root.parent)
    missing = [name for name, value in version.items() if not value]
    if missing:
        raise ValueError(f"原版版本指纹缺失：{', '.join(missing)}")
    if (
        version["caligula_branch"] != f"release/{target_version}"
        or version["clausewitz_branch"] != f"caligula/release/{target_version}"
    ):
        raise ValueError(f"原版版本与目标版本 {target_version} 不符：{version}")
    hashes = {}
    for name, value in version.items():
        path = root.parent / f"{name}.txt"
        _contained(root.parent, path)
        raw = path.read_bytes()
        if raw.decode("utf-8-sig").strip() != value:
            raise ValueError(f"原版版本读取期间漂移：{name}")
        hashes[f"@version/{name}.txt"] = hashlib.sha256(raw).hexdigest()
    inputs, directories, content_roots = _inputs(root)
    hashes.update({name: hashlib.sha256(raw).hexdigest() for name, raw in inputs.items()})
    event_roots = tuple(name for name in content_roots if PurePosixPath(name).name == "events")

    def unverified_scope(
        _directory: str,
        _field: tuple[str, ...],
        _definition: Assignment,
        _assignment: Assignment,
        _source: str,
    ) -> _Scope:
        return _Scope()

    source_syntax = {}

    def retain_source(source: str, raw: bytes, root: Block) -> None:
        source_syntax[source] = _retained_source_syntax(source, raw, root)

    # DLC metadata uses the same parser; descriptor safety and mounts have
    # already been validated by _inputs. Preserve its otherwise unclassified
    # syntax as well, without treating Markdown documentation as PDX syntax.
    for source, raw in inputs.items():
        if source.endswith(".dlc"):
            raw.decode("utf-8-sig")
            parsed = parse_bytes(raw, path=source)
            if parsed.errors:
                raise ValueError(f"DLC 描述符解析失败：{source}: {'; '.join(parsed.errors)}")
            retain_source(source, raw, parsed.root)
    discovery = _scan_declarations(
        inputs, event_roots, unverified_scope, retain_source=retain_source
    )
    # Event candidate generation records slot syntax, not scope evidence. Strip
    # even those syntactic evidence labels from every unverified surface.
    surfaces = tuple(
        sorted(
            (
                replace(
                    item,
                    actor_scope="unknown",
                    target_scope="unknown",
                    operation="declared_field",
                    surface_id=_digest((item.declaration_id, "unverified")),
                    capability="pending",
                    status="pending",
                    getter=None,
                    scope_evidence=(),
                    responsibility_step="D0.03",
                )
                for item in discovery.surfaces
            ),
            key=lambda item: item.surface_id,
        )
    )
    references = _references(inputs)
    surface_ids = {item.declaration_id: item.surface_id for item in surfaces}
    event_slots = tuple(
        replace(
            slot,
            surface_ids=tuple(surface_ids[identity] for identity in slot.surface_declaration_ids),
        )
        for slot in discovery.event_slots
    )
    result_hash = _digest(
        {
            "discovery_mode": "unverified",
            "target_version": target_version,
            "actual_version": version,
            "source_hashes": hashes,
            "scanned_directories": directories,
            "content_roots": content_roots,
            "surfaces": [asdict(item) for item in surfaces],
            "references": [asdict(item) for item in references],
            "event_options": [asdict(item) for item in discovery.event_options],
            "definitions": [asdict(item) for item in discovery.definitions],
            "unsupported_structures": discovery.unsupported_structures,
            "source_syntax": source_syntax,
            "event_slots": [asdict(item) for item in event_slots],
        }
    )
    return UnverifiedVanillaInventory(
        baseline_id=f"victoria3-{target_version}:{_digest(hashes)}",
        source_hashes=dict(sorted(hashes.items())),
        scope_hash=result_hash,
        surfaces=surfaces,
        scanned_directories=directories,
        content_roots=content_roots,
        parsed_files=discovery.parsed_files,
        references=references,
        parse_failures=discovery.parse_failures,
        event_options=discovery.event_options,
        target_version=target_version,
        actual_version=version,
        definitions=discovery.definitions,
        unsupported_structures=discovery.unsupported_structures,
        source_syntax=source_syntax,
        event_slots=event_slots,
    )


__all__ = [
    "CAPABILITIES",
    "LOCKED_VERSION",
    "MIGRATION_DENOMINATOR",
    "SCHEMA",
    "UnverifiedVanillaInventory",
    "VanillaDefinition",
    "VanillaEventSlot",
    "VanillaInventory",
    "VanillaReference",
    "VanillaSurface",
    "discover",
    "discover_unverified",
]
