"""SteamUGC016 的一次性 Windows x64 适配；不创建工坊条目或保存登录凭据。

ABI 对应 Steamworks SDK 1.53 的 ISteamUGC016 / SteamUser021 / SteamUtils010。
结构采用 Windows 8 字节 packing；未知平台或接口版本显式失败，不猜测 ABI。
官方协议：https://partner.steamgames.com/doc/api/ISteamUGC
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pdx import config, deployment, distribution
from pdx.publishing_contract import normalized_description, validate_description, write_receipt

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import TracebackType


class WorkshopError(ValueError):
    """submitted 表示远端可能已变化；不能把超时当成没有发生写入。"""

    def __init__(self, message: str, *, submitted: bool = False, uncertain: bool = False) -> None:
        super().__init__(message)
        self.submitted = submitted
        self.uncertain = uncertain


class QueryCompleted(ctypes.Structure):
    _layout_ = "ms"
    _pack_ = 8
    _fields_ = [
        ("handle", ctypes.c_uint64),
        ("result", ctypes.c_int32),
        ("returned", ctypes.c_uint32),
        ("matching", ctypes.c_uint32),
        ("cached", ctypes.c_bool),
        ("cursor", ctypes.c_char * 256),
    ]


class UpdateCompleted(ctypes.Structure):
    _layout_ = "ms"
    _pack_ = 8
    _fields_ = [
        ("result", ctypes.c_int32),
        ("legal", ctypes.c_bool),
        ("item_id", ctypes.c_uint64),
    ]


class ItemDetails(ctypes.Structure):
    _layout_ = "ms"
    _pack_ = 8
    _fields_ = [
        ("item_id", ctypes.c_uint64),
        ("result", ctypes.c_int32),
        ("file_type", ctypes.c_int32),
        ("creator_app", ctypes.c_uint32),
        ("consumer_app", ctypes.c_uint32),
        ("title", ctypes.c_char * 129),
        ("description", ctypes.c_char * 8000),
        ("owner", ctypes.c_uint64),
        ("created", ctypes.c_uint32),
        ("updated", ctypes.c_uint32),
        ("added", ctypes.c_uint32),
        ("visibility", ctypes.c_int32),
        ("banned", ctypes.c_bool),
        ("accepted", ctypes.c_bool),
        ("truncated", ctypes.c_bool),
        ("tags", ctypes.c_char * 1025),
        ("file", ctypes.c_uint64),
        ("preview", ctypes.c_uint64),
        ("filename", ctypes.c_char * 260),
        ("file_size", ctypes.c_int32),
        ("preview_size", ctypes.c_int32),
        ("url", ctypes.c_char * 256),
        ("votes_up", ctypes.c_uint32),
        ("votes_down", ctypes.c_uint32),
        ("score", ctypes.c_float),
        ("children", ctypes.c_uint32),
    ]


class NativeSteam:
    """仅在隔离 worker 中实例化；测试可替换 CDLL 外部边界。"""

    def __init__(self, library: Path, item_id: int) -> None:
        if sys.platform != "win32" or ctypes.sizeof(ctypes.c_void_p) != 8:
            raise WorkshopError("工坊原生上传目前仅验证 Windows x64；本地部署和离线检查不受限")
        if type(item_id) is not int or not 0 < item_id < 2**64:
            raise WorkshopError("工坊条目 ID 无效")
        self.item_id = item_id
        self.library = library
        self.dll: Any = None

    def _fn(self, name: str, args: list[Any], result: Any) -> Any:
        try:
            function = getattr(self.dll, "SteamAPI_" + name)
        except AttributeError as exc:
            raise WorkshopError(f"Steam 接口版本或导出不受支持：{name}") from exc
        function.argtypes, function.restype = args, result
        return function

    def __enter__(self) -> NativeSteam:
        self.dll = ctypes.CDLL(str(self.library))
        if not self._fn("Init", [], ctypes.c_bool)():
            raise WorkshopError("SteamAPI_Init 失败；请启动 Steam 并登录拥有游戏和工坊条目的账号")
        try:
            self.ugc = self._fn("SteamUGC_v016", [], ctypes.c_void_p)()
            self.utils = self._fn("SteamUtils_v010", [], ctypes.c_void_p)()
            self.user = self._fn("SteamUser_v021", [], ctypes.c_void_p)()
            if not (self.ugc and self.utils and self.user):
                raise WorkshopError("Steam 接口不可用")
            app = self._fn("ISteamUtils_GetAppID", [ctypes.c_void_p], ctypes.c_uint32)(self.utils)
            logged_on = self._fn("ISteamUser_BLoggedOn", [ctypes.c_void_p], ctypes.c_bool)(
                self.user
            )
            if app != config.APP_ID or not logged_on:
                raise WorkshopError("Steam App ID 不符或账号未登录")
            self.user_id = self._fn("ISteamUser_GetSteamID", [ctypes.c_void_p], ctypes.c_uint64)(
                self.user
            )
        except BaseException:
            self._fn("Shutdown", [], None)()
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._fn("Shutdown", [], None)()

    def _ugc(self, method: str, args: list[Any], result: Any, *values: Any) -> Any:
        return self._fn("ISteamUGC_" + method, [ctypes.c_void_p, *args], result)(self.ugc, *values)

    def _wait(
        self, call: int, output: Any, callback: int, timeout: float, *, submitted: bool = False
    ) -> None:
        if not call:
            raise WorkshopError("Steam 异步调用未创建", submitted=submitted)
        failed = ctypes.c_bool()
        completed = self._fn(
            "ISteamUtils_IsAPICallCompleted",
            [ctypes.c_void_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_bool)],
            ctypes.c_bool,
        )
        deadline = time.monotonic() + timeout
        while not completed(self.utils, call, ctypes.byref(failed)):
            if time.monotonic() >= deadline:
                raise WorkshopError(
                    "Steam 异步调用超时；已提交的上传可能仍在服务端处理",
                    submitted=submitted,
                    uncertain=submitted,
                )
            self._fn("RunCallbacks", [], None)()
            time.sleep(0.1)
        if failed.value:
            raise WorkshopError("Steam 异步调用失败", submitted=submitted, uncertain=submitted)
        read = self._fn(
            "ISteamUtils_GetAPICallResult",
            [
                ctypes.c_void_p,
                ctypes.c_uint64,
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_bool),
            ],
            ctypes.c_bool,
        )
        if (
            not read(
                self.utils,
                call,
                ctypes.byref(output),
                ctypes.sizeof(output),
                callback,
                ctypes.byref(failed),
            )
            or failed.value
        ):
            raise WorkshopError(
                "Steam 回调读取失败或 ABI 不符", submitted=submitted, uncertain=submitted
            )

    def _query(self, language: str, timeout: float) -> dict[str, Any]:
        item_ids = (ctypes.c_uint64 * 1)(self.item_id)
        handle = self._ugc(
            "CreateQueryUGCDetailsRequest",
            [ctypes.POINTER(ctypes.c_uint64), ctypes.c_uint32],
            ctypes.c_uint64,
            item_ids,
            1,
        )
        if handle in {0, 2**64 - 1}:
            raise WorkshopError("Steam 无法创建条目查询")
        try:
            for name, argtype, value in (
                ("SetReturnLongDescription", ctypes.c_bool, True),
                ("SetLanguage", ctypes.c_char_p, language.encode("ascii")),
                ("SetAllowCachedResponse", ctypes.c_uint32, 0),
            ):
                if not self._ugc(name, [ctypes.c_uint64, argtype], ctypes.c_bool, handle, value):
                    raise WorkshopError(f"Steam 查询选项失败：{name}")
            call = self._ugc("SendQueryUGCRequest", [ctypes.c_uint64], ctypes.c_uint64, handle)
            result = QueryCompleted()
            self._wait(call, result, 3401, timeout)
            if (
                result.result != 1
                or result.returned != 1
                or result.handle != handle
                or result.cached
            ):
                raise WorkshopError(f"Steam 查询未返回当前条目：result={result.result}")
            details = ItemDetails()
            if not self._ugc(
                "GetQueryUGCResult",
                [ctypes.c_uint64, ctypes.c_uint32, ctypes.POINTER(ItemDetails)],
                ctypes.c_bool,
                handle,
                0,
                ctypes.byref(details),
            ):
                raise WorkshopError("Steam 条目详情读取失败")
            if details.result != 1 or details.item_id != self.item_id or details.banned:
                raise WorkshopError("Steam 条目身份不符、不可用或已被封禁")
            if details.creator_app != config.APP_ID or details.consumer_app != config.APP_ID:
                raise WorkshopError("工坊条目 App ID 不属于 Victoria 3")
            if details.owner != self.user_id:
                raise WorkshopError("当前 Steam 账号不是工坊条目的所有者")
            return {
                "item_id": details.item_id,
                "owner_matches": True,
                "creator_app_id": details.creator_app,
                "consumer_app_id": details.consumer_app,
                "title": bytes(details.title).decode("utf-8"),
                "updated": details.updated,
                "description": bytes(details.description).decode("utf-8"),
            }
        finally:
            self._ugc("ReleaseQueryUGCRequest", [ctypes.c_uint64], ctypes.c_bool, handle)

    def inspect(self, languages: Sequence[str], *, timeout: float = 30) -> dict[str, Any]:
        descriptions = {}
        first = None
        for language in languages or ("english",):
            row = self._query(language, timeout)
            if first is None:
                first = row
            descriptions[language] = row["description"]
        assert first is not None
        return {key: value for key, value in first.items() if key != "description"} | {
            "descriptions": descriptions
        }

    def _start(self) -> int:
        self.inspect(())  # 每次写入前重新核对归属，不依赖旧预检结果。
        handle = self._ugc(
            "StartItemUpdate",
            [ctypes.c_uint32, ctypes.c_uint64],
            ctypes.c_uint64,
            config.APP_ID,
            self.item_id,
        )
        if handle in {0, 2**64 - 1}:
            raise WorkshopError("Steam 无法开始条目更新")
        return int(handle)

    def _set(self, method: str, handle: int, text: str) -> None:
        if not self._ugc(
            method, [ctypes.c_uint64, ctypes.c_char_p], ctypes.c_bool, handle, text.encode("utf-8")
        ):
            raise WorkshopError(f"Steam 更新参数被拒绝：{method}")

    def _submit(self, handle: int, note: str) -> dict[str, Any]:
        call = self._ugc(
            "SubmitItemUpdate",
            [ctypes.c_uint64, ctypes.c_char_p],
            ctypes.c_uint64,
            handle,
            note.encode("utf-8"),
        )
        result = UpdateCompleted()
        self._wait(call, result, 3404, 600, submitted=True)
        if result.legal:
            raise WorkshopError("Steam 要求账号在工坊页面接受法律协议；发布未完成", submitted=True)
        if result.result != 1 or result.item_id != self.item_id:
            raise WorkshopError(
                f"Steam 上传失败：result={result.result}，item={result.item_id}", submitted=True
            )
        return {"result": result.result, "item_id": result.item_id, "submitted": True}

    def upload(self, content: Path, changenote: str) -> dict[str, Any]:
        deployment.reject_links(content)
        thumbnail = content / distribution.THUMBNAIL_NAME
        if not content.is_dir() or not thumbnail.is_file():
            raise WorkshopError("工坊上传目录或缩略图不存在")
        handle = self._start()
        self._set("SetItemContent", handle, str(content.resolve()))
        self._set("SetItemPreview", handle, str(thumbnail.resolve()))
        return self._submit(handle, changenote) | {
            "content_verified": "steam_callback",
            "remote_bytes_verified": False,
        }

    def describe(self, language: str, text: str) -> dict[str, Any]:
        body = validate_description(text)
        handle = self._start()
        self._set("SetItemUpdateLanguage", handle, language)
        self._set("SetItemDescription", handle, body)
        result = self._submit(handle, "")
        try:
            actual = self._query(language, 30)["description"]
            if normalized_description(actual) != body:
                raise WorkshopError(f"工坊正文读回不一致：{language}")
        except (ValueError, OSError) as exc:
            raise WorkshopError(
                f"上传后读回核对失败：{exc}", submitted=True, uncertain=True
            ) from exc
        return result | {"language": language, "readback_verified": True}


class SteamWorkshop:
    """主工具只传递 JSON；原生库、App 环境和 Steam 调试输出留在子进程。"""

    def __init__(self, item_id: int, run_dir: Path) -> None:
        self.item_id, self.run_dir = item_id, run_dir

    def _call(self, action: str, **arguments: Any) -> dict[str, Any]:
        response = self.run_dir / f"steam-{uuid.uuid4().hex}.json"
        request = {"action": action, "item_id": self.item_id, **arguments}
        environment = {
            **os.environ,
            "SteamAppId": str(config.APP_ID),
            "SteamGameId": str(config.APP_ID),
        }
        writing = action != "inspect"
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-X",
                    "utf8",
                    "-m",
                    "pdx.steam_workshop",
                    str(response.resolve()),
                ],
                input=json.dumps(request, ensure_ascii=False),
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
                env=environment,
                timeout=680 if writing else 400,
            )
        except subprocess.TimeoutExpired as exc:
            raise WorkshopError(
                f"Steam 子进程超时；响应={response}", submitted=writing, uncertain=writing
            ) from exc
        try:
            result = json.loads(response.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise WorkshopError(
                f"Steam 子进程没有有效响应（退出码 {completed.returncode}）：{response}",
                submitted=writing,
                uncertain=writing,
            ) from exc
        if not isinstance(result, dict):
            raise WorkshopError(
                "Steam 子进程响应不是 JSON 对象", submitted=writing, uncertain=writing
            )
        if result.get("ok") is not True or completed.returncode:
            raise WorkshopError(
                str(result.get("error", "Steam 子进程失败")),
                submitted=bool(result.get("submitted", writing)),
                uncertain=bool(result.get("uncertain", writing)),
            )
        data = result.get("data")
        if not isinstance(data, dict):
            raise WorkshopError("Steam 子进程响应数据无效", submitted=writing, uncertain=writing)
        return data

    def inspect(self, languages: Sequence[str]) -> dict[str, Any]:
        return self._call("inspect", languages=list(languages))

    def upload(self, content: Path, changenote: str) -> dict[str, Any]:
        return self._call("upload", content=str(content.resolve()), changenote=changenote)

    def describe(self, language: str, text: str) -> dict[str, Any]:
        return self._call("describe", language=language, text=text)


def main() -> int:
    """内部 worker 协议；用户入口为 v3 publish。"""
    if len(sys.argv) != 2:
        raise ValueError("Steam worker 需要唯一响应文件路径")
    response = Path(sys.argv[1])
    try:
        request = json.load(sys.stdin)
        with NativeSteam(config.ROOT / "binaries/steam_api64.dll", request["item_id"]) as steam:
            action = request["action"]
            if action == "inspect":
                data = steam.inspect(request["languages"])
            elif action == "upload":
                data = steam.upload(Path(request["content"]), request["changenote"])
            elif action == "describe":
                data = steam.describe(request["language"], request["text"])
            else:
                raise ValueError("Steam worker 动作无效")
        write_receipt(response, {"ok": True, "data": data})
        return 0
    except (ValueError, OSError, KeyError) as exc:
        write_receipt(
            response,
            {
                "ok": False,
                "error": str(exc),
                "submitted": bool(getattr(exc, "submitted", False)),
                "uncertain": bool(getattr(exc, "uncertain", False)),
            },
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
