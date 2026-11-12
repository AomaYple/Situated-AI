"""The byte reproduction tool rejects bad PE mapping and executable drift."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def evidence_tool():
    path = Path(__file__).resolve().parents[1] / "tools/ci/engine_evidence.py"
    spec = importlib.util.spec_from_file_location("engine_evidence_under_test", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tiny_pe(tmp_path):
    image = bytearray(0x300)
    image[:2] = b"MZ"
    struct.pack_into("<I", image, 0x3C, 0x80)
    image[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", image, 0x86, 1)
    struct.pack_into("<H", image, 0x94, 0xF0)
    struct.pack_into("<H", image, 0x98, 0x20B)
    struct.pack_into("<Q", image, 0xB0, 0x140000000)
    struct.pack_into("<III", image, 0x194, 0x1000, 0x100, 0x200)
    struct.pack_into("<I", image, 0x1AC, 0x60000020)
    image[0x208:0x20E] = b"\xb8\x05\x00\x00\x00\xc3"
    executable = tmp_path / "image.exe"
    executable.write_bytes(image)
    data = {
        "exe": {"sha256": hashlib.sha256(image).hexdigest(), "bytes": len(image)},
        "observations": [
            {
                "label": "unit fixture scope tag",
                "va": "0x140001008",
                "rva": "0x1008",
                "file_offset": "0x208",
                "bytes": "b805000000c3",
            }
        ],
    }
    manifest = tmp_path / "manifest.json"

    def write():
        manifest.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf8", newline="\n"
        )

    write()
    return executable, manifest, data, write


def test_reproduction_independently_maps_rva_and_preserves_exact_bytes(
    evidence_tool, tiny_pe, tmp_path
):
    executable, manifest, _, _ = tiny_pe
    output = tmp_path / "result"
    receipt = evidence_tool.reproduce(manifest, executable, output)
    assert receipt["points_verified"] == 1
    assert receipt["runtime"] == "unknown"
    assert receipt["disassembly_recorded"] is False
    assert (output / manifest.name).read_bytes() == manifest.read_bytes()


@pytest.mark.parametrize("drift", ["exe", "file_offset", "rva", "bytes", "outside_section"])
def test_bad_identity_or_mapping_never_writes_outputs(evidence_tool, tiny_pe, tmp_path, drift):
    executable, manifest, data, write = tiny_pe
    point = data["observations"][0]
    if drift == "exe":
        executable.write_bytes(executable.read_bytes() + b"drift")
    elif drift == "file_offset":
        point["file_offset"] = "0x209"
    elif drift == "rva":
        point["rva"] = "0x1009"
    elif drift == "bytes":
        point["bytes"] = "b806000000c3"
    else:
        point["rva"] = "0x2000"
        point["va"] = "0x140002000"
    write()
    output = tmp_path / "result"
    with pytest.raises(ValueError):
        evidence_tool.reproduce(manifest, executable, output)
    assert not output.exists()
