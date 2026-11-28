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
    _DISCRETE_SLIDERS,
    _SCALE_PRESET_ROWS,
    GraphicsSettingsMenuState,
    _knob_text,
    _knob_value,
    _pct,
    _scale_options,
    _section_label,
)
from space_flight.menus.menu_utils import get_by_path, set_by_path


@pytest.fixture
def state():
    """A GraphicsSettingsMenuState with a mock app and a valid working config."""
    s = GraphicsSettingsMenuState(app=MagicMock())
    s.working_config = {
        "display": {"mode": "fullscreen", "windowed_size": [1280, 720]},
        "mirror": {"scale": 1.0, "msaa": 0, "fxaa": False, "fsr": False},
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
# Resolution drop-downs (render scale presets)
# ---------------------------------------------------------------------------


class TestScalePresets:
    def test_options_run_native_to_ultra_performance(self):
        options = _scale_options(1.0)
        assert options[0] == ("Native (100%)", 1.0)
        assert options[-1] == ("Ultra Performance (33%)", 0.33)
        assert [label for label, _ in options[1:5]] == [
            "Ultra Quality (77%)",
            "Quality (67%)",
            "Balanced (59%)",
            "Performance (50%)",
        ]

    def test_a_saved_scale_no_preset_has_is_offered_as_custom(self):
        assert _scale_options(0.752)[-1] == ("Custom (75%)", 0.752)
        assert len(_scale_options(0.67)) == 6  # a preset: no Custom

    @pytest.mark.parametrize("path", list(_SCALE_PRESET_ROWS))
    def test_every_preset_survives_sanitise(self, state, path):
        """Saving never clamps a resolution the drop-down offered."""
        for _label, scale in _scale_options(1.0):
            state.set_scale_value(path, scale)
            config = GraphicsSettings.sanitise(state.working_config)
            saved = (
                WorldSettings.from_dict(config["world"]).render.scale
                if path[0] == "world"
                else get_by_path(config, path)
            )
            assert saved == pytest.approx(scale)

    def test_the_view_scale_goes_to_the_world(self, state):
        state.set_scale_value(("world", "render", "scale"), 0.59)
        assert state.working_config["world"]["overrides"] == {"render": {"scale": 0.59}}

    def test_the_mirror_scale_goes_to_the_mirror_section(self, state):
        state.set_scale_value(("mirror", "scale"), 0.33)
        assert state.working_config["mirror"]["scale"] == 0.33

    def test_an_unchanged_scale_stores_nothing(self, state):
        state.set_scale_value(("world", "render", "scale"), 1.0)
        assert state.working_config["world"]["overrides"] == {}


# ---------------------------------------------------------------------------
# make_row_data
# ---------------------------------------------------------------------------


class TestMakeRowData:
    def test_one_header_per_yaml_section(self, state):
        """The display, then WorldBuilder's render section (the view's scale
        and anti-aliasing, near the top), the game's other sections, then
        the world's other sections."""
        headers = [r["text"] for r in state.make_row_data() if r["kind"] == "header"]
        world = WorldSettings.schema()["sections"]
        render = next(
            section["label"] for section in world if section["id"] == "render"
        )
        assert headers == [_section_label("display"), render] + [
            _section_label(s) for s in ("mirror", "compatibility", "hud", "world")
        ] + [
            section["label"]
            for section in world
            if section["id"] not in ("display", "render")
        ]

    def test_headers_use_yaml_section_names(self):
        """Section titles must read as the yaml's own section names, not an
        invented label."""
        assert _section_label("display") == "Display"
        assert _section_label("world") == "World"
        assert _section_label("hud") == "HUD"

    def test_mode_row_present_once(self, state):
        modes = [r for r in state.make_row_data() if r["kind"] == "mode"]
        assert len(modes) == 1

    def test_the_resolutions_are_preset_drop_downs(self, state):
        paths = [
            r["path"] for r in state.make_row_data() if r["kind"] == "scale_preset"
        ]
        assert paths == [("world", "render", "scale"), ("mirror", "scale")]

    def test_the_frame_cap_follows_the_display_mode(self, state):
        """WorldBuilder's display section, under the game's display header."""
        rows = state.make_row_data()
        mode = next(i for i, r in enumerate(rows) if r["kind"] == "mode")
        assert rows[mode + 1]["path"] == ("world", "display", "frame_cap")

    def test_the_views_render_rows_follow_the_display(self, state):
        """WorldBuilder's render section, near the top: no preset (it has no
        levels), its knobs in the schema's order, the scale as a preset
        drop-down, the upscaler as an FSR 1 checkbox."""
        rows = state.make_row_data()
        start = next(i for i, r in enumerate(rows) if r["kind"] == "mode") + 2
        assert rows[start]["kind"] == "header"
        kinds = [(r["kind"], r["path"][-1]) for r in rows[start + 1 : start + 6]]
        assert kinds == [
            ("scale_preset", "scale"),
            ("discrete", "msaa"),
            ("world_knob", "fxaa"),
            ("world_switch", "upscaler"),
            ("world_knob", "sharpness"),
        ]
        assert rows[start + 4]["label"] == "FSR 1"
        assert rows[start + 6]["text"] == _section_label("mirror")

    def test_the_mirror_rows(self, state):
        rows = state.make_row_data()
        header = next(
            i for i, r in enumerate(rows) if r.get("text") == _section_label("mirror")
        )
        assert [(r["kind"], r["path"]) for r in rows[header + 1 : header + 5]] == [
            ("scale_preset", ("mirror", "scale")),
            ("discrete", ("mirror", "msaa")),
            ("checkbox", ("mirror", "fxaa")),
            ("checkbox", ("mirror", "fsr")),
        ]

    def test_every_checkbox_path_appears(self, state):
        paths = [r["path"] for r in state.make_row_data() if r["kind"] == "checkbox"]
        assert set(paths) == {
            ("mirror", "fxaa"),
            ("mirror", "fsr"),
            ("compatibility", "alternate_model_orientation"),
            ("hud", "fps_counter"),
        }

    def test_every_world_knob_appears_once_advanced_included(self, state):
        rows = state.make_row_data()
        kinds = ("world_knob", "world_switch", "scale_preset", "discrete")
        paths = [
            r["path"] for r in rows if r["kind"] in kinds and r["path"][0] == "world"
        ]
        expected = [
            ("world", section, name)
            for section, name, _knob, _value in WorldSettings().knobs()
        ]
        # The display and render sections first (near the top), the rest in
        # schema order
        top = [path for path in expected if path[1] == "display"] + [
            path for path in expected if path[1] == "render"
        ]
        assert paths == top + [path for path in expected if path not in top]
        assert ("world", "terrain", "workers") in paths  # an advanced knob

    def test_world_presets_whole_then_per_section(self, state):
        paths = [r["path"] for r in state.make_row_data() if r["kind"] == "world_level"]
        sections = [
            s["id"] for s in WorldSettings.schema()["sections"] if s["levelled"]
        ]
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


# ---------------------------------------------------------------------------
# The view's FSR 1 checkbox and the mirror's rows
# ---------------------------------------------------------------------------


class TestFsrSwitch:
    PATH = ("world", "render", "upscaler")

    def test_checked_is_fsr1_unchecked_bilinear(self, state):
        state.on_checkbox_toggle(1, self.PATH)
        assert WorldSettings.from_dict(state.working_config["world"]).render.fsr
        state.on_checkbox_toggle(0, self.PATH)
        assert not WorldSettings.from_dict(state.working_config["world"]).render.fsr
        assert state.working_config["world"]["overrides"] == {}

    def test_the_unchanged_value_stores_nothing(self, state):
        """A checkbox reports its value when built: no override."""
        state.on_checkbox_toggle(0, self.PATH)
        assert state.working_config["world"]["overrides"] == {}


@pytest.mark.parametrize("key", ["fxaa", "fsr"])
def test_the_mirror_switches_store_into_the_mirror_section(state, key):
    state.on_checkbox_toggle(1, ("mirror", key))
    assert state.working_config["mirror"][key] is True


def test_the_mirror_msaa_stops_are_the_sanitised_values():
    from space_flight.global_architecture.graphics_settings import _VALID_MIRROR_MSAA

    _label, values, labels = _DISCRETE_SLIDERS[("mirror", "msaa")]
    assert values == _VALID_MIRROR_MSAA
    assert labels[0] == "Off" and labels[-1] == "16x"


def test_the_view_msaa_stops_are_worldbuilders_choices():
    _label, values, labels = _DISCRETE_SLIDERS[("world", "render", "msaa")]
    assert list(values) == _knob("render", "msaa")["choices"] == list(labels)


# ---------------------------------------------------------------------------
# on_discrete_slider (both MSAA rows)
# ---------------------------------------------------------------------------


def _msaa(state, path):
    """:return: The stored MSAA of *path*, as samples"""
    if path[0] == "world":
        return WorldSettings.from_dict(state.working_config["world"]).render.msaa
    return get_by_path(state.working_config, path)


@pytest.mark.parametrize("path", [("world", "render", "msaa"), ("mirror", "msaa")])
class TestOnDiscreteSlider:
    @pytest.mark.parametrize(
        "slider_value,expected_msaa,expected_label",
        [
            (0.0, 0, "Off"),
            (0.4, 0, "Off"),
            (1.0, 2, "2x"),
            (2.4, 4, "4x"),
            (3.0, 8, "8x"),
            (4.0, 16, "16x"),
        ],
    )
    def test_rounds_to_nearest_stop(
        self, state, path, slider_value, expected_msaa, expected_label
    ):
        state.sliders = {path: mock_slider(slider_value)}
        state.slider_value_labels = {path: MagicMock()}

        state.on_discrete_slider(path)

        assert _msaa(state, path) == expected_msaa
        state.slider_value_labels[path].__setitem__.assert_called_once_with(
            "text", expected_label
        )

    def test_out_of_range_value_is_clamped(self, state, path):
        state.sliders = {path: mock_slider(99.0)}
        state.slider_value_labels = {path: MagicMock()}
        state.on_discrete_slider(path)
        assert _msaa(state, path) == 16

    def test_does_not_write_back_to_slider(self, state, path):
        # Regression: writing the value back from inside the ADJUST handler
        # re-enqueues ADJUST forever and freezes the game. The handler must
        # never call set_value / mutate the slider.
        slider = mock_slider(2.0)
        state.sliders = {path: slider}
        state.slider_value_labels = {path: MagicMock()}

        state.on_discrete_slider(path)

        slider.set_value.assert_not_called()
        slider.slider.setValue.assert_not_called()


def test_the_view_msaa_slider_at_its_value_stores_nothing(state):
    """A slider reports its value when built: no world override."""
    path = ("world", "render", "msaa")
    state.sliders = {path: mock_slider(0.0)}
    state.slider_value_labels = {path: MagicMock()}
    state.on_discrete_slider(path)
    assert state.working_config["world"]["overrides"] == {}
