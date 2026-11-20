"""Layered research facts and a rebuildable occurrence index.

Indexes and reference candidates describe syntax. They do not grant engine access
or connect products to the game.
"""

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from collections import Counter
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from . import script_research_index
from .committed_raw import read_source, validate_inputs, verified_catalog_inputs
from .input_contracts import UnknownFrontier, dumps_contract
from .input_inventory import STRUCTURED_JSON_SUFFIXES, open_inventory_source
from .model import Assignment, Block, ParsedFile, Scalar
from .parser import PREFIXES
from .references import SCRIPT_SYMBOL_CATEGORIES, script_symbol_references
from .structured_json import JsonDocument, JsonResult, load_payload, parse_json

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Set
    from typing import Any

    from .input_contracts import InputIdentity, InputInventory, InventoryRecord, ParseStatus
    from .script_research import ScriptDefinition, ScriptReference
    from .structured_csv import CsvResult


INDEX_SCHEMA = 3
# Published schema-3 locator indexes from the two 1.15.2 installation scans.
_HISTORICAL_LOCATOR_IMPLEMENTATIONS = frozenset(
    {
        "dc59ca49f90deacb74690c128e1727aa99fb328cd009164708fe520114f0b0bd",
        "204381950006cc8241098aa12ac46042a3c2b719b8014cf5623e53ccabefa6e1",
    }
)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def implementation_digest() -> str:
    """绑定实际格式/parser/交接实现字节，不使用 mtime 或自由版本标签。"""
    root = Path(__file__).parent
    names = (
        "input_contracts.py",
        "input_inventory.py",
        "lexer.py",
        "config.py",
        "version_contracts.py",
        "model.py",
        "parser.py",
        "localization.py",
        "information_catalog.py",
        "capability_catalog.py",
        "committed_raw.py",
        "references.py",
        "structured_csv.py",
        "structured_json.py",
        "research_catalog.py",
        "research_coverage.py",
        "research_output.py",
        "native_rename.py",
        "binary_headers.py",
        "map_structure.py",
        "shader_structure.py",
        "script_research.py",
        "script_research_index.py",
    )
    return hashlib.sha256(
        _json([(name, _digest(root / name)) for name in names]).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class Occurrence:
    id: str
    source: str
    source_sha256: str
    parent_id: str | None
    address: tuple[int, ...]
    path: tuple[str, ...]
    kind: str
    key: str | None
    operator: str | None
    scalar: str | None
    quoted: bool
    line: int
    parse_status: ParseStatus
    value_kind: str
    value_line: int | None


def _occurrence(row: sqlite3.Row) -> Occurrence:
    return Occurrence(
        row["id"],
        row["source"],
        row["source_sha256"],
        row["parent_id"],
        tuple(json.loads(row["address"])),
        tuple(json.loads(row["path"])),
        row["kind"],
        row["key"],
        row["operator"],
        row["scalar"],
        bool(row["quoted"]),
        row["line"],
        row["parse_status"],
        row["value_kind"],
        row["value_line"],
    )


@dataclass(frozen=True, slots=True)
class ResearchReference:
    occurrence_id: str
    value: str
    kind: str
    target_ids: tuple[str, ...]
    status: str
    evidence: str = "research_name_candidates_not_engine_semantics"


@dataclass(frozen=True, slots=True)
class OccurrenceIndex:
    path: Path
    epoch_id: str
    file_set_sha256: str
    implementation_sha256: str
    sha256: str
    occurrence_count: int
    file_count: int

    def implementation_status(self, *, historical_locators: bool = False) -> str:
        if self.implementation_sha256 == implementation_digest():
            return "current"
        if (
            historical_locators
            and self.implementation_sha256 in _HISTORICAL_LOCATOR_IMPLEMENTATIONS
        ):
            return "historical_locators"
        raise ValueError("出现位置索引解析实现已改变，必须重建或显式读取已登记的历史定位")

    @contextmanager
    def connect(self, *, historical_locators: bool = False) -> Iterator[sqlite3.Connection]:
        self.implementation_status(historical_locators=historical_locators)
        with open_inventory_source(self.path.parent.absolute(), self.path.name) as stream:
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
            if digest.hexdigest() != self.sha256:
                raise ValueError("出现位置索引摘要漂移 digest mismatch")
            connection = sqlite3.connect(
                self.path.absolute().as_uri() + "?mode=ro&immutable=1", uri=True
            )
            connection.row_factory = sqlite3.Row
            try:
                metadata = dict(connection.execute("SELECT key,value FROM metadata"))
                expected = {
                    "schema": str(INDEX_SCHEMA),
                    "epoch_id": self.epoch_id,
                    "file_set_sha256": self.file_set_sha256,
                    "implementation_sha256": self.implementation_sha256,
                    "state": "complete",
                    "file_count": str(self.file_count),
                    "occurrence_count": str(self.occurrence_count),
                }
                if metadata != expected:
                    raise ValueError("出现位置索引 epoch/来源/实现身份不匹配")
                yield connection
            finally:
                connection.close()

    @staticmethod
    def find_in_connection(
        connection: sqlite3.Connection,
        *,
        source: str | None = None,
        key: str | None = None,
        scalar: str | None = None,
        path: tuple[str, ...] | None = None,
        after: str = "",
        limit: int | None = None,
    ) -> tuple[Occurrence, ...]:
        """完整查询或按稳定 ID 分页；默认无 sample limit。"""
        if limit is not None and (type(limit) is not int or limit <= 0):
            raise ValueError("limit 必须是正整数")
        clauses, values = ["id > ?"], [after]
        for column, value in (
            ("source", source),
            ("key", key),
            ("scalar", scalar),
            ("path", None if path is None else _json(path)),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                values.append(value)
        query = "SELECT * FROM occurrences WHERE " + " AND ".join(clauses) + " ORDER BY id"
        if limit is not None:
            query += " LIMIT ?"
            values.append(limit)  # type: ignore[arg-type]
        return tuple(_occurrence(row) for row in connection.execute(query, values))

    def find(
        self,
        *,
        source: str | None = None,
        key: str | None = None,
        scalar: str | None = None,
        path: tuple[str, ...] | None = None,
        after: str = "",
        limit: int | None = None,
    ) -> tuple[Occurrence, ...]:
        with self.connect() as connection:
            return self.find_in_connection(
                connection,
                source=source,
                key=key,
                scalar=scalar,
                path=path,
                after=after,
                limit=limit,
            )

    def ancestors(self, occurrence_id: str) -> tuple[Occurrence, ...]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM occurrences WHERE id=?", (occurrence_id,)
            ).fetchone()
            if row is None:
                raise KeyError(occurrence_id)
            parents = []
            while row["parent_id"] is not None:
                row = connection.execute(
                    "SELECT * FROM occurrences WHERE id=?", (row["parent_id"],)
                ).fetchone()
                if row is None:
                    raise ValueError("出现位置索引缺父结构")
                parents.append(_occurrence(row))
            return tuple(reversed(parents))

    def references(self, *, value: str, source: str | None = None) -> tuple[ResearchReference, ...]:
        """全部标量均可检索；候选目标不等于已证明的语义依赖边。"""
        with self.connect() as connection:
            query = "SELECT * FROM occurrences WHERE scalar=?"
            arguments = [value]
            if source is not None:
                query += " AND source=?"
                arguments.append(source)
            rows = connection.execute(query + " ORDER BY id", arguments)
            result = []
            for row in rows:
                variable = value.startswith("@")
                target_query = "SELECT id FROM occurrences WHERE key=?"
                target_arguments = [value]
                if variable:
                    target_query += " AND source=?"
                    target_arguments.append(row["source"])
                else:
                    target_query += " AND parent_id IS NULL"
                targets = tuple(
                    item[0]
                    for item in connection.execute(target_query + " ORDER BY id", target_arguments)
                )
                status = (
                    "unresolved"
                    if not targets
                    else "candidate"
                    if len(targets) == 1
                    else "ambiguous"
                )
                result.append(
                    ResearchReference(
                        row["id"], value, "variable" if variable else "symbol", targets, status
                    )
                )
            return tuple(result)

    def audit_dependencies(self, *, source: str, path: tuple[str, ...]) -> DependencyAudit:
        """原始父结构、全子树、递归变量/同名定义候选；缺口不被解释成无依赖。"""
        with self.connect() as connection:
            return _audit_dependencies(connection, source=source, path=path)

    def search_text(self, text: str, *, source: str | None = None) -> tuple[Occurrence, ...]:
        if not text:
            raise ValueError("检索文本不能为空")
        query, args = "SELECT * FROM occurrences WHERE instr(scalar,?) > 0", [text]
        if source is not None:
            query += " AND source=?"
            args.append(source)
        with self.connect() as connection:
            return tuple(
                _occurrence(row) for row in connection.execute(query + " ORDER BY id", args)
            )

    @staticmethod
    def source_metadata_in_connection(
        connection: sqlite3.Connection, source: str
    ) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT details FROM source_details WHERE source=?", (source,)
        ).fetchone()
        if row is None:
            return None
        result = json.loads(row[0])
        if not isinstance(result, dict):
            raise ValueError("来源元数据不是对象")
        return result

    def source_metadata(self, source: str) -> dict[str, Any]:
        with self.connect() as connection:
            result = self.source_metadata_in_connection(connection, source)
            if result is None:
                raise KeyError(source)
            return result

    def container_members(self, source: str) -> tuple[dict[str, Any], ...]:
        with self.connect() as connection:
            return tuple(
                json.loads(row[0])
                for row in connection.execute(
                    "SELECT details FROM container_members WHERE source=? ORDER BY ordinal",
                    (source,),
                )
            )

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["path"] = str(self.path)
        result["schema"] = INDEX_SCHEMA
        result["evidence"] = "derived_syntax_and_reference_candidates_only"
        return result


