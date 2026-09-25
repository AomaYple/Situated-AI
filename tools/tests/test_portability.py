"""跨平台默认路径的闸门（用户四条原则第三条：Windows / Linux / macOS 都要能跑）。

这一组钉住四件事，缺一个都会以"在我机器上是好的"的方式烂掉：

* **解析链的顺序**：环境变量优先（且**不判存在**）→ 平台候选逐条判存在 → 确定的回落值
  （一条都不存在时也**不抛异常**：`pdx.config` 在没装游戏的机器上照样要被 import）；
* **清单真的按平台给、且都由 `Path.home()` 推出来**：三份清单都能在**假 home** 上核出来
  （用例不必真装游戏、也不受本机影响）；
* **Workshop 由找到 ROOT 的那个 Steam 根推导**，不是第二份平台路径；App ID 只有一个来源；
* **受控 `tools/**/*.py` 里不许再出现机器专属绝对路径** —— 这条闸门要能在有人又写死一个
  用户名时**当场红**（它的阴性对照见 :func:`test_机器路径闸门能被阴性对照撞红`）。

为什么要有这一组：这一条原则原先只是文档里的一句话，而 `config.py` 的三个默认值里就写着
一个**真实账户名**（`tools/probe/**` 的两个采集脚本更写死了整条仓库绝对路径）——
换台机器/换个用户名的代价是"你得先知道要设哪三个环境变量"，而另外两个平台上连
`C:\\Users\\<某人>` 这种形状都不成立。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from pdx import config

pytestmark = pytest.mark.unit

#: 机器专属绝对路径：Windows 用户目录 / Linux home / macOS home。
#: 名字段**不许**以 `<` `>` `{` `}` `%` `$` 开头 —— 那几种是**占位符**（推荐写法），
#: 它们本来就不含任何真实账户名；泛称见 :data:`_GENERIC_NAMES`。
_MACHINE_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]Users[\\/]|/(?:home|Users)/)(?P<name>[^\\/\s\"'()<>{}%$]+)",
)

#: 泛称账户名：不含任何真实账户名，不算违规（`/home/user/...` 是文档里的常见写法）。
_GENERIC_NAMES = frozenset({"user", "username", "you", "me"})


def _machine_paths(text: str) -> list[tuple[int, str]]:
    """文本里的机器专属绝对路径 ⇒ ``[(行号, 命中的那一段), …]``（没有就是空表）。"""
    found: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for match in _MACHINE_PATH.finditer(line):
            if match.group("name") in _GENERIC_NAMES:
                continue
            found.append((number, match.group(0)))
    return found


def _controlled_python_files() -> list[str]:
    """受控（git 跟踪）的 `tools/**/*.py` 清单 —— 用 `git ls-files -z` 拿（转义安全）。

    不用 `rglob`：那会把未入版本控制的临时脚本也算进来；也不用 `git ls-files` 的默认
    输出：非 ASCII 名会被 quote-path 转义成带 `"` 的形式（56 个中文名文件里踩过）。
    """
    proc = subprocess.run(
        ["git", "ls-files", "-z", "--", "tools"],
        cwd=config.REPO,
        capture_output=True,
        check=True,
    )
    names = [raw.decode("utf-8") for raw in proc.stdout.split(b"\x00") if raw]
    return [name for name in names if name.endswith(".py")]


def test_环境变量指向不存在的路径时仍然优先且不炸() -> None:
    """`V3_*` 指到 `Z:/nope`（**不存在**）：三个值就是指定的那串，且 import 不抛异常。

    手法照抄 `tools/tests/test_conftest.py`（子进程 + env 覆盖）—— 那是本仓既有口径，
    也是"CI 里不装游戏"这条路唯一的保证：解析发生在 **import 期**，那一步炸了，
    整套单测连收集都过不去。
    """
    script = (
        "from pdx import config\n"
        "print(config.ROOT)\n"
        "print(config.USERDIR)\n"
        "print(config.WORKSHOP)\n"
        "print(config.GAME)\n"
    )
    env = os.environ.copy()
    env.update({"V3_ROOT": "Z:/nope", "V3_USERDIR": "Z:/nope", "V3_WORKSHOP": "Z:/nope"})
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=config.REPO,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, f"import 期炸了：\n{proc.stderr}"
    nope = Path("Z:/nope")
    assert proc.stdout.splitlines() == [
        str(nope),
        str(nope),
        str(nope),
        str(nope / "game"),
    ]


def test_候选清单里第一个存在的胜出(tmp_path) -> None:
    """候选清单按顺序判存在 ⇒ 先到先得（前面几条不存在不挡路）。"""
    missing = tmp_path / "没有这个"
    second = tmp_path / "second"
    second.mkdir()
    assert config.resolve(None, (missing, second), tmp_path) == second

    first = tmp_path / "first"
    first.mkdir()
    assert config.resolve(None, (first, second), tmp_path) == first, "第一条存在就该赢"


def test_一条都不存在时回落到确定值而不是抛异常(tmp_path) -> None:
    """全不存在 ⇒ 确定的回落值（且 `_first_existing` 如实说"没有"）。"""
    candidates = (tmp_path / "a", tmp_path / "b")
    assert config._first_existing(candidates) is None
    assert config.resolve(None, candidates, tmp_path) == tmp_path

    env = tmp_path / "env-wins"
    assert config.resolve(str(env), candidates, tmp_path) == env, "环境变量连存在都不判"


def test_三份清单都由_home_推导且按平台给() -> None:
    """Windows / Linux / macOS 三份清单：**每一条都在假 home 底下**（不写任何真实用户名）。

    这条就是"不再写死用户名"的机器判据：把 `home` 换成一个不存在的目录，三份清单
    必须整体跟着搬家 —— 只要还有人写死 `C:\\Users\\<某人>`，这条立刻红。
    """
    fake = Path("/fake-home-xyz")

    # Windows
    win_steam = config.steam_roots(home=fake, platform="win32")
    assert all("Steam" in part.name or "SteamLibrary" in part.name for part in win_steam)
    win_user = config.userdir_candidates(home=fake, platform="win32")
    assert win_user == (fake / "Documents" / "Paradox Interactive" / "Victoria 3",)
    win_game = config.game_candidates(home=fake, platform="win32")
    assert win_game[0].parts[-3:] == ("steamapps", "common", "Victoria 3")

    # macOS
    mac_steam = config.steam_roots(home=fake, platform="darwin")
    assert mac_steam == (fake / "Library" / "Application Support" / "Steam",)
    mac_user = config.userdir_candidates(home=fake, platform="darwin")
    assert mac_user == (fake / "Documents" / "Paradox Interactive" / "Victoria 3",)
    assert config.game_candidates(home=fake, platform="darwin")[0].parts[-3:] == (
        "steamapps",
        "common",
        "Victoria 3",
    )

    # Linux：Steam 有三条候选（官方包 / 发行版包 / Flatpak），用户目录走 XDG
    linux_steam = config.steam_roots(home=fake, platform="linux")
    assert len(linux_steam) >= 3
    assert all(path.is_relative_to(fake) for path in linux_steam)
    linux_user = config.userdir_candidates(home=fake, platform="linux")
    assert linux_user[0] == fake / ".local" / "share" / "Paradox Interactive" / "Victoria 3"
    assert all(path.is_relative_to(fake) for path in linux_user)

    # 三份清单里的**每一条**都在假 home 底下（Windows 的候选是绝对盘符路径，例外）
    for platform in ("linux", "darwin"):
        assert all(path.is_relative_to(fake) for path in config.game_candidates(fake, platform))


def test_workshop_由找到_root_的那个_steam_根推导() -> None:
    """Workshop = `<Steam 根>/steamapps/workshop/content/<App ID>`，根由 ROOT 反推。"""
    win_root = Path("C:/Program Files (x86)/Steam/steamapps/common/Victoria 3")
    assert config.steam_root_of(win_root) == Path("C:/Program Files (x86)/Steam")
    linux_root = Path("/home/user/.steam/steam/steamapps/common/Victoria 3")
    assert config.steam_root_of(linux_root) == Path("/home/user/.steam/steam")
    assert config.steam_root_of(Path("D:/games/victoria3")) is None, "形状不符就该说没有"
    assert config.workshop_for(win_root).parts[-3:] == (
        "workshop",
        "content",
        str(config.APP_ID),
    )
    assert config.workshop_for(linux_root) == config.workshop_dir(Path("/home/user/.steam/steam"))
    # 本机这份也必须是同一个形状（App ID 只从常量来）
    assert config.WORKSHOP.parts[-2:] == ("content", str(config.APP_ID))


def test_受控_tools_py_里没有机器专属绝对路径() -> None:
    """受控 `tools/**/*.py` 全扫 —— 有人再写死一个用户名，这条就红。

    判据不许有白名单：`config.py` 自己也在扫描范围内（它现在靠 `Path.home()` 推导，
    所以**不需要**被放行）。
    """
    offenders: list[str] = []
    for name in _controlled_python_files():
        text = (config.REPO / name).read_text(encoding="utf-8", errors="replace")
        offenders.extend(f"{name}:{number}: {hit}" for number, hit in _machine_paths(text))
    assert not offenders, (
        "受控代码里出现了机器专属绝对路径（改用 `Path.home()` / `pdx.config` 推导）：\n"
        + "\n".join(offenders)
    )


def test_机器路径闸门能被阴性对照撞红(tmp_path) -> None:
    """阴性对照：真用户名必须命中；占位符与泛称**不许**命中（它们是推荐写法）。

    ⚠️ 违规样本**不能**在源码里写成字面量：这条闸门扫的正是 `tools/**/*.py`（含本文件），
    一旦写成字面量，它会把**它自己**判红 —— 第一次就是这么撞出来的，而这顺带证明了
    闸门是严格的。所以用 `chr(92)` 拼出那个分隔符。
    """
    sep = chr(92)
    fake = tmp_path / "fake.py"
    fake.write_text(
        f'USERDIR = Path(r"C:{sep}Users{sep}somebody{sep}Documents")\n',
        encoding="utf-8",
        newline="\n",
    )
    hits = _machine_paths(fake.read_text(encoding="utf-8"))
    assert hits, "阴性对照没命中 ⇒ 这条闸门是空转的"
    assert hits[0] == (1, f"C:{sep}Users{sep}somebody")

    clean = (
        'a = Path("/home/<用户名>/x")\n'
        'b = "${USER}/x"\n'
        'c = "/Users/user/x"\n'
        'd = Path.home() / "Documents"\n'
    )
    assert _machine_paths(clean) == [], "占位符与泛称不该被判红"
