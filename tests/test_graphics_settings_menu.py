"""
Unit tests for the graphics settings menu and the settings hub navigation.

Only the pure data + callback methods are exercised (mock app, no DirectGui),
mirroring tests/test_input_settings.py. UI construction (sliders, checkbox)
needs a real window and is verified manually / via integration.
"""

from unittest.mock import MagicMock

import pytest

from space_flight.global_architecture.graphics_settings import GraphicsSettings
from space_flight.menus.graphics_settings_menu_state import (
    _SCALE_SLIDERS,
    GraphicsSettingsMenuState,
    _get_by_path,
    _pct,
    _section_label,
    _set_by_path,
)
from space_flight.menus.settings_menu_state import SettingsMenuState


@pytest.fixture
def state():
    """A GraphicsSettingsMenuState with a mock app and a valid working config."""
    s = GraphicsSettingsMenuState(app=MagicMock())
    s.working_config = {
        "display": {"mode": "fullscreen", "windowed_size": [1280, 720]},
        "render": {"scale": 1.0, "reflection_scale": 0.5, "mirror_scale": 1.0},
        "antialiasing": {"msaa": 0, "fxaa": False},
        "compatibility": {"alternate_model_orientation": False},
        "clouds": {"quality": "high"},
        "hud": {"fps_counter": True},
    }
    return s


def _mock_slider(value):
    """A stand-in CustomSlider exposing get_value() and a set_value spy."""
    sl = MagicMock()
    sl.get_value.return_value = value
    return sl


# ---------------------------------------------------------------------------
# Path / format helpers
# ---------------------------------------------------------------------------


class TestPathHelpers:
    def test_get_by_path_nested(self):
        assert _get_by_path({"a": {"b": {"c": 3}}}, ("a", "b", "c")) == 3

    def test_set_by_path_nested(self):
        d = {"a": {"b": {"c": 1}}}
        _set_by_path(d, ("a", "b", "c"), 9)
        assert d["a"]["b"]["c"] == 9

    def test_set_by_path_leaves_siblings(self):
        d = {"a": {"b": 1, "c": 2}}
        _set_by_path(d, ("a", "b"), 9)
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
        state.sliders = {path: _mock_slider(0.65)}
        state.slider_value_labels = {path: MagicMock()}

        state.on_scale_slider(path)

        assert state.working_config["render"]["scale"] == pytest.approx(0.65)
        state.slider_value_labels[path].__setitem__.assert_called_once_with(
            "text", "65%"
        )

    def test_works_for_reflection_and_mirror_paths(self, state):
        for path, value in [
            (("render", "reflection_scale"), 0.3),
            (("render", "mirror_scale"), 0.8),
        ]:
            state.sliders = {path: _mock_slider(value)}
            state.slider_value_labels = {path: MagicMock()}
            state.on_scale_slider(path)
            assert _get_by_path(state.working_config, path) == pytest.approx(value)


class TestScaleSliderRanges:
    @pytest.mark.parametrize("path", list(_SCALE_SLIDERS))
    def test_slider_range_is_the_sanitised_limits(self, path):
        """
        A slider can reach any value sanitise() keeps, and no other: saving
        never clamps a value the slider showed.
        """
        _label, (low, high) = _SCALE_SLIDERS[path]
        config = {path[0]: {path[1]: -1e9}}
        assert _get_by_path(GraphicsSettings.sanitise(config), path) == low
        config = {path[0]: {path[1]: 1e9}}
        assert _get_by_path(GraphicsSettings.sanitise(config), path) == high


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
        state.sliders = {self.PATH: _mock_slider(slider_value)}
        state.slider_value_labels = {self.PATH: MagicMock()}

        state.on_discrete_slider(self.PATH)

        assert state.working_config["antialiasing"]["msaa"] == expected_msaa
        state.slider_value_labels[self.PATH].__setitem__.assert_called_once_with(
            "text", expected_label
        )

    def test_out_of_range_value_is_clamped(self, state):
        state.sliders = {self.PATH: _mock_slider(99.0)}
        state.slider_value_labels = {self.PATH: MagicMock()}
        state.on_discrete_slider(self.PATH)
        assert state.working_config["antialiasing"]["msaa"] == 8

    def test_does_not_write_back_to_slider(self, state):
        # Regression: writing the value back from inside the ADJUST handler
        # re-enqueues ADJUST forever and freezes the game. The handler must
        # never call set_value / mutate the slider.
        slider = _mock_slider(2.0)
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
                "clouds",
                "hud",
            )
        ]

    def test_headers_use_yaml_section_names(self):
        """Section titles must read as the yaml's own section names, not an
        invented label."""
        assert _section_label("display") == "Display"
        assert _section_label("clouds") == "Clouds"
        assert _section_label("hud") == "HUD"

    def test_mode_row_present_once(self, state):
        modes = [r for r in state.make_row_data() if r["kind"] == "mode"]
        assert len(modes) == 1

    def test_every_slider_path_appears(self, state):
        paths = [r["path"] for r in state.make_row_data() if r["kind"] == "slider"]
        assert set(paths) == {
            ("render", "scale"),
            ("render", "reflection_scale"),
            ("render", "mirror_scale"),
        }

    def test_every_discrete_path_appears(self, state):
        paths = [r["path"] for r in state.make_row_data() if r["kind"] == "discrete"]
        assert set(paths) == {("antialiasing", "msaa"), ("clouds", "quality")}

    def test_every_checkbox_path_appears(self, state):
        paths = [r["path"] for r in state.make_row_data() if r["kind"] == "checkbox"]
        assert set(paths) == {
            ("antialiasing", "fxaa"),
            ("compatibility", "alternate_model_orientation"),
            ("hud", "fps_counter"),
        }

    def test_header_precedes_its_section_rows(self, state):
        rows = state.make_row_data()
        kinds = [r["kind"] for r in rows]
        texts = [r.get("text") for r in rows]
        clouds_header_idx = texts.index(_section_label("clouds"))
        cloud_row_idx = next(
            i for i, r in enumerate(rows) if r.get("path") == ("clouds", "quality")
        )
        assert clouds_header_idx < cloud_row_idx
        assert kinds[clouds_header_idx] == "header"


