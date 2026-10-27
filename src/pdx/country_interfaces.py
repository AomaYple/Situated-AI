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

from . import config, country_state
from .model import Block, Scalar
from .parser import parse_text
from .textio import normalized_text

EVIDENCE = config.REPO / "research/vanilla-ai/1.14.5/country-interfaces.json"
BASELINE = EVIDENCE.parent / "00_default_strategy.txt"


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _required(policy):
    return (
        {r["engine"] for r in policy.readers.values()}
        | set(country_state.HOOKS)
        | {
            "is_ai",
            "has_variable",
            "set_variable",
            "remove_variable",
            "on_actions",
        }
    )


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
            if key not in country_state.HOOKS or (
                top and relative.startswith("common/on_actions/")
            ):
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


def extract(policy, root, sections):
    """从真实原版建立有限样例，不改写既有快照或原版镜像。"""
    root = Path(root)
    baseline = root / "common/ai_strategies/00_default_strategy.txt"
    try:
        baseline_text = baseline.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise ValueError("缺少锁定游戏原件") from exc
    if normalized_text(baseline_text) != BASELINE.read_text(encoding="utf-8"):
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
    return {
        "schema": 1,
        "evidence": "static_vanilla_examples_not_engine_execution",
        "baseline_sha256": hashlib.sha256(BASELINE.read_bytes()).hexdigest(),
        "snapshot_sections_sha256": _digest(sections),
        "sources": sources,
        "interfaces": found,
        "arguments": [
            {"engine": engine, "argument": argument, **row}
            for (engine, argument), row in sorted(args.items())
        ],
    }


def validate(policy, *, root=None, snapshot=None, evidence_path=EVIDENCE):
    evidence = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
    if (
        not isinstance(evidence, dict)
        or evidence.get("schema") != 1
        or evidence.get("baseline_sha256") != hashlib.sha256(BASELINE.read_bytes()).hexdigest()
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
    if normalized_text(baseline_text) != BASELINE.read_text(encoding="utf-8"):
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
    for row in evidence["arguments"]:
        if observed[row["source"]][1].get((row["engine"], row["argument"])) != row["line"]:
            raise ValueError("国家参数样例不匹配")


def main():
    from . import vanilla_index  # noqa: PLC0415 - 仅生成证据需要索引

    parser = argparse.ArgumentParser(description="从锁定原版生成国家接口补充证据")
    parser.add_argument("--write", action="store_true", required=True)
    parser.parse_args()
    index = vanilla_index.snapshot_index()
    if index is None:
        raise ValueError("缺少冻结精简快照")
    evidence = extract(country_state.load(), config.GAME, index.sections)
    EVIDENCE.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    main()
