"""把几条原先只靠评审的工程原则接到自动检查上。

每条检查都由一个纯函数给出违规清单，再配一个“故意违反会失败”的反例用例，
免得检查在无人察觉时退化成空转。条款与入口的对应见 ``docs/principles/README.md``
的“条款执行方式”表：

* EP-34：``tests/*.py`` 里跳过原因的字面量必须能被 ``classify_skip_reason`` 归类，
  且不得出现白名单之外的 xfail；
* EP-24：工作流的 ``uses:`` 以完整提交 SHA 固定；
* EP-16：工具配置集中在 ``pyproject.toml``，仓库根没有另一份独立配置；
* EP-23：Ruff 与 mypy 以 ``==`` 固定，且与 ``requirements.lock`` 一致；
* EP-19：``tests/`` 下的文本读写与文本模式子进程不依赖默认编码。
"""

import ast
import re
import subprocess
import tomllib
from collections.abc import Iterable, Mapping
from pathlib import Path

import pytest

from pdx import lockfile
from pdx.engineering import classify_skip_reason

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

# ── EP-34：跳过原因与 xfail ────────────────────────────────────────────────

#: 会产生 skipped 结果的写法。值是原因所在的位置参数下标；``None`` 表示只接受 ``reason=``
#: （``skipif`` 的位置参数全是条件）。``skip`` 同时覆盖 ``pytest.skip``、``pytest.mark.skip``
#: 与 ``unittest.skip``。
_SKIP_REASON_POSITION: Mapping[str, int | None] = {
    "skip": 0,
    "skipTest": 0,
    "SkipTest": 0,
    "skipif": None,
    "skipIf": 1,
    "skipUnless": 1,
    "importorskip": 2,
}
_SKIP_MODULES = frozenset({"pytest", "unittest"})
#: 不带括号也生效的标记与装饰器；这样写没有地方放原因。
_BARE_MARKS = frozenset({"skip", "skipif"})
_BARE_DECORATORS = frozenset({"skip", "skipIf", "skipUnless"})

#: 本文件自己也在扫描范围内，所以不把被禁写法写成连续字面量。
_XFAIL = "x" + "fail"
#: 属性访问（``pytest.``、``mark.``、任意别名）、从 pytest 导入、直接调用、按名字加标记。
#: ``xfailed``、``wasxfail`` 和作为结果标签的字符串不算。
_XFAIL_USE = re.compile(
    rf"\.{_XFAIL}\b"
    rf"|\bimport\b.*\b{_XFAIL}\b"
    rf"|(?<![\w.\"']){_XFAIL}\s*\("
    rf"|\badd_marker\(\s*[\"']{_XFAIL}\b"
)
#: 故障注入样本：这些 xfail 写在被测子进程的源码字符串里，用来证明 xfail 结果不会被签署。
#: 按“文件 + 所在行去掉首尾空白后的文本”登记；行变了、多了或少了都要重新核对。
_XFAIL_ALLOWED: Mapping[str, tuple[str, ...]] = {
    "test_architecture_witness_capture.py": (
        f"request.node.add_marker(pytest.mark.{_XFAIL}(strict=False))",
        f'pytest.{_XFAIL}("real {_XFAIL}")',
    ),
}


