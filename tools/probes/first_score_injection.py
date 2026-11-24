"""Render original first-score property patches for isolated game probes."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pdx import decision_adapters, decision_rules, distribution
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

DEFINE_SOURCE = "common/defines/00_ai.txt"


@dataclass(frozen=True, slots=True)
class Projection:
    source: str
    output: str
    database: str
    id_prefix: str
    field: str
    define: tuple[str, str]
    default: str
    header: str


def _in_database(source: str, directory: str) -> bool:
    return f"/common/{directory}/" in f"/{source.casefold()}"


def _root(text: str, source: str) -> Block:
    parsed = parse_text(text, source)
    parsed.require_complete()
    return parsed.root


def _block(root: Block, key: str, *, prefix: str | None = None) -> Assignment:
    matches = root.all(key)
    if (
        len(matches) != 1
        or matches[0].op != "="
        or matches[0].prefix != prefix
        or not isinstance(matches[0].value, Block)
    ):
        raise ValueError(f"{key}: expected exactly one {prefix or 'ordinary'} block")
    return matches[0]


def _initial_score(inputs: Mapping[str, str], define: tuple[str, str], expected: str) -> str:
    occurrences: list[tuple[str, Assignment, Assignment]] = []
    for source, text in inputs.items():
        if not _in_database(source, "defines"):
            continue
        root = _root(text, source)
        for namespace in root.all(define[0]):
            if isinstance(namespace.value, Block):
                occurrences.extend(
                    (source, namespace, item) for item in namespace.value.all(define[1])
                )
    if len(occurrences) != 1:
        raise ValueError("Default score must have exactly one definition")
    source, namespace, assignment = occurrences[0]
    value = assignment.value
    if (
        source != DEFINE_SOURCE
        or _block(_root(inputs[DEFINE_SOURCE], DEFINE_SOURCE), define[0]) != namespace
        or assignment.op != "="
        or assignment.prefix is not None
        or not isinstance(value, Scalar)
        or value.quoted
        or value.text != expected
    ):
        raise ValueError(f"Default score differs from the proven scalar {expected}")
    return value.text


def render(
    projection: Projection,
    adapters: decision_adapters.AdapterSet,
    *,
    inputs: Mapping[str, str],
    authority_lines: Mapping[str, int],
    reader_words: frozenset[str],
    model: compiler.SituatedModel,
) -> dict[str, str]:
    """Compile the authorized first direct score fields from one input snapshot."""
    distribution._validate_paths([*inputs, projection.output])
    policies = [policy for source, policy in adapters.policies if source == projection.source]
    if len(policies) != 1:
        raise ValueError("Expected one policy for the entire native file")
    policy = policies[0]
    fields = {(definition, projection.field) for definition in authority_lines}
    if not fields or any(
        not re.fullmatch(projection.id_prefix + r"[a-z0-9_]+", key) for key in authority_lines
    ):
        raise ValueError("Invalid definition identifier or empty authority")
    declared = {rule.field for rule in policy.rules}
    initializers = [item for item in adapters.initial_values if item.source == projection.source]
    expected = Counter(
        decision_adapters.InitialValue(projection.source, field, DEFINE_SOURCE, projection.define)
        for field in fields
    )
    if Counter(initializers) != expected or declared != fields:
        raise ValueError("Rules and initializers must cover exactly the proven fields")

    active = set(policy.groups())
    if not active:
        return {}
    if active != fields or policy.enabled_domains != {rule.domain for rule in policy.rules}:
        raise ValueError("Partial migration would leave writers at the original path")

    for source, field, _ in decision_adapters.writes(adapters):
        if (
            source != projection.source
            and _in_database(source, projection.database)
            and field
            and field[0] in authority_lines
        ):
            raise ValueError(f"Competing policy writer for {field[0]} at {source}")

    bundle = model.consumer_ir
    if bundle is None:
        raise ValueError("Missing compiler IR")
    writers = Counter(
        (writer.kind, writer.definition, writer.field)
        for writer in bundle.writers
        if writer.source == projection.source
    )
    if writers != Counter(("rule_action", rule.id, ".".join(rule.field)) for rule in policy.rules):
        raise ValueError("Compiler writers differ from the policy")
    for writer in bundle.writers:
        if (
            writer.source != projection.source
            and _in_database(writer.source, projection.database)
            and writer.field.split(".", 1)[0] in authority_lines
        ):
            raise ValueError(f"Competing compiler writer for {writer.field}")

    baseline = inputs[projection.source]
    root = _root(baseline, projection.source)
    for definition, line in authority_lines.items():
        parent = _block(root, definition)
        assert isinstance(parent.value, Block)
        if parent.line != line or parent.value.all(projection.field):
            raise ValueError(
                f"{definition}: native position changed or {projection.field} already present"
            )
    for source, text in inputs.items():
        if source == projection.source or not _in_database(source, projection.database):
            continue
        overlap = authority_lines.keys() & set(_root(text, source).keys())
        if overlap:
            raise ValueError(f"Competing definition in {source}: {', '.join(sorted(overlap))}")

    score = _initial_score(inputs, projection.define, projection.default)
    # The compiler edits synthesized containers. The verified native source only
    # supplies the baseline digest and the field absence check above.
    shell = "".join(
        f"{definition} = {{\n\t{projection.field} = {{ value = {score} }}\n}}\n"
        for definition in sorted(authority_lines)
    )
    compiled, _ = compiler.compile_policy(policy, projection.source, model)
    rendered = decision_rules.patch(
        shell,
        compiled,
        baseline=baseline,
        default_strategy=False,
        reader_words=reader_words,
        consumer_ir=bundle,
        consumer_source=projection.source,
    )
    rendered = re.sub(rf"(?m)^({projection.id_prefix}[a-z0-9_]+)(?= = \{{)", r"INJECT:\1", rendered)
    output = _root(rendered, projection.output)
    if len(output.items) != len(fields) or set(output.keys()) != authority_lines.keys():
        raise ValueError("Rendered identifiers differ from authority")
    for definition in authority_lines:
        target = _block(output, definition, prefix="INJECT").value
        assert isinstance(target, Block)
        if len(target.items) != 1:
            raise ValueError(f"{definition}: unexpected data outside {projection.field}")
        _block(target, projection.field)
    return {projection.output: projection.header + "\n" + rendered}


def _database_files(game: Path, directory: str) -> set[str]:
    return {
        path.relative_to(game).as_posix()
        for path in game.rglob("*.[tT][xX][tT]")
        if _in_database(path.relative_to(game).as_posix(), directory)
    }
