"""
Unit tests for the graphics settings menu.

Only the pure data + callback methods are exercised (mock app, no DirectGui),
mirroring tests/test_input_settings.py. UI construction (sliders, checkbox)
needs a real window and is verified manually / via integration.
"""

from unittest.mock import MagicMock

import pytest
from menu_fakes import mock_slider
from world_builder.settings import WorldSettings

from space_flight.global_architecture.graphics_settings import GraphicsSettings
from space_flight.menus.graphics_settings_menu_state import (
    _SCALE_SLIDERS,
    GraphicsSettingsMenuState,
    _knob_text,
    _knob_value,
    _pct,
    _section_label,
)
from space_flight.menus.menu_utils import get_by_path, set_by_path


@pytest.fixture
def state():
    """A GraphicsSettingsMenuState with a mock app and a valid working config."""
    s = GraphicsSettingsMenuState(app=MagicMock())
    s.working_config = {
        "display": {"mode": "fullscreen", "windowed_size": [1280, 720]},
        "render": {"scale": 1.0, "mirror_scale": 1.0},
        "antialiasing": {"msaa": 0, "fxaa": False},
        "compatibility": {"alternate_model_orientation": False},
        "hud": {"fps_counter": True},
        "world": {"version": 1, "preset": "high", "overrides": {}},
    }
    return s


def _knob(section: str, name: str) -> dict:
    """:return: A knob's WorldBuilder schema entry"""
    for entry in WorldSettings.schema()["sections"]:
        if entry["id"] == section:
            return next(k for k in entry["knobs"] if k["id"] == name)
    raise KeyError(section)


# ---------------------------------------------------------------------------
# Path / format helpers
# ---------------------------------------------------------------------------


class TestPathHelpers:
    def testget_by_path_nested(self):
        assert get_by_path({"a": {"b": {"c": 3}}}, ("a", "b", "c")) == 3

    def testset_by_path_nested(self):
        d = {"a": {"b": {"c": 1}}}
        set_by_path(d, ("a", "b", "c"), 9)
        assert d["a"]["b"]["c"] == 9

    def testset_by_path_leaves_siblings(self):
        d = {"a": {"b": 1, "c": 2}}
        set_by_path(d, ("a", "b"), 9)
        assert d["a"] == {"b": 9, "c": 2}

    @pytest.mark.parametrize(
        "value,expected", [(1.0, "100%"), (0.5, "50%"), (0.754, "75%"), (0.1, "10%")]
    )
    def test_pct_formats_rounded_percent(self, value, expected):
        assert _pct(value) == expected


# ---------------------------------------------------------------------------
# on_scale_slider
# ---------------------------------------------------------------------------


class TestOnScaleSlider:
    def test_stores_value_and_updates_label(self, state):
        path = ("render", "scale")
        state.sliders = {path: mock_slider(0.65)}
        state.slider_value_labels = {path: MagicMock()}

        state.on_scale_slider(path)

        assert state.working_config["render"]["scale"] == pytest.approx(0.65)
        state.slider_value_labels[path].__setitem__.assert_called_once_with(
            "text", "65%"
        )

    def test_works_for_mirror_path(self, state):
        for path, value in [(("render", "mirror_scale"), 0.8)]:
            state.sliders = {path: mock_slider(value)}
            state.slider_value_labels = {path: MagicMock()}
            state.on_scale_slider(path)
            assert get_by_path(state.working_config, path) == pytest.approx(value)


class TestScaleSliderRanges:
    @pytest.mark.parametrize("path", list(_SCALE_SLIDERS))
    def test_slider_range_is_the_sanitised_limits(self, path):
        """
        A slider can reach any value sanitise() keeps, and no other: saving
        never clamps a value the slider showed.
        """
        _label, (low, high) = _SCALE_SLIDERS[path]
        config = {path[0]: {path[1]: -1e9}}
        assert get_by_path(GraphicsSettings.sanitise(config), path) == low
        config = {path[0]: {path[1]: 1e9}}
        assert get_by_path(GraphicsSettings.sanitise(config), path) == high


