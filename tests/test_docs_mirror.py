"""看守游戏自带官方 ``.md`` 的**清单与指纹**。

为什么不再直接比对镜像
----------------------
``research/official-docs/`` 曾是 92 篇官方 ``.md`` 的逐字镜像，**现已移出
版本控制** —— 那是 Paradox 的版权内容，而本仓库是 Apache-2.0 公开仓库。
入库的是 ``research/official-docs.manifest.json``（92 篇的路径/字节/行数/sha256，
约 17 KB）：哈希与文件名是事实，不是创作内容，而镜像的**功能价值**
（检测「Paradox 改了官方文档」）全部由它承载。

这个测试拆成两半，各自对应一种环境：

* **有游戏** → 拿清单比对本体：Paradox 动过哪几篇，立刻看得出来。
  这比以前更强 —— 以前只有「镜像 vs 本体」一条路，现在**任意克隆**都能查。
* **有本地镜像**（本机就有，只是不入库）→ 再比一次镜像，保证本地那份没坏。

历史背景（这条不能删）
----------------------
镜像的**时效性不是自动的**。真实踩过一次：``treaty_articles.md`` 的镜像停在
1.14.2（25,364 B / 604 行），而 1.14.3 本体已增至 28,171 B / 648 行 ——
新增的 ``scope:other_country``、``requirement_to_maintain`` 等规则镜像里没有，
**照镜像写条约 mod 会漏掉这些规则**，而当时没有任何断言会响。
清单机制正是为了让这类漂移**在任意机器上**都能被发现。

清单过期时怎么办
----------------
``v3 mirror write`` 重新生成清单（要游戏）；``v3 mirror --sync`` 顺便把
本地镜像从游戏重拷一份。清单里的字节与行数要同步进
``docs/victoria3-modding/07-官方文档索引.md`` —— 那两个数字由 ``v3 verify``
的 ``docs.total_bytes`` / ``docs.max_bytes`` 看守。
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

import pytest
import typer

from pdx import config, docs_mirror

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

#: 官方 .md 的篇数。1.14.3 实测 92（game 91 + jomini 1）；1.14.4 实测 94（game 93 + jomini 1）。
EXPECTED_DOCS = 94


def test_清单存在且可读() -> None:
    data = docs_mirror.load_manifest()
    assert data, f"读不到 {docs_mirror.MANIFEST_NAME} —— 跑 `v3 mirror write` 生成"
    got = docs_mirror.entries(data)
    assert len(got) == EXPECTED_DOCS, f"清单里有 {len(got)} 篇，预期 {EXPECTED_DOCS}"
    assert data.get("版本"), "清单必须记录生成时的游戏版本，否则不知道它属于哪一版"


def test_清单每条都带指纹() -> None:
    for key, meta in docs_mirror.entries().items():
        assert meta.get("sha256"), f"{key} 缺 sha256"
        assert len(str(meta["sha256"])) == 64, f"{key} 的 sha256 长度不对"
        assert int(str(meta.get("字节", 0))) > 0, f"{key} 的字节数不合理"
        assert int(str(meta.get("行数", 0))) > 0, f"{key} 的行数不合理"
        assert key.split("/", 1)[0] in {"game", "jomini", "clausewitz"}, (
            f"{key} 少了内容根前缀 —— 不同内容根下同名相对路径会互相覆盖"
        )


def test_清单不含原文(tmp_path: Path) -> None:
    """清单**只能**是元数据 —— 一旦有人把正文写进去，版权问题就回来了。"""
    path = docs_mirror.manifest_path()
    size = path.stat().st_size
    assert size < 100_000, f"清单 {size:,} 字节，太大了 —— 多半混进了原文"
    text = path.read_text(encoding="utf-8")
    assert "l_english" not in text, "清单里出现了文档正文"


def test_清单自己不含易变字段(tmp_path: Path) -> None:
    """生成必须**可复现**：同一次扫描跑两遍要逐字节相同。

    时间戳、绝对路径这类东西一旦写进去，清单每次生成都不同，
    diff 就成了噪声，而且会在别人的机器上假报「变了」。
    """
    a = json.dumps(docs_mirror.build_manifest(), ensure_ascii=False, sort_keys=True)
    b = json.dumps(docs_mirror.build_manifest(), ensure_ascii=False, sort_keys=True)
    if not (config.GAME / "common").is_dir():
        pytest.skip("游戏目录不可用")
    assert a == b, "两次生成的清单不同 —— 混进了易变字段"
    assert str(config.REPO) not in a, "清单里出现了本机绝对路径"


def test_镜像目录不在版本控制里() -> None:
    """原文必须**不被跟踪** —— 这是这次改动的全部意义。

    用 ``git ls-files`` 问 git 本人，而不是读 .gitignore 猜：
    忽略规则写对了但文件仍在索引里，是这类改动最常见的半成品状态。
    """
    out = subprocess.run(
        ["git", "ls-files", "research/official-docs"],
        cwd=config.REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.stdout.strip() == "", (
        f"research/official-docs 里还有被跟踪的文件：{out.stdout.splitlines()[:3]}"
    )


# ── 以下两条要读游戏本体或本地镜像，本机没有时自动跳过 ──────
_game = pytest.mark.skipif(not (config.GAME / "common").is_dir(), reason="游戏目录不可用")
_mirror = pytest.mark.skipif(
    not config.OFFICIAL_DOCS_MIRROR.is_dir(), reason="本地镜像不存在（它已不入库）"
)


@pytest.mark.integration
@_game
def test_清单与本机游戏一致() -> None:
    """**核心**：清单必须能描述本机的官方文档。

    失败通常意味着游戏升级后 Paradox 改了官方文档 —— 那就重新生成清单
    （``v3 mirror write``），并同步 ``07-官方文档索引.md`` 里的字节/行数。
    """
    diff = docs_mirror.diff_against_game()
    assert not diff, "清单与本机游戏不一致：\n  " + "\n  ".join(diff[:10])


@pytest.mark.integration
@_mirror
def test_本地镜像与清单一致() -> None:
    """本地那份镜像（不入库）必须与清单逐字节相符。"""
    diff = docs_mirror.diff_mirror()
    assert not diff, "本地镜像与清单不符：\n  " + "\n  ".join(diff[:10])


# ── 合成目录：不碰游戏，纯逻辑 ──────────────────────────────
def _fake_roots(tmp_path: Path) -> Path:
    """造一个假的「游戏安装」：两个内容根，各放一篇 .md。"""
    game = tmp_path / "game"
    jomini = tmp_path / "jomini"
    (game / "common").mkdir(parents=True)
    (jomini / "docs").mkdir(parents=True)
    (game / "common" / "a.md").write_bytes("甲\n".encode())
    # 与 game 侧**同名相对路径** —— 这正是键必须带根前缀的原因
    (jomini / "docs" / "a.md").write_bytes("乙\n".encode())
    return tmp_path


def test_键带内容根前缀否则同名文件互相覆盖(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _fake_roots(tmp_path)
    monkeypatch.setattr(
        docs_mirror,
        "_ROOTS",
        (("game", fake / "game"), ("jomini", fake / "jomini")),
    )
    assert [k for k, _ in docs_mirror.iter_docs()] == ["game/common/a.md", "jomini/docs/a.md"]


def test_镜像里的多余文件会被发现(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Paradox 删过文档，或 ``--sync`` 之前留下的陈迹。

    只查「清单里的篇目在不在镜像里」是**单向**的：镜像里多出来的那篇
    永远不会被发现，而它恰恰是过期最多、最容易被当成真的那份。
    """
    fake = _fake_roots(tmp_path)
    mirror = tmp_path / "mirror"
    monkeypatch.setattr(
        docs_mirror,
        "_ROOTS",
        (("game", fake / "game"), ("jomini", fake / "jomini")),
    )
    monkeypatch.setattr(config, "OFFICIAL_DOCS_MIRROR", mirror)
    manifest = docs_mirror.build_manifest()

    (mirror / "game" / "common").mkdir(parents=True)
    (mirror / "game" / "common" / "a.md").write_bytes("甲\n".encode())
    diff = docs_mirror.diff_mirror(manifest)
    assert any("镜像缺篇：jomini/docs/a.md" in d for d in diff), diff

    (mirror / "jomini" / "docs").mkdir(parents=True)
    (mirror / "jomini" / "docs" / "a.md").write_bytes("乙\n".encode())
    (mirror / "game" / "common" / "陈旧.md").write_bytes("丙\n".encode())
    diff = docs_mirror.diff_mirror(manifest)
    assert diff == ["镜像多余：game/common/陈旧.md"], (
        f"应只报多余文件，实际 {diff} —— 逐字相符的篇目不该报"
    )


