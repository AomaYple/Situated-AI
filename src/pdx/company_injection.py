"""Original first-score projection for the locked basic-company database."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import TYPE_CHECKING

from .model import Block, Scalar
from .parser import parse_text
from .situated import engine_scope

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from .decision_adapters import InitialValue
    from .decision_rules import RuleSet

SOURCE = "common/company_types/99_basic_companies.txt"
OUTPUT = "common/company_types/zz_sitai_company_ai_weights.txt"
DEFINE_SOURCE = "common/defines/00_ai.txt"
DEFINE = ("NAI", "COMPANY_TYPE_DEFAULT_BASE_WEIGHT")
# These engine defines are outside the consumer adapter inputs but are within
# the installation database. Pin them to rule out an additional company default.
_ENGINE_DEFINE_HASHES = {
    "common/defines/jomini/00_tooltips.txt": "0ba5c20ffd675bbac121e523e7a331471917d2b1fedbf114340bfeef3dfd9f65",
    "common/defines/jomini/fog_of_war.txt": "826a7b72365ca156576c28cede9eda2f658650f11d71775054b2252c0c88ba96",
    "common/defines/jomini/rivers.txt": "3f32f8f08695325dc47fb8fbb914fcd055fd4604aa4c20211afcfa490eef1c01",
}


def _root(inputs: Mapping[str, str], source: str) -> Block:
    parsed = parse_text(inputs[source], source)
    if parsed.parse_status != "complete":
        raise ValueError(f"Company injection input is not fully parsed: {source}")
    return parsed.root


def _block(root: Block, key: str, *, prefix: str | None = None) -> Block:
    matches = root.all(key)
    if (
        len(matches) != 1
        or matches[0].op != "="
        or matches[0].prefix != prefix
        or not isinstance(matches[0].value, Block)
    ):
        raise ValueError(f"{key}: expected one {prefix or 'ordinary'} block")
    return matches[0].value


def in_company_database(source: str) -> bool:
    return "/common/company_types/" in f"/{source.casefold()}"


def verify_database_sources(game: Path, locked_sources: Iterable[str]) -> None:
    """Reject new company definitions and defines outside the locked adapter snapshot."""

    def relevant(source: str) -> bool:
        source = source.casefold()
        return (
            in_company_database(source) or "/common/defines/" in f"/{source}"
        ) and source.endswith(".txt")

    locked = {source for source in locked_sources if relevant(source)}
    locked.update(_ENGINE_DEFINE_HASHES)
    actual = {
        path.relative_to(game).as_posix(): path
        for path in game.rglob("*.[tT][xX][tT]")
        if relevant(path.relative_to(game).as_posix())
    }
    if actual.keys() != locked or any(
        not path.is_file() or path.resolve() != path.absolute() for path in actual.values()
    ):
        raise ValueError("Company or define database source set changed")
    for source, expected in _ENGINE_DEFINE_HASHES.items():
        if hashlib.sha256(actual[source].read_bytes()).hexdigest() != expected:
            raise ValueError(f"Engine define source changed: {source}")


def make_shell(
    policy: RuleSet,
    selected: frozenset[str],
    initializers: Sequence[InitialValue],
    inputs: Mapping[str, str],
) -> str:
    """Check the entire native path's write set and synthesize the authored fields."""
    proof = json.loads(engine_scope.company_default_snapshot())
    authority = {row["id"]: row["line"] for row in proof["implicit_companies"]}
    fields = {(company, "ai_weight") for company in authority}
    if (
        not fields
        or any(re.fullmatch(r"company_[a-z0-9_]+", key) is None for key in authority)
        or {rule.field for rule in policy.rules} != fields
        or set(policy.groups(selected)) != fields
        or selected != {rule.domain for rule in policy.rules}
        or Counter(item.field for item in initializers) != Counter(fields)
        or any(
            (item.source, item.define_source, item.define) != (SOURCE, DEFINE_SOURCE, DEFINE)
            for item in initializers
        )
    ):
        raise ValueError("Company injection must cover exactly the locked first-score fields")

    baseline = _root(inputs, SOURCE)
    for company, line in authority.items():
        parent = baseline.first(company)
        block = _block(baseline, company)
        if parent is None or parent.line != line or block.all("ai_weight"):
            raise ValueError(f"{company}: native identity changed or ai_weight already present")
    for source in inputs:
        if source == SOURCE or not in_company_database(source):
            continue
        competing = authority.keys() & set(_root(inputs, source).keys())
        if competing:
            raise ValueError(f"Competing company definition in {source}: {sorted(competing)}")

    definitions = _block(_root(inputs, DEFINE_SOURCE), DEFINE[0])
    score = definitions.all(DEFINE[1])
    if (
        len(score) != 1
        or score[0].op != "="
        or score[0].prefix is not None
        or not isinstance(score[0].value, Scalar)
        or score[0].value.quoted
        or score[0].value.text != "1"
    ):
        raise ValueError("Company default differs from the proven scalar 1")
    for source in inputs:
        if source == DEFINE_SOURCE or "/common/defines/" not in f"/{source.casefold()}":
            continue
        if any(
            isinstance(namespace.value, Block) and namespace.value.all(DEFINE[1])
            for namespace in _root(inputs, source).all(DEFINE[0])
        ):
            raise ValueError(f"Competing company default in {source}")
    return "".join(
        f"{company} = {{\n\tai_weight = {{ value = 1 }}\n}}\n" for company in sorted(authority)
    )


def render_injections(text: str, policy: RuleSet) -> str:
    """Add INJECT to the authored shells and verify the complete output shape."""
    text = re.sub(r"(?m)^(company_[a-z0-9_]+)(?= = \{)", r"INJECT:\1", text)
    output = _root({OUTPUT: text}, OUTPUT)
    companies = {rule.field[0] for rule in policy.rules}
    if len(output.items) != len(companies) or set(output.keys()) != companies:
        raise ValueError("Rendered company identifiers differ from the policy")
    for company in companies:
        target = _block(output, company, prefix="INJECT")
        if len(target.items) != 1:
            raise ValueError(f"{company}: unexpected company property")
        score = _block(target, "ai_weight")
        first = score.first("value")
        if (
            first is None
            or first.op != "="
            or first.prefix is not None
            or not isinstance(first.value, Scalar)
            or first.value.quoted
            or first.value.text != "1"
        ):
            raise ValueError(f"{company}: generated score missed its base")
    return "# Situated AI company candidate scores\n" + text
