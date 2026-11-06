"""Exact receiving-country acceptance cost of a new tier-three transfer.

This candidate uses the documented diplomatic acceptance root, never the
unproven root of principle/identity ai_weight. Registration is intentionally
explicit: no generic field or named-scope permission is granted by this module.
"""

from __future__ import annotations

import hashlib
import json
import math
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pdx import config
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import programs
from pdx.treaty_acceptance_opportunities import AcceptanceProgram

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pdx.decision_rules import Reader
    from pdx.situated.decision_ir import EvaluationContext

SOURCE = "common/diplomatic_actions/28_invite_to_power_bloc.txt"
DOC = "common/diplomatic_actions/diplomatic_action.md"
VALUES = "common/script_values/01_power_bloc_values.txt"
PRINCIPLES = "common/power_bloc_principles/00_power_bloc_principles.txt"
ROLE_DOC = "common/power_bloc_principles/power_bloc_principles.md"
GROUPS = "common/power_bloc_principle_groups/00_power_bloc_principle_groups.txt"
FINANCE = "events/iberia_events/negotiation_events.txt"
FIELD = ("invite_to_power_bloc", "ai", "accept_score")
DEFINITION = "principle_exploit_members_3"
TOKEN = "principle:" + DEFINITION
EXPECTED_SOURCES = {
    "common/diplomatic_actions/28_invite_to_power_bloc.txt": "7ba6eec14beedd93e0e25d734fac937242cf34d31ad0d1a2095d707aa2be7ae2",
    "common/diplomatic_actions/diplomatic_action.md": "9f146dd9e108d9753747efb1bf0671a18e19e728f6916a1fcd58c4d0b76fb69c",
    "common/script_values/01_power_bloc_values.txt": "57ef445cfa211e8c2bd040145997a302183ceb827294e878a87ff76db81bf8fe",
    "common/power_bloc_principles/00_power_bloc_principles.txt": "e92e79a48382503971c6f07d2be2d8fffa85a84c1e0e8dc6a200c7a8f3cce455",
    "common/power_bloc_principles/power_bloc_principles.md": "c24d64cad7f793f6ea585729c89582407410ae2bf458da7b7979115cf59ef7ee",
    "common/power_bloc_principle_groups/00_power_bloc_principle_groups.txt": "ccbf4ca1e9c74d1c5f7799093790057c73c00dd88cc0b625a23aef83018fe544",
    "events/iberia_events/negotiation_events.txt": "f738d3fe8d5d828460033d4d4b6b39437021a7f76dc80a2f9e48620a4cccc6ee",
}
ACTION = "bloc_new_exploitation_transfer_deficit"
FROZEN = config.REPO / "research/vanilla-ai/1.15.0/power-bloc-membership.json"
PARAMETERS = config.REPO / "mod/decisions/power_bloc_membership.toml"


def block(parent: Block, key: str) -> Block:
    rows = parent.all(key)
    if len(rows) != 1 or rows[0].op != "=" or not isinstance(rows[0].value, Block):
        raise ValueError("exact native parent missing: " + key)
    return rows[0].value


def shape(node):
    if isinstance(node, Scalar):
        return ["scalar", node.text, node.quoted]
    if isinstance(node, Assignment):
        return ["assignment", node.key, node.op, node.prefix, shape(node.value)]
    if isinstance(node, Block):
        return ["block", [shape(x) for x in node.items]]
    raise ValueError("native AST contains unsupported node")


def scalar(parent, key, value):
    rows = parent.all(key)
    if (
        len(rows) != 1
        or rows[0].op != "="
        or not isinstance(rows[0].value, Scalar)
        or rows[0].value.unquoted != value
    ):
        raise ValueError("native scalar drift: " + key)


def contains(parent, key, value):
    return any(
        (r.key == key and isinstance(r.value, Scalar) and r.value.unquoted == value)
        or (isinstance(r.value, Block) and contains(r.value, key, value))
        for r in parent.assignments()
    )