# ---------------------------------------------------------------------------
# MSAA slider (on_discrete_slider)
# ---------------------------------------------------------------------------


class TestOnMsaaSlider:
    PATH = ("antialiasing", "msaa")

    @pytest.mark.parametrize(
        "slider_value,expected_msaa,expected_label",
        [
            (0.0, 0, "Off"),
            (0.4, 0, "Off"),
            (1.0, 2, "2x"),
            (2.4, 4, "4x"),
            (3.0, 8, "8x"),
        ],
    )
    def test_rounds_to_nearest_stop(
        self, state, slider_value, expected_msaa, expected_label
    ):
        state.sliders = {self.PATH: mock_slider(slider_value)}
        state.slider_value_labels = {self.PATH: MagicMock()}

        state.on_discrete_slider(self.PATH)

        assert state.working_config["antialiasing"]["msaa"] == expected_msaa
        state.slider_value_labels[self.PATH].__setitem__.assert_called_once_with(
            "text", expected_label
        )

    def test_out_of_range_value_is_clamped(self, state):
        state.sliders = {self.PATH: mock_slider(99.0)}
        state.slider_value_labels = {self.PATH: MagicMock()}
        state.on_discrete_slider(self.PATH)
        assert state.working_config["antialiasing"]["msaa"] == 8

    def test_does_not_write_back_to_slider(self, state):
        # Regression: writing the value back from inside the ADJUST handler
        # re-enqueues ADJUST forever and freezes the game. The handler must
        # never call set_value / mutate the slider.
        slider = mock_slider(2.0)
        state.sliders = {self.PATH: slider}
        state.slider_value_labels = {self.PATH: MagicMock()}

        state.on_discrete_slider(self.PATH)

        slider.set_value.assert_not_called()
        slider.slider.setValue.assert_not_called()


# ---------------------------------------------------------------------------
# make_row_data
# ---------------------------------------------------------------------------


class TestMakeRowData:
    def test_one_header_per_yaml_section(self, state):
        headers = [r["text"] for r in state.make_row_data() if r["kind"] == "header"]
        assert headers == [
            _section_label(s)
            for s in (
                "display",
                "render",
                "antialiasing",
                "compatibility",
                "hud",
                "world",
            )
        ] + [section["label"] for section in WorldSettings.schema()["sections"]]

    def test_headers_use_yaml_section_names(self):
        """Section titles must read as the yaml's own section names, not an
        invented label."""
        assert _section_label("display") == "Display"
        assert _section_label("world") == "World"
        assert _section_label("hud") == "HUD"

    def test_mode_row_present_once(self, state):
        modes = [r for r in state.make_row_data() if r["kind"] == "mode"]
        assert len(modes) == 1

    def test_every_slider_path_appears(self, state):
        paths = [r["path"] for r in state.make_row_data() if r["kind"] == "slider"]
        assert set(paths) == {("render", "scale"), ("render", "mirror_scale")}

    def test_every_discrete_path_appears(self, state):
        paths = [r["path"] for r in state.make_row_data() if r["kind"] == "discrete"]
        assert set(paths) == {("antialiasing", "msaa")}

    def test_every_checkbox_path_appears(self, state):
        paths = [r["path"] for r in state.make_row_data() if r["kind"] == "checkbox"]
        assert set(paths) == {
            ("antialiasing", "fxaa"),
            ("compatibility", "alternate_model_orientation"),
            ("hud", "fps_counter"),
        }

    def test_every_world_knob_appears_once_advanced_included(self, state):
        paths = [r["path"] for r in state.make_row_data() if r["kind"] == "world_knob"]
        expected = [
            ("world", section, name)
            for section, name, _knob, _value in WorldSettings().knobs()
        ]
        assert paths == expected
        assert ("world", "terrain", "workers") in paths  # an advanced knob

    def test_world_presets_whole_then_per_section(self, state):
        paths = [r["path"] for r in state.make_row_data() if r["kind"] == "world_level"]
        sections = [s["id"] for s in WorldSettings.schema()["sections"]]
        assert paths == [("world",)] + [("world", s) for s in sections]

    def test_section_header_precedes_its_preset_and_knobs(self, state):
        rows = state.make_row_data()
        header = next(i for i, r in enumerate(rows) if r.get("text") == "Clouds")
        assert rows[header + 1]["path"] == ("world", "clouds")
        assert rows[header + 2]["path"][:2] == ("world", "clouds")


