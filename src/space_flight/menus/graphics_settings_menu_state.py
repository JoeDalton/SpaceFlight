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
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from direct.gui.DirectGui import DirectFrame, DirectLabel
from panda3d.core import TextNode

from space_flight.global_architecture.base_state import BaseState
from space_flight.global_architecture.graphics_settings import (
    _MAX_MIRROR,
    _MAX_REFLECTION,
    _MAX_SCALE,
    _MIN_MIRROR,
    _MIN_REFLECTION,
    _MIN_SCALE,
    _VALID_CLOUD_QUALITY,
    _VALID_MSAA,
    DEFAULT_GRAPHICS_FILE,
    GraphicsSettings,
)
from space_flight.menus.menu_utils import CustomButton, CustomSlider, ScrollableList

if TYPE_CHECKING:
    from space_flight.global_architecture.simulator import SpaceFlightSimulator

# Display mode is a small fixed button group.
_MODE_OPTIONS = [("Fullscreen", "fullscreen"), ("Windowed", "windowed")]

# Continuous quality sliders: path -> (label, (min, max)). The ranges are the
# ones sanitise() clamps to.
_SCALE_SLIDERS = {
    ("render", "scale"): ("Render Scale", (_MIN_SCALE, _MAX_SCALE)),
    ("render", "reflection_scale"): (
        "Reflection Quality",
        (_MIN_REFLECTION, _MAX_REFLECTION),
    ),
    ("render", "mirror_scale"): ("Mirror Quality", (_MIN_MIRROR, _MAX_MIRROR)),
}

# Sliders over discrete stops: path -> (label, values, value labels). Cheapest
# first, so dragging right costs more, like every other slider here.
_DISCRETE_SLIDERS = {
    ("antialiasing", "msaa"): ("MSAA", _VALID_MSAA, ("Off", "2x", "4x", "8x")),
    ("clouds", "quality"): (
        "Cloud Quality",
        _VALID_CLOUD_QUALITY,
        tuple(name.title() for name in _VALID_CLOUD_QUALITY),
    ),
}

# Checkbox toggles: path -> label.
_CHECKBOXES = {
    ("antialiasing", "fxaa"): "FXAA",
    ("compatibility", "alternate_model_orientation"): "Alternate Model Orientation",
    ("hud", "fps_counter"): "FPS Counter",
}

# Section headers are named after the top-level keys of default_graphics.yaml,
# in the order they appear there; override only where title-casing the key
# reads oddly.
_SECTIONS = ("display", "render", "antialiasing", "compatibility", "clouds", "hud")
_SECTION_LABELS = {"hud": "HUD"}

# Layout
_SLIDER_X = 0.0
_SLIDER_SCALE = 0.35
_VALUE_LABEL_X = 0.65
_MODE_BUTTON_X = -0.1

_ROW_HEIGHT = 0.15
_FRAME_TOP = 0.78
_FRAME_BOTTOM = -0.72
_WARNING_Y = -0.8


def _section_label(name: str) -> str:
    """Return the display header for a top-level graphics.yaml section."""
    return _SECTION_LABELS.get(name, name.replace("_", " ").title())


def _get_by_path(cfg: dict, path: tuple) -> Any:
    """Return the value at *path* (a tuple of keys) within nested dict *cfg*."""
    d = cfg
    for key in path:
        d = d[key]
    return d


def _set_by_path(cfg: dict, path: tuple, value: Any):
    """Set the value at *path* (a tuple of keys) within nested dict *cfg*."""
    d = cfg
    for key in path[:-1]:
        d = d[key]
    d[path[-1]] = value


def _pct(value: float) -> str:
    """Format a fraction as a rounded percentage string."""
    return f"{round(value * 100)}%"


