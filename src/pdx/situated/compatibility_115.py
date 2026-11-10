"""Current native authority for the complete historical compatibility generator.

This builds engineering witnesses for the complete legacy graph. It does not
select, package or deploy the separate R2 production candidate.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, cast

from pdx.model import Block
from pdx.parser import parse_bytes

from . import engine_scope

if TYPE_CHECKING:
    from pathlib import Path

SOURCE = engine_scope.REPO / "research/situated/1.15.0/compatibility-production.json"
SHA256 = "f979697ed4bc2750a130f605d60cf2de0b4d2e6123b7a4e9eda0dd39b570e562"
FIELDS = frozenset(
    {
        "diplomatic_play_neutrality",
        "aggression",
        "diplomatic_play_support",
        "change_law_chance",
        "economic_vs_government_spending_balance",
        "recklessness",
    }
)
HOOKS = frozenset(
    {
        "on_monthly_pulse_country",
        "on_country_default",
        "on_country_no_longer_default",
    }
)


def _ordinary_digest(root: Block, name: str, row: dict[str, Any]) -> None:
    from .native_treatments import _digest  # noqa: PLC0415

    nodes = root.all(name)
    if (
        len(nodes) != 1
        or nodes[0].op != "="
        or nodes[0].prefix is not None
        or not isinstance(nodes[0].value, Block)
        or nodes[0].line != row["line"]
        or _digest(nodes[0].value) != row["ast_sha256"]
    ):
        raise ValueError(f"1.15 完整兼容生成原版 AST 漂移：{name}")


def snapshot() -> bytes:
    """Verify the current native fields and separately proven binary scope."""
    raw = SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError("1.15 完整兼容生成来源合同漂移")
    data = json.loads(raw)
    if (
        data["schema"] != 1
        or data["version"] != "1.15.0"
        or data["purpose"] != "complete_historical_compatibility_build_only"
        or data["evidence_kind"] != "native_static"
        or data["runtime"] != "unknown"
        or set(data["fields"]) != FIELDS
        or set(data["hooks"]) != HOOKS
    ):
        raise ValueError("1.15 完整兼容生成身份或范围漂移")
    binary = json.loads(engine_scope.strategy_snapshot())
    if binary["script_hashes"].get(data["strategy_source"]) != data["strategy_source_sha256"]:
        raise ValueError("1.15 完整兼容策略与独立引擎证据来源不一致")
    for field in FIELDS - {"diplomatic_play_support"}:
        if binary["consumers"][field]["actor_scope"] != "country":
            raise ValueError(f"1.15 完整兼容策略没有国家对象证据：{field}")
    from .compiler import baseline_path, support_evaluation_context  # noqa: PLC0415

    support = support_evaluation_context()
    if support.actor_scope is None or support.actor_scope.kind != "country":
        raise ValueError("1.15 完整兼容支持字段缺少独立原版文档对象证据")

    baseline = baseline_path().read_bytes()
    if hashlib.sha256(baseline).hexdigest() != data["baseline_sha256"]:
        raise ValueError("1.15 完整兼容策略底本字节漂移")
    parsed = parse_bytes(baseline, path=data["strategy_source"])
    definitions = parsed.root.all(data["definition"])
    if parsed.errors or len(definitions) != 1 or not isinstance(definitions[0].value, Block):
        raise ValueError("1.15 完整兼容策略定义不唯一或无法解析")
    for field, row in data["fields"].items():
        _ordinary_digest(definitions[0].value, field, row)
    reference = baseline_path().parent / "war_support_values.txt"
    if hashlib.sha256(reference.read_bytes()).hexdigest() != data["fiscal_reference_sha256"]:
        raise ValueError("1.15 财政原版参考字节漂移")
    return raw


def contract() -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(snapshot()))


def verify_game(game: Path) -> None:
    """Generation requires actual source bytes and exact country hook ASTs."""
    data = contract()
    if not engine_scope.verify_strategy_game(game).verified:
        raise ValueError("1.15 完整兼容生成缺少当前真实 EXE 的策略作用域证明")
    for source, expected in (
        (data["strategy_source"], data["strategy_source_sha256"]),
        (data["hooks_source"], data["hooks_source_sha256"]),
        (data["fiscal_reference_source"], data["fiscal_reference_source_sha256"]),
    ):
        path = game / source
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"1.15 完整兼容生成缺少锁定原版来源：{source}")
    raw = (game / data["hooks_source"]).read_bytes()
    parsed = parse_bytes(raw, path=data["hooks_source"])
    if parsed.errors:
        raise ValueError("1.15 财政原版 on_actions 解析失败")
    lines = raw.decode("utf-8-sig").splitlines()
    for hook, row in data["hooks"].items():
        _ordinary_digest(parsed.root, hook, row)
        if (
            row["actor"] != "country"
            or row["scope_line"] != row["line"] - 1
            or row["scope_statement"] != "# Root = Country"
            or lines[row["scope_line"] - 1] != row["scope_statement"]
        ):
            raise ValueError(f"1.15 财政原版 hook 国家对象证据漂移：{hook}")
