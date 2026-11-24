"""Verify and drive selected release channels with one frozen package."""

from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import tempfile
import zipfile
from contextlib import nullcontext
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, cast

from pdx import config, distribution
from pdx.publishing import steam
from pdx.publishing.github import GitHubClient
from pdx.publishing.identity import CHANNELS, ReleaseIdentity
from pdx.publishing.ledger import PublicationLedger, atomic_write, open_ledger, publication_lock
from pdx.publishing.local import checked_path, inspect_local, install

if TYPE_CHECKING:
    from collections.abc import Mapping
    from contextlib import AbstractContextManager

    from pdx.publishing.steam import SteamUGCBackend

_OPERATION_ERRORS = (
    ValueError,
    RuntimeError,
    OSError,
    subprocess.SubprocessError,
    zipfile.BadZipFile,
)
# 3.4.0 default strategy member. Evidence in 发布载荷来源校验设计.md.
_RETAINED_VANILLA_PAYLOAD_SHA256 = (
    "64435666ed847f0308d791a9fae211263fa341a0f681e9ced383a007cf6ebcf3"
)


@dataclass(frozen=True)
class FrozenPackage:
    name: str
    archive: bytes
    files: dict[str, bytes]
    sha256: str

    @property
    def assets(self) -> dict[str, bytes]:
        return {
            self.name: self.archive,
            self.name + ".sha256": f"{self.sha256}  {self.name}\n".encode(),
        }

    def receipt(self) -> dict[str, object]:
        return {
            "name": self.name,
            "sha256": self.sha256,
            "size": len(self.archive),
            "manifest_sha256": hashlib.sha256(self.files[distribution.MANIFEST_NAME]).hexdigest(),
        }


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(config.REPO), *args],
        capture_output=True,
        check=False,
        encoding="utf-8",
        timeout=60,
    )
    if result.returncode:
        raise ValueError("Git 源提交无法核对")
    return result.stdout.strip()


def _source_state(identity: ReleaseIdentity) -> dict[str, object]:
    head = _git("rev-parse", "HEAD")
    branch = _git("branch", "--show-current")
    clean = not _git("status", "--porcelain", "--untracked-files=normal")
    blockers = []
    if (identity.commit or head) != head:
        blockers.append("源提交必须等于当前 HEAD")
    if branch != "main" or not clean:
        blockers.append("正式发布要求干净的 main 工作区")
    if identity.version != distribution.RELEASE_VERSION:
        blockers.append(f"当前生产版本为 {distribution.RELEASE_VERSION}")
    return {"head": head, "branch": branch, "clean": clean, "blockers": blockers}


def _read_bundle(raw: bytes, version: str) -> FrozenPackage:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        distribution._validate_paths(names)
        if len(names) != len(set(names)) or distribution.MANIFEST_NAME not in names:
            raise ValueError("冻结 ZIP 含重复路径或缺少分发清单")
        files = {name: archive.read(name) for name in names}
    manifest = json.loads(files[distribution.MANIFEST_NAME])
    if not isinstance(manifest, dict):
        raise ValueError("冻结 ZIP 分发清单必须是对象")
    generation = manifest.get("generation")
    contract = manifest.get("contract")
    if (
        not isinstance(contract, dict)
        or contract.get("product_version") != version
        or not isinstance(generation, dict)
        or generation.get("publication_channel") != "stable"
    ):
        raise ValueError("冻结 ZIP 的版本或 stable 发布合同不符")
    return FrozenPackage(f"situated-ai-{version}.zip", raw, files, hashlib.sha256(raw).hexdigest())


def _build(version: str) -> FrozenPackage:
    with tempfile.TemporaryDirectory(prefix="sitai-package-") as directory:
        archive = Path(directory) / "release.zip"
        distribution.package(archive)
        return _validate_frozen(archive.read_bytes(), version)


def _validate_frozen(raw: bytes, version: str) -> FrozenPackage:
    # Validate a private copy of the same immutable byte snapshot sent to all channels.
    with tempfile.TemporaryDirectory(prefix="sitai-validate-") as directory:
        archive = Path(directory) / "release.zip"
        archive.write_bytes(raw)
        distribution.validate_package(archive)
    return _read_bundle(raw, version)


def _freeze(identity: ReleaseIdentity, ledger: PublicationLedger) -> FrozenPackage:
    expected_name = f"situated-ai-{identity.version}.zip"
    path = checked_path(ledger.root / expected_name)
    checksum = checked_path(ledger.root / f"{expected_name}.sha256")
    previous = ledger.data.get("package")
    if previous is None:
        bundle = _build(identity.version)
        if path.exists() and path.read_bytes() != bundle.archive:
            raise ValueError("现有冻结包与干净源提交重建结果不同")
        ledger.data["package"] = bundle.receipt()
        ledger.write()
    else:
        if not isinstance(previous, dict) or previous.get("name") != expected_name:
            raise ValueError("发布包收据格式不符")
        if path.exists():
            bundle = _validate_frozen(path.read_bytes(), identity.version)
        else:
            bundle = _build(identity.version)
        if bundle.receipt() != previous:
            raise ValueError("冻结发布包的原始字节发生变化")
    for name, raw in bundle.assets.items():
        destination = path if name == expected_name else checksum
        if destination.exists():
            if destination.read_bytes() != raw:
                raise ValueError(f"冻结附件的原始字节发生变化：{name}")
        else:
            atomic_write(destination, raw)
    return bundle


