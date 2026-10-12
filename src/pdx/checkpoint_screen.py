"""显式检查点原件的有界财政/外交筛选；代理排序不建立引擎资格。"""

from __future__ import annotations

import math
import mmap
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import checkpoint_catalog, decisions
from .deployment_state import digest, plain_path
from .model import Assignment, Block, Scalar
from .parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

BUDGET_LIMIT = 16 * 1024
DIPLOMACY_LIMIT = 256 * 1024
COUNTRY_LIMIT = 1024
NOMINATION_LIMIT = 8
_TOKEN = re.compile(rb'\s+|#[^\r\n]*|"(?:\\.|[^"\\])*"|[{}=]|[^\s{}="#]+')
_STRUCTURE = re.compile(rb'"(?:\\.|[^"\\])*"|#[^\r\n]*|[{}"]')
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_CANONICAL_ID = re.compile(r"0|[1-9][0-9]*")


def _numeric_identity(value: str) -> str:
    """别名仍保留原文；去重按 ASCII 数值身份核对，不能凭前导零换身份。"""
    return str(int(value)) if re.fullmatch(r"[0-9]+", value) else value


@dataclass(frozen=True)
class _Span:
    key: str
    start: int
    end: int
    block: bool


def _token(data: mmap.mmap, at: int, end: int) -> tuple[int, int]:
    while at < end:
        match = _TOKEN.match(data, at, end)
        if match is None:
            raise ValueError(f"structure.invalid_token@{at}")
        stop = match.end()
        if data[at] not in b" \t\r\n\v\f#":
            if data[at] == 34 and data[stop - 1] != 34:
                raise ValueError(f"structure.unclosed_string@{at}")
            return at, stop
        at = stop
    raise ValueError("structure.missing_token")


def _close(data: mmap.mmap, start: int, end: int) -> int:
    depth = 0
    for match in _STRUCTURE.finditer(data, start, end):
        at = match.start()
        char = data[at]
        if char == 123:
            depth += 1
        elif char == 125:
            depth -= 1
            if depth == 0:
                return match.end()
        elif char == 34 and match.end() - at == 1:
            raise ValueError(f"structure.unclosed_string@{at}")
    raise ValueError(f"structure.unclosed_block@{start}")


def _members(data: mmap.mmap, start: int, end: int) -> Iterator[_Span]:
    """只产出直属赋值的字节范围；非目标子块只核括号，不构造 AST。"""
    at = start
    while at < end:
        try:
            key_start, key_end = _token(data, at, end)
        except ValueError as exc:
            if str(exc) == "structure.missing_token":
                return
            raise
        if key_end - key_start > 256:
            raise ValueError("structure.key_too_large")
        key_raw = data[key_start:key_end]
        if key_raw in (b"{", b"}", b"="):
            raise ValueError(f"structure.expected_key@{key_start}")
        key = key_raw.decode("utf-8").strip('"')
        op_start, op_end = _token(data, key_end, end)
        if data[op_start:op_end] != b"=":
            raise ValueError(f"structure.expected_assignment@{op_start}")
        value_start, value_end = _token(data, op_end, end)
        block = data[value_start] == 123
        if block:
            value_end = _close(data, value_start, end)
        elif data[value_start] in b"}=":
            raise ValueError(f"structure.missing_value@{value_start}")
        yield _Span(key, value_start, value_end, block)
        at = value_end


def _one(spans: Sequence[_Span], key: str) -> _Span:
    matches = [span for span in spans if span.key == key]
    if len(matches) != 1:
        raise ValueError(f"field.{key}.{'missing' if not matches else 'duplicate'}")
    return matches[0]


def _database(data: mmap.mmap, spans: Sequence[_Span], name: str) -> _Span:
    container = _one(spans, name)
    if not container.block:
        raise ValueError(f"field.{name}.not_block")
    database = _one(list(_members(data, container.start + 1, container.end - 1)), "database")
    if not database.block:
        raise ValueError(f"field.{name}.database.not_block")
    return database


