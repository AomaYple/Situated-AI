"""Current package inputs and frozen output checks."""

from __future__ import annotations

import hashlib
import json
import re

import pytest

from pdx import config, decisions, distribution
from pdx.situated import network_profile, production_profile, r2_reader_authority


@pytest.mark.integration
def test_current_delivery_is_deterministic_and_includes_its_thumbnail():
    _, _, files = distribution.package_inputs()
    assert distribution.package_inputs()[2] == files
    metadata = json.loads(files[distribution.METADATA_NAME])
    thumbnail = metadata["picture"]
    assert thumbnail == distribution.THUMBNAIL_NAME
    assert files[thumbnail] == (decisions.PRODUCT / thumbnail).read_bytes()
    assert all("probe" not in name.lower() for name in files)


def test_standard_lock_pins_policy_reader_authority_and_actual_source_bytes():
    lock = json.loads(distribution.generation_lock({}))
    for source in (
        production_profile.declaration_path(),
        network_profile.source_path(),
        config.REPO / "src/pdx/situated/r2_reader_authority.py",
    ):
        relative = source.relative_to(config.REPO).as_posix()
        assert lock["sources"][relative] == hashlib.sha256(source.read_bytes()).hexdigest()
    # Exact installed reader bytes are verified at materialization, while the
    # standard generation lock pins the Python declaration that authorizes them.
    assert {source for source in lock["sources"] if source.startswith("game/")} == set()
    assert r2_reader_authority.source_hashes()


@pytest.mark.integration
def test_current_delivery_emits_exact_signed_envelope_bounds(engineering_release_inputs):
    _, _, files = engineering_release_inputs
    # These fields were rejected by the game's fixed-point script-value reader.
    expected = {
        "common/ai_strategies/00_default_strategy.txt": (
            ("f5f8d2ca42dfbbf3", "min", "0.7"),
            ("033ceb9fe07b5f3a", "min", "0.54"),
        ),
        "common/technology/technologies/10_production.txt": (("553bc8d5c9e38810", "max", "1.44"),),
        "common/technology/technologies/20_military.txt": (
            ("1d516438f109c7d8", "max", "1.33"),
            ("764df038985e1421", "max", "1.3"),
            ("4ee411a6dd1da959", "max", "1.42"),
        ),
        "common/technology/technologies/30_society.txt": (
            ("9bbe3ab00bd4d6a1", "max", "1.18"),
            ("36bccecef4292ce1", "max", "1.18"),
            ("4c1ee1986328a279", "max", "1.2"),
            ("3683d4824b307f15", "max", "1.24"),
            ("0c4b871f17b4fa87", "max", "1.16"),
            ("dfd3a65f5100e04d", "max", "1.18"),
            ("93c7ec520ab4190a", "max", "1.16"),
            ("8bc267ba16e88ca8", "max", "1.18"),
            ("a1930806182e1ee3", "max", "1.16"),
            ("2c1016b3d3a97089", "max", "1.16"),
        ),
    }
    errors = {}
    for path, bounds in expected.items():
        script = files[path]
        assert isinstance(script, str)
        actions = dict(
            re.findall(
                r"# ACTION program_([0-9a-f]+) \[joint\][^\n]*\n(.*?)"
                r"(?=\n\t\t} }\n)",
                script,
                re.DOTALL,
            )
        )
        for action, bound, literal in bounds:
            match = re.search(rf"^\s*{bound} = (\S+)$", actions.get(action, ""), re.MULTILINE)
            actual = match[1] if match else None
            if actual != literal:
                errors[path, action, bound] = (actual, literal)
    assert errors == {}