def verify(snapshot):
    if snapshot.get("schema") != 1 or set(snapshot["texts"]) != {
        SOURCE,
        DOC,
        VALUES,
        PRINCIPLES,
        ROLE_DOC,
        GROUPS,
        FINANCE,
    }:
        raise ValueError("exact source collection required")
    if snapshot["sources"] != EXPECTED_SOURCES:
        raise ValueError("source collection identity drift")
    roots = {}
    for name, text in snapshot["texts"].items():
        if hashlib.sha256(text.encode()).hexdigest() != snapshot["sources"][name]:
            raise ValueError("source hash drift: " + name)
        if name.endswith(".txt"):
            parsed = parse_text(text)
            if parsed.errors:
                raise ValueError("native source cannot parse: " + name)
            roots[name] = parsed.root
    doc = snapshot["texts"][DOC]
    for required in (
        "# IMPORTANT: In the AI block, the AI country is always root and the other country always scope:target, regardless of who proposed the diplomatic action",
        "accept_score = {} # If this value evaluates to above zero, AI will accept this action if proposed",
    ):
        if required not in doc:
            raise ValueError("acceptance root/consumer documentation drift")
    action = block(roots[SOURCE], FIELD[0])
    scalar(action, "requires_approval", "yes")
    scalar(action, "uses_random_approval", "yes")
    scalar(block(action, "selectable"), "is_power_bloc_leader", "yes")
    scalar(block(block(action, "accept_effect"), "scope:target_country"), "join_power_bloc", "root")
    acceptance = block(block(action, "ai"), "accept_score")
    helpers = [r.value.unquoted for r in acceptance.all("add") if isinstance(r.value, Scalar)]
    if helpers != ["ai_power_bloc_identity_score", "ai_power_bloc_principle_score"]:
        raise ValueError("acceptance helper closure drift")
    helper = block(roots[VALUES], helpers[1])
    expected = parse_text(
        "ai_power_bloc_principle_score = { if = { limit = { scope:actor.power_bloc ?= { has_principle_group = principle_group:principle_group_exploit_members } } add = { desc = \"[GetPowerBlocPrincipleGroup('principle_group_exploit_members').GetName]\" value = -50 } } }"
    ).root
    if shape(helper) != shape(block(expected, helpers[1])):
        raise ValueError("general native exploitation penalty drift")
    # Whole-parent helper closure has no current net-income or default term.
    for parent in (acceptance, *(block(roots[VALUES], h) for h in helpers)):
        for key in ("net_total_income", "in_default"):

            def keys(p):
                for r in p.assignments():
                    yield r.key
                    if isinstance(r.value, Block):
                        yield from keys(r.value)

            if key in set(keys(parent)):
                raise ValueError("native acceptance already prices the same finance cause")
    tier3 = block(roots[PRINCIPLES], DEFINITION)
    scalar(
        block(tier3, "power_bloc_modifier"), "power_bloc_income_transfer_to_leader_factor", "0.05"
    )
    if "# Income transfer from members to leader" not in snapshot["texts"][PRINCIPLES]:
        raise ValueError("income direction evidence drift")
    group = block(roots[GROUPS], "principle_group_exploit_members")
    levels = block(group, "levels")
    if [row.unquoted for row in levels.items if isinstance(row, Scalar)] != [
        "principle_exploit_members_1",
        "principle_exploit_members_2",
        "principle_exploit_members_3",
    ]:
        raise ValueError("level-three principle group closure drift")
    if "net_total_income < 0" not in snapshot["texts"][FINANCE]:
        raise ValueError("own-country current income getter evidence missing")
    # The membership query and actual inviter role are native at this hook.
    if not contains(acceptance, "is_in_same_power_bloc", "scope:actor"):
        raise ValueError("same actual inviter membership comparison missing")
    if not contains(acceptance, "is_in_power_bloc", "yes"):
        raise ValueError("current membership query missing")
    if not contains(acceptance, "has_principle", "principle:principle_sacred_civics_3"):
        raise ValueError("exact inviter-bloc principle getter use missing")
    return roots


def snapshot() -> dict[str, Any]:
    data = json.loads(FROZEN.read_text(encoding="utf-8"))
    verify(data)
    return cast("dict[str, Any]", data)


def source_hashes() -> dict[str, str]:
    return dict(snapshot()["sources"])


def frozen_inputs() -> dict[str, str]:
    return dict(snapshot()["texts"])


def verify_inputs(inputs: Mapping[str, str]) -> None:
    data = snapshot()
    if any(inputs.get(key) != value for key, value in data["texts"].items()):
        raise ValueError("membership complete native input drift")


def dependency_bytes() -> bytes:
    return PARAMETERS.read_bytes() + FROZEN.read_bytes() + Path(__file__).read_bytes()


def tuning() -> float:
    data = tomllib.loads(PARAMETERS.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "cost"}
        or data["schema"] != 1
        or type(data["cost"]) not in {int, float}
        or not math.isfinite(data["cost"])
        or not -5 <= data["cost"] < 0
    ):
        raise ValueError("finite exact membership cost required")
    return float(data["cost"])