def _parsed(data: mmap.mmap, span: _Span, limit: int) -> Block:
    if not span.block:
        raise ValueError(f"field.{span.key}.not_block")
    if span.end - span.start > limit:
        raise ValueError(f"field.{span.key}.byte_limit")
    parsed = parse_text("slice=" + data[span.start : span.end].decode("utf-8"))
    if parsed.errors:
        raise ValueError("structure.partial_parse")
    value = parsed.root.items[0]
    if not isinstance(value, Assignment) or not isinstance(value.value, Block):
        raise ValueError("structure.invalid_block")
    return value.value


def _field(block: Block, key: str) -> Block | Scalar:
    matches = block.all(key)
    if len(matches) != 1:
        raise ValueError(f"field.{key}.{'missing' if not matches else 'duplicate'}")
    field = matches[0]
    if field.op != "=" or field.prefix or not isinstance(field.value, (Scalar, Block)):
        raise ValueError(f"field.{key}.invalid")
    return field.value


def _scalar(block: Block, key: str) -> str:
    value = _field(block, key)
    if not isinstance(value, Scalar):
        raise ValueError(f"field.{key}.not_scalar")
    return value.unquoted


def _number(block: Block, key: str, *, nonnegative: bool = False) -> float:
    value = _field(block, key)
    if not isinstance(value, Scalar) or value.quoted or not _NUMBER.fullmatch(value.text):
        raise ValueError(f"field.{key}.invalid_number")
    number = float(value.text)
    if not math.isfinite(number) or (nonnegative and number < 0):
        raise ValueError(f"field.{key}.invalid_number")
    return number


def _country(data: mmap.mmap, span: _Span, exit_weeks: int) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": span.key,
        "tag": None,
        "span": [span.start, span.end],
        "budget_span": None,
        "values": {},
        "screen_remaining_credit_weeks": None,
        "fiscal_state": "unknown",
        "nominated": False,
        "risk_nominated": False,
        "reasons": [],
    }
    try:
        if not _CANONICAL_ID.fullmatch(span.key):
            raise ValueError("country.invalid_id")
        if not span.block:
            if data[span.start : span.end] == b"none":
                row["fiscal_state"] = "tombstone"
                row["reasons"] = ["country.tombstone"]
                return row
            raise ValueError("country.not_block")
        fields = list(_members(data, span.start + 1, span.end - 1))
        definition = _one(fields, "definition")
        if definition.block or definition.end - definition.start > 256:
            raise ValueError("country.invalid_definition")
        tag = data[definition.start : definition.end].decode("utf-8").strip('"')
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,31}", tag):
            raise ValueError("country.invalid_tag")
        row["tag"] = tag
        budget_span = _one(fields, "budget")
        row["budget_span"] = [budget_span.start, budget_span.end]
        budget = _parsed(data, budget_span, BUDGET_LIMIT)
        values = row["values"]
        for key in ("money", "credit", "principal"):
            try:
                values[key] = _number(budget, key, nonnegative=key != "money")
            except ValueError as exc:
                values[key] = None
                row["reasons"].append(str(exc))
        try:
            trend = _field(budget, "balance_trend")
            if not isinstance(trend, Block):
                raise ValueError("field.balance_trend.not_block")
            values["balance_trend.current"] = _number(trend, "current")
        except ValueError as exc:
            values["balance_trend.current"] = None
            row["reasons"].append(str(exc))
        if row["reasons"]:
            return row
        credit, principal, balance = (
            values[k] for k in ("credit", "principal", "balance_trend.current")
        )
        if credit <= 0 or balance >= 0:
            row["fiscal_state"] = "no-ranking-proxy"
            row["reasons"].append("proxy.requires_positive_credit_negative_balance")
        else:
            proxy = (credit - principal) / -balance
            if not math.isfinite(proxy):
                raise ValueError("proxy.nonfinite")
            row["screen_remaining_credit_weeks"] = proxy
            row["fiscal_state"] = "near-threshold" if proxy < exit_weeks else "outside-threshold"
            if proxy >= exit_weeks:
                row["reasons"].append("proxy.outside_exit_threshold")
    except (ValueError, UnicodeError, RecursionError) as exc:
        row["fiscal_state"] = "unknown"
        row["reasons"].append(str(exc))
    return row


