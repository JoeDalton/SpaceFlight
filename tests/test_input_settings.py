"""
Unit tests for pure functions and data methods in the input settings menu.

Covers:
- :func:`_format_binding` — pure label-format helper
- :meth:`InputSettingsMenuState.load_file` — static YAML loader
- :meth:`InputSettingsMenuState.make_row_data` — row descriptor builder
- :meth:`InputSettingsMenuState.flush_dead_zones` — entry-widget flush
- :meth:`InputSettingsMenuState.on_confirmed` — binding update callback
"""
from unittest.mock import MagicMock

import pytest

from space_flight.menus.input_settings_menu_state import (
    InputSettingsMenuState,
    format_binding,
)
from space_flight.ui.input_reader import GAMEPAD_AXIS_NAMES, JOYSTICK_AXIS_NAMES

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def state():
    """Return an InputSettingsMenuState with a mock app (no Panda3D UI)."""
    return InputSettingsMenuState(app=MagicMock())


@pytest.fixture
def cfg():
    """Minimal valid configuration dict matching the YAML structure."""
    return {
        "input_type": "keyboard",
        "global": {"pause": "escape"},
        "dead_zones": {"stick": 0.15, "throttle": 0.04},
        "contexts": {
            "flight": {
                "keyboard": {"fire": "space", "boost_on": "b"},
                "gamepad": {"throttle": "right_trigger", "fire": "gamepad_lshoulder"},
                "joystick": {"throttle": "throttle", "fire": "stick_button_1"},
            },
            "radial_menu": {
                "keyboard": {"dir_up": "i"},
                "gamepad": {"axis_x": "right_x"},
            },
        },
    }


# ---------------------------------------------------------------------------
# format_binding
# ---------------------------------------------------------------------------


class TestFormatBinding:
    def test_empty_value_returns_unmapped(self):
        assert format_binding("keyboard", "") == "Unmapped"

    def test_keyboard_button_is_button_prefix(self):
        assert format_binding("keyboard", "space") == "Button: Space"

    def test_keyboard_underscore_replaced_by_space(self):
        assert format_binding("keyboard", "arrow_up") == "Button: Arrow Up"

    def test_keyboard_always_button_even_for_axis_name(self):
        # Keyboard has no axes; axis-name heuristic does not apply.
        assert format_binding("keyboard", "left_x") == "Button: Left X"

    def test_gamepad_known_axis_returns_axis_prefix(self):
        axis = next(iter(GAMEPAD_AXIS_NAMES))
        label = axis.replace("_", " ").title()
        assert format_binding("gamepad", axis) == f"Axis: {label}"

    def test_gamepad_trigger_returns_axis_prefix(self):
        assert format_binding("gamepad", "right_trigger") == "Axis: Right Trigger"

    def test_gamepad_button_returns_button_prefix(self):
        assert (
            format_binding("gamepad", "gamepad_lshoulder")
            == "Button: Gamepad Lshoulder"
        )

    def test_joystick_known_axis_returns_axis_prefix(self):
        axis = next(iter(JOYSTICK_AXIS_NAMES))
        label = axis.replace("_", " ").title()
        assert format_binding("joystick", axis) == f"Axis: {label}"

    def test_joystick_button_returns_button_prefix(self):
        assert format_binding("joystick", "stick_button_1") == "Button: Stick Button 1"

    def test_forced_type_axis_overrides_heuristic(self):
        # "space" is normally a button; forced_type="axis" must win.
        assert format_binding("keyboard", "space", forced_type="axis") == "Axis: Space"

    def test_forced_type_button_overrides_heuristic(self):
        # "left_x" is normally a gamepad axis; forced_type="button" must win.
        assert (
            format_binding("gamepad", "left_x", forced_type="button")
            == "Button: Left X"
        )

    def test_unknown_input_type_falls_back_to_button(self):
        assert format_binding("unknown_device", "left_x") == "Button: Left X"


# ---------------------------------------------------------------------------
# InputSettingsMenuState.load_file
# ---------------------------------------------------------------------------


class TestLoadFile:
    def test_parses_yaml_to_dict(self, tmp_path):
        f = tmp_path / "cfg.yaml"
        f.write_text("input_type: keyboard\n")
        assert InputSettingsMenuState.load_file(f) == {"input_type": "keyboard"}

    def test_nested_structure_preserved(self, tmp_path):
        f = tmp_path / "cfg.yaml"
        f.write_text("dead_zones:\n  stick: 0.15\n  throttle: 0.04\n")
        result = InputSettingsMenuState.load_file(f)
        assert result["dead_zones"]["stick"] == pytest.approx(0.15)

    def test_float_values_parsed_as_float(self, tmp_path):
        f = tmp_path / "cfg.yaml"
        f.write_text("dead_zones:\n  stick: 0.15\n")
        result = InputSettingsMenuState.load_file(f)
        assert isinstance(result["dead_zones"]["stick"], float)


