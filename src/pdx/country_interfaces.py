"""国家接口的可复核原版样例；类型签名与参数证据分别校验。

在线校验原始文件哈希和 AST；离线校验绑定精简快照的冻结样例。
出现过的词不是任意拼接合法性的证明，作用域/单位仍由 reader_scope 限制。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import config, country_state, version_contracts
from .model import Block, Scalar
from .parser import parse_text
from .textio import normalized_text

EVIDENCE = config.REPO / "research/vanilla-ai/1.14.5/country-interfaces.json"
BASELINE = EVIDENCE.parent / "00_default_strategy.txt"
EVIDENCE_1151_SHA256 = "3c75b27004b4c4ff0bc978dec70411fefe747ec75d66144b64e1abbf3e658165"
EVIDENCE_115_SHA256 = "c2e1eec0205efaa2e4c04ff770db418a4d7bd5ebe2649301eabca3e9a861e006"


def evidence_file() -> Path:
    """Choose current evidence at the call boundary, preserving historical overrides."""
    if version_contracts.is_115():
        return version_contracts.research_path("vanilla-ai", "country-interfaces.json")
    return EVIDENCE


def baseline_path() -> Path:
    if version_contracts.is_115():
        return version_contracts.research_path("vanilla-ai", "00_default_strategy.txt")
    return BASELINE


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


# Frozen evidence records actual native lifecycle syntax as well as current readers.
# Keeping this AST extraction rule does not require or generate Mod lifecycle hooks.
_NATIVE_HOOKS = frozenset(
    {"on_monthly_pulse_country", "on_country_default", "on_country_no_longer_default"}
)


def _required(policy):
    return {r["engine"] for r in policy.readers.values()} | {"is_ai"}


def _arguments(policy):
    return {(r["engine"], r["argument"]) for r in policy.readers.values() if "argument" in r}


def _observations(raw, relative):
    parsed = parse_text(raw.decode("utf-8-sig"), relative)
    if parsed.errors:
        raise ValueError(f"原版接口样例解析失败：{relative}")
    words: dict[str, int] = {}
    arguments: dict[tuple[str, str], int] = {}

    def walk(block, *, top=False):
        for assignment in block.assignments():
            key, value = assignment.key, assignment.value
            if key not in _NATIVE_HOOKS or (top and relative.startswith("common/on_actions/")):
                words.setdefault(key, assignment.line)
            if isinstance(value, Scalar) and not value.text.startswith('"'):
                words.setdefault(value.text, assignment.line)
            if top and relative.startswith("common/ai_strategies/"):
                arguments[("has_strategy", key)] = assignment.line
            if top and relative.startswith("common/technology/technologies/"):
                arguments[("has_technology_researched", key)] = assignment.line
            if key == "set_variable":
                name_assignment = value.first("name") if isinstance(value, Block) else None
                name = (
                    value
                    if isinstance(value, Scalar)
                    else name_assignment.value
                    if name_assignment is not None
                    else None
                )
                if isinstance(name, Scalar):
                    arguments[("has_variable", name.unquoted)] = assignment.line
            if isinstance(value, Block):
                walk(value)

    walk(parsed.root, top=True)
    return words, arguments


def _ast_context(raw, relative, token, line):
    """Capture lexical ancestry and exact AST, without inferring reader permissions."""
    parsed = parse_text(raw.decode("utf-8-sig"), relative)
    if parsed.errors:
        raise ValueError(f"原版接口样例解析失败：{relative}")

    def shape(node):
        if isinstance(node, Block):
            return [shape(item) for item in node.items]
        if isinstance(node, Scalar):
            return [node.text, node.quoted]
        return [node.key, node.op, node.prefix, shape(node.value)]

    def walk(block, parents):
        for item in block.assignments():
            name = item.value.first("name") if isinstance(item.value, Block) else None
            variable_name = name.value if name is not None else None
            if item.line == line and (
                item.key == token
                or (isinstance(item.value, Scalar) and item.value.text == token)
                or (
                    item.key == "set_variable"
                    and isinstance(variable_name, Scalar)
                    and variable_name.unquoted == token
                )
            ):
                return {
                    "ancestor_path": parents,
                    "assignment_key": item.key,
                    "operator": item.op,
                    "prefix": item.prefix,
                    "assignment_ast_sha256": _digest(shape(item)),
                    "scope_authorization": "none_lexical_context_only",
                }
            if isinstance(item.value, Block):
                result = walk(
                    item.value,
                    [
                        *parents,
                        {
                            "key": item.key,
                            "line": item.line,
                            "operator": item.op,
                            "prefix": item.prefix,
                        },
                    ],
                )
                if result is not None:
                    return result
        return None

    result = walk(parsed.root, [])
    if result is None:
        raise ValueError(f"国家接口AST语境缺失：{relative}:{line}:{token}")
    return result


def extract(policy, root, sections):
    """从真实原版建立有限样例，不改写既有快照或原版镜像。"""
    root = Path(root)
    baseline = root / "common/ai_strategies/00_default_strategy.txt"
    try:
        baseline_text = baseline.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise ValueError("缺少锁定游戏原件") from exc
    if normalized_text(baseline_text) != baseline_path().read_text(encoding="utf-8"):
        raise ValueError("国家接口底本漂移")
    required, arguments = _required(policy), _arguments(policy)
    found: dict[str, dict[str, Any]] = {}
    args: dict[tuple[str, str], dict[str, Any]] = {}
    sources: dict[str, str] = {}
    for path in sorted([*(root / "common").rglob("*.txt"), *(root / "events").rglob("*.txt")]):
        relative = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        # 粗筛只省解析；最终仍从 AST 取证，不从注释/字符串猜接口。
        if not any(token.encode() in raw for token in required - found.keys()) and not any(
            token.encode() in raw for _, token in arguments - args.keys()
        ):
            continue
        words, observed = _observations(raw, relative)
        new_words = (required - found.keys()) & words.keys()
        new_args = (arguments - args.keys()) & observed.keys()
        if new_words or new_args:
            sources[relative] = hashlib.sha256(raw).hexdigest()
            found.update(
                {word: {"source": relative, "line": words[word]} for word in sorted(new_words)}
            )
            args.update(
                {pair: {"source": relative, "line": observed[pair]} for pair in sorted(new_args)}
            )
        if set(found) == required and set(args) == arguments:
            break
    if required - found.keys() or arguments - args.keys():
        raise ValueError(
            f"国家接口/参数缺少原版证据：{required - found.keys()}, {arguments - args.keys()}"
        )
    result = {
        "schema": 1,
        "evidence": "static_vanilla_examples_not_engine_execution",
        "baseline_sha256": hashlib.sha256(baseline_path().read_bytes()).hexdigest(),
        "snapshot_sections_sha256": _digest(sections),
        "sources": sources,
        "interfaces": found,
        "arguments": [
            {"engine": engine, "argument": argument, **row}
            for (engine, argument), row in sorted(args.items())
        ],
    }
    if version_contracts.is_115():
        # A building modifier with the same spelling is not a country reader example.
        relative = "common/decisions/00_decisions.txt"
        raw = (root / relative).read_bytes()
        words, _ = _observations(raw, relative)
        found["bureaucracy"] = {"source": relative, "line": words["bureaucracy"]}
        sources[relative] = hashlib.sha256(raw).hexdigest()
        used = {row["source"] for row in [*found.values(), *result["arguments"]]}
        result["sources"] = {key: value for key, value in sources.items() if key in used}
        result["baseline_version"] = version_contracts.active_version()
        for token, row in found.items():
            row["ast_context"] = _ast_context(
                (root / row["source"]).read_bytes(), row["source"], token, row["line"]
            )
        bureaucracy = found["bureaucracy"]
        context = bureaucracy["ast_context"]
        if (
            bureaucracy["line"] != 32
            or [entry["key"] for entry in context["ancestor_path"]]
            != ["revive_olympic_games_decision", "ai_chance", "if", "limit"]
            or any(
                entry["operator"] != "=" or entry["prefix"] is not None
                for entry in context["ancestor_path"]
            )
            or context["assignment_key"] != "bureaucracy"
            or context["operator"] != ">"
            or context["prefix"] is not None
            or context["assignment_ast_sha256"]
            != "4a0ca97f0d21262016b445a8852426b2d8852c7ba92a541a859c5720d809f420"
        ):
            raise ValueError("国家bureaucracy原版country决议条件AST漂移")
        for row in result["arguments"]:
            row["ast_context"] = _ast_context(
                (root / row["source"]).read_bytes(), row["source"], row["argument"], row["line"]
            )
    return result


def validate(policy, *, root=None, snapshot=None, evidence_path=None):
    selected_path = evidence_file() if evidence_path is None else Path(evidence_path)
    raw = selected_path.read_bytes()
    if version_contracts.is_115() and hashlib.sha256(raw).hexdigest() != (
        EVIDENCE_1151_SHA256
        if version_contracts.active_version() == "1.15.1"
        else EVIDENCE_115_SHA256
    ):
        raise ValueError("国家接口当前权威证据漂移")
    evidence = json.loads(raw)
    if (
        not isinstance(evidence, dict)
        or evidence.get("schema") != 1
        or evidence.get("baseline_sha256")
        != hashlib.sha256(baseline_path().read_bytes()).hexdigest()
    ):
        raise ValueError("国家接口冻结底本无效")
    sources, interfaces, args = (
        evidence.get(key) for key in ("sources", "interfaces", "arguments")
    )
    if (
        not isinstance(sources, dict)
        or not sources
        or not isinstance(interfaces, dict)
        or not isinstance(args, list)
    ):
        raise ValueError("国家接口证据结构无效")
    for relative, digest in sources.items():
        path = Path(relative)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in relative
            or not relative.startswith(("common/", "events/"))
        ):
            raise ValueError("国家接口证据路径无效")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError("国家接口证据指纹无效")
    for row in [*interfaces.values(), *args]:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("source"), str)
            or row.get("source") not in sources
            or type(row.get("line")) is not int
            or row["line"] <= 0
        ):
            raise ValueError("国家接口样例位置无效")
    if any(
        not isinstance(row.get("engine"), str) or not isinstance(row.get("argument"), str)
        for row in args
    ):
        raise ValueError("国家参数证据结构无效")
    if version_contracts.is_115():
        if evidence.get("baseline_version") != version_contracts.active_version():
            raise ValueError("国家接口当前版本身份无效")
        for row in [*interfaces.values(), *args]:
            context = row.get("ast_context")
            if (
                not isinstance(context, dict)
                or context.get("scope_authorization") != "none_lexical_context_only"
                or not isinstance(context.get("ancestor_path"), list)
                or not isinstance(context.get("assignment_key"), str)
                or not isinstance(context.get("assignment_ast_sha256"), str)
                or len(context["assignment_ast_sha256"]) != 64
            ):
                raise ValueError("国家接口当前AST语境无效")
    if not _required(policy) <= evidence["interfaces"].keys():
        raise ValueError("国家接口缺少冻结证据")
    arguments = {(r["engine"], r["argument"]) for r in evidence["arguments"]}
    if not _arguments(policy) <= arguments:
        raise ValueError("国家 reader 参数没有原版定义/写入证据")
    if root is None:
        if not isinstance(snapshot, Mapping):
            raise ValueError("国家接口校验需要锁定原版或冻结快照")
        sections = snapshot.get("域", snapshot.get("sections"))
        if (
            not isinstance(sections, Mapping)
            or _digest(sections) != evidence["snapshot_sections_sha256"]
        ):
            raise ValueError("国家接口快照缺失或漂移")
        return
    root = Path(root)
    try:
        baseline_text = (root / "common/ai_strategies/00_default_strategy.txt").read_text(
            encoding="utf-8-sig"
        )
    except FileNotFoundError as exc:
        raise ValueError("缺少锁定游戏原件") from exc
    if normalized_text(baseline_text) != baseline_path().read_text(encoding="utf-8"):
        raise ValueError("国家接口底本漂移")
    observed = {}
    for relative, digest in evidence["sources"].items():
        path = Path(relative)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in relative
            or not relative.startswith(("common/", "events/"))
        ):
            raise ValueError("国家接口证据路径无效")
        raw = (root / path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError(f"国家接口样例漂移：{relative}")
        observed[relative] = _observations(raw, relative)
    for key, row in evidence["interfaces"].items():
        if observed[row["source"]][0].get(key) != row["line"]:
            raise ValueError(f"国家接口样例不匹配：{key}")
        if version_contracts.is_115() and row["ast_context"] != _ast_context(
            (root / row["source"]).read_bytes(), row["source"], key, row["line"]
        ):
            raise ValueError(f"国家接口AST语境不匹配：{key}")
    for row in evidence["arguments"]:
        if observed[row["source"]][1].get((row["engine"], row["argument"])) != row["line"]:
            raise ValueError("国家参数样例不匹配")
        if version_contracts.is_115() and row["ast_context"] != _ast_context(
            (root / row["source"]).read_bytes(), row["source"], row["argument"], row["line"]
        ):
            raise ValueError("国家参数AST语境不匹配")


def main():
    from . import vanilla_index  # noqa: PLC0415 - 仅生成证据需要索引

    parser = argparse.ArgumentParser(description="从锁定原版生成国家接口补充证据")
    parser.add_argument("--write", action="store_true", required=True)
    parser.parse_args()
    index = vanilla_index.snapshot_index()
    if index is None:
        raise ValueError("缺少冻结精简快照")
    evidence = extract(country_state.load(), config.GAME, index.sections)
    evidence_file().write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    main()
