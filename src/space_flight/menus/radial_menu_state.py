"""
Radial menu overlay state.

Pushed on top of :class:`~space_flight.game.flight_state.FlightState` when the
player presses the radial-menu trigger, and parameterised via push() kwargs
(see :meth:`~space_flight.actors.player.Player.open_radial_target_menu`)::

    app.state_manager.push(
        state_class=app.state_manager.RADIAL_MENU_STATE,
        on_select=lambda idx: ...,
        slice_labels=TARGET_FILTERS,
    )
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Callable

from direct.gui.DirectGui import DirectLabel
from panda3d.core import Geom, GeomNode, NodePath, TransparencyAttrib

from space_flight.global_architecture.base_state import BaseState
from space_flight.ui.input_context import RadialMenuInputContext, bound_keys
from space_flight.ui.utils import make_ring_sector_geom

if TYPE_CHECKING:
    from space_flight.global_architecture.simulator import SpaceFlightSimulator

# Visual constants
_INNER_RADIUS = 0.3
_OUTER_RADIUS = 0.75
_LABEL_RADIUS = 0.5 * (_INNER_RADIUS + _OUTER_RADIUS)
_SLICE_GAP_RAD = 0.06
_ARC_STEP_RAD = 0.1
_UNSELECTED_SCALE = 0.07
_SELECTED_SLICE_SCALE = 1.08
_UNSELECTED_FG = (0.7, 0.7, 0.7, 0.85)
_SELECTED_FG = (1.0, 0.95, 0.7, 1.0)
_SLICE_COLOR = (0.0, 0.0, 0.0, 0.45)
_SELECTED_SLICE_COLOR = (0.75, 0.55, 0.0, 0.8)


# ---------------------------------------------------------------------------
# Visual overlay
# ---------------------------------------------------------------------------


class RadialMenuVisual:
    """
    Panda3D 2-D overlay that draws the radial menu as a ring of separate slices
    around an empty centre, built from procedural geometry (no assets).

    Slice 0 is centred at the top; subsequent slices are placed clockwise.
    Call :meth:`update` every frame to highlight the currently pointed-at
    slice: it lights up, grows slightly and is drawn over its neighbours.
    """

    def __init__(self, app: SpaceFlightSimulator, slice_labels: list[str]):
        """
        :param app: The simulator app, whose aspect2d parents the overlay.
        :param slice_labels: Display text for each slice
        """
        self.root = app.aspect2d.attachNewNode("radial_menu")
        n_slices = len(slice_labels)
        slice_width = 2 * math.pi / n_slices

        self.slices: list[NodePath] = []
        self.slice_geoms: list[tuple[Geom, Geom]] = []
        self.labels: list[DirectLabel] = []
        for i, text in enumerate(slice_labels):
            # Slice 0 is centred on the top (pi/2); angles grow clockwise
            centre = math.pi / 2 - i * slice_width
            half_width = 0.5 * slice_width - 0.5 * _SLICE_GAP_RAD
            # The selected slice is the normal one scaled up about the menu
            # centre, except for its inner edge which is pulled inwards.
            variants = (
                (_INNER_RADIUS, _OUTER_RADIUS, half_width),
                (
                    _INNER_RADIUS / _SELECTED_SLICE_SCALE,
                    _OUTER_RADIUS * _SELECTED_SLICE_SCALE,
                    half_width * _SELECTED_SLICE_SCALE,
                ),
            )
            geoms = tuple(
                make_ring_sector_geom(
                    inner_radius,
                    outer_radius,
                    centre + half_span,
                    centre - half_span,
                    max(1, math.ceil(2 * half_span / _ARC_STEP_RAD)),
                )
                for inner_radius, outer_radius, half_span in variants
            )
            self.slice_geoms.append(geoms)
            node = GeomNode(f"radial_slice_{i}")
            node.addGeom(geoms[0])
            slice_np = self.root.attachNewNode(node)
            slice_np.setTransparency(TransparencyAttrib.MAlpha)
            slice_np.setDepthTest(False)
            slice_np.setDepthWrite(False)
            self.slices.append(slice_np)

            lbl = DirectLabel(
                text=text,
                text_scale=_UNSELECTED_SCALE,
                text_fg=_UNSELECTED_FG,
                frameColor=(0, 0, 0, 0),
                pos=(
                    _LABEL_RADIUS * math.cos(centre),
                    0,
                    _LABEL_RADIUS * math.sin(centre),
                ),
                parent=self.root,
            )
            self.labels.append(lbl)
        self.update(None)

    def update(self, selected: int | None):
        """
        Highlight *selected* and dim all other slices.

        :param selected: Index of the slice the player is pointing at, or
            None when nothing is selected.
        """
        for i, (slice_np, lbl) in enumerate(zip(self.slices, self.labels)):
            active = i == selected
            slice_np.setColor(*(_SELECTED_SLICE_COLOR if active else _SLICE_COLOR))
            slice_np.node().setGeom(0, self.slice_geoms[i][1 if active else 0])
            slice_np.setBin("fixed", 1 if active else 0)
            lbl["text_scale"] = _UNSELECTED_SCALE * (
                _SELECTED_SLICE_SCALE if active else 1.0
            )
            lbl["text_fg"] = _SELECTED_FG if active else _UNSELECTED_FG

    def destroy(self):
        """Remove all Panda3D nodes."""
        for lbl in self.labels:
            lbl.destroy()
        self.labels = []
        self.slices = []
        self.slice_geoms = []
        self.root.removeNode()
        self.root = None


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class RadialMenuState(BaseState):
    """
    Overlay state for the radial menu.

    PAUSES_BELOW = False, so the game state below keeps simulating while the
    menu is open. This state owns only the visual overlay; input is handled by
    :class:`~space_flight.ui.input_context.RadialMenuInputContext`, pushed in
    :meth:`enter` and popped in :meth:`exit`.
    """

    PAUSES_BELOW: bool = False

    def __init__(
        self,
        app: SpaceFlightSimulator,
        on_select: Callable,
        slice_labels: list[str],
        min_magnitude: float = 0.3,
    ):
        """
        :param app: The simulator app.
        :param on_select: Called with the selected slice index (int) or
            None when the trigger is released without a valid direction.
        :param slice_labels: Display label for each slice. Also determines
            the number of slices, so it must be non-empty.
        :param min_magnitude: Direction vector magnitude below which no slice
            is considered selected.
        """
        super().__init__(app)
        self.slice_labels = slice_labels
        self.n_slices = len(slice_labels)
        self.on_select = on_select
        self.min_magnitude = min_magnitude
        self.visual: RadialMenuVisual | None = None

    def enter(self):
        # Resolve the trigger hardware names from the flight context bindings
        # so we don't duplicate them in the YAML.
        trigger_hw_names = bound_keys(self.app.bindings, "flight", "radial_menu")

        game_state = self.app.state_manager.stack[-2]
        self.visual = RadialMenuVisual(self.app, self.slice_labels)
        ctx = RadialMenuInputContext(
            game=game_state,
            n_slices=self.n_slices,
            on_select=self.on_select,
            trigger_hw_names=trigger_hw_names,
            on_hover=self.visual.update,
            min_magnitude=self.min_magnitude,
        )
        self.app.input_context_stack.push(ctx)

    def pause(self):
        pass

    def resume(self):
        pass

    def exit(self):
        self.app.input_context_stack.pop()
        if self.visual is not None:
            self.visual.destroy()
            self.visual = None
