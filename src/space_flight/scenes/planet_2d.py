import random
from typing import List

import numpy as np
from direct.showbase.ShowBase import ShowBase
from direct.showbase.ShowBaseGlobal import globalClock
from panda3d.core import CardMaker, NodePath, TransparencyAttrib

from space_flight import DATAFILES_PATH



class Planet2D:
    def __init__(
        self,
        app: ShowBase,
        scale: float = 5000,
        position: np.ndarray = np.array([0.0, 10000.0, 0.0]),
        type: str = "terran",
    ):
        self.app = app
        self.position = position
        cm = CardMaker("planet_card")
        cm.setFrame(-1, 1, -1, 1)

        root = NodePath("planet_node")
        root.reparentTo(app.render)
        root.setTransparency(TransparencyAttrib.MAlpha)
        root.setLightOff()

        self.planet = root.attachNewNode(cm.generate())
        self.planet.setPos(position[0], position[1], position[2])
        self.planet.setTexture(
            app.loader.loadTexture(
                DATAFILES_PATH / f"models/planets_2d/{type}.png"
            )
        )
        self.planet.setScale(scale, scale, scale)

        self.app.taskMgr.add(self.move_planet_task, "move_planet_task")

    def move_planet_task(self, task):
        new_position = self.position + self.app.player.ship.position
        self.planet.setPos(new_position[0], new_position[1], new_position[2])
        print("=======================")
        print(self.app.player.ship.position)
        print(self.position)
        print(new_position)
        print("")
        return task.cont