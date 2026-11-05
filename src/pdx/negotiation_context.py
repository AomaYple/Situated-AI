"""Exact native numeric input for the deliberately migrated negotiation policy."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from . import config
from .textio import normalized_text

if TYPE_CHECKING:
    from .decision_rules import Reader
    from .situated.decision_ir import EvaluationContext

SOURCE = "research/situated/victoria3-1.15.0-negotiation-context.json"
SHA256 = "5e8a0d362cbad651d086d09072f25108e475d17d479083b2e80ac9f2aad15141"
ENGINE = "scope:amenability"
KEY = "negotiation_amenability"
UNIT = "normalized_amenability_input"


def snapshot() -> bytes:
    raw = (config.REPO / SOURCE).read_bytes()
    if hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError("谈判原生作用域证明漂移")
    data = json.loads(raw)
    if data["schema"] != 1 or data["version"] != "1.15.0":
        raise ValueError("谈判原生作用域证明版本漂移")
    exe = config.GAME.parent / "binaries/victoria3.exe"
    if exe.is_file():
        for evidence in (data["native_evidence"], data["native_comparison_evidence"]):
            if exe.stat().st_size != evidence["exe"]["bytes"]:
                raise ValueError("谈判原生EXE身份漂移")
            with exe.open("rb") as stream:
                for row in evidence["observations"]:
                    stream.seek(int(row["file_offset"], 16))
                    expected = bytes.fromhex(row["bytes"])
                    if stream.read(len(expected)) != expected:
                        raise ValueError("谈判原生帧/数值比较/随机门/执行尾部字节漂移")
    native = config.GAME / data["native_source"]["source"]
    if (
        native.is_file()
        and hashlib.sha256(
            normalized_text(native.read_text(encoding="utf-8-sig")).encode()
        ).hexdigest()
        != data["native_source"]["normalized_sha256"]
    ):
        raise ValueError("谈判原生完整表达式漂移")
    return raw


def validate_reader(
    reader: Reader, actor_path: tuple[str, ...] = (), native_root: str = "country"
) -> None:
    if (
        reader.key != KEY
        or reader.engine != ENGINE
        or reader.scope != "root"
        or reader.unit != UNIT
        or reader.kind != "number"
        or reader.minimum is not None
        or reader.maximum is not None
        or reader.argument is not None
        or reader.parameters
        or reader.path
        or reader.value_field is not None
        or actor_path
        or native_root != "country"
    ):
        raise ValueError("谈判amenability只允许精确本国帧具名数值签名")


def evaluation_context(text: str) -> EvaluationContext:
    from .situated import decision_ir  # noqa: PLC0415

    raw = snapshot()
    data = json.loads(raw)
    if (
        hashlib.sha256(normalized_text(text).encode()).hexdigest()
        != data["native_source"]["normalized_sha256"]
    ):
        return decision_ir.EvaluationContext(status="unknown")
    lines = raw.decode("utf-8").splitlines()
    query_line = next(i for i, line in enumerate(lines, 1) if '"id": "negotiation_query"' in line)
    return decision_ir.EvaluationContext(
        actor_scope=decision_ir.ContextBinding("root", "country", "actor", SOURCE, query_line),
        auxiliary_scopes=tuple(
            decision_ir.ContextBinding(name, kind, "auxiliary", SOURCE, query_line)
            for name, kind in (
                ("law", "law"),
                ("amenability", "scalar"),
                ("advance_chance", "scalar"),
                ("stall_chance", "scalar"),
            )
        ),
        evidence=(f"{SOURCE}:{query_line}",),
    )