def _occurrence_id(source: str, address: tuple[int, ...]) -> str:
    return hashlib.sha256(_json((source, address)).encode()).hexdigest()


class OccurrenceWriter:
    """一次构建事务；异常或中断不发布候选，也不覆盖上一次索引。"""

    def __init__(
        self,
        path: Path,
        identity: InputIdentity,
        inventory: InputInventory,
        *,
        metadata_only: bool = False,
    ) -> None:
        self.path, self.identity, self.inventory = path, identity, inventory
        self.metadata_only = metadata_only
        self.implementation = implementation_digest()
        self.count = self.files = 0
        self.connection: sqlite3.Connection
        self.temporary: Path

    def __enter__(self) -> OccurrenceWriter:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        os.close(descriptor)
        self.temporary = Path(temporary)
        self.connection = sqlite3.connect(self.temporary)
        try:
            self.connection.executescript("""
                PRAGMA foreign_keys=ON;
                CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE sources(path TEXT PRIMARY KEY,sha256 TEXT,size INTEGER,
                  disposition TEXT NOT NULL,parse_status TEXT NOT NULL);
                CREATE TABLE source_details(source TEXT PRIMARY KEY REFERENCES sources(path), details TEXT NOT NULL);
                CREATE TABLE container_members(source TEXT REFERENCES sources(path),ordinal INTEGER,
                  details TEXT NOT NULL, PRIMARY KEY(source,ordinal));
                CREATE TABLE occurrences(id TEXT PRIMARY KEY,source TEXT NOT NULL REFERENCES sources(path),
                  source_sha256 TEXT NOT NULL,parent_id TEXT REFERENCES occurrences(id),
                  address TEXT NOT NULL,path TEXT NOT NULL,kind TEXT NOT NULL,key TEXT,
                  operator TEXT,scalar TEXT,quoted INTEGER NOT NULL,line INTEGER NOT NULL,
                  parse_status TEXT NOT NULL,value_kind TEXT NOT NULL,value_line INTEGER,
                  UNIQUE(source,address));
                CREATE INDEX occurrence_key ON occurrences(key);
                CREATE INDEX occurrence_scalar ON occurrences(scalar);
                CREATE INDEX occurrence_source_path ON occurrences(source,path);
            """)
            script_research_index.create_tables(self.connection)
        except BaseException:
            self.__exit__(True, None, None)
            raise
        return self

    def add_source(self, record: InventoryRecord, disposition: FileDisposition) -> None:
        self.connection.execute(
            "INSERT INTO sources VALUES(?,?,?,?,?)",
            (
                record.path,
                record.sha256,
                record.size,
                disposition.disposition,
                disposition.parse_status,
            ),
        )
        self.files += 1
        self.connection.execute(
            "INSERT INTO source_details VALUES(?,?)",
            (
                record.path,
                _json(
                    {
                        "inventory": asdict(record),
                        "disposition": asdict(disposition),
                        "version": self.identity.version,
                        "build_id": self.identity.build_id,
                        "document_version_status": "source_bound_to_epoch_not_independent_document_release",
                        "engine_export": {
                            "status": "not_executed",
                            "command": None,
                            "time": None,
                            "context": None,
                        },
                    }
                ),
            ),
        )

    def add_container_members(self, source: str, members: Iterable[Mapping[str, Any]]) -> None:
        self.connection.executemany(
            "INSERT INTO container_members VALUES(?,?,?)",
            ((source, ordinal, _json(dict(member))) for ordinal, member in enumerate(members)),
        )

    def add_details(self, source: str, **values: object) -> None:
        row = self.connection.execute(
            "SELECT details FROM source_details WHERE source=?", (source,)
        ).fetchone()
        details = json.loads(row[0])
        details.update(values)
        self.connection.execute(
            "UPDATE source_details SET details=? WHERE source=?", (_json(details), source)
        )

    def add_script_source(self, source: str, definition_kind: str | None) -> None:
        script_research_index.add_source(self.connection, source, definition_kind)

    def add_script_rows(
        self,
        definitions: Iterable[ScriptDefinition],
        references: Iterable[ScriptReference],
        incomplete_definition_kinds: Set[str],
    ) -> None:
        script_research_index.add_source_rows(
            self.connection, definitions, references, incomplete_definition_kinds, _occurrence_id
        )

    def add(
        self,
        source: str,
        sha256: str,
        *,
        address: tuple[int, ...],
        path: tuple[str, ...],
        kind: str,
        key: str | None,
        operator: str | None,
        scalar: str | None,
        quoted: bool,
        line: int,
        parse_status: ParseStatus,
        parent: str | None = None,
        value_kind: str = "scalar",
        value_line: int | None = None,
    ) -> str:
        occurrence_id = _occurrence_id(source, address)
        self.connection.execute(
            "INSERT INTO occurrences VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                occurrence_id,
                source,
                sha256,
                parent,
                _json(address),
                _json(path),
                kind,
                key,
                operator,
                None if self.metadata_only else scalar,
                int(quoted),
                line,
                parse_status,
                value_kind,
                value_line,
            ),
        )
        self.count += 1
        return occurrence_id

    def add_structured_json(self, record: InventoryRecord, result: JsonResult) -> None:
        if not self.metadata_only:
            self.add_details(record.path, structured_json=_json_details(result))
        else:
            document = result.document
            self.add_details(
                record.path,
                structured_json_node_count=0 if document is None else len(document.nodes),
            )
        if result.document is not None:
            assert record.sha256 is not None
            assert result.root_line is not None
            self.add(
                record.path,
                record.sha256,
                address=(),
                path=(),
                kind="json_root",
                key=None,
                operator=None,
                scalar=None,
                quoted=False,
                line=result.root_line,
                parse_status="complete",
                value_kind="json_document",
                value_line=result.root_line,
            )

    def add_map_table(self, record: InventoryRecord, result: CsvResult) -> None:
        assert record.sha256 is not None
        header = result.rows[0].cells if result.rows else ()
        self.add_details(
            record.path,
            structured_csv={
                "delimiter": ";",
                "columns": len(header),
                "header": () if self.metadata_only else header,
                "rows_read": len(result.rows),
            },
        )
        for ordinal, row in enumerate(result.rows):
            path = ("row", str(ordinal))
            parent = self.add(
                record.path,
                record.sha256,
                address=(ordinal,),
                path=path,
                kind="csv_row" if ordinal else "csv_header",
                key=None,
                operator=None,
                scalar=None,
                quoted=False,
                line=row.line,
                parse_status=result.parse_status,
                value_kind="csv_row",
            )
            for column, cell in enumerate(row.cells):
                key = header[column] if column < len(header) else None
                self.add(
                    record.path,
                    record.sha256,
                    address=(ordinal, column),
                    path=(*path, str(column)),
                    kind="csv_cell",
                    key=key,
                    operator=None,
                    scalar=cell,
                    quoted=False,
                    line=row.line,
                    parse_status=result.parse_status,
                    parent=parent,
                    value_kind="csv_text",
                )

    def add_parsed(self, record: InventoryRecord, parsed: ParsedFile) -> None:
        assert record.sha256 is not None
        if not self.metadata_only:
            details = {
                name: getattr(parsed, name)
                for name in (
                    "encoding",
                    "had_bom",
                    "errors",
                    "max_depth",
                    "unconsumed_tokens",
                    "diagnostics",
                    "token_count",
                    "decoding_error",
                )
            }
            details.update(raw_sha256=record.sha256, raw_size=record.size)
            self.add_details(record.path, parser=details)
        # 显式栈保留匿名块、裸标量与重复赋值；不让目录遍历比共享 parser 更易栈溢出。
        stack: list[
            tuple[Assignment | Block | Scalar, tuple[int, ...], tuple[str, ...], str | None]
        ] = [
            (node, (index,), (), None)
            for index, node in reversed(list(enumerate(parsed.root.items)))
        ]
        while stack:
            node, address, parent_path, parent = stack.pop()
            if isinstance(node, Assignment):
                path, kind, key, operator = (
                    (*parent_path, node.full_key),
                    "assignment",
                    node.full_key,
                    node.op,
                )
                value = node.value
                scalar = value.text if isinstance(value, Scalar) else None
                quoted = isinstance(value, Scalar) and value.quoted
                child = value if isinstance(value, Block) else None
            elif isinstance(node, Block):
                path, kind, key, operator, scalar, quoted, child = (
                    (*parent_path, "[]"),
                    "block",
                    None,
                    None,
                    None,
                    False,
                    node,
                )
            else:
                path, kind, key, operator, scalar, quoted, child = (
                    parent_path,
                    "scalar",
                    None,
                    None,
                    node.text,
                    node.quoted,
                    None,
                )
            occurrence_id = self.add(
                record.path,
                record.sha256,
                address=address,
                path=path,
                kind=kind,
                key=key,
                operator=operator,
                scalar=scalar,
                quoted=quoted,
                line=node.line,
                value_line=node.value.line
                if isinstance(node, Assignment) and node.value is not None
                else None,
                parse_status=parsed.parse_status,
                parent=parent,
                value_kind="block"
                if child is not None
                else "scalar"
                if scalar is not None
                else "missing",
            )
            if child is not None:
                stack.extend(
                    (item, (*address, index), path, occurrence_id)
                    for index, item in reversed(list(enumerate(child.items)))
                )
        for ordinal, (line, comment) in enumerate(parsed.comments):
            self.add(
                record.path,
                record.sha256,
                address=(-1, ordinal),
                path=("#comment",),
                kind="comment",
                key=None,
                operator=None,
                scalar=comment,
                quoted=True,
                line=line,
                parse_status=parsed.parse_status,
            )

    def publish(self) -> OccurrenceIndex:
        if self.files != len(self.inventory.records):
            raise ValueError("索引来源分母不完整，不能发布")
        if implementation_digest() != self.implementation:
            raise ValueError("构建期间解析实现漂移，不能发布")
        metadata = {
            "schema": str(INDEX_SCHEMA),
            "epoch_id": self.identity.epoch_id,
            "file_set_sha256": self.identity.file_set_sha256,
            "implementation_sha256": self.implementation,
            "state": "complete",
            "file_count": str(self.files),
            "occurrence_count": str(self.count),
        }
        self.connection.executemany("INSERT INTO metadata VALUES(?,?)", metadata.items())
        self.connection.commit()
        if self.connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("索引引用/父结构不完整")
        self.connection.close()
        with self.temporary.open("r+b") as stream:
            os.fsync(stream.fileno())
        self.temporary.replace(self.path)
        return OccurrenceIndex(
            self.path,
            self.identity.epoch_id,
            self.identity.file_set_sha256,
            self.implementation,
            _digest(self.path),
            self.count,
            self.files,
        )

    def __exit__(self, *exc: object) -> None:
        self.connection.close()
        with suppress(FileNotFoundError):
            self.temporary.unlink()


