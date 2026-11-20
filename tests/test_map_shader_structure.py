"""地图与 shader 结构读取的合成见证。"""

from dataclasses import asdict

import pytest

from pdx.map_structure import map_structure_format, read_map_structure
from pdx.parser import parse_bytes
from pdx.shader_structure import read_shader_structure


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("game/map_data/default.map", "map_configuration"),
        ("game/map_data/state_regions/example.txt", "map_geography"),
        ("game/map_data/nodes.dat", "map_nodes"),
        ("game/gfx/map/spline_network/network.splnet", "spline_network"),
        ("game/gfx/map/spline_network/spline_types/example.txt", "spline_configuration"),
        ("game/dlc/pack/gfx/map/spline_network/route_graphics/example.txt", "spline_configuration"),
        ("game/gfx/map/spline_network_other/example.txt", None),
        ("game/gfx/map/nodes.dat", None),
    ],
)
def test_map_format_selection(path: str, expected: str | None) -> None:
    assert map_structure_format(path) == expected


def test_map_metadata_reuses_shared_parser() -> None:
    path = "game/map_data/default.map"
    raw = b'# comment\r\nprovinces = "layers\\regions.png"\r\nsea_starts = { 1 2 3 }\r\n'
    parsed = parse_bytes(raw, path, encoding="utf-8-sig")
    result = read_map_structure(path, raw, parsed=parsed)
    assert result == read_map_structure(path, raw)
    assert result is not None
    assert asdict(result) == {
        "format": "map_configuration",
        "scope": "pdx_map_configuration",
        "status": "complete",
        "diagnostics": (),
        "metadata": {
            "max_depth": 1,
            "assignments": [
                {"key": "provinces", "line": 2, "kind": "scalar"},
                {
                    "key": "sea_starts",
                    "line": 3,
                    "kind": "block",
                    "item_count": 3,
                    "field_names": [],
                },
            ],
            "asset_references": [{"field": "provinces", "line": 2, "target": "layers/regions.png"}],
        },
    }


def test_map_binary_is_observed_without_interpreting_prefix_as_schema() -> None:
    path = "game/gfx/map/spline_network/example.splnet"
    result = read_map_structure(path, b"\x01\x02\x03\x04\x05\x06\x07\x08\xff\x00")
    assert result is not None
    assert result.status == "not_attempted"
    assert result.metadata == {
        "observed_prefix_hex": "0102030405060708",
        "byte_size": 10,
        "payload_status": "unknown",
    }
    assert result.diagnostics == ({"code": "map_binary_schema_unknown"},)
    empty = read_map_structure(path, b"")
    assert empty is not None
    assert empty.diagnostics[-1] == {"code": "map_binary_empty", "offset": 0}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"\xef\xbb\xbfabc\xff", {"code": "map_decode_failed", "offset": 6}),
        (b"a\0b", {"code": "map_text_contains_nul", "offset": 1}),
    ],
)
def test_map_text_reports_original_failure_offset(raw: bytes, expected: dict[str, object]) -> None:
    result = read_map_structure("game/map_data/default.map", raw)
    assert result is not None
    assert result.status == "failed"
    assert result.diagnostics == (expected,)


def test_map_rejects_unsafe_resource_reference_and_keeps_syntax_error() -> None:
    raw = b'provinces = "../foreign.png"\nsea_starts = { a'
    result = read_map_structure("game/map_data/default.map", raw)
    assert result is not None
    assert result.status == "partial"
    assert len(result.diagnostics) == 2
    assert result.diagnostics[-1] == {"code": "map_invalid_asset_path", "line": 1}
    assert result.metadata["asset_references"] == []


def test_shader_declarations_keep_positions_without_code_payload() -> None:
    raw = rb"""
// Includes = { "comment.fxh" }
/* Effect Commented { } */
Includes = { "shared\color.fxh" "common.fxH" }
#include <shared/extra.fxh>
VertexShader = {
    MainCode MakeVertex {
        Code [[ float value = source[rows[2]];
                 // ]] Includes = { "not-an-include.fxh" }
                 ]]
    }
}
Effect TestEffect { VertexShader = "MakeVertex" }
"""
    result = read_shader_structure("game/gfx/FX/test.shader", raw)
    assert result is not None
    assert result.status == "complete"
    assert result.metadata == {
        "includes": [
            {"target": "shared/color.fxh", "form": "includes_block", "line": 4, "column": 14},
            {"target": "common.fxH", "form": "includes_block", "line": 4, "column": 33},
            {
                "target": "shared/extra.fxh",
                "form": "preprocessor_angle",
                "line": 5,
                "column": 1,
            },
        ],
        "entry_points": [{"name": "MakeVertex", "stage": "VertexShader", "line": 7, "column": 5}],
        "effects": [{"name": "TestEffect", "line": 13, "column": 1}],
        "effect_stage_references": [
            {
                "effect": "TestEffect",
                "stage": "VertexShader",
                "target": "MakeVertex",
                "line": 13,
                "column": 21,
            }
        ],
        "opaque_code_block_count": 1,
        "include_block_count": 1,
        "code_payload_status": "unknown",
        "include_resolution_status": "unknown",
    }


