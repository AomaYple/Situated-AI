"""只替换 Steam 外部边界；真实适配器须遵守 ABI、归属、提交及语言读回协议。"""

import ctypes
import json
import subprocess
from pathlib import Path

import pytest


class Function:
    def __init__(self, action):
        self.action = action

    def __call__(self, *args):
        return self.action(*args)


class SteamDLL:
    """模拟 Steam 服务状态；调用真实适配器，避免任何测试写入真实工坊。"""

    def __init__(self, module, *, owner=77, app=529340, result=1, legal=False):
        self.module = module
        self.owner = owner
        self.app = app
        self.result = result
        self.legal = legal
        self.languages = {"english": "old English", "schinese": "old Chinese"}
        self.query_language = "english"
        self.update_language = "english"
        self.pending_body = None
        self.updates = 0
        self.shutdown = False
        self.query_released = 0
        self.long_description = False
        self.cached_age = None
        self.preview = None
        self.content = None
        self.completed = True

    def __getattr__(self, name):
        action = getattr(self, name.removeprefix("SteamAPI_"))
        return Function(action)

    def Init(self):
        return True

    def Shutdown(self):
        self.shutdown = True

    def RunCallbacks(self):
        return None

    def SteamUGC_v016(self):
        return 1

    def SteamUtils_v010(self):
        return 2

    def SteamUser_v021(self):
        return 3

    def ISteamUtils_GetAppID(self, _self):
        return 529340

    def ISteamUser_BLoggedOn(self, _self):
        return True

    def ISteamUser_GetSteamID(self, _self):
        return 77

    def ISteamUGC_CreateQueryUGCDetailsRequest(self, _self, ids, count):
        assert ids[0] == 3826910830
        assert count == 1
        return 11

    def ISteamUGC_SetReturnLongDescription(self, _self, _query, value):
        self.long_description = value
        return True

    def ISteamUGC_SetLanguage(self, _self, _query, language):
        self.query_language = language.decode()
        return True

    def ISteamUGC_SetAllowCachedResponse(self, _self, _query, value):
        self.cached_age = value
        return True

    def ISteamUGC_SendQueryUGCRequest(self, _self, _query):
        return 21

    def ISteamUtils_IsAPICallCompleted(self, _self, _call, failed):
        ctypes.cast(failed, ctypes.POINTER(ctypes.c_bool))[0] = False
        return self.completed

    def ISteamUtils_GetAPICallResult(self, _self, _call, buffer, size, callback, failed):
        ctypes.cast(failed, ctypes.POINTER(ctypes.c_bool))[0] = False
        if callback == 3401:
            assert size == 280
            value = ctypes.cast(buffer, ctypes.POINTER(self.module.QueryCompleted)).contents
            value.handle = 11
            value.result = 1
            value.returned = value.matching = 1
            value.cached = False
        elif callback == 3404:
            assert size == 16
            value = ctypes.cast(buffer, ctypes.POINTER(self.module.UpdateCompleted)).contents
            value.result = self.result
            value.legal = self.legal
            value.item_id = 3826910830
        else:
            pytest.fail(f"错误 callback: {callback}")
        return True

    def ISteamUGC_GetQueryUGCResult(self, _self, _query, _index, output):
        value = ctypes.cast(output, ctypes.POINTER(self.module.ItemDetails)).contents
        value.item_id = 3826910830
        value.result = 1
        value.creator_app = value.consumer_app = self.app
        value.owner = self.owner
        value.title = b"Situated AI"
        value.description = self.languages.get(self.query_language, "").encode()
        value.updated = 123
        return True

    def ISteamUGC_ReleaseQueryUGCRequest(self, _self, _query):
        self.query_released += 1
        return True

    def ISteamUGC_StartItemUpdate(self, _self, app, item):
        assert app == 529340
        assert item == 3826910830
        self.updates += 1
        return 31

    def ISteamUGC_SetItemUpdateLanguage(self, _self, _handle, language):
        self.update_language = language.decode()
        return True

    def ISteamUGC_SetItemDescription(self, _self, _handle, body):
        self.pending_body = body.decode()
        return True

    def ISteamUGC_SetItemContent(self, _self, _handle, directory):
        self.content = Path(directory.decode())
        return True

    def ISteamUGC_SetItemPreview(self, _self, _handle, path):
        self.preview = Path(path.decode())
        return True

    def ISteamUGC_SubmitItemUpdate(self, _self, _handle, _note):
        if self.result == 1 and self.pending_body is not None:
            self.languages[self.update_language] = self.pending_body
        return 41


def native(monkeypatch, **kwargs):
    from pdx import steam_workshop

    dll = SteamDLL(steam_workshop, **kwargs)
    monkeypatch.setattr(steam_workshop.sys, "platform", "win32")
    monkeypatch.setattr(steam_workshop.ctypes, "CDLL", lambda _path: dll)
    return steam_workshop, dll, steam_workshop.NativeSteam(Path("steam_api64.dll"), 3826910830)


