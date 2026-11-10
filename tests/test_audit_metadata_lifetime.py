"""One audit owns its decoded candidate; reuse cannot authorize other bytes."""

from __future__ import annotations

import hashlib
import json
from typing import Any, cast

import pytest
import test_support_native_binding as fixtures

from pdx.situated import audit, native_treatments

pytestmark = pytest.mark.unit
METADATA = ".metadata/metadata.json"


def _candidate():
    return cast("Any", fixtures.controlled_output).__wrapped__()


def _scope(raw):
    factory = getattr(native_treatments, "_AuditMetadata", None)
    assert factory is not None, "candidate metadata needs one byte-bound audit lifetime"
    return factory(raw)


def test_scoped_metadata_is_decoded_once_without_skipping_the_real_writer_checks(monkeypatch):
    generated = _candidate()
    raw = generated[METADATA].encode()
    generated[METADATA] = raw
    loads = json.loads
    decodes = []

    def counted(value, *args, **kwargs):
        if value == raw or value == raw.decode():
            decodes.append(value)
        return loads(value, *args, **kwargs)

    monkeypatch.setattr(json, "loads", counted)
    scope = _scope(raw)
    binding = audit._production_continuous_bindings(generated, _metadata=scope)[0]
    # These readers use the same document after the strict support entry point.
    assert scope.document(raw)["default_field_owners"] == {
        "diplomatic_play_support": "situated_kernel"
    }
    assert audit._production_continuous_bindings(generated, _metadata=scope) == (binding,)
    assert len(decodes) == 1
    assert binding.metadata_sha256 == hashlib.sha256(raw).hexdigest()
    generated[fixtures.SOURCE] += "\n\t\t# SITAI BEGIN diplomatic_play_support\n"
    with pytest.raises(ValueError, match=r"支持|连续"):
        audit._production_continuous_bindings(generated, _metadata=scope)


def test_scoped_metadata_cannot_be_reused_for_other_candidate_bytes():
    generated = _candidate()
    raw = generated[METADATA].encode()
    scope = _scope(raw)
    original = {**generated, METADATA: raw}
    assert len(audit._production_continuous_bindings(original, _metadata=scope)) == 1
    document = json.loads(raw)
    document["default_field_owners"]["diplomatic_play_support"] = "legacy"
    generated[METADATA] = json.dumps(document).encode()
    with pytest.raises(ValueError):
        audit._production_continuous_bindings(generated, _metadata=scope)
    # The independent default path must re-read and reject the changed owner too.
    with pytest.raises(ValueError, match="owner"):
        audit._production_continuous_bindings(generated)


def test_separate_audits_do_not_share_mutable_decoded_metadata():
    raw = b'{"country_state":{"enabled":true},"enabled_modules":["country_state"]}'
    first = _scope(raw).document(raw)
    second = _scope(raw).document(raw)
    first["country_state"]["enabled"] = False
    first["enabled_modules"].clear()
    assert second == {
        "country_state": {"enabled": True},
        "enabled_modules": ["country_state"],
    }


def test_decoded_caller_document_cannot_authorize_unrelated_candidate_bytes():
    from types import SimpleNamespace

    generated = _candidate()
    document = json.loads(generated[METADATA])
    forged = SimpleNamespace(
        document=lambda *_args, **_kwargs: document,
        sha256=lambda raw: hashlib.sha256(raw).hexdigest(),
    )
    generated[METADATA] = b"{}"
    with pytest.raises(ValueError):
        audit._production_continuous_bindings(generated, _metadata=cast("Any", forged))


def test_mutating_a_projection_cannot_authorize_the_unchanged_bad_candidate():
    generated = _candidate()
    document = json.loads(generated[METADATA])
    document["default_field_owners"]["diplomatic_play_support"] = "legacy"
    raw = json.dumps(document).encode()
    generated[METADATA] = raw
    scope = _scope(raw)
    projected = scope.document(raw, utf8_text=True)
    projected["default_field_owners"]["diplomatic_play_support"] = "situated_kernel"
    with pytest.raises(ValueError, match="owner"):
        audit._production_continuous_bindings(generated, _metadata=scope)


@pytest.mark.parametrize(
    ("raw", "cause"),
    [
        (b"\xff", UnicodeDecodeError),
        (b"\xef\xbb\xbf{}", json.JSONDecodeError),
        ("{} 快照".encode("utf-16"), UnicodeDecodeError),
        (b"{", json.JSONDecodeError),
        (b"[]", AttributeError),
        (b"null", AttributeError),
        (5, TypeError),
    ],
)
def test_independent_support_metadata_keeps_strict_decode_and_type_failures(raw, cause):
    with pytest.raises(ValueError) as failure:
        audit._production_continuous_bindings({METADATA: raw})
    assert isinstance(failure.value.__cause__, cause)


def test_native_byte_reader_does_not_relax_the_later_strict_utf8_entry():
    raw = '{"country_state":{}}'.encode("utf-16")
    scope = _scope(raw)
    assert scope.document(raw) == {"country_state": {}}
    with pytest.raises(ValueError) as failure:
        audit._production_continuous_bindings({METADATA: raw}, _metadata=scope)
    assert isinstance(failure.value.__cause__, UnicodeDecodeError)


def test_byte_metadata_hash_does_not_encode_a_second_full_unicode_copy():
    class Decoded(str):
        def encode(self, *args, **kwargs):
            raise AssertionError("byte input must be hashed without a full Unicode re-encoding")

    class Encoded(bytes):
        def decode(self, *args, **kwargs):
            return Decoded(super().decode(*args, **kwargs))

    generated = _candidate()
    raw = Encoded(generated[METADATA].encode())
    generated[METADATA] = raw
    binding = audit._production_continuous_bindings(generated)[0]
    assert binding.metadata_sha256 == hashlib.sha256(raw).hexdigest()