# ---------------------------------------------------------------------------
# World settings rows
# ---------------------------------------------------------------------------


class TestKnobFormat:
    @pytest.mark.parametrize(
        "section,name,raw,expected",
        [
            ("terrain", "min_level", 2.6, 3),
            ("terrain", "detail_far", 3012.4, 3012.0),
            ("terrain", "split_factor", 1.234, 1.23),
            ("ocean", "reflection_scale", 0.12345, 0.123),
        ],
    )
    def test_value_rounded_to_what_the_knob_keeps(self, section, name, raw, expected):
        assert _knob_value(_knob(section, name), raw) == expected

    @pytest.mark.parametrize(
        "section,name,value,expected",
        [
            ("terrain", "min_level", 2, "2 levels"),
            ("terrain", "detail_far", 4000.0, "4000 m"),
            ("terrain", "split_factor", 2.0, "2.00x"),
            ("terrain", "workers", 0, "0"),
            ("terrain", "texture_size", "2048", "2048 px"),
        ],
    )
    def test_readout_has_the_unit(self, section, name, value, expected):
        assert _knob_text(_knob(section, name), value) == expected


class TestWorldValues:
    def test_level_of_a_preset(self, state):
        assert state.world_level(("world",)) == "high"
        assert state.world_level(("world", "ocean")) == "high"

    def test_choice_value_is_its_label(self, state):
        assert state.world_value(("world", "terrain", "anisotropy")) == "8x"

    def test_set_value_stores_an_override_and_shows_custom(self, state):
        whole, section = MagicMock(), MagicMock()
        state.drop_downs = {("world",): whole, ("world", "terrain"): section}

        state.set_world_value(("world", "terrain", "anisotropy"), "2x")

        assert state.working_config["world"]["overrides"] == {
            "terrain": {"anisotropy": "2x"}
        }
        whole.set_value.assert_called_with("custom")
        section.set_value.assert_called_with("custom")

    def test_value_out_of_range_is_clamped(self, state):
        state.set_world_value(("world", "terrain", "detail_far"), 1e9)
        assert state.world().terrain.detail_far == 10000.0

    def test_other_sections_keep_their_preset(self, state):
        state.set_world_value(("world", "terrain", "textured"), False)
        assert state.world_level(("world", "ocean")) == "high"
        assert state.world_level(("world", "terrain")) == "custom"


class TestOnWorldSlider:
    PATH = ("world", "terrain", "detail_far")

    def _slide(self, state, value):
        state.sliders = {self.PATH: mock_slider(value)}
        state.slider_value_labels = {self.PATH: MagicMock()}
        state.on_world_slider(self.PATH, _knob("terrain", "detail_far"))

    def test_stores_value_and_updates_label(self, state):
        self._slide(state, 3000.2)
        assert state.world().terrain.detail_far == 3000.0
        state.slider_value_labels[self.PATH].__setitem__.assert_called_once_with(
            "text", "3000 m"
        )

    def test_report_on_build_keeps_the_preset(self, state):
        """A slider reports its (float32) value when built: within the stored
        value's rounding, that must not turn the preset into Custom."""
        self._slide(state, 4000.0001)
        assert state.working_config["world"]["overrides"] == {}
        state.slider_value_labels[self.PATH].__setitem__.assert_not_called()

    def test_preset_with_more_decimals_than_shown_kept(self, state):
        """Clouds' Low lighting is 4/9: shown as 0.44x, still the preset."""
        state.working_config["world"] = {"preset": "low", "overrides": {}}
        path = ("world", "clouds", "march_scale")
        state.sliders = {path: mock_slider(0.4444)}
        state.slider_value_labels = {path: MagicMock()}
        state.on_world_slider(path, _knob("clouds", "march_scale"))
        assert state.world_level(("world",)) == "low"

    def test_does_not_write_back_to_slider(self, state):
        self._slide(state, 2000.0)
        slider = state.sliders[self.PATH]
        slider.set_value.assert_not_called()
        slider.slider.setValue.assert_not_called()