@dataclass(frozen=True, slots=True)
class FileDisposition:
    path: str
    category: str
    raw_status: str
    decode_status: str
    parse_status: ParseStatus
    semantic_status: str
    disposition: str
    reason: str
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LayerCoverage:
    layer: str
    unit: str
    total: int
    known: int
    unknown: int
    not_applicable: int = 0
    denominator_status: str = "complete"

    @property
    def ratio(self) -> float | None:
        if self.denominator_status != "complete" or not self.total:
            return None
        return self.known / self.total


@dataclass(slots=True)
class _FormatCoverage:
    category: str
    suffix: str
    sources: int = 0
    bytes: int = 0
    decode_status: Counter[str] = field(default_factory=Counter)
    parse_status: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True, slots=True)
class LayeredCatalog:
    identity: InputIdentity
    inventory: InputInventory
    dispositions: tuple[FileDisposition, ...]
    index: OccurrenceIndex
    frontier: tuple[UnknownFrontier, ...]
    raw_root: Path | None

    def __post_init__(self) -> None:
        validate_inputs(self.identity, self.inventory)
        if tuple(row.path for row in self.dispositions) != tuple(
            row.path for row in self.inventory.records
        ):
            raise ValueError("目录处置与完整安装分母不相同")
        if (self.index.epoch_id, self.index.file_set_sha256, self.index.file_count) != (
            self.epoch_id,
            self.identity.file_set_sha256,
            len(self.inventory.records),
        ):
            raise ValueError("分层目录与索引 epoch/分母不相同")
        if self.raw_root is None:
            if any(record.raw is not None for record in self.inventory.records) or any(
                row.raw_status != "observed" for row in self.dispositions
            ):
                raise ValueError("现场来源目录必须逐项核验且不声明原件保全")
        else:
            with verified_catalog_inputs(self.identity, self.inventory, raw_root=self.raw_root):
                if any(row.raw_status != "proven" for row in self.dispositions):
                    raise ValueError("完整 raw 分母存在未验证的逐项处置")

    @property
    def epoch_id(self) -> str:
        return self.identity.epoch_id

    @property
    def coverage(self) -> tuple[LayerCoverage, ...]:
        total = len(self.dispositions)
        raw = sum(row.raw_status in {"proven", "observed"} for row in self.dispositions)
        parsed = sum(row.parse_status == "complete" for row in self.dispositions)
        na = sum(row.parse_status == "not_applicable" for row in self.dispositions)
        denominator = (
            "complete"
            if self.identity.completeness == self.inventory.completeness == "complete"
            else "partial"
        )
        unit = "installation_files"
        syntax_denominator = (
            "complete"
            if all(row.parse_status in {"complete", "not_applicable"} for row in self.dispositions)
            else "partial"
        )
        return (
            LayerCoverage(
                "raw" if self.raw_root is not None else "source_bytes",
                unit,
                total,
                raw,
                total - raw,
                denominator_status=denominator,
            ),
            LayerCoverage(
                "decode_parse",
                unit,
                total,
                parsed,
                total - parsed - na,
                na,
                denominator,
            ),
            LayerCoverage(
                "semantic",
                "indexed_occurrences",
                self.index.occurrence_count,
                0,
                self.index.occurrence_count,
                denominator_status=syntax_denominator,
            ),
            LayerCoverage("lawful_read", "exact_contexts", 0, 0, 0, denominator_status="unknown"),
            LayerCoverage("production", "consumer_closures", 0, 0, 0, denominator_status="unknown"),
        )

    def _coverage_by_format(self) -> list[dict[str, object]]:
        formats: dict[tuple[str, str], _FormatCoverage] = {}
        for record, disposition in zip(self.inventory.records, self.dispositions, strict=True):
            key = (disposition.category, Path(record.path).suffix.casefold())
            row = formats.get(key)
            if row is None:
                row = formats[key] = _FormatCoverage(*key)
            row.sources += 1
            row.bytes += record.size or 0
            row.decode_status[disposition.decode_status] += 1
            row.parse_status[disposition.parse_status] += 1
        return [
            {
                "category": row.category,
                "suffix": row.suffix,
                "sources": row.sources,
                "bytes": row.bytes,
                "decode_status": dict(row.decode_status),
                "parse_status": dict(row.parse_status),
            }
            for _, row in sorted(formats.items())
        ]

    def to_dict(self) -> dict[str, object]:
        counts = Counter(row.disposition for row in self.dispositions)
        return {
            "schema": 1,
            "epoch_id": self.epoch_id,
            "input_identity": json.loads(dumps_contract(self.identity)),
            "input_inventory": json.loads(dumps_contract(self.inventory)),
            "coverage": [{**asdict(row), "ratio": row.ratio} for row in self.coverage],
            "coverage_by_format": self._coverage_by_format(),
            "disposition_counts": dict(sorted(counts.items())),
            "dispositions": [asdict(row) for row in self.dispositions],
            "index": self.index.to_dict(),
            "index_projection": "full_private_index"
            if self.raw_root is not None
            else "source_locators",
            "unknown_frontier": [asdict(row) for row in self.frontier],
        }


