"""静态同名候选关联；不作为原版执行或仲裁的消费者白名单。"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .information_catalog import InformationCatalog


class ConsumerKind(StrEnum):
    DIRECT = "direct"
    STRATEGY = "strategy"
    QUALIFICATION = "qualification"
    EXPLANATION = "explanation"


@dataclass(frozen=True, slots=True)
class ConsumerMapping:
    information_id: str
    consumer: str
    field: str
    kind: ConsumerKind
    merge: str
    fallback: str
    source: str
    behavior_verified: bool = False

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                self.information_id,
                self.consumer,
                self.field,
                self.merge,
                self.fallback,
                self.source,
            )
        ):
            raise ValueError("消费者映射字段不能为空")

    def to_dict(self) -> dict[str, object]:
        return {
            "information_id": self.information_id,
            "consumer": self.consumer,
            "field": self.field,
            "kind": self.kind.value,
            "merge": self.merge,
            "fallback": self.fallback,
            "source": self.source,
            "behavior_verified": self.behavior_verified,
        }


@dataclass(frozen=True, slots=True)
class ConsumerMatrix:
    mappings: tuple[ConsumerMapping, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        keys = [(mapping.information_id, mapping.consumer) for mapping in self.mappings]
        if len(keys) != len(set(keys)):
            raise ValueError("消费者矩阵中存在重复映射")
        if tuple(keys) != tuple(sorted(keys)):
            raise ValueError("消费者矩阵必须按信息 ID 和消费者排序")

    @classmethod
    def from_catalog(cls, catalog: InformationCatalog) -> ConsumerMatrix:
        values: list[ConsumerMapping] = []
        for item in catalog.items:
            for consumer in item.consumers:
                kind = (
                    ConsumerKind.QUALIFICATION if ":possible" in consumer else ConsumerKind.STRATEGY
                )
                field = consumer.rsplit(":", 1)[-1]
                values.append(
                    ConsumerMapping(
                        information_id=item.id,
                        consumer=consumer,
                        field=field,
                        kind=kind,
                        merge="unresolved_static_association",
                        fallback="not_an_execution_contract",
                        source=item.source,
                        behavior_verified=False,
                    )
                )
        return cls(tuple(sorted(values, key=lambda value: (value.information_id, value.consumer))))

    @property
    def unverified(self) -> tuple[ConsumerMapping, ...]:
        return tuple(item for item in self.mappings if not item.behavior_verified)

    def to_dict(self) -> dict[str, object]:
        return {
            "format_version": 1,
            "evidence": "static_name_associations_only",
            "count": len(self.mappings),
            "unverified": len(self.unverified),
            "mappings": [mapping.to_dict() for mapping in self.mappings],
        }

    def write(self, path: Path) -> None:
        """以 UTF-8 无 BOM、LF、原子替换方式写出矩阵。"""

        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=1) + "\n"
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            Path(temporary).replace(path)
        except BaseException:
            with suppress(FileNotFoundError):
                Path(temporary).unlink()
            raise


__all__ = ["ConsumerKind", "ConsumerMapping", "ConsumerMatrix"]
