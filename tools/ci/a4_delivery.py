"""Fail-closed, read-only A4-8 delivery verification primitives.

The verifier accepts injected transports so its identity and byte checks can be
tested without contacting GitHub or Steam.  A fixture report is deliberately
marked offline and can never be used as the final A4-8/all result.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import stat
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Never

from pdx import config, deployment, distribution
from pdx.publishing_contract import (
    load_descriptions,
    normalized_description,
    publication_config,
    validate_description,
)
from pdx.steam_workshop import SteamWorkshop

SCHEMA = 1
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
VERSION = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
MAX_ASSET_BYTES = 64 * 1024 * 1024
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_ZIP_ENTRIES = 4096
MAX_ZIP_UNCOMPRESSED = 256 * 1024 * 1024
FOLLOWUP_PREFIX = "docs/design/exec/A4-delivery/"

REQUEST_KEYS = {
    "schema",
    "mode",
    "repository",
    "pull_request",
    "base",
    "head_sha",
    "merge_sha",
    "main_sha",
    "tag",
    "version",
    "asset_name",
    "checksum_name",
    "run_dir",
    "userdir",
    "local_target",
    "lock_paths",
    "cleanup_paths",
    "expected_languages",
    "descriptions",
    "production_snapshot",
    "recovery",
    "cleanup",
    "allowed_followup_paths",
}


class DeliveryError(ValueError):
    """A delivery identity or byte contract failed."""


def _fail(message: str) -> Never:
    raise DeliveryError(message)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{field} must be nonempty text")
    return value


def _sha(value: Any, field: str, *, length: int = 64) -> str:
    if not isinstance(value, str) or len(value) != length or value != value.casefold():
        _fail(f"{field} is not a lowercase hexadecimal hash")
    pattern = HEX64 if length == 64 else SHA40
    if not pattern.fullmatch(value):
        _fail(f"{field} is not a lowercase hexadecimal hash")
    return value


def _safe_rel(value: Any, field: str) -> str:
    text = _text(value, field)
    value = text
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or "\\" in value
        or ":" in value
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != value
        or any(ord(char) < 32 for char in value)
    ):
        _fail(f"{field} is not a safe relative path")
    return text


def validate_request(request: Any) -> dict[str, Any]:
    """Validate the strict sidecar shape; semantic identity is checked later."""
    if not isinstance(request, dict) or set(request) != REQUEST_KEYS:
        _fail(f"delivery request fields: expected {sorted(REQUEST_KEYS)}")
    if type(request["schema"]) is not int or request["schema"] != SCHEMA:
        _fail("unsupported delivery schema")
    if request["mode"] not in {"offline_fixture", "live"}:
        _fail("delivery mode must be offline_fixture or live")
    repository = _text(request["repository"], "repository")
    if not REPOSITORY.fullmatch(repository):
        _fail("repository must be owner/name")
    if type(request["pull_request"]) is not int or request["pull_request"] <= 0:
        _fail("pull_request must be a positive integer")
    if request["base"] != "main":
        _fail("delivery PR must target main")
    for field in ("head_sha", "merge_sha", "main_sha"):
        _sha(request[field], field, length=40)
    tag = _text(request["tag"], "tag")
    version = _text(request["version"], "version")
    if not VERSION.fullmatch(tag) or tag != version:
        _fail("tag/version must be the same strict vMAJOR.MINOR.PATCH")
    _safe_rel(request["run_dir"], "run_dir")
    if not isinstance(request["userdir"], str) or not Path(request["userdir"]).is_absolute():
        _fail("userdir must be absolute")
    if (
        not isinstance(request["local_target"], str)
        or not Path(request["local_target"]).is_absolute()
    ):
        _fail("local_target must be absolute")
    for field in ("asset_name", "checksum_name"):
        _safe_rel(request[field], field)
        if "/" in request[field]:
            _fail(f"{field} must be a basename")
    if (
        request["asset_name"] != f"situated-ai-{tag[1:]}.zip"
        or request["checksum_name"] != request["asset_name"] + ".sha256"
    ):
        _fail("asset names do not match the standard version")
    for field in ("lock_paths", "cleanup_paths", "allowed_followup_paths"):
        if not isinstance(request[field], list) or any(
            not isinstance(item, str) for item in request[field]
        ):
            _fail(f"{field} must be a list of text")
        if len(set(request[field])) != len(request[field]):
            _fail(f"{field} contains duplicates")
    if any(
        not Path(path).is_absolute() for path in [*request["lock_paths"], *request["cleanup_paths"]]
    ):
        _fail("lock and cleanup paths must be absolute")
    languages = request["expected_languages"]
    if (
        not isinstance(languages, list)
        or not languages
        or any(not isinstance(language, str) or not language for language in languages)
        or len(set(languages)) != len(languages)
    ):
        _fail("expected_languages must be a nonempty unique list")
    descriptions = request["descriptions"]
    if not isinstance(descriptions, dict) or set(descriptions) != set(languages):
        _fail("description language set does not match expected_languages")
    for language, body in descriptions.items():
        if not isinstance(language, str) or not isinstance(body, str):
            _fail("descriptions must map text language keys to text bodies")
        validate_description(body)
    snapshot = request["production_snapshot"]
    if not isinstance(snapshot, dict) or not snapshot:
        _fail("production_snapshot must be a nonempty path/hash map")
    for path, digest in snapshot.items():
        _safe_rel(path, "production_snapshot path")
        _sha(digest, f"production_snapshot[{path}]")
    for path in request["allowed_followup_paths"]:
        _safe_rel(path, "allowed_followup_paths item")
        if not path.startswith(FOLLOWUP_PREFIX) or not path.endswith((".json", ".md")):
            _fail("follow-up changes must name exact A4-delivery receipt documents")
    for field in ("recovery", "cleanup"):
        reference = request[field]
        if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
            _fail(f"{field} must be a path/hash reference")
        _safe_rel(reference["path"], f"{field}.path")
        _sha(reference["sha256"], f"{field}.sha256")
    return request


def strict_json(raw: bytes) -> Any:
    """Reject duplicate keys and nonfinite JSON rather than silently choosing one."""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                _fail("duplicate JSON key")
            value[key] = item
        return value

    def invalid(_value: str) -> Any:
        _fail("nonfinite JSON number")

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DeliveryError("invalid UTF-8 JSON") from exc


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{label} is not an object")
    return value


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, _req: Any, _fp: Any, _code: int, _msg: str, _headers: Any, _newurl: str
    ) -> None:
        return None


class GitHubReader:
    """Bounded GET-only GitHub reader; credentials stay in memory."""

    live = True

    def __init__(self, repository: str, *, credential: str | None = None) -> None:
        if not REPOSITORY.fullmatch(repository):
            raise DeliveryError("invalid configured repository")
        self.repository = repository
        self.credential = credential
        self._assets: dict[int, str] = {}

    @classmethod
    def from_git(cls, root: Path) -> GitHubReader:
        repository = GitReader(root).remote_repository()
        try:
            result = subprocess.run(
                ["git", "credential", "fill"],
                cwd=root,
                input="protocol=https\nhost=github.com\n\n",
                text=True,
                capture_output=True,
                timeout=25,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise DeliveryError("GitHub credential helper failed") from None
        if result.returncode:
            raise DeliveryError("GitHub credential helper unavailable")
        credentials = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        token = credentials.get("password")
        if not token:
            raise DeliveryError("GitHub credential unavailable")
        return cls(repository, credential=token)

    def check_url(self, url: str, *, asset: bool) -> str:
        parsed = urllib.parse.urlsplit(url)
        hosts = (
            {
                "api.github.com",
                "release-assets.githubusercontent.com",
                "objects.githubusercontent.com",
            }
            if asset
            else {"api.github.com"}
        )
        try:
            port = parsed.port
        except ValueError:
            raise DeliveryError("invalid GitHub URL port") from None
        if parsed.scheme != "https" or parsed.hostname not in hosts or port not in {None, 443}:
            raise DeliveryError("GitHub route must use an allowed HTTPS host")
        if (
            parsed.username
            or parsed.password
            or parsed.fragment
            or any(ord(char) < 33 for char in url)
        ):
            raise DeliveryError("GitHub route contains unsafe credentials or query")
        prefix = f"/repos/{self.repository}/"
        path = urllib.parse.unquote(parsed.path)
        if "\\" in path or any(part in {".", ".."} for part in path.split("/")) or "%" in path:
            raise DeliveryError("noncanonical GitHub route")
        if parsed.hostname == "api.github.com" and not (
            path == prefix.rstrip("/") or path.startswith(prefix)
        ):
            raise DeliveryError("GitHub route escaped configured repository")
        if parsed.hostname == "api.github.com":
            query = urllib.parse.parse_qs(parsed.query, strict_parsing=True)
            if set(query) - {"page", "per_page", "filter"}:
                raise DeliveryError("unsupported GitHub query")
            if any(len(values) != 1 for values in query.values()):
                raise DeliveryError("duplicate GitHub query")
            for key in {"page", "per_page"} & query.keys():
                if not query[key][0].isdigit() or not 1 <= int(query[key][0]) <= 100:
                    raise DeliveryError("GitHub pagination exceeds bound")
            if "filter" in query and query["filter"] != ["latest"]:
                raise DeliveryError("unsupported GitHub check filter")
        elif not asset or not path.startswith("/github-production-release-asset/"):
            raise DeliveryError("unsupported GitHub asset download path")
        return urllib.parse.urlunsplit(parsed)

    def _read(self, url: str, *, asset: bool, limit: int) -> bytes:
        opener = urllib.request.build_opener(_NoRedirect())
        deadline = time.monotonic() + 120
        for _hop in range(5):
            url = self.check_url(url, asset=asset)
            headers = {
                "Accept": "application/octet-stream" if asset else "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            if self.credential and urllib.parse.urlsplit(url).hostname == "api.github.com":
                headers["Authorization"] = f"Bearer {self.credential}"
            request = urllib.request.Request(url, headers=headers, method="GET")
            try:
                with opener.open(request, timeout=30) as response:
                    chunks: list[bytes] = []
                    total = 0
                    while True:
                        if time.monotonic() > deadline:
                            _fail("GitHub download exceeded time bound")
                        chunk = response.read(min(65536, limit + 1 - total))
                        if not chunk:
                            return b"".join(chunks)
                        total += len(chunk)
                        if total > limit:
                            _fail("GitHub response exceeds configured bound")
                        chunks.append(chunk)
            except urllib.error.HTTPError as exc:
                if exc.code in {301, 302, 303, 307, 308} and asset:
                    location = exc.headers.get("Location")
                    exc.close()
                    if not location:
                        _fail("GitHub redirect has no location")
                    url = urllib.parse.urljoin(url, location)
                    continue
                exc.close()
                raise DeliveryError("GitHub read failed") from None
            except (urllib.error.URLError, TimeoutError, OSError):
                raise DeliveryError("GitHub read failed") from None
        raise DeliveryError("GitHub redirect limit exceeded")

    def get_json(self, route: str) -> Any:
        url = (
            route
            if route.startswith("https://")
            else f"https://api.github.com/repos/{self.repository}/{route.lstrip('/')}"
        )
        return strict_json(self._read(url, asset=False, limit=MAX_JSON_BYTES))

    def get_bytes(self, url: str) -> bytes:
        return self._read(url, asset=True, limit=MAX_ASSET_BYTES)

    def _pages(self, route: str, key: str | None = None) -> list[Any]:
        rows: list[Any] = []
        for page in range(1, 101):
            separator = "&" if "?" in route else "?"
            response = self.get_json(f"{route}{separator}per_page=100&page={page}")
            values = response.get(key) if key and isinstance(response, dict) else response
            if not isinstance(values, list):
                _fail("GitHub paginated response is malformed")
            rows.extend(values)
            if len(values) < 100:
                return rows
        _fail("GitHub pagination limit exceeded")
        return []

    def get(self, route: str) -> Any:
        """Resolve only the verifier's fixed semantic read routes."""
        if route == "repository":
            return self.get_json("")
        if route == "main":
            return self.get_json("branches/main")
        if route == "protection":
            return self.get_json("branches/main/protection")
        if route == "rules":
            return self._pages("rules/branches/main")
        kind, _, value = route.partition(":")
        if kind == "pr" and value.isdigit():
            return self.get_json(f"pulls/{value}")
        if kind == "checks" and SHA40.fullmatch(value):
            return self._pages(f"commits/{value}/check-runs?filter=latest", "check_runs")
        if kind == "tag" and VERSION.fullmatch(value):
            return self.get_json(f"git/ref/tags/{value}")
        if kind == "tag_object" and SHA40.fullmatch(value):
            return self.get_json(f"git/tags/{value}")
        if kind == "release" and VERSION.fullmatch(value):
            release = _object(self.get_json(f"releases/tags/{value}"), "release")
            release_id = release.get("id")
            if type(release_id) is not int or release_id <= 0:
                _fail("release id missing")
            assets = self._pages(f"releases/{release_id}/assets")
            release["assets"] = assets
            for item in assets:
                asset = _object(item, "asset")
                asset_id = asset.get("id")
                if type(asset_id) is not int or asset_id <= 0:
                    _fail("asset id missing")
                expected = (
                    f"https://api.github.com/repos/{self.repository}/releases/assets/{asset_id}"
                )
                if asset.get("url") != expected:
                    _fail("asset API identity mismatch")
                self._assets[asset_id] = expected
            return release
        if kind == "asset" and value.isdigit() and int(value) in self._assets:
            return self.get_bytes(self._assets[int(value)])
        _fail("unsupported GitHub read route")