def _json_details(result: JsonResult) -> dict[str, object]:
    payload = result.document.to_payload() if result.document is not None else None
    return {
        "schema": 1,
        "raw_sha256": result.raw_sha256,
        "raw_size": result.raw_size,
        "decode_status": result.decode_status,
        "parse_status": result.parse_status,
        "had_bom": result.had_bom,
        "root_line": result.root_line,
        "diagnostics": list(result.diagnostics),
        "payload": payload,
        "payload_sha256": hashlib.sha256(payload.encode("ascii")).hexdigest()
        if payload is not None
        else None,
        "node_count": len(result.document.nodes) if result.document is not None else 0,
    }


def structured_json_source(layered: LayeredCatalog, source: str) -> JsonDocument:
    """Load every JSON member by ordinal, verifying derived data against current raw.

    Leaf coordinates remain unknown. A source-level root is indexed in SQLite;
    individual fields are queried through the validated typed document, not SQL.
    """
    if layered.raw_root is None:
        raise ValueError("现场索引只含来源定位，JSON 原文需从已核验安装读取")
    validate_inputs(layered.identity, layered.inventory)
    try:
        ordinal = next(
            i for i, record in enumerate(layered.inventory.records) if record.path == source
        )
    except StopIteration:
        raise KeyError(source) from None
    record, disposition = layered.inventory.records[ordinal], layered.dispositions[ordinal]
    if (
        disposition.category != "structured_configuration"
        or Path(source).suffix.casefold() not in STRUCTURED_JSON_SUFFIXES
        or disposition.path != source
        or disposition.parse_status != "complete"
        or disposition.decode_status != "complete"
    ):
        raise ValueError("source is not a completely parsed structured JSON file")
    with verified_catalog_inputs(layered.identity, layered.inventory, raw_root=layered.raw_root):
        raw = read_source(record, raw_root=layered.raw_root, retain=True)
        if raw is None:
            raise ValueError("JSON raw source is unavailable")
        result = parse_json(raw)
        with layered.index.connect() as connection:
            row = connection.execute("SELECT * FROM sources WHERE path=?", (source,)).fetchone()
            details_row = connection.execute(
                "SELECT details FROM source_details WHERE source=?", (source,)
            ).fetchone()
            roots = connection.execute(
                "SELECT * FROM occurrences WHERE source=?", (source,)
            ).fetchall()
        if row is None or details_row is None:
            raise ValueError("JSON source metadata is missing")
        details = json.loads(details_row[0])
        expected = _json_details(result)
        if (
            type(details) is not dict
            or details_row[0] != _json(details)
            or _json(details.get("inventory")) != _json(asdict(record))
            or _json(details.get("disposition")) != _json(asdict(disposition))
            or _json(details.get("structured_json")) != _json(expected)
            or (row["sha256"], row["size"], row["parse_status"], row["disposition"])
            != (record.sha256, record.size, "complete", disposition.disposition)
            or details.get("version") != layered.identity.version
            or details.get("build_id") != layered.identity.build_id
            or result.document is None
            or len(roots) != 1
        ):
            raise ValueError("JSON derived metadata does not match verified raw source")
        assert result.root_line is not None
        # Compare original SQL fields before adapters can discard shape/type information.
        # The writer emits canonical empty address/path arrays and INTEGER zero for quoted.
        expected_root: dict[str, object] = {
            "id": hashlib.sha256(_json((source, ())).encode()).hexdigest(),
            "source": source,
            "source_sha256": result.raw_sha256,
            "parent_id": None,
            "address": "[]",
            "path": "[]",
            "kind": "json_root",
            "key": None,
            "operator": None,
            "scalar": None,
            "quoted": 0,
            "line": result.root_line,
            "parse_status": "complete",
            "value_kind": "json_document",
            "value_line": result.root_line,
        }
        root = roots[0]
        if set(root.keys()) != set(expected_root) or any(
            type(root[field]) is not type(value) or root[field] != value
            for field, value in expected_root.items()
        ):
            raise ValueError("JSON root occurrence does not match verified source")
        payload = details["structured_json"]["payload"]
        return load_payload(payload)


