"""原版离线路径索引的覆盖回归。"""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pdx import vanilla_index


def test_snapshot_path_dirs_covers_scriptable_assets_and_dlc(tmp_path: Path) -> None:
    (tmp_path / "common" / "buildings").mkdir(parents=True)
    (tmp_path / "common" / "buildings" / "x.txt").write_text(
        "x = { y = 1 }\n", encoding="utf-8", newline="\n"
    )
    (tmp_path / "gui").mkdir()
    (tmp_path / "gui" / "x.gui").write_text("window = { }\n", encoding="utf-8", newline="\n")
    (tmp_path / "gfx" / "interface" / "icons").mkdir(parents=True)
    (tmp_path / "gfx" / "interface" / "icons" / "x.dds").write_bytes(b"dds")
    (tmp_path / "dlc" / "dlc_alpha" / "gfx").mkdir(parents=True)
    (tmp_path / "dlc" / "dlc_alpha" / "gfx" / "x.asset").write_text(
        "entity = { }\n", encoding="utf-8", newline="\n"
    )

    paths = vanilla_index.snapshot_sections(tmp_path)[vanilla_index.SECTION_PATHS]

    assert "common/buildings" in paths
    assert "gui" in paths
    assert "gfx" in paths
    assert "dlc/dlc_alpha" in paths
    assert "common/buildings/x.txt" in paths["common/buildings"]
    assert "gui/x.gui" in paths["gui"]
    assert "gfx/interface/icons/x.dds" in paths["gfx"]
    assert "dlc/dlc_alpha/gfx/x.asset" in paths["dlc/dlc_alpha"]


def test_script_value_accessors_collect_only_calls_from_script_value_sources(
    tmp_path: Path,
) -> None:
    source = tmp_path / "common" / "script_values" / "sample.txt"
    source.parent.mkdir(parents=True)
    source.write_text(
        'sample = { value = "ROOT.economic_dependence(scope:target_country)" }\n'
        '# ignored = "commented_api(scope:target_country)"\n',
        encoding="utf-8",
        newline="\n",
    )
    unrelated = tmp_path / "common" / "scripted_effects" / "sample.txt"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text(
        'sample = { value = "unrelated_api(scope:target_country)" }\n',
        encoding="utf-8",
        newline="\n",
    )

    assert vanilla_index.script_value_accessors(source.parent) == {"economic_dependence"}


def test_snapshot_script_value_accessor_missing_domain_is_uncovered(tmp_path: Path) -> None:
    index = vanilla_index.VanillaIndex(source="snapshot", game=tmp_path, sections={})
    assert index.script_value_accessors() is None

    index = vanilla_index.VanillaIndex(
        source="snapshot",
        game=tmp_path,
        sections={
            vanilla_index.SECTION_SCRIPT_VALUE_ACCESSORS: {
                vanilla_index.SCRIPT_VALUE_ACCESSOR_DIR: ["economic_dependence"]
            }
        },
    )
    assert index.script_value_accessors() == {"economic_dependence"}


@pytest.mark.property
@given(order=st.permutations(("zeta", "alpha", "beta")))
def test_snapshot_sections_are_invariant_to_file_creation_order(order: list[str]) -> None:
    with TemporaryDirectory() as temporary:
        game = Path(temporary)
        for root, names in ((game / "first", order), (game / "second", reversed(order))):
            effects = root / "common/scripted_effects"
            effects.mkdir(parents=True)
            for name in names:
                (effects / f"{name}.txt").write_text(
                    f"{name} = {{ nested = yes }}\n", encoding="utf-8"
                )

        sections = vanilla_index.snapshot_sections(game / "first")
        assert sections == vanilla_index.snapshot_sections(game / "second")
        assert sections[vanilla_index.SECTION_KEYS]["common/scripted_effects"] == [
            "alpha",
            "beta",
            "zeta",
        ]
        assert sections[vanilla_index.SECTION_VOCABULARY]["common/scripted_effects"] == [
            "alpha",
            "beta",
            "nested",
            "zeta",
        ]


@pytest.mark.property
@settings(max_examples=24)
@given(name=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=12))
def test_game_and_snapshot_variable_pools_only_admit_literal_writes(name: str) -> None:
    with TemporaryDirectory() as temporary:
        game = Path(temporary)
        effects = game / "common/scripted_effects"
        effects.mkdir(parents=True)
        (effects / "writes.txt").write_text(
            f"effect = {{ set_variable = {{ name = local_{name} }} }}\n"
            "set_variable = { name = ROOT.dynamic }\n"
            "set_variable = { name = { invalid = yes } }\n"
            "set_variable = { value = { name = nested_lookalike } }\n"
            "set_variable = yes\n"
            "set_global_variable = { name = global_lookalike }\n",
            encoding="utf-8",
        )
        events = game / "events"
        events.mkdir()
        (events / "writes.txt").write_text(
            f'set_variable = {{ name = "event_{name}" }}\n', encoding="utf-8"
        )

        live = vanilla_index.game_index(game)
        assert live is not None
        snapshot = vanilla_index.VanillaIndex(
            source="snapshot", game=game, sections=vanilla_index.snapshot_sections(game)
        )
        expected = {f"local_{name}", f"event_{name}"}
        assert live.variables() == expected
        assert snapshot.variables() == expected
