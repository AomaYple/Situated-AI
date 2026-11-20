import struct

import pytest

from pdx.binary_headers import BINARY_HEADER_SUFFIXES, HEADER_BYTES, binary_header


def _dds(fourcc: bytes | None = None, *, flags: int = 0x2100F) -> bytearray:
    prefix = bytearray(128)
    struct.pack_into("<4s7I", prefix, 0, b"DDS ", 124, flags, 64, 128, 512, 0, 5)
    struct.pack_into(
        "<II4s5I",
        prefix,
        76,
        32,
        4 if fourcc is not None else 0x41,
        fourcc if fourcc is not None else b"DX10",
        32,
        0x00FF0000,
        0x0000FF00,
        0x000000FF,
        0xFF000000,
    )
    struct.pack_into("<II", prefix, 108, 0x401008, 0xFE00)
    return prefix


def test_dds_reports_declared_pixel_layout_and_probe_range() -> None:
    prefix = _dds()
    prefix.extend(bytes(HEADER_BYTES - len(prefix)))
    header = binary_header(".dds", bytes(prefix))

    assert header["status"] == "observed"
    assert header["scope"] == "header"
    assert header["diagnostics"] == []
    assert header["prefix_bytes"] == HEADER_BYTES
    assert header["required_bytes"] == 128
    assert (header["width"], header["height"], header["depth"], header["mip_count"]) == (
        128,
        64,
        0,
        5,
    )
    assert header["fourcc"] is None
    assert "dxgi_format" not in header
    assert header["header_flags"] == 0x2100F
    assert header["pitch_or_linear_size"] == 512
    assert header["pitch_or_linear_size_kind"] == "pitch"
    assert header["pixel_format_flags"] == 0x41
    assert header["rgb_bit_count"] == 32
    assert header["channel_masks"] == {
        "r": 0x00FF0000,
        "g": 0x0000FF00,
        "b": 0x000000FF,
        "a": 0xFF000000,
    }
    assert (header["caps"], header["caps2"]) == (0x401008, 0xFE00)


@pytest.mark.parametrize(
    ("fourcc", "text", "code"),
    [(b"DXT1", "DXT1", 0x31545844), (b"\x80\0\0\0", None, 0x80)],
)
def test_dds_preserves_fourcc_display_and_records_raw_code(
    fourcc: bytes, text: str | None, code: int
) -> None:
    header = binary_header(".dds", bytes(_dds(fourcc, flags=0x81007)))
    assert header["status"] == "observed"
    assert header["fourcc"] == text
    assert header["fourcc_code"] == code
    assert header["pitch_or_linear_size_kind"] == "linear_size"
    assert "channel_masks" not in header


def test_dds_distinguishes_base_and_dx10_truncation() -> None:
    prefix = bytes(_dds(b"DX10")) + struct.pack("<5I", 98, 3, 4, 12, 2)
    assert len(prefix) == HEADER_BYTES

    for length in (0, 4, 127):
        header = binary_header(".dds", prefix[:length])
        assert header["status"] == "truncated"
        assert header["prefix_bytes"] == length
        assert header["required_bytes"] == 128
        assert header["diagnostics"] == ["dds_header_truncated"]
        assert "width" not in header

    for length in range(128, HEADER_BYTES):
        header = binary_header(".dds", prefix[:length])
        assert header["status"] == "truncated"
        assert header["prefix_bytes"] == length
        assert header["required_bytes"] == HEADER_BYTES
        assert header["diagnostics"] == ["dds_dx10_header_truncated"]
        assert (header["width"], header["fourcc"]) == (128, "DX10")
        assert "dxgi_format" not in header

    header = binary_header(".dds", prefix)
    assert header["status"] == "observed"
    assert header["diagnostics"] == []
    assert header["prefix_bytes"] == header["required_bytes"] == HEADER_BYTES
    assert header["dxgi_format"] == 98
    assert header["resource_dimension"] == 3
    assert header["misc_flag"] == 4
    assert header["array_size"] == 12
    assert header["misc_flags2"] == 2


def test_dds_reports_bad_magic_and_each_invalid_base_field() -> None:
    prefix = _dds()
    header = binary_header(".dds", b"BAD " + bytes(prefix[4:]))
    assert header["status"] == "signature_mismatch"
    assert header["diagnostics"] == ["dds_signature_mismatch"]
    assert "width" not in header

    for offset in (4, 12, 76):
        struct.pack_into("<I", prefix, offset, 0)
    header = binary_header(".dds", bytes(prefix))
    assert header["status"] == "invalid_header"
    assert header["diagnostics"] == [
        "dds_header_size_invalid",
        "dds_pixel_format_size_invalid",
        "dds_dimensions_zero",
    ]
    assert "width" not in header


@pytest.mark.parametrize("suffix", [".mesh", ".anim"])
def test_pdx_signature_reports_its_exact_extent(suffix: str) -> None:
    signature = b"@@b@!\x08pdxasset"
    for prefix, status, diagnostics in (
        (signature + b"opaque", "observed", []),
        (signature[:-1], "truncated", ["pdx_asset_signature_truncated"]),
        (bytes(len(signature)), "signature_mismatch", ["pdx_asset_signature_mismatch"]),
    ):
        assert binary_header(suffix, prefix) == {
            "format": "pdx_asset",
            "status": status,
            "scope": "signature",
            "prefix_bytes": len(prefix),
            "required_bytes": len(signature),
            "diagnostics": diagnostics,
        }

    assert ".mb" not in BINARY_HEADER_SUFFIXES