def base_frontier(
    identity: InputIdentity, dispositions: tuple[FileDisposition, ...]
) -> tuple[UnknownFrontier, ...]:
    result = [
        UnknownFrontier("catalog:consumers", "consumer_denominator_not_audited", ("production",)),
        UnknownFrontier("catalog:load_order", "load_order_not_proven", ("legality", "production")),
        UnknownFrontier("catalog:actors", "dynamic_actor_population_not_observed", ("runtime",)),
    ]
    result.extend(
        UnknownFrontier(
            f"dlc:{dlc.id}", f"dlc_availability_not_proven:{dlc.id}", ("legality", "production")
        )
        for dlc in identity.dlcs
        if any(getattr(dlc, field) != "yes" for field in ("owned", "enabled", "script_available"))
    )
    result.extend(
        UnknownFrontier(
            f"source:{row.path}",
            f"{row.parse_status}:{row.reason}",
            ("semantic", "legality", "production"),
        )
        for row in dispositions
        if row.parse_status not in {"complete", "not_applicable"}
    )
    return tuple(result)


@dataclass(frozen=True, slots=True)
class DependencyAudit:
    occurrences: tuple[Occurrence, ...]
    references: tuple[ResearchReference, ...]
    frontier: tuple[str, ...]


def indexed_parsed_file(connection: sqlite3.Connection, source: str) -> ParsedFile:
    """恢复已记录的单文件 parser 结果，保留原诊断和 token 完整性。"""
    row = connection.execute(
        "SELECT details FROM source_details WHERE source=?", (source,)
    ).fetchone()
    if row is None or "parser" not in (details := json.loads(row[0])):
        raise ValueError(f"来源没有已记录的 PDX parser 结果：{source}")
    metadata = details["parser"]
    metadata["unconsumed_tokens"] = [tuple(item) for item in metadata["unconsumed_tokens"]]
    source_identity = (metadata.pop("raw_sha256"), metadata.pop("raw_size"))
    parsed = ParsedFile(
        path=source,
        root=indexed_tree(connection, source),
        comments=[
            (row[0], row[1])
            for row in connection.execute(
                "SELECT line,scalar FROM occurrences WHERE source=? AND kind='comment' ORDER BY line,json_extract(address,'$[1]')",
                (source,),
            )
        ],
        **metadata,
    )
    disposition = details["disposition"]
    inventory = details["inventory"]
    if parsed.parse_status != disposition["parse_status"] or source_identity != (
        inventory["sha256"],
        inventory["size"],
    ):
        raise ValueError(f"索引 parser 状态/原字节身份不符：{source}")
    return parsed


