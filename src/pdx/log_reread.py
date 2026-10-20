"""保存日志源句柄的第二遍新增字节，区间提交后不再覆盖。

这不是完整引擎世代原件，也不是第三方独立测量。源读取和持续采集
属于同一次运行；最终核验只证明已提交区间与采集字节相同。
发布要求刷写用户态缓冲并关闭，不承诺断电或硬件故障恢复。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .deployment_state import plain_path

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import BinaryIO


CHUNK_SIZE = 65536
STREAMS = ("debug", "error")


def _source_stat(value: os.stat_result) -> dict[str, int]:
    return {
        "device": value.st_dev,
        "inode": value.st_ino,
        "size": value.st_size,
        "mtime_ns": value.st_mtime_ns,
        "ctime_ns": value.st_ctime_ns,
    }


def _signature(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


@contextmanager
def _verified_reader(path: Path) -> Iterator[BinaryIO]:
    plain_path(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"源复读核验只接受普通文件：{path}")
    with path.open("rb", buffering=0) as stream:
        handle_before = os.fstat(stream.fileno())
        # Windows Python 3.14 的 stat/fstat 对 ctime 的底层来源不同；
        # 跨接口只比身份/大小/mtime，各接口内部仍完整核对 ctime。
        if _signature(handle_before)[:4] != _signature(before)[:4]:
            raise ValueError(f"源复读文件在打开时发生变化：{path}")
        yield stream
        if _signature(os.fstat(stream.fileno())) != _signature(handle_before):
            raise ValueError(f"源复读句柄在核验期间发生变化：{path}")
        plain_path(path)
        if _signature(path.stat()) != _signature(before):
            raise ValueError(f"源复读文件在核验期间发生变化：{path}")


class SourceRereadArchive:
    """定长状态跟踪每流序号、终点和元数据摘要；最终重新读取磁盘。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.counts = dict.fromkeys(STREAMS, 0)
        self.ends = dict.fromkeys(STREAMS, 0)
        self.chains = {stem: hashlib.sha256() for stem in STREAMS}

    @staticmethod
    def _publish(pending: Path, destination: Path) -> None:
        # 目录内的数据与元数据先全部关闭，再以不可覆盖的目录名发布。
        # 目标目录的 mkdir 是跨平台的原子占位；部分搬运失败时保留残缺目录，
        # 计数不会增加，最终核验会拒绝该残留而不是重试洗白。
        plain_path(destination)
        destination.mkdir()
        for child in pending.iterdir():
            # 同一文件系统内硬链接独占创建目标文件，不复制字节、不覆盖。
            target = destination / child.name
            try:
                os.link(child, target)
            except FileExistsError:
                raise
            except OSError:
                # FAT、受限挂载等不支持硬链接时仍用独占文件，保持平台能力边界。
                with child.open("rb") as incoming, target.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing, CHUNK_SIZE)
                    outgoing.flush()
            child.unlink()
        pending.rmdir()

    def capture(
        self,
        incoming: BinaryIO,
        *,
        stem: str,
        observed_name: str,
        source_start: int,
        source_end: int,
        source_stat: os.stat_result,
        prefix_sha256: str,
        capture_start: int,
    ) -> None:
        if stem not in STREAMS or not 0 <= source_start <= source_end:
            raise ValueError("复读源区间无效")
        length = source_end - source_start
        if capture_start != self.ends[stem]:
            raise RuntimeError(f"复读区间与采集位置不连续：{stem}")
        pending = None
        if length:
            parent = self.root / stem
            plain_path(parent)
            parent.mkdir(parents=True, exist_ok=True)
            pending = Path(tempfile.mkdtemp(prefix=".pending-", dir=parent))
        incoming.seek(0)
        full_hash = hashlib.sha256()
        range_hash = hashlib.sha256()
        position = 0
        output = (pending / "range.bin").open("xb") if pending is not None else nullcontext(None)
        with output as target:
            while position < source_end:
                chunk = incoming.read(min(source_end - position, CHUNK_SIZE))
                if not chunk:
                    raise RuntimeError(f"日志复读期间截断：{observed_name}")
                full_hash.update(chunk)
                end = position + len(chunk)
                if target is not None and end > source_start:
                    addition = chunk[max(source_start - position, 0) :]
                    if target.write(addition) != len(addition):
                        raise OSError("源复读区间写入不完整")
                    range_hash.update(addition)
                position = end
            if full_hash.hexdigest() != prefix_sha256:
                raise RuntimeError(f"日志复读期间覆写：{observed_name}")
            after = os.fstat(incoming.fileno())
            if after.st_size < source_end:
                raise RuntimeError(f"日志复读后截断：{observed_name}")
            if target is not None:
                target.flush()
        if pending is None:
            return
        metadata = {
            "schema": 1,
            "stream": stem,
            "sequence": self.counts[stem],
            "capture_start": capture_start,
            "capture_end": capture_start + length,
            "source_start": source_start,
            "source_end": source_end,
            "observed_name": observed_name,
            "source_stat_before": _source_stat(source_stat),
            "source_stat_after": _source_stat(after),
            "prefix_sha256": prefix_sha256,
            "range_sha256": range_hash.hexdigest(),
        }
        encoded = (json.dumps(metadata, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        with (pending / "metadata.json").open("xb") as stream:
            if stream.write(encoded) != len(encoded):
                raise OSError("源复读元数据写入不完整")
            stream.flush()
        self._publish(pending, pending.parent / f"{self.counts[stem]:08d}")
        self.chains[stem].update(encoded)
        self.counts[stem] += 1
        self.ends[stem] += length

    def verify(self, captured: Path) -> dict[str, Any]:
        """拒绝未提交尾部及未知内容；大小、摘要和逐字节比较分别检查。"""
        plain_path(self.root)
        before = self.root.stat() if self.root.exists() else None
        if before is not None:
            if not self.root.is_dir():
                raise ValueError("源复读归档不是目录")
            for path in self.root.iterdir():
                plain_path(path)
                if path.name not in STREAMS or not path.is_dir():
                    raise ValueError(f"未知源复读归档：{path}")
        streams = {stem: self._verify_stream(stem, captured / f"{stem}.log") for stem in STREAMS}
        if before is not None:
            self._assert_stable(self.root, before, "源复读归档", directory=True)
        elif self.root.exists():
            raise ValueError("源复读归档在核验期间出现")
        return {
            "kind": "source_handle_reread_ranges",
            "root": str(self.root),
            "streams": streams,
            "limits": "同次原始源句柄的第二遍区间，非完整世代原件或第三方独立测量；不涵盖首次轮询前已被删除的字节。",
        }

    def _verify_stream(self, stem: str, captured: Path) -> dict[str, Any]:
        parent = self.root / stem
        plain_path(parent)
        parent_before = parent.stat() if parent.exists() else None
        if parent.exists():
            if not parent.is_dir():
                raise ValueError(f"源复读流不是目录：{stem}")
            count = 0
            for path in parent.iterdir():
                plain_path(path)
                if not path.is_dir() or not path.name.isdecimal():
                    raise ValueError(f"未知或未提交源复读区间：{path}")
                count += 1
            if count != self.counts[stem]:
                raise ValueError(f"源复读区间数量不符：{stem}")
        elif self.counts[stem]:
            raise ValueError(f"源复读流缺失：{stem}")
        plain_path(captured)
        if captured.exists() and not stat.S_ISREG(captured.stat().st_mode):
            raise ValueError(f"采集日志不是普通文件：{stem}")
        if not self.counts[stem]:
            if captured.exists():
                with _verified_reader(captured) as stream:
                    if stream.read(1):
                        raise ValueError(f"采集日志存在未提交尾部：{stem}")
            if parent_before is not None:
                self._assert_stable(parent, parent_before, "源复读流目录", directory=True)
            elif parent.exists():
                raise ValueError(f"源复读流目录在核验期间出现：{stem}")
            return {
                "ranges": 0,
                "bytes": 0,
                "sha256": hashlib.sha256().hexdigest(),
                "metadata_sha256": self.chains[stem].hexdigest(),
            }
        position = 0
        chain = hashlib.sha256()
        capture_hash = hashlib.sha256()
        with _verified_reader(captured) as target:
            for sequence in range(self.counts[stem]):
                directory = parent / f"{sequence:08d}"
                plain_path(directory)
                directory_before = directory.stat()
                if {p.name for p in directory.iterdir()} != {"range.bin", "metadata.json"}:
                    raise ValueError(f"源复读区间包含缺失或未知文件：{directory}")
                meta_path, data_path = directory / "metadata.json", directory / "range.bin"
                plain_path(meta_path)
                plain_path(data_path)
                with _verified_reader(meta_path) as stream:
                    encoded = stream.read(16385)
                if len(encoded) > 16384:
                    raise ValueError("源复读元数据超出大小预算")
                entry = json.loads(encoded)
                chain.update(encoded)
                if not isinstance(entry, dict):
                    raise ValueError("源复读元数据必须是对象")
                integers = (
                    "sequence",
                    "capture_start",
                    "capture_end",
                    "source_start",
                    "source_end",
                )
                if any(type(entry.get(key)) is not int for key in integers):
                    raise ValueError("源复读区间必须使用整数位置")
                length = entry["capture_end"] - position
                if not (
                    entry.get("schema") == 1
                    and entry.get("stream") == stem
                    and entry["sequence"] == sequence
                    and entry["capture_start"] == position
                    and length > 0
                    and entry["source_start"] >= 0
                    and entry["source_end"] - entry["source_start"] == length
                    and data_path.stat().st_size == length
                ):
                    raise ValueError(f"源复读区间存在洞、重叠或长度不符：{directory}")
                range_hash = hashlib.sha256()
                read_bytes = 0
                with _verified_reader(data_path) as source:
                    while chunk := source.read(CHUNK_SIZE):
                        if target.read(len(chunk)) != chunk:
                            raise ValueError(f"采集日志与源复读字节不同：{directory}")
                        range_hash.update(chunk)
                        capture_hash.update(chunk)
                        read_bytes += len(chunk)
                if read_bytes != length or range_hash.hexdigest() != entry.get("range_sha256"):
                    raise ValueError(f"源复读区间摘要不符：{directory}")
                self._assert_stable(directory, directory_before, "源复读区间目录", directory=True)
                position = entry["capture_end"]
            if target.read(1) or position != self.ends[stem]:
                raise ValueError(f"采集日志存在未提交尾部或长度不符：{stem}")
        if chain.digest() != self.chains[stem].digest():
            raise ValueError(f"源复读元数据与运行期提交摘要不符：{stem}")
        if parent_before is not None:
            self._assert_stable(parent, parent_before, "源复读流目录", directory=True)
        return {
            "ranges": self.counts[stem],
            "bytes": position,
            "sha256": capture_hash.hexdigest(),
            "metadata_sha256": chain.hexdigest(),
        }

    @staticmethod
    def _assert_stable(
        path: Path, before: os.stat_result, kind: str, *, directory: bool = False
    ) -> None:
        plain_path(path)
        after = path.stat()
        correct_type = stat.S_ISDIR(after.st_mode) if directory else stat.S_ISREG(after.st_mode)
        if not correct_type or _signature(before) != _signature(after):
            raise ValueError(f"{kind}在核验期间发生变化：{path}")
