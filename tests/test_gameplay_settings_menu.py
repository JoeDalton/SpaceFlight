"""
Unit tests for the gameplay settings menu, its drop-down widget, and the
settings hub navigation to it.

Only the pure data + callback methods of the menu are exercised (mock app, no
DirectGui), mirroring tests/test_graphics_settings_menu.py. The drop-down
(:class:`CustomDropDown`) needs no window, so it is built for real.
"""

import copy
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from direct.gui import DirectGuiGlobals as DGG
from direct.showbase.MessengerGlobal import messenger
from direct.showbase.ShowBaseGlobal import aspect2d
from panda3d.core import Filename, Loader, NodePath

from space_flight import DATAFILES_PATH
from space_flight.global_architecture.gameplay_settings import (
    CUSTOM_PRESET,
    DEFAULT_PRESET,
    GameplaySettings,
    load_presets,
)
from space_flight.menus.gameplay_settings_menu_state import (
    _CHECKBOXES,
    _SLIDERS,
    GameplaySettingsMenuState,
    _snap,
)
from space_flight.menus.graphics_settings_menu_state import _get_by_path
from space_flight.menus.menu_utils import CustomDropDown
from space_flight.menus.settings_menu_state import SettingsMenuState

PRESETS = load_presets()


@pytest.fixture
def state():
    """
    A GameplaySettingsMenuState with a mock app holding the shipped presets, a
    working config on the default preset, and a mocked preset drop-down.
    """
    app = MagicMock()
    app.gameplay_settings.presets = PRESETS
    s = GameplaySettingsMenuState(app=app)
    s.working_config = {"preset": DEFAULT_PRESET, **copy.deepcopy(PRESETS["normal"])}
    s.preset_menu = MagicMock()
    s.rebuild_scroll = MagicMock()
    return s


def _mock_slider(value):
    """A stand-in CustomSlider exposing get_value()."""
    slider = MagicMock()
    slider.get_value.return_value = value
    return slider


def _leaf_paths(config: dict, prefix: tuple = ()) -> set[tuple]:
    """:return: The paths of every non-dict value of a nested dict."""
    paths = set()
    for key, value in config.items():
        if isinstance(value, dict):
            paths |= _leaf_paths(value, (*prefix, key))
        else:
            paths.add((*prefix, key))
    return paths


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


class TestTables:
    def test_every_setting_has_a_row(self, state):
        """Every value the settings hold is shown, as a slider or a checkbox."""
        values = GameplaySettings.sanitise({})
        row_paths = {row["path"] for row in state.make_row_data() if "path" in row}
        assert row_paths == _leaf_paths(values)

    def test_slider_ranges_are_the_sanitised_limits(self):
        """A slider can reach any value sanitise() keeps, and no other."""
        defaults = GameplaySettings.sanitise({})
        for key, (_label, (low, high), _step, _fmt) in _SLIDERS.items():
            for side in ("player", "bots"):
                try:
                    _get_by_path(defaults[side], key)
                except KeyError:
                    continue  # A player-only setting
                config = {side: {}}
                section = config[side]
                for part in key[:-1]:
                    section = section.setdefault(part, {})
                section[key[-1]] = -1e9
                low_out = _get_by_path(GameplaySettings.sanitise(config)[side], key)
                section[key[-1]] = 1e9
                high_out = _get_by_path(GameplaySettings.sanitise(config)[side], key)
                assert (low_out, high_out) == (low, high), key

    def test_every_preset_value_sits_on_its_slider_step(self):
        """Preset values read exactly on their sliders' readouts."""
        for name, values in PRESETS.items():
            for side in ("player", "bots"):
                for key, (_label, _range, step, _fmt) in _SLIDERS.items():
                    try:
                        value = _get_by_path(values[side], key)
                    except KeyError:
                        continue
                    assert _snap(value, step) == pytest.approx(value), (name, key)

    @pytest.mark.parametrize(
        "value, step, expected",
        [(1.1000000238, 0.05, 1.1), (0.024, 0.05, 0.0), (29.6, 1.0, 30.0)],
    )
    def test_snap(self, value, step, expected):
        assert _snap(value, step) == expected


# ---------------------------------------------------------------------------
# make_row_data / preset_options
# ---------------------------------------------------------------------------


class TestMakeRowData:
    def test_one_header_per_side_in_order(self, state):
        headers = [
            row["text"] for row in state.make_row_data() if row["kind"] == "header"
        ]
        assert headers == ["Player", "Bots"]

    def test_header_precedes_its_sides_rows(self, state):
        side = None
        for row in state.make_row_data():
            if row["kind"] == "header":
                side = row["text"].lower()
            else:
                assert row["path"][0] == side

    def test_player_only_rows_are_not_shown_for_bots(self, state):
        bot_rows = {
            row["path"][1:]
            for row in state.make_row_data()
            if "path" in row and row["path"][0] == "bots"
        }
        assert ("lead_indicator",) not in bot_rows
        assert ("collision_damage_multiplier",) not in bot_rows

    def test_row_kinds_match_the_tables(self, state):
        for row in state.make_row_data():
            if row["kind"] == "slider":
                assert row["path"][1:] in _SLIDERS
            elif row["kind"] == "checkbox":
                assert row["path"][1:] in _CHECKBOXES


