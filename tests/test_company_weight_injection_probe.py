"""Static and synthetic checks for the standalone company-score probe."""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest

from pdx import decision_adapters, decision_rules
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler, engine_scope, pdx_eval
from pdx.textio import text_bytes
from tools.probes import company_weight_injection as probe

if TYPE_CHECKING:
    from pdx.model import Node

pytestmark = pytest.mark.unit
OTHER = "common/company_types/00_unmanaged.txt"
UNMANAGED = 'company_fixture_only = { fixture_dummy = "keep#}}" ai_weight = { value = -2 } }'


def _ast(node: Node | None) -> object:
    if isinstance(node, Scalar):
        return node.text, node.quoted
    if isinstance(node, Assignment):
        return node.key, node.op, node.prefix, _ast(node.value)
    if isinstance(node, Block):
        return tuple(_ast(item) for item in node.items)
    return None


@pytest.fixture(scope="module")
def fixture():
    adapters = decision_adapters.load()
    authority = json.loads(engine_scope.company_default_snapshot())
    company_ids = sorted(row["id"] for row in authority["implicit_companies"])
    baseline = "".join(
        f'{company} = {{ fixture_dummy = "keep#}}" fixture_repeat = 9 fixture_repeat = 4 }}\n'
        for company in company_ids
    )
    policy = replace(
        dict(adapters.policies)[probe.SOURCE],
        baseline_sha256=hashlib.sha256(baseline.encode()).hexdigest(),
    )
    fixture_adapters = replace(
        adapters,
        policies=tuple(
            (source, policy if source == probe.SOURCE else item)
            for source, item in adapters.policies
        ),
    )
    words = {
        word
        for reader in policy.readers
        for word in (
            reader.engine,
            *reader.path,
            reader.argument,
            *(part for _, part in reader.parameters),
        )
        if word is not None
    }
    return fixture_adapters, {
        "inputs": {
            probe.SOURCE: baseline,
            probe.DEFINE_SOURCE: "NAI = { COMPANY_TYPE_DEFAULT_BASE_WEIGHT = 1 }",
            OTHER: UNMANAGED,
        },
        "authority_lines": {company: line for line, company in enumerate(company_ids, 1)},
        "reader_words": frozenset(words),
        "model": compiler.load_model(),
    }


def test_original_payload_matches_synthetic_legacy_scores_and_preserves_base(fixture):
    adapters, params = fixture
    payload = probe.render(adapters, **params)
    assert payload == probe.render(adapters, **params)
    assert set(payload) == {probe.OUTPUT}
    text = payload[probe.OUTPUT]
    injected = parse_text(text)
    native = parse_text(params["inputs"][probe.SOURCE] + params["inputs"][OTHER])
    assert injected.parse_status == "complete"
    assert len(injected.top_assignments) == len(params["authority_lines"]) == 26
    assert "fixture_dummy" not in text
    assert "fixture_only" not in text

    original = _ast(native.root)
    policy = dict(adapters.policies)[probe.SOURCE]
    policy, _ = compiler.compile_policy(policy, probe.SOURCE, params["model"])
    synthetic_with_initializers = params["inputs"][probe.SOURCE].replace(
        "fixture_dummy", "ai_weight = { value = 1 } fixture_dummy"
    )
    legacy_text = decision_rules.patch(
        synthetic_with_initializers,
        policy,
        baseline=params["inputs"][probe.SOURCE],
        default_strategy=False,
        reader_words=params["reader_words"],
        consumer_ir=params["model"].consumer_ir,
        consumer_source=probe.SOURCE,
    )
    legacy = parse_text(legacy_text)
    for operation in injected.top_assignments:
        assert operation.prefix == "INJECT"
        assert isinstance(operation.value, Block)
        assert len(operation.value.items) == 1
        score = operation.value.first(probe.SCORE)
        assert score is not None
        assert isinstance(score.value, Block)
        base = score.value.first("value")
        assert base is not None
        assert _ast(base.value) == ("1", False)
        expected = legacy.root.first(operation.key)
        assert expected is not None
        assert isinstance(expected.value, Block)
        assert _ast(score) == _ast(expected.value.first(probe.SCORE))

        target = native.root.first(operation.key)
        assert target is not None
        assert isinstance(target.value, Block)
        native_fields = _ast(target.value)
        assert not target.value.all(probe.SCORE)
        target.value.items.append(score)
        removed = target.value.items.pop()
        assert removed is score
        assert _ast(target.value) == native_fields
    assert _ast(native.root) == original

    key = "company_basic_textiles.ai_weight"
    start = text.index(f"# SITAI BEGIN information:{key}")
    end = text.index(f"# SITAI END information:{key}", start)
    program = "\n".join(text[start:end].splitlines()[1:])
    assert pdx_eval.select(program, {"ROOT": {"is_ai": False}}).operation is None
    assert pdx_eval.select(program, {"ROOT": {"is_ai": True}}).delta == 1
    known: dict[str, Any] = {"is_ai": True}
    for reader in policy.readers:
        current = known
        for step in reader.path:
            current = current.setdefault(step, {})
        value = -1 if reader.key == "country_goods_clothes_balance" else None
        if reader.parameters:
            current.setdefault(reader.engine, {})[tuple(reader.parameters)] = value
        else:
            current[reader.engine] = value
    assert pdx_eval.select(program, {"ROOT": known}).delta == pytest.approx(1.12)


