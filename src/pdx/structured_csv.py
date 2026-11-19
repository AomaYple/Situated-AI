"""Source locations and row syntax for the observed semicolon-delimited map format."""

import csv
from dataclasses import dataclass
from io import StringIO
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .input_contracts import ParseStatus


@dataclass(frozen=True, slots=True)
class CsvRow:
    line: int
    cells: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CsvResult:
    decode_status: Literal["complete", "failed"]
    parse_status: ParseStatus
    rows: tuple[CsvRow, ...]
    diagnostics: tuple[str, ...]


def parse_map_table(raw: bytes) -> CsvResult:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        return CsvResult("failed", "failed", (), (f"csv_decode: {error}",))

    reader = csv.reader(StringIO(text, newline=""), delimiter=";", strict=True)
    rows: list[CsvRow] = []
    diagnostics: list[str] = []
    while True:
        line = reader.line_num + 1
        try:
            cells = tuple(next(reader))
        except StopIteration:
            break
        except csv.Error as error:
            diagnostics.append(f"csv_syntax:{line}: {error}")
            break
        if rows and len(cells) != len(rows[0].cells):
            diagnostics.append(
                f"csv_row_width:{line}: {len(cells)} expected width {len(rows[0].cells)}"
            )
        rows.append(CsvRow(line, cells))
    if not rows or not rows[0].cells:
        diagnostics.append("csv_header_missing")
        return CsvResult("complete", "failed", tuple(rows), tuple(diagnostics))
    return CsvResult(
        "complete", "partial" if diagnostics else "complete", tuple(rows), tuple(diagnostics)
    )