def test_内容改动与字节数篡改都会被抓(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """sha256 是这里唯一的判据 —— 字节数相同但内容不同也必须报。"""
    fake = _fake_roots(tmp_path)
    mirror = tmp_path / "mirror"
    monkeypatch.setattr(docs_mirror, "_ROOTS", (("game", fake / "game"),))
    monkeypatch.setattr(config, "OFFICIAL_DOCS_MIRROR", mirror)
    manifest = docs_mirror.build_manifest()

    (mirror / "game" / "common").mkdir(parents=True)
    (mirror / "game" / "common" / "a.md").write_bytes("乙\n".encode())
    assert docs_mirror.diff_mirror(manifest) == ["镜像与清单不符：game/common/a.md"]


# ── 门禁语义：跑不了的检查不该把退出码弄脏 ──────────────────
def _run_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, manifest: bool, mirror: bool
) -> int:
    from pdx import cli

    research = tmp_path / "research"
    research.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "RESEARCH", research)
    monkeypatch.setattr(config, "GAME", tmp_path / "没有这个目录")
    # _ROOTS 在 import 期就把 config.GAME 绑死了，必须一起换成不存在的目录，
    # 否则 build_manifest() 会去扫**真的**游戏，测试结果就取决于本机装没装游戏。
    monkeypatch.setattr(docs_mirror, "_ROOTS", (("game", tmp_path / "没有这个目录"),))
    if manifest:
        # 顺序要紧：先换 _ROOTS，再生成本就为空的清单
        (research / docs_mirror.MANIFEST_NAME).write_text(
            json.dumps(docs_mirror.build_manifest(), ensure_ascii=False), encoding="utf-8"
        )
    if mirror:
        (tmp_path / "镜").mkdir(exist_ok=True)
    monkeypatch.setattr(
        config, "OFFICIAL_DOCS_MIRROR", tmp_path / "镜" if mirror else tmp_path / "无"
    )
    code = 0
    try:
        cli.mirror_check()
    except typer.Exit as exc:  # 一致性检查通过时 typer 不抛异常，那就是 0
        code = int(exc.exit_code or 0)
    return code


