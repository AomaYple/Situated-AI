"""Reviewed native authority for the current production generator."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, cast

from pdx import config, version_contracts
from pdx.model import Block
from pdx.parser import parse_bytes
from pdx.textio import normalized_text

from . import engine_scope, migration_baseline

if TYPE_CHECKING:
    from pathlib import Path

CURRENT_SHA256 = "10ab73a7890c4d0da10d9367560fdfe2269e8e4125d3e6329dd02a95ed16afc5"
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


def declaration() -> bytes:
    """Load the exact reviewed script declaration without accessing installed bytes."""
    source = version_contracts.research_path("situated", "compatibility-production.json")
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CURRENT_SHA256:
        raise ValueError("1.15 完整兼容生成来源合同漂移")
    data = json.loads(raw)
    if (
        data["schema"] != 1
        or data["version"] != version_contracts.active_version()
        or data["purpose"] != "complete_historical_compatibility_build_only"
        or data["evidence_kind"] != "native_static"
        or data["runtime"] != "unknown"
        or set(data["fields"]) != FIELDS
        or set(data["hooks"]) != HOOKS
    ):
        raise ValueError("1.15 完整兼容生成身份或范围漂移")
    return raw


def snapshot(*, game: Path | None = None) -> bytes:
    """Verify the current native fields and separately proven binary scope."""
    raw = declaration()
    data = json.loads(raw)
    binary = json.loads(engine_scope.strategy_snapshot())
    if binary["script_hashes"].get(data["strategy_source"]) != data["strategy_source_sha256"]:
        raise ValueError("1.15 完整兼容策略与独立引擎证据来源不一致")
    for field in FIELDS - {"diplomatic_play_support"}:
        if binary["consumers"][field]["actor_scope"] != "country":
            raise ValueError(f"1.15 完整兼容策略没有国家对象证据：{field}")
    from .compiler import verify_default_strategy_projection  # noqa: PLC0415

    game = config.GAME if game is None else game
    text = version_contracts.read_default_strategy(game)
    verify_default_strategy_projection(text)
    migration_baseline.verify_default_strategy_retention(text)
    migration_baseline.verify_school_replacement_output(game.parent, text)
    baseline = text.encode("utf-8")
    if hashlib.sha256(baseline).hexdigest() != data["baseline_sha256"]:
        raise ValueError("1.15 完整兼容策略底本字节漂移")
    parsed = parse_bytes(baseline, path=data["strategy_source"])
    definitions = parsed.root.all(data["definition"])
    if parsed.errors or len(definitions) != 1 or not isinstance(definitions[0].value, Block):
        raise ValueError("1.15 完整兼容策略定义不唯一或无法解析")
    for field, row in data["fields"].items():
        _ordinary_digest(definitions[0].value, field, row)
    reference = game / data["fiscal_reference_source"]
    reference_bytes = normalized_text(reference.read_bytes().decode("utf-8-sig")).encode("utf-8")
    if hashlib.sha256(reference_bytes).hexdigest() != data["fiscal_reference_sha256"]:
        raise ValueError("1.15 财政原版参考字节漂移")
    return raw


def contract(*, game: Path | None = None) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(snapshot(game=game)))


def verify_game(game: Path) -> None:
    """Generation requires actual source bytes and exact country hook ASTs."""
    data = contract(game=game)
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
