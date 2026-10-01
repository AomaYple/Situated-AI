"""`pdx.mods` 的第一层：**哪些目录算「本机的 mod」**。

为什么单独一条用例（backlog **B83**）
-------------------------------------
这一层判错一次，代价不是「统计差一点」，而是**整套 mod 侧断言与文档快照集体算错**，
而且错得看不出来：

* `verify._mods_total()` / `_mods_files()` 就是 `analyse_all()` 的长度与文件数之和。
  我们**自己部署进用户 mod 目录**的那份真 mod 被数进来 ⇒ `mod.total` 23→24、
  `mod.files` 4,777→4,828，而 `v3 verify` 报的是「文档过期」，指向完全错误的方向。
* 同一个坑踩过**两次**（第一次见 `exec/收口清单.md` 那段），第二次还把它判成了
  「用户新订阅了一份 mod」—— 所以修法必须是**结构性的**：认 mod 靠
  `.metadata/metadata.json` 的 `id` 前缀（`OWN_MOD_ID_PREFIX`），**不看目录名**。

为什么不能按目录名认
--------------------
部署目录名 = 各档案 id 按字典序用 `-` 连接（`modgen.metadata_payload`）。
档案集合一增删（6 份 → 8 份），上一版部署的目录就再也匹配不上 ——
这正是下面 `test_档案集合变过之后旧副本仍然认得出来` 钉住的那件事。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import TYPE_CHECKING

import pytest

from pdx import config, modgen, mods

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

#: 批次 2（6 档案）部署时用过的目录名 —— 现在**再也拼不出来**了，但它仍然是我们的。
_STALE_DIR = "au_revolution-cn_intervention-eg_debt-pe_great_game-ru_defeat-tr_defeat"


def _write_metadata(root: Path, ident: str) -> None:
    """给一个假 mod 目录写最小 `.metadata/metadata.json`。"""
    meta = root / mods.METADATA_REL
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text(
        json.dumps({"name": "SITAI 处境档案", "id": ident}, ensure_ascii=False),
        encoding="utf-8",
    )


@pytest.fixture
def 假环境(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """把 `LOCAL_MODS` / `WORKSHOP` 指到临时目录，返回 `(本地, workshop)`。"""
    local = tmp_path / "mod"
    workshop = tmp_path / "workshop"
    local.mkdir()
    workshop.mkdir()
    monkeypatch.setattr(mods.config, "LOCAL_MODS", local)
    monkeypatch.setattr(mods.config, "WORKSHOP", workshop)
    return local, workshop


def test_按id前缀认出我们自己的mod(假环境) -> None:
    local, _ = 假环境
    ours = local / "whatever_name"
    _write_metadata(ours, "sitai.ru_defeat")
    theirs = local / "别人的mod"
    _write_metadata(theirs, "someone_else.mod")
    bare = local / "没有元数据"
    bare.mkdir()

    assert mods.own_mod(ours) is True
    assert mods.own_mod(theirs) is False
    assert mods.own_mod(bare) is False, "没有 metadata 就不能认成我们的"


def test_档案集合变过之后旧副本仍然认得出来(假环境) -> None:
    """**回归**：目录名是上一版档案集合拼的，也必须认得出来。

    这一条就是 B83 的现场：批次 2 留下的 `_STALE_DIR` 在批次 3（8 档案）之后
    既删不掉、又被当成用户订阅的 mod。
    """
    local, _ = 假环境
    stale = local / _STALE_DIR
    _write_metadata(stale, f"sitai.{_STALE_DIR}")

    # 仓库当前那一版是 8 档案 —— 名字不同，但 id 前缀相同。
    current_id = str(modgen.metadata_payload(modgen.load_all())["id"])
    assert _STALE_DIR not in current_id, "旧目录名不该再等于当前的名字（否则这条用例没意义）"
    assert mods.own_mod(stale) is True
    assert _STALE_DIR in [p.name for p in mods.own_mod_dirs()]


def test_自己的mod不计入本机mod统计(假环境) -> None:
    local, workshop = 假环境
    (workshop / "1234567890").mkdir()  # 别人的一个 Workshop mod
    _write_metadata(workshop / "1234567890", "some_workshop_mod")
    (local / "some_real_mod").mkdir()
    _write_metadata(local / "some_real_mod", "handmade.mod")
    _write_metadata(local / _STALE_DIR, f"sitai.{_STALE_DIR}")
    (local / (mods.PROBE_PREFIX + "ab")).mkdir()

    found = sorted(p.name for p in mods.discover_mods())
    assert found == ["1234567890", "some_real_mod"]
    assert _STALE_DIR not in found, "我们自己部署的 mod 不算「本机装了哪些 mod」"
    assert not any(name.startswith(mods.PROBE_PREFIX) for name in found)


def test_只数workshop时本地目录一个都不算(假环境) -> None:
    local, workshop = 假环境
    (workshop / "1234567890").mkdir()
    (local / "some_real_mod").mkdir()

    found = [p.name for p in mods.discover_mods(include_local=False)]
    assert found == ["1234567890"]


def test_own_mod_dirs只给我们的目录(假环境) -> None:
    local, _ = 假环境
    _write_metadata(local / _STALE_DIR, f"sitai.{_STALE_DIR}")
    _write_metadata(local / "别人的mod", "someone_else.mod")
    (local / (mods.PROBE_PREFIX + "ab")).mkdir()
    (local / ".隐藏目录").mkdir()

    assert sorted(p.name for p in mods.own_mod_dirs()) == [
        _STALE_DIR,
        mods.PROBE_PREFIX + "ab",
    ]


def test_命名空间常量只有一份() -> None:
    """生成器与扫描器必须读**同一个**前缀（P9：重复定义即红）。

    扫描器不能 import 生成器（`mods.py` 是被 `analyze / verify / evidence` 共用的
    底层模块），所以常量住在 `config` 里，两边都从那里取。
    """
    assert config.NAMESPACE_PREFIX == "sitai_"
    assert modgen.NAMESPACE_PREFIX is config.NAMESPACE_PREFIX
    assert mods.OWN_MOD_ID_PREFIX == "sitai."


def test_本仓库自己的mod元数据对得上判据() -> None:
    """真产物自检：仓库里那份 `mod/.metadata/metadata.json` 必须能被认成我们自己的。

    这条把「按 id 前缀认」这件事钉在**真实数据**上 —— 判据和产物一起漂是发现不了的，
    所以要拿真产物来对。
    """
    payload = modgen.metadata_payload(modgen.load_all())
    ident = str(payload["id"])
    assert ident.startswith(mods.OWN_MOD_ID_PREFIX)
    assert ident == f"{config.NAMESPACE_PREFIX.rstrip('_')}.{ident.split('.', 1)[1]}"


#: doc 12 的两处版本分布：§7 的表（给人看的）与 §9 第 1 条的散文（给结论看的）。
#: 它们**曾经互相矛盾**（表写 `1.13*` 8 / 空 10，散文写 9 / 9），而且两边都没有看守，
#: 所以只能靠人偶然发现。这条用例把「表 == 现场」钉死，散文那一侧由 §7 反向引用。
_DOC12 = config.DOCS / "12-真实mod解剖与改造面地图.md"
_VER_ROW = re.compile(r"^(1\.[\d.*]*|空)$")


def _doc12_version_table() -> dict[str, int]:
    """解析 doc 12 §7 那张 `supported_game_version` 分布表。"""
    text = _DOC12.read_text(encoding="utf-8")
    assert "## 7. 版本兼容性观察" in text, "doc 12 的 §7 标题变了，这条用例要跟着改"
    section = text.split("## 7. 版本兼容性观察", 1)[1].split("## 8.", 1)[0]
    out: dict[str, int] = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        key = cells[0].strip("`").replace("**", "").strip()
        if not _VER_ROW.fullmatch(key):
            continue
        out[key] = int(cells[1].replace(",", ""))
    return out


def test_doc12_版本分布表与现场一致() -> None:
    """**本机快照类数字也要有看守**（B83 的教训：没有看守的分布数会安静地烂掉）。

    跳过条件：本机没有可发现的 mod（CI 上没有 Workshop 内容）—— 这条测的是
    「文档与**这台机器**一致」，没有 mod 就没有可比的东西，跳过而不是假装通过。
    """
    live = Counter(m.supported_game_version or "空" for m in mods.analyse_all())
    if not live:
        pytest.skip("本机没有可发现的 mod，无从对照（CI 环境正常）")

    got = _doc12_version_table()
    assert got, "§7 那张版本分布表没解析到任何行（表格被改过？）"
    assert got == dict(live), f"doc 12 §7 与现场不符：文档 {got}，现场 {dict(live)}"
    assert sum(got.values()) == len(mods.analyse_all())
