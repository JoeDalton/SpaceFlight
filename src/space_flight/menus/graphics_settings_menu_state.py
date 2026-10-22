"""
Graphics settings menu — lets the player view and change display/render options.

Like :mod:`space_flight.menus.input_settings_menu_state`, a deep-copied working
config is edited in memory and written back only on *Save*. Rows are grouped
under one header per top-level section of
datafiles/default_configuration/default_graphics.yaml.

On save the display mode is applied to the live window immediately; every
other setting is read on the next level load (hence the warning shown above
the Save button). See
:class:`~space_flight.global_architecture.graphics_manager.GraphicsManager`.

The WorldBuilder rows (terrain, air, sky, clouds, ocean) are generated from
:meth:`WorldSettings.schema`, so this menu names none of their knobs: a
"World" preset drop-down, then per section a preset drop-down and one row per
knob. They edit ``working_config["world"]`` through :class:`WorldSettings`,
which clamps and validates every value.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from world_builder.settings import WorldSettings

from space_flight.global_architecture.graphics_settings import (
    _MAX_MIRROR,
    _MAX_SCALE,
    _MIN_MIRROR,
    _MIN_SCALE,
    _VALID_MSAA,
    DEFAULT_GRAPHICS_FILE,
    GraphicsSettings,
)
from space_flight.global_architecture.yaml_files import load_yaml
from space_flight.menus.menu_utils import (
    CustomButton,
    CustomDropDown,
    CustomSlider,
    ScrollingSettingsMenuState,
    get_by_path,
    make_action_buttons,
    make_settings_chrome,
    make_warning,
    section_label,
    set_by_path,
)

if TYPE_CHECKING:
    from space_flight.global_architecture.simulator import SpaceFlightSimulator

# Display mode is a small fixed button group.
_MODE_OPTIONS = [("Fullscreen", "fullscreen"), ("Windowed", "windowed")]

# Continuous quality sliders: path -> (label, (min, max)). The ranges are the
# ones sanitise() clamps to.
_SCALE_SLIDERS = {
    ("render", "scale"): ("Render Scale", (_MIN_SCALE, _MAX_SCALE)),
    ("render", "mirror_scale"): ("Mirror Quality", (_MIN_MIRROR, _MAX_MIRROR)),
}

# Sliders over discrete stops: path -> (label, values, value labels). Cheapest
# first, so dragging right costs more, like every other slider here.
_DISCRETE_SLIDERS = {
    ("antialiasing", "msaa"): ("MSAA", _VALID_MSAA, ("Off", "2x", "4x", "8x")),
}

# Checkbox toggles: path -> label.
_CHECKBOXES = {
    ("antialiasing", "fxaa"): "FXAA",
    ("compatibility", "alternate_model_orientation"): "Alternate Model Orientation",
    ("hud", "fps_counter"): "FPS Counter",
}

# Section headers are named after the top-level keys of default_graphics.yaml,
# in the order they appear there; override only where title-casing the key
# reads oddly. The "world" section is listed apart: its rows come from
# WorldBuilder's schema (see make_world_rows).
_SECTIONS = ("display", "render", "antialiasing", "compatibility", "hud")
_SECTION_LABELS = {"hud": "HUD"}

# The world rows' widget paths start with this key, like the config's section
_WORLD = "world"
# A preset drop-down's extra option: the values are no preset's
_CUSTOM = "custom"

# Layout
_SLIDER_X = 0.0
_SLIDER_SCALE = 0.35
_VALUE_LABEL_X = 0.65
_MODE_BUTTON_X = -0.1
_DROP_DOWN_SCALE = 0.17

_ROW_HEIGHT = 0.15
_FRAME_TOP = 0.78
_FRAME_BOTTOM = -0.72
_WARNING_Y = -0.8


def _section_label(name: str) -> str:
    """Return the display header for a top-level graphics.yaml section."""
    return section_label(name, _SECTION_LABELS)


def _pct(value: float) -> str:
    """Format a fraction as a rounded percentage string."""
    return f"{round(value * 100)}%"


def _knob_decimals(knob: dict) -> int:
    """
    :return: The decimals a numeric knob's slider keeps: none for an int,
        else about three significant digits of its range (0.01 over 0.25..2,
        1 m over 500..10000 m)
    """
    if knob["kind"] == "int":
        return 0
    low, high = knob["range"]
    return max(0, 2 - math.floor(math.log10(high - low)))


def _knob_value(knob: dict, raw: float) -> float | int:
    """:return: A numeric knob's slider position as the value to store"""
    if knob["kind"] == "int":
        return int(round(raw))
    return round(raw, _knob_decimals(knob))


