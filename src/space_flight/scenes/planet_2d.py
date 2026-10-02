from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import numpy as np
import quaternion
from panda3d.core import CardMaker, NodePath, Quat, TransparencyAttrib

from space_flight import DATAFILES_PATH

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState


class Planet2D:
    def __init__(
        self,
        game: FlightState,
        scale: float = 5000,
        position: np.ndarray = np.array([0.0, 10000.0, 2000.0]),
        orientation: quaternion.quaternion = np.quaternion(1, 0, 0, 0),
        type: str = "terran",
    ):
        self.game = game
        self.id = uuid.uuid4()
        self.position = position
        cm = CardMaker("planet_card")
        cm.setFrame(-1, 1, -1, 1)

        root = NodePath("planet_node")
        root.reparentTo(game.root_node)
        root.setTransparency(TransparencyAttrib.MAlpha)
        root.setShaderOff()
        root.setLightOff()
        # A backdrop riding at a fixed offset, so its depth means nothing: draw it
        # with the background and write no depth. The default "transparent" bin
        # (sort 30) would draw it after, and over, the clouds (sort 25).
        root.setBin("background", 2)
        root.setDepthWrite(False)

        self.planet = root.attachNewNode(cm.generate())
        self.planet.setPos(position[0], position[1], position[2])
        self.planet.setTexture(
            game.app.loader.loadTexture(
                DATAFILES_PATH / f"sprites/planets_2d/{type}.png"
            )
        )
        self.planet.setScale(scale, scale, scale)
        self.planet.setQuat(
            Quat(
                orientation.w,
                orientation.x,
                orientation.y,
                orientation.z,
            )
        )

        self.game.method_lists[self.id] = [self.move_planet_task]

    def move_planet_task(self):
        new_position = self.position + self.game.player.pawn.position
        self.planet.setPos(new_position[0], new_position[1], new_position[2])

    def clean(self):
        """
        Cleans the Planet2D object
        """
        if self.game.method_lists:
            try:
                self.game.method_lists.pop(self.id)
            except KeyError:
                pass
        self.planet.removeNode()
        self.game = None