def indexed_tree(connection: sqlite3.Connection, source: str) -> Block:
    """按需恢复单文件同一 parser 结构；不解析原文、不保存全库 AST。"""
    occurrences = sorted(
        (
            _occurrence(row)
            for row in connection.execute(
                "SELECT * FROM occurrences WHERE source=? AND kind IN ('assignment','block','scalar')",
                (source,),
            )
        ),
        key=lambda row: row.address,
    )
    root = Block(line=1)
    containers: dict[tuple[int, ...], Block] = {(): root}
    for row in occurrences:
        parent = containers.get(row.address[:-1])
        if parent is None:
            raise ValueError("索引结构缺少可恢复父块")
        if row.address[-1] != len(parent.items):
            raise ValueError("索引结构节点序号不连续")
        if row.kind == "assignment" and row.value_kind != "missing" and row.value_line is None:
            raise ValueError("索引赋值缺少独立值行号，必须重建")
        value_line = row.value_line if row.value_line is not None else row.line
        child = Block(line=value_line) if row.value_kind == "block" else None
        if row.kind == "assignment":
            if row.key is None or row.operator is None:
                raise ValueError("索引赋值缺少 key/operator")
            prefix: str | None
            prefix, separator, key = row.key.partition(":")
            if not separator or prefix not in PREFIXES:
                prefix, key = None, row.key
            value = (
                child
                if child is not None
                else Scalar(row.scalar, row.quoted, value_line)
                if row.scalar is not None
                else None
            )
            node: Assignment | Block | Scalar = Assignment(
                key, row.operator, value, prefix, row.line
            )
        elif row.kind == "block":
            if child is None:
                raise ValueError("索引匿名结构缺块")
            node = child
        else:
            if row.scalar is None:
                raise ValueError("索引裸标量缺值")
            node = Scalar(row.scalar, row.quoted, row.line)
        parent.items.append(node)
        if child is not None:
            containers[row.address] = child
    return root


