"""固定标准包的单次发布编排；默认预览，显式执行才产生外部写入。"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pdx import config, deployment, distribution
from pdx.publishing_contract import (
    load_descriptions,
    normalized_description,
    publication_config,
    write_receipt,
)
from pdx.steam_workshop import SteamWorkshop, WorkshopError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

Target = Literal["all", "local", "workshop", "descriptions"]


class PublicationError(ValueError):
    """始终带上可定位的本次收据，CLI 不必猜测最近一次运行目录。"""

    def __init__(self, message: str, receipt: Path) -> None:
        super().__init__(message)
        self.receipt = receipt.resolve()


class WorkshopGateway(Protocol):
    def inspect(self, languages: Sequence[str]) -> dict[str, Any]: ...
    def upload(self, content: Path, changenote: str) -> dict[str, Any]: ...
    def describe(self, language: str, text: str) -> dict[str, Any]: ...


def _prepare_package(archive: Path, run: Path) -> tuple[Path, dict[str, Any]]:
    frozen = run / "package.zip"
    shutil.copyfile(archive, frozen)
    manifest = distribution.validate_package(frozen)
    content = run / "content"
    content.mkdir()
    with zipfile.ZipFile(frozen) as zipped:
        # validate_package 已核对 POSIX 路径、文件集合与字节；不依赖 extractall 的平台行为。
        for name in zipped.namelist():
            destination = content.joinpath(*name.split("/"))
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(zipped.read(name))
    return content, {
        "sha256": hashlib.sha256(frozen.read_bytes()).hexdigest(),
        "manifest": manifest,
        "files": deployment.tree_hashes(content),
    }


def publish(
    *,
    archive: Path = distribution.DEFAULT_PACKAGE_PATH,
    target: Target = "all",
    execute: bool = False,
    changenote: str = "",
    userdir: Path | None = None,
    run_dir: Path | None = None,
    workshop: WorkshopGateway | None = None,
) -> dict[str, Any]:
    """预检全部目标后依次执行；可用定向目标重试，描述只更新实际不同的语言。"""
    if target not in {"all", "local", "workshop", "descriptions"}:
        raise ValueError(f"发布目标无效：{target}")
    if "\x00" in changenote or len(changenote.encode("utf-8")) >= 8000:
        raise ValueError("工坊更新说明含 NUL 或超过 UTF-8 长度上限")
    destination = config.USERDIR if userdir is None else userdir
    if run_dir is not None:
        for forbidden in (destination / "mod", config.REPO / "mod"):
            if (
                run_dir.resolve() == forbidden.resolve()
                or forbidden.resolve() in run_dir.resolve().parents
            ):
                raise ValueError("运行目录不能放在 Mod 安装或生产源目录中")
    if run_dir is None:
        parent = config.OUT / "publishing"
        parent.mkdir(parents=True, exist_ok=True)
        run = Path(tempfile.mkdtemp(prefix="run-", dir=parent))
    else:
        deployment.reject_links(run_dir)
        if run_dir.exists():
            raise ValueError(f"运行目录已存在，拒绝覆盖证据：{run_dir}")
        run_dir.mkdir(parents=True)
        run = run_dir
    receipt = run / "receipt.json"
    report: dict[str, Any] = {
        "schema": 1,
        "status": "preflight",
        "execute": execute,
        "target": target,
        "started_at": datetime.now(UTC).isoformat(),
        "receipt": str(receipt.resolve()),
        "operations": [],
        "evidence": "publication_operation",
        "behavior_quality": "not_evaluated",
    }
    write_receipt(receipt, report)

    def operation(name: str, action: Callable[[], dict[str, Any]]) -> None:
        row: dict[str, Any] = {"name": name, "status": "in_progress"}
        report["operations"].append(row)
        write_receipt(receipt, report)
        try:
            row["result"] = action()
            row["status"] = "succeeded"
        except BaseException as exc:
            # 提交后超时可能已产生远端变更；保留异常上的不确定状态。
            row["status"] = "uncertain" if getattr(exc, "uncertain", False) else "failed"
            row["submitted"] = bool(getattr(exc, "submitted", False))
            row["error"] = str(exc)
            raise
        finally:
            write_receipt(receipt, report)

    def upload_fixed_content() -> dict[str, Any]:
        assert content is not None
        assert workshop is not None
        expected = report["package"]["files"]
        if deployment.tree_hashes(content) != expected:
            raise ValueError("上传前固定内容树发生变化")
        result = workshop.upload(content, changenote)
        try:
            if deployment.tree_hashes(content) != expected:
                raise ValueError("上传期间固定内容树发生变化")
        except (ValueError, OSError) as exc:
            raise WorkshopError(
                f"上传后固定内容树核对失败：{exc}", submitted=True, uncertain=True
            ) from exc
        return result

    try:
        local = target in {"all", "local"}
        online = target in {"all", "workshop", "descriptions"}
        descriptions = load_descriptions() if target in {"all", "descriptions"} else {}
        report["descriptions"] = {
            language: {
                "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "utf8_bytes": len(body.encode("utf-8")),
            }
            for language, body in descriptions.items()
        }
        content = None
        if target != "descriptions":
            content, package = _prepare_package(archive, run)
            report["package"] = package
        if local:
            deployment.assert_game_stopped()
            deployment.reject_links(destination / "mod" / distribution.INSTALL_DIRECTORY_NAME)
        if online:
            if workshop is None:
                workshop = SteamWorkshop(publication_config()["published_file_id"], run)
            report["remote_before"] = workshop.inspect(tuple(descriptions))
        plan = []
        if local:
            plan.append(
                {
                    "name": "local",
                    "action": "deploy_if_changed",
                    "target": str(destination / "mod" / distribution.INSTALL_DIRECTORY_NAME),
                }
            )
        if target in {"all", "workshop"}:
            plan.append({"name": "workshop", "action": "upload_content"})
        for language, body in descriptions.items():
            equal = (
                normalized_description(report["remote_before"]["descriptions"][language]) == body
            )
            plan.append(
                {
                    "name": f"description:{language}",
                    "action": "unchanged" if equal else "update_description",
                }
            )
        report["plan"] = plan
        write_receipt(receipt, report)
        if not execute:
            report["status"] = "preview"
            return report
        with deployment.deployment_lock(destination, name=".situated-ai-publish.lock"):
            if local and content is not None:
                operation("local", lambda: deployment.deploy(content, destination))
            if target in {"all", "workshop"} and content is not None:
                assert workshop is not None
                operation("workshop", upload_fixed_content)
            for language, body in descriptions.items():
                assert workshop is not None
                remote = report["remote_before"]["descriptions"][language]
                if normalized_description(remote) == body:
                    report["operations"].append(
                        {"name": f"description:{language}", "status": "unchanged"}
                    )
                    write_receipt(receipt, report)
                    continue
                operation(
                    f"description:{language}",
                    partial(workshop.describe, language, body),
                )
        report["status"] = "succeeded"
        return report
    except BaseException as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        if isinstance(exc, (ValueError, OSError)):
            raise PublicationError(str(exc), receipt) from exc
        raise
    finally:
        report["finished_at"] = datetime.now(UTC).isoformat()
        write_receipt(receipt, report)
