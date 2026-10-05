"""Victoria 3 ``default.profile`` 的语义解析与键位漂移检查。

游戏的输入配置是 PDX 花括号文本，通用脚本扫描只能告诉我们文件存在，
无法回答 ``speed_5`` 是否仍绑定到数字键 5。本模块只解析 ``input_action``
块，保留每个动作的全部 scancode / mouse button，并提供一个不依赖游戏
进程的离线检查入口。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import config
from .console import enable_utf8_stdio

if TYPE_CHECKING:
    from collections.abc import Mapping


_NAME_RE = re.compile(r"\bname\s*=\s*\"(?P<value>[^\"]+)\"")
_TEXT_RE = re.compile(r"\btext\s*=\s*\"(?P<value>[^\"]+)\"")
_SCANCODE_RE = re.compile(r"\bscancode\s*=\s*(?P<value>-?\d+)")
_MOUSE_RE = re.compile(r"\bmouse_button\s*=\s*(?P<value>[^\s#]+)")

# 物理 scancode 来自官方 input_profile.md 的 US 键盘表。
EXPECTED_SCANCODES: dict[str, frozenset[int]] = {
    "pause": frozenset({44}),
    "increase_speed": frozenset({46, 87}),
    "decrease_speed": frozenset({45, 86}),
    "speed_1": frozenset({30, 89}),
    "speed_2": frozenset({31, 90}),
    "speed_3": frozenset({32, 91}),
    "speed_4": frozenset({33, 92}),
    "speed_5": frozenset({34, 93}),
    "open_politics": frozenset({58}),
    "open_budget": frozenset({59}),
    "open_buildings": frozenset({60}),
    "open_market": frozenset({61}),
    "open_military": frozenset({62}),
    "open_power_bloc": frozenset({63}),
    "open_diplomatic": frozenset({64}),
    "open_technology": frozenset({65}),
    "open_society": frozenset({66}),
    "open_population": frozenset({67}),
    "open_journal": frozenset({13}),
    "location_finder": frozenset({9}),
    "map_list": frozenset({20}),
    "construction_queue": frozenset({5}),
    "confirm": frozenset({6}),
    "country_panel": frozenset({21}),
    "music_play_pause": frozenset({96, 261}),
    "music_next_track": frozenset({97, 258}),
    "camera_up": frozenset({26, 82}),
    "camera_left": frozenset({4, 80}),
    "camera_down": frozenset({22, 81}),
    "camera_right": frozenset({7, 79}),
    "open_companies": frozenset({58}),
    "tab_1": frozenset({30}),
    "tab_2": frozenset({31}),
    "tab_3": frozenset({32}),
    "tab_4": frozenset({33}),
    "tab_5": frozenset({34}),
    "production_lens": frozenset({30}),
    "political_lens": frozenset({31}),
    "diplomatic_lens": frozenset({32}),
    "military_lens": frozenset({33}),
    "trade_lens": frozenset({34}),
    "outliner_toggle_pinned": frozenset({30}),
    "outliner_toggle_economy": frozenset({31}),
    "outliner_toggle_politics": frozenset({32}),
    "outliner_toggle_diplomacy": frozenset({33}),
    "outliner_toggle_military": frozenset({34}),
    "outliner_toggle_all": frozenset({35}),
    "toggle_construction_queue_pause": frozenset({5}),
    "dismiss_toast": frozenset({41}),
    "current_situation": frozenset({8}),
    "go_to_details": frozenset({10}),
    "merge": frozenset({16}),
    "toggle_pin": frozenset({27}),
    "zoom_to": frozenset({29}),
    "scroll_up": frozenset({75}),
    "scroll_down": frozenset({78}),
    "toggle_gui_debug": frozenset({18}),
}

EXPECTED_MOUSE_BUTTONS: dict[str, frozenset[str]] = {
    "pause": frozenset({"MOUSE_X2"}),
    "lock_tooltip": frozenset({"MOUSE_MIDDLE"}),
    "back": frozenset({"MOUSE_X1"}),
}

EXPECTED_MODIFIERS: dict[str, frozenset[str]] = {
    **{f"tab_{index}": frozenset({"shift"}) for index in range(1, 6)},
    "open_companies": frozenset({"shift"}),
    **{
        f"{name}_lens": frozenset({"alt"})
        for name in ("production", "political", "diplomatic", "military", "trade")
    },
    **{
        f"outliner_toggle_{name}": frozenset({"ctrl"})
        for name in ("pinned", "economy", "politics", "diplomacy", "military", "all")
    },
    "toggle_construction_queue_pause": frozenset({"ctrl"}),
}


@dataclass(frozen=True, slots=True)
class InputBinding:
    """一个绑定块，包含按键/鼠标和修饰键。"""

    scancodes: tuple[int, ...] = ()
    mouse_buttons: tuple[str, ...] = ()
    modifiers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InputAction:
    """一个 ``input_action`` 的完整绑定。"""

    name: str
    scancodes: tuple[int, ...]
    mouse_buttons: tuple[str, ...] = ()
    text: str = ""
    bindings: tuple[InputBinding, ...] = ()


@dataclass(frozen=True, slots=True)
class ProfileCheck:
    """输入配置校验结果；不把缺少游戏文件误报成漂移。"""

    path: Path
    sha256: str
    size: int
    actions: tuple[InputAction, ...]
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "sha256": self.sha256,
            "size": self.size,
            "ok": self.ok,
            "errors": list(self.errors),
            "actions": {
                action.name: {
                    "scancodes": list(action.scancodes),
                    "mouse_buttons": list(action.mouse_buttons),
                    "text": action.text,
                    "bindings": [
                        {
                            "scancodes": list(binding.scancodes),
                            "mouse_buttons": list(binding.mouse_buttons),
                            "modifiers": list(binding.modifiers),
                        }
                        for binding in action.bindings
                    ],
                }
                for action in self.actions
            },
        }


def _block_end(text: str, opening: int) -> int:
    """返回花括号块的结束位置，忽略字符串和 ``#`` 注释中的花括号。"""

    depth = 0
    quoted = False
    escaped = False
    comment = False
    for index in range(opening, len(text)):
        char = text[index]
        if comment:
            if char == "\n":
                comment = False
            continue
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == "#":
            comment = True
        elif char == '"':
            quoted = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError("input_profile 花括号未闭合")


