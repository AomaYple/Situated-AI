"""Resumable GitHub release operations using the authenticated gh CLI."""

from __future__ import annotations

import json
import os
import re
import subprocess
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlencode

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


class GitHubClient:
    def __init__(self, repo: str) -> None:
        self.repo = repo
        self.endpoint = f"repos/{repo}"

    def _run(
        self, arguments: list[str], payload: bytes | None
    ) -> subprocess.CompletedProcess[bytes]:
        env = {**os.environ, "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1"}
        return subprocess.run(
            ["gh", "api", "--hostname", "github.com", *arguments],
            input=payload,
            capture_output=True,
            check=False,
            timeout=180,
            env=env,
        )

    def _api(
        self,
        resource: str,
        *,
        method: str = "GET",
        data: Mapping[str, object] | bytes | None = None,
        binary: bool = False,
        optional: bool = False,
        paginate: bool = False,
        include_headers: bool = False,
        content_type: str | None = None,
    ) -> Any:
        endpoint = (
            resource
            if resource.startswith("https://uploads.github.com/")
            else f"{self.endpoint}/{resource}"
            if resource
            else self.endpoint
        )
        arguments = [endpoint]
        payload = None
        if data is not None:
            arguments.extend(("--method", method, "--input", "-"))
            if isinstance(data, bytes):
                payload = data
                media_type = content_type or "application/octet-stream"
            else:
                payload = json.dumps(dict(data), separators=(",", ":")).encode()
                media_type = "application/json; charset=utf-8"
            arguments.extend(
                (
                    "--header",
                    f"Content-Type: {media_type}",
                    "--header",
                    f"Content-Length: {len(payload)}",
                )
            )
        if binary:
            arguments.extend(("--header", "Accept: application/octet-stream"))
        if paginate:
            arguments.extend(("--paginate", "--slurp"))
        if include_headers:
            arguments.append("--include")
        try:
            result = self._run(arguments, payload)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"GitHub {method} timed out at {resource or 'repository'}") from exc
        if result.returncode:
            match = re.search(rb"\(HTTP ([0-9]{3})\)", result.stderr)
            status = match[1].decode() if match else "auth/transport"
            if optional and status == "404":
                return None
            raise RuntimeError(f"GitHub {method} failed at {resource or 'repository'} ({status})")
        raw = result.stdout
        if include_headers:
            headers, separator, body = raw.replace(b"\r\n", b"\n").partition(b"\n\n")
            if not separator or not headers.startswith(b"HTTP/"):
                raise ValueError("GitHub 鉴权响应格式不符")
            fields = {}
            for line in headers.splitlines()[1:]:
                name, _, value = line.partition(b":")
                fields[name.lower().decode("ascii")] = value.strip().decode("utf-8")
            return json.loads(body), fields
        return raw if binary else json.loads(raw)

    def _check_repository(self, commit: str) -> dict[str, object]:
        repository, headers = self._api("", include_headers=True)
        if (
            not isinstance(repository, dict)
            or str(repository.get("full_name", "")).casefold() != self.repo.casefold()
            or repository.get("visibility") != "public"
        ):
            raise ValueError("GitHub 公共仓库身份无法确认")
        permissions = repository.get("permissions")
        if not isinstance(permissions, dict) or permissions.get("push") is not True:
            raise ValueError("GitHub 帐号缺少仓库 push 角色")
        scopes_raw = headers.get("x-oauth-scopes")
        scopes = {part.strip() for part in scopes_raw.split(",")} if scopes_raw else set()
        if scopes_raw is not None and not scopes.intersection({"repo", "public_repo"}):
            raise ValueError("GitHub OAuth token 缺少 repo 或 public_repo scope")
        self._verify_main(self._api(f"compare/{commit}...main"))
        return {
            "repository_push_role": True,
            "token_write_scope": "oauth_scope_confirmed" if scopes else "unknown",
        }

    @staticmethod
    def _verify_main(comparison: object) -> None:
        if not isinstance(comparison, dict) or comparison.get("status") not in {
            "identical",
            "ahead",
        }:
            raise ValueError("GitHub main 历史不包含发布源提交")

    def check_public_source(self, commit: str) -> None:
        """Check the merged source for channels that need no GitHub credentials."""
        from urllib.request import urlopen  # noqa: PLC0415

        with urlopen(f"https://api.github.com/{self.endpoint}", timeout=30) as response:
            repository = json.load(response)
        if not isinstance(repository, dict) or repository.get("visibility") != "public":
            raise ValueError("GitHub 公共源仓库无法确认")
        if str(repository.get("full_name", "")).casefold() != self.repo.casefold():
            raise ValueError("GitHub 公共源仓库身份不符")
        with urlopen(
            f"https://api.github.com/{self.endpoint}/compare/{commit}...main?per_page=1", timeout=30
        ) as response:
            self._verify_main(json.load(response))

    def _tag_commit(self, tag: str) -> str | None:
        ref = self._api(f"git/ref/tags/{tag}", optional=True)
        if ref is None:
            return None
        if not isinstance(ref, dict) or ref.get("ref") != f"refs/tags/{tag}":
            raise ValueError("GitHub 标签引用回读身份不符")
        obj = ref.get("object")
        for _ in range(8):
            if not isinstance(obj, dict) or not re.fullmatch(r"[0-9a-f]{40}", str(obj.get("sha"))):
                break
            if obj.get("type") == "commit":
                return str(obj["sha"])
            if obj.get("type") != "tag":
                break
            annotation = self._api(f"git/tags/{obj['sha']}")
            obj = annotation.get("object") if isinstance(annotation, dict) else None
        raise ValueError("GitHub 标签无法解析至提交")

    def _release(self, tag: str) -> dict[str, Any] | None:
        # The listing includes drafts visible to a push-capable caller.
        pages = self._api("releases?per_page=100", paginate=True)
        if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
            raise ValueError("GitHub Release 列表格式不符")
        matches = [
            item
            for page in pages
            for item in page
            if isinstance(item, dict) and item.get("tag_name") == tag
        ]
        if len(matches) > 1:
            raise ValueError("发现多个使用同一标签的 GitHub Release")
        return matches[0] if matches else None

    def _verify_assets(
        self, release: Mapping[str, object], files: Mapping[str, bytes] | None
    ) -> set[str]:
        assets = release.get("assets")
        if not isinstance(assets, list):
            raise ValueError("GitHub Release 附件列表格式不符")
        names = set()
        for asset in assets:
            if not isinstance(asset, dict) or type(asset.get("id")) is not int:
                raise ValueError("GitHub Release 附件身份格式不符")
            name = asset.get("name")
            if not isinstance(name, str) or name in names:
                raise ValueError("GitHub Release 存在重复或未完成的附件")
            if asset.get("state") == "starter":
                raise ValueError(
                    f"GitHub Release {release['id']} 的附件 {asset['id']}（{name}）处于 starter 状态。"
                    "请核对未完成附件后在 GitHub 单独处理，再用原收据重试"
                )
            if asset.get("state") != "uploaded":
                raise ValueError(f"GitHub Release 附件状态不符：{name}")
            if files is not None:
                if name not in files:
                    raise ValueError(f"GitHub Release 已有其他附件：{name}")
                remote_bytes = self._api(f"releases/assets/{asset['id']}", binary=True)
                if remote_bytes != files[name]:
                    raise ValueError(f"GitHub Release 附件字节不同：{name}")
            names.add(name)
        return names

    def _upload(self, release_id: int, name: str, raw: bytes) -> None:
        query = urlencode({"name": name})
        self._api(
            f"https://uploads.github.com/{self.endpoint}/releases/{release_id}/assets?{query}",
            method="POST",
            data=raw,
            content_type="application/zip"
            if name.endswith(".zip")
            else "text/plain; charset=utf-8",
        )

    def inspect(
        self,
        tag: str,
        commit: str,
        files: Mapping[str, bytes] | None = None,
        *,
        owned_draft: str | None = None,
        previous: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        authority = self._check_repository(commit)
        tagged = self._tag_commit(tag)
        if tagged is not None and tagged != commit:
            raise ValueError("GitHub 已有标签指向其他提交，拒绝移动")
        release = self._release(tag)
        known_id = previous.get("release_id") if previous is not None else None
        if known_id is not None and type(known_id) is not int:
            raise ValueError("GitHub Release 收据 ID 格式不符")
        state: dict[str, object] = {
            "tag_commit": tagged,
            "release_id": None,
            "assets": [],
            "authority": authority,
        }
        if release is None:
            if known_id is not None:
                raise ValueError("已记录的 GitHub Release 已消失")
            return state
        release_id = release.get("id")
        if known_id is not None and release_id != known_id:
            raise ValueError("已记录的 GitHub Release ID 发生变化")
        draft = release.get("draft")
        if (
            type(release_id) is not int
            or type(draft) is not bool
            or release.get("prerelease") is not False
        ):
            raise ValueError("GitHub Release 身份或正式状态不符")
        if draft and (owned_draft is None or release.get("body") != owned_draft):
            raise ValueError("同一标签已有其他 GitHub Release 草稿，拒绝修改")
        if draft and release.get("target_commitish") != commit:
            raise ValueError("已记录的 GitHub Release 草稿源提交发生变化")
        if draft and previous and previous.get("status") == "verified":
            raise ValueError("已验证的 GitHub Release 变成草稿")
        if tagged is None:
            raise ValueError("GitHub Release 缺少对应提交标签")
        assets = self._verify_assets(release, files)
        if not draft and files is not None and assets != files.keys():
            raise ValueError("已公开的 GitHub Release 缺少预期附件")
        return {**state, "release_id": release_id, "draft": draft, "assets": sorted(assets)}

    def publish(
        self,
        *,
        tag: str,
        commit: str,
        files: Mapping[str, bytes],
        draft_body: str,
        checkpoint: Callable[[Mapping[str, object]], None],
        previous: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        state = self.inspect(tag, commit, files, owned_draft=draft_body, previous=previous)
        if state.get("draft") is False:
            return {**state, "status": "verified", "tag": tag}
        if state["tag_commit"] is None:
            checkpoint({"status": "creating_tag", "tag": tag, "commit": commit})
            self._api("git/refs", method="POST", data={"ref": f"refs/tags/{tag}", "sha": commit})
            if self._tag_commit(tag) != commit:
                raise ValueError("新建 GitHub 标签的回读提交不符")
            checkpoint({"status": "tag_verified", "tag": tag, "commit": commit})
        release_id = state["release_id"]
        if release_id is None:
            checkpoint({"status": "creating_draft"})
            created = self._api(
                "releases",
                method="POST",
                data={
                    "tag_name": tag,
                    "target_commitish": commit,
                    "name": f"Situated AI {tag.removeprefix('v')}",
                    "body": draft_body,
                    "draft": True,
                    "prerelease": False,
                },
            )
            if not isinstance(created, dict) or type(created.get("id")) is not int:
                raise ValueError("GitHub 创建草稿响应缺少 Release ID")
            previous = {"status": "draft_created", "release_id": created["id"]}
            checkpoint(previous)
            state = self.inspect(tag, commit, files, owned_draft=draft_body, previous=previous)
            release_id = state["release_id"]
        if type(release_id) is not int or state.get("draft") is not True:
            raise ValueError("GitHub Release 草稿回读失败")
        checkpoint({"status": "draft_verified", "release_id": release_id})
        uploaded = cast("list[str]", state["assets"])
        for name, raw in files.items():
            if name not in uploaded:
                checkpoint({"status": "uploading_asset", "release_id": release_id, "asset": name})
                self._upload(release_id, name, raw)
        expected_release = {"release_id": release_id}
        state = self.inspect(tag, commit, files, owned_draft=draft_body, previous=expected_release)
        if (
            state.get("release_id") != release_id
            or set(cast("list[str]", state["assets"])) != files.keys()
        ):
            raise ValueError("正式发布前的 GitHub Release 附件回读失败")
        if state.get("draft") is True:
            checkpoint({"status": "publishing_draft", "release_id": release_id})
            self._api(f"releases/{release_id}", method="PATCH", data={"draft": False})
        final = self.inspect(tag, commit, files, owned_draft=draft_body, previous=expected_release)
        if final.get("release_id") != release_id or final.get("draft") is not False:
            raise ValueError("GitHub 正式发布和附件回读失败")
        return {
            **final,
            "status": "verified",
            "tag": tag,
            "url": f"https://github.com/{self.repo}/releases/tag/{tag}",
        }
