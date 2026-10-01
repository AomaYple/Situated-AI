"""取证工具的测试（`pdx.evidence`）。

为什么不依赖游戏：`scan_usage` / `mod_hits` 都接受一个**根目录**参数，
`doc_hits` 读的是 ``config.GAME``（测试里 monkeypatch 成临时目录）。
这样这些用例在 CI（没有游戏）上也能跑，覆盖面不靠「本机恰好装了游戏」。

口径性质的断言（这些是工具的立身之本）：
* **注释不算用法** —— ``#foo = 1`` 不能让 foo 出现计数 +1；
* **键与值分开** —— ``type = country_event`` 里的 ``country_event`` 算「作为值」；
* **只扫 `.txt` / `.gui`** —— `.yml` 里的英文散文不算脚本用法；
* **父键链**要能指出它出现在哪个块里（doc 04 §13 的取证就靠这个）。
"""

from __future__ import annotations

import pytest

from pdx import evidence

pytestmark = pytest.mark.unit


def _tree(root):
    """造一棵小语料树：一个键当键、一个键当值、一个只出现在注释里。"""
    (root / "common" / "journal_entries").mkdir(parents=True)
    (root / "events").mkdir(parents=True)
    (root / "localization").mkdir(parents=True)
    (root / "common" / "journal_entries" / "00_test.txt").write_text(
        "je_alpha = {\n"
        "    is_shown_in_lobby = {\n"
        "        always = yes\n"
        "    }\n"
        "    is_shown_in_lobby = { always = no }\n"
        "}\n",
        encoding="utf-8",
    )
    (root / "events" / "test.txt").write_text(
        "ns.1 = {\n"
        "    type = character_event\n"
        "    #orphan = yes\n"
        "    after = { hidden_effect = { add_treasury = 1 } }\n"
        "}\n",
        encoding="utf-8",
    )
    (root / "localization" / "english.yml").write_text(
        'l_english:\n orphanish: "an orphan in the prose"\n', encoding="utf-8"
    )
    return root


def test_键的用法与父键链(tmp_path) -> None:
    usage = evidence.scan_usage(["is_shown_in_lobby"], _tree(tmp_path))
    u = usage["is_shown_in_lobby"]
    assert u.total == 2, "两处都是真用法"
    assert u.files == 1
    assert "common/journal_entries" in u.by_dir
    assert u.parents["je_alpha"] == 2, "父键应当是外层条目名"
    assert any(s.where.endswith("00_test.txt:2") for s in u.samples)


def test_注释不算用法(tmp_path) -> None:
    """doc 04 对 `weight_multiplier` 的判断（「5 处全被注释」）就靠这条性质。"""
    usage = evidence.scan_usage(["orphan"], _tree(tmp_path))
    assert usage["orphan"].total == 0


def test_值单独统计(tmp_path) -> None:
    usage = evidence.scan_usage(["character_event"], _tree(tmp_path))
    u = usage["character_event"]
    assert u.total == 0, "它没有作为键出现过"
    assert u.values == 1, "作为 type 的值出现一次"
    assert u.value_parents["type"] == 1


def test_不扫yml(tmp_path) -> None:
    """`.yml` 是显示文本，里面的词是英文散文（实测搜 orphan 会命中散文）。"""
    usage = evidence.scan_usage(["orphan"], _tree(tmp_path))
    assert all("localization" not in d for d in usage["orphan"].by_dir)


def test_标量取值分布(tmp_path) -> None:
    usage = evidence.scan_usage(["type"], _tree(tmp_path))
    assert usage["type"].scalar_values["character_event"] == 1


def test_官方md命中区分散文与代码(tmp_path, monkeypatch) -> None:
    game = tmp_path / "game"
    game.mkdir()
    (game / "readme.md").write_text(
        "orphan = yes       # 赋值形式\n"
        "see `orphan` here  # 反引号形式\n"
        "an orphan in prose # 散文\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(evidence.config, "GAME", game)
    hits = evidence.doc_hits(["orphan"])["orphan"]
    kinds = sorted(h.kind for h in hits)
    assert kinds == ["散文", "码", "赋值"]
    documented = [h for h in hits if h.is_code]
    assert len(documented) == 2
    assert all(h.where.startswith("readme.md:") for h in hits)


def test_mod命中按次数排序(tmp_path) -> None:
    a = _tree(tmp_path / "mod_a")
    b = _tree(tmp_path / "mod_b")
    hits = evidence.mod_hits(["is_shown_in_lobby"], [a, b])
    assert [name for name, _n in hits["is_shown_in_lobby"]] == ["mod_a", "mod_b"]


def test_gather把四类证据拼起来(tmp_path, monkeypatch) -> None:
    game = _tree(tmp_path / "game")
    monkeypatch.setattr(evidence.config, "GAME", game)

    # 假装没有 victoria3.exe：exe 那一类应当退化成「无字面量」而不是抛异常
    def _no_identifiers() -> frozenset[str]:
        return frozenset()

    def _no_neighbors(keys, span: int = 8) -> dict[str, list[tuple[str, ...]]]:
        del span
        return {k: [] for k in keys}

    monkeypatch.setattr(evidence.exe_strings, "exe_identifiers", _no_identifiers)
    monkeypatch.setattr(evidence.exe_strings, "identifier_neighbors", _no_neighbors)
    (ev,) = evidence.gather(["is_shown_in_lobby"])
    assert ev.key == "is_shown_in_lobby"
    assert ev.vanilla.total == 2
    assert ev.docs == ()
    assert ev.exe_exact is False, "没有 exe 时按「无字面量」处理，不该炸"
    assert "原版键 2 处" in ev.summary
    assert "官方 md 0 处" in ev.summary


def test_目录缺失时是空结果而不是异常(tmp_path) -> None:
    usage = evidence.scan_usage(["whatever"], tmp_path / "does-not-exist")
    assert usage["whatever"].total == 0