def _play(block: Block, object_id: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": object_id,
        "phase": "unknown",
        "country_records": [],
        "reasons": [],
    }
    for key in ("initiator", "target", "type", "war"):
        try:
            row[key] = _scalar(block, key)
        except ValueError as exc:
            row[key] = None
            row["reasons"].append(str(exc))
    try:
        row["escalation"] = _number(block, "escalation", nonnegative=True)
    except ValueError as exc:
        row["escalation"] = None
        row["reasons"].append(str(exc))
    if not _CANONICAL_ID.fullmatch(object_id):
        row["reasons"].append("diplomacy.invalid_id")
    try:
        records = _field(block, "country_records")
        if not isinstance(records, Block) or not records.items:
            raise ValueError("diplomacy.country_records_missing")
        for item in records.items:
            if not isinstance(item, Block):
                raise ValueError("diplomacy.country_records_shape")
            country, side = _scalar(item, "country"), _scalar(item, "side")
            row["country_records"].append({"country": country, "side": side})
            if not _CANONICAL_ID.fullmatch(country):
                row["reasons"].append("diplomacy.country_record_invalid")
        ids = [_numeric_identity(record["country"]) for record in row["country_records"]]
        if len(ids) != len(set(ids)):
            row["reasons"].append("diplomacy.duplicate_country")
        sides = {record["country"]: record["side"] for record in row["country_records"]}
        if row["reasons"]:
            return row
        if not all(_CANONICAL_ID.fullmatch(row[key]) for key in ("initiator", "target")):
            raise ValueError("diplomacy.invalid_country_id")
        if row["initiator"] == row["target"]:
            raise ValueError("diplomacy.same_sides")
        if sides.get(row["initiator"]) != "initiator" or sides.get(row["target"]) != "target":
            raise ValueError("diplomacy.sides_missing")
        if (
            _CANONICAL_ID.fullmatch(row["war"])
            and int(row["war"]) < 4294967295
            and row["escalation"] == 100
        ):
            row["phase"] = "war"
            row["reasons"].append("diplomacy.war_not_pending")
        else:
            raise ValueError("diplomacy.phase_unverified")
    except (ValueError, RecursionError) as exc:
        row["reasons"].append(str(exc))
    return row


def _country_identity(row: dict[str, Any], key: str) -> str | None:
    value = row[key]
    if not isinstance(value, str):
        return None
    if key == "id":
        return _numeric_identity(value)
    return value


def _read(data: mmap.mmap, exit_weeks: int) -> dict[str, Any]:
    header = re.match(rb"SAV0100[0-9a-f]{16}\n", data)
    if header is None:
        raise ValueError("container.unverified_plain_SAV0100")
    root = list(_members(data, header.end(), len(data)))
    metadata = _parsed(data, _one(root, "meta_data"), 65536)
    structural_header = {key: _scalar(metadata, key) for key in ("version", "game_date")}
    player_db = _database(data, root, "player_manager")
    if list(_members(data, player_db.start + 1, player_db.end - 1)):
        raise ValueError("header.not_observer")
    structural_header["observer"] = "yes"
    country_db = _database(data, root, "country_manager")
    countries: list[dict[str, Any]] = []
    unknown: list[str] = []
    for index, span in enumerate(_members(data, country_db.start + 1, country_db.end - 1)):
        if index >= COUNTRY_LIMIT:
            unknown.append("country.record_limit")
            break
        countries.append(_country(data, span, exit_weeks))
    for key in ("id", "tag"):
        counts = Counter(_country_identity(row, key) for row in countries if row[key] is not None)
        for row in countries:
            if counts[_country_identity(row, key)] > 1:
                row["fiscal_state"] = "unknown"
                row["reasons"].append(f"country.duplicate_{key}")
    plays: list[dict[str, Any]] = []
    diplomacy_span = None
    try:
        diplomacy_db = _database(data, root, "diplomatic_plays")
        diplomacy_span = [diplomacy_db.start, diplomacy_db.end]
        database = _parsed(data, diplomacy_db, DIPLOMACY_LIMIT)
        play_spans = list(_members(data, diplomacy_db.start + 1, diplomacy_db.end - 1))
        ids = Counter(_numeric_identity(item.key) for item in database.assignments())
        for item, span in zip(database.items, play_spans, strict=True):
            if not isinstance(item, Assignment) or item.op != "=" or item.prefix:
                raise ValueError("diplomacy.database_shape")
            if isinstance(item.value, Block):
                plays.append(_play(item.value, item.key))
            elif isinstance(item.value, Scalar) and item.value.text == "none":
                plays.append(
                    {"id": item.key, "phase": "tombstone", "reasons": ["diplomacy.tombstone"]}
                )
            else:
                raise ValueError("diplomacy.record_shape")
            if not _CANONICAL_ID.fullmatch(item.key):
                plays[-1]["phase"] = "unknown"
                if "diplomacy.invalid_id" not in plays[-1]["reasons"]:
                    plays[-1]["reasons"].append("diplomacy.invalid_id")
            if ids[_numeric_identity(item.key)] > 1:
                plays[-1]["phase"] = "unknown"
                plays[-1]["reasons"].append("diplomacy.duplicate_id")
            plays[-1]["span"] = [span.start, span.end]
    except (ValueError, UnicodeError, RecursionError) as exc:
        unknown.append(str(exc))
    if any(row["fiscal_state"] == "unknown" for row in countries):
        unknown.append("country.fields_unknown")
    if any(row["phase"] == "unknown" for row in plays):
        unknown.append("diplomacy.fields_unknown")
    return {
        "countries": countries,
        "diplomatic_plays": plays,
        "diplomacy_span": diplomacy_span,
        "unknown_reasons": unknown,
        "structural_header": structural_header,
        "country_records_read": len(countries),
        "country_database_complete": "country.record_limit" not in unknown,
    }


