"""
Gameplay settings menu — lets the player pick a difficulty preset, or tune the
gameplay settings one by one (the "custom" preset).

Like :mod:`space_flight.menus.graphics_settings_menu_state`, a deep-copied
working config is edited in memory and written back only on *Save*. The preset
drop-down sits above the scrollable rows, which are grouped under one header
per side (player, bots).

Picking a preset loads its values into the rows; editing any row switches the
drop-down to "Custom". Every setting is read on the next level load (hence the
warning shown above the Save button). See
:mod:`space_flight.global_architecture.gameplay_settings`.
"""

from __future__ import annotations

import copy
import math
from typing import TYPE_CHECKING

from direct.gui.DirectGui import DirectFrame, DirectLabel
from panda3d.core import TextNode

from space_flight.global_architecture.base_state import BaseState
from space_flight.global_architecture.gameplay_settings import (
    _AUTO_AIM_LIMITS,
    _COLLISION_DAMAGE_MULTIPLIER_LIMITS,
    _DAMAGE_MULTIPLIER_LIMITS,
    _DEVIATION_LIMITS,
    CUSTOM_PRESET,
    SIDES,
)
from space_flight.menus.graphics_settings_menu_state import (
    _get_by_path,
    _set_by_path,
)
from space_flight.menus.menu_utils import (
    CustomButton,
    CustomDropDown,
    CustomSlider,
    ScrollableList,
)

if TYPE_CHECKING:
    from space_flight.global_architecture.simulator import SpaceFlightSimulator

# Sliders: path within a side's settings -> (label, (min, max), step, value
# format). The ranges are the ones sanitise() clamps to.
_SLIDERS = {
    ("auto_aim", "lock_delay_s"): (
        "Lock Delay",
        _AUTO_AIM_LIMITS["lock_delay_s"][:2],
        0.05,
        "{:.2f} s",
    ),
    ("auto_aim", "lock_angle_deg"): (
        "Lock Angle",
        _AUTO_AIM_LIMITS["lock_angle_deg"][:2],
        1.0,
        "{:.0f} deg",
    ),
    ("auto_aim", "assist_angle_deg"): (
        "Assist Angle",
        _AUTO_AIM_LIMITS["assist_angle_deg"][:2],
        0.5,
        "{:.1f} deg",
    ),
    ("deviation_deg",): ("Shot Deviation", _DEVIATION_LIMITS[:2], 0.1, "{:.1f} deg"),
    ("damage_multiplier",): (
        "Damage Dealt",
        _DAMAGE_MULTIPLIER_LIMITS[:2],
        0.05,
        "x{:.2f}",
    ),
    ("collision_damage_multiplier",): (
        "Collision Damage Taken",
        _COLLISION_DAMAGE_MULTIPLIER_LIMITS[:2],
        0.05,
        "x{:.2f}",
    ),
}

# Checkbox toggles: path within a side's settings -> label.
_CHECKBOXES = {
    ("auto_aim", "enabled"): "Auto-Aim",
    ("lead_indicator",): "Lead Indicator",
}

# Row order within each side. A side only shows the rows it has settings for
# (e.g. the bots have no lead indicator).
_ROW_ORDER = (
    ("auto_aim", "enabled"),
    ("auto_aim", "lock_delay_s"),
    ("auto_aim", "lock_angle_deg"),
    ("auto_aim", "assist_angle_deg"),
    ("deviation_deg",),
    ("damage_multiplier",),
    ("collision_damage_multiplier",),
    ("lead_indicator",),
)

_SECTION_LABELS = {"player": "Player", "bots": "Bots"}

# Layout
_SLIDER_X = 0.0
_SLIDER_SCALE = 0.35
_VALUE_LABEL_X = 0.65
_PRESET_Y = 0.71
_PRESET_MENU_X = _SLIDER_X

_ROW_HEIGHT = 0.15
_FRAME_TOP = 0.6
_FRAME_BOTTOM = -0.72
_WARNING_Y = -0.8


def _snap(value: float, step: float) -> float:
    """Round *value* to the nearest multiple of *step* (free of float noise)."""
    return round(round(value / step) * step, 6)


