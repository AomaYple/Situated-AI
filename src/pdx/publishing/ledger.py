"""Durable, identity-bound checkpoints for resumable publication."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, cast

from pdx.publishing.local import checked_path

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from typing import BinaryIO


def _lock(handle: BinaryIO) -> None:
    try:
        if sys.platform == "win32":
            from msvcrt import LK_NBLCK, locking  # noqa: PLC0415

            locking(handle.fileno(), LK_NBLCK, 1)
        else:
            from fcntl import LOCK_EX, LOCK_NB, flock  # noqa: PLC0415

            flock(handle.fileno(), LOCK_EX | LOCK_NB)
    except OSError as error:
        raise ValueError("发布收据目录正由另一发布进程使用") from error


def atomic_write(path: Path, raw: bytes) -> None:
    checked_path(path)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".publication-", suffix=".tmp")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class PublicationLedger:
    def __init__(self, root: Path, identity_digest: str, *, read_only: bool = False) -> None:
        self.root = root
        self.path = root / "publication.json"
        self.data: dict[str, object]
        checked_path(self.path)
        if self.path.exists():
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict) or loaded.get("schema") != 1:
                raise ValueError("发布收据格式不符")
            if loaded.get("identity_sha256") != identity_digest:
                raise ValueError("已有发布收据绑定了不同的发布身份")
            self.data = loaded
        else:
            if read_only:
                raise ValueError("发布收据不存在")
            if any(path.name != ".publication.lock" for path in root.iterdir()):
                raise ValueError("初次发布要求专用的空收据目录")
            self.data = {
                "schema": 1,
                "identity_sha256": identity_digest,
                "status": "preparing",
                "channels": {},
            }
            self.write()

    def channel(self, name: str) -> dict[str, object]:
        channels = self.data.get("channels")
        if not isinstance(channels, dict):
            raise ValueError("发布收据 channels 字段损坏")
        value = channels.get(name, {})
        if not isinstance(value, dict):
            raise ValueError(f"{name} 发布阶段收据损坏")
        return cast("dict[str, object]", value)

    def checkpoint(self, name: str, value: Mapping[str, object]) -> None:
        channels = self.data.get("channels")
        if not isinstance(channels, dict):
            raise ValueError("发布收据 channels 字段损坏")
        channels[name] = dict(value)
        self.write()

    def write(self) -> None:
        raw = (json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
        atomic_write(self.path, raw)


@contextmanager
def publication_lock(path: Path) -> Iterator[None]:
    lock_path = checked_path(path)
    with lock_path.open("a+b") as lock:
        lock.seek(0)
        _lock(lock)
        yield


@contextmanager
def open_ledger(root: Path, identity_digest: str) -> Iterator[PublicationLedger]:
    root = checked_path(root.absolute())
    if not root.exists():
        root.mkdir(exist_ok=True)
    with publication_lock(root / ".publication.lock"):
        yield PublicationLedger(root, identity_digest)
