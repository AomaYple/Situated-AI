"""黄金回归测试：把全量分析的**逐字节产物**冻结下来。

为什么用指纹而不是整份文件
--------------------------
:func:`pdx.analyze.write_reports` 的产物合计约 9 MB，其中
``游戏本体.json`` 一份就有 8.3 MB。把这种体积的文本塞进 git 会让仓库
迅速劣化，因此这里记录每个产物的 ``(字节数, sha256)`` —— 同样能保证
"改一个字节就失败"，但仓库只增加几百字节。

本测试走的是**真实写盘路径**（``write_reports`` 本身），不是自己重新
序列化一遍。否则测试和实现会各自演化，测的就不是真正交付的东西了。

产物写到 ``tmp_path``，不覆盖 ``tools/out/`` 里的正式产物。

更新方式::

    pytest tools/tests/test_golden.py --force-regen

**只在确认新结果确实正确之后才更新** —— 这个文件的唯一价值就是
"结果不该变的时候它会响"。
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import pytest

from pdx import analyze, config

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.integration, pytest.mark.regression, pytest.mark.slow]

#: 正式产物目录，**导入时捕获**。
#: ``analyze.config`` 就是 ``pdx.config`` 模块本身，patch 它是全局生效的，
#: 所以测试内读 ``config.OUT`` 拿到的可能是被改过的值（踩过）。
_OFFICIAL_OUT = config.OUT
_OFFICIAL_REPORTS = config.REPORTS

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def _write_to(out: Path, ga, ma, ca, monkeypatch) -> dict[str, Path]:
    """让 write_reports 落到临时目录，返回真实产物路径。"""
    monkeypatch.setattr(analyze, "GAME_OUT", out / "game")
    monkeypatch.setattr(analyze, "MODS_OUT", out / "mods")
    monkeypatch.setattr(analyze, "CROSS_OUT", out / "cross")
    monkeypatch.setattr(analyze.config, "REPORTS", out / "reports")
    return analyze.write_reports(ga, ma, ca)

@pytest.fixture
def artifacts(tmp_path, ga, ma, ca, monkeypatch) -> dict[str, Path]:
    """跑一次真实写盘。"""
    return _write_to(tmp_path, ga, ma, ca, monkeypatch)

def test_artifact_digests(artifacts, data_regression) -> None:
    """每个产物的字节数与 sha256 必须与冻结值一致。"""
    digests = {
        name: {"字节": p.stat().st_size, "sha256": _sha256(p)}
        for name, p in sorted(artifacts.items())
    }
    assert digests, "至少要有产物"
    data_regression.check(digests)

def test_全部产物都非空(artifacts) -> None:
    for name, p in artifacts.items():
        assert p.is_file(), f"{name} 未落盘"
        assert p.stat().st_size > 0, f"{name} 是空文件"

def test_报告是合法UTF8且无乱码(artifacts) -> None:
    for name, p in artifacts.items():
        raw = p.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), f"{name} 不应带 BOM"
        raw.decode("utf-8")  # 解码失败即失败

def test_重复分析结果逐字节一致(tmp_path, ga, ma, ca, monkeypatch) -> None:
    """确定性：同一份数据写两次必须完全一样。

    否则"快照差分"这种用法就失去意义 —— 每次都会冒出假差异。
    时间戳、集合迭代序、字典插入序都是常见的破坏源。
    """
    a = _write_to(tmp_path / "run1", ga, ma, ca, monkeypatch)
    b = _write_to(tmp_path / "run2", ga, ma, ca, monkeypatch)
    assert sorted(a) == sorted(b)
    for name in a:
        assert _sha256(a[name]) == _sha256(b[name]), f"{name} 两次结果不同"

def test_产物之间不互相混杂(artifacts) -> None:
    """游戏本体、mod、交叉三类产物必须**分文件存放**。

    这是硬性约定：游戏本体数据里不能出现 mod 内容，反之亦然。
    """
    names = set(artifacts)
    assert any("游戏本体" in n for n in names)
    assert any("mod" in n for n in names)
    assert any("交叉" in n for n in names)
    roots = {p.parent.name for p in artifacts.values()}
    assert len(roots) >= 3, f"产物应分属至少 3 个目录，实际 {roots}"

def test_落盘后能被原样读回(artifacts) -> None:
    """JSON 产物必须能被 json 反序列化，Markdown 必须是文本。"""
    for name, p in artifacts.items():
        text = p.read_text(encoding="utf-8")
        if p.suffix == ".json":
            obj = json.loads(text)
            assert isinstance(obj, dict), f"{name} 顶层应为对象"
        else:
            assert text.lstrip().startswith("#"), f"{name} 应是 Markdown"

def test_不污染正式产物目录(artifacts) -> None:
    """测试不应改写 tools/out/ 与 tools/reports/ 里的正式产物。

    这条用来防止 monkeypatch 失效、真的把正式产物覆盖掉。
    """
    for p in artifacts.values():
        assert _OFFICIAL_OUT not in p.parents, f"{p} 落到了正式产物目录"
        assert _OFFICIAL_REPORTS not in p.parents, f"{p} 落到了正式报告目录"
