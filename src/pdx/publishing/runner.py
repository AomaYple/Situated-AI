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
# Exact 3.4.0 member digests. Evidence in 发布载荷来源校验设计.md.
_RETAINED_VANILLA_PAYLOADS = {
    "64435666ed847f0308d791a9fae211263fa341a0f681e9ced383a007cf6ebcf3": "common/ai_strategies/00_default_strategy.txt",
    "2e9d694393bd63f5ecc0ac42a87b378bdee40b859463ed847a3f29fc05239590": "common/ai_strategies/01_admin_strategies.txt",
    "4c23250b1722d2f6f68dd69d66dabcf239314094791ce08632a4e08284fa69f7": "common/ai_strategies/02_subject_diplomatic_strategies.txt",
    "4b58c6d4318ee8b14b925e07049b9d5ead7cbec45206ea297a36aaa868df93fb": "common/buildings/01_industry.txt",
    "f312edab2d5948d81fb2aab052a0eaea20b08c1567a5584284404d0ee5a855fc": "common/buildings/02_agro.txt",
    "616a9df53f0894147c11218de4e4a0fbecb3179f90768fffd284f32ce7be1964": "common/buildings/03_mines.txt",
    "d439b6c2a433be303a1e9aacfbbca45da47bbc782fa7ca201c6a4986988aa19d": "common/buildings/04_plantations.txt",
    "c69d3d653c97b1f6da9618759f2fa78f13fd8cd7f59c6f225a2656a3971eefea": "common/buildings/06_urban_center.txt",
    "1e37b8ab000055f2081ac3f5c649c55f325cd018e96e2ea4708d8c86f52959aa": "common/buildings/07_government.txt",
    "6bc90d1d000a4ba4a67823647b486f3164c51cb3ed1612fe60db566beb5eafd3": "common/buildings/09_misc_resource.txt",
    "8efd970f69d7179b71aafcf6c25ec9d6aaa84d911158feebedf58ba215b45171": "common/buildings/11_private_infrastructure.txt",
    "161e71ce8e7e97cbdcd0324e811ee108b01a05ff77baa984b7c17aace14bfada": "common/company_types/00_companies_africa.txt",
    "00f50925d1b21e37ad21892b6dea89db6c2f30ef8397d375b88f840c5ef29dc9": "common/company_types/00_companies_americas.txt",
    "51e3bcd5e6008a9783a3a7d25d203a61a683d261e5c600ee1f927ef72291331b": "common/company_types/00_companies_asia.txt",
    "b6fe250a1d07f367dc804ad6aec40283ae54877e256524aafc85c2b2f682f171": "common/company_types/00_companies_austria_hungary.txt",
    "a1ee7f8aa948159750235cbf1c0c0d4d132e98e60ea68e2b0a7138c770a65025": "common/company_types/00_companies_china.txt",
    "faf0db74f133728626b5c081faa2c735e2fc7c53c827d0e436709544f1fb41f4": "common/company_types/00_companies_cots.txt",
    "8ebc0bcc490da9647d8a94896d231d559e5fcf292cd8d6d27db48d2f7096176d": "common/company_types/00_companies_ep2.txt",
    "5f6cd2c1765f2a5566e9d23ebf31bfb82c2fb247906059515e341381497e2ea7": "common/company_types/00_companies_europe.txt",
    "9ab668d8213d2dadc71fffd0e0e6664dc58738e8d35cf6548c58db723bcdaec3": "common/company_types/00_companies_france.txt",
    "a2d550613da0250eed2a0a76096804c1b58cd147c36d2d3b589a731b9dca1215": "common/company_types/00_companies_germany.txt",
    "91f4973b417ad2f06d38c82d9ecd19a6461782a44142211c76682c84d55c0bcc": "common/company_types/00_companies_great_britain.txt",
    "00eb502eeedb5c95055a43568b36803bb4b3d6ceb53278c54a38a6554a69769e": "common/company_types/00_companies_ip2.txt",
    "d7e52cb1ac7ecfca58e2f581ec6c01dfe22c12cc2930f808e3cd1349dfec9f1f": "common/company_types/00_companies_ip3.txt",
    "152e8ac7f37c4234bd7898fcd74c60d58f596e6add5a9ddbdeb36bc475bb5f4f": "common/company_types/00_companies_ip4.txt",
    "a72ef9011c45394eaea8d4b6459d72a6fdaf885d0f3162f2f94d241d9ffc30e6": "common/company_types/00_companies_ip5.txt",
    "d5c8f1ba5d26a6cc4f9597ce8f6e32aab1fae475499608691be09d707ce8a03c": "common/company_types/00_companies_italy.txt",
    "1c307d2a6eff00a3f1cafc118a0088c589f3576b6046aba777cf55869d5ed88d": "common/company_types/00_companies_japan.txt",
    "63511ef33e58b5745807dee3b0fdee4c079024de5c8979d70816555d33356283": "common/company_types/00_companies_mp1.txt",
    "62b1daa2aa6ebb0324c82e0cef5366393059b08674fe120ab9b51c07fb437ea9": "common/company_types/00_companies_russia.txt",
    "5177c92c18cb9bad0f1befe0d7a636d08a5ecad017a27b6e4bcc55ea886ceab8": "common/company_types/00_companies_soi.txt",
    "f61f0712493cc50c591d9131120e8e23be797878adddcd3ff82b7135c3fa19c8": "common/company_types/00_companies_totally_normal.txt",
    "8f26d6209189c3073585969e4a80d49be700c1972f7dbd857480afa6061e6814": "common/company_types/00_companies_usa.txt",
    "d2bdf18f3486a75a72aaab9c583a811f7f82bc8da0042287e3e45420a9869118": "common/company_types/99_basic_companies.txt",
    "69920cf27a4ad4e6f8f84fa00141c4c926b76441a3fcbb7e09ae6c22939d4ace": "common/decrees/00_decree.txt",
    "621aaf26439022469e4f5a9816db2f2ad64e4b139d80b39a628465a61b42a630": "common/diplomatic_actions/00_relations_actions.txt",
    "89ad1187158f257d3d5d3b8eed4293d6493e9b397ad902b22d18bd3ec3c7c614": "common/laws/00_army_model.txt",
    "ca55b3ed67842ee84e699d8aa38fb01f8b77b38d022dc9ffd1cfb508d50f57eb": "common/laws/00_bureaucracy.txt",
    "a0c0973b7d2df718b36f5ff6df8f62244db55f7aeff0f19c4fbd0c98d6c77bf9": "common/laws/00_caste_hegemony.txt",
    "af0abed46fc9fa0e09b0cf8339f81608c10288364f051a3309b2aa551a641ffa": "common/laws/00_church_and_state.txt",
    "d4d704e92849569a9a8c5bc3145f413037e7adaeb876981eab66cb9c389e0eb5": "common/laws/00_citizenship.txt",
    "e44a9b6185eb358588ac248abf69c9f4932a0b42faf34edc0d2e539b5b43453e": "common/laws/00_distribution_of_power.txt",
    "6e3153ccc44fb12a293aaca014c1a72aa170f0fd2030056280dff40648a8b40d": "common/laws/00_governance_principles.txt",
    "357da494791252458276976cc8d240c4efe0f5b80af1d062002202a815e5023b": "common/laws/00_internal_security.txt",
    "29d9e564cd48a0ade92803b203ace174a92e0fd2275cbe9a53445db95ace24b5": "common/laws/00_navy_model.txt",
    "51f7f0df4b2682d3e42aeb7302fbe4996b77d8706e6b0e2f0022c7459ca26beb": "common/laws/01_colonial_affairs.txt",
    "91b14a2c822ba2bb291cedba09049d797ebb1a1ebf96a60b118a6376ac205418": "common/laws/01_economic_system.txt",
    "ca166a7def667015e675b1085771cdf649513b549fb85b75897d427dc38424b7": "common/laws/01_education_system.txt",
    "ee10a3eec09726ed068e87a9501973a2c1661e79bb81f389ce3e8acef009b23b": "common/laws/01_health_system.txt",
    "90d50c257f6484c51da370f45568d52f5cb14e4a3faaeace9972d545f96a018f": "common/laws/01_land_reform.txt",
    "2f816ea57895baef90c53ee3e1764be7da24ebf51e77d85399910ea8f71a15da": "common/laws/01_policing.txt",
    "860be065d57c99c7e30ef00f2ae5cfa391122264bbbdfbf3a6ab49043e5d4000": "common/laws/01_taxation.txt",
    "9902dd5f9c5d4681c69ac791a2c0b7d781007b7854b403b8170915c886bf2bbd": "common/laws/01_trade_policy.txt",
    "8e249d6ce5e003406d20f442f97be37209071191c119c1e2c8e2258e7874445d": "common/laws/02_childrens_rights.txt",
    "99844f99182ccfbeaae8a56c50acc1d0a4cbc31fde185031ff248f29308cc6be": "common/laws/02_free_speech.txt",
    "760fac12719af948d04dd2a51bc02aa743f3304fe2b074cbdc9522a4538c68a8": "common/laws/02_labor_rights.txt",
    "7fffc60be8b8f147e016b83981b302a8acf063a4f0bb210ee7c141822c2a2542": "common/laws/02_labour_associations.txt",
    "c3d480ec0818f02c86c391cf8301868ceb73e460b5305a4905c57c6dc5dfad9d": "common/laws/02_migration.txt",
    "134fdbdacda47bef2f38f1a18447f4df29853527d9a19cf5844d2778b8e2d7e1": "common/laws/02_rights_of_women.txt",
    "41a762f0b5ac29c81d61f08c5b30d84c4a59dc600a8340b507516fe08cb3f365": "common/laws/02_slavery.txt",
    "80c5247da213d0af75f831c8216665a4cf6022fcbf8405f6cb7459d0182b88c1": "common/laws/02_welfare.txt",
    "d2960248bf278dde86a98ed3dd7648c583521b1ac15ce4759c18fb797cb4287e": "common/mobilization_options/00_mobilization_option.txt",
    "cc402a38869610351d1584c797bcee7393e3551eedcda9aafa1998555d5fedb6": "common/ship_modifications/00_ship_modifications.txt",
    "3b569036b159253467cc59aad3e607fa11cdd0cb94e42ea92d27390723805893": "common/ship_modifications/01_utility_modifications.txt",
    "09cb653d4c02cf388a6da2e24908106d4f457b0800d970d3695e538c7b4de9a5": "common/technology/technologies/10_production.txt",
    "a3755220a28853e4c6f58b1b8fdba155f483496aa5f3fa657e977e176e3c7526": "common/technology/technologies/20_military.txt",
    "b17497c524924af874ebb306244d3a90b4cd1ed5b7fce226a9829edc7e83bf6b": "common/technology/technologies/30_society.txt",
    "ec6aab6b2b627297c5e95bcf5081351834b142fb2ffead74f4a914a47bdabd14": "common/treaty_articles/00_alliance.txt",
    "868ea319f4d897cad51f1c7ec041a1df15e94b58b611d8abf7a763189f00d17a": "common/treaty_articles/01_defensive_pact.txt",
    "76f91ccdf3caacab3a0f099375eefe1c0d0db94ba114d50962f9cb32dc855ea1": "common/treaty_articles/02_guarantee_independence.txt",
    "439ac5368733790943aeb5c4ef9ffb221bd4e3bec46b137cb68c96286143c5c7": "common/treaty_articles/07_foreign_investment_rights.txt",
    "22acbc30d6e2929e1e7c4155e29ba17cd1e3fd182a55ea1b94976ca84a475210": "common/treaty_articles/24_transit_rights.txt",
    "98691eff4d5fc52dbbf9b5afcf2aa7b6cfef9225e94ad108869441610c3b9325": "common/treaty_articles/25_trade_privilege.txt",
    "919997b07d68d8d42d23a58fb2178562f81945a4bcd4574921c0e18373da445d": "common/treaty_articles/31_toll_exemption.txt",
    "379908ed998362a730529531994d55fba5415f2b8bc9964094f95e5fa4ca80c5": "common/treaty_articles/32_no_tolls.txt",
    "eb458ff2f798f0291c0b7486943290e982200f761c3b7d1c12c2a99ef99bebfd": "common/treaty_articles/33_strait_access.txt",
    "375cd02d341157dd7ed7a54ac076c0058347b2920a43bec4cc93ced667242e51": "common/treaty_articles/34_no_strait_closure.txt",
}


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
                    if original := _RETAINED_VANILLA_PAYLOADS.get(hashlib.sha256(raw).hexdigest()):
                        raise ValueError(
                            f"公开发布阻塞：{path} 与已证实保留原版字节的 "
                            f"3.4.0 成员 {original} 完全一致"
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
