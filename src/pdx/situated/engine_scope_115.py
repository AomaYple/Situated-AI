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
    "defensive-pact-reader": (
        "research/situated/victoria3-1.15.0-defensive-pact-reader.json",
        "c0dfcd185bd8186faa9d74ea17b86a04e5fafb396f03c1e20564dfcd1f6a816b",
    ),
    "building-default": (
        "research/situated/victoria3-1.15.0-building-default-scope.json",
        "ad217c35af0a2ea1fd601a51fb3fc76c1e3a410e1bb9e01a4bb636a4bbd14a73",
    ),
    "strategy": (
        "research/situated/victoria3-1.15.0-strategy-scope.json",
        "6ef7e8ed915c54fa3bc71443fd637d54e9e5b61e710cfc28b033e27057d1fd50",
    ),
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


EXE_SHA256_1151 = "fb4ec0698afd3d3b1a785926d57bd5d68c95a4afd04b56f6bd45abd7a5672b15"
EXE_BYTES_1151 = 100_221_048
MANIFESTS_1151 = {
    "strategy": (
        "research/situated/1.15.1/engine-strategy.json",
        "a14aa71db94aa6fe526370f6c39c7e7366032ab03ebd48e848c6f57eb8e1c46b",
    ),
    "company": (
        "research/situated/1.15.1/engine-company.json",
        "c8dc4846d92318dddf2398b0b512908b8b69782cf198c49d374a4e7e81bdf82e",
    ),
    "company-default": (
        "research/situated/1.15.1/engine-company-default.json",
        "b05113003de48d057f5c371d563924a414f506f116fbe74c3ad754752faf1593",
    ),
    "country-definition": (
        "research/situated/1.15.1/engine-country-definition.json",
        "7cbf568f2981b7bf2451f621ffe5f58bef919229119c2b7a89ba9bf1b23ef713",
    ),
    "law": (
        "research/situated/1.15.1/engine-law.json",
        "03c8bf8b565d44349ea3dfdc8a8c04bf0d745c4f4fae4b13016cb0f2e4d53cc1",
    ),
    "technology": (
        "research/situated/1.15.1/engine-technology.json",
        "3e439fb4d2e800ae27af325dec620dbe96a309c1c8126afa0a7687019b864922",
    ),
    "building-default": (
        "research/situated/1.15.1/engine-building-default.json",
        "f6f0922c9f0d254d6921ff0fa1f6f24f4e566f1fd9dd340b05dfa2f6ba3c86e2",
    ),
    "defensive-pact-reader": (
        "research/situated/1.15.1/engine-defensive-pact-reader.json",
        "eac4993fad1b0b0bb02acbce3e70117b79de13dc90718fe5ebf677b8e12416c0",
    ),
}


def executable_identity() -> tuple[str, int]:
    """Return the exact selected PE identity; historical declarations stay frozen."""
    from pdx import version_contracts  # noqa: PLC0415

    version = version_contracts.active_version()
    if version == "1.15.1":
        return EXE_SHA256_1151, EXE_BYTES_1151
    if version == "1.15.0":
        return EXE_SHA256, EXE_BYTES
    raise ValueError(f"No 1.15 executable identity for {version}")


def manifest(kind: str) -> tuple[Path, str, str]:
    """Select an independently reviewed exact-version attestation."""
    from pdx import version_contracts  # noqa: PLC0415

    executable_identity()
    version = version_contracts.active_version()
    registry = MANIFESTS_1151 if version == "1.15.1" else MANIFESTS
    try:
        identity, digest = registry[kind]
    except KeyError as exc:
        raise ValueError(f"{version} 尚无独立引擎作用域证据：{kind}") from exc
    return ROOT / identity, identity, digest
