import uuid

import numpy as np
import quaternion
from panda3d.core import CardMaker, NodePath, Quat, TransparencyAttrib

from space_flight import DATAFILES_PATH


class Planet2D:
    def __init__(
        self,
        game,
        scale: float = 5000,
        position: np.ndarray = np.array([0.0, 10000.0, 2000.0]),
        orientation: quaternion = np.quaternion(1, 0, 0, 0),
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
