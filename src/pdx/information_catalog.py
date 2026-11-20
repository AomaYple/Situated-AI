"""锁定游戏版本的 Mod 能力目录。

能力目录是开发期的单一事实入口：它把静态资源中发现的条目和字段
映射到稳定 ID、来源指纹和静态候选消费者关联。
静态发现不会被提升为运行时可读或行为通过；C2/F1 会在同一条记录上
逐项推进状态。

目录只保存可审计的元数据和第一层字段。字段值仍由原始脚本、快照或
分析产物按需读取，避免再建立一份与 ``pdx.analyze`` 重复的完整 AST 数据库。
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import stat
import tempfile
import zipfile
from collections import defaultdict
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING
from xml.parsers import expat

from . import ai_surface, config, political_surface, version_contracts
from .binary_headers import BINARY_HEADER_SUFFIXES, HEADER_BYTES, binary_header
from .cache import parse_cached
from .capability_catalog import FileDisposition, LayeredCatalog, OccurrenceWriter, base_frontier
from .committed_raw import (
    read_record,
    read_source,
    verified_catalog_inputs,
    verified_record,
    verified_source,
)
from .input_contracts import ArtifactRef, InputContractError, ParseStatus
from .input_inventory import (
    DEVELOPER_TEXT_PATHS,
    DEVELOPER_XML_ROOTS,
    EXTENSIONLESS_BODY_RESOURCE,
    FLAT_PDX_RESOURCE_SUFFIXES,
    MAP_ADJACENCIES,
    PDX_RESOURCE_CATEGORIES,
    STRUCTURED_JSON_SUFFIXES,
    classify_path,
)
from .localization import SUFFIXES, parse_loc_entries_with_lines
from .map_structure import map_structure_format, read_map_structure
from .model import Assignment, Block, ParseError, Scalar
from .parser import parse_bytes
from .research_coverage import FormatStructureEvidence
from .scan import FileEntry, walk_files
from .shader_structure import read_shader_structure
from .structured_csv import parse_map_table
from .structured_json import parse_json

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from typing import BinaryIO

    from .input_contracts import CaptureCheck, InputIdentity, InputInventory, InventoryRecord
    from .model import ParsedFile
    from .research_coverage import ResearchCoverage


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
            "条目": self._serialized_items(),
        }

    def _serialized_items(self) -> list[dict[str, object]]:
        return [item.to_dict() for item in self.items]

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


@dataclass(frozen=True, slots=True)
class ResearchInformationCatalog(InformationCatalog):
    """Canonical raw research report with independent source dispositions."""

    layered: LayeredCatalog = field(kw_only=True)
    final_installation_check: CaptureCheck | None = field(default=None, kw_only=True)
    format_evidence: tuple[FormatStructureEvidence, ...] = field(default=(), kw_only=True)
    research_coverage: ResearchCoverage | None = field(default=None, kw_only=True)
    format_version: int = 2

    def to_dict(self) -> dict[str, object]:
        result = InformationCatalog.to_dict(self)
        layers = self.layered.to_dict()
        if self.final_installation_check is not None:
            layers["installation_verification"] = {
                "input_identity_capture_check_scope": "initial_inventory",
                "final_inventory": asdict(self.final_installation_check),
            }
        if self.research_coverage is not None:
            layers["research_coverage"] = self.research_coverage.to_dict()
        result["分层目录"] = layers
        return result

    def _serialized_items(self) -> list[dict[str, object]]:
        statuses = {row.path: row.parse_status for row in self.layered.dispositions}
        return [
            {
                **item.to_dict(),
                "parse_status": statuses[item.source],
                "capability_status": "unknown",
            }
            for item in self.items
        ]


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
        try:
            parsed.require_complete()
        except ParseError as exc:
            items.append(
                _unsupported_script_item(
                    domain=domain,
                    source=source,
                    digest=digest,
                    reason="解析器报告错误：" + ("；".join(parsed.errors) or exc.detail),
                )
            )
            # 解析器可能仍返回部分 AST。部分树不能冒充完整发现，避免把
            # 不完整输入的字段误写成可消费能力；完整失败项保留在目录中。
            continue
        items.extend(_parsed_script_items(parsed, source, domain, digest, consumers))
    return items


def _parsed_script_items(
    parsed: ParsedFile,
    source: str,
    domain: str,
    digest: str,
    consumers: Mapping[str, tuple[tuple[str, ImpactLevel], ...]],
) -> list[InformationItem]:
    items: list[InformationItem] = []
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
        version_contracts.verify_installation_identity(config.ROOT)
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


def _zip_members(stream: BinaryIO) -> tuple[list[dict[str, object]], tuple[str, ...]]:
    """只登记成熟 ZIP reader 的安全映射，不提取、不执行、不推断许可。"""
    with zipfile.ZipFile(stream) as archive:
        entries = archive.infolist()
    counts: dict[str, int] = defaultdict(int)
    for entry in entries:
        counts[entry.filename.rstrip("/").casefold()] += 1
    members, errors = [], []
    for ordinal, entry in enumerate(entries):
        member = entry.filename.rstrip("/")
        reason = "safe_metadata_mapping_content_not_exported"
        try:
            ArtifactRef("evidence", member, "0" * 64)
        except InputContractError:
            reason = "unsafe_member_path"
        if counts[member.casefold()] != 1:
            reason = "duplicate_or_case_conflicting_member"
        if stat.S_ISLNK(entry.external_attr >> 16):
            reason = "symbolic_link_member_refused"
        if entry.flag_bits & 1:
            reason = "encrypted_member_no_read_permission"
        safe = reason == "safe_metadata_mapping_content_not_exported"
        if not safe:
            errors.append(f"{ordinal}:{entry.filename}:{reason}")
        members.append(
            {
                "ordinal": ordinal,
                "path": entry.filename,
                "size": entry.file_size,
                "compressed_size": entry.compress_size,
                "compression": entry.compress_type,
                "directory": entry.is_dir(),
                "safe_mapping": safe,
                "reason": reason,
                "content_status": "not_read",
                "content_sha256": None,
                "support_evidence": "python_standard_library_zipfile_metadata_only",
            }
        )
    return members, tuple(errors)


def _incomplete_script_item(
    *, domain: str, source: str, digest: str, reason: str
) -> InformationItem:
    """登记完整输入缺口；解析失败不能证明引擎不支持。"""

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
        status=InformationStatus.DISCOVERED,
        impact=ImpactLevel.NO_CONSUMER,
        notes=(
            "来源文件未形成可审计 AST；不得把部分结果当作完整能力。"
            f" {reason}；合法引擎读取能力保持 unknown，不能从部分树推导定义不存在"
        ),
    )


def _build_from_raw(
    *,
    identity: InputIdentity,
    inventory: InputInventory,
    index_path: Path,
    raw_root: Path,
) -> ResearchInformationCatalog:
    """Build a private staged index for research_catalog.write to publish."""
    destination = index_path.resolve()
    if any(
        destination.is_relative_to(root.resolve())
        for root in (raw_root, Path(identity.installation_root))
    ):
        raise ValueError("派生索引必须位于原始来源根之外")
    with verified_catalog_inputs(identity, inventory, raw_root=raw_root):
        return _build_research_index(identity, inventory, index_path, raw_root)


_DEVELOPER_XML_BYTE_LIMIT = 1024 * 1024


def _developer_xml_elements(
    raw: bytes, expected_root: str
) -> tuple[list[tuple[int, str]], str | None]:
    parser = expat.ParserCreate(encoding="UTF-8", namespace_separator=" ")
    elements: list[tuple[int, str]] = []
    name_length = 0

    def record_element(name: str, _attributes: dict[str, str]) -> None:
        nonlocal name_length
        if not elements and name != expected_root:
            raise ValueError("developer_xml_unexpected_root")
        # Expanded namespace names can be much larger than the source tags.
        name_length += len(name)
        if name_length > _DEVELOPER_XML_BYTE_LIMIT:
            raise ValueError("developer_xml_element_name_budget_exceeded")
        elements.append((parser.CurrentLineNumber, name))

    def refuse_doctype(*_args: object) -> None:
        raise ValueError("developer_xml_doctype_refused")

    parser.StartElementHandler = record_element
    parser.StartDoctypeDeclHandler = refuse_doctype
    try:
        parser.Parse(raw, True)
    except expat.ExpatError as error:
        return [], f"developer_xml_syntax_failed:{error.lineno}:{error.offset}"
    except ValueError as error:
        return [], str(error)
    return elements, None


def _build_research_index(
    identity: InputIdentity, inventory: InputInventory, index_path: Path, raw_root: Path | None
) -> ResearchInformationCatalog:
    items: list[InformationItem] = []
    dispositions: list[FileDisposition] = []
    format_evidence: list[FormatStructureEvidence] = []
    installation = Path(identity.installation_root)

    def read(
        record: InventoryRecord, *, retain: bool, prefix_size: int | None = None
    ) -> bytes | None:
        if raw_root is not None:
            return read_source(record, raw_root=raw_root, retain=retain, prefix_size=prefix_size)
        return read_record(
            record, root=installation, relative=record.path, retain=retain, prefix_size=prefix_size
        )

    with OccurrenceWriter(
        index_path, identity, inventory, metadata_only=raw_root is None
    ) as writer:
        for record in inventory.records:
            raw_status = "unknown"
            if record.read_status == "read":
                raw_status = "proven" if raw_root is not None else "observed"
            if record.path.partition("/")[0].casefold() == "%localappdata%":
                read(record, retain=False)
                row = FileDisposition(
                    path=record.path,
                    category=record.category,
                    raw_status=raw_status,
                    decode_status="not_attempted",
                    parse_status="not_attempted",
                    semantic_status="unknown",
                    disposition="research_only",
                    reason="local_state_not_projected",
                )
                dispositions.append(row)
                writer.add_source(record, row)
                continue
            suffix = Path(record.path).suffix.casefold()
            resource_category = PDX_RESOURCE_CATEGORIES.get(suffix)
            relative = record.path.casefold()
            if relative == EXTENSIONLESS_BODY_RESOURCE:
                resource_category = "asset_entity_dna"
            category = record.category
            map_table = relative == MAP_ADJACENCIES
            map_structure_selected = map_structure_format(record.path) is not None
            if category == "unknown" or map_table or suffix in FLAT_PDX_RESOURCE_SUFFIXES:
                # 历史盘点的类别属于已提交原件，更新只写入派生处置。
                category = classify_path(record.path)
            pdx_resource = resource_category is not None and category == resource_category
            script = category != "documentation" and (
                suffix in config.SCRIPTABLE_SUFFIXES
                or suffix in {".dna", ".entity", ".gfx", ".dlc"}
                or pdx_resource
            )
            localization = category == "localization"
            developer_text = relative in DEVELOPER_TEXT_PATHS
            document = category == "documentation" and (
                suffix in {".md", ".rst", ".txt", ".html", ".htm"} or developer_text
            )
            structured_json = (
                category == "structured_configuration" and suffix in STRUCTURED_JSON_SUFFIXES
            )
            xml_root = DEVELOPER_XML_ROOTS.get(relative)
            read_xml = xml_root is not None and (record.size or 0) <= _DEVELOPER_XML_BYTE_LIMIT
            shader_source = category == "shader_source"
            python_tool = category == "tooling_source"
            binary_probe = suffix in BINARY_HEADER_SUFFIXES and category in {
                "asset_entity_dna",
                "image_map",
            }
            header = None
            csv_result = None
            json_result = None
            zip_container = (
                category == "container" and suffix == ".zip" and record.read_status == "read"
            )
            raw = (
                None
                if zip_container
                else read(
                    record,
                    retain=script
                    or localization
                    or document
                    or structured_json
                    or read_xml
                    or developer_text
                    or map_table
                    or map_structure_selected
                    or shader_source
                    or python_tool
                    or binary_probe,
                    prefix_size=HEADER_BYTES if binary_probe else None,
                )
            )
            domain = record.path.rpartition("/")[0] or "."
            diagnostics = tuple(f"{d.code}: {d.message}" for d in record.diagnostics)
            locator_diagnostics = [diagnostic.code for diagnostic in record.diagnostics]
            parsed = None
            entries: list[tuple[str, str, int]] = []
            language = "?"
            members: list[dict[str, object]] = []
            text_lines: list[tuple[int, str]] = []
            xml_elements: list[tuple[int, str]] = []
            decode_status = "not_attempted"
            parse_status: ParseStatus = "not_attempted"
            disposition = "research_only"
            reason = "format_reader_not_implemented; raw retained for engineering research"
            if record.read_status != "read":
                reason = "source_not_read"
            elif script and raw is not None:
                parsed = parse_bytes(raw, record.path, encoding="utf-8-sig")
                if pdx_resource and parsed.parse_status == "complete":
                    # 通用 parser 也接受裸标量。这些资料的完整结构至少须包含一块。
                    if b"\x00" in raw:
                        parsed.errors.append("pdx_resource_contains_nul")
                        locator_diagnostics.append("pdx_resource_contains_nul")
                    elif suffix in FLAT_PDX_RESOURCE_SUFFIXES:
                        if not parsed.root.items or any(
                            not isinstance(item, Assignment)
                            or not isinstance(item.value, Scalar)
                            or item.op != "="
                            for item in parsed.root.items
                        ):
                            parsed.errors.append("pdx_resource_expected_flat_scalar_assignments")
                            locator_diagnostics.append(
                                "pdx_resource_expected_flat_scalar_assignments"
                            )
                    elif parsed.max_depth == 0:
                        parsed.errors.append("pdx_resource_missing_top_level_block")
                        locator_diagnostics.append("pdx_resource_missing_top_level_block")
                parse_status = parsed.parse_status
                decode_status = "failed" if parsed.decoding_error else "complete"
                diagnostics += tuple(parsed.errors)
                locator_diagnostics.extend(
                    f"{entry['kind']}:{entry['line']}:{entry['column']}"
                    for entry in parsed.diagnostics
                )
                if parsed.decoding_error is not None:
                    diagnostics += (parsed.decoding_error,)
                    locator_diagnostics.append("pdx_decode_failed")
                    reason = "pdx_decode_failed"
                elif parse_status != "complete":
                    reason = "shared_parser_incomplete"
                else:
                    reason = "PDX syntax and full occurrence index; exact engine semantics require separate evidence"
            elif map_table and raw is not None:
                csv_result = parse_map_table(raw)
                decode_status, parse_status = csv_result.decode_status, csv_result.parse_status
                diagnostics += csv_result.diagnostics
                for message in csv_result.diagnostics:
                    location = re.match(r"^csv_[a-z_]+(?::[0-9]+(?=:))?", message)
                    if location:
                        locator_diagnostics.append(location[0])
                reason = (
                    "map CSV rows and cells indexed; map interpretation requires separate evidence"
                )
            elif structured_json and raw is not None:
                json_result = parse_json(raw)
                decode_status, parse_status = json_result.decode_status, json_result.parse_status
                diagnostics += json_result.diagnostics
                locator_diagnostics.extend(
                    message.partition(":")[0] for message in json_result.diagnostics
                )
                reason = (
                    "complete ordered JSON tree; engine semantics and Unicode interoperability unproven"
                    if parse_status == "complete"
                    else "structured_json_decode_or_parse_failed"
                )
            elif xml_root is not None:
                if raw is None:
                    reason = "developer_xml_byte_budget_exceeded"
                    locator_diagnostics.append(reason)
                    diagnostics += (reason,)
                else:
                    try:
                        raw.decode("utf-8-sig")
                    except UnicodeDecodeError as error:
                        decode_status, parse_status = "failed", "failed"
                        reason = "developer_xml_decode_failed"
                        diagnostic = f"{reason}:byte:{error.start}"
                        diagnostics += (diagnostic,)
                        locator_diagnostics.append(diagnostic)
                    else:
                        decode_status = "complete"
                        xml_elements, error_code = _developer_xml_elements(raw, xml_root)
                        if error_code is None:
                            parse_status = "complete"
                            reason = "well-formed developer XML and element locations indexed"
                        else:
                            parse_status = "failed"
                            reason = "developer_xml_parse_failed"
                            diagnostics += (error_code,)
                            locator_diagnostics.append(error_code)
            elif localization and raw is not None:
                unconsumed: list[tuple[int, str]] = []
                try:
                    text = raw.decode("utf-8-sig")
                except UnicodeDecodeError as error:
                    decode_status, parse_status = "failed", "failed"
                    diagnostics += (str(error),)
                    reason = "localization_decode_failed"
                    locator_diagnostics.append(f"localization_decode_failed:byte:{error.start}")
                else:
                    decode_status = "complete"
                    language, entries = parse_loc_entries_with_lines(
                        text, unconsumed_lines=unconsumed
                    )
                    parse_status = "complete" if language != "?" and not unconsumed else "partial"
                    reason = "all localization languages indexed; engine loading and GUI presentation unproven"
                    if unconsumed or language == "?":
                        diagnostics += (f"language={language}; unconsumed={unconsumed}",)
                        locator_diagnostics.extend(
                            f"localization_unconsumed_line:{line}" for line, _ in unconsumed
                        )
                        if language == "?":
                            locator_diagnostics.append("localization_unknown_language")
            elif zip_container:
                stream_context = (
                    verified_source(record, raw_root=raw_root)
                    if raw_root is not None
                    else verified_record(record, root=installation, relative=record.path)
                )
                with stream_context as stream:
                    try:
                        members, errors = _zip_members(stream)
                    except zipfile.BadZipFile as error:
                        parse_status, reason = "failed", "invalid_zip_container"
                        diagnostics += (str(error),)
                        locator_diagnostics.append("invalid_zip_container")
                    else:
                        parse_status = "partial" if errors else "complete"
                        reason = "safe ZIP metadata mapping; member content/export/license not established"
                        diagnostics += errors
                        locator_diagnostics.extend(
                            f"{message.rpartition(':')[2]}:member:{message.partition(':')[0]}"
                            for message in errors
                        )
            elif (document or shader_source or python_tool or developer_text) and raw is not None:
                try:
                    text = raw.decode("utf-8-sig")
                except UnicodeDecodeError as error:
                    decode_status, parse_status = "failed", "failed"
                    diagnostics += (str(error),)
                    format_name = "document" if document else category
                    reason = f"{format_name}_decode_failed_no_declared_alternative_codec"
                    locator_diagnostics.append(f"{format_name}_decode_failed:byte:{error.start}")
                else:
                    decode_status = "complete"
                    text_lines = list(enumerate(text.splitlines(), 1))
                    if document:
                        parse_status = "not_applicable"
                        reason = "full document line index; source version bound to epoch; engine export not executed"
                    elif python_tool:
                        try:
                            ast.parse(text, filename=record.path)
                        except (SyntaxError, RecursionError) as error:
                            parse_status = "failed"
                            reason = "tooling_python_syntax_failed"
                            syntax_location = (
                                f":{error.lineno}:{error.offset}"
                                if isinstance(error, SyntaxError)
                                else ""
                            )
                            diagnostics += (f"{reason}{syntax_location}",)
                            locator_diagnostics.append(f"{reason}{syntax_location}")
                        else:
                            parse_status = "complete"
                            reason = "Python syntax and source line index; tool not executed"
                    elif developer_text:
                        reason = "developer text lines indexed; editor format not interpreted"
                    else:
                        reason = "shader source lines indexed; shader declarations have separate structure evidence"
            elif binary_probe and raw is not None:
                header = binary_header(suffix, raw)
                reason = f"binary_header_{header['status']}; payload parser unavailable"
                assert record.sha256 is not None
                structure_status: ParseStatus = (
                    "complete" if header["status"] == "observed" else "failed"
                )
                format_evidence.append(
                    FormatStructureEvidence(
                        ArtifactRef("installation", record.path, record.sha256),
                        suffix.removeprefix("."),
                        structure_status,
                        "metadata",
                    )
                )
            elif category in {"image_map", "font", "audio_video", "binary"}:
                parse_status = "not_applicable"
                reason = "binary/media raw engineering input; no text reader or engine observation inferred"
            elif category == "documentation":
                reason = "documentation raw retained; actual document version/export context not yet audited"
            elif category == "container":
                reason = (
                    "container raw retained; safe member mapping and format/license support pending"
                )
            elif category == "unknown":
                disposition, reason = (
                    "unresolved",
                    "unknown format retained; discovery cannot be silently excluded",
                )
            if raw_root is None:
                diagnostics = tuple(locator_diagnostics)
            row = FileDisposition(
                record.path,
                category,
                raw_status,
                decode_status,
                parse_status,
                "unknown",
                disposition,
                reason,
                diagnostics,
            )
            dispositions.append(row)
            writer.add_source(record, row)
            if header is not None:
                writer.add_details(record.path, binary_header=header)
            if raw is not None and record.sha256 is not None:
                map_structure = (
                    read_map_structure(record.path, raw, parsed=parsed)
                    if map_structure_selected
                    else None
                )
                shader_structure = (
                    read_shader_structure(record.path, raw) if shader_source else None
                )
                if map_structure is not None:
                    writer.add_details(record.path, map_structure=asdict(map_structure))
                if shader_structure is not None:
                    writer.add_details(record.path, shader_structure=asdict(shader_structure))
                format_evidence.extend(
                    FormatStructureEvidence(
                        ArtifactRef("installation", record.path, record.sha256),
                        structure.format,
                        structure.status,
                        "metadata",
                    )
                    for structure in (map_structure, shader_structure)
                    if structure is not None
                )
            if localization:
                writer.add_details(record.path, localization_language=language)
            writer.add_container_members(record.path, members)
            if csv_result is not None:
                writer.add_map_table(record, csv_result)
            if json_result is not None:
                writer.add_structured_json(record, json_result)
            if parsed is not None:
                writer.add_parsed(record, parsed)
                if raw_root is None:
                    continue
                if parsed.parse_status == "complete":
                    items.extend(
                        _parsed_script_items(
                            parsed,
                            source=record.path,
                            domain=domain,
                            digest=record.sha256 or "",
                            consumers={},
                        )
                    )
                else:
                    items.append(
                        _incomplete_script_item(
                            domain=domain,
                            source=record.path,
                            digest=record.sha256 or "",
                            reason="; ".join(diagnostics),
                        )
                    )
            elif record.sha256 is not None:
                if raw_root is not None:
                    items.append(
                        InformationItem(
                            id=_item_id(domain, "__source__", record.path),
                            domain=domain,
                            name="__source__",
                            source=record.path,
                            source_sha256=record.sha256,
                            source_line=None,
                            notes=reason,
                        )
                    )
                for ordinal, (key, value, line) in enumerate(entries):
                    writer.add(
                        record.path,
                        record.sha256 or "",
                        address=(ordinal,),
                        path=(language, key),
                        kind="localization",
                        key=key,
                        operator=None,
                        scalar=value,
                        quoted=True,
                        line=line,
                        parse_status=parse_status,
                    )
                for line, text in text_lines:
                    writer.add(
                        record.path,
                        record.sha256 or "",
                        address=(line,),
                        path=("line", str(line)),
                        kind="document_line" if document else "source_line",
                        key=None,
                        operator=None,
                        scalar=text,
                        quoted=True,
                        line=line,
                        parse_status=parse_status,
                    )
                for ordinal, (line, name) in enumerate(xml_elements):
                    writer.add(
                        record.path,
                        record.sha256,
                        address=(ordinal,),
                        path=("xml_element", str(ordinal)),
                        kind="xml_element",
                        key=name,
                        operator=None,
                        scalar=None,
                        quoted=False,
                        line=line,
                        parse_status=parse_status,
                    )
        index = writer.publish()
    rows = tuple(dispositions)
    return ResearchInformationCatalog(
        version={
            "caligula_branch": f"release/{identity.version}",
            "build_id": identity.build_id,
            "branch": identity.branch,
        },
        roots={"raw": str(raw_root)}
        if raw_root is not None
        else {"installation": str(installation)},
        items=tuple(items),
        layered=LayeredCatalog(
            identity, inventory, rows, index, base_frontier(identity, rows), raw_root
        ),
        format_evidence=tuple(format_evidence),
    )


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
        version_contracts.verify_installation_identity(config.ROOT)
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