def _knob_text(knob: dict, value) -> str:
    """:return: A knob's value readout, with its unit ("2.00x", "4000 m")"""
    if knob["kind"] == "float":
        value = f"{value:.{_knob_decimals(knob)}f}"
    unit = knob["unit"]
    if not unit:
        return str(value)
    return f"{value}{unit}" if unit == "x" else f"{value} {unit}"


def _level_options(schema: dict) -> list[tuple[str, str]]:
    """:return: A preset drop-down's (label, value) options: the levels, then
    Custom"""
    return [(level["label"], level["id"]) for level in schema["levels"]] + [
        (_CUSTOM.title(), _CUSTOM)
    ]


class GraphicsSettingsMenuState(ScrollingSettingsMenuState):
    """
    Full-screen overlay for viewing and editing graphics options.

    Save writes the working config to graphics.yaml and applies the window
    mode live; Cancel discards; Default reloads factory settings (unsaved).
    """

    def __init__(self, app: SpaceFlightSimulator):
        super().__init__(
            app,
            row_height=_ROW_HEIGHT,
            frame_top=_FRAME_TOP,
            frame_bottom=_FRAME_BOTTOM,
        )
        # Display-mode button group: list of (value, CustomButton).
        self.mode_buttons: list = []
        # WorldBuilder's settings menu description (see WorldSettings.schema)
        self.world_schema = WorldSettings.schema()
        # World preset and choice drop-downs, by widget path (see
        # make_world_rows)
        self.drop_downs: dict[tuple, CustomDropDown] = {}

    def settings(self):
        return self.app.graphics_settings

    def exit(self):
        """Close and destroy the drop-downs (an open list hangs off aspect2d),
        then the rest of the UI."""
        for drop_down in self.drop_downs.values():
            drop_down.destroy()
        self.drop_downs.clear()
        super().exit()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def build_static_ui(self):
        """Build the background, title, warning, and the Save / Cancel /
        Default action buttons. Called once per :meth:`enter`; only the
        scrollable content is rebuilt afterwards."""
        self.bg, self.title = make_settings_chrome(self.app, "Graphics Settings")
        self.warning = make_warning(
            "Render & quality changes apply on the next level load.", _WARNING_Y
        )
        self.default_btn, self.cancel_btn, self.save_btn = make_action_buttons(
            self.app,
            [
                ("Default", self.load_default),
                ("Cancel", self.cancel),
                ("Save", self.save),
            ],
        )
        self.static_widgets = [
            self.title,
            self.bg,
            self.warning,
            self.default_btn,
            self.cancel_btn,
            self.save_btn,
        ]

    def rebuild_scroll(self):
        """
        Destroy the current scrollable frame and rebuild it from the working
        configuration.

        Called on :meth:`enter` and again by :meth:`load_default`. Also resets
        the :attr:`mode_buttons`, :attr:`sliders`, :attr:`slider_value_labels`,
        :attr:`checkboxes` and :attr:`navigable_rows` caches so stale widget
        references are never kept, and hands the new rows to the menu
        navigator.
        """
        for drop_down in self.drop_downs.values():
            drop_down.destroy()
        self.drop_downs.clear()
        self.mode_buttons.clear()
        self.sliders.clear()
        self.slider_value_labels.clear()
        self.checkboxes.clear()
        self.navigable_rows.clear()

        rows = self.make_row_data()
        self.scroll_list.rebuild(len(rows))

        for i, row in enumerate(rows):
            y = self.scroll_list.row_y(i)
            kind = row["kind"]
            if kind == "header":
                self.scroll_list.add_header(row["text"], y)
                continue
            if kind == "mode":
                self.add_mode_row(y)
                widgets = [btn for _, btn in self.mode_buttons]
            elif kind == "slider":
                self.add_slider_row(row["path"], y)
                widgets = [self.sliders[row["path"]]]
            elif kind == "discrete":
                self.add_discrete_row(row["path"], y)
                widgets = [self.sliders[row["path"]]]
            elif kind == "world_level":
                widgets = [self.add_world_level_row(row["path"], row["label"], y)]
            elif kind == "world_knob":
                widgets = [self.add_world_knob_row(row["path"], row["knob"], y)]
            else:
                self.add_checkbox_row(row["path"], row["label"], y)
                widgets = [self.checkboxes[row["path"]]]
            self.navigable_rows.append((i, widgets))

        self._refresh_navigator()

    def navigation_rows(self) -> tuple[list[list], list[int | None]]:
        """
        :return: The menu navigator's rows (the scroll rows, then Default /
            Cancel / Save) and their scroll-list row indices.
        """
        rows = [widgets for _, widgets in self.navigable_rows]
        rows.append([self.default_btn, self.cancel_btn, self.save_btn])
        scroll_rows = [i for i, _ in self.navigable_rows] + [None]
        return rows, scroll_rows

    def add_mode_row(self, y: float):
        """Add the Display Mode button group to the scroll canvas."""
        self.scroll_list.add_row_label("Display Mode", y)
        for j, (text, value) in enumerate(_MODE_OPTIONS):
            btn = CustomButton(
                app=self.app,
                pos=(_MODE_BUTTON_X + j * 0.46, 0, y),
                command=self.select_mode,
                text=text,
                scale=0.19,
                layout="center",
                extraArgs=[value],
                parent=self.scroll_list.content,
            )
            self.mode_buttons.append((value, btn))
        self.refresh_mode_buttons()

    def _add_value_label(self, path: tuple, text: str, y: float):
        """Create and register the value readout to the right of a slider."""
        self.slider_value_labels[path] = self.scroll_list.add_value_label(
            text, _VALUE_LABEL_X, y
        )

    def add_slider_row(self, path: tuple, y: float):
        """Add a continuous quality slider row (label, slider, % value)."""
        label, value_range = _SCALE_SLIDERS[path]
        self.scroll_list.add_row_label(label, y)
        value = get_by_path(self.working_config, path)
        self.sliders[path] = CustomSlider(
            app=self.app,
            pos=(_SLIDER_X, 0, y),
            value=value,
            value_range=value_range,
            command=self.on_scale_slider,
            extraArgs=[path],
            scale=_SLIDER_SCALE,
            parent=self.scroll_list.content,
        )
        self._add_value_label(path, _pct(value), y)

    def add_discrete_row(self, path: tuple, y: float):
        """Add a slider row over the discrete stops in :data:`_DISCRETE_SLIDERS`."""
        label, values, labels = _DISCRETE_SLIDERS[path]
        self.scroll_list.add_row_label(label, y)
        # sanitise() guarantees a known value, so this cannot raise.
        idx = values.index(get_by_path(self.working_config, path))
        self.sliders[path] = CustomSlider(
            app=self.app,
            pos=(_SLIDER_X, 0, y),
            value=idx,
            value_range=(0, len(values) - 1),
            command=self.on_discrete_slider,
            extraArgs=[path],
            scale=_SLIDER_SCALE,
            parent=self.scroll_list.content,
            step=1,
        )
        self._add_value_label(path, labels[idx], y)

    def add_checkbox_row(self, path: tuple, label: str, y: float):
        """Add a boolean setting label and checkbox to the scroll canvas."""
        self.checkboxes[path] = self.scroll_list.add_checkbox_row(
            label,
            y,
            get_by_path(self.working_config, path),
            self.on_checkbox_toggle,
            extraArgs=[path],
        )

    def add_world_level_row(self, path: tuple, label: str, y: float):
        """
        Add a world preset drop-down row: the whole world's for the path
        ("world",), one section's for ("world", section).

        :return: The drop-down
        """
        self.scroll_list.add_row_label(label, y)
        self.drop_downs[path] = CustomDropDown(
            app=self.app,
            pos=(_SLIDER_X, 0, y),
            options=_level_options(self.world_schema),
            value=self.world_level(path),
            command=lambda level: self.select_world_level(path, level),
            parent=self.scroll_list.content,
            scale=_DROP_DOWN_SCALE,
        )
        return self.drop_downs[path]

    def add_world_knob_row(self, path: tuple, knob: dict, y: float):
        """
        Add a row for one WorldBuilder knob, by its schema kind: a checkbox
        (bool), a drop-down (choice) or a slider with a readout (int, float).

        :param path: ("world", section, knob id)
        :param knob: The knob's schema entry
        :return: The row's widget
        """
        value = self.world_value(path)
        if knob["kind"] == "bool":
            self.checkboxes[path] = self.scroll_list.add_checkbox_row(
                knob["label"], y, value, self.on_checkbox_toggle, extraArgs=[path]
            )
            return self.checkboxes[path]
        self.scroll_list.add_row_label(knob["label"], y)
        if knob["kind"] == "choice":
            self.drop_downs[path] = CustomDropDown(
                app=self.app,
                pos=(_SLIDER_X, 0, y),
                options=[(choice, choice) for choice in knob["choices"]],
                value=value,
                command=lambda choice: self.set_world_value(path, choice),
                parent=self.scroll_list.content,
                scale=_DROP_DOWN_SCALE,
            )
            return self.drop_downs[path]
        low, high = knob["range"]
        self.sliders[path] = CustomSlider(
            app=self.app,
            pos=(_SLIDER_X, 0, y),
            value=value,
            value_range=(low, high),
            command=self.on_world_slider,
            extraArgs=[path, knob],
            scale=_SLIDER_SCALE,
            parent=self.scroll_list.content,
            step=max(1, round((high - low) / 20)) if knob["kind"] == "int" else None,
        )
        self._add_value_label(path, _knob_text(knob, value), y)
        return self.sliders[path]

    def refresh_mode_buttons(self):
        """Press the button matching the current display mode, reset the rest."""
        current = self.working_config["display"]["mode"]
        for value, btn in self.mode_buttons:
            if value == current:
                btn.set_pressed()
            else:
                btn.reset()

    # ------------------------------------------------------------------
    # Row data
    # ------------------------------------------------------------------

    def make_row_data(self) -> list[dict]:
        """
        Build the ordered list of row descriptors for the scrollable area.

        Returns a flat list of dicts, each with a "kind" key that is one of:

        - "header" — section separator with a "text" key.
        - "mode" — the display-mode button group (no extra keys).
        - "slider" — continuous quality slider with a "path" key (see
          :data:`_SCALE_SLIDERS`).
        - "discrete" — slider over fixed stops with a "path" key (see
          :data:`_DISCRETE_SLIDERS`).
        - "checkbox" — boolean toggle with "path" and "label" keys.

        One header precedes each top-level section of
        datafiles/default_configuration/default_graphics.yaml, in file order.

        :return: Ordered list of row descriptor dicts.
        """
        rows = []

        for section in _SECTIONS:
            rows.append({"kind": "header", "text": _section_label(section)})
            if section == "display":
                rows.append({"kind": "mode"})
            for path in _SCALE_SLIDERS:
                if path[0] == section:
                    rows.append({"kind": "slider", "path": path})
            for path in _DISCRETE_SLIDERS:
                if path[0] == section:
                    rows.append({"kind": "discrete", "path": path})
            for path, label in _CHECKBOXES.items():
                if path[0] == section:
                    rows.append({"kind": "checkbox", "path": path, "label": label})

        return rows + self.make_world_rows()

    def make_world_rows(self) -> list[dict]:
        """
        Build the WorldBuilder rows from its schema: a "World" header and the
        whole world's preset, then per section a header, its preset, and one
        row per knob (advanced ones included), in the schema's order.

        Adds two row kinds to :meth:`make_row_data`'s:

        - "world_level" — a preset drop-down, with "path" (("world",) or
          ("world", section)) and "label" keys.
        - "world_knob" — one knob, with "path" (("world", section, knob id))
          and "knob" (its schema entry) keys.

        :return: Ordered list of row descriptor dicts.
        """
        rows = [
            {"kind": "header", "text": _section_label(_WORLD)},
            {"kind": "world_level", "path": (_WORLD,), "label": "Preset"},
        ]
        for section in self.world_schema["sections"]:
            rows.append({"kind": "header", "text": section["label"]})
            rows.append(
                {
                    "kind": "world_level",
                    "path": (_WORLD, section["id"]),
                    "label": "Preset",
                }
            )
            for knob in section["knobs"]:
                rows.append(
                    {
                        "kind": "world_knob",
                        "path": (_WORLD, section["id"], knob["id"]),
                        "knob": knob,
                    }
                )
        return rows

    # ------------------------------------------------------------------
    # World settings
    # ------------------------------------------------------------------

    def world(self) -> WorldSettings:
        """:return: The working config's world settings"""
        return WorldSettings.from_dict(self.working_config[_WORLD])

    def world_level(self, path: tuple) -> str:
        """
        :param path: ("world",) or ("world", section)
        :return: The preset the whole world, or a section, is at, or "custom"
        """
        world = self.world()
        if len(path) == 1:
            return _CUSTOM if world.is_custom() else world.level.value
        level = world.section_level(path[1])
        return _CUSTOM if level is None else level.value

    def world_value(self, path: tuple):
        """
        :param path: ("world", section, knob id)
        :return: The knob's value as saved: a choice by its label
        """
        _, section, name = path
        settings = getattr(self.world(), section)
        value = getattr(settings, name)
        knob = dict(settings.knobs())[name]
        label = knob.label_of(value)
        return value if label is None else label

    def set_world_value(self, path: tuple, value):
        """
        Store one knob's value (WorldSettings clamps it), and show which
        presets still match.

        :param path: ("world", section, knob id)
        """
        _, section, name = path
        world = self.world().with_value(section, name, value)
        self.working_config[_WORLD] = world.to_dict()
        self.refresh_world_levels()

    def refresh_world_levels(self):
        """Show the presets the values are at, or Custom, in the drop-downs."""
        for path, drop_down in self.drop_downs.items():
            if len(path) < 3:
                drop_down.set_value(self.world_level(path))

    def select_world_level(self, path: tuple, level: str):
        """
        Load a preset into the whole world, or one section, and rebuild the
        rows to show its values. Picking Custom keeps the current values.

        :param path: ("world",) or ("world", section)
        :param level: A level's id, or "custom"
        """
        if level == _CUSTOM:
            self.refresh_world_levels()
            return
        world = self.world()
        if len(path) == 1:
            world = world.with_level(level)
        else:
            world = world.with_section_level(path[1], level)
        self.working_config[_WORLD] = world.to_dict()
        scroll = self.scroll_list.v_scrollbar["value"]
        self.rebuild_scroll()
        self.scroll_list.v_scrollbar["value"] = scroll

    def on_world_slider(self, path: tuple, knob: dict):
        """
        Store a numeric knob's slider value, rounded to what it keeps (see
        :func:`_knob_value`), and refresh its readout.

        A slider also reports its value when built: within the rounding of
        the stored value, that stores nothing, so it cannot turn a preset into
        Custom. The thumb is *not* written back (see
        :meth:`on_discrete_slider`).
        """
        raw = self.sliders[path].get_value()
        if abs(raw - self.world_value(path)) < 0.5 * 10.0 ** -_knob_decimals(knob):
            return
        self.set_world_value(path, _knob_value(knob, raw))
        self.slider_value_labels[path]["text"] = _knob_text(
            knob, self.world_value(path)
        )

    # ------------------------------------------------------------------
    # Control callbacks
    # ------------------------------------------------------------------

    def select_mode(self, value: str):
        """Store the chosen display mode and refresh the button group."""
        self.working_config["display"]["mode"] = value
        self.refresh_mode_buttons()

    def on_scale_slider(self, path: tuple):
        """Store a continuous slider's value and refresh its % label."""
        value = self.sliders[path].get_value()
        set_by_path(self.working_config, path, value)
        self.slider_value_labels[path]["text"] = _pct(value)

    def on_discrete_slider(self, path: tuple):
        """Map a discrete slider to the nearest stop and store that stop's value.

        The thumb is *not* written back here: PGSliderBar throws its ADJUST
        event asynchronously, so re-setting the value from inside this handler
        would re-enqueue ADJUST every dispatch and never drain the event queue
        (a hard freeze). The stored value/label are simply rounded to the
        nearest stop; the thumb stays where the user left it.
        """
        _label, values, labels = _DISCRETE_SLIDERS[path]
        idx = int(round(self.sliders[path].get_value()))
        idx = max(0, min(len(values) - 1, idx))
        set_by_path(self.working_config, path, values[idx])
        self.slider_value_labels[path]["text"] = labels[idx]

    def on_checkbox_toggle(self, status: int, path: tuple):
        """Store a toggled checkbox value straight into :attr:`working_config`,
        or into the world settings for a WorldBuilder knob."""
        if path[0] == _WORLD:
            if bool(status) != self.world_value(path):
                self.set_world_value(path, bool(status))
            return
        set_by_path(self.working_config, path, bool(status))

    # ------------------------------------------------------------------
    # Button callbacks
    # ------------------------------------------------------------------

    def save(self):
        """Write the config, apply window mode live, and return to the caller."""
        self.app.graphics_settings.save(self.working_config)
        self.app.graphics_manager.apply_window_settings()
        self.app.state_manager.pop()

    def load_default(self):
        """Reload the factory defaults into the working config and rebuild rows."""
        self.working_config = GraphicsSettings.sanitise(
            load_yaml(DEFAULT_GRAPHICS_FILE)
        )
        self.rebuild_scroll()
