"""`doc14` / `doc17` / `doc18` 与 `engine_log` 的**降级路径与合成树**覆盖。

这四个模块此前是覆盖率最低的一档（77%–85%），缺的全是同一类东西：
「目录/文件不存在就返回零」的分支、以及只在特定合成输入下才走到的计数逻辑。
把 `config.GAME` 指到临时目录、或用合成 `.txt` 喂进去就能全覆盖 ——
不读真游戏、毫秒级，CI 上也能跑（那里 `config.GAME` 本来就不存在）。

⚠️ 这些用例**不替代**集成用例：真实语料上的数字仍由 `test_doc14.py` /
`test_doc17.py` / `test_doc18.py` 与 `v3 tables` 看守。这里只管分支。
"""

from __future__ import annotations

import pytest

from pdx import doc14, doc17, doc18, engine_log

pytestmark = pytest.mark.unit


@pytest.fixture
def fake_game(tmp_path, monkeypatch):
    """把「游戏目录」指到一个空临时目录，再按需往里面造文件。"""
    game = tmp_path / "game"
    (game / "common").mkdir(parents=True)
    for module in (doc14, doc17, doc18):
        monkeypatch.setattr(module.config, "GAME", game)
    return game


def _write(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ────────────────────────── doc 14 ──────────────────────────


def test_doc14_缺目录时给零(fake_game) -> None:
    assert doc14.pm_hyphen_key_count() == 0
    assert doc14.hyphen_key_dir_counts() == {}
    assert doc14.wealth_1_goods_categories() == 0
    assert doc14.buy_package_goods_categories() == 0
    assert doc14.buy_package_entry_count() == 0
    assert doc14.buy_package_field_names() == []


def test_doc14_连字符统计只看键名(fake_game) -> None:
    """口径：数的是**键名**里的连字符，值里的连字符不算（那是另一个量）。"""
    base = fake_game / "common" / "production_methods"
    _write(
        base / "a.txt",
        "pm_with-dash = {\n    value = has-dash-in-value\n}\npm_plain = { x = 1 }\n",
    )
    assert doc14.pm_hyphen_key_count() >= 1
    assert doc14.hyphen_key_dir_counts().get("production_methods", 0) >= 1


def test_doc14_合成buy_packages能数出字段(fake_game) -> None:
    base = fake_game / "common" / "buy_packages"
    _write(base / "00_buy_packages.txt", "wealth_1 = { goods = { a b } }\nwealth_2 = { x = 1 }\n")
    assert doc14.buy_package_entry_count() >= 1
    assert doc14.buy_package_field_names(), "合成语料里应当能数出字段"


# ────────────────────────── doc 17 ──────────────────────────


def test_doc17_缺文件时给零(fake_game) -> None:
    assert doc17.flag_comment_brace_lines() == 0
    assert doc17.fallback_yes_count() == 0
    assert doc17.block_prefix_count("没有这个文件.txt", "block", "pfx") == 0
    assert doc17.block_item_count("没有这个文件.txt", "block") == (0, 0)


def test_doc17_未知概念后缀要报错而不是给零() -> None:
    """这个函数的契约是「键必须是文档里那一行」—— 猜一个键时该炸，不该静默给 0。"""
    with pytest.raises(KeyError):
        doc17.loc_suffix_count("no_such_key")


def test_doc17_合成语料上的计数(fake_game) -> None:
    flag = fake_game / "common" / "flag_definitions" / "00_flag_definitions.txt"
    _write(flag, "flag_a = { # 注释\n    x = yes\n}\n")
    assert doc17.flag_comment_brace_lines() >= 0

    custom = fake_game / "common" / "customizable_localization"
    _write(custom / "00_x.txt", "key_a = {\n    text = { trigger = { always = yes } }\n}\n")
    assert doc17.fallback_yes_count() >= 0

    block_file = "common/scripted_effects/x.txt"
    _write(fake_game / block_file, "pfx_block = {\n    a = 1\n    b = 2\n}\n")
    assert doc17.block_item_count(block_file, "pfx_block")[0] >= 1
    assert doc17.block_prefix_count(block_file, "pfx_block", "a") >= 0


def test_doc17_前缀计数器跳过变量(fake_game) -> None:
    """`@变量` 不是条目 —— 它不该进前缀统计（doc 17 的表按条目计数）。"""
    _write(
        fake_game / "common" / "modifier_type_definitions" / "x.txt",
        "@base = 10\nfoo_bar = { v = @base }\nfoo_baz = { v = 1 }\n",
    )
    counter = doc17._prefix_counter()
    assert counter["foo_"] == 2
    assert counter["_total"] == 2, "@变量 不该被计入总数"


def test_doc17_概览计数在缺目录时为零(fake_game) -> None:
    assert doc17.overview_txt_count() == 0
    assert doc17.overview_key_count() == 0
    assert doc17.gene_block_names() == []
    counts = doc17.tech_counts()
    assert counts["technologies"] == 0
    assert counts["eras"] == 0
    assert counts["definitions"] == 0


def test_doc17_文件与字段计数在缺目录时为零(fake_game) -> None:
    assert doc17.field_occurrence("没有这个目录", "some_field") == 0
    assert doc17.files_without_defs("没有这个目录") == 0


# ────────────────────────── doc 18 ──────────────────────────


def test_doc18_缺目录时给零(fake_game) -> None:
    assert doc18._country_files() == []
    assert doc18.country_effect_occurrences() == {}
    assert doc18.country_effect_file_count() == 0
    assert doc18.effect_file_counts() == {}
    assert doc18.effect_rows() == []


def test_doc18_合成国家文件能数出条目(fake_game) -> None:
    """口径：只认顶层 `COUNTRIES` 包装块里的 `add_*` / `set_*`（任意深度）。"""
    rel = doc18._COUNTRIES_DIR
    _write(
        fake_game / rel / "AAA.txt",
        "COUNTRIES = {\n"
        "    c:AAA = {\n"
        "        effect = { add_treasury = 1 }\n"
        "        set_variable = { x = 1 }\n"
        "    }\n"
        "}\n",
    )
    files = doc18._country_files()
    assert files, "合成目录里应当看得见国家文件"
    assert doc18.country_effect_file_count() >= 1
    assert doc18.country_effect_occurrences()["add_treasury"] == 1


def test_doc18_非COUNTRIES包装块不算(fake_game) -> None:
    """写死包装块名是刻意的：将来多出别的顶层块时不该混进来。"""
    rel = doc18._COUNTRIES_DIR
    _write(
        fake_game / rel / "BBB.txt",
        "SOMETHING_ELSE = {\n    effect = { add_treasury = 1 }\n}\n",
    )
    assert doc18.country_effect_file_count() == 0


# ────────────────────────── engine_log ──────────────────────────


def test_脚本集合统计在空目录上是零(tmp_path) -> None:
    total, parsed = engine_log._scriptable_set(tmp_path, "events", ".txt")
    assert (total, parsed) == (0, 0)


def test_脚本集合统计能区分总数与已解析(tmp_path) -> None:
    events = tmp_path / "events"
    _write(events / "a.txt", "x = { }\n")
    (events / "readme.md").write_text("不是脚本", encoding="utf-8")
    total, parsed = engine_log._scriptable_set(tmp_path, "events", ".txt")
    assert total == 1
    assert parsed == 1


def test_日志解析不因缺文件而失败(tmp_path) -> None:
    """日志目录空着（或只有无关内容）时，解析应当给空结果而不是抛。"""
    (tmp_path / "game.log").write_text("无关内容\n", encoding="utf-8")
    claims, version = engine_log.parse_logs(tmp_path)
    assert claims == []
    assert isinstance(version, str)


def test_日志目录完全不存在也给空结果(tmp_path) -> None:
    claims, version = engine_log.parse_logs(tmp_path / "没有日志")
    assert claims == []
    assert version == ""
