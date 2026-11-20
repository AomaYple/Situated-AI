"""Compact fixtures for the current digest-based executable evidence contract."""

from __future__ import annotations

import hashlib
import json

from pdx import version_contracts
from pdx.situated import engine_scope_115


def current_manifest(kind):
    return json.loads(engine_scope_115.manifest(kind)[0].read_bytes())


def repin_manifest(monkeypatch, path, kind, data):
    raw = json.dumps(data, indent=2).encode()
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    manifest = engine_scope_115.manifest
    _, identity, _ = manifest(kind)
    monkeypatch.setattr(
        engine_scope_115,
        "manifest",
        lambda name: (path, identity, digest) if name == kind else manifest(name),
    )
    return digest


def compact_image(tmp_path, *manifests):
    """Replace reviewed ranges with deterministic synthetic bytes for verifier tests."""
    image = bytearray()
    for data in manifests:
        for point in data["observations"]:
            raw = hashlib.shake_256(point["label"].encode()).digest(point["size"])
            point.update(
                file_offset=hex(len(image)),
                sha256=hashlib.sha256(raw).hexdigest(),
            )
            image.extend(raw)
    executable = tmp_path / "binaries/victoria3.exe"
    executable.parent.mkdir(exist_ok=True)
    executable.write_bytes(image)
    digest = hashlib.sha256(image).hexdigest()
    for data in manifests:
        data["exe"] = {**data["exe"], "sha256": digest, "bytes": len(image)}
    return executable


def strategy_image(tmp_path, monkeypatch, script, *, materialize_definitions=False):
    """Keep current strategy permissions while substituting test source and PE digests."""
    from pdx.situated import engine_scope, engine_strategy_1152

    data = json.loads(engine_scope.strategy_snapshot())
    exe = compact_image(tmp_path, data)
    (tmp_path / "caligula_branch.txt").write_text(
        f"release/{version_contracts.CURRENT_VERSION}", encoding="utf-8"
    )
    for name in ("caligula_rev", "clausewitz_branch", "clausewitz_rev"):
        (tmp_path / f"{name}.txt").write_text("fixture", encoding="utf-8")
    game = tmp_path / "game"
    inputs = {}
    for source in data["script_hashes"]:
        path = game / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(script)
        inputs[source] = script
        data["script_hashes"][source] = hashlib.sha256(script).hexdigest()
    if materialize_definitions:
        for family in ("institution", "stance"):
            sources = data[family + "_definition_sources"]
            for source in sources:
                raw = "\n".join(f"{name} = {{}}" for name in data[family + "_definitions"]).encode()
                path = game / source
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                inputs[source] = raw
                sources[source] = hashlib.sha256(raw).hexdigest()
            monkeypatch.setitem(
                engine_strategy_1152.CONTRACTS, family + "_definition_sources", sources.copy()
            )

    def freeze():
        repin_manifest(monkeypatch, tmp_path / "strategy.json", "strategy", data)
        monkeypatch.setattr(
            engine_scope_115,
            "executable_identity",
            lambda: (data["exe"]["sha256"], data["exe"]["bytes"]),
        )

    freeze()
    return game, exe, data, inputs, freeze
