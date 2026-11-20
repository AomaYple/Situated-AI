"""提取 shader 声明、包含路径和阶段引用的静态位置。"""

from __future__ import annotations

import re
from bisect import bisect_left
from dataclasses import dataclass
from ntpath import isreserved
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from .input_contracts import is_contract_path

if TYPE_CHECKING:
    from .input_contracts import ParseStatus

_STAGES = frozenset(
    {"VertexShader", "PixelShader", "GeometryShader", "ComputeShader", "HullShader", "DomainShader"}
)
_NAMED_BLOCKS = frozenset({"Effect", "MainCode"})
_SUFFIXES = frozenset({".shader", ".fxh"})
_IDENTIFIER = r"[A-Za-z_][A-Za-z_0-9]*"
_TOKEN = re.compile(
    r"(?P<directive>\#[\t ]*include\b[^\n]*)|(?P<line_comment>\#[^\n]*|//[^\n]*)"
    r"|(?P<block_comment>/\*[\s\S]*?(?:\*/|\Z))"
    r"|(?P<code>\[\[)|(?P<code_close>\]\])"
    r'|(?P<string>"(?:\\[^\n]|[^"\\\n])*")|(?P<quote>")'
    rf"|(?P<name>{_IDENTIFIER})|(?P<punctuation>[={{}}])|(?P<other>[^\s])"
)
_CODE_TOKEN = re.compile(r'//[^\n]*|/\*[\s\S]*?(?:\*/|\Z)|"(?:\\.|[^"\\\n])*"|[\[\]]')
_INCLUDE_DIRECTIVE = re.compile(
    r'\#[\t ]*include[\t ]*(?:"([^"\r\n]*)"|<([^>\r\n]*)>)[\t ]*(?://[^\n]*)?[\t \r]*'
)
_UNSAFE_PATH = re.compile(r'[\x00-\x1f\x7f<>"|?*]')
Diagnostic = dict[str, str | int]


@dataclass(frozen=True, slots=True)
class ShaderStructure:
    format: str
    scope: str
    status: ParseStatus
    diagnostics: tuple[Diagnostic, ...]
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class _Token:
    kind: str
    text: str
    line: int
    column: int

    def location(self) -> dict[str, int]:
        return {"line": self.line, "column": self.column}


def _code_end(text: str, start: int) -> int | None:
    bracket_depth = 0
    for match in _CODE_TOKEN.finditer(text, start):
        symbol = match[0]
        if symbol == "[":
            bracket_depth += 1
        elif symbol == "]":
            if bracket_depth:
                bracket_depth -= 1
            elif text[match.end() : match.end() + 1] == "]":
                return match.end() + 1
    return None


def _tokens(text: str, diagnostics: list[Diagnostic]) -> list[_Token]:
    ends = [match.start() for match in re.finditer("\n", text)]
    tokens: list[_Token] = []
    cursor = 0
    while (match := _TOKEN.search(text, cursor)) is not None:
        start = match.start()
        cursor = match.end()
        kind = match.lastgroup or "other"
        if kind == "line_comment":
            continue
        line_index = bisect_left(ends, start)
        line_start = ends[line_index - 1] + 1 if line_index else 0
        token = _Token(kind, match[0], line_index + 1, start - line_start + 1)
        if kind == "block_comment":
            if not token.text.endswith("*/"):
                diagnostics.append({"code": "shader_unclosed_comment", **token.location()})
            continue
        if kind == "code":
            finish = _code_end(text, cursor)
            if finish is None:
                diagnostics.append({"code": "shader_unclosed_code", **token.location()})
                break
            cursor = finish
        elif kind in {"quote", "code_close"}:
            diagnostics.append({"code": f"shader_unmatched_{kind}", **token.location()})
        tokens.append(token)
    return tokens


def _include(
    path: str, token: _Token, form: str, diagnostics: list[Diagnostic]
) -> dict[str, object] | None:
    target = path.replace("\\", "/")
    if (
        not is_contract_path(target)
        or _UNSAFE_PATH.search(target)
        or isreserved(target)
        or any(part != part.strip() for part in target.split("/"))
    ):
        diagnostics.append({"code": "shader_unsafe_include_path", **token.location()})
        return None
    return {"target": target, "form": form, **token.location()}


