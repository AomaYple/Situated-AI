"""Independently reviewed 1.15 static binary evidence identities.

These declarations never inherit permissions from an older executable. Raw
observations identify the reviewed binary; runtime behavior remains unknown.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXE_SHA256 = "473186e8d8deba993651e0ae4cf02a003b02f5accb99b096a6a0a8bd9506cbaa"
EXE_BYTES = 99_988_600
MANIFESTS = {
    "country-definition": (
        "research/situated/victoria3-1.15.0-country-definition-scope.json",
        "9986e4f17edf86fa4a529041fd31a9282ec7fc89c084908cc0e774511d82d3fa",
    ),
    "law": (
        "research/situated/victoria3-1.15.0-law-scope.json",
        "5787364832b3a7c0ab9028d2733623ddbe999af0bd6a613eafcd0dea7ed28a7b",
    ),
    "technology": (
        "research/situated/victoria3-1.15.0-technology-scope.json",
        "f4e02dd206ba62815efaa92a18c0fe01af7a8f5500f62bd61edff8371c01b37b",
    ),
    "company": (
        "research/situated/victoria3-1.15.0-company-scope.json",
        "010637d4ad43500679ff81c3ce0f7ec50fbf038398cf39d20863a88c72398aec",
    ),
    "company-default": (
        "research/situated/victoria3-1.15.0-company-default-scope.json",
        "3a56733d3e6f414b2d9fdbe044d8659627613b8f6294b14c3dd5291e0855cff3",
    ),
}


def manifest(kind: str) -> tuple[Path, str, str]:
    """Return only an independently reviewed current-version attestation."""
    try:
        identity, digest = MANIFESTS[kind]
    except KeyError as exc:
        raise ValueError(f"1.15.0 尚无独立引擎作用域证据：{kind}") from exc
    return ROOT / identity, identity, digest