def _plan_package(identity: ReleaseIdentity, ledger: PublicationLedger | None) -> FrozenPackage:
    if ledger is None or ledger.data.get("package") is None:
        return _build(identity.version)
    name = f"situated-ai-{identity.version}.zip"
    path = checked_path(ledger.root / name)
    bundle = (
        _validate_frozen(path.read_bytes(), identity.version)
        if path.exists()
        else _build(identity.version)
    )
    if bundle.receipt() != ledger.data["package"]:
        raise ValueError("冻结发布包的原始字节发生变化")
    checksum = checked_path(ledger.root / f"{name}.sha256")
    if checksum.exists() and checksum.read_bytes() != bundle.assets[checksum.name]:
        raise ValueError("冻结发布包的 SHA-256 附件发生变化")
    return bundle


def _draft_body(identity: ReleaseIdentity, package: FrozenPackage) -> str:
    introduction = (
        f"Situated AI {identity.version} 正式版本。\n\n"
        f"源提交 `{identity.commit}`。Mod ZIP SHA-256 `{package.sha256}`。"
    )
    if identity.github_notes is None:
        return introduction
    return f"{introduction}\n\n{identity.github_notes}"


def _workshop(identity: ReleaseIdentity, backend: SteamUGCBackend | None) -> steam.SteamWorkshop:
    if identity.workshop_item is None or identity.workshop_owner is None:
        raise ValueError("Workshop 需要 --workshop-item 和 --workshop-owner")
    return steam.SteamWorkshop(
        app_id=config.APP_ID,
        item_id=int(identity.workshop_item),
        owner_id=int(identity.workshop_owner),
        backend=backend,
        helper=identity.workshop_helper,
    )


def _preflight(
    identity: ReleaseIdentity,
    source: Mapping[str, object],
    *,
    package: FrozenPackage | None = None,
    ledger: PublicationLedger | None = None,
    steam_backend: SteamUGCBackend | None = None,
    applying: bool = False,
) -> dict[str, object]:
    channel_states = {}
    blockers = list(cast("list[str]", source["blockers"]))
    source_authority: dict[str, object] | None = None
    selected = identity.channels or tuple(sorted(CHANNELS))
    for channel in selected:
        try:
            if channel == "github":
                if not identity.github_repo:
                    raise ValueError("GitHub 需要 --github-repo")
                client = GitHubClient(identity.github_repo)
                remote = client.inspect(
                    identity.tag,
                    identity.commit or str(source["head"]),
                    package.assets if package else None,
                    owned_draft=_draft_body(identity, package) if package else None,
                    previous=ledger.channel(channel) if ledger else None,
                    verify_published_body=package is not None and identity.github_notes is not None,
                )
                state = {"status": "ready", **remote}
                source_authority = {"repository": identity.github_repo, "merged_main": True}
            elif channel == "local":
                if identity.local_root is None:
                    raise ValueError("本地安装需要 --local-root")
                state = inspect_local(
                    identity.local_root,
                    identity.local_previous_sha256,
                    files=package.files if package else None,
                    previous=ledger.channel(channel) if ledger else None,
                    backup_root=ledger.root if ledger else None,
                    operation_id=identity.digest()[:24] if ledger else None,
                )
            else:
                adapter = _workshop(identity, steam_backend)
                state = dict(
                    adapter.preflight(
                        package.files if package else {},
                        package_sha256=package.sha256 if package else "0" * 64,
                        previous=ledger.channel(channel) if ledger else None,
                        refresh_cached_readback=applying,
                    )
                )
        except _OPERATION_ERRORS as error:
            state = {"status": "blocked", "reason": str(error)}
        if state.get("status") != "ready":
            blockers.append(f"{channel}: {state.get('reason', state['status'])}")
        channel_states[channel] = state
    if "github" not in selected and not blockers:
        try:
            commit = identity.commit or str(source["head"])
            repo = identity.github_repo or _origin_repo()
            GitHubClient(repo).check_public_source(commit)
            source_authority = {"repository": repo, "merged_main": True}
        except _OPERATION_ERRORS as error:
            blockers.append(f"GitHub main: {error}")
    return {
        "status": "blocked" if blockers else "ready",
        "blockers": blockers,
        "channels": channel_states,
        "source_authority": source_authority,
    }


def _origin_repo() -> str:
    remote = _git("remote", "get-url", "origin")
    match = re.fullmatch(
        r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+/[^/]+?)(?:\.git)?/?",
        remote,
    )
    if match is None:
        raise ValueError("请使用 --github-repo 明确发布源公共仓库")
    repo = match[1]
    if re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", repo
    ) is None or repo.rsplit("/", 1)[-1] in {".", ".."}:
        raise ValueError("GitHub origin 仓库格式不符")
    return repo


