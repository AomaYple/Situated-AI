from pathlib import Path

from pdx.input_profile import (
    EXPECTED_MODIFIERS,
    EXPECTED_SCANCODES,
    check_profile,
    parse_profile,
)


def profile_text(*, speed_5: str = "34\n\t\tscancode = 93", pause: str = "44") -> str:
    return f"""version=1
input_context={{
 input_action = {{
  name = "pause"
  scancode = {pause}
 }}
 input_action = {{
  name = "speed_5"
  scancode = {speed_5}
 }}
}}
"""


def test_parse_profile_preserves_all_bindings():
    actions = parse_profile(profile_text())
    by_name = {item.name: item for item in actions}
    assert by_name["pause"].scancodes == (44,)
    assert by_name["speed_5"].scancodes == (34, 93)


def test_parse_profile_preserves_nested_modifier_binding():
    actions = parse_profile(
        """input_action = {
 name = \"tab_1\"
 binding = { scancode = 30 modifier = shift }
}
"""
    )
    assert actions[0].bindings[0].scancodes == (30,)
    assert actions[0].bindings[0].modifiers == ("shift",)


def test_check_profile_reports_drift_and_metadata(tmp_path: Path):
    path = tmp_path / "default.profile"
    path.write_text(profile_text(speed_5="35"), encoding="utf-8", newline="\n")
    result = check_profile(path, expected={"pause": frozenset({44}), "speed_5": frozenset({34})})
    assert not result.ok
    assert "speed_5 键位漂移" in result.errors[0]
    assert len(result.sha256) == 64
    assert result.size == path.stat().st_size


def test_check_profile_missing_file_is_explicit(tmp_path: Path):
    result = check_profile(tmp_path / "missing.profile")
    assert not result.ok
    assert "找不到输入配置" in result.errors[0]


def test_expected_profile_contract_has_speed_and_pause():
    assert EXPECTED_SCANCODES["pause"] == frozenset({44})
    assert EXPECTED_SCANCODES["speed_5"] == frozenset({34, 93})
    assert EXPECTED_MODIFIERS["tab_1"] == frozenset({"shift"})


def test_check_profile_reports_modifier_and_mouse_drift(tmp_path: Path):
    path = tmp_path / "default.profile"
    path.write_text(
        """input_action = {
 name = \"pause\"
 mouse_button = MOUSE_X1
 scancode = 44
}
input_action = {
 name = \"tab_1\"
 binding = { scancode = 30 modifier = ctrl }
}
""",
        encoding="utf-8",
        newline="\n",
    )
    result = check_profile(
        path,
        expected={"pause": frozenset({44})},
        expected_mouse_buttons={"pause": frozenset({"MOUSE_X2"})},
        expected_modifiers={"tab_1": frozenset({"shift"})},
    )
    assert not result.ok
    assert any("鼠标绑定漂移" in error for error in result.errors)
    assert any("修饰键漂移" in error for error in result.errors)