class GraphicsSettingsMenuState(BaseState):
    """
    Full-screen overlay for viewing and editing graphics options.

    Save writes the working config to graphics.yaml and applies the window
    mode live; Cancel discards; Default reloads factory settings (unsaved).
    """

    def __init__(self, app: SpaceFlightSimulator):
        super().__init__(app)
        self.working_config: dict = {}
        # Display-mode button group: list of (value, CustomButton).
        self.mode_buttons: list = []
        # Quality sliders keyed by config path, plus their value labels.
        self.sliders: dict[tuple, CustomSlider] = {}
        self.slider_value_labels: dict[tuple, DirectLabel] = {}
        self.checkboxes: dict[tuple, object] = {}
        self.scroll_list = ScrollableList(
            app,
            row_height=_ROW_HEIGHT,
            frame_top=_FRAME_TOP,
            frame_bottom=_FRAME_BOTTOM,
        )

    # ------------------------------------------------------------------
    # State lifecycle
    # ------------------------------------------------------------------

    def enter(self):
        """Take a working copy of the current settings and build the UI."""
        self.working_config = copy.deepcopy(self.app.graphics_settings.config)
        self.build_static_ui()
        self.rebuild_scroll()
        self.app.accept("wheel_up", lambda: self.wheel_scroll(-0.5))
        self.app.accept("wheel_down", lambda: self.wheel_scroll(0.5))

    def exit(self):
        """Destroy every UI element and force a frame render."""
        self.app.ignore("wheel_up")
        self.app.ignore("wheel_down")
        self.scroll_list.destroy()
        self.title.destroy()
        self.bg.destroy()
        self.warning.destroy()
        self.default_btn.destroy()
        self.cancel_btn.destroy()
        self.save_btn.destroy()
        self.force_render()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def build_static_ui(self):
        """Build the background, title, warning, and the Save / Cancel /
        Default action buttons. Called once per :meth:`enter`; only the
        scrollable content is rebuilt afterwards."""
        self.bg = DirectFrame(
            frameSize=(self.app.a2dLeft, self.app.a2dRight, -1.0, 1.0),
            frameColor=(0.04, 0.04, 0.1, 0.97),
        )
        self.bg.setTransparency(True)

        self.title = DirectLabel(
            text="Graphics Settings",
            scale=0.1,
            pos=(0, 0, 0.88),
            frameColor=(0, 0, 0, 0),
            text_fg=(1, 1, 1, 1),
            text_shadow=(0, 0, 0, 0.75),
            text_shadowOffset=(0.05, 0.05),
            text_align=TextNode.ACenter,
        )
        self.title.setTransparency(True)

        self.warning = DirectLabel(
            text="Render & quality changes apply on the next level load.",
            scale=0.045,
            pos=(0, 0, _WARNING_Y),
            frameColor=(0, 0, 0, 0),
            text_fg=(1.0, 0.85, 0.4, 1.0),
            text_align=TextNode.ACenter,
        )
        self.warning.setTransparency(True)

        self.default_btn = CustomButton(
            app=self.app,
            pos=(-0.7, 0, -0.91),
            command=self.load_default,
            text="Default",
            scale=0.28,
            layout="center",
        )
        self.cancel_btn = CustomButton(
            app=self.app,
            pos=(0.0, 0, -0.91),
            command=self.cancel,
            text="Cancel",
            scale=0.28,
            layout="center",
        )
        self.save_btn = CustomButton(
            app=self.app,
            pos=(0.7, 0, -0.91),
            command=self.save,
            text="Save",
            scale=0.28,
            layout="center",
        )

    def rebuild_scroll(self):
        """
        Destroy the current scrollable frame and rebuild it from the working
        configuration.

        Called on :meth:`enter` and again by :meth:`load_default`. Also resets
        the :attr:`mode_buttons`, :attr:`sliders`, :attr:`slider_value_labels`
        and :attr:`checkboxes` caches so stale widget references are never
        kept.
        """
        self.mode_buttons.clear()
        self.sliders.clear()
        self.slider_value_labels.clear()
        self.checkboxes.clear()

        rows = self.make_row_data()
        self.scroll_list.rebuild(len(rows))

        for i, row in enumerate(rows):
            y = self.scroll_list.row_y(i)
            kind = row["kind"]
            if kind == "header":
                self.scroll_list.add_header(row["text"], y)
            elif kind == "mode":
                self.add_mode_row(y)
            elif kind == "slider":
                self.add_slider_row(row["path"], y)
            elif kind == "discrete":
                self.add_discrete_row(row["path"], y)
            else:
                self.add_checkbox_row(row["path"], row["label"], y)

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
        label = DirectLabel(
            parent=self.scroll_list.content,
            text=text,
            scale=0.05,
            pos=(_VALUE_LABEL_X, 0, y - 0.015),
            frameColor=(0, 0, 0, 0),
            text_fg=(0.7, 0.85, 1.0, 1.0),
            text_align=TextNode.ALeft,
        )
        label.setTransparency(True)
        self.slider_value_labels[path] = label

    def add_slider_row(self, path: tuple, y: float):
        """Add a continuous quality slider row (label, slider, % value)."""
        label, value_range = _SCALE_SLIDERS[path]
        self.scroll_list.add_row_label(label, y)
        value = _get_by_path(self.working_config, path)
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
        idx = values.index(_get_by_path(self.working_config, path))
        self.sliders[path] = CustomSlider(
            app=self.app,
            pos=(_SLIDER_X, 0, y),
            value=idx,
            value_range=(0, len(values) - 1),
            command=self.on_discrete_slider,
            extraArgs=[path],
            scale=_SLIDER_SCALE,
            parent=self.scroll_list.content,
        )
        self._add_value_label(path, labels[idx], y)

    def add_checkbox_row(self, path: tuple, label: str, y: float):
        """Add a boolean setting label and checkbox to the scroll canvas."""
        self.scroll_list.add_row_label(label, y)
        self.checkboxes[path] = self.scroll_list.add_checkbox(
            y,
            _get_by_path(self.working_config, path),
            self.on_checkbox_toggle,
            extraArgs=[path],
        )

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

        return rows

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
        _set_by_path(self.working_config, path, value)
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
        _set_by_path(self.working_config, path, values[idx])
        self.slider_value_labels[path]["text"] = labels[idx]

    def on_checkbox_toggle(self, status: int, path: tuple):
        """Store a toggled checkbox value straight into :attr:`working_config`."""
        _set_by_path(self.working_config, path, bool(status))

    # ------------------------------------------------------------------
    # Button callbacks
    # ------------------------------------------------------------------

    def wheel_scroll(self, direction: float):
        """Scroll the option list by *direction* scroll steps (negative = up)."""
        self.scroll_list.wheel_scroll(direction)

    def save(self):
        """Write the config, apply window mode live, and return to the caller."""
        self.app.graphics_settings.save(self.working_config)
        self.app.graphics_manager.apply_window_settings()
        self.app.state_manager.pop()

    def cancel(self):
        """Discard all unsaved changes and return to the caller."""
        self.app.state_manager.pop()

    def load_default(self):
        """Reload the factory defaults into the working config and rebuild rows."""
        self.working_config = GraphicsSettings.sanitise(
            GraphicsSettings.load_file(DEFAULT_GRAPHICS_FILE)
        )
        self.rebuild_scroll()