def test_没有游戏也没有镜像时不算通过(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """两条比对都跑不成 → 退出码 2（用法错），**不是** 0。

    空过比误报更危险：CI 上它会一直绿着，而实际上什么都没查。
    """
    assert _run_check(monkeypatch, tmp_path, manifest=True, mirror=False) == 2


def test_没有游戏但有镜像时只看镜像(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """没有游戏的那条**跳过**，不该把退出码弄成 1。

    旧实现里「跳过」只是不打印，``against_game`` 那 92 条「删除」
    照样进了退出码判断 —— 于是任何没装游戏的机器上这个门禁永远是红的。
    """
    assert _run_check(monkeypatch, tmp_path, manifest=True, mirror=True) == 0


def test_清单缺失时明确报错(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert _run_check(monkeypatch, tmp_path, manifest=False, mirror=True) == 2


# ── 生成与漂移检测 ──────────────────────────────────────────
def test_写清单可复现且能重读(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """写出来的清单必须能被 ``load_manifest`` 原样读回，且两次生成逐字节相同。

    清单是**入库**文件，它的 diff 就是「Paradox 改了哪些文档」的审计记录 ——
    生成过程只要掺进一点不确定性（时间戳、遍历顺序），这份记录就废了。
    """
    fake = _fake_roots(tmp_path)
    research = tmp_path / "research"
    monkeypatch.setattr(docs_mirror, "_ROOTS", (("game", fake / "game"),))
    monkeypatch.setattr(config, "RESEARCH", research)

    first = docs_mirror.write_manifest()
    assert first == research / docs_mirror.MANIFEST_NAME
    raw1 = first.read_bytes()
    docs_mirror.write_manifest()
    assert first.read_bytes() == raw1, "两次生成的清单不同 —— 混进了易变字段"

    assert set(docs_mirror.entries()) == {"game/common/a.md"}
    assert docs_mirror.diff_against_game() == [], "刚生成就报不一致，说明读写口径不同源"


def test_游戏侧三种漂移都能报出来(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """清单的**全部价值**就在这里：Paradox 改了、加了、删了文档，都要看得出来。"""
    fake = _fake_roots(tmp_path)
    base = fake / "game"
    monkeypatch.setattr(docs_mirror, "_ROOTS", (("game", base),))
    frozen = docs_mirror.build_manifest()  # 相当于入库的那份清单

    (base / "common" / "a.md").write_bytes("甲改了\n".encode())
    (base / "common" / "新.md").write_bytes("新\n".encode())
    diff = docs_mirror.diff_against_game(frozen)
    assert any(d.startswith("内容变了：game/common/a.md") for d in diff), diff
    assert any(d.startswith("新增：game/common/新.md") for d in diff), diff

    (base / "common" / "a.md").unlink()
    assert docs_mirror.diff_against_game(frozen) == [
        "删除：game/common/a.md",
        "新增：game/common/新.md（4 字节）",
    ]


def test_清单为空时提示重新生成(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """空清单不能静默返回「一致」—— 那等于把没查当成查过了。"""
    monkeypatch.setattr(docs_mirror, "_ROOTS", (("game", tmp_path / "没有"),))
    diff = docs_mirror.diff_against_game({})
    assert len(diff) == 1, diff
    assert "mirror write" in diff[0], f"提示里要给出真正的命令名：{diff[0]}"


def test_同步镜像会逐字节拷贝(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``v3 mirror write --sync``：把原文从游戏拷到本机镜像（本机那份不入库）。"""
    from pdx import cli

    fake = _fake_roots(tmp_path)
    research = tmp_path / "research"
    mirror = tmp_path / "mirror"
    monkeypatch.setattr(
        docs_mirror, "_ROOTS", (("game", fake / "game"), ("jomini", fake / "jomini"))
    )
    monkeypatch.setattr(config, "RESEARCH", research)
    monkeypatch.setattr(config, "GAME", fake)
    monkeypatch.setattr(config, "OFFICIAL_DOCS_MIRROR", mirror)

    cli.mirror_write(sync=True)

    assert (mirror / "game/common/a.md").read_bytes() == b"\xe7\x94\xb2\n"
    assert (mirror / "jomini/docs/a.md").read_bytes() == b"\xe4\xb9\x99\n"
    assert docs_mirror.diff_mirror() == [], "刚同步完就报不一致"