@pytest.mark.parametrize(
    "target",
    [
        r"..\outer.fxh",
        r"C:\foreign.fxh",
        r"\\host\share.fxh",
        "decoy/../file.fxh",
        "file.fxh:stream",
        "shared/NUL.fxh",
    ],
)
def test_shader_unsafe_paths_have_locations_without_targets(target: str) -> None:
    escaped = f'Includes = {{ "{target}" }}'
    result = read_shader_structure("test.fxh", escaped.encode())
    assert result is not None
    assert result.status == "partial"
    assert result.metadata["includes"] == []
    assert result.diagnostics[-1] == {"code": "shader_unsafe_include_path", "line": 1, "column": 14}


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b"Code [[ stuff", "shader_unclosed_code"),
        (b"/* stuff", "shader_unclosed_comment"),
        (b'Includes = { "missing_brace.fxh"', "shader_unclosed_brace"),
        (b"#include INPUT_MACRO", "shader_unparsed_include_directive"),
    ],
)
def test_shader_reports_incomplete_or_unsupported_declarations(raw: bytes, code: str) -> None:
    result = read_shader_structure("test.fxh", raw)
    assert result is not None
    assert result.status == "partial"
    assert result.diagnostics[0]["code"] == code


def test_shader_reports_invalid_utf8_byte_offset() -> None:
    result = read_shader_structure("test.shader", b"\xef\xbb\xbf\xe1\xff")
    assert result is not None
    assert result.status == "failed"
    assert result.diagnostics == ({"code": "shader_decode_failed", "offset": 3},)


def test_shader_empty_include_block_and_code_with_index_next_to_close() -> None:
    result = read_shader_structure("test.fxh", b"InClUdEs = {} Code [[ source[2]]]")
    assert result is not None
    assert result.status == "complete"
    assert result.metadata["includes"] == []
    assert result.metadata["include_block_count"] == 1
    assert result.metadata["opaque_code_block_count"] == 1


@pytest.mark.parametrize(
    "raw",
    [
        b"Effect = {}",
        b"Effect {}",
        b'Effect "" {}',
        b'MainCode "  " {}',
        b"MainCode",
    ],
)
def test_shader_named_declarations_require_a_name(raw: bytes) -> None:
    result = read_shader_structure("test.shader", raw)
    assert result is not None
    assert result.status == "partial"
    assert result.diagnostics == (
        {"code": "shader_missing_declaration_name", "line": 1, "column": 1},
    )
    assert result.metadata["effects"] == []
    assert result.metadata["entry_points"] == []


@pytest.mark.parametrize(
    "assignment",
    [b"VertexShader =", b'VertexShader = ""', b"VertexShader", b"VertexShader = 123"],
)
def test_shader_effect_stages_require_a_value(assignment: bytes) -> None:
    raw = b"Effect Example { " + assignment + b'\nPixelShader = "KnownPixel" }'
    result = read_shader_structure("test.shader", raw)
    assert result is not None
    assert result.status == "partial"
    assert result.diagnostics == (
        {"code": "shader_missing_effect_stage_value", "line": 1, "column": 18},
    )
    assert result.metadata["effect_stage_references"] == [
        {
            "effect": "Example",
            "stage": "PixelShader",
            "target": "KnownPixel",
            "line": 2,
            "column": 1,
        }
    ]


def test_shader_named_declaration_requires_a_block() -> None:
    result = read_shader_structure("test.shader", b"Effect Example")
    assert result is not None
    assert result.status == "partial"
    assert result.diagnostics == (
        {"code": "shader_missing_declaration_block", "line": 1, "column": 1},
    )


def test_shader_retains_unquoted_stage_values_that_match_stage_names() -> None:
    raw = b"Effect Example { VertexShader = VertexShader PixelShader = NamedPixel }"
    result = read_shader_structure("test.shader", raw)
    assert result is not None
    assert result.status == "complete"
    assert result.metadata["effect_stage_references"] == [
        {
            "effect": "Example",
            "stage": "VertexShader",
            "target": "VertexShader",
            "line": 1,
            "column": 18,
        },
        {
            "effect": "Example",
            "stage": "PixelShader",
            "target": "NamedPixel",
            "line": 1,
            "column": 46,
        },
    ]
