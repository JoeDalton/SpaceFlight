"""
Generic on-screen waypoint guidance for the player.

When the player is given a list of waypoints to follow, the *next* one is shown
in the world as a semi-transparent, targetable sphere. Reaching it reveals the
one after, and so on. The sphere is registered as a neutral (team 0) actor so the
player's normal targeting can lock onto it, while bots ignore it.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import numpy as np
from panda3d.core import TransparencyAttrib

if TYPE_CHECKING:
    from collections.abc import Sequence

    from space_flight.game.flight_state import FlightState

# A neutral, semi-transparent blue.
_MARKER_COLOR = (0.4, 0.8, 1.0, 0.35)

# Actor category used by the player's "Waypoints" target filter to single out
# waypoint markers (and by other filters to exclude them).
WAYPOINT_CATEGORY = "waypoint"


class WaypointMarker:
    """
    A targetable, semi-transparent sphere marking a single world position.

    Plays the role of a "pawn" in the targeting system: it is added to
    :class:`Interactions` as a team-0 actor and exposes the small attribute
    contract the targeting HUD and interaction maths read (``id``, ``team``,
    ``position``, ``speed``, ``forward``, ``is_dead``, ``parent.name``), plus a
    ``category`` of :data:`WAYPOINT_CATEGORY` so target filters can pick it out.

    :param game: The game/flight state
    :param radius_m: Visual radius of the sphere, in metres
    :param name: Display name shown by the target HUD
    """

    def __init__(
        self, game: FlightState, radius_m: float = 120.0, name: str = "Waypoint"
    ) -> None:
        self.game = game
        self.id = uuid.uuid4()
        self.name = name
        # The target HUD reads ``target.parent.name``; a marker is its own parent.
        self.parent = self
        self.team = 0  # neutral: bots never target it
        self.is_dead = False
        # Actor category: lets the "Waypoints" target filter pick this out (and
        # other filters exclude it).
        self.category = WAYPOINT_CATEGORY
        self.position = np.zeros(3)
        self.speed = np.zeros(3)
        self.forward = np.array([0.0, 1.0, 0.0])

        # A recoloured smiley sphere makes a cheap, always-available marker.
        # setTextureOff strips its baked-in face so only the flat colour shows.
        self.node = game.app.loader.loadModel("models/misc/smiley")
        self.node.setTextureOff(1)
        self.node.setColor(*_MARKER_COLOR)
        self.node.setTransparency(TransparencyAttrib.MAlpha)
        self.node.setScale(radius_m)
        self.node.reparentTo(game.root_node)
        self.node.hide()
        self.node.setShaderOff()
        self.node.setLightOff()

        game.interactions.add_actor(self)

    def move_to(self, position: Sequence[float]) -> None:
        """
        Move the marker to ``position`` (without changing its visibility).

        :param position: World-space position
        """
        self.position = np.asarray(position, dtype=float)
        self.node.setPos(*self.position)

    def set_visible(self, visible: bool) -> None:
        """
        Show or hide the marker.

        :param visible: Whether the sphere should be rendered
        """
        if visible:
            self.node.show()
        else:
            self.node.hide()

    def clean(self) -> None:
        """
        Remove the marker from the world and the targeting system.

        Idempotent: safe to call from both route completion and level teardown.
        """
        self.is_dead = True
        if self.node is not None:
            self.node.removeNode()
            self.node = None
        if self.game is not None:
            try:
                self.game.interactions.remove_actor(self)
            except (KeyError, AttributeError):
                pass
            self.game = None


class PlayerWaypoints:
    """
    Drives the player through an ordered list of waypoints.

    Shows the next waypoint as a :class:`WaypointMarker`; once the player flies
    within ``arrival_radius_m`` of it, the next one is revealed. When the last
    waypoint is reached the marker is removed.

    :param game: The game/flight state
    :param waypoints: Ordered list of world-space positions
    :param arrival_radius_m: How close the player must get to advance
    :param marker_radius_m: Visual radius of the marker sphere
    """

    def __init__(
        self,
        game: FlightState,
        waypoints: Sequence[Sequence[float]],
        arrival_radius_m: float = 350.0,
        marker_radius_m: float = 120.0,
    ) -> None:
        self.game = game
        self.waypoints = [np.asarray(w, dtype=float) for w in waypoints]
        self.arrival_radius_sq = arrival_radius_m * arrival_radius_m
        self.index = 0
        self._done = False
        self.marker = WaypointMarker(game, radius_m=marker_radius_m)

        self.id = uuid.uuid4()
        game.method_lists[self.id] = [self.update]
        self._show_current()

    def _show_current(self) -> None:
        """
        Position the marker on the current waypoint, or finish if past the last.
        """
        if self.index < len(self.waypoints):
            self.marker.move_to(self.waypoints[self.index])
        else:
            self._finish()

    def update(self) -> None:
        """
        Advance to the next waypoint once the player reaches the current one, and
        keep the marker visible only while the "Waypoints" target filter is on.
        """
        if self._done:
            return
        self.marker.set_visible(self.game.player.target_filter == "Waypoints")
        delta = self.game.player.pawn.position - self.waypoints[self.index]
        if float(delta @ delta) <= self.arrival_radius_sq:
            self.index += 1
            self._show_current()

    def _finish(self) -> None:
        """
        Mark the route complete and remove the marker.
        """
        self._done = True
        self.marker.clean()

    def clean(self) -> None:
        """
        Tear down the marker and stop updating.
        """
        self._done = True
        if self.marker is not None:
            self.marker.clean()
            self.marker = None
        if self.game is not None and self.game.method_lists is not None:
            self.game.method_lists.pop(self.id, None)
        self.game = None
