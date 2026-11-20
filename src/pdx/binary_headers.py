"""Identify binary assets and extract bounded DDS header evidence for local research."""

import struct

_DDS_HEADER_BYTES = 128
HEADER_BYTES = 148
BINARY_HEADER_SUFFIXES = frozenset({".dds", ".mesh", ".anim"})
_PDX_ASSET_SIGNATURE = b"@@b@!\x08pdxasset"

_DDSD_PITCH = 0x8
_DDSD_LINEARSIZE = 0x80000
_DDPF_FOURCC = 0x4

_PITCH_OR_LINEAR_SIZE_KIND = {_DDSD_PITCH: "pitch", _DDSD_LINEARSIZE: "linear_size"}


def binary_header(suffix: str, prefix: bytes) -> dict[str, object]:
    """Report the available prefix and the byte count required by the selected probe.

    DDS fields are header declarations. A successful observation covers the header or
    signature only. The prefix may also include bytes past that range.
    """
    if suffix in {".mesh", ".anim"}:
        required = len(_PDX_ASSET_SIGNATURE)
        result: dict[str, object] = {
            "format": "pdx_asset",
            "status": "observed",
            "scope": "signature",
            "prefix_bytes": len(prefix),
            "required_bytes": required,
            "diagnostics": [],
        }
        if len(prefix) < required:
            result.update(status="truncated", diagnostics=["pdx_asset_signature_truncated"])
        elif not prefix.startswith(_PDX_ASSET_SIGNATURE):
            result.update(status="signature_mismatch", diagnostics=["pdx_asset_signature_mismatch"])
        return result
    return _dds_header(prefix)


def _dds_header(prefix: bytes) -> dict[str, object]:
    # DDS_HEADER and DDS_PIXELFORMAT follow the four-byte file magic.
    # https://learn.microsoft.com/en-us/windows/win32/direct3ddds/dds-header
    result: dict[str, object] = {
        "format": "dds",
        "status": "observed",
        "scope": "header",
        "prefix_bytes": len(prefix),
        "required_bytes": _DDS_HEADER_BYTES,
        "diagnostics": [],
    }
    if len(prefix) < _DDS_HEADER_BYTES:
        result.update(status="truncated", diagnostics=["dds_header_truncated"])
        return result

    magic, header_size, flags, height, width, pitch_or_size, depth, mips = struct.unpack_from(
        "<4s7I", prefix
    )
    if magic != b"DDS ":
        result.update(status="signature_mismatch", diagnostics=["dds_signature_mismatch"])
        return result

    pixel_size, pixel_flags, fourcc, bits, red, green, blue, alpha = struct.unpack_from(
        "<II4s5I", prefix, 76
    )
    diagnostics: list[str] = []
    if header_size != 124:
        diagnostics.append("dds_header_size_invalid")
    if pixel_size != 32:
        diagnostics.append("dds_pixel_format_size_invalid")
    if not height or not width:
        diagnostics.append("dds_dimensions_zero")
    if diagnostics:
        result.update(status="invalid_header", diagnostics=diagnostics)
        return result

    caps, caps2 = struct.unpack_from("<II", prefix, 108)
    fourcc_present = bool(pixel_flags & _DDPF_FOURCC)
    result.update(
        width=width,
        height=height,
        depth=depth,
        mip_count=mips,
        fourcc=fourcc.decode("ascii") if fourcc_present and fourcc.isascii() else None,
        header_flags=flags,
        pitch_or_linear_size=pitch_or_size,
        pitch_or_linear_size_kind=_PITCH_OR_LINEAR_SIZE_KIND.get(
            flags & (_DDSD_PITCH | _DDSD_LINEARSIZE)
        ),
        caps=caps,
        caps2=caps2,
        pixel_format_flags=pixel_flags,
    )
    if not fourcc_present:
        result.update(
            rgb_bit_count=bits,
            channel_masks={"r": red, "g": green, "b": blue, "a": alpha},
        )
        return result

    # Some writers use numeric D3DFMT/DXGI_FORMAT codes in the FourCC field.
    result["fourcc_code"] = int.from_bytes(fourcc, "little")
    if fourcc == b"DX10":
        _add_dx10_header(result, prefix)
    return result


def _add_dx10_header(result: dict[str, object], prefix: bytes) -> None:
    # https://learn.microsoft.com/en-us/windows/win32/direct3ddds/dds-header-dxt10
    result["required_bytes"] = HEADER_BYTES
    if len(prefix) < HEADER_BYTES:
        result.update(status="truncated", diagnostics=["dds_dx10_header_truncated"])
        return
    dxgi_format, resource_dimension, misc_flag, array_size, misc_flags2 = struct.unpack_from(
        "<5I", prefix, _DDS_HEADER_BYTES
    )
    result.update(
        dxgi_format=dxgi_format,
        resource_dimension=resource_dimension,
        misc_flag=misc_flag,
        array_size=array_size,
        misc_flags2=misc_flags2,
    )
