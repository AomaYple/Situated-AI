"""锁定游戏版本的 Mod 能力目录。

能力目录是开发期的单一事实入口：它把静态资源中发现的条目和字段
映射到稳定 ID、来源指纹和静态候选消费者关联。
静态发现不会被提升为运行时可读或行为通过；C2/F1 会在同一条记录上
逐项推进状态。

目录只保存可审计的元数据和第一层字段。字段值仍由原始脚本、快照或
分析产物按需读取，避免再建立一份与 ``pdx.analyze`` 重复的完整 AST 数据库。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import defaultdict
from contextlib import suppress
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from . import ai_surface, config, political_surface
from .cache import parse_cached
from .localization import SUFFIXES, parse_loc_entries_with_lines
from .model import Block
from .scan import FileEntry, walk_files

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


class InformationStatus(StrEnum):
    """能力目录中允许的状态。"""

    DISCOVERED = "discovered"
    RUNTIME_READABLE = "runtime_readable"
    DERIVED = "derived"
    CONSUMER_MAPPED = "consumer_mapped"
    BEHAVIOR_VERIFIED = "behavior_verified"
    UNSUPPORTED = "unsupported"


class ImpactLevel(StrEnum):
    """信息对 Mod 决策的影响等级。"""

    DIRECT = "A"  # 直接影响行动或候选
    STRATEGY = "B"  # 影响策略权重或持牌行为
    QUALIFICATION = "C"  # 影响资格、目标或时机
    EXPLANATION = "D"  # 解释和诊断
    NO_CONSUMER = "E"  # 当前没有可靠消费者


CATALOG_FORMAT = 1
LOCALIZATION_CATALOG_FORMAT = 1
DEFAULT_SCOPE = "unknown"
DEFAULT_UNIT = "unknown"
DEFAULT_UPDATE = "static"
DEFAULT_VISIBILITY = "public_script"


def _source_digest(path: Path, cache: dict[Path, str]) -> str:
    """计算文件 SHA-256，并在同一轮扫描中复用结果。"""

    resolved = path.resolve()
    digest = cache.get(resolved)
    if digest is not None:
        return digest
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    cache[resolved] = digest
    return digest


def _consumer_index(game: Path | None) -> dict[str, tuple[tuple[str, ImpactLevel], ...]]:
    """从现有 AI surface 提取保守的消费者索引。

    这里只登记同名关联，不证明作用域或原版数值消费者语义。
    未提供游戏目录时返回空表；已提供的输入读取失败必须显式失败。
    """

    if game is None or not game.is_dir():
        return {}
    if not (game / "common/ai_strategies").exists():
        return {}
    found: dict[str, set[tuple[str, ImpactLevel]]] = defaultdict(set)

    try:
        cards = ai_surface.read_cards(game)
    except (OSError, ValueError) as exc:
        raise ValueError("AI 策略索引读取失败，不能生成完整信息目录") from exc
    for card in cards:
        definition = f"ai_strategy:{card.name}"
        found[card.name].add((definition, ImpactLevel.STRATEGY))
        for name in card.weight_inputs:
            found[name].add((f"{definition}:weight", ImpactLevel.STRATEGY))
        for name in card.possible_inputs:
            found[name].add((f"{definition}:possible", ImpactLevel.QUALIFICATION))
        for name in card.field_inputs:
            found[name].add((f"{definition}:field", ImpactLevel.STRATEGY))

    try:
        strategies = political_surface.read_strategies(game)
    except (OSError, ValueError) as exc:
        raise ValueError("政治策略索引读取失败，不能生成完整信息目录") from exc
    for strategy in strategies:
        found[strategy.name].add((f"political_strategy:{strategy.name}", ImpactLevel.STRATEGY))

    return {
        name: tuple(sorted(values, key=lambda value: (value[0], value[1].value)))
        for name, values in found.items()
    }


def _consumer_matches(
    names: Iterable[str], consumers: Mapping[str, tuple[tuple[str, ImpactLevel], ...]]
) -> tuple[tuple[str, ...], ImpactLevel, InformationStatus]:
    matched: set[tuple[str, ImpactLevel]] = set()
    for name in names:
        matched.update(consumers.get(name, ()))
    if not matched:
        return (), ImpactLevel.NO_CONSUMER, InformationStatus.DISCOVERED
    # 影响级别取最强的一项；同一条信息可以同时影响资格和权重，
    # 所有消费者仍完整记录在 consumers 中。
    rank = {
        ImpactLevel.DIRECT: 0,
        ImpactLevel.STRATEGY: 1,
        ImpactLevel.QUALIFICATION: 2,
        ImpactLevel.EXPLANATION: 3,
        ImpactLevel.NO_CONSUMER: 4,
    }
    impact = min((item[1] for item in matched), key=rank.__getitem__)
    return tuple(sorted(item[0] for item in matched)), impact, InformationStatus.DISCOVERED


@dataclass(frozen=True, slots=True)
class InformationItem:
    """能力目录的一条稳定记录。"""

    id: str
    domain: str
    name: str
    source: str
    source_sha256: str
    source_line: int | None
    scope: str = DEFAULT_SCOPE
    unit: str = DEFAULT_UNIT
    update: str = DEFAULT_UPDATE
    visibility: str = DEFAULT_VISIBILITY
    status: InformationStatus = InformationStatus.DISCOVERED
    impact: ImpactLevel = ImpactLevel.NO_CONSUMER
    consumers: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.id or not self.domain or not self.name:
            raise ValueError("能力目录条目必须有 id、domain 和 name")
        if not self.source:
            raise ValueError("能力目录条目必须有 source")
        if len(self.source_sha256) != 64:
            raise ValueError("source_sha256 必须是 64 位 SHA-256")

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "domain": self.domain,
            "name": self.name,
            "source": self.source,
            "source_sha256": self.source_sha256,
            "source_line": self.source_line,
            "scope": self.scope,
            "unit": self.unit,
            "update": self.update,
            "visibility": self.visibility,
            "status": self.status.value,
            "impact": self.impact.value,
            "consumers": list(self.consumers),
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class InformationCatalog:
    """可确定性序列化的能力目录。"""

    version: dict[str, str]
    roots: dict[str, str]
    items: tuple[InformationItem, ...] = field(default_factory=tuple)
    format_version: int = CATALOG_FORMAT

    def __post_init__(self) -> None:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for item in self.items:
            if item.id in seen:
                duplicates.add(item.id)
            seen.add(item.id)
        if duplicates:
            examples = sorted(duplicates)[:5]
            raise ValueError(f"能力目录存在重复 id：{examples}")

    @property
    def summary(self) -> dict[str, object]:
        by_status: dict[str, int] = defaultdict(int)
        by_impact: dict[str, int] = defaultdict(int)
        by_domain: dict[str, int] = defaultdict(int)
        for item in self.items:
            by_status[item.status.value] += 1
            by_impact[item.impact.value] += 1
            by_domain[item.domain] += 1
        return {
            "条目": len(self.items),
            "状态": dict(sorted(by_status.items())),
            "影响等级": dict(sorted(by_impact.items())),
            "领域": dict(sorted(by_domain.items())),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "格式版本": self.format_version,
            "版本": dict(sorted(self.version.items())),
            "内容根": dict(sorted(self.roots.items())),
            "概览": self.summary,
            # ``build`` 已按内容根、配置目录、路径和 AST 顺序产出确定性序列。
            # 这里不再对大目录的全部条目做一次全量排序，避免 C1 生成时的
            # 峰值内存和等待时间；ID 唯一性仍由 ``__post_init__`` 校验。
            "条目": [item.to_dict() for item in self.items],
        }

    def write(self, path: Path) -> None:
        """以 UTF-8 无 BOM、LF、原子替换方式写出目录。"""

        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=1)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            Path(temporary).replace(path)
        except BaseException:
            with suppress(FileNotFoundError):
                Path(temporary).unlink()
            raise


def _item_id(domain: str, name: str, source: str = "") -> str:
    """返回不依赖绝对路径的稳定 ID。"""

    return f"{domain}:{source}:{name}" if source else f"{domain}:{name}"


def _scope_for(domain: str) -> str:
    """仅使用有把握的作用域提示，未知项保持显式 unknown。"""

    # 同一策略内含国家、目标州、IG 等不同作用域；目录名不能证明作用域。
    if domain.endswith("/defines"):
        return "global"
    return DEFAULT_SCOPE


def _script_items(
    label: str,
    root: Path,
    consumers: Mapping[str, tuple[tuple[str, ImpactLevel], ...]],
    digest_cache: dict[Path, str],
) -> list[InformationItem]:
    items: list[InformationItem] = []
    for entry in _iter_scriptable_files(root):
        try:
            relative = entry.path.relative_to(root)
        except ValueError:
            continue
        if not config.is_scriptable(relative.parts, entry.path.suffix):
            continue
        source = f"{label}/{relative.as_posix()}"
        digest = _source_digest(entry.path, digest_cache)
        domain = "/".join((label, *relative.parts[:-1])) or label
        try:
            parsed = parse_cached(entry.path)
        except Exception as exc:
            items.append(
                _unsupported_script_item(
                    domain=domain,
                    source=source,
                    digest=digest,
                    reason=f"未捕获解析异常 {type(exc).__name__}: {exc}",
                )
            )
            continue
        if parsed.errors:
            items.append(
                _unsupported_script_item(
                    domain=domain,
                    source=source,
                    digest=digest,
                    reason="解析器报告错误：" + "；".join(parsed.errors),
                )
            )
            # 解析器可能仍返回部分 AST。部分树不能冒充完整发现，避免把
            # 不完整输入的字段误写成可消费能力；完整失败项保留在目录中。
            continue
        seen_entries: dict[str, int] = defaultdict(int)
        for assignment in parsed.top_assignments:
            if assignment.is_variable:
                continue
            seen_entries[assignment.key] += 1
            occurrence = seen_entries[assignment.key]
            entry_name = assignment.key if occurrence == 1 else f"{assignment.key}#{occurrence}"
            names = (assignment.key, entry_name)
            matched, impact, status = _consumer_matches(names, consumers)
            base_id = _item_id(domain, entry_name, source)
            items.append(
                InformationItem(
                    id=base_id,
                    domain=domain,
                    name=entry_name,
                    source=source,
                    source_sha256=digest,
                    source_line=assignment.line,
                    scope=_scope_for(domain),
                    status=status,
                    impact=impact,
                    consumers=matched,
                    notes="静态发现；运行时作用域和引擎读取成本未知，须在进入生产规则前单独核对",
                )
            )
            if not isinstance(assignment.value, Block):
                continue
            seen_fields: dict[str, int] = defaultdict(int)
            for field_assignment in assignment.value.assignments():
                seen_fields[field_assignment.key] += 1
                field_occurrence = seen_fields[field_assignment.key]
                field_name = f"{entry_name}.{field_assignment.key}"
                if field_occurrence > 1:
                    field_name += f"#{field_occurrence}"
                field_matches, field_impact, field_status = _consumer_matches(
                    (field_assignment.key, field_name), consumers
                )
                items.append(
                    InformationItem(
                        id=_item_id(domain, field_name, source),
                        domain=domain,
                        name=field_name,
                        source=source,
                        source_sha256=digest,
                        source_line=field_assignment.line,
                        scope=_scope_for(domain),
                        status=field_status,
                        impact=field_impact,
                        consumers=field_matches,
                        notes="第一层字段；嵌套值保留在原始脚本和 AST 产物中",
                    )
                )
    return items


def _unsupported_script_item(
    *, domain: str, source: str, digest: str, reason: str
) -> InformationItem:
    """把无法可靠解析的文件登记为显式 ``unsupported`` 条目。"""

    return InformationItem(
        id=_item_id(domain, "__parse_error__", source),
        domain=domain,
        name="__parse_error__",
        source=source,
        source_sha256=digest,
        source_line=None,
        scope=DEFAULT_SCOPE,
        unit="parse_error",
        update=DEFAULT_UPDATE,
        visibility=DEFAULT_VISIBILITY,
        status=InformationStatus.UNSUPPORTED,
        impact=ImpactLevel.NO_CONSUMER,
        notes=(
            "来源文件未形成可审计 AST；不得把部分结果当作完整能力。"
            f" {reason}；保持 unsupported，只有进入候选决策输入且存在可靠解析需求时才扩展解析器"
        ),
    )


def _iter_scriptable_files(root: Path) -> Iterable[FileEntry]:
    """只遍历可脚本化目录，并在目录栈上提前剪掉明确排除的子树。

    直接对整个内容根调用 ``walk_files`` 会把 ``binaries`` 和生成的地图资源
    也枚举一遍。目录配置已经给出脚本范围，因此在入口处剪枝可以减少大量
    Windows 文件系统调用，同时保持与 ``config.is_scriptable`` 相同的判定。
    """

    stack: list[tuple[Path, tuple[str, ...]]] = []
    for top in config.SCRIPTABLE_DIRS:
        base = root / top
        if base.is_dir():
            stack.append((base, (top,)))
    while stack:
        current, relative_dir = stack.pop()
        try:
            with os.scandir(current) as iterator:
                for entry in sorted(iterator, key=lambda value: value.name):
                    try:
                        name = entry.name
                        relative = (*relative_dir, name)
                        if entry.is_dir(follow_symlinks=False):
                            if not config.is_excluded(relative):
                                stack.append((Path(entry.path), relative))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        suffix = Path(name).suffix.lower()
                        if not config.is_scriptable(relative, suffix):
                            continue
                        stat = entry.stat(follow_symlinks=False)
                        yield FileEntry(path=Path(entry.path), size=stat.st_size, suffix=suffix)
                    except OSError as exc:
                        raise OSError(f"信息目录无法读取路径：{entry.path}") from exc
        except OSError as exc:
            raise OSError(f"信息目录无法遍历目录：{current}") from exc


def _localization_items(
    label: str, root: Path, digest_cache: dict[Path, str]
) -> list[InformationItem]:
    items: list[InformationItem] = []
    localization = root / "localization"
    if not localization.is_dir():
        return items
    for entry in sorted(walk_files(localization), key=lambda value: value.path.as_posix()):
        if entry.path.suffix.lower() not in {".yml", ".yaml"}:
            continue
        relative = entry.path.relative_to(root).as_posix()
        source = f"{label}/{relative}"
        items.append(
            InformationItem(
                id=_item_id(f"{label}/localization", relative, source),
                domain=f"{label}/localization",
                name=relative,
                source=source,
                source_sha256=_source_digest(entry.path, digest_cache),
                source_line=None,
                scope="language",
                unit="localization_key",
                update="static",
                visibility="public_localization",
                status=InformationStatus.DISCOVERED,
                impact=ImpactLevel.EXPLANATION,
                notes="文件级语言入口；键集合复用 pdx.localization 的独立提取结果",
            )
        )
    return items


def _localization_paths(root: Path) -> Iterable[Path]:
    """按相对路径稳定遍历本地化文件，不把路径全集常驻内存。"""

    localization = root / "localization"
    if not localization.is_dir():
        return
    for entry in sorted(walk_files(localization), key=lambda value: value.path.as_posix()):
        if entry.path.suffix.lower() in SUFFIXES:
            yield entry.path


def _localization_key_record(
    *,
    label: str,
    root: Path,
    path: Path,
    digest: str,
    language: str,
    key: str,
    line: int,
    occurrence: int,
) -> dict[str, object]:
    """构造键级 JSONL 记录；字段与 ``InformationItem`` 保持同一契约。"""

    relative = path.relative_to(root).as_posix()
    source = f"{label}/{relative}"
    domain = f"{label}/localization/{language}"
    name = key if occurrence == 1 else f"{key}#{occurrence}"
    item = InformationItem(
        id=_item_id(domain, name, source),
        domain=domain,
        name=name,
        source=source,
        source_sha256=digest,
        source_line=line,
        scope="language",
        unit="localization_key",
        update="static",
        visibility="public_localization",
        status=InformationStatus.DISCOVERED,
        impact=ImpactLevel.NO_CONSUMER,
        notes="只登记键级静态信息；译文语义、GUI 模板及游戏内加载和呈现不由本目录验证",
    )
    return item.to_dict()


def write_localization_catalog(
    path: Path,
    *,
    roots: Mapping[str, Path] | None = None,
    version: Mapping[str, str] | None = None,
) -> dict[str, int]:
    """流式写出完整本地化键目录（JSONL）。

    主能力目录保留文件级入口；本函数以 JSONL 单条写入每个键的来源，避免
    1 百万级键同时驻留在 ``InformationCatalog.items``。首行是元数据，之后
    每行是 ``InformationItem`` 的同构字典；输出通过临时文件原子替换。
    """

    if roots is None:
        selected: dict[str, Path] = {
            "game": config.GAME,
            "jomini": config.JOMINI,
            "clausewitz": config.CLAUSEWITZ,
        }
        selected_version = dict(config.game_version())
    else:
        selected = {str(label): Path(root) for label, root in roots.items()}
        selected_version = {}
    if version is not None:
        selected_version = dict(version)
    for label, root in selected.items():
        if not root.is_dir():
            raise FileNotFoundError(f"信息目录内容根不可用：{label} ({root})")

    path.parent.mkdir(parents=True, exist_ok=True)
    files = keys = errors = 0
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            header = {
                "类型": "header",
                "格式版本": LOCALIZATION_CATALOG_FORMAT,
                "版本": dict(sorted(selected_version.items())),
                "内容根": {
                    label: str(root) for label, root in sorted(selected.items()) if root.is_dir()
                },
                "说明": "键级本地化目录；每个后续 JSONL 行均为 InformationItem 同构记录",
            }
            stream.write(json.dumps(header, ensure_ascii=False, separators=(",", ":")))
            stream.write("\n")
            for label, root in sorted(selected.items()):
                if not root.is_dir():
                    continue
                for path_item in _localization_paths(root):
                    files += 1
                    relative = path_item.relative_to(root).as_posix()
                    source = f"{label}/{relative}"
                    try:
                        raw = path_item.read_bytes()
                        digest = hashlib.sha256(raw).hexdigest()
                        text = raw.decode("utf-8-sig", errors="replace")
                        language, entries = parse_loc_entries_with_lines(text)
                    except OSError as exc:
                        errors += 1
                        stream.write(
                            json.dumps(
                                _unsupported_localization_record(
                                    label=label,
                                    source=source,
                                    digest=_path_digest(path_item),
                                    reason=f"读取异常 {type(exc).__name__}: {exc}",
                                ),
                                ensure_ascii=False,
                                separators=(",", ":"),
                            )
                            + "\n"
                        )
                        continue
                    counts: dict[str, int] = defaultdict(int)
                    for key, _value, line in entries:
                        counts[key] += 1
                        record = _localization_key_record(
                            label=label,
                            root=root,
                            path=path_item,
                            digest=digest,
                            language=language,
                            key=key,
                            line=line,
                            occurrence=counts[key],
                        )
                        stream.write(
                            json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
                        )
                        keys += 1
                    if language == "?":
                        errors += 1
                        stream.write(
                            json.dumps(
                                _unsupported_localization_record(
                                    label=label,
                                    source=source,
                                    digest=digest,
                                    reason="未发现语言头 l_<language>:",
                                ),
                                ensure_ascii=False,
                                separators=(",", ":"),
                            )
                            + "\n"
                        )
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
    except BaseException:
        with suppress(FileNotFoundError):
            Path(temporary).unlink()
        raise
    return {"files": files, "keys": keys, "errors": errors}


def _path_digest(path: Path) -> str:
    """读取失败时仍提供稳定、可审计的路径摘要，而不伪造内容摘要。"""

    return hashlib.sha256(f"unreadable:{path.as_posix()}".encode()).hexdigest()


def _unsupported_localization_record(
    *, label: str, source: str, digest: str, reason: str
) -> dict[str, object]:
    item = InformationItem(
        id=_item_id(f"{label}/localization", "__parse_error__", source),
        domain=f"{label}/localization",
        name="__parse_error__",
        source=source,
        source_sha256=digest,
        source_line=None,
        scope="language",
        unit="parse_error",
        update="static",
        visibility="public_localization",
        status=InformationStatus.UNSUPPORTED,
        impact=ImpactLevel.NO_CONSUMER,
        notes=f"本地化文件未形成键级目录：{reason}；键级本地化能力保持 unsupported",
    )
    return item.to_dict()


def build(
    *,
    roots: Mapping[str, Path] | None = None,
    version: Mapping[str, str] | None = None,
    include_localization: bool = True,
) -> InformationCatalog:
    """构建能力目录。

    ``roots`` 只用于测试或明确的快照/安装根；默认复用当前配置的三个内容根。
    目录建立在静态发现上；扫描、同名关联和静态字段合同都不能升级为运行期行为证据。
    """

    if roots is None:
        selected: dict[str, Path] = {
            "game": config.GAME,
            "jomini": config.JOMINI,
            "clausewitz": config.CLAUSEWITZ,
        }
        selected_version = dict(config.game_version())
    else:
        selected = {str(label): Path(root) for label, root in roots.items()}
        selected_version = {}
    if version is not None:
        selected_version = dict(version)

    for label, root in selected.items():
        if not root.is_dir():
            raise FileNotFoundError(f"信息目录内容根不可用：{label} ({root})")
    game = selected.get("game")
    consumers = _consumer_index(game)
    digest_cache: dict[Path, str] = {}
    items: list[InformationItem] = []
    for label, root in sorted(selected.items()):
        if not root.is_dir():
            continue
        items.extend(_script_items(label, root, consumers, digest_cache))
        if include_localization:
            items.extend(_localization_items(label, root, digest_cache))
    return InformationCatalog(
        version=selected_version,
        roots={label: str(root) for label, root in sorted(selected.items()) if root.is_dir()},
        items=tuple(items),
    )


__all__ = [
    "CATALOG_FORMAT",
    "DEFAULT_SCOPE",
    "DEFAULT_UNIT",
    "DEFAULT_UPDATE",
    "DEFAULT_VISIBILITY",
    "ImpactLevel",
    "InformationCatalog",
    "InformationItem",
    "InformationStatus",
    "build",
    "write_localization_catalog",
]
