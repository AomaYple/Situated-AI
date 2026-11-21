"""Exact native identity and evidence locations for the current release."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from .model import Block, Scalar
from .textio import normalized_text

ENVIRONMENT_VARIABLE = "V3_CONTRACT_PROFILE"
CURRENT_VERSION = "1.15.2"
DEFAULT_STRATEGY_SOURCE = "common/ai_strategies/00_default_strategy.txt"
_LAUNCHER_SETTINGS = "launcher/launcher-settings.json"
INSTALLATION_IDENTITY_SHA256 = {
    "binaries/checksum.txt": "2a8c3667c01597df3ec941c9c012f5b9e2f00a776a6fd9729c171d135422d344",
    "caligula_branch.txt": "e8c4023bf4942a7b58dd4fe86fa3ad729f1ca4f0598fbe2cd3ced3ee432c71be",
    "caligula_rev.txt": "86072c7de4cb3d3e2880246fa58c00eb4525d7a2be9dabadd3b1a6ce4028a74b",
    "clausewitz_branch.txt": "7e62118214c7e94936b5264185fd2c75c2e85ce1709cf831b56437f3bd1b6b75",
    "clausewitz_rev.txt": "7b01c7e17e500a28904d6f00d5dcbbcaa6d5b23ac6ae55d8a9f4d176797697fd",
    _LAUNCHER_SETTINGS: "fe17a1b8195f40757beb5cb03125b7a0619ea2b164bc54309075958a72248232",
}


@dataclass(frozen=True, slots=True)
class VersionContract:
    """One explicitly reviewed native identity and its evidence locations."""

    version: str
    docs_subdir: str
    official_manifest_name: str
    snapshot_label: str
    # Original installed bytes (including BOM/newlines), distinct from the normalized baseline.
    default_strategy_sha256: str
    baseline_strategy_sha256: str


CURRENT_CONTRACT = VersionContract(
    CURRENT_VERSION,
    "victoria3-modding-1.15.2",
    "official-docs-1.15.2.manifest.json",
    "release-1.15.2",
    "7fa4e018a796b1f1c04275e7fbc712ac39a4376e86db311f31079b12a8337760",
    "42088c06f326a6fd1f01ed120928c8888d29b776c9bacb9795c63f9c390d7d40",
)
SUPPORTED_VERSIONS = frozenset({CURRENT_VERSION})


def require_current(version: str | None = None) -> str:
    """Require the exact current release, including any external assertion."""
    for candidate in (os.environ.get(ENVIRONMENT_VARIABLE), version):
        if candidate is not None and candidate != CURRENT_VERSION:
            raise ValueError(f"未支持的原版合同版本：{candidate!r}；当前仅维护 {CURRENT_VERSION}")
    return CURRENT_VERSION


def active_version(version: str | None = None) -> str:
    """Resolve the exact current version."""
    return require_current(version)


def contract(version: str | None = None) -> VersionContract:
    """Return the reviewed contract for the current release."""
    require_current(version)
    return CURRENT_CONTRACT


@dataclass(frozen=True, slots=True)
class VerifiedIdentitySource:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class VerifiedInstallation:
    root: Path
    root_identity: tuple[int, int]
    sources: tuple[VerifiedIdentitySource, ...]


def verify_installation_identity(root: Path) -> VerifiedInstallation:
    """Check the current install and return the specific root and source bytes checked."""
    version = require_current()
    try:
        root = root.resolve(strict=True)
        root_identity = root.lstat()
    except OSError as exc:
        raise ValueError(f"缺少或无法读取 {version} 原版安装根：{root}") from exc
    sources = []
    for relative, expected in INSTALLATION_IDENTITY_SHA256.items():
        path = root / relative
        try:
            if path.is_symlink() or path.resolve(strict=True) != path:
                raise ValueError(f"原版身份文件含链接：{relative}")
            raw = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"缺少或无法读取 {version} 原版身份文件：{relative}") from exc
        digest = hashlib.sha256(raw).hexdigest()
        if relative == _LAUNCHER_SETTINGS:
            try:
                launcher = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_fields)
            except (UnicodeError, ValueError) as exc:
                raise ValueError(f"原版安装的启动器身份无效：{relative}") from exc
            matches = (
                isinstance(launcher, dict)
                and launcher.get("gameId") == "victoria3"
                and launcher.get("rawVersion") == version
                and isinstance(display_version := launcher.get("version"), str)
                and display_version.partition(" ")[0] == version
            )
        else:
            matches = digest == expected
        if not matches:
            raise ValueError(f"原版安装与锁定版本 {version} 的构建身份不符：{relative}")
        sources.append(VerifiedIdentitySource(relative, len(raw), digest))
    try:
        current_root = root.lstat()
    except OSError as exc:
        raise ValueError("原版安装根在核对身份期间变更") from exc
    if not os.path.samestat(root_identity, current_root):
        raise ValueError("原版安装根在核对身份期间变更")
    return VerifiedInstallation(root, (root_identity.st_dev, root_identity.st_ino), tuple(sources))


def read_default_strategy(game: Path) -> str:
    """Read the current source in place and validate raw and normalized identities."""
    require_current()
    selected = contract()
    path = game / DEFAULT_STRATEGY_SOURCE
    try:
        if path.is_symlink() or path.resolve(strict=True) != path.absolute():
            raise ValueError(f"原版默认策略路径含链接：{path}")
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"缺少或无法读取锁定原版默认策略：{path}") from exc
    if hashlib.sha256(raw).hexdigest() != selected.default_strategy_sha256:
        raise ValueError(f"当前原版默认策略原始字节漂移：{path}")
    text = normalized_text(raw.decode("utf-8-sig"))
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != selected.baseline_strategy_sha256:
        raise ValueError(f"当前原版默认策略归一化摘要漂移：{path}")
    return text


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"重复的启动器字段：{key}")
        result[key] = value
    return result


def research_path(category: str, filename: str, version: str | None = None) -> Path:
    """Resolve a versioned evidence path, never reuse another release's identity."""
    if category not in {"situated", "vanilla-ai"}:
        raise ValueError(f"不支持的版本证据类别：{category!r}")
    relative = Path(filename)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"版本证据路径越界：{filename!r}")
    from . import config  # noqa: PLC0415 - config imports the version contract.

    return config.RESEARCH / category / active_version(version) / relative