@pytest.mark.parametrize(
    ("new_score", "error"),
    [
        ("ai_weight = {}", "already present"),
        ("ai_weight = { value = 0 }", "already present"),
        ("ai_weight = { value = -2 }", "already present"),
        ("ai_weight = { value = 4 }", "already present"),
        ("ai_weight = 1", "already present"),
        ("ai_weight > 1", "already present"),
    ],
)
def test_rejects_every_explicit_score(fixture, new_score, error):
    adapters, params = fixture
    inputs = dict(params["inputs"])
    inputs[probe.SOURCE] = inputs[probe.SOURCE].replace(
        "fixture_dummy", f"{new_score} fixture_dummy", 1
    )
    with pytest.raises(ValueError, match=error):
        probe.render(adapters, **{**params, "inputs": inputs})


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ("missing", "exactly one ordinary block"),
        ("duplicate", "exactly one ordinary block"),
        ("foreign_override", "Competing definition"),
        ("shadowed_default", "exactly one definition"),
        ("changed_default", "proven scalar 1"),
        ("escaped_path", "非法交付路径"),
        ("aliased_path", "大小写冲突"),
    ],
)
def test_rejects_incomplete_or_competing_sources(fixture, change, error):
    adapters, params = fixture
    inputs = dict(params["inputs"])
    company = min(params["authority_lines"])
    match change:
        case "missing":
            inputs[probe.SOURCE] = inputs[probe.SOURCE].replace(company, "company_other", 1)
        case "duplicate":
            inputs[probe.SOURCE] += f"{company} = {{}}\n"
        case "foreign_override":
            inputs[OTHER] += f"\nREPLACE:{company} = {{}}\n"
        case "shadowed_default":
            inputs["common/defines/zz_other.txt"] = inputs[probe.DEFINE_SOURCE]
        case "changed_default":
            inputs[probe.DEFINE_SOURCE] = inputs[probe.DEFINE_SOURCE].replace("= 1", "= 2")
        case "escaped_path":
            inputs["common/../bad.txt"] = ""
        case "aliased_path":
            inputs[probe.OUTPUT.upper()] = ""
    with pytest.raises(ValueError, match=error):
        probe.render(adapters, **{**params, "inputs": inputs})


def test_rejects_unaccounted_writer_or_initializer(fixture):
    adapters, params = fixture
    authority = dict(params["authority_lines"])
    del authority[min(authority)]
    with pytest.raises(ValueError, match="cover exactly"):
        probe.render(adapters, **{**params, "authority_lines": authority})

    policy = dict(adapters.policies)[probe.SOURCE]
    competing = replace(adapters, policies=(*adapters.policies, (OTHER, policy)))
    with pytest.raises(ValueError, match="Competing policy writer"):
        probe.render(competing, **params)

    model = params["model"]
    bundle = model.consumer_ir
    assert bundle is not None
    writer = next(writer for writer in bundle.writers if writer.source == probe.SOURCE)
    duplicate_ir = replace(model, consumer_ir=replace(bundle, writers=(*bundle.writers, writer)))
    with pytest.raises(ValueError, match="Compiler writers"):
        probe.render(adapters, **{**params, "model": duplicate_ir})