def _identity(info: os.stat_result) -> list[int]:
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def _screen_one(
    path: Path,
    sha256: str,
    expected_version: str,
    reports: Sequence[dict[str, Any]],
    exit_weeks: int,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "path": str(path.absolute()),
        "expected_sha256": sha256,
        "state": "no-supported-nomination",
        "formal_pair_suitable": False,
        "opportunity_count": None,
        "source_allowed": False,
        "source_status": "unknown",
        "instrument_suitable": False,
        "countries": [],
        "diplomatic_plays": [],
        "nominations": [],
        "risk_nominations": [],
        "risk_screen_state": "no-risk-nomination",
        "unknown_reasons": [],
    }
    try:
        plain_path(path)
        before = _identity(path.stat())
        initial_sha = digest(path)
        row.update(sha256=initial_sha, identity_before=before)
        if initial_sha != sha256:
            raise ValueError("input.sha256_mismatch")
        qualification = checkpoint_catalog.inspect(
            path, expected_version=expected_version, origin_reports=reports
        )
        row["inspection"] = qualification
        row["instrument_suitable"] = qualification["instrument_suitable"]
        origins = qualification["origin_reports"]
        row["origin_reports"] = origins
        row["header"] = qualification["header"]
        source_allowed = bool(origins) and all(
            origin.get("clean") is True
            and origin.get("kind") == "vanilla_checkpoint_preparation"
            and initial_sha in origin.get("output_sha256", ())
            for origin in origins
        )
        row["source_allowed"] = source_allowed and qualification["instrument_suitable"] is True
        row["source_status"] = (
            "audited-vanilla-preparation" if row["source_allowed"] else "unknown-or-rejected"
        )
        if not row["source_allowed"]:
            row["unknown_reasons"].append("source.audited_vanilla_preparation_required")
        with path.open("rb") as stream:
            # Windows 的路径 stat.ctime 为创建时间，fstat.ctime 可为修改时间。
            # 描述符核对 dev/ino/size/mtime；完整路径 identity 仍在前后双检。
            if _identity(os.fstat(stream.fileno()))[:4] != before[:4]:
                raise ValueError("input.identity_changed")
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                try:
                    extracted = _read(data, exit_weeks)
                    row["unknown_reasons"].extend(extracted.pop("unknown_reasons"))
                    row.update(extracted)
                    if any(
                        qualification["header"].get(key) != value
                        for key, value in row["structural_header"].items()
                    ):
                        raise ValueError("header.structural_binding_mismatch")
                except (ValueError, UnicodeError, RecursionError) as exc:
                    row["unknown_reasons"].append(str(exc))
                    row["source_allowed"] = False
        plain_path(path)
        row["sha256_after"] = digest(path)
        row["identity_after"] = _identity(path.stat())
        if (
            row["identity_after"] != before
            or row["sha256_after"] != initial_sha
            or qualification["sha256"] != initial_sha
        ):
            raise ValueError("input.changed_during_read")
        candidates = sorted(
            (
                country
                for country in row["countries"]
                if country["fiscal_state"] == "near-threshold"
            ),
            key=lambda country: (country["screen_remaining_credit_weeks"], country["id"]),
        )
        if row["source_allowed"] and "country.record_limit" not in row["unknown_reasons"]:
            for country in candidates[:NOMINATION_LIMIT]:
                country["risk_nominated"] = True
                row["risk_nominations"].append(country["id"])
            if row["risk_nominations"]:
                row["risk_screen_state"] = "risk-screen-only"
        for country in row["countries"]:
            country["reasons"].append("nomination.pending_object_contract_unverified")
            if not row["source_allowed"]:
                country["reasons"].append("risk_nomination.source_not_allowed")
            elif "country.record_limit" in row["unknown_reasons"]:
                country["reasons"].append("risk_nomination.record_limit")
            elif country["fiscal_state"] == "near-threshold" and not country["risk_nominated"]:
                country["reasons"].append("risk_nomination.limit")
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        row["unknown_reasons"].append(str(exc))
        row["source_allowed"] = False
        row["source_status"] = "input-unverified"
        for country in row["countries"]:
            country["nominated"] = False
            country["risk_nominated"] = False
            country["reasons"].append("nomination.input_unverified")
        row["nominations"] = []
        row["risk_nominations"] = []
        row["risk_screen_state"] = "no-risk-nomination"
        row["state"] = "no-supported-nomination"
    return row


