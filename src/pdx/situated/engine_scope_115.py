"""Independently reviewed 1.15 static binary evidence identities.

These declarations never inherit permissions from an older executable. Raw
observations identify the reviewed binary; runtime behavior remains unknown.
"""

from __future__ import annotations

lazy from pathlib import Path

from pdx import config

ROOT = config.REPO
EXE_SHA256 = "57c4950e9f1046d61729e8faeedbbdbb7aa30ff2a45788217285eb735491ad36"
EXE_BYTES = 100_280_440
MANIFESTS = {
    "defensive-pact-reader": (
        "research/situated/1.15.2/engine-defensive-pact-reader.json",
        "bd5a7c845ae7282499fcbf2a80233690c81e0a9951a97a1054d5e647d2b8e087",
    ),
    "strategy": (
        "research/situated/1.15.2/engine-strategy.json",
        "e69c31f2cd10bcfa36d51c819aa86117bd69f3f4e6a079e29acffe20d3e5d384",
    ),
    "building-default": (
        "research/situated/1.15.2/engine-building-default.json",
        "23250372ee02d3f81212e4b6798c064a33718735eff9d5a5209b1e9c33828765",
    ),
    "company": (
        "research/situated/1.15.2/engine-company.json",
        "823989284f7d5d7de9142bda4689a0136726ae3f7a4e21ccf2316c565e9eb0f6",
    ),
    "company-default": (
        "research/situated/1.15.2/engine-company-default.json",
        "64cbcade0e0b939bc16ded10a6e33f82045a085b59b4dbf9073ef318b7636025",
    ),
    "technology": (
        "research/situated/1.15.2/engine-technology.json",
        "1ef8906bcd28f941e8ebb3b6e00030ed73bb0ffd632be295b0c8e812fff5a6ab",
    ),
    "country-definition": (
        "research/situated/1.15.2/engine-country-definition.json",
        "4d5547de4078b1136e7703fa4d577d0ebcb40cc899bb2ba77b27164a777bd24b",
    ),
    "law": (
        "research/situated/1.15.2/engine-law.json",
        "1e7c0e640d6cde80fcece6951bb26c3ff26b5bbb3eb8daae7c582517e265cec7",
    ),
}


def executable_identity() -> tuple[str, int]:
    """Return the exact selected PE identity; historical declarations stay frozen."""
    from pdx import version_contracts  # noqa: PLC0415

    version_contracts.require_current()
    return EXE_SHA256, EXE_BYTES


def manifest(kind: str) -> tuple[Path, str, str]:
    """Select an independently reviewed exact-version attestation."""
    from pdx import version_contracts  # noqa: PLC0415

    version = version_contracts.require_current()
    try:
        identity, digest = MANIFESTS[kind]
    except KeyError as exc:
        raise ValueError(f"{version} 尚无独立引擎作用域证据：{kind}") from exc
    return ROOT / identity, identity, digest
