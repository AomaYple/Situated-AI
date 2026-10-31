"""D0 原版消费者独立发现，不以 Mod 规则或已修改文件作为发现分母。

扫描 common 全树定位 AI 相关目录，再解析这些目录的全部定义。发现的字段和
读取器均保持实现 pending；只有原版文档明确支持的字段级作用域才进入 legal。
字段存在、脚本引用了某个 scope、可从日志观察，均不能证明合法控制能力。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Any

from .. import config  # noqa: TID252
from ..lexer import ATOM, LBRACE, OP, RBRACE, STRING, tokenize  # noqa: TID252
from ..model import Assignment, Block, Scalar  # noqa: TID252
from ..parser import parse_bytes  # noqa: TID252

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

SCHEMA = 1
LOCKED_VERSION = "1.14.5"
# 冻结旧集合的迁移分母，绝不作为本模块原版消费者分母。
MIGRATION_DENOMINATOR = 1401
CAPABILITIES = ("direct", "indirect", "observation", "unexposed", "pending")
_AI_ASSIGNMENT = re.compile(rb"(?<![\w:])(?:ai|ai_[a-zA-Z0-9_]+)\s*=")
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
        "technology",
        "diplomatic_actions",
        "treaty_articles",
        "war_goal_types",
        "defines",
        "script_values",
        "scripted_triggers",
    }
)
_OBSERVATION_DIRS = frozenset({"script_values", "scripted_triggers"})
_INFRASTRUCTURE_DIRS = frozenset({"scripted_effects", "on_actions", "trigger_localization"})
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
_DIPLOMATIC_FIELDS = frozenset(
    {
        "evaluation_chance",
        "will_select_as_first_state",
        "will_select_as_second_state",
        "will_propose_with_states",
        "will_propose",
        "will_break",
        "will_propose_even_if_not_accepted",
        "accept_score",
        "accept_break_score",
        "propose_score",
        "propose_break_score",
        "use_favor_chance",
        "owe_favor_chance",
    }
)


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
            "plan_version": "31.3",
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
            "surfaces": [{**asdict(item), "legal": item.legal} for item in self.surfaces],
            "discovered_count": self.discovered_count,
            "legal_count": self.legal_count,
            "unexposed_count": self.unexposed_count,
            "pending_count": self.pending_count,
            "status_counts": self.status_counts,
            "capability_counts": self.capability_counts,
            "migration_denominator": MIGRATION_DENOMINATOR,
            "parse_failures": list(self.parse_failures),
            "unknown_scopes": list(self.unknown_scopes),
        }


@dataclass(frozen=True, slots=True)
class _Scope:
    actor: str = "unknown"
    target: str = "unknown"
    operation: str = "declared_field"
    capability: str = "pending"
    evidence: tuple[str, ...] = ()


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


def _inputs(game: Path) -> tuple[dict[str, bytes], tuple[str, ...], tuple[str, ...]]:
    common = game / "common"
    if not common.is_dir():
        raise ValueError(f"原版 common 树不存在：{common}")
    _contained(game, common)
    roots = [common]
    in_game = game / "in_game/common"
    if in_game.is_dir():
        roots.append(in_game)
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
            if mount.name == "common":
                roots.append(mount)
            # A descriptor mounts one content root.  Only its declared root
            # and its direct common trees are in scope; recursively importing
            # arbitrary nested/sibling ``common`` directories would make the
            # inventory claim files the engine does not mount from this DLC.
            roots.extend(
                candidate
                for candidate in (mount / "common", mount / "in_game" / "common")
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
        directory = path.relative_to(content_root).parts[0]
        if directory.startswith("ai_"):
            related.add(directory)
        raw = path.read_bytes()
        if (
            path.suffix == ".txt" and (_AI_ASSIGNMENT.search(raw) or _AI_REFERENCE.search(raw))
        ) or (path.suffix == ".md" and re.search(rb"\bAI\b", raw)):
            related.add(directory)
    selected = {
        path.relative_to(game).as_posix(): path.read_bytes()
        for content_root, path in files
        if path.relative_to(content_root).parts[0] in related
    }
    directories = tuple(
        sorted(
            {
                (content_root / path.relative_to(content_root).parts[0])
                .relative_to(game)
                .as_posix()
                for content_root, path in files
                if path.relative_to(content_root).parts[0] in related
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
        # The sample proves the root but does not specify the complete target
        # context.  A missing statement is not evidence of target=none.
        return _Scope()
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
            if spec is None:
                continue
            comments: list[str] = []
            for line in reversed(lines[: assignment.line - 1]):
                if line.strip() and not line.lstrip().startswith("#"):
                    break
                comments.append(line)
            text = "\n".join(reversed(comments))
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
            if spec[0] in text and spec[1] in text and "function additively" in text:
                scopes[assignment.key] = _Scope(
                    "country", spec[2], "additive_score", "direct", (f"{source}:{assignment.line}",)
                )
    return scopes


def _scope(
    directory: str,
    field: tuple[str, ...],
    inputs: dict[str, bytes],
    strategies: dict[str, _Scope],
    definition: Assignment,
    source: str,
) -> _Scope:
    if directory == "treaty_articles":
        return _treaty_scope(field, inputs, definition, source)
    if directory == "ai_strategies":
        return strategies.get(field[0], _Scope())
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
    if directory == "diplomatic_actions" and field[0] == "ai" and len(field) > 1:
        if field[1] not in _DIPLOMATIC_FIELDS:
            return _Scope()
        actor, target = "country", "scope:target=country"
        diplomatic_markers: list[str] = [
            "the AI country is always root and the other country always scope:target"
        ]
        if field[1] == "evaluation_chance":
            target = "none"
            diplomatic_markers.append("has no data about targets")
        elif field[1] in {"will_select_as_first_state", "will_select_as_second_state"}:
            actor, target = "state", "none"
            diplomatic_markers.append(
                "only contain the state as root in the scope and no other data"
            )
        operation = "predicate" if field[1].startswith("will_") else "score"
        return _doc_scope(
            inputs,
            "common/diplomatic_actions/diplomatic_action.md",
            tuple(diplomatic_markers),
            actor,
            target,
            operation,
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
    if directory == "ai_regional_objectives":
        return _doc_scope(
            inputs,
            "common/ai_regional_objectives/ai_regional_objectives.md",
            (
                "root = the AI country",
                "scope:target_region = the strategic region",
                "scope:target_stance = the regional stance",
            ),
            "country",
            "scope:target_region=strategic_region;scope:target_stance=strategic_region_stance",
            "effect" if field[0].startswith("on_") else "evaluate",
            "indirect" if field[0].startswith("on_") else "direct",
        )
    return _Scope()


def _frontier(
    assignment: Assignment, path: tuple[str, ...], *, mapped: bool = False
) -> Iterator[tuple[tuple[str, ...], Assignment]]:
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
        getter_note=(
            "脚本定义可作为 getter；调用方合法作用域尚待核对"
            if getter
            else (
                "静态全局参数定义；不是国家脚本 getter，也没有生产写入"
                if scope.operation == "global_parameter"
                else "未证明存在读取当前消费者分数的合法 getter；不能据此判为引擎未暴露"
            )
        ),
        scope_evidence=scope.evidence,
        responsibility_step="D4.06" if scope.actor != "unknown" else "D0.03",
        source_line=line,
    )


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
    hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in inputs.items()}
    for name in version:
        hashes[f"@version/{name}.txt"] = hashlib.sha256(
            (root.parent / f"{name}.txt").read_bytes()
        ).hexdigest()
    strategies = _strategy_scopes(inputs)
    references = _references(inputs)
    surfaces: list[VanillaSurface] = []
    parsed_files = 0
    parse_failures: list[str] = []
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
        directory = source.removeprefix("common/").split("/common/")[-1].split("/")[0]
        for definition in parsed.top_assignments:
            if definition.is_variable:
                continue
            if directory in _OBSERVATION_DIRS:
                surfaces.append(
                    _surface(
                        source,
                        definition.key,
                        "__body__",
                        definition.line,
                        _Scope(operation="read", capability="pending"),
                    )
                )
            elif directory == "defines" and isinstance(definition.value, Block):
                surfaces.extend(
                    _surface(
                        source,
                        definition.key,
                        assignment.key,
                        assignment.line,
                        _Scope(
                            "global",
                            "none",
                            "global_parameter",
                            "observation",
                            (f"{source}:{assignment.line}",),
                        ),
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
                            _scope(directory, field, inputs, strategies, definition, source),
                        )
                    )
    counts = Counter(item.surface_id for item in surfaces)
    occurrences: Counter[str] = Counter()
    resolved: list[VanillaSurface] = []
    for original in surfaces:
        item = original
        if counts[item.surface_id] > 1:
            occurrences[item.surface_id] += 1
            occurrence = occurrences[item.surface_id]
            item = replace(
                item,
                surface_id=_digest((item.surface_id, occurrence)),
                declaration_occurrence=occurrence,
                ambiguity="duplicate_field_merge_semantics_unknown",
                capability="pending",
                responsibility_step="D0.03",
            )
        resolved.append(item)
    surfaces_tuple = tuple(sorted(resolved, key=lambda item: item.surface_id))
    scope_hash = _digest(
        {
            "source_hashes": hashes,
            "surfaces": [asdict(item) for item in surfaces_tuple],
            "references": [asdict(item) for item in references],
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
    )


__all__ = [
    "CAPABILITIES",
    "LOCKED_VERSION",
    "MIGRATION_DENOMINATOR",
    "SCHEMA",
    "VanillaInventory",
    "VanillaReference",
    "VanillaSurface",
    "discover",
]