def plan_release(
    identity: ReleaseIdentity, *, steam_backend: SteamUGCBackend | None = None
) -> dict[str, object]:
    identity.validate(applying=False)
    source = _source_state(identity)
    if not identity.commit:
        identity = replace(identity, commit=str(source["head"]))
    package = None
    ledger = None
    # A default plan describes identities without building on an unready checkout.
    if identity.channels and not source["blockers"]:
        try:
            if identity.publication_dir is not None:
                root = checked_path(identity.publication_dir.absolute())
                if checked_path(root / "publication.json").exists():
                    ledger = PublicationLedger(root, identity.digest(), read_only=True)
            package = _plan_package(identity, ledger)
        except _OPERATION_ERRORS as error:
            cast("list[str]", source["blockers"]).append(str(error))
    checks = _preflight(
        identity, source, package=package, ledger=ledger, steam_backend=steam_backend
    )
    return {
        "status": "blocked" if checks["status"] == "blocked" else "planned",
        "identity": identity.receipt(),
        "source": source,
        "package": package.receipt() if package else None,
        "preflight": checks,
        "external_writes": False,
    }


def _apply_channels(
    identity: ReleaseIdentity,
    ledger: PublicationLedger,
    package: FrozenPackage,
    steam_backend: SteamUGCBackend | None,
) -> None:
    # GitHub repository role cannot establish all token and branch-rule permissions.
    # Resolve the selected GitHub write before changing any other destination.
    for channel in (name for name in ("github", "workshop", "local") if name in identity.channels):
        checkpoint = partial(ledger.checkpoint, channel)

        if channel == "github":
            receipt = GitHubClient(identity.github_repo).publish(
                tag=identity.tag,
                commit=identity.commit,
                files=package.assets,
                draft_body=_draft_body(identity, package),
                checkpoint=checkpoint,
                previous=ledger.channel(channel),
                verify_published_body=identity.github_notes is not None,
            )
        elif channel == "local":
            assert identity.local_root is not None
            assert identity.local_previous_sha256 is not None
            receipt = install(
                package.files,
                identity.local_root,
                identity.local_previous_sha256,
                ledger.root,
                identity.digest()[:24],
                ledger.channel(channel),
                checkpoint,
            )
        else:
            receipt = _workshop(identity, steam_backend).publish(
                package.files,
                package_sha256=package.sha256,
                checkpoint=checkpoint,
                previous=ledger.channel(channel),
            )
        checkpoint(receipt)
        if receipt.get("status") != "verified":
            raise ValueError(f"{channel} 未获得独立回读验证")


def run_release(
    identity: ReleaseIdentity, *, steam_backend: SteamUGCBackend | None = None
) -> dict[str, object]:
    identity.validate(applying=True)
    assert identity.publication_dir is not None
    source = _source_state(identity)
    if source["blockers"]:
        raise ValueError("；".join(cast("list[str]", source["blockers"])))
    local_lock: AbstractContextManager[None] = nullcontext()
    if "local" in identity.channels and identity.local_root is not None:
        local = checked_path(identity.local_root)
        root = checked_path(identity.publication_dir.absolute())
        if root.is_relative_to(local) or local.is_relative_to(root):
            raise ValueError("收据与本地安装必须使用各自独立的目录")
        local_lock = publication_lock(local / ".situated-ai-publish.lock")
    with open_ledger(identity.publication_dir, identity.digest()) as ledger, local_lock:
        ledger.data["identity"] = identity.receipt()
        ledger.data["source"] = source
        ledger.data["receipt_path"] = str(ledger.path)
        try:
            package = _freeze(identity, ledger)
            if {"github", "workshop"}.intersection(identity.channels):
                for path, raw in sorted(package.files.items()):
                    if hashlib.sha256(raw).hexdigest() == _RETAINED_VANILLA_PAYLOAD_SHA256:
                        raise ValueError(
                            f"公开发布阻塞：{path} 与已证实保留原版字节的 3.4.0 成员完全一致"
                        )
            checks = _preflight(
                identity,
                _source_state(identity),
                package=package,
                ledger=ledger,
                steam_backend=steam_backend,
                applying=True,
            )
            ledger.data["preflight"] = checks
            if checks["status"] != "ready":
                ledger.data["status"] = "blocked"
                ledger.write()
                return ledger.data
            if "workshop" in identity.channels and not ledger.channel("workshop"):
                channel_states = cast("dict[str, dict[str, object]]", checks["channels"])
                workshop_checkpoint = channel_states["workshop"].get("checkpoint")
                if not isinstance(workshop_checkpoint, dict):
                    raise ValueError("Workshop 预检缺少可持久化的远端基线")
                ledger.checkpoint("workshop", workshop_checkpoint)
            ledger.data["status"] = "in_progress"
            ledger.data.pop("error", None)
            ledger.write()
            _apply_channels(identity, ledger, package, steam_backend)
        except _OPERATION_ERRORS as error:
            ledger.data["status"] = "partial" if ledger.data.get("channels") else "blocked"
            ledger.data["error"] = str(error)
        else:
            ledger.data["status"] = "verified"
        ledger.write()
        return ledger.data