def _collect(tokens: list[_Token], diagnostics: list[Diagnostic]) -> dict[str, object]:
    includes: list[dict[str, object]] = []
    entry_points: list[dict[str, object]] = []
    effects: list[dict[str, object]] = []
    references: list[dict[str, object]] = []
    blocks: list[tuple[_Token, str, str]] = []
    code_blocks = 0
    include_blocks = 0

    for index, token in enumerate(tokens):
        following = tokens[index + 1 : index + 4]
        preceding = tokens[max(0, index - 2) : index]
        if token.kind == "code":
            code_blocks += 1
        elif token.kind == "directive":
            directive = _INCLUDE_DIRECTIVE.fullmatch(token.text)
            if directive is None:
                diagnostics.append(
                    {"code": "shader_unparsed_include_directive", **token.location()}
                )
            else:
                quoted, angled = directive.groups()
                row = _include(
                    quoted if quoted is not None else angled,
                    token,
                    "preprocessor_quoted" if quoted is not None else "preprocessor_angle",
                    diagnostics,
                )
                if row is not None:
                    includes.append(row)
        elif token.text == "{":
            owner, name = _block_owner(preceding)
            if blocks and blocks[-1][1] == "Includes":
                diagnostics.append({"code": "shader_invalid_include_entry", **token.location()})
            blocks.append((token, owner, name))
            if owner == "Includes":
                include_blocks += 1
            elif owner == "Effect":
                effects.append({"name": name, **preceding[0].location()})
            elif owner == "MainCode":
                stage = next((label for _, label, _ in reversed(blocks) if label in _STAGES), None)
                entry_points.append({"name": name, "stage": stage, **preceding[0].location()})
        elif token.text == "}":
            if blocks:
                blocks.pop()
            else:
                diagnostics.append({"code": "shader_unmatched_close_brace", **token.location()})
        elif blocks and blocks[-1][1] == "Includes":
            if token.kind == "string":
                row = _include(token.text[1:-1], token, "includes_block", diagnostics)
                if row is not None:
                    includes.append(row)
            else:
                diagnostics.append({"code": "shader_invalid_include_entry", **token.location()})
        elif token.text.casefold() == "includes":
            if [item.text for item in following[:2]] != ["=", "{"]:
                diagnostics.append({"code": "shader_invalid_includes_block", **token.location()})
        elif token.text in _NAMED_BLOCKS and not (preceding and preceding[-1].text == "="):
            if not following or _declaration_name(following[0]) is None:
                diagnostics.append({"code": "shader_missing_declaration_name", **token.location()})
            elif len(following) < 2 or following[1].text != "{":
                diagnostics.append({"code": "shader_missing_declaration_block", **token.location()})
        elif token.text in _STAGES and blocks and blocks[-1][1] == "Effect":
            starts_assignment = bool(following and following[0].text == "=")
            # "=" 左边的阶段名可与右边的不带引号入口名相同。
            if preceding and preceding[-1].text == "=" and not starts_assignment:
                continue
            target = None
            if starts_assignment and len(following) >= 2:
                next_is_assignment = len(following) == 3 and following[2].text == "="
                if not next_is_assignment:
                    target = _declaration_name(following[1])
            if target is None:
                diagnostics.append(
                    {"code": "shader_missing_effect_stage_value", **token.location()}
                )
            else:
                references.append(
                    {
                        "effect": blocks[-1][2],
                        "stage": token.text,
                        "target": target,
                        **token.location(),
                    }
                )

    diagnostics.extend(
        {"code": "shader_unclosed_brace", **opener.location()} for opener, _, _ in blocks
    )
    return {
        "includes": includes,
        "entry_points": entry_points,
        "effects": effects,
        "effect_stage_references": references,
        "opaque_code_block_count": code_blocks,
        "include_block_count": include_blocks,
        "code_payload_status": "unknown",
        "include_resolution_status": "unknown",
    }


def _declaration_name(token: _Token) -> str | None:
    if token.kind == "name":
        return token.text
    if token.kind == "string" and token.text[1:-1].strip():
        return token.text[1:-1]
    return None


def _block_owner(preceding: list[_Token]) -> tuple[str, str]:
    if len(preceding) != 2:
        return "", ""
    first, second = preceding
    if first.text in _NAMED_BLOCKS:
        name = _declaration_name(second)
        return (first.text, name) if name is not None else ("", "")
    if first.kind == "name" and second.text == "=":
        label = "Includes" if first.text.casefold() == "includes" else first.text
        return label, ""
    return "", ""


def read_shader_structure(path: str, raw: bytes) -> ShaderStructure | None:
    """记录声明结构，代码段内容和引擎的 include 搜索规则维持未知。"""
    suffix = PurePosixPath(path).suffix.casefold()
    if suffix not in _SUFFIXES:
        return None
    format_name = "pdx_shader" if suffix == ".shader" else "pdx_shader_include"
    scope = "shader_declarations"
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        offset = error.start + (3 if raw.startswith(b"\xef\xbb\xbf") else 0)
        return ShaderStructure(
            format_name, scope, "failed", ({"code": "shader_decode_failed", "offset": offset},), {}
        )
    if b"\0" in raw:
        return ShaderStructure(
            format_name,
            scope,
            "failed",
            ({"code": "shader_text_contains_nul", "offset": raw.index(b"\0")},),
            {},
        )
    diagnostics: list[Diagnostic] = []
    tokens = _tokens(text, diagnostics)
    metadata = _collect(tokens, diagnostics)
    if not tokens and not diagnostics:
        diagnostics.append({"code": "shader_no_declarations", "line": 1})
    elif (
        not diagnostics
        and metadata["opaque_code_block_count"] == 0
        and metadata["include_block_count"] == 0
        and not any(
            metadata[key]
            for key in ("includes", "entry_points", "effects", "effect_stage_references")
        )
    ):
        diagnostics.append({"code": "shader_no_recognized_structure", "line": 1})
    return ShaderStructure(
        format_name, scope, "partial" if diagnostics else "complete", tuple(diagnostics), metadata
    )