# ---------------------------------------------------------------------------
# Cloud quality slider (on_discrete_slider)
# ---------------------------------------------------------------------------


class TestOnCloudQualitySlider:
    PATH = ("clouds", "quality")

    @pytest.mark.parametrize(
        "slider_value,expected,expected_label",
        [
            (0.0, "low", "Low"),
            (0.4, "low", "Low"),
            (1.0, "mid", "Mid"),
            (1.6, "high", "High"),
            (3.0, "ultra", "Ultra"),
        ],
    )
    def test_rounds_to_nearest_stop(
        self, state, slider_value, expected, expected_label
    ):
        state.sliders = {self.PATH: _mock_slider(slider_value)}
        state.slider_value_labels = {self.PATH: MagicMock()}

        state.on_discrete_slider(self.PATH)

        assert state.working_config["clouds"]["quality"] == expected
        state.slider_value_labels[self.PATH].__setitem__.assert_called_once_with(
            "text", expected_label
        )

    @pytest.mark.parametrize("value,expected", [(99.0, "ultra"), (-5.0, "low")])
    def test_out_of_range_value_is_clamped(self, state, value, expected):
        state.sliders = {self.PATH: _mock_slider(value)}
        state.slider_value_labels = {self.PATH: MagicMock()}
        state.on_discrete_slider(self.PATH)
        assert state.working_config["clouds"]["quality"] == expected

    def test_does_not_write_back_to_slider(self, state):
        # Same freeze regression as the MSAA slider.
        slider = _mock_slider(2.0)
        state.sliders = {self.PATH: slider}
        state.slider_value_labels = {self.PATH: MagicMock()}

        state.on_discrete_slider(self.PATH)

        slider.set_value.assert_not_called()
        slider.slider.setValue.assert_not_called()

    def test_stores_a_name_the_cloud_model_knows(self, state):
        """The stop values must be CloudQuality names, or a saved setting would
        pass the sanitiser and then silently fall back to HIGH."""
        from space_flight.scenes.cloud import CloudQuality

        for index in range(4):
            state.sliders = {self.PATH: _mock_slider(float(index))}
            state.slider_value_labels = {self.PATH: MagicMock()}
            state.on_discrete_slider(self.PATH)
            CloudQuality(state.working_config["clouds"]["quality"])


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
        assert _get_by_path(state.working_config, path) is expected


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


# ---------------------------------------------------------------------------
# SettingsMenuState navigation
# ---------------------------------------------------------------------------


class TestSettingsHubNavigation:
    def test_input_button_pushes_input_state(self):
        s = SettingsMenuState(app=MagicMock())
        s.enter_input_settings()
        s.app.state_manager.push.assert_called_once_with(
            s.app.state_manager.INPUT_SETTINGS_STATE
        )

    def test_graphics_button_pushes_graphics_state(self):
        s = SettingsMenuState(app=MagicMock())
        s.enter_graphics_settings()
        s.app.state_manager.push.assert_called_once_with(
            s.app.state_manager.GRAPHICS_SETTINGS_STATE
        )

    def test_back_pops(self):
        s = SettingsMenuState(app=MagicMock())
        s.back()
        s.app.state_manager.pop.assert_called_once()
