"""原版离线路径索引的覆盖回归。"""

from pathlib import Path

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
