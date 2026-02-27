import numpy as np
from panda3d.core import CardMaker, NodePath, TransparencyAttrib

from space_flight import DATAFILES_PATH


class Planet2D:
    def __init__(
        self,
        game,
        scale: float = 5000,
        position: np.ndarray = np.array([0.0, 10000.0, 0.0]),
        type: str = "terran",
    ):
        self.game = game
        self.position = position
        cm = CardMaker("planet_card")
        cm.setFrame(-1, 1, -1, 1)

        root = NodePath("planet_node")
        root.reparentTo(game.root_node)
        root.setTransparency(TransparencyAttrib.MAlpha)
        root.setLightOff()

        self.planet = root.attachNewNode(cm.generate())
        self.planet.setPos(position[0], position[1], position[2])
        self.planet.setTexture(
            game.app.loader.loadTexture(
                DATAFILES_PATH / f"sprites/planets_2d/{type}.png"
            )
        )
        self.planet.setScale(scale, scale, scale)

        # TODO add to game "tasks" instead of panda3d
        self.game.app.taskMgr.add(self.move_planet_task, "move_planet_task")

    def move_planet_task(self, task):
        new_position = self.position + self.game.player.ship.position
        self.planet.setPos(new_position[0], new_position[1], new_position[2])
        return task.cont
