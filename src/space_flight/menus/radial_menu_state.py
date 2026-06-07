"""
Radial menu overlay state.

Pushed on top of :class:`~space_flight.game.flight_state.FlightState` when the
player holds the radial-menu trigger.  Game time keeps running (``PAUSES_BELOW
= False``), so the simulation continues while the menu is visible.

The menu is parameterised at push time via ``state_manager.push()`` kwargs::

    app.state_manager.push(
        state_class=app.state_manager.RADIAL_MENU_STATE,
        on_select=lambda idx: ...,
        slice_labels=["Laser", "Missile", "Bomb", "Shield"],
    )
"""

from __future__ import annotations

import math
from typing import Callable

from direct.gui.DirectGui import DirectFrame, DirectLabel

from space_flight.global_architecture.base_state import BaseState
from space_flight.ui.input_context import RadialMenuInputContext

# Visual constants
_RADIUS = 0.4
_UNSELECTED_SCALE = 0.1
_SELECTED_SCALE = 0.11
_UNSELECTED_FG = (0.7, 0.7, 0.7, 0.85)
_SELECTED_FG = (1.0, 0.82, 0.0, 1.0)
_BG_COLOR = (0.0, 0.0, 0.0, 0.45)


# ---------------------------------------------------------------------------
# Visual overlay
# ---------------------------------------------------------------------------


class RadialMenuVisual:
    """
    Panda3D 2-D overlay that draws the radial menu slice labels.

    Slice 0 is rendered at the top; subsequent slices are placed clockwise.
    Call :meth:`update` every frame to highlight the currently pointed-at
    slice.
    """

    def __init__(self, app, slice_labels: list[str]) -> None:
        """
        :param app: The simulator app (needed for ``aspect2d``).
        :param slice_labels: Display text for each slice
        """
        self._frame = DirectFrame(
            frameSize=(-0.7, 0.7, -0.7, 0.7),
            frameColor=_BG_COLOR,
            pos=(0, 0, 0),
        )
        self._frame.setTransparency(True)
        n_slices = len(slice_labels)

        self._labels: list[DirectLabel] = []
        for i, text in enumerate(slice_labels):
            angle = math.pi / 2 - i * 2 * math.pi / n_slices
            x = _RADIUS * math.cos(angle)
            z = _RADIUS * math.sin(angle)
            lbl = DirectLabel(
                text=text,
                text_scale=_UNSELECTED_SCALE,
                text_fg=_UNSELECTED_FG,
                frameColor=(0, 0, 0, 0),
                pos=(x, 0, z),
                parent=self._frame,
            )
            self._labels.append(lbl)

    def update(self, selected: int | None) -> None:
        """
        Highlight *selected* and dim all other slices.

        :param selected: Index of the slice the player is pointing at, or
            ``None`` when the direction vector is within the dead zone.
        """
        for i, lbl in enumerate(self._labels):
            active = i == selected
            lbl["text_scale"] = _SELECTED_SCALE if active else _UNSELECTED_SCALE
            lbl["text_fg"] = _SELECTED_FG if active else _UNSELECTED_FG

    def destroy(self) -> None:
        """Remove all Panda3D nodes."""
        for lbl in self._labels:
            lbl.destroy()
        self._labels = []
        self._frame.destroy()
        self._frame = None


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class RadialMenuState(BaseState):
    """
    Overlay state for the radial menu.

    ``PAUSES_BELOW = False`` means :class:`StateManager` will **not** call
    ``pause()`` on the game state below, so physics and game logic keep
    running while the menu is open.

    This state owns the visual overlay.  The input is handled by
    :class:`~space_flight.ui.input_context.RadialMenuInputContext`, which is
    pushed onto the :class:`~space_flight.ui.input_context.InputContextStack`
    during :meth:`enter` and popped in :meth:`exit`.
    """

    PAUSES_BELOW: bool = False

    def __init__(
        self,
        app,
        on_select: Callable,
        slice_labels: list[str] | None = None,
        min_magnitude: float = 0.3,
    ) -> None:
        """
        :param app: The simulator app.
        :param on_select: Called with the selected slice index (``int``) or
            ``None`` when the trigger is released without a valid direction.
        :param slice_labels: Optional display labels; defaults to ``["0",
            "1", ...]``.
        :param min_magnitude: Direction vector magnitude below which no slice
            is considered selected.
        """
        super().__init__(app)
        self.n_slices = len(slice_labels)
        self._on_select = on_select
        self.slice_labels = (
            slice_labels
            if slice_labels is not None
            else [str(i) for i in range(self.n_slices)]
        )
        self._min_magnitude = min_magnitude
        self._visual: RadialMenuVisual | None = None

    def enter(self) -> None:
        # Resolve the trigger hardware name from the flight context bindings
        # so we don't duplicate it in the YAML.
        input_type = self.app.bindings["input_type"]
        trigger_hw_name: str = (
            self.app.bindings["contexts"]["flight"]
            .get(input_type, {})
            .get("radial_menu", "")
        )

        game_state = self.app.state_manager.stack[-2]
        self._visual = RadialMenuVisual(self.app, self.slice_labels)
        ctx = RadialMenuInputContext(
            game=game_state,
            n_slices=self.n_slices,
            on_select=self._on_select,
            trigger_hw_name=trigger_hw_name,
            on_hover=self._visual.update,
            min_magnitude=self._min_magnitude,
        )
        self.app.input_context_stack.push(ctx)

    def pause(self) -> None:
        pass

    def resume(self) -> None:
        pass

    def exit(self) -> None:
        self.app.input_context_stack.pop()
        if self._visual is not None:
            self._visual.destroy()
            self._visual = None