class TestPresetOptions:
    def test_presets_in_file_order_then_custom(self, state):
        assert state.preset_options() == [
            ("Easy", "easy"),
            ("Normal", "normal"),
            ("Hard", "hard"),
            ("Ace", "ace"),
            ("Custom", CUSTOM_PRESET),
        ]


# ---------------------------------------------------------------------------
# select_preset
# ---------------------------------------------------------------------------


class TestSelectPreset:
    def test_named_preset_loads_its_values_and_rebuilds_rows(self, state):
        state.select_preset("ace")

        assert state.working_config == {"preset": "ace", **PRESETS["ace"]}
        state.rebuild_scroll.assert_called_once()

    def test_loaded_values_are_a_copy(self, state):
        state.select_preset("ace")
        state.working_config["bots"]["damage_multiplier"] = 99.0

        assert PRESETS["ace"]["bots"]["damage_multiplier"] != 99.0

    def test_custom_keeps_the_current_values(self, state):
        state.select_preset("hard")
        state.rebuild_scroll.reset_mock()

        state.select_preset(CUSTOM_PRESET)

        assert state.working_config == {"preset": CUSTOM_PRESET, **PRESETS["hard"]}
        state.rebuild_scroll.assert_not_called()


# ---------------------------------------------------------------------------
# on_slider / on_checkbox_toggle
# ---------------------------------------------------------------------------


class TestOnSlider:
    PATH = ("bots", "auto_aim", "lock_delay_s")

    def test_stores_snapped_value_updates_label_and_switches_to_custom(self, state):
        state.sliders = {self.PATH: _mock_slider(1.512)}
        state.slider_value_labels = {self.PATH: MagicMock()}

        state.on_slider(self.PATH)

        assert state.working_config["bots"]["auto_aim"]["lock_delay_s"] == 1.5
        state.slider_value_labels[self.PATH].__setitem__.assert_called_once_with(
            "text", "1.50 s"
        )
        assert state.working_config["preset"] == CUSTOM_PRESET
        state.preset_menu.set_value.assert_called_once_with(CUSTOM_PRESET)

    def test_unchanged_value_keeps_the_preset(self, state):
        """
        A slider reports its (single precision) value when built: that does not
        switch to Custom.
        """
        path = ("player", "damage_multiplier")
        stored = _get_by_path(state.working_config, path)
        state.sliders = {path: _mock_slider(float(np.float32(stored)))}
        state.slider_value_labels = {path: MagicMock()}

        state.on_slider(path)

        assert state.working_config["preset"] == DEFAULT_PRESET
        state.preset_menu.set_value.assert_not_called()

    def test_does_not_write_back_to_slider(self, state):
        state.sliders = {self.PATH: _mock_slider(1.512)}
        state.slider_value_labels = {self.PATH: MagicMock()}

        state.on_slider(self.PATH)

        state.sliders[self.PATH].set_value.assert_not_called()


class TestOnCheckboxToggle:
    PATH = ("player", "lead_indicator")

    def test_stores_bool_and_switches_to_custom(self, state):
        state.on_checkbox_toggle(0, self.PATH)

        assert state.working_config["player"]["lead_indicator"] is False
        assert state.working_config["preset"] == CUSTOM_PRESET
        state.preset_menu.set_value.assert_called_once_with(CUSTOM_PRESET)

    def test_unchanged_value_keeps_the_preset(self, state):
        state.on_checkbox_toggle(1, self.PATH)

        assert state.working_config["preset"] == DEFAULT_PRESET
        state.preset_menu.set_value.assert_not_called()


class TestMarkCustom:
    def test_already_custom_leaves_the_drop_down_alone(self, state):
        state.working_config["preset"] = CUSTOM_PRESET

        state.mark_custom()

        state.preset_menu.set_value.assert_not_called()


# ---------------------------------------------------------------------------
# save / cancel
# ---------------------------------------------------------------------------


class TestSaveCancel:
    def test_save_writes_and_pops(self, state):
        state.save()

        state.app.gameplay_settings.save.assert_called_once_with(state.working_config)
        state.app.state_manager.pop.assert_called_once()

    def test_cancel_pops_without_saving(self, state):
        state.cancel()

        state.app.gameplay_settings.save.assert_not_called()
        state.app.state_manager.pop.assert_called_once()


