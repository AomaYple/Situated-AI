"""Bounded binary identification and DDS header metadata for local research."""

import struct

HEADER_BYTES = 148
BINARY_HEADER_SUFFIXES = frozenset({".dds", ".mesh", ".anim"})
_PDX_ASSET_SIGNATURE = b"@@b@!\x08pdxasset"


def binary_header(suffix: str, prefix: bytes) -> dict[str, object]:
    if suffix in {".mesh", ".anim"}:
        if len(prefix) < len(_PDX_ASSET_SIGNATURE):
            status = "truncated"
        else:
            status = "observed" if prefix.startswith(_PDX_ASSET_SIGNATURE) else "signature_mismatch"
        return {"format": "pdx_asset", "status": status, "scope": "signature"}
    if len(prefix) < 128:
        return {"format": "dds", "status": "truncated"}
    magic, header_size, _, height, width, _, depth, mips = struct.unpack_from("<4s7I", prefix)
    if magic != b"DDS ":
        return {"format": "dds", "status": "signature_mismatch"}
    pixel_header_size, pixel_flags, fourcc = struct.unpack_from("<II4s", prefix, 76)
    if header_size != 124 or pixel_header_size != 32 or not height or not width:
        return {"format": "dds", "status": "invalid_header"}
    result: dict[str, object] = {
        "format": "dds",
        "status": "observed",
        "scope": "header",
        "width": width,
        "height": height,
        "depth": depth,
        "mip_count": mips,
        "fourcc": fourcc.decode("ascii") if pixel_flags & 4 and fourcc.isascii() else None,
    }
    if pixel_flags & 4 and fourcc == b"DX10":
        if len(prefix) < HEADER_BYTES:
            result["status"] = "truncated"
        else:
            result["dxgi_format"] = struct.unpack_from("<I", prefix, 128)[0]
    return result