def _get(transport: Any, route: str) -> Any:
    if hasattr(transport, "get"):
        value = transport.get(route)
    elif isinstance(transport, Mapping):
        value = transport[route]
    else:
        _fail("transport does not provide read-only get")
    if value is None:
        _fail(f"missing live evidence: {route}")
    return value


def _require_hashes(actual: Mapping[str, str], expected: Mapping[str, str], label: str) -> None:
    if dict(actual) != dict(expected):
        _fail(f"{label} snapshot identity mismatch")


class GitReader:
    """Read local immutable Git objects and compare the controlled worktree."""

    live = True

    def __init__(self, root: Path, *, remote: str = "origin") -> None:
        self.root = root.resolve()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", remote):
            _fail("unsafe remote name")
        self.remote = remote

    def _run(self, *arguments: str) -> bytes:
        try:
            result = subprocess.run(
                ["git", *arguments], cwd=self.root, capture_output=True, timeout=30, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            raise DeliveryError("local Git read failed") from None
        if result.returncode:
            raise DeliveryError("local Git object unavailable; fetch through controller")
        return result.stdout

    def remote_repository(self) -> str:
        remote = self._run("remote", "get-url", self.remote).decode("utf-8").strip()
        match = re.fullmatch(
            r"(?:https://github\.com/|git@github\.com:)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?",
            remote,
        )
        if not match or not REPOSITORY.fullmatch(match[1]):
            _fail("configured Git remote is not a supported GitHub repository")
        return match[1]

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        _sha(ancestor, "ancestor", length=40)
        _sha(descendant, "descendant", length=40)
        # rev-list reads only; no fetch, index refresh, checkout or ref mutation.
        parents = self._run("rev-list", "--ancestry-path", f"{ancestor}..{descendant}").splitlines()
        if ancestor == descendant:
            return True
        if not parents:
            return False
        bases = self._run("merge-base", ancestor, descendant).decode().strip()
        return bases == ancestor

    def tree(self, commit: str) -> dict[str, tuple[str, str]]:
        _sha(commit, "commit", length=40)
        entries = self._run("ls-tree", "-r", "-z", commit).split(b"\0")
        result: dict[str, tuple[str, str]] = {}
        for entry in entries:
            if not entry:
                continue
            header, name = entry.split(b"\t", 1)
            mode, kind, object_id = header.decode("ascii").split()
            path = name.decode("utf-8")
            _safe_rel(path, "Git tree path")
            if kind != "blob" or mode not in {"100644", "100755"}:
                _fail("Git tree contains linked or unsupported object")
            result[path] = (mode, object_id)
        return result

    @staticmethod
    def production_path(path: str) -> bool:
        parent = PurePosixPath(path).parent.as_posix()
        baseline = parent in {"research/vanilla-ai/1.15.0", "research/situated"} and path.endswith(
            (".txt", ".json")
        )
        return (
            path.startswith(("src/pdx/", "mod/", "docs/publishing/"))
            or baseline
            or path in {"pyproject.toml", "requirements.lock"}
        )

    def snapshot(self, commit: str) -> Mapping[str, str]:
        tree = self.tree(commit)
        return {
            path: hashlib.sha256(self._run("cat-file", "blob", object_id)).hexdigest()
            for path, (_mode, object_id) in tree.items()
            if self.production_path(path)
        }

    def verify_current(
        self, merge: str, expected: Mapping[str, str], *, main: str, followup_paths: list[str]
    ) -> None:
        head = self._run("rev-parse", "HEAD").decode().strip()
        if head != main:
            _fail("current HEAD is not live remote main")
        released, current = self.tree(merge), self.tree(head)
        changed = {
            path
            for path in released.keys() | current.keys()
            if released.get(path) != current.get(path)
        }
        if changed - set(followup_paths):
            _fail("follow-up commit includes changes outside exact delivery receipts")
        _require_hashes(self.snapshot(head), expected, "current committed production")
        actual: dict[str, str] = {}
        for path in current:
            if self.production_path(path):
                item = self.root / path
                deployment.reject_links(item)
                actual[path] = hashlib.sha256(item.read_bytes()).hexdigest()
        for directory in (
            "src/pdx",
            "mod",
            "docs/publishing",
            "research/vanilla-ai/1.15.0",
            "research/situated",
        ):
            for item in (self.root / directory).rglob("*"):
                if (
                    item.is_file()
                    and item.suffix not in {".pyc", ".pyo"}
                    and "__pycache__" not in item.parts
                ):
                    path = item.relative_to(self.root).as_posix()
                    if not self.production_path(path):
                        continue
                    deployment.reject_links(item)
                    if path not in current:
                        _fail(f"untracked production input: {path}")
        _require_hashes(actual, expected, "current worktree production")


class WorkshopReader:
    """Expose only the existing standard publisher's read-only inspection API."""

    live = True

    def __init__(self, item_id: int, output: Path) -> None:
        deployment.reject_links(output)
        if not output.is_dir() or not output.resolve().is_relative_to(config.OUT.resolve()):
            _fail("Steam inspection output must be an existing directory below tools/out")
        self.gateway = SteamWorkshop(item_id, output)

    def inspect(self, languages: list[str]) -> Mapping[str, Any]:
        return self.gateway.inspect(languages)


def _verify_github(request: Mapping[str, Any], github: Any) -> dict[str, Any]:
    repo = _get(github, "repository")
    if (
        not isinstance(repo, dict)
        or type(repo.get("id")) is not int
        or repo.get("full_name") != request["repository"]
        or repo.get("default_branch") != "main"
    ):
        _fail("GitHub repository identity mismatch")
    pr = _get(github, f"pr:{request['pull_request']}")
    if (
        not isinstance(pr, dict)
        or pr.get("number") != request["pull_request"]
        or pr.get("base", {}).get("ref") != "main"
    ):
        _fail("PR base is not main")
    if pr.get("base", {}).get("repo", {}).get("full_name") != request["repository"]:
        _fail("PR base repository mismatch")
    if pr["base"]["repo"].get("id") != repo["id"]:
        _fail("PR repository numeric identity mismatch")
    if (
        pr.get("head", {}).get("sha") != request["head_sha"]
        or pr.get("merged") is not True
        or not pr.get("merged_at")
    ):
        _fail("PR head or merged identity mismatch")
    if pr.get("merge_commit_sha") != request["merge_sha"]:
        _fail("PR merge commit mismatch")
    main = _object(_get(github, "main"), "main")
    if main.get("commit", {}).get("sha") != request["main_sha"]:
        _fail("live main identity differs from expected main")
    protection = _get(github, "protection")
    checks = (
        protection.get("required_status_checks", {}).get("checks")
        if isinstance(protection, dict)
        else None
    )
    if not isinstance(checks, list) or not checks:
        _fail("required check contract is missing or empty")
    rules = _get(github, "rules")
    if not isinstance(rules, list):
        _fail("active branch rules are unavailable")
    for rule in rules:
        if not isinstance(rule, dict):
            _fail("branch rule is malformed")
        if rule.get("type") == "required_status_checks":
            parameters = _object(rule.get("parameters"), "branch rule parameters")
            additional = parameters.get("required_status_checks")
            if not isinstance(additional, list) or not additional:
                _fail("branch rule required checks are empty")
            if any(not isinstance(row, dict) for row in additional):
                _fail("branch rule required check member is malformed")
            checks = [
                *checks,
                *(
                    {"context": row.get("context"), "app_id": row.get("integration_id")}
                    for row in additional
                ),
            ]
        else:
            # No other branch rule is treated as irrelevant to delivery. Add a
            # rule only with an explicit proof strategy, never a default skip.
            _fail("unsupported or missing branch rule type must be independently verified")
    if any(not isinstance(row, dict) for row in checks) or any(
        not isinstance(row.get("context"), str)
        or not row["context"]
        or type(row.get("app_id")) is not int
        or row["app_id"] <= 0
        for row in checks
    ):
        _fail("required check contract is malformed")
    required = {(row["context"], row["app_id"]) for row in checks}
    for sha in {request["head_sha"], request["merge_sha"]}:
        runs = _get(github, f"checks:{sha}")
        if not isinstance(runs, list) or any(not isinstance(row, dict) for row in runs):
            _fail("check run response is malformed")
        for context, app_id in required:
            matches = [
                row
                for row in runs
                if row.get("name") == context and row.get("app", {}).get("id") == app_id
            ]
            if (
                len(matches) != 1
                or matches[0].get("head_sha") != sha
                or matches[0].get("status") != "completed"
                or matches[0].get("conclusion") != "success"
            ):
                _fail(f"required check is not successful: {context}@{sha}")
    tag = _get(github, f"tag:{request['tag']}")
    if not isinstance(tag, dict):
        _fail("tag response is malformed")
    target = tag.get("object", {})
    seen: set[str] = set()
    for _ in range(5):
        target = _object(target, "tag object")
        if target.get("type") != "tag":
            break
        sha = _sha(target.get("sha"), "annotated tag object", length=40)
        if sha in seen:
            _fail("annotated tag cycle")
        seen.add(sha)
        annotated = _object(_get(github, f"tag_object:{sha}"), "annotated tag")
        target = annotated.get("object")
    if target.get("type") != "commit" or target.get("sha") != request["merge_sha"]:
        _fail("tag target does not equal merged commit")
    release = _get(github, f"release:{request['tag']}")
    if (
        not isinstance(release, dict)
        or type(release.get("id")) is not int
        or release.get("tag_name") != request["tag"]
        or release.get("draft") is not False
        or release.get("prerelease") is not False
    ):
        _fail("release is missing, draft, prerelease, or tag-mismatched")
    assets = release.get("assets")
    if not isinstance(assets, list) or any(not isinstance(row, dict) for row in assets):
        _fail("release assets are malformed")
    selected = []
    for field in ("asset_name", "checksum_name"):
        matches = [row for row in assets if row.get("name") == request[field]]
        if (
            len(matches) != 1
            or type(matches[0].get("id")) is not int
            or matches[0].get("state") != "uploaded"
        ):
            _fail("release asset exact identity missing or duplicated")
        size = matches[0].get("size")
        if type(size) is not int or not 0 < size <= MAX_ASSET_BYTES:
            _fail("release asset size is invalid")
        raw = _get(github, f"asset:{matches[0]['id']}")
        if not isinstance(raw, bytes) or len(raw) != size:
            _fail("release asset downloaded byte count mismatch")
        selected.append(raw)
    zip_bytes, checksum_bytes = selected
    if not isinstance(zip_bytes, bytes) or not isinstance(checksum_bytes, bytes):
        _fail("release asset transport did not return bytes")
    return {
        "zip": zip_bytes,
        "checksum": checksum_bytes,
        "merge_sha": request["merge_sha"],
        "main": main,
        "tag": tag,
    }


def _verify_checksum(zip_bytes: bytes, checksum_bytes: bytes, asset_name: str) -> str:
    digest = hashlib.sha256(zip_bytes).hexdigest()
    try:
        line = checksum_bytes.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise DeliveryError("checksum is not UTF-8") from exc
    fields = line.split()
    if (
        len(fields) != 2
        or fields[1] != asset_name
        or not HEX64.fullmatch(fields[0])
        or fields[0] != digest
    ):
        _fail("checksum syntax, filename, or digest mismatch")
    return digest


def _zip_payload(zip_bytes: bytes) -> tuple[dict[str, bytes], dict[str, Any]]:
    if len(zip_bytes) > MAX_ASSET_BYTES:
        _fail("ZIP exceeds download bound")
    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except (OSError, zipfile.BadZipFile) as exc:
        raise DeliveryError("release asset is not a valid ZIP") from exc
    with archive:
        if archive.comment:
            _fail("ZIP archive comment differs from deterministic standard archive")
        infos = archive.infolist()
        if not infos or len(infos) > MAX_ZIP_ENTRIES:
            _fail("ZIP entry count or CRC is invalid")
        total = 0
        names = [info.filename for info in infos]
        if names != sorted(names):
            _fail("ZIP entry order is not the deterministic standard order")
        try:
            distribution._validate_paths(names)
        except ValueError as exc:
            raise DeliveryError(str(exc)) from exc
        for info in infos:
            mode = info.external_attr >> 16
            if (
                info.flag_bits & 0x1
                or info.is_dir()
                or (stat.S_IFMT(mode) not in {0, stat.S_IFREG})
            ):
                _fail("ZIP contains encrypted or special entry")
            if (
                info.date_time != (1980, 1, 1, 0, 0, 0)
                or info.create_system != 3
                or mode != 0o100644
                or info.compress_type != zipfile.ZIP_DEFLATED
                or info.extra
                or info.comment
            ):
                _fail("ZIP metadata differs from deterministic standard archive")
            total += info.file_size
            if total > MAX_ZIP_UNCOMPRESSED:
                _fail("ZIP expanded size exceeds bound")
        try:
            data = {info.filename: archive.read(info.filename) for info in infos}
        except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
            raise DeliveryError("ZIP entry bytes/CRC are invalid") from None
    if distribution.MANIFEST_NAME not in data:
        _fail("ZIP manifest is missing")
    try:
        manifest = strict_json(data[distribution.MANIFEST_NAME])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeliveryError("ZIP manifest is invalid JSON") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != 2
        or manifest.get("mod_id") != distribution.MOD_ID
    ):
        _fail("ZIP manifest identity is invalid")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(data) - {distribution.MANIFEST_NAME}:
        _fail("ZIP manifest file set mismatch")
    for name, digest in files.items():
        if (
            not isinstance(digest, str)
            or not HEX64.fullmatch(digest)
            or hashlib.sha256(data[name]).hexdigest() != digest
        ):
            _fail(f"ZIP manifest hash mismatch: {name}")
    return data, manifest