def _action_bodies(text: str) -> list[str]:
    bodies: list[str] = []
    for match in re.finditer(r"\binput_action\s*=\s*\{", text):
        opening = text.find("{", match.start(), match.end())
        closing = _block_end(text, opening)
        bodies.append(text[opening + 1 : closing])
    return bodies


def _bindings(body: str) -> tuple[InputBinding, ...]:
    """解析一个动作的直接绑定和嵌套 ``binding`` 块。"""

    nested: list[tuple[int, int, str]] = []
    for match in re.finditer(r"\bbinding\s*=\s*\{", body):
        opening = body.find("{", match.start(), match.end())
        closing = _block_end(body, opening)
        nested.append((match.start(), closing + 1, body[opening + 1 : closing]))

    direct = body
    for start, end, _nested_body in reversed(nested):
        direct = direct[:start] + (" " * (end - start)) + direct[end:]

    result: list[InputBinding] = []
    direct_scancodes = tuple(int(item.group("value")) for item in _SCANCODE_RE.finditer(direct))
    direct_mouse = tuple(item.group("value") for item in _MOUSE_RE.finditer(direct))
    if direct_scancodes or direct_mouse:
        result.append(InputBinding(direct_scancodes, direct_mouse))
    for _start, _end, nested_body in nested:
        scancodes = tuple(int(item.group("value")) for item in _SCANCODE_RE.finditer(nested_body))
        mouse = tuple(item.group("value") for item in _MOUSE_RE.finditer(nested_body))
        modifiers = tuple(
            item.group("value")
            for item in re.finditer(r"\bmodifier\s*=\s*(?P<value>[A-Za-z0-9_+-]+)", nested_body)
        )
        result.append(InputBinding(scancodes, mouse, modifiers))
    return tuple(result)