def screen(
    inputs: Sequence[tuple[Path, str]],
    *,
    expected_version: str,
    origin_report_paths: Sequence[Path] = (),
) -> dict[str, Any]:
    """筛选仅供人工提名；完整散列和已复核来源缺一不可，不自动开局。"""
    if not 1 <= len(inputs) <= 2:
        raise ValueError("筛选必须显式提供一至两份原件")
    if any(not re.fullmatch(r"[0-9a-f]{64}", sha) for _, sha in inputs):
        raise ValueError("每份原件必须提供完整小写 SHA256")
    reports = [checkpoint_catalog._review_report(path) for path in origin_report_paths]
    policy = decisions.load()
    entries = [
        _screen_one(path, sha, expected_version, reports, policy.exit_weeks) for path, sha in inputs
    ]
    ranked = sorted(
        (country["screen_remaining_credit_weeks"], index, country["id"])
        for index, entry in enumerate(entries)
        for country in entry["countries"]
        if country["risk_nominated"]
    )
    selected = {(index, country_id) for _, index, country_id in ranked[:NOMINATION_LIMIT]}
    for index, entry in enumerate(entries):
        retained = [
            country_id
            for country_id in entry["risk_nominations"]
            if (index, country_id) in selected
        ]
        for country in entry["countries"]:
            if country["risk_nominated"] and country["id"] not in retained:
                country["risk_nominated"] = False
                country["reasons"].append("risk_nomination.global_limit")
        entry["risk_nominations"] = retained
        if not retained:
            entry["risk_screen_state"] = "no-risk-nomination"
    return {
        "schema": 1,
        "mode": "bounded-checkpoint-screen",
        "expected_version": expected_version,
        "thresholds": {"entry_weeks": policy.entry_weeks, "exit_weeks": policy.exit_weeks},
        "state_counts": dict(Counter(row["state"] for row in entries)),
        "entries": entries,
        "reports": reports,
        "formal_pair_suitable": False,
        "opportunity_count": None,
        "parser_sha256": {
            path.name: digest(path)
            for path in (
                Path(__file__),
                Path(checkpoint_catalog.__file__),
                Path(__file__).with_name("parser.py"),
            )
        },
        "limits": [
            "财政代理仅排序，不能替代引擎 weeks/default/loans 或共同 ACTIVE",
            "外交静态线索不能证明 can_support/undecided 或完整机会分母",
            "nomination-only 仍需实机资格；formal=false，不启动游戏",
        ],
    }