def _literal_prefix(node: ast.expr) -> str | None:
    """字符串字面量原样返回；f-string 取第一个插值之前的字面前缀；其余返回 ``None``。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        prefix = ""
        for value in node.values:
            if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
                break
            prefix += value.value
        return prefix
    return None


def _skip_aliases(tree: ast.AST) -> dict[str, str]:
    """``from pytest/unittest import skipIf as x`` ⇒ ``{"x": "skipIf"}``。"""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        if node.module.split(".")[0] not in _SKIP_MODULES:
            continue
        for alias in node.names:
            if alias.name in _SKIP_REASON_POSITION:
                aliases[alias.asname or alias.name] = alias.name
    return aliases


def _skip_name(node: ast.AST, aliases: Mapping[str, str]) -> str | None:
    """节点指向的跳过写法名；不是跳过写法返回 ``None``。"""
    if isinstance(node, ast.Attribute):
        return node.attr if node.attr in _SKIP_REASON_POSITION else None
    if isinstance(node, ast.Name):
        name = aliases.get(node.id, node.id)
        return name if name in _SKIP_REASON_POSITION else None
    return None


def _is_mark(node: ast.AST) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "mark") or (
        isinstance(node, ast.Name) and node.id == "mark"
    )


def _skip_reason_violations(source: str, name: str) -> list[str]:
    """无法归类、缺失或非字面量的跳过原因 ⇒ 按行号排序的 ``["文件:行: 说明", …]``。"""
    tree = ast.parse(source)
    aliases = _skip_aliases(tree)
    called = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    found: dict[tuple[int, int], str] = {}

    def bare(node: ast.AST, call: str) -> None:
        if id(node) not in called and isinstance(node, ast.expr):
            found[(node.lineno, node.col_offset)] = f"{call} 没有调用，没有地方写原因"

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in _BARE_MARKS and _is_mark(node.value):
            bare(node, node.attr)
        elif isinstance(node, ast.Raise) and node.exc is not None:
            if _skip_name(node.exc, aliases) == "SkipTest":
                bare(node.exc, "SkipTest")
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            for decorator in node.decorator_list:
                call = _skip_name(decorator, aliases)
                if call in _BARE_DECORATORS:
                    bare(decorator, call)
        if not isinstance(node, ast.Call):
            continue
        call = _skip_name(node.func, aliases)
        if call is None:
            continue
        reason: ast.expr | None = next(
            (keyword.value for keyword in node.keywords if keyword.arg == "reason"), None
        )
        position = _SKIP_REASON_POSITION[call]
        if reason is None and position is not None and len(node.args) > position:
            reason = node.args[position]
        key = (node.lineno, node.col_offset)
        if reason is None:
            found[key] = f"{call} 没有写原因"
            continue
        literal = _literal_prefix(reason)
        if literal is None:
            found[key] = f"{call} 的原因不是字符串字面量"
        elif classify_skip_reason(literal) is None:
            found[key] = f"{call} 的原因无法归类：{literal!r}"
    return [f"{name}:{line}: {message}" for (line, _), message in sorted(found.items())]


def _xfail_violations(source: str, name: str, allowed: Mapping[str, tuple[str, ...]]) -> list[str]:
    """白名单之外的 xfail 用法；白名单按所在行文本登记，登记了却不再出现同样拒绝。"""
    hits = [
        (number, line.strip())
        for number, line in enumerate(source.splitlines(), start=1)
        if _XFAIL_USE.search(line)
    ]
    remaining = list(allowed.get(name, ()))
    found: list[str] = []
    for number, text in hits:
        if text in remaining:
            remaining.remove(text)
        else:
            found.append(f"{name}:{number}: 未登记的 {_XFAIL}：{text}")
    found.extend(f"{name}: 登记的 {_XFAIL} 行已不存在：{text}" for text in remaining)
    return found


def _test_sources() -> list[tuple[str, str]]:
    sources = [(path.name, path.read_text(encoding="utf-8")) for path in sorted(TESTS.glob("*.py"))]
    assert len(sources) > 100, "tests/*.py 清单异常地短，检查会空转"
    return sources


def test_跳过原因的字面量都能归类() -> None:
    violations = [
        item for name, source in _test_sources() for item in _skip_reason_violations(source, name)
    ]
    assert not violations, (
        "跳过原因须命中 pdx.engineering 的既有类别（改文案，不改条件）：\n" + "\n".join(violations)
    )


def test_跳过原因检查能被反例撞红() -> None:
    bad = (
        "import pytest\n"
        "import unittest\n"
        "from unittest import SkipTest, skipIf\n"
        "from unittest import skipUnless as unless\n"
        "pytestmark = pytest.mark.skip\n"
        "@pytest.mark.skipif(True, reason='some unexplained condition')\n"
        "@pytest.mark.skip\n"
        "@unittest.skipIf(True, 'nope')\n"
        "@skipIf(True, 'nope')\n"
        "@unless(False, 'nope')\n"
        "@unittest.skip('nope')\n"
        "@unittest.skip\n"
        "def test_a():\n"
        "    pytest.skip('whatever')\n"
        "    pytest.skip(f'{value} 游戏目录不可用')\n"
        "    pytest.skip(reason_variable)\n"
        "    pytest.skip()\n"
        "    pytest.importorskip('_winapi')\n"
        "    pytest.importorskip('_winapi', reason='nope')\n"
        "    pytest.importorskip('_winapi', '1.0')\n"
        "    raise unittest.SkipTest('nope')\n"
        "    raise unittest.SkipTest\n"
        "    raise SkipTest\n"
    )
    rejected = [item.split(": ", 1)[0] for item in _skip_reason_violations(bad, "bad.py")]
    assert rejected == [f"bad.py:{line}" for line in (*range(5, 13), *range(14, 24))]
    good = (
        "import pytest\n"
        "import unittest\n"
        "from unittest import SkipTest\n"
        "pytestmark = pytest.mark.skip(reason='游戏目录不可用')\n"
        "@pytest.mark.skipif(True, reason='需要 Windows')\n"
        "@unittest.skipIf(True, '需要 Windows')\n"
        "@unittest.skipUnless(False, reason='需要 Linux')\n"
        "def test_a():\n"
        "    pytest.importorskip('_winapi', reason='需要 Windows 的 _winapi 模块')\n"
        "    pytest.importorskip('_winapi', None, '需要 Windows 的 _winapi 模块')\n"
        "    pytest.skip(f'游戏目录不可用：{path}')\n"
        "    self.skipTest('没有精简快照')\n"
        "    item.add_marker(skip)\n"
        "    assert report.skipped and skip is not None\n"
        "    raise SkipTest('游戏目录不可用')\n"
    )
    assert _skip_reason_violations(good, "good.py") == []


def test_tests_里没有白名单之外的_xfail() -> None:
    sources = dict(_test_sources())
    assert set(_XFAIL_ALLOWED) <= set(sources), "xfail 白名单登记了不存在的文件"
    violations = [
        item
        for name, source in sources.items()
        for item in _xfail_violations(source, name, _XFAIL_ALLOWED)
    ]
    assert not violations, "\n".join(violations)


def test_xfail_检查能被反例撞红() -> None:
    marked = f"@pytest.mark.{_XFAIL}(strict=False)"
    called = f"    pytest.{_XFAIL}('later')"
    for line in (
        marked,
        called,
        f"from pytest import {_XFAIL}",
        f"from pytest import skip, {_XFAIL} as later",
        f"    {_XFAIL}('later')",
        f"    request.node.add_marker('{_XFAIL}')",
        f'    request.node.add_marker("{_XFAIL}")',
        f"    request.node.add_marker(pytest.mark.{_XFAIL}(strict=False))",
        f"    pt.{_XFAIL}('later')",
        f"pytestmark = pytest.mark.{_XFAIL}",
    ):
        assert len(_xfail_violations(f"import pytest as pt\n{line}\n", "new.py", {})) == 1, line
    # 白名单按行文本登记：同一行多出现一次、换了文本、登记了却不再出现，都拒绝。
    allowed = {"sample.py": (marked,)}
    assert _xfail_violations(f"{marked}\n", "sample.py", allowed) == []
    assert len(_xfail_violations(f"{marked}\n{marked}\n", "sample.py", allowed)) == 1
    assert len(_xfail_violations(f"{called}\n", "sample.py", allowed)) == 2
    assert len(_xfail_violations("def test_a(): ...\n", "sample.py", allowed)) == 1
    assert len(_xfail_violations(f"{marked}\n", "other.py", allowed)) == 1
    harmless = (
        f"summary = '1 {_XFAIL}ed, 1 xpassed'\n"
        f"outcome = '{_XFAIL}' if hasattr(report, 'was{_XFAIL}') else report.outcome\n"
        f"if FAULT == '{_XFAIL}':\n"
        f"def test_failed_skipped_{_XFAIL}ed_is_never_signed(): ...\n"
    )
    assert _xfail_violations(harmless, "new.py", {}) == []


# ── EP-24：Actions 固定完整 SHA ────────────────────────────────────────────

_USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(?P<target>[^\s#]+)")
_PINNED = re.compile(r"@[0-9a-f]{40}$")


def _action_references(text: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        match = _USES.match(line)
        if match:
            found.append((number, match.group("target").strip("'\"")))
    return found


def _unpinned_actions(text: str) -> list[tuple[int, str]]:
    """非本地 action 中没有以 ``@<40 位小写十六进制>`` 结尾的引用。"""
    return [
        (number, target)
        for number, target in _action_references(text)
        if not target.startswith("./") and not _PINNED.search(target)
    ]


def test_工作流的_actions_以完整提交_sha_固定() -> None:
    workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflows, "没有找到任何工作流文件"
    references = 0
    offenders: list[str] = []
    for path in workflows:
        text = path.read_text(encoding="utf-8")
        references += len(_action_references(text))
        offenders.extend(
            f"{path.name}:{number}: {target}" for number, target in _unpinned_actions(text)
        )
    assert references, "工作流里没有识别到任何 uses:，检查会空转"
    assert not offenders, "Actions 须以完整提交 SHA 固定：\n" + "\n".join(offenders)


def test_actions_固定检查能被反例撞红() -> None:
    sha = "3d3c42e5aac5ba805825da76410c181273ba90b1"
    text = (
        "steps:\n"
        f"  - uses: actions/checkout@{sha} # v7.0.1\n"
        "  - uses: ./.github/actions/local\n"
        "  - uses: actions/checkout@v7\n"
        "  - name: upload\n"
        "    uses: actions/upload-artifact@main\n"
        f"  - uses: actions/setup-python@{sha[:39]}\n"
        f"  - uses: actions/setup-python@{sha.upper()}\n"
        "  - uses: actions/cache\n"
    )
    assert len(_action_references(text)) == 7
    assert _unpinned_actions(text) == [
        (4, "actions/checkout@v7"),
        (6, "actions/upload-artifact@main"),
        (7, f"actions/setup-python@{sha[:39]}"),
        (8, f"actions/setup-python@{sha.upper()}"),
        (9, "actions/cache"),
    ]


# ── EP-16：配置集中在 pyproject.toml ───────────────────────────────────────

_STANDALONE_CONFIGS = frozenset(
    {
        "pytest.ini",
        "setup.cfg",
        "tox.ini",
        ".coveragerc",
        "mypy.ini",
        "ruff.toml",
        ".ruff.toml",
        "setup.py",
    }
)
_REQUIRED_TOOL_TABLES = ("pytest.ini_options", "coverage", "ruff", "mypy")


def _controlled_root_files() -> list[str]:
    """仓库根的受控文件名：已跟踪的，以及未跟踪但未被忽略的。"""
    raw = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT
    )
    names = [part.decode("utf-8") for part in raw.split(b"\x00") if part]
    return sorted({name for name in names if "/" not in name and (ROOT / name).is_file()})


def _standalone_configs(names: Iterable[str]) -> list[str]:
    return sorted(set(names) & _STANDALONE_CONFIGS)


def _missing_tool_tables(document: Mapping[str, object]) -> list[str]:
    missing: list[str] = []
    for dotted in _REQUIRED_TOOL_TABLES:
        node: object = document.get("tool")
        for key in dotted.split("."):
            node = node.get(key) if isinstance(node, Mapping) else None
        if not isinstance(node, Mapping) or not node:
            missing.append(f"tool.{dotted}")
    return missing


def _pyproject() -> dict[str, object]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_工具配置集中在_pyproject() -> None:
    names = _controlled_root_files()
    assert "pyproject.toml" in names
    assert _standalone_configs(names) == [], "仓库根出现了独立的工具配置文件"
    assert _missing_tool_tables(_pyproject()) == []


def test_配置集中检查能被反例撞红() -> None:
    assert _standalone_configs(["pyproject.toml", "setup.cfg", "README.md", ".ruff.toml"]) == [
        ".ruff.toml",
        "setup.cfg",
    ]
    document = {"tool": {"pytest": {"ini_options": {"addopts": []}}, "ruff": {}, "mypy": 1}}
    assert _missing_tool_tables(document) == ["tool.coverage", "tool.ruff", "tool.mypy"]
    assert _missing_tool_tables({}) == [f"tool.{name}" for name in _REQUIRED_TOOL_TABLES]


# ── EP-23：检查工具版本固定 ────────────────────────────────────────────────

_PINNED_TOOLS = ("ruff", "mypy")
_REQUIREMENT = re.compile(r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*(?P<spec>.*?)\s*$")
_EXACT = re.compile(r"==\s*(?P<version>[0-9][0-9A-Za-z.!+]*)")


def _tool_pin_problems(dev: Iterable[str], locked: Mapping[str, str]) -> list[str]:
    """dev 依赖里的 Ruff、mypy 须恰好声明一次、以 ``==`` 精确固定，并与锁文件版本相等。"""
    declared: dict[str, list[str]] = {tool: [] for tool in _PINNED_TOOLS}
    for requirement in dev:
        match = _REQUIREMENT.match(requirement)
        if match and lockfile.normalize(match.group("name")) in declared:
            declared[lockfile.normalize(match.group("name"))].append(match.group("spec"))
    problems: list[str] = []
    for tool, specs in declared.items():
        if len(specs) != 1:
            problems.append(f"{tool}: dev 依赖里声明了 {len(specs)} 次")
            continue
        exact = _EXACT.fullmatch(specs[0])
        if exact is None:
            problems.append(f"{tool}: 没有以 == 精确固定：{specs[0]!r}")
        elif locked.get(tool) != exact.group("version"):
            problems.append(
                f"{tool}: 声明 {exact.group('version')}，锁文件记录 {locked.get(tool)!r}"
            )
    return problems


def test_ruff_与_mypy_精确固定且与锁文件一致() -> None:
    project = _pyproject()["project"]
    assert isinstance(project, dict)
    dev = project["optional-dependencies"]["dev"]
    locked = lockfile.read()
    assert locked, "requirements.lock 读不出任何条目，检查会空转"
    assert _tool_pin_problems(dev, locked) == []


def test_工具固定检查能被反例撞红() -> None:
    locked = {"ruff": "0.16.7", "mypy": "2.3.1"}
    assert _tool_pin_problems(["ruff==0.16.7", "mypy == 2.3.1", "pytest>=9"], locked) == []
    assert len(_tool_pin_problems(["ruff>=0.16.7", "mypy==2.3.1"], locked)) == 1
    assert len(_tool_pin_problems(["ruff==0.16.*", "mypy==2.3.1"], locked)) == 1
    assert len(_tool_pin_problems(["ruff==0.16.7,<1", "mypy==2.3.1"], locked)) == 1
    assert len(_tool_pin_problems(["ruff==0.16.8", "mypy==2.3.1"], locked)) == 1
    assert len(_tool_pin_problems(["ruff==0.16.7"], locked)) == 1
    assert len(_tool_pin_problems(["ruff==0.16.7", "ruff==0.16.7", "mypy==2.3.1"], locked)) == 1
    assert len(_tool_pin_problems(["ruff==0.16.7", "mypy==2.3.1"], {"ruff": "0.16.7"})) == 1
    # mypy-extensions 是另一个包，不能被当成 mypy 的声明。
    assert len(_tool_pin_problems(["ruff==0.16.7", "mypy-extensions==1.1.0"], locked)) == 1


# ── EP-19：tests/ 不依赖默认编码 ───────────────────────────────────────────

_TEXT_IO = {"read_text": 0, "write_text": 1}  # encoding 之前的位置参数个数
_SUBPROCESS_CALLS = frozenset({"run", "Popen", "check_output", "check_call", "call"})


def _default_encoding_uses(source: str, name: str) -> list[str]:
    """省略 encoding 的 ``read_text`` / ``write_text`` 与文本模式子进程调用。"""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        keywords = {keyword.arg for keyword in node.keywords}
        if None in keywords or "encoding" in keywords:  # **kwargs 无法静态判断，不猜
            continue
        call = node.func.attr
        if call in _TEXT_IO and len(node.args) <= _TEXT_IO[call]:
            found.append(f"{name}:{node.lineno}: {call} 省略了 encoding")
        elif call in _SUBPROCESS_CALLS and keywords & {"text", "universal_newlines"}:
            found.append(f"{name}:{node.lineno}: 文本模式的 {call} 省略了 encoding")
    return found


def test_tests_的文本读写不依赖默认编码() -> None:
    violations = [
        item for name, source in _test_sources() for item in _default_encoding_uses(source, name)
    ]
    assert not violations, "补上 encoding=（通常是 utf-8）：\n" + "\n".join(violations)


def test_默认编码检查能被反例撞红() -> None:
    bad = (
        "text = path.read_text()\n"
        "path.write_text(text)\n"
        "path.write_text(data=text, newline='')\n"
        "subprocess.run(command, text=True, check=False)\n"
        "subprocess.Popen(command, universal_newlines=True)\n"
    )
    assert [item.split(": ", 1)[0] for item in _default_encoding_uses(bad, "bad.py")] == [
        "bad.py:1",
        "bad.py:2",
        "bad.py:3",
        "bad.py:4",
        "bad.py:5",
    ]
    good = (
        "text = path.read_text(encoding='utf-8')\n"
        "text = path.read_text('utf-8')\n"
        "path.write_text(text, encoding='utf-8', newline='')\n"
        "path.write_text(text, 'utf-8')\n"
        "path.write_text(text, **options)\n"
        "subprocess.run(command, text=True, encoding='utf-8', check=False)\n"
        "subprocess.run(command, capture_output=True, check=False)\n"
    )
    assert _default_encoding_uses(good, "good.py") == []