# ---------------------------------------------------------------------------
# InputSettingsMenuState.make_row_data
# ---------------------------------------------------------------------------


class TestMakeRowData:
    def test_dead_zone_header_always_present(self, state, cfg):
        state.working_config = cfg
        headers = [r["text"] for r in state.make_row_data() if r["kind"] == "header"]
        assert "Dead Zones" in headers

    def test_dead_zone_rows_one_per_key(self, state, cfg):
        state.working_config = cfg
        dz_rows = [r for r in state.make_row_data() if r["kind"] == "deadzone"]
        assert len(dz_rows) == 2
        labels = {r["label"] for r in dz_rows}
        assert "Stick" in labels
        assert "Throttle" in labels

    def test_global_bindings_header_present(self, state, cfg):
        state.working_config = cfg
        headers = [r["text"] for r in state.make_row_data() if r["kind"] == "header"]
        assert "Global Bindings" in headers

    def test_global_binding_row_per_action(self, state, cfg):
        state.working_config = cfg
        paths = [r["path"] for r in state.make_row_data() if r["kind"] == "binding"]
        assert ("global", "pause") in paths

    def test_keyboard_bindings_included_for_keyboard_type(self, state, cfg):
        state.working_config = cfg  # input_type = "keyboard"
        paths = [r["path"] for r in state.make_row_data() if r["kind"] == "binding"]
        assert ("contexts", "flight", "keyboard", "fire") in paths

    def test_gamepad_bindings_included_for_gamepad_type(self, state, cfg):
        cfg["input_type"] = "gamepad"
        state.working_config = cfg
        paths = [r["path"] for r in state.make_row_data() if r["kind"] == "binding"]
        assert ("contexts", "flight", "gamepad", "fire") in paths

    def test_inactive_input_type_bindings_excluded(self, state, cfg):
        state.working_config = cfg  # input_type = "keyboard"
        paths = [r["path"] for r in state.make_row_data() if r["kind"] == "binding"]
        assert ("contexts", "flight", "gamepad", "fire") not in paths

    def test_context_label_from_context_labels_dict(self, state, cfg):
        state.working_config = cfg
        headers = [r["text"] for r in state.make_row_data() if r["kind"] == "header"]
        assert "Flight Bindings" in headers

    def test_dead_zones_appear_before_binding_rows(self, state, cfg):
        state.working_config = cfg
        rows = state.make_row_data()
        dz_header_idx = next(
            i
            for i, r in enumerate(rows)
            if r.get("kind") == "header" and r.get("text") == "Dead Zones"
        )
        first_binding_idx = next(
            (i for i, r in enumerate(rows) if r.get("kind") == "binding"), len(rows)
        )
        assert dz_header_idx < first_binding_idx

    def test_empty_contexts_produces_no_binding_rows(self, state):
        state.working_config = {
            "input_type": "keyboard",
            "dead_zones": {},
            "contexts": {},
        }
        rows = state.make_row_data()
        assert not any(r["kind"] == "binding" for r in rows)

    def test_missing_global_omits_global_header(self, state):
        state.working_config = {
            "input_type": "keyboard",
            "dead_zones": {},
            "contexts": {},
        }
        headers = [r["text"] for r in state.make_row_data() if r["kind"] == "header"]
        assert "Global Bindings" not in headers

    def test_deadzone_path_tuple_structure(self, state, cfg):
        state.working_config = cfg
        dz_paths = [r["path"] for r in state.make_row_data() if r["kind"] == "deadzone"]
        assert ("dead_zones", "stick") in dz_paths


# ---------------------------------------------------------------------------
# InputSettingsMenuState.flush_dead_zones
# ---------------------------------------------------------------------------


def mock_entry(text: str):
    """Return a mock that mimics CustomEntry.get() → text."""
    e = MagicMock()
    e.get.return_value = text
    return e