@dataclass(frozen=True, slots=True)
class MembershipAcceptanceProgram(AcceptanceProgram):
    """One exact member-transfer acceptance, using the existing sole writer."""

    @property
    def consumer_id(self) -> str:
        return "power_bloc_membership_acceptance"

    @property
    def field_path(self) -> tuple[str, ...]:
        return FIELD

    def validate(self) -> None:
        if self != compile_program():
            raise ValueError("exact membership acceptance program drift")

    def evaluation_context(self) -> EvaluationContext:
        from pdx.situated.decision_ir import ContextBinding, EvaluationContext  # noqa: PLC0415

        return EvaluationContext(
            actor_scope=ContextBinding("root", "country", "actor", DOC, 118),
            auxiliary_scopes=(ContextBinding("actor", "country", "auxiliary", SOURCE, 98),),
            evidence=(
                f"{DOC}:118",
                f"{DOC}:137",
                f"{SOURCE}:64",
                f"{SOURCE}:98",
                f"{SOURCE}:219",
                f"{PRINCIPLES}:1490",
                f"{GROUPS}:171",
            ),
        )

    def readers(self) -> tuple[Reader, ...]:
        from pdx.decision_rules import Reader  # noqa: PLC0415

        return (
            Reader(
                "bloc_membership_income", "net_total_income", "root", "currency_per_week", "number"
            ),
            Reader("bloc_membership_member", "is_in_power_bloc", "root", "boolean", "boolean"),
            Reader("bloc_membership_leader", "is_power_bloc_leader", "actor", "boolean", "boolean"),
            Reader(
                "bloc_membership_tier3",
                "has_principle",
                "actor",
                "boolean",
                "boolean",
                argument=TOKEN,
                path=("power_bloc",),
            ),
        )

    def reader_bindings(self) -> tuple[tuple[str, str, str, str], ...]:
        return tuple(
            (r.key, r.scope, "country", "actor" if r.scope == "root" else "auxiliary")
            for r in self.readers()
        )

    def predicate_ports(self):
        from pdx.decision_rules import Predicate  # noqa: PLC0415
        from pdx.situated import program_ports  # noqa: PLC0415

        return program_ports.bind(
            scalar=self.scalar,
            source=self.source,
            definition=self.definition,
            context=self.evaluation_context(),
            readers=self.readers(),
            reader_bindings=self.reader_bindings(),
            predicates={
                ACTION: tuple(
                    Predicate(*row)
                    for row in (
                        ("bloc_membership_income", "<", 0),
                        ("bloc_membership_member", "=", False),
                        ("bloc_membership_leader", "=", True),
                        ("bloc_membership_tier3", "=", True),
                    )
                )
            },
            guard_roles={ACTION: "cost"},
            source_sha256=hashlib.sha256(dependency_bytes()).hexdigest(),
            source_proofs=tuple(
                f"{key}:sha256={value}" for key, value in sorted(source_hashes().items())
            ),
            domain="diplomacy",
        )

    def port_guards(self):
        return self.predicate_ports().render()

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "writer_id": self.writer_id,
            "consumer_id": self.consumer_id,
            "domain": "diplomacy",
            "operation": "add",
            "vanilla_tail": "preserve",
            "evaluation_context": self.evaluation_context().as_dict(),
            "reader_context_bindings": [list(row) for row in self.reader_bindings()],
            "readers": [asdict(r) for r in self.readers()],
            "source_hashes": source_hashes(),
            "predicate_ports": self.predicate_ports().as_dict(),
        }

    def evaluate(self, values: Mapping[str, Any], *, is_ai: bool, enabled: bool = True) -> float:
        if type(is_ai) is not bool or type(enabled) is not bool:
            raise ValueError("explicit AI and domain boundaries required")
        if not is_ai or not enabled:
            return 0.0
        guards = self.predicate_ports().evaluate(values)
        return programs.evaluate_scalar(self.scalar, guards)


def compile_program() -> MembershipAcceptanceProgram:
    snapshot()
    scalar = programs.ScalarProgram(
        ACTION,
        "add",
        0,
        -5,
        0,
        (
            programs.ScalarGroup(
                "actual_new_member_transfer_financing",
                (programs.ScalarTerm(ACTION, ACTION, tuning()),),
            ),
        ),
    )
    return MembershipAcceptanceProgram(
        scalar, source=SOURCE, field=".".join(FIELD), kind="membership"
    )


def is_membership(program: object) -> bool:
    return type(program) is MembershipAcceptanceProgram


def consumer_catalog() -> dict[str, Any]:
    program = compile_program()
    return {
        "source": SOURCE,
        "definition": program.definition,
        "field": program.field,
        "native_root": "country",
        "actor": "root",
        "actor_role": "receiving_ai_country",
        "inviter_role": "actual_scope_actor_power_bloc_leader",
        "native_unit": "acceptance_score",
        "operation": "add",
        "placement": "after_complete_native_accept_score",
        "scope_evidence": program.evaluation_context().evidence,
        "unknown_policy": "unknown_finance_or_membership_or_actual_inviter=local_exit",
        "cost_basis": "new tier3 member to leader transfer under observed receiving-country deficit; no monetary estimate",
        "source_sha256": source_hashes()[SOURCE],
    }
