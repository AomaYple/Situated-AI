"""本体语言发现、快照恢复和 Mod 路径契约。"""

from __future__ import annotations

import pytest

from pdx.localization_languages import (
    DEFAULT_LANGUAGES,
    discover,
    from_snapshot,
    language_headers,
    localization_path,
    normalize,
)

pytestmark = pytest.mark.unit


def test_锁定版本包含本体的十一种语言():
    assert tuple(language.directory for language in DEFAULT_LANGUAGES) == (
        "braz_por",
        "english",
        "french",
        "german",
        "japanese",
        "korean",
        "polish",
        "russian",
        "simp_chinese",
        "spanish",
        "turkish",
    )
    assert language_headers() == tuple(f"l_{language.directory}" for language in DEFAULT_LANGUAGES)


def test_实际游戏目录按语言头发现而不猜目录名(tmp_path):
    root = tmp_path / "game"
    (root / "localization" / "portuguese").mkdir(parents=True)
    (root / "localization" / "portuguese" / "x.yml").write_text(
        'l_braz_por:\n key:0 "texto"\n', encoding="utf-8", newline="\n"
    )
    found = discover(root)
    assert found[0].directory == "portuguese"
    assert found[0].header == "l_braz_por"
    assert localization_path(found[0], "sitai_decisions") == (
        "localization/portuguese/sitai_decisions_l_portuguese.yml"
    )


def test_快照必须明确给出语言摘要():
    snapshot: dict[str, object] = {"域": {"localization_digest": {"l_english": [], "l_french": []}}}
    assert language_headers(from_snapshot(snapshot)) == ("l_english", "l_french")
    with pytest.raises(ValueError, match="localization_digest"):
        from_snapshot({"域": {}})


def test_语言规范化拒绝空集合和冲突目录():
    with pytest.raises(ValueError, match="至少需要一种"):
        normalize([])


def test_实机发现拒绝重复语言头和同目录多语言头(tmp_path):
    root = tmp_path / "game" / "localization"
    (root / "english").mkdir(parents=True)
    (root / "other").mkdir()
    (root / "english" / "a.yml").write_text("l_english:\n", encoding="utf-8", newline="\n")
    (root / "other" / "b.yml").write_text("l_english:\n", encoding="utf-8", newline="\n")
    with pytest.raises(ValueError, match="多个目录"):
        discover(root.parent)

    (root / "other" / "b.yml").write_text("l_french:\n", encoding="utf-8", newline="\n")
    (root / "english" / "c.yml").write_text("l_french:\n", encoding="utf-8", newline="\n")
    with pytest.raises(ValueError, match="多个语言头"):
        discover(root.parent)