class TestFlushDeadZones:
    def test_float_string_converted_to_float(self, state):
        state.working_config = {"dead_zones": {"stick": 0.15}}
        state.dz_entries = {("dead_zones", "stick"): mock_entry("0.20")}
        state.flush_dead_zones()
        assert state.working_config["dead_zones"]["stick"] == pytest.approx(0.20)
        assert isinstance(state.working_config["dead_zones"]["stick"], float)

    def test_invalid_string_kept_as_string_when_original_is_float(self, state):
        state.working_config = {"dead_zones": {"stick": 0.15}}
        state.dz_entries = {("dead_zones", "stick"): mock_entry("not_a_number")}
        state.flush_dead_zones()
        assert state.working_config["dead_zones"]["stick"] == "not_a_number"

    def test_string_original_kept_as_string(self, state):
        # When the YAML value was already a string, no float conversion is attempted.
        state.working_config = {"dead_zones": {"stick": "0.15"}}
        state.dz_entries = {("dead_zones", "stick"): mock_entry("0.20")}
        state.flush_dead_zones()
        assert state.working_config["dead_zones"]["stick"] == "0.20"
        assert isinstance(state.working_config["dead_zones"]["stick"], str)

    def test_multiple_entries_all_flushed(self, state):
        state.working_config = {"dead_zones": {"stick": 0.15, "throttle": 0.04}}
        state.dz_entries = {
            ("dead_zones", "stick"): mock_entry("0.20"),
            ("dead_zones", "throttle"): mock_entry("0.06"),
        }
        state.flush_dead_zones()
        assert state.working_config["dead_zones"]["stick"] == pytest.approx(0.20)
        assert state.working_config["dead_zones"]["throttle"] == pytest.approx(0.06)

    def test_whitespace_stripped_before_conversion(self, state):
        state.working_config = {"dead_zones": {"stick": 0.15}}
        state.dz_entries = {("dead_zones", "stick"): mock_entry("  0.20  ")}
        state.flush_dead_zones()
        assert state.working_config["dead_zones"]["stick"] == pytest.approx(0.20)

    def test_no_entries_leaves_config_unchanged(self, state):
        state.working_config = {"dead_zones": {"stick": 0.15}}
        state.dz_entries = {}
        state.flush_dead_zones()
        assert state.working_config["dead_zones"]["stick"] == pytest.approx(0.15)


# ---------------------------------------------------------------------------
# InputSettingsMenuState.on_confirmed
# ---------------------------------------------------------------------------


class TestOnConfirmed:
    def test_none_value_leaves_config_unchanged(self, state):
        state.active_dialog = MagicMock()
        state.working_config = {"global": {"pause": "escape"}}
        state.binding_labels = {}
        state.on_confirmed(("global", "pause"), None, None)
        assert state.working_config["global"]["pause"] == "escape"

    def test_active_dialog_cleared_regardless_of_value(self, state):
        state.active_dialog = MagicMock()
        state.working_config = {"global": {"pause": "escape"}}
        state.binding_labels = {}
        state.on_confirmed(("global", "pause"), None, None)
        assert state.active_dialog is None

    def test_new_value_updates_config(self, state):
        state.active_dialog = MagicMock()
        state.working_config = {"global": {"pause": "escape"}}
        state.binding_labels = {}
        state.on_confirmed(("global", "pause"), "button", "f1")
        assert state.working_config["global"]["pause"] == "f1"

    def test_deep_nested_path_updated(self, state):
        state.active_dialog = MagicMock()
        state.working_config = {
            "input_type": "keyboard",
            "contexts": {"flight": {"keyboard": {"fire": "space"}}},
        }
        state.binding_labels = {}
        path = ("contexts", "flight", "keyboard", "fire")
        state.on_confirmed(path, "button", "f")
        assert state.working_config["contexts"]["flight"]["keyboard"]["fire"] == "f"

    def test_binding_label_updated_when_path_present(self, state):
        state.active_dialog = MagicMock()
        state.working_config = {
            "input_type": "keyboard",
            "contexts": {"flight": {"keyboard": {"fire": "space"}}},
        }
        path = ("contexts", "flight", "keyboard", "fire")
        lbl = MagicMock()
        state.binding_labels = {path: lbl}
        state.on_confirmed(path, "button", "f")
        lbl.__setitem__.assert_called_once()
        key, value = lbl.__setitem__.call_args[0]
        assert key == "text"
        assert "Button" in value

    def test_binding_label_not_touched_when_path_absent(self, state):
        state.active_dialog = MagicMock()
        state.working_config = {"global": {"pause": "escape"}}
        other_lbl = MagicMock()
        state.binding_labels = {("other", "key"): other_lbl}
        state.on_confirmed(("global", "pause"), "button", "f1")
        other_lbl.__setitem__.assert_not_called()

    def test_axis_binding_label_shows_axis_prefix(self, state):
        state.active_dialog = MagicMock()
        state.working_config = {
            "input_type": "gamepad",
            "contexts": {"flight": {"gamepad": {"throttle": "right_trigger"}}},
        }
        path = ("contexts", "flight", "gamepad", "throttle")
        lbl = MagicMock()
        state.binding_labels = {path: lbl}
        state.on_confirmed(path, "axis", "right_trigger")
        _, value = lbl.__setitem__.call_args[0]
        assert "Axis" in value