def _verify_receipt(
    root: Path, request: Mapping[str, Any], zip_digest: str, manifest: Mapping[str, Any]
) -> dict[str, Any]:
    run = (root / request["run_dir"]).resolve()
    deployment.reject_links(root / request["run_dir"])
    if not run.is_relative_to((root / "tools/out").resolve()) or not run.is_dir():
        _fail("publication run directory is unavailable or linked")
    receipt_path = run / "receipt.json"
    try:
        deployment.reject_links(receipt_path)
        receipt = strict_json(receipt_path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DeliveryError("publication receipt is unreadable") from exc
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema") != 1
        or receipt.get("status") != "succeeded"
        or receipt.get("execute") is not True
        or receipt.get("target") != "all"
        or receipt.get("evidence") != "publication_operation"
        or receipt.get("behavior_quality") != "not_evaluated"
    ):
        _fail("publication receipt is not a successful execution")
    if receipt.get("receipt") != str(receipt_path):
        _fail("publication receipt path identity mismatch")
    try:
        started = datetime.fromisoformat(receipt["started_at"])
        finished = datetime.fromisoformat(receipt["finished_at"])
        if started.utcoffset() is None or finished.utcoffset() is None or finished < started:
            _fail("publication operation time order/zone invalid")
    except (KeyError, ValueError, TypeError):
        raise DeliveryError("publication operation time fields invalid") from None
    package = receipt.get("package")
    if (
        not isinstance(package, dict)
        or package.get("sha256") != zip_digest
        or package.get("manifest") != manifest
    ):
        _fail("publication receipt package identity mismatch")
    operations = receipt.get("operations")
    if not isinstance(operations, list) or any(
        not isinstance(row, dict) or row.get("status") not in {"succeeded", "unchanged"}
        for row in operations
    ):
        _fail("publication receipt contains failed or incomplete operation")
    names = [row.get("name") for row in operations]
    expected_names = {
        "local",
        "workshop",
        *(f"description:{language}" for language in request["expected_languages"]),
    }
    if len(names) != len(set(names)) or set(names) != expected_names:
        _fail("publication operation set is missing, extra, or duplicated")
    indexed = {row["name"]: row for row in operations}
    local = indexed["local"]
    if (
        local["status"] != "succeeded"
        or local.get("result", {}).get("status") not in {"succeeded", "unchanged"}
        or local["result"].get("target") != request["local_target"]
    ):
        _fail("local publication result identity invalid")
    workshop = indexed["workshop"]
    callback = workshop.get("result", {})
    item = publication_config(root / "docs/publishing")["published_file_id"]
    if (
        workshop["status"] != "succeeded"
        or callback.get("result") != 1
        or callback.get("item_id") != item
        or callback.get("submitted") is not True
        or callback.get("content_verified") != "steam_callback"
        or callback.get("remote_bytes_verified") is not False
    ):
        _fail("workshop content callback is not verified")
    descriptions = receipt.get("descriptions")
    expected_descriptions = {
        language: {
            "sha256": hashlib.sha256(body.encode()).hexdigest(),
            "utf8_bytes": len(body.encode()),
        }
        for language, body in request["descriptions"].items()
    }
    if descriptions != expected_descriptions:
        _fail("publication description source identity mismatch")
    for language in request["expected_languages"]:
        operation = indexed[f"description:{language}"]
        if operation["status"] == "succeeded":
            result = operation.get("result", {})
            if (
                result.get("result") != 1
                or result.get("item_id") != item
                or result.get("language") != language
                or result.get("readback_verified") is not True
            ):
                _fail("description publication result invalid")
    frozen = run / "package.zip"
    deployment.reject_links(frozen)
    if frozen.stat().st_size > MAX_ASSET_BYTES:
        _fail("fixed publication archive exceeds size bound")
    if hashlib.sha256(frozen.read_bytes()).hexdigest() != zip_digest:
        _fail("fixed run archive differs from Release asset")
    if distribution.validate_package(frozen) != manifest:
        _fail("released ZIP differs from current standard package contract")
    if deployment.tree_hashes(run / "content") != package.get("files"):
        _fail("fixed publication content tree changed")
    return receipt