class GameplaySettingsMenuState(BaseState):
    """
    Full-screen overlay for picking a difficulty preset or tuning the gameplay
    settings.

    Save writes the working config to gameplay.yaml; Cancel discards.
    """

    def __init__(self, app: SpaceFlightSimulator):
        super().__init__(app)
        self.working_config: dict = {}
        self.preset_menu: CustomDropDown | None = None
        # Sliders keyed by full config path, plus their value labels.
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
        self.working_config = copy.deepcopy(self.app.gameplay_settings.config)
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
        self.preset_label.destroy()
        self.preset_menu.destroy()
        self.warning.destroy()
        self.cancel_btn.destroy()
        self.save_btn.destroy()
        self.force_render()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def preset_options(self) -> list[tuple[str, str]]:
        """:return: The drop-down's (label, preset) options: the presets, then
        Custom."""
        return [(name.title(), name) for name in self.app.gameplay_settings.presets] + [
            (CUSTOM_PRESET.title(), CUSTOM_PRESET)
        ]

    def build_static_ui(self):
        """Build the background, title, preset drop-down, warning, and the
        Save / Cancel action buttons. Called once per :meth:`enter`; only the
        scrollable content is rebuilt afterwards."""
        self.bg = DirectFrame(
            frameSize=(self.app.a2dLeft, self.app.a2dRight, -1.0, 1.0),
            frameColor=(0.04, 0.04, 0.1, 0.97),
        )
        self.bg.setTransparency(True)

        self.title = DirectLabel(
            text="Gameplay Settings",
            scale=0.1,
            pos=(0, 0, 0.88),
            frameColor=(0, 0, 0, 0),
            text_fg=(1, 1, 1, 1),
            text_shadow=(0, 0, 0, 0.75),
            text_shadowOffset=(0.05, 0.05),
            text_align=TextNode.ACenter,
        )
        self.title.setTransparency(True)

        self.preset_label = DirectLabel(
            text="Difficulty:",
            scale=0.05,
            pos=(self.app.a2dLeft + 0.2, 0, _PRESET_Y - 0.015),
            frameColor=(0, 0, 0, 0),
            text_fg=(0.898, 0.839, 0.730, 1.0),
            text_align=TextNode.ALeft,
        )
        self.preset_label.setTransparency(True)
        self.preset_menu = CustomDropDown(
            app=self.app,
            pos=(_PRESET_MENU_X, 0, _PRESET_Y),
            options=self.preset_options(),
            value=self.working_config["preset"],
            command=self.select_preset,
        )

        self.warning = DirectLabel(
            text="Changes apply from the next mission.",
            scale=0.045,
            pos=(0, 0, _WARNING_Y),
            frameColor=(0, 0, 0, 0),
            text_fg=(1.0, 0.85, 0.4, 1.0),
            text_align=TextNode.ACenter,
        )
        self.warning.setTransparency(True)

        self.cancel_btn = CustomButton(
            app=self.app,
            pos=(-0.35, 0, -0.91),
            command=self.cancel,
            text="Cancel",
            scale=0.28,
            layout="center",
        )
        self.save_btn = CustomButton(
            app=self.app,
            pos=(0.35, 0, -0.91),
            command=self.save,
            text="Save",
            scale=0.28,
            layout="center",
        )

    def rebuild_scroll(self):
        """
        Destroy the current scrollable frame and rebuild it from the working
        configuration.

        Called on :meth:`enter` and again when a preset is picked. Also resets
        the :attr:`sliders`, :attr:`slider_value_labels` and :attr:`checkboxes`
        caches so stale widget references are never kept.
        """
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
            elif kind == "slider":
                self.add_slider_row(row["path"], y)
            else:
                self.add_checkbox_row(row["path"], y)

    def add_slider_row(self, path: tuple, y: float):
        """Add a slider row (label, slider, value readout) for a full path."""
        label, value_range, _step, value_format = _SLIDERS[path[1:]]
        self.scroll_list.add_row_label(label, y)
        value = _get_by_path(self.working_config, path)
        self.sliders[path] = CustomSlider(
            app=self.app,
            pos=(_SLIDER_X, 0, y),
            value=value,
            value_range=value_range,
            command=self.on_slider,
            extraArgs=[path],
            scale=_SLIDER_SCALE,
            parent=self.scroll_list.content,
        )
        value_label = DirectLabel(
            parent=self.scroll_list.content,
            text=value_format.format(value),
            scale=0.05,
            pos=(_VALUE_LABEL_X, 0, y - 0.015),
            frameColor=(0, 0, 0, 0),
            text_fg=(0.7, 0.85, 1.0, 1.0),
            text_align=TextNode.ALeft,
        )
        value_label.setTransparency(True)
        self.slider_value_labels[path] = value_label

    def add_checkbox_row(self, path: tuple, y: float):
        """Add a boolean setting label and checkbox for a full path."""
        self.scroll_list.add_row_label(_CHECKBOXES[path[1:]], y)
        self.checkboxes[path] = self.scroll_list.add_checkbox(
            y,
            _get_by_path(self.working_config, path),
            self.on_checkbox_toggle,
            extraArgs=[path],
        )

    # ------------------------------------------------------------------
    # Row data
    # ------------------------------------------------------------------

    def make_row_data(self) -> list[dict]:
        """
        Build the ordered list of row descriptors for the scrollable area.

        Returns a flat list of dicts, each with a "kind" key that is one of:

        - "header" — a side's section separator, with a "text" key.
        - "slider" — a numeric setting, with a "path" key: the full config path
          (side first; see :data:`_SLIDERS`).
        - "checkbox" — a boolean setting, with a "path" key (see
          :data:`_CHECKBOXES`).

        Each side lists the settings it has, in :data:`_ROW_ORDER`.

        :return: Ordered list of row descriptor dicts.
        """
        rows = []
        for side in SIDES:
            rows.append({"kind": "header", "text": _SECTION_LABELS[side]})
            for key in _ROW_ORDER:
                try:
                    _get_by_path(self.working_config[side], key)
                except KeyError:
                    continue
                kind = "slider" if key in _SLIDERS else "checkbox"
                rows.append({"kind": kind, "path": (side, *key)})
        return rows

    # ------------------------------------------------------------------
    # Control callbacks
    # ------------------------------------------------------------------

    def select_preset(self, preset: str):
        """
        Load a preset's values into the working config and the rows. Picking
        Custom keeps the current values, to be edited.
        """
        if preset == CUSTOM_PRESET:
            self.working_config["preset"] = CUSTOM_PRESET
            return
        self.working_config = {
            "preset": preset,
            **copy.deepcopy(self.app.gameplay_settings.presets[preset]),
        }
        self.rebuild_scroll()

    def mark_custom(self):
        """An edited value no longer matches a preset: switch to Custom."""
        if self.working_config["preset"] != CUSTOM_PRESET:
            self.working_config["preset"] = CUSTOM_PRESET
            self.preset_menu.set_value(CUSTOM_PRESET)

    def on_slider(self, path: tuple):
        """
        Store a slider's value, snapped to its step, refresh its readout, and
        switch to Custom if the value changed.

        A slider also reports its value when built: being unchanged, that
        does not switch to Custom. The thumb is *not* written back to the
        snapped value (see GraphicsSettingsMenuState.on_discrete_slider).
        """
        _label, _range, step, value_format = _SLIDERS[path[1:]]
        value = _snap(self.sliders[path].get_value(), step)
        if math.isclose(value, _get_by_path(self.working_config, path), abs_tol=1e-6):
            return
        _set_by_path(self.working_config, path, value)
        self.slider_value_labels[path]["text"] = value_format.format(value)
        self.mark_custom()

    def on_checkbox_toggle(self, status: int, path: tuple):
        """Store a toggled checkbox value, and switch to Custom if it changed."""
        value = bool(status)
        if value == _get_by_path(self.working_config, path):
            return
        _set_by_path(self.working_config, path, value)
        self.mark_custom()

    # ------------------------------------------------------------------
    # Button callbacks
    # ------------------------------------------------------------------

    def wheel_scroll(self, direction: float):
        """Scroll the option list by *direction* scroll steps (negative = up)."""
        self.scroll_list.wheel_scroll(direction)

    def save(self):
        """Write the config and return to the caller."""
        self.app.gameplay_settings.save(self.working_config)
        self.app.state_manager.pop()

    def cancel(self):
        """Discard all unsaved changes and return to the caller."""
        self.app.state_manager.pop()