def indexed_lines(
    connection: sqlite3.Connection, source: str, *, documents: bool = False
) -> list[str]:
    """已保留文档行或 parser 注释；不是伪造的完整原文。"""
    kind = "document_line" if documents else "comment"
    rows = connection.execute(
        "SELECT line,scalar FROM occurrences WHERE source=? AND kind=? ORDER BY line,id",
        (source, kind),
    ).fetchall()
    lines = [""] * max((row[0] for row in rows), default=0)
    for line, text in rows:
        lines[line - 1] = text
    return lines


def _audit_dependencies(
    connection: sqlite3.Connection, *, source: str, path: tuple[str, ...], budget: int = 10000
) -> DependencyAudit:
    roots = connection.execute(
        "SELECT * FROM occurrences WHERE source=? AND path=?", (source, _json(path))
    ).fetchall()
    if len(roots) != 1:
        return DependencyAudit(
            (), (), ("missing_parent_definition" if not roots else "ambiguous_parent_definition",)
        )
    symbols: dict[str, list[sqlite3.Row]] = {}
    for definition in connection.execute(
        "SELECT * FROM occurrences WHERE parent_id IS NULL AND kind='assignment' AND key IS NOT NULL"
    ):
        parts = definition["source"].split("/")
        if len(parts) > 3 and parts[1] == "common" and parts[2] in SCRIPT_SYMBOL_CATEGORIES:
            symbols.setdefault(definition["key"], []).append(definition)
    names = set(symbols)
    pending = [roots[0]]
    seen: dict[str, Occurrence] = {}
    references: list[ResearchReference] = []
    frontier: set[str] = set()
    while pending:
        row = pending.pop()
        if row["id"] in seen:
            continue
        if len(seen) >= budget:
            frontier.add("dependency_query_budget_exhausted")
            break
        seen[row["id"]] = _occurrence(row)
        if row["parse_status"] != "complete":
            frontier.add(f"dependency_parse_incomplete:{row['source']}")
        if row["parent_id"] is not None:
            parent = connection.execute(
                "SELECT * FROM occurrences WHERE id=?", (row["parent_id"],)
            ).fetchone()
            if parent is None:
                frontier.add(f"missing_parent_structure:{row['id']}")
            else:
                # 父上下文不可省略；将父作为证据但不把兄弟定义全部拓进消费闭包。
                seen[parent["id"]] = _occurrence(parent)
                ancestor = parent
                while ancestor["parent_id"] is not None:
                    ancestor = connection.execute(
                        "SELECT * FROM occurrences WHERE id=?", (ancestor["parent_id"],)
                    ).fetchone()
                    if ancestor is None:
                        frontier.add("missing_parent_structure")
                        break
                    seen[ancestor["id"]] = _occurrence(ancestor)
        pending.extend(
            connection.execute(
                "SELECT * FROM occurrences WHERE parent_id=? ORDER BY id", (row["id"],)
            )
        )
        typed_calls = []
        if row["kind"] in {"assignment", "scalar"}:
            value = (
                Scalar(row["scalar"], bool(row["quoted"]), row["line"])
                if row["scalar"] is not None
                else None
            )
            item = (
                Assignment(
                    row["key"],
                    row["operator"],
                    Block() if row["value_kind"] == "block" else value,
                    line=row["line"],
                )
                if row["kind"] == "assignment"
                else value
            )
            if item is not None:
                typed_calls = script_symbol_references(item, names, seen[row["id"]].path[:-1])
        for name, _expression, syntax, requested_kind in typed_calls:
            targets = [
                target
                for target in symbols.get(name, ())
                if requested_kind is None
                or SCRIPT_SYMBOL_CATEGORIES[target["source"].split("/")[2]] == requested_kind
            ]
            observational = syntax == "quoted_symbol_observation"
            status = (
                "observational"
                if observational
                else "unresolved"
                if not targets
                else "candidate"
                if len(targets) == 1
                else "ambiguous"
            )
            references.append(
                ResearchReference(
                    row["id"],
                    name,
                    syntax,
                    tuple(target["id"] for target in targets),
                    status,
                    "shared_native_reference_syntax_not_scope_permission",
                )
            )
            if not observational:
                frontier.add(f"{status}_native_symbol:{row['source']}:{name}:{syntax}")
                pending.extend(targets)
        if row["scalar"] is None:
            continue
        value = row["scalar"]
        # 这些是语法字面量；其单位/引擎意义仍需 exact reader 合同。
        if (
            row["quoted"]
            or value in {"yes", "no"}
            or re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value)
        ):
            continue
        variable = value.startswith("@")
        if typed_calls and not variable and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) is None:
            continue
        query = "SELECT * FROM occurrences WHERE key=?"
        args = [value]
        if variable:
            query += " AND source=?"
            args.append(row["source"])
        else:
            query += " AND parent_id IS NULL"
        targets = connection.execute(query + " ORDER BY id", args).fetchall()
        status = "unresolved" if not targets else "candidate" if len(targets) == 1 else "ambiguous"
        references.append(
            ResearchReference(
                row["id"],
                value,
                "variable" if variable else "symbol",
                tuple(target["id"] for target in targets),
                status,
            )
        )
        if variable and len(targets) != 1:
            frontier.add(f"{status}_variable:{row['source']}:{value}")
        elif not variable:
            frontier.add(f"{status}_symbol_semantics:{row['source']}:{value}")
        pending.extend(targets)
    return DependencyAudit(
        tuple(seen[key] for key in sorted(seen)),
        tuple(sorted(references, key=lambda item: item.occurrence_id)),
        tuple(sorted(frontier)),
    )