def test_disabled_policy_produces_no_payload(fixture):
    adapters, params = fixture
    disabled = replace(
        adapters,
        policies=tuple(
            (
                source,
                replace(policy, enabled_domains=frozenset()) if source == probe.SOURCE else policy,
            )
            for source, policy in adapters.policies
        ),
    )
    assert probe.render(disabled, **params) == {}


def test_rejects_installation_read_drift(fixture, tmp_path, monkeypatch):
    adapters, params = fixture
    game = tmp_path / "game"
    executable = tmp_path / "binaries/victoria3.exe"
    executable.parent.mkdir()
    executable.touch()
    reader_source = "common/probe_readers.txt"
    reader_text = " ".join(sorted(params["reader_words"]))
    inputs = {**params["inputs"], reader_source: reader_text}
    for source, text in inputs.items():
        path = game / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    snapshot_adapters = replace(
        adapters,
        native_authority_sha256=None,
        sources=tuple(
            (source, hashlib.sha256(text.encode()).hexdigest()) for source, text in inputs.items()
        ),
    )
    monkeypatch.setattr(decision_adapters, "load", lambda: snapshot_adapters)
    monkeypatch.setattr(compiler, "load_model", lambda: params["model"])
    monkeypatch.setattr(probe.r2_reader_authority, "verify_installation", lambda _: {})
    monkeypatch.setattr(
        engine_scope,
        "company_default_snapshot",
        lambda: json.dumps(
            {
                "implicit_companies": [
                    {"id": company, "line": line}
                    for company, line in params["authority_lines"].items()
                ]
            }
        ).encode(),
    )
    monkeypatch.setattr(
        engine_scope,
        "company_snapshot",
        lambda: json.dumps({"script_hashes": {probe.SOURCE: "", OTHER: ""}}).encode(),
    )
    monkeypatch.setattr(
        engine_scope,
        "company_default_evidence",
        lambda _game, _raw: engine_scope.CompanyScopeEvidence(True, ()),
    )

    render_candidate = probe.render

    def render_then_change(*args, **kwargs):
        result = render_candidate(*args, **kwargs)
        (game / reader_source).write_text(reader_text + " updated", encoding="utf-8")
        return result

    assert probe.render_installation(tmp_path) == probe.render(snapshot_adapters, **params)
    monkeypatch.setattr(probe, "render", render_then_change)
    with pytest.raises(ValueError, match="bytes changed"):
        probe.render_installation(tmp_path)


def test_verify_candidate_binds_archive_member_and_installation(tmp_path, monkeypatch):
    archive_path = tmp_path / "candidate.zip"
    score = "INJECT:company_fixture = {\n\tai_weight = { value = 1\n\t}\n}\n"
    member = text_bytes(score, game=True)
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(probe.OUTPUT, member)
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    monkeypatch.setattr(probe, "FROZEN_SHA256", digest)
    monkeypatch.setattr(probe, "MEMBER_SHA256", hashlib.sha256(member).hexdigest())
    assert probe.verify_candidate(archive_path) == digest

    installation = tmp_path / "installation"

    def render(root):
        assert root == installation
        return {probe.OUTPUT: score.replace("value = 1\n", "value = 1 \n")}

    monkeypatch.setattr(probe, "render_installation", render)
    assert probe.verify_candidate(archive_path, installation) == digest
    monkeypatch.setattr(probe, "render_installation", lambda _: {probe.OUTPUT: score + "# drift"})
    with pytest.raises(ValueError, match="Installation render differs"):
        probe.verify_candidate(archive_path, installation)
    monkeypatch.setattr(probe, "MEMBER_SHA256", "wrong")
    with pytest.raises(ValueError, match="company member differs"):
        probe.verify_candidate(archive_path)
    with archive_path.open("ab") as stream:
        stream.write(b"extra")
    with pytest.raises(ValueError, match="frozen D08 candidate"):
        probe.verify_candidate(archive_path)
