from pathlib import Path

from pdx import references


def test_scan_file_resolves_mod_and_reports_missing(tmp_path: Path, monkeypatch) -> None:
    game = tmp_path / "game"
    game.mkdir()
    (game / "gfx").mkdir()
    (game / "gfx" / "known.dds").write_bytes(b"DDS")
    monkeypatch.setattr(references.config, "GAME", game)
    script = tmp_path / "mod" / "common" / "x.txt"
    script.parent.mkdir(parents=True)
    script.write_text(
        'icon = "known"\n sound = "audio/missing.ogg"\n value = "ordinary text"\n',
        encoding="utf-8",
    )
    found, missing = references.scan_file(script, root=script.parents[2])
    assert any(item.value == "known" and item.status == "ok" for item in found)
    assert any(item.value == "audio/missing.ogg" and item.line == 2 for item in missing)
    assert all(item.field in {"icon", "sound"} for item in found)


def test_scan_tree_is_deterministic_and_json_ready(tmp_path: Path) -> None:
    (tmp_path / "a.gui").write_text('layout = "window"\n', encoding="utf-8")
    (tmp_path / "b.txt").write_text("icon = missing_icon\n", encoding="utf-8")
    references_found, unresolved = references.scan_tree(tmp_path)
    files = [str(item["file"]) for item in references_found]
    assert files == sorted(files)
    assert unresolved[0]["value"] == "window"
