"""Capture current native review candidates without modifying frozen evidence.

The declarations retain the exact source/field closure. Every value below is
read from the identity-verified installation; runtime permissions remain unknown.
Use ``python -m pdx.native_authority_capture --help`` for explicit selection.
Outputs are immutable candidates under tools/out, never automatic authority updates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from . import config, version_contracts
from .model import Assignment, Block
from .parser import parse_bytes

_CAPTURE_VERSION = "1.15.1"
_KINDS = ("parameters", "retentions-native-subset", "compatibility", "technology-catalog")
_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def _candidate_path(output: Path, *, suffix: str) -> Path:
    """Keep explicit candidates in the unlinked, disposable repository output tree."""
    destination = output.absolute()
    root = (config.REPO / "tools/out").absolute()
    if (
        ".." in output.parts
        or destination.suffix != suffix
        or not destination.is_relative_to(root)
        or destination == root
    ):
        raise ValueError("候选输出必须是 tools/out 内显式指定且后缀匹配的文件")
    relative = destination.relative_to(root)
    if relative.parts[0].casefold() in {"snapshots", "evidence"}:
        raise ValueError("候选输出不能进入受控快照或登记证据目录")
    if any(
        part.endswith((" ", "."))
        or any(char in part for char in ':*?"<>|\\')
        or part.split(".")[0].upper() in _RESERVED_NAMES
        for part in relative.parts
    ):
        raise ValueError("候选输出含不安全路径名")
    if root.resolve() != root or destination.resolve() != destination or destination.is_symlink():
        raise ValueError("候选输出不能经过链接或重定向目录")
    if destination.exists() and not destination.is_file():
        raise ValueError("候选输出必须是普通文件")
    return destination


def _prepare_capture(game: Path, output: Path, *, suffix: str) -> tuple[Path, Path]:
    """Validate selection and paths before verifying the complete installed identity."""
    from .situated import r2_reader_authority  # noqa: PLC0415

    if version_contracts.active_version() != _CAPTURE_VERSION:
        raise ValueError("原版权威证据重捕获只接受当前 1.15.1 合同")
    destination = _candidate_path(output, suffix=suffix)
    game = game.absolute()
    if game.name != "game" or not game.is_dir() or game.resolve() != game:
        raise ValueError("必须显式指定真实安装根目录下未链接的 game 目录")
    if destination.is_relative_to(game.parent):
        raise ValueError("候选输出不能写入游戏安装目录")
    r2_reader_authority.verify_installation(game.parent)
    return game, destination


def _write_candidate(output: Path, text: str) -> Path:
    """Write once, or verify identical bytes without touching an existing file."""
    destination = _candidate_path(output, suffix=output.suffix)
    encoded = text.encode("utf-8")
    if destination.exists():
        if destination.read_bytes() != encoded:
            raise ValueError(f"既有候选内容不同，拒绝静默刷新：{destination}")
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as stream:
        stream.write(encoded)
    return destination


def _write(output: Path, data: dict[str, Any]) -> Path:
    return _write_candidate(output, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _root(game: Path, source: str) -> Block:
    parsed = parse_bytes(_source_bytes(game, source), path=source)
    if parsed.errors:
        raise ValueError(f"原版来源 AST 不完整：{source}")
    return parsed.root


def _source_bytes(game: Path, source: str) -> bytes:
    path = game / source
    if (
        ".." in Path(source).parts
        or not path.is_relative_to(game)
        or path.resolve() != path.absolute()
        or path.is_symlink()
        or not path.is_file()
    ):
        raise ValueError(f"原版来源缺失、链接或路径越界：{source}")
    return path.read_bytes()


def _node(root: Block, path: tuple[str, ...]) -> Assignment:
    for index, key in enumerate(path):
        entries = root.all(key)
        if len(entries) != 1 or entries[0].op != "=" or entries[0].prefix is not None:
            raise ValueError(f"原版节点必须唯一且为普通赋值：{'.'.join(path)}")
        item = entries[0]
        if not isinstance(item.value, Block):
            raise ValueError(f"原版节点必须为块：{'.'.join(path)}")
        if index == len(path) - 1:
            return item
        root = item.value
    raise ValueError("原版节点路径不能为空")


def capture_parameters(game: Path, *, output: Path) -> Path:
    """Retain the complete parameter-evidence source set with new raw hashes."""
    from .situated import vanilla_inventory  # noqa: PLC0415

    game, output = _prepare_capture(game, output, suffix=".json")
    return _write(
        output,
        {
            "schema": 1,
            "version": version_contracts.active_version(),
            "evidence_kind": "native_static",
            "runtime": "unknown",
            "sources": {
                source: hashlib.sha256(_source_bytes(game, source)).hexdigest()
                for source in vanilla_inventory._PARAMETER_EVIDENCE_HASHES
            },
        },
    )


def capture_retentions(game: Path, *, output: Path) -> Path:
    """Reprove the native subset, excluding independently reviewed policy migrations."""
    from .situated import (  # noqa: PLC0415
        migration_baseline,
        native_treatments,
    )

    game, output = _prepare_capture(game, output, suffix=".json")
    previous = json.loads(migration_baseline._VERSION_115_SOURCE.read_bytes())
    source = "common/ai_strategies/00_default_strategy.txt"
    root = _root(game, source)
    retentions = {}
    for field, historical in previous["retentions"].items():
        node = _node(root, (previous["definition"], *field.split(".")))
        digest = native_treatments._digest(node.value)
        if digest != historical:
            raise ValueError(f"当前原版保留字段与历史语义不同，必须独立处置：{field}")
        retentions[field] = digest
    baseline = version_contracts.research_path("vanilla-ai", "00_default_strategy.txt")
    return _write(
        output,
        {
            **previous,
            "capture_scope": "native_retention_subset_not_full_migration_contract",
            "version": version_contracts.active_version(),
            "source": baseline.relative_to(config.REPO).as_posix(),
            "source_sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
            "retentions": retentions,
        },
    )


def capture_compatibility(game: Path, *, output: Path) -> Path:
    """Capture the six legacy field ASTs and exact country lifecycle contracts."""
    from .situated import compatibility_115, native_treatments  # noqa: PLC0415

    game, output = _prepare_capture(game, output, suffix=".json")
    source = "common/ai_strategies/00_default_strategy.txt"
    hooks_source = "common/on_actions/00_code_on_actions.txt"
    fiscal_source = "common/script_values/war_support_values.txt"
    strategy = _root(game, source)
    hooks = _root(game, hooks_source)
    lines = _source_bytes(game, hooks_source).decode("utf-8-sig").splitlines()
    fields = {}
    hook_rows = {}
    for field in sorted(compatibility_115.FIELDS):
        node = _node(strategy, ("ai_strategy_default", field))
        fields[field] = {"line": node.line, "ast_sha256": native_treatments._digest(node.value)}
    for hook in sorted(compatibility_115.HOOKS):
        node = _node(hooks, (hook,))
        if node.line < 2:
            raise ValueError(f"原版 hook 缺少精确 Country 语境：{hook}")
        statement = lines[node.line - 2]
        if statement != "# Root = Country":
            raise ValueError(f"原版 hook 缺少精确 Country 语境：{hook}")
        hook_rows[hook] = {
            "line": node.line,
            "ast_sha256": native_treatments._digest(node.value),
            "actor": "country",
            "scope_line": node.line - 1,
            "scope_statement": statement,
        }
    return _write(
        output,
        {
            "schema": 1,
            "version": version_contracts.active_version(),
            "purpose": "complete_historical_compatibility_build_only",
            "evidence_kind": "native_static",
            "runtime": "unknown",
            "strategy_source": source,
            "strategy_source_sha256": hashlib.sha256(_source_bytes(game, source)).hexdigest(),
            "baseline_sha256": hashlib.sha256(
                version_contracts.research_path(
                    "vanilla-ai", "00_default_strategy.txt"
                ).read_bytes()
            ).hexdigest(),
            "definition": "ai_strategy_default",
            "fields": fields,
            "hooks_source": hooks_source,
            "hooks_source_sha256": hashlib.sha256(_source_bytes(game, hooks_source)).hexdigest(),
            "hooks": hook_rows,
            "fiscal_reference_source": fiscal_source,
            "fiscal_reference_source_sha256": hashlib.sha256(
                _source_bytes(game, fiscal_source)
            ).hexdigest(),
            "fiscal_reference_sha256": hashlib.sha256(
                version_contracts.research_path("vanilla-ai", "war_support_values.txt").read_bytes()
            ).hexdigest(),
        },
    )


def main(argv: list[str] | None = None) -> int:
    """Capture one explicitly selected current candidate; never refresh authority in place."""
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--profile", required=True, choices=(_CAPTURE_VERSION,))
    parser.add_argument("--installation", required=True, type=Path, help="真实游戏安装根目录")
    parser.add_argument(
        "--kind",
        required=True,
        choices=_KINDS,
        help="retentions-native-subset 只复核原版保留字段，不生成完整学校迁移合同",
    )
    parser.add_argument("--output", required=True, type=Path, help="tools/out 内显式候选文件路径")
    args = parser.parse_args(argv)
    try:
        with version_contracts.select_version(args.profile):
            game = args.installation / "game"
            if args.kind == "parameters":
                output = capture_parameters(game, output=args.output)
            elif args.kind == "retentions-native-subset":
                output = capture_retentions(game, output=args.output)
            elif args.kind == "compatibility":
                output = capture_compatibility(game, output=args.output)
            else:
                from . import technology_opportunities  # noqa: PLC0415

                output = technology_opportunities.write_catalog_1151(game, output=args.output)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"[native-authority-capture] 捕获失败：{exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "kind": args.kind,
                "version": args.profile,
                "artifact_role": "review_candidate",
                "evidence_kind": "native_static",
                "runtime": "unknown",
                "output": str(output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