class TestSelectWorldLevel:
    @pytest.fixture
    def rebuilt(self, state):
        state.rebuild_scroll = MagicMock()
        state.scroll_list = MagicMock()
        return state

    def test_whole_world_preset(self, rebuilt):
        rebuilt.set_world_value(("world", "terrain", "textured"), False)
        rebuilt.select_world_level(("world",), "low")
        assert rebuilt.working_config["world"] == {
            "version": 1,
            "preset": "low",
            "overrides": {},
        }
        rebuilt.rebuild_scroll.assert_called_once()

    def test_section_preset_leaves_the_others(self, rebuilt):
        rebuilt.select_world_level(("world", "clouds"), "ultra")
        assert rebuilt.world_level(("world", "clouds")) == "ultra"
        assert rebuilt.world_level(("world", "terrain")) == "high"
        assert rebuilt.world_level(("world",)) == "custom"

    def test_custom_keeps_the_values(self, rebuilt):
        drop_down = MagicMock()
        rebuilt.drop_downs = {("world",): drop_down}
        rebuilt.select_world_level(("world",), "custom")
        assert rebuilt.working_config["world"]["preset"] == "high"
        rebuilt.rebuild_scroll.assert_not_called()
        drop_down.set_value.assert_called_once_with("high")

    def test_keeps_the_scroll_position(self, rebuilt):
        bar = {"value": 4.2}
        rebuilt.scroll_list.v_scrollbar = bar
        rebuilt.rebuild_scroll.side_effect = lambda: bar.update(value=0)
        rebuilt.select_world_level(("world",), "mid")
        assert bar["value"] == 4.2


class TestWorldCheckbox:
    def test_stores_into_world(self, state):
        state.on_checkbox_toggle(0, ("world", "ocean", "foam"))
        assert state.world().ocean.foam is False

    def test_report_on_build_keeps_the_preset(self, state):
        state.on_checkbox_toggle(1, ("world", "ocean", "foam"))
        assert state.working_config["world"]["overrides"] == {}


# ---------------------------------------------------------------------------
# on_checkbox_toggle
# ---------------------------------------------------------------------------


class TestOnCheckboxToggle:
    @pytest.mark.parametrize(
        "path",
        [
            ("antialiasing", "fxaa"),
            ("compatibility", "alternate_model_orientation"),
            ("hud", "fps_counter"),
        ],
    )
    @pytest.mark.parametrize(
        "status,expected", [(1, True), (0, False), (True, True), (False, False)]
    )
    def test_stores_bool(self, state, path, status, expected):
        state.on_checkbox_toggle(status, path)
        assert get_by_path(state.working_config, path) is expected


# ---------------------------------------------------------------------------
# select_mode
# ---------------------------------------------------------------------------


class TestSelectMode:
    def test_stores_mode_and_presses_matching_button(self, state):
        fs_btn, win_btn = MagicMock(), MagicMock()
        state.mode_buttons = [("fullscreen", fs_btn), ("windowed", win_btn)]

        state.select_mode("windowed")

        assert state.working_config["display"]["mode"] == "windowed"
        win_btn.set_pressed.assert_called_once()
        fs_btn.reset.assert_called_once()


# ---------------------------------------------------------------------------
# save / cancel
# ---------------------------------------------------------------------------


class TestSaveCancel:
    def test_save_writes_applies_window_and_pops(self, state):
        state.save()
        state.app.graphics_settings.save.assert_called_once_with(state.working_config)
        state.app.graphics_manager.apply_window_settings.assert_called_once()
        state.app.state_manager.pop.assert_called_once()

    def test_cancel_pops_without_saving(self, state):
        state.cancel()
        state.app.graphics_settings.save.assert_not_called()
        state.app.state_manager.pop.assert_called_once()