def _read_reference(root: Path, reference: Mapping[str, str]) -> Any:
    path = root / reference["path"]
    deployment.reject_links(path)
    if path.stat().st_size > MAX_JSON_BYTES:
        _fail("recovery/cleanup artifact exceeds size bound")
    raw = path.read_bytes()
    if len(raw) > MAX_JSON_BYTES or hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        _fail("recovery/cleanup artifact hash mismatch")
    return strict_json(raw)


def _verify_local(
    root: Path, request: Mapping[str, Any], data: Mapping[str, bytes], receipt: Mapping[str, Any]
) -> None:
    target = Path(request["local_target"])
    if not target.is_absolute() or not target.is_dir():
        _fail("local deployment target is unavailable")
    try:
        actual = deployment.tree_hashes(target)
    except (OSError, ValueError) as exc:
        raise DeliveryError(f"local deployment tree invalid: {exc}") from exc
    expected = {name: hashlib.sha256(raw).hexdigest() for name, raw in data.items()}
    if actual != expected:
        _fail("local deployment tree differs from released ZIP")
    if receipt["package"].get("files") != expected:
        _fail("receipt file map differs from released ZIP")
    userdir = Path(request["userdir"])
    deployment.reject_links(userdir)
    if target != userdir / "mod" / distribution.INSTALL_DIRECTORY_NAME:
        _fail("local target is not the standard install directory")
    deployment.assert_game_stopped()
    expected_locks = {
        str(userdir / name) for name in (".situated-ai-publish.lock", ".situated-ai-deploy.lock")
    }
    if set(request["lock_paths"]) != expected_locks:
        _fail("lock observation coverage mismatch")
    for lock in request["lock_paths"]:
        deployment.reject_links(Path(lock))
        if Path(lock).exists():
            _fail(f"publish/deploy lock remains: {lock}")
    for cleanup in request["cleanup_paths"]:
        deployment.reject_links(Path(cleanup))
        if Path(cleanup).exists():
            _fail(f"cleanup residue remains: {cleanup}")
    recovery = _object(_read_reference(root, request["recovery"]), "recovery")
    if (
        set(recovery) != {"schema", "target", "backup", "backup_files", "reason"}
        or recovery["schema"] != 1
        or recovery["target"] != str(target)
    ):
        _fail("recovery receipt contract mismatch")
    local = next(row for row in receipt["operations"] if row["name"] == "local")["result"]
    backup = local.get("backup")
    if recovery["backup"] != backup:
        _fail("backup reference mismatch")
    if backup is None:
        reason = "unchanged" if local["status"] == "unchanged" else "fresh_install"
        if recovery["reason"] != reason or recovery["backup_files"] != {}:
            _fail("missing backup has no supported recovery reason")
    else:
        backup_path = Path(backup)
        deployment.reject_links(backup_path)
        if not backup_path.is_absolute() or not backup_path.resolve().is_relative_to(
            (userdir / ".situated-ai-backups").resolve()
        ):
            _fail("backup is outside supported recovery directory")
        # Use the deployer's old-install identity contract; older valid Mod
        # versions need not match this release. The recovery map proves only
        # current backup bytes, not independently attested historical origin.
        deployment._identity(backup_path)
        if (
            deployment.tree_hashes(backup_path) != recovery["backup_files"]
            or not recovery["backup_files"]
            or recovery["reason"] != "preserved_backup"
        ):
            _fail("backup identity mismatch")
    cleanup = _object(_read_reference(root, request["cleanup"]), "cleanup")
    if (
        set(cleanup) != {"schema", "status", "absent", "remaining"}
        or cleanup["schema"] != 1
        or cleanup["status"] != "complete"
        or cleanup["remaining"] != []
        or cleanup["absent"] != request["cleanup_paths"]
    ):
        _fail("cleanup receipt is incomplete or mismatched")
    for path in (userdir / "mod").iterdir():
        if path == target:
            continue
        deployment.reject_links(path)
        lowered = path.name.casefold()
        if path.is_symlink() or any(
            word in lowered
            for word in (".sitai-stage-", "sitai-probe", "situated-ai-probe", "sitai-mount")
        ):
            _fail(f"task mount/probe remains in mod scan tree: {path.name}")


