"""Steam Workshop publishing through an injected Steamworks UGC transport.

The transport owns Steamworks initialization, login, callback dispatch, and the
native SDK binding. This module validates release inputs and coordinates an
idempotent update of an existing Workshop item.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pdx import config, distribution, localization_languages
from pdx.publishing.local import checked_path

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

WORKSHOP_TITLE = "Situated AI"
DESCRIPTION_LIMIT_BYTES = 8000
TITLE_LIMIT_BYTES = 128
_ITEM_SUBSCRIBED = 1
_ITEM_INSTALLED = 4
_PACKAGE_METADATA_SCHEMA = "situated-ai-workshop-v1"
_LANGUAGE_ROWS = (
    ("simp_chinese", "创意工坊描述.md", "schinese"),
    ("english", "创意工坊描述-en.md", "english"),
    ("french", "创意工坊描述-fr.md", "french"),
    ("german", "创意工坊描述-de.md", "german"),
    ("japanese", "创意工坊描述-ja.md", "japanese"),
    ("korean", "创意工坊描述-ko.md", "koreana"),
    ("polish", "创意工坊描述-pl.md", "polish"),
    ("braz_por", "创意工坊描述-pt-BR.md", "brazilian"),
    ("russian", "创意工坊描述-ru.md", "russian"),
    ("spanish", "创意工坊描述-es.md", "spanish"),
    ("turkish", "创意工坊描述-tr.md", "turkish"),
)
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_HELPER_ENV = "V3_STEAM_WORKSHOP_HELPER"
_HELPER_DEFAULT = (
    _REPOSITORY_ROOT / "tools/out/steam-workshop-helper/situated-ai-steam-workshop.exe"
)
_OS_ENV = (
    "SystemRoot",
    "WINDIR",
    "TEMP",
    "TMP",
    "LOCALAPPDATA",
    "APPDATA",
    "USERPROFILE",
    "ProgramFiles",
    "ProgramFiles(x86)",
)
_CDN_HOSTS = {"images.steamusercontent.com", "steamuserimages-a.akamaihd.net"}


@dataclass(frozen=True, slots=True)
class WorkshopItem:
    """Fields needed to verify the target and the selected localized text."""

    published_file_id: int
    creator_app_id: int
    consumer_app_id: int
    owner_id: str
    is_owner: bool
    banned: bool
    title: str
    description: str
    developer_metadata: str
    content_handle: int = 0
    preview_handle: int = 0
    visibility: int = 0
    preview_url: str = ""
    item_state: int = 0


@dataclass(frozen=True, slots=True)
class UpdateResult:
    """Final result after the SDK adapter has pumped callbacks and progress."""

    succeeded: bool
    published_file_id: int
    result_code: int | None = None
    message: str = ""
    needs_legal_agreement: bool = False


class WorkshopNotSubmittedError(RuntimeError):
    """The transport confirmed that an update exited before SubmitItemUpdate."""


# ISteamUGC::SubmitItemUpdateResult_t documents these as request validation,
# license, source file, quota, or lock failures. A matched callback and an
# unchanged remote baseline are both required before attempting the write again.
_SUBMIT_REJECTION_CODES = {
    8: "InvalidParam",
    9: "FileNotFound",
    15: "AccessDenied",
    25: "LimitExceeded",
    33: "LockingFailed",
}


class WorkshopUpdateRejectedError(RuntimeError):
    """Steam matched the callback to the target and explicitly rejected the update."""

    def __init__(self, language: str, code: int) -> None:
        self.code = code
        super().__init__(
            f"Steam 拒绝提交 Workshop 语言 {language}（{_SUBMIT_REJECTION_CODES[code]}，{code}）。"
            "解决 Steam 报告的原因后，用同一发布收据重跑以重新核对远端基线。"
        )


class SteamUGCBackend(Protocol):
    """Narrow synchronous facade over Steamworks ISteamUGC.

    ``submit_item_update`` must wait for the final SubmitItemUpdateResult_t
    callback and monitor GetItemUpdateProgress. Implementations must use
    SetItemUpdateLanguage for each language before setting its
    description. The caller supplies an authenticated SDK session.
    """

    def app_id(self) -> int: ...

    def logged_on(self) -> bool: ...

    def current_user_id(self) -> str: ...

    def query_item(self, published_file_id: int, language: str) -> WorkshopItem | None: ...

    def start_item_update(
        self, app_id: int, published_file_id: int, current: WorkshopItem
    ) -> object: ...

    def set_item_update_language(self, handle: object, language: str) -> bool: ...

    def set_item_description(self, handle: object, description: str) -> bool: ...

    def set_item_content(self, handle: object, content_folder: Path) -> bool: ...

    def set_item_preview(self, handle: object, preview_file: Path) -> bool: ...

    def set_item_metadata(self, handle: object, metadata: str) -> bool: ...

    def submit_item_update(self, handle: object, change_note: str) -> UpdateResult: ...

    def installed_item(self, published_file_id: int) -> Path | None: ...

    def preview_sha256(self, item: WorkshopItem) -> str: ...


@runtime_checkable
class SteamCacheBackend(Protocol):
    @property
    def supports_cache_download(self) -> bool: ...

    def download_cache(self, published_file_id: int) -> tuple[Path, int, int]: ...

    def cached_item(self, published_file_id: int) -> Path | None: ...


def load_descriptions(repository_root: Path = _REPOSITORY_ROOT) -> dict[str, str]:
    """Read the eleven source BBCode descriptions and verify the README map."""
    root = repository_root / "docs" / "publishing"
    readme = (root / "README.md").read_text(encoding="utf-8")
    parsed_rows = re.findall(r"(?m)^\| (\w+) \| \[[^\]]+\]\(([^)]+)\) \| (\w+) \|$", readme)
    if (
        tuple(parsed_rows) != _LANGUAGE_ROWS
        or {row[0] for row in parsed_rows}
        != localization_languages.DEFAULT_LANGUAGE_BY_DIRECTORY.keys()
    ):
        raise ValueError("docs/publishing/README.md 语言映射与 Steam 发布映射不一致")

    descriptions: dict[str, str] = {}
    for _directory, filename, steam_language in _LANGUAGE_ROWS:
        try:
            description = (root / filename).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"无法读取 Steam 描述 {filename}: {exc}") from exc
        description = description.rstrip("\n")
        if not description.strip() or "\x00" in description or description.startswith("\ufeff"):
            raise ValueError(f"Steam 描述为空或包含 NUL: {filename}")
        if len(description.encode("utf-8")) >= DESCRIPTION_LIMIT_BYTES:
            raise ValueError(f"Steam 描述超过 {DESCRIPTION_LIMIT_BYTES} UTF-8 字节: {filename}")
        descriptions[steam_language] = description
    if len(descriptions) != len(_LANGUAGE_ROWS) or len(set(descriptions.values())) != len(
        descriptions
    ):
        raise ValueError("Steam 描述语言代码或本地化正文重复")
    if len(WORKSHOP_TITLE.encode("utf-8")) > TITLE_LIMIT_BYTES:
        raise ValueError("Steam Workshop 标题超过官方字节限制")
    return descriptions


def _validate_package_files(
    package_files: Mapping[str, bytes],
) -> tuple[dict[str, bytes], dict[str, object]]:
    if not package_files:
        raise ValueError("Steam 发布包不能为空")
    if any(
        not isinstance(name, str) or not isinstance(raw, bytes)
        for name, raw in package_files.items()
    ):
        raise ValueError("Steam 发布包必须是相对路径到 bytes 的映射")
    names = list(package_files)
    distribution._validate_paths(names)
    if distribution.MANIFEST_NAME not in package_files:
        raise ValueError(f"Steam 发布包缺少 {distribution.MANIFEST_NAME}")
    try:
        manifest = json.loads(package_files[distribution.MANIFEST_NAME].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Steam 发布包清单不是有效 UTF-8 JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("Steam 发布包清单必须是 JSON 对象")
    generation = manifest.get("generation")
    if generation is not None and not isinstance(generation, dict):
        raise ValueError("Steam 发布包生成契约无效")
    data = {name: raw for name, raw in package_files.items() if name != distribution.MANIFEST_NAME}
    regenerated = distribution._manifest_for_payloads(data, generation=generation)
    if manifest != regenerated:
        raise ValueError("Steam 发布包清单与文件摘要不一致")
    contract = manifest.get("contract")
    if not isinstance(contract, dict):
        raise ValueError("Steam 发布包缺少正式发布契约")
    for name, raw in data.items():
        if name == distribution.THUMBNAIL_NAME:
            continue
        game_text = PurePosixPath(name).suffix.lower() in distribution.GAME_SUFFIXES
        try:
            decoded = raw.decode("utf-8-sig" if game_text else "utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"Steam 发布文件不是 UTF-8: {name}") from exc
        if raw.startswith(b"\xef\xbb\xbf") != game_text or "\ufeff" in decoded or "\r" in decoded:
            raise ValueError(f"Steam 发布文件 BOM/LF 不符: {name}")
    distribution._validate_release(data, contract)
    return dict(package_files), contract


def _target_id(value: int, kind: str) -> int:
    if type(value) is not int or not 0 < value < 2**64:
        raise ValueError(f"Steam Workshop {kind} must be a positive 64-bit ID")
    return value


def _package_marker(package_sha256: str, manifest_sha256: str) -> str:
    return json.dumps(
        {
            "schema": _PACKAGE_METADATA_SCHEMA,
            "mod_id": config.MOD_ID,
            "package_sha256": package_sha256,
            "manifest_sha256": manifest_sha256,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _verify_item(
    item: WorkshopItem | None, item_id: int, user_id: str, language: str
) -> WorkshopItem:
    if item is None:
        raise RuntimeError(f"Steam Workshop item {item_id} 未能以 {language} 查询")
    if item.published_file_id != item_id:
        raise RuntimeError("Steam 查询返回了不同的 Workshop item ID")
    if item.creator_app_id != config.APP_ID or item.consumer_app_id != config.APP_ID:
        raise RuntimeError("Workshop item 的创建或消费 App ID 不符")
    if not item.is_owner or item.owner_id != user_id:
        raise RuntimeError("当前 Steam 用户不是目标 Workshop item 的所有者")
    if item.banned:
        raise RuntimeError("目标 Workshop item 已被封禁")
    if item.visibility != 0:
        raise RuntimeError("目标 Workshop item 的可见性必须为公开")
    return item


def _require_setter(accepted: bool, field: str) -> None:
    if not accepted:
        raise WorkshopNotSubmittedError(f"Steam 拒绝设置 Workshop 字段 {field}，更新尚未提交")


def _write_content_tree(data: Mapping[str, bytes], content_root: Path) -> None:
    for name, raw in data.items():
        target = content_root.joinpath(*PurePosixPath(name).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)


def _description_matches(item: WorkshopItem, text: str) -> bool:
    return _normalize_description(item.description) == text


def _normalize_description(text: str) -> str:
    return text.replace("\r\n", "\n").rstrip("\n")


def _description_sha256(text: str) -> str:
    return hashlib.sha256(_normalize_description(text).encode("utf-8")).hexdigest()


def _assets_match(item: WorkshopItem, marker: str) -> bool:
    return item.developer_metadata == marker and 0 < item.preview_handle < 2**64 - 1


def _asset_identity(item: WorkshopItem) -> dict[str, object]:
    return {
        "developer_metadata_sha256": hashlib.sha256(
            item.developer_metadata.encode("utf-8")
        ).hexdigest(),
        "content_handle": item.content_handle,
        "preview_handle": item.preview_handle,
        "preview_url": item.preview_url,
    }


@dataclass(slots=True)
class _PendingUpdate:
    item_id: int
    current: WorkshopItem
    language: str = ""
    description: str = ""
    content: Path | None = None
    preview: Path | None = None
    metadata: str = ""


class _NativeHelperBackend:
    """Run the Windows SDK helper in a dedicated App ID context per request."""

    def __init__(self, item_id: int, owner_id: str, helper: Path | None) -> None:
        executable = (
            helper if helper is not None else Path(os.environ.get(_HELPER_ENV, _HELPER_DEFAULT))
        )
        if not executable.is_absolute() or not executable.is_file():
            raise RuntimeError(
                f"Steamworks helper is unavailable. Build tools/steam_workshop/build.ps1 "
                f"or set {_HELPER_ENV} to the absolute path of the built executable."
            )
        self._executable = executable
        self._item_id = item_id
        self._owner_id = owner_id
        version = self._request("version")
        if version.get("protocol") != 2:
            raise RuntimeError("Unsupported Steamworks helper protocol")
        self.supports_cache_download = version.get("download_cache") is True

    def _request(self, *arguments: str, timeout: int = 45) -> dict[str, object]:
        with tempfile.TemporaryDirectory(prefix="sitai-steam-app-") as work:
            cwd = Path(work)
            (cwd / "steam_appid.txt").write_bytes(f"{config.APP_ID}\n".encode("ascii"))
            # Keep the child App ID explicit even when launched from Steam tooling.
            environment = {
                **{key: os.environ[key] for key in _OS_ENV if key in os.environ},
                "SteamAppId": str(config.APP_ID),
                "SteamGameId": str(config.APP_ID),
            }
            try:
                result = subprocess.run(
                    [str(self._executable), *arguments],
                    cwd=cwd,
                    env=environment,
                    capture_output=True,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                raise RuntimeError("Steamworks helper timed out") from None
        if result.returncode:
            reason = result.stderr.decode("utf-8", errors="replace").strip()
            if result.returncode == 3 and arguments[0] == "update":
                raise WorkshopNotSubmittedError(f"Steamworks rejected update preparation. {reason}")
            raise RuntimeError(f"Steamworks helper failed ({result.returncode}) {reason}")
        try:
            data = json.loads(result.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Steamworks helper returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise RuntimeError("Steamworks helper returned a non-object")
        return data

    def app_id(self) -> int:
        # The native helper independently checks the actual app and account at
        # the beginning of every query and submission.
        return config.APP_ID

    def logged_on(self) -> bool:
        return True

    def current_user_id(self) -> str:
        return self._owner_id

    def query_item(self, published_file_id: int, language: str) -> WorkshopItem:
        data = self._request("query", str(published_file_id), self._owner_id, language)
        return WorkshopItem(
            published_file_id=_helper_value(data, "item_id", int),
            creator_app_id=_helper_value(data, "creator_app_id", int),
            consumer_app_id=_helper_value(data, "consumer_app_id", int),
            owner_id=_helper_value(data, "owner_id", str),
            is_owner=_helper_value(data, "is_owner", bool),
            banned=_helper_value(data, "banned", bool),
            title=_helper_value(data, "title", str),
            description=_helper_value(data, "description", str),
            developer_metadata=_helper_value(data, "developer_metadata", str),
            content_handle=_helper_value(data, "content_handle", int),
            preview_handle=_helper_value(data, "preview_handle", int),
            visibility=_helper_value(data, "visibility", int),
            preview_url=_helper_value(data, "preview_url", str),
            item_state=_helper_value(data, "item_state", int),
        )

    def start_item_update(
        self, app_id: int, published_file_id: int, current: WorkshopItem
    ) -> _PendingUpdate:
        if app_id != config.APP_ID or published_file_id != self._item_id:
            raise RuntimeError("Steamworks helper target changed")
        return _PendingUpdate(published_file_id, current)

    def set_item_update_language(self, handle: object, language: str) -> bool:
        _pending(handle).language = language
        return True

    def set_item_description(self, handle: object, description: str) -> bool:
        _pending(handle).description = description
        return True

    def set_item_content(self, handle: object, content_folder: Path) -> bool:
        _pending(handle).content = content_folder
        return True

    def set_item_preview(self, handle: object, preview_file: Path) -> bool:
        _pending(handle).preview = preview_file
        return True

    def set_item_metadata(self, handle: object, metadata: str) -> bool:
        _pending(handle).metadata = metadata
        return True

    def submit_item_update(self, handle: object, change_note: str) -> UpdateResult:
        pending = _pending(handle)
        with tempfile.TemporaryDirectory(prefix="sitai-steam-description-") as work:
            description = Path(work) / "description.bbcode"
            description.write_bytes(pending.description.encode("utf-8"))
            arguments = [
                "update",
                str(pending.item_id),
                self._owner_id,
                pending.language,
                str(description),
                pending.current.description,
            ]
            if pending.content is not None and pending.preview is not None:
                arguments.extend(
                    [
                        str(pending.content),
                        str(pending.preview),
                        pending.metadata,
                        change_note,
                        str(pending.current.preview_handle),
                        str(pending.current.content_handle),
                        pending.current.developer_metadata,
                    ]
                )
            data = self._request(*arguments, timeout=225)
        code = _helper_value(data, "result_code", int)
        return UpdateResult(
            succeeded=code == 1,
            published_file_id=_helper_value(data, "item_id", int),
            result_code=code,
            needs_legal_agreement=_helper_value(data, "needs_legal_agreement", bool),
        )

    def installed_item(self, published_file_id: int) -> Path | None:
        if published_file_id != self._item_id:
            raise RuntimeError("Steamworks installation target changed")
        data = self._request("installed", str(published_file_id), self._owner_id)
        raw = _helper_value(data, "install_path", str)
        return checked_path(Path(raw)) if raw else None

    def download_cache(self, published_file_id: int) -> tuple[Path, int, int]:
        if published_file_id != self._item_id or not self.supports_cache_download:
            raise RuntimeError("Steamworks cache download is unavailable for the target")
        data = self._request("download-cache", str(published_file_id), self._owner_id, timeout=225)
        before = _helper_value(data, "state_before", int)
        after = _helper_value(data, "state_after", int)
        path = Path(_helper_value(data, "install_path", str))
        # ISteamUGC v016 EItemState: only the Installed bit may remain.
        if (
            _helper_value(data, "app_id", int) != config.APP_ID
            or _helper_value(data, "item_id", int) != published_file_id
            or _helper_value(data, "result_code", int) != 1
            or before < 0
            or before & _ITEM_SUBSCRIBED
            or after != _ITEM_INSTALLED
            or not path.is_absolute()
        ):
            raise RuntimeError("Steamworks cache download confirmation is invalid")
        return checked_path(path), before, after

    def cached_item(self, published_file_id: int) -> Path | None:
        if published_file_id != self._item_id or not self.supports_cache_download:
            raise RuntimeError("Steamworks cache inspection is unavailable for the target")
        data = self._request("cached", str(published_file_id), self._owner_id)
        raw = _helper_value(data, "install_path", str)
        if raw and not Path(raw).is_absolute():
            raise RuntimeError("Steamworks cache path is not absolute")
        return checked_path(Path(raw)) if raw else None

    def preview_sha256(self, item: WorkshopItem) -> str:
        _validate_preview_url(item.preview_url)
        request = Request(item.preview_url, headers={"Accept": "image/*"})
        with build_opener(_PreviewRedirect()).open(request, timeout=30) as response:
            _validate_preview_url(response.url)
            raw = response.read(1_000_000)
        if not raw or len(raw) >= 1_000_000:
            raise RuntimeError("Steam 主预览大小超出正式规格")
        return hashlib.sha256(raw).hexdigest()


def _validate_preview_url(value: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _CDN_HOSTS
        or parsed.port not in (None, 443)
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise RuntimeError("Steam 主预览地址不属于已知的 HTTPS CDN")


class _PreviewRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_preview_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _helper_value[T](data: Mapping[str, object], key: str, expected: type[T]) -> T:
    value = data.get(key)
    if not isinstance(value, expected) or type(value) is not expected:
        raise RuntimeError(f"Steamworks helper field {key} is missing or invalid")
    return value


def _pending(handle: object) -> _PendingUpdate:
    if not isinstance(handle, _PendingUpdate):
        raise RuntimeError("Unknown Steamworks update handle")
    return handle


class SteamWorkshop:
    """Read and update one existing item with the explicitly selected account."""

    def __init__(
        self,
        app_id: int,
        item_id: int,
        owner_id: int,
        backend: SteamUGCBackend | None = None,
        *,
        helper: Path | None = None,
        installation: Path | None = None,
    ) -> None:
        if app_id != config.APP_ID:
            raise ValueError(f"Steamworks App ID 必须是 Victoria 3 ({config.APP_ID})")
        self.item_id = _target_id(item_id, "item")
        self.owner_id = str(_target_id(owner_id, "owner"))
        self.installation = checked_path(installation) if installation is not None else None
        self.backend: SteamUGCBackend = (
            backend
            if backend is not None
            else _NativeHelperBackend(self.item_id, self.owner_id, helper)
        )

    def _query(self, language: str) -> WorkshopItem:
        return _verify_item(
            self.backend.query_item(self.item_id, language), self.item_id, self.owner_id, language
        )

    def _observe(self, descriptions: Mapping[str, str]) -> dict[str, WorkshopItem]:
        if (
            self.backend.app_id() != config.APP_ID
            or not self.backend.logged_on()
            or self.backend.current_user_id() != self.owner_id
        ):
            raise RuntimeError("Steamworks App ID 或登录所有者不符")
        items = {language: self._query(language) for language in descriptions}
        if items["english"].title != WORKSHOP_TITLE:
            raise RuntimeError("目标 Workshop 条目的英文标题与 Situated AI 不符")
        return items

    def preflight(
        self,
        package_files: Mapping[str, bytes],
        *,
        package_sha256: str,
        previous: Mapping[str, object] | None = None,
        refresh_cached_readback: bool = False,
    ) -> dict[str, object]:
        """Validate package, localized text and the Steam target without updating."""
        if package_files:
            _validate_package_files(package_files)
        descriptions = load_descriptions()
        identity = self._release_identity(package_files, descriptions, package_sha256)
        items = self._observe(descriptions)
        state = self._resume(identity, descriptions, items, previous)
        if (
            previous
            and previous.get("status") == "verified"
            and not (refresh_cached_readback and "download_cache" in previous)
        ):
            self._verify_assets(
                items[next(iter(descriptions))],
                package_files,
                state,
                lambda _: None,
                download_cache=False,
            )
        installed = (
            self.backend.installed_item(self.item_id) if self.installation is not None else None
        )
        if self.installation is not None and self.installation != installed:
            raise RuntimeError("手动指定的订阅目录与 Steamworks 返回的目录不一致")
        return {
            **identity,
            "status": "ready",
            "public": True,
            "languages": list(descriptions),
            "checkpoint": state,
        }

    def _release_identity(
        self,
        package_files: Mapping[str, bytes],
        descriptions: Mapping[str, str],
        package_sha256: str,
    ) -> dict[str, object]:
        _validate_sha256(package_sha256)
        manifest = package_files.get(distribution.MANIFEST_NAME)
        return {
            "published_file_id": self.item_id,
            "owner_id": self.owner_id,
            "app_id": config.APP_ID,
            "package_sha256": package_sha256,
            "manifest_sha256": hashlib.sha256(manifest).hexdigest() if manifest is not None else "",
            "verification_installation": str(self.installation)
            if self.installation is not None
            else None,
            "description_sha256": {
                language: _description_sha256(text) for language, text in descriptions.items()
            },
        }

    def _resume(
        self,
        identity: Mapping[str, object],
        descriptions: Mapping[str, str],
        items: Mapping[str, WorkshopItem],
        previous: Mapping[str, object] | None,
    ) -> dict[str, object]:
        asset_language = next(iter(descriptions))
        if not previous:
            return {
                **identity,
                "status": "publishing",
                "verified_languages": [],
                "before_descriptions": {
                    language: _description_sha256(item.description)
                    for language, item in items.items()
                },
                "before_assets": _asset_identity(items[asset_language]),
            }
        if any(previous.get(key) != value for key, value in identity.items()):
            raise ValueError("Workshop 发布收据与当前发布身份不符")
        before = previous.get("before_descriptions")
        verified = previous.get("verified_languages")
        pending = previous.get("pending_language")
        if (
            not isinstance(before, dict)
            or before.keys() != descriptions.keys()
            or not isinstance(verified, list)
            or any(not isinstance(code, str) or code not in descriptions for code in verified)
            or (
                pending is not None
                and (not isinstance(pending, str) or pending not in descriptions)
            )
        ):
            raise ValueError("Workshop 发布进度收据损坏")
        ordered = _update_order(descriptions)
        if verified != ordered[: len(verified)] or (
            pending is not None and pending != next(iter(ordered[len(verified) :]), None)
        ):
            raise ValueError("Workshop 发布进度次序与当前发布范围不符")
        current_assets = items[asset_language]
        marker = _package_marker(str(identity["package_sha256"]), str(identity["manifest_sha256"]))
        if asset_language in verified:
            if not _assets_match(current_assets, marker) or previous.get(
                "assets"
            ) != _asset_identity(current_assets):
                raise RuntimeError("已确认的 Workshop 资产后来发生变更")
        elif pending == asset_language:
            if not _assets_match(current_assets, marker):
                raise RuntimeError(
                    "Steam 资产提交结果未知，远端尚未回读目标版本。"
                    "保留收据，用同一参数重跑查询。若仍无法确认，请在 Steam 核实原提交结果。"
                )
        elif previous.get("before_assets") != _asset_identity(current_assets):
            raise RuntimeError("Workshop 资产在发布期间被修改")

        for language, item in items.items():
            observed = _description_sha256(item.description)
            expected = _description_sha256(descriptions[language])
            if language in verified or language == pending:
                if observed != expected:
                    if language in verified:
                        raise RuntimeError(f"已确认的 Workshop 语言 {language} 后来发生变更")
                    raise RuntimeError(
                        f"Workshop 语言 {language} 的提交结果未确认。"
                        "保留收据，用同一参数重跑查询。若仍无法确认，请在 Steam 核实原提交结果。"
                    )
            elif observed != before[language]:
                raise RuntimeError(f"Workshop 语言 {language} 在发布期间被修改")
        return dict(previous)

    def publish(
        self,
        package_files: Mapping[str, bytes],
        *,
        package_sha256: str,
        checkpoint: Callable[[dict[str, object]], None],
        previous: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        """Update the existing item and verify localized descriptions and download bytes."""
        data, contract = _validate_package_files(package_files)
        descriptions = load_descriptions()
        identity = self._release_identity(data, descriptions, package_sha256)
        items = self._observe(descriptions)
        state = self._resume(identity, descriptions, items, previous)
        marker = _package_marker(package_sha256, str(identity["manifest_sha256"]))
        checkpoint(dict(state))
        asset_language = next(iter(descriptions))
        verified_languages = list(_verified_languages(state))

        def mark_pending(language: str) -> None:
            state.pop("last_rejected_update", None)
            state["pending_language"] = language
            checkpoint(dict(state))

        with tempfile.TemporaryDirectory(prefix="situated-ai-steam-") as temporary_root:
            content_root = Path(temporary_root) / "content"
            for language in _update_order(descriptions)[len(verified_languages) :]:
                description = descriptions[language]
                current = self._query(language)
                needs_content = language == asset_language and not _assets_match(current, marker)
                needs_text = not _description_matches(current, description)
                self._ensure_prestate(language, current, items[language], asset_language)
                if needs_content or needs_text:
                    if needs_content:
                        _write_content_tree(data, content_root)
                    try:
                        self._submit(
                            language,
                            description,
                            current,
                            content_root if needs_content else None,
                            marker,
                            f"Situated AI {contract['product_version']}",
                            mark_pending,
                        )
                    except (WorkshopNotSubmittedError, WorkshopUpdateRejectedError) as exc:
                        state.pop("pending_language", None)
                        state["last_rejected_update"] = {
                            "language": language,
                            "status": "steam_rejected"
                            if isinstance(exc, WorkshopUpdateRejectedError)
                            else "not_submitted",
                            "result_code": exc.code
                            if isinstance(exc, WorkshopUpdateRejectedError)
                            else None,
                        }
                        checkpoint(dict(state))
                        raise
                    current = self._query(language)
                if not _description_matches(current, description):
                    raise RuntimeError(f"Steam 未回读预期的 {language} 描述")
                if language == asset_language:
                    if not _assets_match(current, marker):
                        raise RuntimeError("Steam 未回读当前正式包指纹和主预览句柄")
                    state["assets"] = _asset_identity(current)
                verified_languages.append(language)
                state.pop("pending_language", None)
                state["verified_languages"] = list(verified_languages)
                checkpoint(dict(state))

        after = self._observe(descriptions)
        self._resume(identity, descriptions, after, state)
        state["status"] = "uploaded"
        checkpoint(dict(state))
        self._verify_assets(after[asset_language], data, state, checkpoint)
        self._resume(identity, descriptions, self._observe(descriptions), state)
        state["status"] = "verified"
        checkpoint(dict(state))
        return state

    def _verify_assets(
        self,
        current: WorkshopItem,
        files: Mapping[str, bytes],
        state: dict[str, object],
        checkpoint: Callable[[dict[str, object]], None],
        *,
        download_cache: bool = True,
    ) -> None:
        expected_preview = hashlib.sha256(files[distribution.THUMBNAIL_NAME]).hexdigest()
        state["preview"] = {"status": "checking", "expected_sha256": expected_preview}
        checkpoint(dict(state))
        observed_preview = self.backend.preview_sha256(current)
        state["preview"] = {
            "status": "verified" if observed_preview == expected_preview else "mismatch",
            "expected_sha256": expected_preview,
            "observed_sha256": observed_preview,
        }
        if observed_preview != expected_preview:
            checkpoint(dict(state))
            raise RuntimeError("Steam 主预览 CDN 字节与正式封面不一致")
        installed = self.backend.installed_item(self.item_id)
        if (
            installed is None
            and self.installation is None
            and isinstance(self.backend, SteamCacheBackend)
            and self.backend.supports_cache_download
            and not current.item_state & _ITEM_SUBSCRIBED
        ):
            self._verify_cached_assets(self.backend, files, state, checkpoint, download_cache)
            return
        state.pop("download_cache", None)
        if installed is None:
            state["subscription"] = {"status": "awaiting_current_installation"}
            checkpoint(dict(state))
            raise RuntimeError("Steam 尚未提供该条目的当前安装目录，无法核对订阅内容")
        if self.installation is not None and self.installation != installed:
            state["subscription"] = {"status": "installation_mismatch"}
            checkpoint(dict(state))
            raise RuntimeError("手动指定的订阅目录与 Steamworks 返回的目录不一致")
        state["subscription"] = {"status": "checking", "path": str(installed)}
        checkpoint(dict(state))
        _verify_download_tree(installed, files)
        if self.backend.installed_item(self.item_id) != installed:
            raise RuntimeError("订阅文件核对期间 Steam 安装状态发生变化")
        state["subscription"] = {
            "status": "verified",
            "path": str(installed),
            "files": len(files),
            "transformations": [],
        }

    def _verify_cached_assets(
        self,
        backend: SteamCacheBackend,
        files: Mapping[str, bytes],
        state: dict[str, object],
        checkpoint: Callable[[dict[str, object]], None],
        download_cache: bool,
    ) -> None:
        state.pop("subscription", None)
        if download_cache:
            state["download_cache"] = {"status": "downloading"}
            checkpoint(dict(state))
            path, before, after = backend.download_cache(self.item_id)
            evidence = {
                "app_id": config.APP_ID,
                "item_id": self.item_id,
                "result_code": 1,
                "state_before": before,
                "state_after": after,
                "path": str(path),
            }
            state["download_cache"] = {"status": "checking", **evidence}
            checkpoint(dict(state))
        else:
            receipt = state.get("download_cache")
            if not isinstance(receipt, dict) or receipt.get("status") != "verified":
                raise RuntimeError("缺少此条目的 Steam 临时缓存下载收据")
            cached = backend.cached_item(self.item_id)
            if cached is None or str(cached) != receipt.get("path"):
                raise RuntimeError("Steam 临时缓存已失效，需要重新读取")
            path = cached
            evidence = receipt
        _verify_download_tree(path, files)
        if backend.cached_item(self.item_id) != path:
            raise RuntimeError("核对文件期间 Steam 临时缓存状态发生变化")
        state["download_cache"] = {
            **evidence,
            "status": "verified",
            "files": len(files),
            "transformations": [],
        }

    @staticmethod
    def _ensure_prestate(
        language: str, current: WorkshopItem, observed: WorkshopItem, asset_language: str
    ) -> None:
        if _description_sha256(current.description) != _description_sha256(observed.description):
            raise RuntimeError(f"Workshop 语言 {language} 在提交前被修改")
        if language == asset_language and _asset_identity(current) != _asset_identity(observed):
            raise RuntimeError("Workshop 资产在提交前被修改")

    def _submit(
        self,
        language: str,
        description: str,
        current: WorkshopItem,
        content_root: Path | None,
        marker: str,
        change_note: str,
        mark_pending: Callable[[str], None],
    ) -> None:
        handle = self.backend.start_item_update(config.APP_ID, self.item_id, current)
        _require_setter(self.backend.set_item_update_language(handle, language), "language")
        _require_setter(self.backend.set_item_description(handle, description), "description")
        if content_root is not None:
            _require_setter(self.backend.set_item_content(handle, content_root), "content")
            _require_setter(
                self.backend.set_item_preview(handle, content_root / distribution.THUMBNAIL_NAME),
                "preview",
            )
            _require_setter(self.backend.set_item_metadata(handle, marker), "package metadata")
        mark_pending(language)
        result = self.backend.submit_item_update(handle, change_note if content_root else "")
        if result.needs_legal_agreement:
            raise RuntimeError("Steam 要求接受 Workshop Legal Agreement")
        if result.published_file_id != self.item_id:
            raise RuntimeError(
                f"Steam 返回的 Workshop 语言 {language} 提交回调条目 ID 不符，提交结果未确认"
            )
        if not result.succeeded:
            code = result.result_code
            if code is not None and code in _SUBMIT_REJECTION_CODES:
                raise WorkshopUpdateRejectedError(language, code)
            raise RuntimeError(
                f"Steam 返回的 Workshop 语言 {language} 提交结果未确认。"
                f" {result.message or result.result_code or 'unknown result'}"
            )


def _update_order(descriptions: Mapping[str, str]) -> list[str]:
    # Other locale queries can fall back to English; keep that baseline fixed
    # until the last submit to detect intervening changes reliably.
    return [*(language for language in descriptions if language != "english"), "english"]


def _verified_languages(state: Mapping[str, object]) -> list[str]:
    value = state.get("verified_languages")
    if not isinstance(value, list) or not all(isinstance(language, str) for language in value):
        raise ValueError("Workshop 已确认语言收据损坏")
    return value


def _verify_download_tree(root: Path, files: Mapping[str, bytes]) -> None:
    root = checked_path(root)
    if not root.is_dir():
        raise RuntimeError("Steam 下载未提供可用目录")
    expected_directories = {
        parent.as_posix()
        for name in files
        for parent in PurePosixPath(name).parents
        if parent.parts
    }
    observed: set[str] = set()
    for current, directories, names in root.walk(follow_symlinks=False):
        for directory_name in directories:
            directory = checked_path(current / directory_name)
            if directory.relative_to(root).as_posix() not in expected_directories:
                raise RuntimeError("Steam 下载包含未登记目录")
        for name in names:
            path = checked_path(current / name)
            relative = path.relative_to(root).as_posix()
            expected = files.get(relative)
            if expected is None or not path.is_file() or path.stat().st_size != len(expected):
                raise RuntimeError(f"Steam 下载文件集合或长度不符 {relative}")
            if path.read_bytes() != expected:
                raise RuntimeError(f"Steam 下载文件字节不符 {relative}")
            observed.add(relative)
    if observed != files.keys():
        raise RuntimeError("Steam 下载缺少正式包文件")


def _validate_sha256(value: str) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("Steam 发布包 SHA-256 必须是 64 位小写十六进制摘要")