def parse_profile(text: str) -> tuple[InputAction, ...]:
    """解析输入动作块，允许未知字段和动作以保持版本兼容。"""

    actions: list[InputAction] = []
    for body in _action_bodies(text):
        name_match = _NAME_RE.search(body)
        if name_match is None:
            continue
        name = name_match.group("value")
        scancodes = tuple(int(item.group("value")) for item in _SCANCODE_RE.finditer(body))
        mouse_buttons = tuple(item.group("value") for item in _MOUSE_RE.finditer(body))
        text_match = _TEXT_RE.search(body)
        bindings = _bindings(body)
        actions.append(
            InputAction(
                name=name,
                scancodes=scancodes,
                mouse_buttons=mouse_buttons,
                text=text_match.group("value") if text_match else "",
                bindings=bindings,
            )
        )
    return tuple(actions)


def profile_path(game_root: Path | None = None) -> Path:
    """返回跨平台游戏安装根下的公共输入配置路径。"""

    root = config.ROOT if game_root is None else Path(game_root)
    return root / "game" / "input_profile" / "default.profile"


def check_profile(
    path: Path | None = None,
    *,
    expected: Mapping[str, frozenset[int]] | None = None,
    expected_mouse_buttons: Mapping[str, frozenset[str]] | None = None,
    expected_modifiers: Mapping[str, frozenset[str]] | None = None,
) -> ProfileCheck:
    """检查关键动作是否仍包含预期的物理键位。"""

    target = profile_path() if path is None else Path(path)
    if not target.is_file():
        return ProfileCheck(target, "", 0, (), (f"找不到输入配置：{target}",))
    data = target.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    text = data.decode("utf-8-sig")
    actions = parse_profile(text)
    by_name = {action.name: action for action in actions}
    errors: list[str] = []
    expected_scancodes = EXPECTED_SCANCODES if expected is None else expected
    for name, wanted_codes in expected_scancodes.items():
        action = by_name.get(name)
        if action is None:
            errors.append(f"缺少 input_action：{name}")
            continue
        actual_codes = frozenset(action.scancodes)
        if not wanted_codes.issubset(actual_codes):
            errors.append(
                f"{name} 键位漂移：期望至少 {sorted(wanted_codes)}，实际 {sorted(actual_codes)}"
            )
    if expected is None:
        expected_mouse_buttons = EXPECTED_MOUSE_BUTTONS
        expected_modifiers = EXPECTED_MODIFIERS
    by_name = {action.name: action for action in actions}
    for name, wanted_mouse in (expected_mouse_buttons or {}).items():
        action = by_name.get(name)
        if action is None:
            errors.append(f"缺少 input_action：{name}")
            continue
        actual_mouse = frozenset(action.mouse_buttons)
        if actual_mouse != wanted_mouse:
            errors.append(
                f"{name} 鼠标绑定漂移：期望 {sorted(wanted_mouse)}，实际 {sorted(actual_mouse)}"
            )
    for name, wanted_modifiers in (expected_modifiers or {}).items():
        action = by_name.get(name)
        if action is None:
            errors.append(f"缺少 input_action：{name}")
            continue
        actual_modifiers = frozenset(
            modifier for binding in action.bindings for modifier in binding.modifiers
        )
        if actual_modifiers != wanted_modifiers:
            errors.append(
                f"{name} 修饰键漂移：期望 {sorted(wanted_modifiers)}，实际 {sorted(actual_modifiers)}"
            )
    return ProfileCheck(target, digest, len(data), actions, tuple(errors))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="检查 Victoria 3 default.profile 键位漂移")
    parser.add_argument("--path", type=Path, help="显式指定 default.profile")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    enable_utf8_stdio()
    args = _parser().parse_args(argv)
    result = check_profile(args.path)
    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"路径：{result.path}")
        print(f"SHA-256：{result.sha256 or '（无）'}")
        print(f"大小：{result.size} 字节")
        print(f"结果：{'通过' if result.ok else '失败'}")
        for error in result.errors:
            print(f"❌ {error}")
    return 0 if result.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
