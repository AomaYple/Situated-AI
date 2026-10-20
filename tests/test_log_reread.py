"""持续采集的第二遍源读取必须留存，并在结束时从磁盘重新验收。"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from pdx import game_run


@pytest.fixture
def capture(tmp_path):
    source = tmp_path / "live"
    source.mkdir()
    return game_run.LogCapture(source, tmp_path / "logs")


def test_早期引擎世代被删除后仍可逐字节核验复读来源(capture):
    log = capture.source / "debug.log"
    expected = bytearray()
    for index in range(9):
        raw = f"generation {index}\n".encode() * 12000
        log.write_bytes(raw)
        expected.extend(raw)
        capture.poll()
        (capture.source / "debug.2.log").unlink(missing_ok=True)
        previous = capture.source / "debug.1.log"
        if previous.exists():
            previous.rename(capture.source / "debug.2.log")
        log.rename(previous)
    capture.poll()
    assert capture.errors == []
    assert (capture.destination / "debug.log").read_bytes() == expected
    result = capture.verify()
    assert result["streams"]["debug"]["bytes"] == len(expected)
    assert result["streams"]["debug"]["ranges"] == 9
    assert sum(p.stat().st_size for p in capture.archive.root.rglob("range.bin")) == len(expected)


def test_不对齐偏移仅保留复读中新增长的字节(capture):
    log = capture.source / "debug.log"
    first = bytes(range(256)) * 112  # 28672，刻意跨过后续64KiB复读边界。
    extra = b"different new source bytes\n" * 5000
    log.write_bytes(first)
    capture.poll()
    with log.open("ab") as stream:
        stream.write(extra)
    capture.poll()
    assert capture.verify()["streams"]["debug"]["bytes"] == len(first + extra)
    directories = sorted((capture.archive.root / "debug").iterdir())
    assert (directories[0] / "range.bin").read_bytes() == first
    assert (directories[1] / "range.bin").read_bytes() == extra
    entry = json.loads((directories[1] / "metadata.json").read_text(encoding="utf-8"))
    assert entry["source_start"] == entry["capture_start"] == 28672
    assert entry["source_end"] == entry["capture_end"] == len(first + extra)
    assert entry["prefix_sha256"] == hashlib.sha256(first + extra).hexdigest()
    assert entry["range_sha256"] == hashlib.sha256(extra).hexdigest()


def test_复制截断的同inode不等于同逻辑世代(capture):
    log = capture.source / "error.log"
    log.write_bytes(b"Unexpected to")
    capture.poll()
    inode = log.stat().st_ino
    shutil.copyfile(log, capture.source / "error.1.log")
    log.write_bytes(b"ken: bad\n")
    capture.poll()
    assert log.stat().st_ino == inode
    assert capture.guard.failure["kind"] == "Unexpected token"
    assert capture.verify()["streams"]["error"]["bytes"] == len(b"Unexpected token: bad\n")


def test_空日志和不变轮询不创建区间且不重新读取源(capture, monkeypatch):
    log = capture.source / "debug.log"
    log.touch()
    capture.poll()
    assert capture.verify()["streams"]["debug"]["ranges"] == 0
    log.write_bytes(b"stable\n")
    capture.poll()
    original = Path.open

    def no_source_read(path, *args, **kwargs):
        if path.parent == capture.source:
            pytest.fail("不变轮询不得增加源读取")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", no_source_read)
    capture.poll()
    result = capture.verify()
    assert capture.errors == []
    assert result["streams"]["debug"]["ranges"] == 1


@pytest.mark.parametrize("mutation", ["truncate", "overwrite", "second_read_only"])
@pytest.mark.parametrize("byte_count", [3, 1024, 8193, 105000])
def test_第二遍确实读取同一源句柄且变异永久失败(capture, monkeypatch, mutation, byte_count):
    log = capture.source / "debug.log"
    raw = (b"first source contents\n" * 5000)[:byte_count]
    log.write_bytes(raw)
    original = Path.open
    reads = []

    class Source:
        def __init__(self, stream):
            self.stream = stream
            self.second = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def fileno(self):
            return self.stream.fileno()

        def seek(self, offset):
            assert offset == 0
            self.second = True
            if mutation != "second_read_only":
                with original(log, "wb") as replacement:
                    replacement.write(raw[:-1] if mutation == "truncate" else b"x" * len(raw))
            return self.stream.seek(offset)

        def read(self, size):
            chunk = self.stream.read(size)
            reads.append((self.second, len(chunk)))
            if self.second and mutation == "second_read_only" and chunk:
                return b"x" + chunk[1:]
            return chunk

    def instrument(path, *args, **kwargs):
        stream = original(path, *args, **kwargs)
        return Source(stream) if path == log and args == ("rb",) else stream

    monkeypatch.setattr(Path, "open", instrument)
    capture.poll()
    assert capture.errors
    assert any(second for second, _ in reads)
    assert not list(capture.archive.root.rglob("[0-9]*/metadata.json"))
    monkeypatch.setattr(Path, "open", original)
    before = (capture.destination / "debug.log").read_bytes()
    log.write_bytes(raw + b"later changes do not heal the failure\n")
    capture.poll()
    assert (capture.destination / "debug.log").read_bytes() == before
    with pytest.raises(RuntimeError):
        capture.verify()


@pytest.mark.parametrize("damage", ["replace", "truncate", "append", "delete"])
def test_最终复核期间采集文件发生变化必须拒绝(capture, monkeypatch, damage):
    log = capture.source / "debug.log"
    raw = b"stable source range\n" * 100
    log.write_bytes(raw)
    capture.poll()
    original_open = Path.open
    changed = False

    class Captured:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def read(self, size=-1):
            nonlocal changed
            result = self.stream.read(size)
            if not changed and result:
                changed = True
                if damage == "replace":
                    log_target.write_bytes(b"x" * len(raw))
                elif damage == "truncate":
                    log_target.write_bytes(b"x")
                elif damage == "append":
                    with log_target.open("ab") as appended:
                        appended.write(b"tail")
                else:
                    log_target.unlink()
            return result

    log_target = capture.destination / "debug.log"

    def instrument(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return Captured(stream) if path == log_target and args == ("rb",) else stream

    monkeypatch.setattr(Path, "open", instrument)
    with pytest.raises(RuntimeError):
        capture.verify()


def test_零区间不能把同名目录误认为空采集日志(capture):
    capture.destination.mkdir()
    (capture.destination / "debug.log").mkdir()
    with pytest.raises((ValueError, RuntimeError)):
        capture.verify()


@pytest.mark.parametrize("existing", ["empty", "nonempty"])
def test_发布不能覆盖预先存在的目的目录(capture, existing):
    destination = capture.archive.root / "debug" / "00000000"
    destination.mkdir(parents=True)
    if existing == "nonempty":
        (destination / "range.bin").write_bytes(b"preserved existing bytes")
    frozen = {p.name: p.read_bytes() for p in destination.iterdir()}
    (capture.source / "debug.log").write_bytes(b"new source bytes")
    capture.poll()
    assert capture.errors
    assert {p.name: p.read_bytes() for p in destination.iterdir()} == frozen


def test_发布占位之后出现的目标文件也不能覆盖(capture, monkeypatch):
    from pdx import log_reread

    original = log_reread.os.link
    inserted = []

    def concurrent_target(source, target):
        target.write_bytes(b"preserved concurrent bytes")
        inserted.append(target)
        original(source, target)

    monkeypatch.setattr(log_reread.os, "link", concurrent_target)
    (capture.source / "debug.log").write_bytes(b"new source bytes")
    capture.poll()
    assert capture.errors
    assert inserted[0].read_bytes() == b"preserved concurrent bytes"


@pytest.mark.parametrize("fails", [False, True])
def test_不支持硬链接时独占复制且复制失败永久保留(capture, monkeypatch, fails):
    import errno

    from pdx import log_reread

    def unsupported(*_args):
        raise OSError(errno.EOPNOTSUPP, "link unsupported")

    monkeypatch.setattr(log_reread.os, "link", unsupported)
    if fails:

        def copy_failure(incoming, outgoing, _length):
            outgoing.write(incoming.read(2))
            raise OSError("injected copy failure")

        monkeypatch.setattr(log_reread.shutil, "copyfileobj", copy_failure)
    raw = b"source on a filesystem without hardlinks\n"
    (capture.source / "debug.log").write_bytes(raw)
    capture.poll()
    if fails:
        assert capture.errors
        assert capture.archive.counts["debug"] == 0
        capture.poll()
        with pytest.raises(RuntimeError):
            capture.verify()
    else:
        assert capture.errors == []
        assert capture.verify()["streams"]["debug"]["sha256"] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("kind", ["range.bin", "metadata.json"])
def test_复核期间区间或元数据被改写必须拒绝(capture, monkeypatch, kind):
    (capture.source / "debug.log").write_bytes(b"stable source contents")
    capture.poll()
    original = Path.open
    changed = False

    class Mutating:
        def __init__(self, stream, path):
            self.stream, self.path = stream, path

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def fileno(self):
            return self.stream.fileno()

        def read(self, size):
            nonlocal changed
            chunk = self.stream.read(size)
            if not changed:
                changed = True
                with original(self.path, "wb") as altered:
                    altered.write(b"x" * len(chunk))
            return chunk

    def altered_reader(path, *args, **kwargs):
        stream = original(path, *args, **kwargs)
        return Mutating(stream, path) if path.name == kind and args == ("rb",) else stream

    monkeypatch.setattr(Path, "open", altered_reader)
    with pytest.raises(RuntimeError):
        capture.verify()


@pytest.mark.parametrize("point", ["write", "flush", "close", "publish", "metadata"])
def test_持久化任一环节失败不得发布或在以后重试洗白(capture, monkeypatch, point):
    log = capture.source / "debug.log"
    log.write_bytes(b"first committed\n")
    capture.poll()
    first = min((capture.archive.root / "debug").iterdir())
    frozen = {p.name: p.read_bytes() for p in first.iterdir()}
    with log.open("ab") as stream:
        stream.write(b"uncommitted tail\n")
    original = Path.open

    class Broken:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            result = self.stream.__exit__(*args)
            if point == "close":
                raise OSError("injected close")
            return result

        def write(self, data):
            if point == "write":
                raise OSError("injected write")
            return self.stream.write(data)

        def flush(self):
            if point == "flush":
                raise OSError("injected flush")
            return self.stream.flush()

        def fileno(self):
            return self.stream.fileno()

    def fail_open(path, *args, **kwargs):
        if point == "metadata" and path.name == "metadata.json" and args == ("xb",):
            raise OSError("injected metadata")
        stream = original(path, *args, **kwargs)
        if path.name == "range.bin" and args == ("xb",):
            return Broken(stream)
        return stream

    if point == "publish":

        def fail_publish(*_args):
            raise OSError("injected publish")

        monkeypatch.setattr(capture.archive, "_publish", fail_publish)
    else:
        monkeypatch.setattr(Path, "open", fail_open)
    capture.poll()
    assert capture.errors
    assert {p.name: p.read_bytes() for p in first.iterdir()} == frozen
    assert len([p for p in first.parent.iterdir() if p.name.isdecimal()]) == 1
    before = (capture.destination / "debug.log").read_bytes()
    capture.poll()
    assert (capture.destination / "debug.log").read_bytes() == before
    with pytest.raises(RuntimeError):
        capture.verify()


@pytest.mark.parametrize(
    "damage",
    [
        "range",
        "metadata",
        "missing_range",
        "missing_metadata",
        "missing_directory",
        "sequence",
        "gap",
        "overlap",
        "unknown_file",
        "unknown_stream",
        "pending",
        "captured_tail",
        "captured_missing",
        "captured_overwrite",
    ],
)
def test_最终必须读取磁盘字节并拒绝缺损重排洞和未提交尾部(capture, damage):
    log = capture.source / "debug.log"
    log.write_bytes(b"part one\n")
    capture.poll()
    with log.open("ab") as stream:
        stream.write(b"part two\n")
    capture.poll()
    assert capture.verify()["streams"]["debug"]["ranges"] == 2
    entry = sorted((capture.archive.root / "debug").iterdir())[1]
    data, meta = entry / "range.bin", entry / "metadata.json"
    if damage == "range":
        data.write_bytes(b"wrong source bytes\n")
    elif damage == "metadata":
        meta.write_bytes(b"{}")
    elif damage == "missing_range":
        data.unlink()
    elif damage == "missing_metadata":
        meta.unlink()
    elif damage == "missing_directory":
        shutil.rmtree(entry)
    elif damage == "sequence":
        entry.rename(entry.with_name("00000009"))
    elif damage in {"gap", "overlap"}:
        value = json.loads(meta.read_text(encoding="utf-8"))
        value["capture_start"] += 1 if damage == "gap" else -1
        meta.write_text(json.dumps(value), encoding="utf-8")
    elif damage == "unknown_file":
        (entry / "unknown.bin").touch()
    elif damage == "unknown_stream":
        (capture.archive.root / "unknown").mkdir()
    elif damage == "pending":
        (entry.parent / ".pending-test").mkdir()
    elif damage == "captured_tail":
        with (capture.destination / "debug.log").open("ab") as stream:
            stream.write(b"uncommitted\n")
    elif damage == "captured_missing":
        (capture.destination / "debug.log").unlink()
    else:
        (capture.destination / "debug.log").write_bytes(b"x" * 18)
    with pytest.raises(RuntimeError):
        capture.verify()
    assert capture.errors
