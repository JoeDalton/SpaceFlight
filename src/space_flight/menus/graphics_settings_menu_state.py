"""
Graphics settings menu — lets the player view and change display/render options.

Mirrors :mod:`space_flight.menus.input_settings_menu_state`: a deep-copied
working config is edited in memory while the menu is open and written back on
*Save*. Display mode is a button group; the quality knobs are sliders; FXAA is
a checkbox.

On save the display mode is applied to the live window immediately; render
scale, anti-aliasing and the reflection/mirror quality are picked up on the
next level load (hence the warning shown above the Save button). See
:class:`~space_flight.global_architecture.graphics_manager.GraphicsManager`.
"""

import copy

from direct.gui.DirectGui import DirectFrame, DirectLabel
from panda3d.core import TextNode

from space_flight.global_architecture.base_state import BaseState
from space_flight.global_architecture.graphics_settings import (
    _VALID_CLOUD_QUALITY,
    _VALID_MSAA,
    DEFAULT_GRAPHICS_FILE,
    GraphicsSettings,
)
from space_flight.menus.menu_utils import CustomButton, CustomCheckButton, CustomSlider

# Display mode is a small fixed button group.
_MODE_OPTIONS = [("Fullscreen", "fullscreen"), ("Windowed", "windowed")]

# Continuous quality sliders: path -> (label, (min, max)).
_SCALE_SLIDERS = {
    ("render", "scale"): ("Render Scale", (0.5, 2.0)),
    ("render", "reflection_scale"): ("Reflection Quality", (0.25, 1.0)),
    ("render", "mirror_scale"): ("Mirror Quality", (0.25, 1.0)),
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

# Option rows, top to bottom: (builder method name, *builder args before y).
_ROWS = (
    ("build_mode_row",),
    ("build_slider_row", ("render", "scale")),
    ("build_discrete_row", ("antialiasing", "msaa")),
    ("build_fxaa_row",),
    ("build_slider_row", ("render", "reflection_scale")),
    ("build_slider_row", ("render", "mirror_scale")),
    ("build_discrete_row", ("clouds", "quality")),
    ("build_alternate_model_orientation_row",),
)

# Layout
_LABEL_X = -1.15
_SLIDER_X = 0.35
_SLIDER_SCALE = 0.4
_VALUE_LABEL_X = 0.95
_CONTROL_X = -0.05  # left edge of button groups / checkbox

# Rows run top-down from _ROW_TOP, one every _ROW_STEP; a test asserts the lowest
# still clears _WARNING_Y, so adding a row fails loudly instead of overlapping it.
_ROW_TOP = 0.6
_ROW_STEP = 0.175
_ROW_COUNT = len(_ROWS)
_WARNING_Y = -0.7
#: Clearance a row label needs below it before the warning text starts.
_ROW_CLEARANCE = 0.06


def _get_by_path(cfg: dict, path: tuple):
    """Return the value at *path* (a tuple of keys) within nested dict *cfg*."""
    d = cfg
    for key in path:
        d = d[key]
    return d


def _set_by_path(cfg: dict, path: tuple, value):
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

    def __init__(self, app):
        super().__init__(app)
        self.working_config: dict = {}
        # Display-mode button group: list of (value, CustomButton).
        self.mode_buttons: list = []
        # Quality sliders keyed by config path, plus their value labels.
        self.sliders: dict[tuple, CustomSlider] = {}
        self.slider_value_labels: dict[tuple, DirectLabel] = {}
        self.fxaa_checkbox: CustomCheckButton | None = None
        self.alternate_model_orientation_checkbox: CustomCheckButton | None = None
        self.static_widgets: list = []

    # ------------------------------------------------------------------
    # State lifecycle
    # ------------------------------------------------------------------

    def enter(self):
        """Take a working copy of the current settings and build the UI."""
        self.working_config = copy.deepcopy(self.app.graphics_settings.config)
        self.build_ui()

    def exit(self):
        """Destroy every UI element and force a frame render."""
        self.title.destroy()
        self.bg.destroy()
        self.clear_rows()
        self.warning.destroy()
        self.default_btn.destroy()
        self.cancel_btn.destroy()
        self.save_btn.destroy()
        self.force_render()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def build_ui(self):
        """Build the background, title, every option row, the warning, and the
        Save / Cancel / Default action buttons."""
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

        self.build_rows()

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

    def build_rows(self):
        """Build every option row in :data:`_ROWS` from the working config."""
        for index, (builder, *args) in enumerate(_ROWS):
            getattr(self, builder)(*args, _ROW_TOP - index * _ROW_STEP)

    def clear_rows(self):
        """Destroy all option-row widgets (labels, buttons, sliders, checkbox)."""
        for _value, btn in self.mode_buttons:
            btn.destroy()
        self.mode_buttons.clear()
        for slider in self.sliders.values():
            slider.destroy()
        self.sliders.clear()
        for lbl in self.slider_value_labels.values():
            lbl.destroy()
        self.slider_value_labels.clear()
        if self.fxaa_checkbox is not None:
            self.fxaa_checkbox.destroy()
            self.fxaa_checkbox = None
        if self.alternate_model_orientation_checkbox is not None:
            self.alternate_model_orientation_checkbox.destroy()
            self.alternate_model_orientation_checkbox = None
        for w in self.static_widgets:
            w.destroy()
        self.static_widgets.clear()

    def _row_label(self, text: str, y: float):
        """Create and register a left-aligned row label."""
        label = DirectLabel(
            text=text + ":",
            scale=0.055,
            pos=(_LABEL_X, 0, y - 0.015),
            frameColor=(0, 0, 0, 0),
            text_fg=(0.898, 0.839, 0.730, 1.0),
            text_align=TextNode.ALeft,
        )
        label.setTransparency(True)
        self.static_widgets.append(label)

    def build_mode_row(self, y: float):
        """Build the Display Mode button group."""
        self._row_label("Display Mode", y)
        for j, (text, value) in enumerate(_MODE_OPTIONS):
            btn = CustomButton(
                app=self.app,
                pos=(_CONTROL_X + j * 0.46, 0, y),
                command=self.select_mode,
                text=text,
                scale=0.19,
                layout="center",
                extraArgs=[value],
            )
            self.mode_buttons.append((value, btn))
        self.refresh_mode_buttons()

    def _value_label(self, path: tuple, text: str, y: float):
        """Create and register the value readout to the right of a slider."""
        label = DirectLabel(
            text=text,
            scale=0.05,
            pos=(_VALUE_LABEL_X, 0, y - 0.015),
            frameColor=(0, 0, 0, 0),
            text_fg=(0.7, 0.85, 1.0, 1.0),
            text_align=TextNode.ALeft,
        )
        label.setTransparency(True)
        self.slider_value_labels[path] = label

    def build_slider_row(self, path: tuple, y: float):
        """Build a continuous quality slider row (label, slider, % value)."""
        label, value_range = _SCALE_SLIDERS[path]
        self._row_label(label, y)
        value = _get_by_path(self.working_config, path)
        self.sliders[path] = CustomSlider(
            app=self.app,
            pos=(_SLIDER_X, 0, y),
            value=value,
            value_range=value_range,
            command=self.on_scale_slider,
            extraArgs=[path],
            scale=_SLIDER_SCALE,
        )
        self._value_label(path, _pct(value), y)

    def build_discrete_row(self, path: tuple, y: float):
        """Build a slider row over the discrete stops in :data:`_DISCRETE_SLIDERS`."""
        label, values, labels = _DISCRETE_SLIDERS[path]
        self._row_label(label, y)
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
        )
        self._value_label(path, labels[idx], y)

    def build_fxaa_row(self, y: float):
        """Build the FXAA checkbox row."""
        self._row_label("FXAA", y)
        self.fxaa_checkbox = CustomCheckButton(
            app=self.app,
            pos=(_CONTROL_X + 0.06, 0, y),
            value=self.working_config["antialiasing"]["fxaa"],
            command=self.on_fxaa_toggle,
            scale=0.07,
        )

    def build_alternate_model_orientation_row(self, y: float):
        """Build the "Alternate Model Orientation" checkbox row.

        Manual workaround for ship models loading pre-rotated on some
        systems (see
        space_flight.global_architecture.asset_manager.gltf_model_tilt_quaternion)
        -- no automatic detection exists, so the player has to flip this
        themselves if their ships look wrong.
        """
        self._row_label("Alternate Model Orientation", y)
        self.alternate_model_orientation_checkbox = CustomCheckButton(
            app=self.app,
            pos=(_CONTROL_X + 0.06, 0, y),
            value=self.working_config["compatibility"]["alternate_model_orientation"],
            command=self.on_alternate_model_orientation_toggle,
            scale=0.07,
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

    def on_fxaa_toggle(self, status):
        """Store the FXAA checkbox state."""
        self.working_config["antialiasing"]["fxaa"] = bool(status)

    def on_alternate_model_orientation_toggle(self, status):
        """Store the alternate-model-orientation checkbox state."""
        self.working_config["compatibility"]["alternate_model_orientation"] = bool(
            status
        )

    # ------------------------------------------------------------------
    # Action buttons
    # ------------------------------------------------------------------

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
        self.clear_rows()
        self.build_rows()