def journal_completion(journal: Block, *, effect: bool = False) -> Block:
    """Locate the exact 1.15 completion outcome, never the first outcome.

    1.15 moved journal completion predicates/effects into repeated outcome
    blocks. Header and effect-header jointly identify the completion role;
    duplicate, conditional and prefixed structures cannot supply evidence.
    """
    matches: list[Block] = []
    for entry in journal.all("outcome"):
        if entry.op != "=" or entry.prefix is not None or not isinstance(entry.value, Block):
            raise ValueError("原版查询证据缺少唯一普通outcome块")
        headers = entry.value.all("header")
        if not headers:
            continue
        if (
            len(headers) != 1
            or headers[0].op != "="
            or headers[0].prefix is not None
            or not isinstance(headers[0].value, Scalar)
        ):
            raise ValueError("原版查询outcome缺少唯一普通header")
        if headers[0].value.unquoted != "je_standard_completion_header":
            continue
        effect_headers = entry.value.all("effect_header")
        if (
            len(effect_headers) != 1
            or effect_headers[0].op != "="
            or effect_headers[0].prefix is not None
            or not isinstance(effect_headers[0].value, Scalar)
            or effect_headers[0].value.unquoted != "je_standard_on_completion_header"
        ):
            raise ValueError("原版查询outcome完成角色不一致")
        matches.append(entry.value)
    if len(matches) != 1:
        raise ValueError("原版查询证据缺少唯一完成outcome块")
    fields = matches[0].all("effect" if effect else "trigger")
    if (
        len(fields) != 1
        or fields[0].op != "="
        or fields[0].prefix is not None
        or not isinstance(fields[0].value, Block)
    ):
        raise ValueError("原版查询outcome缺少唯一普通完成字段")
    return fields[0].value