# ---------------------------------------------------------------------------
# CustomDropDown
# ---------------------------------------------------------------------------


def _load_geom(egg: str, names: tuple[str, ...]) -> tuple[NodePath, ...]:
    """Load a menu egg without a window and return its named sub-nodes."""
    path = Filename.fromOsSpecific(str(DATAFILES_PATH / "menus" / egg))
    model = NodePath(Loader.getGlobalPtr().loadSync(path))
    return tuple(model.find(f"**/{name}") for name in names)


@pytest.fixture(scope="module")
def menu_models():
    """The menus' button and arrow geometry, as MenuModels holds it."""
    return SimpleNamespace(
        button_geom=_load_geom(
            "button_map.egg", ("ready", "click", "hover", "disabled")
        ),
        inc_geom=_load_geom("inc_map.egg", ("inc_ready",)),
    )


@pytest.fixture
def drop_down(menu_models):
    """A real drop-down over three options, "b" selected, its command a mock."""
    widget = CustomDropDown(
        app=SimpleNamespace(menu_models=menu_models),
        pos=(0.1, 0, 0.5),
        options=[("A", "a"), ("B", "b"), ("C", "c")],
        value="b",
        command=MagicMock(),
    )
    yield widget
    widget.destroy()


class TestCustomDropDown:
    def test_starts_closed_showing_the_selected_label(self, drop_down):
        assert not drop_down.is_open
        assert drop_down.get_value() == "b"
        assert drop_down.head.button["text"] == "B"

    def test_clicking_the_head_opens_the_list(self, drop_down):
        drop_down.head.button.commandFunc(None)  # As a click does

        assert drop_down.is_open
        assert [button.button["text"] for button in drop_down.item_buttons] == [
            "A",
            "B",
            "C",
        ]

    def test_list_stacks_under_the_head_with_the_selection_pressed(
        self, drop_down, menu_models
    ):
        drop_down.open()

        heights = [button.button.getZ(aspect2d) for button in drop_down.item_buttons]
        assert all(z < 0.5 for z in heights)
        assert heights == sorted(heights, reverse=True)
        pressed = [
            button.button["geom"] == menu_models.button_geom[1]
            for button in drop_down.item_buttons
        ]
        assert pressed == [False, True, False]

    def test_open_list_is_clicked_and_drawn_above_every_other_widget(self, drop_down):
        other = aspect2d.attachNewNode("otherWidget")
        try:
            drop_down.open()

            # Last under aspect2d, in the popup bin
            assert aspect2d.getChildren()[-1] == drop_down.popup_root
            assert drop_down.popup_root.getBinName() == "gui-popup"
            # The catcher comes before the option buttons, which win the clicks
            children = list(drop_down.popup_root.getChildren())
            catcher_index = children.index(drop_down.click_catcher)
            for button in drop_down.item_buttons:
                assert children.index(button.button) > catcher_index
        finally:
            other.removeNode()

    def test_opening_twice_builds_one_list(self, drop_down):
        drop_down.open()
        drop_down.open()

        assert len(drop_down.item_buttons) == 3
        assert aspect2d.findAllMatches("dropDownPopup").getNumPaths() == 1

    def test_clicking_an_option_selects_it_and_closes(self, drop_down):
        drop_down.open()
        popup_root = drop_down.popup_root

        drop_down.item_buttons[2].button.commandFunc(None)  # As a click does

        drop_down.command.assert_called_once_with("c")
        assert drop_down.get_value() == "c"
        assert drop_down.head.button["text"] == "C"
        assert not drop_down.is_open
        assert popup_root.isEmpty()

    def test_clicking_elsewhere_closes_without_changing_the_value(self, drop_down):
        drop_down.open()
        catcher = drop_down.click_catcher

        messenger.send(DGG.B1PRESS + catcher.guiId, [None])  # A press on it

        assert not drop_down.is_open
        assert drop_down.get_value() == "b"
        drop_down.command.assert_not_called()

    def test_set_value_selects_without_calling_the_command(self, drop_down):
        drop_down.set_value("a")

        assert drop_down.get_value() == "a"
        assert drop_down.head.button["text"] == "A"
        drop_down.command.assert_not_called()

    def test_destroy_closes_the_list(self, drop_down):
        drop_down.open()
        popup_root = drop_down.popup_root

        drop_down.destroy()

        assert popup_root.isEmpty()


# ---------------------------------------------------------------------------
# SettingsMenuState navigation
# ---------------------------------------------------------------------------


class TestSettingsHubNavigation:
    def test_gameplay_button_pushes_gameplay_state(self):
        app = MagicMock()
        hub = SettingsMenuState(app=app)

        hub.enter_gameplay_settings()

        app.state_manager.push.assert_called_once_with(
            app.state_manager.GAMEPLAY_SETTINGS_STATE
        )
