"""Launcher evidence must prove an enabled exact deployment, not a text mention."""

from __future__ import annotations

import hashlib
import json
import zipfile
from typing import TYPE_CHECKING

import pytest

from pdx.situated import architecture_receipts as receipts

if TYPE_CHECKING:
    from pathlib import Path


def _artifact(root: Path, name: str, value: object) -> dict[str, str]:
    path = root / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def test_delivery_accepts_the_actual_escaped_windows_json_pointer(tmp_path, monkeypatch):
    """Exercise the delivery gate, retaining the other enabled Mod unchanged."""
    deployed = tmp_path / "Situated AI"
    deployed.mkdir()
    payload = b"candidate={weight=1}\n"
    (deployed / "fixture.txt").write_bytes(payload)
    package = tmp_path / "package.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("fixture.txt", payload)
    package_sha = hashlib.sha256(package.read_bytes()).hexdigest()
    checksum = tmp_path / "package.zip.sha256"
    checksum.write_text(f"{package_sha}  package.zip\n", encoding="utf-8")
    launcher = tmp_path / "content_load.json"
    launcher.write_text(
        json.dumps(
            {
                "enabledMods": [
                    {"path": str(tmp_path / "unrelated-workshop-mod")},
                    {"path": str(deployed)},
                ],
                "disabledDLC": [],
            }
        ),
        encoding="utf-8",
    )
    original = launcher.read_bytes()
    identity = {
        "merge_commit": "a" * 40,
        "tag_commit": "a" * 40,
        "tag": "v-test",
        "pull_request_url": "https://example.org/pr/1",
        "release_url": "https://example.org/release/v-test",
        "workshop_url": "https://example.org/workshop/1",
    }
    snapshot_hash = "b" * 64
    publication = {
        **identity,
        "plan_version": "A2",
        "source_snapshot_sha256": snapshot_hash,
        "ci_status": "passed",
        "status": "published",
    }
    delivery = {
        **identity,
        "status": "verified",
        "publication_result": _artifact(tmp_path, "publication.json", publication),
        "zip": {"path": package.name, "sha256": package_sha},
        "checksum": {
            "path": checksum.name,
            "sha256": hashlib.sha256(checksum.read_bytes()).hexdigest(),
        },
        "deployment": {
            "root": str(deployed),
            "launcher": {
                "path": str(launcher),
                "sha256": hashlib.sha256(original).hexdigest(),
            },
        },
        "workshop_copy": _artifact(tmp_path, "workshop.json", {}),
        "rollback_instructions": _artifact(tmp_path, "rollback.json", {}),
        "cleanup_result": _artifact(
            tmp_path, "cleanup.json", {"status": "complete", "remaining": []}
        ),
    }
    # Package semantics are separately verified by the production validator;
    # this regression isolates the real delivery gate's launcher responsibility.
    monkeypatch.setattr(receipts, "_package_contract", lambda _: None)
    assert receipts._delivery(tmp_path, delivery, snapshot_hash) == []
    assert launcher.read_bytes() == original


@pytest.mark.parametrize("bom", [False, True])
def test_json_pointer_accepts_native_and_forward_separators(tmp_path, bom):
    target = tmp_path / "Situated AI"
    target.mkdir()
    launcher = tmp_path / "content_load.json"
    for spelling in (str(target), target.as_posix(), str(target / ".." / target.name)):
        launcher.write_text(
            json.dumps({"enabledMods": [{"path": spelling}]}),
            encoding="utf-8-sig" if bom else "utf-8",
        )
        assert receipts.launcher_points_at_deployment(launcher, target)


@pytest.mark.parametrize(
    "fault",
    [
        "prefix_directory",
        "child_directory",
        "disabled_mods",
        "unrelated_field",
        "nested_enabled_mods",
        "non_path_field",
        "relative_path",
        "missing_directory",
        "bad_json",
        "wrong_root_type",
        "wrong_enabled_type",
        "wrong_entry_type",
        "wrong_path_type",
        "duplicate_enabled_key",
        "duplicate_path_key",
    ],
)
def test_json_pointer_rejects_mentions_and_ambiguous_or_invalid_inputs(tmp_path, fault):
    target = tmp_path / "Situated AI"
    target.mkdir()
    nearby = tmp_path / "Situated AI old"
    nearby.mkdir()
    child = target / "nested"
    child.mkdir()
    pointer = {"path": str(target)}
    data: object = {"enabledMods": [pointer]}
    if fault == "prefix_directory":
        data = {"enabledMods": [{"path": str(nearby)}]}
    elif fault == "child_directory":
        data = {"enabledMods": [{"path": str(child)}]}
    elif fault == "disabled_mods":
        data = {"enabledMods": [], "disabledMods": [pointer]}
    elif fault == "unrelated_field":
        data = {"enabledMods": [], "description": str(target)}
    elif fault == "nested_enabled_mods":
        data = {"metadata": {"enabledMods": [pointer]}}
    elif fault == "non_path_field":
        data = {"enabledMods": [{"name": str(target)}]}
    elif fault == "relative_path":
        data = {"enabledMods": [{"path": target.name}]}
    elif fault == "missing_directory":
        data = {"enabledMods": [{"path": str(tmp_path / "missing")}]}
    elif fault == "wrong_root_type":
        data = [pointer]
    elif fault == "wrong_enabled_type":
        data = {"enabledMods": pointer}
    elif fault == "wrong_entry_type":
        data = {"enabledMods": [str(target)]}
    elif fault == "wrong_path_type":
        data = {"enabledMods": [{"path": [str(target)]}]}
    text = json.dumps(data)
    if fault == "bad_json":
        text = text[:-1]
    elif fault == "duplicate_enabled_key":
        text = '{"enabledMods":[],"enabledMods":[' + json.dumps(pointer) + "]}"
    elif fault == "duplicate_path_key":
        value = json.dumps(str(target))
        text = '{"enabledMods":[{"path":"wrong","path":' + value + "}]}"
    launcher = tmp_path / "content_load.json"
    launcher.write_text(text, encoding="utf-8")
    assert not receipts.launcher_points_at_deployment(launcher, target)


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ('name="Situated AI"\npath="{target}"\n', True),
        ('path="{target}/../Situated AI"\n', True),
        ('path="{target} old"\n', False),
        ('# path="{target}"\nname="unrelated"\n', False),
        ('name="{target}"\npath="wrong"\n', False),
        ('container={{path="{target}"}}\n', False),
        ('path="wrong"\npath="{target}"\n', False),
        ('path>"{target}"\n', False),
        ('REPLACE:path="{target}"\n', False),
        ('path="{target}\n', False),
    ],
)
def test_legacy_descriptor_requires_one_top_level_path_assignment(tmp_path, template, expected):
    target = tmp_path / "Situated AI"
    target.mkdir()
    (tmp_path / "Situated AI old").mkdir()
    launcher = tmp_path / "launcher.mod"
    launcher.write_text(template.format(target=target.as_posix()), encoding="utf-8")
    assert receipts.launcher_points_at_deployment(launcher, target) is expected


def test_pointer_rejects_unknown_format_and_missing_launcher(tmp_path):
    target = tmp_path / "Situated AI"
    target.mkdir()
    launcher = tmp_path / "description.txt"
    launcher.write_text(f'path="{target.as_posix()}"\n', encoding="utf-8")
    assert not receipts.launcher_points_at_deployment(launcher, target)
    assert not receipts.launcher_points_at_deployment(tmp_path / "missing.json", target)
