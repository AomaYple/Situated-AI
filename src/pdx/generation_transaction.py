"""Recoverable replacement of a finite set of generated repository files.

Each batch is fully staged before replacement. Earlier batches can expose
generated input ledgers to strict readers, while every touched original remains
recoverable until the enclosing generation succeeds. This is exception recovery,
not a filesystem-wide atomic commit or a power-loss journal.
"""

from __future__ import annotations

import logging
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from types import TracebackType


class GenerationTransaction:
    """Replace declared files, restoring exact original bytes/existence on error."""

    def __init__(self) -> None:
        self._originals: dict[Path, Path | None] = {}
        self._touched: list[Path] = []
        self._temporary: set[Path] = set()
        self._directories: list[Path] = []

    def __enter__(self) -> GenerationTransaction:
        return self

    @property
    def temporary_paths(self) -> frozenset[Path]:
        """Exact currently owned staging/backup paths, never a filename pattern."""
        return frozenset(self._temporary)

    def _stage(self, target: Path, content: bytes) -> Path:
        missing = []
        parent = target.parent
        while not parent.exists():
            missing.append(parent)
            parent = parent.parent
        for directory in reversed(missing):
            directory.mkdir()
            self._directories.append(directory)
        descriptor, name = tempfile.mkstemp(prefix=".sitai-generation-", dir=target.parent)
        os.close(descriptor)
        temporary = Path(name)
        self._temporary.add(temporary)
        temporary.write_bytes(content)
        return temporary

    def replace(self, files: Mapping[Path, bytes | None]) -> None:
        """Stage all originals and replacements before changing any batch member."""
        staged: dict[Path, Path | None] = {}
        for name, content in files.items():
            target = name.absolute()
            if target.is_symlink():
                raise ValueError(f"生成事务不替换符号链接：{target}")
            if target not in self._originals:
                try:
                    original = target.read_bytes()
                except FileNotFoundError:
                    self._originals[target] = None
                else:
                    self._originals[target] = self._stage(target, original)
            staged[target] = None if content is None else self._stage(target, content)
        for target, temporary in staged.items():
            if temporary is None:
                target.unlink(missing_ok=True)
            else:
                temporary.replace(target)
                self._temporary.discard(temporary)
            self._touched.append(target)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        failures = []
        if exc_type is not None:
            restored: set[Path] = set()
            for target in reversed(self._touched):
                if target in restored:
                    continue
                restored.add(target)
                original = self._originals[target]
                try:
                    if original is None:
                        target.unlink(missing_ok=True)
                    else:
                        original.replace(target)
                        self._temporary.discard(original)
                except OSError as error:
                    failures.append(f"{target}: {error}; 原件备份={original}")
        # If recovery itself is blocked, retain the original backups for manual
        # recovery and make that failure explicit instead of claiming success.
        protected = set(self._originals.values()) if failures else set()
        cleanup_failures = []
        for temporary in self._temporary - protected:
            try:
                temporary.unlink(missing_ok=True)
                self._temporary.discard(temporary)
            except OSError as error:
                cleanup_failures.append(f"{temporary}: {error}")
        for directory in reversed(self._directories):
            # Nonempty directories can contain a retained backup.
            with suppress(OSError):
                directory.rmdir()
        if failures:
            raise OSError("生成事务回滚失败：" + "; ".join(failures)) from exc_value
        if cleanup_failures:
            # Replacement/recovery has already completed. Cleanup failure must
            # not turn a committed update into a falsely reported rollback.
            logging.getLogger(__name__).warning(
                "生成事务临时文件清理失败：%s", "; ".join(cleanup_failures)
            )
