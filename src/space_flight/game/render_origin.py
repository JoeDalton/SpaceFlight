"""
The floating render origin: keeps every coordinate in the scene graph small.

Gameplay works in world coordinates, in float64 (physics, AI, missions,
collisions as reported). Panda3D's scene graph is float32: a node at 10,000 km
from the world's origin (the moon, after a warp) would be placed to the metre at
best, its culling and its rendering jittering by as much.

So the game root (``game.root_node``) is not the world frame but a **local**
frame: local = world - :attr:`RenderOrigin.origin`, a float64 point kept near the
player. Every node under the root is placed in local coordinates, converted in
float64 (:meth:`RenderOrigin.to_local`); every position read from the scene
graph relative to the root is converted back (:meth:`RenderOrigin.to_world`).
Directions and rotations need no conversion: the two frames only differ by a
translation.

The origin is re-based onto the player whenever it strays more than
REBASE_DISTANCE_M from it. The root's direct children are then shifted with it,
so that a node placed once (a waypoint, a particle buffer) stays where it was in
the world; a node placed every frame (a ship) is placed afresh anyway.

Between re-bases, the root is offset by -(player - origin), a small vector, so
that the player, hence the camera, sits at render's origin (see
FlightState.recenter_render_origin): render's origin in the world frame is
always the player's position, which is what the scene's WorldBuilder world is
given.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

import numpy as np
from panda3d.core import Vec3

if TYPE_CHECKING:
    from panda3d.core import NodePath

#: The origin follows the player once it is this far from it. Local
#: coordinates near the player then stay under a few kilometres: about a
#: millimetre of float32 precision.
REBASE_DISTANCE_M = 5000.0


class RenderOrigin:
    """The float64 origin of the game root's frame (see the module)."""

    def __init__(self, root_node: NodePath):
        """
        :param root_node: The game root, whose frame this origin defines
        """
        self.root_node = root_node
        # The world position of the root's frame origin
        self.origin = np.zeros(3)
        # Called with the shift (new origin - old one) on each re-base
        self._on_rebase: list[Callable[[np.ndarray], None]] = []

    def to_local(self, world: Sequence[float]) -> np.ndarray:
        """
        :param world: A world position
        :return: It in the game root's frame, where nodes are placed
        """
        return np.asarray(world, dtype=float) - self.origin

    def to_world(self, local: Sequence[float]) -> np.ndarray:
        """
        :param local: A position in the game root's frame (e.g. a node's
            ``getPos(root_node)``, a collision's ``getSurfacePoint(root_node)``)
        :return: It in the world frame
        """
        return np.asarray(local, dtype=float) + self.origin

    def subscribe(self, on_rebase: Callable[[np.ndarray], None]):
        """
        :param on_rebase: Called with the origin's shift (a world vector) on
            each re-base, for what keeps coordinates outside the scene graph
        """
        self._on_rebase.append(on_rebase)

    def unsubscribe(self, on_rebase: Callable[[np.ndarray], None]):
        """:param on_rebase: A callable given to :meth:`subscribe`"""
        if on_rebase in self._on_rebase:
            self._on_rebase.remove(on_rebase)

    def follow(self, position: Sequence[float]) -> bool:
        """
        Keep render's origin on the player: re-base if it has strayed too far,
        then offset the root so the player sits at render's origin.

        :param position: The player's world position
        :return: Whether it re-based (the player's node, shifted in float32
            with the others, may then want placing afresh)
        """
        position = np.asarray(position, dtype=float)
        rebased = np.linalg.norm(position - self.origin) > REBASE_DISTANCE_M
        if rebased:
            self.rebase(position)
        x, y, z = self.to_local(position)
        self.root_node.setPos(-x, -y, -z)
        return bool(rebased)

    def rebase(self, new_origin: Sequence[float]):
        """
        Move the origin, keeping every node under the root where it is in the
        world: its direct children are shifted back by the move.

        :param new_origin: The new origin, world frame
        """
        new_origin = np.asarray(new_origin, dtype=float)
        shift = new_origin - self.origin
        self.origin = new_origin.copy()
        back = Vec3(*(-shift))
        for child in self.root_node.getChildren():
            child.setPos(child.getPos() + back)
        for on_rebase in list(self._on_rebase):
            on_rebase(shift)
