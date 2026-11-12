"""Reproduce reviewed PE observations without executing or modifying the game.

The controlled manifest is the review specification: its exact VA and byte
length select each observation. This tool verifies the original executable
identity, independently maps every RVA to a PE file offset and records optional
dumpbin output. Outputs are local investigation artifacts, not new permissions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import shutil
import struct
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def pe_sections(raw: bytes | mmap.mmap) -> tuple[int, tuple[tuple[int, int, int, int], ...]]:
    """Return image base and (RVA, file offset, raw length, flags) tuples."""
    if raw[:2] != b"MZ":
        raise ValueError("Not a DOS/PE executable")
    pe = struct.unpack_from("<I", raw, 0x3C)[0]
    if raw[pe : pe + 4] != b"PE\0\0":
        raise ValueError("Missing PE signature")
    count = struct.unpack_from("<H", raw, pe + 6)[0]
    optional_size = struct.unpack_from("<H", raw, pe + 20)[0]
    optional = pe + 24
    if struct.unpack_from("<H", raw, optional)[0] != 0x20B:
        raise ValueError("Only PE32+ images are supported")
    base = struct.unpack_from("<Q", raw, optional + 24)[0]
    sections = []
    for index in range(count):
        offset = optional + optional_size + index * 40
        rva, size, start = struct.unpack_from("<III", raw, offset + 12)
        flags = struct.unpack_from("<I", raw, offset + 36)[0]
        if start + size > len(raw):
            raise ValueError("PE section exceeds executable bounds")
        sections.append((rva, start, size, flags))
    return base, tuple(sections)


def file_location(
    rva: int, length: int, sections: tuple[tuple[int, int, int, int], ...]
) -> tuple[int, bool]:
    for start, offset, size, flags in sections:
        if start <= rva and rva + length <= start + size:
            return offset + rva - start, bool(flags & 0x20000000)
    raise ValueError(f"Observation is outside mapped raw PE sections: {rva:#x}")


def reproduce(
    manifest: Path, executable: Path, destination: Path, dumpbin: Path | None = None
) -> dict[str, Any]:
    raw_manifest = manifest.read_bytes()
    data = json.loads(raw_manifest)
    with (
        executable.open("rb") as stream,
        mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as raw,
    ):
        digest = hashlib.sha256(raw).hexdigest()
        if digest != data["exe"]["sha256"] or len(raw) != data["exe"]["bytes"]:
            raise ValueError("Executable identity differs from the reviewed manifest")
        base, sections = pe_sections(raw)
        observations = []
        commands = []
        excerpts = []
        for point in data["observations"]:
            va, rva = int(point["va"], 16), int(point["rva"], 16)
            expected = bytes.fromhex(point["bytes"])
            if not expected or va != base + rva:
                raise ValueError(f"Invalid image-base identity: {point['label']}")
            offset, is_code = file_location(rva, len(expected), sections)
            if offset != int(point["file_offset"], 16):
                raise ValueError(f"File offset differs from PE mapping: {point['label']}")
            actual = bytes(raw[offset : offset + len(expected)])
            if actual != expected:
                raise ValueError(f"Reviewed bytes differ: {point['label']}")
            observations.append({**point, "bytes": actual.hex()})
            if dumpbin is not None and is_code:
                command = [
                    str(dumpbin),
                    "/nologo",
                    "/disasm:bytes",
                    f"/range:{va:#x},{va + len(actual):#x}",
                    str(executable),
                ]
                result = subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf8",
                    errors="replace",
                )
                commands.append({"label": point["label"], "argv": command})
                excerpts.append(f"{point['label']}\n{result.stdout}")
    data["observations"] = observations
    encoded = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf8")
    if encoded != raw_manifest:
        raise ValueError("Manifest format does not reproduce its original UTF-8 bytes")
    receipt = {
        "manifest": str(manifest),
        "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
        "executable_sha256": digest,
        "points_verified": len(observations),
        "evidence_kind": "binary_static",
        "runtime": "unknown",
        "disassembly_recorded": dumpbin is not None,
        "commands": commands,
    }
    destination.mkdir(parents=True, exist_ok=True)
    (destination / manifest.name).write_bytes(encoded)
    (destination / f"{manifest.stem}-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf8", newline="\n"
    )
    if dumpbin is not None:
        (destination / f"{manifest.stem}-dumpbin.txt").write_text(
            "\n".join(excerpts), encoding="utf8", newline="\n"
        )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, nargs="+")
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--dumpbin", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "tools/out/engine-evidence")
    args = parser.parse_args()
    dumpbin = args.dumpbin
    if dumpbin is None and (found := shutil.which("dumpbin")):
        dumpbin = Path(found)
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / "tools/out").resolve()):
        parser.error("Investigation outputs must stay under tools/out")
    try:
        for manifest in args.manifest:
            receipt = reproduce(manifest.resolve(), args.exe.resolve(), output, dumpbin)
            print(
                f"{manifest.name}: {receipt['points_verified']} points, "
                f"sha256={receipt['manifest_sha256']}, "
                f"disassembly={receipt['disassembly_recorded']}"
            )
    except (ValueError, OSError, struct.error, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Evidence reproduction failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
