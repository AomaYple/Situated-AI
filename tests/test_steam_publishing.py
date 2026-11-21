"""Verify Steam publishing and recovery with a fake SDK transport."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from pdx import config, distribution, version_contracts
from pdx.publishing import steam

if TYPE_CHECKING:
    from pathlib import Path

ITEM = 900001
OWNER = 900002
ZIP_SHA256 = "a" * 64


@pytest.fixture
def files() -> dict[str, bytes]:
    metadata: dict[str, object] = dict.fromkeys(distribution.LAUNCHER_METADATA_KEYS, "")
    metadata.update(
        {
            "name": steam.WORKSHOP_TITLE,
            "id": distribution.MOD_ID,
            "version": distribution.RELEASE_VERSION,
            "supported_game_version": version_contracts.active_version(),
            "picture": distribution.THUMBNAIL_NAME,
            "tags": [],
            "relationships": [],
            "game_custom_data": {},
        }
    )
    data = distribution.payloads(
        {
            distribution.METADATA_NAME: json.dumps(metadata) + "\n",
            distribution.THUMBNAIL_NAME: (
                config.REPO / "mod" / distribution.THUMBNAIL_NAME
            ).read_bytes(),
            "README.md": "Workshop package fixture\n",
            "common/fixture.txt": "fixture = yes\n",
            **{
                f"localization/{language}/sitai_decisions_l_{language}.yml": f'{header}:\n fixture:0 "Fixture"\n'
                for language, header in distribution.decisions.LANGUAGES.items()
            },
        }
    )
    manifest = distribution._manifest_for_payloads(
        data,
        generation={
            "product_contract": {
                "fallback_languages": [],
                "languages": list(distribution.decisions.LANGUAGES),
            },
        },
    )
    return {**data, distribution.MANIFEST_NAME: json.dumps(manifest).encode()}


class FakeSteamUGC:
    def __init__(self, installed: Path) -> None:
        self.installed = installed
        self.items: dict[str, steam.WorkshopItem] = {}
        self.queries: list[str] = []
        self.updates: list[str] = []
        self.uploads = 0
        self.preview: str | None = None
        self.fail_after_apply_language: str | None = None
        self.fail_before_apply_language: str | None = None
        self.reject_submission: tuple[str, steam.UpdateResult | RuntimeError] | None = None
        self.installation_available = True

    def app_id(self) -> int:
        return config.APP_ID

    def logged_on(self) -> bool:
        return True

    def current_user_id(self) -> str:
        return str(OWNER)

    def query_item(self, published_file_id: int, language: str) -> steam.WorkshopItem | None:
        assert published_file_id == ITEM
        self.queries.append(language)
        return self.items.get(language, self.items.get("english"))

    def start_item_update(
        self, app_id: int, published_file_id: int, current: steam.WorkshopItem
    ) -> object:
        assert (app_id, published_file_id) == (config.APP_ID, ITEM)
        return steam._PendingUpdate(published_file_id, current)

    def set_item_update_language(self, handle: object, language: str) -> bool:
        steam._pending(handle).language = language
        return True

    def set_item_description(self, handle: object, description: str) -> bool:
        steam._pending(handle).description = description
        return True

    def set_item_content(self, handle: object, content_folder: Path) -> bool:
        steam._pending(handle).content = content_folder
        return True

    def set_item_preview(self, handle: object, preview_file: Path) -> bool:
        steam._pending(handle).preview = preview_file
        return True

    def set_item_metadata(self, handle: object, metadata: str) -> bool:
        steam._pending(handle).metadata = metadata
        return True

    def submit_item_update(self, handle: object, change_note: str) -> steam.UpdateResult:
        pending = steam._pending(handle)
        language = pending.language
        current = self.query_item(ITEM, language)
        assert current is not None
        assert pending.current == current
        if self.reject_submission is not None and self.reject_submission[0] == language:
            _, rejection = self.reject_submission
            self.reject_submission = None
            if isinstance(rejection, RuntimeError):
                raise rejection
            return rejection
        if language == self.fail_before_apply_language:
            raise TimeoutError("simulated missing Steam callback")
        if pending.content is not None:
            assert pending.preview is not None
            assert change_note == f"Situated AI {distribution.RELEASE_VERSION}"
            assert (pending.content / distribution.MANIFEST_NAME).is_file()
            self.preview = hashlib.sha256(pending.preview.read_bytes()).hexdigest()
            self.uploads += 1
            for name, raw in distribution.payloads(
                {
                    path.relative_to(pending.content).as_posix(): path.read_bytes()
                    for path in pending.content.rglob("*")
                    if path.is_file() and path.name != distribution.MANIFEST_NAME
                }
            ).items():
                target = self.installed / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            manifest = distribution.MANIFEST_NAME
            (self.installed / manifest).write_bytes((pending.content / manifest).read_bytes())
            for key, item in self.items.items():
                self.items[key] = replace(
                    item, developer_metadata=pending.metadata, preview_handle=1
                )
        self.items[language] = replace(
            self.items.get(language, self.items["english"]),
            description=pending.description.replace("\n", "\r\n"),
        )
        self.updates.append(language)
        if language == self.fail_after_apply_language:
            self.fail_after_apply_language = None
            raise TimeoutError("simulated lost callback after remote commit")
        return steam.UpdateResult(True, ITEM, result_code=1)

    def installed_item(self, published_file_id: int) -> Path | None:
        assert published_file_id == ITEM
        return self.installed if self.installation_available and self.installed.is_dir() else None

    def preview_sha256(self, item: steam.WorkshopItem) -> str:
        assert item.preview_handle == 1
        assert self.preview is not None
        return self.preview


@pytest.fixture
def backend(tmp_path: Path) -> FakeSteamUGC:
    result = FakeSteamUGC(tmp_path / "subscription")
    result.items["english"] = steam.WorkshopItem(
        published_file_id=ITEM,
        creator_app_id=config.APP_ID,
        consumer_app_id=config.APP_ID,
        owner_id=str(OWNER),
        is_owner=True,
        banned=False,
        title=steam.WORKSHOP_TITLE,
        description="Previous English description",
        developer_metadata="",
        preview_handle=2,
    )
    return result


def _workshop(backend: FakeSteamUGC) -> steam.SteamWorkshop:
    return steam.SteamWorkshop(config.APP_ID, ITEM, OWNER, backend=backend)


def test_localized_description_map_has_the_eleven_steam_languages() -> None:
    descriptions = steam.load_descriptions()
    assert list(descriptions) == [
        "schinese",
        "english",
        "french",
        "german",
        "japanese",
        "koreana",
        "polish",
        "brazilian",
        "russian",
        "spanish",
        "turkish",
    ]
    assert all(text.startswith("[h1]Situated AI[/h1]") for text in descriptions.values())


def test_preflight_queries_every_language_without_writing(
    files: dict[str, bytes], backend: FakeSteamUGC
) -> None:
    result = _workshop(backend).preflight(files, package_sha256=ZIP_SHA256)
    assert result["status"] == "ready"
    assert result["published_file_id"] == ITEM
    assert backend.queries == list(steam.load_descriptions())
    assert not backend.updates


def test_publish_checks_all_languages_assets_and_subscription_bytes(
    files: dict[str, bytes], backend: FakeSteamUGC
) -> None:
    checkpoints: list[dict[str, object]] = []
    result = _workshop(backend).publish(
        files, package_sha256=ZIP_SHA256, checkpoint=checkpoints.append
    )
    assert result["status"] == "verified"
    preview, subscription = result["preview"], result["subscription"]
    assert isinstance(preview, dict)
    assert isinstance(subscription, dict)
    assert preview["status"] == "verified"
    assert subscription["status"] == "verified"
    assert set(backend.updates) == steam.load_descriptions().keys()
    assert backend.updates[-1] == "english"  # Keep fallback stable for the other locales.
    assert backend.uploads == 1
    assert len(backend.updates) == 11
    assert all(
        item.description.replace("\r\n", "\n") == steam.load_descriptions()[language]
        for language, item in backend.items.items()
    )
    marker = json.loads(backend.items["schinese"].developer_metadata)
    assert marker["package_sha256"] == ZIP_SHA256
    assert checkpoints[0]["status"] == "publishing"
    assert checkpoints[-1]["status"] == "verified"


def test_resume_reconciles_lost_callback_without_resubmitting(
    files: dict[str, bytes], backend: FakeSteamUGC
) -> None:
    workshop = _workshop(backend)
    backend.fail_after_apply_language = "french"
    checkpoints: list[dict[str, object]] = []
    with pytest.raises(TimeoutError, match="lost callback"):
        workshop.publish(files, package_sha256=ZIP_SHA256, checkpoint=checkpoints.append)

    prior = checkpoints[-1]
    assert prior["pending_language"] == "french"
    result = workshop.publish(
        files, package_sha256=ZIP_SHA256, checkpoint=checkpoints.append, previous=prior
    )
    assert result["status"] == "verified"
    assert backend.updates.count("french") == 1
    assert backend.uploads == 1


def test_unknown_submit_blocks_blind_retry(files: dict[str, bytes], backend: FakeSteamUGC) -> None:
    workshop = _workshop(backend)
    backend.fail_before_apply_language = "french"
    checkpoints: list[dict[str, object]] = []
    with pytest.raises(TimeoutError, match="missing Steam callback"):
        workshop.publish(files, package_sha256=ZIP_SHA256, checkpoint=checkpoints.append)
    with pytest.raises(RuntimeError, match="提交结果未确认"):
        workshop.publish(
            files,
            package_sha256=ZIP_SHA256,
            checkpoint=checkpoints.append,
            previous=checkpoints[-1],
        )
    assert backend.updates == ["schinese"]


@pytest.mark.parametrize("language", ["schinese", "french"])
def test_matching_rejection_can_retry_from_the_same_baseline(
    files: dict[str, bytes], backend: FakeSteamUGC, language: str
) -> None:
    workshop = _workshop(backend)
    backend.reject_submission = (language, steam.UpdateResult(False, ITEM, result_code=33))
    checkpoints: list[dict[str, object]] = []
    with pytest.raises(steam.WorkshopUpdateRejectedError, match="LockingFailed"):
        workshop.publish(files, package_sha256=ZIP_SHA256, checkpoint=checkpoints.append)

    previous = checkpoints[-1]
    assert "pending_language" not in previous
    assert previous["last_rejected_update"] == {
        "language": language,
        "status": "steam_rejected",
        "result_code": 33,
    }
    resumed = workshop.publish(
        files, package_sha256=ZIP_SHA256, checkpoint=checkpoints.append, previous=previous
    )
    assert resumed["status"] == "verified"
    assert backend.uploads == 1
    assert backend.updates.count(language) == 1


def test_matching_rejection_cannot_overwrite_asset_drift(
    files: dict[str, bytes], backend: FakeSteamUGC
) -> None:
    workshop = _workshop(backend)
    backend.reject_submission = ("schinese", steam.UpdateResult(False, ITEM, result_code=15))
    checkpoints: list[dict[str, object]] = []
    with pytest.raises(steam.WorkshopUpdateRejectedError, match="AccessDenied"):
        workshop.publish(files, package_sha256=ZIP_SHA256, checkpoint=checkpoints.append)
    previous = checkpoints[-1]
    backend.items["english"] = replace(backend.items["english"], preview_handle=3)
    with pytest.raises(RuntimeError, match="资产在发布期间被修改"):
        workshop.preflight(files, package_sha256=ZIP_SHA256, previous=previous)
    assert not backend.updates


@pytest.mark.parametrize(("item_id", "code"), [(ITEM + 1, 33), (ITEM, 2), (ITEM, 16)])
def test_unmatched_or_indeterminate_rejection_retains_pending_submission(
    files: dict[str, bytes], backend: FakeSteamUGC, item_id: int, code: int
) -> None:
    workshop = _workshop(backend)
    backend.reject_submission = ("schinese", steam.UpdateResult(False, item_id, result_code=code))
    checkpoints: list[dict[str, object]] = []
    with pytest.raises(RuntimeError, match="提交结果未确认"):
        workshop.publish(files, package_sha256=ZIP_SHA256, checkpoint=checkpoints.append)
    previous = checkpoints[-1]
    assert previous["pending_language"] == "schinese"
    with pytest.raises(RuntimeError, match="核实原提交结果"):
        workshop.preflight(files, package_sha256=ZIP_SHA256, previous=previous)
    assert not backend.updates


def test_confirmed_synchronous_rejection_records_no_pending_submission(
    files: dict[str, bytes], backend: FakeSteamUGC
) -> None:
    backend.reject_submission = ("schinese", steam.WorkshopNotSubmittedError("SDK refused update"))
    checkpoints: list[dict[str, object]] = []
    with pytest.raises(steam.WorkshopNotSubmittedError):
        _workshop(backend).publish(files, package_sha256=ZIP_SHA256, checkpoint=checkpoints.append)
    assert "pending_language" not in checkpoints[-1]
    assert checkpoints[-1]["last_rejected_update"] == {
        "language": "schinese",
        "status": "not_submitted",
        "result_code": None,
    }


def test_preflight_rejects_changed_locale_after_release(
    files: dict[str, bytes], backend: FakeSteamUGC
) -> None:
    workshop = _workshop(backend)
    receipt = workshop.publish(files, package_sha256=ZIP_SHA256, checkpoint=lambda _state: None)
    backend.items["koreana"] = replace(backend.items["koreana"], description="External edit")
    with pytest.raises(RuntimeError, match="koreana"):
        workshop.preflight(files, package_sha256=ZIP_SHA256, previous=receipt)
    assert len(backend.updates) == 11


def test_current_subscription_mismatch_stops_completion(
    files: dict[str, bytes], backend: FakeSteamUGC
) -> None:
    workshop = _workshop(backend)
    checkpoints: list[dict[str, object]] = []
    receipt = workshop.publish(files, package_sha256=ZIP_SHA256, checkpoint=checkpoints.append)
    (backend.installed / "README.md").write_bytes(b"Different bytes in current subscription\n")
    with pytest.raises(RuntimeError, match="Steam 下载文件"):
        workshop.publish(
            files, package_sha256=ZIP_SHA256, checkpoint=checkpoints.append, previous=receipt
        )
    assert checkpoints[-1]["status"] == "uploaded"
    assert len(backend.updates) == 11


def test_uploaded_workshop_waits_for_a_current_subscription_without_reupload(
    files: dict[str, bytes], backend: FakeSteamUGC
) -> None:
    workshop = _workshop(backend)
    backend.installation_available = False
    checkpoints: list[dict[str, object]] = []

    with pytest.raises(RuntimeError, match="无法核对订阅内容"):
        workshop.publish(files, package_sha256=ZIP_SHA256, checkpoint=checkpoints.append)

    previous = checkpoints[-1]
    assert previous["status"] == "uploaded"
    assert previous["subscription"] == {"status": "awaiting_current_installation"}
    assert len(backend.updates) == 11
    assert backend.uploads == 1

    backend.installation_available = True
    resumed = workshop.publish(
        files, package_sha256=ZIP_SHA256, checkpoint=checkpoints.append, previous=previous
    )
    assert resumed["status"] == "verified"
    assert len(backend.updates) == 11
    assert backend.uploads == 1


def test_non_owner_is_rejected_before_any_update(
    files: dict[str, bytes], backend: FakeSteamUGC
) -> None:
    backend.items["english"] = replace(backend.items["english"], owner_id="123", is_owner=False)
    with pytest.raises(RuntimeError, match="不是目标 Workshop item 的所有者"):
        _workshop(backend).publish(files, package_sha256=ZIP_SHA256, checkpoint=lambda _state: None)
    assert not backend.updates


def test_zero_item_id_is_rejected(backend: FakeSteamUGC) -> None:
    with pytest.raises(ValueError, match="positive 64-bit ID"):
        steam.SteamWorkshop(config.APP_ID, 0, OWNER, backend=backend)