def test_description_update_sets_language_and_verifies_exact_body(monkeypatch):
    _, dll, api = native(monkeypatch)
    with api:
        result = api.describe("schinese", "[b]新正文[/b]")
    assert result["readback_verified"] is True
    assert dll.languages == {"english": "old English", "schinese": "[b]新正文[/b]"}
    assert dll.long_description is True
    assert dll.cached_age == 0
    assert dll.query_released == 2
    assert dll.shutdown is True


@pytest.mark.parametrize("settings", [{"owner": 88}, {"app": 999}])
def test_wrong_owner_or_app_prevents_starting_update(monkeypatch, settings):
    _, dll, api = native(monkeypatch, **settings)
    with api, pytest.raises(ValueError, match=r"所有者|App"):
        api.describe("english", "new")
    assert dll.updates == 0
    assert dll.shutdown is True


@pytest.mark.parametrize("settings", [{"result": 15}, {"legal": True}])
def test_failure_or_legal_agreement_never_reports_success(monkeypatch, settings):
    _, _, api = native(monkeypatch, **settings)
    with api, pytest.raises(ValueError, match=r"Steam|协议"):
        api.describe("english", "new")


def test_content_upload_uses_directory_and_its_thumbnail(tmp_path, monkeypatch):
    _, dll, api = native(monkeypatch)
    (tmp_path / "thumbnail.png").write_bytes(b"png")
    with api:
        result = api.upload(tmp_path, "更新说明")
    assert result["result"] == 1
    assert dll.content == tmp_path.resolve()
    assert dll.preview == tmp_path.resolve() / "thumbnail.png"
    assert dll.languages == {"english": "old English", "schinese": "old Chinese"}


def test_failed_readback_is_explicitly_uncertain(monkeypatch):
    module, dll, api = native(monkeypatch)
    original = dll.ISteamUGC_SubmitItemUpdate

    def lose_body(*args):
        result = original(*args)
        dll.languages["schinese"] = "server did not retain requested body"
        return result

    monkeypatch.setattr(dll, "ISteamUGC_SubmitItemUpdate", lose_body)
    with api, pytest.raises(module.WorkshopError, match="读回") as caught:
        api.describe("schinese", "new")
    assert caught.value.submitted is True


def test_callback_timeout_is_bounded(monkeypatch):
    _, dll, api = native(monkeypatch)
    dll.completed = False
    with api, pytest.raises(ValueError, match="超时"):
        api.inspect(["english"], timeout=0)
    assert dll.query_released == 1


def test_gateway_does_not_accept_zero_exit_without_response(tmp_path, monkeypatch):
    from pdx import steam_workshop

    monkeypatch.setattr(
        steam_workshop.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0),
    )
    remote = steam_workshop.SteamWorkshop(3826910830, tmp_path)
    with pytest.raises(ValueError, match="响应"):
        remote.inspect(["english"])


def test_worker_crash_after_write_is_uncertain(tmp_path, monkeypatch):
    from pdx import steam_workshop

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("steam", 1)

    monkeypatch.setattr(steam_workshop.subprocess, "run", timeout)
    remote = steam_workshop.SteamWorkshop(3826910830, tmp_path)
    with pytest.raises(steam_workshop.WorkshopError) as caught:
        remote.describe("english", "body")
    assert caught.value.submitted is True


def test_worker_serializes_failure_without_leaking_steam_stdout(tmp_path, monkeypatch):
    from pdx import steam_workshop

    def fail(args, **kwargs):
        Path(args[-1]).write_text(
            json.dumps({"ok": False, "error": "Steam result=15", "submitted": True}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args, 1, stdout="private Steam output", stderr="")

    monkeypatch.setattr(steam_workshop.subprocess, "run", fail)
    remote = steam_workshop.SteamWorkshop(3826910830, tmp_path)
    with pytest.raises(steam_workshop.WorkshopError, match="result=15") as caught:
        remote.describe("english", "body")
    assert "private Steam output" not in str(caught.value)


def test_malformed_worker_response_is_a_publication_error(tmp_path, monkeypatch):
    from pdx import steam_workshop

    def malformed(args, **kwargs):
        Path(args[-1]).write_text("[]", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(steam_workshop.subprocess, "run", malformed)
    with pytest.raises(steam_workshop.WorkshopError, match="响应"):
        steam_workshop.SteamWorkshop(3826910830, tmp_path).inspect(["english"])


def test_known_steam_rejection_is_failed_and_not_unknown(monkeypatch):
    module, _, api = native(monkeypatch, result=15)
    with api, pytest.raises(module.WorkshopError) as caught:
        api.describe("english", "new")
    assert caught.value.submitted is True
    assert caught.value.uncertain is False