def verify_delivery(
    root: Path,
    request: Mapping[str, Any],
    *,
    github: Any,
    git: Any,
    workshop: Any,
    authorized_userdir: Path | None = None,
) -> dict[str, Any]:
    """Verify one immutable delivery chain without performing any write operation.

    The controller selects an alternate userdir independently of the sidecar;
    otherwise the configured game userdir is the only authorized target.
    """
    request = validate_request(dict(request))
    live = request["mode"] == "live"
    if live and (
        type(github) is not GitHubReader
        or type(git) is not GitReader
        or type(workshop) is not WorkshopReader
    ):
        _fail("live delivery requires supported live read-only transports")
    if live and root.resolve() != config.REPO.resolve():
        _fail("live package validation requires the configured repository root")
    if live and git.root.resolve() != root.resolve():
        _fail("live Git reader checkout differs from the package validation root")
    controlled_userdir = config.USERDIR if authorized_userdir is None else authorized_userdir
    if not controlled_userdir.is_absolute():
        _fail("authorized userdir must be absolute")
    deployment.reject_links(controlled_userdir)
    deployment.reject_links(Path(request["userdir"]))
    if Path(request["userdir"]).resolve() != controlled_userdir.resolve():
        _fail("sidecar userdir differs from the independently authorized userdir")
    if git.remote_repository() != request["repository"]:
        _fail("configured Git remote repository mismatch")
    if live and github.repository != request["repository"]:
        _fail("GitHub transport repository mismatch")
    descriptions = load_descriptions(root / "docs/publishing")
    if (
        live
        and workshop.gateway.item_id
        != publication_config(root / "docs/publishing")["published_file_id"]
    ):
        _fail("Steam inspection gateway item identity mismatch")
    if request["descriptions"] != descriptions or set(request["expected_languages"]) != set(
        descriptions
    ):
        _fail("language/source contract differs from current release materials")
    github_result = _verify_github(request, github)
    if not git.is_ancestor(request["head_sha"], request["merge_sha"]):
        _fail("supported delivery requires accepted PR head ancestry (merge commits only)")
    if not git.is_ancestor(request["merge_sha"], request["main_sha"]):
        _fail("release merge is not an ancestor of current main")
    snapshot = git.snapshot(request["merge_sha"])
    _require_hashes(snapshot, request["production_snapshot"], "production")
    git.verify_current(
        request["merge_sha"],
        request["production_snapshot"],
        main=request["main_sha"],
        followup_paths=request["allowed_followup_paths"],
    )
    digest = _verify_checksum(
        github_result["zip"], github_result["checksum"], request["asset_name"]
    )
    data, manifest = _zip_payload(github_result["zip"])
    metadata = _object(strict_json(data.get(distribution.METADATA_NAME, b"{}")), "package metadata")
    if (
        metadata.get("id") != distribution.MOD_ID
        or metadata.get("version") != request["tag"][1:]
        or request["tag"] != f"v{distribution.RELEASE_VERSION}"
    ):
        _fail("package and current release version identity mismatch")
    receipt = _verify_receipt(root, request, digest, manifest)
    _verify_local(root, request, data, receipt)
    observed = workshop.inspect(list(request["expected_languages"]))
    item = publication_config(root / "docs/publishing")["published_file_id"]
    if (
        observed.get("item_id") != item
        or observed.get("owner_matches") is not True
        or observed.get("creator_app_id") != config.APP_ID
        or observed.get("consumer_app_id") != config.APP_ID
    ):
        _fail("workshop live identity mismatch")
    if observed.get("remote_bytes_verified") is True:
        _fail("Steam content cannot claim subscription-side byte verification")
    if set(observed.get("descriptions", {})) != set(request["expected_languages"]):
        _fail("workshop language denominator mismatch")
    for language, expected in request["descriptions"].items():
        actual = observed["descriptions"].get(language)
        if not isinstance(actual, str) or normalized_description(actual) != normalized_description(
            expected
        ):
            _fail(f"workshop description readback mismatch: {language}")
    if (
        _get(github, "main") != github_result["main"]
        or _get(github, f"tag:{request['tag']}") != github_result["tag"]
    ):
        _fail("remote main/tag changed during verification")
    return {
        "schema": SCHEMA,
        "status": "verified",
        "mode": request["mode"],
        "delivery_complete": live,
        "evidence": "live" if live else "offline_fixture",
        "merge_sha": request["merge_sha"],
        "tag": request["tag"],
        "package_sha256": digest,
        "language_count": len(descriptions),
        "remote_bytes_verified": False,
        "receipt": receipt.get(
            "receipt", str((root / request["run_dir"] / "receipt.json").resolve())
        ),
    }


__all__ = ["DeliveryError", "GitHubReader", "validate_request", "verify_delivery"]
